"""pg_duckdb DDL Generator.

Generates CREATE TABLE statements for pg_duckdb, extending PostgreSQL DDL
with pg_duckdb-aware tuning recommendations:
- Standard PostgreSQL DDL (pg_duckdb uses heap tables)
- Reduced index recommendations (DuckDB engine bypasses B-tree indexes)
- Partition support inherited from PostgreSQL

pg_duckdb operates on standard PostgreSQL heap tables, so DDL is identical
to PostgreSQL. The main optimization difference is that pg_duckdb's DuckDB
execution engine performs its own vectorized scans, making B-tree indexes
less beneficial for analytical workloads.

Example:
    >>> from benchbox.core.tuning.generators.pg_duckdb import PgDuckDBDDLGenerator
    >>> generator = PgDuckDBDDLGenerator()
    >>> clauses = generator.generate_tuning_clauses(table_tuning)
    >>> ddl = generator.generate_create_table_ddl("lineitem", columns, clauses)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from benchbox.core.tuning.generators.postgresql import PostgreSQLDDLGenerator

if TYPE_CHECKING:
    from benchbox.core.tuning.ddl_generator import TuningClauses
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        TableTuning,
    )

logger = logging.getLogger(__name__)


class PgDuckDBDDLGenerator(PostgreSQLDDLGenerator):
    """DDL generator for pg_duckdb physical tuning.

    Extends PostgreSQLDDLGenerator with pg_duckdb-aware recommendations.
    Since pg_duckdb uses standard PostgreSQL heap tables, DDL is largely
    identical to PostgreSQL. The key difference is that pg_duckdb's DuckDB
    execution engine performs vectorized scans that bypass PostgreSQL's
    index-based access paths, so B-tree indexes provide less benefit for
    analytical workloads.

    Tuning Notes:
    - PARTITION BY is still beneficial (chunk pruning)
    - CLUSTER is less useful (DuckDB engine does its own scan ordering)
    - B-tree indexes are not used by DuckDB engine for analytical scans
    - PostgreSQL optimizer hints still apply for non-DuckDB queries
    """

    @property
    def platform_name(self) -> str:
        return "pg_duckdb"

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        """Generate pg_duckdb tuning clauses.

        Delegates to PostgreSQL generator but skips CLUSTER post-create
        statements since DuckDB's vectorized engine performs its own
        scan ordering.

        Args:
            table_tuning: Table tuning configuration.
            platform_opts: Platform-specific options.

        Returns:
            TuningClauses with PostgreSQL-compatible DDL (minus CLUSTER).
        """
        clauses = super().generate_tuning_clauses(table_tuning, platform_opts)

        # Filter out CLUSTER statements - DuckDB engine bypasses PostgreSQL
        # index-based scan ordering, so CLUSTER provides no benefit
        clauses.post_create_statements = [
            stmt for stmt in clauses.post_create_statements if not stmt.upper().startswith("CLUSTER")
        ]

        return clauses


__all__ = [
    "PgDuckDBDDLGenerator",
]
