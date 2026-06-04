"""Tests for `evaluation.demand_composition`.

Verifies that audit_fairness and analyze_benchmark can correctly answer
"what fraction of AM peak is school-related?" from a V5+ demand.csv,
and gracefully no-op on pre-V5 bundles missing the `purpose` column.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evaluation.demand_composition import (
    CHAIN_LEG_PURPOSES,
    find_canonical_demand,
    format_composition_report,
    read_demand_composition,
)


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_reads_v5_demand_with_purpose(tmp_path: Path):
    """Happy path: a V5+ demand.csv with all six purpose categories."""
    demand = tmp_path / "demand.csv"
    _write(demand, [
        "trip_id,origin_node_id,destination_node_id,departure_time_s,mode,dest_source,purpose",
        "t0,n1,n2,28000,car,schedule,HBW_AM",
        "t1,n1,n2,28000,car,schedule,HBW_AM",
        "t2,n1,n3,28000,car,schedule,HBSchool_AM",
        "t3,n3,n2,28000,car,schedule,HBW_AM_chained",
        "t4,n2,n1,61000,car,schedule,HBW_PM",
        "t5,n2,n3,61000,car,schedule,HBW_PM_chained",
        "t6,n3,n1,61000,car,schedule,HBSchool_PM",
    ])
    comp = read_demand_composition(demand)
    assert comp is not None
    assert comp["total"] == 7
    # AM_PURPOSES: HBW_AM (×2) + HBSchool_AM + HBW_AM_chained = 4
    assert comp["am_peak"] == 4
    # PM_PURPOSES: HBW_PM + HBW_PM_chained + HBSchool_PM = 3
    assert comp["pm_peak"] == 3
    # Chain legs: HBSchool_AM + HBW_AM_chained + HBW_PM_chained + HBSchool_PM = 4
    assert comp["chain_legs"] == 4
    assert comp["school_chains_am"] == 1
    assert comp["school_chains_pm"] == 1
    assert comp["by_purpose"]["HBW_AM"] == 2


def test_returns_none_for_pre_v5_bundle(tmp_path: Path):
    """Pre-V5 demand.csv has no `purpose` column → no breakdown possible."""
    demand = tmp_path / "demand.csv"
    _write(demand, [
        "trip_id,origin_node_id,destination_node_id,departure_time_s,mode",
        "t0,n1,n2,28000,car",
        "t1,n1,n2,28000,car",
    ])
    assert read_demand_composition(demand) is None


def test_returns_none_for_missing_file(tmp_path: Path):
    """An absent demand.csv (e.g. orphaned scenario dir) returns None."""
    assert read_demand_composition(tmp_path / "does_not_exist.csv") is None


def test_returns_none_for_empty_purpose_column(tmp_path: Path):
    """Header has `purpose` but every row's value is empty → None."""
    demand = tmp_path / "demand.csv"
    _write(demand, [
        "trip_id,origin_node_id,destination_node_id,departure_time_s,mode,purpose",
        "t0,n1,n2,28000,car,",
        "t1,n1,n2,28000,car,",
    ])
    assert read_demand_composition(demand) is None


def test_chain_leg_purposes_subset_of_peak_sets():
    """The CHAIN_LEG_PURPOSES set must be a strict subset of
    AM_PURPOSES ∪ PM_PURPOSES. If a future Phase adds a chain leg to a
    new peak set, this test catches the missing membership."""
    from pipeline.demand.generate_census_demand import (
        AM_PURPOSES,
        PM_PURPOSES,
    )
    assert CHAIN_LEG_PURPOSES.issubset(AM_PURPOSES | PM_PURPOSES)


def test_format_composition_includes_school_count(tmp_path: Path):
    """The terminal-output formatter must surface the school-related
    count and percentage, that's the headline number for the audit."""
    demand = tmp_path / "demand.csv"
    _write(demand, [
        "trip_id,origin_node_id,destination_node_id,departure_time_s,mode,purpose",
        "t0,n1,n2,28000,car,HBW_AM",
        "t1,n1,n3,28000,car,HBSchool_AM",
        "t2,n3,n2,28000,car,HBW_AM_chained",
    ])
    comp = read_demand_composition(demand)
    report = format_composition_report(comp)
    assert "school-related" in report
    assert "AM peak" in report
    # 2 chain legs out of 3 trips → 66.7%
    assert "66.7%" in report


def test_find_canonical_demand_resolves_to_scenarios_dir(tmp_path: Path):
    """The path resolver must find `<repo_root>/scenarios/<name>/demand.csv`."""
    fake_repo = tmp_path / "fake_repo"
    (fake_repo / "scenarios" / "chicago_1k_car").mkdir(parents=True)
    p = find_canonical_demand("chicago_1k_car", repo_root=fake_repo)
    assert p == fake_repo / "scenarios" / "chicago_1k_car" / "demand.csv"
