"""Cross-surface SQL<->DataFrame result-equivalence gates.

A benchmark that ships both a SQL surface and a DataFrame surface gives two
expressions of the same logical queries, so a divergence between them proves at
least one is wrong - a maintenance-free correctness oracle that needs no
hand-curated answer key. For every benchmark except tpch and tpcds (which have
stored expected results) and tpchavoc (which has its own variant + DataFrame
gates), this cross-surface check is the only automated correctness oracle
available today.

What the oracle actually proves (and what it does NOT) - be precise about the
independence, because it varies by benchmark and is weaker than "two independent
implementations" suggests:

* The independence is always SQL-text vs DataFrame-code, authored by the same
  person from the same understanding. So the oracle reliably catches
  TRANSCRIPTION errors (a column/filter/join mistyped on one surface) but not a
  shared CONCEPTUAL error (a misread spec that the author encodes identically on
  both surfaces).
* For ``ssb`` (and ~40/43 ``clickbench`` queries) the two DataFrame backends are
  not independent of each other at all: both the Polars-expression and the
  Pandas impl are GENERATED from one compact DSL spec row, so a logic error in
  that spec appears identically on both backends - the only signal is SQL vs the
  shared spec.
* For ``coffeeshop`` and ``amplab`` each query's two backends are SEPARATELY
  hand-written (``*_expression_impl`` and ``*_pandas_impl``), so they can also
  diverge on engine semantics - a stronger (but still same-author) check.

See ``_project/analysis/cross-surface-oracle-independence.md`` for the
per-benchmark generated-vs-hand-written record.

This module runs that oracle on a bounded small-SF cell, reusing the shared
harness in :mod:`benchbox.core.equivalence.dataframe_surface`:
``python -m benchbox.core.equivalence.cross_surface --benchmark ssb`` (or
``make ssb-cross-surface-equivalence-report``) generates one bounded cell of
data, executes each query's SQL on DuckDB as the trusted reference, loads that
SAME generated data into each shipped DataFrame backend (the Polars expression
family and the Pandas family) via the real production loader, runs each query's
DataFrame implementation, compares each live with the reused
:class:`~benchbox.core.tpchavoc.validation.ResultValidator` (order-insensitive,
float-tolerant), and **exits non-zero** if any benchmark/query/backend cell
diverges beyond that benchmark's ``known_divergences`` baseline (empty - SQL is
the reference for its own DataFrame surface and every cell must match).

The DataFrame side both LOADS and EXECUTES through the real product path - data
via :meth:`load_benchmark_into_context` (the same loader
``DataFrameAdapter.run_benchmark`` uses, so dtypes match a production run) and
queries via :meth:`DataFrameQuery.get_impl_for_family` (the same accessor
``DataFrameAdapter.execute_query`` uses) - rather than any bespoke engine, and
the comparator is reused from the shared harness, never forked.

Currently gated (enforced :data:`GATES`): ssb (canonical and small; SQL and
DataFrame ids correspond 1:1 as ``Q1.1`` .. ``Q4.3``), amplab (8 queries; the SQL
ids ``"1"``, ``"1a"``, ``"2"`` .. ``"5"`` map 1:1 to the DataFrame ids by a
mechanical ``Q`` prefix: ``"Q1"``, ``"Q1a"``, ``"Q2"`` .. ``"Q5"``), coffeeshop,
clickbench (the one classified exception is the order-less ``Q18``),
joinorder_synthetic and h2odb (single ``trips`` table; SQL and DataFrame ids
correspond 1:1 as ``Q1`` .. ``Q10``; the one classified exception is ``Q9``'s
PERCENTILE_CONT, where DuckDB returns the percentile at the source column's
DECIMAL(8,2) scale - see ``_H2ODB_PERCENTILE_DECIMAL``). Additional dual-surface
benchmarks are added by registering a :class:`CrossSurfaceGate` in :data:`GATES`.

Waiver review policy. A ``known_divergences`` entry may carry an OPTIONAL
``review_by`` date (a new field on :class:`ClassifiedDivergence`; bare-``str``
entries cannot carry one - upgrade to ``ClassifiedDivergence`` to add a date).
When ``review_by`` has passed, :func:`_report` prints a "WAIVER REVIEW DUE" line
and WARNS - it does NOT fail the gate. This is a distinct signal from the
existing stale-baseline (``resolved``) failure above: ``resolved`` means the
divergence is GONE and the entry should be deleted; a past-due ``review_by``
means the divergence may still be entirely correct, but enough time has passed
(an engine version bump, a benchmark data/query change, or simply time) that a
human should re-confirm the original rationale still holds. Leaving
``review_by`` unset is always safe - it is opt-in, never required, and no
existing waiver is forced to adopt one.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from benchbox.core.equivalence.builders import (
    CrossSurfaceData,
    build_amplab_duckdb,
    build_clickbench_duckdb,
    build_coffeeshop_duckdb,
    build_h2odb_duckdb,
    build_joinorder_synthetic_duckdb,
    build_read_primitives_duckdb,
    build_ssb_duckdb,
)
from benchbox.core.equivalence.dataframe_surface import (
    DATAFRAME_BACKENDS,
    SurfaceDivergence,
    fetch_reference_rows,
    find_surface_divergences,
    materialize_rows,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Deferred at runtime: importing benchbox.core.tpchavoc.validation triggers
    # the tpchavoc package __init__ (which pulls DuckDB/NumPy), so the runtime
    # imports live inside the functions that need them. This keeps core/equivalence
    # from taking a direct tpchavoc dependency in its module import graph (the
    # shared harness in dataframe_surface deliberately avoids it too), even though
    # importing the top-level benchbox package is heavy for unrelated reasons.
    from benchbox.core.tpchavoc.validation import ResultValidator


def _load_known_divergences_baseline() -> dict[str, dict[str, str]]:
    """Load the plain-string ``known_divergences`` baseline from its YAML file.

    Only entries with no executable acceptance logic live in the YAML file (see
    its header). A gate with no section in the file (or no file entries at all)
    gets an empty dict here - merged with any in-code ``ClassifiedDivergence``
    entries by the gate's own constant below, never a KeyError.
    """
    payload = yaml.safe_load(
        resources.files("benchbox.core.equivalence").joinpath("cross_surface_baseline.yaml").read_text(encoding="utf-8")
    )
    if not isinstance(payload, dict):
        raise RuntimeError("cross_surface_baseline.yaml must contain a top-level mapping")
    return payload


_KNOWN_DIVERGENCES_BASELINE: dict[str, dict[str, str]] = _load_known_divergences_baseline()

# Smallest scale that is both discriminating and cheap; matches the TPC-Havoc
# gates' SF=0.1 DuckDB cell so routine PRs stay cheap (one bounded cell per
# gated benchmark, never a full platform matrix).
EQUIVALENCE_SCALE = 0.1

SURFACE_INDEPENDENCE_SHARED_SPEC = "shared-spec"
SURFACE_INDEPENDENCE_MIXED = "mixed-provenance"
SURFACE_INDEPENDENCE_SEPARATE = "separate-handwritten"

_DEFAULT_SURFACE_INDEPENDENCE_RATIONALE = (
    "SQL and DataFrame surfaces are maintained from a shared benchmark spec; the gate catches "
    "transcription drift between surfaces, not shared conceptual mistakes."
)

# Captures a trailing ``LIMIT n`` so it can be both DETECTED (truncated top-N) and
# REWRITTEN one row wider (the boundary-tie probe). Group 1 is ``limit `` (original
# case/spacing), group 2 the integer, group 3 any OFFSET / statement terminator /
# trailing whitespace - reassembled verbatim so only the count changes.
_TRAILING_LIMIT_RE = re.compile(r"(?is)(\blimit\s+)(\d+)(\s*(?:offset\s+\d+\s*)?;?\s*)$")
_TRAILING_COMMENT_RE = re.compile(r"\s*--[^\n]*$")


def _strip_trailing_comment(sql: str) -> str:
    """Strip a trailing ``-- line comment`` and surrounding whitespace from ``sql``.

    Shared by the trailing-``LIMIT`` detector and rewriter so ``... limit 10 -- note``
    is handled identically by both. Removing a trailing comment never changes query
    semantics, so the stripped form is still valid SQL to execute.
    """
    return _TRAILING_COMMENT_RE.sub("", sql.strip())


def _is_truncated_top_n(sql: str) -> bool:
    """True if a SQL query ends in a ``LIMIT n`` (a truncated top-N candidate).

    The tie-aware boundary relaxation is only sound where a ``LIMIT`` can actually
    truncate a tie across the cutoff. Applying it to a full (un-truncated) result
    set whose last order-key value is duplicated could let a real divergence in a
    determined boundary row pass as an ambiguous "tie swap", so the gate enables
    ``tie_aware`` per query ONLY for queries that carry a trailing ``LIMIT``;
    everything else uses the strict comparator. A trailing line comment /
    statement terminator is stripped first so ``... limit 10 -- note`` matches.
    """
    return bool(_TRAILING_LIMIT_RE.search(_strip_trailing_comment(sql)))


def _bump_trailing_limit(sql: str) -> str | None:
    """Return ``sql`` with its trailing ``LIMIT n`` raised to ``LIMIT n+1``, or None.

    The boundary-tie probe (:func:`_final_key_tied_beyond_limit`) needs exactly one
    row PAST the original top-N cutoff to learn whether the final order key ties
    across it. Raising the trailing ``LIMIT`` by one row does that while preserving
    any ``OFFSET`` (the window simply widens by one at its end), statement
    terminator, and trailing comment, so the probe is the same query plus one row.
    Returns None when no trailing numeric ``LIMIT`` is present (the caller then
    skips the probe and stays strict).
    """
    stripped = _strip_trailing_comment(sql)
    match = _TRAILING_LIMIT_RE.search(stripped)
    if match is None:
        return None
    bumped = int(match.group(2)) + 1
    return f"{stripped[: match.start()]}{match.group(1)}{bumped}{match.group(3)}"


def _final_key_tied_beyond_limit(
    connection: Any,
    sql: str,
    order_by: Sequence[int],
    reference: list[tuple[Any, ...]],
) -> bool:
    """True if the reference's final ORDER BY key value recurs past the LIMIT cutoff.

    A trailing-``LIMIT`` top-N can cut across a tie in the order key, leaving only a
    SUBSET of the rows that share the worst-kept key value. The truncated result
    alone cannot tell that legitimate boundary tie apart from a complete final tie
    group whose members must match, so the comparator would either mask a real value
    bug or false-positive a valid tie pick (the soundness gap this probe closes).
    The probe supplies the missing signal: it re-runs the query one row wider
    (``LIMIT n+1``) and reports whether the row JUST past the original cutoff
    carries the SAME order-key value as the last row inside it. If so, the final key
    is genuinely tied across the cutoff and a final-group membership difference is
    an equally-valid boundary pick; if not (or there is no row past the cutoff), the
    final group is complete or unproven and must match.

    Returns False on any condition that makes the probe unsound or impossible - an
    empty reference, an out-of-range order key, an un-rewritable ``LIMIT``, or a
    probe-query failure - so the caller keeps the strict default and the worst case
    is a (loud, recoverable) caught mismatch, never a masked bug.
    """
    if not reference or not order_by:
        return False
    n = len(reference)
    width = len(reference[-1])
    if any(c < 0 or c >= width for c in order_by):
        return False
    final_key = tuple(reference[-1][c] for c in order_by)
    probe_sql = _bump_trailing_limit(sql)
    if probe_sql is None:
        return False
    try:
        probe = fetch_reference_rows(connection, probe_sql)
    except Exception:  # noqa: BLE001 - a failed probe must not crash the gate; stay strict
        return False
    # No row past the original cutoff -> the final visible row is the true last row,
    # so its key is not tied beyond the LIMIT.
    if len(probe) <= n or len(probe[n]) <= max(order_by):
        return False
    # The first n probe rows are the original window (same deterministic ORDER BY key
    # sequence as the reference), so probe[n] is the first row PAST the cutoff. The
    # final key ties across the cutoff iff probe[n] carries that same key. Both values
    # come from the same DuckDB result, so exact equality is the right within-result
    # tie test (the comparator's cross-engine float tolerance does not apply here).
    key_beyond = tuple(probe[n][c] for c in order_by)
    return final_key == key_beyond


def _is_star_projection(projection: Any) -> bool:
    """True if a SELECT projection is a wildcard (``*`` or ``t.*``), else False.

    A wildcard expands to an unknown number of output columns, so it cannot be
    enumerated to positions without the table schema. A ``Star`` nested INSIDE an
    expression (e.g. ``COUNT(*)``) is a normal single output column and is NOT a
    wildcard projection, so it must return False here.
    """
    from sqlglot import exp

    return isinstance(projection, exp.Star) or (
        isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star)
    )


def _order_by_result_key(sql: str) -> list[int] | None:
    """Resolve a query's ``ORDER BY`` key to RESULT-column positions, or ``None``.

    Returns the list of RESULT-row column indices (in key order) that the query's
    ``ORDER BY`` sorts on, which the order-aware comparator
    (:meth:`ResultValidator.validate_results_exact` with ``order_aware=True``) uses
    to compare rows in returned order. Only the COLUMNS matter, not the sort
    direction: a reversed ``ORDER BY`` is caught by the comparator detecting that
    the returned sequence of distinct key values differs, which is
    direction-independent. Returns ``None`` when no sound mapping exists, so the
    caller falls back to the order-insensitive comparison rather than guessing:

      * the query has no ``ORDER BY`` (nothing to check in returned order);
      * the SQL does not parse (a malformed or unsupported shape);
      * ANY ``ORDER BY`` expression does not correspond to a projected output
        column - e.g. ``ORDER BY EventTime`` over ``SELECT SearchPhrase`` (the
        sort key is not in the result, so the order cannot be verified from the
        returned columns), or ``SELECT *`` (the projection is not enumerable to
        positions without resolving the table schema). Refusing to map these is
        deliberate: an order-blind fallback that silently "passed" an unverifiable
        ORDER BY is exactly the BS2 blind spot, so we never claim an order check we
        cannot perform.

    The mapping resolves each ``ORDER BY`` term to a projection by, in order: a
    1-based ordinal literal (``ORDER BY 2`` -> result column index 1); the
    alias-or-name (so ``ORDER BY revenue`` finds ``SUM(...) AS revenue`` and
    ``ORDER BY ol.order_date`` finds the ``order_date`` output); else the
    normalized SQL of the underlying expression (so ``ORDER BY COUNT(*)`` finds the
    ``COUNT(*)`` projection and ``ORDER BY DATE_TRUNC(...)`` finds its aliased
    projection).
    """
    import sqlglot
    from sqlglot import exp

    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:  # noqa: BLE001 - an unparseable query is just "no sound mapping"
        return None
    if tree is None:
        return None
    select = tree.find(exp.Select)
    if select is None:
        return None
    order = select.args.get("order")
    if order is None:
        return None

    # A bare `SELECT *` (or `t.*`) cannot be enumerated to output positions without
    # resolving the table schema, so a star PROJECTION makes the mapping unsound.
    # Only a projection that IS a star counts: a star nested inside an expression
    # (e.g. ``COUNT(*)``) is a normal single output column, not a wildcard
    # expansion, so it must NOT disqualify the query.
    projections = select.expressions
    if any(_is_star_projection(proj) for proj in projections):
        return None

    alias_to_index: dict[str, int] = {}
    expr_to_index: dict[str, int] = {}
    for index, proj in enumerate(projections):
        name = proj.alias_or_name
        if name:
            alias_to_index.setdefault(name.lower(), index)
        inner = proj.this if isinstance(proj, exp.Alias) else proj
        expr_to_index.setdefault(inner.sql(dialect="duckdb", normalize=True).lower(), index)

    resolved: list[int] = []
    for ordered in order.expressions:
        target = ordered.this
        index = _resolve_order_term(target, projections, alias_to_index, expr_to_index)
        if index is None:
            # An ORDER BY term that is not a projected output column - the order
            # cannot be verified from the returned rows. Refuse the whole key.
            return None
        resolved.append(index)
    return resolved


def _resolve_order_term(
    target: Any,
    projections: Sequence[Any],
    alias_to_index: dict[str, int],
    expr_to_index: dict[str, int],
) -> int | None:
    """Resolve one ``ORDER BY`` term to a result-column index, or ``None``.

    Tries, in order: a 1-based positional ordinal (``ORDER BY 2``); the column
    alias-or-name; else the normalized SQL of the expression. ``None`` means the
    term is not a projected output column (the caller then refuses the whole key).
    """
    from sqlglot import exp

    # 1-based ordinal: ``ORDER BY 2`` references the 2nd projected column. Only a
    # plain integer literal in range is a valid ordinal.
    if isinstance(target, exp.Literal) and target.is_int:
        ordinal = int(target.name)
        return ordinal - 1 if 1 <= ordinal <= len(projections) else None
    if isinstance(target, exp.Column):
        index = alias_to_index.get(target.name.lower())
        if index is not None:
            return index
    return expr_to_index.get(target.sql(dialect="duckdb", normalize=True).lower())


@dataclass(frozen=True)
class ClassifiedDivergence:
    """A baselined divergence accepted ONLY when ``accepts`` matches the live cell.

    A bare ``str`` baseline entry tolerates ANY divergence on its key, which masks a
    real regression that happens to land on the same query/backend. A
    ``ClassifiedDivergence`` instead tolerates a divergence only when its ``accepts``
    predicate confirms the actual cell detail is the specific, defensible difference
    described by ``reason`` - so a genuinely wrong value on the same key is still
    reported as an unclassified gate failure.

    ``requires_live_divergence`` preserves stale-baseline hygiene by default. Set it
    false only for a nondeterministic classification whose absence is not evidence
    of resolution (for example, an order-less LIMIT whose arbitrary top-N selection
    can occasionally line up across surfaces by chance).

    ``review_by`` is an OPTIONAL forcing-function date for waivers whose divergence
    is expected to stay LIVE indefinitely (so the ``resolved`` stale-baseline check
    above never fires on its own). It is a different signal from ``resolved``:
    ``resolved`` means the divergence is GONE and the entry should be deleted;
    a past-due ``review_by`` means the divergence may still be entirely correct, but
    enough time has passed that a human should re-look (the engine version that
    produced the behavior may have changed, the benchmark's data/queries may have
    evolved, or the original rationale may no longer hold). A past-due ``review_by``
    only WARNS in :func:`_report` - it never fails the gate - so leaving it unset is
    always safe and never migrates existing waivers. See the module docstring's
    "waiver review policy" section for the full contract.
    """

    reason: str
    accepts: Callable[[SurfaceDivergence], bool]
    requires_live_divergence: bool = True
    review_by: date | None = None


@dataclass(frozen=True)
class CrossSurfaceGate:
    """Per-benchmark wiring for a cross-surface SQL<->DataFrame gate."""

    name: str
    build: Callable[[float, Path], CrossSurfaceData]
    # Cells tolerated to diverge, keyed by SurfaceDivergence.key
    # ("<query>_<backend>"). Empty by default: SQL is the reference for its own
    # DataFrame surface, so every cell must match. Add a classified entry only
    # for a deliberate, defensible presentational difference - never to mute a
    # regression.
    known_divergences: dict[str, str | ClassifiedDivergence] = field(default_factory=dict)
    # Queries whose SQL reference legitimately returns 0 rows at the bounded
    # cell, keyed by query id, with a rationale string. A both-empty cell
    # compares empty-vs-empty and is NON-discriminating (every backend trivially
    # "matches"), so the gate FAILS on any vacuous query that is NOT listed here -
    # the same discipline as ``known_divergences``, but for vacuity rather than a
    # tolerated mismatch. Prefer making a query non-empty (a discriminating SF or
    # parameter) over classifying it; classify only when the generated data simply
    # cannot contain rows matching the canonical query (e.g. a value-format
    # mismatch the benchmark's own parameters cannot bridge), with a written
    # reason here. NEVER add an entry to mute a query you could make discriminating.
    legitimately_empty: dict[Any, str] = field(default_factory=dict)
    backends: tuple[str, ...] = DATAFRAME_BACKENDS
    tolerance: float = 1e-10
    surface_independence: str = SURFACE_INDEPENDENCE_SHARED_SPEC
    surface_independence_rationale: str = _DEFAULT_SURFACE_INDEPENDENCE_RATIONALE
    # Comparator widening is strict by default. Enable these only for a gate with
    # documented engine decode behavior that otherwise reports presentational
    # NULL/CHAR differences rather than logical result differences.
    treat_nan_as_null: bool = False
    strip_strings: bool = False
    # Per-gate data scale for the bounded cell. Defaults to the shared
    # EQUIVALENCE_SCALE so every gate stays cheap; a gate raises it ONLY when a
    # larger (still bounded) cell is the cheapest way to make its queries
    # discriminating. Kept on the gate (not a global) so one benchmark's data
    # needs never inflate every other gate's cost.
    scale_factor: float = EQUIVALENCE_SCALE

    def build_validator(self) -> ResultValidator:
        """Create the comparator configured for this gate's documented tolerances."""
        from benchbox.core.tpchavoc.validation import ResultValidator

        return ResultValidator(
            tolerance=self.tolerance,
            treat_nan_as_null=self.treat_nan_as_null,
            strip_strings=self.strip_strings,
        )


