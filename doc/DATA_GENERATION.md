# SimForge Data Generation Guide

## Overview

This document provides comprehensive documentation on how scenario data is generated for SimForge benchmarks, including data sources, synthetic generation methods, validation procedures, and reproducibility guarantees.

---

## Table of Contents

1. [Data Components](#1-data-components)
2. [Data Sources: Real vs Synthetic](#2-data-sources-real-vs-synthetic)
3. [Network Generation Pipeline](#3-network-generation-pipeline)
4. [Demand Generation Pipeline](#4-demand-generation-pipeline)
5. [Signal Timing Pipeline](#5-signal-timing-pipeline)
6. [Validation & Quality Assurance](#6-validation--quality-assurance)
7. [HPC Generation Guide (OSC)](#7-hpc-generation-guide-osc)
8. [Reproducibility Guarantees](#8-reproducibility-guarantees)
9. [Known Limitations](#9-known-limitations)

---

## 1. Data Components

Each canonical scenario bundle contains five files:

| File           | Format | Real/Synthetic | Description                                        |
| -------------- | ------ | -------------- | -------------------------------------------------- |
| `network.xml`  | XML    | **Real**       | Road network topology from OpenStreetMap           |
| `demand.csv`   | CSV    | **Synthetic**  | Travel demand (OD trips)                           |
| `signals.xml`  | XML    | **Semi-real**  | Traffic signals (locations real, timing estimated) |
| `config.xml`   | XML    | Generated      | Simulation parameters                              |
| `manifest.xml` | XML    | Generated      | File inventory with SHA-256 hashes                 |

---

## 2. Data Sources: Real vs Synthetic

### 2.1 What's Real

| Component                  | Source        | Accuracy | Notes                              |
| -------------------------- | ------------- | -------- | ---------------------------------- |
| **Road geometry**          | OpenStreetMap | High     | Crowdsourced, continuously updated |
| **Intersection locations** | OpenStreetMap | High     | GPS-accurate                       |
| **Road classification**    | OpenStreetMap | High     | highway=\* tags                    |
| **Lane counts**            | OpenStreetMap | Medium   | Often missing, estimated           |
| **Speed limits**           | OpenStreetMap | Medium   | maxspeed=\* tags, often missing    |
| **Signal locations**       | OpenStreetMap | Medium   | highway=traffic_signals tag        |
| **Turn restrictions**      | OpenStreetMap | Medium   | restriction=\* relations           |

### 2.2 What's Synthetic

| Component                    | Method                            | Rationale                             |
| ---------------------------- | --------------------------------- | ------------------------------------- |
| **Travel demand (OD pairs)** | Gravity model + random sampling   | Real OD data is proprietary/expensive |
| **Departure times**          | Statistical distribution          | Matches typical urban patterns        |
| **Signal timing**            | NEMA defaults + Webster's formula | Real timing data rarely available     |
| **Link capacity**            | HCM 2016 formulas                 | Derived from lane count + road type   |
| **Free-flow speed**          | Speed limit or road class default | When maxspeed tag missing             |

### 2.3 Why Synthetic Demand?

Real travel demand data sources:

| Source           | Cost   | Coverage        | Access                    |
| ---------------- | ------ | --------------- | ------------------------- |
| StreetLight Data | $$$$   | US cities       | Commercial license        |
| Replica          | $$$$   | US cities       | Commercial license        |
| Census LODES     | Free   | US              | Employment flows only     |
| NHTS             | Free   | National        | Survey, not city-specific |
| Transit surveys  | Varies | Agency-specific | Often restricted          |

**Decision**: Use synthetic demand because:

1. **Reproducibility**: Anyone can regenerate identical demand
2. **Cost**: No licensing fees or data agreements required
3. **Flexibility**: Can scale to any demand level (5K → 5M)
4. **Fairness**: Same demand generation for all simulators
5. **Control**: Known ground truth for validation

---

## 3. Network Generation Pipeline

### 3.1 Pipeline Stages

```
OpenStreetMap → Overpass API → OSM XML → netconvert → SUMO net.xml → Canonical network.xml
```

### 3.2 OSM Data Extraction

**Source**: OpenStreetMap via Overpass API

**Query Structure**:

```
[out:xml][timeout:1800];
(
  way["highway"]({south},{west},{north},{east});
  node(w);
);
out body;
```

**Included Highway Types**:

- `motorway`, `motorway_link`
- `trunk`, `trunk_link`
- `primary`, `primary_link`
- `secondary`, `secondary_link`
- `tertiary`, `tertiary_link`
- `residential`
- `unclassified`

**Excluded**:

- `footway`, `cycleway`, `path` (pedestrian/bike only)
- `service` (parking lots, driveways)
- `track` (unpaved roads)

### 3.3 Network Cleaning

Using SUMO's `netconvert` with these operations:

| Operation             | Flag                      | Purpose                     |
| --------------------- | ------------------------- | --------------------------- |
| Remove geometry nodes | `--geometry.remove`       | Simplify links              |
| Guess ramps           | `--ramps.guess`           | Identify highway ramps      |
| Join junctions        | `--junctions.join`        | Merge close intersections   |
| Remove isolated edges | `--remove-edges.isolated` | Clean disconnected segments |
| Remove U-turns        | `--no-turnarounds`        | Realistic turning           |

### 3.4 Attribute Mapping

| OSM Tag      | Canonical Attribute  | Default if Missing    |
| ------------ | -------------------- | --------------------- |
| `highway=*`  | `type`               | `unclassified`        |
| `maxspeed=*` | `speed` (m/s)        | See table below       |
| `lanes=*`    | `lanes`              | See table below       |
| `oneway=*`   | Single/bidirectional | Based on highway type |

**Default Speeds** (when `maxspeed` missing):

| Highway Type | Default (mph) | Default (m/s) |
| ------------ | ------------- | ------------- |
| motorway     | 65            | 29.1          |
| trunk        | 55            | 24.6          |
| primary      | 45            | 20.1          |
| secondary    | 35            | 15.6          |
| tertiary     | 30            | 13.4          |
| residential  | 25            | 11.2          |

**Default Lane Counts** (when `lanes` missing):

| Highway Type | Default Lanes |
| ------------ | ------------- |
| motorway     | 3             |
| trunk        | 2             |
| primary      | 2             |
| secondary    | 2             |
| tertiary     | 1             |
| residential  | 1             |

### 3.5 Capacity Calculation

Link capacity derived using Highway Capacity Manual (HCM 2016):

```
capacity = lanes × base_capacity × adjustment_factors
```

| Road Type | Base Capacity (veh/hr/lane) |
| --------- | --------------------------- |
| Freeway   | 2,200                       |
| Arterial  | 1,800                       |
| Collector | 1,600                       |
| Local     | 1,400                       |

---

## 4. Demand Generation Pipeline

### 4.1 Synthetic Demand Model

We use a **gravity model with random sampling**:

```python
P(trip from i to j) ∝ (Pop_i × Pop_j) / distance(i,j)^β
```

Where:

- `Pop_i`, `Pop_j` = population proxies (node connectivity)
- `β` = distance decay parameter (typically 1.5-2.0)

**Simplified approach** (current implementation):

- Uniform random sampling of origin/destination nodes
- Weighted by node degree (more connected = more trips)

### 4.2 Departure Time Distribution

Trips distributed across 24 hours following typical urban patterns:

| Period   | Time Range  | % of Daily Trips | Distribution |
| -------- | ----------- | ---------------- | ------------ |
| AM Peak  | 07:00-09:00 | 25%              | Uniform      |
| PM Peak  | 16:00-19:00 | 30%              | Uniform      |
| Off-Peak | All other   | 45%              | Uniform      |

```python
def sample_departure_time():
    r = random.random()
    if r < 0.25:      # Morning peak
        return uniform(7*3600, 9*3600)
    elif r < 0.55:    # Evening peak
        return uniform(16*3600, 19*3600)
    else:             # Off-peak
        return uniform(0, 24*3600)
```

### 4.3 Demand Tiers

| Tier | Trip Count | Use Case                       |
| ---- | ---------- | ------------------------------ |
| 5K   | 5,000      | Thesis benchmarks (current)    |
| 50k  | 50,000     | Development, quick testing     |
| 500k | 500,000    | Scalability testing (future)   |
| 5M   | 5,000,000  | Full-scale benchmarks (future) |

### 4.4 Mode Assignment

Currently **car-only** demand:

- All trips assigned mode = "car"
- Future work: multi-modal (transit, bike, walk)

### 4.5 Demand File Format

```csv
trip_id,origin,destination,departure_time,mode
trip_0,node_123,node_456,28847.3,car
trip_1,node_789,node_012,31205.1,car
...
```

---

## 5. Signal Timing Pipeline

### 5.1 Signal Location Detection

**Source**: OpenStreetMap `highway=traffic_signals` nodes

**Intersection identification**:

1. Find nodes tagged with `highway=traffic_signals`
2. Identify all incoming/outgoing links
3. Group into signal-controlled intersection

### 5.2 Timing Estimation

Since real signal timing data is rarely available publicly, we estimate timing using:

**Method 1: SUMO's TLS Guess** (`--tls.guess-signals`)

- Automatically assigns signal control to intersections
- Uses default NEMA timing patterns

**Method 2: Webster's Optimal Cycle** (for arterials)

```
C_opt = (1.5L + 5) / (1 - Y)

Where:
  L = total lost time per cycle
  Y = sum of critical flow ratios
```

**Default Timing Parameters**:

| Parameter    | Value   | Notes              |
| ------------ | ------- | ------------------ |
| Cycle length | 90-120s | Typical urban      |
| Min green    | 7s      | Pedestrian minimum |
| Yellow       | 4s      | Standard           |
| All-red      | 2s      | Clearance          |
| Offset       | 0s      | No coordination    |

### 5.3 Signal Types

| Type       | Description         | Usage                  |
| ---------- | ------------------- | ---------------------- |
| `static`   | Fixed timing        | Default                |
| `actuated` | Detector-responsive | When detectors present |

---

## 6. Validation & Quality Assurance

### 6.1 Network Validation

| Check          | Method                       | Acceptance Criteria    |
| -------------- | ---------------------------- | ---------------------- |
| Connectivity   | BFS from largest component   | >95% nodes reachable   |
| Dead-ends      | Count degree-1 nodes         | <5% of total           |
| Isolated nodes | Find disconnected components | 0 isolated             |
| Link length    | Statistical analysis         | No 0-length links      |
| Speed bounds   | Range check                  | 1 m/s < speed < 50 m/s |

### 6.2 Demand Validation

| Check            | Method               | Acceptance Criteria        |
| ---------------- | -------------------- | -------------------------- |
| Trip count       | Row count            | Matches tier specification |
| Valid OD         | Node existence check | All O/D in network         |
| Departure bounds | Range check          | 0 ≤ depart < 86400         |
| No self-loops    | O ≠ D                | 0% self-loops              |

### 6.3 Hash Verification

Every file tracked in `manifest.xml` with SHA-256:

```xml
<manifest version="0.1">
  <files>
    <file name="network.xml" sha256="a1b2c3..." size="12345678"/>
    <file name="demand.csv" sha256="d4e5f6..." size="87654321"/>
    ...
  </files>
</manifest>
```

Validation command:

```bash
python -m pipeline.validation.validate_bundle scenarios/chicago_5k
```

---

## 7. HPC Generation Guide (OSC)

> **Note**: The 5K-tier scenarios used in the current thesis benchmarks generate
> locally in under 30 seconds each. HPC is only needed for future higher-tier
> scenarios (50K, 500K, 5M). The scripts and instructions below are preserved
> for that future use.

### 7.1 Ohio Supercomputer Center (OSC) Overview

OSC provides two main clusters:

| Cluster    | Nodes | Cores/Node              | Memory/Node | Best For        |
| ---------- | ----- | ----------------------- | ----------- | --------------- |
| **Pitzer** | 560   | 48 (Intel Cascade Lake) | 192 GB      | General compute |
| **Owens**  | 824   | 28 (Intel Haswell)      | 128 GB      | High throughput |

### 7.2 Time Estimates on OSC

**Assumptions**:

- 48 cores per node (Pitzer)
- 8x speedup vs M1 Mac for parallel tasks
- Network download limited by external bandwidth

#### Single-Node Estimates (Pitzer, 48 cores)

| City        | 50k     | 500k    | 5M     |
| ----------- | ------- | ------- | ------ |
| **NYC**     | ~30 min | ~2 hr   | ~18 hr |
| **LA**      | ~25 min | ~1.5 hr | ~16 hr |
| **Chicago** | ~20 min | ~1.5 hr | ~12 hr |

#### Parallel Generation (3 nodes, one per city)

| Scenario Set             | Wall Time  | Node-Hours |
| ------------------------ | ---------- | ---------- |
| All 50k (3 cities)       | ~30 min    | 1.5        |
| All 500k (3 cities)      | ~2 hr      | 6          |
| All 5M (3 cities)        | ~18 hr     | 54         |
| **Complete 9 scenarios** | **~21 hr** | **~62**    |

### 7.3 OSC Job Script

Create `generate_scenarios.slurm`:

```bash
#!/bin/bash
#SBATCH --job-name=simforge_datagen
#SBATCH --account=<your_project>
#SBATCH --time=24:00:00
#SBATCH --nodes=3
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=48
#SBATCH --mem=180G
#SBATCH --cluster=pitzer

# Load modules
module load python/3.10
module load java/17

# Activate environment
source $HOME/simforge_env/bin/activate

# Set working directory
cd $HOME/SimForge

# Run city generation in parallel across nodes
# Node 0: NYC
# Node 1: LA
# Node 2: Chicago

if [ $SLURM_NODEID -eq 0 ]; then
    echo "Node 0: Generating NYC scenarios"
    python -m pipeline.scenariobuilder.generate_city_scenario \
        --city nyc --tier all --output scenarios/nyc --parallel 48
elif [ $SLURM_NODEID -eq 1 ]; then
    echo "Node 1: Generating LA scenarios"
    python -m pipeline.scenariobuilder.generate_city_scenario \
        --city la --tier all --output scenarios/la --parallel 48
elif [ $SLURM_NODEID -eq 2 ]; then
    echo "Node 2: Generating Chicago scenarios"
    python -m pipeline.scenariobuilder.generate_city_scenario \
        --city chicago --tier all --output scenarios/chicago --parallel 48
fi

wait
echo "All scenarios generated!"
```

### 7.4 Alternative: Array Job (Sequential)

If you prefer sequential generation with better fault tolerance:

```bash
#!/bin/bash
#SBATCH --job-name=simforge_gen
#SBATCH --account=<your_project>
#SBATCH --time=24:00:00
#SBATCH --nodes=1
#SBATCH --cpus-per-task=48
#SBATCH --mem=180G
#SBATCH --array=0-8
#SBATCH --cluster=pitzer

# Define scenarios
CITIES=("nyc" "nyc" "nyc" "la" "la" "la" "chicago" "chicago" "chicago")
TIERS=("50k" "500k" "5m" "50k" "500k" "5m" "50k" "500k" "5m")

CITY=${CITIES[$SLURM_ARRAY_TASK_ID]}
TIER=${TIERS[$SLURM_ARRAY_TASK_ID]}

module load python/3.10
source $HOME/simforge_env/bin/activate
cd $HOME/SimForge

echo "Generating ${CITY} tier ${TIER}"
python -m pipeline.scenariobuilder.generate_city_scenario \
    --city $CITY --tier $TIER \
    --output scenarios/${CITY}_tier${TIER} \
    --parallel 48
```

### 7.5 OSC Setup Instructions

```bash
# 1. Connect to OSC
ssh <username>@pitzer.osc.edu

# 2. Clone SimForge
cd $HOME
git clone <your-repo-url> SimForge
cd SimForge

# 3. Create Python environment
module load python/3.10
python -m venv $HOME/simforge_env
source $HOME/simforge_env/bin/activate
pip install -r requirements.txt

# 4. Install SUMO (if not available as module)
# Check: module spider sumo
# If available: module load sumo
# If not: install locally or use containers

# 5. Submit job
sbatch generate_scenarios.slurm

# 6. Monitor progress
squeue -u $username
sacct -j <job_id>
```

### 7.6 Cost Estimate (OSC)

OSC uses Service Units (SU):

- 1 SU = 1 core-hour

| Scenario Set | Core-Hours | Approx SUs |
| ------------ | ---------- | ---------- |
| All 50k      | 72         | 72         |
| All 500k     | 288        | 288        |
| All 5M       | 2,592      | 2,592      |
| **Total**    | **~3,000** | **~3,000** |

Academic allocations typically provide 50,000-200,000 SUs/year.

---

## 8. Reproducibility Guarantees

### 8.1 Deterministic Generation

| Component          | Seed                | Reproducible? |
| ------------------ | ------------------- | ------------- |
| Network extraction | N/A (deterministic) | ✅ Yes        |
| Signal inference   | N/A (deterministic) | ✅ Yes        |
| Demand generation  | `random.seed(42)`   | ✅ Yes        |
| Route assignment   | SUMO seed           | ✅ Yes        |

### 8.2 Version Pinning

```yaml
# Environment specification
python: 3.10+
sumo: 1.18+
osmium: 1.15+
```

### 8.3 Data Versioning

Each scenario tagged with:

- Generation timestamp
- Tool versions
- Git commit hash
- OSM extraction date

### 8.4 Regeneration Command

```bash
# Exact reproduction with same seed (each script uses seed=42 by default)
python scripts/generate_chicago_5k.py
python scripts/generate_nyc_5k.py
python scripts/generate_la_5k.py
```

---

## 9. Known Limitations

### 9.1 Network Limitations

| Limitation               | Impact                  | Mitigation                |
| ------------------------ | ----------------------- | ------------------------- |
| OSM data quality varies  | Missing lanes, speeds   | Use conservative defaults |
| No elevation data        | Flat network assumption | Accept for benchmarking   |
| Simplified intersections | Junction merging        | Trade-off for performance |

### 9.2 Demand Limitations

| Limitation                   | Impact                        | Mitigation                    |
| ---------------------------- | ----------------------------- | ----------------------------- |
| No real OD data              | May not match actual patterns | Consistent across simulators  |
| Uniform spatial distribution | Missing activity centers      | Future: weighted sampling     |
| Car-only                     | No transit, bike, walk        | Future: multi-modal           |
| No temporal variation        | Same pattern daily            | Future: day-of-week variation |

### 9.3 Signal Limitations

| Limitation         | Impact                        | Mitigation                   |
| ------------------ | ----------------------------- | ---------------------------- |
| Estimated timing   | May not match real operations | Consistent across simulators |
| No coordination    | Suboptimal arterial flow      | Future: signal coordination  |
| Static timing only | No adaptive control           | Future: actuated signals     |

---

## 10. Future Enhancements

### 10.1 Planned Improvements

1. **Real demand integration**: Census LODES, LEHD data
2. **Multi-modal demand**: Transit, bike, pedestrian trips
3. **Signal coordination**: Arterial green waves
4. **Population-weighted demand**: Based on census tracts
5. **Time-of-day variation**: Weekday vs weekend patterns

### 10.2 Data Quality Scoring

Future: automatic quality scoring for generated scenarios:

```python
quality_score = {
    "network_completeness": 0.95,  # % links with all attributes
    "demand_realism": 0.80,        # Gravity model fit
    "signal_coverage": 0.70,       # % intersections with signals
    "overall": 0.82
}
```

---

## Appendix A: City Centers (5K Scenarios)

| City    | Center Lat | Center Lon | Radius (km) | Nodes  | Links   |
| ------- | ---------- | ---------- | ----------- | ------ | ------- |
| Chicago | 41.8781    | -87.6298   | 4.0         | ~3,300 | ~8,400  |
| NYC     | 40.7580    | -73.9855   | 3.0         | ~1,900 | ~3,900  |
| LA      | 34.0522    | -118.2437  | 5.0         | ~6,300 | ~17,700 |

## Appendix B: File Size Estimates (5K Tier)

| City    | network.xml | demand.csv | signals.xml | Total Bundle |
| ------- | ----------- | ---------- | ----------- | ------------ |
| Chicago | ~3.5 MB     | ~300 KB    | ~400 KB     | ~5 MB        |
| NYC     | ~1.5 MB     | ~300 KB    | ~200 KB     | ~3 MB        |
| LA      | ~7.0 MB     | ~300 KB    | ~700 KB     | ~9 MB        |

## Appendix C: References

1. OpenStreetMap Contributors. (2024). OpenStreetMap. https://www.openstreetmap.org
2. Highway Capacity Manual 6th Edition. (2016). Transportation Research Board.
3. SUMO Documentation. https://sumo.dlr.de/docs/
4. Webster, F.V. (1958). Traffic Signal Settings. Road Research Technical Paper No. 39.
5. Ohio Supercomputer Center. https://www.osc.edu

---

_Document version: 1.0_  
_Last updated: January 2026_  
_Author: SimForge Team_
