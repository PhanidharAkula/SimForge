# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

Commit hashes refer to the `Version_2` branch.

## [Unreleased]

### Added

- **Hash-pinned local OSM ingest (`osm_data/`)** — SimForge no longer depends on the live Overpass API for the cities it ships. State-level Geofabrik PBF snapshots (Illinois 348 MB, New York 489 MB, California 1.3 GB) are pinned by SHA-256 + MD5 in `osm_data/manifest.json`.
- **`tools/download_osm.py`** — idempotent fetcher that downloads each manifest entry, verifies both hashes, and skips already-present files. Replaces the old per-scenario Overpass warm-up for the committed cities.
- **`pipeline/network/load_network_from_pbf.py`** — pyosmium `FileProcessor().with_locations()` + `BackReferenceWriter` pipeline that bbox-slices a state-level PBF into an `.osm.xml` fragment without materialising the whole file, then hands it to `osmnx.graph_from_xml`.
- **`doc/PITZER.md`** — new end-to-end guide for the OSC Pitzer supercomputer workflow: account setup, module loads, filesystem layout, PBF / ModelGen rsync, `srun` vs. `sbatch` templates per generation tier, job monitoring (`squeue` / `sacct`), QarSUMO GPU build, and troubleshooting.
- **`pyproject.toml`** with `[tool.pytest.ini_options]`: `testpaths`, `--strict-markers`, `--strict-config`, `--tb=short`, and a registered marker set (`slow`, `integration`, `determinism`, `requires_sumo`, `requires_java`, `requires_gpu`). Now also carries `[tool.coverage.run]` / `[tool.coverage.report]` / `[tool.coverage.xml]` (branch coverage, `source = [adapters, evaluation, pipeline]`, renderers + data-dependent modules in `omit`) and `[tool.mutmut]` (mutation-testing scope pinned to the two cross-engine-fairness modules).
- **`tests/conftest.py`** with shared fixtures (`bundled_scenario`, `all_bundled_scenarios`, `small_bundled_scenarios`, `repo_root`) and helpers (`file_sha256`, `directory_sha256`, `is_arm64_netconvert_crash`, `is_large_scenario`, `warn_skipped`). Eliminates the `_CANDIDATES` scenario-discovery duplication that was sitting in five test files.
- **`tests/test_scc.py`** (16 tests) — covers `pipeline/network/scc.py` (iterative Kosaraju + parsing) including a 5 000-node deep-chain test that would blow the recursive form's stack.
- **`tests/test_feasibility.py`** (16 tests) — covers `adapters/common/feasibility.py`, the shared SCC-based trip filter that was the [1.0.0] cross-engine fairness fix. Exercises all four drop reasons (outside-SCC, unknown-node, missing-fields, missing-column), `FeasibilityReport` math, JSON persistence, log-level routing, manifest path resolution, and end-to-end ≥99 % feasibility on bundled scenarios.
- **`tests/test_analyze_benchmark.py`** (25 tests — up from 16) — now also exercises every renderer (`print_runtime_table`, `print_reproducibility_table`, `print_summary_table`, `print_coverage_report` asymmetric + thin-cell detection, `generate_latex_table`, `generate_markdown_table`) alongside the original mode-aware grouping + `_resolve_identity` fallback coverage.
- **`tests/test_osm_fetch.py`** (20 tests) — fully mocked Overpass/osmnx pipeline: `BoundingBox` validation (inverted lat/lon, `from_string` arity, `from_center` geometry), cache folder pinning to `<repo>/cache`, error translation (`ConnectionError → RuntimeError` with a "possible causes" block), empty-result guard (`ValueError`), missing-osmnx guard (`ImportError`), the `PREDEFINED_CITIES` catalogue, and full `build_network_from_osm` end-to-end against a duck-typed stub graph.
- **`tests/test_demand_generators.py`** (21 tests) — `UniformRandomGenerator`, `GravityModelGenerator`, `PeakHourGenerator`, `load_network_for_demand`, and the `generate_synthetic_demand` dispatch. Proves SCC restriction on synthetic grids (dead-end nodes excluded from OD sampling), deterministic seeding (byte-identical `demand.csv` across runs), canonical CSV header, and the peak-hour temporal profile.
- **`tests/test_engine_smoke.py`** (4 tests) — real-binary smoke for `sumo`, `netconvert`, and the MATSim JAR on the bundled scenario; asserts the engine produced non-empty artefacts (`tripinfo.xml`, `output_trips.csv.gz`). Skip-gracefully via `shutil.which()` + `check_java_available()` + `find_matsim_jar()` so `pytest -m "not slow"` stays green on a dev laptop without SUMO/Java installed.
- **`requirements-dev.txt`** — pins `pytest>=7.0`, `pytest-cov>=4.1`, `pytest-xdist>=3.5`, `mutmut>=2.5,<3` on top of the runtime requirements.
- **`doc/MUTATION_BASELINE.md`** — documents the `mutmut` scope (only `adapters/common/feasibility.py` + `pipeline/network/scc.py`, since those are the two modules that make cross-engine comparison *fair*), the narrow runner, the baseline table (populated on first run), and the surviving-mutant review checklist.

