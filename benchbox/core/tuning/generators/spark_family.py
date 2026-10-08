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


class SparkTableFormat(str, Enum):
    DELTA = "delta"
    ICEBERG = "iceberg"
    PARQUET = "parquet"
    HIVE = "hive"


class SparkBaseDDLGenerator(BaseDDLGenerator):
    IDENTIFIER_QUOTE = "`"
    SUPPORTS_IF_NOT_EXISTS = True
    STATEMENT_TERMINATOR = ";"

    SUPPORTED_TUNING_TYPES = frozenset({"partitioning", "clustering", "sorting", "distribution"})

    TABLE_FORMAT: str = "parquet"

    DEFAULT_BUCKET_COUNT = 32

    def __init__(self, default_bucket_count: int = 32):
        self._default_bucket_count = default_bucket_count

    @property
    def platform_name(self) -> str:
        return f"spark-{self.TABLE_FORMAT}"

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

        col_list = self.generate_column_list(columns, include_constraints=False)
        statement = f"{statement} (\n    {col_list}\n)"

        if tuning and not tuning.is_empty():
            for clause in tuning.additional_clauses:
                statement = f"{statement}\n{clause}"

            if tuning.partition_by:
                statement = f"{statement}\n{tuning.partition_by}"

            if tuning.cluster_by:
                statement = f"{statement}\n{tuning.cluster_by}"
            if tuning.distribute_by:
                statement = f"{statement}\n{tuning.distribute_by}"

            if tuning.sort_by:
                statement = f"{statement}\n{tuning.sort_by}"

            if tuning.table_properties:
                props = ", ".join(f"'{k}' = '{v}'" for k, v in sorted(tuning.table_properties.items()))
                statement = f"{statement}\nTBLPROPERTIES ({props})"

        statement = f"{statement}{self.STATEMENT_TERMINATOR}"

        return statement


