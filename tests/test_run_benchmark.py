"""Targeted tests for execution.run_benchmark.BenchmarkHarness.

The harness has historically had three foot-guns that bit hard in
production (see CHANGELOG Phase 12):

  1. ``--output`` CLI overrides were silently clobbered by the runspec's
     ``output_dir:`` inside ``run_benchmark()`` — every parallel-by-scenario
     sbatch worker collapsed to the runspec's single output base, so the
     three workers' aggregate JSONs raced and last-writer-wins.

  2. The per-cell directory was ``<base>/<scenario>/<engine>/seed_<N>/``
     (no mode segment), so SUMO meso and SUMO micro for the same seed
     wrote to the same dir and overwrote each other's tripinfo.xml +
     feasibility_report.json.

  3. ``prepare_<engine>_inputs`` ran per-cell, so the dominant per-trip
     BFS-routing cost was repeated N×reps times even though the routes
     are deterministic given (scenario, engine). la_50k_car had ~10 h
     of BFS per cell × 15 cells = 150 h, busting any reasonable walltime.

These tests pin all three so the regressions don't slip back.
"""

from __future__ import annotations

import os
from pathlib import Path

from execution.run_benchmark import BenchmarkHarness


# ---------------------------------------------------------------------------
# Bug 1: ``--output`` CLI override survives the run_benchmark() entry point.
# ---------------------------------------------------------------------------


class TestExplicitOutputBase:
    def test_default_constructor_marks_output_as_implicit(self, tmp_path: Path):
        """Without an explicit output_base, run_benchmark() may use runspec's value."""
        h = BenchmarkHarness()
        assert h._explicit_output is False
        assert h.output_base == Path("runs")

    def test_explicit_constructor_marks_output_as_explicit(self, tmp_path: Path):
        """An output_base passed to __init__ must NOT be clobbered by run_benchmark()."""
        h = BenchmarkHarness(output_base=tmp_path / "myrun")
        assert h._explicit_output is True
        assert h.output_base == tmp_path / "myrun"
        assert (tmp_path / "myrun").is_dir()

    def test_none_output_falls_back_to_default(self, tmp_path: Path):
        """Explicit ``None`` is the same as omitting the arg — default + implicit."""
        h = BenchmarkHarness(output_base=None)
        assert h._explicit_output is False
        assert h.output_base == Path("runs")


# ---------------------------------------------------------------------------
# Bug 2 (per-cell mode-segmented path) is exercised end-to-end by the
# audit_fairness layout tests in tests/test_audit_fairness.py
# (TestFindCellDir.test_layout_b_phase12_*) — those tests assert that the
# new on-disk layout matches the path that `run_benchmark.py` now writes.
# Keeping that assertion in audit_fairness's test file lets a regression
# in either direction fail loudly.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Bug 3: BFS-prep caching — prepare runs once per (scenario, engine);
# per-cell run dirs receive hardlinks; MATSim's seed-dependent config.xml
# is rewritten per cell.
# ---------------------------------------------------------------------------


