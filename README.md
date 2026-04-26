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

| Component                    | Status                              |
| ---------------------------- | ----------------------------------- |
| Canonical Schema (v0)        | ✅ Stable                           |
| Scenario Validator           | ✅ Complete                         |
| SUMO Adapter                 | ✅ Complete (microscopic + meso)    |
| QarSUMO Adapter              | ✅ Complete (CPU fallback to SUMO)  |
| MATSim Adapter               | ✅ Complete (single-iteration meso) |
| Execution Harness            | ✅ Complete (`run.py` + RunSpec)    |
| Metrics & Plots              | ✅ Complete (9 thesis figures)      |
| Test Suite                   | ✅ 406 tests passing                |
| Bundled scenario: `chicago_1k_car` | ✅ Generated & validated      |

Larger scenarios (10K / 50K / 200K / 500K trips) can be generated locally via the helper scripts in `scripts/`; only the small 1K bundle above is committed to the repo.

---

## 🛠️ Quick Start

### Prerequisites

- **uv** (manages Python + the venv) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Java 17+** (only for MATSim runs) — `brew install openjdk@17` on macOS

Everything else (Python 3.13, all Python packages, **SUMO including the binary**) is locked in [`requirements.lock`](requirements.lock) and installed in one step below.

### Installation

```bash
git clone <repo-url>
cd SimForge

# uv installs Python 3.13.13 and creates the venv
uv python install 3.13
uv venv --python 3.13 .venv
source .venv/bin/activate

# One command pulls every Python dep + SUMO at the locked versions
uv pip install -r requirements.lock

# Download the hash-pinned OSM PBFs (~2.1 GB across IL/NY/CA — the state-level
# extracts used for chicago, nyc, and la scenarios). Skipped if already present.
python tools/download_osm.py

# Verify the toolchain (cross-machine parity reference)
python tools/env_report.py
```

For the MATSim JAR install, supercomputer workflow, and full reproducibility recipe see [SETUP.md](SETUP.md), [doc/PITZER.md](doc/PITZER.md), and [doc/REPRODUCING.md](doc/REPRODUCING.md).

### Validate a Bundled Scenario

```bash
python -m pipeline.validation.validate_bundle scenarios/chicago_1k_car
```

### Run a Single Simulation

```bash
# All installed engines × all modes × all scenarios (default 10 repeats)
python run.py

# One scenario, one engine
python run.py --scenario chicago_1k_car --engine sumo --mode meso

# List what's available
python run.py --list
```

### Run the Full Benchmark

```bash
python -m execution.run_benchmark runspecs/stress_test.yaml
```

`stress_test.yaml` declares the canonical 4-cell matrix (`chicago_1k_car` × {SUMO meso, SUMO micro, QarSUMO meso, MATSim meso}) used to produce the thesis figures. After it finishes:

```bash
python -m evaluation.analyze_benchmark runs/stress_test/benchmark_results_stress_test.json
python -m evaluation.generate_plots    runs/stress_test/benchmark_results_stress_test.json
```

### Generate New Scenarios

```bash
python scripts/01_quick_test.py        # 1K car, Chicago, 7–8 AM
python scripts/02_small_commute.py     # 10K car, NYC, 7–9 AM
python scripts/03_medium_multimodal.py # 50K car+transit+bike, LA, 6–10 AM
python scripts/04_large_full_day.py    # 200K car+transit, Chicago, 24h
python scripts/05_stress_test.py       # 500K car, NYC, 6–10 AM
```

See [doc/SCENARIO_GENERATION.md](doc/SCENARIO_GENERATION.md) for what each tier generates and how realism is calibrated.

---

## 📂 Repository Structure

