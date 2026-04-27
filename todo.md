# SimForge — Version_4 Roadmap

Working tracker for plan-alignment work on the `Version_4` branch.
Cross-references `a personal PDF` (Dec 2025) so the canonical source
of truth is always the plan text, not this file.

---

## 1. Plan vs reality — gap audit (snapshot 2026-04-26)

Every commitment from the plan, mapped to current code state.

### 1.1 Engines (plan §1.10 Objective 1, §3.1, §4.1 Experimental Matrix)

The plan explicitly lists **five engines**: SUMO, MATSim, POLARIS, LPSim,
QarSUMO. Per advisor agreement, we treat SUMO + MATSim + LPSim as the three
primary engines and POLARIS + QarSUMO as documented backups.

| Engine | Plan status | Code state | Plan |
|--------|-----------------|------------|------|
| SUMO | Primary | ✅ adapter implemented and working (`adapters/sumo/`) | Keep |
| MATSim | Primary | ✅ adapter implemented and working (`adapters/matsim/`) | Keep |
| **LPSim** | Primary (with QarSUMO as the GPU comparator originally) | ✅ adapter implemented (`adapters/lpsim/`, Phase B) — needs Pitzer GPU build to actually run | Keep |
| POLARIS | Primary | ❌ no adapter | Drop to backup (per advisor scope) — document in thesis as deferred |
| QarSUMO | Primary in plan, GPU variant | Adapter scaffold exists; **no usable public source** (LLNL/QarSUMO 404, QarSUMO/QarSUMO is empty placeholder, Boulmakoul 2023 paper cited in plan needs re-verification) | **Drop entirely** in Version_4 |

### 1.2 Cities and loads (plan §1.13, §3.3, §4.1)

| Commitment | Reality | Status |
|------------|---------|--------|
| 3 cities (Chicago, NYC, LA) | ✅ all three supported, PBFs hash-pinned in `osm_data/manifest.json` | aligned |
| 3 loads (50K, 500K, 5M) | We have 1K, 10K, 50K, 200K, 500K. **5M not implementable** because of the BFS pre-routing bottleneck in the SUMO adapter (~17h per engine/seed at 200K already). | Per advisor: cap at 500K; document 5M as future work tied to route caching |

### 1.3 Hardware tiers (plan §4.1)

| Commitment | Reality | Status |
|------------|---------|--------|
| 2 hardware tiers (CPU reference + GPU/HPC) | Pitzer cpu and gpu partitions both available; LPSim needs GPU, SUMO/MATSim CPU | aligned (once LPSim lands) |

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
| **OCI/Singularity containers with pinned digest** | ❌ venv only (Python deps frozen via `requirements.lock`, system libs not frozen) | **Implement** after LPSim |
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
| Number of engines actually run | 5 | **3 primary** (SUMO ✅, MATSim ✅, LPSim ✅ Phase B) |
| Backup engines | — | **2 documented** (POLARIS, QarSUMO) — both deferred / unavailable; documented in methods |
| Max scenario load | 5M trips | **500K trips** (5M deferred to future work pending route-cache fix) |
| Repeats N | 10 | **5 across the matrix** (Version_4, advisor-approved). Revisit N=10 once Pitzer wall is measured |
| Hardware tiers | 2 (CPU + GPU/HPC) | 2 (Pitzer cpu + gpu partitions) — aligned |

---

## 3. Roadmap (Version_4)

Ordered. Each item is one commit (or a small batch).

### Phase A — Foundation (this branch, in order)

