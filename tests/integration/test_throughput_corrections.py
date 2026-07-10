"""Integration tests validating throughput test corrections.

This module contains tests that validate the critical fixes made to the
TPC-H and TPC-DS Throughput Test implementations, including:
- Timing measurement accuracy (TTT calculation)
- Timeout behavior and error reporting
- Connection cleanup on failures

These tests use real ThreadPoolExecutor and actual timing to validate
behavior that cannot be tested with mocks alone.
"""

from __future__ import annotations

import time
from threading import Lock
from unittest.mock import Mock

import pytest

from benchbox.core.tpcds.throughput_test import (
    TPCDSThroughputTest,
    TPCDSThroughputTestConfig,
)
from benchbox.core.tpch.throughput_test import (
    TPCHThroughputTest,
    TPCHThroughputTestConfig,
)

# Mark all tests in this file as integration tests
pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]


class TestTimingMeasurementAccuracy:
    """Validate that Total Test Time (TTT) is measured correctly."""

    def test_tpch_ttt_excludes_setup_overhead(self):
        """Test that TPC-H TTT measures only concurrent execution time."""
        # Create a benchmark that tracks when queries actually execute
        execution_times = []
        execution_lock = Lock()

        def mock_get_query(*args, **kwargs):
            with execution_lock:
                execution_times.append(time.time())
            return "SELECT 1"

        benchmark = Mock()
        benchmark.get_query = mock_get_query

        # Create connections that track execution timing
        connection_creation_times = []
        connection_lock = Lock()

        def connection_factory():
            with connection_lock:
                connection_creation_times.append(time.time())

            conn = Mock()
            cursor = Mock()
            cursor.fetchall.return_value = []
            conn.execute.return_value = cursor
            conn.close.return_value = None
            return conn

        # Run throughput test with 2 streams
        config = TPCHThroughputTestConfig(
            scale_factor=1.0,
            num_streams=2,
            stream_timeout=10,
            verbose=False,
        )

        test = TPCHThroughputTest(
            benchmark=benchmark,
            connection_factory=connection_factory,
            scale_factor=config.scale_factor,
            num_streams=config.num_streams,
            verbose=config.verbose,
        )

        test_start = time.time()
        result = test.run(config)
        test_end = time.time()

        # Verify test succeeded
        assert result.success
        assert result.streams_executed == 2
        assert len(result.stream_results) == 2

        # Critical validation: TTT should be less than wall-clock time
        # because it excludes setup/teardown overhead
        wall_clock_time = test_end - test_start
        measured_ttt = result.total_time

        # TTT should be based on actual stream execution time
        assert measured_ttt > 0
        assert measured_ttt <= wall_clock_time

        # TTT should be close to the duration of the longest stream
        # (since streams run concurrently)
        max_stream_duration = max(sr.duration for sr in result.stream_results)

        # TTT should match max stream duration within reasonable tolerance
        # (allowing for thread scheduling overhead)
        assert abs(measured_ttt - max_stream_duration) < 0.5  # 500ms tolerance

    def test_tpcds_ttt_excludes_setup_overhead(self):
        """Test that TPC-DS TTT measures only concurrent execution time."""
        # Similar structure to TPC-H test
        execution_times = []
        execution_lock = Lock()

        def mock_get_query(*args, **kwargs):
            with execution_lock:
                execution_times.append(time.time())
            return "SELECT 1"

        def connection_factory():
            conn = Mock()
            cursor = Mock()
            cursor.fetchall.return_value = []
            conn.execute.return_value = cursor
            conn.close.return_value = None
            conn.commit.return_value = None
            return conn

        # Create mock benchmark
        benchmark = Mock()
        benchmark.get_query = mock_get_query
        benchmark.get_queries.return_value = {"1": "SELECT 1", "2": "SELECT 2"}
        benchmark.query_manager = Mock()

        config = TPCDSThroughputTestConfig(
            scale_factor=1.0,
            num_streams=2,
            stream_timeout=10,
            verbose=False,
            queries_per_stream=2,  # Limit to 2 queries for faster test
            enable_preflight=False,  # Skip preflight for this test
        )

        test = TPCDSThroughputTest(
            benchmark=benchmark,
            connection_factory=connection_factory,
            scale_factor=config.scale_factor,
            num_streams=config.num_streams,
            verbose=config.verbose,
        )

        # Patch stream generation to avoid complexity
        from unittest.mock import patch

        with patch("benchbox.core.tpcds.streams.create_standard_streams") as mock_create:
            mock_manager = Mock()
            mock_streams = {}
            for stream_id in range(2):
                mock_streams[stream_id] = [
                    Mock(stream_id=stream_id, query_id=1, position=1, variant=None, sql="SELECT 1"),
                    Mock(stream_id=stream_id, query_id=2, position=2, variant=None, sql="SELECT 2"),
                ]
            mock_manager.generate_streams.return_value = mock_streams
            mock_create.return_value = mock_manager

            test_start = time.time()
            result = test.run(config)
            test_end = time.time()

        # Validations
        assert result.success
        assert result.streams_executed == 2

        wall_clock_time = test_end - test_start
        measured_ttt = result.total_time

        assert measured_ttt > 0
        assert measured_ttt <= wall_clock_time

        # TTT should match concurrent execution time
        if result.stream_results:
            max_stream_duration = max(sr.duration for sr in result.stream_results)
            assert abs(measured_ttt - max_stream_duration) < 0.5


