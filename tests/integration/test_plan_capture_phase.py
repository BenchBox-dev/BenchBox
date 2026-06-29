# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""Integration tests for the isolated, post-measurement plan-capture phase.

These exercise ``run_plan_capture_phase`` end-to-end against a real (file-based)
DuckDB database, the real DuckDB EXPLAIN, and the real DuckDBQueryPlanParser —
no external credentials required. They verify the two isolation guarantees that
motivated query-plan-capture-isolation-phase-design:

- the phase runs *after* measurement and does not re-execute DML
  (``dml_single_execution``), and
- the phase populates plan fingerprints in its result
  (``capture_phase`` fires post-measurement).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from benchbox.core.plan_capture_phase import run_plan_capture_phase
from benchbox.platforms.duckdb import DuckDBAdapter

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,  # required speed marker: real (file-based) DuckDB I/O
]


@pytest.fixture
def file_adapter(tmp_path):
    """A file-based DuckDB adapter so a fresh phase connection sees loaded data."""
    db_path = str(tmp_path / "phase.duckdb")
    return DuckDBAdapter(database_path=db_path, capture_plans=True)


def _seed_table(adapter: DuckDBAdapter) -> None:
    conn = adapter.create_connection()
    try:
        conn.execute("CREATE TABLE t (id INTEGER, val INTEGER)")
        conn.execute("INSERT INTO t VALUES (1, 10), (2, 20), (3, 30)")
    finally:
        conn.close()


def _row_count(adapter: DuckDBAdapter) -> int:
    conn = adapter.create_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM t").fetchall()[0][0]
    finally:
        conn.close()


def test_capture_phase_populates_fingerprints_post_measurement(file_adapter):
    """The capture phase opens its own connection and fills plans + fingerprints."""
    _seed_table(file_adapter)

    queries = {
        "q_select": "SELECT id, SUM(val) FROM t GROUP BY id",
        "q_filter": "SELECT * FROM t WHERE val > 15",
    }
    result = run_plan_capture_phase(file_adapter, queries)

    assert result.captured == 2
    assert result.failed == 0
    assert set(result.plans) == {"q_select", "q_filter"}
    # Structural fingerprints are populated for every captured query.
    for query_id in queries:
        assert result.fingerprints[query_id]
        assert result.per_query_capture_ms[query_id] >= 0.0
    assert result.total_capture_ms >= 0.0


def test_capture_phase_dml_single_execution(file_adapter):
    """A DML query is captured structurally without re-executing the write."""
    _seed_table(file_adapter)
    before = _row_count(file_adapter)
    assert before == 3

    # The capture phase forces analyze_plans=False, and the shared DML guard
    # downgrades writes to EXPLAIN (FORMAT JSON) — so EXPLAIN must not insert.
    result = run_plan_capture_phase(
        file_adapter,
        {"q_insert": "INSERT INTO t VALUES (4, 40)"},
    )

    after = _row_count(file_adapter)
    assert after == before, "capture phase must not execute the INSERT"
    # The structural plan is still captured for the DML statement.
    assert result.captured == 1
    assert result.fingerprints["q_insert"]


def test_capture_phase_restores_adapter_config(file_adapter):
    """The phase must not leak its capture-on / analyze override back to the adapter."""
    _seed_table(file_adapter)
    file_adapter.analyze_plans = True
    saved_capture_plans = file_adapter.capture_plans

    # The phase forces analyze_plans=False (default) and capture_plans=True for its
    # duration, then must restore the adapter's prior values.
    run_plan_capture_phase(file_adapter, {"q": "SELECT 1"})

    assert file_adapter.analyze_plans is True
    assert file_adapter.capture_plans == saved_capture_plans


def test_capture_phase_reuses_supplied_connection(file_adapter):
    """When a connection is supplied, the phase captures against it and leaves it open."""
    _seed_table(file_adapter)
    conn = file_adapter.create_connection()
    try:
        result = run_plan_capture_phase(
            file_adapter,
            {"q": "SELECT * FROM t"},
            connection=conn,
        )
        assert result.captured == 1
        # Connection is still usable: phase must not close a caller-owned connection.
        assert conn.execute("SELECT COUNT(*) FROM t").fetchall()[0][0] == 3
    finally:
        conn.close()


