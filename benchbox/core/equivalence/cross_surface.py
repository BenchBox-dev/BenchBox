"""Cross-surface SQL<->DataFrame result-equivalence gates.

A benchmark that ships both a SQL surface and a DataFrame surface has two
*independent* implementations of the same logical queries, so a divergence
between them proves at least one is wrong - a maintenance-free correctness
oracle that needs no hand-curated answer key. For every benchmark except tpch
and tpcds (which have stored expected results) and tpchavoc (which has its own
variant + DataFrame gates), this cross-surface check is the only automated
correctness oracle available today.

This module runs that oracle on a bounded small-SF DuckDB cell, reusing the
shared harness in :mod:`benchbox.core.equivalence.dataframe_surface`:
``python -m benchbox.core.equivalence.cross_surface --benchmark ssb`` (or
``make ssb-cross-surface-equivalence-report``) executes each query's SQL on
DuckDB as the trusted reference and each query's DataFrame implementation (both
shipped backends - the Polars expression family and the Pandas family) over the
SAME DuckDB-materialized data, compares each live with the reused
:class:`~benchbox.core.tpchavoc.validation.ResultValidator` (order-insensitive,
float-tolerant), and **exits non-zero** if any benchmark/query/backend cell
diverges beyond that benchmark's ``known_divergences`` baseline (empty - SQL is
the reference for its own DataFrame surface and every cell must match).

The DataFrame side executes through the real product dispatch
(:meth:`DataFrameQuery.get_impl_for_family`, the same accessor
``DataFrameAdapter.execute_query`` uses) rather than a bespoke engine, and the
comparator and the DuckDB->DataFrame data materialization are reused from the
shared harness, never forked.

Currently gated: ssb (canonical and small; SQL and DataFrame ids correspond 1:1
as ``Q1.1`` .. ``Q4.3``). Additional dual-surface benchmarks are added by
registering a :class:`CrossSurfaceGate` in :data:`GATES`.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.core.equivalence.dataframe_surface import (
    DATAFRAME_BACKENDS,
    SurfaceDivergence,
    build_dataframe_contexts_from_specs,
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
    table_specs: list[tuple[str, list[tuple[str, str]]]]


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
    backends: tuple[str, ...] = DATAFRAME_BACKENDS
    tolerance: float = 1e-10


def find_cross_surface_divergences(
    connection: Any,
    *,
    query_ids: Iterable[Any],
    reference_sql: Callable[[Any], str],
    dataframe_query: Callable[[Any], Any],
    contexts: dict[str, Any],
    validator: ResultValidator,
    backends: tuple[str, ...] = DATAFRAME_BACKENDS,
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
            :func:`build_dataframe_contexts_from_specs`, built from the SAME
            DuckDB data.
        validator: The reused result comparator.
        backends: DataFrame backends to gate; a backend a query does not
            implement is skipped (not counted as a divergence). Whether a *whole*
            gated backend is unimplemented (which would silently compare nothing)
            is detected separately via :func:`count_executed_cells`.

    Returns:
        One :class:`SurfaceDivergence` per query/backend cell whose DataFrame
        result is not equivalent to the SQL surface (cell label = backend; the
        whole-query reference failure uses cell ``"reference"``).
    """
    from benchbox.core.tpchavoc.validation import ValidationError

    def reference_rows(query_id: Any) -> list[tuple[Any, ...]]:
        return fetch_reference_rows(connection, reference_sql(query_id))

    def candidate_cells(
        query_id: Any,
    ) -> Iterable[tuple[str, Callable[[list[tuple[Any, ...]]], None]]]:
        query = dataframe_query(query_id)
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
            ) -> None:
                candidate = materialize_rows(impl(contexts[backend]))
                validator.validate_results_exact(reference, candidate, query_id, 0)

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


