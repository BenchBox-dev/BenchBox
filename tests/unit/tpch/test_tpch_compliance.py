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

    def test_tpch_throughput_stream_permutations_keep_stream_zero_validation_context(self):
        """Streams vary query order while validation stays on the canonical context."""
        from benchbox.core.tpch.streams import TPCHStreams
        from benchbox.core.tpch.throughput_test import TPCHThroughputTest

        # Mock benchmark
        mock_benchmark = MagicMock()
        mock_benchmark.get_query.return_value = "SELECT 1"
        mock_connection = MagicMock()
        mock_connection_factory = MagicMock(return_value=mock_connection)

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
        assert len(mock_connection.set_query_context.call_args_list) == 44
        assert all(not call.kwargs for call in mock_connection.set_query_context.call_args_list)
        assert all(len(call.args) == 1 for call in mock_connection.set_query_context.call_args_list)


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
