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
    """The phase must not leak its structural-only overrides back to the adapter."""
    _seed_table(file_adapter)
    file_adapter.analyze_plans = True
    file_adapter.plan_first_n = 7
    file_adapter.plan_sampling_rate = 0.5

    run_plan_capture_phase(file_adapter, {"q": "SELECT 1"})

    assert file_adapter.analyze_plans is True
    assert file_adapter.plan_first_n == 7
    assert file_adapter.plan_sampling_rate == 0.5
    assert file_adapter.capture_plans is True


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
