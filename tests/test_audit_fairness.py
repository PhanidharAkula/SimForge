"""
Tests for evaluation/audit_fairness.py, the post-benchmark cross-engine
fairness audit (Q1–Q4 checks).

We don't run the full audit_scenario flow against a real run directory
here (that's exercised manually after every benchmark via the canonical
post-run pipeline). Instead we cover:

  * Pure parser helpers (HMS→seconds, dtalite/matsim/sumo travel-time
    extraction, demand counting, XML/CSV element counts), synthetic
    fixtures, fully deterministic.
  * `_find_cell_dir`, the four output-layout detector that lets a single
    `audit_fairness <run-dir>` invocation work regardless of whether the
    run came from run.py (flat) or run_benchmark.py (nested) or a
    parallel-by-scenario sbatch wrapper (doubly-nested or per-scenario).
  * `_discover_scenarios`, directory-walking helper used by the CLI.
"""

from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

import pytest

from evaluation.audit_fairness import (
    _count_csv_rows,
    _count_dtalite_demand,
    _count_matsim_persons,
    _count_xml_elements,
    _discover_modes,
    _discover_scenarios,
    _dtalite_travel_times,
    _find_cell_dir,
    _hms_to_seconds,
    _matsim_travel_times,
    _sumo_travel_times,
    audit_scenario,
)


# ---------------------------------------------------------------------------
# HMS time helper
# ---------------------------------------------------------------------------


class TestHmsToSeconds:
    def test_zero(self):
        assert _hms_to_seconds("00:00:00") == 0

    def test_one_hour(self):
        assert _hms_to_seconds("01:00:00") == 3600

    def test_compound(self):
        # 1h 23m 45.5s
        assert _hms_to_seconds("01:23:45.5") == pytest.approx(5025.5)

    def test_garbage_returns_zero(self):
        # MATSim writes "0:0:0" for incomplete trips; nonsense → 0.0
        assert _hms_to_seconds("not a time") == 0.0

    def test_none_input_returns_zero(self):
        assert _hms_to_seconds(None) == 0.0


# ---------------------------------------------------------------------------
# Per-engine travel-time extractors
# ---------------------------------------------------------------------------


class TestSumoTravelTimes:
    def test_extracts_durations(self, tmp_path: Path):
        path = tmp_path / "tripinfo.xml"
        path.write_text(
            """<?xml version="1.0"?>
<tripinfos>
  <tripinfo id="t1" duration="100" />
  <tripinfo id="t2" duration="200" />
  <tripinfo id="t3" duration="300" />
</tripinfos>"""
        )
        assert _sumo_travel_times(path) == [100.0, 200.0, 300.0]

    def test_skips_zero_duration(self, tmp_path: Path):
        path = tmp_path / "tripinfo.xml"
        path.write_text(
            """<?xml version="1.0"?>
<tripinfos>
  <tripinfo id="t1" duration="100" />
  <tripinfo id="t2" duration="0" />
</tripinfos>"""
        )
        assert _sumo_travel_times(path) == [100.0]

    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert _sumo_travel_times(tmp_path / "nope.xml") == []

    def test_malformed_xml_returns_empty(self, tmp_path: Path):
        path = tmp_path / "broken.xml"
        path.write_text("<<not xml>>")
        assert _sumo_travel_times(path) == []


class TestMatsimTravelTimes:
    def _write_gz(self, path: Path, rows: list[dict[str, str]]) -> None:
        with gzip.open(path, "wt") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
            w.writeheader()
            w.writerows(rows)

    def test_extracts_hms_durations(self, tmp_path: Path):
        path = tmp_path / "trips.csv.gz"
        self._write_gz(path, [
            {"trav_time": "0:01:00"},  # 60s
            {"trav_time": "0:02:30"},  # 150s
            {"trav_time": "1:00:00"},  # 3600s
        ])
        assert _matsim_travel_times(path) == [60.0, 150.0, 3600.0]

    def test_drops_zero_duration_trips(self, tmp_path: Path):
        path = tmp_path / "trips.csv.gz"
        self._write_gz(path, [
            {"trav_time": "0:01:00"},
            {"trav_time": "0:00:00"},  # filtered out
        ])
        assert _matsim_travel_times(path) == [60.0]


