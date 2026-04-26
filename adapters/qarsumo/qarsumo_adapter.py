"""
QarSUMO Adapter for SimForge.

QarSUMO is a GPU-accelerated traffic simulator compatible with SUMO input formats.
This adapter reuses the SUMO adapter for input generation and adds GPU-specific
configuration options.

Key differences from SUMO:
- Uses GPU for simulation (massive speedup on large scenarios)
- Same input/output formats as SUMO
- Additional GPU-specific options in config

Usage:
    from adapters.qarsumo import prepare_qarsumo_inputs
    prepare_qarsumo_inputs("scenarios/sioux_falls_tier50k", "out/qarsumo", gpu_device=0)
"""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import logging

try:
    from lxml import etree
except ImportError as exc:
    raise ImportError(
        "lxml is required for the QarSUMO adapter.\n"
        "  Install with: pip install lxml\n"
        "  Or: conda install lxml"
    ) from exc

# Reuse SUMO adapter for base input generation
from adapters.sumo.sumo_adapter import prepare_sumo_inputs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class QarSUMOConfig:
    """Configuration options specific to QarSUMO GPU execution."""
    gpu_device: int = 0
    batch_size: int = 10000
    stream_count: int = 4
    precision: str = "float32"  # float32 or float16
    
    # Performance tuning
    min_batch_threshold: int = 100
    max_pending_vehicles: int = 50000
    
    def to_dict(self) -> dict:
        return {
            "gpu_device": self.gpu_device,
            "batch_size": self.batch_size,
            "stream_count": self.stream_count,
            "precision": self.precision,
            "min_batch_threshold": self.min_batch_threshold,
            "max_pending_vehicles": self.max_pending_vehicles,
        }


def find_qarsumo_binary() -> Optional[Path]:
    """Find the QarSUMO binary in common locations."""
    possible_paths = [
        Path("/usr/local/bin/qarsumo"),
        Path("/opt/qarsumo/bin/qarsumo"),
        Path.home() / "qarsumo" / "build" / "qarsumo",
        Path.home() / ".local" / "bin" / "qarsumo",
    ]
    
    # Also check PATH
    result = shutil.which("qarsumo")
    if result:
        return Path(result)
    
    for p in possible_paths:
        if p.exists():
            return p
    
    return None


