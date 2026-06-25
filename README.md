# 🌉 SimForge

**SimForge** is a reproducible, cross-simulator benchmarking framework for urban traffic simulation.

It provides a **canonical data schema**, **validated scenario bundles**, **deterministic adapters** for multiple simulators, and a **unified execution harness** for fair performance comparison.

---

## ⚡ Highlights

- **3 heterogeneous engines** unified under one canonical schema, SUMO (micro + meso), MATSim (queue-mobsim), DTALite (CPU mesoscopic DTA), with a **code-enforced fair-comparison contract**
- **~20× cold / ~228× warm-cache speedup** on BFS pre-routing (per-cell ~68 h → one shared 7.1 h cold pass, 37 min warm, at the 200K tier), which is what made the 500K tier runnable at all (12.1 h measured vs a ~600 h projection), via canonical-route deduplication, parallel workers, and a content-addressed cache
- **Byte-identical reproducibility**, every run bit-deterministic for a given seed; no live-protocol bindings (no TraCI/Py4J), strictly file-in/file-out
- **HPC-deployed** on two OSC clusters (Pitzer + Cardinal, with cluster-specific SLURM tuning; the shared `$HOME` is also mounted on Ascend)
- **Scales to ~420K SCC nodes / ~1.3M directed links** (NYC 500K tier; measured from the simulated networks) across Chicago, NYC, and LA at five demand tiers (1K → 500K trips)
- **~70–72% demand realism** (vs. ~20–40% for uniform/gravity baselines), calibrated against US Census PUMS microdata, no paid survey data
- **668 tests across 31 files** including byte-identity determinism guards, and Student's-t 95% CIs on every KPI; a `slow` marker gates the heavy engine / BFS-routing / huge-bundle tests, so the default `pytest` runs the fast suite (~30 s) and `pytest --runslow` runs the full sweep (~20-30 min)

> Master's thesis · Miami University · 2024–2026

---

## 🎯 Project Goals

1. **Standardize inputs**: One canonical format converted to any simulator
2. **Ensure reproducibility**: Deterministic pipelines with hash verification
3. **Enable fair comparison**: Same scenarios, same metrics, different engines
4. **Support research**: Ready-to-use benchmarks for thesis/publication

---

## ✅ Current Status

