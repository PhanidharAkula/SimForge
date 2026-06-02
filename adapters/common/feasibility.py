"""The one trip filter every adapter is required to use.

A fair comparison only means something if all three engines run the same
trips. The trouble is they don't agree on what "runnable" means on their
own. SUMO quietly skips any trip with no path; MATSim refuses to start at
all on an unroutable plan, so its adapter pulls the largest strongly
connected component and throws out trips with an endpoint outside it. Two
different filters, two different trip sets: on chicago_1k_car that was
SUMO at ~988/1000 and MATSim at ~981/1000.

So we decide feasibility once, here, and every adapter runs exactly that
set. A trip survives only if both endpoints sit inside the SCC of the
canonical network.

Why the SCC instead of plain origin-to-dest reachability? Three reasons.
It's symmetric, so if a->b is feasible then b->a is too, which kills the
last bit of asymmetry between directed engines. MATSim treats a missing
return leg as a hard error, so a one-way reachability check would still be
too loose for it. And on real urban OSM networks the SCC keeps 99%+ of the
nodes anyway, so the cost is small and, crucially, identical for everyone.

Modes
-----
The engines only do cars today, but a bundle asked for with
``--modes car,transit`` will still carry transit and bike rows in
demand.csv. Each adapter says which modes it handles, and the filter can
drop trips whose ``mode`` falls outside that set. ``audit_fairness`` Q3
then checks each engine's simulated count against this same target.

Usage
-----
    from adapters.common import feasible_trip_ids

    feasible, report = feasible_trip_ids(
        network_path, demand_path,
        supported_modes={"car"},     # what this engine handles
    )
    for row in demand_rows:
        if row["trip_id"] in feasible:
            ...  # render for this engine

Use this and only this to decide routability. Roll your own and the
cross-engine counts drift apart again.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Set, Tuple
from xml.etree import ElementTree as ET

from pipeline.network.scc import (
    compute_largest_scc,
    parse_network as _parse_network,
)

logger = logging.getLogger(__name__)


@dataclass
class FeasibilityReport:
    """Summary of the shared feasibility filter for a scenario."""

    scenario_network: str
    scenario_demand: str
    total_nodes: int
    total_links: int
    scc_nodes: int
    scc_links: int
    total_trips: int
    feasible_trips: int
    skipped_missing_fields: int = 0
    skipped_unknown_nodes: int = 0
    skipped_outside_scc: int = 0
    skipped_unsupported_mode: int = 0
    skipped_trip_ids: List[str] = field(default_factory=list)
    # Modes this engine accepts. Empty means "all modes", which is the old
    # mode-agnostic behaviour we keep around for outside callers.
    supported_modes: List[str] = field(default_factory=list)

    @property
    def feasible_fraction(self) -> float:
        return (self.feasible_trips / self.total_trips) if self.total_trips else 1.0

    def summary_line(self) -> str:
        pct = self.feasible_fraction * 100.0
        mode_clause = (
            f" mode∈{{{','.join(sorted(self.supported_modes))}}};"
            if self.supported_modes else ""
        )
        return (
            f"feasibility:{mode_clause} {self.feasible_trips}/{self.total_trips} trips "
            f"({pct:.1f}%) — SCC covers {self.scc_nodes}/{self.total_nodes} nodes, "
            f"{self.scc_links}/{self.total_links} links"
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["feasible_fraction"] = self.feasible_fraction
        return d


def feasible_trip_ids(
    network_path: Path,
    demand_path: Path,
    supported_modes: Set[str] | None = None,
) -> Tuple[Set[str], FeasibilityReport]:
    """The shared set of feasible trip IDs for one scenario.

    A trip makes the cut when both its endpoints are in the SCC of the
    canonical network and, if ``supported_modes`` is given, its ``mode`` is
    in that set. Every adapter runs exactly this set, which is what lets the
    cross-engine results line up trip for trip.

    Pass ``supported_modes`` as the modes this engine handles; trips outside
    it get dropped. ``None`` turns the mode filter off, which is only there
    for old mode-agnostic callers, new code should always pass a set.

    Returns (feasible_trip_ids, report); the report carries the counts and
    the skipped IDs so a run can be audited after the fact.
    """
    network_path = Path(network_path)
    demand_path = Path(demand_path)

    nodes, edges = _parse_network(network_path)
    scc = compute_largest_scc(nodes, edges)
    scc_link_count = sum(1 for u, v in edges if u in scc and v in scc)

    feasible: Set[str] = set()
    report = FeasibilityReport(
        scenario_network=str(network_path),
        scenario_demand=str(demand_path),
        total_nodes=len(nodes),
        total_links=len(edges),
        scc_nodes=len(scc),
        scc_links=scc_link_count,
        total_trips=0,
        feasible_trips=0,
        supported_modes=sorted(supported_modes) if supported_modes else [],
    )

    with demand_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"demand.csv at {demand_path} has no header row")
        required = {"trip_id", "origin_node_id", "destination_node_id"}
        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError(
                f"demand.csv at {demand_path} missing columns: {', '.join(sorted(missing))}"
            )
        # Older single-mode bundles predate the multi-mode pipeline and have
        # no mode column, so it's optional. Filter on it only when it's both
        # present and the caller asked for one.
        has_mode_column = "mode" in (reader.fieldnames or [])

        for row in reader:
            report.total_trips += 1
            trip_id = (row.get("trip_id") or "").strip()
            origin = (row.get("origin_node_id") or "").strip()
            dest = (row.get("destination_node_id") or "").strip()

            if not trip_id or not origin or not dest:
                report.skipped_missing_fields += 1
                if trip_id:
                    report.skipped_trip_ids.append(trip_id)
                continue
            if origin not in nodes or dest not in nodes:
                report.skipped_unknown_nodes += 1
                report.skipped_trip_ids.append(trip_id)
                continue
            if origin not in scc or dest not in scc:
                report.skipped_outside_scc += 1
                report.skipped_trip_ids.append(trip_id)
                continue
            if supported_modes is not None and has_mode_column:
                trip_mode = (row.get("mode") or "").strip()
                if trip_mode and trip_mode not in supported_modes:
                    report.skipped_unsupported_mode += 1
                    report.skipped_trip_ids.append(trip_id)
                    continue
            feasible.add(trip_id)

    report.feasible_trips = len(feasible)
    return feasible, report


def write_feasibility_report(
    report: FeasibilityReport,
    output_path: Path,
) -> Path:
    """Persist a FeasibilityReport as JSON next to engine inputs."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return output_path


