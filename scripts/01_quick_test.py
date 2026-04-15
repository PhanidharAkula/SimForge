#!/usr/bin/env python3
"""Quick test — 1K car trips, Chicago, 7–8 AM."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate import generate_scenario

generate_scenario(
    city="chicago",
    trips=1_000,
    modes=["car"],
    start_time=25200,   # 7:00 AM
    end_time=28800,     # 8:00 AM
    radius_km=2.0,
    seed=42,
)