def check_gpu_available() -> bool:
    """Check if NVIDIA GPU is available for QarSUMO."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            gpus = result.stdout.strip().split("\n")
            logger.info("Found %d GPU(s): %s", len(gpus), ', '.join(gpus))
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    logger.warning("No NVIDIA GPU detected - QarSUMO requires CUDA-capable GPU")
    return False


def get_gpu_info() -> dict:
    """Get detailed GPU information."""
    info = {
        "available": False,
        "count": 0,
        "devices": []
    }
    
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.total,compute_cap", 
             "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        if result.returncode == 0:
            info["available"] = True
            for line in result.stdout.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    info["devices"].append({
                        "index": int(parts[0]),
                        "name": parts[1],
                        "memory": parts[2],
                        "compute_capability": parts[3]
                    })
            info["count"] = len(info["devices"])
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    return info


def extend_config_for_qarsumo(
    config_path: Path, 
    qarsumo_config: QarSUMOConfig
) -> Path:
    """
    Extend a SUMO config file with QarSUMO-specific options.
    
    Creates a new config file with qarsumo_ prefix.
    """
    try:
        tree = etree.parse(str(config_path))
    except etree.XMLSyntaxError as e:
        raise ValueError(
            f"Failed to parse SUMO config at {config_path}: {e}\n"
            f"  This usually means SUMO input generation failed earlier.\n"
            f"  Check that 'prepare_sumo_inputs' completed successfully."
        ) from e
    root = tree.getroot()
    
    # Add QarSUMO-specific section
    qarsumo_elem = etree.SubElement(root, "qarsumo")
    
    # GPU device
    gpu_elem = etree.SubElement(qarsumo_elem, "gpu-device")
    gpu_elem.set("value", str(qarsumo_config.gpu_device))
    
    # Batch size
    batch_elem = etree.SubElement(qarsumo_elem, "batch-size")
    batch_elem.set("value", str(qarsumo_config.batch_size))
    
    # Stream count
    stream_elem = etree.SubElement(qarsumo_elem, "stream-count")
    stream_elem.set("value", str(qarsumo_config.stream_count))
    
    # Precision
    prec_elem = etree.SubElement(qarsumo_elem, "precision")
    prec_elem.set("value", qarsumo_config.precision)
    
    # Performance tuning
    min_batch_elem = etree.SubElement(qarsumo_elem, "min-batch-threshold")
    min_batch_elem.set("value", str(qarsumo_config.min_batch_threshold))
    
    max_pending_elem = etree.SubElement(qarsumo_elem, "max-pending-vehicles")
    max_pending_elem.set("value", str(qarsumo_config.max_pending_vehicles))
    
    # Write new config
    qarsumo_config_path = config_path.parent / f"qarsumo_{config_path.name}"
    with open(qarsumo_config_path, "wb") as f:
        tree.write(f, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    
    logger.info("Created QarSUMO config: %s", qarsumo_config_path)
    return qarsumo_config_path


def prepare_qarsumo_inputs(
    scenario_path: str | Path,
    output_dir: str | Path,
    qarsumo_config: Optional[QarSUMOConfig] = None
) -> Path:
    """
    Prepare inputs for QarSUMO simulation.
    
    This reuses the SUMO adapter for base input generation,
    then extends the config with QarSUMO-specific options.
    
    Args:
        scenario_path: Path to canonical scenario bundle
        output_dir: Output directory for generated files
        qarsumo_config: QarSUMO-specific configuration options
        
    Returns:
        Path to the generated QarSUMO config file
    """
    scenario_path = Path(scenario_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if qarsumo_config is None:
        qarsumo_config = QarSUMOConfig()
    
    logger.info("Preparing QarSUMO inputs for: %s", scenario_path)
    
    # Step 1: Generate SUMO inputs (network, routes, base config)
    # prepare_sumo_inputs returns a ScenarioSummary, not a path
    logger.info("Step 1: Generating base SUMO inputs...")
    _summary = prepare_sumo_inputs(scenario_path, output_dir)
    
    # The SUMO config is at output_dir/toy.sumocfg
    sumo_config_path = output_dir / "toy.sumocfg"
    if not sumo_config_path.exists():
        raise FileNotFoundError(f"SUMO config not found at {sumo_config_path}")
    
    # Step 2: Extend config with QarSUMO options
    logger.info("Step 2: Adding QarSUMO configuration...")
    qarsumo_config_path = extend_config_for_qarsumo(sumo_config_path, qarsumo_config)
    
    logger.info("QarSUMO inputs ready at: %s", output_dir)
    return qarsumo_config_path


def run_qarsumo(
    config_path: str | Path,
    timeout_s: int = 86400,
    seed: Optional[int] = None,
    gpu_device: int = 0,
    mesoscopic: bool = False
) -> tuple[bool, float, Optional[str]]:
    """
    Run QarSUMO simulation.
    
    Args:
        config_path: Path to QarSUMO config file
        timeout_s: Maximum runtime in seconds
        seed: Random seed (overrides config)
        gpu_device: CUDA device index
        mesoscopic: Use mesoscopic simulation mode (for fallback to SUMO)
        
    Returns:
        Tuple of (success, runtime_seconds, error_message)
    """
    import time
    
    config_path = Path(config_path).resolve()
    
    # Check for QarSUMO binary
    qarsumo_bin = find_qarsumo_binary()
    use_qarsumo = qarsumo_bin is not None
    
    if qarsumo_bin is None:
        # Fall back to SUMO if QarSUMO not available
        logger.warning("QarSUMO not found, falling back to SUMO")
        qarsumo_bin = shutil.which("sumo")
        if qarsumo_bin is None:
            return False, 0.0, "Neither QarSUMO nor SUMO found in PATH"
        
        # When falling back to SUMO, use the base SUMO config (without QarSUMO options)
        # The base config should be in the same directory as toy.sumocfg
        base_config = config_path.parent / "toy.sumocfg"
        if base_config.exists():
            config_path = base_config
            logger.info("Using base SUMO config: %s", config_path)
    
    # Build command with absolute path
    cmd = [
        str(qarsumo_bin),
        "-c", str(config_path),
        "--ignore-route-errors"
    ]
    
    if seed is not None:
        cmd.extend(["--seed", str(seed)])
    
    # Add GPU device if using actual QarSUMO
    if use_qarsumo:
        cmd.extend(["--gpu-device", str(gpu_device)])
    elif mesoscopic:
        # When falling back to SUMO, add mesoscopic flag if requested
        cmd.append("--mesosim")
        logger.info("Using mesoscopic simulation mode (faster)")
    
    logger.debug("Running: %s", ' '.join(cmd))
    
    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=config_path.parent,
            check=False
        )
        elapsed = time.time() - start_time
        
        if result.returncode == 0:
            return True, elapsed, None
        else:
            error = result.stderr[:500] if result.stderr else f"Exit code {result.returncode}"
            return False, elapsed, error
            
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return False, elapsed, f"Timeout after {timeout_s}s"
    except FileNotFoundError:
        elapsed = time.time() - start_time
        return False, elapsed, (
            f"Simulation binary not found: {qarsumo_bin}. "
            f"SUMO is bundled in requirements.lock — install with `uv pip install -r requirements.lock`."
        )
    except OSError as e:
        elapsed = time.time() - start_time
        logger.exception("Unexpected error running simulation: %s", e)
        return False, elapsed, str(e)


# CLI interface
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="QarSUMO Adapter")
    parser.add_argument("scenario", help="Path to canonical scenario bundle")
    parser.add_argument("output", help="Output directory")
    parser.add_argument("--gpu-device", type=int, default=0, help="CUDA device index")
    parser.add_argument("--batch-size", type=int, default=10000, help="GPU batch size")
    parser.add_argument("--run", action="store_true", help="Also run the simulation")
    parser.add_argument("--seed", type=int, help="Random seed")
    
    args = parser.parse_args()
    
    # Check GPU
    gpu_info = get_gpu_info()
    if gpu_info["available"]:
        print(f"GPU(s) available: {gpu_info['count']}")
        for dev in gpu_info["devices"]:
            print(f"  [{dev['index']}] {dev['name']} ({dev['memory']}, CC {dev['compute_capability']})")
    else:
        print("Warning: No GPU detected, QarSUMO will fall back to CPU/SUMO")
    
    # Create config
    config = QarSUMOConfig(
        gpu_device=args.gpu_device,
        batch_size=args.batch_size
    )
    
    # Prepare inputs
    _config_path = prepare_qarsumo_inputs(args.scenario, args.output, config)
    print(f"Generated QarSUMO config: {_config_path}")
    
    # Optionally run
    if args.run:
        print("\nRunning simulation...")
        _success, _runtime, _error = run_qarsumo(
            _config_path, 
            seed=args.seed,
            gpu_device=args.gpu_device
        )
        if _success:
            print(f"✓ Completed in {_runtime:.2f}s")
        else:
            print(f"✗ Failed: {_error}")
