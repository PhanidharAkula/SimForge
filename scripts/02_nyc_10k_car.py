#!/usr/bin/env python3
"""nyc_10k_car: 10K car trips, NYC, 7–9 AM.

Equivalent to: python generate.py --preset nyc_10k_car
Same generate_scenario() call; the preset form additionally accepts
--seed / --output / --city / OSM source overrides.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate import generate_scenario

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show pipeline INFO logs above the progress bar")
    args = parser.parse_args()

    generate_scenario(
        city="nyc",
        trips=10_000,
        modes=["car"],
        start_time=25200,   # 7:00 AM
        end_time=32400,     # 9:00 AM
        radius_km=4.0,
        seed=42,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
