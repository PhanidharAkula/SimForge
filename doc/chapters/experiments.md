# Chapter 4: Experiments

## 4.1 Experimental Design

### 4.1.1 Research Questions

This experimental study addresses the following research questions:

| RQ  | Question                                                                         | Metric(s)              |
| --- | -------------------------------------------------------------------------------- | ---------------------- |
| RQ1 | How do travel-time distributions compare across simulators for identical inputs? | RMSE, GEH, KS          |
| RQ2 | How does runtime scale with network size and demand volume across engines?       | Wall-clock, throughput |
| RQ3 | How consistent are results across repeated runs with different random seeds?     | $R = 1 - \sigma/\mu$   |
| RQ4 | What are the practical trade-offs between fidelity, speed, and reproducibility?  | Multi-metric analysis  |

### 4.1.2 Independent Variables

**Variable 1: Simulator Engine (4 configurations evaluated)**

| Engine          | Paradigm    | Traffic Model                        | Hardware |
| --------------- | ----------- | ------------------------------------ | -------- |
| SUMO (micro)    | Microscopic | Krauss car-following + lane-changing | CPU      |
| SUMO (meso)     | Mesoscopic  | Queue-based link traversal           | CPU      |
| QarSUMO (meso)  | Mesoscopic  | GPU-accelerated queue model (CPU fallback) | GPU/CPU |
| MATSim          | Mesoscopic  | Activity-based, event-driven queues  | CPU      |

> QarSUMO microscopic is supported by the adapter but not part of the canonical stress test — the GPU path is identical to mesoscopic when CUDA is absent (the adapter falls back to standard SUMO and emits bit-identical output).

**Variable 2: Scenario Scale**

The bundled stress test fixes both networks at the **1K-trip tier** to keep the benchmark runnable on a developer laptop in under one minute. Larger tiers (10K, 50K, 200K, 500K) are generated locally via the helper scripts in `scripts/` and are reserved for HPC runs that probe scaling behaviour.

| Tier         | Trip Count | Helper script                       | Where it runs                |
| ------------ | ---------- | ----------------------------------- | ---------------------------- |
| **Bundled**  | **1,000**  | `scripts/01_quick_test.py`          | Laptop (Apple Silicon)       |
| Small        | 10,000     | `scripts/02_small_commute.py`       | Laptop / cluster             |
| Medium       | 50,000     | `scripts/03_medium_multimodal.py`   | Cluster                      |
| Large        | 200,000    | `scripts/04_large_full_day.py`      | Cluster                      |
| Stress       | 500,000    | `scripts/05_stress_test.py`         | Cluster (Linux only)         |

**Variable 3: City Network (2 metropolitan areas in the canonical stress test)**

| City    | Center            | Radius | Nodes | Links | Largest SCC | Character             |
| ------- | ----------------- | ------ | ----- | ----- | ----------- | --------------------- |
| Chicago | 41.88°N, 87.63°W  | 4 km   | 1,245 | 2,862 | 1,204 (96.7 %) | Dense grid, mixed use  |
| NYC     | 40.76°N, 73.99°W  | 3 km   | 1,066 | 2,078 | 1,014 (95.1 %) | Ultra-dense, Manhattan |

> LA is supported by the generator (`--city la`) and used by `scripts/03_medium_multimodal.py`, but is excluded from the canonical 1K stress test because the bundled scenarios deliberately stay small for developer-machine reproduction.

**Why these cities:**

- **Chicago** — classic American grid; mix of arterials and residential streets; ModelGen census coverage is most complete.
- **NYC** — extremely dense Manhattan grid; one-way streets dominate; Broadway diagonal creates non-grid intersection patterns.

### 4.1.3 Dependent Variables

**Fidelity (RQ1):**

