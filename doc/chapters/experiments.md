# Chapter 4: Experiments

## 4.1 Experimental Design

### 4.1.1 Research Questions

This experimental study addresses the following research questions:

| RQ  | Question                                                                         | Metric(s)              |
| --- | -------------------------------------------------------------------------------- | ---------------------- |
| RQ1 | How do travel time distributions compare across simulators for identical inputs? | RMSE, GEH, KS          |
| RQ2 | How does runtime scale with network size and demand volume across engines?       | Wall-clock, throughput |
| RQ3 | How consistent are results across repeated runs with different random seeds?     | $R = 1 - \sigma/\mu$   |
| RQ4 | What are the practical trade-offs between fidelity, speed, and reproducibility?  | Multi-metric analysis  |

### 4.1.2 Independent Variables

**Variable 1: Simulator Engine (5 configurations)**

| Engine          | Paradigm    | Traffic Model                        | Hardware |
| --------------- | ----------- | ------------------------------------ | -------- |
| SUMO (micro)    | Microscopic | Krauss car-following + lane-changing | CPU      |
| SUMO (meso)     | Mesoscopic  | Queue-based link traversal           | CPU      |
| QarSUMO (micro) | Microscopic | GPU-accelerated car-following        | GPU      |
| QarSUMO (meso)  | Mesoscopic  | GPU-accelerated queue model          | GPU      |
| MATSim          | Mesoscopic  | Activity-based, event-driven queues  | CPU      |

**Variable 2: Scenario Scale (4 demand tiers)**

| Tier | Trip Count | Purpose                          |
| ---- | ---------- | -------------------------------- |
| 5K   | 5,000      | Validation, quick testing        |
| 50K  | 50,000     | Medium-scale stress test         |
| 500K | 500,000    | Large-scale scalability analysis |
| 5M   | 5,000,000  | Full-scale performance boundary  |

**Variable 3: City Network (3 metropolitan areas)**

| City    | Center            | Radius | Nodes | Links  | Signal Controllers | Road Types | Character              |
| ------- | ----------------- | ------ | ----- | ------ | ------------------ | ---------- | ---------------------- |
| Chicago | 41.88°N, 87.63°W  | 4 km   | 1,248 | 2,871  | 925                | 7          | Dense grid, mixed use  |
| LA      | 34.05°N, 118.24°W | 6 km   | 6,333 | 17,685 | ~4,000+            | 8          | Sprawl, arterial-heavy |
| NYC     | 40.76°N, 73.99°W  | 3 km   | 1,913 | 3,877  | ~1,200             | 7          | Ultra-dense, Manhattan |

**Why these cities:**

- **Chicago**: Classic American grid; mix of arterials and residential streets; ModelGen data most complete (832K buildings, 281MB)
- **LA**: Sprawling network with heavy freeway usage; largest road network (6km radius captures significant arterial grid); represents car-dependent cities
- **NYC**: Extremely dense Manhattan grid; unusual traffic patterns (one-way streets, high pedestrian interaction); most buildings per area (608MB model file)

### 4.1.3 Dependent Variables

**Fidelity (RQ1):**

| Metric                 | Formula                                     | Unit          | Interpretation                     |
| ---------------------- | ------------------------------------------- | ------------- | ---------------------------------- |
| Mean travel time       | $\bar{t} = \frac{1}{n}\sum_i t_i$           | seconds       | Central tendency of trip durations |
| P95 travel time        | 95th percentile of $\{t_i\}$                | seconds       | Tail behavior / worst-case trips   |
| Trip completion rate   | $n_\text{completed} / n_\text{total}$       | %             | How many trips reach destination   |
| RMSE (cross-simulator) | $\sqrt{\frac{1}{n}\sum(y_i - \hat{y}_i)^2}$ | seconds       | Agreement between two simulators   |
| GEH (link-level)       | $\sqrt{\frac{2(M-C)^2}{M+C}}$               | dimensionless | Traffic engineering fit metric     |
| KS statistic           | $\sup_x \|F_1(x) - F_2(x)\|$                | dimensionless | Distribution shape comparison      |

