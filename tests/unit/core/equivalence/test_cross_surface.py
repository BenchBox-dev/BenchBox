"""Unit tests for the cross-surface SQL<->DataFrame gate control flow.

These lock the benchmark-agnostic behavior of
:func:`benchbox.core.equivalence.cross_surface.find_cross_surface_divergences`
- backend skipping, divergence reporting, cell/key labelling, and reference
failure handling - with pure fakes and the real
:class:`~benchbox.core.tpchavoc.validation.ResultValidator`, without needing
DuckDB / Polars / Pandas (the real data path is exercised by the integration
gate).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.core.equivalence.cross_surface import (
    count_executed_cells,
    find_cross_surface_divergences,
    order_key_from_sql,
)
from benchbox.core.tpchavoc.validation import ResultValidator

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestOrderKeyFromSql:
    """Mapping a query's ORDER BY to output-column indices (w2)."""

    def test_alias_order_key(self) -> None:
        sql = "SELECT RegionID, COUNT(DISTINCT UserID) AS u FROM hits GROUP BY RegionID ORDER BY u DESC LIMIT 10"
        assert order_key_from_sql(sql) == ([1], True)

    def test_expression_order_key(self) -> None:
        sql = "SELECT UserID, COUNT(*) FROM hits GROUP BY UserID ORDER BY COUNT(*) DESC LIMIT 10"
        assert order_key_from_sql(sql) == ([1], True)

    def test_no_order_by(self) -> None:
        sql = "SELECT UserID, SearchPhrase, COUNT(*) FROM hits GROUP BY UserID, SearchPhrase LIMIT 10"
        assert order_key_from_sql(sql) == ([], True)

    def test_no_limit(self) -> None:
        sql = "SELECT M, COUNT(*) AS c FROM hits GROUP BY M ORDER BY M"
        assert order_key_from_sql(sql) == ([0], False)

    def test_select_star_resolves_with_column_names(self) -> None:
        sql = "SELECT * FROM hits WHERE URL LIKE '%g%' ORDER BY EventTime LIMIT 10"
        columns = ["WatchID", "JavaEnable", "Title", "GoodEvent", "EventTime"]
        assert order_key_from_sql(sql, columns) == ([4], True)

    def test_select_star_without_columns_is_unresolved(self) -> None:
        sql = "SELECT * FROM hits ORDER BY EventTime LIMIT 10"
        assert order_key_from_sql(sql) is None


class _FakeFrame:
    """Minimal eager-frame stand-in: materialize_rows reads ``.rows()``."""

    def __init__(self, rows):
        self._rows = rows

    def rows(self):
        return self._rows


class _FakeConnection:
    """Returns canned reference rows keyed by the SQL string passed in."""

    def __init__(self, rows_by_sql):
        self._rows_by_sql = rows_by_sql

    def execute(self, sql):
        self._result = self._rows_by_sql[sql]
        return self

    def fetchall(self):
        return self._result


class _FakeQuery:
    """Stand-in for DataFrameQuery: get_impl_for_family returns a backend impl."""

    def __init__(self, impls):
        self._impls = impls

    def get_impl_for_family(self, family):
        return self._impls.get(family)


def _make_inputs(reference_rows, impls_by_backend):
    sql = "SELECT * FROM t"
    connection = _FakeConnection({sql: reference_rows})

    def reference_sql(_qid):
        return sql

    def dataframe_query(_qid):
        return _FakeQuery({b: (lambda ctx, rows=rows: _FakeFrame(rows)) for b, rows in impls_by_backend.items()})

    contexts = {"expression": object(), "pandas": object()}
    return connection, reference_sql, dataframe_query, contexts


def test_matching_surfaces_yield_no_divergences():
    rows = [(1, 2.0), (3, 4.0)]
    connection, reference_sql, dataframe_query, contexts = _make_inputs(rows, {"expression": rows, "pandas": rows})
    divergences = find_cross_surface_divergences(
        connection,
        query_ids=["Q1.1"],
        reference_sql=reference_sql,
        dataframe_query=dataframe_query,
        contexts=contexts,
        validator=ResultValidator(),
    )
    assert divergences == []


