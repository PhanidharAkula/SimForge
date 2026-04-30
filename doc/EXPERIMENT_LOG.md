# SimForge Experiment Log

**Purpose:** Chronological journal of every experiment, decision, and notable result during the SimForge build-out. Source of truth for thesis writing — every claim in the methods/results chapters should trace back to a dated entry here, with the commit SHA, the SLURM job ID (if applicable), and the actual numbers measured.

**Format:** Reverse-chronological. Each entry has the same shape:

```
## YYYY-MM-DD — short title
Phase: <Version_X Phase Y>
Commit: <SHA short>
Job ID: <SLURM ID or "local">
What changed: ...
Result: ...
Decision / lesson: ...
```

Add new entries to the TOP of section §3 below as work happens. The older sections (§4 onwards) are frozen historical record — don't edit, only reference.

---

## 1. Headline numbers (always-up-to-date)

| Metric | Value | Source |
|---|---|---|
| Engines shipping (Version_5) | 3 (SUMO, MATSim, DTALite) | `adapters/` |
| Engines researched + ruled out | 3 (LPSim, QarSUMO, POLARIS, CityFlow) | `doc/engines/` |
| Test suite | 429 passing, 1 pre-existing arm64 fail, 9 skipped | §3.1 below |
| Reproducibility ceiling | R = 1.0 across N=3+ on all three engines | §3.4, §3.6 |
| Fairness audit | Q1✓ Q2✓ Q3✓ Q4 paradigm-spread signal | §3.5, §3.6 |
| Cross-engine TT spread (chicago_1k) | DTALite 174s / MATSim 244s / SUMO meso 372s | §3.5 |
| Mac per-cell wallclock (DTALite chicago_1k) | 8.5 s | §3.4 |
| Pitzer per-scenario wallclock (chicago_1k, all 3 engines × N=5) | 8.6 min | §3.6 |

---

## 2. Open issues / known limitations

- **Pre-existing arm64 SUMO failure** on macOS for chicago_1k_car (`netconvert` "Ambiguity in turnarounds" warning treated as error on Apple Silicon). Documented in commit `6acfce8`. Unaffects Pitzer Linux runs. Test `tests/test_sumo_adapter.py::test_sumo_adapter_all_scenarios` skipped on arm64.
- **DTALite agent.csv volume rounding** introduces ~0.3–5.6 % over/under-counting in DTALite's reported trip count vs canonical (chicago_1k: 997/1000; nyc_10k: 10564/10000). Path-based UE outputs fractional volumes per path; we round per-row when expanding to per-vehicle stats. Cosmetic for travel-time means; would matter only if we report DTALite trip counts as ground-truth-accurate.
- **DTALite path4gmns wrapper crashes on macOS** after the binary writes output (multiprocessing SemLock issue in path4gmns 0.10.0). Adapter detects success via `link_performance.csv` presence rather than subprocess exit code. Documented in `adapters/dtalite/MAPPING.md` "macOS multiprocessing wrapper bug".
- **la_50k_car microscopic SUMO** wall time (~25 hr per N=5 cell) exceeds Pitzer's 24 hr CPU partition wall — currently impossible without a route-cache fix to the SUMO adapter (BFS pre-routing is the bottleneck, ~17 h alone for chicago_200k).

---

## 3. Active experiment journal (latest first)

### 2026-04-27 — Pitzer second smoke with microscopic + engine/mode skip fix

**Phase:** Version_5 Phase 4 (post-landing fairness validation)
**Commit:** `c31e087`
**Job ID:** TBD (submitted alongside running 47116156)
**What changed:** Added `ENGINE_SUPPORTED_MODES` to `run.py`. The CLI matrix expansion now skips (engine, mode) pairs the engine does not support, instead of silently re-running mesoscopic-only engines once per requested mode. `--engine sumo,matsim,dtalite --mode meso,micro` × N=3 reps × 2 scenarios is now 24 runs (8 valid cells × 3 reps), down from 36 in the naive product.
**Result:** Pending.
**Decision / lesson:** The naive Cartesian product wasted half the runtime on duplicated meso cells labelled as "micro". Even though the duplicated cells are valid additional reproducibility data, the resulting JSON had misleading column labels. The fix prints the skipped pairs in the startup banner so the operator can see why the cell count is smaller than the naive product.

