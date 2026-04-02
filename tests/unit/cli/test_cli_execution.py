"""Unit tests for CLI execution module.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import Mock, patch

import pytest
from rich.console import Console

from benchbox.cli.execution import BenchmarkExecutor
from benchbox.core.schemas import BenchmarkConfig, QueryResult
from benchbox.utils.printing import quiet_console
from tests.fixtures.result_dict_fixtures import make_benchmark_results

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.mark.unit
class TestBenchmarkExecutor:
    """Test BenchmarkExecutor class."""

    def test_executor_creation_default_console(self):
        """Test executor creation with default console."""
        executor = BenchmarkExecutor()

        assert executor.console is quiet_console
        assert executor.engine is not None
        assert executor.display is not None
        assert executor.current_execution is None
        assert executor._stop_requested is False

    def test_executor_creation_custom_console(self):
        """Test executor creation with custom console."""
        mock_console = Mock(spec=Console)
        executor = BenchmarkExecutor(console=mock_console)

        assert executor.console == mock_console
        assert executor.engine is not None
        assert executor.display is not None
        assert executor.current_execution is None
        assert executor._stop_requested is False

    def test_stop_execution(self):
        """Test stop execution functionality."""
        executor = BenchmarkExecutor()
        assert executor._stop_requested is False

        executor.stop_execution()
        assert executor._stop_requested is True


@pytest.mark.unit
class TestBenchmarkExecutorExecution:
    """Test benchmark execution functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_console = Mock(spec=Console)
        self.executor = BenchmarkExecutor(console=self.mock_console)

        # Mock benchmark config
        self.benchmark_config = BenchmarkConfig(
            name="tpch",
            display_name="TPC-H",
            scale_factor=0.01,
            queries=["q1", "q2"],
            concurrency=1,
            options={"estimated_time": "5 minutes"},
        )

        # Mock database config
        self.database_config = Mock()
        self.database_config.name = "test_db"
        self.database_config.type = "duckdb"
        self.database_config.options = {}
        self.database_config.connection_params = {}
        self.database_config.connection_string = None  # Avoid Mock 'in' operator issues

        # Mock system profile
        self.system_profile = Mock()

    @patch("benchbox.cli.execution.console")
    def test_execute_benchmark_success(self, mock_global_console):
        """Test successful benchmark execution."""
        # Mock orchestrator result
        mock_result = make_benchmark_results(
            benchmark_id="tpch_test",
            benchmark_name="TPC-H",
            execution_id="exec_123",
            duration_seconds=10.5,
            validation_status="PASSED",
            total_queries=2,
            successful_queries=2,
            query_results=[
                QueryResult(
                    query_id="q1",
                    query_name="Query 1",
                    sql_text="SELECT 1",
                    execution_time_ms=100.0,
                    rows_returned=1,
                    status="SUCCESS",
                ),
                QueryResult(
                    query_id="q2",
                    query_name="Query 2",
                    sql_text="SELECT 2",
                    execution_time_ms=200.0,
                    rows_returned=1,
                    status="SUCCESS",
                ),
            ],
        )
        mock_result.summary_metrics = {
            "total_queries": 2,
            "successful_queries": 2,
            "success_rate": 1.0,
            "avg_time_ms": 150.0,
        }

        self.executor.engine.execute_benchmark = Mock(return_value=mock_result)

        # Execute
        result = self.executor.execute_benchmark(self.benchmark_config, self.database_config, self.system_profile)

        # Verify result - adapt to actual execution pipeline behavior
        assert result.benchmark_name == "TPC-H"
        assert result.validation_status == "PASSED"

        # Verify engine was called correctly
        self.executor.engine.execute_benchmark.assert_called_once_with(
            benchmark_config=self.benchmark_config,
            database_config=self.database_config,
            system_profile=self.system_profile,
        )

    def test_execute_benchmark_keyboard_interrupt(self):
        """Test benchmark execution interrupted by user."""
        # Mock pipeline engine to raise KeyboardInterrupt
        self.executor.engine.pipeline.execute = Mock(side_effect=KeyboardInterrupt())

        # Execute
        result = self.executor.execute_benchmark(self.benchmark_config, self.database_config, self.system_profile)

        # Verify result
        assert result.benchmark_id == "tpch"
        assert result.benchmark_name == "TPC-H"
        assert result.validation_status == "INTERRUPTED"

    def test_execute_benchmark_exception(self):
        """Test benchmark execution with exception."""
        # Mock pipeline engine to raise exception
        test_error = Exception("Test execution error")
        self.executor.engine.pipeline.execute = Mock(side_effect=test_error)

        # Execute
        result = self.executor.execute_benchmark(self.benchmark_config, self.database_config, self.system_profile)

        # Verify result
        assert result.benchmark_id == "tpch"
        assert result.benchmark_name == "TPC-H"
        assert result.validation_status == "FAILED"
        assert result.validation_details == {"error": "Test execution error"}


