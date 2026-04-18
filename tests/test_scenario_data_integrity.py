# pylint: disable=redefined-outer-name
"""
Comprehensive data integrity tests for ALL generated scenarios.

These tests ensure that any data errors are caught here — before
sending scenarios to simulation engines. A new user generating their
own data should see failures here, not cryptic SUMO/MATSim errors.

Tests cover:
  - File existence and structure
  - XML well-formedness
  - Cross-file referential integrity (demand nodes ⊆ network nodes)
  - Numeric validity (no NaN, no negatives where inappropriate)
  - Edge/link sanity (positive lengths, positive speeds)
  - Demand coverage (origins/destinations reachable)
  - Config consistency (time horizon, seed, units)
  - Signals validation
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = REPO_ROOT / "scenarios"


def _all_scenarios() -> list[Path]:
    """Discover all scenario directories with a manifest.xml."""
    if not SCENARIOS_DIR.is_dir():
        return []
    return sorted(
        p for p in SCENARIOS_DIR.iterdir()
        if p.is_dir() and (p / "manifest.xml").is_file()
    )


SCENARIOS = _all_scenarios()

# Skip entire module if no scenarios exist
pytestmark = pytest.mark.skipif(
    len(SCENARIOS) == 0, reason="No generated scenarios found"
)


# ---------------------------------------------------------------------------
# Parametrized over every available scenario
# ---------------------------------------------------------------------------


@pytest.fixture(params=SCENARIOS, ids=[s.name for s in SCENARIOS])
def scenario(request) -> Path:
    return request.param


# ===== File existence =====

class TestFileExistence:
    def test_manifest_exists(self, scenario):
        assert (scenario / "manifest.xml").is_file()

    def test_network_exists(self, scenario):
        assert (scenario / "network.xml").is_file()

    def test_demand_exists(self, scenario):
        assert (scenario / "demand.csv").is_file()

    def test_config_exists(self, scenario):
        assert (scenario / "config.xml").is_file()

    def test_signals_exists(self, scenario):
        assert (scenario / "signals.xml").is_file()


# ===== XML well-formedness =====

class TestXMLParsing:
    def test_manifest_parses(self, scenario):
        tree = ET.parse(scenario / "manifest.xml")
        assert tree.getroot().tag == "manifest"

    def test_network_parses(self, scenario):
        tree = ET.parse(scenario / "network.xml")
        assert tree.getroot().tag == "network"

    def test_config_parses(self, scenario):
        tree = ET.parse(scenario / "config.xml")
        assert tree.getroot().tag == "config"

    def test_signals_parses(self, scenario):
        signals_path = scenario / "signals.xml"
        if signals_path.is_file():
            tree = ET.parse(signals_path)
            assert tree.getroot().tag == "signals"


# ===== Network integrity =====

class TestNetworkIntegrity:
    def _load_network(self, scenario):
        tree = ET.parse(scenario / "network.xml")
        root = tree.getroot()
        nodes_elem = root.find("nodes")
        links_elem = root.find("links")
        return root, nodes_elem, links_elem

    def test_has_nodes_and_links(self, scenario):
        _, nodes_elem, links_elem = self._load_network(scenario)
        assert nodes_elem is not None, "Missing <nodes>"
        assert links_elem is not None, "Missing <links>"
        nodes = nodes_elem.findall("node")
        links = links_elem.findall("link")
        assert len(nodes) > 0, "Network has no nodes"
        assert len(links) > 0, "Network has no links"

    def test_no_duplicate_node_ids(self, scenario):
        _, nodes_elem, _ = self._load_network(scenario)
        ids = [n.get("id") for n in nodes_elem.findall("node")]
        assert len(ids) == len(set(ids)), "Duplicate node IDs found"

    def test_no_duplicate_link_ids(self, scenario):
        _, _, links_elem = self._load_network(scenario)
        ids = [l.get("id") for l in links_elem.findall("link")]
        assert len(ids) == len(set(ids)), "Duplicate link IDs found"

    def test_node_coordinates_are_valid(self, scenario):
        _, nodes_elem, _ = self._load_network(scenario)
        for node in nodes_elem.findall("node"):
            x = float(node.get("x", "nan"))
            y = float(node.get("y", "nan"))
            assert not math.isnan(x), f"Node {node.get('id')}: x is NaN"
            assert not math.isnan(y), f"Node {node.get('id')}: y is NaN"
            # WGS84 coordinate bounds
            assert -180 <= x <= 180, f"Node {node.get('id')}: x={x} out of WGS84 range"
            assert -90 <= y <= 90, f"Node {node.get('id')}: y={y} out of WGS84 range"

    def test_link_endpoints_exist(self, scenario):
        _, nodes_elem, links_elem = self._load_network(scenario)
        node_ids = {n.get("id") for n in nodes_elem.findall("node")}
        for link in links_elem.findall("link"):
            from_id = link.get("from")
            to_id = link.get("to")
            link_id = link.get("id")
            assert from_id in node_ids, (
                f"Link {link_id}: from node '{from_id}' not in network"
            )
            assert to_id in node_ids, (
                f"Link {link_id}: to node '{to_id}' not in network"
            )

    def test_link_lengths_are_positive(self, scenario):
        _, _, links_elem = self._load_network(scenario)
        for link in links_elem.findall("link"):
            length = float(link.get("length", "0"))
            assert length > 0, (
                f"Link {link.get('id')}: length={length} must be positive"
            )

    def test_link_speeds_are_positive(self, scenario):
        _, _, links_elem = self._load_network(scenario)
        for link in links_elem.findall("link"):
            speed = float(link.get("speed_limit", "0"))
            assert speed > 0, (
                f"Link {link.get('id')}: speed_limit={speed} must be positive"
            )

    def test_link_lanes_are_positive(self, scenario):
        _, _, links_elem = self._load_network(scenario)
        for link in links_elem.findall("link"):
            lanes = int(link.get("lanes", "1"))
            assert lanes >= 1, (
                f"Link {link.get('id')}: lanes={lanes} must be >= 1"
            )

    def test_metadata_has_units(self, scenario):
        root, _, _ = self._load_network(scenario)
        meta = root.find("metadata")
        assert meta is not None, "Missing <metadata> in network.xml"
        assert meta.get("units_length"), "Missing units_length"
        assert meta.get("units_speed"), "Missing units_speed"


# ===== Demand integrity =====

class TestDemandIntegrity:
    def _load_demand_and_nodes(self, scenario):
        tree = ET.parse(scenario / "network.xml")
        nodes_elem = tree.getroot().find("nodes")
        node_ids = {n.get("id") for n in nodes_elem.findall("node")}

        rows = []
        with (scenario / "demand.csv").open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                rows.append(row)
        return node_ids, rows, fieldnames

    def test_has_required_columns(self, scenario):
        _, _, fieldnames = self._load_demand_and_nodes(scenario)
        required = {"trip_id", "origin_node_id", "destination_node_id",
                     "departure_time_s", "mode"}
        missing = required - set(fieldnames)
        assert not missing, f"Missing columns: {missing}"

    def test_has_trips(self, scenario):
        _, rows, _ = self._load_demand_and_nodes(scenario)
        assert len(rows) > 0, "demand.csv has no trips"

    def test_no_duplicate_trip_ids(self, scenario):
        _, rows, _ = self._load_demand_and_nodes(scenario)
        trip_ids = [r["trip_id"] for r in rows]
        assert len(trip_ids) == len(set(trip_ids)), "Duplicate trip_id values"

    def test_all_origins_in_network(self, scenario):
        node_ids, rows, _ = self._load_demand_and_nodes(scenario)
        bad = [
            (i + 2, r["origin_node_id"])
            for i, r in enumerate(rows)
            if r["origin_node_id"].strip() not in node_ids
        ]
        assert not bad, (
            f"{len(bad)} trip(s) reference non-existent origin nodes: "
            f"{bad[:5]}{'...' if len(bad) > 5 else ''}"
        )

    def test_all_destinations_in_network(self, scenario):
        node_ids, rows, _ = self._load_demand_and_nodes(scenario)
        bad = [
            (i + 2, r["destination_node_id"])
            for i, r in enumerate(rows)
            if r["destination_node_id"].strip() not in node_ids
        ]
        assert not bad, (
            f"{len(bad)} trip(s) reference non-existent destination nodes: "
            f"{bad[:5]}{'...' if len(bad) > 5 else ''}"
        )

    def test_departure_times_are_non_negative(self, scenario):
        _, rows, _ = self._load_demand_and_nodes(scenario)
        for i, r in enumerate(rows):
            dep = int(r["departure_time_s"])
            assert dep >= 0, f"Row {i+2}: negative departure_time_s={dep}"

    def test_departure_times_within_horizon(self, scenario):
        """Trip departures should not exceed the config end time."""
        _, rows, _ = self._load_demand_and_nodes(scenario)
        config_tree = ET.parse(scenario / "config.xml")
        time_elem = config_tree.getroot().find("time")
        end_time = int(time_elem.get("end_time_s", "86400"))

        violations = [
            (i + 2, int(r["departure_time_s"]))
            for i, r in enumerate(rows)
            if int(r["departure_time_s"]) > end_time
        ]
        assert not violations, (
            f"{len(violations)} trip(s) depart after end_time_s={end_time}: "
            f"{violations[:5]}"
        )

    def test_origin_differs_from_destination(self, scenario):
        """Same-node trips can't be routed — they should not appear."""
        _, rows, _ = self._load_demand_and_nodes(scenario)
        same = [
            (i + 2, r["trip_id"])
            for i, r in enumerate(rows)
            if r["origin_node_id"].strip() == r["destination_node_id"].strip()
        ]
        assert not same, (
            f"{len(same)} trip(s) have origin == destination: "
            f"{same[:5]}"
        )

    def test_mode_is_valid(self, scenario):
        valid_modes = {"car", "transit", "bike", "walk"}
        _, rows, _ = self._load_demand_and_nodes(scenario)
        bad_modes = set()
        for r in rows:
            mode = r.get("mode", "").strip()
            if mode not in valid_modes:
                bad_modes.add(mode)
        assert not bad_modes, f"Invalid mode(s) in demand: {bad_modes}"


