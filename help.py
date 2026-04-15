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

import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent))

from pipeline.modelgen_scanner import scan_modelgen_dir

# =============================================================================
# DYNAMIC CITY DATA
# =============================================================================

CITY_META = {
    "chicago": {"name": "Chicago, IL", "lat": 41.878, "lon": -87.630, "radius": 4.0},
    "nyc":     {"name": "New York City, NY", "lat": 40.758, "lon": -73.986, "radius": 3.0},
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
        lines.append(f"    +-----------+------------+----------+")
        lines.append(f"    | Mode      |     Trips  | Approx.  |")
        lines.append(f"    +-----------+------------+----------+")
        lines.append(f"    | Car       | {car:>10,} | {_fmt(car):>8} |")
        lines.append(f"    | Transit   | {transit:>10,} | {_fmt(transit):>8} |")
        lines.append(f"    | Bike      | {bike:>10,} | {_fmt(bike):>8} |")
        lines.append(f"    | Walk      | {walk:>10,} | {_fmt(walk):>8} |")
        lines.append(f"    +-----------+------------+----------+")
        lines.append(f"    | TOTAL     | {total:>10,} | {_fmt(total):>8} |")
        lines.append(f"    +-----------+------------+----------+")
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
  1. Generate data:   python generate.py --city chicago --trips 5000
  2. Validate:        python -m pipeline.validation.validate_bundle scenarios/chicago_1k_car
  3. Run simulation:  python run.py --scenario chicago_1k_car --engine sumo --mode meso
  4. Run benchmark:   python -m execution.run_benchmark runspecs/benchmark_small.yaml

HELP TOPICS:
  python help.py generate           Data generation (generate.py)
  python help.py run                Simulation execution (run.py)
  python help.py scripts            Built-in preset scripts
  python help.py cities             Supported cities & census limits (LIVE DATA)
  python help.py modes              Travel modes reference
  python help.py adapters           Simulator adapters (SUMO, MATSim, QarSUMO)
  python help.py metrics            Evaluation metrics
  python help.py schema             Canonical schema format reference
  python help.py benchmark          Benchmark harness and runspecs
  python help.py troubleshooting    Common issues and fixes

PROJECT STRUCTURE:
  generate.py           Unified scenario generator (start here)
  run.py                Simulation runner CLI
  help.py               This help system
  scripts/              5 ready-to-use generation scripts
  scenarios/            Generated canonical data bundles
  adapters/             Simulator-specific converters
  pipeline/             Data generation pipeline modules
  evaluation/           Metrics computation & analysis
  execution/            Benchmark harness
  runspecs/             Benchmark configuration files (YAML)
  modelgen/             Census microdata files (ModelGen)
  tests/                Test suite (pytest)
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
  --start-time <seconds>   Start time, seconds from midnight (default: 0)
  --end-time <seconds>     End time, seconds from midnight (default: 3600)

NETWORK FLAGS:
  --radius, -r <km>        Network extraction radius (default: city-specific)

CONTROL FLAGS:
  --seed, -s <int>         Random seed (default: 42)
  --output, -o <path>      Custom output directory
  --id <string>            Custom scenario ID

DEMAND SOURCE FLAGS:
  --synthetic              Force synthetic gravity model
  --allow-oversample       Allow more trips than census commuters

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
  python generate.py --preset morning_rush
  python generate.py --preset small_commute --trips 100000 --city la

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
  --engine, -e <name>      Engine(s): sumo, matsim, qarsumo
  --mode, -m <name>        Mode(s): micro, meso
  --repeats, -r <n>        Repeats (default: 10)
  --seed <int>             Base random seed (default: 42)
  --timeout, -t <seconds>  Per-run timeout (default: 3600)
  --output, -o <path>      Output directory (default: runs/)
  --list, -l               List available options
  --validate-only, -v      Only validate, don't simulate

EXAMPLES:
  python run.py --engine sumo --mode meso
  python run.py --scenario chicago_1k_car --engine sumo --mode meso
  python run.py --validate-only

BENCHMARK HARNESS:
  python -m execution.run_benchmark runspecs/benchmark_small.yaml
  python -m execution.run_benchmark runspecs/benchmark_small.yaml --dry-run
"""

HELP_SCRIPTS = """
====================================================================
  BUILT-IN SCRIPTS (scripts/)
====================================================================

5 ready-to-use generation scripts, from small to big:

  python scripts/01_quick_test.py          Tiny quick test
  python scripts/02_small_commute.py       Small morning commute
  python scripts/03_medium_multimodal.py   Medium multi-modal city
  python scripts/04_large_full_day.py      Large full-day simulation
  python scripts/05_stress_test.py         Stress test at scale

  +----+------------------------+----------+---------+------------------+----------+
  | #  | Script                 | City     | Trips   | Modes            | Time     |
  +----+------------------------+----------+---------+------------------+----------+
  | 01 | quick_test             | Chicago  |   1,000 | car              | 07-08 AM |
  | 02 | small_commute          | NYC      |  10,000 | car              | 07-09 AM |
  | 03 | medium_multimodal      | LA       |  50,000 | car+transit+bike | 06-10 AM |
  | 04 | large_full_day         | Chicago  | 200,000 | car+transit      | 00-24:00 |
  | 05 | stress_test            | NYC      | 500,000 | car              | 06-10 AM |
  +----+------------------------+----------+---------+------------------+----------+

ALTERNATIVE -- via generate.py presets:
  python generate.py --preset quick_test
  python generate.py --preset small_commute
  python generate.py --preset medium_multimodal
  python generate.py --preset large_full_day
  python generate.py --preset stress_test

  Presets accept overrides: python generate.py --preset small_commute --city la
"""

HELP_MODES = """
====================================================================
  TRAVEL MODES REFERENCE
====================================================================

SUPPORTED MODES:
  car      Private automobile (drove alone, carpool, taxi, other)
  transit  Public transportation (bus, subway, rail, ferry)
  bike     Bicycle
  walk     Walking

CENSUS MODE MAPPING (JWTRNS codes):
  1=drove alone > car     2=carpooled > car       3=bus > transit
  4=streetcar > transit   5=subway > transit       6=railroad > transit
  7=ferry > transit       8=bicycle > bike         9=walked > walk
  10=WFH > excluded       11=taxi > car            12=other > car

SIMULATOR SUPPORT:
  SUMO:    car (micro/meso), transit (with PT module)
  QarSUMO: car only (GPU-accelerated)
  MATSim:  car, transit, bike, walk (full multi-modal)
"""

HELP_ADAPTERS = """
====================================================================
  SIMULATOR ADAPTERS
====================================================================

SUPPORTED SIMULATORS:
  SUMO     1.18+     Microscopic/mesoscopic vehicle simulation
  QarSUMO  Latest    GPU-accelerated SUMO (CUDA required)
  MATSim   15.0      Activity-based mesoscopic multi-agent sim

ADAPTER CLI:
  python -m adapters.sumo.cli <scenario_path> <output_dir>
  python -m adapters.qarsumo.cli <scenario_path> <output_dir> --run
  python -m adapters.matsim.cli <scenario_path> <output_dir> --run

PREREQUISITES:
  SUMO:    brew install sumo  (verify: sumo --version)
  MATSim:  Download JAR to lib/matsim-15.0/, requires Java 17+
  QarSUMO: Requires NVIDIA GPU with CUDA 11+
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

5 files per scenario bundle:

1. network.xml  -- Directed road graph (nodes + links from OSM)
2. demand.csv   -- Trip-level OD: trip_id,origin,dest,departure_s,mode
3. signals.xml  -- Fixed-time traffic signal phases
4. config.xml   -- Scenario metadata (time, seed, units)
5. manifest.xml -- File inventory

VALIDATION:
  python -m pipeline.validation.validate_bundle scenarios/<id>
"""

HELP_BENCHMARK = """
====================================================================
  BENCHMARK HARNESS & RUNSPECS
====================================================================

COMMANDS:
  python -m execution.run_benchmark <runspec.yaml>
  python -m execution.run_benchmark <runspec.yaml> --mesoscopic
  python -m execution.run_benchmark <runspec.yaml> --dry-run

BUILT-IN RUNSPECS:
  benchmark_small.yaml   1K–50K trips, 600s timeout (3 scenarios x 3 engines x 3 repeats = 27 runs)
  benchmark_large.yaml   200K–500K trips, 3600s timeout (2 scenarios x 3 engines x 3 repeats = 18 runs)
"""

HELP_TROUBLESHOOTING = """
====================================================================
  TROUBLESHOOTING
====================================================================

1. "No residential buildings mapped to network nodes"
   -> Increase --radius to capture more buildings.

2. "Requested N trips but only M raw census commuters available"
   -> --allow-oversample, --synthetic, or increase --radius

3. "No scenarios found"
   -> Generate first: python generate.py --city chicago --trips 5000

4. "SUMO not found"
   -> brew install sumo

5. "MATSim JAR not found"
   -> Download to lib/matsim-15.0/, needs Java 17+

6. "netconvert: command not found"
   -> export SUMO_HOME=$(brew --prefix sumo)/share/sumo

7. "ModuleNotFoundError: No module named 'pipeline'"
   -> Run from project root: cd SimForge

8. OSM download timeout
   -> Wait and retry. Large radii may timeout.

GETTING HELP:
  python help.py             Full help overview
  python help.py <topic>     Topic-specific help
  python generate.py --help  Generator CLI help
  python -m pytest tests/ -v Run test suite
"""

# =============================================================================
# TOPIC REGISTRY
# =============================================================================

TOPICS = {
    "overview": HELP_OVERVIEW,
    "generate": HELP_GENERATE,
    "run": HELP_RUN,
    "scripts": HELP_SCRIPTS,
    "presets": HELP_SCRIPTS,
    "cities": None,  # dynamic -- built at runtime
    "modes": HELP_MODES,
    "adapters": HELP_ADAPTERS,
    "metrics": HELP_METRICS,
    "schema": HELP_SCHEMA,
    "benchmark": HELP_BENCHMARK,
    "troubleshooting": HELP_TROUBLESHOOTING,
}


def main():
    if len(sys.argv) < 2:
        print(HELP_OVERVIEW)
        return

    topic = sys.argv[1].lower().strip("-")

    if topic in ("h", "help"):
        print(HELP_OVERVIEW)
        return

    if topic == "cities":
        print(_build_cities_section())
    elif topic in TOPICS:
        print(TOPICS[topic])
    else:
        print(f"\nUnknown help topic: '{topic}'")
        print(f"\nAvailable topics: {', '.join(TOPICS.keys())}")
        print("\nUsage: python help.py [topic]")


if __name__ == "__main__":
    main()
