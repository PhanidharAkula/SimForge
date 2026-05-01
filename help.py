#!/usr/bin/env python3
"""
SimForge Help System

Comprehensive reference for all commands, options, limits, and examples.
City census limits are auto-detected from modelgen/ files (cached).

Usage:
  python help.py                    # Full help
  python help.py generate           # Data generation help
  python help.py run                # Simulation running help
  python help.py scripts            # Built-in scripts help
  python help.py cities             # Supported cities & limits (live data)
  python help.py modes              # Travel modes reference
  python help.py adapters           # Simulator adapters help
  python help.py metrics            # Evaluation metrics help
  python help.py troubleshooting    # Common issues & fixes
"""

import os
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent))

from pipeline.modelgen_scanner import scan_modelgen_dir

# =============================================================================
# DYNAMIC CITY DATA
# =============================================================================

CITY_META = {
    "chicago": {"name": "Chicago, IL", "lat": 41.878, "lon": -87.630, "radius": 2.0},
    "nyc":     {"name": "New York City, NY", "lat": 40.758, "lon": -73.986, "radius": 2.0},
    "la":      {"name": "Los Angeles, CA", "lat": 34.052, "lon": -118.244, "radius": 5.0},
}


def _fmt(n: int) -> str:
    """Format a number as human-readable: 1044084 -> ~1.04M"""
    if n >= 1_000_000:
        return f"~{n / 1_000_000:.2f}M"
    elif n >= 1_000:
        return f"~{n / 1_000:.0f}K"
    return str(n)


def _build_cities_section() -> str:
    """Build the CITIES help section dynamically from modelgen scan."""
    data = scan_modelgen_dir()
    cities = data.get("cities", {})

    lines = [
        "",
        "=" * 68,
        "  SUPPORTED CITIES & CENSUS LIMITS",
        "  (auto-detected from modelgen/ files)",
        "=" * 68,
        "",
    ]

    if not cities:
        lines.append("  No model files found in modelgen/")
        lines.append("  Place *_model.txt files in the modelgen/ folder.")
        return "\n".join(lines)

    for city_key in sorted(cities.keys()):
        stats = cities[city_key]
        meta = CITY_META.get(city_key, {})
        name = meta.get("name", city_key.title())
        lat = meta.get("lat", "?")
        lon = meta.get("lon", "?")
        radius = meta.get("radius", "?")

        car = stats["mode_counts"].get("car", 0)
        transit = stats["mode_counts"].get("transit", 0)
        bike = stats["mode_counts"].get("bike", 0)
        walk = stats["mode_counts"].get("walk", 0)
        total = stats["commuters"]

        lines.append(f"  {city_key.upper()} ({name})")
        lines.append(f"    File:       {stats['file']} ({stats['size_mb']} MB)")
        lines.append(f"    Center:     {lat}, {lon}   Default radius: {radius} km")
        lines.append(f"    Buildings:  {stats['total_buildings']:,}")
        lines.append(f"    Households: {stats['total_households']:,}")
        lines.append(f"    Persons:    {stats['total_persons']:,}")
        lines.append("    +-----------+------------+----------+")
        lines.append("    | Mode      |     Trips  | Approx.  |")
        lines.append("    +-----------+------------+----------+")
        lines.append(f"    | Car       | {car:>10,} | {_fmt(car):>8} |")
        lines.append(f"    | Transit   | {transit:>10,} | {_fmt(transit):>8} |")
        lines.append(f"    | Bike      | {bike:>10,} | {_fmt(bike):>8} |")
        lines.append(f"    | Walk      | {walk:>10,} | {_fmt(walk):>8} |")
        lines.append("    +-----------+------------+----------+")
        lines.append(f"    | TOTAL     | {total:>10,} | {_fmt(total):>8} |")
        lines.append("    +-----------+------------+----------+")
        lines.append("")

    lines.append("  NOTES:")
    lines.append("    * These are FULL model file limits (no bbox filter).")
    lines.append("    * Actual trips depend on --radius (smaller = fewer).")
    lines.append("    * Use --allow-oversample to exceed these limits.")
    lines.append("    * Use --synthetic for unlimited trips (gravity model).")
    lines.append("")
    lines.append("  SCALING GUIDELINES:")
    lines.append("    Radius   Approx. coverage of full census data")
    lines.append("    ------   --------------------------------------")
    lines.append("     2 km    ~1-5% of census records")
    lines.append("     5 km    ~5-15% of census records")
    lines.append("    10 km    ~15-40% of census records")
    lines.append("    20 km    ~40-70% of census records")
    lines.append("    50 km    ~70-100% of census records")
    lines.append("")
    lines.append("  ADDING NEW CITIES:")
    lines.append("    1. Place <city>_model.txt in modelgen/")
    lines.append("    2. The scanner auto-detects it on next run")
    lines.append("    3. Add city coordinates to generate.py CITIES dict")
    lines.append("    4. Run: python help.py cities  (to verify)")
    lines.append("")

    return "\n".join(lines)


# =============================================================================
# STATIC HELP SECTIONS
# =============================================================================

HELP_OVERVIEW = """
====================================================================
  SimForge Help System
  Reproducible Cross-Simulator Traffic Benchmarking
====================================================================

SimForge generates standardized traffic simulation data from real
U.S. Census microdata, converts it to multiple simulator formats,
and provides unified evaluation metrics.

QUICK START:
  0. Install:         python setup_simforge.py && source .venv/bin/activate
  1. Generate data:   python generate.py --city chicago --trips 1000
  2. Validate:        python -m pipeline.validation.validate_bundle scenarios/chicago_1k_car
  3. Run simulation:  python run.py --scenario chicago_1k_car --engine sumo --mode meso
  4. Run benchmark:   python -m execution.run_benchmark runspecs/benchmark_small.yaml

INTERACTIVE MENU (when run from a terminal):
  python help.py                    Full-screen TUI (curses-based).
                                      ↑/↓:    navigate / scroll
                                      Enter:  open the highlighted topic
                                      Esc:    return to the menu
                                      q:      quit (from the menu)
                                    PgUp/PgDn page-scroll and Home/End
                                    jump-to-top/bottom also work inside
                                    a topic (use Fn + arrows on Mac
                                    compact keyboards).
  python help.py --interactive      Force interactive mode (e.g. for testing)
  python help.py --no-interactive   Force this overview text (escape hatch)

  Falls back automatically to a numbered-input menu (with /<word>
  search) if curses can't initialise — e.g. on dumb terminals.

PASTE-SAFE TEXT MODE (any topic name, any environment):
  python help.py setup              Install and bootstrap
  python help.py generate           Data generation entry point — generate.py
  python help.py run                Simulation execution entry point — run.py
  python help.py scripts            Built-in preset scripts
  python help.py cities             Supported cities, census limits — live data
  python help.py modes              Travel modes reference
  python help.py adapters           Simulator adapters — SUMO, MATSim, DTALite
  python help.py metrics            Evaluation metrics
  python help.py evaluation         Analysis, fairness audit, plot generation
  python help.py schema             Canonical schema format reference
  python help.py benchmark          Benchmark harness and runspecs
  python help.py tests              Test suite reference
  python help.py analyzer           tools/analyze_scenarios.py — bundle analyzer
  python help.py troubleshooting    Common issues and fixes

PROJECT STRUCTURE (alphabetical, repo root):
  adapters/             Simulator-specific converters (sumo, matsim, dtalite)
  canonical/            Canonical bundle schema spec (canonical/schema/)
  cluster/              HPC cluster integration (Pitzer SLURM sbatches)
  doc/                  Architecture, retrospectives, thesis chapters
                        (doc/engines/ has LPSim/QarSUMO retrospectives +
                        DTALite selection rationale + thesis quote bank)
  evaluation/           Metrics, analysis, fairness audit, plot generation
  execution/            Benchmark harness (runspec-driven, run_benchmark.py)
  lib/                  Third-party JARs (matsim-15.0/) + version pins
                        (lib/dtalite/manifest.json)
  modelgen/             Census microdata files (ModelGen PUMS)
  osm_data/             Hash-pinned OSM PBF snapshots + manifest.json
                        (URL + SHA256 provenance for every PBF)
  pipeline/             Data generation modules (network, demand, signals)
  runspecs/             Benchmark configuration files (YAML)
  scenarios/            Generated canonical data bundles
  scripts/              5 ready-to-use generation scripts (01–05)
  tests/                Test suite (pytest, ~477 tests across 23 files
                        with the 3 tracked bundles; +36 per extra bundle)
  tools/                Operator utilities (analyze_scenarios.py, clean.sh,
                        download_osm.py, env_report.py, inspect_network.py)

  Top-level files:
    generate.py         Unified scenario generator (start here)
    run.py              Simulation runner CLI
    help.py             This help system
    setup_simforge.py   Bootstrap installer (creates .venv, installs deps)
"""

