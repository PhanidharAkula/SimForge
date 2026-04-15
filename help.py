#!/usr/bin/env python3
"""
SimForge Help System

Comprehensive reference for all commands, options, limits, and examples.

Usage:
  python help.py                    # Full help
  python help.py generate           # Data generation help
  python help.py run                # Simulation running help
  python help.py presets            # Preset configurations help
  python help.py cities             # Supported cities & limits
  python help.py modes              # Travel modes reference
  python help.py adapters           # Simulator adapters help
  python help.py metrics            # Evaluation metrics help
  python help.py troubleshooting    # Common issues & fixes
"""

import sys
from pathlib import Path

# =============================================================================
# HELP SECTIONS
# =============================================================================

HELP_OVERVIEW = """
╔══════════════════════════════════════════════════════════════════════╗
║                     SimForge Help System                             ║
║      Reproducible Cross-Simulator Traffic Benchmarking               ║
╚══════════════════════════════════════════════════════════════════════╝

SimForge generates standardized traffic simulation data from real
U.S. Census microdata, converts it to multiple simulator formats,
and provides unified evaluation metrics.

QUICK START:
  1. Generate data:   python generate.py --city chicago --trips 5000
  2. Validate:        python -m pipeline.validation.validate_bundle scenarios/chicago_5k_car
  3. Run simulation:  python run.py --scenario chicago_5k_car --engine sumo --mode meso
  4. Run benchmark:   python -m execution.run_benchmark runspecs/benchmark_5k.yaml

HELP TOPICS:
  python help.py generate           Data generation (generate.py)
  python help.py run                Simulation execution (run.py)
  python help.py presets            Built-in preset configurations
  python help.py cities             Supported cities, radii, and census limits
  python help.py modes              Travel modes reference
  python help.py adapters           Simulator adapters (SUMO, MATSim, QarSUMO)
  python help.py metrics            Evaluation metrics (fidelity, scalability, reproducibility)
  python help.py schema             Canonical schema format reference
  python help.py benchmark          Benchmark harness and runspecs
  python help.py troubleshooting    Common issues and fixes

PROJECT STRUCTURE:
  generate.py           Unified scenario generator (start here)
  run.py                Simulation runner CLI
  help.py               This help system
  presets/              5 ready-to-use preset scenarios
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
╔══════════════════════════════════════════════════════════════════════╗
║                    DATA GENERATION (generate.py)                     ║
╚══════════════════════════════════════════════════════════════════════╝

The unified generator creates canonical scenario bundles using real
U.S. Census PUMS microdata (via ModelGen) as the default demand source.

BASIC USAGE:
  python generate.py --city <city> --trips <count>

REQUIRED FLAGS:
  --city, -c <name>        City: chicago, nyc, la
                           (or use --preset instead)

DEMAND FLAGS:
  --trips, -t <count>      Number of OD trips (default: 5000)
  --modes <list>           Comma-separated modes: car,transit,bike,walk
                           (default: car)
  --start-time <seconds>   Simulation start, seconds from midnight (default: 0)
  --end-time <seconds>     Simulation end, seconds from midnight (default: 3600)

NETWORK FLAGS:
  --radius, -r <km>        Network extraction radius (default: city-specific)
                           chicago: 4.0 km, nyc: 3.0 km, la: 5.0 km

CONTROL FLAGS:
  --seed, -s <int>         Random seed (default: 42)
  --output, -o <path>      Custom output directory
  --id <string>            Custom scenario ID

DEMAND SOURCE FLAGS:
  --synthetic              Force synthetic gravity model (skip census data)
  --allow-oversample       Allow more trips than census commuters (resamples)

DISPLAY FLAGS:
  --list                   Show all cities, presets, modes, and limits
  --preset, -p <name>      Use a preset configuration (see: python help.py presets)

COMMON TIME REFERENCES (seconds from midnight):
  00:00 =     0     06:00 = 21600     12:00 = 43200     18:00 = 64800
  01:00 =  3600     07:00 = 25200     13:00 = 46800     19:00 = 68400
  02:00 =  7200     08:00 = 28800     14:00 = 50400     20:00 = 72000
  03:00 = 10800     09:00 = 32400     15:00 = 54000     21:00 = 75600
  04:00 = 14400     10:00 = 36000     16:00 = 57600     22:00 = 79200
  05:00 = 18000     11:00 = 39600     17:00 = 61200     23:00 = 82800
                                                        24:00 = 86400

EXAMPLES:

  # Minimal 5K car scenario
  python generate.py --city chicago --trips 5000

  # 200K mixed-mode trips, morning rush (6-9 AM)
  python generate.py --city la --trips 200000 --modes car,transit \\
         --start-time 21600 --end-time 32400

  # Full-day 170K car trips in NYC
  python generate.py --city nyc --trips 170000 \\
         --start-time 0 --end-time 86400

  # Custom radius and seed
  python generate.py --city chicago --trips 10000 --radius 8.0 --seed 7

  # Large-scale with oversampling
  python generate.py --city la --trips 1000000 --allow-oversample \\
         --start-time 21600 --end-time 36000 --radius 30.0

  # Force synthetic demand (no census data needed)
  python generate.py --city chicago --trips 5000 --synthetic

  # Use a preset
  python generate.py --preset morning_rush

  # Override preset parameters
  python generate.py --preset morning_rush --trips 100000 --city nyc

OUTPUT:
  Generated scenarios are saved to: scenarios/<scenario_id>/
  Each bundle contains:
    network.xml              Road network (nodes + links from OSM)
    demand.csv               Trip-level OD demand
    signals.xml              Traffic signal timing
    config.xml               Scenario metadata
    manifest.xml             File inventory
    generation_metadata.json Generation parameters (for reproducibility)
"""

