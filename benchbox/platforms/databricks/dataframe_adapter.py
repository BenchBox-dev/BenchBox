"""Databricks DataFrame adapter for expression-family benchmarking.

This module provides the DatabricksDataFrameAdapter that enables DataFrame-based
benchmark execution on Databricks using the PySpark DataFrame API.

The adapter extends DatabricksAdapter to reuse 100% of the existing infrastructure:
- Connection management (databricks-sql-connector)
- UC Volume staging and upload
- Delta Lake table creation
- Authentication and credential handling

It adds DataFrame execution capabilities:
- Accept DataFrame expressions instead of SQL strings
- Execute queries using Spark Connect or Databricks Connect
- Support filter, groupBy, agg, join expression building

Usage:
    from benchbox.platforms.databricks.dataframe_adapter import DatabricksDataFrameAdapter

    adapter = DatabricksDataFrameAdapter(
        server_hostname="xxx.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/abc123",
        access_token="dapi...",
    )

    # Use the existing SQL infrastructure for schema/data loading
    connection = adapter.create_connection()
    adapter.create_schema(benchmark, connection)
    adapter.load_data(benchmark, connection, data_dir)

    # Execute DataFrame-based queries
    result = adapter.execute_dataframe_query(connection, df_query, "Q1")

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from benchbox.platforms.databricks.adapter import DatabricksAdapter
from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.dependencies import get_package_install_message

if TYPE_CHECKING:
    from pyspark.sql import DataFrame as SparkDataFrame, SparkSession

logger = logging.getLogger(__name__)


# Check if Databricks Connect is available
try:
    from databricks.connect import DatabricksSession

    DATABRICKS_CONNECT_AVAILABLE = True
    _databricks_connect_error: str | None = None
except ImportError:
    DATABRICKS_CONNECT_AVAILABLE = False
    DatabricksSession = None  # type: ignore[assignment,misc]
    _databricks_connect_error = None
except Exception as exc:  # pragma: no cover - defensive guard
    # Some databricks-connect builds crash during import when PySpark lacks
    # optional shims (e.g., SparkSession.Hook). Treat that as unavailable.
    DATABRICKS_CONNECT_AVAILABLE = False
    DatabricksSession = None  # type: ignore[assignment,misc]
    _databricks_connect_error = str(exc)

# Check if PySpark is available for local execution contexts.
try:
    from pyspark.sql import (
        DataFrame as SparkDataFrame,
        SparkSession,
        functions as F,  # noqa: N812
    )

    PYSPARK_AVAILABLE = True
except ImportError:
    PYSPARK_AVAILABLE = False
    SparkDataFrame = Any  # type: ignore[assignment,misc]
    SparkSession = Any  # type: ignore[assignment,misc]
    F = None  # type: ignore[assignment]


class DatabricksDataFrameAdapter(DatabricksAdapter):
    """Databricks DataFrame adapter for expression-family benchmarking.

    Extends DatabricksAdapter to support DataFrame-based query execution
    using Databricks Connect or Spark Connect. All SQL-based infrastructure
    (connection, schema, data loading) is inherited from DatabricksAdapter.

    This adapter provides:
    - DataFrame execution mode for Databricks
    - Spark Connect protocol support via Databricks Connect
    - Integration with expression-family benchmark queries
    - Full access to PySpark DataFrame API on Databricks clusters

    Attributes:
        cluster_id: Optional Databricks cluster ID for Databricks Connect
        execution_mode: "sql" or "dataframe" (default: "dataframe")
    """

    plan_capture_phase_eligible = True

    def __init__(self, **config: Any) -> None:
        """Initialize Databricks DataFrame adapter.

        Args:
            **config: Configuration passed to DatabricksAdapter, plus:
                cluster_id: Databricks cluster ID for Databricks Connect
                execution_mode: "sql" or "dataframe" (default: "dataframe")

        Raises:
            ImportError: If required dependencies are not installed
        """
        # Extract DataFrame-specific config before passing to parent
        self.cluster_id = config.pop("cluster_id", None)
        self.execution_mode = config.pop("execution_mode", "dataframe")

        # Initialize parent adapter (handles SQL connection, UC Volumes, etc.)
        super().__init__(**config)

        # Verify DataFrame mode dependencies
        if self.execution_mode == "dataframe" and not DATABRICKS_CONNECT_AVAILABLE:
            reason = (
                f"Databricks Connect import failed ({_databricks_connect_error})"
                if _databricks_connect_error
                else "Databricks Connect not installed"
            )
            logger.warning(
                "%s. DataFrame mode requires: uv add databricks-connect. Falling back to SQL mode.",
                reason,
            )
            self.execution_mode = "sql"

        # Spark session for DataFrame execution (created lazily)
        self._spark: SparkSession | None = None
        self._spark_initialized = False

    @property
    def platform_name(self) -> str:
        """Return platform name with execution mode."""
        mode_suffix = "-df" if self.execution_mode == "dataframe" else ""
        return f"Databricks{mode_suffix}"

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> DatabricksDataFrameAdapter:
        """Create Databricks DataFrame adapter from unified configuration.

        Args:
            config: Configuration dictionary with Databricks and DataFrame settings

        Returns:
            Configured DatabricksDataFrameAdapter instance
        """
        # Extract DataFrame-specific settings
        adapter_config = dict(config)
        adapter_config["execution_mode"] = config.get("execution_mode", "dataframe")
        adapter_config["cluster_id"] = config.get("cluster_id")

        return cls(**adapter_config)

    def _get_or_create_spark_session(self) -> SparkSession:
        """Get or create a Databricks Connect Spark session.

        Returns:
            SparkSession connected to Databricks cluster

        Raises:
            ImportError: If Databricks Connect is not available
            RuntimeError: If session creation fails
        """
        if self._spark is not None:
            return self._spark

        if not DATABRICKS_CONNECT_AVAILABLE:
            raise ImportError(
                get_package_install_message("databricks-connect", "Databricks Connect required for DataFrame mode.")
            )

        try:
            # Build Databricks Connect session
            builder = DatabricksSession.builder

            # Set host from adapter config
            if self.server_hostname:
                host = f"https://{self.server_hostname}"
                builder = builder.host(host)

            # Set token for authentication
            if self.access_token:
                builder = builder.token(self.access_token)

            # Set cluster ID if provided
            if self.cluster_id:
                builder = builder.clusterId(self.cluster_id)

            # Create session
            self._spark = builder.getOrCreate()
            self._spark_initialized = True

            self.log_verbose(f"Databricks Connect session created: {self.server_hostname}")

            return self._spark

        except Exception as e:
            raise RuntimeError(f"Failed to create Databricks Connect session: {e}") from e

    @property
    def spark(self) -> SparkSession:
        """Access the Databricks Connect Spark session."""
        return self._get_or_create_spark_session()

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get platform information including DataFrame mode details.

        Args:
            connection: Optional SQL connection for base adapter info

        Returns:
            Platform information dictionary with DataFrame mode details
        """
        # Get base platform info from parent
        info = super().get_platform_info(connection)

        # Add DataFrame mode information
        info["execution_mode"] = self.execution_mode
        info["cluster_id"] = self.cluster_id
        info["databricks_connect_available"] = DATABRICKS_CONNECT_AVAILABLE

        if self.execution_mode == "dataframe" and self._spark_initialized:
            try:
                info["spark_version"] = self._spark.version if self._spark else None
            except Exception:
                info["spark_version"] = None

        return info

    def execute_dataframe_query(
        self,
        connection: Any,
        query_builder: Callable[[SparkSession, dict[str, SparkDataFrame]], SparkDataFrame],
        query_id: str,
        tables: dict[str, str] | None = None,
        benchmark_type: str | None = None,
        scale_factor: float | None = None,
        validate_row_count: bool = True,
        stream_id: int | None = None,
    ) -> dict[str, Any]:
        """Execute a DataFrame-based query on Databricks.

        This method executes a query built using PySpark DataFrame API
        rather than a SQL string. The query_builder function receives the
        SparkSession and registered tables, and returns a DataFrame result.

        Args:
            connection: SQL connection (used for table context)
            query_builder: Function that builds and returns the query DataFrame
            query_id: Query identifier (e.g., "Q1", "Q6")
            tables: Optional dict mapping table names to table paths
            benchmark_type: Benchmark type for validation
            scale_factor: Scale factor for validation
            validate_row_count: Whether to validate row count
            stream_id: Stream ID for throughput tests

        Returns:
            Query result dictionary with timing and row count

        Example:
            def q1_builder(spark: SparkSession, tables: dict) -> DataFrame:
                lineitem = spark.table("lineitem")
                return (
                    lineitem
                    .filter(F.col("l_shipdate") <= F.lit("1998-09-02"))
                    .groupBy("l_returnflag", "l_linestatus")
                    .agg(
                        F.sum("l_quantity").alias("sum_qty"),
                        F.sum("l_extendedprice").alias("sum_base_price"),
                    )
                    .orderBy("l_returnflag", "l_linestatus")
                )

            result = adapter.execute_dataframe_query(
                connection, q1_builder, "Q1"
            )
        """
        start_time = mono_time()
        self.log_verbose(f"Executing DataFrame query {query_id}")

        try:
            # Get Spark session
            spark = self.spark

            # Set catalog and schema context
            spark.catalog.setCurrentCatalog(self.catalog)
            spark.catalog.setCurrentDatabase(self.schema)
            self.log_very_verbose(f"Set Spark context: {self.catalog}.{self.schema}")

            # Build table registry from catalog
            table_registry: dict[str, SparkDataFrame] = {}
            if tables:
                for table_name, _table_path in tables.items():
                    # Load table from Databricks catalog
                    table_registry[table_name] = spark.table(table_name)
                    self.log_very_verbose(f"Registered table: {table_name}")

            # Execute query builder to get result DataFrame
            result_df = query_builder(spark, table_registry)

            # Collect results
            result = result_df.collect()
            execution_time = elapsed_seconds(start_time)
            actual_row_count = len(result)

            self.log_verbose(f"Query {query_id} completed: {actual_row_count} rows in {execution_time:.3f}s")

            # Validate row count if enabled
            validation_result = None
            if validate_row_count and benchmark_type:
                from benchbox.core.validation.query_validation import QueryValidator

                validator = QueryValidator()
                validation_result = validator.validate_query_result(
                    benchmark_type=benchmark_type,
                    query_id=query_id,
                    actual_row_count=actual_row_count,
                    scale_factor=scale_factor,
                    stream_id=stream_id,
                )

                if validation_result.warning_message:
                    self.log_verbose(f"Row count validation: {validation_result.warning_message}")
                elif not validation_result.is_valid:
                    self.log_verbose(f"Row count validation FAILED: {validation_result.error_message}")

            # Build result using base helper
            result_dict = self._build_query_result_with_validation(
                query_id=query_id,
                execution_time=execution_time,
                actual_row_count=actual_row_count,
                first_row=tuple(result[0]) if result else None,
                validation_result=validation_result,
            )

            # Add DataFrame mode metadata
            result_dict["execution_mode"] = "dataframe"
            result_dict["resource_usage"] = {
                "execution_time_seconds": execution_time,
            }

            return result_dict

        except Exception as e:
            execution_time = elapsed_seconds(start_time)
            return {
                "query_id": query_id,
                "status": "FAILED",
                "execution_time_seconds": execution_time,
                "rows_returned": 0,
                "error": str(e),
                "error_type": type(e).__name__,
                "execution_mode": "dataframe",
            }

    def execute_query(
        self,
        connection: Any,
        query: str | Callable[[SparkSession, dict[str, SparkDataFrame]], SparkDataFrame],
        query_id: str,
        benchmark_type: str | None = None,
        scale_factor: float | None = None,
        validate_row_count: bool = True,
        stream_id: int | None = None,
    ) -> dict[str, Any]:
        """Execute a query in either SQL or DataFrame mode.

        This method provides a unified interface that dispatches to either
        SQL execution (via parent class) or DataFrame execution based on
        the query type and execution mode.

        Args:
            connection: SQL connection for query execution
            query: SQL string or DataFrame builder function
            query_id: Query identifier
            benchmark_type: Benchmark type for validation
            scale_factor: Scale factor for validation
            validate_row_count: Whether to validate row count
            stream_id: Stream ID for throughput tests

        Returns:
            Query result dictionary
        """
        # If query is a callable, use DataFrame execution
        if callable(query):
            return self.execute_dataframe_query(
                connection=connection,
                query_builder=query,
                query_id=query_id,
                benchmark_type=benchmark_type,
                scale_factor=scale_factor,
                validate_row_count=validate_row_count,
                stream_id=stream_id,
            )

        # Otherwise use SQL execution from parent class
        return super().execute_query(
            connection=connection,
            query=query,
            query_id=query_id,
            benchmark_type=benchmark_type,
            scale_factor=scale_factor,
            validate_row_count=validate_row_count,
            stream_id=stream_id,
        )

    def close_connection(self, connection: Any) -> None:
        """Close SQL connection and Spark session.

        Args:
            connection: SQL connection to close
        """
        # Close SQL connection via parent
        super().close_connection(connection)

        # Close Spark session if initialized
        if self._spark is not None and self._spark_initialized:
            try:
                self._spark.stop()
                self.log_verbose("Databricks Connect session stopped")
            except Exception as e:
                self.logger.warning(f"Error stopping Spark session: {e}")
            finally:
                self._spark = None
                self._spark_initialized = False

    # =========================================================================
    # Expression Helper Methods (for expression-family compatibility)
    # =========================================================================

    def col(self, name: str) -> Any:
        """Create a PySpark column expression.

        Args:
            name: Column name

        Returns:
            PySpark Column expression
        """
        if not PYSPARK_AVAILABLE:
            raise ImportError("PySpark required for DataFrame expressions")
        return F.col(name)

    def lit(self, value: Any) -> Any:
        """Create a PySpark literal expression.

        Args:
            value: Literal value

        Returns:
            PySpark Column with literal value
        """
        if not PYSPARK_AVAILABLE:
            raise ImportError("PySpark required for DataFrame expressions")
        return F.lit(value)

    def sum_col(self, column: str) -> Any:
        """Create a sum aggregation expression.

        Args:
            column: Column name to sum

        Returns:
            Sum aggregation expression
        """
        if not PYSPARK_AVAILABLE:
            raise ImportError("PySpark required for DataFrame expressions")
        return F.sum(F.col(column))

    def avg_col(self, column: str) -> Any:
        """Create an average aggregation expression.

        Args:
            column: Column name to average

        Returns:
            Average aggregation expression
        """
        if not PYSPARK_AVAILABLE:
            raise ImportError("PySpark required for DataFrame expressions")
        return F.avg(F.col(column))

    def count_col(self, column: str | None = None) -> Any:
        """Create a count aggregation expression.

        Args:
            column: Column name to count (None for COUNT(*))

        Returns:
            Count aggregation expression
        """
        if not PYSPARK_AVAILABLE:
            raise ImportError("PySpark required for DataFrame expressions")
        if column:
            return F.count(F.col(column))
        return F.count(F.lit(1))

    def min_col(self, column: str) -> Any:
        """Create a min aggregation expression.

        Args:
            column: Column name

        Returns:
            Min aggregation expression
        """
        if not PYSPARK_AVAILABLE:
            raise ImportError("PySpark required for DataFrame expressions")
        return F.min(F.col(column))

    def max_col(self, column: str) -> Any:
        """Create a max aggregation expression.

        Args:
            column: Column name

        Returns:
            Max aggregation expression
        """
        if not PYSPARK_AVAILABLE:
            raise ImportError("PySpark required for DataFrame expressions")
        return F.max(F.col(column))


# Convenience export
__all__ = ["DatabricksDataFrameAdapter", "DATABRICKS_CONNECT_AVAILABLE"]
