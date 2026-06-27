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
    _report,
    count_executed_cells,
    find_cross_surface_divergences,
)
from benchbox.core.equivalence.dataframe_surface import SurfaceDivergence
from benchbox.core.tpchavoc.validation import ResultValidator

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


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


def _make_inputs(reference_rows, impls_by_backend, sql="SELECT * FROM t"):
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


def test_tie_aware_only_applies_to_truncated_top_n_queries():
    """A boundary-tie swap is tolerated for a LIMIT query but NOT a non-LIMIT one.

    The tie-aware relaxation is only sound where a LIMIT can truncate a tie across
    the cutoff; for a full (non-LIMIT) result set a changed duplicated-last-row is
    a real divergence and must still be reported (it is not an ambiguous swap).
    """
    # Reference ordered by the last column DESC; boundary value 3 is duplicated.
    ref = [(1, 5), (2, 3), (3, 3)]
    swapped = [(1, 5), (2, 3), (99, 3)]  # a different row at the boundary tie value

    # Non-LIMIT query: strict comparison -> the swap is reported.
    connection, reference_sql, dataframe_query, contexts = _make_inputs(
        ref, {"expression": swapped}, sql="SELECT a, c FROM t ORDER BY c DESC"
    )
    strict = find_cross_surface_divergences(
        connection,
        query_ids=["Q1"],
        reference_sql=reference_sql,
        dataframe_query=dataframe_query,
        contexts=contexts,
        validator=ResultValidator(),
        backends=("expression",),
    )
    assert [d.key for d in strict] == ["Q1_expression"], "non-LIMIT swap must be reported, not masked"

    # Same swap under an ORDER BY ... LIMIT query: accepted as a boundary tie.
    connection, reference_sql, dataframe_query, contexts = _make_inputs(
        ref, {"expression": swapped}, sql="SELECT a, c FROM t ORDER BY c DESC LIMIT 3"
    )
    relaxed = find_cross_surface_divergences(
        connection,
        query_ids=["Q1"],
        reference_sql=reference_sql,
        dataframe_query=dataframe_query,
        contexts=contexts,
        validator=ResultValidator(),
        backends=("expression",),
    )
    assert relaxed == [], "boundary-tie swap under a LIMIT query should be tolerated"


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


def test_reference_row_counts_are_populated_when_requested():
    """The opt-in row-count map records the per-query reference row count.

    The vacuity guard (BS3) needs to know which queries returned 0 rows; the
    count map is how :func:`run_gate` learns that without the comparator side
    needing to know about vacuity.
    """
    rows = [(1, 2.0), (3, 4.0)]
    connection, reference_sql, dataframe_query, contexts = _make_inputs(rows, {"expression": rows, "pandas": rows})
    counts: dict = {}
    find_cross_surface_divergences(
        connection,
        query_ids=["Q1.1"],
        reference_sql=reference_sql,
        dataframe_query=dataframe_query,
        contexts=contexts,
        validator=ResultValidator(),
        reference_row_counts=counts,
    )
    assert counts == {"Q1.1": 2}


def test_report_fails_on_unclassified_vacuous_query():
    """An empty-vs-empty query (0 reference rows) with no classification FAILS.

    This is the core BS3 guard: a query whose reference returns 0 rows compares
    empty-vs-empty and trivially "matches", so the gate must NOT report it as a
    pass. With no divergences and full backend coverage the gate would otherwise
    be green; the vacuity guard turns it red.
    """
    coverage = {"expression": 1, "pandas": 1}
    exit_code = _report(
        [],  # no divergences: empty-vs-empty trivially "matches"
        total=2,
        coverage=coverage,
        known={},
        benchmark="fake",
        reference_row_counts={"Q1": 0},
        legitimately_empty={},
    )
    assert exit_code == 1, "an unclassified vacuous (0-row) query must FAIL the gate"


