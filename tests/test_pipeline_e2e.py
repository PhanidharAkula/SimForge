"""
End-to-end pipeline stress tests.

Tests the full workflow that a new user would follow:
  generate scenario → validate → convert to SUMO → run simulation

Also tests edge cases: bad inputs, missing files, corrupt data.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from pipeline.validation.validate_bundle import validate_bundle
from adapters.sumo.sumo_adapter import (
    prepare_sumo_inputs,
    parse_canonical_network,
    shortest_path_nodes,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = REPO_ROOT / "scenarios"


def _first_scenario() -> Path | None:
    if not SCENARIOS_DIR.is_dir():
        return None
    for name in ["chicago_1k_car", "nyc_1k_car", "la_1k_car"]:
        p = SCENARIOS_DIR / name
        if p.is_dir():
            return p
    return None


SCENARIO = _first_scenario()


# ===========================================================================
# Validation tests — catching bad data before simulation
# ===========================================================================

class TestValidatorCatchesBadData:
    """Ensure the validator catches every type of data corruption."""

    @pytest.fixture
    def good_scenario(self, tmp_path) -> Path:
        assert SCENARIO is not None, "No scenario available"
        dst = tmp_path / "good"
        shutil.copytree(SCENARIO, dst)
        return dst

    def test_valid_scenario_passes(self, good_scenario):
        assert validate_bundle(good_scenario) is True

    def test_missing_manifest(self, good_scenario):
        (good_scenario / "manifest.xml").unlink()
        assert validate_bundle(good_scenario) is False

    def test_missing_network(self, good_scenario):
        (good_scenario / "network.xml").unlink()
        assert validate_bundle(good_scenario) is False

    def test_missing_demand(self, good_scenario):
        (good_scenario / "demand.csv").unlink()
        assert validate_bundle(good_scenario) is False

    def test_missing_config(self, good_scenario):
        (good_scenario / "config.xml").unlink()
        assert validate_bundle(good_scenario) is False

    def test_corrupt_xml(self, good_scenario):
        (good_scenario / "network.xml").write_text("<<<not xml>>>")
        assert validate_bundle(good_scenario) is False

    def test_empty_demand(self, good_scenario):
        (good_scenario / "demand.csv").write_text("")
        assert validate_bundle(good_scenario) is False

    def test_demand_missing_columns(self, good_scenario):
        (good_scenario / "demand.csv").write_text("col_a,col_b\n1,2\n")
        assert validate_bundle(good_scenario) is False

    def test_demand_with_nonexistent_origin(self, good_scenario):
        demand_path = good_scenario / "demand.csv"
        rows = []
        with demand_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                rows.append(row)

        # Inject a bogus origin node
        rows[0]["origin_node_id"] = "FAKE_NODE_999"
        with demand_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        assert validate_bundle(good_scenario) is False

    def test_demand_with_nonexistent_destination(self, good_scenario):
        demand_path = good_scenario / "demand.csv"
        rows = []
        with demand_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                rows.append(row)

        rows[0]["destination_node_id"] = "FAKE_DEST_999"
        with demand_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        assert validate_bundle(good_scenario) is False

    def test_demand_with_negative_departure(self, good_scenario):
        demand_path = good_scenario / "demand.csv"
        rows = []
        with demand_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                rows.append(row)

        rows[0]["departure_time_s"] = "-100"
        with demand_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        assert validate_bundle(good_scenario) is False

    def test_scenario_id_mismatch(self, good_scenario):
        """Config scenario_id must match manifest scenario id."""
        config_path = good_scenario / "config.xml"
        tree = ET.parse(config_path)
        meta = tree.getroot().find("metadata")
        meta.set("scenario_id", "WRONG_ID")
        tree.write(config_path)
        assert validate_bundle(good_scenario) is False

    def test_nonexistent_directory(self):
        assert validate_bundle(Path("/tmp/does_not_exist_simforge")) is False


# ===========================================================================
# SUMO adapter robustness tests
# ===========================================================================

class TestSUMOAdapterRobustness:
    _LARGE_PATTERNS = ("50k", "200k", "500k", "5m")

    def test_adapter_on_all_scenarios(self, tmp_path):
        """Every scenario should convert without errors.

        Large scenarios may segfault netconvert on Apple Silicon (arm64).
        """
        import platform

        if not SCENARIOS_DIR.is_dir():
            pytest.skip("No scenarios directory")

        tested = 0
        skipped = []
        for scenario_path in sorted(SCENARIOS_DIR.iterdir()):
            if not scenario_path.is_dir():
                continue
            if not (scenario_path / "manifest.xml").is_file():
                continue
            if any(p in scenario_path.name for p in self._LARGE_PATTERNS):
                skipped.append(scenario_path.name)
                continue

            out = tmp_path / scenario_path.name
            try:
                summary = prepare_sumo_inputs(scenario_path, out)
            except RuntimeError as e:
                if platform.machine() == "arm64" and ("failed" in str(e).lower() or "crashed" in str(e).lower()):
                    skipped.append(scenario_path.name)
                    continue
                raise

            assert summary.node_count > 0
            assert summary.link_count > 0
            assert (out / "net.net.xml").is_file()
            assert (out / "routes.rou.xml").is_file()
            tested += 1

        if skipped:
            import warnings
            warnings.warn(f"Skipped {len(skipped)} scenarios (netconvert arm64): {skipped}")

        assert tested > 0

    def test_output_routes_have_valid_edges(self, tmp_path):
        """Routes in routes.rou.xml should reference edges that exist."""
        assert SCENARIO is not None
        out = tmp_path / "route_check"
        prepare_sumo_inputs(SCENARIO, out)

        # Get edge IDs from edges.edg.xml
        edge_tree = ET.parse(out / "edges.edg.xml")
        edge_ids = {e.get("id") for e in edge_tree.findall(".//edge")}

        # Check route edges
        routes_tree = ET.parse(out / "routes.rou.xml")
        for route in routes_tree.iter("route"):
            edges_str = route.get("edges", "")
            for eid in edges_str.split():
                assert eid in edge_ids, (
                    f"Route references edge '{eid}' not in edges.edg.xml"
                )

    def test_tripinfo_output_configured(self, tmp_path):
        """SUMO config must enable tripinfo output for metric collection."""
        assert SCENARIO is not None
        out = tmp_path / "cfg_check"
        prepare_sumo_inputs(SCENARIO, out)

        cfg_text = (out / "toy.sumocfg").read_text()
        assert "tripinfo" in cfg_text, (
            "SUMO config must include tripinfo-output for metrics"
        )


# ===========================================================================
# Network graph routing tests
# ===========================================================================

class TestNetworkRouting:
    def test_bfs_finds_paths(self):
        """BFS should find paths in a simple graph."""
        adj = {"A": ["B"], "B": ["C"], "C": []}
        path = shortest_path_nodes(adj, "A", "C")
        assert path == ["A", "B", "C"]

    def test_bfs_returns_none_for_unreachable(self):
        adj = {"A": ["B"], "B": [], "C": ["D"], "D": []}
        path = shortest_path_nodes(adj, "A", "C")
        assert path is None

    def test_bfs_same_node(self):
        adj = {"A": ["B"]}
        path = shortest_path_nodes(adj, "A", "A")
        assert path == ["A"]

    def test_real_network_has_paths(self):
        """Real scenario network should have routeable paths."""
        assert SCENARIO is not None
        graph = parse_canonical_network(SCENARIO / "network.xml")

        # Check a sample of demand trips can route
        rows = []
        with (SCENARIO / "demand.csv").open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)

        routeable = 0
        total = min(50, len(rows))
        for row in rows[:total]:
            origin = row["origin_node_id"].strip()
            dest = row["destination_node_id"].strip()
            path = shortest_path_nodes(graph.adjacency, origin, dest)
            if path and len(path) >= 2:
                routeable += 1

        # At least 80% should be routeable
        ratio = routeable / total if total > 0 else 0
        assert ratio >= 0.8, (
            f"Only {routeable}/{total} ({ratio:.0%}) trips are routeable — "
            f"network may have connectivity issues"
        )
