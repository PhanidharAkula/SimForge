# Chapter 3: Methods

## 3.1 Overview

This chapter describes the design, implementation, and rationale of **SimForge** — a reproducible, cross-simulator benchmarking framework for urban traffic simulation. The framework addresses three fundamental challenges in simulator comparison that have historically hindered fair, reproducible evaluation of traffic simulation engines:

1. **Input standardization**: Traffic simulators (SUMO, MATSim, DTALite, etc.) use incompatible input formats with different data models, coordinate systems, and semantic interpretations. Direct comparison requires a common input representation.

2. **Execution reproducibility**: Simulation results vary due to hardware differences, software versions, random seed handling, floating-point behavior, and configuration details. A fair comparison requires deterministic, repeatable execution pipelines.

3. **Metric consistency**: Simulators report different output metrics in different formats. A unified metric library is needed to extract comparable measurements from heterogeneous outputs.

SimForge solves these challenges through five interacting subsystems:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SimForge Architecture                        │
│                                                                     │
│  ┌─────────────┐   ┌──────────┐   ┌──────────┐   ┌─────────────┐  │
│  │  Canonical   │──▶│ Scenario │──▶│ Adapter  │──▶│  Execution  │  │
│  │  Schema      │   │ Pipeline │   │  Layer   │   │  Harness    │  │
│  └─────────────┘   └──────────┘   └──────────┘   └──────┬──────┘  │
│                                                          │         │
│                                                          ▼         │
│                                                   ┌─────────────┐  │
│                                                   │  Evaluation  │  │
│                                                   │  Metrics     │  │
│                                                   └─────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

1. **Canonical Data Schema** (§3.2) — simulator-agnostic intermediate representation
2. **Scenario Generation Pipeline** (§3.3) — data sourcing and scenario construction
3. **Simulator Adapter Layer** (§3.4) — deterministic conversion to simulator-native formats
4. **Execution Harness** (§3.5) — controlled benchmark execution with progress tracking
5. **Evaluation Metrics** (§3.6) — fidelity, scalability, and reproducibility measurement

### 3.1.1 Design Goals

| Goal                | Mechanism                                                                         |
| ------------------- | --------------------------------------------------------------------------------- |
| **Fairness**        | Identical canonical inputs → each simulator receives equivalent scenarios         |
| **Reproducibility** | Fixed seeds, sorted outputs, SHA-256 hash verification, exact version pinning     |
| **Extensibility**   | New simulators require only a new adapter implementing a 3-method interface       |
| **Transparency**    | All data sources documented; every transformation traceable from source to output |
| **Scalability**     | Scenarios from 1K to 5M trips; runs on laptop or HPC cluster                      |

The "exact version pinning" claim above has an in-repo artifact:
[`cluster/example_runs/env_report_canonical.txt`](../../cluster/example_runs/env_report_canonical.txt)
captures the byte-identical Mac M4 Pro and Pitzer Linux x86_64 toolchains
(both produced from `requirements.lock` via `uv pip install`). The
`tools/env_report.py` helper regenerates this report locally so any
operator can `diff` against the canonical reference and surface drift.
Lines marked **MUST match** in the canonical file are reproducibility-
critical (Python 3.13.13, osmnx 2.0.7, lxml 6.0.2, SUMO 1.26.0,
path4gmns 0.10.0, …); lines marked as expected to differ (Mac arm64 vs
Linux x86_64 binary paths, host-specific executable paths) are flagged
inline so they are not mistaken for drift.

### 3.1.2 Technology Stack

