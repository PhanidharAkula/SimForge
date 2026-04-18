"""
Shared trip feasibility filter used by every engine adapter.

SimForge's primary goal is a fair, apples-to-apples comparison. That only holds
if every simulator is asked to run the *same* trip set. Different engines have
different tolerance for unroutable demand:

  - SUMO silently skips trips with no BFS-reachable path.
  - MATSim crashes on unroutable plans, so its adapter extracts the largest
    strongly-connected component and drops trips with endpoints outside it.

Those two filters differ, so SUMO and MATSim were historically simulating
*different* trip subsets — SUMO ~988/1000, MATSim ~981/1000 on chicago_1k_car.
This module centralises the filter: every adapter computes the *same* set of
feasible trip IDs and simulates exactly that subset. The filter is the
intersection of both constraints: both endpoints must lie inside the largest
strongly connected component of the canonical network.

Why SCC (and not just BFS-reachable origin→dest)?

  - SCC is symmetric: if a trip a→b is feasible, b→a is too. That removes the
    last source of asymmetry between directed engines.
  - MATSim's queue-based mobsim treats a missing return leg as a hard error,
    so a strict origin→dest reachability check would still be too permissive
    for MATSim.
  - Empirically the SCC on realistic urban OSM networks keeps ≥99% of nodes,
    so the loss is small and equal across engines.

Usage
-----
    from adapters.common import feasible_trip_ids

    feasible, report = feasible_trip_ids(network_path, demand_path)
    for row in demand_rows:
        if row["trip_id"] in feasible:
            ...  # render for this engine

Every adapter MUST use this filter and nothing else for routability decisions,
otherwise cross-engine counts will drift again.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from xml.etree import ElementTree as ET

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
    skipped_trip_ids: List[str] = field(default_factory=list)

    @property
    def feasible_fraction(self) -> float:
        return (self.feasible_trips / self.total_trips) if self.total_trips else 1.0

    def summary_line(self) -> str:
        pct = self.feasible_fraction * 100.0
        return (
            f"feasibility: {self.feasible_trips}/{self.total_trips} trips "
            f"({pct:.1f}%) — SCC covers {self.scc_nodes}/{self.total_nodes} nodes, "
            f"{self.scc_links}/{self.total_links} links"
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["feasible_fraction"] = self.feasible_fraction
        return d


def _parse_network(network_path: Path) -> Tuple[Set[str], List[Tuple[str, str]]]:
    """Parse canonical network.xml into (node_ids, directed_edges)."""
    try:
        tree = ET.parse(network_path)
    except ET.ParseError as exc:
        raise ValueError(
            f"Failed to parse network.xml at {network_path}: {exc}"
        ) from exc
    root = tree.getroot()
    if root.tag != "network":
        raise ValueError(
            f"network.xml root must be <network>, found <{root.tag}>"
        )

    nodes: Set[str] = set()
    nodes_elem = root.find("nodes")
    if nodes_elem is not None:
        for node_elem in nodes_elem.findall("node"):
            node_id = node_elem.get("id")
            if node_id:
                nodes.add(node_id)

    edges: List[Tuple[str, str]] = []
    links_elem = root.find("links")
    if links_elem is not None:
        for link_elem in links_elem.findall("link"):
            f = link_elem.get("from")
            t = link_elem.get("to")
            if f and t and f != t:
                edges.append((f, t))

    return nodes, edges


def compute_largest_scc(
    nodes: Set[str],
    edges: List[Tuple[str, str]],
) -> Set[str]:
    """
    Return the node IDs of the largest strongly-connected component.

    Implemented iteratively (Kosaraju) to avoid Python recursion limits on
    metropolitan-scale networks.
    """
    fwd: Dict[str, List[str]] = {}
    rev: Dict[str, List[str]] = {}
    for u, v in edges:
        fwd.setdefault(u, []).append(v)
        rev.setdefault(v, []).append(u)

    visited: Set[str] = set()
    finish_order: List[str] = []

    for start in nodes:
        if start in visited:
            continue
        stack: List[Tuple[str, bool]] = [(start, False)]
        while stack:
            node, processed = stack.pop()
            if processed:
                finish_order.append(node)
                continue
            if node in visited:
                continue
            visited.add(node)
            stack.append((node, True))
            for nb in fwd.get(node, ()):
                if nb not in visited:
                    stack.append((nb, False))

    visited.clear()
    best: Set[str] = set()
    for start in reversed(finish_order):
        if start in visited:
            continue
        component: Set[str] = set()
        stk: List[str] = [start]
        while stk:
            node = stk.pop()
            if node in visited:
                continue
            visited.add(node)
            component.add(node)
            for nb in rev.get(node, ()):
                if nb not in visited:
                    stk.append(nb)
        if len(component) > len(best):
            best = component
    return best


def feasible_trip_ids(
    network_path: Path,
    demand_path: Path,
) -> Tuple[Set[str], FeasibilityReport]:
    """
    Compute the shared set of feasible trip IDs for a scenario.

    A trip is feasible when *both* its origin and destination nodes lie in the
    largest strongly-connected component of the canonical network. Every engine
    adapter must simulate exactly this set so cross-engine results compare
    trips 1-to-1.

    Returns (feasible_trip_ids, report). The report contains counts and a list
    of skipped trip IDs for auditability.
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
    """Log the feasibility summary at WARNING level when trips are dropped."""
    if report.feasible_trips == report.total_trips:
        logger.info("[%s] %s", engine, report.summary_line())
        return
    logger.warning(
        "[%s] %s — dropped: %d missing fields, %d unknown nodes, %d outside SCC",
        engine,
        report.summary_line(),
        report.skipped_missing_fields,
        report.skipped_unknown_nodes,
        report.skipped_outside_scc,
    )


def resolve_network_and_demand(scenario_root: Path) -> Tuple[Path, Path]:
    """
    Resolve canonical network/demand paths from a scenario's manifest.xml.

    Kept here so adapters can call a single helper instead of each re-parsing
    the manifest just to run the feasibility filter.
    """
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
