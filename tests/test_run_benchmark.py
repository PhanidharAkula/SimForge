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
        # Phase 12.2 path: <scoped_base>/.cache/<engine>/
        # output_base.name != scenario_id here, so scoped_base inserts
        # the scenario layer.
        cache = tmp_path / "chicago_1k_car" / ".cache" / "sumo"
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

        def fake_prepare(scenario_path, output_dir, seed=0, canonical_routes=None):
            called.append(output_dir)
            (output_dir / "toy.sumocfg").write_text("<dummy/>")
            (output_dir / "tripinfo.xml").write_text("<dummy/>")

        monkeypatch.setattr(h, "prepare_sumo_inputs", fake_prepare)
        # Phase 14: stub the canonical-routes computation — the synthetic
        # bundle has no network.xml/demand.csv. The cache-management
        # behavior under test is independent of route content.
        monkeypatch.setattr(h, "_canonical_routes_for", lambda *a, **kw: {})

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

        def fake_prepare(scenario_path, output_dir, seed=0, canonical_routes=None):
            called.append(output_dir)
            (output_dir / "toy.sumocfg").write_text("<dummy/>")

        monkeypatch.setattr(h, "prepare_sumo_inputs", fake_prepare)
        monkeypatch.setattr(h, "_canonical_routes_for", lambda *a, **kw: {})

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
        # Sentinel now reflects the new hash. Phase 12.2 path:
        # <scoped_base>/.cache/<engine>/.prepared (with scoped_base
        # = output_base/scenario_id since output_base.name != scenario_id).
        cache = tmp_path / "chicago_1k_car" / ".cache" / "sumo"
        assert (cache / ".prepared").read_text() == new_hash

    def test_scoped_base_collapses_when_output_matches_scenario(
        self, tmp_path: Path,
    ):
        """Phase 12.2: when output_base.name == scenario_id (typical
        parallel-by-scenario sbatch case), _scoped_base returns
        output_base unchanged so per-cell + cache paths don't pick up
        a redundant <scenario>/<scenario>/ doubling."""
        per_scenario = tmp_path / "runs_root" / "chicago_1k_car"
        per_scenario.mkdir(parents=True)
        h = BenchmarkHarness(output_base=per_scenario)
        assert h._scoped_base("chicago_1k_car") == per_scenario

    def test_scoped_base_inserts_scenario_when_output_is_shared(
        self, tmp_path: Path,
    ):
        """When output_base is the SHARED runspec output dir (no per-
        scenario sbatch wrapping), _scoped_base inserts scenario_id so
        multiple scenarios under one output_base don't collide."""
        shared = tmp_path / "runs_root"
        shared.mkdir(parents=True)
        h = BenchmarkHarness(output_base=shared)
        assert h._scoped_base("chicago_1k_car") == shared / "chicago_1k_car"
        assert h._scoped_base("nyc_10k_car") == shared / "nyc_10k_car"

    def test_cache_dir_collapses_in_per_scenario_output(
        self, tmp_path: Path, monkeypatch,
    ):
        """Cold prep into a per-scenario output_base lands the cache at
        ``<output_base>/.cache/<engine>/`` (no scenario_id segment)."""
        bundle = tmp_path / "scenarios" / "chicago_1k_car"
        self._write_bundle(bundle)

        per_scenario = tmp_path / "runs" / "chicago_1k_car"
        per_scenario.mkdir(parents=True)
        h = BenchmarkHarness(output_base=per_scenario)

        monkeypatch.setattr(
            h, "prepare_sumo_inputs",
            lambda sp, od, seed=0, canonical_routes=None: (
                (od / "toy.sumocfg").write_text("<x/>")
            ),
        )
        monkeypatch.setattr(h, "_canonical_routes_for", lambda *a, **kw: {})

        cache = h._ensure_prepared_cache(
            scenario_path=bundle, scenario_id="chicago_1k_car",
            engine="sumo", engine_options=None,
        )
        # Phase 12.2: collapsed — no <scenario_id>/ between .cache and engine.
        assert cache == per_scenario / ".cache" / "sumo"
        assert (cache / ".prepared").is_file()

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
        monkeypatch.setattr(h, "_canonical_routes_for", lambda *a, **kw: {})

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


# ---------------------------------------------------------------------------
# Phase 14.13 — canonical_routes cache hoist + legacy-cache migration.
# ---------------------------------------------------------------------------


class TestCanonicalRoutesCacheRoot:
    """Phase 14.13: cache moved from per-output-dir to global cache/canonical_routes/."""

    def test_cache_root_is_global_under_cache_dir(self):
        """Cache root is cache/canonical_routes/ regardless of output_base."""
        root = BenchmarkHarness._canonical_routes_cache_root()
        assert root == Path("cache") / "canonical_routes"

    def test_cache_root_does_not_depend_on_harness_output_base(
        self, tmp_path: Path,
    ):
        """The global cache root is independent of the harness's output_base.

        Two harnesses with different output_base values must agree on the
        cache location — that's the entire point of the Phase 14.13 hoist.
        """
        h1 = BenchmarkHarness(output_base=tmp_path / "runA")
        h2 = BenchmarkHarness(output_base=tmp_path / "runB")
        assert (
            h1._canonical_routes_cache_root()
            == h2._canonical_routes_cache_root()
        )


