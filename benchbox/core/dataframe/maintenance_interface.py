"""DataFrame Maintenance Operations Interface.

This module defines the protocol and base classes for DataFrame maintenance operations,
enabling TPC-H and TPC-DS compliance testing on DataFrame platforms like Delta Lake,
Iceberg, and Parquet-based systems.

Architecture:
- DataFrameMaintenanceOperations: Protocol defining maintenance operations
- DataFrameMaintenanceCapabilities: Capabilities declaration for platforms
- MaintenanceResult: Standardized result container

Supported Operation Types:
- INSERT: Add new rows (RF1-like operations)
- UPDATE: Modify existing rows (dimension updates)
- DELETE: Remove rows (RF2-like operations)
- MERGE: Upsert operations (Delta Lake, Iceberg)

Platform Compatibility:
- Delta Lake: Full ACID support, MERGE/UPDATE/DELETE
- Iceberg: Row-level operations, partition-based deletes
- Parquet: File-level append/overwrite (no row-level operations)
- Polars: LazyFrame append, file replacement
- PySpark: Delta Lake or file-based operations

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

try:
    import pyarrow as pa

    PYARROW_AVAILABLE = True
except ImportError:
    pa = None  # type: ignore[assignment]
    PYARROW_AVAILABLE = False

logger = logging.getLogger(__name__)


class MaintenanceOperationType(Enum):
    """Types of maintenance operations supported.

    These operations map to TPC-H RF1/RF2 and TPC-DS DM1-DM4 operations.
    Not all platforms support all operations.
    """

    # Basic operations (all platforms)
    INSERT = "insert"  # RF1: Insert new rows
    DELETE = "delete"  # RF2: Delete rows

    # Advanced operations (ACID-compliant platforms only)
    UPDATE = "update"  # Modify existing rows
    MERGE = "merge"  # Upsert: insert or update

    # Batch operations
    BULK_INSERT = "bulk_insert"  # Large batch insert
    BULK_DELETE = "bulk_delete"  # Partition-based delete

    # Table-format optimization operations (lakehouse tables only)
    OPTIMIZE = "optimize"  # Compaction / clustering (Delta, Hudi)
    VACUUM = "vacuum"  # Reclaim stale files and snapshots (Delta, Iceberg, Hudi)


class TransactionIsolation(Enum):
    """Transaction isolation levels for maintenance operations."""

    NONE = "none"  # No transaction support (file-based)
    READ_COMMITTED = "read_committed"
    REPEATABLE_READ = "repeatable_read"
    SERIALIZABLE = "serializable"
    SNAPSHOT = "snapshot"  # Optimistic concurrency (Delta Lake, Iceberg)


@dataclass
class DataFrameMaintenanceCapabilities:
    """Declares what maintenance operations a DataFrame platform supports.

    Each DataFrame platform adapter should declare its capabilities,
    allowing the runner to validate operations before execution and
    choose appropriate implementation strategies.

    Attributes:
        platform_name: Name of the platform (e.g., "delta-lake", "iceberg")
        supports_insert: Can add new rows
        supports_delete: Can remove rows
        supports_update: Can modify existing rows in place
        supports_merge: Can perform upsert operations
        supports_transactions: Has transaction support for atomicity
        transaction_isolation: Highest isolation level supported
        supports_partitioned_delete: Can delete entire partitions efficiently
        supports_row_level_delete: Can delete individual rows
        supports_time_travel: Can query historical versions
        supports_optimize: Can compact/cluster files (lakehouse tables)
        supports_vacuum: Can reclaim stale files and snapshots
        max_batch_size: Recommended maximum rows per operation
        notes: Additional platform-specific notes
        accepts_sql_predicates: Can consume backend-rendered SQL predicate
            strings and SQL-rendered update values. False when the adapter
            only parses a narrow predicate subset and needs native
            predicate/value operands instead.
    """

    platform_name: str
    supports_insert: bool = True  # Most platforms support append
    supports_delete: bool = False  # Row-level delete requires ACID
    supports_update: bool = False  # In-place update requires ACID
    supports_merge: bool = False  # MERGE requires advanced support
    supports_transactions: bool = False
    transaction_isolation: TransactionIsolation = TransactionIsolation.NONE
    supports_partitioned_delete: bool = False  # File-level deletion
    supports_row_level_delete: bool = False  # Row-level deletion
    supports_time_travel: bool = False
    supports_optimize: bool = False  # File compaction/clustering needs table-format support
    supports_vacuum: bool = False  # Stale-file reclamation needs table-format support
    max_batch_size: int = 100000
    notes: str = ""
    accepts_sql_predicates: bool = True

    def supports_operation(self, operation: MaintenanceOperationType) -> bool:
        """Check if a specific operation type is supported.

        Args:
            operation: The operation type to check

        Returns:
            True if the operation is supported
        """
        mapping = {
            MaintenanceOperationType.INSERT: self.supports_insert,
            MaintenanceOperationType.DELETE: self.supports_delete or self.supports_partitioned_delete,
            MaintenanceOperationType.UPDATE: self.supports_update,
            MaintenanceOperationType.MERGE: self.supports_merge,
            MaintenanceOperationType.BULK_INSERT: self.supports_insert,
            MaintenanceOperationType.BULK_DELETE: self.supports_partitioned_delete,
            MaintenanceOperationType.OPTIMIZE: self.supports_optimize,
            MaintenanceOperationType.VACUUM: self.supports_vacuum,
        }
        return mapping.get(operation, False)

    def validate_tpc_compliance(self) -> tuple[bool, list[str]]:
        """Check if the platform meets TPC maintenance requirements.

        TPC-H requires RF1 (insert) and RF2 (delete).
        TPC-DS requires INSERT, UPDATE, DELETE operations.

        Returns:
            Tuple of (is_compliant, list of missing capabilities)
        """
        issues = []

        # TPC-H minimum requirements
        if not self.supports_insert:
            issues.append("INSERT required for TPC-H RF1")
        if not (self.supports_delete or self.supports_partitioned_delete):
            issues.append("DELETE required for TPC-H RF2")

        # TPC-DS requirements
        if not self.supports_update:
            issues.append("UPDATE required for TPC-DS dimension updates (DM3)")

        return len(issues) == 0, issues


# Pre-defined capability profiles for common platforms
DELTA_LAKE_CAPABILITIES = DataFrameMaintenanceCapabilities(
    platform_name="delta-lake",
    supports_insert=True,
    supports_delete=True,
    supports_update=True,
    supports_merge=True,
    supports_transactions=True,
    transaction_isolation=TransactionIsolation.SNAPSHOT,
    supports_partitioned_delete=True,
    supports_row_level_delete=True,
    supports_time_travel=True,
    supports_optimize=True,  # OPTIMIZE / Z-ORDER via delta-rs
    supports_vacuum=True,  # VACUUM via delta-rs
    max_batch_size=1000000,
    notes="Full ACID compliance via Delta Lake protocol",
)

ICEBERG_CAPABILITIES = DataFrameMaintenanceCapabilities(
    platform_name="iceberg",
    supports_insert=True,
    supports_delete=True,
    supports_update=True,
    supports_merge=True,
    supports_transactions=True,
    transaction_isolation=TransactionIsolation.SNAPSHOT,
    supports_partitioned_delete=True,
    supports_row_level_delete=True,
    supports_time_travel=True,
    supports_optimize=False,  # pyiceberg has no binpack rewrite; use Spark rewrite_data_files
    supports_vacuum=True,  # Snapshot expiration plus orphan-file reclamation on local tables
    max_batch_size=1000000,
    notes="Full ACID compliance via Apache Iceberg",
    # The Iceberg condition parser handles single unquoted comparisons only;
    # callers must pass native predicate/value operands instead of SQL text.
    accepts_sql_predicates=False,
)

HUDI_CAPABILITIES = DataFrameMaintenanceCapabilities(
    platform_name="hudi",
    supports_insert=True,
    supports_delete=True,
    supports_update=True,
    supports_merge=True,
    supports_transactions=True,
    transaction_isolation=TransactionIsolation.SNAPSHOT,
    supports_partitioned_delete=True,
    supports_row_level_delete=True,
    supports_time_travel=True,
    supports_optimize=True,  # run_compaction / run_clustering procedures via Spark SQL
    supports_vacuum=True,  # run_clean procedure via Spark SQL
    max_batch_size=1000000,
    notes=(
        "Full ACID compliance via Apache Hudi. Requires PySpark with hudi-spark-bundle. "
        "All maintenance operations use Spark SQL (no pure Python library like delta-rs/pyiceberg)."
    ),
)

PARQUET_CAPABILITIES = DataFrameMaintenanceCapabilities(
    platform_name="parquet",
    supports_insert=True,  # Append new files
    supports_delete=False,  # No row-level delete
    supports_update=False,  # No in-place update
    supports_merge=False,  # No merge support
    supports_transactions=False,
    transaction_isolation=TransactionIsolation.NONE,
    supports_partitioned_delete=True,  # Can delete partition directories
    supports_row_level_delete=False,
    supports_time_travel=False,
    max_batch_size=10000000,
    notes="File-based operations only. Updates require read-filter-write pattern.",
)

POLARS_CAPABILITIES = DataFrameMaintenanceCapabilities(
    platform_name="polars",
    supports_insert=True,  # Append to Parquet files
    supports_delete=True,  # Read-filter-write pattern
    supports_update=True,  # Read-modify-write pattern
    supports_merge=True,  # Read-join-write pattern
    supports_transactions=False,  # No transaction log
    transaction_isolation=TransactionIsolation.NONE,
    supports_partitioned_delete=True,  # Can manage partition files
    supports_row_level_delete=True,  # Via full table rewrite
    supports_time_travel=False,  # No versioning
    max_batch_size=10000000,
    notes="Full TPC compliance via read-modify-write. RAM-limited; use Delta Lake/Iceberg for large datasets.",
)


@dataclass
class MaintenanceResult:
    """Result of a maintenance operation.

    Provides standardized result reporting across all DataFrame platforms,
    enabling consistent TPC metrics calculation.

    Attributes:
        operation_type: Type of operation performed
        success: Whether the operation completed successfully
        start_time: Operation start timestamp (Unix time)
        end_time: Operation end timestamp (Unix time)
        duration: Operation duration in seconds
        rows_affected: Number of rows inserted/updated/deleted
        error_message: Error description if operation failed
        transaction_id: Platform-specific transaction identifier
        metrics: Additional platform-specific metrics
    """

    operation_type: MaintenanceOperationType
    success: bool
    start_time: float
    end_time: float
    duration: float
    rows_affected: int
    error_message: str | None = None
    transaction_id: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def failure(
        cls,
        operation_type: MaintenanceOperationType,
        error_message: str,
        start_time: float | None = None,
    ) -> MaintenanceResult:
        """Create a failure result.

        Args:
            operation_type: The operation that failed
            error_message: Description of the failure
            start_time: Optional start time (defaults to now)

        Returns:
            MaintenanceResult indicating failure
        """
        now = time.time()
        return cls(
            operation_type=operation_type,
            success=False,
            start_time=start_time or now,
            end_time=now,
            duration=0.0 if start_time is None else (now - start_time),
            rows_affected=0,
            error_message=error_message,
        )


@runtime_checkable
class DataFrameMaintenanceOperations(Protocol):
    """Protocol defining DataFrame maintenance operations.

    This protocol captures the essential maintenance operations needed for
    TPC-H RF1/RF2 and TPC-DS DM1-DM4 compliance on DataFrame platforms.

    Implementations should:
    1. Declare their capabilities via get_capabilities()
    2. Implement supported operations (raise NotImplementedError for unsupported)
    3. Return standardized MaintenanceResult for all operations
    4. Handle batching internally based on platform limits

    Example Implementation:
        class DeltaLakeMaintenanceOperations:
            def get_capabilities(self) -> DataFrameMaintenanceCapabilities:
                return DELTA_LAKE_CAPABILITIES

            def insert_rows(self, table_path, dataframe, ...) -> MaintenanceResult:
                # Delta Lake-specific INSERT implementation
                ...
    """

    def get_capabilities(self) -> DataFrameMaintenanceCapabilities:
        """Return the platform's maintenance capabilities.

        Returns:
            DataFrameMaintenanceCapabilities describing what operations
            this platform supports.
        """
        ...

    def insert_rows(
        self,
        table_path: Path | str,
        dataframe: Any,
        partition_columns: list[str] | None = None,
        mode: str = "append",
    ) -> MaintenanceResult:
        """Insert rows into a table.

        This implements TPC-H RF1-like operations.

        Args:
            table_path: Path to the table/directory
            dataframe: DataFrame containing rows to insert
            partition_columns: Columns to partition by (if applicable)
            mode: Write mode ("append" or "overwrite")

        Returns:
            MaintenanceResult with operation outcome

        Raises:
            NotImplementedError: If INSERT is not supported
        """
        ...

    def delete_rows(
        self,
        table_path: Path | str,
        condition: str | Any,
    ) -> MaintenanceResult:
        """Delete rows matching a condition.

        This implements TPC-H RF2-like operations.

        Args:
            table_path: Path to the table/directory
            condition: Delete condition (SQL string or platform-specific predicate)

        Returns:
            MaintenanceResult with operation outcome

        Raises:
            NotImplementedError: If DELETE is not supported
        """
        ...

    def update_rows(
        self,
        table_path: Path | str,
        condition: str | Any,
        updates: dict[str, Any],
    ) -> MaintenanceResult:
        """Update rows matching a condition.

        This implements TPC-DS dimension update operations.

        Args:
            table_path: Path to the table/directory
            condition: Update condition (SQL string or platform-specific predicate)
            updates: Column name to new value mapping

        Returns:
            MaintenanceResult with operation outcome

        Raises:
            NotImplementedError: If UPDATE is not supported
        """
        ...

    def merge_rows(
        self,
        table_path: Path | str,
        source_dataframe: Any,
        merge_condition: str | Any,
        when_matched: dict[str, Any] | None = None,
        when_not_matched: dict[str, Any] | None = None,
    ) -> MaintenanceResult:
        """Merge (upsert) rows from a source into the target table.

        Implements MERGE semantics: update existing rows if matched,
        insert new rows if not matched.

        Args:
            table_path: Path to the target table
            source_dataframe: DataFrame containing source rows
            merge_condition: Join condition for matching rows
            when_matched: Updates to apply when matched (None = no update)
            when_not_matched: Values for insert when not matched (None = no insert)

        Returns:
            MaintenanceResult with operation outcome

        Raises:
            NotImplementedError: If MERGE is not supported
        """
        ...


@runtime_checkable
class TableFormatOptimizationOperations(Protocol):
    """Protocol for lakehouse compaction, optimization, and vacuum operations.

    This is intentionally separate from DataFrameMaintenanceOperations: only
    table-format backends (Delta Lake, Iceberg, Hudi) can implement it, and
    file-based engines must never be forced to absorb it. Implementations
    return standardized MaintenanceResult values with operation_type
    OPTIMIZE or VACUUM, raise NotImplementedError for unsupported strategies,
    and return MaintenanceResult.failure for execution errors.

    Per-format native support:
    - Delta Lake: OPTIMIZE (compact, z_order) and VACUUM via delta-rs,
      including dry-run vacuum.
    - Iceberg: VACUUM as snapshot expiration
      (table.maintenance.expire_snapshots); OPTIMIZE is not implemented
      because pyiceberg has no binpack rewrite — use Spark
      rewrite_data_files for file layout work.
    - Hudi: OPTIMIZE as run_compaction / run_clustering and VACUUM as
      run_clean, executed as Spark SQL CALL procedures on the operation's
      session. run_clean has no dry-run mode, so dry_run=True raises
      NotImplementedError there.
    """

    def optimize_table(
        self,
        table_path: Path | str,
        *,
        strategy: str = "compact",
        columns: list[str] | None = None,
        partition_filter: Any | None = None,
    ) -> MaintenanceResult:
        """Compact or cluster a table's files.

        Args:
            table_path: Path to the table/directory, or catalog identifier
            strategy: "compact" (binpack small files; Delta, Hudi MOR) or
                "cluster" (locality ordering; Delta z_order, Hudi clustering).
                "z_order" is accepted as an alias of "cluster" on Delta.
            columns: Ordering columns for the "cluster"/"z_order" strategy
                (required there, ignored by "compact")
            partition_filter: Backend-native partition predicate scoping the
                operation (None = whole table)

        Returns:
            MaintenanceResult with operation outcome; native file metrics
            (files added/removed) are carried in metrics and folded into
            rows_affected as documented by each implementation.

        Raises:
            NotImplementedError: If the strategy is unknown or unsupported
        """
        ...

    def vacuum_table(
        self,
        table_path: Path | str,
        *,
        retention_hours: int | None = None,
        dry_run: bool = True,
        enforce_retention: bool = True,
    ) -> MaintenanceResult:
        """Reclaim stale files and snapshots subject to a retention floor.

        Args:
            table_path: Path to the table/directory, or catalog identifier
            retention_hours: Minimum age of data eligible for reclamation
                (None = backend default)
            dry_run: Report reclaimable state without deleting anything.
                Backends whose native vacuum has no dry-run mode (Hudi
                run_clean) raise NotImplementedError when True.
            enforce_retention: Refuse retentions below the backend safety
                floor instead of deleting recent history (Delta enforces a
                168-hour floor unless this is False)

        Returns:
            MaintenanceResult with operation outcome; reclaimed (or, for a
            dry run, reclaimable) paths are carried in metrics.

        Raises:
            NotImplementedError: If dry-run is requested where unsupported
        """
        ...


class BaseDataFrameMaintenanceOperations(ABC):
    """Abstract base class for DataFrame maintenance implementations.

    Provides common functionality for maintenance operations including:
    - Capability checking before operations
    - Timing and result construction
    - Error handling
    - DataFrame type conversion (_convert_to_arrow)
    - Batch processing helpers

    Subclasses must implement:
    - _get_capabilities(): Return platform-specific capabilities
    - _do_insert(): Platform-specific INSERT implementation
    - _do_delete(): Platform-specific DELETE implementation
    - _do_update(): Platform-specific UPDATE implementation (if supported)
    - _do_merge(): Platform-specific MERGE implementation (if supported)
    """

    def __init__(self) -> None:
        """Initialize the maintenance operations handler."""
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._capabilities: DataFrameMaintenanceCapabilities | None = None

    def _convert_to_arrow(self, dataframe: Any) -> Any:
        """Convert various DataFrame types to PyArrow Table.

        This is a shared utility method for converting Polars, Pandas, and other
        DataFrame types to PyArrow format, which is the common interchange format
        for Delta Lake, Iceberg, DuckLake, and other table formats.

        Args:
            dataframe: Input DataFrame (Polars, Pandas, or PyArrow)

        Returns:
            PyArrow Table

        Raises:
            ImportError: If PyArrow is not available
            TypeError: If dataframe type is not supported
        """
        if not PYARROW_AVAILABLE:
            raise ImportError(
                "PyArrow is not installed. Install with: pip install pyarrow\n"
                "PyArrow is required for maintenance operations."
            )

        # Already PyArrow
        if isinstance(dataframe, pa.Table):
            return dataframe

        # Polars DataFrame/LazyFrame
        if hasattr(dataframe, "to_arrow"):
            # Polars LazyFrame needs collection first
            if hasattr(dataframe, "collect"):
                dataframe = dataframe.collect()
            return dataframe.to_arrow()

        # Pandas DataFrame
        if hasattr(dataframe, "to_parquet") and hasattr(dataframe, "columns"):
            return pa.Table.from_pandas(dataframe)

        raise TypeError(
            f"Unsupported DataFrame type: {type(dataframe)}. "
            f"Expected Polars DataFrame, Pandas DataFrame, or PyArrow Table."
        )

    @abstractmethod
    def _get_capabilities(self) -> DataFrameMaintenanceCapabilities:
        """Return platform-specific capabilities.

        Returns:
            DataFrameMaintenanceCapabilities for this platform
        """
        ...

    def get_capabilities(self) -> DataFrameMaintenanceCapabilities:
        """Return the platform's maintenance capabilities (cached).

        Returns:
            DataFrameMaintenanceCapabilities describing what operations
            this platform supports.
        """
        if self._capabilities is None:
            self._capabilities = self._get_capabilities()
        return self._capabilities

    def _check_capability(self, operation: MaintenanceOperationType) -> None:
        """Check if an operation is supported, raise if not.

        Args:
            operation: The operation to check

        Raises:
            NotImplementedError: If the operation is not supported
        """
        caps = self.get_capabilities()
        if not caps.supports_operation(operation):
            raise NotImplementedError(
                f"{caps.platform_name} does not support {operation.value} operations. "
                f"Consider using Delta Lake or Iceberg for full maintenance support."
            )

    @abstractmethod
    def _do_insert(
        self,
        table_path: Path | str,
        dataframe: Any,
        partition_columns: list[str] | None,
        mode: str,
    ) -> int:
        """Platform-specific INSERT implementation.

        Args:
            table_path: Path to the table/directory
            dataframe: DataFrame containing rows to insert
            partition_columns: Columns to partition by
            mode: Write mode

        Returns:
            Number of rows inserted
        """
        ...

    def insert_rows(
        self,
        table_path: Path | str,
        dataframe: Any,
        partition_columns: list[str] | None = None,
        mode: str = "append",
    ) -> MaintenanceResult:
        """Insert rows into a table.

        Args:
            table_path: Path to the table/directory
            dataframe: DataFrame containing rows to insert
            partition_columns: Columns to partition by
            mode: Write mode ("append" or "overwrite")

        Returns:
            MaintenanceResult with operation outcome
        """
        start_time = time.time()
        operation = MaintenanceOperationType.INSERT

        try:
            self._check_capability(operation)
            rows_affected = self._do_insert(table_path, dataframe, partition_columns, mode)

            end_time = time.time()
            return MaintenanceResult(
                operation_type=operation,
                success=True,
                start_time=start_time,
                end_time=end_time,
                duration=end_time - start_time,
                rows_affected=rows_affected,
            )

        except NotImplementedError:
            raise
        except Exception as e:
            self.logger.error(f"INSERT failed: {e}")
            return MaintenanceResult.failure(operation, str(e), start_time)

    @abstractmethod
    def _do_delete(
        self,
        table_path: Path | str,
        condition: str | Any,
    ) -> int:
        """Platform-specific DELETE implementation.

        Args:
            table_path: Path to the table/directory
            condition: Delete condition

        Returns:
            Number of rows deleted
        """
        ...

    def delete_rows(
        self,
        table_path: Path | str,
        condition: str | Any,
    ) -> MaintenanceResult:
        """Delete rows matching a condition.

        Args:
            table_path: Path to the table/directory
            condition: Delete condition

        Returns:
            MaintenanceResult with operation outcome
        """
        start_time = time.time()
        operation = MaintenanceOperationType.DELETE

        try:
            self._check_capability(operation)
            rows_affected = self._do_delete(table_path, condition)

            end_time = time.time()
            return MaintenanceResult(
                operation_type=operation,
                success=True,
                start_time=start_time,
                end_time=end_time,
                duration=end_time - start_time,
                rows_affected=rows_affected,
            )

        except NotImplementedError:
            raise
        except Exception as e:
            self.logger.error(f"DELETE failed: {e}")
            return MaintenanceResult.failure(operation, str(e), start_time)

    def _do_update(
        self,
        table_path: Path | str,
        condition: str | Any,
        updates: dict[str, Any],
    ) -> int:
        """Platform-specific UPDATE implementation.

        Default implementation raises NotImplementedError.
        Override in platforms that support UPDATE.

        Args:
            table_path: Path to the table/directory
            condition: Update condition
            updates: Column updates

        Returns:
            Number of rows updated
        """
        raise NotImplementedError("UPDATE not implemented for this platform")

    def update_rows(
        self,
        table_path: Path | str,
        condition: str | Any,
        updates: dict[str, Any],
    ) -> MaintenanceResult:
        """Update rows matching a condition.

        Args:
            table_path: Path to the table/directory
            condition: Update condition
            updates: Column name to new value mapping

        Returns:
            MaintenanceResult with operation outcome
        """
        start_time = time.time()
        operation = MaintenanceOperationType.UPDATE

        try:
            self._check_capability(operation)
            rows_affected = self._do_update(table_path, condition, updates)

            end_time = time.time()
            return MaintenanceResult(
                operation_type=operation,
                success=True,
                start_time=start_time,
                end_time=end_time,
                duration=end_time - start_time,
                rows_affected=rows_affected,
            )

        except NotImplementedError:
            raise
        except Exception as e:
            self.logger.error(f"UPDATE failed: {e}")
            return MaintenanceResult.failure(operation, str(e), start_time)

    def _do_merge(
        self,
        table_path: Path | str,
        source_dataframe: Any,
        merge_condition: str | Any,
        when_matched: dict[str, Any] | None,
        when_not_matched: dict[str, Any] | None,
    ) -> int:
        """Platform-specific MERGE implementation.

        Default implementation raises NotImplementedError.
        Override in platforms that support MERGE.

        Args:
            table_path: Path to the target table
            source_dataframe: Source DataFrame
            merge_condition: Merge condition
            when_matched: Updates when matched
            when_not_matched: Inserts when not matched

        Returns:
            Number of rows affected
        """
        raise NotImplementedError("MERGE not implemented for this platform")

    def merge_rows(
        self,
        table_path: Path | str,
        source_dataframe: Any,
        merge_condition: str | Any,
        when_matched: dict[str, Any] | None = None,
        when_not_matched: dict[str, Any] | None = None,
    ) -> MaintenanceResult:
        """Merge rows from source into target.

        Args:
            table_path: Path to the target table
            source_dataframe: Source DataFrame
            merge_condition: Join condition for matching
            when_matched: Updates when matched
            when_not_matched: Inserts when not matched

        Returns:
            MaintenanceResult with operation outcome
        """
        start_time = time.time()
        operation = MaintenanceOperationType.MERGE

        try:
            self._check_capability(operation)
            rows_affected = self._do_merge(
                table_path,
                source_dataframe,
                merge_condition,
                when_matched,
                when_not_matched,
            )

            end_time = time.time()
            return MaintenanceResult(
                operation_type=operation,
                success=True,
                start_time=start_time,
                end_time=end_time,
                duration=end_time - start_time,
                rows_affected=rows_affected,
            )

        except NotImplementedError:
            raise
        except Exception as e:
            self.logger.error(f"MERGE failed: {e}")
            return MaintenanceResult.failure(operation, str(e), start_time)


def get_maintenance_operations_for_platform(platform_name: str) -> DataFrameMaintenanceOperations | None:
    """Get the maintenance operations handler for a platform.

    Args:
        platform_name: Platform name (e.g., "delta-lake", "iceberg", "polars-df")

    Returns:
        Maintenance operations handler if available, None if not implemented

    Note:
        Implementations are loaded lazily to avoid import errors when
        optional dependencies are not installed.
    """
    platform_lower = platform_name.lower()

    # Polars implementation
    if platform_lower in ("polars-df", "polars"):
        try:
            from benchbox.platforms.dataframe.polars_maintenance import (
                get_polars_maintenance_operations,
            )

            return get_polars_maintenance_operations()
        except ImportError:
            logger.debug("Polars maintenance not available (polars not installed)")
            return None

    # Delta Lake implementation
    if platform_lower in ("delta-lake", "delta", "deltalake"):
        try:
            from benchbox.platforms.dataframe.delta_lake_maintenance import (
                get_delta_lake_maintenance_operations,
            )

            return get_delta_lake_maintenance_operations()
        except ImportError:
            logger.debug("Delta Lake maintenance not available (deltalake not installed)")
            return None

    # Iceberg implementation
    if platform_lower in ("iceberg", "apache-iceberg", "pyiceberg"):
        try:
            from benchbox.platforms.dataframe.iceberg_maintenance import (
                get_iceberg_maintenance_operations,
            )

            return get_iceberg_maintenance_operations()
        except ImportError:
            logger.debug("Iceberg maintenance not available (pyiceberg not installed)")
            return None

    # DuckLake implementation
    if platform_lower in ("ducklake", "duck-lake", "duckdb-lake"):
        try:
            from benchbox.platforms.dataframe.ducklake_maintenance import (
                get_ducklake_maintenance_operations,
            )

            return get_ducklake_maintenance_operations()
        except ImportError:
            logger.debug("DuckLake maintenance not available (duckdb not installed)")
            return None

    # Hudi implementation
    # Note: Hudi requires a SparkSession which must be passed separately.
    # For Hudi, use get_hudi_maintenance_operations() directly with a session.
    if platform_lower in ("hudi", "apache-hudi"):
        logger.debug(
            "Hudi maintenance requires SparkSession. Use get_hudi_maintenance_operations(spark_session=spark) directly."
        )
        return None

    # PySpark implementation
    # Note: PySpark requires a SparkSession which must be passed separately.
    # For PySpark, use get_pyspark_maintenance_operations() directly with a session.
    if platform_lower in ("pyspark-df", "pyspark", "spark"):
        logger.debug(
            "PySpark maintenance requires SparkSession. "
            "Use get_pyspark_maintenance_operations(spark_session=spark) directly."
        )
        return None

    logger.debug(f"No maintenance operations implementation for platform: {platform_name}")
    return None
