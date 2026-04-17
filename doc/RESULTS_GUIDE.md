# SimForge Results Guide

This document explains the complete results workflow: what happens after
running simulations, how to interpret outputs, and how each result maps
to thesis chapters.

---

## 1. Pipeline Overview

```
Scenarios  ──►  run.py (benchmark)  ──►  benchmark_results.json
                                              │
                    ┌─────────────────────────┤
                    ▼                         ▼
          analyze_benchmark.py        generate_plots.py
                    │                         │
                    ▼                         ▼
          Tables (5.1, 5.2)       Figures (5.1–5.5)
          LaTeX + Markdown        PNG in doc/figures/
                    │                         │
                    └─────────┬───────────────┘
                              ▼
                     Thesis Chapter 5
```

### Separate mode comparison

```
compare_modes.py  ──►  micro vs meso  ──►  speedup + fidelity
```

---

## 2. Running Benchmarks

### Quick local run (mesoscopic)

```bash
python run.py --scenario chicago_1k_car --engine sumo,qarsumo \
              --mode meso --repeats 3 --timeout 300
```

### Full matrix with microscopic (needs long timeout)

```bash
python run.py --scenario chicago_1k_car --engine sumo,qarsumo \
              --mode micro,meso --repeats 3 --timeout 3600
```

### List available configurations

```bash
python run.py --list
```

### Output location

Results are written to `runs/benchmark_<timestamp>/benchmark_results.json`.

---

## 3. Result JSON Structure

Each run produces a JSON object:

```json
{
  "timestamp": "20260415_194919",
  "matrix": {
    "scenarios": ["chicago_1k_car"],
    "engines": ["sumo", "qarsumo"],
    "modes": ["meso"],
    "repeats": 3
  },
  "summary": { "total": 6, "completed": 6, "failed": 0 },
  "results": [
    {
      "status": "success",
      "wall_time_s": 0.27,
      "scenario": "chicago_1k_car",
      "scenario_id": "chicago_1k_car_sumo_meso",
      "engine": "sumo",
      "mode": "meso",
      "seed": 42,
      "repeat": 1,
      "runtime_s": 0.27,
      "metrics": {
        "travel_time": {
          "trip_count": 985,
          "mean": 2.99,
          "p95": 19.0
        }
      }
    }
  ]
}
```

### Key fields

| Field                            | Meaning                            |
| -------------------------------- | ---------------------------------- |
| `wall_time_s` / `runtime_s`      | Total simulation wall-clock time   |
| `metrics.travel_time.trip_count` | Vehicles that completed their trip |
| `metrics.travel_time.mean`       | Mean trip duration (seconds)       |
| `metrics.travel_time.p95`        | 95th percentile trip duration      |
| `seed`                           | Random seed for reproducibility    |
| `status`                         | `success` or `failed`              |

---

## 4. Analysis Tools

### 4.1 Benchmark Analysis

```bash
python -m evaluation.analyze_benchmark runs/benchmark_*/benchmark_results.json
```

**Add `--latex --markdown` for thesis-ready tables:**

```bash
python -m evaluation.analyze_benchmark runs/benchmark_*/benchmark_results.json \
       --latex --markdown
```

#### Output tables

| Table         | Contents                                                                | Thesis Reference         |
| ------------- | ----------------------------------------------------------------------- | ------------------------ |
| **Table 5.1** | Runtime per scenario × engine (mean, std, min, max)                     | §5.1 Runtime Performance |
| **Table 5.2** | Reproducibility per scenario × engine (avg TT, std TT, R-score, rating) | §5.2 Reproducibility     |
| **Summary**   | Engine-level aggregates (success rate, avg runtime, avg R-score)        | §5.3 Discussion          |
| **LaTeX**     | Copy-pasteable `\begin{table}` block                                    | Appendix / Chapter 5     |
| **Markdown**  | GitHub-friendly table                                                   | README / documentation   |

#### Reproducibility Score (R)

$$R = 1 - \frac{\sigma}{\mu}$$

where $\sigma$ is the standard deviation and $\mu$ is the mean of travel
times across repeat runs with different seeds.

| R-Score     | Rating    |
| ----------- | --------- |
| ≥ 0.95      | Excellent |
| 0.90 – 0.95 | Good      |
| 0.80 – 0.90 | Moderate  |
| < 0.80      | Poor      |

