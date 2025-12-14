from __future__ import annotations

"""
Tests for the canonical bundle validator using the toy_2x2_grid scenario.
"""

import csv
import shutil
from pathlib import Path

from pipeline.validation.validate_bundle import validate_bundle


REPO_ROOT = Path(__file__).resolve().parents[1]
TOY_SCENARIO = REPO_ROOT / "scenarios" / "toy_2x2_grid"


def test_toy_bundle_is_valid() -> None:
    """
    Sanity check: the committed toy_2x2_grid bundle should validate successfully.
    """
    assert TOY_SCENARIO.is_dir(), f"Scenario directory not found: {TOY_SCENARIO}"
    ok = validate_bundle(TOY_SCENARIO)
    assert ok, "Expected toy_2x2_grid scenario to be VALID"


def test_toy_bundle_with_bad_node_in_demand_is_invalid(tmp_path) -> None:
    """
    Copy the toy scenario to a temp directory, intentionally corrupt demand.csv,
    and confirm that the validator marks the bundle as INVALID.
    """
    # 1. Copy the scenario into a temp directory so we don't touch the real files
    tmp_scenario_root = tmp_path / "toy_2x2_grid_bad"
    shutil.copytree(TOY_SCENARIO, tmp_scenario_root)

    demand_path = tmp_scenario_root / "demand.csv"
    assert demand_path.is_file(), f"Copied demand.csv not found at {demand_path}"

    # 2. Read all demand rows and inject a bogus origin node for the first trip
    rows = []
    with demand_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        assert fieldnames is not None, "demand.csv must have a header row"
        for row in reader:
            rows.append(row)

    assert rows, "Expected at least one row in demand.csv to corrupt"

    # Corrupt the origin_node_id for the first trip
    rows[0]["origin_node_id"] = "n999"  # definitely not in the network

    # 3. Write back the corrupted demand.csv
    with demand_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # 4. Run the validator; expect INVALID
    ok = validate_bundle(tmp_scenario_root)
    assert not ok, "Validator should fail when demand references a non-existent node"