@pytest.mark.unit
class TestBenchmarkExecutorDisplayInfo:
    """Test display execution info functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_console = Mock(spec=Console)
        self.executor = BenchmarkExecutor(console=self.mock_console)

        # Mock database config
        self.database_config = Mock()
        self.database_config.name = "test_database"

    @patch("benchbox.cli.execution.console")
    @patch("benchbox.cli.execution.Table")
    def test_display_execution_info_basic(self, mock_table_class, mock_global_console):
        """Test display execution info with basic config."""
        mock_table = Mock()
        mock_table_class.return_value = mock_table

        benchmark_config = BenchmarkConfig(
            name="ssb",
            display_name="Star Schema Benchmark",
            scale_factor=1.0,
            options={},
        )

        self.executor._display_execution_info(benchmark_config, self.database_config)

        # Verify table creation and setup
        mock_table_class.assert_called_once_with(title="Execution Configuration")
        mock_table.add_column.assert_any_call("Setting", style="cyan")
        mock_table.add_column.assert_any_call("Value", style="green")

        # Verify basic rows were added
        mock_table.add_row.assert_any_call("Benchmark", "Star Schema Benchmark")
        mock_table.add_row.assert_any_call("Database", "test_database")
        mock_table.add_row.assert_any_call("Scale Factor", "1.0")
        mock_table.add_row.assert_any_call("Estimated Time", "Unknown")

        # Verify table was printed
        mock_global_console.print.assert_any_call(mock_table)

    @patch("benchbox.cli.execution.console")
    @patch("benchbox.cli.execution.Table")
    def test_display_execution_info_with_queries(self, mock_table_class, mock_global_console):
        """Test display execution info with query subset."""
        mock_table = Mock()
        mock_table_class.return_value = mock_table

        benchmark_config = BenchmarkConfig(
            name="tpch",
            display_name="TPC-H",
            scale_factor=0.1,
            queries=["q1", "q2", "q3", "q4"],
            options={"estimated_time": "10 minutes"},
        )

        self.executor._display_execution_info(benchmark_config, self.database_config)

        # Verify query subset row was added
        mock_table.add_row.assert_any_call("Query Subset", "4 queries")
        mock_table.add_row.assert_any_call("Estimated Time", "10 minutes")

    @patch("benchbox.cli.execution.console")
    @patch("benchbox.cli.execution.Table")
    def test_display_execution_info_with_concurrency(self, mock_table_class, mock_global_console):
        """Test display execution info with concurrency."""
        mock_table = Mock()
        mock_table_class.return_value = mock_table

        benchmark_config = BenchmarkConfig(
            name="tpcds",
            display_name="TPC-DS",
            scale_factor=10.0,
            concurrency=8,
            options={"estimated_time": "2 hours"},
        )

        self.executor._display_execution_info(benchmark_config, self.database_config)

        # Verify concurrency row was added
        mock_table.add_row.assert_any_call("Concurrency", "8 streams")


@pytest.mark.unit
class TestBenchmarkExecutorDisplayResults:
    """Test display results summary functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_console = Mock(spec=Console)
        self.executor = BenchmarkExecutor(console=self.mock_console)

    @patch("benchbox.cli.execution.console")
    @patch("benchbox.cli.execution.Panel")
    @patch("benchbox.cli.execution.Table")
    def test_display_results_summary_basic(self, mock_table_class, mock_panel, mock_global_console):
        """Test display results summary with basic result."""
        mock_table = Mock()
        mock_table_class.return_value = mock_table
        mock_panel.fit.return_value = "mocked_panel"

        result = make_benchmark_results(
            benchmark_id="test_001",
            benchmark_name="Test Benchmark",
            execution_id="exec_456",
            duration_seconds=25.75,
            validation_status="COMPLETED",
        )

        self.executor._display_results_summary(result)

        # Verify panel creation
        mock_panel.fit.assert_called_once_with("[bold green]Benchmark Execution Complete[/bold green]", style="green")

        # Verify table creation
        mock_table_class.assert_called_once_with(title="Execution Summary")
        mock_table.add_column.assert_any_call("Metric", style="cyan")
        mock_table.add_column.assert_any_call("Value", style="green")

        # Verify basic rows
        mock_table.add_row.assert_any_call("Benchmark", "Test Benchmark")
        mock_table.add_row.assert_any_call("Execution ID", "exec_456")
        mock_table.add_row.assert_any_call("Duration", "25.75 seconds")
        mock_table.add_row.assert_any_call("Status", "COMPLETED")

        # Verify output
        mock_global_console.print.assert_any_call("\n" + "=" * 60)
        mock_global_console.print.assert_any_call("mocked_panel")
        mock_global_console.print.assert_any_call(mock_table)

    @patch("benchbox.cli.execution.console")
    @patch("benchbox.cli.execution.Panel")
    @patch("benchbox.cli.execution.Table")
    def test_display_results_summary_with_metrics(self, mock_table_class, mock_panel, mock_global_console):
        """Test display results summary with summary metrics."""
        mock_summary_table = Mock()
        mock_table_class.return_value = mock_summary_table

        result = make_benchmark_results(
            benchmark_id="test_002",
            benchmark_name="Test Benchmark with Metrics",
            execution_id="exec_789",
            duration_seconds=45.25,
            validation_status="PASSED",
        )
        result.summary_metrics = {
            "total_queries": 5.0,
            "successful_queries": 4.0,
            "success_rate": 0.8,
            "avg_time_ms": 250.5,
        }

        self.executor._display_results_summary(result)

        # Verify metrics rows were added
        mock_summary_table.add_row.assert_any_call("Total Queries", "5")
        mock_summary_table.add_row.assert_any_call("Successful", "4")
        mock_summary_table.add_row.assert_any_call("Success Rate", "80.0%")
        mock_summary_table.add_row.assert_any_call("Avg Query Time", "250.50 ms")

    @patch("benchbox.cli.execution.console")
    @patch("benchbox.cli.execution.Panel")
    @patch("benchbox.cli.execution.Table")
    def test_display_results_summary_with_query_results(self, mock_table_class, mock_panel, mock_global_console):
        """Test display results summary with query results."""
        # Mock table creation - first call for summary table, second for performance table
        mock_summary_table = Mock()
        mock_perf_table = Mock()
        mock_table_class.side_effect = [mock_summary_table, mock_perf_table]

        query_results = [
            QueryResult(
                query_id="q1",
                query_name="Query 1",
                sql_text="SELECT 1",
                execution_time_ms=100.25,
                rows_returned=1,
                status="SUCCESS",
            ),
            QueryResult(
                query_id="q2",
                query_name="Query 2",
                sql_text="SELECT 2",
                execution_time_ms=200.75,
                rows_returned=1,
                status="SUCCESS",
            ),
            QueryResult(
                query_id="q3",
                query_name="Query 3",
                sql_text="SELECT 3",
                execution_time_ms=150.50,
                rows_returned=0,
                status="ERROR",
            ),
        ]

        result = make_benchmark_results(
            benchmark_id="test_003",
            benchmark_name="Test Benchmark with Query Results",
            execution_id="exec_999",
            duration_seconds=60.0,
            validation_status="PARTIAL",
            query_results=query_results,
        )

        self.executor._display_results_summary(result)

        # Verify performance table creation (second call)
        assert mock_table_class.call_count == 2
        mock_perf_table.add_column.assert_any_call("Query", style="cyan")
        mock_perf_table.add_column.assert_any_call("Time (ms)", style="yellow", justify="right")
        mock_perf_table.add_column.assert_any_call("Status", style="blue")

        # Verify query result rows were added
        mock_perf_table.add_row.assert_any_call("q1", "100.25", "✅")
        mock_perf_table.add_row.assert_any_call("q2", "200.75", "✅")
        mock_perf_table.add_row.assert_any_call("q3", "150.50", "❌")

        # Verify query results header and table were printed
        mock_global_console.print.assert_any_call("\n[bold]Query Results:[/bold]")
        mock_global_console.print.assert_any_call(mock_perf_table)

    @patch("benchbox.cli.execution.console")
    @patch("benchbox.cli.execution.Panel")
    @patch("benchbox.cli.execution.Table")
    def test_display_results_summary_single_query_no_table(self, mock_table_class, mock_panel, mock_global_console):
        """Test display results summary with single query (no performance table)."""
        mock_summary_table = Mock()
        mock_table_class.return_value = mock_summary_table

        # Single query result should not show performance table
        query_results = [
            QueryResult(
                query_id="q1",
                query_name="Query 1",
                sql_text="SELECT 1",
                execution_time_ms=100.0,
                rows_returned=1,
                status="SUCCESS",
            )
        ]

        result = make_benchmark_results(
            benchmark_id="test_004",
            benchmark_name="Single Query Test",
            query_results=query_results,
        )

        self.executor._display_results_summary(result)

        # Verify only summary table was created (not performance table)
        assert mock_table_class.call_count == 1

        # Verify query results header was NOT printed
        calls = [call[0] for call in mock_global_console.print.call_args_list]
        query_header_calls = [call for call in calls if call and "[bold]Query Results:[/bold]" in str(call[0])]
        assert len(query_header_calls) == 0


