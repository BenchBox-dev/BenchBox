"""ROLLUP expansion helper for TPC-DS DataFrame queries.

This module provides utilities to expand SQL ROLLUP/CUBE GROUP BY patterns
into equivalent DataFrame operations using multiple GROUP BY aggregations
and UNION ALL.

ROLLUP(a, b, c) produces grouping sets:
- (a, b, c)     - Full detail
- (a, b)        - c rolled up (NULL)
- (a)           - b, c rolled up
- ()            - Grand total (all rolled up)

The helper handles:
- Expanding ROLLUP into multiple GROUP BY operations
- Computing GROUPING() function equivalents
- Unioning results with proper NULL handling

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


def expand_rollup_expression(
    df: Any,
    group_cols: list[str],
    agg_exprs: list[Any],
    ctx: Any,
) -> Any:
    """Expand ROLLUP into multiple GROUP BYs for expression-family DataFrames.

    This handles ROLLUP expansion for Polars and other expression-based libraries.

    ROLLUP(a, b, c) expands to:
    - GROUP BY a, b, c  (grouping_id = 0)
    - GROUP BY a, b     (grouping_id = 1, c = NULL)
    - GROUP BY a        (grouping_id = 3, b = c = NULL)
    - GROUP BY ()       (grouping_id = 7, a = b = c = NULL, grand total)

    Args:
        df: Input LazyFrame/DataFrame
        group_cols: Columns to include in ROLLUP (order matters)
        agg_exprs: List of aggregation expressions
        ctx: DataFrameContext for platform-specific operations

    Returns:
        Combined DataFrame with all rollup levels
    """
    from benchbox.platforms.dataframe.unified_frame import UnifiedExpr, UnifiedLazyFrame

    lit = ctx.lit
    results = []
    n = len(group_cols)

    def get_output_name(expr: Any) -> str:
        """Get the alias/output name from an aggregation expression."""
        # Unwrap UnifiedExpr if needed
        native = expr.native if isinstance(expr, UnifiedExpr) else expr
        # Polars - use meta.output_name()
        if hasattr(native, "meta") and hasattr(native.meta, "output_name"):
            try:
                return native.meta.output_name()
            except Exception:
                pass
        # PySpark - extract from string representation
        if hasattr(native, "_jc"):
            try:
                name = str(native._jc.toString())
                # Extract alias name: "foo AS bar" -> "bar" or just "foo"
                if " AS " in name:
                    return name.split(" AS ")[-1].strip("`")
                return name.strip("`")
            except Exception:
                pass
        # Fallback
        return f"agg_{id(expr)}"

    agg_col_names = [get_output_name(e) for e in agg_exprs]

    for i in range(n + 1):
        # Columns to group by at this level
        current_group = group_cols[: n - i]

        # Perform aggregation - use *args not list
        # Grand total (empty group) uses select for aggregation
        grouped = df.group_by(*current_group).agg(*agg_exprs) if current_group else df.select(*agg_exprs)

        # Add NULL for rolled-up columns
        rolled_up_cols = group_cols[n - i :]
        for null_col in rolled_up_cols:
            grouped = grouped.with_columns(lit(None).alias(null_col))

        # Compute grouping_id: sum of 2^position for each rolled-up column
        # This matches SQL GROUPING() function behavior
        grouping_id = sum(2**j for j in range(i))
        grouped = grouped.with_columns(lit(grouping_id).alias("grouping_id"))

        # Reorder columns to consistent layout (if column ordering fails, continue with current layout)
        all_cols = group_cols + agg_col_names + ["grouping_id"]
        with contextlib.suppress(Exception):
            # Use *args for UnifiedLazyFrame, list for native
            grouped = grouped.select(*all_cols) if isinstance(grouped, UnifiedLazyFrame) else grouped.select(all_cols)

        results.append(grouped)

    # Union all levels
    return ctx.concat(results)


def expand_rollup_pandas(
    df: Any,
    group_cols: list[str],
    agg_dict: dict[str, tuple[str, str]],
    ctx: Any,
) -> Any:
    """Expand ROLLUP into multiple GROUP BYs for pandas-family DataFrames.

    This handles ROLLUP expansion for Pandas and Dask, and similar libraries.

    Args:
        df: Input DataFrame (may be UnifiedPandasFrame or native)
        group_cols: Columns to include in ROLLUP (order matters)
        agg_dict: Dictionary mapping output column names to (input_col, agg_func) tuples
                  Example: {"sum_sales": ("sales", "sum"), "avg_qty": ("qty", "mean")}
        ctx: DataFrameContext for platform-specific operations

    Returns:
        Combined DataFrame with all rollup levels
    """
    from benchbox.platforms.dataframe.unified_pandas_frame import UnifiedPandasFrame

    # Unwrap if needed for internal operations
    native_df = df._df if isinstance(df, UnifiedPandasFrame) else df

    # Get adapter for platform-specific operations (handles Dask as_index=False)
    adapter = ctx._adapter if hasattr(ctx, "_adapter") else None

    results = []
    n = len(group_cols)

    for i in range(n + 1):
        # Columns to group by at this level
        current_group = group_cols[: n - i]

        # Perform aggregation
        if current_group:
            # Build pandas-style aggregation
            agg_spec = {out_col: (in_col, func) for out_col, (in_col, func) in agg_dict.items()}
            # Use adapter's groupby_agg which handles Dask's lack of as_index support
            if adapter is not None:
                grouped = adapter.groupby_agg(native_df, current_group, agg_spec, as_index=False)
            else:
                # Fallback for non-pandas contexts (shouldn't happen in practice)
                grouped = native_df.groupby(current_group, as_index=False).agg(**agg_spec)
        else:
            # Grand total - aggregate entire DataFrame
            # For Dask, we need to compute scalars differently
            result_data = {}
            for out_col, (in_col, func) in agg_dict.items():
                col_data = native_df[in_col]
                if func == "sum":
                    val = col_data.sum()
                elif func == "mean":
                    val = col_data.mean()
                elif func == "count":
                    val = col_data.count()
                elif func == "min":
                    val = col_data.min()
                elif func == "max":
                    val = col_data.max()
                else:
                    val = getattr(col_data, func)()
                # Compute if Dask scalar
                if hasattr(val, "compute"):
                    val = val.compute()
                result_data[out_col] = [val]

            # Create a single-row DataFrame using pandas
            import pandas as pd

            grouped = pd.DataFrame(result_data)

        # Add NULL for rolled-up columns
        rolled_up_cols = group_cols[n - i :]
        for null_col in rolled_up_cols:
            grouped[null_col] = None

        # Compute grouping_id
        grouping_id = sum(2**j for j in range(i))
        grouped["grouping_id"] = grouping_id

        results.append(grouped)

    # Union all levels using ctx.concat for platform compatibility
    return ctx.concat(results)


def compute_grouping_function(
    df: Any,
    grouping_id_col: str,
    column_position: int,
) -> Any:
    """Compute the equivalent of SQL GROUPING() function.

    In SQL, GROUPING(col) returns 1 if the column is rolled up (NULL due to
    ROLLUP), 0 otherwise. This is based on bit positions in the grouping_id.

    Args:
        df: DataFrame with grouping_id column
        grouping_id_col: Name of the grouping_id column
        column_position: Position of the column in the ROLLUP list (0-indexed)

    Returns:
        Expression/Series that is 1 if column is rolled up, 0 otherwise
    """
    # The grouping_id encodes which columns are rolled up as bit flags
    # For position 0: bit 0 (value 1)
    # For position 1: bit 1 (value 2)
    # etc.
    bit_value = 2**column_position

    try:
        import polars as pl

        return (pl.col(grouping_id_col) & bit_value) / bit_value
    except ImportError:
        pass

    # For pandas, this would be applied to a DataFrame column
    return lambda gid: (gid & bit_value) // bit_value


def lochierarchy_expression(
    grouping_id_col: str,
    num_cols: int,
    ctx: Any = None,
) -> Any:
    """Compute lochierarchy value used in TPC-DS Q36.

    lochierarchy = GROUPING(col1) + GROUPING(col2) + ...

    This counts how many columns are rolled up at each level.

    Args:
        grouping_id_col: Name of the grouping_id column
        num_cols: Number of columns in the ROLLUP
        ctx: Optional DataFrameContext for platform-specific operations.
             If provided, returns a UnifiedExpr that works across platforms.

    Returns:
        Expression for lochierarchy (UnifiedExpr if ctx provided, else platform-specific)
    """
    # If ctx is provided, use it for platform-agnostic expression building
    if ctx is not None:
        from benchbox.platforms.dataframe.unified_frame import UnifiedExpr

        col_expr = ctx.col(grouping_id_col)
        bit_count = ctx.lit(0)

        # Build expression to count bits
        # For small numbers (< 8 columns), we can use bit math
        for i in range(num_cols):
            # (col & 2^i) / 2^i gives 1 if bit is set, 0 otherwise
            bit_val = 2**i
            bit_expr = (col_expr & bit_val) / bit_val

            # Cast to integer for proper addition
            # Use platform-specific int type
            if hasattr(col_expr, "_is_pyspark") and col_expr._is_pyspark:
                from pyspark.sql.types import IntegerType

                bit_expr = bit_expr.cast(IntegerType())
            else:
                try:
                    import polars as pl

                    bit_expr = bit_expr.cast(pl.Int32)
                except ImportError:
                    pass

            bit_count = bit_count + bit_expr

        # Ensure result is UnifiedExpr
        if isinstance(bit_count, UnifiedExpr):
            return bit_count
        return UnifiedExpr(bit_count)

    # Legacy path: try Polars directly (for backwards compatibility)
    try:
        import polars as pl

        # Count number of set bits in grouping_id
        # For 2 columns: grouping_id can be 0, 1, 2, or 3
        # lochierarchy is the popcount (number of 1 bits)
        col = pl.col(grouping_id_col)

        # Build expression to count bits
        # For small numbers (< 8 columns), we can use bit math
        bit_count = pl.lit(0)
        for i in range(num_cols):
            bit_count = bit_count + ((col & (2**i)) / (2**i)).cast(pl.Int32)
        return bit_count
    except ImportError:
        pass

    # For pandas, return a function to apply
    def count_bits(gid: int) -> int:
        return bin(gid).count("1")

    return count_bits
