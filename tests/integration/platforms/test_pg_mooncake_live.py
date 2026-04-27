# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""
Docker live integration tests for pg_mooncake (PostgreSQL with mooncake extension).

Setup:
    make test-docker-up-pg-extensions
    # or: docker compose -f docker/postgres-extensions/docker-compose.yml up -d --wait

For S3/GCS object storage tests, also set:
    - MOONCAKE_S3_BUCKET (e.g., s3://my-bucket/mooncake)
    - AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY

These tests require a running PostgreSQL instance with pg_mooncake extension.
Set PG_MOONCAKE_HOST, PG_MOONCAKE_PORT, PG_MOONCAKE_USER, PG_MOONCAKE_PASSWORD,
PG_MOONCAKE_DATABASE to target a different instance.
"""

import os

import pytest

from .conftest import get_env_or_skip, skip_unless_docker_service

try:
    from psycopg import sql as psycopg_sql
except ImportError:
    psycopg_sql = None  # type: ignore[assignment]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_integration,
    pytest.mark.live_integration,
    pytest.mark.live_pg_mooncake,
]


class TestLivePgMooncakeConnection:
    """Test basic pg_mooncake connectivity via Docker."""

    def test_connection(self, live_pg_mooncake_adapter):
        """Verify we can connect to PostgreSQL with pg_mooncake and run a trivial query."""
        connection = live_pg_mooncake_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1
        finally:
            live_pg_mooncake_adapter.close_connection(connection)

    def test_extension_loaded(self, live_pg_mooncake_adapter):
        """Verify pg_mooncake extension is installed and loaded."""
        connection = live_pg_mooncake_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'pg_mooncake'")
            result = cursor.fetchone()
            assert result is not None, "pg_mooncake extension not installed"
            assert result[0], "pg_mooncake version should be non-empty"
        finally:
            live_pg_mooncake_adapter.close_connection(connection)

    def test_platform_info(self, live_pg_mooncake_adapter):
        """Verify platform info reports correct metadata."""
        info = live_pg_mooncake_adapter.get_platform_info()
        assert info is not None


class TestLivePgMooncakeQueryExecution:
    """Test query execution against a live pg_mooncake instance."""

    def test_columnstore_table(self, live_pg_mooncake_adapter):
        """Create a columnstore table and verify it works."""
        connection = live_pg_mooncake_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("DROP TABLE IF EXISTS benchbox_smoke_test")
            cursor.execute(
                "CREATE TABLE benchbox_smoke_test (id INT, name TEXT, value DOUBLE PRECISION) USING columnstore"
            )
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
            live_pg_mooncake_adapter.close_connection(connection)

    def test_aggregation_query(self, live_pg_mooncake_adapter):
        """Execute an aggregation query to verify analytical capabilities."""
        connection = live_pg_mooncake_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT COUNT(*) AS cnt, SUM(x) AS total FROM generate_series(1, 100) AS t(x)")
            result = cursor.fetchone()
            assert result[0] == 100
            assert result[1] == 5050
        finally:
            live_pg_mooncake_adapter.close_connection(connection)


class TestLivePgMooncakeObjectStorage:
    """Test S3/GCS object storage integration (requires cloud credentials + Docker)."""

    @pytest.fixture
    def s3_mooncake_bucket(self):
        """Get S3 bucket for mooncake or skip."""
        bucket = os.getenv("MOONCAKE_S3_BUCKET")
        if not bucket:
            pytest.skip("Requires MOONCAKE_S3_BUCKET for object storage tests")
        get_env_or_skip("AWS_ACCESS_KEY_ID", "S3")
        get_env_or_skip("AWS_SECRET_ACCESS_KEY", "S3")
        return bucket

    def test_s3_storage_mode(self, live_pg_mooncake_adapter, s3_mooncake_bucket):
        """Verify pg_mooncake can use S3 as storage backend."""
        connection = live_pg_mooncake_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                psycopg_sql.SQL("SET mooncake.default_bucket = {}").format(psycopg_sql.Literal(s3_mooncake_bucket))
            )
            cursor.execute("DROP TABLE IF EXISTS benchbox_s3_smoke_test")
            cursor.execute("CREATE TABLE benchbox_s3_smoke_test (id INT, value DOUBLE PRECISION) USING columnstore")
            cursor.execute("INSERT INTO benchbox_s3_smoke_test VALUES (1, 42.0)")
            cursor.execute("SELECT COUNT(*) FROM benchbox_s3_smoke_test")
            result = cursor.fetchone()
            assert result[0] == 1
        finally:
            try:
                cursor = connection.cursor()
                cursor.execute("DROP TABLE IF EXISTS benchbox_s3_smoke_test")
            except Exception:
                pass
            live_pg_mooncake_adapter.close_connection(connection)


class TestLivePgMooncakeWALReplication:
    """Test WAL replication benchmarking capabilities (requires Docker with WAL config)."""

    def test_wal_level(self, live_pg_mooncake_adapter):
        """Verify WAL level is set appropriately for replication testing."""
        connection = live_pg_mooncake_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SHOW wal_level")
            result = cursor.fetchone()
            # WAL level should be 'replica' or 'logical' for replication
            assert result[0] in ("replica", "logical"), (
                f"WAL level is '{result[0]}', expected 'replica' or 'logical' for replication testing"
            )
        finally:
            live_pg_mooncake_adapter.close_connection(connection)

    def test_write_and_verify_wal(self, live_pg_mooncake_adapter):
        """Write data and verify WAL position advances (basic replication readiness check)."""
        connection = live_pg_mooncake_adapter.create_connection()
        try:
            cursor = connection.cursor()
            # pg_current_wal_lsn() requires superuser or pg_read_all_stats role
            try:
                cursor.execute("SELECT pg_current_wal_lsn()")
                before_lsn = cursor.fetchone()[0]
            except Exception as exc:
                pytest.skip(f"pg_current_wal_lsn() not accessible (requires superuser): {exc}")

            # Write some data
            cursor.execute("DROP TABLE IF EXISTS benchbox_wal_test")
            cursor.execute("CREATE TABLE benchbox_wal_test (id INT, data TEXT)")
            cursor.execute("INSERT INTO benchbox_wal_test SELECT g, repeat('x', 100) FROM generate_series(1, 100) g")

            # Verify WAL position advanced
            cursor.execute("SELECT pg_current_wal_lsn()")
            after_lsn = cursor.fetchone()[0]
            assert before_lsn != after_lsn, "WAL position should advance after writes"
        finally:
            try:
                cursor = connection.cursor()
                cursor.execute("DROP TABLE IF EXISTS benchbox_wal_test")
            except Exception:
                pass
            live_pg_mooncake_adapter.close_connection(connection)
