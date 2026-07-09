"""Tests for DataFrame write operations in Write Primitives benchmark.

Copyright 2026 Joe Harris / BenchBox Project
"""

import shutil
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


try:
    import polars as pl

    POLARS_AVAILABLE = True
except ImportError:
    POLARS_AVAILABLE = False
    pl = None

try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    pd = None

try:
    from benchbox.platforms.dataframe.pyspark_maintenance import (
        DELTA_SPARK_AVAILABLE,
        PYSPARK_AVAILABLE,
        PYSPARK_DELTA_CAPABILITIES,
        PYSPARK_PARQUET_CAPABILITIES,
        PySparkMaintenanceOperations,
        get_pyspark_maintenance_operations,
    )

    PYSPARK_MAINTENANCE_AVAILABLE = True
    PYSPARK_MAINTENANCE_IMPORT_ERROR = ""
except ImportError as exc:
    # PySpark is a core (non-optional) dependency, so this ImportError normally
    # only fires on developer machines without it installed - but it also fires
    # if the wrapper module itself becomes genuinely broken (moved/renamed
    # symbol, typo). A single module-level guard (rather than 12 duplicated
    # in-body try/except sites) makes the skip reason carry the real
    # ImportError text instead of a generic static string, so a real breakage
    # is visible in the skip reason even though it still (by design) skips
    # rather than errors on machines without PySpark.
    PYSPARK_MAINTENANCE_AVAILABLE = False
    PYSPARK_MAINTENANCE_IMPORT_ERROR = str(exc)
    DELTA_SPARK_AVAILABLE = False
    PYSPARK_AVAILABLE = False
    PYSPARK_DELTA_CAPABILITIES = None
    PYSPARK_PARQUET_CAPABILITIES = None
    PySparkMaintenanceOperations = None
    get_pyspark_maintenance_operations = None

pyspark_maintenance_skip = pytest.mark.skipif(
    not PYSPARK_MAINTENANCE_AVAILABLE,
    reason=f"PySpark maintenance module not available: {PYSPARK_MAINTENANCE_IMPORT_ERROR}",
)

from benchbox.core.write_primitives import (
    DataFrameWriteCapabilities,
    DataFrameWriteOperationsManager,
    DataFrameWriteResult,
    WriteOperationType,
    WritePrimitivesBenchmark,
    get_dataframe_write_manager,
)


class TestWritePrimitivesBenchmarkDataFrameSupport:
    """Test DataFrame mode support in WritePrimitivesBenchmark."""

    def test_supports_dataframe_mode(self):
        """Test that WritePrimitivesBenchmark reports DataFrame support."""
        benchmark = WritePrimitivesBenchmark()
        assert benchmark.supports_dataframe_mode() is True
        assert benchmark.skip_dataframe_data_loading() is True

    def test_get_dataframe_operations_polars(self):
        """Test getting DataFrame operations for Polars."""
        benchmark = WritePrimitivesBenchmark()
        manager = benchmark.get_dataframe_operations("polars-df")

        if POLARS_AVAILABLE:
            assert manager is not None
            assert isinstance(manager, DataFrameWriteOperationsManager)
        else:
            # Manager created but operations may be limited
            assert manager is not None

    def test_get_dataframe_operations_unknown_platform(self):
        """Test that unknown platform returns None."""
        benchmark = WritePrimitivesBenchmark()
        manager = benchmark.get_dataframe_operations("sqlite")
        assert manager is None

    def test_get_dataframe_capabilities(self):
        """Test getting DataFrame capabilities."""
        benchmark = WritePrimitivesBenchmark()
        caps = benchmark.get_dataframe_capabilities("polars-df")

        if POLARS_AVAILABLE:
            assert caps is not None
            assert isinstance(caps, DataFrameWriteCapabilities)
            assert caps.platform_name == "polars-df"

    def test_execute_dataframe_workload_delegates_to_sql_parity_path(self, monkeypatch):
        """DataFrame workload should delegate to SQL-parity operation execution."""
        benchmark = WritePrimitivesBenchmark()
        parity_rows = [
            {"query_id": "insert_single_row", "status": "SUCCESS", "execution_time": 0.001, "rows_returned": 1}
        ]

        monkeypatch.setattr(
            benchmark,
            "_execute_dataframe_sql_parity_workload",
            lambda **_kwargs: parity_rows,
        )

        class DummyAdapter:
            platform_name = "polars-df"

        results = benchmark.execute_dataframe_workload(
            ctx=None,
            adapter=DummyAdapter(),
            benchmark_config=None,
            query_filter={"INSERT_SINGLE_ROW"},
            monitor=None,
            run_options=None,
        )

        assert len(results) == 4
        assert results[0]["run_type"] == "warmup"
        assert results[0]["iteration"] == 0
        assert results[1]["run_type"] == "measurement"
        assert results[1]["iteration"] == 1
        assert results[3]["iteration"] == 3
        assert all(r["query_id"] == "insert_single_row" for r in results)


