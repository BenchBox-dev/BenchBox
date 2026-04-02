"""Latency measurement for multi-region testing.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import socket
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from benchbox.experimental.multiregion.config import Region, RegionConfig

logger = logging.getLogger(__name__)


@dataclass
class LatencyMeasurement:
    """A single latency measurement between two points."""

    source_region: Region
    target_region: Region
    latency_ms: float
    timestamp: float
    success: bool = True
    error: str | None = None
    measurement_type: str = "tcp"  # tcp, http, query


@dataclass
class LatencyProfile:
    """Latency profile for a region pair.

    Contains statistical summary of latency measurements.
    """

    source_region: Region
    target_region: Region
    measurements: list[LatencyMeasurement] = field(default_factory=list)

    @property
    def sample_count(self) -> int:
        """Number of successful measurements."""
        return len([m for m in self.measurements if m.success])

    @property
    def min_latency_ms(self) -> float:
        """Minimum latency in milliseconds."""
        successful = [m.latency_ms for m in self.measurements if m.success]
        return min(successful) if successful else 0.0

    @property
    def max_latency_ms(self) -> float:
        """Maximum latency in milliseconds."""
        successful = [m.latency_ms for m in self.measurements if m.success]
        return max(successful) if successful else 0.0

    @property
    def avg_latency_ms(self) -> float:
        """Average latency in milliseconds."""
        successful = [m.latency_ms for m in self.measurements if m.success]
        return statistics.mean(successful) if successful else 0.0

    @property
    def median_latency_ms(self) -> float:
        """Median latency in milliseconds."""
        successful = [m.latency_ms for m in self.measurements if m.success]
        return statistics.median(successful) if successful else 0.0

    @property
    def stdev_latency_ms(self) -> float:
        """Standard deviation of latency in milliseconds."""
        successful = [m.latency_ms for m in self.measurements if m.success]
        return statistics.stdev(successful) if len(successful) > 1 else 0.0

    @property
    def p95_latency_ms(self) -> float:
        """95th percentile latency in milliseconds."""
        successful = sorted([m.latency_ms for m in self.measurements if m.success])
        if not successful:
            return 0.0
        index = int(len(successful) * 0.95)
        return successful[min(index, len(successful) - 1)]

    @property
    def p99_latency_ms(self) -> float:
        """99th percentile latency in milliseconds."""
        successful = sorted([m.latency_ms for m in self.measurements if m.success])
        if not successful:
            return 0.0
        index = int(len(successful) * 0.99)
        return successful[min(index, len(successful) - 1)]

    @property
    def success_rate(self) -> float:
        """Success rate as percentage."""
        if not self.measurements:
            return 0.0
        return (self.sample_count / len(self.measurements)) * 100

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source_region": self.source_region.code,
            "target_region": self.target_region.code,
            "sample_count": self.sample_count,
            "min_latency_ms": round(self.min_latency_ms, 2),
            "max_latency_ms": round(self.max_latency_ms, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "median_latency_ms": round(self.median_latency_ms, 2),
            "stdev_latency_ms": round(self.stdev_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "p99_latency_ms": round(self.p99_latency_ms, 2),
            "success_rate": round(self.success_rate, 2),
        }


class LatencyMeasurer:
    """Measures network latency between regions.

    Supports multiple measurement methods:
    - TCP connection time
    - HTTP round-trip time
    - Database query latency
    """

    def __init__(
        self,
        source_region: Region,
        target_config: RegionConfig,
        connection_factory: Callable[[], Any] | None = None,
    ):
        """Initialize latency measurer.

        Args:
            source_region: Region where measurements originate
            target_config: Target region configuration
            connection_factory: Optional factory for database connections
        """
        self._source = source_region
        self._target = target_config
        self._connection_factory = connection_factory

    def measure_tcp_latency(self, timeout_seconds: float = 5.0) -> LatencyMeasurement:
        """Measure TCP connection latency.

        Args:
            timeout_seconds: Connection timeout

        Returns:
            Latency measurement
        """
        start = time.perf_counter()
        success = True
        error = None

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout_seconds)
            sock.connect((self._target.endpoint, self._target.port))
            sock.close()
        except TimeoutError:
            success = False
            error = "Connection timeout"
        except OSError as e:
            success = False
            error = str(e)

        end = time.perf_counter()
        latency_ms = (end - start) * 1000

        return LatencyMeasurement(
            source_region=self._source,
            target_region=self._target.region,
            latency_ms=latency_ms if success else 0,
            timestamp=time.time(),
            success=success,
            error=error,
            measurement_type="tcp",
        )

    def measure_query_latency(
        self,
        query: str = "SELECT 1",
        timeout_seconds: float = 30.0,
    ) -> LatencyMeasurement:
        """Measure database query latency.

        Args:
            query: Simple query to execute
            timeout_seconds: Query timeout

        Returns:
            Latency measurement
        """
        if self._connection_factory is None:
            return LatencyMeasurement(
                source_region=self._source,
                target_region=self._target.region,
                latency_ms=0,
                timestamp=time.time(),
                success=False,
                error="No connection factory provided",
                measurement_type="query",
            )

        start = time.perf_counter()
        success = True
        error = None

        try:
            conn = self._connection_factory()
            try:
                cursor = conn.cursor() if hasattr(conn, "cursor") else conn
                cursor.execute(query)
                if hasattr(cursor, "fetchone"):
                    cursor.fetchone()
            finally:
                if hasattr(conn, "close"):
                    conn.close()
        except Exception as e:
            success = False
            error = str(e)

        end = time.perf_counter()
        latency_ms = (end - start) * 1000

        return LatencyMeasurement(
            source_region=self._source,
            target_region=self._target.region,
            latency_ms=latency_ms if success else 0,
            timestamp=time.time(),
            success=success,
            error=error,
            measurement_type="query",
        )

    def measure_latency_profile(
        self,
        samples: int = 10,
        method: str = "tcp",
        interval_seconds: float = 1.0,
    ) -> LatencyProfile:
        """Collect multiple latency samples.

        Args:
            samples: Number of samples to collect
            method: Measurement method ("tcp" or "query")
            interval_seconds: Interval between samples

        Returns:
            Latency profile with statistics
        """
        profile = LatencyProfile(
            source_region=self._source,
            target_region=self._target.region,
        )

        logger.info(
            f"Measuring latency from {self._source.code} to {self._target.region.code} ({samples} samples, {method})"
        )

        for i in range(samples):
            if method == "tcp":
                measurement = self.measure_tcp_latency()
            elif method == "query":
                measurement = self.measure_query_latency()
            else:
                raise ValueError(f"Unknown measurement method: {method}")

            profile.measurements.append(measurement)

            if measurement.success:
                logger.debug(f"Sample {i + 1}: {measurement.latency_ms:.2f}ms")
            else:
                logger.warning(f"Sample {i + 1} failed: {measurement.error}")

            if i < samples - 1:
                time.sleep(interval_seconds)

        logger.info(
            f"Latency profile: avg={profile.avg_latency_ms:.2f}ms, "
            f"p95={profile.p95_latency_ms:.2f}ms, "
            f"success_rate={profile.success_rate:.1f}%"
        )

        return profile


def estimate_latency_from_distance(distance_km: float) -> tuple[float, float]:
    """Estimate latency range from geographic distance.

    Uses speed of light in fiber (~200,000 km/s) as baseline,
    with typical network overhead multiplier.

    Args:
        distance_km: Distance in kilometers

    Returns:
        Tuple of (min_latency_ms, typical_latency_ms)
    """
    # Speed of light in fiber is about 200,000 km/s
    # Typical overhead is 1.5-3x theoretical minimum
    speed_of_light_fiber = 200000  # km/s
    min_rtt = (distance_km / speed_of_light_fiber) * 2 * 1000  # ms, round trip

    # Add typical overhead
    typical_latency = min_rtt * 2.5  # Network overhead multiplier

    return (round(min_rtt, 2), round(typical_latency, 2))
