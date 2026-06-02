"""
SUMO adapter for SimForge.

What this module does:

- Reads a canonical scenario bundle (manifest, network, demand, config, and
  signals if present).
- Summarizes it: node/link/trip counts, time horizon, that sort of thing.
- Writes the SUMO inputs into an output directory:
    - net.net.xml   : edges and lanes from the canonical network.xml
    - routes.rou.xml: vehicles and routes from the canonical demand.csv
    - toy.sumocfg   : the SUMO config that ties them together

The mapping is deliberately lean, but every file reflects the real canonical
content of the bundle.
"""

from __future__ import annotations

import csv
import logging
import subprocess
import time
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
    """Resolve the canonical file paths from manifest.xml.

    Assumes manifest.xml is at scenario_root and its <canonical_files> section
    lists at least network, demand, and config. Signals is optional.
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

    # These three are mandatory; signals is allowed to be absent.
    for required_type in ("network", "demand", "config"):
        if required_type not in resolved:
            raise ValueError(f"manifest.xml does not define canonical '{required_type}' file")

    return resolved


def summarize_scenario(scenario_root: Path) -> ScenarioSummary:
    """Load the bundle and hand back a high-level summary.

    Pulls from config, network, demand, and signals if there is one.
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
    """Parse network.xml into a plain directed-graph representation."""
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
                lanes = max(1, lanes)  # at least one lane
            except ValueError:
                lanes = 1

            # SUMO rejects zero-length or zero-speed edges, so floor both.
            length = max(0.1, length)
            speed = max(0.1, speed)

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
    """BFS shortest path over the node graph.

    Hands back the node ids from origin to dest inclusive, or None if dest
    isn't reachable.
    """
    if origin == dest:
        return [origin]

    if origin not in adjacency:
        # An origin with only incoming edges has nowhere to go; the BFS below
        # just returns None for it.
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
    """Build the SUMO nodes XML that feeds netconvert."""
    lines: List[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<nodes>')
    for node_id in sorted(graph.nodes.keys()):
        node = graph.nodes[node_id]
        lines.append(f'    <node id="{node.id}" x="{node.x}" y="{node.y}" type="priority"/>')
    lines.append('</nodes>')
    return "\n".join(lines)


def build_sumo_edges_xml(graph: NetworkGraph) -> str:
    """Build the SUMO edges XML that feeds netconvert.

    Self-loops (from_node == to_node) get filtered out. SUMO 1.26's
    netconvert exits non-zero and writes no output when it hits one, even
    though it only logs a Warning about it. The canonical SCC already drops
    self-loops, so this just keeps the SUMO build in step with the routable
    subgraph.
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
    canonical_routes: Optional[Dict[str, List[str]]] = None,
) -> str:
    """Build the SUMO routes file from demand.csv and the network graph.

    Only trips in ``feasible`` (the shared cross-engine set) get routed.

    There are two ways routes get computed. If ``canonical_routes`` is
    passed in (the shared BFS output from
    ``adapters.common.canonical_routes.compute_canonical_routes``), we skip
    the inline BFS and just read the pre-computed
    ``Dict[trip_id, List[node_id]]``. Both the SUMO and MATSim adapters
    accept the same dict, so a scenario pays the BFS cost once, not twice.
    If it's ``None`` (the standalone CLI path), we run our own state-aware
    BFS in the loop, same as before Phase 14.

    Either way the BFS is state-aware (V5+): it honors OSM turn
    restrictions, and when no restriction-respecting path exists it falls
    back to plain BFS so the trip still gets rendered. On real OSM networks
    turn restrictions don't actually disconnect any OD pair, so this
    fallback is rare.
    """
    from pipeline.network.turn_restrictions import (
        parse_turn_restrictions, build_forbidden_moves,
        shortest_path_with_restrictions,
    )

    from adapters.common.vehicle_types import (
        SIMFORGE_CAR_VTYPE_ID, sumo_vtype_xml,
    )

    lines: List[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append("<!-- SUMO routes generated from canonical demand.csv -->")
    lines.append(f"<!-- Scenario: {summary.scenario_id}, trips: {summary.trip_count} -->")
    lines.append("<routes>")
    # The shared SimForge car type (V11+). See adapters/common/vehicle_types.py
    # for why the three engines line up: SUMO length+minGap, MATSim effective
    # length, and DTALite PCE all describe the same car.
    lines.append(sumo_vtype_xml())

    # If the harness already ran the shared BFS, skip ours. We still set up
    # the same local counters so the logging looks identical on both paths.
    using_shared_routes = canonical_routes is not None
    forbidden_moves: dict = {}
    network_path = demand_path.parent / "network.xml"
    if not using_shared_routes:
        # Turn restrictions are a V5+ thing; older networks hand back an empty
        # list, and then state-aware BFS is just plain BFS.
        restrictions = parse_turn_restrictions(network_path)
        if restrictions:
            # Outgoing links per node, needed to expand the `only_*_turn` rules.
            outgoing_links_by_node: dict = {}
            for u, neighbors in graph.adjacency.items():
                outgoing_links_by_node[u] = [
                    graph.edge_lookup[(u, v)].id
                    for v in neighbors
                    if (u, v) in graph.edge_lookup
                ]
            forbidden_moves = build_forbidden_moves(restrictions, outgoing_links_by_node)
            logger.info(
                "[sumo] state-aware BFS: %d turn restrictions, %d forbidden (via,from)→to entries",
                len(restrictions), len(forbidden_moves),
            )
    else:
        logger.info(
            "[sumo] using pre-routed canonical paths: %d trips",
            len(canonical_routes),
        )

    route_failures: List[str] = []
    restriction_fallbacks = 0

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

            # Use the pre-computed route if we have one, else run the inline
            # BFS. The two produce byte-identical paths per trip_id, which
            # tests/test_canonical_routes.py::TestByteIdentityVsLegacy pins down.
            if using_shared_routes:
                path_nodes = canonical_routes.get(trip_id) or None
            elif forbidden_moves:
                path_nodes = shortest_path_with_restrictions(
                    origin=origin, dest=dest,
                    adjacency=graph.adjacency,
                    edge_lookup=graph.edge_lookup,
                    forbidden_moves=forbidden_moves,
                )
                if path_nodes is None:
                    restriction_fallbacks += 1
                    path_nodes = shortest_path_nodes(graph.adjacency, origin, dest)
            else:
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

            lines.append(f'  <vehicle id="{veh_id}" type="{SIMFORGE_CAR_VTYPE_ID}" depart="{depart}">')
            lines.append(f'    <route id="{route_id}" edges="{edges_str}"/>')
            lines.append("  </vehicle>")

    pb.finish()

    if forbidden_moves:
        logger.info(
            "[sumo] %d trips had no restriction-respecting path "
            "(fell back to plain BFS); %d total trips routed.",
            restriction_fallbacks, len(feasible) - len(route_failures),
        )

    # If anything lands here, the shared SCC filter and SUMO's BFS disagree,
    # which shouldn't be possible. Make noise rather than drop trips quietly.
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

def prepare_sumo_inputs(
    scenario_root: Path,
    output_dir: Path,
    canonical_routes: Optional[Dict[str, List[str]]] = None,
) -> ScenarioSummary:
    """Write the SUMO input files for a canonical scenario.

    Makes output_dir, builds a ScenarioSummary, parses the network into a
    graph, and writes:
      - nodes.nod.xml  (SUMO nodes, input to netconvert)
      - edges.edg.xml  (SUMO edges, input to netconvert)
      - net.net.xml    (netconvert's output)
      - routes.rou.xml (a vehicle and route per trip that has a valid path)
      - toy.sumocfg    (ties net and routes together with the time horizon)
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

    # Fairness: prune to the largest SCC before writing anything, the same as
    # MATSim's clean_network and DTALite's prepare path. Skip this and SUMO
    # would write the full canonical network, dead-end stubs and all, while
    # the other two write only the SCC subset. That gap once made SUMO's
    # input network read 314 nodes / 346 links bigger than the others on
    # chicago_1k_car. The trips are already pinned to SCC endpoints by the
    # feasibility filter, so the pruned nodes were unused anyway; this just
    # makes the input files byte-comparable for the audit_fairness Q2 check.
    from pipeline.network.scc import compute_largest_scc
    scc_node_ids = compute_largest_scc(
        set(graph.nodes.keys()),
        [(lk.from_node, lk.to_node) for lk in graph.links],
    )
    scc_nodes = {nid: n for nid, n in graph.nodes.items() if nid in scc_node_ids}
    scc_links = [lk for lk in graph.links
                 if lk.from_node in scc_node_ids and lk.to_node in scc_node_ids]
    # Rebuild adjacency and edge_lookup against the filtered links, and don't
    # skip this. shortest_path_nodes (the BFS) reads these two indices to
    # route every trip; leave them stale and the BFS finds no edges, every
    # trip falls into the "SCC-feasible but SUMO failed to route" bucket, and
    # routes.rou.xml comes out empty. Found via audit_fairness Q3=0 on
    # chicago_1k_car smoke2 (Pitzer 2026-04-27).
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

    # The shared feasibility set: every engine simulates exactly this subset.
    # SUMO only does cars for now, so transit/bike/walk trips drop out of the
    # set here, which keeps the cross-engine Q3 audit on one common target.
    feasible, feas_report = _feasibility.feasible_trip_ids(
        network_path, demand_path, supported_modes={"car"},
    )
    _feasibility.log_report(feas_report, engine="sumo")
    _feasibility.write_feasibility_report(feas_report, output_dir / "feasibility_report.json")

    # Build the routes. If the caller already computed canonical routes via
    # adapters.common.canonical_routes.compute_canonical_routes, we use those
    # and skip the inline BFS.
    routes_content = build_sumo_routes_xml(
        summary, graph, demand_path, feasible,
        canonical_routes=canonical_routes,
    )
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


# ---------------------------------------------------------------------------
# Adapter contract: run + parse (matches matsim_adapter / dtalite_adapter)
# ---------------------------------------------------------------------------


def run_sumo(
    config_path: Path,
    timeout_s: int = 3600,
    seed: Optional[int] = None,
    ignore_route_errors: bool = True,
    mesoscopic: bool = False,
) -> Tuple[bool, float, Optional[str]]:
    """Run SUMO against a prepared `.sumocfg`.

    This is the run half of the three-function adapter contract
    (`prepare_<engine>_inputs / run_<engine> / parse_<engine>_output`,
    written up in `doc/engines/THIRD_ENGINE_OPTIONS.md`).
    `execution.run_benchmark.BenchmarkHarness.run_sumo` just delegates here
    so the actual behaviour stays in the adapter.

    Returns (success, runtime_seconds, error_message_or_None).
    """
    config_path = Path(config_path).resolve()
    cmd = ["sumo", "-c", str(config_path)]
    if seed is not None:
        cmd.extend(["--seed", str(seed)])
    if ignore_route_errors:
        cmd.extend(["--ignore-route-errors"])
    if mesoscopic:
        cmd.extend(["--mesosim"])
        logger.info("Using mesoscopic simulation mode (faster)")
    logger.info("Running: %s", " ".join(cmd))

    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=config_path.parent,
            check=False,
        )
        runtime = time.time() - start_time
        if result.returncode != 0:
            error_lines = [
                line for line in (result.stderr or "").split("\n")
                if line.strip().startswith("Error:")
            ]
            error_msg = (
                "\n".join(error_lines[:5])
                if error_lines
                else (result.stderr[:500] if result.stderr else "Unknown error")
            )
            return False, runtime, error_msg
        return True, runtime, None
    except subprocess.TimeoutExpired:
        return False, time.time() - start_time, f"Timeout after {timeout_s}s"
    except OSError as e:
        return False, time.time() - start_time, str(e)


def parse_sumo_output(output_dir: Path) -> dict:
    """Read the SUMO output dir into the standard metrics dict.

    Hands off to `evaluation.metrics.travel_time.parse_sumo_tripinfo` and
    returns the same shape as `parse_matsim_output` and
    `parse_dtalite_output` so the engines stay interchangeable:
    ``{"travel_time": {"mean": float, "p95": float, "trip_count": int}}``
    """
    from evaluation.metrics.travel_time import parse_sumo_tripinfo

    metrics: dict = {}
    tripinfo_path = Path(output_dir) / "tripinfo.xml"
    if tripinfo_path.exists():
        try:
            stats = parse_sumo_tripinfo(tripinfo_path)
            metrics["travel_time"] = {
                "mean": stats.mean_travel_time_s,
                "p95": stats.p95_travel_time_s,
                "trip_count": stats.trip_count,
            }
        except (OSError, ValueError) as e:
            logger.warning("Failed to parse tripinfo: %s", e)
    return metrics