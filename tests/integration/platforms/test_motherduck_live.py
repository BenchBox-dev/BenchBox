# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""
Live integration tests for MotherDuck.

Setup:
1. Create a MotherDuck account (free tier: 10 GB)
2. Set environment variable:
   - MOTHERDUCK_TOKEN
   - MOTHERDUCK_DATABASE (optional, defaults to 'benchbox_test')
3. Run: make test-live-motherduck

These tests use scale_factor=0.01 for minimal storage usage.
"""

import os
import re

import pytest

from benchbox import TPCH

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_integration,
    pytest.mark.live_motherduck,
    pytest.mark.skipif(
        not os.getenv("MOTHERDUCK_TOKEN"),
        reason="Requires MOTHERDUCK_TOKEN environment variable. See docstring for setup.",
    ),
]


@pytest.fixture(scope="module")
def tpch_data(live_motherduck_adapter, test_scale_factor, test_output_dir):
    """Load TPC-H data into a dedicated MotherDuck schema once per module; drop on teardown.

    Uses a process-unique schema name to avoid conflicts with TestLiveMotherDuckSchemaManagement
    which independently creates and drops unique_test_schema.
    """
    schema = f"benchbox_data_{os.getpid()}"
    tpch = TPCH(scale_factor=test_scale_factor, output_dir=test_output_dir, verbose=False)
    data_files = tpch.generate_data()
    assert len(data_files) > 0, "No data files generated"

    connection = live_motherduck_adapter.create_connection()
    try:
        connection.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        connection.execute(f"SET search_path = '{schema}'")
        live_motherduck_adapter.create_schema(tpch, connection)
        stats, _errors, _ = live_motherduck_adapter.load_data(tpch, connection, test_output_dir)
        yield tpch, stats, schema
    finally:
        try:
            connection.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        except Exception:
            pass
        live_motherduck_adapter.close_connection(connection)


class TestLiveMotherDuckConnection:
    """Test basic MotherDuck connectivity."""

    def test_connection(self, live_motherduck_adapter):
        """Verify we can connect to MotherDuck and run a trivial query."""
        connection = live_motherduck_adapter.create_connection()
        try:
            result = connection.execute("SELECT 1").fetchone()
            assert result[0] == 1
        finally:
            live_motherduck_adapter.close_connection(connection)

    def test_platform_info(self, live_motherduck_adapter):
        """Verify platform info reports correct metadata."""
        info = live_motherduck_adapter.get_platform_info()
        assert info is not None
        assert info.get("platform_type") == "motherduck"
        assert info.get("platform_name")
        assert "configuration" in info


class TestLiveMotherDuckQueryExecution:
    """Test query execution against live MotherDuck."""

    def test_create_and_query_table(self, live_motherduck_adapter):
        """Create a test table, insert data, and query it."""
        connection = live_motherduck_adapter.create_connection()
        try:
            connection.execute("DROP TABLE IF EXISTS benchbox_smoke_test")
            connection.execute(
                "CREATE TABLE benchbox_smoke_test AS "
                "SELECT * FROM (VALUES "
                "  (1, 'alpha', 10.5), "
                "  (2, 'beta', 20.3), "
                "  (3, 'gamma', 30.1)"
                ") AS t(id, name, value)"
            )
            result = connection.execute("SELECT COUNT(*) FROM benchbox_smoke_test").fetchone()
            assert result[0] == 3
        finally:
            try:
                connection.execute("DROP TABLE IF EXISTS benchbox_smoke_test")
            except Exception:
                pass
            live_motherduck_adapter.close_connection(connection)

    def test_aggregation_query(self, live_motherduck_adapter):
        """Execute an aggregation query to verify analytical capabilities."""
        connection = live_motherduck_adapter.create_connection()
        try:
            result = connection.execute(
                "SELECT COUNT(*) AS cnt, SUM(x) AS total FROM (VALUES (1), (2), (3)) AS t(x)"
            ).fetchone()
            assert result[0] == 3
            assert result[1] == 6
        finally:
            live_motherduck_adapter.close_connection(connection)

    def test_tpch_query_1(self, live_motherduck_adapter, tpch_data):
        """Execute TPC-H Query 1 against the module-loaded dataset."""
        tpch, _stats, schema = tpch_data
        connection = live_motherduck_adapter.create_connection()
        try:
            query1 = tpch.get_query(1, seed=42)
            # Q1 references only lineitem, so qualifying that single table is sufficient.
            # Extend this substitution if the query set is broadened beyond Q1.
            query1_md = re.sub(r"\blineitem\b", f"{schema}.lineitem", query1)
            results = connection.execute(query1_md).fetchall()
            assert len(results) > 0, "TPC-H Query 1 returned no results"
        finally:
            live_motherduck_adapter.close_connection(connection)


class TestLiveMotherDuckSchemaManagement:
    """Test schema creation and management on MotherDuck."""

    def test_schema_creation(self, live_motherduck_adapter, unique_test_schema):
        """Create a schema and verify it appears in information_schema."""
        connection = live_motherduck_adapter.create_connection()
        try:
            connection.execute(f"CREATE SCHEMA IF NOT EXISTS {unique_test_schema}")
            result = connection.execute(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name = ?",
                [unique_test_schema],
            ).fetchone()
            assert result is not None, f"Schema {unique_test_schema} not found in information_schema"
        finally:
            try:
                connection.execute(f"DROP SCHEMA IF EXISTS {unique_test_schema} CASCADE")
            except Exception:
                pass
            live_motherduck_adapter.close_connection(connection)


class TestLiveMotherDuckDataLoading:
    """Test TPC-H data loading on MotherDuck."""

    def test_tpch_data_load(self, live_motherduck_adapter, tpch_data):
        """Verify TPC-H data was loaded with non-zero row counts in every table."""
        _tpch, stats, schema = tpch_data
        assert len(stats) > 0, "No tables loaded"
        assert all(count > 0 for count in stats.values()), "Some tables have zero rows"
        connection = live_motherduck_adapter.create_connection()
        try:
            row = connection.execute(f"SELECT COUNT(*) FROM {schema}.lineitem").fetchone()
            assert row[0] > 0, "lineitem table is empty"
        finally:
            live_motherduck_adapter.close_connection(connection)


class TestLiveMotherDuckSpecificFeatures:
    """Test MotherDuck-specific features."""

    def test_duckdb_extensions(self, live_motherduck_adapter):
        """Verify DuckDB extensions are accessible via MotherDuck."""
        connection = live_motherduck_adapter.create_connection()
        try:
            result = connection.execute(
                "SELECT extension_name FROM duckdb_extensions() WHERE loaded = true LIMIT 5"
            ).fetchall()
            assert len(result) > 0
        finally:
            live_motherduck_adapter.close_connection(connection)

    def test_cloud_databases(self, live_motherduck_adapter):
        """Verify MotherDuck cloud databases are visible."""
        connection = live_motherduck_adapter.create_connection()
        try:
            result = connection.execute("SHOW DATABASES").fetchall()
            assert len(result) > 0, "Expected at least one database in SHOW DATABASES"
        finally:
            live_motherduck_adapter.close_connection(connection)
