# LPSim Integration Evaluation

**Status:** Adapter implemented and tested; LPSim evaluated as a third-engine candidate and **ruled out** after exhaustive Pitzer debugging.
**Decision date:** 2026-04-27.
**Code disposition:** the `adapters/lpsim/` package, its unit tests, `lib/lpsim/manifest.json`, the build/smoke/diag sbatch jobs, and `adapters/lpsim/MAPPING.md` are not part of the shipped framework once LPSim was ruled out. This evaluation is the surviving record of the integration attempt.

---

## 1. Why LPSim was chosen

LPSim ([Xuan-1998/LPSim](https://github.com/Xuan-1998/LPSim), MIT-licensed) is a GPU-accelerated mesoscopic traffic simulator built on the UC Berkeley B18 traffic-flow model. It was evaluated to fill the **GPU comparator slot** in SimForge's engine matrix after QarSUMO was ruled out at the source-availability stage.

The choice was defensible on five grounds:

1. **Open license**, MIT, no commercial gating.
2. **Pre-built distribution**, the upstream ships a Docker image (`yibo123/lpsim:cuda12.4`) with the binary already compiled, removing the need to build CUDA code from scratch.
3. **Mesoscopic paradigm**, same fidelity tier as MATSim and SUMO meso, making cross-engine comparison meaningful.
4. **Documented input format**, CSV-based (`nodes.csv`, `edges.csv`, `od_demand.csv`) plus a single `command_line_options.ini`. Schema reverse-engineerable from the LivingCity source.
5. **GPU acceleration**, the only one of the three primary engines using CUDA, providing a real performance comparison signal beyond pure scaling.

## 2. What was built

The adapter package is **production-quality and was never the failure point**. It includes:

- **`adapters/lpsim/lpsim_adapter.py`** (~750 lines): canonical → LPSim conversion (`prepare_lpsim_inputs`), engine invocation (`run_lpsim`), and output parsing (`parse_lpsim_output`). Handles three input writers (nodes, edges, demand), the INI emitter, and a robust binary-discovery chain (env var → source build → bundled image → `$PATH`).
- **`tests/test_lpsim_adapter.py`** (45 tests): covers all writers, schema fidelity (LF line endings, `ref` column, `dep_time` column, sequential `uniqueid`), determinism, and output parsing. **All pass on every commit**.
- **`adapters/lpsim/MAPPING.md`** (~280 lines): documents the canonical → LPSim CSV schema mapping with line-level cross-references to the LivingCity source.
- **`lib/lpsim/manifest.json`**, pins the LPSim git SHA (`452067ee...`) and Docker image:tag (`yibo123/lpsim:cuda12.4`) for reproducibility.
- **`cluster/jobs/build_lpsim.sbatch`**, three-mode build pipeline (Singularity image pull, in-container source rebuild, native fallback) with all known patches (Boost 1.59 sed fix for modern g++, CUDA 12.4 path patches, missing-source-file extraction from the SIF, `cuda.depend_command` removal).

The conversion logic, schema mapping, test suite, and build pipeline are **reusable as-is** if LPSim's runtime issues are ever resolved upstream.

## 3. What failed (and where)

The failure was at the **engine runtime layer**, not the adapter or the build. We hit five distinct classes of failure on Pitzer (V100, CUDA 11.8 host / CUDA 12.4 container) and resolved the first four; the fifth was the wall.

### 3.1 Schema mismatches (resolved)

The bundled LivingCity binary has **three different node/edge loaders** (csv.h SP loader, csv.h max-vertex pre-scan, Qt fallback) with overlapping but incompatible column requirements. The strictest (`graph.cc:204`) demands `osmid, x, y, ref, highway, index` with **LF line endings** (csv.h does not strip `\r` from CRLF). Python's csv default is CRLF, which produced `"index\r"` as a column name and the loader threw `missing_column_in_header`.

Fixed across `b060818`, `58df0f7`, `1b075aa`, `560d466`, `466d0a6`:
- LF line endings on all CSVs (`lineterminator="\n"` in `csv.writer`)
- `ref` column added to nodes.csv (empty string, canonical doesn't preserve OSM `ref`)
- `dep_time` column added to OD CSV (the SP loader filters by `dep_time >= startSimulationH * 3600`)
- Sub-meter edges filtered before handoff (the GPU lane-map kernel allocates `length / cell_size` cells; sub-meter edges yield zero cells and trigger illegal-memory access)
- `uniqueid` renumbered sequentially 0..N-1 (the GPU kernel indexes per-edge arrays by `uniqueid`; gaps from filtered self-loops/short edges caused OOB at `b18CUDA_trafficSimulator.cu:1682`)

### 3.2 Container path resolution (resolved)

The bundled binary `chdir`s to `/LivingCity` at startup (or hardcodes the INI path) so `--pwd` alone doesn't redirect input reading, only output writing. Fixed at `e57141e` and `0ed5316` by overlaying our INI and network/ on top of `/LivingCity/command_line_options.ini` and `/LivingCity/network` via `--bind` mounts. Later extended at `99a7354` to also overlay at `/lpsim_src/LivingCity/...` for the rebuilt source binary.

### 3.3 CUDA toolchain mismatch (resolved)

The `yibo123/lpsim:cuda12.4` image is mis-tagged: its installed toolkit is CUDA 12.4, but the bundled binary was compiled against `libcudart.so.11.0`. Fixed by binding the host's `/apps` directory and pointing `LD_LIBRARY_PATH` at Pitzer's `cuda/11.8.0` module while preserving the container's CUDA 12.4 paths. Later (`1f7deb1`) the LD injection was gated to bundled-binary-only because the rebuilt source binary is linked against CUDA 12.4 and the LD-path collision was suspected to cause cuBLAS/cuRAND ABI mismatches.

### 3.4 In-container source rebuild (resolved with effort)

When the bundled binary's GPU OOB at `b18CUDA_trafficSimulator.cu:1682` proved unrelated to the schema fixes, we attempted to rebuild from source against the container's CUDA 12.4. This required ~10 commits of patching (`1359b9e` through `6fdaba1`):
- Patching `LivingCity.pro` for CUDA 12.4 paths (sed-replacing CUDA 9.0/10.1/11.2 references)
- Removing the broken `cuda.depend_command` qmake directive (mis-parses nvcc -M output into a phantom `b18CUDA_trafficSimulator.o` dependency with no recipe)
- Fixing the `cuda.dependcy_type` typo
- Extracting missing `src/benchmarker.{h,cpp}` and `src/linux_host_memory_logger.{h,cpp}` from the SIF (the upstream git repo is missing these files)
- Downloading and bind-mounting Boost 1.59 from `archives.boost.org` (the in-container path is broken)
- **The Boost wall:** Boost 1.59's `point_xy.hpp` uses `this->template set<N>(v)` which modern g++ (the container's gcc 13) resolves to `std::set<N>(...)` instead of the inherited base member template, failing with "type/value mismatch". Tried Boost 1.78 (`166ed87`), broke the Geometry API completely. Reverted to 1.59 (`6fdaba1`) and sed-patched the two offending lines with explicit base-class qualification: `this->boost::geometry::model::point<CoordinateType,2,CoordinateSystem>::template set<N>(v)`. Build then succeeded.
- Bumping CUDA_ARCH from sm_50 (Maxwell, the upstream default) to sm_70 (V100) at `483ebc9`

The build pipeline is fully reproducible, `sbatch --export=ALL,LPSIM_FORCE_SOURCE=1 cluster/jobs/build_lpsim.sbatch` produces a 26 MB binary with sm_70 SASS in ~2 minutes.

### 3.5 The wall, GPU kernel SIGSEGV at first kernel launch (NOT resolved)

After all the above, the rebuilt sm_70 binary on the chicago_1k_car scenario (20,058 nodes, 58,505 edges, 1,000 trips) consistently produces:

```
Running main loop from 7 to 8 with 1000 person...
Starting simulation ...
[exit -11, SIGSEGV]
```

Identical crash signature with:
- Bundled binary (had additional `b18CUDA_trafficSimulator.cu:1682` OOB on top)
- Rebuilt sm_70 binary, with CUDA 11.8 LD path injected
- Rebuilt sm_70 binary, without LD path injection (CUDA 12.4 only)

The crash occurs **inside the simulation kernel entry** before any per-tick output is produced. We did not isolate whether the crash originates in:
- The CPU-side data prep before the first `cudaMalloc`
- The first `cudaMalloc` itself (16 GB V100 should have ample headroom for 20K nodes / 1K trips)
- The first kernel launch (likely, the print "Starting simulation ..." emits then SIGSEGV with no stderr)
- A CUDA driver / runtime context creation

The diagnostic `cluster/jobs/diag_lpsim.sbatch` was prepared to test the rebuilt binary against the container's bundled `berkeley_2018` sample (with no SimForge inputs in the loop) to isolate "is the engine fundamentally broken on this CUDA/GPU combo?" from "are our inputs malformed?". It was not run before the decision to rule LPSim out, see §5.

## 4. Why LPSim was ruled out

Three converging factors:

1. **Time budget.** A long sequence of incremental fixes, all chasing failure modes that originate inside the LPSim engine rather than in SimForge code. The marginal cost of the next fix is bounded only by what the upstream codebase will reveal.
2. **Upstream signals.** The repo is largely abandoned (last commit on the pinned SHA is from 2024; missing source files; broken `LivingCity.pro` against current toolchains; no CI; no released versions). Fixing kernel-level bugs in a defunct GPU codebase is outside the scope of a Master's thesis on **benchmarking infrastructure**, not on engine internals.
3. **Diminishing thesis return.** Even if LPSim worked, the determinism limitation (atomicAdd reductions are not bit-deterministic) would force a separate "GPU non-determinism" footnote in every results table, weakening the cross-engine reproducibility story SimForge was built to demonstrate.

## 5. What this proves about SimForge

Engine churn, projects becoming unmaintained, build chains rotting, dependencies going incompatible, is the **default state** of academic simulation software. SimForge's adapter pattern is designed precisely for this. The LPSim experience is concrete evidence:

- The adapter package, MAPPING.md, manifest, build pipeline, and test suite are all preserved as-is. **If a future user finds a working LPSim fork (e.g., a maintained downstream, or upstream patches the GPU bug), the adapter reactivates with zero rework**, they re-pin the SHA in `lib/lpsim/manifest.json`, re-run `cluster/jobs/build_lpsim.sbatch`, and the test suite is already in place.
- The integration cost, measured in adapter LOC, test count, and conversion logic, is now a known quantity for future engine integrations.
- The diagnostic scripts (`smoke_lpsim.sbatch`, `diag_lpsim.sbatch`) are reusable templates for any engine added through the adapter pattern.

In thesis terms: **SimForge is the framework that survives the engine's failure.** The engine's failure is not a project failure, it is the use case the framework was built to handle.

## 6. References

*(Snapshot of the artifacts as they existed at the 2026-04-27 decision; the
adapter, tests, manifest, and sbatch jobs are not part of the shipped
framework once LPSim was ruled out, see the Code disposition note at the top.)*

- **Manifest:** `lib/lpsim/manifest.json`, pinned `git_sha` and `docker_image:tag`.
- **Test suite:** `tests/test_lpsim_adapter.py` (45 tests, all passing).
- **Methods chapter:** `doc/chapters/methods.md` §3.4.4 (LPSim adapter description; supersede the "fills the GPU comparator slot" claim with a forward-pointer to this evaluation).
- **Glossary:** `doc/GLOSSARY.md` "LPSim" entry, keep, but flag as deferred per this doc.
- **Upstream repo:** [Xuan-1998/LPSim](https://github.com/Xuan-1998/LPSim) (pinned SHA `452067ee831e6ecb4c906bae96fb77fdf71fa92e`).
