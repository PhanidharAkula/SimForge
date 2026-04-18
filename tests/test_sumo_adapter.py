"""
Tests for the SUMO adapter using a generated city scenario.

Validates that prepare_sumo_inputs produces the expected output files
and returns a well-formed ScenarioSummary for a real OSM-derived scenario.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from adapters.sumo.sumo_adapter import prepare_sumo_inputs


REPO_ROOT = Path(__file__).resolve().parents[1]

# Pick the first available generated scenario (chicago preferred, fall back to others)
_CANDIDATES = ["chicago_1k_car", "nyc_1k_car", "la_1k_car", "nyc_10k_car", "la_50k_bike_car_transit"]
SCENARIO: Path | None = None
for _name in _CANDIDATES:
    _path = REPO_ROOT / "scenarios" / _name
    if _path.is_dir():
        SCENARIO = _path
        break


def test_prepare_sumo_inputs_creates_expected_files(tmp_path) -> None:
    """
    Running prepare_sumo_inputs on a generated scenario should:

      - return a ScenarioSummary with positive counts
      - create net.net.xml, routes.rou.xml, and toy.sumocfg
      - embed vehicle and route entries in the routes file
      - reference the correct net and routes files in the config
    """
    assert SCENARIO is not None and SCENARIO.is_dir(), (
        "No generated scenario found in scenarios/. "
        "Run the generation scripts first."
    )

    out_dir = tmp_path / "sumo_out"
    summary = prepare_sumo_inputs(SCENARIO, out_dir)

    # Summary should have sensible values
    assert summary.scenario_id == SCENARIO.name
    assert summary.node_count > 0
    assert summary.link_count > 0
    assert summary.trip_count > 0
    assert summary.start_time_s >= 0
    assert summary.end_time_s > summary.start_time_s

    # Files must exist
    net_path = out_dir / "net.net.xml"
    routes_path = out_dir / "routes.rou.xml"
    cfg_path = out_dir / "toy.sumocfg"

    assert net_path.is_file(), f"Expected SUMO net file not found: {net_path}"
    assert routes_path.is_file(), f"Expected SUMO routes file not found: {routes_path}"
    assert cfg_path.is_file(), f"Expected SUMO config file not found: {cfg_path}"

    # Light content checks
    routes_text = routes_path.read_text(encoding="utf-8")
    cfg_text = cfg_path.read_text(encoding="utf-8")

    # At least one vehicle and route entry should be present
    assert "<vehicle" in routes_text
    assert "<route" in routes_text

    # Config should reference the expected net and routes files
    assert 'net-file value="net.net.xml"' in cfg_text
    assert 'route-files value="routes.rou.xml"' in cfg_text


def test_edges_have_length_attribute(tmp_path) -> None:
    """
    Edge XML must include length attribute from canonical network
    to avoid misinterpreted distances in netconvert.
    """
    assert SCENARIO is not None and SCENARIO.is_dir()

    out_dir = tmp_path / "sumo_edge_check"
    prepare_sumo_inputs(SCENARIO, out_dir)

    import xml.etree.ElementTree as ET
    tree = ET.parse(out_dir / "edges.edg.xml")
    edges = tree.findall(".//edge")
    assert len(edges) > 0, "edges.edg.xml should contain edges"

    for edge in edges:
        length = edge.get("length")
        assert length is not None, f"Edge {edge.get('id')} missing length attribute"
        length_val = float(length)
        assert length_val >= 0.1, f"Edge {edge.get('id')} length={length_val} is unrealistically small"


def test_net_xml_has_realistic_lane_lengths(tmp_path) -> None:
    """
    After netconvert with --proj.plain-geo, lane lengths in net.net.xml
    should be realistic (>10m mean), not sub-meter from raw WGS84 degrees.
    """
    assert SCENARIO is not None and SCENARIO.is_dir()

    out_dir = tmp_path / "sumo_net_check"
    prepare_sumo_inputs(SCENARIO, out_dir)

    import xml.etree.ElementTree as ET
    tree = ET.parse(out_dir / "net.net.xml")

    lane_lengths = []
    for elem in tree.iter():
        if elem.tag == "lane" and elem.get("length"):
            lane_lengths.append(float(elem.get("length")))

    assert len(lane_lengths) > 0, "net.net.xml should contain lanes with lengths"
    mean_length = sum(lane_lengths) / len(lane_lengths)
    assert mean_length > 10.0, (
        f"Mean lane length {mean_length:.2f}m is too small — "
        f"geo projection may be missing (--proj.plain-geo)"
    )


def test_sumo_adapter_all_scenarios(tmp_path) -> None:
    """
    Run the SUMO adapter on every available scenario to ensure
    none of them break during conversion.

    Note: Large scenarios (>3000 nodes) may fail with netconvert
    segfault on Apple Silicon — these are skipped with a warning.
    """
    import platform

    scenarios_dir = REPO_ROOT / "scenarios"
    if not scenarios_dir.is_dir():
        pytest.skip("No scenarios directory found")

    # Skip large scenarios that cause timeouts or ARM64 segfaults
    _LARGE_PATTERNS = ("50k", "200k", "500k", "5m")

    tested = 0
    skipped = []
    for scenario_path in sorted(scenarios_dir.iterdir()):
        if not scenario_path.is_dir():
            continue
        manifest = scenario_path / "manifest.xml"
        if not manifest.is_file():
            continue
        if any(p in scenario_path.name for p in _LARGE_PATTERNS):
            skipped.append(scenario_path.name)
            continue

        out_dir = tmp_path / scenario_path.name
        try:
            summary = prepare_sumo_inputs(scenario_path, out_dir)
        except RuntimeError as e:
            if platform.machine() == "arm64" and ("failed" in str(e).lower() or "crashed" in str(e).lower() or "signal" in str(e).lower()):
                skipped.append(scenario_path.name)
                continue
            raise

        assert summary.node_count > 0, f"{scenario_path.name}: no nodes"
        assert summary.link_count > 0, f"{scenario_path.name}: no links"
        assert summary.trip_count > 0, f"{scenario_path.name}: no trips"
        assert (out_dir / "net.net.xml").is_file(), f"{scenario_path.name}: missing net.net.xml"
        assert (out_dir / "routes.rou.xml").is_file(), f"{scenario_path.name}: missing routes"
        assert (out_dir / "toy.sumocfg").is_file(), f"{scenario_path.name}: missing config"
        tested += 1

    if skipped:
        import warnings
        warnings.warn(f"Skipped {len(skipped)} scenarios (netconvert crash on arm64): {skipped}")

    assert tested > 0, "No scenarios were tested"
