# SimForge Setup Guide

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Scenario Data](#scenario-data)
4. [Running Simulations](#running-simulations)
5. [Understanding the Output](#understanding-the-output)
6. [GPU Acceleration](#gpu-acceleration)
7. [Command Reference](#command-reference)
8. [Project Structure](#project-structure)
9. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

| Software   | Version | Installation                                                              |
| ---------- | ------- | ------------------------------------------------------------------------- |
| **Python** | 3.10+   | `brew install python@3.13` or system package manager                      |
| **Java**   | 17+     | `brew install openjdk@17` (required for MATSim)                           |
| **SUMO**   | 1.20+   | `brew install sumo` or [download](https://sumo.dlr.de/docs/Downloads.php) |
| **Git**    | 2.30+   | Usually pre-installed                                                     |

### Verify Prerequisites

```bash
python3 --version   # Should be 3.10+
java -version       # Should be 17+
sumo --version      # Should be 1.20+
```

---

## Installation

### Option A — One-Command Bootstrap (recommended)

```bash
git clone <repo-url>
cd SimForge
python3 setup_simforge.py
```

`setup_simforge.py` checks Python/Java/SUMO, creates `.venv/`, installs `requirements.txt`, downloads the MATSim 15.0 JAR into `lib/matsim-15.0/`, and runs a sanity import. After it finishes:

```bash
source .venv/bin/activate
```

### Option B — Manual

```bash
git clone <repo-url>
cd SimForge

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt   # pytest-cov, pytest-xdist, mutmut
```

Then download the MATSim JAR (gitignored under `lib/`):

```bash
mkdir -p lib
curl -L -o matsim-15.0-release.zip https://github.com/matsim-org/matsim-libs/releases/download/15.0/matsim-15.0-release.zip
unzip matsim-15.0-release.zip -d lib/       # extracts to lib/matsim-15.0/
rm matsim-15.0-release.zip
```

### Verify Installation

```bash
python -m pytest tests/ -q                              # 293 tests should pass
python -c "from adapters.sumo.sumo_adapter import SUMOAdapter; print('SUMO: OK')"
python -c "from adapters.matsim.matsim_adapter import find_matsim_jar; print('MATSim:', find_matsim_jar())"
```

---

## Scenario Data

### Bundled Scenarios

Two small scenarios are committed to the repo so the test suite and the default `run.py` invocation work out of the box:

| Scenario          | City    | Trips | Modes | Bundle size |
| ----------------- | ------- | ----- | ----- | ----------- |
| `chicago_1k_car`  | Chicago | 1,000 | car   | ~1 MB       |
| `nyc_1k_car`      | NYC     | 1,000 | car   | ~1 MB       |

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
scripts/clean.sh           # Wipe Python bytecode (__pycache__, *.pyc, .pytest_cache)
scripts/clean.sh --all     # Also wipe cache/ (OSM Overpass HTTP cache)
```

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
# Canonical 8-cell stress test (matches the thesis figures)
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

### QarSUMO

| Mode          | Hardware    | Speedup  | Use Case                   |
| ------------- | ----------- | -------- | -------------------------- |
| CPU (SUMO)    | Any CPU     | Baseline | Small scenarios, debugging |
| GPU (QarSUMO) | NVIDIA CUDA | 10–50×   | Large-scale (500K+ trips)  |

QarSUMO requires NVIDIA GPU with CUDA 11.0+ and ≥8 GB VRAM.
Falls back to CPU SUMO automatically when no GPU is available.

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
| `scripts/clean.sh [--all]`                             | Wipe regenerable caches                    |
| `python -m pytest tests/ -v`                           | Run the 293-test suite                     |

---

## Project Structure

```
SimForge/
├── adapters/               # Simulator-specific converters
│   ├── sumo/               #   SUMO adapter (micro + meso)
│   ├── matsim/             #   MATSim adapter
│   └── qarsumo/            #   QarSUMO (GPU) adapter
├── canonical/              # Schema documentation (v0)
├── doc/                    # Architecture, reproduction, thesis chapters
├── evaluation/             # Metrics, analysis, plots
│   └── metrics/            #   Fidelity, scalability, reproducibility
├── execution/              # Benchmark harness
│   ├── run_benchmark.py    #   Orchestrates full benchmark runs
│   └── runspec.py          #   RunSpec / RunConfig schema
├── lib/                    # External JARs (MATSim) — gitignored
├── pipeline/               # Data generation pipeline
│   ├── network/            #   OSM → canonical network
│   ├── demand/             #   Synthetic + census demand generation
│   ├── signals/            #   Traffic signal inference
│   └── validation/         #   Bundle validators
├── scripts/                # Per-tier generation scripts + clean.sh
├── runspecs/               # Benchmark YAML configurations
├── scenarios/              # Bundled canonical scenarios
├── tests/                  # 293 unit & integration tests
├── run.py                  # Convenience CLI
├── generate.py             # Scenario generator entry point
├── setup_simforge.py       # One-command bootstrap
├── requirements.txt        # Python dependencies
└── SETUP.md                # This file
```

---

## Troubleshooting

| Problem                | Solution                                                          |
| ---------------------- | ----------------------------------------------------------------- |
| `MATSim JAR not found` | Re-run `python setup_simforge.py`, or run the manual `curl` above |
| `SUMO not found`       | `brew install sumo`                                               |
| `Java not found`       | `brew install openjdk@17`                                         |
| OSM download timeout   | Check internet connection, retry; cache is in `cache/`            |
| `No scenarios found`   | Run a script in `scripts/` first, or check `python run.py --list` |
| Large `cache/` folder  | `scripts/clean.sh --all` to wipe the OSM Overpass cache           |