HELP_GENERATE = """
====================================================================
  DATA GENERATION (generate.py)
====================================================================

The unified generator creates canonical scenario bundles using real
U.S. Census PUMS microdata (via ModelGen) as the default demand source.

BASIC USAGE:
  python generate.py --city <city> --trips <count>

REQUIRED FLAGS:
  --city, -c <name>        City key (e.g. chicago, nyc, la)

DEMAND FLAGS:
  --trips, -t <count>      Number of OD trips (default: 5000)
  --modes <list>           Comma-separated: car,transit,bike,walk (default: car)
  --start-time <seconds>   Start time, seconds from midnight (default: 25200 = 07:00 AM)
  --end-time <seconds>     End time, seconds from midnight   (default: 28800 = 08:00 AM)

  The default 07:00–08:00 AM rush-hour window matches the bundled
  chicago_1k_car scenario. Together with --radius 2.0 (default for chicago)
  and --seed 42, `generate.py --city chicago --trips 1000` reproduces the
  bundled scenario exactly.

NETWORK FLAGS:
  --radius, -r <km>        Network extraction radius (default: city-specific)

CONTROL FLAGS:
  --seed, -s <int>         Random seed (default: 42)
  --output, -o <path>      Custom output directory
  --id <string>            Custom scenario ID

DEMAND SOURCE FLAGS:
  --synthetic              Force synthetic gravity model
  --allow-oversample       Allow more trips than census commuters

OSM SOURCE FLAGS (mutually exclusive):
  (default)                Use osm_data/<pbf> for the city; FAIL HARD if the
                           PBF is missing. Bundle is byte-reproducible because
                           the PBF is hash-pinned in osm_data/manifest.json.
  --allow-overpass         If osm_data/<pbf> is missing, fall back to the live
                           Overpass API. PBF is still preferred when available.
                           WARNING: Overpass bundles are NOT byte-reproducible.
  --force-overpass         Always use the live Overpass API, ignoring any local
                           PBF. WARNING: NOT byte-reproducible. Use only for
                           one-off experiments or when you specifically want
                           today's OSM data.

OUTPUT FLAGS:
  --verbose                Show pipeline INFO logs (osmnx, demand, signals).
                           Default: WARNING and above only — clean per-step
                           ✓ rows + sticky progress bar. With --verbose the
                           bar stays visible and INFO logs are routed above
                           it cleanly.

DISPLAY FLAGS:
  --list                   Show all cities, presets, modes, and limits
  --preset, -p <name>      Use a preset configuration

TIME REFERENCES (seconds from midnight):
  06:00=21600  07:00=25200  08:00=28800  09:00=32400  10:00=36000
  12:00=43200  18:00=64800  24:00=86400

EXAMPLES:
  python generate.py --city chicago --trips 5000
  python generate.py --city la --trips 200000 --modes car,transit \\
         --start-time 21600 --end-time 32400
  python generate.py --city chicago --trips 10000 --radius 8.0 --seed 7
  python generate.py --city la --trips 2000000 --allow-oversample
  python generate.py --city chicago --trips 5000 --synthetic
  python generate.py --city chicago --trips 5000 --force-overpass    # today's OSM
  python generate.py --city chicago --trips 5000 --verbose           # firehose
  python generate.py --preset chicago_1k_car
  python generate.py --preset nyc_10k_car --trips 100000 --city la

OUTPUT:
  scenarios/<scenario_id>/
    network.xml, demand.csv, signals.xml, config.xml,
    manifest.xml, generation_metadata.json
"""

HELP_RUN = """
====================================================================
  SIMULATION RUNNING (run.py)
====================================================================

FLAGS:
  --scenario, -s <name>    Scenario name(s), comma-separated
  --engine, -e <name>      Engine(s): sumo, matsim, dtalite (comma-separated)
  --mode, -m <name>        Mode(s): micro, meso (comma-separated)
  --repeats, -r <n>        Repeats (default: 10)
  --seed <int>             Base random seed (default: 42)
  --timeout, -t <seconds>  Per-run timeout (default: 3600)
  --output, -o <path>      Output directory (default: runs/)
  --verbose                Show adapter INFO logs (default: WARNING+ only).
                           Bar stays visible; logs routed above it.
  --list, -l               List available options
  --validate-only, -v      Only validate, don't simulate

ENGINE / MODE COMPATIBILITY:
  SUMO supports both meso and micro. MATSim and DTALite are mesoscopic
  only. Cells with an unsupported (engine, mode) pair are skipped — not
  silently re-run as meso. The startup banner prints which pairs were
  skipped and why.

  --engine sumo,matsim,dtalite --mode meso,micro --repeats 3 across 2
  scenarios is 8 valid cells × 3 reps = 24 runs (NOT 36 — the 4 invalid
  matsim/micro and dtalite/micro pairs are skipped).

OUTPUT FORMAT:
  Per-cell rows show: [N/total] engine mode seed=N ✓/✗ runtime
  Scenario dividers (▶ scenario_name) group cells visually.
  Sticky progress bar at the bottom (TTY only) shows overall %,
  ✓N ✗N counters, elapsed clock, and a Braille spinner heartbeat
  (~8 fps) so long-running cells don't look stuck. (No ETA — SimForge
  cells are wildly heterogeneous, so a running-mean ETA swings between
  unhelpful extremes; the percentage + counter + elapsed carry the
  same information without misleading you.)
  Final summary includes per-cell timing breakdown (mean ± 95% CI across
  reps, computed via evaluation/metrics/confidence.py — same Student's-t
  table the thesis tables/figures use).

EXAMPLES:
  python run.py --engine sumo --mode meso
  python run.py --scenario chicago_1k_car --engine sumo,matsim,dtalite \\
         --mode meso --repeats 3
  python run.py --scenario chicago_1k_car --engine sumo --mode meso,micro \\
         --repeats 5 --verbose
  python run.py --validate-only

POST-BENCHMARK PIPELINE (canonical 3-step):
  python -m evaluation.analyze_benchmark <run-dir>/benchmark_results.json
  python -m evaluation.audit_fairness    <run-dir>
  python -m evaluation.generate_plots    <run-dir>/benchmark_results.json

BENCHMARK HARNESS (runspec-driven, for full matrices):
  python -m execution.run_benchmark runspecs/benchmark_small.yaml       # canonical matrix
  python -m execution.run_benchmark runspecs/benchmark_small.yaml
  python -m execution.run_benchmark runspecs/benchmark_small.yaml --dry-run

run.py vs run_benchmark.py:
  Both call the same adapters; the wrapping differs. run.py writes a flat
  per-cell layout and a benchmark_results.json with a {timestamp, matrix,
  summary, results} top-level. run_benchmark.py writes a nested
  scenario/engine/seed_N layout and a benchmark_results_<runspec>.json
  with a {runspec_name, started_at, completed_at, total_runs, ..., summary,
  results} top-level. Use run.py for ad-hoc work, run_benchmark for locked
  thesis matrices. audit_fairness, analyze_benchmark, and generate_plots
  consume both layouts. Full side-by-side: doc/RESULTS_GUIDE.md sec 2.
"""

HELP_SCRIPTS = """
====================================================================
  BUILT-IN SCRIPTS (scripts/)
====================================================================

5 ready-to-use generation scripts, from small to big. All accept --verbose / -v.
All five generate car-only demand to match what the engine adapters simulate
today (see python help.py modes for the engine mode-coverage explanation).

  python scripts/01_chicago_1k_car.py    [--verbose]   Tiny test fixture
  python scripts/02_nyc_10k_car.py       [--verbose]   Small morning commute
  python scripts/03_la_50k_car.py        [--verbose]   Medium tier
  python scripts/04_chicago_200k_car.py  [--verbose]   Large full-day
  python scripts/05_nyc_500k_car.py      [--verbose]   Stress test at scale

  +----+----------------------+----------+---------+------+----------+
  | #  | Script               | City     |  Trips  | Mode | Time     |
  +----+----------------------+----------+---------+------+----------+
  | 01 | chicago_1k_car       | Chicago  |   1,000 | car  | 07-08 AM |
  | 02 | nyc_10k_car          | NYC      |  10,000 | car  | 07-09 AM |
  | 03 | la_50k_car           | LA       |  50,000 | car  | 06-10 AM |
  | 04 | chicago_200k_car     | Chicago  | 200,000 | car  | 00-24:00 |
  | 05 | nyc_500k_car         | NYC      | 500,000 | car  | 06-10 AM |
  +----+----------------------+----------+---------+------+----------+

EQUIVALENT -- via generate.py presets (same code path, prefer this form):
  python generate.py --preset chicago_1k_car
  python generate.py --preset nyc_10k_car
  python generate.py --preset la_50k_car
  python generate.py --preset chicago_200k_car
  python generate.py --preset nyc_500k_car

  scripts/0X are thin wrappers that import generate_scenario() and call it
  with hardcoded kwargs. They accept --verbose / -v only. The preset form
  is preferred when you need other overrides (--output, --seed, --city,
  --modes, --synthetic, OSM source mode):
    python generate.py --preset nyc_10k_car --city la --verbose
"""

HELP_MODES = """
====================================================================
  TRAVEL MODES REFERENCE
====================================================================

SUPPORTED MODES (4 simulator buckets generated from 12 cityscape codes):
  car      Road vehicle    (Car/truck/van, Taxi, Motorcycle)
  transit  Public transport (Bus, Subway, Commuter rail, Light rail, Ferry)
  bike     Bicycle
  walk     Walked

  A 5th implicit bucket "home" excludes WFH workers and "Other method"
  from the demand pool entirely (no commute trip generated).

CENSUS MODE MAPPING (cityscape Schedule-generator branch / ACS PUMS 2021):
   1 Car, truck, or van                    > car
   2 Bus                                   > transit
   3 Subway or elevated rail               > transit
   4 Long-distance / commuter rail         > transit
   5 Light rail, streetcar, trolley        > transit
   6 Ferryboat                             > transit
   7 Taxicab                               > car
   8 Motorcycle                            > car
   9 Bicycle                               > bike
  10 Walked                                > walk
  11 Worked from home                      > home (excluded — no trip)
  12 Other method                          > home (excluded — no trip)
  -1 N/A — not a worker (cityscape's "bb" sentinel)

  Single source of truth: pipeline/demand/parse_model_file.py:200
  See doc/MODELGEN_AND_MODES.md §2 + §4 for cityscape provenance and the
  per-city per-code histograms.

SIMULATOR SUPPORT — what SimForge currently wires up (vs engine capability):
  SUMO:    car only                    (engine supports PT/bike/walk via
                                        busStop/ptlines/vClass; not wired up)
  MATSim:  car only                    (engine supports full multi-modal;
                                        only `mode=car` modeParams configured)
  DTALite: car only                    (engine is car-only by design)

  When simulating a multi-mode bundle, every adapter mode-filters demand to
  its supported set. The shared feasibility filter is mode-aware too, so
  audit_fairness Q3 compares engines on the same mode-restricted target.
  See doc/MODELGEN_AND_MODES.md §5 for adapter mode handling and §8 for
  the future-work pathway to true multi-modal simulation.
"""

