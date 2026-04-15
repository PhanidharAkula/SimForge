# SimForge System Architecture

## 1. Overview

SimForge is a cross-simulator benchmarking framework for urban traffic simulation. It decouples scenario authoring from simulator execution through a canonical intermediate representation, enabling fair, reproducible comparison of any simulator that can be adapted.

**Core design principle**: _Write once, simulate anywhere._ A single canonical scenario bundle feeds into any simulator adapter without modification.

```
┌─────────────────────────────────────────────────────────────────┐
│                         SimForge                                │
│                                                                 │
│  ┌──────────────┐   ┌───────────────┐   ┌──────────────────┐   │
│  │  Data Sources │──▶│ Generation    │──▶│ Canonical Bundle │   │
│  │  (OSM, Census,│   │ Pipeline      │   │ (5 XML/CSV files)│   │
│  │   ModelGen)   │   │               │   │                  │   │
│  └──────────────┘   └───────────────┘   └───────┬──────────┘   │
│                                                  │              │
│                           ┌──────────────────────┼──────┐       │
│                           ▼                      ▼      ▼       │
│                    ┌───────────┐  ┌─────────┐  ┌────────────┐   │
│                    │SUMO       │  │QarSUMO  │  │MATSim      │   │
│                    │Adapter    │  │Adapter  │  │Adapter     │   │
│                    └─────┬─────┘  └────┬────┘  └─────┬──────┘   │
│                          ▼             ▼             ▼          │
│                    ┌───────────────────────────────────────┐    │
│                    │         Execution Harness             │    │
│                    │  (RunSpec → benchmark → results.json) │    │
│                    └──────────────────┬────────────────────┘    │
│                                       ▼                        │
│                    ┌───────────────────────────────────────┐    │
│                    │         Evaluation Metrics            │    │
│                    │  (fidelity, scalability, repro.)      │    │
│                    └──────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Subsystem Architecture

### 2.1 Canonical Data Schema

The canonical schema is the lingua franca of SimForge. Every scenario is expressed as a five-file bundle:

| File           | Schema        | Role                                    | Key Design Decision                                        |
| -------------- | ------------- | --------------------------------------- | ---------------------------------------------------------- |
| `network.xml`  | `network_v0`  | Directed graph (nodes + links)          | IDs are `node_<osm_id>` / `link_<osm_id>` for traceability |
| `demand.csv`   | `demand_v0`   | Trip table (origin, dest, depart, mode) | CSV for ease of analysis; departure in seconds             |
| `signals.xml`  | `signals_v0`  | Fixed-time 2-phase controllers          | Simplified to common denominator across all simulators     |
| `config.xml`   | `config_v0`   | Scenario metadata + parameters          | Engine-agnostic parameters only                            |
| `manifest.xml` | `manifest_v0` | SHA-256 hashes + sizes for all files    | Hash-based integrity verification                          |

**Why this design:**

- XML for structured, hierarchical data (networks, signals) — well-supported by all simulators
- CSV for tabular data (demand) — enables pandas analysis, spreadsheet inspection
- SHA-256 manifest prevents accidental corruption and enables cache-based deduplication

### 2.2 Generation Pipeline

Five-stage pipeline from raw data to validated bundle:

```
Stage 1: Network        pipeline/network/build_network_from_osm.py
         OSM → Overpass API → graph → canonical network.xml

Stage 2: Signals        pipeline/signals/build_signals_default.py
         Network nodes → signal detection → 2-phase timing → signals.xml

Stage 3: Demand         pipeline/demand/generate_census_demand.py
         ModelGen data → census calibration → gravity model → demand.csv
         (fallback)     pipeline/demand/generate_synthetic_demand.py
         No ModelGen → uniform random sampling → demand.csv

Stage 4: Config         pipeline/scenariobuilder/
         Parameters + metadata → config.xml

Stage 5: Manifest       pipeline/validation/validate_bundle.py
         Bundle → SHA-256 hashes → manifest.xml → integrity check