HELP_RUN = """
╔══════════════════════════════════════════════════════════════════════╗
║                    SIMULATION RUNNING (run.py)                       ║
╚══════════════════════════════════════════════════════════════════════╝

The runner executes simulations across scenarios, engines, and modes.

BASIC USAGE:
  python run.py                                    # Run ALL
  python run.py --scenario <name> --engine <name>  # Run specific

FLAGS:
  --scenario, -s <name>    Scenario name(s), comma-separated
  --engine, -e <name>      Engine(s): sumo, matsim, qarsumo
  --mode, -m <name>        Mode(s): micro, meso
  --repeats, -r <n>        Number of repeats (default: 10)
  --seed <int>             Base random seed (default: 42)
  --timeout, -t <seconds>  Per-run timeout (default: 3600)
  --output, -o <path>      Output directory (default: runs/)
  --list, -l               List available scenarios, engines, modes
  --validate-only, -v      Only validate scenarios, don't simulate

EXAMPLES:

  # Run all scenarios with SUMO mesoscopic
  python run.py --engine sumo --mode meso

  # Run specific scenario
  python run.py --scenario chicago_5k_car --engine sumo --mode meso

  # Run with 5 repeats
  python run.py --scenario nyc_5k_car --engine sumo --repeats 5

  # Validate scenarios only
  python run.py --validate-only

  # List all available options
  python run.py --list

BENCHMARK HARNESS:
  For structured benchmarking with multiple configs, use the harness:

  python -m execution.run_benchmark runspecs/benchmark_5k.yaml
  python -m execution.run_benchmark runspecs/benchmark_5k.yaml --mesoscopic
  python -m execution.run_benchmark runspecs/benchmark_5k.yaml --dry-run

OUTPUT:
  Results saved to: runs/benchmark_<timestamp>/
  Each run produces:
    native_files/        Simulator-specific input files
    tripinfo.xml         SUMO trip results
    statistics.xml       SUMO aggregate statistics
    benchmark_results.json  Structured results with metrics
"""

