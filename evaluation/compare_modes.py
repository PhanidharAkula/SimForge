"""
Compare microscopic vs mesoscopic simulation modes.

This script runs the same scenario in both modes and computes
fidelity metrics to quantify the accuracy-performance trade-off.

Usage:
    python -m evaluation.compare_modes scenarios/chicago_1k_car
    python -m evaluation.compare_modes scenarios/chicago_1k_car --seed 42
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass
class ModeResult:
    """Result from running a single mode."""
    mode: str  # "microscopic" or "mesoscopic"
    runtime_s: float
    success: bool
    trip_count: int
    mean_travel_time_s: float
    p95_travel_time_s: float
    error: Optional[str] = None


@dataclass
class ComparisonResult:
    """Comparison between microscopic and mesoscopic modes."""
    scenario_id: str
    seed: int
    microscopic: Optional[ModeResult]
    mesoscopic: Optional[ModeResult]
    
    # Fidelity metrics (if both modes succeeded)
    travel_time_rmse: Optional[float] = None
    travel_time_mape: Optional[float] = None  # Mean Absolute Percentage Error
    trip_count_diff: Optional[int] = None
    speedup_factor: Optional[float] = None
    
    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "microscopic": {
                "runtime_s": self.microscopic.runtime_s if self.microscopic else None,
                "success": self.microscopic.success if self.microscopic else False,
                "trip_count": self.microscopic.trip_count if self.microscopic else 0,
                "mean_travel_time_s": self.microscopic.mean_travel_time_s if self.microscopic else 0,
                "p95_travel_time_s": self.microscopic.p95_travel_time_s if self.microscopic else 0,
            } if self.microscopic else None,
            "mesoscopic": {
                "runtime_s": self.mesoscopic.runtime_s if self.mesoscopic else None,
                "success": self.mesoscopic.success if self.mesoscopic else False,
                "trip_count": self.mesoscopic.trip_count if self.mesoscopic else 0,
                "mean_travel_time_s": self.mesoscopic.mean_travel_time_s if self.mesoscopic else 0,
                "p95_travel_time_s": self.mesoscopic.p95_travel_time_s if self.mesoscopic else 0,
            } if self.mesoscopic else None,
            "comparison": {
                "travel_time_rmse": self.travel_time_rmse,
                "travel_time_mape_percent": self.travel_time_mape,
                "trip_count_diff": self.trip_count_diff,
                "speedup_factor": self.speedup_factor,
            }
        }
    
    def print_summary(self) -> None:
        """Print human-readable summary."""
        print("\n" + "=" * 60)
        print(f"MODE COMPARISON: {self.scenario_id}")
        print("=" * 60)
        
        if self.microscopic and self.microscopic.success:
            print(f"\n📊 MICROSCOPIC (accurate)")
            print(f"   Runtime:        {self.microscopic.runtime_s:.2f} s")
            print(f"   Trips completed: {self.microscopic.trip_count:,}")
            print(f"   Mean travel time: {self.microscopic.mean_travel_time_s:.2f} s")
            print(f"   P95 travel time:  {self.microscopic.p95_travel_time_s:.2f} s")
        elif self.microscopic:
            print(f"\n❌ MICROSCOPIC: Failed - {self.microscopic.error}")
        
        if self.mesoscopic and self.mesoscopic.success:
            print(f"\n⚡ MESOSCOPIC (fast)")
            print(f"   Runtime:        {self.mesoscopic.runtime_s:.2f} s")
            print(f"   Trips completed: {self.mesoscopic.trip_count:,}")
            print(f"   Mean travel time: {self.mesoscopic.mean_travel_time_s:.2f} s")
            print(f"   P95 travel time:  {self.mesoscopic.p95_travel_time_s:.2f} s")
        elif self.mesoscopic:
            print(f"\n❌ MESOSCOPIC: Failed - {self.mesoscopic.error}")
        
        if self.speedup_factor:
            print(f"\n📈 TRADE-OFF ANALYSIS")
            print(f"   Speedup factor:     {self.speedup_factor:.1f}x faster")
            print(f"   Trip count diff:    {self.trip_count_diff:+,} trips")
            print(f"   Travel time MAPE:   {self.travel_time_mape:.2f}%")
            print(f"   Travel time RMSE:   {self.travel_time_rmse:.2f} s")
        
        print("\n" + "=" * 60)


def run_mode(
    scenario_path: Path,
    output_dir: Path,
    seed: int,
    mesoscopic: bool,
    timeout_s: int = 14400  # 4 hours default
) -> ModeResult:
    """Run simulation in specified mode."""
    from adapters.sumo.sumo_adapter import prepare_sumo_inputs
    from evaluation.metrics.travel_time import parse_sumo_tripinfo
    
    mode_name = "mesoscopic" if mesoscopic else "microscopic"
    mode_dir = output_dir / mode_name
    mode_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Running {mode_name} mode...")
    
    # Prepare SUMO inputs
    try:
        summary = prepare_sumo_inputs(scenario_path, mode_dir)
        config_path = mode_dir / "toy.sumocfg"
    except Exception as e:
        return ModeResult(
            mode=mode_name,
            runtime_s=0,
            success=False,
            trip_count=0,
            mean_travel_time_s=0,
            p95_travel_time_s=0,
            error=str(e)
        )
    
    # Build SUMO command
    cmd = [
        "sumo", "-c", str(config_path.resolve()),
        "--seed", str(seed),
        "--ignore-route-errors"
    ]
    if mesoscopic:
        cmd.append("--mesosim")
    
    # Run SUMO
    import subprocess
    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=mode_dir
        )
        runtime = time.time() - start_time
        
        # SUMO returns non-zero for warnings; only fail on actual Error: lines
        # AND if tripinfo.xml is missing
        tripinfo_path = mode_dir / "tripinfo.xml"
        if result.returncode != 0:
            error_lines = [
                line for line in (result.stderr or "").split("\n")
                if line.strip().startswith("Error:")
            ]
            if error_lines and not tripinfo_path.exists():
                error_msg = "\n".join(error_lines[:3])
                return ModeResult(
                    mode=mode_name,
                    runtime_s=runtime,
                    success=False,
                    trip_count=0,
                    mean_travel_time_s=0,
                    p95_travel_time_s=0,
                    error=error_msg
                )
    except subprocess.TimeoutExpired:
        return ModeResult(
            mode=mode_name,
            runtime_s=timeout_s,
            success=False,
            trip_count=0,
            mean_travel_time_s=0,
            p95_travel_time_s=0,
            error=f"Timeout after {timeout_s}s"
        )
    
    # Parse results
    tripinfo_path = mode_dir / "tripinfo.xml"
    if tripinfo_path.exists():
        try:
            stats = parse_sumo_tripinfo(tripinfo_path)
            return ModeResult(
                mode=mode_name,
                runtime_s=runtime,
                success=True,
                trip_count=stats.trip_count,
                mean_travel_time_s=stats.mean_travel_time_s,
                p95_travel_time_s=stats.p95_travel_time_s
            )
        except Exception as e:
            return ModeResult(
                mode=mode_name,
                runtime_s=runtime,
                success=True,  # Simulation succeeded but parsing failed
                trip_count=0,
                mean_travel_time_s=0,
                p95_travel_time_s=0,
                error=f"Parse error: {e}"
            )
    else:
        return ModeResult(
            mode=mode_name,
            runtime_s=runtime,
            success=False,
            trip_count=0,
            mean_travel_time_s=0,
            p95_travel_time_s=0,
            error="No tripinfo.xml generated"
        )


def compare_modes(
    scenario_path: Path,
    output_dir: Path,
    seed: int = 42,
    run_microscopic: bool = True,
    run_mesoscopic: bool = True,
    micro_timeout_s: int = 14400,  # 4 hours
    meso_timeout_s: int = 3600     # 1 hour
) -> ComparisonResult:
    """Compare microscopic and mesoscopic modes."""
    scenario_id = scenario_path.name
    
    micro_result = None
    meso_result = None
    
    # Run mesoscopic first (faster, good sanity check)
    if run_mesoscopic:
        meso_result = run_mode(
            scenario_path, output_dir, seed,
            mesoscopic=True, timeout_s=meso_timeout_s
        )
    
    # Run microscopic
    if run_microscopic:
        micro_result = run_mode(
            scenario_path, output_dir, seed,
            mesoscopic=False, timeout_s=micro_timeout_s
        )
    
    # Compute comparison metrics
    result = ComparisonResult(
        scenario_id=scenario_id,
        seed=seed,
        microscopic=micro_result,
        mesoscopic=meso_result
    )
    
    if (micro_result and micro_result.success and 
        meso_result and meso_result.success):
        
        # Speedup factor
        if micro_result.runtime_s > 0:
            result.speedup_factor = micro_result.runtime_s / meso_result.runtime_s
        
        # Trip count difference
        result.trip_count_diff = meso_result.trip_count - micro_result.trip_count
        
        # Travel time comparison (MAPE and RMSE)
        if micro_result.mean_travel_time_s > 0:
            diff = abs(meso_result.mean_travel_time_s - micro_result.mean_travel_time_s)
            result.travel_time_mape = (diff / micro_result.mean_travel_time_s) * 100
            result.travel_time_rmse = diff  # Simplified RMSE (single value)
    
    return result


def main():
    parser = argparse.ArgumentParser(description="Compare simulation modes")
    parser.add_argument("scenario", type=Path, help="Path to scenario bundle")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--output", type=Path, default=Path("runs/mode_comparison"),
                        help="Output directory")
    parser.add_argument("--micro-only", action="store_true",
                        help="Only run microscopic mode")
    parser.add_argument("--meso-only", action="store_true",
                        help="Only run mesoscopic mode")
    parser.add_argument("--micro-timeout", type=int, default=14400,
                        help="Microscopic timeout in seconds (default: 4 hours)")
    parser.add_argument("--meso-timeout", type=int, default=3600,
                        help="Mesoscopic timeout in seconds (default: 1 hour)")
    parser.add_argument("--json", type=Path, help="Save results to JSON file")
    
    args = parser.parse_args()
    
    if not args.scenario.exists():
        logger.error(f"Scenario not found: {args.scenario}")
        sys.exit(1)
    
    run_micro = not args.meso_only
    run_meso = not args.micro_only
    
    result = compare_modes(
        scenario_path=args.scenario,
        output_dir=args.output,
        seed=args.seed,
        run_microscopic=run_micro,
        run_mesoscopic=run_meso,
        micro_timeout_s=args.micro_timeout,
        meso_timeout_s=args.meso_timeout
    )
    
    result.print_summary()
    
    # Save JSON if requested
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        with open(args.json, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
        logger.info(f"Results saved to: {args.json}")


if __name__ == "__main__":
    main()
