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

| Component | Status |
|-----------|--------|
| Canonical Schema v0 | ✅ Complete |
| Scenario Validator | ✅ Complete |
| SUMO Adapter | ✅ Complete (micro + meso) |
| QarSUMO Adapter | ✅ Complete (falls back to SUMO) |
| MATSim Adapter | ✅ Complete |
| Execution Harness | ✅ Complete |
| Metrics Library | ✅ Complete |
| Toy Scenario | ✅ Validated |
| Sioux Falls 50k | ✅ Validated |
| Austin 50k | ✅ Validated |
| Berlin 50k | ✅ Validated |

---

## 🛠️ Quick Start

### Prerequisites

- Python 3.10+
- SUMO 1.18+ (optional, for simulation)
- Java 17+ (optional, for MATSim)

### Installation

\`\`\`bash
# Clone repository
git clone <repo-url>
cd SimForge

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
\`\`\`

### Validate a Scenario

\`\`\`bash
python -m pipeline.validation.validate_bundle scenarios/toy_2x2_grid
\`\`\`

### Run SUMO Simulation

\`\`\`bash
python -m adapters.sumo.cli scenarios/toy_2x2_grid runs/test_sumo
sumo -c runs/test_sumo/toy.sumocfg
\`\`\`

### Run MATSim Simulation

\`\`\`bash
python -m adapters.matsim.cli scenarios/toy_2x2_grid runs/test_matsim
\`\`\`

### Run Full Benchmark

\`\`\`bash
python -m execution.run_benchmark runspecs/dev_mesoscopic.yaml
\`\`\`

---

## 📂 Repository Structure

\`\`\`
SimForge/
├── adapters/                    # Simulator-specific converters
│   ├── sumo/                    # SUMO adapter
│   ├── qarsumo/                 # GPU-accelerated SUMO
│   └── matsim/                  # Activity-based simulator
├── canonical/schema/            # Schema documentation
├── doc/chapters/                # Thesis documentation
├── evaluation/metrics/          # Metrics computation
├── execution/                   # Benchmark harness
├── pipeline/                    # Data processing
├── runspecs/                    # Benchmark configurations
├── scenarios/                   # Canonical bundles
├── lib/matsim-15.0/             # MATSim JAR + libs
├── runs/                        # Output directory (gitignored)
├── tests/                       # pytest test suite
├── requirements.txt
├── SETUP.md                     # Detailed setup guide
└── TODO.md                      # Development roadmap
\`\`\`

---

## 📊 Canonical Schema

| File | Format | Description |
|------|--------|-------------|
| \`network.xml\` | XML | Road network (nodes + links) |
| \`demand.csv\` | CSV | Travel demand (OD trips) |
| \`signals.xml\` | XML | Traffic signal timing |
| \`config.xml\` | XML | Scenario metadata |
| \`manifest.xml\` | XML | File inventory + SHA-256 hashes |

---

## 🔧 Adapters

| Adapter | Engine | Traffic Model | Output |
|---------|--------|---------------|--------|
| SUMO | SUMO 1.20 | Microscopic/Mesoscopic | net.xml, rou.xml |
| QarSUMO | QarSUMO | GPU-accelerated | SUMO + GPU config |
| MATSim | MATSim 15 | Activity-based meso | network.xml, plans.xml |

---

## 🏃 Running Benchmarks

\`\`\`bash
# Quick development test
python -m execution.run_benchmark runspecs/dev_mesoscopic.yaml

# Full 50k benchmark
python -m execution.run_benchmark runspecs/full_50k_mesoscopic.yaml

# Filter by scenario
python -m execution.run_benchmark runspecs/dev_mesoscopic.yaml --scenario sioux_falls_tier50k
\`\`\`

---

## 📈 Metrics

- **Fidelity**: RMSE, GEH, KS statistic
- **Scalability**: Runtime, throughput (vehicles/sec)
- **Reproducibility**: R = 1 - σ/μ

---

## 🧪 Testing

\`\`\`bash
pytest                           # Run all tests
pytest tests/test_validator_toy.py -v  # Specific test
\`\`\`

---

## 📚 Documentation

- [SETUP.md](SETUP.md) - Detailed installation guide
- [canonical/schema/](canonical/schema/) - Schema specifications
- [adapters/sumo/MAPPING.md](adapters/sumo/MAPPING.md) - SUMO mapping rules
- [adapters/matsim/MAPPING.md](adapters/matsim/MAPPING.md) - MATSim mapping rules
- [doc/chapters/](doc/chapters/) - Thesis chapter drafts

---

## 🎓 Citation

\`\`\`bibtex
@mastersthesis{simforge2026,
  author = {Dharakula, Phani},
  title = {SimForge: A Reproducible Cross-Simulator Benchmarking Framework},
  school = {University of Texas at Austin},
  year = {2026}
}
\`\`\`

---

## 📄 License

MIT License
