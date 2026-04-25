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
  4. Run benchmark:   python -m execution.run_benchmark runspecs/stress_test.yaml

HELP TOPICS:
  python help.py setup              Install and bootstrap
  python help.py generate           Data generation (generate.py)
  python help.py run                Simulation execution (run.py)
  python help.py scripts            Built-in preset scripts
  python help.py cities             Supported cities & census limits (LIVE DATA)
  python help.py modes              Travel modes reference
  python help.py adapters           Simulator adapters (SUMO, MATSim, QarSUMO)
  python help.py metrics            Evaluation metrics
  python help.py evaluation         Analysis & plotting commands
  python help.py schema             Canonical schema format reference
  python help.py benchmark          Benchmark harness and runspecs
  python help.py tests              Test suite reference
  python help.py troubleshooting    Common issues and fixes

PROJECT STRUCTURE:
  generate.py           Unified scenario generator (start here)
  run.py                Simulation runner CLI
  help.py               This help system
  scripts/              5 ready-to-use generation scripts (01–05)
  tools/                Operator utilities (clean.sh, download_osm.py)
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
  python -m execution.run_benchmark runspecs/stress_test.yaml       # canonical 11-run matrix
  python -m execution.run_benchmark runspecs/benchmark_small.yaml
  python -m execution.run_benchmark runspecs/stress_test.yaml --dry-run
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
  SUMO     1.20+     Microscopic/mesoscopic vehicle simulation
  QarSUMO  Latest    GPU-accelerated SUMO (falls back to SUMO without CUDA)
  MATSim   15.0      Activity-based mesoscopic multi-agent sim

ADAPTER CLI:
  python -m adapters.sumo.cli    <scenario_path> <output_dir>          # convert only
  python -m adapters.sumo.cli    <scenario_path> <output_dir> --run --mesoscopic
  python -m adapters.qarsumo.cli <scenario_path> <output_dir> --run
  python -m adapters.matsim.cli  <scenario_path> <output_dir> --run

SUMO NOTES:
  * `--run` invokes `sumo` with `--ignore-route-errors`. That flag is required:
    SimForge pre-computes routes by BFS on the canonical node graph, which can
    disagree with SUMO's edge-level lane connectivity on real-world networks.
    If you drive `sumo` by hand, always pass `--ignore-route-errors`:
        sumo -c toy.sumocfg --ignore-route-errors
  * Add `--mesosim true` (or use our `--mesoscopic` flag) for the faster
    mesoscopic model; omit for the default microscopic simulation.

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

HELP_EVALUATION = """
====================================================================
  EVALUATION, ANALYSIS & PLOTTING
====================================================================

ANALYZE BENCHMARK:
  python -m evaluation.analyze_benchmark <results.json>
  python -m evaluation.analyze_benchmark <results.json> --latex --markdown

  Produces:
    Table 5.1 — Runtime comparison (engine x city x mode)
    Table 5.2 — Reproducibility analysis (R-scores + Adj TT column*)
    Coverage diagnostic — flags low-sample (n<3), asymmetric, silently-failed cells

  --latex       emit LaTeX tables (ready for thesis inclusion)
  --markdown    emit Markdown tables (for docs / GitHub)

  * Adj TT: intersection-corrected mean travel time, computed over the trip-ID
    set completed by ALL engines for a given (scenario, mode, seed).  Eliminates
    the sample bias from SUMO dropping ~5 trips that MATSim always completes.
    Populated automatically when run-artifact directories exist next to the JSON.

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
         runs/stress_test/benchmark_results_stress_test.json --latex --markdown
  python -m evaluation.compare_modes --from-benchmark \\
         runs/stress_test/benchmark_results_stress_test.json
  python -m evaluation.generate_plots \\
         runs/stress_test/benchmark_results_stress_test.json \\
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

BUILT-IN RUNSPECS:
  stress_test.yaml       Canonical 11-run matrix: chicago_1k_car x
                         {SUMO meso, SUMO micro, QarSUMO meso, MATSim meso},
                         3 repeats per stochastic cell (2 for MATSim).
                         ~27 s on Apple M4 Pro. All thesis Chapter 5 numbers
                         come from this runspec.
  benchmark_small.yaml   1K-50K trips, 600 s per-run timeout (laptop tier).
  benchmark_large.yaml   200K-500K trips, 3600 s per-run timeout (HPC tier).

REPRODUCE THE THESIS NUMBERS END-TO-END (about one minute):
  python -m execution.run_benchmark runspecs/stress_test.yaml
  python -m evaluation.analyze_benchmark \\
         runs/stress_test/benchmark_results_stress_test.json --latex --markdown
  python -m evaluation.generate_plots \\
         runs/stress_test/benchmark_results_stress_test.json --output doc/figures

OUTPUT SHAPE:
  runs/<runspec_name>/
    benchmark_results_<runspec_name>.json   # canonical result schema
    run_<i>/                                # per-run engine artefacts
      feasibility_report.json               # SCC filter audit trail
      tripinfo.xml / output_trips.csv.gz    # engine-native outputs
"""