```
SimForge/
├── adapters/               # Simulator-specific converters
│   ├── sumo/               # SUMO adapter (micro + meso)
│   ├── qarsumo/            # GPU-accelerated SUMO (CPU fallback)
│   └── matsim/             # Activity-based simulator
├── canonical/schema/       # Schema documentation (v0)
├── doc/                    # Architecture, reproduction, Pitzer, thesis chapters
├── evaluation/             # Metrics, analysis, plot generation
│   └── metrics/            # Fidelity, scalability, reproducibility
├── execution/              # Benchmark harness & runners
├── osm_data/               # Hash-pinned OSM PBF snapshots + manifest.json
│                           # (PBF binaries gitignored; download via tools/download_osm.py)
├── pipeline/               # Data generation pipeline
│   ├── network/            # OSM (PBF or Overpass) → canonical network
│   ├── demand/             # Synthetic + census-calibrated trip generation
│   ├── signals/            # Traffic signal inference
│   └── validation/         # Bundle validator
├── scripts/                # Per-tier scenario generation (01_quick_test.py … 05_stress_test.py)
├── tools/                  # Operator utilities (clean.sh, download_osm.py)
├── runspecs/               # Benchmark configurations (YAML)
├── scenarios/              # Bundled canonical scenarios
│   └── chicago_1k_car/     # (larger tiers are generated on demand via scripts/)
├── lib/matsim-15.0/        # MATSim JAR + libs (see SETUP.md)
├── runs/                   # Simulation output (gitignored)
├── cache/                  # Overpass HTTP cache — only populated if the fallback path runs (gitignored)
├── tests/                  # pytest test suite (406 tests)
├── run.py                  # Main CLI entry point
├── generate.py             # Scenario generator entry point
├── requirements.txt
└── SETUP.md                # Detailed setup guide
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

| Adapter | Engine    | Traffic Model                      | Output                 |
| ------- | --------- | ---------------------------------- | ---------------------- |
| SUMO    | eclipse-sumo 1.26+| Microscopic / Mesoscopic           | net.xml, rou.xml       |
| QarSUMO | QarSUMO   | GPU-accelerated meso (CPU fallback)| SUMO + GPU config      |
| MATSim  | MATSim 15 | Activity-based, single iteration   | network.xml, plans.xml |

---

## 📈 Metrics

- **Fidelity**: RMSE, GEH, KS statistic
- **Scalability**: Wall-clock runtime, throughput (vehicles/sec)
- **Reproducibility**: R = 1 − σ/μ across repeats

---

## 🧪 Testing

```bash
pytest tests/ -v          # Run all 406 tests
pytest tests/ -v -k sumo  # SUMO-related tests only
```

See [TESTING.md](TESTING.md) for layout and coverage.

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
- **Census-calibrated demand** — population-weighted origins, real commute times (~60–65 % realism)

For detailed architecture documentation, see [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md).

---

## 📚 Documentation

| Document                                                   | Description                                   |
| ---------------------------------------------------------- | --------------------------------------------- |
| [SETUP.md](SETUP.md)                                       | Installation guide (local + OSM data)         |
| [doc/PITZER.md](doc/PITZER.md)                             | Supercomputer (OSC Pitzer) setup and SLURM    |
| [TESTING.md](TESTING.md)                                   | Test suite layout and how to run subsets      |
| [CHANGELOG.md](CHANGELOG.md)                               | Notable changes per release                   |
| [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md)                 | End-to-end system architecture                |
| [doc/SCENARIO_GENERATION.md](doc/SCENARIO_GENERATION.md)   | Data sources, generation pipeline, realism    |
| [doc/REPRODUCING.md](doc/REPRODUCING.md)                   | Full reproduction guide for thesis results    |
| [doc/RESULTS_GUIDE.md](doc/RESULTS_GUIDE.md)               | What each generated figure/table means        |
| [doc/GLOSSARY.md](doc/GLOSSARY.md)                         | Acronyms and term definitions                 |
| [doc/chapters/methods.md](doc/chapters/methods.md)         | Thesis Chapter 3 — Methods                    |
| [doc/chapters/experiments.md](doc/chapters/experiments.md) | Thesis Chapter 4 — Experiments                |
| [doc/chapters/results.md](doc/chapters/results.md)         | Thesis Chapter 5 — Results                    |
| [canonical/schema/](canonical/schema/)                     | Schema specifications (v0)                    |
| `adapters/*/MAPPING.md`                                    | Per-adapter field mapping rules               |
| [CONTRIBUTING.md](CONTRIBUTING.md)                         | Contribution workflow and code style          |

---
