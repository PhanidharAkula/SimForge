"""
High-level runner for SUMO using a canonical SimForge scenario.

Pipeline (v0):

    1. Validate the canonical bundle using the validator.
    2. If valid, run the SUMO adapter to prepare SUMO input files.
    3. (Optional) If a tripinfo XML is present in the output directory, compute
       basic travel-time statistics.

NOTE:
    This script does NOT actually invoke the SUMO binary yet.
    Step (3) is a hook for when SUMO execution is wired in and configured to
    write tripinfo.xml into the same output directory.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pipeline.validation.validate_bundle import validate_bundle
from adapters.sumo.sumo_adapter import prepare_sumo_inputs
from evaluation.metrics.travel_time import parse_sumo_tripinfo, TripTimeStats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a canonical SimForge scenario, prepare SUMO inputs, and optionally compute metrics."
    )
    parser.add_argument(
        "scenario_root",
        type=str,
        help="Path to canonical scenario directory (e.g., scenarios/toy_2x2_grid)",
    )
    parser.add_argument(
        "output_dir",
        type=str,
        help="Directory where SUMO input files (and later outputs) will be written",
    )

    args = parser.parse_args()

    scenario_root = Path(args.scenario_root).resolve()
    output_dir = Path(args.output_dir).resolve()

    # 1. Validate canonical bundle
    print(f"[PIPELINE] Validating canonical bundle at: {scenario_root}")
    ok = validate_bundle(scenario_root)
    if not ok:
        print("[PIPELINE] Validation FAILED. Aborting before SUMO adapter.")
        sys.exit(1)

    # 2. Prepare SUMO inputs
    print(f"[PIPELINE] Validation passed. Preparing SUMO inputs in: {output_dir}")
    summary = prepare_sumo_inputs(scenario_root, output_dir)

    print("[PIPELINE] SUMO inputs prepared.")
    print(f"  Scenario ID : {summary.scenario_id}")
    print(f"  Nodes       : {summary.node_count}")
    print(f"  Links       : {summary.link_count}")
    print(f"  Trips       : {summary.trip_count}")
    print(f"  Has signals : {summary.has_signals}")
    print(f"  Time horizon: {summary.start_time_s} -> {summary.end_time_s} seconds")

    # 3. Optional evaluation stage (trip-level metrics)
    #
    # When SUMO is integrated, configure it to write a tripinfo file into
    # `output_dir` (e.g., output_dir / "tripinfo.xml") and this hook will
    # automatically compute aggregate metrics.
    tripinfo_path = output_dir / "tripinfo.xml"

    if tripinfo_path.is_file():
        print(f"[PIPELINE] Found tripinfo XML at: {tripinfo_path}")
        try:
            stats: TripTimeStats = parse_sumo_tripinfo(tripinfo_path)
        except Exception as e:
            print(f"[PIPELINE] Failed to parse tripinfo metrics: {e}")
        else:
            print("[PIPELINE] Trip-level metrics:")
            print(f"  Completed trips        : {stats.trip_count}")
            print(f"  Mean travel time (s)   : {stats.mean_travel_time_s:.3f}")
            print(f"  95th pct travel time (s): {stats.p95_travel_time_s:.3f}")
    else:
        print("[PIPELINE] No tripinfo.xml found in output directory; "
              "skip metrics (run SUMO to generate tripinfo output).")


if __name__ == "__main__":
    main()