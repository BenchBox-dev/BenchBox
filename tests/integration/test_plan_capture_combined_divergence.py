# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""Integration tests for combined-mode plan-capture divergence.

The isolated capture phase runs after the timed loop. For a read-only workload
that is exactly correct, but a workload that MUTATES data mid-run (combined mode:
power -> throughput -> maintenance) would otherwise have its read-phase plans
EXPLAINed against the POST-maintenance data state — describing a plan the
optimizer never chose during measurement.

These exercise the resolution (query-plan-capture-post-measurement-divergence):

- A capture *checkpoint* fires before the maintenance mutation so read-phase
  plans are captured against the pre-mutation data state they were measured
  against, while the maintenance writes are captured once in the final pass.
- Capture is driven by the recorded-query buffer (digest-keyed, SUCCESS-only),
  and plans attach to result rows by exact capture key or, as a FALLBACK for a
  row that carries no key at all, by the bare public query_id. The TPC
  power/throughput drivers (``benchbox/core/{tpch,tpcds}/{power,throughput}_test.py``
  + their ``platform_power.py`` row-shapers) now propagate the internal
  ``_plan_capture_key`` from the adapter's ``execute_query()`` result all the
  way through to the row ``_attach_captured_plans`` sees, specifically so a
  COMBINED run (power then throughput on the same public query ids) matches
  each row by its EXACT key instead of the public-id fallback — see
  ``test_combined_power_then_throughput_same_public_id_different_sql`` below.
  The public-id fallback below still exercises the general mechanism (e.g. for
  a hypothetical driver that cannot supply a key), verified end-to-end against
  the real DuckDB TPC-H power path in ``test_real_tpch_power_capture_attaches_plans``.

