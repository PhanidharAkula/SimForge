"""
Fidelity metrics for comparing simulation outputs against observed/reference data.

Implements the thesis-defined metrics (C4):

- RMSE (Root Mean Square Error): Measures average magnitude of errors
- GEH (Geoffrey E. Havers statistic): Traffic-specific fit measure
- KS (Kolmogorov-Smirnov statistic): Distribution comparison

These metrics enable fair comparison of simulator outputs against ground truth
or against each other under identical canonical inputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple, Optional
import statistics


@dataclass
class FidelityMetrics:
    """
    Container for fidelity comparison results.
    """
    rmse: float
    geh_mean: float
    geh_pct_below_5: float  # Percentage of links where GEH < 5 (acceptable)
    ks_statistic: float
    ks_critical_value: Optional[float]  # Critical value at α=0.05
    n_observations: int


def compute_rmse(observed: List[float], simulated: List[float]) -> float:
    """
    Compute Root Mean Square Error between observed and simulated values.
    
    RMSE = sqrt(mean((observed - simulated)^2))
    
    Parameters
    ----------
    observed : List[float]
        Ground truth / observed values (e.g., traffic counts)
    simulated : List[float]
        Simulated values from the traffic simulator
        
    Returns
    -------
    float
        RMSE value (same units as input)
        
    Raises
    ------
    ValueError
        If lists have different lengths or are empty
    """
    if len(observed) != len(simulated):
        raise ValueError(
            f"Length mismatch: observed has {len(observed)}, simulated has {len(simulated)}"
        )
    if not observed:
        raise ValueError("Cannot compute RMSE on empty lists")
    
    squared_errors = [(o - s) ** 2 for o, s in zip(observed, simulated)]
    mse = statistics.mean(squared_errors)
    return math.sqrt(mse)


def compute_geh(observed: float, simulated: float) -> float:
    """
    Compute the GEH statistic for a single observation pair.
    
    GEH = sqrt(2 * (simulated - observed)^2 / (simulated + observed))
    
    The GEH statistic is widely used in traffic engineering (UK DfT standard).
    
    Interpretation:
    - GEH < 5: Acceptable fit
    - GEH 5-10: Warrants investigation
    - GEH > 10: Poor fit
    
    Parameters
    ----------
    observed : float
        Observed traffic count (must be > 0)
    simulated : float
        Simulated traffic count (must be > 0)
        
    Returns
    -------
    float
        GEH statistic value
    """
    if observed <= 0 or simulated <= 0:
        # GEH is undefined for zero/negative counts
        return float('inf')
    
    numerator = 2 * (simulated - observed) ** 2
    denominator = simulated + observed
    
    return math.sqrt(numerator / denominator)


def compute_geh_batch(
    observed: List[float], 
    simulated: List[float]
) -> Tuple[float, float, List[float]]:
    """
    Compute GEH statistics for multiple observation pairs.
    
    Parameters
    ----------
    observed : List[float]
        List of observed traffic counts
    simulated : List[float]
        List of simulated traffic counts
        
    Returns
    -------
    Tuple[float, float, List[float]]
        - Mean GEH across all pairs
        - Percentage of pairs with GEH < 5 (acceptable fit)
        - List of individual GEH values
    """
    if len(observed) != len(simulated):
        raise ValueError(
            f"Length mismatch: observed has {len(observed)}, simulated has {len(simulated)}"
        )
    if not observed:
        raise ValueError("Cannot compute GEH on empty lists")
    
    geh_values = [compute_geh(o, s) for o, s in zip(observed, simulated)]
    
    # Filter out infinities for mean calculation
    finite_geh = [g for g in geh_values if math.isfinite(g)]
    
    if not finite_geh:
        return float('inf'), 0.0, geh_values
    
    mean_geh = statistics.mean(finite_geh)
    pct_acceptable = sum(1 for g in geh_values if g < 5) / len(geh_values) * 100
    
    return mean_geh, pct_acceptable, geh_values


def compute_ks_statistic(
    distribution_a: List[float], 
    distribution_b: List[float]
) -> Tuple[float, Optional[float]]:
    """
    Compute the Kolmogorov-Smirnov statistic between two distributions.
    
    The KS statistic measures the maximum difference between the empirical
    cumulative distribution functions (ECDFs) of two samples.
    
    Parameters
    ----------
    distribution_a : List[float]
        First sample (e.g., observed travel times)
    distribution_b : List[float]
        Second sample (e.g., simulated travel times)
        
    Returns
    -------
    Tuple[float, Optional[float]]
        - KS statistic (D): max |ECDF_a(x) - ECDF_b(x)|
        - Critical value at α=0.05 for the given sample sizes
        
    Notes
    -----
    Critical value approximation: c(α) * sqrt((n+m)/(n*m))
    where c(0.05) ≈ 1.36
    """
    if not distribution_a or not distribution_b:
        raise ValueError("Cannot compute KS statistic on empty distributions")
    
    n = len(distribution_a)
    m = len(distribution_b)
    
    # Combine and sort all unique values
    all_values = sorted(set(distribution_a) | set(distribution_b))
    
    # Compute ECDFs
    def ecdf(data: List[float], x: float) -> float:
        """Empirical CDF: proportion of data <= x"""
        return sum(1 for d in data if d <= x) / len(data)
    
    # Find maximum difference
    ks_stat = 0.0
    for x in all_values:
        diff = abs(ecdf(distribution_a, x) - ecdf(distribution_b, x))
        ks_stat = max(ks_stat, diff)
    
    # Critical value at α = 0.05 (two-sample test)
    # D_critical = c(α) * sqrt((n+m)/(n*m)) where c(0.05) ≈ 1.36
    c_alpha = 1.36
    critical_value = c_alpha * math.sqrt((n + m) / (n * m))
    
    return ks_stat, critical_value


def compute_fidelity_metrics(
    observed_counts: List[float],
    simulated_counts: List[float],
    observed_travel_times: Optional[List[float]] = None,
    simulated_travel_times: Optional[List[float]] = None,
) -> FidelityMetrics:
    """
    Compute all fidelity metrics comparing observed vs simulated data.
    
    Parameters
    ----------
    observed_counts : List[float]
        Observed link-level traffic counts
    simulated_counts : List[float]
        Simulated link-level traffic counts
    observed_travel_times : Optional[List[float]]
        Observed trip travel times (for KS test)
    simulated_travel_times : Optional[List[float]]
        Simulated trip travel times (for KS test)
        
    Returns
    -------
    FidelityMetrics
        Container with RMSE, GEH, and KS statistics
    """
    # RMSE
    rmse = compute_rmse(observed_counts, simulated_counts)
    
    # GEH
    geh_mean, geh_pct_below_5, _ = compute_geh_batch(observed_counts, simulated_counts)
    
    # KS (only if travel time distributions provided)
    if observed_travel_times and simulated_travel_times:
        ks_stat, ks_crit = compute_ks_statistic(
            observed_travel_times, simulated_travel_times
        )
    else:
        ks_stat = 0.0
        ks_crit = None
    
    return FidelityMetrics(
        rmse=rmse,
        geh_mean=geh_mean,
        geh_pct_below_5=geh_pct_below_5,
        ks_statistic=ks_stat,
        ks_critical_value=ks_crit,
        n_observations=len(observed_counts),
    )


def interpret_geh(geh_value: float) -> str:
    """Return human-readable interpretation of GEH value."""
    if geh_value < 5:
        return "acceptable"
    elif geh_value < 10:
        return "warrants investigation"
    else:
        return "poor fit"


def interpret_ks(ks_stat: float, critical_value: Optional[float]) -> str:
    """Return human-readable interpretation of KS test result."""
    if critical_value is None:
        return "no test performed"
    if ks_stat < critical_value:
        return f"distributions similar (D={ks_stat:.4f} < critical={critical_value:.4f})"
    else:
        return f"distributions differ (D={ks_stat:.4f} >= critical={critical_value:.4f})"
