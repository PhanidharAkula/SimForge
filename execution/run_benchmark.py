"""
Benchmark execution harness for SimForge.

Orchestrates:
1. Loading run specifications
2. Validating scenario bundles
3. Running adapters to generate engine inputs
4. Executing simulations
5. Collecting outputs and computing metrics

Usage:
    python -m execution.run_benchmark runspecs/benchmark_small.yaml
    python -m execution.run_benchmark runspecs/benchmark_small.yaml --dry-run
    python -m execution.run_benchmark runspecs/benchmark_small.yaml --scenario chicago_1k_car
"""

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import logging

from execution.cli_format import format_error_oneline as _format_error_oneline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """Result of a single simulation run.

    Three timing fields, all in seconds:
      • runtime_s     — back-compat alias for engine_wall_s. Thesis tools
                        (analyze_benchmark, generate_plots) key off this.
      • engine_wall_s — engine subprocess only (mobsim / UE / netsim).
                        What Chapter 5 runtime tables cite.
      • cell_wall_s   — full per-cell wall: adapter prep (incl. per-trip BFS
                        routing) + engine subprocess + output parse.
                        Sums to the harness "Wall time" total.
    """
    scenario: str                       # Base scenario name (e.g. "chicago_1k_car")
    engine: str                         # "sumo", "matsim", "dtalite"
    mode: str                           # "micro" or "meso"
    seed: int
    repeat_index: int                   # 0-based
    status: str                         # "success", "failed", "timeout"
    runtime_s: float                    # engine subprocess only (back-compat)
    output_dir: Path
    tripinfo_path: Optional[Path] = None
    error_message: Optional[str] = None
    metrics: dict = field(default_factory=dict)
    engine_wall_s: float = 0.0          # engine subprocess only (== runtime_s on success)
    cell_wall_s: float = 0.0            # full per-cell wall (prep + engine + parse)

    @property
    def scenario_id(self) -> str:
        """Composite unique ID: <scenario>_<engine>_<mode>."""
        return f"{self.scenario}_{self.engine}_{self.mode}"

    @property
    def repeat(self) -> int:
        """1-based repeat number for display/compat with run.py output."""
        return self.repeat_index + 1

    def to_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "scenario_id": self.scenario_id,
            "engine": self.engine,
            "mode": self.mode,
            "seed": self.seed,
            "repeat": self.repeat,
            "repeat_index": self.repeat_index,
            "status": self.status,
            "runtime_s": self.runtime_s,
            "wall_time_s": self.runtime_s,
            "engine_wall_s": self.engine_wall_s,
            "cell_wall_s": self.cell_wall_s,
            "output_dir": str(self.output_dir),
            "tripinfo_path": str(self.tripinfo_path) if self.tripinfo_path else None,
            "error_message": self.error_message,
            "metrics": self.metrics,
        }


