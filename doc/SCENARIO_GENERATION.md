# SimForge Scenario Generation — In-Depth Documentation

> Everything about how SimForge generates scenarios: what's real, what's synthetic,
> where each piece of data comes from, and how it all fits together.

---

## Table of Contents

1. [High-Level Overview](#1-high-level-overview)
2. [What's REAL vs What's SYNTHETIC](#2-whats-real-vs-whats-synthetic)
3. [The ModelGen Data Files](#3-the-modelgen-data-files)
4. [Step-by-Step Pipeline Walkthrough](#4-step-by-step-pipeline-walkthrough)
   - [Step 1: Network from OpenStreetMap](#step-1-network-from-openstreetmap)
   - [Step 2: Traffic Signals (Inferred)](#step-2-traffic-signals-inferred)
   - [Step 3: Config & Manifest](#step-3-config--manifest)
   - [Step 4: Demand Generation (Census)](#step-4-demand-generation-census)
   - [Step 4-alt: Demand Generation (Synthetic Fallback)](#step-4-alt-demand-generation-synthetic-fallback)
5. [Census Demand Deep Dive](#5-census-demand-deep-dive)
   - [Origin Selection](#51-origin-selection)
   - [Person Sampling](#52-person-sampling)
   - [Destination Selection](#53-destination-selection)
   - [Departure Time Generation](#54-departure-time-generation)
   - [Mode Assignment](#55-mode-assignment)
6. [What Makes It Realistic (and What Doesn't)](#6-what-makes-it-realistic-and-what-doesnt)
7. [Data Lineage Diagram](#7-data-lineage-diagram)
8. [Output Files Explained](#8-output-files-explained)
9. [Cluster Comparison — RedHawk vs Pitzer](#9-cluster-comparison--redhawk-vs-pitzer)
10. [Workspace Alternatives on Pitzer](#10-workspace-alternatives-on-pitzer)
11. [Glossary](#11-glossary)

---

## 1. High-Level Overview

SimForge generates **simulator-agnostic scenario bundles** — a set of XML and CSV files that describe a complete traffic simulation scenario. Any scenario bundle contains:

| File           | What It Describes                          | Source              |
| -------------- | ------------------------------------------ | ------------------- |
| `network.xml`  | Road network (nodes, links, lanes, speeds) | OpenStreetMap (real) |
| `demand.csv`   | Trip table (who, from, to, when, how)      | Census + ModelGen   |
| `signals.xml`  | Traffic signal controllers and phases       | Inferred from network topology |
| `config.xml`   | Simulation parameters (time, seed, units)  | Generated           |
| `manifest.xml` | Bundle inventory listing all files         | Generated           |

The generation pipeline has **4 steps**, executed by `generate.py`:

```
Step 1: Download road network from OpenStreetMap (real roads)
Step 2: Infer traffic signals at busy intersections
Step 3: Write config.xml + manifest.xml
Step 4: Generate trip demand (census-calibrated or synthetic)
```

---

## 2. What's REAL vs What's SYNTHETIC

This is the critical question. Here's the honest breakdown:

### Grounded in Real-World Data (Realistic)

| Component                       | Source                         | How Real Is It? |
| ------------------------------- | ------------------------------ | --------------- |
| **Road network topology**       | OpenStreetMap (crowd-sourced)  | Very real — actual streets, intersections, one-ways |
| **Road lengths**                | OSM edge geometry              | Real — measured from GPS-traced roads |
| **Speed limits**                | OSM `maxspeed` tags, or defaults per road type | Mostly real — some defaults where OSM data is missing |
| **Lane counts**                 | OSM `lanes` tags, or defaults  | Partially real — many roads missing lane data, defaults used |
| **Building locations**          | OpenStreetMap building polygons | Real — actual building footprints |
| **Building-to-road snapping**   | ModelGen nearest-road algorithm | Real — each building is linked to its closest road |
| **Population distribution**     | LandScan population grids      | Real — satellite-derived population estimates at ~1km resolution |
| **Household demographics**      | U.S. Census PUMS microdata     | Real — actual survey responses (anonymized) |
| **Person age, income, wages**   | PUMS (AGEP, HINCP, WAGP)      | Real — from census surveys |
| **Commute duration**            | PUMS JWMNP field               | Real — survey-reported commute time in minutes |
| **Transport mode choice**       | PUMS JWTRNS field              | Real — survey-reported mode (car, bus, rail, bike, walk, etc.) |

### Synthetic / Modeled (Not Directly Observed)

| Component                       | Method                          | How Synthetic Is It? |
| ------------------------------- | ------------------------------- | -------------------- |
| **Trip origins (which node)**   | Population-weighted random sampling | Semi-real: more people → more trips, but exact origins are random within the building pool |
| **Trip destinations**           | Gravity model (degree-weighted, distance-decayed) | Synthetic: no real OD survey data; destinations are probabilistic |
| **Departure times**             | Gaussian peak centered in time window, shifted by commute time | Semi-real: commute duration is from census, but the distribution shape is a model |
| **Traffic signal timing**       | Generic 2-phase signals at high-degree nodes | Synthetic: real cities have complex, optimized timing; we use simple approximations |
| **Signal placement**            | Nodes with degree ≥ 4           | Rough heuristic — real signal placement depends on traffic studies, not just connectivity |
| **OD pair routability**         | Not pre-checked in census mode  | Some OD pairs may not be routable depending on network connectivity |

### Completely Absent (Not Modeled)

| Component                       | Why It's Missing |
| ------------------------------- | ---------------- |
| **Actual OD survey data**       | Real OD surveys (like NHTS or city travel diaries) are not integrated |
| **Time-of-day activity patterns** | Full activity-based models (like POLARIS) schedule entire daily chains; we only model individual commute trips |
| **Turn restrictions**           | OSM has turn restriction data but it's not extracted |
| **Transit routes/schedules**    | Mode is "transit" but no actual bus/rail routes are generated |
| **Parking**                     | No parking availability or search behavior |
| **Weather, events, incidents**  | Not modeled |
| **Freight / commercial vehicles** | Not modeled |

---

## 3. The ModelGen Data Files

### What Are They?

The `modelgen/` directory contains large text files (`chicago_model.txt`, `la_model.txt`, `nyc_model.txt`) produced by an **activity-based population synthesizer** — a standalone C++ tool called **ModelGen** (developed by your advisor's research group).

### What Data Sources Feed Into ModelGen?

ModelGen integrates **four real-world data sources** into a single flat-text model:

```
┌─────────────────────────────────────────────────────┐
│                     ModelGen                         │
│                                                      │
│  Input 1: OpenStreetMap (.osm)                       │
│    → Road network, building polygons, land use       │
│    → Chicago_2023.osm, NYC_2023.osm, etc.           │
│                                                      │
│  Input 2: LandScan Population Grids (.adf)           │
│    → Satellite-derived population density at ~1km    │
│    → Oak Ridge National Laboratory dataset           │
│                                                      │
│  Input 3: U.S. Census PUMS Microdata (.csv)          │
│    → Household: income, bedrooms, building type      │
│    → Person: age, wages, commute time, transport mode│
│    → American Community Survey 5-year estimates      │
│    → State-level files (psam_h17.csv for Illinois)   │
│                                                      │
│  Input 4: PUMA Shapefiles (.shp/.dbf)                │
│    → Public Use Microdata Area boundaries            │
│    → Links census records to geographic areas        │
│                                                      │
│  Output: chicago_model.txt (281 MB)                  │
│    → 832,750 buildings                               │
│    → Hundreds of thousands of households             │
│    → Millions of persons with demographics           │
└─────────────────────────────────────────────────────┘
```

### File Format

The model file is a streaming text format with three record types:

#### Building Record (`bld`)

```
bld 24825537 3 0 465 false "museum:" 249630 -87.61835 41.8656 -87.61545 41.86683 681213873 41.86552 -87.61756 3525 0
```

| Field       | Value         | Meaning |
| ----------- | ------------- | ------- |
| `bld`       | —             | Record type marker |
| `24825537`  | bld_id        | Unique building ID |
| `3`         | levels        | Number of floors |
| `0`         | population    | Estimated residents (0 = non-residential) |
| `465`       | attributes    | Encoded building properties |
| `false`     | is_home       | Is this a residential building? |
| `"museum:"` | kind          | Building use type (from OSM) |
| `249630`    | sq_foot       | Estimated floor area |
| `-87.61835` | top_lon       | Bounding box — top-left longitude |
| `41.8656`   | top_lat       | Bounding box — top-left latitude |
| `-87.61545` | bot_lon       | Bounding box — bottom-right longitude |
| `41.86683`  | bot_lat       | Bounding box — bottom-right latitude |
| `681213873` | way_id        | OSM way ID of nearest road |
| `41.86552`  | way_lat       | Snap point latitude (on nearest road) |
| `-87.61756` | way_lon       | Snap point longitude (on nearest road) |
| `3525`      | puma_id       | PUMA region this building is in |
| `0`         | num_households| Number of households assigned to this building |

**Key insight**: The `way_lat`/`way_lon` fields tell us the exact point on the nearest road where this building "connects" to the road network. This is critical for mapping buildings to network nodes.

#### Household Record (`hld`)

```
hld 47219695 "1,2021HU0097114" 4 6 3525 174 153400 2 1963621 1963622
```

| Field            | Value              | Meaning |
| ---------------- | ------------------ | ------- |
| `hld`            | —                  | Record type |
| `47219695`       | bld_id             | Building this household lives in |
| `"1,2021HU0097114"` | serial_no       | PUMS household serial number (real census record) |
| `4`              | bedrooms           | Number of bedrooms |
| `6`              | bld_type           | Building type code |
| `3525`           | puma_id            | PUMA region |
| `174`            | WGTP               | Household weight (for statistical expansion) |
| `153400`         | HINCP              | Household income ($) |
| `2`              | num_people         | Number of persons |
| `1963621 1963622`| person_ids         | IDs of persons in this household |

**Key insight**: WGTP (household weight) means this one survey record represents ~174 actual households in the real population. We currently sample individual records, not expanded weights.

#### Person Record (`per`)

```
per 1963621 2021HU0097114 4 54 106000 -1 11 ""
```

| Field       | Value             | Meaning |
| ----------- | ----------------- | ------- |
| `per`       | —                 | Record type |
| `1963621`   | per_id            | Unique person ID |
| `2021HU0097114` | hld_serial    | Household they belong to |
| `4`         | num_info          | Number of info fields following |
| `54`        | AGEP              | Age (54 years old) |
| `106000`    | WAGP              | Annual wages ($106,000) |
| `-1`        | JWMNP             | Commute time in minutes (-1 = not a commuter) |
| `11`        | JWTRNS            | Transport mode code (11 = taxicab/rideshare) |

**JWTRNS codes** (from ACS/PUMS):

| Code | Mode | SimForge Mapping |
| ---- | ---- | ---------------- |
| 1    | Car — drove alone | `car` |
| 2    | Car — carpooled | `car` |
| 3    | Bus | `transit` |
| 4    | Streetcar / trolley | `transit` |
| 5    | Subway / elevated rail | `transit` |
| 6    | Railroad | `transit` |
| 7    | Ferryboat | `transit` |
| 8    | Bicycle | `bike` |
| 9    | Walked | `walk` |
| 10   | Worked from home | `home` (no trip generated) |
| 11   | Taxicab / rideshare | `car` |
| 12   | Other | `car` |
| -1   | Not a worker | (excluded from demand) |

### Scale of ModelGen Data

| City    | File Size | Buildings | Approx. Households | Approx. Persons |
| ------- | --------- | --------- | ------------------- | --------------- |
| Chicago | 281 MB    | 832,750   | ~500K+              | ~1M+            |
| LA      | 310 MB    | ~900K     | ~600K+              | ~1.2M+          |
| NYC     | 608 MB    | ~1.5M+    | ~1M+                | ~2M+            |

---

## 4. Step-by-Step Pipeline Walkthrough

When you run `python generate.py --city chicago --trips 5000`, here's exactly what happens:

### Step 1: Network from OpenStreetMap

**File**: `pipeline/network/build_network_from_osm.py`

```
Input:  City center coordinates (41.8781, -87.6298) + radius (4 km)
Output: scenarios/chicago_5k_car/network.xml
```

**What happens**:

1. **Compute bounding box** from center + radius:
   - north = lat + radius/111 km
   - south = lat - radius/111 km
   - east = lon + radius/(111·cos(lat)) km
   - west = lon - radius/(111·cos(lat)) km
   - For Chicago 4km: roughly 41.842°–41.914° N, -87.678°–-87.582° W

2. **Download from OSM** via the Overpass API (through `osmnx` library):
   - Requests all `highway=*` ways within the bounding box
   - Filters to driveable roads (motorway, trunk, primary, secondary, tertiary, residential, service, etc.)
   - Returns a NetworkX directed multigraph

3. **Simplify the graph** (osmnx does this):
   - Merges degree-2 nodes (straight-through road segments) into single edges
   - Keeps only intersections and dead-ends as nodes
   - Preserves the total road length

4. **Convert to canonical format**:
   - Each OSM node → `<node id="n0" x="-87.657" y="41.895" type="intersection" osm_id="25779173" />`
   - Each OSM way segment → `<link id="l0" from="n1" to="n2" length="134.5" lanes="2" speed_limit="13.9" road_type="primary" />`
   - Speed limits: from OSM `maxspeed` tag if present, otherwise defaults by road type (motorway=120km/h, residential=40km/h, etc.)
   - Lane counts: from OSM `lanes` tag if present, otherwise defaults (motorway=3, residential=1)

**Realistic?** YES — these are actual roads from OpenStreetMap with real geometries, real names, and mostly real speed limits. The network structure is as real as OSM data quality allows.

**Typical output**: 1,200-1,500 nodes, 2,500-3,500 links for a 4km radius in a dense urban area.

---

### Step 2: Traffic Signals (Inferred)

**File**: `pipeline/signals/build_signals_default.py`

```
Input:  network.xml
Output: scenarios/chicago_5k_car/signals.xml
```

**What happens**:

1. **Load the network** and compute node degrees (in-links + out-links).
2. **Identify signalized nodes**: any node with degree ≥ 4 (i.e., at least 4 approach roads).
3. **Generate simple 2-phase signal controllers**:
   - Phase 1: Green for incoming links from "north/south" direction
   - Phase 2: Green for incoming links from "east/west" direction
   - Default cycle length: computed from the number of approaching roads
   - Yellow/all-red transitions included

**Realistic?** PARTIALLY — in reality, signal timing is carefully optimized by traffic engineers. Our signals are:
- Placed at approximately the right locations (high-connectivity intersections)
- Timed with reasonable but generic cycle lengths
- Missing: adaptive signals, protected left turns, pedestrian phases, coordinated corridors

---

### Step 3: Config & Manifest

**Files**: Written directly by `generate.py`

```
Output: config.xml, manifest.xml
```

**config.xml** specifies:
- Scenario ID (`chicago_5k_car`)
- Time window (e.g., 25200–28800 seconds = 7:00–8:00 AM)
- Random seed (42)
- Units (meters, m/s, seconds)

**manifest.xml** lists all files in the bundle, their types, and paths.

**Realistic?** N/A — these are metadata files, not simulation data.

---

### Step 4: Demand Generation (Census)

**Files**: `pipeline/demand/parse_model_file.py`, `pipeline/demand/generate_census_demand.py`

This is the most complex step and the most important for realism.

```
Input:  modelgen/chicago_model.txt + network.xml
Output: scenarios/chicago_5k_car/demand.csv
```

**What happens** (detailed in Section 5 below):

1. **Parse the model file**, filtering to the bounding box
2. **Map buildings to network nodes** (spatial nearest-neighbor)
3. **Build population-weighted origin pool**
4. **For each trip**: sample origin → sample person → sample destination → generate departure time → assign mode
5. **Write CSV**: trip_id, origin_node_id, destination_node_id, departure_time_s, mode

---

### Step 4-alt: Demand Generation (Synthetic Fallback)

**File**: `pipeline/demand/generate_synthetic_demand.py`

Used when `--synthetic` flag is passed or no model file exists.

```
Input:  network.xml only
Output: scenarios/chicago_5k_car/demand.csv
```

**What happens**:

1. **Load network** and compute strongly connected component
2. **Use gravity model**: 
   - Origins weighted by node degree (more connections = more activity)
   - Destinations weighted by degree / distance^decay
   - Minimum distance: 0.5 km (avoids trivial trips)
   - Maximum distance: 10 km (keeps trips urban-scale)
3. **Departure times**: uniform random within the time window

**Realistic?** LESS than census mode — everything is based on network topology alone, with no real population or demographic data.

---

## 5. Census Demand Deep Dive

This section explains exactly how each trip is generated when using census (ModelGen) data.

### 5.1 Origin Selection

**Method**: Population-weighted random sampling from residential buildings.

**Process**:
1. Parse model file → extract buildings within bounding box
2. Keep only buildings where `population > 0` (residential buildings)
3. Map each building to its nearest network node using the building's `way_lat`/`way_lon` snap point
4. Aggregate population at each node: `origin_weight[node] = sum(building.population for buildings at this node)`
5. Sample origin using `random.choices(origin_nodes, weights=origin_weights)`

**What's real**: Population distribution comes from LandScan satellite data + OSM building footprints. Areas with more people generate proportionally more trips.

**What's synthetic**: The exact building that "generates" each trip is randomly sampled. In reality, not all people in a building commute, and they don't all leave at the same rate.

**Example**: A node with 5 apartment buildings totaling 2,000 residents will generate ~20× more trips than a node with one house of 100 residents.

### 5.2 Person Sampling

**Method**: After selecting an origin node, pick a census person from a building at that node.

**Process**:
1. Look up the buildings mapped to the chosen origin node
2. Randomly pick one building
3. Look up the households in that building
4. Look up the persons in those households
5. Pick one person who has `commute_min > 0` (i.e., an actual commuter)
6. If no commuters at that building, fall back to the global commuter pool

**What's real**: Each sampled person is an actual census record (anonymized). Their age, income, commute duration, and transport mode are real survey data.

**What's synthetic**: Which specific person "takes" each trip is random. The building-to-person linkage is a synthetic assignment by ModelGen (census records are assigned to buildings probabilistically based on PUMA region).

### 5.3 Destination Selection

**Method**: Gravity model with distance decay calibrated by the person's commute time.

**Process**:
1. From the sampled person, get `commute_min` (e.g., 25 minutes)
2. Estimate target distance: `target_km = commute_min × 0.5` (assumes ~30 km/h average travel speed)
   - Clamped to [0.5, 15.0] km
3. For each candidate destination node, compute:
   - `degree_weight` = how many roads connect (proxy for activity/importance)
   - `dist_score` = Gaussian fit around target distance: `exp(-0.5 × ((dist - target_km) / (target_km × 0.7 + 0.5))²)`
   - `total_score` = `degree_weight × dist_score`
4. Sample destination using weighted random choice

**What's real**: 
- The commute time comes from real census data (JWMNP field)
- More connected nodes (higher degree) attract more trips, which correlates with commercial/employment areas

**What's synthetic**:
- The destination itself is NOT from any real OD survey
- The 30 km/h speed assumption is a rough heuristic
- The Gaussian distance profile is a model, not observed data
- Node degree is a rough proxy for employment/activity density

**This is the single biggest source of approximation in the pipeline.** Real cities have complex OD patterns driven by employment centers, schools, hospitals, shopping — none of which are explicitly modeled.

### 5.4 Departure Time Generation

**Method**: Normal distribution centered in the time window, shifted by commute duration.

**Process**:
1. Compute window midpoint: `mid = (start + end) / 2`
2. Compute spread: `σ = (end - start) / 6` (so ±3σ covers the entire window)
3. Commute offset: longer commutes → earlier departure: `offset = -min(commute_min, 60) × (σ / 120)`
4. Sample: `departure = Normal(mid + offset, σ)`, clamped to [start, end)

**What's real**: Commute duration is from census → longer commuters depart earlier in the peak.

**What's synthetic**: The Gaussian shape is a model. Real departure patterns have sharper peaks and are asymmetric (steep rise in the morning, slower falloff).

### 5.5 Mode Assignment

**Two modes of operation**:

1. **Single-mode** (`--modes car`): All trips get mode "car", regardless of the person's census mode.

2. **Multi-mode** (`--modes car,transit,bike`): Each trip gets the person's actual census mode from JWTRNS:
   - Person with JWTRNS=1 (drove alone) → "car"
   - Person with JWTRNS=3 (bus) → "transit"
   - Person with JWTRNS=8 (bicycle) → "bike"
   - Only persons whose mode is in the allowed list are sampled

**What's real**: Mode split comes directly from census (JWTRNS) and reflects actual self-reported travel behavior.

**What's synthetic**: Mode is assigned at the trip level but doesn't affect routing (SimForge v0 doesn't have transit network routes).

---

## 6. What Makes It Realistic (and What Doesn't)

### The Realism Argument (for a thesis)

SimForge scenarios are **more realistic than typical synthetic benchmarks** because:

1. **Real road networks** from OpenStreetMap, not grid networks or random graphs
2. **Population-grounded origins** — trip production is proportional to where people actually live (LandScan + OSM buildings)
3. **Census-calibrated demographics** — commute times, transport modes, and demographics come from actual PUMS survey responses
4. **Spatial realism** — buildings are snapped to their actual nearest roads, preserving spatial fidelity
5. **City-specific** — Chicago, LA, and NYC each have their own demographics, road patterns, and commute profiles

### The Honest Limitations

1. **No real OD data**: The biggest limitation. Destinations are gravity-modeled, not from actual surveys. Real OD data (like LODES/LEHD or NHTS) would be a major improvement.

2. **No activity chains**: Each trip is independent. Real people make sequences of trips (home → work → lunch → work → home). Activity-based models (like POLARIS) capture these chains.

3. **Simplified signals**: Traffic signals are generic 2-phase controllers, not the city's actual signal plans.

4. **No transit network**: The mode "transit" exists in the demand but there are no bus routes, train lines, or schedules in the network. Transit trips can't actually route.

5. **Static demand**: All trips are generated upfront. No dynamic response to congestion (rerouting, mode switching, departure time shifting).

6. **Population expansion not used**: Census WGTP weights could expand ~10K survey records to represent ~1M real people, but we currently sample raw records. This limits us to ~500K unique trips per city without oversampling.

### Compared to Other Approaches

| Approach | Realism | Data Requirements | Complexity |
| -------- | ------- | ----------------- | ---------- |
| Random OD pairs | Very low | None | Trivial |
| Gravity model (network-only) | Low | Network only | Low |
| **SimForge Census** | **Medium-High** | **OSM + LandScan + PUMS** | **Medium** |
| Activity-based (POLARIS) | Very High | Full survey + land use | Very High |
| Observed OD (LODES/NHTS) | Highest | Real survey data | High |

---

## 7. Data Lineage Diagram

```
  REAL-WORLD DATA SOURCES
  ═══════════════════════

  ┌──────────────────┐    ┌──────────────────┐    ┌────────────────┐    ┌──────────────────┐
  │  OpenStreetMap    │    │ LandScan Pop.    │    │  U.S. Census   │    │  PUMA Boundaries │
  │  (2023 extract)  │    │ Grid (~1km res)  │    │  PUMS 5-year   │    │  (IPUMS 2010)    │
  │                  │    │                  │    │  ACS microdata  │    │                  │
  │  • Road network  │    │  • Population    │    │  • AGEP (age)   │    │  • Geographic    │
  │  • Buildings     │    │    density per   │    │  • WAGP (wages) │    │    boundaries    │
  │  • Land use      │    │    grid cell     │    │  • JWMNP (mins) │    │    linking PUMS  │
  │                  │    │                  │    │  • JWTRNS (mode)│    │    to locations   │
  └────────┬─────────┘    └────────┬─────────┘    │  • HINCP ($)   │    └────────┬─────────┘
           │                       │               │  • WGTP (wt)   │             │
           │                       │               └────────┬───────┘             │
           │                       │                        │                     │
           ▼                       ▼                        ▼                     ▼
  ┌────────────────────────────────────────────────────────────────────────────────┐
  │                           ModelGen (C++ tool)                                  │
  │                                                                                │
  │  Synthesizes a complete population model:                                      │
  │    1. Places OSM buildings on a map                                            │
  │    2. Assigns population to buildings using LandScan                           │
  │    3. Creates households using PUMS records (matched by PUMA region)           │
  │    4. Assigns persons to households with real demographics                     │
  │    5. Links each building to its nearest road (way_lat/way_lon)               │
  │                                                                                │
  │  Output: chicago_model.txt (281 MB, 832K buildings, ~500K+ households)         │
  └─────────────────────────────────────┬──────────────────────────────────────────┘
                                        │
                                        │ (model file)
                                        │
  SIMFORGE PIPELINE                     │
  ═════════════════                     │
                                        │
  ┌────────────────────────┐            │
  │  OpenStreetMap          │            │
  │  (live Overpass API)    │            │
  │                         │            │
  │  Fresh network download │            │
  │  for the exact bbox     │            │
  └───────────┬─────────────┘            │
              │                          │
              ▼                          ▼
  ┌───────────────────┐     ┌──────────────────────────┐
  │ build_network_    │     │   parse_model_file.py     │
  │  from_osm.py      │     │                          │
  │                   │     │  Parse bld/hld/per records│
  │  • Download OSM   │     │  Filter to bounding box  │
  │  • Simplify graph │     │  Filter by mode/car_only │
  │  • Extract nodes  │     │  Build: buildings,        │
  │  • Extract links  │     │    households, persons    │
  │  • Write XML      │     └──────────┬───────────────┘
  └────────┬──────────┘                │
           │                           │
           ▼                           ▼
  ┌──────────────────────────────────────────────────┐
  │           generate_census_demand.py               │
  │                                                    │
  │  1. Map buildings → nearest network nodes          │
  │  2. Weight origins by building population          │
  │  3. For each trip:                                 │
  │     a. Sample origin (population-weighted)         │
  │     b. Sample census person (commute profile)      │
  │     c. Sample destination (gravity + commute km)   │
  │     d. Generate departure time (Gaussian peak)     │
  │     e. Assign mode (from JWTRNS or fixed)          │
  │  4. Write demand.csv                               │
  └──────────────────────┬─────────────────────────────┘
                         │
                         ▼
  ┌──────────────────────────────────────────────────┐
  │               Scenario Bundle                     │
  │                                                    │
  │   scenarios/chicago_5k_car/                        │
  │     ├── network.xml    (real road network)         │
  │     ├── demand.csv     (census-calibrated trips)   │
  │     ├── signals.xml    (inferred signals)          │
  │     ├── config.xml     (simulation params)         │
  │     ├── manifest.xml   (file inventory)            │
  │     └── generation_metadata.json                   │
  └────────────────────────────────────────────────────┘
```

---

## 8. Output Files Explained

### demand.csv

```csv
trip_id,origin_node_id,destination_node_id,departure_time_s,mode
t0,n158,n352,25200,car
t1,n125,n1179,25200,car
t2,n399,n603,25200,car
...
```

| Column               | Source                              | Real or Synthetic? |
| -------------------- | ----------------------------------- | ------------------- |
| `trip_id`            | Sequential counter                  | Generated |
| `origin_node_id`     | Building → nearest node, pop-weighted | Semi-real (population distribution is real, specific node is sampled) |
| `destination_node_id`| Gravity model + commute distance    | Synthetic (no real OD data) |
| `departure_time_s`   | Census commute time + Gaussian peak | Semi-real (census commute data shapes the distribution) |
| `mode`               | Census JWTRNS or fixed              | Real when multi-mode; fixed when single-mode |

### network.xml

```xml
<network>
  <metadata crs="EPSG:4326" units_length="meters" units_speed="m/s" source="OSM"/>
  <nodes>
    <node id="n0" x="-87.6571862" y="41.8950877" type="dead_end" osm_id="25779173"/>
    ...
  </nodes>
  <links>
    <link id="l0" from="n0" to="n1" length="134.5" lanes="2" speed_limit="13.9" road_type="residential"/>
    ...
  </links>
</network>
```

| Attribute    | Source                  | Real or Synthetic? |
| ------------ | ----------------------- | ------------------- |
| Node (x, y)  | OSM node coordinates   | Real (GPS-derived) |
| Link length   | OSM way geometry       | Real (measured) |
| Speed limit   | OSM maxspeed tag       | Mostly real (defaults where missing) |
| Lane count    | OSM lanes tag          | Partially real (defaults common) |
| Road type     | OSM highway tag        | Real |

### signals.xml

```xml
<signals>
  <controller junction_id="sig_n100" node_id="n100" cycle_length_s="80">
    <phase phase_id="p0" duration_s="35" state="GGrrr" />
    <phase phase_id="p1" duration_s="5" state="yyrrrr" />
    ...
  </controller>
</signals>
```

| Attribute     | Source                    | Real or Synthetic? |
| ------------- | ------------------------- | ------------------- |
| Location      | Network degree heuristic  | Approximate |
| Cycle length  | Generic formula           | Synthetic |
| Phase timing  | Equal split               | Synthetic |

### generation_metadata.json

```json
{
  "scenario_id": "chicago_1k_car",
  "city": "chicago",
  "trips_requested": 1000,
  "trips_generated": 1000,
  "demand_strategy": "census",
  "node_count": 1248,
  "link_count": 2871,
  "signal_count": 925,
  "generation_time_s": 27.8
}
```

---

## 9. Cluster Comparison — RedHawk vs Pitzer

### Hardware & Resources

| Feature            | OSC Pitzer                            | Miami RedHawk                         |
| ------------------ | ------------------------------------- | ------------------------------------- |
| **Operator**       | Ohio Supercomputer Center (state)     | Miami University (campus)             |
| **CPU**            | Intel Xeon (40-48 cores/node)         | Intel Xeon Gold 6126 (24+ cores/node) |
| **RAM**            | 178 GB – 744 GB per node              | 93 GB – 708 GB per node              |
| **GPU**            | NVIDIA V100 (2-4/node, GRES works)   | CUDA-capable (GRES not configured)    |
| **Max wall time**  | 7 days                                | 20 days (batch), 3 days (gpu/bigmem)  |
| **Partitions**     | batch*, cpu, gpu, gpu-quad, debug     | batch, gpu, bigmem                    |
| **Storage**        | Home: 500 GB, Project: 500 GB        | Home directory only                   |
| **Project Account**| PMIU0110                              | N/A (user-level)                      |

### Software & Modules

| Software      | OSC Pitzer                           | Miami RedHawk                         |
| ------------- | ------------------------------------ | ------------------------------------- |
| **Python**    | `python/3.10`, `python/3.12`        | `anaconda-python3.10` (Python 3.10.9) |
| **SUMO**      | Not a module — install via `pip install eclipse-sumo` | Not available                 |
| **Java**      | Not available (no MATSim)            | Not checked                           |
| **CUDA**      | `cuda/11.8.0`, `cuda/12.4.1`, `cuda/12.6.2` | Available                   |
| **QarSUMO**   | Not available                        | Not available                          |
| **GCC**       | Modern (build from source works)     | GCC 4.8.5 (can't build pandas 2.x)   |

### SimForge Capabilities

| Capability             | OSC Pitzer | Miami RedHawk | Notes |
| ---------------------- | ---------- | ------------- | ----- |
| **Scenario generation (small, no model file)** | YES | YES | Synthetic gravity model, no internet needed |
| **Scenario generation (large, with model file)** | YES | PARTIAL | RedHawk compute nodes block internet → OSM download hangs |
| **Scenario generation on login node** | YES | YES | Both allow light interactive work |
| **OSM network download in batch jobs** | YES | NO | RedHawk blocks internet on compute nodes; Pitzer allows it |
| **SUMO simulation (meso)** | YES (pip) | NO | eclipse-sumo installable via pip on Pitzer |
| **SUMO simulation (micro)** | YES (pip) | NO | Same — eclipse-sumo includes sumo binary |
| **MATSim simulation** | NO | NO | No Java on either cluster |
| **QarSUMO (GPU-accelerated)** | NO | NO | Custom binary not available on either |
| **Evaluation / analysis** | YES | YES | Pure Python, no external deps |
| **Plot generation** | YES | YES | matplotlib in venv |
| **Transfer model files** | YES (scp) | YES (scp) | Both accept scp transfers |
| **Full benchmark pipeline** | YES | NO (no SUMO) | Pitzer can run end-to-end |

### Recommendation

**Use OSC Pitzer for everything.** RedHawk is limited by:
1. No internet on compute nodes (can't download OSM in batch jobs)
2. No SUMO module or pip-installable SUMO (old GCC)
3. Old GCC prevents building many modern Python packages

Pitzer has internet on compute nodes, modern Python 3.12, and eclipse-sumo installs cleanly.

---

## 10. Workspace Alternatives on Pitzer

You don't need to clone into the project directory (`/fs/ess/PMIU0110/`). Here are your options:

### Option A: Home Directory (Recommended for SimForge)

```bash
# Clone to your home directory — no advisor permission needed
git clone -b modelgen https://github.com/PhanidharAkula/SimForge.git ~/SimForge
```

- **Path**: `/users/PMIU0110/phanidharakula/SimForge/` (this is `~/SimForge`)
- **Quota**: 500 GB (currently using 1.14 GB)
- **Pros**: You own it, no permission issues, plenty of space
- **Cons**: Not shared with other group members

### Option B: Scratch Storage (For Large Temporary Data)

```bash
# OSC provides fast scratch space
# Check: echo $TMPDIR (set per-job) or use /fs/scratch/PMIU0110/
mkdir -p /fs/scratch/PMIU0110/phanidharakula/SimForge
git clone -b modelgen https://github.com/PhanidharAkula/SimForge.git /fs/scratch/PMIU0110/phanidharakula/SimForge
```

- **Pros**: Fast I/O, good for large generation jobs
- **Cons**: Scratch is purged periodically (files older than ~90 days may be deleted)

### Option C: Project Storage (Shared, Ask Advisor)

```bash
# If advisor approves — good for sharing results with the group
mkdir -p /fs/ess/PMIU0110/SimForge
git clone -b modelgen https://github.com/PhanidharAkula/SimForge.git /fs/ess/PMIU0110/SimForge
```

- **Path**: `/fs/ess/PMIU0110/SimForge/`
- **Quota**: 500 GB shared (currently 16 GB used)
- **Pros**: Shared with group, persistent
- **Cons**: Need advisor permission, shared quota

### Recommendation

**Use Option A (home directory)** — it's yours, has 500 GB of space, and requires no special permissions. The model files (~1.2 GB total) and generated scenarios (~1-5 GB) fit easily.

---

## 11. Glossary

| Term | Definition |
| ---- | ---------- |
| **ACS** | American Community Survey — annual U.S. Census Bureau survey of demographics, commuting, housing |
| **Bounding box (bbox)** | Geographic rectangle defined by (north, south, east, west) coordinates |
| **Canonical format** | SimForge's simulator-agnostic scenario schema (network.xml, demand.csv, etc.) |
| **Census-calibrated demand** | Trip generation using real census demographic data (vs purely random) |
| **Gravity model** | Trip distribution model where flow between zones is proportional to "mass" (activity) and inversely proportional to distance |
| **JWMNP** | ACS/PUMS field: Journey to Work — travel time in Minutes to Place of work |
| **JWTRNS** | ACS/PUMS field: Journey to Work — TRaNSportation mode |
| **LandScan** | Global population distribution dataset by Oak Ridge National Laboratory (~1km cells) |
| **ModelGen** | C++ population synthesizer that combines OSM, LandScan, and PUMS into building/household/person models |
| **OD pair** | Origin-Destination pair — a single trip from point A to point B |
| **OSM** | OpenStreetMap — crowd-sourced geographic database |
| **Overpass API** | HTTP API for querying OpenStreetMap data |
| **PUMA** | Public Use Microdata Area — geographic unit (~100K-200K people) used in census microdata |
| **PUMS** | Public Use Microdata Sample — individual-level census records (anonymized) |
| **SCC** | Strongly Connected Component — the largest subgraph where every node can reach every other node |
| **Snap point** | The point on the closest road to a building; stored as `way_lat`/`way_lon` in model files |
| **WGTP** | Household weight from PUMS — how many real households one survey record represents |
