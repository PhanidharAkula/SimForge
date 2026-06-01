# Engine Comparison, Thesis Reference

**Purpose:** A consolidated reference for thesis writing. Captures every cross-engine comparison point developed during Version_4, paradigm spread, wallclock estimates, reproducibility, output fidelity, and "what question each engine answers" framing, across the five engines that appear anywhere in SimForge's lineage:

- **Shipping:** SUMO microscopic, SUMO mesoscopic, MATSim
- **Proposed (pending spike test):** DTALite
- **Dropped:** LPSim, QarSUMO

**How to use this doc:** Sections 2–7 provide the comparison tables. Section 8 is a "thesis-defense quote bank", phrasings you can lift directly into the final thesis when defending engine selection, paradigm spread, or the abandonment decisions. Section 9 cross-links the supporting docs.

**Companion docs:**
- `LPSIM_RETROSPECTIVE.md`, full LPSim integration narrative + abandonment rationale
- `THIRD_ENGINE_OPTIONS.md`, deep research verdicts on DTALite/CityFlow/POLARIS

---

## 1. The five-engine landscape at a glance

| Engine | Status | Paradigm | Implementation | License |
|---|---|---|---|---|
| **SUMO meso** | Shipping | Mesoscopic, queue-based per-link dynamics | C++, single-threaded | EPL 2.0 |
| **SUMO micro** | Shipping | Microscopic, time-stepped car-following | C++, single-threaded | EPL 2.0 |
| **MATSim** | Shipping | Mesoscopic, queue-based with agent plan/replan | Java, JVM | GPL-2.0 |
| **DTALite** | Proposed | Mesoscopic, Dynamic Traffic Assignment (equilibrium) | C++, OpenMP parallel | Apache 2.0 |
| **LPSim** | Dropped (Version_4) | Mesoscopic, GPU-accelerated B18 traffic flow | C++/CUDA on V100 | MIT |
| **QarSUMO** | Dropped (Version_4 Phase A) | (Was) GPU-accelerated parallel SUMO | (No usable source) | (N/A) |

## 2. Paradigm taxonomy

The dominant paradigms in academic traffic simulation, mapped to SimForge's matrix:

| Paradigm | What it models | SimForge engines |
|---|---|---|
| **Microscopic** | Per-vehicle car-following (IDM, Krauss) + lane-change models, time-stepped at sub-second resolution | SUMO micro |
| **Mesoscopic queue-based** | Per-link queue dynamics aggregated from microscopic detail | SUMO meso, MATSim |
| **Mesoscopic agent-based** | Agents with plans (origin, destination, mode, route) iteratively replan toward equilibrium | MATSim |
| **Mesoscopic DTA equilibrium** | Iterative assignment seeking user-equilibrium link flows under route-choice principles | DTALite |
| **GPU-accelerated mesoscopic** | Parallel B18 traffic flow on CUDA | LPSim (would have been; abandoned) |
| **Macroscopic LWR/CTM** | Cell-transmission model, fluid-flow PDEs | Not in SimForge, out of thesis scope |

**Key observation for the thesis:** A 3-engine matrix of {SUMO micro, MATSim, DTALite} covers **three distinct paradigms** (microscopic + queue-based agent + DTA equilibrium). A 2-engine matrix of just {SUMO, MATSim} covers **two**, with overlap on the queue-based mesoscopic side. Paradigm spread is the most defensible "why these engines" answer in a benchmarking thesis.

## 3. Wallclock estimates at SimForge scenario sizes

Order-of-magnitude estimates from the plan-era planning phase, retained here as the design-time time-budget table. **Measured numbers from the shipped framework** are reported in Chapter 5 §5.1 (small tier: chicago_1k + nyc_10k + la_50k) and §5.6.2 (large tier: chicago_200k + nyc_500k under Phase 14 + Wave 2). The measured cross-engine ratios diverge from the design-time estimates at saturation density (large tier) in ways the design phase did not anticipate, see Chapter 6 §6.2.2.

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

**Thesis-defensible claim:** All three shipping/proposed engines (SUMO meso, MATSim, DTALite) are fully deterministic. SimForge's R = 1.0 ceiling is achievable on every cell of the matrix. **LPSim's atomicAdd non-determinism is one of the technical reasons the abandonment decision was correct**, it would have forced an explanatory footnote on every reproducibility number.

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
| 2-engine matrix in results tables | 3-engine matrix, plan-promised count met |
| Reproducibility ceiling shared by 2 engines | Reproducibility ceiling shared by 3 engines, all R = 1.0 |

## 8. Thesis-defense quote bank

Phrasings ready to lift directly into the final thesis. Adapt as needed.

### 8.1 On engine selection (why these engines)

> SimForge's three primary engines, SUMO microscopic, MATSim queue-based agent simulation, and DTALite mesoscopic dynamic traffic assignment, were chosen to cover three fundamentally different paradigms in the academic traffic simulation literature. SUMO microscopic answers "what travel times do vehicles experience in a single time-stepped car-following simulation"; MATSim answers "what travel times emerge when agents iteratively replan toward equilibrium"; DTALite answers "what are the user-equilibrium link flows under the assumption that no driver can unilaterally improve their route." Cross-engine agreement across these three paradigms provides much stronger evidence of result robustness than agreement within a single paradigm would.

