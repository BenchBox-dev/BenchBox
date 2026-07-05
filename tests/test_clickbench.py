"""Tests for ClickBench (ClickHouse Analytics Benchmark) implementation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox import ClickBench
from benchbox.core.clickbench.benchmark import ClickBenchBenchmark

from .fixtures.benchmark_test_mixin import BenchmarkTestMixin

pytestmark = pytest.mark.medium


@pytest.mark.clickbench
class TestClickBench:
    """Test the ClickBench (ClickHouse Analytics Benchmark) implementation."""

    @pytest.fixture
    def clickbench(self, small_scale_factor: float, temp_dir: Path) -> ClickBench:
        """Create a ClickBench  ClickBenchBenchmark instance for testing."""
        return ClickBench(scale_factor=small_scale_factor, output_dir=temp_dir)

    # Runs to completion but far exceeds the medium lane's 60s cap: timed out
    # on a clean GitHub runner (develop-post-merge run 28706929881, medium-test
    # job) and measured ~42s in a 4-core container (2026-07-05). The marker
    # overrides the CLI --timeout=60 (pytest-timeout marker precedence) so the
    # test keeps running in the medium lane instead of being killed mid-work.
    @pytest.mark.timeout(300)
    def test_generate_data(self, clickbench: ClickBench) -> None:
        """Test that data generation produces expected files."""
        data_paths = clickbench.generate_data()

        # Check that output includes expected files

        # ClickBench returns a list, not a dict
        assert isinstance(data_paths, list), "generate_data should return a list"
        assert len(data_paths) >= 1, "Should generate at least one file"

        # Verify files exist
        for path in data_paths:
            assert Path(path).exists(), f"Generated file {path} does not exist"

    def test_get_queries(self, clickbench: ClickBench) -> None:
        """Test that all  ClickBenchBenchmark queries can be retrieved."""
        queries = clickbench.get_queries()

        # ClickBench has 43 queries (Q1-Q43)
        expected_queries = [f"Q{i}" for i in range(1, 44)]

        assert len(queries) == 43
        for query_id in expected_queries:
            assert query_id in queries, f"Query {query_id} not found"
            assert isinstance(queries[query_id], str)
            assert queries[query_id].strip()

            # Check that queries contain expected SQL elements
            query_sql = queries[query_id].upper()
            assert "SELECT" in query_sql
            assert "FROM" in query_sql
            assert "HITS" in query_sql  # All queries should use the hits table

            # Check for various SQL patterns based on query type
            if query_id in ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7"]:
                # Basic aggregation queries
                assert any(agg in query_sql for agg in ["COUNT", "SUM", "AVG", "MIN", "MAX"])
            elif query_id.startswith("Q2"):
                # Queries with WHERE clauses
                assert "WHERE" in query_sql
            elif query_id in ["Q8", "Q9", "Q10", "Q11", "Q12", "Q13", "Q14", "Q15"]:
                # Grouping queries
                assert "GROUP BY" in query_sql

    def test_get_query(self, clickbench: ClickBench) -> None:
        """Test retrieving a specific query."""
        query1 = clickbench.get_query("Q1")
        assert isinstance(query1, str)
        assert "SELECT" in query1.upper()
        assert "COUNT(*)" in query1.upper()
        assert "FROM hits" in query1

        # Test a different query type
        query8 = clickbench.get_query("Q8")
        assert isinstance(query8, str)
        assert "GROUP BY" in query8.upper()
        assert "ORDER BY" in query8.upper()

    def test_translate_query(self, clickbench: ClickBench, sql_dialect: str) -> None:
        """Test translating a query to different SQL dialects."""
        clickbench.get_query("Q1")
        translated_query = clickbench.translate_query("Q1", dialect=sql_dialect)

        assert isinstance(translated_query, str)
        assert "SELECT" in translated_query.upper()

    def test_invalid_query_id(self, clickbench: ClickBench) -> None:
        """Test that requesting an invalid query raises an exception."""
        with pytest.raises(ValueError):
            clickbench.get_query("Q44")  # Only Q1-Q43 exist

        with pytest.raises(ValueError):
            clickbench.get_query("Q0")  # Q0 doesn't exist

    def test_get_query_no_params(self, clickbench: ClickBench) -> None:
        """Test that queries can be retrieved without parameters."""
        # ClickBench queries are static and don't accept parameters
        param_query = clickbench.get_query("Q1")
        assert isinstance(param_query, str)
        assert "SELECT" in param_query.upper()

        # Test that passing params raises an error
        custom_params = {"param1": "value1"}
        with pytest.raises(ValueError, match="don't accept parameters"):
            clickbench.get_query("Q1", params=custom_params)

    def test_get_schema(self, clickbench: ClickBench) -> None:
        """Test retrieving the ClickBench schema."""
        schema = clickbench.get_schema()

        # Check that the hits table is present
        assert isinstance(schema, list), "Schema should be a list"
        assert len(schema) == 1, "ClickBench should have exactly one table"

        hits_table = schema[0]
        assert hits_table["name"] == "hits"

        # Check hits table structure
        column_names = [col["name"] for col in hits_table["columns"]]

        # Expected key columns from ClickBench schema
        expected_columns = [
            "WatchID",
            "JavaEnable",
            "Title",
            "GoodEvent",
            "EventTime",
            "EventDate",
            "CounterID",
            "ClientIP",
            "RegionID",
            "UserID",
            "URL",
            "Referer",
            "SearchPhrase",
            "AdvEngineID",
            "ResolutionWidth",
            "ResolutionHeight",
        ]

        for column in expected_columns:
            assert column in column_names, f"Column {column} not found in hits table"

        # Check that we have a reasonable number of columns (100+)
        assert len(column_names) >= 100, "ClickBench hits table should have many columns"

    def test_get_create_tables_sql(self, clickbench: ClickBench) -> None:
        """Test retrieving SQL to create ClickBench tables."""
        sql = clickbench.get_create_tables_sql()

        assert isinstance(sql, str)
        assert "CREATE TABLE" in sql
        assert "hits" in sql

        # Check for expected column types
        assert "WatchID" in sql
        assert "EventTime" in sql
        assert "UserID" in sql
        # ClickBench schema doesn't have PRIMARY KEY by default (requires tuning_config)

    def test_ClickBenchBenchmark_properties(self, clickbench: ClickBench) -> None:
        """Test  ClickBenchBenchmark-specific properties."""
        # Test that ClickBench has exactly one table (the hits table)
        schema = clickbench.get_schema()
        assert len(schema) == 1

        # Test that all 43 queries are available
        queries = clickbench.get_queries()
        assert len(queries) == 43

        # Check that queries cover different analytical patterns
        all_queries_text = " ".join(queries.values()).upper()

        # Should contain various analytical operations
        analytical_keywords = [
            "COUNT",
            "SUM",
            "AVG",
            "GROUP BY",
            "ORDER BY",
            "WHERE",
            "LIMIT",
        ]
        found_keywords = [kw for kw in analytical_keywords if kw in all_queries_text]
        assert len(found_keywords) >= 5, "ClickBench queries should contain various analytical operations"

    def test_web_analytics_focus(self, clickbench: ClickBench) -> None:
        """Test that the  ClickBenchBenchmark focuses on web analytics workloads."""
        schema = clickbench.get_schema()
        hits_table = schema[0]
        column_names = [col["name"] for col in hits_table["columns"]]

        # Should have web analytics specific columns
        web_analytics_columns = [
            "URL",
            "Referer",
            "SearchPhrase",
            "UserID",
            "EventTime",
            "ClientIP",
            "UserAgent",
            "ResolutionWidth",
            "ResolutionHeight",
        ]

        for col in web_analytics_columns:
            assert col in column_names, f"Web analytics column {col} not found"

        # Queries should reference web analytics concepts
        queries = clickbench.get_queries()
        all_queries_text = " ".join(queries.values()).upper()

        # Should contain references to web analytics operations
        web_keywords = ["URL", "REFERER", "SEARCHPHRASE", "USERID", "EVENTTIME"]
        found_keywords = [kw for kw in web_keywords if kw in all_queries_text]
        assert len(found_keywords) >= 3, "ClickBench queries should reference web analytics concepts"

    def test_query_categories(self, clickbench: ClickBench) -> None:
        """Test that queries are properly categorized."""
        categories = clickbench.get_query_categories()

        # Should have multiple categories
        assert len(categories) >= 6, "Should have multiple query categories"

        # Check specific categories exist
        expected_categories = [
            "basic_aggregation",
            "grouping_and_ordering",
            "user_analysis",
            "text_and_pattern_matching",
            "complex_grouping",
        ]

        for category in expected_categories:
            assert category in categories, f"Category {category} not found"
            assert len(categories[category]) >= 1, f"Category {category} should have queries"

    def test_analytical_query_patterns(self, clickbench: ClickBench) -> None:
        """Test that queries follow expected analytical patterns."""
        queries = clickbench.get_queries()

        # Should have different types of queries
        has_simple_count = False
        has_grouping = False
        has_filtering = False
        has_ordering = False
        has_pattern_matching = False

        for _query_id, query_sql in queries.items():
            query_upper = query_sql.upper()

            # Simple counting queries
            if "COUNT(*)" in query_upper and "GROUP BY" not in query_upper:
                has_simple_count = True

            # Grouping queries
            if "GROUP BY" in query_upper:
                has_grouping = True

            # Filtering queries
            if "WHERE" in query_upper:
                has_filtering = True

            # Ordering queries
            if "ORDER BY" in query_upper:
                has_ordering = True

            # Pattern matching queries
            if "LIKE" in query_upper:
                has_pattern_matching = True

        assert has_simple_count, "Should have simple counting queries"
        assert has_grouping, "Should have grouping queries"
        assert has_filtering, "Should have filtering queries"
        assert has_ordering, "Should have ordering queries"
        assert has_pattern_matching, "Should have pattern matching queries"

    def test_clickbench_characteristics(self, clickbench: ClickBench) -> None:
        """Test characteristics specific to ClickBench  ClickBenchBenchmark."""
        schema = clickbench.get_schema()

        # Should have a single flat table (characteristic of ClickBench)
        assert len(schema) == 1, "ClickBench uses a single flat table"

        hits_table = schema[0]
        # Should have many columns (100+) as it's a denormalized analytics table
        assert len(hits_table["columns"]) >= 100, "ClickBench table should be heavily denormalized"

        # Queries should be designed for analytical performance testing
        queries = clickbench.get_queries()

        # Should have exactly 43 queries as per ClickBench specification
        assert len(queries) == 43, "ClickBench should have exactly 43 queries"

        # All queries should operate on the same table
        for query_id, query_sql in queries.items():
            assert "hits" in query_sql.lower(), f"Query {query_id} should reference hits table"

    def test_performance_oriented_queries(self, clickbench: ClickBench) -> None:
        """Test that queries are designed for performance  ClickBenchBenchmarking."""
        queries = clickbench.get_queries()

        # Should have queries that test different performance characteristics
        has_full_scan = False
        has_aggregation = False
        has_complex_grouping = False
        has_string_operations = False

        for _query_id, query_sql in queries.items():
            query_upper = query_sql.upper()

            # Full table scan queries (no WHERE clause)
            if "WHERE" not in query_upper and "SELECT" in query_upper:
                has_full_scan = True

            # Aggregation queries
            if any(agg in query_upper for agg in ["COUNT", "SUM", "AVG", "MIN", "MAX"]):
                has_aggregation = True

            # Complex grouping (multiple GROUP BY columns)
            if "GROUP BY" in query_upper and query_upper.count(",") >= 2:
                has_complex_grouping = True

            # String operations
            if any(op in query_upper for op in ["LIKE", "LENGTH", "REGEXP"]):
                has_string_operations = True

        assert has_full_scan, "Should have full table scan queries for I/O testing"
        assert has_aggregation, "Should have aggregation queries"
        assert has_complex_grouping, "Should have complex grouping queries"
        assert has_string_operations, "Should have string operation queries"


@pytest.mark.clickbench
class TestClickBenchBenchmarkDirectly(BenchmarkTestMixin):
    """Test ClickBenchBenchmark class directly for better coverage."""

    benchmark_class = ClickBenchBenchmark
    sample_query_id = "Q1"
    sample_table = "hits"
    sample_sql = "SELECT COUNT(*) FROM hits"
    sample_csv_filename = "hits.csv"
    sample_csv_content = (
        "123|1|Title1|1|2023-01-01 12:00:00|2023-01-01|456|127.0.0.1|1|789"
        "|http://example.com|http://referer.com|search phrase|1|1920|1080\n"
    )

    @pytest.fixture
    def clickbench_benchmark(self, small_scale_factor: float, temp_dir: Path) -> ClickBenchBenchmark:
        """Create a ClickBenchBenchmark instance for testing."""
        return ClickBenchBenchmark(scale_factor=small_scale_factor, output_dir=temp_dir)

    @pytest.fixture
    def benchmark_instance(self, clickbench_benchmark: ClickBenchBenchmark) -> ClickBenchBenchmark:
        """Alias for the mixin's benchmark_instance fixture."""
        return clickbench_benchmark

    def test_init_with_default_output_dir(self) -> None:
        """Test  ClickBenchBenchmark initialization with default output directory."""
        clickbench = ClickBenchBenchmark(scale_factor=0.01)
        assert clickbench.scale_factor == 0.01
        # Default output directory is now benchmark_runs/datagen/{benchmark}_sf{scale}
        assert "benchmark_runs/datagen" in str(clickbench.output_dir)
        assert clickbench._name == "ClickBench"
        assert clickbench._version == "1.0"

    def test_generate_data_validation(self, clickbench_benchmark: ClickBenchBenchmark) -> None:
        """Test data generation input validation."""
        # Test unsupported output format
        with pytest.raises(ValueError, match="Unsupported output format"):
            clickbench_benchmark.generate_data(output_format="parquet")

        # Test invalid table names
        with pytest.raises(ValueError, match="Invalid table names"):
            clickbench_benchmark.generate_data(tables=["invalid_table"])

    def test_generate_data_subset(self, clickbench_benchmark: ClickBenchBenchmark) -> None:
        """Test data generation for specific tables."""
        with patch.object(clickbench_benchmark.data_generator, "generate_data") as mock_generate:
            mock_generate.return_value = {"hits": "/path/to/hits.csv"}

            result = clickbench_benchmark.generate_data(tables=["hits"])

            mock_generate.assert_called_once_with(["hits"])
            assert result == {"hits": "/path/to/hits.csv"}
            assert clickbench_benchmark.tables == result

    def test_load_data_to_database_batch_processing(self, clickbench_benchmark: ClickBenchBenchmark) -> None:
        """Test load_data_to_database with large dataset."""
        # Set up mock data with many rows
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_file = Path(temp_dir) / "hits.csv"
            # a large CSV file
            rows = []
            for i in range(15000):  # Large dataset
                rows.append(
                    f"{i}|1|Title{i}|1|2023-01-01 12:00:00|2023-01-01|456|127.0.0.1|1|789|http://example{i}.com|http://referer.com|search phrase|1|1920|1080"
                )
            csv_file.write_text("\n".join(rows) + "\n")

            clickbench_benchmark.tables = {"hits": str(csv_file)}

            mock_connection = Mock()
            mock_connection.executescript = Mock()
            mock_connection.executemany = Mock()
            mock_connection.commit = Mock()

            with patch.object(clickbench_benchmark, "get_create_tables_sql") as mock_get_sql:
                mock_get_sql.return_value = "CREATE TABLE hits (...);"

                clickbench_benchmark.load_data_to_database(mock_connection)

                # Should be called at least once
                assert mock_connection.executemany.call_count >= 1
                mock_connection.commit.assert_called_once()

    def test_run_ClickBenchBenchmark_default_queries(self, clickbench_benchmark: ClickBenchBenchmark) -> None:
        """Test run_ ClickBenchBenchmark with default queries."""
        mock_connection = Mock()

        with patch.object(clickbench_benchmark, "execute_query") as mock_execute:
            mock_execute.return_value = [("result1",), ("result2",)]
            with patch.object(clickbench_benchmark.query_manager, "get_all_queries") as mock_get_all:
                mock_get_all.return_value = {
                    "Q1": "SELECT COUNT(*) FROM hits",
                    "Q2": "SELECT COUNT(*) FROM hits WHERE AdvEngineID != 0",
                }

                result = clickbench_benchmark.run_benchmark(mock_connection, iterations=1)

                assert result["benchmark"] == "ClickBench"
                assert result["scale_factor"] == clickbench_benchmark.scale_factor
                assert result["iterations"] == 1
                assert len(result["queries"]) == 2
                assert "Q1" in result["queries"]
                assert "Q2" in result["queries"]

    def test_run_ClickBenchBenchmark_timing_calculation(self, clickbench_benchmark: ClickBenchBenchmark) -> None:
        """Test run_ ClickBenchBenchmark timing calculations."""
        mock_connection = Mock()

        with patch.object(ClickBenchBenchmark, "execute_query") as mock_execute:
            mock_execute.return_value = [("result1",), ("result2",)]
            with patch("benchbox.core.simple_benchmark_mixin.elapsed_seconds") as mock_elapsed:
                # Mock elapsed_seconds to return predictable values per iteration
                mock_elapsed.side_effect = [0.5, 0.2]  # Two iterations: 0.5s then 0.2s

                result = clickbench_benchmark.run_benchmark(mock_connection, queries=["Q1"], iterations=2)

                query_result = result["queries"]["Q1"]
                # Use approximate comparisons for floating point values
                assert abs(query_result["avg_time"] - 0.35) < 0.01  # (0.5 + 0.2) / 2
                assert abs(query_result["min_time"] - 0.2) < 0.01
                assert abs(query_result["max_time"] - 0.5) < 0.01

    def test_run_ClickBenchBenchmark_with_exceptions(self, clickbench_benchmark: ClickBenchBenchmark) -> None:
        """Test run_ ClickBenchBenchmark handling exceptions during execution."""
        mock_connection = Mock()

        with patch.object(ClickBenchBenchmark, "execute_query") as mock_execute:
            mock_execute.side_effect = Exception("Database error")

            result = clickbench_benchmark.run_benchmark(mock_connection, queries=["Q1"], iterations=1)

            query_result = result["queries"]["Q1"]
            assert query_result["iterations"][0]["success"] is False
            assert query_result["iterations"][0]["error"] == "Database error"
            assert query_result["avg_time"] == 0

    def test_sqlite_integration(self, clickbench_benchmark: ClickBenchBenchmark) -> None:
        """Test actual SQLite integration for load_data_to_database."""
        # Generate some test data for hits table (105 columns total)
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_file = Path(temp_dir) / "hits.csv"
            # CSV with exactly 105 pipe-separated values (number of columns in schema)
            row_values = ["123", "1", "Title1", "1", "2023-01-01 12:00:00", "2023-01-01", "456", "127", "1", "789"]
            # Pad with empty strings to reach 105 columns
            row_values.extend([""] * (105 - len(row_values)))
            csv_file.write_text("|".join(row_values) + "\n")

            clickbench_benchmark.tables = {"hits": str(csv_file)}

            # in-memory SQLite database
            conn = sqlite3.connect(":memory:")

            try:
                # This should work without errors
                clickbench_benchmark.load_data_to_database(conn, tables=["hits"])

                # Verify data was loaded
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM hits")
                count = cursor.fetchone()[0]
                assert count == 1

                cursor.execute("SELECT WatchID, Title FROM hits")
                rows = cursor.fetchall()
                assert len(rows) == 1
                assert rows[0][0] == 123  # WatchID
                assert rows[0][1] == "Title1"  # Title

            finally:
                conn.close()

    def test_schema_methods_delegation(self, clickbench_benchmark: ClickBenchBenchmark) -> None:
        """Test schema-related methods delegate correctly."""
        # Test get_schema
        schema = clickbench_benchmark.get_schema()
        assert isinstance(schema, dict)
        assert "hits" in schema

        # Test get_create_tables_sql
        sql = clickbench_benchmark.get_create_tables_sql()
        assert isinstance(sql, str)
        assert "CREATE TABLE" in sql

    def test_get_all_queries_method(self, clickbench_benchmark: ClickBenchBenchmark) -> None:
        """Test get_all_queries method."""
        with patch.object(clickbench_benchmark.query_manager, "get_all_queries") as mock_get_all:
            mock_get_all.return_value = {"Q1": "SELECT ...", "Q2": "SELECT ..."}

            result = clickbench_benchmark.get_all_queries()

            mock_get_all.assert_called_once()
            assert result == {"Q1": "SELECT ...", "Q2": "SELECT ..."}

    def test_csv_parsing_edge_cases(self, clickbench_benchmark: ClickBenchBenchmark) -> None:
        """Test CSV parsing with various edge cases."""
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_file = Path(temp_dir) / "hits.csv"
            # Test with pipe delimiters and 105 columns (as per ClickBench schema)
            row_values = [
                "123",
                "1",
                "Title1",
                "1",
                "2023-01-01 12:00:00",
                "2023-01-01",
                "456",
                "127",
                "1",
                "789",
                "http://example.com",
                "",
                "search phrase",
                "1",
                "1920",
                "1080",
            ]
            # Pad with empty strings to reach 105 columns
            row_values.extend([""] * (105 - len(row_values)))
            csv_file.write_text("|".join(row_values) + "\n")

            clickbench_benchmark.tables = {"hits": str(csv_file)}

            # mock connection that tracks the data being inserted
            mock_connection = Mock()
            mock_connection.executescript = Mock()
            mock_connection.executemany = Mock()
            mock_connection.commit = Mock()

            with patch.object(ClickBenchBenchmark, "get_create_tables_sql") as mock_get_sql:
                mock_get_sql.return_value = "CREATE TABLE hits (...);"

                clickbench_benchmark.load_data_to_database(mock_connection)

                # Verify executemany was called with the right data
                call_args = mock_connection.executemany.call_args
                assert call_args is not None
                sql, data = call_args[0]
                assert "INSERT INTO hits VALUES" in sql
                assert len(data) == 1
                # Check that the first few fields are parsed correctly
                assert data[0][0] == "123"  # WatchID
                assert data[0][1] == "1"  # JavaEnable
                assert data[0][2] == "Title1"  # Title
