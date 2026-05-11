# SimForge Test Suite

**~477 tests** across **23 test files** covering adapters, metrics, validation,
data integrity, end-to-end pipeline, the canonical SCC algorithm, the shared
feasibility filter, the mode-aware benchmark analyser, the cross-engine
fairness audit, OSM network fetching (mocked), demand generators, and
real-binary engine smoke tests. The total scales with the number of bundled
scenarios in `scenarios/` because `test_scenario_data_integrity.py` is
parametrized over each one.

Pytest configuration lives in `pyproject.toml` (`[tool.pytest.ini_options]`)
with strict-marker enforcement, `testpaths = ["tests"]`, and `--tb=short`.
Coverage thresholds are enforced by `pytest-cov` (≥70 % floor, currently
**76 %** — see `[tool.coverage]` in `pyproject.toml`).  Shared
scenario-discovery, hashing, and arm64-skip helpers live in
`tests/conftest.py`.

The project ships without a hosted CI workflow — `python -m pytest` is the
authoritative gate and is expected to pass before any merge. On Apple Silicon
the SUMO-dependent tests skip individually via the `arm64 netconvert` segfault
detector documented below, so the full suite stays green on a developer Mac.
Mutation testing against the two cross-engine-fairness modules is documented
in [`doc/MUTATION_BASELINE.md`](doc/MUTATION_BASELINE.md).

---

## Quick start

```bash
source .venv/bin/activate

# Full suite (includes adapter sweeps and any available real-binary smoke).
# ~3-4 min on arm64 (where SUMO sweeps skip individually due to the
# netconvert segfault); ~22 s on Linux where SUMO actually runs.
python -m pytest

# Per-test ✓/✗/⊘ rows instead of the per-file rollup.
python -m pytest -v

# Stop on first failure, verbose output.
python -m pytest -v -x

# Plain pytest output (disable the sticky_progress plugin).
python -m pytest -p no:sticky_progress

# One file or one class.
python -m pytest tests/test_feasibility.py
python -m pytest tests/test_scenario_data_integrity.py::TestNetworkIntegrity

# Substring filter on test names.
python -m pytest -k "scc or feasibility"

# Marker filters (registered in pyproject.toml).
python -m pytest -m determinism
python -m pytest -m integration
python -m pytest -m "not requires_sumo"   # skip tests needing the SUMO binary

# Coverage. Dev deps (pytest-cov, pytest-xdist, mutmut) are installed
# automatically by setup_simforge.py; on a manual venv run
# `pip install -r requirements-dev.txt` once before these commands.
# Source/omit lists and the report format are configured in pyproject.toml.
python -m pytest --cov --cov-report=term-missing

# Enforce the 70 % coverage floor (same threshold pyproject.toml declares).
python -m pytest --cov --cov-fail-under=70

# Parallel execution (pytest-xdist ships in requirements-dev.txt).
python -m pytest -n auto

# Mutation testing against the cross-engine-fairness modules (mutmut in dev deps).
mutmut run
mutmut results
```

---

## Markers

Registered in `pyproject.toml`. `--strict-markers` rejects unknown markers.

| Marker            | Meaning                                                      |
| ----------------- | ------------------------------------------------------------ |
| `integration`    | Exercises multiple subsystems end-to-end                      |
| `determinism`    | Verifies byte-identical adapter outputs across re-runs        |
| `requires_sumo`  | Needs the SUMO `netconvert` / `sumo` binaries on PATH         |
| `requires_java`  | Needs Java + the MATSim JAR (`lib/matsim-15.0/`)              |
| `requires_gpu`   | Needs an NVIDIA GPU + a built LPSim binary (no CPU fallback). Preserved for the LPSim retrospective; no V5 tests carry it. |

The `requires_*` markers are advisory today (no auto-skip plumbing yet) — they
let contributors filter explicitly with `-m "not requires_java"`.

---

## Test files

### 1. `test_adapter_determinism.py` — Determinism (8 tests, `@determinism`)

Two runs of `prepare_sumo_inputs` on the same scenario must produce
byte-identical output (modulo netconvert's embedded timestamp on `net.net.xml`).
Catches hash-randomised dict iteration, float summation order, and timestamp
leaks into XML.

### 2. `test_sumo_adapter.py` — SUMO Adapter (4 tests)

Validates the SUMO input bundle (`net.net.xml`, `routes.rou.xml`,
`toy.sumocfg`), edge-length attribution, and lane-length sanity (catches
missing geo projection). Includes an all-scenarios sweep that
`pytest.skip`s when arm64 `netconvert` segfaults filter every candidate.

### 3. `test_matsim_adapter.py` — MATSim Adapter (24 tests)

Tests the MATSim adapter's helpers (`seconds_to_time_string`, `MATSimConfig`,
vehicles XML, network XML, plans XML, config XML) and the full
`prepare_matsim_inputs` pipeline. No Java/JAR required.

