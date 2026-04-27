# Third-Engine Selection — Options & Recommendation

**Status:** Decision pending (advisor approval).
**Context:** LPSim integration was abandoned 2026-04-27 (see `LPSIM_RETROSPECTIVE.md`). SimForge's three-engine matrix needs a working third engine to maintain the cross-simulator benchmarking premise.
**Decision criterion:** an engine that (1) runs reproducibly on Pitzer with bounded build risk, (2) adds a different simulation paradigm to SUMO + MATSim rather than overlapping with one of them, and (3) is academically defensible for a thesis on reproducibility.

---

## 1. Selection criteria

Five mandatory requirements (any candidate failing one is out):

| # | Requirement                | Failure-mode it prevents                                                     |
|---|----------------------------|------------------------------------------------------------------------------|
| 1 | Runs on Linux, no GPU      | Repeats the LPSim CUDA toolchain hell                                        |
| 2 | Open source, active        | Repeats the QarSUMO "no usable source" trap                                  |
| 3 | Pre-built binary OR clean build | Bounded integration cost                                                |
| 4 | Different paradigm from SUMO/MATSim | Avoids "QarSUMO bit-identical fallback" critique                    |
| 5 | Documented input/output    | Adapter is writable in days, not months                                      |

Three nice-to-haves (defense weight, not gating):

- Used in cited academic work
- Consumes an open data standard rather than an engine-private format
- Has a Python wrapper / scripting interface

## 2. Candidates evaluated

### 2.1 DTALite (RECOMMENDED)

**What it is:** A C++ open-source mesoscopic Dynamic Traffic Assignment (DTA) engine, built around the GMNS (General Modeling Network Specification) open data standard. Originally developed at the University of Washington, now maintained by the ASU Trans+AI Lab and a broader academic consortium.

