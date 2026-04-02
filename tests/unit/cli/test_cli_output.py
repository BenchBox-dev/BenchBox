"""Tests for CLI output and result export functionality.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import csv
import json
import shutil
import sys
import tempfile
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any, Optional
from unittest.mock import Mock, patch

import pytest
from rich.console import Console

from benchbox.cli.output import ConsoleResultFormatter, ResultExporter
from benchbox.core.schemas import QueryResult
from tests.fixtures.result_dict_fixtures import make_benchmark_results

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestConsoleResultFormatter:
    """Test the ConsoleResultFormatter class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_console = Mock()

    def create_cli_result(self):
        """Create a mock BenchmarkResults instance mimicking legacy CLI output."""
        query_results = [
            QueryResult(
                query_id="Q1",
                query_name="Query 1",
                sql_text="SELECT COUNT(*) FROM customer",
                execution_time_ms=1500.0,
                rows_returned=1,
                status="SUCCESS",
                error_message=None,
            ),
            QueryResult(
                query_id="Q2",
                query_name="Query 2",
                sql_text="SELECT * FROM orders",
                execution_time_ms=2500.0,
                rows_returned=1000,
                status="SUCCESS",
                error_message=None,
            ),
            QueryResult(
                query_id="Q3",
                query_name="Query 3",
                sql_text="SELECT INVALID SYNTAX",
                execution_time_ms=0.0,
                rows_returned=0,
                status="ERROR",
                error_message="Syntax error in SQL query",
            ),
        ]

        return make_benchmark_results(
            benchmark_name="TPC-H",
            platform="duckdb",
            execution_id="exec_123",
            duration_seconds=5.5,
            total_queries=len(query_results),
            successful_queries=2,
            failed_queries=1,
            query_results=query_results,
            validation_status="PASSED",
            power_at_size=123.45,
            throughput_at_size=456.78,
            geometric_mean_execution_time=2.0,
            total_execution_time=4.0,
            average_query_time=4.0 / len(query_results),
            performance_summary={"avg_time": 1.3},
            execution_metadata={"benchmark_id": "tpch", "benchmark_version": "2.8.0"},
        )

    def create_platform_result(self):
        """Create a mock platform BenchmarkResults."""
        return make_benchmark_results(
            benchmark_name="TPC-H",
            platform="duckdb",
            execution_id="exec_456",
            duration_seconds=4.2,
            total_queries=22,
            successful_queries=20,
            failed_queries=2,
            query_results=[
                {
                    "query_id": "Q1",
                    "execution_time": 1.5,
                    "status": "SUCCESS",
                    "rows_returned": 100,
                },
                {
                    "query_id": "Q2",
                    "execution_time": 2.0,
                    "status": "ERROR",
                    "error": "Timeout",
                },
            ],
            total_execution_time=3.5,
            average_query_time=1.75,
            data_loading_time=0.8,
            schema_creation_time=0.2,
            total_rows_loaded=150000,
            data_size_mb=25.5,
            table_statistics={"customer": 15000, "orders": 135000},
        )

    @patch("benchbox.cli.output.console")
    def test_display_cli_result_basic(self, mock_console):
        """Test basic CLI result display."""
        result = self.create_cli_result()

        ConsoleResultFormatter.display_benchmark_summary(result, verbose=False)

        # Verify console.print was called with key information
        assert mock_console.print.called
        calls = [str(call) for call in mock_console.print.call_args_list]

        # Check that key information was printed
        assert any("TPC-H" in call for call in calls)
        assert any("0.01" in call for call in calls)  # Scale factor
        assert any("2/3" in call for call in calls)  # Success rate

    @patch("benchbox.cli.output.console")
    def test_display_cli_result_verbose(self, mock_console):
        """Test verbose CLI result display."""
        result = self.create_cli_result()

        ConsoleResultFormatter.display_benchmark_summary(result, verbose=True)

        # Verify detailed query information was displayed
        assert mock_console.print.called
        calls = [str(call) for call in mock_console.print.call_args_list]

        # Should include query details
        assert any("Query Details" in call for call in calls)
        assert any("Failed Queries" in call for call in calls)

    @patch("benchbox.cli.output.console")
    def test_display_cli_result_shows_validation_stages(self, mock_console):
        """Ensure validation stage summaries are printed for lifecycle results."""
        result = self.create_cli_result()
        result.validation_status = "PASSED"
        result.validation_details = {
            "stages": [
                {"stage": "preflight", "status": "PASSED", "errors": [], "warnings": []},
                {
                    "stage": "post_generation_manifest",
                    "status": "WARNINGS",
                    "errors": [],
                    "warnings": ["manifest row counts incomplete"],
                },
            ]
        }

        ConsoleResultFormatter.display_benchmark_summary(result, verbose=False)

        assert mock_console.print.called

    @patch("benchbox.cli.output.console")
    def test_display_handles_minimal_query_dicts(self, mock_console):
        """Display should cope with dict-based query results containing sparse fields."""
        result = make_benchmark_results(
            benchmark_name="Test",
            platform="duckdb",
            execution_id="exec_minimal",
            duration_seconds=1.0,
            total_queries=2,
            successful_queries=1,
            failed_queries=1,
            query_results=[
                {"query_id": "Q1", "status": "SUCCESS", "execution_time_ms": 10.0},
                {"query_id": "Q2", "status": "ERROR"},
            ],
            validation_status="PASSED",
        )

        result.validation_details = {
            "stages": [
                {"stage": "preflight", "status": "PASSED", "errors": [], "warnings": []},
                {
                    "stage": "post_generation_manifest",
                    "status": "WARNINGS",
                    "errors": [],
                    "warnings": ["manifest row counts incomplete"],
                },
            ]
        }

        ConsoleResultFormatter.display_benchmark_summary(result, verbose=True)

        assert mock_console.print.called
        rendered = [" ".join(str(arg) for arg in call.args) for call in mock_console.print.call_args_list]

        assert any("Validation Stages" in line for line in rendered)
        assert any("✅ Preflight: PASSED" in line for line in rendered)
        assert any("⚠️ Post Generation Manifest: WARNINGS" in line for line in rendered)
        assert any("manifest row counts incomplete" in line for line in rendered)

    @patch("benchbox.cli.output.console")
    def test_display_platform_result_basic(self, mock_console):
        """Test basic platform result display."""
        result = self.create_platform_result()

        ConsoleResultFormatter.display_benchmark_summary(result, verbose=False)

        # Verify console.print was called
        assert mock_console.print.called
        calls = [str(call) for call in mock_console.print.call_args_list]

        # Check that platform-specific information was printed
        assert any("duckdb" in call for call in calls)
        assert any("20/22" in call for call in calls)  # Success rate

    def test_format_execution_statistics_cli_result(self):
        """Test formatting execution statistics for CLI results."""
        result = self.create_cli_result()

        stats = ConsoleResultFormatter.format_execution_statistics(result)

        assert stats["benchmark"] == "TPC-H"
        assert stats["scale_factor"] == "0.01"
        assert stats["queries_total"] == "3"
        assert stats["queries_successful"] == "2"
        assert stats["power_at_size"] == "123.45"

    def test_format_execution_statistics_platform_result(self):
        """Test formatting execution statistics for platform results."""
        result = self.create_platform_result()

        stats = ConsoleResultFormatter.format_execution_statistics(result)

        assert stats["platform"] == "duckdb"
        assert stats["scale_factor"] == "0.01"
        assert stats["queries_total"] == "22"
        assert stats["queries_successful"] == "20"
        assert "total_execution_time" in stats
        assert "average_query_time" in stats

    @patch("benchbox.cli.output.console")
    def test_display_query_performance(self, mock_console):
        """Test query performance display (verbose mode)."""
        result = self.create_cli_result()

        ConsoleResultFormatter.display_query_performance(result)

        # Should call verbose display
        assert mock_console.print.called
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Query Details" in call for call in calls)

    def _render_summary_output(self, result) -> str:
        output = StringIO()
        render_console = Console(file=output, width=120, force_terminal=False)
        with patch("benchbox.cli.output.console", render_console):
            ConsoleResultFormatter.render_comprehensive_execution_summary(result)
        return output.getvalue()

    def test_render_comprehensive_execution_summary_shows_breakdown_and_failures(self):
        """Comprehensive summary should render validation counts and failed query details."""
        result = make_benchmark_results(
            benchmark_name="TPC-H",
            platform="duckdb",
            execution_id="exec_summary_fail",
            duration_seconds=5.0,
            total_queries=3,
            successful_queries=1,
            failed_queries=2,
            query_results=[
                {
                    "query_id": "Q1",
                    "status": "SUCCESS",
                    "execution_time_seconds": 0.5,
                    "row_count_validation": {"status": "PASSED"},
                },
                {
                    "query_id": "Q2",
                    "status": "ERROR",
                    "error": "row count mismatch on customer table",
                    "execution_time_seconds": 1.2,
                    "row_count_validation": {"status": "FAILED", "expected": 10, "actual": 8},
                },
                {
                    "query_id": "Q3",
                    "status": "ERROR",
                    "error": "permission denied while reading parquet metadata",
                    "execution_time_seconds": 1.4,
                    "row_count_validation": {"status": "SKIPPED"},
                },
            ],
            validation_status="FAILED",
            total_execution_time=3.1,
            average_query_time=3.1,
        )

        output = self._render_summary_output(result)

        assert "Execution Summary" in output
        assert "Validation Breakdown" in output
        assert "FAILED" in output
        assert "SKIPPED" in output
        assert "Top Query Failures" in output
        assert "Query Q2" in output
        assert "Expected 10 rows, got 8" in output
        assert "Benchmark completed with 2 failures" in output

    def test_render_comprehensive_execution_summary_partial_validation(self):
        """Partial validation should keep the success path but show the partial recommendations."""
        result = make_benchmark_results(
            benchmark_name="TPC-DS",
            platform="snowflake",
            execution_id="exec_summary_partial",
            duration_seconds=4.0,
            total_queries=2,
            successful_queries=2,
            failed_queries=0,
            query_results=[
                {
                    "query_id": "Q1",
                    "status": "SUCCESS",
                    "execution_time_seconds": 1.0,
                    "row_count_validation": {"status": "PASSED"},
                },
                {
                    "query_id": "Q2",
                    "status": "SUCCESS",
                    "execution_time_seconds": 1.5,
                    "row_count_validation": {"status": "SKIPPED"},
                },
            ],
            validation_status="PARTIAL",
            total_execution_time=2.5,
            average_query_time=1.25,
        )

        output = self._render_summary_output(result)

        assert "Validation Breakdown" in output
        assert "Note: Validation is typically skipped when scale factor" in output
        assert "Benchmark completed with partial validation" in output
        assert "Run at scale factor 1.0 for full validation" in output

    def test_render_overall_status_unclear_branch(self):
        """Unknown validation states should surface the fallback status message."""
        output = StringIO()
        render_console = Console(file=output, width=100, force_terminal=False)

        with patch("benchbox.cli.output.console", render_console):
            ConsoleResultFormatter._render_overall_status("UNKNOWN", 0, 0)

        rendered = output.getvalue()
        assert "Benchmark status unclear" in rendered
        assert "Validation: UNKNOWN, Queries: 0/0" in rendered