HELP_ADAPTERS = """
====================================================================
  SIMULATOR ADAPTERS
====================================================================

SUPPORTED SIMULATORS:
  SUMO     1.26+     Microscopic/mesoscopic vehicle simulation (eclipse-sumo wheel)
  MATSim   15.0      Activity-based mesoscopic multi-agent sim
  DTALite  0.10.0+   CPU mesoscopic Dynamic Traffic Assignment (path4gmns)

  All three adapters currently configure car-only simulation. When given
  a multi-mode bundle they mode-filter demand to mode==car before routing,
  via the shared mode-aware feasibility filter (adapters/common/feasibility.py).
  See doc/MODELGEN_AND_MODES.md §5 + §6 for adapter mode handling and the
  PT-module wiring required for true multi-modal simulation.

  LPSim, POLARIS, and QarSUMO are documented as evaluated-and-rejected
  in doc/engines/{LPSIM,QARSUMO}_RETROSPECTIVE.md and
  doc/engines/THIRD_ENGINE_OPTIONS.md.

ADAPTER CLI:
  python -m adapters.sumo.cli    <scenario_path> <output_dir>          # convert only
  python -m adapters.sumo.cli    <scenario_path> <output_dir> --run --mesoscopic
  python -m adapters.matsim.cli  <scenario_path> <output_dir> --run
  python -m adapters.dtalite.cli <scenario_path> <output_dir> --run    # CPU only

SUMO NOTES:
  * `--run` invokes `sumo` with `--ignore-route-errors`. That flag is required:
    SimForge pre-computes routes by BFS on the canonical node graph, which can
    disagree with SUMO's edge-level lane connectivity on real-world networks.
    If you drive `sumo` by hand, always pass `--ignore-route-errors`:
        sumo -c toy.sumocfg --ignore-route-errors
  * Add `--mesosim true` (or use our `--mesoscopic` flag) for the faster
    mesoscopic model; omit for the default microscopic simulation.

PREREQUISITES:
  SUMO:    bundled in requirements.lock (eclipse-sumo wheel) — `uv pip install -r requirements.lock` puts `sumo`, `netconvert`, `sumo-gui` directly in `.venv/bin/`. Verify: `sumo --version`.
  MATSim:  Download JAR to lib/matsim-15.0/, requires Java 17+
  DTALite: `uv pip install path4gmns` (binary ships in the package).
           On Mac: `brew install libomp` for the OpenMP runtime.
           No GPU, no extra build step, runs natively on Linux x86_64,
           macOS arm64/x86_64, and Windows.
"""

HELP_METRICS = """
====================================================================
  EVALUATION METRICS
====================================================================

1. FIDELITY -- How close to real traffic?
   RMSE:  sqrt(mean((observed - simulated)^2))
   GEH:   sqrt(2(S-O)^2 / (S+O))   [<5 good, 5-10 check, >=10 poor]
   KS:    max|F_A(x) - F_B(x)|

2. SCALABILITY -- How does cost scale?
   Throughput:  trips / wall_clock_seconds
   SRT Ratio:   simulated_time / wall_clock_time

3. REPRODUCIBILITY -- How consistent?
   R-Index:  R = 1 - sigma/mu   [>=0.99 excellent, >=0.95 very good]

COMMANDS:
  python -m evaluation.analyze_benchmark runs/benchmark_results.json
  python -m evaluation.compare_modes scenarios/chicago_1k_car
  python -m evaluation.generate_plots runs/results.json --output figures/
"""

HELP_SCHEMA = """
====================================================================
  CANONICAL SCHEMA REFERENCE
====================================================================

6 files per scenario bundle:

1. network.xml              -- Directed road graph from OSM. V5+ also
                               carries `has_signal="true"` on traffic-signal
                               nodes (Phase 6) and a top-level
                               <turn_restrictions> block extracted from
                               OSM `type=restriction via=node` relations
                               (Phase 7).
2. demand.csv               -- Trip-level OD: trip_id, origin_node_id,
                               destination_node_id, departure_time_s, mode.
                               V5+ adds two informational columns:
                               `dest_source` (schedule|gravity provenance)
                               and `purpose` (HBW_AM/PM, HBSchool_AM/PM,
                               HBW_*_chained — 4-step taxonomy from
                               Phase 9). Adapters consume the canonical
                               5-column subset by name and ignore the
                               provenance columns.
3. signals.xml              -- Fixed-time traffic signal phases at every
                               OSM-tagged `highway=traffic_signals` node
                               in the bbox (1.4-4.8% of nodes — chicago
                               2.79%, nyc 4.80%, la 1.35% empirically;
                               placeholder 90s 2-phase cycle template —
                               placement is real, timing is synthetic).
                               See doc/SCENARIO_GENERATION.md
                               §"Step 2: Traffic Signals" for full provenance.
4. config.xml               -- Scenario metadata (time, seed, units)
5. manifest.xml             -- File inventory
6. generation_metadata.json -- Per-step source / parameter / hash trail
                               (generator version, seed, OSM source, demand
                               source, modelgen city stats, SCC drop counts,
                               V5+ demand_provenance block with schedule-
                               vs-gravity split + per-reason fallback counts.
                               Chain-leg counts come from the demand.csv
                               `purpose` column, not this block.)

VALIDATION:
  python -m pipeline.validation.validate_bundle scenarios/<id>
"""

HELP_EVALUATION = """
====================================================================
  EVALUATION, ANALYSIS & PLOTTING
====================================================================

ANALYZE BENCHMARK:
  python -m evaluation.analyze_benchmark <results.json>
  python -m evaluation.analyze_benchmark <results.json> --latex --markdown

  Produces:
    Summary               — engine-level aggregates (success rate, avg runtime, R)
    Coverage diagnostic   — flags low-sample (n<3), asymmetric, silently-failed cells
    Demand Composition    — per-scenario V5+ trip-purpose breakdown
                            (HBW_AM/PM, HBSchool_AM/PM, HBW_*_chained)
                            from each bundle's canonical demand.csv;
                            silently omitted for pre-V5 bundles missing
                            the `purpose` column.
    Table 5.1 — Runtime comparison (engine x city x mode)
    Table 5.2 — Reproducibility analysis (R-scores + Adj TT column*)

  --latex       emit LaTeX tables (ready for thesis inclusion)
  --markdown    emit Markdown tables (for docs / GitHub)

  * Adj TT: intersection-corrected mean travel time, computed over the trip-ID
    set completed by ALL engines for a given (scenario, mode, seed).  Eliminates
    the sample bias from SUMO dropping ~5 trips that MATSim always completes.
    Populated automatically when run-artifact directories exist next to the JSON.

AUDIT CROSS-ENGINE FAIRNESS:
  python -m evaluation.audit_fairness <run-dir> [seed]

  Read-only methodology check that every engine in <run-dir> received the
  same problem and was measured the same way. Four fairness questions
  per scenario plus one informational composition section:

    Q1 — same trip set across engines (feasibility verdict byte-identical)
    Q2 — same network across engines (SCC node + link counts match)
    Q3 — same trip count actually simulated (per-engine output count)
    Q4 — cross-engine travel-time spread (mean / P95 / pairwise ratios)
    Q5 — demand composition (V5+ trip-purpose breakdown)
         informational, not a fairness gate. Reads the canonical bundle's
         demand.csv `purpose` column; pre-V5 bundles emit a one-line
         skip and the section is omitted from output.

  Auto-detects four output layouts (run.py flat, run_benchmark nested,
  parallel-by-scenario sbatch nested, per-scenario worker dir). Use this
  before claiming any cross-engine number in the thesis.

COMPARE MICRO vs MESO:
  python -m evaluation.compare_modes <scenario_path>                  # live run
  python -m evaluation.compare_modes --from-benchmark <results.json>  # from existing

  Produces:
    Speedup factors (meso vs micro per engine)
    Travel time difference (mean delta, %)

GENERATE THESIS PLOTS:
  python -m evaluation.generate_plots <results.json> [--output DIR] [--clean]

  Generates (PNG + PDF):
    Fig 5.1 — Runtime comparison (grouped bar: city x engine)
    Fig 5.2 — Reproducibility heatmap (engine x city R-scores)
    Fig 5.3 — Travel time comparison (mean +/- std by engine)
    Fig 5.4 — Engine performance summary (runtime, R-score, throughput)
    Fig 5.5 — Speedup vs MATSim baseline
    Fig 5.6 — Micro vs Meso runtime comparison
    Fig 5.7 — Runtime variability box plot
    Fig 5.8 — P95 tail latency comparison
    Fig 5.9 — Trip-count parity (engine-internal drop reasons)

  Default output: plots/ next to the results JSON file.
  Use --clean to delete old plots before regenerating.

EXAMPLES (using the canonical stress-test runspec):
  python -m evaluation.analyze_benchmark \\
         runs/benchmark_small/benchmark_results_benchmark_small.json --latex --markdown
  python -m evaluation.audit_fairness runs/benchmark_small
  python -m evaluation.compare_modes --from-benchmark \\
         runs/benchmark_small/benchmark_results_benchmark_small.json
  python -m evaluation.generate_plots \\
         runs/benchmark_small/benchmark_results_benchmark_small.json \\
         --output doc/figures --clean
"""

