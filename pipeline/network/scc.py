"""
The largest strongly connected component, computed one way for everyone.

The demand generators (which should only emit trips between routable
endpoints) and the adapters (which check trips right before simulating)
have to agree on what "routable" means, and this module is where that
definition lives.

It's iterative Kosaraju. The recursive version blows Python's default
recursion limit on metro-scale OSM graphs (~10k nodes), so we use an
explicit stack. The result is a `set` of node IDs, which keeps the
membership tests in the demand and trip-filter inner loops at O(1).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set, Tuple
from xml.etree import ElementTree as ET


def parse_network(network_path: Path) -> Tuple[Set[str], List[Tuple[str, str]]]:
    """Parse canonical network.xml into (node_ids, directed_edges).

    Self-loops (from == to) are dropped because they cannot contribute to
    strong connectivity and break some downstream BFS routines.
    """
    network_path = Path(network_path)
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
    """The node IDs of the largest strongly connected component.

    Iterative Kosaraju: a forward DFS records finish times, then a DFS over
    the reverse graph in reverse-finish order peels off the SCCs one by one.
    Biggest one wins.
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


def largest_scc_from_network(network_path: Path) -> Tuple[Set[str], int, int, int]:
    """Parse a network.xml and return (scc_nodes, total_nodes, total_links, scc_links) in one call."""
    nodes, edges = parse_network(network_path)
    scc = compute_largest_scc(nodes, edges)
    scc_links = sum(1 for u, v in edges if u in scc and v in scc)
    return scc, len(nodes), len(edges), scc_links