def find_cross_surface_divergences(
    connection: Any,
    *,
    query_ids: Iterable[Any],
    reference_sql: Callable[[Any], str],
    dataframe_query: Callable[[Any], Any],
    contexts: dict[str, Any],
    validator: ResultValidator,
    backends: tuple[str, ...] = DATAFRAME_BACKENDS,
    reference_row_counts: dict[Any, int] | None = None,
) -> list[SurfaceDivergence]:
    """Compare each query's DataFrame surface to its own SQL surface on DuckDB.

    Args:
        connection: A DuckDB connection populated with the benchmark's data
            (the SQL reference executes here).
        query_ids: The query ids to check (same ids on both surfaces).
        reference_sql: Callable returning the benchmark's SQL for a query id.
        dataframe_query: Callable returning the benchmark's
            :class:`DataFrameQuery` for a query id.
        contexts: Backend-name-to-context mapping from
            :func:`build_production_contexts`, loaded by the real production
            DataFrame loader from the SAME generated data the SQL reference uses.
        validator: The reused result comparator.
        backends: DataFrame backends to gate; a backend a query does not
            implement is skipped (not counted as a divergence). Whether a *whole*
            gated backend is unimplemented (which would silently compare nothing)
            is detected separately via :func:`count_executed_cells`.
        reference_row_counts: Optional mutable mapping; when supplied it is
            populated with ``query_id -> reference row count`` as each query's
            SQL reference is fetched. A query whose reference returns 0 rows
            compares empty-vs-empty (every backend trivially "matches"), so it is
            NON-discriminating - :func:`_report` uses these counts to exclude
            vacuous cells from the compared count and to FAIL on an unclassified
            vacuous query. A query whose reference *fails* is not recorded here
            (it has no row count); it surfaces as a ``reference`` divergence
            instead. Default ``None`` keeps behavior unchanged for callers (e.g.
            the fast-lane integration tests) that do not need the vacuity audit.

    Returns:
        One :class:`SurfaceDivergence` per query/backend cell whose DataFrame
        result is not equivalent to the SQL surface (cell label = backend; the
        whole-query reference failure uses cell ``"reference"``).
    """
    from benchbox.core.tpchavoc.validation import ValidationError

    def reference_rows(query_id: Any) -> list[tuple[Any, ...]]:
        rows = fetch_reference_rows(connection, reference_sql(query_id))
        if reference_row_counts is not None:
            reference_row_counts[query_id] = len(rows)
        return rows

    def candidate_cells(
        query_id: Any,
    ) -> Iterable[tuple[str, Callable[[list[tuple[Any, ...]]], None]]]:
        query = dataframe_query(query_id)
        sql = reference_sql(query_id)
        # tie_aware only for truncated top-N queries: a benchmark's own SQL and
        # DataFrame surfaces are independent top-N implementations, so an
        # ORDER BY ... LIMIT N whose ties span the cutoff can keep a different but
        # equally-valid subset of the tied rows. Accept that boundary-tie ambiguity
        # (the deterministic rows must still match exactly) - but ONLY where a
        # LIMIT can actually truncate; a non-LIMIT query is compared strictly so a
        # real divergence in a duplicated last row is never masked.
        tie_aware = _is_truncated_top_n(sql)
        # order_aware whenever the query declares an ORDER BY whose key maps to
        # result-column positions: the comparator then checks the RETURNED order
        # (catching a reversed ORDER BY) instead of full-row-sorting both sides,
        # while still treating each tie group as a multiset (so a legitimate tie
        # reshuffle is not flagged) and the LIMIT boundary as a tie when
        # tie_aware. _order_by_result_key returns None for an unmappable ORDER BY
        # (e.g. ORDER BY a non-projected column), so those fall back to the
        # order-insensitive comparison rather than a silent order-blind "pass".
        order_by = _order_by_result_key(sql)
        order_aware = order_by is not None
        # Boundary-tie probe, computed at most once per query (lazily, on the first
        # backend's reference, then memoized): a trailing LIMIT can leave just ONE
        # row of a final order-key tie visible, which the truncated result alone
        # cannot tell apart from a deterministic unique last row. For an order-aware
        # truncated top-N, learn whether that final key genuinely ties PAST the cutoff
        # so the comparator accepts a single-visible-row boundary swap but still
        # catches a real unique-final-key value bug. Every backend of a query shares
        # the SAME reference, so the extra LIMIT n+1 query runs once, not per backend.
        probe_result: bool | None = None  # None = not yet computed (memo sentinel)

        def final_key_tied(reference: list[tuple[Any, ...]]) -> bool:
            nonlocal probe_result
            if probe_result is None:
                # order_by is not None is load-bearing: it narrows the type for the
                # call below (the runtime guard inside also rejects a falsy key).
                probe_result = bool(
                    tie_aware
                    and order_by is not None
                    and _final_key_tied_beyond_limit(connection, sql, order_by, reference)
                )
            return probe_result

        for backend in backends:
            impl = query.get_impl_for_family(backend)
            if impl is None:
                # The DataFrame surface does not implement this backend; there is
                # nothing to compare. Skip it rather than report a false divergence.
                continue

            def check(
                reference: list[tuple[Any, ...]],
                *,
                impl: Any = impl,
                backend: str = backend,
                query_id: Any = query_id,
                tie_aware: bool = tie_aware,
                order_aware: bool = order_aware,
                order_by: list[int] | None = order_by,
            ) -> None:
                candidate = materialize_rows(impl(contexts[backend]))
                validator.validate_results_exact(
                    reference,
                    candidate,
                    query_id,
                    0,
                    tie_aware=tie_aware,
                    order_aware=order_aware,
                    order_by=order_by,
                    final_key_tied_beyond_limit=final_key_tied(reference),
                )

            yield backend, check

    return find_surface_divergences(
        query_ids,
        reference_rows=reference_rows,
        candidate_cells=candidate_cells,
        validation_error=ValidationError,
        reference_failure_cell="reference",
    )


