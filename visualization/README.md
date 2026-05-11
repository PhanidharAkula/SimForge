# SimForge Visualization Component

Standalone, opt-in module for generating geographic visualizations from
SimForge bundles and benchmark results. Runs separately from the main
SimForge workflow — `generate.py`, `run_benchmark.py`,
`analyze_benchmark`, `audit_fairness`, and `generate_plots` do **not**
invoke this module, and the main suite incurs no startup cost from it.

The component produces seven map types — two from the bundle alone,
three per-engine maps from a benchmark run, and two cross-engine maps —
covering origin/destination demand, simulated link load, congestion,
mean travel time per origin tract, cross-engine routing diversity, and
animated vehicle flow.

---

## Quick start

```bash
# 1. One-time setup: cache US Census tract shapefiles + TIGER roads
python -m tools.download_census_tracts --all-bundled
python -m tools.download_tiger_roads --all-bundled

# 2. Coverage report (what's generatable from current data?)
python -m visualization.generate_maps --scenario chicago_1k_car --dry-run

# 3. Render every available map type for one scenario
python -m visualization.generate_maps --scenario chicago_1k_car --maps all

# 4. Render a specific subset to a custom output directory
python -m visualization.generate_maps --scenario nyc_10k_car \
    --maps od_origins,od_destinations,link_load \
    --output doc/figures/maps/nyc_10k_car
```

The coverage matrix is printed before any rendering happens. Maps whose
inputs aren't on disk are flagged `[--]` with a one-line reason; `--maps
all` then skips them gracefully (`[SKIP]`) without erroring.

---

## Map types

Seven map types, grouped by what input data they need:

| Map | Inputs needed | Engine specificity | Notes |
|---|---|---|---|
| `od_origins` | Bundle (`network.xml`, `demand.csv`) + cached census tracts + TIGER roads | — | CityScape-style filled tract choropleth on TIGER roads basemap |
| `od_destinations` | (same) | — | Same renderer with destination side |
| `link_load` | Per-cell engine output | per `(engine, mode)` | Color + linewidth = volume per link (log scale) |
| `congestion` | Per-cell DTALite `link_performance.csv` | DTALite only (needs link speed) | Color = mean speed / free-flow speed (green→red) |
| `travel_time` | Per-cell engine output + bundle | per `(engine, mode)` | Choropleth of mean per-trip travel time by origin tract |
| `route_diversity` | Cell output from ≥ 2 engines | cross-engine | Highlights links picked by 1 / 2 / 3 engines — visualizes the SUMO≈MATSim vs DTALite split |
| `animated_flow` | MATSim `output_events.xml.gz` from one cell | MATSim only | Two modes: `particles` (one moving dot per vehicle) or `throughput` (5-min link-load snapshots) |

Phase A = bundle-only maps (`od_*`).
Phase B = per-engine maps (`link_load`, `travel_time`, `congestion`).
Phase C = cross-engine + event-level maps (`route_diversity`,
`animated_flow`).

All renderers are implemented and shipped on the `visualization`
branch; the phasing is a historical grouping, not a status indicator.

---

## CLI reference

```text
usage: generate_maps.py [-h] --scenario SCENARIO [--bundle-dir DIR]
                        [--run-dir DIR] [--maps MAPS] [--output DIR]
                        [--dry-run] [--dpi DPI]
                        [--engine {sumo,matsim,dtalite}]
                        [--anim-mode {particles,throughput}]
                        [--anim-fps N] [--anim-sim-per-frame SEC]
                        [--anim-format {mp4,gif,apng}] [-v]
