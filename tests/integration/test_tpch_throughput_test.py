"""Integration tests for the simulated TPC-H throughput test implementation."""

from __future__ import annotations

import threading
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
        # Opt-in cooperative cancellation must default OFF (behavior-preserving).
        assert config.cancel_on_timeout is False


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

    def test_run_success_gate_is_configurable(self) -> None:
        """Same 1/2 streams-successful pattern as test_run_records_failing_streams,
        but with a lowered min_success_rate: proves the gate is read from
        config rather than a hardcoded threshold."""
        benchmark = _make_benchmark_mock()
        connections: list[Mock] = []
        factory = _make_connection_factory(connections)

        test = TPCHThroughputTest(benchmark=benchmark, connection_factory=factory, scale_factor=0.01, num_streams=2)
        config = TPCHThroughputTestConfig(scale_factor=0.01, num_streams=2, min_success_rate=0.5)

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

        with patch.object(test, "_execute_stream", side_effect=[successful_stream, failing_stream]):
            result = test.run(config)

        # 1/2 = 50% successful streams >= min_success_rate=0.5 -> overall success
        assert result.success is True
        assert result.streams_successful == 1


class TestCooperativeCancellation:
    """Cover the opt-in cooperative-cancel wiring in TPCHThroughputTest (w2)."""

    def test_execute_stream_stops_immediately_when_cancel_event_preset(self) -> None:
        """If StreamRunner.execute() had already signalled cancellation before
        _execute_stream() even starts its query loop (the worst case for a
        timeout that fires almost instantly), no queries run at all."""
        benchmark = _make_benchmark_mock()
        connections: list[Mock] = []
        factory = _make_connection_factory(connections)

        test = TPCHThroughputTest(benchmark=benchmark, connection_factory=factory, scale_factor=0.01, num_streams=1)
        config = TPCHThroughputTestConfig(scale_factor=0.01, num_streams=1, cancel_on_timeout=True)
        config._stream_cancel_events = {0: threading.Event()}
        config._stream_cancel_events[0].set()

        stream_result = test._execute_stream(stream_id=0, seed=1, config=config)

        assert stream_result.queries_executed == 0
        assert stream_result.success is False
        assert "cancel" in (stream_result.error or "").lower()
        assert benchmark.get_query.call_count == 0

    def test_execute_stream_stops_after_cancel_event_set_mid_stream(self) -> None:
        """Cancellation signalled *during* the first query's execution stops
        every subsequent query -- proving cooperative cancel actually halts
        an in-progress stream, not just a not-yet-started one."""
        benchmark = _make_benchmark_mock()
        cancel_event = threading.Event()

        connections: list[Mock] = []

        def factory() -> Mock:
            conn = Mock()
            conn.close.return_value = None
            cursor = Mock()
            cursor.fetchall.return_value = []

            def execute_and_cancel(_query_text: str) -> Mock:
                # Simulate this query's timeout firing while it runs: signal
                # cancellation from "inside" the query, as StreamRunner.execute()
                # would from its own thread once the deadline elapses.
                cancel_event.set()
                return cursor

            conn.execute.side_effect = execute_and_cancel
            connections.append(conn)
            return conn

        test = TPCHThroughputTest(benchmark=benchmark, connection_factory=factory, scale_factor=0.01, num_streams=1)
        config = TPCHThroughputTestConfig(scale_factor=0.01, num_streams=1, cancel_on_timeout=True)
        config._stream_cancel_events = {0: cancel_event}

        stream_result = test._execute_stream(stream_id=0, seed=1, config=config)

        # Exactly 1 query ran (the one that set the event) before the loop
        # noticed and stopped -- not all 22.
        assert stream_result.queries_executed == 1
        assert stream_result.success is False
        assert "cancel" in (stream_result.error or "").lower()

    def test_execute_stream_unaffected_when_cancel_on_timeout_disabled(self) -> None:
        """Sanity check: with the opt-in flag left at its default (False),
        _execute_stream never even looks for a cancel event."""
        benchmark = _make_benchmark_mock()
        connections: list[Mock] = []
        factory = _make_connection_factory(connections)

        test = TPCHThroughputTest(benchmark=benchmark, connection_factory=factory, scale_factor=0.01, num_streams=1)
        config = TPCHThroughputTestConfig(scale_factor=0.01, num_streams=1)  # cancel_on_timeout defaults False

        stream_result = test._execute_stream(stream_id=0, seed=1, config=config)

        assert stream_result.queries_executed == 22
        assert stream_result.success is True