class TestGenerationExcludedFromTiming:
    """Validate that query GENERATION cost is excluded from the timed window.

    Query generation (qgen/dsqgen subprocess calls) used to run INSIDE the
    per-query timed region, contaminating both ``execution_time_seconds`` and
    TTT with generation cost. These tests instrument ``get_query`` to sleep
    for a known duration and assert neither the per-query timing nor TTT
    include it, proving generation now happens entirely before the timed
    concurrent window (see ``_pregenerate_stream_queries`` in both
    ``tpch/throughput_test.py`` and ``tpcds/throughput_test.py``).
    """

    GENERATION_SLEEP = 0.3

    def test_tpch_generation_time_excluded_from_timing(self):
        """22 queries x 0.3s sleep = 6.6s of generation cost must not land
        inside TTT or any single query's execution_time_seconds."""

        def slow_get_query(*args, **kwargs):
            time.sleep(self.GENERATION_SLEEP)
            return "SELECT 1"

        benchmark = Mock()
        benchmark.get_query = slow_get_query

        def connection_factory():
            conn = Mock()
            cursor = Mock()
            cursor.fetchall.return_value = []
            conn.execute.return_value = cursor
            conn.close.return_value = None
            return conn

        config = TPCHThroughputTestConfig(
            scale_factor=0.01,
            num_streams=1,
            stream_timeout=30,
            verbose=False,
        )

        test = TPCHThroughputTest(
            benchmark=benchmark,
            connection_factory=connection_factory,
            scale_factor=config.scale_factor,
            num_streams=config.num_streams,
            verbose=config.verbose,
        )

        result = test.run(config)

        assert result.success
        assert result.stream_results[0].queries_executed == 22

        total_generation_time = 22 * self.GENERATION_SLEEP
        # TTT excludes generation entirely -- it happens before the timed
        # window starts, so it should be nowhere near the 6.6s of sleeping
        # that 22 in-loop get_query() calls would have added.
        assert result.total_time < total_generation_time
        for query_result in result.stream_results[0].query_results:
            assert query_result["execution_time_seconds"] < self.GENERATION_SLEEP

    def test_tpcds_generation_time_excluded_from_timing(self):
        """3 queries x 0.3s sleep = 0.9s of generation cost must not land
        inside TTT or any single query's execution_time_seconds."""

        def slow_get_query(*args, **kwargs):
            time.sleep(self.GENERATION_SLEEP)
            return "SELECT 1"

        def connection_factory():
            conn = Mock()
            cursor = Mock()
            cursor.fetchall.return_value = []
            conn.execute.return_value = cursor
            conn.close.return_value = None
            conn.commit.return_value = None
            return conn

        benchmark = Mock()
        benchmark.get_query = slow_get_query
        benchmark.get_queries.return_value = {"1": "SELECT 1", "2": "SELECT 2", "3": "SELECT 3"}
        benchmark.query_manager = Mock()

        config = TPCDSThroughputTestConfig(
            scale_factor=1.0,
            num_streams=1,
            stream_timeout=30,
            verbose=False,
            queries_per_stream=3,
            enable_preflight=True,  # pre-generation only runs when preflight is enabled
        )

        test = TPCDSThroughputTest(
            benchmark=benchmark,
            connection_factory=connection_factory,
            scale_factor=config.scale_factor,
            num_streams=config.num_streams,
            verbose=config.verbose,
        )

        from unittest.mock import patch

        with patch("benchbox.core.tpcds.streams.create_standard_streams") as mock_create:
            mock_manager = Mock()
            mock_manager.generate_streams.return_value = {
                0: [
                    Mock(stream_id=0, query_id=1, position=0, variant=None, sql="SELECT 1"),
                    Mock(stream_id=0, query_id=2, position=1, variant=None, sql="SELECT 2"),
                    Mock(stream_id=0, query_id=3, position=2, variant=None, sql="SELECT 3"),
                ]
            }
            mock_create.return_value = mock_manager

            result = test.run(config)

        assert result.success
        assert result.stream_results[0].queries_executed == 3

        total_generation_time = 3 * self.GENERATION_SLEEP
        assert result.total_time < total_generation_time
        for query_result in result.stream_results[0].query_results:
            assert query_result["execution_time_seconds"] < self.GENERATION_SLEEP


