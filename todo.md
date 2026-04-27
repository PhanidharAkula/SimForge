# SimForge — Version_4 Roadmap

Working tracker for plan-alignment work on the `Version_4` branch.
Cross-references `a personal PDF` (Dec 2025) so the canonical source
of truth is always the plan text, not this file.

---

## 1. Plan vs reality — gap audit (snapshot 2026-04-26)

Every commitment from the plan, mapped to current code state.

### 1.1 Engines (plan §1.10 Objective 1, §3.1, §4.1 Experimental Matrix)

The plan explicitly lists **five engines**: SUMO, MATSim, POLARIS, LPSim,
QarSUMO. After two integration cycles (Versions 4–5), the matrix narrows to
**three primary engines** chosen for paradigm spread: SUMO microscopic +
mesoscopic, MATSim queue-based agent simulation, and DTALite mesoscopic
Dynamic Traffic Assignment.

| Engine | Plan status | Code state | Plan |
|--------|-----------------|------------|------|
| SUMO | Primary | ✅ adapter implemented and working (`adapters/sumo/`) | Keep |
| MATSim | Primary | ✅ adapter implemented and working (`adapters/matsim/`) | Keep |
| **DTALite** | New in Version_5 (replaces LPSim slot) | ✅ adapter implemented and working (`adapters/dtalite/`) — runs end-to-end on Mac in ~5 s on chicago_1k_car | Keep |
| ~~LPSim~~ | Was Primary in Version_4 | ❌ Adapter, tests, and build pipeline removed in Version_5; full retrospective in [`doc/engines/LPSIM_RETROSPECTIVE.md`](doc/engines/LPSIM_RETROSPECTIVE.md) | **Dropped** in Version_5 — bundled GPU binary crashed on networks > a few-K nodes; in-container source rebuild SIGSEGV'd at first kernel launch despite sm_70 + Boost 1.59 sed-patches |
| ~~POLARIS~~ | Was a backup | ❌ Evaluated as third-engine alternative in Version_5 and ruled out at criteria (license-gated, Argonne-only user base) | **Documented backup** — see [`doc/engines/THIRD_ENGINE_OPTIONS.md`](doc/engines/THIRD_ENGINE_OPTIONS.md) |
| ~~QarSUMO~~ | Was Primary in plan | ❌ Dropped in Version_4 Phase A — no usable public source | **Dropped** — see [`doc/engines/QARSUMO_RETROSPECTIVE.md`](doc/engines/QARSUMO_RETROSPECTIVE.md) |

### 1.2 Cities and loads (plan §1.13, §3.3, §4.1)

| Commitment | Reality | Status |
|------------|---------|--------|
| 3 cities (Chicago, NYC, LA) | ✅ all three supported, PBFs hash-pinned in `osm_data/manifest.json` | aligned |
| 3 loads (50K, 500K, 5M) | We have 1K, 10K, 50K, 200K, 500K. **5M not implementable** because of the BFS pre-routing bottleneck in the SUMO adapter (~17h per engine/seed at 200K already). | Per advisor: cap at 500K; document 5M as future work tied to route caching |

### 1.3 Hardware tiers (plan §4.1)

| Commitment | Reality | Status |
|------------|---------|--------|
| 2 hardware tiers (CPU reference + GPU/HPC) | Pitzer cpu partition only after LPSim removal in Version_5 (all three primary engines are CPU-only). The "GPU tier" claim from the plan is dropped — see `doc/engines/LPSIM_RETROSPECTIVE.md` | reframed: 2 tiers = laptop (Mac arm64) + cluster (Pitzer cpu) |

### 1.4 Repeats (plan §4.1: N=10)

| Commitment | Reality | Status |
|------------|---------|--------|
| N=10 repeats per (city, load, engine, hardware) | **N=5 across the matrix** (Version_4, advisor-approved fallback). Bumping to 10 stays inside the harness — `repeats:` per cell — but ~doubles wall time. | Run at N=5 first; revisit N=10 once Pitzer wall-time budget is measured |

### 1.5 Reproducibility infrastructure (plan §2.7, §3.2, §4.2)

