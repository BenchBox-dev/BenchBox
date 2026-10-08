# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from benchbox.core.tuning.ddl_generator import ColumnDefinition, TuningClauses
    from benchbox.core.tuning.interface import (
        ForeignKeyConfiguration,
        PlatformOptimizationConfiguration,
        PrimaryKeyConfiguration,
        TableTuning,
        UnifiedTuningConfiguration,
    )

from benchbox.platforms.base.cloud_spark.config import CloudPlatform, SparkConfigOptimizer

logger = logging.getLogger(__name__)


class SparkTuningMixin:
    def apply_primary_keys(
        self,
        config: PrimaryKeyConfiguration,
    ) -> list[str]:
        if config and config.enabled:
            logger.info("Primary keys noted (Spark does not enforce constraints)")
        return []

    def apply_foreign_keys(
        self,
        config: ForeignKeyConfiguration,
    ) -> list[str]:
        if config and config.enabled:
            logger.info("Foreign keys noted (Spark does not enforce constraints)")
        return []

    def apply_platform_optimizations(
        self,
        config: PlatformOptimizationConfiguration,
    ) -> list[str]:
        return []

    def apply_tuning_configuration(
        self,
        config: UnifiedTuningConfiguration,
    ) -> dict[str, Any]:
        results: dict[str, Any] = {}
        scale_factor = getattr(config, "scale_factor", None)
        if scale_factor:
            self._scale_factor = scale_factor
        if config.primary_keys:
            results["primary_keys"] = self.apply_primary_keys(config.primary_keys)
        if config.foreign_keys:
            results["foreign_keys"] = self.apply_foreign_keys(config.foreign_keys)
        if config.platform_optimizations:
            results["platform_optimizations"] = self.apply_platform_optimizations(config.platform_optimizations)
        return results

    def apply_constraint_configuration(
        self,
        primary_key_config: PrimaryKeyConfiguration,
        foreign_key_config: ForeignKeyConfiguration,
        connection: Any,
    ) -> None:
        if primary_key_config and primary_key_config.enabled:
            logger.info("Primary key constraints noted (Spark does not enforce constraints)")
        if foreign_key_config and foreign_key_config.enabled:
            logger.info("Foreign key constraints noted (Spark does not enforce constraints)")


class CloudSparkConfigMixin:
    cloud_platform: ClassVar[CloudPlatform]

    _benchmark_type: str | None
    _scale_factor: float
    _spark_config: dict[str, str]

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        self._benchmark_type = benchmark_type.lower()
        platform_name = self.cloud_platform.value.replace("_", " ").title()
        logger.info(f"Configuring {platform_name} for {benchmark_type} benchmark")
        adaptive_enabled = getattr(self, "adaptive_enabled", True)

        if self._benchmark_type == "tpch":
            spark_config = SparkConfigOptimizer.for_tpch(
                scale_factor=self._scale_factor,
                platform=self.cloud_platform,
                adaptive_enabled=adaptive_enabled,
            )
        elif self._benchmark_type == "tpcds":
            spark_config = SparkConfigOptimizer.for_tpcds(
                scale_factor=self._scale_factor,
                platform=self.cloud_platform,
                adaptive_enabled=adaptive_enabled,
            )
        elif self._benchmark_type == "ssb":
            spark_config = SparkConfigOptimizer.for_ssb(
                scale_factor=self._scale_factor,
                platform=self.cloud_platform,
                adaptive_enabled=adaptive_enabled,
            )
        else:
            spark_config = SparkConfigOptimizer.for_tpch(
                scale_factor=self._scale_factor,
                platform=self.cloud_platform,
                adaptive_enabled=adaptive_enabled,
            )

        if "_user_spark_config" not in self.__dict__:
            self._user_spark_config = dict(self._spark_config)
        self._spark_config = {**spark_config.to_dict(), **self._user_spark_config}

        ledger = getattr(self, "_applied_tuning_ledger", None)
        if ledger is not None:
            from benchbox.core.tuning.applied_ledger import PHASE_SESSION

            for _key, _value in self._spark_config.items():
                ledger.record(
                    f"SET {_key}={_value}",
                    PHASE_SESSION,
                    mechanism="spark_session_config",
                )


class SparkTableFormat(str, Enum):
    DELTA = "delta"
    ICEBERG = "iceberg"
    HUDI = "hudi"
    PARQUET = "parquet"
    HIVE = "hive"


