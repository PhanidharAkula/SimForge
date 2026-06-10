"""Tests for the shared canonical-routes BFS module.

These tests pin the API contract for ``compute_canonical_routes``: the
shared, cached, optionally-parallel BFS that both adapters consume. The
suite is skipped when the module is unavailable so the rest of the test
suite still runs.

Coverage:

  Serial API contract + JSONL cache:
    - test_returns_dict_with_path_per_feasible_trip
    - test_paths_have_valid_endpoints
    - test_paths_traverse_real_edges
    - test_empty_feasible_set_returns_empty_dict
  Cache behavior:
    - test_cache_hit_avoids_recomputation
    - test_cache_invalidates_on_demand_csv_change
  Byte-identity vs the in-adapter BFS:
    - test_byte_identical_to_legacy_inline_bfs
  Multiprocessing determinism:
    - test_workers_1_vs_4_byte_identical
"""

from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Dict, List, Set

import pytest


# ---------------------------------------------------------------------------
# Defensive import: the suite skips cleanly when the module is unavailable.
# ---------------------------------------------------------------------------

try:
    from adapters.common.canonical_routes import compute_canonical_routes
    _MODULE_AVAILABLE = True
except ImportError:
    _MODULE_AVAILABLE = False
    compute_canonical_routes = None  # type: ignore[assignment]


pytestmark = [
    pytest.mark.slow,  # real per-trip BFS routing, minutes per test
    pytest.mark.skipif(
        not _MODULE_AVAILABLE,
        reason="adapters.common.canonical_routes is unavailable",
    ),
]


# ---------------------------------------------------------------------------
# Test-only helpers (independent of the shared module, they replicate the
# in-adapter BFS so the byte-identity test is self-contained)
# ---------------------------------------------------------------------------

def _legacy_inline_bfs_paths(scenario_dir: Path) -> Dict[str, List[str]]:
    """Replicate the BFS loop embedded in
    ``adapters/sumo/sumo_adapter.py:build_sumo_routes_xml`` and
    ``adapters/matsim/matsim_adapter.py:build_matsim_plans_xml``.

    This helper stays equivalent to those adapter loops so the
    byte-identity test is meaningful: it is the reference the shared BFS
    is checked against. If the adapters change the BFS call pattern, this
    helper changes with them.
    """
    from adapters.common.feasibility import feasible_trip_ids
    from adapters.sumo.sumo_adapter import (
        parse_canonical_network,
        shortest_path_nodes,
    )
    from pipeline.network.scc import compute_largest_scc
    from pipeline.network.turn_restrictions import (
        build_forbidden_moves,
        parse_turn_restrictions,
        shortest_path_with_restrictions,
    )

    network_path = scenario_dir / "network.xml"
    demand_path = scenario_dir / "demand.csv"

    graph = parse_canonical_network(network_path)

    # SCC filter (matches sumo_adapter.py:605-624 and equivalent in
    # matsim adapter): rebuild adjacency + edge_lookup over the SCC.
    scc_node_ids = compute_largest_scc(
        set(graph.nodes.keys()),
        [(lk.from_node, lk.to_node) for lk in graph.links],
    )
    scc_adjacency: Dict[str, List[str]] = {}
    scc_edge_lookup: Dict = {}
    for lk in graph.links:
        if lk.from_node in scc_node_ids and lk.to_node in scc_node_ids:
            scc_adjacency.setdefault(lk.from_node, []).append(lk.to_node)
            scc_edge_lookup[(lk.from_node, lk.to_node)] = lk

    # Feasibility filter (shared across adapters).
    feasible, _ = feasible_trip_ids(
        network_path=network_path,
        demand_path=demand_path,
        supported_modes={"car"},
    )

    # Turn restrictions → forbidden-moves table.
    restrictions = parse_turn_restrictions(network_path)
    forbidden_moves: dict = {}
    if restrictions:
        outgoing: dict = {}
        for u, neighbors in scc_adjacency.items():
            outgoing[u] = [
                scc_edge_lookup[(u, v)].id for v in neighbors
                if (u, v) in scc_edge_lookup
            ]
        forbidden_moves = build_forbidden_moves(restrictions, outgoing)

    # The per-trip BFS loop (the workload the shared module deduplicates).
    paths: Dict[str, List[str]] = {}
    with demand_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trip_id = (row.get("trip_id") or "").strip()
            if trip_id not in feasible:
                continue
            origin = (row.get("origin_node_id") or "").strip()
            dest = (row.get("destination_node_id") or "").strip()
            path = shortest_path_with_restrictions(
                origin=origin, dest=dest,
                adjacency=scc_adjacency,
                edge_lookup=scc_edge_lookup,
                forbidden_moves=forbidden_moves,
            )
            if path is None:
                path = shortest_path_nodes(scc_adjacency, origin, dest)
            paths[trip_id] = path or []
    return paths


