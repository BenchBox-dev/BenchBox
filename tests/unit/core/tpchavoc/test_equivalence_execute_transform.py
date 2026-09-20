"""Fast unit coverage for sweep-level row handling in ``find_divergences``.

The fourth-engine (ClickHouse) sample runs both canonical and variant SQL through
the production query-time rewrites the real adapter applies. These tests pin that
plumbing without needing chDB: a fake connection records the exact SQL executed.
The CHAR-padding tests pin the PostgreSQL sample's trailing-whitespace tolerance:
an expression-over-``CHAR`` column comes back unpadded while the canonical
``CHAR`` column stays blank-padded, which is semantically equal under SQL
``CHAR`` comparison while the hard DuckDB gate stays byte-strict.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from benchbox.core.tpchavoc.equivalence import _clickhouse_execute_transform, find_divergences
from benchbox.core.tpchavoc.validation import ResultValidator

pytestmark = [pytest.mark.unit, pytest.mark.fast]


class _RecordingConnection:
    """Fake connection capturing every executed SQL string.

    ``fetchall_side_effect`` optionally scripts per-fetch rows by 1-based
    fetch ordinal (1 is the canonical fetch, 2+ are the variant fetches);
    ordinals without an entry fall back to ``[(1,)]``.
    """

    def __init__(self, fetchall_side_effect: dict[int, list[tuple]] | None = None):
        self.executed: list[str] = []
        self._fetchall_side_effect = fetchall_side_effect or {}
        self._fetches = 0

    def execute(self, sql: str):
        self.executed.append(sql)
        self._fetches += 1
        result = MagicMock()
        result.fetchall.return_value = self._fetchall_side_effect.get(self._fetches, [(1,)])
        return result


def _benchmark_with_one_query():
    benchmark = MagicMock()
    benchmark.get_implemented_queries.return_value = [1]
    benchmark.get_query.return_value = "SELECT v FROM t"
    benchmark.validate_variant_equivalence.return_value = None  # never diverges
    return benchmark


def _benchmark_validating_strictly():
    """One-query benchmark wired to the real strict validator, like production."""
    validator = ResultValidator()
    benchmark = MagicMock()
    benchmark.get_implemented_queries.return_value = [1]
    benchmark.get_query.return_value = "SELECT v FROM t"
    benchmark.validate_variant_equivalence.side_effect = lambda qid, vid, original, variant: (
        validator.validate_results_exact(original, variant, qid, vid)
    )
    return benchmark


def _padding_connection(canonical_rows: list[tuple], variant_rows: list[tuple]) -> _RecordingConnection:
    """Script canonical rows, then one variant under test (v1); v2..v10 match."""
    scripted = {1: canonical_rows, 2: variant_rows}
    scripted.update(dict.fromkeys(range(3, 12), canonical_rows))
    return _RecordingConnection(scripted)


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


@pytest.mark.parametrize(
    ("canonical", "variant", "padding_columns", "expected_keys"),
    [
        # Padded canonical vs stripped variant diverges under the strict default.
        ([("1-URGENT       ", 1)], [("1-URGENT", 1)], None, ["1_v1"]),
        # Opt-in tolerance accepts blank-padding but nothing else.
        ([("1-URGENT       ", 1)], [("1-URGENT", 1)], {1: (0,)}, []),
        # Leading whitespace is never padding: still diverges when opted in.
        ([("  1-URGENT", 1)], [("1-URGENT", 1)], {1: (0,)}, ["1_v1"]),
        # A genuinely different value still diverges when opted in.
        ([("1-URGENT       ", 1)], [("2-HIGH", 1)], {1: (0,)}, ["1_v1"]),
        # VARCHAR/TEXT remains strict beside a declared CHAR column.
        ([("1-URGENT       ", "comment ")], [("1-URGENT", "comment")], {1: (0,)}, ["1_v1"]),
        # Tabs and newlines are data, not SQL CHAR blank-padding.
        ([("1-URGENT\t", 1)], [("1-URGENT", 1)], {1: (0,)}, ["1_v1"]),
    ],
)
def test_char_padding_tolerance(canonical, variant, padding_columns, expected_keys):
    """Only declared CHAR columns accept ASCII blank-padding."""
    conn = _padding_connection(canonical, variant)
    divergences = find_divergences(
        conn, _benchmark_validating_strictly(), lambda q: "SELECT 1", char_padding_columns=padding_columns
    )
    assert [d.key for d in divergences] == expected_keys