| Metric                 | Formula                                     | Unit          | Interpretation                     |
| ---------------------- | ------------------------------------------- | ------------- | ---------------------------------- |
| Mean travel time       | $\bar{t} = \frac{1}{n}\sum_i t_i$           | seconds       | Central tendency of trip durations |
| P95 travel time        | 95th percentile of $\{t_i\}$                | seconds       | Tail behaviour / worst-case trips  |
| Trip completion rate   | $n_\text{completed} / n_\text{feasible}$    | %             | How many feasible trips reached destination |
| RMSE (cross-simulator) | $\sqrt{\frac{1}{n}\sum(y_i - \hat{y}_i)^2}$ | seconds       | Agreement between two simulators   |
| GEH (link-level)       | $\sqrt{\frac{2(M-C)^2}{M+C}}$               | dimensionless | Traffic engineering fit metric     |
| KS statistic           | $\sup_x \|F_1(x) - F_2(x)\|$                | dimensionless | Distribution shape comparison      |

**Scalability (RQ2):**

| Metric             | Formula                          | Unit         | Interpretation                  |
| ------------------ | -------------------------------- | ------------ | ------------------------------- |
| Wall-clock runtime | `perf_counter()` end – start     | seconds      | Absolute performance            |
| Throughput         | trips_completed / runtime        | trips/sec    | Efficiency metric               |
| SRT                | simulated_time / wall_clock_time | ratio        | Faster-than-real-time indicator |
| Peak memory        | OS-reported peak RSS             | MB           | Hardware requirement            |

**Reproducibility (RQ3):**

| Metric                    | Formula                | Range       | Interpretation                        |
| ------------------------- | ---------------------- | ----------- | ------------------------------------- |
| Reproducibility index $R$ | $1 - \sigma/\mu$       | [-∞, 1.0]   | 1.0 = perfectly deterministic         |
| Max deviation             | $\max_i \|x_i - \mu\|$ | same as KPI | Worst-case variability                |
| CV (coefficient of variation) | $\sigma/\mu$       | [0, ∞)      | Relative variability (lower = better) |

### 4.1.4 Canonical Experimental Matrix

The matrix declared by `runspecs/stress_test.yaml`:

| Phase | Scenarios | Engines × modes | Repeats | Total runs |
| --- | --- | --- | --- | --- |
| Stress test | `chicago_1k_car`, `nyc_1k_car` | SUMO meso, SUMO micro, QarSUMO meso, MATSim meso | 3 (MATSim 2) | **22 runs** |

Total wall-clock on Apple M4 Pro: ~52 s. Every cell completes successfully and every `feasibility_report.json` confirms `feasible_trips == 1000` per scenario.

**Control variables** (held constant across all conditions):

| Parameter                | Value             | Rationale                                  |
| ------------------------ | ----------------- | ------------------------------------------ |
| Random seeds             | 42, 43, 44        | Reproducible; 3 runs per cell              |
| Demand strategy          | Census-calibrated (ModelGen + PUMS) | Consistent realistic inputs |
| Routing                  | BFS shortest path | Deterministic, version-independent         |
| Time horizon             | 1 hour (3,600 s)  | Standard morning peak period               |
| MATSim iterations        | 1 (no replanning) | Fair comparison with SUMO single-pass mode |
| Feasibility filter       | SCC-based         | Same trip set fed to every engine          |

---

## 4.2 Scenario Descriptions

### 4.2.1 `chicago_1k_car`

**Generated**: `python scripts/01_quick_test.py` (equivalent to `python generate.py --city chicago --trips 1000 --modes car --seed 42`)

| Property               | Value                                  |
| ---------------------- | -------------------------------------- |
| Nodes                  | 1,245                                  |
| Links                  | 2,862                                  |
| Largest SCC            | 1,204 nodes (96.7 %), 2,796 links      |
| Bounding box           | 41.842°–41.914° N, -87.678°–-87.582° W |
| Radius from centre     | 4 km                                   |
| Source                 | OpenStreetMap (cached in `cache/`)     |
| Total trips            | 1,000                                  |
| Demand strategy        | Census-calibrated (ModelGen)           |
| Mode                   | 100 % car                              |
| Time window            | 0 – 3,600 s (one-hour morning peak)    |
| Census commuters in bbox | ~15,000 – 25,000                     |

**Key features**: Dense grid pattern with regular block spacing; high intersection density; mixed residential/commercial; multiple highway segments (I-90/94, I-290).

