"""Benchmark-agnostic cross-surface result-equivalence harness.

This module factors the proven TPC-Havoc DataFrame gate
(:mod:`benchbox.core.tpchavoc.dataframe_equivalence`) into a shared, benchmark-
agnostic helper so the *same* discipline - execute a candidate surface and a
trusted reference over the SAME bounded DuckDB data and compare results live,
with no hand-maintained answer key - can be rolled out to any benchmark that
ships a DataFrame surface.

The reusable pieces are:

* :func:`build_dataframe_contexts` - materialize a benchmark's tables from a
  populated DuckDB connection into the two shipped DataFrame backend contexts
  (Polars expression family, Arrow-backed Pandas family), with ``DECIMAL``
  columns cast to ``DOUBLE`` to mirror the production loader's schema mapping.
* :func:`materialize_rows` - normalize whatever a DataFrame implementation
  returns (a unified-frame wrapper, a Polars lazy/eager frame, or a Pandas
  frame) into ordered row tuples of plain Python scalars.
* :func:`fetch_reference_rows` - run reference SQL on the DuckDB connection and
  normalize its rows through the same scalar vocabulary.
* :func:`find_surface_divergences` - the data-build-agnostic compare loop:
  fetch the reference once per logical query, then run each candidate cell and
  validate it against that reference, recording one :class:`SurfaceDivergence`
  per cell that diverges (or errors).

The comparator/validator and the DuckDB data builder are NEVER forked here:
callers inject their existing validator (e.g.
:meth:`TPCHavocBenchmark.validate_variant_equivalence` or a
:class:`~benchbox.core.tpchavoc.validation.ResultValidator`) and their existing
data builder (e.g.
:func:`~benchbox.core.tpchavoc.equivalence.build_duckdb_with_tpch`).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

# The two shipped DataFrame reference backends (Polars expression family vs
# Pandas). A gate that cares about the DataFrame surface checks both because they
# can diverge on engine semantics - but they are only *independent of each other*
# when a benchmark hand-writes a separate impl per backend (coffeeshop, amplab).
# For DSL-generated benchmarks (ssb, most of clickbench) both backends are
# emitted from one spec row, so they share any spec-level logic error; the only
# independent reference there is the SQL surface. See cross_surface.py's module
# docstring for the per-benchmark detail.
DATAFRAME_BACKENDS = ("expression", "pandas")

_MIDNIGHT = time(0, 0, 0)


@dataclass(frozen=True)
class SurfaceDivergence:
    """A single (query, cell) whose candidate result differs from the reference.

    ``cell`` is a benchmark-defined label for the candidate under test (e.g.
    ``"v3:expression"`` for a TPC-Havoc DataFrame variant/backend, or
    ``"expression"`` for a benchmark's single DataFrame surface on one backend).
    """

    query_id: Any
    cell: str
    detail: str

    @property
    def key(self) -> str:
        """Stable ``<query>_<cell>`` identifier (or ``<query>`` if cell-less)."""
        return f"{self.query_id}_{self.cell}" if self.cell else f"{self.query_id}"


def build_dataframe_contexts_from_specs(
    connection: Any,
    table_specs: Iterable[tuple[str, Iterable[tuple[str, str]]]],
) -> dict[str, Any]:
    """Materialize tables described by ``(name, [(column, sql_type), ...])`` specs.

    The benchmark-agnostic core of :func:`build_dataframe_contexts`: it takes a
    normalized ``(table_name, columns)`` description - where ``columns`` is an
    iterable of ``(column_name, sql_type_string)`` pairs - so it works for any
    benchmark regardless of whether its schema is exposed as typed objects
    (TPC-H ``Table``/``Column``) or plain dicts (SSB/amplab/etc.).

    Tables are exported once through Arrow with ``DECIMAL`` columns cast to
    ``DOUBLE``, mirroring the production DataFrame loader's schema mapping
    (``DECIMAL(15,2) -> Float64`` / ``double``), then registered with the
    reference adapter context of each backend: Polars lazy frames for the
    expression family and Arrow-backed Pandas frames (production loads Parquet
    with ``dtype_backend="pyarrow"``) for the pandas family.

    Platform imports are deferred so importing this module does not pull Polars
    or Pandas into the core import graph.

    Args:
        connection: A DuckDB connection already populated with the benchmark's
            data.
        table_specs: Iterable of ``(table_name, columns)`` where ``columns`` is
            an iterable of ``(column_name, sql_type_string)`` pairs.

    Returns:
        Mapping of backend name (see :data:`DATAFRAME_BACKENDS`) to a context
        with all of the benchmark's tables registered.
    """
    import pandas as pd
    import polars as pl

    from benchbox.platforms.dataframe.pandas_df import PandasDataFrameAdapter
    from benchbox.platforms.dataframe.polars_df import PolarsDataFrameAdapter

    expression_ctx = PolarsDataFrameAdapter().create_context()
    pandas_ctx = PandasDataFrameAdapter().create_context()
    for table_name, columns in table_specs:
        projections = [
            f"CAST({column} AS DOUBLE) AS {column}" if str(sql_type).upper().startswith("DECIMAL") else column
            for column, sql_type in columns
        ]
        # fetch_arrow_table() (not .arrow()) so the result is a materialized
        # pyarrow.Table on every DuckDB version, including >=1.4 where
        # .arrow() returns a RecordBatchReader.
        arrow = connection.execute(f"SELECT {', '.join(projections)} FROM {table_name.lower()}").fetch_arrow_table()
        expression_ctx.register_table(table_name, pl.from_arrow(arrow).lazy())
        pandas_ctx.register_table(table_name, arrow.to_pandas(types_mapper=pd.ArrowDtype))
    return {"expression": expression_ctx, "pandas": pandas_ctx}


def build_dataframe_contexts(connection: Any, tables: Iterable[Any]) -> dict[str, Any]:
    """Materialize typed-object ``tables`` into both DataFrame backend contexts.

    Convenience wrapper over :func:`build_dataframe_contexts_from_specs` for
    benchmarks whose schema is exposed as typed objects (TPC-H ``Table`` whose
    ``.columns`` expose ``.name`` and a ``.data_type`` with a ``.value`` SQL type
    string). Benchmarks with dict-shaped schemas call
    :func:`build_dataframe_contexts_from_specs` directly with normalized specs.

    Args:
        connection: A DuckDB connection already populated with the benchmark's
            data.
        tables: The benchmark's table schemas; each must expose ``.name`` and a
            ``.columns`` iterable of columns exposing ``.name`` and a
            ``.data_type`` whose ``.value`` is the SQL type string.

    Returns:
        Mapping of backend name (see :data:`DATAFRAME_BACKENDS`) to a context
        with all of the benchmark's tables registered.
    """
    specs = ((table.name, [(column.name, column.data_type.value) for column in table.columns]) for table in tables)
    return build_dataframe_contexts_from_specs(connection, specs)


def materialize_rows(result: Any) -> list[tuple[Any, ...]]:
    """Materialize a DataFrame query result to normalized row tuples.

    Accepts whatever a DataFrame implementation returns on either backend - a
    ``UnifiedLazyFrame``/``UnifiedPandasFrame`` wrapper, a Polars lazy or eager
    frame, or a Pandas frame - and produces plain row tuples in the frame's
    column order with values normalized via :func:`_normalize_value`.
    """
    native = getattr(result, "native", result)
    if hasattr(native, "collect"):
        native = native.collect()
    if hasattr(native, "rows"):
        raw_rows = native.rows()
    elif hasattr(native, "itertuples"):
        raw_rows = native.itertuples(index=False, name=None)
    else:
        raise TypeError(f"cannot materialize result of type {type(native).__name__}")
    return [tuple(_normalize_value(value) for value in row) for row in raw_rows]


def fetch_reference_rows(connection: Any, reference_sql: str) -> list[tuple[Any, ...]]:
    """Execute reference SQL on ``connection`` and return normalized row tuples.

    The query is executed as-is - including any presentational top-N ``LIMIT``
    - because the DataFrame implementations reproduce that cut. Values pass
    through the same normalization as the DataFrame side so the comparator sees
    one scalar vocabulary.
    """
    rows = connection.execute(reference_sql).fetchall()
    return [tuple(_normalize_value(value) for value in row) for row in rows]


def find_surface_divergences(
    query_ids: Iterable[Any],
    *,
    reference_rows: Callable[[Any], list[tuple[Any, ...]]],
    candidate_cells: Callable[[Any], Iterable[tuple[str, Callable[[list[tuple[Any, ...]]], None]]]],
    validation_error: type[BaseException],
    reference_failure_cell: str = "reference",
) -> list[SurfaceDivergence]:
    """Compare each query's candidate cells to a trusted reference, live.

    The data build, the reference, the candidate enumeration, and the validator
    are all injected so this loop is benchmark-agnostic: it owns only the
    fetch-reference-once-then-check-each-cell control flow and the per-cell
    error isolation, never the comparator or the data builder.

    Args:
        query_ids: The logical queries to check.
        reference_rows: Callable returning the trusted reference rows for a
            query id (e.g. canonical SQL executed on DuckDB, normalized). A
            failure here is recorded as a single divergence on
            ``reference_failure_cell`` and the query is skipped (its candidate
            cells cannot be compared without a reference).
        candidate_cells: Callable yielding, for a query id, ``(cell, check)``
            pairs. ``cell`` is the benchmark-defined cell label; ``check`` takes
            the reference rows and must materialize the candidate and validate
            it against the reference, raising on any mismatch or execution error.
        validation_error: The exception type a ``check`` raises for a genuine
            result mismatch (its ``str`` is used verbatim as the detail). Any
            other exception is treated as an execution error (``error: ...``).
            Required (not defaulted) so a caller never silently reclassifies an
            implementation crash as a result mismatch; pass :class:`Exception`
            explicitly to opt into "every failure is a mismatch".
        reference_failure_cell: Cell label used when the reference itself fails.

    Returns:
        One :class:`SurfaceDivergence` per cell whose candidate result is not
        equivalent to the reference (plus one per query whose reference failed).
    """
    divergences: list[SurfaceDivergence] = []
    for query_id in query_ids:
        try:
            reference = reference_rows(query_id)
        except Exception as exc:  # noqa: BLE001 - a diagnostic must report, not crash, on a bad query
            divergences.append(SurfaceDivergence(query_id, reference_failure_cell, f"reference query failed: {exc}"))
            continue
        for cell, check in candidate_cells(query_id):
            try:
                check(reference)
            except validation_error as exc:  # type: ignore[misc] - configurable mismatch type
                divergences.append(SurfaceDivergence(query_id, cell, str(exc)))
            except Exception as exc:  # noqa: BLE001 - surface execution errors as divergences
                divergences.append(SurfaceDivergence(query_id, cell, f"error: {exc}"))
    return divergences


def _normalize_value(value: Any) -> Any:
    """Normalize one result value to a plain Python scalar.

    Maps DuckDB ``Decimal`` to float (the DataFrame surface computes in
    float64), midnight timestamps to dates (Pandas materializes DATE columns
    as midnight ``Timestamp``), Pandas missing sentinels (``NA``/``NaT``) to
    ``None``, and unwraps NumPy/Arrow scalars via ``.item()``. Floating NaN is
    preserved so the strict comparator can catch spurious NaN-vs-NULL divergence
    unless a caller explicitly opts into NaN-as-NULL tolerance.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):  # before date: datetime subclasses date
        return value.date() if value.time() == _MIDNIGHT else value
    if isinstance(value, float):  # before .item(): NumPy floats subclass float
        return value if math.isnan(value) else float(value)
    if isinstance(value, (str, bytes, int, date)):
        return value
    if type(value).__name__ in ("NAType", "NaTType"):  # pandas.NA / pandas.NaT without importing pandas
        return None
    item = getattr(value, "item", None)  # NumPy / Arrow scalar wrappers
    if callable(item):
        return _normalize_value(item())
    return value
