"""
Tests for CLI ConsoleResultFormatter functionality.

Tests consolidated result display functionality used across examples.
"""

from dataclasses import dataclass
from typing import Optional
from unittest.mock import patch

import pytest

from benchbox.core.schemas import QueryResult
from tests.fixtures.result_dict_fixtures import make_benchmark_results

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# Import the ConsoleResultFormatter - we'll need to handle import errors gracefully
try:
    from benchbox.cli.output import ConsoleResultFormatter

    IMPORTS_AVAILABLE = True
    skip_reason = None
except ImportError as e:
    # If CLI modules aren't available due to missing dependencies, skip these tests
    IMPORTS_AVAILABLE = False
    skip_reason = f"CLI modules not available: {e}"


# Mock classes for testing when imports are not available
@dataclass
class MockBenchmarkResult:
    """Mock BenchmarkResult for testing."""

    benchmark_name: str = "test-benchmark"
    benchmark_id: str = "test-id"
    scale_factor: float = 1.0
    duration_seconds: float = 10.0
    query_results: list = None
    power_at_size: Optional[float] = None
    throughput_at_size: Optional[float] = None
    geometric_mean_execution_time: Optional[float] = None

    def __post_init__(self):
        if self.query_results is None:
            self.query_results = []


@dataclass
class MockQueryResult:
    """Mock QueryResult for testing."""

    query_id: str
    status: str
    execution_time_ms: float
    error_message: Optional[str] = None


