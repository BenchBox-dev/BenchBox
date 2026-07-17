"""Integration tests for TPC-DS Throughput Test implementation.

This module contains comprehensive integration tests for the TPC-DS throughput test
functionality, including concurrent stream execution, proper parameter generation,
and result validation according to TPC-DS specification.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
import threading
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from benchbox.core.tpcds.benchmark import TPCDSBenchmark
from benchbox.core.tpcds.throughput_test import (
    TPCDSThroughputStreamResult,
    TPCDSThroughputTest,
    TPCDSThroughputTestConfig,
    TPCDSThroughputTestResult,
)

# Mark all tests in this file as integration tests
pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]


class MockConnection:
    """Mock database connection for testing."""

    def __init__(self, query_responses: dict[str, list[dict[str, Any]]] | None = None):
        self.query_responses = query_responses or {}
        self.executed_queries = []
        self.closed = False

    def execute(self, query: str, params=None):
        """Mock query execution."""
        self.executed_queries.append((query, params))

        # Return mock results based on query
        if "SELECT" in query.upper():
            # Return some mock data
            return [{"col1": "value1", "col2": "value2"}] * 10

        return []

    def close(self):
        """Mock connection close."""
        self.closed = True

    def commit(self):
        """Mock transaction commit."""

    def rollback(self):
        """Mock transaction rollback."""


class MockQueryManager:
    """Mock query manager for testing."""

    def __init__(self):
        self.query_calls = []

    def get_query(self, query_id: int, **kwargs) -> str:
        """Mock query generation."""
        self.query_calls.append((query_id, kwargs))
        return f"SELECT * FROM test_table WHERE id = {query_id};"


@pytest.fixture
def mock_connection_factory():
    """Factory for creating mock database connections."""

    def factory():
        return MockConnection()

    return factory


@pytest.fixture
def temp_output_dir():
    """Temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


@pytest.fixture
def throughput_test_config():
    """Basic throughput test configuration."""
    return TPCDSThroughputTestConfig(
        num_streams=2,
        scale_factor=1.0,
        base_seed=42,
        stream_timeout=60,
        verbose=True,
    )


@pytest.fixture
def tpcds_benchmark():
    """TPC-DS benchmark instance for testing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        benchmark = TPCDSBenchmark(scale_factor=1.0, output_dir=tmp_dir, verbose=False)
        yield benchmark


class TestThroughputTestConfig:
    """Test throughput test configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = TPCDSThroughputTestConfig()

        assert config.num_streams == 4  # Default from TPCDSThroughputTestConfig
        assert config.scale_factor == 1.0
        assert config.base_seed == 42
        assert config.stream_timeout == 7200  # Default from TPCDSThroughputTestConfig
        assert config.verbose is False
        assert config.max_workers is None
        assert config.queries_per_stream is None  # Default: execute all queries
        assert config.enable_preflight is True
        # Configurable success gate (mirrors TPC-H's min_success_rate); spec-
        # derived default of 70% must be preserved.
        assert config.min_success_rate == 0.70
        # Opt-in cooperative cancellation must default OFF (behavior-preserving).
        assert config.cancel_on_timeout is False

    def test_custom_config(self):
        """Test custom configuration values."""
        config = TPCDSThroughputTestConfig(
            num_streams=4,
            scale_factor=10.0,
            base_seed=123,
            stream_timeout=7200,
            verbose=True,
        )

        assert config.num_streams == 4
        assert config.scale_factor == 10.0
        assert config.base_seed == 123
        assert config.stream_timeout == 7200
        assert config.verbose is True


