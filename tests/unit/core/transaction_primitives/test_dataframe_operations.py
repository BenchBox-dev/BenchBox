"""Unit tests for Transaction Primitives DataFrame operations.

Tests for:
- TransactionOperationType enum
- DataFrameTransactionCapabilities dataclass
- DataFrameTransactionResult dataclass
- DataFrameTransactionOperationsManager
- Platform validation and error messages

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import pytest

from benchbox.core.dataframe.maintenance_interface import TransactionIsolation
from benchbox.core.transaction_primitives.dataframe_operations import (
    DELTA_LAKE_TRANSACTION_CAPABILITIES,
    ICEBERG_TRANSACTION_CAPABILITIES,
    PANDAS_TRANSACTION_CAPABILITIES,
    POLARS_TRANSACTION_CAPABILITIES,
    PYSPARK_DELTA_TRANSACTION_CAPABILITIES,
    DataFrameTransactionCapabilities,
    DataFrameTransactionOperationsManager,
    DataFrameTransactionResult,
    TransactionOperationType,
    get_dataframe_transaction_manager,
    validate_transaction_primitives_platform,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestTransactionOperationType:
    """Tests for TransactionOperationType enum."""

    def test_atomic_operations_exist(self):
        """Test that atomic write operation types exist."""
        assert TransactionOperationType.ATOMIC_INSERT is not None
        assert TransactionOperationType.ATOMIC_UPDATE is not None
        assert TransactionOperationType.ATOMIC_DELETE is not None
        assert TransactionOperationType.ATOMIC_MERGE is not None

    def test_rollback_operations_exist(self):
        """Test that rollback operation types exist."""
        assert TransactionOperationType.ROLLBACK_TO_VERSION is not None
        assert TransactionOperationType.ROLLBACK_TO_TIMESTAMP is not None

    def test_time_travel_operations_exist(self):
        """Test that time travel operation types exist."""
        assert TransactionOperationType.TIME_TRAVEL_QUERY is not None
        assert TransactionOperationType.VERSION_COMPARE is not None

    def test_concurrency_operations_exist(self):
        """Test that concurrency operation types exist."""
        assert TransactionOperationType.CONCURRENT_WRITE is not None
        assert TransactionOperationType.CONFLICT_RESOLUTION is not None

    def test_isolation_operations_exist(self):
        """Test that isolation operation types exist."""
        assert TransactionOperationType.SNAPSHOT_ISOLATION is not None
        assert TransactionOperationType.READ_YOUR_WRITES is not None

    def test_operation_values_are_strings(self):
        """Test that operation values are lowercase strings."""
        for op in TransactionOperationType:
            assert isinstance(op.value, str)
            assert op.value == op.value.lower()


class TestDataFrameTransactionCapabilities:
    """Tests for DataFrameTransactionCapabilities dataclass."""

    def test_default_no_transaction_support(self):
        """Test default capabilities have no transaction support."""
        caps = DataFrameTransactionCapabilities(platform_name="test")
        assert caps.supports_transactions is False
        assert caps.supports_rollback is False
        assert caps.supports_time_travel is False
        assert caps.supports_concurrent_writes is False
        assert caps.transaction_isolation == TransactionIsolation.NONE
        assert caps.table_format == "none"

    def test_full_transaction_support(self):
        """Test capabilities with full transaction support."""
        caps = DataFrameTransactionCapabilities(
            platform_name="test-acid",
            supports_transactions=True,
            supports_rollback=True,
            supports_time_travel=True,
            supports_concurrent_writes=True,
            transaction_isolation=TransactionIsolation.SNAPSHOT,
            table_format="delta",
        )
        assert caps.supports_transactions is True
        assert caps.supports_rollback is True
        assert caps.supports_time_travel is True
        assert caps.transaction_isolation == TransactionIsolation.SNAPSHOT

    def test_delta_lake_capabilities(self):
        """Test pre-defined Delta Lake capabilities."""
        caps = DELTA_LAKE_TRANSACTION_CAPABILITIES
        assert caps.platform_name == "delta-lake"
        assert caps.supports_transactions is True
        assert caps.supports_rollback is True
        assert caps.supports_time_travel is True
        assert caps.supports_concurrent_writes is True
        assert caps.transaction_isolation == TransactionIsolation.SNAPSHOT
        assert caps.table_format == "delta"

    def test_pyspark_delta_capabilities(self):
        """Test pre-defined PySpark + Delta capabilities."""
        caps = PYSPARK_DELTA_TRANSACTION_CAPABILITIES
        assert caps.platform_name == "pyspark-delta"
        assert caps.supports_transactions is True
        assert caps.supports_rollback is True
        assert caps.table_format == "delta"

    def test_iceberg_capabilities(self):
        """Test pre-defined Iceberg capabilities."""
        caps = ICEBERG_TRANSACTION_CAPABILITIES
        assert caps.platform_name == "iceberg"
        assert caps.supports_transactions is True
        assert caps.supports_rollback is True
        assert caps.table_format == "iceberg"

    def test_polars_capabilities(self):
        """Test pre-defined Polars capabilities (no transactions)."""
        caps = POLARS_TRANSACTION_CAPABILITIES
        assert caps.platform_name == "polars-df"
        assert caps.supports_transactions is False
        assert caps.supports_rollback is False
        assert caps.table_format == "parquet"
        assert "No transaction support" in caps.notes

    def test_pandas_capabilities(self):
        """Test pre-defined Pandas capabilities (no transactions)."""
        caps = PANDAS_TRANSACTION_CAPABILITIES
        assert caps.platform_name == "pandas-df"
        assert caps.supports_transactions is False
        assert caps.supports_rollback is False
        assert caps.table_format == "parquet"

    def test_supports_operation_atomic_writes(self):
        """Test supports_operation for atomic writes."""
        caps = DELTA_LAKE_TRANSACTION_CAPABILITIES
        assert caps.supports_operation(TransactionOperationType.ATOMIC_INSERT) is True
        assert caps.supports_operation(TransactionOperationType.ATOMIC_UPDATE) is True
        assert caps.supports_operation(TransactionOperationType.ATOMIC_DELETE) is True
        assert caps.supports_operation(TransactionOperationType.ATOMIC_MERGE) is True

    def test_supports_operation_rollback(self):
        """Test supports_operation for rollback."""
        delta_caps = DELTA_LAKE_TRANSACTION_CAPABILITIES
        assert delta_caps.supports_operation(TransactionOperationType.ROLLBACK_TO_VERSION) is True
        assert delta_caps.supports_operation(TransactionOperationType.ROLLBACK_TO_TIMESTAMP) is True

        polars_caps = POLARS_TRANSACTION_CAPABILITIES
        assert polars_caps.supports_operation(TransactionOperationType.ROLLBACK_TO_VERSION) is False
        assert polars_caps.supports_operation(TransactionOperationType.ROLLBACK_TO_TIMESTAMP) is False

    def test_supports_operation_time_travel(self):
        """Test supports_operation for time travel."""
        delta_caps = DELTA_LAKE_TRANSACTION_CAPABILITIES
        assert delta_caps.supports_operation(TransactionOperationType.TIME_TRAVEL_QUERY) is True
        assert delta_caps.supports_operation(TransactionOperationType.VERSION_COMPARE) is True

        polars_caps = POLARS_TRANSACTION_CAPABILITIES
        assert polars_caps.supports_operation(TransactionOperationType.TIME_TRAVEL_QUERY) is False

    def test_supports_operation_isolation(self):
        """Test supports_operation for isolation tests."""
        delta_caps = DELTA_LAKE_TRANSACTION_CAPABILITIES
        assert delta_caps.supports_operation(TransactionOperationType.SNAPSHOT_ISOLATION) is True
        assert delta_caps.supports_operation(TransactionOperationType.READ_YOUR_WRITES) is True

        polars_caps = POLARS_TRANSACTION_CAPABILITIES
        assert polars_caps.supports_operation(TransactionOperationType.SNAPSHOT_ISOLATION) is False

    def test_get_unsupported_operations(self):
        """Test get_unsupported_operations method."""
        delta_caps = DELTA_LAKE_TRANSACTION_CAPABILITIES
        unsupported = delta_caps.get_unsupported_operations()
        # Delta Lake supports all operations
        assert len(unsupported) == 0

        polars_caps = POLARS_TRANSACTION_CAPABILITIES
        unsupported = polars_caps.get_unsupported_operations()
        # Polars doesn't support any transaction operations
        assert len(unsupported) == len(list(TransactionOperationType))


class TestDataFrameTransactionResult:
    """Tests for DataFrameTransactionResult dataclass."""

    def test_success_result(self):
        """Test creating a successful result."""
        result = DataFrameTransactionResult(
            operation_type=TransactionOperationType.ATOMIC_INSERT,
            success=True,
            start_time=1000.0,
            end_time=1001.5,
            duration_ms=1500.0,
            rows_affected=100,
            version_before=1,
            version_after=2,
        )
        assert result.success is True
        assert result.rows_affected == 100
        assert result.version_before == 1
        assert result.version_after == 2
        assert result.error_message is None

    def test_failure_result_factory(self):
        """Test creating a failure result via factory method."""
        result = DataFrameTransactionResult.failure(
            TransactionOperationType.ATOMIC_UPDATE,
            "Table not found",
            start_time=1000.0,
        )
        assert result.success is False
        assert result.error_message == "Table not found"
        assert result.rows_affected == 0
        assert result.validation_passed is False

    def test_failure_without_start_time(self):
        """Test failure result without explicit start time."""
        result = DataFrameTransactionResult.failure(
            TransactionOperationType.ROLLBACK_TO_VERSION,
            "Version not available",
        )
        assert result.success is False
        assert result.duration_ms == 0.0

    def test_result_with_metrics(self):
        """Test result with custom metrics."""
        result = DataFrameTransactionResult(
            operation_type=TransactionOperationType.ATOMIC_INSERT,
            success=True,
            start_time=1000.0,
            end_time=1001.0,
            duration_ms=1000.0,
            rows_affected=50,
            metrics={"write_duration_ms": 950.0, "version_check_overhead_ms": 50.0},
        )
        assert result.metrics["write_duration_ms"] == 950.0
        assert result.metrics["version_check_overhead_ms"] == 50.0


class TestValidateTransactionPrimitivesPlatform:
    """Tests for validate_transaction_primitives_platform function."""

    def test_pyspark_is_valid(self):
        """Test that pyspark-df is valid for transactions."""
        is_valid, error_msg = validate_transaction_primitives_platform("pyspark-df")
        assert is_valid is True
        assert error_msg == ""

    def test_delta_lake_is_valid(self):
        """Test that delta-lake is valid for transactions."""
        is_valid, error_msg = validate_transaction_primitives_platform("delta-lake")
        assert is_valid is True
        assert error_msg == ""

    def test_iceberg_is_valid(self):
        """Test that iceberg is valid for transactions."""
        is_valid, error_msg = validate_transaction_primitives_platform("iceberg")
        assert is_valid is True
        assert error_msg == ""

    def test_polars_is_invalid(self):
        """Test that polars-df is invalid for transactions."""
        is_valid, error_msg = validate_transaction_primitives_platform("polars-df")
        assert is_valid is False
        assert "does not support DataFrame transactions" in error_msg
        assert "pyspark-df" in error_msg  # Should suggest alternative

    def test_pandas_is_invalid(self):
        """Test that pandas-df is invalid for transactions."""
        is_valid, error_msg = validate_transaction_primitives_platform("pandas-df")
        assert is_valid is False
        assert "does not support" in error_msg

    def test_duckdb_is_invalid(self):
        """Test that duckdb is invalid for transactions."""
        is_valid, error_msg = validate_transaction_primitives_platform("duckdb")
        assert is_valid is False
        assert "does not support" in error_msg

    def test_sqlite_is_invalid(self):
        """Test that sqlite is invalid for transactions."""
        is_valid, error_msg = validate_transaction_primitives_platform("sqlite")
        assert is_valid is False

    def test_unknown_platform_allowed(self):
        """Test that unknown platforms are allowed (may have transaction support)."""
        is_valid, error_msg = validate_transaction_primitives_platform("custom-platform")
        assert is_valid is True  # Unknown platforms are allowed


class TestDataFrameTransactionOperationsManager:
    """Tests for DataFrameTransactionOperationsManager."""

    def test_polars_manager_no_transaction_support(self):
        """Test that Polars manager reports no transaction support."""
        manager = DataFrameTransactionOperationsManager("polars-df")
        assert manager.supports_transactions() is False

        caps = manager.get_capabilities()
        assert caps.supports_transactions is False

    def test_pandas_manager_no_transaction_support(self):
        """Test that Pandas manager reports no transaction support."""
        manager = DataFrameTransactionOperationsManager("pandas-df")
        assert manager.supports_transactions() is False

    def test_unsupported_message_helpful(self):
        """Test that unsupported message provides helpful alternatives."""
        manager = DataFrameTransactionOperationsManager("polars-df")
        msg = manager.get_unsupported_message()

        assert "polars-df" in msg
        assert "pyspark-df" in msg.lower()  # Should suggest PySpark
        assert "delta" in msg.lower()  # Should mention Delta Lake

    def test_manager_platform_name_normalized(self):
        """Test that platform name is normalized to lowercase."""
        manager = DataFrameTransactionOperationsManager("POLARS-DF")
        assert manager.platform_name == "polars-df"

    def test_manager_supports_operation_check(self):
        """Test supports_operation method."""
        manager = DataFrameTransactionOperationsManager("polars-df")

        # Polars should not support any transaction operations
        assert manager.supports_operation(TransactionOperationType.ATOMIC_INSERT) is False
        assert manager.supports_operation(TransactionOperationType.ROLLBACK_TO_VERSION) is False


class TestGetDataFrameTransactionManager:
    """Tests for get_dataframe_transaction_manager factory function."""

    def test_returns_manager_for_dataframe_platform(self):
        """Test that factory returns manager for known DataFrame platforms."""
        manager = get_dataframe_transaction_manager("polars-df")
        assert manager is not None
        assert isinstance(manager, DataFrameTransactionOperationsManager)

    def test_returns_manager_for_delta_lake(self):
        """Test that factory returns manager for delta-lake."""
        manager = get_dataframe_transaction_manager("delta-lake")
        assert manager is not None

    def test_returns_none_for_sql_platform(self):
        """Test that factory returns None for SQL platforms."""
        manager = get_dataframe_transaction_manager("duckdb")
        assert manager is None

        manager = get_dataframe_transaction_manager("postgresql")
        assert manager is None

    def test_returns_none_for_unknown_platform(self):
        """Test that factory returns None for completely unknown platforms."""
        manager = get_dataframe_transaction_manager("unknown-platform-xyz")
        assert manager is None


class TestAtomicOperationsFailForNonAcidPlatforms:
    """Test that atomic operations fail gracefully for non-ACID platforms."""

    def test_atomic_insert_fails_on_polars(self, tmp_path):
        """Test that atomic insert fails on Polars with helpful message."""
        manager = DataFrameTransactionOperationsManager("polars-df")
        result = manager.execute_atomic_insert(
            table_path=tmp_path / "test_table",
            dataframe=None,  # Would fail anyway, but should fail on capability check first
        )
        assert result.success is False
        assert "ACID transaction support" in result.error_message

    def test_atomic_update_fails_on_polars(self, tmp_path):
        """Test that atomic update fails on Polars with helpful message."""
        manager = DataFrameTransactionOperationsManager("polars-df")
        result = manager.execute_atomic_update(
            table_path=tmp_path / "test_table",
            condition="id > 0",
            updates={"status": "'updated'"},
        )
        assert result.success is False
        assert "ACID transaction support" in result.error_message

    def test_rollback_fails_on_polars(self, tmp_path):
        """Test that rollback fails on Polars with helpful message."""
        manager = DataFrameTransactionOperationsManager("polars-df")
        result = manager.execute_rollback_to_version(
            table_path=tmp_path / "test_table",
            version=1,
        )
        assert result.success is False
        assert "Rollback not supported" in result.error_message

    def test_time_travel_fails_on_polars(self, tmp_path):
        """Test that time travel fails on Polars with helpful message."""
        manager = DataFrameTransactionOperationsManager("polars-df")
        result = manager.execute_time_travel_query(
            table_path=tmp_path / "test_table",
            version=1,
        )
        assert result.success is False
        assert "Time travel not supported" in result.error_message

    def test_version_compare_fails_on_polars(self, tmp_path):
        """Test that version compare fails on Polars with helpful message."""
        manager = DataFrameTransactionOperationsManager("polars-df")
        result = manager.execute_version_compare(
            table_path=tmp_path / "test_table",
            version1=1,
            version2=2,
        )
        assert result.success is False
        assert "Version compare not supported" in result.error_message


class TestTableFormatValidation:
    """Test table format validation."""

    def test_validate_nonexistent_table(self, tmp_path):
        """Test validation of nonexistent table path."""
        manager = DataFrameTransactionOperationsManager("delta-lake")
        is_valid, error_msg = manager.validate_table_format(tmp_path / "nonexistent")
        assert is_valid is False
        assert "does not exist" in error_msg

    def test_validate_plain_parquet_directory(self, tmp_path):
        """Test validation of plain Parquet directory (not Delta)."""
        # Create a directory with a Parquet file but no _delta_log
        table_dir = tmp_path / "parquet_table"
        table_dir.mkdir()
        (table_dir / "part-00000.parquet").touch()

        manager = DataFrameTransactionOperationsManager("delta-lake")
        is_valid, error_msg = manager.validate_table_format(table_dir)
        assert is_valid is False
        assert "not a Delta Lake" in error_msg
        assert "df.write.format('delta')" in error_msg  # Should suggest conversion

    def test_validate_delta_table_directory(self, tmp_path):
        """Test validation of Delta Lake table directory."""
        # Create a directory structure that looks like a Delta table
        table_dir = tmp_path / "delta_table"
        table_dir.mkdir()
        delta_log = table_dir / "_delta_log"
        delta_log.mkdir()
        (delta_log / "00000000000000000000.json").touch()

        manager = DataFrameTransactionOperationsManager("delta-lake")
        is_valid, error_msg = manager.validate_table_format(table_dir)
        assert is_valid is True
        assert error_msg == ""

    def test_validate_path_traversal_rejected(self, tmp_path):
        """Test that path traversal attempts are rejected."""
        manager = DataFrameTransactionOperationsManager("delta-lake")

        # Path traversal attempt
        is_valid, error_msg = manager.validate_table_format(tmp_path / ".." / "etc" / "passwd")
        assert is_valid is False
        assert "Path traversal" in error_msg

    def test_validate_path_traversal_in_string(self):
        """Test that path traversal in string paths is rejected."""
        manager = DataFrameTransactionOperationsManager("delta-lake")

        # String path with traversal
        is_valid, error_msg = manager.validate_table_format("/data/../../../etc/passwd")
        assert is_valid is False
        assert "Path traversal" in error_msg


class TestBenchmarkIntegration:
    """Test integration with TransactionPrimitivesBenchmark."""

    def test_benchmark_supports_dataframe_mode_pyspark(self):
        """Test benchmark supports DataFrame mode for PySpark."""
        from benchbox.core.transaction_primitives.benchmark import TransactionPrimitivesBenchmark

        benchmark = TransactionPrimitivesBenchmark(scale_factor=0.01)
        assert benchmark.supports_dataframe_mode("pyspark-df") is True

    def test_benchmark_supports_dataframe_mode_delta(self):
        """Test benchmark supports DataFrame mode for Delta Lake."""
        from benchbox.core.transaction_primitives.benchmark import TransactionPrimitivesBenchmark

        benchmark = TransactionPrimitivesBenchmark(scale_factor=0.01)
        assert benchmark.supports_dataframe_mode("delta-lake") is True

    def test_benchmark_rejects_dataframe_mode_polars(self):
        """Test benchmark rejects DataFrame mode for Polars."""
        from benchbox.core.transaction_primitives.benchmark import TransactionPrimitivesBenchmark

        benchmark = TransactionPrimitivesBenchmark(scale_factor=0.01)
        assert benchmark.supports_dataframe_mode("polars-df") is False

    def test_benchmark_rejects_dataframe_mode_pandas(self):
        """Test benchmark rejects DataFrame mode for Pandas."""
        from benchbox.core.transaction_primitives.benchmark import TransactionPrimitivesBenchmark

        benchmark = TransactionPrimitivesBenchmark(scale_factor=0.01)
        assert benchmark.supports_dataframe_mode("pandas-df") is False

    def test_benchmark_get_dataframe_operations_raises_for_polars(self):
        """Test get_dataframe_operations raises for Polars."""
        from benchbox.core.transaction_primitives.benchmark import TransactionPrimitivesBenchmark

        benchmark = TransactionPrimitivesBenchmark(scale_factor=0.01)
        with pytest.raises(ValueError, match="does not support"):
            benchmark.get_dataframe_operations("polars-df")

    def test_benchmark_validate_dataframe_configuration_pyspark_no_session(self):
        """Test validation fails for PySpark without SparkSession."""
        from benchbox.core.transaction_primitives.benchmark import TransactionPrimitivesBenchmark

        benchmark = TransactionPrimitivesBenchmark(scale_factor=0.01)
        is_valid, error_msg = benchmark.validate_dataframe_configuration("pyspark-df")
        assert is_valid is False
        assert "SparkSession" in error_msg


class TestNewOperationTypes:
    """Tests for the four additional operation type implementations."""

    def test_all_12_operation_types_present(self):
        assert len(TransactionOperationType) == 12

    def test_concurrent_write_in_enum(self):
        assert TransactionOperationType.CONCURRENT_WRITE.value == "concurrent_write"

    def test_conflict_resolution_in_enum(self):
        assert TransactionOperationType.CONFLICT_RESOLUTION.value == "conflict_resolution"

    def test_snapshot_isolation_in_enum(self):
        assert TransactionOperationType.SNAPSHOT_ISOLATION.value == "snapshot_isolation"

    def test_read_your_writes_in_enum(self):
        assert TransactionOperationType.READ_YOUR_WRITES.value == "read_your_writes"

    def test_execute_concurrent_write_rejects_unsupported_platform(self):
        """Polars cannot run concurrent write - should return failure result."""
        manager = DataFrameTransactionOperationsManager("polars-df", POLARS_TRANSACTION_CAPABILITIES)
        result = manager.execute_concurrent_write("/tmp/fake_table", [])
        assert result.success is False
        assert "concurrent_write" in result.error_message.lower() or "not supported" in result.error_message.lower()

    def test_execute_conflict_resolution_rejects_unsupported_platform(self):
        """Pandas cannot run conflict resolution - should return failure result."""
        manager = DataFrameTransactionOperationsManager("pandas-df", PANDAS_TRANSACTION_CAPABILITIES)
        result = manager.execute_conflict_resolution("/tmp/fake_table", None)
        assert result.success is False

    def test_execute_snapshot_isolation_rejects_unsupported_platform(self):
        """Polars has NONE isolation - should return failure result."""
        manager = DataFrameTransactionOperationsManager("polars-df", POLARS_TRANSACTION_CAPABILITIES)
        result = manager.execute_snapshot_isolation("/tmp/fake_table")
        assert result.success is False

    def test_execute_read_your_writes_rejects_unsupported_platform(self):
        """Polars has no transaction support - should return failure result."""
        manager = DataFrameTransactionOperationsManager("polars-df", POLARS_TRANSACTION_CAPABILITIES)
        result = manager.execute_read_your_writes("/tmp/fake_table", None)
        assert result.success is False

    def test_delta_capabilities_support_all_new_operations(self):
        """Delta Lake capabilities should support all 4 new operation types."""
        assert DELTA_LAKE_TRANSACTION_CAPABILITIES.supports_operation(TransactionOperationType.CONCURRENT_WRITE)
        assert DELTA_LAKE_TRANSACTION_CAPABILITIES.supports_operation(TransactionOperationType.CONFLICT_RESOLUTION)
        assert DELTA_LAKE_TRANSACTION_CAPABILITIES.supports_operation(TransactionOperationType.SNAPSHOT_ISOLATION)
        assert DELTA_LAKE_TRANSACTION_CAPABILITIES.supports_operation(TransactionOperationType.READ_YOUR_WRITES)


class TestBenchmarkRegistryDataframeFlag:
    """Tests that benchmark_registry correctly reports transaction_primitives DataFrame support.

    execute_dataframe_workload() is now fully implemented (three-phase Delta Lake
    execution via DataFrameTransactionOperationsManager), so the flag is True.
    """

    def test_transaction_primitives_supports_dataframe(self):
        from benchbox.core.benchmark_registry import BENCHMARK_METADATA

        assert BENCHMARK_METADATA["transaction_primitives"]["supports_dataframe"] is True

    def test_transaction_primitives_num_queries_is_12(self):
        from benchbox.core.benchmark_registry import BENCHMARK_METADATA

        assert BENCHMARK_METADATA["transaction_primitives"]["num_queries"] == 12