@dataclass
class MockBenchmarkResults:
    """Mock BenchmarkResults for testing."""

    scale_factor: float = 1.0
    platform: str = "test-platform"
    database_name: str = "test-db"
    successful_queries: int = 5
    total_queries: int = 5
    total_execution_time: float = 10.0
    average_query_time: float = 2.0
    benchmark_name: str = "test-benchmark"
    data_size_mb: Optional[float] = None
    schema_creation_time: Optional[float] = None
    data_loading_time: Optional[float] = None
    tuning_enabled: bool = False
    constraints_applied: Optional[str] = None
    query_results: Optional[list] = None


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason=skip_reason or "CLI modules not available")
class TestConsoleResultFormatter:
    """Test ConsoleResultFormatter functionality when imports are available."""

    @patch("benchbox.cli.output.console")
    def test_display_benchmark_summary_cli_result(self, mock_console):
        """Test displaying CLI BenchmarkResult format."""
        # Create mock CLI result
        query_results = [
            QueryResult(
                query_id="Q1",
                query_name="Query 1",
                sql_text="SELECT 1",
                execution_time_ms=1000,
                rows_returned=1,
                status="SUCCESS",
                error_message=None,
            ),
            QueryResult(
                query_id="Q2",
                query_name="Query 2",
                sql_text="SELECT 2",
                execution_time_ms=2000,
                rows_returned=2,
                status="SUCCESS",
                error_message=None,
            ),
        ]

        result = make_benchmark_results(
            benchmark_name="TPC-H",
            benchmark_id="tpch",
            scale_factor=1.0,
            duration_seconds=10.5,
            total_queries=2,
            successful_queries=2,
            query_results=query_results,
            power_at_size=1234.56,
        )
        result.summary_metrics = {
            "total_queries": 2,
            "successful_queries": 2,
            "success_rate": 1.0,
        }

        ConsoleResultFormatter.display_benchmark_summary(result, verbose=False)

        # Verify console.print was called with expected content
        assert mock_console.print.called
        calls = [str(call) for call in mock_console.print.call_args_list]

        # Check for expected content in the output
        assert any("TPC-H" in call for call in calls)
        assert any("1.0" in call for call in calls)  # Scale factor
        assert any("2/2 queries successful" in call for call in calls)

    @patch("benchbox.cli.output.console")
    def test_display_benchmark_summary_platform_result(self, mock_console):
        """Test displaying platform BenchmarkResults format."""
        result = MockBenchmarkResults(
            scale_factor=0.1,
            platform="DuckDB",
            successful_queries=3,
            total_queries=5,
            total_execution_time=25.5,
            average_query_time=8.5,
            data_size_mb=100.0,
            schema_creation_time=1.5,
        )

        # Mock the hasattr calls since our mock doesn't have benchmark_id
        with patch(
            "builtins.hasattr",
            side_effect=lambda obj, attr: attr in ["data_size_mb", "schema_creation_time"],
        ):
            ConsoleResultFormatter.display_benchmark_summary(result, verbose=False)

        # Verify console.print was called
        assert mock_console.print.called
        calls = [str(call) for call in mock_console.print.call_args_list]

        # Check for expected content
        assert any("0.1" in call for call in calls)  # Scale factor
        assert any("DuckDB" in call for call in calls)  # Platform
        assert any("3/5 successful" in call for call in calls)  # Query success count

    @patch("benchbox.cli.output.console")
    def test_display_query_performance_verbose(self, mock_console):
        """Test verbose query performance display."""
        query_results = [
            QueryResult(
                query_id="Q1",
                query_name="Query 1",
                sql_text="SELECT 1",
                status="SUCCESS",
                execution_time_ms=1000,
                rows_returned=1,
            ),
            QueryResult(
                query_id="Q2",
                query_name="Query 2",
                sql_text="SELECT 2",
                status="ERROR",
                execution_time_ms=0,
                rows_returned=0,
                error_message="Syntax error",
            ),
            QueryResult(
                query_id="Q3",
                query_name="Query 3",
                sql_text="SELECT 3",
                status="SUCCESS",
                execution_time_ms=3000,
                rows_returned=3,
            ),
        ]

        result = make_benchmark_results(
            benchmark_name="TPC-H",
            benchmark_id="tpch",
            scale_factor=1.0,
            duration_seconds=10.0,
            total_queries=3,
            successful_queries=2,
            failed_queries=1,
            query_results=query_results,
        )

        ConsoleResultFormatter.display_query_performance(result)

        # Verify console.print was called for verbose output
        assert mock_console.print.called
        calls = [str(call) for call in mock_console.print.call_args_list]

        # Should include query details section
        assert any("Query Details" in call for call in calls)

    def test_format_execution_statistics_cli_result(self):
        """Test formatting execution statistics for CLI results."""
        query_results = [
            QueryResult(
                query_id="Q1",
                query_name="Query 1",
                sql_text="SELECT 1",
                status="SUCCESS",
                execution_time_ms=1000,
                rows_returned=1,
            ),
            QueryResult(
                query_id="Q2",
                query_name="Query 2",
                sql_text="SELECT 2",
                status="SUCCESS",
                execution_time_ms=2000,
                rows_returned=2,
            ),
        ]

        result = make_benchmark_results(
            benchmark_name="TPC-H",
            benchmark_id="tpch",
            scale_factor=2.0,
            duration_seconds=15.5,
            total_queries=2,
            successful_queries=2,
            query_results=query_results,
            power_at_size=987.65,
        )

        stats = ConsoleResultFormatter.format_execution_statistics(result)

        assert isinstance(stats, dict)
        assert stats["benchmark"] == "TPC-H"
        assert stats["scale_factor"] == "2.0"
        assert stats["queries_total"] == "2"
        assert stats["queries_successful"] == "2"
        assert stats["power_at_size"] == "987.65"

    def test_format_execution_statistics_platform_result(self):
        """Test formatting execution statistics for platform results."""
        result = MockBenchmarkResults(
            platform="DuckDB",
            scale_factor=1.5,
            total_queries=10,
            successful_queries=8,
            total_execution_time=45.2,
            average_query_time=5.65,
        )

        # Mock hasattr to return True for platform (platform result)
        with patch("builtins.hasattr", side_effect=lambda obj, attr: attr == "platform"):
            stats = ConsoleResultFormatter.format_execution_statistics(result)

        assert isinstance(stats, dict)
        assert stats["platform"] == "DuckDB"
        assert stats["scale_factor"] == "1.5"
        assert stats["queries_total"] == "10"
        assert stats["queries_successful"] == "8"
        assert "total_execution_time" in stats
        assert "average_query_time" in stats

    @patch("benchbox.cli.output.console")
    def test_display_enhanced_benchmark_result(self, mock_console):
        """Test displaying enhanced BenchmarkResults format."""
        from datetime import datetime

        from benchbox.core.results.models import (
            BenchmarkResults,
            ExecutionPhases,
            SetupPhase,
        )

        # Create mock enhanced result using actual dataclass fields
        result = BenchmarkResults(
            benchmark_name="TPC-H Enhanced",
            platform="TestDB",
            scale_factor=1.0,
            execution_id="test_123",
            timestamp=datetime.now(),
            duration_seconds=15.5,
            query_definitions={},
            execution_phases=ExecutionPhases(setup=SetupPhase()),
            total_queries=2,
            successful_queries=2,
            failed_queries=0,
            total_execution_time=5.0,
            average_query_time=2.5,
        )

        # Manually add enhanced elements to the object for testing (since they're not in constructor)
        result.phases = {"data_generation": {"status": "COMPLETED", "duration": 1.0}}
        result.resource_utilization = {"peak_memory_mb": 128.5, "avg_cpu_percent": 45.2}
        result.performance_characteristics = {"parallel_efficiency": 0.87}

        ConsoleResultFormatter.display_benchmark_summary(result, verbose=False)

        # Verify console.print was called with enhanced content
        assert mock_console.print.called
        calls = [str(call) for call in mock_console.print.call_args_list]

        # Check that enhanced elements are displayed
        all_calls = " ".join(calls)
        assert "Phase Execution Summary" in all_calls
        assert "Resource Utilization" in all_calls
        assert "Performance Characteristics" in all_calls


