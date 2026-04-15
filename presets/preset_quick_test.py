#!/usr/bin/env python3
"""
Preset 1: Quick Test
A minimal scenario for rapid validation and development.

Config:
  City:    Chicago
  Trips:   1,000 car trips
  Time:    00:00–00:30 (30-minute window)
  Radius:  2.0 km
  Demand:  Census (ModelGen)

Expected generation time: ~15 seconds
Expected SUMO meso runtime: <1 second

Usage:
  python presets/preset_quick_test.py
  python presets/preset_quick_test.py --synthetic    # force synthetic demand
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from generate import generate_scenario


def main():
    use_synthetic = "--synthetic" in sys.argv
    generate_scenario(
        city="chicago",
        trips=1_000,
        modes=["car"],
        start_time=0,
        end_time=1800,
        radius_km=2.0,
        seed=42,
        scenario_id="preset_quick_test",
        synthetic=use_synthetic,
    )


if __name__ == "__main__":
    main()
