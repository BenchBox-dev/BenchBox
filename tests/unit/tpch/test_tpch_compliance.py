#!/usr/bin/env python3
"""TPC Specification Compliance Validation Tests

Tests to ensure TPC-H and TPC-DS implementations follow official specifications
for query ordering in power and throughput tests.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import MagicMock

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestTPCHCompliance:
    """Test TPC-H specification compliance."""

    def test_tpch_power_test_uses_correct_permutation(self):
        """Test that TPC-H power test uses stream 0 permutation."""
        from benchbox.core.tpch.power_test import TPCHPowerTest
        from benchbox.core.tpch.streams import TPCHStreams

        # Mock benchmark and connection
        mock_benchmark = MagicMock()
        mock_connection = MagicMock()

        # Create power test with stream_id=0
        power_test = TPCHPowerTest(
            benchmark=mock_benchmark,
            connection=mock_connection,
            stream_id=0,
            verbose=True,
        )

        # Expected permutation for stream 0
        expected_permutation = TPCHStreams.PERMUTATION_MATRIX[0]
        assert expected_permutation == [
            14,
            2,
            9,
            20,
            6,
            17,
            18,
            8,
            21,
            13,
            3,
            22,
            16,
            4,
            11,
            15,
            1,
            10,
            19,
            5,
            7,
            12,
        ]

        # Mock the query generation to avoid actual execution
        executed_queries = []

        def mock_get_query(query_id, **kwargs):
            executed_queries.append(query_id)
            return f"SELECT {query_id}"

        # Mock the preflight validation to avoid actual query generation
        power_test._preflight_validate_generation = MagicMock()

        # Mock the benchmark's get_query method
        mock_benchmark.get_query = mock_get_query

        # Run power test (will simulate execution)
        result = power_test.run()

        # Verify queries were executed in correct permutation order (only once)
        assert executed_queries == expected_permutation
        assert len(executed_queries) == 22

        # Verify stream_id was included in results
        assert result.config.stream_id == 0

    def test_tpch_power_test_different_streams_use_different_permutations(self):
        """Test that different stream IDs use different permutations."""
        from benchbox.core.tpch.streams import TPCHStreams

        # Verify that different streams have different permutations
        stream_0_perm = TPCHStreams.PERMUTATION_MATRIX[0]
        stream_1_perm = TPCHStreams.PERMUTATION_MATRIX[1]
        stream_2_perm = TPCHStreams.PERMUTATION_MATRIX[2]

        # Each permutation should be different
        assert stream_0_perm != stream_1_perm
        assert stream_1_perm != stream_2_perm
        assert stream_0_perm != stream_2_perm

        # But all should contain the same queries (1-22)
        assert set(stream_0_perm) == set(range(1, 23))
        assert set(stream_1_perm) == set(range(1, 23))
        assert set(stream_2_perm) == set(range(1, 23))

    def test_tpch_power_test_disabled_mode_disables_validation(self):
        """Explicit disabled mode should turn validation off at config resolution time."""
        from benchbox.core.tpch.power_test import TPCHPowerTest

        power_test = TPCHPowerTest(
            benchmark=MagicMock(),
            connection=MagicMock(),
            stream_id=0,
            validation_mode="disabled",
        )

        assert power_test.config.validation is False
        assert power_test.config.validation_mode == "disabled"

    def test_tpch_power_test_explicit_mode_preserves_non_stream_validation(self):
        """Explicit validation modes should bypass the auto-disable for non-stream-0 runs."""
        from benchbox.core.tpch.power_test import TPCHPowerTest

        power_test = TPCHPowerTest(
            benchmark=MagicMock(),
            connection=MagicMock(),
            stream_id=1,
            validation_mode="loose",
        )

        assert power_test.config.validation is True
        assert power_test.config.validation_mode == "loose"

    def test_tpch_throughput_test_uses_stream_specific_permutations(self):
        """Test that TPC-H throughput test uses different permutations for different streams."""
        from benchbox.core.tpch.streams import TPCHStreams
        from benchbox.core.tpch.throughput_test import TPCHThroughputTest

        # Mock benchmark
        mock_benchmark = MagicMock()
        mock_benchmark.get_query.return_value = "SELECT 1"
        mock_connection_factory = MagicMock(return_value=MagicMock())

        # Create throughput test
        throughput_test = TPCHThroughputTest(
            benchmark=mock_benchmark,
            connection_factory=mock_connection_factory,
            verbose=True,
        )

        # Test stream 0 execution
        stream_0_queries = []
        stream_1_queries = []

        def capture_queries_stream_0(query_id, **kwargs):
            if kwargs.get("stream_id") == 0:
                stream_0_queries.append(query_id)
            elif kwargs.get("stream_id") == 1:
                stream_1_queries.append(query_id)
            return f"SELECT {query_id}"

        mock_benchmark.get_query = capture_queries_stream_0

        # Simulate stream execution
        config = MagicMock()
        config.num_streams = 2
        config.scale_factor = 0.01
        config.verbose = True
        config.base_seed = 1

        # Execute streams (mocked)
        # This would normally be called by the throughput test framework
        throughput_test._execute_stream(0, 1, config)
        throughput_test._execute_stream(1, 2, config)

        # Verify different streams used different permutations
        expected_stream_0 = TPCHStreams.PERMUTATION_MATRIX[0]
        expected_stream_1 = TPCHStreams.PERMUTATION_MATRIX[1]

        assert stream_0_queries == expected_stream_0
        assert stream_1_queries == expected_stream_1
        assert stream_0_queries != stream_1_queries


class TestTPCDSCompliance:
    """Test TPC-DS specification compliance."""

    def test_tpcds_power_test_uses_stream_permutation(self):
        """Test that TPC-DS power test uses proper stream permutation."""
        from benchbox.core.tpcds.power_test import TPCDSPowerTest

        # Mock benchmark with query manager
        mock_benchmark = MagicMock()
        mock_query_manager = MagicMock()
        mock_benchmark.query_manager = mock_query_manager
        mock_benchmark.get_queries.return_value = {str(i): f"query_{i}" for i in range(1, 100)}
        MagicMock()

        executed_query_order = []

        def mock_get_query(query_id, **kwargs):
            executed_query_order.append(query_id)
            return f"SELECT {query_id}"

        mock_benchmark.get_query = mock_get_query

        # Create power test with stream_id=0
        power_test = TPCDSPowerTest(benchmark=mock_benchmark, stream_id=0, verbose=True)

        # Run power test
        result = power_test.run()

        # Verify that queries were executed (not in sequential order 1,2,3...)
        assert len(executed_query_order) > 0
        assert executed_query_order != list(range(1, len(executed_query_order) + 1))

        # Verify stream_id was set correctly
        assert result.config.stream_id == 0

    def test_tpcds_stream_manager_generates_different_permutations(self):
        """Test that TPC-DS stream manager generates different permutations."""
        from benchbox.core.tpcds.streams import create_standard_streams

        # Mock query manager
        mock_query_manager = MagicMock()

        # Create stream manager with 3 streams
        stream_manager = create_standard_streams(
            query_manager=mock_query_manager,
            num_streams=3,
            query_range=(1, 10),  # Small range for testing
            base_seed=42,
        )

        # Generate streams
        streams = stream_manager.generate_streams()

        # Extract query orders from each stream (main queries only)
        stream_0_order = [sq.query_id for sq in streams[0] if sq.variant is None]
        stream_1_order = [sq.query_id for sq in streams[1] if sq.variant is None]
        stream_2_order = [sq.query_id for sq in streams[2] if sq.variant is None]

        # Verify different streams have different orderings
        assert stream_0_order != stream_1_order
        assert stream_1_order != stream_2_order
        assert stream_0_order != stream_2_order

        # But all should contain the same queries
        assert set(stream_0_order) == set(stream_1_order) == set(stream_2_order)


class TestPowerRunIterationsCompliance:
    """Test power run iterations use different stream permutations."""

    def test_power_run_executor_uses_different_streams_per_iteration(self):
        """Test that power run executor uses different stream IDs for each iteration."""
        from benchbox.utils.execution_manager import PowerRunExecutor

        # Mock config manager - lambda must accept optional default parameter
        mock_config_manager = MagicMock()
        config_values = {
            "execution.power_run.iterations": 3,
            "execution.power_run.warm_up_iterations": 0,
            "execution.power_run.timeout_per_iteration_minutes": 60,
            "execution.power_run.fail_fast": False,
            "execution.power_run.collect_metrics": True,
        }
        mock_config_manager.get.side_effect = lambda key, default=None: config_values.get(key, default)

        # Create executor
        executor = PowerRunExecutor(config_manager=mock_config_manager)

        # Track stream IDs used
        stream_ids_used = []

        def mock_power_test_factory(stream_id=None):
            stream_ids_used.append(stream_id)
            mock_test = MagicMock()
            mock_test.run.return_value = MagicMock(
                success=True,
                power_at_size=100.0,
                total_time=10.0,
                queries_executed=22,
                queries_successful=22,
            )
            return mock_test

        # Execute power runs
        result = executor.execute_power_runs(mock_power_test_factory)

        # Verify different stream IDs were used for different iterations
        assert len(stream_ids_used) == 3  # 3 iterations
        assert stream_ids_used == [0, 1, 2]  # Different stream ID for each iteration
        assert result.iterations_completed == 3


class TestConcurrentQueriesCompliance:
    """Test concurrent queries use different stream permutations."""

    def test_concurrent_query_executor_assigns_different_streams(self):
        """Test that concurrent query executor assigns different stream IDs."""
        from benchbox.utils.execution_manager import ConcurrentQueryExecutor

        # Mock config manager - lambda must accept optional default parameter
        mock_config_manager = MagicMock()
        config_values = {
            "execution.concurrent_queries.enabled": True,
            "execution.concurrent_queries.max_concurrent": 3,
            "execution.concurrent_queries.query_timeout_seconds": 300,
            "execution.concurrent_queries.stream_timeout_seconds": 3600,
            "execution.concurrent_queries.retry_failed_queries": True,
            "execution.concurrent_queries.max_retries": 3,
        }
        mock_config_manager.get.side_effect = lambda key, default=None: config_values.get(key, default)

        # Create executor
        executor = ConcurrentQueryExecutor(config_manager=mock_config_manager)

        # Track stream IDs used
        stream_ids_used = []

        def mock_query_executor_factory(stream_id):
            stream_ids_used.append(stream_id)
            mock_executor = MagicMock()
            # Mock execution result
            return mock_executor

        # Mock _execute_stream to return success
        executor._execute_stream = MagicMock(
            return_value={
                "queries_executed": 22,
                "queries_successful": 22,
                "queries_failed": 0,
            }
        )

        # Execute concurrent queries
        executor.execute_concurrent_queries(mock_query_executor_factory, num_streams=3)

        # Verify different stream IDs were assigned
        assert len(stream_ids_used) == 3  # 3 concurrent streams
        assert stream_ids_used == [0, 1, 2]  # Different stream ID for each stream
