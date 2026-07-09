"""Concurrency analysis tools for load test results.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from benchbox.experimental.load_testing.executor import ConcurrentLoadResult

logger = logging.getLogger(__name__)


@dataclass
class QueueAnalysis:
    """Analysis of query queueing behavior."""

    # Wait time statistics (milliseconds)
    min_wait_ms: float
    max_wait_ms: float
    avg_wait_ms: float
    median_wait_ms: float
    p90_wait_ms: float
    p95_wait_ms: float
    p99_wait_ms: float
    stdev_wait_ms: float

    # Queue depth
    max_queue_depth: int
    avg_queue_depth: float

    # Time in queue vs execution
    queue_time_ratio: float  # Queue time / Total time

    # Queueing indicators
    queueing_detected: bool
    queueing_severity: str  # "none", "mild", "moderate", "severe"

    def __post_init__(self) -> None:
        """Determine queueing severity."""
        if self.avg_wait_ms < 10:
            self.queueing_severity = "none"
            self.queueing_detected = False
        elif self.avg_wait_ms < 100:
            self.queueing_severity = "mild"
            self.queueing_detected = True
        elif self.avg_wait_ms < 500:
            self.queueing_severity = "moderate"
            self.queueing_detected = True
        else:
            self.queueing_severity = "severe"
            self.queueing_detected = True


@dataclass
class ContentionAnalysis:
    """Analysis of resource contention patterns."""

    # Timing variability
    latency_stdev_ms: float
    latency_cv: float  # Coefficient of variation

    # Slow queries
    slow_query_count: int
    slow_query_ratio: float
    slowest_query_ms: float

    # Failure patterns
    failure_rate: float
    timeout_count: int
    connection_error_count: int

    # Contention indicators
    contention_detected: bool
    contention_type: str  # "none", "resource", "lock", "connection", "unknown"
    contention_severity: str  # "none", "mild", "moderate", "severe"

    # Recommendations
    recommendations: list[str] = field(default_factory=list)


@dataclass
class ScalingAnalysis:
    """Analysis of how performance scales with concurrency."""

    # Scaling metrics
    concurrency_levels: list[int]
    throughput_at_level: dict[int, float]  # Concurrency -> queries/sec
    latency_at_level: dict[int, float]  # Concurrency -> avg latency ms

    # Linear scaling analysis
    scaling_efficiency: float  # 1.0 = perfect linear scaling
    optimal_concurrency: int
    saturation_point: int | None  # Where performance starts degrading

    # Amdahl's law estimation
    parallelizable_fraction: float  # Estimated parallelizable portion

    # Scaling characteristics
    scaling_type: str  # "linear", "sublinear", "saturation", "degradation"


class LoadAnalyzer:
    """Analyzes concurrent load test results for patterns and bottlenecks."""

    def __init__(self, result: ConcurrentLoadResult):
        """Initialize analyzer with load test results.

        Args:
            result: Results from ConcurrentLoadExecutor
        """
        self._result = result

    def analyze_queue(self) -> QueueAnalysis:
        """Analyze queueing behavior from the load test.

        Returns:
            Queue analysis with wait time statistics
        """
        wait_times_ms = []
        execution_times_ms = []

        for stream in self._result.streams:
            for execution in stream.query_executions:
                if execution.queue_wait_time > 0:
                    wait_times_ms.append(execution.queue_wait_time * 1000)
                exec_time = (execution.end_time - execution.start_time) * 1000
                execution_times_ms.append(exec_time)

        if not wait_times_ms:
            # No queue tracking data
            return QueueAnalysis(
                min_wait_ms=0,
                max_wait_ms=0,
                avg_wait_ms=0,
                median_wait_ms=0,
                p90_wait_ms=0,
                p95_wait_ms=0,
                p99_wait_ms=0,
                stdev_wait_ms=0,
                max_queue_depth=0,
                avg_queue_depth=0,
                queue_time_ratio=0,
                queueing_detected=False,
                queueing_severity="none",
            )

        wait_times_ms.sort()
        total_queue_time = sum(wait_times_ms)
        total_exec_time = sum(execution_times_ms)

        return QueueAnalysis(
            min_wait_ms=min(wait_times_ms),
            max_wait_ms=max(wait_times_ms),
            avg_wait_ms=statistics.mean(wait_times_ms),
            median_wait_ms=statistics.median(wait_times_ms),
            p90_wait_ms=self._percentile(wait_times_ms, 90),
            p95_wait_ms=self._percentile(wait_times_ms, 95),
            p99_wait_ms=self._percentile(wait_times_ms, 99),
            stdev_wait_ms=statistics.stdev(wait_times_ms) if len(wait_times_ms) > 1 else 0,
            max_queue_depth=self._result.max_concurrency_reached,
            avg_queue_depth=len(self._result.streams) / max(1, self._result.total_duration_seconds),
            queue_time_ratio=total_queue_time / (total_queue_time + total_exec_time) if total_exec_time > 0 else 0,
            queueing_detected=False,  # Set by __post_init__
            queueing_severity="none",  # Set by __post_init__
        )

    def analyze_contention(self, slow_threshold_multiplier: float = 3.0) -> ContentionAnalysis:
        """Analyze resource contention patterns.

        Args:
            slow_threshold_multiplier: Queries taking > multiplier * median are slow

        Returns:
            Contention analysis with bottleneck identification
        """
        latencies_ms = []
        timeout_count = 0
        connection_errors = 0

        for stream in self._result.streams:
            for execution in stream.query_executions:
                latency = (execution.end_time - execution.start_time) * 1000
                latencies_ms.append(latency)

                if execution.error:
                    error_lower = execution.error.lower()
                    if "timeout" in error_lower:
                        timeout_count += 1
                    elif "connection" in error_lower or "connect" in error_lower:
                        connection_errors += 1

        if not latencies_ms:
            return ContentionAnalysis(
                latency_stdev_ms=0,
                latency_cv=0,
                slow_query_count=0,
                slow_query_ratio=0,
                slowest_query_ms=0,
                failure_rate=0,
                timeout_count=0,
                connection_error_count=0,
                contention_detected=False,
                contention_type="none",
                contention_severity="none",
                recommendations=[],
            )

        median_latency = statistics.median(latencies_ms)
        slow_threshold = median_latency * slow_threshold_multiplier
        slow_queries = [l for l in latencies_ms if l > slow_threshold]

        stdev = statistics.stdev(latencies_ms) if len(latencies_ms) > 1 else 0
        mean_latency = statistics.mean(latencies_ms)
        cv = stdev / mean_latency if mean_latency > 0 else 0

        # Determine contention type and severity
        contention_type = "none"
        contention_severity = "none"
        recommendations = []

        failure_rate = (
            self._result.total_queries_failed / self._result.total_queries_executed * 100
            if self._result.total_queries_executed > 0
            else 0
        )

        if connection_errors > 0:
            contention_type = "connection"
            recommendations.append("Increase connection pool size")
            recommendations.append("Check database max_connections setting")
        elif timeout_count > 0:
            contention_type = "resource"
            recommendations.append("Increase query timeout")
            recommendations.append("Optimize slow queries")
            recommendations.append("Consider adding indexes")
        elif cv > 1.0 and len(slow_queries) > len(latencies_ms) * 0.1:
            contention_type = "lock"
            recommendations.append("Check for lock contention")
            recommendations.append("Review transaction isolation levels")
            recommendations.append("Consider read replicas for read-heavy workloads")
        elif cv > 0.5:
            contention_type = "resource"
            recommendations.append("Monitor CPU and memory utilization")
            recommendations.append("Consider scaling up database resources")

        if contention_type != "none":
            if failure_rate > 10 or cv > 2.0:
                contention_severity = "severe"
            elif failure_rate > 5 or cv > 1.0:
                contention_severity = "moderate"
            else:
                contention_severity = "mild"

        return ContentionAnalysis(
            latency_stdev_ms=stdev,
            latency_cv=cv,
            slow_query_count=len(slow_queries),
            slow_query_ratio=len(slow_queries) / len(latencies_ms) if latencies_ms else 0,
            slowest_query_ms=max(latencies_ms),
            failure_rate=failure_rate,
            timeout_count=timeout_count,
            connection_error_count=connection_errors,
            contention_detected=contention_type != "none",
            contention_type=contention_type,
            contention_severity=contention_severity,
            recommendations=recommendations,
        )

    def analyze_scaling(self, results_by_concurrency: dict[int, ConcurrentLoadResult] | None = None) -> ScalingAnalysis:
        """Analyze how performance scales with concurrency.

        Args:
            results_by_concurrency: Optional dict mapping concurrency -> results.
                If not provided, uses data from single result.

        Returns:
            Scaling analysis with efficiency metrics
        """
        if results_by_concurrency is None:
            return self._analyze_scaling_single()

        return self._analyze_scaling_multi(results_by_concurrency)

    def _analyze_scaling_single(self) -> ScalingAnalysis:
        """Scaling analysis from a single concurrency result."""
        concurrency_levels = [self._result.max_concurrency_reached]
        throughput_at_level = {self._result.max_concurrency_reached: self._result.overall_throughput}

        latencies = self._collect_latencies(self._result)
        avg_latency = statistics.mean(latencies) if latencies else 0
        latency_at_level = {self._result.max_concurrency_reached: avg_latency}

        return ScalingAnalysis(
            concurrency_levels=concurrency_levels,
            throughput_at_level=throughput_at_level,
            latency_at_level=latency_at_level,
            scaling_efficiency=1.0,
            optimal_concurrency=self._result.max_concurrency_reached,
            saturation_point=None,
            parallelizable_fraction=0.5,
            scaling_type="unknown",
        )

    def _analyze_scaling_multi(self, results_by_concurrency: dict[int, ConcurrentLoadResult]) -> ScalingAnalysis:
        """Full scaling analysis from multiple concurrency levels."""
        concurrency_levels = sorted(results_by_concurrency.keys())
        throughput_at_level: dict[int, float] = {}
        latency_at_level: dict[int, float] = {}

        for level in concurrency_levels:
            result = results_by_concurrency[level]
            throughput_at_level[level] = result.overall_throughput
            latencies = self._collect_latencies(result)
            latency_at_level[level] = statistics.mean(latencies) if latencies else 0

        avg_efficiency = self._compute_scaling_efficiency(concurrency_levels, throughput_at_level)
        optimal = max(concurrency_levels, key=lambda x: throughput_at_level[x])
        saturation = self._find_saturation_point(concurrency_levels, throughput_at_level)
        p = self._estimate_parallelizable_fraction(concurrency_levels, throughput_at_level)

        if avg_efficiency > 0.9:
            scaling_type = "linear"
        elif avg_efficiency > 0.5:
            scaling_type = "sublinear"
        elif saturation is not None:
            scaling_type = "saturation"
        else:
            scaling_type = "degradation"

        return ScalingAnalysis(
            concurrency_levels=concurrency_levels,
            throughput_at_level=throughput_at_level,
            latency_at_level=latency_at_level,
            scaling_efficiency=avg_efficiency,
            optimal_concurrency=optimal,
            saturation_point=saturation,
            parallelizable_fraction=p,
            scaling_type=scaling_type,
        )

    @staticmethod
    def _collect_latencies(result: ConcurrentLoadResult) -> list[float]:
        """Collect all query latencies in milliseconds from a load result."""
        return [(ex.end_time - ex.start_time) * 1000 for stream in result.streams for ex in stream.query_executions]

    @staticmethod
    def _compute_scaling_efficiency(concurrency_levels: list[int], throughput_at_level: dict[int, float]) -> float:
        """Calculate average scaling efficiency across concurrency levels."""
        if len(concurrency_levels) < 2:
            return 1.0
        base_level = concurrency_levels[0]
        base_throughput = throughput_at_level[base_level]

        efficiencies = []
        for level in concurrency_levels[1:]:
            expected = base_throughput * (level / base_level)
            actual = throughput_at_level[level]
            efficiencies.append(actual / expected if expected > 0 else 0)

        return statistics.mean(efficiencies) if efficiencies else 1.0

    @staticmethod
    def _find_saturation_point(concurrency_levels: list[int], throughput_at_level: dict[int, float]) -> int | None:
        """Find the concurrency level where throughput stops increasing (<10% gain)."""
        for i, level in enumerate(concurrency_levels[:-1]):
            next_level = concurrency_levels[i + 1]
            if throughput_at_level[next_level] < throughput_at_level[level] * 1.1:
                return level
        return None

    @staticmethod
    def _estimate_parallelizable_fraction(
        concurrency_levels: list[int], throughput_at_level: dict[int, float]
    ) -> float:
        """Estimate parallelizable fraction using Amdahl's law."""
        if len(concurrency_levels) < 2:
            return 0.5
        max_level = max(concurrency_levels)
        base_throughput = throughput_at_level[concurrency_levels[0]]
        max_throughput = throughput_at_level[max_level]
        speedup = max_throughput / base_throughput if base_throughput > 0 else 1

        if speedup > 1 and max_level > 1:
            p = (speedup - 1) / (speedup - 1 / max_level)
            return max(0.0, min(1.0, p))
        return 0.5

    def get_summary(self) -> dict:
        """Get a summary of all analyses.

        Returns:
            Dictionary with analysis summaries
        """
        queue_analysis = self.analyze_queue()
        contention_analysis = self.analyze_contention()
        scaling_analysis = self.analyze_scaling()

        return {
            "test_info": {
                "duration_seconds": self._result.total_duration_seconds,
                "total_queries": self._result.total_queries_executed,
                "throughput_qps": self._result.overall_throughput,
                "success_rate": self._result.success_rate,
                "max_concurrency": self._result.max_concurrency_reached,
            },
            "queue": {
                "detected": queue_analysis.queueing_detected,
                "severity": queue_analysis.queueing_severity,
                "avg_wait_ms": queue_analysis.avg_wait_ms,
                "p99_wait_ms": queue_analysis.p99_wait_ms,
            },
            "contention": {
                "detected": contention_analysis.contention_detected,
                "type": contention_analysis.contention_type,
                "severity": contention_analysis.contention_severity,
                "recommendations": contention_analysis.recommendations,
            },
            "scaling": {
                "type": scaling_analysis.scaling_type,
                "efficiency": scaling_analysis.scaling_efficiency,
                "optimal_concurrency": scaling_analysis.optimal_concurrency,
            },
        }

    @staticmethod
    def _percentile(sorted_data: list[float], p: float) -> float:
        """Calculate percentile from sorted data."""
        if not sorted_data:
            return 0.0
        index = int((p / 100) * len(sorted_data))
        index = min(index, len(sorted_data) - 1)
        return sorted_data[index]