**Wall time on M-series Mac: ~10 min.** Most of it is one
`test_all_scenarios` sweep that pre-routes nyc_10k_car's 10K trips
through V5 Phase 7's state-aware BFS — legitimate work, not redundancy.
For routine dev, skip the sweep:

```bash
python -m pytest tests/test_matsim_adapter.py -k "not test_all_scenarios"
```

That keeps 23 of 24 assertions live and runs in ~3 min.

V11.3 added session-scoped fixtures (`canonical_network_data`,
`built_network_xml`, `built_plans_xml`, `prepared_chicago`,
`prepared_sweep`) so structure-only assertions don't re-trigger the
prepare/build pipeline per test. That cleared ~75 s of cross-test
redundancy. Determinism of the cached code paths is enforced separately
in `tests/test_adapter_determinism.py`.

### 4. `test_dtalite_adapter.py` — DTALite Adapter (46 tests)

Tests `DTALiteConfig`, `_to_int_index`, the writers
(`write_dtalite_node_csv`, `write_dtalite_link_csv`,
`write_dtalite_demand_csv`, `write_dtalite_settings_csv`,
`write_dtalite_settings_yml`), demand-driven zoning (only
origin/destination nodes promoted to GMNS zones), the determinism
guarantee (byte-identical re-runs), end-to-end input prep on the
bundled scenario, output parsing on synthetic `agent.csv` fixtures
with volume expansion + minute→second conversion, and binary discovery.
The end-to-end smoke test is gated on path4gmns availability — when
installed, it actually runs DTALite via UE assignment in ~5–10 s.

### 5. `test_fidelity_metrics.py` — Fidelity Metrics (21 tests)

RMSE, GEH (single + batch), KS statistic, and `compute_fidelity_metrics`.

### 6. `test_metrics_travel_time.py` — Travel Time (2 tests)

`parse_sumo_tripinfo` over a hand-written tripinfo XML.

### 7. `test_reproducibility_metrics.py` — Reproducibility (15 tests)

R = 1 − σ/μ scoring, multi-KPI rollup, threshold checks.

### 8. `test_scalability_metrics.py` — Scalability (8 tests)

`SimulationTimer` (now using `time.monotonic()` reference for deterministic
bounds), `HardwareInfo`, `compute_scalability_metrics`, scalability comparison.

### 9. `test_validator.py` — Bundle Validator (2 tests)

Real-bundle round-trip: a clean scenario passes; a scenario with a bogus
origin node fails.

### 10. `test_scenario_data_integrity.py` — Data Integrity (216 tests)

**Critical.** Parametrized over every complete scenario in `scenarios/`. With
the six currently-bundled scenarios this expands to 216 tests across:

| Class                  | What it checks                                                     |
| ---------------------- | ------------------------------------------------------------------ |
| `TestFileExistence`    | All 5 canonical files exist                                         |
| `TestXMLParsing`       | All XML files are well-formed                                       |
| `TestNetworkIntegrity` | Unique node/link IDs, valid WGS84 coords, valid endpoints, +length/speed/lanes |
| `TestDemandIntegrity`  | Required columns, unique trip IDs, all OD nodes exist, sane departures, valid modes |
| `TestConfigIntegrity`  | Metadata, scenario_id matches dir, valid time horizon, units, seed |
| `TestManifestIntegrity`| Manifest ID matches config, all declared files exist               |
| `TestSignalsIntegrity` | All junction node references exist in the network                  |

### 11. `test_pipeline_e2e.py` — End-to-End Pipeline (20 tests; some `@integration`)

| Class                         | What it checks                                                         |
| ----------------------------- | ---------------------------------------------------------------------- |
| `TestValidatorCatchesBadData` | 13 corruption scenarios — missing/corrupt files, bad columns, bogus nodes, etc. |
| `TestSUMOAdapterRobustness`   | All-scenarios sweep, route-edge consistency, tripinfo configured       |
| `TestNetworkRouting`          | BFS correctness on synthetic graphs and ≥80 % real-network routability |

### 12. `test_scc.py` — Canonical SCC (14 tests)

Iterative Kosaraju on synthetic graphs (empty, singleton, 2-cycle, chain,
multiple components, classic Cormen example, 5 000-node deep chain) plus
`parse_network` (well-formed, self-loop drop, malformed XML rejection) and
real bundled-network coverage (≥95 %).

### 13. `test_feasibility.py` — Cross-engine feasibility filter (16 tests)

