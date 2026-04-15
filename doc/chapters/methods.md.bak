# Chapter 3: Methods

## 3.1 Overview

This chapter describes the SimForge framework—a reproducible, cross-simulator testing infrastructure for urban traffic simulation. The framework addresses three key challenges in simulator benchmarking:

1. **Input standardization**: Different simulators use incompatible input formats, making fair comparison difficult.
2. **Execution reproducibility**: Results vary based on hardware, software versions, and configuration details.
3. **Metric consistency**: Simulators report different output metrics, complicating cross-engine analysis.

SimForge solves these challenges through a canonical data schema, validated scenario bundles, deterministic adapter pipelines, and a unified execution harness.

---

## 3.2 Canonical Data Schema

### 3.2.1 Design Principles

The canonical schema serves as an intermediate representation between real-world transportation data and simulator-specific formats. Key design principles:

- **Simulator-agnostic**: No simulator-specific constructs in the canonical format
- **Minimal yet complete**: Include only attributes required by all target simulators
- **Deterministic conversion**: One canonical input produces exactly one simulator input
- **Validation-ready**: Schema supports automated consistency checking

### 3.2.2 Network Schema (`network.xml`)

The network schema defines the static road infrastructure as a directed graph.

**Structure:**

```xml
<network>
  <metadata crs="EPSG:4326" units_length="meters" units_speed="m/s" source="OSM"/>
  <nodes>
    <node id="n1" x="0.0" y="0.0" type="intersection"/>
  </nodes>
  <links>
    <link id="l1" from="n1" to="n2" length="100.0" lanes="2"
          speed_limit="13.9" capacity_veh_per_hour="1800" road_type="arterial"/>
  </links>
</network>
```

**Required attributes:**

| Element    | Attribute      | Type   | Description                                     |
| ---------- | -------------- | ------ | ----------------------------------------------- |
| `metadata` | `crs`          | string | Coordinate reference system (e.g., `EPSG:4326`) |
| `metadata` | `units_length` | string | Length unit (typically `meters`)                |
| `metadata` | `units_speed`  | string | Speed unit (typically `m/s`)                    |
| `node`     | `id`           | string | Unique node identifier                          |
| `node`     | `x`, `y`       | float  | Coordinates in declared CRS                     |
| `link`     | `id`           | string | Unique link identifier                          |
| `link`     | `from`, `to`   | string | Source and target node IDs                      |
| `link`     | `length`       | float  | Link length in `units_length`                   |
| `link`     | `lanes`        | int    | Number of lanes (≥1)                            |
| `link`     | `speed_limit`  | float  | Free-flow speed in `units_speed`                |

### 3.2.3 Demand Schema (`demand.csv`)

Travel demand is represented as individual trips with origin-destination pairs.

**Structure:**

```csv
trip_id,origin_node_id,destination_node_id,departure_time_s,mode
trip_001,n1,n4,28800,car
trip_002,n2,n5,29100,car
```

**Required columns:**

| Column                | Type   | Description                             |
| --------------------- | ------ | --------------------------------------- |
| `trip_id`             | string | Unique trip identifier                  |
| `origin_node_id`      | string | Starting node (must exist in network)   |
| `destination_node_id` | string | Ending node (must exist in network)     |
| `departure_time_s`    | int    | Departure time in seconds from midnight |
| `mode`                | string | Travel mode (`car`, `truck`, etc.)      |

### 3.2.4 Signals Schema (`signals.xml`)

Traffic signal timing is defined per junction with phase-based control.

**Structure:**

```xml
<signals>
  <junction id="n2" cycle_length_s="60">
    <phase duration_s="30">
      <green link_id="l1"/>
    </phase>
    <phase duration_s="30">
      <green link_id="l2"/>
    </phase>
  </junction>
</signals>
```

### 3.2.5 Configuration Schema (`config.xml`)

Scenario metadata and simulation parameters.

**Structure:**

```xml
<config>
  <scenario id="sioux_falls_tier50k" city="Sioux Falls" tier="50k"/>
  <simulation horizon_start_s="0" horizon_end_s="86400" time_step_s="1"/>
  <parameters random_seed="42"/>
  <schema version="0"/>
</config>
```

### 3.2.6 Manifest Schema (`manifest.xml`)

File inventory with integrity verification via SHA-256 hashes.

**Structure:**

```xml
<manifest>
  <file name="network.xml" role="network" sha256="abc123..."/>
  <file name="demand.csv" role="demand" sha256="def456..."/>
  <generator tool="simforge" version="1.0"/>
</manifest>
```

---

## 3.3 Scenario Validation

### 3.3.1 Validation Rules

The validator enforces cross-file consistency through the following checks:

1. **Structural integrity**: All required files exist and parse correctly
2. **Referential integrity**:
   - All `origin_node_id` and `destination_node_id` in demand exist in network
   - All signal junction IDs exist in network
   - All signal link references exist in network
3. **Schema compliance**: Required attributes present with valid types
4. **Hash verification**: File contents match SHA-256 hashes in manifest

