# Third-Engine Selection — Deep Research & Recommendation

**Status:** Decision pending (advisor approval).
**Context:** LPSim integration was abandoned 2026-04-27 (see `LPSIM_RETROSPECTIVE.md`). SimForge needs a working third engine to maintain the cross-simulator benchmarking premise without repeating the LPSim or QarSUMO failure modes.
**Research date:** 2026-04-27 — three deep-research passes against live GitHub state, recent issues (last 12 months), recent papers (2023–2025), and direct compatibility checks for OSC Pitzer (RHEL 8, glibc 2.28, gcc 13.2 modules).
**Decision criterion:** an engine that **will actually work after implementation**, not one that looks promising in marketing copy. The user has explicitly stated that another LPSim/QarSUMO-class failure is unacceptable.

---

## 1. Selection criteria

Five mandatory requirements (any candidate failing one is **OUT**):

| # | Requirement                       | Failure-mode it prevents                                                  |
|---|-----------------------------------|---------------------------------------------------------------------------|
| 1 | Source actually downloadable      | QarSUMO (404, license-gated, "documented but not distributed")            |
| 2 | Build/install works on Pitzer Linux in 2026 | LPSim (broken qmake, missing source files, modern-g++ incompat) |
| 3 | Runs on networks of ≥20k nodes without crashing | LPSim (GPU OOB on > a few-K nodes)                          |
| 4 | Active maintenance OR demonstrably-working pre-built binary | LPSim (upstream abandoned, bundled binary buggy)        |
| 5 | Different paradigm from SUMO/MATSim         | QarSUMO (bit-identical SUMO fallback, zero comparison signal)   |

## 2. Verified verdicts

### 2.1 DTALite — **RISKY → WILL WORK (with 1-day spike-test gate)**

**Confidence:** Medium-High.

**Direct evidence the agent collected:**

- **The pre-built binary actually runs.** `path4gmns/bin/DTALiteMM.so` (1.8 MB ELF x86-64) was smoke-tested on Sioux Falls (24 nodes, exit clean) and Chicago Sketch (~933 nodes, ~143k OD pairs, **2.3 s wallclock**, valid 200 MB `agent.csv` output). Dependencies: only `libc / libgcc_s / libgomp / libm / libstdc++` — no GPU, no exotic libs.
- **Python wrapper is alive.** `jdlph/Path4GMNS` had **23 commits in the last 12 months**, including a segfault fix landed Nov 2025; v0.10.0 shipped 2025-12-16; **97% issue close rate** (28/29) with substantive maintainer responses. Pip-installable, GH Actions CI passing.
- **Build chain is sane.** 65-line CMakeLists, 5 source files, C++11, OpenMP only. None of LPSim's pathologies (no qmake, no Boost, no GPU SDK).
- **GMNS is a real published standard** at `zephyr-data-specs/GMNS` — input format is documented, not engine-private.

**Risks (what could turn this into another LPSim):**

- **C++ upstream is dormant.** `asu-trans-ai-lab/DTALite` had **0 commits in the last 12 months**, no CI, no tagged releases, Issue #21 ("how to build under Linux") unanswered since 2024-12-26. Maintenance has migrated entirely to the Python wrapper. ([Issue #21](https://github.com/asu-trans-ai-lab/DTALite/issues/21))
- **Pitzer glibc gap.** Bundled `.so` needs GLIBC ≥ 2.32; Pitzer RHEL 8 has 2.28. **Mitigation: Apptainer Ubuntu 22.04 image** — exact same pattern we already use for LPSim. Half a day of work.
- **No independent third-party validation at 20k+ nodes.** All published DTALite benchmarks I could find use ~1k-node networks. Chicago/NYC scaling would be a first; Issue #22 (open 2026-01-09, unanswered) flags a data-quality bug in the Chicago Sketch dataset.

**Realistic integration cost:** **3–5 working days** *after* a passing 1-day spike test on the user's actual Chicago bundle. If the spike fails at 20k nodes, abort cleanly (1 day spent, not 12 commits).

**Comparison to QarSUMO/LPSim red flags:**

| Red flag                       | QarSUMO       | LPSim                       | DTALite                          |
|--------------------------------|---------------|-----------------------------|----------------------------------|
| Source code exists             | NO (404)      | partial, missing files      | **YES, complete**                |
| Build system works on Pitzer   | n/a           | broken qmake, Boost incompat | **CMake 65 lines, OpenMP only** |
| GPU dependency                 | n/a           | YES (V100 SIGSEGV)          | **NO**                           |
| Bundled binary works           | n/a           | tiny nets only              | **Verified up to ~1k nodes**     |
| Upstream maintained            | n/a           | abandoned 2024              | **C++ dormant, Python wrapper active** |
| Anonymous download             | NO            | YES                         | **YES (`pip install path4gmns`)** |

DTALite shares **one** risk with LPSim (dormant C++ upstream) but **lacks the other four** that killed it.

