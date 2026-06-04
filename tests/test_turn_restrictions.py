"""
Unit tests for the V5 turn-restriction pipeline.

Coverage:
  - parse_turn_restrictions reads `<turn_restriction>` entries from network.xml
    and ignores incomplete/missing data.
  - build_forbidden_moves correctly compiles negative (`no_*`) and positive
    (`only_*`) restrictions into a forbidden-pairs lookup.
  - shortest_path_with_restrictions routes around forbidden movements while
    still finding a path when one exists, and returns None when restrictions
    leave the graph disconnected for that OD.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.network.turn_restrictions import (
    TurnRestriction,
    parse_turn_restrictions,
    build_forbidden_moves,
    shortest_path_with_restrictions,
)


# ---------------------------------------------------------------------------
# parse_turn_restrictions
# ---------------------------------------------------------------------------


class TestParseTurnRestrictions:
    def test_empty_when_no_block(self, tmp_path: Path):
        net = tmp_path / "network.xml"
        net.write_text(
            "<?xml version='1.0'?>\n"
            "<network><nodes/><links/></network>\n"
        )
        assert parse_turn_restrictions(net) == []

    def test_reads_full_entries(self, tmp_path: Path):
        net = tmp_path / "network.xml"
        net.write_text(
            "<?xml version='1.0'?>\n"
            "<network>\n"
            "  <nodes/>\n"
            "  <links/>\n"
            "  <turn_restrictions>\n"
            "    <turn_restriction type='no_left_turn' from_link='l1' "
            "via_node='n1' to_link='l2' osm_relation_id='42'/>\n"
            "    <turn_restriction type='only_straight_on' from_link='l3' "
            "via_node='n2' to_link='l4'/>\n"
            "  </turn_restrictions>\n"
            "</network>\n"
        )
        out = parse_turn_restrictions(net)
        assert len(out) == 2
        assert out[0] == TurnRestriction(
            restriction="no_left_turn", from_link="l1",
            via_node="n1", to_link="l2", osm_relation_id=42,
        )
        # The second entry has no relation id; should be None.
        assert out[1].osm_relation_id is None

    def test_skips_incomplete_entries(self, tmp_path: Path):
        net = tmp_path / "network.xml"
        net.write_text(
            "<?xml version='1.0'?>\n"
            "<network><nodes/><links/>\n"
            "<turn_restrictions>\n"
            "  <turn_restriction type='no_left_turn' from_link='l1'/>\n"
            "  <turn_restriction type='' from_link='l1' via_node='n1' to_link='l2'/>\n"
            "  <turn_restriction type='no_left_turn' from_link='l1' via_node='n1' to_link='l2'/>\n"
            "</turn_restrictions>\n"
            "</network>\n"
        )
        out = parse_turn_restrictions(net)
        assert len(out) == 1  # only the well-formed one
        assert out[0].from_link == "l1"

    def test_returns_empty_on_malformed_xml(self, tmp_path: Path):
        # parse error → return []; we don't crash the signal/feasibility
        # pipeline because someone's network.xml is malformed.
        net = tmp_path / "broken.xml"
        net.write_text("not valid xml")
        assert parse_turn_restrictions(net) == []


# ---------------------------------------------------------------------------
# build_forbidden_moves
# ---------------------------------------------------------------------------


class TestBuildForbiddenMoves:
    def test_negative_no_left_forbids_one_pair(self):
        rs = [TurnRestriction("no_left_turn", "l1", "n1", "l2")]
        forbidden = build_forbidden_moves(rs, outgoing_links_by_node={"n1": ["l2", "l3"]})
        assert forbidden == {("n1", "l1"): frozenset({"l2"})}

    def test_positive_only_left_forbids_every_other_exit(self):
        # only_left_turn from l1 at n1 means only l2 allowed; forbid l3, l4.
        rs = [TurnRestriction("only_left_turn", "l1", "n1", "l2")]
        forbidden = build_forbidden_moves(
            rs, outgoing_links_by_node={"n1": ["l2", "l3", "l4"]},
        )
        assert forbidden == {("n1", "l1"): frozenset({"l3", "l4"})}

    def test_unknown_restriction_is_ignored(self):
        rs = [TurnRestriction("not_a_real_thing", "l1", "n1", "l2")]
        assert build_forbidden_moves(rs, outgoing_links_by_node={"n1": ["l2"]}) == {}

    def test_multiple_restrictions_at_same_node_merge(self):
        rs = [
            TurnRestriction("no_left_turn", "l1", "n1", "l2"),
            TurnRestriction("no_u_turn", "l1", "n1", "l3"),
        ]
        forbidden = build_forbidden_moves(rs, outgoing_links_by_node={"n1": ["l2", "l3", "l4"]})
        assert forbidden == {("n1", "l1"): frozenset({"l2", "l3"})}


# ---------------------------------------------------------------------------
# shortest_path_with_restrictions
# ---------------------------------------------------------------------------


class _Edge:
    """Minimal stand-in for adapters.sumo.sumo_adapter.CanonicalLink so we
    don't need to import the full adapter module just to test the BFS."""
    def __init__(self, link_id: str):
        self.id = link_id