**Scalability (RQ2):**

| Metric             | Formula                          | Unit         | Interpretation                  |
| ------------------ | -------------------------------- | ------------ | ------------------------------- |
| Wall-clock runtime | `perf_counter()` end - start     | seconds      | Absolute performance            |
| Throughput         | vehicles_completed / runtime     | vehicles/sec | Efficiency metric               |
| SRT                | simulated_time / wall_clock_time | ratio        | Faster-than-real-time indicator |
| Peak memory        | OS-reported peak RSS             | MB           | Hardware requirement            |

**Reproducibility (RQ3):**

| Metric                    | Formula                | Range       | Interpretation                        |
| ------------------------- | ---------------------- | ----------- | ------------------------------------- |
| Reproducibility index $R$ | $1 - \sigma/\mu$       | [-∞, 1.0]   | 1.0 = perfectly deterministic         |
| Max deviation             | $\max_i \|x_i - \mu\|$ | same as KPI | Worst-case variability                |
| CV (coeff. of variation)  | $\sigma/\mu$           | [0, ∞)      | Relative variability (lower = better) |

### 4.1.4 Full Experimental Matrix

**Complete design**: 3 cities × 4 tiers × 5 engine-modes × 3 seeds = **180 runs**

**Focused thesis subset** (practical constraints — time, HPC allocation):

| Phase      | Cities  | Tier(s) | Engines | Seeds | Total Runs | Purpose                        |
| ---------- | ------- | ------- | ------- | ----- | ---------- | ------------------------------ |
| Validation | All 3   | 5K      | All 5   | 3     | 45         | Correctness + quick comparison |
| Scale-up   | Chicago | All 4   | All 5   | 3     | 60         | Scaling behavior               |
| Production | All 3   | 5K, 50K | All 5   | 3     | 90         | Cross-city comparison          |

**Control variables** (held constant across all experimental conditions):

| Parameter                | Value             | Rationale                                 |
| ------------------------ | ----------------- | ----------------------------------------- |
| Random seeds             | 42, 43, 44        | Reproducible; 3 runs per condition        |
| Demand strategy          | Census-calibrated | Consistent realistic inputs               |
| Simulation mode priority | Mesoscopic        | Feasible at all tiers (micro only for 5K) |
| Time horizon             | 1 hour (3,600s)   | Standard morning peak period              |
| MATSim iterations        | 1 (no replanning) | Fair comparison with SUMO (single pass)   |
| SUMO routing             | BFS shortest path | Deterministic, reproducible               |

---

## 4.2 Scenario Descriptions

### 4.2.1 Chicago 5K Scenario

**Generated**: `python generate.py --city chicago --trips 5000 --seed 42`

**Network characteristics (actual, from generated data):**

| Property           | Value                                  |
| ------------------ | -------------------------------------- |
| Nodes              | 1,248                                  |
| Links              | 2,871                                  |
| Signal controllers | 925                                    |
| Total road length  | ~180 km                                |
| Bounding box       | 41.842°–41.914° N, -87.678°–-87.582° W |
| Radius from center | 4 km                                   |
| Source             | OpenStreetMap (live download)          |

**Demand characteristics (actual, from generated data):**

| Property            | Value                        |
| ------------------- | ---------------------------- |
| Total trips         | 5,000                        |
| Demand strategy     | Census-calibrated (ModelGen) |
| Unique origin nodes | ~350-450                     |
| Unique dest nodes   | ~600-800                     |
| Mode                | 100% car                     |
| Time window         | 0-3600s (1 hour)             |
| Model file          | `chicago_model.txt` (281 MB) |
| Census commuters    | ~15,000-25,000 in bbox       |
| Avg commute time    | ~28 min (from PUMS JWMNP)    |
| Generation time     | ~28 seconds                  |