def count_executed_cells(
    query_ids: Iterable[Any],
    dataframe_query: Callable[[Any], Any],
    backends: tuple[str, ...],
) -> dict[str, int]:
    """Count, per gated backend, how many query cells the DataFrame surface implements.

    The gate skips a (query, backend) cell whose DataFrame surface has no impl,
    because a query may legitimately implement only one backend. But a *whole*
    gated backend implementing zero queries is a registration regression, not a
    legitimate skip: with nothing to compare, the gate would report zero
    divergences and go silently green. :func:`run_gate` fails the gate when any
    gated backend has a count of 0 here.
    """
    coverage = dict.fromkeys(backends, 0)
    for query_id in query_ids:
        query = dataframe_query(query_id)
        for backend in backends:
            if query.get_impl_for_family(backend) is not None:
                coverage[backend] += 1
    return coverage


_PRODUCTION_ADAPTERS: dict[str, str] = {
    "expression": "benchbox.platforms.dataframe.polars_df:PolarsDataFrameAdapter",
    "pandas": "benchbox.platforms.dataframe.pandas_df:PandasDataFrameAdapter",
}


def build_production_contexts(
    benchmark: Any,
    data_dir: Path,
    *,
    backends: tuple[str, ...] = DATAFRAME_BACKENDS,
    scale_factor: float = EQUIVALENCE_SCALE,
) -> dict[str, Any]:
    """Load the benchmark's generated data into each backend's DataFrame context.

    Unlike the DuckDB->Arrow materialization, this drives the REAL production
    loader (``adapter.load_benchmark_into_context``), so each backend sees the
    same data path - and the same dtypes - a production DataFrame run would. The
    files were generated by the benchmark's ``build`` function into ``data_dir``,
    the same files the DuckDB SQL reference loaded, so both surfaces still read
    one bounded cell of identical data.
    """
    import importlib

    contexts: dict[str, Any] = {}
    for backend in backends:
        target = _PRODUCTION_ADAPTERS.get(backend)
        if target is None:
            raise ValueError(f"No production DataFrame adapter registered for backend {backend!r}")
        module_name, _, class_name = target.partition(":")
        adapter_cls = getattr(importlib.import_module(module_name), class_name)
        adapter = adapter_cls()
        contexts[backend] = adapter.load_benchmark_into_context(benchmark, Path(data_dir), scale_factor=scale_factor)
    return contexts


# Q18 is `SELECT UserID, SearchPhrase, COUNT(*) ... GROUP BY ... LIMIT 10` with NO
# ORDER BY: at SF=0.1 the GROUP BY yields ~97k groups and the bare LIMIT keeps an
# arbitrary 10, so the SQL and DataFrame surfaces each return a different - but
# equally valid - subset (verified: both are subsets of the full grouped result).
# There is no total order to make this deterministic, so it is a genuinely
# tie-ambiguous query, classified here (the last-resort option) rather than masked:
# the tie-aware comparator handles every ORDER BY ... LIMIT case, only this
# order-less LIMIT needs a baseline entry.
_CLICKBENCH_TIE_AMBIGUOUS_REASON = (
    "Q18 is LIMIT 10 with no ORDER BY over ~97k groups - an arbitrary, order-less top-N selection"
)