class _FakeBenchmark:
    """Minimal benchmark exposing get_queries() for _execute_all_queries."""

    scale_factor = 1.0

    def __init__(self, queries: dict[str, str]):
        self._queries = queries

    def get_queries(self) -> dict[str, str]:
        return dict(self._queries)


class TestIntegratedCapturePhase:
    """The generic run pipeline (_execute_all_queries) drives the isolated phase.

    These exercise the wiring end-to-end: inline capture is suppressed during the
    timed loop for phase-eligible adapters, and plans are captured in a single
    post-measurement pass and merged into the result dicts.
    """

    def test_eligible_adapter_populates_fingerprints_via_phase(self, file_adapter):
        _seed_table(file_adapter)
        conn = file_adapter.create_connection()
        try:
            benchmark = _FakeBenchmark(
                {
                    "q_select": "SELECT id, val FROM t ORDER BY id",
                    "q_agg": "SELECT SUM(val) FROM t",
                }
            )
            results = file_adapter._execute_all_queries(benchmark, conn, {"benchmark_name": "generic"})

            assert {r["query_id"] for r in results} == {"q_select", "q_agg"}
            for result in results:
                assert result["status"] == "SUCCESS"
                assert result.get("plan_fingerprint"), f"no fingerprint for {result['query_id']}"
                assert "plan_capture_time_ms" in result
            # The suppression toggle must be restored after the run.
            assert file_adapter.capture_plans is True
        finally:
            conn.close()

    def test_inline_capture_suppressed_during_measurement(self, file_adapter, monkeypatch):
        """Inline EXPLAIN must NOT run during the timed loop; the phase fills plans after.

        The query is executed through the full dispatch so the central isolation
        wrapper is active. During the timed run the inline chokepoint records the
        query (phase-active) instead of running EXPLAIN; capture_query_plan must only
        be invoked by the post-measurement phase.
        """
        _seed_table(file_adapter)
        conn = file_adapter.create_connection()

        # Spy on the actual inline EXPLAIN entry point and record whether the
        # isolation flag was active at each call.
        phase_active_at_call: list[bool] = []
        original_capture = file_adapter.capture_query_plan

        def _capture_spy(connection, query, query_id):
            phase_active_at_call.append(file_adapter._plan_capture_phase_active)
            return original_capture(connection, query, query_id)

        monkeypatch.setattr(file_adapter, "capture_query_plan", _capture_spy)

        try:
            benchmark = _FakeBenchmark({"q_select": "SELECT * FROM t"})
            results = file_adapter._execute_queries_by_type(
                benchmark, conn, {"benchmark_name": "generic", "test_execution_type": "standard"}
            )

            # capture_query_plan ran exactly once (the post-measurement phase), and
            # never while the timed loop's isolation flag was active.
            assert len(phase_active_at_call) == 1
            assert phase_active_at_call == [False], "EXPLAIN must run only in the post-measurement phase"
            # The plan still landed via the phase.
            assert results[0].get("plan_fingerprint")
            # The isolation flag is cleared after the run.
            assert file_adapter._plan_capture_phase_active is False
        finally:
            conn.close()

    def test_phase_honors_analyze_plans_true(self, file_adapter):
        """analyze_plans=True (the canonical knob) must run EXPLAIN ANALYZE in the phase.

        Regression test for the dead-knob defect: the post-measurement phase used to
        hard-code structural-only capture, so --capture-plans silently lost ANALYZE
        timing. It must now honour the adapter's analyze_plans.
        """
        _seed_table(file_adapter)
        assert file_adapter.analyze_plans is True  # DuckDB default
        conn = file_adapter.create_connection()
        try:
            benchmark = _FakeBenchmark({"q": "SELECT id, SUM(val) FROM t GROUP BY id"})
            results = file_adapter._execute_all_queries(benchmark, conn, {"benchmark_name": "generic"})

            plan = results[0].get("query_plan")
            assert plan is not None
            phys = plan.logical_root.physical_operator
            assert phys is not None
            # EXPLAIN ANALYZE populates per-operator timing; structural-only would not.
            assert phys.properties.get("timing") is not None, "phase must run ANALYZE when analyze_plans=True"
        finally:
            conn.close()

    def test_phase_structural_only_when_analyze_disabled(self, file_adapter):
        """analyze_plans=False keeps the phase structural-only (no re-execution timing)."""
        _seed_table(file_adapter)
        file_adapter.analyze_plans = False
        conn = file_adapter.create_connection()
        try:
            benchmark = _FakeBenchmark({"q": "SELECT id, SUM(val) FROM t GROUP BY id"})
            results = file_adapter._execute_all_queries(benchmark, conn, {"benchmark_name": "generic"})

            plan = results[0].get("query_plan")
            assert plan is not None
            assert results[0].get("plan_fingerprint"), "structural fingerprint still captured"
            phys = plan.logical_root.physical_operator
            timing = phys.properties.get("timing") if phys else None
            assert timing is None or timing == 0, "analyze_plans=False must not run ANALYZE"
        finally:
            conn.close()

    def test_phase_runs_for_non_power_test_types(self, file_adapter, monkeypatch):
        """Capture must be isolated for every test type, not just power/standard.

        Drives the dispatch with test_execution_type='throughput'; the central
        isolation wrapper must record during the timed run and capture in the
        post-measurement phase (EXPLAIN never runs inline during measurement).
        """
        _seed_table(file_adapter)
        conn = file_adapter.create_connection()

        phase_active_at_call: list[bool] = []
        original_capture = file_adapter.capture_query_plan

        def _capture_spy(connection, query, query_id):
            phase_active_at_call.append(file_adapter._plan_capture_phase_active)
            return original_capture(connection, query, query_id)

        monkeypatch.setattr(file_adapter, "capture_query_plan", _capture_spy)
        try:
            benchmark = _FakeBenchmark({"q": "SELECT id, val FROM t"})
            # Non-TPC benchmark falls back to _execute_all_queries under the wrapper.
            results = file_adapter._execute_queries_by_type(
                benchmark, conn, {"benchmark_name": "generic", "test_execution_type": "throughput"}
            )
            assert results[0].get("plan_fingerprint"), "plan must land for throughput type"
            assert phase_active_at_call == [False], "EXPLAIN must run only post-measurement"
        finally:
            conn.close()

    def test_plans_attach_to_all_rows_sharing_query_id(self, file_adapter):
        """Throughput produces one row per stream for a query; all must get the plan."""
        _seed_table(file_adapter)
        conn = file_adapter.create_connection()
        try:
            # Two result rows for the same query_id, as concurrent streams produce.
            results = [
                {"query_id": "q", "status": "SUCCESS", "stream_id": 0},
                {"query_id": "q", "status": "SUCCESS", "stream_id": 1},
            ]
            file_adapter._capture_plans_post_measurement(conn, {"q": "SELECT * FROM t"}, results)

            for row in results:
                assert row.get("plan_fingerprint"), f"row stream {row['stream_id']} missing plan"
                assert row.get("query_plan") is not None
            # Same query captured once: both rows share the identical fingerprint.
            assert results[0]["plan_fingerprint"] == results[1]["plan_fingerprint"]
        finally:
            conn.close()

    def test_plans_land_for_integer_query_ids(self, file_adapter):
        """TPC-H power/throughput rows carry an INTEGER query_id; plans must still land.

        Regression test: the recorded buffer is str-keyed, so an int query_id on the
        result row would never match the merge unless both sides are coerced to str.
        """
        _seed_table(file_adapter)
        conn = file_adapter.create_connection()
        try:
            # Buffer recorded under str keys (as the inline chokepoint stores them);
            # result rows carry the raw integer query id (as TPC-H builds them).
            results = [{"query_id": 6, "status": "SUCCESS", "stream_id": 0}]
            file_adapter._capture_plans_post_measurement(conn, {"6": "SELECT * FROM t"}, results)

            assert results[0].get("plan_fingerprint"), "plan must land for an integer query_id"
            assert results[0].get("query_plan") is not None
        finally:
            conn.close()

    def test_plan_identity_tracks_same_query_id_distinct_sql(self, file_adapter, monkeypatch):
        """Rows sharing a query_id must attach the plan for their own executed SQL."""
        from benchbox.platforms.base.result_capture import _plan_capture_key

        conn = file_adapter.create_connection()
        capture_calls: list[tuple[str, str]] = []
        sql_a = "SELECT 1 AS stream_value"
        sql_b = "SELECT 2 AS stream_value"
        capture_key_a = _plan_capture_key("q", sql_a)
        capture_key_b = _plan_capture_key("q", sql_b)

        def _capture_spy(connection, sql, capture_key):
            capture_calls.append((capture_key, sql))
            return SimpleNamespace(query_id=capture_key, plan_fingerprint=f"fp::{sql}"), 1.0

        monkeypatch.setattr(file_adapter, "capture_query_plan", _capture_spy)
        results = [
            {"query_id": "q", "status": "SUCCESS", "stream_id": 0, "_plan_capture_key": capture_key_a},
            {"query_id": "q", "status": "SUCCESS", "stream_id": 1, "_plan_capture_key": capture_key_b},
        ]
        try:
            file_adapter._capture_plans_post_measurement(
                conn,
                {
                    capture_key_a: sql_a,
                    capture_key_b: sql_b,
                },
                results,
            )
        finally:
            conn.close()

        assert capture_calls == [(capture_key_a, sql_a), (capture_key_b, sql_b)]
        assert results[0]["plan_fingerprint"] == f"fp::{sql_a}"
        assert results[1]["plan_fingerprint"] == f"fp::{sql_b}"
        assert results[0]["query_plan"].query_id == "q"
        assert results[1]["query_plan"].query_id == "q"
        assert "_plan_capture_key" not in results[0]
        assert "_plan_capture_key" not in results[1]

    def test_dml_executed_exactly_once(self, file_adapter):
        """A DML query runs once during measurement; the phase must not re-execute it."""
        _seed_table(file_adapter)
        conn = file_adapter.create_connection()
        try:
            before = conn.execute("SELECT COUNT(*) FROM t").fetchall()[0][0]
            benchmark = _FakeBenchmark({"q_insert": "INSERT INTO t VALUES (4, 40)"})
            results = file_adapter._execute_all_queries(benchmark, conn, {"benchmark_name": "generic"})

            after = conn.execute("SELECT COUNT(*) FROM t").fetchall()[0][0]
            assert after == before + 1, "DML must run exactly once (phase must not re-execute it)"
            # The structural plan is still captured for the DML statement.
            assert results[0].get("plan_fingerprint")
        finally:
            conn.close()


