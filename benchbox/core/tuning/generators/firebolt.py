# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from benchbox.core.tuning.ddl_generator import (
    BaseDDLGenerator,
    ColumnDefinition,
    ColumnNullability,
    TuningClauses,
)
from benchbox.core.tuning.type_mapping import map_sql_type_with_fallback

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        TableTuning,
    )

logger = logging.getLogger(__name__)

FIREBOLT_TYPE_MAPPING: dict[str, str] = {
    "INTEGER": "INT",
    "BIGINT": "LONG",
    "SMALLINT": "INT",
    "TINYINT": "INT",
    "FLOAT": "FLOAT",
    "DOUBLE": "DOUBLE",
    "REAL": "FLOAT",
    "DOUBLE PRECISION": "DOUBLE",
    "DECIMAL": "DECIMAL(38, 9)",
    "NUMERIC": "DECIMAL(38, 9)",
    "VARCHAR": "TEXT",
    "CHAR": "TEXT",
    "TEXT": "TEXT",
    "STRING": "TEXT",
    "DATE": "DATE",
    "TIMESTAMP": "TIMESTAMP",
    "DATETIME": "TIMESTAMP",
    "TIME": "TEXT",
    "BOOLEAN": "BOOLEAN",
    "BOOL": "BOOLEAN",
}


class FireboltDDLGenerator(BaseDDLGenerator):
    IDENTIFIER_QUOTE = '"'
    SUPPORTS_IF_NOT_EXISTS = True
    STATEMENT_TERMINATOR = ";"

    SUPPORTED_TUNING_TYPES = frozenset({"distribution", "partitioning", "sorting", "clustering"})

    @property
    def platform_name(self) -> str:
        return "firebolt"

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        clauses = TuningClauses()

        if not table_tuning:
            return clauses

        from benchbox.core.tuning.interface import TuningType

        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        if sort_columns:
            logger.info(
                f"Sorting hint for Firebolt table {table_tuning.table_name}: "
                f"{[c.name for c in sort_columns]}. "
                f"Firebolt automatically sorts data within segments based on PRIMARY INDEX."
            )

        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
        if cluster_columns:
            logger.info(
                f"Clustering hint for Firebolt table {table_tuning.table_name}: "
                f"{[c.name for c in cluster_columns]}. "
                f"Clustering is achieved through PRIMARY INDEX in Firebolt."
            )

        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns:
            sorted_cols = sorted(distribution_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.distribute_by = f"PRIMARY INDEX ({', '.join(col_names)})"

        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.partition_by = ", ".join(col_names)

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
        statement = f"{statement}\n(\n    {col_list}\n)"

        if tuning:
            if tuning.distribute_by:
                statement = f"{statement}\n{tuning.distribute_by}"

            if tuning.partition_by:
                statement = f"{statement}\nPARTITION BY {tuning.partition_by}"

        statement = f"{statement}{self.STATEMENT_TERMINATOR}"

        return statement

    def generate_column_list(self, columns: list[ColumnDefinition]) -> str:
        col_defs = []
        for column in columns:
            parts = [f"{self.IDENTIFIER_QUOTE}{column.name}{self.IDENTIFIER_QUOTE}"]

            data_type = self._map_to_firebolt_type(column.data_type)

            if column.nullable == ColumnNullability.NOT_NULL:
                data_type = f"{data_type} NOT NULL"

            parts.append(data_type)

            if column.default_value is not None:
                parts.append(f"DEFAULT {column.default_value}")

            col_defs.append(" ".join(parts))

        return ",\n    ".join(col_defs)

    def _map_to_firebolt_type(self, sql_type: str) -> str:
        return map_sql_type_with_fallback(sql_type, FIREBOLT_TYPE_MAPPING)


__all__ = [
    "FireboltDDLGenerator",
]