def _is_clickbench_q18_arbitrary_topn(divergence: SurfaceDivergence) -> bool:
    """Classify only the documented arbitrary-row mismatch, not execution errors."""
    return "Value mismatch" in str(divergence.detail)


_CLICKBENCH_TIE_AMBIGUOUS = ClassifiedDivergence(
    reason=_CLICKBENCH_TIE_AMBIGUOUS_REASON,
    accepts=_is_clickbench_q18_arbitrary_topn,
    requires_live_divergence=False,
    # Worked example of the optional review_by waiver policy (see the module
    # docstring's "waiver review policy" section): this waiver's divergence is
    # structural (no ORDER BY over ~97k groups) and will never resolve on its
    # own, so `requires_live_divergence=False` above means the `resolved` check
    # can never force a re-look either - review_by is the only forcing function
    # that will. 6 months out from when this was added (2026-07-03).
    review_by=date(2027, 1, 3),
)

# Two AMPLab queries return 0 reference rows at the bounded cell. Both end in a
# `GROUP BY ... HAVING COUNT(*) > 10` over a heavily pre-filtered uservisits set,
# and at SF=0.1 no surviving group reaches that per-group threshold (the filtered
# rows fan out across too many distinct grouping keys), so SQL and DataFrame both
# return 0 rows for data-density reasons, not a logic bug:
#   * Q3 filters a 3-day visitDate window AND searchWord LIKE '%database%' then
#     groups by the high-cardinality sourceIP - no single source IP visits >10
#     times in that narrow window (verified still empty at SF=1.0; raising SF
#     scales sourceIP cardinality in step, so it does not cross the threshold).
#   * Q5 joins uservisits to rankings on pageRank>1000 (only ~111 qualifying
#     ranking rows at SF=0.1) then groups by countryCode HAVING COUNT(*)>10 - the
#     join survivors do not reach 10 per country at the bounded cell.
# Making these discriminating would require a much larger (un-bounded) cell, which
# the one-cell-per-benchmark cost model forbids; they are classified (not silently
# passed) so the vacuity guard fails loudly if either becomes one-sided.
_AMPLAB_VACUOUS_Q3 = (
    "0 reference rows at the bounded cell (still empty at SF=1.0): GROUP BY sourceIP "
    "HAVING COUNT(*)>10 over a 3-day visitDate window AND searchWord LIKE '%database%' "
    "- no source IP reaches >10 visits in that narrow slice; data density, not a bug."
)
_AMPLAB_VACUOUS_Q5 = (
    "0 reference rows at the bounded SF=0.1 cell: JOIN rankings ON pageRank>1000 "
    "(~111 qualifying rows) then GROUP BY countryCode HAVING COUNT(*)>10 - the join "
    "survivors do not reach 10 per country at the bounded cell; data density, not a bug."
)
_AMPLAB_LEGITIMATELY_EMPTY: dict[Any, str] = {"3": _AMPLAB_VACUOUS_Q3, "5": _AMPLAB_VACUOUS_Q5}

# Eight canonical ClickBench queries return 0 reference rows at SF=0.1. ClickBench's
# SQL keeps the UPSTREAM ClickBench literals (specific UserID/RefererHash/URLHash
# values, CounterID=62, the July-2013 EventDate window) and HAVING/OFFSET cutoffs
# tuned for the full ~100M-row upstream dataset; the BenchBox synthetic generator
# emits different ids/dates at 100k rows, so these select nothing on EITHER surface:
#   * Q20 (UserID = <specific 18-digit literal>), Q41/Q42 (RefererHash/URLHash =
#     specific literals) - the exact id never occurs in the synthetic 100k rows.
#   * Q28/Q29 (HAVING COUNT(*) > 100000) - impossible when the whole table is 100k
#     rows at SF=0.1, so no group can exceed the threshold.
#   * Q23 (Title LIKE '%Google%' AND URL NOT LIKE '%.google.%' AND SearchPhrase<>'')
#     - the combined upstream-text filters match nothing in the synthetic text.
#   * Q39/Q40 (CounterID=62 + July-2013 window + LIMIT 10 OFFSET 1000) - the
#     filtered slice has fewer than 1000 grouped rows, so the OFFSET skips them all.
# These are upstream-literal/threshold artifacts, not load or logic bugs, and cannot
# be made discriminating without either the full upstream dataset (un-bounded) or
# changing ClickBench's canonical queries (forbidden). Classified so the guard still
# fails loudly if any becomes one-sided.
_CLICKBENCH_VACUOUS = (
    "0 reference rows at the bounded SF=0.1 (100k-row) cell: the canonical ClickBench "
    "query keeps an UPSTREAM literal/threshold (a specific UserID/RefererHash/URLHash, "
    "CounterID=62 + the July-2013 EventDate window, HAVING COUNT(*)>100000, or a "
    "LIMIT...OFFSET past the filtered slice) tuned for the ~100M-row upstream dataset; "
    "the synthetic 100k-row generator emits different ids/dates so the filter selects "
    "nothing on either surface. Data/literal artifact, not a load or logic bug. "
    "Tracked: a larger discriminating cell or upstream-faithful literals (do NOT change "
    "the canonical ClickBench query)."
)
_CLICKBENCH_LEGITIMATELY_EMPTY: dict[Any, str] = dict.fromkeys(
    ("Q20", "Q23", "Q28", "Q29", "Q39", "Q40", "Q41", "Q42"), _CLICKBENCH_VACUOUS
)

# H2O-DB bounded-cell scale. Its generator base is the 10M-row small tier, so the
# shared EQUIVALENCE_SCALE (0.1) would emit ~1M rows; 0.01 gives a ~100k-row cell
# (comparable to ClickBench's SF=0.1 cell) that is cheap yet keeps every H2O-DB
# query discriminating (see build_h2odb_duckdb for the per-query argument).
_H2ODB_SCALE = 0.01

# H2O-DB Q9 is the only classified cell: it computes PERCENTILE_CONT(0.5, 0.9) of
# fare_amount, a DECIMAL(8,2) column. DuckDB's PERCENTILE_CONT over a DECIMAL
# column returns a DECIMAL of the SAME scale (verified: typeof(...) == DECIMAL(8,2)),
# so the continuous (linear-interpolated) percentile is rounded to 2 decimals on
# the SQL surface (e.g. p90 of the passenger_count=4 group = 77.87). The DataFrame
# surface loads fare_amount as float64 (the loader maps DECIMAL -> float) and
# computes the SAME linear-interpolated percentile, keeping full precision (77.874).
# This is NOT a logic or interpolation-method bug: both DataFrame backends use
# linear interpolation and agree with EACH OTHER to full precision, and casting the
# SQL argument to DOUBLE (PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY
# fare_amount::DOUBLE)) yields 77.874 too - proving the only difference is DuckDB's
# DECIMAL(8,2) result scale. The sub-cent gap (<= 0.005, the 3rd decimal of a
# 2-decimal currency) cannot be reproduced faithfully in float (DuckDB's DECIMAL
# rounding is not standard float round-half-away: the passenger_count=5 group rounds
# 77.915 -> 77.91, not 77.92). It is classified here - the last-resort option, with
# justification - rather than masked or papered over with a fragile per-query
# round(). The polars backend originally defaulted to "nearest" interpolation (a
# REAL divergence: it disagreed with both pandas and SQL) and was FIXED to linear in
# the same change; only this DECIMAL-scale residue is classified. Q9's median column
# (0.5) matches exactly on both surfaces; only the p90 column carries the residue.
_H2ODB_PERCENTILE_DECIMAL = (
    "PERCENTILE_CONT over the DECIMAL(8,2) fare_amount column returns a DECIMAL(8,2) "
    "on the SQL surface (continuous percentile rounded to the column's 2-decimal "
    "scale), while the DataFrame surface computes the same linear-interpolated "
    "percentile over float64 (DECIMAL->float at load) and keeps full precision. Both "
    "DataFrame backends use linear interpolation and agree; casting the SQL to DOUBLE "
    "yields the DataFrame value, so the only difference is DuckDB's DECIMAL result "
    "scale - a deterministic, sub-cent presentational/dtype difference, not a logic bug."
)
# Detail-aware acceptance for the Q9 residue. The documented exception is ONLY the
# p90 PERCENTILE_CONT DECIMAL(8,2) scale residue: a SINGLE value, sub-half-cent,
# living in the p90 output column. Q9's projection is
#   col 0 = passenger_count (grouping key),
#   col 1 = median_fare_amount (PERCENTILE_CONT(0.5)),
#   col 2 = p90_fare_amount    (PERCENTILE_CONT(0.9)),
# and the validator reports a divergence as the FIRST positional mismatch
# ("Value mismatch at row {i}, column {j}. Original: {orig}, Variant: {variant}").
# So the predicate is sound only if it pins the difference to the EXACT documented
# cell and signature, not merely "the first value is sub-cent":
#   * it must be a Value mismatch (NOT a row/column-count mismatch, an execution
#     error, or a reference failure - those detail strings do not match and are
#     rejected);
#   * it must be in column 2 (the p90 column). A grouping-key (col 0) or median
#     (col 1) mismatch - even a sub-cent one - is REJECTED, so a wrong median or a
#     wrong group no longer slips through on a small numeric delta;
#   * both values must be numeric and differ by at most half a cent (the
#     DECIMAL(8,2) rounding bound, with a hair of float-formatting slack - still
#     far below a full cent), so any >=1-cent value bug is rejected; and
#   * the SQL (Original) value must already be at the column's 2-decimal scale and
#     the DataFrame (Variant) value must differ only beyond that scale - the actual
#     DECIMAL-rounding signature - so an arbitrary "both happen to be close" pair
#     does not qualify.
# A wrong median, a wrong grouping key, a row/column-count mismatch, an execution
# error, or any larger value bug (e.g. an interpolation-method regression) fails one
# of these checks, so Q9 stays guarded against real result regressions instead of the
# bare key tolerating every Q9 difference.
#
# Residual blind spot (validator-imposed, documented): the validator reports only the
# FIRST positional mismatch, so a SECOND, later Q9 bug behind an accepted p90 residue
# cannot be seen from the detail string alone. Pinning the accepted cell to the exact
# p90 column + sub-half-cent + 2-decimal-scale signature minimizes the surface of that
# blind spot (only the documented cell is ever the "first" accepted mismatch); closing
# it fully would require the validator to surface ALL mismatches, not one.
_H2ODB_Q9_P90_COLUMN = 2
_H2ODB_Q9_RESIDUE_MAX = 0.005 + 1e-6
_VALUE_MISMATCH_RE = re.compile(
    r"Value mismatch at row \d+, column (?P<col>\d+)\. Original:\s*(?P<orig>.+?),\s*Variant:\s*(?P<variant>.+)$"
)
_NUMBER_RE = re.compile(r"[-+]?\d*\.\d+|[-+]?\d+")


