#!/usr/bin/env python3
"""
SimForge runner: the simplified CLI.

Usage:
    python run.py                                    # Run all scenarios, all engines, all modes
    python run.py --scenario chicago_1k_car           # Run specific scenario
    python run.py --scenario chicago_1k_car,nyc_10k_car  # Run multiple scenarios
    python run.py --engine sumo,matsim               # Run with specific engines
    python run.py --mode micro                      # Run with specific mode
    python run.py --repeats 5                       # Run with 5 repeats
    python run.py --list                            # List available options

If no parameters specified, runs ALL scenarios × ALL engines × ALL modes.
Default repeats: 10
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

from adapters.common.engine_binaries import find_engine_binary
from execution.cli_format import format_error_oneline as _format_error_oneline

# =============================================================================
# AUTO-DETECTION
# =============================================================================

def get_scenarios() -> Dict[str, dict]:
    """Auto-detect available scenarios from scenarios/ directory."""
    scenarios_dir = Path("scenarios")
    scenarios = {}
    
    if not scenarios_dir.exists():
        return scenarios
    
    for scenario_path in sorted(scenarios_dir.iterdir()):
        if scenario_path.is_dir() and (scenario_path / "manifest.xml").exists():
            name = scenario_path.name
            
            # Parse trip count from name. Anchor to the count token (a digit
            # run immediately followed by a k/m magnitude suffix, e.g. 1k or
            # 200k), not the first digit run anywhere. Take the last match so
            # a city/year prefix in the name can't be mistaken for the count.
            # The lookahead is needed because \b never fires between "k" and
            # "_" (both word characters), which made every bundled name like
            # chicago_1k_car show "?" trips.
            matches = re.findall(r'(\d+[km])(?=_|$)', name)
            if matches:
                trips = matches[-1].upper()
            else:
                trips = "?"
            
            scenarios[name] = {
                "path": str(scenario_path),
                "id": name,
                "trips": trips,
            }
    
    return scenarios


def check_engine_installed(engine: str) -> bool:
    """Check if an engine is installed."""
    if engine == "sumo":
        # Venv-aware probe: the eclipse-sumo wheel puts the binaries next to
        # the interpreter, so an unactivated `.venv/bin/python run.py` must
        # still find them. Prepare needs netconvert too, so require both.
        return (find_engine_binary("sumo") is not None
                and find_engine_binary("netconvert") is not None)
    elif engine == "matsim":
        # Use the adapter's own JAR discovery so detection here matches the
        # runner. find_matsim_jar() checks MATSIM_HOME, lib/matsim-15.0/, and
        # the standard install paths, returning None when nothing is found.
        from adapters.matsim.matsim_adapter import find_matsim_jar
        java_ok = shutil.which("java") is not None
        return find_matsim_jar() is not None and java_ok
    elif engine == "dtalite":
        from adapters.dtalite import is_dtalite_available
        return is_dtalite_available()
    return False


# Available engines and modes
ALL_ENGINES = ["sumo", "matsim", "dtalite"]
ALL_MODES = ["micro", "meso"]

# Which modes each engine can actually do. SUMO does both microscopic
# (car-following) and mesoscopic (link queue); MATSim is queue-based
# mesoscopic only; DTALite is mesoscopic dynamic traffic assignment only.
# Matrix cells that pair an engine with a mode it can't do are skipped, not
# quietly re-run as meso (which would pad the result count with duplicates).
ENGINE_SUPPORTED_MODES = {
    "sumo": {"micro", "meso"},
    "matsim": {"meso"},
    "dtalite": {"meso"},
}


# =============================================================================
# DISPLAY FUNCTIONS
# =============================================================================

def show_list():
    """Display all available options."""
    scenarios = get_scenarios()
    
    print("\n" + "=" * 60)
    print("  SimForge - Available Options")
    print("=" * 60)
    
    # Scenarios
    print("\n📦 SCENARIOS:")
    print("-" * 60)
    if scenarios:
        for name, info in scenarios.items():
            print(f"  {name:<20} {info['trips']} trips")
    else:
        print("  (no scenarios found - run generation scripts first)")
    
    # Engines
    print("\n🔧 ENGINES:")
    print("-" * 60)
    for engine in ALL_ENGINES:
        installed = "✅" if check_engine_installed(engine) else "❌"
        print(f"  {engine:<12} {installed}")
    
    # Modes
    print("\n⚙️  MODES:")
    print("-" * 60)
    for mode in ALL_MODES:
        print(f"  {mode}")
    
    # Thesis matrix
    n_scenarios = len(scenarios)
    n_engines = sum(1 for e in ALL_ENGINES if check_engine_installed(e))
    n_modes = len(ALL_MODES)
    
    print("\n📊 THESIS EXPERIMENTAL MATRIX:")
    print("-" * 60)
    print(f"  Total = {n_scenarios} scenarios × {n_engines} engines × {n_modes} modes × R repeats")
    print(f"       = {n_scenarios * n_engines * n_modes}R total runs")
    print()


# =============================================================================
# SIMULATION RUNNERS
# =============================================================================

def run_sumo(scenario_path: Path, mode: str, seed: int, output_dir: Path, timeout: int) -> dict:
    """Run SUMO simulation."""
    from adapters.sumo.sumo_adapter import prepare_sumo_inputs
    from evaluation.metrics.travel_time import parse_sumo_tripinfo
    
    native_dir = output_dir / "native_files"
    native_dir.mkdir(parents=True, exist_ok=True)

    # Remove stale outputs from a previous (possibly crashed) run before
    # launching SUMO. Otherwise a crash that produces no new tripinfo.xml
    # could leave the old file in place and we would parse stale metrics
    # while reporting success.
    (output_dir / "tripinfo.xml").unlink(missing_ok=True)
    (output_dir / "statistics.xml").unlink(missing_ok=True)

    # Convert canonical to native SUMO format
    try:
        _summary = prepare_sumo_inputs(scenario_path, native_dir)
    except (OSError, ValueError, RuntimeError) as e:
        return {"status": "failed", "error": f"Conversion failed: {e}", "wall_time_s": 0}
    
    # Find the config file
    cfg_file = native_dir / "toy.sumocfg"
    if not cfg_file.exists():
        return {"status": "failed", "error": "No SUMO config file generated", "wall_time_s": 0}
    
    tripinfo_path = output_dir / "tripinfo.xml"
    
    # Build SUMO command. Resolve the binary venv-aware (PATH first, then the
    # interpreter's own bin/) so unactivated invocations still find the
    # eclipse-sumo wheel's executables.
    sumo_bin = find_engine_binary("sumo")
    if sumo_bin is None:
        return {"status": "failed", "wall_time_s": 0,
                "error": ("sumo binary not found. Install with: "
                          "uv pip install -r requirements.lock "
                          "(bundles eclipse-sumo), or activate the venv.")}
    sumo_cmd = [sumo_bin]
    if mode == "meso":
        sumo_cmd.extend(["--mesosim", "true"])
    
    sumo_cmd.extend([
        "-c", str(cfg_file.resolve()),
        "--seed", str(seed),
        "--ignore-route-errors",
        "--tripinfo-output", str(tripinfo_path.resolve()),
        "--statistic-output", str((output_dir / "statistics.xml").resolve()),
    ])
    
    # Run SUMO. Use a monotonic clock for the duration: time.time() is
    # wall-clock and can jump backward/forward (NTP, laptop sleep), corrupting
    # the engine-time the runtime table reports.
    start_time = time.monotonic()
    try:
        proc_result = subprocess.run(
            sumo_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        wall_time = time.monotonic() - start_time

        # SUMO exits non-zero on warnings (e.g. code 100) but still writes a
        # usable tripinfo.xml in that case, so a non-zero exit is only a real
        # failure when it crashed (signal exit) or produced no tripinfo. We must
        # never report a crashed run as success.
        if proc_result.returncode != 0:
            error_lines = [l for l in (proc_result.stderr or "").split("\n")
                           if l.strip().startswith("Error:")]
            if proc_result.returncode < 0:
                return {"status": "failed", "wall_time_s": round(wall_time, 2),
                        "error": f"SUMO crashed with signal {-proc_result.returncode}"}
            if error_lines or not tripinfo_path.exists():
                msg = "\n".join(error_lines) if error_lines else (
                    (proc_result.stderr or "")[:500]
                    or f"SUMO exited with code {proc_result.returncode}")
                return {"status": "failed", "wall_time_s": round(wall_time, 2),
                        "error": msg}

    except subprocess.TimeoutExpired:
        return {"status": "failed", "error": f"Timeout after {timeout}s", "wall_time_s": timeout}
    except (OSError, subprocess.SubprocessError) as e:
        return {"status": "failed", "error": str(e), "wall_time_s": 0}
    
    # Parse travel time metrics from tripinfo.xml
    metrics = {}
    metrics_error = None
    if tripinfo_path.exists():
        try:
            stats = parse_sumo_tripinfo(tripinfo_path)
            metrics["travel_time"] = {
                "trip_count": stats.trip_count,
                "mean": stats.mean_travel_time_s,
                "p95": stats.p95_travel_time_s,
            }
        except (ValueError, FileNotFoundError) as e:
            # SUMO ran but its tripinfo.xml could not be parsed. Don't
            # silently report success with empty metrics, surface the
            # parse failure so downstream tools can flag the cell.
            metrics_error = f"tripinfo parse failed: {e}"
    else:
        metrics_error = "tripinfo.xml not produced"

    result = {
        "status": "success",
        "wall_time_s": round(wall_time, 2),
        "error": None,
        "metrics": metrics,
    }
    if metrics_error is not None:
        result["metrics_error"] = metrics_error
    return result


def run_matsim(scenario_path: Path, mode: str, seed: int, output_dir: Path, timeout: int) -> dict:
    """Run MATSim simulation."""
    _ = mode  # MATSim mode is configured via its own config, not via CLI flag
    from adapters.matsim.matsim_adapter import (
        prepare_matsim_inputs, run_matsim as _run_matsim,
        parse_matsim_output, find_matsim_jar
    )
    
    matsim_jar = find_matsim_jar()
    if matsim_jar is None:
        return {"status": "failed", "error": "MATSim JAR not found (install to lib/matsim-15.0/)", "wall_time_s": 0}
    
    native_dir = output_dir / "native_files"
    native_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        config_path = prepare_matsim_inputs(scenario_path, native_dir, random_seed=seed)
    except (OSError, ValueError, RuntimeError) as e:
        return {"status": "failed", "error": f"Conversion failed: {e}", "wall_time_s": 0}
    
    success, wall_time, error = _run_matsim(config_path, timeout_s=timeout)
    
    if not success:
        return {"status": "failed", "wall_time_s": round(wall_time, 2), "error": error or "MATSim failed"}
    
    # Parse MATSim output for metrics
    metrics = {}
    # MATSim 15+ puts output_trips.csv.gz in the top-level output dir
    matsim_output_dir = native_dir / "output"
    
    tt_data = parse_matsim_output(matsim_output_dir)
    if tt_data:
        metrics["travel_time"] = {
            "trip_count": tt_data.get("trip_count", 0),
            "mean": tt_data.get("mean_travel_time_s", 0),
            "p95": tt_data.get("p95_travel_time_s", 0),
        }
    
    return {
        "status": "success",
        "wall_time_s": round(wall_time, 2),
        "error": None,
        "metrics": metrics,
    }


def run_dtalite_engine(scenario_path: Path, mode: str, seed: int,
                       output_dir: Path, timeout: int) -> dict:
    """Run DTALite simulation via the adapter (used by run.py one-off path)."""
    _ = mode  # DTALite has no micro/meso flag, it's mesoscopic DTA only
    _ = seed  # DTALite is deterministic; seed has no effect
    from adapters.dtalite import (
        prepare_dtalite_inputs, run_dtalite, parse_dtalite_output, DTALiteConfig
    )

    native_dir = output_dir / "native_files"
    native_dir.mkdir(parents=True, exist_ok=True)

    try:
        prepare_dtalite_inputs(scenario_path, native_dir, DTALiteConfig())
    except (OSError, ValueError, RuntimeError) as e:
        return {"status": "failed", "error": f"DTALite prep failed: {e}", "wall_time_s": 0}

    success, wall_time, error = run_dtalite(native_dir, timeout_s=timeout)
    if not success:
        return {"status": "failed", "wall_time_s": round(wall_time, 2),
                "error": error or "DTALite failed"}

    metrics = {}
    stats = parse_dtalite_output(native_dir)
    if stats is not None and stats.completed_count > 0:
        metrics["travel_time"] = {
            "trip_count": stats.completed_count,
            "mean": stats.mean_travel_time_s,
            "p95": stats.p95_travel_time_s,
        }

    return {
        "status": "success",
        "wall_time_s": round(wall_time, 2),
        "error": None,
        "metrics": metrics,
    }


def run_simulation(scenario: str, engine: str, mode: str, seed: int,
                   output_base: Path, timeout: int) -> dict:
    """Run a single simulation. Pure function, caller handles all output."""
    scenario_path = Path("scenarios") / scenario
    output_dir = output_base / f"{scenario}_{engine}_{mode}_seed{seed}"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        if engine == "sumo":
            result = run_sumo(scenario_path, mode, seed, output_dir, timeout)
        elif engine == "matsim":
            result = run_matsim(scenario_path, mode, seed, output_dir, timeout)
        elif engine == "dtalite":
            result = run_dtalite_engine(scenario_path, mode, seed, output_dir, timeout)
        else:
            result = {"status": "failed", "error": f"Unknown engine: {engine}"}
        return result
    except Exception as e:  # noqa: BLE001
        # Any prep/run failure becomes a failed cell, never an uncaught
        # exception that aborts the whole benchmark loop (the per-cell loop in
        # main() has no outer guard). The narrow (OSError, RuntimeError,
        # ValueError) tuple used to let xml.etree ParseError (a SyntaxError
        # subclass) and KeyError/TypeError from a malformed bundle escape.
        return {"status": "failed",
                "error": f"{type(e).__name__}: {e}", "wall_time_s": 0}


# =============================================================================
# MAIN EXECUTION
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="SimForge Runner - Run traffic simulations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py                              # Run ALL (default)
  python run.py --scenario chicago_1k_car    # Run one scenario
  python run.py --scenario chicago_1k_car,nyc_10k_car  # Run multiple
  python run.py --engine sumo                # Run with one engine
  python run.py --engine sumo,matsim         # Run with multiple engines
  python run.py --mode meso                  # Run with one mode
  python run.py --repeats 5                  # 5 repeats (default: 10)
  python run.py --list                       # Show available options
        """
    )
    
    parser.add_argument("--scenario", "-s", 
                        help="Scenario(s) to run, comma-separated. Default: all")
    parser.add_argument("--engine", "-e", 
                        help="Engine(s) to use, comma-separated. Default: all installed")
    parser.add_argument("--mode", "-m", 
                        help="Mode(s) to run, comma-separated. Default: all")
    parser.add_argument("--repeats", "-r", type=int, default=10,
                        help="Number of repeats (default: 10)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Base random seed (default: 42)")
    parser.add_argument("--timeout", "-t", type=int, default=3600,
                        help="Timeout per run in seconds (default: 3600)")
    parser.add_argument("--output", "-o", 
                        help="Custom output directory (default: runs/)")
    parser.add_argument("--list", "-l", action="store_true",
                        help="List available scenarios, engines, and modes")
    parser.add_argument("--validate-only", "-v", action="store_true",
                        help="Only validate scenarios, don't run")
    parser.add_argument("--verbose", action="store_true",
                        help="Show adapter INFO logs (default: WARNING and above only)")

    args = parser.parse_args()

    # Quiet adapter INFO chatter by default, the per-cell summary lines
    # are enough for the operator. The harness only suppresses INFO from
    # SimForge's own adapter modules; WARNING+ from any source still
    # surfaces. Pass --verbose to restore the firehose (useful when
    # debugging a single failing cell).
    import logging as _logging
    if args.verbose:
        _logging.basicConfig(level=_logging.INFO, force=True)
    else:
        _logging.basicConfig(level=_logging.WARNING, force=True)
        for _name in ("adapters", "adapters.sumo", "adapters.matsim",
                      "adapters.dtalite", "adapters.common", "pipeline"):
            _logging.getLogger(_name).setLevel(_logging.WARNING)
    
    # Handle --list
    if args.list:
        show_list()
        return 0
    
    # Get available scenarios
    scenarios_available = get_scenarios()
    if not scenarios_available:
        print("❌ No scenarios found. Generate scenarios first:")
        print("   python scripts/01_chicago_1k_car.py")
        print("   python generate.py --preset chicago_1k_car")
        return 1
    
    # Determine scenarios to run. The checks distinguish "flag not given"
    # (None: run everything) from "flag given but empty or malformed"
    # (--scenario "" or "a,,b"): the latter must be an explicit error, never
    # a silent fall-through that launches the full multi-day matrix.
    if args.scenario is not None:
        scenarios = [s.strip() for s in args.scenario.split(",")]
        if not scenarios or any(not s for s in scenarios):
            print(f"❌ --scenario must be a non-empty comma-separated list, got: {args.scenario!r}")
            print(f"   Available: {', '.join(scenarios_available.keys())}")
            return 1
        for s in scenarios:
            if s not in scenarios_available:
                print(f"❌ Unknown scenario: {s}")
                print(f"   Available: {', '.join(scenarios_available.keys())}")
                return 1
    else:
        scenarios = list(scenarios_available.keys())

    # Determine engines to use
    if args.engine is not None:
        engines = [e.strip() for e in args.engine.split(",")]
        if not engines or any(not e for e in engines):
            print(f"❌ --engine must be a non-empty comma-separated list, got: {args.engine!r}")
            print(f"   Available: {', '.join(ALL_ENGINES)}")
            return 1
        for e in engines:
            if e not in ALL_ENGINES:
                print(f"❌ Unknown engine: {e}")
                print(f"   Available: {', '.join(ALL_ENGINES)}")
                return 1
            if not check_engine_installed(e):
                print(f"⚠️  Warning: {e} not installed, skipping")
        engines = [e for e in engines if check_engine_installed(e)]
    else:
        engines = [e for e in ALL_ENGINES if check_engine_installed(e)]

    if not engines:
        print("❌ No engines available. Install SUMO, MATSim, or DTALite.")
        return 1

    # Determine modes to run
    if args.mode is not None:
        modes = [m.strip() for m in args.mode.split(",")]
        if not modes or any(not m for m in modes):
            print(f"❌ --mode must be a non-empty comma-separated list, got: {args.mode!r}")
            print(f"   Available: {', '.join(ALL_MODES)}")
            return 1
        for m in modes:
            if m not in ALL_MODES:
                print(f"❌ Unknown mode: {m}")
                print(f"   Available: {', '.join(ALL_MODES)}")
                return 1
    else:
        modes = ALL_MODES
    
    # Handle validation-only. validate_bundle() prints its own ✓ VALID /
    # ✗ INVALID line per scenario, so we don't wrap it with redundant
    # status prints.
    if args.validate_only:
        print("\n" + "=" * 60)
        print("  Validating Scenarios")
        print("=" * 60 + "\n")
        from pipeline.validation.validate_bundle import validate_bundle
        for scenario in scenarios:
            try:
                validate_bundle(Path(scenarios_available[scenario]["path"]))
            except (OSError, ValueError, KeyError) as e:
                print(f"  ✗ EXCEPTION  {scenario}: {e}")
        return 0
    
    # Validate repeats and timeout
    if args.repeats < 1:
        print(f"\u274c --repeats must be \u2265 1, got {args.repeats}")
        return 1
    if args.timeout < 1:
        print(f"\u274c --timeout must be \u2265 1 second, got {args.timeout}")
        return 1

    # Build the actual cell list, skipping (engine, mode) pairs the engine
    # does not support. This avoids re-running MATSim and DTALite once per
    # mode when only SUMO has a meaningful micro/meso distinction.
    repeats = args.repeats
    valid_cells = [
        (scenario, engine, mode)
        for scenario in scenarios
        for engine in engines
        for mode in modes
        if mode in ENGINE_SUPPORTED_MODES[engine]
    ]
    skipped_cells = [
        (engine, mode)
        for engine in engines
        for mode in modes
        if mode not in ENGINE_SUPPORTED_MODES[engine]
    ]
    total_runs = len(valid_cells) * repeats

    # Display experimental matrix
    print("\n" + "=" * 60)
    print("  SimForge Benchmark")
    print("=" * 60)
    print("\n📊 EXPERIMENTAL MATRIX:")
    print("-" * 60)
    print(f"  Scenarios: {len(scenarios)} ({', '.join(scenarios)})")
    print(f"  Engines:   {len(engines)} ({', '.join(engines)})")
    print(f"  Modes:     {len(modes)} ({', '.join(modes)})")
    print(f"  Repeats:   {repeats}")
    if skipped_cells:
        print(f"  Skipped:   {len(skipped_cells)} engine/mode pair(s) "
              f"(unsupported by engine):")
        for engine, mode in sorted(set(skipped_cells)):
            print(f"             - {engine} does not support mode={mode}")
    print("-" * 60)
    print(f"  Total:     {len(valid_cells)} cells × {repeats} repeats = {total_runs} runs")
    print("-" * 60)
    
    # Setup output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_base = Path(args.output) if args.output else Path("runs") / f"benchmark_{timestamp}"
    try:
        output_base.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"❌ Cannot create output directory {output_base}: {e}")
        return 1
    
    print(f"\n  Output: {output_base}")
    print("\n" + "=" * 60)
    print("  Running Simulations")
    print("=" * 60)

    # Compute fixed column widths from the actual matrix so per-cell
    # rows line up cleanly regardless of scenario/engine name length.
    sc_w = max(len(s) for s in scenarios)
    eng_w = max(len(e) for e in engines)
    mode_w = max(len(m) for m in modes)
    cell_idx_w = len(str(total_runs))

    # Sticky progress bar from the shared pipeline.progress.StickyProgress
    # module: TTY-only, a heartbeat spinner, flicker-free in-place updates,
    # ✓N ✗N counters in the tail. It goes quiet when stdout is piped (sbatch
    # logs, CI captures). Logs always route above the bar via print_above() so
    # WARNING+ records (e.g. osmnx "Dropping degenerate edge") don't collide
    # with the bar's no-newline writes. The threshold differs by mode:
    #   default  -> WARNING+ only (errors surface, no INFO firehose)
    #   verbose  -> INFO+    (full adapter chatter)
    import logging as _logging
    from pipeline.progress import StickyProgress
    progress = StickyProgress(
        total_runs, unit="run",
        capture_logs=True,
        capture_log_level=_logging.INFO if args.verbose else _logging.WARNING,
        capture_log_names=("", "adapters", "adapters.sumo",
                           "adapters.matsim", "adapters.dtalite",
                           "adapters.common", "pipeline"),
    )
    progress.start()

    results = []
    completed = 0
    failed = 0
    bench_started_at = time.perf_counter()
    last_scenario = None
    cell_idx = 0

    results_file = output_base / "benchmark_results.json"

    def _save_partial():
        # Checkpoint after every cell so a hard kill (Ctrl-C, SLURM timeout)
        # still leaves a recoverable JSON, mirroring execution.run_benchmark.
        comp = sum(1 for r in results if r.get("status") == "success")
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": timestamp,
                "matrix": {
                    "scenarios": scenarios,
                    "engines": engines,
                    "modes": modes,
                    "repeats": repeats,
                },
                "summary": {
                    "total": total_runs,
                    "completed": comp,
                    "failed": len(results) - comp,
                },
                "results": results,
            }, f, indent=2)

    for scenario, engine, mode in valid_cells:
        for rep in range(repeats):
            cell_idx += 1
            seed = args.seed + rep

            # Print a scenario-divider header the first time we hit a
            # new scenario; print_above clears+redraws the bar around
            # the new line so the divider lands cleanly above the bar.
            if scenario != last_scenario:
                progress.print_above(f"\n▶ {scenario}")
                last_scenario = scenario

            cell_label = f"{scenario}/{engine}/{mode} seed={seed}"
            progress.set_label(cell_label)

            cell_started_at = time.perf_counter()
            result = run_simulation(
                scenario=scenario,
                engine=engine,
                mode=mode,
                seed=seed,
                output_base=output_base,
                timeout=args.timeout,
            )
            elapsed = time.perf_counter() - cell_started_at
            cell_wall_s = round(elapsed, 2)                       # full prep + engine + parse
            engine_wall_s = round(result.get("wall_time_s") or 0.0, 2)  # engine subprocess only
            # `runtime_s` is the legacy field thesis tools key off (Table 5.1,
            # Fig 5.1, R-score). Keep it pointing at engine-only time on success
            # so analyze_benchmark / generate_plots are unchanged; fall back to
            # full cell wall on failure (engine_wall_s is 0 there).
            runtime_s = engine_wall_s if engine_wall_s > 0 else cell_wall_s

            result.update({
                "scenario": scenario,
                "scenario_id": f"{scenario}_{engine}_{mode}",
                "engine": engine,
                "mode": mode,
                "seed": seed,
                "repeat": rep + 1,
                "runtime_s": runtime_s,
                "cell_wall_s": cell_wall_s,        # full per-cell wall (matches Wall time sum)
                "engine_wall_s": engine_wall_s,    # engine subprocess only (thesis number)
            })
            results.append(result)
            _save_partial()  # checkpoint after every cell

            ok = result["status"] == "success"
            if ok:
                completed += 1
                mark = "✓"
                if engine_wall_s > 0:
                    tail = f"{cell_wall_s:>6.1f}s wall  ({engine_wall_s:>5.1f}s engine)"
                else:
                    tail = f"{cell_wall_s:>6.1f}s wall"
            else:
                failed += 1
                mark = "✗"
                tail = f"FAIL  {_format_error_oneline(result.get('error'), max_len=72)}"

            # Print the cell row above the bar, then advance the bar.
            progress.print_above(
                f"  [{cell_idx:>{cell_idx_w}}/{total_runs}]  "
                f"{engine:<{eng_w}}  "
                f"{mode:<{mode_w}}  "
                f"seed={seed}  "
                f"{mark}  {tail}"
            )
            progress.advance(ok=ok)

    progress.stop()
    bench_wall = time.perf_counter() - bench_started_at

    # Final authoritative save (per-cell checkpoints already wrote partials).
    _save_partial()

    # Final summary
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    pct = 100.0 * completed / max(total_runs, 1)
    mins, secs = divmod(int(bench_wall), 60)
    print(f"\n  Wall time:    {mins}m {secs:02d}s")
    print(f"  ✓ Completed:  {completed}/{total_runs} ({pct:.1f}%)")
    print(f"  ✗ Failed:     {failed}/{total_runs}")

    # Per-cell-type timing breakdown using the same Student's-t 95% CI
    # convention the thesis tables and figures use (evaluation/metrics/
    # confidence.py). With N>=2 reps the ± half-width is t_{0.025,N-1}
    # × σ_sample / √N; with N=1 it's 0 (no spread to report).
    from evaluation.metrics.confidence import confidence_interval_95
    import statistics
    by_cell_wall: dict[tuple, list[float]] = {}
    by_cell_engine: dict[tuple, list[float]] = {}
    for r in results:
        if r.get("status") != "success":
            continue
        key = (r["scenario"], r["engine"], r["mode"])
        by_cell_wall.setdefault(key, []).append(r.get("cell_wall_s", r.get("runtime_s", 0.0)))
        by_cell_engine.setdefault(key, []).append(r.get("engine_wall_s", 0.0))

    failed_results = [r for r in results if r.get("status") != "success"]
    if failed_results:
        print("\n  ✗ Failed cells (full error in benchmark_results.json `error` field):")
        for r in failed_results:
            msg = _format_error_oneline(r.get("error"), max_len=72)
            print(f"    {r['scenario']:<{sc_w}}  {r['engine']:<{eng_w}}  "
                  f"{r['mode']:<{mode_w}}  seed={r['seed']}  {msg}")

    if by_cell_wall:
        print("\n  Per-cell wall time (full prep + engine + parse, mean ± 95 % CI across reps;")
        print("  engine-only mean in parens, that's the number Chapter 5 tables cite):")
        for (sc, eng, md), wall_times in by_cell_wall.items():
            eng_times = by_cell_engine.get((sc, eng, md), [])
            ci = confidence_interval_95(wall_times)
            eng_mean = statistics.mean(eng_times) if eng_times else 0.0
            note = "" if ci.n >= 2 else "  (N=1, no CI)"
            print(f"    {sc:<{sc_w}}  {eng:<{eng_w}}  {md:<{mode_w}}  "
                  f"{ci.mean:>7.1f}s ± {ci.half_width:>5.1f}s wall  "
                  f"(engine {eng_mean:>5.1f}s)  ({ci.n} runs){note}")

    print(f"\n  \U0001f4c1 Results:    {results_file}\n")
    print("=" * 60 + "\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # Ctrl-C mid-benchmark: the per-cell checkpoint already wrote every
        # completed cell to benchmark_results.json in the output directory
        # (printed at startup), so nothing is lost but the in-flight cell.
        print("\n⚠ Interrupted (Ctrl-C). Completed cells are checkpointed in "
              "benchmark_results.json under the run's output directory.")
        sys.exit(130)