class TestWriteOperationType:
    """Tests for WriteOperationType enum."""

    def test_all_operation_types(self):
        """Test all operation type values."""
        assert WriteOperationType.INSERT.value == "insert"
        assert WriteOperationType.UPDATE.value == "update"
        assert WriteOperationType.DELETE.value == "delete"
        assert WriteOperationType.MERGE.value == "merge"
        assert WriteOperationType.BULK_LOAD.value == "bulk_load"
        assert WriteOperationType.TRANSACTION.value == "transaction"


class TestDataFrameWriteCapabilities:
    """Tests for DataFrameWriteCapabilities."""

    def test_supports_operation_bulk_load(self):
        """Test BULK_LOAD capability check."""
        caps = DataFrameWriteCapabilities(
            platform_name="test",
            supports_bulk_load=True,
        )
        assert caps.supports_operation(WriteOperationType.BULK_LOAD) is True

        caps_no = DataFrameWriteCapabilities(
            platform_name="test",
            supports_bulk_load=False,
        )
        assert caps_no.supports_operation(WriteOperationType.BULK_LOAD) is False

    def test_supports_operation_without_maintenance_caps(self):
        """Test operations without maintenance capabilities."""
        caps = DataFrameWriteCapabilities(
            platform_name="test",
            maintenance_caps=None,
        )
        # INSERT, UPDATE, DELETE, MERGE should be False without maintenance caps
        assert caps.supports_operation(WriteOperationType.INSERT) is False
        assert caps.supports_operation(WriteOperationType.UPDATE) is False
        assert caps.supports_operation(WriteOperationType.DELETE) is False
        assert caps.supports_operation(WriteOperationType.MERGE) is False

    def test_get_unsupported_operations(self):
        """Test getting list of unsupported operations."""
        caps = DataFrameWriteCapabilities(
            platform_name="test",
            maintenance_caps=None,  # No row-level operations
            supports_bulk_load=True,
        )
        unsupported = caps.get_unsupported_operations()

        # Should include row-level ops but not BULK_LOAD
        assert WriteOperationType.INSERT in unsupported
        assert WriteOperationType.UPDATE in unsupported
        assert WriteOperationType.BULK_LOAD not in unsupported


class TestDataFrameWriteResult:
    """Tests for DataFrameWriteResult."""

    def test_failure_factory(self):
        """Test creating a failure result."""
        result = DataFrameWriteResult.failure(
            WriteOperationType.INSERT,
            "Table not found",
        )

        assert result.success is False
        assert result.rows_affected == 0
        assert result.error_message == "Table not found"
        assert result.operation_type == WriteOperationType.INSERT
        assert result.validation_passed is False

    def test_failure_with_start_time(self):
        """Test failure factory with explicit start time."""
        import time

        start = time.time() - 2.0  # 2 seconds ago
        result = DataFrameWriteResult.failure(
            WriteOperationType.UPDATE,
            "Constraint violation",
            start_time=start,
        )

        assert result.success is False
        assert result.start_time == start
        assert result.duration_ms >= 2000  # At least 2 seconds in ms


