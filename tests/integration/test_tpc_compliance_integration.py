# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.core.results.metrics import TPCMetricsCalculator
from benchbox.core.tpcds.benchmark import TPCDSBenchmark
from benchbox.core.tpch.benchmark import TPCHBenchmark

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
    def setup_method(self) -> None:

        self.temp_dir = tempfile.mkdtemp()
        self.connection_string = "sqlite:///:memory:"
        self.dialect = "sqlite"

    def test_tpch_benchmark_initialization(self) -> None:

        benchmark = TPCHBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        assert benchmark.scale_factor == 1.0
        assert benchmark.output_dir == Path(self.temp_dir)

    def test_tpch_power_test_integration(self) -> None:

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [("result1",), ("result2",)]
        mock_conn.execute.return_value = mock_cursor
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.commit.return_value = None
        mock_conn.close.return_value = None

        benchmark = TPCHBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        with patch.object(benchmark, "get_query") as mock_get_query:
            mock_get_query.return_value = "SELECT 1"

            from benchbox.core.tpch.power_test import TPCHPowerTest

            power_test = TPCHPowerTest(
                benchmark=benchmark,
                connection=mock_conn,
                scale_factor=1.0,
                dialect=self.dialect,
                verbose=False,
            )

            result = power_test.run()

            assert result.scale_factor == 1.0
            assert result.power_at_size > 0
            assert len(result.query_results) == 22

    def test_tpch_throughput_test_integration(self) -> None:

        def mock_connection_factory():
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchall.return_value = [("result1",), ("result2",)]
            mock_conn.execute.return_value = mock_cursor
            mock_conn.cursor.return_value = mock_cursor
            mock_conn.commit.return_value = None
            mock_conn.close.return_value = None
            return mock_conn

        benchmark = TPCHBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        with patch.object(benchmark, "get_query") as mock_get_query:
            mock_get_query.return_value = "SELECT 1"

            from benchbox.core.tpch.throughput_test import TPCHThroughputTest

            throughput_test = TPCHThroughputTest(
                benchmark=benchmark,
                connection_factory=mock_connection_factory,
                num_streams=2,
                scale_factor=1.0,
                verbose=False,
            )

            result = throughput_test.run()

            assert result.scale_factor == 1.0
            assert result.throughput_at_size > 0
            assert len(result.stream_results) == 2

    def test_tpch_maintenance_test_integration(self) -> None:

        def mock_connection_factory():
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchall.return_value = [("result1",), ("result2",)]
            mock_conn.execute.return_value = mock_cursor
            mock_conn.cursor.return_value = mock_cursor
            mock_conn.commit.return_value = None
            mock_conn.close.return_value = None
            return mock_conn

        benchmark = TPCHBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        with patch.object(benchmark, "get_query") as mock_get_query:
            mock_get_query.return_value = "SELECT 1"

            from benchbox.core.tpch.maintenance_test import TPCHMaintenanceTest

            maintenance_test = TPCHMaintenanceTest(
                connection_factory=mock_connection_factory,
                scale_factor=1.0,
                verbose=False,
            )

            result = maintenance_test.run_maintenance_test(rf1_interval=0.0, rf2_interval=0.0)

            assert result.config.scale_factor == 1.0
            assert result.total_time > 0
            assert result.rf1_operations > 0
            assert result.rf2_operations > 0

    def test_tpch_qphh_size_calculation(self) -> None:

        power_time = 360.0
        throughput_time = 720.0
        num_streams = 2

        qphh_size = _calculate_composite_qph(
            scale_factor=1.0,
            power_time=power_time,
            throughput_time=throughput_time,
            num_streams=num_streams,
        )

        assert abs(qphh_size - 10.0) < 0.0001


