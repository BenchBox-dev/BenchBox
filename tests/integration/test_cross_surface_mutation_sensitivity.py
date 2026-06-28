"""Mutation-sensitivity suite for the cross-surface SQL<->DataFrame gates (w10).

The cross-surface campaign only ever measured that the gates PASS (specificity);
it never measured whether they CATCH a seeded bug (sensitivity). PR #859 added a
single planted-divergence regression per enforced gate, but no SYSTEMATIC
mutation suite. This module fills that gap: for every ENFORCED gated benchmark
(read live from :data:`benchbox.core.equivalence.cross_surface.GATES`) it injects
a known DataFrame-side error into ONE query and asserts the real gate machinery
(:func:`find_cross_surface_divergences`, driving the reused
:class:`~benchbox.core.tpchavoc.validation.ResultValidator`) reports a divergence
- i.e. goes RED.

The mutation is applied by WRAPPING the target query's DataFrame impl at test
time (via :func:`dataclasses.replace` on the :class:`DataFrameQuery`), never by
editing the production query registries. The wrapper runs the real impl,
materializes its result rows through the same ``materialize_rows`` the gate uses,
applies one controlled perturbation, and returns the mutated rows as a frame the
comparator consumes - so the test exercises the production comparator end to end.

Four mutation classes, each chosen to exercise a distinct detection path of the
comparator (see :func:`_mutate_rows`):

* ``flip_comparator`` (``<`` -> ``<=``): a relaxed comparator admits the
  boundary-equal rows, so the result gains rows. Modeled by appending a duplicate
  boundary row -> a ROW-COUNT mismatch.
* ``drop_group_key``: grouping on fewer keys merges groups and changes the row
  shape. Modeled by dropping the leading column -> a COLUMN-COUNT mismatch.
* ``reverse_sort``: a reversed ``ORDER BY``. Modeled by reversing the row order
  while preserving the multiset. THIS IS THE BS2 PROBE: the comparator
  full-row-sorts both sides before comparing (validation.py), so a reversed order
  over a multi-row result is INVISIBLE to it. We assert the honest, documented
  outcome per benchmark rather than pretend the gate catches it.
* ``drop_join``: a dropped/incorrect join changes joined column values. Modeled
  by perturbing one cell value -> a VALUE mismatch.

The caught-vs-uncaught matrix this suite asserts is recorded as committed
evidence in ``_project/analysis/cross-surface-mutation-sensitivity.md``.

These tests build one bounded DuckDB cell per benchmark at each gate's declared
scale factor (the same cell the gates use) and are marked ``slow``; the heavier
benchmarks (amplab, clickbench) generate large data, so the whole suite is opt-in
via ``-m slow``.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable

import pytest

pytest.importorskip("polars", reason="Polars not installed")
pytest.importorskip("pandas", reason="Pandas not installed")
pytest.importorskip("duckdb", reason="DuckDB not installed")

import polars as pl

from benchbox.core.equivalence.cross_surface import (
    EQUIVALENCE_SCALE,
    GATES,
    build_production_contexts,
    find_cross_surface_divergences,
)
from benchbox.core.equivalence.dataframe_surface import fetch_reference_rows, materialize_rows
from benchbox.core.tpchavoc.validation import ResultValidator

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.duckdb,
]


# One discriminating target query per ENFORCED gated benchmark. Each was chosen
# (via a reference-shape probe at SF=0.1) to be the kind of query the mutation
# acts on: a multi-row, multi-column, ORDER BY + GROUP BY result wherever the
# benchmark has one, so reverse_sort and drop_group_key are non-degenerate. The
# membership of GATES itself is asserted below so this map cannot silently drift
# from the enforced set.
#
# clickbench deliberately targets Q8 (GROUP BY AdvEngineID ORDER BY COUNT(*) DESC,
# NO trailing LIMIT -> the STRICT comparator, with a DISCRIMINATING order key).
# Q31, the obvious multi-key candidate, is vacuous at SF=0.1: its COUNT(*) order
# key is constant (every row ties at 1) AND it carries a trailing LIMIT, so the
# tie-aware path accepts any single-row perturbation as a boundary swap (a BS3
# artifact). Q8 avoids both.
#
# joinorder_synthetic is the documented exception: every one of its gated queries
# is a single-row scalar aggregate, so a "reversed sort" is a no-op mutation
# (reversing a 1-row list changes nothing) and "drop_group_key" degenerates to a
# bare column drop. Worse, MOST of its queries return all-NULL at SF=0.1 (the
# JOB-style "find the min/argmin" match does not exist in the bounded cell - a
# BS3-vacuous result). Target 4a is one of the few that returns a non-NULL row
# (`('3.2', 'A Action Action')`), so its drop_join lands a real value mismatch.
# We still run it for the row-count/column-count/value paths and record both the
# single-row and mostly-NULL caveats in the findings doc.
_TARGETS: dict[str, str] = {
    "ssb": "Q3.1",  # 149 rows x 4 cols, ORDER BY + GROUP BY
    "amplab": "4",  # 100 rows x 6 cols, ORDER BY + GROUP BY
    "coffeeshop": "SA1",  # 93 rows x 5 cols, ORDER BY + GROUP BY (hand-written impls)
    "clickbench": "Q8",  # 20 rows x 2 cols, GROUP BY + ORDER BY, no LIMIT (strict path)
    "joinorder_synthetic": "4a",  # 1 row x 2 non-NULL string cols (single-row caveat)
    "h2odb": "Q6",  # multiple rows x 4 cols, GROUP BY + ORDER BY at _H2ODB_SCALE
    "read_primitives": "orderby_bigint",  # many rows x 2 cols, GROUP BY + ORDER BY at _READ_PRIMITIVES_SCALE
}


def _mutate_rows(rows: list[tuple[Any, ...]], kind: str) -> list[tuple[Any, ...]]:
    """Apply one controlled perturbation to materialized result rows.

    Each branch models the OBSERVABLE result shape of a real DataFrame logic bug
    of that class - the harness measures whether the gate's comparator catches a
    divergence of that shape, which is exactly the sensitivity question (C2).
    """
    if kind == "flip_comparator":
        # `<` -> `<=` admits boundary-equal rows: the result GAINS a row.
        return rows + [rows[-1]]
    if kind == "drop_group_key":
        # Grouping on fewer keys changes the row shape; drop the leading column.
        return [row[1:] for row in rows]
    if kind == "reverse_sort":
        # A reversed ORDER BY: same multiset, opposite order (the BS2 probe).
        return list(reversed(rows))
    if kind == "drop_join":
        # A dropped/incorrect join changes a joined column's value; perturb one
        # cell on the first row to a value that is the SAME Python type as the cell
        # (so the replacement frame keeps the column's dtype - a type-incompatible
        # sentinel would raise a frame-construction error and be miscounted as an
        # "error:" divergence for the wrong reason) and that differs by a
        # MAGNITUDE-INDEPENDENT amount (so the comparator's relative float tolerance
        # of 1e-10 can never mask it - a bare ``value + 1`` is within tolerance for
        # a large aggregate like SUM(revenue) >= ~1e10).
        first = list(rows[0])
        column = _perturbable_column(first)
        first[column] = _perturb_value(first[column])
        return [tuple(first)] + list(rows[1:])
    raise ValueError(f"unknown mutation kind: {kind}")


def _is_number(value: Any) -> bool:
    """True for a real numeric scalar (int/float), excluding bool."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _perturbable_column(row: list[Any]) -> int:
    """Index of the rightmost numeric (preferred) or string cell to perturb.

    A numeric cell is preferred because the magnitude-independent numeric
    perturbation in :func:`_perturb_value` is guaranteed to exceed the comparator's
    relative tolerance; a string cell is the fallback. Raising on a row with
    neither keeps the harness honest - a value mutation that cannot land a
    type-safe, tolerance-beating change is a test-setup error, surfaced loudly
    rather than silently passing for the wrong reason.
    """
    for index in range(len(row) - 1, -1, -1):
        if _is_number(row[index]):
            return index
    for index in range(len(row) - 1, -1, -1):
        if isinstance(row[index], str):
            return index
    raise ValueError(f"drop_join mutation needs a numeric or string column to perturb; row={row!r}")


