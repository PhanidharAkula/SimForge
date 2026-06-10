"""Behavior tests for run.py (the quick interactive matrix runner).

run.py is the sibling of execution.run_benchmark: it has its own
run_sumo/run_simulation implementations rather than reusing the harness, so the
correctness guarantees the harness provides (per-cell failure isolation,
monotonic timing, never reporting a crashed engine as success) must hold here
too. These tests pin that parity so the two runners stay consistent.
"""

from __future__ import annotations

import importlib
from pathlib import Path


run = importlib.import_module("run")


class TestRunSimulationIsolation:
    def test_unknown_engine_is_failed_not_raise(self, tmp_path: Path):
        r = run.run_simulation("chicago_1k_car", "teleporter", "meso", 42, tmp_path, 5)
        assert r["status"] == "failed"
        assert "Unknown engine" in (r.get("error") or "")

    def test_missing_scenario_is_failed_not_raise(self, tmp_path: Path):
        # Adapter prep raises FileNotFoundError; run_simulation must catch it
        # (its handler is `except Exception`, not a narrow tuple) and return a
        # failed dict so the surrounding matrix loop keeps going.
        r = run.run_simulation("ghost_scenario_xyz", "dtalite", "meso", 42, tmp_path, 5)
        assert r["status"] == "failed"
        assert r.get("error")


class TestRunSumoTiming:
    def test_run_sumo_uses_monotonic_clock(self):
        # Engine duration is measured with a monotonic clock: time.time() can
        # jump on NTP steps or laptop sleep and corrupt the runtime table, so
        # the source must use a monotonic clock instead.
        import inspect
        src = inspect.getsource(run.run_sumo)
        assert "time.monotonic()" in src
        # Check the executable duration calls, not prose: neither the start
        # stamp nor the elapsed computation may use the non-monotonic clock.
        assert "= time.time()" not in src
        assert "time.time() -" not in src
