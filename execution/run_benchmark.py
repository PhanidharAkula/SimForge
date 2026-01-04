"""
Benchmark execution harness for SimForge.

Orchestrates:
1. Loading run specifications
2. Validating scenario bundles
3. Running adapters to generate engine inputs
4. Executing simulations
5. Collecting outputs and computing metrics

Usage:
    python -m execution.run_benchmark runspecs/benchmark_v1.yaml
    python -m execution.run_benchmark runspecs/benchmark_v1.yaml --dry-run
    python -m execution.run_benchmark runspecs/benchmark_v1.yaml --scenario toy_2x2_grid
"""

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import logging

from lxml import etree

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """Result of a single simulation run."""
    scenario_id: str
    engine: str
    seed: int
    repeat_index: int
    status: str  # "success", "failed", "timeout"
    runtime_s: float
    output_dir: Path
    tripinfo_path: Optional[Path] = None
    error_message: Optional[str] = None
    metrics: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "engine": self.engine,
            "seed": self.seed,
            "repeat_index": self.repeat_index,
            "status": self.status,
            "runtime_s": self.runtime_s,
            "output_dir": str(self.output_dir),
            "tripinfo_path": str(self.tripinfo_path) if self.tripinfo_path else None,
            "error_message": self.error_message,
            "metrics": self.metrics
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
    
    def to_dict(self) -> dict:
        return {
            "runspec_name": self.runspec_name,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_runs": self.total_runs,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "results": [r.to_dict() for r in self.results]
        }
    
    def save(self, path: Path) -> None:
        """Save results to JSON file."""
        with open(path, "w") as f:
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
                logger.error(f"Validation failed for {scenario_path}")
            return valid
        except Exception as e:
            logger.error(f"Validation error for {scenario_path}: {e}")
            return False
    
    def prepare_sumo_inputs(
        self,
        scenario_path: Path,
        output_dir: Path,
        seed: int
    ) -> dict:
        """Prepare SUMO inputs from canonical bundle."""
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
        
        logger.info(f"Running: {' '.join(cmd)}")
        
        start_time = time.time()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=config_path.parent
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
        except Exception as e:
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
            except Exception as e:
                logger.warning(f"Failed to parse tripinfo: {e}")
        
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
        
        # Create output directory
        run_dir = self.output_base / scenario_id / engine / f"seed_{seed}"
        run_dir.mkdir(parents=True, exist_ok=True)
        
        mode_str = " (mesoscopic)" if mesoscopic else ""
        logger.info(f"Starting run: {scenario_id} / {engine} / seed={seed}{mode_str}")
        
        # Currently only SUMO is supported
        if engine != "sumo":
            return RunResult(
                scenario_id=scenario_id,
                engine=engine,
                seed=seed,
                repeat_index=repeat_index,
                status="failed",
                runtime_s=0,
                output_dir=run_dir,
                error_message=f"Unsupported engine: {engine}"
            )
        
        # Prepare SUMO inputs
        try:
            self.prepare_sumo_inputs(scenario_path, run_dir, seed)
        except Exception as e:
            return RunResult(
                scenario_id=scenario_id,
                engine=engine,
                seed=seed,
                repeat_index=repeat_index,
                status="failed",
                runtime_s=0,
                output_dir=run_dir,
                error_message=f"Adapter failed: {e}"
            )
        
        # Find config file
        config_files = list(run_dir.glob("*.sumocfg"))
        if not config_files:
            return RunResult(
                scenario_id=scenario_id,
                engine=engine,
                seed=seed,
                repeat_index=repeat_index,
                status="failed",
                runtime_s=0,
                output_dir=run_dir,
                error_message="No .sumocfg file generated"
            )
        
        config_path = config_files[0]
        
        # Run SUMO
        success, runtime, error = self.run_sumo(config_path, timeout_s, seed, mesoscopic=mesoscopic)
        
        status = "success" if success else ("timeout" if "Timeout" in (error or "") else "failed")
        
        # Compute metrics if successful
        metrics = {}
        tripinfo_path = None
        if success:
            tripinfo_path = run_dir / "tripinfo.xml"
            if tripinfo_path.exists():
                metrics = self.compute_metrics(run_dir)
            else:
                tripinfo_path = None
        
        return RunResult(
            scenario_id=scenario_id,
            engine=engine,
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
        force_mesoscopic: bool = False
    ) -> BenchmarkResult:
        """
        Execute a full benchmark from a runspec file.
        
        Args:
            runspec_path: Path to runspec YAML/JSON
            scenario_filter: Only run scenarios matching this ID
            dry_run: If True, only validate and print what would run
            force_mesoscopic: If True, override runspec and use mesoscopic for all runs
        
        Returns:
            BenchmarkResult with all run results
        """
        from execution.runspec import RunSpec
        
        # Load runspec
        runspec = RunSpec.from_file(runspec_path)
        logger.info(f"Loaded runspec: {runspec.name}")
        logger.info(f"Description: {runspec.description}")
        if force_mesoscopic:
            logger.info("MESOSCOPIC MODE FORCED for all runs")
        
        # Set output base from runspec
        self.output_base = Path(runspec.global_output_dir)
        self.output_base.mkdir(parents=True, exist_ok=True)
        
        started_at = datetime.now(timezone.utc).isoformat()
        results = []
        
        # Filter runs if requested
        runs_to_execute = runspec.runs
        if scenario_filter:
            runs_to_execute = [r for r in runs_to_execute if r.scenario_id == scenario_filter]
            logger.info(f"Filtered to {len(runs_to_execute)} runs matching '{scenario_filter}'")
        
        # Count total runs
        total_runs = sum(r.repeats for r in runs_to_execute)
        logger.info(f"Total runs to execute: {total_runs}")
        
        if dry_run:
            logger.info("DRY RUN - no simulations will be executed")
            for run_config in runs_to_execute:
                scenario_path = Path(run_config.scenario_path)
                logger.info(f"\nWould run: {run_config.scenario_id}")
                logger.info(f"  Path: {scenario_path}")
                logger.info(f"  Engine: {run_config.engine}")
                logger.info(f"  Repeats: {run_config.repeats}")
                logger.info(f"  Seeds: {run_config.get_seeds()}")
                
                # Validate bundle
                valid = self.validate_bundle(scenario_path)
                logger.info(f"  Bundle valid: {valid}")
            
            return BenchmarkResult(
                runspec_name=runspec.name,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                total_runs=total_runs,
                successful_runs=0,
                failed_runs=0,
                results=[]
            )
        
        # Execute runs
        successful = 0
        failed = 0
        
        for run_config in runs_to_execute:
            scenario_path = Path(run_config.scenario_path)
            
            # Validate bundle
            if not self.validate_bundle(scenario_path):
                logger.error(f"Skipping {run_config.scenario_id} - validation failed")
                for i, seed in enumerate(run_config.get_seeds()):
                    results.append(RunResult(
                        scenario_id=run_config.scenario_id,
                        engine=run_config.engine,
                        seed=seed,
                        repeat_index=i,
                        status="failed",
                        runtime_s=0,
                        output_dir=self.output_base / run_config.scenario_id,
                        error_message="Bundle validation failed"
                    ))
                    failed += 1
                continue
            
            # Run each repeat
            seeds = run_config.get_seeds()
            mesoscopic = force_mesoscopic or getattr(run_config, 'mesoscopic', False)
            for i, seed in enumerate(seeds):
                result = self.run_single(
                    scenario_id=run_config.scenario_id,
                    scenario_path=scenario_path,
                    engine=run_config.engine,
                    seed=seed,
                    repeat_index=i,
                    timeout_s=run_config.timeout_s,
                    engine_options=run_config.engine_options,
                    mesoscopic=mesoscopic
                )
                results.append(result)
                
                if result.status == "success":
                    successful += 1
                    logger.info(f"✓ {run_config.scenario_id} seed={seed}: {result.runtime_s:.2f}s")
                else:
                    failed += 1
                    logger.error(f"✗ {run_config.scenario_id} seed={seed}: {result.error_message}")
        
        completed_at = datetime.now(timezone.utc).isoformat()
        
        benchmark_result = BenchmarkResult(
            runspec_name=runspec.name,
            started_at=started_at,
            completed_at=completed_at,
            total_runs=total_runs,
            successful_runs=successful,
            failed_runs=failed,
            results=results
        )
        
        # Save results
        results_path = self.output_base / f"benchmark_results_{runspec.name}.json"
        benchmark_result.save(results_path)
        logger.info(f"Results saved to: {results_path}")
        
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
        except Exception as e:
            logger.warning(f"Could not compute reproducibility for {scenario_id}: {e}")
    
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
    
    args = parser.parse_args()
    
    harness = BenchmarkHarness()
    if args.output:
        harness.output_base = Path(args.output)
    
    result = harness.run_benchmark(
        runspec_path=Path(args.runspec),
        scenario_filter=args.scenario,
        dry_run=args.dry_run,
        force_mesoscopic=args.mesoscopic
    )
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"Benchmark Complete: {result.runspec_name}")
    print(f"{'='*60}")
    print(f"Total runs: {result.total_runs}")
    print(f"Successful: {result.successful_runs}")
    print(f"Failed: {result.failed_runs}")
    
    if result.successful_runs > 0:
        # Compute reproducibility
        repro = compute_reproducibility_from_results(result.results)
        if repro:
            print(f"\nReproducibility Analysis:")
            for scenario_id, metrics in repro.items():
                print(f"  {scenario_id}: R={metrics['R_index']:.4f} ({metrics['interpretation']})")
    
    if result.failed_runs > 0:
        print(f"\nFailed runs:")
        for r in result.results:
            if r.status != "success":
                print(f"  - {r.scenario_id} seed={r.seed}: {r.error_message}")


if __name__ == "__main__":
    main()
