"""Read a canonical demand.csv and report trip-purpose composition.

V5+ demand generators emit a `purpose` column on every trip
(`pipeline/demand/generate_census_demand.py`, CHANGELOG Phase 9). This
module tallies that column so `audit_fairness` and `analyze_benchmark`
can answer "what fraction of AM peak is school-related?" without
re-deriving chain/peak labels from coordinates.

When a demand.csv lacks the column (pre-V5 bundles),
`read_demand_composition` returns ``None`` — callers should treat that
as "no V5+ tags available" and skip the breakdown.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from pipeline.demand.generate_census_demand import AM_PURPOSES, PM_PURPOSES

# Chain legs are the four "kid-detour" labels — they're a strict subset
# of AM_PURPOSES ∪ PM_PURPOSES. School-related trip count = sum of these.
CHAIN_LEG_PURPOSES: frozenset[str] = frozenset(
    {"HBSchool_AM", "HBSchool_PM", "HBW_AM_chained", "HBW_PM_chained"}
)


def read_demand_composition(demand_csv: Path) -> dict | None:
    """Tally trip purposes in ``demand_csv``.

    Returns a structured breakdown dict, or ``None`` when the file is
    missing, empty, or lacks the V5+ ``purpose`` column.
    """
    if not demand_csv.is_file():
        return None
    with demand_csv.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "purpose" not in reader.fieldnames:
            return None
        counts: Counter[str] = Counter(row.get("purpose", "") for row in reader)
    counts.pop("", None)  # untagged defensive guard
    if not counts:
        return None
    am = sum(counts[p] for p in AM_PURPOSES)
    pm = sum(counts[p] for p in PM_PURPOSES)
    chain_legs = sum(counts[p] for p in CHAIN_LEG_PURPOSES)
    return {
        "total": sum(counts.values()),
        "by_purpose": dict(counts),
        "am_peak": am,
        "pm_peak": pm,
        "chain_legs": chain_legs,
        "school_chains_am": counts.get("HBSchool_AM", 0),
        "school_chains_pm": counts.get("HBSchool_PM", 0),
    }


def format_composition_report(comp: dict, indent: str = "  ") -> str:
    """Multi-line breakdown for terminal output (used by audit_fairness)."""
    lines = []
    total = comp["total"]
    am = comp["am_peak"]
    pm = comp["pm_peak"]
    chain_legs = comp["chain_legs"]
    pct = lambda n: 100.0 * n / max(total, 1)
    lines.append(f"{indent}total trips:    {total}")
    lines.append(f"{indent}AM peak:        {am:>6} ({pct(am):5.1f}%)")
    lines.append(f"{indent}PM peak:        {pm:>6} ({pct(pm):5.1f}%)")
    lines.append(
        f"{indent}school-related: {chain_legs:>6} ({pct(chain_legs):5.1f}%) — "
        f"{comp['school_chains_am']} AM chains + "
        f"{comp['school_chains_pm']} PM chains"
    )
    lines.append(f"{indent}by purpose:")
    by = comp["by_purpose"]
    for p in sorted(by, key=lambda k: -by[k]):
        lines.append(f"{indent}  {p:20s} {by[p]:>6}")
    return "\n".join(lines)


def find_canonical_demand(scenario: str, repo_root: Path | None = None) -> Path:
    """Resolve the canonical bundle's demand.csv for ``scenario``.

    The bundle directory always lives at ``<repo_root>/scenarios/<scenario>/``.
    ``repo_root`` defaults to the parent of this package's parent
    (i.e., the SimForge repo root when this file is at
    ``<repo>/evaluation/demand_composition.py``).
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "scenarios" / scenario / "demand.csv"