HELP_BENCHMARK = """
====================================================================
  BENCHMARK HARNESS & RUNSPECS
====================================================================

COMMANDS:
  python -m execution.run_benchmark <runspec.yaml>
  python -m execution.run_benchmark <runspec.yaml> --mesoscopic
  python -m execution.run_benchmark <runspec.yaml> --dry-run
  python -m execution.run_benchmark <runspec.yaml> --scenario chicago_1k_car
  python -m execution.run_benchmark <runspec.yaml> --verbose
  python -m execution.run_benchmark <runspec.yaml> --output runs/test1

FLAGS:
  --scenario, -s <id>   Only run scenarios matching this ID
  --dry-run, -n         Validate + print plan; no execution
  --output, -o <path>   Override the runspec's output_dir
  --mesoscopic, -m      Force every row to mesoscopic (overrides per-row mode:)
  --verbose             Show adapter INFO logs above the sticky bar

BUILT-IN RUNSPECS:
  benchmark_small.yaml   Canonical 11-cell matrix used for thesis Chapter 5:
                         chicago_1k_car + nyc_10k_car each x {SUMO meso,
                         SUMO micro, MATSim meso, DTALite meso} (4 cells)
                         plus la_50k_car x {SUMO meso, MATSim meso,
                         DTALite meso} (3 cells, no SUMO micro at 50K),
                         N=5 repeats per cell = 55 runs total. Runs end-to-end
                         on a Mac laptop (DTALite is CPU-only).
  benchmark_large.yaml   chicago_200k_car + nyc_500k_car, mesoscopic only,
                         3 engines x 2 scenarios x 5 reps = 30 runs.
                         Per-run timeout 3600 s for 200K, 7200 s for 500K
                         (HPC tier — submit via cluster/jobs/benchmark_large.sbatch;
                         bundles are gitignored, rsync from your dev box first).

OUTPUT FORMAT:
  Banner with the matrix dimensions (Runspec, Scenarios, Engines, Modes,
  Repeats, Total). Pre-validation block (each unique bundle once).
  Scenario dividers (▶ scenario_id) group cells visually. Per-cell rows:
  [N/total] engine mode seed=N ✓/✗ runtime. Sticky progress bar at the
  bottom (TTY only) shows %, ✓N ✗N counters, elapsed clock, Braille
  spinner heartbeat. (No ETA — see python help.py run for rationale.)
  Final summary mirrors run.py: Wall time + ✓ Completed + ✗ Failed + per-cell
  timing breakdown (mean ± 95% CI across reps, Student's-t via
  evaluation/metrics/confidence.py). Default mode shows WARNING+ records
  routed above the bar via print_above(); --verbose drops the threshold to
  INFO+ for full adapter chatter.

REPRODUCE THE THESIS NUMBERS END-TO-END (~40-100 min on M-series Mac;
~25 min on Linux/HPC where SUMO micro on nyc_10k_car runs faster):
  python -m execution.run_benchmark runspecs/benchmark_small.yaml
  python -m evaluation.analyze_benchmark \\
         runs/benchmark_small/benchmark_results_benchmark_small.json --latex --markdown
  python -m evaluation.audit_fairness runs/benchmark_small
  python -m evaluation.generate_plots \\
         runs/benchmark_small/benchmark_results_benchmark_small.json --output doc/figures

OUTPUT SHAPE:
  runs/<runspec_name>/
    benchmark_results_<runspec_name>.json   # canonical result schema
    <scenario_id>/<engine>/seed_<N>/        # per-cell engine artefacts
      feasibility_report.json               # SCC filter audit trail
      tripinfo.xml / output_trips.csv.gz    # engine-native outputs

  Top-level JSON keys: runspec_name, started_at, completed_at, total_runs,
  successful_runs, failed_runs, summary, results[]. Each results[] entry
  carries scenario, scenario_id, engine, mode, seed, repeat, repeat_index,
  status, runtime_s, wall_time_s, output_dir, tripinfo_path, error_message,
  metrics. Schema is BenchmarkResult.to_dict() in execution/run_benchmark.py.

  This layout differs from run.py's flat output (runs/benchmark_<timestamp>/
  <scenario>_<engine>_<mode>_seed<N>/ + benchmark_results.json with a
  {timestamp, matrix, summary, results} top-level). The downstream tools
  (audit_fairness, analyze_benchmark, generate_plots) handle both. Full
  side-by-side comparison: doc/RESULTS_GUIDE.md sec 2.
"""

HELP_TESTS = """
====================================================================
  TEST SUITE REFERENCE
====================================================================

SimForge ships ~477 tests across 23 files with the 3 tracked bundles
(chicago_1k_car, nyc_10k_car, la_50k_car). The count is
369 base + 36 parametrized per bundle in `scenarios/`. Generating the
two larger tiers (`scripts/04_chicago_200k_car.py` + `05_nyc_500k_car.py`)
adds 72 more tests for a 549-test full local sweep. The shipped 477-test
suite runs in ~3-4 min on arm64 (~22 s on a Linux box where SUMO doesn't
crash); the 549-test full sweep takes ~14 min on M-series Mac because
the integrity tests parse the much larger 200K/500K network.xml files.

Pytest config lives in pyproject.toml [tool.pytest.ini_options] with
--strict-markers + --tb=short. Shared fixtures and platform-skip
helpers live in tests/conftest.py.

RUN COMMANDS:
  python -m pytest                              # Full suite — per-FILE rollup rows
  python -m pytest -v                           # Verbose — per-TEST ✓/✗/⊘ rows
  python -m pytest -v -x                        # Verbose, stop on first failure
  python -m pytest tests/test_feasibility.py    # One file
  python -m pytest tests/test_feasibility.py -v # One file, verbose
  python -m pytest tests/test_scc.py -k "kosaraju"      # Substring filter
  python -m pytest --cov --cov-report=term-missing      # With coverage
  python -m pytest --cov --cov-fail-under=70            # Enforce 70 % floor
  python -m pytest -n auto                      # Parallel (needs pytest-xdist)
  python -m pytest --collect-only               # List tests without running
  python -m pytest -p no:sticky_progress        # Plain pytest output (no plugin)

MARKERS (registered in pyproject.toml; --strict-markers enforced):
  integration     Exercises multiple subsystems end-to-end
  determinism     Verifies byte-identical adapter outputs across re-runs
  requires_sumo   Needs sumo / netconvert on PATH
  requires_java   Needs Java 17+ and the MATSim JAR
  requires_gpu    Needs an NVIDIA GPU + a built LPSim binary (no CPU
                  fallback; preserved for the LPSim retrospective)

  Filter examples:
    python -m pytest -m determinism
    python -m pytest -m integration
    python -m pytest -m "not requires_sumo"

TEST FILES (23 files / ~477 tests with the 3 tracked bundles in scenarios/;
~549 with all 5 generated. Alphabetical):

  test_adapter_determinism.py     (8)   Byte-identical re-runs @determinism
  test_analyze_benchmark.py       (24)  Mode-aware grouping + all renderers
                                        (incl. Phase 10 demand composition table)
  test_audit_fairness.py          (29)  Q1-Q4 audit helpers + 4-layout detector
                                        + synthetic-run-dir orchestrator test
  test_confidence.py              (18)  Student's-t 95 % CI core + edge cases
  test_demand_composition.py      (7)   V5+ Phase 10 — `purpose` column tally,
                                        AM/PM peak split, chain-leg counter,
                                        pre-V5 graceful no-op
  test_demand_generators.py       (21)  Uniform / gravity / peak-hour
  test_dtalite_adapter.py         (46)  DTALite adapter writers, settings,
                                        demand-driven zoning, end-to-end smoke
  test_engine_smoke.py            (4)   Real-binary SUMO/MATSim/DTALite [skip-on-miss]
  test_feasibility.py             (19)  Shared cross-engine trip filter
                                        + mode-aware feasibility (V5)
  test_fidelity_metrics.py        (21)  RMSE / GEH / KS / combined
  test_matsim_adapter.py          (24)  MATSim helpers + end-to-end + sweep
                                        (~10 min on M-series Mac — see
                                        TESTING.md §3 for the -k escape)
  test_metrics_travel_time.py     (2)   tripinfo.xml parser
  test_osm_fetch.py               (20)  Mocked Overpass/osmnx pipeline
  test_parse_model_file.py        (27)  ModelGen file parser + V5 Phase 5
                                        JWTRNS mapping + Phase 9 HBSchool helpers
                                        + AM_PURPOSES/PM_PURPOSES disjointness
  test_pipeline_e2e.py            (20)  13 corruption + 3 robustness + 4 routing
  test_reproducibility_metrics.py (15)  R-score core + edge cases
  test_scalability_metrics.py     (8)   SimulationTimer, throughput
  test_scc.py                     (14)  Iterative Kosaraju + parser
  test_scenario_data_integrity.py (108) 7 classes × 36 tests/scenario, scales
                                        with scenarios/ contents (108 = 3
                                        tracked bundles × 36; 180 if all 5
                                        bundles generated; 0 if scenarios/ empty)
  test_sumo_adapter.py            (4)   SUMO input bundle + sweep
  test_turn_restrictions.py       (17)  V5+ Phase 7 — OSM restriction parser,
                                        forbidden-move builder, state-aware
                                        BFS, DTALite movement.csv writer
  test_validator.py               (2)   Bundle pass + corruption fail
  test_vehicle_types.py           (19)  V5+ Phase 11 — canonical car constants,
                                        SUMO/MATSim XML emission, cross-engine
                                        equivalence (length+gap == effective)

test_scenario_data_integrity.py classes (7, parametrized over every scenario):
  TestFileExistence       All 5 canonical files exist
  TestXMLParsing          All XML files are well-formed
  TestNetworkIntegrity    Unique node/link IDs, WGS84 coords, valid endpoints
  TestDemandIntegrity     Required columns, unique trip IDs, OD nodes exist
  TestConfigIntegrity     Metadata, scenario_id matches dir, valid horizon
  TestManifestIntegrity   Manifest ID matches config, all declared files exist
  TestSignalsIntegrity    Signal junction references exist in the network

WHAT THE OUTPUT LOOKS LIKE:
  Default — per-file rollup rows + sticky progress bar:
    tests/test_feasibility.py    PASSED
    tests/test_engine_smoke.py   SKIPPED
    [████████████░░░░░░░░░░░░░░] 50%  ✓ 238  ✗ 0  ⠼  test 238/477  elapsed 1m 30s

  With -v — per-test ✓/✗/⊘ rows:
    ✓ tests/test_feasibility.py::test_drops_outside_scc
    ⊘ tests/test_engine_smoke.py::test_sumo_real_binary  (SUMO binaries not on PATH)
    ✗ tests/test_x.py::test_y  (AssertionError: expected 5 got 6)

  With --cov — a coverage table is appended below the Summary block:
    Name                              Stmts   Miss  Cover   Missing
    adapters/common/feasibility.py       94      8    91%   42-49
    ...
    TOTAL                              2847    677    76%

  With -p no:sticky_progress — plain pytest output (dots, file headers,
  short test summary info, etc.). Useful when piping to a log file or
  diagnosing the plugin itself.

COVERAGE:
  python -m pytest --cov                        # Terminal summary
  python -m pytest --cov --cov-report=html      # HTML report in htmlcov/
  python -m pytest --cov --cov-fail-under=70    # Enforce 70 % floor

  Current line coverage: ~76 % (branch coverage enabled). Source set and
  omit list configured in pyproject.toml [tool.coverage]. Dev tools install
  via: pip install -r requirements-dev.txt

MUTATION TESTING:
  mutmut run                                    # Run against the cross-engine
  mutmut results                                # fairness modules only.
  Scope defined in pyproject.toml [tool.mutmut]; documented in
  doc/MUTATION_BASELINE.md.

SHARED FIXTURES (tests/conftest.py):
  bundled_scenario           Canonical chicago_1k_car scenario path
  all_bundled_scenarios      Every complete scenarios/ entry
  small_bundled_scenarios    Scenarios under the arm64 netconvert threshold
  file_sha256, directory_sha256           Deterministic hashing helpers
  is_arm64_netconvert_crash               Platform skip detector
  warn_skipped                            Emits a single UserWarning summary

COMMON TEST FLAGS:
  -v, --verbose            Show individual test names
  -vv                      Verbose + full assertion diffs
  --tb=short / --tb=long   Compact / full tracebacks
  -x, --exitfirst          Stop on first failure
  -s                       Don't swallow print() output
  -k EXPR                  Run tests matching expression
  --durations=10           Show 10 slowest tests
  -n auto                  Parallel execution (needs pytest-xdist)
  --collect-only           List tests without running them

SEE ALSO:
  TESTING.md                Full per-file reference + markers + coverage
  CONTRIBUTING.md           Test-writing conventions + determinism rules
  doc/MUTATION_BASELINE.md  Mutation testing scope and baseline
"""

