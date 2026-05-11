# SimForge Results Guide

This document explains the complete results workflow: what happens after running simulations, how to interpret outputs, and how each result maps to thesis Chapter 5.

---

## 1. Pipeline Overview

```
RunSpec ──► run_benchmark ──► runs/<name>/benchmark_results_<name>.json
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            ▼                         ▼                         ▼
  analyze_benchmark.py        audit_fairness.py        generate_plots.py
            │                         │                         │
            ▼                         ▼                         ▼
   Tables 5.1, 5.2 + Coverage     Q1–Q4 PASS/WARN/FAIL    Figures 5.1 – 5.9
   + Demand Composition (V5+)     + Q5 Demand composition  (PNG + PDF in plots/)
   (LaTeX + Markdown)             across all engines
            │                         │                         │
            └─────────────────────────┼─────────────────────────┘
                                      ▼
                              Thesis Chapter 5
```

The middle step — `audit_fairness` — is the methodology check the
thesis defense relies on. It verifies four fairness questions and
reports a fifth informational breakdown on each scenario:

  - **Q1: same trip set** (cross-engine feasibility verdict byte-identical)
  - **Q2: same network** (SCC-filtered nodes/links match across adapters)
  - **Q3: same trip count simulated** (per-engine simulated count = feasibility target)
  - **Q4: cross-engine travel-time spread** (mean / P95 + pairwise ratios — this is the paradigm-spread signal)
  - **Q5: demand composition** (V5+ trip-purpose breakdown) — informational, not a fairness gate. Shows total / AM peak / PM peak / school-related percentages and the per-purpose row count, sourced from the canonical bundle's `demand.csv`. Pre-V5 bundles missing the `purpose` column emit a one-line `(no V5+ purpose column at <path> — skipping)` and the section is omitted.

See `evaluation/audit_fairness.py` docstring for invocation and `doc/EXPERIMENT_LOG.md` §3 for measured Q1–Q4 results from the canonical Pitzer runs.

### Mode comparison (separate path)

```
compare_modes.py  ──►  micro vs meso  ──►  speedup + fidelity
```

---

## 2. Running Benchmarks

### Canonical stress test (matches all thesis figures)

```bash
python -m execution.run_benchmark runspecs/benchmark_small.yaml
```

Writes per-scenario JSONs at `runs/benchmark_small/<scenario>/benchmark_results_benchmark_small.json` (Phase 12+ — 11 cells × 5 repeats = 55 runs total across the three scenarios).

### Ad-hoc one-off via `run.py`

```bash
python run.py --scenario chicago_1k_car --engine sumo,matsim --mode meso --repeats 3
```

Writes to `runs/<timestamp>/benchmark_results_<timestamp>.json`.

### List configurations

```bash
python run.py --list
```

### `run.py` vs `run_benchmark.py` — what differs

Both call the same adapters and produce the same per-cell engine artefacts (`tripinfo.xml`, `output_trips.csv.gz`, `link_performance.csv`, `feasibility_report.json` …). They differ in the wrapping: how the per-cell directories are laid out, what the summary JSON is named, and the top-level schema of that JSON.

| Aspect                       | `run.py`                                                | `python -m execution.run_benchmark`                                       |
| ---------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------- |
| Matrix source                | CLI flags (`--scenario --engine --mode --repeats`)      | Locked YAML in `runspecs/*.yaml`                                          |
| Output base                  | `runs/benchmark_<timestamp>/` (or `--output`)           | `runs/<runspec.output_dir>/` (or `--output`)                              |
| Per-cell directory           | flat: `<scenario>_<engine>_<mode>_seed<seed>/`          | nested: `<scenario_id>/<engine>/<mode>/seed_<seed>/` (Phase 12+)          |
| Summary JSON file            | `benchmark_results.json`                                | `benchmark_results_<runspec_name>.json`                                   |
| Summary JSON top-level keys  | `timestamp`, `matrix`, `summary`, `results`             | `runspec_name`, `started_at`, `completed_at`, `total_runs`, `successful_runs`, `failed_runs`, `summary`, `results` |
| Per-cell record fields       | `status`, `scenario`, `scenario_id`, `engine`, `mode`, `seed`, `repeat`, `runtime_s`, `cell_wall_s`, `engine_wall_s`, `metrics` (+ adapter extras) | same plus `repeat_index`, `wall_time_s`, `output_dir`, `tripinfo_path`, `error_message` (always present) |
| `--verbose` flag             | yes (sticky bar + log capture)                          | no                                                                        |
| Other flags                  | `--list --validate-only --timeout --seed --repeats`     | `--dry-run --mesoscopic`                                                  |
| Cluster sbatch wrappers      | none                                                    | `cluster/jobs/benchmark_*.sbatch`, `cluster/jobs/05_nyc_500k_car.sbatch`   |
| Used for                     | Quick exploration, one-offs, ad-hoc matrices            | Reproducible thesis numbers; locked, version-controllable                 |

