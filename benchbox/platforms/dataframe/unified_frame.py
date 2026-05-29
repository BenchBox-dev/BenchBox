"""Unified DataFrame wrapper for platform-agnostic expression-family queries.

This module provides UnifiedLazyFrame, a wrapper class that provides a
consistent DataFrame API across different expression-family platforms
(Polars, PySpark, DataFusion).

The wrapper intercepts method calls and translates them to the appropriate
platform-specific API. This allows query implementations to use a single
API (similar to Polars) that works across all platforms.

Key API translations:
- join(left_on=, right_on=): Works on all platforms
- group_by(): Translates to groupBy() on PySpark
- unique(): Translates to distinct() on PySpark
- sort(descending=): Translates to orderBy() with asc()/desc() on PySpark
- col().sum()/mean()/count(): Works on all platforms via UnifiedExpr

DataFusion Compatibility Notes:
    The DataFusion support includes experimental AST parsing for handling
    aggregate arithmetic expressions. This was tested with DataFusion 43.0.0
    and may not work with other versions if the error message format changes.
    See _get_datafusion_ast_string() for details.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    import polars as pl
    from datafusion import DataFrame as DataFusionDataFrame, Expr as DataFusionExpr
    from pyspark.sql import Column as PySparkColumn, DataFrame as PySparkDataFrame

    from benchbox.platforms.dataframe.expression_family import ExpressionFamilyAdapter
    from benchbox.platforms.dataframe.protocol import LazyFrameLike

logger = logging.getLogger(__name__)

# Type variable for the underlying DataFrame type
DF = TypeVar("DF")
Expr = TypeVar("Expr")

# =============================================================================
# DataFusion Type Mapping (module-level for efficiency)
# =============================================================================
# Maps string type names to PyArrow types for DataFusion casting.
# Defined at module level to avoid recreation on each cast() call.
_DATAFUSION_TYPE_MAPPING: dict[str, Any] | None = None
_NO_LITERAL_VALUE = object()


def _get_datafusion_type_mapping() -> dict[str, Any]:
    """Get or create the DataFusion type mapping dict (lazy initialization)."""
    global _DATAFUSION_TYPE_MAPPING
    if _DATAFUSION_TYPE_MAPPING is None:
        import pyarrow as pa

        _DATAFUSION_TYPE_MAPPING = {
            "int8": pa.int8(),
            "int16": pa.int16(),
            "int32": pa.int32(),
            "int64": pa.int64(),
            "uint8": pa.uint8(),
            "uint16": pa.uint16(),
            "uint32": pa.uint32(),
            "uint64": pa.uint64(),
            "float32": pa.float32(),
            "float64": pa.float64(),
            "utf8": pa.utf8(),
            "string": pa.utf8(),
            "str": pa.utf8(),
            "bool": pa.bool_(),
            "boolean": pa.bool_(),
            "date": pa.date32(),
            "date32": pa.date32(),
        }
    return _DATAFUSION_TYPE_MAPPING


def _is_pyspark_column(expr: Any) -> bool:
    """Check if an expression is a PySpark Column."""
    type_name = type(expr).__module__
    return "pyspark" in type_name and "Column" in type(expr).__name__


def _is_polars_expr(expr: Any) -> bool:
    """Check if an expression is a Polars Expr."""
    type_name = type(expr).__module__
    return "polars" in type_name and "Expr" in type(expr).__name__


def _unwrap_unified_expr(value: Any) -> Any:
    if isinstance(value, UnifiedExpr):
        literal_value = getattr(value, "_literal_value", _NO_LITERAL_VALUE)
        return value._expr if literal_value is _NO_LITERAL_VALUE else literal_value
    return value


class UnifiedStrExpr:
    """Platform-agnostic string expression namespace.

    Provides Polars-style .str accessor methods that work across platforms:
    - Polars: Uses native .str.starts_with(), etc.
    - PySpark: Uses .startswith(), .contains(), etc.
    - DataFusion: Uses functions.starts_with(), etc.
    """

    def __init__(self, expr: Any, is_pyspark: bool, is_datafusion: bool = False) -> None:
        """Initialize the string expression wrapper.

        Args:
            expr: Native expression (PySpark Column, Polars Expr, or DataFusion Expr)
            is_pyspark: Whether the expression is a PySpark Column
            is_datafusion: Whether the expression is a DataFusion Expr
        """
        self._expr = expr
        self._is_pyspark = is_pyspark
        self._is_datafusion = is_datafusion

    def starts_with(self, prefix: str) -> UnifiedExpr:
        """Check if string starts with prefix.

        Args:
            prefix: The prefix to check for

        Returns:
            UnifiedExpr with boolean result
        """
        prefix = _unwrap_unified_expr(prefix)
        if self._is_pyspark:
            return UnifiedExpr(self._expr.startswith(prefix))
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            prefix = prefix if _is_datafusion_expr(prefix) else df_lit(prefix)
            return UnifiedExpr(df_f.starts_with(self._expr, prefix))
        return UnifiedExpr(self._expr.str.starts_with(prefix))

    def ends_with(self, suffix: str) -> UnifiedExpr:
        """Check if string ends with suffix.

        Args:
            suffix: The suffix to check for

        Returns:
            UnifiedExpr with boolean result
        """
        suffix = _unwrap_unified_expr(suffix)
        if self._is_pyspark:
            return UnifiedExpr(self._expr.endswith(suffix))
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            suffix = suffix if _is_datafusion_expr(suffix) else df_lit(suffix)
            return UnifiedExpr(df_f.ends_with(self._expr, suffix))
        return UnifiedExpr(self._expr.str.ends_with(suffix))

    def contains(self, pattern: str) -> UnifiedExpr:
        """Check if string contains pattern.

        Args:
            pattern: The pattern to search for (regex for Polars/DataFusion, literal for PySpark)

        Returns:
            UnifiedExpr with boolean result
        """
        pattern = _unwrap_unified_expr(pattern)
        if self._is_pyspark:
            # PySpark .contains() uses SQL LIKE pattern, but .rlike() uses regex
            # For compatibility with Polars regex, use rlike
            return UnifiedExpr(self._expr.rlike(pattern))
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            pattern = pattern if _is_datafusion_expr(pattern) else df_lit(pattern)
            return UnifiedExpr(df_f.regexp_like(self._expr, pattern))
        return UnifiedExpr(self._expr.str.contains(pattern))

    def slice(self, offset: int, length: int | None = None) -> UnifiedExpr:
        """Extract substring.

        Args:
            offset: Starting position (0-indexed)
            length: Number of characters (None for rest of string)

        Returns:
            UnifiedExpr with substring
        """
        if self._is_pyspark:
            # PySpark substr is 1-indexed
            # If length is None, use a large number to get rest of string
            substr_length = length if length is not None else 1000000
            return UnifiedExpr(self._expr.substr(offset + 1, substr_length))
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            # DataFusion substring is 1-indexed like SQL and takes (string, position, length)
            substr_length = length if length is not None else 1000000
            return UnifiedExpr(df_f.substring(self._expr, df_lit(offset + 1), df_lit(substr_length)))
        return UnifiedExpr(self._expr.str.slice(offset, length))

    def to_uppercase(self) -> UnifiedExpr:
        """Convert string to uppercase."""
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.upper(self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f

            return UnifiedExpr(df_f.upper(self._expr))
        return UnifiedExpr(self._expr.str.to_uppercase())

    def to_lowercase(self) -> UnifiedExpr:
        """Convert string to lowercase."""
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.lower(self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f

            return UnifiedExpr(df_f.lower(self._expr))
        return UnifiedExpr(self._expr.str.to_lowercase())

    def split(self, separator: str) -> UnifiedListExpr:
        """Split string by separator, returning a list expression.

        Args:
            separator: The string to split on

        Returns:
            UnifiedListExpr wrapping the resulting list-typed expression
        """
        separator = _unwrap_unified_expr(separator)
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedListExpr(F.split(self._expr, separator), is_pyspark=True)
        if self._is_datafusion:
            # string_to_array not in v50 Python bindings; use split_part proxy
            return _DataFusionSplitListExpr(self._expr, separator)
        return UnifiedListExpr(self._expr.str.split(separator), is_polars=True)

    def len_chars(self) -> UnifiedExpr:
        """Get character length of string.

        Returns:
            UnifiedExpr with integer character count
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.length(self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f

            return UnifiedExpr(df_f.character_length(self._expr))
        return UnifiedExpr(self._expr.str.len_chars())


class _DataFusionSplitListExpr:
    """Proxy for DataFusion str.split() that delegates .list.get(n) to split_part.

    DataFusion v50 Python bindings lack string_to_array. This proxy intercepts
    the .list.get(n) pattern (used by json_extract queries) and translates it
    to split_part(expr, separator, n+1).
    """

    def __init__(self, expr: DataFusionExpr, separator: str) -> None:
        self._expr = expr
        self._separator = separator

    @property
    def list(self) -> _DataFusionSplitListExpr:
        return self

    def get(self, index: int | DataFusionExpr) -> UnifiedExpr:
        from datafusion import functions as df_f, lit as df_lit

        # split_part is 1-indexed
        idx = index + 1 if isinstance(index, int) else index
        return UnifiedExpr(df_f.split_part(self._expr, df_lit(self._separator), df_lit(idx)))


class UnifiedListExpr:
    """Platform-agnostic list/array expression namespace.

    Provides Polars-style .list accessor methods that work across platforms:
    - Polars: Uses native .list.contains(), .list.len(), etc.
    - PySpark: Uses F.array_contains(), F.size(), etc.
    - DataFusion: Uses f.array_contains(), f.array_length(), etc.

    Also callable for list aggregation: col("x").list() collects values into a list.
    """

    def __init__(
        self,
        expr: Any,
        *,
        is_pyspark: bool = False,
        is_datafusion: bool = False,
        is_polars: bool = False,
    ) -> None:
        self._expr = expr
        self._is_pyspark = is_pyspark or _is_pyspark_column(expr)
        self._is_datafusion = is_datafusion or _is_datafusion_expr(expr)
        self._is_polars = is_polars or _is_polars_expr(expr)

    def __call__(self) -> UnifiedExpr:
        """List aggregation - collect values into a list.

        Used in .agg() context: col("x").list() -> collect into list.
        - Polars: .implode() (renamed from .list() in newer versions)
        - PySpark: F.collect_list()
        - DataFusion: f.array_agg()
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.collect_list(self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f

            return UnifiedExpr(df_f.array_agg(self._expr))
        # Polars: .implode() collects into a list in agg context
        return UnifiedExpr(self._expr.implode())

    def _wrap(self, expr: Any) -> UnifiedListExpr:
        return UnifiedListExpr(
            expr,
            is_pyspark=self._is_pyspark,
            is_datafusion=self._is_datafusion,
            is_polars=self._is_polars,
        )

    def contains(self, value: Any) -> UnifiedExpr:
        """Check if list contains a value.

        Args:
            value: Value to search for (may be UnifiedExpr)
        """
        val = value._expr if isinstance(value, UnifiedExpr) else value
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.array_contains(self._expr, val))
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            lit_val = df_lit(val) if not _is_datafusion_expr(val) else val
            return UnifiedExpr(df_f.array_has(self._expr, lit_val))
        return UnifiedExpr(self._expr.list.contains(val))

    def unique(self) -> UnifiedListExpr:
        """Get distinct elements from list.

        Returns:
            UnifiedListExpr with unique elements
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return self._wrap(F.array_distinct(self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f

            return self._wrap(df_f.array_distinct(self._expr))
        return self._wrap(self._expr.list.unique())

    def len(self) -> UnifiedExpr:
        """Get list length.

        Returns:
            UnifiedExpr with integer length
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.size(self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f

            return UnifiedExpr(df_f.array_length(self._expr))
        return UnifiedExpr(self._expr.list.len())

    def min(self) -> UnifiedExpr:
        """Get minimum value from list."""
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.array_min(self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            # array_min not in v50 Python bindings; use array_sort + array_element(1)
            return UnifiedExpr(df_f.array_element(df_f.array_sort(self._expr), df_lit(1)))
        return UnifiedExpr(self._expr.list.min())

    def max(self) -> UnifiedExpr:
        """Get maximum value from list."""
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.array_max(self._expr))
        if self._is_datafusion:
            import pyarrow as pa
            from datafusion import functions as df_f

            # array_max not in v50 Python bindings; use array_sort + last element
            # array_length returns UInt64, but array_element requires Int64 index
            return UnifiedExpr(
                df_f.array_element(df_f.array_sort(self._expr), df_f.array_length(self._expr).cast(pa.int64()))
            )
        return UnifiedExpr(self._expr.list.max())

    def sort(self, descending: bool = False) -> UnifiedListExpr:
        """Sort list elements.

        Args:
            descending: Sort in descending order

        Returns:
            UnifiedListExpr with sorted elements
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return self._wrap(F.sort_array(self._expr, asc=not descending))
        if self._is_datafusion:
            from datafusion import functions as df_f

            return self._wrap(df_f.array_sort(self._expr))
        return self._wrap(self._expr.list.sort(descending=descending))

    def slice(self, offset: int, length: int) -> UnifiedListExpr:
        """Get a slice of the list.

        Args:
            offset: Start index (0-based)
            length: Number of elements

        Returns:
            UnifiedListExpr with sliced elements
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            # PySpark slice is 1-indexed
            return self._wrap(F.slice(self._expr, offset + 1, length))
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            # DataFusion array_slice is 1-indexed
            return self._wrap(df_f.array_slice(self._expr, df_lit(offset + 1), df_lit(length)))
        return self._wrap(self._expr.list.slice(offset, length))

    def sum(self) -> UnifiedExpr:
        """Sum all elements in the list."""
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            # PySpark: use aggregate() to sum array elements
            return UnifiedExpr(F.aggregate(self._expr, F.lit(0.0).cast("double"), lambda acc, x: acc + x))
        if self._is_datafusion:
            from datafusion import functions as df_f

            return UnifiedExpr(df_f.array_sum(self._expr))
        return UnifiedExpr(self._expr.list.sum())

    def get(self, index: int | Any) -> UnifiedExpr:
        """Get element at index from list.

        Args:
            index: Element index (0-based)
        """
        if self._is_pyspark:
            return UnifiedExpr(self._expr.getItem(index))
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            # DataFusion array_element is 1-indexed
            idx = index + 1 if isinstance(index, int) else index
            return UnifiedExpr(df_f.array_element(self._expr, df_lit(idx)))
        return UnifiedExpr(self._expr.list.get(index))

    def eval(self, expr: Any) -> UnifiedListExpr:
        """Evaluate an expression on each list element (Polars-only).

        This is a Polars-native operation that evaluates an expression context
        within each list. PySpark and DataFusion don't have a direct equivalent.

        Args:
            expr: Polars expression using pl.element() (via ctx.element())

        Returns:
            UnifiedListExpr with transformed list
        """
        native_expr = expr._expr if isinstance(expr, UnifiedExpr) else expr
        if self._is_polars:
            return self._wrap(self._expr.list.eval(native_expr))
        raise NotImplementedError("list.eval() is only supported on Polars")

    @property
    def list(self) -> UnifiedListExpr:
        """Return self for chaining (e.g., .str.split(" ").list.get(0)).

        Since UnifiedListExpr already IS the list namespace, this property
        enables the Polars-style .list accessor on list-typed expressions.
        """
        return self

    def alias(self, name: str) -> UnifiedExpr:
        """Alias the list expression.

        Args:
            name: New column name
        """
        return UnifiedExpr(self._expr.alias(name))


class UnifiedMapExpr:
    """Platform-agnostic map expression namespace.

    Provides map accessor methods across platforms.
    Note: Polars doesn't have a native Map dtype, so map operations
    are only supported on PySpark and DataFusion.
    """

    def __init__(self, expr: Any, is_pyspark: bool, is_datafusion: bool) -> None:
        self._expr = expr
        self._is_pyspark = is_pyspark
        self._is_datafusion = is_datafusion

    def get(self, key: Any) -> UnifiedExpr:
        """Get value from map by key.

        Args:
            key: Map key (may be UnifiedExpr)
        """
        key_val = key._expr if isinstance(key, UnifiedExpr) else key
        if self._is_pyspark:
            return UnifiedExpr(self._expr.getItem(key_val))
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            lit_key = df_lit(key_val) if not _is_datafusion_expr(key_val) else key_val
            return UnifiedExpr(df_f.map_extract(self._expr, lit_key))
        raise NotImplementedError("Map operations not supported on Polars (no native Map dtype)")

    def keys(self) -> UnifiedExpr:
        """Get all keys from map."""
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.map_keys(self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f

            return UnifiedExpr(df_f.map_keys(self._expr))
        raise NotImplementedError("Map operations not supported on Polars (no native Map dtype)")

    def values(self) -> UnifiedExpr:
        """Get all values from map."""
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.map_values(self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f

            return UnifiedExpr(df_f.map_values(self._expr))
        raise NotImplementedError("Map operations not supported on Polars (no native Map dtype)")


class UnifiedDtExpr:
    """Platform-agnostic datetime expression namespace.

    Provides Polars-style .dt accessor methods that work across platforms:
    - Polars: Uses native .dt.year(), etc.
    - PySpark: Uses F.year(), F.month(), etc.
    - DataFusion: Uses functions.date_part(), etc.
    """

    def __init__(self, expr: Any, is_pyspark: bool, is_datafusion: bool = False) -> None:
        """Initialize the datetime expression wrapper.

        Args:
            expr: Native expression (PySpark Column, Polars Expr, or DataFusion Expr)
            is_pyspark: Whether the expression is a PySpark Column
            is_datafusion: Whether the expression is a DataFusion Expr
        """
        self._expr = expr
        self._is_pyspark = is_pyspark
        self._is_datafusion = is_datafusion

    def _extract_date_part(self, part: str, pyspark_fn_name: str | None = None) -> UnifiedExpr:
        """Multi-platform date-part extraction.

        Args:
            part: Date part name (year, month, day, hour, minute).
            pyspark_fn_name: PySpark function name override (e.g. ``"dayofmonth"``
                instead of ``"day"``).  Defaults to *part*.
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(getattr(F, pyspark_fn_name or part)(self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            return UnifiedExpr(df_f.date_part(df_lit(part), self._expr))
        return UnifiedExpr(getattr(self._expr.dt, part)())

    def year(self) -> UnifiedExpr:
        """Extract year from date/datetime."""
        return self._extract_date_part("year")

    def month(self) -> UnifiedExpr:
        """Extract month from date/datetime."""
        return self._extract_date_part("month")

    def day(self) -> UnifiedExpr:
        """Extract day from date/datetime."""
        return self._extract_date_part("day", pyspark_fn_name="dayofmonth")

    def hour(self) -> UnifiedExpr:
        """Extract hour from datetime."""
        return self._extract_date_part("hour")

    def minute(self) -> UnifiedExpr:
        """Extract minute from datetime."""
        return self._extract_date_part("minute")

    def weekday(self) -> UnifiedExpr:
        """Extract weekday from datetime.

        Returns:
            UnifiedExpr with weekday as integer (0=Monday .. 6=Sunday, ISO 8601)
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            # PySpark dayofweek: 1=Sunday..7=Saturday; convert to ISO
            return UnifiedExpr((F.dayofweek(self._expr) + 5) % 7)
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            # DataFusion dow: 0=Sunday..6=Saturday; convert to ISO
            return UnifiedExpr((df_f.date_part(df_lit("dow"), self._expr) + 6) % 7)
        return UnifiedExpr(self._expr.dt.weekday())

    def truncate(self, every: str) -> UnifiedExpr:
        """Truncate datetime to given interval.

        Args:
            every: Interval string (e.g., "1m" for 1 minute, "1h" for 1 hour, "1d" for 1 day)

        Returns:
            UnifiedExpr with truncated datetime
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            # Map Polars interval syntax to PySpark date_trunc format
            fmt_map = {"1m": "minute", "1h": "hour", "1d": "day", "1w": "week", "1mo": "month", "1y": "year"}
            fmt = fmt_map.get(every, every)
            return UnifiedExpr(F.date_trunc(fmt, self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            fmt_map = {"1m": "minute", "1h": "hour", "1d": "day", "1w": "week", "1mo": "month", "1y": "year"}
            fmt = fmt_map.get(every, every)
            return UnifiedExpr(df_f.date_trunc(df_lit(fmt), self._expr))
        return UnifiedExpr(self._expr.dt.truncate(every))

    def total_seconds(self) -> UnifiedExpr:
        """Get total seconds from a duration/timedelta expression.

        Returns:
            UnifiedExpr with total seconds as float
        """
        if self._is_pyspark:
            # PySpark durations: cast to long (seconds)
            return UnifiedExpr(self._expr.cast("long"))
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            return UnifiedExpr(df_f.extract(df_lit("epoch"), self._expr))
        return UnifiedExpr(self._expr.dt.total_seconds())

    def total_days(self) -> UnifiedExpr:
        """Get total days from a duration/timedelta expression.

        Returns:
            UnifiedExpr with total days as integer
        """
        if self._is_pyspark:
            # PySpark durations: cast to long (seconds) then divide by 86400
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr((self._expr.cast("long") / F.lit(86400)).cast("long"))
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            # Extract epoch seconds and divide by 86400
            return UnifiedExpr(df_f.extract(df_lit("epoch"), self._expr) / df_lit(86400))
        return UnifiedExpr(self._expr.dt.total_days())


class UnifiedStructExpr:
    """Platform-agnostic struct field accessor.

    Provides .struct.field(name) access pattern across platforms.
    """

    def __init__(self, expr: Any, is_pyspark: bool = False, is_datafusion: bool = False) -> None:
        self._expr = expr
        self._is_pyspark = is_pyspark
        self._is_datafusion = is_datafusion

    def field(self, name: str) -> UnifiedExpr:
        """Access a named field from a struct column."""
        if self._is_pyspark:
            return UnifiedExpr(self._expr.getField(name))
        if self._is_datafusion:
            return UnifiedExpr(self._expr[name])
        return UnifiedExpr(self._expr.struct.field(name))


class UnifiedExpr:
    """Platform-agnostic expression wrapper.

    Wraps PySpark Columns and DataFusion Exprs to add Polars-compatible methods like
    .sum(), .mean(), .count(), etc.

    For Polars expressions, this is a pass-through.

    Why so many `Any` parameters in this class:
      Most methods accept "a value the backend would accept here" - that
      means a scalar literal (int / float / str / bool / bytes / date /
      None), another `UnifiedExpr`, a column-name string, or a backend-
      native expression object. The honest type union spans all of those
      and forces optional-dep imports (polars/pyspark/datafusion) at
      type-check time without giving callers a useful narrowing surface.
      Per-method `Any` documents the "we accept whatever the backend
      operator/function accepts" contract; the implementation guards
      runtime branches via isinstance / getattr.
    """

    def __init__(
        self,
        expr: Any,
        *,
        _is_string_literal: bool = False,
        _literal_value: Any = _NO_LITERAL_VALUE,
    ) -> None:
        """Initialize the expression wrapper.

        Args:
            expr: Native expression (PySpark Column, Polars Expr, or DataFusion Expr)
            _is_string_literal: Internal flag indicating this is a string literal
                               (used for PySpark string concatenation detection)
            _literal_value: Optional scalar value behind a backend literal expression.

        `expr: Any` is the same escape-hatch documented on `.native`: the
        honest type is the union of every backend's expression class plus
        scalar literals, but enforcing it forces optional-dep imports at
        type-check time without giving callers a useful common surface.
        Each `Unified*Expr` subclass init below shares this rationale.
        """
        self._expr = expr
        self._is_pyspark = _is_pyspark_column(expr)
        self._is_datafusion = _is_datafusion_expr(expr)
        self._is_string_literal = _is_string_literal
        self._literal_value = _literal_value

    @property
    def native(self) -> Any:
        """Get the underlying native expression.

        Returns the wrapped backend-native expression object, which can be
        a polars.Expr, pyspark.sql.Column, datafusion.Expr, or any other
        per-backend expression type. Caller is expected to know the backend
        before consuming this - narrowing here would force a union over
        every backend's expression class, none of which we want as a hard
        import. Escape-hatch `Any` is intentional.
        """
        return self._expr

    def __repr__(self) -> str:
        return f"UnifiedExpr({self._expr})"

    @staticmethod
    def _unwrap(other: Any) -> Any:
        return other._expr if isinstance(other, UnifiedExpr) else other

    # =========================================================================
    # Arithmetic Operations
    # =========================================================================
    # Why `other: Any` on every dunder: the right-hand operand can be a
    # Python scalar (int/float/str/bool), another UnifiedExpr, a column-name
    # string, or a backend-native expression object passed by user code.
    # `int | float | str | bool | UnifiedExpr | <backend-native>` is the
    # honest type, but the backend-native arm pulls in optional dependencies
    # and the union becomes load-bearing for type checkers without adding
    # call-site safety. `Any` documents the "we accept whatever the backend
    # arithmetic accepts" contract; the implementation guards the runtime
    # branches via isinstance / getattr.

    def __add__(self, other: Any) -> UnifiedExpr:
        """Add operator - handles both numeric addition and string concatenation.

        For PySpark and DataFusion, string concatenation must use concat(), not + operator.
        We detect string operations when either operand is a string literal or
        was created from a string value.
        """
        other_expr = other._expr if isinstance(other, UnifiedExpr) else other

        # Check if this is string concatenation
        # - self is a string literal (e.g., lit("store"))
        # - other is a Python string
        # - other is a UnifiedExpr created from a string literal
        self_is_string = getattr(self, "_is_string_literal", False)
        other_is_string = isinstance(other, str) or (
            isinstance(other, UnifiedExpr) and getattr(other, "_is_string_literal", False)
        )
        is_string_concat = self_is_string or other_is_string

        if self._is_pyspark and is_string_concat:
            # Use F.concat for PySpark string concatenation
            from pyspark.sql import functions as F  # noqa: N812

            if isinstance(other, str):
                # Result is still a string, so preserve the flag for chained concatenation
                return UnifiedExpr(F.concat(self._expr, F.lit(other)), _is_string_literal=True)
            # Result is still a string, so preserve the flag for chained concatenation
            return UnifiedExpr(F.concat(self._expr, other_expr), _is_string_literal=True)

        if self._is_datafusion and is_string_concat:
            # DataFusion doesn't support + for string concatenation, use concat()
            from datafusion import functions as df_f, lit as df_lit

            if isinstance(other, str):
                return UnifiedExpr(df_f.concat(self._expr, df_lit(other)), _is_string_literal=True)
            return UnifiedExpr(df_f.concat(self._expr, other_expr), _is_string_literal=True)

        return UnifiedExpr(self._expr + other_expr)

    def concat_str(self, *others: Any) -> UnifiedExpr:
        """Concatenate strings across platforms.

        For string concatenation, always use this method to ensure
        correct behavior across PySpark and Polars.

        Args:
            *others: Values to concatenate (strings, expressions, or UnifiedExpr)

        Returns:
            UnifiedExpr with concatenated string
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            # Build list of expressions for concat
            exprs = [self._expr]
            for o in others:
                if isinstance(o, str):
                    exprs.append(F.lit(o))
                elif isinstance(o, UnifiedExpr):
                    exprs.append(o._expr)
                else:
                    exprs.append(o)
            return UnifiedExpr(F.concat(*exprs))

        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            exprs = [self._expr]
            for o in others:
                if isinstance(o, str):
                    exprs.append(df_lit(o))
                elif isinstance(o, UnifiedExpr):
                    exprs.append(o._expr)
                else:
                    exprs.append(o)
            return UnifiedExpr(df_f.concat(*exprs), _is_string_literal=True)

        # Polars uses + for string concat
        import polars as pl

        result = self._expr
        for o in others:
            if isinstance(o, str):
                result = result + pl.lit(o)
            elif isinstance(o, UnifiedExpr):
                result = result + o._expr
            else:
                result = result + o
        return UnifiedExpr(result)

    def __radd__(self, other: Any) -> UnifiedExpr:
        """Reverse add - handles string literal + expression concatenation."""
        other_expr = other._expr if isinstance(other, UnifiedExpr) else other

        # Check if this is string concatenation (other is a string literal)
        if self._is_pyspark and isinstance(other, str):
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.concat(F.lit(other), self._expr))

        if self._is_datafusion and isinstance(other, str):
            from datafusion import functions as df_f, lit as df_lit

            return UnifiedExpr(df_f.concat(df_lit(other), self._expr), _is_string_literal=True)

        return UnifiedExpr(other_expr + self._expr)

    def __sub__(self, other: Any) -> UnifiedExpr:
        return UnifiedExpr(self._expr - self._unwrap(other))

    def __rsub__(self, other: Any) -> UnifiedExpr:
        return UnifiedExpr(self._unwrap(other) - self._expr)

    def __mul__(self, other: Any) -> UnifiedExpr:
        return UnifiedExpr(self._expr * self._unwrap(other))

    def __rmul__(self, other: Any) -> UnifiedExpr:
        return UnifiedExpr(self._unwrap(other) * self._expr)

    def __truediv__(self, other: Any) -> UnifiedExpr:
        other_expr = self._unwrap(other)
        # DataFusion: use nullif to prevent DivideByZero errors
        # dividend / nullif(divisor, 0) returns NULL when divisor is 0
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            if isinstance(other_expr, (int, float)):
                # Literal divisor - no need for nullif if non-zero
                if other_expr == 0:
                    return UnifiedExpr(self._expr / df_f.nullif(df_lit(other_expr), df_lit(0)))
                return UnifiedExpr(self._expr / other_expr)
            # Column divisor - wrap in nullif for safety
            return UnifiedExpr(self._expr / df_f.nullif(other_expr, df_lit(0)))
        return UnifiedExpr(self._expr / other_expr)

    def __rtruediv__(self, other: Any) -> UnifiedExpr:
        other_expr = self._unwrap(other)
        # DataFusion: use nullif to prevent DivideByZero errors
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            # self._expr is the divisor here
            return UnifiedExpr(other_expr / df_f.nullif(self._expr, df_lit(0)))
        return UnifiedExpr(other_expr / self._expr)

    # =========================================================================
    # Comparison Operations
    # =========================================================================

    def __eq__(self, other: Any) -> UnifiedExpr:  # type: ignore[override]
        other_expr = other._expr if isinstance(other, UnifiedExpr) else other
        result = UnifiedExpr(self._expr == other_expr)
        # Store operands for join equality decomposition:
        # table.join(other, col("a") == col("b")) needs to be split into left_on/right_on
        result._eq_left = self
        result._eq_right = other if isinstance(other, UnifiedExpr) else UnifiedExpr(other_expr)
        return result

    def __ne__(self, other: Any) -> UnifiedExpr:  # type: ignore[override]
        return UnifiedExpr(self._expr != self._unwrap(other))

    def __lt__(self, other: Any) -> UnifiedExpr:
        return UnifiedExpr(self._expr < self._unwrap(other))

    def __le__(self, other: Any) -> UnifiedExpr:
        return UnifiedExpr(self._expr <= self._unwrap(other))

    def __gt__(self, other: Any) -> UnifiedExpr:
        return UnifiedExpr(self._expr > self._unwrap(other))

    def __ge__(self, other: Any) -> UnifiedExpr:
        return UnifiedExpr(self._expr >= self._unwrap(other))

    def __and__(self, other: Any) -> UnifiedExpr:
        """Logical/bitwise AND operator.

        In PySpark, & is logical AND for boolean columns only.
        For integer columns (like grouping_id), we use SQL expr for bitwise AND.

        In DataFusion, & is only for boolean logical AND, not bitwise operations.
        For integer columns with power-of-2 masks, we use modulo arithmetic.
        """
        other_expr = self._unwrap(other)

        if self._is_pyspark and isinstance(other, int):
            # PySpark's & operator only works for boolean columns, not integers
            # For integer columns (like grouping_id), use bitwiseAND method
            # This handles cases like col("grouping_id") & 1
            col_expr = self._expr
            return UnifiedExpr((col_expr.cast("bigint").bitwiseAND(other)).cast("int"))

        if self._is_datafusion and isinstance(other, int):
            # DataFusion's & operator only works for boolean logical AND, not bitwise
            # For integer bitwise AND with power-of-2 masks, use modulo arithmetic:
            # x & n (where n is power of 2) = ((x // n) % 2) * n
            # For n=1: x & 1 = x % 2
            # For n=2: x & 2 = ((x // 2) % 2) * 2
            import pyarrow as pa
            from datafusion import lit as df_lit

            n = other
            if n == 1:
                # Special case: x & 1 = x % 2
                return UnifiedExpr(self._expr % df_lit(2))
            elif n > 0 and (n & (n - 1)) == 0:
                # n is a power of 2: x & n = ((x // n) % 2) * n
                # Use floor division via cast to int64
                div_expr = (self._expr / df_lit(n)).cast(pa.int64())
                return UnifiedExpr((div_expr % df_lit(2)) * df_lit(n))
            else:
                # For non-power-of-2, fall through to default (will likely error)
                pass

        return UnifiedExpr(self._expr & other_expr)

    def __or__(self, other: Any) -> UnifiedExpr:
        return UnifiedExpr(self._expr | self._unwrap(other))

    def __invert__(self) -> UnifiedExpr:
        return UnifiedExpr(~self._expr)

    # =========================================================================
    # Aggregation Methods (Polars-style API)
    # =========================================================================

    def _apply_aggregation(self, pyspark_name: str, datafusion_name: str, polars_name: str) -> UnifiedExpr:
        """Multi-platform aggregation dispatch.

        Args:
            pyspark_name: PySpark ``functions.{name}`` attribute.
            datafusion_name: DataFusion ``functions.{name}`` attribute.
            polars_name: Polars expression method name.
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(getattr(F, pyspark_name)(self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f

            return UnifiedExpr(getattr(df_f, datafusion_name)(self._expr))
        return UnifiedExpr(getattr(self._expr, polars_name)())

    def sum(self) -> UnifiedExpr:
        """Sum aggregation."""
        return self._apply_aggregation("sum", "sum", "sum")

    def mean(self) -> UnifiedExpr:
        """Mean/average aggregation."""
        return self._apply_aggregation("avg", "avg", "mean")

    def avg(self) -> UnifiedExpr:
        """Average aggregation (alias for mean)."""
        return self.mean()

    def count(self) -> UnifiedExpr:
        """Count aggregation."""
        return self._apply_aggregation("count", "count", "count")

    def min(self) -> UnifiedExpr:
        """Minimum aggregation."""
        return self._apply_aggregation("min", "min", "min")

    def max(self) -> UnifiedExpr:
        """Maximum aggregation."""
        return self._apply_aggregation("max", "max", "max")

    def first(self) -> UnifiedExpr:
        """First value aggregation."""
        return self._apply_aggregation("first", "first_value", "first")

    def last(self) -> UnifiedExpr:
        """Last value aggregation."""
        return self._apply_aggregation("last", "last_value", "last")

    def std(self) -> UnifiedExpr:
        """Standard deviation aggregation."""
        return self._apply_aggregation("stddev", "stddev", "std")

    def var(self) -> UnifiedExpr:
        """Variance aggregation."""
        return self._apply_aggregation("variance", "var_samp", "var")

    def quantile(self, q: float) -> UnifiedExpr:
        """Quantile/percentile aggregation.

        Args:
            q: Quantile value between 0 and 1 (e.g., 0.5 for median, 0.9 for p90)

        Returns:
            UnifiedExpr with the quantile value
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.percentile_approx(self._expr, q))
        if self._is_datafusion:
            from datafusion import functions as df_f

            return UnifiedExpr(df_f.approx_percentile_cont(self._expr, q))
        return UnifiedExpr(self._expr.quantile(q))

    # =========================================================================
    # Naming Methods
    # =========================================================================

    def alias(self, name: str) -> UnifiedExpr:
        """Rename the expression/column."""
        return UnifiedExpr(self._expr.alias(name))

    # =========================================================================
    # Cast Methods
    # =========================================================================

    def cast(self, dtype: Any) -> UnifiedExpr:
        """Cast to a different data type.

        Provides unified casting:
        - Polars: Accepts Polars types (pl.Int64, pl.Utf8, etc.)
        - PySpark: Accepts PySpark types (IntegerType(), StringType(), etc.)
        - DataFusion: Accepts PyArrow types (pa.int64(), pa.utf8(), etc.)

        Args:
            dtype: The target data type (platform-specific or common type name)

        Returns:
            UnifiedExpr with casted values
        """
        if self._is_datafusion:
            import pyarrow as pa

            # If dtype is already a PyArrow type, use it directly
            if isinstance(dtype, pa.DataType):
                return UnifiedExpr(self._expr.cast(dtype))

            # Convert Polars types to PyArrow types using cached mapping
            dtype_str = str(dtype).lower()
            type_mapping = _get_datafusion_type_mapping()
            if dtype_str in type_mapping:
                return UnifiedExpr(self._expr.cast(type_mapping[dtype_str]))

            # Try passing dtype directly (may work if it's a compatible type)
            return UnifiedExpr(self._expr.cast(dtype))

        return UnifiedExpr(self._expr.cast(dtype))

    def round(self, decimals: int = 0) -> UnifiedExpr:
        """Round to specified number of decimal places.

        Provides unified rounding:
        - Polars: Uses .round(decimals)
        - PySpark: Uses F.round(col, decimals)
        - DataFusion: Uses functions.round(col, decimals)

        Args:
            decimals: Number of decimal places (default 0)

        Returns:
            UnifiedExpr with rounded values
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.round(self._expr, decimals))
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            return UnifiedExpr(df_f.round(self._expr, df_lit(decimals)))
        return UnifiedExpr(self._expr.round(decimals))

    def floor(self) -> UnifiedExpr:
        """Compute floor (round down to nearest integer).

        Provides unified floor:
        - Polars: Uses .floor()
        - PySpark: Uses F.floor()
        - DataFusion: Uses functions.floor()

        Returns:
            UnifiedExpr with floor values
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.floor(self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f

            return UnifiedExpr(df_f.floor(self._expr))
        return UnifiedExpr(self._expr.floor())

    def abs(self) -> UnifiedExpr:
        """Compute absolute value.

        Provides unified absolute value:
        - Polars: Uses .abs()
        - PySpark: Uses F.abs()

        Returns:
            UnifiedExpr with absolute values
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.abs(self._expr))
        return UnifiedExpr(self._expr.abs())

    def cast_float(self) -> UnifiedExpr:
        """Alias for cast_float64()."""
        return self.cast_float64()

    def _apply_cast(self, target_type: str) -> UnifiedExpr:
        """Multi-platform casting helper for common numeric target types."""
        if self._is_pyspark:
            from pyspark.sql.types import DoubleType, IntegerType, LongType

            pyspark_types = {
                "float64": DoubleType,
                "int32": IntegerType,
                "int64": LongType,
            }
            return UnifiedExpr(self._expr.cast(pyspark_types[target_type]()))
        if self._is_datafusion:
            import pyarrow as pa

            datafusion_types = {
                "float64": pa.float64,
                "int32": pa.int32,
                "int64": pa.int64,
            }
            return UnifiedExpr(self._expr.cast(datafusion_types[target_type]()))

        import polars as pl

        polars_types = {
            "float64": pl.Float64,
            "int32": pl.Int32,
            "int64": pl.Int64,
        }
        return UnifiedExpr(self._expr.cast(polars_types[target_type]))

    def cast_float64(self) -> UnifiedExpr:
        """Cast to Float64/DoubleType.

        Provides unified float casting:
        - Polars: Uses .cast(pl.Float64)
        - PySpark: Uses .cast(DoubleType())
        - DataFusion: Uses .cast(pa.float64())

        Returns:
            UnifiedExpr with float values
        """
        return self._apply_cast("float64")

    def cast_string(self) -> UnifiedExpr:
        """Cast to String/Utf8 type.

        Provides unified string casting:
        - Polars: Uses .cast(pl.Utf8)
        - PySpark: Uses .cast(StringType())
        - DataFusion: Uses .cast(pa.utf8())

        Returns:
            UnifiedExpr with string values
        """
        if self._is_pyspark:
            from pyspark.sql.types import StringType

            return UnifiedExpr(self._expr.cast(StringType()))
        if self._is_datafusion:
            import pyarrow as pa

            return UnifiedExpr(self._expr.cast(pa.utf8()))

        import polars as pl

        return UnifiedExpr(self._expr.cast(pl.Utf8))

    def cast_int32(self) -> UnifiedExpr:
        """Cast to Int32/IntegerType.

        Provides unified integer casting:
        - Polars: Uses .cast(pl.Int32)
        - PySpark: Uses .cast(IntegerType())
        - DataFusion: Uses .cast(pa.int32())

        Returns:
            UnifiedExpr with integer values
        """
        return self._apply_cast("int32")

    def cast_int64(self) -> UnifiedExpr:
        """Cast to Int64/LongType.

        Provides unified 64-bit integer casting:
        - Polars: Uses .cast(pl.Int64)
        - PySpark: Uses .cast(LongType())
        - DataFusion: Uses .cast(pa.int64())

        Returns:
            UnifiedExpr with 64-bit integer values
        """
        return self._apply_cast("int64")

    def cast_int(self) -> UnifiedExpr:
        """Cast to integer (alias for cast_int32)."""
        return self.cast_int32()

    # =========================================================================
    # Membership Testing
    # =========================================================================

    def is_in(self, values: list) -> UnifiedExpr:
        """Check if value is in a list of values.

        Provides unified membership testing:
        - Polars: Uses .is_in()
        - PySpark: Uses .isin()
        - DataFusion: Uses functions.in_list()

        Args:
            values: List of values to check against

        Returns:
            UnifiedExpr with boolean result
        """
        if self._is_pyspark:
            return UnifiedExpr(self._expr.isin(values))
        if self._is_datafusion:
            from datafusion import functions as df_f, lit as df_lit

            lit_values = [df_lit(v) for v in values]
            return UnifiedExpr(df_f.in_list(self._expr, lit_values, negated=False))
        return UnifiedExpr(self._expr.is_in(values))

    # =========================================================================
    # Count Distinct
    # =========================================================================

    def n_unique(self) -> UnifiedExpr:
        """Count distinct values.

        Provides unified count distinct:
        - Polars: Uses .n_unique()
        - PySpark: Uses F.countDistinct()
        - DataFusion: Uses functions.count_distinct()

        Returns:
            UnifiedExpr with count of distinct values
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.countDistinct(self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f

            return UnifiedExpr(df_f.count(self._expr, distinct=True))
        return UnifiedExpr(self._expr.n_unique())

    def approx_n_unique(self) -> UnifiedExpr:
        """Approximate count distinct (HLL sketch).

        Provides unified sketch-backed distinct count:
        - Polars: Uses .approx_n_unique() (HLL).
        - PySpark: Uses F.approx_count_distinct() (HLL).
        - DataFusion: Uses functions.approx_distinct() (HLL).

        Returns:
            UnifiedExpr with the HLL-estimated count of distinct values.
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.approx_count_distinct(self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f

            return UnifiedExpr(df_f.approx_distinct(self._expr))
        return UnifiedExpr(self._expr.approx_n_unique())

    # =========================================================================
    # Conditional Aggregation
    # =========================================================================

    def filter(self, condition: Any) -> UnifiedExpr:
        """Filter expression for conditional aggregation.

        Provides unified conditional aggregation:
        - Polars: Uses .filter() on expressions (e.g., col.filter(cond).sum())
        - PySpark: Uses F.when(cond, col) to mask values
        - DataFusion: Returns _DataFusionDeferredFilter for later application

        This enables patterns like:
            col("revenue").filter(col("type") == "A").sum()

        For PySpark, this creates a CASE WHEN expression that returns the value
        when the condition is true and NULL otherwise. When aggregated, NULLs
        are ignored, achieving the same effect as Polars' filter.

        For DataFusion, the filter must be applied AFTER the aggregate function,
        so we return a deferred wrapper that applies the filter when sum/count/etc.
        is called.

        Args:
            condition: Boolean expression for filtering (may be UnifiedExpr)

        Returns:
            UnifiedExpr with filtered/masked values (or deferred wrapper for DataFusion)
        """
        # Unwrap UnifiedExpr condition for both platforms
        cond = condition.native if isinstance(condition, UnifiedExpr) else condition
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            # Create CASE WHEN cond THEN value ELSE NULL END
            # This allows aggregations to ignore non-matching rows
            return UnifiedExpr(F.when(cond, self._expr))
        if self._is_datafusion:
            # DataFusion: filter is applied after aggregate, not before
            # Return a deferred wrapper that will apply filter when aggregate is called
            return _DataFusionDeferredFilter(self._expr, cond)
        # Polars uses .filter() on expressions directly
        return UnifiedExpr(self._expr.filter(cond))

    # =========================================================================
    # Null Handling Methods
    # =========================================================================

    def is_null(self) -> UnifiedExpr:
        """Check if value is null.

        Provides unified null checking:
        - Polars: Uses .is_null()
        - PySpark: Uses .isNull()

        Returns:
            UnifiedExpr with boolean result
        """
        if self._is_pyspark:
            return UnifiedExpr(self._expr.isNull())
        return UnifiedExpr(self._expr.is_null())

    def is_not_null(self) -> UnifiedExpr:
        """Check if value is not null.

        Provides unified not-null checking:
        - Polars: Uses .is_not_null()
        - PySpark: Uses .isNotNull()

        Returns:
            UnifiedExpr with boolean result
        """
        if self._is_pyspark:
            return UnifiedExpr(self._expr.isNotNull())
        return UnifiedExpr(self._expr.is_not_null())

    def fill_null(self, value: Any) -> UnifiedExpr:
        """Replace null values with a default value.

        Provides unified null filling:
        - Polars: Uses .fill_null(value)
        - PySpark: Uses F.coalesce(col, lit(value))

        Args:
            value: The value to use as replacement for nulls

        Returns:
            UnifiedExpr with nulls replaced
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            # Handle UnifiedExpr values
            fill_value = value._expr if isinstance(value, UnifiedExpr) else F.lit(value)
            return UnifiedExpr(F.coalesce(self._expr, fill_value))
        # For Polars, unwrap UnifiedExpr values
        fill_value = value._expr if isinstance(value, UnifiedExpr) else value
        return UnifiedExpr(self._expr.fill_null(fill_value))

    # =========================================================================
    # Range Checking Methods
    # =========================================================================

    def is_between(self, low: Any, high: Any) -> UnifiedExpr:
        """Check if value is between low and high (inclusive).

        Provides unified range checking:
        - Polars: Uses .is_between(low, high)
        - PySpark: Uses .between(low, high)
        - DataFusion: Uses (expr >= low) & (expr <= high)

        Args:
            low: Lower bound (inclusive)
            high: Upper bound (inclusive)

        Returns:
            UnifiedExpr with boolean result
        """
        # Unwrap UnifiedExpr bounds if needed
        low_val = low._expr if isinstance(low, UnifiedExpr) else low
        high_val = high._expr if isinstance(high, UnifiedExpr) else high

        if self._is_pyspark:
            return UnifiedExpr(self._expr.between(low_val, high_val))
        if self._is_datafusion:
            # DataFusion doesn't have is_between, use comparison operators
            from datafusion import lit as df_lit

            # Convert Python values to DataFusion literals if needed
            if not _is_datafusion_expr(low_val):
                low_val = df_lit(low_val)
            if not _is_datafusion_expr(high_val):
                high_val = df_lit(high_val)
            return UnifiedExpr((self._expr >= low_val) & (self._expr <= high_val))
        return UnifiedExpr(self._expr.is_between(low_val, high_val))

    # =========================================================================
    # Window Function Methods
    # =========================================================================

    def rank(self, method: str = "min", descending: bool = False) -> UnifiedExpr:
        """Compute rank within partition.

        Provides unified ranking:
        - Polars: Uses .rank(method=method, descending=descending)
        - PySpark: Requires Window specification - returns a deferred rank expression
        - DataFusion: Requires Window specification - returns a deferred rank expression

        Note: For PySpark/DataFusion, this returns a deferred expression. The actual ranking
        requires calling .over() with a window specification.

        Args:
            method: Ranking method: "min", "max", "dense", "ordinal", "average"
            descending: Whether to rank in descending order

        Returns:
            UnifiedExpr with rank values (Polars) or deferred for window (PySpark/DataFusion)
        """
        if self._is_pyspark:
            # For PySpark, we need to store the rank parameters for later use with over()
            # Return a wrapper that tracks the ranking need
            # The actual rank will be computed when over() is called
            return _PySparkDeferredRank(self._expr, method, descending)
        if self._is_datafusion:
            # For DataFusion, we also need deferred ranking with over()
            return _DataFusionDeferredRank(self._expr, method, descending)
        return UnifiedExpr(self._expr.rank(method=method, descending=descending))

    def over(
        self,
        partition_by: str | list[str],
        order_by: str | None = None,
    ) -> UnifiedExpr:
        """Apply expression over a window partition.

        Provides unified window partitioning:
        - Polars: Uses .over(partition_by)
        - PySpark: Uses .over(Window.partitionBy(...).orderBy(...))
        - DataFusion: Uses expr.over(Window(partition_by=[...], order_by=[...]))

        Args:
            partition_by: Column(s) to partition by
            order_by: Optional column to order by within partition

        Returns:
            UnifiedExpr with windowed result
        """
        # Normalize partition_by to list
        partition_cols = [partition_by] if isinstance(partition_by, str) else list(partition_by)

        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812
            from pyspark.sql.window import Window

            # Build window specification
            window = Window.partitionBy(*[F.col(c) for c in partition_cols])
            if order_by:
                window = window.orderBy(F.col(order_by))

            return UnifiedExpr(self._expr.over(window))

        if self._is_datafusion:
            from datafusion import col as df_col
            from datafusion.expr import Window

            # Build DataFusion Window specification
            partition_exprs = [df_col(c) if isinstance(c, str) else c for c in partition_cols]

            if order_by:
                order_exprs = [df_col(order_by).sort(ascending=True)]
                window = Window(partition_by=partition_exprs, order_by=order_exprs)
            else:
                window = Window(partition_by=partition_exprs)

            return UnifiedExpr(self._expr.over(window))

        # Polars: simple over() call
        if order_by:
            # Polars over() with order_by requires a different approach
            # For now, just use partition_by (ordering within window is less common in Polars)
            return UnifiedExpr(self._expr.over(partition_cols))
        return UnifiedExpr(self._expr.over(partition_cols))

    def cum_sum(self) -> UnifiedExpr:
        """Compute cumulative sum.

        Provides unified cumulative sum:
        - Polars: Uses .cum_sum()
        - PySpark: Uses F.sum().over(Window.rowsBetween(...))
        - DataFusion: Uses functions.sum() with window (must be used with .over())

        Note: For PySpark and DataFusion, this returns the expression. Use with .over() for proper windowing.

        Returns:
            UnifiedExpr with cumulative sum values
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            # Return sum expression - caller should use with over()
            return UnifiedExpr(F.sum(self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f

            # Return sum expression - caller should use with over()
            return UnifiedExpr(df_f.sum(self._expr))
        return UnifiedExpr(self._expr.cum_sum())

    def cum_max(self) -> UnifiedExpr:
        """Compute cumulative maximum.

        Provides unified cumulative max:
        - Polars: Uses .cum_max()
        - PySpark: Uses F.max().over(Window.rowsBetween(...))
        - DataFusion: Uses functions.max() with window (must be used with .over())

        Note: For PySpark and DataFusion, this returns the expression. Use with .over() for proper windowing.

        Returns:
            UnifiedExpr with cumulative max values
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            # Return max expression - caller should use with over()
            return UnifiedExpr(F.max(self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f

            # Return max expression - caller should use with over()
            return UnifiedExpr(df_f.max(self._expr))
        return UnifiedExpr(self._expr.cum_max())

    def cum_min(self) -> UnifiedExpr:
        """Compute cumulative minimum.

        Provides unified cumulative min:
        - Polars: Uses .cum_min()
        - PySpark: Uses F.min().over(Window.rowsBetween(...))

        Note: For PySpark, this returns the expression. Use with .over() for proper windowing.

        Returns:
            UnifiedExpr with cumulative min values
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            # Return min expression - caller should use with over()
            return UnifiedExpr(F.min(self._expr))
        return UnifiedExpr(self._expr.cum_min())

    # =========================================================================
    # Aggregation-Context Expression Methods
    # =========================================================================

    def sort_by(self, column: str | Any, descending: bool = False) -> UnifiedExpr:
        """Sort expression values by another column (used in aggregation context).

        In Polars agg context: col("x").sort_by("y") sorts x by y within each group.
        In DataFusion: wraps in array_agg with order_by to produce ordered list.

        Args:
            column: Column name or expression to sort by
            descending: Sort in descending order
        """
        if self._is_datafusion:
            from datafusion import col as df_col, functions as df_f

            col_name = column._expr if isinstance(column, UnifiedExpr) else column
            if isinstance(col_name, str):
                order_expr = df_col(col_name).sort(ascending=not descending)
            else:
                order_expr = col_name.sort(ascending=not descending)
            return UnifiedExpr(df_f.array_agg(self._expr, order_by=[order_expr]))
        if self._is_pyspark:
            # PySpark: no direct equivalent in agg context, pass through
            return UnifiedExpr(self._expr)
        col_name = column._expr if isinstance(column, UnifiedExpr) else column
        return UnifiedExpr(self._expr.sort_by(col_name, descending=descending))

    def unique(self) -> UnifiedExpr:
        """Get unique values (used in aggregation context).

        In Polars agg context: col("x").unique() collects distinct values into a list.

        For PySpark this maps to collect_set() (aggregation).
        """
        if self._is_pyspark:
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.collect_set(self._expr))
        if self._is_datafusion:
            from datafusion import functions as df_f

            return UnifiedExpr(df_f.array_agg(self._expr, distinct=True))
        return UnifiedExpr(self._expr.unique())

    def sort(self, descending: bool = False) -> UnifiedExpr:
        """Sort expression values (used in aggregation context).

        In Polars agg context: col("x").sort() sorts collected values.

        Args:
            descending: Sort in descending order
        """
        if self._is_pyspark or self._is_datafusion:
            # PySpark/DataFusion: no direct agg-context sort, pass through
            return UnifiedExpr(self._expr)
        return UnifiedExpr(self._expr.sort(descending=descending))

    def desc(self) -> UnifiedExpr:
        """Mark expression for descending sort order.

        Returns a sort-marked expression that UnifiedLazyFrame.sort() can interpret.
        - Polars: Uses sort_by with descending=True
        - DataFusion: Uses expr.sort(ascending=False)
        """
        if self._is_datafusion:
            return UnifiedExpr(self._expr.sort(ascending=False, nulls_first=False))
        elif self._is_pyspark:
            return UnifiedExpr(self._expr.desc())
        # Polars: return expr with descending flag via sort_by
        return UnifiedExpr(self._expr.sort(descending=True))

    # =========================================================================
    # Namespace Accessors
    # =========================================================================

    @property
    def str(self) -> UnifiedStrExpr:
        """Access string methods.

        Returns:
            UnifiedStrExpr with string operations
        """
        return UnifiedStrExpr(self._expr, self._is_pyspark, self._is_datafusion)

    @property
    def dt(self) -> UnifiedDtExpr:
        """Access datetime methods.

        Returns:
            UnifiedDtExpr with datetime operations
        """
        return UnifiedDtExpr(self._expr, self._is_pyspark, self._is_datafusion)

    @property
    def list(self) -> UnifiedListExpr:
        """Access list/array methods.

        Returns:
            UnifiedListExpr with list operations
        """
        return UnifiedListExpr(
            self._expr,
            is_pyspark=self._is_pyspark,
            is_datafusion=self._is_datafusion,
            is_polars=not self._is_pyspark and not self._is_datafusion,
        )

    @property
    def map(self) -> UnifiedMapExpr:
        """Access map methods.

        Returns:
            UnifiedMapExpr with map operations
        """
        return UnifiedMapExpr(self._expr, self._is_pyspark, self._is_datafusion)

    @property
    def struct(self) -> UnifiedStructExpr:
        """Access struct field methods.

        Returns:
            UnifiedStructExpr with struct field operations
        """
        return UnifiedStructExpr(self._expr, self._is_pyspark, self._is_datafusion)


class _PySparkDeferredRank(UnifiedExpr):
    """Deferred rank expression for PySpark.

    PySpark requires a Window specification for ranking functions. This class
    captures the rank parameters and applies them when over() is called.
    """

    def __init__(self, expr: PySparkColumn, method: str, descending: bool) -> None:
        """Initialize the deferred rank.

        Args:
            expr: The column expression to rank by
            method: Ranking method: "min", "max", "dense", "ordinal", "average"
            descending: Whether to rank in descending order
        """
        super().__init__(expr)
        self._rank_method = method
        self._rank_descending = descending

    def over(
        self,
        partition_by: str | list[str],
        order_by: str | None = None,
    ) -> UnifiedExpr:
        """Apply ranking over a window partition.

        Args:
            partition_by: Column(s) to partition by
            order_by: Optional column to order by (ignored, uses self._expr)

        Returns:
            UnifiedExpr with rank values
        """
        from pyspark.sql import functions as F  # noqa: N812
        from pyspark.sql.window import Window

        # Normalize partition_by to list
        partition_cols = [partition_by] if isinstance(partition_by, str) else list(partition_by)

        # Build window specification with ordering
        window = Window.partitionBy(*[F.col(c) for c in partition_cols])

        # Add ordering based on the expression
        order_expr = self._expr.desc() if self._rank_descending else self._expr.asc()
        window = window.orderBy(order_expr)

        # Map Polars rank methods to PySpark rank functions
        if self._rank_method == "min":
            rank_expr = F.rank().over(window)
        elif self._rank_method == "dense":
            rank_expr = F.dense_rank().over(window)
        elif self._rank_method == "ordinal":
            rank_expr = F.row_number().over(window)
        elif self._rank_method == "average":
            # PySpark doesn't have average rank, use percent_rank * count
            # For simplicity, fall back to rank()
            rank_expr = F.rank().over(window)
        else:
            # Default to rank()
            rank_expr = F.rank().over(window)

        return UnifiedExpr(rank_expr)


class _DataFusionDeferredRank(UnifiedExpr):
    """Deferred rank expression for DataFusion.

    DataFusion requires a Window specification for ranking functions. This class
    captures the rank parameters and applies them when over() is called.
    """

    def __init__(self, expr: DataFusionExpr, method: str, descending: bool) -> None:
        """Initialize the deferred rank.

        Args:
            expr: The column expression to rank by
            method: Ranking method: "min", "max", "dense", "ordinal", "average"
            descending: Whether to rank in descending order
        """
        super().__init__(expr)
        self._rank_method = method
        self._rank_descending = descending

    def over(
        self,
        partition_by: str | list[str],
        order_by: str | None = None,
    ) -> UnifiedExpr:
        """Apply ranking over a window partition.

        Args:
            partition_by: Column(s) to partition by
            order_by: Optional column to order by (ignored, uses self._expr)

        Returns:
            UnifiedExpr with rank values
        """
        from datafusion import col as df_col, functions as df_f
        from datafusion.expr import Window

        # Normalize partition_by to list
        partition_cols = [partition_by] if isinstance(partition_by, str) else list(partition_by)
        partition_exprs = [df_col(c) if isinstance(c, str) else c for c in partition_cols]

        # Build ordering based on the expression
        order_expr = self._expr.sort(ascending=not self._rank_descending)

        # Build Window specification
        window = Window(partition_by=partition_exprs, order_by=[order_expr])

        # Map Polars rank methods to DataFusion rank functions
        if self._rank_method == "min":
            rank_func = df_f.rank()
        elif self._rank_method == "dense":
            rank_func = df_f.dense_rank()
        elif self._rank_method == "ordinal":
            rank_func = df_f.row_number()
        elif self._rank_method == "average":
            # DataFusion doesn't have average rank, fall back to rank()
            rank_func = df_f.rank()
        else:
            # Default to rank()
            rank_func = df_f.rank()

        # Apply window specification
        return UnifiedExpr(rank_func.over(window))


class _DataFusionDeferredFilter(UnifiedExpr):
    """Deferred filter expression for DataFusion.

    DataFusion applies filters to aggregate functions differently than Polars/PySpark.
    In DataFusion, the pattern is: f.sum(col).filter(cond).build()
    rather than Polars' col.filter(cond).sum()

    This class captures the column and condition, then applies the filter when
    an aggregate method (sum, count, etc.) is called.
    """

    def __init__(self, expr: Any, condition: Any) -> None:
        """Initialize the deferred filter.

        Args:
            expr: The column expression to aggregate (DataFusion `Expr` at runtime)
            condition: The filter condition to apply (DataFusion `Expr` at runtime)

        Both params stay `Any`: the only call site (`UnifiedExpr.filter` in
        the DataFusion branch) unwraps `condition.native` which itself
        returns `Any`. Tightening the annotation here would mis-state the
        contract - runtime values are DataFusion expressions, but the
        type-checker can't see the dynamic dispatch that guarantees it.
        """
        super().__init__(expr)
        self._filter_condition = condition

    def _apply_filtered_agg(self, agg_func: Any) -> UnifiedExpr:
        """Apply an aggregate function with the deferred filter.

        Args:
            agg_func: DataFusion aggregate function (e.g., f.sum, f.count)

        Returns:
            UnifiedExpr with the filtered aggregate
        """

        # Create aggregate expression
        agg_expr = agg_func(self._expr)
        # Apply filter and build
        filtered = agg_expr.filter(self._filter_condition).build()
        return UnifiedExpr(filtered)

    def sum(self) -> UnifiedExpr:
        """Sum aggregation with filter."""
        from datafusion import functions as df_f

        return self._apply_filtered_agg(df_f.sum)

    def count(self) -> UnifiedExpr:
        """Count aggregation with filter."""
        from datafusion import functions as df_f

        return self._apply_filtered_agg(df_f.count)

    def mean(self) -> UnifiedExpr:
        """Mean aggregation with filter."""
        from datafusion import functions as df_f

        return self._apply_filtered_agg(df_f.avg)

    def avg(self) -> UnifiedExpr:
        """Average aggregation with filter (alias for mean)."""
        return self.mean()

    def min(self) -> UnifiedExpr:
        """Minimum aggregation with filter."""
        from datafusion import functions as df_f

        return self._apply_filtered_agg(df_f.min)

    def max(self) -> UnifiedExpr:
        """Maximum aggregation with filter."""
        from datafusion import functions as df_f

        return self._apply_filtered_agg(df_f.max)


class UnifiedWhenThen:
    """Intermediate result from when().then() for chaining.

    This allows the Polars-style when/then/otherwise pattern:
        when(condition).then(value).otherwise(default)

    `Any` parameters here follow the same convention as `UnifiedExpr`:
    builder/condition/value can be a backend-native expression, a
    `UnifiedExpr`, or a scalar literal. See `UnifiedExpr` class docstring
    for the full rationale.
    """

    def __init__(self, when_builder: Any, platform: str, when_pairs: list | None = None) -> None:
        """Initialize the when-then builder.

        Args:
            when_builder: The platform-specific when builder with .then() already called
            platform: Platform name ("PySpark", "DataFusion", or "Polars")
            when_pairs: For DataFusion, list of (condition, value) tuples accumulated so far
        """
        self._when_builder = when_builder
        self._platform = platform
        self._when_pairs = when_pairs or []

    def when(self, condition: Any) -> UnifiedWhen:
        """Add another WHEN clause (chained).

        Args:
            condition: Boolean condition for this WHEN clause

        Returns:
            UnifiedWhen for adding .then()
        """
        # Unwrap UnifiedExpr condition
        cond = condition._expr if isinstance(condition, UnifiedExpr) else condition

        if self._platform == "PySpark":
            return UnifiedWhen(self._when_builder.when(cond), platform="PySpark")
        if self._platform == "DataFusion":
            # For DataFusion, store the accumulated pairs and new condition for next .then()
            return UnifiedWhen(cond, platform="DataFusion", when_pairs=self._when_pairs)
        return UnifiedWhen(self._when_builder.when(cond), platform="Polars")

    def otherwise(self, value: Any) -> UnifiedExpr:
        """Provide the default value for unmatched conditions.

        Args:
            value: Value to use when no conditions match

        Returns:
            UnifiedExpr with the complete CASE expression
        """
        # Unwrap UnifiedExpr value
        val = value._expr if isinstance(value, UnifiedExpr) else value

        if self._platform == "PySpark":
            from pyspark.sql import functions as F  # noqa: N812

            # PySpark's otherwise() returns a Column
            return UnifiedExpr(self._when_builder.otherwise(val if val is not None else F.lit(None)))

        if self._platform == "DataFusion":
            from datafusion import functions as df_f, lit as df_lit

            # Wrap non-expression values in lit() for DataFusion
            if val is None or not _is_datafusion_expr(val):
                val = df_lit(val)

            # If we have multiple when pairs, use coalesce pattern
            if len(self._when_pairs) > 1:
                # Build coalesce(case(cond1).when(True, val1).end(), case(cond2)..., default)
                case_exprs = []
                for cond, then_val in self._when_pairs:
                    case_expr = df_f.case(cond).when(df_lit(True), then_val).end()
                    case_exprs.append(case_expr)
                case_exprs.append(val)
                return UnifiedExpr(df_f.coalesce(*case_exprs))
            else:
                # Single when: use simple case/when/otherwise
                return UnifiedExpr(self._when_builder.otherwise(val))

        # Polars: otherwise returns an Expr
        return UnifiedExpr(self._when_builder.otherwise(val))


class UnifiedWhen:
    """Platform-agnostic WHEN expression builder.

    Provides Polars-style when/then/otherwise syntax that works across platforms:
        ctx.when(condition).then(value).otherwise(default)

    For PySpark:
        F.when(condition, value).otherwise(default)

    For Polars:
        pl.when(condition).then(value).otherwise(default)

    For DataFusion:
        functions.case(condition).when(lit(True), value).otherwise(default)
        For chained whens: coalesce(case(cond1).when(True,v1).end(), case(cond2)..., default)

    `Any` parameters here follow the same convention as `UnifiedExpr`:
    builder/value can be a backend-native expression, a `UnifiedExpr`, or
    a scalar literal. See `UnifiedExpr` class docstring for the full
    rationale.
    """

    def __init__(self, when_builder: Any, platform: str, when_pairs: list | None = None) -> None:
        """Initialize the when builder.

        Args:
            when_builder: The platform-specific when builder (or condition for PySpark/DataFusion)
            platform: Platform name ("PySpark", "DataFusion", or "Polars")
            when_pairs: For DataFusion, list of (condition, value) tuples accumulated so far
        """
        self._when_builder = when_builder
        self._platform = platform
        self._when_pairs = when_pairs or []

    def then(self, value: Any) -> UnifiedWhenThen:
        """Provide the value when condition is true.

        Args:
            value: Value to return when condition matches

        Returns:
            UnifiedWhenThen for adding .otherwise() or more .when() clauses
        """
        # Unwrap UnifiedExpr value
        val = value._expr if isinstance(value, UnifiedExpr) else value

        if self._platform == "PySpark":
            from pyspark.sql import functions as F  # noqa: N812

            # PySpark: Need to re-call when() with the value
            # The when_builder is just the condition, we need to create F.when(cond, val)
            when_expr = F.when(self._when_builder, val)
            return UnifiedWhenThen(when_expr, platform="PySpark")

        if self._platform == "DataFusion":
            from datafusion import functions as df_f, lit as df_lit

            # For DataFusion, when_builder is the condition
            cond = self._when_builder

            # Wrap non-expression values in lit() for DataFusion
            if not _is_datafusion_expr(val):
                val = df_lit(val)

            # Add this (condition, value) pair to the accumulated list
            new_pairs = self._when_pairs + [(cond, val)]

            # Build case expression for this when
            case_builder = df_f.case(cond).when(df_lit(True), val)

            return UnifiedWhenThen(case_builder, platform="DataFusion", when_pairs=new_pairs)

        # Polars: .then() on the when builder
        return UnifiedWhenThen(self._when_builder.then(val), platform="Polars")


def wrap_expr(expr: Any) -> UnifiedExpr:
    """Wrap an expression in UnifiedExpr if needed.

    Args:
        expr: Native expression

    Returns:
        UnifiedExpr wrapper (or the expr if already wrapped)
    """
    if isinstance(expr, UnifiedExpr):
        return expr
    return UnifiedExpr(expr)


# Backend-detection predicates. `Any` is intentional and load-bearing:
# these helpers are called *before* the caller knows the backend type,
# so narrowing the parameter would invert the API. They accept anything
# and return whether it happens to be a frame/expr from a given backend.
def _is_pyspark_df(df: Any) -> bool:
    """Check if a DataFrame is a PySpark DataFrame."""
    type_name = type(df).__module__
    return "pyspark" in type_name


def _is_polars_df(df: Any) -> bool:
    """Check if a DataFrame is a Polars DataFrame/LazyFrame."""
    type_name = type(df).__module__
    return "polars" in type_name


def _is_datafusion_df(df: Any) -> bool:
    """Check if a DataFrame is a DataFusion DataFrame."""
    type_name = type(df).__module__
    return "datafusion" in type_name


def _is_datafusion_expr(expr: Any) -> bool:
    """Check if an expression is a DataFusion Expr."""
    type_name = type(expr).__module__
    return "datafusion" in type_name


# =========================================================================
# DataFusion Aggregate Arithmetic Helpers (EXPERIMENTAL)
# =========================================================================
# These functions help handle DataFusion's limitation that arithmetic
# on aggregates inside aggregate() is not supported. We extract the
# arithmetic and apply it after the aggregation.
#
# WARNING: This implementation uses error message parsing to extract AST
# information, which is inherently fragile. Tested with DataFusion 43.0.0.
# Future DataFusion versions may change error message formats.
#
# If AST extraction fails, the functions gracefully fall back to passing
# expressions through unchanged (which may cause DataFusion errors for
# unsupported aggregate arithmetic patterns).


def _get_datafusion_ast_string(expr: DataFusionExpr) -> str | None:
    """Get the internal AST representation from a DataFusion expression.

    EXPERIMENTAL: This function relies on parsing error messages from
    DataFusion's rex_call_operator() method to extract AST information.
    This is fragile and may break with DataFusion version changes.

    Tested with: DataFusion 43.0.0
    Expected error message format: "Catch all triggered in get_operator_name: Alias(BinaryExpr...)"

    Args:
        expr: A DataFusion expression

    Returns:
        The AST string representation, or None if extraction failed
    """
    try:
        # rex_call_operator throws an error for Alias expressions,
        # but the error message contains the full AST
        expr.rex_call_operator()
        return None
    except Exception as e:
        # The error message contains the AST like:
        # "Catch all triggered in get_operator_name: Alias(BinaryExpr...)"
        error_str = str(e)
        # Verify we got the expected format (basic sanity check)
        if "Alias" in error_str or "BinaryExpr" in error_str or "AggregateFunction" in error_str:
            return error_str
        # Unexpected format - return None to trigger graceful fallback
        return None


def _extract_datafusion_alias_name(expr_str: str) -> str | None:
    """Extract alias name from expression string representation."""
    import re

    # Pattern: name: \"avg_qty\" in the Alias structure (escaped quotes)
    # The error message escapes quotes, so we need to match \"...\", not "..."
    # Look for the last name: occurrence which is the alias name
    matches = list(re.finditer(r'name:\s*\\"([^\\]+)\\"', expr_str))
    if matches:
        # Return the last match (alias name), not intermediate names
        return matches[-1].group(1)
    return None


def _extract_datafusion_multiplier(expr_str: str) -> tuple[float | None, str | None]:
    """Extract multiplier and operation from BinaryExpr Literal.

    Returns:
        Tuple of (multiplier, operation) where operation is 'multiply' or 'divide'
    """
    import re

    # Pattern: Literal(Float64(0.2), None) or Literal(Int64(2), None)
    match = re.search(r"Literal\((Float64|Int64)\(([0-9.]+)\)", expr_str)
    if match:
        multiplier = float(match.group(2))
        # Determine operation type
        if "op: Multiply" in expr_str:
            return multiplier, "multiply"
        elif "op: Divide" in expr_str:
            return multiplier, "divide"
    return None, None


def _rebuild_datafusion_pure_aggregate(expr_str: str) -> DataFusionExpr | None:
    """Rebuild a pure aggregate expression from a BinaryExpr AST string.

    Given an AST string containing the aggregate pattern, extract just
    the aggregate function call.
    """
    import re

    from datafusion import col as df_col, functions as df_f

    # Find aggregate function name - look for UDF inner name like Avg, Sum
    # Pattern: AggregateUDF { inner: Avg { ... } }
    func_match = re.search(r"inner:\s*(\w+)\s*\{", expr_str)
    if not func_match:
        return None
    func_name = func_match.group(1).lower()  # Avg -> avg, Sum -> sum

    # Find column name within the aggregate
    # Pattern: Column { relation: ..., name: \"l_quantity\" } (escaped quotes)
    col_match = re.search(r'Column \{[^}]*name:\s*\\"([^\\]+)\\"', expr_str)
    if not col_match:
        return None
    col_name = col_match.group(1)

    # Rebuild the pure aggregate
    col_expr = df_col(col_name)
    if func_name == "avg":
        return df_f.avg(col_expr)
    elif func_name == "sum":
        return df_f.sum(col_expr)
    elif func_name == "count":
        return df_f.count(col_expr)
    elif func_name == "min":
        return df_f.min(col_expr)
    elif func_name == "max":
        return df_f.max(col_expr)

    return None


def _extract_datafusion_agg_arithmetic(
    exprs: list[DataFusionExpr],
) -> tuple[list[DataFusionExpr], list[tuple]]:
    """Extract arithmetic operations from DataFusion aggregate expressions.

    DataFusion doesn't support arithmetic on aggregates inside aggregate(),
    e.g., (col.mean() * lit(0.2)).alias("avg_qty") fails with:
    "Invalid aggregate expression 'BinaryExpr(...)'"

    This function detects such patterns and separates:
    1. The pure aggregate expressions (to run in aggregate())
    2. The arithmetic to apply after aggregation

    Handles two patterns:
    1. aggregate * literal (e.g., sum(x) * 0.5)
    2. aggregate * aggregate (e.g., sum(x) * avg(y))
    3. aggregate + aggregate (e.g., sum(x) + sum(y) + sum(z))

    Args:
        exprs: List of native DataFusion expressions

    Returns:
        Tuple of:
        - List of cleaned expressions for aggregate()
        - List of post-ops (various formats for different operations)
    """
    processed = []
    post_ops: list[tuple] = []

    for expr in exprs:
        # Get the internal AST representation by triggering an error message
        # that contains the full Rust AST structure
        ast_str = _get_datafusion_ast_string(expr)

        # Check if this is an aliased BinaryExpr with aggregate
        # Pattern: Alias(BinaryExpr { left: AggregateFunction(...), op: Multiply/Divide, right: Literal(...) }, ...)
        if ast_str and "BinaryExpr" in ast_str and "AggregateFunction" in ast_str:
            # Try to extract the alias name
            alias_name = _extract_datafusion_alias_name(ast_str)
            if alias_name:
                # Count how many aggregates are in this expression
                agg_count = ast_str.count("AggregateFunction(")

                if agg_count >= 2:
                    # Multiple aggregates combined with arithmetic (sum * avg, sum + sum + sum)
                    multi_result = _extract_multi_agg_arithmetic(ast_str, alias_name)
                    if multi_result is not None:
                        temp_exprs, post_op = multi_result
                        processed.extend(temp_exprs)
                        post_ops.append(post_op)
                        continue
                else:
                    # Single aggregate with literal multiplier (existing pattern)
                    value, operation = _extract_datafusion_multiplier(ast_str)
                    if value is not None and operation is not None:
                        # Extract the pure aggregate by rebuilding
                        pure_agg = _rebuild_datafusion_pure_aggregate(ast_str)
                        if pure_agg is not None:
                            temp_alias = f"__temp_{alias_name}__"
                            processed.append(pure_agg.alias(temp_alias))
                            post_ops.append(("literal", temp_alias, alias_name, value, operation))
                            continue

        # No transformation needed - use as-is
        processed.append(expr)

    return processed, post_ops


_AGG_FUNCS = ("sum", "avg", "mean", "count", "min", "max")
_OP_MAP = {"Multiply": "multiply", "Plus": "add", "Divide": "divide", "Minus": "subtract"}


def _parse_multi_agg_pairs(ast_str: str, agg_funcs: list[str], col_matches: list[str], has_nvl: bool):
    import re

    if not has_nvl:
        return [(f.lower(), col_matches[i]) for i, f in enumerate(agg_funcs) if i < len(col_matches)]

    # NVL-wrapped aggregates: match (func, col) pairs inside each AggregateFunction block
    agg_pattern = (
        r"AggregateFunction\s*\{[^}]*inner:\s*(\w+)[^}]*args:\s*\[ScalarFunction[^]]+name:\s*\\?\"([^\"\\]+)\\?\""
    )
    nvl_matches = re.findall(agg_pattern, ast_str, re.DOTALL)
    aggregates = [(f.lower(), c) for f, c in nvl_matches if f.lower() in _AGG_FUNCS]
    if aggregates:
        return aggregates
    # Fall back to positional pairing if the NVL-specific regex didn't match
    return [(f.lower(), col_matches[i]) for i, f in enumerate(agg_funcs) if i < len(col_matches)]


def _pick_primary_op(ops: list[str]) -> str:
    for op in ops:
        if op in ("Multiply", "Plus", "Divide", "Minus"):
            return op
    return ops[0]


def _build_pure_agg_expr(func_name: str, col_name: str):
    from datafusion import col as df_col, functions as df_f

    dispatch = {
        "avg": df_f.avg,
        "mean": df_f.avg,
        "sum": df_f.sum,
        "count": df_f.count,
        "min": df_f.min,
        "max": df_f.max,
    }
    builder = dispatch.get(func_name)
    if builder is None:
        return None
    return builder(df_col(col_name))


def _extract_multi_agg_arithmetic(ast_str: str, alias_name: str) -> tuple[list[Any], tuple] | None:
    """Extract multiple aggregates from a BinaryExpr.

    Handles patterns like:
    - sum(x) * avg(y) -> two temp columns, multiply after
    - sum(a) + sum(b) + sum(c) -> three temp columns, add after
    - sum(nvl(x, 0)) / sum(nvl(y, 0)) -> preserve nvl wrapper

    Returns:
        Tuple of (list of temp aggregate expressions, post_op tuple) or None
    """
    import re

    func_matches = re.findall(r"inner:\s*(\w+)\s*\{", ast_str)
    has_nvl = "NVLFunc" in ast_str or "nvl" in ast_str.lower()
    has_cast = "Cast(" in ast_str and "Float64" in ast_str

    col_matches = re.findall(r'name:\s*\\?"([^"\\]+)\\?"', ast_str)
    col_matches = [c for c in col_matches if c and c[0].isalpha() and c not in ("?table?",)]
    agg_funcs = [f for f in func_matches if f.lower() in _AGG_FUNCS]

    if len(agg_funcs) < 2:
        return None

    aggregates = _parse_multi_agg_pairs(ast_str, agg_funcs, col_matches, has_nvl)
    if len(aggregates) < 2:
        return None

    ops = re.findall(r"op:\s*(\w+)", ast_str)
    if not ops:
        return None
    primary_op = _pick_primary_op(ops)

    # IMPORTANT: DataFusion's aggregate() only accepts pure aggregate expressions.
    # Any wrapping (Cast, coalesce, arithmetic) must be done AFTER aggregation.
    temp_exprs = []
    temp_aliases = []
    for i, (func_name, col_name) in enumerate(aggregates):
        agg_expr = _build_pure_agg_expr(func_name, col_name)
        if agg_expr is None:
            return None
        temp_alias = f"__temp_{alias_name}_{i}__"
        temp_aliases.append(temp_alias)
        temp_exprs.append(agg_expr.alias(temp_alias))

    operation = _OP_MAP.get(primary_op, "multiply")
    return temp_exprs, ("multi", temp_aliases, alias_name, operation, has_nvl, has_cast)


def _apply_datafusion_post_ops(result: DataFusionDataFrame, post_ops: list[tuple]) -> DataFusionDataFrame:
    """Apply post-aggregation arithmetic operations to a DataFusion DataFrame.

    Args:
        result: DataFusion DataFrame with aggregation results
        post_ops: List of post-op tuples in one of these formats:
                  - ("literal", temp_alias, final_alias, value, operation) for single agg * literal
                  - ("multi", temp_aliases, final_alias, operation) for multi agg arithmetic

    Returns:
        DataFrame with arithmetic applied and columns renamed
    """
    from datafusion import col as df_col

    for post_op in post_ops:
        op_type = post_op[0]
        if op_type == "literal":
            result = _apply_literal_post_op(result, post_op, df_col)
        elif op_type == "multi":
            result = _apply_multi_post_op(result, post_op, df_col)
        else:
            raise ValueError(f"Unsupported DataFusion post-op format: {post_op}")

    return result


def _apply_literal_post_op(result: DataFusionDataFrame, post_op: tuple, df_col) -> DataFusionDataFrame:
    """Apply ("literal", temp_alias, final_alias, value, operation) post-op."""
    _, temp_alias, final_alias, value, operation = post_op
    if operation == "multiply":
        result = result.with_column(final_alias, df_col(temp_alias) * value)
    elif operation == "divide":
        result = result.with_column(final_alias, df_col(temp_alias) / value)
    if temp_alias != final_alias:
        result = result.drop(temp_alias)
    return result


def _apply_multi_post_op(result: DataFusionDataFrame, post_op: tuple, df_col) -> DataFusionDataFrame:
    """Apply ("multi", temp_aliases, final_alias, operation[, has_nvl, has_cast]) post-op."""
    if len(post_op) == 6:
        _, temp_aliases, final_alias, operation, has_nvl, has_cast = post_op
    else:
        _, temp_aliases, final_alias, operation = post_op
        has_nvl = False
        has_cast = False

    if len(temp_aliases) < 2:
        return result

    import pyarrow as pa
    from datafusion import functions as df_f, lit as df_lit

    def _prep(alias: str):
        expr = df_col(alias)
        if has_nvl:
            expr = df_f.coalesce(expr, df_lit(0))
        if has_cast:
            expr = expr.cast(pa.float64())
        return expr

    combined = _prep(temp_aliases[0])
    for temp_alias in temp_aliases[1:]:
        next_col = _prep(temp_alias)
        if operation == "multiply":
            combined = combined * next_col
        elif operation == "add":
            combined = combined + next_col
        elif operation == "divide":
            combined = combined / df_f.nullif(next_col, df_lit(0.0))
        elif operation == "subtract":
            combined = combined - next_col

    result = result.with_column(final_alias, combined)
    for temp_alias in temp_aliases:
        result = result.drop(temp_alias)
    return result


class UnifiedGroupBy(Generic[DF, Expr]):
    """Platform-agnostic GroupBy wrapper.

    Wraps the result of group_by() and provides unified agg() method.
    For DataFusion, this is a deferred groupby since DataFusion uses aggregate().
    """

    def __init__(
        self,
        grouped: Any,
        columns: list[str],
        adapter: ExpressionFamilyAdapter,
        source_df: Any,
    ) -> None:
        """Initialize the GroupBy wrapper.

        Args:
            grouped: The native grouped object (or None if deferred for DataFusion)
            columns: The columns being grouped by (native expressions)
            adapter: Reference to the parent adapter
            source_df: The source DataFrame (for deferred grouping)
        """
        self._grouped = grouped
        self._columns = columns
        self._adapter = adapter
        self._source_df = source_df

    def agg(self, *exprs: Expr) -> UnifiedLazyFrame:
        """Aggregate the grouped data.

        Args:
            *exprs: Aggregation expressions (aliased expressions, may be UnifiedExpr)
                    Also accepts a single list of expressions for convenience.

        Returns:
            UnifiedLazyFrame with aggregation results
        """
        # Handle case where a single list is passed instead of *args
        # This happens in queries like: .agg([expr1, expr2, expr3])
        if len(exprs) == 1 and isinstance(exprs[0], list):
            exprs = tuple(exprs[0])

        # Unwrap UnifiedExpr objects to native expressions
        unwrapped = [e.native if isinstance(e, UnifiedExpr) else e for e in exprs]

        if _is_pyspark_df(self._source_df):
            # PySpark: Use groupBy().agg()
            result = self._grouped.agg(*unwrapped)
        elif _is_polars_df(self._source_df):
            # Polars: Use group_by().agg()
            result = self._grouped.agg(*unwrapped)
        elif _is_datafusion_df(self._source_df):
            # DataFusion: Use aggregate([group_cols], [agg_exprs])
            # grouped is None, we use source_df.aggregate() directly
            #
            # DataFusion doesn't support arithmetic on aggregates inside agg(),
            # e.g., (col.mean() * lit(0.2)).alias("x") fails.
            # We need to detect these patterns and handle them in post-processing:
            # 1. Extract the pure aggregates
            # 2. Apply arithmetic after aggregation
            processed_exprs, post_ops = _extract_datafusion_agg_arithmetic(unwrapped)
            result = self._source_df.aggregate(self._columns, processed_exprs)

            # Apply any post-aggregation arithmetic
            if post_ops:
                result = _apply_datafusion_post_ops(result, post_ops)
        else:
            # Fallback: try group_by().agg() pattern
            result = self._grouped.agg(*unwrapped)

        return UnifiedLazyFrame(result, self._adapter)


def _normalize_join_keys(on: Any, left_on: Any, right_on: Any, is_cross_join: bool) -> tuple[list, list, bool]:
    """Normalize on/left_on/right_on into (left_items, right_items, has_expr_join).

    Also decomposes a single equality expression of the form `col("a") == col("b")`
    passed via `left_on` into separate left/right keys.
    """

    def has_expressions(val: Any) -> bool:
        if isinstance(val, UnifiedExpr):
            return True
        if isinstance(val, (list, tuple)):
            return any(isinstance(item, UnifiedExpr) for item in val)
        return False

    left_has_expr = has_expressions(left_on)
    right_has_expr = has_expressions(right_on)
    has_expr_join = left_has_expr or right_has_expr

    if is_cross_join:
        return [], [], has_expr_join

    if on is not None:
        left_items = [on] if isinstance(on, str) else list(on)
        return left_items, left_items.copy(), has_expr_join

    if left_on is None:
        left_items = []
    elif isinstance(left_on, (str, UnifiedExpr)):
        left_items = [left_on]
    else:
        left_items = list(left_on)

    if right_on is None:
        right_items = []
    elif isinstance(right_on, (str, UnifiedExpr)):
        right_items = [right_on]
    else:
        right_items = list(right_on)

    if (
        len(left_items) == 1
        and not right_items
        and isinstance(left_items[0], UnifiedExpr)
        and hasattr(left_items[0], "_eq_left")
    ):
        eq_expr = left_items[0]
        left_items = [eq_expr._eq_left]
        right_items = [eq_expr._eq_right]
        has_expr_join = True

    return left_items, right_items, has_expr_join


def _rename_duplicate_right_columns(other_df: Any, duplicate_cols: set[str], used_names: set[str], suffix: str) -> Any:
    """Rename duplicate right-side columns by appending suffix (with incremental counter on collisions)."""
    for col_name in duplicate_cols:
        new_name = f"{col_name}{suffix}"
        counter = 2
        while new_name in used_names:
            new_name = f"{col_name}{suffix}_{counter}"
            counter += 1
        other_df = other_df.with_column_renamed(col_name, new_name)
        used_names.add(new_name)
    return other_df


def _rename_conflicting_join_keys(
    other_df: Any,
    left_cols: list[str],
    right_cols: list[str],
    left_columns: set[str],
    used_names: set[str],
    suffix: str,
    is_outer_join: bool,
) -> tuple[Any, dict[str, str]]:
    """Rename right-side join keys that conflict with left columns.

    Outer joins use suffixed names (so values can be coalesced by the caller).
    Inner joins use a temporary sentinel name the caller drops after joining.
    """
    right_join_key_renames: dict[str, str] = {}
    for i, (left_key, right_key) in enumerate(zip(left_cols, right_cols)):
        if right_key == left_key or (right_key in left_columns and right_key != left_key):
            if is_outer_join:
                new_right_key = f"{right_key}{suffix}"
                counter = 2
                while new_right_key in used_names:
                    new_right_key = f"{right_key}{suffix}_{counter}"
                    counter += 1
                used_names.add(new_right_key)
            else:
                new_right_key = f"__right_join_key_{i}__"
            other_df = other_df.with_column_renamed(right_key, new_right_key)
            right_join_key_renames[right_key] = new_right_key
    return other_df, right_join_key_renames


def _normalize_sort_inputs(
    by: Any,
    more_columns: tuple,
    descending: bool | list[bool],
) -> tuple[list, list[bool]]:
    """Resolve sort inputs into (cols, desc_flags) lists.

    Handles three calling styles:
    - positional columns: .sort("c1", "c2")
    - list + descending flag(s): .sort([...], descending=[True, False])
    - tuple syntax: .sort([("c1", "desc"), ("c2", "asc")])
    """
    cols = list(by) if isinstance(by, list) else [by]
    cols.extend(more_columns)

    tuple_desc_flags: list[bool] | None = None
    if cols and isinstance(cols[0], tuple):
        tuple_desc_flags = []
        parsed_cols = []
        for item in cols:
            if isinstance(item, tuple):
                col_name, direction = item
                parsed_cols.append(col_name)
                tuple_desc_flags.append(direction.lower().startswith("desc"))
            else:
                parsed_cols.append(item)
                tuple_desc_flags.append(False)
        cols = parsed_cols

    if tuple_desc_flags is not None:
        desc_flags = tuple_desc_flags
    elif isinstance(descending, bool):
        desc_flags = [descending] * len(cols)
    else:
        desc_flags = list(descending)
        if len(desc_flags) < len(cols):
            desc_flags.extend([False] * (len(cols) - len(desc_flags)))
    return cols, desc_flags


def _sort_pyspark(df, cols: list, desc_flags: list[bool], nulls_last: bool):
    """Build PySpark orderBy expressions with desc/asc and nulls_last handling."""
    from pyspark.sql import functions as F  # noqa: N812

    order_exprs = []
    for col_item, desc in zip(cols, desc_flags, strict=False):
        if isinstance(col_item, UnifiedExpr):
            expr = col_item.native
        elif isinstance(col_item, str):
            expr = F.col(col_item)
        else:
            expr = col_item

        if desc:
            order_exprs.append(expr.desc_nulls_last() if nulls_last else expr.desc())
        else:
            order_exprs.append(expr.asc_nulls_last() if nulls_last else expr.asc())
    return df.orderBy(*order_exprs)


def _sort_datafusion(df, cols: list, desc_flags: list[bool], nulls_last: bool):
    """Build DataFusion SortExpr list, passing through pre-built SortExprs."""
    from datafusion import col as df_col
    from datafusion.expr import SortExpr

    sort_exprs = []
    for col_item, desc in zip(cols, desc_flags, strict=False):
        if isinstance(col_item, UnifiedExpr):
            expr = col_item.native
        elif isinstance(col_item, str):
            expr = df_col(col_item)
        else:
            expr = col_item
        if isinstance(expr, SortExpr):
            sort_exprs.append(expr)
        else:
            sort_exprs.append(expr.sort(ascending=not desc, nulls_first=not nulls_last))
    return df.sort(*sort_exprs)


def _prepare_join_items(df, items: list, side: str) -> tuple[Any, list[str], list[str]]:
    """Promote expression join items to temp columns; return (df, join_cols, temp_cols)."""
    join_cols: list[str] = []
    temp_cols: list[str] = []
    for i, item in enumerate(items):
        if isinstance(item, UnifiedExpr):
            temp_col = f"__{side}_join_key_{i}__"
            df = df.with_column(temp_col, item.native)
            join_cols.append(temp_col)
            temp_cols.append(temp_col)
        elif isinstance(item, str):
            join_cols.append(item)
        elif _is_datafusion_expr(item):
            temp_col = f"__{side}_join_key_{i}__"
            df = df.with_column(temp_col, item)
            join_cols.append(temp_col)
            temp_cols.append(temp_col)
        else:
            join_cols.append(str(item))
    return df, join_cols, temp_cols


def _rename_same_named_join_keys(
    right_df,
    left_join_cols: list[str],
    right_join_cols: list[str],
    temp_cols_right: list[str],
    left_columns: set[str],
    used_names: set[str],
    is_outer_join: bool,
    suffix: str,
) -> tuple[Any, dict[str, str]]:
    """Rename right join keys that collide with left; inner joins get temp names, outer joins get suffixes."""
    renames: dict[str, str] = {}
    for i, (left_key, right_key) in enumerate(zip(left_join_cols, right_join_cols)):
        collides = right_key == left_key or (right_key in left_columns and right_key not in temp_cols_right)
        if not collides:
            continue
        if is_outer_join:
            new_right_key = f"{right_key}{suffix}"
            counter = 2
            while new_right_key in used_names:
                new_right_key = f"{right_key}{suffix}_{counter}"
                counter += 1
            used_names.add(new_right_key)
        else:
            new_right_key = f"__expr_join_right_key_{i}__"
        right_df = right_df.with_column_renamed(right_key, new_right_key)
        renames[right_key] = new_right_key
    return right_df, renames


def _drop_post_join_temp_columns(
    result,
    temp_cols_left: list[str],
    temp_cols_right: list[str],
    right_join_key_renames: dict[str, str],
    is_outer_join: bool,
    suffix: str,
):
    """Drop join-scaffolding columns (renamed right keys for inner joins, temp left/right cols)."""
    if not is_outer_join:
        for new_key in right_join_key_renames.values():
            if new_key in [field.name for field in result.schema()]:
                result = result.drop(new_key)
    for temp_col in temp_cols_left:
        if temp_col in [field.name for field in result.schema()]:
            result = result.drop(temp_col)
    for temp_col in temp_cols_right:
        for col_name in (temp_col, f"{temp_col}{suffix}"):
            if col_name in [field.name for field in result.schema()]:
                result = result.drop(col_name)
    return result


class UnifiedLazyFrame(Generic[DF, Expr]):
    """Platform-agnostic DataFrame wrapper for expression-family queries.

    This wrapper provides a consistent API that works across Polars, PySpark,
    and DataFusion DataFrames. Method calls are intercepted and translated
    to the appropriate platform-specific API.

    The wrapper maintains method chaining by returning new UnifiedLazyFrame
    instances from operations.

    Attributes:
        _df: The underlying native DataFrame
        _adapter: Reference to the parent adapter for platform-specific operations
    """

    def __init__(self, df: DF, adapter: ExpressionFamilyAdapter) -> None:
        """Initialize the unified frame.

        Args:
            df: The underlying native DataFrame (Polars LazyFrame, PySpark DataFrame, etc.)
            adapter: Reference to the parent adapter
        """
        self._df = df
        self._adapter = adapter

    @property
    def native(self) -> DF:
        """Access the underlying native DataFrame.

        Use this when you need to pass the DataFrame to platform-specific
        functions or when the query is complete.

        Returns:
            The native DataFrame
        """
        return self._df

    @property
    def columns(self) -> list[str]:
        """Get column names from the DataFrame."""
        if _is_datafusion_df(self._df):
            # DataFusion: Use schema() to get field names
            return [field.name for field in self._df.schema()]
        # Use collect_schema().names() for LazyFrames to avoid PerformanceWarning
        if hasattr(self._df, "collect_schema"):
            return self._df.collect_schema().names()
        return list(self._df.columns)

    # =========================================================================
    # Join Operations
    # =========================================================================

    def join(
        self,
        other: UnifiedLazyFrame | LazyFrameLike,
        left_on: str | list | None = None,
        right_on: str | list | Any | None = None,
        on: str | list[str] | None = None,
        how: str = "inner",
        suffix: str = "_right",
    ) -> UnifiedLazyFrame:
        """Join with another DataFrame.

        Provides a unified join API that works across platforms:
        - Polars: Uses native left_on/right_on with suffix
        - PySpark: Translates to column equality conditions with suffix renaming

        Supports expression-based joins where left_on or right_on can contain
        computed expressions (e.g., col("x") + lit(52)).

        Args:
            other: DataFrame to join with (UnifiedLazyFrame or native)
            left_on: Column(s) from left DataFrame (can include UnifiedExpr)
            right_on: Column(s) from right DataFrame (can include UnifiedExpr)
            on: Column(s) if same name in both (alternative to left_on/right_on)
            how: Join type: "inner", "left", "right", "outer", "full", "semi", "anti"
            suffix: Suffix to add to duplicate column names from right DataFrame

        Returns:
            UnifiedLazyFrame with join result
        """
        # Unwrap if other is a UnifiedLazyFrame
        other_df = other._df if isinstance(other, UnifiedLazyFrame) else other

        # Handle cross joins (no join columns)
        is_cross_join = how == "cross" or (on is None and left_on is None and right_on is None)

        left_items, right_items, has_expr_join = _normalize_join_keys(on, left_on, right_on, is_cross_join)

        if _is_pyspark_df(self._df):
            # PySpark join: use condition-based join
            if is_cross_join:
                result = self._pyspark_cross_join(other_df, suffix)
            elif has_expr_join:
                # Multi-column or expression-based join
                result = self._pyspark_join_multi_expr(other_df, left_items, right_items, how, suffix)
            else:
                result = self._pyspark_join(other_df, left_items, right_items, how, suffix)
        elif _is_polars_df(self._df):
            # Polars uses "full" not "outer" for full outer joins (deprecated in 0.20.29)
            if how == "outer":
                how = "full"
            if is_cross_join:
                result = self._df.join(other_df, how="cross", suffix=suffix)
            elif has_expr_join:
                # Polars expression joins: add computed columns, join, drop temp keys
                result = self._polars_join_with_exprs(other_df, left_items, right_items, how, suffix)
            else:
                left_cols = [item for item in left_items if isinstance(item, str)]
                right_cols = [item for item in right_items if isinstance(item, str)]
                result = self._df.join(
                    other_df,
                    left_on=left_cols if len(left_cols) > 1 else left_cols[0],
                    right_on=right_cols if len(right_cols) > 1 else right_cols[0],
                    how=how,
                    suffix=suffix,
                )
        elif _is_datafusion_df(self._df):
            # DataFusion uses "full" not "outer" for full outer joins
            if how == "outer":
                how = "full"

            if is_cross_join:
                result = self._datafusion_cross_join(other_df, suffix)
            elif has_expr_join:
                result = self._datafusion_join_with_exprs(other_df, left_items, right_items, how, suffix)
            else:
                result = self._datafusion_standard_join(other_df, left_items, right_items, how, suffix)
        else:
            # Fallback: try Polars-style
            left_cols = [item for item in left_items if isinstance(item, str)]
            right_cols = [item for item in right_items if isinstance(item, str)]
            result = self._df.join(
                other_df,
                left_on=left_cols,
                right_on=right_cols,
                how=how,
            )

        return UnifiedLazyFrame(result, self._adapter)

    def _datafusion_cross_join(self, other_df: Any, suffix: str) -> Any:
        """DataFusion cross join: rename duplicate cols, add constant keys on each side, inner-join, drop keys."""
        from datafusion import lit as df_lit

        left_columns = {field.name for field in self._df.schema()}
        right_columns = {field.name for field in other_df.schema()}
        duplicate_cols = left_columns & right_columns

        renamed_other = _rename_duplicate_right_columns(other_df, duplicate_cols, set(left_columns), suffix)

        left_with_key = self._df.with_column("__cross_key_left__", df_lit(1))
        right_with_key = renamed_other.with_column("__cross_key_right__", df_lit(1))
        result = left_with_key.join(
            right_with_key,
            left_on=["__cross_key_left__"],
            right_on=["__cross_key_right__"],
            how="inner",
        )
        return result.drop("__cross_key_left__").drop("__cross_key_right__")

    def _datafusion_standard_join(
        self,
        other_df: Any,
        left_items: list,
        right_items: list,
        how: str,
        suffix: str,
    ) -> Any:
        """DataFusion join with manual duplicate-column and join-key renaming (no native suffix support)."""
        left_cols = [item for item in left_items if isinstance(item, str)]
        right_cols = [item for item in right_items if isinstance(item, str)]

        left_columns = {field.name for field in self._df.schema()}
        right_columns = {field.name for field in other_df.schema()}

        join_keys_on_right = set(right_cols)
        non_join_right_cols = right_columns - join_keys_on_right
        duplicate_cols = left_columns & non_join_right_cols

        used_names = set(left_columns)
        renamed_other = _rename_duplicate_right_columns(other_df, duplicate_cols, used_names, suffix)

        is_outer_join = how in ("full", "outer", "left", "right")
        renamed_other, right_join_key_renames = _rename_conflicting_join_keys(
            renamed_other, left_cols, right_cols, left_columns, used_names, suffix, is_outer_join
        )

        actual_right_cols = [right_join_key_renames.get(c, c) for c in right_cols]
        result = self._df.join(
            renamed_other,
            left_on=left_cols,
            right_on=actual_right_cols,
            how=how,
        )

        if not is_outer_join:
            for _old_key, new_key in right_join_key_renames.items():
                if new_key in [field.name for field in result.schema()]:
                    result = result.drop(new_key)
        return result

    def _pyspark_join(
        self,
        other: PySparkDataFrame,
        left_cols: list[str],
        right_cols: list[str],
        how: str,
        suffix: str = "_right",
    ) -> PySparkDataFrame:
        """Execute a PySpark join with column equality conditions.

        Args:
            other: The right DataFrame
            left_cols: Left join columns
            right_cols: Right join columns
            how: Join type
            suffix: Suffix to add to duplicate column names from right DataFrame

        Returns:
            Joined PySpark DataFrame
        """
        # Map join types
        join_map = {
            "inner": "inner",
            "left": "left",
            "right": "right",
            "outer": "outer",
            "full": "outer",
            "semi": "leftsemi",
            "leftsemi": "leftsemi",
            "anti": "leftanti",
            "leftanti": "leftanti",
        }
        spark_how = join_map.get(how, how)

        # Find duplicate column names (excluding join keys)
        left_columns = set(self._df.columns)
        right_columns = set(other.columns)
        # Columns that appear in both (potential duplicates after join)
        duplicate_cols = left_columns & right_columns

        # Determine if join columns are the same names
        same_join_cols = left_cols == right_cols

        # For full/outer joins with same column names, we need BOTH copies of join columns
        # (for coalescing), so rename the right side's join columns too
        is_outer_join = how in ("full", "outer")

        # Rename duplicate NON-JOIN columns on right side before join
        # For same-name joins using list syntax, join columns are automatically unified
        renamed_other = other
        for col_name in duplicate_cols:
            if is_outer_join and same_join_cols:
                # For outer joins: rename ALL duplicates including join keys
                new_name = f"{col_name}{suffix}"
                renamed_other = renamed_other.withColumnRenamed(col_name, new_name)
            elif col_name not in right_cols:
                # For other joins: only rename non-join duplicates
                new_name = f"{col_name}{suffix}"
                renamed_other = renamed_other.withColumnRenamed(col_name, new_name)

        # Build join condition
        if is_outer_join and same_join_cols:
            # For outer joins where we renamed join columns, use condition-based join
            conditions = [
                self._df[lc] == renamed_other[f"{rc}{suffix}"] for lc, rc in zip(left_cols, right_cols, strict=True)
            ]
            condition = conditions[0]
            for c in conditions[1:]:
                condition = condition & c
            result = self._df.join(renamed_other, condition, spark_how)
        elif same_join_cols:
            # For non-outer joins with same column names, use LIST-BASED join
            # PySpark's list-based join automatically unifies join columns and avoids ambiguity
            join_cols = left_cols if len(left_cols) > 1 else left_cols[0]
            result = self._df.join(renamed_other, join_cols, spark_how)
        else:
            # For different column names, use condition-based join
            conditions = [self._df[lc] == renamed_other[rc] for lc, rc in zip(left_cols, right_cols, strict=True)]
            condition = conditions[0]
            for c in conditions[1:]:
                condition = condition & c
            result = self._df.join(renamed_other, condition, spark_how)
            # Drop right join keys for non-outer joins
            if how not in ("semi", "leftsemi", "anti", "leftanti", "full", "outer"):
                for lc, rc in zip(left_cols, right_cols, strict=True):
                    if lc != rc and rc in result.columns:
                        result = result.drop(rc)

        # For outer joins with different column names, keep both sets (for NULL checks)
        # No additional cleanup needed

        return result

    def _pyspark_cross_join(
        self,
        other: PySparkDataFrame,
        suffix: str = "_right",
    ) -> PySparkDataFrame:
        """Execute a PySpark cross join (cartesian product).

        Args:
            other: The right DataFrame
            suffix: Suffix to add to duplicate column names

        Returns:
            Cross-joined PySpark DataFrame
        """
        # Find duplicate column names
        left_columns = set(self._df.columns)
        right_columns = set(other.columns)
        duplicate_cols = left_columns & right_columns

        # Rename duplicate columns on right side before join
        renamed_other = other
        for col_name in duplicate_cols:
            new_name = f"{col_name}{suffix}"
            renamed_other = renamed_other.withColumnRenamed(col_name, new_name)

        # PySpark cross join
        return self._df.crossJoin(renamed_other)

    def _pyspark_join_expr(
        self,
        other: PySparkDataFrame,
        left_col: str,
        right_expr: UnifiedExpr,
        how: str,
        suffix: str = "_right",
    ) -> PySparkDataFrame:
        """Execute a PySpark join with an expression-based condition.

        Used for joins like: left_on="col1", right_on=col("col2") - 53

        Args:
            other: The right DataFrame
            left_col: Left join column name
            right_expr: Right join expression (UnifiedExpr)
            how: Join type
            suffix: Suffix to add to duplicate column names

        Returns:
            Joined PySpark DataFrame
        """
        # Map join types
        join_map = {
            "inner": "inner",
            "left": "left",
            "right": "right",
            "outer": "outer",
            "full": "outer",
            "semi": "leftsemi",
            "leftsemi": "leftsemi",
            "anti": "leftanti",
            "leftanti": "leftanti",
        }
        spark_how = join_map.get(how, how)

        # Find duplicate column names
        left_columns = set(self._df.columns)
        right_columns = set(other.columns)
        duplicate_cols = left_columns & right_columns

        # Rename duplicate columns on right side before join
        renamed_other = other
        for col_name in duplicate_cols:
            new_name = f"{col_name}{suffix}"
            renamed_other = renamed_other.withColumnRenamed(col_name, new_name)

        # Build join condition using expression
        # The right_expr.native gives us the computed PySpark Column
        condition = self._df[left_col] == right_expr.native

        return self._df.join(renamed_other, condition, spark_how)

    def _pyspark_join_multi_expr(
        self,
        other: PySparkDataFrame,
        left_items: list,
        right_items: list,
        how: str,
        suffix: str = "_right",
    ) -> PySparkDataFrame:
        """Execute a PySpark join with mixed column names and expressions.

        Handles joins like:
            left_on=["s_store_id1", (col("d_week_seq1") + lit(52))],
            right_on=["s_store_id2", "d_week_seq2"]

        Args:
            other: The right DataFrame
            left_items: List of column names and/or expressions for left side
            right_items: List of column names and/or expressions for right side
            how: Join type
            suffix: Suffix to add to duplicate column names

        Returns:
            Joined PySpark DataFrame
        """

        # Map join types
        join_map = {
            "inner": "inner",
            "left": "left",
            "right": "right",
            "outer": "outer",
            "full": "outer",
            "semi": "leftsemi",
            "leftsemi": "leftsemi",
            "anti": "leftanti",
            "leftanti": "leftanti",
        }
        spark_how = join_map.get(how, how)

        # Find duplicate column names
        left_columns = set(self._df.columns)
        right_columns = set(other.columns)
        duplicate_cols = left_columns & right_columns

        # Rename duplicate columns on right side before join
        renamed_other = other
        for col_name in duplicate_cols:
            new_name = f"{col_name}{suffix}"
            renamed_other = renamed_other.withColumnRenamed(col_name, new_name)

        # Build join conditions for each pair of left/right items
        conditions = []
        for left_item, right_item in zip(left_items, right_items):
            # Convert left item to PySpark column/expression
            if isinstance(left_item, UnifiedExpr):
                left_col = left_item.native
            elif isinstance(left_item, str):
                left_col = self._df[left_item]
            else:
                left_col = left_item

            # Convert right item to PySpark column/expression
            # Note: right side references renamed_other, but column names in expression
            # may reference original names (need to handle carefully)
            if isinstance(right_item, UnifiedExpr):
                right_col = right_item.native
            elif isinstance(right_item, str):
                # Check if this column was renamed
                if right_item in duplicate_cols:
                    right_col = renamed_other[f"{right_item}{suffix}"]
                else:
                    right_col = renamed_other[right_item]
            else:
                right_col = right_item

            conditions.append(left_col == right_col)

        # Combine all conditions with AND
        combined_condition = conditions[0]
        for cond in conditions[1:]:
            combined_condition = combined_condition & cond

        return self._df.join(renamed_other, combined_condition, spark_how)

    def _polars_join_with_exprs(
        self,
        other: pl.DataFrame | pl.LazyFrame,
        left_items: list,
        right_items: list,
        how: str,
        suffix: str = "_right",
    ) -> pl.DataFrame | pl.LazyFrame:
        """Execute a Polars join with mixed column names and expressions.

        Polars doesn't directly support expression-based joins, so we add
        temporary computed columns, perform the join, then drop the temp columns.

        Args:
            other: The right DataFrame
            left_items: List of column names and/or expressions for left side
            right_items: List of column names and/or expressions for right side
            how: Join type
            suffix: Suffix to add to duplicate column names

        Returns:
            Joined Polars DataFrame
        """

        left_df = self._df
        right_df = other

        # Track temp columns to drop later
        temp_cols_left = []
        temp_cols_right = []

        # Process left items - add temp columns for expressions
        left_join_cols = []
        for i, item in enumerate(left_items):
            if isinstance(item, UnifiedExpr):
                temp_col = f"__left_join_key_{i}__"
                left_df = left_df.with_columns(item.native.alias(temp_col))
                left_join_cols.append(temp_col)
                temp_cols_left.append(temp_col)
            elif isinstance(item, str):
                left_join_cols.append(item)
            else:
                # Try to use as-is (may be a pl.Expr)
                temp_col = f"__left_join_key_{i}__"
                left_df = left_df.with_columns(item.alias(temp_col))
                left_join_cols.append(temp_col)
                temp_cols_left.append(temp_col)

        # Process right items - add temp columns for expressions
        right_join_cols = []
        for i, item in enumerate(right_items):
            if isinstance(item, UnifiedExpr):
                temp_col = f"__right_join_key_{i}__"
                right_df = right_df.with_columns(item.native.alias(temp_col))
                right_join_cols.append(temp_col)
                temp_cols_right.append(temp_col)
            elif isinstance(item, str):
                right_join_cols.append(item)
            else:
                # Try to use as-is (may be a pl.Expr)
                temp_col = f"__right_join_key_{i}__"
                right_df = right_df.with_columns(item.alias(temp_col))
                right_join_cols.append(temp_col)
                temp_cols_right.append(temp_col)

        # Perform the join
        result = left_df.join(
            right_df,
            left_on=left_join_cols if len(left_join_cols) > 1 else left_join_cols[0],
            right_on=right_join_cols if len(right_join_cols) > 1 else right_join_cols[0],
            how=how,
            suffix=suffix,
        )

        # Drop temp columns
        all_temp_cols = temp_cols_left + [f"{c}{suffix}" if c in temp_cols_right else c for c in temp_cols_right]
        # Also need to handle suffixed versions if they ended up in result
        # Use collect_schema().names() to avoid PerformanceWarning on LazyFrame.columns
        result_cols = result.collect_schema().names() if hasattr(result, "collect_schema") else list(result.columns)
        for temp_col in temp_cols_right:
            if f"{temp_col}{suffix}" in result_cols:
                all_temp_cols.append(f"{temp_col}{suffix}")

        # Filter to only columns that exist
        cols_to_drop = [c for c in all_temp_cols if c in result_cols]
        if cols_to_drop:
            result = result.drop(cols_to_drop)

        return result

    def _datafusion_join_with_exprs(
        self,
        other: DataFusionDataFrame,
        left_items: list,
        right_items: list,
        how: str,
        suffix: str = "_right",
    ) -> DataFusionDataFrame:
        """Execute a DataFusion join with mixed column names and expressions.

        DataFusion doesn't directly support expression-based joins, so we add
        temporary computed columns, perform the join, then drop the temp columns.

        Args:
            other: The right DataFrame
            left_items: List of column names and/or expressions for left side
            right_items: List of column names and/or expressions for right side
            how: Join type
            suffix: Suffix to add to duplicate column names

        Returns:
            Joined DataFusion DataFrame
        """
        left_df, left_join_cols, temp_cols_left = _prepare_join_items(self._df, left_items, "left")
        right_df, right_join_cols, temp_cols_right = _prepare_join_items(other, right_items, "right")

        left_columns = {field.name for field in left_df.schema()}
        right_columns = {field.name for field in right_df.schema()}

        duplicate_cols = left_columns & (right_columns - set(right_join_cols))
        used_names = set(left_columns)
        right_df = _rename_duplicate_right_columns(right_df, duplicate_cols, used_names, suffix)

        is_outer_join = how in ("full", "outer", "left", "right")
        right_df, right_join_key_renames = _rename_same_named_join_keys(
            right_df,
            left_join_cols,
            right_join_cols,
            temp_cols_right,
            left_columns,
            used_names,
            is_outer_join,
            suffix,
        )

        actual_right_join_cols = [right_join_key_renames.get(c, c) for c in right_join_cols]
        result = left_df.join(
            right_df,
            left_on=left_join_cols,
            right_on=actual_right_join_cols,
            how=how,
        )
        return _drop_post_join_temp_columns(
            result, temp_cols_left, temp_cols_right, right_join_key_renames, is_outer_join, suffix
        )

    # =========================================================================
    # Grouping Operations
    # =========================================================================

    def group_by(self, *columns: str | Expr | list) -> UnifiedGroupBy:
        """Group by one or more columns.

        Provides unified grouping that works across platforms:
        - Polars: Uses group_by()
        - PySpark: Uses groupBy()
        - DataFusion: Deferred to aggregate() call

        Args:
            *columns: Column names or expressions to group by (may include UnifiedExpr)
                      Also accepts a single list of column names for convenience.

        Returns:
            UnifiedGroupBy for aggregation
        """
        # Handle case where a single list is passed instead of *args
        # This happens in queries like: .group_by(["col1", "col2"])
        if len(columns) == 1 and isinstance(columns[0], list):
            columns = tuple(columns[0])

        # Unwrap UnifiedExpr objects to native expressions
        col_list = [c.native if isinstance(c, UnifiedExpr) else c for c in columns]

        if _is_pyspark_df(self._df):
            # PySpark uses groupBy
            grouped = self._df.groupBy(*col_list)
        elif _is_polars_df(self._df):
            # Polars uses group_by
            grouped = self._df.group_by(*col_list)
        elif _is_datafusion_df(self._df):
            # DataFusion: Deferred groupby - aggregate() will be called in UnifiedGroupBy.agg()
            # Convert column names to col() expressions for aggregate()
            from datafusion import col as df_col

            col_exprs = [df_col(c) if isinstance(c, str) else c for c in col_list]
            grouped = None  # No native grouped object for DataFusion
            return UnifiedGroupBy(grouped, col_exprs, self._adapter, self._df)
        else:
            # Fallback: try group_by
            grouped = self._df.group_by(*col_list)

        return UnifiedGroupBy(grouped, col_list, self._adapter, self._df)

    # =========================================================================
    # Filter/Select Operations
    # =========================================================================

    def filter(self, condition: Expr) -> UnifiedLazyFrame:
        """Filter rows by condition.

        Args:
            condition: Boolean expression for filtering (may be UnifiedExpr)

        Returns:
            UnifiedLazyFrame with filtered rows
        """
        # Unwrap UnifiedExpr if needed
        native_condition = condition.native if isinstance(condition, UnifiedExpr) else condition
        result = self._df.filter(native_condition)
        return UnifiedLazyFrame(result, self._adapter)

    def select(self, *columns: str | Expr | list) -> UnifiedLazyFrame:
        """Select columns.

        Args:
            *columns: Column names or expressions to select (may include UnifiedExpr)
                      Also accepts a single list of columns for convenience.

        Returns:
            UnifiedLazyFrame with selected columns
        """
        # Handle case where a single list is passed instead of *args
        if len(columns) == 1 and isinstance(columns[0], list):
            columns = tuple(columns[0])

        # Unwrap UnifiedExpr objects
        unwrapped = [c.native if isinstance(c, UnifiedExpr) else c for c in columns]

        if _is_datafusion_df(self._df):
            # DataFusion: Check if any expression contains aggregates
            # If so, use aggregate() instead of select() for proper execution
            has_aggregate = self._has_aggregate_expr(unwrapped)
            if has_aggregate:
                # DataFusion doesn't support arithmetic on aggregates inside aggregate(),
                # so we need to extract and apply arithmetic post-aggregation
                processed_exprs, post_ops = _extract_datafusion_agg_arithmetic(unwrapped)
                # Use aggregate with empty group-by for DataFrame-level aggregation
                result = self._df.aggregate([], processed_exprs)
                # Apply any post-aggregation arithmetic
                if post_ops:
                    result = _apply_datafusion_post_ops(result, post_ops)
            else:
                result = self._df.select(*unwrapped)
        else:
            result = self._df.select(*unwrapped)
        return UnifiedLazyFrame(result, self._adapter)

    def _has_aggregate_expr(self, exprs: list) -> bool:
        """Check if any expression contains an aggregate function.

        This is used for DataFusion to determine whether to use aggregate()
        instead of select() for proper execution.

        Args:
            exprs: List of expressions to check

        Returns:
            True if any expression contains an aggregate function
        """
        if not _is_datafusion_df(self._df):
            return False

        for expr in exprs:
            expr_str = str(expr)
            # Check for common aggregate function patterns in the expression string
            agg_patterns = [
                "sum(",
                "avg(",
                "count(",
                "min(",
                "max(",
                "SUM(",
                "AVG(",
                "COUNT(",
                "MIN(",
                "MAX(",
                "first_value(",
                "last_value(",
                "stddev(",
                "FIRST_VALUE(",
                "LAST_VALUE(",
                "STDDEV(",
            ]
            for pattern in agg_patterns:
                if pattern in expr_str:
                    return True
        return False

    def with_columns(self, *exprs: Expr | list) -> UnifiedLazyFrame:
        """Add or replace columns.

        Provides unified column addition:
        - Polars: Uses with_columns() which replaces columns with same name
        - PySpark: Uses withColumn() which also replaces columns with same name

        Args:
            *exprs: Aliased expressions for new columns (may be UnifiedExpr)
                    Also accepts a single list of expressions for convenience.

        Returns:
            UnifiedLazyFrame with new columns
        """
        # Handle case where a single list is passed instead of *args
        if len(exprs) == 1 and isinstance(exprs[0], list):
            exprs = tuple(exprs[0])

        # Unwrap UnifiedExpr objects
        unwrapped = [e.native if isinstance(e, UnifiedExpr) else e for e in exprs]

        if _is_pyspark_df(self._df):
            # PySpark: Use withColumn which properly replaces existing columns
            # (unlike select("*", expr) which adds duplicate columns)
            result = self._df
            for expr in unwrapped:
                # Extract the alias/column name from the expression
                # PySpark Column has _jc.toString() that gives "expr AS alias" format
                col_name = None
                try:
                    # Check if expression has _jc (PySpark Column)
                    if hasattr(expr, "_jc"):
                        expr_str = str(expr._jc.toString())
                        if " AS " in expr_str:
                            col_name = expr_str.split(" AS ")[-1].strip("`")
                except Exception:
                    pass

                # Use withColumn (replaces existing column) if we have a name,
                # else fall back to select (shouldn't happen with properly aliased expressions)
                result = result.withColumn(col_name, expr) if col_name else result.select("*", expr)
        elif _is_polars_df(self._df):
            # Polars: Uses with_columns directly
            result = self._df.with_columns(*unwrapped)
        else:
            # DataFusion or fallback
            result = self._df.with_columns(*unwrapped)

        return UnifiedLazyFrame(result, self._adapter)

    # =========================================================================
    # DataFrame-level Aggregations
    # =========================================================================

    def sum(self) -> UnifiedLazyFrame:
        """Sum all numeric columns (DataFrame-level aggregation).

        Returns a DataFrame with a single row containing the sum of each column.

        For PySpark/DataFusion, this uses agg(sum(col) for each column).

        Returns:
            UnifiedLazyFrame with single row of sums
        """
        if _is_pyspark_df(self._df):
            from pyspark.sql import functions as F  # noqa: N812

            # Get all columns and create sum aggregations
            sum_exprs = [F.sum(F.col(c)).alias(c) for c in self._df.columns]
            result = self._df.agg(*sum_exprs)
        elif _is_polars_df(self._df):
            # Polars: Use native sum()
            result = self._df.sum()
        elif _is_datafusion_df(self._df):
            # DataFusion: Use aggregate() with no group columns
            from datafusion import col as df_col, functions as df_f

            schema_fields = [field.name for field in self._df.schema()]
            sum_exprs = [df_f.sum(df_col(c)).alias(c) for c in schema_fields]
            result = self._df.aggregate([], sum_exprs)
        else:
            # Fallback
            result = self._df.sum()

        return UnifiedLazyFrame(result, self._adapter)

    def mean(self) -> UnifiedLazyFrame:
        """Mean of all numeric columns (DataFrame-level aggregation).

        Returns a DataFrame with a single row containing the mean of each column.

        Returns:
            UnifiedLazyFrame with single row of means
        """
        if _is_pyspark_df(self._df):
            from pyspark.sql import functions as F  # noqa: N812

            mean_exprs = [F.avg(F.col(c)).alias(c) for c in self._df.columns]
            result = self._df.agg(*mean_exprs)
        elif _is_polars_df(self._df):
            result = self._df.mean()
        elif _is_datafusion_df(self._df):
            # DataFusion: Use aggregate() with no group columns
            from datafusion import col as df_col, functions as df_f

            schema_fields = [field.name for field in self._df.schema()]
            mean_exprs = [df_f.avg(df_col(c)).alias(c) for c in schema_fields]
            result = self._df.aggregate([], mean_exprs)
        else:
            result = self._df.mean()

        return UnifiedLazyFrame(result, self._adapter)

    # =========================================================================
    # Unique/Distinct Operations
    # =========================================================================

    def unique(self, subset: str | list[str] | None = None) -> UnifiedLazyFrame:
        """Get unique rows.

        Provides unified unique/distinct:
        - Polars: Uses unique()
        - PySpark: Uses distinct() or dropDuplicates()
        - DataFusion: Uses distinct() (subset not supported)

        Args:
            subset: Column(s) to consider for uniqueness (optional)

        Returns:
            UnifiedLazyFrame with unique rows
        """
        if _is_pyspark_df(self._df):
            if subset is not None:
                # PySpark: Use dropDuplicates with columns
                cols = [subset] if isinstance(subset, str) else list(subset)
                result = self._df.dropDuplicates(cols)
            else:
                result = self._df.distinct()
        elif _is_polars_df(self._df):
            result = self._df.unique(subset=subset) if subset is not None else self._df.unique()
        elif _is_datafusion_df(self._df):
            # DataFusion: Uses ROW_NUMBER dedup for subset (select+distinct drops non-subset columns)
            if subset is not None:
                from datafusion import col as df_col, functions as df_f, lit as df_lit
                from datafusion.expr import Window, WindowFrame

                cols = [subset] if isinstance(subset, str) else list(subset)
                partition_exprs = [df_col(c) for c in cols]
                # Pick an arbitrary column for ordering to make ROW_NUMBER deterministic
                all_cols = [field.name for field in self._df.schema()]
                order_col = df_col(all_cols[0]).sort(ascending=True)
                window_frame = WindowFrame("rows", None, None)
                rn_expr = df_f.row_number().over(
                    Window(partition_by=partition_exprs, order_by=[order_col], window_frame=window_frame)
                )
                result = (
                    self._df.with_column("__dedup_rn__", rn_expr)
                    .filter(df_col("__dedup_rn__") == df_lit(1))
                    .drop("__dedup_rn__")
                )
            else:
                result = self._df.distinct()
        else:
            # Fallback
            result = self._df.unique(subset=subset) if subset is not None else self._df.unique()

        return UnifiedLazyFrame(result, self._adapter)

    def distinct(self) -> UnifiedLazyFrame:
        """Alias for unique() without subset."""
        return self.unique()

    # =========================================================================
    # Sorting Operations
    # =========================================================================

    def sort(
        self,
        by: str | list[str] | list[tuple[str, str]],
        *more_columns: str,
        descending: bool | list[bool] = False,
        nulls_last: bool = False,
    ) -> UnifiedLazyFrame:
        """Sort by columns.

        Provides unified sorting:
        - Polars: Uses sort()
        - PySpark: Uses orderBy() with asc()/desc() and nulls_first()/nulls_last()

        Supports multiple calling styles:
        - `.sort("col1", "col2")` - positional columns
        - `.sort(["col1", "col2"], descending=[True, False])` - list with desc flags
        - `.sort([("col1", "desc"), ("col2", "asc")])` - tuple (column, direction) syntax

        Args:
            by: First column or list of columns to sort by
            *more_columns: Additional columns to sort by (positional)
            descending: Whether to sort descending (per column)
            nulls_last: Whether to put NULL values last (default: False)

        Returns:
            UnifiedLazyFrame with sorted rows
        """
        cols, desc_flags = _normalize_sort_inputs(by, more_columns, descending)

        if _is_pyspark_df(self._df):
            result = _sort_pyspark(self._df, cols, desc_flags, nulls_last)
        elif _is_polars_df(self._df):
            unwrapped_cols = [c.native if isinstance(c, UnifiedExpr) else c for c in cols]
            result = self._df.sort(unwrapped_cols, descending=desc_flags, nulls_last=nulls_last)
        elif _is_datafusion_df(self._df):
            result = _sort_datafusion(self._df, cols, desc_flags, nulls_last)
        else:
            unwrapped_cols = [c.native if isinstance(c, UnifiedExpr) else c for c in cols]
            result = self._df.sort(unwrapped_cols, descending=desc_flags)

        return UnifiedLazyFrame(result, self._adapter)

    # =========================================================================
    # Limit/Head Operations
    # =========================================================================

    def limit(self, n: int) -> UnifiedLazyFrame:
        """Limit to first n rows.

        Args:
            n: Number of rows

        Returns:
            UnifiedLazyFrame with limited rows
        """
        result = self._df.limit(n)
        return UnifiedLazyFrame(result, self._adapter)

    def head(self, n: int = 10) -> UnifiedLazyFrame:
        """Get first n rows (alias for limit)."""
        return self.limit(n)

    # =========================================================================
    # Rename Operations
    # =========================================================================

    def rename(self, mapping: dict[str, str]) -> UnifiedLazyFrame:
        """Rename columns.

        Args:
            mapping: Dict mapping old names to new names

        Returns:
            UnifiedLazyFrame with renamed columns
        """
        if _is_pyspark_df(self._df):
            # PySpark: Use withColumnRenamed
            result = self._df
            for old_name, new_name in mapping.items():
                if old_name in result.columns:
                    result = result.withColumnRenamed(old_name, new_name)
        elif _is_polars_df(self._df):
            # Polars: Use rename
            result = self._df.rename(mapping)
        elif _is_datafusion_df(self._df):
            # DataFusion: Use with_column_renamed for each column
            result = self._df
            for old_name, new_name in mapping.items():
                result = result.with_column_renamed(old_name, new_name)
        else:
            # Fallback: try rename
            result = self._df.rename(mapping)

        return UnifiedLazyFrame(result, self._adapter)

    # =========================================================================
    # Explode/Unnest
    # =========================================================================

    def explode(self, column: str) -> UnifiedLazyFrame:
        """Explode a list column into separate rows.

        Each element in the list becomes its own row, with all other columns duplicated.

        Args:
            column: Name of the list-typed column to explode

        Returns:
            UnifiedLazyFrame with exploded rows
        """
        if _is_pyspark_df(self._df):
            from pyspark.sql import functions as F  # noqa: N812

            # PySpark: select all columns, replacing the list column with exploded version
            result = self._df.withColumn(column, F.explode(F.col(column)))
        elif _is_polars_df(self._df):
            result = self._df.explode(column)
        elif _is_datafusion_df(self._df):
            result = self._df.unnest_columns(column)
        else:
            # Fallback
            result = self._df.explode(column)

        return UnifiedLazyFrame(result, self._adapter)

    # =========================================================================
    # Union / Stack Operations
    # =========================================================================

    def vstack(self, other: UnifiedLazyFrame) -> UnifiedLazyFrame:
        """Vertically stack (UNION ALL) another DataFrame.

        Args:
            other: DataFrame to stack below this one

        Returns:
            UnifiedLazyFrame with rows from both DataFrames
        """
        other_df = other._df if isinstance(other, UnifiedLazyFrame) else other
        if _is_datafusion_df(self._df):
            result = self._df.union(other_df)
        elif _is_polars_df(self._df):
            import polars as pl

            result = pl.concat([self._df, other_df])
        elif _is_pyspark_df(self._df):
            result = self._df.unionAll(other_df)
        else:
            result = self._df.union(other_df)
        return UnifiedLazyFrame(result, self._adapter)

    # =========================================================================
    # Melt / Unpivot Operations
    # =========================================================================

    def melt(
        self,
        id_vars: list[str],
        value_vars: list[str],
        variable_name: str = "variable",
        value_name: str = "value",
    ) -> UnifiedLazyFrame:
        """Unpivot (melt) columns into rows.

        Converts wide format to long format by turning value_vars columns into rows.

        Args:
            id_vars: Columns to keep as identifiers
            value_vars: Columns to unpivot into rows
            variable_name: Name for the variable column
            value_name: Name for the value column

        Returns:
            UnifiedLazyFrame in long format
        """
        if _is_polars_df(self._df):
            result = self._df.unpivot(
                on=value_vars,
                index=id_vars,
                variable_name=variable_name,
                value_name=value_name,
            )
        elif _is_pyspark_df(self._df):
            # PySpark: use stack() expression
            from pyspark.sql import functions as F  # noqa: N812

            stack_args = [F.lit(len(value_vars))]
            for var in value_vars:
                stack_args.extend([F.lit(var), F.col(var)])
            stack_expr = F.expr(
                f"stack({len(value_vars)}, "
                + ", ".join(f"'{v}', `{v}`" for v in value_vars)
                + f") as ({variable_name}, {value_name})"
            )
            result = self._df.select(*id_vars, stack_expr)
        elif _is_datafusion_df(self._df):
            # DataFusion: implement as UNION ALL of per-variable selections
            import pyarrow as pa
            from datafusion import col as df_col, lit as df_lit

            frames = []
            for var in value_vars:
                select_exprs = [df_col(c) for c in id_vars]
                select_exprs.append(df_lit(var).alias(variable_name))
                select_exprs.append(df_col(var).cast(pa.float64()).alias(value_name))
                frames.append(self._df.select(*select_exprs))
            result = frames[0]
            for frame in frames[1:]:
                result = result.union(frame)
        else:
            result = self._df.melt(
                id_vars=id_vars,
                value_vars=value_vars,
                variable_name=variable_name,
                value_name=value_name,
            )
        return UnifiedLazyFrame(result, self._adapter)

    # =========================================================================
    # Collect/Materialize
    # =========================================================================

    def collect(self) -> Any:
        """Collect/materialize the lazy DataFrame.

        Returns:
            Materialized DataFrame (platform-specific type):
            - Polars: Polars DataFrame
            - PySpark: PySpark DataFrame
            - DataFusion: PyArrow Table (from collected batches)

        Escape-hatch `Any`: each backend returns its own materialized type.
        Narrowing to a union (`polars.DataFrame | pyspark.sql.DataFrame |
        pyarrow.Table`) would force optional-dep imports at type-check time
        without giving callers a useful common surface - they have to
        backend-narrow before consuming anyway.
        """
        if _is_pyspark_df(self._df):
            # PySpark DataFrames are already materialized on action
            return self._df
        elif _is_polars_df(self._df):
            # Polars: collect LazyFrame
            if hasattr(self._df, "collect"):
                return self._df.collect()
            return self._df
        elif _is_datafusion_df(self._df):
            # DataFusion: collect() returns list of RecordBatches, convert to Table
            import pyarrow as pa

            batches = self._df.collect()
            if not batches:
                return pa.table({})
            return pa.Table.from_batches(batches)
        else:
            # Fallback
            if hasattr(self._df, "collect"):
                return self._df.collect()
            return self._df

    def collect_column_as_list(self, column: str) -> list:
        """Collect a single column as a Python list.

        This is a platform-agnostic way to extract column values:
        - Polars: Uses .to_series().to_list()
        - PySpark: Uses .select(col).rdd.flatMap(lambda x: x).collect()
        - DataFusion: Uses collect() -> PyArrow batches -> to_pandas()

        Args:
            column: Column name to extract

        Returns:
            List of values from the column
        """
        if _is_pyspark_df(self._df):
            # PySpark: collect column values
            return [row[column] for row in self._df.select(column).collect()]
        elif _is_polars_df(self._df):
            # Polars: collect and convert to list
            collected = self._df.collect() if hasattr(self._df, "collect") else self._df
            return collected[column].to_list()
        elif _is_datafusion_df(self._df):
            # DataFusion: collect() returns list of RecordBatches
            import pyarrow as pa

            batches = self._df.collect()
            if not batches:
                return []
            combined = pa.Table.from_batches(batches)
            return combined.to_pandas()[column].tolist()
        else:
            # Fallback for other platforms
            collected = self._df.collect() if hasattr(self._df, "collect") else self._df
            if hasattr(collected, "to_pandas"):
                return collected.to_pandas()[column].tolist()
            return list(collected[column])

    def scalar(self, row: int = 0, col: int = 0) -> Any:
        """Extract a single scalar value from the DataFrame.

        Platform-agnostic way to extract a value from a single-row result:
        - Polars: Uses collect()[row, col] NumPy-style indexing
        - PySpark: Uses collect()[row][col] list indexing
        - DataFusion: Uses collect() -> PyArrow batches -> to_pandas().iloc

        Args:
            row: Row index (default 0)
            col: Column index (default 0)

        Returns:
            The scalar value at the specified position. Escape-hatch `Any`
            because the backing column can hold any SQL-typed value
            (int / float / Decimal / str / bytes / date / None / nested
            struct). Caller knows their column's type from context.
        """
        if _is_pyspark_df(self._df):
            # PySpark: collect returns list of Row objects
            rows = self._df.collect()
            if not rows:
                return None
            return rows[row][col]
        elif _is_polars_df(self._df):
            # Polars: collect returns DataFrame with NumPy-style indexing
            collected = self._df.collect() if hasattr(self._df, "collect") else self._df
            return collected[row, col]
        elif _is_datafusion_df(self._df):
            # DataFusion: collect() returns list of RecordBatches
            import pyarrow as pa

            batches = self._df.collect()
            if not batches:
                return None
            combined = pa.Table.from_batches(batches)
            return combined.to_pandas().iloc[row, col]
        else:
            # Fallback for other platforms
            collected = self._df.collect() if hasattr(self._df, "collect") else self._df
            if hasattr(collected, "to_pandas"):
                return collected.to_pandas().iloc[row, col]
            return collected[row, col]

    # =========================================================================
    # Drop Operations
    # =========================================================================

    def drop(self, *columns: str) -> UnifiedLazyFrame:
        """Drop columns from the DataFrame.

        Args:
            *columns: Column names to drop

        Returns:
            UnifiedLazyFrame without the specified columns
        """
        # All platforms use the same .drop() API
        result = self._df.drop(*columns)
        return UnifiedLazyFrame(result, self._adapter)


def wrap_dataframe(df: LazyFrameLike, adapter: ExpressionFamilyAdapter) -> UnifiedLazyFrame:
    """Wrap a native DataFrame in a UnifiedLazyFrame.

    Args:
        df: Native DataFrame (Polars, PySpark, DataFusion)
        adapter: The parent adapter

    Returns:
        UnifiedLazyFrame wrapper
    """
    return UnifiedLazyFrame(df, adapter)
