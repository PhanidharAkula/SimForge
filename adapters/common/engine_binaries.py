"""Locate engine executables, venv-aware.

The eclipse-sumo wheel installs the ``sumo`` / ``netconvert`` binaries into
the environment's own ``bin/`` directory (``Scripts/`` on Windows), right
next to the interpreter. ``shutil.which()`` only searches PATH, so an
unactivated invocation (``.venv/bin/python run.py``) misses them even though
they are siblings of the very interpreter that is running. Every PATH probe
for an engine binary should go through ``find_engine_binary`` so activated
and unactivated invocations behave the same.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional


def find_engine_binary(name: str) -> Optional[str]:
    """Return an absolute path to the executable ``name``, or None.

    Checks PATH first (activated venv, system install), then the directory
    containing the running interpreter (unactivated venv, where the
    eclipse-sumo wheel placed the binaries next to python itself).
    """
    found = shutil.which(name)
    if found:
        return found

    exe_dir = Path(sys.executable).parent
    for candidate in (exe_dir / name, exe_dir / f"{name}.exe"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None
