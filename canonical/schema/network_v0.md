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

| Attribute  | Type     | Requirement  | Description                                                         |
| :--------- | :------- | :----------- | :------------------------------------------------------------------ |
| **`id`**   | `string` | **required** | Unique identifier for the node.                                     |
| **`x`**    | `float`  | **required** | X coordinate in the declared CRS.                                   |
| **`y`**    | `float`  | **required** | Y coordinate in the declared CRS.                                   |
| **`type`** | `string` | optional     | Semantic type (e.g., `intersection`, `centroid`, `source`, `sink`). |

**Example:**

```xml
<node id="n1" x="0.0" y="0.0" type="intersection" />
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
| **`road_type`**             | `string` | optional     | Road classification (e.g., `urban`, `arterial`, `highway`). |

**Example:**

```xml
<link id="l1"
      from="n1"
      to="n2"
      length="100.0"
      lanes="1"
      speed_limit="13.9"
      capacity_veh_per_hour="900"
      road_type="urban" />
```

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

---

Do you have any specific attributes or elements you would like me to detail further, or would you like an example of a full `network.xml` file?
