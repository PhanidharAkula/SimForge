# Reproducing This Thesis

This guide explains how to reproduce all experiments from the SimForge thesis using the code in this repository.

## Prerequisites

### Hardware Requirements

**Minimum (for the bundled 1K scenarios + full unit suite):**

- Any modern laptop/desktop
- 8 GB RAM
- 5 GB disk space (caches included)

**Recommended (regenerating the larger 50K – 500K tiers):**

- 16+ GB RAM
- 50+ GB disk space
- NVIDIA GPU with CUDA 11+ (only needed if you want true GPU-accelerated QarSUMO; the framework falls back to SUMO otherwise)

### Software Requirements

| Software   | Version       | Required For                                            |
| ---------- | ------------- | ------------------------------------------------------- |
| Python     | 3.10+         | Framework                                               |
| SUMO       | 1.20+         | SUMO/QarSUMO simulation                                 |
| Java       | 17+           | MATSim simulation                                       |
| Git        | 2.0+          | Repository cloning                                      |
| osmium-tool| 1.14+ (opt)   | Optional CLI sanity checks on PBFs; not required        |

Python dependencies (installed via `requirements.txt`):

| Package     | Version pin        | Used For                                                          |
| ----------- | ------------------ | ----------------------------------------------------------------- |
| `osmnx`     | `>=2.0,<3`         | OSM graph parsing + bbox truncation (network stage); v2.x positional `bbox=(W,S,E,N)` API |
| `osmium`    | `>=4.0` (pyosmium) | PBF slicing (`FileProcessor` + `BackReferenceWriter`)             |
| `networkx`  | (latest)           | Graph representation between osmnx and the canonical writer       |
| `geopandas` | `>=0.9,<1`         | Geometry handling during network conversion                       |
| `pandas`    | (latest)           | Demand + census data frames                                       |

---

## Quick Setup (5 minutes)

```bash
git clone <repo-url>
cd SimForge

python3 setup_simforge.py     # checks prereqs, creates .venv, installs deps, downloads MATSim JAR
source .venv/bin/activate

# Fetch the hash-pinned OSM PBFs (~2.1 GB across IL / NY / CA state extracts).
# Required before regenerating any scenario; skipped if files are already present.
python tools/download_osm.py

# Confirm the bundled scenario validates cleanly
python -m pipeline.validation.validate_bundle scenarios/chicago_1k_car
# Expected: ✓ VALID
```

(For a manual install path, see [SETUP.md](../SETUP.md). For the OSM data source, coverage, and hash-pinning, see [doc/SCENARIO_GENERATION.md §4](SCENARIO_GENERATION.md).)

### Running vs. regenerating — PBF requirement

The pre-built `scenarios/*_1k_car/` bundles already contain `network.xml`; reproducing the published simulation results does **not** require any OSM data. You only need the PBFs when:

- Regenerating any scenario (e.g. `scripts/02_small_commute.py` onwards), **or**
- Running `python -m pipeline.network.warmup` against a scenario whose network was removed.

### Optional: pre-warm a scenario that was regenerated

The network stage is fully deterministic, so pre-warming is only necessary when a bundle has been (re)generated from scratch on a machine without a warm disk cache:

```bash
python -m pipeline.network.warmup            # warm every scenarios/* bundle
python -m pipeline.network.warmup --dry-run  # report only
```

If `osm_data/<state>-<date>.osm.pbf` is missing for a target city, the pipeline falls back to the Overpass API (slower, not hash-pinned). The fallback is intentionally preserved for cities we have not yet committed a PBF for.

---

## Installing Simulators

### SUMO (macOS)

```bash
brew install sumo
sumo --version    # Expect 1.20.0+
```

### SUMO (Ubuntu/Debian)

```bash
sudo add-apt-repository ppa:sumo/stable
sudo apt-get update
sudo apt-get install sumo sumo-tools
```

### MATSim

`setup_simforge.py` downloads the MATSim 15.0 release JAR into `lib/matsim-15.0/`. Verify Java is on PATH:

```bash
java -version    # Expect openjdk 17.x or higher
```

### QarSUMO (optional — GPU only)

QarSUMO requires NVIDIA GPU with CUDA. Without it, the QarSUMO adapter falls back to standard SUMO and emits identical output. Source: <https://github.com/LLNL/QarSUMO>.

