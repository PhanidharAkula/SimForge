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

| Engine       | Paradigm    | Traffic Model                        | Hardware |
| ------------ | ----------- | ------------------------------------ | -------- |
| SUMO (micro) | Microscopic | Krauss car-following + lane-changing | CPU      |
| SUMO (meso)  | Mesoscopic  | Queue-based link traversal           | CPU      |
| MATSim       | Mesoscopic  | Activity-based, event-driven queues  | CPU      |
| DTALite      | Mesoscopic  | Dynamic Traffic Assignment (UE)      | CPU      |

> The plan listed five engines (SUMO, MATSim, POLARIS, LPSim, QarSUMO). After two integration cycles, the matrix narrows to **three primary engines** chosen for paradigm spread: SUMO microscopic (car-following), MATSim queue-based agent simulation, and DTALite mesoscopic Dynamic Traffic Assignment. Three of the originally-proposed engines were systematically evaluated and ruled out: QarSUMO dropped in Version_4 Phase A (no usable public source), LPSim integrated in Version_4 Phase B and abandoned in Version_5 (GPU kernel SIGSEGV on networks > a few-K nodes), POLARIS and CityFlow evaluated as third-engine alternatives and rejected at criteria. Full retrospectives in [`doc/engines/`](../engines/). The canonical stress test now runs all 4 cells (SUMO meso, SUMO micro, MATSim meso, DTALite meso) at N=5 repeats each, and is fully CPU-only — runs end-to-end on a Mac laptop.

**Variable 2: Scenario Scale**

The bundled stress test fixes both networks at the **1K-trip tier** to keep the benchmark runnable on a developer laptop in under one minute. Larger tiers (10K, 50K, 200K, 500K) are generated locally via the helper scripts in `scripts/` and are reserved for HPC runs that probe scaling behaviour.

| Tier         | Trip Count | Helper script                       | Where it runs                |
| ------------ | ---------- | ----------------------------------- | ---------------------------- |
| **Bundled**  | **1,000**  | `scripts/01_chicago_1k_car.py`          | Laptop (Apple Silicon)       |
| Small        | 10,000     | `scripts/02_nyc_10k_car.py`       | Laptop / cluster             |
| Medium       | 50,000     | `scripts/03_la_50k_car.py`   | Cluster                      |
| Large        | 200,000    | `scripts/04_chicago_200k_car.py`      | Cluster                      |
| Stress       | 500,000    | `scripts/05_nyc_500k_car.py`         | Cluster (Linux only)         |

**Variable 3: City Network (1 metropolitan area in the canonical stress test)**

| City    | Center            | Radius | Nodes | Links | Largest SCC    | Character             |
| ------- | ----------------- | ------ | ----- | ----- | -------------- | --------------------- |
| Chicago | 41.88°N, 87.63°W  | 4 km   | 1,245 | 2,862 | 1,204 (96.7 %) | Dense grid, mixed use |

> NYC and LA are supported by the generator (`--city nyc`, `--city la`) and used by `scripts/02_…05_` for the larger tiers, but the canonical 1K stress test is deliberately single-scenario so it finishes in under a minute on a developer laptop.

**Why Chicago:**

- Classic American grid; mix of arterials and residential streets; ModelGen census coverage is most complete. Dense enough to exercise all three engines end-to-end while remaining small enough to ship as a bundled artefact.

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

The matrix declared by `runspecs/benchmark_small.yaml`:

| Phase | Scenarios | Engines × modes | Repeats | Total runs |
| --- | --- | --- | --- | --- |
| Stress test | `chicago_1k_car` | SUMO meso, SUMO micro, MATSim meso, DTALite meso | 5 each | **20 runs** |

Every `feasibility_report.json` confirms `feasible_trips == 1000` for every adapter, so the four engines simulate exactly the same trip set. All four cells are CPU-only and complete end-to-end on a developer laptop in under a minute.

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

**Generated**: `python scripts/01_chicago_1k_car.py` (equivalent to `python generate.py --city chicago --trips 1000 --modes car --seed 42`)

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

### 4.2.2 Larger Tiers (HPC)

The 10K – 500K tiers are generated by `scripts/02_nyc_10k_car.py`, `scripts/03_la_50k_car.py`, `scripts/04_chicago_200k_car.py`, and `scripts/05_nyc_500k_car.py`. They target NYC, LA, and Chicago respectively and run on OSC Pitzer — see [`doc/PITZER.md`](../PITZER.md) for the operational guide.

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

### 4.3.2 HPC Environment (OSC Pitzer)

Used for the larger tiers (50K – 500K) that exceed the arm64 `netconvert` threshold. All three primary engines (SUMO, MATSim, DTALite) are CPU-only after the LPSim removal in Version_5; the bundled stress test runs end-to-end on a developer Mac, and HPC use is reserved purely for the larger trip tiers where SUMO microscopic + MATSim wall time dominates. See `doc/PITZER.md` for the operational guide.

