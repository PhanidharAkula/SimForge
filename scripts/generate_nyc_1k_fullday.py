#!/usr/bin/env python3
"""Generate NYC 1K car trips, full 24-hour day."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate import generate_scenario

generate_scenario(
    city="nyc",
    trips=1_000,
    modes=["car"],
    start_time=0,        # midnight
    end_time=86400,      # 24 hours
    radius_km=1.5,       # smaller radius to avoid netconvert segfault on Apple Silicon
    seed=42,
)
