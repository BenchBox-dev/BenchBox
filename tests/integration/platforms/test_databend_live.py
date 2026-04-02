# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""
Docker live integration tests for Databend.

Setup:
    make test-docker-up-databend

These tests require a running Databend instance accessible at localhost:8000.
"""

import os

import pytest

from benchbox.platforms.databend import DatabendAdapter

from .conftest import skip_unless_docker_service

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_integration,
    pytest.mark.live_integration,
    pytest.mark.live_databend,
]


@pytest.fixture
def databend_adapter():
    """Create a Databend adapter connected to a local Docker instance."""
    port = int(os.getenv("DATABEND_PORT", "8000"))
    skip_unless_docker_service("localhost", port, platform="Databend")
    adapter = DatabendAdapter(
        host="localhost",
        port=port,
        username="benchbox",
        password="benchbox",
        database="default",
        ssl=False,
    )
    adapter.skip_database_management = True
    yield adapter


class TestLiveDatabendConnection:
    """Test basic Databend connectivity via Docker."""

    def test_connection(self, databend_adapter):
        """Verify we can connect to Databend and run a trivial query."""
        connection = databend_adapter.create_connection()
        try:
            assert connection is not None
        finally:
            databend_adapter.close_connection(connection)

    def test_platform_info(self, databend_adapter):
        """Verify platform info reports correct metadata."""
        info = databend_adapter.get_platform_info()
        assert info is not None
        assert info["platform_type"] == "databend"


class TestLiveDatabendQueryExecution:
    """Test query execution against a live Databend instance."""

    def test_create_schema(self, databend_adapter):
        """Verify we can create a database."""
        connection = databend_adapter.create_connection()
        try:
            databend_adapter.execute_query(
                connection,
                "CREATE DATABASE IF NOT EXISTS benchbox_test",
                query_id="Q0",
                benchmark_type="tpch",
            )
            result = databend_adapter.execute_query(
                connection,
                "SHOW DATABASES LIKE 'benchbox_test'",
                query_id="Q0",
                benchmark_type="tpch",
            )
            assert result is not None
        finally:
            databend_adapter.close_connection(connection)

    def test_execute_query(self, databend_adapter):
        """Verify basic query execution with SELECT 1."""
        connection = databend_adapter.create_connection()
        try:
            result = databend_adapter.execute_query(
                connection,
                "SELECT 1",
                query_id="Q0",
                benchmark_type="tpch",
            )
            assert result is not None
        finally:
            databend_adapter.close_connection(connection)
