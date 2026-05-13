"""Tests for the canonical routes shared BFS module (Phase 14).

These tests pin the API contract before the implementation lands. They
will be SKIPPED on commits 14.0 (when the module doesn't exist yet) and
land one-by-one as Phase 14.1-14.5 commits are pushed. The skip /
pass-status of each test acts as a per-commit progress marker.

Test ordering (matches the Phase 14 implementation plan, see
``doc/PHASE_14_DESIGN.md`` §3):

  14.1 (serial impl + JSONL cache):
    - test_returns_dict_with_path_per_feasible_trip
    - test_paths_have_valid_endpoints
    - test_paths_traverse_real_edges
    - test_empty_feasible_set_returns_empty_dict
  14.1 (cache):
    - test_cache_hit_avoids_recomputation
    - test_cache_invalidates_on_demand_csv_change
  14.x (byte-identity vs legacy in-adapter BFS):
    - test_byte_identical_to_legacy_inline_bfs
  14.5 (multiprocessing):
    - test_workers_1_vs_4_byte_identical
"""

from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Dict, List, Set

import pytest


# ---------------------------------------------------------------------------
# Defensive import — module doesn't exist yet at commit 14.0
# ---------------------------------------------------------------------------

try:
    from adapters.common.canonical_routes import compute_canonical_routes
    _MODULE_AVAILABLE = True
except ImportError:
    _MODULE_AVAILABLE = False
    compute_canonical_routes = None  # type: ignore[assignment]


pytestmark = pytest.mark.skipif(
    not _MODULE_AVAILABLE,
    reason=(
        "adapters.common.canonical_routes not yet implemented "
        "(Phase 14 in progress — see doc/PHASE_14_DESIGN.md)"
    ),
)


# ---------------------------------------------------------------------------
# Test-only helpers (don't depend on the new module — they replicate the
# legacy in-adapter BFS so the byte-identity test is self-contained)
# ---------------------------------------------------------------------------

def _legacy_inline_bfs_paths(scenario_dir: Path) -> Dict[str, List[str]]:
    """Replicate the BFS loop currently embedded in
    ``adapters/sumo/sumo_adapter.py:build_sumo_routes_xml`` and
    ``adapters/matsim/matsim_adapter.py:build_matsim_plans_xml``.

    The implementation here MUST stay equivalent to those adapter loops
    for the byte-identity test to be meaningful. If the adapters change
    the BFS call pattern, this helper changes with them.
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

    # The per-trip BFS loop (the workload Phase 14 deduplicates).
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
# Phase 14.1 — basic serial API contract
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
        from pipeline.network import parse_canonical_network
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
# Phase 14.1 — JSONL cache
# ---------------------------------------------------------------------------


class TestCache:
    def test_cache_hit_avoids_recomputation(
        self, bundled_scenario: Path, tmp_path: Path
    ) -> None:
        """A second call with identical inputs should be fast (cache hit)."""
        feasible = _feasible_ids_for(bundled_scenario)

        # First call — cold cache. Should write a cache file.
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

        # Second call — should read from cache without recomputing.
        t0 = time.monotonic()
        result2 = compute_canonical_routes(
            scenario_dir=bundled_scenario,
            feasible_trip_ids=feasible,
            workers=1,
            cache_root=tmp_path,
        )
        warm_wall = time.monotonic() - t0

        assert result1 == result2, "warm cache returned different paths"
        # Cache read should be at least an order of magnitude faster.
        # (chicago_1k_car: cold ~3s, warm ~0.05s.)
        assert warm_wall * 5 < cold_wall, (
            f"cache hit didn't speed up reads: cold={cold_wall:.2f}s "
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
        # Append a trailing newline — content changes, schema unchanged.
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
        """The new shared BFS must produce paths byte-identical to the
        legacy in-adapter BFS loop, per trip_id. This is the load-bearing
        invariant — adapters' route XML byte-identity downstream depends
        on this property.
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
# Phase 14.5 — multiprocessing determinism
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