### 4.2.2 `nyc_1k_car`

**Generated**: `python generate.py --city nyc --trips 1000 --modes car --seed 42`

| Property               | Value                                  |
| ---------------------- | -------------------------------------- |
| Nodes                  | 1,066                                  |
| Links                  | 2,078                                  |
| Largest SCC            | 1,014 nodes (95.1 %), 1,997 links      |
| Bounding box           | Midtown Manhattan (3 km radius)        |
| Total trips            | 1,000                                  |
| Demand strategy        | Census-calibrated (ModelGen)           |

**Key features**: Extreme density; predominantly one-way streets; narrow blocks; heavy east-west / north-south split due to Manhattan grid; Broadway diagonal creates complex intersections.

### 4.2.3 Scenario Comparison

| Metric                 | chicago_1k_car | nyc_1k_car |
| ---------------------- | -------------- | ---------- |
| Nodes                  | 1,245          | 1,066      |
| Links                  | 2,862          | 2,078      |
| Links / Node ratio     | 2.30           | 1.95       |
| Largest SCC fraction   | 96.7 %         | 95.1 %     |
| Network radius (km)    | 4              | 3          |

---

## 4.3 Execution Environment

### 4.3.1 Development Environment (Local)

| Component | Specification                       |
| --------- | ----------------------------------- |
| Machine   | MacBook Pro (Apple Silicon M4 Pro)  |
| CPU       | 14 cores (10P + 4E)                 |
| RAM       | 16 GB                               |
| Storage   | 1 TB SSD                            |
| GPU       | Integrated (no discrete NVIDIA)     |
| OS        | macOS 14.x                          |
| QarSUMO   | Falls back to SUMO (no CUDA GPU)    |

### 4.3.2 HPC Environment (OSC Pitzer)

Used for the larger tiers (50K – 500K) that exceed the arm64 `netconvert` threshold and benefit from QarSUMO's GPU path. All three engines (SUMO, MATSim, QarSUMO) run end-to-end on Pitzer; see `doc/SCENARIO_GENERATION.md` §9 for the operational guide.

| Component       | Specification                                                    |
| --------------- | ---------------------------------------------------------------- |
| Cluster         | Ohio Supercomputer Center — Pitzer (RHEL 9, SLURM)               |
| CPU per node    | Intel Xeon Skylake (40 cores) or Cascade Lake (48 cores), 192 GB |
| Large-mem nodes | Up to 3 TB RAM (`hugemem` partition)                             |
| GPU             | NVIDIA V100 (16 GB or 32 GB), 2 or 4 per GPU node                |
| Partitions used | `cpu` (gen + SUMO + MATSim), `gpu` / `gpu-quad` (QarSUMO)        |
| Max wall time   | 7 days (`cpu`, `gpu`); 14 days (`longcpu`, restricted)            |
| Storage         | Home 500 GB, Project (`PMIU0110`) 500 GB, scratch per-job        |
| Project account | `--account=PMIU0110`                                              |
| Internet access | Outbound via NAT on login + compute nodes (Overpass, PyPI, GitHub) |

### 4.3.3 Software Versions

| Software | Version      | Installation              | Notes               |
| -------- | ------------ | -------------------------- | ------------------- |
| Python   | 3.13.x       | `setup_simforge.py`        | Bootstrapper        |
| SUMO     | 1.20.0       | `brew install sumo`        | Mandatory           |
| MATSim   | 15.0         | JAR                        | `lib/matsim-15.0/`  |
| Java     | 17           | Homebrew                   | MATSim runtime      |
| QarSUMO  | git checkout | LLNL/QarSUMO               | Optional (GPU only) |
| osmnx    | 1.x          | pip                        | Network extraction  |
| lxml     | 5.x          | pip                        | XML processing      |
| pandas   | 2.x          | pip                        | Demand CSV handling |

### 4.3.4 Execution Protocol

For each cell of the stress-test matrix:

