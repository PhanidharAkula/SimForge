"""
Tests for the SUMO adapter using a generated city scenario.

Validates that prepare_sumo_inputs produces the expected output files
and returns a well-formed ScenarioSummary for a real OSM-derived scenario.
"""

from __future__ import annotations

from pathlib import Path

from adapters.sumo.sumo_adapter import prepare_sumo_inputs


REPO_ROOT = Path(__file__).resolve().parents[1]

# Pick the first available generated scenario (chicago preferred, fall back to others)
_CANDIDATES = ["chicago_5k", "nyc_5k", "la_5k"]
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
        f"No generated scenario found in scenarios/. "
        f"Run the generation scripts first."
    )

    out_dir = tmp_path / "sumo_out"
    summary = prepare_sumo_inputs(SCENARIO, out_dir)

    # Summary should have sensible values
    assert summary.scenario_id == SCENARIO.name
    assert summary.node_count > 0
    assert summary.link_count > 0
    assert summary.trip_count > 0
    assert summary.start_time_s == 0
    assert summary.end_time_s == 3600

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