They run against a real (file-based) DuckDB so EXPLAIN sees the live row counts.
"""

from __future__ import annotations

import random

import pytest

from benchbox.platforms.base.result_capture import _plan_capture_key
from benchbox.platforms.duckdb import DuckDBAdapter

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,  # required speed marker: real (file-based) DuckDB I/O
]


@pytest.fixture
def file_adapter(tmp_path):
    """A file-based DuckDB adapter so a phase connection sees the loaded data."""
    db_path = str(tmp_path / "divergence.duckdb")
    return DuckDBAdapter(database_path=db_path, capture_plans=True)


def _seed(conn, rows: int) -> None:
    conn.execute("CREATE TABLE t (id INTEGER, val INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?, ?)", [(i, i % 7) for i in range(rows)])


def _row_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]


def _spy_data_state_at_capture(adapter, monkeypatch) -> dict[str, int]:
    """Patch capture_query_plan to record the table row count seen at each call.

    Returns a dict mapping capture key -> row count visible to that EXPLAIN, so a
    test can assert *which* data state each query's plan was captured against.
    """
    seen: dict[str, int] = {}
    original = adapter.capture_query_plan

    def _spy(connection, sql, capture_key):
        seen[str(capture_key)] = _row_count(connection)
        return original(connection, sql, capture_key)

    monkeypatch.setattr(adapter, "capture_query_plan", _spy)
    return seen


def _begin_phase(adapter) -> None:
    adapter._plan_capture_phase_active = True
    adapter._phase_recorded_queries = {}
    adapter._captured_plans = {}


def _record(adapter, query_id: str, sql: str) -> str:
    """Record a SUCCESS query into the buffer exactly as the chokepoint does."""
    key = _plan_capture_key(query_id, sql)
    adapter._phase_recorded_queries[key] = sql
    return key


def test_combined_maintenance_mutation_captures_read_plan_before_mutation(file_adapter, monkeypatch):
    """A pre-maintenance checkpoint captures read plans against the measured state.

    Simulates the combined-mode lifecycle at the capture seam using the production
    row shape (power/throughput rows carry only the bare query_id, no capture key):
    the read phase is recorded and checkpoint-captured, then a maintenance mutation
    lands, then the final post-measurement pass captures the write. The read query's
    plan must be EXPLAINed against the pre-mutation row count, never the post one,
    and must still attach to its row via the public-id fallback.
    """
    conn = file_adapter.create_connection()
    try:
        _seed(conn, 10)
        seen = _spy_data_state_at_capture(file_adapter, monkeypatch)
        _begin_phase(file_adapter)

        # --- Read phase (power/throughput): record + build a result row ---
        read_sql = "SELECT id, val FROM t WHERE val > 2 ORDER BY id"
        read_key = _record(file_adapter, "q_read", read_sql)
        read_row = {"query_id": "q_read", "status": "SUCCESS", "stream_id": 0}  # no _plan_capture_key

        # Checkpoint fires before maintenance: read plan captured at 10 rows.
        file_adapter._plan_capture_checkpoint(conn)
        assert seen.get(read_key) == 10, "read plan must be captured before the mutation"

        # --- Maintenance phase: data mutates, then a write is recorded ---
        conn.executemany("INSERT INTO t VALUES (?, ?)", [(100 + i, i % 7) for i in range(90)])
        assert _row_count(conn) == 100

        maint_sql = "DELETE FROM t WHERE id > 95"
        maint_key = _record(file_adapter, "q_maint", maint_sql)
        maint_row = {"query_id": "q_maint", "status": "SUCCESS", "stream_id": 0}

        file_adapter._plan_capture_phase_active = False
        file_adapter._capture_plans_post_measurement(
            conn,
            dict(file_adapter._phase_recorded_queries),
            [read_row, maint_row],
        )

        # Read plan captured exactly once, at the pre-mutation state (10 rows); the
        # final pass must NOT re-EXPLAIN it against the post-mutation 100 rows.
        assert seen[read_key] == 10
        # The maintenance write is captured in the final pass (post-mutation is the
        # state it actually ran against).
        assert seen[maint_key] == 100

        # Both rows carry their captured plan, attached via the public-id fallback.
        assert read_row.get("plan_fingerprint")
        assert read_row.get("query_plan") is not None
        assert read_row["query_plan"].query_id == "q_read"
        assert maint_row.get("plan_fingerprint")
    finally:
        conn.close()


def test_combined_maintenance_capture_does_not_reexecute_write(file_adapter):
    """The maintenance DELETE captured in the final pass must not run a second time."""
    conn = file_adapter.create_connection()
    try:
        _seed(conn, 20)
        _begin_phase(file_adapter)

        maint_sql = "DELETE FROM t WHERE id < 5"
        _record(file_adapter, "q_maint", maint_sql)
        conn.execute(maint_sql)  # the measured execution (runs once)
        after_measured = _row_count(conn)
        assert after_measured == 15

        maint_row = {"query_id": "q_maint", "status": "SUCCESS"}
        file_adapter._plan_capture_phase_active = False
        file_adapter._capture_plans_post_measurement(conn, dict(file_adapter._phase_recorded_queries), [maint_row])

        # Capturing the plan must not re-run the DELETE (structural EXPLAIN only).
        assert _row_count(conn) == after_measured, "capture must not re-execute the write"
        assert maint_row.get("plan_fingerprint")
    finally:
        conn.close()


def test_read_only_combined_capture_attaches_via_public_id(file_adapter):
    """Read-only rows in TPC shape (no capture key) still get plans, no checkpoint needed."""
    conn = file_adapter.create_connection()
    try:
        _seed(conn, 12)
        _begin_phase(file_adapter)

        rows = []
        for qid, sql in (("q1", "SELECT COUNT(*) FROM t"), ("q2", "SELECT id FROM t WHERE val = 3")):
            _record(file_adapter, qid, sql)
            rows.append({"query_id": qid, "status": "SUCCESS"})  # no _plan_capture_key

        file_adapter._plan_capture_phase_active = False
        file_adapter._capture_plans_post_measurement(conn, dict(file_adapter._phase_recorded_queries), rows)

        for row in rows:
            assert row.get("plan_fingerprint"), f"no fingerprint for {row['query_id']}"
            assert row.get("query_plan") is not None
    finally:
        conn.close()


def test_ambiguous_query_id_variants_not_misattached(file_adapter):
    """A query_id that ran as two distinct SQL variants must not be mis-paired
    WHEN NEITHER ROW CARRIES A CAPTURE KEY (the public-id-fallback safety net, for
    a driver that cannot supply one). Production TPC power/throughput rows DO carry
    the key today (see test_combined_power_then_throughput_same_public_id_different_sql
    below, which covers the real combined-mode case via the exact-key path instead),
    but the fallback itself must still refuse to guess for a keyless row: it cannot
    tell which row ran which variant, so it must leave them unattached rather than
    attach a wrong plan.
    """
    conn = file_adapter.create_connection()
    try:
        _seed(conn, 8)
        _begin_phase(file_adapter)

        # Same public id, two different SQL texts -> two distinct buffer keys.
        _record(file_adapter, "q", "SELECT id FROM t WHERE val > 1")
        _record(file_adapter, "q", "SELECT id FROM t WHERE val > 4")
        rows = [
            {"query_id": "q", "status": "SUCCESS", "stream_id": 0},
            {"query_id": "q", "status": "SUCCESS", "stream_id": 1},
        ]

        file_adapter._plan_capture_phase_active = False
        file_adapter._capture_plans_post_measurement(conn, dict(file_adapter._phase_recorded_queries), rows)

        for row in rows:
            assert row.get("plan_fingerprint") is None, "ambiguous variant must not be guessed"
            assert row.get("query_plan") is None
    finally:
        conn.close()


def test_standard_path_exact_key_attaches_each_variant(file_adapter):
    """Rows that DO carry an exact capture key (standard path) keep per-variant fidelity."""
    conn = file_adapter.create_connection()
    try:
        _seed(conn, 8)
        _begin_phase(file_adapter)

        sql_a = "SELECT id FROM t WHERE val > 1"
        sql_b = "SELECT id FROM t WHERE val > 4"
        key_a = _record(file_adapter, "q", sql_a)
        key_b = _record(file_adapter, "q", sql_b)
        rows = [
            {"query_id": "q", "status": "SUCCESS", "stream_id": 0, "_plan_capture_key": key_a},
            {"query_id": "q", "status": "SUCCESS", "stream_id": 1, "_plan_capture_key": key_b},
        ]

        file_adapter._plan_capture_phase_active = False
        file_adapter._capture_plans_post_measurement(conn, dict(file_adapter._phase_recorded_queries), rows)

        # Each row attaches the plan for the exact SQL it ran; the key is consumed.
        assert rows[0].get("plan_fingerprint")
        assert rows[1].get("plan_fingerprint")
        assert "_plan_capture_key" not in rows[0]
        assert "_plan_capture_key" not in rows[1]
    finally:
        conn.close()


def test_failed_row_not_annotated_and_key_cleared(file_adapter):
    """A FAILED row sharing a query_id must never be annotated; its key is cleared."""
    conn = file_adapter.create_connection()
    try:
        _seed(conn, 6)
        _begin_phase(file_adapter)
        sql = "SELECT id FROM t"
        key = _record(file_adapter, "q", sql)
        ok_row = {"query_id": "q", "status": "SUCCESS", "_plan_capture_key": key}
        bad_row = {"query_id": "q", "status": "FAILED", "_plan_capture_key": key}

        file_adapter._plan_capture_phase_active = False
        file_adapter._capture_plans_post_measurement(
            conn, dict(file_adapter._phase_recorded_queries), [ok_row, bad_row]
        )

        assert ok_row.get("plan_fingerprint")
        assert bad_row.get("plan_fingerprint") is None
        assert "_plan_capture_key" not in bad_row
    finally:
        conn.close()


def test_checkpoint_is_noop_when_phase_inactive(file_adapter):
    """The checkpoint must do nothing outside the isolated capture phase."""
    conn = file_adapter.create_connection()
    try:
        _seed(conn, 5)
        file_adapter._plan_capture_phase_active = False
        file_adapter._phase_recorded_queries = {}
        file_adapter._captured_plans = {}

        file_adapter._plan_capture_checkpoint(conn)
        assert file_adapter._captured_plans == {}, "no capture should happen when phase inactive"
    finally:
        conn.close()


@pytest.mark.slow
def test_real_tpch_power_capture_attaches_plans(tmp_path):
    """End-to-end: the real TPC-H power driver path attaches captured plans to rows.

    Regression guard for the production code path the method-level tests model.
    The TPC-H power driver now propagates the internal capture key through to its
    result rows (see the module docstring), so this also confirms that
    propagation does not break the ordinary single-run case. Generates a tiny SF
    (data-gen marks this ``slow``).
    """
    from benchbox.core.tpch.benchmark import TPCHBenchmark

    db_path = str(tmp_path / "power.duckdb")
    adapter = DuckDBAdapter(database_path=db_path, capture_plans=True)
    conn = adapter.create_connection()
    try:
        bench = TPCHBenchmark(scale_factor=0.01, output_dir=str(tmp_path / "data"))
        bench.generate_data()
        adapter.create_schema(bench, conn)
        adapter.load_data(bench, conn, str(tmp_path / "data"))

        run_config = {
            "benchmark_name": "tpch",
            "test_execution_type": "power",
            "scale_factor": 0.01,
            "iterations": 1,
            "warm_up_iterations": 0,
            "query_subset": [1, 6],
        }
        results = adapter._execute_queries_by_type(bench, conn, run_config)

        assert results, "power test produced no rows"
        for row in results:
            if row.get("status") != "SUCCESS":
                continue
            assert row.get("plan_fingerprint"), f"power row {row.get('query_id')} got no plan"
            assert row.get("query_plan") is not None
    finally:
        conn.close()


@pytest.mark.slow
def test_combined_power_then_throughput_same_public_id_different_sql(tmp_path):
    """Regression for the P1 finding: a default combined run (power -> throughput)
    executes the SAME public query ids twice, and throughput's per-stream seed
    renders DIFFERENT SQL text for the SAME id, so the two executions capture under
    DIFFERENT internal keys. Before the fix, neither TPC driver's rows carried
    ``_plan_capture_key`` at all, so BOTH attached only via the public-id fallback -
    and the fallback poisons ANY public id that captured more than one distinct SQL
    variant, leaving BOTH the power row and the throughput row unattached (even
    though the power row's own pre-mutation-checkpoint plan was perfectly
    unambiguous on its own). With the fix, both rows carry their OWN exact capture
    key, so each attaches its own plan regardless of the other phase's variant.
    """
    from benchbox.core.tpch.benchmark import TPCHBenchmark

    db_path = str(tmp_path / "combined.duckdb")
    adapter = DuckDBAdapter(database_path=db_path, capture_plans=True)
    conn = adapter.create_connection()
    try:
        bench = TPCHBenchmark(scale_factor=0.01, output_dir=str(tmp_path / "data"))
        bench.generate_data()
        adapter.create_schema(bench, conn)
        adapter.load_data(bench, conn, str(tmp_path / "data"))

        run_config = {
            "benchmark_name": "tpch",
            "test_execution_type": "combined",
            "scale_factor": 0.01,
            "seed": 1,
            "iterations": 1,
            "warm_up_iterations": 0,
            "num_streams": 2,
            "query_subset": [6],  # Q6 has seed-parameterized date/discount predicates.
            "options": {"requested_phases": ["power", "throughput"]},
        }
        results = adapter._execute_queries_by_type(bench, conn, run_config)

        power_rows = [r for r in results if r.get("test_type") == "power" and r.get("status") == "SUCCESS"]
        throughput_rows = [r for r in results if r.get("test_type") == "throughput" and r.get("status") == "SUCCESS"]
        assert power_rows, "combined run produced no successful power rows"
        assert throughput_rows, "combined run produced no successful throughput rows"

        # Every successful row -- power AND throughput -- must have its own captured
        # plan, regardless of whether the other phase captured the SAME public id
        # under a different SQL variant.
        for row in power_rows + throughput_rows:
            assert row.get("plan_fingerprint"), (
                f"{row.get('test_type')} row for query {row.get('query_id')} got no plan "
                "(public-id ambiguity from the other phase must not poison this row)"
            )
            assert row.get("query_plan") is not None
            assert "_plan_capture_key" not in row, "the internal key must be consumed, not leaked to the caller"
    finally:
        conn.close()


@pytest.mark.slow
def test_real_combined_power_maintenance_checkpoint_captures_pre_mutation_plan(tmp_path, monkeypatch):
    """Regression for the real production checkpoint call site.

    The hand-driven tests above (``test_combined_maintenance_mutation_captures_read_plan_before_mutation``
    etc.) exercise ``_plan_capture_checkpoint``/``_capture_plans_post_measurement`` by
    calling them directly, never through the real
    ``_execute_combined_test`` -> ``_execute_tpch_maintenance_test`` lifecycle. Proof of
    the blind spot: deleting the checkpoint call at the top of
    ``_execute_tpch_maintenance_test`` (``self._plan_capture_checkpoint(connection)``) -
    i.e. fully reverting the divergence fix - leaves every test in this file green,
    because none of them drives a real combined power->maintenance run under
    ``capture_plans=True``.

    This test does: a real (file-based) DuckDB TPC-H combined run, power phase then
    maintenance phase, through the actual ``_execute_queries_by_type`` entry point.
    RF1 inserts new rows into ``lineitem`` (and ``orders``); Q1 (a plain lineitem scan)
    is the power-phase query. A spy on ``capture_query_plan`` records the ``lineitem``
    row count visible at the instant Q1's plan is EXPLAINed. If the checkpoint fires
    where it should - before RF1's mutation - that count equals the PRE-mutation
    (post-load) row count. If the checkpoint call is removed or reordered, Q1's plan
    is instead captured in the final post-measurement pass, AFTER RF1 has already
    mutated the table, and this assertion fails.
    """
    from benchbox.core.tpch.benchmark import TPCHBenchmark

    db_path = str(tmp_path / "combined_maintenance.duckdb")
    adapter = DuckDBAdapter(database_path=db_path, capture_plans=True)
    conn = adapter.create_connection()
    try:
        bench = TPCHBenchmark(scale_factor=0.01, output_dir=str(tmp_path / "data"))
        bench.generate_data()
        adapter.create_schema(bench, conn)
        adapter.load_data(bench, conn, str(tmp_path / "data"))

        baseline_lineitem_count = conn.execute("SELECT COUNT(*) FROM lineitem").fetchone()[0]
        # RF2 (delete) targets the single oldest order at scale factor 0.01 (see
        # TPCHMaintenanceTest._identify_old_orders / num_to_delete). Recording its
        # key AND its current lineitem count now, before the run, lets the mutation
        # below be made deterministic (see the random.randint patch): RF1's insert
        # count is otherwise `random.randint(1, 7)`, which could coincidentally
        # equal the oldest order's own lineitem count, netting the total lineitem
        # row count back to the baseline regardless of whether the checkpoint fired.
        oldest_order_key = conn.execute("SELECT O_ORDERKEY FROM orders ORDER BY O_ORDERDATE ASC LIMIT 1").fetchone()[0]
        oldest_order_lineitem_count = conn.execute(
            "SELECT COUNT(*) FROM lineitem WHERE L_ORDERKEY = ?", [oldest_order_key]
        ).fetchone()[0]

        # Force RF1's insert count to be provably different from what RF2 is about
        # to delete, so the net lineitem row count is guaranteed to move (not just
        # usually move) - only the maintenance test's own num_items roll (its one
        # `randint(1, 7)` call site) is intercepted; every other random call in the
        # maintenance test (order dates, keys, prices, ...) is untouched.
        forced_insert_count = oldest_order_lineitem_count + 1
        original_randint = random.randint

        def _deterministic_randint(a, b):
            if (a, b) == (1, 7):
                return forced_insert_count
            return original_randint(a, b)

        monkeypatch.setattr(random, "randint", _deterministic_randint)

        # Record the lineitem row count visible at the instant Q1's SELECT plan is
        # captured. RF1's own INSERT statements never match this filter (not a
        # SELECT), so a non-empty list unambiguously means Q1's plan.
        captured_counts: list[int] = []
        original_capture_query_plan = adapter.capture_query_plan

        def _spy(connection, sql, capture_key):
            if sql.strip().upper().startswith("SELECT") and "lineitem" in sql.lower():
                captured_counts.append(connection.execute("SELECT COUNT(*) FROM lineitem").fetchone()[0])
            return original_capture_query_plan(connection, sql, capture_key)

        monkeypatch.setattr(adapter, "capture_query_plan", _spy)

        run_config = {
            "benchmark_name": "tpch",
            "test_execution_type": "combined",
            "scale_factor": 0.01,
            "iterations": 1,
            "warm_up_iterations": 0,
            "query_subset": [1],  # Q1: a plain lineitem scan, no seed-varied predicates needed
            "maintenance_pairs": 1,
            "rf1_interval": 0.0,
            "rf2_interval": 0.0,
            "validate_integrity": False,
            "output_dir": str(tmp_path / "maintenance_output"),
            "options": {"requested_phases": ["power", "maintenance"]},
        }
        results = adapter._execute_queries_by_type(bench, conn, run_config)

        power_rows = [r for r in results if r.get("test_type") == "power" and r.get("status") == "SUCCESS"]
        assert power_rows, "combined run produced no successful power rows"
        assert power_rows[0].get("plan_fingerprint"), "Q1's power-phase plan was never captured"

        # RF2 must have actually deleted the pre-identified oldest order, or the
        # pre/post comparison below would be vacuously true regardless of whether
        # the checkpoint fired.
        remaining = conn.execute("SELECT COUNT(*) FROM orders WHERE O_ORDERKEY = ?", [oldest_order_key]).fetchone()[0]
        assert remaining == 0, "RF2 did not delete the identified oldest order - test setup invalid"

        post_run_lineitem_count = conn.execute("SELECT COUNT(*) FROM lineitem").fetchone()[0]
        # Guaranteed by the forced insert count above, not a probabilistic hope -
        # this is the invariant the whole test depends on to distinguish a
        # pre-mutation capture from a post-mutation one.
        assert post_run_lineitem_count != baseline_lineitem_count, (
            "lineitem row count did not change net of the mutation - test setup invalid"
        )

        assert captured_counts == [baseline_lineitem_count], (
            f"expected Q1's plan captured exactly once, at the pre-mutation row count "
            f"{baseline_lineitem_count}, but got {captured_counts} (post-mutation count is "
            f"{post_run_lineitem_count}) - the pre-maintenance checkpoint did not fire "
            "before RF1's mutation"
        )
    finally:
        conn.close()
