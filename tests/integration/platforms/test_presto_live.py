# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""
Docker live integration tests for Presto.

Setup:
    make test-docker-up-presto

These tests require a running Presto instance accessible at localhost:18081 by default.
Set PRESTO_HOST_PORT to target a different host port.
"""

import os

import pytest

from benchbox.platforms.presto import PrestoAdapter

from .conftest import skip_unless_docker_service

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_integration,
    pytest.mark.live_integration,
    pytest.mark.live_presto,
]


@pytest.fixture
def presto_adapter():
    """Create a Presto adapter connected to a local Docker instance."""
    port = int(os.getenv("PRESTO_HOST_PORT", "18081"))
    skip_unless_docker_service("localhost", port, platform="Presto")
    adapter = PrestoAdapter(
        host="localhost",
        port=port,
        user="benchbox",
        catalog="memory",
        schema="default",
    )
    adapter.skip_database_management = True
    yield adapter


class TestLivePrestoConnection:
    """Test basic Presto connectivity via Docker."""

    def test_connection(self, presto_adapter):
        """Verify we can connect to Presto and run a trivial query."""
        connection = presto_adapter.create_connection()
        try:
            assert connection is not None
        finally:
            presto_adapter.close_connection(connection)

    def test_platform_info(self, presto_adapter):
        """Verify platform info reports correct metadata."""
        info = presto_adapter.get_platform_info()
        assert info is not None
        assert info["platform_type"] == "presto"


class TestLivePrestoQueryExecution:
    """Test query execution against a live Presto instance."""

    def test_create_schema(self, presto_adapter):
        """Verify we can create a schema in the memory catalog."""
        connection = presto_adapter.create_connection()
        try:
            presto_adapter.execute_query(
                connection,
                "CREATE SCHEMA IF NOT EXISTS memory.benchbox_test",
                query_id="Q0",
                benchmark_type="tpch",
            )
            result = presto_adapter.execute_query(
                connection,
                "SHOW SCHEMAS FROM memory LIKE 'benchbox_test'",
                query_id="Q0",
                benchmark_type="tpch",
            )
            assert result is not None
        finally:
            presto_adapter.close_connection(connection)

    def test_execute_query(self, presto_adapter):
        """Verify basic query execution with SELECT 1."""
        connection = presto_adapter.create_connection()
        try:
            result = presto_adapter.execute_query(
                connection,
                "SELECT 1",
                query_id="Q0",
                benchmark_type="tpch",
            )
            assert result is not None
        finally:
            presto_adapter.close_connection(connection)