class TestGetDataFrameWriteManager:
    """Tests for get_dataframe_write_manager function."""

    def test_polars_manager(self):
        """Test getting Polars manager."""
        manager = get_dataframe_write_manager("polars-df")
        if POLARS_AVAILABLE:
            assert manager is not None
            assert "polars" in manager.platform_name
        else:
            # Manager should still be created for capability checking
            assert manager is not None

    def test_pandas_manager(self):
        """Test getting Pandas manager."""
        manager = get_dataframe_write_manager("pandas-df")
        if PANDAS_AVAILABLE:
            assert manager is not None
            assert "pandas" in manager.platform_name

    def test_unknown_platform_returns_none(self):
        """Test that non-DataFrame platforms return None."""
        manager = get_dataframe_write_manager("duckdb")
        assert manager is None

        manager = get_dataframe_write_manager("sqlite")
        assert manager is None

    def test_case_insensitive(self):
        """Test platform name is case-insensitive."""
        manager1 = get_dataframe_write_manager("Polars-DF")
        manager2 = get_dataframe_write_manager("POLARS-DF")
        # Both should return managers (or both None if Polars not installed)
        assert (manager1 is None) == (manager2 is None)


@pytest.mark.skipif(not POLARS_AVAILABLE, reason="Polars not installed")
class TestPolarsWriteOperations:
    """Tests for Polars write operations."""

    @pytest.fixture
    def temp_table_dir(self, tmp_path: Path) -> Path:
        """Create a temporary directory for test tables."""
        table_dir = tmp_path / "test_table"
        table_dir.mkdir()
        return table_dir

    @pytest.fixture
    def sample_df(self):
        """Create a sample Polars DataFrame."""
        return pl.DataFrame(
            {
                "id": [1, 2, 3, 4, 5],
                "name": ["Alice", "Bob", "Charlie", "Diana", "Eve"],
                "amount": [100.0, 200.0, 150.0, 300.0, 250.0],
                "region": ["US", "EU", "US", "EU", "APAC"],
            }
        )

    @pytest.fixture
    def existing_table(self, temp_table_dir: Path, sample_df):
        """Create a table with existing data."""
        sample_df.write_parquet(temp_table_dir / "part-00000.parquet")
        return temp_table_dir

    @pytest.fixture
    def manager(self):
        """Get Polars write operations manager."""
        return get_dataframe_write_manager("polars-df")

    def test_polars_capabilities(self, manager):
        """Test Polars capabilities are correctly set."""
        caps = manager.get_capabilities()

        assert caps.platform_name == "polars-df"
        # Polars supports all operations via read-modify-write
        assert caps.supports_operation(WriteOperationType.INSERT) is True
        assert caps.supports_operation(WriteOperationType.UPDATE) is True
        assert caps.supports_operation(WriteOperationType.DELETE) is True
        assert caps.supports_operation(WriteOperationType.MERGE) is True
        assert caps.supports_operation(WriteOperationType.BULK_LOAD) is True
        # Polars doesn't have transactions
        assert caps.supports_operation(WriteOperationType.TRANSACTION) is False

    def test_insert_new_rows(self, manager, temp_table_dir: Path, sample_df):
        """Test INSERT operation."""
        result = manager.execute_insert(temp_table_dir, sample_df, mode="append")

        assert result.success is True
        assert result.rows_affected == 5
        assert result.operation_type == WriteOperationType.INSERT

        # Verify data was written
        written = pl.read_parquet(temp_table_dir / "part-00000.parquet")
        assert written.height == 5

    def test_insert_append_mode(self, manager, existing_table: Path, sample_df):
        """Test appending rows to existing table."""
        new_df = pl.DataFrame(
            {"id": [6, 7], "name": ["Frank", "Grace"], "amount": [400.0, 500.0], "region": ["US", "EU"]}
        )

        result = manager.execute_insert(existing_table, new_df, mode="append")

        assert result.success is True
        assert result.rows_affected == 2

        # Verify total row count
        all_data = pl.read_parquet(existing_table / "*.parquet")
        assert all_data.height == 7

    def test_update_rows(self, manager, existing_table: Path):
        """Test UPDATE operation."""
        result = manager.execute_update(
            existing_table,
            "region = 'EU'",
            {"amount": "0"},
        )

        assert result.success is True
        assert result.rows_affected == 2  # Bob and Diana

        # Verify the update
        df = pl.read_parquet(existing_table / "*.parquet")
        eu_rows = df.filter(pl.col("region") == "EU")
        assert eu_rows["amount"].to_list() == [0, 0]

    def test_delete_rows(self, manager, existing_table: Path):
        """Test DELETE operation."""
        result = manager.execute_delete(existing_table, "amount > 200")

        assert result.success is True
        assert result.rows_affected == 2  # Diana (300) and Eve (250)

        # Verify remaining data
        remaining = pl.read_parquet(existing_table / "*.parquet")
        assert remaining.height == 3

    def test_merge_rows(self, manager, existing_table: Path):
        """Test MERGE (upsert) operation."""
        # Source: id=1 exists (update), id=100 is new (insert)
        source_df = pl.DataFrame(
            {
                "id": [1, 100],
                "name": ["Alice Updated", "NewPerson"],
                "amount": [111.0, 100.0],
                "region": ["US", "EU"],
            }
        )

        result = manager.execute_merge(
            existing_table,
            source_df,
            merge_condition="id",
            when_matched={"name": "source.name"},
            when_not_matched={"id": "source.id", "name": "source.name"},
        )

        assert result.success is True
        assert result.rows_affected == 2  # 1 updated + 1 inserted

        # Verify
        df = pl.read_parquet(existing_table / "*.parquet")
        assert df.height == 6  # 5 original + 1 new

        alice = df.filter(pl.col("id") == 1)
        assert alice["name"][0] == "Alice Updated"


