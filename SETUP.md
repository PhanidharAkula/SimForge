# SimForge Setup Guide

This guide explains how to set up and run SimForge from scratch.

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

### Operating System

- macOS, Linux, or Windows with WSL2
- Recommended: macOS 13+ or Ubuntu 22.04+

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
# .venv\Scripts\activate    # Windows
```

### 3. Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Install MATSim JAR

```bash
mkdir -p lib/matsim-15.0
curl -L -o matsim-15.0.zip https://github.com/matsim-org/matsim-libs/releases/download/15.0/matsim-15.0.zip
unzip matsim-15.0.zip -d lib/
rm matsim-15.0.zip
```

### 5. Verify Installation

```bash
# Run tests
python -m pytest tests/ -v

# Check SUMO adapter
python -c "from adapters.sumo.sumo_adapter import SUMOAdapter; print('SUMO: OK')"

# Check MATSim JAR detection
python -c "from adapters.matsim.matsim_adapter import find_matsim_jar; print('MATSim:', find_matsim_jar())"
```

---

## Scenario Data

### Current Scenarios (5K tier)

| Scenario     | City    | Nodes  | Links   | Trips | Radius |
| ------------ | ------- | ------ | ------- | ----- | ------ |
| `chicago_5k` | Chicago | ~3,300 | ~8,400  | 5,000 | 4 km   |
| `nyc_5k`     | NYC     | ~1,900 | ~3,900  | 5,000 | 3 km   |
| `la_5k`      | LA      | ~6,300 | ~17,700 | 5,000 | 5 km   |

### Where Does the Data Come From?

SimForge uses **synthetic data derived from real sources**:

| File         | Source                  | Data Type                              |
| ------------ | ----------------------- | -------------------------------------- |
| network.xml  | **OpenStreetMap (OSM)** | Real road network topology             |
| demand.csv   | **Generated**           | Synthetic trips using gravity model    |
| signals.xml  | **Generated/Estimated** | Traffic signal timing patterns         |
| config.xml   | **Created**             | Simulation parameters (seed, duration) |
| manifest.xml | **Created**             | Checksums and metadata                 |

### Generating Scenarios

Each city has a standalone generation script:

```bash
python scripts/generate_chicago_5k.py
python scripts/generate_nyc_5k.py
python scripts/generate_la_5k.py
```

Generation time is typically 10–30 seconds per city (depends on OSM download).

### Validating Scenarios

```bash
python -m pipeline.validation.validate_bundle scenarios/chicago_5k
python -m pipeline.validation.validate_bundle scenarios/nyc_5k
python -m pipeline.validation.validate_bundle scenarios/la_5k
```

---

## Running Simulations

### Quick Start

```bash
# Run a specific scenario with SUMO (mesoscopic)
python run.py --scenario chicago_5k --engine sumo --mode meso

# Run all scenarios with all engines
python run.py

# List available options
python run.py --list
```

### Run Full Benchmark

```bash
# Execute the 5K benchmark runspec (3 cities × 3 engines × mesoscopic × 3 repeats)
python -m execution.run_benchmark runspecs/benchmark_5k.yaml
```

### Run Individual Adapter CLI

```bash
# SUMO adapter directly
python -m adapters.sumo.cli scenarios/chicago_5k runs/chicago_sumo

# MATSim adapter directly
python -m adapters.matsim.cli scenarios/chicago_5k runs/chicago_matsim
```

### Run SUMO Locally (with binary invocation)

```bash
python -m execution.run_sumo_local scenarios/chicago_5k runs/chicago_sumo_out
```

---

## Understanding the Output

### Key Metrics (Per Thesis)

| Dimension           | Metric     | Formula                    | Purpose                  |
| ------------------- | ---------- | -------------------------- | ------------------------ |
| **Fidelity**        | RMSE       | √(Σ(sim−obs)²/n)           | Accuracy vs ground truth |
| **Fidelity**        | GEH        | √(2(sim−obs)²/(sim+obs))   | Traffic count comparison |
| **Fidelity**        | KS         | max\|F_sim(x) − F_obs(x)\| | Distribution similarity  |
| **Scalability**     | Runtime    | T_wall (seconds)           | How fast it runs         |
| **Scalability**     | Throughput | vehicles/sec/core          | Efficiency per core      |
| **Reproducibility** | R          | 1 − σ/μ                    | Run-to-run consistency   |

---

## GPU Acceleration

### QarSUMO

| Mode          | Hardware    | Speedup  | Use Case                   |
| ------------- | ----------- | -------- | -------------------------- |
| CPU (SUMO)    | Any CPU     | Baseline | Small scenarios, debugging |
| GPU (QarSUMO) | NVIDIA CUDA | 10–50×   | Large-scale (500k+ agents) |

QarSUMO requires an NVIDIA GPU with CUDA 11.0+ and at least 8 GB VRAM.
When no GPU is available, QarSUMO falls back to CPU SUMO automatically.

---

## Command Reference

### Main CLI (`run.py`)

```bash
python run.py                                       # Run ALL
python run.py --scenario chicago_5k                 # One scenario
python run.py --scenario chicago_5k,nyc_5k          # Multiple
python run.py --engine sumo,matsim                  # Specific engines
python run.py --mode meso                           # Mesoscopic only
python run.py --repeats 5                           # 5 repeats
python run.py --list                                # Show available options
python run.py --validate-only                       # Validate only
```

### Benchmark Harness

```bash
python -m execution.run_benchmark runspecs/benchmark_5k.yaml
```

### Bundle Validation

```bash
python -m pipeline.validation.validate_bundle scenarios/<name>
```

---

## Troubleshooting

| Problem                | Solution                                    |
| ---------------------- | ------------------------------------------- |
| `MATSim JAR not found` | Run the MATSim download commands above      |
| `SUMO not found`       | Install via `brew install sumo`             |
| `Java not found`       | Install Java 17+: `brew install openjdk@17` |
| OSM download timeout   | Check internet connection, retry            |

---

## Project Structure

```
SimForge/
├── adapters/               # Simulator-specific converters
│   ├── sumo/               # SUMO/QarSUMO adapter
│   ├── matsim/             # MATSim adapter
│   └── qarsumo/            # QarSUMO (GPU) adapter
├── canonical/              # Schema documentation
├── evaluation/             # Metrics computation
├── execution/              # Benchmark harness
├── lib/                    # External JARs (MATSim)
├── pipeline/               # Data generation pipeline
│   ├── network/            # OSM → canonical network
│   ├── demand/             # Synthetic trip generation
│   ├── signals/            # Traffic signal inference
│   └── validation/         # Bundle validators
├── scripts/                # Per-city generation scripts
├── runspecs/               # Benchmark configurations
├── scenarios/              # Input scenario bundles
├── tests/                  # Unit & integration tests
├── run.py                  # Main CLI
├── requirements.txt        # Python dependencies
└── SETUP.md                # This file
```