HELP_PRESETS = """
╔══════════════════════════════════════════════════════════════════════╗
║                       PRESET CONFIGURATIONS                          ║
╚══════════════════════════════════════════════════════════════════════╝

SimForge includes 5 built-in presets for common use cases.
Run them directly or use as templates for custom scenarios.

RUNNING PRESETS:
  python generate.py --preset <name>           # via unified generator
  python -m presets.run <name>                  # via preset runner
  python presets/preset_<name>.py               # direct script

AVAILABLE PRESETS:
┌─────────────────┬──────────┬────────┬──────────────────┬──────────┬──────────┐
│ Preset          │ City     │ Trips  │ Modes            │ Time     │ Radius   │
├─────────────────┼──────────┼────────┼──────────────────┼──────────┼──────────┤
│ quick_test      │ Chicago  │  1,000 │ car              │ 00-00:30 │  2.0 km  │
│ morning_rush    │ LA       │ 50,000 │ car              │ 06-09:00 │ 10.0 km  │
│ multimodal_city │ NYC      │ 20,000 │ car+transit+bike │ 07-09:00 │  4.0 km  │
│ full_day        │ LA       │100,000 │ car              │ 00-24:00 │ 15.0 km  │
│ stress_test     │ Chicago  │500,000 │ car              │ 06-10:00 │ 20.0 km  │
└─────────────────┴──────────┴────────┴──────────────────┴──────────┴──────────┘

PRESET DETAILS:

  1. quick_test
     Purpose:   Rapid validation during development
     Generate:  python generate.py --preset quick_test
     Runtime:   ~15s generation, <1s simulation

  2. morning_rush
     Purpose:   Realistic peak-hour commute analysis
     Generate:  python generate.py --preset morning_rush
     Runtime:   ~2 min generation, ~15-30s simulation

  3. multimodal_city
     Purpose:   Multi-modal transportation analysis
     Generate:  python generate.py --preset multimodal_city
     Note:      SUMO simulates car trips; MATSim handles all modes
     Runtime:   ~1 min generation, ~5-10s simulation

  4. full_day
     Purpose:   Full 24-hour demand pattern analysis
     Generate:  python generate.py --preset full_day
     Runtime:   ~3-5 min generation, ~1-2 min simulation

  5. stress_test
     Purpose:   Performance limit evaluation
     Generate:  python generate.py --preset stress_test
     Note:      May need --allow-oversample for census data
     Runtime:   ~10-15 min generation, ~5-15 min simulation

OVERRIDING PRESET VALUES:
  Any flag can override the preset defaults:
  python generate.py --preset morning_rush --city nyc --trips 100000
"""