```

| Flag | Default | What it does |
|---|---|---|
| `--scenario` | required | Bundle id (`chicago_1k_car`, `nyc_10k_car`, `chicago_200k_car`, `la_50k_car`, `nyc_500k_car`, …) |
| `--bundle-dir` | `scenarios/<scenario>` | Override the bundle location |
| `--run-dir` | auto-detect under `runs/benchmark_*/<scenario>` | Where per-cell engine artefacts live |
| `--maps` | `all` | Comma-separated list, or `all`. Unknown names exit non-zero with the catalogue |
| `--output` | `visualization/output/<scenario>/` | Where PNGs / MP4s / GIFs land (gitignored by default) |
| `--dry-run` | off | Print the coverage matrix and exit; render nothing |
| `--dpi` | 220 | Render DPI. Animations and statics use the same value |
| `--engine` | first available | Which engine's data to use for Phase B maps. Choices: `sumo`, `matsim`, `dtalite` |
| `--anim-mode` | `particles` | Animation style. `particles` = moving dots per vehicle; `throughput` = per-bin link load snapshots |
| `--anim-fps` | 30 | Playback fps (particles only; throughput is fixed at 2 fps) |
| `--anim-sim-per-frame` | 5.0 | Particles mode: simulated seconds per frame. Lower → slower motion, longer file |
| `--anim-format` | `mp4` | `mp4` (smallest, needs ffmpeg), `gif` (embeds inline in markdown but largest), `apng` (full color, ~5× smaller than GIF) |
| `-v / --verbose` | off | DEBUG-level logging |

Phase B maps render one engine at a time — pass `--engine sumo` / `--engine matsim` / `--engine dtalite` to render the others (or omit and the CLI picks the first cell on disk).

---

## Output layout

After rendering, the default output dir contains one file per map type:

```
visualization/output/chicago_1k_car/
├── od_origins.png                       # Phase A (cross-engine)
├── od_destinations.png                  # Phase A (cross-engine)
├── link_load_sumo_meso.png              # Phase B (per-engine, per-mode)
├── link_load_matsim_meso.png
├── link_load_dtalite_meso.png
├── congestion_dtalite_meso.png          # DTALite only — SUMO/MATSim skip
├── travel_time_sumo_meso.png
├── travel_time_matsim_meso.png
├── travel_time_dtalite_meso.png
├── route_diversity.png                  # Phase C (cross-engine)
└── animated_flow_matsim_meso.mp4        # Phase C (MATSim only; .gif/.apng also supported)
```

Naming: `<map_type>_<engine>_<mode>.<ext>` for engine-specific output;
plain `<map_type>.<ext>` for bundle-only or cross-engine output. Default
extension is `.png` for statics, `.mp4` for animations.

---

## Coverage matrix

Before any rendering, the CLI prints a coverage report from
`visualization/coverage.py`:

```text
Scenario:  chicago_1k_car
Bundle:    [OK]    scenarios/chicago_1k_car  (demand, manifest, network, signals)
Cells:     [OK]    dtalite/meso  seeds=[42, 43, 44, 45, 46]
Cells:     [OK]    matsim/meso   seeds=[42, 43, 44, 45, 46]
Cells:     [OK]    sumo/meso     seeds=[42, 43, 44, 45, 46]
Cells:     [OK]    sumo/micro    seeds=[42, 43, 44, 45, 46]

Available maps:
  [OK]  od_origins            (bundle present (4 files))
  [OK]  od_destinations       (bundle present (4 files))
  [OK]  link_load             (engines with results: ['dtalite', 'matsim', 'sumo'])
  [OK]  travel_time           (engines with results: ['dtalite', 'matsim', 'sumo'])
  [OK]  congestion            (engines with results: ['dtalite', 'matsim', 'sumo'])
  [OK]  route_diversity       (3 engines with results)
  [OK]  animated_flow         (event-level output present)