def _perturb_value(value: Any) -> Any:
    """Return a same-type value that differs from ``value`` beyond any tolerance.

    For a number, ``-value - 1`` flips the sign and offsets: the relative
    difference is ~2 for any large magnitude (well above the 1e-10 relative
    tolerance) and the absolute difference is >= 1 for a value near zero (above
    the absolute tolerance), so the mismatch is ALWAYS reported. For a string,
    append a marker guaranteed to make it distinct.
    """
    if _is_number(value):
        return -value - 1
    return f"{value}_ZZZ_MUTATION"


# Per benchmark+mutation: whether the gate is EXPECTED to catch the seeded bug.
# True  -> the mutation must make the gate go RED (sensitivity proven).
# False -> the gate provably cannot catch it; the reason is recorded in the
#          findings doc and asserted as a documented blind spot, never silently
#          ignored.
_EXPECT_CAUGHT: dict[tuple[str, str], bool] = {
    # reverse_sort is the BS2 order-blindness probe. The order-aware comparator
    # (w2: validate_results_exact(order_aware=True), enabled per query whose
    # ORDER BY maps to result-column positions) now compares the RETURNED order, so
    # a reversed ORDER BY over a multi-row result with a discriminating order key is
    # CAUGHT. Every multi-row target here declares such an ORDER BY (ssb Q3.1
    # d_year/revenue, amplab "4" total_revenue DESC, coffeeshop SA1
    # order_date/region, clickbench Q8 COUNT(*) DESC), so each flips to caught.
    # joinorder_synthetic is single-row: reversing a 1-row list is a no-op, so the
    # mutation injects no divergence at all (a degenerate, expected miss) - it stays
    # the one documented reverse_sort blind spot.
    ("joinorder_synthetic", "reverse_sort"): False,
}


