"""
Turn restrictions for the canonical network.

Reads the `<turn_restriction>` elements from `network.xml` (V5+ schema) and
gives a state-aware BFS that obeys them. The SUMO and MATSim adapters use
it to route trips around movements that aren't physically legal: no-left at
a protected intersection, no-U-turn on a divided highway, and so on.

Who enforces them (V5+):
    - SUMO: enforced. The state-aware BFS stands in for plain BFS at
      `adapters/sumo/sumo_adapter.py:build_sumo_routes_xml`, so the route
      already respects the restrictions and SUMO just drives it.
    - MATSim: enforced. Same BFS pre-routes the plan, and the MATSim adapter
      writes `<route type="links">...</route>` inside each `<leg>` so MATSim
      follows that path rather than routing for itself.
    - DTALite: not actively enforced. We write a GMNS-conformant
      `movement.csv` alongside DTALite's other inputs, but path4gmns 0.10.0
      (the DTA library we run through) doesn't read movement.csv yet, so
      DTALite's UE assignment can still route through a forbidden movement.
      This is the one cross-engine asymmetry V5 leaves open;
      doc/MODELGEN_AND_MODES.md ("Cross-engine asymmetry") and CHANGELOG
      Phase 7 cover the why and the future-work plan.

OSM restriction types we accept:
    no_left_turn, no_right_turn, no_u_turn, no_straight_on,
    only_left_turn, only_right_turn, only_straight_on

The `only_*` ones work backwards: with `only_left_turn` from some
`from_link`, every movement off that `from_link` that isn't the left turn
becomes forbidden. We expand those into forbidden-pair sets when we load
them.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set, Tuple
from xml.etree import ElementTree as ET


_NEGATIVE_RESTRICTIONS = frozenset({
    "no_left_turn",
    "no_right_turn",
    "no_u_turn",
    "no_straight_on",
})

_POSITIVE_RESTRICTIONS = frozenset({
    "only_left_turn",
    "only_right_turn",
    "only_straight_on",
})


@dataclass(frozen=True)
class TurnRestriction:
    """A canonical turn restriction parsed from network.xml."""
    restriction: str  # one of the OSM restriction tag values
    from_link: str
    via_node: str
    to_link: str
    osm_relation_id: Optional[int] = None


def parse_turn_restrictions(network_path: Path) -> List[TurnRestriction]:
    """Read all `<turn_restriction>` entries from a canonical network.xml.

    Returns an empty list if the network was generated before V5 (no
    `<turn_restrictions>` block) or carries no restrictions.
    """
    network_path = Path(network_path)
    try:
        root = ET.parse(str(network_path)).getroot()
    except ET.ParseError:
        return []
    out: List[TurnRestriction] = []
    block = root.find("turn_restrictions")
    if block is None:
        return out
    for r in block.findall("turn_restriction"):
        rtype = r.get("type") or ""
        from_link = r.get("from_link") or ""
        via_node = r.get("via_node") or ""
        to_link = r.get("to_link") or ""
        if not (rtype and from_link and via_node and to_link):
            continue
        rel_id_raw = r.get("osm_relation_id")
        rel_id: Optional[int]
        try:
            rel_id = int(rel_id_raw) if rel_id_raw else None
        except ValueError:
            rel_id = None
        out.append(TurnRestriction(
            restriction=rtype,
            from_link=from_link,
            via_node=via_node,
            to_link=to_link,
            osm_relation_id=rel_id,
        ))
    return out


def build_forbidden_moves(
    restrictions: List[TurnRestriction],
    outgoing_links_by_node: Dict[str, List[str]],
) -> Dict[Tuple[str, str], FrozenSet[str]]:
    """Turn a list of TurnRestrictions into a fast forbidden-moves lookup.

    Returns ``(via_node, from_link) -> frozenset[to_link]``: the to_links you
    can't take when you reach ``via_node`` along ``from_link``.

    A `no_*_turn` just forbids its named (from, to) pair. An `only_*_turn`
    forbids every other exit at the via_node, since the named one is the only
    allowed move. Expanding `only_*` needs the full set of outgoing links at
    the via_node, which the caller passes in as ``outgoing_links_by_node``.
    """
    forbidden: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    for r in restrictions:
        key = (r.via_node, r.from_link)
        if r.restriction in _NEGATIVE_RESTRICTIONS:
            forbidden[key].add(r.to_link)
        elif r.restriction in _POSITIVE_RESTRICTIONS:
            allowed_to = r.to_link
            for other_to in outgoing_links_by_node.get(r.via_node, []):
                if other_to != allowed_to:
                    forbidden[key].add(other_to)
        # Other restriction values (rare / non-standard) are silently ignored.
    return {k: frozenset(v) for k, v in forbidden.items()}


def shortest_path_with_restrictions(
    *,
    origin: str,
    dest: str,
    adjacency: Dict[str, List[str]],
    edge_lookup: Dict[Tuple[str, str], object],
    forbidden_moves: Dict[Tuple[str, str], FrozenSet[str]],
) -> Optional[List[str]]:
    """State-aware BFS that obeys the turn restrictions.

    The state is ``(node, last_link_id)``. At each state we keep only the
    outgoing links that aren't in
    ``forbidden_moves[(node, last_link_id)]``. The start state has no last
    link, so its first moves are unrestricted.

    ``edge_lookup`` is the ``(from_node, to_node) -> link`` map from
    ``parse_canonical_network()``; we read ``link.id`` off each entry for the
    state's last_link_id.

    Returns the node ids from origin to dest inclusive, or None if dest can't
    be reached under the restrictions.
    """
    if origin == dest:
        return [origin]

    # State = (node, last_link_id_or_None)
    initial = (origin, None)
    visited: Set[Tuple[str, Optional[str]]] = {initial}
    parent: Dict[Tuple[str, Optional[str]], Tuple[Tuple[str, Optional[str]], str]] = {}
    queue: deque = deque([initial])

    while queue:
        node, last_link = queue.popleft()
        for nxt in adjacency.get(node, []):
            link = edge_lookup.get((node, nxt))
            if link is None:
                continue
            link_id = getattr(link, "id", None)
            if link_id is None:
                continue
            if last_link is not None:
                forbidden = forbidden_moves.get((node, last_link))
                if forbidden and link_id in forbidden:
                    continue
            state = (nxt, link_id)
            if state in visited:
                continue
            visited.add(state)
            parent[state] = ((node, last_link), nxt)
            if nxt == dest:
                # Walk back to origin to reconstruct the path.
                path: List[str] = [nxt]
                cur_state: Optional[Tuple[str, Optional[str]]] = state
                while cur_state in parent:
                    prev_state, _ = parent[cur_state]
                    path.append(prev_state[0])
                    cur_state = prev_state if prev_state != initial else None
                path.reverse()
                return path
            queue.append(state)
    return None
