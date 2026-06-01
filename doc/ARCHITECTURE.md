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
│                           ┌──────────────────────┼─────────┐    │
│                           ▼                      ▼         ▼    │
│                    ┌───────────┐         ┌────────────┐ ┌──────┐ │
│                    │SUMO       │         │MATSim      │ │DTAlite│ │
│                    │Adapter    │         │Adapter     │ │Adpt.  │ │
│                    └─────┬─────┘         └─────┬──────┘ └──┬──┘ │
│                          ▼                     ▼           ▼    │
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

| File           | Schema        | Role                                                            | Key Design Decision                                        |
| -------------- | ------------- | --------------------------------------------------------------- | ---------------------------------------------------------- |
| `network.xml`  | `network_v0`  | Directed graph (nodes + links + V5+ `<turn_restrictions>`)      | IDs are `node_<osm_id>` / `link_<osm_id>` for traceability. V5+ adds `has_signal` per node and a `<turn_restrictions>` block. |
| `demand.csv`   | `demand_v0`   | Trip table (origin, dest, depart, mode + V5+ `purpose`/`dest_source`) | CSV for ease of analysis; departure in seconds. V5+ provenance columns are informational (adapters ignore). |
| `signals.xml`  | `signals_v0`  | Fixed-time 2-phase controllers at OSM-tagged nodes (V5+)        | Simplified to common denominator across all simulators. V5+ Phase 6: placement is OSM-grounded (`has_signal="true"` only). |
| `config.xml`   | `config_v0`   | Scenario metadata + parameters                                  | Engine-agnostic parameters only                            |
| `manifest.xml` | `manifest_v0` | SHA-256 hashes + sizes for all files                            | Hash-based integrity verification                          |

**Why this design:**

- XML for structured, hierarchical data (networks, signals), well-supported by all simulators
- CSV for tabular data (demand), enables pandas analysis, spreadsheet inspection
- SHA-256 manifest prevents accidental corruption and enables cache-based deduplication

### 2.2 Generation Pipeline

Five-stage pipeline from raw data to validated bundle:

```
Stage 1: Network        pipeline/network/build_network_from_osm.py
                        pipeline/network/load_network_from_pbf.py
                        pipeline/network/turn_restrictions.py (V5+)
         OSM PBF (hash-pinned) → single-pass pyosmium scan extracts
         (a) ways for the road graph,
         (b) `highway=traffic_signals` node tags for V5+ signal placement,
         (c) `type=restriction via=node` relations for V5+ turn restrictions.
         → canonical network.xml (with `has_signal` + `<turn_restrictions>`)
         (Overpass API retained as fallback for cities without a committed PBF)

Stage 2: Signals        pipeline/signals/build_signals_default.py
         (V5+ Phase 6) Reads canonical `<node has_signal="true">` set →
         emits a fixed-time 2-phase 90 s controller per OSM-tagged node →
         signals.xml. Pre-V5 bundles fall back to the legacy `degree ≥ 4`
         heuristic with a runtime WARNING.

Stage 3: Demand         pipeline/demand/generate_census_demand.py
         ModelGen data → cityscape JWTRNS mapping (V5+ Phase 5 fix) →
         peak-aware AM/PM split (V5+ Phase 9a) → schedule path
         (real PUMS workplace + parent-with-kid HBSchool chains, V5+
         Phase 9b/9c) + gravity fallback → per-person empirical
         departures (V5+ Phase 8) → demand.csv with V5+ `purpose` and
         `dest_source` provenance columns
         (fallback)     pipeline/demand/generate_synthetic_demand.py
         No ModelGen → uniform random sampling → demand.csv

Stage 4: Config         generate.py::_write_config_xml
         Parameters + metadata → config.xml

Stage 5: Manifest       generate.py::_write_manifest_xml
         Bundle file inventory → manifest.xml
         (validation lives separately in pipeline/validation/validate_bundle.py)
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
    │                  Schedule path (V5+): real PUMS workplace from
    │                  cityscape `schedule[0]` + HBSchool chains for
    │                  parent-with-kid pairs (Phase 9b/c); fallback
    │                  to gravity for the remaining budget.
    │                         │
    │                         ▼
    │                  Gravity fallback: P(dest) ∝ degree × Gaussian(distance|target_km)
    │                         │
    │                         ▼
    │                  Per-person departure (V5+ Phase 8):
    │                    arrival_s − commute_min × 60
    │                  AM/PM peak split when horizon spans both (V5+ Phase 9a)
    │                         │
    ▼                         ▼
network.xml ◀──────── demand.csv (with `purpose` + `dest_source`)
```