def _expect_caught(benchmark: str, kind: str) -> bool:
    """Default to expecting the mutation caught unless recorded as a blind spot."""
    return _EXPECT_CAUGHT.get((benchmark, kind), True)


def _mutated_dataframe_query(
    dataframe_query: Callable[[Any], Any],
    target: str,
    kind: str,
) -> Callable[[Any], Any]:
    """Return a ``dataframe_query`` that injects ``kind`` into ``target`` only.

    Wraps each implemented backend of the target query so its returned frame is
    replaced by the mutated rows; every other query is passed through unchanged,
    and the production registry is never mutated.
    """

    def wrap(impl: Callable[[Any], Any] | None) -> Callable[[Any], Any] | None:
        if impl is None:
            return None

        def wrapped(ctx: Any) -> Any:
            rows = materialize_rows(impl(ctx))
            if not rows:
                # No rows to mutate (vacuous cell) - return as-is; the harness
                # asserts the chosen targets are non-empty, so this never fires
                # for a real target, only defends against an accidental pick.
                return pl.DataFrame()
            mutated = _mutate_rows(rows, kind)
            schema = [f"c{i}" for i in range(len(mutated[0]))]
            return pl.DataFrame(mutated, schema=schema, orient="row")

        return wrapped

    def dispatch(query_id: Any) -> Any:
        query = dataframe_query(query_id)
        if str(query_id) != target:
            return query
        return replace(
            query,
            pandas_impl=wrap(query.pandas_impl),
            expression_impl=wrap(query.expression_impl),
        )

    return dispatch


