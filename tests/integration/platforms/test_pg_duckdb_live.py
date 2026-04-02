# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""
Docker live integration tests for pg_duckdb (PostgreSQL with DuckDB extension).

Setup (self-hosted mode):
    make test-docker-up-pg-extensions
    # or: docker compose -f docker/postgres-extensions/docker-compose.yml up -d --wait

Setup (MotherDuck mode — also requires MOTHERDUCK_TOKEN):
    export MOTHERDUCK_TOKEN=your_token
    make test-docker-up-pg-extensions

These tests require a running PostgreSQL instance with pg_duckdb extension.
Set PG_DUCKDB_HOST, PG_DUCKDB_PORT, PG_DUCKDB_USER, PG_DUCKDB_PASSWORD,
PG_DUCKDB_DATABASE to target a different instance.
"""

import os

import pytest

from .conftest import get_env_or_skip, skip_unless_docker_service

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_integration,
    pytest.mark.live_integration,
    pytest.mark.live_pg_duckdb,
]


class TestLivePgDuckDBConnection:
    """Test basic pg_duckdb connectivity via Docker."""

    def test_connection(self, live_pg_duckdb_adapter):
        """Verify we can connect to PostgreSQL with pg_duckdb and run a trivial query."""
        connection = live_pg_duckdb_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1
        finally:
            live_pg_duckdb_adapter.close_connection(connection)

    def test_extension_loaded(self, live_pg_duckdb_adapter):
        """Verify pg_duckdb extension is installed and loaded."""
        connection = live_pg_duckdb_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'pg_duckdb'")
            result = cursor.fetchone()
            assert result is not None, "pg_duckdb extension not installed"
            assert result[0], "pg_duckdb version should be non-empty"
        finally:
            live_pg_duckdb_adapter.close_connection(connection)

    def test_platform_info(self, live_pg_duckdb_adapter):
        """Verify platform info reports correct metadata."""
        info = live_pg_duckdb_adapter.get_platform_info()
        assert info is not None
        assert info.get("platform_type") == "pg_duckdb"
        assert info.get("platform_name")
        assert "configuration" in info


class TestLivePgDuckDBQueryExecution:
    """Test query execution against a live pg_duckdb instance."""

    def test_duckdb_execution(self, live_pg_duckdb_adapter):
        """Verify DuckDB execution path works via pg_duckdb."""
        connection = live_pg_duckdb_adapter.create_connection()
        try:
            cursor = connection.cursor()
            # Force DuckDB execution if configured
            cursor.execute("SELECT COUNT(*) AS cnt, SUM(x) AS total FROM generate_series(1, 100) AS t(x)")
            result = cursor.fetchone()
            assert result[0] == 100
            assert result[1] == 5050
        finally:
            live_pg_duckdb_adapter.close_connection(connection)

    def test_create_and_query_table(self, live_pg_duckdb_adapter):
        """Create a test table, insert data, and query it."""
        connection = live_pg_duckdb_adapter.create_connection()
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
            live_pg_duckdb_adapter.close_connection(connection)


class TestLivePgDuckDBMotherDuckMode:
    """Test MotherDuck hybrid mode (requires MOTHERDUCK_TOKEN + Docker)."""

    @pytest.fixture
    def motherduck_pg_duckdb_adapter(self):
        """Create pg_duckdb adapter in MotherDuck mode."""
        from benchbox.platforms.pg_duckdb import PgDuckDBAdapter

        token = os.getenv("MOTHERDUCK_TOKEN")
        if not token:
            pytest.skip("Requires MOTHERDUCK_TOKEN for MotherDuck mode")

        host = os.getenv("PG_DUCKDB_HOST", "localhost")
        port = int(os.getenv("PG_DUCKDB_PORT", "5432"))
        skip_unless_docker_service(host, port, platform="pg_duckdb")
        adapter = PgDuckDBAdapter(
            host=host,
            port=port,
            username=os.getenv("PG_DUCKDB_USER", "benchbox"),
            password=os.getenv("PG_DUCKDB_PASSWORD", "benchbox"),
            database=os.getenv("PG_DUCKDB_DATABASE", "benchbox_test"),
            deployment_mode="motherduck",
            motherduck_token=token,
        )
        yield adapter

    def test_motherduck_connection(self, motherduck_pg_duckdb_adapter):
        """Verify pg_duckdb can connect in MotherDuck hybrid mode."""
        connection = motherduck_pg_duckdb_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1
        finally:
            motherduck_pg_duckdb_adapter.close_connection(connection)


class TestLivePgDuckDBS3LakeQueries:
    """Test S3 Parquet/Iceberg data lake queries (requires AWS credentials + Docker)."""

    @pytest.fixture
    def s3_test_parquet(self):
        """Upload a small Parquet file to S3 and yield its location; delete on teardown."""
        import io

        bucket = os.getenv("BENCHBOX_S3_TEST_BUCKET")
        if not bucket:
            pytest.skip("Requires BENCHBOX_S3_TEST_BUCKET for S3 lake queries")

        access_key = get_env_or_skip("AWS_ACCESS_KEY_ID", "S3")
        secret_key = get_env_or_skip("AWS_SECRET_ACCESS_KEY", "S3")

        try:
            import boto3
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:
            pytest.skip(f"Requires boto3 and pyarrow: {exc}")

        key = "benchbox_test/test.parquet"
        row_count = 100

        # Generate 100-row Parquet in memory
        table = pa.table({"id": list(range(row_count)), "value": [float(i) * 1.5 for i in range(row_count)]})
        buf = io.BytesIO()
        pq.write_table(table, buf)
        buf.seek(0)

        # Upload to S3
        s3 = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        s3.put_object(Bucket=bucket, Key=key, Body=buf.read())

        yield {"bucket": bucket, "key": key, "row_count": row_count}

        # Teardown — delete the object
        try:
            s3.delete_object(Bucket=bucket, Key=key)
        except Exception:
            pass

    def test_s3_parquet_query(self, live_pg_duckdb_adapter, s3_test_parquet):
        """Verify pg_duckdb can query Parquet files on S3."""
        bucket = s3_test_parquet["bucket"]
        key = s3_test_parquet["key"]
        expected_rows = s3_test_parquet["row_count"]

        connection = live_pg_duckdb_adapter.create_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM read_parquet('s3://{bucket}/{key}')")
            result = cursor.fetchone()
            assert result[0] == expected_rows
        finally:
            live_pg_duckdb_adapter.close_connection(connection)