@pytest.mark.skipif(not POLARS_AVAILABLE, reason="Polars not installed")
class TestPolarsBulkLoad:
    """Tests for Polars BULK_LOAD operations."""

    @pytest.fixture
    def source_csv(self, tmp_path: Path) -> Path:
        """Create a source CSV file."""
        csv_path = tmp_path / "source.csv"
        df = pl.DataFrame(
            {
                "id": [1, 2, 3],
                "value": ["a", "b", "c"],
            }
        )
        df.write_csv(csv_path)
        return csv_path

    @pytest.fixture
    def source_parquet(self, tmp_path: Path) -> Path:
        """Create a source Parquet file."""
        parquet_path = tmp_path / "source.parquet"
        df = pl.DataFrame(
            {
                "id": [1, 2, 3, 4, 5],
                "name": ["Alice", "Bob", "Charlie", "Diana", "Eve"],
                "amount": [100.0, 200.0, 150.0, 300.0, 250.0],
            }
        )
        df.write_parquet(parquet_path)
        return parquet_path

    @pytest.fixture
    def manager(self):
        """Get Polars write operations manager."""
        return get_dataframe_write_manager("polars-df")

    def test_bulk_load_csv(self, manager, source_csv: Path, tmp_path: Path):
        """Test loading from CSV."""
        target_path = tmp_path / "target_table"

        result = manager.execute_bulk_load(
            source_path=source_csv,
            target_path=target_path,
            source_format="csv",
            target_format="parquet",
            compression="zstd",
        )

        assert result.success is True
        assert result.rows_affected == 3
        assert result.compression == "zstd"
        assert result.file_count == 1
        assert result.bytes_written is not None
        assert result.bytes_written > 0

        # Verify data
        loaded = pl.read_parquet(target_path / "*.parquet")
        assert loaded.height == 3

    def test_bulk_load_parquet(self, manager, source_parquet: Path, tmp_path: Path):
        """Test loading from Parquet."""
        target_path = tmp_path / "target_table"

        result = manager.execute_bulk_load(
            source_path=source_parquet,
            target_path=target_path,
            source_format="parquet",
            target_format="parquet",
            compression="snappy",
        )

        assert result.success is True
        assert result.rows_affected == 5
        assert result.compression == "snappy"

    def test_bulk_load_with_sorting(self, manager, source_parquet: Path, tmp_path: Path):
        """Test bulk load with sorting."""
        target_path = tmp_path / "target_table"

        result = manager.execute_bulk_load(
            source_path=source_parquet,
            target_path=target_path,
            source_format="parquet",
            sort_columns=["amount"],
        )

        assert result.success is True

        # Verify data is sorted
        loaded = pl.read_parquet(target_path / "*.parquet")
        amounts = loaded["amount"].to_list()
        assert amounts == sorted(amounts)

    def test_bulk_load_with_partitioning(self, manager, tmp_path: Path):
        """Test bulk load with partitioning."""
        # Create source with partition column
        source_path = tmp_path / "source.parquet"
        df = pl.DataFrame(
            {
                "id": [1, 2, 3, 4],
                "region": ["US", "US", "EU", "EU"],
                "value": [10, 20, 30, 40],
            }
        )
        df.write_parquet(source_path)

        target_path = tmp_path / "target_table"

        result = manager.execute_bulk_load(
            source_path=source_path,
            target_path=target_path,
            source_format="parquet",
            partition_columns=["region"],
        )

        assert result.success is True
        assert result.rows_affected == 4
        assert result.file_count == 2  # One per region

        # Verify partition directories
        assert (target_path / "region=US").exists()
        assert (target_path / "region=EU").exists()


