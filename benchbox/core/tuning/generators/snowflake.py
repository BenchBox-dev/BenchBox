# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
from enum import Enum
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


class SearchOptimizationType(str, Enum):
    EQUALITY = "EQUALITY"
    SUBSTRING = "SUBSTRING"
    GEO = "GEO"


class SnowflakeDDLGenerator(BaseDDLGenerator):
    IDENTIFIER_QUOTE = '"'
    SUPPORTS_IF_NOT_EXISTS = True
    STATEMENT_TERMINATOR = ";"

    SUPPORTED_TUNING_TYPES = frozenset({"clustering", "sorting"})

    def __init__(self, max_cluster_columns: int = 4):
        self._max_cluster_columns = max_cluster_columns

    @property
    def platform_name(self) -> str:
        return "snowflake"

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
                f"Distribution tuning not applicable for Snowflake "
                f"(table: {table_tuning.table_name}). "
                f"Snowflake handles data distribution automatically. "
                f"Configured columns {[c.name for c in distribution_columns]} will be ignored."
            )

        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            logger.info(
                f"Partitioning hint for Snowflake table {table_tuning.table_name}: "
                f"{[c.name for c in partition_columns]}. "
                f"Snowflake uses automatic micro-partitioning. "
                f"Consider using these columns for clustering instead."
            )

        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)

        all_cluster_cols = list(cluster_columns) + [c for c in sort_columns if c not in cluster_columns]

        if all_cluster_cols:
            sorted_cols = sorted(all_cluster_cols, key=lambda c: c.order)

            if len(sorted_cols) > self._max_cluster_columns:
                logger.warning(
                    f"Snowflake recommends max {self._max_cluster_columns} clustering columns. "
                    f"Using first {self._max_cluster_columns} of {len(sorted_cols)} columns."
                )
                sorted_cols = sorted_cols[: self._max_cluster_columns]

            col_names = [c.name for c in sorted_cols]
            clauses.cluster_by = f"CLUSTER BY ({', '.join(col_names)})"

        if platform_opts:
            search_opt = getattr(platform_opts, "search_optimization", None)
            if search_opt:
                for col_config in search_opt:
                    col_name = col_config.get("column")
                    opt_type = col_config.get("type", "EQUALITY").upper()
                    if col_name:
                        clauses.post_create_statements.append(
                            f"ALTER TABLE {{table_name}} ADD SEARCH OPTIMIZATION ON {opt_type}({col_name})"
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

        if tuning and tuning.cluster_by:
            statement = f"{statement}\n{tuning.cluster_by}"

        statement = f"{statement}{self.STATEMENT_TERMINATOR}"

        return statement

    def generate_clustering_info_query(self, table_name: str, cluster_columns: list[str]) -> str:
        col_spec = ", ".join(cluster_columns)
        return f"SELECT SYSTEM$CLUSTERING_INFORMATION('{table_name}', '({col_spec})')"

    def generate_resume_recluster(
        self,
        table_name: str,
        schema: str | None = None,
    ) -> str:
        qualified_name = self.format_qualified_name(table_name, schema)
        return f"ALTER TABLE {qualified_name} RESUME RECLUSTER{self.STATEMENT_TERMINATOR}"

    def generate_search_optimization(
        self,
        table_name: str,
        column: str,
        opt_type: SearchOptimizationType = SearchOptimizationType.EQUALITY,
        schema: str | None = None,
    ) -> str:
        qualified_name = self.format_qualified_name(table_name, schema)
        return f"ALTER TABLE {qualified_name} ADD SEARCH OPTIMIZATION ON {opt_type.value}({column}){self.STATEMENT_TERMINATOR}"


__all__ = [
    "SearchOptimizationType",
    "SnowflakeDDLGenerator",
]
