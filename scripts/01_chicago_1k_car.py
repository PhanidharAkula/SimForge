#!/usr/bin/env python3
"""chicago_1k_car — 1K car trips, Chicago, 7–8 AM (smallest tier; test fixture).

Equivalent to: python generate.py --preset chicago_1k_car
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
    city="chicago",
    trips=1_000,
    modes=["car"],
    start_time=25200,   # 7:00 AM
    end_time=28800,     # 8:00 AM
    radius_km=2.0,
    seed=42,
    verbose=args.verbose,
)
