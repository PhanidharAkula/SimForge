# 🌉 SimForge

**SimForge** is a reproducible, cross-simulator benchmarking framework for urban traffic simulation.

It provides a **canonical data schema**, **validated scenario bundles**, **deterministic adapters** for multiple simulators, and a **unified execution harness** for fair performance comparison.

---

## 🎯 Project Goals

1. **Standardize inputs**: One canonical format converted to any simulator
2. **Ensure reproducibility**: Deterministic pipelines with hash verification
3. **Enable fair comparison**: Same scenarios, same metrics, different engines
4. **Support research**: Ready-to-use benchmarks for thesis/publication

---

## ✅ Current Status

| Component          | Status                           |
| ------------------ | -------------------------------- |
| Canonical Schema   | ✅ Complete (v0)                 |
| Scenario Validator | ✅ Complete                      |
| SUMO Adapter       | ✅ Complete (micro + meso)       |
| QarSUMO Adapter    | ✅ Complete (falls back to SUMO) |
| MATSim Adapter     | ✅ Complete                      |
| Execution Harness  | ✅ Complete                      |
| Metrics Library    | ✅ Complete                      |
| Chicago 5K         | ✅ Generated & Validated         |
| NYC 5K             | ✅ Generated & Validated         |
| LA 5K              | ✅ Generated & Validated         |

---

## 🛠️ Quick Start

### Prerequisites

- Python 3.10+
- SUMO 1.20+ (optional, for simulation)
- Java 17+ (optional, for MATSim)

### Installation

```bash
# Clone repository
git clone <repo-url>
cd SimForge

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Generate Scenario Data

```bash
python scripts/01_quick_test.py       # 1K Chicago car
python scripts/02_small_commute.py    # 10K NYC car
python scripts/03_medium_multimodal.py # 50K LA multi-mode
```

### Validate a Scenario

```bash
python -m pipeline.validation.validate_bundle scenarios/chicago_1k_car
```

### Run Simulations

```bash
# Run everything (all scenarios × all engines × all modes)
python run.py

# Run a specific scenario with a specific engine
python run.py --scenario chicago_1k_car --engine sumo --mode meso

# List available options
python run.py --list
```

### Run Full Benchmark

```bash
python -m execution.run_benchmark runspecs/benchmark_small.yaml
```

---

## 📂 Repository Structure

```
SimForge/
├── adapters/               # Simulator-specific converters
│   ├── sumo/               # SUMO adapter (micro + meso)
│   ├── qarsumo/            # GPU-accelerated SUMO
│   └── matsim/             # Activity-based simulator
├── canonical/schema/       # Schema documentation (v0)
├── doc/                    # Thesis documentation & chapters
├── evaluation/             # Metrics computation & analysis
│   └── metrics/            # Fidelity, scalability, reproducibility
├── execution/              # Benchmark harness & runners
├── pipeline/               # Data generation pipeline
│   ├── network/            # OSM → canonical network
│   ├── demand/             # Synthetic trip generation
│   ├── signals/            # Traffic signal inference
│   └── validation/         # Bundle validator
├── scripts/                # Per-city data generation scripts
├── runspecs/               # Benchmark configurations (YAML)
├── scenarios/              # Generated canonical bundles
│   ├── chicago_1k_car/
│   ├── chicago_200k_car_transit/
│   ├── la_1k_car/
│   ├── la_50k_bike_car_transit/
│   ├── nyc_1k_car/
│   └── nyc_10k_car/
├── lib/matsim-15.0/        # MATSim JAR + libs
├── runs/                   # Simulation output (gitignored)
├── tests/                  # pytest test suite
├── run.py                  # Main CLI entry point
├── requirements.txt
├── SETUP.md                # Detailed setup guide
└── TODO.md                 # Development roadmap
```

---

## 📊 Canonical Schema

| File         | Format | Description                     |
| ------------ | ------ | ------------------------------- |
| network.xml  | XML    | Road network (nodes + links)    |
| demand.csv   | CSV    | Travel demand (OD trips)        |
| signals.xml  | XML    | Traffic signal timing           |
| config.xml   | XML    | Scenario metadata               |
| manifest.xml | XML    | File inventory + SHA-256 hashes |

---

## 🔧 Simulators

| Adapter | Engine    | Traffic Model          | Output                 |
| ------- | --------- | ---------------------- | ---------------------- |
| SUMO    | SUMO 1.20 | Microscopic/Mesoscopic | net.xml, rou.xml       |
| QarSUMO | QarSUMO   | GPU-accelerated        | SUMO + GPU config      |
| MATSim  | MATSim 15 | Activity-based meso    | network.xml, plans.xml |

---

## 📈 Metrics

- **Fidelity**: RMSE, GEH, KS statistic
- **Scalability**: Runtime, throughput (vehicles/sec)
- **Reproducibility**: R = 1 − σ/μ

---

## 🧪 Testing

```bash
pytest tests/ -v          # Run all tests
pytest tests/ -v -k sumo  # SUMO-related tests only
```

---

## 🏗️ Architecture

SimForge has five subsystems connected through the canonical schema:

```
Data Sources → Generation Pipeline → Canonical Bundle → Adapter Layer → Execution Harness → Evaluation Metrics
```

| Subsystem           | Modules                                                      | Purpose                                                                         |
| ------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------- |
| Generation Pipeline | `pipeline/network/`, `pipeline/demand/`, `pipeline/signals/` | OSM + Census → validated canonical bundles                                      |
| Canonical Schema    | `canonical/schema/`                                          | 5-file intermediate representation (network, demand, signals, config, manifest) |
| Adapter Layer       | `adapters/sumo/`, `adapters/matsim/`, `adapters/qarsumo/`    | Canonical → simulator-specific format                                           |
| Execution Harness   | `execution/`                                                 | RunSpec-driven benchmark orchestration                                          |
| Evaluation Metrics  | `evaluation/metrics/`                                        | Fidelity (RMSE, GEH, KS), Scalability, Reproducibility                          |

**Key design decisions:**

- **BFS routing at conversion time** — deterministic, version-independent routes
- **MATSim `lastIteration=0`** — single-pass execution for fair cross-simulator comparison
- **SHA-256 manifest** — integrity verification before every simulation run
- **Census-calibrated demand** — real population-weighted origins, census commute times (~60-65% realism)

For detailed architecture documentation, see [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md).

---

## 📚 Documentation

| Document                                                   | Description                                   |
| ---------------------------------------------------------- | --------------------------------------------- |
| [SETUP.md](SETUP.md)                                       | Installation guide (local + HPC)              |
| [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md)                 | End-to-end system architecture                |
| [doc/DATA_GENERATION.md](doc/DATA_GENERATION.md)           | Data sources, generation pipeline, validation |
| [doc/SCENARIO_GENERATION.md](doc/SCENARIO_GENERATION.md)   | Scenario generation with realism assessment   |
| [doc/REPRODUCING.md](doc/REPRODUCING.md)                   | Full reproduction guide                       |
| [doc/chapters/methods.md](doc/chapters/methods.md)         | Thesis Chapter 3 — Methods                    |
| [doc/chapters/experiments.md](doc/chapters/experiments.md) | Thesis Chapter 4 — Experiments                |
| [canonical/schema/](canonical/schema/)                     | Schema specifications (v0)                    |
| `adapters/*/MAPPING.md`                                    | Per-adapter field mapping rules               |

---
