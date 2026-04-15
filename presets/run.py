#!/usr/bin/env python3
"""
Run a preset scenario by name.

Usage:
  python -m presets.run quick_test
  python -m presets.run morning_rush
  python -m presets.run multimodal_city
  python -m presets.run full_day
  python -m presets.run stress_test
  python -m presets.run --list
"""

import importlib
import sys
from pathlib import Path

PRESET_MAP = {
    "quick_test": "presets.preset_quick_test",
    "morning_rush": "presets.preset_morning_rush",
    "multimodal_city": "presets.preset_multimodal_city",
    "full_day": "presets.preset_full_day",
    "stress_test": "presets.preset_stress_test",
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("--list", "-l", "--help", "-h"):
        print("\nAvailable presets:")
        print("-" * 50)
        for name in PRESET_MAP:
            print(f"  {name}")
        print()
        print("Usage: python -m presets.run <preset_name>")
        print("       python -m presets.run <preset_name> --synthetic")
        return

    preset_name = sys.argv[1]
    if preset_name not in PRESET_MAP:
        print(f"Error: Unknown preset '{preset_name}'")
        print(f"Available: {', '.join(PRESET_MAP)}")
        sys.exit(1)

    # Pass remaining args through
    original_argv = sys.argv
    sys.argv = [sys.argv[0]] + sys.argv[2:]

    mod = importlib.import_module(PRESET_MAP[preset_name])
    mod.main()

    sys.argv = original_argv


if __name__ == "__main__":
    main()
