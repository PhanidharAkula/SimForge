"""
Scalability metrics for evaluating simulation performance.

Implements the thesis-defined metrics (C4):

- Runtime measurement (wall-clock time)
- Throughput (vehicles/sec, trips/sec)
- Simulated-to-Real-Time ratio (SRT)
- Per-core and per-watt normalization (when hardware info available)

These metrics enable fair comparison of computational efficiency across
CPU, GPU, and HPC environments.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import platform
import os


@dataclass
class HardwareInfo:
    """
    Hardware information for normalization.
    """
    cpu_model: str = "unknown"
    cpu_cores: int = 1
    cpu_threads: int = 1
    memory_gb: float = 0.0
    gpu_model: Optional[str] = None
    gpu_memory_gb: Optional[float] = None
    power_watts: Optional[float] = None  # TDP or measured power


@dataclass
class ScalabilityMetrics:
    """
    Container for scalability measurement results.
    """
    # Basic timing
    wall_clock_seconds: float
    simulated_time_seconds: float
    
    # Throughput metrics
    vehicles_completed: int
    trips_per_second: float
    simulated_to_realtime_ratio: float  # SRT = T_sim / T_wall
    
    # Normalized metrics (when hardware info available)
    trips_per_second_per_core: Optional[float] = None
    trips_per_second_per_watt: Optional[float] = None
    
    # Context
    hardware_info: Optional[HardwareInfo] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Additional details
    peak_memory_mb: Optional[float] = None
    scenario_id: Optional[str] = None
    engine: str = "unknown"


class SimulationTimer:
    """
    Context manager for timing simulation runs.
    
    Usage:
        with SimulationTimer() as timer:
            run_simulation()
        print(f"Elapsed: {timer.elapsed_seconds} seconds")
    """
    
    def __init__(self):
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.elapsed_seconds: float = 0.0
    
    def __enter__(self) -> "SimulationTimer":
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.end_time = time.perf_counter()
        self.elapsed_seconds = self.end_time - self.start_time


def get_hardware_info() -> HardwareInfo:
    """
    Detect hardware information for the current system.
    
    Returns
    -------
    HardwareInfo
        Detected hardware specifications
    """
    info = HardwareInfo()
    
    # CPU info
    info.cpu_model = platform.processor() or "unknown"
    info.cpu_cores = os.cpu_count() or 1
    info.cpu_threads = info.cpu_cores  # Approximation; would need psutil for accurate count
    
    # Memory (basic detection)
    try:
        # Try to get memory info on macOS/Linux
        if platform.system() == "Darwin":
            import subprocess
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                info.memory_gb = int(result.stdout.strip()) / (1024 ** 3)
        elif platform.system() == "Linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        kb = int(line.split()[1])
                        info.memory_gb = kb / (1024 ** 2)
                        break
    except Exception:
        pass
    
    # GPU detection would require additional libraries (pynvml, etc.)
    # Left as None for now
    
    return info


def compute_scalability_metrics(
    wall_clock_seconds: float,
    simulated_time_seconds: float,
    vehicles_completed: int,
    hardware_info: Optional[HardwareInfo] = None,
    scenario_id: Optional[str] = None,
    engine: str = "unknown",
) -> ScalabilityMetrics:
    """
    Compute scalability metrics from a simulation run.
    
    Parameters
    ----------
    wall_clock_seconds : float
        Wall-clock runtime of the simulation
    simulated_time_seconds : float
        Simulated time horizon (e.g., 3600 for 1-hour simulation)
    vehicles_completed : int
        Number of vehicles/trips that completed
    hardware_info : Optional[HardwareInfo]
        Hardware specifications for normalization
    scenario_id : Optional[str]
        Identifier for the scenario
    engine : str
        Name of the simulation engine (e.g., "sumo", "matsim")
        
    Returns
    -------
    ScalabilityMetrics
        Computed scalability metrics
    """
    # Basic throughput
    trips_per_second = vehicles_completed / wall_clock_seconds if wall_clock_seconds > 0 else 0.0
    
    # Simulated-to-Real-Time ratio
    srt = simulated_time_seconds / wall_clock_seconds if wall_clock_seconds > 0 else 0.0
    
    # Normalized metrics
    trips_per_second_per_core = None
    trips_per_second_per_watt = None
    
    if hardware_info:
        if hardware_info.cpu_cores > 0:
            trips_per_second_per_core = trips_per_second / hardware_info.cpu_cores
        if hardware_info.power_watts and hardware_info.power_watts > 0:
            trips_per_second_per_watt = trips_per_second / hardware_info.power_watts
    
    return ScalabilityMetrics(
        wall_clock_seconds=wall_clock_seconds,
        simulated_time_seconds=simulated_time_seconds,
        vehicles_completed=vehicles_completed,
        trips_per_second=trips_per_second,
        simulated_to_realtime_ratio=srt,
        trips_per_second_per_core=trips_per_second_per_core,
        trips_per_second_per_watt=trips_per_second_per_watt,
        hardware_info=hardware_info,
        scenario_id=scenario_id,
        engine=engine,
    )


def format_scalability_report(metrics: ScalabilityMetrics) -> str:
    """
    Format scalability metrics as a human-readable report.
    
    Parameters
    ----------
    metrics : ScalabilityMetrics
        Computed scalability metrics
        
    Returns
    -------
    str
        Formatted report string
    """
    lines = [
        "=" * 50,
        "SCALABILITY METRICS REPORT",
        "=" * 50,
        f"Engine           : {metrics.engine}",
        f"Scenario         : {metrics.scenario_id or 'N/A'}",
        f"Timestamp        : {metrics.timestamp}",
        "",
        "TIMING",
        "-" * 30,
        f"Wall-clock time  : {metrics.wall_clock_seconds:.3f} seconds",
        f"Simulated time   : {metrics.simulated_time_seconds:.0f} seconds",
        f"SRT ratio        : {metrics.simulated_to_realtime_ratio:.2f}x real-time",
        "",
        "THROUGHPUT",
        "-" * 30,
        f"Vehicles completed : {metrics.vehicles_completed}",
        f"Trips/second       : {metrics.trips_per_second:.2f}",
    ]
    
    if metrics.trips_per_second_per_core is not None:
        lines.append(f"Trips/sec/core     : {metrics.trips_per_second_per_core:.2f}")
    
    if metrics.trips_per_second_per_watt is not None:
        lines.append(f"Trips/sec/watt     : {metrics.trips_per_second_per_watt:.4f}")
    
    if metrics.hardware_info:
        hw = metrics.hardware_info
        lines.extend([
            "",
            "HARDWARE",
            "-" * 30,
            f"CPU model   : {hw.cpu_model}",
            f"CPU cores   : {hw.cpu_cores}",
            f"Memory (GB) : {hw.memory_gb:.1f}",
        ])
        if hw.gpu_model:
            lines.append(f"GPU         : {hw.gpu_model}")
    
    lines.append("=" * 50)
    
    return "\n".join(lines)


def compare_scalability(
    baseline: ScalabilityMetrics,
    comparison: ScalabilityMetrics,
) -> Dict[str, Any]:
    """
    Compare two scalability measurement results.
    
    Parameters
    ----------
    baseline : ScalabilityMetrics
        Baseline/reference metrics
    comparison : ScalabilityMetrics
        Metrics to compare against baseline
        
    Returns
    -------
    Dict[str, Any]
        Comparison results with speedup/slowdown factors
    """
    def safe_ratio(a: float, b: float) -> Optional[float]:
        if b == 0:
            return None
        return a / b
    
    return {
        "runtime_speedup": safe_ratio(baseline.wall_clock_seconds, comparison.wall_clock_seconds),
        "throughput_ratio": safe_ratio(comparison.trips_per_second, baseline.trips_per_second),
        "srt_ratio": safe_ratio(comparison.simulated_to_realtime_ratio, baseline.simulated_to_realtime_ratio),
        "baseline_engine": baseline.engine,
        "comparison_engine": comparison.engine,
    }
