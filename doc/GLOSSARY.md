# SimForge Glossary

Reference for the acronyms and domain terms that appear across the codebase, the thesis chapters, and this documentation set. Entries are alphabetised; cross-references use *italics*.

---

## A

### Adapter
A simulator-specific module under `adapters/<engine>/` that converts a *canonical scenario bundle* into the engine's native input files and parses its output back into a uniform metric object. Adapters are intentionally thin: their only responsibility is byte-deterministic translation.

### Asymmetric coverage
A *coverage diagnostic* class flagged when an `(engine, mode)` cell is present in some scenarios of a *RunSpec* but missing in others. Caught by `evaluation/analyze_benchmark.py`.

---

## C

### Canonical schema
The simulator-agnostic intermediate representation defined in `canonical/schema/`. A scenario bundle consists of `network.xml`, `demand.csv`, `signals.xml`, `config.xml`, and `manifest.xml`. Documented in `doc/SCENARIO_GENERATION.md`.

### Census tract
A US Census Bureau geographic unit of ~4,000 residents. SimForge uses *PUMS* tract-level demographic and commute data to calibrate trip origins and travel-time targets.

### Coverage diagnostic
The audit emitted by `evaluation/analyze_benchmark.py` that flags three classes of silent gap: *low-sample cells*, *asymmetric coverage*, and silently-failed cells. See `doc/RESULTS_GUIDE.md` §4.1.

---

## D

### Determinism (byte-identical)
Property tested by `tests/test_adapter_determinism.py`: two adapter runs with the same input bundle and the same seed produce byte-identical output files. Distinct from *reproducibility*, which is a statistical property of the simulator output itself.

---

## F

### Feasibility report
A `feasibility_report.json` sidecar written next to every adapter's output. Records the *SCC*-derived feasible-trip set and any drops the adapter applied. Used as the audit trail proving every engine in a *RunSpec* received the same input set.

### Fidelity
The dimension of evaluation that compares simulator outputs against each other or against ground truth. Measured by *RMSE*, *GEH*, and *KS statistic*. See `evaluation/metrics/fidelity.py`.

---

## G

### GEH (Geoffrey E. Havers statistic)
A traffic-engineering goodness-of-fit metric, $\text{GEH} = \sqrt{\frac{2(M - C)^2}{M + C}}$, where $M$ is the modelled volume and $C$ is the observed count. Acceptance criterion: ≥ 85 % of links with $\text{GEH} < 5.0$. Implementation: `evaluation/metrics/fidelity.py:compute_geh`.

---

## J

### JWMNP
US Census variable for "Travel time to work, in minutes". One of the two PUMS columns SimForge uses to calibrate per-tract trip-distance distributions.

### JWTRNS
US Census variable for "Means of transportation to work" (car, transit, bike, walk, …). Drives mode assignment in census-calibrated demand generation.

---

## K

### Krauss model
The default car-following model used by SUMO microscopic. A modified Gipps formulation with a stochastic sigma parameter that produces small run-to-run variance (visible as the SUMO micro R-score being slightly below 1.0; see Table 5.2).

### KS statistic (Kolmogorov–Smirnov)
A non-parametric statistic measuring the largest gap between two empirical distributions: $D = \sup_x |F_1(x) - F_2(x)|$. SimForge applies it to travel-time distributions across simulators. Implementation: `evaluation/metrics/fidelity.py:compute_ks_statistic`.

---

## L

### Low-sample cell
A *coverage diagnostic* class flagged when an `(engine, mode)` cell has fewer than 3 successful runs. R-scores in low-sample cells are statistically weak and the diagnostic prints a warning so they are not over-interpreted. MATSim cells are intentionally low-sample (n = 2) because the engine is deterministic.

---

## M

### Manifest
`manifest.xml` inside a canonical scenario bundle. Lists every artefact in the bundle along with its SHA-256 hash, used by `pipeline/validation/validate_bundle.py` to detect tampered or partially-generated bundles.

### MATSim
Multi-Agent Transport Simulation; an activity-based, event-driven, queue-mobsim simulator written in Java. SimForge bundles MATSim 15.0 and runs it in single-iteration mode (`lastIteration = 0`) for reproducibility.

### Mesoscopic (meso)
A simulation paradigm that aggregates per-vehicle behaviour into per-link queue dynamics. Faster than *microscopic* but does not capture intersection-level delays. SUMO meso, QarSUMO meso, and MATSim are all mesoscopic.

### Microscopic (micro)
A simulation paradigm that models each vehicle individually with car-following and lane-changing dynamics. Higher fidelity at the cost of order-of-magnitude longer runtime. SUMO micro is the only microscopic engine in the canonical *RunSpec*.

### ModelGen
The PUMS-based population generator (`pipeline/demand/modelgen/`). Produces tract-level synthetic populations with calibrated demographics and commute patterns.

