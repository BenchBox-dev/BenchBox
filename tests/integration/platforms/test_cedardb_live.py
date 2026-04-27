# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""
Docker live integration tests for CedarDB.

Setup:
    make test-docker-up-cedardb
    # or: docker compose -f docker/cedardb/docker-compose.yml up -d --wait

These tests require a running CedarDB instance accessible via PostgreSQL wire protocol.
Set CEDARDB_HOST, CEDARDB_PORT, CEDARDB_USER, CEDARDB_PASSWORD, CEDARDB_DATABASE
to target a different instance.
"""

import pytest

from .conftest import skip_unless_docker_service

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_integration,
    pytest.mark.live_integration,
    pytest.mark.live_cedardb,
]


class TestLiveCedarDBConnection:
    """Test basic CedarDB connectivity via Docker."""

    def test_connection(self, live_cedardb_adapter):
        """Verify we can connect to CedarDB and run a trivial query."""
        connection = live_cedardb_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1
        finally:
            live_cedardb_adapter.close_connection(connection)

    def test_platform_info(self, live_cedardb_adapter):
        """Verify platform info reports CedarDB metadata."""
        connection = live_cedardb_adapter.create_connection()
        try:
            info = live_cedardb_adapter.get_platform_info(connection=connection)
            assert info["platform_type"] == "cedardb"
            assert info["platform_name"] == "CedarDB"
        finally:
            live_cedardb_adapter.close_connection(connection)

    def test_version_string(self, live_cedardb_adapter):
        """Verify CedarDB returns a version string via SELECT version()."""
        connection = live_cedardb_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT version()")
            result = cursor.fetchone()
            assert result is not None
            assert isinstance(result[0], str)
            assert len(result[0]) > 0
        finally:
            live_cedardb_adapter.close_connection(connection)


class TestLiveCedarDBQueryExecution:
    """Test query execution against a live CedarDB instance."""

    def test_execute_select(self, live_cedardb_adapter):
        """Verify basic SELECT execution via adapter."""
        connection = live_cedardb_adapter.create_connection()
        try:
            result = live_cedardb_adapter.execute_query(
                connection,
                "SELECT 1 AS n",
                query_id="Q0",
                benchmark_type="tpch",
            )
            assert result is not None
        finally:
            live_cedardb_adapter.close_connection(connection)

    def test_aggregation_query(self, live_cedardb_adapter):
        """Execute an aggregation to verify analytical capabilities."""
        connection = live_cedardb_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT COUNT(*) AS cnt, SUM(x) AS total FROM generate_series(1, 100) AS t(x)")
            result = cursor.fetchone()
            assert result[0] == 100
            assert result[1] == 5050
        finally:
            live_cedardb_adapter.close_connection(connection)

    def test_create_and_query_table(self, live_cedardb_adapter):
        """Create a table, insert rows, query, and clean up."""
        connection = live_cedardb_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("DROP TABLE IF EXISTS benchbox_smoke_test")
            cursor.execute("CREATE TABLE benchbox_smoke_test (id INTEGER, label TEXT, value DOUBLE PRECISION)")
            cursor.execute(
                "INSERT INTO benchbox_smoke_test VALUES (1, 'alpha', 10.5), (2, 'beta', 20.3), (3, 'gamma', 30.1)"
            )
            cursor.execute("SELECT COUNT(*) FROM benchbox_smoke_test")
            result = cursor.fetchone()
            assert result[0] == 3

            cursor.execute("SELECT SUM(value) FROM benchbox_smoke_test")
            total = cursor.fetchone()[0]
            assert abs(total - 60.9) < 0.001
        finally:
            try:
                cursor = connection.cursor()
                cursor.execute("DROP TABLE IF EXISTS benchbox_smoke_test")
            except Exception:
                pass
            live_cedardb_adapter.close_connection(connection)

    def test_postgresql_dialect_compatibility(self, live_cedardb_adapter):
        """Verify PostgreSQL dialect features work (CTE, window functions)."""
        connection = live_cedardb_adapter.create_connection()
        try:
            cursor = connection.cursor()
            # CTE + window function - standard PostgreSQL syntax
            cursor.execute(
                """
                WITH nums AS (
                    SELECT g AS n FROM generate_series(1, 5) AS t(g)
                )
                SELECT n, SUM(n) OVER (ORDER BY n) AS running_total
                FROM nums
                ORDER BY n
                """
            )
            rows = cursor.fetchall()
            assert len(rows) == 5
            assert rows[-1][1] == 15  # 1+2+3+4+5
        finally:
            live_cedardb_adapter.close_connection(connection)


class TestLiveCedarDBConstraints:
    """Test primary key and foreign key support (CedarDB-supported tuning types)."""

    def test_primary_key_constraint(self, live_cedardb_adapter):
        """Verify primary key constraints are enforced."""
        connection = live_cedardb_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("DROP TABLE IF EXISTS benchbox_pk_test")
            cursor.execute("CREATE TABLE benchbox_pk_test (id INTEGER PRIMARY KEY, name TEXT)")
            cursor.execute("INSERT INTO benchbox_pk_test VALUES (1, 'first')")

            # Inserting a duplicate PK should fail
            with pytest.raises(Exception):
                cursor.execute("INSERT INTO benchbox_pk_test VALUES (1, 'duplicate')")
                connection.commit()
        finally:
            try:
                connection.rollback()
                cursor = connection.cursor()
                cursor.execute("DROP TABLE IF EXISTS benchbox_pk_test")
            except Exception:
                pass
            live_cedardb_adapter.close_connection(connection)
