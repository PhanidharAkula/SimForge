"""
Tests for the MATSim adapter.

`prepare_matsim_inputs` produces the four MATSim XML files (network, plans,
vehicles, config) from a canonical scenario. These tests exercise file
generation only, no Java or MATSim JAR is required.

The expensive code paths (state-aware BFS pre-routing in
`build_matsim_plans_xml`, full `prepare_matsim_inputs` runs) are shared via
session-scoped fixtures so identical work is not repeated across N
read-only assertions. Determinism of those paths is enforced separately
in `tests/test_adapter_determinism.py`, this file checks structure only.
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
# Session-scoped fixtures (cache expensive prepare/build work across tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def canonical_network_data(bundled_scenario):
    """`(nodes, links)` from the bundled scenario's network.xml, loaded once."""
    return load_canonical_network(bundled_scenario / "network.xml")


@pytest.fixture(scope="session")
def built_network_xml(canonical_network_data):
    """MATSim network XML string, built once per session."""
    nodes, links = canonical_network_data
    return build_matsim_network_xml(nodes, links)


@pytest.fixture(scope="session")
def built_plans_xml(bundled_scenario, canonical_network_data):
    """MATSim plans XML string, built once per session.

    This is the expensive call: state-aware BFS pre-routing runs once per
    trip × N turn restrictions in network.xml. Caching it here drops the
    `TestBuildMATSimPlans` class from ~30 s to ~10 s on chicago_1k_car.
    """
    _, links = canonical_network_data
    feasible, _ = feasible_trip_ids(
        bundled_scenario / "network.xml",
        bundled_scenario / "demand.csv",
    )
    return build_matsim_plans_xml(
        bundled_scenario / "demand.csv", links, feasible,
        network_path=bundled_scenario / "network.xml",
    )


@pytest.fixture(scope="session")
def prepared_chicago(bundled_scenario, tmp_path_factory):
    """Full `prepare_matsim_inputs(chicago_1k_car)` run once per session.

    The 4 read-only tests in `TestPrepareMATSimInputs` consume this
    fixture instead of re-preparing per test. Drops their combined wall
    time from ~40 s to ~10 s on chicago_1k_car.
    """
    out = tmp_path_factory.mktemp("matsim_prepared")
    config_path = prepare_matsim_inputs(bundled_scenario, out)
    return out, config_path


@pytest.fixture(scope="session")
def prepared_sweep(small_bundled_scenarios, tmp_path_factory):
    """Map of every small bundled scenario → its prepared MATSim output.

    The state-aware BFS pre-routing in `build_matsim_plans_xml` is O(trips)
    and dominates wall time on the bigger bundles (nyc_10k_car: ~5-7 min
    of BFS for 10K trips). Caching the prepared bundle once per session
    is the single biggest speedup in this file.
    """
    if not small_bundled_scenarios:
        return {}
    base = tmp_path_factory.mktemp("matsim_sweep")
    prepared: dict[Path, tuple[Path, Path]] = {}
    for scenario_path in small_bundled_scenarios:
        out = base / scenario_path.name
        config_path = prepare_matsim_inputs(scenario_path, out)
        prepared[scenario_path] = (out, config_path)
    return prepared



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
    def test_loads_nodes_and_links(self, canonical_network_data):
        nodes, links = canonical_network_data
        assert nodes
        assert links

    def test_node_has_coordinates(self, canonical_network_data):
        nodes, _ = canonical_network_data
        for _node_id, node in list(nodes.items())[:5]:
            assert "x" in node and "y" in node
            assert isinstance(node["x"], float)

    def test_link_has_required_fields(self, canonical_network_data):
        _, links = canonical_network_data
        for link in links[:5]:
            for key in ("id", "from", "to", "length", "speed"):
                assert key in link
            assert link["length"] > 0


class TestBuildMATSimNetwork:
    def test_valid_xml_output(self, built_network_xml):
        root = ET.fromstring(built_network_xml)
        assert root.tag == "network"

    def test_contains_nodes_and_links(self, built_network_xml, canonical_network_data):
        nodes, links = canonical_network_data
        root = ET.fromstring(built_network_xml)
        xml_nodes = root.findall(".//node")
        xml_links = root.findall(".//link")
        assert len(xml_nodes) == len(nodes)
        # Self-loop removal can shrink links; never grow.
        assert 0 < len(xml_links) <= len(links)

    def test_link_has_car_mode(self, built_network_xml):
        assert 'modes="car"' in built_network_xml