HELP_CITIES = """
╔══════════════════════════════════════════════════════════════════════╗
║                 SUPPORTED CITIES & CENSUS LIMITS                     ║
╚══════════════════════════════════════════════════════════════════════╝

SimForge supports 3 U.S. cities with real census microdata from
ModelGen (PUMS + LandScan + OpenStreetMap integration).

CITY DETAILS:
┌──────────┬────────────────────┬────────────────┬──────────────────────┐
│ Key      │ City               │ Center         │ Default Radius       │
├──────────┼────────────────────┼────────────────┼──────────────────────┤
│ chicago  │ Chicago, IL        │ 41.878, -87.630│ 4.0 km               │
│ nyc      │ New York City, NY  │ 40.758, -73.986│ 3.0 km               │
│ la       │ Los Angeles, CA    │ 34.052,-118.244│ 5.0 km               │
└──────────┴────────────────────┴────────────────┴──────────────────────┘

CENSUS DATA CAPACITY (without --allow-oversample):
┌──────────┬──────────────────┬──────────────────┬──────────────────────┐
│ City     │ Car-only         │ All modes        │ Model file size      │
├──────────┼──────────────────┼──────────────────┼──────────────────────┤
│ Chicago  │ ~500K trips      │ ~600K trips      │ 279 MB               │
│ NYC      │ ~400K trips      │ ~700K trips      │ 608 MB               │
│ LA       │ ~500K trips      │ ~600K trips      │ 310 MB               │
└──────────┴──────────────────┴──────────────────┴──────────────────────┘

  Note: These are approximate limits for the full model file.
  Actual capacity depends on the bounding box (radius) used.
  Smaller radius = fewer census records available.

SCALING GUIDELINES:
  Radius   Approx. nodes    Car commuters available
  ──────   ──────────────   ───────────────────────
   2 km      500-2,000        5K-20K
   5 km    2,000-8,000       20K-100K
  10 km    8,000-30,000      50K-300K
  20 km   20,000-80,000     200K-500K+
  50 km   50,000-200,000    500K+ (may need oversample)

  Rule of thumb: Double the radius → ~4x the area → ~3-4x the records.

BEYOND CENSUS LIMITS:
  For trips exceeding census capacity:
  1. Use --allow-oversample (resamples origins with replacement)
  2. Use --synthetic (gravity model, no census dependency)
  3. Use a larger radius to capture more census records
  4. Use multi-mode (--modes car,transit) to access more records

MODEL FILES:
  Census microdata files are in: modelgen/
    chicago_model.txt    279 MB   Chicago metro PUMS + LandScan
    nyc_model.txt        608 MB   NYC metro PUMS + LandScan
    la_model.txt         310 MB   LA metro PUMS + LandScan

  These files contain building, household, and person records with:
  - Building locations (snapped to OSM roads)
  - Household demographics (income, size)
  - Person-level data (age, commute time JWMNP, transport mode JWTRNS)
"""

HELP_MODES = """
╔══════════════════════════════════════════════════════════════════════╗
║                      TRAVEL MODES REFERENCE                          ║
╚══════════════════════════════════════════════════════════════════════╝

SUPPORTED MODES:
┌──────────┬─────────────────────────────────────────────────────────┐
│ Mode     │ Description                                             │
├──────────┼─────────────────────────────────────────────────────────┤
│ car      │ Private automobile (drove alone, carpool, taxi, other)  │
│ transit  │ Public transportation (bus, subway, rail, ferry)        │
│ bike     │ Bicycle                                                 │
│ walk     │ Walking                                                 │
└──────────┴─────────────────────────────────────────────────────────┘

CENSUS MODE MAPPING (JWTRNS codes → canonical modes):
  JWTRNS 1  (drove alone)           → car
  JWTRNS 2  (carpooled)             → car
  JWTRNS 3  (bus)                   → transit
  JWTRNS 4  (streetcar/trolley)     → transit
  JWTRNS 5  (subway/elevated rail)  → transit
  JWTRNS 6  (railroad)              → transit
  JWTRNS 7  (ferryboat)             → transit
  JWTRNS 8  (bicycle)               → bike
  JWTRNS 9  (walked)                → walk
  JWTRNS 10 (worked from home)      → excluded
  JWTRNS 11 (taxicab/rideshare)     → car
  JWTRNS 12 (other)                 → car

SINGLE MODE (default):
  python generate.py --city la --trips 5000
  → All trips assigned mode="car"

MULTI-MODE:
  python generate.py --city nyc --trips 20000 --modes car,transit,bike
  → Each trip gets the census person's actual transportation mode
  → Mode distribution reflects real city commute patterns

SIMULATOR MODE SUPPORT:
┌──────────┬──────────────────────────────────────────────────────────┐
│ Engine   │ Mode support                                             │
├──────────┼──────────────────────────────────────────────────────────┤
│ SUMO     │ car (micro/meso), transit (with SUMO PT module)          │
│ QarSUMO  │ car only (GPU-accelerated vehicle simulation)            │
│ MATSim   │ car, transit, bike, walk (activity-based multi-modal)    │
└──────────┴──────────────────────────────────────────────────────────┘

  Note: When running multi-modal demand through SUMO, non-car trips are
  included in the demand file but only car trips are routed and simulated.
  MATSim simulates all modes natively.
"""

