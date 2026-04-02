# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""
Live integration tests for Firebolt Cloud.

Setup:
1. Create a Firebolt Cloud account and provision an engine
2. Create a service account with client ID and secret
3. Set environment variables:
   - FIREBOLT_CLIENT_ID
   - FIREBOLT_CLIENT_SECRET
   - FIREBOLT_ACCOUNT_NAME
   - FIREBOLT_ENGINE_NAME
   - FIREBOLT_DATABASE (optional, defaults to 'benchbox')
4. Run: make test-live-firebolt

These tests use scale_factor=0.01 for minimal cost.
"""

import os

import pytest

from benchbox import TPCH

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_integration,
    pytest.mark.live_firebolt,
    pytest.mark.skipif(
        not os.getenv("FIREBOLT_CLIENT_ID"),
        reason="Requires FIREBOLT_CLIENT_ID environment variable. See docstring for setup.",
    ),
]


@pytest.fixture(scope="module")
def tpch_data(live_firebolt_adapter, test_scale_factor, test_output_dir):
    """Load TPC-H data into Firebolt once per module; drop tables on teardown."""
    tpch = TPCH(scale_factor=test_scale_factor, output_dir=test_output_dir, verbose=False)
    data_files = tpch.generate_data()
    assert len(data_files) > 0, "No data files generated"

    connection = live_firebolt_adapter.create_connection()
    try:
        live_firebolt_adapter.create_schema(tpch, connection)
        stats, _errors, _ = live_firebolt_adapter.load_data(tpch, connection, test_output_dir)
        yield tpch, stats
    finally:
        try:
            cursor = connection.cursor()
            for table in ["lineitem", "orders", "customer", "part", "partsupp", "supplier", "nation", "region"]:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
            cursor.close()
        except Exception:
            pass
        live_firebolt_adapter.close_connection(connection)


class TestLiveFireboltConnection:
    """Test basic Firebolt Cloud connectivity."""

    def test_connection(self, live_firebolt_adapter):
        """Verify we can connect to Firebolt and run a trivial query."""
        connection = live_firebolt_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1
        finally:
            live_firebolt_adapter.close_connection(connection)

    def test_platform_info(self, live_firebolt_adapter):
        """Verify platform info reports correct metadata."""
        info = live_firebolt_adapter.get_platform_info()
        assert info is not None
        assert info.get("platform_type") == "firebolt"
        assert info.get("platform_name")
        assert "configuration" in info


class TestLiveFireboltQueryExecution:
    """Test query execution against a live Firebolt instance."""

    def test_create_and_query_table(self, live_firebolt_adapter):
        """Create a test table, insert data, and query it."""
        connection = live_firebolt_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("DROP TABLE IF EXISTS benchbox_smoke_test")
            cursor.execute("CREATE TABLE benchbox_smoke_test (id INT, name TEXT, value DOUBLE PRECISION)")
            cursor.execute(
                "INSERT INTO benchbox_smoke_test VALUES (1, 'alpha', 10.5), (2, 'beta', 20.3), (3, 'gamma', 30.1)"
            )
            cursor.execute("SELECT COUNT(*) FROM benchbox_smoke_test")
            result = cursor.fetchone()
            assert result[0] == 3
        finally:
            try:
                cursor = connection.cursor()
                cursor.execute("DROP TABLE IF EXISTS benchbox_smoke_test")
            except Exception:
                pass
            live_firebolt_adapter.close_connection(connection)

    def test_aggregation_query(self, live_firebolt_adapter):
        """Execute an aggregation query to verify analytical capabilities."""
        connection = live_firebolt_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT COUNT(*) AS cnt, SUM(x) AS total FROM (SELECT 1 AS x UNION ALL SELECT 2 UNION ALL SELECT 3)"
            )
            result = cursor.fetchone()
            assert result[0] == 3
            assert result[1] == 6
        finally:
            live_firebolt_adapter.close_connection(connection)

    def test_tpch_query_1(self, live_firebolt_adapter, tpch_data):
        """Execute TPC-H Query 1 against the module-loaded dataset."""
        tpch, _stats = tpch_data
        connection = live_firebolt_adapter.create_connection()
        try:
            cursor = connection.cursor()
            query1 = tpch.get_query(1, seed=42)
            cursor.execute(query1)
            results = cursor.fetchall()
            assert len(results) > 0, "TPC-H Query 1 returned no results"
        finally:
            live_firebolt_adapter.close_connection(connection)


class TestLiveFireboltSchemaManagement:
    """Test database creation and management on Firebolt (uses databases, not schemas)."""

    def test_create_and_drop_database(self, live_firebolt_adapter):
        """Create a test database and verify it can be dropped."""
        db_name = "benchbox_schema_test"
        connection = live_firebolt_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")
            # Verify database exists via SHOW DATABASES
            cursor.execute("SHOW DATABASES")
            databases = [row[0] for row in cursor.fetchall()]
            assert db_name in databases, f"Expected {db_name} in SHOW DATABASES"
        finally:
            try:
                cursor = connection.cursor()
                cursor.execute(f"DROP DATABASE IF EXISTS {db_name}")
            except Exception:
                pass
            live_firebolt_adapter.close_connection(connection)


class TestLiveFireboltDataLoading:
    """Test TPC-H data loading on Firebolt."""

    def test_tpch_data_load(self, tpch_data):
        """Verify TPC-H data was loaded with non-zero row counts in every table."""
        _tpch, stats = tpch_data
        assert len(stats) > 0, "No tables loaded"
        assert all(count > 0 for count in stats.values()), "Some tables have zero rows"


class TestLiveFireboltSpecificFeatures:
    """Test Firebolt-specific features."""

    def test_result_cache_control(self, live_firebolt_adapter):
        """Verify result cache can be disabled for accurate benchmarking."""
        connection = live_firebolt_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SET enable_result_cache = false")
            # Confirm the setting was accepted by running a query
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1
        finally:
            live_firebolt_adapter.close_connection(connection)

    def test_drop_table_is_synchronous(self, live_firebolt_adapter):
        """Verify DROP TABLE completes synchronously — table is immediately gone after drop."""
        connection = live_firebolt_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS benchbox_cleanup_test (id INT)")
            cursor.execute("DROP TABLE IF EXISTS benchbox_cleanup_test")
            # Verify table is gone
            try:
                cursor.execute("SELECT COUNT(*) FROM benchbox_cleanup_test")
                pytest.fail("Table should have been dropped")
            except Exception:
                pass  # Expected — table does not exist
        finally:
            live_firebolt_adapter.close_connection(connection)
