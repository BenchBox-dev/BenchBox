"""StarRocks DDL Generator.

Generates the physical-tuning clauses of a StarRocks CREATE TABLE statement:
- ``DISTRIBUTED BY HASH(...) BUCKETS N`` for data sharding across BE nodes
  (StarRocks requires an explicit distribution key for a working table -- this
  is the engine-mandatory baseline, emitted even when no tuning is configured)
- ``PARTITION BY (...)`` for expression/range partitioning
- ``ORDER BY (...)`` for the sort key

StarRocks and Apache Doris share the same MPP DISTRIBUTED-BY / PARTITION-BY
lineage, so this generator is modelled closely on
``core.tuning.generators.doris.DorisDDLGenerator``. The differences that matter
for StarRocks:

- Bucket default is 8 (StarRocks' historical BenchBox default), not Doris' 10.
- Sort keys render as a dedicated ``ORDER BY (...)`` clause (StarRocks has a
  first-class sort-key clause), rather than being folded into ``DUPLICATE KEY``.
- The table's key model (``DUPLICATE KEY`` / ``PRIMARY KEY``) is NOT chosen
  here: StarRocks derives it from the source schema's primary key during the
  workload's DuckDB->StarRocks DDL rewrite (see
  ``benchbox/platforms/starrocks/workload.py``), which this generator does not
  see. This generator owns only the tuning clauses (partition / distribution /
  sort), keeping it the single renderer for those while the workload keeps the
  key-model selection it already had.

Unlike Doris, this generator deliberately carries NO per-benchmark default
lookup tables: every clause is derived purely from the configured
``TableTuning`` columns. When no distribution column is configured, callers
fall back to the engine-mandatory ``DISTRIBUTED BY HASH(<first_column>)``
baseline (rendered via :meth:`render_distribution_clause`) so untuned tables
keep their historical, byte-identical DDL.

Example:
    >>> from benchbox.core.tuning.generators.starrocks import StarRocksDDLGenerator
    >>> generator = StarRocksDDLGenerator()
    >>> clauses = generator.generate_tuning_clauses(table_tuning)
    >>> emit(clauses.distribute_by)  # "l_orderkey"
    >>> emit(clauses.order_by)       # "l_orderkey, l_linenumber"

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from benchbox.core.tuning.ddl_generator import (
    BaseDDLGenerator,
    ColumnDefinition,
    TuningClauses,
)

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        TableTuning,
    )

logger = logging.getLogger(__name__)

# StarRocks' historical BenchBox default bucket count for the engine-mandatory
# distribution clause. Kept at 8 so untuned CREATE TABLE output stays
# byte-identical to the adapter's previous bespoke injection.
DEFAULT_BUCKET_COUNT = 8


class StarRocksDDLGenerator(BaseDDLGenerator):
    """DDL generator for StarRocks physical tuning.

    Renders the three tuned clauses StarRocks accepts at CREATE TABLE time:

    StarRocks Tuning Mapping:
    - DISTRIBUTION -> ``DISTRIBUTED BY HASH(col) BUCKETS N`` (data sharding)
    - PARTITIONING -> ``PARTITION BY (...)`` (expression partitioning)
    - SORTING      -> ``ORDER BY (...)`` (sort key)
    - CLUSTERING   -> Logged only (StarRocks has no separate clustering clause)

    ``DISTRIBUTED BY HASH`` is engine-mandatory: StarRocks refuses a table with
    no distribution key. The tuned distribution column, when configured,
    overrides the first-column default the workload otherwise supplies.

    Example DDL (standalone, tuning clauses only -- the key model is added by
    the workload's DDL rewrite):
        CREATE TABLE lineitem (
            `l_orderkey` BIGINT,
            `l_shipdate` DATE,
            ...
        )
        PARTITION BY (l_shipdate)
        DISTRIBUTED BY HASH(`l_orderkey`) BUCKETS 8
        ORDER BY (l_orderkey, l_linenumber);
    """

    IDENTIFIER_QUOTE = "`"
    SUPPORTS_IF_NOT_EXISTS = True
    STATEMENT_TERMINATOR = ";"

    SUPPORTED_TUNING_TYPES = frozenset({"partitioning", "sorting", "distribution"})

    def __init__(self, default_bucket_count: int = DEFAULT_BUCKET_COUNT):
        """Initialize the StarRocks DDL generator.

        Args:
            default_bucket_count: Number of hash buckets used for the
                ``DISTRIBUTED BY HASH`` clause. Defaults to 8 to preserve the
                historical engine-mandatory baseline.
        """
        self._default_bucket_count = default_bucket_count

    @property
    def platform_name(self) -> str:
        return "starrocks"

    # ── Clause renderers (single source of the clause strings) ────────────
    # Both generate_tuning_clauses/generate_create_table_ddl (dry-run preview)
    # and the workload's _optimize_table_definition (real execution) render
    # through these helpers, so preview and execution can never disagree on the
    # clause text.

    def render_distribution_clause(self, column: str, buckets: int | None = None) -> str:
        """Render ``DISTRIBUTED BY HASH(`col`) BUCKETS N``.

        The hash column is always backtick-quoted (StarRocks convention, and
        required to keep the engine-mandatory baseline byte-identical to the
        adapter's previous injection).
        """
        bucket_count = self._default_bucket_count if buckets is None else buckets
        return f"DISTRIBUTED BY HASH(`{column}`) BUCKETS {bucket_count}"

    def render_partition_clause(self, partition_by: str) -> str:
        """Render ``PARTITION BY (...)`` from a comma-joined column expression."""
        return f"PARTITION BY ({partition_by})"

    def render_order_by_clause(self, order_by: str) -> str:
        """Render ``ORDER BY (...)`` (StarRocks sort key) from a column list."""
        return f"ORDER BY ({order_by})"

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        """Generate StarRocks tuning clauses.

        Produces TuningClauses with:
        - ``distribute_by``: the hash distribution column (bare name)
        - ``additional_clauses``: the rendered ``DISTRIBUTED BY HASH`` clause
        - ``partition_by``: ``PARTITION BY`` column expression
        - ``order_by``: sort-key column list (``ORDER BY``)

        All values derive purely from ``table_tuning`` -- there are no
        per-benchmark defaults. A ``table_tuning`` with no distribution column
        yields no distribution clause here; the workload supplies the
        engine-mandatory first-column baseline in that case.

        Args:
            table_tuning: Table tuning configuration.
            platform_opts: Platform-specific options (unused; accepted for
                protocol parity).

        Returns:
            TuningClauses with StarRocks-specific configuration.
        """
        clauses = TuningClauses()

        if not table_tuning:
            return clauses

        from benchbox.core.tuning.interface import TuningType

        # ── DISTRIBUTED BY HASH (from DISTRIBUTION tuning) ──
        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns:
            sorted_cols = sorted(distribution_columns, key=lambda c: c.order)
            # StarRocks HASH distribution uses a single column.
            clauses.distribute_by = sorted_cols[0].name
            clauses.additional_clauses.append(self.render_distribution_clause(clauses.distribute_by))

        # ── PARTITION BY (from PARTITIONING tuning) ──
        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            clauses.partition_by = ", ".join(c.name for c in sorted_cols)

        # ── ORDER BY sort key (from SORTING tuning) ──
        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        if sort_columns:
            sorted_cols = sorted(sort_columns, key=lambda c: c.order)
            clauses.order_by = ", ".join(c.name for c in sorted_cols)

        # ── Clustering warning (no StarRocks clause) ──
        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
        if cluster_columns:
            logger.info(
                "Clustering hint for StarRocks table %s: %s. StarRocks has no separate "
                "clustering clause; use PARTITION BY / ORDER BY instead.",
                table_tuning.table_name,
                [c.name for c in cluster_columns],
            )

        return clauses

    def generate_create_table_ddl(
        self,
        table_name: str,
        columns: list[ColumnDefinition],
        tuning: TuningClauses | None = None,
        if_not_exists: bool = False,
        schema: str | None = None,
    ) -> str:
        """Generate a StarRocks CREATE TABLE statement (tuning clauses only).

        Emits the column list plus the physical-tuning clauses in StarRocks'
        required order: ``PARTITION BY`` -> ``DISTRIBUTED BY HASH`` ->
        ``ORDER BY``. The key model (``DUPLICATE KEY`` / ``PRIMARY KEY``) is
        intentionally not emitted here -- see the module docstring. When no
        tuned distribution column is present, the engine-mandatory baseline
        (``DISTRIBUTED BY HASH(<first_column>)``) is rendered so the statement
        is a valid StarRocks table.

        Args:
            table_name: Table name.
            columns: Column definitions.
            tuning: Tuning clauses from generate_tuning_clauses().
            if_not_exists: Add IF NOT EXISTS clause.
            schema: Database/schema name.

        Returns:
            Complete CREATE TABLE DDL string.
        """
        parts = ["CREATE TABLE"]

        if if_not_exists:
            parts.append("IF NOT EXISTS")

        parts.append(self.format_qualified_name(table_name, schema))

        statement = " ".join(parts)

        # Column definitions
        col_list = self.generate_column_list(columns)
        statement = f"{statement}\n(\n    {col_list}\n)"

        # PARTITION BY (tuned) precedes DISTRIBUTED BY.
        if tuning and tuning.partition_by:
            statement = f"{statement}\n{self.render_partition_clause(tuning.partition_by)}"

        # DISTRIBUTED BY HASH ... BUCKETS N (engine-mandatory). Prefer a tuned
        # distribution column; otherwise fall back to the first column.
        if tuning and tuning.distribute_by:
            statement = f"{statement}\n{self.render_distribution_clause(tuning.distribute_by)}"
        elif columns:
            statement = f"{statement}\n{self.render_distribution_clause(columns[0].name)}"

        # ORDER BY sort key (tuned) follows DISTRIBUTED BY.
        if tuning and tuning.order_by:
            statement = f"{statement}\n{self.render_order_by_clause(tuning.order_by)}"

        statement = f"{statement}{self.STATEMENT_TERMINATOR}"

        return statement


__all__ = [
    "StarRocksDDLGenerator",
]