### MUTCD
Manual on Uniform Traffic Control Devices — the US federal standard for traffic signal phasing. SimForge's signal-inference pipeline (`pipeline/signals/`) targets MUTCD-compatible phase timings inferred from intersection geometry.

---

## N

### NEMA
National Electrical Manufacturers Association. NEMA TS 1/2 defines the standard 8-phase ring-and-barrier signal controller layout used by SimForge's signal generator.

---

## O

### OSM (OpenStreetMap)
The crowdsourced geographic data source SimForge uses for road network topology. Fetched via the *Overpass* API and cached in `cache/`.

### Overpass
The OSM query API (`https://overpass-api.de`). Network fetches are HTTP-cached so re-runs do not re-hit the upstream server. Pre-warm with `python -m pipeline.network.warmup`.

---

## P

### P95 travel time
The 95th percentile of trip durations within a single run. Used as a tail-latency indicator in Fig 5.8 and complements the mean travel time reported in Table 5.2.

### PUMS (Public Use Microdata Sample)
The US Census Bureau dataset of de-identified individual-level census records. SimForge uses PUMS columns *JWMNP* and *JWTRNS* to calibrate demand. Default since the census-calibrated demand became the framework default; pass `--synthetic` to fall back to the gravity model.

---

## Q

### QarSUMO
A GPU-accelerated SUMO fork from LLNL (<https://github.com/LLNL/QarSUMO>) requiring NVIDIA CUDA 11.0+. SimForge's QarSUMO adapter falls back to standard SUMO when CUDA is absent and emits a log line saying so — outputs are bit-identical to SUMO meso in fallback mode. The fallback path is the one exercised on the Apple M4 Pro test bench.

---

## R

### Reproducibility (R-score)
The cross-seed consistency metric, $R = 1 - \sigma/\mu$, where $\sigma$ is the standard deviation and $\mu$ is the mean of mean-travel-time across repeats with different seeds. Rated Excellent (≥ 0.95), Good (0.90 – 0.95), Moderate (0.80 – 0.90), or Poor (< 0.80). Implementation: `evaluation/metrics/reproducibility.py:compute_reproducibility_index`.

### RMSE (Root Mean Square Error)
$\text{RMSE} = \sqrt{\frac{1}{n}\sum (y_i - \hat{y}_i)^2}$. Used to compare a simulator's trip-level output against another simulator (cross-engine) or against ground-truth observations (where available). Implementation: `evaluation/metrics/fidelity.py:compute_rmse`.

### RunSpec
The YAML configuration consumed by `execution/run_benchmark.py`. Declares the matrix of `(scenario × engine × mode)` cells, the seed list, and the repeat count. Canonical example: `runspecs/stress_test.yaml`.

---

## S

### SCC (Strongly Connected Component)
A maximal subgraph in which every node is reachable from every other node. SimForge computes the largest SCC of each scenario network with iterative Kosaraju (`pipeline/network/scc.py`) and rejects any trip whose origin or destination falls outside it. This guarantees every engine in a *RunSpec* receives the same routable trip set, recorded in `feasibility_report.json`.

### Signals
Traffic signal timing plans, written to `signals.xml` in a scenario bundle. Inferred from OSM intersection geometry by `pipeline/signals/`.

### SimForge
The framework documented by this repository — the cross-simulator benchmarking harness, the *canonical schema*, the adapters, and the evaluation tooling.

### SRT (Simulated time : Real time)
The ratio `simulated_time / wall_clock_time`. SRT > 1 means the simulator runs faster than real time. Reported by `evaluation/metrics/scalability.py`.

### SUMO (Simulation of Urban MObility)
The Eclipse open-source traffic simulator. SimForge bundles SUMO 1.20+ and uses it in both *microscopic* and *mesoscopic* modes via the same `adapters/sumo/` adapter.

---

## T

### Throughput
`trip_count / runtime`, expressed in trips/sec. The headline scaling metric reported in Fig 5.4 and Fig 5.9.

### TraCI
SUMO's Traffic Control Interface — a TCP socket protocol for runtime interaction with a running SUMO instance. SimForge does **not** use TraCI; all SUMO adapter interaction is file-based (input XMLs in, `tripinfo.xml` and `statistics.xml` out) for byte-deterministic execution.

### tripinfo.xml
SUMO's per-trip output XML, parsed by `evaluation/metrics/travel_time.py:parse_sumo_tripinfo` to extract mean travel time, P95, and trip count.

---

## V

### Validation
The pre-flight checks run by `pipeline/validation/validate_bundle.py` before any simulation: schema conformance, manifest hash match, referential integrity (every demand entry references a valid network node), and SCC reachability.

---

*Cross-reference: see `doc/RESULTS_GUIDE.md` for how each term shows up in the analysis output, `doc/SCENARIO_GENERATION.md` for canonical-schema details, and `doc/chapters/methods.md` for the formal definitions.*
