"""
Reproducibility metrics: how consistent a run is from one repeat to the next.

The thesis metric (C4) is the reproducibility index R = 1 - σ/μ, where μ is
a KPI's mean across the repeats and σ its standard deviation. R sits near
1.0 when the runs are perfectly reproducible and drops toward 0.0 (or below)
as they vary. It's a measure of how steady the output is under fixed seeds
and identical inputs.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class ReproducibilityMetrics:
    """One KPI's reproducibility measurement."""
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
    """Reproducibility results across several KPIs."""
    kpi_results: Dict[str, ReproducibilityMetrics] = field(default_factory=dict)
    overall_reproducibility: float = 0.0
    n_runs: int = 0
    scenario_id: Optional[str] = None
    engine: str = "unknown"


def compute_reproducibility_index(values: List[float]) -> float:
    """The reproducibility index R = 1 - σ/μ for one KPI's repeated values.

    Higher is better, capped at 1.0: identical values give 1.0, wildly
    varying ones give 0.0 or negative. Needs at least 2 values, else raises
    ValueError.
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
    # Clamp to [0, 1] so the index reads identically here, in
    # analyze_benchmark, and in generate_plots (R = 1 - CV, floored at 0 for
    # high-variance cells rather than going negative).
    r_index = max(0.0, 1.0 - cv)

    return r_index


def compute_reproducibility_metrics(
    values: List[float],
    kpi_name: str = "unknown",
) -> ReproducibilityMetrics:
    """The full reproducibility breakdown for one KPI's repeated values.

    `kpi_name` just labels the result. Returns a ReproducibilityMetrics with
    the index, mean, std, CV, range, and a plain-English interpretation.
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
            # Mean near zero but values vary: maximally non-reproducible. Keep
            # r_index finite (0.0) so the metric stays valid in any JSON it
            # lands in, instead of -inf which is not valid JSON.
            cv = float('inf')
            r_index = 0.0
    else:
        cv = std_dev / abs(mean)
        r_index = max(0.0, 1.0 - cv)
    
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
    """Reproducibility across several KPIs at once.

    `run_results` is one dict of KPI values per run, e.g.
        [
            {"travel_time": 12.5, "throughput": 100},
            {"travel_time": 12.3, "throughput": 102},
            {"travel_time": 12.6, "throughput": 99},
        ]
    `scenario_id` and `engine` just label the result. Returns a
    MultiKPIReproducibility covering every KPI.
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
    """Format one KPI's reproducibility metrics as a readable report.
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
    """Format a multi-KPI reproducibility result as a readable report.
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
    """True if the KPI's R index clears `threshold` (default 0.95).
    """
    return metrics.reproducibility_index >= threshold