class DeltaDDLGenerator(SparkBaseDDLGenerator):
    TABLE_FORMAT = "delta"

    def __init__(
        self,
        use_liquid_clustering: bool = True,
        enable_auto_optimize: bool = True,
        default_bucket_count: int = 32,
    ):
        super().__init__(default_bucket_count)
        self._use_liquid_clustering = use_liquid_clustering
        self._enable_auto_optimize = enable_auto_optimize

    @property
    def platform_name(self) -> str:
        return "delta"

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        clauses = TuningClauses()

        if not table_tuning:
            clauses.additional_clauses.append("USING DELTA")
            return clauses

        from benchbox.core.tuning.interface import TuningType

        clauses.additional_clauses.append("USING DELTA")

        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.partition_by = f"PARTITIONED BY ({', '.join(col_names)})"

        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)

        all_cluster_cols = list(cluster_columns) + [c for c in sort_columns if c not in cluster_columns]

        use_liquid = self._use_liquid_clustering
        if platform_opts:
            use_liquid = getattr(platform_opts, "use_liquid_clustering", use_liquid)

        if all_cluster_cols and use_liquid:
            sorted_cols = sorted(all_cluster_cols, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.cluster_by = f"CLUSTER BY ({', '.join(col_names)})"
        elif all_cluster_cols:
            sorted_cols = sorted(all_cluster_cols, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.post_create_statements.append(f"OPTIMIZE {{table_name}} ZORDER BY ({', '.join(col_names)})")

        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns and not all_cluster_cols:
            sorted_cols = sorted(distribution_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.post_create_statements.append(f"OPTIMIZE {{table_name}} ZORDER BY ({', '.join(col_names)})")

        enable_auto = self._enable_auto_optimize
        if platform_opts:
            enable_auto = getattr(platform_opts, "enable_auto_optimize", enable_auto)

        if enable_auto:
            clauses.table_properties["delta.autoOptimize.optimizeWrite"] = "true"
            clauses.table_properties["delta.autoOptimize.autoCompact"] = "true"

        return clauses


class IcebergDDLGenerator(SparkBaseDDLGenerator):
    TABLE_FORMAT = "iceberg"

    @property
    def platform_name(self) -> str:
        return "iceberg"

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        clauses = TuningClauses()

        if not table_tuning:
            clauses.additional_clauses.append("USING ICEBERG")
            return clauses

        from benchbox.core.tuning.interface import TuningType

        clauses.additional_clauses.append("USING ICEBERG")

        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            transforms = []
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)

            for col in sorted_cols:
                transform = self._get_iceberg_transform(col, platform_opts)
                transforms.append(transform)

            clauses.partition_by = f"PARTITIONED BY ({', '.join(transforms)})"

        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns and not partition_columns:
            sorted_cols = sorted(distribution_columns, key=lambda c: c.order)
            transforms = []

            bucket_count = self._default_bucket_count
            if platform_opts:
                bucket_count = getattr(platform_opts, "bucket_count", bucket_count)

            for col in sorted_cols:
                transforms.append(f"bucket({bucket_count}, {col.name})")

            clauses.partition_by = f"PARTITIONED BY ({', '.join(transforms)})"

        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)

        all_sort_cols = list(sort_columns) + [c for c in cluster_columns if c not in sort_columns]
        if all_sort_cols:
            sorted_cols = sorted(all_sort_cols, key=lambda c: c.order)
            sort_parts = []
            for col in sorted_cols:
                direction = getattr(col, "sort_order", "ASC")
                sort_parts.append(f"{col.name} {direction}")
            clauses.table_properties["write.sort-order"] = ", ".join(sort_parts)

        return clauses

    def _get_iceberg_transform(
        self,
        col,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> str:
        col_name = col.name
        col_type = col.type.upper() if col.type else ""

        if platform_opts:
            col_transforms = getattr(platform_opts, "partition_transforms", {})
            if isinstance(col_transforms, dict) and col_name in col_transforms:
                return col_transforms[col_name]

        if "DATE" in col_type:
            return f"months({col_name})"
        elif "TIMESTAMP" in col_type:
            return f"days({col_name})"
        elif "INT" in col_type or "BIGINT" in col_type:
            return f"bucket({self._default_bucket_count}, {col_name})"
        else:
            return col_name


class ParquetDDLGenerator(SparkBaseDDLGenerator):
    TABLE_FORMAT = "parquet"

    @property
    def platform_name(self) -> str:
        return "parquet"

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        clauses = TuningClauses()

        if not table_tuning:
            clauses.additional_clauses.append("USING PARQUET")
            return clauses

        from benchbox.core.tuning.interface import TuningType

        clauses.additional_clauses.append("USING PARQUET")

        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.partition_by = f"PARTITIONED BY ({', '.join(col_names)})"

        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns:
            sorted_cols = sorted(distribution_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]

            bucket_count = self._default_bucket_count
            if platform_opts:
                bucket_count = getattr(platform_opts, "bucket_count", bucket_count)

            clauses.distribute_by = f"CLUSTERED BY ({', '.join(col_names)}) INTO {bucket_count} BUCKETS"

        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)

        all_sort_cols = list(sort_columns) + [c for c in cluster_columns if c not in sort_columns]
        if all_sort_cols:
            sorted_cols = sorted(all_sort_cols, key=lambda c: c.order)
            sort_parts = []
            for col in sorted_cols:
                direction = getattr(col, "sort_order", "ASC")
                nulls = getattr(col, "nulls_position", "DEFAULT")
                part = col.name
                if direction != "ASC":
                    part = f"{part} {direction}"
                if nulls != "DEFAULT":
                    part = f"{part} NULLS {nulls}"
                sort_parts.append(part)
            clauses.sort_by = f"SORTED BY ({', '.join(sort_parts)})"

        return clauses


class HiveDDLGenerator(SparkBaseDDLGenerator):
    TABLE_FORMAT = "hive"

    def __init__(
        self,
        storage_format: str = "PARQUET",
        default_bucket_count: int = 32,
    ):
        super().__init__(default_bucket_count)
        self._storage_format = storage_format

    @property
    def platform_name(self) -> str:
        return "hive"

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        clauses = TuningClauses()

        storage_format = self._storage_format
        if platform_opts:
            storage_format = getattr(platform_opts, "storage_format", storage_format)
        clauses.additional_clauses.append(f"STORED AS {storage_format}")

        if not table_tuning:
            return clauses

        from benchbox.core.tuning.interface import TuningType

        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            parts = []
            for col in sorted_cols:
                col_type = col.type if col.type else "STRING"
                parts.append(f"{col.name} {col_type}")
            clauses.partition_by = f"PARTITIONED BY ({', '.join(parts)})"

        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)

        all_sort_cols = list(sort_columns) + [c for c in cluster_columns if c not in sort_columns]

        if distribution_columns:
            sorted_dist = sorted(distribution_columns, key=lambda c: c.order)
            dist_names = [c.name for c in sorted_dist]

            bucket_count = self._default_bucket_count
            if platform_opts:
                bucket_count = getattr(platform_opts, "bucket_count", bucket_count)

            bucket_clause = f"CLUSTERED BY ({', '.join(dist_names)})"

            if all_sort_cols:
                sorted_sort = sorted(all_sort_cols, key=lambda c: c.order)
                sort_names = [c.name for c in sorted_sort]
                bucket_clause += f" SORTED BY ({', '.join(sort_names)})"

            bucket_clause += f" INTO {bucket_count} BUCKETS"
            clauses.distribute_by = bucket_clause

        return clauses


__all__ = [
    "DeltaDDLGenerator",
    "HiveDDLGenerator",
    "IcebergDDLGenerator",
    "ParquetDDLGenerator",
    "SparkBaseDDLGenerator",
    "SparkTableFormat",
]
