"""
Tests for evaluation/analyze_benchmark.py — mode-aware grouping and the
identity-resolution fallback that prevent the silent R-score collapse fixed
in [1.0.0].

Regressions here would re-collapse SUMO meso and SUMO micro into a single
row, inflating combined std and crushing the published reproducibility
score from 0.998+ to 0.81.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.analyze_benchmark import (
    _resolve_identity,
    analyze_results,
    compute_reproducibility,
    generate_latex_table,
    generate_markdown_table,
    load_results,
    print_coverage_report,
    print_reproducibility_table,
    print_runtime_table,
    print_summary_table,
)


# ---------------------------------------------------------------------------
# _resolve_identity — explicit fields and string-parsed fallback
# ---------------------------------------------------------------------------


class TestResolveIdentity:
    def test_uses_explicit_fields(self):
        run = {"engine": "sumo", "scenario": "chicago_1k_car", "mode": "meso"}
        assert _resolve_identity(run) == ("chicago_1k_car", "sumo", "meso")

    def test_falls_back_to_scenario_id_for_meso(self):
        # Old-format runs only had scenario_id (e.g. "chicago_1k_car_sumo_meso").
        run = {"scenario_id": "chicago_1k_car_sumo_meso"}
        scenario, engine, mode = _resolve_identity(run)
        assert engine == "sumo"
        assert mode == "meso"
        assert scenario == "chicago_1k_car"

    def test_falls_back_to_scenario_id_for_micro(self):
        run = {"scenario_id": "nyc_1k_car_sumo_micro"}
        scenario, engine, mode = _resolve_identity(run)
        assert (engine, mode, scenario) == ("sumo", "micro", "nyc_1k_car")

    def test_falls_back_for_matsim(self):
        run = {"scenario_id": "chicago_1k_car_matsim_meso"}
        _, engine, mode = _resolve_identity(run)
        assert engine == "matsim"
        assert mode == "meso"

    def test_partial_explicit_fields_filled_from_id(self):
        # engine known, mode/scenario have to come from the id.
        run = {"engine": "sumo", "scenario_id": "chicago_1k_car_sumo_micro"}
        scenario, engine, mode = _resolve_identity(run)
        assert engine == "sumo"
        assert mode == "micro"
        assert scenario == "chicago_1k_car"


# ---------------------------------------------------------------------------
# compute_reproducibility — core R = 1 − σ/μ behaviour
# ---------------------------------------------------------------------------


class TestComputeReproducibility:
    def test_single_value_returns_one(self):
        assert compute_reproducibility([42.0]) == 1.0

    def test_identical_values_return_one(self):
        assert compute_reproducibility([10.0, 10.0, 10.0]) == 1.0

    def test_low_variance_yields_high_score(self):
        assert compute_reproducibility([100.0, 100.5, 99.5, 100.0]) > 0.99

    def test_high_variance_clamps_to_zero(self):
        # σ ≫ μ → CV > 1 → 1 − CV < 0 → clamped to 0.0
        assert compute_reproducibility([1.0, 100.0, 1.0, 100.0]) == 0.0

    def test_zero_mean_treated_as_reproducible(self):
        # All-zero is degenerate; the function returns 1.0 instead of NaN.
        assert compute_reproducibility([0.0, 0.0, 0.0]) == 1.0


# ---------------------------------------------------------------------------
# analyze_results — mode-aware grouping
# ---------------------------------------------------------------------------


def _run(scenario: str, engine: str, mode: str, runtime: float, tt: float, trips: int = 1000):
    return {
        "scenario": scenario,
        "engine": engine,
        "mode": mode,
        "runtime_s": runtime,
        "status": "success",
        "metrics": {"travel_time": {"trip_count": trips, "mean": tt}},
    }


class TestAnalyzeResults:
    def test_mode_keeps_meso_and_micro_separate(self):
        """Regression test for the [1.0.0] silent R-score collapse."""
        results = {"results": [
            _run("chicago_1k_car", "sumo", "meso", 0.30, 204.1),
            _run("chicago_1k_car", "sumo", "meso", 0.29, 204.0),
            _run("chicago_1k_car", "sumo", "micro", 1.10, 287.0),
            _run("chicago_1k_car", "sumo", "micro", 1.11, 287.5),
        ]}
        stats = analyze_results(results)
        # Two distinct rows, not one collapsed row.
        assert len(stats) == 2
        meso = next(s for s in stats if s.mode == "meso")
        micro = next(s for s in stats if s.mode == "micro")
        assert abs(meso.avg_travel_time - 204.05) < 0.1
        assert abs(micro.avg_travel_time - 287.25) < 0.1
        # If grouping had collapsed both modes, the combined std would push the
        # R-score below 0.85. Per-mode it must stay near 1.0.
        assert meso.reproducibility_score > 0.99
        assert micro.reproducibility_score > 0.99

    def test_records_failed_runs(self):
        results = {"results": [{
            "scenario": "x", "engine": "sumo", "mode": "meso",
            "status": "failed", "runtime_s": 0,
        }]}
        stats = analyze_results(results)
        assert len(stats) == 1
        assert stats[0].successes == 0
        assert stats[0].avg_runtime == 0
        assert stats[0].reproducibility_score == 0

    def test_filters_zero_travel_times(self):
        # A zero TT signals a metric-collection failure; it must not pull the
        # mean down or inflate variance.
        results = {"results": [
            _run("x", "sumo", "meso", 1.0, 200.0),
            _run("x", "sumo", "meso", 1.0, 0.0),       # bogus
            _run("x", "sumo", "meso", 1.0, 200.0),
        ]}
        stats = analyze_results(results)
        assert len(stats) == 1
        assert stats[0].avg_travel_time == 200.0
        assert stats[0].reproducibility_score == 1.0

    def test_accepts_runs_under_runs_key(self):
        # Older harness emitted "runs", newer emits "results"; both must work.
        results = {"runs": [_run("x", "sumo", "meso", 1.0, 200.0)]}
        stats = analyze_results(results)
        assert len(stats) == 1


# ---------------------------------------------------------------------------
# load_results
# ---------------------------------------------------------------------------


class TestLoadResults:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_results(tmp_path / "nope.json")

    def test_corrupt_json_raises(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="Failed to parse"):
            load_results(bad)

    def test_round_trip_through_disk(self, tmp_path):
        payload = {"results": [_run("x", "sumo", "meso", 1.0, 200.0)]}
        path = tmp_path / "ok.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_results(path)
        stats = analyze_results(loaded)
        assert len(stats) == 1


# ---------------------------------------------------------------------------
# Table / report renderers
#
# These are thin formatters, but they're what every thesis figure and table
# ultimately boils down to.  A crash here (f-string argument type change,
# missing column, KeyError in the aggregation loop) would bubble up as
# garbled output in the published PDF.  Cheap to test, high-signal.
# ---------------------------------------------------------------------------


class TestTableRenderers:

    @pytest.fixture
    def stats(self):
        results = {"results": [
            _run("chicago_1k_car", "sumo", "meso", 0.30, 204.1),
            _run("chicago_1k_car", "sumo", "meso", 0.29, 204.0),
            _run("chicago_1k_car", "sumo", "meso", 0.30, 204.2),
            _run("chicago_1k_car", "sumo", "micro", 1.10, 287.0),
            _run("chicago_1k_car", "sumo", "micro", 1.11, 287.5),
            _run("chicago_1k_car", "matsim", "meso", 2.50, 215.0),
            {"scenario": "nyc_1k_car", "engine": "sumo", "mode": "meso",
             "status": "failed", "runtime_s": 0},
        ]}
        return analyze_results(results)

    def test_runtime_table_contains_engines_and_modes(self, stats):
        out = print_runtime_table(stats)
        assert "Runtime Performance" in out
        assert "sumo" in out
        assert "meso" in out
        assert "micro" in out
        assert "matsim" in out
        assert "FAILED" in out  # the nyc_1k_car row was a fully-failed cell

    def test_reproducibility_table_rates_cells(self, stats):
        out = print_reproducibility_table(stats)
        # With three SUMO/meso runs differing by 0.2 s on a 204 s mean, the
        # R-score must land in "Excellent".
        assert "Excellent" in out
        assert "Reproducibility" in out

    def test_summary_table_aggregates_by_engine(self, stats):
        out = print_summary_table(stats)
        assert "Success Rate" in out
        assert "sumo" in out
        assert "matsim" in out

    def test_coverage_report_flags_low_sample_and_asymmetric(self, stats):
        """Our stats fixture has a SUMO/micro cell on chicago but not nyc —
        the coverage report must call that out as asymmetric."""
        out = print_coverage_report(stats)
        assert "COVERAGE DIAGNOSTIC" in out
        # nyc_1k_car is missing sumo/micro and matsim/meso relative to chicago.
        assert "Asymmetric" in out
        assert "nyc_1k_car" in out

    def test_coverage_report_flags_thin_cells(self):
        thin_stats = analyze_results({"results": [
            _run("x", "sumo", "meso", 1.0, 200.0),
            _run("x", "sumo", "meso", 1.0, 201.0),  # only 2 runs — thin
        ]})
        out = print_coverage_report(thin_stats)
        assert "Low-sample" in out or "n < 3" in out

    def test_latex_table_is_well_formed(self, stats):
        out = generate_latex_table(stats)
        assert out.count(r"\begin{table}") == 1
        assert out.count(r"\end{table}") == 1
        assert r"\toprule" in out
        assert r"\bottomrule" in out
        # Underscores in scenario names must be escaped to survive LaTeX.
        assert r"chicago\_1k\_car" in out

    def test_markdown_table_has_pipe_columns(self, stats):
        out = generate_markdown_table(stats)
        assert out.startswith("\n## Benchmark Results")
        header = next(line for line in out.splitlines() if line.startswith("| Scenario"))
        # Seven columns: Scenario | Engine | Mode | Runtime | Trips | Avg TT | R-Score
        assert header.count("|") == 8
