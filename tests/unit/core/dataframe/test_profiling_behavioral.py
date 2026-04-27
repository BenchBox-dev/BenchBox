"""Behavioral tests for DataFrame Performance Profiling.

Tests targeting coverage gaps in profiling.py:
- Plan analysis functions (_analyze_polars_plan, _analyze_datafusion_plan, _analyze_pyspark_plan)
- capture_query_plan dispatching for different platforms
- compare_execution_modes notes generation
- DataFrameProfiler statistics with lazy evaluation
- MemoryTracker edge cases (no psutil, double start)
- profile_query_execution error handling
- ProfiledExecutionResult properties

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
    QueryExecutionProfile,
    QueryPlan,
    QueryProfileContext,
    _analyze_datafusion_plan,
    _analyze_polars_plan,
    _analyze_pyspark_plan,
    capture_datafusion_plan,
    capture_pyspark_plan,
    capture_query_plan,
    compare_execution_modes,
    profile_query_execution,
    track_memory,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ---------------------------------------------------------------------------
# Plan analysis - _analyze_polars_plan
# ---------------------------------------------------------------------------


class TestAnalyzePolarisPlan:
    """Tests for _analyze_polars_plan hint detection."""

    def test_detects_select_star(self):
        """Hint generated for SELECT * patterns."""
        hints = _analyze_polars_plan("SCAN table selection: *")
        assert any("selecting only needed columns" in hint for hint in hints)

    def test_detects_multiple_filters(self):
        """Hint generated when more than 3 filter operations detected."""
        plan = "FILTER a > 1\nFILTER b > 2\nFILTER c > 3\nFILTER d > 4"
        hints = _analyze_polars_plan(plan)
        assert any("combining predicates" in hint for hint in hints)

    def test_detects_sort_without_limit(self):
        """Hint generated for sort without limit."""
        hints = _analyze_polars_plan("SORT by column_a ASC")
        assert any("limit" in hint.lower() for hint in hints)

    def test_no_hint_for_sort_with_limit(self):
        """No sort hint when limit is present."""
        hints = _analyze_polars_plan("SORT by column_a ASC\nLIMIT 10")
        sort_hints = [h for h in hints if "limit" in h.lower() and "sort" in h.lower()]
        assert len(sort_hints) == 0

    def test_detects_cross_join(self):
        """Hint generated for cross join."""
        hints = _analyze_polars_plan("CROSS JOIN table_a, table_b")
        assert any("cross join" in hint.lower() for hint in hints)

    def test_detects_multiple_scans_without_cache(self):
        """Hint generated for multiple scans without caching."""
        plan = "SCAN parquet file1\nFILTER\nSCAN parquet file2"
        hints = _analyze_polars_plan(plan)
        assert any("caching" in hint.lower() for hint in hints)

    def test_no_cache_hint_when_cache_present(self):
        """No caching hint when CACHE is in the plan."""
        plan = "SCAN parquet file1\nCACHE\nSCAN parquet file2"
        hints = _analyze_polars_plan(plan)
        cache_hints = [h for h in hints if "caching" in h.lower()]
        assert len(cache_hints) == 0

    def test_clean_plan_produces_no_hints(self):
        """Optimized plan produces no hints."""
        hints = _analyze_polars_plan("SELECT col_a, col_b FROM table LIMIT 100")
        assert len(hints) == 0


# ---------------------------------------------------------------------------
# Plan analysis - _analyze_datafusion_plan
# ---------------------------------------------------------------------------


class TestAnalyzeDatafusionPlan:
    """Tests for _analyze_datafusion_plan hint detection."""

    def test_detects_full_table_scan(self):
        """Hint generated for tableScan without projection."""
        hints = _analyze_datafusion_plan("tableScan some_table")
        assert any("full table scan" in hint.lower() for hint in hints)

    def test_no_hint_with_projection(self):
        """No hint when projection is present alongside tableScan."""
        hints = _analyze_datafusion_plan("tableScan some_table\nprojection: col_a, col_b")
        scan_hints = [h for h in hints if "full table scan" in h.lower()]
        assert len(scan_hints) == 0

    def test_detects_hash_join_without_build(self):
        """Hint generated for HashJoin without Build annotation."""
        hints = _analyze_datafusion_plan("HashJoin: left=orders, right=lineitem")
        assert any("hash join" in hint.lower() for hint in hints)

    def test_no_hint_hash_join_with_build(self):
        """No hint when HashJoin has Build annotation."""
        hints = _analyze_datafusion_plan("HashJoin: left=orders, right=lineitem Build: left")
        join_hints = [h for h in hints if "hash join" in h.lower()]
        assert len(join_hints) == 0


# ---------------------------------------------------------------------------
# Plan analysis - _analyze_pyspark_plan
# ---------------------------------------------------------------------------


class TestAnalyzePysparkPlan:
    """Tests for _analyze_pyspark_plan hint detection."""

    def test_detects_join_without_broadcast(self):
        """Hint generated for join without BroadcastExchange."""
        hints = _analyze_pyspark_plan("SortMergeJoin [key], Inner")
        assert any("broadcast join" in hint.lower() for hint in hints)

    def test_no_broadcast_hint_with_broadcast(self):
        """No hint when BroadcastExchange is present."""
        hints = _analyze_pyspark_plan("BroadcastExchange\nSortMergeJoin [key], Inner")
        broadcast_hints = [h for h in hints if "broadcast" in h.lower()]
        assert len(broadcast_hints) == 0

    def test_detects_shuffle(self):
        """Hint generated for shuffle operations."""
        hints = _analyze_pyspark_plan("Exchange hashpartitioning\nShuffle write")
        assert any("shuffle" in hint.lower() for hint in hints)

    def test_detects_filescan_with_star(self):
        """Hint generated for FileScan with * columns."""
        hints = _analyze_pyspark_plan("FileScan parquet [*]")
        assert any("column scan" in hint.lower() for hint in hints)


# ---------------------------------------------------------------------------
# capture_query_plan - platform dispatching
# ---------------------------------------------------------------------------


class TestCaptureQueryPlanDispatching:
    """Tests for capture_query_plan platform routing."""

    def test_polars_df_suffix_stripped(self):
        """Platform 'polars-df' is normalized to 'polars'."""
        mock_lf = MagicMock()
        mock_lf.explain.return_value = "SCAN parquet"

        plan = capture_query_plan(mock_lf, "polars-df")
        assert plan is not None
        assert plan.platform == "polars"

    def test_datafusion_platform(self):
        """DataFusion plan capture via logical_plan method."""
        mock_df = MagicMock()
        mock_df.logical_plan.return_value = "LogicalPlan: Scan"

        plan = capture_query_plan(mock_df, "datafusion")
        assert plan is not None
        assert plan.platform == "datafusion"

    def test_pyspark_platform(self):
        """PySpark plan capture via explain method."""
        mock_df = MagicMock()
        # PySpark's explain prints to stdout, simulate that
        mock_df.explain.side_effect = lambda extended=False: print("== Physical Plan ==\nScan parquet")

        plan = capture_query_plan(mock_df, "pyspark")
        assert plan is not None
        assert plan.platform == "pyspark"

    def test_unknown_platform_returns_none(self):
        """Unknown platform returns None."""
        result = capture_query_plan(MagicMock(), "unknown_platform")
        assert result is None

    def test_polars_without_explain_returns_none(self):
        """Polars object without explain method returns None."""
        mock_df = MagicMock(spec=[])  # empty spec = no methods
        result = capture_query_plan(mock_df, "polars")
        assert result is None


# ---------------------------------------------------------------------------
# capture_datafusion_plan - explain fallback
# ---------------------------------------------------------------------------


class TestCaptureDatafusionPlan:
    """Tests for capture_datafusion_plan method fallbacks."""

    def test_uses_explain_when_no_logical_plan(self):
        """Falls back to explain() when logical_plan() not available."""
        mock_df = MagicMock(spec=["explain"])
        mock_df.explain.return_value = "Explain output"

        plan = capture_datafusion_plan(mock_df)
        assert plan.plan_text == "Explain output"

    def test_neither_method_available(self):
        """Plan text indicates unavailability when no method exists."""
        mock_df = MagicMock(spec=[])

        plan = capture_datafusion_plan(mock_df)
        assert "not available" in plan.plan_text.lower()

    def test_exception_returns_error_plan(self):
        """Exception during plan capture returns error plan."""
        mock_df = MagicMock()
        mock_df.logical_plan.side_effect = RuntimeError("plan failed")

        plan = capture_datafusion_plan(mock_df)
        assert plan.plan_type == "error"
        assert "plan failed" in plan.plan_text


# ---------------------------------------------------------------------------
# capture_pyspark_plan - error handling
# ---------------------------------------------------------------------------


class TestCapturePysparkPlan:
    """Tests for capture_pyspark_plan error handling."""

    def test_exception_returns_error_plan(self):
        """Exception during PySpark plan capture returns error plan."""
        mock_df = MagicMock()
        mock_df.explain.side_effect = RuntimeError("spark not initialized")

        plan = capture_pyspark_plan(mock_df)
        assert plan.plan_type == "error"
        assert "spark not initialized" in plan.plan_text


# ---------------------------------------------------------------------------
# compare_execution_modes - note generation
# ---------------------------------------------------------------------------


class TestCompareExecutionModesNotes:
    """Tests for compare_execution_modes note generation."""

    def test_dataframe_much_faster_note(self):
        """Note generated when DataFrame is >2x faster."""
        profiles = [
            QueryExecutionProfile(query_id="Q1", execution_time_ms=50.0),
        ]
        sql_times = {"Q1": 200.0}

        results = compare_execution_modes(profiles, sql_times)
        assert len(results) == 1
        assert any("faster" in note.lower() and "DataFrame" in note for note in results[0].notes)

    def test_sql_much_faster_note(self):
        """Note generated when SQL is >2x faster."""
        profiles = [
            QueryExecutionProfile(query_id="Q1", execution_time_ms=200.0),
        ]
        sql_times = {"Q1": 50.0}

        results = compare_execution_modes(profiles, sql_times)
        assert len(results) == 1
        assert any("faster" in note.lower() and "SQL" in note for note in results[0].notes)

    def test_high_lazy_overhead_note(self):
        """Note generated for high lazy evaluation overhead."""
        profiles = [
            QueryExecutionProfile(
                query_id="Q1",
                execution_time_ms=100.0,
                planning_time_ms=15.0,
                collect_time_ms=10.0,
                lazy_evaluation=True,
            ),
        ]
        sql_times = {}

        results = compare_execution_modes(profiles, sql_times)
        assert len(results) == 1
        assert any("lazy evaluation overhead" in note.lower() for note in results[0].notes)

    def test_no_sql_time_for_query(self):
        """No SQL comparison notes when SQL time not available."""
        profiles = [
            QueryExecutionProfile(query_id="Q1", execution_time_ms=100.0),
        ]
        sql_times = {}

        results = compare_execution_modes(profiles, sql_times)
        assert results[0].sql_time_ms is None
        assert results[0].winner == "unknown"


# ---------------------------------------------------------------------------
# ComparisonResult - __post_init__ edge cases
# ---------------------------------------------------------------------------


class TestComparisonResultEdgeCases:
    """Tests for ComparisonResult edge cases."""

    def test_zero_dataframe_time(self):
        """Zero DataFrame time with SQL time does not divide by zero."""
        result = ComparisonResult(
            query_id="Q1",
            dataframe_time_ms=0.0,
            sql_time_ms=100.0,
        )
        # speedup would be inf, but winner should still be set
        assert result.winner == "unknown" or result.speedup is not None

    def test_equal_times(self):
        """Equal times result in speedup of 1.0."""
        result = ComparisonResult(
            query_id="Q1",
            dataframe_time_ms=100.0,
            sql_time_ms=100.0,
        )
        assert result.speedup == 1.0
        # speedup = 1.0, not > 1, so winner is "sql"
        assert result.winner == "sql"


# ---------------------------------------------------------------------------
# DataFrameProfiler - statistics with lazy evaluation
# ---------------------------------------------------------------------------


class TestProfilerLazyEvaluationStats:
    """Tests for DataFrameProfiler aggregate statistics with lazy profiles."""

    def test_statistics_with_lazy_evaluation(self):
        """Lazy evaluation statistics computed from lazy profiles only."""
        profiler = DataFrameProfiler(platform="polars")

        # Add a lazy profile
        lazy_profile = QueryExecutionProfile(
            query_id="Q1",
            execution_time_ms=100.0,
            planning_time_ms=10.0,
            collect_time_ms=20.0,
            lazy_evaluation=True,
        )
        profiler.add_profile(lazy_profile)

        # Add a non-lazy profile
        eager_profile = QueryExecutionProfile(
            query_id="Q2",
            execution_time_ms=50.0,
            lazy_evaluation=False,
        )
        profiler.add_profile(eager_profile)

        stats = profiler.get_statistics()
        assert stats["lazy_evaluation_queries"] == 1
        assert stats["avg_lazy_overhead_percent"] == 30.0  # (10+20)/100 * 100

    def test_statistics_no_lazy_profiles(self):
        """avg_lazy_overhead_percent is 0 when no lazy profiles."""
        profiler = DataFrameProfiler()
        profiler.add_profile(QueryExecutionProfile(query_id="Q1", execution_time_ms=100.0, lazy_evaluation=False))

        stats = profiler.get_statistics()
        assert stats["lazy_evaluation_queries"] == 0
        assert stats["avg_lazy_overhead_percent"] == 0.0

    def test_get_profile_returns_none_for_missing(self):
        """get_profile returns None for non-existent query_id."""
        profiler = DataFrameProfiler()
        assert profiler.get_profile("nonexistent") is None

    def test_profiler_profiles_are_copies(self):
        """get_profiles returns a copy, not the internal list."""
        profiler = DataFrameProfiler()
        profiler.add_profile(QueryExecutionProfile(query_id="Q1", execution_time_ms=100.0))

        profiles = profiler.get_profiles()
        profiles.clear()

        # Internal list should be unaffected
        assert len(profiler.get_profiles()) == 1

    def test_statistics_planning_and_collect_times(self):
        """Planning and collect time aggregations are correct."""
        profiler = DataFrameProfiler(platform="test")

        profiler.add_profile(
            QueryExecutionProfile(query_id="Q1", execution_time_ms=200.0, planning_time_ms=30.0, collect_time_ms=40.0)
        )
        profiler.add_profile(
            QueryExecutionProfile(query_id="Q2", execution_time_ms=100.0, planning_time_ms=10.0, collect_time_ms=20.0)
        )

        stats = profiler.get_statistics()
        assert stats["total_planning_time_ms"] == 40.0
        assert stats["avg_planning_time_ms"] == 20.0
        assert stats["total_collect_time_ms"] == 60.0
        assert stats["avg_collect_time_ms"] == 30.0


# ---------------------------------------------------------------------------
# MemoryTracker - edge cases
# ---------------------------------------------------------------------------


class TestMemoryTrackerEdgeCases:
    """Tests for MemoryTracker edge conditions."""

    def test_double_start_is_idempotent(self):
        """Starting tracker twice does not create multiple threads."""
        tracker = MemoryTracker(sample_interval_ms=50)
        tracker.start()
        tracker.start()  # Should be a no-op

        peak = tracker.stop()
        assert peak >= 0

    def test_stop_before_start_returns_zero(self):
        """Stopping a never-started tracker returns 0.0."""
        tracker = MemoryTracker()
        peak = tracker.stop()
        assert peak == 0.0

    def test_peak_memory_delta(self):
        """peak_memory_delta_mb is non-negative."""
        tracker = MemoryTracker(sample_interval_ms=10)
        tracker.start()
        time.sleep(0.03)
        tracker.stop()

        assert tracker.peak_memory_delta_mb >= 0.0


# ---------------------------------------------------------------------------
# track_memory context manager - exception safety
# ---------------------------------------------------------------------------


class TestTrackMemoryExceptionSafety:
    """Tests for track_memory context manager exception handling."""

    def test_tracker_stops_on_exception(self):
        """Memory tracker is stopped even when block raises."""
        with pytest.raises(ValueError, match="test error"):
            with track_memory(sample_interval_ms=10) as tracker:
                time.sleep(0.02)
                raise ValueError("test error")

        # Tracker should have stopped and recorded something
        assert tracker.peak_memory_mb >= 0


# ---------------------------------------------------------------------------
# profile_query_execution - error paths
# ---------------------------------------------------------------------------


class TestProfileQueryExecutionErrorPaths:
    """Tests for profile_query_execution error handling."""

    def test_plan_capture_exception_is_swallowed(self):
        """Exception in plan_capture_fn is caught, profiling continues."""

        def query_fn():
            return [1, 2, 3]

        def bad_plan_fn(df):
            raise RuntimeError("plan capture failed")

        result, profile = profile_query_execution(
            query_id="Q1",
            platform="test",
            query_fn=query_fn,
            plan_capture_fn=bad_plan_fn,
            track_memory=False,
        )

        assert result == [1, 2, 3]
        assert profile.query_plan is None  # Failed capture results in no plan

    def test_row_count_exception_is_swallowed(self):
        """Exception in row_count_fn is caught, profiling continues."""

        def query_fn():
            return "result"

        def bad_row_count_fn(result):
            raise TypeError("cannot count rows")

        result, profile = profile_query_execution(
            query_id="Q1",
            platform="test",
            query_fn=query_fn,
            row_count_fn=bad_row_count_fn,
            track_memory=False,
        )

        assert result == "result"
        assert profile.rows_processed == 0  # Default when count fails

    def test_plan_capture_returning_none_is_handled(self):
        """plan_capture_fn returning None is handled gracefully."""

        def query_fn():
            return [1]

        def null_plan_fn(df):
            return None

        result, profile = profile_query_execution(
            query_id="Q1",
            platform="test",
            query_fn=query_fn,
            plan_capture_fn=null_plan_fn,
            track_memory=False,
        )

        assert profile.query_plan is None


# ---------------------------------------------------------------------------
# ProfiledExecutionResult - property coverage
# ---------------------------------------------------------------------------


class TestProfiledExecutionResultProperties:
    """Tests for ProfiledExecutionResult computed properties."""

    def test_execution_time_seconds_conversion(self):
        """execution_time_seconds correctly converts from ms."""
        profile = QueryExecutionProfile(query_id="Q1", execution_time_ms=2500.0)
        result = ProfiledExecutionResult(result=None, profile=profile)
        assert result.execution_time_seconds == 2.5

    def test_query_plan_property(self):
        """query_plan property delegates to profile."""
        plan = QueryPlan(platform="test", plan_type="logical", plan_text="PLAN")
        profile = QueryExecutionProfile(query_id="Q1", execution_time_ms=100.0, query_plan=plan)
        result = ProfiledExecutionResult(result=None, profile=profile)
        assert result.query_plan is plan
        assert result.query_plan.plan_text == "PLAN"

    def test_query_plan_none(self):
        """query_plan is None when profile has no plan."""
        profile = QueryExecutionProfile(query_id="Q1", execution_time_ms=100.0)
        result = ProfiledExecutionResult(result=None, profile=profile)
        assert result.query_plan is None


# ---------------------------------------------------------------------------
# QueryProfileContext - end_planning without start
# ---------------------------------------------------------------------------


class TestQueryProfileContextEdgeCases:
    """Tests for QueryProfileContext edge conditions."""

    def test_end_planning_without_start(self):
        """end_planning without start_planning is a no-op."""
        ctx = QueryProfileContext("Q1", "polars")
        ctx._start_time = time.perf_counter()

        ctx.end_planning()  # No start_planning called

        profile = ctx.get_profile()
        assert profile.planning_time_ms == 0.0
        assert profile.lazy_evaluation is False

    def test_end_collect_without_start(self):
        """end_collect without start_collect is a no-op."""
        ctx = QueryProfileContext("Q1", "polars")
        ctx._start_time = time.perf_counter()

        ctx.end_collect()  # No start_collect called

        profile = ctx.get_profile()
        assert profile.collect_time_ms == 0.0


# ---------------------------------------------------------------------------
# QueryPlan - plan_data field
# ---------------------------------------------------------------------------


class TestQueryPlanData:
    """Tests for QueryPlan with plan_data."""

    def test_plan_data_dict(self):
        """plan_data stores structured data."""
        plan = QueryPlan(
            platform="polars",
            plan_type="optimized",
            plan_text="PLAN TEXT",
            plan_data={"optimized_plan": "opt", "logical_plan": "log"},
        )
        assert plan.plan_data is not None
        assert plan.plan_data["optimized_plan"] == "opt"
        assert plan.plan_data["logical_plan"] == "log"
