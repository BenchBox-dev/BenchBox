"""Spark configuration optimizer for benchmark workloads.

Provides optimized Spark configurations for different benchmark types
and cloud platforms. Configurations are tuned for TPC-H, TPC-DS, and
other analytical workloads.

Usage:
    from benchbox.platforms.base.cloud_spark import SparkConfigOptimizer

    # Get TPC-H optimized config for scale factor 10
    config = SparkConfigOptimizer.for_tpch(scale_factor=10)

    # Get platform-specific config
    config = SparkConfigOptimizer.for_tpch(
        scale_factor=10,
        platform="databricks",
        instance_type="r5.2xlarge",
    )

    # Apply to Spark session builder
    for key, value in config.items():
        builder.config(key, value)

Configuration Categories:
- Memory: Driver/executor memory, shuffle buffer sizes
- Parallelism: Shuffle partitions, default parallelism
- AQE: Adaptive Query Execution settings
- I/O: Compression, serialization, file formats
- Platform: Cloud provider-specific optimizations

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BenchmarkType(Enum):
    """Supported benchmark types for configuration optimization."""

    TPCH = "tpch"
    TPCDS = "tpcds"
    SSB = "ssb"
    CLICKBENCH = "clickbench"
    CUSTOM = "custom"


class CloudPlatform(Enum):
    """Cloud platforms with platform-specific optimizations."""

    DATABRICKS = "databricks"
    EMR = "emr"
    EMR_SERVERLESS = "emr-serverless"
    DATAPROC = "dataproc"
    DATAPROC_SERVERLESS = "dataproc-serverless"
    SYNAPSE = "synapse"
    GLUE = "glue"
    FABRIC = "fabric"
    QUANTON = "quanton"
    LOCAL = "local"


@dataclass
class SparkResourceConfig:
    """Resource allocation configuration."""

    driver_memory: str = "4g"
    driver_cores: int = 2
    executor_memory: str = "4g"
    executor_cores: int = 2
    num_executors: int | None = None  # None = dynamic allocation
    memory_overhead_factor: float = 0.1
    memory_fraction: float = 0.6
    storage_fraction: float = 0.5


@dataclass
class SparkParallelismConfig:
    """Parallelism and partitioning configuration."""

    shuffle_partitions: int = 200
    default_parallelism: int = 200
    adaptive_enabled: bool = True
    coalesce_partitions: bool = True
    min_partition_size: str = "64MB"
    max_partition_size: str = "256MB"
    target_post_shuffle_input_size: str = "64MB"


@dataclass
class SparkIOConfig:
    """I/O and serialization configuration."""

    compression_codec: str = "zstd"
    serializer: str = "org.apache.spark.serializer.KryoSerializer"
    parquet_compression: str = "zstd"
    parquet_filter_pushdown: bool = True
    parquet_column_index_filter: bool = True
    broadcast_timeout: int = 300
    network_timeout: int = 600


@dataclass
class SparkAQEConfig:
    """Adaptive Query Execution configuration."""

    enabled: bool = True
    coalesce_partitions_enabled: bool = True
    coalesce_partitions_min_partition_num: int = 1
    skew_join_enabled: bool = True
    skew_join_skewed_partition_factor: float = 5.0
    skew_join_skewed_partition_threshold: str = "256MB"
    local_shuffle_reader_enabled: bool = True
    optimize_skewed_join_enabled: bool = True


@dataclass
class SparkConfig:
    """Complete Spark configuration for benchmarks."""

    resources: SparkResourceConfig = field(default_factory=SparkResourceConfig)
    parallelism: SparkParallelismConfig = field(default_factory=SparkParallelismConfig)
    io: SparkIOConfig = field(default_factory=SparkIOConfig)
    aqe: SparkAQEConfig = field(default_factory=SparkAQEConfig)
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, str]:
        """Convert to Spark configuration dictionary.

        Returns:
            Dictionary of Spark config key-value pairs
        """
        config: dict[str, str] = {}

        # Resource configs
        config["spark.driver.memory"] = self.resources.driver_memory
        config["spark.driver.cores"] = str(self.resources.driver_cores)
        config["spark.executor.memory"] = self.resources.executor_memory
        config["spark.executor.cores"] = str(self.resources.executor_cores)
        config["spark.memory.fraction"] = str(self.resources.memory_fraction)
        config["spark.memory.storageFraction"] = str(self.resources.storage_fraction)

        if self.resources.num_executors is not None:
            config["spark.executor.instances"] = str(self.resources.num_executors)
            config["spark.dynamicAllocation.enabled"] = "false"
        else:
            config["spark.dynamicAllocation.enabled"] = "true"

        # Parallelism configs
        config["spark.sql.shuffle.partitions"] = str(self.parallelism.shuffle_partitions)
        config["spark.default.parallelism"] = str(self.parallelism.default_parallelism)

        # AQE configs
        config["spark.sql.adaptive.enabled"] = str(self.aqe.enabled).lower()
        config["spark.sql.adaptive.coalescePartitions.enabled"] = str(self.aqe.coalesce_partitions_enabled).lower()
        config["spark.sql.adaptive.coalescePartitions.minPartitionNum"] = str(
            self.aqe.coalesce_partitions_min_partition_num
        )
        config["spark.sql.adaptive.skewJoin.enabled"] = str(self.aqe.skew_join_enabled).lower()
        config["spark.sql.adaptive.skewJoin.skewedPartitionFactor"] = str(self.aqe.skew_join_skewed_partition_factor)
        config["spark.sql.adaptive.skewJoin.skewedPartitionThresholdInBytes"] = (
            self.aqe.skew_join_skewed_partition_threshold
        )
        config["spark.sql.adaptive.localShuffleReader.enabled"] = str(self.aqe.local_shuffle_reader_enabled).lower()

        # I/O configs
        config["spark.io.compression.codec"] = self.io.compression_codec
        config["spark.serializer"] = self.io.serializer
        config["spark.sql.parquet.compression.codec"] = self.io.parquet_compression
        config["spark.sql.parquet.filterPushdown"] = str(self.io.parquet_filter_pushdown).lower()
        config["spark.sql.parquet.columnIndex.enabled"] = str(self.io.parquet_column_index_filter).lower()
        config["spark.sql.broadcastTimeout"] = str(self.io.broadcast_timeout)
        config["spark.network.timeout"] = str(self.io.network_timeout)

        # Extra configs
        config.update(self.extra)

        return config


class SparkConfigOptimizer:
    """Optimizer for benchmark-specific Spark configurations.

    Provides factory methods to create optimized configurations for
    different benchmark types, scale factors, and cloud platforms.
    """

    # Scale factor to data size mapping (approximate GB)
    SCALE_TO_GB = {
        0.01: 0.01,
        0.1: 0.1,
        1: 1,
        10: 10,
        100: 100,
        1000: 1000,
    }

    @classmethod
    def for_tpch(
        cls,
        scale_factor: float = 1.0,
        platform: str | CloudPlatform = CloudPlatform.LOCAL,
        instance_type: str | None = None,
        num_executors: int | None = None,
        adaptive_enabled: bool = True,
    ) -> SparkConfig:
        """Create optimized configuration for TPC-H benchmark.

        TPC-H characteristics:
        - 8 tables with known size ratios
        - 22 queries with varying complexity
        - Heavy on joins and aggregations
        - Moderate data skew in some queries

        Args:
            scale_factor: TPC-H scale factor (1 = 1GB)
            platform: Cloud platform for optimizations
            instance_type: Instance type for resource sizing
            num_executors: Number of executors (None = auto)
            adaptive_enabled: Adaptive Query Execution on/off. The three AQE
                keys (enabled, coalescePartitions, skewJoin) render explicitly
                in both directions; an explicit user spark_config entry still
                wins downstream.

        Returns:
            Optimized SparkConfig for TPC-H
        """
        if isinstance(platform, str):
            platform = CloudPlatform(platform.lower())

        # Calculate resources based on scale factor
        data_gb = scale_factor
        shuffle_partitions = cls._calculate_shuffle_partitions(data_gb)
        resources = cls._calculate_resources(data_gb, platform, instance_type, num_executors)

        config = SparkConfig(
            resources=resources,
            parallelism=SparkParallelismConfig(
                shuffle_partitions=shuffle_partitions,
                default_parallelism=shuffle_partitions,
                adaptive_enabled=adaptive_enabled,
                target_post_shuffle_input_size="64MB",
            ),
            io=SparkIOConfig(
                compression_codec="zstd",
                parquet_compression="zstd",
                parquet_filter_pushdown=True,
            ),
            aqe=SparkAQEConfig(
                enabled=adaptive_enabled,
                coalesce_partitions_enabled=adaptive_enabled,
                skew_join_enabled=adaptive_enabled,
                local_shuffle_reader_enabled=adaptive_enabled,
                skew_join_skewed_partition_factor=5.0,
            ),
        )

        # Apply platform-specific optimizations
        cls._apply_platform_optimizations(config, platform, BenchmarkType.TPCH)

        return config

    @classmethod
    def for_tpcds(
        cls,
        scale_factor: float = 1.0,
        platform: str | CloudPlatform = CloudPlatform.LOCAL,
        instance_type: str | None = None,
        num_executors: int | None = None,
        adaptive_enabled: bool = True,
    ) -> SparkConfig:
        """Create optimized configuration for TPC-DS benchmark.

        TPC-DS characteristics:
        - 24 tables with complex relationships
        - 99 queries with high complexity
        - Heavy on subqueries and CTEs
        - Significant data skew

        Args:
            scale_factor: TPC-DS scale factor (1 = 1GB)
            platform: Cloud platform for optimizations
            instance_type: Instance type for resource sizing
            num_executors: Number of executors (None = auto)
            adaptive_enabled: Adaptive Query Execution on/off (default: True).

        Returns:
            Optimized SparkConfig for TPC-DS
        """
        if isinstance(platform, str):
            platform = CloudPlatform(platform.lower())

        # TPC-DS needs more shuffle partitions due to complexity
        data_gb = scale_factor
        shuffle_partitions = cls._calculate_shuffle_partitions(data_gb, complexity_factor=1.5)
        resources = cls._calculate_resources(data_gb, platform, instance_type, num_executors)

        # TPC-DS benefits from more executor memory for complex queries
        if data_gb >= 10:
            resources.executor_memory = cls._increase_memory(resources.executor_memory, 1.5)

        config = SparkConfig(
            resources=resources,
            parallelism=SparkParallelismConfig(
                shuffle_partitions=shuffle_partitions,
                default_parallelism=shuffle_partitions,
                adaptive_enabled=adaptive_enabled,
                target_post_shuffle_input_size="128MB",  # Larger for TPC-DS
            ),
            io=SparkIOConfig(
                compression_codec="zstd",
                parquet_compression="zstd",
                parquet_filter_pushdown=True,
                broadcast_timeout=600,  # Longer timeout for complex queries
            ),
            aqe=SparkAQEConfig(
                enabled=adaptive_enabled,
                coalesce_partitions_enabled=adaptive_enabled,
                skew_join_enabled=adaptive_enabled,
                local_shuffle_reader_enabled=adaptive_enabled,
                skew_join_skewed_partition_factor=3.0,  # More aggressive skew handling
                skew_join_skewed_partition_threshold="128MB",
            ),
        )

        # Apply platform-specific optimizations
        cls._apply_platform_optimizations(config, platform, BenchmarkType.TPCDS)

        return config

    @classmethod
    def for_ssb(
        cls,
        scale_factor: float = 1.0,
        platform: str | CloudPlatform = CloudPlatform.LOCAL,
        adaptive_enabled: bool = True,
        **kwargs: Any,
    ) -> SparkConfig:
        """Create optimized configuration for Star Schema Benchmark.

        SSB characteristics:
        - Star schema with 1 fact + 4 dimension tables
        - 13 queries focused on aggregations
        - Simpler than TPC-H/DS

        Args:
            scale_factor: SSB scale factor
            platform: Cloud platform
            adaptive_enabled: Adaptive Query Execution on/off (default: True).
            **kwargs: Additional configuration

        Returns:
            Optimized SparkConfig for SSB
        """
        # SSB is simpler, use TPC-H config as base with lower resources
        config = cls.for_tpch(scale_factor * 0.5, platform, adaptive_enabled=adaptive_enabled, **kwargs)

        # SSB queries are simpler, reduce partitions
        config.parallelism.shuffle_partitions = max(50, config.parallelism.shuffle_partitions // 2)

        return config

    @classmethod
    def _calculate_shuffle_partitions(
        cls,
        data_gb: float,
        complexity_factor: float = 1.0,
    ) -> int:
        """Calculate optimal shuffle partitions based on data size.

        Rule of thumb:
        - 1 partition per 64-128MB of data after shuffle
        - Complex queries need more partitions
        - Minimum of 50, maximum of 2000

        Args:
            data_gb: Data size in GB
            complexity_factor: Multiplier for complex benchmarks

        Returns:
            Recommended shuffle partition count
        """
        # Estimate shuffle data as 2x input (joins expand data)
        shuffle_gb = data_gb * 2 * complexity_factor

        # Target 64MB per partition
        partitions = int(shuffle_gb * 1024 / 64)

        # Clamp to reasonable range
        return max(50, min(2000, partitions))

    @classmethod
    def _calculate_resources(
        cls,
        data_gb: float,
        platform: CloudPlatform,
        instance_type: str | None,
        num_executors: int | None,
    ) -> SparkResourceConfig:
        """Calculate resource allocation based on data size.

        Args:
            data_gb: Data size in GB
            platform: Cloud platform
            instance_type: Instance type for sizing hints
            num_executors: Fixed executor count or None for dynamic

        Returns:
            Resource configuration
        """
        # Base configuration for small datasets
        resources = SparkResourceConfig()

        if data_gb <= 1:
            resources.driver_memory = "2g"
            resources.executor_memory = "2g"
            resources.executor_cores = 2
        elif data_gb <= 10:
            resources.driver_memory = "4g"
            resources.executor_memory = "4g"
            resources.executor_cores = 4
        elif data_gb <= 100:
            resources.driver_memory = "8g"
            resources.executor_memory = "8g"
            resources.executor_cores = 4
        else:
            resources.driver_memory = "16g"
            resources.executor_memory = "16g"
            resources.executor_cores = 8

        resources.num_executors = num_executors

        return resources

    @classmethod
    def _increase_memory(cls, memory_str: str, factor: float) -> str:
        """Increase memory specification by a factor.

        Args:
            memory_str: Memory string like "4g"
            factor: Multiplication factor

        Returns:
            Increased memory string
        """
        unit = memory_str[-1].lower()
        value = int(memory_str[:-1])
        new_value = int(value * factor)
        return f"{new_value}{unit}"

    @classmethod
    def _apply_platform_optimizations(
        cls,
        config: SparkConfig,
        platform: CloudPlatform,
        benchmark: BenchmarkType,
    ) -> None:
        """Apply platform-specific optimizations.

        Args:
            config: Configuration to modify
            platform: Cloud platform
            benchmark: Benchmark type
        """
        if platform == CloudPlatform.DATABRICKS:
            # Databricks-specific optimizations
            config.extra["spark.databricks.optimizer.dynamicFilePruning"] = "true"
            config.extra["spark.databricks.delta.optimizeWrite.enabled"] = "true"
            config.extra["spark.databricks.delta.autoCompact.enabled"] = "true"

        elif platform == CloudPlatform.EMR:
            # EMR-specific optimizations
            config.extra["spark.sql.optimizer.dynamicPartitionPruning.enabled"] = "true"
            config.extra["spark.emr.optimized.parquet.io.enabled"] = "true"

        elif platform == CloudPlatform.DATAPROC:
            # Dataproc-specific optimizations
            config.extra["spark.sql.optimizer.dynamicPartitionPruning.enabled"] = "true"

        elif platform == CloudPlatform.GLUE:
            # Glue-specific optimizations
            config.extra["spark.sql.parquet.filterPushdown"] = "true"
            # Glue uses different memory model
            config.resources.memory_overhead_factor = 0.2

        elif platform == CloudPlatform.SYNAPSE:
            # Synapse-specific optimizations
            config.extra["spark.sql.optimizer.dynamicPartitionPruning.enabled"] = "true"

        elif platform == CloudPlatform.QUANTON:
            # Onehouse Quanton-specific optimizations
            config.extra["spark.sql.optimizer.dynamicPartitionPruning.enabled"] = "true"
            config.extra["spark.sql.parquet.filterPushdown"] = "true"
            # Quanton uses intelligent lakehouse I/O optimization
            config.extra["spark.sql.adaptive.advisoryPartitionSizeInBytes"] = "67108864"  # 64MB

    @classmethod
    def merge_configs(cls, *configs: SparkConfig) -> SparkConfig:
        """Merge multiple SparkConfigs, later configs override earlier.

        Args:
            *configs: SparkConfig objects to merge

        Returns:
            Merged SparkConfig
        """
        if not configs:
            return SparkConfig()

        result = SparkConfig()
        result_dict = result.to_dict()

        for config in configs:
            config_dict = config.to_dict()
            result_dict.update(config_dict)

        # Reconstruct from merged dict
        result.extra = result_dict
        return result

    @classmethod
    def from_dict(cls, config_dict: dict[str, str]) -> SparkConfig:
        """Create SparkConfig from a dictionary.

        Args:
            config_dict: Spark configuration dictionary

        Returns:
            SparkConfig with values from dict
        """
        config = SparkConfig()
        config.extra = dict(config_dict)
        return config
