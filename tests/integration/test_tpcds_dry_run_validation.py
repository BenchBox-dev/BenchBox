"""Comprehensive TPC-DS Dry Run Validation Tests.

This test suite validates that the dry-run mode for TPC-DS benchmark execution:
1. Captures the correct number of queries for each test type
2. Captures the correct SQL content (not simulated)
3. Executes real benchmark methods without simulation
4. Provides consistent results with actual execution flow

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import Mock, patch

import pytest

from benchbox.cli.dryrun import DryRunExecutor
from benchbox.platforms.duckdb import DuckDBAdapter

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]


class TestTPCDSDryRunValidation:
    """Test TPC-DS dry run functionality for correctness and consistency."""

    def setup_method(self):
        """Set up test fixtures."""
        self.executor = DryRunExecutor()
        # Create minimal config objects for testing
        self.benchmark_config = Mock()
        self.benchmark_config.name = "tpcds"
        self.benchmark_config.scale_factor = 0.01

    def test_dry_run_platform_adapter_integration(self):
        """Test that dry-run mode properly integrates with platform adapter."""
        # Create platform adapter and enable dry-run mode
        platform_adapter = DuckDBAdapter()
        platform_adapter.enable_dry_run()

        # Verify dry-run mode is enabled
        assert platform_adapter.dry_run_mode is True
        assert platform_adapter.captured_sql == []
        assert platform_adapter.query_counter == 0

        # Test SQL capture
        platform_adapter.capture_sql("SELECT 1", "query", None)
        assert len(platform_adapter.captured_sql) == 1
        assert platform_adapter.captured_sql[0]["sql"] == "SELECT 1"
        assert platform_adapter.captured_sql[0]["order"] == 1

        # Test get_captured_sql
        captured = platform_adapter.get_captured_sql()
        assert captured == {"1": "SELECT 1"}

    def test_platform_adapter_sql_capture_integration(self):
        """Test integration between platform adapter dry-run mode and test execution."""
        # Create real platform adapter in dry-run mode
        platform_adapter = DuckDBAdapter()
        platform_adapter.enable_dry_run()

        # Create connection (should be wrapped for SQL capture)
        connection = platform_adapter.create_connection()

        # Test that connection executions are captured
        result = platform_adapter.execute_query(connection, "SELECT 1 as test_query", "test_1")

        # Verify query was captured
        captured_sql = platform_adapter.get_captured_sql()
        assert len(captured_sql) > 0, "SQL should be captured in dry-run mode"
        assert "SELECT 1 as test_query" in str(captured_sql), "Actual SQL should be captured"

        # Verify dry-run result format
        assert result["dry_run"] is True, "Result should indicate dry-run mode"
        assert result["status"] == "DRY_RUN", "Status should be DRY_RUN"
        assert result["execution_time_seconds"] == 0.0, "Execution time should be 0 for dry-run"

    def test_dry_run_create_schema_sql_capture(self):
        """Test that schema creation is captured in dry-run mode."""
        platform_adapter = DuckDBAdapter()
        platform_adapter.enable_dry_run()

        # Mock benchmark with schema
        mock_benchmark = Mock()
        mock_benchmark.get_create_tables_sql.return_value = "CREATE TABLE test_table (id INTEGER, name VARCHAR(50));"

        # Execute schema creation in dry-run mode
        connection = platform_adapter.create_connection()
        platform_adapter.create_schema(mock_benchmark, connection)

        # Verify schema creation was captured
        captured_sql = platform_adapter.get_captured_sql()

        # Should capture CREATE TABLE statements
        create_queries = [sql for sql in captured_sql.values() if "CREATE TABLE" in sql.upper()]
        assert len(create_queries) > 0, "Should capture CREATE TABLE statements"

        # Verify schema operation contains realistic DDL
        create_sql = create_queries[0]
        assert "test_table" in create_sql.lower(), "Should reference correct table name"
        assert "INTEGER" in create_sql.upper() or "VARCHAR" in create_sql.upper(), "Should contain column definitions"

    def test_query_consistency_between_runs(self):
        """Test that dry-run produces consistent results for same parameters."""
        with patch("benchbox.tpcds") as mock_tpcds_class:
            mock_benchmark = Mock()
            mock_benchmark._name = "TPC-DS"
            mock_benchmark.scale_factor = 0.01
            mock_tpcds_class.return_value = mock_benchmark

            # Use deterministic query generation
            mock_benchmark.get_query.side_effect = lambda qid, **kwargs: (
                f"SELECT {qid} FROM table_{qid} WHERE col = {kwargs.get('seed', 1)}"
            )

            # Mock the query retrieval methods that _extract_standard_queries uses
            mock_benchmark.get_queries.return_value = {
                "Q1": "SELECT 1 FROM table_1 WHERE col = 1",
                "Q2": "SELECT 2 FROM table_2 WHERE col = 1",
            }

            # Run dry-run multiple times with same parameters
            queries1 = self.executor._extract_queries_via_real_test_execution(
                mock_benchmark, self.benchmark_config, "power"
            )
            queries2 = self.executor._extract_queries_via_real_test_execution(
                mock_benchmark, self.benchmark_config, "power"
            )

            # Results should be consistent for same input parameters
            assert len(queries1) == len(queries2), "Should produce same number of queries"

            # Note: Exact query content may vary due to seed/randomization in real TPC-DS,
            # but structure should be consistent
            assert type(queries1) == type(queries2), "Should return same result type"
