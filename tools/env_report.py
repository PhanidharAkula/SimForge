#!/usr/bin/env python3
"""
Print a complete toolchain + environment report.

Used to verify Mac<->Pitzer (or any cross-machine) parity after a venv rebuild,
dependency change, or fresh clone. Output is one block of text suitable for
side-by-side diff: run on each machine, paste both outputs, and any drift is
visible by inspection.

Usage:
    python tools/env_report.py
"""

from __future__ import annotations

import glob
import platform
import subprocess
import sys
from importlib import metadata


_PY_DEPS = (
    "osmnx", "numpy", "networkx", "lxml", "shapely",
    "geopandas", "pandas", "osmium", "matplotlib", "seaborn",
    "pyyaml", "pytest",
)

_EXTERNAL_BINS = (
    ("sumo",       ["sumo", "--version"]),
    ("netconvert", ["netconvert", "--version"]),
    ("java",       ["java", "--version"]),
)


def _module_version(mod_name: str) -> str:
    try:
        mod = __import__(mod_name)
    except ImportError:
        return "NOT INSTALLED"
    ver = getattr(mod, "__version__", "")
    if ver:
        return ver
    try:
        return metadata.version(mod_name)
    except metadata.PackageNotFoundError:
        return "unknown"


def _binary_version(cmd: list[str]) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "NOT FOUND"
    out = (result.stdout + result.stderr).strip()
    return out.split("\n")[0] if out else "(no output)"


def main() -> None:
    print("=" * 60)
    print(f"Python:     {platform.python_version()}")
    print(f"Platform:   {platform.system()} {platform.machine()}")
    print(f"Executable: {sys.executable}")
    print()
    print("--- Python deps (importable from current venv) ---")
    for mod in _PY_DEPS:
        print(f"  {mod:<12} {_module_version(mod)}")
    print()
    print("--- External tools (PATH-resolved) ---")
    for label, cmd in _EXTERNAL_BINS:
        print(f"  {label:<12} {_binary_version(cmd)}")
    print()
    print("--- Project files ---")
    # Skip -sources.jar / -javadoc.jar variants — those aren't runnable MATSim.
    matsim = sorted(
        p for p in glob.glob("lib/matsim-*/matsim-*.jar")
        if not p.endswith(("-sources.jar", "-javadoc.jar"))
    )
    print(f"  matsim jar:    {matsim[0] if matsim else 'NOT FOUND'}")
    print(f"  osm pbfs:      {len(glob.glob('osm_data/*.osm.pbf'))}")
    print(f"  modelgen txts: {len(glob.glob('modelgen/*.txt'))}")
    print(f"  scenarios:     {len(glob.glob('scenarios/*/'))}")
    print("=" * 60)


if __name__ == "__main__":
    main()
