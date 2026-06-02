"""
Command-line front end for the DTALite adapter.

Run it from the repo root:
    python -m adapters.dtalite.cli scenarios/chicago_1k_car out/dtalite
    python -m adapters.dtalite.cli scenarios/chicago_1k_car out/dtalite --run
"""

import argparse
import sys
from pathlib import Path

from adapters.dtalite.dtalite_adapter import (
    DTALiteConfig,
    find_dtalite_binary,
    is_dtalite_available,
    parse_dtalite_output,
    prepare_dtalite_inputs,
    run_dtalite,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DTALite Adapter — convert canonical bundles to GMNS inputs and run UE assignment"
    )
    parser.add_argument("scenario", help="Path to canonical scenario bundle")
    parser.add_argument("output", help="Output directory for generated GMNS files")
    parser.add_argument(
        "--run", action="store_true",
        help="Also run the assignment after generating inputs"
    )
    parser.add_argument(
        "--iterations", type=int, default=5,
        help="DTA outer iterations (default: 5)"
    )
    parser.add_argument(
        "--column-updating-iterations", type=int, default=5,
        help="Inner column-pool refinement iterations (default: 5)"
    )
    parser.add_argument(
        "--timeout", type=int, default=3600,
        help="Run timeout in seconds (default: 3600)"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed (DTALite is deterministic; included for harness parity)"
    )
    parser.add_argument(
        "--mesoscopic", action="store_true",
        help="Mesoscopic mode (default for DTALite; included for harness parity)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("DTALite Adapter")
    print("=" * 60)

    if is_dtalite_available():
        print(f"\n✓ DTALite binary: {find_dtalite_binary()}")
    else:
        print("\n⚠ path4gmns not installed.")
        print("  Install:  uv pip install path4gmns")
        print("  Mac dep:  brew install libomp")
        return 2

    print(f"\nScenario: {args.scenario}")
    print(f"Output:   {args.output}")

    config = DTALiteConfig(
        iterations=args.iterations,
        column_updating_iterations=args.column_updating_iterations,
    )

    print("\n--- Preparing inputs ---")
    try:
        summary = prepare_dtalite_inputs(Path(args.scenario), Path(args.output), config)
    except (FileNotFoundError, ValueError) as e:
        print(f"\n✗ prepare failed: {e}")
        return 1
    print(f"  Nodes:   {summary.node_count}")
    print(f"  Links:   {summary.link_count}")
    print(f"  Trips:   {summary.trip_count}")

    if not args.run:
        print("\nDone (use --run to also execute the assignment).")
        return 0

    print("\n--- Running DTALite (UE assignment) ---")
    ok, runtime, err = run_dtalite(
        Path(args.output),
        timeout_s=args.timeout,
        iterations=args.iterations,
        column_updating_iterations=args.column_updating_iterations,
    )
    print(f"  Result: {'OK' if ok else 'FAIL'} in {runtime:.1f}s")
    if err:
        print(f"  Error:  {err}")
        return 1

    print("\n--- Parsing output ---")
    stats = parse_dtalite_output(Path(args.output))
    if stats is None:
        print("  No agent.csv produced.")
        return 1
    print(f"  Trips (vehicle-equiv): {stats.trip_count}")
    print(f"  Completed:             {stats.completed_count}")
    print(f"  Mean travel time:      {stats.mean_travel_time_s:.1f} s "
          f"({stats.mean_travel_time_s/60:.1f} min)")
    print(f"  P95 travel time:       {stats.p95_travel_time_s:.1f} s "
          f"({stats.p95_travel_time_s/60:.1f} min)")
    print(f"  Mean distance:         {stats.mean_distance_m:.0f} m "
          f"({stats.mean_distance_m/1000:.2f} km)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
