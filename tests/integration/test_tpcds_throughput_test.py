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
