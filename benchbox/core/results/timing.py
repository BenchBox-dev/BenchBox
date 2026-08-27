"""Timing collection and analysis for benchmark queries.

Provides detailed timing metrics, statistical analysis, and integration
with platform adapters for performance measurement.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
import statistics
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from benchbox.utils.clock import utc_now

logger = logging.getLogger(__name__)


@dataclass
class QueryTiming:
    """Detailed timing information for a single query execution."""

    # Query identification
    query_id: str
    query_name: Optional[str] = None
    execution_sequence: int = 0

    # Core timing metrics (all in seconds)
    execution_time: float = 0.0
    parse_time: Optional[float] = None
    optimization_time: Optional[float] = None
    execution_only_time: Optional[float] = None
    fetch_time: Optional[float] = None

    # Detailed timing breakdown
    timing_breakdown: dict[str, float] = field(default_factory=dict)

    # Query characteristics
    rows_returned: int = 0
    bytes_processed: Optional[int] = None
    tables_accessed: list[str] = field(default_factory=list)

    # Execution context
    timestamp: datetime = field(default_factory=datetime.now)
    thread_id: Optional[str] = None
    connection_id: Optional[str] = None

    # Performance metrics
    rows_per_second: Optional[float] = None
    bytes_per_second: Optional[float] = None
    cpu_time: Optional[float] = None
    memory_peak: Optional[int] = None

    # Status and error information
    status: str = "SUCCESS"  # SUCCESS, ERROR, TIMEOUT, CANCELLED
    error_message: Optional[str] = None
    warning_count: int = 0

    # Platform-specific metrics
    platform_metrics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Calculate derived metrics after initialization."""
        if self.execution_time > 0 and self.rows_returned > 0:
            self.rows_per_second = self.rows_returned / self.execution_time

        if self.execution_time > 0 and self.bytes_processed:
            self.bytes_per_second = self.bytes_processed / self.execution_time

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "query_id": self.query_id,
            "query_name": self.query_name,
            "execution_sequence": self.execution_sequence,
            "execution_time_seconds": self.execution_time,
            "parse_time": self.parse_time,
            "optimization_time": self.optimization_time,
            "execution_only_time": self.execution_only_time,
            "fetch_time": self.fetch_time,
            "timing_breakdown": self.timing_breakdown,
            "rows_returned": self.rows_returned,
            "bytes_processed": self.bytes_processed,
            "tables_accessed": self.tables_accessed,
            "timestamp": self.timestamp.isoformat(),
            "thread_id": self.thread_id,
            "connection_id": self.connection_id,
            "rows_per_second": self.rows_per_second,
            "bytes_per_second": self.bytes_per_second,
            "cpu_time": self.cpu_time,
            "memory_peak": self.memory_peak,
            "status": self.status,
            "error_message": self.error_message,
            "warning_count": self.warning_count,
            "platform_metrics": self.platform_metrics,
        }


