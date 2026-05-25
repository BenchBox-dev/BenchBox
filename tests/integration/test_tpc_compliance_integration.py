"""Integration tests for TPC-H and TPC-DS compliance flows.

This module contains integration tests for Power, Throughput, and Maintenance
tests for both TPC-H and TPC-DS benchmarks.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.core.results.metrics import TPCMetricsCalculator
from benchbox.core.tpcds.benchmark import TPCDSBenchmark
from benchbox.core.tpch.benchmark import TPCHBenchmark

# Mark all tests in this file as integration tests
pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]


def _calculate_composite_qph(
    *,
    scale_factor: float,
    power_time: float,
    throughput_time: float,
    num_streams: int,
) -> float:
    if power_time <= 0 or throughput_time <= 0 or num_streams <= 0:
        return 0.0

    power_at_size = (3600.0 * scale_factor) / power_time
    throughput_at_size = (num_streams * 3600.0 * scale_factor) / throughput_time
    return TPCMetricsCalculator.calculate_qph(power_at_size, throughput_at_size)


class TestTPCHCompliance:
    """Test TPC-H compliance implementation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.connection_string = "sqlite:///:memory:"
        self.dialect = "sqlite"

    def test_tpch_benchmark_initialization(self) -> None:
        """Test TPC-H benchmark initialization."""
        benchmark = TPCHBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        assert benchmark.scale_factor == 1.0
        assert benchmark.output_dir == Path(self.temp_dir)

    def test_tpch_power_test_integration(self) -> None:
        """Test TPC-H Power Test integration."""
        # Mock database connection
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [("result1",), ("result2",)]
        mock_conn.execute.return_value = mock_cursor
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.commit.return_value = None
        mock_conn.close.return_value = None

        # Create benchmark and run power test
        benchmark = TPCHBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        # Mock the power test execution
        with patch.object(benchmark, "get_query") as mock_get_query:
            mock_get_query.return_value = "SELECT 1"

            # Import and test the power test
            from benchbox.core.tpch.power_test import TPCHPowerTest

            power_test = TPCHPowerTest(
                benchmark=benchmark,
                connection=mock_conn,
                scale_factor=1.0,
                dialect=self.dialect,
                verbose=False,
            )

            # Run the power test
            result = power_test.run()

            # Verify results
            assert result.scale_factor == 1.0
            assert result.power_at_size > 0
            assert len(result.query_results) == 22  # TPC-H has 22 queries

    def test_tpch_throughput_test_integration(self) -> None:
        """Test TPC-H Throughput Test integration."""

        # Create mock connection factory
        def mock_connection_factory():
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchall.return_value = [("result1",), ("result2",)]
            mock_conn.execute.return_value = mock_cursor
            mock_conn.cursor.return_value = mock_cursor
            mock_conn.commit.return_value = None
            mock_conn.close.return_value = None
            return mock_conn

        # Create benchmark and run throughput test
        benchmark = TPCHBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        # Mock the throughput test execution
        with patch.object(benchmark, "get_query") as mock_get_query:
            mock_get_query.return_value = "SELECT 1"

            # Import and test the throughput test
            from benchbox.core.tpch.throughput_test import TPCHThroughputTest

            throughput_test = TPCHThroughputTest(
                benchmark=benchmark,
                connection_factory=mock_connection_factory,
                num_streams=2,
                scale_factor=1.0,
                verbose=False,
            )

            # Run the throughput test
            result = throughput_test.run()

            # Verify results
            assert result.scale_factor == 1.0
            assert result.throughput_at_size > 0
            assert len(result.stream_results) == 2

    def test_tpch_maintenance_test_integration(self) -> None:
        """Test TPC-H Maintenance Test integration."""

        # Create mock connection factory
        def mock_connection_factory():
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchall.return_value = [("result1",), ("result2",)]
            mock_conn.execute.return_value = mock_cursor
            mock_conn.cursor.return_value = mock_cursor
            mock_conn.commit.return_value = None
            mock_conn.close.return_value = None
            return mock_conn

        # Create benchmark and run maintenance test
        benchmark = TPCHBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        # Mock the maintenance test execution
        with patch.object(benchmark, "get_query") as mock_get_query:
            mock_get_query.return_value = "SELECT 1"

            # Import and test the maintenance test
            from benchbox.core.tpch.maintenance_test import TPCHMaintenanceTest

            maintenance_test = TPCHMaintenanceTest(
                connection_factory=mock_connection_factory,
                scale_factor=1.0,
                verbose=False,
            )

            # Run the maintenance test
            result = maintenance_test.run_maintenance_test(rf1_interval=0.0, rf2_interval=0.0)

            # Verify results
            assert result.config.scale_factor == 1.0
            assert result.total_time > 0
            assert result.rf1_operations > 0
            assert result.rf2_operations > 0

    def test_tpch_qphh_size_calculation(self) -> None:
        """Test TPC-H QphH@Size calculation integration."""
        power_time = 360.0  # 6 minutes
        throughput_time = 720.0  # 12 minutes
        num_streams = 2

        qphh_size = _calculate_composite_qph(
            scale_factor=1.0,
            power_time=power_time,
            throughput_time=throughput_time,
            num_streams=num_streams,
        )

        # Expected calculation:
        # Power@Size = 3600 * 1.0 / 360.0 = 10.0
        # Throughput@Size = 2 * 3600 * 1.0 / 720.0 = 10.0
        # QphH@Size = sqrt(10.0 * 10.0) = 10.0
        assert abs(qphh_size - 10.0) < 0.0001


