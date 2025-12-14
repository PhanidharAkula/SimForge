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
from collections import deque
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple, Set, Optional


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
    config_tree = ET.parse(config_path)
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

    start_time_s = int(start_time_s_raw)
    end_time_s = int(end_time_s_raw)

    # --- Network: node + link counts ---
    network_path = paths["network"]
    network_tree = ET.parse(network_path)
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
    with demand_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for _row in reader:
            trip_count += 1

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
class CanonicalLink:
    id: str
    from_node: str
    to_node: str
    length: float
    speed: float


@dataclass
class NetworkGraph:
    nodes: Set[str]
    links: List[CanonicalLink]
    adjacency: Dict[str, List[str]]
    edge_lookup: Dict[Tuple[str, str], CanonicalLink]


def parse_canonical_network(network_path: Path) -> NetworkGraph:
    """
    Parse canonical network.xml into a simple directed graph representation.
    """
    tree = ET.parse(network_path)
    root = tree.getroot()
    if root.tag != "network":
        raise ValueError(f"network.xml root must be <network>, found <{root.tag}>")

    nodes_elem = root.find("nodes")
    links_elem = root.find("links")

    node_ids: Set[str] = set()
    if nodes_elem is not None:
        for node_elem in nodes_elem.findall("node"):
            node_id = node_elem.get("id")
            if node_id:
                node_ids.add(node_id)

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

            try:
                length = float(length_raw)
            except ValueError:
                length = 0.0
            try:
                speed = float(speed_raw)
            except ValueError:
                speed = 13.9

            link = CanonicalLink(
                id=link_id,
                from_node=from_id,
                to_node=to_id,
                length=length,
                speed=speed,
            )
            links.append(link)

            adjacency.setdefault(from_id, []).append(to_id)
            edge_lookup[(from_id, to_id)] = link

    return NetworkGraph(
        nodes=node_ids,
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

def build_sumo_net_xml(summary: ScenarioSummary, graph: NetworkGraph) -> str:
    """
    Build a minimal SUMO network net.xml as a string based on the canonical network.

    For v0, we:
      - Map each canonical node -> SUMO node with same id.
      - Map each canonical link -> SUMO edge with one lane.
    """
    lines: List[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(f"<!-- SUMO net generated from canonical network.xml -->")
    lines.append(f"<!-- Scenario: {summary.scenario_id} -->")
    lines.append('<net>')

    # Nodes
    lines.append('  <nodes>')
    for node_id in sorted(graph.nodes):
        # We do not propagate coordinates here; for real runs, geometry should be included.
        lines.append(f'    <node id="{node_id}" />')
    lines.append('  </nodes>')

    # Edges + lanes
    lines.append('  <edges>')
    for link in graph.links:
        edge_id = link.id
        from_id = link.from_node
        to_id = link.to_node
        priority = 1  # simple default
        lane_id = f"{edge_id}_0"
        lane_index = 0
        lane_speed = link.speed if link.speed > 0 else 13.9
        lane_length = link.length if link.length > 0 else 1.0

        lines.append(
            f'    <edge id="{edge_id}" from="{from_id}" to="{to_id}" priority="{priority}">'
        )
        lines.append(
            f'      <lane id="{lane_id}" index="{lane_index}" speed="{lane_speed}" length="{lane_length}"/>'
        )
        lines.append('    </edge>')
    lines.append('  </edges>')

    lines.append('</net>')
    return "\n".join(lines)


def build_sumo_routes_xml(
    summary: ScenarioSummary,
    graph: NetworkGraph,
    demand_path: Path,
) -> str:
    """
    Build a SUMO routes file based on canonical demand.csv and the network graph.

    For each trip:
      - Run BFS on the node graph to find a path from origin_node_id to destination_node_id.
      - Map node-to-node steps to canonical links, then to edge ids.
      - Create one <vehicle> with a nested <route edges="..."/>.
    """
    lines: List[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append("<!-- SUMO routes generated from canonical demand.csv -->")
    lines.append(f"<!-- Scenario: {summary.scenario_id}, trips: {summary.trip_count} -->")
    lines.append("<routes>")

    skipped_trips: List[str] = []

    with demand_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_idx, row in enumerate(reader, start=2):
            trip_id = (row.get("trip_id") or "").strip()
            origin = (row.get("origin_node_id") or "").strip()
            dest = (row.get("destination_node_id") or "").strip()
            depart = (row.get("departure_time_s") or "").strip()

            if not trip_id or not origin or not dest or not depart:
                skipped_trips.append(f"row {row_idx} (missing fields)")
                continue

            path_nodes = shortest_path_nodes(graph.adjacency, origin, dest)
            if not path_nodes or len(path_nodes) < 2:
                skipped_trips.append(trip_id)
                continue

            # Convert node path to edge ids
            edge_ids: List[str] = []
            ok = True
            for u, v in zip(path_nodes[:-1], path_nodes[1:]):
                link = graph.edge_lookup.get((u, v))
                if not link:
                    ok = False
                    break
                edge_ids.append(link.id)
            if not ok or not edge_ids:
                skipped_trips.append(trip_id)
                continue

            edges_str = " ".join(edge_ids)
            veh_id = f"veh_{trip_id}"
            route_id = f"r_{trip_id}"

            lines.append(
                f'  <vehicle id="{veh_id}" depart="{depart}">'
            )
            lines.append(
                f'    <route id="{route_id}" edges="{edges_str}"/>'
            )
            lines.append("  </vehicle>")

    if skipped_trips:
        lines.append("  <!-- Skipped trips (no path or bad data): "
                     + ", ".join(skipped_trips)
                     + " -->")

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
          - net.net.xml   (nodes + edges + lanes)
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

    # Build SUMO net.xml
    net_content = build_sumo_net_xml(summary, graph)
    net_path = output_dir / "net.net.xml"
    net_path.write_text(net_content, encoding="utf-8")

    # Build SUMO routes
    routes_content = build_sumo_routes_xml(summary, graph, demand_path)
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
</configuration>
"""
    cfg_path = output_dir / "toy.sumocfg"
    cfg_path.write_text(cfg_content, encoding="utf-8")

    return summary