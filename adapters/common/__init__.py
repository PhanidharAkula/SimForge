"""Shared helpers reused by all engine adapters."""

from adapters.common.feasibility import (
    FeasibilityReport,
    feasible_trip_ids,
    write_feasibility_report,
)
from pipeline.network.scc import compute_largest_scc

__all__ = [
    "FeasibilityReport",
    "compute_largest_scc",
    "feasible_trip_ids",
    "write_feasibility_report",
]