# ===== Config integrity =====

class TestConfigIntegrity:
    def _load_config(self, scenario):
        tree = ET.parse(scenario / "config.xml")
        return tree.getroot()

    def test_has_metadata(self, scenario):
        root = self._load_config(scenario)
        meta = root.find("metadata")
        assert meta is not None
        sid = meta.get("scenario_id")
        assert sid, "Missing scenario_id in config metadata"

    def test_scenario_id_matches_directory(self, scenario):
        root = self._load_config(scenario)
        meta = root.find("metadata")
        sid = meta.get("scenario_id")
        assert sid == scenario.name, (
            f"Config scenario_id='{sid}' doesn't match directory '{scenario.name}'"
        )

    def test_time_horizon_valid(self, scenario):
        root = self._load_config(scenario)
        time_elem = root.find("time")
        assert time_elem is not None
        start = int(time_elem.get("start_time_s", "-1"))
        end = int(time_elem.get("end_time_s", "-1"))
        assert start >= 0, f"start_time_s={start} is negative"
        assert end > start, f"end_time_s={end} must be > start_time_s={start}"

    def test_has_units(self, scenario):
        root = self._load_config(scenario)
        units = root.find("units")
        assert units is not None
        assert units.get("length") == "meters"
        assert units.get("speed") == "m/s"
        assert units.get("time") == "seconds"

    def test_has_seed(self, scenario):
        root = self._load_config(scenario)
        rand = root.find("random")
        assert rand is not None
        seed = rand.get("seed")
        assert seed is not None
        assert int(seed) >= 0


