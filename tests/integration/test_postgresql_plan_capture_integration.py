# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""Live PostgreSQL integration tests for query plan capture.

Unlike the mocked unit tests in tests/unit/platforms/test_postgresql_plan_capture.py,
these exercise real ``EXPLAIN (FORMAT JSON)`` against a live PostgreSQL instance,
the real PostgreSQLQueryPlanParser, and the real plan fingerprint.

CI-gating: the whole module is skipped unless ``POSTGRESQL_HOST`` is set, so it
is a graceful no-op locally and in default test runs. A CI job (or
``make test-docker-up-postgresql`` followed by exporting ``POSTGRESQL_HOST``)
that provisions a PostgreSQL service can run it by setting the connection
environment variables below. ``POSTGRESQL_HOST`` is intentionally the single
gate; the other variables fall back to the BenchBox Docker defaults.
"""

import os

import pytest

from benchbox.platforms.postgresql import PostgreSQLAdapter

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("POSTGRESQL_HOST"),
        reason="live PostgreSQL not available (POSTGRESQL_HOST unset)",
    ),
]


@pytest.fixture
def postgresql_adapter():
    adapter = PostgreSQLAdapter(
        host=os.environ["POSTGRESQL_HOST"],
        port=int(os.environ.get("POSTGRESQL_PORT", "5432")),
        username=os.environ.get("POSTGRESQL_USER", "benchbox"),
        password=os.environ.get("POSTGRESQL_PASSWORD", "benchbox"),
        database=os.environ.get("POSTGRESQL_DATABASE", "benchbox_test"),
        capture_plans=True,
    )
    adapter.skip_database_management = True
    yield adapter


@pytest.fixture
def connection(postgresql_adapter):
    conn = postgresql_adapter.create_connection()
    try:
        yield conn
    finally:
        postgresql_adapter.close_connection(conn)


class TestLivePostgreSQLPlanCapture:
    def test_get_query_plan_returns_json(self, postgresql_adapter, connection):
        raw = postgresql_adapter.get_query_plan(connection, "SELECT 1")
        assert raw is not None, "EXPLAIN (FORMAT JSON) should return plan text"
        stripped = raw.strip()
        assert stripped.startswith("[") or stripped.startswith("{"), "Expected FORMAT JSON output"

    def test_parser_produces_dag_with_fingerprint(self, postgresql_adapter, connection):
        raw = postgresql_adapter.get_query_plan(connection, "SELECT 1")
        parser = postgresql_adapter.get_query_plan_parser()
        dag = parser.parse_explain_output("pg_live_dag", raw)
        assert dag is not None
        assert dag.logical_root is not None
        assert dag.plan_fingerprint is not None

    def test_fingerprint_is_idempotent_across_calls(self, postgresql_adapter, connection):
        query = "SELECT 1"
        plan1, _ = postgresql_adapter.capture_query_plan(connection, query, "pg_a")
        plan2, _ = postgresql_adapter.capture_query_plan(connection, query, "pg_b")
        assert plan1 is not None and plan2 is not None
        assert plan1.plan_fingerprint == plan2.plan_fingerprint
