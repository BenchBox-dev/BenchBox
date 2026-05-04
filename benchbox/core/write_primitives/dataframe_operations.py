"""DataFrame operations for Write Primitives benchmark.

This module provides DataFrame implementations of Write Primitives operations,
enabling benchmarking of write operations (INSERT, UPDATE, DELETE, MERGE, BULK_LOAD)
on DataFrame platforms like Polars, Delta Lake, and Iceberg.

The module leverages the existing maintenance interface infrastructure from
benchbox.core.dataframe.maintenance_interface for row-level operations.

Platform Support:
    - Polars: Full support via read-modify-write pattern
    - Delta Lake: Native ACID support via deltalake
    - Iceberg: Native ACID support via pyiceberg
    - PySpark: Via Delta Lake or file-based operations
    - Pandas: File-level operations only (INSERT, BULK_LOAD)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.core.dataframe.maintenance_interface import (
    DataFrameMaintenanceCapabilities,
    MaintenanceResult,
    get_maintenance_operations_for_platform,
)
from benchbox.core.dataframe_manager_factory import get_dataframe_manager

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WriteOperationType(Enum):
    """Types of write operations supported by the benchmark.

    These map to Write Primitives benchmark categories and the underlying
    maintenance operations.
    """

    # File-level operations (all platforms)
    INSERT = "insert"  # Append rows
    BULK_LOAD = "bulk_load"  # Load from files with format options

    # Row-level operations (Polars via rewrite, Delta Lake/Iceberg native)
    UPDATE = "update"  # Modify existing rows
    DELETE = "delete"  # Remove rows
    MERGE = "merge"  # Upsert operations

    # Transaction operations (ACID platforms only)
    TRANSACTION = "transaction"

    # Aggregate-state operations (engines with DataFrame-layer sketch APIs).
    # Modeled as two distinct ops because the persist and merge phases
    # produce separate user-facing measurements (write latency + persisted
    # state size vs. merge+extract latency). The persist phase builds
    # per-group aggregate state and writes it durably; the merge phase
    # reads that state, folds it across rows, and extracts a scalar.
    AGGREGATE_PERSIST = "aggregate_persist"
    AGGREGATE_MERGE = "aggregate_merge"


@dataclass
class DataFrameWriteCapabilities:
    """Platform capabilities for DataFrame write operations.

    Extended from DataFrameMaintenanceCapabilities to include
    Write Primitives-specific features like BULK_LOAD, compression.

    Attributes:
        platform_name: Name of the platform
        maintenance_caps: Underlying maintenance capabilities
        supports_bulk_load: Can load from various file formats
        supports_compression: Supports compression options
        supported_compressions: List of supported compression codecs
        supports_partitioning: Supports partition writes
        supports_sorting: Supports sorted writes
        notes: Platform-specific notes
    """

    platform_name: str
    maintenance_caps: DataFrameMaintenanceCapabilities | None = None
    supports_bulk_load: bool = True  # All DataFrame platforms can read files
    supports_compression: bool = True  # Most platforms support compression
    supported_compressions: list[str] = field(default_factory=lambda: ["zstd", "snappy", "gzip", "lz4"])
    supports_partitioning: bool = False  # PySpark, Polars have partitioning
    supports_sorting: bool = True  # Most platforms can sort before write
    # DataFrame-layer aggregate-state ops require engine-native sketch APIs
    # (e.g. PySpark `hll_sketch_agg`/`hll_union_agg`). Default False; engines
    # that wire concrete sketch surfaces flip these on.
    supports_aggregate_persist: bool = False
    supports_aggregate_merge: bool = False
    notes: str = ""

    def supports_operation(self, operation: WriteOperationType) -> bool:
        """Check if an operation type is supported.

        Args:
            operation: The operation type to check

        Returns:
            True if the operation is supported
        """
        # File-level operations always supported
        if operation == WriteOperationType.BULK_LOAD:
            return self.supports_bulk_load
        if operation == WriteOperationType.TRANSACTION:
            return self.maintenance_caps.supports_transactions if self.maintenance_caps else False

        # Aggregate-state ops are decided by their own dedicated capability flags
        # (no fallback to maintenance_caps because they are not row-level mutations).
        if operation == WriteOperationType.AGGREGATE_PERSIST:
            return self.supports_aggregate_persist
        if operation == WriteOperationType.AGGREGATE_MERGE:
            return self.supports_aggregate_merge

        # Row-level operations depend on maintenance capabilities
        if self.maintenance_caps is None:
            return False

        mapping = {
            WriteOperationType.INSERT: self.maintenance_caps.supports_insert,
            WriteOperationType.UPDATE: self.maintenance_caps.supports_update,
            WriteOperationType.DELETE: self.maintenance_caps.supports_delete
            or self.maintenance_caps.supports_partitioned_delete,
            WriteOperationType.MERGE: self.maintenance_caps.supports_merge,
        }
        return mapping.get(operation, False)

    def get_unsupported_operations(self) -> list[WriteOperationType]:
        """Get list of operations not supported by this platform.

        Returns:
            List of unsupported WriteOperationType values
        """
        return [op for op in WriteOperationType if not self.supports_operation(op)]


# Pre-defined capabilities for common DataFrame platforms
POLARS_WRITE_CAPABILITIES = DataFrameWriteCapabilities(
    platform_name="polars-df",
    maintenance_caps=None,  # Set at runtime via get_maintenance_operations_for_platform
    supports_bulk_load=True,
    supports_compression=True,
    supported_compressions=["zstd", "snappy", "gzip", "lz4"],
    supports_partitioning=True,  # Polars has partition_by in write_parquet
    supports_sorting=True,
    notes="Full operation support via read-modify-write. RAM-limited for large datasets.",
)

PANDAS_WRITE_CAPABILITIES = DataFrameWriteCapabilities(
    platform_name="pandas-df",
    maintenance_caps=None,
    supports_bulk_load=True,
    supports_compression=True,
    supported_compressions=["snappy", "gzip", "brotli"],
    supports_partitioning=False,
    supports_sorting=True,
    notes="File-level operations only. Use Polars or PySpark for row-level operations.",
)

PYSPARK_WRITE_CAPABILITIES = DataFrameWriteCapabilities(
    platform_name="pyspark-df",
    maintenance_caps=None,  # Depends on underlying table format (Delta/Iceberg)
    supports_bulk_load=True,
    supports_compression=True,
    supported_compressions=["zstd", "snappy", "gzip", "lz4"],
    supports_partitioning=True,  # partitionBy
    supports_sorting=True,  # orderBy
    # PySpark exposes hll_sketch_agg / hll_union_agg / hll_sketch_estimate
    # at the DataFrame layer (Spark 3.5+). Concrete sketch wiring lives in
    # the pyspark-dataframe-surface TODO; the capability flag here marks
    # the engine as eligible for the aggregate-state dispatch path.
    supports_aggregate_persist=True,
    supports_aggregate_merge=True,
    notes="Row-level operations require Delta Lake or Iceberg table format.",
)


@dataclass
class DataFrameWriteResult:
    """Result of a DataFrame write operation.

    Extends MaintenanceResult with Write Primitives-specific metrics.

    Attributes:
        operation_type: Type of write operation
        success: Whether the operation completed successfully
        start_time: Operation start timestamp (Unix time)
        end_time: Operation end timestamp (Unix time)
        duration_ms: Operation duration in milliseconds
        rows_affected: Number of rows written/modified
        bytes_written: Bytes written (if available)
        compression: Compression codec used
        file_count: Number of files written
        error_message: Error description if operation failed
        validation_passed: Whether validation checks passed
        validation_results: Details of validation checks
        metrics: Additional platform-specific metrics
    """

    operation_type: WriteOperationType
    success: bool
    start_time: float
    end_time: float
    duration_ms: float
    rows_affected: int
    bytes_written: int | None = None
    compression: str | None = None
    file_count: int | None = None
    error_message: str | None = None
    validation_passed: bool = True
    validation_results: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_maintenance_result(
        cls,
        maintenance_result: MaintenanceResult,
        operation_type: WriteOperationType,
        **extra_fields: Any,
    ) -> DataFrameWriteResult:
        """Create from a MaintenanceResult.

        Args:
            maintenance_result: Underlying maintenance result
            operation_type: Write operation type
            **extra_fields: Additional fields to set

        Returns:
            DataFrameWriteResult instance
        """
        return cls(
            operation_type=operation_type,
            success=maintenance_result.success,
            start_time=maintenance_result.start_time,
            end_time=maintenance_result.end_time,
            duration_ms=maintenance_result.duration * 1000,  # Convert to ms
            rows_affected=maintenance_result.rows_affected,
            error_message=maintenance_result.error_message,
            metrics=maintenance_result.metrics,
            **extra_fields,
        )

    @classmethod
    def failure(
        cls,
        operation_type: WriteOperationType,
        error_message: str,
        start_time: float | None = None,
    ) -> DataFrameWriteResult:
        """Create a failure result.

        Args:
            operation_type: The operation that failed
            error_message: Description of the failure
            start_time: Optional start time (defaults to now)

        Returns:
            DataFrameWriteResult indicating failure
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


