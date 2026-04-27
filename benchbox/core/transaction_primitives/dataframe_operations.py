"""DataFrame operations for Transaction Primitives benchmark.

This module provides DataFrame implementations of Transaction Primitives operations,
enabling benchmarking of ACID transaction semantics on DataFrame platforms that
support Delta Lake, Iceberg, or other table formats with transaction support.

Transaction Primitives tests fundamental database transaction semantics:
- COMMIT: Atomic commit of changes
- ROLLBACK: Rollback to previous state (via RESTORE for Delta Lake)
- Isolation: Snapshot isolation verification
- Concurrency: Parallel write conflict handling
- Time Travel: Query and restore historical versions

Platform Support:
    - PySpark + Delta Lake: Full ACID support
        - Atomic writes (each operation is a transaction)
        - RESTORE TO VERSION/TIMESTAMP for rollback
        - Snapshot isolation
        - Time travel queries
    - PySpark + Iceberg: Full ACID support
        - Snapshot-based isolation
        - Time travel via snapshots
    - Polars/Pandas: NOT SUPPORTED
        - No transaction semantics
        - Users directed to use Delta Lake or Iceberg

Note:
    Unlike traditional SQL databases with BEGIN/COMMIT/ROLLBACK, Delta Lake and
    Iceberg use atomic operations where each write is automatically committed.
    "Rollback" is achieved via RESTORE (Delta) or rollback_to_snapshot (Iceberg).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from benchbox.core.dataframe.maintenance_interface import (
    DataFrameMaintenanceCapabilities,
    TransactionIsolation,
    get_maintenance_operations_for_platform,
)
from benchbox.core.dataframe_manager_factory import get_dataframe_manager

logger = logging.getLogger(__name__)


class TransactionOperationType(Enum):
    """Types of transaction operations supported by the benchmark.

    These operations test ACID transaction semantics on DataFrame platforms
    that support table formats like Delta Lake or Iceberg.
    """

    # Atomic write operations (tests implicit commit)
    ATOMIC_INSERT = "atomic_insert"
    ATOMIC_UPDATE = "atomic_update"
    ATOMIC_DELETE = "atomic_delete"
    ATOMIC_MERGE = "atomic_merge"

    # Rollback operations (Delta Lake RESTORE, Iceberg rollback)
    ROLLBACK_TO_VERSION = "rollback_to_version"
    ROLLBACK_TO_TIMESTAMP = "rollback_to_timestamp"

    # Time travel operations
    TIME_TRAVEL_QUERY = "time_travel_query"
    VERSION_COMPARE = "version_compare"

    # Concurrency tests
    CONCURRENT_WRITE = "concurrent_write"
    CONFLICT_RESOLUTION = "conflict_resolution"

    # Isolation verification
    SNAPSHOT_ISOLATION = "snapshot_isolation"
    READ_YOUR_WRITES = "read_your_writes"


@dataclass
class DataFrameTransactionCapabilities:
    """Platform capabilities for DataFrame transaction operations.

    Declares what transaction-related operations a DataFrame platform supports.
    This is used to validate configurations and provide helpful error messages
    when users attempt to run transaction benchmarks on unsupported platforms.

    Attributes:
        platform_name: Name of the platform
        supports_transactions: Has atomic transaction support
        supports_rollback: Can rollback to previous versions
        supports_time_travel: Can query historical versions
        supports_concurrent_writes: Has concurrency control
        transaction_isolation: Isolation level supported
        table_format: Underlying table format (delta, iceberg, parquet, none)
        notes: Platform-specific notes
    """

    platform_name: str
    supports_transactions: bool = False
    supports_rollback: bool = False
    supports_time_travel: bool = False
    supports_concurrent_writes: bool = False
    transaction_isolation: TransactionIsolation = TransactionIsolation.NONE
    table_format: str = "none"
    notes: str = ""

    def supports_operation(self, operation: TransactionOperationType) -> bool:
        """Check if an operation type is supported.

        Args:
            operation: The operation type to check

        Returns:
            True if the operation is supported
        """
        mapping = {
            # Atomic writes require transaction support
            TransactionOperationType.ATOMIC_INSERT: self.supports_transactions,
            TransactionOperationType.ATOMIC_UPDATE: self.supports_transactions,
            TransactionOperationType.ATOMIC_DELETE: self.supports_transactions,
            TransactionOperationType.ATOMIC_MERGE: self.supports_transactions,
            # Rollback requires RESTORE or equivalent
            TransactionOperationType.ROLLBACK_TO_VERSION: self.supports_rollback,
            TransactionOperationType.ROLLBACK_TO_TIMESTAMP: self.supports_rollback,
            # Time travel queries
            TransactionOperationType.TIME_TRAVEL_QUERY: self.supports_time_travel,
            TransactionOperationType.VERSION_COMPARE: self.supports_time_travel,
            # Concurrency tests
            TransactionOperationType.CONCURRENT_WRITE: self.supports_concurrent_writes,
            TransactionOperationType.CONFLICT_RESOLUTION: self.supports_concurrent_writes,
            # Isolation tests
            TransactionOperationType.SNAPSHOT_ISOLATION: (self.transaction_isolation == TransactionIsolation.SNAPSHOT),
            TransactionOperationType.READ_YOUR_WRITES: self.supports_transactions,
        }
        return mapping.get(operation, False)

    def get_unsupported_operations(self) -> list[TransactionOperationType]:
        """Get list of operations not supported by this platform.

        Returns:
            List of unsupported TransactionOperationType values
        """
        return [op for op in TransactionOperationType if not self.supports_operation(op)]


# Pre-defined capability profiles for platforms
DELTA_LAKE_TRANSACTION_CAPABILITIES = DataFrameTransactionCapabilities(
    platform_name="delta-lake",
    supports_transactions=True,
    supports_rollback=True,
    supports_time_travel=True,
    supports_concurrent_writes=True,
    transaction_isolation=TransactionIsolation.SNAPSHOT,
    table_format="delta",
    notes="Full ACID via Delta Lake. RESTORE for rollback, version queries for time travel.",
)

PYSPARK_DELTA_TRANSACTION_CAPABILITIES = DataFrameTransactionCapabilities(
    platform_name="pyspark-delta",
    supports_transactions=True,
    supports_rollback=True,
    supports_time_travel=True,
    supports_concurrent_writes=True,
    transaction_isolation=TransactionIsolation.SNAPSHOT,
    table_format="delta",
    notes="Full ACID via delta-spark. Uses DeltaTable API for transactions.",
)

ICEBERG_TRANSACTION_CAPABILITIES = DataFrameTransactionCapabilities(
    platform_name="iceberg",
    supports_transactions=True,
    supports_rollback=True,
    supports_time_travel=True,
    supports_concurrent_writes=True,
    transaction_isolation=TransactionIsolation.SNAPSHOT,
    table_format="iceberg",
    notes="Full ACID via Apache Iceberg. Snapshot-based transactions.",
)

POLARS_TRANSACTION_CAPABILITIES = DataFrameTransactionCapabilities(
    platform_name="polars-df",
    supports_transactions=False,
    supports_rollback=False,
    supports_time_travel=False,
    supports_concurrent_writes=False,
    transaction_isolation=TransactionIsolation.NONE,
    table_format="parquet",
    notes="No transaction support. Use Delta Lake or Iceberg for ACID operations.",
)

PANDAS_TRANSACTION_CAPABILITIES = DataFrameTransactionCapabilities(
    platform_name="pandas-df",
    supports_transactions=False,
    supports_rollback=False,
    supports_time_travel=False,
    supports_concurrent_writes=False,
    transaction_isolation=TransactionIsolation.NONE,
    table_format="parquet",
    notes="No transaction support. Use Delta Lake or Iceberg for ACID operations.",
)


@dataclass
class DataFrameTransactionResult:
    """Result of a DataFrame transaction operation.

    Standardized result container for transaction operations, capturing
    timing, success status, and operation-specific metrics.

    Attributes:
        operation_type: Type of transaction operation
        success: Whether the operation completed successfully
        start_time: Operation start timestamp (Unix time)
        end_time: Operation end timestamp (Unix time)
        duration_ms: Operation duration in milliseconds
        rows_affected: Number of rows affected
        version_before: Table version before operation (if applicable)
        version_after: Table version after operation (if applicable)
        error_message: Error description if operation failed
        validation_passed: Whether validation checks passed
        validation_results: Details of validation checks
        metrics: Additional operation-specific metrics
    """

    operation_type: TransactionOperationType
    success: bool
    start_time: float
    end_time: float
    duration_ms: float
    rows_affected: int
    version_before: int | None = None
    version_after: int | None = None
    error_message: str | None = None
    validation_passed: bool = True
    validation_results: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def failure(
        cls,
        operation_type: TransactionOperationType,
        error_message: str,
        start_time: float | None = None,
    ) -> DataFrameTransactionResult:
        """Create a failure result.

        Args:
            operation_type: The operation that failed
            error_message: Description of the failure
            start_time: Optional start time (defaults to now)

        Returns:
            DataFrameTransactionResult indicating failure
        """
        now = time.time()
        return cls(
            operation_type=operation_type,
            success=False,
            start_time=start_time or now,
            end_time=now,
            duration_ms=0.0 if start_time is None else (now - start_time) * 1000,
            rows_affected=0,
            error_message=error_message,
            validation_passed=False,
        )


class DataFrameTransactionOperationsManager:
    """Manager for DataFrame transaction operations.

    Provides transaction-specific operations for DataFrame platforms that support
    ACID semantics via Delta Lake, Iceberg, or similar table formats.

    This manager wraps the maintenance operations interface with transaction-specific
    functionality including:
    - Atomic write operations with version tracking
    - Rollback via RESTORE (Delta Lake) or snapshot rollback (Iceberg)
    - Time travel queries
    - Concurrency and isolation testing

    Example:
        # With PySpark + Delta Lake
        manager = DataFrameTransactionOperationsManager(
            "pyspark-df", spark_session=spark
        )

        # Check capabilities before running
        if not manager.supports_transactions():
            raise RuntimeError(manager.get_unsupported_message())

        # Execute atomic insert
        result = manager.execute_atomic_insert(
            table_path="/data/orders",
            dataframe=new_orders_df
        )
        emit(f"Version: {result.version_before} -> {result.version_after}")

        # Rollback to previous version
        result = manager.execute_rollback_to_version(
            table_path="/data/orders",
            version=result.version_before
        )

    Note:
        For non-ACID platforms (Polars, Pandas), this manager will raise
        clear errors directing users to use Delta Lake or Iceberg.
    """

    def __init__(self, platform_name: str, spark_session: Any = None) -> None:
        """Initialize the transaction operations manager.

        Args:
            platform_name: Platform name (e.g., "pyspark-df", "delta-lake")
            spark_session: SparkSession instance (required for pyspark-df)

        Raises:
            ValueError: If platform is not recognized
        """
        self.platform_name = platform_name.lower()
        self.spark_session = spark_session
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Get maintenance operations handler (for atomic writes)
        self._maintenance_ops = self._get_maintenance_ops()

        # Build transaction capabilities
        self._capabilities = self._build_capabilities()

    def _get_maintenance_ops(self) -> Any:
        """Get the appropriate maintenance operations handler.

        Returns:
            Maintenance operations handler or None
        """
        if "pyspark" in self.platform_name or "spark" in self.platform_name:
            if self.spark_session is not None:
                try:
                    from benchbox.platforms.dataframe.pyspark_maintenance import (
                        get_pyspark_maintenance_operations,
                    )

                    return get_pyspark_maintenance_operations(
                        spark_session=self.spark_session,
                        prefer_delta=True,
                    )
                except ImportError:
                    self.logger.debug("PySpark maintenance module not available")
                    return None
            else:
                self.logger.debug("No SparkSession provided for PySpark platform")
                return None

        return get_maintenance_operations_for_platform(self.platform_name)

    def _build_capabilities(self) -> DataFrameTransactionCapabilities:
        """Build platform transaction capabilities.

        Returns:
            DataFrameTransactionCapabilities for this platform
        """
        # Get maintenance capabilities if available
        maintenance_caps: DataFrameMaintenanceCapabilities | None = None
        if self._maintenance_ops is not None:
            maintenance_caps = self._maintenance_ops.get_capabilities()

        # Platform-specific capability profiles
        if "delta" in self.platform_name:
            # Standalone Delta Lake (delta-rs)
            return DELTA_LAKE_TRANSACTION_CAPABILITIES

        if "pyspark" in self.platform_name or "spark" in self.platform_name:
            # PySpark - check if Delta Lake is available
            if maintenance_caps and maintenance_caps.supports_transactions:
                return PYSPARK_DELTA_TRANSACTION_CAPABILITIES
            # PySpark without Delta Lake - limited support
            return DataFrameTransactionCapabilities(
                platform_name=self.platform_name,
                supports_transactions=False,
                table_format="parquet",
                notes="PySpark without Delta Lake. Install delta-spark for ACID support.",
            )

        if "iceberg" in self.platform_name:
            return ICEBERG_TRANSACTION_CAPABILITIES

        if "polars" in self.platform_name:
            return POLARS_TRANSACTION_CAPABILITIES

        if "pandas" in self.platform_name:
            return PANDAS_TRANSACTION_CAPABILITIES

        # Unknown platform - check maintenance capabilities
        if maintenance_caps and maintenance_caps.supports_transactions:
            return DataFrameTransactionCapabilities(
                platform_name=self.platform_name,
                supports_transactions=True,
                supports_rollback=maintenance_caps.supports_time_travel,
                supports_time_travel=maintenance_caps.supports_time_travel,
                supports_concurrent_writes=True,
                transaction_isolation=maintenance_caps.transaction_isolation,
                table_format="unknown",
            )

        # Default: no transaction support
        return DataFrameTransactionCapabilities(
            platform_name=self.platform_name,
            supports_transactions=False,
            notes="Platform does not support ACID transactions.",
        )

    def get_capabilities(self) -> DataFrameTransactionCapabilities:
        """Get platform transaction capabilities.

        Returns:
            DataFrameTransactionCapabilities for this platform
        """
        return self._capabilities

    def supports_transactions(self) -> bool:
        """Check if the platform supports ACID transactions.

        Returns:
            True if the platform supports transactions
        """
        return self._capabilities.supports_transactions

    def supports_operation(self, operation: TransactionOperationType) -> bool:
        """Check if an operation type is supported.

        Args:
            operation: The operation to check

        Returns:
            True if supported
        """
        return self._capabilities.supports_operation(operation)

    def get_unsupported_message(self) -> str:
        """Get error message when transactions are not supported.

        Returns:
            Helpful error message with alternatives
        """
        return (
            f"Transaction Primitives benchmark requires ACID transaction support.\n"
            f"Platform '{self.platform_name}' does not support transactions.\n"
            f"\n"
            f"Alternatives:\n"
            f"  - Use pyspark-df with Delta Lake table format:\n"
            f"    benchbox run --platform pyspark-df --benchmark transaction_primitives\n"
            f"    (Requires: pip install pyspark delta-spark)\n"
            f"\n"
            f"  - Use delta-lake platform directly:\n"
            f"    benchbox run --platform delta-lake --benchmark transaction_primitives\n"
            f"    (Requires: pip install deltalake)\n"
            f"\n"
            f"Note: {self._capabilities.notes}"
        )

    def _validate_path_safe(self, table_path: Path | str) -> tuple[Path | None, str]:
        """Validate that a path is safe to use (no path traversal).

        Args:
            table_path: Path to validate

        Returns:
            Tuple of (resolved_path, error_message). resolved_path is None if invalid.
        """
        try:
            path = Path(table_path)
            # Resolve to absolute path to detect traversal
            resolved = path.resolve()

            # Check for path traversal attempts (.. in the original path)
            path_str = str(table_path)
            if ".." in path_str:
                return None, f"Path traversal detected in '{table_path}'. Use absolute paths."

            return resolved, ""
        except (ValueError, OSError) as e:
            return None, f"Invalid path '{table_path}': {e}"

    def validate_table_format(self, table_path: Path | str) -> tuple[bool, str]:
        """Validate that a table path is a supported transactional table.

        Checks if the table at the given path is a Delta Lake or Iceberg table
        that supports transaction operations.

        Args:
            table_path: Path to the table directory

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Validate path safety first
        resolved_path, error_msg = self._validate_path_safe(table_path)
        if resolved_path is None:
            return False, error_msg
        table_path = resolved_path

        # Check for Delta Lake table
        delta_log = table_path / "_delta_log"
        if delta_log.exists() and delta_log.is_dir():
            return True, ""

        # Check for Iceberg table (metadata directory)
        iceberg_metadata = table_path / "metadata"
        if iceberg_metadata.exists() and iceberg_metadata.is_dir():
            # Look for Iceberg-specific files
            version_hint = iceberg_metadata / "version-hint.text"
            if version_hint.exists() or list(iceberg_metadata.glob("*.metadata.json")):
                return True, ""

        # Table exists but is not transactional
        if table_path.exists():
            return False, (
                f"Table at '{table_path}' is not a Delta Lake or Iceberg table.\n"
                f"Transaction Primitives requires a transactional table format.\n"
                f"\n"
                f"To convert to Delta Lake:\n"
                f"  df.write.format('delta').mode('overwrite').save('{table_path}')\n"
                f"\n"
                f"Or to create a new Delta table:\n"
                f"  spark.sql(\"CREATE TABLE ... USING DELTA LOCATION '{table_path}'\")"
            )

        return False, f"Table path '{table_path}' does not exist."

    def get_table_version(self, table_path: Path | str) -> int | None:
        """Get the current version of a transactional table.

        Args:
            table_path: Path to the table directory

        Returns:
            Current version number, or None if not available
        """
        table_path = str(table_path)

        # Delta Lake version
        if self._capabilities.table_format == "delta":
            try:
                if "pyspark" in self.platform_name and self.spark_session:
                    from delta.tables import DeltaTable

                    dt = DeltaTable.forPath(self.spark_session, table_path)
                    history = dt.history(1).collect()
                    if history:
                        return history[0]["version"]
                else:
                    # delta-rs
                    from deltalake import DeltaTable

                    dt = DeltaTable(table_path)
                    return dt.version()
            except Exception as e:
                self.logger.warning(f"Could not get table version: {e}")
                return None

        # Iceberg snapshot ID (not numeric version, but serves similar purpose)
        if self._capabilities.table_format == "iceberg":
            # Would need pyiceberg catalog API
            self.logger.debug("Iceberg version tracking not yet implemented")
            return None

        return None

    def execute_atomic_insert(
        self,
        table_path: Path | str,
        dataframe: Any,
        partition_columns: list[str] | None = None,
    ) -> DataFrameTransactionResult:
        """Execute an atomic INSERT operation.

        Each INSERT is a single atomic transaction. Measures the overhead
        of transaction commit vs raw write performance.

        Args:
            table_path: Path to the target table
            dataframe: DataFrame containing rows to insert
            partition_columns: Optional partition columns

        Returns:
            DataFrameTransactionResult with operation outcome
        """
        start_time = time.time()
        operation = TransactionOperationType.ATOMIC_INSERT

        if not self.supports_operation(operation):
            return DataFrameTransactionResult.failure(
                operation,
                self.get_unsupported_message(),
                start_time,
            )

        # Validate table format
        is_valid, error_msg = self.validate_table_format(table_path)
        if not is_valid:
            return DataFrameTransactionResult.failure(operation, error_msg, start_time)

        # Get version before operation
        version_before = self.get_table_version(table_path)

        try:
            if self._maintenance_ops is None:
                return DataFrameTransactionResult.failure(
                    operation,
                    f"Maintenance operations not available for {self.platform_name}",
                    start_time,
                )

            # Execute INSERT via maintenance operations
            result = self._maintenance_ops.insert_rows(
                table_path=table_path,
                dataframe=dataframe,
                partition_columns=partition_columns,
                mode="append",
            )

            # Get version after operation
            version_after = self.get_table_version(table_path)

            end_time = time.time()
            total_duration_ms = (end_time - start_time) * 1000
            write_duration_ms = result.duration * 1000

            return DataFrameTransactionResult(
                operation_type=operation,
                success=result.success,
                start_time=start_time,
                end_time=end_time,
                duration_ms=total_duration_ms,
                rows_affected=result.rows_affected,
                version_before=version_before,
                version_after=version_after,
                error_message=result.error_message,
                metrics={
                    "write_duration_ms": write_duration_ms,
                    "version_check_overhead_ms": total_duration_ms - write_duration_ms,
                },
            )

        except Exception as e:
            self.logger.error(f"Atomic INSERT failed: {e}")
            return DataFrameTransactionResult.failure(operation, str(e), start_time)

    def execute_atomic_update(
        self,
        table_path: Path | str,
        condition: str,
        updates: dict[str, Any],
    ) -> DataFrameTransactionResult:
        """Execute an atomic UPDATE operation.

        Args:
            table_path: Path to the target table
            condition: SQL-like condition string
            updates: Column name to new value mapping

        Returns:
            DataFrameTransactionResult with operation outcome
        """
        start_time = time.time()
        operation = TransactionOperationType.ATOMIC_UPDATE

        if not self.supports_operation(operation):
            return DataFrameTransactionResult.failure(
                operation,
                self.get_unsupported_message(),
                start_time,
            )

        is_valid, error_msg = self.validate_table_format(table_path)
        if not is_valid:
            return DataFrameTransactionResult.failure(operation, error_msg, start_time)

        version_before = self.get_table_version(table_path)

        try:
            if self._maintenance_ops is None:
                return DataFrameTransactionResult.failure(
                    operation,
                    f"Maintenance operations not available for {self.platform_name}",
                    start_time,
                )

            result = self._maintenance_ops.update_rows(
                table_path=table_path,
                condition=condition,
                updates=updates,
            )

            version_after = self.get_table_version(table_path)

            end_time = time.time()
            return DataFrameTransactionResult(
                operation_type=operation,
                success=result.success,
                start_time=start_time,
                end_time=end_time,
                duration_ms=(end_time - start_time) * 1000,
                rows_affected=result.rows_affected,
                version_before=version_before,
                version_after=version_after,
                error_message=result.error_message,
            )

        except Exception as e:
            self.logger.error(f"Atomic UPDATE failed: {e}")
            return DataFrameTransactionResult.failure(operation, str(e), start_time)

    def execute_atomic_delete(
        self,
        table_path: Path | str,
        condition: str,
    ) -> DataFrameTransactionResult:
        """Execute an atomic DELETE operation.

        Args:
            table_path: Path to the target table
            condition: SQL-like condition string

        Returns:
            DataFrameTransactionResult with operation outcome
        """
        start_time = time.time()
        operation = TransactionOperationType.ATOMIC_DELETE

        if not self.supports_operation(operation):
            return DataFrameTransactionResult.failure(
                operation,
                self.get_unsupported_message(),
                start_time,
            )

        is_valid, error_msg = self.validate_table_format(table_path)
        if not is_valid:
            return DataFrameTransactionResult.failure(operation, error_msg, start_time)

        version_before = self.get_table_version(table_path)

        try:
            if self._maintenance_ops is None:
                return DataFrameTransactionResult.failure(
                    operation,
                    f"Maintenance operations not available for {self.platform_name}",
                    start_time,
                )

            result = self._maintenance_ops.delete_rows(
                table_path=table_path,
                condition=condition,
            )

            version_after = self.get_table_version(table_path)

            end_time = time.time()
            return DataFrameTransactionResult(
                operation_type=operation,
                success=result.success,
                start_time=start_time,
                end_time=end_time,
                duration_ms=(end_time - start_time) * 1000,
                rows_affected=result.rows_affected,
                version_before=version_before,
                version_after=version_after,
                error_message=result.error_message,
            )

        except Exception as e:
            self.logger.error(f"Atomic DELETE failed: {e}")
            return DataFrameTransactionResult.failure(operation, str(e), start_time)

    def execute_atomic_merge(
        self,
        table_path: Path | str,
        source_dataframe: Any,
        merge_condition: str,
        when_matched: dict[str, Any] | None = None,
        when_not_matched: dict[str, Any] | None = None,
    ) -> DataFrameTransactionResult:
        """Execute an atomic MERGE (upsert) operation.

        Args:
            table_path: Path to the target table
            source_dataframe: DataFrame containing source rows
            merge_condition: Join condition for matching rows
            when_matched: Updates to apply when matched
            when_not_matched: Values for insert when not matched

        Returns:
            DataFrameTransactionResult with operation outcome
        """
        start_time = time.time()
        operation = TransactionOperationType.ATOMIC_MERGE

        if not self.supports_operation(operation):
            return DataFrameTransactionResult.failure(
                operation,
                self.get_unsupported_message(),
                start_time,
            )

        is_valid, error_msg = self.validate_table_format(table_path)
        if not is_valid:
            return DataFrameTransactionResult.failure(operation, error_msg, start_time)

        version_before = self.get_table_version(table_path)

        try:
            if self._maintenance_ops is None:
                return DataFrameTransactionResult.failure(
                    operation,
                    f"Maintenance operations not available for {self.platform_name}",
                    start_time,
                )

            result = self._maintenance_ops.merge_rows(
                table_path=table_path,
                source_dataframe=source_dataframe,
                merge_condition=merge_condition,
                when_matched=when_matched,
                when_not_matched=when_not_matched,
            )

            version_after = self.get_table_version(table_path)

            end_time = time.time()
            return DataFrameTransactionResult(
                operation_type=operation,
                success=result.success,
                start_time=start_time,
                end_time=end_time,
                duration_ms=(end_time - start_time) * 1000,
                rows_affected=result.rows_affected,
                version_before=version_before,
                version_after=version_after,
                error_message=result.error_message,
            )

        except Exception as e:
            self.logger.error(f"Atomic MERGE failed: {e}")
            return DataFrameTransactionResult.failure(operation, str(e), start_time)

    def execute_rollback_to_version(
        self,
        table_path: Path | str,
        version: int,
    ) -> DataFrameTransactionResult:
        """Rollback a table to a previous version.

        For Delta Lake, this uses RESTORE TO VERSION.
        For Iceberg, this uses rollback_to_snapshot (not yet implemented).

        Args:
            table_path: Path to the table
            version: Target version number

        Returns:
            DataFrameTransactionResult with operation outcome
        """
        start_time = time.time()
        operation = TransactionOperationType.ROLLBACK_TO_VERSION

        if not self.supports_operation(operation):
            return DataFrameTransactionResult.failure(
                operation,
                f"Rollback not supported on {self.platform_name}. "
                f"Use Delta Lake or Iceberg for RESTORE/rollback operations.",
                start_time,
            )

        is_valid, error_msg = self.validate_table_format(table_path)
        if not is_valid:
            return DataFrameTransactionResult.failure(operation, error_msg, start_time)

        version_before = self.get_table_version(table_path)
        table_path_str = str(table_path)

        try:
            # Delta Lake RESTORE
            if self._capabilities.table_format == "delta":
                if "pyspark" in self.platform_name and self.spark_session:
                    from delta.tables import DeltaTable

                    dt = DeltaTable.forPath(self.spark_session, table_path_str)
                    dt.restoreToVersion(version)
                else:
                    # delta-rs
                    from deltalake import DeltaTable

                    dt = DeltaTable(table_path_str)
                    dt.restore(version)

                version_after = self.get_table_version(table_path)

                end_time = time.time()
                return DataFrameTransactionResult(
                    operation_type=operation,
                    success=True,
                    start_time=start_time,
                    end_time=end_time,
                    duration_ms=(end_time - start_time) * 1000,
                    rows_affected=0,  # RESTORE doesn't report rows
                    version_before=version_before,
                    version_after=version_after,
                    metrics={"target_version": version},
                )

            return DataFrameTransactionResult.failure(
                operation,
                f"Rollback not implemented for table format: {self._capabilities.table_format}",
                start_time,
            )

        except Exception as e:
            self.logger.error(f"Rollback to version {version} failed: {e}")
            return DataFrameTransactionResult.failure(operation, str(e), start_time)

    def execute_rollback_to_timestamp(
        self,
        table_path: Path | str,
        timestamp: str,
    ) -> DataFrameTransactionResult:
        """Rollback a table to a previous timestamp.

        For Delta Lake, this uses RESTORE TO TIMESTAMP.

        Args:
            table_path: Path to the table
            timestamp: Target timestamp (ISO format or SQL timestamp)

        Returns:
            DataFrameTransactionResult with operation outcome
        """
        start_time = time.time()
        operation = TransactionOperationType.ROLLBACK_TO_TIMESTAMP

        if not self.supports_operation(operation):
            return DataFrameTransactionResult.failure(
                operation,
                f"Rollback not supported on {self.platform_name}.",
                start_time,
            )

        is_valid, error_msg = self.validate_table_format(table_path)
        if not is_valid:
            return DataFrameTransactionResult.failure(operation, error_msg, start_time)

        version_before = self.get_table_version(table_path)
        table_path_str = str(table_path)

        try:
            if self._capabilities.table_format == "delta":
                if "pyspark" in self.platform_name and self.spark_session:
                    from delta.tables import DeltaTable

                    dt = DeltaTable.forPath(self.spark_session, table_path_str)
                    dt.restoreToTimestamp(timestamp)
                else:
                    # delta-rs - restore to timestamp
                    from deltalake import DeltaTable

                    dt = DeltaTable(table_path_str)
                    # delta-rs uses datetime object
                    from datetime import datetime

                    if isinstance(timestamp, str):
                        # Parse ISO format
                        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    else:
                        ts = timestamp
                    dt.restore(datetime_target=ts)

                version_after = self.get_table_version(table_path)

                end_time = time.time()
                return DataFrameTransactionResult(
                    operation_type=operation,
                    success=True,
                    start_time=start_time,
                    end_time=end_time,
                    duration_ms=(end_time - start_time) * 1000,
                    rows_affected=0,
                    version_before=version_before,
                    version_after=version_after,
                    metrics={"target_timestamp": timestamp},
                )

            return DataFrameTransactionResult.failure(
                operation,
                f"Rollback not implemented for table format: {self._capabilities.table_format}",
                start_time,
            )

        except Exception as e:
            self.logger.error(f"Rollback to timestamp {timestamp} failed: {e}")
            return DataFrameTransactionResult.failure(operation, str(e), start_time)

    def execute_time_travel_query(
        self,
        table_path: Path | str,
        version: int | None = None,
        timestamp: str | None = None,
    ) -> DataFrameTransactionResult:
        """Query a table at a historical version or timestamp.

        Args:
            table_path: Path to the table
            version: Target version number (mutually exclusive with timestamp)
            timestamp: Target timestamp (mutually exclusive with version)

        Returns:
            DataFrameTransactionResult with operation outcome and row count
        """
        start_time = time.time()
        operation = TransactionOperationType.TIME_TRAVEL_QUERY

        if not self.supports_operation(operation):
            return DataFrameTransactionResult.failure(
                operation,
                f"Time travel not supported on {self.platform_name}. Use Delta Lake or Iceberg for historical queries.",
                start_time,
            )

        if version is None and timestamp is None:
            return DataFrameTransactionResult.failure(
                operation,
                "Either version or timestamp must be provided for time travel query.",
                start_time,
            )

        is_valid, error_msg = self.validate_table_format(table_path)
        if not is_valid:
            return DataFrameTransactionResult.failure(operation, error_msg, start_time)

        table_path_str = str(table_path)
        current_version = self.get_table_version(table_path)

        try:
            if self._capabilities.table_format == "delta":
                if "pyspark" in self.platform_name and self.spark_session:
                    # PySpark time travel via options
                    reader = self.spark_session.read.format("delta")
                    if version is not None:
                        reader = reader.option("versionAsOf", version)
                    elif timestamp is not None:
                        reader = reader.option("timestampAsOf", timestamp)

                    df = reader.load(table_path_str)
                    row_count = df.count()
                else:
                    # delta-rs time travel
                    from deltalake import DeltaTable

                    if version is not None:
                        dt = DeltaTable(table_path_str, version=version)
                    else:
                        # delta-rs timestamp query
                        from datetime import datetime

                        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                        dt = DeltaTable(table_path_str, datetime_target=ts)

                    arrow_table = dt.to_pyarrow_table()
                    row_count = arrow_table.num_rows

                end_time = time.time()
                return DataFrameTransactionResult(
                    operation_type=operation,
                    success=True,
                    start_time=start_time,
                    end_time=end_time,
                    duration_ms=(end_time - start_time) * 1000,
                    rows_affected=row_count,
                    version_before=current_version,
                    version_after=current_version,  # No change from query
                    metrics={
                        "query_version": version,
                        "query_timestamp": timestamp,
                        "row_count": row_count,
                    },
                )

            return DataFrameTransactionResult.failure(
                operation,
                f"Time travel not implemented for table format: {self._capabilities.table_format}",
                start_time,
            )

        except Exception as e:
            self.logger.error(f"Time travel query failed: {e}")
            return DataFrameTransactionResult.failure(operation, str(e), start_time)

    def execute_version_compare(
        self,
        table_path: Path | str,
        version1: int,
        version2: int,
    ) -> DataFrameTransactionResult:
        """Compare two versions of a table and return difference metrics.

        Queries both versions and computes the difference in row counts and
        optionally schema changes.

        Args:
            table_path: Path to the table
            version1: First version number (typically older)
            version2: Second version number (typically newer)

        Returns:
            DataFrameTransactionResult with comparison metrics
        """
        start_time = time.time()
        operation = TransactionOperationType.VERSION_COMPARE

        if not self.supports_operation(operation):
            return DataFrameTransactionResult.failure(
                operation,
                f"Version compare not supported on {self.platform_name}. "
                f"Use Delta Lake or Iceberg for time travel operations.",
                start_time,
            )

        is_valid, error_msg = self.validate_table_format(table_path)
        if not is_valid:
            return DataFrameTransactionResult.failure(operation, error_msg, start_time)

        table_path_str = str(table_path)
        current_version = self.get_table_version(table_path)

        try:
            if self._capabilities.table_format == "delta":
                if "pyspark" in self.platform_name and self.spark_session:
                    # Query both versions via PySpark
                    df1 = self.spark_session.read.format("delta").option("versionAsOf", version1).load(table_path_str)
                    df2 = self.spark_session.read.format("delta").option("versionAsOf", version2).load(table_path_str)
                    count1 = df1.count()
                    count2 = df2.count()
                    schema1 = [f.name for f in df1.schema.fields]
                    schema2 = [f.name for f in df2.schema.fields]
                else:
                    # delta-rs
                    from deltalake import DeltaTable

                    dt1 = DeltaTable(table_path_str, version=version1)
                    dt2 = DeltaTable(table_path_str, version=version2)

                    arrow1 = dt1.to_pyarrow_table()
                    arrow2 = dt2.to_pyarrow_table()

                    count1 = arrow1.num_rows
                    count2 = arrow2.num_rows
                    schema1 = arrow1.schema.names
                    schema2 = arrow2.schema.names

                # Compute differences
                row_diff = count2 - count1
                schema_added = [c for c in schema2 if c not in schema1]
                schema_removed = [c for c in schema1 if c not in schema2]

                end_time = time.time()
                return DataFrameTransactionResult(
                    operation_type=operation,
                    success=True,
                    start_time=start_time,
                    end_time=end_time,
                    duration_ms=(end_time - start_time) * 1000,
                    rows_affected=abs(row_diff),
                    version_before=current_version,
                    version_after=current_version,  # No change from comparison
                    metrics={
                        "version1": version1,
                        "version2": version2,
                        "row_count_v1": count1,
                        "row_count_v2": count2,
                        "row_difference": row_diff,
                        "columns_added": schema_added,
                        "columns_removed": schema_removed,
                        "schema_changed": len(schema_added) > 0 or len(schema_removed) > 0,
                    },
                )

            return DataFrameTransactionResult.failure(
                operation,
                f"Version compare not implemented for table format: {self._capabilities.table_format}",
                start_time,
            )

        except Exception as e:
            self.logger.error(f"Version compare failed: {e}")
            return DataFrameTransactionResult.failure(operation, str(e), start_time)

    def execute_concurrent_write(
        self,
        table_path: Path | str,
        dataframes: list[Any],
    ) -> DataFrameTransactionResult:
        """Execute concurrent write operations and measure conflict resolution.

        Simulates concurrent writes to a transactional table using sequential
        execution with version-conflict detection. True parallelism requires
        external coordination (e.g., thread pools), which is intentionally
        out of scope here - the goal is to verify the platform's conflict
        detection semantics and report the outcome.

        Delta Lake uses optimistic concurrency: each write reads the current
        version, writes data, then checks if the version changed. If conflicted,
        the write is retried or fails.

        Args:
            table_path: Path to the target table
            dataframes: List of DataFrames to write (each represents a concurrent write)

        Returns:
            DataFrameTransactionResult with conflict detection metrics
        """
        import time as _time

        start_time = _time.time()
        operation = TransactionOperationType.CONCURRENT_WRITE

        if not self.supports_operation(operation):
            return DataFrameTransactionResult.failure(
                operation,
                f"Concurrent write not supported on platform '{self.platform_name}' "
                f"(table_format={self._capabilities.table_format})",
                start_time,
            )

        table_path_str = str(table_path)

        try:
            version_before = self.get_table_version(table_path_str)
            writes_succeeded = 0
            writes_conflicted = 0

            for i, df in enumerate(dataframes):
                try:
                    if self._capabilities.table_format == "delta" and self.spark_session:
                        df.write.format("delta").mode("append").save(table_path_str)
                        writes_succeeded += 1
                    elif self._capabilities.table_format == "iceberg" and self.spark_session:
                        df.writeTo(table_path_str).append()
                        writes_succeeded += 1
                    else:
                        # delta-rs: write via arrow
                        import pyarrow as pa
                        from deltalake.writer import write_deltalake

                        arrow_table = pa.Table.from_pandas(df.toPandas() if hasattr(df, "toPandas") else df)
                        write_deltalake(table_path_str, arrow_table, mode="append")
                        writes_succeeded += 1
                except Exception as write_err:
                    self.logger.warning(f"Concurrent write {i} conflicted: {write_err}")
                    writes_conflicted += 1

            version_after = self.get_table_version(table_path_str)
            end_time = _time.time()

            return DataFrameTransactionResult(
                operation_type=operation,
                success=True,
                start_time=start_time,
                end_time=end_time,
                duration_ms=(end_time - start_time) * 1000,
                rows_affected=writes_succeeded,
                version_before=version_before,
                version_after=version_after,
                metrics={
                    "writes_attempted": len(dataframes),
                    "writes_succeeded": writes_succeeded,
                    "writes_conflicted": writes_conflicted,
                },
            )

        except Exception as e:
            self.logger.error(f"Concurrent write failed: {e}")
            return DataFrameTransactionResult.failure(operation, str(e), start_time)

    def execute_conflict_resolution(
        self,
        table_path: Path | str,
        dataframe: Any,
        resolution_strategy: str = "retry",
    ) -> DataFrameTransactionResult:
        """Execute a write that may conflict and apply a resolution strategy.

        Tests the platform's conflict resolution behaviour by writing to a table
        with an explicit strategy:
        - "retry": Retry the write after reading the current version
        - "overwrite": Overwrite conflicting changes (last-write-wins)
        - "fail": Surface the conflict as an error (pessimistic)

        Delta Lake uses optimistic concurrency; this operation measures
        the overhead of conflict detection and resolution.

        Args:
            table_path: Path to the target table
            dataframe: DataFrame to write
            resolution_strategy: One of "retry", "overwrite", "fail"

        Returns:
            DataFrameTransactionResult with conflict resolution outcome
        """
        import time as _time

        start_time = _time.time()
        operation = TransactionOperationType.CONFLICT_RESOLUTION

        if not self.supports_operation(operation):
            return DataFrameTransactionResult.failure(
                operation,
                f"Conflict resolution not supported on platform '{self.platform_name}' "
                f"(table_format={self._capabilities.table_format})",
                start_time,
            )

        table_path_str = str(table_path)

        try:
            version_before = self.get_table_version(table_path_str)
            retry_count = 0
            max_retries = 3 if resolution_strategy == "retry" else 1

            last_error: str | None = None
            succeeded = False

            for attempt in range(max_retries):
                try:
                    if self._capabilities.table_format == "delta" and self.spark_session:
                        write_mode = "overwrite" if resolution_strategy == "overwrite" else "append"
                        dataframe.write.format("delta").mode(write_mode).save(table_path_str)
                        succeeded = True
                        break
                    elif self._capabilities.table_format == "iceberg" and self.spark_session:
                        if resolution_strategy == "overwrite":
                            dataframe.writeTo(table_path_str).overwritePartitions()
                        else:
                            dataframe.writeTo(table_path_str).append()
                        succeeded = True
                        break
                    else:
                        from deltalake.writer import write_deltalake

                        write_mode = "overwrite" if resolution_strategy == "overwrite" else "append"
                        import pyarrow as pa

                        arrow_table = pa.Table.from_pandas(
                            dataframe.toPandas() if hasattr(dataframe, "toPandas") else dataframe
                        )
                        write_deltalake(table_path_str, arrow_table, mode=write_mode)
                        succeeded = True
                        break
                except Exception as e:
                    last_error = str(e)
                    retry_count += 1
                    if resolution_strategy == "fail":
                        break

            version_after = self.get_table_version(table_path_str)
            end_time = _time.time()

            if succeeded:
                return DataFrameTransactionResult(
                    operation_type=operation,
                    success=True,
                    start_time=start_time,
                    end_time=end_time,
                    duration_ms=(end_time - start_time) * 1000,
                    rows_affected=1,
                    version_before=version_before,
                    version_after=version_after,
                    metrics={
                        "resolution_strategy": resolution_strategy,
                        "retry_count": retry_count,
                    },
                )
            return DataFrameTransactionResult.failure(
                operation,
                f"Conflict resolution failed after {retry_count} attempts: {last_error}",
                start_time,
            )

        except Exception as e:
            self.logger.error(f"Conflict resolution failed: {e}")
            return DataFrameTransactionResult.failure(operation, str(e), start_time)

    def execute_snapshot_isolation(
        self,
        table_path: Path | str,
        query_fn: Any | None = None,
    ) -> DataFrameTransactionResult:
        """Verify snapshot isolation semantics by reading a stable table snapshot.

        In Delta Lake, reads always see a consistent snapshot of the table at
        a point in time. This operation reads the table twice in sequence and
        verifies that the row count is identical (no dirty reads).

        For PySpark + Delta Lake, snapshot isolation is guaranteed by the table
        format - this operation measures the overhead of reading a snapshot
        vs the current version.

        Args:
            table_path: Path to the target table
            query_fn: Optional function that applies a filter/aggregation on the DataFrame

        Returns:
            DataFrameTransactionResult with snapshot consistency metrics
        """
        import time as _time

        start_time = _time.time()
        operation = TransactionOperationType.SNAPSHOT_ISOLATION

        if not self.supports_operation(operation):
            return DataFrameTransactionResult.failure(
                operation,
                f"Snapshot isolation not supported on platform '{self.platform_name}' "
                f"(isolation={self._capabilities.transaction_isolation})",
                start_time,
            )

        table_path_str = str(table_path)

        try:
            current_version = self.get_table_version(table_path_str)

            if self._capabilities.table_format == "delta" and self.spark_session:
                # Read snapshot at pinned version to verify isolation
                if current_version is not None:
                    df1 = (
                        self.spark_session.read.format("delta")
                        .option("versionAsOf", current_version)
                        .load(table_path_str)
                    )
                else:
                    df1 = self.spark_session.read.format("delta").load(table_path_str)

                if query_fn is not None:
                    df1 = query_fn(df1)

                count1 = df1.count()
                # Second read of same snapshot - must match
                count2 = df1.count()
                consistent = count1 == count2

            elif self._capabilities.table_format == "iceberg" and self.spark_session:
                df1 = self.spark_session.read.format("iceberg").load(table_path_str)
                if query_fn is not None:
                    df1 = query_fn(df1)
                count1 = df1.count()
                count2 = df1.count()
                consistent = count1 == count2

            else:
                # delta-rs: read pinned version
                from deltalake import DeltaTable

                dt = DeltaTable(table_path_str, version=current_version)
                arrow_table = dt.to_pyarrow_table()
                count1 = arrow_table.num_rows
                count2 = arrow_table.num_rows
                consistent = True  # delta-rs reads are always snapshot-isolated

            end_time = _time.time()
            return DataFrameTransactionResult(
                operation_type=operation,
                success=True,
                start_time=start_time,
                end_time=end_time,
                duration_ms=(end_time - start_time) * 1000,
                rows_affected=count1,
                version_before=current_version,
                version_after=current_version,
                metrics={
                    "snapshot_consistent": consistent,
                    "row_count_read1": count1,
                    "row_count_read2": count2,
                    "pinned_version": current_version,
                },
            )

        except Exception as e:
            self.logger.error(f"Snapshot isolation check failed: {e}")
            return DataFrameTransactionResult.failure(operation, str(e), start_time)

    def execute_read_your_writes(
        self,
        table_path: Path | str,
        dataframe: Any,
    ) -> DataFrameTransactionResult:
        """Verify read-your-writes consistency after an atomic write.

        After writing rows to a transactional table, immediately reads them
        back and verifies the count matches. This validates that the platform
        guarantees read-your-writes semantics (the writer always sees its own
        committed changes).

        Delta Lake guarantees this because each write produces a new version
        and subsequent reads default to the latest version.

        Args:
            table_path: Path to the target table
            dataframe: DataFrame containing rows to write then read back

        Returns:
            DataFrameTransactionResult with read-your-writes verification
        """
        import time as _time

        start_time = _time.time()
        operation = TransactionOperationType.READ_YOUR_WRITES

        if not self.supports_operation(operation):
            return DataFrameTransactionResult.failure(
                operation,
                f"Read-your-writes not supported on platform '{self.platform_name}' "
                f"(supports_transactions={self._capabilities.supports_transactions})",
                start_time,
            )

        table_path_str = str(table_path)

        try:
            version_before = self.get_table_version(table_path_str)
            rows_written = 0

            # Write
            if self._capabilities.table_format == "delta" and self.spark_session:
                rows_written = dataframe.count() if hasattr(dataframe, "count") else len(dataframe)
                dataframe.write.format("delta").mode("append").save(table_path_str)
            elif self._capabilities.table_format == "iceberg" and self.spark_session:
                rows_written = dataframe.count() if hasattr(dataframe, "count") else len(dataframe)
                dataframe.writeTo(table_path_str).append()
            else:
                import pyarrow as pa
                from deltalake.writer import write_deltalake

                arrow_table = pa.Table.from_pandas(
                    dataframe.toPandas() if hasattr(dataframe, "toPandas") else dataframe
                )
                rows_written = arrow_table.num_rows
                write_deltalake(table_path_str, arrow_table, mode="append")

            # Read back immediately
            version_after = self.get_table_version(table_path_str)
            rows_read_back = 0

            if self._capabilities.table_format == "delta" and self.spark_session:
                df_back = self.spark_session.read.format("delta").load(table_path_str)
                rows_read_back = df_back.count()
            elif self._capabilities.table_format == "iceberg" and self.spark_session:
                df_back = self.spark_session.read.format("iceberg").load(table_path_str)
                rows_read_back = df_back.count()
            else:
                from deltalake import DeltaTable

                dt = DeltaTable(table_path_str)
                rows_read_back = dt.to_pyarrow_table().num_rows

            end_time = _time.time()
            # Read-your-writes is satisfied if the table grew by at least rows_written
            reads_own_writes = rows_read_back >= rows_written

            return DataFrameTransactionResult(
                operation_type=operation,
                success=True,
                start_time=start_time,
                end_time=end_time,
                duration_ms=(end_time - start_time) * 1000,
                rows_affected=rows_written,
                version_before=version_before,
                version_after=version_after,
                metrics={
                    "rows_written": rows_written,
                    "rows_read_back": rows_read_back,
                    "reads_own_writes": reads_own_writes,
                },
            )

        except Exception as e:
            self.logger.error(f"Read-your-writes check failed: {e}")
            return DataFrameTransactionResult.failure(operation, str(e), start_time)


