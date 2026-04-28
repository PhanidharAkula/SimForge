#!/usr/bin/env python3
"""Large full-day — 200K car+transit trips, Chicago, 24-hour.

Equivalent to: python generate.py --preset large_full_day
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
    trips=200_000,
    modes=["car", "transit"],
    start_time=0,
    end_time=86400,     # 24 hours
    radius_km=15.0,
    seed=42,
    verbose=args.verbose,
)
