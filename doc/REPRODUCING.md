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

# 4. Generate scenario data
python scripts/generate_chicago_5k.py
python scripts/generate_nyc_5k.py
python scripts/generate_la_5k.py

# 5. Verify installation
python -m pipeline.validation.validate_bundle scenarios/chicago_5k
# Expected: [VALID] Scenario bundle at: .../scenarios/chicago_5k
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

### QarSUMO (Optional — GPU only)

QarSUMO requires NVIDIA GPU with CUDA. Download from:
https://github.com/LLNL/QarSUMO

If QarSUMO is not available, the framework automatically falls back to standard SUMO.

---

## Running Experiments

### Step 1: Validate All Scenarios

```bash
python -m pipeline.validation.validate_bundle scenarios/chicago_5k
python -m pipeline.validation.validate_bundle scenarios/nyc_5k
python -m pipeline.validation.validate_bundle scenarios/la_5k
```

All should report `[VALID]`.

### Step 2: Quick Sanity Check

```bash
# Run a single scenario with SUMO mesoscopic
python run.py --scenario chicago_5k --engine sumo --mode meso --repeats 1
```

Expected: completes in under 30 seconds.

### Step 3: Run Full 5K Benchmark

```bash
# Full benchmark: 3 cities × 3 engines × mesoscopic × 3 repeats = 27 runs
python -m execution.run_benchmark runspecs/benchmark_5k.yaml
```

Expected: 10–30 minutes depending on hardware.

### Step 4: Run via CLI (Alternative)

```bash
# Run all combinations using the main CLI
python run.py --mode meso --repeats 3
```

---

## Collecting Results

### Output Location

Results are stored in:

```
runs/
├── benchmark_<timestamp>/
│   ├── <scenario>_<engine>_<mode>_seed<N>/
│   │   ├── native_files/     # Simulator-native input files
│   │   ├── tripinfo.xml      # SUMO trip-level output
│   │   └── statistics.xml    # SUMO summary statistics
│   └── benchmark_results.json
```

### Extracting Metrics

```bash
# Analyze benchmark results
python -m evaluation.analyze_benchmark runs/benchmark_<timestamp>/benchmark_results.json
```

### Generating Thesis Plots

```bash
python -m evaluation.generate_plots runs/benchmark_<timestamp>/benchmark_results.json
```

---

## Expected Results (5K Tier)

### Chicago 5K (5,000 trips, 3,343 nodes, 8,362 links)

| Engine    | Mode | Expected Runtime |
| --------- | ---- | ---------------- |
| SUMO      | meso | ~2–5s            |
| QarSUMO\* | meso | ~2–5s            |
| MATSim    | meso | ~10–15s          |

### NYC 5K (5,000 trips, 1,913 nodes, 3,877 links)

| Engine    | Mode | Expected Runtime |
| --------- | ---- | ---------------- |
| SUMO      | meso | ~1–3s            |
| QarSUMO\* | meso | ~1–3s            |
| MATSim    | meso | ~8–12s           |

### LA 5K (5,000 trips, 6,333 nodes, 17,685 links)

| Engine    | Mode | Expected Runtime |
| --------- | ---- | ---------------- |
| SUMO      | meso | ~3–8s            |
| QarSUMO\* | meso | ~3–8s            |
| MATSim    | meso | ~12–20s          |

\*Falls back to SUMO without GPU

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

MATSim has JVM startup overhead (~5–7s). This is normal for small scenarios.

---

## Reproducing Specific Figures

```bash
# Generate all thesis figures from benchmark results
python -m evaluation.generate_plots runs/<benchmark_dir>/benchmark_results.json
```

Individual plot scripts are available in `evaluation/generate_plots.py`.

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

## Citation

```bibtex
@mastersthesis{simforge2026,
  author = {Dharakula, Phani},
  title  = {SimForge: A Reproducible Cross-Simulator Benchmarking Framework
            for Urban Traffic Simulation},
  school = {University of Texas at Austin},
  year   = {2026}
}
```