### 2.3 Adapter Layer

Each adapter translates the canonical bundle into simulator-specific input format:

```
                  canonical bundle
                        │
            ┌───────────┼───────────┐
            ▼           ▼           ▼
     ┌──────────┐ ┌──────────┐ ┌──────────┐
     │ SUMO     │ │ MATSim   │ │ DTALite  │
     │ Adapter  │ │ Adapter  │ │ Adapter  │
     └────┬─────┘ └────┬─────┘ └────┬─────┘
          ▼            ▼            ▼
     .nod.xml     network.xml  node.csv
     .edg.xml     plans.xml    link.csv
     .rou.xml     config.xml   demand.csv
     .tll.xml                  settings.csv + settings.yml
     .sumocfg
     .net.xml
     (netconvert)
```

**SUMO adapter internals** (most complex):

1. Parse `network.xml` → build adjacency graph
2. Parse `demand.csv` → BFS shortest path for each trip (at conversion time, not simulation time)
3. Generate `.nod.xml`, `.edg.xml`, `.tll.xml` from network + signals
4. Run `netconvert` to produce `.net.xml`
5. Generate `.rou.xml` with full routes (not OD pairs)
6. Write `.sumocfg` referencing all files

**MATSim adapter** translates demand trips into activity-based plans (home → work) with `lastIteration=0` to ensure single-pass execution (fair comparison with SUMO's single-pass simulation).

**DTALite adapter** translates the canonical bundle into the GMNS open standard (`node.csv`, `link.csv`, `demand.csv`) plus `settings.csv` (sections format read by the C++ binary) and `settings.yml` (YAML mirror read by the path4gmns Python wrapper). DTALite runs via the `path4gmns.DTALiteClassic` Python entry point, which dlopens the bundled platform-specific binary (`DTALiteMM_arm.dylib` / `_x86.dylib` / `.so` / `.dll`) and invokes mode 1 (path-based UE). When path4gmns is not installed the adapter raises a clean failure with the install command (`uv pip install path4gmns`). See [`doc/engines/`](engines/) for the full retrospective on LPSim (the GPU comparator that previously occupied this slot, abandoned in Version_5).

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

**RunSpec example** (`runspecs/benchmark_small.yaml`):

```yaml
name: benchmark_large
description: End-to-end stress test across all engines and modes.
output_dir: runs/benchmark_small

runs:
  - scenario_id: chicago_1k_car
    scenario_path: scenarios/chicago_1k_car
    engine: sumo
    mode: mesoscopic
    repeats: 3
    seed: 42
    timeout_s: 300
  # ... four cells total: chicago_1k_car × {SUMO meso, SUMO micro, MATSim meso, DTALite meso}, N=5 each
```

The harness expands each `runs[]` entry into `repeats` individual runs, monotonically incrementing seeds when `seed_increment` is enabled. After execution, `analyze_benchmark.py` and `generate_plots.py` consume the resulting `runs/<name>/benchmark_results_<name>.json`.

### 2.5 Evaluation Metrics

Three metric families, each in a dedicated module:

| Family          | Module                       | Metrics                               | Purpose             |
| --------------- | ---------------------------- | ------------------------------------- | ------------------- |
| Fidelity        | `metrics/fidelity.py`        | RMSE, GEH (batch), KS statistic       | Cross-sim agreement |
| Scalability     | `metrics/scalability.py`     | Wall-clock, throughput, SRT, hardware | Performance         |
| Reproducibility | `metrics/reproducibility.py` | R-index, CV, multi-KPI                | Consistency         |
| Travel Time     | `metrics/travel_time.py`     | Mean, P95, completion rate            | Per-run extraction  |

### 2.6 Visualization Component (Phase 13, separate branch)

Standalone, opt-in module under `visualization/`. Generates geographic
maps from canonical bundles and benchmark results. Lives on the
`visualization` branch and is not imported by any main SimForge code
path, `generate.py`, `run_benchmark.py`, `analyze_benchmark`,
`audit_fairness`, and `generate_plots` are agnostic to it.

```
canonical bundle ──┐
                   ├──► visualization/coverage.py ──► coverage matrix
runs/<runspec>/ ───┘                                      │
                                                          ▼
                                          dispatch by map_type
                                                          │
        ┌─────────────────────────────────────────────────┼─────────────────────────────────────┐
        ▼                                                 ▼                                     ▼
   Phase A maps                                     Phase B maps                          Phase C maps
   (bundle only)                                  (per-engine cell)                    (cross-engine / event)
        │                                                 │                                     │
        ▼                                                 ▼                                     ▼
  od_choropleth.py                               link_load.py                           route_diversity.py
  (od_origins,                                   travel_time.py                         animated_flow.py
   od_destinations)                              (link_load,                            (route_diversity,
                                                  congestion,                            animated_flow)
                                                  travel_time)
```

Seven map types are shipped:

| Map | Phase | Inputs | Engine specificity |
|---|---|---|---|
| `od_origins` / `od_destinations` | A | Bundle (`network.xml` + `demand.csv`) + cached US Census tracts + TIGER roads |, (cross-engine) |
| `link_load` | B | Per-cell engine output | per `(engine, mode)` |
| `congestion` | B | DTALite `link_performance.csv` | DTALite only (needs link mean speed) |
| `travel_time` | B | Per-cell engine output + bundle | per `(engine, mode)` |
| `route_diversity` | C | Cell output from ≥ 2 engines | cross-engine |
| `animated_flow` | C | MATSim `output_events.xml.gz` | MATSim only |

**Data flow per map type:**

```
visualization/data/bundle.py      ─► Network, Demand dataclasses
visualization/data/census.py      ─► TractPolygon list (cb_2024_<fips>_tract_500k.shp)
visualization/data/tiger_roads.py ─► road polylines (tl_2024_<fips>_prisecroads.shp)
visualization/data/osm_ways.py    ─► curved link polylines (sliced from the bundle's PBF)
visualization/data/results.py     ─► LinkPerformance + Trip loaders for SUMO/MATSim/DTALite
visualization/data/events.py      ─► MATSim per-vehicle traversals (for animated_flow particles)
        │
        ▼
visualization/render/<map_type>.py  (matplotlib-only)
        │
        ▼
visualization/output/<scenario>/<map_type>[_<engine>_<mode>].{png,mp4,gif,apng}
```

All `data/` loaders are pure (no matplotlib import); render modules
lazy-import matplotlib + shapely + pyshp. The entire visualization
layer is invisible to anyone who never runs
`python -m visualization.generate_maps`.

**Cross-engine interpretation surfaces.** Three properties visible from
the maps and documented in `visualization/README.md`:

- **SUMO ≈ MATSim, DTALite differs in `link_load`**, same routes
  (SimForge BFS) produce same spatial traffic structure; DTALite's UE
  picks different links. Direct visual proof of the fair-comparison
  contract.
- **`animated_flow` shows departure bursts**, PUMS JWMNP integer-
  minute discretization means 1000 trips share ~20 departure
  timestamps; the bursts are faithful to the data, not a SimForge
  artefact. Cross-referenced with `methods.md` §3.3 step 9.
- **`chicago_200k_car od_origins ≈ od_destinations`**, only the
  full-day scenario emits both AM + PM HBW pairs; origins and
  destinations are then the same set of nodes ({homes} ∪ {workplaces})
  visited at different times.

The component is documented in detail in
[`visualization/README.md`](../visualization/README.md) and consumed by
the post-run pipeline section of
[`doc/RESULTS_GUIDE.md`](RESULTS_GUIDE.md) §4.5.

---

## 3. Module Dependency Graph

```
pipeline/demand/parse_model_file.py     (no deps, pure parser)
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
adapters/dtalite/dtalite_adapter.py
    │ uses: csv, subprocess (path4gmns DTALiteClassic), re, statistics, yaml
    │
    ▼
execution/runspec.py               (YAML/JSON loading, dataclasses)
execution/run_benchmark.py         (uses: runspec, adapters, subprocess, time)
    │
    ▼
evaluation/metrics/fidelity.py      (numpy, scipy.stats)
evaluation/metrics/scalability.py   (time, platform, psutil)
evaluation/metrics/reproducibility.py (statistics)
evaluation/metrics/travel_time.py   (xml.etree, SUMO tripinfo parser)
    │
    ▼  (separate, opt-in, visualization branch)
visualization/data/{bundle,census,events,osm_ways,results,tiger_roads}.py
    │ uses: lxml, csv, pyshp, shapely, pyosmium, gzip
visualization/render/{basemap,od_choropleth,link_load,travel_time,route_diversity,animated_flow}.py
    │ uses: matplotlib (lazy-imported), numpy, shapely
visualization/generate_maps.py + visualization/coverage.py
    └ CLI entrypoint; reads canonical bundle + per-cell engine output
```

**External dependencies** (from `requirements.txt`):

- `osmium` (pyosmium), bbox-slicing of local PBF snapshots
- `osmnx`, parses the sliced XML into a `MultiDiGraph`; also drives the Overpass fallback
- `networkx`, graph operations (pulled in by osmnx)
- `lxml`, XML processing
- `pandas`, demand CSV handling
- `numpy`, numerical computations (metrics)
- `scipy`, KS statistic
- `pyyaml`, RunSpec loading
- `psutil`, hardware detection

---

## 4. Data Flow End-to-End

### 4.1 Scenario Generation Flow

```
User: python generate.py --city chicago --trips 1000 --seed 42
        │
        ▼
[1] Load OSM network (hash-pinned PBF from osm_data/<state>-<date>.osm.pbf;
    bbox computed from city center + radius; pyosmium slices the PBF to a
    reference-complete temp .osm XML via BackReferenceWriter)
        │ → bbox-clipped OSM XML (temp file, not persisted)
        ▼
[2] Parse + simplify (osmnx.graph_from_xml → simplified directed graph,
    then truncate_graph_bbox to clip stub extensions)
        │ → network.xml (1,245 nodes, 2,862 links for chicago_1k_car)
        ▼
[3] Compute largest SCC (pipeline/network/scc.py, iterative Kosaraju)
        │ → SCC node set (1,204/1,245 nodes for chicago_1k_car)
        ▼
[4] Detect signals (OSM highway=traffic_signals nodes)
        │ → signals.xml (2-phase fixed-time controllers)
        ▼
[5] Parse ModelGen (chicago_model.txt → buildings/households/persons)
        │ → buildings restricted to SCC; non-SCC residential dropped
        ▼
[6] Generate demand (V5+: schedule path + gravity fallback on SCC subgraph;
    cityscape JWTRNS mapping; per-person empirical departures from JWMNP;
    AM/PM peak split + HBSchool chains where horizon and demographics fit)
        │ → demand.csv (1,000 trips, V5+ `purpose` + `dest_source`)
        ▼
[7] Write config + manifest (SHA-256 hashes)
        │ → config.xml, manifest.xml
        ▼
[8] Validate bundle (referential integrity + hash check)
        │ → scenarios/chicago_1k_car/ (complete, validated)
```

### 4.2 Simulation Flow

```
User: python run.py --scenario chicago_1k_car --engine sumo --mode meso --seed 42
        │
        ▼
[1] Load manifest → verify file hashes
        │
        ▼
[2] adapters/common/feasibility.py: compute SCC, write feasibility_report.json
        │ → on a correctly-generated bundle the filter is a no-op (defence in depth)
        ▼
[3] SUMO adapter: parse network.xml → state-aware BFS route each trip
    (V5+ Phase 7: avoids forbidden movements per `<turn_restrictions>`,
    falls back to plain BFS when no restriction-respecting path exists)
    → write SUMO files
        │ → runs/<name>/chicago_1k_car/sumo/seed_42/{.net.xml, .rou.xml, .sumocfg}
        ▼
[4] Launch: sumo -c scenario.sumocfg --seed 42 --mesosim
        │ → tripinfo.xml, summary.xml
        ▼
[5] Parse outputs → TripTimeStats(mean, p95, completion)
        │
        ▼
[6] Compute metrics → RunResult(runtime, throughput, travel_times)
```

---

## 5. Design Decisions & Rationale

### 5.1 Why a Canonical Schema?

**Problem**: Each simulator uses a proprietary input format. Direct conversion between N simulators requires N² adapters.

**Solution**: Canonical intermediate representation reduces this to N adapters (one per simulator).

| Approach        | Adapters Needed | Maintenance |
| --------------- | --------------- | ----------- |
| Direct N↔N      | N(N-1) = 6      | Quadratic   |
| Canonical (hub) | N = 3           | Linear      |

(SimForge ships 3 adapters in Version_5: SUMO, MATSim, DTALite.)

### 5.2 Why BFS at Conversion Time?

**Problem**: SUMO requires explicit vehicle routes (sequence of edges), not OD pairs.

**Alternative A**: Use SUMO's `duarouter`, adds external dependency, slower, non-reproducible across SUMO versions.

**Alternative B**: BFS in adapter, deterministic, no external tool, same route regardless of SUMO version.

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

| Test File                         | Tests   | Scope                             |
| --------------------------------- | ------- | --------------------------------- |
| `test_adapter_determinism.py`     | 8       | Byte-identical output across runs |
| `test_sumo_adapter.py`            | 4       | SUMO conversion pipeline          |
| `test_matsim_adapter.py`          | 24      | MATSim adapter unit + integration |
| `test_fidelity_metrics.py`        | 21      | RMSE, GEH, KS computation         |
| `test_metrics_travel_time.py`     | 2       | SUMO tripinfo parsing             |
| `test_reproducibility_metrics.py` | 15      | R-index, multi-KPI analysis       |
| `test_scalability_metrics.py`     | 8       | Timer, throughput, hardware info  |
| `test_validator.py`               | 2       | Bundle validation checks          |
| `test_scenario_data_integrity.py` | 70      | All scenarios × 35 checks each    |
| `test_pipeline_e2e.py`            | 20      | Bad data, routing, robustness     |
| **Total**                         | **174** | **All passing**                   |

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
│  Development (Local)                              │
│  macOS / Apple Silicon / 16 GB                    │
│  → 1K scenarios (< 60 s generation)               │
│  → Full unit suite                                │
│  → SUMO meso + micro, MATSim, DTALite             │
│  → Full 4-cell benchmark matrix runs locally      │
└───────────────────┬──────────────────────────────┘
                    │ git push
                    ▼
┌─────────────────────────────────────────────────┐
│  GitHub                                           │
│  Branch: phase-14-canonical-routes (active), main │
│  + GitHub Actions auto-build → GHCR (Wave 2)      │
└───────────────────┬──────────────────────────────┘
                    │ git clone           │ apptainer pull
                    ▼                     ▼
┌─────────────────────────────────────────────────┐
│  HPC (OSC Pitzer + Cardinal Clusters), optional  │
│  48-core Intel Xeon / 192 GB (Pitzer)             │
│  256-core Xeon Max 9470 / 503 GB (Cardinal)       │
│  → OSM PBFs + ModelGen files rsynced from dev box │
│  → 50K – 500K scenarios (SLURM batch)             │
│  → Full benchmark matrix at scale                 │
│  → All three engines (SUMO, MATSim, DTALite) on cpu partition │
│  → Optional: SIMFORGE_USE_CONTAINER=1 pulls pinned │
│    digest image for bit-identical reproduction    │
└──────────────────────────────────────────────────┘
```

The HPC box uses the same code path and the same `osm_data/manifest.json` hashes as local development, only the job-submission wrapping is cluster-specific. See [doc/PITZER.md](PITZER.md) for the full Pitzer workflow (accounts, modules, rsync, sbatch templates, job monitoring) and [doc/CONTAINER_USAGE.md](CONTAINER_USAGE.md) for the Wave 2 container-mode opt-in.
