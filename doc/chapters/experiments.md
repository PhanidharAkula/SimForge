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

> The plan listed five engines (SUMO, MATSim, POLARIS, LPSim, QarSUMO). After two integration cycles, the matrix narrows to **three primary engines** chosen for paradigm spread: SUMO microscopic (car-following), MATSim queue-based agent simulation, and DTALite mesoscopic Dynamic Traffic Assignment. Three of the originally-proposed engines were systematically evaluated and ruled out: QarSUMO dropped in Version_4 Phase A (no usable public source), LPSim integrated in Version_4 Phase B and abandoned in Version_5 (GPU kernel SIGSEGV on networks > a few-K nodes), POLARIS and CityFlow evaluated as third-engine alternatives and rejected at criteria. Full retrospectives in [`doc/engines/`](../engines/). The canonical 11-cell matrix exercises all four (engine × mode) combinations across three scenarios at N = 5 repeats each, and is fully CPU-only — the 1 K tier runs end-to-end on a Mac laptop in under a minute; the 10 K and 50 K tiers fit inside a single Pitzer SLURM job (~22-23 h wall-clock) with the Phase 12 BFS-prep cache.

**Variable 2: Scenario Scale**

The canonical `benchmark_small.yaml` runspec covers **three tiers** spanning two orders of magnitude in trip count. The 1 K tier is laptop-runnable; the 10 K and 50 K tiers require an HPC node for the SUMO micro and DTALite cells. Larger tiers (200 K, 500 K) are generated locally via helper scripts and reserved for separate HPC runs.

| Tier         | Trip Count | Helper script | In `benchmark_small.yaml` | Where it runs |
|---|---|---|---|---|
| **Bundled** | **1,000** | `scripts/01_chicago_1k_car.py` | ✅ | Laptop (Apple Silicon) |
| **Small** | **10,000** | `scripts/02_nyc_10k_car.py` | ✅ | Laptop (cached) / cluster |
| **Medium** | **50,000** | `scripts/03_la_50k_car.py` | ✅ | Cluster (Pitzer 36 h walltime) |
| Large | 200,000 | `scripts/04_chicago_200k_car.py` | (separate runspec) | Cluster |
| Stress | 500,000 | `scripts/05_nyc_500k_car.py` | (separate runspec) | Cluster (Linux only) |

**Variable 3: City Network (3 metropolitan areas in the canonical matrix)**

| City    | Bundle            | Nodes (in SCC) | Links (in SCC) | SCC % | Character             |
| ------- | ----------------- | -------------- | -------------- | ----- | --------------------- |
| Chicago | `chicago_1k_car`  | 19,744         | 58,432         | 98.4 % | Dense grid, mixed use |
| NYC     | `nyc_10k_car`     | 33,988         | 105,009        | 99.6 % | Multi-borough mix     |
| LA      | `la_50k_car`      | 158,690        | 466,518        | 99.8 % | Sprawling freeway-dominated |

The three scenarios span ~8× in node count and ~8× in link count, while the trip count spans 50× (1K → 50K). This decouples the *network-size* effect from the *demand-density* effect in the scaling analysis (§5.1, §5.5).

**Why Chicago, NYC, and LA:**

- **Chicago** — classic American grid; mix of arterials and residential streets; ModelGen census coverage is most complete. Dense enough to exercise all three engines end-to-end while remaining small enough to ship as a bundled artefact.
- **NYC** — multi-borough, irregular network topology; tests the engines on a network with mixed grid + organic geometry. The 10 K trip volume crosses the threshold where SUMO micro becomes a coffee-break run (~3 min per seed).
- **LA** — sprawling freeway-dominated network; largest tested network (~470 K links). The 50 K trip volume tests the engines at the boundary of practical UE convergence (DTALite hits a path4gmns binary-side scaling ceiling at this size — see §5.7).

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

The matrix declared by `runspecs/benchmark_small.yaml` (11 cells × 5 repeats = **55 runs total**):