The shared SCC-based filter that makes SUMO and MATSim simulate the
**same** trip subset (CHANGELOG 1.0.0 fix). Covers feasible-trip computation,
all four drop reasons (outside-SCC, unknown-node, missing-fields, missing-column-in-CSV),
`FeasibilityReport` math (`feasible_fraction`, `summary_line`, `to_dict`),
JSON persistence, log-level routing, manifest path resolution, and
end-to-end ≥99 % feasibility on the bundled scenario.

### 14. `test_analyze_benchmark.py` — Benchmark analyser (24 tests)

The mode-aware grouping and identity-resolution logic that prevents the
silent R-score collapse that was fixed in [1.0.0]. Covers `_resolve_identity`
explicit + scenario_id-fallback paths for all engines, `compute_reproducibility`
edge cases (single-value, identical, low/high variance, zero-mean), and the
mode-aware grouping itself (meso vs micro stay separate, failed runs recorded,
zero-TT outliers filtered, both `runs` and `results` keys accepted).  Also
exercises every renderer — `print_runtime_table`, `print_reproducibility_table`,
`print_summary_table`, `print_coverage_report` (asymmetric + thin-cell
diagnostics), and the LaTeX/Markdown table generators.

### 15. `test_osm_fetch.py` — OSM network fetching (20 tests)

Fully mocked Overpass/osmnx pipeline.  `BoundingBox` validation (inverted
lat/lon, from_string arity, from_center geometry), cache folder pinning to
`<repo>/cache`, error translation (ConnectionError → RuntimeError with a
"possible causes" block), empty-result guard (`ValueError`), missing-osmnx
guard (`ImportError`), and the `PREDEFINED_CITIES` catalogue.  Also
round-trips `extract_canonical_network` and the full
`build_network_from_osm` end-to-end against a stub graph so XML output is
verified without touching the network.

### 16. `test_demand_generators.py` — Demand generators (21 tests)

`UniformRandomGenerator`, `GravityModelGenerator`, `PeakHourGenerator`,
`load_network_for_demand`, and the top-level `generate_synthetic_demand`
dispatch.  Proves SCC restriction on synthetic grids (dead-end nodes
excluded from OD sampling), deterministic seeding (byte-identical
demand.csv across runs), canonical CSV header, and the peak-hour temporal
profile.  Complements the adapter-level feasibility filter — the two
tests together prove that every emitted trip is routable in the engine.

### 17. `test_engine_smoke.py` — Real-binary smoke (4 tests)

Actually invokes `sumo`, `netconvert`, the MATSim JAR, and `dtalite` (via
path4gmns) on the bundled scenario and asserts the engine produced
non-empty artefacts (`tripinfo.xml`, `output_trips.csv.gz`,
`agent.csv`).  Each binary-driven smoke test `pytest.skip`s gracefully
when the binary is missing so the suite stays green on a developer
laptop without SUMO/Java/path4gmns installed. The fourth test
is a diagnostic `test_engine_availability_report` that always passes and
prints which binaries are present on the host (useful for debugging
unexpected skips in CI / cluster environments). Catches the class of
regression where the adapter writes files the engine refuses to parse —
something no amount of XML-structure assertions can see.

### 18. `test_confidence.py` — Student's-t 95 % CI (18 tests)

`evaluation/metrics/confidence.confidence_interval_95`: the same CI
helper the thesis tables, the run.py per-cell timing footer, and the
run_benchmark.py summary block all consume. Covers the math at every
sample size (N=1 → no spread, N=2 / N=3 / N≥30 → t-table lookups),
zero-variance and degenerate inputs, and the `ConfidenceInterval`
dataclass fields. Same Student's-t convention as Chapter 5's tables.

### 19. `test_parse_model_file.py` — ModelGen file parser (12 tests)

`pipeline/demand/parse_model_file.py`: parses the
`<city>_model.txt` PUMS microdata files used by the census-driven
demand generator. Covers header detection, mode-code mapping
(JWTRNS → car/transit/bike/walk/excluded), the schedule-vs-gravity
fallback logic, and the per-city aggregate counts surfaced by
`python help.py cities`.

### 20. `test_visualization.py` — Visualization component (13 tests, visualization branch only)

`visualization/` is opt-in and not imported by main SimForge code
paths, so its tests live on the `visualization` branch. The 13 tests
cover the bundle / network / demand loaders, the coverage matrix
(`discover_bundle`, `discover_run_cells`, `format_coverage_matrix`,
`map_generatable`), the CLI dry-run + bogus-map-name rejection, and an
end-to-end render that writes a non-trivial PNG. The render test
auto-skips when the Illinois Census tracts aren't cached locally
(`is_state_cached("17")`), so the suite passes on a machine that hasn't
yet run `python -m tools.download_census_tracts --all-bundled`.

