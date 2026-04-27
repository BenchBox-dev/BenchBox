"""Test dry run real test method execution using platform adapters.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import Mock, patch

import pytest

from benchbox.cli.dryrun import DryRunExecutor
from benchbox.platforms.duckdb import DuckDBAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestPlatformAdapterDryRun:
    """Test platform adapter dry-run SQL capture functionality."""

    def test_platform_adapter_dry_run_mode_activation(self):
        """Test that platform adapter dry-run mode can be activated."""
        adapter = DuckDBAdapter()

        # Initially not in dry-run mode
        assert adapter.dry_run_mode is False
        assert adapter.captured_sql == []

        # Enable dry-run mode
        adapter.enable_dry_run()
        assert adapter.dry_run_mode is True
        assert adapter.captured_sql == []
        assert adapter.query_counter == 0

    def test_platform_adapter_sql_capture(self):
        """Test that platform adapter captures SQL in dry-run mode."""
        adapter = DuckDBAdapter()
        adapter.enable_dry_run()

        # Capture some SQL
        adapter.capture_sql("SELECT * FROM table1", "query", None)
        adapter.capture_sql("SELECT * FROM table2", "query", None)

        # Check SQL was captured
        assert len(adapter.captured_sql) == 2
        assert adapter.captured_sql[0]["sql"] == "SELECT * FROM table1"
        assert adapter.captured_sql[1]["sql"] == "SELECT * FROM table2"
        assert adapter.captured_sql[0]["order"] == 1
        assert adapter.captured_sql[1]["order"] == 2

    def test_get_captured_sql_dict(self):
        """Test captured SQL dictionary generation."""
        adapter = DuckDBAdapter()
        adapter.enable_dry_run()

        adapter.capture_sql("SELECT 1", "query")
        adapter.capture_sql("SELECT 2", "query")

        queries_dict = adapter.get_captured_sql()
        assert queries_dict == {"1": "SELECT 1", "2": "SELECT 2"}

    def test_connection_wrapper_sql_interception(self):
        """Test that connection wrapper intercepts and captures SQL."""
        adapter = DuckDBAdapter()
        adapter.enable_dry_run()

        # Create wrapped connection
        connection = adapter.create_connection()

        # Execute query through connection - should be captured
        result = connection.execute("SELECT 42 as test")

        # Verify SQL was captured
        captured = adapter.get_captured_sql()
        assert len(captured) > 0
        assert "SELECT 42 as test" in str(captured.values())

        # Verify dry-run cursor behavior
        assert result.fetchall() == []
        assert result.fetchone() is None


class TestDryRunExecutor:
    """Test DryRunExecutor with platform adapter integration."""

    @patch("benchbox.cli.orchestrator.BenchmarkOrchestrator")
    def test_extract_queries_load_only_returns_empty(self, mock_orchestrator):
        """Test that load-only mode returns empty queries."""
        executor = DryRunExecutor()

        # Create mock benchmark config with load_only
        benchmark_config = Mock()
        benchmark_config.test_execution_type = "load_only"

        # Create mock benchmark
        mock_benchmark = Mock()

        result = executor._extract_queries(mock_benchmark, benchmark_config)
        assert result == {}

    @patch("benchbox.cli.orchestrator.BenchmarkOrchestrator")
    def test_extract_queries_standard_fallback(self, mock_orchestrator):
        """Test fallback to standard query extraction."""
        executor = DryRunExecutor()

        # Create mock benchmark config with standard execution
        benchmark_config = Mock()
        benchmark_config.name = "test_benchmark"
        benchmark_config.test_execution_type = "standard"

        # Create mock benchmark with standard queries
        mock_benchmark = Mock()
        mock_benchmark.get_queries.return_value = {"1": "SELECT 1", "2": "SELECT 2"}

        result = executor._extract_queries(mock_benchmark, benchmark_config)
        assert result == {"1": "SELECT 1", "2": "SELECT 2"}

    def test_extract_queries_via_real_test_execution_integration(self):
        """Test real test execution integration with platform adapter."""
        executor = DryRunExecutor()

        # Create mock benchmark config
        benchmark_config = Mock()
        benchmark_config.name = "tpcds"
        benchmark_config.scale_factor = 0.01

        # Create mock benchmark
        mock_benchmark = Mock()
        mock_benchmark.get_query.return_value = "SELECT 1 as test_query"

        # Test should use platform adapter approach
        with patch.object(executor, "_execute_tpcds_test_class") as mock_execute:
            mock_execute.return_value = {"1": "SELECT 1 as captured_query"}

            result = executor._extract_queries_via_real_test_execution(mock_benchmark, benchmark_config, "power")

            # Verify platform adapter was used
            assert result == {"1": "SELECT 1 as captured_query"}
            mock_execute.assert_called_once()


class TestDryRunExecutorPlatformIntegration:
    """Test DryRunExecutor integration with platform adapters."""

    def test_extract_queries_with_platform_adapter(self):
        """Test query extraction with platform adapter translation."""
        executor = DryRunExecutor()

        # Create mock benchmark
        mock_benchmark = Mock()
        mock_benchmark.get_queries.return_value = {"1": "SELECT 1"}

        # Create mock platform adapter
        mock_adapter = Mock()
        mock_adapter.translate_sql.return_value = "SELECT 1 /* translated */"

        # Create mock benchmark config
        benchmark_config = Mock()
        benchmark_config.name = "tpcds"
        benchmark_config.test_execution_type = "standard"

        result = executor._extract_queries(mock_benchmark, benchmark_config, mock_adapter)

        # Should return standard queries without translation (fallback mode)
        assert result == {"1": "SELECT 1"}

    def test_extract_queries_standard_without_platform_adapter(self):
        """Test standard query extraction without platform adapter."""
        executor = DryRunExecutor()

        # Create mock benchmark
        mock_benchmark = Mock()
        mock_benchmark.get_queries.return_value = {"1": "SELECT 1", "2": "SELECT 2"}

        # Create mock benchmark config
        benchmark_config = Mock()
        benchmark_config.name = "test_benchmark"
        benchmark_config.test_execution_type = "standard"

        result = executor._extract_queries(mock_benchmark, benchmark_config)
        assert result == {"1": "SELECT 1", "2": "SELECT 2"}

    def test_load_only_mode_returns_empty_with_platform_adapter(self):
        """Test that load-only mode returns empty even with platform adapter."""
        executor = DryRunExecutor()

        # Create mock benchmark config with load_only
        benchmark_config = Mock()
        benchmark_config.test_execution_type = "load_only"

        # Create mock benchmark and platform adapter
        mock_benchmark = Mock()
        mock_adapter = Mock()

        result = executor._extract_queries(mock_benchmark, benchmark_config, mock_adapter)
        assert result == {}