class TestLegacyCanonicalRoutesCacheMigration:
    """Phase 14.13: one-time migration of pre-hoist cache files."""

    def test_migrates_legacy_cache_file_to_global_location(
        self, tmp_path: Path,
    ):
        """A cache file at the old per-output-dir location is moved into
        the global location on first lookup.
        """
        h = BenchmarkHarness(output_base=tmp_path)
        legacy_root = tmp_path / "chicago_1k_car" / ".canonical_routes"
        legacy_root.mkdir(parents=True)
        cache_file = legacy_root / "canonical_routes_deadbeef.jsonl"
        cache_file.write_text('{"_meta":true,"version":1,"trip_count":0}\n')
        original_inode = os.stat(cache_file).st_ino

        target_root = tmp_path / "global_cache"
        h._migrate_legacy_canonical_routes_cache("chicago_1k_car", target_root)

        # File moved to global location, original gone.
        assert not cache_file.exists()
        migrated = target_root / "canonical_routes_deadbeef.jsonl"
        assert migrated.exists()
        # Same inode → atomic rename, not copy.
        assert os.stat(migrated).st_ino == original_inode

    def test_no_op_when_legacy_dir_absent(self, tmp_path: Path):
        """A scenario that never used the per-output-dir cache must not
        cause errors when migration is attempted.
        """
        h = BenchmarkHarness(output_base=tmp_path)
        target = tmp_path / "global"
        # No exception — migration is a defensive operation.
        h._migrate_legacy_canonical_routes_cache("never_run_scenario", target)
        # Target dir doesn't get created if there's nothing to migrate.
        assert not target.exists()

    def test_preserves_legacy_when_target_already_has_file(
        self, tmp_path: Path,
    ):
        """If the global cache already contains the same content-hash file,
        the legacy file is left in place (operator can verify before
        manually cleaning up).
        """
        h = BenchmarkHarness(output_base=tmp_path)
        legacy_root = tmp_path / "chicago_1k_car" / ".canonical_routes"
        legacy_root.mkdir(parents=True)
        legacy_file = legacy_root / "canonical_routes_aaa.jsonl"
        legacy_file.write_text("legacy-content")

        target_root = tmp_path / "global_cache"
        target_root.mkdir()
        target_file = target_root / "canonical_routes_aaa.jsonl"
        target_file.write_text("global-content")

        h._migrate_legacy_canonical_routes_cache("chicago_1k_car", target_root)

        # Both files still exist; global wins; legacy untouched.
        assert legacy_file.read_text() == "legacy-content"
        assert target_file.read_text() == "global-content"

    def test_migrates_multiple_cache_files_for_same_scenario(
        self, tmp_path: Path,
    ):
        """When the legacy dir has multiple hash files (e.g. bundle was
        regenerated with different demand), all migrate.
        """
        h = BenchmarkHarness(output_base=tmp_path)
        legacy_root = tmp_path / "chicago_1k_car" / ".canonical_routes"
        legacy_root.mkdir(parents=True)
        for hash_id in ("hash_a", "hash_b", "hash_c"):
            (legacy_root / f"canonical_routes_{hash_id}.jsonl").write_text(
                f"content-{hash_id}"
            )

        target_root = tmp_path / "global_cache"
        h._migrate_legacy_canonical_routes_cache("chicago_1k_car", target_root)

        for hash_id in ("hash_a", "hash_b", "hash_c"):
            assert (
                target_root / f"canonical_routes_{hash_id}.jsonl"
            ).exists(), f"hash_id {hash_id} not migrated"
        # Legacy dir is empty (everything moved out).
        assert not list(legacy_root.glob("canonical_routes_*.jsonl"))

    def test_only_migrates_canonical_routes_files(self, tmp_path: Path):
        """Other files in the legacy dir (e.g. accidentally-placed
        garbage) are NOT migrated — only canonical_routes_*.jsonl.
        """
        h = BenchmarkHarness(output_base=tmp_path)
        legacy_root = tmp_path / "chicago_1k_car" / ".canonical_routes"
        legacy_root.mkdir(parents=True)
        (legacy_root / "canonical_routes_a.jsonl").write_text("yes")
        (legacy_root / "garbage.txt").write_text("no")
        (legacy_root / "canonical_routes_b.json").write_text("no")  # wrong ext

        target_root = tmp_path / "global_cache"
        h._migrate_legacy_canonical_routes_cache("chicago_1k_car", target_root)

        assert (target_root / "canonical_routes_a.jsonl").exists()
        assert not (target_root / "garbage.txt").exists()
        assert not (target_root / "canonical_routes_b.json").exists()
        # Garbage left in legacy dir untouched.
        assert (legacy_root / "garbage.txt").exists()
        assert (legacy_root / "canonical_routes_b.json").exists()
