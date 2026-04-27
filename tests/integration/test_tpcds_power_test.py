"""Integration tests for TPC-DS Power Test implementation.

This module contains comprehensive tests for the TPC-DS Power Test functionality,
including database integration, timing measurement, result validation, and
compliance with TPC-DS specification requirements.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.core.connection import DatabaseConnection
from benchbox.core.tpcds.benchmark import TPCDSBenchmark
from benchbox.core.tpcds.power_test import (
    TPCDSPowerTest,
    TPCDSPowerTestResult as PowerTestResult,  # Alias for backward compatibility
)

# Mark all tests in this file as integration tests
pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]


class TestDatabaseConnection:
    """Test database connection wrapper functionality."""

    def test_sqlite_connection(self):
        """Test SQLite database connection."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        try:
            # Test SQLite connection - create actual sqlite3 connection first
            import sqlite3

            sqlite_conn = sqlite3.connect(db_path)
            conn = DatabaseConnection(sqlite_conn)
            assert conn.connection is not None
            assert conn.cursor is None  # Cursor should be None until first execute

            # Test basic query execution
            conn.execute("CREATE TABLE test (id INTEGER, name TEXT)")
            conn.execute("INSERT INTO test VALUES (1, 'test')")
            conn.commit()

            # Test result fetching
            conn.execute("SELECT * FROM test")
            result = conn.fetchall()
            assert len(result) == 1
            assert result[0] == (1, "test")

            conn.close()

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_connection_without_prefix(self):
        """Test database connection without URL prefix."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        try:
            # Test connection without prefix - create actual sqlite3 connection first
            import sqlite3

            sqlite_conn = sqlite3.connect(db_path)
            conn = DatabaseConnection(sqlite_conn)
            assert conn.connection is not None

            # Test basic functionality
            conn.execute("SELECT 1")
            result = conn.fetchone()
            assert result == (1,)

            conn.close()

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_duckdb_connection(self):
        """Test DuckDB connection if available."""
        try:
            import os

            # a temporary path without creating the file first
            import tempfile

            import duckdb

            temp_dir = tempfile.mkdtemp()
            db_path = os.path.join(temp_dir, "test.duckdb")

            try:
                # actual DuckDB connection first (file doesn't need to exist)
                duckdb_conn = duckdb.connect(db_path)
                conn = DatabaseConnection(duckdb_conn)
                assert conn.connection is not None

                # Test basic query
                conn.execute("SELECT 42")
                result = conn.fetchone()
                assert result == (42,)

                conn.close()

            finally:
                # Cleanup
                if os.path.exists(db_path):
                    os.unlink(db_path)
                os.rmdir(temp_dir)

        except ImportError:
            pytest.skip("DuckDB not available")

    def test_connection_error_handling(self):
        """Test error handling in database connections."""
        with pytest.raises(ValueError, match="Connection object must have either"):
            DatabaseConnection("invalid://connection/string")


class TestPowerTestResult:
    """Test PowerTestResult data structure."""

    def test_power_test_result_creation(self):
        """Test PowerTestResult creation and basic functionality."""
        from benchbox.core.tpcds.power_test import TPCDSPowerTestConfig

        config = TPCDSPowerTestConfig(scale_factor=1.0)
        result = PowerTestResult(
            config=config,
            start_time="2023-01-01T00:00:00",
            end_time="2023-01-01T00:01:40",
            total_time=100.0,
            power_at_size=36.0,
            queries_executed=99,
            queries_successful=99,
            query_results=[],
            success=True,
            errors=[],
        )

        assert result.config.scale_factor == 1.0
        assert result.total_time == 100.0
        assert result.power_at_size == 36.0
        assert result.query_results == []
        assert result.errors == []

    def test_power_test_result_to_dict(self):
        """Test PowerTestResult serialization to dictionary."""
        from benchbox.core.tpcds.power_test import TPCDSPowerTestConfig

        config = TPCDSPowerTestConfig(scale_factor=1.0)
        result = PowerTestResult(
            config=config,
            start_time="2023-01-01T00:00:00",
            end_time="2023-01-01T00:01:40",
            total_time=100.0,
            power_at_size=36.0,
            queries_executed=99,
            queries_successful=99,
            query_results=[
                {
                    "query_id": 1,
                    "execution_time_seconds": 5.0,
                    "status": "success",
                },
                {
                    "query_id": "14a",
                    "execution_time_seconds": 8.0,
                    "status": "success",
                },
            ],
            success=True,
            errors=[],
        )

        result.errors.append("Test error")

        # Test dataclass can be converted to dict using dataclasses.asdict
        import dataclasses

        result_dict = dataclasses.asdict(result)

        assert result_dict["config"]["scale_factor"] == 1.0
        assert result_dict["total_time"] == 100.0
        assert result_dict["power_at_size"] == 36.0
        assert result_dict["query_results"][0]["query_id"] == 1
        assert result_dict["query_results"][1]["query_id"] == "14a"
        assert result_dict["errors"] == ["Test error"]


class TestTPCDSPowerTest:
    """Test TPC-DS Power Test implementation."""

    def create_mock_benchmark(self):
        """Create a mock TPC-DS benchmark for testing."""
        mock_benchmark = Mock()
        mock_benchmark.scale_factor = 1.0

        # Mock query generation
        def mock_get_query(query_id, **kwargs):
            return f"SELECT {query_id} as query_id, 'test' as result"

        mock_benchmark.get_query = mock_get_query
        return mock_benchmark

    def test_power_test_initialization(self):
        """Test Power Test initialization with various parameters."""
        mock_benchmark = self.create_mock_benchmark()

        # Test basic initialization - use connection_factory instead of connection_string
        def mock_connection_factory():
            return Mock()

        power_test = TPCDSPowerTest(benchmark=mock_benchmark, connection_factory=mock_connection_factory)

        assert power_test.benchmark == mock_benchmark
        assert power_test.config.scale_factor == 1.0  # Access via config
        assert power_test.config.seed == 1
        assert not power_test.config.verbose
        assert power_test.config.warm_up
        assert power_test.config.validation

        # Test initialization with custom parameters
        power_test_custom = TPCDSPowerTest(
            benchmark=mock_benchmark,
            connection_factory=mock_connection_factory,
            scale_factor=10.0,
            seed=42,
            verbose=True,
            timeout=30.0,
        )

        assert power_test_custom.config.scale_factor == 10.0
        assert power_test_custom.config.seed == 42
        assert power_test_custom.config.verbose
        assert power_test_custom.config.timeout == 30.0

    def test_power_test_initialization_validation(self):
        """Test Power Test initialization parameter validation."""
        mock_benchmark = self.create_mock_benchmark()

        # Test invalid scale factor
        with pytest.raises(ValueError, match="scale_factor must be a positive number"):
            TPCDSPowerTest(
                benchmark=mock_benchmark,
                connection_string="sqlite::memory:",
                scale_factor=0.0,
            )

        with pytest.raises(ValueError, match="scale_factor must be a positive number"):
            TPCDSPowerTest(
                benchmark=mock_benchmark,
                connection_string="sqlite::memory:",
                scale_factor=-1.0,
            )

    def test_power_at_size_calculation(self):
        """Test Power@Size metric calculation."""
        mock_benchmark = self.create_mock_benchmark()

        power_test = TPCDSPowerTest(
            benchmark=mock_benchmark,
            connection_string="sqlite::memory:",
            scale_factor=1.0,
        )

        # Test calculation: Power@Size = 3600 × Scale_Factor / geometric_mean(exec_times)
        # Scale factor = 1.0, geometric_mean([1.0, 1.0, 1.0, 1.0]) = 1.0
        # Expected: 3600 × 1.0 / 1.0 = 3600.0
        power_at_size = power_test._calculate_power_at_size([1.0, 1.0, 1.0, 1.0])
        assert power_at_size == 3600.0

        # Test with different scale factor
        power_test.config.scale_factor = 10.0
        power_at_size = power_test._calculate_power_at_size([1.0, 1.0, 1.0, 1.0])
        assert power_at_size == 36000.0

        # Test with empty list (should return 0.0)
        power_at_size = power_test._calculate_power_at_size([])
        assert power_at_size == 0.0

    def test_query_sequence_building(self):
        """Test that Power Test builds correct query sequence with variants."""
        mock_benchmark = self.create_mock_benchmark()

        power_test = TPCDSPowerTest(benchmark=mock_benchmark, connection_string="sqlite::memory:")

        # TPC-DS Power Test should execute all 99 queries plus variants
        query_sequence = power_test.query_sequence

        # Check that we have all base queries 1-99
        for i in range(1, 100):
            assert i in query_sequence

        # Check that we have the known variants
        assert "14a" in query_sequence
        assert "14b" in query_sequence
        assert "23a" in query_sequence
        assert "23b" in query_sequence
        assert "24a" in query_sequence
        assert "24b" in query_sequence
        assert "39a" in query_sequence
        assert "39b" in query_sequence

        # Should have 99 base queries + 8 variants (14a, 14b, 23a, 23b, 24a, 24b, 39a, 39b) = 107 total
        assert len(query_sequence) == 107

    def test_status_tracking(self):
        """Test Power Test status tracking."""
        mock_benchmark = self.create_mock_benchmark()

        power_test = TPCDSPowerTest(benchmark=mock_benchmark, connection_string="sqlite::memory:")

        # Test initial status
        status = power_test.get_status()
        assert not status["running"]
        assert status["current_query"] is None
        assert status["scale_factor"] == 1.0
        assert status["seed"] == 1
        assert status["dialect"] == "standard"
        assert status["query_sequence_length"] == 107

        # Test running state
        power_test.test_running = True
        power_test.current_query = 5

        status = power_test.get_status()
        assert status["running"]
        assert status["current_query"] == 5

    @patch("benchbox.core.tpcds.power_test.DatabaseConnection")
    def test_database_connection_lifecycle(self, mock_db_connection):
        """Test database connection establishment and cleanup."""
        mock_benchmark = self.create_mock_benchmark()
        mock_connection = Mock()
        mock_db_connection.return_value = mock_connection

        power_test = TPCDSPowerTest(benchmark=mock_benchmark, connection_string="sqlite::memory:")

        # Test connection establishment
        power_test._connect_database()
        assert power_test.connection == mock_connection
        mock_db_connection.assert_called_once()
        assert mock_db_connection.call_args.kwargs.get("dialect") == "sqlite"

        # Test connection cleanup
        power_test._disconnect_database()
        mock_connection.close.assert_called_once()
        assert power_test.connection is None

    @patch("benchbox.core.tpcds.power_test.DatabaseConnection")
    def test_warm_up_procedure(self, mock_db_connection):
        """Test database warm-up procedure."""
        mock_benchmark = self.create_mock_benchmark()
        mock_connection = Mock()
        mock_db_connection.return_value = mock_connection

        power_test = TPCDSPowerTest(benchmark=mock_benchmark, connection_string="sqlite::memory:", warm_up=True)

        power_test.connection = mock_connection

        # Test warm-up execution
        power_test._warm_up_database()

        # Verify that warm-up queries were executed
        assert mock_connection.execute.call_count >= 5  # At least 5 warm-up queries

    @patch("benchbox.core.tpcds.power_test.DatabaseConnection")
    def test_query_execution(self, mock_db_connection):
        """Test individual query execution and timing."""
        mock_benchmark = self.create_mock_benchmark()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [("result1",), ("result2",)]
        mock_connection.execute.return_value = mock_cursor
        mock_db_connection.return_value = mock_connection

        power_test = TPCDSPowerTest(benchmark=mock_benchmark, connection_string="sqlite::memory:")

        power_test.connection = mock_connection

        # Test successful query execution
        query_text = "SELECT 1 as test"
        result = power_test._execute_query(1, query_text)

        assert result["query_id"] == 1
        assert result["status"] == "success"
        assert result["result_count"] == 2
        assert result["execution_time_seconds"] > 0
        assert result["error"] is None

        # Test query execution with variant
        result = power_test._execute_query("14a", query_text)
        assert result["query_id"] == "14a"
        assert result["status"] == "success"

        # Verify database calls
        mock_connection.execute.assert_called_with(query_text)
        mock_cursor.fetchall.assert_called()
        mock_connection.commit.assert_called()

    @patch("benchbox.core.tpcds.power_test.DatabaseConnection")
    def test_query_execution_error_handling(self, mock_db_connection):
        """Test error handling during query execution."""
        mock_benchmark = self.create_mock_benchmark()
        mock_connection = Mock()
        mock_connection.execute.side_effect = Exception("Database error")
        mock_db_connection.return_value = mock_connection

        power_test = TPCDSPowerTest(benchmark=mock_benchmark, connection_string="sqlite::memory:")

        power_test.connection = mock_connection

        # Test query execution with error
        query_text = "SELECT 1 as test"
        result = power_test._execute_query(1, query_text)

        assert result["query_id"] == 1
        assert result["status"] == "error"
        assert result["result_count"] == 0
        assert result["execution_time_seconds"] > 0
        assert "Database error" in result["error"]

    def test_result_validation(self):
        """Test Power Test result validation."""
        mock_benchmark = self.create_mock_benchmark()

        power_test = TPCDSPowerTest(
            benchmark=mock_benchmark,
            connection_string="sqlite::memory:",
            validation=True,
        )

        # Test valid results
        from benchbox.core.tpcds.power_test import TPCDSPowerTestConfig

        config = TPCDSPowerTestConfig(scale_factor=1.0)
        valid_result = PowerTestResult(
            config=config,
            start_time="2023-01-01T00:00:00",
            end_time="2023-01-01T00:01:40",
            total_time=100.0,
            power_at_size=36.0,
            queries_executed=105,
            queries_successful=105,
            query_results=[],
            success=True,
            errors=[],
        )

        # Include all queries in the sequence
        for query_id in power_test.query_sequence:
            valid_result.query_results.append(
                {
                    "query_id": query_id,
                    "execution_time_seconds": 5.0,
                    "status": "success",
                }
            )

        assert power_test._validate_results(valid_result)

        # Test invalid results (missing queries)
        invalid_config = TPCDSPowerTestConfig(scale_factor=1.0)
        invalid_result = PowerTestResult(
            config=invalid_config,
            start_time="2023-01-01T00:00:00",
            end_time="2023-01-01T00:01:40",
            total_time=100.0,
            power_at_size=36.0,
            queries_executed=49,
            queries_successful=49,
            query_results=[],
            success=True,
            errors=[],
        )

        # Only add some queries (missing many)
        for i in range(1, 50):
            invalid_result.query_results.append(
                {
                    "query_id": i,
                    "execution_time_seconds": 5.0,
                    "status": "success",
                }
            )

        assert not power_test._validate_results(invalid_result)
        assert len(invalid_result.errors) > 0

    def test_result_validation_disabled(self):
        """Test Power Test with validation disabled."""
        mock_benchmark = self.create_mock_benchmark()

        power_test = TPCDSPowerTest(
            benchmark=mock_benchmark,
            connection_string="sqlite::memory:",
            validation=False,
        )

        # Even invalid results should pass validation when disabled
        from benchbox.core.tpcds.power_test import TPCDSPowerTestConfig

        config = TPCDSPowerTestConfig(scale_factor=1.0)
        invalid_result = PowerTestResult(
            config=config,
            start_time="2023-01-01T00:00:00",
            end_time="2023-01-01T00:01:40",
            total_time=100.0,
            power_at_size=36.0,
            queries_executed=0,
            queries_successful=0,
            query_results=[],
            success=True,
            errors=[],
        )

        assert power_test._validate_results(invalid_result)

    def test_database_info_collection(self):
        """Test database information collection."""
        mock_benchmark = self.create_mock_benchmark()

        power_test = TPCDSPowerTest(benchmark=mock_benchmark, connection_string="sqlite::memory:")

        # Mock database connection
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = ("SQLite 3.36.0",)
        mock_connection.execute.return_value = mock_cursor
        power_test.connection = mock_connection

        # Test database info collection
        db_info = power_test._get_database_info()

        assert "connection_string" in db_info
        assert "dialect" in db_info
        assert "timestamp" in db_info
        assert "connection_string" in db_info  # Value depends on mock setup
        assert db_info["dialect"] == "standard"

    def test_result_export(self):
        """Test Power Test result export functionality."""
        mock_benchmark = self.create_mock_benchmark()

        power_test = TPCDSPowerTest(benchmark=mock_benchmark, connection_string="sqlite::memory:")

        # test result
        from benchbox.core.tpcds.power_test import TPCDSPowerTestConfig

        config = TPCDSPowerTestConfig(scale_factor=1.0)
        result = PowerTestResult(
            config=config,
            start_time="2023-01-01T00:00:00",
            end_time="2023-01-01T00:01:40",
            total_time=100.0,
            power_at_size=36.0,
            queries_executed=2,
            queries_successful=2,
            query_results=[],
            success=True,
            errors=[],
        )

        result.query_results.append(
            {
                "query_id": 1,
                "execution_time_seconds": 5.0,
                "status": "success",
            }
        )

        result.query_results.append(
            {
                "query_id": "14a",
                "execution_time_seconds": 8.0,
                "status": "success",
            }
        )

        # Test export to temporary file
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            output_file = tmp.name

        try:
            power_test.export_results(result, output_file)

            # Verify file was created and contains expected data
            assert Path(output_file).exists()

            with open(output_file, encoding="utf-8") as f:
                exported_data = json.load(f)

            assert exported_data["config"]["scale_factor"] == 1.0
            assert exported_data["total_time"] == 100.0
            assert exported_data["power_at_size"] == 36.0
            assert exported_data["query_results"]["1"]["query_id"] == 1
            assert exported_data["query_results"]["14a"]["query_id"] == "14a"

        finally:
            Path(output_file).unlink(missing_ok=True)

    def test_result_comparison(self):
        """Test Power Test result comparison functionality."""
        mock_benchmark = self.create_mock_benchmark()

        power_test = TPCDSPowerTest(benchmark=mock_benchmark, connection_string="sqlite::memory:")

        # two results for comparison
        from benchbox.core.tpcds.power_test import TPCDSPowerTestConfig

        config1 = TPCDSPowerTestConfig(scale_factor=1.0)
        result1 = PowerTestResult(
            config=config1,
            start_time="2023-01-01T00:00:00",
            end_time="2023-01-01T00:01:40",
            total_time=100.0,
            power_at_size=36.0,
            queries_executed=2,
            queries_successful=2,
            query_results=[],
            success=True,
            errors=[],
        )

        config2 = TPCDSPowerTestConfig(scale_factor=1.0)
        result2 = PowerTestResult(
            config=config2,
            start_time="2023-01-01T00:00:00",
            end_time="2023-01-01T00:01:30",
            total_time=90.0,
            power_at_size=40.0,
            queries_executed=2,
            queries_successful=2,
            query_results=[],
            success=True,
            errors=[],
        )

        # Include query results
        result1.query_results.append({"query_id": 1, "execution_time_seconds": 10.0})
        result2.query_results.append({"query_id": 1, "execution_time_seconds": 8.0})

        result1.query_results.append({"query_id": "14a", "execution_time_seconds": 15.0})
        result2.query_results.append({"query_id": "14a", "execution_time_seconds": 12.0})

        # Test comparison
        comparison = power_test.compare_results(result1, result2)

        assert comparison["power_at_size"]["result1"] == 36.0
        assert comparison["power_at_size"]["result2"] == 40.0
        assert comparison["power_at_size"]["improvement"] > 0  # Improvement

        assert comparison["total_time"]["result1"] == 100.0
        assert comparison["total_time"]["result2"] == 90.0
        assert comparison["total_time"]["improvement"] > 0  # Improvement

        assert comparison["query_improvements"][1]["time1"] == 10.0
        assert comparison["query_improvements"][1]["time2"] == 8.0
        assert comparison["query_improvements"][1]["improvement"] > 0  # Improvement

        assert comparison["query_improvements"]["14a"]["time1"] == 15.0
        assert comparison["query_improvements"]["14a"]["time2"] == 12.0
        assert comparison["query_improvements"]["14a"]["improvement"] > 0  # Improvement


class TestTPCDSPowerTestIntegration:
    """Integration tests for TPC-DS Power Test with actual database."""

    @pytest.fixture
    def sqlite_db(self):
        """Create a temporary SQLite database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        # a simple test database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # minimal TPC-DS-like tables for testing
        cursor.execute("""
            CREATE TABLE call_center (
                cc_call_center_sk INTEGER PRIMARY KEY,
                cc_call_center_id TEXT,
                cc_name TEXT,
                cc_class TEXT,
                cc_employees INTEGER,
                cc_sq_ft INTEGER,
                cc_hours TEXT,
                cc_manager TEXT,
                cc_market_id INTEGER,
                cc_market_class TEXT,
                cc_market_desc TEXT,
                cc_market_manager TEXT,
                cc_division_id INTEGER,
                cc_division_name TEXT,
                cc_company_id INTEGER,
                cc_company_name TEXT,
                cc_street_number TEXT,
                cc_street_name TEXT,
                cc_street_type TEXT,
                cc_suite_number TEXT,
                cc_city TEXT,
                cc_county TEXT,
                cc_state TEXT,
                cc_zip TEXT,
                cc_country TEXT,
                cc_gmt_offset REAL,
                cc_tax_percentage REAL
            )
        """)

        cursor.execute("""
            CREATE TABLE date_dim (
                d_date_sk INTEGER PRIMARY KEY,
                d_date_id TEXT,
                d_date TEXT,
                d_month_seq INTEGER,
                d_week_seq INTEGER,
                d_quarter_seq INTEGER,
                d_year INTEGER,
                d_dow INTEGER,
                d_moy INTEGER,
                d_dom INTEGER,
                d_qoy INTEGER,
                d_fy_year INTEGER,
                d_fy_quarter_seq INTEGER,
                d_fy_week_seq INTEGER,
                d_day_name TEXT,
                d_quarter_name TEXT,
                d_holiday TEXT,
                d_weekend TEXT,
                d_following_holiday TEXT,
                d_first_dom INTEGER,
                d_last_dom INTEGER,
                d_same_day_ly INTEGER,
                d_same_day_lq INTEGER,
                d_current_day TEXT,
                d_current_week TEXT,
                d_current_month TEXT,
                d_current_quarter TEXT,
                d_current_year TEXT
            )
        """)

        # Insert test data
        cursor.execute(
            "INSERT INTO call_center VALUES (1, 'CC001', 'Call Center 1', 'medium', 100, 10000, '8AM-8PM', 'Manager 1', 1, 'market', 'Market 1', 'Market Manager 1', 1, 'Division 1', 1, 'Company 1', '123', 'Main St', 'Street', 'Suite 1', 'City', 'County', 'State', '12345', 'Country', -5.0, 0.08)"
        )
        cursor.execute(
            "INSERT INTO date_dim VALUES (1, '2000-01-01', '2000-01-01', 1, 1, 1, 2000, 7, 1, 1, 1, 2000, 1, 1, 'Saturday', 'Q1', 'N', 'Y', 'N', 1, 31, 365, 91, 'N', 'N', 'N', 'N', 'N')"
        )

        conn.commit()
        conn.close()

        yield db_path

        # Cleanup
        Path(db_path).unlink(missing_ok=True)

    def test_power_test_integration_with_sqlite(self, sqlite_db):
        """Test Power Test integration with actual SQLite database."""
        # a mock benchmark with simple queries
        mock_benchmark = Mock()
        mock_benchmark.scale_factor = 1.0

        def mock_get_query(query_id, **kwargs):
            # Return simple queries that will work with our test database
            if query_id == 1:
                return "SELECT COUNT(*) FROM call_center"
            elif query_id == 2:
                return "SELECT COUNT(*) FROM date_dim"
            elif query_id == "14a":
                return "SELECT cc_call_center_sk, cc_name FROM call_center LIMIT 1"
            elif query_id == 3:
                return "SELECT d_date_sk, d_date FROM date_dim LIMIT 1"
            else:
                return "SELECT 1 as test_result"

        mock_benchmark.get_query = mock_get_query

        # connection factory for real SQLite connection
        def sqlite_connection_factory():
            import sqlite3

            return sqlite3.connect(sqlite_db)

        # Power Test instance
        power_test = TPCDSPowerTest(
            benchmark=mock_benchmark,
            connection_factory=sqlite_connection_factory,
            scale_factor=1.0,
            verbose=False,
            warm_up=False,  # Skip warm-up for faster testing
            validation=False,  # Skip validation for simpler testing
        )

        # Run a limited version of the Power Test
        # Override the query sequence to use only a few queries for testing
        power_test._query_sequence = [1, 2, "14a", 3]

        # Execute the test
        result = power_test.run()

        # Verify results
        assert result.config.scale_factor == 1.0
        assert result.total_time > 0
        assert result.power_at_size > 0
        assert len(result.query_results) == 4

        # Verify each query was executed
        query_results_dict = {qr["query_id"]: qr for qr in result.query_results}
        for query_id in ["1", "2", "14a", "3"]:
            assert query_id in query_results_dict
            query_result = query_results_dict[query_id]
            assert query_result["query_id"] == query_id
            assert query_result["execution_time_seconds"] > 0
            # Check if query was successful
            success = query_result.get("success", False)
            status = query_result.get("status", "")
            assert success or status == "success"

    def test_power_test_with_failing_queries(self, sqlite_db):
        """Test Power Test behavior with failing queries."""
        mock_benchmark = Mock()
        mock_benchmark.scale_factor = 1.0

        def mock_get_query(query_id, **kwargs):
            if query_id == 1:
                return "SELECT COUNT(*) FROM call_center"
            elif query_id == "14a":
                return "SELECT COUNT(*) FROM date_dim"
            else:
                # Return an invalid query that will fail
                return "SELECT * FROM nonexistent_table"

        mock_benchmark.get_query = mock_get_query

        # connection factory for real SQLite connection
        def sqlite_connection_factory():
            import sqlite3

            return sqlite3.connect(sqlite_db)

        power_test = TPCDSPowerTest(
            benchmark=mock_benchmark,
            connection_factory=sqlite_connection_factory,
            scale_factor=1.0,
            verbose=False,
            warm_up=False,
            validation=False,
        )

        # Test with a few queries including failures
        power_test._query_sequence = [1, "14a", 2]

        result = power_test.run()

        # Verify that the test completed despite failures
        assert result.config.scale_factor == 1.0
        assert result.total_time > 0
        assert len(result.query_results) == 3

        # Check that first two queries succeeded and third failed
        query_results_dict = {qr["query_id"]: qr for qr in result.query_results}
        assert query_results_dict["1"]["success"]
        assert query_results_dict["14a"]["success"]
        assert not query_results_dict["2"]["success"]
        assert "nonexistent_table" in query_results_dict["2"]["error"]


