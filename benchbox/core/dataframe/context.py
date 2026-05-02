"""DataFrame context for table access and expression helpers.

This module provides the DataFrameContext protocol and implementation
that serves as the bridge between benchmark queries and actual DataFrames.

The context provides:
- Table registration and access
- Expression creation helpers (col, lit)
- Date/time utilities
- Platform-specific type handling

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar, runtime_checkable

if TYPE_CHECKING:
    pass

# Type variable for DataFrame type
DF = TypeVar("DF")


@runtime_checkable
class DataFrameContext(Protocol):
    """Protocol defining the context interface for DataFrame queries.

    The DataFrameContext provides table access and expression helpers
    that abstract away platform-specific details. Query implementations
    use the context to:

    1. Access registered tables: ctx.get_table('orders')
    2. Create column expressions: ctx.col('amount')
    3. Create literal values: ctx.lit(100)
    4. Handle date/time operations: ctx.date_sub(col, 7)

    This abstraction enables queries to be written once per family
    and executed on any platform in that family.

    Example:
        ```python
        def query_impl(ctx: DataFrameContext):
            orders = ctx.get_table('orders')
            # Use platform-agnostic operations
            return orders.filter(ctx.col('amount') > ctx.lit(100))
        ```
    """

    @property
    def platform(self) -> str:
        """Return the platform name."""
        ...

    def get_table(self, name: str) -> Any:
        """Get a registered table by name.

        Args:
            name: The table name (case-insensitive)

        Returns:
            The DataFrame for the table

        Raises:
            KeyError: If the table is not registered
        """
        ...

    def list_tables(self) -> list[str]:
        """Get a list of all registered table names.

        Returns:
            List of table names (lowercase)
        """
        ...

    def table_exists(self, name: str) -> bool:
        """Check if a table is registered.

        Args:
            name: The table name (case-insensitive)

        Returns:
            True if the table exists
        """
        ...

    def col(self, name: str) -> Any:
        """Create a column expression.

        The implementation depends on the DataFrame family:
        - Pandas: Returns a string (column name)
        - Expression: Returns a column expression (e.g., pl.col())

        Args:
            name: The column name

        Returns:
            Platform-specific column reference
        """
        ...

    def lit(self, value: Any) -> Any:
        """Create a literal value expression.

        Args:
            value: The literal value

        Returns:
            Platform-specific literal expression
        """
        ...

    def element(self) -> Any:
        """Create a list element expression for use inside list.eval().

        In Polars, this returns pl.element() which references the current
        list element. Named columns (col("element")) are not allowed
        inside eval() contexts.

        Returns:
            Platform-specific element expression
        """
        ...

    def date_sub(self, column: Any, days: int) -> Any:
        """Subtract days from a date column.

        Args:
            column: The date column expression
            days: Number of days to subtract

        Returns:
            Expression representing the date subtraction
        """
        ...

    def date_add(self, column: Any, days: int) -> Any:
        """Add days to a date column.

        Args:
            column: The date column expression
            days: Number of days to add

        Returns:
            Expression representing the date addition
        """
        ...

    def cast_date(self, column: Any) -> Any:
        """Cast a column to date type.

        Args:
            column: The column expression to cast

        Returns:
            Expression with date type
        """
        ...

    def cast_string(self, column: Any) -> Any:
        """Cast a column to string type.

        Args:
            column: The column expression to cast

        Returns:
            Expression with string type
        """
        ...

    # =========================================================================
    # Window Function Support
    # =========================================================================

    def window_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Any:
        """Create a RANK() window function expression.

        Rank values within partitions. Ties receive the same rank,
        with gaps in the sequence for subsequent values.

        Args:
            order_by: List of (column_name, ascending) tuples for ordering
            partition_by: Columns to partition by (optional)

        Returns:
            Platform-specific window expression

        Example:
            ```python
            # RANK() OVER (PARTITION BY category ORDER BY sales DESC)
            ctx.window_rank(
                order_by=[("sales", False)],
                partition_by=["category"]
            )
            ```
        """
        ...

    def window_row_number(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Any:
        """Create a ROW_NUMBER() window function expression.

        Assign sequential row numbers within partitions.

        Args:
            order_by: List of (column_name, ascending) tuples for ordering
            partition_by: Columns to partition by (optional)

        Returns:
            Platform-specific window expression
        """
        ...

    def window_dense_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Any:
        """Create a DENSE_RANK() window function expression.

        Like RANK but without gaps for ties.

        Args:
            order_by: List of (column_name, ascending) tuples for ordering
            partition_by: Columns to partition by (optional)

        Returns:
            Platform-specific window expression
        """
        ...

    def window_sum(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> Any:
        """Create a SUM() OVER window function expression.

        Without order_by: Sum of all values in partition
        With order_by: Running/cumulative sum

        Args:
            column: Column to sum
            partition_by: Columns to partition by (optional)
            order_by: If provided, creates cumulative sum (optional)

        Returns:
            Platform-specific window expression
        """
        ...

    def window_avg(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> Any:
        """Create an AVG() OVER window function expression.

        Without order_by: Average of all values in partition
        With order_by: Running/cumulative average

        Args:
            column: Column to average
            partition_by: Columns to partition by (optional)
            order_by: If provided, creates cumulative average (optional)

        Returns:
            Platform-specific window expression
        """
        ...

    def window_count(
        self,
        column: str | None = None,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> Any:
        """Create a COUNT() OVER window function expression.

        Args:
            column: Column to count (None for COUNT(*))
            partition_by: Columns to partition by (optional)
            order_by: If provided, creates cumulative count (optional)

        Returns:
            Platform-specific window expression
        """
        ...

    def window_min(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> Any:
        """Create a MIN() OVER window function expression.

        Args:
            column: Column to find minimum
            partition_by: Columns to partition by (optional)

        Returns:
            Platform-specific window expression
        """
        ...

    def window_max(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> Any:
        """Create a MAX() OVER window function expression.

        Args:
            column: Column to find maximum
            partition_by: Columns to partition by (optional)

        Returns:
            Platform-specific window expression
        """
        ...

    # =========================================================================
    # Union Operations
    # =========================================================================

    def union_all(self, *dataframes: Any) -> Any:
        """Union multiple DataFrames (UNION ALL equivalent).

        Concatenates DataFrames vertically, keeping all rows including duplicates.

        Args:
            *dataframes: DataFrames to union

        Returns:
            Combined DataFrame
        """
        ...

    def rename_columns(self, df: Any, mapping: dict[str, str]) -> Any:
        """Rename columns in a DataFrame.

        Args:
            df: The DataFrame
            mapping: Dict mapping old column names to new names

        Returns:
            DataFrame with renamed columns
        """
        ...

    def scalar(self, df: Any, column: str | None = None) -> Any:
        """Extract a single scalar value from a DataFrame.

        This is an optimized method for extracting a single value from a
        DataFrame with one row and one column. More efficient than
        `.collect()[0, 0]` as it uses platform-native scalar extraction.

        Args:
            df: The DataFrame (should have exactly one row)
            column: Optional column name. If None, uses the first column.

        Returns:
            The scalar value
        """
        ...

    def scalar_to_df(self, data: dict[str, Any]) -> Any:
        """Create a single-row DataFrame from scalar values.

        This method creates a DataFrame with one row containing the provided
        column-value pairs. It provides a platform-agnostic way to return
        scalar aggregation results as DataFrames, avoiding direct imports
        of pandas or other libraries in query implementations.

        Args:
            data: Dictionary mapping column names to scalar values.
                  Each value should be a single scalar (int, float, str, etc.),
                  not a list or array.

        Returns:
            DataFrame with a single row containing the scalar values

        Example:
            ```python
            # Instead of: pd.DataFrame({"count": [len(df)]})
            return ctx.scalar_to_df({"count": len(df)})

            # Multiple columns:
            return ctx.scalar_to_df({
                "total_orders": len(orders),
                "total_revenue": orders["price"].sum()
            })
            ```
        """
        ...

    @property
    def family(self) -> str:
        """Return the DataFrame family ('pandas' or 'expression')."""
        ...


class DataFrameContextImpl(Generic[DF], ABC):
    """Abstract base implementation for DataFrameContext.

    This class provides common functionality for both Pandas and
    Expression family contexts, with abstract methods for
    platform-specific operations.

    Type Parameters:
        DF: The concrete DataFrame type for this context

    Attributes:
        _tables: Dictionary mapping table names to DataFrames
        _platform: Platform name (e.g., 'pandas', 'polars')
        _family: Family name ('pandas' or 'expression')
    """

    def __init__(self, platform: str, family: str) -> None:
        """Initialize the context.

        Args:
            platform: Platform name (e.g., 'pandas', 'polars')
            family: Family name ('pandas' or 'expression')
        """
        self._tables: dict[str, DF] = {}
        self._platform = platform
        self._family = family

    @property
    def family(self) -> str:
        """Return the DataFrame family."""
        return self._family

    @property
    def platform(self) -> str:
        """Return the platform name."""
        return self._platform

    def register_table(self, name: str, df: DF) -> None:
        """Register a DataFrame as a named table.

        Args:
            name: Table name (will be lowercased)
            df: The DataFrame to register
        """
        self._tables[name.lower()] = df

    def unregister_table(self, name: str) -> bool:
        """Unregister a table.

        Args:
            name: Table name (case-insensitive)

        Returns:
            True if the table was unregistered, False if not found
        """
        name_lower = name.lower()
        if name_lower in self._tables:
            del self._tables[name_lower]
            return True
        return False

    def get_table(self, name: str) -> DF:
        """Get a registered table by name.

        Args:
            name: The table name (case-insensitive)

        Returns:
            The DataFrame for the table

        Raises:
            KeyError: If the table is not registered
        """
        name_lower = name.lower()
        if name_lower not in self._tables:
            available = ", ".join(sorted(self._tables.keys()))
            raise KeyError(f"Table '{name}' not found. Available tables: {available or 'none'}")
        return self._tables[name_lower]

    def list_tables(self) -> list[str]:
        """Get a list of all registered table names.

        Returns:
            Sorted list of table names
        """
        return sorted(self._tables.keys())

    def table_exists(self, name: str) -> bool:
        """Check if a table is registered.

        Args:
            name: The table name (case-insensitive)

        Returns:
            True if the table exists
        """
        return name.lower() in self._tables

    def clear_tables(self) -> None:
        """Remove all registered tables."""
        self._tables.clear()

    @abstractmethod
    def col(self, name: str) -> Any:
        """Create a column expression.

        Args:
            name: The column name

        Returns:
            Platform-specific column reference
        """

    @abstractmethod
    def lit(self, value: Any) -> Any:
        """Create a literal value expression.

        Args:
            value: The literal value

        Returns:
            Platform-specific literal expression
        """

    def element(self) -> Any:
        """Create a list element expression for use inside list.eval().

        Returns pl.element() on Polars. Raises NotImplementedError on
        platforms that don't support list.eval().
        """
        raise NotImplementedError(f"element() not supported on {self._platform}")

    @abstractmethod
    def date_sub(self, column: Any, days: int) -> Any:
        """Subtract days from a date column.

        Args:
            column: The date column expression
            days: Number of days to subtract

        Returns:
            Expression representing the date subtraction
        """

    @abstractmethod
    def date_add(self, column: Any, days: int) -> Any:
        """Add days to a date column.

        Args:
            column: The date column expression
            days: Number of days to add

        Returns:
            Expression representing the date addition
        """

    @abstractmethod
    def cast_date(self, column: Any) -> Any:
        """Cast a column to date type.

        Args:
            column: The column expression to cast

        Returns:
            Expression with date type
        """

    @abstractmethod
    def cast_string(self, column: Any) -> Any:
        """Cast a column to string type.

        Args:
            column: The column expression to cast

        Returns:
            Expression with string type
        """

    # =========================================================================
    # Window Function Support (Abstract Methods)
    # =========================================================================

    @abstractmethod
    def window_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Any:
        """Create a RANK() window function expression."""

    @abstractmethod
    def window_row_number(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Any:
        """Create a ROW_NUMBER() window function expression."""

    @abstractmethod
    def window_dense_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Any:
        """Create a DENSE_RANK() window function expression."""

    @abstractmethod
    def window_sum(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> Any:
        """Create a SUM() OVER window function expression."""

    @abstractmethod
    def window_avg(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> Any:
        """Create an AVG() OVER window function expression."""

    @abstractmethod
    def window_count(
        self,
        column: str | None = None,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> Any:
        """Create a COUNT() OVER window function expression."""

    @abstractmethod
    def window_min(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> Any:
        """Create a MIN() OVER window function expression."""

    @abstractmethod
    def window_max(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> Any:
        """Create a MAX() OVER window function expression."""

    # =========================================================================
    # Union Operations (Abstract Methods)
    # =========================================================================

    @abstractmethod
    def union_all(self, *dataframes: Any) -> Any:
        """Union multiple DataFrames (UNION ALL equivalent)."""

    @abstractmethod
    def rename_columns(self, df: Any, mapping: dict[str, str]) -> Any:
        """Rename columns in a DataFrame."""

    @abstractmethod
    def scalar(self, df: Any, column: str | None = None) -> Any:
        """Extract a single scalar value from a DataFrame.

        This is an optimized method for extracting a single value from a
        DataFrame with one row and one column.

        Args:
            df: The DataFrame (should have exactly one row)
            column: Optional column name. If None, uses the first column.

        Returns:
            The scalar value
        """

    @abstractmethod
    def scalar_to_df(self, data: dict[str, Any]) -> Any:
        """Create a single-row DataFrame from scalar values.

        This method creates a DataFrame with one row containing the provided
        column-value pairs. It provides a platform-agnostic way to return
        scalar aggregation results as DataFrames.

        Args:
            data: Dictionary mapping column names to scalar values

        Returns:
            DataFrame with a single row containing the scalar values
        """

    def to_date(self, value: str | date | datetime) -> date:
        """Convert a value to a Python date.

        This helper is useful for creating date literals in queries.

        Args:
            value: String (YYYY-MM-DD format) or date/datetime

        Returns:
            Python date object
        """
        if isinstance(value, datetime):
            return value.date()
        elif isinstance(value, date):
            return value
        elif isinstance(value, str):
            return datetime.strptime(value, "%Y-%m-%d").date()
        else:
            raise TypeError(f"Cannot convert {type(value)} to date")

    def days(self, n: int) -> timedelta:
        """Create a timedelta of n days.

        Args:
            n: Number of days

        Returns:
            timedelta representing n days
        """
        return timedelta(days=n)