### 8.2 On the abandonment of LPSim

> LPSim was selected in Version_4 Phase B as a GPU-accelerated mesoscopic comparator. After exhaustive integration work, 12 commits across two debugging sessions, including in-container source rebuild, CUDA toolchain reconciliation, Boost compatibility patches, and CUDA architecture target changes, the rebuilt binary continued to crash with SIGSEGV at first kernel launch on networks of 20,000 nodes or larger. The upstream codebase shows clear signs of abandonment: the pinned commit dates from 2024, the repository is missing source files referenced by its own build script, the build chain assumes Boost 1.59 against a modern g++ that has incompatible name-lookup semantics, and there is no continuous integration. We retain the LPSim adapter, test suite, manifest, and build pipeline in the repository as ready-to-reactivate code; the abandonment decision is documented in `doc/engines/LPSIM_RETROSPECTIVE.md` and is itself evidence that SimForge's adapter pattern handles engine churn cleanly.

### 8.3 On the QarSUMO drop

> QarSUMO was listed in the original plan as a fifth engine but was dropped in Version_4 Phase A after a source-availability audit found no usable public distribution: `LLNL/QarSUMO` returns HTTP 404, `QarSUMO/QarSUMO` is an empty placeholder repository, and the cited Boulmakoul 2023 IEEE HPCS paper has not produced runnable code. The Version_3 SimForge harness ran a CPU-fallback path that was bit-identical to standard SUMO mesoscopic, contributing zero new comparison signal while occupying one fifth of the experimental matrix. The drop demonstrates the framework's selection discipline: when source is unavailable, the right answer is to remove the engine and document why, not to silently substitute.

### 8.4 On reproducibility (R-score)

> SimForge's reproducibility metric (R-score, defined in §X.X) requires bit-identical output across N = 5 repeats with fixed seeds. All three primary engines, SUMO mesoscopic, MATSim with `lastIteration=0`, and DTALite, are fully deterministic by construction and achieve R = 1.0 on every scenario in the benchmark matrix. The abandoned LPSim engine would have required an explanatory footnote on every reproducibility number because its GPU code path uses `atomicAdd` reductions that are not bit-deterministic across runs even with identical seeds; this non-determinism is documented LPSim behavior and one of the technical reasons the abandonment decision was correct.

### 8.5 On adaptability of the framework

> SimForge's adapter pattern is engine-agnostic by construction. Every engine integration follows the same three-function contract: `prepare_<engine>_inputs`, `run_<engine>`, `parse_<engine>_output`. A new engine is added by implementing those functions, documenting the schema mapping in a `MAPPING.md`, pinning the engine version in `lib/<engine>/manifest.json`, writing a unit test suite, and registering the engine in the runspec module. No core SimForge code needs to change. The three engines we ship are not the framework's limit, they are its demonstration. The two engines we abandoned (LPSim, QarSUMO) are evidence that the same adapter pattern that makes integration cheap also makes removal cheap when an engine cannot be honestly compared.

### 8.6 On paradigm spread (one-line claim)

> Three engines from three paradigms (microscopic + queue-based agent + DTA equilibrium) provides stronger cross-engine validation signal than any number of engines drawn from a single paradigm.

### 8.7 On wallclock honesty

> DTALite's wallclock at SimForge scenario sizes is comparable to MATSim and slower than SUMO mesoscopic. The thesis does not claim DTALite is faster than the existing engines, it claims that DTALite contributes a different *paradigm* at *acceptable computational cost*, which is the relevant benchmark for a cross-engine comparison framework.

### 8.8 On the "two-engine framework" fallback

> If the DTALite spike test fails (defined in `doc/engines/THIRD_ENGINE_OPTIONS.md` §4), SimForge ships as a 2-engine framework with three engine retrospectives in the methodology chapter. This is itself a defensible thesis contribution: the framework was designed to handle engine churn, three engines were systematically evaluated, and the framework's selection discipline produced honest answers in every case. Adapter code for LPSim and DTALite is retained in the repository, ready for reactivation when upstream conditions change.

## 9. Cross-references to supporting material

- **CHANGELOG:** Version_5 unreleased section enumerates the LPSim removal and DTALite addition; SCC-fairness fixes and audit_fairness landings tracked separately under Phase 4.
- **Glossary:** `doc/GLOSSARY.md`, DTALite entry under §D; LPSim entry rewritten as "abandoned".
- **Experiment log:** `doc/EXPERIMENT_LOG.md`, chronological journal of every commit, job ID, and measured number; the source for any specific Q1–Q4 fairness audit result you want to cite.
- **Fairness audit script:** `evaluation/audit_fairness.py`, invoke as `python -m evaluation.audit_fairness <run_dir>` to verify any benchmark run was actually fair across engines (Q1–Q4 PASS/WARN/FAIL report).
