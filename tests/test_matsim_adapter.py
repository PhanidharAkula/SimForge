"""
Tests for the MATSim adapter.

Validates that prepare_matsim_inputs produces correctly structured
MATSim XML files (network, plans, vehicles, config) from a canonical
scenario bundle. Does NOT require Java or a MATSim JAR — only tests
file generation.
"""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from adapters.matsim.matsim_adapter import (
    MATSimConfig,
    build_matsim_config_xml,
    build_matsim_network_xml,
    build_matsim_plans_xml,
    build_matsim_vehicles_xml,
    load_canonical_network,
    prepare_matsim_inputs,
    seconds_to_time_string,
)


REPO_ROOT = Path(__file__).resolve().parents[1]

_CANDIDATES = ["chicago_1k_car", "nyc_1k_car", "la_1k_car"]
SCENARIO: Path | None = None
for _name in _CANDIDATES:
    _path = REPO_ROOT / "scenarios" / _name
    if _path.is_dir():
        SCENARIO = _path
        break


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------

class TestSecondsToTimeString:
    def test_midnight(self):
        assert seconds_to_time_string(0) == "00:00:00"

    def test_morning(self):
        assert seconds_to_time_string(25200) == "07:00:00"

    def test_end_of_day(self):
        assert seconds_to_time_string(86400) == "24:00:00"

    def test_arbitrary(self):
        assert seconds_to_time_string(45296) == "12:34:56"


class TestMATSimConfig:
    def test_defaults(self):
        cfg = MATSimConfig()
        assert cfg.iterations == 0
        assert cfg.flow_capacity_factor == 1.0
        assert cfg.java_heap_gb == 4

    def test_to_dict(self):
        cfg = MATSimConfig(iterations=5, java_heap_gb=8)
        d = cfg.to_dict()
        assert d["iterations"] == 5
        assert d["java_heap_gb"] == 8


class TestBuildVehiclesXml:
    def test_produces_valid_xml(self):
        xml_str = build_matsim_vehicles_xml()
        root = ET.fromstring(xml_str)
        assert "vehicleDefinitions" in root.tag
        vtype = root.find(".//{http://www.matsim.org/files/dtd}vehicleType")
        if vtype is None:
            # Try without namespace
            vtype = root.find(".//vehicleType")
        assert vtype is not None, "Should contain vehicleType element"

    def test_car_type_present(self):
        xml_str = build_matsim_vehicles_xml()
        assert 'id="car"' in xml_str


# ---------------------------------------------------------------------------
# Integration tests with real scenarios
# ---------------------------------------------------------------------------

class TestLoadCanonicalNetwork:
    def test_loads_nodes_and_links(self):
        assert SCENARIO is not None, "No scenario available"
        network_path = SCENARIO / "network.xml"
        nodes, links = load_canonical_network(network_path)
        assert len(nodes) > 0, "Should load nodes from network.xml"
        assert len(links) > 0, "Should load links from network.xml"

    def test_node_has_coordinates(self):
        assert SCENARIO is not None
        nodes, _ = load_canonical_network(SCENARIO / "network.xml")
        for _node_id, node in list(nodes.items())[:5]:
            assert "x" in node
            assert "y" in node
            assert isinstance(node["x"], float)

    def test_link_has_required_fields(self):
        assert SCENARIO is not None
        _, links = load_canonical_network(SCENARIO / "network.xml")
        for link in links[:5]:
            assert "id" in link
            assert "from" in link
            assert "to" in link
            assert "length" in link
            assert "speed" in link
            assert link["length"] > 0


class TestBuildMATSimNetwork:
    def test_valid_xml_output(self):
        assert SCENARIO is not None
        nodes, links = load_canonical_network(SCENARIO / "network.xml")
        xml_str = build_matsim_network_xml(nodes, links)
        root = ET.fromstring(xml_str)
        assert root.tag == "network"

    def test_contains_nodes_and_links(self):
        assert SCENARIO is not None
        nodes, links = load_canonical_network(SCENARIO / "network.xml")
        xml_str = build_matsim_network_xml(nodes, links)
        root = ET.fromstring(xml_str)
        xml_nodes = root.findall(".//node")
        xml_links = root.findall(".//link")
        assert len(xml_nodes) == len(nodes)
        # Links may exclude self-loops
        assert len(xml_links) <= len(links)
        assert len(xml_links) > 0

    def test_link_has_car_mode(self):
        assert SCENARIO is not None
        nodes, links = load_canonical_network(SCENARIO / "network.xml")
        xml_str = build_matsim_network_xml(nodes, links)
        assert 'modes="car"' in xml_str


