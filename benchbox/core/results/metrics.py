"""TPC benchmark metrics calculators.

This module provides standardized calculation of TPC-compliant benchmark metrics
including Power@Size and Throughput@Size.

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

NON_POWER_TEST_TYPES = frozenset({"throughput", "maintenance"})
UNOFFICIAL_COMPLIANCE_CLASSES = frozenset({"unofficial_subscale", "unofficial_nonstandard"})
TPC_QUERIES_PER_STREAM = {"tpch": 22, "tpcds": 99}
_TPC_BENCHMARK_LABELS = {"tpch": "TPC-H", "tpcds": "TPC-DS"}


def percentile_ms(times_ms: Sequence[float], p: float) -> float:
    """Return the p-th percentile of ``times_ms`` using the nearest-rank method.

    ``p`` is a fraction in ``[0, 1]``: ``percentile_ms(times, 0.95)`` is p95.
    A ``p`` outside that range raises ``ValueError`` rather than being clamped.
    The surface-local implementations this function replaced took ``p`` on a
    0-100 scale, so ``percentile_ms(times, 95)`` is the likely porting mistake;
    clamping it would silently return ``max(times_ms)`` and call it a p95.

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

    Raises:
        ValueError: If ``p`` is outside ``[0, 1]``.
    """
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"percentile must be a fraction in [0, 1], got {p!r} (use 0.95 for p95, not 95)")

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
    def calculate_geometric_mean(times: Sequence[float]) -> float:
        """Calculate geometric mean of execution times.

        Args:
            times: Sequence of execution times (in any unit)

        Returns:
            Geometric mean of times, or 0.0 if not calculable
        """
        return geometric_mean_ms(times)

    @staticmethod
    def resolve_scale_factor(
        power_data: dict,
        throughput_data: dict,
        scale_factor: float | None = None,
    ) -> float:
        """Resolve scale factor from result data or explicit value.

        Moved from ``benchbox.cli.commands.metrics`` so the policy lives in
        core and any surface (CLI, MCP) uses the same resolution. The CLI
        translates ``ValueError`` to its console message + ``sys.exit(1)``.

        Args:
            power_data: Power test result dict.
            throughput_data: Throughput test result dict.
            scale_factor: Explicit SF when supplied, otherwise auto-detected.

        Returns:
            Resolved scale factor.

        Raises:
            ValueError: If SF cannot be auto-detected or the two files
                disagree.
        """
        if scale_factor is not None:
            return scale_factor
        sf_power = power_data.get("environment", {}).get("scale_factor") or power_data.get("benchmark", {}).get(
            "scale_factor"
        )
        sf_throughput = throughput_data.get("environment", {}).get("scale_factor") or throughput_data.get(
            "benchmark", {}
        ).get("scale_factor")
        if sf_power and sf_throughput:
            if sf_power != sf_throughput:
                raise ValueError(f"Scale factor mismatch: power={sf_power}, throughput={sf_throughput}")
            return sf_power
        raise ValueError("Could not auto-detect scale factor. Please specify --scale-factor")

    @staticmethod
    def metrics_refusal_reason(data: dict, label: str) -> str | None:
        summary = data.get("summary", {})
        tpc_metrics = summary.get("tpc_metrics") or {}
        if tpc_metrics.get("suppressed"):
            return f"{label} results have suppressed TPC metrics ({tpc_metrics.get('reason', 'suppressed')})"
        compliance_class = (data.get("benchmark") or {}).get("compliance_class")
        if compliance_class in UNOFFICIAL_COMPLIANCE_CLASSES:
            return f"{label} results are {compliance_class} and carry no official TPC metrics"
        failed = (summary.get("queries") or {}).get("failed") or 0
        if failed:
            return f"{label} results contain {failed} failed queries"
        throughput_phase = (data.get("phases") or {}).get("throughput_test") or {}
        if throughput_phase.get("status") == "FAILED":
            return f"{label} results have a failed throughput phase"
        return None

    @staticmethod
    def derive_tpc_metrics(
        power_data: dict,
        throughput_data: dict,
        scale_factor: float,
    ) -> tuple[float | None, float | None, float | None, float | None]:
        """Extract or derive Power@Size and Throughput@Size.

        Returns ``(power_at_size, throughput_at_size, power_time,
        throughput_time)``. Raises ``ValueError`` when either file has
        suppressed metrics, failed queries or a failed throughput phase.
        Derivation uses the final power iteration and the throughput phase
        wall duration, never summed query time.
        """
        for label, data in (("Power", power_data), ("Throughput", throughput_data)):
            reason = TPCMetricsCalculator.metrics_refusal_reason(data, label)
            if reason:
                raise ValueError(reason)

        power_metrics = power_data.get("summary", {}).get("tpc_metrics", {})
        throughput_metrics = throughput_data.get("summary", {}).get("tpc_metrics", {})
        power_at_size = power_metrics.get("power_at_size")
        throughput_at_size = throughput_metrics.get("throughput_at_size")

        power_times = TPCMetricsCalculator._final_power_iteration_times(power_data)
        power_time = sum(power_times) if power_times else None
        if power_at_size is None and power_times:
            power_at_size = TPCMetricsCalculator.calculate_power_at_size(power_times, scale_factor)

        phase = (throughput_data.get("phases") or {}).get("throughput_test") or {}
        duration_ms = phase.get("duration_ms")
        throughput_time = duration_ms / 1000.0 if duration_ms else None
        if throughput_at_size is None and throughput_time and phase.get("status") == "COMPLETED":
            num_streams = len(phase.get("stream_results") or []) or throughput_data.get("run", {}).get("streams") or 1
            per_stream = TPC_QUERIES_PER_STREAM.get(throughput_data.get("benchmark", {}).get("id"))
            if per_stream:
                throughput_at_size = TPCMetricsCalculator.calculate_throughput_at_size(
                    per_stream * num_streams,
                    throughput_time,
                    scale_factor,
                    num_streams,
                )
        return power_at_size, throughput_at_size, power_time, throughput_time

    @staticmethod
    def _final_power_iteration_times(power_data: dict) -> list[float]:
        rows = [
            q
            for q in power_data.get("queries", [])
            if q.get("run_type") == "measurement"
            and q.get("status") == "SUCCESS"
            and q.get("test_type") not in NON_POWER_TEST_TYPES
            and q.get("ms")
        ]
        if not rows:
            return []
        final_iteration = max(q.get("iter") or 0 for q in rows)
        return [q["ms"] / 1000.0 for q in rows if (q.get("iter") or 0) == final_iteration]

    @staticmethod
    def compute_qphh_result(
        power_data: dict,
        throughput_data: dict,
        scale_factor: float | None = None,
    ) -> dict:
        """Compute the Power@Size and Throughput@Size result dict.

        No composite QphH/QphDS is produced. Raises ``ValueError`` when
        derivation is refused or fails; CLI maps it to a console error.
        """
        sf = TPCMetricsCalculator.resolve_scale_factor(power_data, throughput_data, scale_factor)
        power_at_size, throughput_at_size, power_time, throughput_time = TPCMetricsCalculator.derive_tpc_metrics(
            power_data, throughput_data, sf
        )
        if power_at_size is None or throughput_at_size is None:
            raise ValueError("Could not derive Power@Size or Throughput@Size from result data")
        throughput_phase = (throughput_data.get("phases") or {}).get("throughput_test") or {}
        num_streams = (
            len(throughput_phase.get("stream_results") or [])
            or throughput_data.get("run", {}).get("streams")
            or throughput_data.get("environment", {}).get("num_streams", 1)
        )
        benchmark = throughput_data.get("benchmark", {})
        return {
            "benchmark": benchmark.get("name") or _TPC_BENCHMARK_LABELS.get(benchmark.get("id"), "TPC"),
            "scale_factor": sf,
            "num_streams": num_streams,
            "power_test_time": power_time,
            "throughput_test_time": throughput_time,
            "power_at_size": power_at_size,
            "throughput_at_size": throughput_at_size,
        }


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
