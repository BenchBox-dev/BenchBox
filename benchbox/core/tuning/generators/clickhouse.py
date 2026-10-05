# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
from collections.abc import Sequence
from enum import Enum
from typing import TYPE_CHECKING

from benchbox.core.tuning.ddl_generator import (
    BaseDDLGenerator,
    ColumnDefinition,
    TuningClauses,
)
from benchbox.core.tuning.type_mapping import map_sql_type_with_fallback

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        TableTuning,
    )

logger = logging.getLogger(__name__)

CLICKHOUSE_TYPE_MAPPING: dict[str, str] = {
    "INTEGER": "Int32",
    "INT": "Int32",
    "BIGINT": "Int64",
    "SMALLINT": "Int16",
    "TINYINT": "Int8",
    "FLOAT": "Float32",
    "DOUBLE": "Float64",
    "REAL": "Float32",
    "DOUBLE PRECISION": "Float64",
    "DECIMAL": "Decimal(18, 2)",
    "NUMERIC": "Decimal(18, 2)",
    "VARCHAR": "String",
    "CHAR": "FixedString(255)",
    "TEXT": "String",
    "STRING": "String",
    "DATE": "Date",
    "TIMESTAMP": "DateTime",
    "DATETIME": "DateTime",
    "TIME": "String",
    "BOOLEAN": "Bool",
    "BOOL": "Bool",
}


class ClickHousePrimaryKeyPrefixError(ValueError):
    pass


def clickhouse_sort_key_columns(table_tuning: TableTuning) -> list[str]:
    from benchbox.core.tuning.interface import TuningType

    ordered = []
    for tuning_type in (TuningType.CLUSTERING, TuningType.SORTING):
        columns = table_tuning.get_columns_by_type(tuning_type)
        if columns:
            ordered.extend(sorted(columns, key=lambda c: c.order))

    seen = set()
    names = []
    for column in ordered:
        if column.name not in seen:
            names.append(column.name)
            seen.add(column.name)
    return names


def primary_key_prefix_violation(
    table_name: str,
    primary_key_columns: Sequence[str],
    sort_key_columns: Sequence[str],
) -> str | None:
    if not primary_key_columns or not sort_key_columns:
        return None

    primary_key = [column.lower() for column in primary_key_columns]
    sort_key = [column.lower() for column in sort_key_columns]
    if sort_key[: len(primary_key)] == primary_key:
        return None

    return (
        f"ClickHouse table {table_name}: primary key ({', '.join(primary_key_columns)}) must be a prefix of "
        f"the tuned sort key ({', '.join(sort_key_columns)}). "
        "Put the PK columns first in the sort key, or disable primary_keys."
    )


class MergeTreeEngine(str, Enum):
    MERGE_TREE = "MergeTree"
    REPLACING_MERGE_TREE = "ReplacingMergeTree"
    SUMMING_MERGE_TREE = "SummingMergeTree"
    AGGREGATING_MERGE_TREE = "AggregatingMergeTree"
    COLLAPSING_MERGE_TREE = "CollapsingMergeTree"
    VERSIONED_COLLAPSING_MERGE_TREE = "VersionedCollapsingMergeTree"
    GRAPHITE_MERGE_TREE = "GraphiteMergeTree"


class ClickHouseDDLGenerator(BaseDDLGenerator):
    IDENTIFIER_QUOTE = "`"
    SUPPORTS_IF_NOT_EXISTS = True
    STATEMENT_TERMINATOR = ";"

    SUPPORTED_TUNING_TYPES = frozenset({"sorting", "clustering", "partitioning", "distribution"})

    def __init__(
        self,
        engine: MergeTreeEngine = MergeTreeEngine.MERGE_TREE,
        index_granularity: int = 8192,
    ):
        self._engine = engine
        self._index_granularity = index_granularity

    @property
    def platform_name(self) -> str:
        return "clickhouse"

    @property
    def engine(self) -> MergeTreeEngine:
        return self._engine

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
        primary_key_columns: Sequence[str] | None = None,
    ) -> TuningClauses:
        clauses = TuningClauses()

        if not table_tuning:
            return clauses

        from benchbox.core.tuning.interface import TuningType

        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns:
            logger.info(
                f"Distribution hint for ClickHouse table {table_tuning.table_name}: "
                f"{[c.name for c in distribution_columns]}. "
                f"Distribution is handled via Distributed engine, not table DDL."
            )

        sort_key_columns = clickhouse_sort_key_columns(table_tuning)
        if sort_key_columns:
            clauses.sort_by = ", ".join(sort_key_columns)
            if primary_key_columns:
                violation = primary_key_prefix_violation(table_tuning.table_name, primary_key_columns, sort_key_columns)
                if violation:
                    raise ClickHousePrimaryKeyPrefixError(violation)
                clauses.primary_key = ", ".join(primary_key_columns)

        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            partition_exprs = []
            for col in sorted_cols:
                if col.type and col.type.lower() in ("date", "datetime", "timestamp"):
                    partition_exprs.append(f"toYYYYMM({col.name})")
                else:
                    partition_exprs.append(col.name)
            clauses.partition_by = ", ".join(partition_exprs)

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

        statement = f"{statement}\nENGINE = {self._engine.value}()"

        if tuning:
            if tuning.partition_by:
                statement = f"{statement}\nPARTITION BY ({tuning.partition_by})"

            if tuning.sort_by:
                statement = f"{statement}\nORDER BY ({tuning.sort_by})"
                if tuning.primary_key:
                    statement = f"{statement}\nPRIMARY KEY ({tuning.primary_key})"
            else:
                statement = f"{statement}\nORDER BY tuple()"

        else:
            statement = f"{statement}\nORDER BY tuple()"

        statement = f"{statement}\nSETTINGS index_granularity = {self._index_granularity}"

        statement = f"{statement}{self.STATEMENT_TERMINATOR}"

        return statement

    def get_post_load_statements(
        self,
        table_name: str,
        tuning: TuningClauses | None = None,
        schema: str | None = None,
    ) -> list[str]:
        statements = []
        qualified_name = self.format_qualified_name(table_name, schema)

        statements.append(f"OPTIMIZE TABLE {qualified_name}")

        return statements

    def generate_column_list(self, columns: list[ColumnDefinition]) -> str:
        col_defs = []
        for column in columns:
            parts = [f"{self.IDENTIFIER_QUOTE}{column.name}{self.IDENTIFIER_QUOTE}"]

            data_type = self._map_to_clickhouse_type(column.data_type)
            from benchbox.core.tuning.ddl_generator import ColumnNullability

            if column.nullable == ColumnNullability.NULLABLE or column.nullable == ColumnNullability.DEFAULT:
                data_type = f"Nullable({data_type})"

            parts.append(data_type)

            if column.default_value is not None:
                parts.append(f"DEFAULT {column.default_value}")

            col_defs.append(" ".join(parts))

        return ",\n    ".join(col_defs)

    def _map_to_clickhouse_type(self, sql_type: str) -> str:
        return map_sql_type_with_fallback(sql_type, CLICKHOUSE_TYPE_MAPPING)


__all__ = [
    "ClickHouseDDLGenerator",
    "ClickHousePrimaryKeyPrefixError",
    "MergeTreeEngine",
    "clickhouse_sort_key_columns",
    "primary_key_prefix_violation",
]
