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
- SUMO 1.18+ (optional, for simulation)
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
python scripts/generate_chicago_5k.py
python scripts/generate_nyc_5k.py
python scripts/generate_la_5k.py
```

### Validate a Scenario

```bash
python -m pipeline.validation.validate_bundle scenarios/chicago_5k
```

### Run Simulations

```bash
# Run everything (all scenarios × all engines × all modes)
python run.py

# Run a specific scenario with a specific engine
python run.py --scenario chicago_5k --engine sumo --mode meso

# List available options
python run.py --list
```

### Run Full Benchmark

```bash
python -m execution.run_benchmark runspecs/benchmark_5k.yaml
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
│   ├── chicago_5k/
│   ├── nyc_5k/
│   └── la_5k/
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

## 📚 Documentation

- `SETUP.md` — Detailed installation guide
- `canonical/schema/` — Schema specifications
- `adapters/sumo/SUMO_NOTES.md` — SUMO mapping rules
- `adapters/matsim/MATSIM_NOTES.md` — MATSim mapping rules
- `doc/chapters/` — Thesis chapter drafts

---

## 🎓 Citation

```bibtex
@mastersthesis{simforge2026,
  author = {Dharakula, Phani},
  title  = {SimForge: A Reproducible Cross-Simulator Benchmarking Framework},
  school = {University of Texas at Austin},
  year   = {2026}
}
```

---

## 📄 License

MIT License
