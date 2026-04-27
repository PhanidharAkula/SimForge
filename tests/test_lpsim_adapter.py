"""
Tests for the LPSim adapter.

`prepare_lpsim_inputs` produces LPSim's nodes.csv / edges.csv / od_demand.csv
plus command_line_options.ini from a canonical scenario. These tests exercise
input preparation, schema fidelity, determinism, and output parsing — no GPU
or LivingCity binary is required for the fast tier. The single binary-driven
smoke test lives in test_engine_smoke.py and skips when no GPU is present.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from adapters.lpsim.lpsim_adapter import (
    LPSimConfig,
    LPSimTripStats,
    _MS_TO_MPH,
    _hours_from_seconds,
    _to_int_index,
    find_lpsim_binary,
    find_lpsim_singularity_image,
    parse_lpsim_output,
    prepare_lpsim_inputs,
    write_lpsim_demand_csv,
    write_lpsim_edges_csv,
    write_lpsim_ini,
    write_lpsim_nodes_csv,
)
from adapters.sumo.sumo_adapter import (
    CanonicalLink,
    CanonicalNode,
    NetworkGraph,
    ScenarioSummary,
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
        ("12", 12),  # tolerates raw integers from older / hand-rolled fixtures
    ])
    def test_strips_prefix(self, canonical_id, expected):
        assert _to_int_index(canonical_id) == expected

    def test_rejects_garbage(self):
        with pytest.raises(ValueError, match="Cannot map"):
            _to_int_index("not_a_node")
        with pytest.raises(ValueError, match="Cannot map"):
            _to_int_index("")


class TestHoursFromSeconds:
    @pytest.mark.parametrize("seconds, expected", [
        (0, 0),
        (3599, 0),       # floor → still 0
        (3600, 1),
        (25200, 7),      # 07:00 morning peak
        (28800, 8),      # 08:00
        (86399, 23),
        (86400, 24),     # midnight rollover clamped to 24
        (-100, 0),       # negative clamped
        (999_999, 24),   # huge clamped
    ])
    def test_floors_and_clamps(self, seconds, expected):
        assert _hours_from_seconds(seconds) == expected


class TestLPSimConfig:
    def test_defaults_match_plan(self):
        cfg = LPSimConfig()
        assert cfg.use_cpu is False           # GPU path is the canonical run
        assert cfg.num_passes == 1            # comparable to SUMO/MATSim single-iter
        assert cfg.use_sp_routing is True
        assert cfg.use_johnson_routing is False

    def test_to_dict(self):
        cfg = LPSimConfig(use_cpu=True, num_passes=3)
        d = cfg.to_dict()
        assert d["use_cpu"] is True
        assert d["num_passes"] == 3


# ---------------------------------------------------------------------------
# Synthetic graph fixture for builder unit tests
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_graph() -> NetworkGraph:
    """A 3-node, 3-edge graph plus one self-loop that must be dropped."""
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
        # Self-loop — adapter must drop it
        CanonicalLink(id="l3", from_node="n1", to_node="n1",
                      length=10.0, speed=5.0, lanes=1),
    ]
    return NetworkGraph(nodes=nodes, links=links, adjacency={}, edge_lookup={})


class TestNodesCsv:
    def test_writes_header_and_rows(self, tiny_graph, tmp_path):
        out = tmp_path / "nodes.csv"
        rows = write_lpsim_nodes_csv(tiny_graph, out)
        assert rows == 3
        text = out.read_text(encoding="utf-8")
        # graph.cc:204 is the binding constraint — strictest of the three
        # node loaders inside the binary. `ref` is OSM-specific and we
        # emit empty strings since canonical networks don't preserve it.
        assert text.splitlines()[0] == "osmid,x,y,ref,highway,index"

    def test_uses_lf_line_endings(self, tiny_graph, tmp_path):
        # csv.h SP loader rejects CRLF — see write_lpsim_nodes_csv docstring.
        out = tmp_path / "nodes.csv"
        write_lpsim_nodes_csv(tiny_graph, out)
        assert b"\r\n" not in out.read_bytes(), \
            "nodes.csv must use LF line endings (csv.h rejects CRLF)"

    def test_index_matches_canonical_int(self, tiny_graph, tmp_path):
        out = tmp_path / "nodes.csv"
        write_lpsim_nodes_csv(tiny_graph, out)
        with out.open() as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert {int(r["index"]) for r in rows} == {0, 1, 2}
        assert all(r["osmid"] == r["index"] for r in rows), \
            "osmid and index should match — canonical schema collapses them"
        assert all(r["ref"] == "" for r in rows), \
            "ref column must be present (graph.cc:204 requires it) but empty " \
            "since canonical networks don't preserve OSM ref tags"

    def test_coordinates_round_to_six_decimals(self, tiny_graph, tmp_path):
        out = tmp_path / "nodes.csv"
        write_lpsim_nodes_csv(tiny_graph, out)
        with out.open() as f:
            reader = csv.DictReader(f)
            for r in reader:
                # 6 decimals is plenty for a sub-meter precision at street scale
                assert len(r["x"].split(".")[-1]) == 6
                assert len(r["y"].split(".")[-1]) == 6


class TestEdgesCsv:
    def test_writes_header_with_required_columns(self, tiny_graph, tmp_path):
        out = tmp_path / "edges.csv"
        write_lpsim_edges_csv(tiny_graph, out)
        header = out.read_text(encoding="utf-8").splitlines()[0]
        # All columns the LPSim B18 loader looks up by name
        for col in ("uniqueid", "u", "v", "length", "lanes", "speed_mph"):
            assert col in header.split(",")

    def test_uses_lf_line_endings(self, tiny_graph, tmp_path):
        out = tmp_path / "edges.csv"
        write_lpsim_edges_csv(tiny_graph, out)
        assert b"\r\n" not in out.read_bytes(), \
            "edges.csv must use LF line endings (csv.h rejects CRLF)"

    def test_drops_self_loops(self, tiny_graph, tmp_path):
        out = tmp_path / "edges.csv"
        rows_written = write_lpsim_edges_csv(tiny_graph, out)
        # Input had 4 links, 1 self-loop → 3 emitted
        assert rows_written == 3
        with out.open() as f:
            reader = csv.DictReader(f)
            data = list(reader)
        assert all(r["u"] != r["v"] for r in data), \
            "self-loops must not appear in LPSim edges.csv"

    def test_speed_converted_to_mph(self, tiny_graph, tmp_path):
        out = tmp_path / "edges.csv"
        write_lpsim_edges_csv(tiny_graph, out)
        with out.open() as f:
            reader = csv.DictReader(f)
            data = sorted(reader, key=lambda r: int(r["uniqueid"]))
        # The writer formats speed as %.1f mph, so the absolute tolerance
        # has to allow for one-decimal rounding (≤ 0.05). 13.9 m/s → 31.1 mph,
        # 11.1 m/s → 24.8 mph, 22.2 m/s → 49.7 mph.
        assert float(data[0]["speed_mph"]) == pytest.approx(13.9 * _MS_TO_MPH, abs=0.05)
        assert float(data[1]["speed_mph"]) == pytest.approx(11.1 * _MS_TO_MPH, abs=0.05)
        assert float(data[2]["speed_mph"]) == pytest.approx(22.2 * _MS_TO_MPH, abs=0.05)

    def test_uniqueid_is_sequential(self, tiny_graph, tmp_path):
        # LPSim's GPU kernel indexes per-edge arrays by `uniqueid`, so
        # gappy IDs (from self-loop / short-edge filters) trigger an
        # OOB at b18CUDA_trafficSimulator.cu:1682. Diagnosed on Pitzer
        # 2026-04-27 — confirmed our edges.csv had max uniqueid 58917
        # but only 58505 rows. The adapter therefore renumbers
        # uniqueid sequentially 0..N-1 as it writes. Note: tiny_graph
        # has 4 links incl. one self-loop, so we expect 3 written
        # rows with uniqueids exactly {0, 1, 2}.
        out = tmp_path / "edges.csv"
        n = write_lpsim_edges_csv(tiny_graph, out)
        with out.open() as f:
            reader = csv.DictReader(f)
            uniqueids = [int(r["uniqueid"]) for r in reader]
        assert uniqueids == list(range(n)), (
            f"uniqueid must be 0..N-1 contiguous, got {uniqueids}"
        )

    def test_drops_sub_meter_edges(self, tmp_path):
        # LPSim's GPU lane-map kernel allocates `length / cell_size` cells
        # per edge; a sub-meter edge yields zero cells and the simulation
        # kernel hits an illegal-memory access. Diagnosed on Pitzer
        # 2026-04-27. The adapter therefore filters edges < 1 m.
        nodes = {
            "n0": CanonicalNode(id="n0", x=0, y=0),
            "n1": CanonicalNode(id="n1", x=1, y=1),
            "n2": CanonicalNode(id="n2", x=2, y=2),
        }
        links = [
            CanonicalLink(id="l0", from_node="n0", to_node="n1",
                          length=0.13, speed=10, lanes=1),  # too short
            CanonicalLink(id="l1", from_node="n1", to_node="n2",
                          length=120.0, speed=10, lanes=1),  # OK
            CanonicalLink(id="l2", from_node="n0", to_node="n2",
                          length=0.99, speed=10, lanes=1),  # too short by a hair
        ]
        graph = NetworkGraph(nodes=nodes, links=links,
                             adjacency={}, edge_lookup={})
        out = tmp_path / "edges.csv"
        rows_written = write_lpsim_edges_csv(graph, out)
        assert rows_written == 1, \
            "only the 120 m edge survives; both sub-meter edges dropped"

    def test_lanes_clamped_to_at_least_1(self, tmp_path):
        # An edge with lanes=0 (rare but possible from osm data) should still
        # be writable as a 1-lane road.
        nodes = {
            "n0": CanonicalNode(id="n0", x=0, y=0),
            "n1": CanonicalNode(id="n1", x=1, y=1),
        }
        link = CanonicalLink(id="l0", from_node="n0", to_node="n1",
                             length=100, speed=10, lanes=0)
        graph = NetworkGraph(nodes=nodes, links=[link],
                             adjacency={}, edge_lookup={})
        out = tmp_path / "edges.csv"
        write_lpsim_edges_csv(graph, out)
        with out.open() as f:
            reader = csv.DictReader(f)
            row = next(reader)
        assert int(row["lanes"]) == 1


class TestDemandCsv:
    def _write_canonical_demand(self, path: Path):
        path.write_text(
            "trip_id,origin_node_id,destination_node_id,departure_time_s,mode\n"
            "trip_a,n0,n1,25200,car\n"
            "trip_b,n1,n2,25500,car\n"
            "trip_c,n0,n2,25800,car\n",
            encoding="utf-8",
        )

    def test_only_emits_feasible_trips(self, tmp_path):
        demand = tmp_path / "demand.csv"
        self._write_canonical_demand(demand)
        out = tmp_path / "od.csv"
        n = write_lpsim_demand_csv(demand, out, feasible_trip_ids={"trip_a", "trip_c"})
        assert n == 2
        with out.open() as f:
            data = list(csv.DictReader(f))
        assert {r["PERNO"] for r in data} == {"trip_a", "trip_c"}

    def test_columns_match_sp_loader(self, tmp_path):
        # b18TrafficSP.cpp:108 (the loader USE_SP_ROUTING=true invokes):
        #   read_header(ignore_extra_column, "dep_time", "origin", "destination")
        # Plus we keep PERNO for the older Qt loader. Order MUST match
        # what we expose on disk so a defender can inspect by eye.
        demand = tmp_path / "demand.csv"
        self._write_canonical_demand(demand)
        out = tmp_path / "od.csv"
        write_lpsim_demand_csv(demand, out, feasible_trip_ids={"trip_a"})
        header = out.read_text(encoding="utf-8").splitlines()[0]
        assert header == "dep_time,origin,destination,PERNO", (
            "LPSim's SP loader requires exactly dep_time/origin/destination "
            "(in that order); PERNO is appended for the Qt loader's compat. "
            "Renaming or reordering silently breaks every lpsim run."
        )

    def test_keeps_departure_time_column(self, tmp_path):
        # Earlier versions of the adapter dropped departure_time_s under
        # the false belief that LPSim ignored per-trip times. The SP
        # loader at b18TrafficSP.cpp:108 actually reads `dep_time` and
        # filters trips by `dep_time >= startSimulationH * 3600`, so the
        # column is required.
        demand = tmp_path / "demand.csv"
        self._write_canonical_demand(demand)
        out = tmp_path / "od.csv"
        write_lpsim_demand_csv(demand, out, feasible_trip_ids={"trip_a"})
        text = out.read_text(encoding="utf-8")
        assert "dep_time" in text.splitlines()[0]
        # The first data row's first column (dep_time) should be the
        # canonical departure_time_s from trip_a (25200 = 07:00:00).
        first_data_row = text.splitlines()[1]
        assert first_data_row.startswith("25200,"), (
            f"first data row should lead with dep_time=25200, got: {first_data_row}"
        )

    def test_uses_lf_line_endings(self, tmp_path):
        # csv.h's CSV reader (used by USE_SP_ROUTING=true) does NOT strip
        # \r from CRLF endings — diagnosed on Pitzer 2026-04-27 when our
        # initial CRLF-by-default Python writer produced "index\r" as
        # the last column name and the loader couldn't find "index".
        demand = tmp_path / "demand.csv"
        self._write_canonical_demand(demand)
        out = tmp_path / "od.csv"
        write_lpsim_demand_csv(demand, out, feasible_trip_ids={"trip_a"})
        raw = out.read_bytes()
        assert b"\r\n" not in raw, "OD CSV must use LF line endings (csv.h rejects CRLF)"


class TestIniWriter:
    def _summary(self, start_s=25200, end_s=28800) -> ScenarioSummary:
        return ScenarioSummary(
            scenario_id="chicago_1k_car",
            node_count=10, link_count=20, trip_count=5,
            has_signals=False,
            start_time_s=start_s, end_time_s=end_s,
        )

    def test_writes_general_section_with_required_keys(self, tmp_path):
        cfg = LPSimConfig()
        out = tmp_path / "ini"
        write_lpsim_ini(out, "network", "od.csv", self._summary(), cfg)
        text = out.read_text(encoding="utf-8")
        assert text.startswith("[General]")
        for key in ("USE_CPU", "NETWORK_PATH", "OD_DEMAND_FILENAME",
                    "START_HR", "END_HR", "NUM_PASSES", "USE_SP_ROUTING"):
            assert f"{key}=" in text

    def test_start_end_hours_from_canonical_seconds(self, tmp_path):
        # 07:00 → 08:00 morning peak rounds to floor 7 / ceil 8
        cfg = LPSimConfig()
        out = tmp_path / "ini"
        write_lpsim_ini(out, "network", "od.csv",
                        self._summary(25200, 28800), cfg)
        text = out.read_text(encoding="utf-8")
        assert "START_HR=7" in text
        assert "END_HR=8" in text

    def test_partial_hour_window_widens_to_at_least_one_hour(self, tmp_path):
        cfg = LPSimConfig()
        out = tmp_path / "ini"
        # 07:00 to 07:30 — needs to round end_hr up to at least 8 so trips
        # have a chance to depart
        write_lpsim_ini(out, "network", "od.csv",
                        self._summary(25200, 27000), cfg)
        text = out.read_text(encoding="utf-8")
        assert "START_HR=7" in text
        assert "END_HR=8" in text


# ---------------------------------------------------------------------------
# Determinism — the whole adapter must be byte-identical across re-runs
# ---------------------------------------------------------------------------


@pytest.mark.determinism
class TestDeterminism:
    def test_full_output_tree_byte_identical(self, bundled_scenario, tmp_path):
        """Two prepare_lpsim_inputs calls must produce identical files."""
        run1 = tmp_path / "run1"
        run2 = tmp_path / "run2"
        run1.mkdir()
        run2.mkdir()
        prepare_lpsim_inputs(bundled_scenario, run1)
        prepare_lpsim_inputs(bundled_scenario, run2)
        # feasibility_report.json contains a timestamp; exclude it from the
        # diff just like the SUMO determinism test excludes net.net.xml.
        h1 = directory_sha256(run1, exclude_patterns=["feasibility_report.json"])
        h2 = directory_sha256(run2, exclude_patterns=["feasibility_report.json"])
        assert set(h1) == set(h2)
        for name in h1:
            assert h1[name] == h2[name], f"{name} differs across re-runs"


# ---------------------------------------------------------------------------
# End-to-end smoke on the bundled scenario (no binary needed)
# ---------------------------------------------------------------------------


class TestPrepareLPSimInputs:
    def test_produces_expected_layout(self, bundled_scenario, tmp_path):
        out = tmp_path / "lpsim_out"
        summary = prepare_lpsim_inputs(bundled_scenario, out)
        assert summary.scenario_id == bundled_scenario.name
        assert summary.node_count > 0
        assert summary.link_count > 0
        assert summary.trip_count > 0
        # Required artefacts
        assert (out / "command_line_options.ini").is_file()
        assert (out / "network" / "nodes.csv").is_file()
        assert (out / "network" / "edges.csv").is_file()
        assert (out / "network" / "od_demand.csv").is_file()
        assert (out / "feasibility_report.json").is_file()

    def test_ini_references_emitted_paths(self, bundled_scenario, tmp_path):
        out = tmp_path / "lpsim_out"
        prepare_lpsim_inputs(bundled_scenario, out)
        ini_text = (out / "command_line_options.ini").read_text(encoding="utf-8")
        assert "NETWORK_PATH=network/" in ini_text
        assert "OD_DEMAND_FILENAME=od_demand.csv" in ini_text


# ---------------------------------------------------------------------------
# Output parsing — synthetic *_people.csv fixtures
# ---------------------------------------------------------------------------


class TestParseOutput:
    def _write_people_csv(self, dir_path: Path, rows: list[dict],
                          numpasses: int = 1):
        path = dir_path / f"{numpasses}_people.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "p", "init_intersection", "end_intersection",
                    "time_departure", "num_steps", "travel_time", "distance",
                ],
            )
            w.writeheader()
            for r in rows:
                w.writerow(r)
        return path

    def test_returns_none_when_no_output_present(self, tmp_path):
        # No *_people.csv → None lets the harness record a clean failure
        assert parse_lpsim_output(tmp_path) is None

    def test_aggregates_completed_trips(self, tmp_path):
        self._write_people_csv(tmp_path, [
            dict(p=0, init_intersection=1, end_intersection=2,
                 time_departure=25200, num_steps=200, travel_time=100, distance=1500),
            dict(p=1, init_intersection=3, end_intersection=4,
                 time_departure=25260, num_steps=400, travel_time=200, distance=3000),
            dict(p=2, init_intersection=5, end_intersection=6,
                 time_departure=25320, num_steps=600, travel_time=300, distance=4500),
        ])
        stats = parse_lpsim_output(tmp_path)
        assert stats is not None
        assert stats.trip_count == 3
        assert stats.completed_count == 3
        assert stats.mean_travel_time_s == pytest.approx(200.0)
        assert stats.mean_distance_m == pytest.approx(3000.0)

    def test_skips_zero_travel_time_rows(self, tmp_path):
        # LPSim writes travel_time=0 for abandoned trips; we exclude them
        # from the mean (matches the SUMO / MATSim parsers).
        self._write_people_csv(tmp_path, [
            dict(p=0, init_intersection=1, end_intersection=2,
                 time_departure=25200, num_steps=0, travel_time=0, distance=0),
            dict(p=1, init_intersection=3, end_intersection=4,
                 time_departure=25260, num_steps=400, travel_time=180, distance=2700),
        ])
        stats = parse_lpsim_output(tmp_path)
        assert stats.trip_count == 2
        assert stats.completed_count == 1
        assert stats.mean_travel_time_s == 180.0

    def test_p95_uses_sorted_index(self, tmp_path):
        # 100 evenly spaced travel times → P95 = the 95th-percentile entry
        rows = [
            dict(p=i, init_intersection=0, end_intersection=0,
                 time_departure=0, num_steps=0, travel_time=float(i + 1), distance=0)
            for i in range(100)
        ]
        self._write_people_csv(tmp_path, rows)
        stats = parse_lpsim_output(tmp_path)
        # Sorted travel_times = 1, 2, ..., 100. P95 index = floor(0.95 * 99) = 94 → value 95.
        assert stats.p95_travel_time_s == 95.0


# ---------------------------------------------------------------------------
# Binary discovery — mostly None on dev laptops; just verify the helpers
# return something sensible without raising.
# ---------------------------------------------------------------------------


class TestBinaryDiscovery:
    def test_find_binary_returns_path_or_none(self):
        result = find_lpsim_binary()
        assert result is None or isinstance(result, Path)

    def test_find_singularity_image_returns_path_or_none(self):
        result = find_lpsim_singularity_image()
        assert result is None or isinstance(result, Path)