`evaluation/audit_fairness.py` autodetects both layouts (plus the two sbatch-nested variants), so the same `audit_fairness <run-dir>` invocation works regardless of which entry point produced the run. `analyze_benchmark` and `generate_plots` consume either summary JSON unchanged — they key off `results[].{scenario,engine,mode,seed,runtime_s,metrics}`, all of which exist in both schemas.

Why both still exist: `run.py` predates the runspec harness and grew the nicer interactive ergonomics (sticky progress bar, `--verbose`, `--list`, `--validate-only`); `run_benchmark.py` was added when locked, citable matrices became thesis-critical. Neither has been retired. See `help.py run` and `help.py benchmark` for the per-script flag list.

---

## 3. Result JSON Structure

Two shapes — one per entry point. The `results[]` array fields mostly overlap; the top-level wrapper is what differs.

### 3.1 `benchmark_results.json` — written by `run.py`

```json
{
  "timestamp": "20260418_223000",
  "matrix": {
    "scenarios": ["chicago_1k_car"],
    "engines": ["sumo", "matsim"],
    "modes": ["meso"],
    "repeats": 3
  },
  "summary": { "total": 6, "completed": 6, "failed": 0 },
  "results": [
    {
      "status": "success",
      "scenario": "chicago_1k_car",
      "scenario_id": "chicago_1k_car_sumo_meso",
      "engine": "sumo",
      "mode": "meso",
      "seed": 42,
      "repeat": 1,
      "runtime_s": 0.27,
      "engine_wall_s": 0.27,
      "cell_wall_s": 1.83,
      "metrics": {
        "travel_time": {
          "trip_count": 995,
          "mean": 204.05,
          "p95": 412.3
        }
      }
    }
  ]
}
```

### 3.2 `benchmark_results_<runspec_name>.json` — written by `run_benchmark.py`

```json
{
  "runspec_name": "stress_test",
  "started_at": "2026-04-25T18:00:00Z",
  "completed_at": "2026-04-25T18:27:14Z",
  "total_runs": 20,
  "successful_runs": 20,
  "failed_runs": 0,
  "summary": { "total": 20, "completed": 20, "failed": 0 },
  "results": [
    {
      "scenario": "chicago_1k_car",
      "scenario_id": "chicago_1k_car_sumo_meso",
      "engine": "sumo",
      "mode": "meso",
      "seed": 42,
      "repeat": 1,
      "repeat_index": 0,
      "status": "success",
      "runtime_s": 0.27,
      "wall_time_s": 0.27,
      "engine_wall_s": 0.27,
      "cell_wall_s": 1.83,
      "output_dir": "runs/benchmark_small/chicago_1k_car/sumo/meso/seed_42",
      "tripinfo_path": "runs/benchmark_small/chicago_1k_car/sumo/meso/seed_42/tripinfo.xml",
      "error_message": null,
      "metrics": {
        "travel_time": {
          "trip_count": 995,
          "mean": 204.05,
          "p95": 412.3
        }
      }
    }
  ]
}
```

The harness shape is defined by `BenchmarkResult.to_dict()` / `RunResult.to_dict()` in `execution/run_benchmark.py` (lines ~170–245). The `run.py` shape is built inline at `run.py` ~623.

### Key fields

