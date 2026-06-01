# 🌉 SimForge

**SimForge** is a reproducible, cross-simulator benchmarking framework for urban traffic simulation.

It provides a **canonical data schema**, **validated scenario bundles**, **deterministic adapters** for multiple simulators, and a **unified execution harness** for fair performance comparison.

---

## ⚡ Highlights

- **3 heterogeneous engines** unified under one canonical schema, SUMO (micro + meso), MATSim (queue-mobsim), DTALite (CPU mesoscopic DTA), with a **code-enforced fair-comparison contract**
- **~25–30× speedup** on BFS pre-routing (~68h → ~5–8h on NYC 500K-trip scenarios) via canonical-route deduplication, 16-way parallelism, and a content-addressed cache
- **Byte-identical reproducibility**, every run bit-deterministic for a given seed; no live-protocol bindings (no TraCI/Py4J), strictly file-in/file-out
- **HPC-deployed** across three OSC clusters (Pitzer, Cardinal, Ascend) with cluster-specific SLURM tuning
- **Scales to ~80K nodes / ~200K directed links** across Chicago, NYC, and LA at five demand tiers (1K → 500K trips)
- **~70–72% demand realism** (vs. ~20–40% for uniform/gravity baselines), calibrated against US Census PUMS microdata, no paid survey data
- **~639 tests** including mutation tests, byte-identity determinism guards, and Student's-t 95% CIs on every KPI

