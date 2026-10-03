"""Integration tests for Metadata Primitives benchmark with DuckDB.

This module tests end-to-end execution of metadata queries against a live DuckDB
database. Unlike Read/Write Primitives, these tests don't require data generation -
they query the database's own catalog metadata.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.metadata_primitives import (
    MetadataPrimitivesBenchmark,
    MetadataPrimitivesQueryManager,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]


@pytest.fixture
def duckdb_connection():
    """Create a DuckDB connection with some sample tables."""
    import duckdb

    conn = duckdb.connect(":memory:")

    # Create sample tables to have metadata to query
    conn.execute("""
        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(255),
            created_at TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            total_amount DECIMAL(10, 2),
            order_date DATE,
            status VARCHAR(20)
        )
    """)

    conn.execute("""
        CREATE TABLE products (
            product_id INTEGER PRIMARY KEY,
            name VARCHAR(200),
            price DECIMAL(10, 2),
            category VARCHAR(50)
        )
    """)

    conn.execute("""
        CREATE VIEW active_orders AS
        SELECT * FROM orders WHERE status = 'active'
    """)

    yield conn
    conn.close()


@pytest.mark.integration
class TestMetadataPrimitivesQueryExecution:
    """Test metadata query execution against DuckDB."""

    def test_schema_list_schemata(self, duckdb_connection):

        manager = MetadataPrimitivesQueryManager()
        sql = manager.get_query("schema_list_schemata", dialect="duckdb")

        result = duckdb_connection.execute(sql).fetchall()
        assert len(result) > 0

        # Should find main schema
        schema_names = [row[0] for row in result]
        assert "main" in schema_names

    def test_schema_list_tables(self, duckdb_connection):

        manager = MetadataPrimitivesQueryManager()
        sql = manager.get_query("schema_list_tables", dialect="duckdb")

        result = duckdb_connection.execute(sql).fetchall()
        assert len(result) >= 3  # customers, orders, products

        table_names = [row[0] for row in result]
        assert "customers" in table_names
        assert "orders" in table_names
        assert "products" in table_names

    def test_schema_list_views(self, duckdb_connection):

        manager = MetadataPrimitivesQueryManager()
        sql = manager.get_query("schema_list_views", dialect="duckdb")

        result = duckdb_connection.execute(sql).fetchall()
        # Should find our active_orders view
        view_names = [row[0] for row in result]
        assert "active_orders" in view_names

    def test_schema_table_count(self, duckdb_connection):

        manager = MetadataPrimitivesQueryManager()
        sql = manager.get_query("schema_table_count", dialect="duckdb")

        result = duckdb_connection.execute(sql).fetchall()
        assert len(result) == 1
        count = result[0][0]
        assert count >= 3  # At least our 3 tables

    def test_column_list_all(self, duckdb_connection):

        manager = MetadataPrimitivesQueryManager()
        sql = manager.get_query("column_list_all", dialect="duckdb")

        result = duckdb_connection.execute(sql).fetchall()
        assert len(result) > 0

        # Should find columns from our tables
        column_names = [row[2] for row in result]  # column_name is 3rd
        assert "customer_id" in column_names
        assert "order_id" in column_names

    def test_column_data_types(self, duckdb_connection):

        manager = MetadataPrimitivesQueryManager()
        sql = manager.get_query("column_data_types", dialect="duckdb")

        result = duckdb_connection.execute(sql).fetchall()
        assert len(result) > 0

        # Should find various data types
        data_types = [row[0] for row in result]
        # Check for presence of common types (case insensitive)
        data_types_upper = [dt.upper() for dt in data_types]
        has_integer = any("INT" in dt for dt in data_types_upper)
        has_varchar = any("VARCHAR" in dt for dt in data_types_upper)
        assert has_integer or has_varchar

    def test_stats_column_count_summary(self, duckdb_connection):

        manager = MetadataPrimitivesQueryManager()
        sql = manager.get_query("stats_column_count_summary", dialect="duckdb")

        result = duckdb_connection.execute(sql).fetchall()
        assert len(result) == 1

        total_tables, total_columns, avg_columns = result[0]
        assert total_tables >= 3
        assert total_columns >= 10
        assert avg_columns > 0

    def test_query_explain_simple(self, duckdb_connection):

        manager = MetadataPrimitivesQueryManager()
        sql = manager.get_query("query_explain_simple", dialect="duckdb")

        result = duckdb_connection.execute(sql).fetchall()
        assert len(result) > 0


@pytest.mark.integration
class TestMetadataPrimitivesBenchmarkExecution:
    """Test full benchmark execution with DuckDB."""

    def test_execute_single_query(self, duckdb_connection):

        benchmark = MetadataPrimitivesBenchmark()

        result = benchmark.execute_query(
            "schema_list_tables",
            duckdb_connection,
            dialect="duckdb",
        )

        assert result.success is True
        assert result.query_id == "schema_list_tables"
        assert result.category == "schema"
        assert result.execution_time_ms > 0
        assert result.row_count >= 0

    def test_execute_query_with_error(self, duckdb_connection):

        benchmark = MetadataPrimitivesBenchmark()

        # Force an error by passing invalid dialect (to trigger skip_on)
        result = benchmark.execute_query(
            "schema_list_views",
            duckdb_connection,
            dialect="clickhouse",  # This is in skip_on
        )

        assert result.success is False
        assert result.error is not None

    def test_run_benchmark_all_queries(self, duckdb_connection):

        benchmark = MetadataPrimitivesBenchmark()

        result = benchmark.run_benchmark(
            duckdb_connection,
            dialect="duckdb",
        )

        assert result.total_queries > 0
        assert result.successful_queries > 0
        # Some queries might fail due to DuckDB-specific limitations
        assert result.total_time_ms > 0
        assert len(result.results) > 0
        assert len(result.category_summary) > 0

    def test_run_benchmark_by_category(self, duckdb_connection):

        benchmark = MetadataPrimitivesBenchmark()

        result = benchmark.run_benchmark(
            duckdb_connection,
            dialect="duckdb",
            categories=["schema"],
        )

        assert result.total_queries > 0
        # All results should be in schema category
        for qr in result.results:
            assert qr.category == "schema"

    def test_run_benchmark_specific_queries(self, duckdb_connection):

        benchmark = MetadataPrimitivesBenchmark()

        result = benchmark.run_benchmark(
            duckdb_connection,
            dialect="duckdb",
            query_ids=["schema_list_tables", "column_list_all"],
        )

        assert result.total_queries == 2
        query_ids = {r.query_id for r in result.results}
        assert "schema_list_tables" in query_ids
        assert "column_list_all" in query_ids

    def test_run_benchmark_with_iterations(self, duckdb_connection):

        benchmark = MetadataPrimitivesBenchmark()

        result = benchmark.run_benchmark(
            duckdb_connection,
            dialect="duckdb",
            query_ids=["schema_list_tables"],
            iterations=3,
        )

        # Should have 3 results for the same query
        assert result.total_queries == 3
        assert all(r.query_id == "schema_list_tables" for r in result.results)

    def test_category_summary(self, duckdb_connection):

        benchmark = MetadataPrimitivesBenchmark()

        result = benchmark.run_benchmark(
            duckdb_connection,
            dialect="duckdb",
            categories=["schema", "column"],
        )

        assert "schema" in result.category_summary
        assert "column" in result.category_summary

        schema_summary = result.category_summary["schema"]
        assert "total_queries" in schema_summary
        assert "successful" in schema_summary
        assert "avg_time_ms" in schema_summary


@pytest.mark.integration
class TestAllQueriesExecute:
    """Test that all queries can execute without SQL errors."""

    def test_all_duckdb_queries_execute(self, duckdb_connection):
        """Test that all DuckDB-compatible queries execute successfully."""
        manager = MetadataPrimitivesQueryManager()
        queries = manager.get_queries_for_dialect("duckdb")

        failed_queries = []
        for query_id, sql in queries.items():
            try:
                duckdb_connection.execute(sql).fetchall()
            except Exception as e:
                failed_queries.append((query_id, str(e)))

        # Report failures
        if failed_queries:
            failure_msg = "\n".join(f"  {qid}: {err}" for qid, err in failed_queries)
            pytest.fail(f"The following queries failed:\n{failure_msg}")

    def test_schema_category_queries(self, duckdb_connection):
        """Test all schema category queries execute."""
        manager = MetadataPrimitivesQueryManager()
        schema_queries = manager.get_queries_by_category("schema")

        for query_id in schema_queries:
            try:
                sql = manager.get_query(query_id, dialect="duckdb")
                duckdb_connection.execute(sql).fetchall()
            except ValueError:
                # Skip if query not supported on duckdb
                continue

    def test_column_category_queries(self, duckdb_connection):
        """Test all column category queries execute."""
        manager = MetadataPrimitivesQueryManager()
        column_queries = manager.get_queries_by_category("column")

        for query_id in column_queries:
            try:
                sql = manager.get_query(query_id, dialect="duckdb")
                duckdb_connection.execute(sql).fetchall()
            except ValueError:
                # Skip if query not supported on duckdb
                continue

    def test_stats_category_queries(self, duckdb_connection):
        """Test all stats category queries execute."""
        manager = MetadataPrimitivesQueryManager()
        stats_queries = manager.get_queries_by_category("stats")

        for query_id in stats_queries:
            try:
                sql = manager.get_query(query_id, dialect="duckdb")
                duckdb_connection.execute(sql).fetchall()
            except ValueError:
                # Skip if query not supported on duckdb
                continue


@pytest.mark.integration
class TestBenchmarkLoaderIntegration:
    """Test benchmark loader integration."""

    def test_benchmark_loads_from_loader(self):

        from benchbox.core.benchmark_loader import get_benchmark_class

        benchmark_class = get_benchmark_class("metadata_primitives")
        assert benchmark_class == MetadataPrimitivesBenchmark

        # Verify we can instantiate it
        benchmark = benchmark_class()
        assert benchmark._name == "Metadata Primitives Benchmark"
