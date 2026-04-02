"""Integration tests for TSBS DevOps benchmark with DuckDB.

This module tests the TSBS DevOps implementation with a real DuckDB database,
focusing on data generation, schema creation, and query execution.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import duckdb
import pytest

from benchbox import TSBSDevOps

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]


@pytest.mark.duckdb
@pytest.mark.tsbs_devops
class TestTSBSDevOpsDuckDBIntegration:
    """Integration tests for TSBS DevOps benchmark with DuckDB."""

    @pytest.fixture
    def tsbs_benchmark(self, temp_dir):
        """Create a minimal TSBS DevOps instance for testing."""
        return TSBSDevOps(
            scale_factor=0.1,
            output_dir=temp_dir,
            num_hosts=5,
            duration_days=1,
            interval_seconds=3600,  # 1-hour intervals for smaller data
        )

    @pytest.fixture
    def duckdb_conn(self):
        """Create a temporary DuckDB database."""
        conn = duckdb.connect(":memory:")
        yield conn
        conn.close()

    def test_benchmark_instantiation(self, tsbs_benchmark):
        """Test that TSBS DevOps benchmark can be instantiated."""
        assert tsbs_benchmark.scale_factor == 0.1
        assert tsbs_benchmark.num_hosts == 5
        assert tsbs_benchmark._impl is not None

    def test_benchmark_info(self, tsbs_benchmark):
        """Test that benchmark info provides comprehensive metadata."""
        info = tsbs_benchmark.get_benchmark_info()

        # Check required fields
        assert "name" in info
        assert "description" in info
        assert "scale_factor" in info
        assert "num_hosts" in info
        assert "duration_days" in info
        assert "num_queries" in info
        assert "query_categories" in info
        assert "tables" in info

        # Check values
        assert info["name"] == "TSBS DevOps"
        assert info["scale_factor"] == 0.1
        assert info["num_hosts"] == 5
        assert info["num_queries"] == 18

    def test_get_queries(self, tsbs_benchmark):
        """Test that all queries can be retrieved."""
        queries = tsbs_benchmark.get_queries()

        # Should have 18 queries
        assert len(queries) == 18

        # Each query should be a non-empty SQL string
        for query_id, query_text in queries.items():
            assert isinstance(query_text, str), f"Query {query_id} should be a string"
            assert len(query_text.strip()) > 0, f"Query {query_id} should not be empty"
            assert "SELECT" in query_text.upper(), f"Query {query_id} should be a SELECT statement"

    def test_get_query_by_id(self, tsbs_benchmark):
        """Test retrieving individual queries."""
        # Test a known query ID
        query = tsbs_benchmark.get_query("single-host-12-hr")
        assert isinstance(query, str)
        assert "SELECT" in query.upper()
        assert "cpu" in query.lower()

    def test_get_queries_by_category(self, tsbs_benchmark):
        """Test filtering queries by category."""
        # Test aggregation category
        aggregation_queries = tsbs_benchmark.get_queries_by_category("aggregation")
        assert len(aggregation_queries) > 0

        # Test threshold category
        threshold_queries = tsbs_benchmark.get_queries_by_category("threshold")
        assert len(threshold_queries) > 0

        # Test single-host category
        single_host_queries = tsbs_benchmark.get_queries_by_category("single-host")
        assert len(single_host_queries) > 0

    def test_query_info(self, tsbs_benchmark):
        """Test that query metadata is available."""
        info = tsbs_benchmark.get_query_info("cpu-max-all-1-hr")

        assert "id" in info
        assert "name" in info
        assert "category" in info
        assert info["category"] == "aggregation"

    def test_schema_creation(self, tsbs_benchmark, duckdb_conn):
        """Test that schema can be created in DuckDB."""
        # Get schema SQL
        sql = tsbs_benchmark.get_create_tables_sql(dialect="duckdb")

        # Execute schema creation (split by semicolons)
        for statement in sql.strip().split(";"):
            stmt = statement.strip()
            if stmt and not stmt.startswith("--"):
                duckdb_conn.execute(stmt)

        # Verify tables were created
        tables_result = duckdb_conn.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            ORDER BY table_name
        """).fetchall()

        table_names = [row[0].lower() for row in tables_result]

        # TSBS DevOps should have these tables
        assert "tags" in table_names, "tags table should exist"
        assert "cpu" in table_names, "cpu table should exist"
        assert "mem" in table_names, "mem table should exist"
        assert "disk" in table_names, "disk table should exist"
        assert "net" in table_names, "net table should exist"

    def test_schema_columns(self, tsbs_benchmark):
        """Test that schema has correct column definitions."""
        schema = tsbs_benchmark.get_schema()

        # Check tags table
        assert "tags" in schema
        tags_columns = schema["tags"]["columns"]
        assert "hostname" in tags_columns
        assert "region" in tags_columns
        assert "datacenter" in tags_columns
        assert "service" in tags_columns

        # Check cpu table
        assert "cpu" in schema
        cpu_columns = schema["cpu"]["columns"]
        assert "time" in cpu_columns
        assert "hostname" in cpu_columns
        assert "usage_user" in cpu_columns
        assert "usage_system" in cpu_columns
        assert "usage_idle" in cpu_columns

        # Check mem table
        assert "mem" in schema
        mem_columns = schema["mem"]["columns"]
        assert "time" in mem_columns
        assert "hostname" in mem_columns
        assert "total" in mem_columns
        assert "used" in mem_columns

    def test_query_sql_syntax_validity(self, tsbs_benchmark):
        """Test that all queries have valid SQL syntax."""
        queries = tsbs_benchmark.get_queries()

        for query_id, query_text in queries.items():
            # Basic SQL syntax checks
            upper_sql = query_text.upper()
            assert "SELECT" in upper_sql, f"Query {query_id} should have SELECT"
            assert "FROM" in upper_sql, f"Query {query_id} should have FROM"

            # Should be well-formed (basic check)
            assert query_text.count("(") == query_text.count(")"), f"Query {query_id} should have balanced parentheses"

    def test_scale_factor_validation(self, temp_dir):
        """Test that invalid scale factors are rejected."""
        with pytest.raises(ValueError, match="must be positive"):
            TSBSDevOps(scale_factor=0, output_dir=temp_dir)

        with pytest.raises(ValueError, match="must be positive"):
            TSBSDevOps(scale_factor=-1.0, output_dir=temp_dir)

    def test_generation_stats(self, tsbs_benchmark):
        """Test that generation stats are available."""
        stats = tsbs_benchmark.get_generation_stats()

        assert "num_hosts" in stats
        assert stats["num_hosts"] == 5
        assert "duration_days" in stats
        assert "interval_seconds" in stats
        assert "rows" in stats
        assert "total_rows" in stats


