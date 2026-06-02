"""
MATSim adapter for SimForge.

MATSim is an activity-based mesoscopic simulator: it models agents and the
daily activity plans they follow, not just vehicles. This adapter turns a
canonical bundle into MATSim's input formats.

Where it differs from SUMO:
- agents, not vehicles
- activity plans, not bare OD trips
- a queue-based mesoscopic traffic model
- normally iterates with replanning, which we switch off so the comparison
  is a single run

Usage:
    from adapters.matsim import prepare_matsim_inputs
    prepare_matsim_inputs("scenarios/chicago_1k_car", "out/matsim")
"""

import csv
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from xml.etree import ElementTree as ET
import logging

from adapters.common import feasibility as _feasibility

logger = logging.getLogger(__name__)


@dataclass
class MATSimConfig:
    """Configuration options for MATSim execution."""
    # Simulation settings
    iterations: int = 0  # 0 = single iteration (no replanning)
    flow_capacity_factor: float = 1.0
    storage_capacity_factor: float = 1.0
    
    # Time settings (in seconds from midnight)
    start_time_s: int = 0
    end_time_s: int = 108000  # 30 hours to capture late arrivals
    
    # Memory settings
    java_heap_gb: int = 4
    
    # Output settings
    write_events: bool = True
    write_plans: bool = True
    
    def to_dict(self) -> dict:
        return {
            "iterations": self.iterations,
            "flow_capacity_factor": self.flow_capacity_factor,
            "storage_capacity_factor": self.storage_capacity_factor,
            "start_time_s": self.start_time_s,
            "end_time_s": self.end_time_s,
            "java_heap_gb": self.java_heap_gb,
        }


def find_matsim_jar() -> Optional[Path]:
    """Look for the MATSim JAR in the usual places."""
    import os
    
    possible_paths = [
        Path("/opt/matsim/matsim.jar"),
        Path("/usr/local/share/matsim/matsim.jar"),
        Path.home() / "matsim" / "matsim.jar",
        Path.home() / ".local" / "share" / "matsim" / "matsim.jar",
    ]
    
    # Check MATSIM_HOME environment variable
    matsim_home = os.environ.get("MATSIM_HOME")
    if matsim_home:
        possible_paths.insert(0, Path(matsim_home) / "matsim.jar")
        # Also check for matsim-{version}.jar pattern
        for jar in Path(matsim_home).glob("matsim-*.jar"):
            if "sources" not in jar.name:
                possible_paths.insert(0, jar)
    
    # Check lib/ folder in project root (relative to this file)
    project_lib = Path(__file__).parent.parent.parent / "lib"
    if project_lib.exists():
        for version_dir in project_lib.glob("matsim-*"):
            if version_dir.is_dir():
                for jar in version_dir.glob("matsim-*.jar"):
                    if "sources" not in jar.name:
                        possible_paths.insert(0, jar)
    
    for p in possible_paths:
        if p.exists():
            return p
    
    # Check for any matsim*.jar in current directory
    for jar in Path(".").glob("matsim*.jar"):
        return jar
    
    return None


