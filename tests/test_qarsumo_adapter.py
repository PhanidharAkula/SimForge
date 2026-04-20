"""
Tests for the QarSUMO adapter.

QarSUMO reuses the SUMO inputs and extends the config with a `<qarsumo>`
GPU section. These tests cover the config extension and the prepare-inputs
path without requiring NVIDIA hardware (the adapter falls back to SUMO
on CPU-only hosts).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from adapters.qarsumo.qarsumo_adapter import (
    QarSUMOConfig,
    check_gpu_available,
    extend_config_for_qarsumo,
    get_gpu_info,
    prepare_qarsumo_inputs,
)

from .conftest import (
    is_arm64_netconvert_crash,
    is_large_scenario,
    warn_skipped,
)


# ---------------------------------------------------------------------------
# QarSUMOConfig
# ---------------------------------------------------------------------------


class TestQarSUMOConfig:
    def test_defaults(self):
        cfg = QarSUMOConfig()
        assert cfg.gpu_device == 0
        assert cfg.batch_size == 10000
        assert cfg.precision == "float32"

    def test_to_dict(self):
        cfg = QarSUMOConfig(gpu_device=1, batch_size=5000, precision="float16")
        d = cfg.to_dict()
        assert d["gpu_device"] == 1
        assert d["batch_size"] == 5000
        assert d["precision"] == "float16"

    def test_custom_config(self):
        cfg = QarSUMOConfig(
            stream_count=8, min_batch_threshold=50, max_pending_vehicles=100000
        )
        assert cfg.stream_count == 8
        assert cfg.min_batch_threshold == 50
        assert cfg.max_pending_vehicles == 100000


# ---------------------------------------------------------------------------
# GPU detection — must not crash on hosts without an NVIDIA card.
# ---------------------------------------------------------------------------


class TestGPUDetection:
    def test_check_gpu_returns_bool(self):
        assert isinstance(check_gpu_available(), bool)

    def test_get_gpu_info_returns_dict(self):
        info = get_gpu_info()
        assert isinstance(info, dict)
        for key in ("available", "count", "devices"):
            assert key in info
        assert isinstance(info["devices"], list)


# ---------------------------------------------------------------------------
# Config extension
# ---------------------------------------------------------------------------


class TestExtendConfig:
    def test_adds_qarsumo_section(self, tmp_path):
        cfg_content = """<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <input>
    <net-file value="net.net.xml" />
    <route-files value="routes.rou.xml" />
  </input>
</configuration>"""
        cfg_path = tmp_path / "toy.sumocfg"
        cfg_path.write_text(cfg_content, encoding="utf-8")

        result_path = extend_config_for_qarsumo(
            cfg_path, QarSUMOConfig(gpu_device=2, batch_size=20000)
        )
        assert result_path.is_file()
        assert result_path.name.startswith("qarsumo_")

        root = etree.parse(str(result_path)).getroot()
        qarsumo = root.find("qarsumo")
        assert qarsumo is not None, "Missing <qarsumo> section"
        assert qarsumo.find("gpu-device").get("value") == "2"
        assert qarsumo.find("batch-size").get("value") == "20000"

    def test_preserves_original_config(self, tmp_path):
        cfg_content = """<?xml version="1.0" encoding="UTF-8"?>
<configuration><input><net-file value="net.net.xml" /></input></configuration>"""
        cfg_path = tmp_path / "toy.sumocfg"
        cfg_path.write_text(cfg_content, encoding="utf-8")
        original = cfg_path.read_text()
        extend_config_for_qarsumo(cfg_path, QarSUMOConfig())
        assert cfg_path.read_text() == original


# ---------------------------------------------------------------------------
# Full prepare path
# ---------------------------------------------------------------------------


class TestPrepareQarSUMOInputs:
    def test_generates_sumo_plus_qarsumo_config(self, bundled_scenario, tmp_path):
        out = tmp_path / "qarsumo_out"
        config_path = prepare_qarsumo_inputs(bundled_scenario, out)
        assert config_path.is_file()
        assert "qarsumo_" in config_path.name
        for name in ("net.net.xml", "routes.rou.xml", "toy.sumocfg"):
            assert (out / name).is_file(), f"Missing base SUMO file: {name}"

    def test_qarsumo_config_has_gpu_settings(self, bundled_scenario, tmp_path):
        cfg = QarSUMOConfig(gpu_device=0, batch_size=8000, precision="float16")
        config_path = prepare_qarsumo_inputs(bundled_scenario, tmp_path / "qarsumo_gpu", qarsumo_config=cfg)
        qarsumo = etree.parse(str(config_path)).getroot().find("qarsumo")
        assert qarsumo is not None
        assert qarsumo.find("precision").get("value") == "float16"

    @pytest.mark.slow
    @pytest.mark.requires_sumo
    def test_all_scenarios(self, small_bundled_scenarios, tmp_path):
        if not small_bundled_scenarios:
            pytest.skip("No bundled scenarios to sweep")

        tested = 0
        skipped: list[str] = []
        for scenario_path in small_bundled_scenarios:
            if is_large_scenario(scenario_path.name):
                skipped.append(scenario_path.name)
                continue

            out = tmp_path / scenario_path.name
            try:
                config_path = prepare_qarsumo_inputs(scenario_path, out)
            except RuntimeError as e:
                if is_arm64_netconvert_crash(e):
                    skipped.append(scenario_path.name)
                    continue
                raise

            assert config_path.is_file(), f"{scenario_path.name}: no config generated"
            assert (out / "net.net.xml").is_file()
            tested += 1

        warn_skipped("QarSUMO sweep", skipped)
        assert tested > 0
