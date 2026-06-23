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
clickbench (the one classified exception is the order-less ``Q18``) and
joinorder_synthetic. Additional dual-surface benchmarks are added by registering a
:class:`CrossSurfaceGate` in :data:`GATES`.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

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

# Smallest scale that is both discriminating and cheap; matches the TPC-Havoc
# gates' SF=0.1 DuckDB cell so routine PRs stay cheap (one bounded cell per
# gated benchmark, never a full platform matrix).
EQUIVALENCE_SCALE = 0.1

_TRAILING_LIMIT_RE = re.compile(r"(?is)\blimit\s+\d+\s*(?:offset\s+\d+\s*)?;?\s*$")


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
    stripped = re.sub(r"\s*--[^\n]*$", "", sql.strip())
    return bool(_TRAILING_LIMIT_RE.search(stripped))


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
class CrossSurfaceData:
    """Everything the gate needs to compare a benchmark's two surfaces.

    Returned by a benchmark's ``build`` function on a freshly generated, loaded
    DuckDB cell. ``reference_sql`` and ``dataframe_query`` are keyed by the SAME
    query id (the two surfaces are confirmed to correspond 1:1).
    """

    connection: Any
    query_ids: Sequence[Any]
    reference_sql: Callable[[Any], str]
    dataframe_query: Callable[[Any], Any]
    # The benchmark instance + the directory its data was generated into. The
    # DataFrame surface is loaded from these via the real production loader (see
    # :func:`build_production_contexts`), reading the SAME generated files the
    # DuckDB SQL reference loaded, so the comparison stays a single bounded cell.
    benchmark: Any
    data_dir: Path


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
    known_divergences: dict[str, str] = field(default_factory=dict)
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
    # Per-gate data scale for the bounded cell. Defaults to the shared
    # EQUIVALENCE_SCALE so every gate stays cheap; a gate raises it ONLY when a
    # larger (still bounded) cell is the cheapest way to make its queries
    # discriminating. Kept on the gate (not a global) so one benchmark's data
    # needs never inflate every other gate's cost.
    scale_factor: float = EQUIVALENCE_SCALE


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


def _dtype_family(dtype: Any) -> str:
    """Classify a loaded DataFrame column dtype into a coarse family.

    Maps a Polars or Pandas/Arrow dtype to one of ``"string"``, ``"numeric"``,
    ``"temporal"``, ``"boolean"`` or ``"other"`` so a loaded column's family can
    be compared to the family the benchmark's DECLARED SQL type implies. This is
    deliberately coarse: the gate only needs to catch a *family* corruption (a
    declared VARCHAR materialized as an integer because a leading-zero string was
    inferred numeric), not an exact width/precision difference.
    """
    text = str(dtype).lower()
    # Order matters: check temporal/bool before the numeric substring test, and
    # the string test last so a "string" anywhere wins only when nothing numeric
    # matched (e.g. Arrow "large_string", Polars "String", pandas "object").
    if any(token in text for token in ("date", "time", "timestamp", "duration")):
        return "temporal"
    if "bool" in text:
        return "boolean"
    if any(token in text for token in ("int", "float", "double", "decimal", "number", "numeric")):
        return "numeric"
    if any(token in text for token in ("str", "utf8", "object", "category", "categorical")):
        return "string"
    return "other"


def _loaded_column_dtypes(table: Any) -> dict[str, Any]:
    """Return ``{column_name: dtype}`` for a production-loaded table.

    Handles every backend the gate loads: a unified wrapper (unwrapped via
    ``.native``), a Polars lazy/eager frame (``collect_schema``/``schema``), and a
    Pandas-family frame (``.dtypes``). Returns ``{}`` for an unintrospectable
    object so a dtype check is simply skipped rather than crashing the gate.
    """
    native = getattr(table, "native", table)
    # Polars LazyFrame: schema without materializing rows.
    collect_schema = getattr(native, "collect_schema", None)
    if callable(collect_schema):
        return dict(collect_schema())
    schema = getattr(native, "schema", None)
    if schema is not None and hasattr(schema, "items"):
        return dict(schema)
    dtypes = getattr(native, "dtypes", None)
    if dtypes is not None and hasattr(dtypes, "items"):
        return {str(name): dtype for name, dtype in dtypes.items()}
    return {}


