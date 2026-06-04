"""
Tests for the SUMO adapter.

`prepare_sumo_inputs` must produce a complete, plausible SUMO input bundle
for any canonical scenario. Lane-length and edge-length sanity checks guard
against the projection-missing class of bugs (raw WGS84 degrees getting
interpreted as metres).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from adapters.sumo.sumo_adapter import prepare_sumo_inputs

from .conftest import is_arm64_netconvert_crash, warn_skipped


def _prepare_or_skip(scenario: Path, out: Path):
    """Call `prepare_sumo_inputs`, skipping the test on a known arm64 netconvert crash.

    The bundled scenarios can exceed SUMO 1.26's macOS arm64 `netconvert`
    threshold (~3K nodes), chicago_1k_car under osmnx 2.x extracts ~20K
    nodes once denser highway types are included. Linux CI handles them
    fine; on macOS arm64 we skip cleanly so the suite stays green.
    """
    try:
        return prepare_sumo_inputs(scenario, out)
    except RuntimeError as exc:
        if is_arm64_netconvert_crash(exc):
            pytest.skip(
                f"arm64 netconvert can't process {scenario.name} "
                f"({exc.args[0].splitlines()[0][:120]})"
            )
        raise


@pytest.mark.requires_sumo
def test_prepare_sumo_inputs_creates_expected_files(bundled_scenario: Path, tmp_path: Path) -> None:
    out = tmp_path / "sumo_out"
    summary = _prepare_or_skip(bundled_scenario, out)

    assert summary.scenario_id == bundled_scenario.name
    assert summary.node_count > 0
    assert summary.link_count > 0
    assert summary.trip_count > 0
    assert summary.start_time_s >= 0
    assert summary.end_time_s > summary.start_time_s

    for name in ("net.net.xml", "routes.rou.xml", "toy.sumocfg"):
        assert (out / name).is_file(), f"Missing SUMO output: {name}"

    routes_text = (out / "routes.rou.xml").read_text(encoding="utf-8")
    cfg_text = (out / "toy.sumocfg").read_text(encoding="utf-8")
    assert "<vehicle" in routes_text
    assert "<route" in routes_text
    assert 'net-file value="net.net.xml"' in cfg_text
    assert 'route-files value="routes.rou.xml"' in cfg_text


@pytest.mark.requires_sumo
def test_edges_have_length_attribute(bundled_scenario: Path, tmp_path: Path) -> None:
    """Edges must carry an explicit `length` so netconvert doesn't recompute it."""
    out = tmp_path / "sumo_edge_check"
    _prepare_or_skip(bundled_scenario, out)

    edges = ET.parse(out / "edges.edg.xml").findall(".//edge")
    assert edges, "edges.edg.xml should contain edges"
    for edge in edges:
        length = edge.get("length")
        assert length is not None, f"Edge {edge.get('id')} missing length attribute"
        assert float(length) >= 0.1, (
            f"Edge {edge.get('id')} length={length} m is unrealistically small"
        )


@pytest.mark.requires_sumo
def test_net_xml_has_realistic_lane_lengths(bundled_scenario: Path, tmp_path: Path) -> None:
    """Mean lane length must be > 10 m, guards against raw-WGS84 lengths."""
    out = tmp_path / "sumo_net_check"
    _prepare_or_skip(bundled_scenario, out)

    lane_lengths = [
        float(elem.get("length"))
        for elem in ET.parse(out / "net.net.xml").iter()
        if elem.tag == "lane" and elem.get("length")
    ]
    assert lane_lengths, "net.net.xml should contain lanes with lengths"
    mean_length = sum(lane_lengths) / len(lane_lengths)
    assert mean_length > 10.0, (
        f"Mean lane length {mean_length:.2f} m is too small — "
        "geo projection (--proj.plain-geo) may be missing"
    )


@pytest.mark.requires_sumo
def test_sumo_adapter_all_scenarios(small_bundled_scenarios: list[Path], tmp_path: Path) -> None:
    """
    Every small bundled scenario must convert without errors. Large scenarios
    (≥50 K trips) are excluded because SUMO 1.20's arm64 `netconvert` segfaults
    above ~3 000 nodes.
    """
    if not small_bundled_scenarios:
        pytest.skip("No bundled scenarios to sweep")

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
        assert summary.trip_count > 0
        for name in ("net.net.xml", "routes.rou.xml", "toy.sumocfg"):
            assert (out / name).is_file(), f"{scenario_path.name}: missing {name}"
        tested += 1

    warn_skipped("SUMO sweep", skipped)
    if tested == 0:
        pytest.skip(
            f"All {len(skipped)} candidate scenarios were filtered "
            f"by the arm64 netconvert detector."
        )