class SparkDDLGeneratorMixin:
    table_format: ClassVar[SparkTableFormat] = SparkTableFormat.PARQUET

    default_bucket_count: ClassVar[int] = 32

    SUPPORTED_TUNING_TYPES: ClassVar[frozenset[str]] = frozenset(
        {"partitioning", "clustering", "sorting", "distribution"}
    )

    def get_table_format(
        self,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> SparkTableFormat:
        if platform_opts:
            format_str = getattr(platform_opts, "table_format", None)
            if format_str:
                try:
                    return SparkTableFormat(format_str.lower())
                except ValueError:
                    logger.warning(f"Invalid table_format '{format_str}', using default {self.table_format}")

        return self.table_format

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        table_format = self.get_table_format(platform_opts)

        if table_format == SparkTableFormat.DELTA:
            return self._generate_delta_tuning(table_tuning, platform_opts)
        elif table_format == SparkTableFormat.ICEBERG:
            return self._generate_iceberg_tuning(table_tuning, platform_opts)
        elif table_format == SparkTableFormat.HUDI:
            return self._generate_hudi_tuning(table_tuning, platform_opts)
        elif table_format == SparkTableFormat.PARQUET:
            return self._generate_parquet_tuning(table_tuning, platform_opts)
        elif table_format == SparkTableFormat.HIVE:
            return self._generate_hive_tuning(table_tuning, platform_opts)

        from benchbox.core.tuning.ddl_generator import TuningClauses

        return TuningClauses()

    def _generate_delta_tuning(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        from benchbox.core.tuning.ddl_generator import TuningClauses
        from benchbox.core.tuning.interface import TuningType

        clauses = TuningClauses()

        clauses.additional_clauses.append("USING DELTA")

        if not table_tuning:
            enable_auto_optimize = True
            if platform_opts:
                enable_auto_optimize = getattr(platform_opts, "enable_auto_optimize", True)
            if enable_auto_optimize:
                clauses.table_properties["delta.autoOptimize.optimizeWrite"] = "true"
                clauses.table_properties["delta.autoOptimize.autoCompact"] = "true"
            return clauses

        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.partition_by = f"PARTITIONED BY ({', '.join(col_names)})"

        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)

        all_cluster_cols = list(cluster_columns) + [c for c in sort_columns if c not in cluster_columns]

        use_liquid_clustering = True
        if platform_opts:
            use_liquid_clustering = getattr(platform_opts, "use_liquid_clustering", True)

        if all_cluster_cols and use_liquid_clustering:
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

        enable_auto_optimize = True
        if platform_opts:
            enable_auto_optimize = getattr(platform_opts, "enable_auto_optimize", True)

        if enable_auto_optimize:
            clauses.table_properties["delta.autoOptimize.optimizeWrite"] = "true"
            clauses.table_properties["delta.autoOptimize.autoCompact"] = "true"

        return clauses

    def _generate_iceberg_tuning(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        from benchbox.core.tuning.ddl_generator import TuningClauses
        from benchbox.core.tuning.interface import TuningType

        clauses = TuningClauses()

        clauses.additional_clauses.append("USING ICEBERG")

        if not table_tuning:
            return clauses

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

            bucket_count = self.default_bucket_count
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
            return f"bucket({self.default_bucket_count}, {col_name})"
        else:
            return col_name

    def _generate_hudi_tuning(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        from benchbox.core.tuning.ddl_generator import TuningClauses
        from benchbox.core.tuning.interface import TuningType

        clauses = TuningClauses()

        clauses.additional_clauses.append("USING HUDI")

        record_key = None
        precombine_field = None
        table_type = "COPY_ON_WRITE"
        write_operation = "upsert"

        if platform_opts:
            record_key = getattr(platform_opts, "record_key", None)
            precombine_field = getattr(platform_opts, "precombine_field", None)
            table_type = getattr(platform_opts, "hudi_table_type", table_type)
            write_operation = getattr(platform_opts, "hudi_write_operation", write_operation)

        if record_key:
            clauses.table_properties["hoodie.datasource.write.recordkey.field"] = record_key

        if precombine_field:
            clauses.table_properties["hoodie.datasource.write.precombine.field"] = precombine_field

        clauses.table_properties["hoodie.table.type"] = table_type

        clauses.table_properties["hoodie.datasource.write.operation"] = write_operation

        if not table_tuning:
            return clauses

        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.partition_by = f"PARTITIONED BY ({', '.join(col_names)})"

            clauses.table_properties["hoodie.datasource.write.hive_style_partitioning"] = "true"

        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns and not record_key:
            sorted_cols = sorted(distribution_columns, key=lambda c: c.order)
            clauses.table_properties["hoodie.datasource.write.recordkey.field"] = sorted_cols[0].name

        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)

        all_sort_cols = list(sort_columns) + [c for c in cluster_columns if c not in sort_columns]
        if all_sort_cols:
            sorted_cols = sorted(all_sort_cols, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]

            clauses.table_properties["hoodie.clustering.inline"] = "true"
            clauses.table_properties["hoodie.clustering.inline.max.commits"] = "4"
            clauses.table_properties["hoodie.clustering.plan.strategy.sort.columns"] = ",".join(col_names)

        return clauses

    def _generate_parquet_tuning(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        from benchbox.core.tuning.ddl_generator import TuningClauses
        from benchbox.core.tuning.interface import TuningType

        clauses = TuningClauses()

        clauses.additional_clauses.append("USING PARQUET")

        if not table_tuning:
            return clauses

        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.partition_by = f"PARTITIONED BY ({', '.join(col_names)})"

        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns:
            sorted_cols = sorted(distribution_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]

            bucket_count = self.default_bucket_count
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

    def _generate_hive_tuning(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        from benchbox.core.tuning.ddl_generator import TuningClauses
        from benchbox.core.tuning.interface import TuningType

        clauses = TuningClauses()

        storage_format = "PARQUET"
        if platform_opts:
            storage_format = getattr(platform_opts, "storage_format", storage_format)
        clauses.additional_clauses.append(f"STORED AS {storage_format}")

        if not table_tuning:
            return clauses

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

            bucket_count = self.default_bucket_count
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

        if schema:
            parts.append(f"{schema}.{table_name}")
        else:
            parts.append(table_name)

        statement = " ".join(parts)

        col_defs = []
        for col in columns:
            col_def = f"{col.name} {col.data_type}"
            col_defs.append(col_def)

        col_list = ",\n    ".join(col_defs)
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

        statement = f"{statement};"

        return statement

    def get_post_load_statements(
        self,
        table_name: str,
        tuning: TuningClauses,
        schema: str | None = None,
    ) -> list[str]:
        if not tuning or not tuning.post_create_statements:
            return []

        qualified_name = f"{schema}.{table_name}" if schema else table_name
        return [stmt.format(table_name=qualified_name) for stmt in tuning.post_create_statements]

    def supports_tuning_type(self, tuning_type: str) -> bool:
        return tuning_type.lower() in self.SUPPORTED_TUNING_TYPES
