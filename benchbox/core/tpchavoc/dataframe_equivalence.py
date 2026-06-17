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

It is a thin benchmark-specific wrapper over the shared, benchmark-agnostic
harness in :mod:`benchbox.core.equivalence.dataframe_surface`: it reuses that
harness's DataFrame materialization
(:func:`~benchbox.core.equivalence.dataframe_surface.materialize_rows`,
:func:`~benchbox.core.equivalence.dataframe_surface.build_dataframe_contexts`,
:func:`~benchbox.core.equivalence.dataframe_surface.fetch_reference_rows`) and
its compare loop
(:func:`~benchbox.core.equivalence.dataframe_surface.find_surface_divergences`),
the SQL gate's data builder
(:func:`~benchbox.core.tpchavoc.equivalence.build_duckdb_with_tpch`), and the
existing comparator (:meth:`TPCHavocBenchmark.validate_variant_equivalence`).
The only TPC-Havoc-specific logic here is the canonical reference accessor, the
variant/backend cell enumeration, and the Q11 scale-aware parameter wiring.

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
``get_tpch_parameters``, whose default is now scale-aware: it scales the SF=1
value by the scale factor declared via ``set_scale_factor``, exactly like the
qgen rendering and the unseeded production run path. The gate declares its
scale (``EQUIVALENCE_SCALE``) through that same product seam so the canonical
SQL reference and the DataFrame variants agree on the threshold without any
gate-local parameter override.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark(TM) H (TPC-H) - Copyright (C) Transaction Processing Performance Council.
This implementation is derived from TPC-H.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from benchbox.core.equivalence.dataframe_surface import (
    DATAFRAME_BACKENDS,
    SurfaceDivergence,
    build_dataframe_contexts as _build_dataframe_contexts,
    fetch_reference_rows,
    find_surface_divergences,
    materialize_rows,
)
from benchbox.core.tpchavoc.benchmark import TPCHavocBenchmark
from benchbox.core.tpchavoc.equivalence import EQUIVALENCE_SCALE, build_duckdb_with_tpch
from benchbox.core.tpchavoc.validation import ValidationError

# Re-exported from the shared harness so existing imports of these names from
# this module keep working; the comparator/data-builder are never forked.
__all__ = [
    "DATAFRAME_BACKENDS",
    "KNOWN_DIVERGENCES",
    "build_dataframe_contexts",
    "fetch_canonical_rows",
    "find_dataframe_divergences",
    "main",
    "materialize_rows",
]

# Variant/backend cells tolerated to diverge from canonical TPC-H at
# EQUIVALENCE_SCALE, with the reason class. Empty: every DataFrame variant must
# match canonical on both backends. Add an entry (with a class and a tracking
# TODO) only for a divergence that is deliberate, never to mute a regression.
# Keyed by "<query>_v<variant>:<backend>".
KNOWN_DIVERGENCES: dict[str, str] = {}

# Canonical TPC-H SQL reference rows are normalized the same way as the
# DataFrame side; re-exported under the historical name for callers/tests.
fetch_canonical_rows = fetch_reference_rows


def build_dataframe_contexts(connection: Any) -> dict[str, Any]:
    """Materialize the TPC-H tables on ``connection`` into both DataFrame contexts.

    Thin TPC-H-specific wrapper over
    :func:`benchbox.core.equivalence.dataframe_surface.build_dataframe_contexts`,
    supplying the TPC-H table schema.

    Args:
        connection: A DuckDB connection already populated with TPC-H data.

    Returns:
        Mapping of backend name (see :data:`DATAFRAME_BACKENDS`) to a context
        with all eight TPC-H tables registered.
    """
    from benchbox.core.tpch.schema import TABLES

    return _build_dataframe_contexts(connection, TABLES)


def find_dataframe_divergences(
    connection: Any,
    benchmark: TPCHavocBenchmark,
    canonical_query: Callable[[int], str],
    contexts: dict[str, Any],
    *,
    query_ids: list[int] | None = None,
    backends: tuple[str, ...] = DATAFRAME_BACKENDS,
) -> list[SurfaceDivergence]:
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
        One :class:`SurfaceDivergence` per variant/backend cell whose result is
        not equivalent to canonical TPC-H (cell label ``v<variant>:<backend>``).
        Reuses :meth:`TPCHavocBenchmark.validate_variant_equivalence` and the
        shared :func:`find_surface_divergences` loop.
    """
    from benchbox.core.tpch import dataframe_queries as tpch_dataframe_queries
    from benchbox.core.tpch.dataframe_queries import set_parameter_overrides, set_scale_factor

    ids = query_ids if query_ids is not None else benchmark.get_implemented_queries()
    registry = benchmark.get_dataframe_queries()

    def reference_rows(query_id: int) -> list[tuple[Any, ...]]:
        return fetch_canonical_rows(connection, canonical_query(query_id))

    def candidate_cells(
        query_id: int,
    ) -> Iterable[tuple[str, Callable[[list[tuple[Any, ...]]], None]]]:
        for variant_id in range(1, 11):
            query = registry.get_or_raise(f"Q{query_id}v{variant_id}")
            for backend in backends:
                impl = query.expression_impl if backend == "expression" else query.pandas_impl

                def check(
                    reference: list[tuple[Any, ...]],
                    *,
                    impl: Any = impl,
                    backend: str = backend,
                    variant_id: int = variant_id,
                ) -> None:
                    candidate = materialize_rows(impl(contexts[backend]))
                    benchmark.validate_variant_equivalence(query_id, variant_id, reference, candidate)

                yield f"v{variant_id}:{backend}", check

    # Compare against the scale-aware defaults alone. The DataFrame Q11 default
    # is now scale-aware (0.0001 / SF), exactly like canonical qgen and the
    # unseeded production run path, so no gate-local fraction override is needed:
    # clear any ambient parameter overrides and declare the gate's scale through
    # the same product seam the run path uses. Restore both afterwards.
    previous_overrides = tpch_dataframe_queries._parameter_overrides
    previous_scale_factor = tpch_dataframe_queries._scale_factor
    set_parameter_overrides(None)
    set_scale_factor(benchmark.scale_factor)
    try:
        return find_surface_divergences(
            ids,
            reference_rows=reference_rows,
            candidate_cells=candidate_cells,
            validation_error=ValidationError,
            reference_failure_cell="v0:canonical",
        )
    finally:
        set_parameter_overrides(previous_overrides)
        set_scale_factor(previous_scale_factor)


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

    by_class: dict[str, list[SurfaceDivergence]] = {}
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


def _sort_key(key: str) -> tuple[int, int, str]:
    """Sort ``<query>_v<variant>:<backend>`` keys numerically then by backend."""
    cell, _, backend = key.partition(":")
    query, _, variant = cell.partition("_v")
    return int(query), int(variant or 0), backend


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