class TestDtaliteTravelTimes:
    def test_minute_to_second_conversion_and_volume_expansion(self, tmp_path: Path):
        path = tmp_path / "agent.csv"
        with path.open("w") as f:
            w = csv.DictWriter(f, fieldnames=["travel_time", "volume"])
            w.writeheader()
            w.writerow({"travel_time": "5", "volume": "3"})    # 3 trips × 300s
            w.writerow({"travel_time": "10", "volume": "1"})   # 1 trip  × 600s
        # 5 min = 300s; volume=3 → 3 entries
        # 10 min = 600s; volume=1 → 1 entry
        assert sorted(_dtalite_travel_times(path)) == [300.0, 300.0, 300.0, 600.0]

    def test_skips_zero_travel_time(self, tmp_path: Path):
        path = tmp_path / "agent.csv"
        with path.open("w") as f:
            w = csv.DictWriter(f, fieldnames=["travel_time", "volume"])
            w.writeheader()
            w.writerow({"travel_time": "5", "volume": "1"})
            w.writerow({"travel_time": "0", "volume": "1"})  # filtered
        assert _dtalite_travel_times(path) == [300.0]


# ---------------------------------------------------------------------------
# Cheap counters
# ---------------------------------------------------------------------------


class TestCountHelpers:
    def test_count_dtalite_demand(self, tmp_path: Path):
        path = tmp_path / "demand.csv"
        with path.open("w") as f:
            w = csv.DictWriter(f, fieldnames=["o_zone_id", "d_zone_id", "volume"])
            w.writeheader()
            w.writerows([
                {"o_zone_id": "1", "d_zone_id": "2", "volume": "3"},
                {"o_zone_id": "2", "d_zone_id": "3", "volume": "5"},
                {"o_zone_id": "3", "d_zone_id": "1", "volume": "2"},
            ])
        pairs, vol = _count_dtalite_demand(path)
        assert pairs == 3
        assert vol == 10

    def test_count_dtalite_demand_skips_garbage_volume(self, tmp_path: Path):
        path = tmp_path / "demand.csv"
        with path.open("w") as f:
            w = csv.DictWriter(f, fieldnames=["o_zone_id", "d_zone_id", "volume"])
            w.writeheader()
            w.writerows([
                {"o_zone_id": "1", "d_zone_id": "2", "volume": "3"},
                {"o_zone_id": "2", "d_zone_id": "3", "volume": "n/a"},
            ])
        pairs, vol = _count_dtalite_demand(path)
        assert pairs == 2
        assert vol == 3

    def test_count_matsim_persons(self, tmp_path: Path):
        # V11.2+ MATSim adapter emits population_v6 (root <population>);
        # _count_matsim_persons just findall("person") on the root, so
        # it's root-tag-agnostic, but the fixture uses the production
        # root to stay aligned with what the adapter actually writes.
        path = tmp_path / "plans.xml"
        path.write_text(
            """<?xml version="1.0"?>
<population>
  <person id="1"/><person id="2"/><person id="3"/>
</population>"""
        )
        assert _count_matsim_persons(path) == 3

    def test_count_xml_elements(self, tmp_path: Path):
        path = tmp_path / "network.xml"
        path.write_text(
            """<?xml version="1.0"?>
<network>
  <nodes>
    <node id="a"/><node id="b"/><node id="c"/>
  </nodes>
  <links>
    <link id="L1"/><link id="L2"/>
  </links>
</network>"""
        )
        assert _count_xml_elements(path, "node") == 3
        assert _count_xml_elements(path, "link") == 2

    def test_count_csv_rows(self, tmp_path: Path):
        path = tmp_path / "x.csv"
        with path.open("w") as f:
            w = csv.DictWriter(f, fieldnames=["a", "b"])
            w.writeheader()
            w.writerows([{"a": "1", "b": "2"}, {"a": "3", "b": "4"}])
        assert _count_csv_rows(path) == 2


# ---------------------------------------------------------------------------
# _find_cell_dir, the 4-layout detector that's the whole reason
# audit_fairness.py works against both run.py and run_benchmark.py output.
# ---------------------------------------------------------------------------


