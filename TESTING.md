# SimForge Test Suite

**406 tests** across **18 test files** covering adapters, metrics, validation,
data integrity, end-to-end pipeline, the canonical SCC algorithm, the shared
feasibility filter, the mode-aware benchmark analyser, OSM network fetching
(mocked), demand generators, and real-binary engine smoke tests.

Pytest configuration lives in `pyproject.toml` (`[tool.pytest.ini_options]`)
with strict-marker enforcement, `testpaths = ["tests"]`, and `--tb=short`.
Coverage thresholds are enforced by `pytest-cov` (≥70 % floor, currently
**76 %** — see `[tool.coverage]` in `pyproject.toml`).  Shared
scenario-discovery, hashing, and arm64-skip helpers live in
`tests/conftest.py`.

The project ships without a hosted CI workflow — `python -m pytest` is the
authoritative gate and is expected to pass before any merge. On Apple Silicon
the `slow` tier is gated by the real-binary `netconvert` segfault documented
below; skip it with `-m "not slow"` for the fast developer loop. Mutation
testing against the two cross-engine-fairness modules is documented in
[`doc/MUTATION_BASELINE.md`](doc/MUTATION_BASELINE.md).

---

## Quick start

```bash
source .venv/bin/activate

# Fast tier — everything except whole-suite adapter sweeps and real-binary
# smoke.  ~12 s including coverage.
python -m pytest -m "not slow"

# Full suite (includes slow sweeps and any available real-binary smoke).
# ~22 s on M-series.
python -m pytest

# Stop on first failure, verbose output.
python -m pytest -v -x

# One file or one class.
python -m pytest tests/test_feasibility.py
python -m pytest tests/test_scenario_data_integrity.py::TestNetworkIntegrity

# Substring filter on test names.
python -m pytest -k "scc or feasibility"

# Marker filters (registered in pyproject.toml).
python -m pytest -m slow
python -m pytest -m determinism
python -m pytest -m "integration and not slow"
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
| `slow`            | Test takes > 2 s or sweeps every bundled scenario            |
| `integration`    | Exercises multiple subsystems end-to-end                      |
| `determinism`    | Verifies byte-identical adapter outputs across re-runs        |
| `requires_sumo`  | Needs the SUMO `netconvert` / `sumo` binaries on PATH         |
| `requires_java`  | Needs Java + the MATSim JAR (`lib/matsim-15.0/`)              |

The `requires_*` markers are advisory today (no auto-skip plumbing yet) — they
let contributors filter explicitly with `-m "not requires_java"`.

---

## Test files

### 1. `test_adapter_determinism.py` — Determinism (8 tests, `@determinism`)

Two runs of `prepare_sumo_inputs` on the same scenario must produce
byte-identical output (modulo netconvert's embedded timestamp on `net.net.xml`).
Catches hash-randomised dict iteration, float summation order, and timestamp
leaks into XML.

### 2. `test_sumo_adapter.py` — SUMO Adapter (4 tests; sweep `@slow`)

Validates the SUMO input bundle (`net.net.xml`, `routes.rou.xml`,
`toy.sumocfg`), edge-length attribution, and lane-length sanity (catches
missing geo projection). The all-scenarios sweep is `@slow`.

### 3. `test_matsim_adapter.py` — MATSim Adapter (24 tests; sweep `@slow`)

Tests the MATSim adapter's helpers (`seconds_to_time_string`, `MATSimConfig`,
vehicles XML, network XML, plans XML, config XML) and the full
`prepare_matsim_inputs` pipeline. No Java/JAR required.

### 4. `test_fidelity_metrics.py` — Fidelity Metrics (21 tests)

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

### 10. `test_scenario_data_integrity.py` — Data Integrity (70 tests)

**Critical.** Parametrized over every complete scenario in `scenarios/`. With
the two bundled scenarios this expands to 70 tests across:

| Class                  | What it checks                                                     |
| ---------------------- | ------------------------------------------------------------------ |
| `TestFileExistence`    | All 5 canonical files exist                                         |
| `TestXMLParsing`       | All XML files are well-formed                                       |
| `TestNetworkIntegrity` | Unique node/link IDs, valid WGS84 coords, valid endpoints, +length/speed/lanes |
| `TestDemandIntegrity`  | Required columns, unique trip IDs, all OD nodes exist, sane departures, valid modes |
| `TestConfigIntegrity`  | Metadata, scenario_id matches dir, valid time horizon, units, seed |
| `TestManifestIntegrity`| Manifest ID matches config, all declared files exist               |
| `TestSignalsIntegrity` | All junction node references exist in the network                  |

### 11. `test_pipeline_e2e.py` — End-to-End Pipeline (20 tests; some `@integration` + `@slow`)

| Class                         | What it checks                                                         |
| ----------------------------- | ---------------------------------------------------------------------- |
| `TestValidatorCatchesBadData` | 13 corruption scenarios — missing/corrupt files, bad columns, bogus nodes, etc. |
| `TestSUMOAdapterRobustness`   | All-scenarios sweep, route-edge consistency, tripinfo configured       |
| `TestNetworkRouting`          | BFS correctness on synthetic graphs and ≥80 % real-network routability |

### 12. `test_scc.py` — Canonical SCC (16 tests, NEW)

Iterative Kosaraju on synthetic graphs (empty, singleton, 2-cycle, chain,
multiple components, classic Cormen example, 5 000-node deep chain) plus
`parse_network` (well-formed, self-loop drop, malformed XML rejection) and
real bundled-network coverage (≥95 %).

### 13. `test_feasibility.py` — Cross-engine feasibility filter (16 tests, NEW)

The shared SCC-based filter that makes SUMO and MATSim simulate the
**same** trip subset (CHANGELOG 1.0.0 fix). Covers feasible-trip computation,
all four drop reasons (outside-SCC, unknown-node, missing-fields, missing-column-in-CSV),
`FeasibilityReport` math (`feasible_fraction`, `summary_line`, `to_dict`),
JSON persistence, log-level routing, manifest path resolution, and
end-to-end ≥99 % feasibility on the bundled scenario.

### 14. `test_analyze_benchmark.py` — Benchmark analyser (25 tests)

The mode-aware grouping and identity-resolution logic that prevents the
silent R-score collapse that was fixed in [1.0.0]. Covers `_resolve_identity`
explicit + scenario_id-fallback paths for all engines, `compute_reproducibility`
edge cases (single-value, identical, low/high variance, zero-mean), and the
mode-aware grouping itself (meso vs micro stay separate, failed runs recorded,
zero-TT outliers filtered, both `runs` and `results` keys accepted).  Also
exercises every renderer — `print_runtime_table`, `print_reproducibility_table`,
`print_summary_table`, `print_coverage_report` (asymmetric + thin-cell
diagnostics), and the LaTeX/Markdown table generators.

### 15. `test_osm_fetch.py` — OSM network fetching (20 tests, NEW)

Fully mocked Overpass/osmnx pipeline.  `BoundingBox` validation (inverted
lat/lon, from_string arity, from_center geometry), cache folder pinning to
`<repo>/cache`, error translation (ConnectionError → RuntimeError with a
"possible causes" block), empty-result guard (`ValueError`), missing-osmnx
guard (`ImportError`), and the `PREDEFINED_CITIES` catalogue.  Also
round-trips `extract_canonical_network` and the full
`build_network_from_osm` end-to-end against a stub graph so XML output is
verified without touching the network.

### 16. `test_demand_generators.py` — Demand generators (21 tests, NEW)

`UniformRandomGenerator`, `GravityModelGenerator`, `PeakHourGenerator`,
`load_network_for_demand`, and the top-level `generate_synthetic_demand`
dispatch.  Proves SCC restriction on synthetic grids (dead-end nodes
excluded from OD sampling), deterministic seeding (byte-identical
demand.csv across runs), canonical CSV header, and the peak-hour temporal
profile.  Complements the adapter-level feasibility filter — the two
tests together prove that every emitted trip is routable in the engine.

### 16. `test_engine_smoke.py` — Real-binary smoke (3 tests, NEW)

Actually invokes `sumo`, `netconvert`, and the MATSim JAR on the bundled
scenario and asserts the engine produced non-empty artefacts
(`tripinfo.xml`, `output_trips.csv.gz`).  Both binary-driven smoke tests
`pytest.skip` gracefully when the binary is missing so `pytest -m "not
slow"` stays green on a developer laptop without SUMO/Java installed.
Catches the class of regression where the adapter writes files the engine
refuses to parse — something no amount of XML-structure assertions can
see.

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
| SUMO / MATSim determinism | 8    | Byte-identical tripinfo across re-runs                      |
| MATSim Adapter         | 24      | Helpers, builders, prepare path, sweep                      |
| Fidelity Metrics       | 21      | RMSE, GEH, KS, combined                                     |
| Travel Time            | 2       | Tripinfo parser                                             |
| Reproducibility        | 15      | R-score core, multi-KPI, thresholds                         |
| Scalability            | 8       | Monotonic timer, throughput, comparison                     |
| Validator              | 2       | Real-bundle pass + corruption fail                          |
| Data Integrity         | 35      | 7 classes × the bundled `chicago_1k_car` scenario           |
| E2E Pipeline           | 20      | 13 corruption modes, 3 robustness, 4 routing                |
| SCC algorithm          | 14      | Iterative Kosaraju + bundled-network coverage               |
| Feasibility filter     | 16      | Shared cross-engine trip filter                             |
| Benchmark analyser     | 25      | Mode-aware grouping + identity fallback + renderers         |
| OSM fetch              | 20      | Mocked Overpass, bbox validation, cache pin                 |
| Demand generators      | 21      | Synthetic generators + SCC restriction + seed               |
| Engine smoke           | 3       | Real-binary SUMO/MATSim smoke, skip-gracefully              |
| **Total**              | **~395** | **~22 s** full suite on M-series; **~7 s** with `-m "not slow"` (count scales with the number of committed scenarios — three reference bundles add ~108 parametrized integrity tests on top of the per-module suite) |

Line coverage across `adapters`, `evaluation`, and `pipeline` sits at
**~76 %** (pytest-cov + `branch = true`).  The coverage floor is **70 %**
to leave headroom for ongoing refactoring; the uncovered lines are
concentrated in the subprocess-invoking `run_matsim` path and the
PUMS/modelgen parsers (tested instead by the slow-tier integration
sweep and the engine-smoke tests).
