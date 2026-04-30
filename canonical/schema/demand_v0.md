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

- `purpose` (V5+ generator emits a fixed enum — see below)
- `dest_source` (V5+ provenance tag — see below)
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
| **`purpose`**       | `string` | optional    | Trip purpose. V5+ census generator emits the 4-step taxonomy `HBW_AM`, `HBW_PM`, `HBSchool_AM`, `HBSchool_PM`, `HBW_AM_chained`, `HBW_PM_chained` (see below). Other producers may use any string. |
| **`dest_source`**   | `string` | optional    | Provenance of the destination. V5+ census generator emits `schedule` (cityscape PUMS-derived workplace) or `gravity` (commute-calibrated gravity-model fallback). Logged for downstream split analysis. |
| **`passengers`**    | `int`    | optional    | Number of occupants in the vehicle (default is 1 if omitted).      |
| **`value_of_time`** | `float`  | optional    | Value of time (e.g., in USD/hour), for cost-based analyses.        |
| **`vehicle_type`**  | `string` | optional    | Vehicle type label, e.g., `sedan`, `bus`, `truck`, `bike`, `walk`. |

#### V5+ `purpose` taxonomy

The census-calibrated generator (`pipeline/demand/generate_census_demand.py`)
emits one of six purpose labels per row, drawn from the standard
4-step transportation-planning taxonomy plus SimForge-specific chain
provenance suffixes:

| Label                 | Meaning                                                              | Origin                                  |
| :-------------------- | :------------------------------------------------------------------- | :-------------------------------------- |
| `HBW_AM`              | Home-Based Work, AM peak (home → work, ~8 AM arrival)                | cityscape `schedule[0]`                 |
| `HBW_PM`              | Home-Based Work, PM peak (work → home, ~17:00 arrival)               | cityscape `schedule[1]`                 |
| `HBSchool_AM`         | Home-Based School, AM peak (home → school, kid drop-off leg)         | parent + school-age dependent + OSM kind=school |
| `HBSchool_PM`         | Home-Based School, PM peak (school → home, kid pickup leg)           | symmetric mirror                        |
| `HBW_AM_chained`      | Continuation leg of an HBSchool AM chain (school → work)             | parent's continued commute              |
| `HBW_PM_chained`      | Continuation leg of an HBSchool PM chain (work → school)             | parent leaving work for pickup          |

Adapters consume the canonical 5-column subset (`trip_id`,
`origin_node_id`, `destination_node_id`, `departure_time_s`, `mode`)
by name and ignore both `purpose` and `dest_source`. The columns are
informational — used by `evaluation/audit_fairness.py` (Q5 section)
and `evaluation/analyze_benchmark.py`
(`print_demand_composition_table`) to surface per-scenario demand
mix without coordinate re-derivation.

Engines treat each row as an independent vehicle/agent — chain
semantics are not preserved at simulation time (would require SUMO
`<person>` activity sequences or MATSim `<plan>` chains, neither
wired today).

---

## Example

### Minimal **toy** demand file:

```csv
trip_id,origin_node_id,destination_node_id,departure_time_s,mode
t1,n1,n4,0,car
t2,n2,n3,60,car
t3,n3,n1,120,car
```

### Example with V5+ optional fields:

```csv
trip_id,origin_node_id,destination_node_id,departure_time_s,mode,dest_source,purpose
t0,n158,n352,25200,car,schedule,HBW_AM
t1,n125,n1179,25200,car,gravity,HBW_AM
t2,n399,n603,25201,car,schedule,HBSchool_AM
t3,n603,n352,25201,car,schedule,HBW_AM_chained
```

### Example with full optional fields:

```csv
trip_id,origin_node_id,destination_node_id,departure_time_s,mode,purpose,passengers,value_of_time,vehicle_type
t1,n1,n4,0,car,HBW_AM,1,15.0,sedan
t2,n2,n3,60,car,HBSchool_AM,2,10.0,sedan
t3,n3,n1,120,car,HBW_PM,1,8.0,sedan
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