| Field                            | Meaning                                              |
| -------------------------------- | ---------------------------------------------------- |
| `runtime_s`                      | Engine subprocess wall (back-compat alias of `engine_wall_s` on success). What `analyze_benchmark` / `generate_plots` / Chapter 5 tables key off. |
| `wall_time_s`                    | Same as `runtime_s` on success (engine subprocess only). Preserved verbatim from earlier SimForge versions. |
| `engine_wall_s`                  | Engine subprocess only (mobsim / DTA iterations / queue net). Explicit alias of `wall_time_s`; what the thesis runtime numbers cite. |
| `cell_wall_s`                    | Full per-cell wall: adapter prep (canonical → engine format, including per-trip BFS pre-routing) + engine subprocess + output parsing. Per-cell `cell_wall_s` values sum to the harness `Wall time` total. |
| `metrics.travel_time.trip_count` | Vehicles that completed their trip                   |
| `metrics.travel_time.mean`       | Mean trip duration (seconds)                         |
| `metrics.travel_time.p95`        | 95th percentile trip duration                        |
| `seed`                           | RNG seed (deterministic across re-runs)              |
| `mode`                           | `meso` or `micro` (kept separate by analysis layer)  |
| `status`                         | `success` or `failed`                                |

> **Wall vs engine.** SimForge separates these because Chapter 5 is benchmarking the *engine paradigm* (mobsim vs UE vs queue), not the Python adapter prep. A faster Python adapter would lower `cell_wall_s` but leave `engine_wall_s` (and therefore the thesis runtime numbers) untouched. The CLI shows both — `wall (engine)` per cell — so users can see where time actually goes; downstream tools key off the engine number for citing.

A sibling `feasibility_report.json` is written next to every adapter's output, recording the SCC-derived feasible-trip set and any drops — proves engines were fed the same input set.

---

## 4. Analysis Tools

### 4.1 Benchmark Analysis

```bash
python -m evaluation.analyze_benchmark runs/benchmark_small/benchmark_results_benchmark_small.json
python -m evaluation.analyze_benchmark runs/benchmark_small/benchmark_results_benchmark_small.json --latex --markdown
```

#### Output sections

| Section                  | Contents                                                                           | Thesis Use                |
| ------------------------ | ---------------------------------------------------------------------------------- | ------------------------- |
| **Summary**              | Engine-level aggregates (success rate, avg runtime, avg R-score)                   | §5.0 Discussion           |
| **Coverage diagnostic**  | Flags low-sample (`n < 3`) cells, asymmetric coverage across scenarios, fully-failed cells | §5.3 Methodology notes    |
| **Demand Composition** (V5+) | One row per scenario showing total / AM peak / PM peak / school-related counts (V5+ purpose taxonomy). Read from `scenarios/<name>/demand.csv`'s `purpose` column. Pre-V5 bundles silently omit the section. | §5.6 Demand realism appendix |
| **Table 5.1**            | Runtime per `(scenario, engine, mode)` (mean, std, min, max)                       | §5.1 Runtime Performance  |
| **Table 5.2**            | Reproducibility per `(scenario, engine, mode)` (avg TT, std TT, R-score, rating)   | §5.2 Reproducibility      |
| **LaTeX**                | Copy-pasteable `\begin{table}` blocks                                              | Appendix / Chapter 5      |
| **Markdown**             | GitHub-friendly tables                                                             | README / documentation    |

> **Mode is part of the grouping key** — SUMO meso and SUMO micro never collapse into one row. (See CHANGELOG.md → Addendum 3 for why this matters.)

#### Reproducibility Score (R)

$$R = 1 - \frac{\sigma}{\mu}$$

where σ is the standard deviation and μ is the mean of travel times across repeat runs with different seeds.

| R-Score     | Rating    |
| ----------- | --------- |
| ≥ 0.95      | Excellent |
| 0.90 – 0.95 | Good      |
| 0.80 – 0.90 | Moderate  |
| < 0.80      | Poor      |

#### Coverage diagnostic

Catches three classes of silent gaps in any RunSpec:

- **Low-sample cells** — `n < 3`: R-score is statistically weak; the diagnostic prints a warning so the table reader knows not to over-interpret.
- **Asymmetric coverage** — engine/mode present in some scenarios but missing in others (the gap that motivated `runspecs/benchmark_small.yaml`'s NYC-cell fill-in).
- **Silently-failed cells** — declared `runs[]` entries that produced 0 successes.

### 4.2 Plot Generation

```bash
python -m evaluation.generate_plots runs/benchmark_small/benchmark_results_benchmark_small.json
python -m evaluation.generate_plots runs/benchmark_small/benchmark_results_benchmark_small.json --output doc/figures
```

Renders **10 figures** (PNG + PDF) into `<results-dir>/plots/` (or `--output` if specified). Two of them — Fig 5.9 (Demand composition) and Fig 5.10 (Wall vs engine) — are auto-skipped when their data isn't available, so the figure count drops to 8 on pre-V5 bundles or pre-Phase-11.6 result files.

#### Generated figures

| Figure      | Plot Type            | Content                                                          | Thesis Use                          |
| ----------- | -------------------- | ---------------------------------------------------------------- | ----------------------------------- |
| **Fig 5.1**  | Grouped bar (errbar) | **Engine** runtime by `(city, engine)`, faceted by mode (engine subprocess only — see §3) | Headline runtime comparison         |
| **Fig 5.2**  | Heatmap              | Reproducibility R-score per `(engine, mode)` × scenario; NaN cells render hatched grey ("not run") rather than red | Determinism evidence              |
| **Fig 5.3**  | Grouped bar (errbar) | Mean travel time by engine, faceted by mode                      | Cross-engine output fidelity        |
| **Fig 5.4**  | Speedup bars         | Engine speedup vs MATSim baseline, **within-mode**               | Cross-simulator comparison          |
| **Fig 5.5**  | Mode comparison      | Micro vs meso **engine** runtime per engine                      | Mesoscopic-mode value proposition   |
| **Fig 5.6**  | Boxplot              | **Engine** runtime variability per `(engine, mode)`              | Tail-behaviour discussion           |
| **Fig 5.7**  | Scatter / dual-bar   | P95 tail latency vs mean travel time, faceted by mode            | Worst-case behaviour                |
| **Fig 5.8**  | Trip-count parity    | Completed trips per `(engine, mode)`                             | Validates SCC/feasibility filter — every engine is shown to receive the same N |
| **Fig 5.9**  | Stacked bar          | Per-scenario V5+ trip-purpose composition (HBW_AM/PM, HBSchool_AM/PM, chains) read from canonical `demand.csv` | Demand-realism evidence (Phases 5–10) |
| **Fig 5.10** | Stacked bar          | Per-cell wall time breakdown — engine subprocess vs adapter prep + parse (`cell_wall_s − engine_wall_s`); skipped on pre-Phase-11.6 result files | Methodological footnote: where time actually goes |

### 4.3 Mode Comparison

```bash
python -m evaluation.compare_modes scenarios/chicago_1k_car --seed 42
```

Runs both micro and meso modes on the same scenario and computes:

- **Speedup**: meso runtime ÷ micro runtime
- **Fidelity metrics**: RMSE, GEH, KS-statistic between micro/meso travel-time distributions
- **Trip completion ratio** for each mode

### 4.4 Geographic Visualization — `python -m visualization.generate_maps`

Separate, opt-in component on the `visualization` branch. Reads the
same canonical bundle + per-cell engine output as the other analysis
tools and renders seven geographic map types — two from the bundle
alone, three per-engine maps, and two cross-engine maps. The main
SimForge code paths do not import it, so the locked benchmark numbers
are independent of any rendered plot.

```bash
# One-time setup: cache the US Census tract + TIGER roads shapefiles
python -m tools.download_census_tracts --all-bundled
python -m tools.download_tiger_roads --all-bundled

# Coverage report (what's generatable from what's on disk?)
python -m visualization.generate_maps --scenario chicago_1k_car --dry-run

# Render every available map type
python -m visualization.generate_maps --scenario chicago_1k_car --maps all

# Render one engine's Phase B maps
python -m visualization.generate_maps --scenario nyc_10k_car \
    --maps link_load,travel_time --engine matsim

# MATSim particle animation, GIF format, half-speed playback
python -m visualization.generate_maps --scenario chicago_1k_car \
    --maps animated_flow --anim-format gif --anim-sim-per-frame 10
```

**Map catalogue:**

| Map | Inputs | Engine specificity | Use in thesis |
|---|---|---|---|
| `od_origins` / `od_destinations` | Bundle + cached US Census tracts + TIGER roads | — (cross-engine, demand only) | §3.3 demand realism — proves the V5+ Phase 9c PM-chain mechanism produces symmetric metro-scale demand |
| `link_load` | Per-cell engine output | per `(engine, mode)` | §5.0 cross-engine sanity — SUMO ≈ MATSim, DTALite distinct (same data as `route_diversity`, different framing) |
| `congestion` | DTALite `link_performance.csv` | DTALite only | §5.0 — visualizes UE equilibrium link-level congestion |
| `travel_time` | Per-cell engine output + bundle | per `(engine, mode)` | §5.2 — choropleth of mean travel time by origin tract |
| `route_diversity` | Cell output from ≥ 2 engines | cross-engine | §5.0 — direct visual proof of the SimForge BFS contract: consensus links gray, DTALite UE alternates red |
| `animated_flow` | MATSim `output_events.xml.gz` | MATSim only | §3.3 — visualizes PUMS integer-minute departure bursts (cross-references `methods.md` step 9) |

**Coverage matrix.** The CLI prints what's renderable before doing
work, similar to `analyze_scenarios`:

```text
Scenario:  chicago_1k_car
Bundle:    [OK]    scenarios/chicago_1k_car  (demand, manifest, network, signals)
Cells:     [OK]    dtalite/meso  seeds=[42, 43, 44, 45, 46]
Cells:     [OK]    matsim/meso   seeds=[42, 43, 44, 45, 46]
Cells:     [OK]    sumo/meso     seeds=[42, 43, 44, 45, 46]
Cells:     [OK]    sumo/micro    seeds=[42, 43, 44, 45, 46]

Available maps:
  [OK]  od_origins            (bundle present (4 files))
  [OK]  link_load             (engines with results: ['dtalite', 'matsim', 'sumo'])
  [OK]  congestion            (engines with results: ['dtalite', 'matsim', 'sumo'])
  [OK]  travel_time           (engines with results: ['dtalite', 'matsim', 'sumo'])
  [OK]  route_diversity       (3 engines with results)
  [OK]  animated_flow         (event-level output present)
```

Maps whose inputs aren't on disk render as `[--]` in the matrix and
`[SKIP]` when actually requested — never an error.

**Output layout.** Default destination is
`visualization/output/<scenario>/` (gitignored). Naming convention:

- `<map_type>.png` for bundle-only or cross-engine maps
  (`od_origins.png`, `od_destinations.png`, `route_diversity.png`)
- `<map_type>_<engine>_<mode>.<ext>` for engine-specific maps
  (`link_load_dtalite_meso.png`, `animated_flow_matsim_meso.mp4`)

Animations support three containers: `mp4` (default, smallest), `gif`
(embeds directly in markdown, one-shot playback), `apng` (full color,
~5× smaller than GIF).

**Cross-engine interpretation surfaces.** Three properties the maps
make visible — see `visualization/README.md` for the full detail:

- *SUMO and MATSim `link_load` look identical, DTALite differs.* Same
  SimForge BFS routes → same spatial traffic structure across SUMO /
  MATSim; DTALite's UE picks alternative paths. Direct visual proof of
  the fair-comparison contract.
- *`animated_flow` shows "departure bursts".* PUMS JWMNP is integer-
  minute, so chicago_1k_car's 1000 trips share only ~20 unique
  departure timestamps. Faithful to data, not a SimForge artefact —
  documented in `methods.md` §3.3 step 9.
- *`chicago_200k_car od_origins ≈ od_destinations` (74 % overlap).*
  Full-day scenarios emit both AM + PM HBW pairs; OD sets are the same
  places at different times. AM-only bundles see only 5.5 % overlap.

See [`visualization/README.md`](../visualization/README.md) for the
full CLI reference, output conventions, data-source provenance, and
the `tools/download_census_tracts.py` / `tools/download_tiger_roads.py`
helpers that populate the public-domain shapefile cache.

### 4.5 Pre-Run Bundle Inspection — `tools/analyze_scenarios.py`

Tabular end-to-end analysis of every (or any) scenario bundle in
`scenarios/`. Useful before running the benchmark to verify the
generated bundles look right, or when comparing realism across tiers.

```bash
python tools/analyze_scenarios.py                        # all bundles, all sections
python tools/analyze_scenarios.py chicago_1k_car         # single bundle
python tools/analyze_scenarios.py chicago_1k_car nyc_10k_car
python tools/analyze_scenarios.py --section network --section signals
python tools/analyze_scenarios.py --no-color             # plain ASCII (for piping)
```

Seven sections (each one side-by-side table with scenarios as columns):

| Section          | Reports                                                               |
| ---------------- | --------------------------------------------------------------------- |
| `configuration`  | City, trips, time window, radius, seed, strategy, generation time, OSM source |
| `network`        | Nodes, links, has_signal, turn restrictions, speed/lane stats          |
| `road_classes`   | Per-OSM-highway-type link counts, sorted by total                     |
| `signals`        | Junction count, cycle, phase pattern, density                         |
| `demand`         | Totals + trip-purpose breakdown + peak split & chain summary          |
| `artefacts`      | Per-file sizes + total                                                |
| `toolchain`      | Python / osmnx / numpy / etc. versions recorded at generation time    |

Auto-paginates when the terminal isn't wide enough — each section
splits into pages of N scenarios with a `(scenarios X–Y of N)` page
suffix. Pre-V5 bundles missing the `purpose` column gracefully render
the demand totals subsection only.

This complements `audit_fairness` Q5 and `analyze_benchmark`'s demand
composition table — those run *after* simulation; `analyze_scenarios`
runs *before*, on the canonical bundle alone, with no engine output
needed.

For the same content from inside the in-CLI help system, run
`python help.py analyzer` (TUI: arrow-key into the "Analysis & tools"
group; text mode: pipes/non-TTY also work).

---

## 5. Metric Modules

Located in `evaluation/metrics/`:

| Module               | Key Functions                                               | What It Measures                                         |
| -------------------- | ----------------------------------------------------------- | -------------------------------------------------------- |
| `travel_time.py`     | `parse_sumo_tripinfo()`                                     | Parses SUMO `tripinfo.xml` → trip count, mean TT, p95 TT |
| `fidelity.py`        | `compute_rmse()`, `compute_geh()`, `compute_ks_statistic()` | How close two simulators' outputs are                    |
| `reproducibility.py` | `compute_reproducibility_index()`                           | Cross-seed consistency (R = 1 − CV)                      |
| `scalability.py`     | `SimulationTimer`, `get_hardware_info()`                    | Wall-clock scaling with demand size                      |

---

## 6. Interpreting Results for Thesis

### What to report in Chapter 5

1. **Runtime comparison** (Table 5.1, Fig 5.1, Fig 5.4)
   - SUMO meso vs MATSim vs DTALite wall-clock, **per mode**
   - DTALite's UE assignment gives a third-paradigm reference point; comparable to MATSim at scenario sizes the bundled stress test exercises.

2. **Reproducibility** (Table 5.2, Fig 5.2)
   - R-scores ≥ 0.997 across all engines confirm deterministic behaviour
   - MATSim hits R = 1.0 (perfectly deterministic with `lastIteration=0`)

3. **Fidelity** (Fig 5.3, Fig 5.8)
   - Mean travel times are consistent across engines for the same scenario
   - Fig 5.8 shows engines all received the same trip set — any per-engine `trip_count` gap is engine-internal mobsim behaviour, not feed asymmetry

4. **Mode trade-off** (Fig 5.5, Fig 5.6, Fig 5.7)
   - Micro is more accurate at the edges (P95) but pays an order-of-magnitude runtime cost vs meso

5. **Demand realism** (Fig 5.9, audit_fairness Q5)
   - Per-scenario stacked bar makes the V5+ trip-purpose composition visible at a glance — HBW dominates, HBSchool + chain legs are the parent-with-school-age-dependent share.
   - Pairs with the MODELGEN_AND_MODES.md text and Phase 9 in CHANGELOG to back the "we use real demand, not a uniform OD matrix" claim.

6. **Methodological footnote** (Fig 5.10)
   - Per-cell wall = adapter prep + engine subprocess + parse. Chapter 5 runtime tables and Fig 5.1 cite the engine subprocess only; this figure documents that prep is non-trivial for large MATSim/SUMO scenarios (per-trip BFS routing on the canonical graph).
   - Useful in the defense if a committee member asks "is the engine number really the right thing to compare?" — the answer is yes, because adapter prep is a SimForge implementation cost, not an engine cost.

### Key thesis claims these results support

| Claim                                          | Evidence                                                         |
| ---------------------------------------------- | ---------------------------------------------------------------- |
| Canonical schema enables fair comparison       | Same scenario runs on all engines with identical demand (Fig 5.8) |
| Mesoscopic mode is much faster than micro      | Fig 5.5 (within-engine), `compare_modes.py` speedup ratio         |
| Results are reproducible                       | R-scores ≥ 0.997 across seeds (Table 5.2, Fig 5.2)                |
| Demand is realistic, not a uniform OD matrix   | Fig 5.9 V5+ trip-purpose composition (HBW + HBSchool + chains)    |
| Engine times are comparable across simulators  | Fig 5.10 isolates engine subprocess from adapter prep             |
| Framework scales to large scenarios            | Scalability metrics from HPC runs (200K, 500K tiers)              |
| Three-paradigm cross-engine validation         | DTALite (DTA equilibrium) vs MATSim (queue-based agent) vs SUMO (microscopic / meso queue) on chicago_200k and nyc_500k tiers |

---

## 7. Known Limitations

- **Apple Silicon arm64**: `netconvert` on macOS arm64 has historically segfaulted on large networks (>~3,000 nodes) under SUMO 1.20.x. Behaviour under the locked SUMO 1.26.0 wheel has not been re-verified at scale; the bundled 1K and 10K scenarios run cleanly, but for the 50K+ tiers we recommend Linux/HPC where the same `eclipse-sumo` wheel installs without the macOS-specific issue.
- **MATSim**: Requires Java 17+ and the JAR in `lib/matsim-15.0/` (downloaded once per [SETUP.md](../SETUP.md)).
- **Microscopic mode**: Order-of-magnitude slower than meso for the same trip count.
- **DTALite**: Requires `path4gmns` from `requirements.lock`. On macOS the bundled binary needs `brew install libomp` for the OpenMP runtime. The adapter does not silently fall back — when path4gmns is not installed, every `dtalite` cell records a clean failure with the install command.
- **DTALite determinism**: Fully deterministic — UE algorithm with fixed iteration order, no atomic reductions, no GPU non-determinism. R = 1.0 expected, matching SUMO meso and MATSim with `lastIteration=0`.
- **LPSim** (historical): Was the third primary engine in Versions 1–4, abandoned in Version_5 after the bundled GPU binary crashed on networks > a few-K nodes and a from-source rebuild SIGSEGV'd at first kernel launch. Full retrospective: [`doc/engines/LPSIM_RETROSPECTIVE.md`](engines/LPSIM_RETROSPECTIVE.md).

---

## 8. Quick Reference

```bash
# 1. Run the canonical benchmark
python -m execution.run_benchmark runspecs/benchmark_small.yaml

# 2. Analyze results
python -m evaluation.analyze_benchmark runs/benchmark_small/benchmark_results_benchmark_small.json --latex --markdown

# 3. Generate the 10 thesis figures
python -m evaluation.generate_plots runs/benchmark_small/benchmark_results_benchmark_small.json --output doc/figures

# 4. Compare micro vs meso explicitly
python -m evaluation.compare_modes scenarios/chicago_1k_car

# 5. Run the test suite
python -m pytest tests/ -q
```