| Scenario | Engine | Mode | Trips | Repeats |
|---|---|---|---|---|
| chicago_1k_car | sumo | mesoscopic | 1,000 | 5 |
| chicago_1k_car | sumo | microscopic | 1,000 | 5 |
| chicago_1k_car | matsim | mesoscopic | 1,000 | 5 |
| chicago_1k_car | dtalite | mesoscopic | 1,000 | 5 |
| nyc_10k_car | sumo | mesoscopic | 10,000 | 5 |
| nyc_10k_car | sumo | microscopic | 10,000 | 5 |
| nyc_10k_car | matsim | mesoscopic | 10,000 | 5 |
| nyc_10k_car | dtalite | mesoscopic | 10,000 | 5 |
| la_50k_car | sumo | mesoscopic | 50,000 | 5 |
| la_50k_car | matsim | mesoscopic | 50,000 | 5 |
| la_50k_car | dtalite | mesoscopic | 50,000 | 5 |

la_50k_car drops SUMO microscopic by design — at 50 K trips a single arm64 SUMO micro run wall-clocks past 4 h, which is impractical for a "small tier" matrix and provides little additional paradigm signal beyond chicago_1k + nyc_10k micro. MATSim and DTALite are mesoscopic-only by design.

Every `feasibility_report.json` confirms `feasible_trips` matches the trip count for every adapter (verified by Q1 of `audit_fairness`), so the four engines simulate exactly the same trip set per cell. All three engines are CPU-only and the full matrix completes inside a single Pitzer SLURM job (~22-23 h with the Phase 12 BFS-prep cache populated by the first seed of each scenario × engine pair).

**Control variables** (held constant across all conditions):

| Parameter | Value | Rationale |
|---|---|---|
| Random seeds | 42, 43, 44, 45, 46 | Reproducible; 5 runs per cell |
| Demand strategy | Census-calibrated (ModelGen + PUMS) | Consistent realistic inputs |
| Routing | State-aware BFS with OSM turn restrictions | Deterministic, version-independent |
| Time horizon | 1 hour (3,600 s) | Standard morning peak period |
| MATSim iterations | 1 (`lastIteration = 0`, no replanning) | Fair comparison with SUMO single-pass mode |
| DTALite iterations | 5 column-gen + 5 column-update | Standard UE convergence |
| Feasibility filter | SCC-based | Same trip set fed to every engine |

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

Used for the canonical 11-cell `benchmark_small` matrix (chicago_1k + nyc_10k + la_50k). The 1 K tier alone is laptop-runnable; the 10 K and 50 K tiers need HPC because (a) SUMO micro at 10 K is a coffee-break run, and (b) DTALite at 10 K + has super-linear UE iteration cost. All three primary engines (SUMO, MATSim, DTALite) are CPU-only after the LPSim removal in Version_5. See `doc/PITZER.md` for the operational guide and `cluster/jobs/benchmark_small.sbatch` for the canonical sbatch script (Phase 12.4: `--mem=128G`, `--cpus-per-task=16`, `--time=36:00:00`).

| Component       | Specification                                                    |
| --------------- | ---------------------------------------------------------------- |
| Cluster         | Ohio Supercomputer Center — Pitzer (RHEL 9, SLURM)               |
| CPU per node    | Intel Xeon Skylake (40 cores) or Cascade Lake (48 cores), 192 GB |
| Large-mem nodes | Up to 3 TB RAM (`hugemem` partition)                             |
| Partitions used | `cpu` (all three shipped engines are CPU-only after the Version_5 LPSim retirement) |
| Max wall time   | 7 days (`cpu`, `gpu`); 14 days (`longcpu`, restricted)            |
| Storage         | Home 500 GB, Project (`PMIU0110`) 500 GB, scratch per-job        |
| Project account | `--account=PMIU0110`                                              |
| Internet access | Outbound via NAT on login + compute nodes (PyPI, GitHub; Overpass used only as fallback — primary OSM ingest uses state PBFs staged under `~/SimForge/osm_data/`) |