| Commitment | Reality | Status |
|------------|---------|--------|
| Canonical schema (`network.xml`, `demand.csv`, `signals.xml`, `config.xml`, `manifest.xml`) | ✅ implemented | aligned |
| SHA-256 manifest checksums | ✅ in `manifest.xml` | aligned |
| Fixed seeds, deterministic adapters | ✅ seeds wired through, sorted iteration in adapters | aligned |
| **OCI/Singularity containers with pinned digest** | ❌ venv only (Python deps frozen via `requirements.lock`, system libs not frozen) | **Implement** in Version_5 Phase C |
| Auto re-run on hash mismatch (plan §2.7, §4.4) | ❌ not implemented | Defer; hash mismatch currently surfaces as a test failure |
| Per-bundle `toolchain` block in metadata | ✅ implemented (Version_3 work) | exceeds plan |
| `dest_source` per-trip provenance | ✅ implemented (Version_3 work) | exceeds plan |

### 1.6 Calibration (plan §3.4 Calibration Protocol)

| Commitment | Reality | Status |
|------------|---------|--------|
| Calibration / evaluation window split | ❌ not implemented; no observed-data ingestion | **Discuss with advisor** — costliest item, mostly data acquisition |
| Fixed grid search (3-5 settings per parameter) | ❌ not implemented | Same |
| Per-engine calibrated `config.xml` | ❌ defaults used everywhere | Same |

### 1.7 Evaluation metrics (plan §3.5)

| Commitment | Reality | Status |
|------------|---------|--------|
| Fidelity: RMSE, GEH, KS | ✅ in `evaluation/metrics/fidelity.py` | aligned |
| Scalability: runtime, throughput, vehicles/sec/core | ✅ in `evaluation/metrics/scalability.py` | aligned |
| Reproducibility: R = 1 − σ/μ | ✅ in `evaluation/metrics/reproducibility.py` | aligned |
| **95 % CIs on every KPI** | ✅ implemented (Phase A) — Student's t with hard-coded table, no scipy dep | aligned |
| **Per-watt normalization** (vehicles/sec/watt) | ❌ no power instrumentation | **Discuss with advisor** — defensible to defer |
| 95% CIs in plots and markdown tables | ✅ implemented (Phase A) — `evaluation/metrics/confidence.py`, wired into Tables 5.1/5.2 + LaTeX/Markdown + error bars on Figs 5.1/5.3/5.6 | aligned |

### 1.8 Deliverables (plan §4.6)

| Commitment | Reality | Status |
|------------|---------|--------|
| Open-source SimForge repo | ✅ public on GitHub | aligned |
| Run artifacts per benchmark tuple | ✅ produced (per-seed JSONs + plots) | aligned |
| Reproducibility scorecard | ❌ not produced | Generate from CI output once #1.7 lands |

---

## 2. Scope adjustments approved by advisor

These reduce scope from the written plan; document in the thesis methods chapter as such.

| Item | Plan | Approved scope |
|------|----------|----------------|
| Number of engines actually run | 5 | **3 primary** (SUMO ✅, MATSim ✅, DTALite ✅ Version_5) |
| Engines researched and ruled out | — | **3 documented retrospectives** in [`doc/engines/`](doc/engines/): LPSim (abandoned Version_5 after GPU SIGSEGV), QarSUMO (no usable source), POLARIS + CityFlow (evaluated as third-engine alternatives in Version_5, ruled out at criteria) |
| Max scenario load | 5M trips | **500K trips** (5M deferred to future work pending route-cache fix) |
| Repeats N | 10 | **5 across the matrix** (Version_4, advisor-approved). Revisit N=10 once Pitzer wall is measured |
| Hardware tiers | 2 (CPU + GPU/HPC) | 2 (Mac laptop + Pitzer cpu) — GPU tier dropped after LPSim removal in Version_5 |

---

## 3. Roadmap (Version_4)

Ordered. Each item is one commit (or a small batch).

### Phase A — Foundation (this branch, in order)

