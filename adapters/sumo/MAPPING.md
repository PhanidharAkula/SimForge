# SUMO Adapter Mapping Documentation

This document describes how SimForge canonical schema files are translated into SUMO-specific input files.

## Overview

The SUMO adapter performs a deterministic, one-to-one mapping from the canonical scenario bundle to SUMO's native XML formats.

```
CANONICAL                          SUMO
─────────────────────────────────────────────────────
network.xml  ───┬──►  nodes.nod.xml
                │     edges.edg.xml
                └──►  net.net.xml (via netconvert)

demand.csv   ──────►  routes.rou.xml

signals.xml  ──────►  (embedded in net.net.xml)

config.xml   ──────►  toy.sumocfg
```

---

## Network Mapping

### Nodes: `network.xml` → `nodes.nod.xml`

| Canonical Attribute | SUMO Attribute | Transformation                 |
| ------------------- | -------------- | ------------------------------ |
| `node/@id`          | `node/@id`     | Direct copy                    |
| `node/@x`           | `node/@x`      | Direct copy                    |
| `node/@y`           | `node/@y`      | Direct copy                    |
| `node/@type`        | `node/@type`   | Maps to `"priority"` (default) |

**Example:**

Canonical:

```xml
<node id="n1" x="0.0" y="0.0" type="intersection" />
```

SUMO:

```xml
<node id="n1" x="0.0" y="0.0" type="priority"/>
```

### Links: `network.xml` → `edges.edg.xml`

| Canonical Attribute | SUMO Attribute           | Transformation      |
| ------------------- | ------------------------ | ------------------- |
| `link/@id`          | `edge/@id`               | Direct copy         |
| `link/@from`        | `edge/@from`             | Direct copy         |
| `link/@to`          | `edge/@to`               | Direct copy         |
| `link/@lanes`       | `edge/@numLanes`         | Direct copy         |
| `link/@speed_limit` | `edge/@speed`            | Direct copy (m/s)   |
| `link/@length`      | (computed by netconvert) | Not directly mapped |

**Example:**

Canonical:

```xml
<link id="l1" from="n1" to="n2" length="100.0" lanes="1" speed_limit="13.9" />
```

SUMO:

```xml
<edge id="l1" from="n1" to="n2" numLanes="1" speed="13.9"/>
```

### Network Generation: `netconvert`

The adapter uses SUMO's `netconvert` tool to build the final network:

```bash
netconvert --node-files nodes.nod.xml \
           --edge-files edges.edg.xml \
           --output-file net.net.xml \
           --no-turnarounds
```

This generates:

- Junction geometry and connections
- Lane-level detail
- Internal edges for turning movements
- Traffic light programs (from signals.xml)

---

## Demand Mapping

### Trips: `demand.csv` → `routes.rou.xml`

| Canonical Column      | SUMO Element/Attribute | Transformation            |
| --------------------- | ---------------------- | ------------------------- |
| `trip_id`             | `vehicle/@id`          | Prefixed with `veh_`      |
| `origin_node_id`      | (route computation)    | Used as BFS start         |
| `destination_node_id` | (route computation)    | Used as BFS end           |
| `departure_time_s`    | `vehicle/@depart`      | Direct copy (seconds)     |
| `mode`                | `vehicle/@type`        | `car` → `DEFAULT_VEHTYPE` |

### Route Computation

The adapter computes routes using **BFS shortest path** on the network graph:

1. Build adjacency list from canonical links
2. For each trip, run BFS from origin to destination
3. Convert node path to edge IDs
4. Embed route directly in vehicle element

**Example:**

Canonical (`demand.csv`):

```csv
trip_id,origin_node_id,destination_node_id,departure_time_s,mode
t1,n1,n4,0,car
```

Route computation:

```
BFS(n1 → n4) = [n1, n2, n4]
Edge path = [l1, l7]  (n1→n2, n2→n4)
```

SUMO (`routes.rou.xml`):

