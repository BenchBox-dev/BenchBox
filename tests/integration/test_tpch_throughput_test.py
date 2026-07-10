"""Integration tests for the simulated TPC-H throughput test implementation."""

from __future__ import annotations

from typing import Callable
from unittest.mock import Mock, patch

import pytest

from benchbox.core.tpch.throughput_test import (
    TPCHThroughputStreamResult,
    TPCHThroughputTest,
    TPCHThroughputTestConfig,
    TPCHThroughputTestResult,
)

# Mark all tests in this file as integration tests
pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]


def _make_benchmark_mock() -> Mock:
    benchmark = Mock()
    benchmark.get_query.return_value = "SELECT 1"
    return benchmark


def _make_connection_factory(registry: list[Mock]) -> Callable[[], Mock]:
    def factory() -> Mock:
        conn = Mock()
        conn.close.return_value = None

        # Set up cursor mock with fetchall() returning empty list
        cursor = Mock()
        cursor.fetchall.return_value = []
        conn.execute.return_value = cursor

        registry.append(conn)
        return conn

    return factory


class TestThroughputConfig:
    """Validate throughput test configuration dataclass."""

    def test_defaults(self) -> None:
        config = TPCHThroughputTestConfig()
        assert config.scale_factor == 1.0
        assert config.num_streams == 2
        assert config.base_seed == 42
        assert config.stream_timeout == 3600
        assert config.max_workers is None
        assert config.verbose is False
        assert config.min_success_rate == 0.99


class TestThroughputResult:
    """Exercise TPCHThroughputTestResult behaviour."""

    def test_basic_dataclass_initialisation(self) -> None:
        config = TPCHThroughputTestConfig(scale_factor=0.1, num_streams=1)
        stream_result = TPCHThroughputStreamResult(
            stream_id=0,
            start_time=0.0,
            end_time=0.5,
            duration=0.5,
            queries_executed=22,
            queries_successful=22,
            queries_failed=0,
            query_results=[{"query_id": 1, "success": True}],
        )
        result = TPCHThroughputTestResult(
            config=config,
            start_time="2025-01-01T00:00:00",
            end_time="2025-01-01T00:00:01",
            total_time=1.0,
            throughput_at_size=50.0,
            streams_executed=1,
            streams_successful=1,
            stream_results=[stream_result],
            query_throughput=22.0,
            success=True,
        )

        assert result.success is True
        assert result.streams_executed == 1
        assert result.stream_results[0].queries_failed == 0


class TestThroughputExecution:
    """Cover the public execution helpers."""

    def test_execute_stream_produces_basic_statistics(self) -> None:
        benchmark = _make_benchmark_mock()
        connections: list[Mock] = []
        factory = _make_connection_factory(connections)

        test = TPCHThroughputTest(benchmark=benchmark, connection_factory=factory, scale_factor=0.01, num_streams=1)

        stream_result = test._execute_stream(stream_id=0, seed=101, config=test.config)

        assert stream_result.stream_id == 0
        assert stream_result.queries_executed == 22
        assert stream_result.queries_failed == 0
        assert len(stream_result.query_results) == 22
        assert connections and connections[0].close.called

    def test_run_with_single_stream(self) -> None:
        benchmark = _make_benchmark_mock()
        connections: list[Mock] = []
        factory = _make_connection_factory(connections)

        test = TPCHThroughputTest(benchmark=benchmark, connection_factory=factory, scale_factor=0.01, num_streams=1)
        result = test.run()

        assert isinstance(result, TPCHThroughputTestResult)
        assert result.success is True
        assert result.streams_executed == 1
        assert result.stream_results[0].queries_successful == 22
        assert result.throughput_at_size > 0
        assert result.query_throughput > 0
        assert benchmark.get_query.call_count == 22

    def test_run_records_failing_streams(self) -> None:
        benchmark = _make_benchmark_mock()
        connections: list[Mock] = []
        factory = _make_connection_factory(connections)

        test = TPCHThroughputTest(benchmark=benchmark, connection_factory=factory, scale_factor=0.01, num_streams=2)

        successful_stream = TPCHThroughputStreamResult(
            stream_id=0,
            start_time=0.0,
            end_time=0.1,
            duration=0.1,
            queries_executed=22,
            queries_successful=22,
            queries_failed=0,
        )
        failing_stream = TPCHThroughputStreamResult(
            stream_id=1,
            start_time=0.0,
            end_time=0.1,
            duration=0.1,
            queries_executed=22,
            queries_successful=20,
            queries_failed=2,
            success=False,
            error="stream failure",
        )

        with patch.object(
            test,
            "_execute_stream",
            side_effect=[successful_stream, failing_stream],
        ):
            result = test.run()

        assert result.success is False
        assert result.streams_successful == 1
        assert any("failed" in error.lower() for error in result.errors)
        assert len(result.stream_results) == 2
