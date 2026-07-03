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

import inspect
from datetime import date

import pytest

from benchbox.core.equivalence.cross_surface import (
    ClassifiedDivergence,
    _bump_trailing_limit,
    _final_key_tied_beyond_limit,
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


def test_cross_surface_builders_are_decomposed_and_share_loader():
    import benchbox.core.equivalence.cross_surface as cross_surface

    builder_names = {
        "build_ssb_duckdb",
        "build_amplab_duckdb",
        "build_clickbench_duckdb",
        "build_coffeeshop_duckdb",
        "build_joinorder_synthetic_duckdb",
        "build_h2odb_duckdb",
        "build_read_primitives_duckdb",
    }

    cross_surface_source = inspect.getsource(cross_surface)
    for name in builder_names:
        builder = getattr(cross_surface, name)
        assert builder.__module__.startswith("benchbox.core.equivalence.builders.")
        assert f"def {name}" not in cross_surface_source

    for name in ("build_clickbench_duckdb", "build_coffeeshop_duckdb", "build_joinorder_synthetic_duckdb"):
        builder_source = inspect.getsource(getattr(cross_surface, name))
        assert "_load_duckdb_cell(" in builder_source
        assert "DuckDBAdapter" not in builder_source


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


def test_strict_default_reports_dataframe_nan_against_sql_null():
    ref = [(None,)]
    connection, reference_sql, dataframe_query, contexts = _make_inputs(ref, {"pandas": [(float("nan"),)]})
    divergences = find_cross_surface_divergences(
        connection,
        query_ids=["Qnan"],
        reference_sql=reference_sql,
        dataframe_query=dataframe_query,
        contexts=contexts,
        validator=ResultValidator(),
        backends=("pandas",),
    )
    assert [(d.query_id, d.cell, d.key) for d in divergences] == [("Qnan", "pandas", "Qnan_pandas")]
    assert "Value mismatch" in divergences[0].detail


def test_strict_default_reports_trailing_whitespace_divergence():
    ref = [("foo",)]
    connection, reference_sql, dataframe_query, contexts = _make_inputs(ref, {"expression": [("foo ",)]})
    divergences = find_cross_surface_divergences(
        connection,
        query_ids=["Qspace"],
        reference_sql=reference_sql,
        dataframe_query=dataframe_query,
        contexts=contexts,
        validator=ResultValidator(),
        backends=("expression",),
    )
    assert [(d.query_id, d.cell, d.key) for d in divergences] == [("Qspace", "expression", "Qspace_expression")]
    assert "Value mismatch" in divergences[0].detail


def test_explicit_value_widening_flags_accept_documented_decode_cases():
    ref = [(None, "foo")]
    connection, reference_sql, dataframe_query, contexts = _make_inputs(ref, {"pandas": [(float("nan"), "foo ")]})
    divergences = find_cross_surface_divergences(
        connection,
        query_ids=["Qtolerated"],
        reference_sql=reference_sql,
        dataframe_query=dataframe_query,
        contexts=contexts,
        validator=ResultValidator(treat_nan_as_null=True, strip_strings=True),
        backends=("pandas",),
    )
    assert divergences == []


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

    # Same swap under an ORDER BY ... LIMIT query with the final key tied past the
    # cutoff: accepted as a boundary tie.
    connection, reference_sql, dataframe_query, contexts = _make_inputs(
        ref, {"expression": swapped}, sql="SELECT a, c FROM t ORDER BY c DESC LIMIT 3"
    )
    connection._rows_by_sql["SELECT a, c FROM t ORDER BY c DESC LIMIT 4"] = [(1, 5), (2, 3), (3, 3), (4, 3)]
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


# --- Boundary-tie probe: a one-visible-row final tie is not a false positive -----


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("SELECT a FROM t ORDER BY a DESC LIMIT 2", "SELECT a FROM t ORDER BY a DESC LIMIT 3"),
        ("SELECT a FROM t ORDER BY a LIMIT 10 OFFSET 5", "SELECT a FROM t ORDER BY a LIMIT 11 OFFSET 5"),
        ("select a from t order by a limit 1;", "select a from t order by a limit 2;"),
        ("SELECT a FROM t ORDER BY a LIMIT 7 -- top seven", "SELECT a FROM t ORDER BY a LIMIT 8"),
        ("SELECT a FROM t ORDER BY a", None),  # no trailing LIMIT -> not rewritable
    ],
)
def test_bump_trailing_limit_raises_the_cutoff_by_one(sql, expected):
    """The probe rewriter raises ``LIMIT n`` to ``n+1``, preserving OFFSET/terminator."""
    assert _bump_trailing_limit(sql) == expected


