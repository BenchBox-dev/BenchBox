"""Result-equivalence gate for TPC-Havoc DataFrame variants.

The DataFrame variants in :mod:`benchbox.core.tpchavoc.dataframe_queries` are
*independent designs*, not mirrors of the SQL variants: the same variant id
encodes a different transformation per surface. The SQL gate in
:mod:`benchbox.core.tpchavoc.equivalence` therefore proves nothing about this
surface, and the same silent defect classes it caught (value clamping, dropped
or extra output columns, filtering the wrong frame) are equally expressible in
DataFrame code.

This module extends the same guarantee to the DataFrame surface:
``python -m benchbox.core.tpchavoc.dataframe_equivalence`` (or
``make tpchavoc-dataframe-equivalence-report``) executes every DataFrame
variant of every implemented query on **both** shipped backends - the
expression family (Polars reference adapter) and the Pandas family (Pandas
reference adapter) - against the same bounded SF=0.1 DuckDB-generated data the
SQL gate uses, compares each result to **canonical TPC-H SQL** executed on
DuckDB (never to the variant's SQL namesake and never to a sibling DataFrame
variant), and **exits non-zero** if any variant/backend cell diverges beyond
:data:`KNOWN_DIVERGENCES` (currently empty - every cell must match).

It deliberately reuses the SQL gate's data builder
(:func:`~benchbox.core.tpchavoc.equivalence.build_duckdb_with_tpch`) and the
existing comparator (:meth:`TPCHavocBenchmark.validate_variant_equivalence`);
the only new logic is materializing tables into DataFrame contexts and variant
results into ordered row tuples.

Two normalization choices differ from the SQL gate, both forced by the
surface:

* The canonical reference keeps its presentational ``ORDER BY ... LIMIT n``
  top-N cut (the SQL gate strips it) because every DataFrame implementation -
  canonical and variant alike - reproduces the cut via ``limit()``/``head()``.
  Comparing cut-to-cut keeps a missing or wrong-sized cut visible as a row
  count divergence.
* Values are normalized to plain Python scalars before the comparator sees
  them: DuckDB ``DECIMAL`` results become floats (the DataFrame surface
  computes in float64 throughout, mirroring the production loader's
  ``DECIMAL -> Float64`` schema mapping), midnight timestamps become dates,
  and missing values (``None``/``NaN``/``NA``/``NaT``) become ``None``.

Q11's value threshold is scale-dependent (canonical qgen renders
``0.0001 / SF``). The DataFrame implementations read the fraction from
``get_tpch_parameters``, whose static default is the SF=1 value; production
runs inject the scale-correct value via seeded parameter extraction. The gate
mirrors that run path through the same public
``set_parameter_overrides`` seam so the canonical SQL reference and the
DataFrame variants agree on the threshold. Making the *unseeded* product run
path scale-aware (and dropping this injection) is tracked in
``_project/TODO/main/planning/tpch-dataframe-unseeded-q11-scale-fraction.yaml``.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark(TM) H (TPC-H) - Copyright (C) Transaction Processing Performance Council.
This implementation is derived from TPC-H.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Callable

from benchbox.core.tpchavoc.benchmark import TPCHavocBenchmark
from benchbox.core.tpchavoc.equivalence import EQUIVALENCE_SCALE, build_duckdb_with_tpch
from benchbox.core.tpchavoc.validation import ValidationError

# Both shipped DataFrame backends are gated: they are independent
# implementations (expression_impl vs pandas_impl) and can diverge
# independently. The reference adapters are Polars (expression family) and
# Pandas (pandas family).
DATAFRAME_BACKENDS = ("expression", "pandas")

# Variant/backend cells tolerated to diverge from canonical TPC-H at
# EQUIVALENCE_SCALE, with the reason class. Empty: every DataFrame variant must
# match canonical on both backends. Add an entry (with a class and a tracking
# TODO) only for a divergence that is deliberate, never to mute a regression.
# Keyed by "<query>_v<variant>:<backend>".
KNOWN_DIVERGENCES: dict[str, str] = {}

_MIDNIGHT = time(0, 0, 0)


@dataclass(frozen=True)
class DataFrameDivergence:
    """A variant/backend cell whose result differs from canonical TPC-H."""

    query_id: int
    variant_id: int
    backend: str
    detail: str

    @property
    def key(self) -> str:
        """Stable ``<query>_v<variant>:<backend>`` identifier."""
        return f"{self.query_id}_v{self.variant_id}:{self.backend}"


def build_dataframe_contexts(connection: Any) -> dict[str, Any]:
    """Materialize the TPC-H tables on ``connection`` into both DataFrame contexts.

    Tables are exported once through Arrow with ``DECIMAL`` columns cast to
    ``DOUBLE``, mirroring the production DataFrame loader's schema mapping
    (``DECIMAL(15,2) -> Float64`` / ``double``), then registered with the
    reference adapter context of each backend: Polars lazy frames for the
    expression family and Arrow-backed Pandas frames (production loads Parquet
    with ``dtype_backend="pyarrow"``) for the pandas family.

    Platform imports are deferred so importing this module does not pull
    Polars or Pandas into the core import graph.

    Args:
        connection: A DuckDB connection already populated with TPC-H data.

    Returns:
        Mapping of backend name (see :data:`DATAFRAME_BACKENDS`) to a context
        with all eight TPC-H tables registered.
    """
    import pandas as pd
    import polars as pl

    from benchbox.core.tpch.schema import TABLES
    from benchbox.platforms.dataframe.pandas_df import PandasDataFrameAdapter
    from benchbox.platforms.dataframe.polars_df import PolarsDataFrameAdapter

    expression_ctx = PolarsDataFrameAdapter().create_context()
    pandas_ctx = PandasDataFrameAdapter().create_context()
    for table in TABLES:
        projections = [
            f"CAST({column.name} AS DOUBLE) AS {column.name}"
            if column.data_type.value.startswith("DECIMAL")
            else column.name
            for column in table.columns
        ]
        arrow = connection.execute(f"SELECT {', '.join(projections)} FROM {table.name.lower()}").arrow()
        expression_ctx.register_table(table.name, pl.from_arrow(arrow).lazy())
        pandas_ctx.register_table(table.name, arrow.to_pandas(types_mapper=pd.ArrowDtype))
    return {"expression": expression_ctx, "pandas": pandas_ctx}


def materialize_rows(result: Any) -> list[tuple[Any, ...]]:
    """Materialize a DataFrame query result to normalized row tuples.

    Accepts whatever a variant implementation returns on either backend - a
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