@pytest.mark.skipif(not PANDAS_AVAILABLE, reason="Pandas not installed")
class TestPandasWriteOperations:
    """Tests for Pandas write operations (limited to file-level ops)."""

    @pytest.fixture
    def manager(self):
        """Get Pandas write operations manager."""
        return get_dataframe_write_manager("pandas-df")

    def test_pandas_capabilities(self, manager):
        """Test Pandas capabilities are correctly limited."""
        caps = manager.get_capabilities()

        assert caps.platform_name == "pandas-df"
        # Pandas only supports file-level operations
        assert caps.supports_operation(WriteOperationType.BULK_LOAD) is True
        # Row-level operations not supported (no maintenance ops)
        assert caps.supports_operation(WriteOperationType.UPDATE) is False
        assert caps.supports_operation(WriteOperationType.DELETE) is False
        assert caps.supports_operation(WriteOperationType.MERGE) is False

    def test_unsupported_operation_message(self, manager):
        """Test helpful error message for unsupported operations."""
        result = manager.execute_update(
            "/some/path",
            "id = 1",
            {"name": "'Updated'"},
        )

        assert result.success is False
        assert "polars-df" in result.error_message.lower() or "pyspark-df" in result.error_message.lower()

    def test_bulk_load_parquet(self, manager, tmp_path: Path):
        """Test Pandas bulk load from Parquet."""
        # Create source
        source_path = tmp_path / "source.parquet"
        df = pd.DataFrame(
            {
                "id": [1, 2, 3],
                "name": ["A", "B", "C"],
            }
        )
        df.to_parquet(source_path, index=False)

        target_path = tmp_path / "target_table"

        result = manager.execute_bulk_load(
            source_path=source_path,
            target_path=target_path,
            source_format="parquet",
        )

        assert result.success is True
        assert result.rows_affected == 3


# =============================================================================
# PySpark Tests
# =============================================================================


@pyspark_maintenance_skip
class TestPySparkCapabilities:
    """Test PySpark capability profiles for Delta vs Parquet."""

    def test_delta_capabilities_full_acid(self):
        """Test that Delta capabilities declare full ACID support."""
        caps = PYSPARK_DELTA_CAPABILITIES

        assert caps.platform_name == "pyspark-delta"
        assert caps.supports_insert is True
        assert caps.supports_delete is True
        assert caps.supports_update is True
        assert caps.supports_merge is True
        assert caps.supports_transactions is True
        assert caps.supports_row_level_delete is True
        assert caps.supports_time_travel is True

    def test_parquet_capabilities_limited(self):
        """Test that Parquet capabilities only support INSERT/BULK_LOAD."""
        caps = PYSPARK_PARQUET_CAPABILITIES

        assert caps.platform_name == "pyspark-parquet"
        assert caps.supports_insert is True
        # Row-level operations NOT supported for plain Parquet
        assert caps.supports_delete is False
        assert caps.supports_update is False
        assert caps.supports_merge is False
        assert caps.supports_transactions is False
        assert caps.supports_row_level_delete is False


