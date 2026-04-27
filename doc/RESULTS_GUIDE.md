# SimForge Results Guide

This document explains the complete results workflow: what happens after running simulations, how to interpret outputs, and how each result maps to thesis Chapter 5.

---

## 1. Pipeline Overview

```
RunSpec ──► run_benchmark ──► runs/<name>/benchmark_results_<name>.json
                                      │
            ┌─────────────────────────┤
            ▼                         ▼
  analyze_benchmark.py        generate_plots.py
            │                         │
            ▼                         ▼
   Tables 5.1, 5.2 + Coverage     Figures 5.1 – 5.9
   (LaTeX + Markdown)             (PNG + PDF in plots/)
            │                         │
            └─────────┬───────────────┘
                      ▼
              Thesis Chapter 5
```

### Mode comparison (separate path)

```
compare_modes.py  ──►  micro vs meso  ──►  speedup + fidelity
```

---

## 2. Running Benchmarks

### Canonical stress test (matches all thesis figures)

```bash
python -m execution.run_benchmark runspecs/stress_test.yaml
```

Writes to `runs/stress_test/benchmark_results_stress_test.json` (4 cells × 5 repeats = 20 runs).

### Ad-hoc one-off via `run.py`

```bash
python run.py --scenario chicago_1k_car --engine sumo,matsim --mode meso --repeats 3
```

Writes to `runs/<timestamp>/benchmark_results_<timestamp>.json`.

### List configurations

```bash
python run.py --list
```

---

## 3. Result JSON Structure

Each run produces a JSON object:

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
python -m evaluation.analyze_benchmark runs/stress_test/benchmark_results_stress_test.json
python -m evaluation.analyze_benchmark runs/stress_test/benchmark_results_stress_test.json --latex --markdown
```

#### Output sections

| Section                 | Contents                                                                           | Thesis Use                |
| ----------------------- | ---------------------------------------------------------------------------------- | ------------------------- |
| **Summary**             | Engine-level aggregates (success rate, avg runtime, avg R-score)                   | §5.0 Discussion           |
| **Table 5.1**           | Runtime per `(scenario, engine, mode)` (mean, std, min, max)                       | §5.1 Runtime Performance  |
| **Table 5.2**           | Reproducibility per `(scenario, engine, mode)` (avg TT, std TT, R-score, rating)   | §5.2 Reproducibility      |
| **Coverage diagnostic** | Flags low-sample (`n < 3`) cells, asymmetric coverage across scenarios, fully-failed cells | §5.3 Methodology notes    |
| **LaTeX**               | Copy-pasteable `\begin{table}` blocks                                              | Appendix / Chapter 5      |
| **Markdown**            | GitHub-friendly tables                                                             | README / documentation    |

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
- **Asymmetric coverage** — engine/mode present in some scenarios but missing in others (the gap that motivated `runspecs/stress_test.yaml`'s NYC-cell fill-in).
- **Silently-failed cells** — declared `runs[]` entries that produced 0 successes.

### 4.2 Plot Generation

```bash
python -m evaluation.generate_plots runs/stress_test/benchmark_results_stress_test.json
python -m evaluation.generate_plots runs/stress_test/benchmark_results_stress_test.json --output doc/figures
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
   - SUMO meso vs MATSim vs LPSim wall-clock, **per mode**
   - LPSim's GPU runtime is the headline scalability story for the 200K and 500K tiers.

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
| GPU acceleration provides speedup at scale     | LPSim vs SUMO meso runtime on chicago_200k and nyc_500k tiers     |

---

## 7. Known Limitations

- **Apple Silicon arm64**: `netconvert` on macOS arm64 has historically segfaulted on large networks (>~3,000 nodes) under SUMO 1.20.x. Behaviour under the locked SUMO 1.26.0 wheel has not been re-verified at scale; the bundled 1K and 10K scenarios run cleanly, but for the 50K+ tiers we recommend Linux/HPC where the same `eclipse-sumo` wheel installs without the macOS-specific issue.
- **MATSim**: Requires Java 17+ and the JAR in `lib/matsim-15.0/` (downloaded once per [SETUP.md](../SETUP.md)).
- **Microscopic mode**: Order-of-magnitude slower than meso for the same trip count.
- **LPSim**: Requires NVIDIA CUDA. The adapter does not silently fall back to CPU — when no GPU binary is staged, every `lpsim` cell records a clean failure with a build pointer. Build via `sbatch cluster/jobs/build_lpsim.sbatch` on a Pitzer GPU node.
- **LPSim determinism**: GPU atomic reductions are not bit-deterministic across runs even with the same seed — expect lower R-scores than SUMO meso (which is fully deterministic) or MATSim (R = 1.0 with `lastIteration=0`). N=5 repeats give us statistical room; reported as `mean ± 95 % CI`.

---

## 8. Quick Reference

```bash
# 1. Run the canonical benchmark
python -m execution.run_benchmark runspecs/stress_test.yaml

# 2. Analyze results
python -m evaluation.analyze_benchmark runs/stress_test/benchmark_results_stress_test.json --latex --markdown

# 3. Generate the 9 thesis figures
python -m evaluation.generate_plots runs/stress_test/benchmark_results_stress_test.json --output doc/figures

# 4. Compare micro vs meso explicitly
python -m evaluation.compare_modes scenarios/chicago_1k_car

# 5. Run the test suite
python -m pytest tests/ -q
```