class TestShortestPathWithRestrictions:
    """Toy network::

           l1                 l2
        n1 ───▶ n2 ─────────▶ n3
                │              │
                │ l3        l4 │
                ▼              ▼
                n4 ──────────▶ n5
                       l5

    Two paths from n1 to n5:
      A) n1 -l1→ n2 -l3→ n4 -l5→ n5
      B) n1 -l1→ n2 -l2→ n3 -l4→ n5

    With "no_left_turn" forbidding l1→l3 at n2, path B is the only option.
    With "no_left_turn" forbidding l1→l3 at n2 *and* l1→l2 at n2, no path.
    """

    @staticmethod
    def _setup():
        adjacency = {
            "n1": ["n2"], "n2": ["n3", "n4"],
            "n3": ["n5"], "n4": ["n5"], "n5": [],
        }
        edge_lookup = {
            ("n1", "n2"): _Edge("l1"),
            ("n2", "n3"): _Edge("l2"),
            ("n2", "n4"): _Edge("l3"),
            ("n3", "n5"): _Edge("l4"),
            ("n4", "n5"): _Edge("l5"),
        }
        return adjacency, edge_lookup

    def test_no_restrictions_returns_shortest(self):
        adjacency, edge_lookup = self._setup()
        path = shortest_path_with_restrictions(
            origin="n1", dest="n5",
            adjacency=adjacency, edge_lookup=edge_lookup,
            forbidden_moves={},
        )
        # BFS expands neighbors in adjacency order; first to reach n5 wins.
        assert path is not None and path[0] == "n1" and path[-1] == "n5"
        assert len(path) == 4  # 3 hops, either route

    def test_routes_around_forbidden_movement(self):
        # Forbid l1→l3 at n2 (the "left turn" onto n2→n4). Should pick
        # the n2 -l2→ n3 -l4→ n5 path.
        adjacency, edge_lookup = self._setup()
        path = shortest_path_with_restrictions(
            origin="n1", dest="n5",
            adjacency=adjacency, edge_lookup=edge_lookup,
            forbidden_moves={("n2", "l1"): frozenset({"l3"})},
        )
        assert path == ["n1", "n2", "n3", "n5"]

    def test_returns_none_when_all_paths_blocked(self):
        adjacency, edge_lookup = self._setup()
        path = shortest_path_with_restrictions(
            origin="n1", dest="n5",
            adjacency=adjacency, edge_lookup=edge_lookup,
            forbidden_moves={
                ("n2", "l1"): frozenset({"l2", "l3"}),
            },
        )
        assert path is None

    def test_origin_equals_dest(self):
        adjacency, edge_lookup = self._setup()
        path = shortest_path_with_restrictions(
            origin="n1", dest="n1",
            adjacency=adjacency, edge_lookup=edge_lookup,
            forbidden_moves={},
        )
        assert path == ["n1"]


# ---------------------------------------------------------------------------
# End-to-end on a real bundled scenario (when present)
# ---------------------------------------------------------------------------


