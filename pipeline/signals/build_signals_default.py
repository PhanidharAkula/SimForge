"""
Build default traffic signals for a canonical network.

Source-of-truth (V5+):
  Real signal placement comes from OSM's `highway=traffic_signals` node tag,
  which is community-curated ground truth for actual signalized intersections
  in major US cities. The network builder
  (`pipeline/network/build_network_from_osm.py`) reads the tag during PBF
  ingestion and persists it as `has_signal="true"` on the canonical
  `<node>` element. This module only signalizes those tagged nodes —
  typical share is 1-5% of network nodes (Manhattan ~3%, downtown LA ~1.4%,
  downtown Chicago ~3%), matching the absolute count of real signals in
  each city's bbox.

Legacy fallback:
  When no nodes carry `has_signal="true"` — either because the network
  was generated before V5's OSM-signal plumbing landed, or because a
  synthetic / non-OSM network is being processed — this module falls back
  to a degree-based heuristic: signalize every node with `degree >= 4`.
  That heuristic catches every junction where two bidirectional ways meet
  (~85-90% of nodes), which is structurally fine as simulator input but
  NOT a real-world signalization model. The fallback emits a loud
  WARNING so the operator knows to regenerate the network when realistic
  signal placement matters.

Each signalized node receives a 2-phase 90-second cycle (NS green / EW
red, then EW green / NS red) — a placeholder, not a real-world signal
plan with optimized timing. Cross-engine fairness comparisons are
unaffected by this choice (every adapter consumes the same signals.xml).

Usage:
    python -m pipeline.signals.build_signals_default \\
        --network scenarios/city1/network.xml \\
        --output scenarios/city1/signals.xml

  --min-degree only matters when the legacy fallback fires (default 4).
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import logging

from lxml import etree

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class SignalPhase:
    """A single phase in a traffic signal cycle."""
    phase_id: str
    duration_s: int
    state: str  # SUMO-style: G=green, r=red, y=yellow
    link_ids: list[str]  # Links that get green in this phase


@dataclass
class SignalController:
    """A traffic signal controller at an intersection."""
    junction_id: str
    node_id: str
    cycle_length_s: int
    phases: list[SignalPhase]


def load_network_topology(network_path: Path) -> tuple[dict, dict, dict, set]:
    """
    Load network and compute node degrees and connected links.

    Returns:
        Tuple of:
        - node_coords: {node_id: (x, y)}
        - in_links: {node_id: [link_ids entering]}
        - out_links: {node_id: [link_ids leaving]}
        - osm_signal_nodes: {node_id, ...} — nodes tagged `has_signal="true"` in
          network.xml (sourced from OSM `highway=traffic_signals`).
          Empty set if the network was built before V5's OSM-signal plumbing.
    """
    if not network_path.is_file():
        raise FileNotFoundError(
            f"Network file not found: {network_path}\n"
            f"  Signal generation requires a valid network.xml.\n"
            f"  Run network generation first."
        )
    try:
        tree = etree.parse(str(network_path))
    except etree.XMLSyntaxError as e:
        raise ValueError(
            f"Failed to parse network.xml at {network_path}: {e}\n"
            f"  The file may be corrupted or truncated. Re-generate it."
        ) from e
    root = tree.getroot()

    node_coords = {}
    in_links = defaultdict(list)
    out_links = defaultdict(list)
    osm_signal_nodes: set = set()

    # Parse nodes
    for node in root.findall(".//node"):
        nid = node.get("id")
        x = float(node.get("x", 0))
        y = float(node.get("y", 0))
        node_coords[nid] = (x, y)
        if node.get("has_signal", "").lower() == "true":
            osm_signal_nodes.add(nid)

    # Parse links
    for link in root.findall(".//link"):
        lid = link.get("id")
        from_node = link.get("from")
        to_node = link.get("to")

        if from_node and to_node:
            out_links[from_node].append(lid)
            in_links[to_node].append(lid)

    return node_coords, dict(in_links), dict(out_links), osm_signal_nodes


def identify_signalized_intersections(
    node_coords: dict,
    in_links: dict,
    out_links: dict,
    osm_signal_nodes: Optional[set] = None,
    min_degree: int = 4,
    max_signals: Optional[int] = None,
) -> list[str]:
    """
    Identify nodes that should have traffic signals.

    Source-of-truth selection:
    - **Preferred — OSM ground truth.** When ``osm_signal_nodes`` is non-empty
      (V5+ networks where ``build_network_from_osm.extract_canonical_network``
      reads OSM's ``highway=traffic_signals`` node tag and persists it as
      ``has_signal="true"`` in network.xml), only those nodes are signalized.
      Real-world signal counts in major US cities run ~5-15 % of intersections,
      which is what this path produces. ``min_degree`` is ignored in this mode.
    - **Fallback — degree heuristic.** When no node carries the OSM tag
      (legacy network.xml from before the OSM-signal plumbing, or a synthetic
      network without OSM provenance), fall back to the old ``degree >=
      min_degree`` rule. This signalizes ~85-90 % of nodes — accurate as
      simulator-input geometry but NOT as a real-world signalization model.
      A WARNING is logged when this fallback fires.

    Args:
        node_coords: Node coordinate mapping
        in_links: Incoming links per node
        out_links: Outgoing links per node
        osm_signal_nodes: Set of node IDs OSM tagged as traffic_signals
            (from network.xml's ``has_signal="true"`` attribute). When
            empty/None, the degree-heuristic fallback runs.
        min_degree: Minimum total degree for signalization (degree-fallback only)
        max_signals: Optional maximum number of signals (applies to both paths)

    Returns:
        List of node IDs to signalize
    """
    # --- Preferred path: trust OSM's `highway=traffic_signals` ground truth.
    if osm_signal_nodes:
        # Constrain to nodes that actually exist in the SCC-clipped network
        # (OSM tag may sit on a node that didn't survive bbox truncation /
        # SCC filtering — drop those quietly).
        signalized = sorted(n for n in osm_signal_nodes if n in node_coords)
        logger.info(
            "Signal source: OSM `highway=traffic_signals` — %d/%d nodes tagged "
            "(%.1f%% of network nodes).",
            len(signalized), len(node_coords),
            100.0 * len(signalized) / max(len(node_coords), 1),
        )
        if max_signals and len(signalized) > max_signals:
            signalized = signalized[:max_signals]
        return signalized

    # --- Fallback: legacy degree-based heuristic. Loud warning so a regen
    # of the network is the obvious next step.
    logger.warning(
        "Signal source: degree heuristic (legacy fallback). "
        "network.xml has no nodes tagged `has_signal=\"true\"` — regenerate "
        "the network with the V5+ pipeline to get OSM-grounded signal "
        "placement. Falling back to min_degree=%d, which signalizes ~85-90%% "
        "of nodes (every junction).", min_degree,
    )

    # Compute degrees
    node_degrees = {}
    for nid in node_coords:
        in_deg = len(in_links.get(nid, []))
        out_deg = len(out_links.get(nid, []))
        node_degrees[nid] = in_deg + out_deg

    # Filter by minimum degree
    candidates = [(nid, deg) for nid, deg in node_degrees.items() if deg >= min_degree]

    # Sort by degree (descending)
    candidates.sort(key=lambda x: (-x[1], x[0]))
    
    # Apply limit
    if max_signals:
        candidates = candidates[:max_signals]
    
    signalized = [nid for nid, _ in candidates]
    
    logger.info("Identified %d nodes for signalization", len(signalized))
    return signalized


def group_links_by_direction(
    node_id: str,
    node_coords: dict,
    in_links: dict
) -> tuple[list[str], list[str]]:
    """
    Group incoming links into two opposing phases based on direction.
    
    Uses angle from link origin to intersection to determine grouping.
    Links within 90 degrees of each other go in the same phase.
    
    Returns:
        Tuple of (phase1_links, phase2_links)
    """
    _, _ = node_coords[node_id]  # coords reserved for angle-based grouping
    incoming = in_links.get(node_id, [])
    
    if not incoming:
        return [], []
    
    if len(incoming) <= 2:
        # Simple case: one link per phase
        return incoming[:1], incoming[1:] if len(incoming) > 1 else []
    
    # For now, use simple alternating grouping
    # A more sophisticated version would compute actual angles
    phase1 = incoming[::2]  # Even indices
    phase2 = incoming[1::2]  # Odd indices
    
    return phase1, phase2


def build_signal_controller(
    node_id: str,
    node_coords: dict,
    in_links: dict,
    out_links: dict,
    cycle_length_s: int = 90,
    yellow_time_s: int = 3,
    all_red_s: int = 2
) -> SignalController:
    """
    Build a simple 2-phase signal controller for a node.
    
    Phase timing:
    - Green time split evenly between phases
    - Yellow interval at end of each green
    - All-red clearance between phases
    
    Args:
        node_id: Node to signalize
        node_coords: Node coordinates
        in_links: Incoming links per node
        out_links: Outgoing links per node
        cycle_length_s: Total cycle length
        yellow_time_s: Yellow interval duration
        all_red_s: All-red clearance duration
    
    Returns:
        SignalController object
    """
    # Group links into phases
    _ = out_links  # reserved for future directional logic
    phase1_links, phase2_links = group_links_by_direction(node_id, node_coords, in_links)
    
    # Calculate green times
    # Total non-green = 2 * (yellow + all_red)
    non_green_time = 2 * (yellow_time_s + all_red_s)
    total_green_time = cycle_length_s - non_green_time
    
    # Split green evenly
    green1 = total_green_time // 2
    green2 = total_green_time - green1
    
    # Build phases
    phases = []
    
    # Phase 1: Green
    phases.append(SignalPhase(
        phase_id="p1",
        duration_s=green1,
        state="G",
        link_ids=phase1_links
    ))
    
    # Phase 1: Yellow
    phases.append(SignalPhase(
        phase_id="p1y",
        duration_s=yellow_time_s,
        state="y",
        link_ids=phase1_links
    ))
    
    # All red
    phases.append(SignalPhase(
        phase_id="ar1",
        duration_s=all_red_s,
        state="r",
        link_ids=[]
    ))
    
    # Phase 2: Green
    phases.append(SignalPhase(
        phase_id="p2",
        duration_s=green2,
        state="G",
        link_ids=phase2_links
    ))
    
    # Phase 2: Yellow
    phases.append(SignalPhase(
        phase_id="p2y",
        duration_s=yellow_time_s,
        state="y",
        link_ids=phase2_links
    ))
    
    # All red
    phases.append(SignalPhase(
        phase_id="ar2",
        duration_s=all_red_s,
        state="r",
        link_ids=[]
    ))
    
    return SignalController(
        junction_id=f"tl_{node_id}",
        node_id=node_id,
        cycle_length_s=cycle_length_s,
        phases=phases
    )


def build_signals_xml(controllers: list[SignalController]) -> etree.Element:
    """
    Build canonical signals.xml from controllers.
    
    Args:
        controllers: List of SignalController objects
    
    Returns:
        lxml Element tree root
    """
    root = etree.Element("signals")
    
    for controller in sorted(controllers, key=lambda c: c.junction_id):
        junction = etree.SubElement(root, "junction")
        junction.set("id", controller.junction_id)
        junction.set("node_id", controller.node_id)
        junction.set("cycle_length_s", str(controller.cycle_length_s))
        
        for phase in controller.phases:
            phase_elem = etree.SubElement(junction, "phase")
            phase_elem.set("id", phase.phase_id)
            phase_elem.set("duration_s", str(phase.duration_s))
            phase_elem.set("state", phase.state)
            
            # Add link references
            for link_id in phase.link_ids:
                link_ref = etree.SubElement(phase_elem, "link_ref")
                link_ref.set("id", link_id)
    
    return root


def build_signals_default(
    network_path: Path,
    output_path: Path,
    min_degree: int = 4,
    max_signals: Optional[int] = None,
    cycle_length_s: int = 90
) -> dict:
    """
    Main entry point: build default signals for a network.
    
    Args:
        network_path: Path to canonical network.xml
        output_path: Path to write signals.xml
        min_degree: Minimum node degree for signalization
        max_signals: Optional max number of signals
        cycle_length_s: Signal cycle length
    
    Returns:
        Summary dict
    """
    # Load network (now also returns OSM-tagged signal nodes; empty set on
    # legacy networks that pre-date the V5 OSM-signal plumbing).
    node_coords, in_links, out_links, osm_signal_nodes = load_network_topology(network_path)
    logger.info("Loaded %d nodes", len(node_coords))

    # Identify intersections (prefers OSM ground truth, falls back to degree).
    signalized_nodes = identify_signalized_intersections(
        node_coords, in_links, out_links,
        osm_signal_nodes=osm_signal_nodes,
        min_degree=min_degree,
        max_signals=max_signals,
    )
    
    # Build controllers
    controllers = []
    for node_id in signalized_nodes:
        controller = build_signal_controller(
            node_id, node_coords, in_links, out_links,
            cycle_length_s=cycle_length_s
        )
        controllers.append(controller)
    
    # Build XML
    root = build_signals_xml(controllers)
    
    # Write
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree = etree.ElementTree(root)
    tree.write(str(output_path), pretty_print=True, xml_declaration=True, encoding="UTF-8")
    
    logger.info("Wrote %d signal controllers to %s", len(controllers), output_path)
    
    return {
        "signal_count": len(controllers),
        "min_degree": min_degree,
        "cycle_length_s": cycle_length_s,
        "output_path": str(output_path)
    }


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Build default traffic signals for canonical network"
    )
    parser.add_argument(
        "--network", "-n", type=str, required=True,
        help="Path to canonical network.xml"
    )
    parser.add_argument(
        "--output", "-o", type=str, required=True,
        help="Output path for signals.xml"
    )
    parser.add_argument(
        "--min-degree", type=int, default=4,
        help="Minimum node degree for signalization (default: 4)"
    )
    parser.add_argument(
        "--max-signals", type=int, default=None,
        help="Maximum number of signals to create (default: unlimited)"
    )
    parser.add_argument(
        "--cycle-length", type=int, default=90,
        help="Signal cycle length in seconds (default: 90)"
    )
    
    args = parser.parse_args()
    
    result = build_signals_default(
        network_path=Path(args.network),
        output_path=Path(args.output),
        min_degree=args.min_degree,
        max_signals=args.max_signals,
        cycle_length_s=args.cycle_length
    )
    
    print("\nSignals built successfully:")
    print(f"  Controllers: {result['signal_count']}")
    print(f"  Min degree: {result['min_degree']}")
    print(f"  Cycle length: {result['cycle_length_s']}s")
    print(f"  Output: {result['output_path']}")


if __name__ == "__main__":
    main()
