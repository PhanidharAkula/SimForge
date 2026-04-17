"""
Build default traffic signals for a canonical network.

Identifies intersection nodes with high connectivity and generates
simple 2-phase signal controllers.

Usage:
    python -m pipeline.signals.build_signals_default \
        --network scenarios/city1/network.xml \
        --output scenarios/city1/signals.xml \
        --min-degree 4
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


def load_network_topology(network_path: Path) -> tuple[dict, dict, dict]:
    """
    Load network and compute node degrees and connected links.
    
    Returns:
        Tuple of:
        - node_coords: {node_id: (x, y)}
        - in_links: {node_id: [link_ids entering]}
        - out_links: {node_id: [link_ids leaving]}
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
    
    # Parse nodes
    for node in root.findall(".//node"):
        nid = node.get("id")
        x = float(node.get("x", 0))
        y = float(node.get("y", 0))
        node_coords[nid] = (x, y)
    
    # Parse links
    for link in root.findall(".//link"):
        lid = link.get("id")
        from_node = link.get("from")
        to_node = link.get("to")
        
        if from_node and to_node:
            out_links[from_node].append(lid)
            in_links[to_node].append(lid)
    
    return node_coords, dict(in_links), dict(out_links)


def identify_signalized_intersections(
    node_coords: dict,
    in_links: dict,
    out_links: dict,
    min_degree: int = 4,
    max_signals: Optional[int] = None
) -> list[str]:
    """
    Identify nodes that should have traffic signals.
    
    Criteria:
    - Node has at least min_degree incoming + outgoing links
    - Optionally limit to top N by degree
    
    Args:
        node_coords: Node coordinate mapping
        in_links: Incoming links per node
        out_links: Outgoing links per node
        min_degree: Minimum total degree for signalization
        max_signals: Optional maximum number of signals
    
    Returns:
        List of node IDs to signalize
    """
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
    
    logger.info(f"Identified {len(signalized)} nodes for signalization")
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
    import math
    
    node_x, node_y = node_coords[node_id]
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
    # Load network
    node_coords, in_links, out_links = load_network_topology(network_path)
    logger.info(f"Loaded {len(node_coords)} nodes")
    
    # Identify intersections
    signalized_nodes = identify_signalized_intersections(
        node_coords, in_links, out_links,
        min_degree=min_degree,
        max_signals=max_signals
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
    
    logger.info(f"Wrote {len(controllers)} signal controllers to {output_path}")
    
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
    
    print(f"\nSignals built successfully:")
    print(f"  Controllers: {result['signal_count']}")
    print(f"  Min degree: {result['min_degree']}")
    print(f"  Cycle length: {result['cycle_length_s']}s")
    print(f"  Output: {result['output_path']}")


if __name__ == "__main__":
    main()
