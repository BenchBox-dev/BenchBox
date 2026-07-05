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
    CrossSurfaceGate,
    _apply_baseline_update,
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


def _make_gate(name: str, known_divergences: dict) -> CrossSurfaceGate:
    return CrossSurfaceGate(name=name, build=lambda scale, tmp: None, known_divergences=known_divergences)


def test_update_baseline_prunes_resolved_entry_when_nothing_else_is_wrong(monkeypatch, capsys):
    """--update-baseline: a resolved entry with no other failure prunes and exits 0."""
    gate = _make_gate("fake", {"Q1_pandas": "documented test baseline"})
    calls = []
    monkeypatch.setattr(
        "benchbox.core.equivalence.known_divergences_baseline.update_baseline_file",
        lambda path, resolved, gate_name: calls.append((sorted(resolved), gate_name)) or list(resolved),
    )

    exit_code = _apply_baseline_update(
        gate,
        divergences=[],  # Q1_pandas no longer reproduces -> resolved.
        total=2,
        coverage={"expression": 1, "pandas": 1},
        reference_row_counts={"Q1": 5},
        vacuous_cells=0,
    )

    assert exit_code == 0
    assert calls == [(["Q1_pandas"], "fake")]
    assert "removed resolved known-divergence baseline entries" in capsys.readouterr().out