### 3.3.2 Validation Implementation

```python
# Simplified validation logic
def validate_bundle(scenario_path: Path) -> ValidationResult:
    network = parse_network(scenario_path / "network.xml")
    demand = parse_demand(scenario_path / "demand.csv")
    signals = parse_signals(scenario_path / "signals.xml")
    config = parse_config(scenario_path / "config.xml")
    manifest = parse_manifest(scenario_path / "manifest.xml")

    errors = []

    # Check demand references
    node_ids = {n.id for n in network.nodes}
    for trip in demand.trips:
        if trip.origin_node_id not in node_ids:
            errors.append(f"Unknown origin: {trip.origin_node_id}")
        if trip.destination_node_id not in node_ids:
            errors.append(f"Unknown destination: {trip.destination_node_id}")

    # Check signal references
    for junction in signals.junctions:
        if junction.id not in node_ids:
            errors.append(f"Unknown signal junction: {junction.id}")

    # Verify hashes
    for file_entry in manifest.files:
        actual_hash = compute_sha256(scenario_path / file_entry.name)
        if actual_hash != file_entry.sha256:
            errors.append(f"Hash mismatch: {file_entry.name}")

    return ValidationResult(valid=len(errors) == 0, errors=errors)
```

---

## 3.4 Simulator Adapters

### 3.4.1 Adapter Architecture

Each adapter implements a common interface:

```python
class SimulatorAdapter(Protocol):
    def prepare_inputs(self, scenario_path: Path, output_dir: Path) -> None:
        """Convert canonical bundle to simulator-specific inputs."""

    def run_simulation(self, config_path: Path, **kwargs) -> SimulationResult:
        """Execute the simulator and return results."""

    def parse_outputs(self, output_dir: Path) -> SimulationMetrics:
        """Extract metrics from simulator outputs."""
```

### 3.4.2 SUMO Adapter

**SUMO** (Simulation of Urban Mobility) is a microscopic traffic simulator that models individual vehicles with car-following and lane-changing behavior.

**Conversion pipeline:**

```
CANONICAL                        SUMO
───────────────────────────────────────────
network.xml  ──► nodes.nod.xml ─┐
                 edges.edg.xml ─┴─► netconvert ──► net.net.xml
demand.csv   ──► routes.rou.xml (with BFS routing)
signals.xml  ──► (embedded in net.net.xml)
config.xml   ──► scenario.sumocfg
```

**Key mapping decisions:**

| Canonical          | SUMO              | Notes                         |
| ------------------ | ----------------- | ----------------------------- |
| `node.type`        | `node.type`       | Maps to `priority` by default |
| `link.speed_limit` | `edge.speed`      | Direct copy (m/s)             |
| `link.lanes`       | `edge.numLanes`   | Direct copy                   |
| Trip routing       | BFS shortest path | Computed at conversion time   |

**Mesoscopic mode**: SUMO supports mesoscopic simulation via `--mesosim` flag, which uses queue-based link traversal instead of car-following.

### 3.4.3 QarSUMO Adapter

**QarSUMO** is a GPU-accelerated variant of SUMO that offloads car-following computations to CUDA-enabled GPUs.

The QarSUMO adapter reuses the SUMO adapter's conversion pipeline, adding GPU-specific configuration:

```xml
<!-- QarSUMO additional config -->
<processing>
  <qarsumo.gpu-device value="0"/>
  <qarsumo.batch-size value="1024"/>
</processing>
```

**Fallback behavior**: When QarSUMO binary is unavailable, the adapter falls back to standard SUMO execution with a warning.

### 3.4.4 MATSim Adapter

**MATSim** (Multi-Agent Transport Simulation) is an activity-based, mesoscopic simulator that models agents executing daily activity plans.

**Conversion pipeline:**

```
CANONICAL                        MATSIM
───────────────────────────────────────────
network.xml  ──► network.xml (MATSim format)
demand.csv   ──► plans.xml (activity chains)
config.xml   ──► config.xml (MATSim config)
```

**Key differences from SUMO:**

| Aspect                | SUMO          | MATSim                   |
| --------------------- | ------------- | ------------------------ |
| Unit of simulation    | Vehicle       | Agent (person)           |
| Demand representation | OD trips      | Activity plans           |
| Traffic flow model    | Car-following | Queue-based              |
| Typical iterations    | 1             | Multiple with replanning |

**Demand conversion**: Each canonical trip becomes a 2-activity plan:

```xml
<person id="person_trip_001">
  <plan selected="yes">
    <activity type="home" link="l_near_origin" end_time="08:00:00"/>
    <leg mode="car"/>
    <activity type="work" link="l_near_destination"/>
  </plan>
</person>
```

**Single-iteration mode**: For fair comparison with SUMO, MATSim is configured with `lastIteration=0`, disabling replanning.

---

## 3.5 Execution Harness

### 3.5.1 Run Specification

Benchmark runs are defined via YAML runspec files:

```yaml
name: thesis_benchmark_matrix
description: "Full experimental matrix for thesis"

scenarios:
  - id: sioux_falls_tier50k
    path: scenarios/sioux_falls_tier50k
  - id: austin_tier50k
    path: scenarios/austin_tier50k
  - id: berlin_tier50k
    path: scenarios/berlin_tier50k

engines:
  - name: sumo
    modes: [microscopic, mesoscopic]
  - name: qarsumo
    modes: [microscopic, mesoscopic]
  - name: matsim
    modes: [mesoscopic]

repeats: 3
seeds: [42, 43, 44]
```

### 3.5.2 Execution Pipeline

```python
def run_benchmark(runspec_path: Path) -> BenchmarkResult:
    runspec = load_runspec(runspec_path)
    results = []

    for scenario in runspec.scenarios:
        # Validate canonical bundle
        validate_bundle(scenario.path)

        for engine in runspec.engines:
            adapter = get_adapter(engine.name)

            for mode in engine.modes:
                for seed in runspec.seeds:
                    # Prepare inputs
                    run_dir = f"runs/{scenario.id}/{engine.name}/{mode}/seed_{seed}"
                    adapter.prepare_inputs(scenario.path, run_dir)

                    # Execute
                    start_time = time.time()
                    result = adapter.run_simulation(run_dir, seed=seed, mode=mode)
                    elapsed = time.time() - start_time

                    # Collect metrics
                    metrics = adapter.parse_outputs(run_dir)
                    results.append(RunResult(
                        scenario=scenario.id,
                        engine=engine.name,
                        mode=mode,
                        seed=seed,
                        runtime_s=elapsed,
                        metrics=metrics
                    ))

    return BenchmarkResult(runs=results)
```

### 3.5.3 Output Structure

```
runs/
├── sioux_falls_tier50k/
│   ├── sumo/
│   │   ├── microscopic/
│   │   │   ├── seed_42/
│   │   │   │   ├── net.net.xml
│   │   │   │   ├── routes.rou.xml
│   │   │   │   ├── scenario.sumocfg
│   │   │   │   └── output/
│   │   │   │       ├── tripinfo.xml
│   │   │   │       └── summary.xml
│   │   │   ├── seed_43/
│   │   │   └── seed_44/
│   │   └── mesoscopic/
│   ├── qarsumo/
│   └── matsim/
├── austin_tier50k/
└── berlin_tier50k/
```

---

## 3.6 Evaluation Metrics

### 3.6.1 Fidelity Metrics

**Root Mean Square Error (RMSE)**:
$$\text{RMSE} = \sqrt{\frac{1}{n}\sum_{i=1}^{n}(y_i - \hat{y}_i)^2}$$

**GEH Statistic** (traffic engineering standard):
$$\text{GEH} = \sqrt{\frac{2(M - C)^2}{M + C}}$$
where $M$ is the modeled value and $C$ is the count/observed value.

**Kolmogorov-Smirnov Statistic**:
$$D = \sup_x |F_1(x) - F_2(x)|$$
comparing empirical CDFs of travel time distributions.

### 3.6.2 Scalability Metrics

**Runtime**: Wall-clock time for simulation execution (excluding I/O).

**Throughput**:
$$\text{Throughput} = \frac{\text{Total vehicles simulated}}{\text{Runtime (seconds)}}$$

**Scaling efficiency**:
$$\text{Efficiency} = \frac{T_1}{p \cdot T_p}$$
where $T_1$ is single-core runtime, $T_p$ is $p$-core runtime.

### 3.6.3 Reproducibility Metric

**Coefficient of Reproducibility**:
$$R = 1 - \frac{\sigma}{\mu}$$
where $\sigma$ is standard deviation and $\mu$ is mean across repeated runs with different seeds.

Values close to 1 indicate high reproducibility; values near 0 indicate high variability.

---

## 3.7 Implementation Details

### 3.7.1 Technology Stack

- **Python 3.10+**: Core framework implementation
- **lxml**: XML parsing and generation
- **pandas**: Demand data processing
- **pydantic**: Schema validation
- **osmnx/networkx**: Network extraction from OpenStreetMap
- **SUMO 1.20**: Microscopic/mesoscopic simulation
- **MATSim 15.0**: Activity-based simulation
- **Java 17**: MATSim runtime

### 3.7.2 Determinism Guarantees

To ensure reproducibility:

1. **Fixed random seeds**: All stochastic processes seeded via `config.xml`
2. **Sorted outputs**: All generated files use sorted iteration over sets/dicts
3. **Hash verification**: Manifest SHA-256 checksums detect input drift
4. **Version pinning**: Requirements specify exact package versions

### 3.7.3 Containerization (Future Work)

For HPC deployment, Docker containers will encapsulate simulator dependencies:

```dockerfile
FROM ubuntu:22.04
RUN apt-get install -y sumo sumo-tools
COPY simforge/ /app/
ENTRYPOINT ["python", "-m", "execution.run_benchmark"]
```