@pytest.mark.unit
class TestBenchmarkExecutorIntegration:
    """Test integration scenarios for BenchmarkExecutor."""

    def test_executor_workflow_complete(self):
        """Test complete executor workflow with mocked components."""
        mock_console = Mock(spec=Console)
        executor = BenchmarkExecutor(console=mock_console)

        # Mock successful execution
        mock_result = make_benchmark_results(
            benchmark_id="integration_test",
            benchmark_name="Integration Test",
            validation_status="PASSED",
        )
        executor.engine.execute_benchmark = Mock(return_value=mock_result)

        # Create test config
        config = BenchmarkConfig(name="test", display_name="Test Benchmark")
        db_config = Mock()
        db_config.name = "test_db"
        db_config.type = "duckdb"
        db_config.options = {}
        db_config.connection_params = {}
        db_config.connection_string = None  # Avoid Mock 'in' operator issues
        system_profile = Mock()

        # Execute
        result = executor.execute_benchmark(config, db_config, system_profile)

        # Verify result
        assert result == mock_result
        assert executor._stop_requested is False  # Should not be set for normal execution

        # Verify orchestrator was called
        executor.engine.execute_benchmark.assert_called_once_with(
            benchmark_config=config,
            database_config=db_config,
            system_profile=system_profile,
        )

    def test_executor_stop_functionality(self):
        """Test executor stop functionality."""
        executor = BenchmarkExecutor()

        # Initially not stopped
        assert executor._stop_requested is False

        # Stop execution
        executor.stop_execution()
        assert executor._stop_requested is True

        # Stop again (should remain True)
        executor.stop_execution()
        assert executor._stop_requested is True


