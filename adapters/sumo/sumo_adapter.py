"""
SUMO adapter for SimForge.

For v0, this module:

- Loads a canonical scenario bundle (manifest, network, demand, config, optional signals).
- Builds a simple summary of the scenario (node count, link count, trip count, time horizon, etc.).
- Generates basic SUMO input files into an output directory:
    - net.net.xml  : edges + lanes derived from canonical network.xml
    - routes.rou.xml: vehicles + routes derived from canonical demand.csv
    - toy.sumocfg   : SUMO configuration wiring them together

This is still a simplified mapping, but unlike the pure placeholders, the files now
reflect the actual canonical content of the toy scenario.
"""

from __future__ import annotations

import csv
import logging
import subprocess
from collections import deque
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple, Set, Optional

from adapters.common import feasibility as _feasibility

logger = logging.getLogger(__name__)


@dataclass
class ScenarioSummary:
    scenario_id: str
    node_count: int
    link_count: int
    trip_count: int
    has_signals: bool
    start_time_s: int
    end_time_s: int


# ---------------------------------------------------------------------------
# Canonical bundle helpers
# ---------------------------------------------------------------------------

def load_canonical_paths(scenario_root: Path) -> dict[str, Path]:
    """
    Resolve canonical file paths from manifest.xml.

    Expected:
      - manifest.xml exists at scenario_root
      - <canonical_files> section lists at least network, demand, config
      - signals is optional
    """
    manifest_path = scenario_root / "manifest.xml"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest.xml not found at {manifest_path}")

    tree = ET.parse(manifest_path)
    root = tree.getroot()
    if root.tag != "manifest":
        raise ValueError(f"manifest.xml root tag must be <manifest>, found <{root.tag}>")

    canonical_files_elem = root.find("canonical_files")
    if canonical_files_elem is None:
        raise ValueError("manifest.xml missing <canonical_files> element")

    resolved: dict[str, Path] = {}
    for file_elem in canonical_files_elem.findall("file"):
        file_type = file_elem.get("type")
        rel_path = file_elem.get("path")
        if not file_type or not rel_path:
            continue
        resolved[file_type] = (manifest_path.parent / rel_path).resolve()

    # Basic expectations for v0
    for required_type in ("network", "demand", "config"):
        if required_type not in resolved:
            raise ValueError(f"manifest.xml does not define canonical '{required_type}' file")

    # signals is optional
    return resolved