def fetch_canonical_rows(connection: Any, canonical_sql: str) -> list[tuple[Any, ...]]:
    """Execute canonical TPC-H SQL and return normalized row tuples.

    The query is executed as-is - including its presentational top-N ``LIMIT``
    - because the DataFrame implementations reproduce that cut (see module
    docstring). Values pass through the same normalization as the DataFrame
    side so the comparator sees one scalar vocabulary.
    """
    rows = connection.execute(canonical_sql).fetchall()
    return [tuple(_normalize_value(value) for value in row) for row in rows]


def find_dataframe_divergences(
    connection: Any,
    benchmark: TPCHavocBenchmark,
    canonical_query: Callable[[int], str],
    contexts: dict[str, Any],
    *,
    query_ids: list[int] | None = None,
    backends: tuple[str, ...] = DATAFRAME_BACKENDS,
) -> list[DataFrameDivergence]:
    """Compare every DataFrame variant of each query to canonical TPC-H.

    Args:
        connection: A DuckDB connection already populated with TPC-H data
            (the canonical reference executes here).
        benchmark: The TPC-Havoc benchmark providing the DataFrame registry,
            the validator, and the scale factor.
        canonical_query: Callable returning canonical TPC-H SQL for a query id.
        contexts: Backend-name-to-context mapping from
            :func:`build_dataframe_contexts`.
        query_ids: Subset of query ids to check; defaults to all implemented.
        backends: Backends to gate; defaults to both shipped backends.

    Returns:
        One :class:`DataFrameDivergence` per variant/backend cell whose result
        is not equivalent to canonical TPC-H. Reuses
        :meth:`TPCHavocBenchmark.validate_variant_equivalence`.
    """
    from benchbox.core.tpch import dataframe_queries as tpch_dataframe_queries
    from benchbox.core.tpch.dataframe_queries import TPCH_DEFAULT_PARAMS, set_parameter_overrides

    ids = query_ids if query_ids is not None else benchmark.get_implemented_queries()
    registry = benchmark.get_dataframe_queries()
    divergences: list[DataFrameDivergence] = []
    # Align the DataFrame surface's Q11 threshold with canonical qgen's
    # fraction/SF rendering, exactly as seeded production runs do; restore any
    # ambient overrides afterwards rather than clearing them.
    previous_overrides = tpch_dataframe_queries._parameter_overrides
    sf1_fraction = TPCH_DEFAULT_PARAMS[11]["fraction"]
    set_parameter_overrides({11: {"fraction": sf1_fraction / benchmark.scale_factor}})
    try:
        for query_id in ids:
            try:
                canonical_rows = fetch_canonical_rows(connection, canonical_query(query_id))
            except Exception as exc:  # noqa: BLE001 - a diagnostic must report, not crash, on a bad query
                divergences.append(DataFrameDivergence(query_id, 0, "canonical", f"canonical query failed: {exc}"))
                continue
            for variant_id in range(1, 11):
                query = registry.get_or_raise(f"Q{query_id}v{variant_id}")
                for backend in backends:
                    impl = query.expression_impl if backend == "expression" else query.pandas_impl
                    try:
                        variant_rows = materialize_rows(impl(contexts[backend]))
                        benchmark.validate_variant_equivalence(query_id, variant_id, canonical_rows, variant_rows)
                    except ValidationError as exc:
                        divergences.append(DataFrameDivergence(query_id, variant_id, backend, str(exc)))
                    except Exception as exc:  # noqa: BLE001 - surface execution errors as divergences
                        divergences.append(DataFrameDivergence(query_id, variant_id, backend, f"error: {exc}"))
    finally:
        set_parameter_overrides(previous_overrides)
    return divergences


