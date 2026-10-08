# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

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

MIN_ORDER_BY_VERSION = (0, 10, 0)


def parse_version(version_str: str) -> tuple[int, ...]:
    version_str = version_str.lstrip("v")
    version_str = version_str.split("-")[0]
    try:
        return tuple(int(x) for x in version_str.split("."))
    except ValueError:
        return (0, 0, 0)


def get_duckdb_version() -> tuple[int, ...]:
    try:
        import duckdb

        version = duckdb.__version__
        return parse_version(version)
    except ImportError:
        return (0, 0, 0)


def supports_order_by() -> bool:
    return True


class DuckDBDDLGenerator(BaseDDLGenerator):
    IDENTIFIER_QUOTE = '"'
    SUPPORTS_IF_NOT_EXISTS = True
    STATEMENT_TERMINATOR = ";"

    SUPPORTED_TUNING_TYPES = frozenset({"sorting", "partitioning"})

    def __init__(self, check_version: bool = True):
        self._check_version = check_version
        self._version: tuple[int, ...] | None = None

    @property
    def platform_name(self) -> str:
        return "duckdb"

    @property
    def duckdb_version(self) -> tuple[int, ...]:
        if self._version is None:
            self._version = get_duckdb_version()
        return self._version

    @property
    def supports_order_by_clause(self) -> bool:
        return True

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        clauses = TuningClauses()

        if not table_tuning:
            return clauses

        from benchbox.core.tuning.interface import TuningType

        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns:
            logger.warning(
                f"Distribution tuning not applicable for single-node DuckDB "
                f"(table: {table_tuning.table_name}). "
                f"Configured columns {[c.name for c in distribution_columns]} will be ignored."
            )

        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
        if cluster_columns:
            logger.info(
                f"Clustering hint for DuckDB table {table_tuning.table_name}: "
                f"{[c.name for c in cluster_columns]}. "
                f"DuckDB handles clustering automatically based on sorting."
            )

        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        if sort_columns:
            sorted_cols = sorted(sort_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.sort_by = f"ORDER BY {', '.join(col_names)}"

        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            logger.info(
                f"Partitioning hint for DuckDB table {table_tuning.table_name}: "
                f"columns [{', '.join(col_names)}]. "
                f"Use PARTITION_BY in COPY TO for Hive-style partitioned exports."
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
        parts = ["CREATE TABLE"]

        if if_not_exists:
            parts.append("IF NOT EXISTS")

        parts.append(self.format_qualified_name(table_name, schema))

        statement = " ".join(parts)

        col_list = self.generate_column_list(columns)
        statement = f"{statement} (\n    {col_list}\n)"

        statement = f"{statement}{self.STATEMENT_TERMINATOR}"

        return statement

    def generate_ctas_ddl(
        self,
        table_name: str,
        source_query: str,
        tuning: TuningClauses | None = None,
        or_replace: bool = False,
        schema: str | None = None,
    ) -> str:
        parts = ["CREATE"]

        if or_replace:
            parts.append("OR REPLACE")

        parts.append("TABLE")
        parts.append(self.format_qualified_name(table_name, schema))
        parts.append("AS")

        statement = " ".join(parts)
        statement = f"{statement} {source_query}"

        if tuning and tuning.sort_by:
            statement = f"{statement} {tuning.sort_by}"

        statement = f"{statement}{self.STATEMENT_TERMINATOR}"

        return statement

    def generate_copy_to_partitioned(
        self,
        source_query: str,
        destination_path: str,
        partition_columns: list[str],
        file_format: str = "PARQUET",
    ) -> str:
        partition_clause = ", ".join(partition_columns)
        return (
            f"COPY ({source_query}) TO '{destination_path}' (FORMAT {file_format}, PARTITION_BY ({partition_clause}))"
        )


__all__ = [
    "DuckDBDDLGenerator",
    "get_duckdb_version",
    "parse_version",
    "supports_order_by",
]
