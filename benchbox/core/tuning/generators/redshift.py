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

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        TableTuning,
    )

logger = logging.getLogger(__name__)


class DistStyle(str, Enum):
    ALL = "ALL"
    KEY = "KEY"
    EVEN = "EVEN"
    AUTO = "AUTO"


class SortStyle(str, Enum):
    COMPOUND = "COMPOUND"
    INTERLEAVED = "INTERLEAVED"


class ColumnEncoding(str, Enum):
    RAW = "raw"
    AZ64 = "az64"
    BYTEDICT = "bytedict"
    DELTA = "delta"
    DELTA32K = "delta32k"
    LZO = "lzo"
    MOSTLY8 = "mostly8"
    MOSTLY16 = "mostly16"
    MOSTLY32 = "mostly32"
    RUNLENGTH = "runlength"
    TEXT255 = "text255"
    TEXT32K = "text32k"
    ZSTD = "zstd"
    AUTO = "AUTO"


def recommend_encoding(data_type: str) -> ColumnEncoding:
    dt_upper = data_type.upper()

    if any(t in dt_upper for t in ["INT", "BIGINT", "SMALLINT", "DECIMAL", "NUMERIC", "DOUBLE", "FLOAT", "REAL"]):
        return ColumnEncoding.AZ64

    if any(t in dt_upper for t in ["DATE", "TIME", "TIMESTAMP"]):
        return ColumnEncoding.AZ64

    if "BOOL" in dt_upper:
        return ColumnEncoding.RUNLENGTH

    if any(t in dt_upper for t in ["VARCHAR", "CHAR", "TEXT"]):
        return ColumnEncoding.LZO

    return ColumnEncoding.AUTO


class RedshiftDDLGenerator(BaseDDLGenerator):
    IDENTIFIER_QUOTE = '"'
    SUPPORTS_IF_NOT_EXISTS = True
    STATEMENT_TERMINATOR = ";"

    SUPPORTED_TUNING_TYPES = frozenset({"distribution", "sorting", "clustering"})

    def __init__(
        self,
        default_dist_style: DistStyle = DistStyle.AUTO,
        default_sort_style: SortStyle = SortStyle.COMPOUND,
        auto_encoding: bool = True,
    ):
        self._default_dist_style = default_dist_style
        self._default_sort_style = default_sort_style
        self._auto_encoding = auto_encoding

    @property
    def platform_name(self) -> str:
        return "redshift"

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        clauses = TuningClauses()

        if not table_tuning:
            return clauses

        from benchbox.core.tuning.interface import TuningType

        dist_style = self._default_dist_style
        sort_style = self._default_sort_style

        if platform_opts:
            if hasattr(platform_opts, "dist_style") and platform_opts.dist_style:
                try:
                    dist_style = DistStyle(platform_opts.dist_style.upper())
                except ValueError:
                    logger.warning(f"Invalid dist_style '{platform_opts.dist_style}', using default")

            if hasattr(platform_opts, "sort_style") and platform_opts.sort_style:
                try:
                    sort_style = SortStyle(platform_opts.sort_style.upper())
                except ValueError:
                    logger.warning(f"Invalid sort_style '{platform_opts.sort_style}', using default")

        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            logger.info(
                f"Partitioning hint for Redshift table {table_tuning.table_name}: "
                f"{[c.name for c in partition_columns]}. "
                f"Redshift doesn't support native partitioning. Consider using sort key "
                f"and date predicates for similar query performance."
            )

        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns:
            sorted_cols = sorted(distribution_columns, key=lambda c: c.order)
            if len(sorted_cols) == 1:
                clauses.distribute_by = f"DISTSTYLE KEY\nDISTKEY ({sorted_cols[0].name})"
            else:
                logger.warning(
                    f"Redshift only supports single-column DISTKEY. "
                    f"Using first column '{sorted_cols[0].name}' from {[c.name for c in sorted_cols]}."
                )
                clauses.distribute_by = f"DISTSTYLE KEY\nDISTKEY ({sorted_cols[0].name})"
        elif dist_style != DistStyle.AUTO:
            clauses.distribute_by = f"DISTSTYLE {dist_style.value}"

        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)

        all_sort_cols = list(sort_columns) + [c for c in cluster_columns if c not in sort_columns]
        if all_sort_cols:
            sorted_cols = sorted(all_sort_cols, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]

            if sort_style == SortStyle.INTERLEAVED:
                clauses.sort_by = f"INTERLEAVED SORTKEY ({', '.join(col_names)})"
            else:
                clauses.sort_by = f"COMPOUND SORTKEY ({', '.join(col_names)})"

        return clauses

    def generate_column_definition(
        self,
        column: ColumnDefinition,
        include_encoding: bool | None = None,
    ) -> str:
        parts = [column.name, column.data_type]

        if column.nullable == ColumnNullability.NOT_NULL:
            parts.append("NOT NULL")
        elif column.nullable == ColumnNullability.NULLABLE:
            parts.append("NULL")

        if column.default_value is not None:
            parts.append(f"DEFAULT {column.default_value}")

        should_encode = include_encoding if include_encoding is not None else self._auto_encoding
        if should_encode:
            encoding = recommend_encoding(column.data_type)
            if encoding != ColumnEncoding.AUTO:
                parts.append(f"ENCODE {encoding.value}")

        return " ".join(parts)

    def generate_column_list(
        self,
        columns: list[ColumnDefinition],
        include_encoding: bool | None = None,
    ) -> str:
        col_defs = [self.generate_column_definition(col, include_encoding) for col in columns]
        return ",\n    ".join(col_defs)

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

        tuning_parts = []
        if tuning:
            if tuning.distribute_by:
                tuning_parts.append(tuning.distribute_by)
            if tuning.sort_by:
                tuning_parts.append(tuning.sort_by)

        if tuning_parts:
            statement = f"{statement}\n{chr(10).join(tuning_parts)}"

        statement = f"{statement}{self.STATEMENT_TERMINATOR}"

        return statement

    def generate_copy_command(
        self,
        table_name: str,
        s3_path: str,
        iam_role: str,
        file_format: str = "PARQUET",
        schema: str | None = None,
    ) -> str:
        qualified_name = self.format_qualified_name(table_name, schema)

        parts = [
            f"COPY {qualified_name}",
            f"FROM '{s3_path}'",
            f"IAM_ROLE '{iam_role}'",
            f"FORMAT AS {file_format}",
        ]

        return "\n".join(parts) + self.STATEMENT_TERMINATOR


__all__ = [
    "ColumnEncoding",
    "DistStyle",
    "RedshiftDDLGenerator",
    "SortStyle",
    "recommend_encoding",
]