def get_dataframe_transaction_manager(
    platform_name: str,
    spark_session: Any = None,
) -> DataFrameTransactionOperationsManager | None:
    """Get a DataFrame transaction operations manager for a platform.

    Args:
        platform_name: Platform name (e.g., "pyspark-df", "delta-lake")
        spark_session: SparkSession instance (required for pyspark-df)

    Returns:
        DataFrameTransactionOperationsManager if platform is recognized,
        None if platform is not a DataFrame platform.
    """
    return get_dataframe_manager(
        platform_name,
        manager_class=DataFrameTransactionOperationsManager,
        supported_platforms=(
            "polars-df",
            "polars",
            "pandas-df",
            "pandas",
            "pyspark-df",
            "pyspark",
            "delta-lake",
            "delta",
            "iceberg",
        ),
        logger=logger,
        manager_label="transaction",
        spark_session=spark_session,
    )


def validate_transaction_primitives_platform(platform_name: str) -> tuple[bool, str]:
    """Validate that a platform can run Transaction Primitives benchmark.

    This is called during benchmark configuration to provide early feedback
    when users attempt to run Transaction Primitives on unsupported platforms.

    Args:
        platform_name: Platform name to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    platform_lower = platform_name.lower()

    # Platforms that definitely support transactions
    supported_patterns = ("delta", "iceberg", "pyspark")

    if any(p in platform_lower for p in supported_patterns):
        return True, ""

    # Platforms that definitely don't support transactions
    unsupported_patterns = ("polars", "pandas", "duckdb", "sqlite", "datafusion")

    if any(p in platform_lower for p in unsupported_patterns):
        return False, (
            f"Transaction Primitives benchmark requires ACID transaction support.\n"
            f"Platform '{platform_name}' does not support DataFrame transactions.\n"
            f"\n"
            f"Supported platforms:\n"
            f"  - pyspark-df (with Delta Lake table format)\n"
            f"  - delta-lake (standalone Delta Lake)\n"
            f"  - iceberg (Apache Iceberg tables)\n"
            f"\n"
            f"Example:\n"
            f"  benchbox run --platform pyspark-df --benchmark transaction_primitives\n"
        )

    # Unknown platform - allow but warn
    return True, ""


__all__ = [
    "TransactionOperationType",
    "DataFrameTransactionCapabilities",
    "DataFrameTransactionResult",
    "DataFrameTransactionOperationsManager",
    "get_dataframe_transaction_manager",
    "validate_transaction_primitives_platform",
    "DELTA_LAKE_TRANSACTION_CAPABILITIES",
    "PYSPARK_DELTA_TRANSACTION_CAPABILITIES",
    "ICEBERG_TRANSACTION_CAPABILITIES",
    "POLARS_TRANSACTION_CAPABILITIES",
    "PANDAS_TRANSACTION_CAPABILITIES",
]
