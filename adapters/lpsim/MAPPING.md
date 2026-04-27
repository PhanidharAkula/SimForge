# LPSim Adapter Mapping

## Overview

LPSim ([Xuan-1998/LPSim](https://github.com/Xuan-1998/LPSim), MIT) is a
GPU-accelerated mesoscopic traffic simulator built on the LivingCity / B18
(Berkeley 2018) road-graph model. It replaces QarSUMO as SimForge's 3rd
primary engine in Version_4 — see `todo.md` for the gap audit and rationale.

**Key references:**
- LPSim source: `LPSim/LivingCity/`
- Berkeley B18 loader: `LivingCity/roadGraphB2018Loader.cpp` (the file the
  adapter targets — it defines the column schemas LPSim reads at startup)
- Output writer: `LivingCity/traffic/b18TrafficSimulator.cpp::writePeopleFile`

## Fundamental Differences from SUMO and MATSim

| Aspect | SUMO | MATSim | LPSim |
|---|---|---|---|
| Hardware | CPU | CPU + JVM | CUDA GPU (CPU fallback) |
| Unit of simulation | Vehicle | Agent (person) | Person |
| Routing | Pre-routed (BFS) | Replanning | Shortest-path or Johnson |
| Demand format | OD with departure times | Activity plans | OD with per-trip `dep_time` (seconds) |
| Time control | Per-trip departure | Per-trip departure | Per-trip `dep_time` filtered against `START_HR`/`END_HR` window in INI |
| Config | XML (`.sumocfg`) | XML (config.xml) | INI (`command_line_options.ini`) |
| Output | `tripinfo.xml` | `output_trips.csv.gz` | `<NUM_PASSES>_people*.csv` |

## Canonical → LPSim Mapping

### 1. Network nodes

**Canonical `network.xml`:**

```xml
<nodes>
  <node id="n123" x="-87.6332" y="41.8781"/>
</nodes>
```

**LPSim `network/nodes.csv`** (schema from `roadGraphB2018Loader.cpp:116-119`):

| canonical | LPSim column | how |
|---|---|---|
| `id` ("n123") | `osmid`, `index` | strip "n" prefix → integer 123 |
| `x` | `x` | longitude, copied verbatim |
| `y` | `y` | latitude, copied verbatim |
| (none) | `highway` | empty string — canonical doesn't preserve OSM tag |

LPSim's loader requires both `osmid` and `index`; we set them to the same
integer because the canonical schema collapses them into one identifier.

### 2. Network edges

**Canonical `network.xml`:**

```xml
<links>
  <link id="l456" from="n10" to="n11" length="120.5" speed_limit="13.9" lanes="2"/>
</links>
```

**LPSim `network/edges.csv`** (schema from `roadGraphB2018Loader.cpp:216-221`):

| canonical | LPSim column | how |
|---|---|---|
| `id` | `uniqueid` | strip "l" prefix → integer 456 |
| `from`, `to` | `u`, `v` | strip "n" prefix → integers |
| (mirror) | `osmid_u`, `osmid_v` | same as `u`, `v` (parity with bundled berkeley_2018 schema) |
| `length` | `length` | meters → meters (no conversion) |
| `speed_limit` (m/s) | `speed_mph` | × 2.236936 |
| `lanes` | `lanes` | clamped to ≥ 1 |

Self-loops (`u == v`) are filtered — same policy as the SUMO adapter and
the canonical SCC. The canonical generator already drops them at extract
time as of Version_4 Phase A.

### 3. Demand

**Canonical `demand.csv`:**

```
trip_id,origin_node_id,destination_node_id,departure_time_s,mode
trip_0,n42,n100,25260,car
```

**LPSim OD CSV** (schema from `roadGraphB2018Loader.cpp:319-321`):

| canonical | LPSim column | how |
|---|---|---|
| `trip_id` | `PERNO` | copied verbatim |
| `origin_node_id` | `origin` | strip "n" prefix → integer |
| `destination_node_id` | `destination` | strip "n" prefix → integer |
| `departure_time_s` | (none) | **dropped** — LPSim has no per-trip departure column |

LPSim distributes departures inside `[START_HR, END_HR]` per its own
heuristic; the `departure_time_s` precision available to SUMO and MATSim
is not exposed to LPSim. This is documented as a fidelity trade-off in
the methods chapter and is the single cleanest difference between the
three engines from the demand-modeling perspective.

Only trips that pass the cross-engine SCC feasibility filter
(`adapters/common/feasibility.py`) are written, so SUMO, MATSim, and
LPSim simulate exactly the same trip subset (`feasibility_report.json`
is written next to the LPSim inputs as the audit trail).

### 4. Configuration

**Canonical `config.xml`:**

```xml
<config>
  <metadata scenario_id="chicago_1k_car"/>
  <time start_time_s="25200" end_time_s="28800"/>
</config>
```

**LPSim `command_line_options.ini`:**

```ini
[General]
GUI=false
USE_CPU=false                  # GPU path
NETWORK_PATH=network/          # relative to CWD at run time
USE_SP_ROUTING=true            # Dijkstra-style shortest path
USE_JOHNSON_ROUTING=false
USE_PREV_PATHS=false           # don't reuse cache (each repeat is independent)
LIMIT_NUM_PEOPLE=0             # 0 = no cap
ADD_RANDOM_PEOPLE=false
NUM_PASSES=1                   # one pass = comparable to SUMO/MATSim single-iter
TIME_STEP=0.5
START_HR=7                     # floor(25200 / 3600)
END_HR=8                       # ceil(28800 / 3600)
OD_DEMAND_FILENAME=od_demand.csv
SHOW_BENCHMARKS=false
REROUTE_INCREMENT=0
```

`START_HR` is the floor of `start_time_s / 3600`, `END_HR` is the ceiling
of `end_time_s / 3600`, both clamped to `[0, 24]`. The 1-hour granularity
is a true loss vs SUMO/MATSim — flagged in `doc/chapters/methods.md`.

## Output

LPSim writes one row per simulated person to a CSV named
`<NUM_PASSES>_people*.csv` in its CWD (the run dir). Schema (from
`writePeopleFile`):

```
p, init_intersection, end_intersection, time_departure, num_steps, travel_time, distance
```

`parse_lpsim_output` finds the file via the regex `^\d+_people.*\.csv$`,
keeps only rows with `travel_time > 0` (LPSim leaves zeros on abandoned
trips), and computes:

- `trip_count` — total rows in the CSV (= LIMIT_NUM_PEOPLE or len(demand))
- `completed_count` — rows with `travel_time > 0`
- `mean_travel_time_s` — arithmetic mean over completed trips
- `p95_travel_time_s` — 95th percentile of completed travel times
- `mean_distance_m` — mean of `distance` column

These plug into the same fidelity / scalability / reproducibility metric
modules SUMO and MATSim use, so cross-engine comparison stays honest.

## Binary discovery

`find_lpsim_binary()` looks, in order:

1. `$LPSIM_BINARY` (explicit override)
2. `$HOME/lpsim/LivingCity/LivingCity` — produced by `cluster/jobs/build_lpsim.sbatch`
3. `$HOME/lpsim/LivingCity` — alternative shallow layout
4. `LivingCity` on `PATH`

`find_lpsim_singularity_image()` checks `$HOME/lpsim/lpsim.sif`. When the
image is present and `singularity` is on `PATH`, `run_lpsim` prefers it
and runs `singularity exec --nv $HOME/lpsim/lpsim.sif LivingCity`.

If neither is available, `run_lpsim` returns a clean error pointing at
`sbatch cluster/jobs/build_lpsim.sbatch` so the operator can recover
without reading source.

## Determinism note

LPSim's GPU code path uses `atomicAdd` and other reduction operations
that are **not** bit-deterministic across runs even with the same seed.
This is documented behaviour, not a SimForge bug. Reproducibility (R-score)
is therefore expected to be lower for LPSim than for SUMO meso (which is
fully deterministic) or MATSim (R = 1.0 with `lastIteration=0`). The
N=5 repeats in the runspecs give us statistical room to characterize the
spread — reported as `mean ± 95 % CI` in Tables 5.1 / 5.2.
