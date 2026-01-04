"""
Reproducibility metrics for evaluating run-to-run consistency.

Implements the thesis-defined metric (C4):

- R = 1 - σ/μ (Reproducibility index)

Where:
- μ = mean of a KPI across repeated runs
- σ = standard deviation across repeated runs
- R approaches 1.0 for perfectly reproducible runs
- R approaches 0.0 (or negative) for highly variable runs

These metrics quantify the consistency of simulation outputs when
executed with fixed seeds and identical inputs.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


@dataclass
class ReproducibilityMetrics:
    """
    Container for reproducibility measurement results.
    """
    # Core metric
    reproducibility_index: float  # R = 1 - σ/μ
    
    # Components
    mean_value: float
    std_dev: float
    coefficient_of_variation: float  # CV = σ/μ
    
    # Sample info
    n_runs: int
    values: List[float]
    
    # Context
    kpi_name: str = "unknown"
    min_value: float = 0.0
    max_value: float = 0.0
    
    # Interpretation
    interpretation: str = ""


@dataclass
class MultiKPIReproducibility:
    """
    Reproducibility results across multiple KPIs.
    """
    kpi_results: Dict[str, ReproducibilityMetrics] = field(default_factory=dict)
    overall_reproducibility: float = 0.0
    n_runs: int = 0
    scenario_id: Optional[str] = None
    engine: str = "unknown"


def compute_reproducibility_index(values: List[float]) -> float:
    """
    Compute the reproducibility index R = 1 - σ/μ.
    
    Parameters
    ----------
    values : List[float]
        KPI values from repeated simulation runs
        
    Returns
    -------
    float
        Reproducibility index (higher is better, max 1.0)
        Returns 1.0 if all values are identical
        Returns 0.0 or negative if highly variable
        
    Raises
    ------
    ValueError
        If fewer than 2 values provided
    """
    if len(values) < 2:
        raise ValueError("Need at least 2 values to compute reproducibility")
    
    mean = statistics.mean(values)
    
    # Handle edge case: if mean is zero or very small
    if abs(mean) < 1e-10:
        # Check if all values are effectively zero
        if all(abs(v) < 1e-10 for v in values):
            return 1.0  # All zeros = perfectly reproducible
        else:
            return 0.0  # Mean near zero but values vary = not reproducible
    
    std_dev = statistics.stdev(values)
    cv = std_dev / abs(mean)
    r_index = 1.0 - cv
    
    return r_index


def compute_reproducibility_metrics(
    values: List[float],
    kpi_name: str = "unknown",
) -> ReproducibilityMetrics:
    """
    Compute comprehensive reproducibility metrics for a KPI.
    
    Parameters
    ----------
    values : List[float]
        KPI values from repeated simulation runs
    kpi_name : str
        Name of the KPI being measured
        
    Returns
    -------
    ReproducibilityMetrics
        Full reproducibility analysis
    """
    if len(values) < 2:
        raise ValueError("Need at least 2 values to compute reproducibility")
    
    mean = statistics.mean(values)
    std_dev = statistics.stdev(values)
    
    # Handle edge cases for CV calculation
    if abs(mean) < 1e-10:
        if all(abs(v) < 1e-10 for v in values):
            cv = 0.0
            r_index = 1.0
        else:
            cv = float('inf')
            r_index = float('-inf')
    else:
        cv = std_dev / abs(mean)
        r_index = 1.0 - cv
    
    # Interpretation
    if r_index >= 0.99:
        interpretation = "excellent (near-deterministic)"
    elif r_index >= 0.95:
        interpretation = "very good"
    elif r_index >= 0.90:
        interpretation = "good"
    elif r_index >= 0.80:
        interpretation = "acceptable"
    elif r_index >= 0.50:
        interpretation = "moderate variability"
    else:
        interpretation = "poor (high variability)"
    
    return ReproducibilityMetrics(
        reproducibility_index=r_index,
        mean_value=mean,
        std_dev=std_dev,
        coefficient_of_variation=cv,
        n_runs=len(values),
        values=values.copy(),
        kpi_name=kpi_name,
        min_value=min(values),
        max_value=max(values),
        interpretation=interpretation,
    )


def compute_multi_kpi_reproducibility(
    run_results: List[Dict[str, float]],
    scenario_id: Optional[str] = None,
    engine: str = "unknown",
) -> MultiKPIReproducibility:
    """
    Compute reproducibility across multiple KPIs from repeated runs.
    
    Parameters
    ----------
    run_results : List[Dict[str, float]]
        List of dictionaries, each containing KPI values from one run.
        Example: [
            {"travel_time": 12.5, "throughput": 100},
            {"travel_time": 12.3, "throughput": 102},
            {"travel_time": 12.6, "throughput": 99},
        ]
    scenario_id : Optional[str]
        Identifier for the scenario
    engine : str
        Name of the simulation engine
        
    Returns
    -------
    MultiKPIReproducibility
        Reproducibility analysis for all KPIs
    """
    if len(run_results) < 2:
        raise ValueError("Need at least 2 runs to compute reproducibility")
    
    # Get all KPI names from the first run
    kpi_names = list(run_results[0].keys())
    
    kpi_results: Dict[str, ReproducibilityMetrics] = {}
    
    for kpi_name in kpi_names:
        # Extract values for this KPI across all runs
        values = [run.get(kpi_name, 0.0) for run in run_results]
        
        try:
            metrics = compute_reproducibility_metrics(values, kpi_name)
            kpi_results[kpi_name] = metrics
        except ValueError:
            continue
    
    # Compute overall reproducibility (average of all R indices)
    if kpi_results:
        r_indices = [m.reproducibility_index for m in kpi_results.values() 
                     if m.reproducibility_index > float('-inf')]
        overall_r = statistics.mean(r_indices) if r_indices else 0.0
    else:
        overall_r = 0.0
    
    return MultiKPIReproducibility(
        kpi_results=kpi_results,
        overall_reproducibility=overall_r,
        n_runs=len(run_results),
        scenario_id=scenario_id,
        engine=engine,
    )


def format_reproducibility_report(metrics: ReproducibilityMetrics) -> str:
    """
    Format reproducibility metrics as a human-readable report.
    
    Parameters
    ----------
    metrics : ReproducibilityMetrics
        Computed reproducibility metrics
        
    Returns
    -------
    str
        Formatted report string
    """
    lines = [
        f"REPRODUCIBILITY: {metrics.kpi_name}",
        "-" * 40,
        f"R index (1-σ/μ) : {metrics.reproducibility_index:.4f}",
        f"Mean            : {metrics.mean_value:.4f}",
        f"Std dev         : {metrics.std_dev:.4f}",
        f"CV (σ/μ)        : {metrics.coefficient_of_variation:.4f}",
        f"Range           : [{metrics.min_value:.4f}, {metrics.max_value:.4f}]",
        f"N runs          : {metrics.n_runs}",
        f"Interpretation  : {metrics.interpretation}",
    ]
    return "\n".join(lines)


def format_multi_kpi_report(results: MultiKPIReproducibility) -> str:
    """
    Format multi-KPI reproducibility results as a report.
    
    Parameters
    ----------
    results : MultiKPIReproducibility
        Multi-KPI reproducibility analysis
        
    Returns
    -------
    str
        Formatted report string
    """
    lines = [
        "=" * 50,
        "REPRODUCIBILITY REPORT",
        "=" * 50,
        f"Engine      : {results.engine}",
        f"Scenario    : {results.scenario_id or 'N/A'}",
        f"N runs      : {results.n_runs}",
        f"Overall R   : {results.overall_reproducibility:.4f}",
        "",
        "KPI BREAKDOWN",
        "-" * 50,
    ]
    
    for kpi_name, metrics in results.kpi_results.items():
        lines.append(
            f"  {kpi_name:20s}: R={metrics.reproducibility_index:.4f} "
            f"(μ={metrics.mean_value:.2f}, σ={metrics.std_dev:.4f}) "
            f"[{metrics.interpretation}]"
        )
    
    lines.append("=" * 50)
    
    return "\n".join(lines)


def is_reproducible(
    metrics: ReproducibilityMetrics,
    threshold: float = 0.95,
) -> bool:
    """
    Check if a KPI meets the reproducibility threshold.
    
    Parameters
    ----------
    metrics : ReproducibilityMetrics
        Computed reproducibility metrics
    threshold : float
        Minimum R index to be considered reproducible (default 0.95)
        
    Returns
    -------
    bool
        True if reproducibility index meets threshold
    """
    return metrics.reproducibility_index >= threshold