@pytest.mark.unit
class TestBenchmarkExecutorEdgeCases:
    """Test edge cases and error conditions."""

    def test_display_info_with_none_queries(self):
        """Test display info when queries is None."""
        executor = BenchmarkExecutor()

        config = BenchmarkConfig(
            name="test",
            display_name="Test",
            queries=None,  # Explicitly None
        )
        db_config = Mock()
        db_config.name = "test_db"

        with patch("benchbox.cli.execution.console"), patch("benchbox.cli.execution.Table") as mock_table_class:
            mock_table = Mock()
            mock_table_class.return_value = mock_table

            # Should not raise exception
            executor._display_execution_info(config, db_config)

            # Should not add query subset row
            calls = mock_table.add_row.call_args_list
            query_subset_calls = [call for call in calls if call[0][0] == "Query Subset"]
            assert len(query_subset_calls) == 0

    def test_display_results_with_empty_metrics(self):
        """Test display results with empty summary metrics."""
        executor = BenchmarkExecutor()

        result = make_benchmark_results(
            benchmark_id="empty_test",
            benchmark_name="Empty Test",
        )
        result.summary_metrics = {}

        with patch("benchbox.cli.execution.console"), patch("benchbox.cli.execution.Table") as mock_table_class:
            with patch("benchbox.cli.execution.Panel"):
                mock_table = Mock()
                mock_table_class.return_value = mock_table

                # Should not raise exception
                executor._display_results_summary(result)

                # Should not add metrics rows
                calls = mock_table.add_row.call_args_list
                metrics_calls = [
                    call for call in calls if call[0][0] in ["Total Queries", "Successful", "Success Rate"]
                ]
                assert metrics_calls == []

    def test_display_results_with_zero_avg_time(self):
        """Test display results with zero average time."""
        executor = BenchmarkExecutor()

        result = make_benchmark_results(
            benchmark_id="zero_time_test",
            benchmark_name="Zero Time Test",
        )
        result.summary_metrics = {
            "total_queries": 1.0,
            "successful_queries": 1.0,
            "success_rate": 1.0,
            "avg_time_ms": 0.0,
        }

        with patch("benchbox.cli.execution.console"), patch("benchbox.cli.execution.Table") as mock_table_class:
            with patch("benchbox.cli.execution.Panel"):
                mock_table = Mock()
                mock_table_class.return_value = mock_table

                executor._display_results_summary(result)

                # Should not add average time row when avg_time_ms is 0
                calls = mock_table.add_row.call_args_list
                avg_time_calls = [call for call in calls if call[0][0] == "Avg Query Time"]
                assert len(avg_time_calls) == 0

    def test_config_with_concurrency_one(self):
        """Test config with concurrency = 1 (should not show concurrency row)."""
        executor = BenchmarkExecutor()

        config = BenchmarkConfig(
            name="test",
            display_name="Test",
            concurrency=1,  # Default concurrency
        )
        db_config = Mock()
        db_config.name = "test_db"

        with patch("benchbox.cli.execution.console"), patch("benchbox.cli.execution.Table") as mock_table_class:
            mock_table = Mock()
            mock_table_class.return_value = mock_table

            executor._display_execution_info(config, db_config)

            # Should not add concurrency row when concurrency <= 1
            calls = mock_table.add_row.call_args_list
            concurrency_calls = [call for call in calls if call[0][0] == "Concurrency"]
            assert len(concurrency_calls) == 0


