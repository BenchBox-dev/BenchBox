# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""
Docker live integration tests for StarRocks.

Setup:
    make test-docker-up-starrocks
    # or: docker compose -f docker/starrocks/docker-compose.yml up -d --wait

These tests require a running StarRocks instance accessible at localhost:19030 by default.
Set STARROCKS_HOST_PORT and STARROCKS_HTTP_PORT to target different host ports.
"""

import os

import pymysql
import pytest

from benchbox.platforms.starrocks import StarRocksAdapter

from .conftest import skip_unless_docker_service

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_integration,
    pytest.mark.live_integration,
    pytest.mark.live_starrocks,
]


@pytest.fixture(scope="module", autouse=True)
def ensure_database():
    """Pre-create the test database (StarRocks adapter expects it to exist)."""
    port = int(os.getenv("STARROCKS_HOST_PORT", "19030"))
    try:
        conn = pymysql.connect(host="localhost", port=port, user="root", password="", autocommit=True)
        cursor = conn.cursor()
        cursor.execute("CREATE DATABASE IF NOT EXISTS benchbox_test")
        cursor.close()
        conn.close()
    except Exception:
        pytest.skip(f"StarRocks not reachable at localhost:{port}")


@pytest.fixture
def starrocks_adapter():
    """Create a StarRocks adapter connected to a local Docker instance."""
    port = int(os.getenv("STARROCKS_HOST_PORT", "19030"))
    http_port = int(os.getenv("STARROCKS_HTTP_PORT", "18040"))
    skip_unless_docker_service("localhost", port, platform="StarRocks")
    adapter = StarRocksAdapter(
        host="localhost",
        port=port,
        user="root",
        password="",
        database="benchbox_test",
        http_port=http_port,
    )
    adapter.skip_database_management = True
    yield adapter


class TestLiveStarRocksConnection:
    """Test basic StarRocks connectivity via Docker."""

    def test_connection(self, starrocks_adapter):
        """Verify we can connect to StarRocks and run a trivial query."""
        connection = starrocks_adapter.create_connection()
        try:
            assert connection is not None
        finally:
            starrocks_adapter.close_connection(connection)

    def test_platform_info(self, starrocks_adapter):
        """Verify platform info reports correct metadata."""
        info = starrocks_adapter.get_platform_info()
        assert info is not None
        assert info["platform_type"] == "starrocks"


class TestLiveStarRocksQueryExecution:
    """Test query execution against a live StarRocks instance."""

    def test_create_schema(self, starrocks_adapter):
        """Verify we can create a database."""
        connection = starrocks_adapter.create_connection()
        try:
            starrocks_adapter.execute_query(
                connection,
                "CREATE DATABASE IF NOT EXISTS benchbox_test_schema",
                query_id="Q0",
                benchmark_type="tpch",
            )
            result = starrocks_adapter.execute_query(
                connection,
                "SHOW DATABASES LIKE 'benchbox_test_schema'",
                query_id="Q0",
                benchmark_type="tpch",
            )
            assert result is not None
        finally:
            starrocks_adapter.close_connection(connection)

    def test_execute_query(self, starrocks_adapter):
        """Verify basic query execution with SELECT 1."""
        connection = starrocks_adapter.create_connection()
        try:
            result = starrocks_adapter.execute_query(
                connection,
                "SELECT 1",
                query_id="Q0",
                benchmark_type="tpch",
            )
            assert result is not None
        finally:
            starrocks_adapter.close_connection(connection)