def log_report(report: FeasibilityReport, engine: str) -> None:
    """Log the feasibility summary, bumping to WARNING when trips got dropped."""
    if report.feasible_trips == report.total_trips:
        logger.info("[%s] %s", engine, report.summary_line())
        return
    logger.warning(
        "[%s] %s — dropped: %d missing fields, %d unknown nodes, "
        "%d outside SCC, %d unsupported mode",
        engine,
        report.summary_line(),
        report.skipped_missing_fields,
        report.skipped_unknown_nodes,
        report.skipped_outside_scc,
        report.skipped_unsupported_mode,
    )


def resolve_network_and_demand(scenario_root: Path) -> Tuple[Path, Path]:
    """Pull the canonical network and demand paths out of a scenario's
    manifest.xml, so each adapter doesn't reparse the manifest itself just to
    run the filter."""
    manifest = scenario_root / "manifest.xml"
    if not manifest.is_file():
        raise FileNotFoundError(f"manifest.xml not found at {manifest}")
    root = ET.parse(manifest).getroot()
    canonical = root.find("canonical_files")
    if canonical is None:
        raise ValueError("manifest.xml missing <canonical_files>")
    paths: Dict[str, Path] = {}
    for file_elem in canonical.findall("file"):
        ftype = file_elem.get("type")
        rel = file_elem.get("path")
        if ftype and rel:
            paths[ftype] = (manifest.parent / rel).resolve()
    try:
        return paths["network"], paths["demand"]
    except KeyError as exc:
        raise ValueError(
            f"manifest.xml at {manifest} missing canonical '{exc.args[0]}' file"
        ) from exc