```

**Data flow (census-calibrated path):**

```
modelgen/{city}_model.txt
    │
    ▼
parse_model_file.py ──▶ ModelData(buildings, households, persons)
    │                         │
    │                         ▼
    │                  map_buildings_to_nodes()
    │                  (grid spatial index, snap to nearest network node)
    │                         │
    │                         ▼
    │                  Census worker pool (PUMS: JWMNP, JWTRNS)
    │                         │
    │                         ▼
    │                  Gravity model: P(dest) ∝ jobs / dist²
    │                         │
    │                         ▼
    │                  Gaussian departure: N(μ_commute, σ=15min)
    │                         │
    ▼                         ▼
network.xml ◀──────── demand.csv
```

### 2.3 Adapter Layer

Each adapter translates the canonical bundle into simulator-specific input format:

```
                  canonical bundle
                        │
            ┌───────────┼───────────┐
            ▼           ▼           ▼
     ┌──────────┐  ┌─────────┐  ┌──────────┐
     │ SUMO     │  │ QarSUMO │  │ MATSim   │
     │ Adapter  │  │ Adapter │  │ Adapter  │
     └────┬─────┘  └────┬────┘  └────┬─────┘
          ▼              ▼           ▼
     .nod.xml       .nod.xml    network.xml
     .edg.xml       .edg.xml    plans.xml
     .rou.xml       .rou.xml    config.xml
     .tll.xml       .tll.xml
     .sumocfg       .sumocfg
     .net.xml       .net.xml
     (netconvert)   gpu_config.yaml
```

**SUMO adapter internals** (most complex):

1. Parse `network.xml` → build adjacency graph
2. Parse `demand.csv` → BFS shortest path for each trip (at conversion time, not simulation time)
3. Generate `.nod.xml`, `.edg.xml`, `.tll.xml` from network + signals
4. Run `netconvert` to produce `.net.xml`
5. Generate `.rou.xml` with full routes (not OD pairs)
6. Write `.sumocfg` referencing all files

**MATSim adapter** translates demand trips into activity-based plans (home → work) with `lastIteration=0` to ensure single-pass execution (fair comparison with SUMO's single-pass simulation).

**QarSUMO adapter** delegates to SUMO adapter, adds GPU configuration layer. Falls back to SUMO if no CUDA GPU detected.

### 2.4 Execution Harness

The execution harness provides reproducible, instrumented simulation runs:

```
RunSpec (YAML)
    │
    ▼
BenchmarkHarness
    │
    ├── for each scenario × engine × mode × seed:
    │       │
    │       ├── Validate scenario (hash check)
    │       ├── Convert via adapter (if needed)
    │       ├── Start SimulationTimer
    │       ├── Launch simulator subprocess
    │       ├── Collect stdout/stderr
    │       ├── Stop timer → RunResult
    │       └── Extract metrics (travel time, throughput)
    │
    ▼
BenchmarkResult (JSON)
    ├── individual RunResult objects
    ├── aggregated metrics
    └── hardware info (CPU, cores, memory, GPU)
```

**RunSpec example** (`runspecs/benchmark_5k.yaml`):

```yaml
name: benchmark_5k
scenarios:
  - chicago_5k
  - nyc_5k
  - la_5k
engines: [sumo, qarsumo, matsim]
modes: [micro, meso]
seeds: [42, 43, 44]
```

### 2.5 Evaluation Metrics

Three metric families, each in a dedicated module:

| Family          | Module                       | Metrics                               | Purpose             |
| --------------- | ---------------------------- | ------------------------------------- | ------------------- |
| Fidelity        | `metrics/fidelity.py`        | RMSE, GEH (batch), KS statistic       | Cross-sim agreement |
| Scalability     | `metrics/scalability.py`     | Wall-clock, throughput, SRT, hardware | Performance         |
| Reproducibility | `metrics/reproducibility.py` | R-index, CV, multi-KPI                | Consistency         |
| Travel Time     | `metrics/travel_time.py`     | Mean, P95, completion rate            | Per-run extraction  |

---

## 3. Module Dependency Graph

```
pipeline/demand/parse_model_file.py     (no deps — pure parser)
    │
    ▼
