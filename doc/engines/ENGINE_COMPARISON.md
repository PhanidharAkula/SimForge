# Engine Comparison, Thesis Reference

**Purpose:** A consolidated reference for thesis writing. Captures every cross-engine comparison point from the engine evaluation, paradigm spread, wallclock estimates, reproducibility, output fidelity, and "what question each engine answers" framing, across the five engines considered during engine selection:

- **Shipping:** SUMO microscopic, SUMO mesoscopic, MATSim, DTALite (adopted as the third primary engine after the spike test passed)
- **Ruled out:** LPSim, QarSUMO

**How to use this doc:** Sections 2–7 provide the comparison tables. Section 8 is a "thesis-defense quote bank", phrasings you can lift directly into the final thesis when defending engine selection, paradigm spread, or the decisions to rule engines out. Section 9 cross-links the supporting docs.

**Companion docs:**
- `LPSIM_EVALUATION.md`, full LPSim integration narrative + rationale for ruling it out
- `THIRD_ENGINE_OPTIONS.md`, deep research verdicts on DTALite/CityFlow/POLARIS

---

## 1. The five-engine landscape at a glance

| Engine | Status | Paradigm | Implementation | License |
|---|---|---|---|---|
| **SUMO meso** | Shipping | Mesoscopic, queue-based per-link dynamics | C++, single-threaded | EPL 2.0 |
| **SUMO micro** | Shipping | Microscopic, time-stepped car-following | C++, single-threaded | EPL 2.0 |
| **MATSim** | Shipping | Mesoscopic, queue-based with agent plan/replan | Java, JVM | GPL-2.0 |
| **DTALite** | Shipping | Mesoscopic, Dynamic Traffic Assignment (equilibrium) | C++, OpenMP parallel | Apache 2.0 |
| **LPSim** | Ruled out | Mesoscopic, GPU-accelerated B18 traffic flow | C++/CUDA on V100 | MIT |
| **QarSUMO** | Ruled out | (Was) GPU-accelerated parallel SUMO | (No usable source) | (N/A) |

## 2. Paradigm taxonomy

The dominant paradigms in academic traffic simulation, mapped to SimForge's matrix:

| Paradigm | What it models | SimForge engines |
|---|---|---|
| **Microscopic** | Per-vehicle car-following (IDM, Krauss) + lane-change models, time-stepped at sub-second resolution | SUMO micro |
| **Mesoscopic queue-based** | Per-link queue dynamics aggregated from microscopic detail | SUMO meso, MATSim |
| **Mesoscopic agent-based** | Agents with plans (origin, destination, mode, route) iteratively replan toward equilibrium | MATSim |
| **Mesoscopic DTA equilibrium** | Iterative assignment seeking user-equilibrium link flows under route-choice principles | DTALite |
| **GPU-accelerated mesoscopic** | Parallel B18 traffic flow on CUDA | LPSim (would have been; ruled out) |
| **Macroscopic LWR/CTM** | Cell-transmission model, fluid-flow PDEs | Not in SimForge, out of thesis scope |

**Key observation for the thesis:** A 3-engine matrix of {SUMO micro, MATSim, DTALite} covers **three distinct paradigms** (microscopic + queue-based agent + DTA equilibrium). A 2-engine matrix of just {SUMO, MATSim} covers **two**, with overlap on the queue-based mesoscopic side. Paradigm spread is the most defensible "why these engines" answer in a benchmarking thesis.

## 3. Wallclock estimates at SimForge scenario sizes

Order-of-magnitude estimates from the early planning phase, retained here as the design-time time-budget table. **Measured numbers from the shipped framework** are reported in Chapter 5 §5.1 (small tier: chicago_1k + nyc_10k + la_50k) and §5.6.2 (large tier: chicago_200k + nyc_500k with canonical-routes BFS deduplication and container-mode execution). The measured cross-engine ratios diverge from the design-time estimates at saturation density (large tier) in ways the design phase did not anticipate, see Chapter 6 §6.2.2.

| Scenario | SUMO meso | SUMO micro | MATSim | DTALite (est.) | LPSim (would have been) |
|---|---|---|---|---|---|
| chicago_1k_car (20k nodes, 1k trips) | ~5 s | ~30 s | ~60 s | 30–120 s | 5–10 s on V100 |
| nyc_10k_car | ~30 s | ~5 min | ~3 min | 2–5 min | ~30 s |
| chicago_200k_car | ~5 min | ~30 min | ~15 min | 10–20 min | ~3 min |
| nyc_500k_car | ~10 min | ~1+ hr | ~30 min | ~30 min | ~5 min |

**What the table tells the thesis:**

- **DTALite is competitive with MATSim** at every scale and **faster than SUMO micro** at large scale. Not a speedup story, a "different paradigm at acceptable cost" story.
- **LPSim's wallclock advantage was real but only for very large scenarios** (5M+ trips, out of thesis scope). At your scenario sizes, GPU launch overhead dominates and the advantage shrinks to single-digit seconds.
- **The thesis should not claim DTALite is "faster" than current engines**, it isn't. It is *different in paradigm at comparable cost*.

