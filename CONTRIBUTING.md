# Contributing to SimForge

SimForge is a thesis artefact, but the framework is designed to outlive the thesis as a reusable cross-simulator benchmarking harness. Contributions that improve reproducibility, broaden simulator coverage, or sharpen the evaluation tooling are welcome.

This document describes the development workflow, the conventions enforced by the test suite, and the bar for changes that touch the *canonical schema*, the adapters, or the evaluation tooling.

---

## Quick start

```bash
git clone <repo-url>
cd SimForge
python setup_simforge.py        # creates .venv, installs deps, downloads MATSim JAR
source .venv/bin/activate
python -m pytest tests/ -q      # ~477 tests should pass (369 base + 3 × 36 integrity)
```

If `setup_simforge.py` fails, see [SETUP.md](SETUP.md) for the manual install path.

---

## Development workflow

### 1. Branch from `Version_5`

`main` tracks the released thesis snapshot. `Version_5` is the active development branch (succeeded `Version_4` in 2026-04 with the DTALite-as-third-engine swap and the V5 realism phases — JWTRNS mapping fix, OSM-grounded signals, OSM turn restrictions, PUMS-grounded departures, modelgen-grounded trip purposes, and audit-tooling wiring). Base your work on it:

```bash
git checkout Version_5
git pull origin Version_5
git checkout -b your-feature-branch
```

### 2. Write the test first

The ~477-test suite is the only thing standing between a "small fix" and a silently broken adapter. The test layout (per `TESTING.md`):

| Test file                              | Tests | Covers                                                       |
| -------------------------------------- | ----- | ------------------------------------------------------------ |
| `test_adapter_determinism.py`          | 8     | Byte-identical re-runs across all adapters                   |
| `test_sumo_adapter.py`                 | 4     | SUMO adapter input/output shape                              |
| `test_matsim_adapter.py`               | 24    | MATSim adapter, JAR discovery, classpath, config generation |
| `test_dtalite_adapter.py`              | 46    | DTALite adapter — writers, settings, demand-driven zoning, determinism, output parsing |
| `test_fidelity_metrics.py`             | 21    | RMSE, GEH, KS                                                |
| `test_metrics_travel_time.py`          | 2     | tripinfo.xml parser                                          |
| `test_reproducibility_metrics.py`      | 15    | R-score, edge cases (μ → 0)                                  |
| `test_scalability_metrics.py`          | 8     | SimulationTimer, throughput, hardware info                   |
| `test_validator.py`                    | 2     | Bundle validator (manifest + referential integrity)          |
| `test_scenario_data_integrity.py`      | 35    | Per-bundle hash, manifest, SCC, demand integrity             |
| `test_pipeline_e2e.py`                 | 20    | OSM fetch → bundle → adapter → metrics                       |
| `test_scc.py`                          | 14    | Iterative Kosaraju + bundled-network coverage                |
| `test_feasibility.py`                  | 16    | Shared SCC-based cross-engine trip filter                    |
| `test_analyze_benchmark.py`            | 24    | Mode-aware grouping, renderers (incl. Adj TT), intersection helpers |
| `test_osm_fetch.py`                    | 20    | OSM/Overpass fetch (mocked), bbox validation, cache pinning  |
| `test_demand_generators.py`            | 21    | Uniform / gravity / peak-hour generators, SCC-restricted OD |
| `test_engine_smoke.py`                 | 3     | Real-binary SUMO/MATSim smoke (skip if missing)              |

If you change adapter behaviour, run the determinism tests *and* the relevant adapter tests — the determinism tests catch silent file-format regressions that the adapter unit tests miss.

### 3. Run the canonical stress test

If your change could affect benchmark numbers, regenerate the headline matrix and confirm it still produces the values published in `CHANGELOG.md` (most recent addendum):

```bash
python -m execution.run_benchmark runspecs/benchmark_small.yaml
python -m evaluation.analyze_benchmark runs/benchmark_small/benchmark_results_benchmark_small.json
```

If the numbers move, file the new numbers as a new `CHANGELOG.md` entry — do not silently shift the published table.

### 4. Open a pull request

PR description should include:

- One-sentence summary of the user-visible change.
- Test counts before/after if you added/modified tests.
- A `runs/benchmark_small/benchmark_results_benchmark_small.json` diff (or "no benchmark impact") if you touched the adapter, scenario pipeline, or evaluation code.

---

## Code conventions

### Python

- **Python 3.10+** (the test bench uses 3.13.2). Type hints are encouraged but not enforced.
- **Black-compatible formatting**: 88-column lines, double-quoted strings.
- **Imports**: stdlib → third-party → first-party, grouped with blank lines.
- **No comments without a "why"**: avoid restating what the code does. Comments earn their place when they document a non-obvious constraint, a workaround, or a hidden invariant.

### File-based execution only

