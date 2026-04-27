"""pg_mooncake DDL Generator.

Generates CREATE TABLE statements for pg_mooncake with columnstore access method:
- Adds USING columnstore to all CREATE TABLE statements
- Skips PostgreSQL-specific tuning (indexes, CLUSTER, partitioning)
  since columnstore tables manage their own storage layout

pg_mooncake uses Parquet-based columnstore tables with Iceberg metadata.
The DuckDB execution engine handles query optimization internally, so
PostgreSQL's index-based and partition-based tuning is not applicable.

Example:
    >>> from benchbox.core.tuning.generators.pg_mooncake import PgMooncakeDDLGenerator
    >>> generator = PgMooncakeDDLGenerator()
    >>> clauses = generator.generate_tuning_clauses(table_tuning)
    >>> ddl = generator.generate_create_table_ddl("lineitem", columns, clauses)
    >>> # DDL ends with USING columnstore

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
    """DDL generator for pg_mooncake columnstore tables.

    Extends PostgreSQLDDLGenerator to add USING columnstore to CREATE TABLE
    statements. Since columnstore tables manage their own Parquet-based
    storage layout internally, most PostgreSQL physical tuning options
    (partitioning, clustering, indexes) are not applicable.

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
        """Generate CREATE TABLE DDL with USING columnstore.

        Delegates to PostgreSQL generator for the base DDL, then appends
        USING columnstore before the semicolon.

        Args:
            table_name: Name of the table to create.
            columns: Column definitions.
            tuning: Tuning clauses (typically empty for columnstore).
            schema: Optional schema name.

        Returns:
            CREATE TABLE statement with USING columnstore access method.
        """
        base_ddl = super().generate_create_table_ddl(table_name, columns, tuning, schema)

        # Add USING columnstore if not already present
        if "USING columnstore" not in base_ddl and "using columnstore" not in base_ddl:
            if base_ddl.rstrip().endswith(";"):
                base_ddl = base_ddl.rstrip()[:-1] + " USING columnstore;"
            else:
                base_ddl = base_ddl.rstrip() + " USING columnstore"

        return base_ddl

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