def test_final_key_tied_beyond_limit_true_when_key_recurs_past_cutoff():
    """The probe reports True when the row past the cutoff shares the final order key."""
    sql = "SELECT a, b FROM t ORDER BY a DESC LIMIT 2"
    # Keys 10, 5, 5 under LIMIT 2 -> visible [10, 5]; the row just past the cutoff is
    # another key-5 row, so the final key 5 ties across the LIMIT.
    connection = _FakeConnection({"SELECT a, b FROM t ORDER BY a DESC LIMIT 3": [(10, "x"), (5, "a"), (5, "b")]})
    reference = [(10, "x"), (5, "a")]
    assert _final_key_tied_beyond_limit(connection, sql, [0], reference) is True


def test_final_key_tied_beyond_limit_false_when_no_row_past_cutoff():
    """The probe reports False when the table is exhausted at the cutoff (deterministic)."""
    sql = "SELECT a, b FROM t ORDER BY a DESC LIMIT 2"
    # Only two rows total: LIMIT 3 returns the same two, nothing past the cutoff, so
    # the final row is deterministic - a difference there is a real value bug.
    connection = _FakeConnection({"SELECT a, b FROM t ORDER BY a DESC LIMIT 3": [(10, "x"), (5, "good")]})
    reference = [(10, "x"), (5, "good")]
    assert _final_key_tied_beyond_limit(connection, sql, [0], reference) is False


def test_final_key_tied_beyond_limit_false_when_next_row_is_a_distinct_key():
    """A distinct order key just past the cutoff means the final row is deterministic."""
    sql = "SELECT a, b FROM t ORDER BY a DESC LIMIT 2"
    # The row past the cutoff has key 3 (not the boundary value 5), so key 5 is NOT
    # tied across the LIMIT - the lone visible key-5 row is the true last row.
    connection = _FakeConnection({"SELECT a, b FROM t ORDER BY a DESC LIMIT 3": [(10, "x"), (5, "a"), (3, "c")]})
    reference = [(10, "x"), (5, "a")]
    assert _final_key_tied_beyond_limit(connection, sql, [0], reference) is False


def test_final_key_tied_beyond_limit_checks_multi_row_final_group():
    """A visible multi-row final tie still needs the LIMIT n+1 probe."""
    sql = "SELECT a, b FROM t ORDER BY a DESC LIMIT 3"
    connection = _FakeConnection(
        {"SELECT a, b FROM t ORDER BY a DESC LIMIT 4": [(10, "x"), (5, "a"), (5, "b"), (5, "c")]}
    )
    reference = [(10, "x"), (5, "a"), (5, "b")]
    assert _final_key_tied_beyond_limit(connection, sql, [0], reference) is True


def test_multi_row_complete_final_tie_value_bug_is_caught_via_probe():
    """End-to-end: complete multi-row final ties cannot hide value divergence."""
    sql = "SELECT a, b FROM t ORDER BY a DESC LIMIT 3"
    reference = [(10, "x"), (5, "a"), (5, "b")]
    candidate = [(10, "x"), (5, "a"), (5, "bad")]
    connection = _FakeConnection(
        {
            sql: reference,
            "SELECT a, b FROM t ORDER BY a DESC LIMIT 4": reference,
        }
    )

    def reference_sql(_qid):
        return sql

    def dataframe_query(_qid):
        return _FakeQuery({"expression": lambda ctx: _FakeFrame(candidate)})

    divergences = find_cross_surface_divergences(
        connection,
        query_ids=["Q1"],
        reference_sql=reference_sql,
        dataframe_query=dataframe_query,
        contexts={"expression": object()},
        validator=ResultValidator(),
        backends=("expression",),
    )
    assert [d.key for d in divergences] == ["Q1_expression"], "complete final tie divergence must be reported"


