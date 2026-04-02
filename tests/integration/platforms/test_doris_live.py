# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""
Docker live integration tests for Apache Doris.

Setup:
    make test-docker-up-doris

These tests require a running Doris instance accessible at localhost:19031 by default.
Set DORIS_HOST_PORT and DORIS_HTTP_PORT to target different host ports.
"""

import os

import pymysql
import pytest

from benchbox.platforms.doris import DorisAdapter

from .conftest import skip_unless_docker_service

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_integration,
    pytest.mark.live_integration,
    pytest.mark.live_doris,
]


@pytest.fixture(scope="module", autouse=True)
def ensure_database():
    """Pre-create the test database (Doris adapter expects it to exist)."""
    port = int(os.getenv("DORIS_HOST_PORT", "19031"))
    try:
        conn = pymysql.connect(host="localhost", port=port, user="root", password="", autocommit=True)
        cursor = conn.cursor()
        cursor.execute("CREATE DATABASE IF NOT EXISTS benchbox_test")
        cursor.close()
        conn.close()
    except Exception:
        pytest.skip(f"Doris not reachable at localhost:{port}")


@pytest.fixture
def doris_adapter():
    """Create a Doris adapter connected to a local Docker instance."""
    port = int(os.getenv("DORIS_HOST_PORT", "19031"))
    http_port = int(os.getenv("DORIS_HTTP_PORT", "18030"))
    skip_unless_docker_service("localhost", port, platform="Doris")
    adapter = DorisAdapter(
        host="localhost",
        port=port,
        user="root",
        password="",
        database="benchbox_test",
        http_port=http_port,
    )
    adapter.skip_database_management = True
    yield adapter


class TestLiveDorisConnection:
    """Test basic Doris connectivity via Docker."""

    def test_connection(self, doris_adapter):
        """Verify we can connect to Doris and run a trivial query."""
        connection = doris_adapter.create_connection()
        try:
            assert hasattr(connection, "cursor")
        finally:
            doris_adapter.close_connection(connection)

    def test_platform_info(self, doris_adapter):
        """Verify platform info reports correct metadata."""
        info = doris_adapter.get_platform_info()
        assert info is not None
        assert info["platform_type"] == "doris"


class TestLiveDorisQueryExecution:
    """Test query execution against a live Doris instance."""

    def test_create_schema(self, doris_adapter):
        """Verify we can create a database."""
        connection = doris_adapter.create_connection()
        try:
            doris_adapter.execute_query(
                connection,
                "CREATE DATABASE IF NOT EXISTS benchbox_test",
                query_id="Q0",
                benchmark_type="tpch",
            )
            result = doris_adapter.execute_query(
                connection,
                "SHOW DATABASES LIKE 'benchbox_test'",
                query_id="Q0",
                benchmark_type="tpch",
            )
            assert isinstance(result, dict)
        finally:
            doris_adapter.close_connection(connection)

    def test_execute_query(self, doris_adapter):
        """Verify basic query execution with SELECT 1."""
        connection = doris_adapter.create_connection()
        try:
            result = doris_adapter.execute_query(
                connection,
                "SELECT 1",
                query_id="Q0",
                benchmark_type="tpch",
            )
            assert isinstance(result, dict)
        finally:
            doris_adapter.close_connection(connection)
