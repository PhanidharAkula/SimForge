#!/usr/bin/env python3
"""
Preset 4: Full Day
A full 24-hour simulation for LA with 100K car trips.

Config:
  City:    Los Angeles
  Trips:   100,000 car trips
  Time:    00:00–24:00 (full day)
  Radius:  15.0 km
  Demand:  Census (ModelGen)

Expected generation time: ~3–5 minutes
Expected SUMO meso runtime: ~1–2 minutes

Usage:
  python presets/preset_full_day.py
  python presets/preset_full_day.py --synthetic
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from generate import generate_scenario


def main():
    use_synthetic = "--synthetic" in sys.argv
    generate_scenario(
        city="la",
        trips=100_000,
        modes=["car"],
        start_time=0,
        end_time=86400,      # 24 hours
        radius_km=15.0,
        seed=42,
        scenario_id="preset_full_day",
        synthetic=use_synthetic,
    )


if __name__ == "__main__":
    main()