class TestResultExporter:
    """Test the ResultExporter class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.exporter = ResultExporter(output_dir=Path(self.temp_dir), anonymize=False)

    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_cli_result(
        self,
        *,
        query_results: Optional[list[QueryResult]] = None,
        execution_id: str = "exec_123",
    ):
        """Create a test BenchmarkResults instance representing legacy CLI output."""

        if query_results is None:
            query_results = [
                QueryResult(
                    query_id="Q1",
                    query_name="Query 1",
                    sql_text="SELECT COUNT(*) FROM customer",
                    execution_time_ms=1000.0,
                    rows_returned=1,
                    status="SUCCESS",
                    error_message=None,
                ),
                QueryResult(
                    query_id="Q2",
                    query_name="Query 2",
                    sql_text="SELECT * FROM orders",
                    execution_time_ms=2000.0,
                    rows_returned=500,
                    status="SUCCESS",
                    error_message=None,
                ),
            ]

        def _extract_status(entry: QueryResult | dict[str, Any]) -> str:
            if isinstance(entry, dict):
                return entry.get("status", "UNKNOWN")
            return entry.status

        def _extract_execution_ms(entry: QueryResult | dict[str, Any]) -> float:
            if isinstance(entry, dict):
                if entry.get("execution_time_ms") is not None:
                    return float(entry["execution_time_ms"])
                if entry.get("execution_time") is not None:
                    return float(entry["execution_time"]) * 1000.0
                return 0.0
            return float(entry.execution_time_ms)

        total_queries = len(query_results)
        successful_queries = len([q for q in query_results if _extract_status(q) == "SUCCESS"])
        failed_queries = total_queries - successful_queries
        total_execution_time = sum(_extract_execution_ms(q) for q in query_results) / 1000.0
        average_query_time = total_execution_time / successful_queries if successful_queries else 0.0

        return make_benchmark_results(
            benchmark_id="tpch",
            benchmark_name="TPC-H",
            execution_id=execution_id,
            timestamp=datetime(2025, 1, 15, 10, 30, 0),
            duration_seconds=3.5,
            total_queries=total_queries,
            successful_queries=successful_queries,
            failed_queries=failed_queries,
            query_results=query_results,
            total_execution_time=total_execution_time,
            average_query_time=average_query_time,
            validation_status="PASSED",
            validation_details={"all_queries": "passed"},
            execution_metadata={"benchmark_id": "tpch", "benchmark_version": "2.8.0"},
            power_at_size=123.45,
            throughput_at_size=456.78,
            geometric_mean_execution_time=2.0,
            performance_summary={"avg_time": 1.5},
            total_rows_loaded=0,
            data_size_mb=0.0,
        )

    def create_platform_result(self):
        """Create a test platform result."""
        return make_benchmark_results(
            benchmark_name="TPC-H",
            platform="duckdb",
            execution_id="exec_456",
            timestamp=datetime(2025, 1, 15, 11, 0, 0),
            duration_seconds=4.2,
            total_queries=2,
            successful_queries=2,
            query_results=[
                {
                    "query_id": "Q1",
                    "execution_time": 1.0,
                    "status": "SUCCESS",
                    "rows_returned": 100,
                },
                {
                    "query_id": "Q2",
                    "execution_time": 2.0,
                    "status": "SUCCESS",
                    "rows_returned": 200,
                },
            ],
            total_execution_time=3.0,
            average_query_time=1.5,
            data_loading_time=0.5,
            schema_creation_time=0.2,
            total_rows_loaded=10000,
            data_size_mb=5.0,
            table_statistics={"customer": 1500, "orders": 8500},
            database_name="test_db",
            validation_status="PASSED",
            validation_details={},
        )

    def test_exporter_initialization(self):
        """Test ResultExporter initialization."""
        exporter = ResultExporter(output_dir=Path(self.temp_dir))
        assert exporter.output_dir == Path(self.temp_dir)
        assert exporter.anonymize is True  # Default
        assert exporter.anonymization_manager is not None

        # Test without anonymization
        exporter_no_anon = ResultExporter(output_dir=Path(self.temp_dir), anonymize=False)
        assert exporter_no_anon.anonymize is False
        assert exporter_no_anon.anonymization_manager is None

    @patch("benchbox.cli.output.console")
    def test_export_json_cli_result(self, mock_console):
        """Test JSON export for CLI results."""
        result = self.create_cli_result()

        exported = self.exporter.export_result(result, formats=["json"])

        assert "json" in exported
        json_path = exported["json"]
        assert json_path.exists()

        # Verify JSON content (v2.0 schema)
        with open(json_path) as f:
            data = json.load(f)

        assert data["version"] == "2.1"
        assert data["benchmark"]["id"] == "tpch"
        assert data["benchmark"]["name"] == "TPC-H"

        # v2.0 uses summary.queries and compact queries array
        summary_queries = data["summary"]["queries"]
        assert summary_queries["total"] == 2
        assert summary_queries["passed"] == 2

        queries = data["queries"]
        assert len(queries) == 2
        # Query IDs are normalized to numeric strings (e.g., "Q1" -> "1")
        assert queries[0]["id"] == "1"

        assert data["export"]["anonymized"] is False

    @patch("benchbox.cli.output.console")
    def test_export_json_platform_result(self, mock_console):
        """Test JSON export for platform results."""
        result = self.create_platform_result()

        exported = self.exporter.export_result(result, formats=["json"])

        assert "json" in exported
        json_path = exported["json"]
        assert json_path.exists()

        # Verify JSON content (v2.0 schema)
        with open(json_path) as f:
            data = json.load(f)

        assert data["version"] == "2.1"
        assert data["benchmark"]["name"] == "TPC-H"
        assert data["platform"]["name"] == "duckdb"

        # v2.0 uses summary.queries
        summary_queries = data["summary"]["queries"]
        assert summary_queries["total"] == 2
        assert summary_queries["passed"] == 2

    def test_export_csv_cli_result(self):
        """Test CSV export of CLI result."""
        # Create test result
        query_results = [
            {
                "query_id": "q1",
                "query_name": "Query 1",
                "execution_time_ms": 100.0,
                "rows_returned": 1,
                "status": "SUCCESS",
                "error_message": None,
            },
            {
                "query_id": "q2",
                "query_name": "Query 2",
                "execution_time_ms": 200.0,
                "rows_returned": 2,
                "status": "SUCCESS",
                "error_message": None,
            },
            {
                "query_id": "q3",
                "query_name": "Query 3",
                "execution_time_ms": 150.0,
                "rows_returned": 0,
                "status": "ERROR",
                "error_message": "Test error",
            },
        ]

        result = self.create_cli_result(query_results=query_results, execution_id="exec_csv")

        # Export to CSV
        exported = self.exporter.export_result(result, ["csv"])

        # Verify CSV was exported
        assert "csv" in exported
        csv_path = exported["csv"]

        # Verify CSV content
        with open(csv_path, newline="") as f:
            reader = csv.reader(f)
            headers = next(reader)
            rows = list(reader)

        # v2.0 CSV format has simplified headers
        expected_headers = [
            "query_id",
            "execution_time_ms",
            "rows_returned",
            "status",
            "error_message",
            "iteration",
            "stream",
        ]
        assert headers == expected_headers

        # Check data rows
        assert len(rows) == 3
        assert rows[0][0] == "q1"  # query_id
        assert rows[0][1] == "100.0"  # execution_time_ms
        assert rows[0][3] == "SUCCESS"  # status
        assert rows[2][0] == "q3"  # query_id
        assert rows[2][4] == "Test error"  # error_message

    @patch("benchbox.cli.output.console")
    def test_export_html_cli_result(self, mock_console):
        """Test HTML export for CLI results."""
        query_results = [
            {
                "query_id": "Q1",
                "query_name": "Query 1",
                "execution_time_ms": 1000.0,
                "rows_returned": 1,
                "status": "SUCCESS",
            },
            {
                "query_id": "Q2",
                "query_name": "Query 2",
                "execution_time_ms": 2000.0,
                "rows_returned": 500,
                "status": "SUCCESS",
            },
        ]

        result = self.create_cli_result(query_results=query_results)

        exported = self.exporter.export_result(result, formats=["html"])

        assert "html" in exported
        html_path = exported["html"]
        assert html_path.exists()

        # Verify HTML content
        with open(html_path) as f:
            html_content = f.read()

        assert "BenchBox Results" in html_content
        assert "TPC-H" in html_content
        assert "Query Results" in html_content
        assert "Q1" in html_content
        assert "SUCCESS" in html_content

    def test_export_multiple_formats(self):
        """Test exporting to multiple formats simultaneously."""
        # Create test result
        query_results = [
            {
                "query_id": "q1",
                "query_name": "Query 1",
                "execution_time_ms": 100.0,
                "rows_returned": 1,
                "status": "SUCCESS",
            },
            {
                "query_id": "q2",
                "query_name": "Query 2",
                "execution_time_ms": 200.0,
                "rows_returned": 2,
                "status": "SUCCESS",
            },
        ]

        result = self.create_cli_result(query_results=query_results, execution_id="exec_multi")

        # Export to multiple formats
        exported = self.exporter.export_result(result, ["json", "csv", "html"])

        # Verify all formats were exported
        assert len(exported) == 3
        assert "json" in exported
        assert "csv" in exported
        assert "html" in exported

        # Verify all files exist
        for path in exported.values():
            assert path.exists()

    @patch("benchbox.cli.output.console")
    def test_export_with_anonymization(self, mock_console):
        """Test export with anonymization enabled."""
        # Create exporter with anonymization
        anon_exporter = ResultExporter(output_dir=Path(self.temp_dir), anonymize=True)
        result = self.create_cli_result()

        with patch.object(anon_exporter.anonymization_manager, "anonymize_execution_metadata") as mock_anonymize:
            with patch.object(anon_exporter.anonymization_manager, "validate_anonymization") as mock_validate:
                mock_anonymize.return_value = {"anonymized": "data"}
                mock_validate.return_value = {"is_valid": True, "warnings": []}

                exported = anon_exporter.export_result(result, formats=["json"])

        json_path = exported["json"]
        with open(json_path) as f:
            data = json.load(f)

        assert data["export"]["anonymized"] is True
        # v2.0 schema puts machine_id in environment block
        assert data.get("environment", {}).get("machine_id")

    def test_list_results_empty(self):
        """Test listing results when no results exist."""
        results = self.exporter.list_results()
        assert results == []

    def test_list_results_with_files(self):
        """Test listing results with existing files."""
        # Create a test result file
        result = self.create_cli_result()
        self.exporter.export_result(result, formats=["json"])

        results = self.exporter.list_results()

        assert len(results) == 1
        assert results[0]["benchmark"] == "TPC-H"
        assert results[0]["execution_id"] == "exec_123"
        assert results[0]["queries"] == 2
        # v2.0 uses lowercase status
        assert results[0]["status"] == "passed"

    @patch("benchbox.cli.output.console")
    def test_show_results_summary_empty(self, mock_console):
        """Test showing results summary when no results exist."""
        self.exporter.show_results_summary()

        # Should print "No exported results found"
        assert mock_console.print.called
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("No exported results found" in call for call in calls)

    @patch("benchbox.cli.output.console")
    def test_show_results_summary_with_results(self, mock_console):
        """Test showing results summary with existing results."""
        # Create test results
        result = self.create_cli_result()
        self.exporter.export_result(result, formats=["json"])

        self.exporter.show_results_summary()

        # Should print results table
        assert mock_console.print.called
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Exported Results" in call for call in calls)

    def test_load_result_from_file_success(self):
        """Test loading result from file successfully."""
        # Create and export a result
        result = self.create_cli_result()
        exported = self.exporter.export_result(result, formats=["json"])

        loaded = self.exporter.load_result_from_file(exported["json"])

        assert loaded is not None
        assert loaded["version"] == "2.1"
        assert loaded["data"]["benchmark"]["id"] == "tpch"

    def test_load_result_from_file_not_found(self):
        """Test loading result from non-existent file."""
        non_existent_path = Path(self.temp_dir) / "non_existent.json"

        loaded = self.exporter.load_result_from_file(non_existent_path)

        assert loaded is None

    def test_compare_results_success(self):
        """Test successful result comparison."""
        # Create baseline result
        baseline_result = self.create_cli_result()
        baseline_result.query_results[0].execution_time_ms = 1000.0  # Q1: 1000ms
        baseline_result.query_results[1].execution_time_ms = 2000.0  # Q2: 2000ms
        baseline_exported = self.exporter.export_result(baseline_result, formats=["json"])

        # Create current result with different timings and execution_id
        current_result = self.create_cli_result()
        current_result.execution_id = "exec_456"  # Different execution_id to avoid filename collision
        current_result.query_results[0].execution_time_ms = 800.0  # Q1: 800ms (improved)
        current_result.query_results[1].execution_time_ms = 2500.0  # Q2: 2500ms (regressed)
        current_exported = self.exporter.export_result(current_result, formats=["json"])

        comparison = self.exporter.compare_results(baseline_exported["json"], current_exported["json"])

        assert "error" not in comparison
        assert comparison["summary"]["total_queries_compared"] == 2
        assert comparison["summary"]["improved_queries"] == 1  # Q1 improved
        assert comparison["summary"]["regressed_queries"] == 1  # Q2 regressed

        # Check individual query comparisons
        # Query IDs are normalized to numeric strings (e.g., "Q1" -> "1")
        query_comparisons = {q["query_id"]: q for q in comparison["query_comparisons"]}
        assert query_comparisons["1"]["improved"] is True
        assert query_comparisons["1"]["change_percent"] == -20.0  # 800 vs 1000 = -20%
        assert query_comparisons["2"]["improved"] is False
        assert query_comparisons["2"]["change_percent"] == 25.0  # 2500 vs 2000 = +25%

    def test_compare_results_file_not_found(self):
        """Test comparison with non-existent files."""
        non_existent1 = Path(self.temp_dir) / "baseline.json"
        non_existent2 = Path(self.temp_dir) / "current.json"

        comparison = self.exporter.compare_results(non_existent1, non_existent2)

        assert "error" in comparison
        assert "Failed to load" in comparison["error"]

    def test_compare_results_schema_mismatch(self):
        """Comparison should indicate version mismatch when versions differ."""
        baseline_result = self.create_cli_result()
        baseline_path = self.exporter.export_result(baseline_result, formats=["json"])["json"]

        current_result = self.create_cli_result()
        current_result.execution_id = "exec_other"
        current_path = self.exporter.export_result(current_result, formats=["json"])["json"]

        # Corrupt baseline to simulate unsupported non-v2 shape (remove canonical version).
        baseline_data = json.loads(baseline_path.read_text())
        del baseline_data["version"]
        baseline_data["schema_version"] = "1.1"
        baseline_path.write_text(json.dumps(baseline_data))

        comparison = self.exporter.compare_results(baseline_path, current_path)

        # Comparison proceeds but reports missing canonical version as unknown
        assert comparison["baseline_version"] == "unknown"
        assert comparison["current_version"] == "2.1"

    def test_export_comparison_report(self):
        """Test exporting comparison report."""
        # Create comparison data
        comparison = {
            "baseline_file": "baseline.json",
            "current_file": "current.json",
            "summary": {
                "total_queries_compared": 2,
                "improved_queries": 1,
                "regressed_queries": 1,
                "overall_assessment": "mixed_results",
            },
            "performance_changes": {
                "total_execution_time": {
                    "baseline": 3.0,
                    "current": 3.3,
                    "change_percent": 10.0,
                    "improved": False,
                }
            },
            "query_comparisons": [
                {
                    "query_id": "Q1",
                    "baseline_time_ms": 1000.0,
                    "current_time_ms": 800.0,
                    "change_percent": -20.0,
                    "improved": True,
                }
            ],
        }

        report_path = self.exporter.export_comparison_report(comparison)

        assert report_path.exists()
        assert report_path.suffix == ".html"

        # Verify HTML content
        with open(report_path) as f:
            html_content = f.read()

        assert "Performance Comparison Report" in html_content
        assert "Q1" in html_content
        assert "Improved" in html_content

    def test_assess_performance_change(self):
        """Test performance change assessment."""
        # Significant improvement
        changes = {
            "total_execution_time": {"change_percent": -15.0},
            "average_query_time": {"change_percent": -12.0},
        }
        assessment = self.exporter._assess_performance_change(changes)
        assert assessment == "significant_improvement"

        # Significant regression
        changes = {
            "total_execution_time": {"change_percent": 15.0},
            "average_query_time": {"change_percent": 12.0},
        }
        assessment = self.exporter._assess_performance_change(changes)
        assert assessment == "significant_regression"

        # No significant change
        changes = {
            "total_execution_time": {"change_percent": 2.0},
            "average_query_time": {"change_percent": 1.0},
        }
        assessment = self.exporter._assess_performance_change(changes)
        assert assessment == "no_significant_change"

        # No data
        assessment = self.exporter._assess_performance_change({})
        assert assessment == "no_data"


class TestResultExporterErrorHandling:
    """Test error handling in result exporter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.exporter = ResultExporter(output_dir=Path(self.temp_dir), anonymize=False)

    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("benchbox.cli.output.console")
    def test_export_invalid_format(self, mock_console):
        """Test export with invalid format."""
        result = make_benchmark_results(
            benchmark_name="Test",
            scale_factor=1.0,
            execution_id="exec_1",
            duration_seconds=1.0,
            validation_status="PASSED",
        )

        exported = self.exporter.export_result(result, formats=["invalid_format"])

        # Should not include the invalid format
        assert "invalid_format" not in exported

        # Should print warning message
        assert mock_console.print.called
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Unknown export format" in call for call in calls)

    @pytest.mark.skipif(sys.platform == "win32", reason="Path handling differs on Windows")
    def test_export_with_invalid_output_dir(self):
        """Test export with invalid output directory."""
        with pytest.raises(FileNotFoundError):
            ResultExporter(output_dir=Path("/invalid/path/that/cannot/be/created"))

    def test_list_results_with_corrupted_json(self):
        """Test listing results with corrupted JSON files."""
        # Create a corrupted JSON file
        corrupted_file = Path(self.temp_dir) / "corrupted.json"
        with open(corrupted_file, "w") as f:
            f.write("{ invalid json content")

        # The exporter uses logger.debug, not console.print
        results = self.exporter.list_results()

        # Should return empty list (corrupted file is skipped)
        assert results == []


if __name__ == "__main__":
    pytest.main([__file__])
