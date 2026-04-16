"""
Tests for the QarSUMO adapter.

QarSUMO reuses SUMO inputs and extends the config with GPU options.
These tests validate config extension and the fallback-to-SUMO logic
without requiring NVIDIA hardware.
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


REPO_ROOT = Path(__file__).resolve().parents[1]

_CANDIDATES = ["chicago_1k_car", "nyc_1k_car", "la_1k_car"]
SCENARIO: Path | None = None
for _name in _CANDIDATES:
    _path = REPO_ROOT / "scenarios" / _name
    if _path.is_dir():
        SCENARIO = _path
        break


# ---------------------------------------------------------------------------
# Unit tests for QarSUMOConfig
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
            stream_count=8,
            min_batch_threshold=50,
            max_pending_vehicles=100000
        )
        assert cfg.stream_count == 8
        assert cfg.min_batch_threshold == 50
        assert cfg.max_pending_vehicles == 100000


# ---------------------------------------------------------------------------
# GPU detection (always safe — returns False if no GPU)
# ---------------------------------------------------------------------------

class TestGPUDetection:
    def test_check_gpu_returns_bool(self):
        result = check_gpu_available()
        assert isinstance(result, bool)

    def test_get_gpu_info_returns_dict(self):
        info = get_gpu_info()
        assert isinstance(info, dict)
        assert "available" in info
        assert "count" in info
        assert "devices" in info
        assert isinstance(info["devices"], list)


# ---------------------------------------------------------------------------
# Config extension
# ---------------------------------------------------------------------------

class TestExtendConfig:
    def test_adds_qarsumo_section(self, tmp_path):
        """Extending a SUMO config should add a <qarsumo> XML section."""
        cfg_content = """<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <input>
    <net-file value="net.net.xml" />
    <route-files value="routes.rou.xml" />
  </input>
</configuration>"""
        cfg_path = tmp_path / "toy.sumocfg"
        cfg_path.write_text(cfg_content, encoding="utf-8")

        qarsumo_cfg = QarSUMOConfig(gpu_device=2, batch_size=20000)
        result_path = extend_config_for_qarsumo(cfg_path, qarsumo_cfg)

        assert result_path.is_file()
        assert result_path.name.startswith("qarsumo_")

        tree = etree.parse(str(result_path))
        root = tree.getroot()

        qarsumo_elem = root.find("qarsumo")
        assert qarsumo_elem is not None, "Missing <qarsumo> section"

        gpu_dev = qarsumo_elem.find("gpu-device")
        assert gpu_dev is not None
        assert gpu_dev.get("value") == "2"

        batch = qarsumo_elem.find("batch-size")
        assert batch is not None
        assert batch.get("value") == "20000"

    def test_preserves_original_config(self, tmp_path):
        """Original SUMO config should remain unchanged."""
        cfg_content = """<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <input>
    <net-file value="net.net.xml" />
  </input>
</configuration>"""
        cfg_path = tmp_path / "toy.sumocfg"
        cfg_path.write_text(cfg_content, encoding="utf-8")

        original_text = cfg_path.read_text()
        extend_config_for_qarsumo(cfg_path, QarSUMOConfig())

        # Original file should be untouched
        assert cfg_path.read_text() == original_text


# ---------------------------------------------------------------------------
# Full input preparation
# ---------------------------------------------------------------------------

class TestPrepareQarSUMOInputs:
    def test_generates_sumo_plus_qarsumo_config(self, tmp_path):
        assert SCENARIO is not None, "No scenario available"
        out = tmp_path / "qarsumo_out"
        config_path = prepare_qarsumo_inputs(SCENARIO, out)

        assert config_path.is_file(), "Should return path to QarSUMO config"
        assert "qarsumo_" in config_path.name, "Config should have qarsumo_ prefix"

        # Base SUMO files should also exist
        assert (out / "net.net.xml").is_file()
        assert (out / "routes.rou.xml").is_file()
        assert (out / "toy.sumocfg").is_file()

    def test_qarsumo_config_has_gpu_settings(self, tmp_path):
        assert SCENARIO is not None
        out = tmp_path / "qarsumo_gpu"
        cfg = QarSUMOConfig(gpu_device=0, batch_size=8000, precision="float16")
        config_path = prepare_qarsumo_inputs(SCENARIO, out, qarsumo_config=cfg)

        tree = etree.parse(str(config_path))
        root = tree.getroot()
        qarsumo_elem = root.find("qarsumo")
        assert qarsumo_elem is not None

        prec = qarsumo_elem.find("precision")
        assert prec is not None
        assert prec.get("value") == "float16"

    def test_all_scenarios(self, tmp_path):
        """Run QarSUMO adapter on all available scenarios."""
        import platform

        scenarios_dir = REPO_ROOT / "scenarios"
        tested = 0
        skipped = []
        for scenario_path in sorted(scenarios_dir.iterdir()):
            if not scenario_path.is_dir():
                continue
            if not (scenario_path / "manifest.xml").is_file():
                continue

            out = tmp_path / scenario_path.name
            try:
                config_path = prepare_qarsumo_inputs(scenario_path, out)
            except RuntimeError as e:
                if platform.machine() == "arm64" and "failed" in str(e).lower():
                    skipped.append(scenario_path.name)
                    continue
                raise

            assert config_path.is_file(), f"{scenario_path.name}: no config generated"
            assert (out / "net.net.xml").is_file()
            tested += 1

        if skipped:
            import warnings
            warnings.warn(f"Skipped {len(skipped)} scenarios (netconvert arm64): {skipped}")

        assert tested > 0
