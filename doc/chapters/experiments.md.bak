# Chapter 4: Experiments

## 4.1 Experimental Design

### 4.1.1 Research Questions

This experimental study addresses the following research questions:

1. **RQ1 (Fidelity)**: How do travel time distributions compare across simulators for identical inputs?
2. **RQ2 (Scalability)**: How does runtime scale with network size and demand volume across engines?
3. **RQ3 (Reproducibility)**: How consistent are results across repeated runs with different random seeds?
4. **RQ4 (Trade-offs)**: What are the practical trade-offs between fidelity, speed, and reproducibility?

### 4.1.2 Independent Variables

**Simulator Engines:**
| Engine | Type | Traffic Model | Hardware |
|--------|------|---------------|----------|
| SUMO (micro) | Microscopic | Car-following + lane-changing | CPU |
| SUMO (meso) | Mesoscopic | Queue-based links | CPU |
| QarSUMO (micro) | Microscopic | GPU-accelerated car-following | GPU |
| QarSUMO (meso) | Mesoscopic | GPU-accelerated queues | GPU |
| MATSim | Mesoscopic | Activity-based, queue model | CPU |

**Scenario Scale:**
| Tier | Trips | Description |
|------|-------|-------------|
| 50k | 50,000 | Small-scale validation |
| 500k | 500,000 | Medium-scale stress test |
| 5M | 5,000,000 | Large-scale performance |

**City Networks:**
| City | Nodes | Links | Characteristics |
|------|-------|-------|-----------------|
| Sioux Falls | ~3,000 | ~7,000 | Small grid, benchmark standard |
| Austin, TX | ~45,000 | ~110,000 | Medium sprawl, arterial-heavy |
| Berlin | ~40,000 | ~103,000 | Medium dense, mixed road types |

### 4.1.3 Dependent Variables

**Fidelity metrics:**

- Mean travel time (seconds)
- Travel time distribution (via KS statistic)
- Link-level volume RMSE

**Scalability metrics:**

- Wall-clock runtime (seconds)
- Throughput (vehicles/second)
- Memory usage (peak GB)

**Reproducibility metrics:**

- Coefficient of reproducibility $R = 1 - \sigma/\mu$
- Max deviation across seeds

### 4.1.4 Experimental Matrix

Full experimental design: **3 cities × 3 tiers × 5 engine-modes × 3 seeds = 135 runs**

For the thesis, we execute a focused subset:

| Phase      | Cities      | Tiers     | Engines | Seeds | Total Runs |
| ---------- | ----------- | --------- | ------- | ----- | ---------- |
| Validation | All 3       | 50k       | All 5   | 3     | 45         |
| Scale-up   | Sioux Falls | All 3     | All 5   | 3     | 45         |
| Production | All 3       | 50k, 500k | All 5   | 3     | 90         |

---

## 4.2 Scenario Descriptions

### 4.2.1 Sioux Falls Network

The Sioux Falls network is a standard transportation research benchmark representing a mid-size American city.

**Network characteristics:**

- **Nodes**: 2,958 (intersections and endpoints)
- **Links**: 7,132 (directed road segments)
- **Total length**: 1,847 km
- **Source**: OpenStreetMap extraction via osmnx

**Demand generation:**

- Synthetic OD pairs based on population-weighted centroids
- Departure times: Uniform 6:00-9:00 AM peak
- Mode: 100% car (private vehicle)

### 4.2.2 Austin, TX Network

Austin represents a sprawling American sunbelt city with arterial-dominated road structure.

**Network characteristics:**

- **Nodes**: 44,861
- **Links**: 110,533
- **Total length**: 12,340 km
- **Source**: OpenStreetMap (bounding box: downtown + major suburbs)

**Notable features:**

- Highway network (I-35, MoPac, Loop 1)
- Large arterial grid
- Limited transit (excluded from this study)

### 4.2.3 Berlin Network

Berlin represents a dense European city with mixed road types and complex intersections.

**Network characteristics:**

- **Nodes**: 39,866
- **Links**: 103,309
- **Total length**: 8,920 km
- **Source**: OpenStreetMap (city boundary)

**Notable features:**

- Mixed grid and radial structure
- Dense inner city (Mitte, Kreuzberg)
- Suburban areas (Spandau, Marzahn)

---

## 4.3 Execution Environment

### 4.3.1 Hardware Specifications

**Development/Testing:**

- MacBook Pro M1/M2 (Apple Silicon)
- 16 GB RAM
- No discrete GPU (QarSUMO falls back to SUMO)

**Production runs (planned):**

- HPC cluster nodes with NVIDIA GPUs
- 128 GB RAM
- CUDA 12.0+

### 4.3.2 Software Versions

| Software | Version      | Notes                    |
| -------- | ------------ | ------------------------ |
| Python   | 3.13.2       | Framework implementation |
| SUMO     | 1.20.0       | via Homebrew             |
| MATSim   | 15.0         | JAR distribution         |
| Java     | 17 (Temurin) | MATSim runtime           |
| QarSUMO  | N/A          | Requires CUDA GPU        |

### 4.3.3 Execution Protocol

1. **Validation**: Run `validate_bundle.py` on scenario
2. **Conversion**: Generate simulator-specific inputs
3. **Warm-up**: Discard first run (JIT compilation, caching)
4. **Measurement**: 3 runs with seeds 42, 43, 44
5. **Collection**: Extract metrics from output files

---

## 4.4 Results Tables (Template)

### 4.4.1 Runtime Comparison (50k tier)

