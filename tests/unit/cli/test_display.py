from tests.fixtures.result_dict_fixtures import make_benchmark_results

"""Tests for CLI display functionality.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from datetime import datetime
from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console

from benchbox.cli.display import StandardDisplays
from benchbox.core.schemas import BenchmarkConfig, DatabaseConfig, QueryResult, SystemProfile

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestStandardDisplays:
    """Test StandardDisplays functionality."""

    def test_standard_displays_creation(self):
        """Test creating StandardDisplays with console."""
        console = Console(file=StringIO(), force_terminal=False)
        displays = StandardDisplays(console)

        assert displays.console == console

    def test_show_banner(self):
        """Test showing banner."""
        output = StringIO()
        console = Console(file=output, force_terminal=False)
        displays = StandardDisplays(console)

        displays.show_banner("BenchBox", "1.0.0")

        output_text = output.getvalue()
        assert "BenchBox" in output_text
        assert "1.0.0" in output_text
        assert "Benchmark Suite" in output_text

    def test_show_banner_with_description(self):
        """Test showing banner with custom description."""
        output = StringIO()
        console = Console(file=output, force_terminal=False)
        displays = StandardDisplays(console)

        displays.show_banner("TestApp", "2.0.0", "Custom Description")

        output_text = output.getvalue()
        assert "TestApp" in output_text
        assert "2.0.0" in output_text
        assert "Custom Description" in output_text

    def test_show_system_profile(self):
        """Test showing system profile."""
        output = StringIO()
        console = Console(file=output, force_terminal=False)
        displays = StandardDisplays(console)

        profile = SystemProfile(
            os_name="Linux",
            os_version="5.4.0",
            architecture="x86_64",
            cpu_model="Intel Core i7",
            cpu_cores_physical=4,
            cpu_cores_logical=8,
            memory_total_gb=16.0,
            memory_available_gb=12.0,
            python_version="3.11.0",
            disk_space_gb=500.0,
            timestamp=datetime.now(),
            hostname="test-machine",
        )

        displays.show_system_profile(profile, detailed=True)

        output_text = output.getvalue()
        assert "System Information" in output_text
        assert "Linux" in output_text
        assert "Intel Core i7" in output_text
        assert "16.0 GB" in output_text
        assert "test-machine" in output_text
        assert "4 physical" in output_text
        assert "8 logical" in output_text

    def test_show_benchmark_config(self):
        """Test showing benchmark configuration."""
        output = StringIO()
        console = Console(file=output, force_terminal=False)
        displays = StandardDisplays(console)

        benchmark_config = BenchmarkConfig(
            name="tpch",
            display_name="TPC-H Benchmark",
            scale_factor=1.0,
            concurrency=2,
            compress_data=True,
            compression_type="zstd",
            compression_level=3,
            test_execution_type="power",
            options={"custom_option": "value"},
        )

        database_config = DatabaseConfig(
            type="duckdb",
            name="benchmark.db",
            connection_string="duckdb://benchmark.db",
            options={"threads": 4, "memory": "2GB"},
        )

        displays.show_benchmark_config(benchmark_config, database_config)

        output_text = output.getvalue()
        assert "Benchmark Configuration" in output_text
        assert "TPC-H Benchmark" in output_text
        assert "Scale Factor" in output_text
        assert "1.0" in output_text
        assert "power" in output_text
        assert "DuckDB" in output_text
        assert "benchmark.db" in output_text
        assert "zstd" in output_text
        assert "level 3" in output_text

    def test_show_benchmark_config_minimal(self):
        """Test showing minimal benchmark configuration."""
        output = StringIO()
        console = Console(file=output, force_terminal=False)
        displays = StandardDisplays(console)

        benchmark_config = BenchmarkConfig(name="ssb", display_name="Star Schema Benchmark")

        database_config = DatabaseConfig(type="sqlite3", name="test.db")

        displays.show_benchmark_config(benchmark_config, database_config)

        output_text = output.getvalue()
        assert "Star Schema Benchmark" in output_text
        assert "0.01" in output_text  # Default scale factor
        assert "standard" in output_text  # Default execution type
        assert "SQLite" in output_text
        assert "Compression" not in output_text  # Not enabled

    def test_show_benchmark_result_success(self):
        """Test showing successful benchmark result."""
        output = StringIO()
        console = Console(file=output, force_terminal=False)
        displays = StandardDisplays(console)

        # Create query results
        query_results = [
            QueryResult(
                query_id="q1",
                query_name="Query 1",
                sql_text="SELECT COUNT(*) FROM lineitem",
                execution_time_ms=123.45,
                rows_returned=1,
                status="SUCCESS",
            ),
            QueryResult(
                query_id="q2",
                query_name="Query 2",
                sql_text="SELECT * FROM orders WHERE invalid",
                execution_time_ms=0.0,
                rows_returned=0,
                status="ERROR",
                error_message="Column 'invalid' doesn't exist",
            ),
        ]

        result = make_benchmark_results(
            benchmark_id="tpch",
            benchmark_name="TPC-H Power Test",
            test_execution_type="power",
            scale_factor=1.0,
            query_results=query_results,
            power_at_size=1500.75,
            geometric_mean_execution_time=87.23,
            duration_seconds=180.5,
        )

        displays.show_benchmark_result(result)

        output_text = output.getvalue()
        assert "Results" in output_text
        assert "TPC-H Power Test" in output_text
        assert "Scale Factor: 1.0" in output_text
        assert "Power@Size" in output_text and "1500.75" in output_text
        assert "Geometric Mean" in output_text and "87.230s" in output_text
        assert "Duration" in output_text and "180.50 seconds" in output_text
        assert "Query Execution Summary" in output_text
        assert "Query 1" in output_text
        assert "123.5" in output_text
        assert "SUCCESS" in output_text
        assert "ERROR" in output_text
        # Error details are not shown in basic display mode

    def test_show_benchmark_result_minimal(self):
        """Test showing minimal benchmark result."""
        output = StringIO()
        console = Console(file=output, force_terminal=False)
        displays = StandardDisplays(console)

        result = make_benchmark_results(
            benchmark_id="ssb",
            benchmark_name="Star Schema Benchmark",
            query_results=[],  # No queries run
        )

        displays.show_benchmark_result(result)

        output_text = output.getvalue()
        assert "Star Schema Benchmark" in output_text
        assert "Scale Factor: 0.01" in output_text  # Default
        assert "Type: standard" in output_text  # Default
        assert "No query results available" in output_text

    def test_show_benchmark_result_with_metrics(self):
        """Test showing benchmark result with various metrics."""
        output = StringIO()
        console = Console(file=output, force_terminal=False)
        displays = StandardDisplays(console)

        result = make_benchmark_results(
            benchmark_id="tpcds",
            benchmark_name="TPC-DS Throughput Test",
            test_execution_type="throughput",
            scale_factor=10.0,
            duration_seconds=3600.0,
            query_results=[],
        )

        displays.show_benchmark_result(result)

        output_text = output.getvalue()
        assert "TPC-DS Throughput Test" in output_text
        assert "Scale Factor: 10.0" in output_text
        assert "throughput" in output_text
        # The display doesn't show throughput metrics without data
        assert "3600.00 seconds" in output_text

    def test_show_benchmark_result_performance_summary(self):
        """Test benchmark result shows performance summary correctly."""
        output = StringIO()
        console = Console(file=output, force_terminal=False)
        displays = StandardDisplays(console)

        # Mix of successful and failed queries
        query_results = [
            QueryResult(
                query_id="q1",
                query_name="Query 1",
                sql_text="SELECT 1",
                execution_time_ms=50.0,
                rows_returned=100,
                status="SUCCESS",
            ),
            QueryResult(
                query_id="q2",
                query_name="Query 2",
                sql_text="SELECT 2",
                execution_time_ms=75.0,
                rows_returned=200,
                status="SUCCESS",
            ),
            QueryResult(
                query_id="q3",
                query_name="Query 3",
                sql_text="SELECT invalid",
                execution_time_ms=0.0,
                rows_returned=0,
                status="ERROR",
                error_message="Invalid query",
            ),
        ]

        result = make_benchmark_results(
            benchmark_id="test",
            benchmark_name="Test Benchmark",
            query_results=query_results,
            duration_seconds=125.0,
        )

        displays.show_benchmark_result(result)

        output_text = output.getvalue()
        # Performance summary is shown in Query Execution Summary
        assert "Query Execution Summary" in output_text
        assert "2 successful" in output_text
        assert "1 failed" in output_text
        # Summary shows total/average time not individual metrics
        assert "0.042s per query" in output_text

    def test_rich_formatting_disabled_for_tests(self):
        """Test that rich formatting is properly disabled in test output."""
        output = StringIO()
        console = Console(file=output, force_terminal=False)  # Disable terminal features
        displays = StandardDisplays(console)

        displays.show_banner("Test", "1.0")

        output_text = output.getvalue()
        # Should not contain ANSI escape codes when terminal is disabled
        assert "\x1b[" not in output_text  # No ANSI escape sequences

    @patch("benchbox.cli.common_types.datetime")
    def test_timestamp_formatting(self, mock_datetime):
        """Test that timestamps are formatted correctly."""
        # Mock datetime.now() to return fixed time
        fixed_time = datetime(2025, 1, 15, 10, 30, 45)
        mock_datetime.now.return_value = fixed_time
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        output = StringIO()
        console = Console(file=output, force_terminal=False)
        displays = StandardDisplays(console)

        profile = SystemProfile(
            os_name="Linux",
            os_version="5.4.0",
            architecture="x86_64",
            cpu_model="Intel",
            cpu_cores_physical=4,
            cpu_cores_logical=8,
            memory_total_gb=16.0,
            memory_available_gb=12.0,
            python_version="3.11.0",
            disk_space_gb=500.0,
            timestamp=fixed_time,
            hostname="test",
        )

        displays.show_system_profile(profile, detailed=True)

        output_text = output.getvalue()
        assert "2025-01-15 10:30:45" in output_text


class TestDisplayFormattingEdgeCases:
    """Test edge cases and error conditions in display formatting."""

    def test_large_numbers_formatting(self):
        """Test formatting of large numbers."""
        output = StringIO()
        console = Console(file=output, force_terminal=False)
        displays = StandardDisplays(console)

        result = make_benchmark_results(
            benchmark_id="large_test",
            benchmark_name="Large Numbers Test",
            scale_factor=1000.0,
            power_at_size=1234567.89,
            geometric_mean_execution_time=987654.321,
            duration_seconds=86400.0,  # 24 hours
            query_results=[],
        )

        displays.show_benchmark_result(result)

        output_text = output.getvalue()
        assert "1000.0" in output_text
        assert "1234567.89" in output_text
        assert "987654.321" in output_text
        assert "86400.0" in output_text

    def test_zero_and_negative_values(self):
        """Test handling of zero and edge case values."""
        output = StringIO()
        console = Console(file=output, force_terminal=False)
        displays = StandardDisplays(console)

        query_results = [
            QueryResult(
                query_id="q_zero",
                query_name="Zero Time Query",
                sql_text="SELECT 1",
                execution_time_ms=0.0,
                rows_returned=0,
                status="SUCCESS",
            )
        ]

        result = make_benchmark_results(
            benchmark_id="edge_test",
            benchmark_name="Edge Case Test",
            scale_factor=0.001,
            query_results=query_results,
            duration_seconds=0.0,
        )

        displays.show_benchmark_result(result)

        output_text = output.getvalue()
        assert "0.001" in output_text
        assert "0.0" in output_text  # Time shows as 0.0 in the table
        assert "0.00 seconds" in output_text

    def test_none_values_handling(self):
        """Test handling of None values in data structures."""
        output = StringIO()
        console = Console(file=output, force_terminal=False)
        displays = StandardDisplays(console)

        # SystemProfile with some None values
        profile = SystemProfile(
            os_name="Unknown",
            os_version="Unknown",
            architecture="Unknown",
            cpu_model="Unknown CPU",
            cpu_cores_physical=1,
            cpu_cores_logical=1,
            memory_total_gb=0.0,
            memory_available_gb=0.0,
            python_version="3.11.0",
            disk_space_gb=0.0,
            timestamp=datetime.now(),
            hostname="unknown",
        )

        displays.show_system_profile(profile)

        output_text = output.getvalue()
        assert "Unknown" in output_text
        assert "0.0 GB" in output_text
