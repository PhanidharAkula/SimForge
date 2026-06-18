"""
Tests for the DTALite adapter.

`prepare_dtalite_inputs` produces GMNS node.csv / link.csv / demand.csv plus
settings.csv / settings.yml from a canonical scenario. These tests exercise
input preparation, schema fidelity, determinism, and output parsing, no
DTALite binary is required for the fast tier. The single binary-driven
smoke test is gated on `is_dtalite_available()` and skips when path4gmns
is not installed.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from adapters.dtalite.dtalite_adapter import (
    DTALiteConfig,
    _DEFAULT_CAPACITY_VPH_PER_LANE,
    _DTALITE_MIN_SPEED_KMH,
    _M_TO_KM,
    _MS_TO_KMH,
    _to_int_index,
    collect_demand_node_ids,
    find_dtalite_binary,
    is_dtalite_available,
    parse_dtalite_output,
    prepare_dtalite_inputs,
    write_dtalite_demand_csv,
    write_dtalite_link_csv,
    write_dtalite_node_csv,
    write_dtalite_settings_csv,
    write_dtalite_settings_yml,
)
from adapters.sumo.sumo_adapter import (
    CanonicalLink,
    CanonicalNode,
    NetworkGraph,
)

from .conftest import directory_sha256


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestToIntIndex:
    @pytest.mark.parametrize("canonical_id, expected", [
        ("n0", 0),
        ("n1", 1),
        ("n12345", 12345),
        ("l456", 456),
        ("12", 12),
    ])
    def test_strips_prefix(self, canonical_id, expected):
        assert _to_int_index(canonical_id) == expected

    def test_rejects_garbage(self):
        with pytest.raises(ValueError, match="Cannot map"):
            _to_int_index("not_a_node")
        with pytest.raises(ValueError, match="Cannot map"):
            _to_int_index("")


class TestDTALiteConfig:
    def test_defaults(self):
        cfg = DTALiteConfig()
        assert cfg.iterations == 5
        assert cfg.column_updating_iterations == 5
        assert cfg.simulation_output == 1
        assert cfg.demand_period_start_hhmm == "0700"
        assert cfg.demand_period_end_hhmm == "0800"

    def test_to_dict(self):
        cfg = DTALiteConfig(iterations=10, column_updating_iterations=3)
        d = cfg.to_dict()
        assert d["iterations"] == 10
        assert d["column_updating_iterations"] == 3


# ---------------------------------------------------------------------------
# Synthetic graph fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_graph() -> NetworkGraph:
    """3-node, 3-edge graph + one self-loop (must be dropped)."""
    nodes = {
        "n0": CanonicalNode(id="n0", x=-87.65, y=41.88),
        "n1": CanonicalNode(id="n1", x=-87.64, y=41.89),
        "n2": CanonicalNode(id="n2", x=-87.63, y=41.90),
    }
    links = [
        CanonicalLink(id="l0", from_node="n0", to_node="n1",
                      length=120.5, speed=13.9, lanes=2),
        CanonicalLink(id="l1", from_node="n1", to_node="n2",
                      length=80.0, speed=11.1, lanes=1),
        CanonicalLink(id="l2", from_node="n2", to_node="n0",
                      length=200.0, speed=22.2, lanes=3),
        CanonicalLink(id="l3", from_node="n1", to_node="n1",
                      length=10.0, speed=5.0, lanes=1),
    ]
    return NetworkGraph(nodes=nodes, links=links, adjacency={}, edge_lookup={})


# ---------------------------------------------------------------------------
# Node CSV
# ---------------------------------------------------------------------------


class TestNodeCsv:
    def test_writes_header_and_rows(self, tiny_graph, tmp_path):
        out = tmp_path / "node.csv"
        n = write_dtalite_node_csv(tiny_graph, out)
        assert n == 3
        header = out.read_text(encoding="utf-8").splitlines()[0]
        for col in ("node_id", "zone_id", "x_coord", "y_coord",
                    "production", "attraction"):
            assert col in header.split(",")

    def test_uses_lf_line_endings(self, tiny_graph, tmp_path):
        out = tmp_path / "node.csv"
        write_dtalite_node_csv(tiny_graph, out)
        assert b"\r\n" not in out.read_bytes()

    def test_zone_id_defaults_to_node_id_when_no_filter(self, tiny_graph, tmp_path):
        # zone_node_ids=None means every node is a zone (test fixture mode).
        out = tmp_path / "node.csv"
        write_dtalite_node_csv(tiny_graph, out)
        with out.open() as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            assert r["zone_id"] == r["node_id"]
            assert r["production"] == "1"
            assert r["attraction"] == "1"

    def test_zone_id_demand_filtered(self, tiny_graph, tmp_path):
        # Pass only n0 + n2 as zones; n1 should be transit-only.
        out = tmp_path / "node.csv"
        write_dtalite_node_csv(tiny_graph, out, zone_node_ids={"n0", "n2"})
        with out.open() as f:
            rows = {r["node_id"]: r for r in csv.DictReader(f)}
        assert rows["0"]["zone_id"] == "0"
        assert rows["1"]["zone_id"] == ""
        assert rows["2"]["zone_id"] == "2"
        assert rows["1"]["production"] == "0"
        assert rows["1"]["attraction"] == "0"

    def test_coordinates_round_to_six_decimals(self, tiny_graph, tmp_path):
        out = tmp_path / "node.csv"
        write_dtalite_node_csv(tiny_graph, out)
        with out.open() as f:
            for r in csv.DictReader(f):
                assert len(r["x_coord"].split(".")[-1]) == 6
                assert len(r["y_coord"].split(".")[-1]) == 6


# ---------------------------------------------------------------------------
# Link CSV
# ---------------------------------------------------------------------------


class TestLinkCsv:
    def test_writes_header(self, tiny_graph, tmp_path):
        out = tmp_path / "link.csv"
        write_dtalite_link_csv(tiny_graph, out)
        header = out.read_text(encoding="utf-8").splitlines()[0]
        for col in ("link_id", "from_node_id", "to_node_id", "length",
                    "lanes", "free_speed", "capacity",
                    "VDF_fftt1", "VDF_alpha1", "VDF_beta1"):
            assert col in header.split(",")

    def test_uses_lf_line_endings(self, tiny_graph, tmp_path):
        out = tmp_path / "link.csv"
        write_dtalite_link_csv(tiny_graph, out)
        assert b"\r\n" not in out.read_bytes()

    def test_drops_self_loops(self, tiny_graph, tmp_path):
        out = tmp_path / "link.csv"
        n = write_dtalite_link_csv(tiny_graph, out)
        # 4 input links - 1 self-loop = 3 output rows
        assert n == 3
        with out.open() as f:
            for r in csv.DictReader(f):
                assert r["from_node_id"] != r["to_node_id"]

    def test_length_converted_to_km(self, tiny_graph, tmp_path):
        out = tmp_path / "link.csv"
        write_dtalite_link_csv(tiny_graph, out)
        with out.open() as f:
            data = sorted(csv.DictReader(f), key=lambda r: int(r["link_id"]))
        # 120.5 m → 0.1205 km
        assert float(data[0]["length"]) == pytest.approx(0.1205, abs=1e-5)
        assert float(data[1]["length"]) == pytest.approx(0.080, abs=1e-5)
        assert float(data[2]["length"]) == pytest.approx(0.200, abs=1e-5)

    def test_speed_converted_to_kmh(self, tiny_graph, tmp_path):
        out = tmp_path / "link.csv"
        write_dtalite_link_csv(tiny_graph, out)
        with out.open() as f:
            data = sorted(csv.DictReader(f), key=lambda r: int(r["link_id"]))
        # 13.9 m/s × 3.6 ≈ 50.0 km/h (formatted at 1 decimal)
        assert float(data[0]["free_speed"]) == pytest.approx(13.9 * _MS_TO_KMH, abs=0.05)

    def test_capacity_per_lane(self, tiny_graph, tmp_path):
        out = tmp_path / "link.csv"
        write_dtalite_link_csv(tiny_graph, out)
        with out.open() as f:
            data = sorted(csv.DictReader(f), key=lambda r: int(r["link_id"]))
        # link 0 has 2 lanes → 3600 vph
        assert int(data[0]["capacity"]) == 2 * _DEFAULT_CAPACITY_VPH_PER_LANE
        assert int(data[1]["capacity"]) == 1 * _DEFAULT_CAPACITY_VPH_PER_LANE
        assert int(data[2]["capacity"]) == 3 * _DEFAULT_CAPACITY_VPH_PER_LANE

    def test_vdf_fftt_matches_length_over_speed(self, tiny_graph, tmp_path):
        out = tmp_path / "link.csv"
        write_dtalite_link_csv(tiny_graph, out)
        with out.open() as f:
            data = sorted(csv.DictReader(f), key=lambda r: int(r["link_id"]))
        # 120.5 m at 13.9 m/s = 8.67 s = 0.1445 min
        expected = (120.5 * _M_TO_KM) / (13.9 * _MS_TO_KMH) * 60.0
        assert float(data[0]["VDF_fftt1"]) == pytest.approx(expected, abs=1e-3)

    def test_drops_sub_meter_edges(self, tmp_path):
        nodes = {f"n{i}": CanonicalNode(id=f"n{i}", x=i, y=i) for i in range(3)}
        links = [
            CanonicalLink(id="l0", from_node="n0", to_node="n1",
                          length=0.5, speed=10, lanes=1),
            CanonicalLink(id="l1", from_node="n1", to_node="n2",
                          length=120.0, speed=10, lanes=1),
        ]
        graph = NetworkGraph(nodes=nodes, links=links, adjacency={}, edge_lookup={})
        out = tmp_path / "link.csv"
        n = write_dtalite_link_csv(graph, out)
        assert n == 1, "sub-meter link should have been dropped"

    def test_lanes_clamped_to_at_least_1(self, tmp_path):
        nodes = {"n0": CanonicalNode(id="n0", x=0, y=0),
                 "n1": CanonicalNode(id="n1", x=1, y=1)}
        link = CanonicalLink(id="l0", from_node="n0", to_node="n1",
                             length=100, speed=10, lanes=0)
        graph = NetworkGraph(nodes=nodes, links=[link], adjacency={}, edge_lookup={})
        out = tmp_path / "link.csv"
        write_dtalite_link_csv(graph, out)
        with out.open() as f:
            row = next(csv.DictReader(f))
        assert int(row["lanes"]) == 1

    def test_speed_floor_applied(self, tmp_path):
        # Sub-walking-pace speed gets floored to keep BPR numerical stability.
        nodes = {"n0": CanonicalNode(id="n0", x=0, y=0),
                 "n1": CanonicalNode(id="n1", x=1, y=1)}
        link = CanonicalLink(id="l0", from_node="n0", to_node="n1",
                             length=100, speed=0.1, lanes=1)  # 0.36 km/h
        graph = NetworkGraph(nodes=nodes, links=[link], adjacency={}, edge_lookup={})
        out = tmp_path / "link.csv"
        write_dtalite_link_csv(graph, out)
        with out.open() as f:
            row = next(csv.DictReader(f))
        assert float(row["free_speed"]) >= _DTALITE_MIN_SPEED_KMH


# ---------------------------------------------------------------------------
# Demand CSV + zone collection
# ---------------------------------------------------------------------------


class TestDemandCsv:
    def _write_canonical_demand(self, path: Path):
        path.write_text(
            "trip_id,origin_node_id,destination_node_id,departure_time_s,mode\n"
            "trip_a,n0,n1,25200,car\n"
            "trip_b,n1,n2,25500,car\n"
            "trip_c,n0,n1,25800,car\n"  # same OD as trip_a → aggregates
            "trip_d,n0,n0,26000,car\n"  # intra-zonal → dropped
            "trip_e,n2,n0,26100,car\n",
            encoding="utf-8",
        )

    def test_aggregates_by_od(self, tmp_path):
        demand = tmp_path / "demand.csv"
        self._write_canonical_demand(demand)
        out = tmp_path / "od.csv"
        n = write_dtalite_demand_csv(
            demand, out, feasible_trip_ids={"trip_a", "trip_b", "trip_c", "trip_e"}
        )
        # 4 feasible trips, 3 unique OD pairs (trip_a + trip_c collapse)
        assert n == 3
        with out.open() as f:
            rows = list(csv.DictReader(f))
        od_volume = {(r["o_zone_id"], r["d_zone_id"]): int(r["volume"]) for r in rows}
        assert od_volume[("0", "1")] == 2
        assert od_volume[("1", "2")] == 1
        assert od_volume[("2", "0")] == 1

    def test_only_emits_feasible_trips(self, tmp_path):
        demand = tmp_path / "demand.csv"
        self._write_canonical_demand(demand)
        out = tmp_path / "od.csv"
        n = write_dtalite_demand_csv(demand, out, feasible_trip_ids={"trip_a"})
        assert n == 1

    def test_drops_intra_zonal(self, tmp_path):
        # trip_d is n0→n0, must NOT appear even when feasible.
        demand = tmp_path / "demand.csv"
        self._write_canonical_demand(demand)
        out = tmp_path / "od.csv"
        write_dtalite_demand_csv(
            demand, out, feasible_trip_ids={"trip_a", "trip_d"}
        )
        with out.open() as f:
            rows = list(csv.DictReader(f))
        assert all(r["o_zone_id"] != r["d_zone_id"] for r in rows)

    def test_uses_lf_line_endings(self, tmp_path):
        demand = tmp_path / "demand.csv"
        self._write_canonical_demand(demand)
        out = tmp_path / "od.csv"
        write_dtalite_demand_csv(demand, out, feasible_trip_ids={"trip_a"})
        assert b"\r\n" not in out.read_bytes()

    def test_columns_match_gmns(self, tmp_path):
        demand = tmp_path / "demand.csv"
        self._write_canonical_demand(demand)
        out = tmp_path / "od.csv"
        write_dtalite_demand_csv(demand, out, feasible_trip_ids={"trip_a"})
        header = out.read_text().splitlines()[0]
        assert header == "o_zone_id,d_zone_id,volume"


class TestCollectDemandNodeIds:
    def test_picks_up_origin_and_destination(self, tmp_path):
        demand = tmp_path / "demand.csv"
        demand.write_text(
            "trip_id,origin_node_id,destination_node_id,departure_time_s,mode\n"
            "t0,n0,n5,25200,car\n"
            "t1,n7,n5,25500,car\n",
            encoding="utf-8",
        )
        nodes = collect_demand_node_ids(demand, feasible_trip_ids={"t0", "t1"})
        assert nodes == {"n0", "n5", "n7"}

    def test_respects_feasibility_filter(self, tmp_path):
        demand = tmp_path / "demand.csv"
        demand.write_text(
            "trip_id,origin_node_id,destination_node_id,departure_time_s,mode\n"
            "t0,n0,n5,25200,car\n"
            "t1,n7,n9,25500,car\n",
            encoding="utf-8",
        )
        nodes = collect_demand_node_ids(demand, feasible_trip_ids={"t0"})
        assert nodes == {"n0", "n5"}


# ---------------------------------------------------------------------------
# Settings writers
# ---------------------------------------------------------------------------


class TestSettingsWriters:
    def test_yml_has_required_sections(self, tmp_path):
        cfg = DTALiteConfig()
        out = tmp_path / "settings.yml"
        write_dtalite_settings_yml(out, cfg)
        text = out.read_text(encoding="utf-8")
        assert "agents:" in text
        assert "demand_periods:" in text
        assert "demand_files:" in text
        assert "demand.csv" in text

    def test_csv_has_required_sections(self, tmp_path):
        cfg = DTALiteConfig()
        out = tmp_path / "settings.csv"
        write_dtalite_settings_csv(out, cfg)
        text = out.read_text(encoding="utf-8")
        for section in (
            "[assignment]", "[agent_type]", "[link_type]",
            "[demand_period]", "[demand_file_list]",
        ):
            assert section in text

    def test_csv_period_window_uses_underscores(self, tmp_path):
        # DTALite C++ binary expects HHMM_HHMM (underscore separator)
        # in settings.csv, not the HHMM-HHMM (hyphen) used in YAML.
        cfg = DTALiteConfig(demand_period_start_hhmm="0600",
                            demand_period_end_hhmm="0900")
        out = tmp_path / "settings.csv"
        write_dtalite_settings_csv(out, cfg)
        assert "0600_0900" in out.read_text(encoding="utf-8")

    def test_csv_iteration_counts_propagate(self, tmp_path):
        cfg = DTALiteConfig(iterations=12, column_updating_iterations=8)
        out = tmp_path / "settings.csv"
        write_dtalite_settings_csv(out, cfg)
        text = out.read_text(encoding="utf-8")
        assert ",12," in text or ",12\n" in text
        assert ",8," in text or ",8\n" in text


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@pytest.mark.determinism
class TestDeterminism:
    def test_full_output_tree_byte_identical(self, bundled_scenario, tmp_path):
        run1 = tmp_path / "run1"
        run2 = tmp_path / "run2"
        run1.mkdir()
        run2.mkdir()
        prepare_dtalite_inputs(bundled_scenario, run1)
        prepare_dtalite_inputs(bundled_scenario, run2)
        h1 = directory_sha256(run1, exclude_patterns=["feasibility_report.json"])
        h2 = directory_sha256(run2, exclude_patterns=["feasibility_report.json"])
        assert set(h1) == set(h2)
        for name in h1:
            assert h1[name] == h2[name], f"{name} differs across re-runs"


# ---------------------------------------------------------------------------
# End-to-end prepare on bundled scenario
# ---------------------------------------------------------------------------


class TestPrepareDTALiteInputs:
    def test_produces_expected_layout(self, bundled_scenario, tmp_path):
        out = tmp_path / "dtalite_out"
        summary = prepare_dtalite_inputs(bundled_scenario, out)
        assert summary.scenario_id == bundled_scenario.name
        assert summary.node_count > 0
        assert summary.link_count > 0
        assert summary.trip_count > 0
        for f in ("settings.yml", "settings.csv", "node.csv", "link.csv",
                  "demand.csv", "feasibility_report.json"):
            assert (out / f).is_file(), f"missing {f}"

    def test_zones_are_demand_driven(self, bundled_scenario, tmp_path):
        # Zone count should be << node count for a sparse-demand bundle.
        out = tmp_path / "dtalite_out"
        prepare_dtalite_inputs(bundled_scenario, out)
        with (out / "node.csv").open() as f:
            rows = list(csv.DictReader(f))
        zones = sum(1 for r in rows if (r.get("zone_id") or "").strip())
        assert 0 < zones < len(rows), (
            f"zone count should be a strict subset of nodes; got {zones}/{len(rows)}"
        )


# ---------------------------------------------------------------------------
# Output parsing, synthetic agent.csv
# ---------------------------------------------------------------------------


class TestParseOutput:
    def _write_agent_csv(self, dir_path: Path, rows: list[dict]):
        path = dir_path / "agent.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "agent_id", "o_zone_id", "d_zone_id", "path_id",
                    "agent_type", "demand_period", "volume", "toll",
                    "travel_time", "distance", "node_sequence", "link_sequence",
                ],
            )
            w.writeheader()
            for r in rows:
                w.writerow(r)
        return path

    def test_returns_none_when_no_output(self, tmp_path):
        assert parse_dtalite_output(tmp_path) is None

    def test_minutes_to_seconds(self, tmp_path):
        # travel_time=2.0 min × 60 = 120 s
        self._write_agent_csv(tmp_path, [
            dict(agent_id=1, o_zone_id=1, d_zone_id=2, path_id=0,
                 agent_type="p", demand_period="AM", volume=1, toll=0,
                 travel_time=2.0, distance=1.5,
                 node_sequence="1;2;", link_sequence="1;"),
        ])
        stats = parse_dtalite_output(tmp_path)
        assert stats.mean_travel_time_s == pytest.approx(120.0)
        assert stats.mean_distance_m == pytest.approx(1500.0)

    def test_volume_expansion(self, tmp_path):
        # One row with volume=3 should count as 3 vehicle-trips.
        self._write_agent_csv(tmp_path, [
            dict(agent_id=1, o_zone_id=1, d_zone_id=2, path_id=0,
                 agent_type="p", demand_period="AM", volume=3, toll=0,
                 travel_time=1.0, distance=1.0,
                 node_sequence="", link_sequence=""),
        ])
        stats = parse_dtalite_output(tmp_path)
        assert stats.completed_count == 3
        assert stats.trip_count == 3

    def test_skips_zero_travel_time_in_stats(self, tmp_path):
        # Zero-tt rows still count toward trip_count but not completed_count.
        self._write_agent_csv(tmp_path, [
            dict(agent_id=1, o_zone_id=1, d_zone_id=2, path_id=0,
                 agent_type="p", demand_period="AM", volume=1, toll=0,
                 travel_time=0, distance=0, node_sequence="", link_sequence=""),
            dict(agent_id=2, o_zone_id=3, d_zone_id=4, path_id=0,
                 agent_type="p", demand_period="AM", volume=1, toll=0,
                 travel_time=3.0, distance=2.0,
                 node_sequence="", link_sequence=""),
        ])
        stats = parse_dtalite_output(tmp_path)
        assert stats.trip_count == 2
        assert stats.completed_count == 1
        assert stats.mean_travel_time_s == 180.0

    def test_p95_uses_sorted_index(self, tmp_path):
        # 100 evenly spaced travel times → P95 = the 95th-percentile entry.
        rows = [
            dict(agent_id=i, o_zone_id=i, d_zone_id=i + 1, path_id=0,
                 agent_type="p", demand_period="AM", volume=1, toll=0,
                 travel_time=float(i + 1), distance=0,
                 node_sequence="", link_sequence="")
            for i in range(100)
        ]
        self._write_agent_csv(tmp_path, rows)
        stats = parse_dtalite_output(tmp_path)
        # Sorted travel_times (in seconds) = 60, 120, ..., 6000.
        # P95 index = floor(0.95 × 99) = 94 → value (95)*60 = 5700.
        assert stats.p95_travel_time_s == 5700.0


# ---------------------------------------------------------------------------
# Binary discovery
# ---------------------------------------------------------------------------


class TestBinaryDiscovery:
    def test_is_dtalite_available_returns_bool(self):
        result = is_dtalite_available()
        assert isinstance(result, bool)

    def test_find_binary_returns_path_or_none(self):
        result = find_dtalite_binary()
        assert result is None or isinstance(result, Path)

    def test_find_binary_is_consistent_with_is_available(self):
        # If is_dtalite_available() is True, find_dtalite_binary() must
        # return a real file.
        if is_dtalite_available():
            binary = find_dtalite_binary()
            assert binary is not None
            assert binary.is_file()


# ---------------------------------------------------------------------------
# End-to-end smoke (gated on path4gmns availability)
# ---------------------------------------------------------------------------


@pytest.mark.slow  # runs a real DTALite engine subprocess
@pytest.mark.skipif(
    not is_dtalite_available(),
    reason="path4gmns not installed (uv pip install path4gmns; brew install libomp on Mac)",
)
class TestRunSmoke:
    """End-to-end run on the bundled scenario (~5-10 s). Skipped when
    path4gmns is not installed."""

    def test_run_to_completion(self, bundled_scenario, tmp_path):
        from adapters.dtalite import run_dtalite

        out = tmp_path / "smoke"
        prepare_dtalite_inputs(bundled_scenario, out)
        ok, runtime, err = run_dtalite(
            out, timeout_s=300, iterations=2, column_updating_iterations=2
        )
        # The class is already gated on is_dtalite_available(); once the engine
        # is present a failed run is a real regression, not an environment skip,
        # so assert rather than skip (a broken adapter must fail the suite).
        assert ok, f"DTALite run failed: {err}"
        # Must produce at least link_performance.csv
        assert (out / "link_performance.csv").is_file()
        # Stats parse should produce non-zero completed if assignment converged
        stats = parse_dtalite_output(out)
        assert stats is not None
        assert stats.completed_count > 0, "UE should have converged for at least one trip"
