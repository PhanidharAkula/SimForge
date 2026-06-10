# Canonical Network Schema v0

## Purpose

Defines the **static road network** for a scenario in `network.xml`.

This schema is simulator-agnostic and intended to be translated into engine-specific formats (e.g., SUMO, MATSim, POLARIS).

---

## File

- `network.xml` (UTF-8 encoded XML)

## Top-Level Structure

```xml
<network>
  <metadata />
  <nodes>
    <node />
  </nodes>
  <links>
    <link />
  </links>
  <turn_restrictions>      <!-- optional, V5+ -->
    <turn_restriction />
  </turn_restrictions>
</network>
```

---

## Elements

### `<metadata>`

Provides global information about coordinate systems and units.

| Attribute          | Type     | Requirement  | Description                                                               |
| :----------------- | :------- | :----------- | :------------------------------------------------------------------------ |
| **`crs`**          | `string` | **required** | Coordinate Reference System identifier (e.g., `EPSG:4326`, `EPSG:26917`). |
| **`units_length`** | `string` | **required** | Unit of length used in the network (e.g., `meters`).                      |
| **`units_speed`**  | `string` | **required** | Unit of speed used in the network (e.g., `m/s`, `km/h`).                  |
| **`source`**       | `string` | optional     | Origin of the network data (e.g., `OSM`, `synthetic`, `manual`).          |

**Example:**

```xml
<metadata crs="EPSG:4326"
          units_length="meters"
          units_speed="m/s"
          source="synthetic" />
```

### `<node>`

Represents a network node such as an intersection, junction, or endpoint.

| Attribute        | Type      | Requirement  | Description                                                         |
| :--------------- | :-------- | :----------- | :------------------------------------------------------------------ |
| **`id`**         | `string`  | **required** | Unique identifier for the node.                                     |
| **`x`**          | `float`   | **required** | X coordinate in the declared CRS.                                   |
| **`y`**          | `float`   | **required** | Y coordinate in the declared CRS.                                   |
| **`type`**       | `string`  | optional     | Semantic type (`intersection`, `dead_end`, `major_intersection`).   |
| **`osm_id`**     | `string`  | optional     | Source OSM node ID. Provenance only.                                |
| **`has_signal`** | `boolean` | optional     | `"true"` when OSM tags this node as `highway=traffic_signals`. The signal generator (`pipeline/signals/build_signals_default.py`) uses these as ground-truth signal placement. Absent / `"false"` means no signal. |

**Example:**

```xml
<node id="n1" x="0.0" y="0.0" type="intersection" has_signal="true" />
```

### `<link>`

Represents a **directed road segment** between two nodes.

| Attribute                   | Type     | Requirement  | Description                                                 |
| :-------------------------- | :------- | :----------- | :---------------------------------------------------------- |
| **`id`**                    | `string` | **required** | Unique identifier for the link.                             |
| **`from`**                  | `string` | **required** | ID of the **upstream** node.                                |
| **`to`**                    | `string` | **required** | ID of the **downstream** node.                              |
| **`length`**                | `float`  | **required** | Length of the link in `units_length`.                       |
| **`lanes`**                 | `int`    | **required** | Number of lanes (must be $\ge 1$).                          |
| **`speed_limit`**           | `float`  | **required** | Free-flow speed in `units_speed`.                           |
| **`capacity_veh_per_hour`** | `float`  | optional     | Approximate hourly capacity.                                |
| **`highway_type`**          | `string` | optional     | OSM `highway=*` classification (e.g., `motorway`, `primary`, `residential`, `service`, `footway`). Mirrors the OSM tag value verbatim. |
| **`osm_way_id`**            | `string` | optional     | Source OSM way ID (or list `[id1, id2]` when an OSM way was split). Provenance only. |
| **`name`**                  | `string` | optional     | Street name from OSM `name=*`, when present.               |

**Example:**

```xml
<link id="l1"
      from="n1"
      to="n2"
      length="100.0"
      lanes="1"
      speed_limit="13.9"
      capacity_veh_per_hour="900"
      highway_type="primary"
      osm_way_id="24093736"
      name="East Huron Street" />
```

### `<turn_restriction>` (V5+, optional)

Represents a single turning-movement restriction at a junction, sourced
from an OSM `type=restriction` relation with `via=node`. Wrapped in a
top-level `<turn_restrictions>` block.

| Attribute             | Type      | Requirement  | Description                                                                                                              |
| :-------------------- | :-------- | :----------- | :----------------------------------------------------------------------------------------------------------------------- |
| **`type`**            | `string`  | **required** | OSM restriction value: `no_left_turn`, `no_right_turn`, `no_u_turn`, `no_straight_on`, `only_left_turn`, `only_right_turn`, `only_straight_on`. |
| **`from_link`**       | `string`  | **required** | ID of the canonical link approaching the junction (its `to` is `via_node`).                                              |
| **`via_node`**        | `string`  | **required** | ID of the junction node (the `<node>` where the restriction applies).                                                    |
| **`to_link`**         | `string`  | **required** | ID of the canonical link leaving the junction (its `from` is `via_node`). For `only_*` restrictions, this is the *only* allowed exit.   |
| **`osm_relation_id`** | `string`  | optional     | Source OSM relation ID. Provenance only.                                                                                 |

**Example:**

```xml
<turn_restrictions>
  <turn_restriction type="no_left_turn"
                    from_link="l1234"
                    via_node="n567"
                    to_link="l5678"
                    osm_relation_id="123456" />
</turn_restrictions>
```

**Semantics:**

- A `no_*_turn` restriction forbids the specific `(from_link, to_link)` pair at `via_node`.
- An `only_*_turn` restriction forbids every `(from_link, *)` pair at `via_node` *except* the one named, i.e. the only allowed exit from `from_link` is `to_link`.
- `via=way` restrictions (rare, restriction spans a sequence of ways) are not currently emitted.
- Adapter enforcement (V5+):
  - **SUMO** and **MATSim** enforce these via state-aware BFS pre-routing in `pipeline/network/turn_restrictions.shortest_path_with_restrictions`; the prescribed route avoids forbidden movements and the engine drives it verbatim.
  - **DTALite** receives the data as a sibling `movement.csv` (GMNS-conformant), but path4gmns 0.10.0 does not ingest movement.csv natively yet; DTALite's UE assignment may still cross forbidden movements. This is a documented cross-engine asymmetry. See `pipeline/network/turn_restrictions.py` module docstring and `doc/MODELGEN_AND_MODES.md` §"Cross-engine asymmetry".

---

## Constraints

- All **`node.id`** values must be **unique**.
- All **`link.id`** values must be **unique**.
- Every **`from`** and **`to`** reference in `<link>` must correspond to an existing `<node>`.
- `length` $> 0$
- `lanes` $\ge 1$
- `speed_limit` $> 0$
- `crs`, `units_length`, and `units_speed` must be defined in `<metadata>`.

---

## Versioning

- This document defines **v0** of the canonical network schema.
- Future versions may extend attributes but should preserve backward compatibility with v0.
