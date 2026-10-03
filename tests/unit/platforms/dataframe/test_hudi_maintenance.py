"""Tests for Apache Hudi maintenance operations.

These tests verify the HudiMaintenanceOperations class and its integration
with PySpark SQL. Since Hudi requires a SparkSession with the hudi-spark-bundle,
most tests are mocked to avoid heavy dependencies in unit tests.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Check if pyspark is available
try:
    from pyspark.sql import SparkSession

    PYSPARK_AVAILABLE = True
except ImportError:
    SparkSession = None  # type: ignore[assignment, misc]
    PYSPARK_AVAILABLE = False

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestHudiMaintenanceAvailability:
    """Tests for Hudi maintenance availability and configuration."""

    def test_hudi_requires_spark_session(self):

        from benchbox.core.dataframe.maintenance_interface import (
            get_maintenance_operations_for_platform,
        )

        # Hudi requires SparkSession, so factory returns None with debug message
        result = get_maintenance_operations_for_platform("hudi")
        assert result is None

    def test_hudi_capabilities_defined(self):

        from benchbox.core.dataframe.maintenance_interface import HUDI_CAPABILITIES

        assert HUDI_CAPABILITIES.platform_name == "hudi"
        assert HUDI_CAPABILITIES.supports_insert is True
        assert HUDI_CAPABILITIES.supports_delete is True
        assert HUDI_CAPABILITIES.supports_update is True
        assert HUDI_CAPABILITIES.supports_merge is True
        assert HUDI_CAPABILITIES.supports_transactions is True
        assert HUDI_CAPABILITIES.supports_time_travel is True

    def test_hudi_tpc_compliance(self):

        from benchbox.core.dataframe.maintenance_interface import HUDI_CAPABILITIES

        is_compliant, missing = HUDI_CAPABILITIES.validate_tpc_compliance()
        assert is_compliant is True
        assert len(missing) == 0

    def test_hudi_notes_mention_pyspark(self):
        """Test that Hudi capabilities notes mention PySpark requirement."""
        from benchbox.core.dataframe.maintenance_interface import HUDI_CAPABILITIES

        assert "PySpark" in HUDI_CAPABILITIES.notes
        assert "hudi-spark-bundle" in HUDI_CAPABILITIES.notes


class TestHudiMaintenanceOperationsInit:
    """Tests for HudiMaintenanceOperations initialization."""

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_init_requires_spark_session(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        with pytest.raises(ValueError, match="spark_session is required"):
            HudiMaintenanceOperations(spark_session=None)

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_init_with_mock_spark(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)

        ops = HudiMaintenanceOperations(
            spark_session=mock_spark,
            record_key="order_key",
            precombine_field="order_date",
            table_type="COPY_ON_WRITE",
        )

        assert ops.spark is mock_spark
        assert ops.record_key == "order_key"
        assert ops.precombine_field == "order_date"
        assert ops.table_type == "COPY_ON_WRITE"

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_init_with_merge_on_read_table_type(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)

        ops = HudiMaintenanceOperations(
            spark_session=mock_spark,
            table_type="MERGE_ON_READ",
        )

        assert ops.table_type == "MERGE_ON_READ"

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_capabilities(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        caps = ops.get_capabilities()

        assert caps.platform_name == "hudi"
        assert caps.supports_insert is True
        assert caps.supports_delete is True
        assert caps.supports_update is True
        assert caps.supports_merge is True


class TestHudiTableIdentifierNormalization:
    """Tests for table identifier normalization."""

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_normalize_catalog_path(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        # Catalog paths should be preserved
        result = ops._normalize_table_identifier("database.table_name")
        assert result == "database.table_name"

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_normalize_s3_path(self):
        """Test normalization of S3 paths."""
        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        # S3 paths should get backtick quoting
        result = ops._normalize_table_identifier("s3://bucket/path/table")
        assert "`hudi`" in result
        assert "s3://bucket/path/table" in result

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_normalize_local_path(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        # Local paths should get backtick quoting
        result = ops._normalize_table_identifier("/data/hudi/table")
        assert "`hudi`" in result
        assert "/data/hudi/table" in result


class TestHudiInsertOperations:
    """Tests for Hudi INSERT operations."""

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_insert_creates_temp_view(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        mock_df = MagicMock()
        mock_df.count.return_value = 3

        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        # Mock _convert_to_spark_df to return our mock DataFrame
        with patch.object(ops, "_convert_to_spark_df", return_value=mock_df):
            result = ops.insert_rows(
                table_path="test_db.test_table",
                dataframe={"data": "test"},
                mode="append",
            )

        assert result.success is True
        assert result.rows_affected == 3

        # Verify temp view was created and cleaned up
        mock_df.createOrReplaceTempView.assert_called_once()
        mock_spark.catalog.dropTempView.assert_called_once()

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_insert_overwrite_mode(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        mock_df = MagicMock()
        mock_df.count.return_value = 5

        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        with patch.object(ops, "_convert_to_spark_df", return_value=mock_df):
            result = ops.insert_rows(
                table_path="test_db.test_table",
                dataframe={"data": "test"},
                mode="overwrite",
            )

        assert result.success is True

        # Verify INSERT OVERWRITE was used
        sql_calls = [str(call) for call in mock_spark.sql.call_args_list]
        assert any("INSERT OVERWRITE" in str(call) for call in sql_calls)

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_insert_empty_dataframe(self):
        """Test inserting empty dataframe returns 0 rows."""
        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        mock_df = MagicMock()
        mock_df.count.return_value = 0

        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        with patch.object(ops, "_convert_to_spark_df", return_value=mock_df):
            result = ops.insert_rows(
                table_path="test_db.test_table",
                dataframe={"data": "test"},
                mode="append",
            )

        assert result.success is True
        assert result.rows_affected == 0

        # Verify no SQL was executed
        mock_spark.sql.assert_not_called()


class TestHudiDeleteOperations:
    """Tests for Hudi DELETE operations."""

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_delete_with_condition(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        # Mock count before and after
        mock_spark.sql.return_value.collect.side_effect = [
            [{"cnt": 10}],  # count before
            [{"cnt": 7}],  # count after
        ]

        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        result = ops.delete_rows(
            table_path="test_db.test_table",
            condition="order_date < '2020-01-01'",
        )

        assert result.success is True
        assert result.rows_affected == 3  # 10 - 7

        # Verify DELETE FROM was called
        sql_calls = [str(call) for call in mock_spark.sql.call_args_list]
        assert any("DELETE FROM" in str(call) for call in sql_calls)
        assert any("order_date < '2020-01-01'" in str(call) for call in sql_calls)

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_delete_no_matches(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        # Same count before and after
        mock_spark.sql.return_value.collect.side_effect = [
            [{"cnt": 10}],  # count before
            [{"cnt": 10}],  # count after (no change)
        ]

        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        result = ops.delete_rows(
            table_path="test_db.test_table",
            condition="id > 9999",
        )

        assert result.success is True
        assert result.rows_affected == 0


class TestHudiUpdateOperations:
    """Tests for Hudi UPDATE operations."""

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_update_rows(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        # Mock matching count
        mock_spark.sql.return_value.collect.return_value = [{"cnt": 5}]

        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        result = ops.update_rows(
            table_path="test_db.test_table",
            condition="status = 'pending'",
            updates={"status": "'completed'", "updated_at": "current_timestamp()"},
        )

        assert result.success is True
        assert result.rows_affected == 5

        # Verify UPDATE was called with correct SET clause
        sql_calls = [str(call) for call in mock_spark.sql.call_args_list]
        assert any("UPDATE" in str(call) for call in sql_calls)
        assert any("SET" in str(call) for call in sql_calls)

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_update_no_matches(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        mock_spark.sql.return_value.collect.return_value = [{"cnt": 0}]

        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        result = ops.update_rows(
            table_path="test_db.test_table",
            condition="id = -1",
            updates={"status": "'updated'"},
        )

        assert result.success is True
        assert result.rows_affected == 0


class TestHudiMergeOperations:
    """Tests for Hudi MERGE operations."""

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_merge_upsert(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        mock_source_df = MagicMock()
        mock_source_df.count.return_value = 10

        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        with patch.object(ops, "_convert_to_spark_df", return_value=mock_source_df):
            result = ops.merge_rows(
                table_path="test_db.test_table",
                source_dataframe={"data": "test"},
                merge_condition="target.id = source.id",
                when_matched={"name": "source.name", "value": "source.value"},
                when_not_matched={"id": "source.id", "name": "source.name"},
            )

        assert result.success is True
        assert result.rows_affected == 10

        # Verify MERGE INTO was called
        sql_calls = [str(call) for call in mock_spark.sql.call_args_list]
        assert any("MERGE INTO" in str(call) for call in sql_calls)
        assert any("WHEN MATCHED" in str(call) for call in sql_calls)
        assert any("WHEN NOT MATCHED" in str(call) for call in sql_calls)

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_merge_creates_and_cleans_temp_view(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        mock_source_df = MagicMock()
        mock_source_df.count.return_value = 5

        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        with patch.object(ops, "_convert_to_spark_df", return_value=mock_source_df):
            ops.merge_rows(
                table_path="test_db.test_table",
                source_dataframe={"data": "test"},
                merge_condition="target.id = source.id",
                when_matched={"value": "source.value"},
            )

        # Verify temp view was created and cleaned up
        mock_source_df.createOrReplaceTempView.assert_called_once()
        mock_spark.catalog.dropTempView.assert_called_once()


class TestHudiDataFrameConversion:
    """Tests for DataFrame type conversion in Hudi."""

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_convert_spark_dataframe_passthrough(self):

        from pyspark.sql import DataFrame as SparkDataFrame

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        mock_df = MagicMock(spec=SparkDataFrame)

        ops = HudiMaintenanceOperations(spark_session=mock_spark)
        result = ops._convert_to_spark_df(mock_df)

        assert result is mock_df

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_convert_pandas_dataframe(self):

        pytest.importorskip("pandas")
        import pandas as pd

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        mock_spark_df = MagicMock()
        mock_spark.createDataFrame.return_value = mock_spark_df

        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        df = pd.DataFrame({"id": [1, 2, 3], "name": ["A", "B", "C"]})
        result = ops._convert_to_spark_df(df)

        mock_spark.createDataFrame.assert_called_once()
        assert result is mock_spark_df

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_convert_polars_dataframe(self):

        pytest.importorskip("polars")
        pytest.importorskip("pandas")
        import polars as pl

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        mock_spark_df = MagicMock()
        mock_spark.createDataFrame.return_value = mock_spark_df

        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        df = pl.DataFrame({"id": [1, 2, 3], "name": ["A", "B", "C"]})
        result = ops._convert_to_spark_df(df)

        mock_spark.createDataFrame.assert_called_once()
        assert result is mock_spark_df

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_convert_pyarrow_table(self):

        pytest.importorskip("pyarrow")
        pytest.importorskip("pandas")
        import pyarrow as pa

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        mock_spark_df = MagicMock()
        mock_spark.createDataFrame.return_value = mock_spark_df

        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        table = pa.table({"id": [1, 2, 3], "name": ["A", "B", "C"]})
        result = ops._convert_to_spark_df(table)

        mock_spark.createDataFrame.assert_called_once()
        assert result is mock_spark_df

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_convert_list_of_dicts(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        mock_spark_df = MagicMock()
        mock_spark.createDataFrame.return_value = mock_spark_df

        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        data = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
        result = ops._convert_to_spark_df(data)

        mock_spark.createDataFrame.assert_called_once_with(data)
        assert result is mock_spark_df

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_convert_unsupported_type_raises_error(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        with pytest.raises(TypeError, match="Unsupported DataFrame type"):
            ops._convert_to_spark_df("not a dataframe")


class TestHudiMaintenanceResultTiming:
    """Tests for result timing in Hudi operations."""

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_result_includes_timing(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        mock_df = MagicMock()
        mock_df.count.return_value = 3

        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        with patch.object(ops, "_convert_to_spark_df", return_value=mock_df):
            result = ops.insert_rows(
                table_path="test_db.test_table",
                dataframe={"data": "test"},
                mode="append",
            )

        assert result.duration is not None
        assert result.duration >= 0
        # Use <= because mocked operations can complete within the same clock tick
        # (Windows time.time() has ~15ms resolution)
        assert result.start_time <= result.end_time


class TestGetHudiMaintenanceOperations:
    """Tests for the factory function."""

    def test_factory_returns_none_without_spark(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            get_hudi_maintenance_operations,
        )

        result = get_hudi_maintenance_operations(spark_session=None)
        assert result is None

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_factory_returns_operations_with_spark(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
            get_hudi_maintenance_operations,
        )

        mock_spark = MagicMock(spec=SparkSession)

        result = get_hudi_maintenance_operations(
            spark_session=mock_spark,
            record_key="id",
            precombine_field="ts",
            table_type="MERGE_ON_READ",
        )

        assert result is not None
        assert isinstance(result, HudiMaintenanceOperations)
        assert result.record_key == "id"
        assert result.precombine_field == "ts"
        assert result.table_type == "MERGE_ON_READ"


class TestHudiWorkingDirectory:
    """Tests for working directory configuration."""

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_init_with_working_dir(self, tmp_path):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        working_dir = tmp_path / "hudi_work"

        ops = HudiMaintenanceOperations(
            spark_session=mock_spark,
            working_dir=str(working_dir),
        )

        assert ops.working_dir is not None
        assert str(ops.working_dir) == str(working_dir)

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_init_with_path_working_dir(self, tmp_path):

        from pathlib import Path

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        working_dir = tmp_path / "hudi_work"

        ops = HudiMaintenanceOperations(
            spark_session=mock_spark,
            working_dir=working_dir,
        )

        assert ops.working_dir == working_dir


class TestHudiGCSPathNormalization:
    """Tests for GCS path normalization."""

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_normalize_gcs_path(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        # GCS paths should get backtick quoting
        result = ops._normalize_table_identifier("gs://bucket/path/table")
        assert "`hudi`" in result
        assert "gs://bucket/path/table" in result


class TestHudiMergeOperationsExtended:
    """Extended tests for Hudi MERGE operations."""

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_merge_with_only_when_matched(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        mock_source_df = MagicMock()
        mock_source_df.count.return_value = 5

        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        with patch.object(ops, "_convert_to_spark_df", return_value=mock_source_df):
            result = ops.merge_rows(
                table_path="test_db.test_table",
                source_dataframe={"data": "test"},
                merge_condition="target.id = source.id",
                when_matched={"status": "source.status"},
                when_not_matched=None,
            )

        assert result.success is True

        # Verify MERGE INTO was called with WHEN MATCHED but not WHEN NOT MATCHED
        sql_calls = [str(call) for call in mock_spark.sql.call_args_list]
        assert any("MERGE INTO" in str(call) for call in sql_calls)
        assert any("WHEN MATCHED" in str(call) for call in sql_calls)

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_merge_with_only_when_not_matched(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        mock_source_df = MagicMock()
        mock_source_df.count.return_value = 3

        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        with patch.object(ops, "_convert_to_spark_df", return_value=mock_source_df):
            result = ops.merge_rows(
                table_path="test_db.test_table",
                source_dataframe={"data": "test"},
                merge_condition="target.id = source.id",
                when_matched=None,
                when_not_matched={"id": "source.id", "name": "source.name"},
            )

        assert result.success is True

        # Verify MERGE INTO was called with WHEN NOT MATCHED
        sql_calls = [str(call) for call in mock_spark.sql.call_args_list]
        assert any("MERGE INTO" in str(call) for call in sql_calls)


class TestHudiPySparkAvailability:
    """Tests for PySpark availability checking."""

    def test_pyspark_available_constant(self):

        from benchbox.platforms.dataframe.hudi_maintenance import PYSPARK_AVAILABLE

        # Just verify it's a boolean
        assert isinstance(PYSPARK_AVAILABLE, bool)

    def test_module_exports(self):

        from benchbox.platforms.dataframe import hudi_maintenance

        assert "HudiMaintenanceOperations" in hudi_maintenance.__all__
        assert "get_hudi_maintenance_operations" in hudi_maintenance.__all__
        assert "PYSPARK_AVAILABLE" in hudi_maintenance.__all__


class TestHudiInsertWithPartitions:
    """Tests for INSERT with partition columns."""

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
    def test_insert_with_partition_columns(self):

        from benchbox.platforms.dataframe.hudi_maintenance import (
            HudiMaintenanceOperations,
        )

        mock_spark = MagicMock(spec=SparkSession)
        mock_df = MagicMock()
        mock_df.count.return_value = 10

        ops = HudiMaintenanceOperations(spark_session=mock_spark)

        with patch.object(ops, "_convert_to_spark_df", return_value=mock_df):
            result = ops.insert_rows(
                table_path="test_db.test_table",
                dataframe={"data": "test"},
                partition_columns=["year", "month"],
                mode="append",
            )

        assert result.success is True
        assert result.rows_affected == 10