1. ✅ **Create `Version_4` branch**
2. ✅ **Write `todo.md`** ← this file
3. ✅ **Drop QarSUMO completely** — adapter package removed, `tests/test_qarsumo_adapter.py` removed, `cluster/jobs/build_qarsumo.sbatch` removed, all 9 qarsumo runspec entries removed across `stress_test.yaml` / `benchmark_small.yaml` / `benchmark_large.yaml`, sbatches switched off the GPU partition, engine registries pruned in `execution/runspec.py` / `execution/run_benchmark.py` / `run.py` / `evaluation/`, all docs updated (CHANGELOG, README, SETUP, TESTING, CONTRIBUTING, doc/*, doc/chapters/*). Historical references kept in `doc/STRESS_TEST_AUDIT.md` (snapshot doc) and `doc/GLOSSARY.md` (explains the drop).
4. ✅ **Implement 95% CIs** — `evaluation/metrics/confidence.py` (Student's t with hard-coded table, no scipy dep), `tests/test_confidence.py` (11 tests), wired into `evaluation/analyze_benchmark.py` (Table 5.1, Table 5.2, LaTeX, Markdown all carry the new `95% CI` column / `± half-width` notation) and `evaluation/generate_plots.py` (Figs 5.1, 5.3, 5.6 error bars are now 95 % CIs instead of ± 1σ).

> Pause here and talk to advisor about: (a) calibration scope, (b) per-watt scope, (c) target N for repeats.

### Phase B — LPSim as the 3rd primary engine (landed in Version_4, ABANDONED in Version_5)

5–9. ⚠️ **Phase B implemented in Version_4 then atomically removed in Version_5 commit `f6b1cdb`.** The bundled LPSim GPU binary (`yibo123/lpsim:cuda12.4`) crashed at `b18CUDA_trafficSimulator.cu:1682` on networks > a few-K nodes; an in-container source rebuild against the V100's sm_70 arch (with Boost 1.59 sed-patches for modern g++) succeeded but the rebuilt binary still SIGSEGV'd at "Starting simulation ...". After 12+ commits across two debugging sessions, the integration was abandoned and the entire Phase B output was removed: `adapters/lpsim/`, `tests/test_lpsim_adapter.py` (39 tests), `lib/lpsim/manifest.json`, `cluster/jobs/build_lpsim.sbatch` + `smoke_lpsim.sbatch` + `diag_lpsim.sbatch`, all `engine: lpsim` runspec entries, engine-registry membership, and doc references. Full retrospective: [`doc/engines/LPSIM_RETROSPECTIVE.md`](doc/engines/LPSIM_RETROSPECTIVE.md).

### Phase B′ — DTALite as the 3rd primary engine (✅ landed in Version_5)

5b. ✅ **`adapters/dtalite/`** — full package: adapter, CLI, MAPPING.md, `__init__.py`
   - `prepare_dtalite_inputs(scenario_path, output_dir, config)` writes GMNS `node.csv` (with demand-driven `zone_id`), `link.csv` (km + km/h units, BPR VDF columns), `demand.csv` (OD-aggregated), `settings.csv` (sections format read by the C++ binary), `settings.yml` (YAML mirror read by the path4gmns wrapper)
   - `run_dtalite(output_dir, timeout_s, iterations, column_updating_iterations)` invokes `path4gmns.DTALiteClassic(1, ...)` (mode 1 = path-based UE) via subprocess
   - `parse_dtalite_output(output_dir)` reads `agent.csv` → `DTALiteTripStats(trip_count, completed_count, mean_travel_time_s, p95_travel_time_s, mean_distance_m)` with volume expansion + minute→second conversion
   - **No silent fallback** — when path4gmns is not installed, `run_dtalite` returns a clean failure with the install command
6b. ✅ **`tests/test_dtalite_adapter.py`** (46 tests) — helpers, all 5 writers, demand-driven zoning, determinism, end-to-end input prep on chicago_1k_car, output parsing on synthetic fixtures, binary discovery, end-to-end smoke test gated on path4gmns availability
7b. ✅ **`lib/dtalite/manifest.json`** — pinned `path4gmns==0.10.0`; re-included via `.gitignore` rule (replaces the LPSim re-include rule)
8b. ✅ **`requirements.txt` + `requirements.lock`** — `path4gmns>=0.10.0,<1` added with macOS `brew install libomp` note
9b. ✅ **Runspec entries** — `engine: dtalite` rows in `stress_test.yaml`, `benchmark_small.yaml`, `benchmark_large.yaml` (12 DTALite cells across the matrix; 60 invocations at N=5)
10b. ✅ **Sbatches flipped back to CPU** — `benchmark_small.sbatch` and `benchmark_large.sbatch` now request `--partition=cpu` (no engine needs CUDA after LPSim removal); `cuda/11.8.0` module load dropped; LPSim binary preflight replaced with python-side `is_dtalite_available()` check

### Phase C — Containerization (~2-3 days)

11. **Write `Dockerfile`** — Python 3.13.13 + uv + `requirements.lock` (pulls `path4gmns` along with everything else) + SUMO + Java 17 + MATSim JAR. No GPU base image needed since the matrix is CPU-only after Version_5.
12. **Build + push to a registry** (Docker Hub or GitHub Container Registry), capture pinned digest
13. **Update sbatches** to use `singularity exec docker://simforge@sha256:<digest> python -m execution.run_benchmark ...`
14. **Update `doc/REPRODUCING.md`** — pinned digest becomes part of the canonical "how to reproduce" recipe

### Phase D — Optional (decide after advisor conversation)

14. **Calibration framework** — observed data ingestion + grid search + cal/eval window split
15. **Per-watt normalization** — `nvidia-smi` polling for GPU runs (skip CPU RAPL — needs root)
16. **Fix BFS routing bottleneck in SUMO adapter** — cache routes per (origin, destination) pair so 200K/500K bundles finish inside Pitzer wall-clock

### Phase E — Final integration

17. **Run full benchmark matrix** (3 cities × 5 loads × 3 engines × N repeats) on Pitzer
18. **Generate thesis figures** from results + `summary.md`
19. **Write up methods chapter** with the explicit scope-deviation notes from §2 above

---

## 4. Open questions for advisor

Pasteable for the next meeting.

1. **Repeats N** — plan commits to N=10 (450 runs total under reduced scope, ~24-40h Pitzer wall). Acceptable to start with N=5 (225 runs, ~12-20h) and document the smaller sample in the methods chapter? Or insist on N=10 even if it means staging across multiple sbatch jobs?
2. **Calibration framework** — plan §3.4 commits to grid search with cal/eval window split using observed link counts. Two sub-questions:
   - Engine-vs-observed fidelity (needs observed data) vs engine-vs-engine fidelity (doesn't): which is required for the thesis?
   - One-city case study (e.g., Chicago only, where data is best) vs all three cities?
3. **Per-watt normalization** — wall-clock + hardware-spec table sufficient, or required to compare CPU vs GPU energy efficiency? If required, GPU-only via `nvidia-smi` is much easier than full CPU RAPL on Pitzer.
4. **POLARIS adapter** — drop entirely as per current advisor agreement, or implement as the 4th engine for stronger thesis story? (`anl-tracc/polaris` is open source.)
5. **5M trip scale** — capped at 500K in current scope due to BFS routing bottleneck. Acceptable to document 5M as future work, or required to be addressed (would need route caching, ~1-2 days of dev)?

---

## 5. References

- `a personal PDF` — root of the repo, December 2025
- `CHANGELOG.md` — running record of code-level changes
- `doc/chapters/methods.md` — current methods chapter draft
- `doc/REPRODUCING.md` — current reproducibility recipe (will need a "containerization" section after Phase C)
- `requirements.lock` — pinned Python deps (current foundation; gets superseded by container digest in Phase C)
- DTALite: bundled inside [`path4gmns`](https://github.com/jdlph/Path4GMNS) (Apache 2.0). DTALite C++ upstream: [`asu-trans-ai-lab/DTALite`](https://github.com/asu-trans-ai-lab/DTALite). Pin in `lib/dtalite/manifest.json`.
- ~~LPSim~~: abandoned Version_5 — see `doc/engines/LPSIM_RETROSPECTIVE.md`
- POLARIS: [anl-tracc/polaris](https://github.com/anl-tracc/polaris) (open source, Argonne)
- QarSUMO: no usable public source as of this audit