| Component                                                        | Status                                                                                                                                                     |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Canonical Schema (v0)                                            | ✅ Stable                                                                                                                                                  |
| Scenario Validator                                               | ✅ Complete                                                                                                                                                |
| SUMO Adapter                                                     | ✅ Complete (microscopic + meso)                                                                                                                           |
| MATSim Adapter                                                   | ✅ Complete (single-iteration meso)                                                                                                                        |
| DTALite Adapter (3rd primary)                                    | ✅ Complete (CPU mesoscopic DTA, runs on Mac/Linux)                                                                                                        |
| 95 % CIs on every KPI                                            | ✅ Complete (Student's t)                                                                                                                                  |
| Execution Harness                                                | ✅ Complete (`run.py` + RunSpec)                                                                                                                           |
| Metrics & Plots                                                  | ✅ Complete (10 thesis figures)                                                                                                                            |
| Test Suite                                                       | ✅ 668 tests across 31 files (fast default `pytest` ~30 s: 522 pass, 146 skip; full `pytest --runslow` ~20-30 min; 13 SUMO netconvert tests skip on arm64) |
| Bundled scenarios: `chicago_1k_car`, `nyc_10k_car`, `la_50k_car` | ✅ Generated, validated, SHA-256-stamped manifests                                                                                                         |
| Visualization Component (opt-in)                                 | ✅ Complete (7 map types, OD choropleths, link load, congestion, travel time, route diversity, animated flow)                                              |

The 200K / 500K tiers are not committed (their network/signals files exceed GitHub's 100 MB limit); regenerate them locally via the helper scripts in `scripts/`.

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
ratios. See [doc/RESULTS_GUIDE.md](doc/RESULTS_GUIDE.md) for how to read
the audit output, and [doc/EXPERIMENT_LOG.md](doc/EXPERIMENT_LOG.md) §3
for the measured Q1–Q4 results from the canonical cluster runs.

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
├── doc/                    # Engineering docs (architecture, reproduction, Pitzer, engine evaluations)
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
│                           # analyze_scenarios.py, generate_scorecard.py,
│                           # recover_partial_summary.py, plus
│                           # download_census_tracts.py + download_tiger_roads.py
│                           # for the visualization shapefile cache)
├── runspecs/               # Benchmark configurations (YAML)
├── scenarios/              # Bundled canonical scenarios (chicago_1k_car,
│                           # nyc_10k_car, la_50k_car; the 200K/500K tiers
│                           # are generated on demand via scripts/)
├── lib/matsim-15.0/        # MATSim JAR + libs (see SETUP.md)
├── runs/                   # Simulation output (gitignored)
├── cache/                  # Overpass HTTP cache + US Census shapefiles (gitignored)
├── tests/                  # pytest test suite (668 tests across 31 files; slow tests gated behind --runslow)
├── visualization/          # Opt-in geographic-map renderer
├── cluster/                # SLURM sbatch templates + example runs (OSC)
├── run.py                  # Main CLI entry point
├── generate.py             # Scenario generator entry point
├── help.py                 # In-CLI help system (curses TUI + topics)
├── setup_simforge.py       # One-command bootstrap installer
├── requirements.lock       # Exact pinned deps (canonical install)
├── requirements.txt        # Loose ranges (development)
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

| Adapter | Engine                           | Traffic Model                                  | Native inputs written                                 |
| ------- | -------------------------------- | ---------------------------------------------- | ----------------------------------------------------- |
| SUMO    | eclipse-sumo 1.26+               | Microscopic / Mesoscopic                       | net.net.xml, routes.rou.xml, toy.sumocfg              |
| MATSim  | MATSim 15                        | Activity-based, single iteration               | network.xml, plans.xml, config.xml                    |
| DTALite | path4gmns 0.10+ (DTALiteClassic) | CPU mesoscopic Dynamic Traffic Assignment (UE) | node.csv + link.csv + demand.csv + settings.{csv,yml} |

LPSim, POLARIS, and QarSUMO were evaluated and rejected, see the engine evaluations in [`doc/engines/`](doc/engines/).

> **DTALite ships inside `path4gmns`.** Pip-installable, CPU-only, runs on Mac (arm64/x86_64), Linux x86_64, and Windows. The pinned version is in [`lib/dtalite/manifest.json`](lib/dtalite/manifest.json). On macOS the bundled binary needs OpenMP: `brew install libomp`.

---

## 📈 Metrics

- **Fidelity**: RMSE, GEH, KS statistic
- **Scalability**: Wall-clock runtime, throughput (vehicles/sec)
- **Reproducibility**: R = 1 − σ/μ across repeats

---

## 🧪 Testing

```bash
pytest tests/ -v             # Fast suite (default, ~30 s): unit + small-bundle integration; slow tests skipped (this run: 522 pass, 146 skip)
pytest tests/ -v --runslow   # Full suite (~20-30 min, pre-ship / CI gate): all 668 tests; 13 SUMO netconvert tests skip on Apple Silicon (arm64), they run on Linux
pytest tests/ -v -k sumo     # SUMO-related tests only
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

- **State-aware BFS routing at conversion time**, deterministic, engine-independent routes that respect OSM-extracted turn restrictions
- **MATSim `lastIteration=0`**, single-pass execution for fair cross-simulator comparison
- **SHA-256 manifest**, integrity verification before every simulation run
- **Census-calibrated demand**, population-weighted origins, real commute times, per-person empirical departures from PUMS JWMNP (~70–72 % realism)
- **OSM-grounded signal placement**, signals only at nodes carrying `highway=traffic_signals`, rather than a `degree ≥ 4` heuristic
- **Modelgen-grounded trip purposes**, HBW (AM + PM) commutes plus parent-with-kid HBSchool chains derived from cityscape `schedule[0,1]` + AGEP + OSM `building.kind`; six-purpose taxonomy on `demand.csv`
- **Cross-engine vehicle parameter alignment**, single canonical car description in `adapters/common/vehicle_types.py` consumed by all three adapters; SUMO `length+minGap` ≡ MATSim effective `length` ≡ DTALite PCE 1.0, regression-pinned by `tests/test_vehicle_types.py`

For detailed architecture documentation, see [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md).

---

## 🗺️ Geographic Visualization (opt-in)

A standalone visualization component under `visualization/`
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

| Document                                                   | Description                                                                                                                                                                                                                                                    |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [SETUP.md](SETUP.md)                                       | Installation guide (local + OSM data)                                                                                                                                                                                                                          |
| [doc/PITZER.md](doc/PITZER.md)                             | Supercomputer (OSC Pitzer) setup and SLURM                                                                                                                                                                                                                     |
| [TESTING.md](TESTING.md)                                   | Test suite layout and how to run subsets                                                                                                                                                                                                                       |
| [CHANGELOG.md](CHANGELOG.md)                               | Notable changes per release                                                                                                                                                                                                                                    |
| [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md)                 | End-to-end system architecture                                                                                                                                                                                                                                 |
| [doc/SCENARIO_GENERATION.md](doc/SCENARIO_GENERATION.md)   | Data sources, generation pipeline, realism                                                                                                                                                                                                                     |
| [doc/REPRODUCING.md](doc/REPRODUCING.md)                   | Full reproduction guide for thesis results                                                                                                                                                                                                                     |
| [doc/RESULTS_GUIDE.md](doc/RESULTS_GUIDE.md)               | What each generated figure/table means                                                                                                                                                                                                                         |
| [doc/GLOSSARY.md](doc/GLOSSARY.md)                         | Acronyms and term definitions                                                                                                                                                                                                                                  |
| [doc/SIMULATION_PARADIGMS.md](doc/SIMULATION_PARADIGMS.md) | Macro / meso / micro reference + per-engine support                                                                                                                                                                                                            |
| [doc/LICENSING.md](doc/LICENSING.md)                       | Per-component license declarations                                                                                                                                                                                                                             |
| [doc/DATA_MANAGEMENT.md](doc/DATA_MANAGEMENT.md)           | Data sources, PII policy, retention, ethics                                                                                                                                                                                                                    |
| [doc/EXPERIMENT_LOG.md](doc/EXPERIMENT_LOG.md)             | Chronological measurement journal                                                                                                                                                                                                                              |
| [doc/CONTAINER_USAGE.md](doc/CONTAINER_USAGE.md)           | Docker / Singularity (GHCR) container workflow                                                                                                                                                                                                                 |
| [doc/MODELGEN_AND_MODES.md](doc/MODELGEN_AND_MODES.md)     | Census ModelGen provenance + travel-mode handling                                                                                                                                                                                                              |
| [doc/engines/](doc/engines/)                               | Engine comparison + LPSim/QarSUMO evaluations                                                                                                                                                                                                                  |
| [canonical/schema/](canonical/schema/)                     | Schema specifications (v0)                                                                                                                                                                                                                                     |
| `adapters/*/MAPPING.md`                                    | Per-adapter field mapping rules                                                                                                                                                                                                                                |
| [visualization/README.md](visualization/README.md)         | Geographic visualization (opt-in, 7 map types)                                                                                                                                                                                                                 |
| [CONTRIBUTING.md](CONTRIBUTING.md)                         | Contribution workflow and code style                                                                                                                                                                                                                           |
| `python help.py`                                           | In-CLI help: curses TUI in a terminal, `python help.py <topic>` (overview / setup / generate / run / scripts / cities / modes / adapters / metrics / evaluation / schema / benchmark / tests / analyzer / visualization / troubleshooting) for paste-safe text |

---