@pytest.mark.unit
class TestBenchmarkExecutorResultCreation:
    """Test minimal result creation edge cases."""

    def test_update_cached_benchmark_instance_no_getter(self):
        """Test cache update when engine has no get_benchmark_instance."""
        executor = BenchmarkExecutor()
        # Mock engine with no getter
        executor.engine = Mock(spec=[])

        executor._update_cached_benchmark_instance()

        # Should gracefully handle missing getter
        assert executor._benchmark_instance is None

    def test_build_minimal_result_with_benchmark_create_method(self):
        """Test minimal result when benchmark instance has create_minimal_benchmark_result."""
        executor = BenchmarkExecutor()
        mock_benchmark = Mock()
        mock_result = make_benchmark_results(validation_status="INTERRUPTED")
        mock_benchmark.create_minimal_benchmark_result.return_value = mock_result

        # Mock the engine's get_benchmark_instance to return our mock
        with patch.object(executor.engine, "get_benchmark_instance", return_value=mock_benchmark):
            result = executor._build_minimal_result(
                benchmark_config=Mock(name="tpch", display_name="TPC-H", scale_factor=0.01),
                database_config=Mock(type="duckdb"),
                system_profile=Mock(),
                validation_status="INTERRUPTED",
            )

        assert result.validation_status == "INTERRUPTED"
        mock_benchmark.create_minimal_benchmark_result.assert_called_once()

    def test_build_minimal_result_fallback_no_benchmark_instance(self):
        """Test fallback result creation when benchmark instance is None."""
        executor = BenchmarkExecutor()

        # Mock engine to have no get_benchmark_instance
        executor.engine = Mock(spec=[])

        # Use a real benchmark config object
        from benchbox.core.schemas import BenchmarkConfig

        config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=0.01)

        result = executor._build_minimal_result(
            benchmark_config=config,
            database_config=Mock(type="duckdb"),
            system_profile=Mock(),
            validation_status="FAILED",
            validation_details={"error": "Test error"},
        )

        assert result.benchmark_name == "TPC-H"
        assert result.validation_status == "FAILED"
        assert result.scale_factor == 0.01
        assert hasattr(result, "_benchmark_id_override")
        assert result._benchmark_id_override == "tpch"

    def test_execution_caches_benchmark_instance(self):
        """Test that successful execution updates cached benchmark instance."""
        executor = BenchmarkExecutor()
        result = make_benchmark_results(validation_status="PASSED")

        with patch.object(executor.engine, "execute_benchmark", return_value=result):
            with patch.object(executor.engine, "get_benchmark_instance", return_value=Mock()):
                with patch("benchbox.cli.execution.quiet_console.print"):
                    executor.execute_benchmark(
                        benchmark_config=Mock(name="tpch", display_name="TPC-H", scale_factor=0.01),
                        database_config=Mock(name="test_db", type="duckdb"),
                        system_profile=Mock(),
                    )

        assert executor._benchmark_instance is not None
        assert isinstance(executor._benchmark_instance, Mock)

    def test_display_execution_info_with_queries_subset(self):
        """Test display when queries attribute exists."""
        executor = BenchmarkExecutor()
        config = BenchmarkConfig(name="tpch", display_name="TPC-H", queries=["Q1", "Q6", "Q17"], scale_factor=0.01)
        db_config = Mock(name="test_db")

        with patch("benchbox.cli.execution.console.print") as mock_print:
            executor._display_execution_info(config, db_config)
            mock_print.assert_called()

    def test_display_execution_info_with_high_concurrency(self):
        """Test display with concurrency > 1."""
        executor = BenchmarkExecutor()
        config = BenchmarkConfig(name="tpch", display_name="TPC-H", concurrency=4, scale_factor=0.01)
        db_config = Mock(name="test_db")

        with patch("benchbox.cli.execution.console.print") as mock_print:
            executor._display_execution_info(config, db_config)
            mock_print.assert_called()
