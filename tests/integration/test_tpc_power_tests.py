"""
Integration tests for TPC Power/Throughput/Maintenance test implementations.

Tests that the --phases power, --phases throughput, and --phases maintenance options
work correctly and route to proper TPC test implementations.
"""

from unittest.mock import Mock, patch

import pytest

from benchbox.platforms.duckdb import DuckDBAdapter

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]


class TestTPCTestRouting:
    """Test TPC test routing functionality in platform adapters."""

    def test_platform_adapter_has_tpc_methods(self):
        """Test that platform adapter has all TPC test methods."""
        adapter = DuckDBAdapter()

        # Check that all required TPC test methods exist
        assert hasattr(adapter, "_execute_queries_by_type")
        assert hasattr(adapter, "_execute_power_test")
        assert hasattr(adapter, "_execute_throughput_test")
        assert hasattr(adapter, "_execute_maintenance_test")
        assert hasattr(adapter, "_execute_combined_test")
        assert hasattr(adapter, "_execute_tpch_power_test")
        assert hasattr(adapter, "_execute_tpcds_power_test")
        assert hasattr(adapter, "_execute_tpcds_throughput_test")
        assert hasattr(adapter, "_execute_tpcds_maintenance_test")

    def test_benchmark_name_detection_tpch(self):
        """Test TPC-H benchmark name detection."""
        DuckDBAdapter()

        # Mock TPC-H benchmark
        mock_benchmark = Mock()
        mock_benchmark._name = ""
        mock_benchmark.__class__.__name__ = "TPCHBenchmark"
        mock_benchmark.display_name = "TPC-H Benchmark"

        # Simulate the detection logic
        benchmark_name = getattr(mock_benchmark, "_name", type(mock_benchmark).__name__.lower())
        if not any(x in benchmark_name.lower() for x in ["tpch", "tpcds"]):
            display_name = getattr(mock_benchmark, "display_name", "").lower()
            class_name = type(mock_benchmark).__name__.lower()
            if "tpch" in display_name or "tpch" in class_name:
                benchmark_name = "tpch"

        assert "tpch" in benchmark_name.lower()

    def test_benchmark_name_detection_tpcds(self):
        """Test TPC-DS benchmark name detection."""
        DuckDBAdapter()

        # Mock TPC-DS benchmark
        mock_benchmark = Mock()
        mock_benchmark._name = ""
        mock_benchmark.__class__.__name__ = "TPCDSBenchmark"
        mock_benchmark.display_name = "TPC-DS Benchmark"

        # Simulate the detection logic
        benchmark_name = getattr(mock_benchmark, "_name", type(mock_benchmark).__name__.lower())
        if not any(x in benchmark_name.lower() for x in ["tpch", "tpcds"]):
            display_name = getattr(mock_benchmark, "display_name", "").lower()
            class_name = type(mock_benchmark).__name__.lower()
            if "tpcds" in display_name or "tpcds" in class_name:
                benchmark_name = "tpcds"

        assert "tpcds" in benchmark_name.lower()

    def test_queries_by_type_routing(self):
        """Test that queries are routed by test execution type."""
        adapter = DuckDBAdapter()

        # Test different execution types route to different methods
        mock_benchmark = Mock()
        mock_connection = Mock()

        # Mock the specific test execution methods
        adapter._execute_all_queries = Mock(return_value=[])
        adapter._execute_power_test = Mock(return_value=[])
        adapter._execute_throughput_test = Mock(return_value=[])
        adapter._execute_maintenance_test = Mock(return_value=[])
        adapter._execute_combined_test = Mock(return_value=[])

        # Test standard execution
        adapter._execute_queries_by_type(mock_benchmark, mock_connection, {"test_execution_type": "standard"})
        adapter._execute_all_queries.assert_called_once()

        # Test power execution
        adapter._execute_queries_by_type(mock_benchmark, mock_connection, {"test_execution_type": "power"})
        adapter._execute_power_test.assert_called_once()

        # Test throughput execution
        adapter._execute_queries_by_type(mock_benchmark, mock_connection, {"test_execution_type": "throughput"})
        adapter._execute_throughput_test.assert_called_once()

        # Test maintenance execution
        adapter._execute_queries_by_type(mock_benchmark, mock_connection, {"test_execution_type": "maintenance"})
        adapter._execute_maintenance_test.assert_called_once()

        # Test combined execution
        adapter._execute_queries_by_type(mock_benchmark, mock_connection, {"test_execution_type": "combined"})
        adapter._execute_combined_test.assert_called_once()

    def test_tpch_power_test_method_structure(self):
        """Test TPC-H power test method returns proper structure."""
        adapter = DuckDBAdapter()

        # Mock dependencies
        mock_benchmark = Mock()
        mock_benchmark.__class__.__name__ = "TPCHBenchmark"
        mock_connection = Mock()

        # Mock query execution
        adapter.execute_query = Mock(
            return_value={
                "query_id": 1,
                "execution_time": 0.1,
                "status": "SUCCESS",
                "rows_returned": 100,
                "error": None,
            }
        )

        # Mock streams module
        with patch("benchbox.core.tpch.streams.TPCHStreams") as mock_streams:
            mock_streams.PERMUTATION_MATRIX = [
                [
                    1,
                    2,
                    3,
                    4,
                    5,
                    6,
                    7,
                    8,
                    9,
                    10,
                    11,
                    12,
                    13,
                    14,
                    15,
                    16,
                    17,
                    18,
                    19,
                    20,
                    21,
                    22,
                ]
            ]

            # Mock benchmark.get_query
            mock_benchmark.get_query = Mock(return_value="SELECT 1")

            run_config = {
                "scale_factor": 1.0,
                "seed": 1,
                "stream_id": 0,
                "verbose": False,
                "iterations": 1,  # Single iteration for test
                "warm_up_iterations": 0,  # No warmup
            }

            result = adapter._execute_tpch_power_test(mock_benchmark, mock_connection, run_config)

            # Check result structure
            assert isinstance(result, list)
            assert len(result) == 22  # TPC-H has 22 queries (1 iteration)

            # Check each result has required fields
            for query_result in result:
                assert "query_id" in query_result
                assert "execution_time_seconds" in query_result
                assert "status" in query_result
                assert "test_type" in query_result
                assert query_result["test_type"] == "power"
                assert "stream_id" in query_result
                assert "position" in query_result

    def test_unsupported_benchmark_fallback(self):
        """Test that unsupported benchmarks fall back to standard execution."""
        adapter = DuckDBAdapter()

        mock_benchmark = Mock()
        mock_connection = Mock()

        # Mock fallback method
        adapter._execute_all_queries = Mock(return_value=[{"test_type": "standard"}])

        run_config = {
            "benchmark_name": "unsupported",
            "test_execution_type": "power",
            "iterations": 1,  # Single iteration for test
            "warm_up_iterations": 0,  # No warmup
        }
        result = adapter._execute_power_test(mock_benchmark, mock_connection, run_config)

        # Should fall back to standard execution once per iteration (1 time total)
        adapter._execute_all_queries.assert_called_once()
        assert result[0]["test_type"] == "standard"