def find_loader_dtype_divergences(
    benchmark: Any,
    contexts: dict[str, Any],
    *,
    backends: tuple[str, ...] = DATAFRAME_BACKENDS,
) -> list[SurfaceDivergence]:
    """Observe production-loader dtype fidelity for each gated backend.

    The value comparison in :func:`find_cross_surface_divergences` already runs
    through the REAL production loader (:func:`build_production_contexts` ->
    ``adapter.load_benchmark_into_context``), so loader corruption that *changes a
    value* is already caught. This adds the missing DTYPE-level observability the
    M4 review flagged: a column DECLARED as a string/VARCHAR/TEXT on the SQL
    surface must NOT be silently inferred NUMERIC by the production load path -
    the leading-zero ``"007"`` -> ``7`` corruption (and the related empty-field
    inference that drops a column to a float/null numeric). For every loaded
    table, each declared-string column whose loaded dtype family is ``"numeric"``
    is reported as a divergence keyed ``<table>.<column>_<backend>:dtype`` so the
    gate goes RED on loader dtype corruption even when the surviving values happen
    to still compare equal.

    A declared-string column loaded as a TEMPORAL dtype is deliberately NOT
    flagged: that is the loader's documented date/timestamp coercion for
    date-named columns (e.g. SSB's ``d_date``), a separate behavior whose VALUE
    fidelity the cross-surface comparison already checks - not the numeric
    inference M4 is about. ``boolean``/``other``/``string`` are likewise left to
    the value comparison.

    Returns an empty list when the benchmark exposes no introspectable schema
    (the check is additive and never fabricates a divergence from missing data).
    """
    from benchbox.core.dataframe.data_loader import SchemaMapper
    from benchbox.core.dataframe.schema_utils import get_benchmark_schema_columns

    schema = get_benchmark_schema_columns(benchmark)
    if not schema:
        return []

    divergences: list[SurfaceDivergence] = []
    for backend in backends:
        context = contexts.get(backend)
        if context is None:
            continue
        for table_name, columns in schema.items():
            declared_string = {
                str(column.get("name")): column.get("type")
                for column in columns
                if column.get("name") and SchemaMapper.sql_type_to_pyarrow(str(column.get("type") or "")) == "string"
            }
            if not declared_string:
                continue
            try:
                table = context.get_table(table_name)
            except Exception:  # noqa: BLE001 - a table the gate does not load is not a dtype defect
                continue
            loaded = _loaded_column_dtypes(table)
            lowered = {name.lower(): dtype for name, dtype in loaded.items()}
            for column, sql_type in declared_string.items():
                dtype = loaded.get(column, lowered.get(column.lower()))
                if dtype is None:
                    continue
                family = _dtype_family(dtype)
                if family == "numeric":
                    divergences.append(
                        SurfaceDivergence(
                            f"{table_name}.{column}",
                            f"{backend}:dtype",
                            f"declared {sql_type} loaded as {dtype} (numeric); production loader "
                            f"inferred a string column numeric (e.g. leading-zero VARCHAR '007' -> 7)",
                        )
                    )
    return divergences


def _load_duckdb_cell(benchmark: Any, output_dir: Path, table_names: Sequence[str], *, label: str) -> Any:
    """Create an in-memory DuckDB, build the schema, load the data, and verify it.

    Shared by every benchmark's ``build`` function: it runs the benchmark's
    create-table DDL, loads the generated files via the real
    :class:`~benchbox.platforms.duckdb.DuckDBAdapter`, and asserts each expected
    table got rows. A silent empty/partial load would make every query compare
    empty-vs-empty and report a FALSE green, so an empty table fails loudly here.
    Returns the populated connection (closed by the caller on any later error).
    ``duckdb``/adapter imports are deferred so importing this module stays cheap.
    """
    import duckdb

    from benchbox.platforms.duckdb import DuckDBAdapter

    connection = duckdb.connect(":memory:")
    try:
        for statement in benchmark.get_create_tables_sql(dialect="duckdb").strip().split(";"):
            if statement.strip():
                connection.execute(statement.strip())
        table_stats, _, _ = DuckDBAdapter(database=":memory:").load_data(benchmark, connection, Path(output_dir))

        stats_lower = {str(name).lower(): rows for name, rows in table_stats.items()}
        empty = [name for name in table_names if stats_lower.get(name.lower(), 0) <= 0]
        if empty:
            raise RuntimeError(f"{label} load failed - no rows in {empty} (stats={table_stats})")
    except Exception:
        connection.close()
        raise
    return connection