def _first_number(text: str) -> float | None:
    match = _NUMBER_RE.search(text)
    return float(match.group()) if match else None


def _is_two_decimal_scale(value: str) -> bool:
    """True if ``value`` is a plain decimal already rounded to <= 2 fractional digits.

    The SQL (Original) side of the documented residue is a DECIMAL(8,2), so it never
    carries a 3rd fractional digit; the DataFrame (Variant) side keeps full float
    precision. Requiring the Original to be at 2-decimal scale pins the difference to
    DuckDB's DECIMAL-scale rounding rather than an arbitrary near-equal pair.
    """
    number = _NUMBER_RE.search(value)
    if number is None:
        return False
    _, _, frac = number.group().partition(".")
    return len(frac) <= 2


def _h2odb_q9_decimal_residue(divergence: SurfaceDivergence) -> bool:
    """True iff a Q9 divergence is the documented sub-cent p90 DECIMAL-scale residue.

    Pins the accepted difference to the EXACT documented cell (the p90 column, a
    single sub-half-cent value at the SQL column's 2-decimal scale) so a wrong
    median, a wrong grouping key, a structural mismatch, an execution error, or any
    >=1-cent value bug is rejected rather than tolerated.
    """
    match = _VALUE_MISMATCH_RE.search(str(divergence.detail))
    if match is None:
        return False
    # Only the p90 column (index 2) carries the documented residue; a grouping-key
    # or median mismatch - sub-cent or not - is a real Q9 regression.
    if int(match.group("col")) != _H2ODB_Q9_P90_COLUMN:
        return False
    orig_text = match.group("orig")
    variant_text = match.group("variant")
    orig = _first_number(orig_text)
    variant = _first_number(variant_text)
    if orig is None or variant is None:
        return False
    # The SQL value must already be at DECIMAL(8,2) scale (the rounding signature);
    # the DataFrame value differs only beyond that scale, sub-half-cent.
    if not _is_two_decimal_scale(orig_text):
        return False
    return abs(orig - variant) <= _H2ODB_Q9_RESIDUE_MAX


_H2ODB_KNOWN_DIVERGENCES: dict[str, str | ClassifiedDivergence] = {
    **_KNOWN_DIVERGENCES_BASELINE.get("h2odb", {}),
    **dict.fromkeys(
        ("Q9_expression", "Q9_pandas"),
        ClassifiedDivergence(_H2ODB_PERCENTILE_DECIMAL, _h2odb_q9_decimal_residue),
    ),
}


# Read Primitives classified cells. As a *primitives* benchmark it deliberately
# exercises engine features that have no faithful exact DataFrame equivalent:
# approximate sketches, DECIMAL-scale arithmetic, JSON text, and a Polars Map gap.
# Each is the last-resort classification (with rationale), not a masked defect.
# Every waiver below is a ClassifiedDivergence (not a bare string): a predicate
# pins the accepted divergence to its documented signature (column position,
# numeric bound, or execution-error text), mirroring _h2odb_q9_decimal_residue
# and _is_clickbench_q18_arbitrary_topn, so a genuinely wrong value on the same
# key is still reported as an unclassified gate failure.
_READ_PRIMITIVES_APPROX = (
    "DuckDB APPROX_COUNT_DISTINCT (HyperLogLog) and APPROX_QUANTILE (T-Digest) are "
    "inherently approximate sketches; the DataFrame computes the exact distinct "
    "count / quantile, so the values differ by the sketch's error - approximate by "
    "construction, not a logic divergence."
)
# Sketch-error bound. DuckDB's APPROX_COUNT_DISTINCT uses HyperLogLog at its
# default (12-bit, ~4096-register) precision, nominally ~2% relative standard
# error at large cardinalities; APPROX_QUANTILE's T-Digest has a small error near
# the middle of the distribution. Per-group cardinalities in this benchmark's
# bounded SF=0.05 cell are far smaller than a full-table HLL estimate (tens of
# thousands, split across a 2-column GROUP BY), which pushes the empirical
# residue toward the tail of that error distribution - measured at this cell:
#   approx_count_distinct_simple:    4969 vs 5210 (4.6%), 4990 vs 5210 (4.2%)
#   approx_count_distinct_groupby:  32458 vs 36069 (10.0%), 32235 vs 36069 (10.6%)
#   approx_quantile_groupby:          25.0 vs 26 (3.8%)
# Bounded at 15% - about 1.4x the largest observed residue, comfortably wide
# enough to absorb engine-version HLL/T-Digest implementation drift while still
# rejecting a sketch off by an order of magnitude (a broken sketch merge), per
# the mutation probe in tests/unit/core/equivalence/.
_READ_PRIMITIVES_SKETCH_RELATIVE_ERROR_MAX = 0.15
# Query-id substring -> result-column indices where the sketch value lives. The
# grouping-key columns (l_returnflag/l_linestatus/l_shipmode) are deliberately
# absent, so a wrong grouping key is still rejected as an unclassified mismatch.
_READ_PRIMITIVES_SKETCH_COLUMNS: dict[str, tuple[int, ...]] = {
    "approx_count_distinct_simple": (0,),
    "approx_count_distinct_groupby": (2, 3),
    "approx_quantile_groupby": (1,),
}


def _read_primitives_sketch_residue(divergence: SurfaceDivergence) -> bool:
    """Accept only a bounded-relative-error sketch value in its documented column.

    Rejects a row/column-count mismatch, an execution error, a grouping-key
    mismatch, or a numeric difference beyond
    :data:`_READ_PRIMITIVES_SKETCH_RELATIVE_ERROR_MAX`, so a broken sketch merge
    (or an off-by-a-large-factor regression) is still reported as unclassified.
    """
    match = _VALUE_MISMATCH_RE.search(str(divergence.detail))
    if match is None:
        return False
    query_id = str(divergence.query_id)
    allowed_columns = next(
        (columns for name, columns in _READ_PRIMITIVES_SKETCH_COLUMNS.items() if name in query_id),
        None,
    )
    if allowed_columns is None or int(match.group("col")) not in allowed_columns:
        return False
    orig = _first_number(match.group("orig"))
    variant = _first_number(match.group("variant"))
    if orig is None or variant is None:
        return False
    denominator = abs(orig) if orig != 0 else abs(variant)
    if denominator == 0:
        return orig == variant
    return abs(orig - variant) / denominator <= _READ_PRIMITIVES_SKETCH_RELATIVE_ERROR_MAX


_READ_PRIMITIVES_DECIMAL_PERCENTILE = (
    "PERCENTILE_CONT over DECIMAL(15,2) returns a 2-decimal value on the SQL surface; "
    "the DataFrame interpolates in float64. Both use linear interpolation - only the "
    "DECIMAL result scale differs (sub-cent), the same presentational class as h2odb Q9."
)
_READ_PRIMITIVES_DECIMAL_ROUND = (
    "ROUND() of a DECIMAL revenue (DuckDB, exact) vs the same product computed in "
    "float64 (DataFrame) flips at a half-cent rounding boundary; a DECIMAL-vs-float "
    "presentational residue (every other column matches), not a logic divergence."
)
# Both bounds share _h2odb_q9_decimal_residue's derivation (a DECIMAL-scale
# rounding residue pinned to one documented output column), applied to two
# different read_primitives arithmetic paths with different maximum residues -
# do not copy h2odb's constant blind, each is re-derived from this benchmark's
# own measured cell:
#   * statistical_percentiles' p95 column is a DECIMAL(15,2) PERCENTILE_CONT
#     result (same shape as h2odb Q9): the residue is bounded by half the
#     column's 0.01 unit (measured: 74356.28 vs 74356.28399999996, a 0.004 gap).
#   * optimizer_common_subexpression's rounded_revenue is DuckDB's ROUND() of a
#     DECIMAL product vs Python/NumPy rounding of the same product in float64;
#     the two rounding rules can flip a FULL cent at a half-cent boundary, not
#     just sub-cent (measured: 4721058.05 vs 4721058.04, exactly a 0.01 gap).
_READ_PRIMITIVES_PERCENTILE_P95_COLUMN = 6
_READ_PRIMITIVES_PERCENTILE_RESIDUE_MAX = 0.005 + 1e-6
_READ_PRIMITIVES_ROUND_COLUMN = 6
_READ_PRIMITIVES_ROUND_RESIDUE_MAX = 0.01 + 1e-6


def _read_primitives_decimal_scale_residue(divergence: SurfaceDivergence, *, column: int, max_residue: float) -> bool:
    """Shared DECIMAL(<=2)-scale residue check, pinned to one column and bound.

    Mirrors :func:`_h2odb_q9_decimal_residue`: the SQL (Original) side must
    already be at <=2-decimal scale (the rounding signature) and the numeric gap
    must be within ``max_residue`` - a wrong value, a wrong column, or a
    structural mismatch (row/column count, execution error) is rejected.
    """
    match = _VALUE_MISMATCH_RE.search(str(divergence.detail))
    if match is None:
        return False
    if int(match.group("col")) != column:
        return False
    orig_text = match.group("orig")
    orig = _first_number(orig_text)
    variant = _first_number(match.group("variant"))
    if orig is None or variant is None:
        return False
    if not _is_two_decimal_scale(orig_text):
        return False
    return abs(orig - variant) <= max_residue


