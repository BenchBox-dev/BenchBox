"""TPC benchmark metrics calculators.

This module provides standardized calculation of TPC-compliant benchmark metrics
including Power@Size, Throughput@Size, and QphH/QphDS composite metrics.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import math
import statistics
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

# Metric names accepted by :func:`calculate_named_metric`. This vocabulary is
# shared by every surface, so a name means the same thing in a CLI aggregate
# CSV, an MCP trends response, and a result bundle.
NAMED_METRICS = ("geometric_mean", "p50", "p95", "p99", "total_time", "mean")


def percentile_ms(times_ms: Sequence[float], p: float) -> float:
    """Return the p-th percentile of ``times_ms`` using the nearest-rank method.

    ``p`` is a fraction in ``[0, 1]``: ``percentile_ms(times, 0.95)`` is p95.

    BenchBox uses nearest-rank -- rank ``ceil(n * p)``, clamped to ``[1, n]`` --
    as its single percentile definition, for two reasons:

    1. It returns an actually-observed measurement. An interpolated percentile
       reports a duration no query ever took, and with small query counts the
       interpolating methods drift far: over 22 TPC-H timings, the exclusive
       method that ``statistics.quantiles(n=20)[18]`` implements returned a p95
       of 293.5 ms when the second-slowest query took 200 ms.
    2. It is what every published BenchBox result bundle already reports, so
       adopting it repo-wide changes no archived number.

    Returns 0.0 for an empty sequence.
    """
    sorted_times = sorted(times_ms)
    n = len(sorted_times)
    if n == 0:
        return 0.0
    rank = min(max(1, math.ceil(n * p)), n)
    return sorted_times[rank - 1]


def geometric_mean_ms(times_ms: Sequence[float]) -> float:
    """Return the geometric mean of the strictly positive values in ``times_ms``.

    Non-positive timings have no logarithm and are excluded rather than
    poisoning the result. Returns 0.0 when nothing positive remains.
    """
    positive = [t for t in times_ms if t > 0]
    if not positive:
        return 0.0
    return statistics.geometric_mean(positive)


def sample_stdev_ms(times_ms: Sequence[float]) -> float:
    """Return the sample standard deviation, or 0.0 for fewer than two values."""
    times_list = list(times_ms)
    if len(times_list) < 2:
        return 0.0
    return statistics.stdev(times_list)


def calculate_named_metric(times_ms: Sequence[float], metric: str) -> float:
    """Return one named summary metric over ``times_ms``.

    Args:
        times_ms: Execution times in milliseconds.
        metric: One of :data:`NAMED_METRICS`. Any other name falls back to the
            arithmetic mean, preserving the behavior of the surface-local
            implementations this function replaced.

    Returns:
        The metric value, or 0.0 when ``times_ms`` is empty.
    """
    times_list = list(times_ms)
    if not times_list:
        return 0.0

    if metric == "geometric_mean":
        return geometric_mean_ms(times_list)
    if metric == "p50":
        return percentile_ms(times_list, 0.50)
    if metric == "p95":
        return percentile_ms(times_list, 0.95)
    if metric == "p99":
        return percentile_ms(times_list, 0.99)
    if metric == "total_time":
        return sum(times_list)
    return statistics.mean(times_list)


class TPCMetricsCalculator:
    """Calculate TPC-compliant benchmark metrics.

    Implements metrics as defined in TPC-H and TPC-DS specifications:
    - Power@Size: Single-stream query throughput metric
    - Throughput@Size: Multi-stream concurrent throughput metric
    - QphH/QphDS: Composite metric combining power and throughput
    """

    @staticmethod
    def calculate_power_at_size(
        query_times_seconds: Sequence[float],
        scale_factor: float,
    ) -> float:
        """Calculate Power@Size metric (TPC-H/TPC-DS specification).

        Power@Size measures single-stream query performance:
        Power@Size = (SF * 3600) / geometric_mean(query_times)

        This represents queries per hour at the given scale factor.

        Args:
            query_times_seconds: List of query execution times in seconds
            scale_factor: Benchmark scale factor (e.g., 0.01, 1, 10, 100)

        Returns:
            Power@Size metric value, or 0.0 if calculation not possible
        """
        if not query_times_seconds:
            return 0.0

        # Filter out zero/negative times which would break geometric mean
        valid_times = [t for t in query_times_seconds if t > 0]
        if not valid_times:
            return 0.0

        geometric_mean = statistics.geometric_mean(valid_times)
        if geometric_mean <= 0:
            return 0.0

        return (scale_factor * 3600) / geometric_mean

    @staticmethod
    def calculate_throughput_at_size(
        total_queries: int,
        total_time_seconds: float,
        scale_factor: float,
        num_streams: int = 1,
    ) -> float:
        """Calculate Throughput@Size metric (TPC-H/TPC-DS specification).

        Throughput@Size measures concurrent multi-stream performance:
        Throughput@Size = (S * Q * SF * 3600) / T_s

        Where:
        - S = number of concurrent streams
        - Q = number of queries per stream
        - SF = scale factor
        - T_s = total elapsed time in seconds

        Args:
            total_queries: Total queries executed across all streams
            total_time_seconds: Total elapsed wall-clock time
            scale_factor: Benchmark scale factor
            num_streams: Number of concurrent streams

        Returns:
            Throughput@Size metric value, or 0.0 if calculation not possible
        """
        if total_time_seconds <= 0 or num_streams <= 0:
            return 0.0

        # Per TPC spec: (Streams * QueriesPerStream * SF * 3600) / TotalTime
        # But we have total_queries already = Streams * QueriesPerStream
        return (total_queries * scale_factor * 3600) / total_time_seconds

    @staticmethod
    def calculate_qph(power_at_size: float, throughput_at_size: float) -> float:
        """Calculate composite QphH/QphDS metric.

        The composite metric is the geometric mean of Power and Throughput:
        QphH = sqrt(Power@Size * Throughput@Size)

        Args:
            power_at_size: Power@Size metric value
            throughput_at_size: Throughput@Size metric value

        Returns:
            Composite QphH/QphDS metric, or 0.0 if either input is invalid
        """
        if power_at_size <= 0 or throughput_at_size <= 0:
            return 0.0

        return statistics.geometric_mean([power_at_size, throughput_at_size])

    @staticmethod
    def calculate_geometric_mean(times: Sequence[float]) -> float:
        """Calculate geometric mean of execution times.

        Args:
            times: Sequence of execution times (in any unit)

        Returns:
            Geometric mean of times, or 0.0 if not calculable
        """
        return geometric_mean_ms(times)


class TimingStatsCalculator:
    """Calculate timing statistics for query results."""

    @staticmethod
    def calculate(times_ms: Sequence[float]) -> dict[str, float]:
        """Calculate comprehensive timing statistics.

        Args:
            times_ms: List of execution times in milliseconds

        Returns:
            Dictionary containing:
            - total_ms: Sum of all times
            - avg_ms: Arithmetic mean
            - min_ms: Minimum time
            - max_ms: Maximum time
            - geometric_mean_ms: Geometric mean
            - stdev_ms: Standard deviation (0 if single value)
            - p50_ms: 50th percentile (median)
            - p90_ms: 90th percentile
            - p95_ms: 95th percentile
            - p99_ms: 99th percentile
        """
        if not times_ms:
            return {}

        times_list = list(times_ms)

        return {
            "total_ms": sum(times_list),
            "avg_ms": statistics.mean(times_list),
            "min_ms": min(times_list),
            "max_ms": max(times_list),
            "geometric_mean_ms": geometric_mean_ms(times_list),
            "stdev_ms": sample_stdev_ms(times_list),
            "p50_ms": percentile_ms(times_list, 0.50),
            "p90_ms": percentile_ms(times_list, 0.90),
            "p95_ms": percentile_ms(times_list, 0.95),
            "p99_ms": percentile_ms(times_list, 0.99),
        }

    @staticmethod
    def calculate_seconds(times_seconds: Sequence[float]) -> dict[str, float]:
        """Calculate timing statistics with times in seconds.

        Convenience method that returns results in seconds instead of milliseconds.

        Args:
            times_seconds: List of execution times in seconds

        Returns:
            Same structure as calculate() but with _s suffix instead of _ms
        """
        if not times_seconds:
            return {}

        times_ms = [t * 1000 for t in times_seconds]
        stats_ms = TimingStatsCalculator.calculate(times_ms)

        # Convert back to seconds
        return {key.replace("_ms", "_s"): value / 1000 for key, value in stats_ms.items()}