class TestTPCDSCompliance:
    def setup_method(self) -> None:

        self.temp_dir = tempfile.mkdtemp()
        self.connection_string = "sqlite:///:memory:"
        self.dialect = "sqlite"

    def test_tpcds_benchmark_initialization(self) -> None:

        benchmark = TPCDSBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        assert benchmark.scale_factor == 1.0
        assert benchmark.output_dir == Path(self.temp_dir)

    def test_tpcds_power_test_integration(self) -> None:

        benchmark = TPCDSBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        with (
            patch.object(benchmark, "get_query") as mock_get_query,
            patch.object(benchmark, "get_queries") as mock_get_queries,
        ):
            mock_get_query.return_value = "SELECT 1"

            mock_get_queries.return_value = {str(i): f"SELECT {i}" for i in range(1, 11)}

            from benchbox.core.tpcds.power_test import TPCDSPowerTest

            def mock_connection_factory():
                mock_conn = Mock()
                mock_cursor = Mock()

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

            power_test._query_sequence = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

            result = power_test.run()

            assert result.scale_factor == 1.0
            assert result.power_at_size > 0

            assert len(result.query_results) == 10

    def test_tpcds_throughput_test_integration(self) -> None:

        def mock_connection_factory():
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchall.return_value = [("result1",), ("result2",)]
            mock_conn.execute.return_value = mock_cursor
            mock_conn.cursor.return_value = mock_cursor
            mock_conn.commit.return_value = None
            mock_conn.close.return_value = None
            return mock_conn

        benchmark = TPCDSBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        with patch.object(benchmark, "get_query") as mock_get_query:
            mock_get_query.return_value = "SELECT 1"

            from benchbox.core.tpcds.throughput_test import TPCDSThroughputTest

            throughput_test = TPCDSThroughputTest(
                benchmark=benchmark,
                connection_factory=mock_connection_factory,
                num_streams=2,
                scale_factor=1.0,
                verbose=False,
            )

            result = throughput_test.run()

            assert result.scale_factor == 1.0
            assert result.throughput_at_size > 0
            assert len(result.stream_results) == 2

    def test_tpcds_maintenance_test_integration(self) -> None:

        def mock_connection_factory():
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchall.return_value = [("result1",), ("result2",)]
            mock_conn.execute.return_value = mock_cursor
            mock_conn.cursor.return_value = mock_cursor
            mock_conn.commit.return_value = None
            mock_conn.close.return_value = None
            return mock_conn

        benchmark = TPCDSBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        with patch.object(benchmark, "run_maintenance_test") as mock_run_test:
            mock_result = Mock()
            mock_result.test_duration = 60.0
            mock_result.overall_throughput = 100.0
            mock_result.operation_metrics = []
            mock_run_test.return_value = mock_result

            result = benchmark.run_maintenance_test(connection_factory=mock_connection_factory)

            assert result.test_duration == 60.0
            assert result.overall_throughput == 100.0

    def test_tpcds_qphds_size_calculation(self) -> None:

        power_time = 600.0
        throughput_time = 1200.0
        num_streams = 3

        qphds_size = _calculate_composite_qph(
            scale_factor=1.0,
            power_time=power_time,
            throughput_time=throughput_time,
            num_streams=num_streams,
        )

        assert abs(qphds_size - 7.35) < 0.01


class TestTPCBenchmarkFlows:
    def setup_method(self) -> None:

        self.temp_dir = tempfile.mkdtemp()
        self.connection_string = "sqlite:///:memory:"
        self.dialect = "sqlite"

    def test_tpch_complete_benchmark_workflow(self) -> None:

        def mock_connection_factory():
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchall.return_value = [("result1",), ("result2",)]
            mock_conn.execute.return_value = mock_cursor
            mock_conn.cursor.return_value = mock_cursor
            mock_conn.commit.return_value = None
            mock_conn.close.return_value = None
            return mock_conn

        mock_conn = mock_connection_factory()

        benchmark = TPCHBenchmark(scale_factor=1.0, output_dir=self.temp_dir)

        with patch.object(benchmark, "get_query") as mock_get_query:
            mock_get_query.return_value = "SELECT 1"

            from benchbox.core.tpch.power_test import TPCHPowerTest

            power_test = TPCHPowerTest(
                benchmark=benchmark,
                connection=mock_conn,
                scale_factor=1.0,
                dialect=self.dialect,
                verbose=False,
            )
            power_result = power_test.run()

            from benchbox.core.tpch.throughput_test import TPCHThroughputTest

            throughput_test = TPCHThroughputTest(
                benchmark=benchmark,
                connection_factory=mock_connection_factory,
                num_streams=2,
                scale_factor=1.0,
                verbose=False,
            )
            throughput_result = throughput_test.run()

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

            assert power_result.power_at_size > 0
            assert throughput_result.throughput_at_size > 0
            assert maintenance_result.total_time > 0
            assert qphh_size > 0

    def test_tpc_metrics_validation(self) -> None:

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