def summarize_scenario(scenario_root: Path) -> ScenarioSummary:
    """
    Load the canonical bundle and return a high-level summary.

    Uses canonical config, network, demand, and optional signals.
    """
    paths = load_canonical_paths(scenario_root)

    # --- Config: scenario_id + time horizon ---
    config_path = paths["config"]
    try:
        config_tree = ET.parse(config_path)
    except ET.ParseError as e:
        raise ValueError(
            f"Failed to parse config.xml at {config_path}: {e}\n"
            f"  Possible causes: file is truncated, has encoding issues, or is not valid XML.\n"
            f"  Fix: Re-generate the scenario or check the file with 'xmllint {config_path}'."
        ) from e
    config_root = config_tree.getroot()
    if config_root.tag != "config":
        raise ValueError(f"config.xml root must be <config>, found <{config_root.tag}>")

    metadata_elem = config_root.find("metadata")
    time_elem = config_root.find("time")

    if metadata_elem is None:
        raise ValueError("config.xml missing <metadata> element")
    if time_elem is None:
        raise ValueError("config.xml missing <time> element")

    scenario_id = metadata_elem.get("scenario_id") or ""
    if not scenario_id:
        raise ValueError("config.xml <metadata> must have non-empty 'scenario_id'")

    start_time_s_raw = time_elem.get("start_time_s")
    end_time_s_raw = time_elem.get("end_time_s")
    if start_time_s_raw is None or end_time_s_raw is None:
        raise ValueError("config.xml <time> must define 'start_time_s' and 'end_time_s'")

    try:
        start_time_s = int(float(start_time_s_raw))
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"config.xml <time> start_time_s='{start_time_s_raw}' is not a valid number.\n"
            f"  Expected an integer (seconds), e.g. start_time_s=\"0\"."
        ) from exc
    try:
        end_time_s = int(float(end_time_s_raw))
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"config.xml <time> end_time_s='{end_time_s_raw}' is not a valid number.\n"
            f"  Expected an integer (seconds), e.g. end_time_s=\"86400\"."
        ) from exc
    if end_time_s <= start_time_s:
        raise ValueError(
            f"config.xml <time> end_time_s ({end_time_s}) must be greater than "
            f"start_time_s ({start_time_s})."
        )

    # --- Network: node + link counts ---
    network_path = paths["network"]
    try:
        network_tree = ET.parse(network_path)
    except ET.ParseError as e:
        raise ValueError(
            f"Failed to parse network.xml at {network_path}: {e}\n"
            f"  Fix: Re-generate the network or check with 'xmllint {network_path}'."
        ) from e
    network_root = network_tree.getroot()
    if network_root.tag != "network":
        raise ValueError(f"network.xml root must be <network>, found <{network_root.tag}>")

    nodes_elem = network_root.find("nodes")
    links_elem = network_root.find("links")

    node_count = len(nodes_elem.findall("node")) if nodes_elem is not None else 0
    link_count = len(links_elem.findall("link")) if links_elem is not None else 0

    # --- Demand: trip count ---
    demand_path = paths["demand"]
    trip_count = 0
    try:
        with demand_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise ValueError(
                    f"demand.csv at {demand_path} is empty or has no header row.\n"
                    f"  Expected columns: trip_id, origin_node_id, destination_node_id, departure_time_s, mode"
                )
            required = {"trip_id", "origin_node_id", "destination_node_id", "departure_time_s"}
            missing = required - set(reader.fieldnames)
            if missing:
                raise ValueError(
                    f"demand.csv at {demand_path} is missing required columns: {', '.join(sorted(missing))}\n"
                    f"  Found columns: {', '.join(reader.fieldnames)}\n"
                    f"  Expected: trip_id, origin_node_id, destination_node_id, departure_time_s, mode"
                )
            for _row in reader:
                trip_count += 1
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"demand.csv not found at {demand_path}.\n"
            f"  Check that manifest.xml points to the correct demand file."
        ) from exc

    # --- Signals: presence flag ---
    has_signals = False
    signals_path = paths.get("signals")
    if signals_path is not None and signals_path.is_file():
        signals_tree = ET.parse(signals_path)
        signals_root = signals_tree.getroot()
        if signals_root.tag == "signals":
            junctions = signals_root.findall("junction")
            has_signals = len(junctions) > 0

    return ScenarioSummary(
        scenario_id=scenario_id,
        node_count=node_count,
        link_count=link_count,
        trip_count=trip_count,
        has_signals=has_signals,
        start_time_s=start_time_s,
        end_time_s=end_time_s,
    )


# ---------------------------------------------------------------------------
# Network parsing and routing helpers
# ---------------------------------------------------------------------------

@dataclass
class CanonicalNode:
    id: str
    x: float
    y: float


@dataclass
class CanonicalLink:
    id: str
    from_node: str
    to_node: str
    length: float
    speed: float
    lanes: int = 1


@dataclass
class NetworkGraph:
    nodes: Dict[str, CanonicalNode]
    links: List[CanonicalLink]
    adjacency: Dict[str, List[str]]
    edge_lookup: Dict[Tuple[str, str], CanonicalLink]