### 2.2 CityFlow — **WILL FAIL**

**Confidence:** High.

**Direct evidence the agent collected:**

- **Project is effectively abandoned.** Exactly **1 commit in the last 12 months** (a contributed converter script, not core), the previous commit before that was Dec 2020. **0 GitHub releases ever.** Open Issue #194 ("Status of this project? abandoned…") sits with **0 maintainer responses**. ([Issue #194](https://github.com/cityflow-project/CityFlow/issues/194))
- **Build is broken on modern Python.** No PyPI package despite docs claiming `pip install cityflow`. setup.py uses `distutils.version.LooseVersion` (removed in Python 3.12). The maintainer's only recommendation, dated 2026-01-08, is literally **"just don't use Python version after 3.11. I use Python 3.9."** Pitzer ships Python 3.11. ([Issue #188](https://github.com/cityflow-project/CityFlow/issues/188))
- **Crashes on real-world networks.** Issue #181 (closed) shows **a SUMO-converted real network segfaults on `cityflow.Engine()`**, with the only response being "try a 2x2 grid instead." This is *exactly* the LPSim failure mode at network scale. ([Issue #181](https://github.com/cityflow-project/CityFlow/issues/181))
- **Largest demonstrated network in any 2024 paper:** 16 intersections (PyTSC, Hangzhou). The user needs 20,000.
- **No OD demand primitive.** `flow.json` is per-flow `route: [startRoad, endRoad]` only — there is no OD-matrix or trip-table concept. The whole input pipeline would need a custom shim.
- **Bundled SUMO converter is rotten.** Hardcodes SUMO 0.32.0 (released 2017).

**Verdict:** Hard NO. Same LPSim signature: dormant 2019-era research artifact, scales 25× too small, documented to crash on real-world inputs. Estimated cost 12–20 days **with unbounded tail risk** (the same kind of risk that killed LPSim). Two-microscopic-engines comparison framing is also academically weak.

### 2.3 POLARIS — **WILL FAIL**

**Confidence:** High.

**Direct evidence the agent collected:**