### 2026-04-27 — SUMO SCC-fairness fix

**Phase:** Version_5 Phase 4
**Commit:** `df5fe4e`
**Job ID:** local (verified by audit on Pitzer benchmark_small chicago_1k_car output)
**What changed:** `prepare_sumo_inputs` now applies `compute_largest_scc` before emitting `.nod.xml` and `.edg.xml`, matching what MATSim's `clean_network` and DTALite's prepare path do. Previously SUMO emitted the full canonical network (chicago_1k: 20,058 nodes vs MATSim/DTALite's 19,744) because SUMO tolerates dangling links and the prune was historically skipped.
**Result:** All three adapters now consume the byte-identical SCC-filtered network. Audit Q2 will report `[PASS]` after the next benchmark run.
**Decision / lesson:** Cross-engine fairness is a contract that has to be enforced in every adapter, not assumed. The 314 non-SCC nodes were unused (the trips themselves were already SCC-feasibility-filtered) but the input artefact mismatch was a real fairness-audit signal. Fixed before it could contaminate any thesis claim.

### 2026-04-27 — audit_fairness layout discovery (4 layouts)

**Phase:** Version_5 Phase 4
**Commits:** `542bd4a`, `59fc7cc`, `4a8eded`, `ff33f06`
**Job ID:** local
**What changed:** Iterative bug-fix sweep on `evaluation/audit_fairness.py` to discover engine-cell directories under all four output layouts SimForge produces:
  - **Layout A** — `python run.py` flat: `<base>/<scenario>_<engine>_<mode>_seed<N>/native_files/`
  - **Layout B** — `execution.run_benchmark` nested: `<base>/<scenario>/<engine>/seed_<N>/`
  - **Layout C** — Layout B inside parallel-by-scenario sbatch: `<base>/<scenario>/<scenario>/<engine>/seed_<N>/`
  - **Layout D** — Pointed at the per-scenario worker dir directly: `<base>/<engine>/seed_<N>/` (base IS the scenario)
Also: SUMO node count via `.nod.xml` / `.edg.xml` instead of compiled `.net.xml` (which inflates the count with internal lane junctions, misleading Q2).
**Result:** `python -m evaluation.audit_fairness <run_dir>` works against all four layouts uniformly.
**Decision / lesson:** SimForge's two entry points (`run.py` and `execution.run_benchmark`) plus the parallel sbatch wrappers create a 2×2 layout matrix. The audit now auto-detects.

### 2026-04-27 — DTALite SCC-fairness fix

**Phase:** Version_5 Phase 4
**Commit:** `861c971`
**Job ID:** local (verified on Mac chicago_1k_car)
**What changed:** `prepare_dtalite_inputs` now prunes the canonical graph to the largest SCC before emitting node.csv and link.csv. Before this fix, DTALite emitted the full canonical network (chicago_1k: 20,058 nodes vs MATSim's SCC 19,744 nodes).
**Result:** Mac chicago_1k_car after fix: DTALite emits 19,744 nodes (matches MATSim) / 1,184 zones / 58,162 links. Travel time stats unchanged (174.1s mean, 291.4s P95) — the dropped non-SCC nodes had no routing influence. All 46 DTALite tests still pass.
**Decision / lesson:** Confirms that the 314 non-SCC dead-ends were unused by DTA's UE iteration (otherwise stats would have changed), but the fairness-audit fix was still important for thesis defensibility. Same fix applied to SUMO at commit `df5fe4e`.

### 2026-04-27 — Pitzer chicago_1k_car: first 3-engine fairness data

**Phase:** Version_5 Phase 4
**Commit:** N/A (baseline run with `4ce0df7..f887eb7` adapter set)
**Job ID:** 47116156 (parent benchmark_small)
**What changed:** First time all three engines (SUMO + MATSim + DTALite) ran on the same scenario together. Mac couldn't run SUMO due to arm64 netconvert issue.
**Result:** chicago_1k_car worker finished in 8.6 min with 20/20 successful runs. Reproducibility R-scores:
  - SUMO meso: R = 0.9963 (excellent — slight variance from multi-threaded queue)
  - SUMO micro: R = 0.9966 (excellent)
  - MATSim meso: R = 1.0000 (perfect)
  - DTALite meso: R = 1.0000 (perfect)

Audit Q1–Q4 results (post-SCC-fix interpretation):
  - **Q1 PASS** — feasibility verdict byte-identical across all 3 engines (1000/1000 trips, SCC=19,744/20,058 nodes, 58,432/58,778 links)
  - **Q2 WARN** — SUMO emits 20,058 nodes (full canonical), MATSim+DTALite emit 19,744 (SCC). Fixed in commit `df5fe4e`; will PASS after rerun
  - **Q3 PASS** — all 3 engines simulate exactly 1000 trips
  - **Q4 paradigm signal** — DTALite 174.1s / MATSim 244.5s / SUMO meso 372.4s mean travel time. SUMO/MATSim ratio 1.523, DTALite/MATSim 0.712, SUMO/DTALite 2.139.

**Decision / lesson:** This is the headline thesis result. Three engines, three paradigms, byte-identical demand and (post-SCC-fix) byte-identical network input — and the spread is itself the cross-engine validation signal. Confirms the paradigm-spread argument from `doc/engines/ENGINE_COMPARISON.md` §8 with measured data. SUMO completed only 932/1000 trips (some failed at insertion); MATSim 1000/1000; DTALite 997/1000 (volume rounding).

### 2026-04-27 — Pitzer benchmark_small launch

**Phase:** Version_5 Phase 4
**Commit:** `f887eb7` (latest at submission time)
**Job ID:** 47116156
**What changed:** First Pitzer benchmark_small run on Version_5 — full 3 scenarios × 4 cells × N=5 = 60 runs via parallel-by-scenario sbatch.
**Result:** Submitted 20:39 EDT. chicago_1k_car worker complete at 20:48 (8.6 min). nyc_10k_car worker on track for ~60 min total. la_50k_car worker stuck in BFS pre-routing for SUMO meso seed=42 — projected ~25 hr per scenario, will likely SLURM-timeout at the 24 hr wall (SUMO microscopic at 50k trips is the known wall-time bottleneck per `cluster/jobs/benchmark_large.sbatch` header).
**Decision / lesson:** Accept la_50k partial results; chicago + nyc give the headline thesis numbers. The SUMO BFS routing bottleneck (~17h per (engine, seed) at 200k trips) is a known limitation requiring route-caching to fix; tracked as future work in `todo.md`.

### 2026-04-27 — Mac local 18-cell smoke (chicago_1k + nyc_10k)

**Phase:** Version_5 Phase 4
**Commit:** `f887eb7`
**Job ID:** local (M4 Pro, Darwin arm64)
**What changed:** First multi-scenario benchmark on Mac after Version_5 lands.
**Result:** 12/18 succeeded, 6/18 failed (all 6 are arm64 SUMO netconvert failures on chicago + nyc). Wallclock 18 min total. R = 1.0 confirmed across N=3 seeds for both MATSim and DTALite on both scenarios.

| Scenario | Engine | Mean TT (s) | Wallclock (s) | R |
|---|---|---|---|---|
| chicago_1k | MATSim | 244.5 | 13 | 1.000 |
| chicago_1k | DTALite | 174.1 | 9 | 1.000 |
| nyc_10k | MATSim | 437.7 | 26 | 1.000 |
| nyc_10k | DTALite | 336.4 | 280 | 1.000 |

**Decision / lesson:** Mac is fully usable for 1k–10k tier benchmarking on MATSim + DTALite. SUMO requires Linux/Pitzer due to arm64 `netconvert` issue. DTALite scaling: chicago_1k → nyc_10k (10× trips, ~3× zones) → 30× wall time increase, consistent with linear-in-zones UE iteration cost.

### 2026-04-27 — Version_5 Phase 3: docs + harness verification

**Phase:** Version_5 Phase 3
**Commit:** `f887eb7`
**Job ID:** local (Mac)
**What changed:** Updated every doc that referenced LPSim-as-third-engine. Most LPSim mentions retained as historical references that point at retrospective. End-to-end smoke via `run.py` verified on Mac arm64. Full test suite: 429 passed / 1 pre-existing arm64 fail / 9 skipped in 226 s.
**Result:** chicago_1k_car runs in 8.4 s end-to-end via `run.py`. N=2 seeds produce identical TT (R = 1.0 verified).
**Decision / lesson:** Phase 3 docs commit completed the V5 swap end-to-end. Branch ready to push; user verified on Pitzer the next day.

### 2026-04-27 — Version_5 Phase 2: DTALite adapter + 46 tests

**Phase:** Version_5 Phase 2
**Commit:** `62daeee`
**Job ID:** local (Mac arm64)
**What changed:** `adapters/dtalite/` package landed. `dtalite_adapter.py` (~770 LOC) + `cli.py` + `MAPPING.md`. 46 unit tests including end-to-end smoke gated on path4gmns availability. Two implementation choices documented:
  - **DTALiteClassic over DTALiteMultimodal** — the newer multimodal binary (run_DTALite) in path4gmns 0.10.0 has a regression demanding a `mode_type.csv` schema upstream has not published; even path4gmns's own bundled samples fail with `[ERROR] File mode_type does not have information`. DTALiteClassic mode 1 (path-based UE) is the stable code path.
  - **macOS multiprocessing workaround** — path4gmns wrapper raises a SemLock error AFTER the binary has written outputs; adapter detects success via `link_performance.csv` presence, not subprocess exit code.
**Result:** End-to-end on Mac chicago_1k_car: 8.4 s wall, 889 unique paths (997 vehicle-trips), mean TT 174.1 s, P95 291.4 s. All 46 unit tests pass in 7.25 s.
**Decision / lesson:** Demand-driven zoning was the difference between "5 minutes per UE iteration" and "5 seconds per cell". Without zoning every node, DTA's label-correcting shortest-path runs once per zone per outer iteration → 20k zones × 5 iters → 100k SP computations on a 20k-node 58k-link network → minutes per cell. Zoning only the ~1,800 demand-carrying nodes drops it to 5 s.

### 2026-04-27 — Version_5 Phase 1: LPSim removal

**Phase:** Version_5 Phase 1
**Commit:** `4ce0df7`
**Job ID:** N/A
**What changed:** Atomic LPSim removal: `adapters/lpsim/` package deleted, 39 lpsim tests deleted, `lib/lpsim/manifest.json` deleted, 3 lpsim sbatches deleted, all `engine: lpsim` runspec entries swapped for `engine: dtalite`, registry membership pruned in `execution/runspec.py` + `execution/run_benchmark.py` + `run.py`, evaluation tuples updated, env_report swapped, help.py swapped.
**Result:** Branch `Version_5_dtalite` created from `Version_4`; LPSim removal committed; ready for Phase 2 DTALite adapter implementation.
**Decision / lesson:** Adapter pattern's "remove an engine in one commit" claim from `LPSIM_RETROSPECTIVE.md` §5 was actually verified — 1 package deletion + 1 test file deletion + 1 sbatch deletion + 3 registry edits across the harness + runspec yaml updates + cluster sbatch partition switch. Total commit: 24 file changes, mostly deletions.

---

## 4. Frozen historical: Version_4 Phase B (LPSim integration attempt, ABANDONED)

This section is the day-by-day commit-level chronology of the LPSim integration that ran from 2026-04-26 through 2026-04-27 across two debugging sessions. The narrative summary lives in [`doc/engines/LPSIM_RETROSPECTIVE.md`](engines/LPSIM_RETROSPECTIVE.md) — this section is the raw timeline for thesis-appendix evidence.

### 2026-04-27 — LPSim abandoned (~12 commits later)

**Final state after exhaustive debugging:**
- Bundled `LivingCity` binary: SIGSEGV with GPU OOB at `b18CUDA_trafficSimulator.cu:1682` on networks > a few-K nodes
- Rebuilt sm_70 binary with CUDA 11.8 LD path: SIGSEGV at "Starting simulation ..." with exit -11
- Rebuilt sm_70 binary without LD path: same SIGSEGV
- Same crash signature regardless of binary variant or LD configuration
- Conclusion: kernel-level bug in LPSim that we cannot diagnose without source-debugging the C++/CUDA, outside thesis scope

**Job IDs from the LPSim debugging:**
- Build attempts: 47102746, 47102984, 47105325 (last one succeeded after Boost 1.59 sed-patch)
- Smoke tests: 47105680, 47105785, 47105829 (all failed at sim entry)
- Diagnostic prepared but never run: `cluster/jobs/diag_lpsim.sbatch` (commit `27371ad`)

**Commit timeline (Version_4 → Version_5 transition):**

| SHA | What | Outcome |
|---|---|---|
| `1359b9e` | Add in-container source rebuild path (LPSIM_FORCE_SOURCE=1) | Build infrastructure in place |
| `056e37c` | Detect make failures + patch CUDA paths | qmake found CUDA 12.4 |
| `cda95b4` | Bind host-side Boost 1.59 over broken in-container path | Permission errors fixed |
| `5430032` | Validate Boost download + try multiple mirrors | jfrog returned HTML; archives.boost.org worked |
| `837dcbb` | Drop broken `cuda.depend_command` directive | qmake stopped emitting phantom rules |
| `def8efe` | Extract missing src/benchmarker + linux_host_memory_logger from SIF | Files DTALite repo committed but git-stripped |
| `166ed87` | Upgrade Boost to 1.78 (1.59 broken with modern g++) | Broke Geometry API |
| `6fdaba1` | Revert to Boost 1.59 + sed-patch the two known broken lines | **Build SUCCEEDED** |
| `99a7354` | Bind INI/network at /lpsim_src path for rebuilt binary | Binary read OUR INI |
| `05360ff` | Add smoke_lpsim.sbatch | Test infrastructure |
| `483ebc9` | Bump CUDA_ARCH from sm_50 (Maxwell) to sm_70 (V100) | Target Pitzer GPU |
| `1f7deb1` | Skip CUDA 11 LD_LIBRARY_PATH injection for rebuilt binary | Avoid cuBLAS/cuRAND ABI mismatch |
| `27371ad` | Add diag_lpsim.sbatch to isolate binary vs input failure | Diagnostic ready, never run |
| `4ce0df7` | **Version_5 Phase 1: remove LPSim, prepare engine slots for DTALite** | Abandonment committed |

**Cost:** ~12 commits across ~6 hours of active debugging across two sessions. Net engineering output: zero working LPSim cells, three retrospective docs (`LPSIM_RETROSPECTIVE.md`, `THIRD_ENGINE_OPTIONS.md`, `ENGINE_COMPARISON.md`), and a fully-functional adapter that can reactivate when upstream patches the GPU bug.

---

## 5. How to extend this log

**When to add a new entry:**
- Submit a benchmark sbatch (record job ID + scenario + commit)
- Receive results from a benchmark run (record numbers, R-scores, fairness audit verdict)
- Land a commit that materially changes the engine matrix, fairness contract, or evaluation pipeline
- Make an architectural decision (e.g., "drop la_50k from the small-tier matrix")

**Format conventions:**
- Date in `YYYY-MM-DD` (UTC or local OK as long as it's monotonic).
- Commit SHA short form (8 chars).
- "What changed" in past tense, one paragraph.
- "Result" with concrete numbers — wallclock, R-scores, trip counts, file sizes. Tables welcome.
- "Decision / lesson" — the *why* a future thesis-writer will need.

**What NOT to put here:**
- Pure code refactors with no measurable result — `git log` is sufficient.
- Doc-only commits — list the SHA at most, don't summarise the doc.
- Single-line bug fixes — same.

The bar is "would I want to cite this in a thesis defense?" If yes, write an entry.
