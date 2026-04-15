#!/usr/bin/env python3
"""Medium multi-modal — 50K trips (car+transit+bike), LA, 6–10 AM."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate import generate_scenario

generate_scenario(
    city="la",
    trips=50_000,
    modes=["car", "transit", "bike"],
    start_time=21600,   # 6:00 AM
    end_time=36000,     # 10:00 AM
    radius_km=10.0,
    seed=42,
)