@pyspark_maintenance_skip
class TestPySparkMaintenanceInit:
    """Test PySparkMaintenanceOperations initialization."""

    def test_requires_spark_session(self):
        """Test that None spark_session raises ValueError."""
        with pytest.raises(ValueError, match="spark_session is required"):
            PySparkMaintenanceOperations(spark_session=None)

    def test_factory_returns_none_without_session(self):
        """Test that factory function returns None without SparkSession."""
        result = get_pyspark_maintenance_operations(spark_session=None)
        assert result is None


@pyspark_maintenance_skip
class TestPySparkInsertWithMock:
    """Test PySpark INSERT operations verify DataFrame API is used (not SQL)."""

    def test_insert_uses_dataframe_write_api(self):
        """Verify INSERT uses df.write.mode().format().save(), not spark.sql()."""
        if not PYSPARK_AVAILABLE:
            pytest.skip("PySpark not installed")

        from unittest.mock import MagicMock, patch

        # Create mock SparkSession and DataFrame
        mock_spark = MagicMock()
        mock_df = MagicMock()
        mock_df.count.return_value = 5

        # Mock the write chain
        mock_writer = MagicMock()
        mock_df.write = mock_writer
        mock_writer.mode.return_value = mock_writer
        mock_writer.partitionBy.return_value = mock_writer
        mock_writer.format.return_value = mock_writer

        ops = PySparkMaintenanceOperations(spark_session=mock_spark, prefer_delta=False)

        # Execute insert
        with patch.object(ops, "_convert_to_spark_df", return_value=mock_df):
            with patch.object(ops, "is_delta_table", return_value=False):
                result = ops._do_insert(
                    table_path="/tmp/test_table",
                    dataframe=mock_df,
                    partition_columns=None,
                    mode="append",
                )

        # Verify DataFrame write API was used (NOT spark.sql())
        mock_writer.mode.assert_called_once_with("append")
        mock_writer.parquet.assert_called_once_with("/tmp/test_table")

        # Verify spark.sql() was NOT called
        mock_spark.sql.assert_not_called()

        assert result == 5


@pyspark_maintenance_skip
class TestPySparkBulkLoadWithMock:
    """Test PySpark BULK_LOAD uses spark.read().write() pattern."""

    def test_bulk_load_uses_read_write_pattern(self):
        """Verify BULK_LOAD uses spark.read.format().load() then df.write."""
        if not PYSPARK_AVAILABLE:
            pytest.skip("PySpark not installed")

        from unittest.mock import MagicMock

        # Create mock SparkSession
        mock_spark = MagicMock()

        # Mock the read chain
        mock_reader = MagicMock()
        mock_spark.read = mock_reader
        mock_reader.format.return_value = mock_reader
        mock_reader.option.return_value = mock_reader

        # Mock DataFrame returned from load
        mock_df = MagicMock()
        mock_df.count.return_value = 100
        mock_reader.load.return_value = mock_df

        # Mock the write chain
        mock_writer = MagicMock()
        mock_df.write = mock_writer
        mock_writer.mode.return_value = mock_writer
        mock_writer.partitionBy.return_value = mock_writer
        mock_writer.option.return_value = mock_writer
        mock_writer.format.return_value = mock_writer

        ops = PySparkMaintenanceOperations(spark_session=mock_spark)

        # Execute bulk load
        result = ops.execute_bulk_load(
            source_path="/tmp/source.parquet",
            target_path="/tmp/target",
            source_format="parquet",
            target_format="parquet",
            compression="zstd",
            sort_columns=None,
        )

        # Verify read chain: spark.read.format("parquet").load(path)
        mock_reader.format.assert_called_with("parquet")
        mock_reader.load.assert_called_once_with("/tmp/source.parquet")

        # Verify write chain: df.write.mode().option().parquet()
        mock_writer.mode.assert_called_once_with("overwrite")
        mock_writer.option.assert_called_with("compression", "zstd")

        # Verify spark.sql() was NOT called
        mock_spark.sql.assert_not_called()

        assert result == 100