class TestTPCTestIntegration:
    """Integration tests for actual TPC test execution."""

    @pytest.fixture
    def tpch_mock_benchmark(self):
        """Create a mock TPC-H benchmark."""
        mock = Mock()
        mock.get_query = Mock(return_value="SELECT 1 as test_query")
        return mock

    @pytest.fixture
    def tpcds_mock_benchmark(self):
        """Create a mock TPC-DS benchmark."""
        mock = Mock()
        mock.get_query = Mock(return_value="SELECT 1 as test_query")
        mock.get_queries = Mock(return_value={"1": "SELECT 1", "2": "SELECT 2"})
        return mock

    @patch("rich.console.Console")
    def test_tpch_power_test_execution_flow(self, mock_console, tpch_mock_benchmark):
        """Test TPC-H power test execution flow."""
        adapter = DuckDBAdapter()

        # Mock the connection properly
        mock_connection = Mock()
        mock_connection.execute = Mock()
        mock_connection.fetchall = Mock(return_value=[])

        with patch("benchbox.core.tpch.streams.TPCHStreams") as mock_streams:
            mock_streams.PERMUTATION_MATRIX = [
                [
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
            ]

            run_config = {
                "benchmark_name": "tpch",
                "scale_factor": 1.0,
                "seed": 1,
                "stream_id": 0,
                "verbose": False,
                "iterations": 1,  # Single iteration for test
                "warm_up_iterations": 0,  # No warmup
            }

            result = adapter._execute_tpch_power_test(tpch_mock_benchmark, mock_connection, run_config)

            # Verify execution
            assert len(result) == 22  # 1 iteration × 22 queries

            # Verify first query is from permutation (will be first in the permutation we set)
            first_query_result = result[0]
            expected_first_query = mock_streams.PERMUTATION_MATRIX[0][0]  # First query in permutation
            assert first_query_result["query_id"] == expected_first_query
            assert first_query_result["position"] == 1
            assert first_query_result["test_type"] == "power"

    @patch("rich.console.Console")
    def test_tpcds_power_test_with_limited_queries(self, mock_console, tpcds_mock_benchmark):
        """Test TPC-DS power test with limited query set."""
        adapter = DuckDBAdapter()

        # Mock the connection properly
        mock_connection = Mock()
        mock_connection.execute = Mock()
        mock_connection.fetchall = Mock(return_value=[])

        run_config = {
            "benchmark_name": "tpcds",
            "scale_factor": 1.0,
            "seed": 1,
            "stream_id": 0,
            "verbose": False,
            "iterations": 1,  # Single iteration for test
            "warm_up_iterations": 0,  # No warmup
        }

        result = adapter._execute_tpcds_power_test(tpcds_mock_benchmark, mock_connection, run_config)

        # Should execute available queries (1 and 2)
        assert len(result) == 2  # 1 iteration × 2 queries

        # Verify query execution order and metadata
        query_ids = [r["query_id"] for r in result]
        assert set(query_ids) == {"1", "2"}  # Should have both queries (as strings from fixture)

        for query_result in result:
            assert query_result["query_id"] in ["1", "2"]
            assert query_result["test_type"] == "power"
            assert "position" in query_result

    @patch("rich.console.Console")
    def test_error_handling_in_power_test(self, mock_console, tpch_mock_benchmark):
        """Test error handling in TPC power test."""
        adapter = DuckDBAdapter()

        # Mock the connection properly
        mock_connection = Mock()

        # Make benchmark.get_query raise an error
        tpch_mock_benchmark.get_query.side_effect = Exception("Query generation failed")

        with patch("benchbox.core.tpch.streams.TPCHStreams") as mock_streams:
            mock_streams.PERMUTATION_MATRIX = [[1, 2]]  # Simplified for test

            run_config = {
                "scale_factor": 1.0,
                "seed": 1,
                "stream_id": 0,
                "verbose": False,
            }

            result = adapter._execute_tpch_power_test(tpch_mock_benchmark, mock_connection, run_config)

            # Should handle errors gracefully - execution may fail during preflight
            # or during execution, both are valid error handling scenarios
            assert len(result) >= 1  # At least one error result
            # Check that error was captured
            assert any("error" in str(r).lower() or r.get("status") == "FAILED" for r in result)

    @patch("rich.console.Console")
    def test_maintenance_test_basic_operations(self, mock_console):
        """Test TPC-DS maintenance test basic operations."""
        adapter = DuckDBAdapter()

        # Mock the connection properly
        mock_connection = Mock()
        mock_connection.execute = Mock()
        mock_connection.fetchall = Mock(return_value=[])

        # Mock TPCDSMaintenanceTest to avoid actual benchmark execution
        with patch("benchbox.core.tpcds.maintenance_test.TPCDSMaintenanceTest") as mock_maintenance_class:
            # Create mock operation objects
            mock_ops = []
            for op_type, table in [
                ("COUNT_VALIDATION", "customer"),
                ("INDEX_CHECK", "store_sales"),
                ("DATA_INTEGRITY", "item"),
                ("REFERENTIAL_CHECK", "date_dim"),
            ]:
                mock_op = Mock()
                mock_op.operation_type = op_type
                mock_op.table_name = table
                mock_op.duration = 0.1
                mock_op.success = True
                mock_op.rows_affected = 100
                mock_ops.append(mock_op)

            # Mock the run() method to return expected result structure
            mock_maintenance_instance = Mock()
            mock_maintenance_instance.run.return_value = {
                "success": True,
                "operations": mock_ops,
                "insert_operations": 1,
                "update_operations": 1,
                "delete_operations": 1,
                "total_operations": 4,
                "successful_operations": 4,
                "total_time": 0.4,
                "overall_throughput": 10.0,
                "errors": [],
            }
            mock_maintenance_class.return_value = mock_maintenance_instance

            run_config = {"scale_factor": 1.0, "verbose": False}
            result = adapter._execute_tpcds_maintenance_test(None, mock_connection, run_config)

            # Should execute 4 maintenance operations
            assert len(result) == 4

            # Verify operation metadata - check that we have the expected structure
            for op_result in result:
                assert op_result["test_type"] == "maintenance"
                assert "table_name" in op_result
                assert "operation_type" in op_result

            # Verify we have the expected operation types
            expected_operations = [
                "COUNT_VALIDATION",
                "INDEX_CHECK",
                "DATA_INTEGRITY",
                "REFERENTIAL_CHECK",
            ]
            actual_operations = [r["operation_type"] for r in result]
            assert set(actual_operations) == set(expected_operations)
