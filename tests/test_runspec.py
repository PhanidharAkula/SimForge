"""Unit coverage for the runspec schema: mode parsing, config validation,
seed generation, and YAML loading.

These tests exercise execution/runspec.py directly, verifying its schema
validation, mode parsing, and seed generation independently of the harness.
"""

import pytest

from execution.runspec import RunConfig, RunSpec, SimulationMode


# ---------------------------------------------------------------------------
# SimulationMode.from_string
# ---------------------------------------------------------------------------

class TestSimulationMode:
    @pytest.mark.parametrize("text", ["micro", "microscopic", "MICRO", "  Microscopic "])
    def test_microscopic_aliases(self, text):
        assert SimulationMode.from_string(text) == SimulationMode.MICROSCOPIC

    @pytest.mark.parametrize("text", ["meso", "mesoscopic", "MESO", "Mesoscopic"])
    def test_mesoscopic_aliases(self, text):
        assert SimulationMode.from_string(text) == SimulationMode.MESOSCOPIC

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            SimulationMode.from_string("warpspeed")


# ---------------------------------------------------------------------------
# RunConfig validation + seeds
# ---------------------------------------------------------------------------

class TestRunConfig:
    def _cfg(self, **kw):
        base = dict(scenario_id="s", scenario_path="p", engine="sumo")
        base.update(kw)
        return RunConfig(**base)

    def test_repeats_below_one_raises(self):
        with pytest.raises(ValueError):
            self._cfg(repeats=0)

    def test_timeout_below_one_raises(self):
        with pytest.raises(ValueError):
            self._cfg(timeout_s=0)

    def test_seed_increment_false_with_repeats_raises(self):
        # Running N repeats on a single fixed seed would fabricate reproducibility, so it is rejected.
        with pytest.raises(ValueError):
            self._cfg(repeats=5, seed_increment=False)

    def test_seed_increment_false_single_repeat_ok(self):
        # repeats=1 with a fixed seed is not contradictory.
        cfg = self._cfg(repeats=1, seed_increment=False)
        assert cfg.get_seeds() == [42]

    def test_get_seeds_incrementing(self):
        cfg = self._cfg(repeats=3, seed=42, seed_increment=True)
        assert cfg.get_seeds() == [42, 43, 44]

    def test_is_mesoscopic_property(self):
        assert self._cfg(mode=SimulationMode.MESOSCOPIC).is_mesoscopic is True
        assert self._cfg(mode=SimulationMode.MICROSCOPIC).is_mesoscopic is False


# ---------------------------------------------------------------------------
# RunSpec parsing
# ---------------------------------------------------------------------------

class TestRunSpec:
    def _data(self, **run_overrides):
        run = dict(scenario_id="chicago_1k_car", scenario_path="scenarios/chicago_1k_car",
                   engine="sumo", repeats=2, seed=42, mode="mesoscopic")
        run.update(run_overrides)
        return {"name": "t", "description": "d", "output_dir": "runs", "runs": [run]}

    def test_from_dict_basic(self, tmp_path):
        spec = RunSpec._from_dict(self._data(), tmp_path / "t.yaml")
        assert spec.name == "t"
        assert len(spec.runs) == 1
        assert spec.runs[0].engine == "sumo"
        assert spec.runs[0].is_mesoscopic

    def test_missing_engine_raises(self, tmp_path):
        data = self._data()
        del data["runs"][0]["engine"]
        with pytest.raises(ValueError):
            RunSpec._from_dict(data, tmp_path / "t.yaml")

    def test_missing_scenario_id_raises(self, tmp_path):
        data = self._data()
        del data["runs"][0]["scenario_id"]
        with pytest.raises(ValueError):
            RunSpec._from_dict(data, tmp_path / "t.yaml")

    def test_unknown_engine_raises(self, tmp_path):
        with pytest.raises(ValueError):
            RunSpec._from_dict(self._data(engine="teleporter"), tmp_path / "t.yaml")

    def test_empty_runs_raises(self, tmp_path):
        with pytest.raises(ValueError):
            RunSpec._from_dict({"name": "t", "runs": []}, tmp_path / "t.yaml")

    def test_from_yaml_round_trip(self, tmp_path):
        import yaml
        path = tmp_path / "spec.yaml"
        path.write_text(yaml.safe_dump(self._data()))
        spec = RunSpec.from_yaml(path)
        assert spec.name == "t"
        assert spec.runs[0].get_seeds() == [42, 43]

    def test_from_yaml_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            RunSpec.from_yaml(tmp_path / "nope.yaml")

    def test_from_file_unknown_suffix_raises(self, tmp_path):
        with pytest.raises(ValueError):
            RunSpec.from_file(tmp_path / "spec.toml")
