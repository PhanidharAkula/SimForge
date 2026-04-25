# Chapter 3: Methods

## 3.1 Overview

This chapter describes the design, implementation, and rationale of **SimForge** — a reproducible, cross-simulator benchmarking framework for urban traffic simulation. The framework addresses three fundamental challenges in simulator comparison that have historically hindered fair, reproducible evaluation of traffic simulation engines:

1. **Input standardization**: Traffic simulators (SUMO, MATSim, QarSUMO, etc.) use incompatible input formats with different data models, coordinate systems, and semantic interpretations. Direct comparison requires a common input representation.

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
| QarSUMO            | QarSUMO (LLNL)               | —       | GPU-accelerated SUMO variant            |
| GPU compute        | CUDA                         | 11.8+   | QarSUMO acceleration                    |
| Testing            | pytest                       | 8.0+    | 249 tests across all subsystems         |

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

- **2-phase default**: Current signal inference uses a simplified 2-direction split. Real intersections may have 4-8 phases.
- **State string encoding**: Compact representation where each character maps to one approach link. SUMO uses the same encoding natively.
- **Node reference**: Every signal controller references a network node, enabling cross-file validation.

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

**Input**: `network.xml`

**Output**: `signals.xml`

**Algorithm:**

1. Load network and compute **in-degree + out-degree** for each node
2. Mark nodes with degree ≥ 4 as signalized (heuristic: busy intersections tend to have signals)
3. For each signalized node, generate a **2-phase controller**:
   - Phase 1: Green for one set of approach links (e.g., N/S)
   - Phase 2: Green for orthogonal approach links (e.g., E/W)
   - Yellow and all-red clearance phases included
   - Cycle length computed from number of approaching links

**Limitations**: Real traffic signal timing involves:

- Protected left-turn phases
- Pedestrian walk/don't-walk intervals
- Adaptive (actuated) control responding to real-time demand
- Coordinated "green waves" along arterials
- None of these are currently modeled

**Typical output**: ~900 signal controllers for a 4km urban radius (Chicago: 925 controllers).

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

**Census demand generation algorithm** (7 steps):

1. **Parse model file** with geographic filtering to bounding box
2. **Map buildings to network nodes** using haversine nearest-neighbor with spatial grid index (O(B log N) complexity via grid bucketing vs O(BN) brute force)
3. **Build population-weighted origin pool**: `weight(node) = Σ building.population` for all residential buildings at that node
4. **For each trip** (repeated `num_trips` times):
   - **Sample origin**: `random.choices(nodes, weights=population)` — more people → more trips
   - **Sample census person**: Pick a PUMS person record from a building at the origin (for commute profile)
   - **Sample destination**: Gravity model with distance decay calibrated by person's commute time:
     $$P(\text{dest} = j) \propto \text{degree}(j) \cdot \exp\left(-\frac{1}{2}\left(\frac{d_{ij} - d_\text{target}}{\sigma}\right)^2\right)$$
     where $d_\text{target} = \text{JWMNP} \times 0.5$ km (assuming 30 km/h average) and $\sigma = d_\text{target} \times 0.7 + 0.5$
   - **Generate departure time**: Gaussian centered in time window, offset by commute duration:
     $$t_\text{depart} \sim \mathcal{N}(\mu + \delta, \sigma)$$
     where $\mu = (t_\text{start} + t_\text{end})/2$, $\sigma = (t_\text{end} - t_\text{start})/6$, and $\delta = -\min(\text{JWMNP}, 60) \cdot \sigma / 120$
   - **Assign mode**: From PUMS JWTRNS if multi-mode, or fixed if single-mode
5. **Sort by departure time** and renumber trip IDs sequentially
6. **Write demand.csv**

**JWTRNS → canonical mode mapping:**

| PUMS Code | Census Mode          | SimForge Mode |
| --------- | -------------------- | ------------- |
| 1         | Car — drove alone    | `car`         |
| 2         | Car — carpooled      | `car`         |
| 3         | Bus                  | `transit`     |
| 4         | Streetcar/trolley    | `transit`     |
| 5         | Subway/elevated rail | `transit`     |
| 6         | Railroad             | `transit`     |
| 7         | Ferryboat            | `transit`     |
| 8         | Bicycle              | `bike`        |
| 9         | Walked               | `walk`        |
| 10        | Worked from home     | excluded      |
| 11        | Taxicab/rideshare    | `car`         |
| 12        | Other                | `car`         |
| -1        | Not a worker         | excluded      |

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

| Feature              | Census Mode                | Synthetic Mode        |
| -------------------- | -------------------------- | --------------------- |
| Origin weighting     | Real population            | Node degree           |
| Destination model    | Commute-calibrated gravity | Topology-only gravity |
| Departure times      | Gaussian peak (JWMNP)      | Uniform random        |
| Mode assignment      | Census JWTRNS              | Fixed (car only)      |
| External data needed | ModelGen file (~300MB)     | None                  |
| Realism              | ~60-65%                    | ~15-20%               |

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
| Trip (origin, dest)       | Vehicle with route  | BFS shortest path on node graph → edge sequence   |
| `config.random_seed`      | `--seed` CLI arg    | Passed to sumo/sumo-gui                           |

