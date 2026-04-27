"""Unit tests for DataFrame profiling module.

Tests for:
- QueryExecutionProfile dataclass
- QueryProfileContext timing tracking
- MemoryTracker runtime memory tracking
- DataFrameProfiler aggregate statistics
- Query plan capture functions
- profile_query_execution helper

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from benchbox.core.dataframe.profiling import (
    ComparisonResult,
    DataFrameProfiler,
    MemoryTracker,
    ProfiledExecutionResult,
    ProfileMetricType,
    QueryExecutionProfile,
    QueryPlan,
    QueryProfileContext,
    capture_query_plan,
    compare_execution_modes,
    get_current_memory_mb,
    profile_query_execution,
    track_memory,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestQueryExecutionProfile:
    """Tests for QueryExecutionProfile dataclass."""

    def test_basic_creation(self):
        """Test creating a basic profile."""
        profile = QueryExecutionProfile(
            query_id="Q1",
            execution_time_ms=1000.0,
        )

        assert profile.query_id == "Q1"
        assert profile.execution_time_ms == 1000.0
        assert profile.planning_time_ms == 0.0
        assert profile.collect_time_ms == 0.0
        assert profile.rows_processed == 0
        assert profile.peak_memory_mb == 0.0
        assert profile.query_plan is None
        assert profile.platform == ""
        assert profile.lazy_evaluation is False
        assert profile.metrics == {}

    def test_full_creation(self):
        """Test creating a profile with all fields."""
        plan = QueryPlan(
            platform="polars",
            plan_type="optimized",
            plan_text="FILTER -> GROUP BY",
        )

        profile = QueryExecutionProfile(
            query_id="Q1",
            execution_time_ms=1000.0,
            planning_time_ms=50.0,
            collect_time_ms=200.0,
            rows_processed=1000,
            peak_memory_mb=512.0,
            query_plan=plan,
            platform="polars",
            lazy_evaluation=True,
            metrics={"custom_metric": 42},
        )

        assert profile.planning_time_ms == 50.0
        assert profile.collect_time_ms == 200.0
        assert profile.rows_processed == 1000
        assert profile.peak_memory_mb == 512.0
        assert profile.query_plan is not None
        assert profile.lazy_evaluation is True

    def test_lazy_overhead_ms(self):
        """Test lazy overhead calculation in ms."""
        profile = QueryExecutionProfile(
            query_id="Q1",
            execution_time_ms=1000.0,
            planning_time_ms=100.0,
            collect_time_ms=200.0,
        )

        assert profile.lazy_overhead_ms == 300.0

    def test_lazy_overhead_percent(self):
        """Test lazy overhead as percentage."""
        profile = QueryExecutionProfile(
            query_id="Q1",
            execution_time_ms=1000.0,
            planning_time_ms=100.0,
            collect_time_ms=200.0,
        )

        assert profile.lazy_overhead_percent == 30.0

    def test_lazy_overhead_percent_zero_execution_time(self):
        """Test lazy overhead when execution time is zero."""
        profile = QueryExecutionProfile(
            query_id="Q1",
            execution_time_ms=0.0,
            planning_time_ms=100.0,
            collect_time_ms=200.0,
        )

        assert profile.lazy_overhead_percent == 0.0


class TestQueryPlan:
    """Tests for QueryPlan dataclass."""

    def test_basic_creation(self):
        """Test creating a basic query plan."""
        plan = QueryPlan(
            platform="polars",
            plan_type="optimized",
            plan_text="FILTER col > 10",
        )

        assert plan.platform == "polars"
        assert plan.plan_type == "optimized"
        assert plan.plan_text == "FILTER col > 10"
        assert plan.plan_data is None
        assert plan.optimization_hints == []

    def test_str_method(self):
        """Test string representation."""
        plan = QueryPlan(
            platform="polars",
            plan_type="optimized",
            plan_text="FILTER -> GROUP BY -> SORT",
        )

        assert str(plan) == "FILTER -> GROUP BY -> SORT"

    def test_with_hints(self):
        """Test plan with optimization hints."""
        plan = QueryPlan(
            platform="polars",
            plan_type="optimized",
            plan_text="SELECT * FROM table",
            optimization_hints=["Consider selecting only needed columns"],
        )

        assert len(plan.optimization_hints) == 1


class TestQueryProfileContext:
    """Tests for QueryProfileContext timing."""

    def test_basic_context(self):
        """Test basic context usage."""
        ctx = QueryProfileContext("Q1", "polars")
        ctx._start_time = time.perf_counter()

        # Simulate execution
        time.sleep(0.05)  # 50ms — 5× margin for Windows timer resolution

        profile = ctx.get_profile()

        assert profile.query_id == "Q1"
        assert profile.platform == "polars"
        assert profile.execution_time_ms >= 10  # At least 10ms

    def test_planning_phase_timing(self):
        """Test planning phase timing."""
        ctx = QueryProfileContext("Q1", "polars")
        ctx._start_time = time.perf_counter()

        ctx.start_planning()
        time.sleep(0.05)
        ctx.end_planning()

        profile = ctx.get_profile()

        assert profile.planning_time_ms >= 10
        assert profile.lazy_evaluation is True

    def test_collect_phase_timing(self):
        """Test collect phase timing."""
        ctx = QueryProfileContext("Q1", "polars")
        ctx._start_time = time.perf_counter()

        ctx.start_collect()
        time.sleep(0.05)  # 50ms — 5× margin for Windows timer resolution
        ctx.end_collect()

        profile = ctx.get_profile()

        assert profile.collect_time_ms >= 10

    def test_set_rows(self):
        """Test setting row count."""
        ctx = QueryProfileContext("Q1", "polars")
        ctx._start_time = time.perf_counter()

        ctx.set_rows(1000)

        profile = ctx.get_profile()
        assert profile.rows_processed == 1000

    def test_set_query_plan(self):
        """Test setting query plan."""
        ctx = QueryProfileContext("Q1", "polars")
        ctx._start_time = time.perf_counter()

        plan = QueryPlan("polars", "optimized", "FILTER -> GROUP BY")
        ctx.set_query_plan(plan)

        profile = ctx.get_profile()
        assert profile.query_plan is not None
        assert profile.query_plan.platform == "polars"

    def test_set_peak_memory(self):
        """Test setting peak memory."""
        ctx = QueryProfileContext("Q1", "polars")
        ctx._start_time = time.perf_counter()

        ctx.set_peak_memory(512.5)

        profile = ctx.get_profile()
        assert profile.peak_memory_mb == 512.5

    def test_add_metric(self):
        """Test adding custom metrics."""
        ctx = QueryProfileContext("Q1", "polars")
        ctx._start_time = time.perf_counter()

        ctx.add_metric("cache_hits", 100)
        ctx.add_metric("shuffle_writes", 1024)

        profile = ctx.get_profile()
        assert profile.metrics["cache_hits"] == 100
        assert profile.metrics["shuffle_writes"] == 1024


class TestMemoryTracker:
    """Tests for MemoryTracker runtime memory tracking."""

    def test_basic_tracking(self):
        """Test basic memory tracking."""
        tracker = MemoryTracker(sample_interval_ms=10)
        tracker.start()

        # Allocate some memory
        data = [0] * 100000
        time.sleep(0.05)

        peak = tracker.stop()

        # Should have recorded some memory usage
        assert peak >= 0
        del data  # cleanup

    def test_peak_memory_property(self):
        """Test peak_memory_mb property."""
        tracker = MemoryTracker(sample_interval_ms=10)
        tracker.start()
        time.sleep(0.03)
        tracker.stop()

        assert tracker.peak_memory_mb >= 0

    def test_samples_property(self):
        """Test samples are collected."""
        tracker = MemoryTracker(sample_interval_ms=10)
        tracker.start()
        time.sleep(0.05)
        tracker.stop()

        samples = tracker.samples
        assert len(samples) >= 1  # At least baseline sample

    def test_get_statistics(self):
        """Test get_statistics method."""
        tracker = MemoryTracker(sample_interval_ms=10)
        tracker.start()
        time.sleep(0.03)
        tracker.stop()

        stats = tracker.get_statistics()

        assert "baseline_mb" in stats
        assert "peak_mb" in stats
        assert "peak_delta_mb" in stats
        assert "avg_mb" in stats
        assert "sample_count" in stats
        assert stats["sample_count"] >= 1

    def test_empty_statistics(self):
        """Test statistics when no tracking done."""
        tracker = MemoryTracker()
        stats = tracker.get_statistics()

        assert stats["sample_count"] == 0
        assert stats["peak_mb"] == 0.0

    def test_stop_idempotent(self):
        """Test that stop() is idempotent."""
        tracker = MemoryTracker(sample_interval_ms=10)
        tracker.start()
        tracker.stop()

        # Second stop should be safe
        peak = tracker.stop()
        assert peak >= 0


class TestTrackMemoryContextManager:
    """Tests for track_memory context manager."""

    def test_context_manager_usage(self):
        """Test using track_memory as context manager."""
        with track_memory(sample_interval_ms=10) as tracker:
            # Allocate some memory
            data = [0] * 100000
            time.sleep(0.03)
            del data

        assert tracker.peak_memory_mb >= 0


class TestGetCurrentMemoryMb:
    """Tests for get_current_memory_mb function."""

    def test_returns_value(self):
        """Test that function returns a value."""
        memory = get_current_memory_mb()
        assert memory >= 0  # May be 0 if psutil not available


class TestDataFrameProfiler:
    """Tests for DataFrameProfiler class."""

    def test_basic_profiling(self):
        """Test basic profiler usage."""
        profiler = DataFrameProfiler(platform="polars")

        with profiler.profile_query("Q1") as ctx:
            time.sleep(0.01)
            ctx.set_rows(100)

        profiles = profiler.get_profiles()
        assert len(profiles) == 1
        assert profiles[0].query_id == "Q1"
        assert profiles[0].rows_processed == 100

    def test_multiple_queries(self):
        """Test profiling multiple queries."""
        profiler = DataFrameProfiler(platform="polars")

        for i in range(3):
            with profiler.profile_query(f"Q{i + 1}") as ctx:
                time.sleep(0.01)
                ctx.set_rows(100 * (i + 1))

        profiles = profiler.get_profiles()
        assert len(profiles) == 3

    def test_get_profile_by_id(self):
        """Test getting specific profile by ID."""
        profiler = DataFrameProfiler(platform="polars")

        with profiler.profile_query("Q1") as ctx:
            ctx.set_rows(100)

        with profiler.profile_query("Q2") as ctx:
            ctx.set_rows(200)

        profile = profiler.get_profile("Q2")
        assert profile is not None
        assert profile.rows_processed == 200

    def test_get_statistics(self):
        """Test aggregate statistics."""
        profiler = DataFrameProfiler(platform="polars")

        with profiler.profile_query("Q1") as ctx:
            time.sleep(0.01)
            ctx.set_rows(100)

        with profiler.profile_query("Q2") as ctx:
            time.sleep(0.02)
            ctx.set_rows(200)

        stats = profiler.get_statistics()

        assert stats["query_count"] == 2
        assert stats["total_rows_processed"] == 300
        assert stats["avg_rows_per_query"] == 150
        assert stats["total_execution_time_ms"] > 0
        assert stats["platform"] == "polars"

    def test_empty_statistics(self):
        """Test statistics when no queries profiled."""
        profiler = DataFrameProfiler()
        stats = profiler.get_statistics()

        assert stats["query_count"] == 0
        assert stats["total_execution_time_ms"] == 0

    def test_add_profile(self):
        """Test adding externally created profile."""
        profiler = DataFrameProfiler()

        profile = QueryExecutionProfile(
            query_id="Q1",
            execution_time_ms=100.0,
            rows_processed=50,
        )

        profiler.add_profile(profile)

        assert len(profiler.get_profiles()) == 1
        assert profiler.get_profile("Q1") is not None

    def test_clear(self):
        """Test clearing profiles."""
        profiler = DataFrameProfiler()

        with profiler.profile_query("Q1") as ctx:
            ctx.set_rows(100)

        assert len(profiler.get_profiles()) == 1

        profiler.clear()
        assert len(profiler.get_profiles()) == 0


class TestProfileQueryExecution:
    """Tests for profile_query_execution helper function."""

    def test_basic_execution(self):
        """Test basic profiled execution."""

        def query_fn():
            return [1, 2, 3]

        result, profile = profile_query_execution(
            query_id="Q1",
            platform="test",
            query_fn=query_fn,
            track_memory=False,
        )

        assert result == [1, 2, 3]
        assert profile.query_id == "Q1"
        assert profile.platform == "test"
        assert profile.execution_time_ms > 0

    def test_with_collect(self):
        """Test profiled execution with collect function."""

        def query_fn():
            return range(100)

        def collect_fn(lazy):
            return list(lazy)

        def row_count_fn(result):
            return len(result)

        result, profile = profile_query_execution(
            query_id="Q1",
            platform="test",
            query_fn=query_fn,
            collect_fn=collect_fn,
            row_count_fn=row_count_fn,
            track_memory=False,
        )

        assert len(result) == 100
        assert profile.rows_processed == 100
        assert profile.collect_time_ms > 0

    def test_with_memory_tracking(self):
        """Test profiled execution with memory tracking."""

        def query_fn():
            return [0] * 100000

        result, profile = profile_query_execution(
            query_id="Q1",
            platform="test",
            query_fn=query_fn,
            track_memory=True,
            memory_sample_interval_ms=10,
        )

        assert profile.peak_memory_mb >= 0
        # Check memory stats are in metrics
        assert "memory_baseline_mb" in profile.metrics

    def test_with_plan_capture(self):
        """Test profiled execution with plan capture."""
        mock_plan = QueryPlan(
            platform="test",
            plan_type="logical",
            plan_text="TEST PLAN",
        )

        def query_fn():
            return [1, 2, 3]

        def plan_capture_fn(df):
            return mock_plan

        result, profile = profile_query_execution(
            query_id="Q1",
            platform="test",
            query_fn=query_fn,
            plan_capture_fn=plan_capture_fn,
            track_memory=False,
        )

        assert profile.query_plan is not None
        assert profile.query_plan.plan_text == "TEST PLAN"


class TestProfiledExecutionResult:
    """Tests for ProfiledExecutionResult class."""

    def test_basic_creation(self):
        """Test creating a ProfiledExecutionResult."""
        profile = QueryExecutionProfile(
            query_id="Q1",
            execution_time_ms=1000.0,
            rows_processed=100,
            peak_memory_mb=512.0,
        )

        result = ProfiledExecutionResult(
            result=[1, 2, 3],
            profile=profile,
        )

        assert result.result == [1, 2, 3]
        assert result.execution_time_ms == 1000.0
        assert result.execution_time_seconds == 1.0
        assert result.rows_returned == 100
        assert result.peak_memory_mb == 512.0


class TestComparisonResult:
    """Tests for ComparisonResult dataclass."""

    def test_dataframe_faster(self):
        """Test when DataFrame is faster."""
        result = ComparisonResult(
            query_id="Q1",
            dataframe_time_ms=100.0,
            sql_time_ms=200.0,
        )

        assert result.speedup == 2.0
        assert result.winner == "dataframe"

    def test_sql_faster(self):
        """Test when SQL is faster."""
        result = ComparisonResult(
            query_id="Q1",
            dataframe_time_ms=200.0,
            sql_time_ms=100.0,
        )

        assert result.speedup == 0.5
        assert result.winner == "sql"

    def test_no_sql_time(self):
        """Test when SQL time not available."""
        result = ComparisonResult(
            query_id="Q1",
            dataframe_time_ms=100.0,
        )

        assert result.speedup is None
        assert result.winner == "unknown"


class TestCompareExecutionModes:
    """Tests for compare_execution_modes function."""

    def test_comparison(self):
        """Test comparing profiles with SQL times."""
        profiles = [
            QueryExecutionProfile(query_id="Q1", execution_time_ms=100.0),
            QueryExecutionProfile(query_id="Q2", execution_time_ms=200.0),
        ]

        sql_times = {"Q1": 150.0, "Q2": 100.0}

        results = compare_execution_modes(profiles, sql_times)

        assert len(results) == 2

        # Q1: DataFrame faster (100 vs 150)
        assert results[0].winner == "dataframe"

        # Q2: SQL faster (200 vs 100)
        assert results[1].winner == "sql"


class TestCaptureQueryPlan:
    """Tests for query plan capture functions."""

    def test_capture_query_plan_unknown_platform(self):
        """Test capture_query_plan with unknown platform."""
        result = capture_query_plan({}, "unknown")
        assert result is None

    def test_capture_query_plan_polars_no_explain(self):
        """Test capture_query_plan when object has no explain method."""
        mock_df = MagicMock()
        del mock_df.explain  # Remove explain method

        result = capture_query_plan(mock_df, "polars")
        assert result is None


class TestProfileMetricType:
    """Tests for ProfileMetricType enum."""

    def test_metric_types(self):
        """Test all metric types exist."""
        assert ProfileMetricType.TIMING.value == "timing"
        assert ProfileMetricType.MEMORY.value == "memory"
        assert ProfileMetricType.ROWS.value == "rows"
        assert ProfileMetricType.PLAN.value == "plan"