### 4.3.3 Software Versions

| Software | Version      | Installation              | Notes               |
| -------- | ------------ | -------------------------- | ------------------- |
| Python   | 3.13.x       | `setup_simforge.py`        | Bootstrapper        |
| SUMO     | 1.26.0       | `uv pip install eclipse-sumo==1.26.0` (separate from `requirements.lock`; the wheel is manylinux_2_28_x86_64-only and pinned outside the cross-platform lockfile) | Mandatory           |
| MATSim   | 15.0         | JAR                        | `lib/matsim-15.0/`  |
| Java     | 17           | Homebrew                   | MATSim runtime      |
| DTALite  | path4gmns 0.10.0 | bundled in `requirements.lock` (`path4gmns` wheel) | CPU mesoscopic DTA; on Mac needs `brew install libomp` |
| osmnx    | 2.x (`>=2.0,<3`) | pip               | Parse PBF slice → graph, bbox truncate (`bbox=(W,S,E,N)` tuple)  |
| pyosmium | 4.x          | pip (`osmium`)             | Bbox-slice Geofabrik PBFs in `osm_data/` |
| lxml     | 5.x          | pip                        | XML processing      |
| pandas   | 2.x          | pip                        | Demand CSV handling |

### 4.3.4 Execution Protocol

For each cell of the 11-cell matrix:

1. **Validation**: `validate_bundle.py` verifies hash + referential integrity for the scenario bundle.
2. **Conversion**: Adapter writes simulator-specific inputs (network XML, plans/routes, settings) plus a `feasibility_report.json` sidecar. Phase 12 BFS-prep cache: the first seed populates a per-engine cache; the remaining 4 seeds hardlink the cached prep into their cell directories (~93 s/seed for cached SUMO meso vs ~28,681 s/seed for the cold first seed at la_50k).
3. **Measurement runs**: 5 runs per cell with seeds {42, 43, 44, 45, 46}.
4. **Metric extraction**: Parse simulator outputs → travel-time stats, throughput. SUMO via `parse_sumo_tripinfo` (tripinfo.xml), MATSim via `parse_matsim_output` (output_trips.csv.gz), DTALite via `parse_dtalite_output` (link_performance.csv + agent.csv).
5. **Result serialisation**: `runs/benchmark_small/<scenario>/benchmark_results_benchmark_small.json` per scenario; the parallel-by-scenario sbatch (Phase 12) produces three independent JSONs that the analyzer + audit_fairness can read together.

---

## 4.4 Measured Results

### 4.4.1 Headline numbers (OSC Pitzer Intel Xeon Skylake, 16 cores per worker)

The numbers below come from Pitzer SLURM jobs `47237978` (initial run) + `47248311` (post-Phase-12.4 re-queue) + `tools/recover_partial_summary.py` (Phase 12.5 synthesis for la_50k_car DTALite cells). See [CHANGELOG.md](../../CHANGELOG.md) Phase 12 series for the full diagnostic chain. Chapter 5 (Results) reproduces these numbers verbatim from the on-disk JSONs at `runs/benchmark_small/<scenario>/benchmark_results_benchmark_small.json` — see §5.1 (Table 5.1), §5.2 (Table 5.2), §5.3 (Fig 5.3 cross-engine ratios), §5.7 (DTALite scaling-ceiling discussion).

Compact summary (full 11-cell table is Table 5.1 in Chapter 5):

| Scenario | SUMO/MATSim mean-TT ratio | SUMO meso runtime | MATSim meso runtime | DTALite meso runtime |
|---|---|---|---|---|
| chicago_1k_car | 0.869 (-13.1 %) | 9.50 s | 8.00 s | 22.26 s |
| nyc_10k_car | 1.132 (+13.2 %) | 19.90 s | 15.24 s | 583.06 s |
| **la_50k_car** | **1.046 (+4.6 %)** | 91.68 s | 52.98 s | _did not converge — see §5.7_ |