HELP_ADAPTERS = """
╔══════════════════════════════════════════════════════════════════════╗
║                      SIMULATOR ADAPTERS                              ║
╚══════════════════════════════════════════════════════════════════════╝

SimForge converts canonical data bundles to simulator-native formats
via deterministic adapters.

SUPPORTED SIMULATORS:
┌──────────┬────────────┬──────────────────────────────────────────────┐
│ Engine   │ Version    │ Description                                  │
├──────────┼────────────┼──────────────────────────────────────────────┤
│ SUMO     │ 1.18+      │ Microscopic/mesoscopic vehicle simulation    │
│ QarSUMO  │ Latest     │ GPU-accelerated SUMO (CUDA required)         │
│ MATSim   │ 15.0       │ Activity-based mesoscopic multi-agent sim    │
└──────────┴────────────┴──────────────────────────────────────────────┘

SIMULATION MODES:
  micro    Microscopic — car-following, lane-changing (accurate, slow)
  meso     Mesoscopic — queue-based edge travel (fast, 10-100x speedup)

ADAPTER CLI COMMANDS:
  # SUMO adapter
  python -m adapters.sumo.cli <scenario_path> <output_dir>

  # QarSUMO adapter (GPU)
  python -m adapters.qarsumo.cli <scenario_path> <output_dir> --run

  # MATSim adapter
  python -m adapters.matsim.cli <scenario_path> <output_dir> --run

PREREQUISITES:
  SUMO:    brew install sumo  (or https://sumo.dlr.de/docs/Downloads.php)
           Verify: sumo --version

  MATSim:  Download JAR to lib/matsim-15.0/matsim-15.0.jar
           Requires: Java 17+ (brew install openjdk@17)

  QarSUMO: Requires NVIDIA GPU with CUDA 11+
           Falls back to SUMO on CPU-only systems

CONVERSION FLOW:
  Canonical Bundle       →  SUMO:    nodes.nod.xml + edges.edg.xml
                                     → netconvert → net.net.xml
                                     → routes.rou.xml + toy.sumocfg

  Canonical Bundle       →  MATSim:  network.xml + plans.xml
                                     + vehicles.xml + config.xml

  Canonical Bundle       →  QarSUMO: Same as SUMO + <qarsumo> GPU config

EXPECTED PERFORMANCE (mesoscopic, 5K tier):
  Engine   │ Chicago  │ NYC    │ LA
  ─────────┼──────────┼────────┼──────────
  SUMO     │ 2-5 s    │ 1-3 s  │ 3-8 s
  MATSim   │ 10-15 s  │ 8-12 s │ 12-20 s
  QarSUMO  │ 2-5 s    │ 1-3 s  │ 3-8 s (CPU fallback)
"""

HELP_METRICS = """
╔══════════════════════════════════════════════════════════════════════╗
║                       EVALUATION METRICS                             ║
╚══════════════════════════════════════════════════════════════════════╝

SimForge evaluates simulations across three dimensions:

1. FIDELITY — How closely does the simulator reproduce traffic patterns?

   RMSE (Root Mean Square Error)
     Formula:  RMSE = sqrt(mean((observed - simulated)²))
     Usage:    Compares link-level volumes or travel times

   GEH Statistic (Geoffrey E. Havers)
     Formula:  GEH = sqrt(2(S-O)² / (S+O))
     Thresholds:
       GEH < 5    Acceptable fit
       5 ≤ GEH < 10  Warrants investigation
       GEH ≥ 10   Poor fit

   KS Statistic (Kolmogorov-Smirnov)
     Formula:  D = max|F_A(x) - F_B(x)|
     Usage:    Compares travel time distributions between engines

2. SCALABILITY — How does computational cost scale?

   Throughput:        trips / wall_clock_seconds
   SRT Ratio:         simulated_time / wall_clock_time
                      (SRT > 1 = faster than real-time)
   Per-core:          throughput / CPU_cores
   Per-watt:          throughput / TDP_watts

3. REPRODUCIBILITY — How consistent are repeated runs?

   R-Index:           R = 1 - σ/μ  (coefficient of variation)
   Interpretation:
     R ≥ 0.99    Excellent (near-deterministic)
     0.95 ≤ R    Very good
     0.90 ≤ R    Good
     0.80 ≤ R    Acceptable
     R < 0.50    Poor (high variability)

RUNNING ANALYSIS:
  # Analyze benchmark results
  python -m evaluation.analyze_benchmark runs/benchmark_results.json

  # Compare micro vs meso modes
  python -m evaluation.compare_modes scenarios/chicago_5k_car

  # Generate thesis plots
  python -m evaluation.generate_plots runs/benchmark_results.json --output figures/
"""