@dataclass
class _GateCell:
    """One benchmark's bounded cell, built ONCE and reused across its mutations.

    Building the SF=0.1 cell (data generation + the production CSV->parquet load
    into both backend contexts) is the dominant cost - tens of seconds, up to
    minutes for the heavier benchmarks. Rebuilding it per mutation would be ~5x the
    work AND would let two xdist workers regenerate the same heavy benchmark
    concurrently (observed to OOM a worker mid-parquet-write -> a truncated file).
    So a module-scoped fixture builds each benchmark's cell once; the mutations
    only re-wrap the target impl (cheap) and re-run the comparator on the shared,
    read-only contexts.
    """

    gate_name: str
    data: Any
    contexts: dict[str, Any]
    reference_row_count: int


def _build_gate_cell(gate_name: str, tmp_path: Any) -> _GateCell:
    """Build one benchmark's bounded cell and capture the target's reference count."""
    gate = GATES[gate_name]
    data = gate.build(gate.scale_factor, tmp_path)
    contexts = build_production_contexts(data.benchmark, data.data_dir, backends=gate.backends)
    reference_row_count = len(fetch_reference_rows(data.connection, data.reference_sql(_TARGETS[gate_name])))
    return _GateCell(gate_name=gate_name, data=data, contexts=contexts, reference_row_count=reference_row_count)


def _run_target_gate(cell: _GateCell, *, mutation: str | None = None) -> list[Any]:
    """Run the gate over the single target query of an already-built cell.

    Running only the target query (the rest are unmutated and already green) keeps
    the comparison cheap while still driving the real gate machinery. The mutation,
    when given, wraps only the target impl - the shared contexts are never mutated,
    so reusing one cell across all mutations is safe.
    """
    gate = GATES[cell.gate_name]
    data = cell.data
    target = _TARGETS[cell.gate_name]
    dataframe_query = data.dataframe_query
    if mutation is not None:
        dataframe_query = _mutated_dataframe_query(data.dataframe_query, target, mutation)
    return find_cross_surface_divergences(
        data.connection,
        query_ids=[target],
        reference_sql=data.reference_sql,
        dataframe_query=dataframe_query,
        contexts=cell.contexts,
        validator=ResultValidator(tolerance=gate.tolerance),
        backends=gate.backends,
    )


_MUTATIONS = ("flip_comparator", "drop_group_key", "reverse_sort", "drop_join")


# Module-scoped per-benchmark cell, built once PER WORKER. With xdist's default
# `load` distribution a benchmark's cells can still land on different workers (each
# builds its own copy into its own ``tmp_path_factory`` dir - no shared file, so no
# cross-worker corruption), but a single worker never rebuilds the same benchmark
# for each of its mutations - it builds once and reuses. That bounds heavy data
# generation to at most one concurrent build per worker, which removed the
# OOM/truncated-parquet failures seen when every mutation rebuilt from scratch. The
# connection is closed by the fixture finalizer.
@pytest.fixture(scope="module")
def gate_cell(request: Any, tmp_path_factory: Any) -> Any:
    """Build (once per worker) and yield the requested benchmark's bounded cell."""
    gate_name = request.param
    tmp_path = tmp_path_factory.mktemp(f"mutcell_{gate_name}")
    cell = _build_gate_cell(gate_name, tmp_path)
    try:
        yield cell
    finally:
        cell.data.connection.close()


def test_targets_cover_every_enforced_gate() -> None:
    """The mutation targets must track the live enforced GATES set exactly.

    Guards against drift: if a benchmark is added to or removed from GATES the
    suite fails until a target query is chosen for it, so a newly-enforced gate
    can never silently escape sensitivity testing.
    """
    assert set(_TARGETS) == set(GATES), (
        "mutation targets out of sync with enforced GATES: "
        f"missing={set(GATES) - set(_TARGETS)} extra={set(_TARGETS) - set(GATES)}"
    )