HELP_ANALYZER = """
====================================================================
  SCENARIO ANALYZER (tools/analyze_scenarios.py)
====================================================================

Tabular end-to-end analysis of one or more canonical scenario
bundles. Each section is one side-by-side table with metrics as rows
and scenarios as columns. Auto-paginates per section when the
terminal isn't wide enough.

USAGE:
  python tools/analyze_scenarios.py                  # all bundles
  python tools/analyze_scenarios.py chicago_1k_car   # single bundle
  python tools/analyze_scenarios.py chicago_1k_car nyc_10k_car
  python tools/analyze_scenarios.py --section network
  python tools/analyze_scenarios.py --section demand --section road_classes
  python tools/analyze_scenarios.py --no-color       # plain ASCII

SECTIONS (selectable via --section, repeatable):
  configuration  city, trips, time window, radius, seed, strategy,
                 generation time, OSM source
  network        nodes, links, has_signal, turn restrictions,
                 speed/lane stats (range + mean)
  road_classes   per-OSM-highway-type link counts (top 12 + (other))
  signals        junction count, cycle length, phase pattern, density
  demand         totals (mode mix, schedule vs gravity, departure
                 window, schedule pool size) + Trip-purpose
                 breakdown subsection (HBW_AM/PM, HBSchool_AM/PM,
                 HBW_*_chained) + Peak split & chain summary subsection
  artefacts      per-canonical-file size + total bundle size
  toolchain      Python / osmnx / numpy / lxml / pandas / etc.
                 versions recorded at generation time

PAGINATION (automatic):
  shutil.get_terminal_size() drives per-section pagination. Sections
  with compact integer columns fit more scenarios per page than
  sections with wide-string rows (e.g. CONFIGURATION with the OSM
  filename row). Page titles get a `(scenarios X-Y of N)` suffix
  whenever a section spans more than one page.

WHEN TO USE:
  Before benchmarking, to verify generated bundles look correct.
  When comparing realism features (chain rates, signal density,
  turn restriction count) across tiers. As a pre-run complement to
  audit_fairness Q5 and analyze_benchmark's demand-composition table
  (those run *after* simulation; analyze_scenarios runs on the
  canonical bundle alone, no engine output needed).

SEE ALSO:
  python help.py evaluation         audit_fairness + analyze_benchmark
  doc/RESULTS_GUIDE.md sec 4.4      full reference + usage examples
"""

HELP_TROUBLESHOOTING = """
====================================================================
  TROUBLESHOOTING
====================================================================

1. "command not found: python" / "No module named 'pytest'"
   -> You forgot to activate the venv. Run: source .venv/bin/activate
      (On Windows: .venv\\Scripts\\activate)

2. "ModuleNotFoundError: No module named 'pipeline'"
   -> Run from project root: cd SimForge (not from scripts/, tools/, or tests/).

3. "No residential buildings mapped to network nodes"
   -> Increase --radius to capture more buildings.

4. "Requested N trips but only M raw census commuters available"
   -> Use --allow-oversample, --synthetic, or increase --radius

5. "No scenarios found"
   -> Generate first: python generate.py --city chicago --trips 1000

6. "SUMO not found" / "netconvert: command not found"
   -> SUMO is bundled in requirements.lock as `eclipse-sumo`. Install via:
        source .venv/bin/activate
        uv pip install -r requirements.lock
      That puts `sumo`, `netconvert`, `sumo-gui` in `.venv/bin/`. Confirm:
        which sumo netconvert
        sumo --version

7. "MATSim JAR not found"
   -> Download to lib/matsim-15.0/, needs Java 17+
      setup_simforge.py does this automatically.

8. "netconvert segfaults on arm64 with networks > ~3000 nodes"
   -> SUMO platform bug, not SimForge. Adapter sweeps auto-skip
      affected scenarios on arm64 with a summary UserWarning.
      The bundled 1K scenario is safely below the threshold.
      Run the larger tiers on Linux / HPC to sidestep the crash.

9. "OSM download timeout / ConnectionError to Overpass"
   -> Wait and retry. Large radii may timeout. Pre-warm the cache:
        python -m pipeline.network.warmup
      Fresh fetches are logged with "first-time fetch" WARNING.

9b. "FileNotFoundError: OSM PBF required for city '<name>'"
   -> generate.py needs a hash-pinned state PBF in osm_data/. Fetch it:
        python tools/download_osm.py
      The committed scenarios/chicago_1k_car/ bundle runs without this step.

10. "Pytest passes nothing visible — I see only dots"
   -> Add -v for one line per test:
        python -m pytest tests/test_feasibility.py -v
      Add -vv for full assertion diffs on failures.

11. "Tests fail with 'binary not found' errors"
   -> test_engine_smoke.py needs real SUMO / MATSim / Java on PATH.
      Tests skip individually when binaries are missing, so the suite
      stays green. Filter the SUMO-dependent ones with:
          python -m pytest -m "not requires_sumo"

12. "Coverage numbers look low (~40 %)"
   -> setup_simforge.py installs the dev deps; if you used a manual venv,
      install them yourself:
        pip install -r requirements-dev.txt
      and make sure you're running from the project root.

13. "sumo: Error: No connection between edge 'lX' and edge 'lY'"
   -> Drive sumo with --ignore-route-errors. SimForge pre-computes routes by
      BFS on the canonical node graph; on real-world networks some of those
      edge-level transitions lack a valid lane connection. The benchmark
      harness, run.py, and `python -m adapters.sumo.cli --run` all pass the
      flag automatically. Example direct invocation:
        sumo -c toy.sumocfg --ignore-route-errors

GETTING HELP:
  python help.py                    Full help overview
  python help.py <topic>            Topic-specific help
  python help.py setup              Install + bootstrap
  python generate.py --help         Generator CLI help
  python run.py --help              Run CLI help
  python -m pytest tests/ -v        Run test suite (verbose)

DIAGNOSTIC INFO TO INCLUDE WHEN REPORTING BUGS:
  python -c "import sys, platform; print(sys.version, platform.platform())"
  sumo --version
  java -version
  git rev-parse HEAD
"""