class TimingCollector:
    """Collects detailed timing information during query execution."""

    def __init__(self, enable_detailed_timing: bool = True):
        """Initialize the timing collector.

        Args:
            enable_detailed_timing: Whether to collect detailed breakdown timing
        """
        self.enable_detailed_timing = enable_detailed_timing
        self._active_timings: dict[str, dict[str, Any]] = {}
        self._active_query_tokens: dict[str, list[str]] = {}
        self._completed_timings: list[QueryTiming] = []
        self._lock = threading.RLock()
        self._current_timing_token: ContextVar[str | None] = ContextVar(
            "benchbox_current_timing_token",
            default=None,
        )

    def _resolve_timing_token(self, query_id: str) -> str | None:
        """Resolve a query ID to the current execution, preferring context scope."""
        current_token = self._current_timing_token.get()
        with self._lock:
            if current_token is not None:
                timing_data = self._active_timings.get(current_token)
                if timing_data is not None and timing_data["query_id"] == query_id:
                    return current_token

            query_tokens = self._active_query_tokens.get(query_id)
            return query_tokens[-1] if query_tokens else None

    @contextmanager
    def time_query(self, query_id: str, query_name: Optional[str] = None):
        """Context manager for timing a complete query execution.

        Args:
            query_id: Unique identifier for the query
            query_name: Human-readable query name

        Yields:
            Dictionary for collecting timing data during execution
        """
        start_time = time.perf_counter()
        start_wall_clock = utc_now()
        timing_data = {
            "query_id": query_id,
            "query_name": query_name,
            "start_time": start_time,
            "start_wall_clock": start_wall_clock,
            "timing_breakdown": {},
            "metrics": {},
        }

        execution_token = f"{query_id}:{id(timing_data)}"
        with self._lock:
            self._active_timings[execution_token] = timing_data
            self._active_query_tokens.setdefault(query_id, []).append(execution_token)
        context_token = self._current_timing_token.set(execution_token)

        try:
            yield timing_data
        except Exception as e:
            timing_data["error"] = str(e)
            timing_data["status"] = "ERROR"
            raise
        finally:
            end_time = time.perf_counter()
            timing_data["end_time"] = end_time
            timing_data["execution_time_seconds"] = end_time - start_time

            # Create QueryTiming object
            query_timing = self._create_query_timing(timing_data)
            with self._lock:
                self._completed_timings.append(query_timing)

            # Clean up active timing
            with self._lock:
                self._active_timings.pop(execution_token, None)
                query_tokens = self._active_query_tokens.get(query_id)
                if query_tokens is not None:
                    query_tokens.remove(execution_token)
                    if not query_tokens:
                        self._active_query_tokens.pop(query_id, None)
            self._current_timing_token.reset(context_token)

    @contextmanager
    def time_phase(self, query_id: str, phase_name: str):
        """Context manager for timing a specific phase of query execution.

        Args:
            query_id: Query identifier this phase belongs to
            phase_name: Name of the execution phase (e.g., 'parse', 'optimize', 'execute')
        """
        if not self.enable_detailed_timing:
            yield
            return

        execution_token = self._resolve_timing_token(query_id)
        if execution_token is None:
            yield
            return

        start_time = time.perf_counter()

        try:
            yield
        finally:
            end_time = time.perf_counter()
            phase_duration = end_time - start_time

            with self._lock:
                timing_data = self._active_timings.get(execution_token)
                if timing_data is not None:
                    timing_data["timing_breakdown"][phase_name] = phase_duration

    def record_metric(self, query_id: str, metric_name: str, value: Any):
        """Record a metric for a query execution.

        Args:
            query_id: Query identifier
            metric_name: Name of the metric
            value: Metric value
        """
        execution_token = self._resolve_timing_token(query_id)
        if execution_token is not None:
            with self._lock:
                timing_data = self._active_timings.get(execution_token)
                if timing_data is not None:
                    timing_data["metrics"][metric_name] = value

    def _create_query_timing(self, timing_data: dict[str, Any]) -> QueryTiming:
        """Create a QueryTiming object from collected timing data."""
        return QueryTiming(
            query_id=timing_data["query_id"],
            query_name=timing_data.get("query_name"),
            execution_time=timing_data["execution_time_seconds"],
            parse_time=timing_data["timing_breakdown"].get("parse"),
            optimization_time=timing_data["timing_breakdown"].get("optimize"),
            execution_only_time=timing_data["timing_breakdown"].get("execute"),
            fetch_time=timing_data["timing_breakdown"].get("fetch"),
            timing_breakdown=timing_data["timing_breakdown"],
            rows_returned=timing_data["metrics"].get("rows_returned", 0),
            bytes_processed=timing_data["metrics"].get("bytes_processed"),
            tables_accessed=timing_data["metrics"].get("tables_accessed", []),
            timestamp=timing_data.get("start_wall_clock", utc_now()),
            thread_id=timing_data["metrics"].get("thread_id"),
            connection_id=timing_data["metrics"].get("connection_id"),
            cpu_time=timing_data["metrics"].get("cpu_time"),
            memory_peak=timing_data["metrics"].get("memory_peak"),
            status=timing_data.get("status", "SUCCESS"),
            error_message=timing_data.get("error"),
            warning_count=timing_data["metrics"].get("warning_count", 0),
            platform_metrics=timing_data["metrics"].get("platform_metrics", {}),
        )

    def get_completed_timings(self) -> list[QueryTiming]:
        """Get all completed query timings."""
        with self._lock:
            return self._completed_timings.copy()

    def clear_completed_timings(self):
        """Clear the completed timings cache."""
        with self._lock:
            self._completed_timings.clear()

    def get_timing_summary(self) -> dict[str, Any]:
        """Get a summary of all collected timings."""
        with self._lock:
            completed_timings = self._completed_timings.copy()

        if not completed_timings:
            return {}

        execution_times = [t.execution_time for t in completed_timings if t.status == "SUCCESS"]

        if not execution_times:
            return {
                "total_queries": len(completed_timings),
                "successful_queries": 0,
            }

        return {
            "total_queries": len(completed_timings),
            "successful_queries": len(execution_times),
            "failed_queries": len(completed_timings) - len(execution_times),
            "total_execution_time": sum(execution_times),
            "average_execution_time": statistics.mean(execution_times),
            "median_execution_time": statistics.median(execution_times),
            "min_execution_time": min(execution_times),
            "max_execution_time": max(execution_times),
            "execution_time_stddev": statistics.stdev(execution_times) if len(execution_times) > 1 else 0,
        }