def test_one_visible_row_boundary_tie_is_not_a_divergence_via_probe():
    """End-to-end: a one-visible-row boundary tie is accepted once the probe confirms it.

    Reference top-2 is ``[10, 5]`` with the boundary key 5 tied past the LIMIT (a
    third key-5 row exists). The DataFrame surface keeps a DIFFERENT but equally-valid
    key-5 row, so the lone final group differs - and the gate must NOT flag it,
    because the boundary-tie probe (``LIMIT 3``) shows key 5 recurs past the cutoff.
    """
    sql = "SELECT a, b FROM t ORDER BY a DESC LIMIT 2"
    reference = [(10, "x"), (5, "a")]
    candidate = [(10, "x"), (5, "b")]  # the lone visible boundary-tie member differs
    connection = _FakeConnection(
        {
            sql: reference,
            "SELECT a, b FROM t ORDER BY a DESC LIMIT 3": [(10, "x"), (5, "a"), (5, "b")],
        }
    )

    def reference_sql(_qid):
        return sql

    def dataframe_query(_qid):
        return _FakeQuery({"expression": lambda ctx: _FakeFrame(candidate)})

    divergences = find_cross_surface_divergences(
        connection,
        query_ids=["Q1"],
        reference_sql=reference_sql,
        dataframe_query=dataframe_query,
        contexts={"expression": object()},
        validator=ResultValidator(),
        backends=("expression",),
    )
    assert divergences == [], "a probe-confirmed one-visible-row boundary tie must not be flagged"


def test_one_visible_row_final_value_bug_is_caught_when_not_tied_past_limit():
    """End-to-end: a unique-final-key value bug is still caught when the probe says deterministic.

    Same single-row final-group shape as the boundary-tie case, but the probe
    (``LIMIT 3``) finds NO row tied past the cutoff, so the final row is deterministic
    and the ``good`` -> ``bad`` change is a real divergence the gate must report.
    """
    sql = "SELECT a, b FROM t ORDER BY a DESC LIMIT 2"
    reference = [(10, "x"), (5, "good")]
    candidate = [(10, "x"), (5, "bad")]
    connection = _FakeConnection(
        {
            sql: reference,
            "SELECT a, b FROM t ORDER BY a DESC LIMIT 3": [(10, "x"), (5, "good")],
        }
    )

    def reference_sql(_qid):
        return sql

    def dataframe_query(_qid):
        return _FakeQuery({"expression": lambda ctx: _FakeFrame(candidate)})

    divergences = find_cross_surface_divergences(
        connection,
        query_ids=["Q1"],
        reference_sql=reference_sql,
        dataframe_query=dataframe_query,
        contexts={"expression": object()},
        validator=ResultValidator(),
        backends=("expression",),
    )
    assert [d.key for d in divergences] == ["Q1_expression"], "a deterministic final-row bug must still be caught"


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