| Component       | Specification                                                    |
| --------------- | ---------------------------------------------------------------- |
| Cluster         | Ohio Supercomputer Center — Pitzer (RHEL 9, SLURM)               |
| CPU per node    | Intel Xeon Skylake (40 cores) or Cascade Lake (48 cores), 192 GB |
| Large-mem nodes | Up to 3 TB RAM (`hugemem` partition)                             |
| Partitions used | `cpu` (all three engines are CPU-only in Version_5)              |
| Max wall time   | 7 days (`cpu`, `gpu`); 14 days (`longcpu`, restricted)            |
| Storage         | Home 500 GB, Project (`PMIU0110`) 500 GB, scratch per-job        |
| Project account | `--account=PMIU0110`                                              |
| Internet access | Outbound via NAT on login + compute nodes (PyPI, GitHub; Overpass used only as fallback — primary OSM ingest uses state PBFs staged under `~/SimForge/osm_data/`) |

### 4.3.3 Software Versions

| Software | Version      | Installation              | Notes               |
| -------- | ------------ | -------------------------- | ------------------- |
| Python   | 3.13.x       | `setup_simforge.py`        | Bootstrapper        |
| SUMO     | 1.26.0       | bundled in `requirements.lock` (`eclipse-sumo` wheel) | Mandatory           |
| MATSim   | 15.0         | JAR                        | `lib/matsim-15.0/`  |
| Java     | 17           | Homebrew                   | MATSim runtime      |
| DTALite  | path4gmns 0.10.0 | bundled in `requirements.lock` (`path4gmns` wheel) | CPU mesoscopic DTA; on Mac needs `brew install libomp` |
| osmnx    | 2.x (`>=2.0,<3`) | pip               | Parse PBF slice → graph, bbox truncate (`bbox=(W,S,E,N)` tuple)  |
| pyosmium | 4.x          | pip (`osmium`)             | Bbox-slice Geofabrik PBFs in `osm_data/` |
| lxml     | 5.x          | pip                        | XML processing      |
| pandas   | 2.x          | pip                        | Demand CSV handling |

### 4.3.4 Execution Protocol

For each cell of the stress-test matrix:

1. **Validation**: `validate_bundle.py` verifies hash + referential integrity.
2. **Conversion**: Adapter writes simulator-specific inputs and a `feasibility_report.json` sidecar.
3. **Measurement runs**: 3 runs (or 2 for MATSim) with seeds 42, 43, 44.
4. **Metric extraction**: Parse simulator outputs → travel-time stats, throughput.
5. **Result serialisation**: `runs/benchmark_small/benchmark_results_benchmark_small.json`.

---

## 4.4 Measured Results

### 4.4.1 Headline numbers (Apple M4 Pro)

The numbers below come from the most recent canonical stress test (see [CHANGELOG.md](../../CHANGELOG.md), Addendum 3):

| Scenario       | Engine  | Mode  | Trips simulated  | Avg TT (s)  | Runtime (s)  | R-Score |
| -------------- | ------- | ----- | ---------------- | ----------- | ------------ | ------- |
| chicago_1k_car | matsim  | meso  | **1000 (100 %)** | 195.7 ± 0.0 | 10.19 ± 0.16 | 1.0000  |
| chicago_1k_car | sumo    | meso  | 995 (99.5 %)     | 204.1 ± 0.4 |  0.27 ± 0.00 | 0.9981  |
| chicago_1k_car | sumo    | micro | 940 (94.0 %)     | 288.0 ± 0.8 |  1.24 ± 0.01 | 0.9971  |

Total wall-clock across the 8-run matrix: ~22 s.

### 4.4.2 Fidelity (RQ1)

- SUMO meso vs MATSim meso disagree on mean travel time by 8.4 s — driven by MATSim's earlier mobsim release and SUMO's slightly stricter insertion logic.
- SUMO meso and SUMO micro disagree by 84 s on mean travel time — micro captures intersection delays and queue spillback that meso averages out.

### 4.4.3 Scalability (RQ2)

- SUMO meso is **~37 ×** faster than MATSim on the same scenario (0.27 s vs 10.19 s).
- SUMO meso vs SUMO micro: **~4.6 ×** speedup (0.27 s vs 1.24 s) at the 1K tier; the gap widens at higher tiers (see HPC results in `runs/`).
- MATSim's wall-clock is dominated by JVM startup (~5 – 7 s) at this tier.

### 4.4.4 Reproducibility (RQ3)

- All R-scores ≥ 0.997 ("Excellent") across every engine/mode combination.
- MATSim achieves R = 1.0000 (perfectly deterministic with `lastIteration = 0`).
- SUMO micro shows the most variance (R = 0.9971) — Krauss model has small stochastic components.

### 4.4.5 Trade-off Analysis (RQ4)

```
Fidelity ▲
         │  ● SUMO-micro      (highest fidelity, 4–5 × slower than meso at 1K)
         │
         │      ● SUMO-meso   (lower fidelity, near-instant)
         │      ● MATSim      (different model, perfectly deterministic; JVM tax)
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
python -m evaluation.analyze_benchmark runs/benchmark_small/benchmark_results_benchmark_small.json --latex --markdown
```

