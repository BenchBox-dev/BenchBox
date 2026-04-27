"""PySpark DataFrame adapter for expression-family benchmarking.

This module provides the PySparkDataFrameAdapter that implements the
ExpressionFamilyAdapter interface for Apache Spark.

PySpark provides a distributed DataFrame API with:
- Lazy evaluation via DataFrame (all operations are lazy until action)
- Expression API with F.col(), F.lit()
- High-performance distributed execution
- Native Parquet and CSV support with schema inference
- Session-based resource management

Usage:
    from benchbox.platforms.dataframe.pyspark_df import PySparkDataFrameAdapter

    adapter = PySparkDataFrameAdapter(master="local[*]")
    ctx = adapter.create_context()

    # Load data
    adapter.load_table(ctx, "orders", [Path("orders.parquet")])

    # Execute query
    result = adapter.execute_query(ctx, query)

    # Always close to stop SparkSession
    adapter.close()

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import contextlib
import io
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.platforms.pyspark import (
    PYSPARK_AVAILABLE,
    PYSPARK_VERSION,
    SparkSessionManager,
)

if PYSPARK_AVAILABLE:
    from pyspark.sql import DataFrame, SparkSession, functions as spark_functions
    from pyspark.sql.column import Column
    from pyspark.sql.types import StringType, StructField, StructType
    from pyspark.sql.window import Window

    F = spark_functions  # noqa: N816 - industry convention for PySpark
else:
    DataFrame = Any  # type: ignore[assignment,misc]
    SparkSession = Any  # type: ignore[assignment,misc]
    Column = Any  # type: ignore[assignment,misc]
    F = None  # type: ignore[assignment,misc]
    Window = Any  # type: ignore[assignment,misc]
    StringType = Any  # type: ignore[assignment,misc]
    StructField = Any  # type: ignore[assignment,misc]
    StructType = Any  # type: ignore[assignment,misc]

from benchbox.core.dataframe.tuning import DataFrameTuningConfiguration
from benchbox.platforms.dataframe.expression_family import (
    ExpressionFamilyAdapter,
)
from benchbox.utils.file_format import TRAILING_DUMMY_COLUMN, has_trailing_delimiter

if TYPE_CHECKING:
    from pyspark.sql.window import WindowSpec

logger = logging.getLogger(__name__)

# Type aliases for PySpark types (when available)
if PYSPARK_AVAILABLE:
    PySparkDF = DataFrame  # Materialized result type (same as lazy in Spark)
    PySparkLazyDF = DataFrame  # Lazy DataFrame type (same type, always lazy)
    PySparkExpr = Column  # Expression type
else:
    PySparkDF = Any
    PySparkLazyDF = Any
    PySparkExpr = Any


class PySparkDataFrameAdapter(ExpressionFamilyAdapter[PySparkDF, PySparkLazyDF, PySparkExpr]):
    """PySpark adapter for expression-family DataFrame benchmarking.

    This adapter provides PySpark integration for expression-based
    DataFrame benchmarking using Apache Spark's Python API.

    Features:
    - Lazy evaluation via Spark DataFrame
    - Expression API (F.col, F.lit)
    - Distributed execution (local and cluster modes)
    - Native Parquet and CSV support
    - Session lifecycle management

    Attributes:
        master: Spark master URL (default: "local[*]")
        app_name: Application name for SparkSession
        driver_memory: Memory allocated to driver
        shuffle_partitions: Number of shuffle partitions
    """

    def __init__(
        self,
        working_dir: str | Path | None = None,
        verbose: bool = False,
        very_verbose: bool = False,
        tuning_config: DataFrameTuningConfiguration | None = None,
        # PySpark-specific options
        master: str = "local[*]",
        app_name: str = "BenchBox-TPC-H",
        driver_memory: str = "4g",
        executor_memory: str | None = None,
        shuffle_partitions: int | None = None,
        enable_aqe: bool = True,
        **spark_config: Any,
    ) -> None:
        """Initialize the PySpark adapter.

        Args:
            working_dir: Working directory for data files
            verbose: Enable verbose logging
            very_verbose: Enable very verbose logging
            tuning_config: Optional tuning configuration for performance optimization
            master: Spark master URL (default: "local[*]" for all local cores)
            app_name: Application name for SparkSession
            driver_memory: Memory for the driver process (default: "4g")
            executor_memory: Memory for executors (optional, for cluster mode)
            shuffle_partitions: Number of shuffle partitions (default: CPU count)
            enable_aqe: Enable Adaptive Query Execution (default: True)
            **spark_config: Additional Spark configuration options

        Raises:
            ImportError: If PySpark is not installed
        """
        if not PYSPARK_AVAILABLE:
            raise ImportError("PySpark not installed. Install with: pip install pyspark pyarrow")

        super().__init__(
            working_dir=working_dir,
            verbose=verbose,
            very_verbose=very_verbose,
            tuning_config=tuning_config,
        )

        # PySpark-specific settings (may be overridden by tuning config)
        self._master = master
        self._app_name = app_name
        self._driver_memory = driver_memory
        self._executor_memory = executor_memory
        self._shuffle_partitions = shuffle_partitions or os.cpu_count() or 8
        self._enable_aqe = enable_aqe
        self._spark_config = spark_config

        # SparkSession is created lazily
        self._spark: SparkSession | None = None
        self._session_claimed = False

        # Validate and apply tuning configuration
        self._validate_and_apply_tuning()

    def _apply_tuning(self) -> None:
        """Apply PySpark-specific tuning configuration.

        This method applies tuning settings from the configuration to the
        PySpark runtime. Settings include:
        - Thread/partition count for parallelism
        - Memory settings
        """
        config = self._tuning_config

        # Apply parallelism settings
        if config.parallelism.thread_count is not None:
            # For local mode, this affects the number of cores used
            self._master = f"local[{config.parallelism.thread_count}]"
            self._shuffle_partitions = config.parallelism.thread_count
            self._log_verbose(f"Set master={self._master}, shuffle_partitions={self._shuffle_partitions}")

        # Apply memory settings (memory_limit is a string like "4GB")
        if config.memory.memory_limit is not None:
            self._driver_memory = config.memory.memory_limit
            self._log_verbose(f"Set driver_memory={self._driver_memory}")

        # Note: streaming_mode not applicable to PySpark batch DataFrames
        if config.execution.streaming_mode:
            self._log_verbose("Note: streaming_mode not applicable to PySpark batch DataFrames")

    @property
    def platform_name(self) -> str:
        """Return the platform name."""
        return "PySpark"

    def _get_or_create_session(self) -> SparkSession:
        """Get existing or create new SparkSession.

        Returns:
            The SparkSession instance
        """
        if self._spark is None:
            self._spark = SparkSessionManager.get_or_create(
                master=self._master,
                app_name=self._app_name,
                driver_memory=self._driver_memory,
                executor_memory=self._executor_memory,
                shuffle_partitions=self._shuffle_partitions,
                enable_aqe=self._enable_aqe,
                extra_configs=self._spark_config,
                verbose=self.verbose,
            )
            self._session_claimed = True

            if self.verbose and self._spark is not None:
                master = self._spark.sparkContext.master
                self._log_verbose(f"SparkSession acquired: master={master}")

        return self._spark

    @property
    def spark(self) -> SparkSession:
        """Access the SparkSession."""
        return self._get_or_create_session()

    def close(self) -> None:
        """Release the shared SparkSession and cleanup resources."""
        if self._session_claimed:
            SparkSessionManager.release()
            self._session_claimed = False
            if self.verbose:
                self._log_verbose("SparkSession reference released")
        self._spark = None

    def __del__(self) -> None:
        """Cleanup on garbage collection."""
        with contextlib.suppress(Exception):
            self.close()

    def __enter__(self) -> PySparkDataFrameAdapter:
        """Enter context manager - return self for use in `with` blocks.

        Example:
            with PySparkDataFrameAdapter() as adapter:
                ctx = adapter.create_context()
                # ... use adapter ...
            # SparkSession automatically stopped on exit
        """
        return self

    def __exit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any) -> None:
        """Exit context manager - stop SparkSession."""
        self.close()

    # =========================================================================
    # Expression Methods
    # =========================================================================

    def _ensure_spark(self) -> None:
        """Ensure SparkSession is active.

        PySpark 4.x requires an active SparkContext for expression creation.
        This method triggers lazy session creation if needed.
        """
        _ = self.spark

    def col(self, name: str) -> PySparkExpr:
        """Create a PySpark column expression.

        Args:
            name: The column name

        Returns:
            PySpark Column expression
        """
        self._ensure_spark()
        return F.col(name)

    def lit(self, value: Any) -> PySparkExpr:
        """Create a PySpark literal expression.

        Args:
            value: The literal value

        Returns:
            PySpark Column containing the literal value
        """
        self._ensure_spark()
        return F.lit(value)

    def date_sub(self, column: PySparkExpr, days: int) -> PySparkExpr:
        """Subtract days from a date column.

        Args:
            column: The date column expression
            days: Number of days to subtract

        Returns:
            Expression with days subtracted
        """
        self._ensure_spark()
        return F.date_sub(column, days)

    def date_add(self, column: PySparkExpr, days: int) -> PySparkExpr:
        """Add days to a date column.

        Args:
            column: The date column expression
            days: Number of days to add

        Returns:
            Expression with days added
        """
        self._ensure_spark()
        return F.date_add(column, days)

    def cast_date(self, column: PySparkExpr) -> PySparkExpr:
        """Cast a column to date type.

        Args:
            column: The column expression to cast

        Returns:
            Expression cast to Date type
        """
        return column.cast("date")

    def cast_string(self, column: PySparkExpr) -> PySparkExpr:
        """Cast a column to string type.

        Args:
            column: The column expression to cast

        Returns:
            Expression cast to string type
        """
        return column.cast("string")

    # =========================================================================
    # Aggregation Helper Methods (for API parity with Polars/DataFusion)
    # =========================================================================

    def sum(self, column: str) -> PySparkExpr:
        """Create a sum aggregation expression.

        Args:
            column: Column to sum

        Returns:
            Sum expression
        """
        self._ensure_spark()
        return F.sum(F.col(column))

    def mean(self, column: str) -> PySparkExpr:
        """Create a mean/average aggregation expression.

        Args:
            column: Column to average

        Returns:
            Mean expression
        """
        self._ensure_spark()
        return F.avg(F.col(column))

    def count(self, column: str | None = None) -> PySparkExpr:
        """Create a count aggregation expression.

        Args:
            column: Column to count (None for COUNT(*))

        Returns:
            Count expression
        """
        self._ensure_spark()
        if column:
            return F.count(F.col(column))
        return F.count(F.lit(1))

    def min(self, column: str) -> PySparkExpr:
        """Create a min aggregation expression.

        Args:
            column: Column to find minimum of

        Returns:
            Min expression
        """
        self._ensure_spark()
        return F.min(F.col(column))

    def max(self, column: str) -> PySparkExpr:
        """Create a max aggregation expression.

        Args:
            column: Column to find maximum of

        Returns:
            Max expression
        """
        self._ensure_spark()
        return F.max(F.col(column))

    def when(self, condition: PySparkExpr) -> Any:
        """Create a when expression for conditional logic.

        Args:
            condition: The condition expression

        Returns:
            PySpark When builder for chaining .when().otherwise()
        """
        self._ensure_spark()
        return F.when(condition, True)

    def concat_str(self, *columns: str, separator: str = "") -> PySparkExpr:
        """Concatenate string columns.

        Args:
            *columns: Column names to concatenate
            separator: Separator between values

        Returns:
            Expression concatenating the columns
        """
        self._ensure_spark()
        if separator:
            return F.concat_ws(separator, *[F.col(c) for c in columns])
        return F.concat(*[F.col(c) for c in columns])

    # =========================================================================
    # Data Loading Methods
    # =========================================================================

    def read_csv(
        self,
        path: Path,
        *,
        delimiter: str = ",",
        has_header: bool = True,
        column_names: list[str] | None = None,
        null_marker: str | None = None,
    ) -> PySparkLazyDF:
        """Read a CSV file into a PySpark DataFrame.

        Args:
            path: Path to the CSV file
            delimiter: Field delimiter
            has_header: Whether file has header row
            column_names: Optional column names (overrides header)
            null_marker: When not None, enables trailing-delimiter probing (TPC-style rows end with a spurious delimiter).

        Returns:
            PySpark DataFrame with the file contents
        """
        path_str = str(path)

        reader = self.spark.read.option("delimiter", delimiter).option("header", str(has_header).lower())

        # Trailing-delimiter probing only for TPC-style sources (null_marker is not None).
        if null_marker is not None and column_names and has_trailing_delimiter(path, delimiter, column_names):
            extended_names = column_names + [TRAILING_DUMMY_COLUMN]
            schema = self._build_schema(extended_names)
            df = reader.schema(schema).csv(path_str)
            df = df.drop(TRAILING_DUMMY_COLUMN)
        elif column_names:
            schema = self._build_schema(column_names)
            df = reader.schema(schema).csv(path_str)
        else:
            # Let Spark infer schema
            df = reader.option("inferSchema", "true").csv(path_str)

        return df

    def _build_schema(self, column_names: list[str]) -> StructType:
        """Build a Spark StructType schema for CSV reading.

        Args:
            column_names: List of column names

        Returns:
            StructType schema (all columns as StringType for flexibility)
        """
        return StructType([StructField(name, StringType(), nullable=True) for name in column_names])

    def read_parquet(self, path: Path) -> PySparkLazyDF:
        """Read a Parquet file into a PySpark DataFrame.

        Args:
            path: Path to the Parquet file

        Returns:
            PySpark DataFrame with the file contents
        """
        return self.spark.read.parquet(str(path))

    def collect(self, df: PySparkLazyDF) -> PySparkDF:
        """Materialize a PySpark DataFrame.

        For PySpark, this triggers computation. The DataFrame itself is returned
        since Spark DataFrames are always the same type (lazy until action).

        Note: For actual data retrieval, use .toPandas() or .collect().

        Args:
            df: The DataFrame to materialize

        Returns:
            The same DataFrame (after triggering computation via count)
        """
        # Trigger computation by counting
        _ = df.count()
        return df

    def get_row_count(self, df: PySparkLazyDF | PySparkDF) -> int:
        """Get the number of rows in a DataFrame.

        Args:
            df: The DataFrame

        Returns:
            Number of rows
        """
        return df.count()

    def scalar(self, df: PySparkDF, column: str | None = None) -> Any:
        """Extract a single scalar value from a DataFrame.

        Uses PySpark's .limit(2).collect() to efficiently validate single-row
        constraint while avoiding a full count() operation.

        Args:
            df: The DataFrame (should have exactly one row)
            column: Optional column name. If None, uses the first column.

        Returns:
            The scalar value

        Raises:
            ValueError: If the DataFrame is empty or has more than one row
        """
        # Limit to 2 rows and collect to validate single-row constraint
        # This is more efficient than count() for large DataFrames
        rows = df.limit(2).collect()

        if len(rows) == 0:
            raise ValueError("Cannot extract scalar from empty DataFrame")
        if len(rows) > 1:
            raise ValueError("Expected exactly one row, got multiple")

        first_row = rows[0]

        # Get the value from the specified column or first column
        if column is not None:
            return first_row[column]

        # Return first column value
        return first_row[0]

    def scalar_to_df(self, data: dict[str, Any]) -> PySparkDF:
        """Create a single-row PySpark DataFrame from scalar values.

        Args:
            data: Dictionary mapping column names to scalar values

        Returns:
            PySpark DataFrame with a single row
        """
        self._ensure_spark()
        from pyspark.sql import Row

        row = Row(**data)
        return self._spark.createDataFrame([row])

    # =========================================================================
    # Window Functions
    # =========================================================================

    def _build_window_spec(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> WindowSpec:
        """Build a Window specification from order_by and partition_by.

        Args:
            order_by: List of (column_name, ascending) tuples
            partition_by: Columns to partition by (optional)

        Returns:
            WindowSpec for use with window functions
        """
        self._ensure_spark()
        # Start with partition if provided
        window = Window.partitionBy(*[F.col(c) for c in partition_by]) if partition_by else Window.partitionBy()

        # Add ordering
        order_cols = []
        for col_name, ascending in order_by:
            col_expr = F.col(col_name)
            if ascending:
                order_cols.append(col_expr.asc())
            else:
                order_cols.append(col_expr.desc())

        if order_cols:
            window = window.orderBy(*order_cols)

        return window

    def _build_aggregate_window_spec(
        self,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> WindowSpec:
        """Build Window spec for aggregate window functions.

        Args:
            partition_by: Columns to partition by (optional)
            order_by: If provided, creates running aggregate (optional)

        Returns:
            WindowSpec for aggregate functions
        """
        self._ensure_spark()
        window = Window.partitionBy(*[F.col(c) for c in partition_by]) if partition_by else Window.partitionBy()

        if order_by:
            order_cols = []
            for col_name, ascending in order_by:
                col_expr = F.col(col_name)
                order_cols.append(col_expr.asc() if ascending else col_expr.desc())
            window = window.orderBy(*order_cols)
            # Running window for ordered aggregates
            window = window.rowsBetween(Window.unboundedPreceding, Window.currentRow)

        return window

    def window_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> PySparkExpr:
        """Create a RANK() window function expression.

        Args:
            order_by: List of (column_name, ascending) tuples for ordering
            partition_by: Columns to partition by (optional)

        Returns:
            PySpark Column for rank within partitions
        """
        window_spec = self._build_window_spec(order_by, partition_by)
        return F.rank().over(window_spec)

    def window_row_number(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> PySparkExpr:
        """Create a ROW_NUMBER() window function expression.

        Args:
            order_by: List of (column_name, ascending) tuples for ordering
            partition_by: Columns to partition by (optional)

        Returns:
            PySpark Column for row number within partitions
        """
        window_spec = self._build_window_spec(order_by, partition_by)
        return F.row_number().over(window_spec)

    def window_dense_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> PySparkExpr:
        """Create a DENSE_RANK() window function expression.

        Args:
            order_by: List of (column_name, ascending) tuples for ordering
            partition_by: Columns to partition by (optional)

        Returns:
            PySpark Column for dense rank within partitions
        """
        window_spec = self._build_window_spec(order_by, partition_by)
        return F.dense_rank().over(window_spec)

    def window_sum(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> PySparkExpr:
        """Create a SUM() OVER window function expression.

        Without order_by: Sum of all values in partition
        With order_by: Running/cumulative sum

        Args:
            column: Column to sum
            partition_by: Columns to partition by (optional)
            order_by: If provided, creates cumulative sum (optional)

        Returns:
            PySpark Column for windowed sum
        """
        window_spec = self._build_aggregate_window_spec(partition_by, order_by)
        return F.sum(F.col(column)).over(window_spec)

    def window_avg(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> PySparkExpr:
        """Create an AVG() OVER window function expression.

        Args:
            column: Column to average
            partition_by: Columns to partition by (optional)
            order_by: If provided, creates cumulative average (optional)

        Returns:
            PySpark Column for windowed average
        """
        window_spec = self._build_aggregate_window_spec(partition_by, order_by)
        return F.avg(F.col(column)).over(window_spec)

    def window_count(
        self,
        column: str | None = None,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> PySparkExpr:
        """Create a COUNT() OVER window function expression.

        Args:
            column: Column to count (None for COUNT(*))
            partition_by: Columns to partition by (optional)
            order_by: If provided, creates cumulative count (optional)

        Returns:
            PySpark Column for windowed count
        """
        window_spec = self._build_aggregate_window_spec(partition_by, order_by)
        if column:
            return F.count(F.col(column)).over(window_spec)
        else:
            return F.count(F.lit(1)).over(window_spec)

    def window_min(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> PySparkExpr:
        """Create a MIN() OVER window function expression.

        Args:
            column: Column to find minimum
            partition_by: Columns to partition by (optional)

        Returns:
            PySpark Column for windowed minimum
        """
        window_spec = self._build_aggregate_window_spec(partition_by, None)
        return F.min(F.col(column)).over(window_spec)

    def window_max(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> PySparkExpr:
        """Create a MAX() OVER window function expression.

        Args:
            column: Column to find maximum
            partition_by: Columns to partition by (optional)

        Returns:
            PySpark Column for windowed maximum
        """
        window_spec = self._build_aggregate_window_spec(partition_by, None)
        return F.max(F.col(column)).over(window_spec)

    # =========================================================================
    # Union and Rename Operations
    # =========================================================================

    def union_all(self, *dataframes: PySparkLazyDF) -> PySparkLazyDF:
        """Union multiple DataFrames (UNION ALL equivalent).

        Args:
            *dataframes: DataFrames to union

        Returns:
            Combined DataFrame
        """
        if len(dataframes) == 0:
            raise ValueError("At least one DataFrame required for union")
        if len(dataframes) == 1:
            return dataframes[0]

        result = dataframes[0]
        for df in dataframes[1:]:
            result = result.union(df)
        return result

    def rename_columns(self, df: PySparkLazyDF, mapping: dict[str, str]) -> PySparkLazyDF:
        """Rename columns in a DataFrame.

        Args:
            df: The DataFrame
            mapping: Dict mapping old column names to new names

        Returns:
            DataFrame with renamed columns
        """
        result = df
        for old_name, new_name in mapping.items():
            if old_name in df.columns:
                result = result.withColumnRenamed(old_name, new_name)
        return result

    # =========================================================================
    # Override Methods
    # =========================================================================

    def _concat_dataframes(self, dfs: list[PySparkLazyDF]) -> PySparkLazyDF:
        """Concatenate multiple PySpark DataFrames.

        Args:
            dfs: List of DataFrames to concatenate

        Returns:
            Combined DataFrame
        """
        if len(dfs) == 1:
            return dfs[0]
        return self.union_all(*dfs)

    def _get_first_row(self, df: PySparkDF) -> tuple | None:
        """Get the first row of a PySpark DataFrame.

        Args:
            df: The DataFrame

        Returns:
            First row as tuple, or None if empty
        """
        rows = df.take(1)
        if not rows:
            return None
        return tuple(rows[0])

    def get_platform_info(self) -> dict[str, Any]:
        """Get platform information for reporting.

        Returns:
            Dictionary with platform details
        """
        info = {
            "platform": self.platform_name,
            "family": self.family,
            "master": self._master,
            "driver_memory": self._driver_memory,
            "shuffle_partitions": self._shuffle_partitions,
            "aqe_enabled": self._enable_aqe,
            "working_dir": str(self.working_dir),
        }

        # Use module-level version (doesn't require SparkSession)
        if PYSPARK_AVAILABLE:
            info["version"] = PYSPARK_VERSION

        return info

    def get_tuning_summary(self) -> dict[str, Any]:
        """Get summary of applied tuning settings.

        Returns:
            Dictionary with tuning summary information
        """
        base_summary = super().get_tuning_summary()
        base_summary.update(
            {
                "master": self._master,
                "driver_memory": self._driver_memory,
                "executor_memory": self._executor_memory,
                "shuffle_partitions": self._shuffle_partitions,
                "aqe_enabled": self._enable_aqe,
                "spark_version": PYSPARK_VERSION,
            }
        )
        return base_summary

    # =========================================================================
    # PySpark-Specific Methods
    # =========================================================================

    def explain(self, df: PySparkLazyDF, mode: str = "extended") -> str:
        """Get the query plan for a DataFrame.

        Args:
            df: DataFrame to explain
            mode: "simple", "extended", "codegen", "cost", or "formatted"

        Returns:
            Query plan as string
        """
        # Capture explain output
        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()
        try:
            df.explain(mode=mode)
        finally:
            sys.stdout = old_stdout

        return buffer.getvalue()

    def get_query_plan(self, df: PySparkLazyDF) -> dict[str, str]:
        """Get both logical and physical query plans.

        Args:
            df: DataFrame to get plans for

        Returns:
            Dictionary with 'logical' and 'physical' plans
        """
        return {
            "logical": self.explain(df, "simple"),
            "physical": self.explain(df, "extended"),
        }

    def sql(self, query: str) -> PySparkLazyDF:
        """Execute a SQL query against registered tables.

        Args:
            query: SQL query string

        Returns:
            DataFrame with query results
        """
        return self.spark.sql(query)

    def register_table(self, name: str, df: PySparkLazyDF) -> None:
        """Register a DataFrame as a temporary view for SQL queries.

        Args:
            name: Table name
            df: DataFrame to register
        """
        df.createOrReplaceTempView(name)

    def to_pandas(self, df: PySparkLazyDF) -> Any:
        """Convert DataFrame to Pandas.

        Args:
            df: DataFrame to convert

        Returns:
            Pandas DataFrame
        """
        return df.toPandas()

    def to_polars(self, df: PySparkLazyDF) -> Any:
        """Convert DataFrame to Polars via Arrow for efficient transfer.

        Uses PySpark's Arrow-based conversion when available (PySpark 3.x+)
        for efficient memory transfer without copying data.

        Args:
            df: DataFrame to convert

        Returns:
            Polars DataFrame
        """
        try:
            import polars as pl
        except ImportError as e:
            raise ImportError("Polars not installed. Install with: pip install polars") from e

        # Try toArrow() first (PySpark 4.0+), then fall back to toPandas() with Arrow
        # PySpark 3.x has Arrow enabled by default for toPandas()
        try:
            # PySpark 4.0+ has toArrow() method
            if hasattr(df, "toArrow"):
                arrow_table = df.toArrow()
                return pl.from_arrow(arrow_table)
        except Exception:
            pass  # Fall back to pandas path

        # PySpark 3.x: toPandas() uses Arrow internally (spark.sql.execution.arrow.pyspark.enabled=true)
        # Then convert from pandas to polars (polars handles this efficiently)
        pandas_df = df.toPandas()
        return pl.from_pandas(pandas_df)