### 4.2 Plot Generation

```bash
python -m evaluation.generate_plots runs/benchmark_*/benchmark_results.json \
       --output doc/figures
```

#### Generated figures

| Figure      | Plot Type         | Content                                           | Thesis Use                        |
| ----------- | ----------------- | ------------------------------------------------- | --------------------------------- |
| **Fig 5.1** | Grouped bar chart | Runtime by city and engine                        | Shows relative engine performance |
| **Fig 5.2** | Heatmap           | Reproducibility R-scores (engine × scenario)      | Validates determinism             |
| **Fig 5.3** | Grouped bar chart | Mean travel time by engine                        | Confirms output fidelity          |
| **Fig 5.4** | 3-panel summary   | Runtime, reproducibility, throughput side-by-side | Executive summary                 |
| **Fig 5.5** | Speedup bars      | Engine speedup vs MATSim baseline                 | Cross-simulator comparison        |

### 4.3 Mode Comparison

```bash
python -m evaluation.compare_modes scenarios/chicago_1k_car --seed 42
```

Runs both micro and meso modes on the same scenario and computes:

- **Speedup**: meso runtime ÷ micro runtime
- **Fidelity metrics**: RMSE, GEH, KS-statistic between micro/meso travel time distributions
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

1. **Runtime comparison** (Table 5.1, Fig 5.1):
   - Compare SUMO vs QarSUMO vs MATSim wall-clock times
   - Report speedup of mesoscopic over microscopic
   - Note: QarSUMO without NVIDIA GPU falls back to SUMO (identical performance)

2. **Reproducibility** (Table 5.2, Fig 5.2):
   - R-scores near 1.0 confirm deterministic behavior with seed control
   - Across 3+ seeds, low variance validates reproduciblity claims

3. **Fidelity** (Fig 5.3):
   - Mean travel times should be consistent across engines for the same scenario
   - Mesoscopic travel times are approximations — expect small differences vs microscopic

4. **Throughput** (Fig 5.4 right panel):
   - Trips per second = trip_count / runtime
   - Higher throughput → more scalable for larger scenarios

5. **Cross-simulator speedup** (Fig 5.5):
   - Requires MATSim baseline (MATSim JAR in `lib/matsim-15.0/`)
   - Reports how much faster SUMO/QarSUMO are vs MATSim

### Key thesis claims these results support

| Claim                                          | Evidence                                                |
| ---------------------------------------------- | ------------------------------------------------------- |
| Canonical schema enables fair comparison       | Same scenario runs on all engines with identical demand |
| Mesoscopic mode is 100–1000× faster than micro | Compare_modes speedup ratio                             |
| Results are reproducible                       | R-scores ≥ 0.95 across seeds                            |
| QarSUMO GPU acceleration provides speedup      | QarSUMO vs SUMO runtime (requires NVIDIA GPU)           |
| Framework scales to large scenarios            | Scalability metrics from HPC runs                       |

---

## 7. Known Limitations

- **NYC scenario**: SUMO `netconvert` 1.20.0 segfaults on the NYC network
  (4041 nodes, 8625 links) on Apple Silicon. Works on HPC/Linux.
- **QarSUMO**: Falls back to SUMO if no NVIDIA GPU is detected
  (Apple Silicon Macs have no NVIDIA support).
- **MATSim**: Requires separate JAR installation in `lib/matsim-15.0/`.
- **Microscopic mode**: Very slow for real city networks (>10 min for 1K trips
  on Chicago). Use mesoscopic for quick iteration.

---

## 8. Quick Reference

```bash
# 1. Run benchmark
python run.py --scenario chicago_1k_car --engine sumo,qarsumo \
              --mode meso --repeats 3

# 2. Analyze results
python -m evaluation.analyze_benchmark runs/benchmark_*/benchmark_results.json \
       --latex --markdown

# 3. Generate plots
python -m evaluation.generate_plots runs/benchmark_*/benchmark_results.json \
       --output doc/figures

# 4. Compare micro vs meso
python -m evaluation.compare_modes scenarios/chicago_1k_car

# 5. Run tests
python -m pytest tests/ -q
```