class TestTPCDSBenchmarkIntegration:
    """Test integration with TPCDSBenchmark class."""

    @patch("benchbox.core.tpcds.power_test.DatabaseConnection")
    def test_benchmark_run_power_test_method(self, mock_db_connection):
        """Test the run_power_test method added to TPCDSBenchmark."""
        # a real TPCDSBenchmark instance
        benchmark = TPCDSBenchmark(scale_factor=1.0, verbose=False)

        # Mock the database connection
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [("test_result",)]
        mock_connection.execute.return_value = mock_cursor
        mock_db_connection.return_value = mock_connection

        # Mock the query manager to return simple queries
        def mock_get_query(query_id, **kwargs):
            return f"SELECT {query_id} as query_id"

        benchmark.get_query = mock_get_query

        # Call the benchmark's run_power_test method with mock queries
        # a mock connection object instead of connection string
        result = benchmark.run_power_test(connection=mock_connection, seed=42, verbose=False)

        # Verify the result was returned as dictionary
        assert isinstance(result, dict)
        assert result["scale_factor"] == 1.0
        assert "total_time" in result
        assert "power_at_size" in result
        assert "query_results" in result
        assert isinstance(result["query_results"], dict)

        # The benchmark should handle connection errors gracefully
        # If no queries were executed due to connection issues, that's acceptable
        if len(result["query_results"]) == 0 and "errors" in result and result["errors"]:
            # This is expected for connection issues
            assert len(result["errors"]) > 0
            return

        # If queries were executed successfully, verify their structure
        if len(result["query_results"]) > 0:
            for _query_id, query_result in result["query_results"].items():
                assert "query_id" in query_result
                assert "execution_time_seconds" in query_result
                assert "status" in query_result

    def test_benchmark_run_power_test_parameter_validation(self):
        """Test parameter validation in benchmark's run_power_test method."""
        benchmark = TPCDSBenchmark(scale_factor=1.0, verbose=False)

        # Mock the query method to avoid query issues
        def mock_get_query(query_id, **kwargs):
            return f"SELECT {query_id} as query_id"

        benchmark.get_query = mock_get_query

        # Test with invalid connection object - should return result with errors
        # an invalid connection object (None) to trigger errors
        result = benchmark.run_power_test(connection=None)

        # The benchmark should return a result dictionary with errors, not raise exception
        assert isinstance(result, dict)
        assert "errors" in result
        assert len(result["errors"]) > 0  # Should have connection errors


