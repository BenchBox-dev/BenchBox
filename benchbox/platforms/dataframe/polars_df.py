"""Polars DataFrame adapter for expression-family benchmarking.

This module provides the PolarsDataFrameAdapter that implements the
ExpressionFamilyAdapter interface for Polars.

Polars is the reference implementation for the expression family, providing:
- Lazy evaluation with pl.LazyFrame
- Expression API with pl.col(), pl.lit()
- High-performance Rust backend
- Native support for many file formats

Usage:
    from benchbox.platforms.dataframe.polars_df import PolarsDataFrameAdapter

    adapter = PolarsDataFrameAdapter()
    ctx = adapter.create_context()

    # Load data
    adapter.load_table(ctx, "orders", [Path("orders.parquet")])

    # Execute query
    result = adapter.execute_query(ctx, query)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

try:
    import polars as pl

    POLARS_AVAILABLE = True
except ImportError:
    pl = None  # type: ignore[assignment]
    POLARS_AVAILABLE = False

from benchbox.core.dataframe.tuning import DataFrameTuningConfiguration
from benchbox.platforms.dataframe.expression_family import (
    ExpressionFamilyAdapter,
)

logger = logging.getLogger(__name__)

# Type aliases for Polars types (when available)
if POLARS_AVAILABLE:
    PolarsDF = pl.DataFrame
    PolarsLazyDF = pl.LazyFrame
    PolarsExpr = pl.Expr
else:
    PolarsDF = Any
    PolarsLazyDF = Any
    PolarsExpr = Any


class PolarsDataFrameAdapter(ExpressionFamilyAdapter[PolarsDF, PolarsLazyDF, PolarsExpr]):
    """Polars adapter for expression-family DataFrame benchmarking.

    This adapter provides the reference implementation for expression-based
    DataFrame benchmarking using Polars.

    Features:
    - Lazy evaluation via pl.LazyFrame
    - Expression API (pl.col, pl.lit)
    - High-performance data loading
    - Native Parquet and CSV support

    Attributes:
        streaming: Enable streaming mode for large datasets
        rechunk: Rechunk data for better memory layout
        n_rows: Optional limit on rows to read
    """

    def __init__(
        self,
        working_dir: str | Path | None = None,
        verbose: bool = False,
        very_verbose: bool = False,
        streaming: bool = False,
        rechunk: bool = True,
        n_rows: int | None = None,
        tuning_config: DataFrameTuningConfiguration | None = None,
    ) -> None:
        """Initialize the Polars adapter.

        Args:
            working_dir: Working directory for data files
            verbose: Enable verbose logging
            very_verbose: Enable very verbose logging
            streaming: Enable streaming mode for large datasets
            rechunk: Rechunk data for better memory layout
            n_rows: Optional limit on rows to read (for testing)
            tuning_config: Optional tuning configuration for performance optimization

        Raises:
            ImportError: If Polars is not installed
        """
        if not POLARS_AVAILABLE:
            raise ImportError("Polars not installed. Install with: pip install polars")

        super().__init__(
            working_dir=working_dir,
            verbose=verbose,
            very_verbose=very_verbose,
            tuning_config=tuning_config,
        )

        # Default values (may be overridden by tuning config)
        self.streaming = streaming
        self.rechunk = rechunk
        self.n_rows = n_rows

        # Enable string cache for consistent string handling
        pl.enable_string_cache()

        # Validate and apply tuning configuration
        self._validate_and_apply_tuning()

    def _apply_tuning(self) -> None:
        """Apply Polars-specific tuning configuration.

        This method applies tuning settings from the configuration to the Polars
        runtime environment. Settings include:
        - Thread count (via POLARS_MAX_THREADS environment variable)
        - Streaming mode for large datasets
        - Chunk size for memory-constrained environments
        - Rechunking behavior after filter operations

        Note: Only non-default tuning config values are applied to avoid overriding
        explicit constructor arguments.
        """
        import os

        config = self._tuning_config

        # Apply thread count setting (None is the default, so any value means it was set)
        if config.parallelism.thread_count is not None:
            os.environ["POLARS_MAX_THREADS"] = str(config.parallelism.thread_count)
            self._log_verbose(f"Set POLARS_MAX_THREADS={config.parallelism.thread_count}")

        # Apply streaming mode only if explicitly enabled in tuning config
        if config.execution.streaming_mode:
            self.streaming = True
            self._log_verbose("Enabled streaming mode from tuning configuration")

        # Apply rechunk only if explicitly disabled in tuning config (default is True)
        if not config.memory.rechunk_after_filter:
            self.rechunk = False
            self._log_verbose("Disabled rechunk from tuning configuration")

        # Configure streaming chunk size if specified (None is default)
        if config.memory.chunk_size is not None:
            pl.Config.set_streaming_chunk_size(config.memory.chunk_size)
            self._log_verbose(f"Set streaming chunk size={config.memory.chunk_size}")

        # Configure engine affinity (affects .collect() behavior)
        if config.execution.engine_affinity == "streaming":
            self.streaming = True
            self._log_verbose("Set streaming mode from engine_affinity='streaming'")

    @property
    def platform_name(self) -> str:
        """Return the platform name."""
        return "Polars"

    # =========================================================================
    # Expression Methods
    # =========================================================================

    def col(self, name: str) -> PolarsExpr:
        """Create a Polars column expression.

        Args:
            name: The column name

        Returns:
            pl.Expr for the column
        """
        return pl.col(name)

    def lit(self, value: Any) -> PolarsExpr:
        """Create a Polars literal expression.

        Args:
            value: The literal value

        Returns:
            pl.Expr containing the literal value
        """
        return pl.lit(value)

    def element(self) -> PolarsExpr:
        """Create a Polars list element expression for use inside list.eval()."""
        return pl.element()

    def date_sub(self, column: PolarsExpr, days: int) -> PolarsExpr:
        """Subtract days from a date column.

        Args:
            column: The date column expression
            days: Number of days to subtract

        Returns:
            Expression with days subtracted
        """

        return column - pl.duration(days=days)

    def date_add(self, column: PolarsExpr, days: int) -> PolarsExpr:
        """Add days to a date column.

        Args:
            column: The date column expression
            days: Number of days to add

        Returns:
            Expression with days added
        """
        return column + pl.duration(days=days)

    def cast_date(self, column: PolarsExpr) -> PolarsExpr:
        """Cast a column to date type.

        Args:
            column: The column expression to cast

        Returns:
            Expression cast to Date type
        """
        return column.cast(pl.Date)

    def cast_string(self, column: PolarsExpr) -> PolarsExpr:
        """Cast a column to string type.

        Args:
            column: The column expression to cast

        Returns:
            Expression cast to Utf8 (string) type
        """
        return column.cast(pl.Utf8)

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
    ) -> PolarsLazyDF:
        """Read a CSV file into a Polars LazyFrame.

        Args:
            path: Path to the CSV file (can be glob pattern)
            delimiter: Field delimiter
            has_header: Whether file has header row
            column_names: Optional column names (overrides header)
            null_marker: The SQL dialect's null marker. ``None`` means empty fields
                stay '' in string columns (match DuckDB/pandas); ``""`` means empty
                fields are NULL. (Trailing delimiters are handled natively by
                truncate_ragged_lines.)

        Returns:
            Polars LazyFrame with the file contents
        """
        scan_kwargs: dict[str, Any] = {
            "separator": delimiter,
            "has_header": has_header,
            "rechunk": self.rechunk,
            "ignore_errors": True,
            # Handle files with or without trailing delimiters
            "truncate_ragged_lines": True,
            # Mirror the SQL dialect's empty-field semantics, matching the pandas
            # CSV path: when the loader keeps empty fields as '' (null_marker is
            # None, e.g. ClickBench) keep '' in string columns so the raw-CSV path
            # agrees with the SQL reference (DuckDB keeps ''), the Parquet path
            # (strings_can_be_null=False) and pandas; when the dialect treats empty
            # as NULL (null_marker == '', e.g. JoinOrder) leave Polars' default
            # empty->null. Without this, a prefer_parquet=False load reintroduces the
            # empty-string->null divergence (the cross-surface Q6/Q17/Q18 bug) on the
            # Polars surface. Numeric columns always treat an empty field as null.
            "missing_utf8_is_empty_string": null_marker is None,
        }

        # Add row limit if specified
        if self.n_rows is not None:
            scan_kwargs["n_rows"] = self.n_rows

        # Handle column names
        if column_names:
            scan_kwargs["new_columns"] = column_names

        # Scan the file(s)
        lf = pl.scan_csv(path, **scan_kwargs)

        return lf

    def read_parquet(self, path: Path) -> PolarsLazyDF:
        """Read a Parquet file into a Polars LazyFrame.

        Dictionary-encoded columns in Parquet are read as Categorical by Polars.
        We cast them back to String to avoid type mismatches in joins and filters.

        Args:
            path: Path to the Parquet file (can be glob pattern)

        Returns:
            Polars LazyFrame with the file contents
        """
        scan_kwargs: dict[str, Any] = {
            "rechunk": self.rechunk,
        }

        if self.n_rows is not None:
            scan_kwargs["n_rows"] = self.n_rows

        lf = pl.scan_parquet(path, **scan_kwargs)

        # Cast Categorical columns to String to prevent type mismatches
        # when joining or filtering (Parquet dictionary encoding -> Polars Categorical)
        schema = lf.collect_schema()
        cat_cols = [name for name, dtype in schema.items() if dtype == pl.Categorical]
        if cat_cols:
            lf = lf.with_columns([pl.col(c).cast(pl.String) for c in cat_cols])

        return lf

    def collect(self, df: PolarsLazyDF) -> PolarsDF:
        """Materialize a Polars LazyFrame.

        Args:
            df: The LazyFrame to materialize

        Returns:
            Materialized DataFrame
        """
        if isinstance(df, pl.LazyFrame):
            if self.streaming:
                return df.collect(engine="streaming")
            return df.collect()
        return df

    def get_row_count(self, df: PolarsDF | PolarsLazyDF) -> int:
        """Get the number of rows in a DataFrame.

        Args:
            df: The DataFrame or LazyFrame

        Returns:
            Number of rows
        """
        if isinstance(df, pl.LazyFrame):
            # Use select(count) for lazy frames
            return df.select(pl.len()).collect().item()
        return len(df)

    def scalar(self, df: PolarsDF | PolarsLazyDF, column: str | None = None) -> Any:
        """Extract a single scalar value from a DataFrame.

        Uses Polars' native .item() method for efficient scalar extraction.

        Args:
            df: The DataFrame or LazyFrame (should have exactly one row)
            column: Optional column name. If None, uses the first column.

        Returns:
            The scalar value

        Raises:
            ValueError: If the DataFrame is empty
        """
        # Materialize if lazy
        if isinstance(df, pl.LazyFrame):
            df = df.collect()

        if len(df) == 0:
            raise ValueError("Cannot extract scalar from empty DataFrame")

        # Select specific column if provided
        if column is not None:
            return df.select(column).item()

        # For single-column DataFrames, item() works directly
        if len(df.columns) == 1:
            return df.item()

        # For multi-column DataFrames, select first column
        return df.select(df.columns[0]).item()

    def scalar_to_df(self, data: dict[str, Any]) -> PolarsDF:
        """Create a single-row Polars DataFrame from scalar values.

        Args:
            data: Dictionary mapping column names to scalar values

        Returns:
            Polars DataFrame with a single row
        """
        return pl.DataFrame({k: [v] for k, v in data.items()})

    # =========================================================================
    # Override Methods
    # =========================================================================

    def _concat_dataframes(self, dfs: list[PolarsLazyDF]) -> PolarsLazyDF:
        """Concatenate multiple Polars DataFrames.

        Args:
            dfs: List of LazyFrames to concatenate

        Returns:
            Combined LazyFrame
        """
        if len(dfs) == 1:
            return dfs[0]
        return pl.concat(dfs)

    def _get_first_row(self, df: PolarsDF) -> tuple | None:
        """Get the first row of a Polars DataFrame.

        Args:
            df: The DataFrame

        Returns:
            First row as tuple, or None if empty
        """
        if isinstance(df, pl.LazyFrame):
            df = df.collect()

        if len(df) == 0:
            return None

        return tuple(df.row(0))

    def get_platform_info(self) -> dict[str, Any]:
        """Get platform information for reporting.

        Returns:
            Dictionary with platform details
        """
        info = {
            "platform": self.platform_name,
            "family": self.family,
            "streaming": self.streaming,
            "rechunk": self.rechunk,
            "working_dir": str(self.working_dir),
        }

        if POLARS_AVAILABLE:
            info["version"] = pl.__version__

        return info

    # =========================================================================
    # Polars-Specific Methods
    # =========================================================================

    def when(self, condition: PolarsExpr) -> Any:
        """Create a when expression for conditional logic.

        Args:
            condition: The condition expression

        Returns:
            Polars When builder
        """
        return pl.when(condition)

    def concat_str(self, *columns: str, separator: str = "") -> PolarsExpr:
        """Concatenate string columns.

        Args:
            *columns: Column names to concatenate
            separator: Separator between values

        Returns:
            Expression concatenating the columns
        """
        return pl.concat_str([pl.col(c) for c in columns], separator=separator)

    def sum(self, column: str) -> PolarsExpr:
        """Create a sum aggregation expression.

        Args:
            column: Column to sum

        Returns:
            Sum expression
        """
        return pl.col(column).sum()

    def mean(self, column: str) -> PolarsExpr:
        """Create a mean aggregation expression.

        Args:
            column: Column to average

        Returns:
            Mean expression
        """
        return pl.col(column).mean()

    def count(self) -> PolarsExpr:
        """Create a count expression.

        Returns:
            Count expression
        """
        return pl.len()

    def min(self, column: str) -> PolarsExpr:
        """Create a min aggregation expression.

        Args:
            column: Column to find minimum of

        Returns:
            Min expression
        """
        return pl.col(column).min()

    def max(self, column: str) -> PolarsExpr:
        """Create a max aggregation expression.

        Args:
            column: Column to find maximum of

        Returns:
            Max expression
        """
        return pl.col(column).max()

    # =========================================================================
    # Window Functions
    # =========================================================================

    def _polars_window_rank(
        self,
        method: str,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> PolarsExpr:
        """Shared Polars rank-window implementation.

        Args:
            method: Polars rank method - ``"min"`` (RANK), ``"ordinal"``
                (ROW_NUMBER), or ``"dense"`` (DENSE_RANK).
            order_by: List of (column_name, ascending) tuples for ordering.
            partition_by: Columns to partition by (optional).

        Returns:
            Polars expression for rank within partitions.
        """
        order_col, ascending = order_by[0]
        expr = pl.col(order_col)

        if ascending:
            rank_expr = expr.rank(method=method)
        else:
            rank_expr = expr.rank(method=method, descending=True)

        if partition_by:
            return rank_expr.over(partition_by)
        return rank_expr

    def window_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> PolarsExpr:
        """Create a RANK() window function expression."""
        return self._polars_window_rank("min", order_by, partition_by)

    def window_row_number(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> PolarsExpr:
        """Create a ROW_NUMBER() window function expression."""
        return self._polars_window_rank("ordinal", order_by, partition_by)

    def window_dense_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> PolarsExpr:
        """Create a DENSE_RANK() window function expression."""
        return self._polars_window_rank("dense", order_by, partition_by)

    def window_sum(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> PolarsExpr:
        """Create a SUM() OVER window function expression.

        Without order_by: Sum of all values in partition
        With order_by: Running/cumulative sum

        Args:
            column: Column to sum
            partition_by: Columns to partition by (optional)
            order_by: If provided, creates cumulative sum (optional)

        Returns:
            Polars expression for windowed sum
        """
        if order_by:
            # Cumulative sum (running total)
            sum_expr = pl.col(column).cum_sum()
        else:
            # Partition-wide sum
            sum_expr = pl.col(column).sum()

        if partition_by:
            return sum_expr.over(partition_by)
        return sum_expr

    def window_avg(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> PolarsExpr:
        """Create an AVG() OVER window function expression.

        Without order_by: Average of all values in partition
        With order_by: Running/cumulative average

        Args:
            column: Column to average
            partition_by: Columns to partition by (optional)
            order_by: If provided, creates cumulative average (optional)

        Returns:
            Polars expression for windowed average
        """
        if order_by:
            # Cumulative average: cum_sum / cum_count
            # Use row_number as the count of rows seen so far
            avg_expr = pl.col(column).cum_sum() / pl.col(column).cum_count()
        else:
            # Partition-wide average
            avg_expr = pl.col(column).mean()

        if partition_by:
            return avg_expr.over(partition_by)
        return avg_expr

    def window_count(
        self,
        column: str | None = None,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> PolarsExpr:
        """Create a COUNT() OVER window function expression.

        Args:
            column: Column to count (None for COUNT(*))
            partition_by: Columns to partition by (optional)
            order_by: If provided, creates cumulative count (optional)

        Returns:
            Polars expression for windowed count
        """
        if order_by:
            # Cumulative count
            if column:
                count_expr = pl.col(column).cum_count()
            else:
                count_expr = pl.lit(1).cum_sum()
        else:
            # Partition-wide count
            if column:
                count_expr = pl.col(column).count()
            else:
                count_expr = pl.len()

        if partition_by:
            return count_expr.over(partition_by)
        return count_expr

    def window_min(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> PolarsExpr:
        """Create a MIN() OVER window function expression.

        Args:
            column: Column to find minimum
            partition_by: Columns to partition by (optional)

        Returns:
            Polars expression for windowed minimum
        """
        min_expr = pl.col(column).min()

        if partition_by:
            return min_expr.over(partition_by)
        return min_expr

    def window_max(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> PolarsExpr:
        """Create a MAX() OVER window function expression.

        Args:
            column: Column to find maximum
            partition_by: Columns to partition by (optional)

        Returns:
            Polars expression for windowed maximum
        """
        max_expr = pl.col(column).max()

        if partition_by:
            return max_expr.over(partition_by)
        return max_expr

    def window_lag(
        self,
        column: str,
        offset: int = 1,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> PolarsExpr:
        """Create a LAG() window function expression."""
        order_col, ascending = order_by[0] if order_by else (column, True)
        expr = pl.col(column).shift(offset).sort_by(order_col, descending=not ascending)
        if partition_by:
            return expr.over(partition_by)
        return expr

    def window_lead(
        self,
        column: str,
        offset: int = 1,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> PolarsExpr:
        """Create a LEAD() window function expression."""
        order_col, ascending = order_by[0] if order_by else (column, True)
        expr = pl.col(column).shift(-offset).sort_by(order_col, descending=not ascending)
        if partition_by:
            return expr.over(partition_by)
        return expr

    def window_ntile(
        self,
        n: int,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> PolarsExpr:
        """Create a NTILE() window function expression."""
        order_col, ascending = order_by[0]
        # Polars doesn't have ntile directly; use rank-based calculation
        rank_expr = pl.col(order_col).rank(method="ordinal", descending=not ascending)
        count_expr = pl.col(order_col).count()
        # NTILE formula: ceil(rank * n / count)
        ntile_expr = ((rank_expr * pl.lit(n) - pl.lit(1)) / count_expr).floor().cast(pl.Int64) + pl.lit(1)
        if partition_by:
            return ntile_expr.over(partition_by)
        return ntile_expr

    def window_percent_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> PolarsExpr:
        """Create a PERCENT_RANK() window function expression."""
        order_col, ascending = order_by[0]
        # PERCENT_RANK = (rank - 1) / (count - 1)
        rank_expr = pl.col(order_col).rank(method="min", descending=not ascending)
        count_expr = pl.col(order_col).count()
        pct_expr = (rank_expr.cast(pl.Float64) - pl.lit(1.0)) / (count_expr.cast(pl.Float64) - pl.lit(1.0))
        if partition_by:
            return pct_expr.over(partition_by)
        return pct_expr

    def window_cume_dist(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> PolarsExpr:
        """Create a CUME_DIST() window function expression."""
        order_col, ascending = order_by[0]
        # CUME_DIST = count(value <= current) / total_count
        rank_expr = pl.col(order_col).rank(method="max", descending=not ascending)
        count_expr = pl.col(order_col).count()
        cd_expr = rank_expr.cast(pl.Float64) / count_expr.cast(pl.Float64)
        if partition_by:
            return cd_expr.over(partition_by)
        return cd_expr

    # =========================================================================
    # Union Operations
    # =========================================================================

    def union_all(self, *dataframes: PolarsLazyDF) -> PolarsLazyDF:
        """Union multiple DataFrames (UNION ALL equivalent).

        Args:
            *dataframes: LazyFrames to union

        Returns:
            Combined LazyFrame
        """
        if len(dataframes) == 0:
            raise ValueError("At least one DataFrame required for union")
        if len(dataframes) == 1:
            return dataframes[0]
        return pl.concat(list(dataframes))

    def rename_columns(self, df: PolarsLazyDF, mapping: dict[str, str]) -> PolarsLazyDF:
        """Rename columns in a DataFrame.

        Args:
            df: The LazyFrame
            mapping: Dict mapping old column names to new names

        Returns:
            LazyFrame with renamed columns
        """
        return df.rename(mapping)