def _read_primitives_percentile_decimal_residue(divergence: SurfaceDivergence) -> bool:
    """Accept only statistical_percentiles' p95 DECIMAL(15,2)-scale residue (column 6)."""
    return _read_primitives_decimal_scale_residue(
        divergence,
        column=_READ_PRIMITIVES_PERCENTILE_P95_COLUMN,
        max_residue=_READ_PRIMITIVES_PERCENTILE_RESIDUE_MAX,
    )


def _read_primitives_round_decimal_residue(divergence: SurfaceDivergence) -> bool:
    """Accept only optimizer_common_subexpression's ROUND() half-cent flip (column 6)."""
    return _read_primitives_decimal_scale_residue(
        divergence,
        column=_READ_PRIMITIVES_ROUND_COLUMN,
        max_residue=_READ_PRIMITIVES_ROUND_RESIDUE_MAX,
    )


_READ_PRIMITIVES_ARGMIN_TIE = (
    "ARG_MIN(p_name, p_retailprice) is non-deterministic when several parts in a brand "
    "share the minimum retail price; DuckDB's tie pick is engine-defined and not "
    "reproducible by a fixed DataFrame tie-break (the min_price value matches exactly)."
)
# min_by_complex's projection is [p_brand(0), cheapest_part_name(1),
# cheapest_part_type(2), min_price(3)]; only the two ARG_MIN-tie-broken columns
# may differ. A p_brand (grouping key) or min_price mismatch - even a numerically
# close one - is a real regression and is rejected.
#
# Residual blind spot (validator-imposed, the same shape as h2odb Q9's
# documented one): the comparator reports only the FIRST positional mismatch per
# row, so if cheapest_part_name (column 1) differs AND min_price (column 3) is
# ALSO wrong on the same row, only the accepted column-1 tie-break is visible
# here. Pinning to columns 1-2 only (never 0 or 3) minimizes, but cannot fully
# close, that blind spot; closing it fully would require the validator to
# surface every mismatch per row, not just the first.
_READ_PRIMITIVES_ARGMIN_TIE_COLUMNS = (1, 2)


def _read_primitives_argmin_tie(divergence: SurfaceDivergence) -> bool:
    """Accept only a tie-broken name/type column mismatch, never the brand key or price."""
    match = _VALUE_MISMATCH_RE.search(str(divergence.detail))
    if match is None:
        return False
    return int(match.group("col")) in _READ_PRIMITIVES_ARGMIN_TIE_COLUMNS


_READ_PRIMITIVES_JSON_TEXT = (
    "JSON_GROUP_ARRAY/JSON_GROUP_OBJECT return JSON *text* with engine-defined element/"
    "key order and number formatting; the DataFrame produces native list/dict "
    "containers. Representational difference, not a logic divergence."
)
# json_aggregates' two gated cells diverge in TWO different observed shapes, both
# accepted here by structural (not textual) equivalence rather than a blanket
# "match this label":
#   * json_aggregates_pandas: a "Value mismatch" on column 1 (part_names, a
#     JSON_GROUP_ARRAY) or column 2 (part_prices, a JSON_GROUP_OBJECT) - the SQL
#     side is JSON *text*, the DataFrame side a native list/dict. Parse both and
#     compare structurally (order-insensitive, number-format-insensitive); a
#     missing/added/wrong element compares unequal and is rejected.
#   * json_aggregates_expression: an "ORDER BY key mismatch" on the p_brand
#     grouping column - verified (via a diagnostic probe of the built cell) that
#     the Polars expression aggregate returns all 25 TPC-H p_brand values, the
#     SAME set the SQL reference returns, in an engine-arbitrary (unsorted)
#     order; it is not a missing/extra group. Accept a reordering only when BOTH
#     reported keys are members of TPC-H's fixed 25-value p_brand domain, so a
#     genuinely wrong grouping key (a value outside that domain) - or a group
#     COUNT mismatch, which the validator reports as a different message and this
#     predicate does not match - is still rejected as an unclassified mismatch.
_READ_PRIMITIVES_BRAND_DOMAIN = frozenset(f"Brand#{m}{n}" for m in range(1, 6) for n in range(1, 6))
_ORDER_KEY_MISMATCH_RE = re.compile(
    r"Original key:\s*\('(?P<orig>[^']*)',\),\s*Variant key:\s*\('(?P<variant>[^']*)',\)"
)


def _read_primitives_json_parse(text: str) -> Any:
    """Parse a JSON-text or Python-repr container into a comparable Python value."""
    import ast
    import json

    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return ast.literal_eval(text)


def _read_primitives_json_equivalent(original: str, variant: str) -> bool:
    """True if two JSON-text/native-container reprs hold the same content.

    Order-insensitive (JSON_GROUP_ARRAY element order and dict key order are
    engine-defined) and number-format-insensitive (DECIMAL text vs float); a
    genuinely missing/added/wrong element or value still compares unequal.
    """

    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return sorted((normalize(item) for item in value), key=str)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return round(float(value), 2)
        return value

    try:
        return normalize(_read_primitives_json_parse(original)) == normalize(_read_primitives_json_parse(variant))
    except (ValueError, SyntaxError):
        return False


def _read_primitives_json_agg_accepts(divergence: SurfaceDivergence) -> bool:
    """Accept the documented JSON-text-vs-container shape, structurally verified."""
    detail = str(divergence.detail)
    order_match = _ORDER_KEY_MISMATCH_RE.search(detail)
    if order_match is not None:
        return (
            order_match.group("orig") in _READ_PRIMITIVES_BRAND_DOMAIN
            and order_match.group("variant") in _READ_PRIMITIVES_BRAND_DOMAIN
        )
    value_match = _VALUE_MISMATCH_RE.search(detail)
    if value_match is None:
        return False
    if int(value_match.group("col")) not in (1, 2):
        return False
    return _read_primitives_json_equivalent(value_match.group("orig"), value_match.group("variant"))


_READ_PRIMITIVES_POLARS_MAP = (
    "Polars (the expression backend) has no native Map dtype, so MAP_FROM_ENTRIES is "
    "unsupported (the query is in the benchmark's SKIP_FOR_POLARS set); there is no "
    "expression-surface result to compare. The pandas surface matches its SQL."
)
# Confirmed (TODO w5): only the three "_expression" cells ever reach
# known_divergences - the pandas cells are never classified here because pandas
# supports dict natively and matches its SQL cleanly (no pandas key is declared
# above, so a pandas divergence on these queries would surface as unclassified,
# which is intended). Accept ONLY the documented "no native Map dtype" execution
# error text (both raise sites use it verbatim - expression_family.py's
# map_from_entries and unified_frame.py's Map accessors); a DIFFERENT execution
# error, or a Value mismatch (Polars started supporting Map but produced a wrong
# value), is rejected as unclassified.
_READ_PRIMITIVES_POLARS_MAP_ERROR_SIGNATURE = "not supported on Polars (no native Map dtype)"


def _read_primitives_polars_map_gap(divergence: SurfaceDivergence) -> bool:
    """Accept only the documented Polars Map-dtype execution gap, nothing else."""
    detail = str(divergence.detail)
    return detail.startswith("error: ") and detail.endswith(_READ_PRIMITIVES_POLARS_MAP_ERROR_SIGNATURE)


# Read Primitives bounded-cell scale. Its TPC-H generator base means SF=1.0 is
# ~6M lineitem rows; SF=0.05 gives a ~300k-row cell that keeps the selective
# filter/aggregate queries discriminating while staying a single bounded cell.
_READ_PRIMITIVES_SCALE = 0.05

_READ_PRIMITIVES_KNOWN_DIVERGENCES: dict[str, str | ClassifiedDivergence] = {
    **_KNOWN_DIVERGENCES_BASELINE.get("read_primitives", {}),
    **dict.fromkeys(
        (
            "approx_count_distinct_simple_expression",
            "approx_count_distinct_simple_pandas",
            "approx_count_distinct_groupby_expression",
            "approx_count_distinct_groupby_pandas",
            "approx_quantile_groupby_expression",
            "approx_quantile_groupby_pandas",
        ),
        ClassifiedDivergence(_READ_PRIMITIVES_APPROX, _read_primitives_sketch_residue),
    ),
    **dict.fromkeys(
        ("statistical_percentiles_expression", "statistical_percentiles_pandas"),
        ClassifiedDivergence(_READ_PRIMITIVES_DECIMAL_PERCENTILE, _read_primitives_percentile_decimal_residue),
    ),
    **dict.fromkeys(
        ("optimizer_common_subexpression_expression", "optimizer_common_subexpression_pandas"),
        ClassifiedDivergence(_READ_PRIMITIVES_DECIMAL_ROUND, _read_primitives_round_decimal_residue),
    ),
    **dict.fromkeys(
        ("min_by_complex_expression", "min_by_complex_pandas"),
        ClassifiedDivergence(_READ_PRIMITIVES_ARGMIN_TIE, _read_primitives_argmin_tie),
    ),
    **dict.fromkeys(
        ("json_aggregates_expression", "json_aggregates_pandas"),
        ClassifiedDivergence(_READ_PRIMITIVES_JSON_TEXT, _read_primitives_json_agg_accepts),
    ),
    **dict.fromkeys(
        ("map_access_expression", "map_construction_expression", "map_keys_values_expression"),
        ClassifiedDivergence(_READ_PRIMITIVES_POLARS_MAP, _read_primitives_polars_map_gap),
    ),
}
_READ_PRIMITIVES_LEGITIMATELY_EMPTY: dict[Any, str] = {
    **dict.fromkeys(
        ("filter_bigint_selective", "filter_decimal_selective", "filter_decimal_in_list_selective"),
        "Highly selective exact-match filter whose literal does not occur in the bounded "
        "SF=0.05 cell (an orderkey outside the generated range, or an exact DECIMAL price "
        "that the generator never produces), so the SQL reference is empty.",
    ),
    "json_extract_nested": (
        "TPC-H c_comment is free natural-language text, never valid JSON, so "
        "WHERE JSON_VALID(c_comment) matches nothing at any scale - the benchmark has no "
        "JSON source data. The DataFrame surface mirrors the empty result."
    ),
}