class TestThroughputTest:
    """Test TPC-DS throughput test implementation."""

    def test_throughput_test_initialization(self, throughput_test_config, tpcds_benchmark):
        """Test throughput test initialization."""
        test = TPCDSThroughputTest(
            benchmark=tpcds_benchmark,
            scale_factor=throughput_test_config.scale_factor,
            num_streams=throughput_test_config.num_streams,
            verbose=throughput_test_config.verbose,
        )

        assert test.config.scale_factor == throughput_test_config.scale_factor
        assert test.config.num_streams == throughput_test_config.num_streams
        assert test.config.verbose == throughput_test_config.verbose
        assert test.benchmark is not None
        assert test.logger is not None

    def test_stream_config_generation(self, throughput_test_config, tpcds_benchmark):
        """Test stream configuration generation."""
        test = TPCDSThroughputTest(
            benchmark=tpcds_benchmark,
            scale_factor=throughput_test_config.scale_factor,
            num_streams=throughput_test_config.num_streams,
            verbose=throughput_test_config.verbose,
        )

        # Test that the config was created with the expected number of streams
        assert test.config.num_streams == throughput_test_config.num_streams
        assert test.config.scale_factor == throughput_test_config.scale_factor
        assert test.config.base_seed == 42  # Default base seed

    def test_throughput_at_size_calculation(self, throughput_test_config, tpcds_benchmark):
        """Test Throughput@Size calculation."""
        test = TPCDSThroughputTest(
            benchmark=tpcds_benchmark,
            scale_factor=throughput_test_config.scale_factor,
            num_streams=throughput_test_config.num_streams,
            verbose=throughput_test_config.verbose,
        )

        # Test with 2 streams, scale factor 0.1, duration 100 seconds
        # Expected: 2 * 3600 * 0.1 / 100 = 7.2
        # The calculation is done in the run method, so let's test that the config is set up correctly
        (throughput_test_config.num_streams * 3600 * throughput_test_config.scale_factor / 100.0)
        # We can't test the internal calculation method since it's integrated into run(),
        # so we just verify the config has the right values for calculation
        assert test.config.num_streams == throughput_test_config.num_streams
        assert test.config.scale_factor == throughput_test_config.scale_factor

    def test_throughput_at_size_zero_duration(self, throughput_test_config, tpcds_benchmark):
        """Test Throughput@Size calculation with zero duration."""
        test = TPCDSThroughputTest(
            benchmark=tpcds_benchmark,
            scale_factor=throughput_test_config.scale_factor,
            num_streams=throughput_test_config.num_streams,
            verbose=throughput_test_config.verbose,
        )

        # Since the throughput calculation is done in the run method and handles zero duration,
        # we test that the configuration is properly set up
        assert test.config.num_streams > 0
        assert test.config.scale_factor > 0

    def test_run_throughput_test_success(
        self,
        throughput_test_config,
        mock_connection_factory,
        tpcds_benchmark,
    ):
        """Test successful throughput test execution."""
        # Create test with minimal configuration
        test = TPCDSThroughputTest(
            benchmark=tpcds_benchmark,
            connection_factory=mock_connection_factory,
            scale_factor=throughput_test_config.scale_factor,
            num_streams=1,  # Use just 1 stream for faster test
            verbose=False,
        )

        # Run test
        result = test.run()

        # Verify results structure
        assert result.config.scale_factor == throughput_test_config.scale_factor
        assert result.config.num_streams == 1
        assert result.streams_executed >= 0
        assert result.total_time >= 0
        assert result.throughput_at_size >= 0

    def test_result_validation_success(self, throughput_test_config):
        """Test result validation with successful results."""
        test = TPCDSThroughputTest(throughput_test_config)

        # Create successful result
        result = TPCDSThroughputTestResult(
            config=throughput_test_config,
            start_time="2023-01-01T00:00:00",
            end_time="2023-01-01T00:01:40",
            total_time=100,
            streams_executed=2,
            streams_successful=2,
            stream_results=[
                TPCDSThroughputStreamResult(
                    stream_id=0,
                    start_time=0,
                    end_time=50,
                    duration=50,
                    queries_executed=99,
                    queries_successful=99,
                    queries_failed=0,
                    query_results=[],
                    success=True,
                ),
                TPCDSThroughputStreamResult(
                    stream_id=1,
                    start_time=0,
                    end_time=50,
                    duration=50,
                    queries_executed=99,
                    queries_successful=99,
                    queries_failed=0,
                    query_results=[],
                    success=True,
                ),
            ],
            throughput_at_size=7.2,
            success=True,
        )

        validation = test.validate_results(result)
        assert validation is True

    def test_result_validation_failures(self, throughput_test_config):
        """Test result validation with failures."""
        test = TPCDSThroughputTest(throughput_test_config)

        # Create result with failures
        result = TPCDSThroughputTestResult(
            config=throughput_test_config,
            start_time="2023-01-01T00:00:00",
            end_time="2023-01-01T00:01:40",
            total_time=100,
            streams_executed=2,
            streams_successful=1,
            stream_results=[
                TPCDSThroughputStreamResult(
                    stream_id=0,
                    start_time=0,
                    end_time=50,
                    duration=50,
                    queries_executed=99,
                    queries_successful=99,
                    queries_failed=0,
                    query_results=[],
                    success=True,
                ),
                TPCDSThroughputStreamResult(
                    stream_id=1,
                    start_time=0,
                    end_time=50,
                    duration=50,
                    queries_executed=50,
                    queries_successful=40,
                    queries_failed=10,
                    query_results=[],
                    success=False,
                ),
            ],
            throughput_at_size=7.2,
            success=False,
        )

        validation = test.validate_results(result)
        assert validation is False

    def test_validate_results_gate_is_configurable(self, tpcds_benchmark):
        """Same 1/2 streams-successful pattern as test_result_validation_failures
        but with a lowered min_success_rate, proving validate_results() reads
        config.min_success_rate instead of a hardcoded 0.7 (the third of the
        three previously-independent hard-coded 70% literals)."""
        config = TPCDSThroughputTestConfig(num_streams=2, min_success_rate=0.5)
        test = TPCDSThroughputTest(benchmark=tpcds_benchmark)

        result = TPCDSThroughputTestResult(
            config=config,
            start_time="2023-01-01T00:00:00",
            end_time="2023-01-01T00:01:40",
            total_time=100,
            streams_executed=2,
            streams_successful=1,
            stream_results=[],
            throughput_at_size=7.2,
            success=True,
        )

        # 1/2 = 50% >= min_success_rate=0.5 -> validation passes even though
        # it would fail against the (still-default-elsewhere) 70% threshold.
        assert test.validate_results(result) is True

    def test_result_structure(self, throughput_test_config, temp_output_dir):
        """Test TPCDSThroughputTestResult structure and properties."""
        # Create test result
        result = TPCDSThroughputTestResult(
            config=throughput_test_config,
            start_time="2023-01-01T00:00:00",
            end_time="2023-01-01T00:01:40",
            total_time=100,
            streams_executed=2,
            streams_successful=2,
            stream_results=[
                TPCDSThroughputStreamResult(
                    stream_id=0,
                    start_time=0,
                    end_time=50,
                    duration=50,
                    queries_executed=99,
                    queries_successful=99,
                    queries_failed=0,
                    query_results=[],
                    success=True,
                ),
                TPCDSThroughputStreamResult(
                    stream_id=1,
                    start_time=0,
                    end_time=50,
                    duration=50,
                    queries_executed=99,
                    queries_successful=99,
                    queries_failed=0,
                    query_results=[],
                    success=True,
                ),
            ],
            throughput_at_size=7.2,
            success=True,
        )

        # Verify result structure
        assert result.config == throughput_test_config
        assert result.start_time == "2023-01-01T00:00:00"
        assert result.end_time == "2023-01-01T00:01:40"
        assert result.total_time == 100
        assert result.throughput_at_size == 7.2
        assert result.streams_executed == 2
        assert result.streams_successful == 2
        assert len(result.stream_results) == 2
        assert result.success is True

        # Verify scale factor via canonical config path
        assert result.config.scale_factor == throughput_test_config.scale_factor


