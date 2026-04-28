# project notes

This file provides guidance to local tooling (claude.ai/code) when working with code in this repository.

## Project context

SimForge is a Master's thesis artefact: a reproducible, cross-simulator benchmarking framework that runs the same scenario through SUMO, MATSim, and DTALite. The "fair comparison" claim is the core thesis contribution and is enforced by code (the SCC + feasibility filter), tests, and a post-run audit. Don't undermine it. The thesis defense is the load-bearing deadline; treat changes that affect the locked benchmark numbers conservatively.

Active dev branch: `Version_5_dtalite` (DTALite replaced LPSim in V5 — see `doc/engines/LPSIM_RETROSPECTIVE.md`). `main` tracks the released thesis snapshot.

## Environment

Python 3.13 + `uv`. The lockfile pulls every Python dep **including SUMO** (`eclipse-sumo` wheel):

```bash
uv pip install -r requirements.lock
python tools/download_osm.py    # hash-pinned PBFs (~2.1 GB)
```

Extra system deps:
- Java 17+ for MATSim (`brew install openjdk@17` on macOS).
- `libomp` for DTALite OpenMP runtime on macOS (`brew install libomp`). DTALite is bundled inside `path4gmns`; no separate build.
- `setup_simforge.py` is the one-shot bootstrap; `tools/env_report.py` prints a cross-machine parity report.

## Common commands

```bash
# Tests
python -m pytest                            # full suite (~3-4 min arm64 / ~22 s Linux)
python -m pytest tests/test_feasibility.py  # one file
python -m pytest -k "scc or feasibility"    # substring filter on test names
python -m pytest -m determinism             # marker filter
python -m pytest --cov --cov-fail-under=70  # enforce coverage floor

# Validate a scenario bundle
python -m pipeline.validation.validate_bundle scenarios/<name>

# Generate a scenario (canonical bundle: GMNS network + demand + signals + manifest)
python generate.py --city chicago --trips 1000 --output scenarios/chicago_1k_demo
python generate.py --preset quick_test       # 5 presets: quick_test/small_commute/medium_multimodal/large_full_day/stress_test
python scripts/01_quick_test.py [--verbose]  # thin wrapper around the preset; only --verbose / -v
# Prefer --preset for other overrides (--output, --seed, --city, --modes, --synthetic, OSM source mode).

# Two execution paths — see the Architecture section
python run.py --scenario chicago_1k_car --engine sumo,matsim --mode meso --repeats 5
python -m execution.run_benchmark runspecs/stress_test.yaml

# Post-run pipeline (canonical 3-step)
python -m evaluation.analyze_benchmark <run-dir>/<results>.json --latex --markdown
python -m evaluation.audit_fairness    <run-dir>
python -m evaluation.generate_plots    <run-dir>/<results>.json --output doc/figures

# In-CLI help system (paste-safe topic descriptions)
python help.py                       # topic index
python help.py run | benchmark | tests | results | architecture
```

## Architecture

### Cross-engine fairness contract (load-bearing — verified by `audit_fairness`)

A single canonical bundle (`scenarios/<id>/`) is the source of truth. Each adapter (`adapters/{sumo,matsim,dtalite}/`) reads the same bundle, applies the **same** SCC + feasibility filter (`pipeline/network/scc.py`, `adapters/common/feasibility.py`), and writes a per-engine `feasibility_report.json` proving the trip-set sent to its engine. `evaluation/audit_fairness.py` checks Q1–Q4 across all three engines:

- **Q1** byte-identical feasible-trip set
- **Q2** SCC-filtered nodes/links match
- **Q3** simulated trip count = feasibility target
- **Q4** cross-engine travel-time spread (paradigm signal)

Don't bypass the SCC/feasibility filter in any adapter — it is the only thing that makes the cross-engine numbers comparable. The audit is mutation-tested (`doc/MUTATION_BASELINE.md` pins `adapters/common/feasibility.py` and `pipeline/network/scc.py`).

### Two execution paths (different output layouts, same adapters)

Both `run.py` and `python -m execution.run_benchmark <runspec.yaml>` ultimately call the same `adapters/<engine>/` code, so per-cell engine artefacts (`tripinfo.xml`, `output_trips.csv.gz`, `link_performance.csv`, `feasibility_report.json`) are identical. The wrapping differs:

| Aspect              | `run.py`                                       | `run_benchmark.py`                             |
| ------------------- | ---------------------------------------------- | ---------------------------------------------- |
| Matrix source       | CLI flags                                      | locked YAML in `runspecs/`                     |
| Per-cell dir        | flat `<scenario>_<engine>_<mode>_seed<N>/`     | nested `<scenario_id>/<engine>/seed_<N>/`      |
| Summary JSON        | `benchmark_results.json`                       | `benchmark_results_<runspec>.json`             |
| JSON top-level keys | `timestamp, matrix, summary, results`          | `runspec_name, started_at, completed_at, total_runs, successful_runs, failed_runs, summary, results` |
| Used for            | ad-hoc / one-off                               | reproducible thesis numbers, sbatch wrappers   |