SimForge adapters are intentionally file-based: input XMLs in, output XMLs/JSONs out. **Do not introduce TraCI, Py4J, or other live-protocol bindings** — they break byte-identical determinism and complicate the audit trail. If you need runtime interaction, write the events to disk and parse them post-hoc.

### Determinism is non-negotiable

Every adapter run with the same `(scenario, seed)` MUST produce byte-identical output. The `test_adapter_determinism.py` tests will catch:

- Timestamps embedded in output files (use the seed-derived deterministic time instead).
- Hash-randomised dict iteration order leaking into XML attribute order.
- Floating-point summation order (use `sorted()` before reducing).

### Errors that should crash, do crash

Don't add try/except around `pipeline/`, `adapters/`, or `evaluation/` code paths to "make it more robust". A silent failure in the adapter is the worst possible outcome — it produces a `benchmark_results_<runspec>.json` with subtly wrong numbers that look fine. Crash loudly; the harness will record the failure in the `runs[]` summary.

---

## Adding a new simulator adapter

The minimum surface area for a new adapter `adapters/<engine>/`:

1. **`<engine>_adapter.py`** with the standard methods:
   - `convert(scenario_dir, output_dir)` — write engine-native input files + `feasibility_report.json`.
   - `run(scenario_dir, output_dir, seed)` — invoke the engine and write its output XMLs.
   - `parse(output_dir)` — return the canonical metric dict.
2. **`cli.py`** — thin argparse wrapper for one-off invocation.
3. **A determinism test** added to `tests/test_adapter_determinism.py`.
4. **A unit test file** `tests/test_<engine>_adapter.py` mirroring the SUMO/MATSim style.
5. **`feasibility_report.json` parity** — your adapter MUST drop trips outside the SCC and record the drop in the report. This is what makes cross-engine comparison fair.

Update `runspecs/benchmark_small.yaml` and `evaluation/analyze_benchmark.py`'s engine list once the adapter is green.

---

## Adding a new scenario tier

Place a generation script in `scripts/` named `NN_<short_name>.py` where `NN` continues the existing 01 – 05 sequence. The script should:

1. Call `generate.py` with the appropriate `--city`, `--trips`, `--modes`, and `--time` flags.
2. Write to `scenarios/<scenario_id>/`.
3. Run `python -m pipeline.validation.validate_bundle scenarios/<scenario_id>` at the end and exit non-zero on failure.

Bundles larger than 1K should **not** be committed to the repo. Add the scenario id to `SCENARIO_GENERATION.md` and `SETUP.md` so future contributors know to regenerate it locally.

---

## Documentation changes

The doc set is intentionally consolidated — please don't introduce new top-level `.md` files without a discussion. The current layout:

| Audience            | File                              | Scope                                             |
| ------------------- | --------------------------------- | ------------------------------------------------- |
| Newcomer            | `README.md`                       | Hook + 60-second orientation                      |
| Newcomer            | `SETUP.md`                        | Install + first run                               |
| Newcomer            | `CONTRIBUTING.md`                 | This file                                         |
| Reproducer          | `doc/REPRODUCING.md`              | End-to-end thesis-figure reproduction             |
| Reproducer          | `doc/RESULTS_GUIDE.md`            | Per-figure / per-table interpretation             |
| Implementer         | `doc/ARCHITECTURE.md`             | Subsystem boundaries, data flow                   |
| Implementer         | `doc/SCENARIO_GENERATION.md`      | Canonical bundle anatomy, generator pipeline      |
| Maintainer          | `CHANGELOG.md`                    | Per-commit user-visible change log                 |
| Maintainer          | `TESTING.md`                      | Test layout + per-file counts                     |
| Reader              | `doc/GLOSSARY.md`                 | Acronyms and domain terms                         |
| Thesis              | `doc/chapters/methods.md`         | Chapter 3                                         |
| Thesis              | `doc/chapters/experiments.md`     | Chapter 4                                         |
| Thesis              | `doc/chapters/results.md`         | Chapter 5                                         |

Documentation that duplicates information in another file is technical debt — link, don't restate. If a number appears in two places, only one of them is right after the next change.

---

## Reporting bugs

Open a GitHub issue with:

1. The `benchmark_results_<runspec>.json` snippet (or `feasibility_report.json`) showing the unexpected value.
2. The exact command line you ran.
3. The output of `python -c "import sys, platform; print(sys.version, platform.platform())"` plus `sumo --version` and `java -version`.
4. The commit hash from `git rev-parse HEAD`.

Determinism bugs are highest priority — if `python -m pytest tests/test_adapter_determinism.py` fails on your machine but passes in CI, that is a P0.

---

## Licence and citation

This codebase is the artefact behind the thesis cited in `README.md`. If you use SimForge in published work, please cite the thesis (BibTeX in `doc/REPRODUCING.md` §Citation).