**BFS Routing**: The SUMO adapter computes shortest paths at conversion time (not at simulation time). For each trip in demand.csv:

1. Run BFS from `origin_node_id` to `destination_node_id` on the directed adjacency graph
2. Convert the node path to an edge sequence via the `edge_lookup` dictionary
3. Write as `<vehicle id="veh_t0" depart="25200"><route edges="l0 l1 l2"/></vehicle>`

Trips with no valid path (disconnected OD pairs) are skipped and logged.

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

### 3.4.4 QarSUMO Adapter

**Simulator**: QarSUMO (LLNL) — GPU-accelerated variant of SUMO that offloads car-following computations to CUDA-enabled GPUs.

**Conversion**: Reuses the SUMO adapter's conversion pipeline entirely. Adds GPU-specific configuration:

```xml
<processing>
  <qarsumo.gpu-device value="0"/>
  <qarsumo.batch-size value="1024"/>
</processing>
```

**Fallback behavior**: When the QarSUMO binary is unavailable (no GPU, not installed), the adapter automatically falls back to standard SUMO execution with a warning.

**GPU detection:**

```python
def _detect_gpu() -> bool:
    """Check for CUDA GPU availability."""
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False
```

**Performance expectation**: QarSUMO provides 2-10× speedup over SUMO for microscopic simulations with >100K vehicles, due to GPU-parallel car-following computation.

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
output_dir: runs/stress_test

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
| `engine`        | string | Simulator: `sumo`, `matsim`, `qarsumo`                 |
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

**Progress tracking**: The `ProgressTracker` displays real-time progress with ETA:

```
[████████████████████░░░░░░░░░░░░░░░░░░░░] 52.3% | 47/90 runs | ✓45 ✗2 | Elapsed: 12.5m | ETA: 11.4m
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

The framework includes **249 tests** across all subsystems:

| Test Module                       | Tests | What It Validates                                       |
| --------------------------------- | ----- | ------------------------------------------------------- |
| `test_adapter_determinism.py`     | 8     | Byte-identical outputs from identical inputs            |
| `test_sumo_adapter.py`            | 4     | SUMO conversion: network, routes, config                |
| `test_matsim_adapter.py`          | 24    | MATSim adapter: unit + integration, all scenarios       |
| `test_qarsumo_adapter.py`         | 10    | QarSUMO config, GPU detection, all scenarios            |
| `test_fidelity_metrics.py`        | 21    | RMSE, GEH, KS computation correctness                   |
| `test_metrics_travel_time.py`     | 2     | SUMO tripinfo parsing                                   |
| `test_reproducibility_metrics.py` | 15    | R-index computation, edge cases, interpretation         |
| `test_scalability_metrics.py`     | 8     | Timer, throughput, hardware detection                   |
| `test_validator.py`               | 2     | Bundle validation: valid and invalid bundles            |
| `test_scenario_data_integrity.py` | 35    | 7 classes x the bundled scenario                        |
| `test_pipeline_e2e.py`            | 20    | Bad data detection, routing, adapter robustness         |
| `test_scc.py`                     | 14    | Iterative Kosaraju + parsing                            |
| `test_feasibility.py`             | 16    | Shared cross-engine trip filter                         |
| `test_analyze_benchmark.py`       | 25    | Mode-aware grouping + identity fallback + renderers     |
| `test_osm_fetch.py`               | 20    | OSM/Overpass fetch (mocked), bbox validation, cache pin |
| `test_demand_generators.py`       | 21    | Uniform/gravity/peak-hour generators, SCC restriction   |
| `test_engine_smoke.py`            | 4     | Real-binary smoke on SUMO/MATSim/QarSUMO                |

**All 249 tests passing** as of current version. Marker registry in
`pyproject.toml`; shared fixtures in `tests/conftest.py`.  Line coverage
sits at **76 %** across the adapter, pipeline, and evaluation packages;
the local gate enforces ≥70 % via `pytest --cov --cov-fail-under=70`.

### 3.7.2 Determinism Guarantees

| Mechanism          | What It Ensures                                              |
| ------------------ | ------------------------------------------------------------ |
| Fixed random seeds | All stochastic processes seeded via config.xml `random_seed` |
| Sorted outputs     | All XML/CSV files use sorted iteration over sets/dicts       |
| SHA-256 hashes     | Manifest checksums detect any input drift                    |
| Version pinning    | `requirements.txt` specifies exact package versions          |
| Deterministic BFS  | Adapter routing uses sorted adjacency lists for tie-breaking |

### 3.7.3 Error Handling

- **Graceful fallback**: QarSUMO → SUMO when no GPU; MATSim adapter detects missing Java
- **Informative errors**: Demand generation provides specific guidance when model file lacks data for the target city
- **Timeout protection**: Each simulation run has a configurable timeout to prevent HPC job hangs
- **Progress tracking**: Real-time progress bars with ETA prevent silent failures in long benchmark runs
