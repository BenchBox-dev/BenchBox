# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
from enum import Enum
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

SYNAPSE_TYPE_MAPPING: dict[str, str] = {
    "INTEGER": "INT",
    "INT": "INT",
    "BIGINT": "BIGINT",
    "SMALLINT": "SMALLINT",
    "TINYINT": "TINYINT",
    "FLOAT": "FLOAT",
    "DOUBLE": "FLOAT",
    "REAL": "REAL",
    "DOUBLE PRECISION": "FLOAT",
    "DECIMAL": "DECIMAL(38, 9)",
    "NUMERIC": "NUMERIC(38, 9)",
    "VARCHAR": "NVARCHAR(4000)",
    "CHAR": "NCHAR(255)",
    "TEXT": "NVARCHAR(MAX)",
    "STRING": "NVARCHAR(4000)",
    "DATE": "DATE",
    "TIMESTAMP": "DATETIME2",
    "DATETIME": "DATETIME2",
    "TIME": "TIME",
    "BOOLEAN": "BIT",
    "BOOL": "BIT",
}


class DistributionType(str, Enum):
    HASH = "HASH"
    ROUND_ROBIN = "ROUND_ROBIN"
    REPLICATE = "REPLICATE"


class IndexType(str, Enum):
    CLUSTERED_COLUMNSTORE = "CLUSTERED COLUMNSTORE INDEX"
    CLUSTERED = "CLUSTERED INDEX"
    HEAP = "HEAP"


class AzureSynapseDDLGenerator(BaseDDLGenerator):
    IDENTIFIER_QUOTE = "["
    IDENTIFIER_QUOTE_END = "]"
    SUPPORTS_IF_NOT_EXISTS = False
    STATEMENT_TERMINATOR = ";"

    SUPPORTED_TUNING_TYPES = frozenset({"distribution", "partitioning", "indexing"})

    def __init__(
        self,
        distribution_default: DistributionType = DistributionType.ROUND_ROBIN,
        index_type: IndexType = IndexType.CLUSTERED_COLUMNSTORE,
    ):
        self._distribution_default = distribution_default
        self._index_type = index_type

    @property
    def platform_name(self) -> str:
        return "azure_synapse"

    def format_qualified_name(
        self,
        table_name: str,
        schema: str | None = None,
    ) -> str:
        if schema:
            return f"[{schema}].[{table_name}]"
        return f"[{table_name}]"

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        clauses = TuningClauses()

        if not table_tuning:
            clauses.distribute_by = self._distribution_default.value
            return clauses

        from benchbox.core.tuning.interface import TuningType

        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        if sort_columns:
            logger.info(
                f"Sorting hint for Azure Synapse table {table_tuning.table_name}: "
                f"{[c.name for c in sort_columns]}. "
                f"Azure Synapse sorting is handled by the index type (CLUSTERED INDEX on specific columns)."
            )

        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
        if cluster_columns:
            logger.info(
                f"Clustering hint for Azure Synapse table {table_tuning.table_name}: "
                f"{[c.name for c in cluster_columns]}. "
                f"Clustering is achieved via DISTRIBUTION and CLUSTERED INDEX."
            )

        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns:
            sorted_cols = sorted(distribution_columns, key=lambda c: c.order)
            dist_col = sorted_cols[0]
            clauses.distribute_by = f"HASH([{dist_col.name}])"
        else:
            clauses.distribute_by = self._distribution_default.value

        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            part_col = sorted_cols[0]
            clauses.partition_by = f"[{part_col.name}]"

        return clauses

    def generate_create_table_ddl(
        self,
        table_name: str,
        columns: list[ColumnDefinition],
        tuning: TuningClauses | None = None,
        if_not_exists: bool = False,
        schema: str | None = None,
    ) -> str:
        if if_not_exists:
            logger.warning("Azure Synapse doesn't support IF NOT EXISTS clause")

        parts = ["CREATE TABLE"]
        parts.append(self.format_qualified_name(table_name, schema))

        statement = " ".join(parts)

        col_list = self.generate_column_list(columns)
        statement = f"{statement}\n(\n    {col_list}\n)"

        with_clauses = []

        if tuning:
            if tuning.distribute_by:
                with_clauses.append(f"DISTRIBUTION = {tuning.distribute_by}")
            else:
                with_clauses.append(f"DISTRIBUTION = {self._distribution_default.value}")

            if tuning.partition_by:
                with_clauses.append(f"PARTITION ({tuning.partition_by} RANGE RIGHT FOR VALUES ())")
        else:
            with_clauses.append(f"DISTRIBUTION = {self._distribution_default.value}")

        with_clauses.append(self._index_type.value)

        statement = f"{statement}\nWITH ({', '.join(with_clauses)})"
        statement = f"{statement}{self.STATEMENT_TERMINATOR}"

        return statement

    def generate_column_list(self, columns: list[ColumnDefinition]) -> str:
        col_defs = []
        for column in columns:
            parts = [f"[{column.name}]"]

            data_type = self._map_to_synapse_type(column.data_type)
            parts.append(data_type)

            if column.nullable == ColumnNullability.NOT_NULL:
                parts.append("NOT NULL")
            else:
                parts.append("NULL")

            if column.default_value is not None:
                parts.append(f"DEFAULT {column.default_value}")

            col_defs.append(" ".join(parts))

        return ",\n    ".join(col_defs)

    def get_post_load_statements(
        self,
        table_name: str,
        tuning: TuningClauses | None = None,
        schema: str | None = None,
    ) -> list[str]:
        statements = []
        qualified_name = self.format_qualified_name(table_name, schema)

        statements.append(f"UPDATE STATISTICS {qualified_name}")

        return statements

    def _map_to_synapse_type(self, sql_type: str) -> str:
        return map_sql_type_with_fallback(sql_type, SYNAPSE_TYPE_MAPPING)


__all__ = [
    "AzureSynapseDDLGenerator",
    "DistributionType",
    "IndexType",
]