pipeline/demand/generate_census_demand.py
    │ uses: parse_model_file, xml.etree (network parsing)
    │
    ▼
pipeline/network/build_network_from_osm.py
    │ uses: osmnx, lxml
    │
    ▼
pipeline/signals/build_signals_default.py
    │ uses: lxml (reads network.xml)
    │
    ▼
pipeline/validation/validate_bundle.py
    │ uses: hashlib, xml.etree, csv
    │
    ▼
adapters/sumo/sumo_adapter.py
    │ uses: xml.etree, csv, subprocess (netconvert), collections.deque (BFS)
    │
adapters/matsim/matsim_adapter.py
    │ uses: xml.etree, csv
    │
adapters/qarsumo/qarsumo_adapter.py
    │ uses: sumo_adapter (delegation), yaml
    │
    ▼
execution/runspec.py               (YAML/JSON loading, dataclasses)
execution/run_benchmark.py         (uses: runspec, adapters, subprocess, time)
    │
    ▼
evaluation/metrics/fidelity.py      (numpy, scipy.stats)
evaluation/metrics/scalability.py   (time, platform, psutil)
evaluation/metrics/reproducibility.py (statistics)
evaluation/metrics/travel_time.py   (xml.etree — SUMO tripinfo parser)
```

**External dependencies** (from `requirements.txt`):

- `osmnx` — OpenStreetMap network extraction
- `lxml` — XML processing
- `pandas` — demand CSV handling
- `numpy` — numerical computations (metrics)
- `scipy` — KS statistic
- `pyyaml` — RunSpec loading
- `psutil` — hardware detection

---

## 4. Data Flow End-to-End

### 4.1 Scenario Generation Flow

```
User: python generate.py --city chicago --trips 5000 --seed 42
        │
        ▼
[1] Download OSM network (Overpass API, bbox from city center + radius)
        │ → raw OSM XML
        ▼
[2] Clean + convert (osmnx → netconvert → simplified graph)
        │ → network.xml (1,248 nodes, 2,871 links for Chicago)
        ▼
[3] Detect signals (OSM highway=traffic_signals nodes)
        │ → signals.xml (925 controllers, 2-phase, 90s cycle)
        ▼
[4] Parse ModelGen (chicago_model.txt → buildings/households/persons)
        │ → 832,750 buildings, ~15K-25K commuters in bbox
        ▼
[5] Generate demand (census-calibrated gravity model)
        │ → demand.csv (5,000 trips, Gaussian departures)
        ▼
[6] Write config + manifest (SHA-256 hashes)
        │ → config.xml, manifest.xml
        ▼
[7] Validate bundle (referential integrity + hash check)
        │ → scenarios/chicago_5k/ (complete, validated)
```

### 4.2 Simulation Flow

```
User: python run.py --scenario chicago_5k --engine sumo --mode meso --seed 42
        │
        ▼
[1] Load manifest → verify file hashes
        │
        ▼
[2] SUMO adapter: parse network.xml → BFS route each trip → write SUMO files
        │ → runs/chicago_5k_sumo_meso_42/{.net.xml, .rou.xml, .sumocfg}
        ▼
[3] Launch: sumo -c scenario.sumocfg --seed 42 --mesosim
        │ → tripinfo.xml, summary.xml
        ▼
[4] Parse outputs → TripTimeStats(mean, p95, completion)
        │
        ▼