**Key features**: Dense grid pattern with regular block spacing; high intersection density; mixed residential/commercial; multiple highway segments (I-90/94, I-290).

### 4.2.2 NYC 5K Scenario

**Generated**: `python generate.py --city nyc --trips 5000 --seed 42`

**Network characteristics:**

| Property           | Value                   |
| ------------------ | ----------------------- |
| Nodes              | 1,913                   |
| Links              | 3,877                   |
| Signal controllers | ~1,200                  |
| Bounding box       | Midtown Manhattan focus |
| Radius from center | 3 km                    |

**Demand characteristics:**

| Property         | Value                    |
| ---------------- | ------------------------ |
| Total trips      | 5,000                    |
| Model file       | `nyc_model.txt` (608 MB) |
| Building density | Highest of all cities    |

**Key features**: Extreme density; predominantly one-way streets; narrow blocks; heavy east-west/north-south split due to Manhattan grid; Broadway diagonal creates complex intersections.

### 4.2.3 LA 5K Scenario

**Generated**: `python generate.py --city la --trips 5000 --seed 42`

**Network characteristics:**

| Property           | Value                 |
| ------------------ | --------------------- |
| Nodes              | 6,333                 |
| Links              | 17,685                |
| Signal controllers | ~4,000+               |
| Bounding box       | Downtown LA + suburbs |
| Radius from center | 6 km                  |

**Demand characteristics:**

| Property           | Value                   |
| ------------------ | ----------------------- |
| Total trips        | 5,000                   |
| Model file         | `la_model.txt` (310 MB) |
| Modes (multi-mode) | car, transit, bike      |

**Key features**: Largest network by far (6.3K nodes vs 1.2-1.9K); arterial-dominated; significant freeway network (I-10, I-110, US-101); sprawling layout with longer average trip distances.

### 4.2.4 Scenario Comparison

| Metric               | Chicago 5K | NYC 5K | LA 5K  |
| -------------------- | ---------- | ------ | ------ |
| Nodes                | 1,248      | 1,913  | 6,333  |
| Links                | 2,871      | 3,877  | 17,685 |
| Links/Node ratio     | 2.30       | 2.03   | 2.79   |
| Signal controllers   | 925        | ~1,200 | ~4,000 |
| Network radius (km)  | 4          | 3      | 6      |
| Grid regularity      | High       | High   | Medium |
| Freeway presence     | Moderate   | Low    | High   |
| Model file size (MB) | 281        | 608    | 310    |
| Buildings in model   | 832,750    | ~1.5M+ | ~900K  |

---

## 4.3 Execution Environment

### 4.3.1 Development Environment (Local)

| Component | Specification                       |
| --------- | ----------------------------------- |
| Machine   | MacBook Pro (Apple Silicon M1/M2)   |
| CPU       | 8-10 cores (4P + 4E)                |
| RAM       | 16 GB                               |
| Storage   | 512 GB SSD                          |
| GPU       | Integrated (no discrete NVIDIA GPU) |
| OS        | macOS 14.x                          |
| QarSUMO   | Falls back to SUMO (no CUDA GPU)    |

### 4.3.2 HPC Environment (OSC Pitzer)

| Component       | Specification                                   |
| --------------- | ----------------------------------------------- |
| Cluster         | Ohio Supercomputer Center — Pitzer              |
| CPU per node    | Intel Xeon (40-48 cores)                        |
| RAM per node    | 178 GB – 744 GB                                 |
| GPU per node    | NVIDIA V100 (2-4 per GPU node, GRES configured) |
| Storage         | Home: 500 GB, Project (PMIU0110): 500 GB        |
| Max wall time   | 7 days                                          |
| Interconnect    | InfiniBand HDR                                  |
| Internet access | Available on compute nodes (critical for OSM)   |
| CUDA versions   | 11.8.0, 12.4.1, 12.6.2                          |