class TestConsoleFormatterMocked:
    """Test ConsoleResultFormatter functionality using mocked classes."""

    def test_mock_result_creation(self):
        """Test that our mock classes work properly."""
        if IMPORTS_AVAILABLE:
            assert ConsoleResultFormatter is not None
            return
        result = MockBenchmarkResult(benchmark_name="Test", scale_factor=1.0, duration_seconds=10.0)

        assert result.benchmark_name == "Test"
        assert result.scale_factor == 1.0
        assert result.duration_seconds == 10.0
        assert result.query_results == []  # Default from __post_init__

    def test_mock_platform_result(self):
        """Test mock platform result creation."""
        if IMPORTS_AVAILABLE:
            assert ConsoleResultFormatter is not None
            return
        result = MockBenchmarkResults(platform="MockDB", successful_queries=3, total_queries=5)

        assert result.platform == "MockDB"
        assert result.successful_queries == 3
        assert result.total_queries == 5


class TestFormattingIntegration:
    """Test integration with formatting utilities (should always work)."""

    def test_formatting_import(self):
        """Test that formatting utilities are available."""
        from benchbox.utils import format_bytes, format_duration

        # Test the functions work as expected
        assert format_duration(1.5) == "1.500s"
        assert format_bytes(2048) == "2.00 KB"

    def test_formatting_consistency(self):
        """Test formatting consistency across different values."""
        from benchbox.utils import format_bytes, format_duration

        # Test duration formatting consistency
        durations = [0.001, 0.5, 1.0, 30.0, 60.0, 120.0]
        for duration in durations:
            result = format_duration(duration)
            assert isinstance(result, str)
            assert len(result) > 0

        # Test byte formatting consistency
        byte_sizes = [0, 1024, 1048576, 1073741824]
        for size in byte_sizes:
            result = format_bytes(size)
            assert isinstance(result, str)
            assert len(result) > 0
            assert "B" in result  # Should contain unit