# ===== Manifest integrity =====

class TestManifestIntegrity:
    def test_scenario_id_matches_config(self, scenario):
        manifest_tree = ET.parse(scenario / "manifest.xml")
        manifest_root = manifest_tree.getroot()
        scenario_elem = manifest_root.find("scenario")
        manifest_id = scenario_elem.get("id") if scenario_elem is not None else None

        config_tree = ET.parse(scenario / "config.xml")
        config_meta = config_tree.getroot().find("metadata")
        config_id = config_meta.get("scenario_id") if config_meta is not None else None

        assert manifest_id == config_id, (
            f"Manifest id='{manifest_id}' != config scenario_id='{config_id}'"
        )

    def test_all_declared_files_exist(self, scenario):
        tree = ET.parse(scenario / "manifest.xml")
        cf = tree.getroot().find("canonical_files")
        assert cf is not None
        for f_elem in cf.findall("file"):
            rel_path = f_elem.get("path")
            ftype = f_elem.get("type")
            full_path = scenario / rel_path
            assert full_path.is_file(), (
                f"Manifest declares {ftype}='{rel_path}' but file doesn't exist"
            )


# ===== Signals integrity =====

class TestSignalsIntegrity:
    def test_signal_nodes_exist_in_network(self, scenario):
        signals_path = scenario / "signals.xml"
        if not signals_path.is_file():
            pytest.skip("No signals.xml")

        net_tree = ET.parse(scenario / "network.xml")
        node_ids = {
            n.get("id")
            for n in net_tree.getroot().find("nodes").findall("node")
        }

        sig_tree = ET.parse(signals_path)
        for junc in sig_tree.getroot().findall("junction"):
            jid = junc.get("node_id")
            assert jid in node_ids, (
                f"Signal junction references node '{jid}' not in network"
            )