HELP_SETUP = """
====================================================================
  SETUP & INSTALLATION
====================================================================

ONE-COMMAND BOOTSTRAP:
  python setup_simforge.py

  This creates .venv/, installs runtime dependencies (requirements.txt)
  AND developer tooling (requirements-dev.txt: pytest-cov, pytest-xdist,
  mutmut), and downloads the MATSim 15.0 JAR to lib/matsim-15.0/.
  Re-running is idempotent.

ACTIVATE THE VENV (REQUIRED IN EVERY NEW SHELL):
  source .venv/bin/activate                     # macOS / Linux
  .venv\\Scripts\\activate                       # Windows (CMD)
  .venv\\Scripts\\Activate.ps1                   # Windows (PowerShell)

  After activation, 'python' and 'pytest' resolve to the venv's copy.
  If you see 'command not found: python', the venv is not active.

EXTERNAL DEPENDENCIES:
  SUMO 1.26+        Bundled in requirements.lock (eclipse-sumo wheel — same
                    binary on macOS arm64 and Linux x86_64). Installed by
                    `uv pip install -r requirements.lock`. Verify: sumo --version
  Java 17+          macOS:  brew install openjdk@17
                    Linux:  apt-get install openjdk-17-jdk  (or `module load openjdk/21.0.3_9` on Pitzer)
                    Verify: java -version

DEV DEPENDENCIES (coverage + mutation testing + parallel pytest):
  Installing requirements.lock via `uv pip install -r requirements.lock`
  bundles pytest, pytest-cov, and other dev tooling. The legacy
  `pip install -r requirements-dev.txt` path still works for ad-hoc dev installs.

VERIFY THE INSTALL (full sanity check):
  source .venv/bin/activate
  python -m pytest                              # Full test suite (~3-4 min on arm64)
  python -m pipeline.validation.validate_bundle scenarios/chicago_1k_car
  python -m execution.run_benchmark runspecs/benchmark_small.yaml --dry-run
  python -m execution.run_benchmark runspecs/benchmark_small.yaml      # ~40-100 min on M-series Mac

MANUAL INSTALL (if setup_simforge.py fails — see SETUP.md):
  python3.10+ -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
  pip install -r requirements-dev.txt

  # MATSim JAR (needed only for MATSim runs):
  mkdir -p lib/matsim-15.0
  # Download matsim-15.0.jar from the official MATSim GitHub release
  # and place it in lib/matsim-15.0/

OSM PBF SNAPSHOTS (required only if you regenerate scenarios):
  python tools/download_osm.py                     # fetch all manifest entries
  python tools/download_osm.py illinois            # fetch one state (IL/NY/CA)
  python tools/download_osm.py --force             # re-download + hash-verify

  Skipped if files are already present and hashes match. The committed
  scenarios/chicago_1k_car/ bundle works without running this.

OPERATOR UTILITIES (tools/):
  tools/download_osm.py      Hash-pinned Geofabrik PBF fetcher
  tools/clean.sh             Wipe __pycache__ / *.pyc / .pytest_cache
  tools/clean.sh --all       Also drops cache/ (Overpass HTTP cache)
  tools/inspect_network.py <scenario_dir>    Length distribution + degenerate-edge report
  tools/env_report.py                        Toolchain + dep + binary versions, for cross-machine parity check
  tools/analyze_scenarios.py [name…]         Tabular end-to-end analysis of one or
                                             more scenario bundles. Seven sections,
                                             scenarios as columns:
                                               configuration / network / road_classes /
                                               signals / demand (with subsections for
                                               trip-purpose breakdown + peak split) /
                                               artefacts (file sizes) / toolchain
                                             Default: every bundle in scenarios/.
                                             Auto-paginates when too many scenarios
                                             for the terminal width — each section
                                             splits into pages of N scenarios.
                                             Flags:
                                               --section <name>     pick subset
                                                                    (repeatable)
                                               --no-color           plain ASCII

FIRST RUN (after install):
  python generate.py --city chicago --trips 1000        # generate bundle
  python run.py --scenario chicago_1k_car --engine sumo --mode meso

SEE ALSO:
  SETUP.md          Full install guide + per-OS details
  CONTRIBUTING.md   Dev workflow + test conventions
  python help.py troubleshooting     Common install errors
"""


# =============================================================================
# TOPIC REGISTRY
# =============================================================================

TOPICS = {
    "overview": HELP_OVERVIEW,
    "setup": HELP_SETUP,
    "install": HELP_SETUP,
    "bootstrap": HELP_SETUP,
    "generate": HELP_GENERATE,
    "run": HELP_RUN,
    "scripts": HELP_SCRIPTS,
    "presets": HELP_SCRIPTS,
    "cities": None,  # dynamic -- built at runtime
    "modes": HELP_MODES,
    "adapters": HELP_ADAPTERS,
    "engines": HELP_ADAPTERS,
    "scenarios": HELP_GENERATE,
    "metrics": HELP_METRICS,
    "evaluation": HELP_EVALUATION,
    "analysis": HELP_EVALUATION,
    "plots": HELP_EVALUATION,
    "schema": HELP_SCHEMA,
    "benchmark": HELP_BENCHMARK,
    "tests": HELP_TESTS,
    "testing": HELP_TESTS,
    "analyzer": HELP_ANALYZER,
    "analyze": HELP_ANALYZER,
    "troubleshooting": HELP_TROUBLESHOOTING,
}


# Menu metadata: ordered groups of (key, short_desc).
# `key` must resolve via TOPICS. Each group becomes a labeled section in
# the interactive menu; topics are numbered globally so users can jump
# by number or name.
TOPIC_GROUPS = [
    ("Getting started", [
        ("overview", "Top-level project overview"),
        ("setup", "Install + bootstrap"),
        ("cities", "Live census stats per supported city"),
        ("scripts", "Built-in preset generation scripts"),
    ]),
    ("Core workflows", [
        ("generate", "Bundle generator (generate.py)"),
        ("run", "Simulator runner (run.py)"),
        ("benchmark", "Benchmark harness (run_benchmark)"),
        ("tests", "Test suite reference"),
    ]),
    ("Reference", [
        ("modes", "Travel-mode taxonomy + JWTRNS mapping"),
        ("adapters", "SUMO / MATSim / DTALite adapter notes"),
        ("schema", "Canonical bundle schema (5 files)"),
    ]),
    ("Analysis & tools", [
        ("metrics", "Evaluation metric definitions"),
        ("evaluation", "audit_fairness + analyze_benchmark + plots"),
        ("analyzer", "tools/analyze_scenarios.py — bundle analyzer"),
    ]),
    ("Troubleshooting", [
        ("troubleshooting", "Common issues + fixes"),
    ]),
]


# =============================================================================
# INTERACTIVE MENU
# =============================================================================


def _resolve_content(topic: str) -> str:
    """Topic key → printable content. Handles the dynamic `cities` topic."""
    if topic == "cities":
        return _build_cities_section()
    return TOPICS.get(topic, "")