HELP_SCHEMA = """
╔══════════════════════════════════════════════════════════════════════╗
║                    CANONICAL SCHEMA REFERENCE                        ║
╚══════════════════════════════════════════════════════════════════════╝

Every SimForge scenario bundle contains 5 canonical files:

1. network.xml — Road Network
   <network>
     <metadata crs="EPSG:4326" units_length="meters" units_speed="m/s"/>
     <nodes>
       <node id="n0" x="-87.63" y="41.88" type="intersection"/>
     </nodes>
     <links>
       <link id="l0" from="n0" to="n1" length="150.0" lanes="2"
             speed_limit="13.9" road_type="residential"/>
     </links>
   </network>

2. demand.csv — Trip-Level OD Demand
   trip_id,origin_node_id,destination_node_id,departure_time_s,mode
   t0,n42,n187,21600,car
   t1,n15,n93,21660,transit

3. signals.xml — Traffic Signal Timing
   <signals>
     <junction id="tl_n0" node_id="n0" cycle_length_s="90">
       <phase id="p0" duration_s="37" state="G">
         <link_ref id="l1"/>
       </phase>
     </junction>
   </signals>

4. config.xml — Scenario Configuration
   <config>
     <metadata scenario_id="chicago_5k_car"/>
     <time start_time_s="0" end_time_s="3600"/>
     <random seed="42"/>
     <units length="meters" speed="m/s" time="seconds"/>
   </config>

5. manifest.xml — File Inventory
   <manifest version="0.1">
     <scenario id="chicago_5k_car"/>
     <canonical_files>
       <file type="network" path="network.xml"/>
       <file type="demand" path="demand.csv"/>
       <file type="config" path="config.xml"/>
       <file type="signals" path="signals.xml"/>
     </canonical_files>
   </manifest>

VALIDATION:
  python -m pipeline.validation.validate_bundle scenarios/<scenario_id>

  Checks: manifest structure, config consistency, network integrity,
  demand-network referential integrity (all OD node IDs exist), units.
"""

HELP_BENCHMARK = """
╔══════════════════════════════════════════════════════════════════════╗
║                  BENCHMARK HARNESS & RUNSPECS                        ║
╚══════════════════════════════════════════════════════════════════════╝

The benchmark harness executes simulation matrices defined in YAML
runspec files.

RUNNING BENCHMARKS:
  python -m execution.run_benchmark <runspec.yaml>
  python -m execution.run_benchmark <runspec.yaml> --mesoscopic
  python -m execution.run_benchmark <runspec.yaml> --dry-run
  python -m execution.run_benchmark <runspec.yaml> --scenario chicago_5k

BUILT-IN RUNSPECS:
┌────────────────────────┬───────┬──────────┬───────┬─────────────────┐
│ File                   │ Trips │ Timeout  │ Runs  │ Description     │
├────────────────────────┼───────┼──────────┼───────┼─────────────────┤
│ benchmark_5k.yaml      │  5K   │  600s    │ 27    │ Quick benchmark │
│ benchmark_50k.yaml     │ 50K   │ 1800s    │ 27    │ Medium scale    │
│ benchmark_500k.yaml    │ 500K  │ 3600s    │ 27    │ Large scale     │
│ benchmark_5m.yaml      │  5M   │ 7200s    │ 27    │ Extreme scale   │
└────────────────────────┴───────┴──────────┴───────┴─────────────────┘

  Each runspec: 3 cities x 3 engines x 3 repeats = 27 runs
  Engines: sumo, qarsumo, matsim (all mesoscopic)

RUNSPEC YAML FORMAT:
  name: my_benchmark
  description: Custom benchmark
  global_output_dir: runs
  runs:
    - scenario_id: chicago_5k_car
      scenario_path: scenarios/chicago_5k_car
      engine: sumo
      mode: mesoscopic
      repeats: 3
      seed: 42
      timeout_s: 600

OUTPUT:
  runs/<output_dir>/
    benchmark_results_<name>.json    Full results with per-run metrics
"""