**HPC job configuration by tier:**

| Tier | CPUs | RAM    | Wall Time | GPU             |
| ---- | ---- | ------ | --------- | --------------- |
| 5K   | 4    | 8 GB   | 30 min    | No              |
| 50K  | 8    | 32 GB  | 2 hrs     | No              |
| 500K | 8    | 64 GB  | 4 hrs     | No              |
| 5M   | 16   | 128 GB | 12 hrs    | Optional (V100) |

### 4.3.3 Software Versions

| Software | Version      | Installation Method        | Notes               |
| -------- | ------------ | -------------------------- | ------------------- |
| Python   | 3.12.x       | `module load python/3.12`  | Pitzer module       |
| SUMO     | 1.20.0       | `pip install eclipse-sumo` | pip in venv         |
| MATSim   | 15.0         | JAR distribution           | `lib/matsim-15.0/`  |
| Java     | 17 (Temurin) | Homebrew / manual          | MATSim runtime      |
| QarSUMO  | N/A          | Not yet available on HPC   | Falls back to SUMO  |
| osmnx    | 1.9.x        | pip in venv                | Network extraction  |
| lxml     | 5.x          | pip in venv                | XML processing      |
| pandas   | 2.x          | pip in venv                | Demand CSV handling |

### 4.3.4 Execution Protocol

For each experimental condition:

1. **Validation**: Run `validate_bundle.py` to verify scenario integrity (hash check, referential integrity)
2. **Conversion**: Generate simulator-specific inputs via appropriate adapter
3. **Warm-up run** (optional): First run discarded to account for JIT compilation (Java/MATSim), disk caching, and OS scheduling effects
4. **Measurement runs**: 3 runs with seeds 42, 43, 44
5. **Metric extraction**: Parse simulator outputs → compute travel time stats, throughput, reproducibility
6. **Result serialization**: Write `benchmark_results.json` with all run data

---

## 4.4 Expected Results

### 4.4.1 Fidelity Expectations (RQ1)

**Hypothesis**: Mesoscopic simulators (SUMO-meso, QarSUMO-meso, MATSim) will agree closely with each other (KS < 0.1) but diverge from microscopic results (KS > 0.2) due to fundamentally different traffic flow models.

**Expected travel time patterns:**

| Engine          | Mode  | Expected Mean Travel Time (5K)        | Relative to SUMO-micro |
| --------------- | ----- | ------------------------------------- | ---------------------- |
| SUMO (micro)    | micro | Baseline                              | 1.00×                  |
| SUMO (meso)     | meso  | 10-30% lower (no congestion modeling) | 0.70-0.90×             |
| QarSUMO (micro) | micro | ≈ identical to SUMO-micro             | ~1.00×                 |
| QarSUMO (meso)  | meso  | ≈ identical to SUMO-meso              | ~0.70-0.90×            |
| MATSim          | meso  | 5-20% different from SUMO-meso        | 0.80-1.20×             |

**Rationale**: Microscopic simulation captures intersection delays, queue spillback, and lane-changing friction that mesoscopic models approximate or ignore. MATSim uses a different queue model than SUMO's mesoscopic mode, potentially producing systematically different link traversal times.

### 4.4.2 Scalability Expectations (RQ2)

**Hypothesis**: Runtime scales sub-linearly with trip count for mesoscopic simulators and super-linearly for microscopic simulators at high demand.

**Expected runtime matrix (5K tier, mesoscopic):**

| Engine    | Chicago 5K | NYC 5K | LA 5K   |
| --------- | ---------- | ------ | ------- |
| SUMO meso | ~2-5s      | ~1-3s  | ~3-8s   |
| QarSUMO\* | ~2-5s      | ~1-3s  | ~3-8s   |
| MATSim    | ~10-15s    | ~8-12s | ~12-20s |