```

`[OK]` = the map's inputs are on disk and it will render.
`[--]` = an input is missing; the map will be skipped if requested.
`[FAIL]` = the input was present but the renderer raised — the rest of the run continues.

| Scenario | Behaviour |
|---|---|
| Only bundle present, no simulations run | `od_*` are `[OK]`; everything else `[--]` |
| Only one engine has succeeded | `od_*`, `link_load`, `travel_time` (for that engine) are `[OK]`; `route_diversity` is `[--]` (needs ≥ 2 engines); `congestion` is `[--]` unless that engine is DTALite |
| Bundle missing entirely | All map types `[--]` with reason "missing network.xml or demand.csv in bundle" |
| Unknown map name on CLI | Hard exit (rc=2) with the catalogue |

---

## Data sources

| Data | Origin | Cache location | Helper |
|---|---|---|---|
| Bundle network + demand | `scenarios/<id>/{network.xml, demand.csv}` (canonical bundle) | n/a | — |
| US Census tract polygons (CB 2024, 500k resolution) | US Census Bureau Cartographic Boundary files | `cache/census/<fips>/cb_2024_<fips>_tract_500k.{shp,shx,dbf}` | `python -m tools.download_census_tracts --all-bundled` |
| TIGER PRISECROADS (roads basemap) | US Census TIGER/Line 2024 | `cache/tiger/<fips>/tl_2024_<fips>_prisecroads.{shp,shx,dbf}` | `python -m tools.download_tiger_roads --all-bundled` |
| OSM way geometries (curved link polylines) | Sliced from the scenario's OSM PBF | `cache/osm_ways/<scenario>/` | Built on-demand by `visualization/data/osm_ways.py` |
| Per-cell engine output | `runs/benchmark_*/<scenario>/<engine>/<mode>/seed_*/` | n/a | `python -m execution.run_benchmark <runspec>.yaml` |
| MATSim events (for `animated_flow`) | `output/output_events.xml.gz` in a MATSim cell | n/a (parsed once per render) | Always written by the MATSim adapter |

All cached data is from public-domain US government sources. The two
`tools/download_*.py` helpers are one-shot — they skip downloads whose
shapefiles already exist locally.

---

## Rendering defaults

| Concern | Default |
|---|---|
| DPI | 220 (override with `--dpi`) |
| OD map style | CityScape-derived 100-step blue→red log-scale palette over US Census tracts; light gray (`#dddddd`) for empty tracts |
| Basemap (OD maps) | TIGER PRISECROADS at `linewidth=0.7`, `color="#1a1a1a"`, `alpha=0.7` |
| Basemap (link maps) | The canonical SimForge network (extracted from the bundle's hash-pinned OSM PBF); footways, paths, steps, cycleways, and pedestrian links are excluded by default |
| Background | White everywhere |
| Travel-time colormap | `RdYlGn_r` (green = fast, red = slow) |
| Link-load colormap | `Reds` |
| Congestion colormap | `RdYlGn` (green = free-flow, red = standstill) |
| Route diversity legend | 3 engines = gray (consensus), 2 engines = blue, 1 engine = red (typically DTALite UE alternate) |
| Animated-flow particles | dot size = 9.0 px, red `#e60026` on dark gray `#888888` basemap |
| Output dir | `visualization/output/<scenario>/` (gitignored) |

---

## Cross-engine interpretation notes

### Why SUMO and MATSim `link_load` look identical

SimForge's fairness contract forces SUMO and MATSim to **use the same
routes** — both adapters read SimForge's pre-routed link sequences via
state-aware BFS:

| Engine | Route source | Mobsim job |
|---|---|---|
| SUMO | SimForge BFS routes in `routes.rou.xml` | Queue dynamics + completion |
| MATSim | SimForge BFS routes in `<route type="links">` of plans.xml | Qsim + completion |
| DTALite | Computes its own UE routes via Frank-Wolfe / column generation | Routing + flow assignment |

So when `link_load` aggregates "which links appear in completed trip
routes":

- SUMO and MATSim render the **same** input route distribution (just
  scaled by completion rate — SUMO drops some trips at congested-edge
  insertion, MATSim never does)
- DTALite renders its own UE-equilibrated routes, which spread flow
  across alternative paths

**Visual implication**: SUMO and MATSim `link_load` maps look
~identical (same shape, slightly different intensity); DTALite looks
distinctly different. This is **direct visual proof of the
fair-comparison contract** — when routes are held constant, spatial
traffic structure is identical, so any cross-engine travel-time
difference is purely engine-internal mobsim behavior, not an input
asymmetry.

The `route_diversity` map makes the same story explicit: links picked
by all 3 engines are gray (the BFS consensus), links picked by only 1
are red (the DTALite UE alternates).

### Why `animated_flow` shows "departure bursts"

When watching the particle animation, the swarm of moving dots may
appear to *jump* at certain moments — many vehicles materialize on the
network at once, then traffic thins again until the next jump. Users
typically notice 2-3 such bursts in a `chicago_1k_car` playback, more
in `nyc_10k_car`.

This is **real demand behaviour**, not a rendering glitch. Per
`doc/chapters/methods.md` §3.3 step 9, departures are computed as
`t_depart = t_arrival − JWMNP × 60` where JWMNP (PUMS-reported commute
time in minutes) is quantised by Census to **integer minutes**. Every
person reporting the same JWMNP value lands on the exact same
`departure_time_s`:

- chicago_1k_car: 1000 trips compressed onto **20 unique departure
  timestamps**. Largest burst: 148 trips departing at 28440 s
  (7:54:00 AM).
- nyc_10k_car: 10000 trips onto **34 unique timestamps**. Largest
  burst: 1561 trips at 27000 s (7:30:00 AM).

The animation shows these bursts faithfully — at each PUMS departure
mark (7:00, 7:15, 7:30, 7:40, 7:54…) hundreds-to-thousands of vehicles
enter the network in the same simulation second. The aggregate peak
shape is realistic; the per-second discretisation is the PUMS data
property, not a SimForge artefact.

A future enhancement would add sub-minute uniform jitter
(`random.uniform(-30, +30) s`) to spread bucket-mates across their
60 s window. That's feature-ready in the demand generator but disabled
by default to preserve byte-deterministic `demand.csv` across
regenerations.

### Why `chicago_200k_car od_origins` ≈ `od_destinations`

Among the bundled scenarios, **chicago_200k_car is the only one with a
full-day horizon (7am-4pm)** that produces both AM **and** PM trips per
Phase 9c. Other scenarios are AM-only (single peak hour).

In a full-day demand:

- AM HBW: home → work (origin = home, destination = work)
- PM HBW: work → home (origin = work, destination = home)

The combined `demand.csv`'s origin-set and destination-set are then the
**same set of places** ({homes} ∪ {workplaces}), just visited at
different times. The OD choropleths necessarily look identical because
they aggregate the same node visits.

Numerically:

- chicago_1k_car (AM only): 5.5 % origin↔destination set overlap
- chicago_200k_car (full day): **74 %** overlap

This is correct behavior, not a bug — it reflects the symmetry of
commute patterns once both AM and PM are included. Useful for thesis
§3.3 as evidence the Phase 9c PM chain mechanism produces genuinely
symmetric demand at the metro scale.

---

## Module layout

```
visualization/
├── generate_maps.py        # CLI entry point + per-phase render dispatch
├── coverage.py             # Bundle + run-dir discovery, map_generatable() matrix
├── data/                   # Pure loaders, zero rendering deps
│   ├── bundle.py           # network.xml + demand.csv → Network / Demand dataclasses
│   ├── census.py           # CB 2024 tract shapefiles → TractPolygon list, state detection from bbox
│   ├── events.py           # MATSim events.xml.gz → per-vehicle traversal sequences (for animated_flow particles)
│   ├── osm_ways.py         # OSM PBF → curved link polylines via pyosmium way-id resolution
│   ├── results.py          # Per-engine LinkPerformance + Trip loaders for SUMO/MATSim/DTALite
│   └── tiger_roads.py      # TIGER/Line PRISECROADS shapefile → road polylines
├── render/                 # Matplotlib-only render functions, one file per map type
│   ├── basemap.py          # Faded SimForge network underlay (shared by link maps + animated_flow)
│   ├── od_choropleth.py    # Phase A — filled-tract choropleth (CityScape palette)
│   ├── link_load.py        # Phase B — link_load + congestion (color = volume / speed_ratio)
│   ├── travel_time.py      # Phase B — choropleth of mean travel time by origin tract
│   ├── route_diversity.py  # Phase C — cross-engine consensus / divergence map
│   └── animated_flow.py    # Phase C — particles + throughput animation modes
├── output/                 # Default render destination (gitignored)
│   └── <scenario>/
└── README.md               # This file
```

Lazy imports keep matplotlib + shapely + pyshp off the import path of
anything that doesn't actually render. `visualization/` is never
imported by the main SimForge code paths.

---

## Testing

`tests/test_visualization.py` (13 tests) covers:

- Bundle loaders (network, demand, bbox)
- Coverage discovery + matrix formatting
- Multi-engine coverage detection
- CLI dry-run + bogus-map-name rejection
- End-to-end CLI render writing a non-trivial PNG (skips if the
  Illinois Census tracts aren't cached)

Run via `python -m pytest tests/test_visualization.py -q`. Cached US
Census tracts are not in the test fixtures — the CLI render test skips
gracefully on a machine that hasn't run `download_census_tracts.py`.

---

## Why a separate component?

The visualization layer has different concerns from the rest of
SimForge:

- It doesn't affect the canonical fairness contract — adapters and
  `audit_fairness` are agnostic to it.
- It needs heavier rendering deps (matplotlib + shapely + pyshp + the
  US Census shapefiles); users who never want maps shouldn't pay any
  startup cost.
- It's only used during writeup / analysis, not during simulation —
  the locked benchmark numbers are independent of any plot.
- Keeping it isolated means the main workflow stays lean and the
  visualization layer can evolve independently (e.g., adding a new map
  type doesn't require touching any adapter).
