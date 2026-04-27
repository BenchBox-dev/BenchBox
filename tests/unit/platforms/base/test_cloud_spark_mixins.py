"""Tests for cloud Spark DDL and config mixins.

Covers SparkTuningMixin, CloudSparkConfigMixin, SparkDDLGeneratorMixin,
and SparkTableFormat enum.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.tuning.ddl_generator import ColumnDefinition, TuningClauses
from benchbox.core.tuning.interface import (
    ForeignKeyConfiguration,
    PrimaryKeyConfiguration,
    TableTuning,
    TuningColumn,
    TuningType,
)
from benchbox.platforms.base.cloud_spark.config import CloudPlatform
from benchbox.platforms.base.cloud_spark.mixins import (
    CloudSparkConfigMixin,
    SparkDDLGeneratorMixin,
    SparkTableFormat,
    SparkTuningMixin,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


# ---------------------------------------------------------------------------
# Minimal stub classes to host each mixin without a full adapter hierarchy
# ---------------------------------------------------------------------------


class StubSparkTuning(SparkTuningMixin):
    """Minimal stub to test SparkTuningMixin in isolation."""


class StubCloudSparkConfig(CloudSparkConfigMixin):
    """Minimal stub to test CloudSparkConfigMixin in isolation."""

    cloud_platform = CloudPlatform.DATAPROC_SERVERLESS
    _benchmark_type: str | None = None
    _scale_factor: float = 1.0
    _spark_config: dict = {}


class StubSparkDDL(SparkDDLGeneratorMixin):
    """Minimal stub to test SparkDDLGeneratorMixin with default PARQUET format."""

    table_format = SparkTableFormat.PARQUET


class StubDeltaDDL(SparkDDLGeneratorMixin):
    """DDL stub using DELTA format."""

    table_format = SparkTableFormat.DELTA


class StubIcebergDDL(SparkDDLGeneratorMixin):
    """DDL stub using ICEBERG format."""

    table_format = SparkTableFormat.ICEBERG


class StubHudiDDL(SparkDDLGeneratorMixin):
    """DDL stub using HUDI format."""

    table_format = SparkTableFormat.HUDI


class StubHiveDDL(SparkDDLGeneratorMixin):
    """DDL stub using HIVE format."""

    table_format = SparkTableFormat.HIVE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _col(name: str, col_type: str = "INTEGER", order: int = 1) -> TuningColumn:
    return TuningColumn(name=name, type=col_type, order=order)


def _table_tuning(
    *,
    partitioning=None,
    clustering=None,
    distribution=None,
    sorting=None,
) -> TableTuning:
    """Build a minimal TableTuning with at least one non-None list."""
    return TableTuning(
        table_name="test_table",
        partitioning=partitioning,
        clustering=clustering,
        distribution=distribution,
        sorting=sorting,
    )


# ---------------------------------------------------------------------------
# SparkTuningMixin
# ---------------------------------------------------------------------------


class TestSparkTuningMixin:
    def test_apply_primary_keys_disabled_returns_empty(self):
        mixin = StubSparkTuning()
        cfg = PrimaryKeyConfiguration(enabled=False)
        result = mixin.apply_primary_keys(cfg)
        assert result == []

    def test_apply_primary_keys_enabled_returns_empty_logs(self, caplog):
        mixin = StubSparkTuning()
        cfg = PrimaryKeyConfiguration(enabled=True)
        with caplog.at_level("INFO"):
            result = mixin.apply_primary_keys(cfg)
        assert result == []
        assert "Primary keys noted" in caplog.text

    def test_apply_primary_keys_none_returns_empty(self):
        mixin = StubSparkTuning()
        result = mixin.apply_primary_keys(None)
        assert result == []

    def test_apply_foreign_keys_disabled_returns_empty(self):
        mixin = StubSparkTuning()
        cfg = ForeignKeyConfiguration(enabled=False)
        result = mixin.apply_foreign_keys(cfg)
        assert result == []

    def test_apply_foreign_keys_enabled_returns_empty_logs(self, caplog):
        mixin = StubSparkTuning()
        cfg = ForeignKeyConfiguration(enabled=True)
        with caplog.at_level("INFO"):
            result = mixin.apply_foreign_keys(cfg)
        assert result == []
        assert "Foreign keys noted" in caplog.text

    def test_apply_foreign_keys_none_returns_empty(self):
        mixin = StubSparkTuning()
        result = mixin.apply_foreign_keys(None)
        assert result == []

    def test_apply_platform_optimizations_always_empty(self):
        mixin = StubSparkTuning()
        result = mixin.apply_platform_optimizations(MagicMock())
        assert result == []

    def test_apply_constraint_configuration_both_enabled(self, caplog):
        mixin = StubSparkTuning()
        pk_cfg = PrimaryKeyConfiguration(enabled=True)
        fk_cfg = ForeignKeyConfiguration(enabled=True)
        with caplog.at_level("INFO"):
            mixin.apply_constraint_configuration(pk_cfg, fk_cfg, connection=None)
        assert "Primary key constraints noted" in caplog.text
        assert "Foreign key constraints noted" in caplog.text

    def test_apply_constraint_configuration_both_disabled(self, caplog):
        mixin = StubSparkTuning()
        pk_cfg = PrimaryKeyConfiguration(enabled=False)
        fk_cfg = ForeignKeyConfiguration(enabled=False)
        with caplog.at_level("INFO"):
            mixin.apply_constraint_configuration(pk_cfg, fk_cfg, connection=None)
        assert "Primary key constraints noted" not in caplog.text
        assert "Foreign key constraints noted" not in caplog.text

    def test_apply_constraint_configuration_none_configs(self):
        mixin = StubSparkTuning()
        # Should not raise
        mixin.apply_constraint_configuration(None, None, connection=None)


# ---------------------------------------------------------------------------
# CloudSparkConfigMixin
# ---------------------------------------------------------------------------


class TestCloudSparkConfigMixin:
    @pytest.fixture(autouse=True)
    def _mock_optimizer(self):
        mock_config = MagicMock()
        mock_config.to_dict.return_value = {"spark.executor.memory": "4g"}
        with patch("benchbox.platforms.base.cloud_spark.mixins.SparkConfigOptimizer") as mock_cls:
            mock_cls.for_tpch.return_value = mock_config
            mock_cls.for_tpcds.return_value = mock_config
            mock_cls.for_ssb.return_value = mock_config
            self.mock_optimizer = mock_cls
            self.mock_config = mock_config
            yield

    def test_configure_for_tpch(self):
        mixin = StubCloudSparkConfig()
        mixin.configure_for_benchmark(connection=None, benchmark_type="tpch")
        self.mock_optimizer.for_tpch.assert_called_once()
        assert mixin._benchmark_type == "tpch"
        assert mixin._spark_config == {"spark.executor.memory": "4g"}

    def test_configure_for_tpcds(self):
        mixin = StubCloudSparkConfig()
        mixin.configure_for_benchmark(connection=None, benchmark_type="tpcds")
        self.mock_optimizer.for_tpcds.assert_called_once()
        assert mixin._benchmark_type == "tpcds"

    def test_configure_for_ssb(self):
        mixin = StubCloudSparkConfig()
        mixin.configure_for_benchmark(connection=None, benchmark_type="ssb")
        self.mock_optimizer.for_ssb.assert_called_once()
        assert mixin._benchmark_type == "ssb"

    def test_configure_for_unknown_falls_back_to_tpch(self):
        mixin = StubCloudSparkConfig()
        mixin.configure_for_benchmark(connection=None, benchmark_type="UNKNOWN_BENCH")
        self.mock_optimizer.for_tpch.assert_called_once()
        assert mixin._benchmark_type == "unknown_bench"

    def test_benchmark_type_lowercased(self):
        mixin = StubCloudSparkConfig()
        mixin.configure_for_benchmark(connection=None, benchmark_type="TPC-H")
        assert mixin._benchmark_type == "tpc-h"


# ---------------------------------------------------------------------------
# SparkTableFormat
# ---------------------------------------------------------------------------


class TestSparkTableFormat:
    def test_enum_values(self):
        assert SparkTableFormat.DELTA.value == "delta"
        assert SparkTableFormat.ICEBERG.value == "iceberg"
        assert SparkTableFormat.HUDI.value == "hudi"
        assert SparkTableFormat.PARQUET.value == "parquet"
        assert SparkTableFormat.HIVE.value == "hive"

    def test_is_str_enum(self):
        assert isinstance(SparkTableFormat.DELTA, str)


# ---------------------------------------------------------------------------
# SparkDDLGeneratorMixin - get_table_format
# ---------------------------------------------------------------------------


class TestGetTableFormat:
    def test_default_returns_class_format(self):
        mixin = StubSparkDDL()
        assert mixin.get_table_format() == SparkTableFormat.PARQUET

    def test_platform_opts_override(self):
        mixin = StubSparkDDL()
        opts = MagicMock()
        opts.table_format = "delta"
        result = mixin.get_table_format(opts)
        assert result == SparkTableFormat.DELTA

    def test_platform_opts_invalid_format_falls_back(self):
        mixin = StubSparkDDL()
        opts = MagicMock()
        opts.table_format = "nonexistent_format"
        result = mixin.get_table_format(opts)
        assert result == SparkTableFormat.PARQUET

    def test_platform_opts_none_table_format_attr(self):
        mixin = StubSparkDDL()
        opts = MagicMock()
        opts.table_format = None
        result = mixin.get_table_format(opts)
        assert result == SparkTableFormat.PARQUET


# ---------------------------------------------------------------------------
# SparkDDLGeneratorMixin - generate_tuning_clauses routing
# ---------------------------------------------------------------------------


class TestGenerateTuningClausesRouting:
    def test_routes_to_delta(self):
        mixin = StubDeltaDDL()
        clauses = mixin.generate_tuning_clauses(None)
        assert "USING DELTA" in clauses.additional_clauses

    def test_routes_to_iceberg(self):
        mixin = StubIcebergDDL()
        clauses = mixin.generate_tuning_clauses(None)
        assert "USING ICEBERG" in clauses.additional_clauses

    def test_routes_to_hudi(self):
        mixin = StubHudiDDL()
        clauses = mixin.generate_tuning_clauses(None)
        assert "USING HUDI" in clauses.additional_clauses

    def test_routes_to_parquet(self):
        mixin = StubSparkDDL()
        clauses = mixin.generate_tuning_clauses(None)
        assert "USING PARQUET" in clauses.additional_clauses

    def test_routes_to_hive(self):
        mixin = StubHiveDDL()
        clauses = mixin.generate_tuning_clauses(None)
        assert "STORED AS PARQUET" in clauses.additional_clauses

    def test_unknown_format_returns_empty_tuning_clauses(self):
        mixin = StubSparkDDL()

        def _fake_get_table_format(platform_opts=None):
            return object()

        mixin.get_table_format = _fake_get_table_format
        clauses = mixin.generate_tuning_clauses(None)
        assert clauses.is_empty()


# ---------------------------------------------------------------------------
# Delta tuning
# ---------------------------------------------------------------------------


class TestDeltaTuning:
    def test_no_tuning_adds_auto_optimize_props(self):
        mixin = StubDeltaDDL()
        clauses = mixin._generate_delta_tuning(None)
        assert clauses.table_properties["delta.autoOptimize.optimizeWrite"] == "true"
        assert clauses.table_properties["delta.autoOptimize.autoCompact"] == "true"

    def test_no_tuning_auto_optimize_disabled(self):
        mixin = StubDeltaDDL()
        opts = MagicMock()
        opts.enable_auto_optimize = False
        clauses = mixin._generate_delta_tuning(None, opts)
        assert "delta.autoOptimize.optimizeWrite" not in clauses.table_properties

    def test_partition_columns(self):
        mixin = StubDeltaDDL()
        tt = _table_tuning(partitioning=[_col("l_shipdate", "DATE", order=1)])
        clauses = mixin._generate_delta_tuning(tt)
        assert clauses.partition_by == "PARTITIONED BY (l_shipdate)"

    def test_cluster_by_liquid_clustering(self):
        mixin = StubDeltaDDL()
        tt = _table_tuning(clustering=[_col("l_orderkey", "BIGINT", order=1)])
        clauses = mixin._generate_delta_tuning(tt)
        assert clauses.cluster_by == "CLUSTER BY (l_orderkey)"

    def test_cluster_by_zorder_when_liquid_disabled(self):
        mixin = StubDeltaDDL()
        opts = MagicMock()
        opts.use_liquid_clustering = False
        opts.enable_auto_optimize = True
        tt = _table_tuning(clustering=[_col("l_orderkey", "BIGINT", order=1)])
        clauses = mixin._generate_delta_tuning(tt, opts)
        assert clauses.cluster_by is None
        assert any("ZORDER" in s for s in clauses.post_create_statements)

    def test_distribution_zorder_when_no_cluster_cols(self):
        mixin = StubDeltaDDL()
        tt = _table_tuning(distribution=[_col("l_orderkey", "BIGINT", order=1)])
        clauses = mixin._generate_delta_tuning(tt)
        assert any("ZORDER" in s for s in clauses.post_create_statements)

    def test_sort_columns_added_to_cluster(self):
        mixin = StubDeltaDDL()
        tt = _table_tuning(sorting=[_col("l_shipdate", "DATE", order=1)])
        clauses = mixin._generate_delta_tuning(tt)
        assert clauses.cluster_by == "CLUSTER BY (l_shipdate)"

    def test_auto_optimize_false_via_platform_opts(self):
        mixin = StubDeltaDDL()
        opts = MagicMock()
        opts.enable_auto_optimize = False
        opts.use_liquid_clustering = True
        tt = _table_tuning(partitioning=[_col("l_shipdate", "DATE", order=1)])
        clauses = mixin._generate_delta_tuning(tt, opts)
        assert "delta.autoOptimize.optimizeWrite" not in clauses.table_properties


# ---------------------------------------------------------------------------
# Iceberg tuning
# ---------------------------------------------------------------------------


class TestIcebergTuning:
    def test_no_tuning_returns_iceberg_clause_only(self):
        mixin = StubIcebergDDL()
        clauses = mixin._generate_iceberg_tuning(None)
        assert "USING ICEBERG" in clauses.additional_clauses
        assert clauses.partition_by is None

    def test_date_column_gets_months_transform(self):
        mixin = StubIcebergDDL()
        tt = _table_tuning(partitioning=[_col("o_orderdate", "DATE", order=1)])
        clauses = mixin._generate_iceberg_tuning(tt)
        assert "months(o_orderdate)" in clauses.partition_by

    def test_timestamp_column_gets_days_transform(self):
        mixin = StubIcebergDDL()
        tt = _table_tuning(partitioning=[_col("ts_col", "TIMESTAMP", order=1)])
        clauses = mixin._generate_iceberg_tuning(tt)
        assert "days(ts_col)" in clauses.partition_by

    def test_int_column_gets_bucket_transform(self):
        mixin = StubIcebergDDL()
        tt = _table_tuning(partitioning=[_col("o_orderkey", "INTEGER", order=1)])
        clauses = mixin._generate_iceberg_tuning(tt)
        assert f"bucket({mixin.default_bucket_count}, o_orderkey)" in clauses.partition_by

    def test_string_column_gets_identity_transform(self):
        mixin = StubIcebergDDL()
        tt = _table_tuning(partitioning=[_col("nation_name", "VARCHAR", order=1)])
        clauses = mixin._generate_iceberg_tuning(tt)
        assert "nation_name" in clauses.partition_by

    def test_explicit_partition_transform_via_platform_opts(self):
        mixin = StubIcebergDDL()
        opts = MagicMock()
        opts.partition_transforms = {"o_orderdate": "years(o_orderdate)"}
        tt = _table_tuning(partitioning=[_col("o_orderdate", "DATE", order=1)])
        clauses = mixin._generate_iceberg_tuning(tt, opts)
        assert "years(o_orderdate)" in clauses.partition_by

    def test_distribution_bucket_when_no_partition(self):
        mixin = StubIcebergDDL()
        tt = _table_tuning(distribution=[_col("o_orderkey", "INTEGER", order=1)])
        clauses = mixin._generate_iceberg_tuning(tt)
        assert "bucket(" in clauses.partition_by
        assert "o_orderkey" in clauses.partition_by

    def test_distribution_bucket_count_from_opts(self):
        mixin = StubIcebergDDL()
        opts = MagicMock()
        opts.bucket_count = 16
        opts.partition_transforms = {}
        tt = _table_tuning(distribution=[_col("o_orderkey", "INTEGER", order=1)])
        clauses = mixin._generate_iceberg_tuning(tt, opts)
        assert "bucket(16, o_orderkey)" in clauses.partition_by

    def test_sort_columns_added_to_write_sort_order(self):
        mixin = StubIcebergDDL()
        tt = _table_tuning(sorting=[_col("l_shipdate", "DATE", order=1)])
        clauses = mixin._generate_iceberg_tuning(tt)
        assert "write.sort-order" in clauses.table_properties
        assert "l_shipdate" in clauses.table_properties["write.sort-order"]

    def test_clustering_columns_added_to_sort_order(self):
        mixin = StubIcebergDDL()
        tt = _table_tuning(clustering=[_col("l_orderkey", "BIGINT", order=1)])
        clauses = mixin._generate_iceberg_tuning(tt)
        assert "write.sort-order" in clauses.table_properties

    def test_partition_transforms_dict_missing_key_falls_to_auto_detect(self):
        mixin = StubIcebergDDL()
        opts = MagicMock()
        opts.partition_transforms = {"other_col": "years(other_col)"}
        tt = _table_tuning(partitioning=[_col("o_orderdate", "DATE", order=1)])
        clauses = mixin._generate_iceberg_tuning(tt, opts)
        assert "months(o_orderdate)" in clauses.partition_by


# ---------------------------------------------------------------------------
# Hudi tuning
# ---------------------------------------------------------------------------


class TestHudiTuning:
    def test_no_tuning_sets_required_properties(self):
        mixin = StubHudiDDL()
        clauses = mixin._generate_hudi_tuning(None)
        assert "USING HUDI" in clauses.additional_clauses
        assert clauses.table_properties["hoodie.table.type"] == "COPY_ON_WRITE"
        assert clauses.table_properties["hoodie.datasource.write.operation"] == "upsert"

    def test_record_key_from_platform_opts(self):
        mixin = StubHudiDDL()
        opts = MagicMock()
        opts.record_key = "id"
        opts.precombine_field = "ts"
        opts.hudi_table_type = "MERGE_ON_READ"
        opts.hudi_write_operation = "insert"
        clauses = mixin._generate_hudi_tuning(None, opts)
        assert clauses.table_properties["hoodie.datasource.write.recordkey.field"] == "id"
        assert clauses.table_properties["hoodie.datasource.write.precombine.field"] == "ts"
        assert clauses.table_properties["hoodie.table.type"] == "MERGE_ON_READ"

    def test_partition_columns_enable_hive_style(self):
        mixin = StubHudiDDL()
        tt = _table_tuning(partitioning=[_col("o_orderdate", "DATE", order=1)])
        clauses = mixin._generate_hudi_tuning(tt)
        assert clauses.partition_by == "PARTITIONED BY (o_orderdate)"
        assert clauses.table_properties["hoodie.datasource.write.hive_style_partitioning"] == "true"

    def test_distribution_col_becomes_record_key_when_no_explicit_key(self):
        mixin = StubHudiDDL()
        tt = _table_tuning(distribution=[_col("o_orderkey", "INTEGER", order=1)])
        clauses = mixin._generate_hudi_tuning(tt)
        assert clauses.table_properties.get("hoodie.datasource.write.recordkey.field") == "o_orderkey"

    def test_sorting_enables_inline_clustering(self):
        mixin = StubHudiDDL()
        tt = _table_tuning(sorting=[_col("l_shipdate", "DATE", order=1)])
        clauses = mixin._generate_hudi_tuning(tt)
        assert clauses.table_properties["hoodie.clustering.inline"] == "true"
        assert "l_shipdate" in clauses.table_properties["hoodie.clustering.plan.strategy.sort.columns"]

    def test_clustering_columns_enable_inline_clustering(self):
        mixin = StubHudiDDL()
        tt = _table_tuning(clustering=[_col("l_orderkey", "BIGINT", order=1)])
        clauses = mixin._generate_hudi_tuning(tt)
        assert clauses.table_properties["hoodie.clustering.inline"] == "true"


# ---------------------------------------------------------------------------
# Parquet tuning
# ---------------------------------------------------------------------------


class TestParquetTuning:
    def test_no_tuning_returns_parquet_clause_only(self):
        mixin = StubSparkDDL()
        clauses = mixin._generate_parquet_tuning(None)
        assert "USING PARQUET" in clauses.additional_clauses
        assert clauses.partition_by is None
        assert clauses.distribute_by is None

    def test_partition_columns(self):
        mixin = StubSparkDDL()
        tt = _table_tuning(partitioning=[_col("l_shipdate", "DATE", order=1)])
        clauses = mixin._generate_parquet_tuning(tt)
        assert clauses.partition_by == "PARTITIONED BY (l_shipdate)"

    def test_distribution_columns_clustered_by(self):
        mixin = StubSparkDDL()
        tt = _table_tuning(distribution=[_col("o_orderkey", "INTEGER", order=1)])
        clauses = mixin._generate_parquet_tuning(tt)
        assert "CLUSTERED BY (o_orderkey)" in clauses.distribute_by
        assert f"INTO {mixin.default_bucket_count} BUCKETS" in clauses.distribute_by

    def test_distribution_bucket_count_override(self):
        mixin = StubSparkDDL()
        opts = MagicMock()
        opts.bucket_count = 64
        tt = _table_tuning(distribution=[_col("o_orderkey", "INTEGER", order=1)])
        clauses = mixin._generate_parquet_tuning(tt, opts)
        assert "INTO 64 BUCKETS" in clauses.distribute_by

    def test_sort_columns_basic(self):
        mixin = StubSparkDDL()
        tt = _table_tuning(sorting=[_col("l_shipdate", "DATE", order=1)])
        clauses = mixin._generate_parquet_tuning(tt)
        assert clauses.sort_by == "SORTED BY (l_shipdate)"

    def test_sort_column_with_desc(self):
        mixin = StubSparkDDL()
        col = TuningColumn(name="l_shipdate", type="DATE", order=1, sort_order="DESC")
        tt = _table_tuning(sorting=[col])
        clauses = mixin._generate_parquet_tuning(tt)
        assert "l_shipdate DESC" in clauses.sort_by

    def test_sort_column_with_nulls_position(self):
        mixin = StubSparkDDL()
        col = TuningColumn(name="l_shipdate", type="DATE", order=1, nulls_position="FIRST")
        tt = _table_tuning(sorting=[col])
        clauses = mixin._generate_parquet_tuning(tt)
        assert "NULLS FIRST" in clauses.sort_by

    def test_clustering_columns_merged_into_sort(self):
        mixin = StubSparkDDL()
        tt = _table_tuning(clustering=[_col("l_orderkey", "BIGINT", order=1)])
        clauses = mixin._generate_parquet_tuning(tt)
        assert clauses.sort_by == "SORTED BY (l_orderkey)"


# ---------------------------------------------------------------------------
# Hive tuning
# ---------------------------------------------------------------------------


class TestHiveTuning:
    def test_no_tuning_defaults_stored_as_parquet(self):
        mixin = StubHiveDDL()
        clauses = mixin._generate_hive_tuning(None)
        assert "STORED AS PARQUET" in clauses.additional_clauses

    def test_storage_format_override(self):
        mixin = StubHiveDDL()
        opts = MagicMock()
        opts.storage_format = "ORC"
        clauses = mixin._generate_hive_tuning(None, opts)
        assert "STORED AS ORC" in clauses.additional_clauses

    def test_partition_columns_include_type(self):
        mixin = StubHiveDDL()
        tt = _table_tuning(partitioning=[_col("l_shipdate", "DATE", order=1)])
        clauses = mixin._generate_hive_tuning(tt)
        assert clauses.partition_by == "PARTITIONED BY (l_shipdate DATE)"

    def test_partition_column_no_type_defaults_to_string(self):
        mixin = StubHiveDDL()
        col_mock = MagicMock()
        col_mock.type = ""
        col_mock.name = "region"
        col_mock.order = 1
        tt = MagicMock()
        tt.get_columns_by_type.side_effect = lambda t: ([col_mock] if t == TuningType.PARTITIONING else [])
        clauses = mixin._generate_hive_tuning(tt)
        assert "region STRING" in clauses.partition_by

    def test_distribution_columns_clustered_by_into_buckets(self):
        mixin = StubHiveDDL()
        tt = _table_tuning(distribution=[_col("o_orderkey", "INTEGER", order=1)])
        clauses = mixin._generate_hive_tuning(tt)
        assert "CLUSTERED BY (o_orderkey)" in clauses.distribute_by
        assert f"INTO {mixin.default_bucket_count} BUCKETS" in clauses.distribute_by

    def test_distribution_with_sorting_adds_sorted_by(self):
        mixin = StubHiveDDL()
        tt = _table_tuning(
            distribution=[_col("o_orderkey", "INTEGER", order=1)],
            sorting=[_col("l_shipdate", "DATE", order=2)],
        )
        clauses = mixin._generate_hive_tuning(tt)
        assert "SORTED BY (l_shipdate)" in clauses.distribute_by

    def test_bucket_count_override(self):
        mixin = StubHiveDDL()
        opts = MagicMock()
        opts.bucket_count = 8
        opts.storage_format = "PARQUET"
        tt = _table_tuning(distribution=[_col("o_orderkey", "INTEGER", order=1)])
        clauses = mixin._generate_hive_tuning(tt, opts)
        assert "INTO 8 BUCKETS" in clauses.distribute_by


# ---------------------------------------------------------------------------
# generate_create_table_ddl
# ---------------------------------------------------------------------------


class TestGenerateCreateTableDDL:
    def _columns(self):
        return [
            ColumnDefinition(name="id", data_type="BIGINT"),
            ColumnDefinition(name="name", data_type="VARCHAR(255)"),
        ]

    def test_basic_ddl_no_tuning(self):
        mixin = StubSparkDDL()
        ddl = mixin.generate_create_table_ddl("my_table", self._columns())
        assert "CREATE TABLE my_table" in ddl
        assert "id BIGINT" in ddl
        assert "name VARCHAR(255)" in ddl
        assert ddl.endswith(";")

    def test_if_not_exists(self):
        mixin = StubSparkDDL()
        ddl = mixin.generate_create_table_ddl("my_table", self._columns(), if_not_exists=True)
        assert "IF NOT EXISTS" in ddl

    def test_schema_prefix(self):
        mixin = StubSparkDDL()
        ddl = mixin.generate_create_table_ddl("my_table", self._columns(), schema="my_schema")
        assert "my_schema.my_table" in ddl

    def test_with_tuning_clauses(self):
        mixin = StubDeltaDDL()
        tt = _table_tuning(partitioning=[_col("l_shipdate", "DATE", order=1)])
        tuning = mixin.generate_tuning_clauses(tt)
        ddl = mixin.generate_create_table_ddl("lineitem", self._columns(), tuning=tuning)
        assert "USING DELTA" in ddl
        assert "PARTITIONED BY (l_shipdate)" in ddl

    def test_tblproperties_rendered(self):
        mixin = StubDeltaDDL()
        tuning = mixin.generate_tuning_clauses(None)  # adds auto-optimize props
        ddl = mixin.generate_create_table_ddl("lineitem", self._columns(), tuning=tuning)
        assert "TBLPROPERTIES" in ddl

    def test_empty_tuning_skipped(self):
        mixin = StubSparkDDL()
        empty_tuning = TuningClauses()
        ddl = mixin.generate_create_table_ddl("my_table", self._columns(), tuning=empty_tuning)
        # Empty tuning - no extra clauses
        assert "TBLPROPERTIES" not in ddl
        assert "USING" not in ddl

    def test_distribute_by_rendered(self):
        mixin = StubSparkDDL()
        tt = _table_tuning(distribution=[_col("o_orderkey", "INTEGER", order=1)])
        tuning = mixin.generate_tuning_clauses(tt)
        ddl = mixin.generate_create_table_ddl("orders", self._columns(), tuning=tuning)
        assert "CLUSTERED BY" in ddl

    def test_sort_by_rendered(self):
        mixin = StubSparkDDL()
        tt = _table_tuning(sorting=[_col("l_shipdate", "DATE", order=1)])
        tuning = mixin.generate_tuning_clauses(tt)
        ddl = mixin.generate_create_table_ddl("lineitem", self._columns(), tuning=tuning)
        assert "SORTED BY" in ddl

    def test_cluster_by_rendered(self):
        mixin = StubDeltaDDL()
        tt = _table_tuning(clustering=[_col("l_orderkey", "BIGINT", order=1)])
        tuning = mixin.generate_tuning_clauses(tt)
        assert tuning.cluster_by is not None
        ddl = mixin.generate_create_table_ddl("lineitem", self._columns(), tuning=tuning)
        assert "CLUSTER BY" in ddl


# ---------------------------------------------------------------------------
# get_post_load_statements
# ---------------------------------------------------------------------------


class TestGetPostLoadStatements:
    def test_no_post_create_statements_returns_empty(self):
        mixin = StubDeltaDDL()
        tuning = TuningClauses()
        result = mixin.get_post_load_statements("lineitem", tuning)
        assert result == []

    def test_none_tuning_returns_empty(self):
        mixin = StubDeltaDDL()
        result = mixin.get_post_load_statements("lineitem", None)
        assert result == []

    def test_post_create_statements_formatted_with_table_name(self):
        mixin = StubDeltaDDL()
        tuning = TuningClauses()
        tuning.post_create_statements.append("OPTIMIZE {table_name} ZORDER BY (id)")
        result = mixin.get_post_load_statements("lineitem", tuning)
        assert result == ["OPTIMIZE lineitem ZORDER BY (id)"]

    def test_schema_prefix_in_post_load(self):
        mixin = StubDeltaDDL()
        tuning = TuningClauses()
        tuning.post_create_statements.append("OPTIMIZE {table_name} ZORDER BY (id)")
        result = mixin.get_post_load_statements("lineitem", tuning, schema="tpch")
        assert result == ["OPTIMIZE tpch.lineitem ZORDER BY (id)"]

    def test_multiple_post_load_statements(self):
        mixin = StubDeltaDDL()
        tuning = TuningClauses()
        tuning.post_create_statements.extend(
            [
                "OPTIMIZE {table_name}",
                "ANALYZE TABLE {table_name}",
            ]
        )
        result = mixin.get_post_load_statements("orders", tuning)
        assert len(result) == 2
        assert "OPTIMIZE orders" in result[0]
        assert "ANALYZE TABLE orders" in result[1]


# ---------------------------------------------------------------------------
# supports_tuning_type
# ---------------------------------------------------------------------------


class TestSupportsTuningType:
    def test_supported_types(self):
        mixin = StubSparkDDL()
        for t in ("partitioning", "clustering", "sorting", "distribution"):
            assert mixin.supports_tuning_type(t) is True

    def test_unsupported_type(self):
        mixin = StubSparkDDL()
        assert mixin.supports_tuning_type("primary_keys") is False

    def test_case_insensitive(self):
        mixin = StubSparkDDL()
        assert mixin.supports_tuning_type("PARTITIONING") is True
