from __future__ import annotations

import math

import pytest

from benchbox.core.results.metrics import (
    TimingStatsCalculator,
    TPCMetricsCalculator,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestTPCMetricsCalculator:
    def test_calculate_power_at_size_basic(self) -> None:

        times = [1.0, 1.0, 1.0, 1.0]
        result = TPCMetricsCalculator.calculate_power_at_size(times, scale_factor=1.0)
        assert result == 3600.0

    def test_calculate_power_at_size_different_scale_factor(self) -> None:
        times = [1.0, 1.0, 1.0, 1.0]

        result = TPCMetricsCalculator.calculate_power_at_size(times, scale_factor=10.0)
        assert result == 36000.0

        result = TPCMetricsCalculator.calculate_power_at_size(times, scale_factor=0.01)
        assert result == 36.0

    def test_calculate_power_at_size_varied_times(self) -> None:

        times = [1.0, 2.0, 4.0, 8.0]
        result = TPCMetricsCalculator.calculate_power_at_size(times, scale_factor=1.0)
        expected_geom_mean = math.pow(64, 0.25)
        expected = 3600.0 / expected_geom_mean
        assert abs(result - expected) < 0.01

    def test_calculate_power_at_size_empty_list(self) -> None:
        result = TPCMetricsCalculator.calculate_power_at_size([], scale_factor=1.0)
        assert result == 0.0

    def test_calculate_power_at_size_with_zeros(self) -> None:
        times = [0.0, 1.0, 1.0, 0.0]
        result = TPCMetricsCalculator.calculate_power_at_size(times, scale_factor=1.0)

        assert result == 3600.0

    def test_calculate_power_at_size_all_zeros(self) -> None:
        times = [0.0, 0.0, 0.0]
        result = TPCMetricsCalculator.calculate_power_at_size(times, scale_factor=1.0)
        assert result == 0.0

    def test_calculate_power_at_size_matches_legacy_power_formula(self) -> None:
        times = [float(i + 1) for i in range(22)]

        result = TPCMetricsCalculator.calculate_power_at_size(times, scale_factor=10.0)

        assert result == pytest.approx((10.0 * 3600.0) / math.prod(times) ** (1 / len(times)))

    def test_calculate_throughput_at_size_basic(self) -> None:

        result = TPCMetricsCalculator.calculate_throughput_at_size(
            total_queries=100,
            total_time_seconds=100.0,
            scale_factor=1.0,
            num_streams=1,
        )
        assert result == 3600.0

    def test_calculate_throughput_at_size_with_streams(self) -> None:

        result = TPCMetricsCalculator.calculate_throughput_at_size(
            total_queries=100,
            total_time_seconds=100.0,
            scale_factor=1.0,
            num_streams=2,
        )

        assert result == 3600.0

    def test_calculate_throughput_at_size_zero_time(self) -> None:
        result = TPCMetricsCalculator.calculate_throughput_at_size(
            total_queries=100,
            total_time_seconds=0.0,
            scale_factor=1.0,
            num_streams=1,
        )
        assert result == 0.0

    def test_calculate_throughput_at_size_zero_streams(self) -> None:
        result = TPCMetricsCalculator.calculate_throughput_at_size(
            total_queries=100,
            total_time_seconds=100.0,
            scale_factor=1.0,
            num_streams=0,
        )
        assert result == 0.0

    def test_calculate_throughput_at_size_uses_total_query_count(self) -> None:
        result = TPCMetricsCalculator.calculate_throughput_at_size(
            total_queries=44,
            total_time_seconds=22.0,
            scale_factor=1.0,
            num_streams=2,
        )

        assert result == pytest.approx((44 * 3600.0) / 22.0)

    def test_calculate_qph_basic(self) -> None:

        result = TPCMetricsCalculator.calculate_qph(
            power_at_size=100.0,
            throughput_at_size=100.0,
        )
        assert abs(result - 100.0) < 0.0001

    def test_calculate_qph_different_values(self) -> None:

        result = TPCMetricsCalculator.calculate_qph(
            power_at_size=400.0,
            throughput_at_size=100.0,
        )
        assert abs(result - 200.0) < 0.0001

    def test_calculate_qph_matches_legacy_tpc_h_and_tpc_ds_composite_formula(self) -> None:
        assert TPCMetricsCalculator.calculate_qph(1000.0, 4000.0) == pytest.approx(2000.0)
        assert TPCMetricsCalculator.calculate_qph(900.0, 100.0) == pytest.approx(300.0)

    def test_calculate_qph_zero_power(self) -> None:
        result = TPCMetricsCalculator.calculate_qph(
            power_at_size=0.0,
            throughput_at_size=100.0,
        )
        assert result == 0.0

    def test_calculate_qph_zero_throughput(self) -> None:
        result = TPCMetricsCalculator.calculate_qph(
            power_at_size=100.0,
            throughput_at_size=0.0,
        )
        assert result == 0.0

    def test_calculate_geometric_mean_basic(self) -> None:
        times = [1.0, 1.0, 1.0, 1.0]
        result = TPCMetricsCalculator.calculate_geometric_mean(times)
        assert result == 1.0

    def test_calculate_geometric_mean_varied(self) -> None:
        times = [1.0, 2.0, 4.0, 8.0]
        result = TPCMetricsCalculator.calculate_geometric_mean(times)
        expected = math.pow(64, 0.25)
        assert abs(result - expected) < 0.0001

    def test_calculate_geometric_mean_empty(self) -> None:
        result = TPCMetricsCalculator.calculate_geometric_mean([])
        assert result == 0.0

    def test_calculate_geometric_mean_filters_zeros(self) -> None:
        times = [0.0, 1.0, 1.0, 0.0]
        result = TPCMetricsCalculator.calculate_geometric_mean(times)
        assert result == 1.0


class TestTimingStatsCalculator:
    def test_calculate_basic(self) -> None:
        times_ms = [100.0, 200.0, 300.0, 400.0, 500.0]
        result = TimingStatsCalculator.calculate(times_ms)

        assert result["total_ms"] == 1500.0
        assert result["avg_ms"] == 300.0
        assert result["min_ms"] == 100.0
        assert result["max_ms"] == 500.0
        assert "geometric_mean_ms" in result
        assert "stdev_ms" in result
        assert "p50_ms" in result
        assert "p90_ms" in result
        assert "p95_ms" in result
        assert "p99_ms" in result

    def test_calculate_empty(self) -> None:
        result = TimingStatsCalculator.calculate([])
        assert result == {}

    def test_calculate_single_value(self) -> None:
        times_ms = [100.0]
        result = TimingStatsCalculator.calculate(times_ms)

        assert result["total_ms"] == 100.0
        assert result["avg_ms"] == 100.0
        assert result["min_ms"] == 100.0
        assert result["max_ms"] == 100.0
        assert result["stdev_ms"] == 0.0

    def test_calculate_percentiles(self) -> None:

        times_ms = [float(i) for i in range(1, 101)]
        result = TimingStatsCalculator.calculate(times_ms)

        assert result["p50_ms"] == 50.0
        assert result["p90_ms"] == 90.0
        assert result["p95_ms"] == 95.0
        assert result["p99_ms"] == 99.0

    def test_calculate_seconds(self) -> None:
        times_seconds = [0.1, 0.2, 0.3, 0.4, 0.5]
        result = TimingStatsCalculator.calculate_seconds(times_seconds)

        assert result["total_s"] == 1.5
        assert result["avg_s"] == 0.3
        assert result["min_s"] == 0.1
        assert result["max_s"] == 0.5
        assert "geometric_mean_s" in result
        assert "stdev_s" in result

    def test_calculate_seconds_empty(self) -> None:
        result = TimingStatsCalculator.calculate_seconds([])
        assert result == {}
