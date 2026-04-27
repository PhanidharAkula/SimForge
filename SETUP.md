# SimForge Setup Guide

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [OSM Data](#osm-data)
4. [Scenario Data](#scenario-data)
5. [Running Simulations](#running-simulations)
6. [Understanding the Output](#understanding-the-output)
7. [GPU Acceleration](#gpu-acceleration)
8. [HPC / Supercomputer](#hpc--supercomputer)
9. [Command Reference](#command-reference)
10. [Project Structure](#project-structure)
11. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

| Software   | Version          | Installation                                              |
| ---------- | ---------------- | --------------------------------------------------------- |
| **uv**     | 0.4+             | `curl -LsSf https://astral.sh/uv/install.sh \| sh`        |
| **Java**   | 17+              | `brew install openjdk@17` (required only for MATSim)      |
| **Git**    | 2.30+            | Usually pre-installed                                     |

`uv` manages Python and the venv; **Python itself does not need to be pre-installed**. SUMO (the simulator binary) is installed automatically via [`requirements.lock`](requirements.lock) — no separate `brew install sumo` step.

### Verify Prerequisites

```bash
uv --version        # 0.4+
java -version       # openjdk 17.x or newer
```

---

## Installation

The canonical install path uses `uv` and the **fully-pinned `requirements.lock`** so every machine ends up on byte-identical dep versions (Python 3.13.13 + 42 packages, including `eclipse-sumo==1.26.0`).

```bash
git clone <repo-url>
cd SimForge

# uv installs Python 3.13.13 (in user space, no admin) and creates the venv
uv python install 3.13
uv venv --python 3.13 .venv
source .venv/bin/activate

# One command resolves every Python dep + SUMO at the locked versions
uv pip install --upgrade pip
uv pip install -r requirements.lock
```

Then download the MATSim 15.0 JAR (gitignored under `lib/`):

```bash
mkdir -p lib
curl -L -o matsim-15.0-release.zip https://github.com/matsim-org/matsim-libs/releases/download/15.0/matsim-15.0-release.zip
unzip matsim-15.0-release.zip -d lib/       # extracts to lib/matsim-15.0/
rm matsim-15.0-release.zip
```

> **Why `requirements.lock` not `requirements.txt`?** `requirements.txt` lists loose pin ranges suitable for development; `requirements.lock` records exact transitive versions captured from the canonical thesis-build environment. Installing from the lockfile guarantees you get the same stack used to produce the recorded thesis bundles. See [doc/REPRODUCING.md §Cross-Platform Reproducibility](doc/REPRODUCING.md#cross-platform-reproducibility-verified) for the verification recipe.

### Verify Installation

```bash
# Toolchain + dep + binary report — same output expected on any locked machine
python tools/env_report.py

# Fast unit suite
python -m pytest tests/ -m "not slow" -q
```

`env_report.py` prints Python version, all 12 watched dep versions, SUMO/Java/MATSim binary status, and counts of OSM PBFs / ModelGen files / scenarios. It's the canonical cross-platform parity check (run it on any second machine and `diff` the outputs to verify they match).

---

## OSM Data

SimForge generates road networks from **hash-pinned OSM PBF snapshots** rather than live Overpass API queries. The PBFs live under `osm_data/`, each tracked by an entry in [`osm_data/manifest.json`](osm_data/manifest.json) that pins a SHA-256 hash for reproducibility.

### Why local PBFs

| Path           | Reproducibility                  | Speed (city-scale bbox) | Reliability                                  |
| -------------- | -------------------------------- | ----------------------- | -------------------------------------------- |
| Local PBF      | ✅ SHA-256 pinned, byte-identical | 30 – 90 s               | ✅ Deterministic — no rate limits             |
| Overpass (API) | ⚠️ Upstream OSM is a moving target | 5 – 30+ min             | ⚠️ Rate-limited; stalls on NYC-sized bboxes   |

The Overpass path still exists as a fallback in `pipeline/network/build_network_from_osm.py` for cities without a committed PBF, but every bundled city (`chicago`, `nyc`, `la`) ships with a matching state-level PBF entry in the manifest.

### Download the PBFs

The PBFs themselves are **gitignored** (348 MB – 1.3 GB each, too large for git). Fetch them on first install:

```bash
python tools/download_osm.py
```

That script reads `osm_data/manifest.json`, downloads any missing file from Geofabrik, and refuses to proceed on a SHA-256 mismatch. Re-running is cheap — it just verifies existing files' hashes.

| File                                 | Size    | Covers                        | Used by   |
| ------------------------------------ | ------- | ----------------------------- | --------- |
| `osm_data/illinois-2026-04-22.osm.pbf`  | 348 MB  | State of Illinois             | `chicago` |
| `osm_data/new-york-2026-04-22.osm.pbf`  | 489 MB  | State of New York             | `nyc`     |
| `osm_data/california-2026-04-22.osm.pbf` | 1.3 GB | State of California           | `la`      |

Total: ~2.1 GB. Re-download only needed if the manifest is updated (rare — `downloaded_on` is pinned).

### How the PBF is consumed

`generate.py` passes the city's `pbf_file` into `pipeline/network/build_network_from_osm.py::build_network_from_osm`, which delegates to `pipeline/network/load_network_from_pbf.py`:

1. **pyosmium** scans the state PBF and writes a bbox-clipped `.osm` XML file with every `highway=*` way plus every node those ways reference (via `BackReferenceWriter` — the equivalent of `osmium extract -b ...` via the Python API).
2. **osmnx** (`graph_from_xml`) parses the XML into a `MultiDiGraph` with the same attributes the Overpass path produced.
3. **osmnx** (`truncate.truncate_graph_bbox`) clips edges that bleed past the requested bbox.

The result is schema-identical to what the Overpass path returned — downstream canonical extraction is unchanged.

---

## Scenario Data

### Bundled Scenarios

One small scenario is committed to the repo so the test suite and the default `run.py` invocation work out of the box:

| Scenario          | City    | Trips | Modes | Bundle size |
| ----------------- | ------- | ----- | ----- | ----------- |
| `chicago_1k_car`  | Chicago | 1,000 | car   | ~1 MB       |

Larger scenarios are not committed — generate them locally with the helper scripts below.

### Generation Tiers

| Preset             | Trips   | Horizon  | Helper script                       |
| ------------------ | ------- | -------- | ----------------------------------- |
| `quick_test`       | 1,000   | 7–8 AM   | `scripts/01_quick_test.py`          |
| `small_commute`    | 10,000  | 7–9 AM   | `scripts/02_small_commute.py`       |
| `medium_multimodal`| 50,000  | 6–10 AM  | `scripts/03_medium_multimodal.py`   |
| `large_full_day`   | 200,000 | 24 h     | `scripts/04_large_full_day.py`      |
| `stress_test`      | 500,000 | 6–10 AM  | `scripts/05_stress_test.py`         |

### Data Sources

| File         | Source                      | Description                                |
| ------------ | --------------------------- | ------------------------------------------ |
| network.xml  | **OpenStreetMap (OSM)**     | Real road network topology                 |
| demand.csv   | **Census** (default) or **Synthetic** | PUMS-calibrated or gravity model |
| signals.xml  | **Inferred from OSM**       | Signal timing inferred from intersection geometry |
| config.xml   | **Created**                 | Simulation parameters (seed, duration)     |
| manifest.xml | **Created**                 | SHA-256 checksums and metadata             |

### Demand Modes

`generate.py` uses **census-calibrated demand by default** (ModelGen PUMS microdata for population-weighted origins and commute-time-calibrated trip distances). Pass `--synthetic` to fall back to the gravity model.

### Generating Scenarios

```bash
# Preset scripts (one-shot)
python scripts/01_quick_test.py        # 1K car, Chicago
python scripts/02_small_commute.py     # 10K car, NYC
python scripts/03_medium_multimodal.py # 50K car+transit+bike, LA
python scripts/04_large_full_day.py    # 200K car+transit, Chicago
python scripts/05_stress_test.py       # 500K car, NYC

# Or generate.py directly
python generate.py --preset quick_test
python generate.py --city chicago --trips 5000 --modes car
python generate.py --city nyc --trips 10000 --synthetic
python generate.py --list              # Show cities, presets, modes
```

See [doc/SCENARIO_GENERATION.md](doc/SCENARIO_GENERATION.md) for what each tier produces and how realism is measured.

### Validating Scenarios

```bash
python -m pipeline.validation.validate_bundle scenarios/chicago_1k_car
```

### Cleaning Caches

```bash
tools/clean.sh           # Wipe Python bytecode (__pycache__, *.pyc, .pytest_cache)
tools/clean.sh --all     # Also wipe cache/ (only populated if the Overpass fallback ran)
```

`tools/clean.sh` never touches `osm_data/` — those PBFs are the provenance anchor and should only be removed by editing the manifest.

---

## Running Simulations

### Quick Start

```bash
python run.py --scenario chicago_1k_car --engine sumo --mode meso
python run.py --list
python run.py                                 # All bundled scenarios × all installed engines
```

### Run Benchmark from RunSpec

```bash
# Canonical 4-cell stress test (matches the thesis figures)
python -m execution.run_benchmark runspecs/stress_test.yaml

# Dry run (validate without executing)
python -m execution.run_benchmark runspecs/stress_test.yaml --dry-run

# Filter to one scenario
python -m execution.run_benchmark runspecs/stress_test.yaml --scenario chicago_1k_car
```

After the benchmark finishes:

```bash
python -m evaluation.analyze_benchmark runs/stress_test/benchmark_results_stress_test.json
python -m evaluation.generate_plots    runs/stress_test/benchmark_results_stress_test.json
```

### Run Individual Adapter CLI

```bash
python -m adapters.sumo.cli   scenarios/chicago_1k_car runs/chicago_sumo
python -m adapters.matsim.cli scenarios/chicago_1k_car runs/chicago_matsim
```

---

## Understanding the Output

### Key Metrics

| Dimension           | Metric     | Formula                  | Purpose                  |
| ------------------- | ---------- | ------------------------ | ------------------------ |
| **Fidelity**        | RMSE       | √(Σ(sim−obs)²/n)         | Accuracy vs ground truth |
| **Fidelity**        | GEH        | √(2(sim−obs)²/(sim+obs)) | Traffic count comparison |
| **Fidelity**        | KS         | max\|F_sim − F_obs\|     | Distribution similarity  |
| **Scalability**     | Runtime    | Wall-clock seconds       | How fast it runs         |
| **Scalability**     | Throughput | vehicles/sec/core        | Efficiency per core      |
| **Reproducibility** | R          | 1 − σ/μ                  | Run-to-run consistency   |

For a tour of every figure produced by `generate_plots.py`, see [doc/RESULTS_GUIDE.md](doc/RESULTS_GUIDE.md).

---

## GPU Acceleration

LPSim is the 3rd primary engine ([Xuan-1998/LPSim](https://github.com/Xuan-1998/LPSim), MIT, GPU mesoscopic). Build it once on a Pitzer GPU node via `sbatch cluster/jobs/build_lpsim.sbatch`. Without that build the LPSim adapter records a clean failure (it does **not** fall back to CPU silently — that was the QarSUMO trap we want to avoid).

| Engine    | Hardware    | Use Case                          |
| --------- | ----------- | --------------------------------- |
| SUMO      | Any CPU     | Small/medium scenarios, debugging |
| MATSim    | Any CPU     | Activity-based, multi-modal       |
| LPSim     | NVIDIA CUDA | Large-scale mesoscopic on GPU     |

---

## HPC / Supercomputer

For running on the Ohio Supercomputer Center's Pitzer cluster (the target HPC for the 50K – 500K scenarios), see the dedicated guide:

- **[doc/PITZER.md](doc/PITZER.md)** — SSH setup, module loads, PBF transfer via rsync, SLURM job templates per tier, job monitoring, and troubleshooting.

Short version:

```bash
ssh pitzer
cd ~ && git clone -b Version_3 https://github.com/PhanidharAkula/SimForge.git
cd SimForge

# Install uv (manages Python + venv; user-space, no admin)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env
uv python install 3.13                          # Pitzer modules only offer 3.10/3.12

module load openjdk/21.0.3_9                     # for MATSim — Pitzer's lmod requires an explicit version
uv venv --python 3.13 .venv && source .venv/bin/activate
uv pip install -r requirements.lock             # 42 packages including SUMO

# Ship PBFs + ModelGen from your local machine (from local, not Pitzer):
rsync -avh osm_data/ pitzer:SimForge/osm_data/
rsync -avh modelgen/ pitzer:SimForge/modelgen/

sbatch cluster/jobs/05_stress_test.sbatch       # or any of cluster/jobs/01..05
```

---

## Command Reference

| Command                                                | Description                                |
| ------------------------------------------------------ | ------------------------------------------ |
| `python setup_simforge.py`                             | One-command bootstrap (venv + deps + JAR) |
| `python run.py`                                        | Main CLI — run all or filtered simulations |
| `python run.py --list`                                 | Show available scenarios/engines/modes     |
| `python run.py --validate-only`                        | Validate scenario bundles only             |
| `python -m execution.run_benchmark <runspec>`          | Run benchmark from YAML spec               |
| `python -m pipeline.validation.validate_bundle <path>` | Validate a single bundle                   |
| `python generate.py --preset <name>`                   | Generate a scenario from a preset         |
| `python -m evaluation.analyze_benchmark <results.json>` | Print stats + coverage diagnostic         |
| `python -m evaluation.generate_plots    <results.json>` | Render the 9 thesis figures               |
| `tools/clean.sh [--all]`                             | Wipe regenerable caches                    |
| `python -m pytest tests/ -v`                           | Run the test suite (~434 tests)            |

---

## Project Structure

```
SimForge/
├── adapters/               # Simulator-specific converters
│   ├── sumo/               #   SUMO adapter (micro + meso)
│   ├── matsim/             #   MATSim adapter
│   └── lpsim/              #   LPSim adapter (GPU mesoscopic)
├── canonical/              # Schema documentation (v0)
├── doc/                    # Architecture, reproduction, thesis chapters
├── evaluation/             # Metrics, analysis, plots
│   └── metrics/            #   Fidelity, scalability, reproducibility
├── execution/              # Benchmark harness
│   ├── run_benchmark.py    #   Orchestrates full benchmark runs
│   └── runspec.py          #   RunSpec / RunConfig schema
├── lib/                    # External JARs (MATSim) — gitignored
├── osm_data/               # Hash-pinned OSM PBF snapshots (gitignored binaries)
│   └── manifest.json       #   SHA-256 + URL + coverage per state PBF
├── pipeline/               # Data generation pipeline
│   ├── network/            #   OSM (PBF or Overpass) → canonical network
│   ├── demand/             #   Synthetic + census demand generation
│   ├── signals/            #   Traffic signal inference
│   └── validation/         #   Bundle validators
├── scripts/                # Per-tier scenario generation (01_quick_test.py … 05_stress_test.py)
├── tools/                  # Operator utilities (clean.sh, download_osm.py)
├── runspecs/               # Benchmark YAML configurations
├── scenarios/              # Bundled canonical scenarios
├── tests/                  # 406 unit & integration tests
├── run.py                  # Convenience CLI
├── generate.py             # Scenario generator entry point
├── setup_simforge.py       # One-command bootstrap
├── requirements.txt        # Python dependencies (osmium, osmnx, lxml, …)
└── SETUP.md                # This file
```

---

## Troubleshooting

| Problem                | Solution                                                          |
| ---------------------- | ----------------------------------------------------------------- |
| `MATSim JAR not found`                          | Re-run `python setup_simforge.py`, or run the manual `curl` above                                     |
| `SUMO not found`                                | `brew install sumo`                                                                                    |
| `Java not found`                                | `brew install openjdk@17`                                                                              |
| `FileNotFoundError: osm_data/<state>.osm.pbf`   | Run `python tools/download_osm.py` — fetches + SHA-256-verifies every PBF in the manifest            |
| `ImportError: osmium`                           | `pip install 'osmium>=4.0'` (not `pyrosm`; that package no longer builds on Python 3.13+)              |
| Overpass fallback hangs                         | Prefer the PBF path — add the city's `pbf_file` to `generate.py::CITIES` and update the manifest       |
| `No scenarios found`                            | Run a script in `scripts/` first, or check `python run.py --list`                                      |
| Large `cache/` folder                           | `tools/clean.sh --all` to wipe the Overpass HTTP cache (no effect on the pinned PBFs in `osm_data/`) |