def test_known_divergence_baseline_fails_when_entry_is_resolved(capsys):
    """A known-divergence entry must be removed once the live cell matches again."""
    coverage = {"expression": 1, "pandas": 1}

    exit_code = _report(
        [],
        total=2,
        coverage=coverage,
        known={"Q1_pandas": "documented test baseline"},
        benchmark="fake",
        reference_row_counts={"Q1": 5},
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "GATE FAILURE - previously-known divergences now equivalent: ['Q1_pandas']" in out
    assert "remove the stale baseline entry" in out


def test_known_divergence_baseline_allows_nondeterministic_absence(capsys):
    """A marked nondeterministic baseline may compare equal by chance."""
    coverage = {"expression": 1, "pandas": 1}

    exit_code = _report(
        [],
        total=2,
        coverage=coverage,
        known={
            "Q1_pandas": ClassifiedDivergence(
                reason="arbitrary top-N selection",
                accepts=lambda divergence: "Value mismatch" in str(divergence.detail),
                requires_live_divergence=False,
            )
        },
        benchmark="fake",
        reference_row_counts={"Q1": 5},
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "previously-known divergences now equivalent" not in out
    assert "SQL and DataFrame surfaces are equivalent (modulo classified exceptions)." in out


def test_known_divergence_baseline_accepts_live_entry(capsys):
    """A still-reproducing, baselined divergence remains accepted."""
    coverage = {"expression": 1, "pandas": 1}

    exit_code = _report(
        [SurfaceDivergence("Q1", "pandas", "accepted mismatch")],
        total=2,
        coverage=coverage,
        known={"Q1_pandas": "documented test baseline"},
        benchmark="fake",
        reference_row_counts={"Q1": 5},
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[documented test baseline]" in out
    assert "SQL and DataFrame surfaces are equivalent (modulo classified exceptions)." in out


def test_known_divergence_baseline_does_not_hide_new_unclassified_divergence(capsys):
    """An unlisted divergence is still a gate failure."""
    coverage = {"expression": 1, "pandas": 1}

    exit_code = _report(
        [SurfaceDivergence("Q2", "pandas", "new mismatch")],
        total=2,
        coverage=coverage,
        known={},
        benchmark="fake",
        reference_row_counts={"Q2": 5},
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "GATE FAILURE - unclassified cross-surface divergences: ['Q2_pandas']" in out


def test_review_by_past_due_warns_but_does_not_fail_the_gate(capsys):
    """A ClassifiedDivergence with a past-due review_by warns, never fails (w1's warn decision)."""
    coverage = {"expression": 1, "pandas": 1}

    exit_code = _report(
        [SurfaceDivergence("Q1", "pandas", "accepted mismatch")],
        total=2,
        coverage=coverage,
        known={
            "Q1_pandas": ClassifiedDivergence(
                reason="synthetic long-lived waiver",
                accepts=lambda divergence: "accepted" in str(divergence.detail),
                review_by=date(2020, 1, 1),  # far in the past
            )
        },
        benchmark="fake",
        reference_row_counts={"Q1": 5},
    )

    out = capsys.readouterr().out
    assert exit_code == 0  # a past-due review_by warns, it never fails the gate
    assert "WAIVER REVIEW DUE - Q1_pandas: review_by 2020-01-01 has passed - synthetic long-lived waiver" in out


def test_review_by_future_date_does_not_warn(capsys):
    """A ClassifiedDivergence with a future (or absent) review_by produces no warning."""
    coverage = {"expression": 1, "pandas": 1}

    exit_code = _report(
        [SurfaceDivergence("Q1", "pandas", "accepted mismatch")],
        total=2,
        coverage=coverage,
        known={
            "Q1_pandas": ClassifiedDivergence(
                reason="synthetic waiver, not due",
                accepts=lambda divergence: "accepted" in str(divergence.detail),
                review_by=date(2099, 1, 1),
            )
        },
        benchmark="fake",
        reference_row_counts={"Q1": 5},
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "WAIVER REVIEW DUE" not in out


def test_review_by_absent_by_default_produces_no_warning(capsys):
    """A bare-string baseline entry (no review_by carrier) never warns - opt-in only."""
    coverage = {"expression": 1, "pandas": 1}

    exit_code = _report(
        [SurfaceDivergence("Q1", "pandas", "accepted mismatch")],
        total=2,
        coverage=coverage,
        known={"Q1_pandas": "documented test baseline"},
        benchmark="fake",
        reference_row_counts={"Q1": 5},
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "WAIVER REVIEW DUE" not in out


def test_clickbench_and_joinorder_are_enforced_gates():
    """ClickBench and joinorder_synthetic are promoted to enforced GATES (w4).

    Once the two cross-cutting prerequisites landed - w9 (loader applies schema
    column TYPES + DuckDB empty-string semantics) and w8 (tie-aware comparator) -
    both staged gates went clean and graduated from STAGED_GATES to GATES, so the
    oracle coverage map marks them cross-surface "guarded". ClickBench's residual
    baseline entries are the genuinely order-less Q18 backends.
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


def test_read_primitives_gate_opts_into_documented_nan_null_decode_tolerance():
    """Read Primitives keeps strict defaults global while opting in for pandas NULL decode."""
    from benchbox.core.equivalence.cross_surface import GATES

    gate = GATES["read_primitives"]
    validator = gate.build_validator()

    assert gate.treat_nan_as_null is True
    assert validator.treat_nan_as_null is True
    assert validator.strip_strings is False
    assert GATES["ssb"].build_validator().treat_nan_as_null is False


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


def test_h2odb_q9_baseline_tolerates_only_the_sub_cent_residue_not_real_bugs():
    """The Q9 baseline is detail-aware: it classifies ONLY the sub-cent DECIMAL
    residue, so a genuine Q9 regression on the same key still fails the gate."""
    from benchbox.core.equivalence.cross_surface import GATES

    known = GATES["h2odb"].known_divergences
    coverage = {"expression": 1, "pandas": 1}

    # The documented residue: p90 differs by < half a cent on both backends ->
    # classified, the gate passes.
    residue = [
        SurfaceDivergence(
            "Q9", "expression", "Q9.0: Value mismatch at row 4, column 2. Original: 77.87, Variant: 77.874"
        ),
        SurfaceDivergence("Q9", "pandas", "Q9.0: Value mismatch at row 4, column 2. Original: 77.87, Variant: 77.874"),
    ]
    assert (
        _report(residue, total=2, coverage=coverage, known=known, benchmark="h2odb", reference_row_counts={"Q9": 6})
        == 0
    )

    # A real value bug on the SAME key (wrong median, off by ten) is not sub-cent,
    # so it is unclassified and the gate FAILS - the bare key no longer masks it.
    real_bug = [
        SurfaceDivergence("Q9", "pandas", "Q9.0: Value mismatch at row 0, column 1. Original: 50.0, Variant: 60.0"),
    ]
    assert (
        _report(real_bug, total=2, coverage=coverage, known=known, benchmark="h2odb", reference_row_counts={"Q9": 6})
        == 1
    )

    # A SUB-CENT bug in the WRONG column (the median, col 1, not the documented p90
    # col 2) is a real Q9 regression - the gate FAILS. The magnitude-only predicate
    # wrongly tolerated this; pinning the accepted cell to the p90 column catches it.
    wrong_column = [
        SurfaceDivergence("Q9", "pandas", "Q9.0: Value mismatch at row 4, column 1. Original: 77.87, Variant: 77.874"),
    ]
    assert (
        _report(
            wrong_column, total=2, coverage=coverage, known=known, benchmark="h2odb", reference_row_counts={"Q9": 6}
        )
        == 1
    )


def test_h2odb_q9_residue_predicate_rejects_structural_and_large_diffs():
    """The Q9 acceptance predicate accepts a sub-cent p90 value mismatch and nothing
    else.

    The documented exception is ONLY the p90 PERCENTILE_CONT DECIMAL(8,2) scale
    residue (Q9 projects col 0 = passenger_count, col 1 = median, col 2 = p90), so the
    predicate must pin the EXACT cell: the p90 column, a single sub-half-cent value at
    the SQL column's 2-decimal scale. A sub-cent mismatch in the median or the
    grouping key, a structural mismatch, an execution error, or any >=1-cent value bug
    is rejected.
    """
    from benchbox.core.equivalence.cross_surface import _h2odb_q9_decimal_residue

    def d(detail: str) -> SurfaceDivergence:
        return SurfaceDivergence("Q9", "pandas", detail)

    # ACCEPT: the documented residue - p90 column (2), Original at DECIMAL(8,2) scale,
    # Variant differs only in the 3rd decimal, sub-half-cent.
    assert _h2odb_q9_decimal_residue(d("Q9.0: Value mismatch at row 4, column 2. Original: 77.87, Variant: 77.874"))

    # REJECT: a full value bug (>= a cent), a wrong grouping (row/column-count
    # mismatch), and an execution error.
    assert not _h2odb_q9_decimal_residue(d("Q9.0: Value mismatch at row 0, column 1. Original: 50.0, Variant: 60.0"))
    assert not _h2odb_q9_decimal_residue(d("Q9.0: Row count mismatch. Original: 6, Variant: 5"))
    assert not _h2odb_q9_decimal_residue(d("Q9.0: Column count mismatch at row 0. Original: 3, Variant: 2"))
    assert not _h2odb_q9_decimal_residue(d("error: boom"))

    # REJECT: a SUB-CENT mismatch in the WRONG column. The bare-magnitude predicate
    # wrongly accepted these (only the value delta was checked); pinning to the p90
    # column (2) rejects a sub-cent median (col 1) or grouping-key (col 0) bug, which
    # are real Q9 regressions, not the documented p90 DECIMAL residue.
    assert not _h2odb_q9_decimal_residue(d("Q9.0: Value mismatch at row 4, column 1. Original: 77.87, Variant: 77.874"))
    assert not _h2odb_q9_decimal_residue(d("Q9.0: Value mismatch at row 4, column 0. Original: 4.00, Variant: 4.004"))

    # REJECT: a >=1-cent value bug in the p90 column (right column, wrong magnitude).
    assert not _h2odb_q9_decimal_residue(d("Q9.0: Value mismatch at row 4, column 2. Original: 77.87, Variant: 77.90"))

    # REJECT: a p90, sub-cent delta whose Original is NOT at DECIMAL(8,2) scale - so it
    # lacks the DuckDB DECIMAL-rounding signature (both sides carry a 3rd decimal),
    # which is not the documented presentational difference.
    assert not _h2odb_q9_decimal_residue(
        d("Q9.0: Value mismatch at row 4, column 2. Original: 77.874, Variant: 77.877")
    )

    # ACCEPT: the median (col 1) is allowed to be the documented residue too only when
    # it is p90 - it is NOT - so this stays rejected even though it is sub-cent. (Guard
    # against a future loosening: only column 2 is ever accepted.)
    assert not _h2odb_q9_decimal_residue(d("Q9.5: Value mismatch at row 5, column 1. Original: 77.91, Variant: 77.915"))


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
