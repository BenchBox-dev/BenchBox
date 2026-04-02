# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""
Docker live integration tests for Trino.

Setup:
    make test-docker-up-trino

These tests require a running Trino instance accessible at localhost:18080 by default.
Set TRINO_HOST_PORT to target a different host port.
"""

import os

import pytest

from benchbox.platforms.trino import TrinoAdapter

from .conftest import skip_unless_docker_service

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_integration,
    pytest.mark.live_integration,
    pytest.mark.live_trino,
]


@pytest.fixture
def trino_adapter():
    """Create a Trino adapter connected to a local Docker instance."""
    port = int(os.getenv("TRINO_HOST_PORT", "18080"))
    skip_unless_docker_service("localhost", port, platform="Trino")
    adapter = TrinoAdapter(
        host="localhost",
        port=port,
        user="benchbox",
        catalog="memory",
        schema="default",
    )
    adapter.skip_database_management = True
    yield adapter


class TestLiveTrinoConnection:
    """Test basic Trino connectivity via Docker."""

    def test_connection(self, trino_adapter):
        """Verify we can connect to Trino and run a trivial query."""
        connection = trino_adapter.create_connection()
        try:
            assert hasattr(connection, "cursor")
        finally:
            trino_adapter.close_connection(connection)

    def test_platform_info(self, trino_adapter):
        """Verify platform info reports correct metadata."""
        info = trino_adapter.get_platform_info()
        assert info is not None
        assert info["platform_type"] == "trino"


class TestLiveTrinoQueryExecution:
    """Test query execution against a live Trino instance."""

    def test_create_schema(self, trino_adapter):
        """Verify we can create a schema in the memory catalog."""
        connection = trino_adapter.create_connection()
        try:
            trino_adapter.execute_query(
                connection,
                "CREATE SCHEMA IF NOT EXISTS memory.benchbox_test",
                query_id="Q0",
                benchmark_type="tpch",
            )
            result = trino_adapter.execute_query(
                connection,
                "SHOW SCHEMAS FROM memory LIKE 'benchbox_test'",
                query_id="Q0",
                benchmark_type="tpch",
            )
            assert isinstance(result, dict)
        finally:
            trino_adapter.close_connection(connection)

    def test_execute_query(self, trino_adapter):
        """Verify basic query execution with SELECT 1."""
        connection = trino_adapter.create_connection()
        try:
            result = trino_adapter.execute_query(
                connection,
                "SELECT 1",
                query_id="Q0",
                benchmark_type="tpch",
            )
            assert isinstance(result, dict)
        finally:
            trino_adapter.close_connection(connection)