| Component          | Technology                   | Version | Role                                    |
| ------------------ | ---------------------------- | ------- | --------------------------------------- |
| Core framework     | Python                       | 3.10+   | All pipeline, adapter, and harness code |
| XML processing     | lxml / xml.etree.ElementTree | —       | Canonical and simulator XML I/O         |
| OSM slicing        | pyosmium (libosmium bindings) | 4.0+   | Bbox-slice hash-pinned Geofabrik PBFs   |
| Network extraction | osmnx + networkx             | 2.x     | Parse sliced OSM XML → `MultiDiGraph`   |
| Data processing    | pandas                       | 2.0+    | Demand CSV handling                     |
| Validation         | pydantic                     | 2.0+    | Schema enforcement                      |
| SUMO simulator     | SUMO (eclipse-sumo)          | 1.20.0  | Microscopic + mesoscopic simulation     |
| MATSim simulator   | MATSim                       | 15.0    | Activity-based mesoscopic simulation    |
| MATSim runtime     | Java (OpenJDK)               | 17+     | JVM for MATSim execution                |
| DTALite simulator  | DTALite (bundled in [`path4gmns`](https://github.com/jdlph/Path4GMNS)) | 0.10.0+ | CPU mesoscopic Dynamic Traffic Assignment |
| OpenMP runtime (Mac) | libomp (brew install libomp) | — | DTALite OpenMP runtime on macOS |
| Testing            | pytest                       | 8.0+    | ~574 tests across all subsystems (502 with the 3 tracked bundles) |

> **Engine selection scope deviation.** The original plan listed five engines (SUMO, MATSim, POLARIS, LPSim, QarSUMO). Per advisor agreement and after exhaustive integration work in Versions 4–5, the matrix narrows to **three primary engines** (SUMO microscopic + mesoscopic, MATSim queue-based agent, DTALite mesoscopic Dynamic Traffic Assignment) chosen for paradigm spread. Three of the originally-proposed engines were systematically evaluated and ruled out: **QarSUMO** dropped in Version_4 Phase A (no usable public source — LLNL/QarSUMO 404, QarSUMO/QarSUMO empty placeholder, Boulmakoul 2023 IEEE HPCS paper produced no runnable code; full retrospective in [`doc/engines/QARSUMO_RETROSPECTIVE.md`](../engines/QARSUMO_RETROSPECTIVE.md)); **LPSim** integrated in Version_4 Phase B but abandoned in Version_5 after the bundled GPU binary crashed at network sizes > a few-K nodes and a from-source rebuild SIGSEGV'd at first kernel launch (full retrospective in [`doc/engines/LPSIM_RETROSPECTIVE.md`](../engines/LPSIM_RETROSPECTIVE.md)); **POLARIS** and **CityFlow** evaluated as alternatives during the third-engine selection but ruled out at criteria (POLARIS license-gated, CityFlow scaling-broken — see [`doc/engines/THIRD_ENGINE_OPTIONS.md`](../engines/THIRD_ENGINE_OPTIONS.md)). DTALite (bundled inside [`path4gmns`](https://github.com/jdlph/Path4GMNS), Apache 2.0) was selected on three grounds: bounded integration cost (pre-built binary, working CMake), paradigm-spread value (DTA equilibrium is distinct from SUMO microscopic and MATSim queue-based), and CPU-only execution (the full matrix runs on Mac as well as Linux). See [`doc/engines/ENGINE_COMPARISON.md`](../engines/ENGINE_COMPARISON.md) for the full cross-engine comparison and `todo.md` for the rollout history.

---

## 3.2 Canonical Data Schema

### 3.2.1 Design Principles

The canonical schema serves as a **simulator-neutral intermediate representation** between real-world transportation data and simulator-specific input formats. It is the central innovation of SimForge — by decoupling data preparation from simulator specifics, we ensure that every simulator receives semantically identical inputs.

Design principles:

- **Simulator-agnostic**: No SUMO-specific edge types, no MATSim-specific activity chains, no simulator assumptions in the canonical format
- **Minimal yet complete**: Include only attributes that all target simulators can consume; omit simulator-specific extensions
- **Deterministic conversion**: One canonical input must produce exactly one simulator-native input for a given adapter version
- **Validation-ready**: Schema supports automated cross-file consistency checking (referential integrity, hash verification)
- **Human-readable**: XML with meaningful attribute names; CSV for tabular demand data

### 3.2.2 Schema Overview

Each scenario bundle consists of five canonical files:

| File           | Format | Purpose                                    | Key Contents                                 |
| -------------- | ------ | ------------------------------------------ | -------------------------------------------- |
| `network.xml`  | XML    | Static road infrastructure                 | Nodes (intersections), links (road segments) |
| `demand.csv`   | CSV    | Travel demand (trip table)                 | Origin, destination, departure time, mode    |
| `signals.xml`  | XML    | Traffic signal controllers                 | Junction IDs, phases, cycle lengths          |
| `config.xml`   | XML    | Simulation parameters                      | Time horizon, random seed, units             |
| `manifest.xml` | XML    | File inventory with integrity verification | File list, types, SHA-256 checksums          |

### 3.2.3 Network Schema (`network.xml`)

The network schema defines the static road infrastructure as a **directed graph** $G = (N, L)$ where $N$ is the set of nodes (intersections and endpoints) and $L$ is the set of links (directed road segments).

**Structure:**

```xml
<network>
  <metadata crs="EPSG:4326" units_length="meters" units_speed="m/s" source="OSM"/>
  <nodes>
    <node id="n0" x="-87.6571862" y="41.8950877" type="intersection" osm_id="25779173"/>
    <node id="n1" x="-87.6554321" y="41.8962134" type="dead_end" osm_id="25779198"/>
  </nodes>
  <links>
    <link id="l0" from="n0" to="n1" length="134.5" lanes="2"
          speed_limit="13.9" capacity_veh_per_hour="1800" road_type="residential"/>
  </links>
</network>
```

**Node attributes:**

| Attribute | Type   | Required | Description                                   |
| --------- | ------ | -------- | --------------------------------------------- |
| `id`      | string | Yes      | Unique node identifier (format: `n{index}`)   |
| `x`       | float  | Yes      | Longitude (EPSG:4326) or x-coordinate         |
| `y`       | float  | Yes      | Latitude (EPSG:4326) or y-coordinate          |
| `type`    | string | Yes      | `intersection`, `dead_end`, or `highway_ramp` |
| `osm_id`  | string | No       | Original OpenStreetMap node ID for provenance |

**Link attributes:**

| Attribute               | Type   | Required | Description                                           |
| ----------------------- | ------ | -------- | ----------------------------------------------------- |
| `id`                    | string | Yes      | Unique link identifier (format: `l{index}`)           |
| `from`                  | string | Yes      | Source node ID (must exist in nodes)                  |
| `to`                    | string | Yes      | Target node ID (must exist in nodes)                  |
| `length`                | float  | Yes      | Road segment length in meters                         |
| `lanes`                 | int    | Yes      | Number of lanes (≥ 1)                                 |
| `speed_limit`           | float  | Yes      | Posted speed limit in m/s                             |
| `capacity_veh_per_hour` | int    | No       | Hourly capacity per HCM 2016 (derived if absent)      |
| `road_type`             | string | Yes      | Road classification (motorway, primary, residential…) |
| `osm_way_id`            | string | No       | Original OpenStreetMap way ID                         |

**Design decisions:**

- **Directed links**: Each link is directional. Two-way roads produce two links (one per direction). This matches all three target simulators.
- **EPSG:4326 coordinates**: WGS84 lat/lon avoids projection-specific distortions. Simulators that need projected coordinates (e.g., UTM) handle conversion in their adapters.
- **Speed in m/s**: SI units throughout. OSM `maxspeed` tags in mph/km/h are converted at extraction time.
- **Capacity optional**: Not all simulators use capacity directly. SUMO derives it from lane count and speed; MATSim uses flow capacity per link.

**Typical scale (bundled `chicago_1k_car`, 2 km radius):**

| Metric          | Value                            |
| --------------- | -------------------------------- |
| Nodes           | 1,245                            |
| Links           | 2,862                            |
| Signal controllers | 922                           |
| Largest SCC     | 1,204 nodes (96.7 %), 2,796 links |
| Road types      | 7 (motorway through residential) |

### 3.2.4 Demand Schema (`demand.csv`)

The demand schema defines the travel demand as a **trip table** — a list of individual trips with origin, destination, departure time, and travel mode.

**Format:**

```csv
trip_id,origin_node_id,destination_node_id,departure_time_s,mode
t0,n158,n352,25200,car
t1,n125,n1179,25245,car
t2,n399,n603,25301,transit
```

**Column definitions:**

| Column                | Type   | Required | Description                                       |
| --------------------- | ------ | -------- | ------------------------------------------------- |
| `trip_id`             | string | Yes      | Unique trip identifier (format: `t{index}`)       |
| `origin_node_id`      | string | Yes      | Starting network node (must exist in network.xml) |
| `destination_node_id` | string | Yes      | Ending network node (must exist in network.xml)   |
| `departure_time_s`    | int    | Yes      | Departure time in seconds from simulation start   |
| `mode`                | string | Yes      | Travel mode: `car`, `transit`, `bike`, `walk`     |

**Design decisions:**

- **CSV format**: Tabular trip data scales better in CSV than XML for large scenarios (5M trips would be ~200MB in CSV vs >1GB in XML).
- **Node-level OD**: Origins and destinations reference network nodes, not zones or coordinates. This forces routing responsibility onto the simulator (or adapter).
- **Sorted by departure time**: Trips are sorted ascending by `departure_time_s` to enable streaming consumption by simulators.
- **Mode as string**: Supports multi-modal scenarios. Currently `car`, `transit`, `bike`, `walk` are defined. Adapters map these to simulator-specific vehicle types.

**Demand generation strategies** (detailed in §3.3.4):

| Strategy  | Real Data Used                             | Realism Level |
| --------- | ------------------------------------------ | ------------- |
| Census    | LandScan, PUMS JWMNP/JWTRNS, OSM buildings | Medium-High   |
| Synthetic | Network topology only                      | Low           |

### 3.2.5 Signals Schema (`signals.xml`)

The signals schema defines traffic signal controllers at intersections.

**Structure:**

```xml
<signals>
  <controller junction_id="sig_n100" node_id="n100" cycle_length_s="80">
    <phase phase_id="p0" duration_s="35" state="GGrrr"/>
    <phase phase_id="p1" duration_s="5"  state="yyrrr"/>
    <phase phase_id="p2" duration_s="30" state="rrGGr"/>
    <phase phase_id="p3" duration_s="5"  state="rryyr"/>
    <phase phase_id="p4" duration_s="5"  state="rrrrG"/>
  </controller>
</signals>
```

**Controller attributes:**

| Attribute        | Type   | Description                                     |
| ---------------- | ------ | ----------------------------------------------- |
| `junction_id`    | string | Unique signal controller ID                     |
| `node_id`        | string | Associated network node (must exist in network) |
| `cycle_length_s` | int    | Total cycle length in seconds                   |

**Phase attributes:**

| Attribute    | Type   | Description                                          |
| ------------ | ------ | ---------------------------------------------------- |
| `phase_id`   | string | Unique within controller                             |
| `duration_s` | int    | Phase duration in seconds                            |
| `state`      | string | Signal state per approach (G=green, y=yellow, r=red) |

**Design decisions:**

- **OSM-grounded placement** (V5+): signals are emitted only at network
  nodes that OSM tags as `highway=traffic_signals`. This is community-
  curated ground truth for actual signalized intersections in major US
  cities. Empirical share in the three reference bundles: chicago_1k_car
  2.8 % of network nodes (560 / 20,058), la_50k_car 1.4 % (2,153 /
  159,042). These percentages re-stated against *real* intersections only
  (~25-30 % of OSM nodes are real intersections; the rest are driveways,
  cul-de-sacs, alley junctions) come out to 5-10 %, matching real-world
  signalization rates. Absolute counts also match: LADOT public records
  show ~5,000-6,000 signals across LA County's 10,500 km², which scales
  proportionally to the ~2,000-2,500 expected in the la_50k_car 314 km²
  bbox — landing right where 2,153 sits.
- **2-phase placeholder cycle**: each signalized node receives a 2-phase
  90-second fixed-cycle template (NS green / EW red, then EW green / NS
  red). Real intersections may have 4-8 phases with actuation, lead/lag
  protected lefts, pedestrian phases, and coordinated arterial timing —
  none of which SimForge models. Cross-engine fairness is unaffected
  (every adapter consumes the same `signals.xml`); absolute travel-time
  realism is bounded by the placeholder timing, not the placement.
- **Legacy fallback**: when consuming a network without `has_signal=true`
  attributes (pre-V5 bundles or non-OSM-derived networks), the signal
  generator falls back to a degree heuristic (`degree >= 4`, signalizes
  ~85-90 % of nodes — every junction). The fallback emits a WARNING; for
  realistic signal placement, regenerate the network with the V5+ pipeline.
- **State string encoding**: Compact representation where each character maps to one approach link. SUMO uses the same encoding natively.
- **Node reference**: Every signal controller references a network node, enabling cross-file validation.
- **OSM turn-restriction enforcement (V5+)**: SimForge extracts OSM
  `type=restriction` relations during PBF ingestion and emits them in
  `network.xml` as `<turn_restriction>` entries. The SUMO and MATSim
  adapters pre-route trips via a shared state-aware BFS
  (`pipeline/network/turn_restrictions.py`) that respects these
  restrictions; both engines drive the prescribed restriction-respecting
  path verbatim, so SUMO ↔ MATSim travel-time differences in Q4 reflect
  *only physics* (queue dynamics, signal phasing) rather than routing
  disagreement. The DTALite adapter emits a GMNS-conformant
  `movement.csv` with `capacity=0` per restriction, but path4gmns 0.10.0
  (the DTA backend SimForge runs through) does not yet ingest
  `movement.csv` natively; DTALite's UE assignment may therefore route
  through individually-restricted movements. This is a documented
  V5 cross-engine asymmetry — Q1–Q3 audits remain unaffected (same
  trip set, same network, same target count); Q4's interpretation
  shifts as detailed in `doc/MODELGEN_AND_MODES.md` §9. Closing this
  loop awaits either an upstream path4gmns release that adds
  `movement.csv` ingestion, or in-tree DTALite-network restructuring
  to encode restrictions via via-node splitting (~1 week, deferred).

### 3.2.6 Config Schema (`config.xml`)

Simulation parameters that control execution behavior.

**Structure:**

```xml
<config>
  <metadata scenario_id="chicago_1k_car" version="v0" created="2025-01-15T10:30:00"/>
  <time start_time_s="0" end_time_s="3600"/>
  <parameters random_seed="42"/>
  <schema version="0"/>
</config>
```

**Key parameters:**

| Parameter      | Type   | Description                                                              |
| -------------- | ------ | ------------------------------------------------------------------------ |
| `scenario_id`  | string | Unique human-readable identifier                                         |
| `start_time_s` | int    | Simulation start time (seconds from midnight, or relative)               |
| `end_time_s`   | int    | Simulation end time                                                      |
| `random_seed`  | int    | Master seed for reproducibility (propagated to all stochastic processes) |
| `version`      | string | Schema version for forward compatibility                                 |

### 3.2.7 Manifest Schema (`manifest.xml`)

File inventory with integrity verification via SHA-256 hashes.

**Structure:**

```xml
<manifest>
  <scenario id="chicago_1k_car" schema_version="0"/>
  <canonical_files>
    <file type="network" path="network.xml" sha256="a1b2c3..."/>
    <file type="demand" path="demand.csv" sha256="d4e5f6..."/>
    <file type="signals" path="signals.xml" sha256="g7h8i9..."/>
    <file type="config" path="config.xml" sha256="j0k1l2..."/>
  </canonical_files>
  <generator tool="simforge" version="1.0.0" timestamp="2025-01-15T10:30:00"/>
</manifest>
```

**Purpose**: The manifest enables two critical operations:

1. **Integrity verification**: Recompute SHA-256 of each file and compare to manifest hashes. Detects accidental modification, truncation, or corruption.
2. **Completeness checking**: Verify all required file types are present before simulation.

### 3.2.8 Scenario Validation

The validator (`pipeline/validation/validate_bundle.py`) enforces cross-file consistency through four categories of checks:

| Check Category            | What Is Verified                                                                           | Why It Matters                                       |
| ------------------------- | ------------------------------------------------------------------------------------------ | ---------------------------------------------------- |
| **Structural integrity**  | All required files exist and parse correctly                                               | Prevents runtime failures in simulators              |
| **Referential integrity** | All origin/destination nodes in demand exist in network; all signal nodes exist in network | Ensures demand can be routed on the network          |
| **Schema compliance**     | Required attributes present with valid types                                               | Catches generation bugs before simulation            |
| **Hash verification**     | File contents match SHA-256 hashes in manifest                                             | Detects data corruption or unauthorized modification |

**Validation implementation** (simplified):

```python
def validate_bundle(scenario_path: Path) -> ValidationResult:
    # 1. Load manifest and verify all files exist
    manifest = parse_manifest(scenario_path / "manifest.xml")

    # 2. Extract network node IDs
    network_nodes = extract_node_ids(scenario_path / "network.xml")

    # 3. Check demand references
    for trip in parse_demand(scenario_path / "demand.csv"):
        assert trip.origin_node_id in network_nodes
        assert trip.destination_node_id in network_nodes

    # 4. Check signal references
    for signal in parse_signals(scenario_path / "signals.xml"):
        assert signal.node_id in network_nodes

    # 5. Verify SHA-256 hashes
    for file_entry in manifest.files:
        assert compute_sha256(file_entry.path) == file_entry.sha256
```

**Test coverage**: `test_validator.py` provides the 2 core valid/invalid-bundle unit tests; `test_scenario_data_integrity.py` adds 70 per-bundle integrity checks; `test_pipeline_e2e.py` adds 20 end-to-end pipeline checks (see §3.7.1).

---

## 3.3 Scenario Generation Pipeline

### 3.3.1 Pipeline Architecture

The scenario generation pipeline is a 4-stage process orchestrated by `generate.py` (unified CLI entry point):

```
Stage 1: Network Extraction       → network.xml
Stage 2: Signal Inference          → signals.xml
Stage 3: Metadata Generation       → config.xml + manifest.xml
Stage 4: Demand Generation         → demand.csv
```

Each stage is implemented as an independent Python module that reads from the file system and writes its output. Stages 1-3 run sequentially (signals depend on network); Stage 4 depends on Stage 1 output (network) and optionally on external model files.

**CLI invocation:**

```bash
# Census-calibrated demand (requires model file)
python generate.py --city chicago --trips 5000 --seed 42

# Multi-modal with transit and bike
python generate.py --city la --trips 50000 --modes car,transit,bike --seed 42

# Synthetic fallback (no model file needed)
python generate.py --city chicago --trips 5000 --synthetic --seed 42
```

### 3.3.2 Stage 1: Network Extraction from OpenStreetMap

**Module**: `pipeline/network/build_network_from_osm.py`

**Input**: City name (predefined) or custom bounding box coordinates

**Output**: `network.xml` in canonical format

**Predefined cities:**

| City    | Center (lat, lon)    | Radius | Typical Nodes | Typical Links |
| ------- | -------------------- | ------ | ------------- | ------------- |
| Chicago | (41.8781, -87.6298)  | 4 km   | 1,248         | 2,871         |
| LA      | (34.0522, -118.2437) | 6 km   | 6,333         | 17,685        |
| NYC     | (40.7580, -73.9855)  | 3 km   | 1,913         | 3,877         |

**Pipeline steps:**

1. **Bounding box computation** from center coordinates and radius:
   $$\text{north} = \text{lat} + \frac{r_\text{km}}{111}$$
   $$\text{south} = \text{lat} - \frac{r_\text{km}}{111}$$
   $$\text{east} = \text{lon} + \frac{r_\text{km}}{111 \cdot \cos(\text{lat})}$$
   $$\text{west} = \text{lon} - \frac{r_\text{km}}{111 \cdot \cos(\text{lat})}$$

2. **OSM ingest.** SimForge prefers a hash-pinned, state-level Geofabrik PBF when `osm_data/manifest.json` covers the target bounding box; it falls back to the live Overpass API otherwise.
   - **PBF path (primary).** `pyosmium.FileProcessor(pbf).with_locations()` streams the state PBF and a `BackReferenceWriter` writes a bbox-clipped `.osm.xml` slice without materialising the whole file; `osmnx.graph_from_xml` then parses that slice into a NetworkX directed multigraph and `osmnx.truncate.truncate_graph_bbox` trims boundary-clipped edges. The PBF's SHA-256 + MD5 are validated against `manifest.json` before parsing.
   - **Overpass path (fallback).** `osmnx.graph_from_bbox(...)` with response caching under `cache/`. Used only for cities without a committed PBF.
   - Filters to `highway=*` tags for driveable roads; returns a NetworkX directed multigraph identical in schema regardless of ingest path.
   - Road types included: motorway, trunk, primary, secondary, tertiary, residential, unclassified.

3. **Graph simplification** (performed by osmnx):
   - Merges degree-2 nodes (straight-through segments) into single edges
   - Retains only intersections (degree ≥ 3) and dead-ends (degree 1)
   - Preserves total road length through merged geometry

4. **Attribute extraction and defaulting:**

   | OSM Tag      | Canonical Attribute | Default (if missing)                          |
   | ------------ | ------------------- | --------------------------------------------- |
   | `highway=*`  | `road_type`         | `unclassified`                                |
   | `maxspeed=*` | `speed_limit` (m/s) | By road type (see table below)                |
   | `lanes=*`    | `lanes`             | By road type (see table below)                |
   | `oneway=*`   | Directed links      | Based on highway type (motorways are one-way) |

   **Speed limit defaults** (applied when OSM `maxspeed` tag is absent):

   | Road Type   | Default Speed (mph) | Default Speed (m/s) |
   | ----------- | ------------------- | ------------------- |
   | motorway    | 65                  | 29.1                |
   | trunk       | 55                  | 24.6                |
   | primary     | 45                  | 20.1                |
   | secondary   | 35                  | 15.6                |
   | tertiary    | 30                  | 13.4                |
   | residential | 25                  | 11.2                |

   **Lane count defaults:**

   | Road Type   | Default Lanes |
   | ----------- | ------------- |
   | motorway    | 3             |
   | trunk       | 2             |
   | primary     | 2             |
   | secondary   | 2             |
   | tertiary    | 1             |
   | residential | 1             |

5. **Canonical XML generation**: Nodes and links written with sequential IDs (`n0`, `n1`, ..., `l0`, `l1`, ...), sorted deterministically.

**Realism assessment**: Network structure is **~95% realistic** — derived from GPS-traced, crowd-verified OpenStreetMap data. Speed limits are **~75% realistic** (60% tagged, 40% defaulted). Lane counts are **~60% realistic** (30-40% tagged, rest defaulted).

### 3.3.3 Stage 2: Traffic Signal Inference

**Module**: `pipeline/signals/build_signals_default.py`

**Input**: `network.xml` (Phase 6+ also reads OSM `highway=traffic_signals` tags carried into the canonical bundle)

**Output**: `signals.xml`

**Algorithm (V5+ Phase 6 — OSM-grounded by default):**

1. For each network node carrying an OSM `highway=traffic_signals` tag,
   emit a signalized junction.
2. For each signalized node, generate a **2-phase controller**:
   - Phase 1: Green for one set of approach links (e.g., N/S)
   - Phase 2: Green for orthogonal approach links (e.g., E/W)
   - Yellow and all-red clearance phases included
   - Cycle length is the placeholder 90 s 2-phase template
   - Placement is real (OSM-tagged); timing is synthetic.

**Empirical signal density** at the OSM-tagged nodes: 1.4 – 4.8 % of
nodes (Chicago 2.79 %, NYC 4.80 %, LA 1.35 %; chicago_1k_car emits ~84
controllers in its 2 km radius). See `doc/SCENARIO_GENERATION.md`
§"Step 2: Traffic Signals" for the full provenance.

**Legacy fallback (pre-V5 / synthetic networks without OSM tags):** the
generator uses a degree heuristic — mark nodes with degree ≥ 4 as
signalized, on the assumption that busy intersections tend to have
signals. This produces ~900 controllers for a 4 km urban radius
(Chicago: 925) but is not OSM-grounded and is no longer the default.

**Limitations**: Real traffic signal timing involves:

- Protected left-turn phases
- Pedestrian walk/don't-walk intervals
- Adaptive (actuated) control responding to real-time demand
- Coordinated "green waves" along arterials
- None of these are currently modeled — the timing template is the
  placeholder 90 s cycle described above.

### 3.3.4 Stage 4: Demand Generation

SimForge supports two demand generation strategies:

#### Census-Calibrated Demand (Primary)

**Module**: `pipeline/demand/generate_census_demand.py`

**External dependency**: ModelGen output file (`modelgen/chicago_model.txt`, etc.)

**Data flow:**

```
ModelGen file → parse_model_file.py → generate_census_demand.py → demand.csv
     ↑                                       ↑
     │                                       │
  4 real data sources                  network.xml
  (OSM, LandScan, PUMS, PUMA)         (for spatial matching)
```

**ModelGen data sources** (integrated by the separate C++ ModelGen tool):

| Source                     | What It Provides                            | Scale                  |
| -------------------------- | ------------------------------------------- | ---------------------- |
| OpenStreetMap              | Building locations, footprints, land use    | Every mapped building  |
| LandScan (ORNL)            | Population density at ~1km grid cells       | Global coverage        |
| U.S. Census PUMS (ACS 5yr) | Household demographics, commute data        | ~1% population sample  |
| PUMA Shapefiles (IPUMS)    | Geographic boundaries linking PUMS to areas | 2,378 PUMAs nationwide |

**ModelGen output format** (space-delimited text with 3 record types):

| Record | Fields                                                               | Count (Chicago) |
| ------ | -------------------------------------------------------------------- | --------------- |
| `bld`  | ID, levels, population, is_home, kind, sqft, bbox, way_lat/lon, PUMA | 832,750         |
| `hld`  | bld_ID, PUMS serial, bedrooms, WGTP, HINCP, person_ids               | ~500K+          |
| `per`  | ID, AGEP, WAGP, JWMNP, JWTRNS, schedule                              | ~1M+            |

**Census demand generation algorithm** — schedule-first hybrid:

1. **Parse model file** with geographic filtering to bounding box; extract building, household, and person records along with the per-person activity schedule field added by the cityscape ScheduleGenerator (Rao, [github.com/raodj/cityscape](https://github.com/raodj/cityscape), Schedule-generator branch).
2. **Map buildings to network nodes** using haversine nearest-neighbor with a spatial grid index (O(B log N) via grid bucketing vs O(BN) brute force).
3. **Build population-weighted origin pool**: `weight(node) = Σ building.population` for residential buildings at that node, restricted to the largest strongly-connected component (SCC) of the network.
4. **Validate the schedule-driven pool.** For each person whose cityscape schedule is non-empty, resolve their home building (`ModelData.home_bld_by_per_id[per_id]`) and their workplace building (`schedule[0].bld_id`). Drop the person if any of these fail: home unmapped to a node, home outside SCC, workplace unmapped (orphan or outside bbox), workplace outside SCC, workplace == home. Surviving entries form `valid_scheduled = list[(person, home_node, dest_node)]`.
5. **Peak split (V5+ Phase 9a).** Detect whether the user's horizon spans the AM peak (cityscape arrival 28800 s = 08:00), the PM peak (61200 s = 17:00), or both. Allocate the `--trips N` budget across `n_am_target` and `n_pm_target` accordingly: 50/50 when both peaks are in window, all-AM or all-PM when only one is, default to AM template when neither (rare).

6. **Phase 1a — schedule-driven AM trips.** Deterministically shuffle `valid_scheduled`. For each entry, decide whether the parent emits a chained school drop-off (V5+ Phase 9b) by checking household composition and OSM building kinds:
   - If the household contains at least one member with `0 ≤ AGEP < 18` AND a building with `kind ∈ {school, kindergarten, preschool, college, university}` exists within `_SCHOOL_MAX_KM = 5.0` km of the home, emit a 2-row chain: `home → school` with `purpose = HBSchool_AM` plus `school → work` with `purpose = HBW_AM_chained`. Both rows carry `dest_source = "schedule"` and share the same departure time. Each chain consumes 2 budget slots.
   - Otherwise emit a single `home → work` row with `purpose = HBW_AM`.

   Continue until `n_am_target` is reached or the pool is exhausted.

7. **Phase 1b — schedule-driven PM trips (V5+ Phase 9a/9c).** Symmetric mirror of Phase 1a, but reading `schedule[1]` (17:00 home arrival) and reversing the OD direction:
   - Parent-with-kid + reachable-school case: 2-row chain `work → school` (`HBW_PM_chained`) plus `school → home` (`HBSchool_PM`).
   - Otherwise single `work → home` row with `purpose = HBW_PM`.

8. **Phase 2 — gravity fallback for the remainder.** When the scheduled pool is exhausted (`num_trips > len(valid_scheduled)`) or the chain-fitting check rejects some entries, the remaining trips fall back to the gravity sampler. Sample an origin node by population weight, sample a census person from a building at that origin, then sample a destination over all SCC destination nodes:
   $$P(\text{dest} = j) \propto \text{degree}(j) \cdot \exp\left(-\frac{1}{2}\left(\frac{d_{ij} - d_\text{target}}{\sigma}\right)^2\right)$$
   where $d_\text{target} = \text{JWMNP} \times 0.5$ km and $\sigma = d_\text{target} \times 0.7 + 0.5$. Gravity fallback fills both AM and PM budgets in proportion to remaining slots; each emitted trip carries `dest_source = "gravity"` and `purpose ∈ \{HBW_AM, HBW_PM\}` keyed by the peak being filled.

9. **Departure time per row (V5+ Phase 8).** Pure per-person empirical formula — **no synthetic distribution**:

   $$t_\text{depart} = t_\text{arrival} - \text{JWMNP} \cdot 60$$

   where $t_\text{arrival}$ is the cityscape-emitted arrival for the row's peak (28800 s for AM rows, 61200 s for PM rows; same constants for gravity-fallback rows whose `schedule` is empty). Departures that would fall outside `[t_\text{horizon\_start}, t_\text{horizon\_end} - 1]` clamp to the boundary rather than being dropped (keeps trip counts stable). This replaces the V4 Gaussian peak $t_\text{depart} \sim \mathcal{N}(\mu + \delta, \sigma)$ with $\mu = (t_\text{start} + t_\text{end})/2$, $\sigma = (t_\text{end} - t_\text{start})/6$ — the V4 formula used commute time as a soft offset on a synthetic peak shape; the V5 formula uses commute time as the actual per-person input and the aggregate temporal shape emerges from the JWMNP distribution itself.

   **Discretization caveat.** Census PUMS records JWMNP in **integer minutes**, so the per-person commute is quantised to 60-second steps. Combined with the formula above, every person reporting the same JWMNP value (e.g., a 6-minute commute) lands on the *exact same* `departure_time_s` (e.g., 28440 s = 7:54:00 AM in the AM peak). For chicago_1k_car this collapses 1000 trips onto only 20 distinct departure timestamps; for nyc_10k_car, 10000 trips onto 34 timestamps. The aggregate temporal *shape* (peak hour distribution, JWMNP histogram) is realistic; the per-second departures are not — at 7:00, 7:15, 7:30, 7:54 etc. SimForge releases burst cohorts of trips simultaneously rather than spreading them across a continuous range. This is faithful to PUMS's integer-minute reporting, not a SimForge artefact, but it is visible in the `animated_flow` particle visualization (`visualization/README.md` documents this as the "departure burst" effect). Adding sub-minute uniform jitter to spread bucket-mates across their 60s window is feature-ready in the demand generator but disabled by default to keep `demand.csv` byte-deterministic across regenerations.

10. **Assign mode**: from PUMS JWTRNS using the V5+ corrected mapping (Phase 5 — see table below) if multi-mode, or fixed if single-mode.
11. **Sort by departure time** (with origin/destination secondary keys for stable ordering) and renumber trip IDs sequentially.
12. **Write demand.csv** with columns `trip_id, origin_node_id, destination_node_id, departure_time_s, mode, dest_source, purpose`. Adapters consume the canonical 5-column subset by name; the `dest_source` and `purpose` columns are provenance metadata read only by `evaluation/audit_fairness.py` (Q5) and `evaluation/analyze_benchmark.py` (demand composition table).

**Bundle-level provenance.** `generation_metadata.json` carries a `demand_provenance` block listing `schedule_driven_count`, `gravity_fallback_count`, `schedule_driven_pct`, `scheduled_pool_size`, and `fallback_reasons` (a counter over the validation rejections in step 4). For NYC-500K with the 20 km radius bbox, the scheduled pool covers all 500K trips (100 % schedule-driven). For the small 2 km Chicago bbox most workplaces fall outside the bbox and the scheduled fraction drops accordingly — this is captured per-bundle so the methods chapter never has to hand-wave the realism mix.

**Why the cityscape schedules are more realistic than gravity alone.** Cityscape's `RadiusFilterWorkBuildingAssigner` selects each person's workplace from real non-residential OSM buildings whose predicted travel time matches the person's PUMS-reported commute time (JWMNP) within ±1 minute, subject to per-building office-capacity bounds (`offSqFtPer`). Gravity uses commute time only as a soft weight on a topology-only network node and has no capacity constraint, so it can over-concentrate trips at the gravity peak and routinely puts workplaces in residential cul-de-sacs. The schedule path's destinations are PUMS-derived OD pairs anchored to physical buildings; gravity's destinations are samples from a fitted distribution. Both methods produce demand calibrated to the same JWMNP commute-time distribution; the schedule path additionally preserves *individual* OD identity, not just the aggregate distribution.

**JWTRNS → canonical mode mapping** (cityscape Schedule-generator branch /
ACS PUMS 2021; canonical reference cited at cityscape
`model_gen/ScheduleGenerator.h:211-233`):

| PUMS Code | Cityscape label                | SimForge Mode |
| --------- | ------------------------------ | ------------- |
| 1         | Car, truck, or van             | `car`         |
| 2         | Bus                            | `transit`     |
| 3         | Subway or elevated rail        | `transit`     |
| 4         | Long-distance / commuter rail  | `transit`     |
| 5         | Light rail, streetcar, trolley | `transit`     |
| 6         | Ferryboat                      | `transit`     |
| 7         | Taxicab                        | `car`         |
| 8         | Motorcycle                     | `car`         |
| 9         | Bicycle                        | `bike`        |
| 10        | Walked                         | `walk`        |
| 11        | Worked from home               | excluded      |
| 12        | Other method                   | excluded      |
| -1        | N/A — not a worker             | excluded      |

ACS 2019+ merged the previous "drove alone" + "carpooled" codes into a
single "Car, truck, or van" code 1 (passenger-occupancy detail moved to a
separate variable `JWAP`). See `doc/MODELGEN_AND_MODES.md` §2 for full
provenance and §4 for the bucketing rationale.

#### Synthetic Demand (Fallback)

**Module**: `pipeline/demand/generate_synthetic_demand.py`

Used when no ModelGen file is available. Generates demand from network topology alone.

**Algorithm:**

1. Compute the **largest strongly connected component** (SCC) of the network — ensures all OD pairs are routable
2. Apply a **gravity model**:
   $$P(\text{trip from } i \text{ to } j) \propto \frac{\text{degree}(i) \cdot \text{degree}(j)}{d(i,j)^\beta}$$
   with $\beta = 2.0$ (distance decay exponent) and minimum distance 0.5 km
3. Departure times: **uniform random** within the time window (no census calibration)

**Comparison with census mode:**

| Feature              | Census Mode (schedule-first hybrid)                                | Synthetic Mode        |
| -------------------- | ------------------------------------------------------------------ | --------------------- |
| Origin               | Person's actual PUMS home building → nearest network node          | Node degree           |
| Destination (primary)| Cityscape PUMS-derived workplace `bld_id` (real non-home building) | Topology-only gravity |
| Destination (fallback)| Commute-calibrated gravity (when person has no usable schedule)   | (n/a)                 |
| Departure times      | **Per-person empirical**: $t_\text{depart} = t_\text{arrival} - \text{JWMNP} \cdot 60$ (V5+ Phase 8) | Uniform random        |
| Mode assignment      | PUMS JWTRNS                                                         | Fixed (car only)      |
| External data needed | ModelGen + cityscape ScheduleGenerator output (~300 MB per city)   | None                  |
| Per-trip provenance  | `dest_source` + `purpose` columns (V5+) + `demand_provenance` metadata block | None        |
| Trip purposes (V5+)  | `HBW_AM` / `HBW_PM` (commutes) + `HBSchool_AM/PM` (parent-with-kid chains) + `HBW_AM/PM_chained` (chain continuation legs) | Untagged |

---

## 3.4 Simulator Adapter Layer

### 3.4.1 Adapter Architecture

Each adapter implements a common operational pattern:

```python
class SimulatorAdapter(Protocol):
    def prepare_inputs(self, scenario_path: Path, output_dir: Path) -> None:
        """Convert canonical bundle to simulator-specific inputs."""

    def run_simulation(self, config_path: Path, **kwargs) -> SimulationResult:
        """Execute the simulator and return results."""

    def parse_outputs(self, output_dir: Path) -> SimulationMetrics:
        """Extract metrics from simulator outputs."""
```

**Conversion guarantees:**

- **Deterministic**: Given the same canonical input and adapter version, the output is byte-identical
- **Lossless (within schema)**: All canonical attributes are mapped; no information is dropped
- **Documented**: Every mapping decision is recorded in `adapters/<engine>/MAPPING.md`
- **Cross-engine vehicle alignment** (V11+): All three adapters source vehicle parameters from a single shared module `adapters/common/vehicle_types.py`. Pre-V11 each adapter declared its own values inline (SUMO inherited the implicit `DEFAULT_VEHTYPE`, MATSim hardcoded `length=7.5` and `width=1.0`), with the cross-engine equivalence undocumented and untested. The canonical SimForge car is now a 5.0 m sedan with a 2.5 m gap, 1.8 m wide, 40 m/s max speed, PCE 1.0. SUMO emits `length="5.0" minGap="2.5"` (physical convention); MATSim emits `<length meter="7.5"/>` (effective-spacing convention = SUMO's length + minGap); DTALite consumes `PCE = 1.0` (link-capacity convention). The equivalence is pinned by `tests/test_vehicle_types.py::TestCrossEngineEquivalence`. Within-bucket heterogeneity (motorcycles, taxis, freight) is post-V11 work and remains a documented limitation.

### 3.4.2 SUMO Adapter

**Simulator**: SUMO (Simulation of Urban Mobility) — microscopic traffic simulator modeling individual vehicles with car-following (Krauss model) and lane-changing behavior.

**Supported modes**: Microscopic (default) and Mesoscopic (queue-based, ~100× faster)

**Conversion pipeline:**

```
CANONICAL                           SUMO
────────────────────────────────────────────────
network.xml  ──► nodes.nod.xml ─┐
                 edges.edg.xml ─┴─► netconvert ──► net.net.xml
demand.csv   ──► routes.rou.xml (with BFS routing)
signals.xml  ──► (embedded in net.net.xml via netconvert)
config.xml   ──► scenario.sumocfg
```

**Key mapping decisions:**

| Canonical                 | SUMO                | Transformation                                    |
| ------------------------- | ------------------- | ------------------------------------------------- |
| `node (x, y)`             | `node (x, y, type)` | x=lon, y=lat; type defaults to `priority`         |
| `link (from, to, length)` | `edge + lanes`      | One edge per link; numLanes, speed from canonical |
| `link.speed_limit`        | `edge.speed`        | Direct copy (both in m/s)                         |
| `link.lanes`              | `edge.numLanes`     | Direct copy                                       |
| Trip (origin, dest)       | Vehicle with route  | State-aware BFS shortest path on node graph (V5+ Phase 7) → edge sequence |
| `config.random_seed`      | `--seed` CLI arg    | Passed to sumo/sumo-gui                           |

**State-aware BFS routing (V5+ Phase 7)**: The SUMO adapter computes shortest paths at conversion time (not at simulation time). For each trip in demand.csv:

1. Build the forbidden-move set from the `<turn_restrictions>` block in `network.xml` via `pipeline/network/turn_restrictions.build_forbidden_moves`.
2. Run state-aware BFS from `origin_node_id` to `destination_node_id` over `(node, last_link)` states — never traversing a `(from_link, via_node, to_link)` triple in the forbidden set. Implemented at `pipeline/network/turn_restrictions.shortest_path_with_restrictions`.
3. Fall back to plain BFS if no restriction-respecting path exists (rare; SCC-feasible by construction).
4. Convert the node path to an edge sequence via the `edge_lookup` dictionary.
5. Write as `<vehicle id="veh_t0" depart="25200"><route edges="l0 l1 l2"/></vehicle>`.

The MATSim adapter uses the same state-aware BFS to pre-route every plan and writes a `<route type="links" start_link="..." end_link="...">interior</route>` per the MATSim 15 **population_v6** DTD (corrected from plans_v4 in V11.2 — plans_v4's `<route>` element rejects `type="links"` and treats text content as a node sequence; population_v6 supports both natively). The DTALite adapter emits a sibling `movement.csv` with forbidden movements (capacity = 0, penalty = 99999) but path4gmns 0.10.0 does not natively ingest it — a documented cross-engine asymmetry. Trips with no valid path (disconnected OD pairs) are skipped and logged.

**Mesoscopic mode**: Activated via `--mesosim` flag in SUMO configuration. Uses queue-based link traversal instead of car-following. Dramatically faster for large scenarios (100-1000× speedup at 500K+ trips) with lower fidelity.

**netconvert invocation:**

```bash
netconvert --node-files nodes.nod.xml \
           --edge-files edges.edg.xml \
           --output-file net.net.xml \
           --no-turnarounds
```

### 3.4.3 MATSim Adapter

**Simulator**: MATSim (Multi-Agent Transport Simulation) — activity-based, mesoscopic simulator modeling agents executing daily activity plans.

**Conversion pipeline:**

```
CANONICAL                           MATSIM
────────────────────────────────────────────────
network.xml  ──► network.xml (MATSim DTD format)
demand.csv   ──► plans.xml (2-activity chains)
config.xml   ──► config.xml (MATSim config format) + vehicles.xml
```

**Key mapping decisions:**

| Canonical       | MATSim                        | Notes                                                 |
| --------------- | ----------------------------- | ----------------------------------------------------- |
| Node (x, y)     | Node with coords              | Coordinates preserved as-is                           |
| Link            | Link with freespeed, capacity | `freespeed = speed_limit`; capacity from lanes × 1800 |
| Trip (OD, time) | Person with 2-activity plan   | home(origin) → work(destination)                      |
| Mode            | Leg mode                      | car/transit/bike mapped to MATSim modes               |
| Random seed     | `config/global/randomSeed`    | Propagated to MATSim config XML                       |

**Demand conversion**: Each canonical trip becomes a MATSim agent with a 2-activity plan:

```xml
<person id="person_t0">
  <plan selected="yes">
    <activity type="home" link="l_near_origin" end_time="07:00:00"/>
    <leg mode="car"/>
    <activity type="work" link="l_near_destination"/>
  </plan>
</person>
```

**Single-iteration mode**: For fair comparison with SUMO, MATSim is configured with `lastIteration=0`, disabling the iterative replanning loop that MATSim normally uses to reach user equilibrium.

**Java/JAR detection**: The adapter auto-detects the Java runtime and MATSim JAR location:

1. Checks `JAVA_HOME`, then `PATH`, then common install locations
2. Locates `matsim-15.0.jar` in the `lib/` directory
3. Constructs classpath including all dependency JARs

| Aspect                | SUMO          | MATSim                         |
| --------------------- | ------------- | ------------------------------ |
| Resolution            | Vehicle-level | Agent-level                    |
| Demand representation | OD routes     | Activity plans                 |
| Traffic flow          | Car-following | Queue-based (mesoscopic)       |
| Typical iterations    | 1             | 1 (forced for fair comparison) |
| Startup overhead      | ~0.1s         | ~5-7s (JVM warmup)             |

### 3.4.4 DTALite Adapter

**Simulator**: DTALite — CPU-only mesoscopic Dynamic Traffic Assignment engine distributed under Apache 2.0 license, bundled inside the [`path4gmns`](https://github.com/jdlph/Path4GMNS) Python package. Replaces LPSim in the third-engine slot in **Version_5** after the LPSim integration was abandoned (see [`doc/engines/LPSIM_RETROSPECTIVE.md`](../engines/LPSIM_RETROSPECTIVE.md)). The selection rationale and the two ruled-out alternatives (CityFlow, POLARIS) are documented in [`doc/engines/THIRD_ENGINE_OPTIONS.md`](../engines/THIRD_ENGINE_OPTIONS.md).

**Conversion** (Canonical → GMNS schema):

| File | Canonical | DTALite (GMNS) |
|---|---|---|
| Nodes | `network.xml` `<node id="n123" x="…" y="…"/>` | `node.csv` columns `node_id, zone_id, x_coord, y_coord, production, attraction` |
| Edges | `network.xml` `<link id="l456" from="n10" to="n11" length="120.5" speed_limit="13.9" lanes="2"/>` | `link.csv` columns `link_id, from_node_id, to_node_id, length (km), lanes, free_speed (km/h), capacity, link_type, VDF_fftt1, VDF_alpha1, VDF_beta1` (m → km, m/s × 3.6 → km/h) |
| Demand | `demand.csv` `trip_id, origin_node_id, destination_node_id, departure_time_s, mode` | `demand.csv` columns `o_zone_id, d_zone_id, volume` (trips aggregated by OD pair) |
| Config | `config.xml` `<time start_time_s="25200" end_time_s="28800"/>` | `settings.csv` (`[demand_period]` AM 0700_0800) + `settings.yml` mirror for the path4gmns Python wrapper |

**Demand-driven zoning**: DTALite's UE assignment iterates over zones, running label-correcting shortest-path from each zone in every outer iteration. Treating every node as a zone (the naive approach) produced 20,058-zone runs that took minutes per outer iteration on chicago_1k_car. The adapter therefore promotes only nodes that appear as origin or destination in the demand to GMNS zones (~1,800 zones for chicago_1k_car); transit-only intersections retain network connectivity but are skipped in the UE loop. Runtime drops from "minutes" to ~5 seconds at the bundled scenario size.

**Fidelity trade-off — departure timing**: DTALite's GMNS demand format does not include a per-trip departure column; trips are aggregated by (origin, destination) into a count `volume`. Departures are distributed uniformly inside the `[demand_period]` window (default 0700-0800 — controlled by `DTALiteConfig`). The canonical `departure_time_s` precision available to SUMO and MATSim is therefore not exposed to DTALite. This is the single cleanest difference between the three engines from a demand-modeling perspective and is documented in `adapters/dtalite/MAPPING.md` for full audit trail.

**Determinism**: DTALite is fully deterministic. The UE algorithm (Method of Successive Averages / Frank-Wolfe) iterates in fixed order with no atomic reductions and no GPU non-determinism. R-score is expected to be 1.0 across N=5 repeats with the same inputs, matching SUMO mesoscopic and MATSim with `lastIteration=0`. (This determinism is one of the technical reasons DTALite was preferred over LPSim, whose `atomicAdd` GPU reductions would have forced an explanatory footnote on every reproducibility number — see `LPSIM_RETROSPECTIVE.md` §5.)

**Binary discovery**: `is_dtalite_available()` checks both that `path4gmns` is importable AND that the platform-specific bundled binary (`DTALiteMM_arm.dylib` / `DTALiteMM_x86.dylib` / `DTALiteMM.so` / `DTALiteMM.dll`) exists in the package's `bin/` directory. With path4gmns not installed, `run_dtalite()` returns a clean `RunResult` failure with the install command (`uv pip install path4gmns`) — no silent fallback (the failure mode that motivated dropping QarSUMO).

**Implementation note** — DTALiteClassic vs DTALiteMultimodal: path4gmns 0.10.0 ships two DTALite binaries. The adapter calls `DTALiteClassic` (mode 1 = path-based UE), not the newer `DTALiteMultimodal` wrapper. The multimodal binary has a regression demanding a `mode_type.csv` schema upstream has not published — even path4gmns's own bundled samples fail with `[ERROR] File mode_type does not have information` when invoked fresh. Full implementation note in `adapters/dtalite/MAPPING.md`.

**Performance expectation**: at SimForge scenario sizes (1k–500k trips, ≤500k nodes) DTALite is comparable to MATSim in wallclock — slower than SUMO meso, faster than SUMO micro at scale. The thesis claim is paradigm spread (microscopic + queue-based agent + DTA equilibrium), not raw speedup; see `doc/engines/ENGINE_COMPARISON.md` §3 for the per-tier wallclock estimates.

### 3.4.5 Adapter Determinism

All adapters enforce deterministic output through:

1. **Sorted iteration**: All XML elements emitted in sorted order (by node ID, link ID, etc.) — avoids hash-set iteration order differences
2. **Fixed random seeds**: The canonical `random_seed` from config.xml is propagated to all simulator-level random seed parameters
3. **Version pinning**: Adapter code is versioned alongside the framework; simulator versions are recorded in metadata
4. **Hash verification**: Post-conversion, the adapter can re-validate that canonical inputs haven't drifted since scenario generation

---

## 3.5 Execution Harness

### 3.5.1 Run Specification Schema

Benchmark runs are defined via YAML runspec files that specify the experimental matrix:

```yaml
name: stress_test
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

  - scenario_id: chicago_1k_car
    scenario_path: scenarios/chicago_1k_car
    engine: matsim
    mode: mesoscopic
    repeats: 2
    seed: 42
    timeout_s: 600
```

**RunConfig fields:**

| Field           | Type   | Description                                            |
| --------------- | ------ | ------------------------------------------------------ |
| `scenario_id`   | string | Human-readable scenario identifier                     |
| `scenario_path` | string | Path to canonical scenario bundle                      |
| `engine`        | string | Simulator: `sumo`, `matsim`, `dtalite`                 |
| `mode`          | enum   | `microscopic` or `mesoscopic`                          |
| `repeats`       | int    | Number of repeated runs (for reproducibility analysis) |
| `seed`          | int    | Base seed (incremented per repeat: 42, 43, 44)         |
| `timeout_s`     | int    | Maximum wall-clock time per run                        |

**SimulationMode enum:**

```python
class SimulationMode(str, Enum):
    MICROSCOPIC = "microscopic"  # Car-following + lane-changing (accurate, slow)
    MESOSCOPIC = "mesoscopic"    # Queue-based edge traversal (fast, ~100× speedup)
```

### 3.5.2 Benchmark Execution Pipeline

The `BenchmarkHarness` orchestrates the full execution lifecycle:

```
For each (scenario, engine, mode, seed):
    1. Validate canonical bundle  ──► abort if invalid
    2. Prepare simulator inputs   ──► adapter.prepare_inputs()
    3. Execute simulation         ──► adapter.run_simulation()
    4. Collect raw outputs        ──► tripinfo.xml, summary.xml, etc.
    5. Compute metrics            ──► adapter.parse_outputs()
    6. Record RunResult           ──► JSON serializable
```

**Progress tracking**: The `StickyProgress` bar displays real-time progress with completion ratio, ✓/✗ counts, elapsed clock, and a Braille spinner heartbeat (V11.2+ removed the ETA estimate — SimForge cells are heterogeneous, so a running-mean ETA swings between unhelpful extremes):

```
[████████████████████░░░░░░░░░░░░░░░░░░░░] 52.3%  ⠼  47/90 runs  ✓45 ✗2  elapsed 12m 30s
```

**Output structure:**

```
runs/
└── benchmark_20250615_143022/
    ├── chicago_1k_car_sumo_meso_seed42/
    │   ├── net.net.xml
    │   ├── routes.rou.xml
    │   ├── scenario.sumocfg
    │   └── output/
    │       ├── tripinfo.xml
    │       └── summary.xml
    ├── chicago_1k_car_matsim_meso_seed42/
    │   ├── network.xml
    │   ├── plans.xml
    │   ├── config.xml
    │   └── output/
    │       └── output_events.xml.gz
    └── benchmark_results_<runspec>.json
```

### 3.5.3 Result Aggregation

All run results are serialized to `benchmark_results_<runspec>.json`:

```json
{
  "runspec_name": "stress_test",
  "started_at": "2026-04-19T02:05:28+00:00",
  "completed_at": "2026-04-19T02:06:19+00:00",
  "total_runs": 22,
  "successful_runs": 22,
  "failed_runs": 0,
  "results": [
    {
      "scenario": "chicago_1k_car",
      "engine": "sumo",
      "mode": "meso",
      "seed": 42,
      "status": "success",
      "runtime_s": 0.279,
      "metrics": {
        "travel_time": {
          "mean": 204.18,
          "p95": 406.0,
          "trip_count": 996
        }
      }
    }
  ]
}
```

---

## 3.6 Evaluation Metrics

### 3.6.1 Metric Categories

The evaluation framework measures three orthogonal quality dimensions:

| Dimension           | Question                                                   | Metrics                   |
| ------------------- | ---------------------------------------------------------- | ------------------------- |
| **Fidelity**        | How closely do simulators agree with each other?           | RMSE, GEH, KS statistic   |
| **Scalability**     | How efficiently does each simulator use compute resources? | Runtime, throughput, SRT  |
| **Reproducibility** | How consistent are results across repeated runs?           | Reproducibility index $R$ |

### 3.6.2 Fidelity Metrics

**Root Mean Square Error (RMSE):**

$$\text{RMSE} = \sqrt{\frac{1}{n}\sum_{i=1}^{n}(y_i - \hat{y}_i)^2}$$

Applied to link-level traffic counts or travel times across two simulators. Lower RMSE indicates closer agreement. Units match the input (seconds for travel time, vehicles for counts).

**GEH Statistic** (Geoffrey E. Havers):

$$\text{GEH} = \sqrt{\frac{2(M - C)^2}{M + C}}$$

where $M$ is the modeled value and $C$ is the comparison/observed value. Standard in traffic engineering (UK DfT, FHWA):

| GEH Range | Interpretation         | Action                 |
| --------- | ---------------------- | ---------------------- |
| < 5       | Acceptable fit         | No action needed       |
| 5 – 10    | Warrants investigation | Check individual links |
| > 10      | Poor fit               | Model needs revision   |

The implementation computes per-link GEH and reports both the **mean GEH** and the **percentage of links with GEH < 5** (the industry-standard acceptance criterion).

**Kolmogorov-Smirnov Statistic:**

$$D = \sup_x |F_1(x) - F_2(x)|$$

Compares the empirical cumulative distribution functions (CDFs) of travel time distributions from two simulators. Critical value at significance level $\alpha = 0.05$:

$$D_{\text{crit}} = 1.36 \sqrt{\frac{n_1 + n_2}{n_1 \cdot n_2}}$$

If $D > D_{\text{crit}}$, the distributions are statistically different at the 5% level.

### 3.6.3 Scalability Metrics

**Wall-clock runtime**: Measured via `time.perf_counter()` context manager for nanosecond precision:

```python
class SimulationTimer:
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
    def __exit__(self, *args):
        self.elapsed_seconds = time.perf_counter() - self.start_time
```

**Throughput:**

$$\text{Throughput} = \frac{\text{vehicles completed}}{\text{wall-clock seconds}}$$

Units: vehicles/second. Higher is better. Enables direct comparison across hardware.

**Simulated-to-Real-Time ratio (SRT):**

$$\text{SRT} = \frac{T_\text{simulated}}{T_\text{wall-clock}}$$

SRT > 1 means the simulator is faster than real time. SRT = 10 means 1 hour of traffic simulated in 6 minutes.

**Normalized throughput** (when hardware info available):

$$\text{Throughput}_\text{core} = \frac{\text{Throughput}}{\text{CPU cores}}$$

$$\text{Throughput}_\text{watt} = \frac{\text{Throughput}}{\text{TDP (watts)}}$$

**Hardware detection**: The framework auto-detects CPU model, core count, and memory via platform APIs.

### 3.6.4 Reproducibility Metric

**Coefficient of Reproducibility:**

$$R = 1 - \frac{\sigma}{\mu}$$

where $\sigma$ is standard deviation and $\mu$ is mean of a KPI across repeated runs with different random seeds.

| $R$ Range            | Interpretation                 |
| -------------------- | ------------------------------ |
| $R \geq 0.99$        | Excellent (near-deterministic) |
| $0.95 \leq R < 0.99$ | Very good                      |
| $0.90 \leq R < 0.95$ | Good                           |
| $0.80 \leq R < 0.90$ | Acceptable                     |
| $0.50 \leq R < 0.80$ | Marginal                       |
| $R < 0.50$           | Poor                           |

**Multi-KPI analysis**: The `MultiKPIReproducibility` class computes $R$ across multiple KPIs (mean travel time, p95 travel time, throughput, etc.) and reports the **overall reproducibility** as the average $R$ across all KPIs.

**Edge case handling:**

- All values identical → $R = 1.0$ (perfect reproducibility)
- Mean near zero → special handling to avoid division instability
- Fewer than 2 runs → error (meaningless without repetition)

### 3.6.5 Travel Time Extraction

The `travel_time` module parses simulator-specific output files to extract trip-level metrics:

**SUMO tripinfo.xml parsing:**

```xml
<tripinfo id="veh_t0" depart="25200.00" departDelay="0.00"
          arrival="25445.30" duration="245.30" routeLength="3240.1"/>
```

Extracted fields: `duration` (travel time in seconds) for each completed trip.

**Computed statistics:**

| Statistic             | Formula                                      |
| --------------------- | -------------------------------------------- |
| Mean travel time      | $\bar{t} = \frac{1}{n}\sum_i t_i$            |
| P95 travel time       | 95th percentile of sorted durations          |
| Trip completion count | Number of trips with arrival time < end_time |

---

## 3.7 Implementation Quality

### 3.7.1 Test Suite

The framework includes **~574 tests** with all 5 bundles generated
(or **~502** with just the 3 tracked bundles `chicago_1k_car`,
`nyc_10k_car`, `la_50k_car`). The base count is 394 tests + 36
parametrized integrity tests per bundle in `scenarios/`, so
generating the two larger benchmark tiers (`chicago_200k_car`,
`nyc_500k_car`) lifts the count from 502 to 574.

| Test Module                       | Tests | What It Validates                                       |
| --------------------------------- | ----- | ------------------------------------------------------- |
| `test_adapter_determinism.py`     | 8     | Byte-identical outputs from identical inputs            |
| `test_sumo_adapter.py`            | 4     | SUMO conversion: network, routes, config                |
| `test_matsim_adapter.py`          | 26    | MATSim adapter (incl. Phase 12.1 route-text format pin) |
| `test_fidelity_metrics.py`        | 21    | RMSE, GEH, KS computation correctness                   |
| `test_metrics_travel_time.py`     | 2     | SUMO tripinfo parsing                                   |
| `test_reproducibility_metrics.py` | 15    | R-index computation, edge cases, interpretation         |
| `test_scalability_metrics.py`     | 8     | Timer, throughput, hardware detection                   |
| `test_validator.py`               | 2     | Bundle validation: valid and invalid bundles            |
| `test_scenario_data_integrity.py` | 36 × N | 7 classes × 36 tests/scenario × N bundles in `scenarios/` (108 for 3 tracked, 180 for all 5) |
| `test_pipeline_e2e.py`            | 20    | Bad data detection, routing, adapter robustness         |
| `test_scc.py`                     | 14    | Iterative Kosaraju + parsing                            |
| `test_feasibility.py`             | 19    | Shared cross-engine trip filter + V5 mode-aware feasibility |
| `test_analyze_benchmark.py`       | 24    | Mode-aware grouping + Phase 10 demand composition table |
| `test_audit_fairness.py`          | 40    | Q1–Q5 audit helpers + 5-layout detector (Phase 12+ mode-segmented + back-compat fallbacks) |
| `test_run_benchmark.py` (Phase 12+) | 12  | BenchmarkHarness explicit-output, prep-cache, bundle-hash invalidation, scoped_base collapse (Phase 12.2) |
| `test_confidence.py`              | 18    | Student's-t 95 % CI core + edge cases                   |
| `test_osm_fetch.py`               | 20    | OSM/Overpass fetch (mocked), bbox validation, cache pin |
| `test_demand_generators.py`       | 21    | Uniform/gravity/peak-hour generators, SCC restriction   |
| `test_demand_composition.py` (V5+ Phase 10) | 7 | `purpose` column tally, AM/PM peak split, pre-V5 graceful no-op |
| `test_parse_model_file.py`        | 27    | ModelGen parser + V5 Phase 5 JWTRNS mapping + Phase 9 HBSchool helpers |
| `test_turn_restrictions.py` (V5+ Phase 7) | 17 | OSM restriction parser, forbidden-move builder, state-aware BFS, DTALite movement.csv |
| `test_vehicle_types.py` (V5+ Phase 11) | 19 | Canonical car constants, SUMO/MATSim XML emission, cross-engine equivalence |
| `test_dtalite_adapter.py`         | 46    | DTALite adapter: writers, settings, demand-driven zoning, determinism, output parsing, end-to-end smoke |
| `test_engine_smoke.py`            | 4     | Real-binary smoke on SUMO/MATSim/DTALite                |

**All ~574 tests passing** with all 5 bundles as of Version_5
Phase 12.2 (or ~502 with just the 3 tracked bundles). Marker registry
in `pyproject.toml`; shared fixtures in `tests/conftest.py`. Line
coverage sits at **76 %** across the adapter, pipeline, and evaluation
packages; the local gate enforces ≥70 % via
`pytest --cov --cov-fail-under=70`.

### 3.7.2 Determinism Guarantees

| Mechanism                       | What It Ensures                                                                                  |
| ------------------------------- | ------------------------------------------------------------------------------------------------ |
| Fixed random seeds              | All stochastic processes seeded via config.xml `random_seed`                                     |
| Sorted outputs                  | All XML/CSV files use sorted iteration over sets/dicts                                           |
| SHA-256 hashes                  | Manifest checksums detect any input drift                                                        |
| Version pinning                 | `requirements.txt` specifies exact package versions                                              |
| Per-bundle toolchain capture    | `generation_metadata.json::toolchain` records the Python and dep versions that built each bundle |
| Deterministic BFS               | Adapter routing uses sorted adjacency lists for tie-breaking                                     |
| Schedule-first hybrid (demand)  | PUMS-derived workplace destinations are deterministic per (modelgen, network, seed) triple       |

**Cross-platform reproducibility (verified).** Generation produces byte-identical `demand.csv` and `signals.xml` across (Apple Silicon ARM64, macOS, Python 3.13.2, osmnx 2.0.7) and (x86_64, RHEL Pitzer, Python 3.12.4, osmnx 2.1.0), verified empirically on the `la_50k_car` bundle (50K LA car + transit + bike trips, 06:00–10:00, 10 km radius, seed 42). The `network.xml` file itself differs in MD5 across the two architectures because the lxml serialization is version-dependent (attribute ordering, float-precision rendering); the semantic content (node IDs, edge `from`/`to` pairs, attributes, SCC membership) is identical, as proven by both downstream artefacts being byte-equal — they reference network node IDs by string, so any drift would have propagated. The verification recipe and reference MD5 hashes are documented in [doc/REPRODUCING.md §Cross-Platform Reproducibility](../REPRODUCING.md#cross-platform-reproducibility-verified). At the level the simulators care about (the canonical `demand.csv` and `signals.xml` consumed by every adapter), generation is fully cross-platform reproducible.

### 3.7.3 Error Handling

- **Graceful fallback**: MATSim adapter detects missing Java and reports an actionable error rather than producing empty outputs
- **Informative errors**: Demand generation provides specific guidance when model file lacks data for the target city
- **Timeout protection**: Each simulation run has a configurable timeout to prevent HPC job hangs
- **Progress tracking**: Real-time progress bars with ETA prevent silent failures in long benchmark runs

## 3.8 Canonical-Routes BFS Deduplication and Parallelization (Phase 14)

A late-stage thesis-engineering finding worth recording as an
optimization narrative: measure, identify, fix, re-measure.

### 3.8.1 The Cost That Wasn't Modelled

The cross-engine fairness contract (§3.4.2 SUMO, §3.4.3 MATSim)
requires both engines to consume identical pre-computed routes — the
state-aware BFS pre-routing introduced in V5 Phase 7 (`pipeline.\
network.turn_restrictions.shortest_path_with_restrictions`). Until
late in Version_5, each adapter ran an independent copy of this BFS
loop over the canonical network, despite the inputs (network,
turn-restrictions, feasible-trip set) being identical:

- `adapters/sumo/sumo_adapter.py:build_sumo_routes_xml` — per-trip
  BFS embedded in the routes-XML emitter.
- `adapters/matsim/matsim_adapter.py:build_matsim_plans_xml` —
  per-trip BFS embedded in the plans-XML emitter.

At small bundle scales (1K–10K trips) the duplication is invisible
(seconds), so the architectural inefficiency went unmeasured. Two
empirical data points exposed it during the 200K/500K benchmark
run on OSC Cardinal (job 9332478 / 9332482, 2026-05-12):

| Network | Trips | Per-trip BFS rate | Cold prep per engine |
|---|---|---|---|
| chicago_200k_car (50 km² bbox, ~50K nodes) | 200,000 | 1.48 s/trip | ~82 h |
| nyc_500k_car (80 km² bbox, ~80K nodes) | 500,000 | 2.16 s/trip | ~300 h |

With two engines (SUMO + MATSim) each paying the cold prep
sequentially, total adapter-prep walls projected to ~164 h
(chicago_200k) and ~600 h (nyc_500k). Cardinal's 7-day `cpu`
partition cap is 168 h. nyc_500k was therefore structurally
infeasible to complete: the job was cancelled (`scancel 9332482`)
once the projection became measurable from a 22 h sample.

Three compounding factors explain the per-trip cost:

1. **Network size scaling.** State-aware BFS visits `O(V + E)`; the
   200K/500K bundles use 15–20 km bbox radii, producing graphs an
   order of magnitude larger than the small-tier scenarios used in
   pre-V5 development.
2. **State-aware expansion.** The Phase 7 state is
   `(node, last_link_id)`, expanding the BFS visited set by a factor
   roughly equal to the average in-degree.
3. **CPython overhead.** The inner loop is pure Python; at ~5 µs per
   state expansion on a 200K-edge graph, individual BFS calls cost
   1–2 s wall.

### 3.8.2 Two Compounding Optimisations

The fix has two independent levers; both preserve the byte-identity
invariant required by the audit:

**Phase 14a — canonical-routes deduplication.** Introduces a shared
module `adapters/common/canonical_routes.py` that computes the
state-aware BFS once per `(scenario, feasible-trip-set)` and returns
a `Dict[trip_id, List[node_id]]`. The result is content-addressed
on disk in a JSONL cache (SHA-256 over network + demand + sorted
feasible IDs), so subsequent harness invocations or re-runs read
from cache in seconds. Both adapters acquire an optional
`canonical_routes=` kwarg; when provided, they skip their inline BFS
and consume the pre-computed dict. When `None` (back-compat path),
the inline BFS still runs — preserving standalone CLI use.

**Phase 14b — multiprocessing parallel BFS.** The shared module
dispatches to `multiprocessing.Pool` (spawn start method) when
`workers > 1`. Each worker loads the SCC-filtered network once via
the initializer, then processes one big chunk of trips sequentially.
`Pool.imap` preserves submission order; combined with sorted-by-
trip_id chunking, the parallel output is byte-identical to the
serial output. The execution harness reads `SLURM_CPUS_PER_TASK`
to size the pool, defaulting to one worker per SBATCH-allocated CPU.

### 3.8.3 Determinism Invariants Preserved

The byte-identity contract that `audit_fairness` Q1–Q3 enforces is
preserved at every layer of the refactor, pinned by an explicit
test suite (`tests/test_canonical_routes.py`):

1. `TestByteIdentityVsLegacy`: paths from the new shared BFS are
   byte-identical to those from the legacy inline BFS, per trip_id,
   on the tracked `chicago_1k_car` bundle.
2. `TestSumoRoutesXmlByteIdentity`: `routes.rou.xml` is byte-
   identical whether the SUMO adapter consumes pre-computed routes
   or runs its own BFS.
3. `TestMatsimPlansXmlByteIdentity`: `plans.xml` is byte-identical
   under the same with/without-canonical_routes comparison.
4. `TestParallelDeterminism`: routes from `workers=2` and
   `workers=4` are byte-identical to `workers=1`.

The 8 existing `test_adapter_determinism.py` checks (byte-identical
re-runs of the full adapter pipeline) continue to hold, because the
canonical-routes JSONL cache file is itself byte-deterministic
(sorted by trip_id on write).

### 3.8.4 Measured Speedup

**Local serial-vs-parallel calibration (chicago_1k_car, M-series Mac):**

| Worker count | Wall (s) | Speedup |
|---|---|---|
| 1 | 27.2 | 1.0× |
| 2 | 17.4 | 1.56× |
| 4 | 11.3 | 2.41× |
| 8 |  6.6 | 4.12× |

Sub-linear scaling at 1K trips reflects the per-worker init cost
(parsing the network, building the forbidden-moves table) which does
not amortize over only ~125–500 trips per worker. At the cluster
scale these init costs are dwarfed by the in-worker BFS time
(12.5K–31K trips per worker at 16-way), so the Amdahl ratio is
much closer to ideal.

**Cluster Phase 13 baseline — chicago_200k_car on Cardinal (job
9332478, 2026-05-12 to 2026-05-18):**

| Step | Wall | Notes |
|---|---|---|
| Cold SUMO BFS-prep (cell 1/10) | ~68.2 h | 200,000 trips × ~1.226 s/trip, single-thread |
| Cached SUMO mobsim cells (2–5 / 10) | ~242–246 s each | hardlink from `.cache/sumo/` (Phase 12) |
| Cold MATSim BFS-prep (cell 6/10) | ~68 h | second pass over the same network (the redundancy Phase 14a eliminates) |
| Cached MATSim mobsim cells (7–10 / 10) | ~210 s each | |
| analyze + audit + plots | ~10 min | |
| **Total wall** | **141.87 h** | of 168 h cap (15.5 % margin) |

The two cold BFS passes consume ~136 h of the 141.87 h total — **96 %
of the run was per-trip BFS routing**. This is the empirical signal
that motivated the Phase 14 refactor.

**Cluster Phase 14 re-measurement** (jobs 9954279 chicago_200k + 9954287
nyc_500k, submitted 2026-05-18 14:30 EDT) is pending. Expected post-
Phase-14 walls per the Amdahl extrapolation: ~5–8 h chicago_200k_car,
~20–30 h nyc_500k_car. The post-landing numbers replace this paragraph
with the measured-speedup table; see `CHANGELOG.md` Phase 14.9 (post-
landing) for the full diff.

### 3.8.5 Engineering Implications

This phase illustrates a methodology point that the thesis defense
benefits from: **the fairness contract talks about engine output,
not engineering effort**. The original architecture satisfied
fairness (same routes per trip across engines) by running the same
BFS twice; the Phase 14 architecture satisfies the same contract by
running the BFS once and sharing the output. The audit invariants
are insensitive to that change — they verify the produced trip set,
SCC, and travel times, all of which are byte-stable.

The optimisation also generalises: any cross-engine pre-processing
step that today lives inside per-engine adapters is a candidate for
the same treatment (deduplication via a shared module, then
parallelisation as a follow-up). Future engines added to SimForge
inherit the canonical_routes API for free — they accept the dict
or fall back to their own routing.

## 3.9 Geographic Visualization (Opt-in)

A separate, opt-in component on the `visualization` branch generates
geographic maps from canonical bundles and benchmark results. The
component is **independent of the fairness contract**: adapters,
`audit_fairness`, and the thesis runtime numbers do not import it,
and the locked benchmark numbers in Chapter 5 are unchanged by any
rendered plot. The module exists to *visualize* findings that the
quantitative analysis already establishes.

### 3.8.1 Map Catalogue

Seven map types are shipped, grouped by what input data they need:

| Map | Inputs | Engine specificity |
|---|---|---|
| `od_origins`, `od_destinations` | Canonical bundle + cached US Census tract polygons + TIGER PRISECROADS basemap | — (cross-engine, demand only) |
| `link_load` | Per-cell engine output (SUMO `tripinfo.xml`, MATSim `output_trips.csv.gz`, or DTALite `link_performance.csv`) | per `(engine, mode)` |
| `congestion` | DTALite `link_performance.csv` (needs link mean speed) | DTALite only |
| `travel_time` | Per-cell engine output + bundle | per `(engine, mode)` |
| `route_diversity` | Cell output from ≥ 2 engines | cross-engine |
| `animated_flow` | MATSim `output_events.xml.gz` | MATSim only |

The `od_*` and `travel_time` renderers use the CityScape-derived
choropleth style (100-step blue→red log palette on Census tract
polygons, light gray for empty tracts) layered on top of the US Census
TIGER PRISECROADS basemap — chosen for cartographic legibility over
the canonical SimForge network underlay (which is denser and competes
visually with the colored tract fills).

### 3.8.2 Design Principles

The visualization layer enforces three invariants:

1. **No effect on simulation inputs.** The renderer only reads files
   produced upstream; it never writes any artefact that an adapter or
   `audit_fairness` consumes. This is enforced by directory
   convention — outputs land in `visualization/output/<scenario>/`,
   distinct from `scenarios/`, `runs/`, and `doc/figures/`.
2. **Coverage-first dispatch.** Before any rendering, the CLI walks the
   bundle directory + the per-cell run directory and prints a coverage
   matrix flagging each map type `[OK]` (renderable) or `[--]`
   (missing input, with reason). `--maps all` then skips the unavailable
   maps rather than erroring, so the tool is usable on partial data.
3. **Lazy imports.** Matplotlib, shapely, pyshp, pyosmium, and the FFmpeg
   subprocess used by `animated_flow` are imported only inside the
   render path, so the main SimForge test suite has no dependency on
   them.

### 3.8.3 Cross-Engine Interpretation Surfaces

Three properties become directly visible in the maps and reinforce
quantitative findings stated elsewhere in this chapter:

- **SUMO and MATSim `link_load` are visually identical; DTALite differs.**
  The fairness contract forces SUMO and MATSim to use SimForge's
  pre-routed BFS link sequences (§3.4.2 and §3.4.3), so they render the
  same spatial traffic structure. DTALite computes its own UE
  assignment (§3.4.4) and picks alternative paths under congestion. The
  `route_diversity` map shades this difference directly: links picked
  by all three engines are gray (the BFS consensus), links picked by
  only one are red (typically DTALite's UE alternates). This is the
  *visual proof* of the fair-comparison contract whose quantitative
  signal lives in `audit_fairness` Q4 (cross-engine travel-time spread).

- **`animated_flow` shows the PUMS departure-burst effect** discussed
  in §3.3.4 step 9. Every person reporting the same JWMNP commute time
  receives the same `departure_time_s`, so 1000 chicago_1k_car trips
  collapse onto only 20 unique departure timestamps. The animation is
  *faithful to the PUMS data property*, not a SimForge bug — a future
  uniform-jitter pass would smooth the bursts at the cost of byte-
  deterministic `demand.csv`.

- **chicago_200k_car's `od_origins` ≈ `od_destinations`** (74 % node
  overlap vs 5.5 % for AM-only bundles). The full-day horizon (07:00–
  16:00) emits both AM home→work and PM work→home pairs per the Phase
  9c chain mechanism, so the OD sets become the same {homes} ∪
  {workplaces} visited at different times. This is direct evidence
  that the schedule-driven generator produces genuinely symmetric
  commute patterns at the metro scale.

The full CLI reference, render defaults, data-source provenance, and
caching layout are documented in
[`visualization/README.md`](../../visualization/README.md). The post-
run analysis pipeline that wraps the visualization tool is in
[`doc/RESULTS_GUIDE.md`](../RESULTS_GUIDE.md) §4.4.