class TestFindCellDir:
    def test_layout_a_flat_run_py(self, tmp_path: Path):
        """run.py: <base>/<scenario>_<engine>_<mode>_seed<N>/native_files/"""
        cell = tmp_path / "chicago_1k_car_sumo_meso_seed42" / "native_files"
        cell.mkdir(parents=True)
        assert _find_cell_dir(tmp_path, "chicago_1k_car", "sumo", 42) == cell

    def test_layout_b_nested_run_benchmark(self, tmp_path: Path):
        """run_benchmark.py: <base>/<scenario>/<engine>/seed_<N>/"""
        cell = tmp_path / "chicago_1k_car" / "matsim" / "seed_42"
        cell.mkdir(parents=True)
        assert _find_cell_dir(tmp_path, "chicago_1k_car", "matsim", 42) == cell

    def test_layout_c_doubly_nested_sbatch(self, tmp_path: Path):
        """sbatch parallel-by-scenario: <base>/<scenario>/<scenario>/<engine>/seed_<N>/"""
        cell = (
            tmp_path / "chicago_1k_car" / "chicago_1k_car" / "dtalite" / "seed_42"
        )
        cell.mkdir(parents=True)
        assert _find_cell_dir(tmp_path, "chicago_1k_car", "dtalite", 42) == cell

    def test_layout_d_per_scenario_worker_dir(self, tmp_path: Path):
        """Pointed at <runs>/<scenario>/: <base>/<engine>/seed_<N>/"""
        cell = tmp_path / "sumo" / "seed_42"
        cell.mkdir(parents=True)
        assert _find_cell_dir(tmp_path, "ignored_in_layout_d", "sumo", 42) == cell

    def test_returns_none_when_not_found(self, tmp_path: Path):
        assert _find_cell_dir(tmp_path, "missing", "sumo", 42) is None

    def test_seed_is_part_of_path(self, tmp_path: Path):
        """A run dir for seed=42 must NOT match a query for seed=43."""
        (tmp_path / "x" / "sumo" / "seed_42").mkdir(parents=True)
        assert _find_cell_dir(tmp_path, "x", "sumo", 42) is not None
        assert _find_cell_dir(tmp_path, "x", "sumo", 43) is None

    # -- Phase 12+ layout: mode segment in the path --

    def test_layout_b_phase12_meso_segmented(self, tmp_path: Path):
        """Phase 12+ layout B: <base>/<scenario>/<engine>/<mode>/seed_<N>/."""
        cell = tmp_path / "chicago_1k_car" / "sumo" / "meso" / "seed_42"
        cell.mkdir(parents=True)
        assert _find_cell_dir(tmp_path, "chicago_1k_car", "sumo", 42) == cell

    def test_layout_b_phase12_explicit_micro_mode(self, tmp_path: Path):
        """When both meso and micro exist, ``mode='micro'`` returns the micro dir."""
        meso = tmp_path / "nyc_10k_car" / "sumo" / "meso" / "seed_42"
        micro = tmp_path / "nyc_10k_car" / "sumo" / "micro" / "seed_42"
        meso.mkdir(parents=True)
        micro.mkdir(parents=True)
        assert _find_cell_dir(tmp_path, "nyc_10k_car", "sumo", 42, mode="meso") == meso
        assert _find_cell_dir(tmp_path, "nyc_10k_car", "sumo", 42, mode="micro") == micro

    def test_layout_d_phase12_per_scenario_with_mode(self, tmp_path: Path):
        """Phase 12+ layout D: <base>/<engine>/<mode>/seed_<N>/."""
        cell = tmp_path / "dtalite" / "meso" / "seed_42"
        cell.mkdir(parents=True)
        assert _find_cell_dir(tmp_path, "ignored", "dtalite", 42) == cell

    def test_back_compat_pre_phase12_layout_b(self, tmp_path: Path):
        """Pre-Phase-12 mode-less layout still found as a fallback."""
        cell = tmp_path / "chicago_1k_car" / "matsim" / "seed_42"
        cell.mkdir(parents=True)
        # Phase 12+ requested mode not on disk → falls back to mode-less layout.
        assert _find_cell_dir(tmp_path, "chicago_1k_car", "matsim", 42, mode="meso") == cell

    def test_phase12_preferred_over_legacy_when_both_exist(self, tmp_path: Path):
        """If both mode-less and mode-segmented dirs exist, Phase 12+ wins."""
        legacy = tmp_path / "x" / "sumo" / "seed_42"
        new = tmp_path / "x" / "sumo" / "meso" / "seed_42"
        legacy.mkdir(parents=True)
        new.mkdir(parents=True)
        assert _find_cell_dir(tmp_path, "x", "sumo", 42, mode="meso") == new


