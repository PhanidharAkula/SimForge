# MATSim Adapter Mapping

## Overview

MATSim (Multi-Agent Transport Simulation) is an activity-based, mesoscopic traffic simulator that models individual agents and their daily activity plans. Unlike SUMO which simulates vehicles on links, MATSim simulates agents making activity-travel decisions.

**Key Reference**: MATSim: The Multi-Agent Transport Simulation (Horni et al., 2016)

## Fundamental Differences from SUMO

| Aspect             | SUMO                     | MATSim                          |
| ------------------ | ------------------------ | ------------------------------- |
| Unit of simulation | Vehicle                  | Agent (person)                  |
| Modeling approach  | Network-based            | Activity-based                  |
| Traffic flow       | Microscopic/Mesoscopic   | Queue-based mesoscopic          |
| Typical use        | Traffic engineering      | Urban planning, policy          |
| Input format       | XML (.net.xml, .rou.xml) | XML (network.xml, plans.xml)    |
| Iteration          | Single run               | Multi-iteration with replanning |

## Canonical → MATSim Mapping

### 1. Network Mapping

**Canonical network.xml → MATSim network.xml**

```xml
<!-- Canonical format -->
<network>
  <nodes>
    <node id="n1" x="0" y="0"/>
  </nodes>
  <links>
    <link id="l1" from="n1" to="n2" length="100" speed_limit="13.9" lanes="2"/>
  </links>
</network>

<!-- MATSim format -->
<network>
  <nodes>
    <node id="n1" x="0.0" y="0.0"/>
  </nodes>
  <links>
    <link id="l1" from="n1" to="n2"
          length="100.0"
          freespeed="13.9"
          capacity="1800"
          permlanes="2.0"
          modes="car"/>
  </links>
</network>
```

**Mapping Rules:**
| Canonical | MATSim | Notes |
|-----------|--------|-------|
| `node.id` | `node.id` | Direct mapping |
| `node.x`, `node.y` | `node.x`, `node.y` | Direct mapping (assumes same CRS) |
| `link.id` | `link.id` | Direct mapping |
| `link.from`, `link.to` | `link.from`, `link.to` | Direct mapping |
| `link.length` | `link.length` | In meters |
| `link.speed_limit` | `link.freespeed` | m/s |
| `link.lanes` | `link.permlanes` | Float in MATSim |
| (computed) | `link.capacity` | `lanes * 1800` veh/hour default |
| (default) | `link.modes` | "car" for now |

### 2. Demand Mapping

**Canonical demand.csv → MATSim plans.xml**

MATSim uses "plans" which are activity chains for agents, not simple OD trips.

```csv
# Canonical demand.csv
trip_id,origin_node_id,destination_node_id,departure_time_s,mode
trip_1,n1,n4,28800,car
```

```xml
<!-- MATSim plans.xml -->
<population>
  <person id="person_trip_1">
    <plan selected="yes">
      <activity type="home" link="l_near_n1" end_time="08:00:00"/>
      <leg mode="car"/>
      <activity type="work" link="l_near_n4"/>
    </plan>
  </person>
</population>
```

**Mapping Rules:**

- Each trip becomes a person with a 2-activity plan (home → work)
- `origin_node_id` → find nearest link → `home` activity location
- `destination_node_id` → find nearest link → `work` activity location
- `departure_time_s` → `end_time` of first activity (seconds → HH:MM:SS)
- `mode` → `leg.mode`

### 3. Signals Mapping

MATSim has a separate signals extension. For v0, we can:

1. **Skip signals** - MATSim's queue model handles capacity constraints
2. **Future**: Map to MATSim's `signalSystems.xml`, `signalGroups.xml`, `signalControl.xml`

### 4. Config Mapping

**Canonical config.xml → MATSim config.xml**

```xml
<!-- MATSim config.xml -->
<config>
  <module name="global">
    <param name="randomSeed" value="42"/>
    <param name="coordinateSystem" value="EPSG:4326"/>
  </module>

  <module name="network">
    <param name="inputNetworkFile" value="network.xml"/>
  </module>

  <module name="plans">
    <param name="inputPlansFile" value="plans.xml"/>
  </module>

  <module name="qsim">
    <param name="startTime" value="00:00:00"/>
    <param name="endTime" value="30:00:00"/>
    <param name="flowCapacityFactor" value="1.0"/>
    <param name="storageCapacityFactor" value="1.0"/>
  </module>

  <module name="controler">
    <param name="outputDirectory" value="./output"/>
    <param name="firstIteration" value="0"/>
    <param name="lastIteration" value="0"/>  <!-- Single iteration for comparison -->
  </module>

  <module name="planCalcScore">
    <!-- Scoring parameters -->
  </module>
</config>
```

**Key Differences:**

- MATSim typically runs multiple iterations with replanning
- For fair comparison with SUMO, we run **single iteration** (`lastIteration=0`)
- This disables replanning, making it closer to a single-pass simulation

## Output Format

MATSim produces:

- `output_events.xml.gz` - Timestamped events (vehicle enters/leaves link, activity starts/ends)
- `output_legs.csv.gz` - Per-leg travel information
- `output_trips.csv.gz` - Per-trip summary

**Extracting Travel Times:**

```python
# From output_trips.csv
# Columns: person, trip_number, trip_id, dep_time, trav_time, wait_time, ...
# trav_time is in HH:MM:SS format
```

## Execution

```bash
# Run MATSim (requires Java)
java -Xmx4g -cp matsim.jar org.matsim.run.Controler config.xml

# Or using MATSim's built-in runner
matsim run config.xml
```

## Environment Requirements

| Component | Requirement              |
| --------- | ------------------------ |
| Java      | JDK 11+ (17 recommended) |
| MATSim    | 14.0+                    |
| Memory    | 4GB+ for 50K agents      |

## Installation

```bash
# Download MATSim release
wget https://github.com/matsim-org/matsim-libs/releases/download/v14.0/matsim-14.0.zip
unzip matsim-14.0.zip

# Or via Maven for custom builds
```

## Expected Performance

| Scenario Size | SUMO (meso) | MATSim (1 iter) | Notes                    |
| ------------- | ----------- | --------------- | ------------------------ |
| 50K trips     | ~5 sec      | ~30 sec         | MATSim has more overhead |
| 500K trips    | ~1 min      | ~5 min          | Scales linearly          |
| 5M trips      | ~10 min     | ~1 hour         | Memory becomes factor    |

## Validation Strategy

1. Run both SUMO (mesoscopic) and MATSim on same scenario
2. Extract travel times from both outputs
3. Compute fidelity metrics:
   - RMSE of travel times
   - Distribution comparison (KS test)
   - Correlation coefficient