`evaluation/audit_fairness.py` auto-detects four output layouts (flat, nested, sbatch-nested-once, sbatch-nested-twice). `analyze_benchmark` and `generate_plots` consume either summary JSON. Full side-by-side: `doc/RESULTS_GUIDE.md` §2. Don't unify the two paths without checking `audit_fairness`'s detector.

### Module map (when reading is faster than greping)

- `adapters/{sumo,matsim,dtalite}/` — engine-specific input prep + run + output parse. `adapters/common/feasibility.py` is shared.
- `pipeline/` — bundle generation primitives: `network/` (OSM fetch + canonical GMNS graph + SCC), `demand/` (census/ModelGen-driven trips), `signals/`, `validation/`, `progress.py` (StickyProgress + the older ProgressBar; the `_STICKY_ACTIVE` flag silences the latter when the former is alive).
- `execution/` — runspec dataclasses + benchmark harness.
- `evaluation/` — `analyze_benchmark`, `audit_fairness`, `compare_modes`, `generate_plots`, plus `metrics/` (travel time, fidelity, reproducibility R = 1 − CV, scalability, Student's-t 95% CI).
- `runspecs/` — locked YAML matrices. `stress_test.yaml` is the canonical thesis matrix; `benchmark_{small,large}.yaml` are tier variants.
- `cluster/jobs/` — Pitzer SLURM sbatch wrappers (`benchmark_small.sbatch`, `05_stress_test.sbatch`, etc.).
- `doc/` — `ARCHITECTURE.md` (data flow), `RESULTS_GUIDE.md` (post-run pipeline + JSON schemas), `REPRODUCING.md` (end-to-end recipe), `PITZER.md` (HPC), `EXPERIMENT_LOG.md` (chronological run journal), `engines/LPSIM_RETROSPECTIVE.md`.

### Hash-pinned data provenance

`osm_data/manifest.json` pins SHA256 for each state-level PBF. `tools/download_osm.py` will skip files whose hash already matches. Don't replace PBFs without updating the manifest.

## Conventions and invariants

- **Coverage floor 70 %** (currently ~76 %), enforced via `--cov-fail-under=70` when `--cov` is passed. Coverage scope is `adapters/`, `evaluation/`, `pipeline/` only — see `pyproject.toml` `[tool.coverage]`.
- **Test markers** (registered in `pyproject.toml`, `--strict-markers`): `integration`, `requires_sumo`, `requires_java`, `requires_gpu`, `determinism`. Adding a new marker requires registering it.
- **Don't add try/except around `pipeline/`, `adapters/`, or `evaluation/` paths to "make it more robust"** (per `CONTRIBUTING.md`). A silently-swallowed adapter failure produces a `benchmark_results_*.json` with subtly wrong numbers that look fine. Crash loudly; the harness records the failure.
- **Determinism**: SUMO meso/micro and DTALite UE are byte-deterministic with a fixed seed. MATSim is deterministic only with `lastIteration=0`. The `determinism` test marker enforces byte-identical adapter outputs across re-runs — don't introduce non-determinism (atomic reductions, hash-iteration ordering, time-based seeds).
- **Engine/mode compatibility**: SUMO supports meso + micro; MATSim and DTALite are mesoscopic only. `run.py` uses `ENGINE_SUPPORTED_MODES` to skip invalid pairs. `run_benchmark.py` trusts the runspec rows.
- **No CI**: `python -m pytest` is the gate. The full suite is expected to pass before any merge. Apple Silicon arm64 has historical `netconvert` segfaults on large networks; the SUMO-dependent tests skip individually via `is_arm64_netconvert_crash` in `tests/conftest.py` so the suite stays green.
- **DTALite import banner**: `path4gmns` prints a `path4gmns, version 0.10.0` line at import. The adapter (`adapters/dtalite/dtalite_adapter.py`) suppresses it via stdout redirect — don't reintroduce a bare `import path4gmns` at module top.

## Documentation pointers

- `README.md` — top-level overview + quick start.
- `SETUP.md` — manual install path when `setup_simforge.py` doesn't fit.
- `TESTING.md` — full test layout per file with counts and what they cover.
- `CONTRIBUTING.md` — development workflow, branch policy, change-bar for schema/adapter/evaluation work.
- `doc/REPRODUCING.md` — exact recipe for thesis numbers (canonical stress_test runspec).
- `doc/RESULTS_GUIDE.md` §2 — `run.py` vs `run_benchmark.py` side-by-side.
- `doc/PITZER.md` — HPC workflow, sbatch templates.
- `help.py <topic>` — paste-safe in-CLI help system.
