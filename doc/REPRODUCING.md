# Reproducing This Thesis

This guide explains how to reproduce all experiments from the SimForge thesis using the code in this repository.

## Prerequisites

### Hardware Requirements

**Minimum (development/testing):**

- Any modern laptop/desktop
- 8 GB RAM
- 10 GB disk space

**Recommended (full experiments):**

- 16+ GB RAM
- 50+ GB disk space
- NVIDIA GPU with CUDA 11+ (for QarSUMO)

### Software Requirements

| Software | Version | Required For            |
| -------- | ------- | ----------------------- |
| Python   | 3.10+   | Framework               |
| SUMO     | 1.18+   | SUMO/QarSUMO simulation |
| Java     | 17+     | MATSim simulation       |
| Git      | 2.0+    | Repository cloning      |

---

## Quick Setup (5 minutes)

```bash
# 1. Clone repository
git clone <repo-url>
cd SimForge

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Verify installation
python -m pipeline.validation.validate_bundle scenarios/toy_2x2_grid
# Expected: [VALID] Scenario bundle at: .../scenarios/toy_2x2_grid
```

---

## Installing Simulators

### SUMO (macOS)

```bash
brew install sumo
sumo --version
# Expected: SUMO 1.20.0 or higher
```

### SUMO (Ubuntu/Debian)

```bash
sudo add-apt-repository ppa:sumo/stable
sudo apt-get update
sudo apt-get install sumo sumo-tools
```

### MATSim

MATSim is pre-installed in this repository:

```
lib/matsim-15.0/
├── matsim-15.0.jar
└── libs/   # Dependencies
```

Verify Java:

```bash
java -version
# Expected: openjdk 17.x or higher
```

### QarSUMO (Optional - GPU only)

QarSUMO requires NVIDIA GPU with CUDA. Download from:
https://github.com/LLNL/QarSUMO

If QarSUMO is not available, the framework automatically falls back to standard SUMO.

---

## Running Experiments

### Step 1: Validate All Scenarios

```bash
# Validate toy scenario
python -m pipeline.validation.validate_bundle scenarios/toy_2x2_grid

# Validate city scenarios
python -m pipeline.validation.validate_bundle scenarios/sioux_falls_tier50k
python -m pipeline.validation.validate_bundle scenarios/austin_tier50k
python -m pipeline.validation.validate_bundle scenarios/berlin_tier50k
```

All should report `[VALID]`.

### Step 2: Run Toy Scenario (Sanity Check)

```bash
# Test all engines on toy scenario
python -m execution.run_benchmark runspecs/dev_toy.yaml
```

Expected: ~30 seconds, all engines pass.

### Step 3: Run Development Benchmark

```bash
# Quick 50k benchmark (mesoscopic only)
python -m execution.run_benchmark runspecs/dev_mesoscopic.yaml
```

Expected: ~5-10 minutes.

### Step 4: Run Full Thesis Benchmark

```bash
# Full 50k matrix (all engines, 3 seeds)
python -m execution.run_benchmark runspecs/full_50k_mesoscopic.yaml
```

Expected: ~30-60 minutes depending on hardware.

### Step 5: Run Complete Matrix (Optional)

```bash
# Complete thesis matrix (all cities, all tiers, all engines)
python -m execution.run_benchmark runspecs/thesis_benchmark_matrix.yaml
```

Expected: Several hours to days depending on tier sizes.

---

## Collecting Results

### Output Location

Results are stored in:

```
runs/
├── <scenario>/
│   ├── <engine>/
│   │   └── <mode>/
│   │       ├── seed_42/
│   │       ├── seed_43/
│   │       └── seed_44/
```

### Extracting Metrics

```bash
# Extract travel times from SUMO output
python -c "
from evaluation.metrics.travel_time import extract_sumo_travel_times
times = extract_sumo_travel_times('runs/sioux_falls_sumo_meso/sumo/seed_42/output/tripinfo.xml')
print(f'Mean travel time: {sum(times)/len(times):.1f}s')
"
```

### Generating Summary

```bash
# Run metrics collection
python -m evaluation.collect_results runs/
```

This generates `results/summary.csv` with all metrics.

---

## Expected Results

### Toy Scenario (6 trips)

| Engine     | Runtime | Mean Travel Time |
| ---------- | ------- | ---------------- |
| SUMO micro | ~0.03s  | ~21s             |
| SUMO meso  | ~0.03s  | ~21s             |
| QarSUMO\*  | ~0.03s  | ~21s             |
| MATSim     | ~7s     | ~21s             |

\*Falls back to SUMO without GPU

### Sioux Falls 50k (50,000 trips)

| Engine     | Runtime | Status   |
| ---------- | ------- | -------- |
| SUMO micro | ~120s   | Expected |
| SUMO meso  | ~15s    | Expected |
| MATSim     | ~45s    | Expected |

---

## Troubleshooting

### "MATSim ClassNotFoundException"

**Solution:** The classpath needs all JARs from `libs/` folder. This is handled automatically by the adapter.

### "QarSUMO not found"

**Expected:** QarSUMO requires NVIDIA GPU. Falls back to SUMO automatically.

### "SUMO command not found"

**Solution:**

```bash
# macOS
brew install sumo

# Linux
sudo apt-get install sumo
```

### "Java version too old"

**Solution:** Install Java 17+:

```bash
# macOS
brew install openjdk@17

# Linux
sudo apt-get install openjdk-17-jdk
```

### Slow MATSim runs

MATSim has JVM startup overhead (~5-7s). This is normal for small scenarios.

---

## Reproducing Specific Figures

### Figure 1: Travel Time CDFs

```bash
# Generate CDF data
python scripts/plot_travel_time_cdf.py runs/ figures/travel_time_cdf.png
```

### Figure 2: Runtime Comparison

```bash
# Generate bar chart
python scripts/plot_runtime_comparison.py results/summary.csv figures/runtime.png
```

### Figure 3: Scaling Analysis

```bash
# Requires 50k, 500k, 5M tier runs
python scripts/plot_scaling.py results/summary.csv figures/scaling.png
```

---

## Version Information

This thesis was produced with:

| Component | Version |
| --------- | ------- |
| SimForge  | v1.0.0  |
| Python    | 3.13.2  |
| SUMO      | 1.20.0  |
| MATSim    | 15.0    |
| Java      | 17.0.13 |

To reproduce exactly, use these versions.

---

## Contact

For questions about reproducing this work:

- Open an issue on the repository
- Email: [thesis author email]

---

## Citation

```bibtex
@mastersthesis{simforge2026,
  author = {Dharakula, Phani},
  title = {SimForge: A Reproducible Cross-Simulator Benchmarking Framework for Urban Traffic Simulation},
  school = {University of Texas at Austin},
  year = {2026}
}
```