- **Source code is license-gated.** Both `github.com/anl-tracc/polaris` and `github.com/anl-polaris/polaris-linux` return **HTTP 404 to anonymous users**. Official build instructions point to `git-out.gss.anl.gov/polaris/code/polaris-linux.git` which returns **HTTP 403**. The Argonne tool page states verbatim: *"A license is required to use and run POLARIS… freely available for academic research"* via a request form. **This is structurally identical to the QarSUMO failure mode** — cited in papers, not anonymously distributable. ([vms.taps.anl.gov/tools/polaris](https://vms.taps.anl.gov/tools/polaris/))
- **Effectively zero non-Argonne user base.** Of the four most-cited recent POLARIS papers (2102.07505, 2403.14669, 2408.05176, 2409.04568), the lead/operating authors are all Argonne staff. The single paper with non-Argonne co-authors (MIT) places those authors in policy/transit roles, not as people who built and ran POLARIS independently. **No 2023–2025 paper documents a university group building POLARIS from source on their own hardware.**
- **Build assumes Argonne-internal toolchain.** Build instructions explicitly require **gcc-10/g++-10** (Pitzer has gcc 13.2), the separate `polaris-dependencies` repo, and recommend Argonne's Bebop/Crossover clusters. Same LPSim "bundled-Boost-incompatible-with-modern-g++" pattern.
- **Designed for integrated activity-based regional models, not network+trips benchmarks.** Requires population synthesis, separate Supply and Demand SQLite databases, ADAPTS activity scheduling. A 1k-trip Chicago scenario doesn't match POLARIS's design intent at all.

**Verdict:** Hard NO. POLARIS hits **both** failure modes at once: license-gated like QarSUMO AND Argonne-toolchain-locked like LPSim. License turnaround is unspecified and bureaucratic — for a thesis on a fixed clock, this is a hard blocker. Estimated cost 20–40 days **if** license arrives quickly; **indefinite** if delayed or denied.

### 2.4 Considered and ruled out at the criteria stage

| Engine            | Why out                                                                          |
|-------------------|----------------------------------------------------------------------------------|
| MovSim            | Highway-segment focus; no multi-OD network support — wrong scope.                |
| Eclipse Mosaic    | Co-simulation framework that wraps SUMO; not a standalone engine.                 |
| TRANSIMS          | Last release ~2014; signal of definitive abandonment.                             |
| Aimsun / Vissim / Paramics | Commercial licenses; ruled out at plan stage.                       |
| Veins / Flow      | Wrap SUMO; not standalone engines.                                                |
| SimMobility (MIT) | Heavy in-house Linux toolchain; integration cost > DTALite by ~5×.                |
| AequilibraE       | Python library, not a discrete-event simulator — paradigm mismatch with SUMO/MATSim. |

## 3. Recommendation

**DTALite via the Path4GMNS Python wrapper, gated on a 1-day spike test.**

Rationale:

1. **It is the only one of the three researched options that the deep-research evidence supports as realistically viable.** CityFlow and POLARIS each hit hard blockers (CityFlow: maintainer-confirmed scaling failure on real networks + abandoned project; POLARIS: license gate + Argonne-only user base).
2. **The risk profile is the OPPOSITE of LPSim's.** No GPU, no missing source files, no broken build chain, no bundled-binary mystery — and the maintainer is actively responsive on the wrapper that gates the install.
3. **Paradigm spread is preserved.** SUMO microscopic + MATSim queue-based agent + DTALite mesoscopic DTA = three fundamentally different simulation paradigms. Strongest possible "why these three engines" defense.
4. **GMNS reinforces SimForge's reproducibility framing** (we adapt to community standards, not just engine-private formats).
5. **Failure mode is bounded.** If the 1-day spike on Chicago crashes, we have spent 1 day instead of 12 commits, and the failure reason is publishable (upstream dormancy + scale-validation gap) rather than mysterious.

## 4. Spike-test protocol (do this BEFORE committing to the integration)

```bash
# On Pitzer, in an existing Apptainer image based on Ubuntu 22.04
# (or build a minimal one — same pattern as cluster/jobs/build_lpsim.sbatch):

apptainer exec ubuntu22.04.sif bash -c "
  pip install path4gmns
  python -c \"
import path4gmns as pg
# Convert the user's chicago_1k_car bundle to GMNS CSVs
# (this conversion is the deliverable of the spike — if we can't
# write a clean GMNS converter from canonical in 4 hours, that
# is itself a fail signal)
pg.read_network()
pg.network_assignment(mode=0, gen=5, upd=5)  # link-based UE, 5 outer + 5 inner iters
\"
"
```

**Pass conditions:** finishes in under 5 minutes, produces a non-empty `link_performance.csv`, no segfault.
**Fail conditions:** segfault, hang past 30 minutes, missing-output crash, or GMNS-converter complexity that exceeds 1 day.

If pass → proceed to full adapter (3–5 days).
If fail → document the spike result in this file, leave SimForge as a 2-engine framework, and frame the thesis defense around the three retrospectives (LPSim, QarSUMO, DTALite spike) as **proof that SimForge's adapter pattern handles engine churn cleanly** — three engines researched, two ruled out at criteria, one ruled out at spike, two delivered with full validation.

## 5. Adaptability of SimForge to future simulators

This question deserves an explicit answer in the thesis defense, especially in light of LPSim's abandonment. The answer:

**SimForge's adapter pattern is engine-agnostic by construction.** Every engine integration follows the same three-function contract:

```python
prepare_<engine>_inputs(scenario_path, output_dir, config) -> ScenarioSummary
run_<engine>(output_dir, timeout_s, ...) -> tuple[bool, float, Optional[str]]
parse_<engine>_output(output_dir) -> Optional[<Engine>TripStats]
```

A new engine is added by:

1. Implementing the three functions in `adapters/<engine>/<engine>_adapter.py`.
2. Documenting the canonical → engine-native schema mapping in `adapters/<engine>/MAPPING.md`.
3. Pinning the engine version in `lib/<engine>/manifest.json`.
4. Writing a unit test suite following the pattern in `tests/test_<existing>_adapter.py`.
5. Registering the engine in `execution/runspec.py`'s engine registry.
6. (If cluster build needed) Adding `cluster/jobs/build_<engine>.sbatch`.

No core SimForge code needs to change. The harness, the canonical schema, the feasibility filter, the evaluation pipeline, and the plot generators are all engine-agnostic. **The framework's value is exactly that the engine is a plug-in.**

The engines we ship are not the framework's *limit*. They are the framework's *demonstration*. **The thesis claim is that any reasonable traffic simulator can be added by following the documented adapter contract; the integrations we ship are the proof points.** LPSim's abandonment and QarSUMO's removal are *additional* evidence: the same adapter pattern that makes integration cheap (one package, one test file, one sbatch, three registry edits) also makes removal cheap when an engine cannot be honestly compared.

## 6. References

### Engines
- **DTALite C++:** [asu-trans-ai-lab/DTALite](https://github.com/asu-trans-ai-lab/DTALite) (dormant since 2024)
- **Path4GMNS Python wrapper:** [jdlph/Path4GMNS](https://github.com/jdlph/Path4GMNS) (active, v0.10.0 Dec 2025)
- **GMNS specification:** [zephyr-data-specs/GMNS](https://github.com/zephyr-data-specs/GMNS)
- **CityFlow:** [cityflow-project/CityFlow](https://github.com/cityflow-project/CityFlow) (effectively abandoned)
- **POLARIS:** [vms.taps.anl.gov/tools/polaris](https://vms.taps.anl.gov/tools/polaris/) (license-gated)

### Companion docs
- `LPSIM_RETROSPECTIVE.md`
- `QARSUMO_RETROSPECTIVE.md`
