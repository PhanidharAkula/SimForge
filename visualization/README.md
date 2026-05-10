# SimForge Visualization Component

Standalone, opt-in module for generating geographic visualizations from
SimForge bundles and benchmark results. Runs separately from the main
SimForge workflow — `generate.py`, `run_benchmark.py`, and
`analyze_benchmark` do **not** invoke this module.

## Quick start

Coverage report (what's generatable from current data?):

```bash
python -m visualization.generate_maps --scenario chicago_1k_car --dry-run
```

Render the origin-density choropleth (Phase A flagship):

```bash
python -m visualization.generate_maps --scenario chicago_1k_car --maps od_origins
```

Render both origin + destination densities at higher resolution, custom output:

```bash
python -m visualization.generate_maps --scenario chicago_1k_car \
    --maps od_origins,od_destinations \
    --output runs/benchmark_small/chicago_1k_car/maps \
    --gridsize 80 \
    --cmap viridis
```

## Map types and data tiers

Each map requires different data. The component reports the coverage matrix
before rendering; missing data results in a `[SKIP]`, never an error.

| Map | Phase | Data needed | Generatable when |
|---|---|---|---|
| `od_origins` | A (shipped) | Bundle: `network.xml` + `demand.csv` | After `generate.py` — no simulation needed |
| `od_destinations` | A (shipped) | Bundle: `network.xml` + `demand.csv` | After `generate.py` — no simulation needed |
| `link_load` | B (planned) | Per-engine cell output (SUMO `tripinfo.xml`, MATSim `output_events.xml.gz`, DTALite `link_performance.csv`) | Any successful seed |
| `travel_time` | B (planned) | Per-engine per-trip travel time | Any successful seed |
| `congestion` | B (planned) | Per-engine link speed + free-flow speed | Any successful seed |
| `route_diversity` | C (planned) | Routes from ≥ 2 engines | Multi-engine results |
| `animated_flow` | C (planned) | Event-level engine output (MATSim default) | Successful seed with events |

## Defaults

- **Basemap**: the canonical SimForge network (extracted from the bundle's
  hash-pinned OSM PBF). Fully offline, deterministic, no third-party tile
  service. Footways / cycleways / steps are excluded by default to reduce
  visual noise; pass `--include-pedestrian` (Phase B) to keep them.
- **Output dir**: `runs/<runspec>/<scenario>/maps/` if a benchmark run
  exists for that scenario; else `scenarios/<scenario>/maps/` next to the
  bundle. Override with `--output`.
- **Output format**: PNG at 150 DPI (overridable via `--dpi`).
- **Colormap**: `YlOrRd` (yellow → red, SEARUMS-style aesthetic). Try
  `viridis` for perceptually uniform.

## Edge cases — what happens when data is partial

| Scenario | Behaviour |
|---|---|
| Only bundle present, no simulations run | Coverage matrix reports just `od_*` as generatable; everything else `[SKIP]` |
| Only one engine has succeeded | `od_*`, `link_load` (for that engine), `travel_time` (for that engine) all generatable; `route_diversity` skipped |
| Some seeds failed for an engine | The available seeds are aggregated; PNG annotated with `n=3 (out of 5)` (Phase B) |
| Bundle missing | All map types skipped with reason "missing network or demand" |
| User passes `--maps unknown` | Hard error, exits with usage hint |

## Dependencies

Phase A: `matplotlib`, `lxml`, `numpy` (all already in `requirements.lock`).
Phase B: same. Phase C may need additional deps for animated output;
those will be lazily imported so users not generating videos pay no cost.

## Output layout

After rendering, the output directory contains one PNG per map type:

```
runs/benchmark_small/chicago_1k_car/maps/
├── od_origins.png            # Phase A
├── od_destinations.png       # Phase A
├── link_load_sumo_meso.png   # Phase B (per-engine, per-mode)
├── link_load_matsim_meso.png
├── travel_time_sumo_meso.png
├── route_diversity.png       # Phase C (cross-engine)
└── ...
```

Naming: `<map_type>_<engine>_<mode>.png` for engine-specific maps, plain
`<map_type>.png` for cross-engine or pre-simulation maps.

## Why a separate component?

The visualization layer has different concerns from the rest of SimForge:
- It doesn't affect the canonical fairness contract
- It needs heavier rendering deps (matplotlib geometry stack)
- It's only used during writeup / analysis, not during simulation
- Users who never want maps shouldn't pay any startup cost

Keeping it isolated means the main workflow stays lean and the
visualization can evolve independently.