@dataclass
class BenchmarkResult:
    """Aggregated results from a benchmark run."""
    runspec_name: str
    started_at: str
    completed_at: str
    total_runs: int
    successful_runs: int
    failed_runs: int
    results: list[RunResult] = field(default_factory=list)

    @property
    def summary(self) -> dict:
        return {
            "total": self.total_runs,
            "completed": self.successful_runs,
            "failed": self.failed_runs,
        }

    def to_dict(self) -> dict:
        return {
            "runspec_name": self.runspec_name,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_runs": self.total_runs,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "summary": self.summary,
            "results": [r.to_dict() for r in self.results]
        }

    def save(self, path: Path) -> None:
        """Save results to JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)


class BenchmarkHarness:
    """Main benchmark execution harness."""
    
    def __init__(self, output_base: Path = Path("runs")):
        self.output_base = Path(output_base)
        self.output_base.mkdir(parents=True, exist_ok=True)
    
    def validate_bundle(self, scenario_path: Path) -> bool:
        """Validate a canonical scenario bundle."""
        from pipeline.validation.validate_bundle import validate_bundle
        
        try:
            # validate_bundle returns True if valid, False otherwise
            # and prints errors to stdout
            valid = validate_bundle(scenario_path)
            if not valid:
                logger.error("Validation failed for %s", scenario_path)
            return valid
        except (OSError, ValueError) as e:
            logger.error("Validation error for %s: %s", scenario_path, e)
            return False
    
    def prepare_sumo_inputs(
        self,
        scenario_path: Path,
        output_dir: Path,
        seed: int
    ) -> dict:
        """Prepare SUMO inputs from canonical bundle."""
        _ = seed  # SUMO adapter handles seeds at runtime, not during input prep
        from adapters.sumo.sumo_adapter import prepare_sumo_inputs
        
        return prepare_sumo_inputs(scenario_path, output_dir)
    
    def run_sumo(
        self,
        config_path: Path,
        timeout_s: int = 3600,
        seed: Optional[int] = None,
        ignore_route_errors: bool = True,
        mesoscopic: bool = False
    ) -> tuple[bool, float, Optional[str]]:
        """
        Run SUMO simulation.
        
        Args:
            config_path: Path to .sumocfg file
            timeout_s: Simulation timeout
            seed: Random seed for SUMO
            ignore_route_errors: If True, skip vehicles with invalid routes instead of aborting
            mesoscopic: If True, use mesoscopic simulation (10-100x faster for large scenarios)
        
        Returns:
            Tuple of (success, runtime_seconds, error_message)
        """
        # Use absolute path for config
        config_path = config_path.resolve()
        cmd = ["sumo", "-c", str(config_path)]
        
        if seed is not None:
            cmd.extend(["--seed", str(seed)])
        
        if ignore_route_errors:
            cmd.extend(["--ignore-route-errors"])
        
        if mesoscopic:
            cmd.extend(["--mesosim"])
            logger.info("Using mesoscopic simulation mode (faster)")
        
        logger.info("Running: %s", ' '.join(cmd))
        
        start_time = time.time()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=config_path.parent,
                check=False
            )
            runtime = time.time() - start_time
            
            if result.returncode != 0:
                # Extract only actual error lines (not warnings)
                error_lines = [
                    line for line in (result.stderr or "").split("\n")
                    if line.strip().startswith("Error:")
                ]
                error_msg = "\n".join(error_lines[:5]) if error_lines else (result.stderr[:500] if result.stderr else "Unknown error")
                return False, runtime, error_msg
            
            return True, runtime, None
            
        except subprocess.TimeoutExpired:
            runtime = time.time() - start_time
            return False, runtime, f"Timeout after {timeout_s}s"
        except OSError as e:
            runtime = time.time() - start_time
            return False, runtime, str(e)
    
    def compute_metrics(self, output_dir: Path) -> dict:
        """Compute metrics from simulation outputs."""
        from evaluation.metrics.travel_time import parse_sumo_tripinfo
        
        metrics = {}
        
        # Parse tripinfo if available
        tripinfo_path = output_dir / "tripinfo.xml"
        if tripinfo_path.exists():
            try:
                stats = parse_sumo_tripinfo(tripinfo_path)
                metrics["travel_time"] = {
                    "mean": stats.mean_travel_time_s,
                    "p95": stats.p95_travel_time_s,
                    "trip_count": stats.trip_count
                }
            except (OSError, ValueError) as e:
                logger.warning("Failed to parse tripinfo: %s", e)
        
        return metrics
    
    def run_single(
        self,
        scenario_id: str,
        scenario_path: Path,
        engine: str,
        seed: int,
        repeat_index: int,
        timeout_s: int = 3600,
        engine_options: dict = None,
        mesoscopic: bool = False
    ) -> RunResult:
        """Execute a single simulation run."""

        mode = "meso" if mesoscopic else "micro"
        # Create output directory
        run_dir = self.output_base / scenario_id / engine / f"seed_{seed}"
        run_dir.mkdir(parents=True, exist_ok=True)

        mode_str = " (mesoscopic)" if mesoscopic else ""
        logger.info("Starting run: %s / %s / seed=%d%s", scenario_id, engine, seed, mode_str)

        # Handle different engines
        supported_engines = ["sumo", "matsim", "dtalite"]
        if engine not in supported_engines:
            return RunResult(
                scenario=scenario_id,
                engine=engine,
                mode=mode,
                seed=seed,
                repeat_index=repeat_index,
                status="failed",
                runtime_s=0,
                output_dir=run_dir,
                error_message=f"Unsupported engine: {engine}. Supported: {supported_engines}"
            )
        
        # Prepare inputs based on engine
        try:
            if engine == "matsim":
                # MATSim activity-based simulator
                from adapters.matsim import prepare_matsim_inputs, MATSimConfig
                matsim_opts = engine_options or {}
                matsim_config = MATSimConfig(
                    iterations=matsim_opts.get("iterations", 0),
                    java_heap_gb=matsim_opts.get("heap_gb", 4),
                )
                prepare_matsim_inputs(scenario_path, run_dir, matsim_config, random_seed=seed)
            elif engine == "dtalite":
                # DTALite mesoscopic Dynamic Traffic Assignment (CPU)
                from adapters.dtalite import prepare_dtalite_inputs, DTALiteConfig
                dtalite_opts = engine_options or {}
                dtalite_config = DTALiteConfig(
                    iterations=dtalite_opts.get("iterations", 5),
                    column_updating_iterations=dtalite_opts.get(
                        "column_updating_iterations", 5
                    ),
                    simulation_output=dtalite_opts.get("simulation_output", 1),
                )
                prepare_dtalite_inputs(scenario_path, run_dir, dtalite_config)
            else:
                # SUMO
                self.prepare_sumo_inputs(scenario_path, run_dir, seed)
        except (OSError, ValueError, RuntimeError) as e:
            return RunResult(
                scenario=scenario_id,
                engine=engine,
                mode=mode,
                seed=seed,
                repeat_index=repeat_index,
                status="failed",
                runtime_s=0,
                output_dir=run_dir,
                error_message=f"Adapter failed: {e}"
            )
        
        # Find config file and run simulation based on engine
        if engine == "matsim":
            # MATSim uses config.xml
            config_path = run_dir / "config.xml"
            if not config_path.exists():
                return RunResult(
                    scenario=scenario_id,
                    engine=engine,
                    mode=mode,
                    seed=seed,
                    repeat_index=repeat_index,
                    status="failed",
                    runtime_s=0,
                    output_dir=run_dir,
                    error_message="No config.xml file generated for MATSim"
                )

            from adapters.matsim import run_matsim, parse_matsim_output
            matsim_opts = engine_options or {}
            success, runtime, error = run_matsim(
                config_path,
                timeout_s=timeout_s,
                java_heap_gb=matsim_opts.get("heap_gb", 4)
            )

            # Parse MATSim-specific metrics
            metrics = {}
            tripinfo_path = None
            if success:
                output_subdir = run_dir / "output"
                stats = parse_matsim_output(output_subdir)
                if stats:
                    metrics["travel_time"] = {
                        "mean": stats.get("mean_travel_time_s", 0),
                        "p95": stats.get("p95_travel_time_s", 0),
                        "trip_count": stats.get("trip_count", 0)
                    }
        elif engine == "dtalite":
            # DTALite reads settings.csv + node.csv + link.csv + demand.csv
            # from CWD; the adapter writes them under run_dir during
            # prepare_dtalite_inputs.
            settings_path = run_dir / "settings.csv"
            if not settings_path.exists():
                return RunResult(
                    scenario=scenario_id,
                    engine=engine,
                    mode=mode,
                    seed=seed,
                    repeat_index=repeat_index,
                    status="failed",
                    runtime_s=0,
                    output_dir=run_dir,
                    error_message="No settings.csv generated for DTALite"
                )

            from adapters.dtalite import run_dtalite, parse_dtalite_output
            dtalite_opts = engine_options or {}
            success, runtime, error = run_dtalite(
                run_dir,
                timeout_s=timeout_s,
                iterations=dtalite_opts.get("iterations", 5),
                column_updating_iterations=dtalite_opts.get(
                    "column_updating_iterations", 5
                ),
            )

            metrics = {}
            tripinfo_path = None
            if success:
                stats = parse_dtalite_output(run_dir)
                if stats is not None and stats.completed_count > 0:
                    metrics["travel_time"] = {
                        "mean": stats.mean_travel_time_s,
                        "p95": stats.p95_travel_time_s,
                        "trip_count": stats.completed_count,
                    }
        else:
            # SUMO uses .sumocfg
            config_files = list(run_dir.glob("*.sumocfg"))
            if not config_files:
                return RunResult(
                    scenario=scenario_id,
                    engine=engine,
                    mode=mode,
                    seed=seed,
                    repeat_index=repeat_index,
                    status="failed",
                    runtime_s=0,
                    output_dir=run_dir,
                    error_message="No .sumocfg file generated"
                )

            config_path = config_files[0]
            success, runtime, error = self.run_sumo(config_path, timeout_s, seed, mesoscopic=mesoscopic)

            # Compute metrics if successful
            metrics = {}
            tripinfo_path = None
            if success:
                tripinfo_path = run_dir / "tripinfo.xml"
                if tripinfo_path.exists():
                    metrics = self.compute_metrics(run_dir)
                else:
                    tripinfo_path = None
        
        # Determine status
        status = "success" if success else ("timeout" if "Timeout" in (error or "") else "failed")

        return RunResult(
            scenario=scenario_id,
            engine=engine,
            mode=mode,
            seed=seed,
            repeat_index=repeat_index,
            status=status,
            runtime_s=runtime,
            output_dir=run_dir,
            tripinfo_path=tripinfo_path,
            error_message=error,
            metrics=metrics
        )
    
    def run_benchmark(
        self,
        runspec_path: Path,
        scenario_filter: Optional[str] = None,
        dry_run: bool = False,
        force_mesoscopic: bool = False,
        verbose: bool = False,
    ) -> BenchmarkResult:
        """
        Execute a full benchmark from a runspec file.

        Args:
            runspec_path: Path to runspec YAML/JSON
            scenario_filter: Only run scenarios matching this ID
            dry_run: If True, only validate and print what would run
            force_mesoscopic: If True, override runspec and use mesoscopic for all runs
            verbose: If True, route adapter INFO logs above the sticky bar

        Returns:
            BenchmarkResult with all run results
        """
        from execution.runspec import RunSpec

        runspec = RunSpec.from_file(runspec_path)
        self.output_base = Path(runspec.global_output_dir)
        self.output_base.mkdir(parents=True, exist_ok=True)

        started_at = datetime.now(timezone.utc).isoformat()
        results: list[RunResult] = []

        runs_to_execute = runspec.runs
        if scenario_filter:
            runs_to_execute = [r for r in runs_to_execute if r.scenario_id == scenario_filter]

        total_runs = sum(r.repeats for r in runs_to_execute)
        distinct_scenarios = list(dict.fromkeys(r.scenario_id for r in runs_to_execute))
        distinct_engines = list(dict.fromkeys(r.engine for r in runs_to_execute))
        modes_used: list[str] = []
        for r in runs_to_execute:
            m = "meso" if (force_mesoscopic or r.is_mesoscopic) else "micro"
            if m not in modes_used:
                modes_used.append(m)
        distinct_repeats = sorted({r.repeats for r in runs_to_execute})

        # Matrix banner — same look as run.py
        print("\n" + "=" * 60)
        print("  SimForge Benchmark")
        print("=" * 60)
        print("\n📊 EXPERIMENTAL MATRIX:")
        print("-" * 60)
        print(f"  Runspec:   {runspec.name}")
        print(f"  Scenarios: {len(distinct_scenarios)} ({', '.join(distinct_scenarios)})")
        print(f"  Engines:   {len(distinct_engines)} ({', '.join(distinct_engines)})")
        print(f"  Modes:     {len(modes_used)} ({', '.join(modes_used)})")
        if len(distinct_repeats) == 1:
            print(f"  Repeats:   {distinct_repeats[0]}")
        else:
            print(f"  Repeats:   {distinct_repeats[0]}-{distinct_repeats[-1]} (varies per row)")
        if force_mesoscopic:
            print("  Override:  --mesoscopic (every row forced to meso)")
        if scenario_filter:
            print(f"  Filter:    --scenario {scenario_filter}")
        print("-" * 60)
        print(f"  Total:     {len(runs_to_execute)} cells × repeats = {total_runs} runs")
        print("-" * 60)

        if dry_run:
            print("\n🔍 DRY RUN MODE - No simulations will be executed")
            # Pre-validate each unique bundle once (validate_bundle prints
            # its own ✓ VALID / ✗ INVALID line); cache the result so the
            # per-row "Would run" block stays purely formatted.
            print("\n📋 Validating scenario bundles...")
            dry_validation: dict[str, bool] = {}
            for run_config in runs_to_execute:
                scenario_path = Path(run_config.scenario_path)
                if str(scenario_path) not in dry_validation:
                    dry_validation[str(scenario_path)] = self.validate_bundle(scenario_path)

            print()
            for run_config in runs_to_execute:
                scenario_path = Path(run_config.scenario_path)
                mode = "meso" if run_config.is_mesoscopic or force_mesoscopic else "micro"
                bundle_ok = dry_validation.get(str(scenario_path), False)
                marker = "✓" if bundle_ok else "✗"
                print(f"  {marker} {run_config.scenario_id}")
                print(f"      path:    {scenario_path}")
                print(f"      engine:  {run_config.engine} ({mode})")
                print(f"      repeats: {run_config.repeats}")
                print(f"      seeds:   {run_config.get_seeds()}\n")
            return BenchmarkResult(
                runspec_name=runspec.name,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                total_runs=total_runs,
                successful_runs=0,
                failed_runs=0,
                results=[]
            )

        # Pre-validate all bundles. validate_bundle() already prints its
        # own ✓ VALID / ✗ INVALID line per scenario, so we don't echo a
        # second status line here.
        print("\n📋 Validating scenario bundles...")
        validation_status: dict[str, bool] = {}
        for run_config in runs_to_execute:
            scenario_path = Path(run_config.scenario_path)
            if str(scenario_path) not in validation_status:
                validation_status[str(scenario_path)] = self.validate_bundle(scenario_path)

        print(f"\n  Output: {self.output_base}")
        print("\n" + "=" * 60)
        print("  Running Simulations")
        print("=" * 60)

        # Fixed-width columns for the per-cell rows (same as run.py).
        sc_w = max((len(s) for s in distinct_scenarios), default=1)
        eng_w = max((len(e) for e in distinct_engines), default=1)
        mode_w = max((len(m) for m in modes_used), default=4)
        cell_idx_w = len(str(max(total_runs, 1)))

        # Always route logs through print_above() so WARNING+ records
        # don't collide with the sticky bar's no-newline writes. Level
        # threshold: WARNING+ in default mode, INFO+ when --verbose.
        import logging as _logging
        from pipeline.progress import StickyProgress
        progress = StickyProgress(
            total_runs, unit="run",
            capture_logs=True,
            capture_log_level=_logging.INFO if verbose else _logging.WARNING,
            capture_log_names=("", "adapters", "adapters.sumo",
                               "adapters.matsim", "adapters.dtalite",
                               "adapters.common", "pipeline"),
        )
        progress.start()

        bench_started_at = time.perf_counter()
        last_scenario: Optional[str] = None
        cell_idx = 0

        for run_config in runs_to_execute:
            scenario_path = Path(run_config.scenario_path)
            mesoscopic = force_mesoscopic or run_config.is_mesoscopic
            mode_label = "meso" if mesoscopic else "micro"
            seeds = run_config.get_seeds()
            bundle_ok = validation_status.get(str(scenario_path), False)

            for i, seed in enumerate(seeds):
                cell_idx += 1

                if run_config.scenario_id != last_scenario:
                    progress.print_above(f"\n▶ {run_config.scenario_id}")
                    last_scenario = run_config.scenario_id

                if not bundle_ok:
                    results.append(RunResult(
                        scenario=run_config.scenario_id,
                        engine=run_config.engine,
                        mode=mode_label,
                        seed=seed,
                        repeat_index=i,
                        status="failed",
                        runtime_s=0,
                        output_dir=self.output_base / run_config.scenario_id,
                        error_message="Bundle validation failed",
                    ))
                    progress.print_above(
                        f"  [{cell_idx:>{cell_idx_w}}/{total_runs}]  "
                        f"{run_config.engine:<{eng_w}}  "
                        f"{mode_label:<{mode_w}}  "
                        f"seed={seed}  "
                        f"✗  FAIL  bundle validation failed"
                    )
                    progress.advance(ok=False)
                    continue

                progress.set_label(f"{run_config.scenario_id}/{run_config.engine}/{mode_label} seed={seed}")
                cell_started_at = time.perf_counter()
                result = self.run_single(
                    scenario_id=run_config.scenario_id,
                    scenario_path=scenario_path,
                    engine=run_config.engine,
                    seed=seed,
                    repeat_index=i,
                    timeout_s=run_config.timeout_s,
                    engine_options=run_config.engine_options,
                    mesoscopic=mesoscopic,
                )
                elapsed = time.perf_counter() - cell_started_at
                cell_wall_s = round(elapsed, 2)
                engine_wall_s = round(result.runtime_s or 0.0, 2)
                # Backfill wall fields the harness now exposes.
                result.cell_wall_s = cell_wall_s
                result.engine_wall_s = engine_wall_s
                results.append(result)

                ok = result.status == "success"
                if ok:
                    mark = "✓"
                    if engine_wall_s > 0:
                        tail = f"{cell_wall_s:>6.1f}s wall  ({engine_wall_s:>5.1f}s engine)"
                    else:
                        tail = f"{cell_wall_s:>6.1f}s wall"
                else:
                    mark = "✗"
                    tail = f"FAIL  {_format_error_oneline(result.error_message, max_len=72)}"

                progress.print_above(
                    f"  [{cell_idx:>{cell_idx_w}}/{total_runs}]  "
                    f"{run_config.engine:<{eng_w}}  "
                    f"{mode_label:<{mode_w}}  "
                    f"seed={seed}  "
                    f"{mark}  {tail}"
                )
                progress.advance(ok=ok)

        progress.stop()
        bench_wall = time.perf_counter() - bench_started_at

        completed_at = datetime.now(timezone.utc).isoformat()
        successful = sum(1 for r in results if r.status == "success")
        failed = len(results) - successful

        benchmark_result = BenchmarkResult(
            runspec_name=runspec.name,
            started_at=started_at,
            completed_at=completed_at,
            total_runs=total_runs,
            successful_runs=successful,
            failed_runs=failed,
            results=results,
        )

        results_path = self.output_base / f"benchmark_results_{runspec.name}.json"
        benchmark_result.save(results_path)

        # Final summary — same look as run.py
        print("\n" + "=" * 60)
        print("  Summary")
        print("=" * 60)
        pct = 100.0 * successful / max(total_runs, 1)
        mins, secs = divmod(int(bench_wall), 60)
        print(f"\n  Wall time:    {mins}m {secs:02d}s")
        print(f"  ✓ Completed:  {successful}/{total_runs} ({pct:.1f}%)")
        print(f"  ✗ Failed:     {failed}/{total_runs}")

        from evaluation.metrics.confidence import confidence_interval_95
        import statistics
        by_cell_wall: dict[tuple, list[float]] = {}
        by_cell_engine: dict[tuple, list[float]] = {}
        for r in results:
            if r.status != "success":
                continue
            key = (r.scenario, r.engine, r.mode)
            by_cell_wall.setdefault(key, []).append(r.cell_wall_s or r.runtime_s)
            by_cell_engine.setdefault(key, []).append(r.engine_wall_s or r.runtime_s)

        failed_results = [r for r in results if r.status != "success"]
        if failed_results:
            print(f"\n  ✗ Failed cells (full error in {results_path.name} `error_message` field):")
            for r in failed_results:
                msg = _format_error_oneline(r.error_message, max_len=72)
                print(f"    {r.scenario:<{sc_w}}  {r.engine:<{eng_w}}  "
                      f"{r.mode:<{mode_w}}  seed={r.seed}  {msg}")

        if by_cell_wall:
            print("\n  Per-cell wall time (full prep + engine + parse, mean ± 95 % CI across reps;")
            print("  engine-only mean in parens — that's the number Chapter 5 tables cite):")
            for (sc, eng, md), wall_times in by_cell_wall.items():
                eng_times = by_cell_engine.get((sc, eng, md), [])
                ci = confidence_interval_95(wall_times)
                eng_mean = statistics.mean(eng_times) if eng_times else 0.0
                note = "" if ci.n >= 2 else "  (N=1, no CI)"
                print(f"    {sc:<{sc_w}}  {eng:<{eng_w}}  {md:<{mode_w}}  "
                      f"{ci.mean:>7.1f}s ± {ci.half_width:>5.1f}s wall  "
                      f"(engine {eng_mean:>5.1f}s)  ({ci.n} runs){note}")

        print(f"\n  📁 Results:    {results_path}\n")
        print("=" * 60 + "\n")

        return benchmark_result


def compute_reproducibility_from_results(results: list[RunResult]) -> dict:
    """
    Compute reproducibility metrics across repeated runs.
    
    Groups results by scenario_id and computes R index for travel time.
    """
    from evaluation.metrics.reproducibility import compute_reproducibility_metrics
    from collections import defaultdict
    
    # Group by scenario
    by_scenario = defaultdict(list)
    for r in results:
        if r.status == "success" and r.metrics.get("travel_time"):
            by_scenario[r.scenario_id].append(r)
    
    reproducibility = {}
    for scenario_id, runs in by_scenario.items():
        if len(runs) < 2:
            continue
        
        # Extract mean travel times from each run
        mean_travel_times = [r.metrics["travel_time"]["mean"] for r in runs]
        
        try:
            r_metrics = compute_reproducibility_metrics(mean_travel_times, "mean_travel_time")
            reproducibility[scenario_id] = {
                "R_index": r_metrics.reproducibility_index,
                "interpretation": r_metrics.interpretation,
                "n_runs": len(runs),
                "values": mean_travel_times
            }
        except (ValueError, ZeroDivisionError) as e:
            logger.warning("Could not compute reproducibility for %s: %s", scenario_id, e)
    
    return reproducibility


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Run SimForge benchmark from a runspec file"
    )
    parser.add_argument(
        "runspec", type=str,
        help="Path to runspec YAML or JSON file"
    )
    parser.add_argument(
        "--scenario", "-s", type=str, default=None,
        help="Only run scenarios matching this ID"
    )
    parser.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Validate and show what would run without executing"
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="Override output directory"
    )
    parser.add_argument(
        "--mesoscopic", "-m", action="store_true",
        help="Use mesoscopic simulation mode (10-100x faster, less detailed)"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Show adapter INFO logs (default: WARNING and above only). "
             "Bar stays visible; logs routed above it."
    )

    args = parser.parse_args()

    # Quiet adapter INFO chatter by default — the per-cell summary lines are
    # enough for the operator. Same convention as run.py.
    if args.verbose:
        logging.basicConfig(level=logging.INFO, force=True)
    else:
        logging.basicConfig(level=logging.WARNING, force=True)
        for _name in ("adapters", "adapters.sumo", "adapters.matsim",
                      "adapters.dtalite", "adapters.common", "pipeline"):
            logging.getLogger(_name).setLevel(logging.WARNING)

    harness = BenchmarkHarness()
    if args.output:
        harness.output_base = Path(args.output)

    result = harness.run_benchmark(
        runspec_path=Path(args.runspec),
        scenario_filter=args.scenario,
        dry_run=args.dry_run,
        force_mesoscopic=args.mesoscopic,
        verbose=args.verbose,
    )
    
    # Print reproducibility analysis if we have successful runs
    if result.successful_runs > 0:
        repro = compute_reproducibility_from_results(result.results)
        if repro:
            print("\n📈 Reproducibility Analysis:")
            for scenario_id, metrics in repro.items():
                r_val = metrics['R_index']
                interp = metrics['interpretation']
                icon = "🟢" if r_val > 0.95 else "🟡" if r_val > 0.8 else "🔴"
                print(f"  {icon} {scenario_id}: R={r_val:.4f} ({interp})")
    
    if result.failed_runs > 0:
        print("\n❌ Failed runs:")
        for r in result.results:
            if r.status != "success":
                print(f"  • {r.scenario_id} seed={r.seed}: {r.error_message[:70]}...")
    
    # Exit with error code if any failures
    sys.exit(0 if result.failed_runs == 0 else 1)


if __name__ == "__main__":
    main()
