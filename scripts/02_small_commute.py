#!/usr/bin/env python3
"""Small commute — 10K car trips, NYC, 7–9 AM."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate import generate_scenario

generate_scenario(
    city="nyc",
    trips=10_000,
    modes=["car"],
    start_time=25200,   # 7:00 AM
    end_time=32400,     # 9:00 AM
    radius_km=4.0,
    seed=42,
)
