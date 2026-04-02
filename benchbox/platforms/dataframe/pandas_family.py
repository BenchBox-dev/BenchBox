"""Pandas Family Adapter base class for DataFrame benchmarking.

This module provides the PandasFamilyAdapter abstract base class that
serves as the foundation for Pandas-like DataFrame libraries:
- Pandas (reference implementation)
- Modin (distributed Pandas)
- cuDF (GPU-accelerated)
- Vaex (out-of-core)
- Dask (lazy distributed)

Pandas-like libraries share common characteristics:
- String-based column access: df['column']
- Boolean indexing: df[df['col'] > 5]
- Dict-based aggregation: .agg({'col': 'sum'})
- Eager evaluation (except Dask which adds .compute())

The adapter handles:
- Data loading (CSV, Parquet, TBL formats)
- Table registration and context management
- Query execution with timing
- Result collection and validation

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from benchbox.core.dataframe.context import DataFrameContextImpl
from benchbox.core.dataframe.profiling import (
    MemoryTracker,
    QueryExecutionProfile,
    QueryProfileContext,
)
from benchbox.core.dataframe.query import DataFrameQuery
from benchbox.core.dataframe.tuning import DataFrameTuningConfiguration
from benchbox.platforms.dataframe.benchmark_mixin import BenchmarkExecutionMixin
from benchbox.platforms.dataframe.tuning_mixin import TuningConfigurableMixin
from benchbox.platforms.dataframe.unified_pandas_frame import UnifiedPandasFrame
from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.file_format import detect_data_format

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Type variable for generic DataFrame type
DF = TypeVar("DF")  # DataFrame type (e.g., pd.DataFrame)


class PandasFamilyContext(DataFrameContextImpl[DF], Generic[DF]):
    """Context implementation for Pandas-family adapters.

    This context provides table access and expression helpers specific to
    Pandas-like DataFrame libraries. Unlike expression-based libraries,
    Pandas uses string column names directly.

    Type Parameters:
        DF: The DataFrame type (e.g., pd.DataFrame)

    Attributes:
        adapter: Reference to the parent adapter for platform-specific operations
    """

    def __init__(self, adapter: PandasFamilyAdapter[DF]) -> None:
        """Initialize the context.

        Args:
            adapter: The parent adapter instance
        """
        super().__init__(platform=adapter.platform_name, family="pandas")
        self._adapter = adapter

    def get_table(self, name: str) -> UnifiedPandasFrame[DF]:
        """Get a registered table wrapped in UnifiedPandasFrame.

        This override wraps native DataFrames in UnifiedPandasFrame to provide
        a consistent API across Pandas, Modin, cuDF, and Dask.

        Args:
            name: The table name (case-insensitive)

        Returns:
            UnifiedPandasFrame wrapping the native DataFrame
        """
        native_df = super().get_table(name)
        return UnifiedPandasFrame(native_df, self._adapter)

    def col(self, name: str) -> str:
        """Return column name as string for Pandas-style access.

        In Pandas-family libraries, column references are just strings
        used for dictionary-style access: df['column_name']

        Args:
            name: The column name

        Returns:
            The column name string
        """
        return name

    def lit(self, value: Any) -> Any:
        """Return literal value directly for Pandas.

        In Pandas, literal values are used directly without wrapping.

        Args:
            value: The literal value

        Returns:
            The value unchanged
        """
        return value

    def date_sub(self, column: Any, days: int) -> dict[str, Any]:
        """Create a date subtraction operation descriptor.

        In Pandas family, date operations are applied during query execution.
        This returns a descriptor that the query implementation will use.

        Args:
            column: Column name (string)
            days: Number of days to subtract

        Returns:
            Operation descriptor for query implementation
        """
        return self._adapter.date_sub(column, days)

    def date_add(self, column: Any, days: int) -> dict[str, Any]:
        """Create a date addition operation descriptor.

        Args:
            column: Column name (string)
            days: Number of days to add

        Returns:
            Operation descriptor for query implementation
        """
        return self._adapter.date_add(column, days)

    def cast_date(self, column: Any) -> dict[str, Any]:
        """Create a date cast operation descriptor.

        Args:
            column: Column name (string)

        Returns:
            Operation descriptor for query implementation
        """
        return self._adapter.cast_date(column)

    def cast_string(self, column: Any) -> dict[str, Any]:
        """Create a string cast operation descriptor.

        Args:
            column: Column name (string)

        Returns:
            Operation descriptor for query implementation
        """
        return self._adapter.cast_string(column)

    # =========================================================================
    # Window Function Support
    # =========================================================================

    def window_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a RANK() window function descriptor.

        Args:
            order_by: List of (column_name, ascending) tuples for ordering
            partition_by: Columns to partition by (optional)

        Returns:
            Operation descriptor for window rank
        """
        return self._adapter.window_rank(order_by, partition_by)

    def window_row_number(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a ROW_NUMBER() window function descriptor."""
        return self._adapter.window_row_number(order_by, partition_by)

    def window_dense_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a DENSE_RANK() window function descriptor."""
        return self._adapter.window_dense_rank(order_by, partition_by)

    def window_sum(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> dict[str, Any]:
        """Create a SUM() OVER window function descriptor."""
        return self._adapter.window_sum(column, partition_by, order_by)

    def window_avg(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> dict[str, Any]:
        """Create an AVG() OVER window function descriptor."""
        return self._adapter.window_avg(column, partition_by, order_by)

    def window_count(
        self,
        column: str | None = None,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> dict[str, Any]:
        """Create a COUNT() OVER window function descriptor."""
        return self._adapter.window_count(column, partition_by, order_by)

    def window_min(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a MIN() OVER window function descriptor."""
        return self._adapter.window_min(column, partition_by)

    def window_max(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a MAX() OVER window function descriptor."""
        return self._adapter.window_max(column, partition_by)

    # =========================================================================
    # Union Operations
    # =========================================================================

    def union_all(self, *dataframes: Any) -> Any:
        """Union multiple DataFrames (UNION ALL equivalent)."""
        return self._adapter.union_all(*dataframes)

    def concat(self, dataframes: list[Any]) -> Any:
        """Concatenate multiple DataFrames (platform-agnostic).

        This is the preferred way to combine DataFrames in Pandas-family queries.
        Uses the adapter's platform-specific concat implementation.

        For Dask, this uses dd.concat instead of pd.concat.
        For Pandas/Modin/cuDF, this uses pd.concat.

        Args:
            dataframes: List of DataFrames to concatenate

        Returns:
            Combined DataFrame
        """
        # Unwrap UnifiedPandasFrame instances
        from benchbox.platforms.dataframe.unified_pandas_frame import UnifiedPandasFrame

        unwrapped = [df._df if isinstance(df, UnifiedPandasFrame) else df for df in dataframes]
        result = self._adapter.concat(unwrapped)
        return UnifiedPandasFrame(result, self._adapter)

    def rename_columns(self, df: Any, mapping: dict[str, str]) -> Any:
        """Rename columns in a DataFrame."""
        return self._adapter.rename_columns(df, mapping)

    def groupby_size(
        self,
        df: Any,
        by: str | list[str],
        name: str = "size",
    ) -> Any:
        """Group by columns and count rows per group.

        This is a platform-agnostic replacement for:
            df.groupby(by).size().reset_index(name='count')

        The pattern above doesn't work on Dask because:
        1. .size() returns a Series
        2. Dask Series.reset_index() doesn't support 'name' parameter

        Args:
            df: DataFrame to group
            by: Column(s) to group by
            name: Name for the count column (default 'size')

        Returns:
            DataFrame with group columns and count column
        """
        from benchbox.platforms.dataframe.unified_pandas_frame import UnifiedPandasFrame

        # Unwrap if needed
        native_df = df._df if isinstance(df, UnifiedPandasFrame) else df

        result = self._adapter.groupby_size(native_df, by, name)
        return UnifiedPandasFrame(result, self._adapter)

    def groupby_agg(
        self,
        df: Any,
        by: str | list[str],
        agg_spec: dict[str, Any],
        as_index: bool = False,
    ) -> Any:
        """Perform grouped aggregation with platform-specific handling.

        This is a platform-agnostic replacement for:
            df.groupby(by, as_index=False).agg(**agg_spec)

        The pattern above doesn't work on Dask because Dask's groupby()
        doesn't support as_index parameter. The adapter handles this
        by using reset_index() after aggregation on Dask.

        Args:
            df: DataFrame to group
            by: Column(s) to group by
            agg_spec: Aggregation specification (named or direct)
            as_index: Whether to use group columns as index (default False)

        Returns:
            Aggregated DataFrame
        """
        from benchbox.platforms.dataframe.unified_pandas_frame import UnifiedPandasFrame

        # Unwrap if needed
        native_df = df._df if isinstance(df, UnifiedPandasFrame) else df

        result = self._adapter.groupby_agg(native_df, by, agg_spec, as_index=as_index)
        return UnifiedPandasFrame(result, self._adapter)

    def scalar(self, df: Any, column: str | None = None) -> Any:
        """Extract a single scalar value from a DataFrame.

        Delegates to the adapter's platform-specific implementation.

        Args:
            df: The DataFrame (should have exactly one row)
            column: Optional column name. If None, uses the first column.

        Returns:
            The scalar value
        """
        return self._adapter.scalar(df, column)

    def scalar_to_df(self, data: dict[str, Any]) -> Any:
        """Create a single-row DataFrame from scalar values.

        This creates a DataFrame with one row containing the provided values.
        Provides a platform-agnostic way to return scalar aggregation results.

        Args:
            data: Dictionary mapping column names to scalar values

        Returns:
            UnifiedPandasFrame wrapping a single-row DataFrame
        """
        from benchbox.platforms.dataframe.unified_pandas_frame import UnifiedPandasFrame

        native_df = self._adapter.scalar_to_df(data)
        return UnifiedPandasFrame(native_df, self._adapter)

    def to_set(self, series_or_df: Any) -> set[Any]:
        """Convert a Series or single-column DataFrame to a set.

        This is used for Dask compatibility when using .isin().
        Dask's .isin() doesn't accept Dask Series, so we need to
        compute the values to a set first.

        Args:
            series_or_df: A Series or single-column DataFrame

        Returns:
            Set of unique values
        """
        from benchbox.platforms.dataframe.unified_pandas_frame import UnifiedPandasFrame

        # Unwrap if needed
        native = series_or_df._df if isinstance(series_or_df, UnifiedPandasFrame) else series_or_df

        # If it's a DataFrame (2D), extract the first column to get a Series (1D)
        # Use ndim for duck-typing: Series.ndim == 1, DataFrame.ndim == 2
        if hasattr(native, "ndim") and native.ndim == 2:
            col = native.columns[0]
            native = native[col]

        # For Dask, compute first
        if hasattr(native, "compute"):
            native = native.compute()

        # Return as set
        return set(native.unique())

    def filter_gt(self, df: Any, column: str, threshold: Any) -> Any:
        """Filter DataFrame where column > threshold (Dask-compatible).

        Dask has issues with boolean indexing due to index alignment.
        This method uses .query() with local_dict for variable resolution.

        Args:
            df: DataFrame to filter
            column: Column name to compare
            threshold: Value to compare against

        Returns:
            Filtered DataFrame
        """
        from benchbox.platforms.dataframe.unified_pandas_frame import UnifiedPandasFrame

        # Unwrap if needed
        native_df = df._df if isinstance(df, UnifiedPandasFrame) else df

        # Use query with local_dict for Dask-safe filtering
        if hasattr(native_df, "query"):
            result = native_df.query(f"`{column}` > @_threshold", local_dict={"_threshold": threshold})
        else:
            # Fallback for platforms without query
            result = native_df[native_df[column] > threshold]

        return UnifiedPandasFrame(result, self._adapter)


class PandasFamilyAdapter(BenchmarkExecutionMixin, TuningConfigurableMixin, ABC, Generic[DF]):
    """Abstract base class for Pandas-like DataFrame platform adapters.

    This class provides the common interface and functionality for
    Pandas-family DataFrame libraries (Pandas, Modin, cuDF, Vaex, Dask).

    Implements run_benchmark() for unified interface with SQL adapters,
    enabling polymorphic adapter usage without caller branching.

    Subclasses must implement:
    - read_csv(): Read CSV file to DataFrame
    - read_parquet(): Read Parquet file to DataFrame
    - to_datetime(): Convert to datetime
    - timedelta(): Create timedelta object

    Type Parameters:
        DF: The concrete DataFrame type

    Attributes:
        platform_name: Human-readable platform name
        working_dir: Directory for data files
        verbose: Enable verbose logging
    """

    def __init__(
        self,
        working_dir: str | Path | None = None,
        verbose: bool = False,
        very_verbose: bool = False,
        tuning_config: DataFrameTuningConfiguration | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            working_dir: Working directory for data files
            verbose: Enable verbose logging
            very_verbose: Enable very verbose logging
            tuning_config: Optional tuning configuration for performance optimization
        """
        self.working_dir = Path(working_dir) if working_dir else Path.cwd()
        self.verbose = verbose
        self.very_verbose = very_verbose
        self._context: PandasFamilyContext[DF] | None = None

        # Initialize tuning configuration (from mixin)
        self._init_tuning(tuning_config)

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the human-readable platform name."""

    @property
    def family(self) -> str:
        """Return the DataFrame family name."""
        return "pandas"

    def _build_ctas_sort_sql(self, table_name: str, sort_columns: list[Any]) -> None:
        """DataFrame platforms do not use post-load CTAS table rewrites for sorting.

        Physical sort ordering for pandas-family platforms is applied during
        Parquet cache generation via ``DataFrameWriteConfiguration.sort_by``, which
        instructs ``FormatConverter._apply_write_config`` to sort the PyArrow table
        before writing to disk. This produces pre-sorted Parquet files that are read
        directly by the adapter, requiring no further rewrite after loading.
        """
        return None

    # =========================================================================
    # Abstract Methods - Must be implemented by subclasses
    # =========================================================================

    @abstractmethod
    def read_csv(
        self,
        path: Path,
        *,
        delimiter: str = ",",
        header: int | None = 0,
        names: list[str] | None = None,
    ) -> DF:
        """Read a CSV file into a DataFrame.

        Args:
            path: Path to the CSV file
            delimiter: Field delimiter
            header: Row to use as header (None for no header)
            names: Column names (if header is None)

        Returns:
            DataFrame with the file contents
        """

    @abstractmethod
    def read_parquet(self, path: Path) -> DF:
        """Read a Parquet file into a DataFrame.

        Args:
            path: Path to the Parquet file

        Returns:
            DataFrame with the file contents
        """

    @abstractmethod
    def to_datetime(self, series: Any) -> Any:
        """Convert a Series to datetime type.

        Args:
            series: The Series to convert

        Returns:
            Datetime Series
        """

    @abstractmethod
    def timedelta_days(self, days: int) -> timedelta:
        """Create a timedelta representing the given number of days.

        Args:
            days: Number of days

        Returns:
            Timedelta object
        """

    @abstractmethod
    def concat(self, dfs: list[DF]) -> DF:
        """Concatenate multiple DataFrames.

        Args:
            dfs: List of DataFrames to concatenate

        Returns:
            Combined DataFrame
        """

    @abstractmethod
    def get_row_count(self, df: DF) -> int:
        """Get the number of rows in a DataFrame.

        Args:
            df: The DataFrame

        Returns:
            Number of rows
        """

    # =========================================================================
    # Date Operation Methods
    # =========================================================================

    def date_sub(self, column: str, days: int) -> dict[str, Any]:
        """Create a date subtraction operation descriptor.

        Args:
            column: The column name
            days: Number of days to subtract

        Returns:
            Operation descriptor
        """
        return {"op": "date_sub", "column": column, "days": days}

    def date_add(self, column: str, days: int) -> dict[str, Any]:
        """Create a date addition operation descriptor.

        Args:
            column: The column name
            days: Number of days to add

        Returns:
            Operation descriptor
        """
        return {"op": "date_add", "column": column, "days": days}

    def cast_date(self, column: str) -> dict[str, Any]:
        """Create a date cast operation descriptor.

        Args:
            column: The column name

        Returns:
            Operation descriptor
        """
        return {"op": "cast_date", "column": column}

    def cast_string(self, column: str) -> dict[str, Any]:
        """Create a string cast operation descriptor.

        Args:
            column: The column name

        Returns:
            Operation descriptor
        """
        return {"op": "cast_string", "column": column}

    # =========================================================================
    # Window Function Methods
    # =========================================================================

    def window_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a RANK() window function descriptor.

        Args:
            order_by: List of (column_name, ascending) tuples for ordering
            partition_by: Columns to partition by (optional)

        Returns:
            Operation descriptor for applying window rank
        """
        return {
            "op": "window_rank",
            "order_by": order_by,
            "partition_by": partition_by or [],
        }

    def window_row_number(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a ROW_NUMBER() window function descriptor."""
        return {
            "op": "window_row_number",
            "order_by": order_by,
            "partition_by": partition_by or [],
        }

    def window_dense_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a DENSE_RANK() window function descriptor."""
        return {
            "op": "window_dense_rank",
            "order_by": order_by,
            "partition_by": partition_by or [],
        }

    def window_sum(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> dict[str, Any]:
        """Create a SUM() OVER window function descriptor."""
        return {
            "op": "window_sum",
            "column": column,
            "partition_by": partition_by or [],
            "order_by": order_by,
        }

    def window_avg(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> dict[str, Any]:
        """Create an AVG() OVER window function descriptor."""
        return {
            "op": "window_avg",
            "column": column,
            "partition_by": partition_by or [],
            "order_by": order_by,
        }

    def window_count(
        self,
        column: str | None = None,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> dict[str, Any]:
        """Create a COUNT() OVER window function descriptor."""
        return {
            "op": "window_count",
            "column": column,
            "partition_by": partition_by or [],
            "order_by": order_by,
        }

    def window_min(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a MIN() OVER window function descriptor."""
        return {
            "op": "window_min",
            "column": column,
            "partition_by": partition_by or [],
        }

    def window_max(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a MAX() OVER window function descriptor."""
        return {
            "op": "window_max",
            "column": column,
            "partition_by": partition_by or [],
        }

    # =========================================================================
    # Union Operations
    # =========================================================================

    def union_all(self, *dataframes: DF) -> DF:
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
        return self.concat(list(dataframes))

    def rename_columns(self, df: DF, mapping: dict[str, str]) -> DF:
        """Rename columns in a DataFrame.

        Args:
            df: The DataFrame
            mapping: Dict mapping old column names to new names

        Returns:
            DataFrame with renamed columns
        """
        return df.rename(columns=mapping)  # type: ignore[attr-defined]

    def merge(
        self,
        left: DF,
        right: DF,
        on: str | list[str] | None = None,
        left_on: str | list[str] | None = None,
        right_on: str | list[str] | None = None,
        how: str = "inner",
    ) -> DF:
        """Merge two DataFrames using the shared pandas-style API.

        The wrapper keeps join semantics centralized while allowing subclasses
        to override merge backend selection via ``_merge_frames`` where needed
        (for example, module-level merge helpers in distributed/GPU adapters).
        """
        return self._merge_frames(
            left,
            right,
            on=on,
            left_on=left_on,
            right_on=right_on,
            how=how,
        )

    def _merge_frames(
        self,
        left: DF,
        right: DF,
        *,
        on: str | list[str] | None,
        left_on: str | list[str] | None,
        right_on: str | list[str] | None,
        how: str,
    ) -> DF:
        """Default merge implementation using DataFrame.merge.

        Subclasses may override to use module-level merge functions (e.g.
        cudf.merge, dask.dataframe.merge) instead of the instance method.
        """
        if not hasattr(left, "merge"):
            raise TypeError(f"{self.platform_name} merge requires DataFrame-like inputs, got {type(left).__name__}")
        return left.merge(
            right,
            on=on,
            left_on=left_on,
            right_on=right_on,
            how=how,
        )  # type: ignore[return-value]

    def scalar(self, df: DF, column: str | None = None) -> Any:
        """Extract a single scalar value from a DataFrame.

        Uses Pandas' .iloc for efficient scalar extraction.

        Args:
            df: The DataFrame (should have exactly one row)
            column: Optional column name. If None, uses the first column.

        Returns:
            The scalar value

        Raises:
            ValueError: If the DataFrame is empty or has more than one row
        """
        # For Dask, compute first
        if hasattr(df, "compute"):
            df = df.compute()  # type: ignore[attr-defined]

        row_count = len(df)  # type: ignore[arg-type]
        if row_count == 0:
            raise ValueError("Cannot extract scalar from empty DataFrame")
        if row_count > 1:
            raise ValueError(f"Expected exactly one row, got {row_count}")

        # Get the value from the specified column or first column
        if column is not None:
            return df[column].iloc[0]  # type: ignore[index]

        # Return first column, first row value
        return df.iloc[0, 0]  # type: ignore[index]

    def scalar_to_df(self, data: dict[str, Any]) -> DF:
        """Create a single-row DataFrame from scalar values.

        This is the base implementation for Pandas-family adapters. It uses
        the native DataFrame creation mechanism for the platform.

        Args:
            data: Dictionary mapping column names to scalar values

        Returns:
            DataFrame with a single row containing the scalar values
        """
        return self._create_single_row_df(data)

    def _create_single_row_df(self, data: dict[str, Any]) -> DF:
        """Platform-specific single-row DataFrame creation.

        Override in subclasses for platform-specific implementations.
        Default uses Pandas-style dict-with-list construction.

        Args:
            data: Dictionary mapping column names to scalar values

        Returns:
            Single-row DataFrame
        """
        # Default implementation wraps each value in a list
        # This works for Pandas, Modin, cuDF
        # Subclasses may override for platform-specific optimizations
        import pandas as pd

        return pd.DataFrame({k: [v] for k, v in data.items()})  # type: ignore[return-value]

    def groupby_size(
        self,
        df: DF,
        by: str | list[str],
        name: str = "size",
    ) -> DF:
        """Group by columns and count rows per group.

        This is a platform-agnostic replacement for:
            df.groupby(by).size().reset_index(name='count')

        Args:
            df: Input DataFrame
            by: Column(s) to group by
            name: Name for the count column (default 'size')

        Returns:
            DataFrame with group columns and count column
        """
        by_list = [by] if isinstance(by, str) else list(by)
        # Use size() then reset_index() with name parameter (works on Pandas)
        result = df.groupby(by_list).size().reset_index(name=name)  # type: ignore[attr-defined]
        return result  # type: ignore[return-value]

    # =========================================================================
    # GroupBy Aggregation (Platform-Specific)
    # =========================================================================

    def groupby_agg(
        self,
        df: DF,
        by: str | list[str],
        agg_spec: dict[str, Any],
        as_index: bool = False,
    ) -> DF:
        """Perform grouped aggregation with platform-specific handling.

        This is the default implementation for Pandas/Modin/cuDF which support
        as_index=False natively. Dask overrides this to use reset_index() instead.

        Args:
            df: Input DataFrame
            by: Column(s) to group by
            agg_spec: Aggregation specification. Supports:
                - Named aggs: {"sum_qty": ("qty", "sum"), "avg_price": ("price", "mean")}
                - Direct aggs: {"qty": "sum", "price": "mean"}
            as_index: Whether to use group columns as index (default False)

        Returns:
            Aggregated DataFrame
        """
        # Check if this is named aggregation (tuples) or direct dict-style
        # Named: {"sum_qty": ("qty", "sum")} -> use **agg_spec
        # Direct: {"qty": "sum"} -> use agg_spec directly
        is_named_agg = any(isinstance(v, tuple) for v in agg_spec.values())

        if is_named_agg:
            return df.groupby(by, as_index=as_index).agg(**agg_spec)  # type: ignore[return-value]
        else:
            return df.groupby(by, as_index=as_index).agg(agg_spec)  # type: ignore[return-value]

    # =========================================================================
    # Concrete Methods - Common functionality
    # =========================================================================

    def create_context(self) -> PandasFamilyContext[DF]:
        """Create a new context for query execution.

        The context provides table access and expression helpers.

        Returns:
            New PandasFamilyContext instance
        """
        self._context = PandasFamilyContext(self)
        return self._context

    def get_context(self) -> PandasFamilyContext[DF]:
        """Get the current context, creating one if needed.

        Returns:
            The current context
        """
        if self._context is None:
            return self.create_context()
        return self._context

    def load_table(
        self,
        ctx: PandasFamilyContext[DF],
        table_name: str,
        file_paths: list[Path],
        column_names: list[str] | None = None,
        delimiter: str | None = None,
    ) -> int:
        """Load a table from data files.

        Automatically detects file format (Parquet, CSV, TBL) and loads
        appropriately.

        Args:
            ctx: The context to register the table in
            table_name: Name for the table
            file_paths: List of file paths to load
            column_names: Optional column names for headerless files

        Returns:
            Number of rows loaded
        """
        if not file_paths:
            raise ValueError(f"No files provided for table '{table_name}'")

        # Detect format from first file
        first_file = file_paths[0]
        format_type = self._detect_format(first_file)

        self._log_verbose(f"Loading table {table_name} from {len(file_paths)} file(s), format: {format_type}")

        if format_type == "parquet":
            df = self._load_parquet_files(file_paths)
        else:
            # CSV or TBL
            actual_delimiter = delimiter if delimiter is not None else ("|" if format_type == "tbl" else ",")
            has_header = format_type == "csv"
            df = self._load_csv_files(
                file_paths,
                delimiter=actual_delimiter,
                has_header=has_header,
                column_names=column_names,
            )

        # Register table
        ctx.register_table(table_name, df)

        # Get row count
        row_count = self.get_row_count(df)
        self._log_verbose(f"Loaded table {table_name}: {row_count:,} rows")

        return row_count

    def load_tables_from_data_source(
        self,
        ctx: PandasFamilyContext[DF],
        data_dir: Path,
        schema_info: dict[str, dict] | None = None,
    ) -> dict[str, int]:
        """Load all tables from a data directory.

        Args:
            ctx: The context to register tables in
            data_dir: Directory containing data files
            schema_info: Optional schema information with column names

        Returns:
            Dictionary mapping table name to row count
        """
        from benchbox.platforms.dataframe.shared_loading import load_tables_from_data_source_impl

        return load_tables_from_data_source_impl(self, ctx, data_dir, schema_info)

    def execute_query(
        self,
        ctx: PandasFamilyContext[DF],
        query: DataFrameQuery,
        query_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a DataFrame query and return results.

        Args:
            ctx: The context with registered tables
            query: The query to execute
            query_id: Optional query ID (defaults to query.query_id)

        Returns:
            Dictionary with execution results
        """
        qid = query_id or query.query_id
        self._log_verbose(f"Executing query {qid}: {query.query_name}")

        start_time = mono_time()

        try:
            # Get the pandas implementation
            impl = query.get_impl_for_family("pandas")
            if impl is None:
                raise ValueError(f"Query '{qid}' has no pandas implementation")

            # Execute the query
            result_df = impl(ctx)

            # Compute if lazy (Dask)
            if hasattr(result_df, "compute"):
                result_df = result_df.compute()

            # Get row count
            row_count = self.get_row_count(result_df)

            # Get first row if available
            first_row = self._get_first_row(result_df)

            execution_time = elapsed_seconds(start_time)

            self._log_verbose(f"Query {qid} completed in {execution_time:.3f}s, returned {row_count} rows")

            return {
                "query_id": qid,
                "status": "SUCCESS",
                "execution_time_seconds": execution_time,
                "rows_returned": row_count,
                "first_row": first_row,
            }

        except Exception as e:
            execution_time = elapsed_seconds(start_time)
            error_msg = str(e)
            logger.error(f"Query {qid} failed: {error_msg}")

            return {
                "query_id": qid,
                "status": "FAILED",
                "execution_time_seconds": execution_time,
                "error": error_msg,
            }

    def execute_query_profiled(
        self,
        ctx: PandasFamilyContext[DF],
        query: DataFrameQuery,
        query_id: str | None = None,
        *,
        track_memory: bool = True,
        memory_sample_interval_ms: int = 50,
    ) -> tuple[dict[str, Any], QueryExecutionProfile]:
        """Execute a DataFrame query with comprehensive profiling.

        This method provides detailed profiling including:
        - Query execution time
        - Compute/collection time (for Dask)
        - Peak memory usage during execution

        Note: Pandas-family adapters don't have lazy evaluation planning
        overhead like Expression-family, but Dask has compute time.

        Args:
            ctx: The context with registered tables
            query: The query to execute
            query_id: Optional query ID (defaults to query.query_id)
            track_memory: Whether to track memory usage (default: True)
            memory_sample_interval_ms: Memory sampling interval (default: 50ms)

        Returns:
            Tuple of (result_dict, QueryExecutionProfile)
            - result_dict: Same format as execute_query()
            - profile: Detailed execution profile

        Example:
            result, profile = adapter.execute_query_profiled(ctx, query)
            emit(f"Execution time: {profile.execution_time_ms}ms")
            emit(f"Peak memory: {profile.peak_memory_mb}MB")
        """
        qid = query_id or query.query_id
        self._log_verbose(f"Executing query {qid} with profiling: {query.query_name}")

        # Create profile context
        profile_ctx = QueryProfileContext(qid, self.platform_name)
        profile_ctx._start_time = mono_time()

        # Start memory tracking if enabled
        memory_tracker: MemoryTracker | None = None
        if track_memory:
            memory_tracker = MemoryTracker(sample_interval_ms=memory_sample_interval_ms)
            memory_tracker.start()

        try:
            # Get the pandas implementation
            impl = query.get_impl_for_family("pandas")
            if impl is None:
                raise ValueError(f"Query '{qid}' has no pandas implementation")

            # Execute the query (Pandas family is eager, so this includes "planning")
            result_df = impl(ctx)

            # Compute if lazy (Dask) - track as collect phase
            if hasattr(result_df, "compute"):
                profile_ctx.start_collect()
                result_df = result_df.compute()
                profile_ctx.end_collect()

            # Get row count
            row_count = self.get_row_count(result_df)
            profile_ctx.set_rows(row_count)

            # Get first row if available
            first_row = self._get_first_row(result_df)

            # Stop memory tracking and record
            if memory_tracker is not None:
                peak_memory = memory_tracker.stop()
                profile_ctx.set_peak_memory(peak_memory)

                # Add memory stats as metrics
                stats = memory_tracker.get_statistics()
                profile_ctx.add_metric("memory_baseline_mb", stats["baseline_mb"])
                profile_ctx.add_metric("memory_delta_mb", stats["peak_delta_mb"])
                profile_ctx.add_metric("memory_samples", stats["sample_count"])

            # Get the profile
            profile = profile_ctx.get_profile()
            execution_time = profile.execution_time_ms / 1000.0

            self._log_verbose(
                f"Query {qid} completed in {execution_time:.3f}s, "
                f"collect={profile.collect_time_ms:.1f}ms, "
                f"rows={row_count}"
            )

            result_dict = {
                "query_id": qid,
                "status": "SUCCESS",
                "execution_time_seconds": execution_time,
                "rows_returned": row_count,
                "first_row": first_row,
            }

            return result_dict, profile

        except Exception as e:
            # Stop memory tracking on error
            if memory_tracker is not None:
                memory_tracker.stop()

            # Get profile even on error
            profile = profile_ctx.get_profile()
            execution_time = profile.execution_time_ms / 1000.0
            error_msg = str(e)
            logger.error(f"Query {qid} failed: {error_msg}")

            result_dict = {
                "query_id": qid,
                "status": "FAILED",
                "execution_time_seconds": execution_time,
                "error": error_msg,
            }

            return result_dict, profile

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _detect_format(self, path: Path) -> str:
        """Detect file format from path.

        Uses centralized utility that handles compression extensions.

        Args:
            path: Path to the file

        Returns:
            Format string: 'parquet', 'csv', or 'tbl'
        """
        return detect_data_format(path)

    def _load_parquet_files(self, file_paths: list[Path]) -> DF:
        """Load Parquet files.

        Args:
            file_paths: Paths to Parquet files

        Returns:
            Combined DataFrame
        """
        if len(file_paths) == 1:
            return self.read_parquet(file_paths[0])

        # Multiple files - load and concatenate
        dfs = [self.read_parquet(f) for f in file_paths]
        return self.concat(dfs)

    def _load_csv_files(
        self,
        file_paths: list[Path],
        delimiter: str,
        has_header: bool,
        column_names: list[str] | None,
    ) -> DF:
        """Load CSV/TBL files.

        Args:
            file_paths: Paths to CSV files
            delimiter: Field delimiter
            has_header: Whether files have headers
            column_names: Optional column names

        Returns:
            Combined DataFrame
        """
        header = 0 if has_header else None
        names = column_names if not has_header else None

        if len(file_paths) == 1:
            return self.read_csv(
                file_paths[0],
                delimiter=delimiter,
                header=header,
                names=names,
            )

        # Multiple files - load and concatenate
        dfs = [
            self.read_csv(
                f,
                delimiter=delimiter,
                header=header,
                names=names,
            )
            for f in file_paths
        ]
        return self.concat(dfs)

    def _get_first_row(self, df: DF) -> tuple | None:
        """Get the first row of a DataFrame.

        Default implementation returns None.
        Subclasses should override.

        Args:
            df: The DataFrame

        Returns:
            First row as tuple, or None
        """
        return None

    def _log_verbose(self, message: str) -> None:
        """Log a verbose message if verbose mode is enabled."""
        if self.verbose:
            logger.info(message)

    def _log_very_verbose(self, message: str) -> None:
        """Log a very verbose message if very_verbose mode is enabled."""
        if self.very_verbose:
            logger.debug(message)