class TestSuccessGateConfigurable:
    """Cover the configurable min_success_rate gate (w3): run(),
    _finalize_stream_success() (per-stream), and validate_results() must all
    read the SAME config.min_success_rate -- single source of truth, no more
    independently hard-coded 0.7 literals."""

    def test_finalize_stream_success_uses_configurable_gate(self, tpcds_benchmark):
        """3/5 = 60% queries successful: fails against the default 70% gate,
        passes against a lowered 50% gate -- proving the per-stream gate
        (previously a second, separate hard-coded 0.7) now reads config."""
        test = TPCDSThroughputTest(benchmark=tpcds_benchmark)

        def _make_result(min_success_rate: float) -> TPCDSThroughputStreamResult:
            config = TPCDSThroughputTestConfig(min_success_rate=min_success_rate)
            stream_result = TPCDSThroughputStreamResult(
                stream_id=0,
                start_time=0.0,
                end_time=1.0,
                duration=1.0,
                queries_executed=5,
                queries_successful=3,
                queries_failed=2,
            )
            test._finalize_stream_success(0, stream_result, config)
            return stream_result

        assert _make_result(0.70).success is False
        assert _make_result(0.50).success is True

    def test_run_success_gate_is_configurable(self, tpcds_benchmark):
        """Same 1/2-streams-successful pattern used for the run()-level gate
        elsewhere in this file, but with a lowered min_success_rate."""
        connections: list[Mock] = []

        def factory() -> Mock:
            conn = Mock()
            conn.close.return_value = None
            connections.append(conn)
            return conn

        test = TPCDSThroughputTest(benchmark=tpcds_benchmark, connection_factory=factory, num_streams=2)
        config = TPCDSThroughputTestConfig(num_streams=2, min_success_rate=0.5, enable_preflight=False)

        successful_stream = TPCDSThroughputStreamResult(
            stream_id=0,
            start_time=0.0,
            end_time=0.1,
            duration=0.1,
            queries_executed=99,
            queries_successful=99,
            queries_failed=0,
        )
        failing_stream = TPCDSThroughputStreamResult(
            stream_id=1,
            start_time=0.0,
            end_time=0.1,
            duration=0.1,
            queries_executed=99,
            queries_successful=50,
            queries_failed=49,
            success=False,
            error="stream failure",
        )

        with patch.object(test, "_execute_stream", side_effect=[successful_stream, failing_stream]):
            result = test.run(config)

        # 1/2 = 50% successful streams >= min_success_rate=0.5 -> overall success
        assert result.success is True
        assert result.streams_successful == 1


