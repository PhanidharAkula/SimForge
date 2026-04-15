#!/usr/bin/env python3
"""Large full-day — 200K car+transit trips, Chicago, 24-hour."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate import generate_scenario

generate_scenario(
    city="chicago",
    trips=200_000,
    modes=["car", "transit"],
    start_time=0,
    end_time=86400,     # 24 hours
    radius_km=15.0,
    seed=42,
)
