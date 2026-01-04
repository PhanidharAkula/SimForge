"""
Tests for evaluation/metrics/fidelity.py

Tests the RMSE, GEH, and KS statistic implementations.
"""

from __future__ import annotations

import math
import pytest

from evaluation.metrics.fidelity import (
    compute_rmse,
    compute_geh,
    compute_geh_batch,
    compute_ks_statistic,
    compute_fidelity_metrics,
    interpret_geh,
)


class TestRMSE:
    """Tests for Root Mean Square Error computation."""
    
    def test_rmse_identical_values(self):
        """RMSE should be 0 when observed == simulated."""
        observed = [100.0, 200.0, 300.0]
        simulated = [100.0, 200.0, 300.0]
        assert compute_rmse(observed, simulated) == 0.0
    
    def test_rmse_known_values(self):
        """RMSE should match hand-calculated value."""
        # Errors: [2, -2, 2, -2] => squared: [4, 4, 4, 4] => MSE = 4 => RMSE = 2
        observed = [10.0, 20.0, 30.0, 40.0]
        simulated = [12.0, 18.0, 32.0, 38.0]
        assert abs(compute_rmse(observed, simulated) - 2.0) < 1e-6
    
    def test_rmse_single_value(self):
        """RMSE should work with single value."""
        observed = [100.0]
        simulated = [110.0]
        assert abs(compute_rmse(observed, simulated) - 10.0) < 1e-6
    
    def test_rmse_length_mismatch_raises(self):
        """RMSE should raise ValueError for length mismatch."""
        with pytest.raises(ValueError):
            compute_rmse([1.0, 2.0], [1.0])
    
    def test_rmse_empty_raises(self):
        """RMSE should raise ValueError for empty lists."""
        with pytest.raises(ValueError):
            compute_rmse([], [])


class TestGEH:
    """Tests for GEH statistic computation."""
    
    def test_geh_identical_values(self):
        """GEH should be 0 when observed == simulated."""
        assert compute_geh(100.0, 100.0) == 0.0
    
    def test_geh_known_acceptable(self):
        """GEH < 5 is considered acceptable in traffic engineering."""
        # GEH = sqrt(2 * (105-100)^2 / (105+100)) = sqrt(50/205) ≈ 0.49
        geh = compute_geh(100.0, 105.0)
        assert geh < 5.0  # Should be acceptable
        assert geh < 1.0  # Actually quite close
    
    def test_geh_known_poor(self):
        """GEH > 10 is considered poor fit."""
        # Very large difference needed for GEH > 10
        # GEH(100, 300) = sqrt(2*(300-100)^2/(300+100)) = sqrt(80000/400) = sqrt(200) ≈ 14.1
        geh = compute_geh(100.0, 300.0)
        assert geh > 10.0  # Should be poor fit
    
    def test_geh_symmetric(self):
        """GEH should be symmetric (same result if you swap observed/simulated)."""
        geh1 = compute_geh(100.0, 120.0)
        geh2 = compute_geh(120.0, 100.0)
        assert abs(geh1 - geh2) < 1e-6
    
    def test_geh_zero_returns_inf(self):
        """GEH should return inf for zero values."""
        assert compute_geh(0.0, 100.0) == float('inf')
        assert compute_geh(100.0, 0.0) == float('inf')


class TestGEHBatch:
    """Tests for batch GEH computation."""
    
    def test_geh_batch_basic(self):
        """Batch GEH should compute mean and percentage."""
        observed = [100.0, 200.0, 300.0]
        simulated = [105.0, 195.0, 310.0]  # Small differences
        
        mean_geh, pct_below_5, geh_values = compute_geh_batch(observed, simulated)
        
        assert len(geh_values) == 3
        assert pct_below_5 == 100.0  # All should be acceptable
        assert mean_geh < 5.0
    
    def test_geh_batch_mixed(self):
        """Batch GEH with mixed acceptable/poor fits."""
        observed = [100.0, 100.0]
        simulated = [105.0, 200.0]  # First acceptable, second poor
        
        mean_geh, pct_below_5, geh_values = compute_geh_batch(observed, simulated)
        
        assert pct_below_5 == 50.0  # One of two is acceptable


class TestKSStatistic:
    """Tests for Kolmogorov-Smirnov statistic computation."""
    
    def test_ks_identical_distributions(self):
        """KS should be 0 for identical distributions."""
        dist = [1.0, 2.0, 3.0, 4.0, 5.0]
        ks_stat, _ = compute_ks_statistic(dist, dist.copy())
        assert ks_stat == 0.0
    
    def test_ks_completely_different(self):
        """KS should be 1.0 for non-overlapping distributions."""
        dist_a = [1.0, 2.0, 3.0]
        dist_b = [10.0, 11.0, 12.0]
        ks_stat, _ = compute_ks_statistic(dist_a, dist_b)
        assert ks_stat == 1.0
    
    def test_ks_similar_distributions(self):
        """KS should be small for similar distributions."""
        dist_a = [1.0, 2.0, 3.0, 4.0, 5.0]
        dist_b = [1.1, 2.1, 2.9, 4.1, 4.9]  # Slightly shifted
        ks_stat, critical = compute_ks_statistic(dist_a, dist_b)
        assert ks_stat < 0.5  # Should be relatively small
        assert critical is not None
    
    def test_ks_critical_value_exists(self):
        """KS should return a critical value for α=0.05."""
        dist_a = [1.0, 2.0, 3.0, 4.0, 5.0]
        dist_b = [2.0, 3.0, 4.0, 5.0, 6.0]
        _, critical = compute_ks_statistic(dist_a, dist_b)
        assert critical is not None
        assert critical > 0


class TestInterpretGEH:
    """Tests for GEH interpretation."""
    
    def test_interpret_acceptable(self):
        assert interpret_geh(3.0) == "acceptable"
        assert interpret_geh(4.9) == "acceptable"
    
    def test_interpret_warrants_investigation(self):
        assert interpret_geh(5.0) == "warrants investigation"
        assert interpret_geh(9.9) == "warrants investigation"
    
    def test_interpret_poor(self):
        assert interpret_geh(10.0) == "poor fit"
        assert interpret_geh(20.0) == "poor fit"


class TestFidelityMetrics:
    """Tests for combined fidelity metrics computation."""
    
    def test_compute_fidelity_metrics_basic(self):
        """Test full fidelity metrics computation."""
        observed_counts = [100.0, 200.0, 300.0, 400.0, 500.0]
        simulated_counts = [105.0, 198.0, 305.0, 395.0, 510.0]
        
        metrics = compute_fidelity_metrics(
            observed_counts, 
            simulated_counts,
        )
        
        assert metrics.n_observations == 5
        assert metrics.rmse >= 0
        assert metrics.geh_mean >= 0
        assert 0 <= metrics.geh_pct_below_5 <= 100
    
    def test_compute_fidelity_metrics_with_travel_times(self):
        """Test fidelity metrics with travel time distributions."""
        observed_counts = [100.0, 200.0]
        simulated_counts = [105.0, 195.0]
        observed_tt = [10.0, 12.0, 14.0, 16.0, 18.0]
        simulated_tt = [11.0, 13.0, 15.0, 17.0, 19.0]
        
        metrics = compute_fidelity_metrics(
            observed_counts,
            simulated_counts,
            observed_tt,
            simulated_tt,
        )
        
        assert metrics.ks_statistic >= 0
        assert metrics.ks_critical_value is not None
