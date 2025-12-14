"""
High-level runner for SUMO using a canonical SimForge scenario.

Pipeline (v0):

    1. Validate the canonical bundle using the validator.
    2. If valid, run the SUMO adapter to prepare SUMO input files.

This does NOT actually call the SUMO binary yet.
That will be added once the SUMO conversion is fully implemented.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pipeline.validation.validate_bundle import validate_bundle
from adapters.sumo.sumo_adapter import prepare_sumo_inputs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a canonical SimForge scenario and prepare SUMO inputs."
    )
    parser.add_argument(
        "scenario_root",
        type=str,
        help="Path to canonical scenario directory (e.g., scenarios/toy_2x2_grid)",
    )
    parser.add_argument(
        "output_dir",
        type=str,
        help="Directory where SUMO input files will be written",
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


if __name__ == "__main__":
    main()