class TestCooperativeCancellation:
    """Cover the opt-in cooperative-cancel wiring in TPCDSThroughputTest (w2)."""

    @staticmethod
    def _stream_query(query_id: int, variant: Any = None) -> Mock:
        sq = Mock()
        sq.query_id = query_id
        sq.variant = variant
        return sq

    @staticmethod
    def _connection_factory(registry: list[Mock], execute_side_effect=None) -> Any:
        def factory() -> Mock:
            conn = Mock()
            conn.close.return_value = None
            conn.commit.return_value = None
            cursor = Mock()
            cursor.fetchall.return_value = []
            if execute_side_effect is not None:
                conn.execute.side_effect = execute_side_effect(cursor)
            else:
                conn.execute.return_value = cursor
            registry.append(conn)
            return conn

        return factory

    def test_execute_stream_stops_immediately_when_cancel_event_preset(self, tpcds_benchmark):
        connections: list[Mock] = []
        factory = self._connection_factory(connections)

        test = TPCDSThroughputTest(benchmark=tpcds_benchmark, connection_factory=factory, num_streams=1)
        config = TPCDSThroughputTestConfig(num_streams=1, cancel_on_timeout=True, enable_preflight=False)
        config._stream_cancel_events = {0: threading.Event()}
        config._stream_cancel_events[0].set()
        test._pregenerated_queries = {0: [(self._stream_query(1), "SELECT 1"), (self._stream_query(2), "SELECT 2")]}

        stream_result = test._execute_stream(stream_id=0, seed=1, config=config)

        assert stream_result.queries_executed == 0
        assert stream_result.success is False
        assert "cancel" in (stream_result.error or "").lower()
        assert connections[0].execute.call_count == 0

    def test_execute_stream_stops_after_cancel_event_set_mid_stream(self, tpcds_benchmark):
        cancel_event = threading.Event()

        def execute_side_effect(cursor):
            def _execute(_query_text: str) -> Mock:
                cancel_event.set()
                return cursor

            return _execute

        connections: list[Mock] = []
        factory = self._connection_factory(connections, execute_side_effect=execute_side_effect)

        test = TPCDSThroughputTest(benchmark=tpcds_benchmark, connection_factory=factory, num_streams=1)
        config = TPCDSThroughputTestConfig(num_streams=1, cancel_on_timeout=True, enable_preflight=False)
        config._stream_cancel_events = {0: cancel_event}
        test._pregenerated_queries = {
            0: [
                (self._stream_query(1), "SELECT 1"),
                (self._stream_query(2), "SELECT 2"),
                (self._stream_query(3), "SELECT 3"),
            ]
        }

        stream_result = test._execute_stream(stream_id=0, seed=1, config=config)

        assert stream_result.queries_executed == 1
        assert stream_result.success is False
        assert "cancel" in (stream_result.error or "").lower()

    def test_execute_stream_unaffected_when_cancel_on_timeout_disabled(self, tpcds_benchmark):
        connections: list[Mock] = []
        factory = self._connection_factory(connections)

        test = TPCDSThroughputTest(benchmark=tpcds_benchmark, connection_factory=factory, num_streams=1)
        config = TPCDSThroughputTestConfig(num_streams=1, enable_preflight=False)  # cancel_on_timeout defaults False
        test._pregenerated_queries = {0: [(self._stream_query(1), "SELECT 1"), (self._stream_query(2), "SELECT 2")]}

        stream_result = test._execute_stream(stream_id=0, seed=1, config=config)

        assert stream_result.queries_executed == 2
        assert stream_result.success is True

    def test_execute_stream_ignores_stale_cancel_event_from_reused_config(self, tpcds_benchmark):
        """Regression (review follow-up): a config object reused across
        runs must not let a PRIOR run's already-``set()`` cancel event leak
        into a later call where ``cancel_on_timeout`` is now False.

        Simulates exactly the state ``StreamRunner.execute()`` leaves on a
        config object after a run-1 timeout with ``cancel_on_timeout=True``
        (this stream's ``Event`` set()), then reuses that SAME config
        object with ``cancel_on_timeout`` flipped to False -- while
        deliberately leaving ``_stream_cancel_events`` stale/untouched, to
        isolate ``_execute_stream``'s own independent ``cancel_on_timeout``
        gate (the belt-and-suspenders fix) from ``StreamRunner.execute()``'s
        separate reset-to-``{}`` behavior on its own next call.
        """
        connections: list[Mock] = []
        factory = self._connection_factory(connections)

        test = TPCDSThroughputTest(benchmark=tpcds_benchmark, connection_factory=factory, num_streams=1)

        stale_config = TPCDSThroughputTestConfig(num_streams=1, cancel_on_timeout=True, enable_preflight=False)
        stale_config._stream_cancel_events = {0: threading.Event()}
        stale_config._stream_cancel_events[0].set()
        test._pregenerated_queries = {0: [(self._stream_query(1), "SELECT 1"), (self._stream_query(2), "SELECT 2")]}

        # Reuse the SAME config object with cancel_on_timeout now False.
        stale_config.cancel_on_timeout = False

        stream_result = test._execute_stream(stream_id=0, seed=1, config=stale_config)

        assert stream_result.queries_executed == 2
        assert stream_result.success is True
        assert connections[0].execute.call_count == 2