> Master's thesis · Miami University · 2024–2026

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
| MATSim Adapter               | ✅ Complete (single-iteration meso) |
| DTALite Adapter (3rd primary) | ✅ Complete (CPU mesoscopic DTA, runs on Mac/Linux) |
| 95 % CIs on every KPI        | ✅ Complete (Student's t)            |
| Execution Harness            | ✅ Complete (`run.py` + RunSpec)    |
| Metrics & Plots              | ✅ Complete (10 thesis figures)     |
| Test Suite                   | ✅ ~639 tests (626 pass, 13 arm64-netconvert skips) |
| Bundled scenario: `chicago_1k_car` | ✅ Generated & validated      |
| Visualization Component (opt-in, separate branch) | ✅ Complete (7 map types, OD choropleths, link load, congestion, travel time, route diversity, animated flow) |

Larger scenarios (10K / 50K / 200K / 500K trips) can be generated locally via the helper scripts in `scripts/`; only the small 1K bundle above is committed to the repo.

---

## 🛠️ Quick Start

### Prerequisites

- **uv** (manages Python + the venv), `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Java 17+** (only for MATSim runs), `brew install openjdk@17` on macOS

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

# Download the hash-pinned OSM PBFs (~2.1 GB across IL/NY/CA, the state-level
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
python -m execution.run_benchmark runspecs/benchmark_small.yaml
```

`benchmark_small.yaml` declares the canonical 11-cell matrix
(`chicago_1k_car` × {SUMO meso/micro, MATSim meso, DTALite meso} +
`nyc_10k_car` × {SUMO meso/micro, MATSim meso, DTALite meso} +
`la_50k_car` × {SUMO meso, MATSim meso, DTALite meso}) at N=5 repeats per
cell. All three engines are CPU-only and run on Mac and Linux without
special hardware. After it finishes:

```bash
python -m evaluation.analyze_benchmark runs/benchmark_small/benchmark_results_benchmark_small.json
python -m evaluation.audit_fairness    runs/benchmark_small
python -m evaluation.generate_plots    runs/benchmark_small/benchmark_results_benchmark_small.json
```

The middle step (`audit_fairness`) is the cross-engine fairness check,
verifies that all engines saw the same trip set, the same SCC-filtered
network, and the same trip count, and reports per-engine travel-time
ratios. See [doc/EXPERIMENT_LOG.md](doc/EXPERIMENT_LOG.md) for the
canonical interpretation of audit output.

`run_benchmark.py` also auto-emits a one-shot `reproducibility_scorecard.md`
next to `benchmark_results_*.json`: provenance hashes + environment +
Q1 byte-identity verdict + R = 1 − CV per cell + pass/warn/fail rollup.
Regenerate manually with `python -m tools.generate_scorecard <run-dir>`.

### Generate New Scenarios

```bash
python generate.py --preset chicago_1k_car      # 1K car, Chicago, 7–8 AM
python generate.py --preset nyc_10k_car         # 10K car, NYC, 7–9 AM
python generate.py --preset la_50k_car          # 50K car, LA, 6–10 AM
python generate.py --preset chicago_200k_car    # 200K car, Chicago, 24h
python generate.py --preset nyc_500k_car        # 500K car, NYC, 6–10 AM
```

All five presets generate **car-only** demand because SimForge's three engine adapters (SUMO, MATSim, DTALite) currently only simulate car traffic, see [doc/MODELGEN_AND_MODES.md](doc/MODELGEN_AND_MODES.md) §5 for adapter mode handling and §8 for the future-work pathway to multi-modal simulation.

The numbered files in `scripts/` (`01_chicago_1k_car.py` … `05_nyc_500k_car.py`) are thin wrappers that call the **same** `generate_scenario()` with the same hardcoded kwargs as the preset above. They accept `--verbose` / `-v` only; the `--preset` form remains preferred when you need other overrides (`--output`, `--seed`, `--city`, `--modes`, `--synthetic`, OSM source mode).

See [doc/SCENARIO_GENERATION.md](doc/SCENARIO_GENERATION.md) for what each tier generates and how realism is calibrated.

---

## 📂 Repository Structure

```
SimForge/
├── adapters/               # Simulator-specific converters
│   ├── sumo/               # SUMO adapter (micro + meso)
│   ├── matsim/             # Activity-based simulator
│   └── dtalite/            # CPU mesoscopic Dynamic Traffic Assignment (path4gmns)
├── canonical/schema/       # Schema documentation (v0)
├── doc/                    # Engineering docs (architecture, reproduction, Pitzer, engine retrospectives)
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
├── scripts/                # Per-tier scenario generation (01_chicago_1k_car.py … 05_nyc_500k_car.py)
├── tools/                  # Operator utilities (clean.sh, download_osm.py,
│                           # env_report.py, inspect_network.py,
│                           # analyze_scenarios.py, see `python help.py analyzer`,
│                           # download_census_tracts.py + download_tiger_roads.py
│                           # for the visualization-branch shapefile cache)
├── runspecs/               # Benchmark configurations (YAML)
├── scenarios/              # Bundled canonical scenarios
│   └── chicago_1k_car/     # (larger tiers are generated on demand via scripts/)
├── lib/matsim-15.0/        # MATSim JAR + libs (see SETUP.md)
├── runs/                   # Simulation output (gitignored)
├── cache/                  # Overpass HTTP cache + US Census shapefiles (gitignored)
├── tests/                  # pytest test suite (~639 tests across 29 files)
├── visualization/          # Opt-in geographic-map renderer (on visualization branch)
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
| SUMO    | eclipse-sumo 1.26+| Microscopic / Mesoscopic   | net.xml, rou.xml       |
| MATSim  | MATSim 15 | Activity-based, single iteration   | network.xml, plans.xml |
| DTALite | path4gmns 0.10+ (DTALiteClassic)| CPU mesoscopic Dynamic Traffic Assignment (UE) | node.csv + link.csv + demand.csv + settings.{csv,yml} |

LPSim, POLARIS, and QarSUMO were evaluated and rejected, see the retrospectives in [`doc/engines/`](doc/engines/).

> **DTALite ships inside `path4gmns`.** Pip-installable, CPU-only, runs on Mac (arm64/x86_64), Linux x86_64, and Windows. The pinned version is in [`lib/dtalite/manifest.json`](lib/dtalite/manifest.json). On macOS the bundled binary needs OpenMP: `brew install libomp`.

---

## 📈 Metrics

- **Fidelity**: RMSE, GEH, KS statistic
- **Scalability**: Wall-clock runtime, throughput (vehicles/sec)
- **Reproducibility**: R = 1 − σ/μ across repeats

---

## 🧪 Testing

```bash
pytest tests/ -v          # Run all ~639 tests (~626 pass, 13 arm64-netconvert skips on Apple Silicon)
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
| Adapter Layer       | `adapters/sumo/`, `adapters/matsim/`, `adapters/dtalite/`    | Canonical → simulator-specific format                                           |
| Execution Harness   | `execution/`                                                 | RunSpec-driven benchmark orchestration                                          |
| Evaluation Metrics  | `evaluation/metrics/`                                        | Fidelity (RMSE, GEH, KS), Scalability, Reproducibility                          |

**Key design decisions:**

- **State-aware BFS routing at conversion time** (V5+), deterministic, version-independent routes that respect OSM-extracted turn restrictions
- **MATSim `lastIteration=0`**, single-pass execution for fair cross-simulator comparison
- **SHA-256 manifest**, integrity verification before every simulation run
- **Census-calibrated demand**, population-weighted origins, real commute times, V5+ per-person empirical departures from PUMS JWMNP (~70–72 % realism after Phases 5-10)
- **OSM-grounded signal placement** (V5+), signals only at nodes carrying `highway=traffic_signals`, replacing the pre-V5 `degree ≥ 4` heuristic
- **Modelgen-grounded trip purposes** (V5+), HBW (AM + PM) commutes plus parent-with-kid HBSchool chains derived from cityscape `schedule[0,1]` + AGEP + OSM `building.kind`; six-purpose taxonomy on `demand.csv`
- **Cross-engine vehicle parameter alignment** (V11+), single canonical car description in `adapters/common/vehicle_types.py` consumed by all three adapters; SUMO `length+minGap` ≡ MATSim effective `length` ≡ DTALite PCE 1.0, regression-pinned by `tests/test_vehicle_types.py`

For detailed architecture documentation, see [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md).

---

## 🗺️ Geographic Visualization (opt-in)

A standalone visualization component on the `visualization` branch
renders **7 map types** from any bundle / benchmark run, OD demand
choropleths on US Census tracts, per-engine link load + congestion +
travel time, cross-engine route diversity, and MATSim-driven flow
animations (mp4/gif/apng). The main SimForge code paths do not import
it, so the locked benchmark numbers are independent of any plot.

```bash
# One-time setup: cache US Census tracts + TIGER roads
python -m tools.download_census_tracts --all-bundled
python -m tools.download_tiger_roads --all-bundled

# Coverage report (what's renderable from what's on disk?)
python -m visualization.generate_maps --scenario chicago_1k_car --dry-run

# Render every available map type
python -m visualization.generate_maps --scenario chicago_1k_car --maps all
```

Output defaults to `visualization/output/<scenario>/`. See
[`visualization/README.md`](visualization/README.md) for the full
catalogue, CLI reference, and the cross-engine interpretation notes
(SUMO ≈ MATSim vs DTALite, PUMS departure bursts, full-day OD
symmetry).

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
| [doc/SIMULATION_PARADIGMS.md](doc/SIMULATION_PARADIGMS.md) | Macro / meso / micro reference + per-engine support |
| [doc/LICENSING.md](doc/LICENSING.md)                       | Per-component license declarations            |
| [doc/DATA_MANAGEMENT.md](doc/DATA_MANAGEMENT.md)           | Data sources, PII policy, retention, ethics   |
| [doc/EXPERIMENT_LOG.md](doc/EXPERIMENT_LOG.md)             | Chronological measurement journal             |
| [canonical/schema/](canonical/schema/)                     | Schema specifications (v0)                    |
| `adapters/*/MAPPING.md`                                    | Per-adapter field mapping rules               |
| [visualization/README.md](visualization/README.md)         | Geographic visualization (opt-in, 7 map types) |
| [CONTRIBUTING.md](CONTRIBUTING.md)                         | Contribution workflow and code style          |
| `python help.py`                                           | In-CLI help: curses TUI in a terminal, `python help.py <topic>` (overview / setup / generate / run / scripts / cities / modes / adapters / metrics / evaluation / schema / benchmark / tests / analyzer / troubleshooting) for paste-safe text |

---
