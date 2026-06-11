# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""
Docker live integration tests for PostgreSQL.

Setup:
    make test-docker-up-postgresql

These tests require a running PostgreSQL instance accessible at localhost:5432.
"""

import json

import pytest

from benchbox.platforms.postgresql import PostgreSQLAdapter

from .conftest import skip_unless_docker_service

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_integration,
    pytest.mark.live_integration,
    pytest.mark.live_postgresql,
]


@pytest.fixture
def postgresql_adapter():
    """Create a PostgreSQL adapter connected to a local Docker instance."""
    skip_unless_docker_service("localhost", 5432, platform="PostgreSQL")
    adapter = PostgreSQLAdapter(
        host="localhost",
        port=5432,
        username="benchbox",
        password="benchbox",
        database="benchbox_test",
    )
    adapter.skip_database_management = True
    yield adapter


@pytest.fixture
def postgresql_adapter_with_capture():
    """Create a PostgreSQL adapter with query plan capture enabled."""
    skip_unless_docker_service("localhost", 5432, platform="PostgreSQL")
    adapter = PostgreSQLAdapter(
        host="localhost",
        port=5432,
        username="benchbox",
        password="benchbox",
        database="benchbox_test",
        capture_plans=True,
    )
    adapter.skip_database_management = True
    yield adapter


class TestLivePostgreSQLConnection:
    """Test basic PostgreSQL connectivity via Docker."""

    def test_connection(self, postgresql_adapter):
        """Verify we can connect to PostgreSQL and run a trivial query."""
        connection = postgresql_adapter.create_connection()
        try:
            assert connection is not None
        finally:
            postgresql_adapter.close_connection(connection)

    def test_platform_info(self, postgresql_adapter):
        """Verify platform info reports correct metadata."""
        info = postgresql_adapter.get_platform_info()
        assert info is not None
        assert info["platform_type"] == "postgresql"


class TestLivePostgreSQLQueryExecution:
    """Test query execution against a live PostgreSQL instance."""

    def test_create_schema(self, postgresql_adapter):
        """Verify we can create a schema."""
        connection = postgresql_adapter.create_connection()
        try:
            postgresql_adapter.execute_query(
                connection,
                "CREATE SCHEMA IF NOT EXISTS benchbox_test_schema",
                query_id="Q0",
                benchmark_type="tpch",
            )
            result = postgresql_adapter.execute_query(
                connection,
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'benchbox_test_schema'",
                query_id="Q0",
                benchmark_type="tpch",
            )
            assert result is not None
        finally:
            postgresql_adapter.close_connection(connection)

    def test_execute_query(self, postgresql_adapter):
        """Verify basic query execution with SELECT 1."""
        connection = postgresql_adapter.create_connection()
        try:
            result = postgresql_adapter.execute_query(
                connection,
                "SELECT 1",
                query_id="Q0",
                benchmark_type="tpch",
            )
            assert result is not None
        finally:
            postgresql_adapter.close_connection(connection)


class TestLivePostgreSQLQueryPlanCapture:
    """Test query plan capture against a live PostgreSQL instance."""

    def test_get_query_plan_returns_json(self, postgresql_adapter):
        """get_query_plan should return a non-empty JSON string."""
        connection = postgresql_adapter.create_connection()
        try:
            plan = postgresql_adapter.get_query_plan(connection, "SELECT 1")
            assert plan is not None
            assert len(plan) > 0
            # PostgreSQL FORMAT JSON wraps the plan in a list
            parsed = json.loads(plan)
            assert isinstance(parsed, list)
            assert len(parsed) > 0
        finally:
            postgresql_adapter.close_connection(connection)

    def test_capture_query_plan_returns_dag(self, postgresql_adapter_with_capture):
        """capture_query_plan should return a QueryPlanDAG for a simple SELECT."""
        adapter = postgresql_adapter_with_capture
        connection = adapter.create_connection()
        try:
            plan, capture_ms = adapter.capture_query_plan(connection, "SELECT 1", "q_test")
            assert plan is not None, "Expected a QueryPlanDAG but got None"
            assert capture_ms >= 0.0
            assert plan.logical_root is not None
        finally:
            adapter.close_connection(connection)

    def test_capture_query_plan_has_fingerprint(self, postgresql_adapter_with_capture):
        """Captured plan must have a non-empty fingerprint."""
        adapter = postgresql_adapter_with_capture
        connection = adapter.create_connection()
        try:
            plan, _ = adapter.capture_query_plan(connection, "SELECT 1", "q_fp")
            assert plan is not None
            assert plan.plan_fingerprint
            assert len(plan.plan_fingerprint) == 64  # SHA256 hex
        finally:
            adapter.close_connection(connection)

    def test_capture_query_plan_fingerprint_stable(self, postgresql_adapter_with_capture):
        """Same query executed twice must produce identical fingerprints."""
        adapter = postgresql_adapter_with_capture
        connection = adapter.create_connection()
        try:
            plan1, _ = adapter.capture_query_plan(connection, "SELECT 1", "q_fp_a")
            plan2, _ = adapter.capture_query_plan(connection, "SELECT 1", "q_fp_b")
            assert plan1 is not None
            assert plan2 is not None
            assert plan1.plan_fingerprint == plan2.plan_fingerprint
        finally:
            adapter.close_connection(connection)
