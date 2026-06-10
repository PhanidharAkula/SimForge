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
| `link/@length`      | `edge/@length`           | Direct copy (m); keeps canonical lengths instead of netconvert's geometric recomputation |

**Example:**

Canonical:

```xml
<link id="l1" from="n1" to="n2" length="100.0" lanes="1" speed_limit="13.9" />
```

SUMO:

```xml
<edge id="l1" from="n1" to="n2" numLanes="1" speed="13.9" length="100.0"/>
```

### Network Generation: `netconvert`

The adapter uses SUMO's `netconvert` tool to build the final network
(`--proj.plain-geo` keeps the WGS84 lon/lat inputs from being read as
meters, which used to produce sub-meter lane lengths):

```bash
netconvert --node-files nodes.nod.xml \
           --edge-files edges.edg.xml \
           --output-file net.net.xml \
           --proj.plain-geo \
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
| `mode`                | `vehicle/@type`        | `car` → `simforge_car` (V11+ canonical vType, see below) |

### Route Computation

The adapter computes routes using **state-aware BFS shortest path**
(V5+ Phase 7), a BFS over `(node, last_link)` states that respects
the V5+ `<turn_restrictions>` block in `network.xml`:

1. Build adjacency list from canonical links
2. Build forbidden-move set from `<turn_restrictions>` via
   `pipeline/network/turn_restrictions.build_forbidden_moves`
3. For each trip, run state-aware BFS from origin to destination via
   `pipeline/network/turn_restrictions.shortest_path_with_restrictions`
never traversing a `(from_link, via_node, to_link)` triple
   present in the forbidden set.
4. **Fallback:** if no restriction-respecting path exists, retry with
   plain BFS (the bundle-validation contract guarantees the trip is
   feasible at the SCC level, so plain BFS always succeeds).
5. Convert node path to edge IDs
6. Embed route directly in vehicle element

Pre-V5 behaviour was plain BFS (turn restrictions were not extracted).
The `purpose` and `dest_source` columns on `demand.csv` (V5+ Phase 9)
are read-by-name and ignored, they don't affect route computation.

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
<routes>
  <vType id="simforge_car" vClass="passenger" guiShape="passenger"
         length="5.0" minGap="2.5" width="1.8"
         maxSpeed="40.0" accel="2.6" decel="4.5" sigma="0.5"/>

  <vehicle id="veh_t1" type="simforge_car" depart="0">
    <route edges="l1 l7"/>
  </vehicle>
</routes>
```

### Vehicle type (V11+)

Pre-V11 the adapter emitted ``<vehicle>`` elements without a ``type=``
attribute, which fell back to SUMO's built-in ``DEFAULT_VEHTYPE``. That
was implicit (any SUMO version change could silently shift the
parameters) and inconsistent with the MATSim adapter's hardcoded values.

V11+ emits an explicit ``<vType id="simforge_car" .../>`` block at the
top of ``routes.rou.xml`` and references it on every ``<vehicle>``. The
parameters are pulled from ``adapters/common/vehicle_types.py``, a
single source of truth shared across SUMO, MATSim, and DTALite. See
that module's docstring for the cross-engine alignment rationale and
``CHANGELOG.md`` Phase 11 for the full history.

Canonical values (SUMO idiom, physical length + safety gap separate):

| Attribute   | Value | Meaning |
|---|---|---|
| `vClass`    | `passenger` | Standard private car class |
| `length`    | 5.0 m | Physical body length |
| `minGap`    | 2.5 m | Comfort gap to next vehicle |
| `width`     | 1.8 m | Cosmetic in mobsim, used for animations |
| `maxSpeed`  | 40 m/s | Free-flow ceiling, edge `speed` clamps |
| `accel`     | 2.6 m/s² | Comfortable acceleration |
| `decel`     | 4.5 m/s² | Comfortable deceleration |
| `sigma`     | 0.5 | Krauss model driver imperfection |

SUMO's effective queue spacing per vehicle = ``length + minGap = 7.5 m``,
which equals MATSim's ``length`` attribute (MATSim folds the gap into a
single value). Both adapters thus pack vehicles identically into queues.

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

1. **Signals:** Placement is OSM-grounded (V5+ Phase 6), but timing is a fixed-time 2-phase 90 s placeholder, not real coordinated timing.
2. **Vehicle types:** All vehicles use the canonical `simforge_car` vType (V11+; pre-V11 used SUMO's implicit `DEFAULT_VEHTYPE`). Within-bucket heterogeneity (taxis, motorcycles, trucks, carpools, all collapsed into the `car` JWTRNS bucket) is not modeled, every car-bucket trip simulates as the same sedan. See `doc/SCENARIO_GENERATION.md` §"Vehicle-type realism" for the V12 improvement path.
3. **Turn restrictions:** Enforced via state-aware BFS pre-routing (V5+ Phase 7), see "Route Computation" above. Restrictions that fully wall off an SCC-feasible trip cause a fall-back to plain BFS (rare).
4. **Trip chains:** V5+ Phase 9b/9c emits HBSchool chains as two separate `<vehicle>` rows; SUMO models them as independent vehicles, so chain agency is not preserved at simulation time.
5. **Multi-modal:** Only `car` mode supported (transit/bike/walk rows are filtered out by `feasibility.py` before reaching the SUMO writer).
6. **Large networks:** BFS routing may be slow for city-scale networks.

---

## Future Enhancements

- [ ] Full traffic light integration via `--tls-file`
- [ ] Custom vehicle types from demand.csv
- [ ] Dijkstra routing for weighted shortest paths
- [x] `--seed` support (every run path passes `--seed <N>` to the binary)
- [ ] Edge-level capacity constraints