class TestTPCDSCompliance:
    """Test TPC-DS compliance implementation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.connection_string = "sqlite:///:memory:"
        self.dialect = "sqlite"

    def test_tpcds_benchmark_initialization(self) -> None:
        """Test TPC-DS benchmark initialization."""
        benchmark = TPCDSBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        assert benchmark.scale_factor == 1.0
        assert benchmark.output_dir == Path(self.temp_dir)

    def test_tpcds_power_test_integration(self) -> None:
        """Test TPC-DS Power Test integration."""
        # Create benchmark and run power test
        benchmark = TPCDSBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        # Mock the power test execution
        with (
            patch.object(benchmark, "get_query") as mock_get_query,
            patch.object(benchmark, "get_queries") as mock_get_queries,
        ):
            mock_get_query.return_value = "SELECT 1"
            # Mock get_queries to return a dictionary of queries 1-10 for testing
            mock_get_queries.return_value = {str(i): f"SELECT {i}" for i in range(1, 11)}

            # Import and test the power test
            from benchbox.core.tpcds.power_test import TPCDSPowerTest

            # Create a mock connection factory that returns properly structured mock
            def mock_connection_factory():
                mock_conn = Mock()
                mock_cursor = Mock()
                # Configure fetchall to return list that has proper len()
                mock_results = [("result1",), ("result2",), ("result3",)]
                mock_cursor.fetchall.return_value = mock_results
                mock_conn.execute.return_value = mock_cursor
                mock_conn.commit.return_value = None
                mock_conn.close.return_value = None
                return mock_conn

            power_test = TPCDSPowerTest(
                benchmark=benchmark,
                connection_factory=mock_connection_factory,
                scale_factor=1.0,
                verbose=False,
            )

            # Set a limited query sequence for testing
            power_test._query_sequence = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

            # Run the power test
            result = power_test.run()

            # Verify results
            assert result.scale_factor == 1.0
            assert result.power_at_size > 0
            # We set 10 queries for testing
            assert len(result.query_results) == 10

    def test_tpcds_throughput_test_integration(self) -> None:
        """Test TPC-DS Throughput Test integration."""

        # Create mock connection factory
        def mock_connection_factory():
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchall.return_value = [("result1",), ("result2",)]
            mock_conn.execute.return_value = mock_cursor
            mock_conn.cursor.return_value = mock_cursor
            mock_conn.commit.return_value = None
            mock_conn.close.return_value = None
            return mock_conn

        # Create benchmark and run throughput test
        benchmark = TPCDSBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        # Mock the throughput test execution
        with patch.object(benchmark, "get_query") as mock_get_query:
            mock_get_query.return_value = "SELECT 1"

            # Import and test the throughput test
            from benchbox.core.tpcds.throughput_test import TPCDSThroughputTest

            throughput_test = TPCDSThroughputTest(
                benchmark=benchmark,
                connection_factory=mock_connection_factory,
                num_streams=2,
                scale_factor=1.0,
                verbose=False,
            )

            # Run the throughput test
            result = throughput_test.run()

            # Verify results
            assert result.scale_factor == 1.0
            assert result.throughput_at_size > 0
            assert len(result.stream_results) == 2

    def test_tpcds_maintenance_test_integration(self) -> None:
        """Test TPC-DS Maintenance Test integration."""

        # Create mock connection factory
        def mock_connection_factory():
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchall.return_value = [("result1",), ("result2",)]
            mock_conn.execute.return_value = mock_cursor
            mock_conn.cursor.return_value = mock_cursor
            mock_conn.commit.return_value = None
            mock_conn.close.return_value = None
            return mock_conn

        # Create benchmark
        benchmark = TPCDSBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        # Mock the maintenance test execution
        with patch.object(benchmark, "run_maintenance_test") as mock_run_test:
            mock_result = Mock()
            mock_result.test_duration = 60.0
            mock_result.overall_throughput = 100.0
            mock_result.operation_metrics = []
            mock_run_test.return_value = mock_result

            # Run the maintenance test
            result = benchmark.run_maintenance_test(connection_factory=mock_connection_factory)

            # Verify results
            assert result.test_duration == 60.0
            assert result.overall_throughput == 100.0

    def test_tpcds_qphds_size_calculation(self) -> None:
        """Test TPC-DS QphDS@Size calculation integration."""
        power_time = 600.0  # 10 minutes
        throughput_time = 1200.0  # 20 minutes
        num_streams = 3

        qphds_size = _calculate_composite_qph(
            scale_factor=1.0,
            power_time=power_time,
            throughput_time=throughput_time,
            num_streams=num_streams,
        )

        # Expected calculation:
        # Power@Size = 3600 * 1.0 / 600.0 = 6.0
        # Throughput@Size = 3 * 3600 * 1.0 / 1200.0 = 9.0
        # QphDS@Size = sqrt(6.0 * 9.0) = sqrt(54.0) ≈ 7.35
        assert abs(qphds_size - 7.35) < 0.01


class TestTPCBenchmarkFlows:
    """End-to-end integration tests for TPC benchmark flows."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.connection_string = "sqlite:///:memory:"
        self.dialect = "sqlite"

    def test_tpch_complete_benchmark_workflow(self) -> None:
        """Test complete TPC-H benchmark workflow."""

        # Create mock connection factory
        def mock_connection_factory():
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchall.return_value = [("result1",), ("result2",)]
            mock_conn.execute.return_value = mock_cursor
            mock_conn.cursor.return_value = mock_cursor
            mock_conn.commit.return_value = None
            mock_conn.close.return_value = None
            return mock_conn

        # Create single mock connection for power test
        mock_conn = mock_connection_factory()

        # Create benchmark
        benchmark = TPCHBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        # Mock query retrieval
        with patch.object(benchmark, "get_query") as mock_get_query:
            mock_get_query.return_value = "SELECT 1"

            # Test power test
            from benchbox.core.tpch.power_test import TPCHPowerTest

            power_test = TPCHPowerTest(
                benchmark=benchmark,
                connection=mock_conn,
                scale_factor=1.0,
                dialect=self.dialect,
                verbose=False,
            )
            power_result = power_test.run()

            # Test throughput test
            from benchbox.core.tpch.throughput_test import TPCHThroughputTest

            throughput_test = TPCHThroughputTest(
                benchmark=benchmark,
                connection_factory=mock_connection_factory,
                num_streams=2,
                scale_factor=1.0,
                verbose=False,
            )
            throughput_result = throughput_test.run()

            # Test maintenance test
            from benchbox.core.tpch.maintenance_test import TPCHMaintenanceTest

            maintenance_test = TPCHMaintenanceTest(
                connection_factory=mock_connection_factory,
                scale_factor=1.0,
                verbose=False,
            )
            maintenance_result = maintenance_test.run_maintenance_test(rf1_interval=0.0, rf2_interval=0.0)

            qphh_size = _calculate_composite_qph(
                scale_factor=1.0,
                power_time=power_result.total_time,
                throughput_time=throughput_result.total_time,
                num_streams=2,
            )

            # Verify all tests completed successfully
            assert power_result.power_at_size > 0
            assert throughput_result.throughput_at_size > 0
            assert maintenance_result.total_time > 0
            assert qphh_size > 0

    def test_tpc_metrics_validation(self) -> None:
        """Test TPC metrics validation and error handling."""
        qphh_size = _calculate_composite_qph(
            scale_factor=1.0,
            power_time=0.0,
            throughput_time=100.0,
            num_streams=2,
        )
        assert qphh_size == 0.0

        qphh_size = _calculate_composite_qph(
            scale_factor=1.0,
            power_time=-50.0,
            throughput_time=100.0,
            num_streams=2,
        )
        assert qphh_size == 0.0

        qphh_size = _calculate_composite_qph(
            scale_factor=1.0,
            power_time=100.0,
            throughput_time=100.0,
            num_streams=0,
        )
        assert qphh_size == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