### 4.4.2 Fidelity (RQ1)

- **Cross-engine alignment improves with scale.** SUMO/MATSim mean-TT gap narrows from ±13 % at 1 K and 10 K → +4.6 % at 50 K. The convergence is law-of-large-numbers: with more trips, per-trip differences between SUMO's stricter insertion logic and MATSim's earlier mobsim release average out. This is the central paradigm-spread finding (§5.3).
- **DTALite UE underestimates travel time vs queue-based mobsim by ~40-45 %** at the scales where it converges (chicago_1k, nyc_10k). Expected behaviour: equilibrium assignment ignores transient congestion build-up and dissipation that event-driven mobsim captures.
- **SUMO meso vs SUMO micro disagree by 28-73 % on mean travel time** (gap grows with scale) — micro captures intersection delays and queue spillback.

### 4.4.3 Scalability (RQ2)

- **SUMO meso : MATSim meso runtime ratio** narrows with scale: 1.19× at 1 K → 1.31× at 10 K → 1.73× at 50 K (MATSim faster at 50 K; JVM startup amortises).
- **SUMO meso vs SUMO micro speedup** widens with scale: 1.65× at 1 K → 9.01× at 10 K (micro becomes a coffee-break run at 10 K).
- **DTALite super-linear cost.** From 22 s (1 K) → 583 s (10 K) is 26× cost for 10× trips. Beyond 10 K the path4gmns 0.10.0 binary's 4-thread cap makes it prohibitive — la_50k_car would need ~25 h per seed at observed rates (§5.7).
- **MATSim's per-trip cost amortises the JVM tax rapidly.** ~7 s startup + per-trip work; at 50 K, MATSim achieves 944 trips/s — the highest throughput at any tested tier (§5.5).

### 4.4.4 Reproducibility (RQ3)

- **MATSim is byte-deterministic at all scales** (R = 1.0000 across all 3 scenarios) with `lastIteration = 0`.
- **DTALite is byte-deterministic where it converges** (R = 1.0000 at chicago_1k and nyc_10k; la_50k did not converge).
- **SUMO R drops with scale but stays "Good"**: 0.9982 (1 K) → 0.9564 (10 K, worst case) → 0.9804 (50 K). CV stays < 5 % everywhere. SUMO is *reproducible* in the engineering sense but not byte-deterministic like MATSim and DTALite.

### 4.4.5 Trade-off Analysis (RQ4)

```
Fidelity ▲
         │  ● SUMO-micro     (highest fidelity; 9× slower than meso at 10K, infeasible at 50K)
         │
         │      ● SUMO-meso  (lower fidelity, scales linearly with trip count)
         │      ● MATSim     (different mobsim, byte-deterministic; JVM-tax floor)
         │      ● DTALite    (UE equilibrium; -40% mean TT; super-linear cost; 4-thread cap at 50K)
         │
         └──────────────────────────────────────▶ Speed
```

**Key trade-off**: The 1 K tier is too small to be practically interesting — all four cells finish in ≤ 22 s. The decisive trade-offs surface at 10 K + (SUMO micro becomes coffee-break) and 50 K + (SUMO micro infeasible, DTALite hits path4gmns scaling ceiling). The published thesis numbers cover all three regimes; future work would extend to 200 K and 500 K once the path4gmns ceiling is mitigated (§5.7).

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

`evaluation/generate_plots.py` emits 10 figures (5.1 – 5.10). See [doc/RESULTS_GUIDE.md](../RESULTS_GUIDE.md) for the per-figure description.

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