# Registry of ENFORCED gated benchmarks: clean, blocking cross-surface gates whose
# DataFrame surface matches its SQL surface. The oracle coverage map reads this set
# to classify a benchmark as cross-surface "guarded", so only clean+enforced gates
# belong here (registering a red gate here would be coverage theater).
GATES: dict[str, CrossSurfaceGate] = {
    "ssb": CrossSurfaceGate(
        name="ssb",
        build=build_ssb_duckdb,
        surface_independence=SURFACE_INDEPENDENCE_SHARED_SPEC,
        surface_independence_rationale=(
            "Both DataFrame backends are generated from compact SSB query metadata; the independent "
            "signal is SQL text versus the shared generated DataFrame spec."
        ),
    ),
    "amplab": CrossSurfaceGate(
        name="amplab",
        build=build_amplab_duckdb,
        legitimately_empty=_AMPLAB_LEGITIMATELY_EMPTY,
        surface_independence=SURFACE_INDEPENDENCE_SEPARATE,
        surface_independence_rationale=(
            "Expression and pandas DataFrame implementations are separately handwritten for each query, "
            "so the gate has stronger cross-implementation signal than shared-spec generators."
        ),
    ),
    "coffeeshop": CrossSurfaceGate(
        name="coffeeshop",
        build=build_coffeeshop_duckdb,
        surface_independence=SURFACE_INDEPENDENCE_SEPARATE,
        surface_independence_rationale=(
            "Expression and pandas DataFrame implementations are separately handwritten for each query, "
            "so the gate has stronger cross-implementation signal than shared-spec generators."
        ),
    ),
    # Promoted from STAGED_GATES once the two cross-cutting prerequisites landed:
    # w9 (loader applies schema column TYPES + DuckDB empty-string semantics) made
    # joinorder_synthetic 26/26 and cleared ClickBench Q17/Q24; w8 (tie-aware
    # comparator) cleared ORDER BY ... LIMIT top-N cells. ClickBench's residual
    # order-less Q18 baselines may line up by chance on a run, so they are not
    # stale merely because one execution happens to compare equal.
    "clickbench": CrossSurfaceGate(
        name="clickbench",
        build=build_clickbench_duckdb,
        known_divergences={
            **_KNOWN_DIVERGENCES_BASELINE.get("clickbench", {}),
            "Q18_expression": _CLICKBENCH_TIE_AMBIGUOUS,
            "Q18_pandas": _CLICKBENCH_TIE_AMBIGUOUS,
        },
        legitimately_empty=_CLICKBENCH_LEGITIMATELY_EMPTY,
        surface_independence=SURFACE_INDEPENDENCE_MIXED,
        surface_independence_rationale=(
            "Most ClickBench DataFrame cells are generated from shared compact specs, with a small set "
            "of bespoke implementations; read as mixed provenance, not fully independent implementations."
        ),
    ),
    "joinorder_synthetic": CrossSurfaceGate(
        name="joinorder_synthetic",
        build=build_joinorder_synthetic_duckdb,
        surface_independence=SURFACE_INDEPENDENCE_SHARED_SPEC,
        surface_independence_rationale=(
            "Both DataFrame families are generated through shared JoinOrder translation helpers, so the "
            "gate primarily catches SQL-vs-generated-DataFrame transcription drift."
        ),
    ),
    # H2O-DB's generator base is the published 10M-row small tier, so the shared
    # EQUIVALENCE_SCALE (0.1) would generate ~1M rows - far from a cheap bounded
    # cell. Run this gate on a smaller cell (~100k rows, comparable to ClickBench's
    # SF=0.1 100k-row cell) where every H2O-DB query is still fully discriminating.
    "h2odb": CrossSurfaceGate(
        name="h2odb",
        build=build_h2odb_duckdb,
        known_divergences=_H2ODB_KNOWN_DIVERGENCES,
        surface_independence=SURFACE_INDEPENDENCE_SEPARATE,
        surface_independence_rationale=(
            "H2O-DB expression and pandas DataFrame implementations are separately handwritten for each query."
        ),
        scale_factor=_H2ODB_SCALE,
    ),
    # Read Primitives: a 152-query DataFrame surface vs its DuckDB-dialect SQL
    # surface on a bounded ~300k-row TPC-H cell (SF=0.05). 148 gateable queries (the
    # 4 fulltext/json ids DuckDB cannot transpile are excluded in the builder); every
    # compared cell matches. The classified cells are the irreducible engine
    # differences a primitives benchmark exercises - HyperLogLog/T-Digest
    # approximations, DECIMAL-scale percentile/ROUND residues, ARG_MIN ties, JSON
    # text, and the Polars Map-dtype gap - plus the legitimately-empty selective and
    # no-JSON filters. Promoted from STAGED_GATES after the full burn-down.
    "read_primitives": CrossSurfaceGate(
        name="read_primitives",
        build=build_read_primitives_duckdb,
        known_divergences=_READ_PRIMITIVES_KNOWN_DIVERGENCES,
        legitimately_empty=_READ_PRIMITIVES_LEGITIMATELY_EMPTY,
        # Pandas decodes selected SQL NULL cells as NaN in object/numeric result
        # columns (for example MAP lookup misses and LEAD/LAG frame edges). Keep
        # the global comparator strict; opt in only for this gate's decode path.
        treat_nan_as_null=True,
        surface_independence=SURFACE_INDEPENDENCE_MIXED,
        surface_independence_rationale=(
            "Read Primitives combines explicit family implementations with factory-built/query-catalog "
            "implementations, so provenance is mixed rather than wholly independent."
        ),
        scale_factor=_READ_PRIMITIVES_SCALE,
    ),
}

# Staged gates: a load-faithful builder is wired and runnable in report mode, but
# the benchmark still has open cross-surface divergences to burn down before it can
# be promoted into GATES (and made a blocking CI gate). Kept OUT of GATES so the
# coverage map does not prematurely mark these benchmarks "guarded". Currently empty
# - read_primitives graduated to GATES after its burn-down; the next gateable
# benchmarks (datavault, flightdata, nyctaxi, tpcds_obt, tpch_skew, tsbs_devops)
# land here first when their builders are wired.
STAGED_GATES: dict[str, CrossSurfaceGate] = {}


def get_gate(name: str) -> CrossSurfaceGate:
    """Resolve a gate by name from the enforced or staged registries."""
    if name in GATES:
        return GATES[name]
    return STAGED_GATES[name]


# Filesystem path the ``--update-baseline`` writer edits directly. Reads elsewhere
# in this module go through ``importlib.resources`` (works from an installed
# package); this is a real path because update-baseline is an explicit,
# operator-only local dev tool that edits a tracked source file for the operator
# to review and commit, never something that runs against an installed wheel.
_BASELINE_YAML_PATH = Path(__file__).parent / "cross_surface_baseline.yaml"


def _resolved_baseline_keys(
    known: dict[str, str | ClassifiedDivergence], divergences: list[SurfaceDivergence]
) -> list[str]:
    """Known-divergence keys whose cell now matches (mirrors ``_report``'s own check)."""
    found = {d.key for d in divergences}
    return sorted(key for key, entry in known.items() if key not in found and _requires_live_divergence(entry))


def _apply_baseline_update(
    gate: CrossSurfaceGate,
    divergences: list[SurfaceDivergence],
    total: int,
    coverage: dict[str, int],
    reference_row_counts: dict[Any, int],
    vacuous_cells: int,
) -> int:
    """Drop this gate's resolved known-divergence entries from the YAML baseline,
    but ONLY when the run is otherwise completely clean.

    Explicit, operator-driven affordance behind ``--update-baseline`` for the FAIL
    that #903 added ("remove the stale baseline entry in a reviewed change"). Never
    invoked by a normal blocking gate run.

    Requires a fully clean run before writing anything: the report is computed
    with the resolved keys already excluded from ``known`` (so their own
    stale-baseline failure cannot block this check), and if any OTHER condition
    still fails - an unclassified divergence, a vacuous unclassified query, a
    missing backend - nothing is written at all. An operator hitting an unrelated
    regression on the same run must fix it first, then re-run to prune; a resolved
    entry is never pruned out of a still-failing run, so "baseline maintained"
    can never be mistaken for "run is otherwise clean" when it is not.
    """
    from benchbox.core.equivalence.known_divergences_baseline import update_baseline_file

    resolved = _resolved_baseline_keys(gate.known_divergences, divergences)
    known_after_update = {key: entry for key, entry in gate.known_divergences.items() if key not in resolved}
    exit_code = _report(
        divergences,
        total,
        coverage,
        known_after_update,
        benchmark=gate.name,
        reference_row_counts=reference_row_counts,
        legitimately_empty=gate.legitimately_empty,
        scale_factor=gate.scale_factor,
        vacuous_cells=vacuous_cells,
    )

    if exit_code != 0:
        print(f"{gate.name}: refusing to update baseline - gate reported other failure(s) above; nothing written.")
        return exit_code

    if not resolved:
        print(f"{gate.name}: no resolved known-divergence entries; baseline unchanged.")
        return exit_code

    removed = update_baseline_file(_BASELINE_YAML_PATH, resolved, gate.name)
    if removed:
        print(f"{gate.name}: removed resolved known-divergence baseline entries: {removed}")
    else:
        print(f"{gate.name}: resolved entries {resolved} not in the YAML baseline (code-only entry); unchanged.")
    return exit_code