class TestBuildMATSimPlans:
    def test_valid_xml_output(self, built_plans_xml):
        # V11.2 migrated from plans_v4 (<plans>/<act>) to population_v6
        # (<population>/<activity>), see CHANGELOG Phase 11.2 for the
        # rationale (plans_v4 rejected V5 Phase 7's `<route type="links">`).
        root = ET.fromstring(built_plans_xml)
        assert root.tag == "population"

    def test_contains_persons(self, built_plans_xml):
        root = ET.fromstring(built_plans_xml)
        assert root.findall("person"), "Population should contain at least one person"

    def test_person_has_plan_with_activities(self, built_plans_xml):
        root = ET.fromstring(built_plans_xml)
        person = root.find("person")
        assert person is not None
        plan = person.find("plan")
        assert plan is not None
        # population_v6 element name is `<activity>`, not plans_v4's `<act>`.
        assert len(plan.findall("activity")) == 2
        assert len(plan.findall("leg")) == 1

    def test_route_text_includes_start_and_end_links(self, built_plans_xml):
        """MATSim 15 / population_v6 expects the <route type="links"> text
        to be the FULL link sequence (including start_link as first token
        and end_link as last token), NOT just the interior. Confirmed
        against MATSim's own output_plans.xml.gz format. Pre-V12 SimForge
        emitted only the interior; MATSim's mobsim then rejected every
        transition with `DefaultTurnAcceptanceLogic` "Cannot move vehicle"
        warnings and output_trips.csv.gz ended up empty (zero trips →
        zero std → trivial R = 1.0000 that read as perfect determinism
        but was actually no determinism at all). See CHANGELOG Phase 12
        "MATSim route text format".
        """
        root = ET.fromstring(built_plans_xml)
        for person in root.findall("person"):
            plan = person.find("plan")
            assert plan is not None
            leg = plan.find("leg")
            if leg is None:
                continue
            route = leg.find("route")
            if route is None or route.get("type") != "links":
                # Some plans fall back to MATSim's own routing
                # (no `<route>` element); those are exempt from this check.
                continue
            start = route.get("start_link")
            end = route.get("end_link")
            assert start, f"{person.get('id')}: route missing start_link"
            assert end, f"{person.get('id')}: route missing end_link"
            tokens = (route.text or "").split()
            assert tokens, f"{person.get('id')}: route text is empty"
            assert tokens[0] == start, (
                f"{person.get('id')}: route text first token {tokens[0]!r} "
                f"must equal start_link {start!r} (MATSim 15 idiom)"
            )
            assert tokens[-1] == end, (
                f"{person.get('id')}: route text last token {tokens[-1]!r} "
                f"must equal end_link {end!r} (MATSim 15 idiom)"
            )

    def test_route_start_link_matches_start_activity_link(self, built_plans_xml):
        """The route's start_link must equal the link of the preceding
        activity (because the agent is physically *on* that link when the
        leg starts). Same for end_link / next-activity link. Pre-V12 the
        adapter emitted route start_link = first BFS-derived edge instead
        of the activity link, leaving the agent unable to begin the leg.
        """
        root = ET.fromstring(built_plans_xml)
        for person in root.findall("person"):
            plan = person.find("plan")
            assert plan is not None
            activities = plan.findall("activity")
            leg = plan.find("leg")
            if leg is None or len(activities) < 2:
                continue
            route = leg.find("route")
            if route is None:
                continue
            assert route.get("start_link") == activities[0].get("link"), (
                f"{person.get('id')}: route start_link "
                f"{route.get('start_link')!r} ≠ start activity link "
                f"{activities[0].get('link')!r}"
            )
            assert route.get("end_link") == activities[1].get("link"), (
                f"{person.get('id')}: route end_link "
                f"{route.get('end_link')!r} ≠ end activity link "
                f"{activities[1].get('link')!r}"
            )


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
    def test_generates_all_files(self, prepared_chicago):
        out, config_path = prepared_chicago
        assert config_path.is_file()
        for name in ("network.xml", "plans.xml", "vehicles.xml"):
            assert (out / name).is_file(), f"Missing MATSim {name}"

    def test_network_xml_is_valid(self, prepared_chicago):
        out, _ = prepared_chicago
        root = ET.parse(out / "network.xml").getroot()
        assert root.tag == "network"
        assert root.findall(".//node")
        assert root.findall(".//link")

    def test_plans_xml_has_persons(self, prepared_chicago):
        out, _ = prepared_chicago
        root = ET.parse(out / "plans.xml").getroot()
        assert root.findall("person")

    def test_all_scenarios(self, prepared_sweep):
        """Verify the MATSim adapter prepared every small bundled scenario."""
        if not prepared_sweep:
            pytest.skip("No bundled scenarios to sweep")

        for scenario_path, (out, config_path) in prepared_sweep.items():
            assert config_path.is_file(), f"{scenario_path.name}: no config"
            assert (out / "network.xml").is_file()
            assert (out / "plans.xml").is_file()
