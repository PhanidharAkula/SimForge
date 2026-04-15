#!/usr/bin/env python3
"""
Preset 3: Multimodal City
A multi-modal NYC scenario with car, transit, and bike trips.

Config:
  City:    New York City
  Trips:   20,000 (car + transit + bike)
  Time:    07:00–09:00 (2-hour morning window)
  Radius:  4.0 km
  Demand:  Census (ModelGen) — each trip gets the person's actual mode

Expected generation time: ~1 minute
Expected SUMO meso runtime: ~5–10 seconds (car trips only in SUMO)

Note: SUMO processes car trips. Transit/bike trips are included in the
      demand file for cross-simulator analysis (MATSim handles all modes).

Usage:
  python presets/preset_multimodal_city.py
  python presets/preset_multimodal_city.py --synthetic
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from generate import generate_scenario


def main():
    use_synthetic = "--synthetic" in sys.argv
    generate_scenario(
        city="nyc",
        trips=20_000,
        modes=["car", "transit", "bike"],
        start_time=25200,    # 7:00 AM
        end_time=32400,      # 9:00 AM
        radius_km=4.0,
        seed=42,
        scenario_id="preset_multimodal_city",
        synthetic=use_synthetic,
    )


if __name__ == "__main__":
    main()
