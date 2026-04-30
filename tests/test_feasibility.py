"""
Tests for adapters/common/feasibility.py — the shared trip-feasibility filter
that makes cross-engine comparison apples-to-apples.

The filter is the foundation of the [1.0.0] fix that closed the SUMO/MATSim
silent-divergence gap. Regressions here would re-introduce mismatched trip
subsets across engines, so behaviour is exercised against synthetic networks
with known SCC topology and against the bundled scenarios.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from adapters.common.feasibility import (
    FeasibilityReport,
    feasible_trip_ids,
    log_report,
    resolve_network_and_demand,
    write_feasibility_report,
)


# ---------------------------------------------------------------------------
# Synthetic-graph helpers
# ---------------------------------------------------------------------------


def _write_network(path: Path, nodes: list[str], edges: list[tuple[str, str]]) -> None:
    nodes_xml = "\n".join(f'    <node id="{n}" x="0" y="0" />' for n in nodes)
    links_xml = "\n".join(
        f'    <link id="L{i}" from="{u}" to="{v}" />'
        for i, (u, v) in enumerate(edges)
    )
    path.write_text(
        f"""<?xml version="1.0"?>
<network>
  <nodes>
{nodes_xml}
  </nodes>
  <links>
{links_xml}
  </links>
</network>
""",
        encoding="utf-8",
    )


def _write_demand(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = ["trip_id", "origin_node_id", "destination_node_id"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# Synthetic-graph behaviour
# ---------------------------------------------------------------------------


class TestFeasibleTripIds:
    def test_all_trips_inside_scc(self, tmp_path):
        # Single 3-cycle a→b→c→a; every trip is feasible.
        _write_network(tmp_path / "network.xml", ["a", "b", "c"],
                       [("a", "b"), ("b", "c"), ("c", "a")])
        _write_demand(tmp_path / "demand.csv", [
            {"trip_id": "t1", "origin_node_id": "a", "destination_node_id": "b"},
            {"trip_id": "t2", "origin_node_id": "b", "destination_node_id": "c"},
            {"trip_id": "t3", "origin_node_id": "c", "destination_node_id": "a"},
        ])

        feasible, report = feasible_trip_ids(
            tmp_path / "network.xml", tmp_path / "demand.csv"
        )
        assert feasible == {"t1", "t2", "t3"}
        assert report.total_trips == 3
        assert report.feasible_trips == 3
        assert report.skipped_outside_scc == 0
        assert report.feasible_fraction == 1.0

    def test_drops_trip_outside_scc(self, tmp_path):
        # a⇄b⇄c is the SCC; d is reachable from c but never returns.
        _write_network(tmp_path / "network.xml", ["a", "b", "c", "d"],
                       [("a", "b"), ("b", "a"), ("b", "c"), ("c", "b"), ("c", "d")])
        _write_demand(tmp_path / "demand.csv", [
            {"trip_id": "ok", "origin_node_id": "a", "destination_node_id": "c"},
            {"trip_id": "to_d", "origin_node_id": "a", "destination_node_id": "d"},
            {"trip_id": "from_d", "origin_node_id": "d", "destination_node_id": "a"},
        ])
        feasible, report = feasible_trip_ids(
            tmp_path / "network.xml", tmp_path / "demand.csv"
        )
        assert feasible == {"ok"}
        assert report.skipped_outside_scc == 2
        assert sorted(report.skipped_trip_ids) == ["from_d", "to_d"]

    def test_drops_trip_referencing_unknown_node(self, tmp_path):
        _write_network(tmp_path / "network.xml", ["a", "b"],
                       [("a", "b"), ("b", "a")])
        _write_demand(tmp_path / "demand.csv", [
            {"trip_id": "ok", "origin_node_id": "a", "destination_node_id": "b"},
            {"trip_id": "ghost", "origin_node_id": "a", "destination_node_id": "ZZ"},
        ])
        feasible, report = feasible_trip_ids(
            tmp_path / "network.xml", tmp_path / "demand.csv"
        )
        assert feasible == {"ok"}
        assert report.skipped_unknown_nodes == 1

    def test_drops_trip_with_missing_fields(self, tmp_path):
        _write_network(tmp_path / "network.xml", ["a", "b"],
                       [("a", "b"), ("b", "a")])
        _write_demand(tmp_path / "demand.csv", [
            {"trip_id": "ok", "origin_node_id": "a", "destination_node_id": "b"},
            {"trip_id": "no_origin", "origin_node_id": "", "destination_node_id": "b"},
            {"trip_id": "", "origin_node_id": "a", "destination_node_id": "b"},
        ])
        feasible, report = feasible_trip_ids(
            tmp_path / "network.xml", tmp_path / "demand.csv"
        )
        assert feasible == {"ok"}
        assert report.skipped_missing_fields == 2

    def test_demand_missing_required_column_raises(self, tmp_path):
        _write_network(tmp_path / "network.xml", ["a", "b"],
                       [("a", "b"), ("b", "a")])
        # Missing destination_node_id column entirely.
        (tmp_path / "demand.csv").write_text(
            "trip_id,origin_node_id\nt1,a\n", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="missing columns"):
            feasible_trip_ids(tmp_path / "network.xml", tmp_path / "demand.csv")


# ---------------------------------------------------------------------------
# FeasibilityReport surface
# ---------------------------------------------------------------------------


class TestFeasibilityReport:
    def _make(self, feasible: int, total: int) -> FeasibilityReport:
        return FeasibilityReport(
            scenario_network="net.xml",
            scenario_demand="demand.csv",
            total_nodes=10, total_links=20,
            scc_nodes=9, scc_links=18,
            total_trips=total, feasible_trips=feasible,
        )

    def test_feasible_fraction_when_all_pass(self):
        assert self._make(100, 100).feasible_fraction == 1.0

    def test_feasible_fraction_partial(self):
        assert abs(self._make(75, 100).feasible_fraction - 0.75) < 1e-9

    def test_feasible_fraction_zero_trips(self):
        # Avoid division-by-zero — empty demand is treated as "100% feasible".
        assert self._make(0, 0).feasible_fraction == 1.0

    def test_summary_line_contains_counts(self):
        line = self._make(95, 100).summary_line()
        assert "95/100" in line
        assert "95.0%" in line
        assert "9/10" in line  # SCC node coverage

    def test_to_dict_includes_fraction(self):
        d = self._make(50, 100).to_dict()
        assert d["feasible_fraction"] == 0.5
        assert d["total_trips"] == 100


# ---------------------------------------------------------------------------
# Persistence + logging
# ---------------------------------------------------------------------------


class TestWriteFeasibilityReport:
    def test_writes_valid_json(self, tmp_path):
        report = FeasibilityReport(
            scenario_network="n.xml", scenario_demand="d.csv",
            total_nodes=1, total_links=1, scc_nodes=1, scc_links=1,
            total_trips=1, feasible_trips=1,
        )
        out = tmp_path / "subdir" / "feasibility_report.json"
        path = write_feasibility_report(report, out)
        assert path.is_file()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["total_trips"] == 1
        assert loaded["feasible_fraction"] == 1.0


class TestLogReport:
    def test_emits_warning_when_trips_dropped(self, caplog):
        report = FeasibilityReport(
            scenario_network="n", scenario_demand="d",
            total_nodes=10, total_links=10, scc_nodes=10, scc_links=10,
            total_trips=10, feasible_trips=8, skipped_outside_scc=2,
        )
        with caplog.at_level("WARNING"):
            log_report(report, engine="sumo")
        assert any("sumo" in rec.message and "8/10" in rec.message
                   for rec in caplog.records)

    def test_logs_info_when_all_feasible(self, caplog):
        report = FeasibilityReport(
            scenario_network="n", scenario_demand="d",
            total_nodes=10, total_links=10, scc_nodes=10, scc_links=10,
            total_trips=5, feasible_trips=5,
        )
        with caplog.at_level("INFO"):
            log_report(report, engine="matsim")
        # No WARNING records expected
        assert not any(rec.levelname == "WARNING" for rec in caplog.records)


# ---------------------------------------------------------------------------
# Manifest resolver
# ---------------------------------------------------------------------------


class TestResolveNetworkAndDemand:
    def test_resolves_paths_from_real_bundle(self, bundled_scenario):
        net, demand = resolve_network_and_demand(bundled_scenario)
        assert net.is_file() and net.name == "network.xml"
        assert demand.is_file() and demand.name == "demand.csv"

    def test_missing_manifest_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            resolve_network_and_demand(tmp_path)


# ---------------------------------------------------------------------------
# End-to-end on bundled scenario
# ---------------------------------------------------------------------------


class TestRealBundledFeasibility:
    def test_real_scenario_high_feasibility(self, bundled_scenario):
        """Bundled scenarios are SCC-clean by construction (≥99 % feasible)."""
        feasible, report = feasible_trip_ids(
            bundled_scenario / "network.xml", bundled_scenario / "demand.csv"
        )
        assert report.total_trips > 0
        assert report.feasible_fraction >= 0.99, (
            f"{bundled_scenario.name}: only "
            f"{report.feasible_trips}/{report.total_trips} trips feasible"
        )
        assert isinstance(feasible, set)


# ---------------------------------------------------------------------------
# Mode-aware feasibility (V5 — adapters narrow demand to supported_modes)
# ---------------------------------------------------------------------------


class TestModeAwareFeasibility:
    """Verify the mode filter that adapters use to narrow demand to their
    supported modes. SUMO/MATSim/DTALite all pass `supported_modes={"car"}`
    today; this verifies the filter actually drops non-car rows and reports
    the count under skipped_unsupported_mode.
    """

    def _write_mixed_demand(self, tmp_path):
        d = tmp_path / "demand.csv"
        d.write_text(
            "trip_id,origin_node_id,destination_node_id,departure_time_s,mode\n"
            "t1,n1,n2,0,car\n"
            "t2,n1,n2,0,car\n"
            "t3,n1,n2,0,transit\n"
            "t4,n1,n2,0,bike\n"
            "t5,n1,n2,0,walk\n"
        )
        return d

    def _write_two_node_network(self, tmp_path):
        n = tmp_path / "network.xml"
        n.write_text(
            "<?xml version='1.0'?>\n"
            "<network>\n"
            "  <nodes>\n"
            "    <node id='n1' x='0' y='0'/>\n"
            "    <node id='n2' x='1' y='0'/>\n"
            "  </nodes>\n"
            "  <links>\n"
            "    <link id='l1' from='n1' to='n2'/>\n"
            "    <link id='l2' from='n2' to='n1'/>\n"
            "  </links>\n"
            "</network>\n"
        )
        return n

    def test_filter_keeps_only_supported_modes(self, tmp_path):
        net = self._write_two_node_network(tmp_path)
        dem = self._write_mixed_demand(tmp_path)
        feasible, report = feasible_trip_ids(
            net, dem, supported_modes={"car"}
        )
        assert feasible == {"t1", "t2"}
        assert report.total_trips == 5
        assert report.feasible_trips == 2
        assert report.skipped_unsupported_mode == 3
        assert report.supported_modes == ["car"]

    def test_mode_filter_disabled_keeps_everything(self, tmp_path):
        # supported_modes=None → mode column ignored (back-compat path).
        net = self._write_two_node_network(tmp_path)
        dem = self._write_mixed_demand(tmp_path)
        feasible, report = feasible_trip_ids(net, dem, supported_modes=None)
        assert len(feasible) == 5
        assert report.skipped_unsupported_mode == 0
        assert report.supported_modes == []

    def test_multi_mode_set_keeps_union(self, tmp_path):
        net = self._write_two_node_network(tmp_path)
        dem = self._write_mixed_demand(tmp_path)
        feasible, report = feasible_trip_ids(
            net, dem, supported_modes={"car", "transit"}
        )
        assert feasible == {"t1", "t2", "t3"}
        assert report.skipped_unsupported_mode == 2
        assert sorted(report.supported_modes) == ["car", "transit"]
        assert len(feasible) == report.feasible_trips
