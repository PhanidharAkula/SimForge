"""
Determinism tests — running the SUMO adapter twice on the same scenario
must produce byte-identical outputs (modulo netconvert's embedded timestamp).

Cross-run divergence is what makes "reproducible benchmark" a lie, so these
tests are the canary for hash-randomised dict order, floating-point summation
order, and timestamps leaking into XML attributes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.sumo.sumo_adapter import prepare_sumo_inputs

from .conftest import directory_sha256, file_sha256


pytestmark = pytest.mark.determinism


class TestSUMOAdapterDeterminism:
    """Two runs of `prepare_sumo_inputs` must agree byte-for-byte."""

    def _run_twice(self, scenario: Path, tmp_path: Path) -> tuple[Path, Path]:
        run1 = tmp_path / "run1"
        run2 = tmp_path / "run2"
        run1.mkdir()
        run2.mkdir()
        assert prepare_sumo_inputs(scenario, run1) is not None
        assert prepare_sumo_inputs(scenario, run2) is not None
        return run1, run2

    def test_full_output_tree_is_identical(self, bundled_scenario, tmp_path):
        run1, run2 = self._run_twice(bundled_scenario, tmp_path)
        # net.net.xml has a netconvert timestamp; everything else must match.
        h1 = directory_sha256(run1, exclude_patterns=["net.net.xml"])
        h2 = directory_sha256(run2, exclude_patterns=["net.net.xml"])
        assert set(h1) == set(h2), (
            f"Different files generated:\nrun1={sorted(h1)}\nrun2={sorted(h2)}"
        )
        for name in h1:
            assert h1[name] == h2[name], f"{name} differs across runs"

    def test_routes_file_is_deterministic(self, bundled_scenario, tmp_path):
        run1, run2 = self._run_twice(bundled_scenario, tmp_path)
        assert file_sha256(run1 / "routes.rou.xml") == file_sha256(run2 / "routes.rou.xml")

    def test_nodes_file_is_deterministic(self, bundled_scenario, tmp_path):
        run1, run2 = self._run_twice(bundled_scenario, tmp_path)
        assert file_sha256(run1 / "nodes.nod.xml") == file_sha256(run2 / "nodes.nod.xml")

    def test_edges_file_is_deterministic(self, bundled_scenario, tmp_path):
        run1, run2 = self._run_twice(bundled_scenario, tmp_path)
        assert file_sha256(run1 / "edges.edg.xml") == file_sha256(run2 / "edges.edg.xml")

    def test_config_file_is_deterministic(self, bundled_scenario, tmp_path):
        run1, run2 = self._run_twice(bundled_scenario, tmp_path)
        assert file_sha256(run1 / "toy.sumocfg") == file_sha256(run2 / "toy.sumocfg")


class TestHashUtilities:
    """Sanity checks for the SHA-256 helpers in conftest."""

    def test_same_content_same_hash(self, tmp_path):
        f = tmp_path / "x.txt"
        f.write_text("hello world")
        assert file_sha256(f) == file_sha256(f)
        assert len(file_sha256(f)) == 64

    def test_different_content_different_hash(self, tmp_path):
        a, b = tmp_path / "a.txt", tmp_path / "b.txt"
        a.write_text("hello")
        b.write_text("world")
        assert file_sha256(a) != file_sha256(b)

    def test_directory_excludes_match_pattern(self, tmp_path):
        (tmp_path / "keep.txt").write_text("k")
        (tmp_path / "skip.log").write_text("s")
        h = directory_sha256(tmp_path, exclude_patterns=[".log"])
        assert "keep.txt" in h
        assert "skip.log" not in h
