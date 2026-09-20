# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""Live plan-capture hooks for the misc-platform parsers (Databend, QuestDB, Doris, SingleStore).

Each class runs a
real EXPLAIN over a live instance and asserts the adapter's
get_query_plan_parser() yields a non-None QueryPlanDAG with a stable
fingerprint. Every class is gated on its own env var and skips cleanly when
the engine is absent. Shares the provenance convention in
tests/fixtures/query_plans/PROVENANCE.md with the sibling
query-plan-capture-parser-live-validation item.
"""

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
]


def _assert_live_plan(adapter, connection, query="SELECT 1"):
    # Two EXPLAINs of a trivial query by design (get + capture); keep the
    # query trivial — these modules cover provisioned engines only, never
    # per-byte-billed ones.
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


@pytest.mark.skipif(not os.environ.get("DATABEND_HOST"), reason="live Databend not available (DATABEND_HOST unset)")
class TestLiveDatabendQueryPlanCapture:
    @pytest.fixture
    def adapter(self):
        from benchbox.platforms.databend.adapter import DatabendAdapter

        return DatabendAdapter(
            host=os.environ["DATABEND_HOST"],
            username=os.environ.get("DATABEND_USER", "root"),
            password=os.environ.get("DATABEND_PASSWORD", ""),
            database=os.environ.get("DATABEND_DATABASE", "default"),
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


@pytest.mark.skipif(not os.environ.get("QUESTDB_HOST"), reason="live QuestDB not available (QUESTDB_HOST unset)")
class TestLiveQuestDBQueryPlanCapture:
    @pytest.fixture
    def adapter(self):
        from benchbox.platforms.questdb import QuestDBAdapter

        return QuestDBAdapter(
            host=os.environ.get("QUESTDB_HOST", "localhost"),
            pg_port=int(os.environ.get("QUESTDB_PG_PORT", "8812")),
            username=os.environ.get("QUESTDB_USER", "admin"),
            password=os.environ.get("QUESTDB_PASSWORD", "quest"),
            database=os.environ.get("QUESTDB_DATABASE", "qdb"),
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


@pytest.mark.skipif(not os.environ.get("DORIS_HOST"), reason="live Doris not available (DORIS_HOST unset)")
class TestLiveDorisQueryPlanCapture:
    @pytest.fixture
    def adapter(self):
        from benchbox.platforms.doris import DorisAdapter

        return DorisAdapter(
            host=os.environ["DORIS_HOST"],
            port=int(os.environ.get("DORIS_PORT", "9030")),
            username=os.environ.get("DORIS_USER", "root"),
            password=os.environ.get("DORIS_PASSWORD", ""),
            database=os.environ.get("DORIS_DATABASE", "benchbox_test"),
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
        _assert_live_plan(adapter, connection, query="SELECT 1")


@pytest.mark.skipif(
    not os.environ.get("SINGLESTORE_HOST"), reason="live SingleStore not available (SINGLESTORE_HOST unset)"
)
class TestLiveSingleStoreQueryPlanCapture:
    @pytest.fixture
    def adapter(self):
        from benchbox.platforms.singlestore import SingleStoreAdapter

        return SingleStoreAdapter(
            host=os.environ["SINGLESTORE_HOST"],
            port=int(os.environ.get("SINGLESTORE_PORT", "3306")),
            username=os.environ.get("SINGLESTORE_USER", "root"),
            password=os.environ.get("SINGLESTORE_PASSWORD", ""),
            database=os.environ.get("SINGLESTORE_DATABASE", "benchbox_test"),
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