def build_ssb_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate SSB data, load it into in-memory DuckDB, and wire both surfaces.

    Platform/generator imports are deferred so importing this module stays cheap.
    """
    from benchbox.core.ssb.benchmark import SSBBenchmark
    from benchbox.core.ssb.dataframe_queries import SSB_DATAFRAME_QUERIES
    from benchbox.core.ssb.generator import SSBDataGenerator
    from benchbox.core.ssb.schema import TABLES

    output_dir = Path(output_dir)
    SSBDataGenerator(scale_factor=scale_factor, output_dir=output_dir).generate_data()
    benchmark = SSBBenchmark(scale_factor=scale_factor, output_dir=output_dir)

    connection = _load_duckdb_cell(benchmark, output_dir, [table["name"] for table in TABLES.values()], label="SSB")
    return CrossSurfaceData(
        connection=connection,
        query_ids=list(benchmark.get_queries().keys()),
        reference_sql=lambda query_id: benchmark.get_query(query_id),
        dataframe_query=lambda query_id: SSB_DATAFRAME_QUERIES.get_or_raise(query_id),
        benchmark=benchmark,
        data_dir=output_dir,
    )


def build_amplab_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate AMPLab data, load it into in-memory DuckDB, and wire both surfaces.

    The SQL surface keys queries by ``"1"``, ``"1a"``, ``"2"`` .. ``"5"`` (8 ids)
    while the DataFrame registry keys the SAME logical queries by the ``Q``-prefixed
    ``"Q1"``, ``"Q1a"``, ``"Q2"`` .. ``"Q5"`` (1:1, mechanical prefix), so the
    DataFrame accessor maps the SQL id across. Platform/generator imports are
    deferred so importing this module stays cheap.
    """
    from benchbox.core.amplab.benchmark import AMPLabBenchmark
    from benchbox.core.amplab.dataframe_queries import AMPLAB_DATAFRAME_QUERIES
    from benchbox.core.amplab.generator import AMPLabDataGenerator
    from benchbox.core.amplab.schema import TABLES

    output_dir = Path(output_dir)
    AMPLabDataGenerator(scale_factor=scale_factor, output_dir=output_dir).generate_data()
    benchmark = AMPLabBenchmark(scale_factor=scale_factor, output_dir=output_dir)

    connection = _load_duckdb_cell(benchmark, output_dir, [table["name"] for table in TABLES.values()], label="AMPLab")
    return CrossSurfaceData(
        connection=connection,
        query_ids=list(benchmark.get_queries().keys()),
        reference_sql=lambda query_id: benchmark.get_query(query_id),
        dataframe_query=lambda query_id: AMPLAB_DATAFRAME_QUERIES.get_or_raise(f"Q{query_id}"),
        benchmark=benchmark,
        data_dir=output_dir,
    )