### Changed

- **Network generation default flipped to PBF.** `pipeline/network/build_network_from_osm.py` now looks up `osm_data/manifest.json` first and dispatches to `load_network_from_pbf.py` when a covering PBF is present; the live Overpass path is reached only when no local file covers the bbox. `generate.py` hard-fails with a pointer to `tools/download_osm.py` if a committed city is requested but its PBF is absent.
- **osmnx 2.x required.** `requirements.txt` now pins `osmnx>=2.0,<3` and `pipeline/network/load_network_from_pbf.py` calls `truncate_graph_bbox` only with the v2.x positional `bbox=(W, S, E, N)` tuple. The 1.9.x compat branch (`north=/south=/east=/west=` kwargs) is gone — clean reinstalls and Pitzer envs need `pip install -U "osmnx>=2.0,<3"` before re-running generation. The `geopandas` pin is bumped to `>=1.0,<2` to satisfy osmnx 2.x's transitive requirement (`geopandas>=1.0.1`); the previous `>=0.9,<1` would break `pip install -r requirements.txt` against the new osmnx range. SimForge code does not import geopandas directly.
- **`requirements.txt`** now declares `osmium>=4.0` (pyosmium) explicitly and documents Overpass as fallback-only in an inline comment.
- **All test files refactored** to use shared `bundled_scenario` / `small_bundled_scenarios` fixtures instead of duplicating the scenario-discovery preamble. Suite-wide adapter sweeps now carry `@pytest.mark.slow` / `@pytest.mark.requires_sumo` so contributors can run the fast tier with `pytest -m "not slow"`.
- **`tests/test_scalability_metrics.py`** — `test_timer_measures_time` no longer relies on a hard-coded 0.05–0.30 s window; it now compares against a `time.monotonic()` reference, removing host-load flakiness.
- **`TESTING.md`** rewritten to document the 17-file / 293-test layout, the coverage summary (76.3 % line coverage; 70 % floor), and the run-command catalogue (full / fast / slow / by-marker / coverage / parallel / mutmut).

### Fixed

- **NYC 500 K generation unblocked** — the previous Overpass path timed out on the full NYC bbox and the alternative (splitting the bbox across multiple Overpass queries) produced non-deterministic topology between runs. The PBF slice is both faster and byte-reproducible.
- **MATSim 15.0 download URL** corrected in `setup_simforge.py`; the old release asset URL had been superseded on GitHub and caused a silent 404 → zero-byte JAR on fresh clones.
- **Test count reconciled to 249.** Removing the redundant `nyc_1k_car`, `la_1k_car`, and three synthetic bundles shrank the parametrised suite in `tests/test_scenario_data_integrity.py` (70 → 35) and `tests/test_scc.py` (16 → 14). Docs across `README.md`, `SETUP.md`, `TESTING.md`, `CONTRIBUTING.md`, `help.py`, and the thesis chapters now consistently report **249 tests** (previously 293).

---

## [1.1.0] — 2026-04-19

Plot polish, coverage diagnostics, and cache hygiene. Commit `537ae75`.

### Added

- **Coverage diagnostic** in `evaluation/analyze_benchmark.py` (`print_coverage_report`) — flags low-sample cells (`n < 3`), asymmetric coverage across scenarios, and silently-failed cells.
- **`tools/clean.sh`** — wipes Python bytecode (`__pycache__`, `*.pyc`, `.pytest_cache`); `--all` also drops `cache/` (OSM Overpass HTTP cache).
- **Per-bar error bars** confirmed on Figs 5.1 and 5.3 (`yerr=errs, capsize=3`) for cross-engine variance disclosure.

### Changed

- **`runspecs/stress_test.yaml`** now declares the full 8-cell matrix (2 scenarios × {SUMO meso, SUMO micro, QarSUMO meso, MATSim meso}); previously NYC was missing `qarsumo/meso` and `sumo/micro`.
- **Plot save signature** simplified: folded redundant `_save(fig, name, dir)` into `_save(name, dir)` across all 9 figure functions; cleaned up Pylance warnings.

### Removed

- **Fig 5.10 (travel-time spread)** — duplicated information already shown in Fig 5.7 (runtime variability boxplot).

### Fixed

- **`.gitignore`** now covers `.modelgen_cache.json` (per-machine fingerprints — kept causing diff churn). Verified no stray `.DS_Store` files were tracked.

---

## [1.0.0] — 2026-04-18

First end-to-end-correct release: SCC-aware demand, mode-aware analysis, fair cross-engine comparison, unified result schema. Commits `e508d5c`, `cd16a52`, `ac7e483`.

### Added

