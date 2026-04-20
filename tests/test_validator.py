"""
Tests for the canonical bundle validator using a real bundled scenario.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

from pipeline.validation.validate_bundle import validate_bundle


def test_generated_bundle_is_valid(bundled_scenario: Path) -> None:
    """A bundled scenario must pass the validator unmodified."""
    assert validate_bundle(bundled_scenario), (
        f"Expected scenario {bundled_scenario.name} to be VALID"
    )


def test_bundle_with_bad_node_in_demand_is_invalid(bundled_scenario: Path, tmp_path: Path) -> None:
    """Inject a bogus origin node and confirm the validator rejects the bundle."""
    bad = tmp_path / f"{bundled_scenario.name}_bad"
    shutil.copytree(bundled_scenario, bad)

    demand_path = bad / "demand.csv"
    rows: list[dict] = []
    with demand_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        assert fieldnames is not None
        rows.extend(reader)
    assert rows
    rows[0]["origin_node_id"] = "n999999"

    with demand_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    assert not validate_bundle(bad), (
        "Validator should fail when demand references a non-existent node"
    )
