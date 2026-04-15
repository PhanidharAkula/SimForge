"""
Test suite to verify SUMO adapter produces deterministic outputs.

Running the adapter twice on the same canonical bundle should produce
byte-identical output files.
"""

import hashlib
import tempfile
from pathlib import Path

import pytest

from adapters.sumo.sumo_adapter import prepare_sumo_inputs


REPO_ROOT = Path(__file__).resolve().parents[1]

# Pick the first available generated scenario
_CANDIDATES = ["chicago_1k_car", "nyc_10k_car", "la_50k_bike_car_transit"]
_SCENARIO: Path | None = None
for _name in _CANDIDATES:
    _path = REPO_ROOT / "scenarios" / _name
    if _path.is_dir():
        _SCENARIO = _path
        break


def compute_file_hash(filepath: Path) -> str:
    """Compute SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_file_hashes(directory: Path, exclude_patterns: list[str] | None = None) -> dict[str, str]:
    """
    Compute hashes for all files in a directory.

    Args:
        directory: Path to directory
        exclude_patterns: Filename substrings to exclude (e.g. files with timestamps)

    Returns:
        Dict mapping relative filename to SHA256 hash
    """
    exclude_patterns = exclude_patterns or []
    hashes = {}

    for filepath in sorted(directory.rglob("*")):
        if filepath.is_file():
            rel_path = filepath.relative_to(directory)

            skip = any(pat in str(rel_path) for pat in exclude_patterns)
            if not skip:
                hashes[str(rel_path)] = compute_file_hash(filepath)

    return hashes


class TestSUMOAdapterDeterminism:
    """Tests verifying deterministic output from the SUMO adapter."""

    @pytest.fixture
    def scenario_path(self) -> Path:
        """Path to a generated scenario bundle."""
        assert _SCENARIO is not None and _SCENARIO.is_dir(), (
            "No generated scenario found. Run the generation scripts first."
        )
        return _SCENARIO

    def test_adapter_produces_identical_outputs_across_runs(self, scenario_path: Path):
        """
        Running the adapter twice on the same input should produce
        byte-identical outputs (except for netconvert timestamp in net.xml).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            run1_dir = Path(tmpdir) / "run1"
            run2_dir = Path(tmpdir) / "run2"
            run1_dir.mkdir()
            run2_dir.mkdir()

            result1 = prepare_sumo_inputs(scenario_path, run1_dir)
            result2 = prepare_sumo_inputs(scenario_path, run2_dir)

            assert result1 is not None, "Run 1 failed"
            assert result2 is not None, "Run 2 failed"

            # Exclude net.net.xml (contains netconvert timestamp)
            hashes1 = get_file_hashes(run1_dir, exclude_patterns=["net.net.xml"])
            hashes2 = get_file_hashes(run2_dir, exclude_patterns=["net.net.xml"])

            assert set(hashes1.keys()) == set(hashes2.keys()), (
                f"Different files generated:\n"
                f"Run 1: {sorted(hashes1.keys())}\n"
                f"Run 2: {sorted(hashes2.keys())}"
            )

            for filename in sorted(hashes1.keys()):
                assert hashes1[filename] == hashes2[filename], (
                    f"File {filename} differs between runs"
                )

    def test_routes_file_is_deterministic(self, scenario_path: Path):
        """Routes file should be byte-identical across runs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run1_dir = Path(tmpdir) / "run1"
            run2_dir = Path(tmpdir) / "run2"
            run1_dir.mkdir()
            run2_dir.mkdir()

            prepare_sumo_inputs(scenario_path, run1_dir)
            prepare_sumo_inputs(scenario_path, run2_dir)

            hash1 = compute_file_hash(run1_dir / "routes.rou.xml")
            hash2 = compute_file_hash(run2_dir / "routes.rou.xml")
            assert hash1 == hash2, "Routes file should be deterministic"

    def test_nodes_file_is_deterministic(self, scenario_path: Path):
        """Nodes file should be byte-identical across runs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run1_dir = Path(tmpdir) / "run1"
            run2_dir = Path(tmpdir) / "run2"
            run1_dir.mkdir()
            run2_dir.mkdir()

            prepare_sumo_inputs(scenario_path, run1_dir)
            prepare_sumo_inputs(scenario_path, run2_dir)

            hash1 = compute_file_hash(run1_dir / "nodes.nod.xml")
            hash2 = compute_file_hash(run2_dir / "nodes.nod.xml")
            assert hash1 == hash2, "Nodes file should be deterministic"

    def test_edges_file_is_deterministic(self, scenario_path: Path):
        """Edges file should be byte-identical across runs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run1_dir = Path(tmpdir) / "run1"
            run2_dir = Path(tmpdir) / "run2"
            run1_dir.mkdir()
            run2_dir.mkdir()

            prepare_sumo_inputs(scenario_path, run1_dir)
            prepare_sumo_inputs(scenario_path, run2_dir)

            hash1 = compute_file_hash(run1_dir / "edges.edg.xml")
            hash2 = compute_file_hash(run2_dir / "edges.edg.xml")
            assert hash1 == hash2, "Edges file should be deterministic"

    def test_config_file_is_deterministic(self, scenario_path: Path):
        """SUMO config file should be byte-identical across runs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run1_dir = Path(tmpdir) / "run1"
            run2_dir = Path(tmpdir) / "run2"
            run1_dir.mkdir()
            run2_dir.mkdir()

            prepare_sumo_inputs(scenario_path, run1_dir)
            prepare_sumo_inputs(scenario_path, run2_dir)

            hash1 = compute_file_hash(run1_dir / "toy.sumocfg")
            hash2 = compute_file_hash(run2_dir / "toy.sumocfg")
            assert hash1 == hash2, "Config file should be deterministic"


class TestHashUtilities:
    """Tests for the hash utility functions."""

    def test_compute_file_hash_consistent(self, tmp_path: Path):
        """Same file content should produce same hash."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        hash1 = compute_file_hash(test_file)
        hash2 = compute_file_hash(test_file)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex is 64 chars

    def test_compute_file_hash_different_content(self, tmp_path: Path):
        """Different content should produce different hash."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"

        file1.write_text("hello")
        file2.write_text("world")

        assert compute_file_hash(file1) != compute_file_hash(file2)

    def test_get_file_hashes_excludes_patterns(self, tmp_path: Path):
        """Exclude patterns should filter out matching files."""
        (tmp_path / "keep.txt").write_text("keep")
        (tmp_path / "skip.log").write_text("skip")
        (tmp_path / "also_skip.log").write_text("skip too")

        hashes = get_file_hashes(tmp_path, exclude_patterns=[".log"])

        assert "keep.txt" in hashes
        assert "skip.log" not in hashes
        assert "also_skip.log" not in hashes
