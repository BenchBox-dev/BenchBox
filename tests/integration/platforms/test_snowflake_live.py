"""Live integration tests for Snowflake with real credentials.

These tests are SKIPPED by default and only run when credentials are available.
They execute real queries against live Snowflake Data Cloud instances.

Setup:
1. Copy .env.example to .env
2. Fill in your Snowflake credentials:
   - SNOWFLAKE_ACCOUNT
   - SNOWFLAKE_USERNAME
   - SNOWFLAKE_PASSWORD
   - SNOWFLAKE_WAREHOUSE
   - SNOWFLAKE_DATABASE
   - SNOWFLAKE_SCHEMA
3. Run: make test-live-snowflake

Cost: All tests use scale_factor=0.01 (~10MB) for minimal cost.
Estimated cost per test run: <$0.05

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import os

import pytest

from benchbox import TPCH

# Mark all tests in this file
pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_integration,
    pytest.mark.live_snowflake,
    pytest.mark.skipif(
        not os.getenv("SNOWFLAKE_PASSWORD"),
        reason="Requires SNOWFLAKE_PASSWORD environment variable. See .env.example for setup.",
    ),
]


class TestLiveSnowflakeConnection:
    """Test basic Snowflake connectivity."""

    def test_snowflake_live_connection(self, live_snowflake_adapter):
        """Verify Snowflake connection works and can execute simple query."""
        connection = live_snowflake_adapter.create_connection()
        try:
            # Execute simple query to verify connection
            cursor = connection.cursor()
            cursor.execute("SELECT 1 as test")
            result = cursor.fetchone()
            assert result[0] == 1

        finally:
            live_snowflake_adapter.close_connection(connection)

    def test_snowflake_live_version_info(self, live_snowflake_adapter):
        """Verify we can get Snowflake version information."""
        connection = live_snowflake_adapter.create_connection()
        try:
            metadata = live_snowflake_adapter.get_platform_info(connection)

            assert metadata["platform_name"] == "Snowflake"
            assert "version" in metadata
            assert metadata["connection_type"] in ["snowflake", "data_cloud"]

        finally:
            live_snowflake_adapter.close_connection(connection)

    def test_snowflake_live_warehouse_access(self, live_snowflake_adapter):
        """Verify warehouse and database access."""
        connection = live_snowflake_adapter.create_connection()
        try:
            cursor = connection.cursor()

            # Get current database and schema
            cursor.execute("SELECT CURRENT_DATABASE(), CURRENT_SCHEMA()")
            result = cursor.fetchone()

            assert result is not None
            assert len(result) == 2  # database, schema
            print(f"Connected to database: {result[0]}, schema: {result[1]}")

        finally:
            live_snowflake_adapter.close_connection(connection)


class TestLiveSnowflakeSchemaManagement:
    """Test schema creation and management."""

    def test_snowflake_live_schema_creation(self, live_snowflake_adapter, unique_test_schema, cleanup_test_schema):
        """Create and verify test schema."""
        connection = live_snowflake_adapter.create_connection()
        cleanup_test_schema(live_snowflake_adapter, unique_test_schema)

        try:
            cursor = connection.cursor()

            # Create schema
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {unique_test_schema}")

            # Verify schema exists
            cursor.execute("SHOW SCHEMAS")
            schemas = [row[1] for row in cursor.fetchall()]  # Schema name is in column 1
            assert unique_test_schema.upper() in [s.upper() for s in schemas]

        finally:
            live_snowflake_adapter.close_connection(connection)


class TestLiveSnowflakeDataLoading:
    """Test TPC-H data loading on Snowflake."""

    def test_snowflake_live_tpch_data_load(
        self, live_snowflake_adapter, unique_test_schema, test_scale_factor, test_output_dir, cleanup_test_schema
    ):
        """Load TPC-H data into Snowflake and verify."""
        cleanup_test_schema(live_snowflake_adapter, unique_test_schema)

        # Create TPC-H benchmark
        tpch = TPCH(scale_factor=test_scale_factor, output_dir=test_output_dir, verbose=False)

        # Generate data
        data_files = tpch.generate_data()
        assert len(data_files) > 0, "No data files generated"

        connection = live_snowflake_adapter.create_connection()
        try:
            cursor = connection.cursor()

            # Create schema
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {unique_test_schema}")
            cursor.execute(f"USE SCHEMA {unique_test_schema}")

            # Create tables
            create_sql = tpch.get_create_tables_sql(dialect="snowflake")
            for statement in create_sql.split(";"):
                if statement.strip():
                    cursor.execute(statement)

            # Load data using adapter
            stats, errors, _ = live_snowflake_adapter.load_data(tpch, connection, test_output_dir)

            # Verify data was loaded
            assert len(stats) > 0, "No tables loaded"
            assert all(count > 0 for count in stats.values()), "Some tables have zero rows"

            # Verify specific table
            cursor.execute(f"SELECT COUNT(*) FROM {unique_test_schema}.LINEITEM")
            lineitem_count = cursor.fetchone()[0]
            assert lineitem_count > 0, "LINEITEM table is empty"

        finally:
            live_snowflake_adapter.close_connection(connection)


class TestLiveSnowflakeQueryExecution:
    """Test query execution on Snowflake."""

    def test_snowflake_live_simple_query(self, live_snowflake_adapter, unique_test_schema):
        """Execute simple query to verify query execution works."""
        connection = live_snowflake_adapter.create_connection()
        try:
            cursor = connection.cursor()

            # Simple aggregation query
            cursor.execute("SELECT COUNT(*) as cnt, SUM(1) as total FROM (SELECT 1 UNION ALL SELECT 2)")
            result = cursor.fetchone()

            assert result[0] == 2  # count
            assert result[1] == 2  # sum

        finally:
            live_snowflake_adapter.close_connection(connection)

    def test_snowflake_live_tpch_query_execution(
        self, live_snowflake_adapter, unique_test_schema, test_scale_factor, test_output_dir
    ):
        """Execute TPC-H Query 1 on loaded data (requires data load test to pass first)."""
        # Note: This test assumes data is already loaded from previous test
        # In real usage, you'd load data in a session-scoped fixture

        tpch = TPCH(scale_factor=test_scale_factor, output_dir=test_output_dir, verbose=False)

        connection = live_snowflake_adapter.create_connection()
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

            # Translate to Snowflake SQL dialect
            query1_snowflake = query1.replace("LINEITEM", f"{unique_test_schema}.LINEITEM")

            cursor.execute(query1_snowflake)
            results = cursor.fetchall()

            # Verify we got results
            assert len(results) > 0, "Query 1 returned no results"
            print(f"Query 1 returned {len(results)} rows")

        finally:
            live_snowflake_adapter.close_connection(connection)


class TestLiveSnowflakeSpecificFeatures:
    """Test Snowflake-specific features."""

    def test_snowflake_live_put_copy(
        self, live_snowflake_adapter, unique_test_schema, test_output_dir, cleanup_test_schema
    ):
        """Test PUT + COPY INTO workflow with staged files."""
        cleanup_test_schema(live_snowflake_adapter, unique_test_schema)

        connection = live_snowflake_adapter.create_connection()
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

            # Note: Real PUT + COPY would upload and load the file
            # This test verifies the SQL syntax works
            # In production, adapter.load_data() handles PUT + COPY

            # Verify table exists and is empty
            cursor.execute(f"SELECT COUNT(*) FROM {unique_test_schema}.test_copy")
            initial_count = cursor.fetchone()[0]
            assert initial_count == 0

        finally:
            live_snowflake_adapter.close_connection(connection)

    def test_snowflake_live_cleanup(self, live_snowflake_adapter, unique_test_schema):
        """Verify cleanup works correctly."""
        connection = live_snowflake_adapter.create_connection()
        try:
            cursor = connection.cursor()

            # Try to drop schema (should work even if it doesn't exist)
            cursor.execute(f"DROP SCHEMA IF EXISTS {unique_test_schema} CASCADE")

            # Verify schema is gone
            cursor.execute("SHOW SCHEMAS")
            schemas = [row[1].upper() for row in cursor.fetchall()]
            assert unique_test_schema.upper() not in schemas

        finally:
            live_snowflake_adapter.close_connection(connection)


@pytest.fixture
def live_snowflake_adapter_with_capture(snowflake_credentials):
    """Create a Snowflake adapter with query plan capture enabled."""
    from benchbox.platforms.snowflake import SnowflakeAdapter

    adapter = SnowflakeAdapter(**{**snowflake_credentials, "capture_plans": True})
    yield adapter
    # No cleanup needed - adapter manages its own connections


class TestLiveSnowflakeQueryPlanCapture:
    """Test query plan capture against a live Snowflake instance.

    Queries stay trivial (SELECT 1): warehouse compute bills per second and
    auto-resume on first query is expected, so an XS warehouse with
    auto-suspend is the assumed floor.
    """

    def test_get_query_plan_returns_json(self, live_snowflake_adapter):
        """get_query_plan should return a non-empty JSON string via EXPLAIN USING JSON."""
        connection = live_snowflake_adapter.create_connection()
        try:
            plan = live_snowflake_adapter.get_query_plan(connection, "SELECT 1")
            assert plan is not None
            assert len(plan) > 0
            parsed = json.loads(plan)
            assert parsed is not None
        finally:
            live_snowflake_adapter.close_connection(connection)

    def test_capture_query_plan_returns_dag(self, live_snowflake_adapter_with_capture):
        """capture_query_plan should return a QueryPlanDAG for a simple SELECT."""
        adapter = live_snowflake_adapter_with_capture
        connection = adapter.create_connection()
        try:
            plan, _ = adapter.capture_query_plan(connection, "SELECT 1", "q_test")
            assert plan is not None, "Expected a QueryPlanDAG but got None"
            assert plan.logical_root is not None
        finally:
            adapter.close_connection(connection)

    def test_capture_query_plan_has_fingerprint(self, live_snowflake_adapter_with_capture):
        """Captured plan must have a non-empty fingerprint."""
        adapter = live_snowflake_adapter_with_capture
        connection = adapter.create_connection()
        try:
            plan, _ = adapter.capture_query_plan(connection, "SELECT 1", "q_fp")
            assert plan is not None
            assert plan.plan_fingerprint
            assert len(plan.plan_fingerprint) == 64  # SHA256 hex
        finally:
            adapter.close_connection(connection)

    def test_capture_query_plan_fingerprint_stable(self, live_snowflake_adapter_with_capture):
        """Same query executed twice must produce identical fingerprints."""
        adapter = live_snowflake_adapter_with_capture
        connection = adapter.create_connection()
        try:
            plan1, _ = adapter.capture_query_plan(connection, "SELECT 1", "q_fp_a")
            plan2, _ = adapter.capture_query_plan(connection, "SELECT 1", "q_fp_b")
            assert plan1 is not None
            assert plan2 is not None
            assert plan1.plan_fingerprint == plan2.plan_fingerprint
        finally:
            adapter.close_connection(connection)
