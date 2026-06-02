"""
Fidelity metrics: how close a simulation's output is to reference data.

The three the thesis uses (C4):

- RMSE: average error magnitude.
- GEH (the Geoffrey E. Havers statistic): a traffic-specific goodness of fit.
- KS (Kolmogorov-Smirnov): compares whole distributions.

They let us compare engines against ground truth, or against each other, on
the same canonical inputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple, Optional
import statistics


@dataclass
class FidelityMetrics:
    """The results of a fidelity comparison."""
    rmse: float
    geh_mean: float
    geh_pct_below_5: float  # Percentage of links where GEH < 5 (acceptable)
    ks_statistic: float
    ks_critical_value: Optional[float]  # Critical value at α=0.05
    n_observations: int


def compute_rmse(observed: List[float], simulated: List[float]) -> float:
    """Root mean square error between observed and simulated values.

    RMSE = sqrt(mean((observed - simulated)^2)), in the same units as the
    input. `observed` is the ground truth (e.g. traffic counts), `simulated`
    the engine's output. Raises ValueError if the lists differ in length or
    are empty.
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
    GEH for one observation pair.

    GEH = sqrt(2 * (simulated - observed)^2 / (simulated + observed)).
    It's a standard traffic-engineering fit measure (the UK DfT one). Both
    counts must be > 0. How to read it:
    - GEH < 5: acceptable fit
    - GEH 5-10: worth a look
    - GEH > 10: poor fit
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
    """GEH over many observation pairs.

    Returns (mean GEH across the pairs, percentage of pairs with GEH < 5,
    the list of per-pair GEH values).
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
    """The Kolmogorov-Smirnov statistic between two distributions.

    KS is the largest gap between the two samples' empirical CDFs.
    `distribution_a` and `distribution_b` are the two samples (e.g. observed
    vs simulated travel times).

    Returns (D, critical_value): D is max |ECDF_a(x) - ECDF_b(x)|, and the
    critical value at α=0.05 is approximated as c(α) * sqrt((n+m)/(n*m))
    with c(0.05) about 1.36.
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
    """All the fidelity metrics for one observed-vs-simulated comparison.

    `*_counts` are the link-level traffic counts (RMSE and GEH). The optional
    `*_travel_times` are trip travel-time samples; pass both to also run the
    KS test. Returns a FidelityMetrics with RMSE, GEH, and KS.
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
    """A plain-English reading of a GEH value."""
    if geh_value < 5:
        return "acceptable"
    elif geh_value < 10:
        return "warrants investigation"
    else:
        return "poor fit"


def interpret_ks(ks_stat: float, critical_value: Optional[float]) -> str:
    """A plain-English reading of a KS test result."""
    if critical_value is None:
        return "no test performed"
    if ks_stat < critical_value:
        return f"distributions similar (D={ks_stat:.4f} < critical={critical_value:.4f})"
    else:
        return f"distributions differ (D={ks_stat:.4f} >= critical={critical_value:.4f})"