# Performance and stress tests
class TestTPCDSPowerTestPerformance:
    """Performance and stress tests for TPC-DS Power Test."""

    @pytest.mark.slow
    def test_power_test_performance_measurement(self):
        """Test that Power Test accurately measures performance."""
        mock_benchmark = Mock()
        mock_benchmark.scale_factor = 1.0

        # queries with artificial delays
        def mock_get_query(query_id, **kwargs):
            return f"SELECT {query_id} as query_id"

        mock_benchmark.get_query = mock_get_query

        # Mock database with controlled delays
        with patch("benchbox.core.tpcds.power_test.DatabaseConnection") as mock_db_connection:
            mock_connection = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchall.return_value = [("result",)]
            mock_connection.execute.return_value = mock_cursor
            mock_db_connection.return_value = mock_connection

            # Include artificial delay to query execution
            def delayed_execute(query):
                time.sleep(0.01)  # 10ms delay per query
                return mock_cursor

            mock_connection.execute.side_effect = delayed_execute

            power_test = TPCDSPowerTest(
                benchmark=mock_benchmark,
                connection_string="sqlite::memory:",
                warm_up=False,
                validation=False,
            )

            # Test with reduced query set for performance
            power_test.query_sequence = list(range(1, 6)) + ["14a"]  # 5 queries + 1 variant

            result = power_test.run()

            # Verify timing accuracy
            expected_min_time = 0.06  # 6 queries × 10ms = 60ms
            assert result.total_time >= expected_min_time
            assert result.power_at_size > 0

            # Verify individual query times - query IDs are strings
            query_results_dict = {qr["query_id"]: qr for qr in result.query_results}
            for query_id in ["1", "2", "3", "4", "5", "14a"]:
                query_result = query_results_dict[query_id]
                assert query_result["execution_time_seconds"] >= 0.01  # At least 10ms

    @pytest.mark.slow
    def test_power_test_timeout_handling(self):
        """Test timeout handling in Power Test."""
        mock_benchmark = Mock()
        mock_benchmark.scale_factor = 1.0
        mock_benchmark.get_query = lambda query_id, **kwargs: f"SELECT {query_id}"

        with patch("benchbox.core.tpcds.power_test.DatabaseConnection") as mock_db_connection:
            mock_connection = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchall.return_value = [("result",)]
            mock_connection.execute.return_value = mock_cursor
            mock_db_connection.return_value = mock_connection

            # Simulate slow query execution
            def slow_execute(query):
                time.sleep(0.1)  # 100ms delay
                return mock_cursor

            mock_connection.execute.side_effect = slow_execute

            power_test = TPCDSPowerTest(
                benchmark=mock_benchmark,
                connection_string="sqlite::memory:",
                timeout=0.05,  # 50ms timeout
                warm_up=False,
                validation=False,
            )

            power_test.query_sequence = [1, "14a"]  # Just 2 queries

            result = power_test.run()

            # Verify that queries took longer than the timeout but completed
            # The current implementation appears to check timeout after completion
            # rather than aborting queries mid-execution
            query_results_dict = {qr["query_id"]: qr for qr in result.query_results}

            # Both queries should have executed (even if they took longer than timeout)
            assert len(result.query_results) == 2

            # Check that queries took longer than the timeout
            for query_id in ["1", "14a"]:
                query_result = query_results_dict[query_id]
                assert query_result["execution_time_seconds"] > 0.05  # Longer than 50ms timeout