1. ✅ **Create `Version_4` branch**
2. ✅ **Write `todo.md`** ← this file
3. ✅ **Drop QarSUMO completely** — adapter package removed, `tests/test_qarsumo_adapter.py` removed, `cluster/jobs/build_qarsumo.sbatch` removed, all 9 qarsumo runspec entries removed across `stress_test.yaml` / `benchmark_small.yaml` / `benchmark_large.yaml`, sbatches switched off the GPU partition, engine registries pruned in `execution/runspec.py` / `execution/run_benchmark.py` / `run.py` / `evaluation/`, all docs updated (CHANGELOG, README, SETUP, TESTING, CONTRIBUTING, doc/*, doc/chapters/*). Historical references kept in `doc/STRESS_TEST_AUDIT.md` (snapshot doc) and `doc/GLOSSARY.md` (explains the drop).
4. ✅ **Implement 95% CIs** — `evaluation/metrics/confidence.py` (Student's t with hard-coded table, no scipy dep), `tests/test_confidence.py` (11 tests), wired into `evaluation/analyze_benchmark.py` (Table 5.1, Table 5.2, LaTeX, Markdown all carry the new `95% CI` column / `± half-width` notation) and `evaluation/generate_plots.py` (Figs 5.1, 5.3, 5.6 error bars are now 95 % CIs instead of ± 1σ).

> Pause here and talk to advisor about: (a) calibration scope, (b) per-watt scope, (c) target N for repeats.

### Phase B — LPSim as the 3rd primary engine (✅ landed in Version_4)

5. ✅ **`cluster/jobs/build_lpsim.sbatch`** — Pitzer GPU job that prefers `singularity pull docker://yibo123/lpsim:cuda12.4` and falls back to `git clone Xuan-1998/LPSim && make` under `LivingCity/`. Output symlinked to `$HOME/lpsim/LivingCity/LivingCity` (or `$HOME/lpsim/lpsim.sif` for the Singularity path).
6. ✅ **`adapters/lpsim/`** — full package: adapter, CLI, MAPPING.md, `__init__.py`
   - `prepare_lpsim_inputs(scenario_path, output_dir, config)` writes LPSim's `nodes.csv` (osmid, x, y, highway, index), `edges.csv` (uniqueid, u, v, length, lanes, speed_mph), `od_demand.csv` (PERNO, origin, destination), and `command_line_options.ini` ([General] section with START_HR/END_HR derived from canonical config)
   - `run_lpsim(output_dir, timeout_s, use_singularity)` invokes `LivingCity` (native or via `singularity exec --nv … LivingCity`) with CWD set to the prepared run dir
   - `parse_lpsim_output(output_dir)` reads `<NUM_PASSES>_people*.csv` → `LPSimTripStats(trip_count, completed_count, mean_travel_time_s, p95_travel_time_s, mean_distance_m)`
   - **No silent CPU fallback** — when no GPU binary is staged, `run_lpsim` returns a clean failure with a build pointer
7. ✅ **`tests/test_lpsim_adapter.py`** (39 tests) — helpers, all 4 writers, determinism (byte-identical re-runs), end-to-end input prep on chicago_1k_car, output parsing on synthetic fixtures, binary discovery
8. ✅ **Runspec entries** — `engine: lpsim` rows in `stress_test.yaml`, `benchmark_small.yaml`, `benchmark_large.yaml` (12 LPSim cells across the matrix; 60 invocations at N=5)
9. ✅ **Sbatches flipped back to GPU** — `benchmark_small.sbatch` and `benchmark_large.sbatch` now request `--partition=gpu --gres=gpu:v100:1`; SUMO + MATSim share the same node and don't touch the GPU

### Phase C — Containerization (~2-3 days)

10. **Write `Dockerfile`** — Python 3.13.13 + uv + `requirements.lock` + SUMO + Java 17 + MATSim JAR + LPSim binary (or use LPSim's Docker base)
11. **Build + push to a registry** (Docker Hub or GitHub Container Registry), capture pinned digest
12. **Update sbatches** to use `singularity exec docker://simforge@sha256:<digest> python -m execution.run_benchmark ...`
13. **Update `doc/REPRODUCING.md`** — pinned digest becomes part of the canonical "how to reproduce" recipe

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
- LPSim: [Xuan-1998/LPSim](https://github.com/Xuan-1998/LPSim) (MIT, Docker shipped at `yibo123/lpsim:cuda12.4`)
- POLARIS: [anl-tracc/polaris](https://github.com/anl-tracc/polaris) (open source, Argonne)
- QarSUMO: no usable public source as of this audit
