"""
Tests for pipeline/network/scc.py — the canonical largest-SCC computation.

Both demand generators and adapter feasibility filters delegate to this
module. A regression here silently corrupts every cross-engine run, so the
algorithm itself is exercised against synthetic graphs with hand-checked
answers as well as against the bundled real network.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pipeline.network.scc import (
    compute_largest_scc,
    largest_scc_from_network,
    parse_network,
)


# ---------------------------------------------------------------------------
# Pure-algorithm tests — no I/O
# ---------------------------------------------------------------------------


class TestComputeLargestSCC:
    def test_empty_graph(self):
        assert compute_largest_scc(set(), []) == set()

    def test_single_node_no_edges(self):
        # A lone node is trivially its own SCC of size 1.
        assert compute_largest_scc({"a"}, []) == {"a"}

    def test_two_node_cycle(self):
        # a ⇄ b → both nodes form one SCC.
        assert compute_largest_scc({"a", "b"}, [("a", "b"), ("b", "a")]) == {"a", "b"}

    def test_directed_chain_no_cycle(self):
        # a → b → c with no return: each node is its own SCC; the largest is size 1.
        scc = compute_largest_scc({"a", "b", "c"}, [("a", "b"), ("b", "c")])
        assert len(scc) == 1

    def test_picks_largest_when_multiple_components(self):
        # Big cycle a→b→c→a + small isolated cycle d⇄e.
        nodes = {"a", "b", "c", "d", "e"}
        edges = [("a", "b"), ("b", "c"), ("c", "a"), ("d", "e"), ("e", "d")]
        assert compute_largest_scc(nodes, edges) == {"a", "b", "c"}

    def test_classic_kosaraju_example(self):
        # Cormen-style graph: SCCs = {1,2,3}, {4,5}, {6,7,8}.
        nodes = {"1", "2", "3", "4", "5", "6", "7", "8"}
        edges = [
            ("1", "2"), ("2", "3"), ("3", "1"),  # SCC #1
            ("4", "5"), ("5", "4"),               # SCC #2
            ("6", "7"), ("7", "8"), ("8", "6"),   # SCC #3
            ("3", "4"), ("5", "6"),               # cross edges between SCCs
        ]
        scc = compute_largest_scc(nodes, edges)
        assert len(scc) == 3
        # Either of the size-3 SCCs is a valid winner; Kosaraju is deterministic
        # for a given iteration order, but we don't lock the algorithm to one.
        assert scc in ({"1", "2", "3"}, {"6", "7", "8"})

    def test_self_loop_is_not_required_for_singleton(self):
        # parse_network drops self-loops; compute_largest_scc should still
        # treat a node with no edges as a singleton SCC.
        assert compute_largest_scc({"x"}, []) == {"x"}

    def test_iterative_handles_deep_chain(self):
        """Deep chain (5 000 nodes) — the recursive form would blow the stack."""
        n = 5000
        nodes = {f"n{i}" for i in range(n)}
        edges = [(f"n{i}", f"n{i+1}") for i in range(n - 1)]
        edges.append((f"n{n-1}", "n0"))  # close the cycle so all nodes are in one SCC
        scc = compute_largest_scc(nodes, edges)
        assert len(scc) == n


# ---------------------------------------------------------------------------
# Network parsing
# ---------------------------------------------------------------------------


class TestParseNetwork:
    def _write_network(self, tmp_path: Path, body: str) -> Path:
        path = tmp_path / "network.xml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_parses_minimal_network(self, tmp_path):
        body = """<?xml version="1.0"?>
<network>
  <nodes>
    <node id="a" x="0" y="0" />
    <node id="b" x="1" y="1" />
  </nodes>
  <links>
    <link id="L1" from="a" to="b" />
  </links>
</network>
"""
        nodes, edges = parse_network(self._write_network(tmp_path, body))
        assert nodes == {"a", "b"}
        assert edges == [("a", "b")]

    def test_drops_self_loops(self, tmp_path):
        body = """<?xml version="1.0"?>
<network>
  <nodes><node id="a" /><node id="b" /></nodes>
  <links>
    <link id="L1" from="a" to="b" />
    <link id="L2" from="a" to="a" />
  </links>
</network>
"""
        _, edges = parse_network(self._write_network(tmp_path, body))
        assert ("a", "a") not in edges
        assert edges == [("a", "b")]

    def test_rejects_non_network_root(self, tmp_path):
        body = "<other><nodes/></other>"
        with pytest.raises(ValueError, match="must be <network>"):
            parse_network(self._write_network(tmp_path, body))

    def test_rejects_malformed_xml(self, tmp_path):
        path = tmp_path / "broken.xml"
        path.write_text("<<not xml>>", encoding="utf-8")
        with pytest.raises(ValueError, match="Failed to parse"):
            parse_network(path)


# ---------------------------------------------------------------------------
# Real bundled network
# ---------------------------------------------------------------------------


class TestRealBundledNetwork:
    def test_scc_covers_almost_every_node(self, bundled_scenario):
        """For a clean OSM extract, SCC should cover ≥95 % of nodes."""
        scc, total_nodes, total_links, scc_links = largest_scc_from_network(
            bundled_scenario / "network.xml"
        )
        assert len(scc) > 0
        coverage = len(scc) / total_nodes
        assert coverage >= 0.95, (
            f"{bundled_scenario.name}: SCC covers only {coverage:.1%} of nodes"
        )
        assert scc_links > 0
        assert scc_links <= total_links

    def test_scc_membership_is_consistent(self, bundled_scenario):
        """Two runs against the same network must return the same set."""
        scc_a, *_ = largest_scc_from_network(bundled_scenario / "network.xml")
        scc_b, *_ = largest_scc_from_network(bundled_scenario / "network.xml")
        assert scc_a == scc_b
