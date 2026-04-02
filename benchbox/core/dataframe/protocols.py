"""Protocol definitions for DataFrame operations.

This module defines the core protocols that DataFrame implementations must satisfy,
enabling type-safe polymorphism across different DataFrame libraries.

The protocols are designed to capture the common operations shared by both
Pandas-like and Expression-based DataFrame families.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence

# Type variable for generic DataFrame types
DF = TypeVar("DF", covariant=True)
Expr = TypeVar("Expr")


class JoinType(Enum):
    """Enumeration of supported join types.

    These join types are supported across all DataFrame families with
    consistent semantics.
    """

    INNER = "inner"
    LEFT = "left"
    RIGHT = "right"
    OUTER = "outer"
    CROSS = "cross"
    SEMI = "semi"
    ANTI = "anti"

    def __str__(self) -> str:
        """Return the string representation of the join type."""
        return self.value

    @classmethod
    def from_string(cls, value: str) -> JoinType:
        """Create a JoinType from a string value.

        Args:
            value: The string representation (case-insensitive)

        Returns:
            The corresponding JoinType enum value

        Raises:
            ValueError: If the value is not a valid join type
        """
        value_lower = value.lower()
        for join_type in cls:
            if join_type.value == value_lower:
                return join_type
        raise ValueError(f"Invalid join type: {value}. Valid types: {[j.value for j in cls]}")


class AggregateFunction(Enum):
    """Enumeration of supported aggregate functions.

    These functions are available across all DataFrame families.
    Platform-specific implementations translate to native function calls.
    """

    SUM = "sum"
    MEAN = "mean"
    AVG = "avg"  # Alias for mean
    COUNT = "count"
    MIN = "min"
    MAX = "max"
    FIRST = "first"
    LAST = "last"
    STD = "std"
    VAR = "var"
    MEDIAN = "median"
    COUNT_DISTINCT = "count_distinct"

    def __str__(self) -> str:
        """Return the string representation of the aggregate function."""
        return self.value

    @classmethod
    def from_string(cls, value: str) -> AggregateFunction:
        """Create an AggregateFunction from a string value.

        Args:
            value: The string representation (case-insensitive)

        Returns:
            The corresponding AggregateFunction enum value

        Raises:
            ValueError: If the value is not a valid aggregate function
        """
        value_lower = value.lower()
        for agg_func in cls:
            if agg_func.value == value_lower:
                return agg_func
        raise ValueError(f"Invalid aggregate function: {value}. Valid functions: {[a.value for a in cls]}")


class SortOrder(Enum):
    """Enumeration of sort ordering options."""

    ASC = "asc"
    DESC = "desc"

    def __str__(self) -> str:
        """Return the string representation of the sort order."""
        return self.value

    @property
    def ascending(self) -> bool:
        """Return True if this is ascending order."""
        return self == SortOrder.ASC


@runtime_checkable
class DataFrameOps(Protocol[DF]):
    """Protocol defining common DataFrame operations.

    This protocol captures the essential operations that both Pandas-like
    and Expression-based DataFrames support. Implementations provide
    family-specific or platform-specific implementations.

    Type Parameters:
        DF: The concrete DataFrame type (e.g., pd.DataFrame, pl.DataFrame)

    Design Notes:
        - Methods return the same protocol type for chaining
        - Operations are designed to be lazy-evaluation compatible
        - Both families support all operations (with different syntax)
    """

    def select(self, *columns: str) -> DataFrameOps[DF]:
        """Select specified columns from the DataFrame.

        This is the fundamental column projection operation supported
        by all DataFrame libraries.

        Args:
            *columns: Column names to select

        Returns:
            New DataFrame with only the specified columns

        Example:
            df.select('id', 'name', 'amount')
        """
        ...

    def filter(self, condition: Any) -> DataFrameOps[DF]:
        """Filter rows based on a condition.

        Args:
            condition: A boolean expression or Series.
                For Pandas family: boolean Series or string expression
                For Expression family: Expression object

        Returns:
            New DataFrame with only rows where condition is True

        Example:
            # Pandas family
            df.filter(df['amount'] > 100)

            # Expression family
            df.filter(col('amount') > 100)
        """
        ...

    def group_by(self, *columns: str) -> DataFrameGroupBy[DF]:
        """Group the DataFrame by specified columns.

        Args:
            *columns: Column names to group by

        Returns:
            DataFrameGroupBy object for aggregation

        Example:
            df.group_by('category', 'region').agg(sum('amount'))
        """
        ...

    def join(
        self,
        other: DataFrameOps[DF],
        on: str | Sequence[str] | None = None,
        left_on: str | Sequence[str] | None = None,
        right_on: str | Sequence[str] | None = None,
        how: JoinType | str = JoinType.INNER,
    ) -> DataFrameOps[DF]:
        """Join with another DataFrame.

        Args:
            other: The DataFrame to join with
            on: Column name(s) to join on (when same in both DataFrames)
            left_on: Column name(s) in left DataFrame
            right_on: Column name(s) in right DataFrame
            how: Join type (inner, left, right, outer, etc.)

        Returns:
            Joined DataFrame

        Example:
            orders.join(customers, on='customer_id', how=JoinType.LEFT)
        """
        ...

    def sort(
        self,
        *columns: str,
        ascending: bool | Sequence[bool] = True,
    ) -> DataFrameOps[DF]:
        """Sort the DataFrame by specified columns.

        Args:
            *columns: Column names to sort by
            ascending: Whether to sort ascending (True) or descending (False).
                Can be a single boolean for all columns or a sequence
                matching the number of columns.

        Returns:
            Sorted DataFrame

        Example:
            df.sort('date', 'amount', ascending=[True, False])
        """
        ...

    def with_column(self, name: str, expr: Any) -> DataFrameOps[DF]:
        """Add or replace a column with a computed expression.

        Args:
            name: Name for the new/replaced column
            expr: Expression to compute the column values.
                For Pandas family: Series or scalar
                For Expression family: Expression object

        Returns:
            DataFrame with the new/modified column

        Example:
            df.with_column('total', col('price') * col('quantity'))
        """
        ...

    def distinct(self) -> DataFrameOps[DF]:
        """Remove duplicate rows.

        Returns:
            DataFrame with duplicate rows removed
        """
        ...

    def limit(self, n: int) -> DataFrameOps[DF]:
        """Limit the number of rows returned.

        Args:
            n: Maximum number of rows to return

        Returns:
            DataFrame with at most n rows
        """
        ...

    def collect(self) -> Any:
        """Execute the query and return results.

        For lazy evaluation libraries (Polars, Dask), this triggers
        computation. For eager libraries (Pandas), this may be a no-op
        or convert to a specific format.

        Returns:
            Materialized result (concrete DataFrame or list of rows)
        """
        ...

    def count(self) -> int:
        """Return the number of rows in the DataFrame.

        Note: This may trigger computation for lazy DataFrames.

        Returns:
            Number of rows
        """
        ...

    @property
    def columns(self) -> list[str]:
        """Return the list of column names.

        Returns:
            List of column names
        """
        ...

    @property
    def shape(self) -> tuple[int, int]:
        """Return the shape of the DataFrame.

        Note: This may trigger computation for lazy DataFrames.

        Returns:
            Tuple of (rows, columns)
        """
        ...


@runtime_checkable
class DataFrameGroupBy(Protocol[DF]):
    """Protocol for grouped DataFrame operations.

    After calling group_by() on a DataFrame, this protocol defines
    the available aggregation operations.

    Type Parameters:
        DF: The concrete DataFrame type
    """

    def agg(self, *_aggregations: Any, **_named_aggregations: Any) -> DataFrameOps[DF]:
        """Apply aggregation functions to grouped data.

        Supports both positional and keyword arguments for flexibility
        across different family syntaxes.

        Args:
            *_aggregations: Aggregation expressions (Expression family)
                or list of column/function pairs (Pandas family)
            **_named_aggregations: Named aggregations as output_col=expr

        Returns:
            Aggregated DataFrame

        Example:
            # Pandas family
            grouped.agg({'amount': 'sum', 'count': 'count'})

            # Expression family
            grouped.agg(col('amount').sum(), col('id').count())

            # Named (both families)
            grouped.agg(total_amount=sum('amount'))
        """
        ...

    def sum(self, *columns: str) -> DataFrameOps[DF]:
        """Sum the specified columns within each group.

        Args:
            *columns: Column names to sum. If empty, sums all numeric columns.

        Returns:
            DataFrame with summed values per group
        """
        ...

    def mean(self, *columns: str) -> DataFrameOps[DF]:
        """Calculate mean of specified columns within each group.

        Args:
            *columns: Column names to average. If empty, averages all numeric columns.

        Returns:
            DataFrame with mean values per group
        """
        ...

    def count(self) -> DataFrameOps[DF]:
        """Count rows within each group.

        Returns:
            DataFrame with count per group
        """
        ...

    def min(self, *columns: str) -> DataFrameOps[DF]:
        """Find minimum of specified columns within each group.

        Args:
            *columns: Column names to find minimum of.

        Returns:
            DataFrame with minimum values per group
        """
        ...

    def max(self, *columns: str) -> DataFrameOps[DF]:
        """Find maximum of specified columns within each group.

        Args:
            *columns: Column names to find maximum of.

        Returns:
            DataFrame with maximum values per group
        """
        ...

    def first(self, *columns: str) -> DataFrameOps[DF]:
        """Get first value of specified columns within each group.

        Args:
            *columns: Column names to get first value of.

        Returns:
            DataFrame with first values per group
        """
        ...
