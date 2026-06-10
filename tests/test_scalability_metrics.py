"""
Tests for evaluation/metrics/scalability.py

Tests the scalability measurement implementations.
"""

from __future__ import annotations

import time

from evaluation.metrics.scalability import (
    HardwareInfo,
    SimulationTimer,
    get_hardware_info,
    compute_scalability_metrics,
    format_scalability_report,
    compare_scalability,
)


class TestSimulationTimer:
    """Tests for the SimulationTimer context manager."""
    
    def test_timer_measures_time(self):
        """Timer should report elapsed time consistent with a monotonic-clock
        reference. Loose upper bound, tightened lower bound, so the test
        passes on loaded CI runners without going flaky in either direction.
        """
        ref_start = time.monotonic()
        with SimulationTimer() as timer:
            time.sleep(0.1)
        ref_elapsed = time.monotonic() - ref_start
        assert timer.elapsed_seconds >= 0.09
        assert timer.elapsed_seconds <= ref_elapsed + 0.05
    
    def test_timer_zero_time(self):
        """Timer should handle instant operations."""
        with SimulationTimer() as timer:
            pass  # Do nothing
        
        assert timer.elapsed_seconds >= 0
        assert timer.elapsed_seconds < 0.1


class TestHardwareInfo:
    """Tests for hardware detection."""
    
    def test_get_hardware_info_returns_valid(self):
        """Hardware info should return reasonable values."""
        info = get_hardware_info()
        
        assert info.cpu_cores >= 1
        assert info.cpu_threads >= 1
        # Memory might be 0 if detection fails, but shouldn't be negative
        assert info.memory_gb >= 0


class TestScalabilityMetrics:
    """Tests for scalability metrics computation."""
    
    def test_compute_basic_metrics(self):
        metrics = compute_scalability_metrics(
            wall_clock_seconds=10.0,
            simulated_time_seconds=3600.0,
            vehicles_completed=100,
            engine="test",
        )
        
        assert metrics.wall_clock_seconds == 10.0
        assert metrics.simulated_time_seconds == 3600.0
        assert metrics.vehicles_completed == 100
        assert metrics.trips_per_second == 10.0  # 100/10
        assert metrics.simulated_to_realtime_ratio == 360.0  # 3600/10
    
    def test_compute_with_hardware_info(self):
        hw_info = HardwareInfo(
            cpu_model="Test CPU",
            cpu_cores=4,
            power_watts=100.0,
        )
        
        metrics = compute_scalability_metrics(
            wall_clock_seconds=10.0,
            simulated_time_seconds=3600.0,
            vehicles_completed=100,
            hardware_info=hw_info,
            engine="test",
        )
        
        assert metrics.trips_per_second_per_core == 2.5  # 10/4
        assert metrics.trips_per_second_per_watt == 0.1  # 10/100
    
    def test_compute_zero_runtime(self):
        metrics = compute_scalability_metrics(
            wall_clock_seconds=0.0,
            simulated_time_seconds=3600.0,
            vehicles_completed=100,
            engine="test",
        )
        
        assert metrics.trips_per_second == 0.0
        assert metrics.simulated_to_realtime_ratio == 0.0


class TestScalabilityReport:
    """Tests for scalability report formatting."""
    
    def test_format_report_basic(self):
        metrics = compute_scalability_metrics(
            wall_clock_seconds=10.0,
            simulated_time_seconds=3600.0,
            vehicles_completed=100,
            scenario_id="test_scenario",
            engine="sumo",
        )
        
        report = format_scalability_report(metrics)
        
        assert "SCALABILITY METRICS" in report
        assert "sumo" in report
        assert "test_scenario" in report
        assert "10.000 seconds" in report


class TestScalabilityComparison:
    """Tests for comparing scalability results."""
    
    def test_compare_scalability(self):
        baseline = compute_scalability_metrics(
            wall_clock_seconds=20.0,
            simulated_time_seconds=3600.0,
            vehicles_completed=100,
            engine="sumo",
        )
        
        faster = compute_scalability_metrics(
            wall_clock_seconds=10.0,  # 2x faster
            simulated_time_seconds=3600.0,
            vehicles_completed=100,
            engine="matsim",
        )

        comparison = compare_scalability(baseline, faster)

        assert comparison["runtime_speedup"] == 2.0  # 20/10
        assert comparison["throughput_ratio"] == 2.0  # faster has 2x throughput
        assert comparison["baseline_engine"] == "sumo"
        assert comparison["comparison_engine"] == "matsim"
