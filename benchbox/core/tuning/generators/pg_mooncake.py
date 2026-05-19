"""pg_mooncake DDL Generator.

Generates loadable CREATE TABLE statements for pg_mooncake:
- Keeps PostgreSQL heap DDL for the bulk COPY load path
- Skips PostgreSQL-specific tuning (indexes, CLUSTER, partitioning)
  because loaded tables are promoted into mooncake mirrors after load

pg_mooncake uses Parquet-based columnstore tables with Iceberg metadata.
The DuckDB execution engine handles query optimization internally, so
PostgreSQL's index-based and partition-based tuning is not applicable.

Example:
    >>> from benchbox.core.tuning.generators.pg_mooncake import PgMooncakeDDLGenerator
    >>> generator = PgMooncakeDDLGenerator()
    >>> clauses = generator.generate_tuning_clauses(table_tuning)
    >>> ddl = generator.generate_create_table_ddl("lineitem", columns, clauses)
    >>> # DDL remains COPY-loadable PostgreSQL heap DDL

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from benchbox.core.tuning.ddl_generator import TuningClauses
from benchbox.core.tuning.generators.postgresql import PostgreSQLDDLGenerator

if TYPE_CHECKING:
    from benchbox.core.tuning.ddl_generator import ColumnDefinition
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        TableTuning,
    )

logger = logging.getLogger(__name__)


class PgMooncakeDDLGenerator(PostgreSQLDDLGenerator):
    """DDL generator for pg_mooncake heap-load tables.

    Extends PostgreSQLDDLGenerator to preserve COPY-loadable heap CREATE TABLE
    statements. The runtime adapter promotes loaded heap tables into mooncake
    mirrors after COPY because pg_mooncake 0.2.0 does not support COPY into
    mooncake access-method tables.

    Tuning Notes:
    - PARTITION BY is not applicable (Iceberg handles partitioning internally)
    - CLUSTER is not applicable (Parquet files have their own row ordering)
    - Indexes are not supported on columnstore tables
    - DuckDB engine handles query optimization automatically
    """

    @property
    def platform_name(self) -> str:
        return "pg_mooncake"

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        """Generate pg_mooncake tuning clauses.

        Returns empty tuning clauses since columnstore tables manage their
        own storage layout. No PostgreSQL-level partitioning, clustering,
        or index tuning is needed.

        Args:
            table_tuning: Table tuning configuration (ignored for columnstore).
            platform_opts: Platform-specific options (ignored for columnstore).

        Returns:
            Empty TuningClauses - columnstore tables handle tuning internally.
        """
        # Columnstore tables manage their own storage layout.
        # No PostgreSQL-level partitioning, clustering, or index tuning.
        return TuningClauses()

    def generate_create_table_ddl(
        self,
        table_name: str,
        columns: list[ColumnDefinition],
        tuning: TuningClauses,
        schema: str | None = None,
    ) -> str:
        """Generate COPY-loadable heap CREATE TABLE DDL.

        Delegates to PostgreSQL generator for the base DDL and deliberately
        avoids adding ``USING mooncake``. Runtime promotion happens after data
        load through ``mooncake.create_table``.

        Args:
            table_name: Name of the table to create.
            columns: Column definitions.
            tuning: Tuning clauses (typically empty for columnstore).
            schema: Optional schema name.

        Returns:
            CREATE TABLE statement suitable for PostgreSQL COPY loading.
        """
        return super().generate_create_table_ddl(table_name, columns, tuning, schema)

    def generate_partition_children(
        self,
        parent_table: str,
        columns,
        tuning: TuningClauses,
        table_tuning: TableTuning | None = None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
        schema: str | None = None,
    ) -> list[str]:
        """pg_mooncake doesn't need explicit partition children.

        Columnstore tables manage partitioning internally via Iceberg metadata.
        """
        return []


__all__ = [
    "PgMooncakeDDLGenerator",
]
