# SimForge Complete Setup Guide

This guide explains how to set up and run SimForge from scratch on any machine.

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
| **Python** | 3.10+   | `brew install python@3.11` or system package manager                      |
| **Java**   | 17+     | `brew install openjdk@17` (required for MATSim)                           |
| **SUMO**   | 1.18+   | `brew install sumo` or [download](https://sumo.dlr.de/docs/Downloads.php) |
| **Git**    | 2.30+   | Usually pre-installed                                                     |

### Verify Prerequisites

```bash
# Check Python
python3 --version  # Should be 3.10+

# Check Java (for MATSim)
java -version  # Should be 17+

# Check SUMO
sumo --version  # Should be 1.18+
```

---

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/yourrepo/SimForge.git
cd SimForge
```

### 2. Create Python Virtual Environment

```bash
# Create virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows
```

### 3. Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Install MATSim JAR

```bash
# Create lib directory
mkdir -p lib/matsim-15.0

# Download MATSim 15.0 release
curl -L -o matsim-15.0.zip https://github.com/matsim-org/matsim-libs/releases/download/15.0/matsim-15.0.zip
unzip matsim-15.0.zip -d lib/
rm matsim-15.0.zip
```

### 5. Verify Installation

```bash
# Run tests
python -m pytest tests/ -v

# Check MATSim JAR detection
python -c "from adapters.matsim.matsim_adapter import find_matsim_jar; print('MATSim:', find_matsim_jar())"

# Check SUMO
python -c "from adapters.sumo.sumo_adapter import SUMOAdapter; print('SUMO: OK')"
```

---

## Scenario Data

### Where Does the Data Come From?

SimForge uses **synthetic data derived from real sources**:

| File           | Source                  | Data Type                               |
| -------------- | ----------------------- | --------------------------------------- |
| `network.xml`  | **OpenStreetMap (OSM)** | Real road network topology              |
| `demand.csv`   | **Generated**           | Synthetic trips using population models |
| `signals.xml`  | **Generated/Estimated** | Traffic signal timing patterns          |
| `config.xml`   | **Created**             | Simulation parameters (seed, duration)  |
| `manifest.xml` | **Created**             | Checksums and metadata                  |

### Why Synthetic Demand?

Per the thesis plan, synthetic demand is used because:

- **Privacy**: Real trip data contains personally identifiable information (PII)
- **Scalability**: Real data is expensive/unavailable at 50k-5M scale
- **Reproducibility**: Synthetic data with fixed seeds ensures identical runs
- **Licensing**: OD matrices from public planning models avoid IP issues

The demand is **statistically realistic** - generated using:

- Population density from census data
- Peak-hour distribution curves (8% of daily trips in AM peak)
- Origin-destination patterns based on urban form

### Pre-Built Scenarios

| Scenario              | Nodes  | Links   | Available Tiers |
| --------------------- | ------ | ------- | --------------- |
| `toy_2x2_grid`        | 9      | 24      | Test only       |
| `sioux_falls_tier50k` | ~3,000 | ~8,000  | 50k             |
| `austin_tier50k`      | 44,861 | 110,533 | 50k             |
| `berlin_tier50k`      | 39,866 | 103,309 | 50k             |

### Generating Your Own Scenarios

```bash
# Generate Austin 50k
python -m pipeline.scenariobuilder.build_city_bundles austin --tier 50k

# Generate Berlin at multiple tiers
python -m pipeline.scenariobuilder.build_city_bundles berlin --tier all

# Generate all cities
python -m pipeline.scenariobuilder.build_city_bundles --all
```

**Time estimates for scenario generation:**

- 50k tier: ~2-5 minutes (depends on OSM download)
- 500k tier: ~10-15 minutes
- 5M tier: ~30-60 minutes

---

## Running Simulations

### Quick Start: Toy Scenario

```bash
# Run with SUMO (microscopic)
python run.py run toy_2x2_grid sumo

# Run with SUMO mesoscopic
python run.py run toy_2x2_grid sumo --mesoscopic

# Run with MATSim
python run.py run toy_2x2_grid matsim
```

### Run City Scenarios

```bash
# Run Austin with SUMO
python run.py run austin_50k sumo

# Run Berlin with MATSim
python run.py run berlin_50k matsim
```

### Run Full Benchmark Matrix

```bash
# Execute the thesis benchmark runspec
python run.py benchmark runspecs/thesis_benchmark_matrix.yaml
```

### Run Individual Adapter CLI

```bash
# SUMO adapter directly
python -m adapters.sumo.cli scenarios/toy_2x2_grid out/sumo_output

# MATSim adapter directly
python -m adapters.matsim.cli scenarios/toy_2x2_grid out/matsim_output
```

---

## Understanding the Output

### What Results Do Simulators Produce?

After running a simulation, you get:

```
out/{engine}_{scenario}/
├── trips.csv          # Completed trips with travel times
├── link_stats.csv     # Per-link flow counts and speeds
├── runtime.json       # Wall-clock time, throughput metrics
└── config_used.xml    # Actual configuration used
```

### Key Metrics (Per Thesis)

| Dimension           | Metric     | Formula                    | Purpose                  |
| ------------------- | ---------- | -------------------------- | ------------------------ |
| **Fidelity**        | RMSE       | √(Σ(sim-obs)²/n)           | Accuracy vs ground truth |
| **Fidelity**        | GEH        | √(2(sim-obs)²/(sim+obs))   | Traffic count comparison |
| **Fidelity**        | KS         | max\|F_sim(x) - F_obs(x)\| | Distribution similarity  |
| **Scalability**     | Runtime    | Twall (seconds)            | How fast it runs         |
| **Scalability**     | Throughput | vehicles/sec/core          | Efficiency per core      |
| **Reproducibility** | R          | 1 - σ/μ                    | Run-to-run consistency   |

### Example Output

```
==============================
Simulation Complete: toy_2x2_grid + sumo
==============================
Runtime:        12.4 seconds
Trips Complete: 1,000
Avg Travel Time: 245.3 seconds
Throughput:     80.6 vehicles/sec
```

### Final Thesis Output

The complete thesis benchmark produces:

1. **Comparative Tables**: Fidelity/scalability across all 3 cities × 3 tiers × 5 engines
2. **Scalability Plots**: Runtime vs agent count (log-log)
3. **Reproducibility Scores**: R values with 95% confidence intervals
4. **Hardware Efficiency**: vehicles/sec/core and vehicles/sec/watt

---

## GPU Acceleration

### How GPU Helps (QarSUMO)

| Mode          | Hardware    | Speedup  | Use Case                   |
| ------------- | ----------- | -------- | -------------------------- |
| CPU (SUMO)    | Any CPU     | Baseline | Small scenarios, debugging |
| GPU (QarSUMO) | NVIDIA CUDA | 10-50x   | Large-scale (500k+ agents) |

### GPU Requirements for QarSUMO

- NVIDIA GPU with CUDA 11.0+
- QarSUMO binary compiled with CUDA support
- At least 8GB VRAM for 500k agents

### Running with GPU

```bash
# QarSUMO uses GPU automatically if available
python run.py run austin_50k qarsumo

# Force CPU fallback
python run.py run austin_50k qarsumo --no-gpu
```

### Current Status

On your local machine:

- **SUMO**: ✅ Installed and working
- **MATSim**: ✅ Installed (lib/matsim-15.0/)
- **QarSUMO**: ⚠️ Binary not found - falls back to SUMO

To install QarSUMO with GPU support, you need to compile from source with CUDA.

---

## Command Reference

### Main CLI Commands

```bash
# List available scenarios
python run.py list

# Run single scenario
python run.py run <scenario> <engine> [options]

# Run benchmark matrix
python run.py benchmark <runspec.yaml>

# Validate scenario bundle
python -m pipeline.validation.validate_bundle scenarios/<name>
```

### Options

| Flag             | Description                                   |
| ---------------- | --------------------------------------------- |
| `--mesoscopic`   | Use mesoscopic mode (faster, less detailed)   |
| `--iterations N` | Number of iterations (MATSim)                 |
| `--seed N`       | Random seed for reproducibility               |
| `--output DIR`   | Output directory                              |
| `--force`        | Overwrite existing output (skip confirmation) |

### What is `--force`?

The `--force` flag skips the "output directory exists" warning and overwrites previous results. Use it when:

- Re-running experiments after code changes
- Automating batch runs in scripts
- You're sure you don't need the old output

---

## Troubleshooting

### Common Issues

| Problem                | Solution                                             |
| ---------------------- | ---------------------------------------------------- |
| `MATSim JAR not found` | Run the MATSim download commands above               |
| `SUMO not found`       | Install via `brew install sumo`                      |
| `Java version error`   | Install Java 17+: `brew install openjdk@17`          |
| `OSM download failed`  | Check internet connection, retry with smaller radius |
| `Out of memory`        | Reduce tier (use 50k instead of 500k)                |

### Getting Help

```bash
# CLI help
python run.py --help
python run.py run --help

# Run tests
python -m pytest tests/ -v
```

---

## Project Structure

```
SimForge/
├── adapters/           # Simulator-specific converters
│   ├── sumo/          # SUMO/QarSUMO adapter
│   ├── matsim/        # MATSim adapter
│   └── qarsumo/       # QarSUMO (GPU) adapter
├── canonical/          # Schema documentation
├── evaluation/         # Metrics computation
├── execution/          # Benchmark harness
├── lib/               # External JARs (MATSim)
├── pipeline/          # Data generation tools
│   ├── scenariobuilder/  # City bundle generator
│   └── validation/       # Bundle validators
├── runspecs/          # Benchmark configurations
├── scenarios/         # Input scenario bundles
├── tests/             # Unit tests
├── run.py             # Main CLI
├── requirements.txt   # Python dependencies
└── SETUP.md          # This file
```

---

## License

- Code: Apache-2.0
- Schemas: CC BY 4.0
- Network data derived from OpenStreetMap: ODbL