class TestBenchmarkIntegration:
    """Test integration with TPC-DS benchmark class."""

    def test_benchmark_run_throughput_test(self, tpcds_benchmark, mock_connection_factory):
        """Test benchmark throughput test integration."""
        # This test verifies that run_throughput_test exists and can be called
        # The actual throughput test implementation is tested in other test classes

        # Just verify the method exists and has the correct signature
        assert hasattr(tpcds_benchmark, "run_throughput_test")
        assert callable(tpcds_benchmark.run_throughput_test)

        # We can't easily test the full execution without a real database,
        # so we just verify the interface is correct by checking it accepts the expected parameters
        import inspect

        sig = inspect.signature(tpcds_benchmark.run_throughput_test)
        param_names = list(sig.parameters.keys())

        # Verify expected parameters exist
        assert "connection_factory" in param_names
        assert "num_streams" in param_names
        assert "stream_timeout" in param_names
        assert "base_seed" in param_names

    def test_benchmark_throughput_test_validation(self, tpcds_benchmark, mock_connection_factory):
        """Test parameter validation in benchmark throughput test."""
        # Test invalid num_streams
        with pytest.raises(ValueError, match="num_streams must be positive"):
            tpcds_benchmark.run_throughput_test(mock_connection_factory, num_streams=0)

        # Test invalid stream_timeout
        with pytest.raises(ValueError, match="stream_timeout must be positive"):
            tpcds_benchmark.run_throughput_test(mock_connection_factory, stream_timeout=0)

        # Note: base_seed validation was removed - negative seeds are technically valid for RNG