\*Falls back to SUMO on CPU-only hardware

**Expected scaling behavior:**

| Tier | SUMO (meso) | SUMO (micro) | MATSim  |
| ---- | ----------- | ------------ | ------- |
| 5K   | ~3s         | ~15s         | ~12s    |
| 50K  | ~30s        | ~5 min       | ~2 min  |
| 500K | ~5 min      | ~2 hrs       | ~20 min |
| 5M   | ~1 hr       | Infeasible\* | ~3 hrs  |

\*Microscopic SUMO with 5M vehicles on a single node may exceed memory/time limits

**Key scalability insight**: The mesoscopic—microscopic performance gap widens with scale. At 5K trips, microscopic is only 5× slower; at 500K, it's 20-50× slower; at 5M, it becomes impractical on a single node.

### 4.4.3 Reproducibility Expectations (RQ3)

**Hypothesis**: All deterministic simulators should achieve $R > 0.99$ for mean travel time across repeated runs with different seeds, because:

1. Input demand is fixed (same trips, same departure times)
2. Network is fixed (same roads, same signals)
3. Only routing-level stochasticity varies by seed

**Expected reproducibility by engine:**

| Engine          | Expected $R$ (mean TT) | Expected $R$ (p95 TT) | Rationale                                             |
| --------------- | ---------------------- | --------------------- | ----------------------------------------------------- |
| SUMO (micro)    | 0.98-1.00              | 0.95-0.99             | Krauss model has stochastic components                |
| SUMO (meso)     | 0.99-1.00              | 0.98-1.00             | Queue model is more deterministic                     |
| QarSUMO (micro) | 0.97-0.99              | 0.94-0.98             | GPU parallelism may introduce order-dependent effects |
| QarSUMO (meso)  | 0.99-1.00              | 0.98-1.00             | Same as SUMO meso                                     |
| MATSim          | 1.00                   | 1.00                  | Fully deterministic with fixed seed + 1 iteration     |

**Why P95 is less reproducible than mean**: Tail behavior is more sensitive to individual vehicle interactions, which vary with random seed.

### 4.4.4 Trade-off Analysis (RQ4)

**Expected trade-off frontier:**

```
Fidelity ▲
         │  ● SUMO-micro      (highest fidelity, slowest)
         │
         │  ● QarSUMO-micro   (same fidelity, GPU-accelerated)
         │
         │      ● SUMO-meso   (lower fidelity, much faster)
         │      ● QarSUMO-meso
         │    ● MATSim        (different model, unique insights)
         │
         └──────────────────────────────────▶ Speed
```

**Key trade-off**: Mesoscopic simulation trades ~20-30% fidelity for 100× performance improvement. For large-scale studies (50K+ trips), mesoscopic is the only practical option.

---

## 4.5 Analysis Methods

### 4.5.1 Statistical Analysis

**Cross-simulator comparison (RQ1)**:

- Paired comparisons: Each pair of simulators compared on identical scenarios
- KS test at α = 0.05: Determines if travel time distributions are statistically different
- GEH acceptance criterion: ≥85% of links with GEH < 5.0 indicates acceptable fit

**Scaling analysis (RQ2)**:

- Log-log plot of runtime vs trip count → slope indicates scaling exponent
- Expected: meso slopes ≈ 1.0 (linear), micro slopes ≈ 1.2-1.5 (super-linear)

**Reproducibility analysis (RQ3)**:

- Compute $R$ for each (scenario, engine, KPI) combination
- Report $R ≥ 0.99$ as "effectively deterministic"
- Flag any $R < 0.90$ for investigation

### 4.5.2 Visualization Plan