## 4. Reproducibility (the metric SimForge actually scores)

R-score = ratio of inter-run variance to mean (lower is better; R = 1.0 means bit-identical across N=5 reps).

| Engine | Determinism source | Expected R-score |
|---|---|---|
| SUMO meso | Fully deterministic with fixed `--seed` | 1.0 ✅ |
| SUMO micro | Fully deterministic with fixed `--seed` | 1.0 ✅ |
| MATSim | Deterministic with `lastIteration=0` | 1.0 ✅ |
| **DTALite** | Equilibrium-seeking algorithm with fixed iteration order, no atomic reductions | **1.0 expected** ✅ |
| LPSim (would have been) | **Non-deterministic**, `atomicAdd` GPU reductions vary across runs even with same seed (documented LPSim behavior) | < 1.0, would have required a "GPU non-determinism" footnote in every results table |
| QarSUMO (would have been) | Inherits SUMO's determinism (because the fallback was bit-identical to SUMO meso) | 1.0, but trivially, because it added zero new signal |

**Thesis-defensible claim:** All three shipping engines (SUMO meso, MATSim, DTALite) are fully deterministic. SimForge's R = 1.0 ceiling is achievable on every cell of the matrix. **LPSim's atomicAdd non-determinism is one of the technical reasons it was ruled out**, it would have forced an explanatory footnote on every reproducibility number.

## 5. Output fidelity, what each engine produces

| Engine | Per-vehicle output | Per-link output | Equilibrium output | Format |
|---|---|---|---|---|
| SUMO meso | YES (`tripinfo.xml`) | YES (`edgedata`) | NO (one-shot simulation) | XML |
| SUMO micro | YES (`tripinfo.xml`) | YES | NO | XML |
| MATSim | YES (`events.xml`, parsed) | YES (`linkstats`) | After iterations (set `lastIteration > 0`) | XML / TSV |
| DTALite | YES (`agent.csv`) | YES (`link_performance.csv`) | **YES, natively** | CSV |
| LPSim (was) | YES (`<NUM_PASSES>_people.csv`) | NO (aggregated only) | NO | CSV |
| QarSUMO (was) | (would have inherited SUMO's) | (would have inherited SUMO's) | NO | XML |

**Key point for the thesis:** DTALite is the **only engine in the matrix that produces equilibrium output as a first-class artifact**. This makes it useful as a "reference equilibrium" that SUMO meso (one-shot) and MATSim (iteratively converging) can be checked against, a cross-engine *validation* angle, not just a comparison angle.

## 6. The "what question does each engine answer" framing

Each engine answers a *slightly different question* about the same scenario. This is the heart of the cross-engine paradigm-spread argument:

| Engine | The question it answers |
|---|---|
| **SUMO micro** | "What travel times do vehicles experience in a single time-stepped car-following simulation?", high-fidelity, one realization |
| **SUMO meso** | "What travel times do vehicles experience when link dynamics are aggregated to queues?", medium-fidelity, one realization |
| **MATSim** | "What travel times emerge when agents iteratively replan and seek equilibrium over many days?", co-evolutionary equilibrium |
| **DTALite** | "What are the user-equilibrium link flows and travel times under the assumption that no driver can unilaterally improve their route?", analytical iterative equilibrium |
| **LPSim (was)** | (Would have been the same question as SUMO meso, answered on GPU) |
| **QarSUMO (was)** | (Would have been the same question as SUMO meso, answered in parallel, bit-identical fallback meant it answered exactly the same question with exactly the same numbers) |

**The cross-engine comparison is meaningful because the engines answer different questions about the same data.** Agreement across paradigms = strong signal that the answer is robust to modeling-paradigm choice. Disagreement across paradigms = research finding worth reporting.

## 7. What DTALite *adds* vs the current 2-engine framework

| Without DTALite (current) | With DTALite |
|---|---|
| "We benchmarked two mainstream traffic engines" | "We benchmarked three paradigm-distinct engines covering the dominant approaches in the literature" |
| Cross-engine agreement = some signal | Cross-engine agreement across **three paradigms** = much stronger signal |
| No GMNS / open-standard adapter | GMNS adapter demonstrates SimForge handles community standards, not just engine-private formats |
| Engine selection narrative is "the two engines that worked" | Engine selection narrative is "three paradigms validated through systematic ruling-out of two failures + one success" |
| 2-engine matrix in results tables | 3-engine matrix, the planned three-paradigm count met |
| Reproducibility ceiling shared by 2 engines | Reproducibility ceiling shared by 3 engines, all R = 1.0 |

## 8. Thesis-defense quote bank

Phrasings ready to lift directly into the final thesis. Adapt as needed.

### 8.1 On engine selection (why these engines)