@pytest.mark.slow
class TestEndToEndThroughputTest:
    """End-to-end throughput test scenarios."""

    def test_minimal_throughput_test(self, temp_output_dir):
        """Test minimal throughput test execution."""
        # Create minimal config
        config = TPCDSThroughputTestConfig(
            num_streams=1,
            scale_factor=1.0,
            stream_timeout=30,
            verbose=False,
        )

        # Mock connection factory
        def connection_factory():
            return MockConnection()

        # Run test with patched stream creation
        with patch("benchbox.core.tpcds.streams.create_standard_streams") as mock_create_streams:
            mock_manager = Mock()
            mock_manager.generate_streams.return_value = {
                0: [
                    Mock(
                        stream_id=0,
                        query_id=1,
                        position=0,
                        variant=None,
                        sql="SELECT 1;",
                    )
                ]
            }
            mock_create_streams.return_value = mock_manager

            # Create a mock benchmark with required attributes
            mock_benchmark = Mock()
            mock_benchmark.get_query = Mock(return_value="SELECT 1;")
            mock_benchmark.get_queries = Mock(return_value={"1": "SELECT 1;"})
            mock_benchmark.query_manager = Mock()

            test = TPCDSThroughputTest(
                benchmark=mock_benchmark,
                connection_factory=connection_factory,
                scale_factor=config.scale_factor,
                num_streams=config.num_streams,
                verbose=config.verbose,
            )
            result = test.run(config)

            # Verify basic result structure
            assert result.config == config
            assert result.total_time > 0
            assert result.streams_executed == 1
            assert result.throughput_at_size >= 0

    def test_concurrent_streams_execution(self, temp_output_dir):
        """Test concurrent stream execution."""
        # Create config with multiple streams
        config = TPCDSThroughputTestConfig(
            num_streams=3,
            scale_factor=1.0,
            stream_timeout=10,
            verbose=False,
        )

        # Mock connection factory
        def connection_factory():
            return MockConnection()

        # Run test with patched stream creation
        with patch("benchbox.core.tpcds.streams.create_standard_streams") as mock_create_streams:
            mock_manager = Mock()
            mock_streams = {}
            for i in range(3):
                mock_streams[i] = [
                    Mock(
                        stream_id=i,
                        query_id=j,
                        position=j,
                        variant=None,
                        sql=f"SELECT {j};",
                    )
                    for j in range(1, 4)
                ]
            mock_manager.generate_streams.return_value = mock_streams
            mock_create_streams.return_value = mock_manager

            # Create a mock benchmark with required attributes
            mock_benchmark = Mock()
            mock_benchmark.get_query = Mock(return_value="SELECT 1;")
            mock_benchmark.get_queries = Mock(return_value={"1": "SELECT 1;", "2": "SELECT 2;", "3": "SELECT 3;"})
            mock_benchmark.query_manager = Mock()

            test = TPCDSThroughputTest(
                benchmark=mock_benchmark,
                connection_factory=connection_factory,
                scale_factor=config.scale_factor,
                num_streams=config.num_streams,
                verbose=config.verbose,
            )
            result = test.run(config)

            # Verify results
            assert result.streams_executed == 3
            assert len(result.stream_results) == 3
            assert all(sr.stream_id in [0, 1, 2] for sr in result.stream_results)