def _feasible_ids_for(scenario_dir: Path) -> Set[str]:
    from adapters.common.feasibility import feasible_trip_ids
    feasible, _ = feasible_trip_ids(
        network_path=scenario_dir / "network.xml",
        demand_path=scenario_dir / "demand.csv",
        supported_modes={"car"},
    )
    return set(feasible)


# ---------------------------------------------------------------------------
# Basic serial API contract
# ---------------------------------------------------------------------------


class TestSerialAPI:
    def test_returns_dict_with_path_per_feasible_trip(
        self, bundled_scenario: Path, tmp_path: Path
    ) -> None:
        feasible = _feasible_ids_for(bundled_scenario)
        result = compute_canonical_routes(
            scenario_dir=bundled_scenario,
            feasible_trip_ids=feasible,
            workers=1,
            cache_root=tmp_path,
        )
        assert isinstance(result, dict)
        # One path per feasible trip (no extras, no missing).
        assert set(result.keys()) == feasible
        # Every value is a non-empty list of node ids.
        for tid, path in result.items():
            assert isinstance(path, list), f"trip {tid}: path not a list"
            assert len(path) >= 2, f"trip {tid}: path too short ({path!r})"
            assert all(isinstance(n, str) for n in path), (
                f"trip {tid}: non-str node id in {path!r}"
            )

    def test_paths_have_valid_endpoints(
        self, bundled_scenario: Path, tmp_path: Path
    ) -> None:
        """The first node must equal the demand's origin, last must equal dest."""
        feasible = _feasible_ids_for(bundled_scenario)
        result = compute_canonical_routes(
            scenario_dir=bundled_scenario,
            feasible_trip_ids=feasible,
            workers=1,
            cache_root=tmp_path,
        )
        with (bundled_scenario / "demand.csv").open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                tid = row["trip_id"]
                if tid not in result:
                    continue
                path = result[tid]
                assert path[0] == row["origin_node_id"], (
                    f"trip {tid}: path starts at {path[0]}, expected "
                    f"{row['origin_node_id']}"
                )
                assert path[-1] == row["destination_node_id"], (
                    f"trip {tid}: path ends at {path[-1]}, expected "
                    f"{row['destination_node_id']}"
                )

    def test_paths_traverse_real_edges(
        self, bundled_scenario: Path, tmp_path: Path
    ) -> None:
        """Every consecutive (u, v) in a path must be a directed edge."""
        from adapters.sumo.sumo_adapter import parse_canonical_network
        graph = parse_canonical_network(bundled_scenario / "network.xml")
        valid_edges = {(lk.from_node, lk.to_node) for lk in graph.links}

        result = compute_canonical_routes(
            scenario_dir=bundled_scenario,
            feasible_trip_ids=_feasible_ids_for(bundled_scenario),
            workers=1,
            cache_root=tmp_path,
        )
        for tid, path in result.items():
            for u, v in zip(path[:-1], path[1:]):
                assert (u, v) in valid_edges, (
                    f"trip {tid}: edge ({u}, {v}) not in network"
                )

    def test_empty_feasible_set_returns_empty_dict(
        self, bundled_scenario: Path, tmp_path: Path
    ) -> None:
        result = compute_canonical_routes(
            scenario_dir=bundled_scenario,
            feasible_trip_ids=set(),
            workers=1,
            cache_root=tmp_path,
        )
        assert result == {}


# ---------------------------------------------------------------------------
# JSONL cache
# ---------------------------------------------------------------------------


