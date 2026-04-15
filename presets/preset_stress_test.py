#!/usr/bin/env python3
"""
Preset 5: Stress Test
A large-scale benchmark for evaluating simulator performance limits.

Config:
  City:    Chicago
  Trips:   500,000 car trips
  Time:    06:00–10:00 (4-hour morning window)
  Radius:  20.0 km
  Demand:  Census (ModelGen)

Expected generation time: ~10–15 minutes
Expected SUMO meso runtime: ~5–15 minutes

Warning: This preset pushes close to the census data capacity (~500K car
         commuters for Chicago). If generation fails with an oversample
         error, re-run with --allow-oversample flag or use --synthetic.

Usage:
  python presets/preset_stress_test.py
  python presets/preset_stress_test.py --allow-oversample
  python presets/preset_stress_test.py --synthetic
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from generate import generate_scenario


def main():
    use_synthetic = "--synthetic" in sys.argv
    allow_oversample = "--allow-oversample" in sys.argv
    generate_scenario(
        city="chicago",
        trips=500_000,
        modes=["car"],
        start_time=21600,    # 6:00 AM
        end_time=36000,      # 10:00 AM
        radius_km=20.0,
        seed=42,
        scenario_id="preset_stress_test",
        synthetic=use_synthetic,
        allow_oversample=allow_oversample,
    )


if __name__ == "__main__":
    main()
