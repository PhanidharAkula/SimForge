"""
End-to-end pipeline stress tests.

Covers the full new-user workflow (generate → validate → adapt → simulate)
plus negative testing of each corruption mode the validator must catch.
"""

from __future__ import annotations

import csv
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from adapters.sumo.sumo_adapter import (
    parse_canonical_network,
    prepare_sumo_inputs,
    shortest_path_nodes,
)
from pipeline.validation.validate_bundle import validate_bundle

from .conftest import is_arm64_netconvert_crash, warn_skipped


# ===========================================================================
# Validation tests, every corruption mode the validator must catch
# ===========================================================================


@pytest.mark.integration
class TestValidatorCatchesBadData:
    @pytest.fixture
    def good_scenario(self, bundled_scenario, tmp_path) -> Path:
        dst = tmp_path / "good"
        shutil.copytree(bundled_scenario, dst)
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

    def _rewrite_first_row(self, demand_path: Path, key: str, value: str) -> None:
        with demand_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)
        rows[0][key] = value
        with demand_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_demand_with_nonexistent_origin(self, good_scenario):
        self._rewrite_first_row(good_scenario / "demand.csv", "origin_node_id", "FAKE_NODE_999")
        assert validate_bundle(good_scenario) is False

    def test_demand_with_nonexistent_destination(self, good_scenario):
        self._rewrite_first_row(good_scenario / "demand.csv", "destination_node_id", "FAKE_DEST_999")
        assert validate_bundle(good_scenario) is False

    def test_demand_with_negative_departure(self, good_scenario):
        self._rewrite_first_row(good_scenario / "demand.csv", "departure_time_s", "-100")
        assert validate_bundle(good_scenario) is False

    def test_scenario_id_mismatch(self, good_scenario):
        config_path = good_scenario / "config.xml"
        tree = ET.parse(config_path)
        meta = tree.getroot().find("metadata")
        meta.set("scenario_id", "WRONG_ID")
        tree.write(config_path)
        assert validate_bundle(good_scenario) is False

    def test_nonexistent_directory(self):
        assert validate_bundle(Path("/tmp/does_not_exist_simforge")) is False


# ===========================================================================
# SUMO adapter robustness
# ===========================================================================


@pytest.mark.integration
@pytest.mark.requires_sumo
class TestSUMOAdapterRobustness:
    def test_adapter_on_all_scenarios(self, small_bundled_scenarios, tmp_path):
        """Every small scenario must convert without errors."""
        if not small_bundled_scenarios:
            pytest.skip("No bundled scenarios available")

        tested = 0
        skipped: list[str] = []
        for scenario_path in small_bundled_scenarios:
            out = tmp_path / scenario_path.name
            try:
                summary = prepare_sumo_inputs(scenario_path, out)
            except RuntimeError as e:
                if is_arm64_netconvert_crash(e):
                    skipped.append(scenario_path.name)
                    continue
                raise

            assert summary.node_count > 0
            assert summary.link_count > 0
            assert (out / "net.net.xml").is_file()
            assert (out / "routes.rou.xml").is_file()
            tested += 1

        warn_skipped("E2E SUMO sweep", skipped)
        if tested == 0:
            pytest.skip(
                f"All {len(skipped)} candidate scenarios were filtered "
                f"by the arm64 netconvert detector."
            )

    def test_output_routes_have_valid_edges(self, bundled_scenario, tmp_path):
        out = tmp_path / "route_check"
        try:
            prepare_sumo_inputs(bundled_scenario, out)
        except RuntimeError as exc:
            if is_arm64_netconvert_crash(exc):
                pytest.skip(f"arm64 netconvert can't process {bundled_scenario.name}")
            raise

        edge_ids = {e.get("id") for e in ET.parse(out / "edges.edg.xml").findall(".//edge")}
        for route in ET.parse(out / "routes.rou.xml").iter("route"):
            for eid in route.get("edges", "").split():
                assert eid in edge_ids, f"Route references missing edge '{eid}'"

    def test_tripinfo_output_configured(self, bundled_scenario, tmp_path):
        out = tmp_path / "cfg_check"
        try:
            prepare_sumo_inputs(bundled_scenario, out)
        except RuntimeError as exc:
            if is_arm64_netconvert_crash(exc):
                pytest.skip(f"arm64 netconvert can't process {bundled_scenario.name}")
            raise
        cfg_text = (out / "toy.sumocfg").read_text()
        assert "tripinfo" in cfg_text, "SUMO config must enable tripinfo-output"


# ===========================================================================
# Network routing
# ===========================================================================


class TestNetworkRouting:
    def test_bfs_finds_paths(self):
        adj = {"A": ["B"], "B": ["C"], "C": []}
        assert shortest_path_nodes(adj, "A", "C") == ["A", "B", "C"]

    def test_bfs_returns_none_for_unreachable(self):
        adj = {"A": ["B"], "B": [], "C": ["D"], "D": []}
        assert shortest_path_nodes(adj, "A", "C") is None

    def test_bfs_same_node(self):
        adj = {"A": ["B"]}
        assert shortest_path_nodes(adj, "A", "A") == ["A"]

    def test_real_network_has_paths(self, bundled_scenario):
        graph = parse_canonical_network(bundled_scenario / "network.xml")
        with (bundled_scenario / "demand.csv").open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        total = min(50, len(rows))
        routeable = sum(
            1
            for row in rows[:total]
            if (
                path := shortest_path_nodes(
                    graph.adjacency,
                    row["origin_node_id"].strip(),
                    row["destination_node_id"].strip(),
                )
            ) is not None and len(path) >= 2
        )

        ratio = routeable / total if total else 0
        assert ratio >= 0.8, (
            f"Only {routeable}/{total} ({ratio:.0%}) trips routeable — "
            "network may have connectivity issues"
        )