def build_clickbench_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate ClickBench data, load it into in-memory DuckDB, and wire both surfaces.

    Mirrors :func:`build_ssb_duckdb`. ClickBench is a single wide table (``hits``);
    the SQL surface (ids ``Q1``..``Q43``) and the DataFrame registry key by the same
    ids 1:1. Imports are deferred so importing this module stays cheap.
    """
    import duckdb

    from benchbox.core.clickbench.benchmark import ClickBenchBenchmark
    from benchbox.core.clickbench.dataframe_queries import CLICKBENCH_DATAFRAME_QUERIES
    from benchbox.core.clickbench.generator import ClickBenchDataGenerator
    from benchbox.core.clickbench.schema import TABLES
    from benchbox.platforms.duckdb import DuckDBAdapter

    output_dir = Path(output_dir)
    ClickBenchDataGenerator(scale_factor=scale_factor, output_dir=output_dir).generate_data()
    benchmark = ClickBenchBenchmark(scale_factor=scale_factor, output_dir=output_dir)

    connection = duckdb.connect(":memory:")
    try:
        for statement in benchmark.get_create_tables_sql(dialect="duckdb").strip().split(";"):
            if statement.strip():
                connection.execute(statement.strip())
        table_stats, _, _ = DuckDBAdapter(database=":memory:").load_data(benchmark, connection, output_dir)

        # A silent empty/partial load would compare empty-vs-empty and report a
        # FALSE green, so verify the table loaded.
        table_names = [table["name"] for table in TABLES.values()]
        stats_lower = {str(name).lower(): rows for name, rows in table_stats.items()}
        empty = [name for name in table_names if stats_lower.get(name.lower(), 0) <= 0]
        if empty:
            raise RuntimeError(f"ClickBench load failed - no rows in {empty} (stats={table_stats})")
    except Exception:
        connection.close()
        raise

    return CrossSurfaceData(
        connection=connection,
        query_ids=list(benchmark.get_queries().keys()),
        reference_sql=lambda query_id: benchmark.get_query(query_id),
        dataframe_query=lambda query_id: CLICKBENCH_DATAFRAME_QUERIES.get_or_raise(query_id),
        benchmark=benchmark,
        data_dir=output_dir,
    )


def build_coffeeshop_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate CoffeeShop data, load it into in-memory DuckDB, and wire both surfaces.

    Platform/generator imports are deferred so importing this module stays cheap.
    """
    import duckdb

    from benchbox.core.coffeeshop.benchmark import CoffeeShopBenchmark
    from benchbox.core.coffeeshop.dataframe_queries import COFFEESHOP_DATAFRAME_QUERIES
    from benchbox.core.coffeeshop.generator import CoffeeShopDataGenerator
    from benchbox.core.coffeeshop.schema import TABLES
    from benchbox.platforms.duckdb import DuckDBAdapter

    output_dir = Path(output_dir)
    CoffeeShopDataGenerator(scale_factor=scale_factor, output_dir=output_dir).generate_data()
    benchmark = CoffeeShopBenchmark(scale_factor=scale_factor, output_dir=output_dir)

    connection = duckdb.connect(":memory:")
    try:
        for statement in benchmark.get_create_tables_sql(dialect="duckdb").strip().split(";"):
            if statement.strip():
                connection.execute(statement.strip())
        table_stats, _, _ = DuckDBAdapter(database=":memory:").load_data(benchmark, connection, output_dir)

        # A silent empty/partial load would make every query compare
        # empty-vs-empty and report a FALSE green, so verify each table loaded.
        table_names = [table["name"] for table in TABLES.values()]
        stats_lower = {str(name).lower(): rows for name, rows in table_stats.items()}
        empty = [name for name in table_names if stats_lower.get(name.lower(), 0) <= 0]
        if empty:
            raise RuntimeError(f"CoffeeShop load failed - no rows in {empty} (stats={table_stats})")
    except Exception:
        connection.close()
        raise

    return CrossSurfaceData(
        connection=connection,
        query_ids=list(benchmark.get_queries().keys()),
        reference_sql=lambda query_id: benchmark.get_query(query_id),
        dataframe_query=lambda query_id: COFFEESHOP_DATAFRAME_QUERIES.get_or_raise(query_id),
        benchmark=benchmark,
        data_dir=output_dir,
    )