1. **Validation**: `validate_bundle.py` verifies hash + referential integrity.
2. **Conversion**: Adapter writes simulator-specific inputs and a `feasibility_report.json` sidecar.
3. **Measurement runs**: 3 runs (or 2 for MATSim) with seeds 42, 43, 44.
4. **Metric extraction**: Parse simulator outputs → travel-time stats, throughput.
5. **Result serialisation**: `runs/stress_test/benchmark_results_stress_test.json`.

---

## 4.4 Measured Results

### 4.4.1 Headline numbers (Apple M4 Pro)

The numbers below come from the most recent canonical stress test (see [CHANGELOG.md](../../CHANGELOG.md), Addendum 3):

| Scenario       | Engine  | Mode  | Trips simulated | Avg TT (s)  | Runtime (s)  | R-Score |
| -------------- | ------- | ----- | --------------- | ----------- | ------------ | ------- |
| chicago_1k_car | matsim  | meso  | **1000 (100 %)** | 195.7 ± 0.0 | 10.19 ± 0.16 | 1.0000  |
| chicago_1k_car | qarsumo | meso  | 995 (99.5 %)    | 204.1 ± 0.4 |  0.28 ± 0.01 | 0.9981  |
| chicago_1k_car | sumo    | meso  | 995 (99.5 %)    | 204.1 ± 0.4 |  0.27 ± 0.00 | 0.9981  |
| chicago_1k_car | sumo    | micro | 940 (94.0 %)    | 288.0 ± 0.8 |  1.24 ± 0.01 | 0.9971  |
| nyc_1k_car     | matsim  | meso  | **1000 (100 %)** | 249.3 ± 0.0 |  9.99 ± 0.06 | 1.0000  |
| nyc_1k_car     | sumo    | meso  | 995 (99.5 %)    | 253.4 ± 0.3 |  0.26 ± 0.06 | 0.9988  |

Total wall-clock across the 22-run matrix: ~52 s.

### 4.4.2 Fidelity (RQ1)

- SUMO meso vs MATSim meso disagree on mean travel time by 8.4 s (Chicago) and 4.1 s (NYC) — driven by MATSim's earlier mobsim release and SUMO's slightly stricter insertion logic.
- SUMO meso and SUMO micro disagree by 84 s (Chicago) on mean travel time — micro captures intersection delays and queue spillback that meso averages out.
- QarSUMO meso and SUMO meso are bit-identical (QarSUMO falls back to SUMO without CUDA).

### 4.4.3 Scalability (RQ2)

- SUMO meso is **~37 ×** faster than MATSim on the same scenario (0.27 s vs 10.19 s for Chicago).
- SUMO meso vs SUMO micro: **~4.6 ×** speedup (0.27 s vs 1.24 s) at the 1K tier; the gap widens at higher tiers (see HPC results in `runs/`).
- MATSim's wall-clock is dominated by JVM startup (~5 – 7 s) at this tier.

### 4.4.4 Reproducibility (RQ3)

- All R-scores ≥ 0.997 ("Excellent") across both scenarios and all engine/mode combinations.
- MATSim achieves R = 1.0000 (perfectly deterministic with `lastIteration = 0`).
- SUMO micro shows the most variance (R = 0.9971) — Krauss model has small stochastic components.

### 4.4.5 Trade-off Analysis (RQ4)

```
Fidelity ▲
         │  ● SUMO-micro      (highest fidelity, 4–5 × slower than meso at 1K)
         │
         │      ● SUMO-meso  ≡  QarSUMO-meso   (lower fidelity, near-instant)
         │      ● MATSim     (different model, perfectly deterministic; JVM tax)
         │
         └──────────────────────────────────▶ Speed
```

**Key trade-off**: Mesoscopic simulation trades intersection-level accuracy for orders-of-magnitude runtime improvement. For the 1K tier the absolute runtimes are too small to be a practical concern; the trade-off becomes decisive at the 50K – 500K tiers where SUMO micro becomes infeasible and MATSim's per-run JVM tax amortises better.

---

## 4.5 Analysis Methods

### 4.5.1 Statistical Analysis

**Cross-simulator comparison (RQ1)**

- Paired comparisons: each pair of simulators compared on identical scenarios.
- KS test at α = 0.05: determines whether travel-time distributions differ significantly.
- GEH acceptance criterion: ≥ 85 % of links with GEH < 5.0 indicates acceptable fit.

