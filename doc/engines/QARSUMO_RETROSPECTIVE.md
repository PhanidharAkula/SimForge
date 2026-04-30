# QarSUMO Integration — Retrospective

**Status:** Adapter scaffolded in Versions 1–3; engine **dropped entirely** in Version_4 Phase A (2026-04-26).
**Decision date:** 2026-04-26.
**Code retained:** Historical references only. The `adapters/qarsumo/` package, `tests/test_qarsumo_adapter.py`, `cluster/jobs/build_qarsumo.sbatch`, and all runspec entries were removed at commit `7fdc0e3`. Mentions remain in `doc/STRESS_TEST_AUDIT.md` (snapshot doc) and `doc/GLOSSARY.md` (with explicit superseded notes).

---

## 1. Why QarSUMO was chosen

The original thesis plan listed QarSUMO as one of five primary engines, motivated by the same goal LPSim later inherited: **a GPU-accelerated comparator** to put SUMO and MATSim's CPU-based numbers in context.

QarSUMO's claimed advantages:

1. **SUMO API compatibility** — a parallel re-implementation of SUMO's mesoscopic kernel meant the adapter could share input format with the SUMO adapter (low integration cost).
2. **GPU acceleration** — listed in the plan as the GPU comparator.
3. **Academic provenance** — referenced in the Boulmakoul 2023 IEEE HPCS paper cited in the plan.

## 2. What was built

A complete adapter scaffold reached Version_3:

- `adapters/qarsumo/` package with the same input/output contract shape as the SUMO adapter (since QarSUMO consumes SUMO's `.sumocfg` directly).
- `tests/test_qarsumo_adapter.py` — 10 unit tests, all passing on the adapter scaffold.
- `cluster/jobs/build_qarsumo.sbatch` — Pitzer GPU build job.
- 9 runspec entries across `runspecs/benchmark_small.yaml`, `runspecs/benchmark_small.yaml`, `runspecs/benchmark_large.yaml`.
- Engine registry membership in `execution/runspec.py`, `execution/run_benchmark.py`, `run.py`, and the evaluation pipeline.
- Plot/analyze tuples in `evaluation/generate_plots.py`, `evaluation/analyze_benchmark.py`, `evaluation/compare_modes.py`.

## 3. What failed

The 2026-04-26 source-availability audit found **no usable public source** for QarSUMO:

| Source                              | Status                                                                                |
|-------------------------------------|---------------------------------------------------------------------------------------|
| `LLNL/QarSUMO`                      | **404 Not Found**. The repo cited in early SimForge planning no longer resolves.       |
| `QarSUMO/QarSUMO`                   | **Empty placeholder repo**. No source files, no commits beyond an initial README.      |
| Boulmakoul 2023 (IEEE HPCS paper)   | **Cited but no code released**. The paper describes the architecture but the implementation was never made publicly available. |

In the absence of any working QarSUMO binary, the Version_3 SimForge harness ran a **CPU-fallback path** that invoked standard SUMO meso under the QarSUMO label. This was disclosed in plot footnotes and the methods chapter (`doc/STRESS_TEST_AUDIT.md` §5 "QarSUMO CPU-fallback disclosure"), but the audit identified it as a structural problem:

> **The QarSUMO column in every results table was bit-identical to the SUMO meso column.** It contributed zero new comparison signal, occupied 1/5 of the experimental matrix, and risked misleading readers who trusted the column heading.

## 4. Why the drop decision

Three factors converged at the Version_4 Phase A audit:

1. **No upstream to integrate against.** Without source code, "the QarSUMO adapter" could only ever be an alias for SUMO. There was no engineering work that could change that — the failure was upstream, not in SimForge.
2. **Bit-identical fallback inflated the engine count without adding information.** The whole point of cross-engine benchmarking is to compare *different* engines. A column that mirrors another column is worse than no column — it implies validation where none exists.
3. **Advisor agreement.** The Version_4 scope was renegotiated to **three primary engines** (SUMO, MATSim, LPSim), with POLARIS and QarSUMO as documented backups. QarSUMO failed the "documented backup" test too — there is no backup to document, only an absence.

## 5. What was removed (audit trail)

Commit `7fdc0e3` (Version_4 Phase A) made the cleanup atomic:

- **Adapter package:** `adapters/qarsumo/` (package + `MAPPING.md`)
- **Test suite:** `tests/test_qarsumo_adapter.py` (10 tests)
- **Cluster job:** `cluster/jobs/build_qarsumo.sbatch`
- **Runspecs:** 9 `qarsumo` entries across `stress_test.yaml`, `benchmark_small.yaml`, `benchmark_large.yaml`
- **Engine registries:** `execution/runspec.py`, `execution/run_benchmark.py`, `run.py`
- **Evaluation tuples:** `evaluation/generate_plots.py`, `evaluation/analyze_benchmark.py`, `evaluation/compare_modes.py`
- **Cluster job partitions:** `benchmark_small.sbatch` and `benchmark_large.sbatch` switched off `--partition=gpu` (no current engine needed CUDA after the drop; LPSim was queued to put it back, but see `LPSIM_RETROSPECTIVE.md`)

Historical references intentionally **kept** for traceability:

- `doc/STRESS_TEST_AUDIT.md` — Version_3 audit snapshot, with a "**Superseded by Version_4**" header at the top.
- `doc/GLOSSARY.md` "QarSUMO" entry — explicitly explains the drop with citation to this retrospective.
- `CHANGELOG.md` entry for `[Version_4]` Phase A documenting the removal.

## 6. What this proves about SimForge

The QarSUMO drop is a **textbook case for the framework's selection discipline**:

- An engine slot in a benchmarking matrix is valuable only if it produces *independent* signal. Bit-identical fallback fails that test, no matter how prestigious the upstream paper.
- Reproducibility infrastructure must enforce honesty: when source is unavailable, the right answer is to remove the engine and document why, not to silently substitute.
- The `adapters/` directory pattern made the removal cheap (one package, one test file, one sbatch, three registry edits) — the same pattern that makes adding new engines cheap also makes removing dead ones cheap.

In thesis terms: **the framework's value includes telling the user when an engine cannot be honestly compared.** The QarSUMO drop is evidence of that discipline being exercised, not of project failure.

## 7. References

- **Drop commit:** `7fdc0e3` (Version_4 Phase A).
- **CHANGELOG entry:** `CHANGELOG.md` `[Version_4]` Phase A.
- **Methods chapter:** `doc/chapters/methods.md` §3 "Engine selection scope deviation" callout box.
- **Audit snapshot:** `doc/STRESS_TEST_AUDIT.md` (with superseded notice).
- **Glossary:** `doc/GLOSSARY.md` "QarSUMO" entry.
- **Source availability audit:** `todo.md` Version_4 gap-audit table (row 24).