def test_report_passes_when_vacuous_query_is_classified():
    """A vacuous query explicitly classified ``legitimately_empty`` is tolerated."""
    coverage = {"expression": 1, "pandas": 1}
    exit_code = _report(
        [],
        total=2,
        coverage=coverage,
        known={},
        benchmark="fake",
        reference_row_counts={"Q1": 0},
        legitimately_empty={"Q1": "genuinely empty at the bounded cell - rationale"},
    )
    assert exit_code == 0, "a classified legitimately-empty query must pass"


def test_report_excludes_vacuous_cells_from_discriminating_count(capsys):
    """The 'compared N of M' line counts discriminating cells only, not vacuous ones."""
    coverage = {"expression": 2, "pandas": 2}
    _report(
        [],
        total=4,
        coverage=coverage,
        known={},
        benchmark="fake",
        reference_row_counts={"Q1": 5, "Q2": 0},  # Q2 vacuous on both backends
        legitimately_empty={"Q2": "classified"},
    )
    out = capsys.readouterr().out
    # 4 executed - 2 vacuous (Q2 x 2 backends) = 2 discriminating.
    assert "compared 2 of 4 query-backend cells" in out
    assert "2 vacuous empty-vs-empty" in out


def test_report_with_real_divergence_still_fails_for_nonempty_query():
    """A genuine mismatch on a NON-empty query still fails - the guard is additive."""
    coverage = {"expression": 1, "pandas": 1}
    exit_code = _report(
        [SurfaceDivergence("Q1", "pandas", "value mismatch")],
        total=2,
        coverage=coverage,
        known={},
        benchmark="fake",
        reference_row_counts={"Q1": 5},
        legitimately_empty={},
    )
    assert exit_code == 1


def test_clickbench_and_joinorder_are_enforced_gates():
    """ClickBench and joinorder_synthetic are promoted to enforced GATES (w4).

    Once the two cross-cutting prerequisites landed - w9 (loader applies schema
    column TYPES + DuckDB empty-string semantics) and w8 (tie-aware comparator) -
    both staged gates went clean and graduated from STAGED_GATES to GATES, so the
    oracle coverage map marks them cross-surface "guarded". ClickBench's only
    baseline entry is the genuinely order-less Q18.
    """
    from benchbox.core.equivalence.cross_surface import GATES, STAGED_GATES, get_gate

    assert "clickbench" in GATES
    assert "joinorder_synthetic" in GATES
    assert "clickbench" not in STAGED_GATES
    assert get_gate("clickbench").name == "clickbench"
    assert set(GATES["clickbench"].known_divergences) == {"Q18_expression", "Q18_pandas"}
    # joinorder_synthetic is clean (empty baseline).
    assert GATES["joinorder_synthetic"].known_divergences == {}
    # ssb stays the enforced precedent.
    assert "ssb" in GATES


def test_h2odb_is_an_enforced_gate_with_classified_percentile_exception():
    """H2O-DB is an enforced GATE; its only baseline entry is Q9's DECIMAL percentile.

    DuckDB's PERCENTILE_CONT over the DECIMAL(8,2) fare_amount column returns a
    value at the column's 2-decimal scale, while the DataFrame computes the same
    linear-interpolated percentile over float64 - a deterministic sub-cent
    presentational difference classified (not masked) for both backends. Every
    other H2O-DB cell must match, so no other key is in the baseline.
    """
    from benchbox.core.equivalence.cross_surface import GATES, STAGED_GATES, get_gate

    assert "h2odb" in GATES
    assert "h2odb" not in STAGED_GATES
    assert get_gate("h2odb").name == "h2odb"
    assert set(GATES["h2odb"].known_divergences) == {"Q9_expression", "Q9_pandas"}
    # Runs on a smaller-than-default bounded cell (its generator base is 10M rows).
    assert GATES["h2odb"].scale_factor == 0.01