# ---------------------------------------------------------------------------
# _discover_scenarios
# ---------------------------------------------------------------------------


class TestDiscoverScenarios:
    def test_finds_layout_b_nested_run_benchmark(self, tmp_path: Path):
        """Layout B: <base>/<scenario>/<engine>/seed_<N>/."""
        for sc in ("nyc_1k_car", "chicago_1k_car", "la_50k_bike"):
            (tmp_path / sc / "sumo" / "seed_42").mkdir(parents=True)
        assert _discover_scenarios(tmp_path) == [
            "chicago_1k_car", "la_50k_bike", "nyc_1k_car"
        ]

    def test_finds_layout_a_flat_run_py(self, tmp_path: Path):
        """Layout A: <base>/<scenario>_<engine>_meso_seed<N>/."""
        (tmp_path / "chicago_1k_car_sumo_meso_seed42").mkdir()
        (tmp_path / "nyc_10k_car_matsim_meso_seed42").mkdir()
        assert _discover_scenarios(tmp_path) == ["chicago_1k_car", "nyc_10k_car"]

    def test_returns_empty_when_no_scenarios(self, tmp_path: Path):
        (tmp_path / "stray.txt").write_text("x")
        assert _discover_scenarios(tmp_path) == []

    def test_finds_layout_b_phase12_with_mode_segment(self, tmp_path: Path):
        """Phase 12+ layout B: <base>/<scenario>/<engine>/<mode>/seed_<N>/."""
        for sc in ("chicago_1k_car", "nyc_10k_car"):
            (tmp_path / sc / "sumo" / "meso" / "seed_42").mkdir(parents=True)
        assert _discover_scenarios(tmp_path) == ["chicago_1k_car", "nyc_10k_car"]

    def test_finds_layout_a_micro_seed(self, tmp_path: Path):
        """Layout A discovery now also recognises micro-mode flat dirs."""
        (tmp_path / "chicago_1k_car_sumo_micro_seed42").mkdir()
        assert _discover_scenarios(tmp_path) == ["chicago_1k_car"]


# ---------------------------------------------------------------------------
# _discover_modes, Phase 12+ helper that lets the orchestrator audit
# both meso and micro for the same (scenario, seed) tuple.
# ---------------------------------------------------------------------------


class TestDiscoverModes:
    def test_meso_only(self, tmp_path: Path):
        (tmp_path / "chicago_1k_car" / "matsim" / "meso" / "seed_42").mkdir(parents=True)
        assert _discover_modes(tmp_path, "chicago_1k_car") == ["meso"]

    def test_meso_and_micro(self, tmp_path: Path):
        (tmp_path / "nyc_10k_car" / "sumo" / "meso" / "seed_42").mkdir(parents=True)
        (tmp_path / "nyc_10k_car" / "sumo" / "micro" / "seed_42").mkdir(parents=True)
        assert _discover_modes(tmp_path, "nyc_10k_car") == ["meso", "micro"]

    def test_pre_phase12_layout_defaults_to_meso(self, tmp_path: Path):
        """Pre-Phase-12 mode-less dirs report as meso (mode unrecoverable)."""
        (tmp_path / "old_run" / "sumo" / "seed_42").mkdir(parents=True)
        assert _discover_modes(tmp_path, "old_run") == ["meso"]

    def test_no_cells_at_all_defaults_to_meso(self, tmp_path: Path):
        assert _discover_modes(tmp_path, "missing") == ["meso"]


# ---------------------------------------------------------------------------
# audit_scenario, orchestrator integration test against a synthetic run dir.
#
# Exercises the Q1-Q4 print path end-to-end on a layout-B run directory we
# build from scratch with realistic per-engine fixture files.
# ---------------------------------------------------------------------------


