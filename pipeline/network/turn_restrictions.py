"""
Turn-restriction utilities for the canonical network.

Reads `<turn_restriction>` elements out of `network.xml` (V5+ schema) and
provides a state-aware BFS that respects them. The SUMO and MATSim
adapters use this to pre-route trips around physically illegal
movements (no-left-turn at protected intersections, no-U-turn on
divided highways, etc.).

Cross-engine enforcement state (V5+):
    - SUMO: ENFORCED. State-aware BFS replaces plain BFS at
      `adapters/sumo/sumo_adapter.py:build_sumo_routes_xml` — the
      prescribed route is restriction-respecting and SUMO drives it
      verbatim.
    - MATSim: ENFORCED. Same state-aware BFS pre-routes the plan; the
      MATSim adapter writes `<route type="links">…</route>` inside
      each `<leg>` so MATSim follows the prescribed path instead of
      routing internally.
    - DTALite: NOT ACTIVELY ENFORCED. SimForge emits a GMNS-conformant
      `movement.csv` next to DTALite's other inputs, but path4gmns
      0.10.0 (the DTA library SimForge runs through) doesn't ingest
      movement.csv natively yet. DTALite's UE assignment may
      therefore route through forbidden movements. This is the one
      cross-engine asymmetry V5 leaves open. See
      doc/MODELGEN_AND_MODES.md §"Cross-engine asymmetry" and
      CHANGELOG Phase 7 for the rationale and future-work plan.

OSM restriction types accepted:
    no_left_turn, no_right_turn, no_u_turn, no_straight_on,
    only_left_turn, only_right_turn, only_straight_on

`only_*` restrictions invert: at a junction with `only_left_turn` from
some `from_link`, every NON-left-turn movement from that `from_link`
becomes forbidden. We expand them to forbidden-pair sets at load time.
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
    """Compile a list of TurnRestrictions into a fast-lookup forbidden-moves table.

    Returns a mapping ``(via_node, from_link) -> frozenset[to_link]`` where
    each entry lists the to_links that are forbidden when arriving at
    ``via_node`` from ``from_link``.

    Negative restrictions (`no_*_turn`) directly forbid the named (from, to)
    pair. Positive restrictions (`only_*_turn`) forbid every OTHER outgoing
    link at the via_node — i.e. the only allowed exit is the one named.
    Expanding `only_*` requires knowing all outgoing links at the via_node,
    which the caller must supply via ``outgoing_links_by_node``.
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
    """State-aware BFS that respects turn restrictions.

    State is ``(node, last_link_id)``. From each state, neighbors are
    filtered to outgoing links not in ``forbidden_moves[(node, last_link_id)]``.
    The initial state has no last link; its expansions are unrestricted.

    ``edge_lookup`` is the ``(from_node, to_node) -> link`` map from
    ``parse_canonical_network()``. We use ``link.id`` from each entry as
    the state's last_link_id.

    Returns a list of node ids from origin to dest (inclusive), or None if
    unreachable under the restrictions.
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