### 21. `test_audit_fairness.py` — Cross-engine fairness audit (29 tests)

`evaluation/audit_fairness.py`: the post-benchmark Q1–Q4 audit script
that proves every engine in a run directory was given the same problem
(SCC-filtered network, byte-identical feasible-trip set) and measured
the same way. Covers the HMS→seconds parser, per-engine travel-time
extractors (SUMO `tripinfo.xml`, MATSim gzipped `output_trips.csv.gz`,
DTALite `agent.csv` with minute→second conversion + volume expansion),
the cheap counters (`_count_dtalite_demand`, `_count_matsim_persons`,
`_count_xml_elements`, `_count_csv_rows`), and — critically — the
4-layout `_find_cell_dir` detector that lets a single
`audit_fairness <run-dir>` invocation work whether the run came from
`run.py` (flat), `run_benchmark.py` (nested), or a parallel-by-scenario
sbatch wrapper (doubly-nested or per-scenario).

---

## Platform notes

### Apple Silicon (arm64) — `netconvert` segfault

SUMO 1.20's `netconvert` can segfault on networks above ~3 000 nodes on
arm64. This is a **SUMO platform bug**, not a SimForge issue.

Adapter sweeps detect arm64 + recognisable crash signals via
`tests/conftest.py::is_arm64_netconvert_crash` and skip those scenarios with
a single `UserWarning` summarising what was skipped. The two bundled small
scenarios are well below the threshold and never skip.

---

## Coverage summary

| Area                   | Tests   | Notes                                                       |
| ---------------------- | ------- | ----------------------------------------------------------- |
| SUMO Adapter           | 4       | File generation, determinism, geo projection, sweep         |
| Adapter determinism    | 8       | Byte-identical SUMO/MATSim outputs across re-runs           |
| MATSim Adapter         | 24      | Helpers, builders, prepare path, sweep                      |
| DTALite Adapter        | 46      | Helpers, writers, demand-driven zoning, determinism, output parsing, end-to-end smoke |
| Fidelity Metrics       | 21      | RMSE, GEH, KS, combined                                     |
| Travel Time            | 2       | Tripinfo parser                                             |
| Reproducibility        | 15      | R-score core, multi-KPI, thresholds                         |
| Scalability            | 8       | Monotonic timer, throughput, comparison                     |
| Validator              | 2       | Real-bundle pass + corruption fail                          |
| Data Integrity         | 216     | 7 classes × every bundled scenario (parametrized)           |
| E2E Pipeline           | 20      | 13 corruption modes, 3 robustness, 4 routing                |
| SCC algorithm          | 14      | Iterative Kosaraju + bundled-network coverage               |
| Feasibility filter     | 16      | Shared cross-engine trip filter                             |
| Benchmark analyser     | 24      | Mode-aware grouping + identity fallback + renderers         |
| OSM fetch              | 20      | Mocked Overpass, bbox validation, cache pin                 |
| Demand generators      | 21      | Synthetic generators + SCC restriction + seed               |
| ModelGen parser        | 12      | PUMS microdata header / mode-code parsing                   |
| Confidence (95 % CI)   | 18      | Student's-t helper used by all per-cell summaries           |
| Engine smoke           | 4       | Real-binary SUMO/MATSim/DTALite smoke + availability report |
| Audit fairness         | 29      | HMS parser, per-engine TT extractors, 4-layout cell detector, orchestrator integration |
| Visualization (opt-in) | 13      | Bundle / coverage loaders, CLI dry-run + render smoke (visualization branch only) |
| **Total**              | **~477** | **~3-4 min** on arm64 (SUMO sweeps skip individually via the netconvert detector); **~22 s** on Linux where SUMO actually runs. Headline count assumes the **3 tracked bundles** (chicago_1k_car, nyc_10k_car, la_50k_car) — every additional bundle in `scenarios/` adds 36 parametrized data-integrity tests, so generating all 5 standard tiers (`scripts/01..05`) lifts the count to ~549 with proportionally longer wall time (~14 min on M-series Mac). V5+ added `tests/test_turn_restrictions.py` (Phase 7), `tests/test_demand_composition.py` (Phase 10), `tests/test_vehicle_types.py` (Phase 11), and the `TestHBSchoolHelpers` class on `tests/test_parse_model_file.py` (Phase 9). |

Line coverage across `adapters`, `evaluation`, and `pipeline` sits at
**~76 %** (pytest-cov + `branch = true`).  The coverage floor is **70 %**
to leave headroom for ongoing refactoring; the uncovered lines are
concentrated in the subprocess-invoking `run_matsim` path and the
PUMS/modelgen parsers (tested instead by the all-scenarios adapter
sweeps and the engine-smoke tests).