| Threat | Mitigation |
|---|---|
| Random seed affecting results | 5 runs per condition with seeds {42, 43, 44, 45, 46}; report mean ± 95 % CI |
| JVM warm-up affecting MATSim | All runs include the same JVM start cost; comparison is fair-relative; cost amortises < 30 % at 10 K + |
| OS scheduling noise | Use `perf_counter()`; HPC runs on dedicated nodes; cached cell std < 5 % CV |
| Adapter conversion errors | ~633 unit tests (with all 5 bundles generated) including byte-identical determinism tests |
| Scenario validation failures | Pre-flight validation check before every run |
| Trip-count asymmetry across engines | SCC filter at generator + adapter; `feasibility_report.json` audit trail; `audit_fairness` Q1 PASS on all 3 scenarios |
| MATSim adapter route-format ambiguity | Phase 12.1 fix: `<route type="links">` text content includes start_link + end_link tokens; verified by 0-trip → 1000-trip empirical check |
| path4gmns 0.10.0 4-thread cap on DTALite | Discovered Phase 12.5; documented as scaling ceiling (§5.7); affects la_50k_car DTALite cells only |

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

- [ ] Clone repository (branch `phase-14-canonical-routes` for the active development tip, or `main` for the thesis-tagged snapshot). The fully reproducible thesis-default container image is pinned at `ghcr.io/phanidharakula/simforge:db8d786` (see §3.11.5).
- [ ] Install `uv`: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- [ ] Provision the canonical environment: `uv python install 3.13 && uv venv --python 3.13 .venv && source .venv/bin/activate && uv pip install -r requirements.lock && uv pip install eclipse-sumo==1.26.0` (installs Python 3.13.13, the 35 lockfile-pinned packages including `path4gmns==0.10.0`, then `eclipse-sumo==1.26.0` separately — the eclipse-sumo wheel is manylinux_2_28_x86_64-only and excluded from the cross-platform lockfile). Alternatively pull the pinned container; see §3.11.
- [ ] Install Java 17+ for MATSim: `brew install openjdk@17` (macOS) / `apt install openjdk-17-jdk` (Linux) / `module load openjdk/21.0.3_9` (Pitzer — explicit version required by lmod). Then download the MATSim JAR per [SETUP.md](../../SETUP.md).
- [ ] (macOS only, for DTALite OpenMP runtime) `brew install libomp`.
- [ ] Fetch hash-pinned OSM PBFs: `python tools/download_osm.py` (only required if you plan to *regenerate* bundles; the committed `scenarios/{chicago_1k_car,nyc_10k_car,la_50k_car}/` networks are already built).
- [ ] Validate the bundled scenarios: `python -m pipeline.validation.validate_bundle scenarios/{chicago_1k_car,nyc_10k_car,la_50k_car}`.
- [ ] Submit the canonical 55-cell benchmark on Pitzer: `sbatch cluster/jobs/benchmark_small.sbatch` (~22-23 h walltime with Phase 12 BFS-prep cache; uses `--mem=128G` and `--cpus-per-task=16` per Phase 12.4). On a Mac, run only the 1 K cells: `python -m execution.run_benchmark runspecs/benchmark_small.yaml --scenario chicago_1k_car`.
- [ ] (If a Pitzer worker is killed before writing its summary JSON, recover from disk:) `python -m tools.recover_partial_summary --runspec runspecs/benchmark_small.yaml --scenario <scenario_id> --base-dir runs/benchmark_small/<scenario_id>`.
- [ ] Analyse: `python -m evaluation.analyze_benchmark runs/benchmark_small/benchmark_results_benchmark_small.json --latex --markdown`.
- [ ] Audit fairness: `python -m evaluation.audit_fairness runs/benchmark_small`.
- [ ] Render figures: `python -m evaluation.generate_plots runs/benchmark_small/benchmark_results_benchmark_small.json --output doc/figures`.
- [ ] Verify: all ~633 tests pass (`python -m pytest tests/ -q`) with all 5 generated bundles present. On Apple Silicon arm64, 3 SUMO-dependent tests skip individually due to a known `netconvert` segfault on large networks; this is documented in `tests/conftest.py`.