class DataFrameWriteOperationsManager:
    """Manager for DataFrame write operations.

    Wraps the maintenance operations interface with Write Primitives-specific
    functionality including BULK_LOAD, validation, and result formatting.

    Example:
        manager = DataFrameWriteOperationsManager("polars-df")

        # Check capabilities
        if manager.supports_operation(WriteOperationType.UPDATE):
            result = manager.execute_update(
                table_path="/data/orders",
                condition="status = 'pending'",
                updates={"status": "'cancelled'"}
            )

        # Bulk load with options
        result = manager.execute_bulk_load(
            source_path="/data/raw/orders.csv",
            target_path="/data/orders",
            format="csv",
            compression="zstd"
        )
    """

    def __init__(self, platform_name: str, spark_session: Any = None) -> None:
        """Initialize the write operations manager.

        Args:
            platform_name: Platform name (e.g., "polars-df", "pyspark-df")
            spark_session: SparkSession instance (required for pyspark-df)

        Raises:
            ValueError: If platform is not supported for DataFrame operations
        """
        self.platform_name = platform_name.lower()
        self.spark_session = spark_session
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Get maintenance operations handler
        self._maintenance_ops = self._get_maintenance_ops()

        # Build capabilities
        self._capabilities = self._build_capabilities()

    def _get_maintenance_ops(self) -> Any:
        """Get the appropriate maintenance operations handler.

        For PySpark, uses the dedicated PySpark maintenance module.
        For other platforms, uses the generic maintenance interface.

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

    def _build_capabilities(self) -> DataFrameWriteCapabilities:
        """Build platform capabilities.

        Returns:
            DataFrameWriteCapabilities for this platform
        """
        maintenance_caps = None
        if self._maintenance_ops is not None:
            maintenance_caps = self._maintenance_ops.get_capabilities()

        # Use platform-specific defaults
        if "polars" in self.platform_name:
            caps = DataFrameWriteCapabilities(
                platform_name=self.platform_name,
                maintenance_caps=maintenance_caps,
                supports_bulk_load=True,
                supports_compression=True,
                supported_compressions=["zstd", "snappy", "gzip", "lz4"],
                supports_partitioning=True,
                supports_sorting=True,
                notes="Full operation support via read-modify-write.",
            )
        elif "pandas" in self.platform_name:
            caps = DataFrameWriteCapabilities(
                platform_name=self.platform_name,
                maintenance_caps=maintenance_caps,
                supports_bulk_load=True,
                supports_compression=True,
                supported_compressions=["snappy", "gzip", "brotli"],
                supports_partitioning=False,
                supports_sorting=True,
                notes="File-level operations only.",
            )
        elif "pyspark" in self.platform_name or "spark" in self.platform_name:
            caps = DataFrameWriteCapabilities(
                platform_name=self.platform_name,
                maintenance_caps=maintenance_caps,
                supports_bulk_load=True,
                supports_compression=True,
                supported_compressions=["zstd", "snappy", "gzip", "lz4"],
                supports_partitioning=True,
                supports_sorting=True,
                # PySpark has DataFrame-layer sketch APIs (hll_sketch_agg etc., Spark 3.5+).
                # See PYSPARK_WRITE_CAPABILITIES preset for rationale.
                supports_aggregate_persist=True,
                supports_aggregate_merge=True,
                notes="Row-level operations require Delta Lake table format.",
            )
        else:
            # Generic capabilities
            caps = DataFrameWriteCapabilities(
                platform_name=self.platform_name,
                maintenance_caps=maintenance_caps,
                supports_bulk_load=True,
                supports_compression=True,
            )

        return caps

    def get_capabilities(self) -> DataFrameWriteCapabilities:
        """Get platform write capabilities.

        Returns:
            DataFrameWriteCapabilities for this platform
        """
        return self._capabilities

    def supports_operation(self, operation: WriteOperationType) -> bool:
        """Check if an operation type is supported.

        Args:
            operation: The operation to check

        Returns:
            True if supported
        """
        return self._capabilities.supports_operation(operation)

    def get_unsupported_message(self, operation: WriteOperationType) -> str:
        """Get error message for unsupported operation.

        Args:
            operation: The unsupported operation

        Returns:
            Helpful error message with alternatives
        """
        if operation in (WriteOperationType.UPDATE, WriteOperationType.DELETE, WriteOperationType.MERGE):
            return (
                f"{self.platform_name} does not support {operation.value} operations in the current configuration.\n"
                f"Alternatives:\n"
                f"  - Use polars-df (supports row-level operations via read-modify-write)\n"
                f"  - Use pyspark-df with Delta Lake table format\n"
                f"  - Use file-level INSERT/BULK_LOAD operations instead"
            )
        if operation == WriteOperationType.TRANSACTION:
            return (
                f"{self.platform_name} does not support explicit transactions.\n"
                f"Use Delta Lake or Iceberg for ACID transaction support."
            )
        if operation in (WriteOperationType.AGGREGATE_PERSIST, WriteOperationType.AGGREGATE_MERGE):
            return (
                f"{self.platform_name} does not support DataFrame-layer "
                f"{operation.value} operations.\n"
                f"Aggregate-state ops require an engine with sketch APIs at the "
                f"DataFrame layer (e.g. PySpark `hll_sketch_agg`). "
                f"Use the SQL surface or skip this op."
            )
        return f"{self.platform_name} does not support {operation.value} operations."

    def execute_insert(
        self,
        table_path: Path | str,
        dataframe: Any,
        partition_columns: list[str] | None = None,
        mode: str = "append",
    ) -> DataFrameWriteResult:
        """Execute INSERT operation.

        Args:
            table_path: Path to the table directory
            dataframe: DataFrame containing rows to insert
            partition_columns: Columns to partition by
            mode: Write mode ("append" or "overwrite")

        Returns:
            DataFrameWriteResult with operation outcome
        """
        if not self.supports_operation(WriteOperationType.INSERT):
            return DataFrameWriteResult.failure(
                WriteOperationType.INSERT,
                self.get_unsupported_message(WriteOperationType.INSERT),
            )

        if self._maintenance_ops is None:
            return DataFrameWriteResult.failure(
                WriteOperationType.INSERT,
                f"Maintenance operations not available for {self.platform_name}",
            )

        result = self._maintenance_ops.insert_rows(
            table_path=table_path,
            dataframe=dataframe,
            partition_columns=partition_columns,
            mode=mode,
        )

        return DataFrameWriteResult.from_maintenance_result(
            result,
            WriteOperationType.INSERT,
        )

    def execute_update(
        self,
        table_path: Path | str,
        condition: str,
        updates: dict[str, Any],
    ) -> DataFrameWriteResult:
        """Execute UPDATE operation.

        Args:
            table_path: Path to the table directory
            condition: SQL-like condition string
            updates: Column name to new value mapping

        Returns:
            DataFrameWriteResult with operation outcome
        """
        if not self.supports_operation(WriteOperationType.UPDATE):
            return DataFrameWriteResult.failure(
                WriteOperationType.UPDATE,
                self.get_unsupported_message(WriteOperationType.UPDATE),
            )

        if self._maintenance_ops is None:
            return DataFrameWriteResult.failure(
                WriteOperationType.UPDATE,
                f"Maintenance operations not available for {self.platform_name}",
            )

        result = self._maintenance_ops.update_rows(
            table_path=table_path,
            condition=condition,
            updates=updates,
        )

        return DataFrameWriteResult.from_maintenance_result(
            result,
            WriteOperationType.UPDATE,
        )

    def execute_delete(
        self,
        table_path: Path | str,
        condition: str,
    ) -> DataFrameWriteResult:
        """Execute DELETE operation.

        Args:
            table_path: Path to the table directory
            condition: SQL-like condition string

        Returns:
            DataFrameWriteResult with operation outcome
        """
        if not self.supports_operation(WriteOperationType.DELETE):
            return DataFrameWriteResult.failure(
                WriteOperationType.DELETE,
                self.get_unsupported_message(WriteOperationType.DELETE),
            )

        if self._maintenance_ops is None:
            return DataFrameWriteResult.failure(
                WriteOperationType.DELETE,
                f"Maintenance operations not available for {self.platform_name}",
            )

        result = self._maintenance_ops.delete_rows(
            table_path=table_path,
            condition=condition,
        )

        return DataFrameWriteResult.from_maintenance_result(
            result,
            WriteOperationType.DELETE,
        )

    def execute_merge(
        self,
        table_path: Path | str,
        source_dataframe: Any,
        merge_condition: str,
        when_matched: dict[str, Any] | None = None,
        when_not_matched: dict[str, Any] | None = None,
    ) -> DataFrameWriteResult:
        """Execute MERGE (upsert) operation.

        Args:
            table_path: Path to the target table
            source_dataframe: DataFrame containing source rows
            merge_condition: Join condition for matching rows
            when_matched: Updates to apply when matched
            when_not_matched: Values for insert when not matched

        Returns:
            DataFrameWriteResult with operation outcome
        """
        if not self.supports_operation(WriteOperationType.MERGE):
            return DataFrameWriteResult.failure(
                WriteOperationType.MERGE,
                self.get_unsupported_message(WriteOperationType.MERGE),
            )

        if self._maintenance_ops is None:
            return DataFrameWriteResult.failure(
                WriteOperationType.MERGE,
                f"Maintenance operations not available for {self.platform_name}",
            )

        result = self._maintenance_ops.merge_rows(
            table_path=table_path,
            source_dataframe=source_dataframe,
            merge_condition=merge_condition,
            when_matched=when_matched,
            when_not_matched=when_not_matched,
        )

        return DataFrameWriteResult.from_maintenance_result(
            result,
            WriteOperationType.MERGE,
        )

    def execute_bulk_load(
        self,
        source_path: Path | str,
        target_path: Path | str,
        source_format: str = "parquet",
        target_format: str = "parquet",
        compression: str | None = "zstd",
        partition_columns: list[str] | None = None,
        sort_columns: list[str] | None = None,
    ) -> DataFrameWriteResult:
        """Execute BULK_LOAD operation.

        Reads data from source files and writes to target with specified options.

        Args:
            source_path: Path to source data files
            target_path: Path to write target data
            source_format: Source file format ("parquet", "csv", "json")
            target_format: Target file format ("parquet")
            compression: Compression codec (None, "zstd", "snappy", "gzip", "lz4")
            partition_columns: Columns to partition by
            sort_columns: Columns to sort by before writing

        Returns:
            DataFrameWriteResult with operation outcome
        """
        if not self.supports_operation(WriteOperationType.BULK_LOAD):
            return DataFrameWriteResult.failure(
                WriteOperationType.BULK_LOAD,
                self.get_unsupported_message(WriteOperationType.BULK_LOAD),
            )

        start_time = time.time()
        source_path = Path(source_path)
        target_path = Path(target_path)

        try:
            # Platform-specific bulk load implementation
            if "polars" in self.platform_name:
                rows, bytes_written, file_count = self._bulk_load_polars(
                    source_path,
                    target_path,
                    source_format,
                    target_format,
                    compression,
                    partition_columns,
                    sort_columns,
                )
            elif "pandas" in self.platform_name:
                rows, bytes_written, file_count = self._bulk_load_pandas(
                    source_path,
                    target_path,
                    source_format,
                    target_format,
                    compression,
                    sort_columns,
                )
            elif "pyspark" in self.platform_name or "spark" in self.platform_name:
                rows, bytes_written, file_count = self._bulk_load_pyspark(
                    source_path,
                    target_path,
                    source_format,
                    target_format,
                    compression,
                    partition_columns,
                    sort_columns,
                )
            else:
                return DataFrameWriteResult.failure(
                    WriteOperationType.BULK_LOAD,
                    f"BULK_LOAD not implemented for {self.platform_name}",
                    start_time,
                )

            end_time = time.time()
            return DataFrameWriteResult(
                operation_type=WriteOperationType.BULK_LOAD,
                success=True,
                start_time=start_time,
                end_time=end_time,
                duration_ms=(end_time - start_time) * 1000,
                rows_affected=rows,
                bytes_written=bytes_written,
                compression=compression,
                file_count=file_count,
            )

        except Exception as e:
            self.logger.error(f"BULK_LOAD failed: {e}")
            return DataFrameWriteResult.failure(
                WriteOperationType.BULK_LOAD,
                str(e),
                start_time,
            )

    def _bulk_load_polars(
        self,
        source_path: Path,
        target_path: Path,
        source_format: str,
        target_format: str,
        compression: str | None,
        partition_columns: list[str] | None,
        sort_columns: list[str] | None,
    ) -> tuple[int, int | None, int]:
        """Polars-specific bulk load implementation.

        Returns:
            Tuple of (rows_written, bytes_written, file_count)
        """
        try:
            import polars as pl
        except ImportError as e:
            raise ImportError("Polars is required for polars-df bulk load") from e

        # Read source data
        if source_format == "parquet":
            df = pl.scan_parquet(source_path).collect()
        elif source_format == "csv":
            df = pl.scan_csv(source_path).collect()
        elif source_format == "json":
            df = pl.read_json(source_path)
        else:
            raise ValueError(f"Unsupported source format: {source_format}")

        row_count = df.height

        # Apply sorting
        if sort_columns:
            df = df.sort(sort_columns)

        # Write to target
        target_path.mkdir(parents=True, exist_ok=True)

        if partition_columns:
            # Partitioned write
            for partition_vals, partition_df in df.group_by(partition_columns):
                if isinstance(partition_vals, tuple):
                    parts = zip(partition_columns, partition_vals)
                else:
                    parts = [(partition_columns[0], partition_vals)]

                partition_path = target_path
                for col, val in parts:
                    partition_path = partition_path / f"{col}={val}"

                partition_path.mkdir(parents=True, exist_ok=True)
                partition_df.write_parquet(
                    partition_path / "part-00000.parquet",
                    compression=compression or "uncompressed",
                )
            file_count = len(list(target_path.rglob("*.parquet")))
        else:
            # Single file write
            output_file = target_path / "part-00000.parquet"
            df.write_parquet(
                output_file,
                compression=compression or "uncompressed",
            )
            file_count = 1

        # Estimate bytes written
        bytes_written = sum(f.stat().st_size for f in target_path.rglob("*.parquet"))

        return row_count, bytes_written, file_count

    def _bulk_load_pandas(
        self,
        source_path: Path,
        target_path: Path,
        source_format: str,
        target_format: str,
        compression: str | None,
        sort_columns: list[str] | None,
    ) -> tuple[int, int | None, int]:
        """Pandas-specific bulk load implementation.

        Returns:
            Tuple of (rows_written, bytes_written, file_count)
        """
        try:
            import pandas as pd
        except ImportError as e:
            raise ImportError("Pandas is required for pandas-df bulk load") from e

        # Read source data
        if source_format == "parquet":
            df = pd.read_parquet(source_path)
        elif source_format == "csv":
            df = pd.read_csv(source_path)
        elif source_format == "json":
            df = pd.read_json(source_path)
        else:
            raise ValueError(f"Unsupported source format: {source_format}")

        row_count = len(df)

        # Apply sorting
        if sort_columns:
            df = df.sort_values(sort_columns)

        # Write to target
        target_path.mkdir(parents=True, exist_ok=True)
        output_file = target_path / "part-00000.parquet"
        df.to_parquet(
            output_file,
            compression=compression or "snappy",
            index=False,
        )

        bytes_written = output_file.stat().st_size

        return row_count, bytes_written, 1

    def _bulk_load_pyspark(
        self,
        source_path: Path,
        target_path: Path,
        source_format: str,
        target_format: str,
        compression: str | None,
        partition_columns: list[str] | None,
        sort_columns: list[str] | None,
    ) -> tuple[int, int | None, int]:
        """PySpark-specific bulk load implementation using DataFrame API.

        Uses spark.read.format().load() and df.write.format().save() pattern.

        Returns:
            Tuple of (rows_written, bytes_written, file_count)
        """
        if self.spark_session is None:
            raise ValueError(
                "SparkSession is required for PySpark bulk load. "
                "Pass spark_session to DataFrameWriteOperationsManager or use get_pyspark_write_manager()."
            )

        spark = self.spark_session
        source_str = str(source_path)
        target_str = str(target_path)

        # Read source data using DataFrame API
        reader = spark.read.format(source_format)

        if source_format == "csv":
            reader = reader.option("header", "true").option("inferSchema", "true")

        df = reader.load(source_str)
        row_count = df.count()

        if row_count == 0:
            self.logger.info("No rows to load")
            return 0, 0, 0

        # Apply sorting
        if sort_columns:
            df = df.orderBy(*sort_columns)

        # Build writer
        writer = df.write.mode("overwrite")

        if partition_columns:
            writer = writer.partitionBy(*partition_columns)

        if compression:
            writer = writer.option("compression", compression)

        # Write using DataFrame API
        if target_format == "delta":
            writer.format("delta").save(target_str)
        else:
            writer.parquet(target_str)

        # Estimate bytes written and file count
        target_path.mkdir(parents=True, exist_ok=True)
        parquet_files = list(target_path.rglob("*.parquet"))
        file_count = len(parquet_files)
        bytes_written = sum(f.stat().st_size for f in parquet_files)

        return row_count, bytes_written, file_count

    def execute_aggregate_persist(
        self,
        target_path: Path | str,
        state_builder: Any,
        compression: str | None = "zstd",
    ) -> DataFrameWriteResult:
        """Execute AGGREGATE_PERSIST: build per-group aggregate state and persist it.

        Sketch-shaped DataFrame ops express the persist phase as a callable that
        returns a DataFrame holding the per-group sketch state column(s). The
        manager handles the durable write to ``target_path`` (Parquet) plus the
        timing, byte, and file-count bookkeeping. Engine-specific sketch APIs
        live in the callable; the manager stays agnostic.

        Args:
            target_path: Directory where the aggregate state is persisted.
            state_builder: Callable taking no arguments and returning a DataFrame
                whose columns include the aggregate-state output(s). For PySpark
                the typical implementation calls ``df.groupBy(...).agg(F.hll_sketch_agg(...))``;
                for engines without a DataFrame-layer sketch surface this method
                is unsupported and is rejected upstream by ``supports_operation``.
            compression: Parquet compression codec (default zstd).

        Returns:
            DataFrameWriteResult with rows_affected = number of state rows
            persisted, bytes_written = persisted state size, and file_count.
        """
        if not self.supports_operation(WriteOperationType.AGGREGATE_PERSIST):
            return DataFrameWriteResult.failure(
                WriteOperationType.AGGREGATE_PERSIST,
                self.get_unsupported_message(WriteOperationType.AGGREGATE_PERSIST),
            )

        start_time = time.time()
        target_path = Path(target_path)
        try:
            state_df = state_builder()
            target_path.mkdir(parents=True, exist_ok=True)
            rows, bytes_written, file_count = self._persist_dataframe_to_parquet(state_df, target_path, compression)
            end_time = time.time()
            return DataFrameWriteResult(
                operation_type=WriteOperationType.AGGREGATE_PERSIST,
                success=True,
                start_time=start_time,
                end_time=end_time,
                duration_ms=(end_time - start_time) * 1000,
                rows_affected=rows,
                bytes_written=bytes_written,
                compression=compression,
                file_count=file_count,
            )
        except Exception as e:
            self.logger.error(f"AGGREGATE_PERSIST failed: {e}")
            return DataFrameWriteResult.failure(
                WriteOperationType.AGGREGATE_PERSIST,
                str(e),
                start_time,
            )

    def execute_aggregate_merge(
        self,
        source_path: Path | str,
        merge_extract: Any,
    ) -> DataFrameWriteResult:
        """Execute AGGREGATE_MERGE: read persisted state, merge across rows, extract scalar.

        The merge phase is the user-facing measurement that pairs with
        AGGREGATE_PERSIST. The callable receives the path the persist phase wrote
        to and is responsible for reading the state, folding it via the engine's
        merge UDF (e.g. ``F.hll_union_agg`` on PySpark), and returning the final
        scalar (e.g. via ``F.hll_sketch_estimate``). The manager handles the
        timing and result envelope.

        Args:
            source_path: Directory the AGGREGATE_PERSIST run wrote to.
            merge_extract: Callable taking ``Path`` and returning the extracted
                scalar value. Engine-agnostic at this layer; concrete sketch
                wiring lives in the callable.

        Returns:
            DataFrameWriteResult with rows_affected = 1 and the extracted scalar
            in ``metrics["aggregate_value"]``.
        """
        if not self.supports_operation(WriteOperationType.AGGREGATE_MERGE):
            return DataFrameWriteResult.failure(
                WriteOperationType.AGGREGATE_MERGE,
                self.get_unsupported_message(WriteOperationType.AGGREGATE_MERGE),
            )

        start_time = time.time()
        source_path = Path(source_path)
        try:
            value = merge_extract(source_path)
            end_time = time.time()
            return DataFrameWriteResult(
                operation_type=WriteOperationType.AGGREGATE_MERGE,
                success=True,
                start_time=start_time,
                end_time=end_time,
                duration_ms=(end_time - start_time) * 1000,
                rows_affected=1,
                metrics={"aggregate_value": value},
            )
        except Exception as e:
            self.logger.error(f"AGGREGATE_MERGE failed: {e}")
            return DataFrameWriteResult.failure(
                WriteOperationType.AGGREGATE_MERGE,
                str(e),
                start_time,
            )

    def _persist_dataframe_to_parquet(
        self,
        state_df: Any,
        target_path: Path,
        compression: str | None,
    ) -> tuple[int, int, int]:
        """Persist an arbitrary DataFrame to Parquet at ``target_path``.

        Returns (row_count, bytes_written, file_count). Selects the writer based
        on ``self.platform_name`` so engines expose their native partitioned
        writers. Aggregate-state engines that introduce richer state shapes can
        override this method later without touching the dispatch envelope.
        """
        if "pyspark" in self.platform_name or "spark" in self.platform_name:
            row_count = state_df.count()
            (
                state_df.write.mode("overwrite")
                .option("compression", compression or "uncompressed")
                .parquet(str(target_path))
            )
        elif "polars" in self.platform_name:
            row_count = state_df.height
            state_df.write_parquet(
                target_path / "part-00000.parquet",
                compression=compression or "uncompressed",
            )
        else:
            raise RuntimeError(f"Aggregate-state persistence not implemented for platform '{self.platform_name}'")

        parquet_files = list(target_path.rglob("*.parquet"))
        file_count = len(parquet_files)
        bytes_written = sum(f.stat().st_size for f in parquet_files)
        return row_count, bytes_written, file_count


def get_dataframe_write_manager(
    platform_name: str,
    spark_session: Any = None,
) -> DataFrameWriteOperationsManager | None:
    """Get a DataFrame write operations manager for a platform.

    Args:
        platform_name: Platform name (e.g., "polars-df", "pandas-df", "pyspark-df")
        spark_session: SparkSession instance (required for pyspark-df)

    Returns:
        DataFrameWriteOperationsManager if platform supports DataFrame writes,
        None if platform is not a DataFrame platform.
    """
    return get_dataframe_manager(
        platform_name,
        manager_class=DataFrameWriteOperationsManager,
        supported_platforms=("polars-df", "polars", "pandas-df", "pandas", "pyspark-df", "pyspark"),
        logger=logger,
        manager_label="write",
        spark_session=spark_session,
    )


__all__ = [
    "WriteOperationType",
    "DataFrameWriteCapabilities",
    "DataFrameWriteResult",
    "DataFrameWriteOperationsManager",
    "get_dataframe_write_manager",
    "POLARS_WRITE_CAPABILITIES",
    "PANDAS_WRITE_CAPABILITIES",
    "PYSPARK_WRITE_CAPABILITIES",
]
