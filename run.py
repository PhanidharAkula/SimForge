#!/usr/bin/env python3
"""
SimForge Runner - Simplified CLI

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
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

# Suppress unused import warning - subprocess is used in multiple functions
_ = subprocess  # noqa: F401

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
            
            # Parse trip count from name
            import re
            m = re.search(r'(\d+[km]?)', name)
            if m:
                trips = m.group(1).upper()
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
        return shutil.which("sumo") is not None
    elif engine == "matsim":
        matsim_jar = Path("lib/matsim-15.0/matsim-15.0.jar")
        java_ok = shutil.which("java") is not None
        return matsim_jar.exists() and java_ok
    elif engine == "dtalite":
        from adapters.dtalite import is_dtalite_available
        return is_dtalite_available()
    return False


# Available engines and modes
ALL_ENGINES = ["sumo", "matsim", "dtalite"]
ALL_MODES = ["micro", "meso"]

# Per-engine mode capability. Engines simulate exactly one paradigm each:
# SUMO supports both microscopic (car-following) and mesoscopic (link queue);
# MATSim is queue-based mesoscopic only; DTALite is mesoscopic Dynamic
# Traffic Assignment only. Cells in the experimental matrix that pair an
# engine with an unsupported mode are skipped — not silently re-run as
# meso, which would inflate the result count with duplicated cells.
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
    
    # Build SUMO command
    sumo_cmd = ["sumo"]
    if mode == "meso":
        sumo_cmd.extend(["--mesosim", "true"])
    
    sumo_cmd.extend([
        "-c", str(cfg_file.resolve()),
        "--seed", str(seed),
        "--ignore-route-errors",
        "--tripinfo-output", str(tripinfo_path.resolve()),
        "--statistic-output", str((output_dir / "statistics.xml").resolve()),
    ])
    
    # Run SUMO
    start_time = time.time()
    try:
        proc_result = subprocess.run(
            sumo_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        wall_time = time.time() - start_time
        
        # SUMO returns non-zero for warnings (e.g., code 100).
        # Check for actual errors in stderr, not just return code.
        has_error = False
        if proc_result.returncode != 0:
            error_lines = [l for l in (proc_result.stderr or "").split("\n")
                           if l.strip().startswith("Error:")]
            if error_lines:
                has_error = True
        
        if has_error and not tripinfo_path.exists():
            return {"status": "failed", "wall_time_s": round(wall_time, 2),
                    "error": proc_result.stderr[:500]}
    
    except subprocess.TimeoutExpired:
        return {"status": "failed", "error": f"Timeout after {timeout}s", "wall_time_s": timeout}
    except (OSError, subprocess.SubprocessError) as e:
        return {"status": "failed", "error": str(e), "wall_time_s": 0}
    
    # Parse travel time metrics from tripinfo.xml
    metrics = {}
    if tripinfo_path.exists():
        try:
            stats = parse_sumo_tripinfo(tripinfo_path)
            metrics["travel_time"] = {
                "trip_count": stats.trip_count,
                "mean": stats.mean_travel_time_s,
                "p95": stats.p95_travel_time_s,
            }
        except (ValueError, FileNotFoundError):
            pass
    
    return {
        "status": "success",
        "wall_time_s": round(wall_time, 2),
        "error": None,
        "metrics": metrics,
    }


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
    _ = mode  # DTALite has no micro/meso flag — it's mesoscopic DTA only
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
    """Run a single simulation. Pure function — caller handles all output."""
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
    except (OSError, RuntimeError, ValueError) as e:
        return {"status": "failed", "error": str(e), "wall_time_s": 0}


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

    # Quiet adapter INFO chatter by default — the per-cell summary lines
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
    
    # Determine scenarios to run
    if args.scenario:
        scenarios = [s.strip() for s in args.scenario.split(",")]
        for s in scenarios:
            if s not in scenarios_available:
                print(f"❌ Unknown scenario: {s}")
                print(f"   Available: {', '.join(scenarios_available.keys())}")
                return 1
    else:
        scenarios = list(scenarios_available.keys())
    
    # Determine engines to use
    if args.engine:
        engines = [e.strip() for e in args.engine.split(",")]
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
        print("❌ No engines available. Install SUMO or MATSim.")
        return 1
    
    # Determine modes to run
    if args.mode:
        modes = [m.strip() for m in args.mode.split(",")]
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
    output_base.mkdir(parents=True, exist_ok=True)
    
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

    def _fmt_dur(seconds: float) -> str:
        s = int(seconds)
        if s < 60:
            return f"{s}s"
        m, s = divmod(s, 60)
        if m < 60:
            return f"{m}m {s:02d}s"
        h, m = divmod(m, 60)
        return f"{h}h {m:02d}m"

    # Sticky progress bar from the shared pipeline.progress.StickyProgress
    # module. TTY-only with a heartbeat spinner, flicker-free in-place
    # updates, ✓N ✗N counters in the tail. Suppressed silently when
    # stdout is piped (sbatch logs, CI captures). Logs are ALWAYS routed
    # above the bar via print_above() so WARNING+ records (e.g. osmnx
    # "Dropping degenerate edge") don't collide with the bar's
    # no-newline writes. The level threshold differs by mode:
    #   default  → WARNING+ only (errors surface, no INFO firehose)
    #   verbose  → INFO+    (full adapter chatter)
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
            wall = result.get("wall_time_s") or round(elapsed, 2)

            result.update({
                "scenario": scenario,
                "scenario_id": f"{scenario}_{engine}_{mode}",
                "engine": engine,
                "mode": mode,
                "seed": seed,
                "repeat": rep + 1,
                "runtime_s": wall,
            })
            results.append(result)

            ok = result["status"] == "success"
            if ok:
                completed += 1
                mark = "✓"
                tail = f"{wall:>7.1f}s"
            else:
                failed += 1
                mark = "✗"
                err = (result.get("error") or "unknown error")
                err = " ".join(err.split())[:60]
                tail = f"FAIL  {err}"

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
    
    # Save results
    results_file = output_base / "benchmark_results.json"
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
                "completed": completed,
                "failed": failed,
            },
            "results": results,
        }, f, indent=2)
    
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
    by_cell: dict[tuple, list[float]] = {}
    for r in results:
        if r.get("status") != "success":
            continue
        key = (r["scenario"], r["engine"], r["mode"])
        by_cell.setdefault(key, []).append(r["runtime_s"])
    if by_cell:
        print("\n  Per-cell timing (mean ± 95% CI across reps, successful runs only):")
        for (sc, eng, md), times in by_cell.items():
            ci = confidence_interval_95(times)
            note = "" if ci.n >= 2 else "  (N=1, no CI)"
            print(f"    {sc:<{sc_w}}  {eng:<{eng_w}}  {md:<{mode_w}}  "
                  f"{ci.mean:>7.1f}s ± {ci.half_width:>5.1f}s  "
                  f"({ci.n} runs){note}")

    print(f"\n  \U0001f4c1 Results:    {results_file}")
    print("=" * 60 + "\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