@pytest.mark.integration
@pytest.mark.duckdb
@pytest.mark.tsbs_devops
@pytest.mark.slow
class TestTSBSDevOpsDataGeneration:
    """Integration tests for TSBS DevOps data generation (slower tests)."""

    @pytest.fixture
    def tsbs_with_data(self, temp_dir):
        """Create TSBS DevOps instance and generate data."""
        benchmark = TSBSDevOps(
            scale_factor=0.1,
            output_dir=temp_dir,
            num_hosts=3,
            duration_days=1,
            interval_seconds=3600,
        )
        benchmark.generate_data()
        return benchmark

    def test_data_generation_creates_files(self, tsbs_with_data):
        """Test that data generation creates expected files."""
        tables = tsbs_with_data.tables

        assert "tags" in tables
        assert "cpu" in tables
        assert "mem" in tables
        assert "disk" in tables
        assert "net" in tables

        # Files should exist
        for table_name, file_path in tables.items():
            assert file_path.exists(), f"{table_name} data file should exist"
            assert file_path.stat().st_size > 0, f"{table_name} data file should not be empty"

    def test_tags_data_structure(self, tsbs_with_data):
        """Test that tags data has correct structure."""
        import csv

        tags_file = tsbs_with_data.tables["tags"]

        with open(tags_file, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)

            # Should have expected columns
            expected_columns = [
                "hostname",
                "region",
                "datacenter",
                "rack",
                "os",
                "arch",
                "team",
                "service",
            ]

            for col in expected_columns:
                assert col in header, f"Column {col} should be in tags header"

            # Should have correct number of rows
            rows = list(reader)
            assert len(rows) == 3  # num_hosts = 3

    def test_cpu_data_structure(self, tsbs_with_data):
        """Test that CPU data has correct structure."""
        import csv

        cpu_file = tsbs_with_data.tables["cpu"]

        with open(cpu_file, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)

            # Should have expected columns
            expected_columns = [
                "time",
                "hostname",
                "usage_user",
                "usage_system",
                "usage_idle",
            ]

            for col in expected_columns:
                assert col in header, f"Column {col} should be in cpu header"

            # Sample first row
            first_row = next(reader)
            assert len(first_row) == len(header)

    def test_data_load_to_duckdb(self, tsbs_with_data):
        """Test that data can be loaded into DuckDB."""
        conn = duckdb.connect(":memory:")

        try:
            # Create schema
            sql = tsbs_with_data.get_create_tables_sql(dialect="duckdb")
            for statement in sql.strip().split(";"):
                stmt = statement.strip()
                if stmt and not stmt.startswith("--"):
                    conn.execute(stmt)

            # Load data
            for table_name, file_path in tsbs_with_data.tables.items():
                conn.execute(f"""
                    INSERT INTO {table_name}
                    SELECT * FROM read_csv('{file_path}', header=true, auto_detect=true)
                """)

            # Verify data was loaded
            tags_count = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
            assert tags_count == 3  # num_hosts

            cpu_count = conn.execute("SELECT COUNT(*) FROM cpu").fetchone()[0]
            assert cpu_count > 0

            mem_count = conn.execute("SELECT COUNT(*) FROM mem").fetchone()[0]
            assert mem_count > 0

        finally:
            conn.close()

    def test_queries_execute_on_data(self, tsbs_with_data):
        """Test that benchmark queries execute successfully on loaded data."""
        conn = duckdb.connect(":memory:")

        try:
            # Create schema and load data
            sql = tsbs_with_data.get_create_tables_sql(dialect="duckdb")
            for statement in sql.strip().split(";"):
                stmt = statement.strip()
                if stmt and not stmt.startswith("--"):
                    conn.execute(stmt)

            for table_name, file_path in tsbs_with_data.tables.items():
                conn.execute(f"""
                    INSERT INTO {table_name}
                    SELECT * FROM read_csv('{file_path}', header=true, auto_detect=true)
                """)

            # Try executing some queries
            test_queries = [
                "cpu-max-all-1-hr",
                "mem-by-host-1-hr",
            ]

            for query_id in test_queries:
                query_sql = tsbs_with_data.get_query(query_id)
                result = conn.execute(query_sql).fetchall()
                # Query should execute without error and return results
                assert isinstance(result, list), f"Query {query_id} should return results"

        finally:
            conn.close()