class TestBuildMATSimPlans:
    def test_valid_xml_output(self):
        assert SCENARIO is not None
        _, links = load_canonical_network(SCENARIO / "network.xml")
        from adapters.common import feasible_trip_ids
        feasible, _ = feasible_trip_ids(SCENARIO / "network.xml", SCENARIO / "demand.csv")
        xml_str = build_matsim_plans_xml(SCENARIO / "demand.csv", links, feasible)
        root = ET.fromstring(xml_str)
        assert root.tag == "plans"

    def test_contains_persons(self):
        assert SCENARIO is not None
        _, links = load_canonical_network(SCENARIO / "network.xml")
        from adapters.common import feasible_trip_ids
        feasible, _ = feasible_trip_ids(SCENARIO / "network.xml", SCENARIO / "demand.csv")
        xml_str = build_matsim_plans_xml(SCENARIO / "demand.csv", links, feasible)
        root = ET.fromstring(xml_str)
        persons = root.findall("person")
        assert len(persons) > 0, "Plans should contain at least one person"

    def test_person_has_plan_with_activities(self):
        assert SCENARIO is not None
        _, links = load_canonical_network(SCENARIO / "network.xml")
        from adapters.common import feasible_trip_ids
        feasible, _ = feasible_trip_ids(SCENARIO / "network.xml", SCENARIO / "demand.csv")
        xml_str = build_matsim_plans_xml(SCENARIO / "demand.csv", links, feasible)
        root = ET.fromstring(xml_str)
        person = root.find("person")
        assert person is not None
        plan = person.find("plan")
        assert plan is not None
        acts = plan.findall("act")
        legs = plan.findall("leg")
        assert len(acts) == 2, "Each plan should have home and work activities"
        assert len(legs) == 1, "Each plan should have one leg (trip)"


class TestBuildMATSimConfig:
    def test_valid_xml_output(self):
        cfg = MATSimConfig()
        xml_str = build_matsim_config_xml(cfg)
        root = ET.fromstring(xml_str)
        assert root.tag == "config"

    def test_contains_required_modules(self):
        cfg = MATSimConfig()
        xml_str = build_matsim_config_xml(cfg)
        required_modules = ["global", "network", "plans", "qsim", "controler"]
        for mod_name in required_modules:
            assert f'name="{mod_name}"' in xml_str, f"Missing module: {mod_name}"

    def test_seed_propagated(self):
        cfg = MATSimConfig()
        xml_str = build_matsim_config_xml(cfg, random_seed=12345)
        assert 'value="12345"' in xml_str


class TestPrepareMATSimInputs:
    def test_generates_all_files(self, tmp_path):
        assert SCENARIO is not None, "No scenario available"
        out = tmp_path / "matsim_out"
        config_path = prepare_matsim_inputs(SCENARIO, out)

        assert config_path.is_file(), "Should return path to config.xml"
        assert (out / "network.xml").is_file(), "Missing MATSim network.xml"
        assert (out / "plans.xml").is_file(), "Missing MATSim plans.xml"
        assert (out / "vehicles.xml").is_file(), "Missing MATSim vehicles.xml"

    def test_network_xml_is_valid(self, tmp_path):
        assert SCENARIO is not None
        out = tmp_path / "matsim_net"
        prepare_matsim_inputs(SCENARIO, out)

        tree = ET.parse(out / "network.xml")
        root = tree.getroot()
        assert root.tag == "network"
        nodes = root.findall(".//node")
        links = root.findall(".//link")
        assert len(nodes) > 0
        assert len(links) > 0

    def test_plans_xml_has_persons(self, tmp_path):
        assert SCENARIO is not None
        out = tmp_path / "matsim_plans"
        prepare_matsim_inputs(SCENARIO, out)

        tree = ET.parse(out / "plans.xml")
        root = tree.getroot()
        persons = root.findall("person")
        assert len(persons) > 0

    def test_all_scenarios(self, tmp_path):
        """Run MATSim adapter on all available scenarios."""
        scenarios_dir = REPO_ROOT / "scenarios"
        # Skip large scenarios that cause timeouts
        _LARGE_PATTERNS = ("50k", "200k", "500k", "5m")
        tested = 0
        skipped = []
        for scenario_path in sorted(scenarios_dir.iterdir()):
            if not scenario_path.is_dir():
                continue
            if not (scenario_path / "manifest.xml").is_file():
                continue
            if any(p in scenario_path.name for p in _LARGE_PATTERNS):
                skipped.append(scenario_path.name)
                continue

            out = tmp_path / scenario_path.name
            config_path = prepare_matsim_inputs(scenario_path, out)

            assert config_path.is_file(), f"{scenario_path.name}: no config"
            assert (out / "network.xml").is_file(), f"{scenario_path.name}: no network"
            assert (out / "plans.xml").is_file(), f"{scenario_path.name}: no plans"
            tested += 1

        if skipped:
            import warnings
            warnings.warn(f"Skipped {len(skipped)} large scenarios: {skipped}")

        assert tested > 0, "No scenarios tested"