> SimForge's three primary engines, SUMO microscopic, MATSim queue-based agent simulation, and DTALite mesoscopic dynamic traffic assignment, were chosen to cover three fundamentally different paradigms in the academic traffic simulation literature. SUMO microscopic answers "what travel times do vehicles experience in a single time-stepped car-following simulation"; MATSim answers "what travel times emerge when agents iteratively replan toward equilibrium"; DTALite answers "what are the user-equilibrium link flows under the assumption that no driver can unilaterally improve their route." Cross-engine agreement across these three paradigms provides much stronger evidence of result robustness than agreement within a single paradigm would.

### 8.2 On ruling out LPSim

> LPSim was evaluated as a third-engine candidate, a GPU-accelerated mesoscopic comparator. After exhaustive integration work, including in-container source rebuild, CUDA toolchain reconciliation, Boost compatibility patches, and CUDA architecture target changes, the rebuilt binary continued to crash with SIGSEGV at first kernel launch on networks of 20,000 nodes or larger. The upstream codebase shows clear signs of abandonment: the pinned commit dates from 2024, the repository is missing source files referenced by its own build script, the build chain assumes Boost 1.59 against a modern g++ that has incompatible name-lookup semantics, and there is no continuous integration. The LPSim adapter, test suite, manifest, and build pipeline remain as ready-to-reactivate code; the decision to rule LPSim out is documented in `doc/engines/LPSIM_EVALUATION.md` and is itself evidence that SimForge's adapter pattern handles engine churn cleanly.

### 8.3 On the QarSUMO drop

> QarSUMO was an early fifth-engine candidate but was ruled out after a source-availability audit found no usable public distribution: `LLNL/QarSUMO` returns HTTP 404, `QarSUMO/QarSUMO` is an empty placeholder repository, and the cited Boulmakoul 2023 IEEE HPCS paper has not produced runnable code. The only path that ran was a CPU fallback bit-identical to standard SUMO mesoscopic, contributing zero new comparison signal while occupying one fifth of the experimental matrix. Ruling it out demonstrates the framework's selection discipline: when source is unavailable, the right answer is to remove the engine and document why, not to silently substitute.

### 8.4 On reproducibility (R-score)

> SimForge's reproducibility metric (R-score, defined in §X.X) requires bit-identical output across N = 5 repeats with fixed seeds. All three primary engines, SUMO mesoscopic, MATSim with `lastIteration=0`, and DTALite, are fully deterministic by construction and achieve R = 1.0 on every scenario in the benchmark matrix. The ruled-out LPSim engine would have required an explanatory footnote on every reproducibility number because its GPU code path uses `atomicAdd` reductions that are not bit-deterministic across runs even with identical seeds; this non-determinism is documented LPSim behavior and one of the technical reasons it was ruled out.

### 8.5 On adaptability of the framework

> SimForge's adapter pattern is engine-agnostic by construction. Every engine integration follows the same three-function contract: `prepare_<engine>_inputs`, `run_<engine>`, `parse_<engine>_output`. A new engine is added by implementing those functions, documenting the schema mapping in a `MAPPING.md`, pinning the engine version in `lib/<engine>/manifest.json`, writing a unit test suite, and registering the engine in the runspec module. No core SimForge code needs to change. The three engines we ship are not the framework's limit, they are its demonstration. The two engines we ruled out (LPSim, QarSUMO) are evidence that the same adapter pattern that makes integration cheap also makes removal cheap when an engine cannot be honestly compared.

### 8.6 On paradigm spread (one-line claim)

> Three engines from three paradigms (microscopic + queue-based agent + DTA equilibrium) provides stronger cross-engine validation signal than any number of engines drawn from a single paradigm.

### 8.7 On wallclock honesty

> DTALite's wallclock at SimForge scenario sizes is comparable to MATSim and slower than SUMO mesoscopic. The thesis does not claim DTALite is faster than the existing engines, it claims that DTALite contributes a different *paradigm* at *acceptable computational cost*, which is the relevant benchmark for a cross-engine comparison framework.

### 8.8 On the "two-engine framework" contingency

> Had the DTALite spike test failed (defined in `doc/engines/THIRD_ENGINE_OPTIONS.md` §4), SimForge would have shipped as a 2-engine framework with three engine evaluations in the methodology chapter, itself a defensible thesis contribution: the framework was designed to handle engine churn, three engines were systematically evaluated, and the selection discipline produced honest answers in every case. The spike passed and DTALite shipped as the third primary engine; `LPSIM_EVALUATION.md` is the surviving record of the LPSim integration attempt.

## 9. Cross-references to supporting material

- **CHANGELOG:** enumerates the DTALite addition; SCC-fairness fixes and audit_fairness landings tracked separately under the fairness-audit work.
- **Glossary:** `doc/GLOSSARY.md`, DTALite entry under §D; LPSim entry marked "ruled out".
- **Experiment log:** `doc/EXPERIMENT_LOG.md`, chronological journal of every commit, job ID, and measured number; the source for any specific Q1–Q4 fairness audit result you want to cite.
- **Fairness audit script:** `evaluation/audit_fairness.py`, invoke as `python -m evaluation.audit_fairness <run_dir>` to verify any benchmark run was actually fair across engines (Q1–Q4 PASS/WARN/FAIL report).
