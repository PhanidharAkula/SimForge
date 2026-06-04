"""Tests for tools/recover_partial_summary.py, Phase 12.5 + 12.6."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.recover_partial_summary import _parse_harness_log


# ---------------------------------------------------------------------------
# _parse_harness_log: harness cell-tape regex
# ---------------------------------------------------------------------------


SAMPLE_LOG = """\
============================================================
  SimForge Benchmark
============================================================

▶ la_50k_car
  [ 1/15]  sumo     meso  seed=42  ✓    92.6s wall  ( 92.1s engine)
  [ 2/15]  sumo     meso  seed=43  ✓    93.2s wall  ( 92.8s engine)
  [ 6/15]  matsim   meso  seed=42  ✓    55.5s wall  ( 55.1s engine)
  [11/15]  dtalite  meso  seed=42  ✗  FAIL  DTALite timeout after 3600s
  [12/15]  dtalite  meso  seed=43  ✗  FAIL  Adapter failed: SemLock error
something else
"""


@pytest.fixture
def log_file(tmp_path: Path) -> Path:
    p = tmp_path / "harness.log"
    p.write_text(SAMPLE_LOG, encoding="utf-8")
    return p


class TestParseHarnessLog:
    def test_parses_success_cells(self, log_file: Path) -> None:
        parsed = _parse_harness_log(log_file)
        assert ("sumo", "meso", 42) in parsed
        assert parsed[("sumo", "meso", 42)] == {
            "status": "success",
            "wall_s": 92.6,
            "engine_s": 92.1,
            "error_msg": None,
        }

    def test_parses_failure_cells_with_error_message(self, log_file: Path) -> None:
        parsed = _parse_harness_log(log_file)
        assert ("dtalite", "meso", 42) in parsed
        assert parsed[("dtalite", "meso", 42)]["status"] == "failed"
        assert parsed[("dtalite", "meso", 42)]["error_msg"] == "DTALite timeout after 3600s"
        # Failure cells have wall/engine = 0 (no timing was reported)
        assert parsed[("dtalite", "meso", 42)]["wall_s"] == 0.0
        assert parsed[("dtalite", "meso", 42)]["engine_s"] == 0.0

    def test_strips_FAIL_prefix_from_error(self, log_file: Path) -> None:
        parsed = _parse_harness_log(log_file)
        assert parsed[("dtalite", "meso", 43)]["error_msg"] == "Adapter failed: SemLock error"

    def test_count(self, log_file: Path) -> None:
        # Should ignore the unrelated "something else" line.
        assert len(_parse_harness_log(log_file)) == 5

    def test_missing_log_returns_empty_dict(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does_not_exist.log"
        assert _parse_harness_log(nonexistent) == {}

    def test_handles_alternate_seeds(self, tmp_path: Path) -> None:
        """Mixed-seed log (seeds 42, 43, 44) parsed correctly."""
        p = tmp_path / "log.txt"
        p.write_text(
            "  [ 1/3]  sumo     meso  seed=42  ✓    10.0s wall  (  9.0s engine)\n"
            "  [ 2/3]  sumo     meso  seed=43  ✓    11.0s wall  ( 10.0s engine)\n"
            "  [ 3/3]  sumo     meso  seed=44  ✓    12.0s wall  ( 11.0s engine)\n",
            encoding="utf-8",
        )
        parsed = _parse_harness_log(p)
        assert {k[2] for k in parsed.keys()} == {42, 43, 44}
        assert parsed[("sumo", "meso", 44)]["engine_s"] == 11.0
