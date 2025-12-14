# ⚙️ Canonical Config Schema v0

## Purpose

Defines **scenario-level configuration** in `config.xml`:

- global time horizon,
- random seed,
- units,
- and simple simulation options.

This file ties together the canonical bundle and provides defaults that adapters and execution code can rely on.

---

## File

- `config.xml` (UTF-8 encoded XML)

---

## Top-Level Structure

```xml
<config>
  <metadata />
  <time />
  <random />
  <units />
  <simulation />
</config>
```

All elements are strongly recommended for v0. Some may become optional in future versions as defaults are clarified.

---

## Elements

### `<config>`

Root element.

- Contains exactly one `<metadata>`, `<time>`, `<random>`, and `<units>` element in v0.
- May contain an optional `<simulation>` element.

### `<metadata>`

Describes the scenario at a high level.

| Attribute         | Type     | Requirement  | Description                                        |
| :---------------- | :------- | :----------- | :------------------------------------------------- |
| **`scenario_id`** | `string` | **required** | Unique ID for the scenario (e.g., `toy_2x2_grid`). |
| **`created_by`**  | `string` | optional     | Author or generator (e.g., `phanidhar`).           |
| **`created_at`**  | `string` | optional     | ISO-8601 timestamp (e.g., `2025-12-01T10:00:00Z`). |

A child `<description>` element is allowed for human-readable text.

**Example:**

```xml
<metadata scenario_id="toy_2x2_grid" created_by="phanidhar">
  <description>Toy 2x2 grid canonical scenario for adapter testing.</description>
</metadata>
```

### `<time>`

Defines the **temporal extent** of the scenario.

| Attribute          | Type  | Requirement  | Description                                       |
| :----------------- | :---- | :----------- | :------------------------------------------------ |
| **`start_time_s`** | `int` | **required** | Scenario start time in seconds (usually $0$).     |
| **`end_time_s`**   | `int` | **required** | Scenario end time in seconds (must be $>$ start). |
| **`time_step_s`**  | `int` | optional     | Recommended base time step (e.g., $1$).           |

**Example:**

```xml
<time start_time_s="0" end_time_s="3600" time_step_s="1" />
```

### `<random>`

Controls **randomness** for reproducible runs.

| Attribute              | Type     | Requirement  | Description                                                   |
| :--------------------- | :------- | :----------- | :------------------------------------------------------------ |
| **`seed`**             | `int`    | **required** | Global random seed for canonical runs.                        |
| **`engine_seed_mode`** | `string` | optional     | Strategy, e.g., `fixed`, `per_run`. v0 tools can ignore this. |

**Example:**

```xml
<random seed="42" engine_seed_mode="fixed" />
```

### `<units>`

Specifies canonical **units** used across the scenario.

| Attribute    | Type     | Requirement  | Description                       |
| :----------- | :------- | :----------- | :-------------------------------- |
| **`length`** | `string` | **required** | Length unit (e.g., `meters`).     |
| **`speed`**  | `string` | **required** | Speed unit (e.g., `m/s`, `km/h`). |
| **`time`**   | `string` | **required** | Time unit (e.g., `seconds`).      |

These should be consistent with `network.xml` `<metadata>` and with how `demand.csv` is interpreted.

**Example:**

```xml
<units length="meters" speed="m/s" time="seconds" />
```

### `<simulation>` (optional)

Provides extra **simulation-level settings**. For v0, these are simple hints; engines and adapters may or may not use them.

| Attribute                    | Type  | Requirement | Description                                                |
| :--------------------------- | :---- | :---------- | :--------------------------------------------------------- |
| **`warmup_time_s`**          | `int` | optional    | Warmup period before metrics are collected.                |
| **`aggregation_interval_s`** | `int` | optional    | Time window for aggregating summary metrics (e.g., $300$). |

**Example:**

```xml
<simulation warmup_time_s="600" aggregation_interval_s="300" />
```

---

## Minimal Example

A small but complete `config.xml` for a toy scenario:

```xml
<config>
  <metadata scenario_id="toy_2x2_grid" created_by="phanidhar">
    <description>Toy 2x2 grid canonical scenario for SUMO adapter testing.</description>
  </metadata>

  <time start_time_s="0" end_time_s="3600" time_step_s="1" />

  <random seed="42" engine_seed_mode="fixed" />

  <units length="meters" speed="m/s" time="seconds" />

  <simulation warmup_time_s="600" aggregation_interval_s="300" />
</config>
```

---

## Constraints

- Exactly one `<config>` root element per file.
- `metadata.scenario_id` must:
  - be non-empty,
  - match the scenario ID used in `manifest.xml` (v0 rule).
- `end_time_s` $>$ `start_time_s`.
- `seed` must be an integer.
- `length`, `speed`, and `time` must be non-empty strings.
- Units and time horizon must be **consistent** with the interpretations used in:
  - `network.xml` (`units_length`, `units_speed`),
  - `demand.csv` (`departure_time_s`).

---

## Versioning

- This document defines **v0** of the canonical config schema.
- Future versions may:
  - add more detailed simulation parameters,
  - add output or logging controls,
  - while keeping v0 fields valid and stable for existing scenarios.