HELP_TROUBLESHOOTING = """
╔══════════════════════════════════════════════════════════════════════╗
║                       TROUBLESHOOTING                                ║
╚══════════════════════════════════════════════════════════════════════╝

COMMON ISSUES:

1. "No residential buildings mapped to network nodes"
   Cause:  Model file covers a different area than the bounding box.
   Fix:    Check --city matches the model file region.
           Increase --radius to capture more buildings.

2. "Requested N trips but only M raw census commuters available"
   Cause:  Trip count exceeds census population in the bounding box.
   Fix:    a) Use --allow-oversample (resamples with replacement)
           b) Use --synthetic (gravity model, no census limit)
           c) Increase --radius to capture more commuters
           d) Reduce --trips

3. "No scenarios found" when running simulations
   Cause:  Scenarios haven't been generated yet.
   Fix:    python generate.py --city chicago --trips 5000

4. "SUMO not found" / "sumo: command not found"
   Cause:  SUMO simulator not installed.
   Fix:    macOS:  brew install sumo
           Linux:  apt install sumo sumo-tools
           Verify: sumo --version (need 1.18+)

5. "MATSim JAR not found"
   Cause:  MATSim not downloaded.
   Fix:    mkdir -p lib
           Download matsim-15.0.zip from GitHub releases
           Unzip to lib/matsim-15.0/
           Verify: ls lib/matsim-15.0/matsim-15.0.jar

6. "netconvert: command not found"
   Cause:  SUMO tools not in PATH.
   Fix:    Ensure SUMO_HOME is set and SUMO bin/ is in PATH.
           macOS: export SUMO_HOME=$(brew --prefix sumo)/share/sumo

7. "ModuleNotFoundError: No module named 'pipeline'"
   Cause:  Python path not set to project root.
   Fix:    Run from project root: cd SimForge
           Or: PYTHONPATH=. python generate.py ...

8. OSM download timeout / network errors
   Cause:  Overpass API rate limiting or connectivity issues.
   Fix:    Wait and retry. Large radii (>20 km) may timeout.
           Consider caching: scenarios persist after generation.

9. "Java version too old" for MATSim
   Cause:  Java < 17 installed.
   Fix:    brew install openjdk@17
           export JAVA_HOME=$(/usr/libexec/java_home -v 17)

GETTING HELP:
  python help.py                    Full help overview
  python help.py <topic>            Topic-specific help
  python generate.py --help         Generator CLI help
  python run.py --help              Runner CLI help
  python -m pytest tests/ -v        Run test suite to verify installation
"""

# =============================================================================
# TOPIC REGISTRY
# =============================================================================

TOPICS = {
    "overview": HELP_OVERVIEW,
    "generate": HELP_GENERATE,
    "run": HELP_RUN,
    "presets": HELP_PRESETS,
    "cities": HELP_CITIES,
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

    if topic in TOPICS:
        print(TOPICS[topic])
    else:
        print(f"\nUnknown help topic: '{topic}'")
        print(f"\nAvailable topics: {', '.join(TOPICS.keys())}")
        print("\nUsage: python help.py [topic]")


if __name__ == "__main__":
    main()