HELP_TESTS = """
====================================================================
  TEST SUITE REFERENCE
====================================================================

SimForge ships 249 tests across 17 files. The fast tier (~7 s) is
what developers run locally; the full suite (~22 s on M-series) adds
adapter sweeps and real-binary smoke tests.

Pytest config lives in pyproject.toml [tool.pytest.ini_options] with
--strict-markers + --tb=short. Shared fixtures and platform-skip
helpers live in tests/conftest.py.

RUN COMMANDS:
  python -m pytest                              # Full suite (~22 s)
  python -m pytest -m "not slow"                # Fast tier (~12 s)
  python -m pytest -v                           # Verbose — named lines per test
  python -m pytest -v -x                        # Verbose, stop on first failure
  python -m pytest tests/test_feasibility.py    # One file
  python -m pytest tests/test_feasibility.py -v # One file, verbose
  python -m pytest tests/test_scc.py -k "kosaraju"      # Substring filter
  python -m pytest --cov --cov-report=term-missing      # With coverage
  python -m pytest --cov --cov-fail-under=70            # Enforce 70 % floor
  python -m pytest -n auto                      # Parallel (needs pytest-xdist)
  python -m pytest --collect-only               # List tests without running

MARKERS (registered in pyproject.toml; --strict-markers enforced):
  slow            Test takes > 2 s or sweeps every bundled scenario
  integration     Exercises multiple subsystems end-to-end
  determinism     Verifies byte-identical adapter outputs across re-runs
  requires_sumo   Needs sumo / netconvert on PATH
  requires_java   Needs Java 17+ and the MATSim JAR
  requires_gpu    Needs NVIDIA GPU (otherwise QarSUMO CPU fallback)

  Filter examples:
    python -m pytest -m slow
    python -m pytest -m determinism
    python -m pytest -m "integration and not slow"
    python -m pytest -m "not requires_sumo"

TEST FILES (17 files / 249 tests):

  test_adapter_determinism.py     (8)   Byte-identical re-runs @determinism
  test_sumo_adapter.py            (4)   SUMO input bundle + sweep [slow]
  test_matsim_adapter.py          (24)  MATSim helpers + end-to-end [slow sweep]
  test_qarsumo_adapter.py         (10)  QarSUMO + CPU fallback [slow sweep]
  test_fidelity_metrics.py        (21)  RMSE / GEH / KS / combined
  test_metrics_travel_time.py     (2)   tripinfo.xml parser
  test_reproducibility_metrics.py (15)  R-score core + edge cases
  test_scalability_metrics.py     (8)   SimulationTimer, throughput
  test_validator.py               (2)   Bundle pass + corruption fail
  test_scenario_data_integrity.py (35)  7 classes x the bundled scenario
  test_pipeline_e2e.py            (20)  13 corruption + 3 robustness + 4 routing
  test_scc.py                     (14)  Iterative Kosaraju + parser
  test_feasibility.py             (16)  Shared cross-engine trip filter
  test_analyze_benchmark.py       (25)  Mode-aware grouping + all renderers
  test_osm_fetch.py               (20)  Mocked Overpass/osmnx pipeline
  test_demand_generators.py       (21)  Uniform / gravity / peak-hour
  test_engine_smoke.py            (4)   Real-binary SUMO/MATSim [skips if missing]

test_scenario_data_integrity.py classes (7, parametrized over every scenario):
  TestFileExistence       All 5 canonical files exist
  TestXMLParsing          All XML files are well-formed
  TestNetworkIntegrity    Unique node/link IDs, WGS84 coords, valid endpoints
  TestDemandIntegrity     Required columns, unique trip IDs, OD nodes exist
  TestConfigIntegrity     Metadata, scenario_id matches dir, valid horizon
  TestManifestIntegrity   Manifest ID matches config, all declared files exist
  TestSignalsIntegrity    Signal junction references exist in the network

WHAT THE OUTPUT LOOKS LIKE:
  Default (quiet) — one dot per passing test:
    tests/test_feasibility.py ................             [100%]
    =================== 16 passed in 0.03s ===================

  With -v — a named line per test (useful for learning the suite):
    tests/test_feasibility.py::test_drops_outside_scc PASSED    [  6%]
    tests/test_feasibility.py::test_drops_unknown_nodes PASSED  [ 12%]
    ...

  With --cov — a coverage table is appended:
    Name                              Stmts   Miss  Cover   Missing
    adapters/common/feasibility.py       94      8    91%   42-49
    ...
    TOTAL                              2847    677    76%

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
  repo_root                  Absolute path to the project root
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
   -> macOS: brew install sumo
      Linux: apt-get install sumo
      If installed but still not found:
        export SUMO_HOME=$(brew --prefix sumo)/share/sumo

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
      Skip them with: python -m pytest -m "not slow"

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
  SUMO 1.20+        macOS:  brew install sumo
                    Linux:  apt-get install sumo
                    Verify: sumo --version
  Java 17+          macOS:  brew install openjdk@17
                    Linux:  apt-get install openjdk-17-jdk
                    Verify: java -version
  QarSUMO           Optional — GPU path only. Falls back to SUMO without
                    CUDA, so most developers can skip this.

DEV DEPENDENCIES (coverage + mutation testing + parallel pytest):
  setup_simforge.py installs these automatically. To install manually:
    pip install -r requirements-dev.txt

VERIFY THE INSTALL (full sanity check):
  source .venv/bin/activate
  python -m pytest -m "not slow"                # Fast tier, ~12 s
  python -m pipeline.validation.validate_bundle scenarios/chicago_1k_car
  python -m execution.run_benchmark runspecs/stress_test.yaml --dry-run
  python -m execution.run_benchmark runspecs/stress_test.yaml      # ~27 s

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
