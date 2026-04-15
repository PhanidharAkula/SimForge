# SimForge Setup Guide

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Scenario Data](#scenario-data)
4. [Running Simulations](#running-simulations)
5. [Understanding the Output](#understanding-the-output)
6. [GPU Acceleration](#gpu-acceleration)
7. [Command Reference](#command-reference)

---

## Prerequisites

### Required Software

| Software   | Version | Installation                                                              |
| ---------- | ------- | ------------------------------------------------------------------------- |
| **Python** | 3.10+   | `brew install python@3.13` or system package manager                      |
| **Java**   | 17+     | `brew install openjdk@17` (required for MATSim)                           |
| **SUMO**   | 1.18+   | `brew install sumo` or [download](https://sumo.dlr.de/docs/Downloads.php) |
| **Git**    | 2.30+   | Usually pre-installed                                                     |

### Verify Prerequisites

```bash
python3 --version   # Should be 3.10+
java -version       # Should be 17+
sumo --version      # Should be 1.18+
```

---

## Installation

### 1. Clone the Repository

```bash
git clone <repo-url>
cd SimForge
```

### 2. Create Python Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate   # macOS/Linux
```

### 3. Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Install MATSim JAR

MATSim is a Java application — download and extract it into `lib/`:

```bash
mkdir -p lib
curl -L -o matsim-15.0.zip https://github.com/matsim-org/matsim-libs/releases/download/15.0/matsim-15.0.zip
unzip matsim-15.0.zip -d lib/
rm matsim-15.0.zip
```

> **Note:** `lib/` is gitignored (downloaded dependency). Each developer must
> run this step after cloning.

### 5. Verify Installation

```bash
python -m pytest tests/ -v
python -c "from adapters.sumo.sumo_adapter import SUMOAdapter; print('SUMO: OK')"
python -c "from adapters.matsim.matsim_adapter import find_matsim_jar; print('MATSim:', find_matsim_jar())"
```

---

## Scenario Data

### Available Tiers

| Tier | Trips     | Horizon | Use Case                   |
| ---- | --------- | ------- | -------------------------- |
| 5K   | 5,000     | 1 hr    | Development, quick tests   |
| 50K  | 50,000    | 2 hr    | Medium-scale benchmarks    |
| 500K | 500,000   | 4 hr    | Large-scale evaluation     |
| 5M   | 5,000,000 | 8 hr    | Extreme scale (GPU needed) |

### Current Scenarios

| Scenario                  | City    | Trips  | Modes              |
| ------------------------- | ------- | ------ | ------------------ |
| `chicago_1k_car`          | Chicago | 1,000  | car                |
| `nyc_10k_car`             | NYC     | 10,000 | car                |
| `la_50k_bike_car_transit` | LA      | 50,000 | bike, car, transit |

### Data Sources

| File         | Source                      | Description                                |
| ------------ | --------------------------- | ------------------------------------------ |
| network.xml  | **OpenStreetMap (OSM)**     | Real road network topology                 |
| demand.csv   | **Synthetic** or **Census** | Gravity model (default) or PUMS-calibrated |
| signals.xml  | **Generated/Estimated**     | Inferred signal timing from OSM nodes      |
| config.xml   | **Created**                 | Simulation parameters (seed, duration)     |
| manifest.xml | **Created**                 | SHA-256 checksums and metadata             |

### Demand Modes

Each generation script supports two demand modes:

- **Synthetic (default):** Gravity model with degree-weighted origins and distance-decayed destinations.
- **Census-calibrated (`--model`):** Uses ModelGen PUMS microdata for population-weighted origins and commute-time-calibrated trip distances.

### Generating Scenarios

```bash
# Run preset scripts
python scripts/01_quick_test.py       # 1K Chicago car
python scripts/02_small_commute.py    # 10K NYC car
python scripts/03_medium_multimodal.py # 50K LA multi-mode

# Or use generate.py directly
python generate.py --city chicago --trips 1000 --modes car
python generate.py --preset quick_test
```

### Validating Scenarios

```bash
python -m pipeline.validation.validate_bundle scenarios/chicago_1k_car
```

---

## Running Simulations

### Quick Start

```bash
# Run a specific scenario with SUMO (mesoscopic)
python run.py --scenario chicago_1k_car --engine sumo --mode meso

# Run all scenarios with all engines
python run.py

# List available options
python run.py --list
```

### Run Benchmark from Runspec

```bash
# Small benchmark (3 scenarios × 3 engines × meso × 3 repeats = 27 runs)
python -m execution.run_benchmark runspecs/benchmark_small.yaml

# Dry run (validate without executing)
python -m execution.run_benchmark runspecs/benchmark_small.yaml --dry-run

# Filter to one scenario
python -m execution.run_benchmark runspecs/benchmark_small.yaml --scenario chicago_1k_car
```

### Run Individual Adapter CLI

```bash
python -m adapters.sumo.cli scenarios/chicago_1k_car runs/chicago_sumo
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
| `python run.py`                                        | Main CLI — run all or filtered simulations |
| `python run.py --list`                                 | Show available scenarios/engines/modes     |
| `python run.py --validate-only`                        | Validate scenario bundles only             |
| `python -m execution.run_benchmark <runspec>`          | Run benchmark from YAML spec               |
| `python -m pipeline.validation.validate_bundle <path>` | Validate a single bundle                   |
| `python scripts/generate_<city>_<tier>.py`             | Generate a scenario bundle                 |
| `python -m pytest tests/ -v`                           | Run test suite                             |

---

## Project Structure

```
SimForge/
├── adapters/               # Simulator-specific converters
│   ├── sumo/               #   SUMO / QarSUMO adapter
│   ├── matsim/             #   MATSim adapter
│   └── qarsumo/            #   QarSUMO (GPU) adapter
├── canonical/              # Schema documentation
├── evaluation/             # Metrics computation
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
├── scripts/                # Per-city generation scripts (12 total)
├── runspecs/               # Benchmark YAML configurations
├── scenarios/              # Generated scenario bundles
├── tests/                  # Unit & integration tests
├── run.py                  # Convenience CLI
├── requirements.txt        # Python dependencies
├── SETUP.md                # This file
└── TODO.md                 # Development roadmap
```

---

## Troubleshooting

| Problem                | Solution                           |
| ---------------------- | ---------------------------------- |
| `MATSim JAR not found` | Run MATSim download commands above |
| `SUMO not found`       | `brew install sumo`                |
| `Java not found`       | `brew install openjdk@17`          |
| OSM download timeout   | Check internet connection, retry   |
| `No scenarios found`   | Run generation scripts first       |
