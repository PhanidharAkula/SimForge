"""
Tests for tools/generate_scorecard.py, the reproducibility-scorecard
emitter that summarizes provenance, environment, Q1 fairness, and R
per cell into a single Markdown artefact.

Strategy: build a tiny synthetic run dir (one results JSON + per-cell
feasibility_reports), call _render directly, assert the seven sections
land in the output with the expected verdicts. Pure-Python; no engine
invocation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.generate_scorecard import (
    _interpret_r,
    _q1_verdict,
    _r_per_cell,
    _render,
    _resolve_results_json,
)


# ---------------------------------------------------------------------------
# Helper: minimal run-dir fixture matching execution.run_benchmark layout B.
# ---------------------------------------------------------------------------


def _build_run_dir(tmp_path: Path, *, q1_drift: bool = False,
                   include_failures: bool = False) -> Path:
    """One scenario, three engines, two seeds. Layout B (Phase 12+)."""
    scenario = "synth_5_car"
    engines = ("sumo", "matsim", "dtalite")
    seeds = (42, 43)

    feasibility = {
        "feasible_trips": 5,
        "total_trips": 5,
        "scc_nodes": 100,
        "scc_links": 200,
        "skipped_outside_scc": 0,
        "skipped_unknown_nodes": 0,
        "skipped_missing_fields": 0,
        "skipped_unsupported_mode": 0,
        "supported_modes": ["car"],
    }

    results: list[dict] = []
    for engine in engines:
        for seed in seeds:
            cell = tmp_path / scenario / engine / "meso" / f"seed_{seed}"
            cell.mkdir(parents=True)
            cell_report = dict(feasibility)
            if q1_drift and engine == "dtalite":
                cell_report["feasible_trips"] = 4  # drift on purpose
            (cell / "feasibility_report.json").write_text(json.dumps(cell_report))

            # Two seeds with slightly different mean → R < 1 but > 0.99
            mean_tt = 100.0 if seed == 42 else 100.5
            results.append({
                "scenario": scenario,
                "scenario_id": f"{scenario}_{engine}_meso",
                "engine": engine,
                "mode": "meso",
                "seed": seed,
                "repeat": seed - 41,
                "status": "success",
                "runtime_s": 1.0,
                "wall_time_s": 1.0,
                "engine_wall_s": 1.0,
                "cell_wall_s": 1.0,
                "output_dir": str(cell),
                "tripinfo_path": None,
                "error_message": None,
                "metrics": {"travel_time": {"mean": mean_tt, "p95": mean_tt * 2,
                                            "trip_count": 5}},
            })

    if include_failures:
        results.append({
            "scenario": scenario,
            "scenario_id": f"{scenario}_sumo_meso",
            "engine": "sumo",
            "mode": "meso",
            "seed": 99,
            "repeat": 99,
            "status": "failed",
            "runtime_s": 0.0,
            "wall_time_s": 0.0,
            "engine_wall_s": 0.0,
            "cell_wall_s": 0.0,
            "output_dir": "",
            "tripinfo_path": None,
            "error_message": "synthetic failure for testing",
            "metrics": {},
        })

    payload = {
        "runspec_name": "synth_runspec",
        "started_at": "",
        "completed_at": "",
        "total_runs": len(results),
        "successful_runs": sum(1 for r in results if r["status"] == "success"),
        "failed_runs": sum(1 for r in results if r["status"] != "success"),
        "results": results,
        "summary": {"total": len(results),
                    "completed": sum(1 for r in results if r["status"] == "success"),
                    "failed": sum(1 for r in results if r["status"] != "success")},
    }
    results_path = tmp_path / "benchmark_results_synth_runspec.json"
    results_path.write_text(json.dumps(payload))
    return results_path


# ---------------------------------------------------------------------------
# Helper-function level
# ---------------------------------------------------------------------------


class TestInterpretR:
    def test_excellent(self):
        assert _interpret_r(0.995) == "EXCELLENT"

    def test_good(self):
        assert _interpret_r(0.96) == "GOOD"

    def test_acceptable(self):
        assert _interpret_r(0.85) == "ACCEPTABLE"

    def test_poor(self):
        assert _interpret_r(0.50) == "POOR"

    def test_none(self):
        assert _interpret_r(None) == "N/A"


class TestQ1Verdict:
    def test_all_equal_passes(self):
        base = {"feasible_trips": 5, "total_trips": 5, "scc_nodes": 10,
                "scc_links": 20, "skipped_outside_scc": 0,
                "skipped_unknown_nodes": 0, "skipped_missing_fields": 0,
                "skipped_unsupported_mode": 0}
        feas = {("sc", e, "meso"): dict(base) for e in ("sumo", "matsim", "dtalite")}
        assert _q1_verdict(feas) == {"sc": "PASS"}

    def test_drift_fails(self):
        base = {"feasible_trips": 5, "total_trips": 5, "scc_nodes": 10,
                "scc_links": 20, "skipped_outside_scc": 0,
                "skipped_unknown_nodes": 0, "skipped_missing_fields": 0,
                "skipped_unsupported_mode": 0}
        feas = {("sc", e, "meso"): dict(base) for e in ("sumo", "matsim")}
        feas[("sc", "dtalite", "meso")] = dict(base, feasible_trips=4)
        assert _q1_verdict(feas) == {"sc": "FAIL"}

    def test_single_engine_marked_na(self):
        feas = {("sc", "sumo", "meso"): {"feasible_trips": 5}}
        assert _q1_verdict(feas) == {"sc": "N/A (single engine)"}


class TestRPerCell:
    def test_singleton_returns_no_r(self):
        results = [{"scenario": "s", "engine": "sumo", "mode": "meso",
                    "status": "success",
                    "metrics": {"travel_time": {"mean": 100.0}}}]
        r = _r_per_cell(results)
        assert r[("s", "sumo", "meso")]["R"] is None
        assert r[("s", "sumo", "meso")]["n"] == 1

    def test_identical_values_yield_R_1(self):
        results = [{"scenario": "s", "engine": "sumo", "mode": "meso",
                    "status": "success",
                    "metrics": {"travel_time": {"mean": 100.0}}}
                   for _ in range(3)]
        r = _r_per_cell(results)[("s", "sumo", "meso")]
        assert r["n"] == 3
        assert r["R"] == pytest.approx(1.0)
        assert r["stdev_tt"] == 0.0

    def test_failed_runs_ignored(self):
        results = [
            {"scenario": "s", "engine": "sumo", "mode": "meso",
             "status": "success",
             "metrics": {"travel_time": {"mean": 100.0}}},
            {"scenario": "s", "engine": "sumo", "mode": "meso",
             "status": "failed",
             "metrics": {}},
        ]
        r = _r_per_cell(results)[("s", "sumo", "meso")]
        assert r["n"] == 1
        assert r["R"] is None


# ---------------------------------------------------------------------------
# End-to-end render
# ---------------------------------------------------------------------------


class TestRender:
    def test_seven_sections_present(self, tmp_path):
        results_json = _build_run_dir(tmp_path)
        md = _render(results_json)
        # Headings present
        for heading in ("# Reproducibility Scorecard",
                        "## 1. Provenance",
                        "## 2. Environment",
                        "## 3. Cross-engine fairness",
                        "## 4. Reproducibility R",
                        "## 5. Run summary",
                        "_Scorecard schema v1"):
            assert heading in md, f"missing section: {heading}"

    def test_q1_pass_when_engines_agree(self, tmp_path):
        results_json = _build_run_dir(tmp_path)
        md = _render(results_json)
        assert "| `synth_5_car` | `PASS` |" in md

    def test_q1_fail_when_engines_drift(self, tmp_path):
        results_json = _build_run_dir(tmp_path, q1_drift=True)
        md = _render(results_json)
        assert "| `synth_5_car` | `FAIL` |" in md
        assert "**Overall verdict: `FAIL" in md

    def test_failed_cells_table_emitted(self, tmp_path):
        results_json = _build_run_dir(tmp_path, include_failures=True)
        md = _render(results_json)
        assert "### Failed cells" in md
        assert "synthetic failure for testing" in md
        # Verdict should reflect partial-failure when fairness is OK
        assert "WARN" in md.split("**Overall verdict:")[1].split("**")[0]

    def test_overall_R_present(self, tmp_path):
        results_json = _build_run_dir(tmp_path)
        md = _render(results_json)
        assert "**Overall R" in md

    def test_provenance_records_git_head(self, tmp_path):
        # The generator runs inside the repo dir at test time, so git rev-parse
        # should succeed unless the test is being run from a non-repo cwd.
        # Either way the section must exist; the value can be 'unknown'.
        results_json = _build_run_dir(tmp_path)
        md = _render(results_json)
        assert "**Git HEAD:**" in md


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestResolveResultsJson:
    def test_direct_file(self, tmp_path):
        results_json = _build_run_dir(tmp_path)
        assert _resolve_results_json(results_json) == results_json

    def test_directory_finds_single_json(self, tmp_path):
        results_json = _build_run_dir(tmp_path)
        assert _resolve_results_json(tmp_path) == results_json

    def test_directory_no_json_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            _resolve_results_json(tmp_path)

    def test_directory_multiple_json_exits(self, tmp_path):
        _build_run_dir(tmp_path)
        # Add a second results JSON
        (tmp_path / "benchmark_results_other.json").write_text("{}")
        with pytest.raises(SystemExit):
            _resolve_results_json(tmp_path)

    def test_nonexistent_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            _resolve_results_json(tmp_path / "does-not-exist.json")
