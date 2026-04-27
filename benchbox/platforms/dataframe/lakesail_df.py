"""LakeSail Sail DataFrame adapter for expression-family benchmarking.

This module provides the LakeSailDataFrameAdapter that implements the
ExpressionFamilyAdapter interface for LakeSail Sail via Spark Connect.

LakeSail Sail is a Rust-based, drop-in Spark replacement built on DataFusion.
Since it implements the Spark Connect protocol, it uses the standard PySpark
client and provides the same DataFrame API as Apache Spark.

This adapter is nearly identical to PySparkDataFrameAdapter but connects
to a Sail server endpoint via Spark Connect rather than creating a local
SparkSession.

Usage:
    from benchbox.platforms.dataframe.lakesail_df import LakeSailDataFrameAdapter

    adapter = LakeSailDataFrameAdapter(endpoint="sc://localhost:50051")
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

# Type aliases for LakeSail types (same as PySpark since it uses Spark Connect)
if PYSPARK_AVAILABLE:
    LakeSailDF = DataFrame
    LakeSailLazyDF = DataFrame
    LakeSailExpr = Column
else:
    LakeSailDF = Any
    LakeSailLazyDF = Any
    LakeSailExpr = Any


class LakeSailDataFrameAdapter(ExpressionFamilyAdapter[LakeSailDF, LakeSailLazyDF, LakeSailExpr]):
    """LakeSail Sail adapter for expression-family DataFrame benchmarking.

    This adapter provides LakeSail Sail integration for expression-based
    DataFrame benchmarking using the PySpark DataFrame API via Spark Connect.

    Features:
    - Spark Connect protocol to LakeSail Sail server
    - Full PySpark DataFrame/Column expression API
    - DataFusion-based execution engine (Rust)
    - Native Parquet and CSV support

    Attributes:
        endpoint: Sail server Spark Connect endpoint
        app_name: Application name for the Spark Connect session
        driver_memory: Memory allocated to driver
        shuffle_partitions: Number of shuffle partitions
    """

    def __init__(
        self,
        working_dir: str | Path | None = None,
        verbose: bool = False,
        very_verbose: bool = False,
        tuning_config: DataFrameTuningConfiguration | None = None,
        # LakeSail-specific options
        endpoint: str = "sc://localhost:50051",
        app_name: str = "BenchBox-LakeSail-DF",
        driver_memory: str = "4g",
        shuffle_partitions: int | None = None,
        enable_aqe: bool = True,
        **spark_config: Any,
    ) -> None:
        """Initialize the LakeSail DataFrame adapter.

        Args:
            working_dir: Working directory for data files
            verbose: Enable verbose logging
            very_verbose: Enable very verbose logging
            tuning_config: Optional tuning configuration for performance optimization
            endpoint: Sail server Spark Connect endpoint (default: "sc://localhost:50051")
            app_name: Application name for the session
            driver_memory: Memory for the driver process (default: "4g")
            shuffle_partitions: Number of shuffle partitions (default: CPU count)
            enable_aqe: Enable Adaptive Query Execution (default: True)
            **spark_config: Additional Spark configuration options

        Raises:
            ImportError: If PySpark is not installed
        """
        if not PYSPARK_AVAILABLE:
            raise ImportError(
                "PySpark not installed. Install with: pip install pyspark pyarrow\n"
                "LakeSail Sail uses the standard PySpark client via Spark Connect."
            )

        super().__init__(
            working_dir=working_dir,
            verbose=verbose,
            very_verbose=very_verbose,
            tuning_config=tuning_config,
        )

        # LakeSail-specific settings
        self._endpoint = endpoint
        self._app_name = app_name
        self._driver_memory = driver_memory
        self._shuffle_partitions = shuffle_partitions or os.cpu_count() or 8
        self._enable_aqe = enable_aqe
        self._spark_config = spark_config

        # SparkSession is created lazily
        self._spark: SparkSession | None = None

        # Validate and apply tuning configuration
        self._validate_and_apply_tuning()

    def _apply_tuning(self) -> None:
        """Apply LakeSail-specific tuning configuration."""
        config = self._tuning_config

        if config.parallelism.thread_count is not None:
            self._shuffle_partitions = config.parallelism.thread_count
            self._log_verbose(f"Set shuffle_partitions={self._shuffle_partitions}")

        if config.memory.memory_limit is not None:
            self._driver_memory = config.memory.memory_limit
            self._log_verbose(f"Set driver_memory={self._driver_memory}")

        if config.execution.streaming_mode:
            self._log_verbose("Note: streaming_mode not applicable to LakeSail batch DataFrames")

    @property
    def platform_name(self) -> str:
        """Return the platform name."""
        return "LakeSail"

    def _get_or_create_session(self) -> SparkSession:
        """Get existing or create new SparkSession via Spark Connect to Sail server."""
        if self._spark is None:
            builder = SparkSession.builder.remote(self._endpoint)
            builder = builder.config("spark.app.name", self._app_name)
            builder = builder.config("spark.sql.shuffle.partitions", str(self._shuffle_partitions))

            if self._enable_aqe:
                builder = builder.config("spark.sql.adaptive.enabled", "true")

            for key, value in self._spark_config.items():
                builder = builder.config(key, str(value))

            self._spark = builder.getOrCreate()

            if self.verbose and self._spark is not None:
                self._log_verbose(f"LakeSail Spark Connect session acquired: endpoint={self._endpoint}")

        return self._spark

    @property
    def spark(self) -> SparkSession:
        """Access the SparkSession."""
        return self._get_or_create_session()

    def close(self) -> None:
        """Stop the Spark Connect session and cleanup resources."""
        if self._spark is not None:
            try:
                self._spark.stop()
            except Exception:
                pass
            if self.verbose:
                self._log_verbose("LakeSail Spark Connect session stopped")
        self._spark = None

    def __del__(self) -> None:
        """Cleanup on garbage collection."""
        with contextlib.suppress(Exception):
            self.close()

    def __enter__(self) -> LakeSailDataFrameAdapter:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any) -> None:
        """Exit context manager - stop session."""
        self.close()

    # =========================================================================
    # Expression Methods
    # =========================================================================

    def _ensure_spark(self) -> None:
        """Ensure SparkSession is active."""
        _ = self.spark

    def col(self, name: str) -> LakeSailExpr:
        """Create a column expression."""
        self._ensure_spark()
        return F.col(name)

    def lit(self, value: Any) -> LakeSailExpr:
        """Create a literal expression."""
        self._ensure_spark()
        return F.lit(value)

    def date_sub(self, column: LakeSailExpr, days: int) -> LakeSailExpr:
        """Subtract days from a date column."""
        self._ensure_spark()
        return F.date_sub(column, days)

    def date_add(self, column: LakeSailExpr, days: int) -> LakeSailExpr:
        """Add days to a date column."""
        self._ensure_spark()
        return F.date_add(column, days)

    def cast_date(self, column: LakeSailExpr) -> LakeSailExpr:
        """Cast a column to date type."""
        return column.cast("date")

    def cast_string(self, column: LakeSailExpr) -> LakeSailExpr:
        """Cast a column to string type."""
        return column.cast("string")

    # =========================================================================
    # Aggregation Helper Methods
    # =========================================================================

    def sum(self, column: str) -> LakeSailExpr:
        """Create a sum aggregation expression."""
        self._ensure_spark()
        return F.sum(F.col(column))

    def mean(self, column: str) -> LakeSailExpr:
        """Create a mean/average aggregation expression."""
        self._ensure_spark()
        return F.avg(F.col(column))

    def count(self, column: str | None = None) -> LakeSailExpr:
        """Create a count aggregation expression."""
        self._ensure_spark()
        if column:
            return F.count(F.col(column))
        return F.count(F.lit(1))

    def min(self, column: str) -> LakeSailExpr:
        """Create a min aggregation expression."""
        self._ensure_spark()
        return F.min(F.col(column))

    def max(self, column: str) -> LakeSailExpr:
        """Create a max aggregation expression."""
        self._ensure_spark()
        return F.max(F.col(column))

    def when(self, condition: LakeSailExpr) -> Any:
        """Create a when expression for conditional logic."""
        self._ensure_spark()
        return F.when(condition, True)

    def concat_str(self, *columns: str, separator: str = "") -> LakeSailExpr:
        """Concatenate string columns."""
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
    ) -> LakeSailLazyDF:
        """Read a CSV file into a DataFrame via Spark Connect."""
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
            df = reader.option("inferSchema", "true").csv(path_str)

        return df

    def _build_schema(self, column_names: list[str]) -> StructType:
        """Build a Spark StructType schema for CSV reading."""
        return StructType([StructField(name, StringType(), nullable=True) for name in column_names])

    def read_parquet(self, path: Path) -> LakeSailLazyDF:
        """Read a Parquet file into a DataFrame."""
        return self.spark.read.parquet(str(path))

    def collect(self, df: LakeSailLazyDF) -> LakeSailDF:
        """Materialize a DataFrame (triggers computation)."""
        _ = df.count()
        return df

    def get_row_count(self, df: LakeSailLazyDF | LakeSailDF) -> int:
        """Get the number of rows in a DataFrame."""
        return df.count()

    def scalar(self, df: LakeSailDF, column: str | None = None) -> Any:
        """Extract a single scalar value from a DataFrame."""
        rows = df.limit(2).collect()

        if len(rows) == 0:
            raise ValueError("Cannot extract scalar from empty DataFrame")
        if len(rows) > 1:
            raise ValueError("Expected exactly one row, got multiple")

        first_row = rows[0]

        if column is not None:
            return first_row[column]

        return first_row[0]

    def scalar_to_df(self, data: dict[str, Any]) -> LakeSailDF:
        """Create a single-row DataFrame from scalar values."""
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
        """Build a Window specification."""
        self._ensure_spark()
        window = Window.partitionBy(*[F.col(c) for c in partition_by]) if partition_by else Window.partitionBy()

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
        """Build Window spec for aggregate window functions."""
        self._ensure_spark()
        window = Window.partitionBy(*[F.col(c) for c in partition_by]) if partition_by else Window.partitionBy()

        if order_by:
            order_cols = []
            for col_name, ascending in order_by:
                col_expr = F.col(col_name)
                order_cols.append(col_expr.asc() if ascending else col_expr.desc())
            window = window.orderBy(*order_cols)
            window = window.rowsBetween(Window.unboundedPreceding, Window.currentRow)

        return window

    def window_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> LakeSailExpr:
        """Create a RANK() window function expression."""
        window_spec = self._build_window_spec(order_by, partition_by)
        return F.rank().over(window_spec)

    def window_row_number(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> LakeSailExpr:
        """Create a ROW_NUMBER() window function expression."""
        window_spec = self._build_window_spec(order_by, partition_by)
        return F.row_number().over(window_spec)

    def window_dense_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> LakeSailExpr:
        """Create a DENSE_RANK() window function expression."""
        window_spec = self._build_window_spec(order_by, partition_by)
        return F.dense_rank().over(window_spec)

    def window_sum(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> LakeSailExpr:
        """Create a SUM() OVER window function expression."""
        window_spec = self._build_aggregate_window_spec(partition_by, order_by)
        return F.sum(F.col(column)).over(window_spec)

    def window_avg(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> LakeSailExpr:
        """Create an AVG() OVER window function expression."""
        window_spec = self._build_aggregate_window_spec(partition_by, order_by)
        return F.avg(F.col(column)).over(window_spec)

    def window_count(
        self,
        column: str | None = None,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> LakeSailExpr:
        """Create a COUNT() OVER window function expression."""
        window_spec = self._build_aggregate_window_spec(partition_by, order_by)
        if column:
            return F.count(F.col(column)).over(window_spec)
        else:
            return F.count(F.lit(1)).over(window_spec)

    def window_min(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> LakeSailExpr:
        """Create a MIN() OVER window function expression."""
        window_spec = self._build_aggregate_window_spec(partition_by, None)
        return F.min(F.col(column)).over(window_spec)

    def window_max(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> LakeSailExpr:
        """Create a MAX() OVER window function expression."""
        window_spec = self._build_aggregate_window_spec(partition_by, None)
        return F.max(F.col(column)).over(window_spec)

    # =========================================================================
    # Union and Rename Operations
    # =========================================================================

    def union_all(self, *dataframes: LakeSailLazyDF) -> LakeSailLazyDF:
        """Union multiple DataFrames (UNION ALL equivalent)."""
        if len(dataframes) == 0:
            raise ValueError("At least one DataFrame required for union")
        if len(dataframes) == 1:
            return dataframes[0]

        result = dataframes[0]
        for df in dataframes[1:]:
            result = result.union(df)
        return result

    def rename_columns(self, df: LakeSailLazyDF, mapping: dict[str, str]) -> LakeSailLazyDF:
        """Rename columns in a DataFrame."""
        result = df
        for old_name, new_name in mapping.items():
            if old_name in df.columns:
                result = result.withColumnRenamed(old_name, new_name)
        return result

    # =========================================================================
    # Override Methods
    # =========================================================================

    def _concat_dataframes(self, dfs: list[LakeSailLazyDF]) -> LakeSailLazyDF:
        """Concatenate multiple DataFrames."""
        if len(dfs) == 1:
            return dfs[0]
        return self.union_all(*dfs)

    def _get_first_row(self, df: LakeSailDF) -> tuple | None:
        """Get the first row of a DataFrame."""
        rows = df.take(1)
        if not rows:
            return None
        return tuple(rows[0])

    def get_platform_info(self) -> dict[str, Any]:
        """Get platform information for reporting."""
        info = {
            "platform": self.platform_name,
            "family": self.family,
            "endpoint": self._endpoint,
            "driver_memory": self._driver_memory,
            "shuffle_partitions": self._shuffle_partitions,
            "aqe_enabled": self._enable_aqe,
            "working_dir": str(self.working_dir),
        }

        if PYSPARK_AVAILABLE:
            info["pyspark_version"] = PYSPARK_VERSION

        return info

    def get_tuning_summary(self) -> dict[str, Any]:
        """Get summary of applied tuning settings."""
        base_summary = super().get_tuning_summary()
        base_summary.update(
            {
                "endpoint": self._endpoint,
                "driver_memory": self._driver_memory,
                "shuffle_partitions": self._shuffle_partitions,
                "aqe_enabled": self._enable_aqe,
                "pyspark_version": PYSPARK_VERSION,
            }
        )
        return base_summary

    # =========================================================================
    # LakeSail-Specific Methods
    # =========================================================================

    def explain(self, df: LakeSailLazyDF, mode: str = "extended") -> str:
        """Get the query plan for a DataFrame."""
        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()
        try:
            df.explain(mode=mode)
        finally:
            sys.stdout = old_stdout

        return buffer.getvalue()

    def get_query_plan(self, df: LakeSailLazyDF) -> dict[str, str]:
        """Get both logical and physical query plans."""
        return {
            "logical": self.explain(df, "simple"),
            "physical": self.explain(df, "extended"),
        }

    def sql(self, query: str) -> LakeSailLazyDF:
        """Execute a SQL query against registered tables."""
        return self.spark.sql(query)

    def register_table(self, name: str, df: LakeSailLazyDF) -> None:
        """Register a DataFrame as a temporary view for SQL queries."""
        df.createOrReplaceTempView(name)

    def to_pandas(self, df: LakeSailLazyDF) -> Any:
        """Convert DataFrame to Pandas."""
        return df.toPandas()

    def to_polars(self, df: LakeSailLazyDF) -> Any:
        """Convert DataFrame to Polars via Arrow for efficient transfer."""
        try:
            import polars as pl
        except ImportError as e:
            raise ImportError("Polars not installed. Install with: pip install polars") from e

        try:
            if hasattr(df, "toArrow"):
                arrow_table = df.toArrow()
                return pl.from_arrow(arrow_table)
        except Exception:
            pass

        pandas_df = df.toPandas()
        return pl.from_pandas(pandas_df)