---

## Running the Canonical Stress Test

The thesis figures are produced by `runspecs/stress_test.yaml` — a 4-cell matrix of `chicago_1k_car × {SUMO meso, SUMO micro, QarSUMO meso, MATSim meso}` with 3 repeats each (MATSim runs 2 repeats since it is deterministic).

```bash
# 1. Sanity check (one run, ~30 s)
python run.py --scenario chicago_1k_car --engine sumo --mode meso --repeats 1

# 2. Full benchmark (~1 minute on a laptop, ~2 minutes on cluster CPU)
python -m execution.run_benchmark runspecs/stress_test.yaml

# 3. Generate analysis tables
python -m evaluation.analyze_benchmark runs/stress_test/benchmark_results_stress_test.json

# 4. Render the 9 thesis figures
python -m evaluation.generate_plots runs/stress_test/benchmark_results_stress_test.json
```

---

## Generating the Larger Tiers (Optional)

The repo only commits the `chicago_1k_car` bundle. To recreate the 10K/50K/200K/500K tiers used for scalability discussion:

```bash
python scripts/02_small_commute.py     # 10K NYC car, 7–9 AM
python scripts/03_medium_multimodal.py # 50K LA car+transit+bike, 6–10 AM
python scripts/04_large_full_day.py    # 200K Chicago car+transit, 24 h
python scripts/05_stress_test.py       # 500K NYC car, 6–10 AM
```

Each writes a fresh bundle into `scenarios/<id>/` and is then runnable through `run.py` or by adding it to a runspec.

> **Apple Silicon caveat:** SUMO 1.20's `netconvert` crashes on networks above ~3,000 nodes on arm64 (a SUMO bug, not SimForge's). The 1K bundles run cleanly; the 200K and 500K tiers must be run on Linux/HPC.

### Regenerating on a Supercomputer (OSC Pitzer)

The 200K and 500K tiers were produced on the Ohio Supercomputer Center's Pitzer cluster. The full workflow — module setup, PBF / ModelGen rsync, per-tier SLURM templates, monitoring, and troubleshooting — is documented in [doc/PITZER.md](PITZER.md). Short version:

```bash
# From your laptop
rsync -avh osm_data/   pitzer:SimForge/osm_data/
rsync -avh modelgen/   pitzer:SimForge/modelgen/

# On Pitzer (login node)
module load python/3.12 openjdk
cd ~/SimForge && source .venv/bin/activate
sbatch jobs/gen_nyc_500k.sbatch        # template in doc/PITZER.md §7
```

---

## Collecting Results

### Output Layout

```
runs/stress_test/
├── benchmark_results_stress_test.json
└── chicago_1k_car/
    ├── sumo/
    │   ├── seed_42/
    │   │   ├── feasibility_report.json
    │   │   ├── tripinfo.xml
    │   │   ├── statistics.xml
    │   │   └── (SUMO native files)
    │   ├── seed_43/
    │   └── seed_44/
    ├── qarsumo/
    └── matsim/
```

`feasibility_report.json` is the audit trail proving every engine was fed the same trip set (see [CHANGELOG.md](../CHANGELOG.md), Addenda 1–2).

### Extracting Metrics

```bash
python -m evaluation.analyze_benchmark runs/stress_test/benchmark_results_stress_test.json --markdown --latex
```

Produces:

- Summary table (one row per `(scenario, engine, mode)` cell)
- Runtime performance table
- Reproducibility table (R = 1 − σ/μ across repeats)
- **Coverage diagnostic** — flags low-sample (`n < 3`) cells, asymmetric coverage, and silently-failed cells

### Generating Plots

```bash
python -m evaluation.generate_plots runs/stress_test/benchmark_results_stress_test.json
```

Renders Fig 5.1 – Fig 5.9 (PNG + PDF) into `runs/stress_test/plots/`. See [doc/RESULTS_GUIDE.md](RESULTS_GUIDE.md) for what each figure shows.

---

## Expected Results (1K Tier — measured on Apple M4 Pro)

These are the numbers from the most recent canonical stress test (see CHANGELOG.md → Addendum 3):