def test_divergent_backend_is_reported_with_backend_cell():
    ref = [(1, 2.0)]
    connection, reference_sql, dataframe_query, contexts = _make_inputs(
        ref, {"expression": ref, "pandas": [(1, 999.0)]}
    )
    divergences = find_cross_surface_divergences(
        connection,
        query_ids=["Q1.1"],
        reference_sql=reference_sql,
        dataframe_query=dataframe_query,
        contexts=contexts,
        validator=ResultValidator(),
    )
    assert [(d.query_id, d.cell, d.key) for d in divergences] == [("Q1.1", "pandas", "Q1.1_pandas")]


def test_missing_backend_impl_is_skipped_not_a_divergence():
    ref = [(1, 2.0)]
    # Only the expression backend implements the query; pandas is absent.
    connection, reference_sql, dataframe_query, contexts = _make_inputs(ref, {"expression": ref})
    divergences = find_cross_surface_divergences(
        connection,
        query_ids=["Q1.1"],
        reference_sql=reference_sql,
        dataframe_query=dataframe_query,
        contexts=contexts,
        validator=ResultValidator(),
        backends=("expression", "pandas"),
    )
    assert divergences == []


def test_count_executed_cells_detects_a_fully_absent_backend():
    # expression implements both queries; pandas implements neither.
    def dataframe_query(qid):
        return _FakeQuery({"expression": lambda ctx: _FakeFrame([])})

    coverage = count_executed_cells(["Q1.1", "Q1.2"], dataframe_query, ("expression", "pandas"))
    assert coverage == {"expression": 2, "pandas": 0}
    # A 0-count gated backend is the registration regression run_gate fails on.
    assert [b for b, n in coverage.items() if n == 0] == ["pandas"]


def test_count_executed_cells_full_coverage():
    def dataframe_query(qid):
        return _FakeQuery({"expression": lambda ctx: _FakeFrame([]), "pandas": lambda ctx: _FakeFrame([])})

    coverage = count_executed_cells(["Q1.1", "Q1.2", "Q1.3"], dataframe_query, ("expression", "pandas"))
    assert coverage == {"expression": 3, "pandas": 3}


def test_reference_failure_records_one_cell_and_skips_candidates():
    def reference_sql(_qid):
        return "SELECT bad"

    class _BoomConnection:
        def execute(self, sql):
            raise RuntimeError("no such table")

    def dataframe_query(_qid):  # pragma: no cover - must not be reached
        raise AssertionError("candidates must not run without a reference")

    divergences = find_cross_surface_divergences(
        _BoomConnection(),
        query_ids=["Q1.1"],
        reference_sql=reference_sql,
        dataframe_query=dataframe_query,
        contexts={"expression": object(), "pandas": object()},
        validator=ResultValidator(),
    )
    assert len(divergences) == 1
    assert divergences[0].cell == "reference"
    assert divergences[0].key == "Q1.1_reference"
    assert "no such table" in divergences[0].detail


def test_clickbench_is_staged_not_enforced():
    """ClickBench is wired as a STAGED gate (report mode) but NOT an enforced GATES entry.

    It still has open SQL<->DataFrame divergences (see
    _project/analysis/clickbench-cross-surface-divergences.md), so it must stay out
    of GATES - the oracle coverage map reads GATES to mark a benchmark "guarded",
    and registering a red gate there would be coverage theater. `get_gate` must
    still resolve it for report-mode runs.
    """
    from benchbox.core.equivalence.cross_surface import GATES, STAGED_GATES, get_gate

    assert "clickbench" in STAGED_GATES
    assert "clickbench" not in GATES
    assert get_gate("clickbench").name == "clickbench"
    # ssb stays the enforced precedent.
    assert "ssb" in GATES
