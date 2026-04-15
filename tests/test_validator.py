"""
Tests for the canonical bundle validator using generated city scenarios.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

from pipeline.validation.validate_bundle import validate_bundle


REPO_ROOT = Path(__file__).resolve().parents[1]

# Pick the first available generated scenario
_CANDIDATES = ["chicago_1k_car", "nyc_10k_car", "la_50k_bike_car_transit"]
SCENARIO: Path | None = None
for _name in _CANDIDATES:
    _path = REPO_ROOT / "scenarios" / _name
    if _path.is_dir():
        SCENARIO = _path
        break


def test_generated_bundle_is_valid() -> None:
    """
    A generated scenario bundle should pass the validator.
    """
    assert SCENARIO is not None and SCENARIO.is_dir(), (
        "No generated scenario found. Run the generation scripts first."
    )
    ok = validate_bundle(SCENARIO)
    assert ok, f"Expected scenario {SCENARIO.name} to be VALID"


def test_bundle_with_bad_node_in_demand_is_invalid(tmp_path) -> None:
    """
    Copy a scenario, inject a bogus origin node, and confirm the validator
    marks the bundle as INVALID.
    """
    assert SCENARIO is not None and SCENARIO.is_dir(), (
        "No generated scenario found. Run the generation scripts first."
    )

    tmp_scenario = tmp_path / f"{SCENARIO.name}_bad"
    shutil.copytree(SCENARIO, tmp_scenario)

    demand_path = tmp_scenario / "demand.csv"
    assert demand_path.is_file()

    # Read, corrupt, write back
    rows = []
    with demand_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        assert fieldnames is not None
        for row in reader:
            rows.append(row)

    assert rows, "Expected at least one row in demand.csv"
    rows[0]["origin_node_id"] = "n999999"  # non-existent node

    with demand_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    ok = validate_bundle(tmp_scenario)
    assert not ok, "Validator should fail when demand references a non-existent node"