# Indirect parametrization on the ``gate_cell`` fixture (built once per benchmark).
# The id is the benchmark name. The fixture's request.param is named ``gate_cell``
# (not ``benchmark``): pytest-benchmark registers a ``benchmark`` fixture, so a
# parameter of that name collides with it and crashes the xdist worker.
@pytest.mark.parametrize("gate_cell", sorted(_TARGETS), indirect=True)
def test_unmutated_target_is_green(gate_cell: _GateCell) -> None:
    """Sanity floor: the chosen target query is non-empty and diverges from nothing.

    A mutation-sensitivity result is only meaningful if the un-mutated cell is
    already green and discriminating (non-empty). This pins both: an empty target
    would make every "not caught" result a BS3 artifact rather than a comparator
    property.
    """
    gate_name = gate_cell.gate_name
    target = _TARGETS[gate_name]
    divergences = _run_target_gate(gate_cell, mutation=None)
    assert not divergences, f"{gate_name} target {target} is not green before mutation: {divergences}"
    # Non-vacuity floor. >= 2 (not just >= 1) so reverse_sort is a real ordering
    # change, not a single-row no-op - except joinorder_synthetic, whose every
    # gated query is a single-row scalar (the documented single-row caveat); there
    # we still require a non-empty (>= 1) reference so the cell is not vacuous.
    minimum = 1 if gate_name == "joinorder_synthetic" else 2
    assert gate_cell.reference_row_count >= minimum, (
        f"{gate_name} target {target} returned {gate_cell.reference_row_count} reference row(s) "
        f"at SF={GATES[gate_name].scale_factor}; a vacuous/too-small target would make 'not caught' results a "
        f"BS3 artifact - pick a discriminating target."
    )


@pytest.mark.parametrize("gate_cell", sorted(_TARGETS), indirect=True)
@pytest.mark.parametrize("kind", _MUTATIONS)
def test_mutation_sensitivity(kind: str, gate_cell: _GateCell) -> None:
    """A seeded DataFrame bug either makes the gate RED, or is a documented miss.

    For each (benchmark, mutation) the expected outcome is recorded in
    :data:`_EXPECT_CAUGHT`. A "caught" mutation asserts the gate reports >=1
    divergence (sensitivity proven). A "not caught" mutation asserts the gate
    reports ZERO divergences - the honest evidence that the comparator is blind to
    that mutation class (the reversed-sort BS2 blindness, or a single-row
    degenerate no-op), cross-referenced in
    ``_project/analysis/cross-surface-mutation-sensitivity.md``.
    """
    gate_name = gate_cell.gate_name
    gate = GATES[gate_name]
    target = _TARGETS[gate_name]
    divergences = _run_target_gate(gate_cell, mutation=kind)
    caught = bool(divergences)
    expected = _expect_caught(gate_name, kind)

    if expected:
        # find_cross_surface_divergences emits one SurfaceDivergence per
        # query/backend cell, keyed ``f"{query_id}_{backend}"``. A bare
        # ``bool(divergences)`` would pass as soon as ANY single backend caught
        # the mutation, so if the target query lost one of its gated impls (or
        # only one gated backend caught it) the other backend would be silently
        # skipped/green while the test still claimed sensitivity. Require EVERY
        # gated backend to have caught it.
        expected_keys = {f"{target}_{backend}" for backend in gate.backends}
        found_keys = {d.key for d in divergences}
        missing = expected_keys - found_keys
        assert not missing, (
            f"SENSITIVITY GAP: {gate_name} {target} {kind} was NOT caught by the gate "
            f"on every gated backend (expected RED on {sorted(expected_keys)}; "
            f"missing {sorted(missing)}, got {sorted(found_keys)}). A target query that "
            f"lost an implementation or that only one backend catches must not pass as "
            f"'sensitive' - the comparator missed a seeded bug it should detect."
        )
        # The catch must be a genuine result mismatch, not an ``error:`` from the
        # harness failing to build the mutated frame (which would "pass" for the
        # wrong reason - see find_surface_divergences' execution-error branch).
        errored = [d for d in divergences if d.detail.startswith("error:")]
        assert not errored, (
            f"{gate_name} {target} {kind} was caught only via a harness execution error, "
            f"not a result mismatch: {[(d.key, d.detail) for d in errored]}"
        )
    else:
        assert not caught, (
            f"{gate_name} {target} {kind} was unexpectedly CAUGHT "
            f"({[d.key for d in divergences]}). A documented blind spot is now closed - "
            f"update _EXPECT_CAUGHT and the findings doc."
        )


