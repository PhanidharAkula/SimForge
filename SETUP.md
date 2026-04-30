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

# Run the test suite
python -m pytest
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
| `quick_test`       | 1,000   | 7–8 AM   | `scripts/01_chicago_1k_car.py`          |
| `small_commute`    | 10,000  | 7–9 AM   | `scripts/02_nyc_10k_car.py`       |
| `medium_multimodal`| 50,000  | 6–10 AM  | `scripts/03_la_50k_car.py`   |
| `large_full_day`   | 200,000 | 24 h     | `scripts/04_chicago_200k_car.py`      |
| `stress_test`      | 500,000 | 6–10 AM  | `scripts/05_nyc_500k_car.py`         |

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

The two columns of the table above (`Preset` and `Helper script`) are equivalent surfaces — `scripts/0X_*.py` is a thin wrapper that imports `generate_scenario()` and calls it with the same hardcoded kwargs the preset already encodes. The `generate.py --preset <name>` form remains preferred when you need overrides (`--output`, `--seed`, `--city`, `--modes`, `--synthetic`, OSM source mode); the scripts accept `--verbose` / `-v` only.

```bash
# Preset form (preferred — accepts the full override set)
python generate.py --preset chicago_1k_car
python generate.py --preset nyc_10k_car
python generate.py --preset la_50k_car
python generate.py --preset chicago_200k_car
python generate.py --preset nyc_500k_car

# Custom (override any preset field)
python generate.py --city chicago --trips 5000 --modes car
python generate.py --city nyc --trips 10000 --synthetic
python generate.py --preset nyc_10k_car --city la --verbose
python generate.py --list              # Show cities, presets, modes

# Equivalent legacy script form (--verbose / -v only; same generated bundle)
python scripts/01_chicago_1k_car.py [--verbose]
python scripts/02_nyc_10k_car.py [--verbose]
python scripts/03_la_50k_car.py [--verbose]
python scripts/04_chicago_200k_car.py [--verbose]
python scripts/05_nyc_500k_car.py [--verbose]
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
python -m execution.run_benchmark runspecs/benchmark_small.yaml

# Dry run (validate without executing)
python -m execution.run_benchmark runspecs/benchmark_small.yaml --dry-run

# Filter to one scenario
python -m execution.run_benchmark runspecs/benchmark_small.yaml --scenario chicago_1k_car
```

After the benchmark finishes:

```bash
python -m evaluation.analyze_benchmark runs/benchmark_small/benchmark_results_benchmark_small.json
python -m evaluation.generate_plots    runs/benchmark_small/benchmark_results_benchmark_small.json
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

## Third Engine — DTALite (CPU mesoscopic DTA)

DTALite is the third primary engine, replacing the GPU-based LPSim that
was attempted-and-abandoned in Version_4 (see
[`doc/engines/LPSIM_RETROSPECTIVE.md`](doc/engines/LPSIM_RETROSPECTIVE.md)
and [`doc/engines/THIRD_ENGINE_OPTIONS.md`](doc/engines/THIRD_ENGINE_OPTIONS.md)
for the full selection rationale).

| Engine    | Hardware    | Use Case                                |
| --------- | ----------- | --------------------------------------- |
| SUMO      | Any CPU     | Small/medium scenarios, debugging        |
| MATSim    | Any CPU + Java | Activity-based, multi-modal           |
| DTALite   | Any CPU     | Mesoscopic Dynamic Traffic Assignment (UE) |

### Will DTALite run on my Mac?

**Yes.** DTALite ships native arm64 and x86_64 binaries inside the
[`path4gmns`](https://github.com/jdlph/Path4GMNS) Python package. The
full SimForge cross-engine matrix runs on Mac without Pitzer.

### Installing DTALite

DTALite is bundled inside `path4gmns`, which is in `requirements.lock`.
A one-line install gets it:

```bash
uv pip install -r requirements.lock
```

On macOS the bundled binary needs the OpenMP runtime:

```bash
brew install libomp
```

That's it — no compile step, no GPU drivers, no Singularity image.

### Verifying DTALite is staged

```bash
python tools/env_report.py | grep -i dtalite
# dtalite:       /path/to/.venv/lib/python3.13/site-packages/path4gmns/bin/DTALiteMM_arm.dylib
# dtalite pin:   path4gmns==0.10.0 | upstream=https://github.com/jdlph/Path4GMNS
```

### Bumping the pinned version

1. Update `path4gmns==X.Y.Z` in `requirements.lock` and `requirements.txt`
2. Update `lib/dtalite/manifest.json::dtalite.path4gmns_version`
3. Re-run `uv pip sync requirements.lock`
4. Commit all three changes so future installs land on the same binary

### DTALite implementation choice

The adapter calls `path4gmns.DTALiteClassic` (the stable C++ binary in
path4gmns), not the newer `DTALiteMultimodal` wrapper. The multimodal
binary in path4gmns 0.10.0 has a regression demanding a `mode_type.csv`
schema upstream has not published — even path4gmns's own bundled
samples fail with `[ERROR] File mode_type does not have information`
when invoked fresh. See `adapters/dtalite/MAPPING.md` for the full
implementation note.

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

sbatch cluster/jobs/05_nyc_500k_car.sbatch       # or any of cluster/jobs/01..05
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
│   └── dtalite/            #   DTALite adapter (CPU mesoscopic DTA, path4gmns)
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
├── scripts/                # Per-tier scenario generation (01_chicago_1k_car.py … 05_nyc_500k_car.py)
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