def _is_tty() -> bool:
    """True only when both stdin AND stdout are connected to a terminal."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _colors_enabled() -> bool:
    """ANSI colours on iff TTY-attached AND NO_COLOR env var unset.

    See https://no-color.org for the convention. Honoring NO_COLOR keeps
    the menu readable in CI logs, dumb terminals, and `script(1)`-style
    capture sessions.
    """
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


# ANSI escape codes — emitted only when `_colors_enabled()` is True at
# render time (checked inside `_c()` and `_input_prompt()`).
_C_RESET = "\033[0m"
_C_BOLD = "\033[1m"
_C_DIM = "\033[2m"
_C_CYAN = "\033[36m"
_C_GREEN = "\033[32m"
_C_YELLOW = "\033[33m"
_C_RED = "\033[31m"


def _c(text: str, code: str) -> str:
    if not _colors_enabled():
        return text
    return f"{code}{text}{_C_RESET}"


def _input_prompt(text: str, code: str) -> str:
    """Build an `input()` prompt with ANSI codes wrapped in `\\001…\\002`.

    Without these readline-style non-printing markers, GNU readline
    miscounts the visible column position (because it sees the raw
    ANSI bytes as printable characters), which corrupts cursor placement
    when the user backspaces or scrolls history.

    Returns plain text when colours are disabled (NO_COLOR or no TTY).
    """
    if not code or not _colors_enabled():
        return text
    return f"\001{code}\002{text}\001{_C_RESET}\002"


def _clear_screen() -> None:
    # ANSI clear + cursor home; works on every modern terminal.
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def _build_index() -> tuple[dict[str, str], list[tuple[str, list[tuple[int, str, str]]]]]:
    """Build the (resolver, layout) pair the menu loop needs.

    Resolver maps user input (number string or topic name/alias) → topic key.
    Layout is a list of (group_label, [(num, key, short_desc), ...]) for
    rendering the menu visually.
    """
    resolver: dict[str, str] = {}
    layout: list[tuple[str, list[tuple[int, str, str]]]] = []
    n = 1
    for group, items in TOPIC_GROUPS:
        rows: list[tuple[int, str, str]] = []
        for key, desc in items:
            resolver[str(n)] = key
            resolver[key.lower()] = key
            rows.append((n, key, desc))
            n += 1
        layout.append((group, rows))
    # Aliases not in the menu (e.g. "install" → setup) still resolve.
    for alias, content in TOPICS.items():
        if alias.lower() not in resolver:
            # Find which canonical key shares this content so the alias
            # routes to the same content path.
            for canonical in resolver.values():
                if TOPICS.get(canonical) is content:
                    resolver[alias.lower()] = canonical
                    break
    return resolver, layout


def _render_menu(layout) -> str:
    """Pretty-print the categorised menu with numbered topics."""
    lines: list[str] = []
    bar = "═" * 68
    lines.append(_c(bar, _C_CYAN))
    lines.append(_c("                    SimForge — Interactive Help",
                    _C_BOLD + _C_CYAN))
    lines.append(_c(bar, _C_CYAN))
    lines.append("")
    # Compute label width for alignment.
    all_keys = [k for _, items in layout for _, k, _ in items]
    key_w = max(len(k) for k in all_keys)
    for group, items in layout:
        lines.append("  " + _c(group, _C_BOLD + _C_YELLOW))
        for n, key, desc in items:
            num_str = _c(f"{n:>3}", _C_GREEN)
            key_str = _c(key.ljust(key_w), _C_BOLD)
            lines.append(f"  {num_str}  {key_str}  {_c(desc, _C_DIM)}")
        lines.append("")
    rule = "─" * 68
    lines.append(_c(rule, _C_DIM))
    lines.append(_c("  Enter:", _C_BOLD)
                 + _c("  number / topic name", _C_DIM) + " → show topic")
    lines.append(_c("        ", _C_BOLD)
                 + _c("  /<word>", _C_DIM) + "             → search topics for keyword")
    lines.append(_c("        ", _C_BOLD)
                 + _c("  q   (or empty)", _C_DIM) + "      → quit")
    lines.append(_c(rule, _C_DIM))
    return "\n".join(lines)


def _search(query: str, resolver: dict[str, str]) -> None:
    """Full-text search across all topic content, ranked by hit count."""
    query_lower = query.lower()
    if not query_lower:
        print(_c("  (empty search query)", _C_RED))
        input("  Press Enter to continue...")
        return
    seen: set[str] = set()
    matches: list[tuple[str, int]] = []
    for key in resolver.values():
        if key in seen:
            continue
        seen.add(key)
        content = _resolve_content(key)
        n = content.lower().count(query_lower)
        if n:
            matches.append((key, n))
    matches.sort(key=lambda x: -x[1])

    print()
    if not matches:
        print(_c(f"  No matches for '/{query}'.", _C_RED))
    else:
        n_topics = len(matches)
        if n_topics == 1:
            header = f"  1 topic matches '/{query}':"
        else:
            header = f"  {n_topics} topics match '/{query}':"
        print(_c(header, _C_BOLD))
        # Pad the plain key first, then apply colour — otherwise the f-string
        # `:<28` width counts the ANSI bytes too and the columns wobble.
        key_w = max(len(k) for k, _ in matches) + 4
        for key, n in matches:
            hit_str = f"{n} hit" if n == 1 else f"{n} hits"
            print(f"    {_c(key.ljust(key_w), _C_BOLD)}  {_c(hit_str, _C_DIM)}")
    print()
    try:
        input(_input_prompt("  Press Enter to continue...", _C_DIM))
    except (EOFError, KeyboardInterrupt):
        print()


def _page(content: str) -> None:
    """Display content via `less -FRX` when available, plain print otherwise.

    `-F` auto-exits when content fits on one screen (no q-press needed for
    short topics). `-R` renders ANSI escapes (we don't currently embed any
    in topic content, but harmless if a future topic does). `-X` skips
    the alt-screen sequence so the topic stays in scrollback for later
    reference. Falls through to plain print when `less` isn't on PATH
    (rare; mostly Windows without WSL).
    """
    import shutil
    import subprocess
    less = shutil.which("less")
    if less is None:
        # Last-resort fallback: defer to stdlib pydoc, which itself
        # falls back to plain print when no pager is available.
        import pydoc
        pydoc.pager(content)
        return
    try:
        subprocess.run([less, "-FRX"], input=content, text=True, check=False)
    except (KeyboardInterrupt, BrokenPipeError):
        pass


def _resolve_choice(choice: str, resolver: dict[str, str]) -> tuple[str | None, list[str]]:
    """Map a user input to a topic key.

    Returns ``(topic_key, suggestions)``. When the input matches exactly,
    ``topic_key`` is set and ``suggestions`` is empty. When it doesn't
    match exactly but uniquely prefixes one topic name, that topic is
    chosen. When multiple topics share the prefix, ``topic_key`` is None
    and ``suggestions`` lists the candidates.
    """
    key = choice.lower().strip()
    if not key:
        return None, []
    # Exact match wins immediately (numbers + full names + aliases).
    if key in resolver:
        return resolver[key], []
    # Try unique prefix match against canonical names only.
    canonical_keys = sorted({v for v in resolver.values()})
    prefix_hits = [k for k in canonical_keys if k.startswith(key)]
    if len(prefix_hits) == 1:
        return prefix_hits[0], []
    return None, prefix_hits  # 0 or 2+ hits → caller suggests


def _flat_menu_items() -> list[dict]:
    """Flatten TOPIC_GROUPS into a list of menu rows for the curses TUI.

    Each row is a dict with `type ∈ {'group', 'topic'}`. Group rows are
    non-selectable headers; topic rows carry the canonical key + the
    short description used in the menu display.
    """
    items: list[dict] = []
    for group, topics in TOPIC_GROUPS:
        items.append({"type": "group", "label": group})
        for key, desc in topics:
            items.append({"type": "topic", "key": key,
                          "label": key, "desc": desc})
    return items


def _next_selectable(items: list[dict], current: int) -> int:
    n = len(items)
    for i in range(1, n + 1):
        idx = (current + i) % n
        if items[idx]["type"] == "topic":
            return idx
    return current


def _prev_selectable(items: list[dict], current: int) -> int:
    n = len(items)
    for i in range(1, n + 1):
        idx = (current - i) % n
        if items[idx]["type"] == "topic":
            return idx
    return current


def _safe_addstr(stdscr, y: int, x: int, text: str, attr: int = 0) -> None:
    """Add a string at (y, x) without raising on edge-of-screen writes."""
    import curses
    h, w = stdscr.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w:
        return
    text = text[:max(0, w - x - 1)]
    try:
        stdscr.addstr(y, x, text, attr)
    except curses.error:
        # Last-column-on-last-row writes raise on some terminals — harmless.
        pass


def _curses_draw_menu(stdscr, items: list[dict], selected: int,
                      has_colors: bool) -> None:
    import curses
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    title = "  SimForge — Interactive Help"
    title_attr = (curses.color_pair(1) | curses.A_BOLD) if has_colors \
                 else curses.A_REVERSE
    _safe_addstr(stdscr, 0, 0, title.ljust(w - 1), title_attr)

    row = 2
    first_group = True
    for i, item in enumerate(items):
        if row >= h - 2:
            break
        if item["type"] == "group":
            # Blank line above each group except the first one — gives
            # the menu visible breathing room between categories.
            if not first_group:
                row += 1
                if row >= h - 2:
                    break
            first_group = False
            attr = (curses.color_pair(2) | curses.A_BOLD) if has_colors \
                   else curses.A_BOLD
            _safe_addstr(stdscr, row, 2, item["label"], attr)
            row += 1
            continue
        label_w = 18
        line = f"  {item['label']:<{label_w}}  {item['desc']}"
        if i == selected:
            cursor = "▶ "
            attr = (curses.color_pair(3) | curses.A_BOLD) if has_colors \
                   else curses.A_REVERSE
        else:
            cursor = "  "
            attr = curses.color_pair(4) if has_colors else 0
        _safe_addstr(stdscr, row, 2, cursor, attr)
        _safe_addstr(stdscr, row, 4, line[:max(0, w - 5)], attr)
        row += 1

    footer = "  ↑/↓: navigate    Enter: open topic    Esc / q: quit"
    footer_attr = (curses.color_pair(1) | curses.A_BOLD) if has_colors \
                  else curses.A_REVERSE
    _safe_addstr(stdscr, h - 1, 0, footer.ljust(w - 1), footer_attr)
    stdscr.refresh()


def _topic_attr(kind: str, has_colors: bool) -> int:
    """Curses attribute for a content line classified by `_classify_line`.

    Falls back to plain text when colour support isn't available
    (NO_COLOR-style environments, dumb terminals).
    """
    import curses
    if not has_colors:
        if kind in ("title", "header"):
            return curses.A_BOLD
        if kind == "rule":
            return curses.A_DIM
        return 0
    if kind == "rule":
        return curses.color_pair(1) | curses.A_DIM
    if kind == "title":
        return curses.color_pair(1) | curses.A_BOLD
    if kind == "header":
        return curses.color_pair(2) | curses.A_BOLD
    if kind == "command":
        return curses.color_pair(3)
    return 0


def _classify_line(line: str) -> str:
    """Best-effort syntax-highlight kind for a help-content line.

    Used by the topic viewer to choose a curses attribute. Pattern
    matching is intentionally conservative — we'd rather under-highlight
    a line than miscolour real text. Categories:

      ``rule``    — line of ``=`` or ``-`` characters (decorative
                    horizontal bar)
      ``title``   — short, mostly uppercase line *between* rules (e.g.
                    "DATA GENERATION (generate.py)")
      ``header``  — section heading like ``QUICK START:`` or
                    ``REQUIRED FLAGS:`` (uppercase + trailing colon)
      ``command`` — example invocation (starts with ``python``, ``$``,
                    ``sumo``, ``java``, ``pip``, ``uv``, ``brew``,
                    or ``git`` after stripping leading whitespace)
      ``normal``  — everything else
    """
    stripped = line.strip()
    if not stripped:
        return "blank"
    # Decorative rules first — they're the easiest to spot.
    if len(stripped) >= 4 and all(c == "=" for c in stripped):
        return "rule"
    if len(stripped) >= 4 and all(c == "-" for c in stripped):
        return "rule"
    # Section header like "QUICK START:" — uppercase letters with optional
    # spaces / numbers, ending in a colon.
    if stripped.endswith(":") and len(stripped) <= 60:
        body = stripped[:-1].replace(" ", "").replace("/", "").replace("-", "")
        if body and body.isupper() and any(c.isalpha() for c in body):
            return "header"
    # Command example — common shell prefixes, after lstripping.
    cmd_prefixes = ("python ", "python3 ", "$ ", "$\t", "sumo ", "java ",
                    "pip ", "uv ", "brew ", "git ", "pytest ", "make ")
    if stripped.startswith(cmd_prefixes):
        return "command"
    # Title = uppercase-ish line that's centred-ish (i.e. has indent).
    # We only flag it when there's some lead indent (≥2 spaces) to avoid
    # false positives on uppercase prose.
    if line.startswith("  ") and len(stripped) <= 60:
        letters = [c for c in stripped if c.isalpha()]
        if letters and sum(1 for c in letters if c.isupper()) / len(letters) >= 0.7:
            return "title"
    return "normal"


def _curses_show_topic(stdscr, title: str, content: str,
                       has_colors: bool) -> None:
    """Scrollable topic view. Esc returns the caller (menu) — and
    because we erase the screen on every menu redraw, the topic content
    leaves no residue behind.

    Content gets a subtle 2-column left margin and best-effort syntax
    highlighting so the page reads as a help document rather than an
    error log: rule lines dim, ALL-CAPS titles bold cyan, ``HEADER:``
    bold yellow, command examples green.
    """
    import curses
    lines = content.split("\n")
    # Drop any leading/trailing blank lines so the page starts at real
    # content (the help-string convention puts a leading "\n" inside the
    # triple-quoted block which then renders as wasted screen real-estate).
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    n_lines = len(lines)
    offset = 0

    # Pre-classify every line once; cheap and avoids re-running pattern
    # checks per scroll-redraw.
    kinds = [_classify_line(line) for line in lines]

    LEFT_PAD = 2     # visible margin from screen edge
    TOP_PAD = 1      # blank row between title bar and content
    BOTTOM_PAD = 1   # matching blank row above the footer (symmetry)

    while True:
        h, w = stdscr.getmaxyx()
        # Total non-content rows = title (1) + top pad + bottom pad + footer (1)
        body_h = max(1, h - 1 - TOP_PAD - BOTTOM_PAD - 1)
        max_offset = max(0, n_lines - body_h)
        offset = max(0, min(offset, max_offset))

        stdscr.erase()
        header = f"  Topic: {title}"
        title_attr = (curses.color_pair(1) | curses.A_BOLD) if has_colors \
                     else curses.A_REVERSE
        _safe_addstr(stdscr, 0, 0, header.ljust(w - 1), title_attr)

        for i in range(body_h):
            idx = offset + i
            if idx >= n_lines:
                break
            line = lines[idx]
            kind = kinds[idx]
            attr = _topic_attr(kind, has_colors)
            row_y = 1 + TOP_PAD + i
            _safe_addstr(stdscr, row_y, LEFT_PAD,
                         line[:max(0, w - LEFT_PAD - 1)], attr)

        if max_offset == 0:
            pos = "all"
        else:
            pct = int(100 * offset / max_offset)
            pos = (f"{pct:3d}%   line {offset + 1}–"
                   f"{min(offset + body_h, n_lines)}/{n_lines}")
        # PgUp/PgDn and Home/End still WORK (helpful on long topics) but
        # we keep them off the footer because compact Mac keyboards lack
        # those keys natively (need Fn-modifier) and most users won't
        # discover them. The two essentials live here.
        footer = f"  ↑/↓: scroll    Esc: back    [{pos}]"
        footer_attr = (curses.color_pair(1) | curses.A_BOLD) if has_colors \
                      else curses.A_REVERSE
        _safe_addstr(stdscr, h - 1, 0, footer.ljust(w - 1), footer_attr)
        stdscr.refresh()

        try:
            ch = stdscr.getch()
        except KeyboardInterrupt:
            return
        if ch == curses.KEY_UP:
            offset -= 1
        elif ch == curses.KEY_DOWN:
            offset += 1
        elif ch == curses.KEY_PPAGE:
            offset -= body_h
        elif ch == curses.KEY_NPAGE:
            offset += body_h
        elif ch == curses.KEY_HOME:
            offset = 0
        elif ch == curses.KEY_END:
            offset = max_offset
        elif ch == 27:  # Esc → back to menu
            return
        elif ch == curses.KEY_RESIZE:
            continue


def _curses_main(stdscr) -> int:
    import curses
    curses.curs_set(0)
    stdscr.keypad(True)

    has_colors = False
    if curses.has_colors():
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)     # title bars
            curses.init_pair(2, curses.COLOR_YELLOW, -1)   # group headings
            curses.init_pair(3, curses.COLOR_GREEN, -1)    # current row
            curses.init_pair(4, curses.COLOR_WHITE, -1)    # default text
            has_colors = True
        except curses.error:
            has_colors = False

    items = _flat_menu_items()
    selected = _next_selectable(items, -1)  # first topic, skip leading group

    while True:
        _curses_draw_menu(stdscr, items, selected, has_colors)
        try:
            ch = stdscr.getch()
        except KeyboardInterrupt:
            return 0
        if ch == curses.KEY_UP:
            selected = _prev_selectable(items, selected)
        elif ch == curses.KEY_DOWN:
            selected = _next_selectable(items, selected)
        elif ch in (curses.KEY_ENTER, 10, 13):
            item = items[selected]
            content = _resolve_content(item["key"])
            _curses_show_topic(stdscr, item["label"], content, has_colors)
            # On return, loop redraws the menu — Esc-to-back leaves no
            # topic residue because curses owns the entire screen and
            # the next _curses_draw_menu() call calls stdscr.erase().
        elif ch in (27, ord("q"), ord("Q")):
            return 0
        elif ch == curses.KEY_RESIZE:
            continue


def _interactive_legacy_loop() -> int:
    """Numbered-input fallback for environments where curses can't init.

    Same as the previous interactive menu (number → topic, /<word>
    search, q to quit). Used only when `import curses` fails or the
    terminal can't host a curses session.
    """
    try:
        import readline  # noqa: F401
    except ImportError:
        pass

    resolver, layout = _build_index()
    while True:
        _clear_screen()
        print(_render_menu(layout))
        try:
            choice = input(_input_prompt("\n> ", _C_BOLD + _C_GREEN)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not choice or choice.lower() in ("q", "quit", "exit"):
            return 0
        if choice.startswith("/"):
            _search(choice[1:].strip(), resolver)
            continue
        topic, suggestions = _resolve_choice(choice, resolver)
        if topic is None:
            if suggestions:
                print(_c(f"  '{choice}' matches multiple topics:", _C_YELLOW))
                print("    " + ", ".join(suggestions))
            else:
                print(_c(f"  Unknown topic: '{choice}'", _C_RED))
                print(_c("  Try a number 1–15, a topic name, /<keyword>, or q.",
                         _C_DIM))
            try:
                input(_input_prompt("  Press Enter to continue...", _C_DIM))
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            continue
        content = _resolve_content(topic)
        _page(content)


def _interactive_loop() -> int:
    """Main entry: try the curses TUI first, fall back to the legacy
    numbered menu when curses can't run."""
    os.environ.setdefault("ESCDELAY", "25")
    try:
        import curses
    except ImportError:
        return _interactive_legacy_loop()
    try:
        return curses.wrapper(_curses_main)
    except curses.error:
        return _interactive_legacy_loop()


