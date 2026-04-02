# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""
Live integration tests for Starburst Galaxy (Trino-compatible).

Setup:
1. Create a Starburst Galaxy account and provision a cluster
2. Set environment variables:
   - STARBURST_HOST (e.g., your-cluster.galaxy.starburst.io)
   - STARBURST_USER
   - STARBURST_PASSWORD
   - STARBURST_CATALOG (optional, defaults to 'tpch')
   - STARBURST_SCHEMA (optional, defaults to 'sf1')
   - STARBURST_PORT (optional, defaults to 443)
3. Run: make test-live-starburst

These tests use the built-in TPC-H catalog available in Starburst Galaxy.

Write tests (SchemaManagement, DataLoading) require a writable catalog:
   - STARBURST_WRITABLE_CATALOG (e.g., 'memory' or a configured Hive/Iceberg catalog)

Without STARBURST_WRITABLE_CATALOG these tests are skipped — the default tpch
catalog is read-only and cannot accept DDL or DML.
"""

import os

import pytest
from trino.exceptions import TrinoUserError

from benchbox import TPCH

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_integration,
    pytest.mark.live_starburst,
    pytest.mark.skipif(
        not os.getenv("STARBURST_HOST"),
        reason="Requires STARBURST_HOST environment variable. See docstring for setup.",
    ),
]


@pytest.fixture(scope="module")
def starburst_writable_catalog():
    """Return the writable catalog name or skip the test.

    The default tpch catalog in Starburst Galaxy is read-only; write operations
    require a separate catalog (e.g. 'memory', 'hive', or an Iceberg catalog).
    Set STARBURST_WRITABLE_CATALOG to enable write tests.
    """
    catalog = os.getenv("STARBURST_WRITABLE_CATALOG")
    if not catalog:
        pytest.skip("Requires STARBURST_WRITABLE_CATALOG for write tests (tpch catalog is read-only)")
    return catalog


class TestLiveStarburstConnection:
    """Test basic Starburst Galaxy connectivity."""

    def test_connection(self, live_starburst_adapter):
        """Verify we can connect to Starburst Galaxy and run a trivial query."""
        connection = live_starburst_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1
        finally:
            live_starburst_adapter.close_connection(connection)

    def test_platform_info(self, live_starburst_adapter):
        """Verify platform info reports correct metadata."""
        info = live_starburst_adapter.get_platform_info()
        assert info is not None
        assert info.get("platform_type") == "starburst"
        assert info.get("platform_name")
        assert "configuration" in info


class TestLiveStarburstQueryExecution:
    """Test query execution against a live Starburst Galaxy cluster."""

    def test_tpch_query(self, live_starburst_adapter):
        """Execute a TPC-H-style aggregation query.

        Uses the built-in tpch catalog if available, otherwise runs a
        standalone aggregation.
        """
        connection = live_starburst_adapter.create_connection()
        try:
            cursor = connection.cursor()
            # Try querying the built-in TPC-H catalog
            try:
                cursor.execute("SELECT COUNT(*) FROM tpch.tiny.lineitem")
                result = cursor.fetchone()
                assert result[0] > 0
            except TrinoUserError:
                # Fall back if tpch catalog is not available
                cursor.execute("SELECT COUNT(*) AS cnt, SUM(x) AS total FROM (VALUES 1, 2, 3) AS t(x)")
                result = cursor.fetchone()
                assert result[0] == 3
                assert result[1] == 6
        finally:
            live_starburst_adapter.close_connection(connection)

    def test_aggregation_query(self, live_starburst_adapter):
        """Execute an aggregation query to verify analytical capabilities."""
        connection = live_starburst_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT COUNT(*) AS cnt, SUM(x) AS total FROM (VALUES 1, 2, 3) AS t(x)")
            result = cursor.fetchone()
            assert result[0] == 3
            assert result[1] == 6
        finally:
            live_starburst_adapter.close_connection(connection)

    def test_tpch_builtin_query(self, live_starburst_adapter):
        """Query the built-in tpch catalog with a GROUP BY aggregation."""
        connection = live_starburst_adapter.create_connection()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT returnflag, COUNT(*) AS cnt FROM tpch.tiny.lineitem GROUP BY returnflag ORDER BY returnflag"
                )
                results = cursor.fetchall()
                assert len(results) > 0, "Expected rows from tpch.tiny.lineitem GROUP BY"
            except TrinoUserError:
                pytest.skip("tpch catalog not available in this Starburst cluster")
        finally:
            live_starburst_adapter.close_connection(connection)


class TestLiveStarburstSchemaManagement:
    """Test schema creation in a writable catalog on Starburst Galaxy."""

    def test_schema_creation(self, live_starburst_adapter, starburst_writable_catalog, unique_test_schema):
        """Create a schema in the writable catalog and verify it exists."""
        connection = live_starburst_adapter.create_connection()
        schema_ref = f"{starburst_writable_catalog}.{unique_test_schema}"
        try:
            cursor = connection.cursor()
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_ref}")
            cursor.execute(f"SHOW SCHEMAS FROM {starburst_writable_catalog}")
            schemas = [row[0] for row in cursor.fetchall()]
            assert unique_test_schema in schemas, (
                f"Schema {unique_test_schema} not found in {starburst_writable_catalog}"
            )
        finally:
            try:
                cursor = connection.cursor()
                cursor.execute(f"DROP SCHEMA IF EXISTS {schema_ref}")
            except Exception:
                pass
            live_starburst_adapter.close_connection(connection)


class TestLiveStarburstDataLoading:
    """Test TPC-H data loading into a writable Starburst catalog."""

    def test_tpch_data_load(
        self,
        live_starburst_adapter,
        starburst_writable_catalog,
        unique_test_schema,
        test_scale_factor,
        test_output_dir,
    ):
        """Load TPC-H data into Starburst via the writable catalog and verify row counts."""
        tpch = TPCH(scale_factor=test_scale_factor, output_dir=test_output_dir, verbose=False)
        data_files = tpch.generate_data()
        assert len(data_files) > 0, "No data files generated"

        schema_ref = f"{starburst_writable_catalog}.{unique_test_schema}"
        connection = live_starburst_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_ref}")
            # USE sets the session's current catalog.schema on this connection.
            # trino-python-client propagates session context to subsequent cursors
            # opened from the same connection, so create_schema/load_data below
            # will execute DDL/DML in {schema_ref} without explicit qualification.
            cursor.execute(f"USE {schema_ref}")
            live_starburst_adapter.create_schema(tpch, connection)
            stats, _errors, _ = live_starburst_adapter.load_data(tpch, connection, test_output_dir)
            assert len(stats) > 0, "No tables loaded"
            assert all(count > 0 for count in stats.values()), "Some tables have zero rows"
        finally:
            try:
                cursor = connection.cursor()
                cursor.execute(f"DROP SCHEMA IF EXISTS {schema_ref} CASCADE")
            except Exception:
                pass
            live_starburst_adapter.close_connection(connection)


class TestLiveStarburstSpecificFeatures:
    """Test Starburst Galaxy-specific features."""

    def test_show_catalogs(self, live_starburst_adapter):
        """Verify we can list catalogs."""
        connection = live_starburst_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SHOW CATALOGS")
            catalogs = [row[0] for row in cursor.fetchall()]
            assert len(catalogs) > 0
        finally:
            live_starburst_adapter.close_connection(connection)

    def test_information_schema(self, live_starburst_adapter):
        """Verify information_schema is accessible on the default catalog."""
        connection = live_starburst_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT table_schema, table_name FROM tpch.information_schema.tables LIMIT 5")
            results = cursor.fetchall()
            assert len(results) > 0, "Expected rows from tpch.information_schema.tables"
        finally:
            live_starburst_adapter.close_connection(connection)