class TestConnectionCleanup:
    """Validate connection cleanup on failures."""

    def test_tpch_connection_closed_on_query_failure(self):
        """Test that TPC-H closes connections even when queries fail."""
        connections_created = []
        connections_closed = []
        creation_lock = Lock()
        close_lock = Lock()

        def connection_factory():
            conn = Mock()

            # Track creation
            with creation_lock:
                connections_created.append(conn)

            # Track closure
            original_close = conn.close

            def tracked_close():
                with close_lock:
                    connections_closed.append(conn)
                return original_close()

            conn.close = tracked_close

            # Make execute fail
            def failing_execute(*args, **kwargs):
                raise RuntimeError("Simulated query failure")

            conn.execute = failing_execute

            return conn

        benchmark = Mock()
        benchmark.get_query.return_value = "SELECT 1"

        config = TPCHThroughputTestConfig(
            scale_factor=1.0,
            num_streams=2,
            stream_timeout=5,
            verbose=False,
        )

        test = TPCHThroughputTest(
            benchmark=benchmark,
            connection_factory=connection_factory,
            scale_factor=config.scale_factor,
            num_streams=config.num_streams,
            verbose=config.verbose,
        )

        result = test.run(config)

        # Verify test failed (queries failed)
        assert not result.success

        # Critical validation: All connections were closed
        # Even though queries failed, connections must be cleaned up
        assert len(connections_created) == 2  # 2 streams = 2 connections

        # Wait briefly for background cleanup paths to close all connections.
        deadline = time.time() + 0.5
        while len(connections_closed) < 2 and time.time() < deadline:
            time.sleep(0.01)

        assert len(connections_closed) == 2  # All connections closed

        # Same connection objects should be in both lists
        assert set(connections_created) == set(connections_closed)

    def test_tpcds_connection_closed_on_stream_failure(self):
        """Test that TPC-DS closes connections even when streams fail."""
        connections_created = []
        connections_closed = []
        creation_lock = Lock()
        close_lock = Lock()

        def connection_factory():
            conn = Mock()

            with creation_lock:
                connections_created.append(conn)

            original_close = conn.close

            def tracked_close():
                with close_lock:
                    connections_closed.append(conn)
                return original_close()

            conn.close = tracked_close

            # Make execute fail
            def failing_execute(*args, **kwargs):
                raise RuntimeError("Simulated failure")

            conn.execute = failing_execute
            conn.commit = Mock()

            return conn

        benchmark = Mock()
        benchmark.get_query.return_value = "SELECT 1"
        benchmark.get_queries.return_value = {"1": "SELECT 1"}
        benchmark.query_manager = Mock()

        config = TPCDSThroughputTestConfig(
            scale_factor=1.0,
            num_streams=2,
            stream_timeout=5,
            verbose=False,
            queries_per_stream=1,
            enable_preflight=False,
        )

        test = TPCDSThroughputTest(
            benchmark=benchmark,
            connection_factory=connection_factory,
            scale_factor=config.scale_factor,
            num_streams=config.num_streams,
            verbose=config.verbose,
        )

        from unittest.mock import patch

        with patch("benchbox.core.tpcds.streams.create_standard_streams") as mock_create:
            mock_manager = Mock()
            mock_streams = {
                0: [Mock(stream_id=0, query_id=1, position=1, variant=None, sql="SELECT 1")],
                1: [Mock(stream_id=1, query_id=1, position=1, variant=None, sql="SELECT 1")],
            }
            mock_manager.generate_streams.return_value = mock_streams
            mock_create.return_value = mock_manager

            result = test.run(config)

        # Verify failures occurred
        assert result.streams_executed == 2

        # Validate cleanup
        assert len(connections_created) == 2

        deadline = time.time() + 0.5
        while len(connections_closed) < 2 and time.time() < deadline:
            time.sleep(0.01)

        assert len(connections_closed) == 2
        assert set(connections_created) == set(connections_closed)