- **`pipeline/network/scc.py`** — single canonical iterative-Kosaraju + network parser. Used by both demand generators and the adapter-layer post-condition feasibility check.
- **`adapters/common/feasibility.py`** — `feasible_trip_ids(network_path, demand_path)` builds the SCC once and returns the set of trip IDs whose origin AND destination both lie in it.
- **`feasibility_report.json`** — emitted next to every adapter's output, plus a WARNING line: `[sumo] feasibility: 1000/1000 trips (100.0%) — SCC covers 1204/1245 nodes, 2796/2856 links`.
- **`pipeline/network/warmup.py`** — walks `scenarios/*/`, reconstructs each bbox (preferring `generation_metadata.json`'s `city`+`radius_km` so it matches the original Overpass cache key), and forces a fetch through the same `download_osm_network` path used at scenario generation. A fresh clone can pre-warm everything with `python -m pipeline.network.warmup`.
- **OSM cold-start logging** — `download_osm_network()` logs a WARNING (`first-time fetch contacts the Overpass API and may take 10 s–2 min`) on cache miss, INFO (`cached OSM response found`) otherwise, with a `cache hit` / `fresh fetch` label after the call.

### Changed

- **Mode-aware analysis grouping**: `evaluation/analyze_benchmark.py` previously grouped by `(scenario, engine)`, collapsing SUMO meso (mean TT 204 s) and micro (mean TT 288 s) into one row. `_resolve_identity` now returns `(scenario, engine, mode)`; grouping key, `ScenarioStats` dataclass, and all output renderers (summary, runtime, reproducibility, LaTeX, Markdown) carry the mode column. (`generate_plots.py` and `compare_modes.py` already grouped by mode — only the analyze module was buggy.)
- **`pipeline/demand/generate_synthetic_demand.py`** replaced its single-source-BFS SCC approximation with `compute_largest_scc`.
- **`pipeline/demand/generate_census_demand.py`** restricts both origin sampling (residential buildings) and destination sampling (degree-weighted gravity) to SCC members; logs dropped-building count.
- **`adapters/common/feasibility.py`** delegates SCC computation to `pipeline.network.scc` — behaviour unchanged but no longer duplicated.
- **OSM cache pinned**: `pipeline/network/build_network_from_osm.py::_configure_osmnx_cache()` pins `ox.settings.cache_folder` to `<repo>/cache`.
- **Unified result schema**: `run.py` and `execution.run_benchmark` previously emitted slightly different JSON shapes; both code paths now write the same canonical schema. Downstream tools (`analyze_benchmark.py`, `generate_plots.py`, `compare_modes.py`) accept either source uniformly.

### Fixed

- **Engine input asymmetry**: SUMO and MATSim previously simulated *different subsets* of the same demand — SUMO silently dropped per-trip if origin/destination weren't reachable, while MATSim dropped trips whose nodes lay outside the largest strongly-connected component of its cleaned network. Result on `chicago_1k_car`: SUMO ran 988/1000 trips, MATSim ran 981/1000. Now SUMO, MATSim, and QarSUMO all consume the shared SCC filter — verified the per-engine skip lists are byte-identical and `feasibility_report.json` reports `feasible_trips == total_trips == 1000` on both bundles.
- **Inflated R-Score from mode collapse**: combining SUMO meso (TT ≈ 204 s) and micro (TT ≈ 288 s) into one row inflated combined std/mean and dropped the displayed R-Score to 0.8132 ("Poor") despite each individual mode scoring ≥ 0.997 ("Excellent"). Mode-aware grouping (above) restored correct per-mode scores.

---

## [0.9.0] — 2026-04-17

Initial end-to-end stress test: the first comprehensive run-through of the full pipeline (generate → validate → benchmark → analyse → plot). Surfaced the silent failure modes that `[1.0.0]` subsequently fixed, plus four concrete bugs. Commit `d06cf0a`.

### Fixed

- **`--validate-only` `AttributeError` on `Path`** — `run.py` now wraps `scenarios_available[s]["path"]` in `Path(...)`.
- **`test_all_scenarios` hangs on 50K+ scenarios** — added `_LARGE_PATTERNS` filter (`50k`, `200k`, `500k`, `5m`) to all four `test_*_all_scenarios` paths.
- **`RuntimeError` text-matching missed arm64 "crashed"** — tests now match both `"failed"` and `"crashed"` in error text.
- **`nyc_10k_car` arm64 netconvert crash** (4 041 nodes exceeded the ~3 000-node arm64 SUMO threshold) — regenerated with `--radius 2.5` (1 376 nodes).

### Outcome

- 184 unit tests passing.
- Full benchmark matrix 16/16 successful at the time (subsequently expanded to 22/22 in `[1.1.0]` after NYC qarsumo/micro cells were added to the runspec).
- Plots rendering cleanly; all error paths handled.

---

## [0.5.0] — 2026-04-15 → 2026-04-17

Foundation work prior to the first end-to-end stress test. Earlier per-commit detail is in `git log`; the key milestones:

### Added

- **Comprehensive test suite** (`ae4dcb2`) — now 184 tests across 11 files.
- **OSC Pitzer cluster scripts**, 500K jobs, cluster guide, HPC pin updates (`be20205`, `7ac0bb5`, `45188be`).
- **ModelGen integration** (`2315dde`) — PUMS census microdata for population-weighted demand.

### Changed

- **Thesis-defense documentation overhaul** (`e7e156d`, `6d98a7d`, `66f3d5f`) — architecture, scenario generation, methods/experiments chapters.

---

For per-commit detail beyond what's captured here, run `git log` on the `Version_2` branch.