| Scenario       | Engine  | Mode  | Trips simulated  | Avg TT (s)  | Runtime (s)  | R-Score |
| -------------- | ------- | ----- | ---------------- | ----------- | ------------ | ------- |
| chicago_1k_car | matsim  | meso  | **1000 (100 %)** | 195.7 ± 0.0 | 10.19 ± 0.16 | 1.0000  |
| chicago_1k_car | qarsumo | meso  | 995 (99.5 %)     | 204.1 ± 0.4 |  0.28 ± 0.01 | 0.9981  |
| chicago_1k_car | sumo    | meso  | 995 (99.5 %)     | 204.1 ± 0.4 |  0.27 ± 0.00 | 0.9981  |
| chicago_1k_car | sumo    | micro | 940 (94.0 %)     | 288.0 ± 0.8 |  1.24 ± 0.01 | 0.9971  |

Total wall-clock for the 11-run matrix: ~27 s.

The remaining 5 – 60 trip gap is **engine-internal mobsim behaviour** (SUMO refuses congested edge insertions; MATSim's queue mobsim never refuses). It is the simulation outcome we want to *measure*, not an input asymmetry — every `feasibility_report.json` records `feasible_trips == total_trips == 1000`.

---

## Troubleshooting

| Problem                          | Solution                                                                                                |
| -------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `MATSim ClassNotFoundException`  | The classpath includes everything in `libs/` automatically. Re-run `setup_simforge.py` to repair the JAR. |
| `QarSUMO not found`              | Expected without an NVIDIA GPU — the adapter falls back to SUMO and emits a log line saying so.          |
| `SUMO command not found`         | `brew install sumo` (macOS) or `apt-get install sumo` (Linux).                                           |
| `Java version too old`           | `brew install openjdk@17` (macOS) or `apt-get install openjdk-17-jdk` (Linux).                            |
| Slow MATSim runs                 | MATSim has ~5 – 7 s JVM startup overhead per run; this dominates wall-clock for the 1K tier.              |
| `FileNotFoundError: osm_data/illinois-*.osm.pbf` during generation | Run `python tools/download_osm.py` to fetch the hash-pinned PBFs.                      |
| `SHA-256 mismatch` on a PBF      | A partial download — delete the offending file in `osm_data/` and re-run `tools/download_osm.py`.       |
| `osmnx.truncate` TypeError on `bbox` kwargs | osmnx 1.x is installed. `requirements.txt` now requires `osmnx>=2.0,<3` (positional `bbox=(W,S,E,N)`). Run `pip install -U "osmnx>=2.0,<3"`. |
| Overpass fallback hangs          | Only reachable for cities without a committed PBF. Pre-fetch with `pipeline.network.warmup`, or add the PBF to `osm_data/manifest.json`. |
| `cache/` grows large             | `tools/clean.sh --all` to wipe both Python bytecode and the OSM HTTP cache. (PBFs in `osm_data/` are kept.) |

---

## Reproducing Specific Figures

All nine thesis figures are emitted by a single command:

```bash
python -m evaluation.generate_plots runs/stress_test/benchmark_results_stress_test.json
```

| Figure   | What it shows                                              |
| -------- | ---------------------------------------------------------- |
| Fig 5.1  | Cross-engine runtime bar chart (mean + error bars)         |
| Fig 5.2  | Reproducibility heatmap (R-Score per cell)                 |
| Fig 5.3  | Travel-time comparison (mean + error bars)                 |
| Fig 5.4  | Engine summary panel                                       |
| Fig 5.5  | Speedup analysis (relative to mesoscopic baseline)         |
| Fig 5.6  | Micro vs meso comparison                                   |
| Fig 5.7  | Runtime variability (boxplot per cell)                     |
| Fig 5.8  | P95 tail-latency analysis                                  |
| Fig 5.9  | Throughput (vehicles per second per core)                  |

See [doc/RESULTS_GUIDE.md](RESULTS_GUIDE.md) for each figure's full interpretation.

---

## Version Information

This thesis was produced with:

| Component | Version |
| --------- | ------- |
| SimForge  | Version_2 (commit `d66747d` or later) |
| Python    | 3.13.2  |
| SUMO      | 1.20.0  |
| MATSim    | 15.0    |
| Java      | 17.0.13 |
| osmnx     | 2.x (`requirements.txt` pins `>=2.0,<3`) |
| osmium (pyosmium) | 4.x |
| OSM PBF snapshots | Geofabrik extracts — exact SHA-256 hashes in `osm_data/manifest.json` |

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