def main() -> int:
    """Generate data, run the DataFrame oracle, and print a categorized report.

    Returns non-zero if any variant/backend cell diverges beyond
    :data:`KNOWN_DIVERGENCES` - this is the TPC-Havoc DataFrame
    semantic-equivalence gate.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        connection, tpchavoc, tpch = build_duckdb_with_tpch(EQUIVALENCE_SCALE, tmp)
        try:
            contexts = build_dataframe_contexts(connection)
            divergences = find_dataframe_divergences(connection, tpchavoc, lambda q: tpch.get_query(q), contexts)
        finally:
            connection.close()

    total = len(tpchavoc.get_implemented_queries()) * 10 * len(DATAFRAME_BACKENDS)
    found = {d.key for d in divergences}
    new = sorted(found - set(KNOWN_DIVERGENCES), key=_sort_key)
    resolved = sorted(set(KNOWN_DIVERGENCES) - found, key=_sort_key)

    print(f"TPC-Havoc DataFrame variant equivalence vs canonical TPC-H @ SF={EQUIVALENCE_SCALE} (DuckDB-backed)")
    print(
        f"  checked {total} variant-backend cells - "
        f"{len(divergences)} divergent, {total - len(divergences)} equivalent\n"
    )

    by_class: dict[str, list[DataFrameDivergence]] = {}
    for divergence in sorted(divergences, key=lambda d: _sort_key(d.key)):
        klass = KNOWN_DIVERGENCES.get(divergence.key, "UNCLASSIFIED")
        by_class.setdefault(klass, []).append(divergence)
    for klass in sorted(by_class):
        print(f"  [{klass}]")
        for divergence in by_class[klass]:
            print(f"    {divergence.key}: {divergence.detail}")
        print()

    if new:
        print(f"GATE FAILURE - unclassified DataFrame divergences from canonical TPC-H: {new}")
    if resolved:
        print(f"Previously-known divergences now equivalent - update KNOWN_DIVERGENCES: {resolved}")
    if not new and not resolved:
        print("All DataFrame variants equivalent to canonical TPC-H (modulo KNOWN_DIVERGENCES).")
    return 1 if new else 0


def _normalize_value(value: Any) -> Any:
    """Normalize one result value to a plain Python scalar.

    Maps DuckDB ``Decimal`` to float (the DataFrame surface computes in
    float64), midnight timestamps to dates (Pandas materializes DATE columns
    as midnight ``Timestamp``), missing values (``None``/``NaN``/Pandas
    ``NA``/``NaT``) to ``None``, and unwraps NumPy/Arrow scalars via
    ``.item()``.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):  # before date: datetime subclasses date
        return value.date() if value.time() == _MIDNIGHT else value
    if isinstance(value, float):  # before .item(): NumPy floats subclass float
        return None if math.isnan(value) else float(value)
    if isinstance(value, (str, bytes, int, date)):
        return value
    if type(value).__name__ in ("NAType", "NaTType"):  # pandas.NA / pandas.NaT without importing pandas
        return None
    item = getattr(value, "item", None)  # NumPy / Arrow scalar wrappers
    if callable(item):
        return _normalize_value(item())
    return value


def _sort_key(key: str) -> tuple[int, int, str]:
    """Sort ``<query>_v<variant>:<backend>`` keys numerically then by backend."""
    cell, _, backend = key.partition(":")
    query, _, variant = cell.partition("_v")
    return int(query), int(variant or 0), backend


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
