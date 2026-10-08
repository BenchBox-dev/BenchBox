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

DEFAULT_BUCKET_COUNT = 8


class StarRocksDDLGenerator(BaseDDLGenerator):
    IDENTIFIER_QUOTE = "`"
    SUPPORTS_IF_NOT_EXISTS = True
    STATEMENT_TERMINATOR = ";"

    SUPPORTED_TUNING_TYPES = frozenset({"partitioning", "sorting", "distribution"})

    def __init__(self, default_bucket_count: int = DEFAULT_BUCKET_COUNT):
        self._default_bucket_count = default_bucket_count

    @property
    def platform_name(self) -> str:
        return "starrocks"

    def render_distribution_clause(self, column: str, buckets: int | None = None) -> str:
        bucket_count = self._default_bucket_count if buckets is None else buckets
        return f"DISTRIBUTED BY HASH(`{column}`) BUCKETS {bucket_count}"

    def render_partition_clause(self, partition_by: str) -> str:
        return f"PARTITION BY ({partition_by})"

    def render_order_by_clause(self, order_by: str) -> str:
        return f"ORDER BY ({order_by})"

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        clauses = TuningClauses(platform=self.platform_name)

        if not table_tuning:
            return clauses

        from benchbox.core.tuning.interface import TuningType

        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns:
            sorted_cols = sorted(distribution_columns, key=lambda c: c.order)
            clauses.distribute_by = self.render_distribution_clause(sorted_cols[0].name)

        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            clauses.partition_by = self.render_partition_clause(", ".join(c.name for c in sorted_cols))

        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        if sort_columns:
            sorted_cols = sorted(sort_columns, key=lambda c: c.order)
            clauses.order_by = self.render_order_by_clause(", ".join(c.name for c in sorted_cols))

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
        parts = ["CREATE TABLE"]

        if if_not_exists:
            parts.append("IF NOT EXISTS")

        parts.append(self.format_qualified_name(table_name, schema))

        statement = " ".join(parts)

        col_list = self.generate_column_list(columns)
        statement = f"{statement}\n(\n    {col_list}\n)"

        if tuning and tuning.partition_by:
            statement = f"{statement}\n{tuning.partition_by}"

        if tuning and tuning.distribute_by:
            statement = f"{statement}\n{tuning.distribute_by}"
        elif columns:
            statement = f"{statement}\n{self.render_distribution_clause(columns[0].name)}"

        if tuning and tuning.order_by:
            statement = f"{statement}\n{tuning.order_by}"

        statement = f"{statement}{self.STATEMENT_TERMINATOR}"

        return statement


__all__ = [
    "StarRocksDDLGenerator",
]