def check_java_available() -> Tuple[bool, str]:
    """Is Java on PATH, and if so what version."""
    try:
        result = subprocess.run(
            ["java", "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        # Java version is typically in stderr
        version_output = result.stderr or result.stdout
        if "version" in version_output.lower():
            # Extract version number
            lines = version_output.strip().split("\n")
            return True, lines[0] if lines else "unknown"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    return False, "Java not found"


def seconds_to_time_string(seconds: int) -> str:
    """Convert seconds since midnight to HH:MM:SS format."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def load_canonical_network(network_path: Path) -> Tuple[Dict, List]:
    """Read network.xml, hand back its nodes and links."""
    tree = ET.parse(network_path)
    root = tree.getroot()
    
    nodes = {}
    nodes_elem = root.find("nodes")
    if nodes_elem is not None:
        for node_elem in nodes_elem.findall("node"):
            node_id = node_elem.get("id")
            if node_id:
                nodes[node_id] = {
                    "id": node_id,
                    "x": float(node_elem.get("x", 0)),
                    "y": float(node_elem.get("y", 0)),
                }
    
    links = []
    links_elem = root.find("links")
    if links_elem is not None:
        for link_elem in links_elem.findall("link"):
            link_id = link_elem.get("id")
            if link_id:
                links.append({
                    "id": link_id,
                    "from": link_elem.get("from"),
                    "to": link_elem.get("to"),
                    "length": float(link_elem.get("length", 100)),
                    "speed": float(link_elem.get("speed_limit", 13.9)),
                    "lanes": int(link_elem.get("lanes", 1)),
                })
    
    return nodes, links


def _largest_strongly_connected_component(nodes: Dict, links: List) -> set:
    """The largest strongly connected component, as a set of node IDs.

    Plain Kosaraju: one DFS pass forward to get a finish order, a second
    pass over the reverse graph in that order to peel off components.
    """

    # Adjacency both ways, forward and reverse.
    fwd = {}
    rev = {}
    for link in links:
        f, t = link["from"], link["to"]
        if f == t:
            continue
        fwd.setdefault(f, []).append(t)
        rev.setdefault(t, []).append(f)

    all_nodes = set(nodes.keys())
    visited = set()
    finish_order = []

    # Pass 1: DFS on forward graph to get finish order
    for start in all_nodes:
        if start in visited:
            continue
        stack = [(start, False)]
        while stack:
            node, processed = stack.pop()
            if processed:
                finish_order.append(node)
                continue
            if node in visited:
                continue
            visited.add(node)
            stack.append((node, True))
            for nb in fwd.get(node, []):
                if nb not in visited:
                    stack.append((nb, False))

    # Pass 2: DFS on reverse graph in reverse finish order
    visited.clear()
    best_component = set()

    for start in reversed(finish_order):
        if start in visited:
            continue
        component = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            component.add(node)
            for nb in rev.get(node, []):
                if nb not in visited:
                    stack.append(nb)
        if len(component) > len(best_component):
            best_component = component

    return best_component


def clean_network(nodes: Dict, links: List) -> tuple:
    """Keep only the largest SCC, drop everything else.

    Returns (filtered_nodes, filtered_links, reachable_node_ids).
    """
    reachable = _largest_strongly_connected_component(nodes, links)

    filtered_nodes = {nid: n for nid, n in nodes.items() if nid in reachable}
    filtered_links = [
        l for l in links
        if l["from"] in reachable and l["to"] in reachable and l["from"] != l["to"]
    ]

    removed_nodes = len(nodes) - len(filtered_nodes)
    removed_links = len(links) - len(filtered_links)
    if removed_nodes > 0 or removed_links > 0:
        logger.info(
            "  Network cleaning: kept %d/%d nodes, %d/%d links "
            "(removed %d nodes, %d links from disconnected components)",
            len(filtered_nodes), len(nodes), len(filtered_links), len(links),
            removed_nodes, removed_links
        )

    return filtered_nodes, filtered_links, reachable


def build_matsim_link_indices(
    valid_links: List[dict], link_adjacency: dict,
) -> Dict[str, object]:
    """Pre-build the O(1) lookup tables used to find links per trip.

    The old code did a per-trip O(N) linear scan; this builds the index
    once up front and then every trip is a dict lookup. On chicago_200k_car
    (~1M links, 200K trips) that scan used to burn ~64 h in find_link_for_*,
    and it's under a second now. The output is byte-identical because each
    table records the *first* match in the original ``valid_links`` order,
    which is exactly what the linear scan returned.

    Returns a dict of five lookup tables plus one fallback link id:

    - ``nodes_with_outgoing``: set of node_ids that appear as a from-node
      in at least one link (i.e., have outgoing edges).
    - ``origin_links_by_to_first``: node_id -> first link_id where
      link.to == node_id.
    - ``origin_links_by_from_filt_first``: node_id -> first link_id where
      link.from == node_id AND link.to in nodes_with_outgoing (the
      "second priority" filter of the old find_link_for_origin).
    - ``origin_links_touching_first``: node_id -> first link_id where
      link.to == node_id OR link.from == node_id (the fallback).
    - ``dest_links_by_from_first``: node_id -> first link_id where
      link.from == node_id (the primary destination priority).
    - ``dest_links_by_to_first``: node_id -> first link_id where
      link.to == node_id (the destination fallback).
    - ``fallback_link_id``: links[0]["id"] when every other lookup misses.
    """
    nodes_with_outgoing = set(link_adjacency.keys())

    origin_links_by_to_first: Dict[str, str] = {}
    origin_links_by_from_filt_first: Dict[str, str] = {}
    origin_links_touching_first: Dict[str, str] = {}
    dest_links_by_from_first: Dict[str, str] = {}
    dest_links_by_to_first: Dict[str, str] = {}

    for link in valid_links:
        lid = link["id"]
        tt = link["to"]
        ff = link["from"]
        if tt not in origin_links_by_to_first:
            origin_links_by_to_first[tt] = lid
        if tt in nodes_with_outgoing and ff not in origin_links_by_from_filt_first:
            origin_links_by_from_filt_first[ff] = lid
        if tt not in origin_links_touching_first:
            origin_links_touching_first[tt] = lid
        if ff not in origin_links_touching_first:
            origin_links_touching_first[ff] = lid
        if ff not in dest_links_by_from_first:
            dest_links_by_from_first[ff] = lid
        if tt not in dest_links_by_to_first:
            dest_links_by_to_first[tt] = lid

    return {
        "nodes_with_outgoing": nodes_with_outgoing,
        "origin_links_by_to_first": origin_links_by_to_first,
        "origin_links_by_from_filt_first": origin_links_by_from_filt_first,
        "origin_links_touching_first": origin_links_touching_first,
        "dest_links_by_from_first": dest_links_by_from_first,
        "dest_links_by_to_first": dest_links_by_to_first,
        "fallback_link_id": valid_links[0]["id"] if valid_links else None,
    }


def find_link_for_origin(node_id: str, idx: Dict[str, object]) -> Optional[str]:
    """The O(1) lookup; see ``build_matsim_link_indices`` for the tables it
    reads. Byte-for-byte the same answer the old linear scan gave.

    A MATSim agent departs from the TO-node of its activity link, so we want
    a link whose TO-node is the origin and that has somewhere to go next.
    """
    nodes_with_outgoing = idx["nodes_with_outgoing"]
    # First choice: a link ending at the origin (TO=origin) that has outgoing edges.
    if node_id in nodes_with_outgoing:
        link_id = idx["origin_links_by_to_first"].get(node_id)
        if link_id is not None:
            return link_id
    # Second choice: a link starting at the origin (FROM=origin) whose TO end can go on.
    link_id = idx["origin_links_by_from_filt_first"].get(node_id)
    if link_id is not None:
        return link_id
    # Last resort: any link touching the node at all.
    link_id = idx["origin_links_touching_first"].get(node_id)
    if link_id is not None:
        return link_id
    return idx["fallback_link_id"]


def find_link_for_destination(node_id: str, idx: Dict[str, object]) -> Optional[str]:
    """The O(1) lookup; see ``build_matsim_link_indices``.

    MATSim routes from the origin's TO-node to the destination's FROM-node,
    so we want a link whose FROM-node is the destination, falling back to its
    TO-node.
    """
    link_id = idx["dest_links_by_from_first"].get(node_id)
    if link_id is not None:
        return link_id
    link_id = idx["dest_links_by_to_first"].get(node_id)
    if link_id is not None:
        return link_id
    return idx["fallback_link_id"]


def build_matsim_vehicles_xml() -> str:
    """Build MATSim vehicles.xml with the shared SimForge car type.

    Since V11 the numbers come from ``adapters/common/vehicle_types.py``, so
    all three engines agree on the car. MATSim's ``length`` here is the
    effective spacing (body plus comfort gap), which is its convention and
    matches SUMO's ``length + minGap``.
    """
    from adapters.common.vehicle_types import matsim_vehicle_type_xml
    return matsim_vehicle_type_xml()


def build_matsim_network_xml(nodes: Dict, links: List) -> str:
    """Build MATSim network.xml from the canonical nodes and links."""
    lines = []
    lines.append('<?xml version="1.0" encoding="utf-8"?>')
    lines.append('<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v2.dtd">')
    lines.append('<network name="simforge_network">')
    
    # Nodes
    lines.append('  <nodes>')
    for node_id, node in sorted(nodes.items()):
        lines.append(f'    <node id="{node_id}" x="{node["x"]}" y="{node["y"]}"/>')
    lines.append('  </nodes>')
    
    # capperiod sets the window the capacity number applies to.
    # MATSim rejects self-loops (from == to), so drop them.
    valid_links = [link for link in links if link["from"] != link["to"]]

    lines.append('  <links capperiod="01:00:00">')
    for link in valid_links:
        # Capacity = lanes * 1800 veh/h, a typical saturation flow.
        lanes = max(1, link["lanes"])  # at least one lane
        capacity = lanes * 1800
        length = max(1.0, link["length"])  # floor at 1 m
        # modes="car" is what makes the link routable.
        lines.append(
            f'    <link id="{link["id"]}" '
            f'from="{link["from"]}" to="{link["to"]}" '
            f'length="{length:.2f}" '
            f'freespeed="{link["speed"]:.2f}" '
            f'capacity="{capacity}" '
            f'permlanes="{lanes}" '
            f'modes="car"/>'
        )
    lines.append('  </links>')
    
    lines.append('</network>')
    return "\n".join(lines)


class _LinkRef:
    """Tiny shim so MATSim's dict-style links work with the generic
    `pipeline.network.turn_restrictions.shortest_path_with_restrictions`
    BFS, which just wants each edge_lookup value to have an `.id`."""
    __slots__ = ("id",)

    def __init__(self, link_id: str):
        self.id = link_id


def build_matsim_plans_xml(
    demand_path: Path,
    links: List,
    feasible: Set[str],
    network_path: Optional[Path] = None,
    canonical_routes: Optional[Dict[str, List[str]]] = None,
) -> str:
    """Build MATSim plans.xml from demand.csv.

    Only trips in ``feasible`` (the shared cross-engine set) get written, so
    MATSim runs the same trips as everyone else.

    Like the SUMO adapter, routes come from one of two places. If
    ``canonical_routes`` is passed in (the shared BFS output from
    ``adapters.common.canonical_routes.compute_canonical_routes``), we look
    up each trip's path there and skip the inline BFS; both adapters share
    that dict, so the scenario pays the BFS cost once. If it's ``None`` (the
    standalone CLI path), we run our own state-aware BFS in the loop, loading
    turn restrictions from ``network_path``.

    Either way, when the network.xml carries an OSM ``<turn_restrictions>``
    block we pre-route with the same state-aware BFS the SUMO adapter uses
    and write the link sequence straight into MATSim's
    ``<route type="links">``. MATSim then drives that exact path instead of
    routing itself, so SUMO and MATSim run identical paths and the
    cross-engine travel-time comparison stays honest, both respecting real
    turn restrictions. Older bundles and synthetic networks have no such
    block, and there MATSim just routes on its own.
    """
    from pipeline.network.turn_restrictions import (
        parse_turn_restrictions, build_forbidden_moves,
        shortest_path_with_restrictions,
    )

    lines = []
    lines.append('<?xml version="1.0" ?>')
    # population_v6, the DTD that ships with MATSim 15. We used plans_v4
    # before V11.2, but its <route> only takes cost-optimisation `type`
    # values (dist|trav-time|num-nodes|num-intersects) and reads the text as
    # a node sequence, not a link sequence. Both of those fight V5 Phase 7's
    # whole point of feeding in a pre-routed link sequence. population_v6
    # takes `type="links" start_link="..." end_link=".."` directly, and
    # PopulationReaderMatsimV6 is in the same MATSim 15 JAR.
    lines.append('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">')
    lines.append('<population>')

    valid_links = [link for link in links if link["from"] != link["to"]]

    link_adjacency: Dict[str, List[str]] = {}
    for link in valid_links:
        link_adjacency.setdefault(link["from"], []).append(link["to"])

    # edge_lookup for the state-aware BFS: (from_node, to_node) -> object-with-id.
    edge_lookup: Dict[Tuple[str, str], _LinkRef] = {
        (link["from"], link["to"]): _LinkRef(link["id"])
        for link in valid_links
    }

    # If the harness already ran the shared BFS, skip the turn-restriction
    # setup. The flag tells the per-trip loop below which path to take.
    using_shared_routes = canonical_routes is not None
    forbidden_moves: dict = {}
    if not using_shared_routes:
        # Turn restrictions (V5+), when we were handed a network_path.
        restrictions = parse_turn_restrictions(network_path) if network_path else []
        if restrictions:
            outgoing_links_by_node: dict = {}
            for u, neighbors in link_adjacency.items():
                outgoing_links_by_node[u] = [
                    edge_lookup[(u, v)].id for v in neighbors
                    if (u, v) in edge_lookup
                ]
            forbidden_moves = build_forbidden_moves(restrictions, outgoing_links_by_node)
            logger.info(
                "[matsim] state-aware BFS: %d turn restrictions, "
                "%d forbidden (via,from)→to entries",
                len(restrictions), len(forbidden_moves),
            )
    else:
        logger.info(
            "[matsim] using pre-routed canonical paths: %d trips",
            len(canonical_routes),
        )

    # Build the O(1) link-finding indices once. Before this, each of the
    # 200K trips ran two O(N) scans over ~1M links inside
    # find_link_for_origin/find_link_for_destination, which was ~64 h of the
    # 73 h MATSim cold-prep wall on chicago_200k. This is a single O(N) pass,
    # and then every per-trip lookup is O(1).
    link_indices = build_matsim_link_indices(valid_links, link_adjacency)
    logger.info(
        "[matsim] built link-finding indices: %d nodes with outgoing edges, "
        "%d origin-by-to keys, %d dest-by-from keys",
        len(link_indices["nodes_with_outgoing"]),
        len(link_indices["origin_links_by_to_first"]),
        len(link_indices["dest_links_by_from_first"]),
    )

    missing_link = 0
    restriction_fallbacks = 0
    pre_routed = 0
    n_processed = 0
    PROGRESS_EVERY = 10000  # Phase 12.3: surface BFS-prep progress at WARNING
    with demand_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trip_id = row.get("trip_id", "").strip()
            if trip_id not in feasible:
                continue

            origin = row.get("origin_node_id", "").strip()
            dest = row.get("destination_node_id", "").strip()
            depart_s = row.get("departure_time_s", "0").strip()
            mode = row.get("mode", "car").strip()

            try:
                depart_seconds = int(float(depart_s))
            except ValueError:
                depart_seconds = 0

            origin_link = find_link_for_origin(origin, link_indices)
            dest_link = find_link_for_destination(dest, link_indices)

            # Both endpoints are in the SCC, so there has to be a link for
            # each. If there somehow isn't, count it and move on rather than
            # hide it.
            if not origin_link or not dest_link:
                missing_link += 1
                continue

            # Pre-route when we have turn restrictions, or when the harness
            # handed us canonical routes, so MATSim drives the exact path.
            route_link_ids: Optional[List[str]] = None
            path_nodes: Optional[List[str]] = None
            if using_shared_routes:
                path_nodes = canonical_routes.get(trip_id) or None
            elif forbidden_moves:
                path_nodes = shortest_path_with_restrictions(
                    origin=origin, dest=dest,
                    adjacency=link_adjacency,
                    edge_lookup=edge_lookup,
                    forbidden_moves=forbidden_moves,
                )
                if path_nodes is None:
                    restriction_fallbacks += 1
            if path_nodes is not None:
                route_link_ids = [
                    edge_lookup[(u, v)].id
                    for u, v in zip(path_nodes[:-1], path_nodes[1:])
                    if (u, v) in edge_lookup
                ]
                if route_link_ids:
                    pre_routed += 1

            end_time = seconds_to_time_string(depart_seconds)
            person_id = f"person_{trip_id}"

            lines.append(f'<person id="{person_id}">')
            lines.append('  <plan>')
            lines.append(f'    <activity type="h" link="{origin_link}" end_time="{end_time}"/>')
            if route_link_ids:
                # MATSim 15 / population_v6 wants the FULL link sequence in
                # the <route type="links"> text, start_link and end_link
                # included, not just the interior. Confirmed against MATSim's
                # own output_plans.xml.gz:
                #     <route type="links" start_link="A" end_link="Z">
                #         A B C D E ... X Y Z
                #     </route>
                # Yes, the first and last tokens repeat the start_link and
                # end_link attributes; that redundancy is just how MATSim
                # writes it. We learned this the hard way. Pre-V12 we emitted
                # only "B C D ... Y" (no A or Z), MATSim's mobsim saw a route
                # disjoint from where the agent actually stood, and it
                # rejected every transition. The log filled with
                # `DefaultTurnAcceptanceLogic` warnings ("Cannot move vehicle
                # person_t82 from link l1502 to link l28738") and
                # output_trips.csv.gz came out empty. Zero trips means zero
                # variance, so every MATSim cell scored R = 1.0000, which the
                # analyzer happily read as perfect determinism when it was
                # really no data at all. Found 2026-05-02 (Phase 12).
                #
                # The real traversal is [origin_link, *route_link_ids,
                # dest_link]; we de-dup in case the BFS already landed on
                # origin_link or dest_link (rare).
                full_path = []
                if not route_link_ids or route_link_ids[0] != origin_link:
                    full_path.append(origin_link)
                full_path.extend(route_link_ids)
                if not full_path or full_path[-1] != dest_link:
                    full_path.append(dest_link)
                start = full_path[0]
                end = full_path[-1]
                full_link_seq = " ".join(full_path)
                lines.append(f'    <leg mode="{mode}">')
                lines.append(
                    f'      <route type="links" start_link="{start}" '
                    f'end_link="{end}">{full_link_seq}</route>'
                )
                lines.append(f'    </leg>')
            else:
                # No pre-route, so let MATSim do its own routing.
                lines.append(f'    <leg mode="{mode}"/>')
            lines.append(f'    <activity type="w" link="{dest_link}"/>')
            lines.append('  </plan>')
            lines.append('</person>')

            n_processed += 1
            if n_processed % PROGRESS_EVERY == 0:
                logger.warning(
                    "[matsim] BFS-prep: %d feasible trips routed", n_processed
                )

    if forbidden_moves:
        logger.info(
            "[matsim] %d trips pre-routed via state-aware BFS, "
            "%d had no restriction-respecting path "
            "(MATSim will route those itself).",
            pre_routed, restriction_fallbacks,
        )

    if missing_link:
        logger.error(
            "MATSim could not attach links for %d feasible trips — "
            "this contradicts the shared SCC filter.",
            missing_link,
        )

    lines.append('</population>')
    return "\n".join(lines)


def build_matsim_config_xml(
    config: MATSimConfig,
    network_file: str = "network.xml",
    plans_file: str = "plans.xml",
    vehicles_file: str = "vehicles.xml",
    output_dir: str = "./output",
    random_seed: int = 42
) -> str:
    """Build MATSim config.xml from a MATSimConfig."""
    start_time = seconds_to_time_string(config.start_time_s)
    end_time = seconds_to_time_string(config.end_time_s)
    
    return f'''<?xml version="1.0" ?>
<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">
<config>
    <module name="global">
        <param name="randomSeed" value="{random_seed}"/>
        <param name="coordinateSystem" value="EPSG:4326"/>
        <param name="numberOfThreads" value="4"/>
    </module>
    
    <module name="network">
        <param name="inputNetworkFile" value="{network_file}"/>
    </module>
    
    <module name="vehicles">
        <param name="vehiclesFile" value="{vehicles_file}"/>
    </module>
    
    <module name="plans">
        <param name="inputPlansFile" value="{plans_file}"/>
        <param name="removingUnnecessaryPlanAttributes" value="true"/>
    </module>
    
    <module name="qsim">
        <param name="startTime" value="{start_time}"/>
        <param name="endTime" value="{end_time}"/>
        <param name="flowCapacityFactor" value="{config.flow_capacity_factor}"/>
        <param name="storageCapacityFactor" value="{config.storage_capacity_factor}"/>
        <param name="numberOfThreads" value="4"/>
        <param name="mainMode" value="car"/>
        <param name="vehiclesSource" value="modeVehicleTypesFromVehiclesData"/>
        <param name="simStarttimeInterpretation" value="onlyUseStarttime"/>
    </module>
    
    <module name="controler">
        <param name="outputDirectory" value="{output_dir}"/>
        <param name="firstIteration" value="0"/>
        <param name="lastIteration" value="{config.iterations}"/>
        <param name="writeEventsInterval" value="1"/>
        <param name="writePlansInterval" value="1"/>
        <param name="mobsim" value="qsim"/>
        <param name="overwriteFiles" value="deleteDirectoryIfExists"/>
    </module>
    
    <module name="planCalcScore">
        <parameterset type="scoringParameters">
            <param name="lateArrival" value="-18"/>
            <param name="earlyDeparture" value="-0"/>
            <param name="performing" value="6"/>
            <param name="waiting" value="-0"/>
            <param name="waitingPt" value="-2"/>
            
            <parameterset type="modeParams">
                <param name="mode" value="car"/>
                <param name="constant" value="0.0"/>
                <param name="marginalUtilityOfTraveling_util_hr" value="-6.0"/>
                <param name="monetaryDistanceRate" value="-0.0002"/>
            </parameterset>
            
            <parameterset type="activityParams">
                <param name="activityType" value="h"/>
                <param name="typicalDuration" value="12:00:00"/>
            </parameterset>
            
            <parameterset type="activityParams">
                <param name="activityType" value="w"/>
                <param name="typicalDuration" value="08:00:00"/>
                <param name="openingTime" value="06:00:00"/>
                <param name="closingTime" value="20:00:00"/>
            </parameterset>
        </parameterset>
    </module>
    
    <module name="strategy">
        <param name="maxAgentPlanMemorySize" value="1"/>
        <parameterset type="strategysettings">
            <param name="strategyName" value="BestScore"/>
            <param name="weight" value="1.0"/>
        </parameterset>
    </module>
</config>
'''


def load_canonical_paths(scenario_root: Path) -> Dict[str, Path]:
    """Pull the canonical file paths out of manifest.xml."""
    manifest_path = scenario_root / "manifest.xml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.xml not found at {manifest_path}")
    
    tree = ET.parse(manifest_path)
    root = tree.getroot()
    
    canonical_files = root.find("canonical_files")
    if canonical_files is None:
        raise ValueError("manifest.xml missing <canonical_files>")
    
    paths = {}
    for file_elem in canonical_files.findall("file"):
        file_type = file_elem.get("type")
        rel_path = file_elem.get("path")
        if file_type and rel_path:
            paths[file_type] = (scenario_root / rel_path).resolve()
    
    return paths


def prepare_matsim_inputs(
    scenario_path: str | Path,
    output_dir: str | Path,
    config: Optional[MATSimConfig] = None,
    random_seed: int = 42,
    canonical_routes: Optional[Dict[str, List[str]]] = None,
) -> Path:
    """Write the MATSim inputs for a scenario and return the config path.

    ``scenario_path`` is the canonical bundle, ``output_dir`` is where the
    generated files go, ``config`` and ``random_seed`` tune the run.

    ``canonical_routes`` is the optional shared BFS output
    (``Dict[trip_id, List[node_id]]``). Pass it and build_matsim_plans_xml
    reads routes straight from it instead of running its own BFS; leave it
    ``None`` and the plan builder routes for itself.
    """
    scenario_path = Path(scenario_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if config is None:
        config = MATSimConfig()
    
    logger.info("Preparing MATSim inputs for: %s", scenario_path)
    
    # Load canonical files
    paths = load_canonical_paths(scenario_path)
    network_path = paths.get("network")
    demand_path = paths.get("demand")
    
    if not network_path or not network_path.exists():
        raise FileNotFoundError(f"Network file not found: {network_path}")
    if not demand_path or not demand_path.exists():
        raise FileNotFoundError(f"Demand file not found: {demand_path}")
    
    # The shared feasibility set: the trips every engine runs. MATSim only
    # does cars for now, so transit/bike/walk drop out here too.
    feasible, feas_report = _feasibility.feasible_trip_ids(
        network_path, demand_path, supported_modes={"car"},
    )
    _feasibility.log_report(feas_report, engine="matsim")
    _feasibility.write_feasibility_report(feas_report, output_dir / "feasibility_report.json")

    # Load and convert network
    logger.info("Converting network to MATSim format...")
    nodes, links = load_canonical_network(network_path)

    # MATSim's mobsim crashes on dangling links, so its network input has to
    # be the SCC. We prune to the same SCC the feasibility filter uses, which
    # keeps the trips and the emitted network consistent.
    nodes, links, _reachable = clean_network(nodes, links)

    network_xml = build_matsim_network_xml(nodes, links)
    network_out = output_dir / "network.xml"
    network_out.write_text(network_xml, encoding="utf-8")
    logger.info("  Created: %s", network_out)

    # Demand to plans, feasible trips only, so the subset matches every
    # engine. We hand over `network_path` so the V5+ turn-restriction
    # pre-routing can run the same state-aware BFS the SUMO adapter uses and
    # the cross-engine paths line up. If the harness already computed the
    # shared routes, passing them in skips the inline BFS.
    logger.info("Converting demand to MATSim plans...")
    plans_xml = build_matsim_plans_xml(
        demand_path, links, feasible, network_path=network_path,
        canonical_routes=canonical_routes,
    )
    plans_out = output_dir / "plans.xml"
    plans_out.write_text(plans_xml, encoding="utf-8")
    logger.info("  Created: %s", plans_out)
    
    # Create vehicles definition
    logger.info("Creating MATSim vehicles definition...")
    vehicles_xml = build_matsim_vehicles_xml()
    vehicles_out = output_dir / "vehicles.xml"
    vehicles_out.write_text(vehicles_xml, encoding="utf-8")
    logger.info("  Created: %s", vehicles_out)
    
    # Create output directory for MATSim
    matsim_output = output_dir / "output"
    matsim_output.mkdir(exist_ok=True)
    
    # Create config
    logger.info("Creating MATSim config...")
    config_xml = build_matsim_config_xml(
        config,
        network_file="network.xml",
        plans_file="plans.xml",
        vehicles_file="vehicles.xml",
        output_dir="./output",
        random_seed=random_seed
    )
    config_out = output_dir / "config.xml"
    config_out.write_text(config_xml, encoding="utf-8")
    logger.info("  Created: %s", config_out)
    
    logger.info("MATSim inputs ready at: %s", output_dir)
    return config_out


def run_matsim(
    config_path: str | Path,
    timeout_s: int = 86400,
    java_heap_gb: int = 4
) -> Tuple[bool, float, Optional[str]]:
    """Run MATSim against a prepared config.

    ``config_path`` is the MATSim config, ``timeout_s`` caps the runtime, and
    ``java_heap_gb`` sizes the JVM heap. Returns
    (success, runtime_seconds, error_message).
    """
    import time
    
    config_path = Path(config_path).resolve()
    
    # Check Java
    java_ok, java_version = check_java_available()
    if not java_ok:
        return False, 0.0, f"Java not available: {java_version}"
    
    logger.info("Java version: %s", java_version)
    
    # Find MATSim JAR
    matsim_jar = find_matsim_jar()
    if matsim_jar is None:
        return False, 0.0, "MATSim JAR not found. Please install MATSim or set MATSIM_HOME"
    
    logger.info("Using MATSim: %s", matsim_jar)
    
    # Build classpath including all dependencies in libs/ folder
    matsim_dir = matsim_jar.parent
    libs_dir = matsim_dir / "libs"
    
    # List every JAR by hand. Classpath wildcards are flaky when the path has
    # spaces in it (and ours does, thanks to iCloud).
    classpath_parts = [str(matsim_jar)]
    if libs_dir.exists():
        for jar in libs_dir.glob("*.jar"):
            classpath_parts.append(str(jar))
    classpath = ":".join(classpath_parts)

    # MATSim 15+ entry point is RunMatsim, not the old Controler.
    cmd = [
        "java",
        f"-Xmx{java_heap_gb}g",
        "-cp", classpath,
        "org.matsim.run.RunMatsim",
        str(config_path)
    ]
    
    logger.debug("Running: %s", ' '.join(cmd))
    
    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=config_path.parent,
            check=False
        )
        elapsed = time.time() - start_time
        
        if result.returncode == 0:
            return True, elapsed, None
        else:
            error = result.stderr[:500] if result.stderr else f"Exit code {result.returncode}"
            return False, elapsed, error
            
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return False, elapsed, f"Timeout after {timeout_s}s"
    except OSError as e:
        elapsed = time.time() - start_time
        return False, elapsed, str(e)


def parse_matsim_output(output_dir: Path) -> dict:
    """Read MATSim's output dir and pull out travel-time stats.

    Returns a dict of stats, or an empty dict if there's nothing to read.
    """
    import gzip

    # Prefer the gzipped trips file, fall back to uncompressed.
    trips_file = output_dir / "output_trips.csv.gz"
    if not trips_file.exists():
        trips_file = output_dir / "output_trips.csv"
    
    if not trips_file.exists():
        logger.warning("No trips output found in %s", output_dir)
        return {}
    
    travel_times = []
    
    try:
        if trips_file.suffix == ".gz":
            f = gzip.open(trips_file, "rt", encoding="utf-8")
        else:
            f = open(trips_file, "r", encoding="utf-8")
        
        with f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                # trav_time is in HH:MM:SS format
                trav_time_str = row.get("trav_time", "")
                if trav_time_str:
                    try:
                        parts = trav_time_str.split(":")
                        if len(parts) == 3:
                            h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                            travel_times.append(h * 3600 + m * 60 + s)
                    except ValueError:
                        pass
    except (OSError, csv.Error, KeyError) as e:
        logger.warning("Failed to parse MATSim output: %s", e)
        return {}
    
    if not travel_times:
        return {}
    
    import statistics
    travel_times_sorted = sorted(travel_times)
    p95_idx = int(len(travel_times_sorted) * 0.95)
    
    return {
        "trip_count": len(travel_times),
        "mean_travel_time_s": statistics.mean(travel_times),
        "median_travel_time_s": statistics.median(travel_times),
        "p95_travel_time_s": travel_times_sorted[p95_idx] if p95_idx < len(travel_times_sorted) else travel_times_sorted[-1],
        "min_travel_time_s": min(travel_times),
        "max_travel_time_s": max(travel_times),
    }


# CLI interface
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="MATSim Adapter")
    parser.add_argument("scenario", help="Path to canonical scenario bundle")
    parser.add_argument("output", help="Output directory")
    parser.add_argument("--iterations", type=int, default=0, help="MATSim iterations (0=single run)")
    parser.add_argument("--run", action="store_true", help="Also run the simulation")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--heap", type=int, default=4, help="Java heap size in GB")
    
    args = parser.parse_args()
    
    # Check Java
    _java_ok, _java_version = check_java_available()
    if _java_ok:
        print(f"✓ Java available: {_java_version}")
    else:
        print("⚠ Java not found - MATSim requires Java 11+")
    
    # Check MATSim
    _matsim_jar = find_matsim_jar()
    if _matsim_jar:
        print(f"✓ MATSim found: {_matsim_jar}")
    else:
        print("⚠ MATSim JAR not found - set MATSIM_HOME or place matsim.jar in working directory")
    
    # Create config
    _config = MATSimConfig(iterations=args.iterations)
    
    # Prepare inputs
    print("\nPreparing MATSim inputs...")
    _config_path = prepare_matsim_inputs(args.scenario, args.output, _config, args.seed)
    print(f"✓ MATSim config: {_config_path}")
    
    # Optionally run
    if args.run:
        if not _java_ok:
            print("\n✗ Cannot run without Java")
        elif not _matsim_jar:
            print("\n✗ Cannot run without MATSim JAR")
        else:
            print("\nRunning MATSim...")
            _success, _runtime, _error = run_matsim(_config_path, java_heap_gb=args.heap)
            if _success:
                print(f"✓ Completed in {_runtime:.2f}s")
                
                # Parse output
                _output_dir = Path(args.output) / "output"
                stats = parse_matsim_output(_output_dir)
                if stats:
                    print("\nTravel Time Statistics:")
                    print(f"  Trips: {stats['trip_count']}")
                    print(f"  Mean: {stats['mean_travel_time_s']:.1f}s")
                    print(f"  P95: {stats['p95_travel_time_s']:.1f}s")
            else:
                print(f"✗ Failed: {_error}")
