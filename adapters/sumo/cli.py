"""
Command-line interface for the SUMO adapter.

Usage (from repo root):
    python -m adapters.sumo.cli scenarios/toy_2x2_grid out/sumo_toy
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .sumo_adapter import prepare_sumo_inputs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare SUMO inputs from a SimForge canonical scenario bundle."
    )
    parser.add_argument(
        "scenario_root",
        type=str,
        help="Path to canonical scenario directory (e.g., scenarios/toy_2x2_grid)",
    )
    parser.add_argument(
        "output_dir",
        type=str,
        help="Directory where SUMO input files will be written (will be created if needed)",
    )

    args = parser.parse_args()

    scenario_root = Path(args.scenario_root)
    output_dir = Path(args.output_dir)

    summary = prepare_sumo_inputs(scenario_root, output_dir)

    print(f"[SUMO ADAPTER] Prepared SUMO inputs at: {output_dir.resolve()}")
    print(f"  Scenario ID : {summary.scenario_id}")
    print(f"  Nodes       : {summary.node_count}")
    print(f"  Links       : {summary.link_count}")
    print(f"  Trips       : {summary.trip_count}")
    print(f"  Has signals : {summary.has_signals}")
    print(f"  Time horizon: {summary.start_time_s} -> {summary.end_time_s} seconds")


if __name__ == "__main__":
    main()