def parse_canonical_network(network_path: Path) -> NetworkGraph:
    """
    Parse canonical network.xml into a simple directed graph representation.
    """
    try:
        tree = ET.parse(network_path)
    except ET.ParseError as e:
        raise ValueError(
            f"Failed to parse network.xml at {network_path}: {e}\n"
            f"  Fix: Re-generate the network or check with 'xmllint {network_path}'."
        ) from e
    root = tree.getroot()
    if root.tag != "network":
        raise ValueError(f"network.xml root must be <network>, found <{root.tag}>")

    nodes_elem = root.find("nodes")
    links_elem = root.find("links")

    nodes: Dict[str, CanonicalNode] = {}
    if nodes_elem is not None:
        for node_elem in nodes_elem.findall("node"):
            node_id = node_elem.get("id")
            if not node_id:
                continue
            x_raw = node_elem.get("x") or "0"
            y_raw = node_elem.get("y") or "0"
            try:
                x = float(x_raw)
                y = float(y_raw)
            except ValueError:
                x, y = 0.0, 0.0
            nodes[node_id] = CanonicalNode(id=node_id, x=x, y=y)

    links: List[CanonicalLink] = []
    adjacency: Dict[str, List[str]] = {}
    edge_lookup: Dict[Tuple[str, str], CanonicalLink] = {}

    if links_elem is not None:
        for link_elem in links_elem.findall("link"):
            link_id = link_elem.get("id")
            from_id = link_elem.get("from")
            to_id = link_elem.get("to")
            if not link_id or not from_id or not to_id:
                continue

            length_raw = link_elem.get("length") or "0"
            speed_raw = link_elem.get("speed_limit") or "13.9"
            lanes_raw = link_elem.get("lanes") or "1"

            try:
                length = float(length_raw)
            except ValueError:
                length = 0.0
            try:
                speed = float(speed_raw)
            except ValueError:
                speed = 13.9
            try:
                lanes = int(lanes_raw)
                lanes = max(1, lanes)  # Ensure at least 1 lane
            except ValueError:
                lanes = 1

            # Ensure minimum values for SUMO compatibility
            length = max(0.1, length)  # Minimum 0.1m length
            speed = max(0.1, speed)    # Minimum 0.1 m/s speed

            link = CanonicalLink(
                id=link_id,
                from_node=from_id,
                to_node=to_id,
                length=length,
                speed=speed,
                lanes=lanes,
            )
            links.append(link)

            adjacency.setdefault(from_id, []).append(to_id)
            edge_lookup[(from_id, to_id)] = link

    return NetworkGraph(
        nodes=nodes,
        links=links,
        adjacency=adjacency,
        edge_lookup=edge_lookup,
    )


def shortest_path_nodes(
    adjacency: Dict[str, List[str]],
    origin: str,
    dest: str,
) -> Optional[List[str]]:
    """
    Simple BFS shortest path on the node graph.

    Returns list of node ids from origin to dest (inclusive), or None if unreachable.
    """
    if origin == dest:
        return [origin]

    if origin not in adjacency:
        # Origin may still have incoming edges only; treat as no outgoing path
        # For tiny toy networks we assume adjacency is enough.
        pass

    visited: Set[str] = set()
    parent: Dict[str, str] = {}

    queue: deque[str] = deque()
    queue.append(origin)
    visited.add(origin)

    while queue:
        u = queue.popleft()
        for v in adjacency.get(u, []):
            if v in visited:
                continue
            visited.add(v)
            parent[v] = u
            if v == dest:
                # reconstruct path
                path: List[str] = [v]
                cur = v
                while cur != origin:
                    cur = parent[cur]
                    path.append(cur)
                path.reverse()
                return path
            queue.append(v)

    return None


# ---------------------------------------------------------------------------
# SUMO XML generation helpers
# ---------------------------------------------------------------------------