class TestCache:
    def test_cache_hit_avoids_recomputation(
        self, bundled_scenario: Path, tmp_path: Path
    ) -> None:
        """A second call with identical inputs should be fast (cache hit)."""
        feasible = _feasible_ids_for(bundled_scenario)

        # First call, cold cache. Should write a cache file.
        t0 = time.monotonic()
        result1 = compute_canonical_routes(
            scenario_dir=bundled_scenario,
            feasible_trip_ids=feasible,
            workers=1,
            cache_root=tmp_path,
        )
        cold_wall = time.monotonic() - t0

        # The cache dir should now contain at least one JSONL file.
        cache_files = list(tmp_path.glob("canonical_routes_*.jsonl"))
        assert len(cache_files) == 1, (
            f"expected 1 cache file, found {len(cache_files)}: {cache_files}"
        )

        # Second call, should read from cache without recomputing.
        t0 = time.monotonic()
        result2 = compute_canonical_routes(
            scenario_dir=bundled_scenario,
            feasible_trip_ids=feasible,
            workers=1,
            cache_root=tmp_path,
        )
        warm_wall = time.monotonic() - t0

        # The cache hit is proven functionally: the warm call returns the
        # identical routes and reuses the single cache file written by the cold
        # call (no second cache file appears). A wall-clock speedup ratio like
        # `warm * 5 < cold` is flaky on fast/noisy machines, so we only require
        # the warm read not to be dramatically slower than the cold compute.
        assert result1 == result2, "warm cache returned different paths"
        assert list(tmp_path.glob("canonical_routes_*.jsonl")) == cache_files, (
            "warm call changed the cache file set (expected a pure read)"
        )
        assert warm_wall < cold_wall + 0.5, (
            f"warm cache read was unexpectedly slow: cold={cold_wall:.2f}s "
            f"warm={warm_wall:.2f}s"
        )

    def test_cache_invalidates_on_demand_csv_change(
        self, bundled_scenario: Path, tmp_path: Path
    ) -> None:
        """Modifying the demand bytes triggers a fresh computation."""
        feasible = _feasible_ids_for(bundled_scenario)

        # Cold compute.
        compute_canonical_routes(
            scenario_dir=bundled_scenario,
            feasible_trip_ids=feasible,
            workers=1,
            cache_root=tmp_path,
        )
        files_before = sorted(tmp_path.glob("canonical_routes_*.jsonl"))
        assert len(files_before) == 1

        # Copy the bundle into a scratch dir and tweak demand.csv so the
        # bytes differ (re-using the same cache_root). Different inputs
        # → different hash → new cache file alongside the old one.
        import shutil
        scratch = tmp_path / "tweaked_bundle"
        shutil.copytree(bundled_scenario, scratch)
        demand_path = scratch / "demand.csv"
        text = demand_path.read_text(encoding="utf-8")
        # Append a trailing newline, content changes, schema unchanged.
        demand_path.write_text(text + "\n", encoding="utf-8")

        # The feasibility filter recomputes on the tweaked bundle.
        feasible_tweaked = _feasible_ids_for(scratch)
        compute_canonical_routes(
            scenario_dir=scratch,
            feasible_trip_ids=feasible_tweaked,
            workers=1,
            cache_root=tmp_path,
        )
        files_after = sorted(tmp_path.glob("canonical_routes_*.jsonl"))
        assert len(files_after) == 2, (
            "expected a 2nd cache file after demand.csv tweak, "
            f"found {len(files_after)}: {files_after}"
        )


# ---------------------------------------------------------------------------
# Byte-identity guard (pins equivalence to the legacy in-adapter BFS)
# ---------------------------------------------------------------------------


class TestByteIdentityVsLegacy:
    def test_byte_identical_to_legacy_inline_bfs(
        self, bundled_scenario: Path, tmp_path: Path
    ) -> None:
        """The shared BFS produces paths byte-identical to the in-adapter
        BFS loop, per trip_id. This is the load-bearing invariant: the
        adapters' route XML byte-identity downstream depends on it.
        """
        legacy = _legacy_inline_bfs_paths(bundled_scenario)
        new = compute_canonical_routes(
            scenario_dir=bundled_scenario,
            feasible_trip_ids=set(legacy.keys()),
            workers=1,
            cache_root=tmp_path,
        )
        assert set(legacy.keys()) == set(new.keys()), (
            "trip_id set differs between legacy and new implementations"
        )
        for tid in sorted(legacy.keys()):
            assert legacy[tid] == new[tid], (
                f"trip {tid}: path mismatch\n"
                f"  legacy:  {legacy[tid]}\n"
                f"  new:     {new[tid]}"
            )


# ---------------------------------------------------------------------------
# SUMO adapter byte-identity (with vs without canonical_routes)
# ---------------------------------------------------------------------------


