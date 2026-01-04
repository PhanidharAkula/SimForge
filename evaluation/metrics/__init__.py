"""
SimForge Evaluation Metrics Module.

Provides metrics for evaluating simulation outputs:

- travel_time: Basic travel time statistics from SUMO tripinfo
- fidelity: RMSE, GEH, KS statistics for accuracy assessment
- scalability: Runtime, throughput, SRT measurements
- reproducibility: R = 1 - σ/μ for run-to-run consistency
"""

from .travel_time import TripTimeStats, parse_sumo_tripinfo
from .fidelity import (
    FidelityMetrics,
    compute_rmse,
    compute_geh,
    compute_geh_batch,
    compute_ks_statistic,
    compute_fidelity_metrics,
    interpret_geh,
    interpret_ks,
)
from .scalability import (
    HardwareInfo,
    ScalabilityMetrics,
    SimulationTimer,
    get_hardware_info,
    compute_scalability_metrics,
    format_scalability_report,
    compare_scalability,
)
from .reproducibility import (
    ReproducibilityMetrics,
    MultiKPIReproducibility,
    compute_reproducibility_index,
    compute_reproducibility_metrics,
    compute_multi_kpi_reproducibility,
    format_reproducibility_report,
    format_multi_kpi_report,
    is_reproducible,
)

__all__ = [
    # Travel time
    "TripTimeStats",
    "parse_sumo_tripinfo",
    # Fidelity
    "FidelityMetrics",
    "compute_rmse",
    "compute_geh",
    "compute_geh_batch",
    "compute_ks_statistic",
    "compute_fidelity_metrics",
    "interpret_geh",
    "interpret_ks",
    # Scalability
    "HardwareInfo",
    "ScalabilityMetrics",
    "SimulationTimer",
    "get_hardware_info",
    "compute_scalability_metrics",
    "format_scalability_report",
    "compare_scalability",
    # Reproducibility
    "ReproducibilityMetrics",
    "MultiKPIReproducibility",
    "compute_reproducibility_index",
    "compute_reproducibility_metrics",
    "compute_multi_kpi_reproducibility",
    "format_reproducibility_report",
    "format_multi_kpi_report",
    "is_reproducible",
]
