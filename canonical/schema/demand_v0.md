# Canonical Demand Schema v0

## Purpose

Defines **trip-level demand** for a scenario in `demand.csv`.

This schema is simulator-agnostic and designed to scale from tiny toy examples to millions of trips.

---

## File

- `demand.csv` (UTF-8 encoded, comma-separated)

---

## Structure

Each row represents **one trip**.

### Required columns:

- `trip_id`
- `origin_node_id`
- `destination_node_id`
- `departure_time_s`
- `mode`

### Optional but allowed columns:

- `purpose`
- `passengers`
- `value_of_time`
- `vehicle_type`

---

## Columns

### Required Columns

| Column                    | Type     | Requirement  | Description                                                                  |
| :------------------------ | :------- | :----------- | :--------------------------------------------------------------------------- |
| **`trip_id`**             | `string` | **required** | Unique ID per trip within a scenario.                                        |
| **`origin_node_id`**      | `string` | **required** | Must match a `node.id` in `network.xml`.                                     |
| **`destination_node_id`** | `string` | **required** | Must match a `node.id` in `network.xml`.                                     |
| **`departure_time_s`**    | `int`    | **required** | Departure time in **seconds** from scenario start (0-based).                 |
| **`mode`**                | `string` | **required** | Travel mode, e.g., `car`, `transit`, `bike`, `walk` (v0 can just use `car`). |

### Optional Columns

These are allowed for future flexibility. v0 tools may ignore them, but parsers must tolerate their presence.

| Column              | Type     | Requirement | Description                                                        |
| :------------------ | :------- | :---------- | :----------------------------------------------------------------- |
| **`purpose`**       | `string` | optional    | Trip purpose, e.g., `work`, `school`, `shopping`, `other`.         |
| **`passengers`**    | `int`    | optional    | Number of occupants in the vehicle (default is 1 if omitted).      |
| **`value_of_time`** | `float`  | optional    | Value of time (e.g., in USD/hour), for cost-based analyses.        |
| **`vehicle_type`**  | `string` | optional    | Vehicle type label, e.g., `sedan`, `bus`, `truck`, `bike`, `walk`. |

---

## Example

### Minimal **toy** demand file:

```csv
trip_id,origin_node_id,destination_node_id,departure_time_s,mode
t1,n1,n4,0,car
t2,n2,n3,60,car
t3,n3,n1,120,car
```

### Example with optional fields:

```csv
trip_id,origin_node_id,destination_node_id,departure_time_s,mode,purpose,passengers,value_of_time,vehicle_type
t1,n1,n4,0,car,work,1,15.0,sedan
t2,n2,n3,60,car,school,2,10.0,sedan
t3,n3,n1,120,car,other,1,8.0,sedan
```

---

## Constraints

- `trip_id` must be **unique** within a scenario.
- `origin_node_id` and `destination_node_id` must **exist** as `node.id` values in `network.xml`.
- `departure_time_s` $\ge 0$.
- `mode` must be one of the allowed modes for the scenario (for v0, `car` is sufficient).
- No missing values in any **required** column.
- Extra columns beyond those listed are allowed, but must not break CSV parsing.

---

## Versioning

- This document defines **v0** of the canonical demand schema.
- Future versions may:
  - add more optional columns (e.g., OD matrix identifiers, user groups),
  - tighten semantics for specific simulators,
  - while keeping the v0 required columns stable.
