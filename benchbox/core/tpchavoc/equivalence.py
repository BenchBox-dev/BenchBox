"""Result-equivalence gate for TPC-Havoc SQL variants.

TPC-Havoc's premise is that the ten SQL variants of each TPC-H query are
structurally diverse but *semantically equivalent* to the canonical TPC-H
query. benchbox ships :meth:`TPCHavocBenchmark.validate_variant_equivalence`,
but nothing in the default run or in CI ever called it for a real variant, so
divergences were silent (see ``_project/TODO/main/active/
tpchavoc-variant-equivalence-gate.yaml``).

This module wires that existing validator over a real, small-scale dataset:
``python -m benchbox.core.tpchavoc.equivalence`` (or
``make tpchavoc-equivalence-report``) compares every variant of every
implemented query to canonical TPC-H, prints a report, and **exits non-zero**
if any variant diverges beyond the classified baseline in
:data:`KNOWN_DIVERGENCES` (currently empty - every variant must match).

The oracle is engine-agnostic: :func:`find_divergences` takes the connection
and a rendering of both canonical and variants into a target dialect, and reuses
the SAME comparator across engines (it is never forked per engine). DuckDB at
SF=0.1 is the default and the hard, blocking gate. ``--engine postgres`` runs a
bounded *second-engine sample* against the Postgres service container: variants
are written once but run on ~20 platforms after dialect translation, so
"equivalent on DuckDB" does not imply "equivalent everywhere". The sample runs
canonical TPC-H and the variants through the SAME translation to the SAME
Postgres instance (so shared translation cancels out), excludes the variants
PostgreSQL cannot execute (POSTGRES_TPCHAVOC_SKIPS), and classifies any residue
against :data:`POSTGRES_KNOWN_DIVERGENCES`. It catches the largest class of
translation-induced divergence one engine over without gating all ~20 platforms.

``--engine datafusion`` adds a bounded *third-engine sample* on the in-process
DataFusion engine (no service container). Its execution gaps DIFFER from
Postgres's - correlated EXISTS/IN/scalar sub-query physical planning rather than
HAVING/WHERE alias and aggregate-in-window limits - so it tests whether the
translation fidelity is systematic or Postgres-specific. Variants DataFusion
cannot plan are excluded via DATAFUSION_TPCHAVOC_SKIPS; any residue is classified
against :data:`DATAFUSION_KNOWN_DIVERGENCES`. Across DuckDB, PostgreSQL, and
DataFusion every executable variant is result-equivalent: translation divergence
is systematic-zero, not engine-specific.

``--engine clickhouse`` adds a bounded *fourth-engine sample* on the in-process
ClickHouse engine (chDB / ``clickhouse-local``). It is the first sampled engine
that translates through a NATIVE, non-Postgres SQLGlot dialect
(``normalize_dialect_for_sqlglot("clickhouse") == "clickhouse"``), so the seam
renders both canonical and variants through a DIFFERENT code path than the three
Postgres-family engines. ClickHouse also differs on the result-semantic axes the
prior TODOs flagged, and unlike the first three engines it does NOT yield
systematic-zero: after excluding the variants it cannot execute
(CLICKHOUSE_TPCHAVOC_SKIPS) and running with the engine's production TPC-H session
configuration (SQL-standard NULL semantics via ``join_use_nulls=1``) AND the same
production query-time rewrites the real adapter applies (Decimal/Float casts, safe
division, the ``joined_subquery_requires_alias`` SETTINGS - see
:func:`_clickhouse_execute_transform`), a small residue of irreducible
engine-semantic RESULT differences remains, classified in
:data:`CLICKHOUSE_KNOWN_DIVERGENCES` (Decimal-vs-Float division truncation,
``SUM`` of an empty group returning 0 instead of NULL, and partial
correlated-subquery decorrelation). The seam is still faithful - every divergence
is an engine-semantic result difference or an executability gap, never a
translation bug - but the four-engine signal is "faithful across dialect
FAMILIES, modulo documented engine result-semantics", not systematic-zero.

Comparison is order-insensitive with float tolerance (the validator sorts both
sides). Because canonical TPC-H queries carry a presentational ``ORDER BY ...
LIMIT n`` top-N cut that the variant families treat inconsistently, the trailing
``LIMIT`` is stripped from both sides before comparison.

One consequence: NULL ordering/placement is deliberately NOT sampled by this
oracle. Sorting both sides is what lets variants legitimately permute row order
without being flagged, but it also normalizes away a difference that shows up only
as where NULLs land within an ``ORDER BY`` (e.g. ``NULLS FIRST`` vs ``NULLS
LAST``). Such a difference is invisible here by construction; covering it would
need a separate order-sensitive check on the subset of queries with a
NULL-bearing sort key, which is out of scope for this row-set equivalence sample.

The gate's burndown (24 divergences at the first report) resolved every
divergence class as a variant defect:

* value-distorting bugs: ``q2_v10``/``q10_v10`` clamped negative balances,
  ``q1_v8`` filtered in ``QUALIFY`` instead of ``WHERE``, ``q7_v5`` fanned a
  date-filtered-orders CTE against the full ``lineitem`` table (~4.5x revenue),
  ``q9_v10`` bucketed nations and clamped negative profit.
* ``scale-threshold``: the Q11 variants hardcoded the SF=1 ``0.0001`` value
  threshold; they now carry a ``{q11_fraction}`` token rendered with
  ``0.0001 / scale_factor`` exactly like canonical qgen.
* ``extra-column``: eight "window function" variants projected a helper
  ``rank()``/discriminator column; the window structure stays, the column no
  longer leaks into the output schema.
* ``limit-semantics``: ``14_v9`` needed ``LIMIT 1`` only because its helper
  rank column defeated ``DISTINCT``; with the column gone, ``DISTINCT``
  collapses to the canonical single row.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark(TM) H (TPC-H) - Copyright (C) Transaction Processing Performance Council.
This implementation is derived from TPC-H.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.core.tpchavoc.benchmark import TPCHavocBenchmark
from benchbox.core.tpchavoc.validation import ValidationError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from benchbox import TPCH

# Smallest scale that is discriminating for the known defect classes: at SF=0.01
# the Q2/Q10 projection bugs do not surface (no negative balances in the result)
# and Q17 is NULL, so a gate there would be vacuous. SF=0.1 catches them while
# staying ~10x cheaper than SF=1.
EQUIVALENCE_SCALE = 0.1

# Variants tolerated to diverge from canonical TPC-H at EQUIVALENCE_SCALE, with
# the reason class. Empty: the original 24-divergence burndown is complete and
# every variant must match canonical. Add an entry (with a class and a tracking
# TODO) only for a divergence that is deliberate, never to mute a regression.
# Keyed by "<query>_v<variant>".
#
# This is the DuckDB gate's baseline and MUST stay empty - DuckDB at SF=0.1 is
# the hard, blocking equivalence gate (see ``main``/``correctness-gate`` CI job).
KNOWN_DIVERGENCES: dict[str, str] = {}

# Per-engine equivalence exceptions for the *second-engine sample* (PostgreSQL),
# keyed by "<query>_v<variant>". An entry here records a divergence that is an
# irreducible engine-semantic difference (NOT a translation bug, NOT a variant
# defect) - e.g. a result shape that PostgreSQL produces differently from
# canonical TPC-H run on PostgreSQL and that cannot be reconciled in the
# translation layer. Translation bugs are fixed in the dialect seam
# (benchbox/core/tpch/benchmark.py:translate_query_text) so the fix generalizes;
# they are NEVER muted here. Variants PostgreSQL cannot execute at all are
# excluded via POSTGRES_TPCHAVOC_SKIPS, never marked equivalent.
#
# Empty: the Postgres sample (SF=0.1, both canonical and variants translated to
# the postgres dialect through the same seam) found zero divergences over the
# 203 executable variants - the translation layer is faithful and no variant is
# silently wrong on PostgreSQL while green on DuckDB.
POSTGRES_KNOWN_DIVERGENCES: dict[str, str] = {}

# Per-engine equivalence exceptions for the *third-engine sample* (DataFusion),
# keyed by "<query>_v<variant>". Same contract as POSTGRES_KNOWN_DIVERGENCES: an
# entry records an irreducible engine-semantic *result* difference, never a
# translation bug (fixed in the dialect seam) and never a variant DataFusion
# cannot execute (those are excluded via DATAFUSION_TPCHAVOC_SKIPS).
#
# Empty: the DataFusion sample (SF=0.1, both canonical and variants translated to
# the datafusion dialect - which the seam normalizes to postgres - through the
# same path) found zero *result* divergences over the 206 executable variants.
# DataFusion's gaps are confined to which variants it can plan at all (the 14
# DATAFUSION_TPCHAVOC_SKIPS), a DIFFERENT gap profile from PostgreSQL's; on the
# variants it does execute the translation layer is just as faithful. Three
# engines now agree: translation divergence is systematic-zero, not engine-specific.
DATAFUSION_KNOWN_DIVERGENCES: dict[str, str] = {}

_TRAILING_LIMIT = re.compile(r"(?is)\s+limit\s+\d+\s*;?\s*$")


@dataclass(frozen=True)
class Divergence:
    """A single variant whose result differs from the canonical TPC-H query."""

    query_id: int
    variant_id: int
    detail: str

    @property
    def key(self) -> str:
        """Stable ``<query>_v<variant>`` identifier."""
        return f"{self.query_id}_v{self.variant_id}"


def strip_top_n(sql: str) -> str:
    """Remove a trailing line comment, statement terminator, and ``LIMIT n``.

    Canonical TPC-H queries truncate to a top-N for display; the TPC-Havoc
    variant families do not do this consistently, and some variant files end the
    statement with a ``-- Variant N`` comment. The trailing comment, terminator,
    and ``LIMIT`` are normalized away on both sides before comparing the
    underlying result sets, so a variant that keeps ``LIMIT`` (e.g. ``21_v*``,
    which end ``limit 100 -- Variant N``) is compared on the same footing as one
    that drops it.
    """
    normalized = re.sub(r"\s*--[^\n]*$", "", sql.strip())
    normalized = normalized.rstrip().rstrip(";")
    return _TRAILING_LIMIT.sub("", normalized)


def _identity(sql: str) -> str:
    """Default translation: render SQL unchanged (the DuckDB-native path)."""
    return sql


def find_divergences(
    connection: Any,
    benchmark: TPCHavocBenchmark,
    canonical_query: Callable[[int], str],
    *,
    query_ids: list[int] | None = None,
    translate_variant: Callable[[str], str] | None = None,
    skip_variants: Collection[str] | None = None,
    execute_transform: Callable[[str], str] | None = None,
) -> list[Divergence]:
    """Compare every variant of each query to canonical TPC-H on ``connection``.

    Engine-agnostic: the connection/engine is injected, and ``canonical_query``
    and ``translate_variant`` are responsible for rendering both sides into the
    SAME target dialect before comparison so that shared translation cancels out
    and only genuine variant-vs-canonical differences surface. The comparator
    itself - :meth:`TPCHavocBenchmark.validate_variant_equivalence` - is reused
    verbatim across engines; it is never forked per engine.

    The default (no ``translate_variant``) is the DuckDB-native path: variants
    run as authored and canonical is whatever ``canonical_query`` returns, with
    no extra translation - so the existing DuckDB gate is unchanged. For a second
    engine (e.g. PostgreSQL), pass ``canonical_query`` that renders canonical in
    the engine's dialect (``tpch.get_query(q, dialect="postgres")``) and a
    ``translate_variant`` that renders each variant into that SAME dialect
    (``benchmark.translate_query_text(sql, "netezza", "postgres")``).

    Args:
        connection: A connection (DuckDB, or psycopg in autocommit) already
            populated with TPC-H data; must support ``execute(sql).fetchall()``.
        benchmark: The TPC-Havoc benchmark providing variants and the validator.
        canonical_query: Callable returning the canonical TPC-H SQL for a query
            id, already rendered in the target engine's dialect.
        query_ids: Subset of query ids to check; defaults to all implemented.
        translate_variant: Optional callable rendering a variant's SQL into the
            target engine's dialect. Defaults to identity (DuckDB-native).
        skip_variants: Variant keys ("<query>_v<variant>") to exclude from the
            sweep entirely - e.g. POSTGRES_TPCHAVOC_SKIPS, which the engine
            cannot execute. Excluded variants are neither run nor counted as
            divergences; they are NEVER silently marked equivalent.
        execute_transform: Optional callable applied to the FINAL SQL string of
            BOTH sides (after dialect rendering and top-N stripping) immediately
            before execution. Use to reproduce an engine's production query-time
            rewrites (e.g. ClickHouse's Decimal/Float casts + SETTINGS) so the
            sample exercises the real execution path; applied identically to
            canonical and variant, so shared transforms still cancel out. Defaults
            to identity, leaving the DuckDB/Postgres/DataFusion samples unchanged.

    Returns:
        One :class:`Divergence` per variant whose result is not equivalent to
        canonical TPC-H. Reuses :meth:`TPCHavocBenchmark.validate_variant_equivalence`.
    """
    ids = query_ids if query_ids is not None else benchmark.get_implemented_queries()
    render_variant = translate_variant if translate_variant is not None else _identity
    transform_for_engine = execute_transform if execute_transform is not None else _identity
    excluded = set(skip_variants or ())
    divergences: list[Divergence] = []
    for query_id in ids:
        try:
            original = connection.execute(transform_for_engine(strip_top_n(canonical_query(query_id)))).fetchall()
        except Exception as exc:  # noqa: BLE001 - a diagnostic must report, not crash, on a bad query
            divergences.append(Divergence(query_id, 0, f"canonical query failed: {exc}"))
            continue
        for variant_id in range(1, 11):
            if f"{query_id}_v{variant_id}" in excluded:
                continue
            try:
                variant_sql = transform_for_engine(
                    render_variant(strip_top_n(benchmark.get_query(f"{query_id}_v{variant_id}")))
                )
                variant_rows = connection.execute(variant_sql).fetchall()
                benchmark.validate_variant_equivalence(query_id, variant_id, original, variant_rows)
            except ValidationError as exc:
                divergences.append(Divergence(query_id, variant_id, str(exc)))
            except Exception as exc:  # noqa: BLE001 - surface execution/sort errors as divergences
                divergences.append(Divergence(query_id, variant_id, f"error: {exc}"))
    return divergences


def _generate_tpch(scale_factor: float, output_dir: Path) -> tuple[Path, TPCHavocBenchmark, TPCH]:
    """Generate TPC-H data and the paired benchmarks for an engine build.

    Shared by both engine builders so the (fragile) data-dir resolution lives in
    one place. Generator import is deferred to keep this module cheap to import.

    Returns:
        ``(data_dir, tpchavoc_benchmark, tpch_benchmark)``.
    """
    from benchbox import TPCH
    from benchbox.core.tpch.generator import TPCHDataGenerator

    generated = TPCHDataGenerator(scale_factor=scale_factor, output_dir=output_dir).generate()
    data_dir = next(Path(paths[0] if isinstance(paths, list) else paths).parent for paths in generated.values())
    tpchavoc = TPCHavocBenchmark(scale_factor=scale_factor, output_dir=output_dir)
    tpch = TPCH(scale_factor=scale_factor, output_dir=output_dir)
    return data_dir, tpchavoc, tpch


def build_duckdb_with_tpch(scale_factor: float, output_dir: str | Path) -> tuple[Any, TPCHavocBenchmark, TPCH]:
    """Generate TPC-H data and return a populated in-memory DuckDB connection.

    Platform/generator imports are deferred so importing this module does not
    pull DuckDB or the data generator into the core import graph.

    Returns:
        ``(connection, tpchavoc_benchmark, tpch_benchmark)``.
    """
    import duckdb

    from benchbox.platforms.duckdb import DuckDBAdapter

    data_dir, tpchavoc, tpch = _generate_tpch(scale_factor, Path(output_dir))

    connection = duckdb.connect(":memory:")
    for statement in tpchavoc.get_create_tables_sql(dialect="duckdb").strip().split(";"):
        if statement.strip():
            connection.execute(statement.strip())
    DuckDBAdapter(database=":memory:").load_data(tpchavoc, connection, data_dir)
    return connection, tpchavoc, tpch


# The second engine sampled beyond DuckDB. PostgreSQL is the natural first pick:
# a Postgres 17 service container already exists in CI (postgres-integration job)
# and POSTGRES_TPCHAVOC_SKIPS bounds which variants are even executable on it.
POSTGRES_TARGET_DIALECT = "postgres"

# Per-statement ceiling for the Postgres sample. Indexed at SF=0.1 every variant
# runs in <5s; the ceiling only fences a pathological plan so the sample reports
# a bounded error instead of hanging the (time-boxed) CI job.
POSTGRES_STATEMENT_TIMEOUT_MS = 120_000

# Standard TPC-H primary-key / foreign-key indexes. The generated DDL carries no
# keys or indexes (it targets columnar engines), so PostgreSQL otherwise plans
# correlated-subquery variants as O(n*m) nested loops. These indexes are a
# performance setup detail only - they never change query *results*, just keep
# the sample tractable inside CI's budget.
POSTGRES_TPCH_INDEXES: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS pk_region ON region(r_regionkey)",
    "CREATE UNIQUE INDEX IF NOT EXISTS pk_nation ON nation(n_nationkey)",
    "CREATE UNIQUE INDEX IF NOT EXISTS pk_part ON part(p_partkey)",
    "CREATE UNIQUE INDEX IF NOT EXISTS pk_supplier ON supplier(s_suppkey)",
    "CREATE UNIQUE INDEX IF NOT EXISTS pk_partsupp ON partsupp(ps_partkey, ps_suppkey)",
    "CREATE UNIQUE INDEX IF NOT EXISTS pk_customer ON customer(c_custkey)",
    "CREATE UNIQUE INDEX IF NOT EXISTS pk_orders ON orders(o_orderkey)",
    "CREATE INDEX IF NOT EXISTS ix_lineitem_orderkey ON lineitem(l_orderkey)",
    "CREATE INDEX IF NOT EXISTS ix_lineitem_partkey ON lineitem(l_partkey)",
    "CREATE INDEX IF NOT EXISTS ix_lineitem_suppkey ON lineitem(l_suppkey)",
    "CREATE INDEX IF NOT EXISTS ix_partsupp_suppkey ON partsupp(ps_suppkey)",
    "CREATE INDEX IF NOT EXISTS ix_orders_custkey ON orders(o_custkey)",
)

_TPCH_TABLES = ("lineitem", "orders", "partsupp", "part", "customer", "supplier", "nation", "region")


def postgres_connection_config() -> dict[str, Any]:
    """PostgreSQL connection settings for the equivalence sample.

    Defaults match the Postgres service container in the ``postgres-integration``
    CI job (and the live integration tests); each is overridable via the
    standard ``PG*``/``POSTGRES_*`` environment variables for local runs.
    """
    import os

    return {
        "host": os.environ.get("PGHOST", os.environ.get("POSTGRES_HOST", "localhost")),
        "port": int(os.environ.get("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))),
        "username": os.environ.get("PGUSER", os.environ.get("POSTGRES_USER", "benchbox")),
        "password": os.environ.get("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "benchbox")),
        "database": os.environ.get("PGDATABASE", os.environ.get("POSTGRES_DB", "benchbox_test")),
    }


def build_postgres_with_tpch(
    scale_factor: float,
    output_dir: str | Path,
    *,
    connection_config: dict[str, Any] | None = None,
) -> tuple[Any, TPCHavocBenchmark, TPCH]:
    """Generate TPC-H data and return a populated PostgreSQL connection.

    Mirrors :func:`build_duckdb_with_tpch` for the second engine. The returned
    connection is in autocommit mode with a statement timeout, so the per-query
    error isolation in :func:`find_divergences` works (a failed statement aborts
    only itself, not the rest of the sweep). Platform/generator imports are
    deferred so importing this module stays cheap.

    Returns:
        ``(connection, tpchavoc_benchmark, tpch_benchmark)``.
    """
    from benchbox.platforms.postgresql import PostgreSQLAdapter

    data_dir, tpchavoc, tpch = _generate_tpch(scale_factor, Path(output_dir))

    # The per-statement ceiling is applied by the adapter at connect time (it
    # injects `-c statement_timeout=...`), not as a post-hoc SET, so the harness
    # does not have to know Postgres GUC syntax.
    config = {
        **(connection_config or postgres_connection_config()),
        "statement_timeout": POSTGRES_STATEMENT_TIMEOUT_MS,
    }
    adapter = PostgreSQLAdapter(**config)
    adapter.skip_database_management = True
    connection = adapter.create_connection()

    try:
        # Idempotent setup: drop any prior TPC-H tables so repeated runs against a
        # persistent database start clean (CI's container DB is already fresh).
        cursor = connection.cursor()
        for table in _TPCH_TABLES:
            cursor.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
        connection.commit()
        cursor.close()

        adapter.create_schema(tpchavoc, connection)
        # PostgreSQLAdapter.load_data swallows per-file COPY failures (logs, rolls
        # back, records 0 rows). A silent empty/partial load would make every
        # variant compare empty-vs-empty and report a FALSE green, so verify each
        # table actually loaded rows before sampling.
        table_stats, _, _ = adapter.load_data(tpchavoc, connection, data_dir)
        empty = [table for table in _TPCH_TABLES if table_stats.get(table, 0) <= 0]
        if empty:
            raise RuntimeError(f"PostgreSQL TPC-H load failed - no rows in {empty} (stats={table_stats})")

        # End the load transaction before switching to autocommit for the sweep,
        # so a failed statement aborts only itself (per-query error isolation).
        connection.rollback()
        connection.autocommit = True
        for index_sql in POSTGRES_TPCH_INDEXES:
            connection.execute(index_sql)
        connection.execute("ANALYZE")
    except Exception:
        connection.close()
        raise
    return connection, tpchavoc, tpch


def _report(
    divergences: list[Divergence],
    total: int,
    known: dict[str, str],
    *,
    engine_label: str,
    baseline_name: str,
) -> int:
    """Print a categorized divergence report and return the gate exit code.

    Shared by every engine so the comparator/report is never forked. Returns
    non-zero only when a divergence is unclassified (i.e. not in ``known``).
    """
    found = {d.key for d in divergences}
    new = sorted(found - set(known), key=_sort_key)
    resolved = sorted(set(known) - found, key=_sort_key)

    print(f"TPC-Havoc variant equivalence vs canonical TPC-H @ SF={EQUIVALENCE_SCALE} ({engine_label})")
    print(f"  checked {total} variants - {len(divergences)} divergent, {total - len(divergences)} equivalent\n")

    by_class: dict[str, list[Divergence]] = {}
    for divergence in sorted(divergences, key=lambda d: _sort_key(d.key)):
        klass = known.get(divergence.key, "UNCLASSIFIED")
        by_class.setdefault(klass, []).append(divergence)
    for klass in sorted(by_class):
        print(f"  [{klass}]")
        for divergence in by_class[klass]:
            print(f"    {divergence.key}: {divergence.detail}")
        print()

    if new:
        print(f"GATE FAILURE - unclassified divergences from canonical TPC-H: {new}")
    if resolved:
        print(f"Previously-known divergences now equivalent - update {baseline_name}: {resolved}")
    if not new and not resolved:
        print("All variants equivalent to canonical TPC-H (modulo classified exceptions).")
    return 1 if new else 0


def run_duckdb_gate() -> int:
    """The hard, blocking DuckDB equivalence gate (KNOWN_DIVERGENCES must be empty)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        connection, tpchavoc, tpch = build_duckdb_with_tpch(EQUIVALENCE_SCALE, tmp)
        try:
            divergences = find_divergences(connection, tpchavoc, lambda q: tpch.get_query(q))
        finally:
            connection.close()

    total = len(tpchavoc.get_implemented_queries()) * 10
    return _report(
        divergences,
        total,
        KNOWN_DIVERGENCES,
        engine_label="DuckDB",
        baseline_name="KNOWN_DIVERGENCES",
    )


def find_postgres_divergences(
    connection: Any,
    tpchavoc: TPCHavocBenchmark,
    tpch: TPCH,
    *,
    query_ids: list[int] | None = None,
) -> list[Divergence]:
    """Run the PostgreSQL equivalence sweep with the canonical Postgres wiring.

    Single source of truth for *how* the Postgres sample is run - both the CLI
    (:func:`run_postgres_sample`) and the integration test call this so they
    cannot drift. Canonical and variants are both translated to the postgres
    dialect through the SAME seam, and POSTGRES_TPCHAVOC_SKIPS variants are
    excluded (never marked equivalent).
    """
    from benchbox.sql_compat.rules.execution_filter.postgres_tpchavoc import POSTGRES_TPCHAVOC_SKIPS

    return find_divergences(
        connection,
        tpchavoc,
        lambda q: tpch.get_query(q, dialect=POSTGRES_TARGET_DIALECT),
        query_ids=query_ids,
        translate_variant=lambda sql: tpchavoc.translate_query_text(sql, "netezza", POSTGRES_TARGET_DIALECT),
        skip_variants=set(POSTGRES_TPCHAVOC_SKIPS),
    )


def run_postgres_sample() -> int:
    """Run the second-engine (PostgreSQL) equivalence sample.

    Both canonical TPC-H and every variant are translated to the postgres dialect
    through the SAME seam, then compared on the SAME Postgres instance, so shared
    translation cancels out (anti-pattern: never compare a Postgres variant to a
    DuckDB canonical). Variants PostgreSQL cannot execute are excluded via
    POSTGRES_TPCHAVOC_SKIPS - they are never marked equivalent. A divergence is
    classified against POSTGRES_KNOWN_DIVERGENCES; an unclassified one returns
    non-zero, but this is a *sample* run from the non-blocking postgres job - the
    DuckDB gate remains the hard blocker.
    """
    import tempfile

    import psycopg

    from benchbox.sql_compat.rules.execution_filter.postgres_tpchavoc import POSTGRES_TPCHAVOC_SKIPS

    try:
        with tempfile.TemporaryDirectory() as tmp:
            connection, tpchavoc, tpch = build_postgres_with_tpch(EQUIVALENCE_SCALE, tmp)
            try:
                divergences = find_postgres_divergences(connection, tpchavoc, tpch)
            finally:
                connection.close()
    except psycopg.OperationalError as exc:
        # ONLY an unreachable / unusable server is a skip. Schema, load (incl. the
        # row-count guard), translation, and sweep failures must propagate as real
        # failures - otherwise this report could not catch the regressions it exists
        # to surface.
        print(f"PostgreSQL equivalence sample SKIPPED - could not connect to PostgreSQL: {exc}")
        return 0

    # Exclude un-executable variants from the denominator too: they are bounded
    # out of scope, not failures.
    total = len(tpchavoc.get_implemented_queries()) * 10 - len(POSTGRES_TPCHAVOC_SKIPS)
    return _report(
        divergences,
        total,
        POSTGRES_KNOWN_DIVERGENCES,
        engine_label="PostgreSQL",
        baseline_name="POSTGRES_KNOWN_DIVERGENCES",
    )


# The third engine sampled beyond DuckDB and PostgreSQL. DataFusion is the
# cheapest contrast: it is in-process (no service container), and its execution
# gaps DIFFER from PostgreSQL's (correlated EXISTS/IN/scalar sub-query physical
# planning rather than HAVING/WHERE alias and aggregate-in-window limits), so the
# sample adds information about whether translation divergence is systematic or
# engine-specific. The seam normalizes "datafusion" to the postgres dialect, so
# both sides go through the same translation and shared translation cancels out.
DATAFUSION_TARGET_DIALECT = "datafusion"


def _close_quietly(connection: Any) -> None:
    """Close a connection if it exposes ``close()``.

    DataFusion's in-process session has no ``close()`` (it is GC'd), so callers
    that mirror the DB-API ``finally: connection.close()`` shape stay uniform
    across engines without special-casing DataFusion at every call site.
    """
    close = getattr(connection, "close", None)
    if callable(close):
        close()


def build_datafusion_with_tpch(scale_factor: float, output_dir: str | Path) -> tuple[Any, TPCHavocBenchmark, TPCH]:
    """Generate TPC-H data and return a populated in-process DataFusion connection.

    Mirrors :func:`build_duckdb_with_tpch`/:func:`build_postgres_with_tpch` for the
    third engine, reusing ``DataFusionAdapter.load_data`` (which now ingests the
    field-terminating trailing delimiter in raw TPC-H ``.tbl`` files). DataFusion is
    in-process, so there is no service container and no per-statement transaction to
    isolate: ``ctx.sql(...)`` failures raise per query and are caught by
    :func:`find_divergences` without poisoning the sweep. Each table's row count is
    verified (>0) so a partial load cannot produce a FALSE green by comparing
    empty-vs-empty (the adapter's loader raises on its own load errors).

    Returns:
        ``(connection, tpchavoc_benchmark, tpch_benchmark)``.
    """
    from benchbox.platforms.datafusion import DataFusionAdapter

    data_dir, tpchavoc, tpch = _generate_tpch(scale_factor, Path(output_dir))

    adapter = DataFusionAdapter(working_dir=str(Path(output_dir) / "datafusion_working"))
    connection = adapter.create_connection()
    try:
        adapter.create_schema(tpchavoc, connection)
        table_stats, _, _ = adapter.load_data(tpchavoc, connection, data_dir)
        empty = [table for table in _TPCH_TABLES if table_stats.get(table, 0) <= 0]
        if empty:
            raise RuntimeError(f"DataFusion TPC-H load failed - no rows in {empty} (stats={table_stats})")
    except Exception:
        _close_quietly(connection)
        raise
    return connection, tpchavoc, tpch


def find_datafusion_divergences(
    connection: Any,
    tpchavoc: TPCHavocBenchmark,
    tpch: TPCH,
    *,
    query_ids: list[int] | None = None,
) -> list[Divergence]:
    """Run the DataFusion equivalence sweep with the canonical DataFusion wiring.

    Single source of truth for *how* the DataFusion sample is run - both the CLI
    (:func:`run_datafusion_sample`) and the integration test call this so they
    cannot drift. Canonical and variants are both translated to the datafusion
    dialect through the SAME seam (the seam normalizes datafusion -> postgres for
    SQLGlot), and DATAFUSION_TPCHAVOC_SKIPS variants are excluded (never marked
    equivalent).
    """
    from benchbox.platforms.datafusion_query_transformer import DataFusionQueryTransformer
    from benchbox.sql_compat.rules.execution_filter.datafusion_tpchavoc import DATAFUSION_TPCHAVOC_SKIPS

    transformer = DataFusionQueryTransformer(verbose=False)

    def _canonical_sql(query_id: int) -> str:
        sql = tpch.get_query(query_id, dialect=DATAFUSION_TARGET_DIALECT)
        return transformer.transform(sql, query_id=query_id)

    return find_divergences(
        connection,
        tpchavoc,
        _canonical_sql,
        query_ids=query_ids,
        translate_variant=lambda sql: tpchavoc.translate_query_text(sql, "netezza", DATAFUSION_TARGET_DIALECT),
        skip_variants=set(DATAFUSION_TPCHAVOC_SKIPS),
    )


def run_datafusion_sample() -> int:
    """Run the third-engine (DataFusion) equivalence sample.

    Both canonical TPC-H and every variant are translated to the datafusion
    dialect through the SAME seam, then compared on the SAME in-process DataFusion
    session, so shared translation cancels out (anti-pattern: never compare a
    DataFusion variant to a DuckDB or Postgres canonical). Variants DataFusion
    cannot execute are excluded via DATAFUSION_TPCHAVOC_SKIPS - they are never
    marked equivalent. A divergence is classified against DATAFUSION_KNOWN_DIVERGENCES;
    an unclassified one returns non-zero, but this is a *sample* run - the DuckDB
    gate remains the hard blocker.

    DataFusion is in-process, so the only "engine unusable" case is the library
    not being installed; that alone is a clean skip (mirroring the Postgres
    sample's connect-only skip). Schema, load (incl. the row-count guard),
    translation, and sweep failures all propagate as real failures.
    """
    import tempfile

    from benchbox.sql_compat.rules.execution_filter.datafusion_tpchavoc import DATAFUSION_TPCHAVOC_SKIPS

    try:
        import datafusion  # noqa: F401
    except ImportError as exc:
        print(f"DataFusion equivalence sample SKIPPED - DataFusion not installed: {exc}")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        connection, tpchavoc, tpch = build_datafusion_with_tpch(EQUIVALENCE_SCALE, tmp)
        try:
            divergences = find_datafusion_divergences(connection, tpchavoc, tpch)
        finally:
            _close_quietly(connection)

    # Exclude un-executable variants from the denominator too: they are bounded
    # out of scope, not failures.
    total = len(tpchavoc.get_implemented_queries()) * 10 - len(DATAFUSION_TPCHAVOC_SKIPS)
    return _report(
        divergences,
        total,
        DATAFUSION_KNOWN_DIVERGENCES,
        engine_label="DataFusion",
        baseline_name="DATAFUSION_KNOWN_DIVERGENCES",
    )


# The fourth engine sampled beyond DuckDB, PostgreSQL, and DataFusion. ClickHouse
# is the first sampled engine whose SQLGlot dialect is NOT normalized to postgres
# (normalize_dialect_for_sqlglot("clickhouse") == "clickhouse"), so both canonical
# and variants are rendered through a DIFFERENT seam code path than the three
# Postgres-family engines - the whole point of the choice. It runs in-process via
# chDB (clickhouse-local), so like DataFusion there is no service container.
CLICKHOUSE_TARGET_DIALECT = "clickhouse"

# Benchmark type passed to ClickHouseTuningMixin.configure_for_benchmark so the
# sample runs ClickHouse with the SAME session configuration the real TPC-H /
# TPC-Havoc ClickHouse benchmark uses (rather than a hand-rolled subset that could
# drift). Two of those settings are load-bearing for this oracle:
#   * join_use_nulls=1: ClickHouse's DEFAULT join_use_nulls=0 fills unmatched
#     LEFT/RIGHT JOIN rows with column-type DEFAULTS (0, '') instead of NULL - a
#     documented departure from SQL-standard outer-join semantics that NO other
#     sampled engine has. Canonical TPC-H and the variants are written for standard
#     NULL semantics (they pass the DuckDB/Postgres/DataFusion samples, all of which
#     use them), so the anti-join variants (`LEFT JOIN ... WHERE x IS NULL`) would
#     otherwise diverge purely from this config default. join_use_nulls=1 configures
#     ClickHouse to the standard semantics the benchmark assumes, isolating
#     translation fidelity and the deeper result-semantic differences. This is NOT
#     used to mute a divergence: the residual CLICKHOUSE_KNOWN_DIVERGENCES are still
#     reported, and the JOIN-NULL default is itself recorded as an engine-semantic
#     difference in the four-engine conclusion.
#   * allow_experimental_correlated_subqueries=1: lets ClickHouse plan the
#     correlated-subquery variants it can (the rest raise NOT_IMPLEMENTED and are in
#     CLICKHOUSE_TPCHAVOC_SKIPS), matching production so the skip-list and divergence
#     classification reflect the real engine configuration.
# Verified: configure_for_benchmark and a hand-applied {join_use_nulls:1} produce an
# IDENTICAL divergence/skip surface at SF=0.1, so reusing it adds production fidelity
# (and validated SET application) without changing the classification.
CLICKHOUSE_BENCHMARK_TYPE = "tpch"

# Per-engine equivalence exceptions for the *fourth-engine sample* (ClickHouse),
# keyed by "<query>_v<variant>". Same contract as POSTGRES_/DATAFUSION_KNOWN_
# DIVERGENCES: an entry records an irreducible engine-semantic *result* difference
# - ClickHouse executes the variant but computes a different answer than canonical
# TPC-H run on ClickHouse, and the difference cannot be reconciled in the
# translation layer (which is faithful). It is NEVER a translation bug (those are
# fixed in the dialect seam) and NEVER a variant ClickHouse cannot execute (those
# are excluded via CLICKHOUSE_TPCHAVOC_SKIPS, never marked equivalent).
#
# Unlike the three Postgres-family engines (all empty), ClickHouse - the first
# sampled engine on a NATIVE non-Postgres dialect - is NOT systematic-zero. The
# residue is three documented ClickHouse result-semantic classes:
#   * decimal-division-truncation: ClickHouse `SUM(decimal)/COUNT` keeps the
#     operand's Decimal scale, truncating an average that the variant computes as
#     SUM/COUNT, whereas canonical `AVG(...)` returns full Float64 precision.
#   * sum-empty-group-zero: ClickHouse `SUM`/`sumIf` over an all-filtered group
#     returns 0, not NULL, so variants that emulate a WHERE filter with
#     `SUM(...) FILTER(...)` + `HAVING <agg> IS NOT NULL` never drop the empty
#     groups canonical's WHERE removes (extra rows).
#   * correlated-subquery-decorrelation: ClickHouse's (partial, experimental)
#     correlated-subquery decorrelation computes a different result than the
#     standard-SQL semantics for these shapes (a correlated scalar COUNT returns
#     NULL for an empty correlation; a doubly-correlated NOT EXISTS returns a
#     different row set).
CLICKHOUSE_KNOWN_DIVERGENCES: dict[str, str] = {
    "1_v4": "decimal-division-truncation",
    "2_v8": "correlated-subquery-decorrelation",
    "3_v7": "sum-empty-group-zero",
    "7_v7": "sum-empty-group-zero",
    "10_v7": "sum-empty-group-zero",
    "10_v8": "sum-empty-group-zero",
    "13_v1": "correlated-subquery-decorrelation",
}


def build_clickhouse_with_tpch(scale_factor: float, output_dir: str | Path) -> tuple[Any, TPCHavocBenchmark, TPCH]:
    """Generate TPC-H data and return a populated in-process ClickHouse connection.

    Mirrors :func:`build_datafusion_with_tpch` for the fourth engine, reusing
    ``ClickHouseLocalAdapter`` (embedded chDB) and its ``load_data`` (which ingests
    the raw TPC-H ``.tbl`` files via ClickHouse's native CSV reader). The chDB
    client exposes ``execute(sql).fetchall()`` and raises per query, so the
    per-query error isolation in :func:`find_divergences` works without an
    autocommit transaction. The adapter's own ``configure_for_benchmark`` is
    applied with :data:`CLICKHOUSE_BENCHMARK_TYPE` so the sample runs with the SAME
    validated session configuration as the real ClickHouse TPC-H benchmark (notably
    SQL-standard ``join_use_nulls=1`` and ``allow_experimental_correlated_subqueries``).
    Each table's row count is verified (>0) so a partial load cannot produce a
    FALSE green by comparing empty-vs-empty. MergeTree ``ORDER BY`` (derived from
    the PK by the adapter) is physical layout only and never changes results.

    Returns:
        ``(connection, tpchavoc_benchmark, tpch_benchmark)``.
    """
    from benchbox.platforms.clickhouse_local import ClickHouseLocalAdapter

    data_dir, tpchavoc, tpch = _generate_tpch(scale_factor, Path(output_dir))

    adapter = ClickHouseLocalAdapter(database_path=str(Path(output_dir) / "clickhouse_store"))
    # Core/programmatic use: do not let the adapter try to manage (drop/create) a
    # database; we create the schema directly on the fresh embedded store.
    adapter.skip_database_management = True
    connection = adapter.create_connection()
    try:
        adapter.create_schema(tpchavoc, connection)
        table_stats, _, _ = adapter.load_data(tpchavoc, connection, data_dir)
        empty = [table for table in _TPCH_TABLES if table_stats.get(table, 0) <= 0]
        if empty:
            raise RuntimeError(f"ClickHouse TPC-H load failed - no rows in {empty} (stats={table_stats})")
        adapter.configure_for_benchmark(connection, CLICKHOUSE_BENCHMARK_TYPE)
    except Exception:
        _close_quietly(connection)
        raise
    return connection, tpchavoc, tpch


def _clickhouse_execute_transform(sql: str) -> str:
    """Apply the SAME query-time rewrites the production ClickHouse adapter runs.

    ``ClickHouseWorkloadMixin.execute_query`` rewrites every query through
    ``ClickHouseQueryTransformer.transform`` (Decimal/Float casts + safe division)
    and then ``add_query_settings`` (the ``joined_subquery_requires_alias = 0``
    SETTINGS clause) before executing it. Reusing that exact sequence here makes the
    fourth-engine sample exercise the real execution path rather than the raw SQLGlot
    translation; it is applied identically to canonical and variant, so shared
    transforms cancel out and only genuine variant-vs-canonical differences surface.
    """
    from benchbox.platforms.clickhouse.query_transformer import ClickHouseQueryTransformer

    transformer = ClickHouseQueryTransformer()
    return transformer.add_query_settings(transformer.transform(sql))


def find_clickhouse_divergences(
    connection: Any,
    tpchavoc: TPCHavocBenchmark,
    tpch: TPCH,
    *,
    query_ids: list[int] | None = None,
) -> list[Divergence]:
    """Run the ClickHouse equivalence sweep with the canonical ClickHouse wiring.

    Single source of truth for *how* the ClickHouse sample is run - both the CLI
    (:func:`run_clickhouse_sample`) and the integration test call this so they
    cannot drift. Canonical and variants are both translated to the NATIVE
    clickhouse dialect through the SAME seam (NOT normalized to postgres), then
    run through the SAME production query-time transforms the real ClickHouse
    adapter applies (see :func:`_clickhouse_execute_transform`), and
    CLICKHOUSE_TPCHAVOC_SKIPS variants are excluded (never marked equivalent).
    """
    from benchbox.sql_compat.rules.execution_filter.clickhouse_tpchavoc import CLICKHOUSE_TPCHAVOC_SKIPS

    return find_divergences(
        connection,
        tpchavoc,
        lambda q: tpch.get_query(q, dialect=CLICKHOUSE_TARGET_DIALECT),
        query_ids=query_ids,
        translate_variant=lambda sql: tpchavoc.translate_query_text(sql, "netezza", CLICKHOUSE_TARGET_DIALECT),
        skip_variants=set(CLICKHOUSE_TPCHAVOC_SKIPS),
        execute_transform=_clickhouse_execute_transform,
    )


def run_clickhouse_sample() -> int:
    """Run the fourth-engine (ClickHouse) equivalence sample.

    Both canonical TPC-H and every variant are translated to the NATIVE clickhouse
    dialect through the SAME seam, then compared on the SAME in-process chDB
    instance, so shared translation cancels out (anti-pattern: never compare a
    ClickHouse variant to a DuckDB/Postgres/DataFusion canonical). Variants
    ClickHouse cannot execute are excluded via CLICKHOUSE_TPCHAVOC_SKIPS - they are
    never marked equivalent. A divergence is classified against
    CLICKHOUSE_KNOWN_DIVERGENCES (non-empty: ClickHouse's native dialect surfaces
    real engine-semantic result differences); an unclassified one returns
    non-zero, but this is a *sample* run - the DuckDB gate remains the hard blocker.

    ClickHouse runs in-process via chDB, so the only "engine unusable" case is chDB
    not being installed; that alone is a clean skip (mirroring the DataFusion
    sample). Schema, load (incl. the row-count guard), translation, and sweep
    failures all propagate as real failures.
    """
    import tempfile

    from benchbox.sql_compat.rules.execution_filter.clickhouse_tpchavoc import CLICKHOUSE_TPCHAVOC_SKIPS

    try:
        import chdb  # noqa: F401
    except ImportError as exc:
        print(f"ClickHouse equivalence sample SKIPPED - chDB (clickhouse-local) not installed: {exc}")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        connection, tpchavoc, tpch = build_clickhouse_with_tpch(EQUIVALENCE_SCALE, tmp)
        try:
            divergences = find_clickhouse_divergences(connection, tpchavoc, tpch)
        finally:
            _close_quietly(connection)

    # Exclude un-executable variants from the denominator too: they are bounded
    # out of scope, not failures.
    total = len(tpchavoc.get_implemented_queries()) * 10 - len(CLICKHOUSE_TPCHAVOC_SKIPS)
    return _report(
        divergences,
        total,
        CLICKHOUSE_KNOWN_DIVERGENCES,
        engine_label="ClickHouse",
        baseline_name="CLICKHOUSE_KNOWN_DIVERGENCES",
    )


def main(argv: list[str] | None = None) -> int:
    """Generate data, run the oracle for the chosen engine, and print a report.

    ``--engine duckdb`` (default) is the hard, blocking gate. ``--engine
    postgres``, ``--engine datafusion``, and ``--engine clickhouse`` run the
    bounded second-, third-, and fourth-engine samples described in
    :func:`run_postgres_sample`, :func:`run_datafusion_sample`, and
    :func:`run_clickhouse_sample`.
    """
    import argparse

    parser = argparse.ArgumentParser(description="TPC-Havoc variant-equivalence oracle.")
    parser.add_argument(
        "--engine",
        choices=("duckdb", "postgres", "datafusion", "clickhouse"),
        default="duckdb",
        help="SQL engine to sample (default: duckdb, the hard gate).",
    )
    args = parser.parse_args(argv)
    if args.engine == "postgres":
        return run_postgres_sample()
    if args.engine == "datafusion":
        return run_datafusion_sample()
    if args.engine == "clickhouse":
        return run_clickhouse_sample()
    return run_duckdb_gate()


def _sort_key(key: str) -> tuple[int, int]:
    """Sort ``<query>_v<variant>`` keys numerically."""
    query, variant = key.split("_v")
    return int(query), int(variant)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
