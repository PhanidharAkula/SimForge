"""
Shared pytest fixtures and helpers for the SimForge test suite.

Centralises the scenario-discovery logic that was previously duplicated in
five different test files, plus the arm64 / large-scenario skip patterns and
the SHA-256 file-hashing utility used by the determinism tests.
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import warnings
from pathlib import Path
from typing import Iterable

import pytest


# ---------------------------------------------------------------------------
# Slow-test gating
# ---------------------------------------------------------------------------
# Tests marked ``@pytest.mark.slow`` run real engines (SUMO / MATSim / DTALite
# subprocesses) or per-trip BFS routing and take minutes each; a handful of
# them account for nearly the whole suite's wall time. They are skipped by
# default so the everyday ``pytest`` run stays fast (the unit suite). Pass
# ``--runslow`` to include them, which is the full pre-ship / CI gate:
#
#     pytest                 # fast: unit suite only
#     pytest --runslow       # full: everything, incl. the engine/BFS tests
#     pytest --runslow -m slow   # only the slow tests
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--runslow", action="store_true", default=False,
        help="run @pytest.mark.slow tests (real engine / BFS runs, minutes each)",
    )


def pytest_collection_modifyitems(config, items):
    run_slow = config.getoption("--runslow")
    skip_slow = pytest.mark.skip(reason="slow test; pass --runslow to run it")

    # Engine availability, probed once per collection. Tests marked
    # requires_sumo / requires_java previously relied on imperative checks
    # inside individual test bodies; the unchecked ones FAILED (instead of
    # skipping) whenever the engines were absent or the venv unactivated.
    # The probe is venv-aware so `.venv/bin/python -m pytest` without
    # `source .venv/bin/activate` still finds the eclipse-sumo wheel's
    # binaries next to the interpreter.
    from adapters.common.engine_binaries import find_engine_binary
    have_sumo = (find_engine_binary("sumo") is not None
                 and find_engine_binary("netconvert") is not None)
    have_java = shutil.which("java") is not None
    skip_no_sumo = pytest.mark.skip(
        reason="SUMO binaries (sumo/netconvert) not available; "
               "install eclipse-sumo via requirements.lock")
    skip_no_java = pytest.mark.skip(reason="Java runtime not available")

    for item in items:
        if not run_slow and "slow" in item.keywords:
            item.add_marker(skip_slow)
        if not have_sumo and "requires_sumo" in item.keywords:
            item.add_marker(skip_no_sumo)
        if not have_java and "requires_java" in item.keywords:
            item.add_marker(skip_no_java)


REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = REPO_ROOT / "scenarios"

# Scenarios bundled in the repo, in preference order. The first one that
# actually exists on disk becomes the default for single-scenario tests.
_BUNDLED_PREFERENCE = (
    "chicago_1k_car",
    "nyc_10k_car",
    "la_50k_car",
    "chicago_200k_car",
    "nyc_500k_car",
)

# Substring filename patterns identifying scenarios that are too large for the
# arm64 SUMO `netconvert` binary (segfaults above ~3000 nodes) or that take
# minutes per adapter run. Skip them in suite-wide adapter sweeps.
LARGE_SCENARIO_PATTERNS: tuple[str, ...] = ("50k", "200k", "500k", "5m")

# Required canonical files, a scenario directory missing any of these is
# treated as an orphan (e.g. iCloud half-sync) and excluded from discovery.
_REQUIRED_BUNDLE_FILES = ("manifest.xml", "network.xml", "demand.csv", "config.xml")


def _is_complete_bundle(path: Path) -> bool:
    return path.is_dir() and all((path / f).is_file() for f in _REQUIRED_BUNDLE_FILES)


def _discover_default_scenario() -> Path | None:
    if not SCENARIOS_DIR.is_dir():
        return None
    for name in _BUNDLED_PREFERENCE:
        candidate = SCENARIOS_DIR / name
        if _is_complete_bundle(candidate):
            return candidate
    for candidate in sorted(SCENARIOS_DIR.iterdir()):
        if _is_complete_bundle(candidate):
            return candidate
    return None


def _discover_all_scenarios() -> list[Path]:
    if not SCENARIOS_DIR.is_dir():
        return []
    return sorted(p for p in SCENARIOS_DIR.iterdir() if _is_complete_bundle(p))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def bundled_scenario() -> Path:
    """First available bundled scenario; skips the test if none exist.

    Replaces the per-file `_CANDIDATES` lookup that was duplicated across
    test_adapter_determinism, test_sumo_adapter, test_matsim_adapter,
    test_dtalite_adapter, test_validator, and test_pipeline_e2e.
    """
    s = _discover_default_scenario()
    if s is None:
        pytest.skip("No bundled scenario available — run scripts/01_chicago_1k_car.py first")
    return s


@pytest.fixture(scope="session")
def all_bundled_scenarios() -> list[Path]:
    """Every complete scenario bundle in scenarios/ (sorted by name)."""
    return _discover_all_scenarios()


@pytest.fixture(scope="session")
def small_bundled_scenarios(all_bundled_scenarios: list[Path]) -> list[Path]:
    """Bundled scenarios excluding ones that segfault arm64 netconvert."""
    return [s for s in all_bundled_scenarios if not _is_large(s.name)]


# ---------------------------------------------------------------------------
# Helpers exposed to test modules
# ---------------------------------------------------------------------------


def _is_large(scenario_name: str) -> bool:
    return any(p in scenario_name for p in LARGE_SCENARIO_PATTERNS)


def is_arm64_netconvert_crash(exc: BaseException) -> bool:
    """True if `exc` looks like a SUMO netconvert segfault on Apple Silicon.

    Requires `netconvert` to appear in the message so a generic adapter error
    whose text merely contains "failed" (e.g. "SUMO route generation failed")
    is NOT silently skipped on arm64; only a real netconvert crash/failure is.
    Both arm64 cases qualify: the SIGSEGV ("netconvert crashed with signal 11")
    and the non-zero "netconvert failed: Warning: Ambiguity ..." exit.
    """
    if platform.machine() != "arm64":
        return False
    text = str(exc).lower()
    return "netconvert" in text and any(
        token in text for token in ("failed", "crashed", "signal")
    )


def warn_skipped(prefix: str, names: Iterable[str]) -> None:
    """Emit a single UserWarning summarising scenarios skipped by a sweep."""
    names = list(names)
    if names:
        warnings.warn(f"{prefix}: skipped {len(names)} scenarios: {names}")


def file_sha256(path: Path) -> str:
    """SHA-256 hex digest of a file (8 KiB chunks)."""
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def directory_sha256(directory: Path, exclude_patterns: list[str] | None = None) -> dict[str, str]:
    """Map of relative-path → sha256 for every file in `directory`."""
    exclude_patterns = exclude_patterns or []
    out: dict[str, str] = {}
    for p in sorted(directory.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(directory)
        if any(pat in str(rel) for pat in exclude_patterns):
            continue
        out[str(rel)] = file_sha256(p)
    return out
