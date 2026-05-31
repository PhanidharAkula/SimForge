"""
95% confidence intervals via the Student's t-distribution.

The thesis plan (§3.5) commits to reporting **95 % CIs on every KPI**.
SimForge already records mean and standard deviation per `(scenario, engine,
mode)` cell across N stochastic repeats; this module turns those moments
into the confidence interval that quantifies how much sampling noise the
mean carries.

For N independent draws from an approximately-normal population,

    half_width = t_{α/2, N-1} * σ / √N
    CI = mean ± half_width

where t_{α/2, df} is the two-tailed Student's t critical value. We hard-code
the table for α = 0.05 (95 % confidence) rather than depend on scipy, both
to keep `requirements.lock` minimal and to make the math auditable in the
thesis appendix. For N > 31 we fall back to the normal-distribution Z = 1.960
limit, which differs from t_{29} by ≤ 5 %.

Edge cases:
  * N == 0 → cannot compute anything meaningful; raise ValueError.
  * N == 1 → CI is undefined (no sample variance); we return half_width = 0
    so callers can render "203.5 ± 0.0" without special-casing.

For our standard runspecs (N=3 SUMO, N=2 MATSim, N=10 target after advisor
sign-off), the relevant t-critical values are:

  N=2  → t = 12.706   (CI is huge — flagged in the thesis as a known limit
                       of the deterministic MATSim cell.)
  N=3  → t =  4.303
  N=5  → t =  2.776
  N=10 → t =  2.262

See `tests/test_confidence.py` for the validation suite.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# Two-tailed t-critical values at α = 0.05 (95 % confidence) by degrees of
# freedom (df = N-1). Sourced from any standard statistics textbook;
# round-tripped against scipy.stats.t.ppf(0.975, df) to within 1e-3.
_T_CRITICAL_95: dict[int, float] = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.080,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.060,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
    30: 2.042,
}

# For df > 30, t_{α/2, df} converges quickly to the normal distribution's
# 1.960 limit. Using 1.960 for df > 30 is conservative (slightly narrower
# than the true t-CI) by < 5 % at df = 30 and < 1 % at df = 60.
_Z_CRITICAL_95: float = 1.960


def t_critical_95(n: int) -> float:
    """
    Return the two-tailed t-critical value at α = 0.05 for a sample of size N.

    For N == 1 returns 0.0 (CI undefined; caller will format as ± 0.0).
    For N > 31 returns the normal-distribution Z = 1.960 limit.
    """
    if n < 1:
        raise ValueError(f"sample size must be >= 1, got {n}")
    if n == 1:
        return 0.0
    df = n - 1
    if df in _T_CRITICAL_95:
        return _T_CRITICAL_95[df]
    return _Z_CRITICAL_95


@dataclass(frozen=True)
class ConfidenceInterval:
    """A 95 % confidence interval on the sample mean."""

    mean: float
    half_width: float       # t_{0.025, n-1} * σ / √N
    n: int                  # sample size used to compute it

    @property
    def low(self) -> float:
        return self.mean - self.half_width

    @property
    def high(self) -> float:
        return self.mean + self.half_width

    def format(self, decimals: int = 2) -> str:
        """`"<mean> ± <half_width>"` rounded to `decimals` places."""
        return f"{self.mean:.{decimals}f} ± {self.half_width:.{decimals}f}"


def confidence_interval_95(values: list[float] | tuple[float, ...]) -> ConfidenceInterval:
    """
    Compute the 95 % CI on the mean of `values` using Student's t.

    Returns a `ConfidenceInterval(mean, half_width, n)`. With `n == 1` the
    half-width is 0 (sample variance is undefined; caller renders as ± 0.0).
    With `n == 0` raises `ValueError` — there is no mean to report.
    """
    n = len(values)
    if n == 0:
        raise ValueError("cannot compute a confidence interval over an empty sample")
    mean = sum(values) / n
    if n == 1:
        return ConfidenceInterval(mean=mean, half_width=0.0, n=1)
    # Sample standard deviation (Bessel-corrected: divide by N-1).
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    stddev = math.sqrt(variance)
    half_width = t_critical_95(n) * stddev / math.sqrt(n)
    return ConfidenceInterval(mean=mean, half_width=half_width, n=n)
