# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""Live plan-capture hooks for the synthetic-fixture parsers (Presto/Trino, ClickHouse, Spark).

Part of query-plan-capture-parser-live-validation (w2): each class runs a real
EXPLAIN over a live instance and asserts the parser yields a non-None
QueryPlanDAG with a stable fingerprint. Every class is gated on its own env
var and skips cleanly when the engine is absent, so this module is a no-op in
default CI. See tests/fixtures/query_plans/PROVENANCE.md for validation status.
"""

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
]


def _assert_live_plan(adapter, connection, query="SELECT 1"):
    raw = adapter.get_query_plan(connection, query)
    assert raw is not None and raw.strip(), "get_query_plan returned empty plan text"
    plan, _ = adapter.capture_query_plan(connection, query, "live-validation")
    assert plan is not None, "capture_query_plan returned None for live output"
    assert plan.logical_root is not None
    assert plan.plan_fingerprint is not None and len(plan.plan_fingerprint) == 64
    plan2, _ = adapter.capture_query_plan(connection, query, "live-validation")
    assert plan2 is not None
    assert plan2.plan_fingerprint == plan.plan_fingerprint
    return raw


@pytest.mark.skipif(not os.environ.get("PRESTO_HOST"), reason="live Presto not available (PRESTO_HOST unset)")
class TestLivePrestoQueryPlanCapture:
    @pytest.fixture
    def adapter(self):
        from benchbox.platforms.presto import PrestoAdapter

        return PrestoAdapter(
            host=os.environ["PRESTO_HOST"],
            port=int(os.environ.get("PRESTO_PORT", "8080")),
            username=os.environ.get("PRESTO_USER", "benchbox"),
            catalog=os.environ.get("PRESTO_CATALOG", "tpch"),
            schema=os.environ.get("PRESTO_SCHEMA", "sf1"),
            capture_plans=True,
        )

    @pytest.fixture
    def connection(self, adapter):
        conn = adapter.create_connection()
        try:
            yield conn
        finally:
            adapter.close_connection(conn)

    def test_live_plan_parses(self, adapter, connection):
        _assert_live_plan(adapter, connection)


@pytest.mark.skipif(not os.environ.get("TRINO_HOST"), reason="live Trino not available (TRINO_HOST unset)")
class TestLiveTrinoQueryPlanCapture:
    @pytest.fixture
    def adapter(self):
        from benchbox.platforms.trino import TrinoAdapter

        return TrinoAdapter(
            host=os.environ["TRINO_HOST"],
            port=int(os.environ.get("TRINO_PORT", "8080")),
            username=os.environ.get("TRINO_USER", "benchbox"),
            catalog=os.environ.get("TRINO_CATALOG", "tpch"),
            schema=os.environ.get("TRINO_SCHEMA", "sf1"),
            capture_plans=True,
        )

    @pytest.fixture
    def connection(self, adapter):
        conn = adapter.create_connection()
        try:
            yield conn
        finally:
            adapter.close_connection(conn)

    def test_live_plan_parses(self, adapter, connection):
        _assert_live_plan(adapter, connection)


@pytest.mark.skipif(
    not os.environ.get("CLICKHOUSE_HOST"), reason="live ClickHouse not available (CLICKHOUSE_HOST unset)"
)
class TestLiveClickHouseQueryPlanCapture:
    @pytest.fixture
    def adapter(self):
        from benchbox.platforms.clickhouse.adapter import ClickHouseAdapter

        return ClickHouseAdapter(
            host=os.environ["CLICKHOUSE_HOST"],
            port=int(os.environ.get("CLICKHOUSE_PORT", "8123")),
            username=os.environ.get("CLICKHOUSE_USER", "default"),
            password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
            database=os.environ.get("CLICKHOUSE_DATABASE", "default"),
            capture_plans=True,
        )

    @pytest.fixture
    def connection(self, adapter):
        conn = adapter.create_connection()
        try:
            yield conn
        finally:
            adapter.close_connection(conn)

    def test_live_plan_parses(self, adapter, connection):
        _assert_live_plan(adapter, connection)


@pytest.mark.skipif(not os.environ.get("SPARK_MASTER"), reason="live Spark not available (SPARK_MASTER unset)")
class TestLiveSparkQueryPlanCapture:
    @pytest.fixture
    def adapter(self):
        from benchbox.platforms.spark import SparkAdapter

        return SparkAdapter(
            master=os.environ["SPARK_MASTER"],
            capture_plans=True,
        )

    @pytest.fixture
    def connection(self, adapter):
        conn = adapter.create_connection()
        try:
            yield conn
        finally:
            adapter.close_connection(conn)

    def test_live_plan_parses(self, adapter, connection):
        _assert_live_plan(adapter, connection)