| City        | SUMO μ | SUMO m | QarSUMO μ | QarSUMO m | MATSim |
| ----------- | ------ | ------ | --------- | --------- | ------ |
| Sioux Falls | _TBD_  | _TBD_  | _TBD_     | _TBD_     | _TBD_  |
| Austin      | _TBD_  | _TBD_  | _TBD_     | _TBD_     | _TBD_  |
| Berlin      | _TBD_  | _TBD_  | _TBD_     | _TBD_     | _TBD_  |

_μ = microscopic, m = mesoscopic_

### 4.4.2 Travel Time Statistics (50k tier)

| City        | Engine | Mean (s) | Std (s) | Median (s) | P95 (s) |
| ----------- | ------ | -------- | ------- | ---------- | ------- |
| Sioux Falls | SUMO μ | _TBD_    | _TBD_   | _TBD_      | _TBD_   |
| Sioux Falls | SUMO m | _TBD_    | _TBD_   | _TBD_      | _TBD_   |
| Sioux Falls | MATSim | _TBD_    | _TBD_   | _TBD_      | _TBD_   |
| Austin      | SUMO μ | _TBD_    | _TBD_   | _TBD_      | _TBD_   |
| ...         | ...    | ...      | ...     | ...        | ...     |

### 4.4.3 Reproducibility (Coefficient R)

| City        | SUMO μ | SUMO m | QarSUMO μ | QarSUMO m | MATSim |
| ----------- | ------ | ------ | --------- | --------- | ------ |
| Sioux Falls | _TBD_  | _TBD_  | _TBD_     | _TBD_     | _TBD_  |
| Austin      | _TBD_  | _TBD_  | _TBD_     | _TBD_     | _TBD_  |
| Berlin      | _TBD_  | _TBD_  | _TBD_     | _TBD_     | _TBD_  |

### 4.4.4 Scaling Analysis (Sioux Falls)

| Tier | SUMO μ (s) | SUMO m (s) | MATSim (s) | Speedup (m vs μ) |
| ---- | ---------- | ---------- | ---------- | ---------------- |
| 50k  | _TBD_      | _TBD_      | _TBD_      | _TBD_            |
| 500k | _TBD_      | _TBD_      | _TBD_      | _TBD_            |
| 5M   | _TBD_      | _TBD_      | _TBD_      | _TBD_            |

---

## 4.5 Planned Figures

### 4.5.1 Figure List

1. **Travel time distributions** (CDF comparison across engines)
2. **Runtime bar chart** (grouped by city, colored by engine)
3. **Scaling curves** (log-log plot: trips vs runtime)
4. **Reproducibility heatmap** (engine × city matrix)
5. **Trade-off scatter plot** (runtime vs fidelity, sized by reproducibility)

### 4.5.2 Figure Specifications

**Figure 1: Travel Time CDFs**

- X-axis: Travel time (seconds)
- Y-axis: Cumulative probability
- Lines: One per engine (5 lines)
- Panels: One per city (3 panels)

**Figure 2: Runtime Comparison**

- X-axis: City
- Y-axis: Runtime (seconds, log scale)
- Bars: Grouped by engine-mode
- Error bars: Min-max across seeds

**Figure 3: Scaling Behavior**

- X-axis: Number of trips (log scale)
- Y-axis: Runtime (seconds, log scale)
- Lines: One per engine
- Expected: Linear scaling (slope ≈ 1)

---

## 4.6 Preliminary Results

### 4.6.1 Toy Scenario Validation

The 2×2 grid toy scenario (6 trips) validates adapter correctness:

| Engine    | Runtime (s) | Mean Travel Time (s) | Status  |
| --------- | ----------- | -------------------- | ------- |
| SUMO μ    | 0.03        | 21.5                 | ✓ Valid |
| SUMO m    | 0.03        | 20.8                 | ✓ Valid |
| QarSUMO\* | 0.03        | 21.5                 | ✓ Valid |
| MATSim    | 7.0         | 21.0                 | ✓ Valid |

\*QarSUMO falls back to SUMO without GPU

### 4.6.2 Initial 50k Results (Sioux Falls)

Preliminary runs on Sioux Falls 50k tier (single seed):

| Engine | Mode        | Runtime (s) | Vehicles/sec |
| ------ | ----------- | ----------- | ------------ |
| SUMO   | microscopic | ~120        | ~417         |
| SUMO   | mesoscopic  | ~15         | ~3,333       |
| MATSim | mesoscopic  | ~45         | ~1,111       |

**Observations:**

- Mesoscopic SUMO achieves 8× speedup over microscopic
- MATSim slower than SUMO meso due to Java overhead and activity handling
- All engines complete successfully with validated bundles

---

## 4.7 Threats to Validity

### 4.7.1 Internal Validity

- **Configuration bias**: Default parameters may favor certain engines
- **Routing differences**: BFS routing (SUMO) vs native routing (MATSim)
- **Warm-up effects**: JVM warm-up for MATSim

**Mitigations:**

- Use engine-recommended defaults
- Document all configuration choices
- Include warm-up runs in protocol

### 4.7.2 External Validity

- **Network selection**: Three cities may not represent all urban forms
- **Demand synthesis**: Synthetic demand lacks real-world patterns
- **Mode limitation**: Car-only excludes transit/active modes

**Mitigations:**

- Select diverse city types (American/European, sprawl/dense)
- Use standard demand generation methods
- Note limitations in discussion

### 4.7.3 Construct Validity

- **Fidelity definition**: No ground truth for comparison
- **Scalability measurement**: Wall-clock time varies by hardware

**Mitigations:**

- Compare simulators to each other (relative fidelity)
- Report hardware specifications and normalize where possible
