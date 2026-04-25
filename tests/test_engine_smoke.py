"""
Real-binary smoke tests for the SUMO, QarSUMO, and MATSim engines.

Every other test file exercises *adapter* code (input preparation, XML
structure, determinism).  This file goes one step further: it actually
invokes the engine binary on the smallest bundled scenario and asserts the
engine produced a non-empty results artefact.

The tests skip gracefully when the binary is missing so `pytest -m "not
slow"` stays green on developer machines without SUMO / Java / the MATSim
JAR installed.

These catch the class of regression where the adapter writes files the
engine refuses to parse (e.g. an attribute added/removed in a breaking
SUMO release) — something no amount of XML-structure assertions can see.
"""

from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from adapters.matsim.matsim_adapter import (
    check_java_available,
    find_matsim_jar,
    prepare_matsim_inputs,
    run_matsim,
)
from adapters.qarsumo.qarsumo_adapter import prepare_qarsumo_inputs
from adapters.sumo.sumo_adapter import prepare_sumo_inputs

from .conftest import is_arm64_netconvert_crash


# Short per-engine timeout — the 1k-trip scenario finishes in seconds; if it
# takes longer than this something is wrong, and we'd rather fail CI fast.
SUMO_TIMEOUT_S = 120
MATSIM_TIMEOUT_S = 600


# ---------------------------------------------------------------------------
# Skip helpers
# ---------------------------------------------------------------------------


def _have_sumo() -> bool:
    return shutil.which("sumo") is not None and shutil.which("netconvert") is not None


def _have_java_and_matsim() -> bool:
    ok, _ = check_java_available()
    return ok and find_matsim_jar() is not None


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# SUMO
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.requires_sumo
def test_sumo_real_binary_produces_tripinfo(bundled_scenario: Path, tmp_path: Path) -> None:
    """`sumo -c toy.sumocfg` writes non-empty tripinfo.xml with ≥1 tripinfo row."""
    if not _have_sumo():
        pytest.skip("SUMO binaries (sumo / netconvert) not on PATH")

    out = tmp_path / "sumo_run"
    try:
        prepare_sumo_inputs(bundled_scenario, out)
    except RuntimeError as exc:
        if is_arm64_netconvert_crash(exc):
            pytest.skip(f"arm64 netconvert crashed preparing {bundled_scenario.name}")
        raise

    cfg = out / "toy.sumocfg"
    assert cfg.is_file(), "adapter did not emit toy.sumocfg"

    result = subprocess.run(
        ["sumo", "-c", str(cfg), "--ignore-route-errors"],
        cwd=out,
        capture_output=True,
        text=True,
        timeout=SUMO_TIMEOUT_S,
        check=False,
    )
    assert result.returncode == 0, (
        f"sumo exited {result.returncode}\n"
        f"stderr (first 500 chars): {(result.stderr or '')[:500]}"
    )

    tripinfo = out / "tripinfo.xml"
    assert tripinfo.is_file(), "sumo ran cleanly but emitted no tripinfo.xml"
    root = ET.parse(tripinfo).getroot()
    rows = root.findall("tripinfo")
    assert rows, "tripinfo.xml has zero <tripinfo> rows — no vehicles completed"
    # A 1k-trip scenario should land the overwhelming majority; anything below
    # 50 % means the route file is broken in ways the adapter tests missed.
    assert len(rows) >= 50, f"only {len(rows)} trips completed — route file likely broken"


@pytest.mark.slow
@pytest.mark.requires_sumo
def test_qarsumo_real_binary_falls_back_to_sumo(bundled_scenario: Path, tmp_path: Path) -> None:
    """QarSUMO config is SUMO-compatible; the plain `sumo` binary must still run it.

    This is the documented fallback: QarSUMO-specific `<qarsumo>` extensions are
    ignored by stock SUMO so an adapter regression that breaks the `.sumocfg`
    itself would fail here even without a CUDA GPU."""
    if not _have_sumo():
        pytest.skip("SUMO binaries not on PATH")

    out = tmp_path / "qarsumo_run"
    try:
        prepare_qarsumo_inputs(bundled_scenario, out)
    except RuntimeError as exc:
        if is_arm64_netconvert_crash(exc):
            pytest.skip(f"arm64 netconvert crashed preparing {bundled_scenario.name}")
        raise

    cfgs = list(out.glob("*.sumocfg"))
    assert cfgs, "qarsumo adapter did not emit a .sumocfg"

    result = subprocess.run(
        ["sumo", "-c", str(cfgs[0]), "--ignore-route-errors"],
        cwd=out,
        capture_output=True,
        text=True,
        timeout=SUMO_TIMEOUT_S,
        check=False,
    )
    assert result.returncode == 0, (
        f"sumo rejected the QarSUMO-extended config: "
        f"stderr={result.stderr[:500]!r}"
    )


# ---------------------------------------------------------------------------
# MATSim
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.requires_java
def test_matsim_real_jar_produces_output_trips(bundled_scenario: Path, tmp_path: Path) -> None:
    """`java -jar matsim-15.0.jar ... config.xml` writes output_trips.csv.gz."""
    if not _have_java_and_matsim():
        pytest.skip("Java or MATSim JAR not available")

    out = tmp_path / "matsim_run"
    prepare_matsim_inputs(bundled_scenario, out, random_seed=42)

    cfg = out / "config.xml"
    assert cfg.is_file()

    success, runtime, error = run_matsim(cfg, timeout_s=MATSIM_TIMEOUT_S)
    assert success, f"MATSim failed after {runtime:.1f}s: {error}"

    output_dir = out / "output"
    assert output_dir.is_dir(), "MATSim produced no output/ directory"

    trips_file = output_dir / "output_trips.csv.gz"
    if not trips_file.is_file():
        trips_file = output_dir / "output_trips.csv"
    assert trips_file.is_file(), (
        f"MATSim ran but did not emit output_trips.csv[.gz] in {output_dir}"
    )
    assert trips_file.stat().st_size > 0, "output_trips file is empty"


# ---------------------------------------------------------------------------
# Availability report — always runs, always passes, just surfaces what's on
# the host.  Makes debugging CI/local skips instant.
# ---------------------------------------------------------------------------


def test_engine_availability_report() -> None:
    """Log which engines are available — helps debug skipped tests in CI."""
    sumo_present = _have_sumo()
    matsim_present = _have_java_and_matsim()
    # No assertion — this is a diagnostic.  We just want the test header to
    # show the binary availability for the running host.
    print(f"\n  SUMO:   {'available' if sumo_present else 'not installed'}")
    print(f"  MATSim: {'available' if matsim_present else 'not installed'}")
