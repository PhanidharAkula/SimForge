"""
Local SUMO execution runner for a canonical SimForge scenario.

Pipeline:

    1. Validate canonical bundle.
    2. Prepare SUMO inputs (net, routes, config) in the output directory.
    3. Invoke the local `sumo` binary with the generated config.
    4. Parse `tripinfo.xml` (if generated) and print travel-time metrics.

Requirements:

    - SUMO must be installed and `sumo` must be on your PATH.
      On macOS with Homebrew: `brew install sumo`
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from pipeline.validation.validate_bundle import validate_bundle
from adapters.sumo.sumo_adapter import prepare_sumo_inputs
from evaluation.metrics.travel_time import parse_sumo_tripinfo, TripTimeStats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run SUMO locally for a canonical SimForge scenario and compute trip metrics."
    )
    parser.add_argument(
        "scenario_root",
        type=str,
        help="Path to canonical scenario directory (e.g., scenarios/toy_2x2_grid)",
    )
    parser.add_argument(
        "output_dir",
        type=str,
        help="Directory where SUMO input/output files will be written",
    )

    args = parser.parse_args()

    scenario_root = Path(args.scenario_root).resolve()
    output_dir = Path(args.output_dir).resolve()

    # 1. Validate canonical bundle
    print(f"[RUN-SUMO] Validating canonical bundle at: {scenario_root}")
    ok = validate_bundle(scenario_root)
    if not ok:
        print("[RUN-SUMO] Validation FAILED. Aborting before SUMO adapter.")
        sys.exit(1)

    # 2. Prepare SUMO inputs
    print(f"[RUN-SUMO] Validation passed. Preparing SUMO inputs in: {output_dir}")
    summary = prepare_sumo_inputs(scenario_root, output_dir)

    print("[RUN-SUMO] SUMO inputs prepared.")
    print(f"  Scenario ID : {summary.scenario_id}")
    print(f"  Nodes       : {summary.node_count}")
    print(f"  Links       : {summary.link_count}")
    print(f"  Trips       : {summary.trip_count}")
    print(f"  Has signals : {summary.has_signals}")
    print(f"  Time horizon: {summary.start_time_s} -> {summary.end_time_s} seconds")

    # 3. Call SUMO
    cfg_path = output_dir / "toy.sumocfg"
    if not cfg_path.is_file():
        print(f"[RUN-SUMO] SUMO config not found at {cfg_path}, cannot run SUMO.")
        sys.exit(1)

    print(f"[RUN-SUMO] Running SUMO with config: {cfg_path}")
    try:
        # Run SUMO in the output directory so outputs (tripinfo.xml) land there
        subprocess.run(
            ["sumo", "-c", str(cfg_path.name)],
            cwd=output_dir,
            check=True,
        )
    except FileNotFoundError:
        print("[RUN-SUMO] Error: 'sumo' binary not found. "
              "Install SUMO and ensure it is on your PATH.")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"[RUN-SUMO] SUMO exited with non-zero status: {e}")
        sys.exit(1)

    # 4. Parse tripinfo metrics
    tripinfo_path = output_dir / "tripinfo.xml"
    if not tripinfo_path.is_file():
        print("[RUN-SUMO] SUMO completed, but no tripinfo.xml was found. "
              "Check your SUMO config/output settings.")
        sys.exit(1)

    print(f"[RUN-SUMO] Parsing tripinfo metrics from: {tripinfo_path}")
    try:
        stats: TripTimeStats = parse_sumo_tripinfo(tripinfo_path)
    except Exception as e:
        print(f"[RUN-SUMO] Failed to parse tripinfo metrics: {e}")
        sys.exit(1)

    print("[RUN-SUMO] Trip-level metrics:")
    print(f"  Completed trips         : {stats.trip_count}")
    print(f"  Mean travel time (s)    : {stats.mean_travel_time_s:.3f}")
    print(f"  95th pct travel time (s): {stats.p95_travel_time_s:.3f}")


if __name__ == "__main__":
    main()