class TimingAnalyzer:
    """Analyzes timing data to provide insights and statistics."""

    def __init__(self, timings: list[QueryTiming]):
        """Initialize with a list of query timings.

        Args:
            timings: List of QueryTiming objects to analyze
        """
        self.timings = timings
        self.successful_timings = [t for t in timings if t.status == "SUCCESS"]

    def get_basic_statistics(self) -> dict[str, Any]:
        """Get basic statistical measures for execution times."""
        if not self.successful_timings:
            return {}

        execution_times = [t.execution_time for t in self.successful_timings]

        stats = {
            "count": len(execution_times),
            "total_time": sum(execution_times),
            "mean": statistics.mean(execution_times),
            "median": statistics.median(execution_times),
            "min": min(execution_times),
            "max": max(execution_times),
        }

        if len(execution_times) > 1:
            stats["stdev"] = statistics.stdev(execution_times)
            stats["variance"] = statistics.variance(execution_times)
        else:
            stats["stdev"] = 0
            stats["variance"] = 0

        return stats

    def get_percentiles(self, percentiles: list[float] | None = None) -> dict[float, float]:
        """Calculate percentiles for execution times.

        Args:
            percentiles: List of percentile values (0-100)

        Returns:
            Dictionary mapping percentile to execution time
        """
        if percentiles is None:
            percentiles = [50, 75, 90, 95, 99]

        if not self.successful_timings:
            return {}

        execution_times = sorted([t.execution_time for t in self.successful_timings])

        result = {}
        for p in percentiles:
            if p < 0 or p > 100:
                continue
            index = (p / 100) * (len(execution_times) - 1)
            if index.is_integer():
                result[p] = execution_times[int(index)]
            else:
                lower = execution_times[int(index)]
                upper = execution_times[int(index) + 1]
                result[p] = lower + (upper - lower) * (index - int(index))

        return result

    def analyze_query_performance(self) -> dict[str, Any]:
        """Analyze performance characteristics of queries."""
        analysis = {
            "basic_stats": self.get_basic_statistics(),
            "percentiles": self.get_percentiles(),
            "status_breakdown": {},
            "timing_phases": {},
            "throughput_metrics": {},
        }

        # Status breakdown
        status_counts = {}
        for timing in self.timings:
            status = timing.status
            status_counts[status] = status_counts.get(status, 0) + 1
        analysis["status_breakdown"] = status_counts

        # Timing phase analysis
        if self.successful_timings and any(t.timing_breakdown for t in self.successful_timings):
            phase_stats = {}
            phases = set()
            for timing in self.successful_timings:
                phases.update(timing.timing_breakdown.keys())

            for phase in phases:
                phase_times = [
                    t.timing_breakdown.get(phase, 0) for t in self.successful_timings if phase in t.timing_breakdown
                ]
                if phase_times:
                    phase_stats[phase] = {
                        "count": len(phase_times),
                        "total": sum(phase_times),
                        "mean": statistics.mean(phase_times),
                        "median": statistics.median(phase_times),
                    }
            analysis["timing_phases"] = phase_stats

        # Throughput metrics
        throughput_timings = [t for t in self.successful_timings if t.rows_per_second]
        if throughput_timings:
            throughput_rates = [t.rows_per_second for t in throughput_timings]
            analysis["throughput_metrics"] = {
                "mean_rows_per_second": statistics.mean(throughput_rates),
                "median_rows_per_second": statistics.median(throughput_rates),
                "max_rows_per_second": max(throughput_rates),
                "total_rows_processed": sum(t.rows_returned for t in throughput_timings),
            }

        return analysis

    def identify_outliers(self, method: str = "iqr", factor: float = 1.5) -> list[QueryTiming]:
        """Identify timing outliers using statistical methods.

        Args:
            method: Outlier detection method ('iqr', 'zscore')
            factor: Outlier factor threshold

        Returns:
            List of QueryTiming objects identified as outliers
        """
        if not self.successful_timings:
            return []

        execution_times = [t.execution_time for t in self.successful_timings]

        if method == "iqr":
            # Interquartile Range method
            q1 = statistics.quantiles(execution_times, n=4)[0]
            q3 = statistics.quantiles(execution_times, n=4)[2]
            iqr = q3 - q1
            lower_bound = q1 - factor * iqr
            upper_bound = q3 + factor * iqr

            outliers = [
                timing
                for timing in self.successful_timings
                if timing.execution_time < lower_bound or timing.execution_time > upper_bound
            ]

        elif method == "zscore":
            # Z-score method
            mean_time = statistics.mean(execution_times)
            stdev_time = statistics.stdev(execution_times) if len(execution_times) > 1 else 0

            if stdev_time == 0:
                return []

            outliers = [
                timing
                for timing in self.successful_timings
                if abs(timing.execution_time - mean_time) / stdev_time > factor
            ]

        else:
            raise ValueError(f"Unknown outlier detection method: {method}")

        return outliers

    def compare_query_performance(self, baseline_timings: list[QueryTiming]) -> dict[str, Any]:
        """Compare current timings against baseline timings.

        Args:
            baseline_timings: List of baseline QueryTiming objects

        Returns:
            Comparison analysis results
        """
        baseline_analyzer = TimingAnalyzer(baseline_timings)
        current_stats = self.get_basic_statistics()
        baseline_stats = baseline_analyzer.get_basic_statistics()

        if not current_stats or not baseline_stats:
            return {"error": "Insufficient data for comparison"}

        comparison = {
            "current_stats": current_stats,
            "baseline_stats": baseline_stats,
            "performance_change": {},
            "regression_analysis": {},
        }

        # Calculate performance changes
        for metric in ["mean", "median", "min", "max"]:
            if metric in current_stats and metric in baseline_stats:
                current_val = current_stats[metric]
                baseline_val = baseline_stats[metric]
                change_pct = ((current_val - baseline_val) / baseline_val) * 100
                comparison["performance_change"][metric] = {
                    "current": current_val,
                    "baseline": baseline_val,
                    "change_percent": change_pct,
                    "improved": change_pct < 0,  # Lower execution time is better
                }

        # Regression analysis
        mean_change = comparison["performance_change"].get("mean", {}).get("change_percent", 0)
        comparison["regression_analysis"] = {
            "is_regression": mean_change > 10,  # More than 10% slower
            "is_improvement": mean_change < -10,  # More than 10% faster
            "severity": (
                "critical"
                if mean_change > 50
                else "major"
                if mean_change > 25
                else "minor"
                if mean_change > 10
                else "none"
            ),
        }

        return comparison
