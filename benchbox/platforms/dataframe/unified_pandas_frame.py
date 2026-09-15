"""Unified DataFrame wrapper for Pandas-family platforms.

This module provides UnifiedPandasFrame, a wrapper class that provides a
consistent DataFrame API across different Pandas-family platforms
(Pandas, cuDF, Dask).

The wrapper intercepts method calls and translates them to platform-specific
implementations. This allows query implementations to use a single API that
works transparently across all Pandas-family platforms.

Key API translations:
- groupby(as_index=False): Works on Pandas/cuDF; for Dask uses reset_index()
- .dt accessor: Works on all platforms with proper handling
- nunique aggregation: Standard on Pandas; Dask requires separate computation

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from benchbox.platforms.dataframe.pandas_family import PandasFamilyAdapter

logger = logging.getLogger(__name__)

# Type variable for the underlying DataFrame type
DF = TypeVar("DF")


def _is_dask_df(df: Any) -> bool:
    """Check if a DataFrame is a Dask DataFrame."""
    type_module = type(df).__module__
    return "dask" in type_module


def _is_dataframe(obj: Any) -> bool:
    """Check if an object is a DataFrame (not a Series).

    DataFrames have 'columns' (Index of column names) and no 'name' attribute.
    Series have 'name' (single column name) and no 'columns' attribute.

    This distinction is critical because Dask Series also have groupby(),
    so we can't rely on that check alone.
    """
    # Must have columns attribute (DataFrames have this, Series don't)
    if not hasattr(obj, "columns"):
        return False

    # Series have a 'name' attribute (single string), DataFrames don't
    # Check if it's a Series by looking for the 'name' attribute without 'columns'
    # being an Index-like object
    type_name = type(obj).__name__
    return "Series" not in type_name


class UnifiedPandasFrame(Generic[DF]):
    """Platform-agnostic DataFrame wrapper for Pandas-family.

    Intercepts operations and routes through adapter for platform-specific handling.
    Transparent to query implementations - they use normal DataFrame API.

    This wrapper provides:
    - Transparent groupby handling (as_index translation for Dask)
    - Merge operations with wrapper preservation
    - Copy, sort, head operations that preserve wrapping
    - Attribute proxying for direct DataFrame access

    Attributes:
        _df: The underlying native DataFrame
        _adapter: Reference to the parent adapter for platform-specific operations
    """

    def __init__(self, df: DF, adapter: PandasFamilyAdapter[DF]) -> None:
        """Initialize the wrapper.

        Args:
            df: The underlying native DataFrame
            adapter: Reference to the parent adapter
        """
        # Use object.__setattr__ to avoid triggering __setattr__ during init
        object.__setattr__(self, "_df", df)
        object.__setattr__(self, "_adapter", adapter)

    @property
    def native(self) -> DF:
        """Access the underlying native DataFrame.

        Use this when you need to pass the DataFrame to platform-specific
        functions or when the query is complete.

        Returns:
            The native DataFrame
        """
        return self._df

    # =========================================================================
    # DataFrame Property Access
    # =========================================================================

    @property
    def columns(self) -> Any:
        """Get column names from the DataFrame."""
        return self._df.columns

    @property
    def dtypes(self) -> Any:
        """Get column data types."""
        return self._df.dtypes

    @property
    def shape(self) -> tuple[int, ...]:
        """Get DataFrame shape."""
        return self._df.shape

    @property
    def iloc(self) -> Any:
        """Integer-location based indexer."""
        return self._df.iloc

    @property
    def loc(self) -> Any:
        """Label-location based indexer."""
        return self._df.loc

    @property
    def values(self) -> Any:
        """Get underlying numpy array."""
        return self._df.values

    # =========================================================================
    # Attribute Access Proxy
    # =========================================================================

    def __getattr__(self, name: str) -> Any:
        """Proxy attribute access to the underlying DataFrame.

        This allows transparent access to DataFrame methods and properties
        not explicitly defined in this wrapper.

        Args:
            name: Attribute name

        Returns:
            The attribute from the underlying DataFrame
        """
        attr = getattr(self._df, name)
        if callable(attr):
            return self._wrap_method(attr, name)
        return attr

    def __setattr__(self, name: str, value: Any) -> None:
        """Set attribute on the underlying DataFrame.

        Args:
            name: Attribute name
            value: Value to set
        """
        if name in ("_df", "_adapter"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._df, name, value)

    def _wrap_method(self, method: Any, name: str) -> Any:
        """Wrap a DataFrame method to preserve wrapper on DataFrame results.

        Args:
            method: The method to wrap
            name: Method name for debugging

        Returns:
            Wrapped method that preserves UnifiedPandasFrame wrapping
        """

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            result = method(*args, **kwargs)
            # If result is a DataFrame, wrap it
            if _is_dataframe(result):
                return UnifiedPandasFrame(result, self._adapter)
            return result

        return wrapped

    # =========================================================================
    # Item Access (Column/Row Selection)
    # =========================================================================

    def __getitem__(self, key: Any) -> UnifiedPandasFrame[DF] | Any:
        """Column/row access with auto-wrapping.

        Args:
            key: Column name(s) or boolean mask

        Returns:
            UnifiedPandasFrame for DataFrame results, raw value otherwise
        """
        result = self._df[key]
        # If result is a DataFrame, wrap it
        if _is_dataframe(result):
            return UnifiedPandasFrame(result, self._adapter)
        return result

    def __setitem__(self, key: Any, value: Any) -> None:
        """Set column value.

        Args:
            key: Column name
            value: Value to set
        """
        # Unwrap if value is a UnifiedPandasFrame
        if isinstance(value, UnifiedPandasFrame):
            value = value._df
        self._df[key] = value

    # =========================================================================
    # GroupBy Operations
    # =========================================================================

    def groupby(
        self,
        by: str | list[str],
        as_index: bool = True,
        **kwargs: Any,
    ) -> UnifiedPandasGroupBy[DF]:
        """Create a grouped DataFrame for aggregation.

        Intercepts groupby to handle platform differences:
        - Pandas/cuDF: Support as_index=False natively
        - Dask: Does not support as_index, use reset_index() instead

        Args:
            by: Column(s) to group by
            as_index: Whether to use group columns as index (default True)
            **kwargs: Additional arguments passed to native groupby

        Returns:
            UnifiedPandasGroupBy for aggregation
        """
        by_list = [by] if isinstance(by, str) else list(by)
        return UnifiedPandasGroupBy(
            self._df,
            by_list,
            self._adapter,
            as_index=as_index,
            kwargs=kwargs,
        )

    # =========================================================================
    # Merge Operations
    # =========================================================================

    def merge(
        self,
        right: UnifiedPandasFrame[DF] | DF,
        on: str | list[str] | None = None,
        left_on: str | list[str] | None = None,
        right_on: str | list[str] | None = None,
        how: str = "inner",
        **kwargs: Any,
    ) -> UnifiedPandasFrame[DF]:
        """Merge with another DataFrame.

        Args:
            right: Right DataFrame (UnifiedPandasFrame or native)
            on: Column(s) to join on (when same in both)
            left_on: Column(s) from left DataFrame
            right_on: Column(s) from right DataFrame
            how: Join type ('inner', 'left', 'right', 'outer')
            **kwargs: Additional arguments

        Returns:
            UnifiedPandasFrame with merge result
        """
        # Unwrap right if it's a UnifiedPandasFrame
        right_df = right._df if isinstance(right, UnifiedPandasFrame) else right

        result = self._df.merge(
            right_df,
            on=on,
            left_on=left_on,
            right_on=right_on,
            how=how,
            **kwargs,
        )
        return UnifiedPandasFrame(result, self._adapter)

    # =========================================================================
    # Copy Operations
    # =========================================================================

    def copy(self, deep: bool = True) -> UnifiedPandasFrame[DF]:
        """Copy the DataFrame.

        For Dask DataFrames, deep copy is not supported - only shallow copy
        of the computational graph is allowed. This method handles that
        automatically.

        Args:
            deep: Whether to create a deep copy (ignored for Dask)

        Returns:
            UnifiedPandasFrame with copy
        """
        # Dask only supports shallow copy of the computational graph
        result = self._df.copy(deep=False) if _is_dask_df(self._df) else self._df.copy(deep=deep)
        return UnifiedPandasFrame(result, self._adapter)

    # =========================================================================
    # Sort Operations
    # =========================================================================

    def sort_values(
        self,
        by: str | list[str],
        ascending: bool | list[bool] = True,
        **kwargs: Any,
    ) -> UnifiedPandasFrame[DF]:
        """Sort by column values.

        Args:
            by: Column(s) to sort by
            ascending: Sort order
            **kwargs: Additional arguments

        Returns:
            UnifiedPandasFrame with sorted result
        """
        result = self._df.sort_values(by=by, ascending=ascending, **kwargs)
        return UnifiedPandasFrame(result, self._adapter)

    # =========================================================================
    # Limit/Head Operations
    # =========================================================================

    def head(self, n: int = 5) -> UnifiedPandasFrame[DF]:
        """Get first n rows.

        Args:
            n: Number of rows

        Returns:
            UnifiedPandasFrame with first n rows
        """
        result = self._df.head(n)
        return UnifiedPandasFrame(result, self._adapter)

    def tail(self, n: int = 5) -> UnifiedPandasFrame[DF]:
        """Get last n rows.

        Args:
            n: Number of rows

        Returns:
            UnifiedPandasFrame with last n rows
        """
        result = self._df.tail(n)
        return UnifiedPandasFrame(result, self._adapter)

    # =========================================================================
    # Rename Operations
    # =========================================================================

    def rename(self, columns: dict[str, str] | None = None, **kwargs: Any) -> UnifiedPandasFrame[DF]:
        """Rename columns.

        Args:
            columns: Dict mapping old names to new names
            **kwargs: Additional arguments

        Returns:
            UnifiedPandasFrame with renamed columns
        """
        result = self._df.rename(columns=columns, **kwargs)
        return UnifiedPandasFrame(result, self._adapter)

    # =========================================================================
    # Drop Operations
    # =========================================================================

    def drop(
        self,
        labels: str | list[str] | None = None,
        columns: str | list[str] | None = None,
        **kwargs: Any,
    ) -> UnifiedPandasFrame[DF]:
        """Drop columns or rows.

        Args:
            labels: Labels to drop
            columns: Columns to drop
            **kwargs: Additional arguments

        Returns:
            UnifiedPandasFrame without dropped items
        """
        result = self._df.drop(labels=labels, columns=columns, **kwargs)
        return UnifiedPandasFrame(result, self._adapter)

    # =========================================================================
    # Dask/Lazy Evaluation Support
    # =========================================================================

    def compute(self) -> Any:
        """Materialize lazy DataFrame (Dask).

        For non-Dask DataFrames, returns self unchanged.

        Returns:
            Materialized DataFrame
        """
        if hasattr(self._df, "compute"):
            return self._df.compute()
        return self._df

    # =========================================================================
    # Length/Boolean Operations
    # =========================================================================

    def __len__(self) -> int:
        """Get number of rows."""
        return len(self._df)

    def __repr__(self) -> str:
        """String representation."""
        return f"UnifiedPandasFrame({type(self._df).__name__})"


class UnifiedPandasGroupBy(Generic[DF]):
    """Platform-agnostic GroupBy wrapper for Pandas-family.

    Intercepts aggregation operations and handles platform differences:
    - Pandas/cuDF: Use as_index=False in groupby
    - Dask: Use reset_index() after aggregation

    Attributes:
        _df: The source DataFrame
        _by: Columns to group by
        _adapter: Reference to the parent adapter
        _as_index: Whether to use group columns as index
        _kwargs: Additional groupby arguments
    """

    def __init__(
        self,
        df: DF,
        by: list[str],
        adapter: PandasFamilyAdapter[DF],
        as_index: bool = True,
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the GroupBy wrapper.

        Args:
            df: The source DataFrame
            by: Columns to group by
            adapter: Reference to the parent adapter
            as_index: Whether to use group columns as index
            kwargs: Additional groupby arguments
        """
        self._df = df
        self._by = by
        self._adapter = adapter
        self._as_index = as_index
        self._kwargs = kwargs or {}

    def agg(self, *args: Any, **kwargs: Any) -> UnifiedPandasFrame[DF]:
        """Aggregate the grouped data.

        Routes to adapter's groupby_agg for platform-specific handling.
        Supports both positional dict argument and keyword arguments.

        Args:
            *args: Positional arguments (e.g., dict of aggregations)
            **kwargs: Named aggregations (e.g., sum_qty=("qty", "sum"))

        Returns:
            UnifiedPandasFrame with aggregation results
        """
        # Merge positional dict arg with kwargs
        agg_spec = args[0] if args and isinstance(args[0], dict) else kwargs

        result = self._adapter.groupby_agg(
            self._df,
            self._by,
            agg_spec,
            as_index=self._as_index,
        )
        return UnifiedPandasFrame(result, self._adapter)

    def _native_groupby(self) -> Any:
        """Create the native groupby object."""
        if _is_dask_df(self._df):
            return self._df.groupby(self._by, **self._kwargs)  # type: ignore[union-attr]
        return self._df.groupby(self._by, as_index=self._as_index, **self._kwargs)  # type: ignore[union-attr]

    def __getitem__(self, key: str | list[str]) -> Any:
        """Column selection on grouped data (e.g., grouped["col"]).

        Args:
            key: Column name or list of column names

        Returns:
            Native grouped series/frame for further operations (quantile, etc.)
        """
        return self._native_groupby()[key]

    def __getattr__(self, name: str) -> Any:
        """Proxy attribute access to native groupby.

        For methods not explicitly handled, delegate to native groupby.

        Args:
            name: Attribute name

        Returns:
            The attribute from native groupby
        """
        return getattr(self._native_groupby(), name)