def test_order_by_result_key_maps_alias_name_expr_and_ordinal():
    """_order_by_result_key resolves the ORDER BY shapes the gated queries use."""
    from benchbox.core.equivalence.cross_surface import _order_by_result_key as resolve

    # plain output column names
    assert resolve("SELECT a, b FROM t ORDER BY a, b") == [0, 1]
    # an alias (ORDER BY revenue -> SUM(...) AS revenue at position 0)
    assert resolve("SELECT sum(x) AS revenue, y FROM t GROUP BY y ORDER BY revenue DESC") == [0]
    # a qualified column resolves by its bare name to the output position
    assert resolve("SELECT ol.d, dl.r FROM o ol JOIN d dl ON 1=1 ORDER BY ol.d, dl.r") == [0, 1]
    # an aggregate EXPRESSION (COUNT(*)) - a nested star must NOT disqualify it
    assert resolve("SELECT k, COUNT(*) AS c FROM t GROUP BY k ORDER BY COUNT(*) DESC") == [1]
    # a 1-based ordinal maps to the result column index
    assert resolve("SELECT a, b FROM t ORDER BY 2 DESC") == [1]


def test_order_by_result_key_refuses_unmappable_keys():
    """An ORDER BY whose key is not a projected column yields None (no order claim).

    These fall back to the order-insensitive comparison rather than a silent
    order-blind "pass" - the documented residual blind spot.
    """
    from benchbox.core.equivalence.cross_surface import _order_by_result_key as resolve

    assert resolve("SELECT a FROM t") is None  # no ORDER BY
    assert resolve("SELECT * FROM t ORDER BY x") is None  # SELECT * - unenumerable
    assert resolve("SELECT t.* FROM t ORDER BY x") is None  # qualified star
    assert resolve("SELECT a FROM t ORDER BY b") is None  # ORDER BY a non-projected column
    assert resolve("SELECT a, b FROM t ORDER BY 5") is None  # out-of-range ordinal
    assert resolve("this is not sql ;;;") is None  # unparseable


class TestBoundaryTiedPastLimitProbe:
    """The LIMIT N+1 probe that gives the comparator a precise boundary signal."""

    def _conn(self):
        duckdb = pytest.importorskip("duckdb")
        pytest.importorskip("sqlglot")
        c = duckdb.connect(":memory:")
        c.execute("CREATE TABLE t(k VARCHAR, v INTEGER)")
        c.execute("INSERT INTO t VALUES ('a',10),('b',5),('c',5),('d',5)")
        return c

    def test_tied_past_cutoff_is_true(self):
        from benchbox.core.equivalence.cross_surface import _boundary_tied_past_limit, _order_by_result_key

        c = self._conn()
        try:
            sql = "SELECT k, v FROM t ORDER BY v DESC LIMIT 2"  # keeps [10,5]; v=5 has 3 rows
            assert _boundary_tied_past_limit(c, sql, _order_by_result_key(sql)) is True
        finally:
            c.close()

    def test_complete_final_group_is_false(self):
        from benchbox.core.equivalence.cross_surface import _boundary_tied_past_limit, _order_by_result_key

        c = self._conn()
        try:
            sql = "SELECT k, v FROM t ORDER BY v DESC LIMIT 1"  # top v=10 is unique
            assert _boundary_tied_past_limit(c, sql, _order_by_result_key(sql)) is False
        finally:
            c.close()

    def test_untruncated_is_false(self):
        from benchbox.core.equivalence.cross_surface import _boundary_tied_past_limit, _order_by_result_key

        c = self._conn()
        try:
            sql = "SELECT k, v FROM t ORDER BY v DESC LIMIT 10"  # only 4 rows exist
            assert _boundary_tied_past_limit(c, sql, _order_by_result_key(sql)) is False
        finally:
            c.close()

    def test_no_order_key_or_no_limit_is_none(self):
        from benchbox.core.equivalence.cross_surface import _boundary_tied_past_limit

        c = self._conn()
        try:
            assert _boundary_tied_past_limit(c, "SELECT k, v FROM t ORDER BY v DESC LIMIT 2", None) is None
            assert _boundary_tied_past_limit(c, "SELECT k, v FROM t ORDER BY v DESC", [1]) is None
        finally:
            c.close()
