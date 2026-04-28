"""
Tests for the MATSim adapter.

`prepare_matsim_inputs` produces the four MATSim XML files (network, plans,
vehicles, config) from a canonical scenario. These tests exercise file
generation only — no Java or MATSim JAR is required.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from adapters.common import feasible_trip_ids
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



# ---------------------------------------------------------------------------
# Pure helpers
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
            vtype = root.find(".//vehicleType")
        assert vtype is not None, "Should contain vehicleType element"

    def test_car_type_present(self):
        assert 'id="car"' in build_matsim_vehicles_xml()


# ---------------------------------------------------------------------------
# Canonical-network loading + MATSim builders
# ---------------------------------------------------------------------------


class TestLoadCanonicalNetwork:
    def test_loads_nodes_and_links(self, bundled_scenario):
        nodes, links = load_canonical_network(bundled_scenario / "network.xml")
        assert nodes
        assert links

    def test_node_has_coordinates(self, bundled_scenario):
        nodes, _ = load_canonical_network(bundled_scenario / "network.xml")
        for _node_id, node in list(nodes.items())[:5]:
            assert "x" in node and "y" in node
            assert isinstance(node["x"], float)

    def test_link_has_required_fields(self, bundled_scenario):
        _, links = load_canonical_network(bundled_scenario / "network.xml")
        for link in links[:5]:
            for key in ("id", "from", "to", "length", "speed"):
                assert key in link
            assert link["length"] > 0


class TestBuildMATSimNetwork:
    def test_valid_xml_output(self, bundled_scenario):
        nodes, links = load_canonical_network(bundled_scenario / "network.xml")
        root = ET.fromstring(build_matsim_network_xml(nodes, links))
        assert root.tag == "network"

    def test_contains_nodes_and_links(self, bundled_scenario):
        nodes, links = load_canonical_network(bundled_scenario / "network.xml")
        root = ET.fromstring(build_matsim_network_xml(nodes, links))
        xml_nodes = root.findall(".//node")
        xml_links = root.findall(".//link")
        assert len(xml_nodes) == len(nodes)
        # Self-loop removal can shrink links; never grow.
        assert 0 < len(xml_links) <= len(links)

    def test_link_has_car_mode(self, bundled_scenario):
        nodes, links = load_canonical_network(bundled_scenario / "network.xml")
        assert 'modes="car"' in build_matsim_network_xml(nodes, links)


class TestBuildMATSimPlans:
    def _build(self, scenario: Path) -> str:
        _, links = load_canonical_network(scenario / "network.xml")
        feasible, _ = feasible_trip_ids(scenario / "network.xml", scenario / "demand.csv")
        return build_matsim_plans_xml(scenario / "demand.csv", links, feasible)

    def test_valid_xml_output(self, bundled_scenario):
        root = ET.fromstring(self._build(bundled_scenario))
        assert root.tag == "plans"

    def test_contains_persons(self, bundled_scenario):
        root = ET.fromstring(self._build(bundled_scenario))
        assert root.findall("person"), "Plans should contain at least one person"

    def test_person_has_plan_with_activities(self, bundled_scenario):
        root = ET.fromstring(self._build(bundled_scenario))
        person = root.find("person")
        assert person is not None
        plan = person.find("plan")
        assert plan is not None
        assert len(plan.findall("act")) == 2
        assert len(plan.findall("leg")) == 1


class TestBuildMATSimConfig:
    def test_valid_xml_output(self):
        root = ET.fromstring(build_matsim_config_xml(MATSimConfig()))
        assert root.tag == "config"

    def test_contains_required_modules(self):
        xml_str = build_matsim_config_xml(MATSimConfig())
        for mod_name in ("global", "network", "plans", "qsim", "controler"):
            assert f'name="{mod_name}"' in xml_str

    def test_seed_propagated(self):
        assert 'value="12345"' in build_matsim_config_xml(MATSimConfig(), random_seed=12345)


# ---------------------------------------------------------------------------
# End-to-end input preparation
# ---------------------------------------------------------------------------


class TestPrepareMATSimInputs:
    def test_generates_all_files(self, bundled_scenario, tmp_path):
        out = tmp_path / "matsim_out"
        config_path = prepare_matsim_inputs(bundled_scenario, out)

        assert config_path.is_file()
        for name in ("network.xml", "plans.xml", "vehicles.xml"):
            assert (out / name).is_file(), f"Missing MATSim {name}"

    def test_network_xml_is_valid(self, bundled_scenario, tmp_path):
        out = tmp_path / "matsim_net"
        prepare_matsim_inputs(bundled_scenario, out)
        root = ET.parse(out / "network.xml").getroot()
        assert root.tag == "network"
        assert root.findall(".//node")
        assert root.findall(".//link")

    def test_plans_xml_has_persons(self, bundled_scenario, tmp_path):
        out = tmp_path / "matsim_plans"
        prepare_matsim_inputs(bundled_scenario, out)
        root = ET.parse(out / "plans.xml").getroot()
        assert root.findall("person")

    def test_all_scenarios(self, small_bundled_scenarios, tmp_path):
        """Run the MATSim adapter on every small bundled scenario."""
        if not small_bundled_scenarios:
            pytest.skip("No bundled scenarios to sweep")

        for scenario_path in small_bundled_scenarios:
            out = tmp_path / scenario_path.name
            config_path = prepare_matsim_inputs(scenario_path, out)
            assert config_path.is_file(), f"{scenario_path.name}: no config"
            assert (out / "network.xml").is_file()
            assert (out / "plans.xml").is_file()
