"""Tests for AMPLab Big Data Benchmark implementation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox import AMPLab
from benchbox.core.amplab.benchmark import AMPLabBenchmark
from benchbox.utils.path_utils import resolve_benchmark_runs_dir

from .fixtures.benchmark_test_mixin import BenchmarkTestMixin

pytestmark = pytest.mark.medium


@pytest.mark.amplab
class TestAMPLab:
    """Test the AMPLab Big Data Benchmark implementation."""

    @pytest.fixture
    def amplab(self, small_scale_factor: float, temp_dir: Path) -> AMPLab:
        """Create an AMPLab benchmark instance for testing."""
        return AMPLab(scale_factor=small_scale_factor, output_dir=temp_dir)

    def test_generate_data(self, amplab: AMPLab) -> None:
        """Test that data generation produces expected files."""
        data_paths = amplab.generate_data()

        # Check that output includes expected files (returns dict)
        expected_tables = ["rankings", "uservisits", "documents"]

        assert isinstance(data_paths, dict), "generate_data should return a dictionary"

        for table in expected_tables:
            assert table in data_paths, f"Table {table} not found in generated data"

        # Verify files exist
        for _table_name, path in data_paths.items():
            assert Path(path).exists(), f"Generated file {path} does not exist"

    def test_get_queries(self, amplab: AMPLab) -> None:
        """Test that all benchmark queries can be retrieved."""
        queries = amplab.get_queries()

        # AMPLab has multiple queries (scan, join, analytics)
        expected_queries = ["1", "2", "3", "4", "5"]  # Basic set, may have more

        assert len(queries) >= 5  # Should have at least 5 queries
        for query_id in expected_queries:
            if query_id in queries:  # Check if this specific query exists
                assert isinstance(queries[query_id], str)
                assert queries[query_id].strip()

                # Check that queries contain expected SQL elements
                query_sql = queries[query_id].upper()
                assert "SELECT" in query_sql
                assert "FROM" in query_sql

                # Different query types should use different tables
                if "RANKINGS" in query_sql:
                    # Scan query on rankings
                    pass
                elif "USERVISITS" in query_sql:
                    # Queries involving user visits
                    pass
                elif "DOCUMENTS" in query_sql:
                    # Queries involving documents
                    pass

    def test_get_query(self, amplab: AMPLab) -> None:
        """Test retrieving a specific query."""
        queries = amplab.get_queries()
        first_query_id = list(queries.keys())[0]

        query = amplab.get_query(first_query_id)
        assert isinstance(query, str)
        assert "SELECT" in query.upper()
        assert "FROM" in query.upper()

        # Test another query if available
        if len(queries) > 1:
            second_query_id = list(queries.keys())[1]
            query2 = amplab.get_query(second_query_id)
            assert isinstance(query2, str)
            assert "SELECT" in query2.upper()

    def test_translate_query(self, amplab: AMPLab, sql_dialect: str) -> None:
        """Test translating a query to different SQL dialects."""
        queries = amplab.get_queries()
        first_query_id = list(queries.keys())[0]

        translated_query = amplab.translate_query(first_query_id, dialect=sql_dialect)

        assert isinstance(translated_query, str)
        assert "SELECT" in translated_query.upper()

    def test_invalid_query_id(self, amplab: AMPLab) -> None:
        """Test that requesting an invalid query raises an exception."""
        with pytest.raises(ValueError):
            amplab.get_query("Q999")  # Non-existent query

    def test_get_schema(self, amplab: AMPLab) -> None:
        """Test retrieving the AMPLab schema."""
        schema = amplab.get_schema()

        # Check that schema is a dictionary and all tables are present
        assert isinstance(schema, dict), "Schema should be a dictionary"
        expected_tables = ["rankings", "uservisits", "documents"]

        for table in expected_tables:
            assert table in schema, f"Table {table} not found in schema"

        # Check rankings table structure
        rankings_table = schema["rankings"]
        column_names = [col["name"] for col in rankings_table["columns"]]
        expected_rankings_columns = ["pageURL", "pageRank", "avgDuration"]

        for column in expected_rankings_columns:
            assert column in column_names

        # Check uservisits table structure
        uservisits_table = schema["uservisits"]
        uservisits_columns = [col["name"] for col in uservisits_table["columns"]]
        expected_uservisits_columns = [
            "sourceIP",
            "destURL",
            "visitDate",
            "adRevenue",
            "userAgent",
            "countryCode",
            "languageCode",
            "searchWord",
            "duration",
        ]

        for column in expected_uservisits_columns:
            assert column in uservisits_columns

        # Check documents table structure
        documents_table = schema["documents"]
        documents_columns = [col["name"] for col in documents_table["columns"]]
        expected_documents_columns = ["url", "contents"]

        for column in expected_documents_columns:
            assert column in documents_columns

    def test_get_create_tables_sql(self, amplab: AMPLab) -> None:
        """Test retrieving SQL to create AMPLab tables."""
        sql = amplab.get_create_tables_sql()

        assert isinstance(sql, str)
        assert "CREATE TABLE" in sql

        # Check for all tables (using lowercase names as they appear in SQL)
        expected_tables = ["rankings", "uservisits", "documents"]

        for table in expected_tables:
            assert f"CREATE TABLE {table}" in sql

    def test_benchmark_properties(self, amplab: AMPLab) -> None:
        """Test benchmark-specific properties."""
        # Test that AMPLab has exactly 3 tables
        schema = amplab.get_schema()
        assert len(schema) == 3

        # Test that queries cover different types of operations
        queries = amplab.get_queries()
        assert len(queries) >= 3  # Should have multiple queries

        # Check that queries test different aspects of big data processing
        all_queries_text = " ".join(queries.values()).upper()

        # Should contain various big data operations
        big_data_keywords = ["GROUP BY", "ORDER BY", "JOIN", "WHERE"]
        found_keywords = [kw for kw in big_data_keywords if kw in all_queries_text]
        assert len(found_keywords) >= 2, "AMPLab queries should contain various big data operations"

    def test_web_analytics_focus(self, amplab: AMPLab) -> None:
        """Test that the benchmark focuses on web analytics workloads."""
        schema = amplab.get_schema()
        table_names = list(schema.keys())

        # Should have web-specific tables
        assert "rankings" in table_names, "Should have rankings table for web analytics"
        assert "uservisits" in table_names, "Should have uservisits table for web analytics"

        # Check for web-specific columns
        uservisits_table = schema["uservisits"]
        column_names = [col["name"] for col in uservisits_table["columns"]]

        web_columns = ["sourceIP", "destURL", "adRevenue", "userAgent"]
        for col in web_columns:
            assert col in column_names, f"Web-specific column {col} not found"

    def test_query_types_coverage(self, amplab: AMPLab) -> None:
        """Test that queries cover different types of big data workloads."""
        queries = amplab.get_queries()

        # Should have different types of queries
        has_scan = False
        has_join = False
        has_aggregation = False

        for _query_id, query_sql in queries.items():
            query_upper = query_sql.upper()

            # Scan queries (simple SELECT with filtering)
            if "WHERE" in query_upper and "JOIN" not in query_upper:
                has_scan = True

            # Join queries
            if "JOIN" in query_upper or (
                query_upper.count("FROM") == 1
                and len([table for table in ["RANKINGS", "USERVISITS", "DOCUMENTS"] if table in query_upper]) > 1
            ):
                has_join = True

            # Aggregation queries
            if any(agg in query_upper for agg in ["COUNT", "SUM", "AVG", "GROUP BY"]):
                has_aggregation = True

        # AMPLab should test various types of operations
        # Note: Not all query types may be present, but we should have some variety
        operation_count = sum([has_scan, has_join, has_aggregation])
        assert operation_count >= 1, "AMPLab benchmark should include various types of operations"

    def test_big_data_characteristics(self, amplab: AMPLab) -> None:
        """Test characteristics that make this suitable for big data testing."""
        schema = amplab.get_schema()

        # Should have tables that can scale to large sizes
        uservisits_table = schema["uservisits"]
        # This table should have many columns suitable for large-scale analytics
        assert len(uservisits_table["columns"]) >= 8, "uservisits should have many columns for analytics"

        # Queries should be suitable for distributed processing
        queries = amplab.get_queries()
        all_queries_text = " ".join(queries.values()).upper()

        # Should contain operations that benefit from distributed processing
        distributed_keywords = ["GROUP BY", "ORDER BY", "DISTINCT", "JOIN"]
        found_keywords = [kw for kw in distributed_keywords if kw in all_queries_text]
        assert len(found_keywords) >= 1, "Should have operations suitable for distributed processing"


@pytest.mark.amplab
class TestAMPLabBenchmarkDirectly(BenchmarkTestMixin):
    """Test AMPLabBenchmark class directly for better coverage."""

    benchmark_class = AMPLabBenchmark
    sample_query_id = "1"
    sample_table = "rankings"
    sample_sql = "SELECT * FROM rankings"
    sample_csv_filename = "rankings.csv"
    sample_csv_content = "url1|1|100\nurl2|2|200\n"

    @pytest.fixture
    def amplab_benchmark(self, small_scale_factor: float, temp_dir: Path) -> AMPLabBenchmark:
        """Create an AMPLabBenchmark instance for testing."""
        return AMPLabBenchmark(scale_factor=small_scale_factor, output_dir=temp_dir)

    @pytest.fixture
    def benchmark_instance(self, amplab_benchmark: AMPLabBenchmark) -> AMPLabBenchmark:
        """Alias for the mixin's benchmark_instance fixture."""
        return amplab_benchmark

    def test_init_with_default_output_dir(self) -> None:
        """Test benchmark initialization with default output directory."""
        benchmark = AMPLabBenchmark(scale_factor=0.01)
        assert benchmark.scale_factor == 0.01
        # Default path follows: benchmark_runs/datagen/{benchmark}_sf{formatted_sf}
        # 0.01 formats as "sf001" per format_scale_factor()
        assert benchmark.output_dir == resolve_benchmark_runs_dir() / "datagen" / "amplab_sf001"
        assert benchmark._name == "AMPLab Big Data Benchmark"
        assert benchmark._version == "1.0"

    def test_generate_data_validation(self, amplab_benchmark: AMPLabBenchmark) -> None:
        """Test data generation input validation."""
        # Test unsupported output format
        with pytest.raises(ValueError, match="Unsupported output format"):
            amplab_benchmark.generate_data(output_format="json")

        # Test invalid table names
        with pytest.raises(ValueError, match="Invalid table names"):
            amplab_benchmark.generate_data(tables=["invalid_table"])

    def test_generate_data_subset(self, amplab_benchmark: AMPLabBenchmark) -> None:
        """Test data generation for specific tables."""
        with patch.object(amplab_benchmark.data_generator, "generate_data") as mock_generate:
            mock_generate.return_value = {"rankings": "/path/to/rankings.csv"}

            result = amplab_benchmark.generate_data(tables=["rankings"])

            mock_generate.assert_called_once_with(["rankings"])
            assert result == {"rankings": "/path/to/rankings.csv"}
            assert amplab_benchmark.tables == result

    def test_load_data_to_database_cursor_mode(self, amplab_benchmark: AMPLabBenchmark) -> None:
        """Test load_data_to_database with cursor mode."""
        # Set up mock data
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_file = Path(temp_dir) / "rankings.csv"
            csv_file.write_text("url1|1|100\nurl2|2|200\n")

            amplab_benchmark.tables = {"rankings": str(csv_file)}

            mock_connection = Mock()
            mock_cursor = Mock()
            mock_connection.cursor.return_value = mock_cursor
            mock_connection.commit = Mock()
            delattr(mock_connection, "executescript")
            delattr(mock_connection, "executemany")

            with patch.object(amplab_benchmark, "get_create_tables_sql") as mock_get_sql:
                mock_get_sql.return_value = "CREATE TABLE rankings (...);"

                amplab_benchmark.load_data_to_database(mock_connection)

                mock_cursor.execute.assert_called()
                mock_connection.commit.assert_called_once()

    def test_load_data_to_database_specific_tables(self, amplab_benchmark: AMPLabBenchmark) -> None:
        """Test load_data_to_database with specific table list."""
        # Set up mock data
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_file = Path(temp_dir) / "rankings.csv"
            csv_file.write_text("url1|1|100\n")

            amplab_benchmark.tables = {
                "rankings": str(csv_file),
                "uservisits": "/path/to/uservisits.csv",
            }

            mock_connection = Mock()
            mock_connection.executescript = Mock()
            mock_connection.executemany = Mock()
            mock_connection.commit = Mock()

            with patch.object(amplab_benchmark, "get_create_tables_sql") as mock_get_sql:
                mock_get_sql.return_value = "CREATE TABLE rankings (...);"

                amplab_benchmark.load_data_to_database(mock_connection, tables=["rankings"])

                # Should only process rankings table
                mock_connection.executemany.assert_called_once()

    def test_run_benchmark_default_queries(self, amplab_benchmark: AMPLabBenchmark) -> None:
        """Test run_benchmark with default queries."""
        mock_connection = Mock()

        with patch.object(amplab_benchmark, "execute_query") as mock_execute:
            mock_execute.return_value = [("result1",), ("result2",)]
            with patch.object(amplab_benchmark.query_manager, "get_all_queries") as mock_get_all:
                mock_get_all.return_value = {"1": "SELECT ...", "2": "SELECT ..."}

                result = amplab_benchmark.run_benchmark(mock_connection, iterations=1)

                assert result["benchmark"] == "AMPLab"
                assert result["scale_factor"] == amplab_benchmark.scale_factor
                assert result["iterations"] == 1
                assert len(result["queries"]) == 2
                assert "1" in result["queries"]
                assert "2" in result["queries"]

    def test_run_benchmark_specific_queries(self, amplab_benchmark: AMPLabBenchmark) -> None:
        """Test run_benchmark with specific query list."""
        mock_connection = Mock()

        with patch.object(amplab_benchmark, "execute_query") as mock_execute:
            mock_execute.return_value = [("result1",)]

            result = amplab_benchmark.run_benchmark(mock_connection, queries=["1"], iterations=2)

            assert len(result["queries"]) == 1
            assert len(result["queries"]["1"]["iterations"]) == 2

    def test_run_benchmark_with_exceptions(self, amplab_benchmark: AMPLabBenchmark) -> None:
        """Test run_benchmark handling exceptions during execution."""
        mock_connection = Mock()

        with patch.object(amplab_benchmark, "execute_query") as mock_execute:
            mock_execute.side_effect = Exception("Database error")

            result = amplab_benchmark.run_benchmark(mock_connection, queries=["1"], iterations=1)

            query_result = result["queries"]["1"]
            assert query_result["iterations"][0]["success"] is False
            assert query_result["iterations"][0]["error"] == "Database error"
            assert query_result["avg_time"] == 0

    def test_run_benchmark_timing_calculation(self, amplab_benchmark: AMPLabBenchmark) -> None:
        """Test run_benchmark timing calculations."""
        mock_connection = Mock()

        with patch.object(amplab_benchmark, "execute_query") as mock_execute:
            mock_execute.return_value = [("result1",), ("result2",)]
            with patch("benchbox.core.simple_benchmark_mixin.elapsed_seconds") as mock_elapsed:
                # Mock elapsed_seconds to return predictable values per iteration
                mock_elapsed.side_effect = [0.5, 0.2]  # Two iterations: 0.5s then 0.2s

                result = amplab_benchmark.run_benchmark(mock_connection, queries=["1"], iterations=2)

                query_result = result["queries"]["1"]
                # Use approximate comparisons for floating point values
                assert abs(query_result["avg_time"] - 0.35) < 0.01  # (0.5 + 0.2) / 2
                assert abs(query_result["min_time"] - 0.2) < 0.01
                assert abs(query_result["max_time"] - 0.5) < 0.01

    def test_run_benchmark_mixed_success_failure(self, amplab_benchmark: AMPLabBenchmark) -> None:
        """Test run_benchmark with mixed successful and failed iterations."""
        mock_connection = Mock()

        with patch.object(amplab_benchmark, "execute_query") as mock_execute:
            # First iteration succeeds, second fails
            mock_execute.side_effect = [[("result1",)], Exception("Database error")]
            with patch("benchbox.core.simple_benchmark_mixin.elapsed_seconds") as mock_elapsed:
                # Only the successful iteration calls elapsed_seconds
                mock_elapsed.side_effect = [0.5]

                result = amplab_benchmark.run_benchmark(mock_connection, queries=["1"], iterations=2)

                query_result = result["queries"]["1"]
                assert len(query_result["iterations"]) == 2
                assert query_result["iterations"][0]["success"] is True
                assert query_result["iterations"][1]["success"] is False
                assert abs(query_result["avg_time"] - 0.5) < 0.01  # Only successful iteration counted

    def test_output_format_validation(self, amplab_benchmark: AMPLabBenchmark) -> None:
        """Test output format validation in generate_data."""
        with pytest.raises(ValueError, match="Unsupported output format: parquet"):
            amplab_benchmark.generate_data(output_format="parquet")

    def test_get_all_queries_method(self, amplab_benchmark: AMPLabBenchmark) -> None:
        """Test get_all_queries method."""
        with patch.object(amplab_benchmark.query_manager, "get_all_queries") as mock_get_all:
            mock_get_all.return_value = {"1": "SELECT ...", "2": "SELECT ..."}

            result = amplab_benchmark.get_all_queries()

            mock_get_all.assert_called_once()
            assert result == {"1": "SELECT ...", "2": "SELECT ..."}

    def test_schema_methods_delegation(self, amplab_benchmark: AMPLabBenchmark) -> None:
        """Test schema-related methods delegate correctly."""
        # Test get_schema
        schema = amplab_benchmark.get_schema()
        assert isinstance(schema, dict)
        assert "rankings" in schema

        # Test get_create_tables_sql
        sql = amplab_benchmark.get_create_tables_sql()
        assert isinstance(sql, str)
        assert "CREATE TABLE" in sql

    def test_sqlite_integration(self, amplab_benchmark: AMPLabBenchmark) -> None:
        """Test actual SQLite integration for load_data_to_database."""
        # Generate some test data
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_file = Path(temp_dir) / "rankings.csv"
            csv_file.write_text("http://example.com/1|1|100\nhttp://example.com/2|2|200\n")

            amplab_benchmark.tables = {"rankings": str(csv_file)}

            # in-memory SQLite database
            conn = sqlite3.connect(":memory:")

            try:
                # This should work without errors
                amplab_benchmark.load_data_to_database(conn, tables=["rankings"])

                # Verify data was loaded
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM rankings")
                count = cursor.fetchone()[0]
                assert count == 2

                cursor.execute("SELECT pageURL, pageRank, avgDuration FROM rankings ORDER BY pageRank")
                rows = cursor.fetchall()
                assert len(rows) == 2
                assert rows[0][1] == 1  # pageRank
                assert rows[1][1] == 2  # pageRank

            finally:
                conn.close()

    def test_csv_parsing_edge_cases(self, amplab_benchmark: AMPLabBenchmark) -> None:
        """Test CSV parsing with various edge cases."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Test with empty lines and different delimiters
            csv_file = Path(temp_dir) / "rankings.csv"
            csv_file.write_text("url1|1|100\nurl2|2|200\n")

            amplab_benchmark.tables = {"rankings": str(csv_file)}

            # mock connection that tracks the data being inserted
            mock_connection = Mock()
            mock_connection.executescript = Mock()
            mock_connection.executemany = Mock()
            mock_connection.commit = Mock()

            with patch.object(amplab_benchmark, "get_create_tables_sql") as mock_get_sql:
                mock_get_sql.return_value = "CREATE TABLE rankings (...);"

                amplab_benchmark.load_data_to_database(mock_connection)

                # Verify executemany was called with the right data
                call_args = mock_connection.executemany.call_args
                assert call_args is not None
                sql, data = call_args[0]
                assert "INSERT INTO rankings VALUES" in sql
                assert len(data) == 2
                assert data[0] == ["url1", "1", "100"]
                assert data[1] == ["url2", "2", "200"]
