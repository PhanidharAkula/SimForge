#!/usr/bin/env python3
"""Stress test — 500K car trips, NYC, 6–10 AM."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate import generate_scenario

generate_scenario(
    city="nyc",
    trips=500_000,
    modes=["car"],
    start_time=21600,   # 6:00 AM
    end_time=36000,     # 10:00 AM
    radius_km=20.0,
    seed=42,
)
