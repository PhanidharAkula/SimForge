# Canonical Manifest Schema v0

## Purpose

Defines the **scenario bundle inventory** in `manifest.xml`.

The manifest is the single source of truth listing:

- which canonical files exist (network, demand, signals, config, manifest),
- where they live (relative paths),
- and optional integrity metadata (hashes, sizes).

Validators, adapters, and execution pipelines all rely on this file.

---

## File

- `manifest.xml` (UTF-8 encoded XML)

---

## Top-Level Structure

```xml
<manifest>
  <scenario />
  <canonical_files>
    <file />
  </canonical_files>
  <engine_assets>
    <engine>
      <file />
    </engine>
  </engine_assets>
</manifest>
```

For **v0**:

- `<scenario>` and `<canonical_files>` are required.
- `<engine_assets>` is optional.

---

## Elements

### `<manifest>`

Root element.

- Contains exactly one `<scenario>` element.
- Contains exactly one `<canonical_files>` element.
- May contain an optional `<engine_assets>` element.

### `<scenario>`

Describes the canonical scenario at a high level.

| Attribute  | Type     | Requirement  | Description                                                  |
| :--------- | :------- | :----------- | :----------------------------------------------------------- |
| **`id`**   | `string` | **required** | Scenario ID. Must match `config.xml` `metadata.scenario_id`. |
| **`name`** | `string` | optional     | Human-friendly name for the scenario.                        |

**Child elements:**

- `<description>` (optional): free-text description.

**Example:**

```xml
<scenario id="toy_2x2_grid" name="Toy 2x2 Grid">
  <description>Toy canonical scenario for SUMO adapter testing.</description>
</scenario>
```

### `<canonical_files>`

Lists the **canonical bundle** files.

Contains one or more `<file>` elements.

Each `<file>` describes a canonical input:

| Attribute        | Type     | Requirement  | Description                                                            |
| :--------------- | :------- | :----------- | :--------------------------------------------------------------------- |
| **`type`**       | `string` | **required** | One of: `network`, `demand`, `signals`, `config`, `manifest` (for v0). |
| **`path`**       | `string` | **required** | Relative path from the **scenario root** (e.g., `network.xml`).        |
| **`required`**   | `string` | optional     | `"true"` or `"false"`. Defaults to `"true"` if omitted.                |
| **`sha256`**     | `string` | optional     | SHA-256 hash of the file (for integrity checking).                     |
| **`size_bytes`** | `int`    | optional     | File size in bytes (sanity check only).                                |

**Example (toy scenario):**

```xml
<canonical_files>
  <file type="network" path="network.xml" required="true" />
  <file type="demand" path="demand.csv" required="true" />
  <file type="signals" path="signals.xml" required="false" />
  <file type="config" path="config.xml" required="true" />
  </canonical_files>
```

For **v0** and the toy scenario, it is acceptable to omit the `manifest.xml` entry to avoid self-reference, as long as the four primary files are listed.

### `<engine_assets>` (optional)

Lists **engine-specific** artifacts derived from the canonical bundle (e.g., pre-generated SUMO nets, MATSim configs, POLARIS networks).

**Structure:**

```xml
<engine_assets>
  <engine name="SUMO">
    <file type="network" path="sumo/net.net.xml" />
  </engine>
  <engine name="MATSim">
    <file type="config" path="matsim/config.xml" />
  </engine>
</engine_assets>
```

#### `<engine>`

| Attribute  | Type     | Requirement  | Description                 |
| :--------- | :------- | :----------- | :-------------------------- |
| **`name`** | `string` | **required** | Engine name (e.g., `SUMO`). |

Contains zero or more `<file>` elements, with:

| Attribute    | Type     | Requirement  | Description                                     |
| :----------- | :------- | :----------- | :---------------------------------------------- |
| **`type`**   | `string` | optional     | Informal type label for the engine asset.       |
| **`path`**   | `string` | **required** | Relative path to engine-specific file/artifact. |
| **`sha256`** | `string` | optional     | SHA-256 hash for reproducibility checks.        |

For **Milestone 1**, this section can be empty or omitted entirely.

---

## Minimal Example

A minimal but valid `manifest.xml` for the toy scenario:

```xml
<manifest>
  <scenario id="toy_2x2_grid" name="Toy 2x2 Grid">
    <description>Toy canonical scenario for SUMO adapter and validation tests.</description>
  </scenario>

  <canonical_files>
    <file type="network" path="network.xml" required="true" />
    <file type="demand" path="demand.csv" required="true" />
    <file type="signals" path="signals.xml" required="false" />
    <file type="config" path="config.xml" required="true" />
  </canonical_files>
</manifest>
```

---

## Constraints

- Exactly one `<manifest>` root element per file.
- Exactly one `<scenario>` and one `<canonical_files>` inside `<manifest>`.
- `scenario.id` must:
  - be non-empty,
  - match `config.xml` `metadata.scenario_id`.
- For each `<file>` in `<canonical_files>`:
  - `type` must be one of: `network`, `demand`, `signals`, `config`, `manifest` (v0).
  - `path` must be a valid relative path from the scenario directory.
  - If `required="true"` (or omitted), the file **must exist** on disk for the bundle to be valid.
- If `<engine_assets>` is present:
  - Each `<engine>` must have a unique `name`.
  - `path` attributes must be valid relative paths.

---

## Versioning

- This document defines **v0** of the canonical manifest schema.
- Future versions may:
  - add more file `type` values,
  - add richer metadata for engine assets and outputs,
  - while keeping v0 elements and semantics valid for existing scenarios.
