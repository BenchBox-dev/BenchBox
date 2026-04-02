"""Tests for latency measurement module.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import time

import pytest

from benchbox.experimental.multiregion.latency import (
    LatencyMeasurement,
    LatencyMeasurer,
    LatencyProfile,
    estimate_latency_from_distance,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestLatencyMeasurement:
    """Tests for LatencyMeasurement dataclass."""

    def test_basic_creation(self, us_east_region, eu_west_region):
        """Should create measurement record."""
        measurement = LatencyMeasurement(
            source_region=us_east_region,
            target_region=eu_west_region,
            latency_ms=75.5,
            timestamp=time.time(),
            success=True,
        )
        assert measurement.latency_ms == 75.5
        assert measurement.success is True

    def test_failed_measurement(self, us_east_region, eu_west_region):
        """Should record failed measurement."""
        measurement = LatencyMeasurement(
            source_region=us_east_region,
            target_region=eu_west_region,
            latency_ms=0,
            timestamp=time.time(),
            success=False,
            error="Connection timeout",
        )
        assert measurement.success is False
        assert measurement.error == "Connection timeout"

    def test_measurement_type(self, us_east_region, eu_west_region):
        """Should record measurement type."""
        measurement = LatencyMeasurement(
            source_region=us_east_region,
            target_region=eu_west_region,
            latency_ms=50,
            timestamp=time.time(),
            success=True,
            measurement_type="query",
        )
        assert measurement.measurement_type == "query"


class TestLatencyProfile:
    """Tests for LatencyProfile dataclass."""

    @pytest.fixture
    def profile_with_measurements(self, us_east_region, eu_west_region):
        """Create profile with sample measurements."""
        profile = LatencyProfile(
            source_region=us_east_region,
            target_region=eu_west_region,
        )
        latencies = [70, 75, 80, 72, 78, 85, 73, 77, 90, 76]
        for i, lat in enumerate(latencies):
            profile.measurements.append(
                LatencyMeasurement(
                    source_region=us_east_region,
                    target_region=eu_west_region,
                    latency_ms=float(lat),
                    timestamp=time.time() + i,
                    success=True,
                )
            )
        return profile

    def test_sample_count(self, profile_with_measurements):
        """Should count successful samples."""
        assert profile_with_measurements.sample_count == 10

    def test_min_latency(self, profile_with_measurements):
        """Should calculate min latency."""
        assert profile_with_measurements.min_latency_ms == 70

    def test_max_latency(self, profile_with_measurements):
        """Should calculate max latency."""
        assert profile_with_measurements.max_latency_ms == 90

    def test_avg_latency(self, profile_with_measurements):
        """Should calculate average latency."""
        # (70+75+80+72+78+85+73+77+90+76) / 10 = 77.6
        assert 77 < profile_with_measurements.avg_latency_ms < 78

    def test_median_latency(self, profile_with_measurements):
        """Should calculate median latency."""
        # Sorted: 70,72,73,75,76,77,78,80,85,90 -> median = (76+77)/2 = 76.5
        assert 76 <= profile_with_measurements.median_latency_ms <= 77

    def test_stdev_latency(self, profile_with_measurements):
        """Should calculate standard deviation."""
        assert profile_with_measurements.stdev_latency_ms > 0

    def test_p95_latency(self, profile_with_measurements):
        """Should calculate p95 latency."""
        assert profile_with_measurements.p95_latency_ms >= 85

    def test_success_rate(self, profile_with_measurements):
        """Should calculate success rate."""
        assert profile_with_measurements.success_rate == 100.0

    def test_success_rate_with_failures(self, us_east_region, eu_west_region):
        """Should handle failed measurements in success rate."""
        profile = LatencyProfile(
            source_region=us_east_region,
            target_region=eu_west_region,
        )
        profile.measurements.append(LatencyMeasurement(us_east_region, eu_west_region, 50, time.time(), True))
        profile.measurements.append(LatencyMeasurement(us_east_region, eu_west_region, 0, time.time(), False))
        assert profile.success_rate == 50.0

    def test_to_dict(self, profile_with_measurements):
        """Should convert to dictionary."""
        d = profile_with_measurements.to_dict()
        assert "source_region" in d
        assert "target_region" in d
        assert "avg_latency_ms" in d
        assert "p95_latency_ms" in d

    def test_empty_profile(self, us_east_region, eu_west_region):
        """Should handle empty profile."""
        profile = LatencyProfile(
            source_region=us_east_region,
            target_region=eu_west_region,
        )
        assert profile.sample_count == 0
        assert profile.min_latency_ms == 0
        assert profile.avg_latency_ms == 0
        assert profile.success_rate == 0


class TestLatencyMeasurer:
    """Tests for LatencyMeasurer class."""

    def test_tcp_measurement_unreachable(self, us_east_region, eu_west_config):
        """Should handle unreachable endpoint."""
        measurer = LatencyMeasurer(
            source_region=us_east_region,
            target_config=eu_west_config,
        )
        # Use a very short timeout to fail quickly
        measurement = measurer.measure_tcp_latency(timeout_seconds=0.1)
        # Should complete (may fail due to connection)
        assert measurement is not None

    def test_query_measurement_no_factory(self, us_east_region, eu_west_config):
        """Should handle missing connection factory."""
        measurer = LatencyMeasurer(
            source_region=us_east_region,
            target_config=eu_west_config,
            connection_factory=None,
        )
        measurement = measurer.measure_query_latency()
        assert measurement.success is False
        assert "No connection factory" in measurement.error

    def test_latency_profile_invalid_method(self, us_east_region, eu_west_config):
        """Should raise for invalid measurement method."""
        measurer = LatencyMeasurer(
            source_region=us_east_region,
            target_config=eu_west_config,
        )
        with pytest.raises(ValueError, match="Unknown measurement method"):
            measurer.measure_latency_profile(samples=1, method="invalid")


class TestEstimateLatencyFromDistance:
    """Tests for estimate_latency_from_distance function."""

    def test_short_distance(self):
        """Should estimate low latency for short distance."""
        min_lat, typical_lat = estimate_latency_from_distance(100)  # 100 km
        assert min_lat < 5  # Less than 5ms
        assert typical_lat > min_lat

    def test_transatlantic(self):
        """Should estimate reasonable transatlantic latency."""
        min_lat, typical_lat = estimate_latency_from_distance(5500)  # ~5500 km
        # Theoretical minimum ~55ms, typical ~140ms
        assert 30 < min_lat < 80
        assert 100 < typical_lat < 200

    def test_transpacific(self):
        """Should estimate higher latency for longer distance."""
        min_lat, typical_lat = estimate_latency_from_distance(10000)
        assert min_lat > 50
        assert typical_lat > 150

    def test_zero_distance(self):
        """Should handle zero distance."""
        min_lat, typical_lat = estimate_latency_from_distance(0)
        assert min_lat == 0
        assert typical_lat == 0