def build_ssb_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate SSB data, load it into in-memory DuckDB, and wire both surfaces.

    Platform/generator imports are deferred so importing this module stays cheap.
    """
    import duckdb

    from benchbox.core.ssb.benchmark import SSBBenchmark
    from benchbox.core.ssb.dataframe_queries import SSB_DATAFRAME_QUERIES
    from benchbox.core.ssb.generator import SSBDataGenerator
    from benchbox.core.ssb.schema import TABLES
    from benchbox.platforms.duckdb import DuckDBAdapter

    output_dir = Path(output_dir)
    SSBDataGenerator(scale_factor=scale_factor, output_dir=output_dir).generate_data()
    benchmark = SSBBenchmark(scale_factor=scale_factor, output_dir=output_dir)

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
            raise RuntimeError(f"SSB load failed - no rows in {empty} (stats={table_stats})")
    except Exception:
        connection.close()
        raise

    table_specs = [
        (table["name"], [(column["name"], str(column["type"])) for column in table["columns"]])
        for table in TABLES.values()
    ]
    return CrossSurfaceData(
        connection=connection,
        query_ids=list(benchmark.get_queries().keys()),
        reference_sql=lambda query_id: benchmark.get_query(query_id),
        dataframe_query=lambda query_id: SSB_DATAFRAME_QUERIES.get_or_raise(query_id),
        table_specs=table_specs,
    )


# Registry of gated benchmarks. Add a benchmark by registering its build
# function (and any classified known divergences) here.
GATES: dict[str, CrossSurfaceGate] = {
    "ssb": CrossSurfaceGate(name="ssb", build=build_ssb_duckdb),
}


def run_gate(gate: CrossSurfaceGate) -> int:
    """Run one benchmark's cross-surface gate and print a categorized report."""
    import tempfile

    from benchbox.core.tpchavoc.validation import ResultValidator

    with tempfile.TemporaryDirectory() as tmp:
        data = gate.build(EQUIVALENCE_SCALE, Path(tmp))
        connection = data.connection
        try:
            contexts = build_dataframe_contexts_from_specs(connection, data.table_specs)
            divergences = find_cross_surface_divergences(
                connection,
                query_ids=data.query_ids,
                reference_sql=data.reference_sql,
                dataframe_query=data.dataframe_query,
                contexts=contexts,
                validator=ResultValidator(tolerance=gate.tolerance),
                backends=gate.backends,
            )
            coverage = count_executed_cells(data.query_ids, data.dataframe_query, gate.backends)
        finally:
            connection.close()

    total = len(data.query_ids) * len(gate.backends)
    return _report(divergences, total, coverage, gate.known_divergences, benchmark=gate.name)


def _report(
    divergences: list[SurfaceDivergence],
    total: int,
    coverage: dict[str, int],
    known: dict[str, str],
    *,
    benchmark: str,
) -> int:
    """Print a categorized divergence report and return the gate exit code.

    Fails (non-zero) on any unclassified divergence OR any gated backend that
    implemented no queries (which would otherwise make the gate silently green
    by comparing nothing on that backend).
    """
    found = {d.key for d in divergences}
    new = sorted(found - set(known))
    resolved = sorted(set(known) - found)
    missing_backends = sorted(backend for backend, count in coverage.items() if count == 0)
    executed = sum(coverage.values())

    print(f"{benchmark} cross-surface SQL<->DataFrame equivalence @ SF={EQUIVALENCE_SCALE} (DuckDB-backed)")
    print(
        f"  compared {executed} of {total} query-backend cells "
        f"({total - executed} not implemented by the DataFrame surface) - {len(divergences)} divergent\n"
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

    if missing_backends:
        print(f"GATE FAILURE - gated backend(s) implement no queries (nothing compared): {missing_backends}")
    if new:
        print(f"GATE FAILURE - unclassified cross-surface divergences: {new}")
    if resolved:
        print(f"Previously-known divergences now equivalent - update the baseline: {resolved}")
    if not new and not resolved and not missing_backends:
        print("SQL and DataFrame surfaces are equivalent (modulo classified exceptions).")
    return 1 if (new or missing_backends) else 0


def main(argv: list[str] | None = None) -> int:
    """Run the cross-surface gate for the chosen benchmark."""
    import argparse

    parser = argparse.ArgumentParser(description="Cross-surface SQL<->DataFrame equivalence gate.")
    parser.add_argument(
        "--benchmark",
        choices=sorted(GATES),
        default="ssb",
        help="Benchmark to gate (default: ssb).",
    )
    args = parser.parse_args(argv)
    return run_gate(GATES[args.benchmark])


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
