"""Tests for concurrent load executor module.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.experimental.load_testing.executor import (
    ConcurrentLoadConfig,
    ConcurrentLoadExecutor,
    ConcurrentLoadResult,
    QueryExecution,
    StreamResult,
)
from benchbox.experimental.load_testing.patterns import SteadyPattern, StepPattern

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


class TestQueryExecution:
    """Tests for QueryExecution dataclass."""

    def test_basic_creation(self):
        """Should create execution record."""
        exec_record = QueryExecution(
            query_id="q1",
            stream_id=0,
            start_time=1000.0,
            end_time=1001.0,
            success=True,
        )
        assert exec_record.query_id == "q1"
        assert exec_record.stream_id == 0
        assert exec_record.success is True

    def test_with_error(self):
        """Should record error information."""
        exec_record = QueryExecution(
            query_id="q1",
            stream_id=0,
            start_time=1000.0,
            end_time=1001.0,
            success=False,
            error="Connection timeout",
        )
        assert exec_record.success is False
        assert exec_record.error == "Connection timeout"

    def test_queue_wait_time(self):
        """Should track queue wait time."""
        exec_record = QueryExecution(
            query_id="q1",
            stream_id=0,
            start_time=1000.0,
            end_time=1001.0,
            success=True,
            queue_wait_time=0.5,
        )
        assert exec_record.queue_wait_time == 0.5


class TestStreamResult:
    """Tests for StreamResult dataclass."""

    def test_basic_creation(self):
        """Should create stream result."""
        result = StreamResult(
            stream_id=1,
            queries_executed=10,
            queries_succeeded=9,
            queries_failed=1,
            total_time_seconds=5.0,
        )
        assert result.stream_id == 1
        assert result.queries_executed == 10

    def test_success_rate(self):
        """Should calculate success rate."""
        result = StreamResult(
            stream_id=0,
            queries_executed=10,
            queries_succeeded=8,
            queries_failed=2,
            total_time_seconds=5.0,
        )
        assert result.success_rate == 80.0

    def test_success_rate_zero_queries(self):
        """Should handle zero queries."""
        result = StreamResult(
            stream_id=0,
            queries_executed=0,
            queries_succeeded=0,
            queries_failed=0,
            total_time_seconds=1.0,
        )
        assert result.success_rate == 0.0

    def test_throughput(self):
        """Should calculate throughput."""
        result = StreamResult(
            stream_id=0,
            queries_executed=100,
            queries_succeeded=100,
            queries_failed=0,
            total_time_seconds=10.0,
        )
        assert result.throughput == 10.0

    def test_throughput_zero_time(self):
        """Should handle zero time."""
        result = StreamResult(
            stream_id=0,
            queries_executed=10,
            queries_succeeded=10,
            queries_failed=0,
            total_time_seconds=0.0,
        )
        assert result.throughput == 0.0


class TestConcurrentLoadResult:
    """Tests for ConcurrentLoadResult dataclass."""

    def test_basic_creation(self):
        """Should create load result."""
        result = ConcurrentLoadResult(
            start_time=1000.0,
            end_time=1010.0,
            total_duration_seconds=10.0,
            streams=[],
            total_streams_executed=5,
            total_streams_succeeded=5,
            total_queries_executed=50,
            total_queries_succeeded=48,
            total_queries_failed=2,
            overall_throughput=5.0,
        )
        assert result.total_duration_seconds == 10.0
        assert result.overall_throughput == 5.0

    def test_success_rate(self):
        """Should calculate overall success rate."""
        result = ConcurrentLoadResult(
            start_time=0,
            end_time=10,
            total_duration_seconds=10,
            streams=[],
            total_streams_executed=1,
            total_streams_succeeded=1,
            total_queries_executed=100,
            total_queries_succeeded=95,
            total_queries_failed=5,
            overall_throughput=10,
        )
        assert result.success_rate == 95.0

    def test_percentile_latency(self):
        """Should calculate percentile latency."""
        executions = [
            QueryExecution(
                query_id=f"q{i}",
                stream_id=0,
                start_time=float(i),
                end_time=float(i) + 0.1 * (i + 1),  # Varying latencies
                success=True,
            )
            for i in range(10)
        ]
        stream = StreamResult(
            stream_id=0,
            queries_executed=10,
            queries_succeeded=10,
            queries_failed=0,
            total_time_seconds=5.0,
            query_executions=executions,
        )
        result = ConcurrentLoadResult(
            start_time=0,
            end_time=5,
            total_duration_seconds=5,
            streams=[stream],
            total_streams_executed=1,
            total_streams_succeeded=1,
            total_queries_executed=10,
            total_queries_succeeded=10,
            total_queries_failed=0,
            overall_throughput=2.0,
        )
        p50 = result.get_percentile_latency(50)
        p99 = result.get_percentile_latency(99)
        assert p50 > 0
        assert p99 >= p50


class TestConcurrentLoadConfig:
    """Tests for ConcurrentLoadConfig dataclass."""

    def test_default_pattern(self, mock_connection_factory, mock_query_factory, mock_execute_query):
        """Should use default steady pattern."""
        config = ConcurrentLoadConfig(
            query_factory=mock_query_factory,
            connection_factory=mock_connection_factory,
            execute_query=mock_execute_query,
        )
        assert config.pattern.max_concurrency == 1
        assert config.queries_per_stream == 10


class TestConcurrentLoadExecutor:
    """Tests for ConcurrentLoadExecutor."""

    def test_basic_execution(self, mock_connection_factory, mock_query_factory, mock_execute_query):
        """Should execute basic load test."""
        config = ConcurrentLoadConfig(
            query_factory=mock_query_factory,
            connection_factory=mock_connection_factory,
            execute_query=mock_execute_query,
            pattern=SteadyPattern(concurrency=2, duration_seconds=1),
            queries_per_stream=3,
            collect_resource_metrics=False,
        )
        executor = ConcurrentLoadExecutor(config)
        result = executor.run()

        assert result.total_queries_executed > 0
        assert result.total_duration_seconds >= 1.0
        assert result.pattern_name == "SteadyPattern"

    def test_tracks_stream_results(self, mock_connection_factory, mock_query_factory, mock_execute_query):
        """Should track results for each stream."""
        config = ConcurrentLoadConfig(
            query_factory=mock_query_factory,
            connection_factory=mock_connection_factory,
            execute_query=mock_execute_query,
            pattern=SteadyPattern(concurrency=3, duration_seconds=0.5),
            queries_per_stream=2,
            collect_resource_metrics=False,
        )
        executor = ConcurrentLoadExecutor(config)
        result = executor.run()

        assert len(result.streams) > 0
        for stream in result.streams:
            assert stream.queries_executed <= 2

    def test_handles_query_failure(self, mock_connection_factory, mock_query_factory):
        """Should handle query failures gracefully."""

        def failing_execute(connection, sql):
            if "1" in sql:
                return (False, None, "Query failed")
            return (True, 1, None)

        config = ConcurrentLoadConfig(
            query_factory=mock_query_factory,
            connection_factory=mock_connection_factory,
            execute_query=failing_execute,
            pattern=SteadyPattern(concurrency=1, duration_seconds=0.5),
            queries_per_stream=3,
            collect_resource_metrics=False,
        )
        executor = ConcurrentLoadExecutor(config)
        result = executor.run()

        assert result.total_queries_failed > 0
        assert result.success_rate < 100

    def test_handles_connection_failure(self, mock_query_factory, mock_execute_query):
        """Should handle connection failures."""

        def failing_factory():
            raise RuntimeError("Connection refused")

        config = ConcurrentLoadConfig(
            query_factory=mock_query_factory,
            connection_factory=failing_factory,
            execute_query=mock_execute_query,
            pattern=SteadyPattern(concurrency=1, duration_seconds=0.5),
            queries_per_stream=1,
            collect_resource_metrics=False,
        )
        executor = ConcurrentLoadExecutor(config)
        result = executor.run()

        # Should complete without raising
        assert result.total_streams_executed >= 0

    def test_tracks_max_concurrency(self, mock_connection_factory, mock_query_factory, mock_execute_query):
        """Should track maximum concurrency reached."""
        config = ConcurrentLoadConfig(
            query_factory=mock_query_factory,
            connection_factory=mock_connection_factory,
            execute_query=mock_execute_query,
            pattern=StepPattern([(1, 0.3), (3, 0.3)]),
            queries_per_stream=5,
            collect_resource_metrics=False,
        )
        executor = ConcurrentLoadExecutor(config)
        result = executor.run()

        assert result.max_concurrency_reached >= 1

    def test_calculates_throughput(self, mock_connection_factory, mock_query_factory, mock_execute_query):
        """Should calculate overall throughput."""
        config = ConcurrentLoadConfig(
            query_factory=mock_query_factory,
            connection_factory=mock_connection_factory,
            execute_query=mock_execute_query,
            pattern=SteadyPattern(concurrency=2, duration_seconds=1),
            queries_per_stream=5,
            collect_resource_metrics=False,
        )
        executor = ConcurrentLoadExecutor(config)
        result = executor.run()

        assert result.overall_throughput > 0

    def test_queue_metrics_collected(self, mock_connection_factory, mock_query_factory, mock_execute_query):
        """Should collect queue metrics when enabled."""
        config = ConcurrentLoadConfig(
            query_factory=mock_query_factory,
            connection_factory=mock_connection_factory,
            execute_query=mock_execute_query,
            pattern=SteadyPattern(concurrency=3, duration_seconds=0.5),
            queries_per_stream=2,
            track_queue_times=True,
            collect_resource_metrics=False,
        )
        executor = ConcurrentLoadExecutor(config)
        result = executor.run()

        # Queue metrics should be present (may be empty if no queueing)
        assert isinstance(result.queue_metrics, dict)


class TestConcurrentLoadExecutorEdgeCases:
    """Edge case tests for ConcurrentLoadExecutor."""

    def test_single_query_per_stream(self, mock_connection_factory, mock_query_factory, mock_execute_query):
        """Should handle single query per stream."""
        config = ConcurrentLoadConfig(
            query_factory=mock_query_factory,
            connection_factory=mock_connection_factory,
            execute_query=mock_execute_query,
            pattern=SteadyPattern(concurrency=1, duration_seconds=0.5),
            queries_per_stream=1,
            collect_resource_metrics=False,
        )
        executor = ConcurrentLoadExecutor(config)
        result = executor.run()

        assert result.total_queries_executed > 0

    def test_high_concurrency(self, mock_connection_factory, mock_query_factory, mock_execute_query):
        """Should handle high concurrency levels."""
        config = ConcurrentLoadConfig(
            query_factory=mock_query_factory,
            connection_factory=mock_connection_factory,
            execute_query=mock_execute_query,
            pattern=SteadyPattern(concurrency=20, duration_seconds=0.5),
            queries_per_stream=1,
            collect_resource_metrics=False,
        )
        executor = ConcurrentLoadExecutor(config)
        result = executor.run()

        assert result.max_concurrency_reached > 0

    def test_exception_in_query_execution(self, mock_connection_factory, mock_query_factory):
        """Should handle exceptions during query execution."""

        def exception_execute(connection, sql):
            raise ValueError("Unexpected error")

        config = ConcurrentLoadConfig(
            query_factory=mock_query_factory,
            connection_factory=mock_connection_factory,
            execute_query=exception_execute,
            pattern=SteadyPattern(concurrency=1, duration_seconds=0.5),
            queries_per_stream=2,
            collect_resource_metrics=False,
        )
        executor = ConcurrentLoadExecutor(config)
        result = executor.run()

        # Should complete and record failures
        assert result.total_queries_failed > 0
