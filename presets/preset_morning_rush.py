#!/usr/bin/env python3
"""
Preset 2: Morning Rush
A realistic morning commute scenario for LA.

Config:
  City:    Los Angeles
  Trips:   50,000 car trips
  Time:    06:00–09:00 (3-hour morning peak)
  Radius:  10.0 km
  Demand:  Census (ModelGen)

Expected generation time: ~2 minutes
Expected SUMO meso runtime: ~15–30 seconds

Usage:
  python presets/preset_morning_rush.py
  python presets/preset_morning_rush.py --synthetic
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from generate import generate_scenario


def main():
    use_synthetic = "--synthetic" in sys.argv
    generate_scenario(
        city="la",
        trips=50_000,
        modes=["car"],
        start_time=21600,    # 6:00 AM
        end_time=32400,      # 9:00 AM
        radius_km=10.0,
        seed=42,
        scenario_id="preset_morning_rush",
        synthetic=use_synthetic,
    )


if __name__ == "__main__":
    main()
