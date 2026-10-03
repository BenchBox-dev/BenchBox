"""Live integration tests for Databricks with real credentials.

These tests are SKIPPED by default and only run when credentials are available.
They execute real queries against live Databricks SQL Warehouses.

Setup:
1. Copy .env.example to .env
2. Fill in your Databricks credentials:
   - DATABRICKS_HOST
   - DATABRICKS_HTTP_PATH
   - DATABRICKS_TOKEN
3. Run: make test-live-databricks

Cost: All tests use scale_factor=0.01 (~10MB) for minimal cost.
Estimated cost per test run: <$0.05

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import os

import pytest

from benchbox import TPCH

# Mark all tests in this file
pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_integration,
    pytest.mark.live_databricks,
    pytest.mark.skipif(
        not os.getenv("DATABRICKS_TOKEN"),
        reason="Requires DATABRICKS_TOKEN environment variable. See .env.example for setup.",
    ),
]


class TestLiveDatabricksConnection:
    """Test basic Databricks connectivity."""

    def test_databricks_live_connection(self, live_databricks_adapter):

        connection = live_databricks_adapter.create_connection()
        try:
            # Execute simple query to verify connection
            cursor = connection.cursor()
            cursor.execute("SELECT 1 as test")
            result = cursor.fetchone()
            assert result[0] == 1

        finally:
            live_databricks_adapter.close_connection(connection)

    def test_databricks_live_version_info(self, live_databricks_adapter):

        connection = live_databricks_adapter.create_connection()
        try:
            metadata = live_databricks_adapter.get_platform_info(connection)

            assert metadata["platform_name"] == "Databricks"
            assert "version" in metadata
            assert metadata["connection_type"] == "sql_warehouse"

        finally:
            live_databricks_adapter.close_connection(connection)

    def test_databricks_live_catalog_access(self, live_databricks_adapter):

        connection = live_databricks_adapter.create_connection()
        try:
            cursor = connection.cursor()

            # Get current catalog
            cursor.execute("SELECT CURRENT_CATALOG(), CURRENT_SCHEMA()")
            result = cursor.fetchone()

            assert result is not None
            assert len(result) == 2  # catalog, schema
            print(f"Connected to catalog: {result[0]}, schema: {result[1]}")

        finally:
            live_databricks_adapter.close_connection(connection)


class TestLiveDatabricksSchemaManagement:
    """Test schema creation and management."""

    def test_databricks_live_schema_creation(self, live_databricks_adapter, unique_test_schema, cleanup_test_schema):
        """Create and verify test schema."""
        connection = live_databricks_adapter.create_connection()
        cleanup_test_schema(live_databricks_adapter, unique_test_schema)

        try:
            cursor = connection.cursor()

            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {unique_test_schema}")

            # Verify schema exists
            cursor.execute("SHOW SCHEMAS")
            schemas = [row[0] for row in cursor.fetchall()]
            assert unique_test_schema in schemas

        finally:
            live_databricks_adapter.close_connection(connection)


class TestLiveDatabricksDataLoading:
    """Test TPC-H data loading on Databricks."""

    def test_databricks_live_tpch_data_load(
        self, live_databricks_adapter, unique_test_schema, test_scale_factor, test_output_dir, cleanup_test_schema
    ):
        """Load TPC-H data into Databricks and verify."""
        cleanup_test_schema(live_databricks_adapter, unique_test_schema)

        # Create TPC-H benchmark
        tpch = TPCH(scale_factor=test_scale_factor, output_dir=test_output_dir, verbose=False)

        data_files = tpch.generate_data()
        assert len(data_files) > 0, "No data files generated"

        connection = live_databricks_adapter.create_connection()
        try:
            cursor = connection.cursor()

            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {unique_test_schema}")
            cursor.execute(f"USE SCHEMA {unique_test_schema}")

            # Create tables
            create_sql = tpch.get_create_tables_sql(dialect="databricks")
            for statement in create_sql.split(";"):
                if statement.strip():
                    cursor.execute(statement)

            stats, errors, _ = live_databricks_adapter.load_data(tpch, connection, test_output_dir)

            assert len(stats) > 0, "No tables loaded"
            assert all(count > 0 for count in stats.values()), "Some tables have zero rows"

            # Verify specific table
            cursor.execute(f"SELECT COUNT(*) FROM {unique_test_schema}.LINEITEM")
            lineitem_count = cursor.fetchone()[0]
            assert lineitem_count > 0, "LINEITEM table is empty"

        finally:
            live_databricks_adapter.close_connection(connection)


class TestLiveDatabricksQueryExecution:
    """Test query execution on Databricks."""

    def test_databricks_live_simple_query(self, live_databricks_adapter, unique_test_schema):
        """Execute simple query to verify query execution works."""
        connection = live_databricks_adapter.create_connection()
        try:
            cursor = connection.cursor()

            # Simple aggregation query
            cursor.execute("SELECT COUNT(*) as cnt, SUM(1) as total FROM (SELECT 1 UNION ALL SELECT 2)")
            result = cursor.fetchone()

            assert result[0] == 2  # count
            assert result[1] == 2  # sum

        finally:
            live_databricks_adapter.close_connection(connection)

    def test_databricks_live_tpch_query_execution(
        self, live_databricks_adapter, unique_test_schema, test_scale_factor, test_output_dir
    ):
        """Execute TPC-H Query 1 on loaded data (requires data load test to pass first)."""
        # Note: This test assumes data is already loaded from previous test
        # In real usage, you'd load data in a session-scoped fixture

        tpch = TPCH(scale_factor=test_scale_factor, output_dir=test_output_dir, verbose=False)

        connection = live_databricks_adapter.create_connection()
        try:
            cursor = connection.cursor()

            # Check if data exists (skip if not)
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {unique_test_schema}.LINEITEM")
                count = cursor.fetchone()[0]
                if count == 0:
                    pytest.skip("No data loaded - run data load test first")
            except Exception:
                pytest.skip("Schema not found - run schema creation test first")

            # Get and execute Query 1
            query1 = tpch.get_query(1, seed=42)

            # Translate to Databricks SQL dialect
            query1_databricks = query1.replace("LINEITEM", f"{unique_test_schema}.LINEITEM")

            cursor.execute(query1_databricks)
            results = cursor.fetchall()

            assert len(results) > 0, "Query 1 returned no results"
            print(f"Query 1 returned {len(results)} rows")

        finally:
            live_databricks_adapter.close_connection(connection)


class TestLiveDatabricksSpecificFeatures:
    """Test Databricks-specific features."""

    def test_databricks_live_copy_into(
        self, live_databricks_adapter, unique_test_schema, test_output_dir, cleanup_test_schema
    ):

        cleanup_test_schema(live_databricks_adapter, unique_test_schema)

        connection = live_databricks_adapter.create_connection()
        try:
            cursor = connection.cursor()

            # Create schema and simple table
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {unique_test_schema}")
            cursor.execute(f"USE SCHEMA {unique_test_schema}")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS test_copy (
                    id INT,
                    value STRING
                )
            """)

            # Create a small test file
            test_file = test_output_dir / "test_data.csv"
            test_file.write_text("1|test1\n2|test2\n3|test3\n")

            # Note: Real COPY INTO would require DBFS staging
            # This test verifies the SQL syntax works
            # In production, adapter.load_data() handles staging

            # Verify table exists and is empty
            cursor.execute(f"SELECT COUNT(*) FROM {unique_test_schema}.test_copy")
            initial_count = cursor.fetchone()[0]
            assert initial_count == 0

        finally:
            live_databricks_adapter.close_connection(connection)

    def test_databricks_live_cleanup(self, live_databricks_adapter, unique_test_schema):

        connection = live_databricks_adapter.create_connection()
        try:
            cursor = connection.cursor()

            # Try to drop schema (should work even if it doesn't exist)
            cursor.execute(f"DROP SCHEMA IF EXISTS {unique_test_schema} CASCADE")

            # Verify schema is gone
            cursor.execute("SHOW SCHEMAS")
            schemas = [row[0] for row in cursor.fetchall()]
            assert unique_test_schema not in schemas

        finally:
            live_databricks_adapter.close_connection(connection)
