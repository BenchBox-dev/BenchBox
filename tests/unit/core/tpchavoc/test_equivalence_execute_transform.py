"""Fast unit coverage for the engine-agnostic ``execute_transform`` hook.

The fourth-engine (ClickHouse) sample runs both canonical and variant SQL through
the production query-time rewrites the real adapter applies. These tests pin that
plumbing without needing chDB: a fake connection records the exact SQL executed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from benchbox.core.tpchavoc.equivalence import _clickhouse_execute_transform, find_divergences

pytestmark = [pytest.mark.unit, pytest.mark.fast]


class _RecordingConnection:
    """Fake connection capturing every executed SQL string."""

    def __init__(self):
        self.executed: list[str] = []

    def execute(self, sql: str):
        self.executed.append(sql)
        result = MagicMock()
        result.fetchall.return_value = [(1,)]
        return result


def _benchmark_with_one_query():
    benchmark = MagicMock()
    benchmark.get_implemented_queries.return_value = [1]
    benchmark.get_query.return_value = "SELECT v FROM t"
    benchmark.validate_variant_equivalence.return_value = None  # never diverges
    return benchmark


def test_execute_transform_applied_to_canonical_and_every_variant():
    conn = _RecordingConnection()
    benchmark = _benchmark_with_one_query()

    divergences = find_divergences(
        conn,
        benchmark,
        lambda q: "SELECT c FROM t",
        translate_variant=lambda sql: sql,
        execute_transform=lambda sql: f"{sql} /*X*/",
    )

    assert divergences == []
    # 1 canonical + 10 variants, each rewritten by the transform.
    assert len(conn.executed) == 11
    assert all(sql.endswith(" /*X*/") for sql in conn.executed)
    assert conn.executed[0] == "SELECT c FROM t /*X*/"


def test_no_transform_leaves_sql_unchanged():
    conn = _RecordingConnection()
    benchmark = _benchmark_with_one_query()

    find_divergences(conn, benchmark, lambda q: "SELECT c FROM t", translate_variant=lambda sql: sql)

    # Default identity transform: the executed SQL is exactly what was rendered.
    assert conn.executed[0] == "SELECT c FROM t"
    assert all("/*X*/" not in sql for sql in conn.executed)


def test_clickhouse_execute_transform_mirrors_production_sequence():
    # transform() wraps divisors with NULLIF; add_query_settings() appends SETTINGS.
    out = _clickhouse_execute_transform("SELECT revenue / SUM(quantity) FROM t")
    assert "revenue / NULLIF(SUM(quantity), 0)" in out
    assert out.rstrip().endswith("SETTINGS joined_subquery_requires_alias = 0")


def test_clickhouse_execute_transform_keeps_windowed_divisor_intact():
    # Regression guard tied to the safe_division window-function fix: the OVER clause
    # stays inside the NULLIF rather than being stranded outside it.
    out = _clickhouse_execute_transform("SELECT mkt / SUM(volume) OVER (PARTITION BY o_year) FROM t")
    assert "NULLIF(SUM(volume) OVER (PARTITION BY o_year), 0)" in out
    assert "NULLIF(SUM(volume), 0) OVER" not in out