class TestRealBundle:
    """The bundled scenarios may or may not have been regenerated under the
    V5 turn-restriction pipeline yet. If none exist, skip cleanly.
    """

    def test_real_network_loads_without_error(self, bundled_scenario):
        # Don't assert on count, if the bundle pre-dates V5 turn restrictions
        # the result is just an empty list, which is fine.
        out = parse_turn_restrictions(bundled_scenario / "network.xml")
        assert isinstance(out, list)


# ---------------------------------------------------------------------------
# DTALite movement.csv emission (V5+)
# ---------------------------------------------------------------------------


class TestDTALiteMovementCSV:
    """Verify the DTALite GMNS movement.csv writer faithfully translates
    canonical turn restrictions. path4gmns 0.10.0 doesn't ingest this file
    natively, but emitting it preserves OSM ground truth for downstream
    audit + future engine support.
    """

    def _network_with_restrictions(self, tmp_path: Path):
        net = tmp_path / "network.xml"
        net.write_text(
            "<?xml version='1.0'?>\n"
            "<network>\n"
            "  <nodes><node id='n1' x='0' y='0'/></nodes>\n"
            "  <links/>\n"
            "  <turn_restrictions>\n"
            "    <turn_restriction type='no_left_turn' "
            "from_link='l1' via_node='n1' to_link='l2' osm_relation_id='42'/>\n"
            "    <turn_restriction type='only_straight_on' "
            "from_link='l3' via_node='n1' to_link='l4'/>\n"
            "  </turn_restrictions>\n"
            "</network>\n"
        )
        return net

    def test_emits_one_row_per_restriction(self, tmp_path: Path):
        from adapters.dtalite.dtalite_adapter import write_dtalite_movement_csv
        net = self._network_with_restrictions(tmp_path)
        out = tmp_path / "movement.csv"
        rows = write_dtalite_movement_csv(net, out)
        assert rows == 2
        assert out.is_file()
        content = out.read_text().strip().split("\n")
        # Header + 2 rows
        assert len(content) == 3
        # Header columns include GMNS-required + osm_restriction provenance
        header = content[0].split(",")
        for required in ("mvmt_id", "node_id", "ib_link_id",
                         "ob_link_id", "type", "penalty", "capacity"):
            assert required in header
        assert "osm_restriction" in header

    def test_capacity_zero_marks_forbidden(self, tmp_path: Path):
        from adapters.dtalite.dtalite_adapter import write_dtalite_movement_csv
        net = self._network_with_restrictions(tmp_path)
        out = tmp_path / "movement.csv"
        write_dtalite_movement_csv(net, out)
        # Every emitted row must have capacity=0 (= forbidden under GMNS)
        # so that any GMNS-aware loader can interpret the restriction
        # without parsing the OSM-specific provenance column.
        for line in out.read_text().strip().split("\n")[1:]:
            cells = line.split(",")
            cap_idx = out.read_text().strip().split("\n")[0].split(",").index("capacity")
            assert cells[cap_idx] == "0"

    def test_no_file_when_no_restrictions(self, tmp_path: Path):
        from adapters.dtalite.dtalite_adapter import write_dtalite_movement_csv
        net = tmp_path / "network.xml"
        net.write_text(
            "<?xml version='1.0'?>\n"
            "<network><nodes/><links/></network>\n"
        )
        out = tmp_path / "movement.csv"
        rows = write_dtalite_movement_csv(net, out)
        assert rows == 0
        # Don't emit empty file; absence is unambiguous.
        assert not out.exists()

    def test_osm_to_gmns_type_mapping(self, tmp_path: Path):
        """Negative restrictions translate directly; positive `only_*`
        restrictions also map to the named direction (the named direction
        is the *allowed* one, DTALite's penalty/capacity is the same
        no-go signal regardless)."""
        from adapters.dtalite.dtalite_adapter import write_dtalite_movement_csv
        net = self._network_with_restrictions(tmp_path)
        out = tmp_path / "movement.csv"
        write_dtalite_movement_csv(net, out)
        rows = out.read_text().strip().split("\n")[1:]
        # First row is the no_left_turn (sorted by via_node='n1', from_link='l1')
        cells = rows[0].split(",")
        # Find the type column dynamically
        header = out.read_text().strip().split("\n")[0].split(",")
        type_col = header.index("type")
        assert cells[type_col] == "left"