### 4.5.4 Cross-engine fairness audit

`evaluation/audit_fairness.py` is the methodology check that verifies
the cross-engine comparison was actually fair before any of its results
are reported. For each scenario, it compares the inputs each engine
consumed and the outputs each engine produced, organised as four
checks:

| Check | What it verifies | Pass condition |
|---|---|---|
| **Q1** | Cross-engine feasibility verdict | All engines' `feasibility_report.json` byte-identical (same `feasible_trips`, `total_trips`, `scc_nodes`, `scc_links`, skip counts) |
| **Q2** | Engine input network | All engines emit identical SCC-filtered node + link counts (modulo documented OSM-noise drops) |
| **Q3** | Trips actually simulated | Each engine simulates exactly the cross-engine `feasible_trips` count (MATSim plans, DTALite demand-volume sum, SUMO routes) |
| **Q4** | Cross-engine travel-time spread | Per-engine mean / P95 / completion + pairwise mean-TT ratios — this is the paradigm-spread signal |

```bash
python -m evaluation.audit_fairness runs/benchmark_small
```

The audit is read-only and emits a defender-friendly report. PASS/WARN/FAIL
verdicts on Q1–Q3 are the methodology-section evidence that "the engines
were given the same problem"; the Q4 ratios are the paradigm-spread
signal at the heart of the cross-engine comparison. Sample audit output
on the bundled chicago_1k_car (Pitzer, all three engines) is recorded in
`doc/EXPERIMENT_LOG.md` §3.

---

## 4.6 Threats to Validity

### 4.6.1 Internal Validity

| Threat                        | Mitigation                                                      |
| ----------------------------- | --------------------------------------------------------------- |
| Random seed affecting results | 3 runs per condition with different seeds; report mean ± std    |
| JVM warm-up affecting MATSim  | All runs include the same JVM start cost; comparison is fair-relative |
| OS scheduling noise           | Use `perf_counter()`; HPC runs on dedicated nodes               |
| Adapter conversion errors     | 406 unit tests including byte-identical determinism tests       |
| Scenario validation failures  | Pre-flight validation check before every run                    |
| Trip-count asymmetry across engines | SCC filter at generator + adapter; `feasibility_report.json` audit trail |

### 4.6.2 External Validity

| Threat                              | Mitigation                                                              |
| ----------------------------------- | ----------------------------------------------------------------------- |
| Only 1 US city in the stress test   | Larger HPC tiers cover NYC at 10K and 500K, LA at 50K, Chicago at 200K  |
| Census-calibrated (not real OD)     | Documented realism assessment (~60 – 65 %); exceeds synthetic baselines |
| No transit routing                  | Mode is assigned but not routed; acknowledged limitation                |
| Single peak hour                    | Larger tiers cover 24-hour demand patterns                              |

### 4.6.3 Construct Validity

| Threat                                 | Mitigation                                                |
| -------------------------------------- | --------------------------------------------------------- |
| GEH not universally accepted           | Report multiple metrics (RMSE, KS, GEH) for triangulation |
| Reproducibility index R sensitive to μ | Handle edge cases (μ → 0) explicitly; report CV alongside R |
| Travel time only (no queue lengths)    | Focus on trip-level metrics; acknowledge this limitation  |

---

## 4.7 Reproducibility Checklist

For any researcher to reproduce these experiments:

- [ ] Clone repository (branch `Version_3`).
- [ ] Install `uv`: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- [ ] Provision the canonical environment: `uv python install 3.13 && uv venv --python 3.13 .venv && source .venv/bin/activate && uv pip install -r requirements.lock` (installs Python 3.13.13, all 41 Python deps, AND `eclipse-sumo==1.26.0` in one step).
- [ ] Install Java 17+ for MATSim: `brew install openjdk@17` (macOS) / `apt install openjdk-17-jdk` (Linux) / `module load openjdk/21.0.3_9` (Pitzer — explicit version required by lmod). Then download the MATSim JAR per [SETUP.md](../../SETUP.md).
- [ ] Fetch hash-pinned OSM PBFs: `python tools/download_osm.py` (only required if you plan to *regenerate* bundles; the committed `scenarios/{chicago_1k_car,nyc_10k_car,la_50k_car}/` networks are already built).
- [ ] (Optional, fallback-path only) Pre-warm OSM cache: `python -m pipeline.network.warmup`.
- [ ] Validate the bundled scenarios: `python -m pipeline.validation.validate_bundle scenarios/chicago_1k_car`.
- [ ] Run the canonical benchmark: `python -m execution.run_benchmark runspecs/benchmark_small.yaml`.
- [ ] Analyse: `python -m evaluation.analyze_benchmark runs/benchmark_small/benchmark_results_benchmark_small.json --latex --markdown`.
- [ ] Audit fairness: `python -m evaluation.audit_fairness runs/benchmark_small`.
- [ ] Render figures: `python -m evaluation.generate_plots runs/benchmark_small/benchmark_results_benchmark_small.json`.
- [ ] Verify: all 406 tests pass (`python -m pytest tests/ -q`).