# =============================================================================
# MAIN ENTRY
# =============================================================================


def main() -> int:
    """Help system entry point.

    Behavior matrix (preserves paste-safe text mode):
      no args  + TTY      → interactive menu
      no args  + non-TTY  → print HELP_OVERVIEW (paste-safe)
      <topic>             → print topic to stdout (paste-safe)
      -i / --interactive  → force interactive (even if non-TTY, for testing)
      --no-interactive    → force text overview (escape hatch)

    The `<topic>` path is back-compat: anything that worked on a previous
    SimForge release still produces the same paste-able plain text.
    """
    args = sys.argv[1:]

    # Explicit flag overrides.
    if "--no-interactive" in args:
        print(HELP_OVERVIEW)
        return 0
    force_interactive = ("-i" in args) or ("--interactive" in args)

    # Strip flags so positional arg handling sees only topic names.
    args = [a for a in args
            if a not in ("--no-interactive", "-i", "--interactive")]

    # No positional arg → interactive (when TTY) or overview (otherwise).
    if not args:
        if force_interactive or _is_tty():
            try:
                return _interactive_loop()
            except KeyboardInterrupt:
                print()
                return 0
        print(HELP_OVERVIEW)
        return 0

    # Positional topic — paste-safe text mode.
    topic = args[0].lower().strip("-")
    if topic in ("h", "help"):
        print(HELP_OVERVIEW)
        return 0
    if topic in TOPICS:
        print(_resolve_content(topic))
        return 0

    # Unknown topic.
    print(f"\nUnknown help topic: '{topic}'")
    print(f"\nAvailable topics: {', '.join(sorted(set(TOPICS.keys())))}")
    print("\nUsage: python help.py [topic]")
    print("       python help.py            # interactive menu (TTY)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