**Scaling analysis (RQ2)**

- Log-log plot of runtime vs trip count → slope indicates scaling exponent.
- Expected: meso slopes ≈ 1.0 (linear), micro slopes ≈ 1.2 – 1.5 (super-linear).

**Reproducibility analysis (RQ3)**

- Compute $R$ for each `(scenario, engine, mode, KPI)` combination.
- Report $R \geq 0.99$ as "effectively deterministic"; flag any $R < 0.90$ for investigation.

### 4.5.2 Visualisation Plan

`evaluation/generate_plots.py` emits 9 figures (5.1 – 5.9). See [doc/RESULTS_GUIDE.md](../RESULTS_GUIDE.md) for the per-figure description.

### 4.5.3 Output Formats

`evaluation/analyze_benchmark.py` emits:

- **Console summary** with categorised metrics
- **LaTeX tables** ready for thesis inclusion (`--latex`)
- **Markdown tables** for documentation (`--markdown`)
- **Coverage diagnostic** flagging low-sample / asymmetric / silently-failed cells

```bash
python -m evaluation.analyze_benchmark runs/stress_test/benchmark_results_stress_test.json --latex --markdown
```

---

## 4.6 Threats to Validity

### 4.6.1 Internal Validity

| Threat                        | Mitigation                                                      |
| ----------------------------- | --------------------------------------------------------------- |
| Random seed affecting results | 3 runs per condition with different seeds; report mean ± std    |
| JVM warm-up affecting MATSim  | All runs include the same JVM start cost; comparison is fair-relative |
| OS scheduling noise           | Use `perf_counter()`; HPC runs on dedicated nodes               |
| Adapter conversion errors     | 293 unit tests including byte-identical determinism tests       |
| Scenario validation failures  | Pre-flight validation check before every run                    |
| Trip-count asymmetry across engines | SCC filter at generator + adapter; `feasibility_report.json` audit trail |

### 4.6.2 External Validity

| Threat                          | Mitigation                                                           |
| ------------------------------- | -------------------------------------------------------------------- |
| Only 2 US cities in the stress test | Larger HPC runs cover Chicago/NYC at 200K and 500K; LA via 50K tier |
| Census-calibrated (not real OD) | Documented realism assessment (~60 – 65 %); exceeds synthetic baselines |
| No transit routing              | Mode is assigned but not routed; acknowledged limitation             |
| Single peak hour                | Larger tiers cover 24-hour demand patterns                           |

### 4.6.3 Construct Validity

| Threat                                 | Mitigation                                                |
| -------------------------------------- | --------------------------------------------------------- |
| GEH not universally accepted           | Report multiple metrics (RMSE, KS, GEH) for triangulation |
| Reproducibility index R sensitive to μ | Handle edge cases (μ → 0) explicitly; report CV alongside R |
| Travel time only (no queue lengths)    | Focus on trip-level metrics; acknowledge this limitation  |

---

## 4.7 Reproducibility Checklist

For any researcher to reproduce these experiments:

- [ ] Clone repository (branch `Version_2`).
- [ ] `python setup_simforge.py` (creates `.venv`, installs deps, downloads MATSim JAR).
- [ ] Install SUMO: `brew install sumo` (macOS) or `apt-get install sumo` (Linux).
- [ ] Install Java 17+: `brew install openjdk@17`.
- [ ] (Optional) Pre-warm OSM cache: `python -m pipeline.network.warmup`.
- [ ] Validate the bundled scenarios: `python -m pipeline.validation.validate_bundle scenarios/chicago_1k_car`.
- [ ] Run the canonical benchmark: `python -m execution.run_benchmark runspecs/stress_test.yaml`.
- [ ] Analyse: `python -m evaluation.analyze_benchmark runs/stress_test/benchmark_results_stress_test.json --latex --markdown`.
- [ ] Render figures: `python -m evaluation.generate_plots runs/stress_test/benchmark_results_stress_test.json`.
- [ ] Verify: 293/293 tests pass (`python -m pytest tests/ -q`).