class TestPreparedCache:
    def _write_bundle(self, bundle_dir: Path, manifest_text: str = "v1") -> str:
        """Write a synthetic manifest.xml and return its expected SHA-256."""
        bundle_dir.mkdir(parents=True, exist_ok=True)
        (bundle_dir / "manifest.xml").write_text(manifest_text)
        import hashlib
        return hashlib.sha256(manifest_text.encode()).hexdigest()

    def test_warm_cache_skips_prepare(self, tmp_path: Path, monkeypatch):
        """Cache hit when .prepared content matches the bundle's manifest hash."""
        bundle = tmp_path / "scenarios" / "chicago_1k_car"
        bundle_hash = self._write_bundle(bundle)

        h = BenchmarkHarness(output_base=tmp_path)
        cache = tmp_path / ".cache" / "chicago_1k_car" / "sumo"
        cache.mkdir(parents=True)
        (cache / ".prepared").write_text(bundle_hash)

        called = []
        monkeypatch.setattr(
            h, "prepare_sumo_inputs",
            lambda *a, **kw: called.append((a, kw)),
        )
        result = h._ensure_prepared_cache(
            scenario_path=bundle,
            scenario_id="chicago_1k_car",
            engine="sumo",
            engine_options=None,
        )
        assert result == cache
        assert called == []

    def test_cold_cache_calls_prepare_and_marks_sentinel(
        self, tmp_path: Path, monkeypatch,
    ):
        """A cold cache invokes prepare and writes the sentinel with hash."""
        bundle = tmp_path / "scenarios" / "chicago_1k_car"
        bundle_hash = self._write_bundle(bundle)

        h = BenchmarkHarness(output_base=tmp_path)
        called = []

        def fake_prepare(scenario_path, output_dir, seed=0):
            called.append(output_dir)
            (output_dir / "toy.sumocfg").write_text("<dummy/>")
            (output_dir / "tripinfo.xml").write_text("<dummy/>")

        monkeypatch.setattr(h, "prepare_sumo_inputs", fake_prepare)

        cache = h._ensure_prepared_cache(
            scenario_path=bundle,
            scenario_id="chicago_1k_car",
            engine="sumo",
            engine_options=None,
        )
        assert len(called) == 1
        assert (cache / ".prepared").read_text() == bundle_hash
        assert (cache / "toy.sumocfg").is_file()

        # Second call: warm hit, no re-invocation.
        h._ensure_prepared_cache(
            scenario_path=bundle,
            scenario_id="chicago_1k_car",
            engine="sumo",
            engine_options=None,
        )
        assert len(called) == 1

    def test_cache_invalidates_when_bundle_changes(
        self, tmp_path: Path, monkeypatch,
    ):
        """Regenerating the bundle (different manifest) triggers cache rebuild."""
        bundle = tmp_path / "scenarios" / "chicago_1k_car"
        self._write_bundle(bundle, manifest_text="v1")

        h = BenchmarkHarness(output_base=tmp_path)
        called = []

        def fake_prepare(scenario_path, output_dir, seed=0):
            called.append(output_dir)
            (output_dir / "toy.sumocfg").write_text("<dummy/>")

        monkeypatch.setattr(h, "prepare_sumo_inputs", fake_prepare)

        # Cold prep with v1 bundle.
        h._ensure_prepared_cache(
            scenario_path=bundle, scenario_id="chicago_1k_car",
            engine="sumo", engine_options=None,
        )
        assert len(called) == 1

        # Bundle "regenerated" — manifest hash changes.
        new_hash = self._write_bundle(bundle, manifest_text="v2-different-content")
        h._ensure_prepared_cache(
            scenario_path=bundle, scenario_id="chicago_1k_car",
            engine="sumo", engine_options=None,
        )
        assert len(called) == 2, (
            "cache should have rebuilt because bundle's manifest.xml changed"
        )
        # Sentinel now reflects the new hash.
        cache = tmp_path / ".cache" / "chicago_1k_car" / "sumo"
        assert (cache / ".prepared").read_text() == new_hash

    def test_warm_hit_when_bundle_unchanged(
        self, tmp_path: Path, monkeypatch,
    ):
        """Sanity: re-running with the SAME manifest content is a cache hit."""
        bundle = tmp_path / "scenarios" / "chicago_1k_car"
        self._write_bundle(bundle, manifest_text="stable")

        h = BenchmarkHarness(output_base=tmp_path)
        called = []
        monkeypatch.setattr(
            h, "prepare_sumo_inputs",
            lambda *a, **kw: called.append(1),
        )

        for _ in range(3):
            h._ensure_prepared_cache(
                scenario_path=bundle, scenario_id="chicago_1k_car",
                engine="sumo", engine_options=None,
            )
        # Note: prepare is called once on cold, but our monkeypatch above
        # never writes anything to the cache dir, so the dir is empty
        # except for the sentinel. Subsequent calls still hit because
        # the sentinel exists with matching hash.
        assert len(called) == 1, "should prep only once for an unchanged bundle"

    def test_mirror_hardlinks_cache_to_run_dir(self, tmp_path: Path):
        """Files mirrored from cache to run_dir share inodes (hardlink)."""
        h = BenchmarkHarness(output_base=tmp_path)
        cache = tmp_path / ".cache" / "x" / "dtalite"
        cache.mkdir(parents=True)
        (cache / "node.csv").write_text("id,x,y\n1,0,0\n")
        (cache / "link.csv").write_text("from,to\n1,2\n")
        (cache / ".prepared").touch()

        run_dir = tmp_path / "x" / "dtalite" / "meso" / "seed_42"
        h._mirror_cache_to_run_dir(cache, run_dir, "dtalite", 42, None)

        for name in ("node.csv", "link.csv"):
            assert (run_dir / name).is_file(), f"{name} missing from run_dir"
            # Same inode → hardlinked, no disk-space duplication.
            assert (
                os.stat(cache / name).st_ino == os.stat(run_dir / name).st_ino
            ), f"{name} not hardlinked"
        # Sentinel must NOT propagate (it would confuse other code).
        assert not (run_dir / ".prepared").exists()

    def test_mirror_falls_back_to_copy_on_oserror(
        self, tmp_path: Path, monkeypatch,
    ):
        """When os.link raises (cross-FS), fall back to shutil.copy2."""
        import execution.run_benchmark as mod

        h = BenchmarkHarness(output_base=tmp_path)
        cache = tmp_path / ".cache" / "x" / "sumo"
        cache.mkdir(parents=True)
        (cache / "f.txt").write_text("hello")
        (cache / ".prepared").touch()

        def boom(_src, _dst):
            raise OSError("simulated cross-filesystem")

        monkeypatch.setattr(mod.os, "link", boom)

        run_dir = tmp_path / "x" / "sumo" / "meso" / "seed_42"
        h._mirror_cache_to_run_dir(cache, run_dir, "sumo", 42, None)

        assert (run_dir / "f.txt").read_text() == "hello"
        # Copy → different inode (not hardlinked).
        assert (
            os.stat(cache / "f.txt").st_ino != os.stat(run_dir / "f.txt").st_ino
        )