@pyspark_maintenance_skip
class TestPySparkDeltaOperationsWithMock:
    """Test PySpark Delta Lake operations use DeltaTable API."""

    def test_delete_uses_delta_table_api(self):
        """Verify DELETE uses DeltaTable.forPath().delete(), not spark.sql()."""
        if not PYSPARK_AVAILABLE:
            pytest.skip("PySpark not installed")

        if not DELTA_SPARK_AVAILABLE:
            pytest.skip("delta-spark not installed")

        from unittest.mock import MagicMock, patch

        mock_spark = MagicMock()
        mock_delta_table = MagicMock()

        # Mock toDF() for row counting
        mock_df_before = MagicMock()
        mock_df_before.count.return_value = 100
        mock_df_after = MagicMock()
        mock_df_after.count.return_value = 90
        mock_delta_table.toDF.side_effect = [mock_df_before, mock_df_after]

        ops = PySparkMaintenanceOperations(spark_session=mock_spark, prefer_delta=True)

        with patch("benchbox.platforms.dataframe.pyspark_maintenance.DeltaTable") as MockDeltaTable:
            MockDeltaTable.forPath.return_value = mock_delta_table

            with patch.object(ops, "is_delta_table", return_value=True):
                result = ops._do_delete(
                    table_path="/tmp/delta_table",
                    condition="id > 100",
                )

        # Verify DeltaTable.forPath() was called
        MockDeltaTable.forPath.assert_called_once_with(mock_spark, "/tmp/delta_table")

        # Verify DeltaTable.delete() was called with condition
        mock_delta_table.delete.assert_called_once_with(condition="id > 100")

        # Verify spark.sql() was NOT called
        mock_spark.sql.assert_not_called()

        assert result == 10  # 100 - 90

    def test_update_uses_delta_table_api(self):
        """Verify UPDATE uses DeltaTable.forPath().update(), not spark.sql()."""
        if not PYSPARK_AVAILABLE:
            pytest.skip("PySpark not installed")

        if not DELTA_SPARK_AVAILABLE:
            pytest.skip("delta-spark not installed")

        from unittest.mock import MagicMock, patch

        mock_spark = MagicMock()
        mock_delta_table = MagicMock()

        # Mock toDF() for row counting
        mock_df = MagicMock()
        mock_filtered = MagicMock()
        mock_filtered.count.return_value = 5
        mock_df.filter.return_value = mock_filtered
        mock_delta_table.toDF.return_value = mock_df

        ops = PySparkMaintenanceOperations(spark_session=mock_spark, prefer_delta=True)

        with patch("benchbox.platforms.dataframe.pyspark_maintenance.DeltaTable") as MockDeltaTable:
            MockDeltaTable.forPath.return_value = mock_delta_table

            with patch.object(ops, "is_delta_table", return_value=True):
                with patch.object(ops, "_to_spark_column", side_effect=lambda value: value):
                    result = ops._do_update(
                        table_path="/tmp/delta_table",
                        condition="status = 'pending'",
                        updates={"status": "'completed'"},
                    )

        # Verify DeltaTable.forPath() was called
        MockDeltaTable.forPath.assert_called_once_with(mock_spark, "/tmp/delta_table")

        # Verify DeltaTable.update() was called
        mock_delta_table.update.assert_called_once()

        # Verify spark.sql() was NOT called
        mock_spark.sql.assert_not_called()

        assert result == 5

    def test_merge_uses_delta_table_api(self):
        """Verify MERGE uses DeltaTable.alias().merge().execute(), not spark.sql()."""
        if not PYSPARK_AVAILABLE:
            pytest.skip("PySpark not installed")

        if not DELTA_SPARK_AVAILABLE:
            pytest.skip("delta-spark not installed")

        from unittest.mock import MagicMock, patch

        mock_spark = MagicMock()
        mock_delta_table = MagicMock()

        # Mock the merge chain
        mock_merge_builder = MagicMock()
        mock_delta_table.alias.return_value = mock_delta_table
        mock_delta_table.merge.return_value = mock_merge_builder
        mock_merge_builder.whenMatchedUpdate.return_value = mock_merge_builder
        mock_merge_builder.whenNotMatchedInsert.return_value = mock_merge_builder

        # Mock source DataFrame
        mock_source_df = MagicMock()
        mock_source_df.count.return_value = 10
        mock_source_df.alias.return_value = mock_source_df

        ops = PySparkMaintenanceOperations(spark_session=mock_spark, prefer_delta=True)

        with patch("benchbox.platforms.dataframe.pyspark_maintenance.DeltaTable") as MockDeltaTable:
            MockDeltaTable.forPath.return_value = mock_delta_table

            with patch.object(ops, "is_delta_table", return_value=True):
                with patch.object(ops, "_convert_to_spark_df", return_value=mock_source_df):
                    with patch.object(ops, "_to_spark_column", side_effect=lambda value: value):
                        result = ops._do_merge(
                            table_path="/tmp/delta_table",
                            source_dataframe=mock_source_df,
                            merge_condition="target.id = source.id",
                            when_matched={"name": "source.name"},
                            when_not_matched={"id": "source.id"},
                        )

        # Verify DeltaTable.forPath() was called
        MockDeltaTable.forPath.assert_called_once_with(mock_spark, "/tmp/delta_table")

        # Verify merge chain was called
        mock_delta_table.alias.assert_called_with("target")
        mock_delta_table.merge.assert_called_once()
        mock_merge_builder.execute.assert_called_once()

        # Verify spark.sql() was NOT called
        mock_spark.sql.assert_not_called()

        assert result == 10