def build_joinorder_synthetic_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate synthetic Join Order data, load into DuckDB, and wire both surfaces.

    Mirrors :func:`build_clickbench_duckdb`. The SQL surface and the
    ``JOINORDER_DATAFRAME_QUERIES`` registry key by the same 13 ids (e.g. ``1a``,
    ``2a``). The generator is seeded, so the bounded cell is reproducible.
    """
    import duckdb

    from benchbox.core.joinorder_synthetic.benchmark import JoinOrderSyntheticBenchmark
    from benchbox.core.joinorder_synthetic.dataframe_queries import JOINORDER_DATAFRAME_QUERIES
    from benchbox.core.joinorder_synthetic.generator import JoinOrderGenerator
    from benchbox.platforms.duckdb import DuckDBAdapter

    output_dir = Path(output_dir)
    JoinOrderGenerator(scale_factor=scale_factor, output_dir=output_dir).generate_data()
    benchmark = JoinOrderSyntheticBenchmark(scale_factor=scale_factor, output_dir=output_dir)

    connection = duckdb.connect(":memory:")
    try:
        for statement in benchmark.get_create_tables_sql(dialect="duckdb").strip().split(";"):
            if statement.strip():
                connection.execute(statement.strip())
        table_stats, _, _ = DuckDBAdapter(database=":memory:").load_data(benchmark, connection, output_dir)

        # A silent empty/partial load would compare empty-vs-empty and report a
        # FALSE green, so verify each table loaded.
        stats_lower = {str(name).lower(): rows for name, rows in table_stats.items()}
        empty = [name for name in benchmark.get_table_names() if stats_lower.get(name.lower(), 0) <= 0]
        if empty:
            raise RuntimeError(f"JoinOrder synthetic load failed - no rows in {empty} (stats={table_stats})")
    except Exception:
        connection.close()
        raise

    return CrossSurfaceData(
        connection=connection,
        query_ids=list(benchmark.get_queries().keys()),
        reference_sql=lambda query_id: benchmark.get_query(query_id),
        dataframe_query=lambda query_id: JOINORDER_DATAFRAME_QUERIES.get_or_raise(query_id),
        benchmark=benchmark,
        data_dir=output_dir,
    )


# Q18 is `SELECT UserID, SearchPhrase, COUNT(*) ... GROUP BY ... LIMIT 10` with NO
# ORDER BY: at SF=0.1 the GROUP BY yields ~97k groups and the bare LIMIT keeps an
# arbitrary 10, so the SQL and DataFrame surfaces each return a different - but
# equally valid - subset (verified: both are subsets of the full grouped result).
# There is no total order to make this deterministic, so it is a genuinely
# tie-ambiguous query, classified here (the last-resort option) rather than masked:
# the tie-aware comparator handles every ORDER BY ... LIMIT case, only this
# order-less LIMIT needs a baseline entry.
_CLICKBENCH_TIE_AMBIGUOUS = (
    "Q18 is LIMIT 10 with no ORDER BY over ~97k groups - an arbitrary, order-less top-N selection"
)

# Six SSB queries return 0 reference rows at EVERY bounded scale (verified empty at
# SF=0.1, 0.2, 0.3, 0.5 AND 1.0), so no cheap SF override makes them discriminating.
# Root cause: the BenchBox SSB generator emits value FORMATS that the canonical SSB
# query parameters never match, so the highly-selective multi-join filters select
# nothing at any scale:
#   * p_category is generated as 'MFGR#112' (3-digit), but Q2.1/Q4.3 filter on the
#     canonical 'MFGR#12' (2-digit) - no part row ever qualifies (verified
#     count(part WHERE p_category='MFGR#12') == 0 at SF=1.0).
#   * c_city/s_city are generated as 'UNITED K0'..'UNITED K9' (name truncated to
#     10 chars), but Q3.3 filters on the canonical 'UNITED KI1'/'UNITED KI5' - no
#     city row ever qualifies.
#   * Q2.2/Q2.3 filter on canonical p_brand1 ranges/values that the generated
#     'MFGR#NNNNN' brand format does not populate; Q3.4 layers the same city
#     mismatch with a yearmonth filter.
# Fixing this would require either changing SSB's canonical query parameters (which
# would alter the benchmark itself - forbidden) or regenerating the SSB data with
# SSB-faithful value formats (a generator change out of scope for this gate). Until
# then these queries are LEGITIMATELY empty: SQL and DataFrame both return 0 rows
# because the data genuinely contains no matching rows, not because of a load or
# logic bug. They are classified (not silently passed) so the vacuity guard fails
# loudly if a future change makes one of them produce rows on only one surface.
_SSB_VACUOUS = (
    "0 reference rows at every bounded SF (verified to SF=1.0): the BenchBox SSB "
    "generator's value formats (p_category 'MFGR#112' not 'MFGR#12'; c_city/s_city "
    "'UNITED K0' not 'UNITED KI1') never match this query's canonical SSB filter "
    "parameters, so the selective multi-join selects no rows on either surface. "
    "Tracked: regenerate SSB data with SSB-faithful value formats (do NOT change "
    "the canonical query parameters)."
)
_SSB_LEGITIMATELY_EMPTY: dict[Any, str] = dict.fromkeys(("Q2.1", "Q2.2", "Q2.3", "Q3.3", "Q3.4", "Q4.3"), _SSB_VACUOUS)

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

# Registry of ENFORCED gated benchmarks: clean, blocking cross-surface gates whose
# DataFrame surface matches its SQL surface. The oracle coverage map reads this set
# to classify a benchmark as cross-surface "guarded", so only clean+enforced gates
# belong here (registering a red gate here would be coverage theater).
GATES: dict[str, CrossSurfaceGate] = {
    "ssb": CrossSurfaceGate(name="ssb", build=build_ssb_duckdb, legitimately_empty=_SSB_LEGITIMATELY_EMPTY),
    "amplab": CrossSurfaceGate(name="amplab", build=build_amplab_duckdb, legitimately_empty=_AMPLAB_LEGITIMATELY_EMPTY),
    "coffeeshop": CrossSurfaceGate(name="coffeeshop", build=build_coffeeshop_duckdb),
    # Promoted from STAGED_GATES once the two cross-cutting prerequisites landed:
    # w9 (loader applies schema column TYPES + DuckDB empty-string semantics) made
    # joinorder_synthetic 26/26 and cleared ClickBench Q17/Q24; w8 (tie-aware
    # comparator) cleared ClickBench's tie-ambiguous top-N cells. ClickBench's only
    # baseline entry is the order-less Q18 (see above).
    "clickbench": CrossSurfaceGate(
        name="clickbench",
        build=build_clickbench_duckdb,
        known_divergences={
            "Q18_expression": _CLICKBENCH_TIE_AMBIGUOUS,
            "Q18_pandas": _CLICKBENCH_TIE_AMBIGUOUS,
        },
        legitimately_empty=_CLICKBENCH_LEGITIMATELY_EMPTY,
    ),
    "joinorder_synthetic": CrossSurfaceGate(name="joinorder_synthetic", build=build_joinorder_synthetic_duckdb),
}

# Staged gates: a load-faithful builder is wired and runnable in report mode, but
# the benchmark still has open cross-surface divergences to burn down before it can
# be promoted into GATES (and made a blocking CI gate). Kept OUT of GATES so the
# coverage map does not prematurely mark these benchmarks "guarded". Currently empty
# - clickbench and joinorder_synthetic graduated to GATES; the next gateable
# benchmarks (datavault, flightdata, h2odb, nyctaxi, read_primitives, tpcds_obt,
# tpch_skew, tsbs_devops) land here first when their builders are wired.
STAGED_GATES: dict[str, CrossSurfaceGate] = {}


def get_gate(name: str) -> CrossSurfaceGate:
    """Resolve a gate by name from the enforced or staged registries."""
    if name in GATES:
        return GATES[name]
    return STAGED_GATES[name]


def run_gate(gate: CrossSurfaceGate) -> int:
    """Run one benchmark's cross-surface gate and print a categorized report."""
    import tempfile

    from benchbox.core.tpchavoc.validation import ResultValidator

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
                validator=ResultValidator(tolerance=gate.tolerance),
                backends=gate.backends,
                reference_row_counts=reference_row_counts,
            )
            # Production-loader dtype observability (M4): assert each declared
            # string column survived the REAL CSV->parquet->read loader as a
            # string family, so a leading-zero VARCHAR inferred numeric (or an
            # all-empty TEXT column dropped to a null/float column) makes the gate
            # RED even if the surviving values still compared equal above.
            divergences += find_loader_dtype_divergences(data.benchmark, contexts, backends=gate.backends)
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
    return _report(
        divergences,
        total,
        coverage,
        gate.known_divergences,
        benchmark=gate.name,
        reference_row_counts=reference_row_counts,
        legitimately_empty=gate.legitimately_empty,
        scale_factor=gate.scale_factor,
        vacuous_cells=sum(vacuous_cells.values()),
    )