def build_sumo_nodes_xml(graph: NetworkGraph) -> str:
    """
    Build a SUMO nodes XML file (input for netconvert).
    """
    lines: List[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<nodes>')
    for node_id in sorted(graph.nodes.keys()):
        node = graph.nodes[node_id]
        lines.append(f'    <node id="{node.id}" x="{node.x}" y="{node.y}" type="priority"/>')
    lines.append('</nodes>')
    return "\n".join(lines)


def build_sumo_edges_xml(graph: NetworkGraph) -> str:
    """
    Build a SUMO edges XML file (input for netconvert).

    Self-looped links (from_node == to_node) are filtered out: SUMO
    1.26's netconvert exits non-zero with no output file when it sees
    them, even though it only emits Warning lines. The canonical SCC
    computation already drops self-loops, so this filter just keeps the
    SUMO build path consistent with the routable subgraph.
    """
    lines: List[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<edges>')
    for link in graph.links:
        if link.from_node == link.to_node:
            continue
        lines.append(
            f'    <edge id="{link.id}" from="{link.from_node}" to="{link.to_node}" '
            f'numLanes="{link.lanes}" speed="{link.speed}" length="{link.length:.2f}"/>'
        )
    lines.append('</edges>')
    return "\n".join(lines)


def build_sumo_routes_xml(
    summary: ScenarioSummary,
    graph: NetworkGraph,
    demand_path: Path,
    feasible: Set[str],
) -> str:
    """
    Build a SUMO routes file based on canonical demand.csv and the network graph.

    Only trips in ``feasible`` (the shared cross-engine feasibility set) are
    routed. For each feasible trip we BFS on the node graph for a path.
    """
    lines: List[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append("<!-- SUMO routes generated from canonical demand.csv -->")
    lines.append(f"<!-- Scenario: {summary.scenario_id}, trips: {summary.trip_count} -->")
    lines.append("<routes>")

    route_failures: List[str] = []

    from pipeline.progress import ProgressBar
    pb = ProgressBar(total=len(feasible), desc="Routing trips (BFS)")

    with demand_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trip_id = (row.get("trip_id") or "").strip()
            if trip_id not in feasible:
                continue
            pb.update()
            origin = (row.get("origin_node_id") or "").strip()
            dest = (row.get("destination_node_id") or "").strip()
            depart = (row.get("departure_time_s") or "").strip()

            path_nodes = shortest_path_nodes(graph.adjacency, origin, dest)
            if not path_nodes or len(path_nodes) < 2:
                route_failures.append(trip_id)
                continue

            edge_ids: List[str] = []
            ok = True
            for u, v in zip(path_nodes[:-1], path_nodes[1:]):
                link = graph.edge_lookup.get((u, v))
                if not link:
                    ok = False
                    break
                edge_ids.append(link.id)
            if not ok or not edge_ids:
                route_failures.append(trip_id)
                continue

            edges_str = " ".join(edge_ids)
            veh_id = f"veh_{trip_id}"
            route_id = f"r_{trip_id}"

            lines.append(f'  <vehicle id="{veh_id}" depart="{depart}">')
            lines.append(f'    <route id="{route_id}" edges="{edges_str}"/>')
            lines.append("  </vehicle>")

    pb.finish()

    # Any failure here means the shared SCC filter disagrees with SUMO's BFS —
    # that should never happen, so loudly surface it instead of silently dropping.
    if route_failures:
        logger.error(
            "SUMO could not route %d feasible trips — this contradicts the "
            "shared SCC filter (%s). First IDs: %s",
            len(route_failures),
            _feasibility.__name__,
            ", ".join(route_failures[:5]),
        )
        lines.append(
            "  <!-- SCC-feasible trips that SUMO failed to route: "
            + ", ".join(route_failures) + " -->"
        )

    lines.append("</routes>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def prepare_sumo_inputs(scenario_root: Path, output_dir: Path) -> ScenarioSummary:
    """
    Prepare SUMO input files for the given canonical scenario.

    v0 behavior:
      - Ensure output_dir exists.
      - Compute a ScenarioSummary.
      - Parse canonical network into a simple graph.
      - Generate:
          - nodes.nod.xml (SUMO nodes input for netconvert)
          - edges.edg.xml (SUMO edges input for netconvert)
          - net.net.xml   (generated by netconvert)
          - routes.rou.xml (vehicles + routes for each trip with a valid path)
          - toy.sumocfg   (linking net + routes with correct time horizon)
    """
    scenario_root = scenario_root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Summary
    summary = summarize_scenario(scenario_root)

    # Canonical paths
    paths = load_canonical_paths(scenario_root)
    network_path = paths["network"]
    demand_path = paths["demand"]

    # Network graph for routing + edge mapping
    graph = parse_canonical_network(network_path)

    # Cross-engine fairness: prune to the largest SCC before emitting,
    # matching what MATSim's clean_network and DTALite's prepare path
    # do. Without this filter, SUMO would emit the full canonical
    # network (with non-SCC dead-end stubs) while MATSim and DTALite
    # emit only the SCC subset — a documented fairness gap that made
    # SUMO's input network read 314 nodes / 346 links larger than the
    # other two on chicago_1k_car. The trips themselves are already
    # restricted to SCC origins/destinations by the shared feasibility
    # filter, so the dropped non-SCC nodes are unused either way; this
    # change just makes the input artefacts byte-comparable across
    # engines for the audit_fairness Q2 check.
    from pipeline.network.scc import compute_largest_scc
    scc_node_ids = compute_largest_scc(
        set(graph.nodes.keys()),
        [(lk.from_node, lk.to_node) for lk in graph.links],
    )
    scc_nodes = {nid: n for nid, n in graph.nodes.items() if nid in scc_node_ids}
    scc_links = [lk for lk in graph.links
                 if lk.from_node in scc_node_ids and lk.to_node in scc_node_ids]
    # Critical: rebuild adjacency + edge_lookup against the filtered link
    # set. These two indices are consumed by shortest_path_nodes (BFS) when
    # SUMO's prepare path routes every trip; leaving them empty made BFS
    # return no edges, which silently dropped every trip into the
    # "SCC-feasible but SUMO failed to route" bucket and produced an empty
    # routes.rou.xml. Diagnosed via audit_fairness Q3=0 on chicago_1k_car
    # smoke2 (Pitzer 2026-04-27).
    scc_adjacency: Dict[str, List[str]] = {}
    scc_edge_lookup: Dict[Tuple[str, str], CanonicalLink] = {}
    for lk in scc_links:
        scc_adjacency.setdefault(lk.from_node, []).append(lk.to_node)
        scc_edge_lookup[(lk.from_node, lk.to_node)] = lk
    graph = NetworkGraph(
        nodes=scc_nodes,
        links=scc_links,
        adjacency=scc_adjacency,
        edge_lookup=scc_edge_lookup,
    )

    # Build SUMO nodes and edges XML (input for netconvert)
    nodes_content = build_sumo_nodes_xml(graph)
    nodes_path = output_dir / "nodes.nod.xml"
    nodes_path.write_text(nodes_content, encoding="utf-8")

    edges_content = build_sumo_edges_xml(graph)
    edges_path = output_dir / "edges.edg.xml"
    edges_path.write_text(edges_content, encoding="utf-8")

    # Run netconvert to generate proper net.net.xml
    net_path = output_dir / "net.net.xml"
    try:
        nc_result = subprocess.run(
            [
                "netconvert",
                "--node-files", str(nodes_path),
                "--edge-files", str(edges_path),
                "--output-file", str(net_path),
                "--proj.plain-geo",
                "--no-turnarounds",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        # netconvert returns non-zero for warnings; only fail on actual errors
        if nc_result.returncode != 0:
            # Detect signal-based crashes (e.g., SIGSEGV on Apple Silicon)
            if nc_result.returncode < 0:
                import platform
                signal_num = -nc_result.returncode
                msg = (
                    f"netconvert crashed with signal {signal_num} (e.g., segmentation fault).\n"
                )
                if platform.machine() == "arm64":
                    msg += (
                        "  This is a known SUMO bug on Apple Silicon for large networks (>~3000 nodes).\n"
                        "  Workarounds:\n"
                        "    1. Use a smaller network (reduce --radius in the generation script)\n"
                        "    2. Run on Linux/HPC where SUMO's x86_64 binary handles large networks\n"
                        "    3. Build SUMO from source with Rosetta 2 (arch -x86_64)"
                    )
                raise RuntimeError(msg)
            error_lines = [l for l in (nc_result.stderr or "").split("\n")
                           if l.strip().startswith("Error:")]
            if error_lines or not net_path.exists():
                raise RuntimeError(f"netconvert failed: {nc_result.stderr}")
    except FileNotFoundError as exc:
        raise RuntimeError(
            "netconvert not found on PATH.\n"
            "  SUMO is bundled in requirements.lock as the eclipse-sumo wheel.\n"
            "  Install with:  uv pip install -r requirements.lock\n"
            "    (or:         pip install eclipse-sumo  for an ad-hoc install)\n"
            "  Then verify:   netconvert --version"
        ) from exc

    # Compute the shared feasibility set — every engine must simulate exactly this subset.
    feasible, feas_report = _feasibility.feasible_trip_ids(network_path, demand_path)
    _feasibility.log_report(feas_report, engine="sumo")
    _feasibility.write_feasibility_report(feas_report, output_dir / "feasibility_report.json")

    # Build SUMO routes
    routes_content = build_sumo_routes_xml(summary, graph, demand_path, feasible)
    routes_path = output_dir / "routes.rou.xml"
    routes_path.write_text(routes_content, encoding="utf-8")

    # Minimal SUMO config referencing the above files
    cfg_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- SUMO config for scenario '{summary.scenario_id}' -->
<configuration>
  <input>
    <net-file value="net.net.xml" />
    <route-files value="routes.rou.xml" />
  </input>
  <time>
    <begin value="{summary.start_time_s}" />
    <end value="{summary.end_time_s}" />
  </time>
  <output>
    <tripinfo-output value="tripinfo.xml" />
  </output>
</configuration>
"""
    cfg_path = output_dir / "toy.sumocfg"
    cfg_path.write_text(cfg_content, encoding="utf-8")

    return summary