"""
Tests for the synthetic demand generators.

Covers the three generators (`UniformRandomGenerator`,
`GravityModelGenerator`, `PeakHourGenerator`), the `load_network_for_demand`
network parser, the top-level `generate_synthetic_demand` dispatch, and the
`write_demand_csv` schema contract.

Focus areas:

  - SCC restriction of origins *and* destinations, the [1.0.0] cross-engine
    fairness fix relies on this being true for the generator AND the
    adapter-side feasibility filter.
  - Deterministic seeding, two runs with the same seed on the same network
    must produce byte-identical demand.csv files.
  - Peak-hour temporal profile, the peak-hour generator must actually
    concentrate departures in the requested windows (we don't test exact
    fractions, just a strong-signal assertion).
  - Canonical CSV schema, columns and types match `canonical/schema/demand_v0.md`.
  - Error translation, missing / corrupt network paths produce clear errors.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from pipeline.demand.generate_synthetic_demand import (
    DemandGenerator,
    GravityModelGenerator,
    NetworkStats,
    PeakHourGenerator,
    UniformRandomGenerator,
    compute_reachability,
    compute_strongly_connected_component,
    generate_synthetic_demand,
    haversine_distance_km,
    load_network_for_demand,
    write_demand_csv,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


_NETWORK_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<network crs="EPSG:4326">
  <nodes>
{nodes}
  </nodes>
  <links>
{links}
  </links>
</network>
"""


def _write_grid_network(path: Path, n: int = 4) -> None:
    """Write an n-node ring network to `path`, SCC is the whole ring.

    Coordinates are spaced ~111 m apart (0.001 deg latitude) so the
    Haversine distances used by the gravity model land in a realistic range.
    """
    nodes = []
    for i in range(n):
        lon = -87.65 + 0.001 * i
        lat = 41.88
        nodes.append(f'    <node id="n{i}" x="{lon}" y="{lat}"/>')
    links = []
    # Bidirectional ring, guarantees the whole graph is one SCC.
    for i in range(n):
        j = (i + 1) % n
        links.append(f'    <link id="l{i}a" from="n{i}" to="n{j}" length_m="111"/>')
        links.append(f'    <link id="l{i}b" from="n{j}" to="n{i}" length_m="111"/>')
    path.write_text(
        _NETWORK_XML_TEMPLATE.format(nodes="\n".join(nodes), links="\n".join(links)),
        encoding="utf-8",
    )


