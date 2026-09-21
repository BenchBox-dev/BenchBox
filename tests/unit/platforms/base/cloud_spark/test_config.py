"""Tests for SparkConfigOptimizer benchmark configuration.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.platforms.base.cloud_spark.config import (
    BenchmarkType,
    CloudPlatform,
    SparkAQEConfig,
    SparkConfig,
    SparkConfigOptimizer,
    SparkParallelismConfig,
    SparkResourceConfig,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestSparkResourceConfig:
    """Test SparkResourceConfig dataclass."""

    def test_default_values(self):
        """Test default resource configuration."""
        config = SparkResourceConfig()

        assert config.driver_memory == "4g"
        assert config.driver_cores == 2
        assert config.executor_memory == "4g"
        assert config.executor_cores == 2
        assert config.num_executors is None
        assert config.memory_fraction == 0.6

    def test_custom_values(self):
        """Test custom resource configuration."""
        config = SparkResourceConfig(
            driver_memory="8g",
            executor_memory="16g",
            executor_cores=4,
            num_executors=10,
        )

        assert config.driver_memory == "8g"
        assert config.executor_memory == "16g"
        assert config.executor_cores == 4
        assert config.num_executors == 10


class TestSparkParallelismConfig:
    """Test SparkParallelismConfig dataclass."""

    def test_default_values(self):
        """Test default parallelism configuration."""
        config = SparkParallelismConfig()

        assert config.shuffle_partitions == 200
        assert config.adaptive_enabled is True
        assert config.coalesce_partitions is True

    def test_custom_values(self):
        """Test custom parallelism configuration."""
        config = SparkParallelismConfig(
            shuffle_partitions=500,
            default_parallelism=500,
            adaptive_enabled=False,
        )

        assert config.shuffle_partitions == 500
        assert config.adaptive_enabled is False


class TestSparkConfig:
    """Test SparkConfig dataclass and to_dict() method."""

    def test_default_config_to_dict(self):
        """Test converting default config to dictionary."""
        config = SparkConfig()
        result = config.to_dict()

        assert "spark.driver.memory" in result
        assert "spark.executor.memory" in result
        assert "spark.sql.shuffle.partitions" in result
        assert "spark.sql.adaptive.enabled" in result

    def test_to_dict_values(self):
        """Test specific configuration values in dict."""
        config = SparkConfig(
            resources=SparkResourceConfig(
                driver_memory="8g",
                executor_memory="16g",
            ),
            parallelism=SparkParallelismConfig(
                shuffle_partitions=1000,
            ),
            aqe=SparkAQEConfig(
                enabled=True,
                skew_join_enabled=True,
            ),
        )
        result = config.to_dict()

        assert result["spark.driver.memory"] == "8g"
        assert result["spark.executor.memory"] == "16g"
        assert result["spark.sql.shuffle.partitions"] == "1000"
        assert result["spark.sql.adaptive.enabled"] == "true"
        assert result["spark.sql.adaptive.skewJoin.enabled"] == "true"

    def test_to_dict_dynamic_allocation(self):
        """Test dynamic allocation enabled when num_executors is None."""
        config = SparkConfig(resources=SparkResourceConfig(num_executors=None))
        result = config.to_dict()

        assert result["spark.dynamicAllocation.enabled"] == "true"

    def test_to_dict_fixed_executors(self):
        """Test dynamic allocation disabled when num_executors is set."""
        config = SparkConfig(resources=SparkResourceConfig(num_executors=10))
        result = config.to_dict()

        assert result["spark.dynamicAllocation.enabled"] == "false"
        assert result["spark.executor.instances"] == "10"

    def test_to_dict_extra_configs(self):
        """Test extra configs are included."""
        config = SparkConfig(
            extra={
                "spark.custom.setting": "value",
                "spark.another.setting": "123",
            }
        )
        result = config.to_dict()

        assert result["spark.custom.setting"] == "value"
        assert result["spark.another.setting"] == "123"


class TestSparkConfigOptimizerTPCH:
    """Test SparkConfigOptimizer.for_tpch() method."""

    def test_tpch_small_scale(self):
        """Test TPC-H config for small scale factor."""
        config = SparkConfigOptimizer.for_tpch(scale_factor=0.01)

        assert config.resources.driver_memory == "2g"
        assert config.resources.executor_memory == "2g"
        assert config.aqe.enabled is True

    def test_tpch_medium_scale(self):
        """Test TPC-H config for medium scale factor."""
        config = SparkConfigOptimizer.for_tpch(scale_factor=1.0)

        assert config.resources.driver_memory == "2g"
        assert config.resources.executor_memory == "2g"
        assert config.parallelism.shuffle_partitions >= 50

    def test_tpch_large_scale(self):
        """Test TPC-H config for large scale factor."""
        config = SparkConfigOptimizer.for_tpch(scale_factor=100)

        assert config.resources.driver_memory == "8g"
        assert config.resources.executor_memory == "8g"
        assert config.parallelism.shuffle_partitions >= 200

    def test_tpch_with_platform_string(self):
        """Test TPC-H config with platform as string."""
        config = SparkConfigOptimizer.for_tpch(
            scale_factor=1.0,
            platform="databricks",
        )

        result = config.to_dict()
        assert "spark.databricks.optimizer.dynamicFilePruning" in result

    def test_tpch_with_fixed_executors(self):
        """Test TPC-H config with fixed executor count."""
        config = SparkConfigOptimizer.for_tpch(
            scale_factor=1.0,
            num_executors=5,
        )

        assert config.resources.num_executors == 5


class TestSparkConfigOptimizerTPCDS:
    """Test SparkConfigOptimizer.for_tpcds() method."""

    def test_tpcds_small_scale(self):
        """Test TPC-DS config for small scale factor."""
        config = SparkConfigOptimizer.for_tpcds(scale_factor=1.0)

        assert config.aqe.enabled is True
        assert config.aqe.skew_join_enabled is True

    def test_tpcds_large_scale(self):
        """Test TPC-DS config for large scale factor."""
        config = SparkConfigOptimizer.for_tpcds(scale_factor=100)

        # TPC-DS needs more resources for complex queries
        assert config.resources.driver_memory != "2g"
        assert config.io.broadcast_timeout == 600

    def test_tpcds_more_partitions_than_tpch(self):
        """Test TPC-DS has more shuffle partitions than TPC-H at same scale."""
        tpch_config = SparkConfigOptimizer.for_tpch(scale_factor=10)
        tpcds_config = SparkConfigOptimizer.for_tpcds(scale_factor=10)

        # TPC-DS complexity factor should result in more partitions
        assert tpcds_config.parallelism.shuffle_partitions >= tpch_config.parallelism.shuffle_partitions


class TestSparkConfigOptimizerSSB:
    """Test SparkConfigOptimizer.for_ssb() method."""

    def test_ssb_smaller_than_tpch(self):
        """Test SSB config is smaller than TPC-H for same scale."""
        ssb_config = SparkConfigOptimizer.for_ssb(scale_factor=10)

        # SSB is simpler, should have fewer partitions
        assert ssb_config.parallelism.shuffle_partitions <= 200


class TestSparkConfigOptimizerPlatformOptimizations:
    """Test platform-specific optimizations."""

    def test_databricks_optimizations(self):
        """Test Databricks-specific optimizations are applied."""
        config = SparkConfigOptimizer.for_tpch(
            scale_factor=1.0,
            platform=CloudPlatform.DATABRICKS,
        )
        result = config.to_dict()

        assert result.get("spark.databricks.optimizer.dynamicFilePruning") == "true"
        assert result.get("spark.databricks.delta.optimizeWrite.enabled") == "true"

    def test_emr_optimizations(self):
        """Test EMR-specific optimizations are applied."""
        config = SparkConfigOptimizer.for_tpch(
            scale_factor=1.0,
            platform=CloudPlatform.EMR,
        )
        result = config.to_dict()

        assert result.get("spark.sql.optimizer.dynamicPartitionPruning.enabled") == "true"
        assert result.get("spark.emr.optimized.parquet.io.enabled") == "true"

    def test_glue_optimizations(self):
        """Test Glue-specific optimizations are applied."""
        config = SparkConfigOptimizer.for_tpch(
            scale_factor=1.0,
            platform=CloudPlatform.GLUE,
        )

        # Glue uses different memory model
        assert config.resources.memory_overhead_factor == 0.2


class TestSparkConfigOptimizerHelpers:
    """Test SparkConfigOptimizer helper methods."""

    def test_calculate_shuffle_partitions_small(self):
        """Test shuffle partition calculation for small data."""
        partitions = SparkConfigOptimizer._calculate_shuffle_partitions(0.1)

        # Should be at least minimum (50)
        assert partitions >= 50

    def test_calculate_shuffle_partitions_large(self):
        """Test shuffle partition calculation for large data."""
        partitions = SparkConfigOptimizer._calculate_shuffle_partitions(100)

        # Should scale with data size
        assert partitions > 200
        assert partitions <= 2000  # Should be capped

    def test_calculate_shuffle_partitions_with_complexity(self):
        """Test shuffle partition calculation with complexity factor."""
        base = SparkConfigOptimizer._calculate_shuffle_partitions(10)
        complex = SparkConfigOptimizer._calculate_shuffle_partitions(10, complexity_factor=2.0)

        assert complex >= base

    def test_increase_memory(self):
        """Test memory string increase."""
        result = SparkConfigOptimizer._increase_memory("4g", 1.5)
        assert result == "6g"

        result = SparkConfigOptimizer._increase_memory("8g", 2.0)
        assert result == "16g"

    def test_from_dict(self):
        """Test creating config from dictionary."""
        input_dict = {
            "spark.driver.memory": "8g",
            "spark.executor.memory": "16g",
            "spark.sql.shuffle.partitions": "500",
        }

        config = SparkConfigOptimizer.from_dict(input_dict)

        assert config.extra["spark.driver.memory"] == "8g"
        assert config.extra["spark.sql.shuffle.partitions"] == "500"


class TestCloudPlatformEnum:
    """Test CloudPlatform enum."""

    def test_all_platforms_defined(self):
        """Test all expected platforms are defined."""
        platforms = [p.value for p in CloudPlatform]

        assert "databricks" in platforms
        assert "emr" in platforms
        assert "dataproc" in platforms
        assert "synapse" in platforms
        assert "glue" in platforms
        assert "fabric" in platforms
        assert "local" in platforms


class TestOptimizerAdaptiveToggle:
    """SparkConfigOptimizer honors adaptive_enabled instead of force-enabling AQE."""

    AQE_KEYS = (
        "spark.sql.adaptive.enabled",
        "spark.sql.adaptive.coalescePartitions.enabled",
        "spark.sql.adaptive.skewJoin.enabled",
    )

    def test_tpch_disables_all_three_aqe_keys(self):
        config = SparkConfigOptimizer.for_tpch(scale_factor=1.0, adaptive_enabled=False)
        rendered = config.to_dict()
        assert [rendered[key] for key in self.AQE_KEYS] == ["false"] * 3
        assert config.parallelism.adaptive_enabled is False

    def test_tpch_defaults_to_aqe_on(self):
        rendered = SparkConfigOptimizer.for_tpch(scale_factor=1.0).to_dict()
        assert [rendered[key] for key in self.AQE_KEYS] == ["true"] * 3

    def test_tpcds_disables_all_three_aqe_keys(self):
        config = SparkConfigOptimizer.for_tpcds(scale_factor=1.0, adaptive_enabled=False)
        rendered = config.to_dict()
        assert [rendered[key] for key in self.AQE_KEYS] == ["false"] * 3

    def test_ssb_forwards_toggle_to_tpch(self):
        config = SparkConfigOptimizer.for_ssb(scale_factor=1.0, adaptive_enabled=False)
        rendered = config.to_dict()
        assert [rendered[key] for key in self.AQE_KEYS] == ["false"] * 3


class TestBenchmarkTypeEnum:
    """Test BenchmarkType enum."""

    def test_all_benchmarks_defined(self):
        """Test all expected benchmarks are defined."""
        benchmarks = [b.value for b in BenchmarkType]

        assert "tpch" in benchmarks
        assert "tpcds" in benchmarks
        assert "ssb" in benchmarks
        assert "clickbench" in benchmarks
        assert "custom" in benchmarks