| Criterion             | Evidence                                                                                       |
|-----------------------|------------------------------------------------------------------------------------------------|
| Runs on Linux, no GPU | Yes — single static C++ executable; pre-built linux-x64 binary on GitHub Releases.             |
| Open source, active   | Apache 2.0; recent commits within the last 12 months on `asu-trans-ai-lab/DTALite`.            |
| Build complexity      | None for the binary; ~30 s for a from-source build (CMake, no exotic deps).                    |
| Paradigm              | **Mesoscopic DTA / equilibrium-seeking** — distinct from SUMO (microscopic time-stepping) and MATSim (queue-based agent plan/replan). |
| I/O format            | GMNS: `node.csv`, `link.csv`, `demand.csv`. Output: CSV link performance + agent path files.   |
| Citations             | Used in 100+ papers; GMNS is referenced in USDOT/SHRP2 documentation.                          |
| Python wrapper        | [`path4gmns`](https://github.com/jdlph/Path4GMNS) — pip-installable, mature.                   |

**Why this is the strongest candidate:**

1. **Paradigm spread.** SimForge gains a clean three-paradigm matrix:
   - SUMO — microscopic, time-stepping, car-following
   - MATSim — mesoscopic, queue-based, agent plan/replan
   - DTALite — mesoscopic, DTA, equilibrium

   This is the strongest possible answer to "why these three engines" — they cover three fundamentally different ways to simulate the same demand, so cross-engine agreement (or disagreement) carries information.

2. **Reproducibility framing.** GMNS is an *open published data standard*, not an engine-private format. Using a GMNS-consuming engine reinforces SimForge's reproducibility thesis: we adapt to both engine-native formats (SUMO XML, MATSim XML) AND community standards (GMNS). The framework demonstrably handles both worlds.

3. **Bounded risk.** Pre-built binary exists. Format is documented. Engine is deterministic. Last LPSim-style "failure mode" we'd face is a column-name mismatch, fixable in a single commit.

**Estimated integration cost:** 3–5 working days for a complete adapter (writers, MAPPING.md, ~30 unit tests, manifest, smoke sbatch). Bounded by the adapter pattern we've now demonstrated three times.

### 2.2 CityFlow

**What it is:** A microscopic traffic simulator from SJTU/Penn State, designed for reinforcement-learning research on traffic signal control. JSON-based I/O, C++ core with Python bindings.

| Criterion             | Evidence                                                                          |
|-----------------------|-----------------------------------------------------------------------------------|
| Runs on Linux, no GPU | Yes — pure CPU, pip-installable.                                                  |
| Open source, active   | Apache 2.0; semi-active (last commit 2023).                                       |
| Build complexity      | None — `pip install cityflow`.                                                    |
| Paradigm              | **Microscopic** — overlaps with SUMO. Weakens the "three paradigms" story.        |
| I/O format            | JSON network + JSON flow + Python API.                                            |
| Citations             | IJCAI 2019 RL benchmark paper (~500+ citations).                                  |
| Python wrapper        | First-class — Python is the primary interface.                                    |

**Why it's the second-best option:** Easiest possible integration (one `pip install`), strong RL-community citations, fast and deterministic. **Why it's not first:** the microscopic-microscopic overlap with SUMO. We could frame it as "we picked CityFlow specifically to compare two microscopic engines and see whether the SUMO microscopic results generalise" — defensible but weaker than DTALite's paradigm spread.

### 2.3 POLARIS

**What it is:** Argonne National Laboratory's agent-based regional travel simulator. Already listed as a "documented backup" in `todo.md`.

| Criterion             | Evidence                                                                              |
|-----------------------|---------------------------------------------------------------------------------------|
| Runs on Linux, no GPU | Yes.                                                                                  |
| Open source, active   | Custom license (research-permissive); active.                                         |
| Build complexity      | **High** — CMake, several deps, designed for full regional models.                    |
| Paradigm              | **Agent-based with activity scheduling** — overlaps somewhat with MATSim.             |
| I/O format            | SQLite-based scenario, custom CSV outputs.                                            |
| Citations             | Strong (Argonne research output).                                                     |
| Python wrapper        | Partial.                                                                              |

**Why it's third:** Build complexity reintroduces the LPSim risk (an academic codebase with a non-trivial CMake graph and Argonne-internal toolchain assumptions). Paradigm overlap with MATSim is moderate. Defensible but riskier.

### 2.4 Considered and ruled out

| Engine     | Why out                                                                                     |
|------------|---------------------------------------------------------------------------------------------|
| MovSim     | Highway/single-link focus; limited multi-OD network support — wrong scope.                  |
| Eclipse Mosaic | Co-simulation framework that wraps SUMO, not a standalone engine.                       |
| TRANSIMS   | Dead since ~2014; bad signal for a 2026 thesis.                                             |
| Aimsun     | Commercial license; ruled out at plan stage.                                            |
| Veins      | VANET wrapper around SUMO + OMNeT++, not standalone.                                        |
| SimMobility (MIT/SMART) | Heavy MIT-only Linux toolchain dependencies; integration cost exceeds DTALite by 5×. |
| Flow       | RL training framework on top of SUMO; not a separate engine.                                |

## 3. Recommendation

**DTALite.** Three reasons in priority order:

1. **Paradigm spread is the strongest defense of "why these three engines."** Microscopic + agent-based + DTA covers the three dominant simulation paradigms in the literature.
2. **GMNS reinforces the reproducibility thesis** by demonstrating SimForge adapts to community standards, not just engine-private formats.
3. **Bounded integration cost** — pre-built binary, documented format, active maintenance, no GPU. The risk profile is the opposite of LPSim's.

If risk-aversion outweighs paradigm-spread (e.g., if the thesis defense window is tight), CityFlow is the safer fallback at the cost of weakening the "different paradigms" story.

## 4. Adaptability of SimForge to future simulators

This question deserves an explicit answer in the thesis defense, because both LPSim's abandonment and the pending third-engine choice make it salient. The answer:

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

No core SimForge code needs to change. The harness, the canonical schema, the feasibility filter, the evaluation pipeline, the plot generators — all are engine-agnostic. **The framework's value is exactly that the engine is a plug-in.**

The three engines we will ship — SUMO, MATSim, and (pending decision) DTALite or CityFlow — are not the framework's *limit*. They are the framework's *demonstration*. The thesis claim is that any reasonable traffic simulator can be added by following the documented adapter contract; the three integrations are the proof points.

LPSim's abandonment is *additional* evidence: when an engine cannot be made to work, the same adapter pattern that makes integration cheap also makes removal cheap (one package, one test file, one sbatch, three registry edits — see `QARSUMO_RETROSPECTIVE.md` §5 for the QarSUMO removal audit trail).

## 5. References

- **DTALite:** [asu-trans-ai-lab/DTALite](https://github.com/asu-trans-ai-lab/DTALite)
- **GMNS specification:** [zephyr-data-specs/GMNS](https://github.com/zephyr-data-specs/GMNS)
- **path4gmns:** [jdlph/Path4GMNS](https://github.com/jdlph/Path4GMNS)
- **CityFlow:** [cityflow-project/CityFlow](https://github.com/cityflow-project/CityFlow)
- **POLARIS:** [anl-tracc/polaris](https://github.com/anl-tracc/polaris)
- **Companion retrospectives:** `LPSIM_RETROSPECTIVE.md`, `QARSUMO_RETROSPECTIVE.md`