def _write_partial_scc_network(path: Path) -> None:
    """Network where only nodes n0..n3 are in the SCC; n4 is a dead-end sink.

    Forces the generator to drop n4 from origin / destination sampling even
    though it's present in the network.
    """
    nodes = "\n".join(
        f'    <node id="n{i}" x="{-87.65 + 0.001 * i}" y="41.88"/>' for i in range(5)
    )
    # Ring 0–3 both directions + a one-way link 2→4 so n4 is reachable but not
    # part of any cycle.
    ring = []
    for i in range(4):
        j = (i + 1) % 4
        ring.append(f'    <link id="l{i}a" from="n{i}" to="n{j}" length_m="111"/>')
        ring.append(f'    <link id="l{i}b" from="n{j}" to="n{i}" length_m="111"/>')
    ring.append('    <link id="lsink" from="n2" to="n4" length_m="111"/>')
    path.write_text(
        _NETWORK_XML_TEMPLATE.format(nodes=nodes, links="\n".join(ring)),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


class TestGraphPrimitives:

    def test_compute_strongly_connected_component_bidirectional_ring(self):
        adjacency = {"n0": ["n1"], "n1": ["n2"], "n2": ["n3"], "n3": ["n0"]}
        reverse = {"n1": ["n0"], "n2": ["n1"], "n3": ["n2"], "n0": ["n3"]}
        scc = compute_strongly_connected_component(adjacency, reverse, ["n0", "n1", "n2", "n3"])
        assert scc == {"n0", "n1", "n2", "n3"}

    def test_compute_strongly_connected_component_picks_largest(self):
        # Two cycles: {a,b} of size 2 and {c,d,e} of size 3.
        adjacency = {"a": ["b"], "b": ["a"], "c": ["d"], "d": ["e"], "e": ["c"]}
        reverse = {"a": ["b"], "b": ["a"], "c": ["e"], "d": ["c"], "e": ["d"]}
        scc = compute_strongly_connected_component(adjacency, reverse, list("abcde"))
        assert scc == {"c", "d", "e"}

    def test_compute_reachability_transitive(self):
        adjacency = {"a": ["b"], "b": ["c"], "c": []}
        reach = compute_reachability(adjacency, ["a", "b", "c"])
        # Reachable excludes the starting node itself (see docstring).
        assert reach["a"] == {"b", "c"}
        assert reach["b"] == {"c"}
        assert reach["c"] == set()

    def test_haversine_distance_zero_for_same_point(self):
        assert haversine_distance_km((-87.65, 41.88), (-87.65, 41.88)) == 0.0

    def test_haversine_distance_is_symmetric(self):
        d_ab = haversine_distance_km((-87.65, 41.88), (-87.64, 41.89))
        d_ba = haversine_distance_km((-87.64, 41.89), (-87.65, 41.88))
        assert d_ab == pytest.approx(d_ba, rel=1e-12)


# ---------------------------------------------------------------------------
# load_network_for_demand
# ---------------------------------------------------------------------------


class TestLoadNetwork:

    def test_loads_ring_and_computes_full_scc(self, tmp_path):
        p = tmp_path / "network.xml"
        _write_grid_network(p, n=4)
        stats = load_network_for_demand(p)
        assert stats.total_nodes == 4
        assert stats.total_links == 8
        assert stats.strongly_connected_nodes == {"n0", "n1", "n2", "n3"}
        # Every SCC node can reach every other SCC node (reachability excludes self).
        for n in stats.strongly_connected_nodes:
            assert stats.reachable_from[n] == stats.strongly_connected_nodes - {n}

    def test_excludes_dead_end_from_scc(self, tmp_path):
        p = tmp_path / "network.xml"
        _write_partial_scc_network(p)
        stats = load_network_for_demand(p)
        assert stats.strongly_connected_nodes == {"n0", "n1", "n2", "n3"}
        assert "n4" not in stats.strongly_connected_nodes

    def test_missing_network_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Network file not found"):
            load_network_for_demand(tmp_path / "does_not_exist.xml")

    def test_corrupt_network_raises_value_error(self, tmp_path):
        p = tmp_path / "network.xml"
        p.write_text("<network><nodes><node id=broken", encoding="utf-8")
        with pytest.raises(ValueError, match="Failed to parse"):
            load_network_for_demand(p)


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------


@pytest.fixture
def ring_network(tmp_path) -> NetworkStats:
    p = tmp_path / "network.xml"
    _write_grid_network(p, n=8)
    return load_network_for_demand(p)


@pytest.fixture
def partial_scc_network(tmp_path) -> NetworkStats:
    p = tmp_path / "network.xml"
    _write_partial_scc_network(p)
    return load_network_for_demand(p)


class TestUniformRandomGenerator:

    def test_returns_valid_od_pairs(self, ring_network):
        gen = UniformRandomGenerator(ring_network, seed=42)
        for _ in range(50):
            o, d = gen.generate_od_pair()
            assert o in ring_network.strongly_connected_nodes
            assert d in ring_network.strongly_connected_nodes

    def test_excludes_dead_end_nodes(self, partial_scc_network):
        """n4 is reachable but outside the SCC, uniform sampler must skip it."""
        gen = UniformRandomGenerator(partial_scc_network, seed=42)
        origins, destinations = set(), set()
        for _ in range(200):
            o, d = gen.generate_od_pair()
            origins.add(o)
            destinations.add(d)
        assert "n4" not in origins
        assert "n4" not in destinations


class TestGravityModelGenerator:

    def test_od_pairs_within_scc(self, ring_network):
        gen = GravityModelGenerator(ring_network, seed=0)
        for _ in range(50):
            o, d = gen.generate_od_pair()
            assert o in ring_network.strongly_connected_nodes
            assert d in ring_network.strongly_connected_nodes

    def test_same_seed_same_output(self, ring_network):
        # Two identical generators must yield identical sequences.
        g1 = GravityModelGenerator(ring_network, seed=123)
        g2 = GravityModelGenerator(ring_network, seed=123)
        seq1 = [g1.generate_od_pair() for _ in range(25)]
        seq2 = [g2.generate_od_pair() for _ in range(25)]
        assert seq1 == seq2

    def test_different_seed_different_output(self, ring_network):
        g1 = GravityModelGenerator(ring_network, seed=1)
        g2 = GravityModelGenerator(ring_network, seed=2)
        seq1 = [g1.generate_od_pair() for _ in range(25)]
        seq2 = [g2.generate_od_pair() for _ in range(25)]
        # Strong probabilistic guarantee: at least one element should differ
        # between two independent seeded streams over 25 samples on an 8-ring.
        assert seq1 != seq2


class TestPeakHourGenerator:

    def test_departures_concentrate_in_peak(self, ring_network):
        """At peak_fraction=0.7, ≥60 % of departures must fall in the peaks."""
        gen = PeakHourGenerator(
            ring_network,
            seed=42,
            morning_peak=(7 * 3600, 9 * 3600),
            evening_peak=(17 * 3600, 19 * 3600),
            peak_fraction=0.7,
        )
        samples = [gen.generate_departure_time(0, 24 * 3600) for _ in range(2000)]
        in_peak = sum(
            1 for t in samples
            if (7 * 3600 <= t < 9 * 3600) or (17 * 3600 <= t < 19 * 3600)
        )
        assert in_peak / len(samples) >= 0.6


# ---------------------------------------------------------------------------
# write_demand_csv
# ---------------------------------------------------------------------------


def test_write_demand_csv_emits_canonical_header(tmp_path):
    out = tmp_path / "demand.csv"
    trips = [{
        "trip_id": "t0",
        "origin_node_id": "n0",
        "destination_node_id": "n3",
        "departure_time_s": 123,
        "mode": "car",
    }]
    write_demand_csv(trips, out)

    with out.open() as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == [
            "trip_id", "origin_node_id", "destination_node_id",
            "departure_time_s", "mode",
        ]
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["trip_id"] == "t0"
    assert rows[0]["mode"] == "car"


# ---------------------------------------------------------------------------
# generate_synthetic_demand end-to-end
# ---------------------------------------------------------------------------


class TestGenerateSyntheticDemand:

    def test_end_to_end_gravity(self, tmp_path):
        net_path = tmp_path / "network.xml"
        _write_grid_network(net_path, n=8)
        out_path = tmp_path / "demand.csv"

        result = generate_synthetic_demand(
            network_path=net_path,
            output_path=out_path,
            num_trips=20,
            strategy="gravity",
            seed=42,
            horizon_start=0,
            horizon_end=3600,
        )
        assert result["trip_count"] == 20
        assert result["strategy"] == "gravity"
        assert out_path.is_file()

        # Every emitted trip must reference nodes that exist in the network.
        valid_nodes = {f"n{i}" for i in range(8)}
        with out_path.open() as f:
            for row in csv.DictReader(f):
                assert row["origin_node_id"] in valid_nodes
                assert row["destination_node_id"] in valid_nodes
                assert row["origin_node_id"] != row["destination_node_id"]
                assert 0 <= int(row["departure_time_s"]) < 3600

    def test_determinism_across_runs(self, tmp_path):
        """Two generate_synthetic_demand calls with the same seed must yield
        byte-identical demand.csv files, this is the guarantee adapters rely
        on to produce byte-identical SCC-filtered skip lists."""
        net_path = tmp_path / "network.xml"
        _write_grid_network(net_path, n=8)

        out_a = tmp_path / "a.csv"
        out_b = tmp_path / "b.csv"
        kwargs = dict(
            num_trips=50,
            strategy="gravity",
            seed=2026,
            horizon_start=0,
            horizon_end=3600,
        )
        generate_synthetic_demand(net_path, out_a, **kwargs)
        generate_synthetic_demand(net_path, out_b, **kwargs)
        assert out_a.read_bytes() == out_b.read_bytes()

    def test_rejects_unknown_strategy(self, tmp_path):
        net_path = tmp_path / "network.xml"
        _write_grid_network(net_path, n=4)
        with pytest.raises(ValueError, match="Unknown strategy"):
            generate_synthetic_demand(
                network_path=net_path,
                output_path=tmp_path / "demand.csv",
                num_trips=10,
                strategy="not-a-real-strategy",
            )

    def test_gravity_restricts_to_scc(self, tmp_path):
        """n4 is outside the SCC, no emitted trip may reference it."""
        net_path = tmp_path / "network.xml"
        _write_partial_scc_network(net_path)
        out_path = tmp_path / "demand.csv"

        generate_synthetic_demand(
            network_path=net_path,
            output_path=out_path,
            num_trips=100,
            strategy="gravity",
            seed=7,
        )
        with out_path.open() as f:
            for row in csv.DictReader(f):
                assert row["origin_node_id"] != "n4"
                assert row["destination_node_id"] != "n4"


# ---------------------------------------------------------------------------
# Base class contract
# ---------------------------------------------------------------------------


def test_base_demand_generator_raises_not_implemented(ring_network):
    base = DemandGenerator(ring_network, seed=0)
    with pytest.raises(NotImplementedError):
        base.generate_od_pair()