def run_gate(gate: CrossSurfaceGate, *, update_baseline: bool = False) -> int:
    """Run one benchmark's cross-surface gate and print a categorized report.

    When ``update_baseline`` is set, any resolved known-divergence entries are
    dropped from the YAML baseline (see :func:`_apply_baseline_update`), but ONLY
    if the run is otherwise completely clean; any other gate-failure condition
    (unclassified divergences, vacuous queries, missing backends) still fails the
    command (non-zero exit) with nothing written.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        data = gate.build(gate.scale_factor, Path(tmp))
        connection = data.connection
        reference_row_counts: dict[Any, int] = {}
        try:
            contexts = build_production_contexts(
                data.benchmark, data.data_dir, backends=gate.backends, scale_factor=gate.scale_factor
            )
            divergences = find_cross_surface_divergences(
                connection,
                query_ids=data.query_ids,
                reference_sql=data.reference_sql,
                dataframe_query=data.dataframe_query,
                contexts=contexts,
                validator=gate.build_validator(),
                backends=gate.backends,
                reference_row_counts=reference_row_counts,
            )
            coverage = count_executed_cells(data.query_ids, data.dataframe_query, gate.backends)
            # Count vacuous CELLS exactly (one per backend a vacuous query
            # actually implements), not an estimate: a future gate may implement
            # a query on only one backend, and overstating vacuous cells would be
            # the very coverage theater this guard prevents.
            vacuous_cells = count_executed_cells(
                [qid for qid, n in reference_row_counts.items() if n == 0],
                data.dataframe_query,
                gate.backends,
            )
        finally:
            connection.close()

    total = len(data.query_ids) * len(gate.backends)
    vacuous_cells_total = sum(vacuous_cells.values())

    if update_baseline:
        return _apply_baseline_update(gate, divergences, total, coverage, reference_row_counts, vacuous_cells_total)

    return _report(
        divergences,
        total,
        coverage,
        gate.known_divergences,
        benchmark=gate.name,
        reference_row_counts=reference_row_counts,
        legitimately_empty=gate.legitimately_empty,
        scale_factor=gate.scale_factor,
        vacuous_cells=vacuous_cells_total,
    )


def _classification(known: dict[str, str | ClassifiedDivergence], divergence: SurfaceDivergence) -> str | None:
    """Return the reason a divergence is tolerated, or None if it is unclassified.

    A bare-string baseline entry tolerates ANY divergence on that key (back-compat).
    A :class:`ClassifiedDivergence` entry tolerates the divergence only when its
    ``accepts`` predicate confirms the live cell, so a regression on a baselined key
    is still unclassified.
    """
    entry = known.get(divergence.key)
    if entry is None:
        return None
    if isinstance(entry, ClassifiedDivergence):
        return entry.reason if entry.accepts(divergence) else None
    return entry


def _requires_live_divergence(entry: str | ClassifiedDivergence) -> bool:
    """True if a missing known divergence should fail as a stale baseline."""
    return entry.requires_live_divergence if isinstance(entry, ClassifiedDivergence) else True


def _report(
    divergences: list[SurfaceDivergence],
    total: int,
    coverage: dict[str, int],
    known: dict[str, str | ClassifiedDivergence],
    *,
    benchmark: str,
    reference_row_counts: dict[Any, int] | None = None,
    legitimately_empty: dict[Any, str] | None = None,
    scale_factor: float = EQUIVALENCE_SCALE,
    vacuous_cells: int | None = None,
) -> int:
    """Print a categorized divergence report and return the gate exit code.

    Fails (non-zero) on:
      * any unclassified cross-surface divergence,
      * any gated backend that implemented no queries (which would otherwise make
        the gate silently green by comparing nothing on that backend), and
      * any known divergence whose cell is now equivalent, so stale baselines are
        removed in a reviewed change instead of masking a future regression, and
      * any VACUOUS query - one whose SQL reference returns 0 rows, so every
        backend compares empty-vs-empty and trivially "matches" without
        discriminating anything - UNLESS it is explicitly classified in
        ``legitimately_empty`` with a rationale.

    The "compared N of M cells" line reports DISCRIMINATING cells only: a vacuous
    query's cells are excluded from the discriminating count and reported
    separately, so a report can never present empty-vs-empty passes as coverage.

    Additionally WARNS (never fails the gate) when a :class:`ClassifiedDivergence`
    entry carries a past-due ``review_by`` date - see the module's waiver review
    policy docstring. This is independent of the ``resolved`` stale-baseline
    failure above: ``resolved`` means the divergence is gone (delete the entry);
    a past-due ``review_by`` means the divergence may still be entirely valid but
    a human should re-look (the entry stays, the gate stays green).
    """
    legitimately_empty = legitimately_empty or {}
    reference_row_counts = reference_row_counts or {}

    found = {d.key for d in divergences}
    # A divergence is classified only if its key is baselined AND (for a detail-aware
    # ClassifiedDivergence entry) the live cell matches the entry's predicate, so a
    # real regression on a baselined key is still reported as unclassified.
    new = sorted({d.key for d in divergences if _classification(known, d) is None})
    resolved = sorted(key for key, entry in known.items() if key not in found and _requires_live_divergence(entry))
    missing_backends = sorted(backend for backend, count in coverage.items() if count == 0)
    executed = sum(coverage.values())

    # A DIFFERENT signal from `resolved`: a waiver whose divergence is still LIVE
    # never trips `resolved` on its own, so it can sit correct-when-written but
    # stale-in-spirit indefinitely. An optional `review_by` on a ClassifiedDivergence
    # entry forces periodic re-examination even when the divergence never disappears.
    # WARN only (see the module's waiver review policy docstring) - a past-due date
    # is a prompt to re-look, not proof the waiver is wrong, so it never affects the
    # exit code.
    review_due = sorted(
        key
        for key, entry in known.items()
        if isinstance(entry, ClassifiedDivergence) and entry.review_by is not None and entry.review_by < date.today()
    )

    # A query is vacuous when its reference returned 0 rows; classify each as
    # legitimately-empty (tolerated, with a rationale) or unclassified (a gate
    # failure). Reference-row-count availability is opt-in (run_gate passes it;
    # the fast-lane integration tests do not), so when it is absent every cell is
    # treated as discriminating - the prior behavior is preserved.
    vacuous = sorted(qid for qid, count in reference_row_counts.items() if count == 0)
    classified_empty = [qid for qid in vacuous if qid in legitimately_empty]
    unclassified_empty = [qid for qid in vacuous if qid not in legitimately_empty]

    # Each vacuous query compares one trivially-matching cell per gated backend it
    # implements; exclude those from the discriminating count so coverage is
    # honest. ``run_gate`` passes the EXACT vacuous-cell count (counted per
    # implemented backend via :func:`count_executed_cells`), which stays correct
    # even for a future gate that implements a query on only one backend. When no
    # exact count is supplied (a direct ``_report`` caller such as a unit test),
    # fall back to "one cell per executed backend per vacuous query" - exact for
    # every gated benchmark today (each query implements both backends) and a
    # conservative under-count of discriminating cells otherwise.
    if vacuous_cells is not None:
        vacuous_executed = vacuous_cells
    else:
        implemented_backends = sum(1 for count in coverage.values() if count)
        vacuous_executed = len(vacuous) * implemented_backends if reference_row_counts else 0
    discriminating = max(executed - vacuous_executed, 0)

    print(f"{benchmark} cross-surface SQL<->DataFrame equivalence @ SF={scale_factor} (DuckDB-backed)")
    print(
        f"  compared {discriminating} of {total} query-backend cells "
        f"({total - executed} not implemented by the DataFrame surface, "
        f"{vacuous_executed} vacuous empty-vs-empty) - {len(divergences)} divergent\n"
    )

    by_class: dict[str, list[SurfaceDivergence]] = {}
    for divergence in sorted(divergences, key=lambda d: d.key):
        klass = _classification(known, divergence) or "UNCLASSIFIED"
        by_class.setdefault(klass, []).append(divergence)
    for klass in sorted(by_class):
        print(f"  [{klass}]")
        for divergence in by_class[klass]:
            print(f"    {divergence.key}: {divergence.detail}")
        print()

    if classified_empty:
        print("  [legitimately-empty - classified, NON-discriminating]")
        for qid in classified_empty:
            print(f"    {qid}: {legitimately_empty[qid]}")
        print()

    if missing_backends:
        print(f"GATE FAILURE - gated backend(s) implement no queries (nothing compared): {missing_backends}")
    if new:
        print(f"GATE FAILURE - unclassified cross-surface divergences: {new}")
    if unclassified_empty:
        print(
            "GATE FAILURE - vacuous empty-vs-empty queries (0 reference rows) not classified "
            f"legitimately_empty: {unclassified_empty} - make them discriminating or classify them with a rationale"
        )
    if resolved:
        print(
            "GATE FAILURE - previously-known divergences now equivalent: "
            f"{resolved} - remove the stale baseline entry in a reviewed change"
        )
    if review_due:
        for key in review_due:
            entry = known[key]
            assert isinstance(entry, ClassifiedDivergence)  # narrowed by review_due's filter above
            print(f"WAIVER REVIEW DUE - {key}: review_by {entry.review_by} has passed - {entry.reason}")
    if not new and not resolved and not missing_backends and not unclassified_empty:
        suffix = " (modulo classified exceptions)" if (known or classified_empty) else ""
        print(f"SQL and DataFrame surfaces are equivalent{suffix}.")
    return 1 if (new or resolved or missing_backends or unclassified_empty) else 0


def main(argv: list[str] | None = None) -> int:
    """Run the cross-surface gate for the chosen benchmark."""
    import argparse

    parser = argparse.ArgumentParser(description="Cross-surface SQL<->DataFrame equivalence gate.")
    parser.add_argument(
        "--benchmark",
        choices=sorted({**GATES, **STAGED_GATES}),
        default="ssb",
        help="Benchmark to gate (default: ssb). Staged gates run in report mode but may diverge.",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help=(
            "Explicit maintenance writer: drop any known-divergence entries that no longer "
            "reproduce from this benchmark's YAML baseline (cross_surface_baseline.yaml). "
            "Only writes when the run is otherwise completely clean - any other gate failure "
            "(unclassified divergences, vacuous queries, missing backends) leaves the baseline "
            "untouched and still fails the command (non-zero exit). Idempotent on a second run."
        ),
    )
    args = parser.parse_args(argv)
    return run_gate(get_gate(args.benchmark), update_baseline=args.update_baseline)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
