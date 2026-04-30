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

Writes to `runs/benchmark_small/benchmark_results_benchmark_small.json` (4 cells × 5 repeats = 20 runs).

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
| Per-cell directory           | flat: `<scenario>_<engine>_<mode>_seed<seed>/`          | nested: `<scenario_id>/<engine>/seed_<seed>/`                             |
| Summary JSON file            | `benchmark_results.json`                                | `benchmark_results_<runspec_name>.json`                                   |
| Summary JSON top-level keys  | `timestamp`, `matrix`, `summary`, `results`             | `runspec_name`, `started_at`, `completed_at`, `total_runs`, `successful_runs`, `failed_runs`, `summary`, `results` |
| Per-cell record fields       | `status`, `scenario`, `scenario_id`, `engine`, `mode`, `seed`, `repeat`, `runtime_s`, `metrics` (+ adapter extras) | same plus `repeat_index`, `wall_time_s`, `output_dir`, `tripinfo_path`, `error_message` (always present) |
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
      "output_dir": "runs/benchmark_small/chicago_1k_car/sumo/seed_42",
      "tripinfo_path": "runs/benchmark_small/chicago_1k_car/sumo/seed_42/tripinfo.xml",
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
| `runtime_s`                      | Simulator wall-clock time for the run                |
| `metrics.travel_time.trip_count` | Vehicles that completed their trip                   |
| `metrics.travel_time.mean`       | Mean trip duration (seconds)                         |
| `metrics.travel_time.p95`        | 95th percentile trip duration                        |
| `seed`                           | RNG seed (deterministic across re-runs)              |
| `mode`                           | `meso` or `micro` (kept separate by analysis layer)  |
| `status`                         | `success` or `failed`                                |

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

Renders **9 figures** (PNG + PDF) into `<results-dir>/plots/` (or `--output` if specified).

#### Generated figures

| Figure      | Plot Type            | Content                                                          | Thesis Use                          |
| ----------- | -------------------- | ---------------------------------------------------------------- | ----------------------------------- |
| **Fig 5.1** | Grouped bar (errbar) | Runtime by `(city, engine)`, faceted by mode                     | Headline runtime comparison         |
| **Fig 5.2** | Heatmap              | Reproducibility R-score per `(engine, mode)` × scenario; NaN cells render hatched grey ("not run") rather than red | Determinism evidence              |
| **Fig 5.3** | Grouped bar (errbar) | Mean travel time by engine, faceted by mode                      | Cross-engine output fidelity        |
| **Fig 5.4** | 3-panel summary      | Per-mode runtime, R-score, throughput side-by-side               | Executive summary                   |
| **Fig 5.5** | Speedup bars         | Engine speedup vs MATSim baseline, **within-mode**               | Cross-simulator comparison          |
| **Fig 5.6** | Mode comparison      | Micro vs meso runtime per engine                                 | Mesoscopic-mode value proposition   |
| **Fig 5.7** | Boxplot              | Runtime variability per `(engine, mode)`                         | Tail-behaviour discussion           |
| **Fig 5.8** | Scatter / dual-bar   | P95 tail latency vs mean travel time, faceted by mode            | Worst-case behaviour                |
| **Fig 5.9** | Trip-count parity    | Completed trips per `(engine, mode)`                             | Validates SCC/feasibility filter — every engine is shown to receive the same N |

### 4.3 Mode Comparison

```bash
python -m evaluation.compare_modes scenarios/chicago_1k_car --seed 42
```

Runs both micro and meso modes on the same scenario and computes:

- **Speedup**: meso runtime ÷ micro runtime
- **Fidelity metrics**: RMSE, GEH, KS-statistic between micro/meso travel-time distributions
- **Trip completion ratio** for each mode

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

1. **Runtime comparison** (Table 5.1, Fig 5.1, Fig 5.5)
   - SUMO meso vs MATSim vs DTALite wall-clock, **per mode**
   - DTALite's UE assignment gives a third-paradigm reference point; comparable to MATSim at scenario sizes the bundled stress test exercises.

2. **Reproducibility** (Table 5.2, Fig 5.2)
   - R-scores ≥ 0.997 across all engines confirm deterministic behaviour
   - MATSim hits R = 1.0 (perfectly deterministic with `lastIteration=0`)

3. **Fidelity** (Fig 5.3, Fig 5.9)
   - Mean travel times are consistent across engines for the same scenario
   - Fig 5.9 shows engines all received the same trip set — any per-engine `trip_count` gap is engine-internal mobsim behaviour, not feed asymmetry

4. **Throughput** (Fig 5.4 right panel)
   - Trips per second = `trip_count / runtime`
   - Higher throughput → more scalable for larger scenarios

5. **Mode trade-off** (Fig 5.6, Fig 5.7, Fig 5.8)
   - Micro is more accurate at the edges (P95) but pays an order-of-magnitude runtime cost vs meso

### Key thesis claims these results support

| Claim                                          | Evidence                                                         |
| ---------------------------------------------- | ---------------------------------------------------------------- |
| Canonical schema enables fair comparison       | Same scenario runs on all engines with identical demand (Fig 5.9) |
| Mesoscopic mode is much faster than micro      | Fig 5.6 (within-engine), `compare_modes.py` speedup ratio         |
| Results are reproducible                       | R-scores ≥ 0.997 across seeds (Table 5.2, Fig 5.2)                |
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

# 3. Generate the 9 thesis figures
python -m evaluation.generate_plots runs/benchmark_small/benchmark_results_benchmark_small.json --output doc/figures

# 4. Compare micro vs meso explicitly
python -m evaluation.compare_modes scenarios/chicago_1k_car

# 5. Run the test suite
python -m pytest tests/ -q
```
