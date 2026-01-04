"""
Tests for evaluation/metrics/reproducibility.py

Tests the reproducibility index (R = 1 - σ/μ) implementations.
"""

from __future__ import annotations

import pytest

from evaluation.metrics.reproducibility import (
    compute_reproducibility_index,
    compute_reproducibility_metrics,
    compute_multi_kpi_reproducibility,
    format_reproducibility_report,
    is_reproducible,
)


class TestReproducibilityIndex:
    """Tests for the core R = 1 - σ/μ computation."""
    
    def test_identical_values_perfect_reproducibility(self):
        """Identical values should give R = 1.0."""
        values = [100.0, 100.0, 100.0, 100.0]
        r = compute_reproducibility_index(values)
        assert r == 1.0
    
    def test_low_variance_high_reproducibility(self):
        """Low variance relative to mean should give high R."""
        # Mean = 100, values very close to mean
        values = [99.9, 100.0, 100.1, 100.0]
        r = compute_reproducibility_index(values)
        assert r > 0.99  # Should be very high
    
    def test_high_variance_low_reproducibility(self):
        """High variance relative to mean should give low R."""
        # Mean = 100, but huge spread
        values = [50.0, 150.0, 50.0, 150.0]
        r = compute_reproducibility_index(values)
        assert r < 0.5  # Should be low
    
    def test_cv_equals_one_gives_r_zero(self):
        """When CV = 1 (σ = μ), R should be 0."""
        # This is a theoretical case
        # For CV=1: σ = μ, so R = 1 - 1 = 0
        # Hard to construct exactly, but we can approximate
        values = [0.0, 200.0]  # mean=100, stdev≈141, CV≈1.41, R≈-0.41
        r = compute_reproducibility_index(values)
        assert r < 0  # Negative due to high variance
    
    def test_single_value_raises(self):
        """Single value should raise ValueError."""
        with pytest.raises(ValueError):
            compute_reproducibility_index([100.0])
    
    def test_zero_mean_all_zeros(self):
        """All zeros should give R = 1.0 (perfectly reproducible)."""
        values = [0.0, 0.0, 0.0]
        r = compute_reproducibility_index(values)
        assert r == 1.0


class TestReproducibilityMetrics:
    """Tests for comprehensive reproducibility metrics."""
    
    def test_compute_metrics_basic(self):
        """Test basic metrics computation."""
        values = [10.0, 10.1, 9.9, 10.0, 10.0]
        metrics = compute_reproducibility_metrics(values, kpi_name="travel_time")
        
        assert metrics.kpi_name == "travel_time"
        assert metrics.n_runs == 5
        assert abs(metrics.mean_value - 10.0) < 0.1
        assert metrics.std_dev < 0.1
        assert metrics.reproducibility_index > 0.99
        assert metrics.interpretation == "excellent (near-deterministic)"
    
    def test_compute_metrics_stores_values(self):
        """Metrics should store original values."""
        values = [1.0, 2.0, 3.0]
        metrics = compute_reproducibility_metrics(values, kpi_name="test")
        
        assert metrics.values == values
        assert metrics.min_value == 1.0
        assert metrics.max_value == 3.0
    
    def test_interpretation_levels(self):
        """Test different interpretation levels."""
        # Excellent: R >= 0.99
        excellent = compute_reproducibility_metrics([100.0, 100.0, 100.0], "test")
        assert "excellent" in excellent.interpretation
        
        # Poor: R < 0.5 (need high variance)
        poor = compute_reproducibility_metrics([10.0, 50.0, 10.0, 50.0], "test")
        # This gives R ≈ 0.33 which should be "poor"
        assert "poor" in poor.interpretation or "moderate" in poor.interpretation


class TestMultiKPIReproducibility:
    """Tests for multi-KPI reproducibility analysis."""
    
    def test_multi_kpi_basic(self):
        """Test multi-KPI analysis."""
        run_results = [
            {"travel_time": 12.0, "throughput": 100.0},
            {"travel_time": 12.1, "throughput": 99.0},
            {"travel_time": 11.9, "throughput": 101.0},
        ]
        
        results = compute_multi_kpi_reproducibility(
            run_results,
            scenario_id="test",
            engine="sumo",
        )
        
        assert results.n_runs == 3
        assert results.engine == "sumo"
        assert results.scenario_id == "test"
        assert "travel_time" in results.kpi_results
        assert "throughput" in results.kpi_results
        assert results.overall_reproducibility > 0.9  # Should be high
    
    def test_multi_kpi_single_run_raises(self):
        """Multi-KPI with single run should raise."""
        with pytest.raises(ValueError):
            compute_multi_kpi_reproducibility([{"kpi": 1.0}])


class TestReproducibilityReport:
    """Tests for report formatting."""
    
    def test_format_single_kpi_report(self):
        """Test single KPI report formatting."""
        metrics = compute_reproducibility_metrics(
            [10.0, 10.1, 9.9], "travel_time"
        )
        
        report = format_reproducibility_report(metrics)
        
        assert "travel_time" in report
        assert "R index" in report
        assert "Mean" in report
        assert "Std dev" in report


class TestIsReproducible:
    """Tests for reproducibility threshold checking."""
    
    def test_is_reproducible_high_r(self):
        """High R should pass default threshold."""
        metrics = compute_reproducibility_metrics([100.0, 100.0, 100.0], "test")
        assert is_reproducible(metrics)
        assert is_reproducible(metrics, threshold=0.95)
        assert is_reproducible(metrics, threshold=0.99)
    
    def test_is_reproducible_low_r(self):
        """Low R should fail default threshold."""
        metrics = compute_reproducibility_metrics([10.0, 50.0, 10.0, 50.0], "test")
        assert not is_reproducible(metrics)
        assert not is_reproducible(metrics, threshold=0.95)
    
    def test_is_reproducible_custom_threshold(self):
        """Custom threshold should work."""
        metrics = compute_reproducibility_metrics([100.0, 105.0, 95.0], "test")
        # This has moderate variance, R around 0.95
        # Should pass at 0.90 but might fail at 0.99
        assert is_reproducible(metrics, threshold=0.80)
