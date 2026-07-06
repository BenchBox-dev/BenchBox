"""DataFrame Performance Profiling.

Provides performance profiling capabilities for DataFrame query execution including:
- Query execution timing and memory tracking
- Query plan capture for lazy evaluation platforms
- Lazy evaluation overhead measurement
- Platform-specific metrics collection

Usage:
    from benchbox.core.dataframe.profiling import (
        DataFrameProfiler,
        QueryExecutionProfile,
        capture_query_plan,
    )

    profiler = DataFrameProfiler()

    with profiler.profile_query("q1") as ctx:
        result = execute_query(...)

    profile = ctx.get_profile()
    emit(f"Execution time: {profile.execution_time_ms}ms")
    emit(f"Query plan: {profile.query_plan}")

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None  # type: ignore[assignment]

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Module-level lock for PySpark stdout capture to ensure thread safety
# when multiple threads are profiling PySpark queries concurrently
_pyspark_stdout_lock = threading.Lock()


class ProfileMetricType(Enum):
    """Types of profile metrics."""

    TIMING = "timing"
    MEMORY = "memory"
    ROWS = "rows"
    PLAN = "plan"


@dataclass
class QueryPlan:
    """Captured query execution plan.

    Attributes:
        platform: Platform that generated the plan
        plan_type: Type of plan (logical, physical, optimized)
        plan_text: Human-readable plan representation
        plan_data: Structured plan data if available
        optimization_hints: Detected optimization opportunities
    """

    platform: str
    plan_type: str
    plan_text: str
    plan_data: dict[str, Any] | None = None
    optimization_hints: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        """Return human-readable plan."""
        return self.plan_text


@dataclass
class QueryExecutionProfile:
    """Profile of a single query execution.

    Timing semantics:
        ``execution_time_ms`` is the query's own work time and EXCLUDES the plan
        capture phase, so enabling ``--capture-plans`` does not change the reported
        per-query time. It covers the segments that make up executing the query
        itself -- planning (building the lazy query), collect/materialize, and the
        surrounding result-shaping overhead (row count, first-row fetch, memory
        tracker stop) -- but not the ``capture_query_plan`` call, whose measured
        duration is reported separately as ``plan_capture_time_ms``. This aligns
        DataFrame timing with the SQL platforms, which capture plans after the timed
        block and likewise surface capture cost as ``plan_capture_time_ms``. The
        capture time is measured explicitly (a timed phase in QueryProfileContext),
        never estimated and subtracted.

    Attributes:
        query_id: Query identifier
        execution_time_ms: Query execution time in milliseconds, EXCLUDING plan
            capture time (see Timing semantics above)
        planning_time_ms: Time spent in query planning (lazy platforms)
        collect_time_ms: Time spent in collect/materialize phase
        plan_capture_time_ms: Time spent capturing the query plan (0.0 when capture
            was disabled or no plan was captured); excluded from execution_time_ms
        rows_processed: Number of rows in result
        peak_memory_mb: Peak memory usage in MB
        query_plan: Captured query plan if available
        platform: Execution platform
        lazy_evaluation: Whether lazy evaluation was used
        metrics: Additional platform-specific metrics
    """

    query_id: str
    execution_time_ms: float
    planning_time_ms: float = 0.0
    collect_time_ms: float = 0.0
    plan_capture_time_ms: float = 0.0
    rows_processed: int = 0
    peak_memory_mb: float = 0.0
    query_plan: QueryPlan | None = None
    platform: str = ""
    lazy_evaluation: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def lazy_overhead_ms(self) -> float:
        """Calculate lazy evaluation overhead (planning + collect)."""
        return self.planning_time_ms + self.collect_time_ms

    @property
    def lazy_overhead_percent(self) -> float:
        """Lazy evaluation overhead as percentage of total execution time."""
        if self.execution_time_ms <= 0:
            return 0.0
        return (self.lazy_overhead_ms / self.execution_time_ms) * 100


class QueryProfileContext:
    """Context manager for profiling a query execution."""

    def __init__(self, query_id: str, platform: str = ""):
        self.query_id = query_id
        self.platform = platform
        self._start_time: float = 0.0
        self._planning_start: float = 0.0
        self._planning_time: float = 0.0
        self._collect_start: float = 0.0
        self._collect_time: float = 0.0
        self._plan_capture_start: float = 0.0
        self._plan_capture_time: float = 0.0
        self._rows: int = 0
        self._query_plan: QueryPlan | None = None
        self._peak_memory: float = 0.0
        self._lazy_evaluation: bool = False
        self._metrics: dict[str, Any] = {}

    def start_planning(self) -> None:
        """Mark start of planning phase."""
        self._planning_start = time.perf_counter()

    def end_planning(self) -> None:
        """Mark end of planning phase."""
        if self._planning_start > 0:
            self._planning_time = (time.perf_counter() - self._planning_start) * 1000
            self._lazy_evaluation = True

    def start_collect(self) -> None:
        """Mark start of collect/materialize phase."""
        self._collect_start = time.perf_counter()

    def end_collect(self) -> None:
        """Mark end of collect/materialize phase."""
        if self._collect_start > 0:
            self._collect_time = (time.perf_counter() - self._collect_start) * 1000

    def start_plan_capture(self) -> None:
        """Mark start of the plan-capture phase (excluded from execution_time_ms)."""
        self._plan_capture_start = time.perf_counter()

    def end_plan_capture(self) -> None:
        """Mark end of the plan-capture phase.

        The measured duration is accumulated into ``plan_capture_time_ms`` and
        subtracted from ``execution_time_ms`` in :meth:`get_profile`, so plan
        capture never inflates the reported query time. Accumulates across calls in
        case capture happens in more than one segment.
        """
        if self._plan_capture_start > 0:
            self._plan_capture_time += (time.perf_counter() - self._plan_capture_start) * 1000
            self._plan_capture_start = 0.0

    def set_rows(self, rows: int) -> None:
        """Set number of rows processed."""
        self._rows = rows

    def set_query_plan(self, plan: QueryPlan) -> None:
        """Set captured query plan."""
        self._query_plan = plan

    def set_peak_memory(self, memory_mb: float) -> None:
        """Set peak memory usage in MB."""
        self._peak_memory = memory_mb

    def add_metric(self, name: str, value: Any) -> None:
        """Add a custom metric."""
        self._metrics[name] = value

    def get_profile(self) -> QueryExecutionProfile:
        """Get the execution profile.

        ``execution_time_ms`` is the wall-clock span since the context started with
        the measured plan-capture phase subtracted out, so capture on/off report the
        same query time. The subtracted amount is the value measured by
        ``start_plan_capture``/``end_plan_capture`` -- never an estimate. Clamped at
        0.0 to defend against clock noise if capture somehow exceeds the window.
        """
        wall_ms = (time.perf_counter() - self._start_time) * 1000
        execution_time = max(0.0, wall_ms - self._plan_capture_time)

        return QueryExecutionProfile(
            query_id=self.query_id,
            execution_time_ms=execution_time,
            planning_time_ms=self._planning_time,
            collect_time_ms=self._collect_time,
            plan_capture_time_ms=self._plan_capture_time,
            rows_processed=self._rows,
            peak_memory_mb=self._peak_memory,
            query_plan=self._query_plan,
            platform=self.platform,
            lazy_evaluation=self._lazy_evaluation,
            metrics=self._metrics,
        )


class MemoryTracker:
    """Runtime memory tracker using background sampling.

    Tracks peak memory usage during query execution by sampling
    process memory at regular intervals in a background thread.

    Example:
        tracker = MemoryTracker(sample_interval_ms=50)
        tracker.start()

        # Execute query...
        result = df.collect()

        tracker.stop()
        peak_mb = tracker.peak_memory_mb
        emit(f"Peak memory: {peak_mb:.2f} MB")

    Attributes:
        sample_interval_ms: Time between memory samples in milliseconds
        peak_memory_mb: Peak memory observed during tracking
        samples: List of all memory samples taken

    Thread Safety:
        All mutable state is protected by _lock. The _running flag is
        accessed under lock to prevent race conditions between start/stop
        and the sampling thread.

    Performance Notes:
        - Each sample requires ~2-3ms kernel syscall (psutil)
        - 50ms interval = ~20 syscalls/second = ~5% overhead for 100ms+ queries
        - For queries < 50ms, consider disabling memory tracking
        - For microbenchmarks, increase sample_interval_ms to 100-200ms
    """

    def __init__(self, sample_interval_ms: int = 50):
        """Initialize the memory tracker.

        Args:
            sample_interval_ms: Interval between samples (default 50ms)
        """
        self._sample_interval = sample_interval_ms / 1000.0  # Convert to seconds
        self._running = False
        self._thread: threading.Thread | None = None
        self._samples: list[float] = []
        self._peak_memory: float = 0.0
        self._baseline_memory: float = 0.0
        self._lock = threading.Lock()

    @property
    def peak_memory_mb(self) -> float:
        """Get the peak memory observed in MB."""
        with self._lock:
            return self._peak_memory

    @property
    def peak_memory_delta_mb(self) -> float:
        """Get the peak memory increase from baseline in MB."""
        with self._lock:
            return max(0.0, self._peak_memory - self._baseline_memory)

    @property
    def samples(self) -> list[float]:
        """Get all memory samples taken."""
        with self._lock:
            return self._samples.copy()

    def start(self) -> None:
        """Start memory tracking in background thread."""
        if not PSUTIL_AVAILABLE:
            logger.debug("psutil not available - memory tracking disabled")
            return

        with self._lock:
            if self._running:
                return

            # Capture baseline memory before tracking
            self._baseline_memory = self._get_current_memory()
            self._peak_memory = self._baseline_memory
            self._samples = [self._baseline_memory]
            self._running = True

        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def stop(self) -> float:
        """Stop memory tracking and return peak memory.

        Returns:
            Peak memory in MB observed during tracking
        """
        # Atomically check and clear running flag
        with self._lock:
            if not self._running:
                return self._peak_memory
            self._running = False
            # Capture thread reference under lock, clear it
            thread = self._thread
            self._thread = None
            peak = self._peak_memory

        # Join thread OUTSIDE the lock to avoid potential deadlock
        if thread is not None:
            try:
                thread.join(timeout=1.0)
            except Exception as e:
                logger.warning(f"Error joining memory tracker thread: {e}")

        return peak

    def _sample_loop(self) -> None:
        """Background sampling loop."""
        while True:
            # Check running flag under lock
            with self._lock:
                if not self._running:
                    break

            # Sample memory OUTSIDE lock to avoid blocking other operations
            current = self._get_current_memory()

            with self._lock:
                if not self._running:
                    break
                self._samples.append(current)
                if current > self._peak_memory:
                    self._peak_memory = current

            time.sleep(self._sample_interval)

    def _get_current_memory(self) -> float:
        """Get current process memory usage in MB.

        Returns:
            Current memory in MB, or 0.0 if unavailable
        """
        if not PSUTIL_AVAILABLE:
            return 0.0

        try:
            process = psutil.Process(os.getpid())
            # Use RSS (Resident Set Size) for actual physical memory
            return process.memory_info().rss / (1024 * 1024)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
            # Expected psutil errors - process state issues
            logger.debug(f"Cannot access process memory: {e}")
            return 0.0
        except OSError as e:
            # System-level errors (permission, resource issues)
            logger.debug(f"OS error reading process memory: {e}")
            return 0.0

    def get_statistics(self) -> dict[str, float]:
        """Get memory tracking statistics.

        Returns:
            Dictionary with memory statistics
        """
        # Capture all state atomically under lock
        with self._lock:
            samples = self._samples.copy()
            baseline = self._baseline_memory
            peak = self._peak_memory

        if not samples:
            return {
                "baseline_mb": 0.0,
                "peak_mb": 0.0,
                "peak_delta_mb": 0.0,
                "avg_mb": 0.0,
                "sample_count": 0,
            }

        return {
            "baseline_mb": baseline,
            "peak_mb": peak,
            "peak_delta_mb": max(0.0, peak - baseline),
            "avg_mb": sum(samples) / len(samples),
            "sample_count": len(samples),
        }


def get_current_memory_mb() -> float:
    """Get current process memory usage in MB.

    Returns:
        Current memory usage in MB, or 0.0 if unavailable
    """
    if not PSUTIL_AVAILABLE:
        return 0.0

    try:
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / (1024 * 1024)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
        # Expected psutil errors - process state issues
        logger.debug(f"Cannot access process memory: {e}")
        return 0.0
    except OSError as e:
        # System-level errors (permission, resource issues)
        logger.debug(f"OS error reading process memory: {e}")
        return 0.0


@contextmanager
def track_memory(sample_interval_ms: int = 50) -> Generator[MemoryTracker, None, None]:
    """Context manager for memory tracking.

    Example:
        with track_memory() as tracker:
            result = df.collect()
        emit(f"Peak memory delta: {tracker.peak_memory_delta_mb:.2f} MB")

    Args:
        sample_interval_ms: Interval between samples

    Yields:
        MemoryTracker instance

    Note:
        If an exception occurs in the tracked block, the tracker will still
        be stopped. If stop() itself raises an exception, it will be logged
        but not re-raised to avoid masking the original exception.
    """
    tracker = MemoryTracker(sample_interval_ms=sample_interval_ms)
    tracker.start()
    try:
        yield tracker
    finally:
        try:
            tracker.stop()
        except Exception as e:
            # Don't mask the original exception with cleanup errors
            logger.error(f"Error stopping memory tracker: {e}")


class DataFrameProfiler:
    """Profiler for DataFrame query execution.

    Collects execution profiles across multiple queries and provides
    aggregate statistics.

    Example:
        profiler = DataFrameProfiler(platform="polars")

        with profiler.profile_query("q1") as ctx:
            # Execute query
            result = df.filter(...).collect()
            ctx.set_rows(len(result))

        # Get statistics
        stats = profiler.get_statistics()
        emit(f"Average execution time: {stats['avg_execution_time_ms']:.2f}ms")
    """

    def __init__(self, platform: str = ""):
        self.platform = platform
        self._profiles: list[QueryExecutionProfile] = []

    @contextmanager
    def profile_query(self, query_id: str) -> Generator[QueryProfileContext, None, None]:
        """Profile a query execution.

        Args:
            query_id: Identifier for the query

        Yields:
            QueryProfileContext for recording metrics
        """
        ctx = QueryProfileContext(query_id, self.platform)
        ctx._start_time = time.perf_counter()

        try:
            yield ctx
        finally:
            profile = ctx.get_profile()
            self._profiles.append(profile)

    def add_profile(self, profile: QueryExecutionProfile) -> None:
        """Add an externally created profile."""
        self._profiles.append(profile)

    def get_profiles(self) -> list[QueryExecutionProfile]:
        """Get all collected profiles."""
        return self._profiles.copy()

    def get_profile(self, query_id: str) -> QueryExecutionProfile | None:
        """Get profile for a specific query."""
        for profile in self._profiles:
            if profile.query_id == query_id:
                return profile
        return None

    def get_statistics(self) -> dict[str, Any]:
        """Get aggregate statistics across all profiles.

        Returns:
            Dictionary with aggregate statistics
        """
        if not self._profiles:
            return {
                "query_count": 0,
                "total_execution_time_ms": 0,
                "avg_execution_time_ms": 0,
                "min_execution_time_ms": 0,
                "max_execution_time_ms": 0,
            }

        execution_times = [p.execution_time_ms for p in self._profiles]
        planning_times = [p.planning_time_ms for p in self._profiles]
        collect_times = [p.collect_time_ms for p in self._profiles]
        rows = [p.rows_processed for p in self._profiles]

        # Calculate lazy overhead stats
        lazy_profiles = [p for p in self._profiles if p.lazy_evaluation]
        avg_lazy_overhead = 0.0
        if lazy_profiles:
            overheads = [p.lazy_overhead_percent for p in lazy_profiles]
            avg_lazy_overhead = sum(overheads) / len(overheads)

        return {
            "query_count": len(self._profiles),
            "total_execution_time_ms": sum(execution_times),
            "avg_execution_time_ms": sum(execution_times) / len(execution_times),
            "min_execution_time_ms": min(execution_times),
            "max_execution_time_ms": max(execution_times),
            "total_planning_time_ms": sum(planning_times),
            "avg_planning_time_ms": sum(planning_times) / len(planning_times) if planning_times else 0,
            "total_collect_time_ms": sum(collect_times),
            "avg_collect_time_ms": sum(collect_times) / len(collect_times) if collect_times else 0,
            "total_rows_processed": sum(rows),
            "avg_rows_per_query": sum(rows) / len(rows) if rows else 0,
            "lazy_evaluation_queries": len(lazy_profiles),
            "avg_lazy_overhead_percent": avg_lazy_overhead,
            "platform": self.platform,
        }

    def clear(self) -> None:
        """Clear all collected profiles."""
        self._profiles.clear()


def capture_polars_plan(lazy_frame: Any) -> QueryPlan:
    """Capture query plan from a Polars LazyFrame.

    Args:
        lazy_frame: Polars LazyFrame

    Returns:
        QueryPlan with logical and optimized plans
    """
    try:
        # Get the optimized plan (what will actually execute)
        optimized_plan = lazy_frame.explain(optimized=True)

        # Get the logical plan (before optimization)
        logical_plan = lazy_frame.explain(optimized=False)

        # Analyze for optimization hints
        hints = _analyze_polars_plan(optimized_plan)

        return QueryPlan(
            platform="polars",
            plan_type="optimized",
            plan_text=optimized_plan,
            plan_data={
                "optimized_plan": optimized_plan,
                "logical_plan": logical_plan,
            },
            optimization_hints=hints,
        )
    except Exception as e:
        logger.debug(f"Could not capture Polars plan: {e}")
        return QueryPlan(
            platform="polars",
            plan_type="error",
            plan_text=f"Could not capture plan: {e}",
        )


def capture_datafusion_plan(df: Any) -> QueryPlan:
    """Capture query plan from a DataFusion DataFrame.

    Args:
        df: DataFusion DataFrame

    Returns:
        QueryPlan with logical plan
    """
    try:
        # DataFusion uses logical_plan() method
        if hasattr(df, "logical_plan"):
            plan = str(df.logical_plan())
        elif hasattr(df, "explain"):
            plan = df.explain()
        else:
            plan = "Plan capture not available"

        hints = _analyze_datafusion_plan(plan)

        return QueryPlan(
            platform="datafusion",
            plan_type="logical",
            plan_text=plan,
            optimization_hints=hints,
        )
    except Exception as e:
        logger.debug(f"Could not capture DataFusion plan: {e}")
        return QueryPlan(
            platform="datafusion",
            plan_type="error",
            plan_text=f"Could not capture plan: {e}",
        )


def capture_pyspark_plan(df: Any) -> QueryPlan:
    """Capture query plan from a PySpark DataFrame.

    Args:
        df: PySpark DataFrame

    Returns:
        QueryPlan with execution plan

    Thread Safety:
        Uses _pyspark_stdout_lock to ensure thread safety when multiple
        threads are profiling PySpark queries concurrently. The stdout
        redirection is not thread-safe by itself.
    """
    try:
        # PySpark uses _jdf.queryExecution() or explain()
        import io
        import sys

        # Capture explain output with lock to ensure thread safety
        # This prevents concurrent threads from interfering with stdout redirection
        with _pyspark_stdout_lock:
            old_stdout = sys.stdout
            sys.stdout = buffer = io.StringIO()

            try:
                df.explain(extended=True)
                plan = buffer.getvalue()
            finally:
                sys.stdout = old_stdout

        # Process plan outside lock to minimize lock contention
        hints = _analyze_pyspark_plan(plan)

        return QueryPlan(
            platform="pyspark",
            plan_type="extended",
            plan_text=plan,
            optimization_hints=hints,
        )
    except Exception as e:
        logger.debug(f"Could not capture PySpark plan: {e}")
        return QueryPlan(
            platform="pyspark",
            plan_type="error",
            plan_text=f"Could not capture plan: {e}",
        )


def capture_query_plan(df: Any, platform: str) -> QueryPlan | None:
    """Capture query plan for any supported platform.

    Args:
        df: DataFrame or LazyFrame
        platform: Platform name

    Returns:
        QueryPlan if capture supported, None otherwise
    """
    platform_lower = platform.lower().replace("-df", "")

    if platform_lower == "polars":
        # Only capture for LazyFrame
        if hasattr(df, "explain"):
            return capture_polars_plan(df)
    elif platform_lower == "datafusion":
        return capture_datafusion_plan(df)
    elif platform_lower == "pyspark":
        return capture_pyspark_plan(df)

    return None


def _analyze_polars_plan(plan: str) -> list[str]:
    """Analyze Polars query plan for optimization hints.

    Args:
        plan: Query plan text

    Returns:
        List of optimization hints
    """
    hints = []

    # Check for common patterns that might indicate optimization opportunities
    plan_lower = plan.lower()

    if "select *" in plan_lower or "selection: *" in plan_lower:
        hints.append("Consider selecting only needed columns to reduce memory usage")

    if plan_lower.count("filter") > 3:
        hints.append("Multiple filter operations - consider combining predicates")

    if "sort" in plan_lower and "limit" not in plan_lower:
        hints.append("Sorting without limit may be expensive - add limit if only top N needed")

    if "cross join" in plan_lower:
        hints.append("Cross join detected - ensure this is intentional")

    if "cache" not in plan_lower and plan_lower.count("scan") > 1:
        hints.append("Multiple scans of same data - consider caching intermediate results")

    return hints


def _analyze_datafusion_plan(plan: str) -> list[str]:
    """Analyze DataFusion query plan for optimization hints."""
    hints = []
    plan_lower = plan.lower()

    if "tablescan" in plan_lower and "projection" not in plan_lower:
        hints.append("Full table scan without projection - select specific columns")

    if "HashJoin" in plan and "Build" not in plan:
        hints.append("Hash join detected - ensure smaller table is on build side")

    return hints


def _analyze_pyspark_plan(plan: str) -> list[str]:
    """Analyze PySpark query plan for optimization hints."""
    hints = []
    plan_lower = plan.lower()

    if "broadcastexchange" not in plan_lower and "join" in plan_lower:
        hints.append("Consider broadcast join for small dimension tables")

    if "shuffle" in plan_lower:
        hints.append("Shuffle operations detected - may benefit from partitioning strategy")

    if "filescan" in plan_lower and "*" in plan:
        hints.append("Full column scan detected - select only needed columns")

    return hints


@dataclass
class ComparisonResult:
    """Result of comparing DataFrame vs SQL execution.

    Attributes:
        query_id: Query identifier
        dataframe_time_ms: DataFrame execution time
        sql_time_ms: SQL execution time (if available)
        speedup: Ratio of SQL time to DataFrame time (> 1 means DF is faster)
        winner: Which mode was faster
        notes: Additional comparison notes
    """

    query_id: str
    dataframe_time_ms: float
    sql_time_ms: float | None = None
    speedup: float | None = None
    winner: str = "unknown"
    notes: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.sql_time_ms is not None and self.dataframe_time_ms > 0:
            self.speedup = self.sql_time_ms / self.dataframe_time_ms
            self.winner = "dataframe" if self.speedup > 1 else "sql"


def compare_execution_modes(
    df_profiles: list[QueryExecutionProfile],
    sql_times: dict[str, float],
) -> list[ComparisonResult]:
    """Compare DataFrame execution profiles against SQL execution times.

    Args:
        df_profiles: List of DataFrame execution profiles
        sql_times: Dictionary mapping query_id to SQL execution time in ms

    Returns:
        List of comparison results
    """
    results = []

    for profile in df_profiles:
        sql_time = sql_times.get(profile.query_id)

        result = ComparisonResult(
            query_id=profile.query_id,
            dataframe_time_ms=profile.execution_time_ms,
            sql_time_ms=sql_time,
        )

        # Add analysis notes
        if sql_time is not None:
            if result.speedup and result.speedup > 2:
                result.notes.append(f"DataFrame is {result.speedup:.1f}x faster")
            elif result.speedup and result.speedup < 0.5:
                result.notes.append(f"SQL is {1 / result.speedup:.1f}x faster")

        if profile.lazy_overhead_percent > 20:
            result.notes.append(f"High lazy evaluation overhead: {profile.lazy_overhead_percent:.1f}%")

        results.append(result)

    return results


def profile_query_execution(
    query_id: str,
    platform: str,
    query_fn: Callable[[], Any],
    collect_fn: Callable[[Any], Any] | None = None,
    row_count_fn: Callable[[Any], int] | None = None,
    plan_capture_fn: Callable[[Any], QueryPlan | None] | None = None,
    track_memory: bool = True,
    memory_sample_interval_ms: int = 50,
) -> tuple[Any, QueryExecutionProfile]:
    """Execute a query with full profiling.

    This is a helper function that wraps query execution with comprehensive
    profiling including timing, memory tracking, and plan capture.

    Args:
        query_id: Identifier for the query
        platform: Platform name (polars, pyspark, etc.)
        query_fn: Function that builds and returns the lazy query result
        collect_fn: Optional function to materialize results (for lazy platforms)
        row_count_fn: Optional function to count rows in result
        plan_capture_fn: Optional function to capture query plan
        track_memory: Whether to track memory usage
        memory_sample_interval_ms: Memory sampling interval

    Returns:
        Tuple of (result, QueryExecutionProfile)

    Example:
        def build_query():
            return df.filter(...).group_by(...).agg(...)

        result, profile = profile_query_execution(
            query_id="Q1",
            platform="polars",
            query_fn=build_query,
            collect_fn=lambda df: df.collect(),
            row_count_fn=lambda df: len(df),
            plan_capture_fn=lambda df: capture_polars_plan(df),
        )
    """
    ctx = QueryProfileContext(query_id, platform)
    ctx._start_time = time.perf_counter()
    memory_tracker: MemoryTracker | None = None

    # Start memory tracking if enabled
    if track_memory:
        memory_tracker = MemoryTracker(sample_interval_ms=memory_sample_interval_ms)
        memory_tracker.start()

    try:
        # Phase 1: Build query (planning phase for lazy platforms)
        ctx.start_planning()
        lazy_result = query_fn()
        ctx.end_planning()

        # Capture query plan before collect if possible. Timed as its own phase so
        # it is excluded from execution_time_ms (see QueryProfileContext timing).
        query_plan = None
        if plan_capture_fn is not None:
            ctx.start_plan_capture()
            try:
                query_plan = plan_capture_fn(lazy_result)
                if query_plan:
                    ctx.set_query_plan(query_plan)
            except Exception as e:
                logger.debug(f"Plan capture failed: {e}")
            finally:
                ctx.end_plan_capture()

        # Phase 2: Collect/materialize results
        if collect_fn is not None:
            ctx.start_collect()
            result = collect_fn(lazy_result)
            ctx.end_collect()
        else:
            result = lazy_result

        # Phase 3: Get row count
        if row_count_fn is not None:
            try:
                rows = row_count_fn(result)
                ctx.set_rows(rows)
            except Exception as e:
                logger.debug(f"Row count failed: {e}")

    finally:
        # Stop memory tracking
        if memory_tracker is not None:
            peak_memory = memory_tracker.stop()
            ctx.set_peak_memory(peak_memory)

            # Add memory stats as metrics
            stats = memory_tracker.get_statistics()
            ctx.add_metric("memory_baseline_mb", stats["baseline_mb"])
            ctx.add_metric("memory_delta_mb", stats["peak_delta_mb"])
            ctx.add_metric("memory_samples", stats["sample_count"])

    profile = ctx.get_profile()
    return result, profile


@dataclass
class ProfiledExecutionResult:
    """Result of a profiled query execution.

    Contains both the query result and the execution profile,
    along with convenience access to common metrics.
    """

    result: Any
    profile: QueryExecutionProfile

    @property
    def execution_time_ms(self) -> float:
        """Total execution time in milliseconds."""
        return self.profile.execution_time_ms

    @property
    def execution_time_seconds(self) -> float:
        """Total execution time in seconds."""
        return self.profile.execution_time_ms / 1000.0

    @property
    def rows_returned(self) -> int:
        """Number of rows in result."""
        return self.profile.rows_processed

    @property
    def peak_memory_mb(self) -> float:
        """Peak memory usage in MB."""
        return self.profile.peak_memory_mb

    @property
    def query_plan(self) -> QueryPlan | None:
        """Query execution plan if captured."""
        return self.profile.query_plan