| Plot                      | Type         | Shows                                        |
| ------------------------- | ------------ | -------------------------------------------- |
| Travel time distributions | Box plot     | Mean, median, quartiles, outliers per engine |
| Travel time CDFs          | Line plot    | Cumulative distributions for KS comparison   |
| Runtime vs scale          | Log-log plot | Scaling exponent per engine                  |
| Throughput comparison     | Bar chart    | Vehicles/sec per engine                      |
| Reproducibility heatmap   | Heatmap      | $R$ values across (engine × KPI) matrix      |
| Trade-off frontier        | Scatter plot | Fidelity vs runtime for each engine          |

### 4.5.3 Output Formats

The `evaluation/analyze_benchmark.py` module generates:

- **LaTeX tables**: Ready for direct inclusion in thesis document
- **Markdown tables**: For documentation and quick reference
- **JSON summaries**: Machine-readable aggregated results
- **Console output**: Formatted summary with categorized metrics

```python
# Example analysis invocation
python -m evaluation.analyze_benchmark runs/benchmark_results.json

# Expected output:
# ═══════════════════════════════════════════
# 📊 BENCHMARK ANALYSIS
# ═══════════════════════════════════════════
#   Scenarios:   3
#   Engines:     3
#   Total runs:  27
# ───────────────────────────────────────────
#   Avg runtime:    4.2s
#   Completion:     98.5%
#   Max R-index:    0.999
# ═══════════════════════════════════════════
```

---

## 4.6 Threats to Validity

### 4.6.1 Internal Validity

| Threat                        | Mitigation                                                      |
| ----------------------------- | --------------------------------------------------------------- |
| Random seed affecting results | 3 runs per condition with different seeds; report mean ± std    |
| JVM warm-up affecting MATSim  | Discard first run; measure only subsequent runs                 |
| OS scheduling noise           | Use `perf_counter()` (process time); run on dedicated HPC nodes |
| Adapter conversion errors     | 57 unit tests; determinism tests verify byte-identical outputs  |
| Scenario validation failures  | Pre-flight validation check before every run                    |

### 4.6.2 External Validity

| Threat                          | Mitigation                                                           |
| ------------------------------- | -------------------------------------------------------------------- |
| Only 3 US cities                | Cities chosen to represent diversity (grid, dense, sprawl)           |
| Census-calibrated (not real OD) | Documented realism assessment (~60-65%); exceeds synthetic baselines |
| No transit routing              | Mode is assigned but not routed; acknowledged limitation             |
| Limited demand tiers tested     | 4 tiers (5K-5M) span 3 orders of magnitude                           |

### 4.6.3 Construct Validity

| Threat                                 | Mitigation                                                |
| -------------------------------------- | --------------------------------------------------------- |
| GEH not universally accepted           | Report multiple metrics (RMSE, KS, GEH) for triangulation |
| Reproducibility index R sensitive to μ | Handle edge cases (μ→0) explicitly; report CV alongside R |
| Travel time only (no queue lengths)    | Focus on trip-level metrics; acknowledge this limitation  |

---

## 4.7 Reproducibility Checklist

For any researcher to reproduce these experiments:

- [ ] Clone repository: `git clone -b modelgen https://github.com/PhanidharAkula/SimForge.git`
- [ ] Install Python deps: `pip install -r requirements.txt`
- [ ] Install SUMO: `brew install sumo` (macOS) or `pip install eclipse-sumo` (Linux)
- [ ] Install Java 17+ (for MATSim): `brew install openjdk@17`
- [ ] Transfer model files to `modelgen/` (chicago_model.txt, la_model.txt, nyc_model.txt)
- [ ] Generate scenarios: `python generate.py --city <city> --trips <N> --seed 42`
- [ ] Validate: `python -m pipeline.validation.validate_bundle scenarios/<name>`
- [ ] Run benchmark: `python -m execution.run_benchmark runspecs/benchmark_5k.yaml`
- [ ] Analyze: `python -m evaluation.analyze_benchmark runs/<dir>/benchmark_results.json`
- [ ] Verify: 57/57 tests pass (`python -m pytest tests/`)