def _report(
    divergences: list[SurfaceDivergence],
    total: int,
    coverage: dict[str, int],
    known: dict[str, str],
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
      * any VACUOUS query - one whose SQL reference returns 0 rows, so every
        backend compares empty-vs-empty and trivially "matches" without
        discriminating anything - UNLESS it is explicitly classified in
        ``legitimately_empty`` with a rationale.

    The "compared N of M cells" line reports DISCRIMINATING cells only: a vacuous
    query's cells are excluded from the discriminating count and reported
    separately, so a report can never present empty-vs-empty passes as coverage.
    """
    legitimately_empty = legitimately_empty or {}
    reference_row_counts = reference_row_counts or {}

    found = {d.key for d in divergences}
    new = sorted(found - set(known))
    resolved = sorted(set(known) - found)
    missing_backends = sorted(backend for backend, count in coverage.items() if count == 0)
    executed = sum(coverage.values())

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
        klass = known.get(divergence.key, "UNCLASSIFIED")
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
        print(f"Previously-known divergences now equivalent - update the baseline: {resolved}")
    if not new and not resolved and not missing_backends and not unclassified_empty:
        suffix = " (modulo classified exceptions)" if (known or classified_empty) else ""
        print(f"SQL and DataFrame surfaces are equivalent{suffix}.")
    return 1 if (new or missing_backends or unclassified_empty) else 0


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
    args = parser.parse_args(argv)
    return run_gate(get_gate(args.benchmark))


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
