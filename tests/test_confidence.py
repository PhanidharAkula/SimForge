"""
Tests for `evaluation/metrics/confidence.py` — 95 % confidence intervals.

Validation strategy:
  1. **Tabulated t-critical values** — round-tripped against published
     two-tailed t-tables for α = 0.05 (any standard stats textbook).
  2. **Edge cases** — N=0 raises, N=1 returns ± 0.0, identical samples
     return ± 0.0.
  3. **Worked examples** — small hand-computable inputs let us assert exact
     means and half-widths to machine precision.
  4. **Monotonicity** — half-width strictly shrinks as N grows for a
     fixed-σ population (the whole point of larger N).
"""

from __future__ import annotations

import math

import pytest

from evaluation.metrics.confidence import (
    ConfidenceInterval,
    confidence_interval_95,
    t_critical_95,
)


# ---------------------------------------------------------------------------
# t_critical_95 — table fidelity and degenerate inputs
# ---------------------------------------------------------------------------


class TestTCritical:
    """Cross-check the embedded t-table against textbook values."""

    @pytest.mark.parametrize(
        "n, expected_t",
        [
            (2, 12.706),    # df = 1
            (3, 4.303),     # df = 2
            (5, 2.776),     # df = 4
            (10, 2.262),    # df = 9 — the plan's target N
            (30, 2.045),    # df = 29 — last tabulated entry
        ],
    )
    def test_tabulated_values_match_textbook(self, n: int, expected_t: float) -> None:
        assert t_critical_95(n) == pytest.approx(expected_t, abs=1e-3)

    def test_n_above_30_falls_back_to_normal_z(self) -> None:
        """df > 30 should use the Z = 1.960 normal-distribution limit."""
        assert t_critical_95(35) == 1.960
        assert t_critical_95(1000) == 1.960

    def test_n_equals_1_returns_zero(self) -> None:
        """N=1 has no sample variance — half-width is undefined → 0.0."""
        assert t_critical_95(1) == 0.0

    def test_n_below_1_raises(self) -> None:
        with pytest.raises(ValueError, match="sample size must be >= 1"):
            t_critical_95(0)
        with pytest.raises(ValueError, match="sample size must be >= 1"):
            t_critical_95(-3)


# ---------------------------------------------------------------------------
# confidence_interval_95 — semantic behaviour
# ---------------------------------------------------------------------------


class TestConfidenceInterval:
    """Validate mean, half-width, and dataclass plumbing."""

    def test_empty_sample_raises(self) -> None:
        with pytest.raises(ValueError, match="empty sample"):
            confidence_interval_95([])

    def test_single_value_returns_zero_half_width(self) -> None:
        ci = confidence_interval_95([42.0])
        assert ci.mean == 42.0
        assert ci.half_width == 0.0
        assert ci.n == 1
        assert ci.low == ci.high == 42.0

    def test_identical_values_have_zero_half_width(self) -> None:
        """All-same sample → variance 0 → half_width 0 regardless of N."""
        ci = confidence_interval_95([5.0, 5.0, 5.0, 5.0])
        assert ci.mean == 5.0
        assert ci.half_width == 0.0
        assert ci.n == 4

    def test_mean_is_arithmetic_mean(self) -> None:
        ci = confidence_interval_95([1.0, 2.0, 3.0, 4.0, 5.0])
        assert ci.mean == 3.0

    def test_half_width_matches_hand_computation_n3(self) -> None:
        """
        Hand-computed reference for N=3, values [10, 12, 14]:

            mean        = 12
            sample std  = 2.0  (Bessel-corrected)
            t_{0.025,2} = 4.303
            half_width  = 4.303 * 2.0 / sqrt(3) = 4.967...
        """
        ci = confidence_interval_95([10.0, 12.0, 14.0])
        assert ci.mean == pytest.approx(12.0)
        expected_hw = 4.303 * 2.0 / math.sqrt(3)
        assert ci.half_width == pytest.approx(expected_hw, rel=1e-3)
        assert ci.n == 3

    def test_half_width_matches_hand_computation_n5(self) -> None:
        """N=5, values [1, 2, 3, 4, 5] → mean=3, std≈1.581, t=2.776, hw≈1.962."""
        ci = confidence_interval_95([1.0, 2.0, 3.0, 4.0, 5.0])
        assert ci.mean == pytest.approx(3.0)
        # std = sqrt(sum((x-3)^2)/4) = sqrt(10/4) = sqrt(2.5)
        expected_hw = 2.776 * math.sqrt(2.5) / math.sqrt(5)
        assert ci.half_width == pytest.approx(expected_hw, rel=1e-3)

    def test_high_and_low_bracket_mean(self) -> None:
        ci = confidence_interval_95([100.0, 102.0, 98.0])
        assert ci.low < ci.mean < ci.high
        assert ci.high - ci.mean == pytest.approx(ci.mean - ci.low)

    def test_half_width_shrinks_as_n_grows_for_same_sigma(self) -> None:
        """
        For populations with the same sigma, larger N → narrower CI.
        Constructing two samples with std = 1.0 exactly: pairs of (μ-1, μ+1)
        for N=2, and (μ-1, μ-0.5, μ+0.5, μ+1, μ+0, ...) is fiddly. Easier:
        use samples of different sizes drawn from {-1, +1} alternation, then
        spot-check the t-factor / √N drives the contraction.
        """
        # N=3 vs N=10, both with the same σ ≈ 1.0 sample.
        small = [-1.0, 0.0, 1.0]
        large = [-1.0, -0.5, 0.0, 0.5, 1.0, -1.0, -0.5, 0.0, 0.5, 1.0]
        ci_small = confidence_interval_95(small)
        ci_large = confidence_interval_95(large)
        assert ci_large.half_width < ci_small.half_width, (
            f"larger N should narrow CI: small={ci_small.half_width}, "
            f"large={ci_large.half_width}"
        )

    def test_format_renders_with_pm_separator(self) -> None:
        ci = ConfidenceInterval(mean=203.5, half_width=0.42, n=3)
        assert ci.format(decimals=2) == "203.50 ± 0.42"
        assert ci.format(decimals=1) == "203.5 ± 0.4"
        assert ci.format(decimals=0) == "204 ± 0"

    def test_n_is_recorded_for_downstream_diagnostics(self) -> None:
        """Coverage diagnostic uses ci.n to flag thin-sample cells."""
        for k in (1, 2, 3, 5, 10):
            ci = confidence_interval_95([1.0] * k)
            assert ci.n == k
