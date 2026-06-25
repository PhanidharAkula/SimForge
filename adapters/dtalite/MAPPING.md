# DTALite Adapter: Schema Mapping

**Engine:** DTALite (CPU mesoscopic Dynamic Traffic Assignment)
**Distribution:** Bundled inside the [`path4gmns`](https://github.com/jdlph/Path4GMNS) Python package (`uv pip install path4gmns`)
**Native binary:** `path4gmns/bin/DTALiteMM_{arm,x86}.dylib` (macOS) / `DTALiteMM.so` (Linux) / `DTALiteMM.dll` (Windows)
**Mac runtime dep:** `libomp` (`brew install libomp`)
**Input format:** GMNS (General Modeling Network Specification), open data standard published at [zephyr-data-specs/GMNS](https://github.com/zephyr-data-specs/GMNS)

---

## Canonical → GMNS conversion

### Network → `node.csv`

| Canonical column      | GMNS column     | Conversion                                      |
|-----------------------|-----------------|-------------------------------------------------|
| `node[id]` (e.g. n42) | `node_id`       | Strip prefix → integer                          |
| `node[x]`             | `x_coord`       | passthrough (lon, 6 decimals)                   |
| `node[y]`             | `y_coord`       | passthrough (lat, 6 decimals)                   |
| n/a | `zone_id`       | Set to `node_id` IFF node appears as origin/dest in demand; otherwise blank (transit-only) |
| n/a | `production`    | 1 if zone, 0 otherwise                          |
| n/a | `attraction`    | 1 if zone, 0 otherwise                          |

**Critical note: zone count = demand-driven.** DTALite's UE iteration cost scales linearly with zone count (each zone runs label-correcting shortest-path per outer iteration). With one zone per intersection on a 20k-node network that's 20k × outer_iters shortest-path computations, intractable. By limiting zones to nodes that actually carry demand (~1,800 for chicago_1k_car), runtime drops from "minutes" to ~5 seconds.

### Network → `link.csv`

| Canonical column            | GMNS column      | Conversion                              |
|-----------------------------|------------------|-----------------------------------------|
| `link[id]`                  | `link_id`        | Strip prefix → integer                  |
| `link[from]`                | `from_node_id`   | Strip prefix → integer                  |
| `link[to]`                  | `to_node_id`     | Strip prefix → integer                  |
| `link[length]` (m)          | `length` (km)    | × 0.001                                 |
| `link[speed_limit]` (m/s)   | `free_speed` (km/h) | × 3.6                                |
| `link[lanes]`               | `lanes`          | max(int, 1)                             |
| n/a | `capacity` (vph) | lanes × 1800 (FHWA HCM urban-arterial)  |
| n/a | `link_type`      | 1 (Highway/Expressway)                  |
| n/a | `facility_type`  | "Highway"                               |
| n/a | `dir_flag`       | 1 (one-way; canonical links already directional) |
| n/a | `VDF_fftt1` (min)| length_km / free_speed_kmh × 60         |
| n/a | `VDF_cap1`       | = capacity                              |
| n/a | `VDF_alpha1`     | 0.15 (FHWA BPR default)                 |
| n/a | `VDF_beta1`      | 4   (FHWA BPR default)                  |

**Filters applied at writer:**
- Self-loops (`u == v`) dropped (BPR cost function would divide by zero)
- Sub-meter edges (`length < 1 m`) dropped (would round to 0 km in GMNS)
- Speed floor: `free_speed >= 5 km/h` (BPR numerical stability)

### Demand → `demand.csv`

| Canonical column           | GMNS column      | Conversion                              |
|----------------------------|------------------|-----------------------------------------|
| `origin_node_id` (e.g. n42)| `o_zone_id`      | Strip prefix → integer (must be a zone in node.csv) |
| `destination_node_id`      | `d_zone_id`      | Strip prefix → integer                  |
| n/a | `volume`         | Aggregated count: number of trips per (origin, destination) pair |

**Trip aggregation.** Canonical demand is per-trip (one row per vehicle). DTALite's UE assignment expects an OD matrix (one row per OD pair with vehicle count). The writer aggregates trips by (origin, destination) and emits `volume = count`. Per-trip departure times are NOT preserved, DTALite distributes departures uniformly inside the demand period window (controlled by `[demand_period]` in `settings.csv`).

**Filters:**
- Cross-engine SCC feasibility filter (same one SUMO and MATSim use), only feasible trips are emitted
- Intra-zonal trips (`origin == destination`) dropped (DTALite assigns zero-cost paths to them, inflating cross-engine agreement metrics)

### Settings

DTALite's binary reads its assignment configuration from **two files**:

1. **`settings.csv`**: the section-formatted CSV the C++ binary reads. SimForge writes:
   - `[assignment]`: assignment_mode=ue, iteration counts, UE convergence
   - `[agent_type]`: single auto agent (cars only, `p` = passenger). PCE pulled from `adapters/common/vehicle_types.CAR_PCE`. DTALite has no per-vehicle length parameter, link capacity expresses the storage equivalent of SUMO's `length + minGap` and MATSim's effective length, and `PCE = 1.0` keeps that equivalent.
   - `[link_type]`: Highway/Expressway, type_code=f
   - `[demand_period]`: single AM period (default 0700-0800, controlled by `DTALiteConfig`)
   - `[demand_file_list]`: points at demand.csv
2. **`settings.yml`**: the YAML the path4gmns Python wrapper reads. Mirror of settings.csv in YAML form.

Both files coexist in every working path4gmns sample. The DTALite C++ binary reads `settings.csv`; the path4gmns wrapper reads `settings.yml`.

---

## DTALite output → SimForge metrics

DTALite produces (in the run directory):

| File                       | Schema                                                          | Used by SimForge?           |
|----------------------------|-----------------------------------------------------------------|-----------------------------|
| `link_performance.csv`     | per-link volume, travel_time (min), VOC, queue                   | NO, link-level not used    |
| `agent.csv`                | per-path agent_id, o_zone, d_zone, volume, travel_time (min), distance (km), node_sequence, link_sequence | YES, travel-time stats     |
| `route_assignment.csv`     | per-path columns/paths                                          | NO, implementation detail  |
| `od_performance.csv`       | per-OD-pair performance                                          | NO, agent.csv is per-path  |
| `log.txt`, `log_main.txt`, `log_DTA.txt` | binary diagnostic logs                              | YES, error surfacing       |

### Travel-time parsing

`parse_dtalite_output` reads `agent.csv` and produces:

| SimForge metric          | Source                                                              |
|--------------------------|---------------------------------------------------------------------|
| `trip_count`             | Sum of `volume` across all rows (vehicle-equivalents)               |
| `completed_count`        | Sum of `volume` across rows with `travel_time > 0` (UE-converged)   |
| `mean_travel_time_s`     | volume-expanded mean of `travel_time × 60`                          |
| `p95_travel_time_s`      | volume-expanded P95 of `travel_time × 60`                           |
| `mean_distance_m`        | volume-expanded mean of `distance × 1000`                           |

**Unit conversions at parse time:** travel_time minutes → seconds; distance km → meters.

**Why volume expansion.** DTALite outputs one row per **unique path** with `volume` = number of vehicles assigned to that path. SUMO and MATSim output one row per **vehicle**. To make per-vehicle statistics comparable across engines, we expand each agent.csv row by its volume before computing means/percentiles.

---

## Determinism

DTALite is fully deterministic:

- The UE assignment algorithm (Method of Successive Averages or Frank-Wolfe) iterates in fixed order
- No atomic reductions, no GPU non-determinism
- Same inputs → same outputs across runs

SimForge expects R = 1.0 for DTALite on the reproducibility metric, matching SUMO mesoscopic and MATSim with `lastIteration=0`.

---

## Implementation notes

### DTALiteClassic vs DTALiteMultimodal

path4gmns 0.10.0 ships TWO DTALite binaries:

- `DTALiteClassic`, the stable C++ binary, accepts `(assignment_mode, column_gen_num, column_upd_num)` as direct args. Uses the "classic" GMNS schema (settings.csv with sections).
- `DTALiteMultimodal` (a.k.a. `run_DTALite`), the newer multimodal version. **Has a regression as of path4gmns 0.10.0**: requires a `mode_type.csv` file in a schema the upstream has not published. Even path4gmns's own bundled samples fail on this binary with `[ERROR] File mode_type does not have information`.

SimForge uses **DTALiteClassic** (mode 1 = path-based UE) for all runs. If the multimodal regression is ever fixed upstream, we can switch by changing the `cmd` line in `run_dtalite`.

### macOS multiprocessing wrapper bug

path4gmns 0.10.0's `DTALiteClassic` Python wrapper attempts to spawn a `multiprocessing.Process` for the binary call. On macOS + Python 3.8+ this fails with a SemLock error AFTER the binary has already produced full output (the C++ binary call happens before the fork attempt). `run_dtalite` therefore uses **output-file presence** (not subprocess exit code) as the success signal: if `link_performance.csv` exists and is non-empty, the assignment succeeded regardless of the wrapper's crash.

### Settings.yml format

`settings.yml` keys:

- `agents`, list of agent types (cars only for SimForge)
- `demand_periods`, list of time windows (single AM 0700-0800 default)
- `demand_files`, list mapping each demand CSV to a period + agent type

The YAML format used by path4gmns 0.10.0 differs from earlier versions; the writer in `write_dtalite_settings_yml` uses the format that's compatible with the bundled binaries.

---

## Known limitations

1. **Per-trip departure times are not preserved.** DTALite's demand layer is OD-matrix-based; departures are distributed uniformly within the period window. This is the cleanest cross-engine difference for DTALite (SUMO and MATSim simulate per-trip departure times faithfully).
2. **Single mode: car only.** SimForge's bike/walk/transit modes are dropped at the demand writer. (Path4GMNS supports multi-modal via `agents:` but the cross-engine harness currently only runs car demand.)
3. **20k+ node networks need demand-driven zoning** to keep runtime sub-minute. Already enforced by `prepare_dtalite_inputs`.
4. **Turn restrictions emitted but not enforced.** The adapter writes a sibling `movement.csv` (GMNS-derived: `mvmt_id, node_id, ib_link_id, ob_link_id, type, penalty, capacity, ctrl_type, geometry, osm_restriction`) alongside `node.csv`/`link.csv`/`demand.csv`. Each canonical `<turn_restriction>` becomes one forbidden movement row with `capacity = 0` and `penalty = 99999`. **path4gmns 0.10.0 does not natively ingest movement.csv**, so DTALite's UE assignment may still cross forbidden movements. SUMO and MATSim adapters enforce restrictions via state-aware BFS pre-routing, this is a documented cross-engine asymmetry. The movement.csv is a documentary artefact for future engine versions and downstream tooling. See `pipeline/network/turn_restrictions.py` module docstring and `doc/MODELGEN_AND_MODES.md` §"Cross-engine asymmetry".
5. **Canonical `purpose` and `dest_source` columns dropped.** The DTALite `demand.csv` has only three columns (`o_zone_id`, `d_zone_id`, `volume`), the canonical-bundle `purpose` / `dest_source` provenance is lost in the OD aggregation. `evaluation/audit_fairness.py` Q5 reads from the canonical bundle's `demand.csv`, not the DTALite cell copy, so this is not a reporting gap, but consumers reading the DTALite cell directly will not see the purpose taxonomy.

---

## References

- **path4gmns:** [jdlph/Path4GMNS](https://github.com/jdlph/Path4GMNS), Python wrapper, actively maintained
- **DTALite C++:** [asu-trans-ai-lab/DTALite](https://github.com/asu-trans-ai-lab/DTALite), upstream (dormant)
- **GMNS spec:** [zephyr-data-specs/GMNS](https://github.com/zephyr-data-specs/GMNS), published data standard
- **SimForge engine evaluations:** `doc/engines/{LPSIM,QARSUMO}_EVALUATION.md`, `doc/engines/THIRD_ENGINE_OPTIONS.md`
- **Cross-engine comparison reference:** `doc/engines/ENGINE_COMPARISON.md`