class TestCanonicalCaptureContract:
    """w6: the canonical model — one isolated phase, ``analyze_plans`` the only
    capture-detail knob, default eligibility ON for every EXPLAIN engine, and the
    per-iteration/per-stream sampling machinery retired.
    """

    def test_explain_engines_default_phase_eligible(self):
        """EXPLAIN engines inherit default-ON eligibility; the base default is True."""
        from benchbox.platforms.base.adapter import PlatformAdapter

        assert PlatformAdapter.plan_capture_phase_eligible is True
        assert DuckDBAdapter.plan_capture_phase_eligible is True

    def test_bigquery_is_the_side_effect_exception(self):
        """BigQuery is the one engine excluded from the isolated phase."""
        from benchbox.platforms.bigquery import BigQueryAdapter

        assert BigQueryAdapter.plan_capture_phase_eligible is False

    def test_sampling_machinery_is_retired(self, file_adapter):
        """The per-iteration / per-stream sampling attributes no longer exist;
        only the ``plan_query_filter`` query-selection set remains."""
        assert not hasattr(file_adapter, "plan_first_n")
        assert not hasattr(file_adapter, "plan_sampling_rate")
        assert not hasattr(file_adapter, "_plan_capture_iteration_counts")
        assert hasattr(file_adapter, "plan_query_filter")

    def test_analyze_plans_is_first_class_tri_state_on_configs(self):
        """analyze_plans is a first-class, tri-state field on BenchmarkConfig and
        RunConfig (None = not specified, so the adapter default True applies)."""
        from benchbox.core.schemas import BenchmarkConfig, RunConfig

        assert BenchmarkConfig(name="tpch", display_name="x").analyze_plans is None
        assert RunConfig(benchmark="tpch").analyze_plans is None

        bc = BenchmarkConfig(name="tpch", display_name="x", capture_plans=True, analyze_plans=False)
        # The orchestrator/runner thread BenchmarkConfig.analyze_plans into RunConfig.
        rc = RunConfig(benchmark="tpch", capture_plans=True, analyze_plans=bc.analyze_plans)
        assert rc.analyze_plans is False