def test_update_baseline_refuses_to_write_on_an_unrelated_regression(monkeypatch, capsys):
    """A resolved entry must NOT be pruned when an UNRELATED new unclassified
    divergence rides along on the same run (e.g. one backend resolves while
    another regresses outside its accepted residue) -- nothing is written until
    the run is fully clean."""
    gate = _make_gate("fake", {"Q1_pandas": "documented test baseline"})
    calls = []
    monkeypatch.setattr(
        "benchbox.core.equivalence.known_divergences_baseline.update_baseline_file",
        lambda path, resolved, gate_name: calls.append((sorted(resolved), gate_name)) or list(resolved),
    )

    exit_code = _apply_baseline_update(
        gate,
        # Q1_pandas no longer reproduces (resolved) but Q2_pandas is a brand-new,
        # unrelated, unclassified divergence.
        divergences=[SurfaceDivergence("Q2", "pandas", "new mismatch")],
        total=4,
        coverage={"expression": 2, "pandas": 2},
        reference_row_counts={"Q1": 5, "Q2": 5},
        vacuous_cells=0,
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "GATE FAILURE - unclassified cross-surface divergences: ['Q2_pandas']" in out
    assert "refusing to update baseline" in out
    # Nothing was pruned even though Q1_pandas resolved on its own merits -- the
    # writer must never be called while the run has any other failure.
    assert calls == []


def test_update_baseline_with_nothing_resolved_still_enforces_other_failures(monkeypatch, capsys):
    """No resolved entries at all: --update-baseline must still fail on a genuine
    unclassified divergence rather than silently printing "unchanged" and exiting 0."""
    gate = _make_gate("fake", {})
    monkeypatch.setattr(
        "benchbox.core.equivalence.known_divergences_baseline.update_baseline_file",
        lambda path, resolved, gate_name: pytest.fail("update_baseline_file must not be called"),
    )

    exit_code = _apply_baseline_update(
        gate,
        divergences=[SurfaceDivergence("Q2", "pandas", "new mismatch")],
        total=2,
        coverage={"expression": 1, "pandas": 1},
        reference_row_counts={"Q2": 5},
        vacuous_cells=0,
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "GATE FAILURE - unclassified cross-surface divergences: ['Q2_pandas']" in out
    assert "refusing to update baseline" in out


def test_update_baseline_with_nothing_resolved_and_run_clean_is_a_noop(monkeypatch, capsys):
    """A clean run with no resolved entries prints "unchanged" and exits 0,
    without ever touching the writer."""
    gate = _make_gate("fake", {})
    monkeypatch.setattr(
        "benchbox.core.equivalence.known_divergences_baseline.update_baseline_file",
        lambda path, resolved, gate_name: pytest.fail("update_baseline_file must not be called"),
    )

    exit_code = _apply_baseline_update(
        gate,
        divergences=[],
        total=2,
        coverage={"expression": 1, "pandas": 1},
        reference_row_counts={"Q1": 5},
        vacuous_cells=0,
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "no resolved known-divergence entries; baseline unchanged." in out


def test_update_baseline_code_only_entry_cannot_be_pruned_and_fails(monkeypatch, capsys):
    """A resolved key backed by a ClassifiedDivergence (never in the YAML file)
    cannot be pruned by the writer -- and must NOT report success, since the
    stale predicate is still in cross_surface.py and the next normal run of
    this gate would correctly fail on it as a stale-baseline entry."""
    gate = _make_gate(
        "fake",
        {
            "Q9_expression": ClassifiedDivergence(
                reason="code-only entry", accepts=lambda d: False, requires_live_divergence=True
            )
        },
    )
    monkeypatch.setattr(
        "benchbox.core.equivalence.known_divergences_baseline.update_baseline_file",
        lambda path, resolved, gate_name: [],  # not present in the YAML file
    )

    exit_code = _apply_baseline_update(
        gate,
        divergences=[],  # Q9_expression no longer reproduces -> resolved.
        total=2,
        coverage={"expression": 1, "pandas": 1},
        reference_row_counts={"Q1": 5},
        vacuous_cells=0,
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "['Q9_expression'] are code-only (ClassifiedDivergence) and cannot be auto-pruned" in out
    assert "remove them manually from cross_surface.py in a reviewed change" in out


def test_update_baseline_prunes_yaml_entries_and_still_fails_on_remaining_code_only_entry(monkeypatch, capsys):
    """When a gate has BOTH a prunable YAML entry and an unprunable code-only
    entry resolved on the same run, the writer still prunes the YAML entry (no
    reason to withhold a safe, successful prune), but the command's own exit
    code reflects the code-only entry that could NOT be handled."""
    gate = _make_gate(
        "fake",
        {
            "Q1_pandas": "documented test baseline",
            "Q9_expression": ClassifiedDivergence(
                reason="code-only entry", accepts=lambda d: False, requires_live_divergence=True
            ),
        },
    )
    monkeypatch.setattr(
        "benchbox.core.equivalence.known_divergences_baseline.update_baseline_file",
        # Only the YAML-backed key is ever actually removable.
        lambda path, resolved, gate_name: sorted(set(resolved) & {"Q1_pandas"}),
    )

    exit_code = _apply_baseline_update(
        gate,
        divergences=[],  # both Q1_pandas and Q9_expression no longer reproduce.
        total=4,
        coverage={"expression": 2, "pandas": 2},
        reference_row_counts={"Q1": 5, "Q9": 5},
        vacuous_cells=0,
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "removed resolved known-divergence baseline entries: ['Q1_pandas']" in out
    assert "['Q9_expression'] are code-only (ClassifiedDivergence) and cannot be auto-pruned" in out


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


def test_read_primitives_known_divergences_are_all_classified():
    """All 17 read_primitives waivers are ClassifiedDivergence, none a bare string.

    Converts the previously bare-``str`` ``known_divergences`` (which tolerated
    ANY divergence on the key) so a genuine regression on the same cell is still
    reported as unclassified - see the module's read_primitives section.
    """
    from benchbox.core.equivalence.cross_surface import GATES

    known = GATES["read_primitives"].known_divergences
    assert len(known) == 17
    assert all(isinstance(entry, ClassifiedDivergence) for entry in known.values())
    assert set(known) == {
        "approx_count_distinct_simple_expression",
        "approx_count_distinct_simple_pandas",
        "approx_count_distinct_groupby_expression",
        "approx_count_distinct_groupby_pandas",
        "approx_quantile_groupby_expression",
        "approx_quantile_groupby_pandas",
        "statistical_percentiles_expression",
        "statistical_percentiles_pandas",
        "optimizer_common_subexpression_expression",
        "optimizer_common_subexpression_pandas",
        "min_by_complex_expression",
        "min_by_complex_pandas",
        "json_aggregates_expression",
        "json_aggregates_pandas",
        "map_access_expression",
        "map_construction_expression",
        "map_keys_values_expression",
    }


def test_read_primitives_sketch_residue_predicate_accepts_bounded_rejects_wide():
    """The HLL/T-Digest sketch predicate accepts <=15% relative error in its
    documented column and rejects a wider gap, the wrong column, or a structural
    mismatch - so a broken sketch merge (e.g. off by 10x) is unclassified."""
    from benchbox.core.equivalence.cross_surface import _read_primitives_sketch_residue

    def d(query: str, col: int, orig: str, variant: str) -> SurfaceDivergence:
        return SurfaceDivergence(
            f"Q{query}",
            "expression",
            f"Q{query}.0: Value mismatch at row 0, column {col}. Original: {orig}, Variant: {variant}",
        )

    # ACCEPT: the documented in-bounds residues, one per sketch key.
    assert _read_primitives_sketch_residue(d("approx_count_distinct_simple", 0, "5210", "4969"))  # 4.6%
    assert _read_primitives_sketch_residue(d("approx_count_distinct_groupby", 2, "36069", "32458"))  # 10.0%
    assert _read_primitives_sketch_residue(d("approx_count_distinct_groupby", 3, "36069", "32458"))  # unique_parts col
    assert _read_primitives_sketch_residue(d("approx_quantile_groupby", 1, "26", "25.0"))  # 3.8%

    # ACCEPT: right at the 15% bound.
    assert _read_primitives_sketch_residue(d("approx_count_distinct_simple", 0, "1000", "850.001"))

    # REJECT: an out-of-bounds sketch value - a broken sketch merge off by 10x.
    assert not _read_primitives_sketch_residue(d("approx_count_distinct_simple", 0, "5210", "521"))
    assert not _read_primitives_sketch_residue(d("approx_count_distinct_groupby", 2, "36069", "3600"))
    # REJECT: just past the 15% bound.
    assert not _read_primitives_sketch_residue(d("approx_count_distinct_simple", 0, "1000", "849"))

    # REJECT: the grouping-key columns (l_returnflag/l_linestatus/l_shipmode), even
    # with a numerically tiny difference - a wrong group is a real regression.
    assert not _read_primitives_sketch_residue(d("approx_count_distinct_groupby", 0, "R", "N"))
    assert not _read_primitives_sketch_residue(d("approx_quantile_groupby", 0, "MAIL", "AIR"))

    # REJECT: a query id not in the sketch map, a structural mismatch, and an error.
    assert not _read_primitives_sketch_residue(
        SurfaceDivergence("Qother", "expression", "Qother.0: Row count mismatch. Original: 6, Variant: 5")
    )
    assert not _read_primitives_sketch_residue(
        SurfaceDivergence("Qapprox_quantile_groupby", "expression", "error: boom")
    )


def test_read_primitives_percentile_decimal_residue_predicate():
    """statistical_percentiles' p95 (column 6) DECIMAL(15,2) residue is pinned like
    h2odb Q9: only a sub-half-cent gap at the documented column and scale is accepted."""
    from benchbox.core.equivalence.cross_surface import _read_primitives_percentile_decimal_residue as predicate

    def d(col: int, orig: str, variant: str) -> SurfaceDivergence:
        return SurfaceDivergence(
            "Qstatistical_percentiles",
            "expression",
            f"Qstatistical_percentiles.0: Value mismatch at row 1, column {col}. Original: {orig}, Variant: {variant}",
        )

    # ACCEPT: the documented residue (measured: 74356.28 vs 74356.28399999996).
    assert predicate(d(6, "74356.28", "74356.28399999996"))

    # REJECT: a full-cent-or-more value bug in the p95 column.
    assert not predicate(d(6, "74356.28", "74357.30"))
    # REJECT: a sub-cent mismatch in the WRONG column (e.g. quantity_median, col 4).
    assert not predicate(d(4, "25.00", "25.004"))
    # REJECT: Original not at <=2-decimal scale (no DECIMAL-rounding signature).
    assert not predicate(d(6, "74356.284", "74356.288"))
    # REJECT: structural mismatches and execution errors.
    assert not predicate(
        SurfaceDivergence(
            "Qstatistical_percentiles",
            "expression",
            "Qstatistical_percentiles.0: Row count mismatch. Original: 6, Variant: 5",
        )
    )
    assert not predicate(SurfaceDivergence("Qstatistical_percentiles", "expression", "error: boom"))


def test_read_primitives_round_decimal_residue_predicate():
    """optimizer_common_subexpression's rounded_revenue (column 6) ROUND()
    half-cent-boundary flip is pinned to a full-cent bound, wider than the
    percentile class because DuckDB ROUND() vs float rounding can flip by 0.01."""
    from benchbox.core.equivalence.cross_surface import _read_primitives_round_decimal_residue as predicate

    def d(col: int, orig: str, variant: str) -> SurfaceDivergence:
        return SurfaceDivergence(
            "Qoptimizer_common_subexpression",
            "expression",
            f"Qoptimizer_common_subexpression.0: Value mismatch at row 0, column {col}. Original: {orig}, Variant: {variant}",
        )

    # ACCEPT: the documented residue (measured: 4721058.05 vs 4721058.04, exactly 0.01).
    assert predicate(d(6, "4721058.05", "4721058.04"))

    # REJECT: more than a full cent off - a genuine value bug, not a rounding flip.
    assert not predicate(d(6, "4721058.05", "4721057.90"))
    # REJECT: the wrong column (e.g. l_orderkey/l_partkey join-key columns).
    assert not predicate(d(0, "100", "99"))
    # REJECT: Original not at <=2-decimal scale.
    assert not predicate(d(6, "4721058.051", "4721058.041"))
    # REJECT: structural mismatches and execution errors.
    assert not predicate(
        SurfaceDivergence(
            "Qoptimizer_common_subexpression",
            "expression",
            "Qoptimizer_common_subexpression.0: Column count mismatch at row 0. Original: 7, Variant: 6",
        )
    )
    assert not predicate(SurfaceDivergence("Qoptimizer_common_subexpression", "expression", "error: boom"))


def test_read_primitives_argmin_tie_predicate():
    """min_by_complex's ARG_MIN tie-break predicate accepts only the tie-broken
    name/type columns (1, 2), never the p_brand grouping key (0) or min_price (3)."""
    from benchbox.core.equivalence.cross_surface import _read_primitives_argmin_tie as predicate

    def d(col: int, orig: str, variant: str) -> SurfaceDivergence:
        return SurfaceDivergence(
            "Qmin_by_complex",
            "expression",
            f"Qmin_by_complex.0: Value mismatch at row 0, column {col}. Original: {orig}, Variant: {variant}",
        )

    # ACCEPT: the documented tie-break columns.
    assert predicate(d(1, "seashell orange firebrick peach rose", "gainsboro snow indian frosted navy"))
    assert predicate(d(2, "SMALL BRUSHED STEEL", "LARGE POLISHED TIN"))

    # REJECT: the grouping key (p_brand, col 0) - a wrong group is a real bug.
    assert not predicate(d(0, "Brand#11", "Brand#25"))
    # REJECT: min_price itself (col 3) - the metric must match exactly.
    assert not predicate(d(3, "901.00", "850.00"))
    # REJECT: structural mismatches and execution errors.
    assert not predicate(
        SurfaceDivergence(
            "Qmin_by_complex", "expression", "Qmin_by_complex.0: Row count mismatch. Original: 25, Variant: 24"
        )
    )
    assert not predicate(SurfaceDivergence("Qmin_by_complex", "expression", "error: boom"))


def test_read_primitives_json_agg_predicate_accepts_structural_match_only():
    """json_aggregates' predicate accepts only a genuine reordering (expression,
    within the fixed p_brand domain) or a structurally-equivalent JSON payload
    (pandas), never a missing/added/wrong element or an out-of-domain key."""
    from benchbox.core.equivalence.cross_surface import _read_primitives_json_agg_accepts as predicate

    def order_mismatch(orig_key: str, variant_key: str) -> SurfaceDivergence:
        return SurfaceDivergence(
            "Qjson_aggregates",
            "expression",
            "Qjson_aggregates.0: ORDER BY key mismatch at position 0. "
            f"Original key: ('{orig_key}',), Variant key: ('{variant_key}',) "
            "(order-key columns [0]) - the returned order differs (e.g. a reversed ORDER BY).",
        )

    def value_mismatch(col: int, orig: str, variant: str) -> SurfaceDivergence:
        return SurfaceDivergence(
            "Qjson_aggregates",
            "pandas",
            f"Qjson_aggregates.0: Value mismatch at row 0, column {col}. Original: {orig}, Variant: {variant}",
        )

    # ACCEPT: a reorder within the fixed 25-value p_brand domain (Polars' expression
    # aggregate does not sort its groups; the underlying set is unchanged).
    assert predicate(order_mismatch("Brand#11", "Brand#51"))

    # REJECT: a reported key outside the known p_brand domain - a genuinely wrong
    # grouping key, not a reorder of the same set.
    assert not predicate(order_mismatch("Brand#11", "NotABrand"))
    assert not predicate(order_mismatch("NotABrand", "Brand#11"))

    # ACCEPT: the JSON array (col 1) holds the same elements, order-insensitive.
    assert predicate(value_mismatch(1, '["a","b","c"]', "['a', 'b', 'c']"))
    assert predicate(value_mismatch(1, '["a","b","c"]', "['c', 'b', 'a']"))  # reordered, same multiset

    # ACCEPT: the JSON object (col 2) holds the same mapping, number-format-insensitive.
    assert predicate(value_mismatch(2, '{"1": 901.00, "2": 902.50}', "{'1': 901.0, '2': 902.5}"))

    # REJECT: a genuinely missing element - not merely reordered/reformatted.
    assert not predicate(value_mismatch(1, '["a","b","c"]', "['a', 'b']"))
    # REJECT: a genuinely wrong value.
    assert not predicate(value_mismatch(1, '["a","b","c"]', "['a', 'b', 'ZZZ']"))
    assert not predicate(value_mismatch(2, '{"1": 901.00}', "{'1': 850.0}"))
    # REJECT: the wrong column (e.g. p_brand or part_count, cols 0/3).
    assert not predicate(value_mismatch(0, "Brand#11", "Brand#12"))
    assert not predicate(value_mismatch(3, "5", "4"))
    # REJECT: unparsable payloads and execution errors.
    assert not predicate(value_mismatch(1, "not json", "also not json"))
    assert not predicate(SurfaceDivergence("Qjson_aggregates", "expression", "error: boom"))


def test_read_primitives_polars_map_gap_predicate():
    """The Polars Map-dtype gap predicate accepts ONLY the documented
    'no native Map dtype' execution error, never a different error or a value
    mismatch (which would mean Polars started supporting Map but got it wrong)."""
    from benchbox.core.equivalence.cross_surface import _read_primitives_polars_map_gap as predicate

    # ACCEPT: both documented raise-site messages share the same dtype-gap signature.
    assert predicate(
        SurfaceDivergence(
            "Qmap_access", "expression", "error: map_from_entries not supported on Polars (no native Map dtype)"
        )
    )
    assert predicate(
        SurfaceDivergence(
            "Qmap_keys_values", "expression", "error: Map operations not supported on Polars (no native Map dtype)"
        )
    )

    # REJECT: a different execution error - not the documented dtype gap.
    assert not predicate(SurfaceDivergence("Qmap_access", "expression", "error: unexpected KeyError: 'foo'"))
    # REJECT: a value mismatch - Polars would have to actually execute and diverge,
    # which contradicts "no expression-surface result to compare".
    assert not predicate(
        SurfaceDivergence(
            "Qmap_access", "expression", "Qmap_access.0: Value mismatch at row 0, column 1. Original: 1.0, Variant: 2.0"
        )
    )


def _read_primitives_live_baseline_divergences() -> list[SurfaceDivergence]:
    """One in-bounds :class:`SurfaceDivergence` per read_primitives known key.

    Detail strings are the ACTUAL divergences observed from a real
    ``make read-primitives-cross-surface-equivalence-report`` run (see the
    TODO's before/after gate captures), so this fixture doubles as a
    regression pin on the documented residues themselves, not just the
    predicates' logic in isolation.
    """
    sketch_detail = {
        "approx_count_distinct_simple": (0, "5210", "4969"),
        "approx_count_distinct_groupby": (2, "36069", "32458"),
        "approx_quantile_groupby": (1, "26", "25.0"),
    }
    divergences = []
    for base, (col, orig, variant) in sketch_detail.items():
        for cell in ("expression", "pandas"):
            divergences.append(
                SurfaceDivergence(
                    base,
                    cell,
                    f"Q{base}.0: Value mismatch at row 0, column {col}. Original: {orig}, Variant: {variant}",
                )
            )
    for cell in ("expression", "pandas"):
        divergences.append(
            SurfaceDivergence(
                "statistical_percentiles",
                cell,
                "Qstatistical_percentiles.0: Value mismatch at row 1, column 6. "
                "Original: 74356.28, Variant: 74356.28399999996",
            )
        )
        divergences.append(
            SurfaceDivergence(
                "optimizer_common_subexpression",
                cell,
                "Qoptimizer_common_subexpression.0: Value mismatch at row 0, column 6. "
                "Original: 4721058.05, Variant: 4721058.04",
            )
        )
        divergences.append(
            SurfaceDivergence(
                "min_by_complex",
                cell,
                "Qmin_by_complex.0: Value mismatch at row 0, column 1. "
                "Original: seashell orange firebrick peach rose, Variant: gainsboro snow indian frosted navy",
            )
        )
    divergences.append(
        SurfaceDivergence(
            "json_aggregates",
            "expression",
            "Qjson_aggregates.0: ORDER BY key mismatch at position 0. Original key: ('Brand#11',), "
            "Variant key: ('Brand#51',) (order-key columns [0]) - the returned order differs "
            "(e.g. a reversed ORDER BY).",
        )
    )
    divergences.append(
        SurfaceDivergence(
            "json_aggregates",
            "pandas",
            "Qjson_aggregates.0: Value mismatch at row 0, column 1. Original: [\"a\",\"b\"], Variant: ['a', 'b']",
        )
    )
    for base in ("map_access", "map_construction", "map_keys_values"):
        divergences.append(
            SurfaceDivergence(
                base, "expression", "error: map_from_entries not supported on Polars (no native Map dtype)"
            )
        )
    return divergences


def test_read_primitives_baseline_report_accepts_documented_cells_rejects_regressions(capsys):
    """End-to-end through :func:`_report`: the documented residues pass for every
    converted class, and a wider divergence on the SAME key fails the gate."""
    from benchbox.core.equivalence.cross_surface import GATES

    known = GATES["read_primitives"].known_divergences
    documented = _read_primitives_live_baseline_divergences()
    assert {f"{d.query_id}_{d.cell}" for d in documented} == set(known), (
        "test fixture must cover every converted read_primitives waiver key exactly once"
    )
    coverage = {"expression": len(documented), "pandas": len(documented)}
    assert (
        _report(
            documented,
            total=len(documented),
            coverage=coverage,
            known=known,
            benchmark="read_primitives",
            reference_row_counts={},
        )
        == 0
    )
    capsys.readouterr()

    # A wider, out-of-bounds sketch divergence on the SAME key is unclassified -
    # replace the documented approx_count_distinct_simple entry with a 10x-off
    # value; the rest of the baseline stays live so only this one regresses.
    regression = [d for d in documented if f"{d.query_id}_{d.cell}" != "approx_count_distinct_simple_expression"]
    regression.append(
        SurfaceDivergence(
            "approx_count_distinct_simple",
            "expression",
            "Qapprox_count_distinct_simple.0: Value mismatch at row 0, column 0. Original: 5210, Variant: 100",
        )
    )
    assert (
        _report(
            regression,
            total=len(regression),
            coverage=coverage,
            known=known,
            benchmark="read_primitives",
            reference_row_counts={},
        )
        == 1
    )
