#!/usr/bin/env python3
"""nyc_500k_car — 500K car trips, NYC, 6–10 AM (largest tier; HPC scale).

Equivalent to: python generate.py --preset nyc_500k_car
Same generate_scenario() call; the preset form additionally accepts
--seed / --output / --city / OSM source overrides.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate import generate_scenario

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--verbose", "-v", action="store_true",
                    help="Show pipeline INFO logs above the progress bar")
args = parser.parse_args()

generate_scenario(
    city="nyc",
    trips=500_000,
    modes=["car"],
    start_time=21600,   # 6:00 AM
    end_time=36000,     # 10:00 AM
    radius_km=20.0,
    seed=42,
    verbose=args.verbose,
)