@pyspark_maintenance_skip
class TestPySparkParquetLimitations:
    """Test that row-level operations raise NotImplementedError for plain Parquet."""

    def test_delete_raises_for_parquet(self):
        """Test DELETE raises NotImplementedError for non-Delta tables."""
        if not PYSPARK_AVAILABLE:
            pytest.skip("PySpark not installed")

        from unittest.mock import MagicMock, patch

        mock_spark = MagicMock()
        ops = PySparkMaintenanceOperations(spark_session=mock_spark, prefer_delta=True)

        with patch.object(ops, "is_delta_table", return_value=False):
            with pytest.raises(NotImplementedError, match="DELETE requires Delta Lake"):
                ops._do_delete("/tmp/parquet_table", "id > 100")

    def test_update_raises_for_parquet(self):
        """Test UPDATE raises NotImplementedError for non-Delta tables."""
        if not PYSPARK_AVAILABLE:
            pytest.skip("PySpark not installed")

        from unittest.mock import MagicMock, patch

        mock_spark = MagicMock()
        ops = PySparkMaintenanceOperations(spark_session=mock_spark, prefer_delta=True)

        with patch.object(ops, "is_delta_table", return_value=False):
            with pytest.raises(NotImplementedError, match="UPDATE requires Delta Lake"):
                ops._do_update("/tmp/parquet_table", "status = 'x'", {"status": "'y'"})

    def test_merge_raises_for_parquet(self):
        """Test MERGE raises NotImplementedError for non-Delta tables."""
        if not PYSPARK_AVAILABLE:
            pytest.skip("PySpark not installed")

        from unittest.mock import MagicMock, patch

        mock_spark = MagicMock()
        ops = PySparkMaintenanceOperations(spark_session=mock_spark, prefer_delta=True)

        with patch.object(ops, "is_delta_table", return_value=False):
            with pytest.raises(NotImplementedError, match="MERGE requires Delta Lake"):
                ops._do_merge("/tmp/parquet_table", MagicMock(), "id = id", None, None)