def _write_feasibility_report(path: Path) -> None:
    path.write_text(
        json.dumps({
            "feasible_trips": 995, "total_trips": 1000,
            "scc_nodes": 1850, "total_nodes": 1900,
            "scc_links": 4100, "total_links": 4250,
            "skipped_outside_scc": 5,
            "skipped_unknown_nodes": 0,
            "skipped_missing_fields": 0,
            "feasible_fraction": 0.995,
        })
    )


def _build_synthetic_run_dir(base: Path, scenario: str = "chicago_1k_car", seed: int = 42) -> None:
    """Build a layout-B run dir with realistic per-engine artefacts.

    Mirrors what `python -m execution.run_benchmark` would produce after a
    real run: feasibility_report.json + travel-time output for every engine,
    plus the network/demand fixtures audit_scenario reads to count Q2/Q3.
    """
    # SUMO cell
    sumo = base / scenario / "sumo" / f"seed_{seed}"
    sumo.mkdir(parents=True)
    _write_feasibility_report(sumo / "feasibility_report.json")
    (sumo / "ch.nod.xml").write_text(
        '<nodes><node id="a"/><node id="b"/></nodes>'
    )
    (sumo / "ch.edg.xml").write_text(
        '<edges><edge id="e1" from="a" to="b"/></edges>'
    )
    (sumo / "routes.rou.xml").write_text(
        '<routes><vehicle id="v1"/><vehicle id="v2"/></routes>'
    )
    (sumo / "tripinfo.xml").write_text(
        '<?xml version="1.0"?><tripinfos>'
        '<tripinfo id="t1" duration="100"/>'
        '<tripinfo id="t2" duration="200"/>'
        '</tripinfos>'
    )

    # MATSim cell
    matsim = base / scenario / "matsim" / f"seed_{seed}"
    matsim.mkdir(parents=True)
    _write_feasibility_report(matsim / "feasibility_report.json")
    (matsim / "network.xml").write_text(
        '<network><nodes><node id="a"/><node id="b"/></nodes>'
        '<links><link id="L1" from="a" to="b"/></links></network>'
    )
    (matsim / "plans.xml").write_text(
        '<population><person id="1"/><person id="2"/></population>'
    )
    output = matsim / "output"
    output.mkdir()
    import gzip as _gzip
    with _gzip.open(output / "output_trips.csv.gz", "wt") as f:
        f.write("trav_time\n0:01:30\n0:02:00\n")

    # DTALite cell
    dtalite = base / scenario / "dtalite" / f"seed_{seed}"
    dtalite.mkdir(parents=True)
    _write_feasibility_report(dtalite / "feasibility_report.json")
    with (dtalite / "node.csv").open("w") as f:
        f.write("node_id\na\nb\n")
    with (dtalite / "link.csv").open("w") as f:
        f.write("link_id,from,to\nL1,a,b\n")
    with (dtalite / "demand.csv").open("w") as f:
        f.write("o_zone_id,d_zone_id,volume\n1,2,5\n2,1,3\n")
    with (dtalite / "agent.csv").open("w") as f:
        f.write("travel_time,volume\n2.0,3\n3.0,2\n")


class TestAuditScenarioIntegration:
    def test_runs_clean_against_synthetic_dir(self, tmp_path: Path, capsys):
        _build_synthetic_run_dir(tmp_path)
        # No return value, we just need the orchestrator not to crash and
        # to print every Q1-Q4 section.
        audit_scenario(tmp_path, "chicago_1k_car", seed=42)
        out = capsys.readouterr().out
        assert "FAIRNESS AUDIT" in out
        assert "chicago_1k_car" in out
        assert "Q1: Same feasibility verdict" in out
        assert "Q2: Same network" in out
        assert "Q3: Are all engines actually simulating" in out
        assert "Q4: Cross-engine travel time" in out
        # Per-engine TT lines must reference all three engines.
        assert "sumo" in out
        assert "matsim" in out
        assert "dtalite" in out
        # Q1 verdicts should agree (same feasibility report copied to all 3 cells).
        assert "[PASS]" in out

    def test_returns_silently_when_no_cells(self, tmp_path: Path, capsys):
        audit_scenario(tmp_path, "missing_scenario", seed=42)
        out = capsys.readouterr().out
        assert "no cells found" in out