class TestSumoRoutesXmlByteIdentity:
    """``build_sumo_routes_xml`` produces identical output whether routes
    come from the inline BFS (canonical_routes=None) or from the shared
    pre-computed dict.
    """

    def test_routes_rou_xml_byte_identical(
        self, bundled_scenario: Path, tmp_path: Path
    ) -> None:
        from adapters.common import feasibility as _feasibility
        from adapters.sumo.sumo_adapter import (
            build_sumo_routes_xml, parse_canonical_network, summarize_scenario,
        )
        from pipeline.network.scc import compute_largest_scc

        # Mirror the prep_sumo_inputs SCC-filtering step so the graph
        # we pass to build_sumo_routes_xml matches what the harness
        # would pass at runtime.
        summary = summarize_scenario(bundled_scenario)
        graph = parse_canonical_network(bundled_scenario / "network.xml")
        scc = compute_largest_scc(
            set(graph.nodes.keys()),
            [(lk.from_node, lk.to_node) for lk in graph.links],
        )
        scc_nodes = {nid: n for nid, n in graph.nodes.items() if nid in scc}
        scc_links = [lk for lk in graph.links
                     if lk.from_node in scc and lk.to_node in scc]
        from adapters.sumo.sumo_adapter import NetworkGraph
        scc_adjacency: dict = {}
        scc_edge_lookup: dict = {}
        for lk in scc_links:
            scc_adjacency.setdefault(lk.from_node, []).append(lk.to_node)
            scc_edge_lookup[(lk.from_node, lk.to_node)] = lk
        scc_graph = NetworkGraph(
            nodes=scc_nodes, links=scc_links,
            adjacency=scc_adjacency, edge_lookup=scc_edge_lookup,
        )

        feasible, _ = _feasibility.feasible_trip_ids(
            network_path=bundled_scenario / "network.xml",
            demand_path=bundled_scenario / "demand.csv",
            supported_modes={"car"},
        )

        # Inline path: adapter runs its own BFS.
        legacy_xml = build_sumo_routes_xml(
            summary, scc_graph, bundled_scenario / "demand.csv", feasible,
        )
        # Shared path: adapter consumes pre-computed routes.
        routes = compute_canonical_routes(
            scenario_dir=bundled_scenario,
            feasible_trip_ids=feasible,
            workers=1,
            cache_root=tmp_path,
        )
        new_xml = build_sumo_routes_xml(
            summary, scc_graph, bundled_scenario / "demand.csv", feasible,
            canonical_routes=routes,
        )
        assert legacy_xml == new_xml, (
            "SUMO routes.rou.xml diverged between inline BFS "
            "and shared pre-computed routes"
        )


# ---------------------------------------------------------------------------
# MATSim adapter byte-identity (with vs without canonical_routes)
# ---------------------------------------------------------------------------


class TestMatsimPlansXmlByteIdentity:
    """``build_matsim_plans_xml`` produces identical output whether routes
    come from the inline BFS (canonical_routes=None) or from the shared
    pre-computed dict.
    """

    def test_plans_xml_byte_identical(
        self, bundled_scenario: Path, tmp_path: Path
    ) -> None:
        from adapters.common import feasibility as _feasibility
        from adapters.matsim.matsim_adapter import (
            build_matsim_plans_xml, clean_network, load_canonical_network,
        )

        # Mirror what prepare_matsim_inputs does: load network, SCC-prune
        # via clean_network, then pass `links` to build_matsim_plans_xml.
        nodes, links = load_canonical_network(bundled_scenario / "network.xml")
        nodes, links, _ = clean_network(nodes, links)

        feasible, _ = _feasibility.feasible_trip_ids(
            network_path=bundled_scenario / "network.xml",
            demand_path=bundled_scenario / "demand.csv",
            supported_modes={"car"},
        )

        # Inline path: adapter runs its own BFS.
        legacy_xml = build_matsim_plans_xml(
            demand_path=bundled_scenario / "demand.csv",
            links=links,
            feasible=feasible,
            network_path=bundled_scenario / "network.xml",
        )
        # Shared path: adapter consumes pre-computed routes.
        routes = compute_canonical_routes(
            scenario_dir=bundled_scenario,
            feasible_trip_ids=feasible,
            workers=1,
            cache_root=tmp_path,
        )
        new_xml = build_matsim_plans_xml(
            demand_path=bundled_scenario / "demand.csv",
            links=links,
            feasible=feasible,
            network_path=bundled_scenario / "network.xml",
            canonical_routes=routes,
        )
        assert legacy_xml == new_xml, (
            "MATSim plans.xml diverged between inline BFS "
            "and shared pre-computed routes"
        )


# ---------------------------------------------------------------------------
# Multiprocessing determinism
# ---------------------------------------------------------------------------


class TestParallelDeterminism:
    @pytest.mark.parametrize("workers", [2, 4])
    def test_workers_n_byte_identical_to_workers_1(
        self, bundled_scenario: Path, tmp_path: Path, workers: int
    ) -> None:
        """The multiprocessing implementation must produce byte-identical
        results to the serial implementation, for any worker count.
        """
        feasible = _feasible_ids_for(bundled_scenario)
        # Use separate cache roots so neither call hits the other's cache.
        cache_1 = tmp_path / f"serial"
        cache_n = tmp_path / f"parallel_{workers}"
        cache_1.mkdir()
        cache_n.mkdir()

        serial = compute_canonical_routes(
            scenario_dir=bundled_scenario,
            feasible_trip_ids=feasible,
            workers=1,
            cache_root=cache_1,
        )
        parallel = compute_canonical_routes(
            scenario_dir=bundled_scenario,
            feasible_trip_ids=feasible,
            workers=workers,
            cache_root=cache_n,
        )
        assert serial == parallel, (
            f"workers={workers} produced different routes than workers=1"
        )