```xml
<vehicle id="veh_t1" depart="0">
  <route edges="l1 l7"/>
</vehicle>
```

---

## Signals Mapping

### Traffic Lights: `signals.xml` → SUMO TLS

| Canonical Attribute        | SUMO Attribute    | Transformation                |
| -------------------------- | ----------------- | ----------------------------- |
| `junction/@id`             | `tlLogic/@id`     | Direct copy                   |
| `junction/@cycle_length_s` | (sum of phases)   | Implicit                      |
| `phase/@duration_s`        | `phase/@duration` | Direct copy                   |
| `phase/@state`             | `phase/@state`    | Direct copy (SUMO convention) |

**Note:** Currently, signals are not yet fully integrated into the netconvert pipeline. The adapter parses them for summary purposes, but full TLS generation is planned for a future version.

**State encoding (SUMO convention):**

- `G` = Green (protected)
- `g` = Green (permissive)
- `y` = Yellow
- `r` = Red

---

## Configuration Mapping

### Simulation Config: `config.xml` → `toy.sumocfg`

| Canonical Element    | SUMO Element        | Transformation |
| -------------------- | ------------------- | -------------- |
| `time/@start_time_s` | `time/begin/@value` | Direct copy    |
| `time/@end_time_s`   | `time/end/@value`   | Direct copy    |
| `random/@seed`       | (not yet mapped)    | Planned        |

**Generated SUMO config:**

```xml
<configuration>
  <input>
    <net-file value="net.net.xml" />
    <route-files value="routes.rou.xml" />
  </input>
  <time>
    <begin value="0" />
    <end value="3600" />
  </time>
  <output>
    <tripinfo-output value="tripinfo.xml" />
  </output>
</configuration>
```

---

## Units

| Quantity    | Canonical Unit | SUMO Unit     | Conversion |
| ----------- | -------------- | ------------- | ---------- |
| Length      | meters         | meters        | None       |
| Speed       | m/s            | m/s           | None       |
| Time        | seconds        | seconds       | None       |
| Coordinates | CRS-dependent  | CRS-dependent | None       |

---

## Output Files

The adapter generates the following files in the output directory:

| File             | Description                       | Source      |
| ---------------- | --------------------------------- | ----------- |
| `nodes.nod.xml`  | SUMO node definitions             | network.xml |
| `edges.edg.xml`  | SUMO edge definitions             | network.xml |
| `net.net.xml`    | Complete SUMO network             | netconvert  |
| `routes.rou.xml` | Vehicle routes                    | demand.csv  |
| `toy.sumocfg`    | Simulation configuration          | config.xml  |
| `tripinfo.xml`   | **(Output)** Trip completion data | SUMO run    |

---

## Determinism Guarantees

The adapter ensures deterministic output through:

1. **Sorted iteration:** Nodes and edges are processed in sorted order by ID
2. **Consistent BFS:** Route computation uses deterministic graph traversal
3. **Fixed netconvert flags:** Same flags produce same network structure
4. **No random sampling:** All mappings are one-to-one

To verify determinism:

```bash
# Run adapter twice
python -m adapters.sumo.cli scenarios/toy_2x2_grid out/run1
python -m adapters.sumo.cli scenarios/toy_2x2_grid out/run2

# Compare outputs (should be identical except for netconvert timestamp)
diff out/run1/routes.rou.xml out/run2/routes.rou.xml
```

---

## Limitations (v0)

1. **Signals:** Not fully integrated into SUMO network generation
2. **Vehicle types:** All vehicles use `DEFAULT_VEHTYPE`
3. **Turn restrictions:** Not supported
4. **Multi-modal:** Only `car` mode supported
5. **Large networks:** BFS routing may be slow for city-scale networks

---

## Future Enhancements

- [ ] Full traffic light integration via `--tls-file`
- [ ] Custom vehicle types from demand.csv
- [ ] Dijkstra routing for weighted shortest paths
- [ ] Support for `--seed` flag for SUMO reproducibility
- [ ] Edge-level capacity constraints