@pytest.mark.parametrize("gate_cell", ["ssb"], indirect=True)
def test_reversed_sort_is_the_bs2_probe(gate_cell: _GateCell) -> None:
    """Headline BS2 probe: a reversed ORDER BY is now CAUGHT on a multi-row gate.

    The previously-open half of w2/BS2 was whether the comparator catches a
    reversed ORDER BY. It used to full-row-sort both sides before comparing, so it
    could not - and this test pinned the silent pass. The w2 order-aware comparator
    closes that blind spot: for a query whose ORDER BY maps to result-column
    positions (ssb Q3.1 sorts by d_year ASC, revenue DESC -> result columns 2, 3),
    ``validate_results_exact(order_aware=True)`` compares the RETURNED order, so a
    reversed result now diverges. This test pins the FIXED property directly on ssb
    Q3.1 (149 ordered rows): the reversed result yields >= 1 divergence, and it is a
    genuine ORDER BY mismatch, not a harness ``error:``.
    """
    # The probe is only meaningful over a genuinely ordered, multi-row result: a
    # 0/1-row reference would make the result an artifact rather than a comparator
    # property.
    assert gate_cell.reference_row_count >= 2, (
        f"ssb {_TARGETS['ssb']} returned only {gate_cell.reference_row_count} row(s); reverse-sort probe is vacuous."
    )
    divergences = _run_target_gate(gate_cell, mutation="reverse_sort")
    assert divergences, (
        "ssb Q3.1 reversed-sort was NOT caught - the order-aware comparator (w2) "
        "should make a reversed ORDER BY visible on this multi-row gate."
    )
    errored = [d for d in divergences if d.detail.startswith("error:")]
    assert not errored, (
        f"ssb Q3.1 reversed-sort was flagged only via a harness execution error, "
        f"not an ORDER BY mismatch: {[(d.key, d.detail) for d in errored]}"
    )


def test_gate_output_is_byte_stable_across_two_in_process_runs(tmp_path: Any) -> None:
    """w3 byte-stability regression: two in-process runs on one seed agree exactly.

    w3's second acceptance criterion is a regression that asserts gate output is
    byte-stable across two in-process runs on the same seed. We run the ssb gate's
    full query set twice in the same process and assert the divergence sets (keys
    and details) are identical, pinning the determinism the tie-aware comparator
    provides.
    """
    benchmark = "ssb"
    gate = GATES[benchmark]

    def run_once(sub: Any) -> list[tuple[str, str]]:
        data = gate.build(EQUIVALENCE_SCALE, sub)
        connection = data.connection
        try:
            contexts = build_production_contexts(data.benchmark, data.data_dir, backends=gate.backends)
            divergences = find_cross_surface_divergences(
                connection,
                query_ids=data.query_ids,
                reference_sql=data.reference_sql,
                dataframe_query=data.dataframe_query,
                contexts=contexts,
                validator=ResultValidator(tolerance=gate.tolerance),
                backends=gate.backends,
            )
        finally:
            connection.close()
        return sorted((d.key, d.detail) for d in divergences)

    first = run_once(tmp_path / "run1")
    second = run_once(tmp_path / "run2")
    assert first == second, f"ssb gate output not byte-stable across runs: {first!r} != {second!r}"
