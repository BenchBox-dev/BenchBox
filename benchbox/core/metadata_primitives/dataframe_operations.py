"""DataFrame operations for Metadata Primitives benchmark.

This module provides DataFrame implementations of metadata introspection operations,
enabling benchmarking of schema discovery, column introspection, and table statistics
on DataFrame platforms like Polars, PySpark, and Pandas.

Platform Support:
    - Polars: Schema introspection (df.schema, df.dtypes, df.describe())
    - Pandas: Schema introspection (df.dtypes, df.info(), df.describe())
    - PySpark: Full catalog support via spark.catalog API + Delta Lake/Iceberg metadata

The operations are organized into categories based on capability level:
    - Schema Introspection: Available on all platforms
    - Catalog Operations: PySpark with configured catalog only
    - Lakehouse Metadata: Delta Lake and Iceberg table formats

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from benchbox.core.dataframe_manager_factory import get_dataframe_manager

logger = logging.getLogger(__name__)


class MetadataOperationType(Enum):
    """Types of metadata operations supported by the benchmark.

    Operations are grouped by platform capability level:
    - Schema introspection: All DataFrame platforms
    - Catalog operations: PySpark with catalog
    - Lakehouse metadata: Delta Lake / Iceberg
    """

    # Schema introspection (all platforms)
    LIST_COLUMNS = "list_columns"
    GET_DTYPES = "get_dtypes"
    GET_SCHEMA = "get_schema"
    DESCRIBE_STATS = "describe_stats"
    ROW_COUNT = "row_count"
    COLUMN_COUNT = "column_count"

    # Catalog operations (PySpark with catalog)
    LIST_DATABASES = "list_databases"
    LIST_TABLES = "list_tables"
    LIST_TABLE_COLUMNS = "list_table_columns"
    TABLE_EXISTS = "table_exists"
    GET_TABLE_INFO = "get_table_info"

    # Lakehouse metadata (Delta Lake / Iceberg)
    TABLE_HISTORY = "table_history"
    TABLE_DETAIL = "table_detail"
    FILE_METADATA = "file_metadata"
    PARTITION_INFO = "partition_info"
    SNAPSHOT_INFO = "snapshot_info"

    # Complexity testing
    WIDE_TABLE_SCHEMA = "wide_table_schema"
    LARGE_CATALOG_LIST = "large_catalog_list"
    COMPLEX_TYPE_INTROSPECTION = "complex_type_introspection"


class MetadataOperationCategory(Enum):
    """Categories of metadata operations."""

    SCHEMA = "schema"  # Schema introspection (all platforms)
    CATALOG = "catalog"  # Catalog operations (PySpark)
    LAKEHOUSE = "lakehouse"  # Delta Lake / Iceberg metadata
    COMPLEXITY = "complexity"  # Complexity stress testing


# Mapping of operation types to categories
OPERATION_CATEGORIES: dict[MetadataOperationType, MetadataOperationCategory] = {
    # Schema operations
    MetadataOperationType.LIST_COLUMNS: MetadataOperationCategory.SCHEMA,
    MetadataOperationType.GET_DTYPES: MetadataOperationCategory.SCHEMA,
    MetadataOperationType.GET_SCHEMA: MetadataOperationCategory.SCHEMA,
    MetadataOperationType.DESCRIBE_STATS: MetadataOperationCategory.SCHEMA,
    MetadataOperationType.ROW_COUNT: MetadataOperationCategory.SCHEMA,
    MetadataOperationType.COLUMN_COUNT: MetadataOperationCategory.SCHEMA,
    # Catalog operations
    MetadataOperationType.LIST_DATABASES: MetadataOperationCategory.CATALOG,
    MetadataOperationType.LIST_TABLES: MetadataOperationCategory.CATALOG,
    MetadataOperationType.LIST_TABLE_COLUMNS: MetadataOperationCategory.CATALOG,
    MetadataOperationType.TABLE_EXISTS: MetadataOperationCategory.CATALOG,
    MetadataOperationType.GET_TABLE_INFO: MetadataOperationCategory.CATALOG,
    # Lakehouse operations
    MetadataOperationType.TABLE_HISTORY: MetadataOperationCategory.LAKEHOUSE,
    MetadataOperationType.TABLE_DETAIL: MetadataOperationCategory.LAKEHOUSE,
    MetadataOperationType.FILE_METADATA: MetadataOperationCategory.LAKEHOUSE,
    MetadataOperationType.PARTITION_INFO: MetadataOperationCategory.LAKEHOUSE,
    MetadataOperationType.SNAPSHOT_INFO: MetadataOperationCategory.LAKEHOUSE,
    # Complexity operations
    MetadataOperationType.WIDE_TABLE_SCHEMA: MetadataOperationCategory.COMPLEXITY,
    MetadataOperationType.LARGE_CATALOG_LIST: MetadataOperationCategory.COMPLEXITY,
    MetadataOperationType.COMPLEX_TYPE_INTROSPECTION: MetadataOperationCategory.COMPLEXITY,
}


@dataclass
class DataFrameMetadataCapabilities:
    """Platform capabilities for DataFrame metadata operations.

    Different DataFrame platforms have varying levels of metadata introspection
    support. This dataclass captures what operations each platform can perform.

    Attributes:
        platform_name: Name of the platform (e.g., "polars-df", "pyspark-df")
        supports_schema_introspection: Can introspect DataFrame schema/dtypes
        supports_describe: Can compute summary statistics
        supports_catalog: Has catalog API (list databases, tables)
        supports_delta_lake: Has Delta Lake metadata capabilities
        supports_iceberg: Has Iceberg metadata capabilities
        supports_partitions: Can introspect partition information
        supports_complex_types: Can introspect nested/complex types
        notes: Platform-specific notes
    """

    platform_name: str
    supports_schema_introspection: bool = True  # All platforms support basic schema
    supports_describe: bool = True  # Most platforms support describe
    supports_catalog: bool = False  # Only PySpark with catalog
    supports_delta_lake: bool = False  # Requires delta-spark or deltalake
    supports_iceberg: bool = False  # Requires iceberg-spark or pyiceberg
    supports_partitions: bool = False  # PySpark, some lakehouse formats
    supports_complex_types: bool = True  # Most platforms handle complex types
    notes: str = ""

    def supports_operation(self, operation: MetadataOperationType) -> bool:
        """Check if an operation type is supported.

        Args:
            operation: The operation type to check

        Returns:
            True if the operation is supported
        """
        # Schema operations - all platforms
        if operation in (
            MetadataOperationType.LIST_COLUMNS,
            MetadataOperationType.GET_DTYPES,
            MetadataOperationType.GET_SCHEMA,
            MetadataOperationType.ROW_COUNT,
            MetadataOperationType.COLUMN_COUNT,
        ):
            return self.supports_schema_introspection

        if operation == MetadataOperationType.DESCRIBE_STATS:
            return self.supports_describe

        # Catalog operations - PySpark with catalog
        if operation in (
            MetadataOperationType.LIST_DATABASES,
            MetadataOperationType.LIST_TABLES,
            MetadataOperationType.LIST_TABLE_COLUMNS,
            MetadataOperationType.TABLE_EXISTS,
            MetadataOperationType.GET_TABLE_INFO,
        ):
            return self.supports_catalog

        # Lakehouse operations - Delta Lake / Iceberg
        if operation in (
            MetadataOperationType.TABLE_HISTORY,
            MetadataOperationType.TABLE_DETAIL,
        ):
            return self.supports_delta_lake

        if operation == MetadataOperationType.SNAPSHOT_INFO:
            return self.supports_iceberg

        if operation == MetadataOperationType.FILE_METADATA:
            return self.supports_delta_lake or self.supports_iceberg

        if operation == MetadataOperationType.PARTITION_INFO:
            return self.supports_partitions

        # Complexity operations
        if operation == MetadataOperationType.WIDE_TABLE_SCHEMA:
            return self.supports_schema_introspection

        if operation == MetadataOperationType.LARGE_CATALOG_LIST:
            return self.supports_catalog

        if operation == MetadataOperationType.COMPLEX_TYPE_INTROSPECTION:
            return self.supports_complex_types

        return False

    def get_supported_operations(self) -> list[MetadataOperationType]:
        """Get list of operations supported by this platform.

        Returns:
            List of supported MetadataOperationType values
        """
        return [op for op in MetadataOperationType if self.supports_operation(op)]

    def get_unsupported_operations(self) -> list[MetadataOperationType]:
        """Get list of operations not supported by this platform.

        Returns:
            List of unsupported MetadataOperationType values
        """
        return [op for op in MetadataOperationType if not self.supports_operation(op)]

    def get_supported_categories(self) -> list[MetadataOperationCategory]:
        """Get list of operation categories supported by this platform.

        Returns:
            List of supported MetadataOperationCategory values
        """
        categories = set()
        for op in self.get_supported_operations():
            if op in OPERATION_CATEGORIES:
                categories.add(OPERATION_CATEGORIES[op])
        return sorted(categories, key=lambda c: c.value)


# Pre-defined capabilities for common DataFrame platforms
POLARS_METADATA_CAPABILITIES = DataFrameMetadataCapabilities(
    platform_name="polars-df",
    supports_schema_introspection=True,
    supports_describe=True,
    supports_catalog=False,
    supports_delta_lake=False,  # Can read Delta via polars, limited metadata
    supports_iceberg=False,
    supports_partitions=False,
    supports_complex_types=True,
    notes="Schema introspection via df.schema, df.dtypes. No catalog support.",
)

PANDAS_METADATA_CAPABILITIES = DataFrameMetadataCapabilities(
    platform_name="pandas-df",
    supports_schema_introspection=True,
    supports_describe=True,
    supports_catalog=False,
    supports_delta_lake=False,
    supports_iceberg=False,
    supports_partitions=False,
    supports_complex_types=False,  # Pandas has limited nested type support
    notes="Schema introspection via df.dtypes, df.info(). No catalog support.",
)

PYSPARK_METADATA_CAPABILITIES = DataFrameMetadataCapabilities(
    platform_name="pyspark-df",
    supports_schema_introspection=True,
    supports_describe=True,
    supports_catalog=True,  # spark.catalog API
    supports_delta_lake=False,  # Set at runtime based on available packages
    supports_iceberg=False,  # Set at runtime based on available packages
    supports_partitions=True,
    supports_complex_types=True,
    notes="Full catalog support via spark.catalog. Delta Lake/Iceberg require packages.",
)

DATAFUSION_METADATA_CAPABILITIES = DataFrameMetadataCapabilities(
    platform_name="datafusion-df",
    supports_schema_introspection=True,
    supports_describe=True,
    supports_catalog=False,  # Limited catalog in standalone mode
    supports_delta_lake=False,
    supports_iceberg=False,
    supports_partitions=False,
    supports_complex_types=True,
    notes="Schema introspection via DataFrame schema. Limited catalog support.",
)


def get_platform_capabilities(platform_name: str, **kwargs: Any) -> DataFrameMetadataCapabilities:
    """Get metadata capabilities for a platform.

    Args:
        platform_name: Platform name (e.g., "polars-df", "pyspark-df")
        **kwargs: Optional overrides (e.g., supports_delta_lake=True)

    Returns:
        DataFrameMetadataCapabilities for the platform
    """
    platform_lower = platform_name.lower()

    # Select base capabilities
    if "polars" in platform_lower:
        base = POLARS_METADATA_CAPABILITIES
    elif "pandas" in platform_lower:
        base = PANDAS_METADATA_CAPABILITIES
    elif "pyspark" in platform_lower or "spark" in platform_lower:
        base = PYSPARK_METADATA_CAPABILITIES
    elif "datafusion" in platform_lower:
        base = DATAFUSION_METADATA_CAPABILITIES
    else:
        # Generic capabilities
        base = DataFrameMetadataCapabilities(
            platform_name=platform_name,
            supports_schema_introspection=True,
            supports_describe=True,
            notes="Unknown platform - basic schema introspection only.",
        )

    # Apply overrides if any
    if kwargs:
        return DataFrameMetadataCapabilities(
            platform_name=platform_name,
            supports_schema_introspection=kwargs.get(
                "supports_schema_introspection", base.supports_schema_introspection
            ),
            supports_describe=kwargs.get("supports_describe", base.supports_describe),
            supports_catalog=kwargs.get("supports_catalog", base.supports_catalog),
            supports_delta_lake=kwargs.get("supports_delta_lake", base.supports_delta_lake),
            supports_iceberg=kwargs.get("supports_iceberg", base.supports_iceberg),
            supports_partitions=kwargs.get("supports_partitions", base.supports_partitions),
            supports_complex_types=kwargs.get("supports_complex_types", base.supports_complex_types),
            notes=kwargs.get("notes", base.notes),
        )

    return base


@dataclass
class DataFrameMetadataResult:
    """Result of a DataFrame metadata operation.

    Attributes:
        operation_type: Type of metadata operation
        success: Whether the operation completed successfully
        start_time: Operation start timestamp (Unix time)
        end_time: Operation end timestamp (Unix time)
        duration_ms: Operation duration in milliseconds
        result_count: Number of items returned (columns, tables, etc.)
        result_data: The actual metadata result (schema dict, column list, etc.)
        error_message: Error description if operation failed
        metrics: Additional platform-specific metrics
    """

    operation_type: MetadataOperationType
    success: bool
    start_time: float
    end_time: float
    duration_ms: float
    result_count: int = 0
    result_data: Any = None
    error_message: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success_result(
        cls,
        operation_type: MetadataOperationType,
        start_time: float,
        result_count: int,
        result_data: Any = None,
        metrics: dict[str, Any] | None = None,
    ) -> DataFrameMetadataResult:
        """Create a successful result.

        Args:
            operation_type: The operation that completed
            start_time: When the operation started
            result_count: Number of items in the result
            result_data: The actual result data
            metrics: Additional metrics

        Returns:
            DataFrameMetadataResult indicating success
        """
        end_time = time.time()
        return cls(
            operation_type=operation_type,
            success=True,
            start_time=start_time,
            end_time=end_time,
            duration_ms=(end_time - start_time) * 1000,
            result_count=result_count,
            result_data=result_data,
            metrics=metrics or {},
        )

    @classmethod
    def failure_result(
        cls,
        operation_type: MetadataOperationType,
        error_message: str,
        start_time: float | None = None,
    ) -> DataFrameMetadataResult:
        """Create a failure result.

        Args:
            operation_type: The operation that failed
            error_message: Description of the failure
            start_time: Optional start time (defaults to now)

        Returns:
            DataFrameMetadataResult indicating failure
        """
        now = time.time()
        return cls(
            operation_type=operation_type,
            success=False,
            start_time=start_time or now,
            end_time=now,
            duration_ms=0.0 if start_time is None else (now - start_time) * 1000,
            result_count=0,
            error_message=error_message,
        )


class UnsupportedOperationError(Exception):
    """Raised when a metadata operation is not supported on the current platform.

    Provides a helpful error message with alternatives.
    """

    def __init__(
        self,
        operation: MetadataOperationType,
        platform_name: str,
        suggestion: str | None = None,
    ):
        self.operation = operation
        self.platform_name = platform_name
        self.suggestion = suggestion

        message = f"{platform_name} does not support {operation.value} operations."
        if suggestion:
            message += f"\n{suggestion}"

        super().__init__(message)


def get_unsupported_message(operation: MetadataOperationType, platform_name: str) -> str:
    """Get helpful error message for unsupported operations.

    Args:
        operation: The unsupported operation
        platform_name: The platform name

    Returns:
        Helpful error message with alternatives
    """
    category = OPERATION_CATEGORIES.get(operation, MetadataOperationCategory.SCHEMA)

    if category == MetadataOperationCategory.CATALOG:
        return (
            f"{platform_name} does not support catalog operations ({operation.value}).\n"
            f"Catalog operations require PySpark with a configured catalog.\n"
            f"Alternatives:\n"
            f"  - Use schema introspection operations (df.schema, df.dtypes)\n"
            f"  - Switch to pyspark-df platform with Hive metastore or Unity Catalog"
        )

    if category == MetadataOperationCategory.LAKEHOUSE:
        if "delta" in operation.value.lower() or operation in (
            MetadataOperationType.TABLE_HISTORY,
            MetadataOperationType.TABLE_DETAIL,
        ):
            return (
                f"{platform_name} does not support Delta Lake metadata operations ({operation.value}).\n"
                f"Delta Lake operations require:\n"
                f"  - pyspark-df with delta-spark package, or\n"
                f"  - polars with delta support (read-only)"
            )
        if "iceberg" in operation.value.lower() or operation == MetadataOperationType.SNAPSHOT_INFO:
            return (
                f"{platform_name} does not support Iceberg metadata operations ({operation.value}).\n"
                f"Iceberg operations require:\n"
                f"  - pyspark-df with iceberg-spark package, or\n"
                f"  - pyiceberg library"
            )
        return (
            f"{platform_name} does not support lakehouse metadata operations ({operation.value}).\n"
            f"Use pyspark-df with Delta Lake or Iceberg table format."
        )

    return f"{platform_name} does not support {operation.value} operations."


class DataFrameMetadataOperationsManager:
    """Manager for DataFrame metadata introspection operations.

    Provides a unified interface for metadata operations across DataFrame platforms.
    Handles platform capability detection and provides helpful error messages for
    unsupported operations.

    Example:
        manager = DataFrameMetadataOperationsManager("polars-df")

        # Check capabilities
        if manager.supports_operation(MetadataOperationType.GET_SCHEMA):
            result = manager.execute_get_schema(df)

        # Get all supported operations
        ops = manager.get_supported_operations()
    """

    def __init__(
        self,
        platform_name: str,
        spark_session: Any = None,
        delta_available: bool | None = None,
        iceberg_available: bool | None = None,
    ) -> None:
        """Initialize the metadata operations manager.

        Args:
            platform_name: Platform name (e.g., "polars-df", "pyspark-df")
            spark_session: SparkSession instance (required for pyspark-df catalog ops)
            delta_available: Override for Delta Lake availability detection
            iceberg_available: Override for Iceberg availability detection

        Raises:
            ValueError: If platform is not supported for DataFrame operations
        """
        self.platform_name = platform_name.lower()
        self.spark_session = spark_session
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Build capabilities with optional overrides
        overrides = {}

        if "pyspark" in self.platform_name or "spark" in self.platform_name:
            # Detect Delta Lake / Iceberg availability
            if delta_available is None:
                delta_available = self._detect_delta_lake()
            if iceberg_available is None:
                iceberg_available = self._detect_iceberg()

            overrides["supports_delta_lake"] = delta_available
            overrides["supports_iceberg"] = iceberg_available

        self._capabilities = get_platform_capabilities(self.platform_name, **overrides)

    def _detect_delta_lake(self) -> bool:
        """Detect if Delta Lake is available.

        Returns:
            True if delta-spark or deltalake is available
        """
        try:
            import delta  # noqa: F401

            return True
        except ImportError:
            pass

        try:
            import deltalake  # noqa: F401

            return True
        except ImportError:
            pass

        return False

    def _detect_iceberg(self) -> bool:
        """Detect if Iceberg is available.

        Returns:
            True if iceberg-spark or pyiceberg is available
        """
        try:
            import pyiceberg  # noqa: F401

            return True
        except ImportError:
            pass

        # Check for iceberg-spark via SparkSession
        if self.spark_session is not None:
            try:
                # Check if iceberg catalog is configured
                catalogs = self.spark_session.conf.get("spark.sql.catalog", "")
                if "iceberg" in catalogs.lower():
                    return True
            except Exception:
                pass

        return False

    def get_capabilities(self) -> DataFrameMetadataCapabilities:
        """Get platform metadata capabilities.

        Returns:
            DataFrameMetadataCapabilities for this platform
        """
        return self._capabilities

    def supports_operation(self, operation: MetadataOperationType) -> bool:
        """Check if an operation type is supported.

        Args:
            operation: The operation to check

        Returns:
            True if supported
        """
        return self._capabilities.supports_operation(operation)

    def get_supported_operations(self) -> list[MetadataOperationType]:
        """Get list of supported operations.

        Returns:
            List of supported MetadataOperationType values
        """
        return self._capabilities.get_supported_operations()

    def validate_operation(self, operation: MetadataOperationType) -> None:
        """Validate that an operation is supported.

        Args:
            operation: The operation to validate

        Raises:
            UnsupportedOperationError: If operation is not supported
        """
        if not self.supports_operation(operation):
            raise UnsupportedOperationError(
                operation=operation,
                platform_name=self.platform_name,
                suggestion=get_unsupported_message(operation, self.platform_name),
            )

    # =========================================================================
    # Schema Introspection Operations (All Platforms)
    # =========================================================================

    def execute_list_columns(self, dataframe: Any) -> DataFrameMetadataResult:
        """List column names from a DataFrame.

        Args:
            dataframe: The DataFrame to introspect

        Returns:
            DataFrameMetadataResult with column names
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.LIST_COLUMNS)

            if "polars" in self.platform_name:
                columns = dataframe.columns
            elif "pandas" in self.platform_name:
                columns = list(dataframe.columns)
            elif "pyspark" in self.platform_name or "spark" in self.platform_name:
                columns = dataframe.columns
            elif "datafusion" in self.platform_name:
                columns = [field.name for field in dataframe.schema()]
            else:
                # Generic fallback
                columns = list(getattr(dataframe, "columns", []))

            return DataFrameMetadataResult.success_result(
                operation_type=MetadataOperationType.LIST_COLUMNS,
                start_time=start_time,
                result_count=len(columns),
                result_data=columns,
            )

        except UnsupportedOperationError:
            raise
        except Exception as e:
            self.logger.error(f"LIST_COLUMNS failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.LIST_COLUMNS,
                str(e),
                start_time,
            )

    def execute_get_dtypes(self, dataframe: Any) -> DataFrameMetadataResult:
        """Get data types for all columns.

        Args:
            dataframe: The DataFrame to introspect

        Returns:
            DataFrameMetadataResult with column name to dtype mapping
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.GET_DTYPES)

            if "polars" in self.platform_name:
                dtypes = {col: str(dtype) for col, dtype in zip(dataframe.columns, dataframe.dtypes)}
            elif "pandas" in self.platform_name:
                dtypes = {col: str(dtype) for col, dtype in dataframe.dtypes.items()}
            elif "pyspark" in self.platform_name or "spark" in self.platform_name:
                dtypes = {field.name: str(field.dataType) for field in dataframe.schema.fields}
            elif "datafusion" in self.platform_name:
                dtypes = {field.name: str(field.type) for field in dataframe.schema()}
            else:
                # Generic fallback
                dtypes = {}
                if hasattr(dataframe, "dtypes"):
                    dtypes = dict(dataframe.dtypes)

            return DataFrameMetadataResult.success_result(
                operation_type=MetadataOperationType.GET_DTYPES,
                start_time=start_time,
                result_count=len(dtypes),
                result_data=dtypes,
            )

        except UnsupportedOperationError:
            raise
        except Exception as e:
            self.logger.error(f"GET_DTYPES failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.GET_DTYPES,
                str(e),
                start_time,
            )

    def execute_get_schema(self, dataframe: Any) -> DataFrameMetadataResult:
        """Get full schema information for a DataFrame.

        Args:
            dataframe: The DataFrame to introspect

        Returns:
            DataFrameMetadataResult with schema dict (name, dtype, nullable)
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.GET_SCHEMA)

            schema_info: list[dict[str, Any]] = []

            if "polars" in self.platform_name:
                for col, dtype in zip(dataframe.columns, dataframe.dtypes):
                    schema_info.append(
                        {
                            "name": col,
                            "dtype": str(dtype),
                            "nullable": True,  # Polars columns are nullable by default
                        }
                    )
            elif "pandas" in self.platform_name:
                for col, dtype in dataframe.dtypes.items():
                    schema_info.append(
                        {
                            "name": col,
                            "dtype": str(dtype),
                            "nullable": dataframe[col].isna().any(),
                        }
                    )
            elif "pyspark" in self.platform_name or "spark" in self.platform_name:
                for field in dataframe.schema.fields:
                    schema_info.append(
                        {
                            "name": field.name,
                            "dtype": str(field.dataType),
                            "nullable": field.nullable,
                        }
                    )
            elif "datafusion" in self.platform_name:
                for field in dataframe.schema():
                    schema_info.append(
                        {
                            "name": field.name,
                            "dtype": str(field.type),
                            "nullable": field.is_nullable,
                        }
                    )
            else:
                # Generic fallback
                if hasattr(dataframe, "columns") and hasattr(dataframe, "dtypes"):
                    for col, dtype in zip(dataframe.columns, dataframe.dtypes):
                        schema_info.append({"name": col, "dtype": str(dtype), "nullable": True})

            return DataFrameMetadataResult.success_result(
                operation_type=MetadataOperationType.GET_SCHEMA,
                start_time=start_time,
                result_count=len(schema_info),
                result_data=schema_info,
            )

        except UnsupportedOperationError:
            raise
        except Exception as e:
            self.logger.error(f"GET_SCHEMA failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.GET_SCHEMA,
                str(e),
                start_time,
            )

    def execute_describe_stats(self, dataframe: Any) -> DataFrameMetadataResult:
        """Get summary statistics for a DataFrame.

        Args:
            dataframe: The DataFrame to introspect

        Returns:
            DataFrameMetadataResult with statistics DataFrame/dict
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.DESCRIBE_STATS)

            if "polars" in self.platform_name:
                stats_df = dataframe.describe()
                result_data = stats_df.to_dicts()
                result_count = stats_df.height
            elif "pandas" in self.platform_name:
                stats_df = dataframe.describe()
                result_data = stats_df.to_dict()
                result_count = len(stats_df)
            elif "pyspark" in self.platform_name or "spark" in self.platform_name:
                stats_df = dataframe.describe()
                result_data = stats_df.collect()
                result_count = stats_df.count()
            elif "datafusion" in self.platform_name:
                # DataFusion doesn't have describe() yet
                result_data = None
                result_count = 0
            else:
                result_data = None
                result_count = 0

            return DataFrameMetadataResult.success_result(
                operation_type=MetadataOperationType.DESCRIBE_STATS,
                start_time=start_time,
                result_count=result_count,
                result_data=result_data,
            )

        except UnsupportedOperationError:
            raise
        except Exception as e:
            self.logger.error(f"DESCRIBE_STATS failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.DESCRIBE_STATS,
                str(e),
                start_time,
            )

    def execute_row_count(self, dataframe: Any) -> DataFrameMetadataResult:
        """Get row count for a DataFrame.

        Note: This may require full scan on lazy/distributed platforms.

        Args:
            dataframe: The DataFrame to count

        Returns:
            DataFrameMetadataResult with row count
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.ROW_COUNT)

            if "polars" in self.platform_name:
                count = dataframe.height
            elif "pandas" in self.platform_name:
                count = len(dataframe)
            elif "pyspark" in self.platform_name or "spark" in self.platform_name or "datafusion" in self.platform_name:
                count = dataframe.count()
            else:
                count = len(dataframe) if hasattr(dataframe, "__len__") else 0

            return DataFrameMetadataResult.success_result(
                operation_type=MetadataOperationType.ROW_COUNT,
                start_time=start_time,
                result_count=1,
                result_data=count,
                metrics={"row_count": count},
            )

        except UnsupportedOperationError:
            raise
        except Exception as e:
            self.logger.error(f"ROW_COUNT failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.ROW_COUNT,
                str(e),
                start_time,
            )

    def execute_column_count(self, dataframe: Any) -> DataFrameMetadataResult:
        """Get column count for a DataFrame.

        Args:
            dataframe: The DataFrame to count

        Returns:
            DataFrameMetadataResult with column count
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.COLUMN_COUNT)

            if "polars" in self.platform_name:
                count = dataframe.width
            elif "pandas" in self.platform_name or "pyspark" in self.platform_name or "spark" in self.platform_name:
                count = len(dataframe.columns)
            elif "datafusion" in self.platform_name:
                count = len(dataframe.schema())
            else:
                count = len(getattr(dataframe, "columns", []))

            return DataFrameMetadataResult.success_result(
                operation_type=MetadataOperationType.COLUMN_COUNT,
                start_time=start_time,
                result_count=1,
                result_data=count,
                metrics={"column_count": count},
            )

        except UnsupportedOperationError:
            raise
        except Exception as e:
            self.logger.error(f"COLUMN_COUNT failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.COLUMN_COUNT,
                str(e),
                start_time,
            )

    # =========================================================================
    # Catalog Operations (PySpark with Catalog)
    # =========================================================================

    def execute_list_databases(self) -> DataFrameMetadataResult:
        """List all databases in the catalog.

        Requires PySpark with configured catalog.

        Returns:
            DataFrameMetadataResult with database names
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.LIST_DATABASES)

            if self.spark_session is None:
                return DataFrameMetadataResult.failure_result(
                    MetadataOperationType.LIST_DATABASES,
                    "SparkSession is required for catalog operations. "
                    "Pass spark_session to DataFrameMetadataOperationsManager.",
                    start_time,
                )

            databases = self.spark_session.catalog.listDatabases()
            db_names = [db.name for db in databases]

            return DataFrameMetadataResult.success_result(
                operation_type=MetadataOperationType.LIST_DATABASES,
                start_time=start_time,
                result_count=len(db_names),
                result_data=db_names,
            )

        except UnsupportedOperationError:
            raise
        except Exception as e:
            self.logger.error(f"LIST_DATABASES failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.LIST_DATABASES,
                str(e),
                start_time,
            )

    def execute_list_tables(self, database: str | None = None) -> DataFrameMetadataResult:
        """List all tables in a database.

        Requires PySpark with configured catalog.

        Args:
            database: Database name (uses current database if None)

        Returns:
            DataFrameMetadataResult with table names
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.LIST_TABLES)

            if self.spark_session is None:
                return DataFrameMetadataResult.failure_result(
                    MetadataOperationType.LIST_TABLES,
                    "SparkSession is required for catalog operations.",
                    start_time,
                )

            if database:
                tables = self.spark_session.catalog.listTables(database)
            else:
                tables = self.spark_session.catalog.listTables()

            table_info = [{"name": t.name, "database": t.database, "tableType": t.tableType} for t in tables]

            return DataFrameMetadataResult.success_result(
                operation_type=MetadataOperationType.LIST_TABLES,
                start_time=start_time,
                result_count=len(table_info),
                result_data=table_info,
            )

        except UnsupportedOperationError:
            raise
        except Exception as e:
            self.logger.error(f"LIST_TABLES failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.LIST_TABLES,
                str(e),
                start_time,
            )

    def execute_list_table_columns(self, table_name: str, database: str | None = None) -> DataFrameMetadataResult:
        """List columns for a specific table in the catalog.

        Requires PySpark with configured catalog.

        Args:
            table_name: Name of the table
            database: Database name (uses current database if None)

        Returns:
            DataFrameMetadataResult with column information
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.LIST_TABLE_COLUMNS)

            if self.spark_session is None:
                return DataFrameMetadataResult.failure_result(
                    MetadataOperationType.LIST_TABLE_COLUMNS,
                    "SparkSession is required for catalog operations.",
                    start_time,
                )

            if database:
                columns = self.spark_session.catalog.listColumns(table_name, database)
            else:
                columns = self.spark_session.catalog.listColumns(table_name)

            column_info = [
                {
                    "name": c.name,
                    "dataType": c.dataType,
                    "nullable": c.nullable,
                    "description": c.description,
                }
                for c in columns
            ]

            return DataFrameMetadataResult.success_result(
                operation_type=MetadataOperationType.LIST_TABLE_COLUMNS,
                start_time=start_time,
                result_count=len(column_info),
                result_data=column_info,
            )

        except UnsupportedOperationError:
            raise
        except Exception as e:
            self.logger.error(f"LIST_TABLE_COLUMNS failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.LIST_TABLE_COLUMNS,
                str(e),
                start_time,
            )

    def execute_table_exists(self, table_name: str, database: str | None = None) -> DataFrameMetadataResult:
        """Check if a table exists in the catalog.

        Requires PySpark with configured catalog.

        Args:
            table_name: Name of the table
            database: Database name (uses current database if None)

        Returns:
            DataFrameMetadataResult with exists boolean
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.TABLE_EXISTS)

            if self.spark_session is None:
                return DataFrameMetadataResult.failure_result(
                    MetadataOperationType.TABLE_EXISTS,
                    "SparkSession is required for catalog operations.",
                    start_time,
                )

            if database:
                full_name = f"{database}.{table_name}"
            else:
                full_name = table_name

            exists = self.spark_session.catalog.tableExists(full_name)

            return DataFrameMetadataResult.success_result(
                operation_type=MetadataOperationType.TABLE_EXISTS,
                start_time=start_time,
                result_count=1 if exists else 0,
                result_data=exists,
            )

        except UnsupportedOperationError:
            raise
        except Exception as e:
            self.logger.error(f"TABLE_EXISTS failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.TABLE_EXISTS,
                str(e),
                start_time,
            )

    def execute_get_table_info(self, table_name: str, database: str | None = None) -> DataFrameMetadataResult:
        """Get detailed information about a table.

        Requires PySpark with configured catalog.

        Args:
            table_name: Name of the table
            database: Database name (uses current database if None)

        Returns:
            DataFrameMetadataResult with table metadata
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.GET_TABLE_INFO)

            if self.spark_session is None:
                return DataFrameMetadataResult.failure_result(
                    MetadataOperationType.GET_TABLE_INFO,
                    "SparkSession is required for catalog operations.",
                    start_time,
                )

            if database:
                full_name = f"{database}.{table_name}"
            else:
                full_name = table_name

            table = self.spark_session.catalog.getTable(full_name)

            table_info = {
                "name": table.name,
                "database": table.database,
                "tableType": table.tableType,
                "description": table.description,
                "isTemporary": table.isTemporary,
            }

            return DataFrameMetadataResult.success_result(
                operation_type=MetadataOperationType.GET_TABLE_INFO,
                start_time=start_time,
                result_count=1,
                result_data=table_info,
            )

        except UnsupportedOperationError:
            raise
        except Exception as e:
            self.logger.error(f"GET_TABLE_INFO failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.GET_TABLE_INFO,
                str(e),
                start_time,
            )

    # =========================================================================
    # Lakehouse Metadata Operations (Delta Lake / Iceberg)
    # =========================================================================

    def execute_table_history(self, table_path: str) -> DataFrameMetadataResult:
        """Get transaction history for a Delta Lake table.

        Requires Delta Lake support.

        Args:
            table_path: Path to the Delta table

        Returns:
            DataFrameMetadataResult with transaction history
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.TABLE_HISTORY)

            if self.spark_session is not None:
                # Use DeltaTable API
                from delta.tables import DeltaTable

                delta_table = DeltaTable.forPath(self.spark_session, table_path)
                history_df = delta_table.history()
                history = history_df.collect()

                return DataFrameMetadataResult.success_result(
                    operation_type=MetadataOperationType.TABLE_HISTORY,
                    start_time=start_time,
                    result_count=len(history),
                    result_data=[row.asDict() for row in history],
                )
            else:
                # Use deltalake Python library
                from deltalake import DeltaTable as PyDeltaTable

                dt = PyDeltaTable(table_path)
                history = list(dt.history())

                return DataFrameMetadataResult.success_result(
                    operation_type=MetadataOperationType.TABLE_HISTORY,
                    start_time=start_time,
                    result_count=len(history),
                    result_data=history,
                )

        except UnsupportedOperationError:
            raise
        except ImportError as e:
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.TABLE_HISTORY,
                f"Delta Lake library not available: {e}",
                start_time,
            )
        except Exception as e:
            self.logger.error(f"TABLE_HISTORY failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.TABLE_HISTORY,
                str(e),
                start_time,
            )

    def execute_table_detail(self, table_path: str) -> DataFrameMetadataResult:
        """Get detailed metadata for a Delta Lake table.

        Requires Delta Lake support.

        Args:
            table_path: Path to the Delta table

        Returns:
            DataFrameMetadataResult with table detail
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.TABLE_DETAIL)

            if self.spark_session is not None:
                # Use DeltaTable API
                from delta.tables import DeltaTable

                delta_table = DeltaTable.forPath(self.spark_session, table_path)
                detail_df = delta_table.detail()
                detail = detail_df.collect()[0].asDict()

                return DataFrameMetadataResult.success_result(
                    operation_type=MetadataOperationType.TABLE_DETAIL,
                    start_time=start_time,
                    result_count=1,
                    result_data=detail,
                )
            else:
                # Use deltalake Python library
                from deltalake import DeltaTable as PyDeltaTable

                dt = PyDeltaTable(table_path)
                metadata = dt.metadata()

                detail = {
                    "id": metadata.id,
                    "name": metadata.name,
                    "description": metadata.description,
                    "partitionColumns": metadata.partition_columns,
                    "createdTime": metadata.created_time,
                }

                return DataFrameMetadataResult.success_result(
                    operation_type=MetadataOperationType.TABLE_DETAIL,
                    start_time=start_time,
                    result_count=1,
                    result_data=detail,
                )

        except UnsupportedOperationError:
            raise
        except ImportError as e:
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.TABLE_DETAIL,
                f"Delta Lake library not available: {e}",
                start_time,
            )
        except Exception as e:
            self.logger.error(f"TABLE_DETAIL failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.TABLE_DETAIL,
                str(e),
                start_time,
            )

    def execute_file_metadata(self, table_path: str) -> DataFrameMetadataResult:
        """Get file-level metadata for a lakehouse table.

        Requires Delta Lake or Iceberg support.

        Args:
            table_path: Path to the table

        Returns:
            DataFrameMetadataResult with file metadata
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.FILE_METADATA)

            if self._capabilities.supports_delta_lake:
                # Delta Lake file metadata
                if self.spark_session is not None:
                    from delta.tables import DeltaTable

                    delta_table = DeltaTable.forPath(self.spark_session, table_path)
                    # Get files via detail or internal API
                    detail = delta_table.detail().collect()[0]
                    files = {
                        "numFiles": detail.numFiles if hasattr(detail, "numFiles") else None,
                        "sizeInBytes": detail.sizeInBytes if hasattr(detail, "sizeInBytes") else None,
                    }
                else:
                    from deltalake import DeltaTable as PyDeltaTable

                    dt = PyDeltaTable(table_path)
                    file_uris = dt.file_uris()
                    files = {
                        "numFiles": len(file_uris),
                        "files": file_uris[:100],  # Limit for large tables
                    }

                return DataFrameMetadataResult.success_result(
                    operation_type=MetadataOperationType.FILE_METADATA,
                    start_time=start_time,
                    result_count=files.get("numFiles", 0),
                    result_data=files,
                )

            elif self._capabilities.supports_iceberg:
                # Iceberg file metadata - requires catalog configuration
                # Note: pyiceberg.catalog and pyiceberg.table would be used here
                # but require proper catalog setup which is outside scope of basic introspection
                return DataFrameMetadataResult.failure_result(
                    MetadataOperationType.FILE_METADATA,
                    "Iceberg file metadata requires catalog configuration",
                    start_time,
                )

            else:
                return DataFrameMetadataResult.failure_result(
                    MetadataOperationType.FILE_METADATA,
                    "No lakehouse format available for file metadata",
                    start_time,
                )

        except UnsupportedOperationError:
            raise
        except ImportError as e:
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.FILE_METADATA,
                f"Lakehouse library not available: {e}",
                start_time,
            )
        except Exception as e:
            self.logger.error(f"FILE_METADATA failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.FILE_METADATA,
                str(e),
                start_time,
            )

    def execute_partition_info(self, table_path: str) -> DataFrameMetadataResult:
        """Get partition information for a table.

        Requires PySpark or lakehouse table format.

        Args:
            table_path: Path to the table

        Returns:
            DataFrameMetadataResult with partition info
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.PARTITION_INFO)

            if self.spark_session is not None and self._capabilities.supports_delta_lake:
                from delta.tables import DeltaTable

                delta_table = DeltaTable.forPath(self.spark_session, table_path)
                detail = delta_table.detail().collect()[0]
                partitions = {
                    "partitionColumns": list(detail.partitionColumns) if detail.partitionColumns else [],
                    "numPartitions": len(detail.partitionColumns) if detail.partitionColumns else 0,
                }

                return DataFrameMetadataResult.success_result(
                    operation_type=MetadataOperationType.PARTITION_INFO,
                    start_time=start_time,
                    result_count=partitions["numPartitions"],
                    result_data=partitions,
                )

            elif self._capabilities.supports_delta_lake:
                # Use standalone deltalake Python library (no SparkSession)
                from deltalake import DeltaTable as PyDeltaTable

                dt = PyDeltaTable(table_path)
                metadata = dt.metadata()
                partitions = {
                    "partitionColumns": metadata.partition_columns,
                    "numPartitions": len(metadata.partition_columns),
                }

                return DataFrameMetadataResult.success_result(
                    operation_type=MetadataOperationType.PARTITION_INFO,
                    start_time=start_time,
                    result_count=partitions["numPartitions"],
                    result_data=partitions,
                )

            else:
                return DataFrameMetadataResult.failure_result(
                    MetadataOperationType.PARTITION_INFO,
                    "Partition info requires Delta Lake or Iceberg table format",
                    start_time,
                )

        except UnsupportedOperationError:
            raise
        except ImportError as e:
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.PARTITION_INFO,
                f"Lakehouse library not available: {e}",
                start_time,
            )
        except Exception as e:
            self.logger.error(f"PARTITION_INFO failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.PARTITION_INFO,
                str(e),
                start_time,
            )

    def execute_snapshot_info(self, table_path: str) -> DataFrameMetadataResult:
        """Get snapshot information for an Iceberg table.

        Requires Iceberg support.

        Args:
            table_path: Path or identifier for the Iceberg table

        Returns:
            DataFrameMetadataResult with snapshot info
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.SNAPSHOT_INFO)

            # This requires proper Iceberg catalog configuration
            # Simplified implementation for now
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.SNAPSHOT_INFO,
                "Iceberg snapshot info requires catalog configuration. "
                "Configure Iceberg catalog in your Spark session or use pyiceberg with proper catalog.",
                start_time,
            )

        except UnsupportedOperationError:
            raise
        except Exception as e:
            self.logger.error(f"SNAPSHOT_INFO failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.SNAPSHOT_INFO,
                str(e),
                start_time,
            )

    # =========================================================================
    # Complexity Testing Operations
    # =========================================================================

    def execute_wide_table_schema(self, dataframe: Any) -> DataFrameMetadataResult:
        """Introspect schema of a wide DataFrame (100+ columns).

        Tests metadata introspection performance on DataFrames with many columns.
        This is useful for benchmarking schema discovery performance.

        Args:
            dataframe: A wide DataFrame with many columns

        Returns:
            DataFrameMetadataResult with schema info and metrics
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.WIDE_TABLE_SCHEMA)

            # Get column count
            if "polars" in self.platform_name:
                column_count = dataframe.width
                schema_info = [
                    {"name": col, "dtype": str(dtype)} for col, dtype in zip(dataframe.columns, dataframe.dtypes)
                ]
            elif "pandas" in self.platform_name:
                column_count = len(dataframe.columns)
                schema_info = [{"name": col, "dtype": str(dtype)} for col, dtype in dataframe.dtypes.items()]
            elif "pyspark" in self.platform_name or "spark" in self.platform_name:
                column_count = len(dataframe.columns)
                schema_info = [{"name": f.name, "dtype": str(f.dataType)} for f in dataframe.schema.fields]
            else:
                column_count = len(getattr(dataframe, "columns", []))
                schema_info = []

            return DataFrameMetadataResult.success_result(
                operation_type=MetadataOperationType.WIDE_TABLE_SCHEMA,
                start_time=start_time,
                result_count=column_count,
                result_data=schema_info,
                metrics={
                    "column_count": column_count,
                    "is_wide_table": column_count >= 100,
                },
            )

        except UnsupportedOperationError:
            raise
        except Exception as e:
            self.logger.error(f"WIDE_TABLE_SCHEMA failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.WIDE_TABLE_SCHEMA,
                str(e),
                start_time,
            )

    def execute_large_catalog_list(self) -> DataFrameMetadataResult:
        """List tables in a large catalog (100+ tables).

        Tests catalog introspection performance with many tables.
        Requires PySpark with configured catalog.

        Returns:
            DataFrameMetadataResult with table list and metrics
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.LARGE_CATALOG_LIST)

            if self.spark_session is None:
                return DataFrameMetadataResult.failure_result(
                    MetadataOperationType.LARGE_CATALOG_LIST,
                    "SparkSession is required for catalog operations.",
                    start_time,
                )

            # Get all tables across all databases
            tables_result = []
            databases = self.spark_session.catalog.listDatabases()

            for db in databases:
                try:
                    tables = self.spark_session.catalog.listTables(db.name)
                    for t in tables:
                        tables_result.append({"name": t.name, "database": db.name, "tableType": t.tableType})
                except Exception as e:
                    self.logger.debug(f"Skipping database {db.name}: {e}")

            table_count = len(tables_result)

            return DataFrameMetadataResult.success_result(
                operation_type=MetadataOperationType.LARGE_CATALOG_LIST,
                start_time=start_time,
                result_count=table_count,
                result_data=tables_result,
                metrics={
                    "table_count": table_count,
                    "database_count": len(databases),
                    "is_large_catalog": table_count >= 100,
                },
            )

        except UnsupportedOperationError:
            raise
        except Exception as e:
            self.logger.error(f"LARGE_CATALOG_LIST failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.LARGE_CATALOG_LIST,
                str(e),
                start_time,
            )

    def execute_complex_type_introspection(self, dataframe: Any) -> DataFrameMetadataResult:
        """Introspect complex/nested types in a DataFrame.

        Tests metadata introspection for DataFrames containing complex types
        like ARRAY, STRUCT, MAP, and nested structures.

        Args:
            dataframe: DataFrame with complex nested types

        Returns:
            DataFrameMetadataResult with type analysis
        """
        start_time = time.time()

        try:
            self.validate_operation(MetadataOperationType.COMPLEX_TYPE_INTROSPECTION)

            complex_types = []
            nested_depth = 0

            if "polars" in self.platform_name:
                import polars as pl

                for col, dtype in zip(dataframe.columns, dataframe.dtypes):
                    type_info = self._analyze_polars_type(col, dtype, pl)
                    if type_info.get("is_complex"):
                        complex_types.append(type_info)
                        nested_depth = max(nested_depth, type_info.get("nested_depth", 0))

            elif "pyspark" in self.platform_name or "spark" in self.platform_name:
                from pyspark.sql.types import ArrayType, MapType, StructType

                for field in dataframe.schema.fields:
                    type_info = self._analyze_spark_type(field, ArrayType, MapType, StructType)
                    if type_info.get("is_complex"):
                        complex_types.append(type_info)
                        nested_depth = max(nested_depth, type_info.get("nested_depth", 0))

            elif "pandas" in self.platform_name:
                # Pandas has limited complex type support
                for col, dtype in dataframe.dtypes.items():
                    if str(dtype) == "object":
                        # Could contain nested structures
                        complex_types.append(
                            {
                                "name": col,
                                "dtype": str(dtype),
                                "is_complex": True,
                                "complex_type": "object",
                                "nested_depth": 1,
                            }
                        )

            return DataFrameMetadataResult.success_result(
                operation_type=MetadataOperationType.COMPLEX_TYPE_INTROSPECTION,
                start_time=start_time,
                result_count=len(complex_types),
                result_data=complex_types,
                metrics={
                    "complex_column_count": len(complex_types),
                    "max_nested_depth": nested_depth,
                    "has_arrays": any(t.get("complex_type") == "array" for t in complex_types),
                    "has_structs": any(t.get("complex_type") == "struct" for t in complex_types),
                    "has_maps": any(t.get("complex_type") == "map" for t in complex_types),
                },
            )

        except UnsupportedOperationError:
            raise
        except Exception as e:
            self.logger.error(f"COMPLEX_TYPE_INTROSPECTION failed: {e}")
            return DataFrameMetadataResult.failure_result(
                MetadataOperationType.COMPLEX_TYPE_INTROSPECTION,
                str(e),
                start_time,
            )

    def _analyze_polars_type(self, col_name: str, dtype: Any, pl: Any) -> dict[str, Any]:
        """Analyze a Polars data type for complexity.

        Args:
            col_name: Column name
            dtype: Polars data type
            pl: Polars module

        Returns:
            Type analysis dict
        """
        dtype_str = str(dtype)
        is_complex = False
        complex_type = None
        nested_depth = 0

        if dtype_str.startswith("List"):
            is_complex = True
            complex_type = "array"
            nested_depth = dtype_str.count("List") + dtype_str.count("Struct")
        elif dtype_str.startswith("Struct"):
            is_complex = True
            complex_type = "struct"
            nested_depth = dtype_str.count("Struct")

        return {
            "name": col_name,
            "dtype": dtype_str,
            "is_complex": is_complex,
            "complex_type": complex_type,
            "nested_depth": nested_depth,
        }

    def _analyze_spark_type(self, field: Any, ArrayType: type, MapType: type, StructType: type) -> dict[str, Any]:
        """Analyze a Spark schema field for complexity.

        Args:
            field: Spark StructField
            ArrayType: Spark ArrayType class
            MapType: Spark MapType class
            StructType: Spark StructType class

        Returns:
            Type analysis dict
        """
        dtype = field.dataType
        is_complex = False
        complex_type = None
        nested_depth = 0

        def count_depth(t: Any, depth: int = 0) -> int:
            if isinstance(t, ArrayType):
                return count_depth(t.elementType, depth + 1)
            elif isinstance(t, MapType):
                return max(count_depth(t.keyType, depth + 1), count_depth(t.valueType, depth + 1))
            elif isinstance(t, StructType):
                if t.fields:
                    return max(count_depth(f.dataType, depth + 1) for f in t.fields)
                return depth + 1
            return depth

        if isinstance(dtype, ArrayType):
            is_complex = True
            complex_type = "array"
            nested_depth = count_depth(dtype)
        elif isinstance(dtype, MapType):
            is_complex = True
            complex_type = "map"
            nested_depth = count_depth(dtype)
        elif isinstance(dtype, StructType):
            is_complex = True
            complex_type = "struct"
            nested_depth = count_depth(dtype)

        return {
            "name": field.name,
            "dtype": str(dtype),
            "is_complex": is_complex,
            "complex_type": complex_type,
            "nested_depth": nested_depth,
        }


def get_dataframe_metadata_manager(
    platform_name: str,
    spark_session: Any = None,
) -> DataFrameMetadataOperationsManager | None:
    """Get a DataFrame metadata operations manager for a platform.

    Args:
        platform_name: Platform name (e.g., "polars-df", "pandas-df", "pyspark-df")
        spark_session: SparkSession instance (required for pyspark-df catalog ops)

    Returns:
        DataFrameMetadataOperationsManager if platform supports DataFrame operations,
        None if platform is not a DataFrame platform.
    """
    return get_dataframe_manager(
        platform_name,
        manager_class=DataFrameMetadataOperationsManager,
        supported_platforms=("polars-df", "polars", "pandas-df", "pandas", "pyspark-df", "pyspark", "datafusion"),
        logger=logger,
        manager_label="metadata",
        spark_session=spark_session,
    )


__all__ = [
    # Enums
    "MetadataOperationType",
    "MetadataOperationCategory",
    "OPERATION_CATEGORIES",
    # Capabilities
    "DataFrameMetadataCapabilities",
    "get_platform_capabilities",
    "POLARS_METADATA_CAPABILITIES",
    "PANDAS_METADATA_CAPABILITIES",
    "PYSPARK_METADATA_CAPABILITIES",
    "DATAFUSION_METADATA_CAPABILITIES",
    # Results
    "DataFrameMetadataResult",
    # Errors
    "UnsupportedOperationError",
    "get_unsupported_message",
    # Manager
    "DataFrameMetadataOperationsManager",
    "get_dataframe_metadata_manager",
]