[5] Compute metrics → RunResult(runtime, throughput, travel_times)
```

---

## 5. Design Decisions & Rationale

### 5.1 Why a Canonical Schema?

**Problem**: Each simulator uses a proprietary input format. Direct conversion between N simulators requires N² adapters.

**Solution**: Canonical intermediate representation reduces this to N adapters (one per simulator).

| Approach        | Adapters Needed | Maintenance |
| --------------- | --------------- | ----------- |
| Direct N↔N      | N(N-1) = 20     | Quadratic   |
| Canonical (hub) | N = 5           | Linear      |

### 5.2 Why BFS at Conversion Time?

**Problem**: SUMO requires explicit vehicle routes (sequence of edges), not OD pairs.

**Alternative A**: Use SUMO's `duarouter` — adds external dependency, slower, non-reproducible across SUMO versions.

**Alternative B**: BFS in adapter — deterministic, no external tool, same route regardless of SUMO version.

**Chosen**: Alternative B. BFS guarantees byte-identical routes given the same network, regardless of simulator version.

### 5.3 Why MATSim lastIteration=0?

MATSim's replanning loop (default: 100+ iterations) progressively improves routes via agent learning. This makes it incomparable to SUMO's single-pass execution. Setting `lastIteration=0` forces a single pass, enabling fair comparison.

### 5.4 Why CSV for Demand?

| Format  | Pros                          | Cons                       |
| ------- | ----------------------------- | -------------------------- |
| XML     | Consistent with other files   | Verbose for tabular data   |
| CSV     | Simple, pandas-friendly, fast | No schema enforcement      |
| Parquet | Compact, typed                | Requires pyarrow, overkill |

CSV chosen for simplicity, tool compatibility, and human readability.

### 5.5 Why Census-Calibrated Demand?

| Strategy          | Realism | Reproducibility   | Data Required              |
| ----------------- | ------- | ----------------- | -------------------------- |
| Uniform random    | ~20%    | Perfect           | None                       |
| Gravity model     | ~40%    | Perfect           | Node locations             |
| Census-calibrated | ~60-65% | Perfect           | ModelGen files (free)      |
| Real OD data      | ~90%    | Dataset-dependent | StreetLight/Replica ($$$$) |

Census-calibrated balances realism with reproducibility at zero cost.

---

## 6. Testing Architecture

### 6.1 Test Suite Organization

| Test File                         | Tests  | Scope                             |
| --------------------------------- | ------ | --------------------------------- |
| `test_adapter_determinism.py`     | 4      | Byte-identical output across runs |
| `test_fidelity_metrics.py`        | 6      | RMSE, GEH, KS computation         |
| `test_metrics_travel_time.py`     | 5      | SUMO tripinfo parsing             |
| `test_reproducibility_metrics.py` | 7      | R-index, multi-KPI analysis       |
| `test_scalability_metrics.py`     | 6      | Timer, throughput, hardware info  |
| `test_sumo_adapter.py`            | 18     | Full SUMO conversion pipeline     |
| `test_validator.py`               | 11     | Bundle validation checks          |
| **Total**                         | **57** | **All passing**                   |

### 6.2 Determinism Guarantees

The `test_adapter_determinism.py` module runs each adapter twice with the same inputs and asserts byte-identical outputs, verifying:

- No timestamp injection
- No non-deterministic iteration ordering
- No floating-point rounding differences
- No random seed leakage

---

## 7. Deployment Topology

```
┌─────────────────────────────────────────────────┐
│  Development (Local)                             │
│  macOS / Apple Silicon / 16 GB                   │
│  → 5K scenarios (< 30s generation)               │
│  → Unit tests (57/57)                            │
│  → SUMO + MATSim execution                       │
└───────────────────┬─────────────────────────────┘
                    │ git push
                    ▼
┌─────────────────────────────────────────────────┐
│  GitHub (github.com/PhanidharAkula/SimForge)     │
│  Branch: modelgen                                │
└───────────────────┬─────────────────────────────┘
                    │ git clone
                    ▼
┌─────────────────────────────────────────────────┐
│  HPC (OSC Pitzer Cluster)                        │
│  48-core Intel Xeon / 192 GB / V100 GPU          │
│  → 50K-5M scenarios                              │
│  → Full benchmark matrix                         │
│  → QarSUMO GPU experiments                       │
└─────────────────────────────────────────────────┘
```
