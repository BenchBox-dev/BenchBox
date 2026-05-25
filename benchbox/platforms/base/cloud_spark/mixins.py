"""Reusable mixins for cloud Spark platform adapters.

This module provides mixins that eliminate code duplication across
cloud Spark platform adapters. Each mixin encapsulates a specific
concern that is common across multiple adapters.

Mixins:
    SparkTuningMixin: Default constraint handling for Spark platforms
        (Spark does not enforce primary/foreign key constraints)
    CloudSparkConfigMixin: Benchmark configuration using SparkConfigOptimizer
    SparkDDLGeneratorMixin: DDL generation for Spark platforms with Delta/Iceberg/Parquet

Usage:
    from benchbox.platforms.base.cloud_spark.mixins import (
        SparkTuningMixin,
        CloudSparkConfigMixin,
        SparkDDLGeneratorMixin,
    )

    class MySparkAdapter(CloudSparkConfigMixin, SparkTuningMixin, SparkDDLGeneratorMixin, PlatformAdapter):
        cloud_platform = CloudPlatform.DATAPROC_SERVERLESS
        table_format = "delta"  # or "iceberg", "parquet", "hive"
        # Inherits configure_for_benchmark, apply_primary_keys, generate_tuning_clauses, etc.
        pass

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

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
    """Default tuning/constraint handling for Spark platforms.

    Spark SQL does not enforce primary key or foreign key constraints.
    This mixin provides the standard implementation that all Spark-based
    adapters use: logging the constraint configuration but returning
    empty lists (no DDL executed).

    This mixin should be inherited by all Spark-based platform adapters:
    - AWS: Athena Spark, EMR Serverless, Glue
    - GCP: Dataproc, Dataproc Serverless
    - Azure: Synapse Spark, Fabric Spark
    - Snowflake: Snowpark
    - Databricks: DataFrame mode
    """

    def apply_primary_keys(
        self,
        config: PrimaryKeyConfiguration,
    ) -> list[str]:
        """Apply primary key configuration (logging only for Spark).

        Spark SQL does not enforce primary key constraints. This method
        logs the configuration for informational purposes but does not
        execute any DDL.

        Args:
            config: Primary key configuration.

        Returns:
            Empty list (Spark doesn't enforce PKs).
        """
        if config and config.enabled:
            logger.info("Primary keys noted (Spark does not enforce constraints)")
        return []

    def apply_foreign_keys(
        self,
        config: ForeignKeyConfiguration,
    ) -> list[str]:
        """Apply foreign key configuration (logging only for Spark).

        Spark SQL does not enforce foreign key constraints. This method
        logs the configuration for informational purposes but does not
        execute any DDL.

        Args:
            config: Foreign key configuration.

        Returns:
            Empty list (Spark doesn't enforce FKs).
        """
        if config and config.enabled:
            logger.info("Foreign keys noted (Spark does not enforce constraints)")
        return []

    def apply_platform_optimizations(
        self,
        config: PlatformOptimizationConfiguration,
    ) -> list[str]:
        """Apply platform-specific optimizations.

        For Spark platforms, optimizations are typically applied via
        Spark configuration at session/job creation time, not through
        DDL statements.

        Args:
            config: Platform optimization configuration.

        Returns:
            Empty list (optimizations applied via Spark config).
        """
        # Optimizations applied via Spark configuration, not DDL
        return []

    def apply_tuning_configuration(
        self,
        config: UnifiedTuningConfiguration,
    ) -> dict[str, Any]:
        """Apply unified tuning configuration through the Spark tuning hooks."""
        results: dict[str, Any] = {}
        if config.scale_factor:
            self._scale_factor = config.scale_factor
        if config.primary_keys:
            results["primary_keys"] = self.apply_primary_keys(config.primary_keys)
        if config.foreign_keys:
            results["foreign_keys"] = self.apply_foreign_keys(config.foreign_keys)
        if config.platform:
            results["platform_optimizations"] = self.apply_platform_optimizations(config.platform)
        return results

    def apply_constraint_configuration(
        self,
        primary_key_config: PrimaryKeyConfiguration,
        foreign_key_config: ForeignKeyConfiguration,
        connection: Any,
    ) -> None:
        """Apply constraint configurations (not enforced in Spark).

        Combined method for applying both primary and foreign key
        configurations. For Spark platforms, this only logs the
        configuration since constraints are not enforced.

        Args:
            primary_key_config: Primary key configuration.
            foreign_key_config: Foreign key configuration.
            connection: Database connection (unused for Spark).
        """
        if primary_key_config and primary_key_config.enabled:
            logger.info("Primary key constraints noted (Spark does not enforce constraints)")
        if foreign_key_config and foreign_key_config.enabled:
            logger.info("Foreign key constraints noted (Spark does not enforce constraints)")


class CloudSparkConfigMixin:
    """Benchmark configuration mixin for cloud Spark platforms.

    Provides the configure_for_benchmark() method that uses SparkConfigOptimizer
    to generate optimized Spark configurations based on benchmark type and
    scale factor.

    Subclasses must define a class variable `cloud_platform` specifying which
    CloudPlatform enum value to use for configuration generation.

    Example:
        class DataprocServerlessAdapter(CloudSparkConfigMixin, SparkTuningMixin, PlatformAdapter):
            cloud_platform: ClassVar[CloudPlatform] = CloudPlatform.DATAPROC_SERVERLESS
    """

    # Subclasses must set this to their CloudPlatform enum value
    cloud_platform: ClassVar[CloudPlatform]

    # These attributes are expected to exist on the adapter
    _benchmark_type: str | None
    _scale_factor: float
    _spark_config: dict[str, str]

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Configure adapter for specific benchmark.

        Uses SparkConfigOptimizer to generate optimized Spark configuration
        for the specified benchmark type and scale factor.

        Args:
            connection: Connection object (unused, for interface compatibility).
            benchmark_type: Benchmark type (tpch, tpcds, ssb).
        """
        self._benchmark_type = benchmark_type.lower()
        platform_name = self.cloud_platform.value.replace("_", " ").title()
        logger.info(f"Configuring {platform_name} for {benchmark_type} benchmark")

        # Get optimized Spark config from cloud-spark infrastructure
        if self._benchmark_type == "tpch":
            spark_config = SparkConfigOptimizer.for_tpch(
                scale_factor=self._scale_factor,
                platform=self.cloud_platform,
            )
        elif self._benchmark_type == "tpcds":
            spark_config = SparkConfigOptimizer.for_tpcds(
                scale_factor=self._scale_factor,
                platform=self.cloud_platform,
            )
        elif self._benchmark_type == "ssb":
            spark_config = SparkConfigOptimizer.for_ssb(
                scale_factor=self._scale_factor,
                platform=self.cloud_platform,
            )
        else:
            # Default to TPC-H config for unknown benchmarks
            spark_config = SparkConfigOptimizer.for_tpch(
                scale_factor=self._scale_factor,
                platform=self.cloud_platform,
            )

        self._spark_config = spark_config.to_dict()


class SparkTableFormat(str, Enum):
    """Supported Spark table formats for DDL generation."""

    DELTA = "delta"  # Delta Lake (Databricks, EMR, Dataproc with Delta)
    ICEBERG = "iceberg"  # Apache Iceberg
    HUDI = "hudi"  # Apache Hudi (Onehouse, AWS EMR, Dataproc)
    PARQUET = "parquet"  # Apache Parquet (native Spark)
    HIVE = "hive"  # Legacy Hive format


class SparkDDLGeneratorMixin:
    """DDL generation mixin for Spark-based platforms.

    Provides unified DDL generation across all Spark platforms with support for:
    - Delta Lake: PARTITIONED BY, CLUSTER BY (liquid clustering), Z-ORDER
    - Apache Iceberg: partition transforms (bucket, years, months, days)
    - Apache Parquet: PARTITIONED BY, CLUSTERED BY, SORTED BY
    - Hive (legacy): STORED AS, CLUSTERED INTO BUCKETS

    Subclasses should set `table_format` class variable to specify the default format.
    The format can also be overridden via platform_opts.

    Example:
        class DataprocServerlessAdapter(SparkDDLGeneratorMixin, PlatformAdapter):
            table_format: ClassVar[SparkTableFormat] = SparkTableFormat.PARQUET
    """

    # Default table format - subclasses should override
    table_format: ClassVar[SparkTableFormat] = SparkTableFormat.PARQUET

    # Default bucket count for hash partitioning
    default_bucket_count: ClassVar[int] = 32

    # Supported tuning types for Spark platforms
    SUPPORTED_TUNING_TYPES: ClassVar[frozenset[str]] = frozenset(
        {"partitioning", "clustering", "sorting", "distribution"}
    )

    def get_table_format(
        self,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> SparkTableFormat:
        """Determine the table format to use.

        Args:
            platform_opts: Platform options may override default format.

        Returns:
            SparkTableFormat enum value.
        """
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
        """Generate Spark tuning clauses based on table format.

        Routes to format-specific generators based on configured table format.

        Args:
            table_tuning: Table tuning configuration.
            platform_opts: Platform-specific options.

        Returns:
            TuningClauses with appropriate Spark SQL clauses.
        """
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

        # Fallback for unknown formats
        from benchbox.core.tuning.ddl_generator import TuningClauses

        return TuningClauses()

    def _generate_delta_tuning(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        """Generate Delta Lake tuning clauses.

        Delta Lake supports:
        - PARTITIONED BY (col1, col2)
        - CLUSTER BY (col1, col2) - Delta 2.0+ liquid clustering
        - TBLPROPERTIES for auto-optimize
        - Z-ORDER via post-load OPTIMIZE command
        """
        from benchbox.core.tuning.ddl_generator import TuningClauses
        from benchbox.core.tuning.interface import TuningType

        clauses = TuningClauses()

        # Set table format
        clauses.additional_clauses.append("USING DELTA")

        if not table_tuning:
            # Add auto-optimize properties even without table tuning
            enable_auto_optimize = True
            if platform_opts:
                enable_auto_optimize = getattr(platform_opts, "enable_auto_optimize", True)
            if enable_auto_optimize:
                clauses.table_properties["delta.autoOptimize.optimizeWrite"] = "true"
                clauses.table_properties["delta.autoOptimize.autoCompact"] = "true"
            return clauses

        # Handle partitioning
        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.partition_by = f"PARTITIONED BY ({', '.join(col_names)})"

        # Handle clustering (Delta 2.0+ liquid clustering)
        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)

        # Delta CLUSTER BY can use clustering or sorting columns
        all_cluster_cols = list(cluster_columns) + [c for c in sort_columns if c not in cluster_columns]

        # Check for liquid clustering support
        use_liquid_clustering = True
        if platform_opts:
            use_liquid_clustering = getattr(platform_opts, "use_liquid_clustering", True)

        if all_cluster_cols and use_liquid_clustering:
            sorted_cols = sorted(all_cluster_cols, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.cluster_by = f"CLUSTER BY ({', '.join(col_names)})"
        elif all_cluster_cols:
            # Fall back to Z-ORDER for older Delta versions
            sorted_cols = sorted(all_cluster_cols, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.post_create_statements.append(f"OPTIMIZE {{table_name}} ZORDER BY ({', '.join(col_names)})")

        # Handle distribution via Z-ORDER
        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns and not all_cluster_cols:
            # Z-ORDER on distribution columns if not already clustering
            sorted_cols = sorted(distribution_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.post_create_statements.append(f"OPTIMIZE {{table_name}} ZORDER BY ({', '.join(col_names)})")

        # Add Delta Lake optimization properties
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
        """Generate Apache Iceberg tuning clauses.

        Iceberg supports partition transforms:
        - years(col), months(col), days(col), hours(col)
        - bucket(N, col)
        - truncate(N, col)
        - identity(col)
        """
        from benchbox.core.tuning.ddl_generator import TuningClauses
        from benchbox.core.tuning.interface import TuningType

        clauses = TuningClauses()

        # Set table format
        clauses.additional_clauses.append("USING ICEBERG")

        if not table_tuning:
            return clauses

        # Handle partitioning with transforms
        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            transforms = []
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)

            for col in sorted_cols:
                transform = self._get_iceberg_transform(col, platform_opts)
                transforms.append(transform)

            clauses.partition_by = f"PARTITIONED BY ({', '.join(transforms)})"

        # Handle distribution via bucket transform
        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns and not partition_columns:
            # Add bucket partitioning for distribution
            sorted_cols = sorted(distribution_columns, key=lambda c: c.order)
            transforms = []

            bucket_count = self.default_bucket_count
            if platform_opts:
                bucket_count = getattr(platform_opts, "bucket_count", bucket_count)

            for col in sorted_cols:
                transforms.append(f"bucket({bucket_count}, {col.name})")

            clauses.partition_by = f"PARTITIONED BY ({', '.join(transforms)})"

        # Handle sorting
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
        """Get Iceberg partition transform for a column.

        Args:
            col: TuningColumn with name and type.
            platform_opts: May contain explicit transforms.

        Returns:
            Transform string like "months(col)" or "bucket(16, col)".
        """
        col_name = col.name
        col_type = col.type.upper() if col.type else ""

        # Check for explicit transform in platform_opts
        if platform_opts:
            col_transforms = getattr(platform_opts, "partition_transforms", {})
            if isinstance(col_transforms, dict) and col_name in col_transforms:
                return col_transforms[col_name]

        # Auto-detect transform based on column type
        if "DATE" in col_type:
            return f"months({col_name})"
        elif "TIMESTAMP" in col_type:
            return f"days({col_name})"
        elif "INT" in col_type or "BIGINT" in col_type:
            return f"bucket({self.default_bucket_count}, {col_name})"
        else:
            # Default to identity transform
            return col_name

    def _generate_hudi_tuning(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        """Generate Apache Hudi tuning clauses.

        Hudi supports:
        - PARTITIONED BY (col1, col2) with hive_style_partitioning
        - TBLPROPERTIES for:
          - hoodie.table.name (table name for metadata)
          - hoodie.datasource.write.recordkey.field (required: record key for dedup)
          - hoodie.datasource.write.precombine.field (ordering field for updates)
          - hoodie.table.type (COPY_ON_WRITE default, MERGE_ON_READ option)
          - hoodie.datasource.write.operation (insert, upsert, bulk_insert)
          - hoodie.datasource.write.hive_style_partitioning (for partition path)

        Unlike Delta Lake/Iceberg, Hudi requires explicit record key and precombine
        field configuration. These must be provided via platform_opts or detected
        from table schema.
        """
        from benchbox.core.tuning.ddl_generator import TuningClauses
        from benchbox.core.tuning.interface import TuningType

        clauses = TuningClauses()

        # Set table format
        clauses.additional_clauses.append("USING HUDI")

        # Get Hudi-specific configuration from platform_opts
        record_key = None
        precombine_field = None
        table_type = "COPY_ON_WRITE"  # Default: better for analytics reads
        write_operation = "upsert"  # Default write mode

        if platform_opts:
            record_key = getattr(platform_opts, "record_key", None)
            precombine_field = getattr(platform_opts, "precombine_field", None)
            table_type = getattr(platform_opts, "hudi_table_type", table_type)
            write_operation = getattr(platform_opts, "hudi_write_operation", write_operation)

        # Record key is required - use sensible defaults if not provided
        if record_key:
            clauses.table_properties["hoodie.datasource.write.recordkey.field"] = record_key
        # Note: If no record_key is provided, the caller should set it based on schema

        # Precombine field for ordering during updates
        if precombine_field:
            clauses.table_properties["hoodie.datasource.write.precombine.field"] = precombine_field

        # Table type: COW for analytics (faster reads), MOR for streaming (faster writes)
        clauses.table_properties["hoodie.table.type"] = table_type

        # Write operation mode
        clauses.table_properties["hoodie.datasource.write.operation"] = write_operation

        if not table_tuning:
            return clauses

        # Handle partitioning
        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.partition_by = f"PARTITIONED BY ({', '.join(col_names)})"

            # Enable hive-style partitioning for better compatibility
            clauses.table_properties["hoodie.datasource.write.hive_style_partitioning"] = "true"

        # Handle distribution via Hudi's file group assignment
        # Hudi uses record key for distribution, not explicit CLUSTERED BY
        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns and not record_key:
            # Use first distribution column as record key if not explicitly set
            sorted_cols = sorted(distribution_columns, key=lambda c: c.order)
            clauses.table_properties["hoodie.datasource.write.recordkey.field"] = sorted_cols[0].name

        # Handle sorting via Hudi's clustering
        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)

        all_sort_cols = list(sort_columns) + [c for c in cluster_columns if c not in sort_columns]
        if all_sort_cols:
            sorted_cols = sorted(all_sort_cols, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]

            # Enable Hudi clustering for sorted data layout
            clauses.table_properties["hoodie.clustering.inline"] = "true"
            clauses.table_properties["hoodie.clustering.inline.max.commits"] = "4"
            clauses.table_properties["hoodie.clustering.plan.strategy.sort.columns"] = ",".join(col_names)

        return clauses

    def _generate_parquet_tuning(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        """Generate Apache Parquet tuning clauses.

        Parquet/Spark SQL supports:
        - PARTITIONED BY (col1, col2)
        - CLUSTERED BY (col) INTO N BUCKETS
        - SORTED BY (col1, col2)
        """
        from benchbox.core.tuning.ddl_generator import TuningClauses
        from benchbox.core.tuning.interface import TuningType

        clauses = TuningClauses()

        # Set table format
        clauses.additional_clauses.append("USING PARQUET")

        if not table_tuning:
            return clauses

        # Handle partitioning
        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]
            clauses.partition_by = f"PARTITIONED BY ({', '.join(col_names)})"

        # Handle distribution via CLUSTERED BY
        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns:
            sorted_cols = sorted(distribution_columns, key=lambda c: c.order)
            col_names = [c.name for c in sorted_cols]

            bucket_count = self.default_bucket_count
            if platform_opts:
                bucket_count = getattr(platform_opts, "bucket_count", bucket_count)

            clauses.distribute_by = f"CLUSTERED BY ({', '.join(col_names)}) INTO {bucket_count} BUCKETS"

        # Handle sorting
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
        """Generate legacy Hive tuning clauses.

        Hive supports:
        - STORED AS (PARQUET, ORC, etc.)
        - PARTITIONED BY (col TYPE)
        - CLUSTERED BY (col) SORTED BY (col) INTO N BUCKETS
        """
        from benchbox.core.tuning.ddl_generator import TuningClauses
        from benchbox.core.tuning.interface import TuningType

        clauses = TuningClauses()

        # Set storage format
        storage_format = "PARQUET"
        if platform_opts:
            storage_format = getattr(platform_opts, "storage_format", storage_format)
        clauses.additional_clauses.append(f"STORED AS {storage_format}")

        if not table_tuning:
            return clauses

        # Handle partitioning
        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            # Hive requires type in PARTITIONED BY clause
            parts = []
            for col in sorted_cols:
                col_type = col.type if col.type else "STRING"
                parts.append(f"{col.name} {col_type}")
            clauses.partition_by = f"PARTITIONED BY ({', '.join(parts)})"

        # Handle distribution and sorting via CLUSTERED BY ... SORTED BY ... INTO BUCKETS
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
        """Generate Spark CREATE TABLE statement.

        Spark DDL structure:
        CREATE TABLE [IF NOT EXISTS] t (...)
        USING <format>
        PARTITIONED BY (...)
        CLUSTER BY (...) | CLUSTERED BY (...) INTO N BUCKETS
        [SORTED BY (...)]
        [TBLPROPERTIES (...)]
        """
        parts = ["CREATE TABLE"]

        if if_not_exists:
            parts.append("IF NOT EXISTS")

        # Table name with optional schema
        if schema:
            parts.append(f"{schema}.{table_name}")
        else:
            parts.append(table_name)

        statement = " ".join(parts)

        # Column definitions
        col_defs = []
        for col in columns:
            col_def = f"{col.name} {col.data_type}"
            col_defs.append(col_def)

        col_list = ",\n    ".join(col_defs)
        statement = f"{statement} (\n    {col_list}\n)"

        # Add tuning clauses if provided
        if tuning and not tuning.is_empty():
            # USING clause
            for clause in tuning.additional_clauses:
                statement = f"{statement}\n{clause}"

            # Partitioning
            if tuning.partition_by:
                statement = f"{statement}\n{tuning.partition_by}"

            # Clustering (Delta) or CLUSTERED BY (Parquet/Hive)
            if tuning.cluster_by:
                statement = f"{statement}\n{tuning.cluster_by}"
            if tuning.distribute_by:
                statement = f"{statement}\n{tuning.distribute_by}"

            # Sorting
            if tuning.sort_by:
                statement = f"{statement}\n{tuning.sort_by}"

            # Table properties
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
        """Get statements to run after data load.

        For Spark, this typically includes:
        - OPTIMIZE with Z-ORDER (Delta Lake)
        - ANALYZE TABLE for statistics

        Args:
            table_name: Name of the table.
            tuning: Tuning clauses with post_create_statements.
            schema: Optional schema prefix.

        Returns:
            List of SQL statements to execute after data load.
        """
        if not tuning or not tuning.post_create_statements:
            return []

        qualified_name = f"{schema}.{table_name}" if schema else table_name
        return [stmt.format(table_name=qualified_name) for stmt in tuning.post_create_statements]

    def supports_tuning_type(self, tuning_type: str) -> bool:
        """Check if this generator supports a specific tuning type."""
        return tuning_type.lower() in self.SUPPORTED_TUNING_TYPES
