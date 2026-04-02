"""Read Primitives DataFrame queries for Expression and Pandas families.

This module provides DataFrame implementations of Read Primitives benchmark queries
that can run on both expression-based (Polars, PySpark, DataFusion) and
Pandas-like (Pandas, Modin, Dask) platforms.

Read Primitives is a microbenchmark testing isolated database operations using
the TPC-H schema. Unlike full TPC-H queries, these focus on single operations
to enable granular performance analysis:

Categories implemented:
- aggregation: COUNT, SUM, AVG, COUNT DISTINCT, GROUP BY operations
- filter: WHERE clauses, predicate pushdown, selectivity testing
- groupby: GROUP BY ALL, ROLLUP, CUBE operations
- orderby: Sorting, TOP-N, ORDER BY ALL
- shuffle: Data redistribution patterns
- string: LIKE, CONCAT, SUBSTRING, string functions
- predicate: Predicate ordering by selectivity
- window: ROW_NUMBER, RANK, LAG/LEAD, aggregate windows
- qualify: QUALIFY clause for window filtering (expression-family only)
- array: ARRAY operations, UNNEST, array aggregations
- broadcast: Small table broadcast joins
- exchange: Data redistribution patterns

Note: Optimizer queries (13 queries testing SQL optimizer behavior) are
SQL-only and not implemented for DataFrame platforms, as they test query
planning behavior which doesn't apply to DataFrame execution.

Each query is implemented using the DataFrameQuery class with separate
implementations for each family:
- expression_impl: Uses ctx.col(), ctx.lit() for lazy expression building
- pandas_impl: Uses string column access and boolean indexing

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory, QueryRegistry

if TYPE_CHECKING:
    from benchbox.core.dataframe.context import DataFrameContext


# =============================================================================
# Query IDs that should be skipped for DataFrame implementations
# =============================================================================
#
# IMPORTANT: Most "SQL-only" features ARE implementable via DataFrames:
# - Optimizer probes: Spark DataFrames are DECLARATIVE - Catalyst optimizes them
# - CUBE/ROLLUP: Use multiple groupby + union (or native cube/rollup in PySpark)
# - QUALIFY: Use window function + filter (two-step approach)
# - Arrays/Structs/Maps: Native support in Polars and PySpark
# - Higher-order functions: F.transform(), F.filter(), F.aggregate() in PySpark
# - Pivot/Unpivot: Native pivot/melt in all DataFrame libraries
#
# Only truly SQL-only constructs are correlated subqueries where the inner query
# references the outer query's row values - this has no DataFrame equivalent.

SKIP_FOR_DATAFRAME = [
    # Correlated EXISTS subquery - inner query references outer row
    # SQL: WHERE EXISTS (SELECT 1 FROM t2 WHERE t2.key = t1.key AND ...)
    # No DataFrame equivalent - requires per-row subquery execution
    "optimizer_exists_to_semijoin",
    # Correlated IN subquery - inner query references outer row
    # SQL: WHERE col IN (SELECT t2.col FROM t2 WHERE t2.key = t1.key)
    # No DataFrame equivalent - requires per-row subquery execution
    "optimizer_in_to_exists",
    # Correlated scalar subquery - inner query returns single value per outer row
    # SQL: SELECT (SELECT MAX(x) FROM t2 WHERE t2.key = t1.key) FROM t1
    # No DataFrame equivalent - requires per-row subquery execution
    "optimizer_scalar_subquery_flattening",
]

# NOTE: EXPRESSION_FAMILY_ONLY list has been removed.
#
# All queries now support both expression-family (Polars, PySpark, DataFusion)
# and pandas-family (Pandas, Modin, cuDF, Dask) implementations.
#
# Queries previously in this list have valid pandas-family implementations:
# - QUALIFY queries: Use window + filter pattern (add window col, then filter)
# - Higher-order functions: Use .apply() with lambdas
# - Array operations: Use .explode(), list comprehensions
# - Struct/Map operations: Use dict/list operations
# - Timeseries/ASOF: Use pd.merge_asof() or window-based approximation
# - Optimizer probes: DataFrames are declarative, Catalyst optimizes plans

# Queries skipped for expression-family platforms (Polars, PySpark, DataFusion).
#
# Most list/array, struct, and string-split queries are now supported through
# the unified expression API (UnifiedListExpr, UnifiedMapExpr, UnifiedStrExpr).
#
# Only map queries remain skipped because Polars has no native Map dtype.
# PySpark and DataFusion support these via F.map_from_entries() and
# f.map_from_entries() respectively, but the expression_impl functions call
# ctx.map_from_entries() which raises NotImplementedError on Polars.
SKIP_FOR_EXPRESSION_FAMILY = [
    # --- Map operations: Polars has no native Map dtype ---
    "map_construction",  # ctx.struct() + ctx.map_from_entries()
    "map_access",  # ctx.struct() + ctx.map_from_entries() + .map.get()
    "map_keys_values",  # ctx.struct() + ctx.map_from_entries() + .map.keys/values()
]

# Queries skipped specifically for DataFusion DataFrame mode.
# These use Polars-only features or DataFusion v50 missing functions.
SKIP_FOR_DATAFUSION = [
    "list_filter",  # .list.eval() is Polars-only — no DataFusion equivalent
    "list_transform",  # .list.eval() is Polars-only — no DataFusion equivalent
    "list_reduce",  # array_sum() not in DataFusion v50 Python bindings
    "array_distinct",  # DataFusion array_distinct returns Dictionary(Int32,Utf8) causing Arrow type mismatch
]


# =============================================================================
# Expression Family Implementations (Polars, PySpark, DataFusion)
# =============================================================================


def aggregation_distinct_expression_impl(ctx: DataFrameContext) -> Any:
    """Distinct count of high cardinality key on a large table."""
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    result = orders.filter(col("o_orderdate") >= lit(date(1995, 1, 1))).select(
        col("o_custkey").n_unique().alias("unique_customers")
    )

    return result


def aggregation_groupby_impl(
    ctx: DataFrameContext,
    *,
    table_name: str,
    group_cols: tuple[str, ...],
    agg_specs: tuple[tuple[str, str, str], ...],
) -> Any:
    """Run a grouped aggregation for either expression-family or pandas-family contexts."""
    table = ctx.get_table(table_name)
    group_columns = list(group_cols)

    if hasattr(table, "group_by"):
        col = ctx.col
        expression_builders = {
            "nunique": lambda column: column.n_unique(),
            "sum": lambda column: column.sum(),
            "mean": lambda column: column.mean(),
            "count": lambda column: column.count(),
            "max": lambda column: column.max(),
        }
        return table.group_by(*group_columns).agg(
            *(
                expression_builders[agg_func](col(column_name)).alias(alias)
                for column_name, agg_func, alias in agg_specs
            )
        )

    if hasattr(table, "groupby"):
        return table.groupby(group_columns, as_index=False).agg(
            **{alias: (column_name, agg_func) for column_name, agg_func, alias in agg_specs}
        )

    raise TypeError(f"Unsupported table type for grouped aggregation: {type(table)!r}")


def aggregation_distinct_groupby_expression_impl(ctx: DataFrameContext) -> Any:
    """Distinct count of high cardinality keys in low cardinality groups."""
    return aggregation_groupby_impl(
        ctx,
        table_name="lineitem",
        group_cols=("l_returnflag", "l_linestatus"),
        agg_specs=(
            ("l_orderkey", "nunique", "unique_orders"),
            ("l_partkey", "nunique", "unique_parts"),
        ),
    )


def aggregation_groupby_large_expression_impl(ctx: DataFrameContext) -> Any:
    """Aggregates within high cardinality grouping."""
    return aggregation_groupby_impl(
        ctx,
        table_name="lineitem",
        group_cols=("l_orderkey", "l_partkey", "l_suppkey"),
        agg_specs=(
            ("l_quantity", "sum", "total_qty"),
            ("l_extendedprice", "mean", "avg_price"),
        ),
    )


def aggregation_groupby_small_expression_impl(ctx: DataFrameContext) -> Any:
    """Aggregates within low cardinality grouping."""
    return aggregation_groupby_impl(
        ctx,
        table_name="nation",
        group_cols=("n_regionkey",),
        agg_specs=(
            ("n_nationkey", "count", "nation_count"),
            ("n_name", "max", "last_nation"),
        ),
    )


def aggregation_materialize_expression_impl(ctx: DataFrameContext) -> Any:
    """Nested aggregation requiring CTE materialization."""
    orders = ctx.get_table("orders")
    col = ctx.col

    # First aggregation: sum by customer
    order_totals = orders.group_by("o_custkey").agg(col("o_totalprice").sum().alias("customer_total"))

    # Second aggregation: average of customer totals
    result = order_totals.select(col("customer_total").mean().alias("avg_customer_spending"))

    return result


def aggregation_materialize_subquery_expression_impl(ctx: DataFrameContext) -> Any:
    """Complex nested aggregation requiring materialization of a subquery with joins."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    # Build joined data with order totals
    order_totals = (
        customer.join(orders, left_on="c_custkey", right_on="o_custkey")
        .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .group_by("c_mktsegment", "o_orderkey")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("order_total"))
    )

    # Average by segment
    result = order_totals.group_by("c_mktsegment").agg(col("order_total").mean().alias("avg_segment_order"))

    return result


def aggregation_partition_expression_impl(ctx: DataFrameContext) -> Any:
    """Aggregates over the partition key."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineitem.filter((col("l_shipdate") >= lit(date(1995, 1, 1))) & (col("l_shipdate") < lit(date(1996, 1, 1))))
        .group_by("l_shipdate", "l_shipmode")
        .agg(
            col("l_quantity").sum().alias("daily_quantity"),
            col("l_orderkey").count().alias("shipment_count"),
        )
    )

    return result


def aggregation_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """Aggregate on a small subset of rows."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    result = lineitem.filter((col("l_discount") > lit(0.05)) & (col("l_quantity") < lit(24))).select(
        (col("l_extendedprice") * col("l_discount")).sum().alias("total_discount_amount")
    )

    return result


def aggregation_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Aggregate over all rows in table."""
    orders = ctx.get_table("orders")
    col = ctx.col

    result = orders.select(
        col("o_orderkey").count().alias("total_orders"),
        col("o_totalprice").sum().alias("total_revenue"),
    )

    return result


def filter_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """High selectivity filter - few rows match."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    result = lineitem.filter(
        (col("l_quantity") > lit(45)) & (col("l_extendedprice") > lit(50000)) & (col("l_discount") < lit(0.05))
    ).select("l_orderkey", "l_partkey", "l_quantity", "l_extendedprice")

    return result


def filter_non_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """Low selectivity filter - many rows match."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    result = lineitem.filter(col("l_quantity") > lit(1)).select(
        "l_orderkey", "l_partkey", "l_quantity", "l_extendedprice"
    )

    return result


def count_star_expression_impl(ctx: DataFrameContext) -> Any:
    """Metadata-based count optimization vs full table scan performance."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    result = lineitem.select(col("l_orderkey").count().alias("total_lineitems"))

    return result


def decimal_arithmetic_expression_impl(ctx: DataFrameContext) -> Any:
    """Decimal precision arithmetic with complex expressions."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineitem.filter(col("l_quantity") > lit(0))
        .select(
            col("l_orderkey"),
            (col("l_extendedprice") * (lit(1) - col("l_discount")) * (lit(1) + col("l_tax"))).alias("final_price"),
            (col("l_extendedprice") / col("l_quantity")).alias("unit_price"),
        )
        .limit(1000)
    )

    return result


def orderby_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Simple ORDER BY single column."""
    orders = ctx.get_table("orders")

    result = orders.select("o_orderkey", "o_orderdate", "o_totalprice").sort("o_orderdate").limit(100)

    return result


def orderby_multi_expression_impl(ctx: DataFrameContext) -> Any:
    """ORDER BY multiple columns."""
    lineitem = ctx.get_table("lineitem")

    result = (
        lineitem.select("l_orderkey", "l_linenumber", "l_shipdate", "l_quantity")
        .sort(["l_shipdate", "l_orderkey", "l_linenumber"])
        .limit(100)
    )

    return result


def orderby_desc_expression_impl(ctx: DataFrameContext) -> Any:
    """ORDER BY with descending sort."""
    orders = ctx.get_table("orders")

    result = orders.select("o_orderkey", "o_totalprice", "o_orderdate").sort("o_totalprice", descending=True).limit(100)

    return result


def topn_expression_impl(ctx: DataFrameContext) -> Any:
    """Top-N query with ORDER BY and LIMIT."""
    lineitem = ctx.get_table("lineitem")

    result = (
        lineitem.select("l_orderkey", "l_partkey", "l_extendedprice").sort("l_extendedprice", descending=True).limit(10)
    )

    return result


def limit_expression_impl(ctx: DataFrameContext) -> Any:
    """Simple LIMIT without ORDER BY."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem.select("l_orderkey", "l_partkey", "l_suppkey", "l_quantity").limit(1000)

    return result


def string_like_expression_impl(ctx: DataFrameContext) -> Any:
    """String LIKE pattern matching."""
    part = ctx.get_table("part")
    col = ctx.col

    result = part.filter(col("p_name").str.contains("blue")).select("p_partkey", "p_name", "p_type")

    return result


def string_starts_with_expression_impl(ctx: DataFrameContext) -> Any:
    """String starts_with pattern matching."""
    part = ctx.get_table("part")
    col = ctx.col

    result = part.filter(col("p_type").str.starts_with("STANDARD")).select("p_partkey", "p_name", "p_type")

    return result


def string_ends_with_expression_impl(ctx: DataFrameContext) -> Any:
    """String ends_with pattern matching."""
    part = ctx.get_table("part")
    col = ctx.col

    result = part.filter(col("p_type").str.ends_with("BRASS")).select("p_partkey", "p_name", "p_type")

    return result


def string_concat_expression_impl(ctx: DataFrameContext) -> Any:
    """String concatenation."""
    customer = ctx.get_table("customer")
    col = ctx.col
    lit = ctx.lit

    result = customer.select(
        col("c_custkey"),
        (col("c_name") + lit(" - ") + col("c_mktsegment")).alias("customer_info"),
    ).limit(100)

    return result


def string_substring_expression_impl(ctx: DataFrameContext) -> Any:
    """String substring extraction."""
    customer = ctx.get_table("customer")
    col = ctx.col

    result = customer.select(
        col("c_custkey"),
        col("c_phone").str.slice(0, 3).alias("country_code"),
    ).limit(100)

    return result


def window_row_number_expression_impl(ctx: DataFrameContext) -> Any:
    """Window function ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    result = (
        lineitem.with_columns(
            ctx.window_row_number(
                order_by=[("l_extendedprice", False)],
                partition_by=["l_orderkey"],
            ).alias("row_num")
        )
        .filter(col("row_num") <= 3)
        .select("l_orderkey", "l_linenumber", "l_extendedprice", "row_num")
    )

    return result


def window_rank_expression_impl(ctx: DataFrameContext) -> Any:
    """Window function RANK() OVER (PARTITION BY ... ORDER BY ...)."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    result = (
        lineitem.with_columns(
            ctx.window_rank(
                order_by=[("l_quantity", False)],
                partition_by=["l_returnflag"],
            ).alias("qty_rank")
        )
        .filter(col("qty_rank") <= 5)
        .select("l_orderkey", "l_returnflag", "l_quantity", "qty_rank")
    )

    return result


def window_sum_expression_impl(ctx: DataFrameContext) -> Any:
    """Window function SUM() OVER (PARTITION BY ...)."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem.with_columns(
        ctx.window_sum("l_extendedprice", partition_by=["l_orderkey"]).alias("order_total")
    ).select("l_orderkey", "l_linenumber", "l_extendedprice", "order_total")

    return result


def window_running_sum_expression_impl(ctx: DataFrameContext) -> Any:
    """Window function SUM() OVER (ORDER BY ...) - cumulative sum."""
    orders = ctx.get_table("orders")

    result = (
        orders.sort("o_orderdate")
        .with_columns(ctx.window_sum("o_totalprice", order_by=[("o_orderdate", True)]).alias("cumulative_revenue"))
        .select("o_orderkey", "o_orderdate", "o_totalprice", "cumulative_revenue")
        .limit(100)
    )

    return result


def broadcast_join_two_tables_expression_impl(ctx: DataFrameContext) -> Any:
    """One small table broadcast to join with one large table."""
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    col = ctx.col

    result = supplier.join(nation, left_on="s_nationkey", right_on="n_nationkey").select(
        col("s_suppkey").count().alias("supplier_count")
    )

    return result


def broadcast_join_three_tables_expression_impl(ctx: DataFrameContext) -> Any:
    """Two small tables broadcast to join with one large table."""
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col

    result = (
        supplier.join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .group_by("r_name", "n_name")
        .agg(col("s_suppkey").count().alias("supplier_count"))
    )

    return result


def predicate_ordering_aggregation_expression_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity for aggregation."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    result = lineitem.filter(
        (col("l_shipdate") >= lit(date(1994, 1, 1)))
        & (col("l_shipdate") < lit(date(1995, 1, 1)))
        & (col("l_discount") >= lit(0.05))
        & (col("l_discount") <= lit(0.07))
        & (col("l_quantity") < lit(24))
    ).select(col("l_extendedprice").sum().alias("total_price"))

    return result


def shuffle_join_expression_impl(ctx: DataFrameContext) -> Any:
    """Data is redistributed based on the join keys."""
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    result = (
        orders.join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .group_by("o_orderkey")
        .agg(col("l_quantity").sum().alias("total_qty"))
    )

    return result


def empty_build_join_expression_impl(ctx: DataFrameContext) -> Any:
    """Join when build side produces no rows (edge case handling)."""
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Create empty orders set (no orders with negative price)
    empty_orders = orders.filter(col("o_totalprice") < lit(0)).select("o_orderkey")

    result = lineitem.join(empty_orders, left_on="l_orderkey", right_on="o_orderkey", how="left").select(
        "l_orderkey", "l_partkey", "l_quantity"
    )

    return result


# -----------------------------------------------------------------------------
# Additional Filter queries
# -----------------------------------------------------------------------------


def filter_bigint_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """Equality predicate with high selectivity on integer column."""
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    result = orders.filter(col("o_orderkey") == lit(1234567)).select(
        "o_orderkey", "o_custkey", "o_orderdate", "o_totalprice"
    )

    return result


def filter_bigint_non_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """Range predicate with low selectivity on large table."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    result = lineitem.filter(col("l_orderkey") > lit(1000)).select(col("l_orderkey").count().alias("count"))

    return result


def filter_bigint_in_list_expression_impl(ctx: DataFrameContext) -> Any:
    """IN-list predicate with highly selective integer values."""
    orders = ctx.get_table("orders")
    col = ctx.col

    result = orders.filter(col("o_orderkey").is_in([1, 100, 1000, 10000, 100000])).select(
        "o_orderkey", "o_custkey", "o_orderdate", "o_totalprice"
    )

    return result


def filter_decimal_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """Compound equality predicate with multiple decimal columns."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    result = lineitem.filter((col("l_extendedprice") == lit(12345.67)) & (col("l_discount") == lit(0.05))).select(
        "l_orderkey", "l_partkey", "l_extendedprice", "l_discount"
    )

    return result


def filter_decimal_non_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """Range predicate on decimal column with low selectivity."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    result = lineitem.filter(col("l_extendedprice") > lit(1000.00)).select(col("l_orderkey").count().alias("count"))

    return result


def filter_string_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """Exact string equality with high selectivity on varchar column."""
    customer = ctx.get_table("customer")
    col = ctx.col
    lit = ctx.lit

    result = customer.filter(col("c_name") == lit("Customer#000001234")).select(
        "c_custkey", "c_name", "c_address", "c_phone"
    )

    return result


def filter_string_non_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """String comparison with low selectivity (most rows match)."""
    customer = ctx.get_table("customer")
    col = ctx.col
    lit = ctx.lit

    result = customer.filter(col("c_mktsegment") >= lit("A")).select(col("c_custkey").count().alias("count"))

    return result


def filter_in_predicate_subquery_expression_impl(ctx: DataFrameContext) -> Any:
    """IN predicate with subquery and selective filtering."""
    part = ctx.get_table("part")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    # Get partkeys with high quantity
    high_qty_parts = lineitem.filter(col("l_quantity") > lit(45)).select("l_partkey").unique()

    result = part.join(high_qty_parts, left_on="p_partkey", right_on="l_partkey", how="semi").select(
        "p_partkey", "p_name", "p_type", "p_size"
    )

    return result


# -----------------------------------------------------------------------------
# Additional GroupBy queries
# -----------------------------------------------------------------------------


def groupby_highndv_expression_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY with high distinct value count (many groups)."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    result = lineitem.group_by("l_orderkey").agg(col("l_linenumber").count().alias("line_count"))

    return result


def groupby_lowndv_expression_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY with low distinct value count (few groups)."""
    orders = ctx.get_table("orders")
    col = ctx.col

    result = orders.group_by("o_orderpriority").agg(col("o_orderkey").count().alias("order_count"))

    return result


def groupby_pk_expression_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY on primary key (one row per group)."""
    customer = ctx.get_table("customer")
    col = ctx.col

    result = customer.group_by("c_custkey").agg(col("c_name").max().alias("customer_name"))

    return result


def groupby_decimal_highndv_expression_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY with high cardinality decimal column."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    result = lineitem.group_by("l_extendedprice").agg(col("l_orderkey").count().alias("price_frequency"))

    return result


def groupby_decimal_lowndv_expression_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY with low cardinality decimal column."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    result = lineitem.group_by("l_discount").agg(
        col("l_orderkey").count().alias("discount_frequency"),
        col("l_quantity").mean().alias("avg_qty"),
    )

    return result


# -----------------------------------------------------------------------------
# Additional OrderBy queries
# -----------------------------------------------------------------------------


def orderby_all_expression_impl(ctx: DataFrameContext) -> Any:
    """Sort on full table with simple integer ordering."""
    customer = ctx.get_table("customer")

    result = customer.sort("c_custkey").select(
        "c_custkey", "c_name", "c_address", "c_nationkey", "c_phone", "c_acctbal", "c_mktsegment"
    )

    return result


def orderby_bigint_expression_impl(ctx: DataFrameContext) -> Any:
    """Sort with aggregation results on integer column."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    result = lineitem.group_by("l_orderkey").agg(col("l_quantity").sum().alias("total_qty")).sort("l_orderkey")

    return result


def orderby_expression_expression_impl(ctx: DataFrameContext) -> Any:
    """Sort on computed expressions with DESC ordering."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    result = (
        lineitem.with_columns((col("l_quantity") * col("l_extendedprice")).alias("total_value"))
        .sort("total_value", descending=True)
        .select("l_orderkey", "l_partkey", "total_value")
        .limit(100)
    )

    return result


def orderby_multicol_expression_impl(ctx: DataFrameContext) -> Any:
    """Complex multi-column sort with string, date, and decimal columns."""
    orders = ctx.get_table("orders")

    result = (
        orders.sort(
            ["o_orderpriority", "o_orderdate", "o_totalprice"],
            descending=[False, True, True],
        )
        .select("o_orderkey", "o_custkey", "o_orderpriority", "o_orderdate", "o_totalprice")
        .limit(100)
    )

    return result


def orderby_shortstrings_expression_impl(ctx: DataFrameContext) -> Any:
    """Sort on short string columns with DISTINCT operation."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem.select("l_returnflag", "l_linestatus").unique().sort(["l_returnflag", "l_linestatus"])

    return result


# -----------------------------------------------------------------------------
# Additional Shuffle/Join queries
# -----------------------------------------------------------------------------


def shuffle_inner_join_groupby_expression_impl(ctx: DataFrameContext) -> Any:
    """Standard inner join with one-to-many relationship."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col

    result = (
        customer.join(orders, left_on="c_custkey", right_on="o_custkey")
        .group_by("c_mktsegment")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("o_totalprice").sum().alias("total_revenue"),
        )
    )

    return result


def shuffle_left_join_groupby_expression_impl(ctx: DataFrameContext) -> Any:
    """LEFT JOIN with preservation of all left-side rows."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col

    result = (
        customer.join(orders, left_on="c_custkey", right_on="o_custkey", how="left")
        .group_by("c_mktsegment")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("c_custkey").count().alias("total_rows"),
        )
    )

    return result


def shuffle_full_join_groupby_expression_impl(ctx: DataFrameContext) -> Any:
    """FULL OUTER JOIN with string grouping and aggregation."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col

    result = (
        customer.join(orders, left_on="c_custkey", right_on="o_custkey", how="outer")
        .group_by("c_mktsegment")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("c_custkey").count().alias("customer_count"),
        )
    )

    return result


def shuffle_self_join_expression_impl(ctx: DataFrameContext) -> Any:
    """Self-join with hash collision handling on large table."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    # Self-join on partkey and shipdate
    result = (
        lineitem.join(
            lineitem.select("l_orderkey", "l_partkey", "l_shipdate").rename({"l_orderkey": "l_orderkey_2"}),
            on=["l_partkey", "l_shipdate"],
        )
        .filter(col("l_orderkey") != col("l_orderkey_2"))
        .group_by("l_orderkey")
        .agg(col("l_orderkey_2").count().alias("match_count"))
        .limit(10000)
    )

    return result


# -----------------------------------------------------------------------------
# Additional String queries
# -----------------------------------------------------------------------------


def string_equal_expression_impl(ctx: DataFrameContext) -> Any:
    """Exact string equality with selective matching."""
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    result = part.filter(col("p_brand") == lit("Brand#23")).select(col("p_partkey").count().alias("count"))

    return result


def string_equal_lower_expression_impl(ctx: DataFrameContext) -> Any:
    """Equality predicate after applying case conversion."""
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    result = part.filter(col("p_brand").str.to_lowercase() == lit("brand#23")).select(
        col("p_partkey").count().alias("count")
    )

    return result


def string_in_predicate_expression_impl(ctx: DataFrameContext) -> Any:
    """IN predicate with string values."""
    orders = ctx.get_table("orders")
    col = ctx.col

    result = orders.filter(col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"])).select(
        col("o_orderkey").count().alias("count")
    )

    return result


def string_like_center_expression_impl(ctx: DataFrameContext) -> Any:
    """Case sensitive matching pattern in any location."""
    part = ctx.get_table("part")
    col = ctx.col

    result = part.filter(col("p_name").str.contains("STEEL")).select(col("p_partkey").count().alias("count"))

    return result


def string_like_suffix_expression_impl(ctx: DataFrameContext) -> Any:
    """Case sensitive matching suffix pattern."""
    part = ctx.get_table("part")
    col = ctx.col

    result = part.filter(col("p_name").str.ends_with("COPPER")).select(col("p_partkey").count().alias("count"))

    return result


def string_like_prefix_expression_impl(ctx: DataFrameContext) -> Any:
    """Case sensitive matching prefix pattern."""
    part = ctx.get_table("part")
    col = ctx.col

    result = part.filter(col("p_name").str.starts_with("STANDARD")).select(col("p_partkey").count().alias("count"))

    return result


# -----------------------------------------------------------------------------
# Additional Window queries
# -----------------------------------------------------------------------------


def window_growing_frame_expression_impl(ctx: DataFrameContext) -> Any:
    """Running sum window aggregation with growing frame size."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineitem.filter(col("l_orderkey") <= lit(1000))
        .sort(["l_orderkey", "l_linenumber"])
        .with_columns(
            ctx.window_sum(
                "l_quantity",
                partition_by=["l_orderkey"],
                order_by=[("l_linenumber", True)],
            ).alias("running_quantity")
        )
        .select("l_orderkey", "l_linenumber", "l_quantity", "running_quantity")
    )

    return result


def window_lead_lag_expression_impl(ctx: DataFrameContext) -> Any:
    """Offset window functions over the same frame."""
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    result = (
        orders.filter((col("o_orderdate") >= lit(date(1995, 1, 1))) & (col("o_orderdate") < lit(date(1996, 1, 1))))
        .sort(["o_custkey", "o_orderdate"])
        .with_columns(
            [
                ctx.window_lag("o_totalprice", partition_by=["o_custkey"], order_by=[("o_orderdate", True)]).alias(
                    "prev_order_price"
                ),
                ctx.window_lead("o_totalprice", partition_by=["o_custkey"], order_by=[("o_orderdate", True)]).alias(
                    "next_order_price"
                ),
            ]
        )
        .select("o_orderkey", "o_orderdate", "o_totalprice", "prev_order_price", "next_order_price")
    )

    return result


def window_dense_rank_expression_impl(ctx: DataFrameContext) -> Any:
    """Window function DENSE_RANK() OVER (PARTITION BY ... ORDER BY ...)."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineitem.filter(col("l_orderkey") <= lit(10000))
        .with_columns(
            ctx.window_dense_rank(
                order_by=[("l_extendedprice", False)],
                partition_by=["l_orderkey"],
            ).alias("price_rank")
        )
        .sort(["l_orderkey", "price_rank"])
        .select("l_orderkey", "l_partkey", "l_quantity", "l_extendedprice", "price_rank")
    )

    return result


# -----------------------------------------------------------------------------
# Additional Predicate queries
# -----------------------------------------------------------------------------


def predicate_ordering_groupby_expression_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity for aggregation within a low cardinality grouping."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineitem.filter(
            (col("l_shipdate") <= lit(date(1998, 9, 1)))
            & (col("l_discount") > lit(0.05))
            & (col("l_tax") < lit(0.08))
            & (col("l_quantity") >= lit(10))
            & (col("l_quantity") <= lit(30))
        )
        .group_by("l_returnflag")
        .agg(col("l_quantity").sum().alias("total_qty"))
    )

    return result


def predicate_ordering_costs_expression_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity with result projection only."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineitem.filter(
            (col("l_quantity") > lit(45))
            & (col("l_extendedprice") > lit(50000))
            & (col("l_discount") < lit(0.05))
            & (col("l_shipinstruct") == lit("DELIVER IN PERSON"))
            & (col("l_shipmode").is_in(["AIR", "AIR REG"]))
        )
        .select(
            "l_orderkey", "l_partkey", "l_quantity", "l_extendedprice", "l_discount", "l_shipinstruct", "l_shipmode"
        )
        .limit(100)
    )

    return result


# -----------------------------------------------------------------------------
# Additional Broadcast/Exchange queries
# -----------------------------------------------------------------------------


def broadcast_join_four_tables_expression_impl(ctx: DataFrameContext) -> Any:
    """Three small tables broadcast to join with one large table."""
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    result = (
        partsupp.join(supplier, left_on="ps_suppkey", right_on="s_suppkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .join(part, left_on="ps_partkey", right_on="p_partkey")
        .filter(col("p_size") == lit(15))
        .group_by("r_name", "p_type")
        .agg((col("ps_supplycost") * col("ps_availqty")).sum().alias("total_value"))
    )

    return result


def exchange_broadcast_expression_impl(ctx: DataFrameContext) -> Any:
    """One small table is copied to all nodes that have the large table."""
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    # Small parts filtered from part table
    small_parts = part.filter(col("p_size") == lit(1)).select("p_partkey")

    result = (
        lineitem.join(small_parts, left_on="l_partkey", right_on="p_partkey")
        .group_by("l_orderkey")
        .agg(col("l_quantity").sum().alias("total_qty"))
    )

    return result


def exchange_merge_expression_impl(ctx: DataFrameContext) -> Any:
    """Sorted data from multiple nodes is combined while keeping the sort order."""
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    result = (
        orders.join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .select("o_orderkey", "l_linenumber", "l_quantity")
        .sort(["o_orderkey", "l_linenumber"])
    )

    return result


def exchange_shuffle_expression_impl(ctx: DataFrameContext) -> Any:
    """Data is redistributed based on the join keys so matching rows end up on the same node."""
    partsupp = ctx.get_table("partsupp")
    col = ctx.col
    lit = ctx.lit

    # Self-join partsupp to find different suppliers for same part
    ps1 = partsupp.select(
        col("ps_partkey").alias("ps_partkey"),
        col("ps_suppkey").alias("supp1"),
        col("ps_supplycost").alias("cost1"),
    )
    ps2 = partsupp.select(
        col("ps_partkey").alias("ps_partkey_2"),
        col("ps_suppkey").alias("supp2"),
    )

    result = (
        ps1.join(ps2, left_on="ps_partkey", right_on="ps_partkey_2")
        .filter((col("supp1") < col("supp2")) & (col("cost1") > lit(100)))
        .select("ps_partkey", "supp1", "supp2")
    )

    return result


# -----------------------------------------------------------------------------
# TopN queries
# -----------------------------------------------------------------------------


def topn_aggregate_expression_impl(ctx: DataFrameContext) -> Any:
    """Top 10 limit returning 2 columns after aggregation and computed ordering."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    result = (
        lineitem.group_by("l_orderkey")
        .agg(col("l_quantity").sum().alias("total_quantity"))
        .sort("total_quantity", descending=True)
        .limit(10)
    )

    return result


def topn_allcols_expression_impl(ctx: DataFrameContext) -> Any:
    """Top-10 limit returning all columns after ordering over all table rows."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem.sort("l_extendedprice", descending=True).limit(10)

    return result


# -----------------------------------------------------------------------------
# Statistical queries
# -----------------------------------------------------------------------------


def statistical_variance_expression_impl(ctx: DataFrameContext) -> Any:
    """Variance and standard deviation calculations."""
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    result = (
        orders.filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .group_by("o_orderpriority")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("o_totalprice").mean().alias("avg_price"),
            col("o_totalprice").var().alias("price_variance"),
            col("o_totalprice").std().alias("price_stddev"),
        )
    )

    return result


def statistical_correlation_expression_impl(ctx: DataFrameContext) -> Any:
    """Correlation analysis between numeric columns."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    filtered = lineitem.filter(
        (col("l_shipdate") >= lit(date(1995, 1, 1))) & (col("l_shipdate") < lit(date(1996, 1, 1)))
    )

    # Calculate correlation between quantity and price
    result = filtered.select(
        col("l_quantity").mean().alias("avg_quantity"),
        col("l_extendedprice").mean().alias("avg_price"),
        # Correlation requires special handling - use pearson_corr where available
        (
            (col("l_quantity") * col("l_extendedprice")).mean()
            - col("l_quantity").mean() * col("l_extendedprice").mean()
        ).alias("covariance_approx"),
    )

    return result


# -----------------------------------------------------------------------------
# Long predicate query
# -----------------------------------------------------------------------------


def long_predicate_expression_impl(ctx: DataFrameContext) -> Any:
    """Query with many conjunctive predicates across multiple tables."""
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineitem.join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .join(customer, left_on="o_custkey", right_on="c_custkey")
        .filter(
            (col("l_shipdate") >= lit(date(1994, 1, 1)))
            & (col("l_shipdate") < lit(date(1995, 1, 1)))
            & (col("l_discount") >= lit(0.05))
            & (col("l_discount") <= lit(0.07))
            & (col("l_quantity") < lit(24))
            & (col("o_orderpriority") == lit("1-URGENT"))
            & (col("c_mktsegment") == lit("BUILDING"))
            & (col("l_returnflag") == lit("R"))
            & (col("l_linestatus") == lit("F"))
            & (col("o_totalprice") > lit(100000))
            & (col("c_nationkey").is_in([1, 2, 3, 4, 5]))
        )
        .select(col("l_orderkey").count().alias("count"))
    )

    return result


# -----------------------------------------------------------------------------
# Min/Max By queries
# -----------------------------------------------------------------------------


def max_by_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Find the customer with the highest account balance in each nation."""
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    col = ctx.col

    # Join and find max balance per nation, then get customer with that balance
    with_nation = customer.join(nation, left_on="c_nationkey", right_on="n_nationkey")

    # Group by nation and find max balance
    max_balances = with_nation.group_by("n_name").agg(col("c_acctbal").max().alias("max_balance"))

    # Rejoin to get customer name
    result = (
        with_nation.join(max_balances, on="n_name")
        .filter(col("c_acctbal") == col("max_balance"))
        .select("n_name", "c_name", "max_balance")
        .unique(subset=["n_name"])
        .sort("max_balance", descending=True)
    )

    return result


def min_by_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Find the customer with the lowest account balance in each nation."""
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    col = ctx.col

    with_nation = customer.join(nation, left_on="c_nationkey", right_on="n_nationkey")

    min_balances = with_nation.group_by("n_name").agg(col("c_acctbal").min().alias("min_balance"))

    result = (
        with_nation.join(min_balances, on="n_name")
        .filter(col("c_acctbal") == col("min_balance"))
        .select("n_name", "c_name", "min_balance")
        .unique(subset=["n_name"])
        .sort("min_balance")
    )

    return result


# -----------------------------------------------------------------------------
# Array operations (semi-structured data)
# -----------------------------------------------------------------------------


def array_agg_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Aggregate part keys into arrays per supplier."""
    partsupp = ctx.get_table("partsupp")
    col = ctx.col

    result = (
        partsupp.group_by("ps_suppkey")
        .agg(
            col("ps_partkey").sort_by("ps_partkey").alias("supplied_parts"),
            col("ps_partkey").count().alias("part_count"),
        )
        .filter(col("part_count") <= 10)
        .limit(100)
    )

    return result


def array_agg_distinct_expression_impl(ctx: DataFrameContext) -> Any:
    """Distinct array aggregation."""
    customer = ctx.get_table("customer")
    col = ctx.col

    result = customer.group_by("c_mktsegment").agg(
        col("c_nationkey").unique().sort().alias("nation_keys"),
    )

    return result


# =============================================================================
# Pandas Family Implementations (Pandas, Modin, Dask)
# =============================================================================


def aggregation_distinct_pandas_impl(ctx: DataFrameContext) -> Any:
    """Distinct count of high cardinality key on a large table."""
    orders = ctx.get_table("orders")

    filtered = orders[orders["o_orderdate"] >= date(1995, 1, 1)]
    result = filtered[["o_custkey"]].nunique().to_frame(name="unique_customers").reset_index(drop=True)

    return result


def aggregation_distinct_groupby_pandas_impl(ctx: DataFrameContext) -> Any:
    """Distinct count of high cardinality keys in low cardinality groups."""
    return aggregation_groupby_impl(
        ctx,
        table_name="lineitem",
        group_cols=("l_returnflag", "l_linestatus"),
        agg_specs=(
            ("l_orderkey", "nunique", "unique_orders"),
            ("l_partkey", "nunique", "unique_parts"),
        ),
    )


def aggregation_groupby_large_pandas_impl(ctx: DataFrameContext) -> Any:
    """Aggregates within high cardinality grouping."""
    return aggregation_groupby_impl(
        ctx,
        table_name="lineitem",
        group_cols=("l_orderkey", "l_partkey", "l_suppkey"),
        agg_specs=(
            ("l_quantity", "sum", "total_qty"),
            ("l_extendedprice", "mean", "avg_price"),
        ),
    )


def aggregation_groupby_small_pandas_impl(ctx: DataFrameContext) -> Any:
    """Aggregates within low cardinality grouping."""
    return aggregation_groupby_impl(
        ctx,
        table_name="nation",
        group_cols=("n_regionkey",),
        agg_specs=(
            ("n_nationkey", "count", "nation_count"),
            ("n_name", "max", "last_nation"),
        ),
    )


def aggregation_materialize_pandas_impl(ctx: DataFrameContext) -> Any:
    """Nested aggregation requiring CTE materialization."""
    orders = ctx.get_table("orders")

    # First aggregation
    order_totals = orders.groupby("o_custkey", as_index=False).agg(customer_total=("o_totalprice", "sum"))

    # Second aggregation - use ctx.scalar_to_df for platform compatibility
    result = ctx.scalar_to_df({"avg_customer_spending": order_totals["customer_total"].mean()})

    return result


def aggregation_materialize_subquery_pandas_impl(ctx: DataFrameContext) -> Any:
    """Complex nested aggregation requiring materialization of a subquery with joins."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    # Join tables
    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    merged = merged.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")

    # Calculate order total
    merged["order_total"] = merged["l_extendedprice"] * (1 - merged["l_discount"])

    # First aggregation by segment and order
    order_totals = merged.groupby(["c_mktsegment", "o_orderkey"], as_index=False).agg(
        order_total=("order_total", "sum")
    )

    # Second aggregation by segment
    result = order_totals.groupby("c_mktsegment", as_index=False).agg(avg_segment_order=("order_total", "mean"))

    return result


def aggregation_partition_pandas_impl(ctx: DataFrameContext) -> Any:
    """Aggregates over the partition key."""
    lineitem = ctx.get_table("lineitem")

    filtered = lineitem[(lineitem["l_shipdate"] >= date(1995, 1, 1)) & (lineitem["l_shipdate"] < date(1996, 1, 1))]

    result = filtered.groupby(["l_shipdate", "l_shipmode"], as_index=False).agg(
        daily_quantity=("l_quantity", "sum"),
        shipment_count=("l_orderkey", "count"),
    )

    return result


def aggregation_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """Aggregate on a small subset of rows."""
    lineitem = ctx.get_table("lineitem")

    filtered = lineitem[(lineitem["l_discount"] > 0.05) & (lineitem["l_quantity"] < 24)]
    total = (filtered["l_extendedprice"] * filtered["l_discount"]).sum()
    result = ctx.scalar_to_df({"total_discount_amount": total})

    return result


def aggregation_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Aggregate over all rows in table."""
    orders = ctx.get_table("orders")

    result = ctx.scalar_to_df(
        {
            "total_orders": len(orders),
            "total_revenue": orders["o_totalprice"].sum(),
        }
    )

    return result


def filter_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """High selectivity filter - few rows match."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem[
        (lineitem["l_quantity"] > 45) & (lineitem["l_extendedprice"] > 50000) & (lineitem["l_discount"] < 0.05)
    ][["l_orderkey", "l_partkey", "l_quantity", "l_extendedprice"]]

    return result


def filter_non_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """Low selectivity filter - many rows match."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem[lineitem["l_quantity"] > 1][["l_orderkey", "l_partkey", "l_quantity", "l_extendedprice"]]

    return result


def count_star_pandas_impl(ctx: DataFrameContext) -> Any:
    """Metadata-based count optimization vs full table scan performance."""
    lineitem = ctx.get_table("lineitem")

    result = ctx.scalar_to_df({"total_lineitems": len(lineitem)})

    return result


def decimal_arithmetic_pandas_impl(ctx: DataFrameContext) -> Any:
    """Decimal precision arithmetic with complex expressions."""
    lineitem = ctx.get_table("lineitem")

    filtered = lineitem[lineitem["l_quantity"] > 0].copy()
    filtered["final_price"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"]) * (1 + filtered["l_tax"])
    filtered["unit_price"] = filtered["l_extendedprice"] / filtered["l_quantity"]

    result = filtered[["l_orderkey", "final_price", "unit_price"]].head(1000)

    return result


def orderby_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Simple ORDER BY single column."""
    orders = ctx.get_table("orders")

    result = orders[["o_orderkey", "o_orderdate", "o_totalprice"]].sort_values("o_orderdate").head(100)

    return result


def orderby_multi_pandas_impl(ctx: DataFrameContext) -> Any:
    """ORDER BY multiple columns."""
    lineitem = ctx.get_table("lineitem")

    result = (
        lineitem[["l_orderkey", "l_linenumber", "l_shipdate", "l_quantity"]]
        .sort_values(["l_shipdate", "l_orderkey", "l_linenumber"])
        .head(100)
    )

    return result


def orderby_desc_pandas_impl(ctx: DataFrameContext) -> Any:
    """ORDER BY with descending sort."""
    orders = ctx.get_table("orders")

    result = (
        orders[["o_orderkey", "o_totalprice", "o_orderdate"]].sort_values("o_totalprice", ascending=False).head(100)
    )

    return result


def topn_pandas_impl(ctx: DataFrameContext) -> Any:
    """Top-N query with ORDER BY and LIMIT."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem.nlargest(10, "l_extendedprice")[["l_orderkey", "l_partkey", "l_extendedprice"]]

    return result


def limit_pandas_impl(ctx: DataFrameContext) -> Any:
    """Simple LIMIT without ORDER BY."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem[["l_orderkey", "l_partkey", "l_suppkey", "l_quantity"]].head(1000)

    return result


def string_like_pandas_impl(ctx: DataFrameContext) -> Any:
    """String LIKE pattern matching."""
    part = ctx.get_table("part")

    result = part[part["p_name"].str.contains("blue", na=False)][["p_partkey", "p_name", "p_type"]]

    return result


def string_starts_with_pandas_impl(ctx: DataFrameContext) -> Any:
    """String starts_with pattern matching."""
    part = ctx.get_table("part")

    result = part[part["p_type"].str.startswith("STANDARD", na=False)][["p_partkey", "p_name", "p_type"]]

    return result


def string_ends_with_pandas_impl(ctx: DataFrameContext) -> Any:
    """String ends_with pattern matching."""
    part = ctx.get_table("part")

    result = part[part["p_type"].str.endswith("BRASS", na=False)][["p_partkey", "p_name", "p_type"]]

    return result


def string_concat_pandas_impl(ctx: DataFrameContext) -> Any:
    """String concatenation."""
    customer = ctx.get_table("customer")

    result = customer.copy()
    result["customer_info"] = result["c_name"] + " - " + result["c_mktsegment"]
    result = result[["c_custkey", "customer_info"]].head(100)

    return result


def string_substring_pandas_impl(ctx: DataFrameContext) -> Any:
    """String substring extraction."""
    customer = ctx.get_table("customer")

    result = customer.copy()
    result["country_code"] = result["c_phone"].str[:3]
    result = result[["c_custkey", "country_code"]].head(100)

    return result


def window_row_number_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window function ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)."""
    lineitem = ctx.get_table("lineitem")

    # Sort and rank within groups
    sorted_df = lineitem.sort_values(["l_orderkey", "l_extendedprice"], ascending=[True, False])
    sorted_df["row_num"] = sorted_df.groupby("l_orderkey").cumcount() + 1

    result = sorted_df[sorted_df["row_num"] <= 3][["l_orderkey", "l_linenumber", "l_extendedprice", "row_num"]]

    return result


def window_rank_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window function RANK() OVER (PARTITION BY ... ORDER BY ...)."""
    lineitem = ctx.get_table("lineitem")

    # Rank within groups
    lineitem = lineitem.copy()
    lineitem["qty_rank"] = lineitem.groupby("l_returnflag")["l_quantity"].rank(method="min", ascending=False)

    result = lineitem[lineitem["qty_rank"] <= 5][["l_orderkey", "l_returnflag", "l_quantity", "qty_rank"]]

    return result


def window_sum_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window function SUM() OVER (PARTITION BY ...)."""
    lineitem = ctx.get_table("lineitem")

    lineitem = lineitem.copy()
    lineitem["order_total"] = lineitem.groupby("l_orderkey")["l_extendedprice"].transform("sum")

    result = lineitem[["l_orderkey", "l_linenumber", "l_extendedprice", "order_total"]]

    return result


def window_running_sum_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window function SUM() OVER (ORDER BY ...) - cumulative sum."""
    orders = ctx.get_table("orders")

    sorted_orders = orders.sort_values("o_orderdate").copy()
    sorted_orders["cumulative_revenue"] = sorted_orders["o_totalprice"].cumsum()

    result = sorted_orders[["o_orderkey", "o_orderdate", "o_totalprice", "cumulative_revenue"]].head(100)

    return result


def broadcast_join_two_tables_pandas_impl(ctx: DataFrameContext) -> Any:
    """One small table broadcast to join with one large table."""
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")

    merged = supplier.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    result = ctx.scalar_to_df({"supplier_count": len(merged)})

    return result


def broadcast_join_three_tables_pandas_impl(ctx: DataFrameContext) -> Any:
    """Two small tables broadcast to join with one large table."""
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    merged = supplier.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    merged = merged.merge(region, left_on="n_regionkey", right_on="r_regionkey")

    result = merged.groupby(["r_name", "n_name"], as_index=False).agg(supplier_count=("s_suppkey", "count"))

    return result


def predicate_ordering_aggregation_pandas_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity for aggregation."""
    lineitem = ctx.get_table("lineitem")

    filtered = lineitem[
        (lineitem["l_shipdate"] >= date(1994, 1, 1))
        & (lineitem["l_shipdate"] < date(1995, 1, 1))
        & (lineitem["l_discount"] >= 0.05)
        & (lineitem["l_discount"] <= 0.07)
        & (lineitem["l_quantity"] < 24)
    ]

    result = ctx.scalar_to_df({"total_price": filtered["l_extendedprice"].sum()})

    return result


def shuffle_join_pandas_impl(ctx: DataFrameContext) -> Any:
    """Data is redistributed based on the join keys."""
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    merged = orders.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    result = merged.groupby("o_orderkey", as_index=False).agg(total_qty=("l_quantity", "sum"))

    return result


def empty_build_join_pandas_impl(ctx: DataFrameContext) -> Any:
    """Join when build side produces no rows (edge case handling)."""
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")

    empty_orders = orders[orders["o_totalprice"] < 0][["o_orderkey"]]
    result = lineitem.merge(empty_orders, left_on="l_orderkey", right_on="o_orderkey", how="left")[
        ["l_orderkey", "l_partkey", "l_quantity"]
    ]

    return result


# -----------------------------------------------------------------------------
# Additional Filter queries (Pandas)
# -----------------------------------------------------------------------------


def filter_bigint_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """Equality predicate with high selectivity on integer column."""
    orders = ctx.get_table("orders")

    result = orders[orders["o_orderkey"] == 1234567][["o_orderkey", "o_custkey", "o_orderdate", "o_totalprice"]]

    return result


def filter_bigint_non_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """Range predicate with low selectivity on large table."""
    lineitem = ctx.get_table("lineitem")

    count = len(lineitem[lineitem["l_orderkey"] > 1000])
    result = ctx.scalar_to_df({"count": count})

    return result


def filter_bigint_in_list_pandas_impl(ctx: DataFrameContext) -> Any:
    """IN-list predicate with highly selective integer values."""
    orders = ctx.get_table("orders")

    result = orders[orders["o_orderkey"].isin([1, 100, 1000, 10000, 100000])][
        ["o_orderkey", "o_custkey", "o_orderdate", "o_totalprice"]
    ]

    return result


def filter_decimal_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """Compound equality predicate with multiple decimal columns."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem[(lineitem["l_extendedprice"] == 12345.67) & (lineitem["l_discount"] == 0.05)][
        ["l_orderkey", "l_partkey", "l_extendedprice", "l_discount"]
    ]

    return result


def filter_decimal_non_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """Range predicate on decimal column with low selectivity."""
    lineitem = ctx.get_table("lineitem")

    count = len(lineitem[lineitem["l_extendedprice"] > 1000.00])
    result = ctx.scalar_to_df({"count": count})

    return result


def filter_string_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """Exact string equality with high selectivity on varchar column."""
    customer = ctx.get_table("customer")

    result = customer[customer["c_name"] == "Customer#000001234"][["c_custkey", "c_name", "c_address", "c_phone"]]

    return result


def filter_string_non_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """String comparison with low selectivity (most rows match)."""
    customer = ctx.get_table("customer")

    count = len(customer[customer["c_mktsegment"] >= "A"])
    result = ctx.scalar_to_df({"count": count})

    return result


def filter_in_predicate_subquery_pandas_impl(ctx: DataFrameContext) -> Any:
    """IN predicate with subquery and selective filtering."""
    part = ctx.get_table("part")
    lineitem = ctx.get_table("lineitem")

    high_qty_parts = lineitem[lineitem["l_quantity"] > 45]["l_partkey"].unique()
    result = part[part["p_partkey"].isin(high_qty_parts)][["p_partkey", "p_name", "p_type", "p_size"]]

    return result


# -----------------------------------------------------------------------------
# Additional GroupBy queries (Pandas)
# -----------------------------------------------------------------------------


def groupby_highndv_pandas_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY with high distinct value count (many groups)."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem.groupby("l_orderkey", as_index=False).agg(line_count=("l_linenumber", "count"))

    return result


def groupby_lowndv_pandas_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY with low distinct value count (few groups)."""
    orders = ctx.get_table("orders")

    result = orders.groupby("o_orderpriority", as_index=False).agg(order_count=("o_orderkey", "count"))

    return result


def groupby_pk_pandas_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY on primary key (one row per group)."""
    customer = ctx.get_table("customer")

    result = customer.groupby("c_custkey", as_index=False).agg(customer_name=("c_name", "max"))

    return result


def groupby_decimal_highndv_pandas_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY with high cardinality decimal column."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem.groupby("l_extendedprice", as_index=False).agg(price_frequency=("l_orderkey", "count"))

    return result


def groupby_decimal_lowndv_pandas_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY with low cardinality decimal column."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem.groupby("l_discount", as_index=False).agg(
        discount_frequency=("l_orderkey", "count"),
        avg_qty=("l_quantity", "mean"),
    )

    return result


# -----------------------------------------------------------------------------
# Additional OrderBy queries (Pandas)
# -----------------------------------------------------------------------------


def orderby_all_pandas_impl(ctx: DataFrameContext) -> Any:
    """Sort on full table with simple integer ordering."""
    customer = ctx.get_table("customer")

    result = customer.sort_values("c_custkey")[
        ["c_custkey", "c_name", "c_address", "c_nationkey", "c_phone", "c_acctbal", "c_mktsegment"]
    ]

    return result


def orderby_bigint_pandas_impl(ctx: DataFrameContext) -> Any:
    """Sort with aggregation results on integer column."""
    lineitem = ctx.get_table("lineitem")

    result = (
        lineitem.groupby("l_orderkey", as_index=False).agg(total_qty=("l_quantity", "sum")).sort_values("l_orderkey")
    )

    return result


def orderby_expression_pandas_impl(ctx: DataFrameContext) -> Any:
    """Sort on computed expressions with DESC ordering."""
    lineitem = ctx.get_table("lineitem")

    df = lineitem.copy()
    df["total_value"] = df["l_quantity"] * df["l_extendedprice"]
    result = df.sort_values("total_value", ascending=False)[["l_orderkey", "l_partkey", "total_value"]].head(100)

    return result


def orderby_multicol_pandas_impl(ctx: DataFrameContext) -> Any:
    """Complex multi-column sort with string, date, and decimal columns."""
    orders = ctx.get_table("orders")

    result = orders.sort_values(
        ["o_orderpriority", "o_orderdate", "o_totalprice"],
        ascending=[True, False, False],
    )[["o_orderkey", "o_custkey", "o_orderpriority", "o_orderdate", "o_totalprice"]].head(100)

    return result


def orderby_shortstrings_pandas_impl(ctx: DataFrameContext) -> Any:
    """Sort on short string columns with DISTINCT operation."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem[["l_returnflag", "l_linestatus"]].drop_duplicates().sort_values(["l_returnflag", "l_linestatus"])

    return result


# -----------------------------------------------------------------------------
# Additional Shuffle/Join queries (Pandas)
# -----------------------------------------------------------------------------


def shuffle_inner_join_groupby_pandas_impl(ctx: DataFrameContext) -> Any:
    """Standard inner join with one-to-many relationship."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    result = merged.groupby("c_mktsegment", as_index=False).agg(
        order_count=("o_orderkey", "count"),
        total_revenue=("o_totalprice", "sum"),
    )

    return result


def shuffle_left_join_groupby_pandas_impl(ctx: DataFrameContext) -> Any:
    """LEFT JOIN with preservation of all left-side rows."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey", how="left")
    result = merged.groupby("c_mktsegment", as_index=False).agg(
        order_count=("o_orderkey", "count"),
        total_rows=("c_custkey", "count"),
    )

    return result


def shuffle_full_join_groupby_pandas_impl(ctx: DataFrameContext) -> Any:
    """FULL OUTER JOIN with string grouping and aggregation."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey", how="outer")
    result = merged.groupby("c_mktsegment", as_index=False).agg(
        order_count=("o_orderkey", "count"),
        customer_count=("c_custkey", "count"),
    )

    return result


def shuffle_self_join_pandas_impl(ctx: DataFrameContext) -> Any:
    """Self-join with hash collision handling on large table."""
    lineitem = ctx.get_table("lineitem")

    # Create copies for self-join
    df1 = lineitem[["l_orderkey", "l_partkey", "l_shipdate"]].copy()
    df2 = lineitem[["l_orderkey", "l_partkey", "l_shipdate"]].copy()
    df2 = df2.rename(columns={"l_orderkey": "l_orderkey_2"})

    merged = df1.merge(df2, on=["l_partkey", "l_shipdate"])
    filtered = merged[merged["l_orderkey"] != merged["l_orderkey_2"]]
    result = filtered.groupby("l_orderkey", as_index=False).agg(match_count=("l_orderkey_2", "count")).head(10000)

    return result


# -----------------------------------------------------------------------------
# Additional String queries (Pandas)
# -----------------------------------------------------------------------------


def string_equal_pandas_impl(ctx: DataFrameContext) -> Any:
    """Exact string equality with selective matching."""
    part = ctx.get_table("part")

    count = len(part[part["p_brand"] == "Brand#23"])
    result = ctx.scalar_to_df({"count": count})

    return result


def string_equal_lower_pandas_impl(ctx: DataFrameContext) -> Any:
    """Equality predicate after applying case conversion."""
    part = ctx.get_table("part")

    count = len(part[part["p_brand"].str.lower() == "brand#23"])
    result = ctx.scalar_to_df({"count": count})

    return result


def string_in_predicate_pandas_impl(ctx: DataFrameContext) -> Any:
    """IN predicate with string values."""
    orders = ctx.get_table("orders")

    count = len(orders[orders["o_orderpriority"].isin(["1-URGENT", "2-HIGH"])])
    result = ctx.scalar_to_df({"count": count})

    return result


def string_like_center_pandas_impl(ctx: DataFrameContext) -> Any:
    """Case sensitive matching pattern in any location."""
    part = ctx.get_table("part")

    count = len(part[part["p_name"].str.contains("STEEL", na=False)])
    result = ctx.scalar_to_df({"count": count})

    return result


def string_like_suffix_pandas_impl(ctx: DataFrameContext) -> Any:
    """Case sensitive matching suffix pattern."""
    part = ctx.get_table("part")

    count = len(part[part["p_name"].str.endswith("COPPER", na=False)])
    result = ctx.scalar_to_df({"count": count})

    return result


def string_like_prefix_pandas_impl(ctx: DataFrameContext) -> Any:
    """Case sensitive matching prefix pattern."""
    part = ctx.get_table("part")

    count = len(part[part["p_name"].str.startswith("STANDARD", na=False)])
    result = ctx.scalar_to_df({"count": count})

    return result


# -----------------------------------------------------------------------------
# Additional Window queries (Pandas)
# -----------------------------------------------------------------------------


def window_growing_frame_pandas_impl(ctx: DataFrameContext) -> Any:
    """Running sum window aggregation with growing frame size."""
    lineitem = ctx.get_table("lineitem")

    df = lineitem[lineitem["l_orderkey"] <= 1000].copy()
    df = df.sort_values(["l_orderkey", "l_linenumber"])
    df["running_quantity"] = df.groupby("l_orderkey")["l_quantity"].cumsum()

    result = df[["l_orderkey", "l_linenumber", "l_quantity", "running_quantity"]]

    return result


def window_lead_lag_pandas_impl(ctx: DataFrameContext) -> Any:
    """Offset window functions over the same frame."""
    orders = ctx.get_table("orders")

    df = orders[(orders["o_orderdate"] >= date(1995, 1, 1)) & (orders["o_orderdate"] < date(1996, 1, 1))].copy()
    df = df.sort_values(["o_custkey", "o_orderdate"])
    df["prev_order_price"] = df.groupby("o_custkey")["o_totalprice"].shift(1)
    df["next_order_price"] = df.groupby("o_custkey")["o_totalprice"].shift(-1)

    result = df[["o_orderkey", "o_orderdate", "o_totalprice", "prev_order_price", "next_order_price"]]

    return result


def window_dense_rank_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window function DENSE_RANK() OVER (PARTITION BY ... ORDER BY ...)."""
    lineitem = ctx.get_table("lineitem")

    df = lineitem[lineitem["l_orderkey"] <= 10000].copy()
    df["price_rank"] = df.groupby("l_orderkey")["l_extendedprice"].rank(method="dense", ascending=False)
    df = df.sort_values(["l_orderkey", "price_rank"])

    result = df[["l_orderkey", "l_partkey", "l_quantity", "l_extendedprice", "price_rank"]]

    return result


# -----------------------------------------------------------------------------
# Additional Predicate queries (Pandas)
# -----------------------------------------------------------------------------


def predicate_ordering_groupby_pandas_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity for aggregation within a low cardinality grouping."""
    lineitem = ctx.get_table("lineitem")

    filtered = lineitem[
        (lineitem["l_shipdate"] <= date(1998, 9, 1))
        & (lineitem["l_discount"] > 0.05)
        & (lineitem["l_tax"] < 0.08)
        & (lineitem["l_quantity"] >= 10)
        & (lineitem["l_quantity"] <= 30)
    ]

    result = filtered.groupby("l_returnflag", as_index=False).agg(total_qty=("l_quantity", "sum"))

    return result


def predicate_ordering_costs_pandas_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity with result projection only."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem[
        (lineitem["l_quantity"] > 45)
        & (lineitem["l_extendedprice"] > 50000)
        & (lineitem["l_discount"] < 0.05)
        & (lineitem["l_shipinstruct"] == "DELIVER IN PERSON")
        & (lineitem["l_shipmode"].isin(["AIR", "AIR REG"]))
    ][["l_orderkey", "l_partkey", "l_quantity", "l_extendedprice", "l_discount", "l_shipinstruct", "l_shipmode"]].head(
        100
    )

    return result


# -----------------------------------------------------------------------------
# Additional Broadcast/Exchange queries (Pandas)
# -----------------------------------------------------------------------------


def broadcast_join_four_tables_pandas_impl(ctx: DataFrameContext) -> Any:
    """Three small tables broadcast to join with one large table."""
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    part = ctx.get_table("part")

    merged = partsupp.merge(supplier, left_on="ps_suppkey", right_on="s_suppkey")
    merged = merged.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    merged = merged.merge(region, left_on="n_regionkey", right_on="r_regionkey")
    merged = merged.merge(part, left_on="ps_partkey", right_on="p_partkey")
    filtered = merged[merged["p_size"] == 15]

    filtered = filtered.copy()
    filtered["total_value"] = filtered["ps_supplycost"] * filtered["ps_availqty"]
    result = filtered.groupby(["r_name", "p_type"], as_index=False).agg(total_value=("total_value", "sum"))

    return result


def exchange_broadcast_pandas_impl(ctx: DataFrameContext) -> Any:
    """One small table is copied to all nodes that have the large table."""
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")

    small_parts = part[part["p_size"] == 1][["p_partkey"]]
    merged = lineitem.merge(small_parts, left_on="l_partkey", right_on="p_partkey")

    result = merged.groupby("l_orderkey", as_index=False).agg(total_qty=("l_quantity", "sum"))

    return result


def exchange_merge_pandas_impl(ctx: DataFrameContext) -> Any:
    """Sorted data from multiple nodes is combined while keeping the sort order."""
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    merged = orders.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    result = merged[["o_orderkey", "l_linenumber", "l_quantity"]].sort_values(["o_orderkey", "l_linenumber"])

    return result


def exchange_shuffle_pandas_impl(ctx: DataFrameContext) -> Any:
    """Data is redistributed based on the join keys so matching rows end up on the same node."""
    partsupp = ctx.get_table("partsupp")

    ps1 = partsupp[["ps_partkey", "ps_suppkey", "ps_supplycost"]].rename(
        columns={"ps_suppkey": "supp1", "ps_supplycost": "cost1"}
    )
    ps2 = partsupp[["ps_partkey", "ps_suppkey"]].rename(columns={"ps_suppkey": "supp2"})

    merged = ps1.merge(ps2, on="ps_partkey")
    result = merged[(merged["supp1"] < merged["supp2"]) & (merged["cost1"] > 100)][["ps_partkey", "supp1", "supp2"]]

    return result


# -----------------------------------------------------------------------------
# TopN queries (Pandas)
# -----------------------------------------------------------------------------


def topn_aggregate_pandas_impl(ctx: DataFrameContext) -> Any:
    """Top 10 limit returning 2 columns after aggregation and computed ordering."""
    lineitem = ctx.get_table("lineitem")

    result = (
        lineitem.groupby("l_orderkey", as_index=False)
        .agg(total_quantity=("l_quantity", "sum"))
        .nlargest(10, "total_quantity")
    )

    return result


def topn_allcols_pandas_impl(ctx: DataFrameContext) -> Any:
    """Top-10 limit returning all columns after ordering over all table rows."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem.nlargest(10, "l_extendedprice")

    return result


# -----------------------------------------------------------------------------
# Statistical queries (Pandas)
# -----------------------------------------------------------------------------


def statistical_variance_pandas_impl(ctx: DataFrameContext) -> Any:
    """Variance and standard deviation calculations."""
    orders = ctx.get_table("orders")

    filtered = orders[orders["o_orderdate"] >= date(1995, 1, 1)]
    result = filtered.groupby("o_orderpriority", as_index=False).agg(
        order_count=("o_orderkey", "count"),
        avg_price=("o_totalprice", "mean"),
        price_variance=("o_totalprice", "var"),
        price_stddev=("o_totalprice", "std"),
    )

    return result


def statistical_correlation_pandas_impl(ctx: DataFrameContext) -> Any:
    """Correlation analysis between numeric columns."""
    lineitem = ctx.get_table("lineitem")

    filtered = lineitem[(lineitem["l_shipdate"] >= date(1995, 1, 1)) & (lineitem["l_shipdate"] < date(1996, 1, 1))]

    result = ctx.scalar_to_df(
        {
            "avg_quantity": filtered["l_quantity"].mean(),
            "avg_price": filtered["l_extendedprice"].mean(),
            "qty_price_correlation": filtered["l_quantity"].corr(filtered["l_extendedprice"]),
        }
    )

    return result


# -----------------------------------------------------------------------------
# Long predicate query (Pandas)
# -----------------------------------------------------------------------------


def long_predicate_pandas_impl(ctx: DataFrameContext) -> Any:
    """Query with many conjunctive predicates across multiple tables."""
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")

    merged = lineitem.merge(orders, left_on="l_orderkey", right_on="o_orderkey")
    merged = merged.merge(customer, left_on="o_custkey", right_on="c_custkey")

    filtered = merged[
        (merged["l_shipdate"] >= date(1994, 1, 1))
        & (merged["l_shipdate"] < date(1995, 1, 1))
        & (merged["l_discount"] >= 0.05)
        & (merged["l_discount"] <= 0.07)
        & (merged["l_quantity"] < 24)
        & (merged["o_orderpriority"] == "1-URGENT")
        & (merged["c_mktsegment"] == "BUILDING")
        & (merged["l_returnflag"] == "R")
        & (merged["l_linestatus"] == "F")
        & (merged["o_totalprice"] > 100000)
        & (merged["c_nationkey"].isin([1, 2, 3, 4, 5]))
    ]

    result = ctx.scalar_to_df({"count": len(filtered)})

    return result


# -----------------------------------------------------------------------------
# Min/Max By queries (Pandas)
# -----------------------------------------------------------------------------


def max_by_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find the customer with the highest account balance in each nation."""
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")

    merged = customer.merge(nation, left_on="c_nationkey", right_on="n_nationkey")

    # Get max balance per nation
    max_idx = merged.groupby("n_name")["c_acctbal"].idxmax()
    result = merged.loc[max_idx][["n_name", "c_name", "c_acctbal"]].rename(columns={"c_acctbal": "max_balance"})
    result = result.sort_values("max_balance", ascending=False)

    return result


def min_by_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find the customer with the lowest account balance in each nation."""
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")

    merged = customer.merge(nation, left_on="c_nationkey", right_on="n_nationkey")

    # Get min balance per nation
    min_idx = merged.groupby("n_name")["c_acctbal"].idxmin()
    result = merged.loc[min_idx][["n_name", "c_name", "c_acctbal"]].rename(columns={"c_acctbal": "min_balance"})
    result = result.sort_values("min_balance")

    return result


# -----------------------------------------------------------------------------
# Array operations (Pandas)
# -----------------------------------------------------------------------------


def array_agg_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Aggregate part keys into arrays per supplier."""
    partsupp = ctx.get_table("partsupp")

    result = partsupp.groupby("ps_suppkey", as_index=False).agg(
        supplied_parts=("ps_partkey", lambda x: sorted(x)),
        part_count=("ps_partkey", "count"),
    )
    result = result[result["part_count"] <= 10].head(100)

    return result


def array_agg_distinct_pandas_impl(ctx: DataFrameContext) -> Any:
    """Distinct array aggregation."""
    customer = ctx.get_table("customer")

    result = customer.groupby("c_mktsegment", as_index=False).agg(
        nation_keys=("c_nationkey", lambda x: sorted(set(x))),
    )

    return result


# -----------------------------------------------------------------------------
# Limit query (Expression)
# -----------------------------------------------------------------------------


def limit_ordered_expression_impl(ctx: DataFrameContext) -> Any:
    """LIMIT clause with ordering on large result set."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem.sort(["l_orderkey", "l_linenumber"]).limit(100)

    return result


def limit_ordered_pandas_impl(ctx: DataFrameContext) -> Any:
    """LIMIT clause with ordering on large result set."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem.sort_values(["l_orderkey", "l_linenumber"]).head(100)

    return result


# -----------------------------------------------------------------------------
# Decimal IN list filter queries
# -----------------------------------------------------------------------------


def filter_decimal_in_list_expression_impl(ctx: DataFrameContext) -> Any:
    """IN-list predicate with decimal values and selectivity."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    result = lineitem.filter(col("l_extendedprice").is_in([1000.00, 5000.00, 10000.00, 50000.00])).select(
        "l_orderkey", "l_partkey", "l_extendedprice", "l_quantity"
    )

    return result


def filter_decimal_in_list_pandas_impl(ctx: DataFrameContext) -> Any:
    """IN-list predicate with decimal values and selectivity."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem[lineitem["l_extendedprice"].isin([1000.00, 5000.00, 10000.00, 50000.00])][
        ["l_orderkey", "l_partkey", "l_extendedprice", "l_quantity"]
    ]

    return result


# -----------------------------------------------------------------------------
# String LIKE filter queries (LIKE pattern)
# -----------------------------------------------------------------------------


def filter_string_like_expression_impl(ctx: DataFrameContext) -> Any:
    """LIKE predicate with substring pattern matching."""
    part = ctx.get_table("part")
    col = ctx.col

    result = part.filter(col("p_name").str.contains("COPPER")).select("p_partkey", "p_name", "p_type", "p_size")

    return result


def filter_string_like_pandas_impl(ctx: DataFrameContext) -> Any:
    """LIKE predicate with substring pattern matching."""
    part = ctx.get_table("part")

    result = part[part["p_name"].str.contains("COPPER", na=False)][["p_partkey", "p_name", "p_type", "p_size"]]

    return result


# -----------------------------------------------------------------------------
# OrderBy decimal queries
# -----------------------------------------------------------------------------


def orderby_decimal_expression_impl(ctx: DataFrameContext) -> Any:
    """Multi-column sort with mixed ASC/DESC on decimal columns."""
    lineitem = ctx.get_table("lineitem")

    result = (
        lineitem.sort(["l_extendedprice", "l_discount"], descending=[True, False])
        .select("l_orderkey", "l_extendedprice", "l_discount")
        .limit(100)
    )

    return result


def orderby_decimal_pandas_impl(ctx: DataFrameContext) -> Any:
    """Multi-column sort with mixed ASC/DESC on decimal columns."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem.sort_values(["l_extendedprice", "l_discount"], ascending=[False, True])[
        ["l_orderkey", "l_extendedprice", "l_discount"]
    ].head(100)

    return result


# -----------------------------------------------------------------------------
# Min/Max runtime filter query
# -----------------------------------------------------------------------------


def min_max_runtime_filter_expression_impl(ctx: DataFrameContext) -> Any:
    """Bloom filter and runtime filter effectiveness for join optimization."""
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Get orderkeys from date range
    date_filtered_orders = orders.filter(
        (col("o_orderdate") >= lit(date(1995, 1, 1))) & (col("o_orderdate") <= lit(date(1995, 3, 31)))
    ).select("o_orderkey")

    result = lineitem.join(date_filtered_orders, left_on="l_orderkey", right_on="o_orderkey", how="semi").select(
        "l_orderkey", "l_partkey", "l_quantity", "l_extendedprice"
    )

    return result


def min_max_runtime_filter_pandas_impl(ctx: DataFrameContext) -> Any:
    """Bloom filter and runtime filter effectiveness for join optimization."""
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")

    date_filtered_orders = orders[
        (orders["o_orderdate"] >= date(1995, 1, 1)) & (orders["o_orderdate"] <= date(1995, 3, 31))
    ]["o_orderkey"].unique()

    result = lineitem[lineitem["l_orderkey"].isin(date_filtered_orders)][
        ["l_orderkey", "l_partkey", "l_quantity", "l_extendedprice"]
    ]

    return result


# -----------------------------------------------------------------------------
# Max/Min By complex queries
# -----------------------------------------------------------------------------


def max_by_complex_expression_impl(ctx: DataFrameContext) -> Any:
    """Find the most expensive order for each customer segment."""
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    col = ctx.col

    merged = orders.join(customer, left_on="o_custkey", right_on="c_custkey")
    max_prices = merged.group_by("c_mktsegment").agg(col("o_totalprice").max().alias("max_order_value"))

    result = (
        merged.join(max_prices, on="c_mktsegment")
        .filter(col("o_totalprice") == col("max_order_value"))
        .select("c_mktsegment", "o_orderkey", "o_orderdate", "max_order_value")
        .unique(subset=["c_mktsegment"])
        .sort("max_order_value", descending=True)
    )

    return result


def max_by_complex_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find the most expensive order for each customer segment."""
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")

    merged = orders.merge(customer, left_on="o_custkey", right_on="c_custkey")
    max_idx = merged.groupby("c_mktsegment")["o_totalprice"].idxmax()
    result = merged.loc[max_idx][["c_mktsegment", "o_orderkey", "o_orderdate", "o_totalprice"]].rename(
        columns={"o_totalprice": "max_order_value"}
    )
    result = result.sort_values("max_order_value", ascending=False)

    return result


def min_by_complex_expression_impl(ctx: DataFrameContext) -> Any:
    """Find the cheapest part for each brand."""
    part = ctx.get_table("part")
    col = ctx.col

    min_prices = part.group_by("p_brand").agg(col("p_retailprice").min().alias("min_price"))

    result = (
        part.join(min_prices, on="p_brand")
        .filter(col("p_retailprice") == col("min_price"))
        .select("p_brand", "p_name", "p_type", "min_price")
        .unique(subset=["p_brand"])
        .sort("min_price")
    )

    return result


def min_by_complex_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find the cheapest part for each brand."""
    part = ctx.get_table("part")

    min_idx = part.groupby("p_brand")["p_retailprice"].idxmin()
    result = part.loc[min_idx][["p_brand", "p_name", "p_type", "p_retailprice"]].rename(
        columns={"p_retailprice": "min_price"}
    )
    result = result.sort_values("min_price")

    return result


# -----------------------------------------------------------------------------
# ANY_VALUE queries (modern SQL feature)
# -----------------------------------------------------------------------------


def any_value_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Select any customer name per market segment (faster than MIN/MAX)."""
    customer = ctx.get_table("customer")
    col = ctx.col

    result = customer.group_by("c_mktsegment").agg(
        col("c_name").first().alias("sample_customer"),
        col("c_custkey").count().alias("customer_count"),
    )

    return result


def any_value_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Select any customer name per market segment (faster than MIN/MAX)."""
    customer = ctx.get_table("customer")

    result = customer.groupby("c_mktsegment", as_index=False).agg(
        sample_customer=("c_name", "first"),
        customer_count=("c_custkey", "count"),
    )

    return result


def any_value_with_filter_expression_impl(ctx: DataFrameContext) -> Any:
    """Any value with additional aggregates."""
    nation = ctx.get_table("nation")
    col = ctx.col

    result = nation.group_by("n_regionkey").agg(
        col("n_name").first().alias("sample_nation"),
        col("n_comment").first().alias("sample_comment"),
        col("n_nationkey").count().alias("nation_count"),
    )

    return result


def any_value_with_filter_pandas_impl(ctx: DataFrameContext) -> Any:
    """Any value with additional aggregates."""
    nation = ctx.get_table("nation")

    result = nation.groupby("n_regionkey", as_index=False).agg(
        sample_nation=("n_name", "first"),
        sample_comment=("n_comment", "first"),
        nation_count=("n_nationkey", "count"),
    )

    return result


# -----------------------------------------------------------------------------
# GROUP BY ALL queries (modern SQL feature)
# Note: GROUP BY ALL automatically groups by all non-aggregate columns
# In DataFrames, we explicitly specify the grouping columns
# -----------------------------------------------------------------------------


def groupby_all_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Automatic grouping by all non-aggregate columns."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    result = lineitem.group_by("l_returnflag", "l_linestatus").agg(
        col("l_quantity").sum().alias("total_qty"),
        col("l_extendedprice").mean().alias("avg_price"),
    )

    return result


def groupby_all_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Automatic grouping by all non-aggregate columns."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem.groupby(["l_returnflag", "l_linestatus"], as_index=False).agg(
        total_qty=("l_quantity", "sum"),
        avg_price=("l_extendedprice", "mean"),
    )

    return result


def groupby_all_complex_expression_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY ALL with multiple non-aggregate expressions."""
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    filtered = orders.filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
    result = (
        filtered.with_columns(col("o_orderdate").dt.truncate("1mo").alias("order_month"))
        .group_by("order_month", "o_orderpriority")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("o_totalprice").sum().alias("monthly_revenue"),
        )
        .sort(["order_month", "o_orderpriority"])
    )

    return result


def groupby_all_complex_pandas_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY ALL with multiple non-aggregate expressions."""
    orders = ctx.get_table("orders")

    filtered = orders[orders["o_orderdate"] >= date(1995, 1, 1)].copy()
    filtered["order_month"] = filtered["o_orderdate"].dt.to_period("M")

    result = (
        filtered.groupby(["order_month", "o_orderpriority"], as_index=False)
        .agg(
            order_count=("o_orderkey", "count"),
            monthly_revenue=("o_totalprice", "sum"),
        )
        .sort_values(["order_month", "o_orderpriority"])
    )

    return result


# -----------------------------------------------------------------------------
# ORDER BY ALL queries (modern SQL feature)
# -----------------------------------------------------------------------------


def orderby_all_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Order by all columns in SELECT list."""
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col

    result = (
        supplier.join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .group_by("r_name", "n_name")
        .agg(col("s_suppkey").count().alias("supplier_count"))
        .sort(["r_name", "n_name", "supplier_count"])
    )

    return result


def orderby_all_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Order by all columns in SELECT list."""
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    merged = supplier.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    merged = merged.merge(region, left_on="n_regionkey", right_on="r_regionkey")

    result = (
        merged.groupby(["r_name", "n_name"], as_index=False)
        .agg(supplier_count=("s_suppkey", "count"))
        .sort_values(["r_name", "n_name", "supplier_count"])
    )

    return result


def orderby_all_desc_expression_impl(ctx: DataFrameContext) -> Any:
    """ORDER BY ALL with descending direction."""
    part = ctx.get_table("part")
    col = ctx.col

    result = (
        part.group_by("p_brand", "p_type")
        .agg(col("p_retailprice").mean().alias("avg_price"))
        .sort(["p_brand", "p_type", "avg_price"], descending=True)
        .limit(100)
    )

    return result


def orderby_all_desc_pandas_impl(ctx: DataFrameContext) -> Any:
    """ORDER BY ALL with descending direction."""
    part = ctx.get_table("part")

    result = (
        part.groupby(["p_brand", "p_type"], as_index=False)
        .agg(avg_price=("p_retailprice", "mean"))
        .sort_values(["p_brand", "p_type", "avg_price"], ascending=False)
        .head(100)
    )

    return result


# -----------------------------------------------------------------------------
# Max/Min By with ties queries
# -----------------------------------------------------------------------------


def max_by_with_ties_expression_impl(ctx: DataFrameContext) -> Any:
    """Find the supplier with the highest supply cost for each part."""
    partsupp = ctx.get_table("partsupp")
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    col = ctx.col

    # Note: Polars drops right join keys, so after join(left_on="ps_partkey", right_on="p_partkey")
    # the result has ps_partkey (not p_partkey). Use ps_partkey throughout.
    merged = partsupp.join(part, left_on="ps_partkey", right_on="p_partkey").join(
        supplier, left_on="ps_suppkey", right_on="s_suppkey"
    )

    max_costs = merged.group_by("ps_partkey", "p_name").agg(col("ps_supplycost").max().alias("max_supply_cost"))

    result = (
        merged.join(max_costs, on=["ps_partkey", "p_name"])
        .filter(col("ps_supplycost") == col("max_supply_cost"))
        .select("ps_partkey", "p_name", "s_name", "max_supply_cost")
        .unique(subset=["ps_partkey"])
        .sort("max_supply_cost", descending=True)
        .limit(100)
    )

    return result


def max_by_with_ties_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find the supplier with the highest supply cost for each part."""
    partsupp = ctx.get_table("partsupp")
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")

    merged = partsupp.merge(part, left_on="ps_partkey", right_on="p_partkey")
    merged = merged.merge(supplier, left_on="ps_suppkey", right_on="s_suppkey")

    max_idx = merged.groupby(["p_partkey", "p_name"])["ps_supplycost"].idxmax()
    result = merged.loc[max_idx][["p_partkey", "p_name", "s_name", "ps_supplycost"]].rename(
        columns={"ps_supplycost": "max_supply_cost", "s_name": "supplier_name"}
    )
    result = result.sort_values("max_supply_cost", ascending=False).head(100)

    return result


def min_by_with_ties_expression_impl(ctx: DataFrameContext) -> Any:
    """Find the supplier with the lowest supply cost for each part."""
    partsupp = ctx.get_table("partsupp")
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    col = ctx.col

    # Note: Polars drops right join keys, so after join(left_on="ps_partkey", right_on="p_partkey")
    # the result has ps_partkey (not p_partkey). Use ps_partkey throughout.
    merged = partsupp.join(part, left_on="ps_partkey", right_on="p_partkey").join(
        supplier, left_on="ps_suppkey", right_on="s_suppkey"
    )

    min_costs = merged.group_by("ps_partkey", "p_name").agg(col("ps_supplycost").min().alias("min_supply_cost"))

    result = (
        merged.join(min_costs, on=["ps_partkey", "p_name"])
        .filter(col("ps_supplycost") == col("min_supply_cost"))
        .select("ps_partkey", "p_name", "s_name", "min_supply_cost")
        .unique(subset=["ps_partkey"])
        .sort("min_supply_cost")
        .limit(100)
    )

    return result


def min_by_with_ties_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find the supplier with the lowest supply cost for each part."""
    partsupp = ctx.get_table("partsupp")
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")

    merged = partsupp.merge(part, left_on="ps_partkey", right_on="p_partkey")
    merged = merged.merge(supplier, left_on="ps_suppkey", right_on="s_suppkey")

    min_idx = merged.groupby(["p_partkey", "p_name"])["ps_supplycost"].idxmin()
    result = merged.loc[min_idx][["p_partkey", "p_name", "s_name", "ps_supplycost"]].rename(
        columns={"ps_supplycost": "min_supply_cost", "s_name": "supplier_name"}
    )
    result = result.sort_values("min_supply_cost").head(100)

    return result


# -----------------------------------------------------------------------------
# Additional predicate queries
# -----------------------------------------------------------------------------


def predicate_ordering_subquery_expression_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity with subquery predicate."""
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    col = ctx.col
    lit = ctx.lit

    # Get customers matching criteria
    building_customers = customer.filter(
        (col("c_mktsegment") == lit("BUILDING")) & (col("c_nationkey") == lit(1))
    ).select("c_custkey")

    result = (
        orders.filter((col("o_totalprice") > lit(100000)) & (col("o_orderdate") >= lit(date(1995, 1, 1))))
        .join(building_customers, left_on="o_custkey", right_on="c_custkey", how="semi")
        .select("o_orderkey", "o_totalprice")
    )

    return result


def predicate_ordering_subquery_pandas_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity with subquery predicate."""
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")

    building_customers = customer[(customer["c_mktsegment"] == "BUILDING") & (customer["c_nationkey"] == 1)][
        "c_custkey"
    ].unique()

    filtered_orders = orders[(orders["o_totalprice"] > 100000) & (orders["o_orderdate"] >= date(1995, 1, 1))]
    result = filtered_orders[filtered_orders["o_custkey"].isin(building_customers)][["o_orderkey", "o_totalprice"]]

    return result


# -----------------------------------------------------------------------------
# Shuffle with UNION ALL query
# -----------------------------------------------------------------------------


def shuffle_union_all_groupby_expression_impl(ctx: DataFrameContext) -> Any:
    """Complex join with UNION ALL and different data sources."""
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    # First source: orders from date range
    orders_source = (
        orders.filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .select(col("o_custkey").alias("cust_id"))
        .with_columns(lit("ORDER").alias("source_type"))
    )

    # Second source: lineitems joined with orders
    lineitem_orders = (
        orders.join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .filter(col("l_shipdate") >= lit(date(1995, 1, 1)))
        .select(col("o_custkey").alias("cust_id"))
        .with_columns(lit("LINEITEM").alias("source_type"))
    )

    # Combine and aggregate
    result = (
        orders_source.vstack(lineitem_orders).group_by("source_type").agg(col("cust_id").count().alias("record_count"))
    )

    return result


def shuffle_union_all_groupby_pandas_impl(ctx: DataFrameContext) -> Any:
    """Complex join with UNION ALL and different data sources."""
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    # First source
    orders_source = orders[orders["o_orderdate"] >= date(1995, 1, 1)][["o_custkey"]].copy()
    orders_source["source_type"] = "ORDER"
    orders_source = orders_source.rename(columns={"o_custkey": "cust_id"})

    # Second source
    merged = orders.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    lineitem_source = merged[merged["l_shipdate"] >= date(1995, 1, 1)][["o_custkey"]].copy()
    lineitem_source["source_type"] = "LINEITEM"
    lineitem_source = lineitem_source.rename(columns={"o_custkey": "cust_id"})

    # Combine using ctx.concat for platform compatibility
    combined = ctx.concat([orders_source, lineitem_source])
    result = combined.groupby("source_type", as_index=False).agg(record_count=("cust_id", "count"))

    return result


# -----------------------------------------------------------------------------
# Statistical percentiles query
# -----------------------------------------------------------------------------


def statistical_percentiles_expression_impl(ctx: DataFrameContext) -> Any:
    """Percentile calculation functions for distribution analysis."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    result = lineitem.group_by("l_returnflag", "l_linestatus").agg(
        col("l_orderkey").count().alias("record_count"),
        col("l_quantity").quantile(0.25).alias("quantity_q1"),
        col("l_quantity").quantile(0.5).alias("quantity_median"),
        col("l_quantity").quantile(0.75).alias("quantity_q3"),
        col("l_extendedprice").quantile(0.95).alias("price_p95"),
    )

    return result


def statistical_percentiles_pandas_impl(ctx: DataFrameContext) -> Any:
    """Percentile calculation functions for distribution analysis."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem.groupby(["l_returnflag", "l_linestatus"], as_index=False).agg(
        record_count=("l_orderkey", "count"),
        quantity_q1=("l_quantity", lambda x: x.quantile(0.25)),
        quantity_median=("l_quantity", "median"),
        quantity_q3=("l_quantity", lambda x: x.quantile(0.75)),
        price_p95=("l_extendedprice", lambda x: x.quantile(0.95)),
    )

    return result


# -----------------------------------------------------------------------------
# Case-insensitive string matching queries
# -----------------------------------------------------------------------------


def string_ilike_start_expression_impl(ctx: DataFrameContext) -> Any:
    """Case insensitive matching prefix pattern."""
    part = ctx.get_table("part")
    col = ctx.col

    result = part.filter(col("p_name").str.to_lowercase().str.starts_with("standard")).select(
        col("p_partkey").count().alias("count")
    )

    return result


def string_ilike_start_pandas_impl(ctx: DataFrameContext) -> Any:
    """Case insensitive matching prefix pattern."""
    part = ctx.get_table("part")

    count = len(part[part["p_name"].str.lower().str.startswith("standard", na=False)])
    result = ctx.scalar_to_df({"count": count})

    return result


def string_ilike_end_expression_impl(ctx: DataFrameContext) -> Any:
    """Case insensitive matching suffix pattern."""
    part = ctx.get_table("part")
    col = ctx.col

    result = part.filter(col("p_name").str.to_lowercase().str.ends_with("copper")).select(
        col("p_partkey").count().alias("count")
    )

    return result


def string_ilike_end_pandas_impl(ctx: DataFrameContext) -> Any:
    """Case insensitive matching suffix pattern."""
    part = ctx.get_table("part")

    count = len(part[part["p_name"].str.lower().str.endswith("copper", na=False)])
    result = ctx.scalar_to_df({"count": count})

    return result


def string_like_multi_expression_impl(ctx: DataFrameContext) -> Any:
    """Case sensitive matching multipart pattern."""
    part = ctx.get_table("part")
    col = ctx.col

    result = part.filter(col("p_name").str.contains("STEEL") & col("p_name").str.contains("BRASS")).select(
        col("p_partkey").count().alias("count")
    )

    return result


def string_like_multi_pandas_impl(ctx: DataFrameContext) -> Any:
    """Case sensitive matching multipart pattern."""
    part = ctx.get_table("part")

    count = len(part[part["p_name"].str.contains("STEEL", na=False) & part["p_name"].str.contains("BRASS", na=False)])
    result = ctx.scalar_to_df({"count": count})

    return result


def string_ilike_multi_expression_impl(ctx: DataFrameContext) -> Any:
    """Case insensitive matching multipart pattern."""
    part = ctx.get_table("part")
    col = ctx.col

    lower_name = col("p_name").str.to_lowercase()
    result = part.filter(lower_name.str.contains("steel") & lower_name.str.contains("brass")).select(
        col("p_partkey").count().alias("count")
    )

    return result


def string_ilike_multi_pandas_impl(ctx: DataFrameContext) -> Any:
    """Case insensitive matching multipart pattern."""
    part = ctx.get_table("part")

    lower_name = part["p_name"].str.lower()
    count = len(part[lower_name.str.contains("steel", na=False) & lower_name.str.contains("brass", na=False)])
    result = ctx.scalar_to_df({"count": count})

    return result


def string_like_center_insensitive_expression_impl(ctx: DataFrameContext) -> Any:
    """Case insensitive matching pattern in any location."""
    part = ctx.get_table("part")
    col = ctx.col

    result = part.filter(col("p_name").str.to_lowercase().str.contains("steel")).select(
        col("p_partkey").count().alias("count")
    )

    return result


def string_like_center_insensitive_pandas_impl(ctx: DataFrameContext) -> Any:
    """Case insensitive matching pattern in any location."""
    part = ctx.get_table("part")

    count = len(part[part["p_name"].str.lower().str.contains("steel", na=False)])
    result = ctx.scalar_to_df({"count": count})

    return result


# -----------------------------------------------------------------------------
# Additional Window queries
# -----------------------------------------------------------------------------


def window_moving_frame_expression_impl(ctx: DataFrameContext) -> Any:
    """Window aggregations with complex moving frame definitions."""
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    result = (
        orders.filter((col("o_orderdate") >= lit(date(1995, 1, 1))) & (col("o_orderdate") < lit(date(1996, 1, 1))))
        .sort("o_orderdate")
        .with_columns(
            ctx.window_avg(
                "o_totalprice",
                order_by=[("o_orderdate", True)],
            ).alias("moving_avg")
        )
        .select("o_orderkey", "o_orderdate", "o_totalprice", "moving_avg")
        .sort("o_orderdate")
    )

    return result


def window_moving_frame_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window aggregations with complex moving frame definitions."""
    orders = ctx.get_table("orders")

    filtered = orders[(orders["o_orderdate"] >= date(1995, 1, 1)) & (orders["o_orderdate"] < date(1996, 1, 1))].copy()
    filtered = filtered.sort_values("o_orderdate")
    # Rolling average with 6 order window
    filtered["moving_avg"] = filtered["o_totalprice"].rolling(window=6, min_periods=1).mean()

    result = filtered[["o_orderkey", "o_orderdate", "o_totalprice", "moving_avg"]]

    return result


def window_unbounded_frame_expression_impl(ctx: DataFrameContext) -> Any:
    """Window aggregations with the same unbounded frame definition."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineitem.filter((col("l_orderkey") >= lit(1)) & (col("l_orderkey") <= lit(5000)))
        .sort(["l_orderkey", "l_linenumber"])
        .with_columns(
            [
                col("l_quantity").first().over("l_orderkey").alias("first_line_qty"),
                col("l_quantity").last().over("l_orderkey").alias("last_line_qty"),
            ]
        )
        .select("l_orderkey", "l_linenumber", "l_shipdate", "l_quantity", "first_line_qty", "last_line_qty")
    )

    return result


def window_unbounded_frame_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window aggregations with the same unbounded frame definition."""
    lineitem = ctx.get_table("lineitem")

    filtered = lineitem[(lineitem["l_orderkey"] >= 1) & (lineitem["l_orderkey"] <= 5000)].copy()
    filtered = filtered.sort_values(["l_orderkey", "l_linenumber"])

    filtered["first_line_qty"] = filtered.groupby("l_orderkey")["l_quantity"].transform("first")
    filtered["last_line_qty"] = filtered.groupby("l_orderkey")["l_quantity"].transform("last")

    result = filtered[["l_orderkey", "l_linenumber", "l_shipdate", "l_quantity", "first_line_qty", "last_line_qty"]]

    return result


# =============================================================================
# Intrinsic Queries (Approximate Median, Date Conversion)
# =============================================================================


def intrinsic_appx_median_expression_impl(ctx: DataFrameContext) -> Any:
    """Approximate median calculation per group using quantile(0.5)."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    result = lineitem.group_by("l_shipmode").agg(col("l_quantity").quantile(0.5).alias("median_quantity"))

    return result


def intrinsic_appx_median_pandas_impl(ctx: DataFrameContext) -> Any:
    """Approximate median calculation per group using quantile(0.5)."""
    lineitem = ctx.get_table("lineitem")

    result = lineitem.groupby("l_shipmode", as_index=False).agg(median_quantity=("l_quantity", "median"))

    return result


def intrinsic_to_date_expression_impl(ctx: DataFrameContext) -> Any:
    """Count orders matching a specific date."""
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Filter for specific date and count
    result = orders.filter(col("o_orderdate") == lit(date(1995, 3, 15))).select(
        col("o_orderkey").count().alias("orders_by_month")
    )

    return result


def intrinsic_to_date_pandas_impl(ctx: DataFrameContext) -> Any:
    """Count orders matching a specific date."""
    orders = ctx.get_table("orders")

    target_date = date(1995, 3, 15)
    count = len(orders[orders["o_orderdate"] == target_date])
    result = ctx.scalar_to_df({"orders_by_month": count})

    return result


# =============================================================================
# Fulltext Queries (String Pattern Matching - DataFrame Equivalent)
# =============================================================================
# Note: DataFrames don't have SQL-style MATCH...AGAINST fulltext search.
# We implement these using string pattern matching which provides similar
# functionality for basic text search use cases.


def fulltext_simple_search_expression_impl(ctx: DataFrameContext) -> Any:
    """Basic text search using string contains pattern matching."""
    part = ctx.get_table("part")
    col = ctx.col

    # Search for parts containing "STEEL" or "COPPER" in name or comment
    result = (
        part.filter(
            col("p_name").str.contains("STEEL")
            | col("p_name").str.contains("COPPER")
            | col("p_comment").str.contains("STEEL")
            | col("p_comment").str.contains("COPPER")
        )
        .select("p_partkey", "p_name", "p_mfgr", "p_comment")
        .limit(100)
    )

    return result


def fulltext_simple_search_pandas_impl(ctx: DataFrameContext) -> Any:
    """Basic text search using string contains pattern matching."""
    part = ctx.get_table("part")

    # Search for parts containing "STEEL" or "COPPER" in name or comment
    mask = (
        part["p_name"].str.contains("STEEL", case=True, na=False)
        | part["p_name"].str.contains("COPPER", case=True, na=False)
        | part["p_comment"].str.contains("STEEL", case=True, na=False)
        | part["p_comment"].str.contains("COPPER", case=True, na=False)
    )
    result = part[mask][["p_partkey", "p_name", "p_mfgr", "p_comment"]].head(100)

    return result


def fulltext_boolean_search_expression_impl(ctx: DataFrameContext) -> Any:
    """Boolean text search with AND/NOT operators."""
    customer = ctx.get_table("customer")
    col = ctx.col

    # Must contain "BUILDING", must NOT contain "FURNITURE"
    # Also compute a simple relevance score (1 for match, 0 for no match)
    result = (
        customer.filter(col("c_comment").str.contains("BUILDING") & ~col("c_comment").str.contains("FURNITURE"))
        .with_columns(col("c_comment").str.contains("BUILDING").cast(int).alias("relevance_score"))
        .select("c_custkey", "c_name", "c_comment", "relevance_score")
        .sort("relevance_score", descending=True)
        .limit(50)
    )

    return result


def fulltext_boolean_search_pandas_impl(ctx: DataFrameContext) -> Any:
    """Boolean text search with AND/NOT operators."""
    customer = ctx.get_table("customer")

    # Must contain "BUILDING", must NOT contain "FURNITURE"
    contains_building = customer["c_comment"].str.contains("BUILDING", case=True, na=False)
    contains_furniture = customer["c_comment"].str.contains("FURNITURE", case=True, na=False)

    filtered = customer[contains_building & ~contains_furniture].copy()
    filtered["relevance_score"] = 1  # Simple relevance: all matches score 1

    result = (
        filtered[["c_custkey", "c_name", "c_comment", "relevance_score"]]
        .sort_values("relevance_score", ascending=False)
        .head(50)
    )

    return result


def fulltext_phrase_search_expression_impl(ctx: DataFrameContext) -> Any:
    """Phrase-based text search for exact phrase match."""
    supplier = ctx.get_table("supplier")
    col = ctx.col

    # Search for exact phrase "Customer Complaints" (case-insensitive for robustness)
    result = (
        supplier.filter(col("s_comment").str.to_lowercase().str.contains("customer complaints"))
        .with_columns(
            col("s_comment")
            .str.to_lowercase()
            .str.contains("customer complaints")
            .cast(int)
            .alias("phrase_match_score")
        )
        .select("s_suppkey", "s_name", "s_comment", "phrase_match_score")
        .sort("phrase_match_score", descending=True)
    )

    return result


def fulltext_phrase_search_pandas_impl(ctx: DataFrameContext) -> Any:
    """Phrase-based text search for exact phrase match."""
    supplier = ctx.get_table("supplier")

    # Search for exact phrase "Customer Complaints" (case-insensitive)
    phrase_match = supplier["s_comment"].str.lower().str.contains("customer complaints", na=False)

    filtered = supplier[phrase_match].copy()
    filtered["phrase_match_score"] = 1  # All matches score 1

    result = filtered[["s_suppkey", "s_name", "s_comment", "phrase_match_score"]].sort_values(
        "phrase_match_score", ascending=False
    )

    return result


# =============================================================================
# OLAP Queries (CUBE/ROLLUP - Multi-dimensional Aggregation)
# =============================================================================
# CUBE and ROLLUP produce multiple levels of aggregation in SQL.
# For DataFrames, we implement these using:
# - PySpark: Native cube()/rollup() methods
# - Polars/Pandas: Multiple groupby operations + union


def olap_cube_analysis_expression_impl(ctx: DataFrameContext) -> Any:
    """CUBE operation for multidimensional analysis.

    Expression-family (Polars/PySpark) implementation.
    For PySpark, we can use native .cube() method.
    For Polars, we simulate with multiple groupby + union.
    """
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    # Join tables to get nation/region info
    joined = (
        orders.filter((col("o_orderdate") >= lit(date(1995, 1, 1))) & (col("o_orderdate") < lit(date(1997, 1, 1))))
        .join(customer, col("o_custkey") == col("c_custkey"))
        .join(nation, col("c_nationkey") == col("n_nationkey"))
        .join(region, col("n_regionkey") == col("r_regionkey"))
    )

    # Simple groupby aggregation (CUBE approximation - just the most detailed level)
    # Full CUBE would require union of all dimension combinations
    result = joined.group_by("n_name", "r_name").agg(
        col("o_orderkey").count().alias("order_count"),
        col("o_totalprice").sum().alias("total_revenue"),
        col("o_totalprice").mean().alias("avg_order_value"),
    )

    return result


def olap_cube_analysis_pandas_impl(ctx: DataFrameContext) -> Any:
    """CUBE operation for multidimensional analysis.

    Pandas-family implementation using groupby.
    """
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    # Filter orders
    filtered = orders[(orders["o_orderdate"] >= date(1995, 1, 1)) & (orders["o_orderdate"] < date(1997, 1, 1))]

    # Join tables
    merged = filtered.merge(customer, left_on="o_custkey", right_on="c_custkey")
    merged = merged.merge(nation, left_on="c_nationkey", right_on="n_nationkey")
    merged = merged.merge(region, left_on="n_regionkey", right_on="r_regionkey")

    # Groupby aggregation (simplified CUBE - most detailed level)
    result = merged.groupby(["n_name", "r_name"], as_index=False).agg(
        order_count=("o_orderkey", "count"),
        total_revenue=("o_totalprice", "sum"),
        avg_order_value=("o_totalprice", "mean"),
    )

    return result


def olap_rollup_analysis_expression_impl(ctx: DataFrameContext) -> Any:
    """ROLLUP operation for hierarchical aggregation.

    Expression-family implementation.
    """
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    # Join tables
    joined = (
        orders.filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .join(customer, col("o_custkey") == col("c_custkey"))
        .join(nation, col("c_nationkey") == col("n_nationkey"))
        .join(region, col("n_regionkey") == col("r_regionkey"))
    )

    # Hierarchical aggregation (simplified ROLLUP - most detailed level)
    result = (
        joined.group_by("r_name", "n_name", "c_mktsegment")
        .agg(
            col("c_custkey").n_unique().alias("customer_count"),
            col("o_orderkey").count().alias("order_count"),
            col("o_totalprice").sum().alias("total_revenue"),
            col("o_totalprice").mean().alias("avg_order_value"),
        )
        .sort("r_name", "n_name", "c_mktsegment", nulls_last=True)
    )

    return result


def olap_rollup_analysis_pandas_impl(ctx: DataFrameContext) -> Any:
    """ROLLUP operation for hierarchical aggregation.

    Pandas-family implementation.
    """
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    # Filter and join
    filtered = orders[orders["o_orderdate"] >= date(1995, 1, 1)]
    merged = filtered.merge(customer, left_on="o_custkey", right_on="c_custkey")
    merged = merged.merge(nation, left_on="c_nationkey", right_on="n_nationkey")
    merged = merged.merge(region, left_on="n_regionkey", right_on="r_regionkey")

    # Hierarchical aggregation
    result = merged.groupby(["r_name", "n_name", "c_mktsegment"], as_index=False).agg(
        customer_count=("c_custkey", "nunique"),
        order_count=("o_orderkey", "count"),
        total_revenue=("o_totalprice", "sum"),
        avg_order_value=("o_totalprice", "mean"),
    )

    result = result.sort_values(["r_name", "n_name", "c_mktsegment"], na_position="last")

    return result


# =============================================================================
# Pivot/Unpivot Queries
# =============================================================================


def pivot_basic_expression_impl(ctx: DataFrameContext) -> Any:
    """Pivot ship modes into columns.

    Expression-family implementation using Polars pivot.
    """
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    # Filter and select
    filtered = lineitem.filter(
        (col("l_shipdate") >= lit(date(1995, 1, 1))) & (col("l_shipdate") < lit(date(1995, 4, 1)))
    ).select("l_returnflag", "l_shipmode", "l_quantity")

    # Pivot: sum l_quantity for each l_shipmode per l_returnflag
    result = filtered.group_by("l_returnflag").agg(
        col("l_quantity").filter(col("l_shipmode") == lit("AIR")).sum().alias("AIR"),
        col("l_quantity").filter(col("l_shipmode") == lit("RAIL")).sum().alias("RAIL"),
        col("l_quantity").filter(col("l_shipmode") == lit("SHIP")).sum().alias("SHIP"),
        col("l_quantity").filter(col("l_shipmode") == lit("TRUCK")).sum().alias("TRUCK"),
    )

    return result


def pivot_basic_pandas_impl(ctx: DataFrameContext) -> Any:
    """Pivot ship modes into columns.

    Pandas-family implementation using pivot_table.
    """
    lineitem = ctx.get_table("lineitem")

    # Filter
    filtered = lineitem[(lineitem["l_shipdate"] >= date(1995, 1, 1)) & (lineitem["l_shipdate"] < date(1995, 4, 1))][
        ["l_returnflag", "l_shipmode", "l_quantity"]
    ]

    # Pivot
    result = filtered.pivot_table(
        index="l_returnflag",
        columns="l_shipmode",
        values="l_quantity",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()

    return result


def unpivot_basic_expression_impl(ctx: DataFrameContext) -> Any:
    """Unpivot part dimensions into rows.

    Expression-family implementation using melt.
    """
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    # Filter and select columns to unpivot
    filtered = part.filter(col("p_partkey") <= lit(100)).select(
        "p_partkey",
        col("p_size").cast(float).alias("p_size"),
        col("p_retailprice").alias("p_retailprice"),
    )

    # Melt (unpivot) - convert p_size and p_retailprice to dimension_name/dimension_value rows
    result = filtered.melt(
        id_vars=["p_partkey"],
        value_vars=["p_size", "p_retailprice"],
        variable_name="dimension_name",
        value_name="dimension_value",
    )

    return result


def unpivot_basic_pandas_impl(ctx: DataFrameContext) -> Any:
    """Unpivot part dimensions into rows.

    Pandas-family implementation using melt.
    """
    part = ctx.get_table("part")

    # Filter and select
    filtered = part[part["p_partkey"] <= 100][["p_partkey", "p_size", "p_retailprice"]].copy()
    filtered["p_size"] = filtered["p_size"].astype(float)

    # Melt (unpivot)
    result = filtered.melt(
        id_vars=["p_partkey"],
        value_vars=["p_size", "p_retailprice"],
        var_name="dimension_name",
        value_name="dimension_value",
    )

    return result


# =============================================================================
# Optimizer Probe Queries
# =============================================================================
# These queries test SQL optimizer behavior. The key is to write them in "naive"
# form WITHOUT manually optimizing - let Catalyst/query planner do the work.
#
# IMPORTANT: Do NOT "bake in" the optimization:
# - predicate_pushdown: Filter AFTER join, not before
# - join_reordering: Keep "bad" join order, no broadcast hints
# - limit_pushdown: orderBy().limit() at end only
# - column_pruning: Select only at the very end
# - common_subexpression: Repeat full expression multiple times
# - constant_folding: Use Spark expressions, not Python math


def optimizer_distinct_elimination_expression_impl(ctx: DataFrameContext) -> Any:
    """Test DISTINCT elimination when result is already unique (PK included).

    Expression-family implementation - write naive DISTINCT on columns including PK.
    """
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Apply DISTINCT even though o_orderkey is unique (optimizer should eliminate)
    result = (
        orders.filter((col("o_orderdate") >= lit(date(1995, 1, 1))) & (col("o_orderdate") < lit(date(1996, 1, 1))))
        .select("o_orderkey", "o_custkey", "o_orderdate", "o_totalprice")
        .unique()  # Should be eliminated by optimizer since o_orderkey is unique
    )

    return result


def optimizer_distinct_elimination_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test DISTINCT elimination when result is already unique (PK included)."""
    orders = ctx.get_table("orders")

    filtered = orders[(orders["o_orderdate"] >= date(1995, 1, 1)) & (orders["o_orderdate"] < date(1996, 1, 1))]
    result = filtered[["o_orderkey", "o_custkey", "o_orderdate", "o_totalprice"]].drop_duplicates()

    return result


def optimizer_common_subexpression_expression_impl(ctx: DataFrameContext) -> Any:
    """Test Common Subexpression Elimination (CSE).

    Write the SAME complex expression multiple times - optimizer should compute once.
    """
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    # Define the complex expression (will be repeated)
    # DO NOT name it once and reuse - let optimizer find the common subexpression
    result = (
        lineitem.filter(col("l_quantity") > lit(0))
        .select(
            "l_orderkey",
            "l_partkey",
            "l_suppkey",
            "l_linenumber",
            # Repeat the same expression multiple times
            (col("l_quantity") * col("l_extendedprice") * (lit(1) - col("l_discount")) * (lit(1) + col("l_tax"))).alias(
                "revenue_with_tax"
            ),
            (col("l_quantity") * col("l_extendedprice") * (lit(1) - col("l_discount")) * (lit(1) + col("l_tax"))).alias(
                "revenue_copy"
            ),
        )
        .filter(col("revenue_with_tax") > lit(1000))
        .limit(100)
    )

    return result


def optimizer_common_subexpression_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test Common Subexpression Elimination (CSE)."""
    lineitem = ctx.get_table("lineitem")

    filtered = lineitem[lineitem["l_quantity"] > 0].copy()

    # Compute the expression multiple times (pandas will compute each time)
    expr = filtered["l_quantity"] * filtered["l_extendedprice"] * (1 - filtered["l_discount"]) * (1 + filtered["l_tax"])

    filtered["revenue_with_tax"] = expr
    filtered["revenue_copy"] = expr

    result = filtered[filtered["revenue_with_tax"] > 1000][
        ["l_orderkey", "l_partkey", "l_suppkey", "l_linenumber", "revenue_with_tax", "revenue_copy"]
    ].head(100)

    return result


def optimizer_predicate_pushdown_expression_impl(ctx: DataFrameContext) -> Any:
    """Test predicate pushdown through joins.

    IMPORTANT: Filter AFTER join to let optimizer push predicates down.
    """
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Join first, THEN filter (optimizer should push predicates down)
    result = (
        customer.join(orders, col("c_custkey") == col("o_custkey"))
        .filter(col("c_nationkey") == lit(15))  # Predicate on customer - should push before join
        .filter(col("o_orderdate") >= lit(date(1995, 1, 1)))  # Predicate on orders - should push before join
        .select("c_name", "c_mktsegment", "o_orderdate", "o_totalprice")
        .limit(100)
    )

    return result


def optimizer_predicate_pushdown_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test predicate pushdown through joins."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    # Join first, then filter (pandas doesn't optimize, but tests the pattern)
    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    filtered = merged[(merged["c_nationkey"] == 15) & (merged["o_orderdate"] >= date(1995, 1, 1))]
    result = filtered[["c_name", "c_mktsegment", "o_orderdate", "o_totalprice"]].head(100)

    return result


def optimizer_join_reordering_expression_impl(ctx: DataFrameContext) -> Any:
    """Test join reordering optimization.

    Write joins in SUBOPTIMAL order (largest table first) - optimizer should reorder.
    """
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    # Join in "bad" order: orders (largest) -> customer -> nation (smallest)
    # Good optimizer should reorder to nation -> customer -> orders
    result = (
        orders.filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .join(customer, col("o_custkey") == col("c_custkey"))
        .join(nation, col("c_nationkey") == col("n_nationkey"))
        .group_by("n_name", "c_name")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("o_totalprice").sum().alias("total_value"),
        )
    )

    return result


def optimizer_join_reordering_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test join reordering optimization."""
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")

    # Join in suboptimal order
    filtered = orders[orders["o_orderdate"] >= date(1995, 1, 1)]
    merged = filtered.merge(customer, left_on="o_custkey", right_on="c_custkey")
    merged = merged.merge(nation, left_on="c_nationkey", right_on="n_nationkey")

    result = merged.groupby(["n_name", "c_name"], as_index=False).agg(
        order_count=("o_orderkey", "count"),
        total_value=("o_totalprice", "sum"),
    )

    return result


def optimizer_limit_pushdown_expression_impl(ctx: DataFrameContext) -> Any:
    """Test limit pushdown through operations.

    Apply limit at the END only - optimizer should push partial limits down.
    """
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Join and sort, then limit at the end only
    result = (
        customer.join(orders, col("c_custkey") == col("o_custkey"))
        .filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .select("c_name", "c_mktsegment", "o_orderdate", "o_totalprice", "o_orderpriority")
        .sort("o_totalprice", descending=True)
        .limit(100)  # Optimizer should push partial limit into join
    )

    return result


def optimizer_limit_pushdown_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test limit pushdown through operations."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    filtered = merged[merged["o_orderdate"] >= date(1995, 1, 1)]
    result = (
        filtered[["c_name", "c_mktsegment", "o_orderdate", "o_totalprice", "o_orderpriority"]]
        .sort_values("o_totalprice", ascending=False)
        .head(100)
    )

    return result


def optimizer_aggregate_pushdown_expression_impl(ctx: DataFrameContext) -> Any:
    """Test aggregate pushdown before join.

    Join first, THEN aggregate - optimizer can push partial aggregates before join.
    """
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Join first, then aggregate (optimizer can push partial agg before join)
    result = (
        customer.join(orders, col("c_custkey") == col("o_custkey"))
        .filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .group_by("c_custkey", "c_name", "c_mktsegment")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("o_totalprice").sum().alias("total_spent"),
            col("o_totalprice").mean().alias("avg_order"),
        )
    )

    return result


def optimizer_aggregate_pushdown_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test aggregate pushdown before join."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    filtered = merged[merged["o_orderdate"] >= date(1995, 1, 1)]

    result = filtered.groupby(["c_custkey", "c_name", "c_mktsegment"], as_index=False).agg(
        order_count=("o_orderkey", "count"),
        total_spent=("o_totalprice", "sum"),
        avg_order=("o_totalprice", "mean"),
    )

    return result


def optimizer_constant_folding_expression_impl(ctx: DataFrameContext) -> Any:
    """Test constant folding optimization.

    Use Spark expressions for constants - optimizer should fold them at compile time.
    """
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    # Use Spark expressions for constants (optimizer should fold lit(2)*lit(3)+lit(4) to lit(10))
    result = (
        lineitem.filter(col("l_quantity") > lit(0))
        .select(
            "l_orderkey",
            "l_quantity",
            # Constant expression that should be folded
            (col("l_quantity") * (lit(2) * lit(3) + lit(4))).alias("scaled_quantity"),
            (col("l_extendedprice") * (lit(1) - lit(0.1)) / lit(10)).alias("discounted_unit_price"),
        )
        .limit(1000)
    )

    return result


def optimizer_constant_folding_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test constant folding optimization."""
    lineitem = ctx.get_table("lineitem")

    filtered = lineitem[lineitem["l_quantity"] > 0].copy()
    # In pandas, constants are evaluated at Python level anyway
    filtered["scaled_quantity"] = filtered["l_quantity"] * (2 * 3 + 4)
    filtered["discounted_unit_price"] = filtered["l_extendedprice"] * (1 - 0.1) / 10

    result = filtered[["l_orderkey", "l_quantity", "scaled_quantity", "discounted_unit_price"]].head(1000)

    return result


def optimizer_column_pruning_expression_impl(ctx: DataFrameContext) -> Any:
    """Test column pruning optimization.

    Select only at the very END - optimizer should prune unused columns at scan.
    """
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    # Don't select early - let optimizer prune columns
    result = (
        customer.join(orders, col("c_custkey") == col("o_custkey"))
        .join(lineitem, col("o_orderkey") == col("l_orderkey"))
        .filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .filter(col("l_quantity") > lit(10))
        .select("c_name")  # Only select c_name at the end - optimizer prunes all other columns
        .unique()
        .limit(100)
    )

    return result


def optimizer_column_pruning_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test column pruning optimization."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    merged = merged.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    filtered = merged[(merged["o_orderdate"] >= date(1995, 1, 1)) & (merged["l_quantity"] > 10)]

    result = filtered[["c_name"]].drop_duplicates().head(100)

    return result


def optimizer_union_optimization_expression_impl(ctx: DataFrameContext) -> Any:
    """Test union optimization.

    Use multiple unions, then sort - optimizer may combine/deduplicate scans.
    """
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Create multiple filtered views and union them
    urgent = orders.filter(col("o_orderpriority") == lit("1-URGENT")).select(
        "o_orderkey", "o_custkey", "o_orderpriority", "o_totalprice"
    )
    high = orders.filter(col("o_orderpriority") == lit("2-HIGH")).select(
        "o_orderkey", "o_custkey", "o_orderpriority", "o_totalprice"
    )
    medium = orders.filter(col("o_orderpriority") == lit("3-MEDIUM")).select(
        "o_orderkey", "o_custkey", "o_orderpriority", "o_totalprice"
    )

    # Union and sort
    result = ctx.concat([urgent, high, medium]).sort("o_totalprice", descending=True).limit(100)

    return result


def optimizer_union_optimization_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test union optimization."""
    orders = ctx.get_table("orders")

    cols = ["o_orderkey", "o_custkey", "o_orderpriority", "o_totalprice"]
    urgent = orders[orders["o_orderpriority"] == "1-URGENT"][cols]
    high = orders[orders["o_orderpriority"] == "2-HIGH"][cols]
    medium = orders[orders["o_orderpriority"] == "3-MEDIUM"][cols]

    combined = ctx.concat([urgent, high, medium])
    result = combined.sort_values("o_totalprice", ascending=False).head(100)

    return result


def optimizer_runtime_filter_expression_impl(ctx: DataFrameContext) -> Any:
    """Test runtime filter / dynamic partition pruning.

    Join with highly selective filter on dimension - Spark generates bloom filter.
    """
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    # Selective filter on part table - Spark can use this to generate runtime filter
    selective_parts = part.filter(col("p_brand") == lit("Brand#23")).filter(col("p_container") == lit("MED BOX"))

    result = (
        lineitem.join(selective_parts, col("l_partkey") == col("p_partkey"))
        .select(
            "l_orderkey",
            "l_quantity",
            "l_extendedprice",
            "p_partkey",
            "p_name",
        )
        .limit(100)
    )

    return result


def optimizer_runtime_filter_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test runtime filter / dynamic partition pruning."""
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")

    # Selective filter on part table
    selective_parts = part[(part["p_brand"] == "Brand#23") & (part["p_container"] == "MED BOX")]

    merged = lineitem.merge(selective_parts, left_on="l_partkey", right_on="p_partkey")
    result = merged[["l_orderkey", "l_quantity", "l_extendedprice", "p_partkey", "p_name"]].head(100)

    return result


# =============================================================================
# QUALIFY Queries
# =============================================================================
# QUALIFY is a SQL clause that filters window function results. In DataFrames,
# this is equivalent to computing the window function, then filtering rows.


def qualify_row_number_expression_impl(ctx: DataFrameContext) -> Any:
    """Find top 3 orders by total price for each customer using ROW_NUMBER.

    Expression-family implementation using window functions.
    """
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Join orders with customers
    joined = orders.join(customer, col("o_custkey") == col("c_custkey")).filter(
        col("o_orderdate") >= lit(date(1995, 1, 1))
    )

    # Add row number and filter (QUALIFY equivalent)
    result = (
        joined.with_columns(
            ctx.window_row_number(
                order_by=[("o_totalprice", False)],
                partition_by=["c_custkey"],
            ).alias("order_rank")
        )
        .filter(col("order_rank") <= lit(3))
        .select("c_custkey", "c_name", "o_orderkey", "o_orderdate", "o_totalprice", "order_rank")
        .sort("c_custkey", "order_rank")
    )

    return result


def qualify_row_number_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find top 3 orders by total price for each customer using ROW_NUMBER."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    # Join and filter
    joined = orders.merge(customer, left_on="o_custkey", right_on="c_custkey")
    filtered = joined[joined["o_orderdate"] >= date(1995, 1, 1)].copy()

    # Add row number within partition
    filtered["order_rank"] = filtered.groupby("c_custkey")["o_totalprice"].rank(method="first", ascending=False)

    # Filter (QUALIFY equivalent)
    cols = ["c_custkey", "c_name", "o_orderkey", "o_orderdate", "o_totalprice", "order_rank"]
    result = filtered[filtered["order_rank"] <= 3][cols].sort_values(["c_custkey", "order_rank"]).reset_index(drop=True)

    return result


def qualify_dense_rank_expression_impl(ctx: DataFrameContext) -> Any:
    """Find top 2 most expensive parts in each category using DENSE_RANK.

    Expression-family implementation using window functions.
    """
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    # Add dense rank and filter (QUALIFY equivalent)
    result = (
        part.with_columns(
            ctx.window_dense_rank(
                order_by=[("p_retailprice", False)],
                partition_by=["p_type"],
            ).alias("price_rank")
        )
        .filter(col("price_rank") <= lit(2))
        .select("p_type", "p_name", "p_retailprice", "price_rank")
        .sort("p_type", "price_rank")
    )

    return result


def qualify_dense_rank_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find top 2 most expensive parts in each category using DENSE_RANK."""
    part = ctx.get_table("part")

    df = part.copy()

    # Add dense rank within partition
    df["price_rank"] = df.groupby("p_type")["p_retailprice"].rank(method="dense", ascending=False)

    # Filter (QUALIFY equivalent)
    result = (
        df[df["price_rank"] <= 2][["p_type", "p_name", "p_retailprice", "price_rank"]]
        .sort_values(["p_type", "price_rank"])
        .reset_index(drop=True)
    )

    return result


def qualify_ntile_expression_impl(ctx: DataFrameContext) -> Any:
    """Find orders in top quartile by value for each market segment using NTILE.

    Expression-family implementation using window functions.
    """
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    col = ctx.col
    lit = ctx.lit

    # Join orders with customers and filter
    joined = orders.join(customer, col("o_custkey") == col("c_custkey")).filter(
        col("o_orderdate") >= lit(date(1995, 1, 1))
    )

    # Add ntile(4) and filter for quartile 4 (top 25%)
    result = (
        joined.with_columns(
            ctx.window_ntile(
                4,
                order_by=[("o_totalprice", True)],
                partition_by=["c_mktsegment"],
            ).alias("quartile")
        )
        .filter(col("quartile") == lit(4))
        .select("c_mktsegment", "o_orderkey", "o_totalprice", "quartile")
        .sort(col("c_mktsegment"), col("o_totalprice").desc())
    )

    return result


def qualify_ntile_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find orders in top quartile by value for each market segment using NTILE."""
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")

    # Join and filter
    joined = orders.merge(customer, left_on="o_custkey", right_on="c_custkey")
    filtered = joined[joined["o_orderdate"] >= date(1995, 1, 1)].copy()

    # Add ntile (quartile) - pandas doesn't have built-in ntile, use qcut approach
    def assign_quartile(group):
        import pandas as pd

        n = len(group)
        if n == 0:
            return group
        group = group.copy()
        # Sort by o_totalprice and assign quartiles
        group = group.sort_values("o_totalprice")
        group["quartile"] = pd.qcut(range(n), 4, labels=[1, 2, 3, 4], duplicates="drop")
        return group

    filtered = filtered.groupby("c_mktsegment", group_keys=False).apply(assign_quartile, include_groups=False)

    # Filter for top quartile
    result = (
        filtered[filtered["quartile"] == 4][["c_mktsegment", "o_orderkey", "o_totalprice", "quartile"]]
        .sort_values(["c_mktsegment", "o_totalprice"], ascending=[True, False])
        .reset_index(drop=True)
    )

    return result


def qualify_percentile_expression_impl(ctx: DataFrameContext) -> Any:
    """Find orders in top 10% by value for each order priority using PERCENT_RANK.

    Expression-family implementation using window functions.
    """
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Filter orders
    filtered = orders.filter(col("o_orderdate") >= lit(date(1995, 1, 1)))

    # Add percent_rank and filter for top 10%
    result = (
        filtered.with_columns(
            ctx.window_percent_rank(
                order_by=[("o_totalprice", True)],
                partition_by=["o_orderpriority"],
            ).alias("price_percentile")
        )
        .filter(col("price_percentile") >= lit(0.9))
        .select("o_orderpriority", "o_orderkey", "o_totalprice", "price_percentile")
        .sort(col("o_orderpriority"), col("o_totalprice").desc())
    )

    return result


def qualify_percentile_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find orders in top 10% by value for each order priority using PERCENT_RANK."""
    orders = ctx.get_table("orders")

    # Filter
    filtered = orders[orders["o_orderdate"] >= date(1995, 1, 1)].copy()

    # Add percent rank within partition
    filtered["price_percentile"] = filtered.groupby("o_orderpriority")["o_totalprice"].rank(pct=True)

    # Filter for top 10%
    result = (
        filtered[filtered["price_percentile"] >= 0.9][
            ["o_orderpriority", "o_orderkey", "o_totalprice", "price_percentile"]
        ]
        .sort_values(["o_orderpriority", "o_totalprice"], ascending=[True, False])
        .reset_index(drop=True)
    )

    return result


def qualify_cume_dist_expression_impl(ctx: DataFrameContext) -> Any:
    """Find lineitems with quantity in top 5% of their ship date using CUME_DIST.

    Expression-family implementation using window functions.
    """
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    # Filter lineitems
    filtered = lineitem.filter(
        (col("l_shipdate") >= lit(date(1995, 1, 1))) & (col("l_shipdate") < lit(date(1996, 1, 1)))
    )

    # Add cume_dist and filter for top 5%
    result = (
        filtered.with_columns(
            ctx.window_cume_dist(
                order_by=[("l_quantity", True)],
                partition_by=["l_shipdate"],
            ).alias("quantity_cumulative_dist")
        )
        .filter(col("quantity_cumulative_dist") >= lit(0.95))
        .select("l_shipdate", "l_orderkey", "l_linenumber", "l_quantity", "quantity_cumulative_dist")
        .sort(col("l_shipdate"), col("l_quantity").desc())
    )

    return result


def qualify_cume_dist_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find lineitems with quantity in top 5% of their ship date using CUME_DIST."""
    lineitem = ctx.get_table("lineitem")

    # Filter
    filtered = lineitem[
        (lineitem["l_shipdate"] >= date(1995, 1, 1)) & (lineitem["l_shipdate"] < date(1996, 1, 1))
    ].copy()

    # Add cumulative distribution - rank as fraction, ceiling-based
    def calc_cume_dist(group):
        group = group.copy()
        n = len(group)
        ranks = group["l_quantity"].rank(method="max")
        group["quantity_cumulative_dist"] = ranks / n
        return group

    filtered = filtered.groupby("l_shipdate", group_keys=False).apply(calc_cume_dist, include_groups=False)

    # Filter for top 5%
    result = (
        filtered[filtered["quantity_cumulative_dist"] >= 0.95][
            ["l_shipdate", "l_orderkey", "l_linenumber", "l_quantity", "quantity_cumulative_dist"]
        ]
        .sort_values(["l_shipdate", "l_quantity"], ascending=[True, False])
        .reset_index(drop=True)
    )

    return result


def qualify_lag_lead_expression_impl(ctx: DataFrameContext) -> Any:
    """Find orders where price increased from previous order using LAG.

    Expression-family implementation using window functions.
    """
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Join orders with customers and filter
    joined = orders.join(customer, col("o_custkey") == col("c_custkey")).filter(
        col("o_orderdate") >= lit(date(1995, 1, 1))
    )

    # Add lag and filter where price increased
    result = (
        joined.with_columns(
            ctx.window_lag(
                "o_totalprice",
                offset=1,
                partition_by=["c_custkey"],
                order_by=[("o_orderdate", True)],
            ).alias("prev_order_price")
        )
        .filter(col("o_totalprice") > col("prev_order_price"))
        .select("c_custkey", "c_name", "o_orderkey", "o_orderdate", "o_totalprice", "prev_order_price")
        .sort("c_custkey", "o_orderdate")
    )

    return result


def qualify_lag_lead_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find orders where price increased from previous order using LAG."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    # Join and filter
    joined = orders.merge(customer, left_on="o_custkey", right_on="c_custkey")
    filtered = joined[joined["o_orderdate"] >= date(1995, 1, 1)].copy()

    # Sort and add lag
    filtered = filtered.sort_values(["c_custkey", "o_orderdate"])
    filtered["prev_order_price"] = filtered.groupby("c_custkey")["o_totalprice"].shift(1)

    # Filter where price increased
    result = (
        filtered[filtered["o_totalprice"] > filtered["prev_order_price"]][
            ["c_custkey", "c_name", "o_orderkey", "o_orderdate", "o_totalprice", "prev_order_price"]
        ]
        .sort_values(["c_custkey", "o_orderdate"])
        .reset_index(drop=True)
    )

    return result


# =============================================================================
# Struct Queries
# =============================================================================
# Struct construction and field access using DataFrame APIs.


def struct_construction_expression_impl(ctx: DataFrameContext) -> Any:
    """Construct struct from columns.

    Expression-family implementation using struct construction.
    """
    customer = ctx.get_table("customer")
    col = ctx.col
    lit = ctx.lit
    struct = ctx.struct

    result = (
        customer.filter(col("c_nationkey") == lit(1))
        .select(
            "c_custkey",
            struct(col("c_name"), col("c_address"), col("c_phone")).alias("contact_info"),
            "c_acctbal",
        )
        .limit(100)
    )

    return result


def struct_construction_pandas_impl(ctx: DataFrameContext) -> Any:
    """Construct struct from columns."""
    customer = ctx.get_table("customer")

    filtered = customer[customer["c_nationkey"] == 1].copy()

    # Create dict column to represent struct
    filtered["contact_info"] = filtered.apply(
        lambda row: {"c_name": row["c_name"], "c_address": row["c_address"], "c_phone": row["c_phone"]}, axis=1
    )

    result = filtered[["c_custkey", "contact_info", "c_acctbal"]].head(100).reset_index(drop=True)

    return result


def struct_access_expression_impl(ctx: DataFrameContext) -> Any:
    """Access struct fields.

    Expression-family implementation using struct field access.
    """
    customer = ctx.get_table("customer")
    col = ctx.col
    lit = ctx.lit
    struct = ctx.struct

    # First construct struct, then access fields
    with_struct = customer.filter(col("c_nationkey") == lit(1)).select(
        "c_custkey",
        struct(col("c_name").alias("name"), col("c_phone").alias("phone"), col("c_acctbal").alias("balance")).alias(
            "info"
        ),
    )

    # Access struct fields
    result = (
        with_struct.select(
            "c_custkey",
            col("info").struct.field("name").alias("name"),
            col("info").struct.field("balance").alias("balance"),
        )
        .filter(col("balance") > lit(5000))
        .limit(100)
    )

    return result


def struct_access_pandas_impl(ctx: DataFrameContext) -> Any:
    """Access struct fields."""
    customer = ctx.get_table("customer")

    filtered = customer[customer["c_nationkey"] == 1].copy()

    # Create dict column to represent struct
    filtered["info"] = filtered.apply(
        lambda row: {"name": row["c_name"], "phone": row["c_phone"], "balance": row["c_acctbal"]}, axis=1
    )

    # Access fields from struct
    filtered["name"] = filtered["info"].apply(lambda x: x["name"])
    filtered["balance"] = filtered["info"].apply(lambda x: x["balance"])

    # Filter and select
    result = filtered[filtered["balance"] > 5000][["c_custkey", "name", "balance"]].head(100).reset_index(drop=True)

    return result


# =============================================================================
# Array Queries
# =============================================================================
# Array operations using DataFrame APIs.


def array_contains_expression_impl(ctx: DataFrameContext) -> Any:
    """Check if array contains a value.

    Expression-family implementation using array aggregation and contains.
    """
    partsupp = ctx.get_table("partsupp")
    col = ctx.col
    lit = ctx.lit

    # Aggregate parts per supplier
    supplier_parts = partsupp.group_by("ps_suppkey").agg(col("ps_partkey").list().alias("parts"))

    # Check if contains part 100
    result = supplier_parts.with_columns(col("parts").list.contains(lit(100)).alias("has_part_100")).limit(100)

    return result


def array_contains_pandas_impl(ctx: DataFrameContext) -> Any:
    """Check if array contains a value."""
    partsupp = ctx.get_table("partsupp")

    # Aggregate parts per supplier into lists
    supplier_parts = partsupp.groupby("ps_suppkey")["ps_partkey"].apply(list).reset_index()
    supplier_parts.columns = ["ps_suppkey", "parts"]

    # Check if 100 is in each list
    supplier_parts["has_part_100"] = supplier_parts["parts"].apply(lambda x: 100 in x)

    result = supplier_parts.head(100).reset_index(drop=True)

    return result


def array_distinct_expression_impl(ctx: DataFrameContext) -> Any:
    """Get distinct array elements.

    Expression-family implementation using array aggregation and unique.
    """
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    # Aggregate ship modes per order
    ship_modes = lineitem.group_by("l_orderkey").agg(col("l_shipmode").list().alias("modes"))

    # Get unique modes
    result = ship_modes.with_columns(col("modes").list.unique().alias("unique_modes")).limit(100)

    return result


def array_distinct_pandas_impl(ctx: DataFrameContext) -> Any:
    """Get distinct array elements."""
    lineitem = ctx.get_table("lineitem")

    # Aggregate ship modes per order
    ship_modes = lineitem.groupby("l_orderkey")["l_shipmode"].apply(list).reset_index()
    ship_modes.columns = ["l_orderkey", "modes"]

    # Get unique modes
    ship_modes["unique_modes"] = ship_modes["modes"].apply(lambda x: list(set(x)))

    result = ship_modes.head(100).reset_index(drop=True)

    return result


def array_length_expression_impl(ctx: DataFrameContext) -> Any:
    """Get array length/cardinality.

    Expression-family implementation using array aggregation and length.
    """
    partsupp = ctx.get_table("partsupp")
    col = ctx.col

    # Aggregate parts per supplier
    supplier_parts = partsupp.group_by("ps_suppkey").agg(col("ps_partkey").list().alias("parts"))

    # Get count and sort
    result = (
        supplier_parts.with_columns(col("parts").list.len().alias("num_parts")).sort(col("num_parts").desc()).limit(100)
    )

    return result


def array_length_pandas_impl(ctx: DataFrameContext) -> Any:
    """Get array length/cardinality."""
    partsupp = ctx.get_table("partsupp")

    # Aggregate parts per supplier
    supplier_parts = partsupp.groupby("ps_suppkey")["ps_partkey"].apply(list).reset_index()
    supplier_parts.columns = ["ps_suppkey", "parts"]

    # Get length
    supplier_parts["num_parts"] = supplier_parts["parts"].apply(len)

    # Sort by num_parts descending
    result = supplier_parts.sort_values("num_parts", ascending=False).head(100).reset_index(drop=True)

    return result


def array_min_max_expression_impl(ctx: DataFrameContext) -> Any:
    """Get min/max from array.

    Expression-family implementation using array aggregation and min/max.
    """
    orders = ctx.get_table("orders")
    col = ctx.col

    # Aggregate prices per customer
    order_prices = orders.group_by("o_custkey").agg(col("o_totalprice").list().alias("prices"))

    # Get min and max from array
    result = order_prices.with_columns(
        col("prices").list.min().alias("min_order"), col("prices").list.max().alias("max_order")
    ).limit(100)

    return result


def array_min_max_pandas_impl(ctx: DataFrameContext) -> Any:
    """Get min/max from array."""
    orders = ctx.get_table("orders")

    # Aggregate prices per customer
    order_prices = orders.groupby("o_custkey")["o_totalprice"].apply(list).reset_index()
    order_prices.columns = ["o_custkey", "prices"]

    # Get min and max
    order_prices["min_order"] = order_prices["prices"].apply(min)
    order_prices["max_order"] = order_prices["prices"].apply(max)

    result = order_prices.head(100).reset_index(drop=True)

    return result


def array_of_struct_expression_impl(ctx: DataFrameContext) -> Any:
    """Array of structs - orders with line items summary.

    Expression-family implementation using struct in array aggregation.
    """
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit
    struct = ctx.struct

    # Filter orders and join with lineitem
    filtered_orders = orders.filter(col("o_orderdate") == lit(date(1995, 3, 15)))
    joined = lineitem.join(filtered_orders, col("l_orderkey") == col("o_orderkey"))

    # Create struct and aggregate into array
    result = (
        joined.group_by("o_orderkey")
        .agg(
            struct(col("l_linenumber"), col("l_partkey"), col("l_quantity"), col("l_extendedprice"))
            .list()
            .alias("line_items")
        )
        .limit(50)
    )

    return result


def array_of_struct_pandas_impl(ctx: DataFrameContext) -> Any:
    """Array of structs - orders with line items summary."""
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    # Filter and join
    filtered_orders = orders[orders["o_orderdate"] == date(1995, 3, 15)]
    joined = lineitem.merge(filtered_orders, left_on="l_orderkey", right_on="o_orderkey")

    # Create list of dicts per order
    def agg_to_struct_list(group):
        return [
            {
                "l_linenumber": row["l_linenumber"],
                "l_partkey": row["l_partkey"],
                "l_quantity": row["l_quantity"],
                "l_extendedprice": row["l_extendedprice"],
            }
            for _, row in group.sort_values("l_linenumber").iterrows()
        ]

    result = joined.groupby("o_orderkey").apply(agg_to_struct_list, include_groups=False).reset_index()
    result.columns = ["o_orderkey", "line_items"]

    return result.head(50).reset_index(drop=True)


def array_slice_expression_impl(ctx: DataFrameContext) -> Any:
    """Get array slice/subset.

    Expression-family implementation using array slicing.
    """
    orders = ctx.get_table("orders")
    col = ctx.col

    # Aggregate prices per customer sorted descending
    order_prices = orders.group_by("o_custkey").agg(
        col("o_totalprice").sort(descending=True).list().alias("prices"), col("o_totalprice").count().alias("cnt")
    )

    # Filter for customers with at least 5 orders and get top 3
    result = (
        order_prices.filter(col("cnt") >= 5)
        .with_columns(col("prices").list.slice(0, 3).alias("top_3_orders"))
        .select("o_custkey", "top_3_orders")
        .limit(100)
    )

    return result


def array_slice_pandas_impl(ctx: DataFrameContext) -> Any:
    """Get array slice/subset."""
    orders = ctx.get_table("orders")

    # Aggregate prices per customer sorted descending
    order_prices = orders.groupby("o_custkey")["o_totalprice"].apply(lambda x: sorted(x, reverse=True)).reset_index()
    order_prices.columns = ["o_custkey", "prices"]

    # Filter for 5+ orders and get top 3
    order_prices = order_prices[order_prices["prices"].apply(len) >= 5].copy()
    order_prices["top_3_orders"] = order_prices["prices"].apply(lambda x: x[:3])

    result = order_prices[["o_custkey", "top_3_orders"]].head(100).reset_index(drop=True)

    return result


def array_sort_expression_impl(ctx: DataFrameContext) -> Any:
    """Sort array elements.

    Expression-family implementation using array sorting.
    """
    part = ctx.get_table("part")
    col = ctx.col

    # Aggregate sizes per brand
    part_sizes = part.group_by("p_brand").agg(col("p_size").list().alias("sizes"))

    # Sort the array
    result = part_sizes.with_columns(col("sizes").list.sort().alias("sorted_sizes")).limit(50)

    return result


def array_sort_pandas_impl(ctx: DataFrameContext) -> Any:
    """Sort array elements."""
    part = ctx.get_table("part")

    # Aggregate sizes per brand
    part_sizes = part.groupby("p_brand")["p_size"].apply(list).reset_index()
    part_sizes.columns = ["p_brand", "sizes"]

    # Sort each array
    part_sizes["sorted_sizes"] = part_sizes["sizes"].apply(sorted)

    result = part_sizes.head(50).reset_index(drop=True)

    return result


def array_unnest_expression_impl(ctx: DataFrameContext) -> Any:
    """Unnest/explode array back to rows.

    Expression-family implementation using array explode.
    """
    partsupp = ctx.get_table("partsupp")
    col = ctx.col
    lit = ctx.lit

    # Filter to small set and aggregate parts per supplier
    filtered = partsupp.filter(col("ps_suppkey") <= lit(10))
    supplier_parts = filtered.group_by("ps_suppkey").agg(col("ps_partkey").list().alias("parts"))

    # Explode array back to rows
    result = supplier_parts.explode("parts").rename({"parts": "part_key"})

    return result


def array_unnest_pandas_impl(ctx: DataFrameContext) -> Any:
    """Unnest/explode array back to rows."""
    partsupp = ctx.get_table("partsupp")

    # Filter and aggregate
    filtered = partsupp[partsupp["ps_suppkey"] <= 10]
    supplier_parts = filtered.groupby("ps_suppkey")["ps_partkey"].apply(list).reset_index()
    supplier_parts.columns = ["ps_suppkey", "parts"]

    # Explode
    result = supplier_parts.explode("parts").reset_index(drop=True)
    result.columns = ["ps_suppkey", "part_key"]

    return result


# =============================================================================
# Map Queries
# =============================================================================
# Map construction and access using DataFrame APIs.


def map_construction_expression_impl(ctx: DataFrameContext) -> Any:
    """Construct map from key-value pairs.

    Expression-family implementation using map construction.
    """
    partsupp = ctx.get_table("partsupp")
    col = ctx.col
    lit = ctx.lit
    map_from_entries = ctx.map_from_entries
    struct = ctx.struct

    # Filter and create map per supplier
    filtered = partsupp.filter(col("ps_suppkey") <= lit(10))

    # Group and aggregate as list of struct, then convert to map
    result = filtered.group_by("ps_suppkey").agg(
        struct(col("ps_partkey").cast("str"), col("ps_supplycost")).list().alias("entries")
    )

    # Convert entries to map
    result = result.with_columns(map_from_entries("entries").alias("part_costs")).select("ps_suppkey", "part_costs")

    return result


def map_construction_pandas_impl(ctx: DataFrameContext) -> Any:
    """Construct map from key-value pairs."""
    partsupp = ctx.get_table("partsupp")

    # Filter
    filtered = partsupp[partsupp["ps_suppkey"] <= 10]

    # Create dict per supplier
    def to_map(group):
        return {str(row["ps_partkey"]): row["ps_supplycost"] for _, row in group.iterrows()}

    result = filtered.groupby("ps_suppkey").apply(to_map, include_groups=False).reset_index()
    result.columns = ["ps_suppkey", "part_costs"]

    return result


def map_access_expression_impl(ctx: DataFrameContext) -> Any:
    """Access map values by key.

    Expression-family implementation using map element access.
    """
    partsupp = ctx.get_table("partsupp")
    col = ctx.col
    lit = ctx.lit
    map_from_entries = ctx.map_from_entries
    struct = ctx.struct

    # Create maps
    filtered = partsupp.filter(col("ps_suppkey") <= lit(10))
    with_map = (
        filtered.group_by("ps_suppkey")
        .agg(struct(col("ps_partkey").cast("str"), col("ps_supplycost")).list().alias("entries"))
        .with_columns(map_from_entries("entries").alias("part_costs"))
    )

    # Access map elements
    result = with_map.select(
        "ps_suppkey",
        col("part_costs").map.get(lit("1")).alias("cost_for_part_1"),
        col("part_costs").map.get(lit("5")).alias("cost_for_part_5"),
    ).limit(10)

    return result


def map_access_pandas_impl(ctx: DataFrameContext) -> Any:
    """Access map values by key."""
    partsupp = ctx.get_table("partsupp")

    # Create maps
    filtered = partsupp[partsupp["ps_suppkey"] <= 10]

    def to_map(group):
        return {str(row["ps_partkey"]): row["ps_supplycost"] for _, row in group.iterrows()}

    result = filtered.groupby("ps_suppkey").apply(to_map, include_groups=False).reset_index()
    result.columns = ["ps_suppkey", "part_costs"]

    # Access map elements
    result["cost_for_part_1"] = result["part_costs"].apply(lambda m: m.get("1"))
    result["cost_for_part_5"] = result["part_costs"].apply(lambda m: m.get("5"))

    result = result[["ps_suppkey", "cost_for_part_1", "cost_for_part_5"]].head(10).reset_index(drop=True)

    return result


def map_keys_values_expression_impl(ctx: DataFrameContext) -> Any:
    """Extract map keys and values.

    Expression-family implementation using map keys/values extraction.
    """
    partsupp = ctx.get_table("partsupp")
    col = ctx.col
    lit = ctx.lit
    map_from_entries = ctx.map_from_entries
    struct = ctx.struct

    # Create maps
    filtered = partsupp.filter(col("ps_suppkey") <= lit(5))
    with_map = (
        filtered.group_by("ps_suppkey")
        .agg(struct(col("ps_partkey").cast("str"), col("ps_supplycost")).list().alias("entries"))
        .with_columns(map_from_entries("entries").alias("part_costs"))
    )

    # Extract keys and values
    result = with_map.select(
        "ps_suppkey",
        col("part_costs").map.keys().alias("part_ids"),
        col("part_costs").map.values().alias("costs"),
    )

    return result


def map_keys_values_pandas_impl(ctx: DataFrameContext) -> Any:
    """Extract map keys and values."""
    partsupp = ctx.get_table("partsupp")

    # Create maps
    filtered = partsupp[partsupp["ps_suppkey"] <= 5]

    def to_map(group):
        return {str(row["ps_partkey"]): row["ps_supplycost"] for _, row in group.iterrows()}

    result = filtered.groupby("ps_suppkey").apply(to_map, include_groups=False).reset_index()
    result.columns = ["ps_suppkey", "part_costs"]

    # Extract keys and values
    result["part_ids"] = result["part_costs"].apply(lambda m: list(m.keys()))
    result["costs"] = result["part_costs"].apply(lambda m: list(m.values()))

    result = result[["ps_suppkey", "part_ids", "costs"]].reset_index(drop=True)

    return result


# =============================================================================
# Higher-Order Function Queries
# =============================================================================
# List filter, transform, and reduce operations.


def list_filter_expression_impl(ctx: DataFrameContext) -> Any:
    """Filter array elements by condition.

    Expression-family implementation using list filter.
    """
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit
    elem = ctx.element()

    # Aggregate prices per customer
    order_prices = orders.group_by("o_custkey").agg(col("o_totalprice").list().alias("prices"))

    # Filter to keep only large orders (> 100000)
    result = order_prices.with_columns(
        col("prices").list.eval(elem.filter(elem > lit(100000))).alias("large_orders")
    ).limit(100)

    return result


def list_filter_pandas_impl(ctx: DataFrameContext) -> Any:
    """Filter array elements by condition."""
    orders = ctx.get_table("orders")

    # Aggregate prices per customer
    order_prices = orders.groupby("o_custkey")["o_totalprice"].apply(list).reset_index()
    order_prices.columns = ["o_custkey", "prices"]

    # Filter to keep only large orders
    order_prices["large_orders"] = order_prices["prices"].apply(lambda x: [p for p in x if p > 100000])

    result = order_prices.head(100).reset_index(drop=True)

    return result


def list_transform_expression_impl(ctx: DataFrameContext) -> Any:
    """Transform each array element.

    Expression-family implementation using list transform.
    """
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit
    elem = ctx.element()

    # Aggregate prices per brand
    part_prices = part.group_by("p_brand").agg(col("p_retailprice").list().alias("prices"))

    # Transform to apply 10% markup
    result = part_prices.with_columns(col("prices").list.eval(elem * lit(1.1)).alias("prices_with_tax")).limit(50)

    return result


def list_transform_pandas_impl(ctx: DataFrameContext) -> Any:
    """Transform each array element."""
    part = ctx.get_table("part")

    # Aggregate prices per brand
    part_prices = part.groupby("p_brand")["p_retailprice"].apply(list).reset_index()
    part_prices.columns = ["p_brand", "prices"]

    # Transform with 10% markup
    part_prices["prices_with_tax"] = part_prices["prices"].apply(lambda x: [p * 1.1 for p in x])

    result = part_prices.head(50).reset_index(drop=True)

    return result


def list_reduce_expression_impl(ctx: DataFrameContext) -> Any:
    """Reduce array to single value.

    Expression-family implementation using list sum (as reduce equivalent).
    """
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    # Aggregate quantities per order
    quantities = lineitem.group_by("l_orderkey").agg(col("l_quantity").list().alias("qtys"))

    # Reduce to sum (most frameworks don't have general reduce, use sum)
    result = quantities.with_columns(col("qtys").list.sum().alias("total_qty")).limit(100)

    return result


def list_reduce_pandas_impl(ctx: DataFrameContext) -> Any:
    """Reduce array to single value."""
    lineitem = ctx.get_table("lineitem")

    # Aggregate quantities per order
    quantities = lineitem.groupby("l_orderkey")["l_quantity"].apply(list).reset_index()
    quantities.columns = ["l_orderkey", "qtys"]

    # Reduce to sum
    quantities["total_qty"] = quantities["qtys"].apply(sum)

    result = quantities.head(100).reset_index(drop=True)

    return result


# =============================================================================
# JSON Queries
# =============================================================================
# JSON extraction and aggregation (simplified - assumes string columns).
# NOTE: These are approximations since TPC-H doesn't have native JSON columns.


def json_extract_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Extract from JSON with simple path expressions.

    Expression-family implementation - uses string operations as JSON placeholder.
    Since TPC-H doesn't have JSON columns, we use comment fields as stand-ins.
    """
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Use order comment field - extract words as "JSON path" simulation
    # This demonstrates the pattern even without native JSON
    result = (
        orders.with_columns(
            col("o_comment").str.split(" ").list.get(0).alias("first_word"),
            col("o_comment").str.len_chars().alias("comment_length"),
        )
        .filter(col("comment_length") > lit(10))
        .select("o_orderkey", "o_comment", "first_word", "comment_length")
        .limit(1000)
    )

    return result


def json_extract_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Extract from JSON with simple path expressions."""
    orders = ctx.get_table("orders")

    # Simulate JSON extraction with string operations
    df = orders.copy()
    df["first_word"] = df["o_comment"].str.split(" ").str[0]
    df["comment_length"] = df["o_comment"].str.len()

    result = (
        df[df["comment_length"] > 10][["o_orderkey", "o_comment", "first_word", "comment_length"]]
        .head(1000)
        .reset_index(drop=True)
    )

    return result


def json_extract_nested_expression_impl(ctx: DataFrameContext) -> Any:
    """Extract from JSON with complex path expressions.

    Expression-family implementation - uses string operations as placeholder.
    """
    customer = ctx.get_table("customer")
    col = ctx.col
    lit = ctx.lit

    # Simulate nested extraction with string split operations
    result = (
        customer.with_columns(
            col("c_comment").str.split(" ").list.get(0).alias("segment_word"),
            col("c_comment").str.split(",").list.get(0).alias("first_segment"),
            col("c_comment").str.len_chars().alias("comment_len"),
        )
        .filter(col("comment_len") > lit(20))
        .select("c_custkey", "segment_word", "first_segment", "comment_len")
        .limit(500)
    )

    return result


def json_extract_nested_pandas_impl(ctx: DataFrameContext) -> Any:
    """Extract from JSON with complex path expressions."""
    customer = ctx.get_table("customer")

    # Simulate nested extraction with string operations
    df = customer.copy()
    df["segment_word"] = df["c_comment"].str.split(" ").str[0]
    df["first_segment"] = df["c_comment"].str.split(",").str[0]
    df["comment_len"] = df["c_comment"].str.len()

    result = (
        df[df["comment_len"] > 20][["c_custkey", "segment_word", "first_segment", "comment_len"]]
        .head(500)
        .reset_index(drop=True)
    )

    return result


def json_aggregates_expression_impl(ctx: DataFrameContext) -> Any:
    """Create JSON array and object with aggregate functions.

    Expression-family implementation - creates list structures as JSON equivalent.
    """
    part = ctx.get_table("part")
    col = ctx.col

    # Filter and aggregate into list structures (JSON array equivalent)
    result = (
        part.filter(col("p_type").str.contains("STEEL"))
        .group_by("p_brand")
        .agg(
            col("p_name").list().alias("part_names"),
            col("p_retailprice").list().alias("part_prices"),
            col("p_partkey").count().alias("part_count"),
        )
        .limit(100)
    )

    return result


def json_aggregates_pandas_impl(ctx: DataFrameContext) -> Any:
    """Create JSON array and object with aggregate functions."""
    part = ctx.get_table("part")

    # Filter
    filtered = part[part["p_type"].str.contains("STEEL")]

    # Aggregate
    result = (
        filtered.groupby("p_brand").agg({"p_name": list, "p_retailprice": list, "p_partkey": "count"}).reset_index()
    )
    result.columns = ["p_brand", "part_names", "part_prices", "part_count"]

    return result.head(100).reset_index(drop=True)


# =============================================================================
# Timeseries Analysis Query
# =============================================================================


def timeseries_trend_analysis_expression_impl(ctx: DataFrameContext) -> Any:
    """Time series trend analysis with aggregations.

    Expression-family implementation using date truncation and window functions.
    """
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Truncate to month and aggregate
    monthly = (
        orders.with_columns(col("o_orderdate").dt.truncate("1mo").alias("order_month"))
        .group_by("order_month")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("o_totalprice").sum().alias("monthly_revenue"),
            col("o_totalprice").mean().alias("avg_order_value"),
        )
    )

    # Add month-over-month metrics using ctx.window_lag
    result = (
        monthly.with_columns(
            ctx.window_lag("monthly_revenue", offset=1, order_by=[("order_month", True)]).alias("prev_month_revenue")
        )
        .with_columns(
            ((col("monthly_revenue") - col("prev_month_revenue")) / col("prev_month_revenue") * lit(100)).alias(
                "mom_growth_pct"
            )
        )
        .sort("order_month")
    )

    return result


def timeseries_trend_analysis_pandas_impl(ctx: DataFrameContext) -> Any:
    """Time series trend analysis with aggregations."""
    orders = ctx.get_table("orders")

    # Truncate to month
    df = orders.copy()
    df["order_month"] = df["o_orderdate"].values.astype("datetime64[M]")

    # Aggregate by month
    monthly = df.groupby("order_month").agg({"o_orderkey": "count", "o_totalprice": ["sum", "mean"]}).reset_index()
    monthly.columns = ["order_month", "order_count", "monthly_revenue", "avg_order_value"]

    # Add month-over-month metrics
    monthly = monthly.sort_values("order_month")
    monthly["prev_month_revenue"] = monthly["monthly_revenue"].shift(1)
    monthly["mom_growth_pct"] = (
        (monthly["monthly_revenue"] - monthly["prev_month_revenue"]) / monthly["prev_month_revenue"] * 100
    )

    return monthly.reset_index(drop=True)


# =============================================================================
# ASOF Join Query
# =============================================================================


def asof_join_basic_expression_impl(ctx: DataFrameContext) -> Any:
    """ASOF join: find closest prior order for each lineitem shipment.

    Expression-family implementation using join with inequality predicates.
    Note: True ASOF join semantics require specialized support. This is an approximation.
    """
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Filter lineitem to date range
    filtered_lineitem = lineitem.filter(
        (col("l_shipdate") >= lit(date(1995, 1, 1))) & (col("l_shipdate") < lit(date(1995, 2, 1)))
    )

    # Join with orders using equi-join on orderkey (left_on/right_on, not expression join)
    # True ASOF would find the closest prior order by date
    result = (
        filtered_lineitem.join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .filter(col("l_shipdate") >= col("o_orderdate"))
        .with_columns((col("l_shipdate") - col("o_orderdate")).dt.total_days().alias("days_to_ship"))
        .select("l_orderkey", "l_shipdate", "o_orderdate", "o_totalprice", "days_to_ship")
        .limit(100)
    )

    return result


def asof_join_basic_pandas_impl(ctx: DataFrameContext) -> Any:
    """ASOF join: find closest prior order for each lineitem shipment."""
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")

    # Filter lineitem
    filtered_lineitem = lineitem[
        (lineitem["l_shipdate"] >= date(1995, 1, 1)) & (lineitem["l_shipdate"] < date(1995, 2, 1))
    ]

    # Join with orders
    merged = filtered_lineitem.merge(orders, left_on="l_orderkey", right_on="o_orderkey")
    merged = merged[merged["l_shipdate"] >= merged["o_orderdate"]].copy()

    # Calculate days to ship
    merged["days_to_ship"] = (merged["l_shipdate"] - merged["o_orderdate"]).dt.days

    result = merged[["l_orderkey", "l_shipdate", "o_orderdate", "o_totalprice", "days_to_ship"]].head(100)

    return result.reset_index(drop=True)


# =============================================================================
# Query Registry
# =============================================================================

REGISTRY = QueryRegistry(benchmark="Read Primitives")

# Register all queries
_QUERIES = [
    # Aggregation queries
    DataFrameQuery(
        query_id="aggregation_distinct",
        query_name="Distinct Aggregation",
        description="Distinct count of high cardinality key on a large table",
        categories=[QueryCategory.AGGREGATE],
        expression_impl=aggregation_distinct_expression_impl,
        pandas_impl=aggregation_distinct_pandas_impl,
        sql_equivalent="SELECT COUNT(DISTINCT o_custkey) FROM orders WHERE o_orderdate >= DATE '1995-01-01'",
    ),
    DataFrameQuery(
        query_id="aggregation_distinct_groupby",
        query_name="Distinct Aggregation with Group By",
        description="Distinct count of high cardinality keys in low cardinality groups",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=aggregation_distinct_groupby_expression_impl,
        pandas_impl=aggregation_distinct_groupby_pandas_impl,
    ),
    DataFrameQuery(
        query_id="aggregation_groupby_large",
        query_name="Large Cardinality Group By",
        description="Aggregates within high cardinality grouping",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=aggregation_groupby_large_expression_impl,
        pandas_impl=aggregation_groupby_large_pandas_impl,
    ),
    DataFrameQuery(
        query_id="aggregation_groupby_small",
        query_name="Small Cardinality Group By",
        description="Aggregates within low cardinality grouping",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=aggregation_groupby_small_expression_impl,
        pandas_impl=aggregation_groupby_small_pandas_impl,
    ),
    DataFrameQuery(
        query_id="aggregation_materialize",
        query_name="Nested Aggregation",
        description="Nested aggregation requiring CTE materialization",
        categories=[QueryCategory.AGGREGATE, QueryCategory.SUBQUERY],
        expression_impl=aggregation_materialize_expression_impl,
        pandas_impl=aggregation_materialize_pandas_impl,
    ),
    DataFrameQuery(
        query_id="aggregation_materialize_subquery",
        query_name="Subquery Materialization",
        description="Complex nested aggregation with joins",
        categories=[QueryCategory.AGGREGATE, QueryCategory.SUBQUERY, QueryCategory.JOIN],
        expression_impl=aggregation_materialize_subquery_expression_impl,
        pandas_impl=aggregation_materialize_subquery_pandas_impl,
    ),
    DataFrameQuery(
        query_id="aggregation_partition",
        query_name="Partition Key Aggregation",
        description="Aggregates over the partition key",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=aggregation_partition_expression_impl,
        pandas_impl=aggregation_partition_pandas_impl,
    ),
    DataFrameQuery(
        query_id="aggregation_selective",
        query_name="Selective Aggregation",
        description="Aggregate on a small subset of rows",
        categories=[QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=aggregation_selective_expression_impl,
        pandas_impl=aggregation_selective_pandas_impl,
    ),
    DataFrameQuery(
        query_id="aggregation_simple",
        query_name="Simple Aggregation",
        description="Aggregate over all rows in table",
        categories=[QueryCategory.AGGREGATE],
        expression_impl=aggregation_simple_expression_impl,
        pandas_impl=aggregation_simple_pandas_impl,
    ),
    # Filter queries
    DataFrameQuery(
        query_id="filter_selective",
        query_name="High Selectivity Filter",
        description="High selectivity filter - few rows match",
        categories=[QueryCategory.FILTER],
        expression_impl=filter_selective_expression_impl,
        pandas_impl=filter_selective_pandas_impl,
    ),
    DataFrameQuery(
        query_id="filter_non_selective",
        query_name="Low Selectivity Filter",
        description="Low selectivity filter - many rows match",
        categories=[QueryCategory.FILTER],
        expression_impl=filter_non_selective_expression_impl,
        pandas_impl=filter_non_selective_pandas_impl,
    ),
    # Count/Limit queries
    DataFrameQuery(
        query_id="count_star",
        query_name="Count Star",
        description="Metadata-based count optimization vs full table scan",
        categories=[QueryCategory.AGGREGATE],
        expression_impl=count_star_expression_impl,
        pandas_impl=count_star_pandas_impl,
    ),
    DataFrameQuery(
        query_id="decimal_arithmetic",
        query_name="Decimal Arithmetic",
        description="Decimal precision arithmetic with complex expressions",
        categories=[QueryCategory.PROJECTION],
        expression_impl=decimal_arithmetic_expression_impl,
        pandas_impl=decimal_arithmetic_pandas_impl,
    ),
    # Order By queries
    DataFrameQuery(
        query_id="orderby_simple",
        query_name="Simple Order By",
        description="Simple ORDER BY single column",
        categories=[QueryCategory.SORT],
        expression_impl=orderby_simple_expression_impl,
        pandas_impl=orderby_simple_pandas_impl,
    ),
    DataFrameQuery(
        query_id="orderby_multi",
        query_name="Multi-Column Order By",
        description="ORDER BY multiple columns",
        categories=[QueryCategory.SORT],
        expression_impl=orderby_multi_expression_impl,
        pandas_impl=orderby_multi_pandas_impl,
    ),
    DataFrameQuery(
        query_id="orderby_desc",
        query_name="Descending Order By",
        description="ORDER BY with descending sort",
        categories=[QueryCategory.SORT],
        expression_impl=orderby_desc_expression_impl,
        pandas_impl=orderby_desc_pandas_impl,
    ),
    DataFrameQuery(
        query_id="topn",
        query_name="Top-N Query",
        description="Top-N query with ORDER BY and LIMIT",
        categories=[QueryCategory.SORT],
        expression_impl=topn_expression_impl,
        pandas_impl=topn_pandas_impl,
    ),
    DataFrameQuery(
        query_id="limit",
        query_name="Simple Limit",
        description="Simple LIMIT without ORDER BY",
        categories=[QueryCategory.SCAN],
        expression_impl=limit_expression_impl,
        pandas_impl=limit_pandas_impl,
    ),
    DataFrameQuery(
        query_id="limit_ordered",
        query_name="Ordered Limit",
        description="LIMIT clause with ordering on large result set",
        categories=[QueryCategory.SORT],
        expression_impl=limit_ordered_expression_impl,
        pandas_impl=limit_ordered_pandas_impl,
    ),
    # String queries
    DataFrameQuery(
        query_id="string_like",
        query_name="String LIKE",
        description="String LIKE pattern matching",
        categories=[QueryCategory.FILTER],
        expression_impl=string_like_expression_impl,
        pandas_impl=string_like_pandas_impl,
    ),
    DataFrameQuery(
        query_id="string_starts_with",
        query_name="String Starts With",
        description="String starts_with pattern matching",
        categories=[QueryCategory.FILTER],
        expression_impl=string_starts_with_expression_impl,
        pandas_impl=string_starts_with_pandas_impl,
    ),
    DataFrameQuery(
        query_id="string_ends_with",
        query_name="String Ends With",
        description="String ends_with pattern matching",
        categories=[QueryCategory.FILTER],
        expression_impl=string_ends_with_expression_impl,
        pandas_impl=string_ends_with_pandas_impl,
    ),
    DataFrameQuery(
        query_id="string_concat",
        query_name="String Concatenation",
        description="String concatenation",
        categories=[QueryCategory.PROJECTION],
        expression_impl=string_concat_expression_impl,
        pandas_impl=string_concat_pandas_impl,
    ),
    DataFrameQuery(
        query_id="string_substring",
        query_name="String Substring",
        description="String substring extraction",
        categories=[QueryCategory.PROJECTION],
        expression_impl=string_substring_expression_impl,
        pandas_impl=string_substring_pandas_impl,
    ),
    # Window queries
    DataFrameQuery(
        query_id="window_row_number",
        query_name="Window ROW_NUMBER",
        description="Window function ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)",
        categories=[QueryCategory.WINDOW],
        expression_impl=window_row_number_expression_impl,
        pandas_impl=window_row_number_pandas_impl,
    ),
    DataFrameQuery(
        query_id="window_rank",
        query_name="Window RANK",
        description="Window function RANK() OVER (PARTITION BY ... ORDER BY ...)",
        categories=[QueryCategory.WINDOW],
        expression_impl=window_rank_expression_impl,
        pandas_impl=window_rank_pandas_impl,
    ),
    DataFrameQuery(
        query_id="window_sum",
        query_name="Window SUM",
        description="Window function SUM() OVER (PARTITION BY ...)",
        categories=[QueryCategory.WINDOW, QueryCategory.AGGREGATE],
        expression_impl=window_sum_expression_impl,
        pandas_impl=window_sum_pandas_impl,
    ),
    DataFrameQuery(
        query_id="window_running_sum",
        query_name="Window Running Sum",
        description="Window function SUM() OVER (ORDER BY ...) - cumulative sum",
        categories=[QueryCategory.WINDOW, QueryCategory.AGGREGATE],
        expression_impl=window_running_sum_expression_impl,
        pandas_impl=window_running_sum_pandas_impl,
    ),
    # Join queries
    DataFrameQuery(
        query_id="broadcast_join_two_tables",
        query_name="Broadcast Join (2 tables)",
        description="One small table broadcast to join with one large table",
        categories=[QueryCategory.JOIN],
        expression_impl=broadcast_join_two_tables_expression_impl,
        pandas_impl=broadcast_join_two_tables_pandas_impl,
    ),
    DataFrameQuery(
        query_id="broadcast_join_three_tables",
        query_name="Broadcast Join (3 tables)",
        description="Two small tables broadcast to join with one large table",
        categories=[QueryCategory.JOIN, QueryCategory.MULTI_JOIN],
        expression_impl=broadcast_join_three_tables_expression_impl,
        pandas_impl=broadcast_join_three_tables_pandas_impl,
    ),
    DataFrameQuery(
        query_id="predicate_ordering_aggregation",
        query_name="Predicate Ordering with Aggregation",
        description="Order filter predicates by selectivity for aggregation",
        categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
        expression_impl=predicate_ordering_aggregation_expression_impl,
        pandas_impl=predicate_ordering_aggregation_pandas_impl,
    ),
    DataFrameQuery(
        query_id="shuffle_join",
        query_name="Shuffle Join",
        description="Data is redistributed based on the join keys",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE],
        expression_impl=shuffle_join_expression_impl,
        pandas_impl=shuffle_join_pandas_impl,
    ),
    DataFrameQuery(
        query_id="empty_build_join",
        query_name="Empty Build Side Join",
        description="Join when build side produces no rows (edge case handling)",
        categories=[QueryCategory.JOIN],
        expression_impl=empty_build_join_expression_impl,
        pandas_impl=empty_build_join_pandas_impl,
    ),
    # Additional Filter queries
    DataFrameQuery(
        query_id="filter_bigint_selective",
        query_name="Bigint Selective Filter",
        description="Equality predicate with high selectivity on integer column",
        categories=[QueryCategory.FILTER],
        expression_impl=filter_bigint_selective_expression_impl,
        pandas_impl=filter_bigint_selective_pandas_impl,
    ),
    DataFrameQuery(
        query_id="filter_bigint_non_selective",
        query_name="Bigint Non-Selective Filter",
        description="Range predicate with low selectivity on large table",
        categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
        expression_impl=filter_bigint_non_selective_expression_impl,
        pandas_impl=filter_bigint_non_selective_pandas_impl,
    ),
    DataFrameQuery(
        query_id="filter_bigint_in_list_selective",
        query_name="Bigint IN List Filter",
        description="IN-list predicate with highly selective integer values",
        categories=[QueryCategory.FILTER],
        expression_impl=filter_bigint_in_list_expression_impl,
        pandas_impl=filter_bigint_in_list_pandas_impl,
    ),
    DataFrameQuery(
        query_id="filter_decimal_selective",
        query_name="Decimal Selective Filter",
        description="Compound equality predicate with multiple decimal columns",
        categories=[QueryCategory.FILTER],
        expression_impl=filter_decimal_selective_expression_impl,
        pandas_impl=filter_decimal_selective_pandas_impl,
    ),
    DataFrameQuery(
        query_id="filter_decimal_non_selective",
        query_name="Decimal Non-Selective Filter",
        description="Range predicate on decimal column with low selectivity",
        categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
        expression_impl=filter_decimal_non_selective_expression_impl,
        pandas_impl=filter_decimal_non_selective_pandas_impl,
    ),
    DataFrameQuery(
        query_id="filter_string_selective",
        query_name="String Selective Filter",
        description="Exact string equality with high selectivity on varchar column",
        categories=[QueryCategory.FILTER],
        expression_impl=filter_string_selective_expression_impl,
        pandas_impl=filter_string_selective_pandas_impl,
    ),
    DataFrameQuery(
        query_id="filter_string_non_selective",
        query_name="String Non-Selective Filter",
        description="String comparison with low selectivity (most rows match)",
        categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
        expression_impl=filter_string_non_selective_expression_impl,
        pandas_impl=filter_string_non_selective_pandas_impl,
    ),
    DataFrameQuery(
        query_id="filter_in_predicate_selective",
        query_name="IN Predicate with Subquery",
        description="IN predicate with subquery and selective filtering",
        categories=[QueryCategory.FILTER, QueryCategory.SUBQUERY],
        expression_impl=filter_in_predicate_subquery_expression_impl,
        pandas_impl=filter_in_predicate_subquery_pandas_impl,
    ),
    # Additional GroupBy queries
    DataFrameQuery(
        query_id="groupby_bigint_highndv",
        query_name="High NDV GroupBy",
        description="GROUP BY with high distinct value count (many groups)",
        categories=[QueryCategory.GROUP_BY, QueryCategory.AGGREGATE],
        expression_impl=groupby_highndv_expression_impl,
        pandas_impl=groupby_highndv_pandas_impl,
    ),
    DataFrameQuery(
        query_id="groupby_bigint_lowndv",
        query_name="Low NDV GroupBy",
        description="GROUP BY with low distinct value count (few groups)",
        categories=[QueryCategory.GROUP_BY, QueryCategory.AGGREGATE],
        expression_impl=groupby_lowndv_expression_impl,
        pandas_impl=groupby_lowndv_pandas_impl,
    ),
    DataFrameQuery(
        query_id="groupby_bigint_pk",
        query_name="Primary Key GroupBy",
        description="GROUP BY on primary key (one row per group)",
        categories=[QueryCategory.GROUP_BY, QueryCategory.AGGREGATE],
        expression_impl=groupby_pk_expression_impl,
        pandas_impl=groupby_pk_pandas_impl,
    ),
    DataFrameQuery(
        query_id="groupby_decimal_highndv",
        query_name="High NDV Decimal GroupBy",
        description="GROUP BY with high cardinality decimal column",
        categories=[QueryCategory.GROUP_BY, QueryCategory.AGGREGATE],
        expression_impl=groupby_decimal_highndv_expression_impl,
        pandas_impl=groupby_decimal_highndv_pandas_impl,
    ),
    DataFrameQuery(
        query_id="groupby_decimal_lowndv",
        query_name="Low NDV Decimal GroupBy",
        description="GROUP BY with low cardinality decimal column",
        categories=[QueryCategory.GROUP_BY, QueryCategory.AGGREGATE],
        expression_impl=groupby_decimal_lowndv_expression_impl,
        pandas_impl=groupby_decimal_lowndv_pandas_impl,
    ),
    # Additional OrderBy queries
    DataFrameQuery(
        query_id="orderby_all",
        query_name="Full Table Order By",
        description="Sort on full table with simple integer ordering",
        categories=[QueryCategory.SORT],
        expression_impl=orderby_all_expression_impl,
        pandas_impl=orderby_all_pandas_impl,
    ),
    DataFrameQuery(
        query_id="orderby_bigint",
        query_name="Bigint Order By",
        description="Sort with aggregation results on integer column",
        categories=[QueryCategory.SORT, QueryCategory.AGGREGATE],
        expression_impl=orderby_bigint_expression_impl,
        pandas_impl=orderby_bigint_pandas_impl,
    ),
    DataFrameQuery(
        query_id="orderby_bigint_expression",
        query_name="Expression Order By",
        description="Sort on computed expressions with DESC ordering",
        categories=[QueryCategory.SORT, QueryCategory.PROJECTION],
        expression_impl=orderby_expression_expression_impl,
        pandas_impl=orderby_expression_pandas_impl,
    ),
    DataFrameQuery(
        query_id="orderby_multicol",
        query_name="Multi-Column Complex Order By",
        description="Complex multi-column sort with string, date, and decimal columns",
        categories=[QueryCategory.SORT],
        expression_impl=orderby_multicol_expression_impl,
        pandas_impl=orderby_multicol_pandas_impl,
    ),
    DataFrameQuery(
        query_id="orderby_shortstrings",
        query_name="Short Strings Order By",
        description="Sort on short string columns with DISTINCT operation",
        categories=[QueryCategory.SORT],
        expression_impl=orderby_shortstrings_expression_impl,
        pandas_impl=orderby_shortstrings_pandas_impl,
    ),
    # Additional Shuffle/Join queries
    DataFrameQuery(
        query_id="shuffle_inner_join_one_to_many_string_with_groupby",
        query_name="Inner Join with GroupBy",
        description="Standard inner join with one-to-many relationship",
        categories=[QueryCategory.JOIN, QueryCategory.GROUP_BY, QueryCategory.AGGREGATE],
        expression_impl=shuffle_inner_join_groupby_expression_impl,
        pandas_impl=shuffle_inner_join_groupby_pandas_impl,
    ),
    DataFrameQuery(
        query_id="shuffle_left_join_one_to_many_string_with_groupby",
        query_name="Left Join with GroupBy",
        description="LEFT JOIN with preservation of all left-side rows",
        categories=[QueryCategory.JOIN, QueryCategory.GROUP_BY, QueryCategory.AGGREGATE],
        expression_impl=shuffle_left_join_groupby_expression_impl,
        pandas_impl=shuffle_left_join_groupby_pandas_impl,
    ),
    DataFrameQuery(
        query_id="shuffle_full_join_one_to_many_string_with_groupby",
        query_name="Full Outer Join with GroupBy",
        description="FULL OUTER JOIN with string grouping and aggregation",
        categories=[QueryCategory.JOIN, QueryCategory.GROUP_BY, QueryCategory.AGGREGATE],
        expression_impl=shuffle_full_join_groupby_expression_impl,
        pandas_impl=shuffle_full_join_groupby_pandas_impl,
    ),
    DataFrameQuery(
        query_id="shuffle_1mb_rows",
        query_name="Self Join with Hash Collision",
        description="Self-join with hash collision handling on large table",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE],
        expression_impl=shuffle_self_join_expression_impl,
        pandas_impl=shuffle_self_join_pandas_impl,
    ),
    # Additional String queries
    DataFrameQuery(
        query_id="string_equal_predicate",
        query_name="String Equality",
        description="Exact string equality with selective matching",
        categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
        expression_impl=string_equal_expression_impl,
        pandas_impl=string_equal_pandas_impl,
    ),
    DataFrameQuery(
        query_id="string_equal_predicate_lower",
        query_name="String Equality (Case Insensitive)",
        description="Equality predicate after applying case conversion",
        categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
        expression_impl=string_equal_lower_expression_impl,
        pandas_impl=string_equal_lower_pandas_impl,
    ),
    DataFrameQuery(
        query_id="string_in_predicate",
        query_name="String IN Predicate",
        description="IN predicate with string values",
        categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
        expression_impl=string_in_predicate_expression_impl,
        pandas_impl=string_in_predicate_pandas_impl,
    ),
    DataFrameQuery(
        query_id="string_like_predicate_center",
        query_name="String LIKE Center",
        description="Case sensitive matching pattern in any location",
        categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
        expression_impl=string_like_center_expression_impl,
        pandas_impl=string_like_center_pandas_impl,
    ),
    DataFrameQuery(
        query_id="string_like_predicate_end",
        query_name="String LIKE Suffix",
        description="Case sensitive matching suffix pattern",
        categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
        expression_impl=string_like_suffix_expression_impl,
        pandas_impl=string_like_suffix_pandas_impl,
    ),
    DataFrameQuery(
        query_id="string_like_predicate_start",
        query_name="String LIKE Prefix",
        description="Case sensitive matching prefix pattern",
        categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
        expression_impl=string_like_prefix_expression_impl,
        pandas_impl=string_like_prefix_pandas_impl,
    ),
    # Additional Window queries
    DataFrameQuery(
        query_id="window_growing_frame",
        query_name="Window Growing Frame",
        description="Running sum window aggregation with growing frame size",
        categories=[QueryCategory.WINDOW, QueryCategory.AGGREGATE],
        expression_impl=window_growing_frame_expression_impl,
        pandas_impl=window_growing_frame_pandas_impl,
    ),
    DataFrameQuery(
        query_id="window_lead_lag_same_frame",
        query_name="Window Lead/Lag",
        description="Offset window functions over the same frame",
        categories=[QueryCategory.WINDOW],
        expression_impl=window_lead_lag_expression_impl,
        pandas_impl=window_lead_lag_pandas_impl,
    ),
    DataFrameQuery(
        query_id="window_multiple_orderings",
        query_name="Window Dense Rank",
        description="Window function DENSE_RANK() OVER (PARTITION BY ... ORDER BY ...)",
        categories=[QueryCategory.WINDOW],
        expression_impl=window_dense_rank_expression_impl,
        pandas_impl=window_dense_rank_pandas_impl,
    ),
    # Additional Predicate queries
    DataFrameQuery(
        query_id="predicate_ordering_aggregation_groupby",
        query_name="Predicate Ordering with GroupBy",
        description="Order filter predicates by selectivity for aggregation within a low cardinality grouping",
        categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.AGGREGATE],
        expression_impl=predicate_ordering_groupby_expression_impl,
        pandas_impl=predicate_ordering_groupby_pandas_impl,
    ),
    DataFrameQuery(
        query_id="predicate_ordering_costs",
        query_name="Predicate Ordering Costs",
        description="Order filter predicates by selectivity with result projection only",
        categories=[QueryCategory.FILTER, QueryCategory.PROJECTION],
        expression_impl=predicate_ordering_costs_expression_impl,
        pandas_impl=predicate_ordering_costs_pandas_impl,
    ),
    # Additional Broadcast/Exchange queries
    DataFrameQuery(
        query_id="broadcast_join_four_tables",
        query_name="Broadcast Join (4 tables)",
        description="Three small tables broadcast to join with one large table",
        categories=[QueryCategory.JOIN, QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE],
        expression_impl=broadcast_join_four_tables_expression_impl,
        pandas_impl=broadcast_join_four_tables_pandas_impl,
    ),
    DataFrameQuery(
        query_id="exchange_broadcast",
        query_name="Exchange Broadcast",
        description="One small table is copied to all nodes that have the large table",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE],
        expression_impl=exchange_broadcast_expression_impl,
        pandas_impl=exchange_broadcast_pandas_impl,
    ),
    DataFrameQuery(
        query_id="exchange_merge",
        query_name="Exchange Merge",
        description="Sorted data from multiple nodes is combined while keeping the sort order",
        categories=[QueryCategory.JOIN, QueryCategory.SORT],
        expression_impl=exchange_merge_expression_impl,
        pandas_impl=exchange_merge_pandas_impl,
    ),
    DataFrameQuery(
        query_id="exchange_shuffle",
        query_name="Exchange Shuffle",
        description="Data is redistributed based on the join keys so matching rows end up on the same node",
        categories=[QueryCategory.JOIN],
        expression_impl=exchange_shuffle_expression_impl,
        pandas_impl=exchange_shuffle_pandas_impl,
    ),
    # TopN queries
    DataFrameQuery(
        query_id="topn_aggregate_2columns",
        query_name="TopN with Aggregation",
        description="Top 10 limit returning 2 columns after aggregation and computed ordering",
        categories=[QueryCategory.SORT, QueryCategory.AGGREGATE],
        expression_impl=topn_aggregate_expression_impl,
        pandas_impl=topn_aggregate_pandas_impl,
    ),
    DataFrameQuery(
        query_id="topn_ordered_allcols",
        query_name="TopN All Columns",
        description="Top-10 limit returning all columns after ordering over all table rows",
        categories=[QueryCategory.SORT, QueryCategory.SCAN],
        expression_impl=topn_allcols_expression_impl,
        pandas_impl=topn_allcols_pandas_impl,
    ),
    # Statistical queries
    DataFrameQuery(
        query_id="statistical_variance_stddev",
        query_name="Variance and StdDev",
        description="Variance and standard deviation calculations",
        categories=[QueryCategory.AGGREGATE],
        expression_impl=statistical_variance_expression_impl,
        pandas_impl=statistical_variance_pandas_impl,
    ),
    DataFrameQuery(
        query_id="statistical_correlation",
        query_name="Correlation Analysis",
        description="Correlation analysis between numeric columns",
        categories=[QueryCategory.AGGREGATE],
        expression_impl=statistical_correlation_expression_impl,
        pandas_impl=statistical_correlation_pandas_impl,
    ),
    # Long predicate query
    DataFrameQuery(
        query_id="long_predicate",
        query_name="Long Predicate",
        description="Query with many conjunctive predicates across multiple tables",
        categories=[QueryCategory.FILTER, QueryCategory.JOIN, QueryCategory.MULTI_JOIN],
        expression_impl=long_predicate_expression_impl,
        pandas_impl=long_predicate_pandas_impl,
    ),
    # Min/Max By queries
    DataFrameQuery(
        query_id="max_by_simple",
        query_name="MAX_BY Simple",
        description="Find the customer with the highest account balance in each nation",
        categories=[QueryCategory.AGGREGATE, QueryCategory.JOIN],
        expression_impl=max_by_simple_expression_impl,
        pandas_impl=max_by_simple_pandas_impl,
    ),
    DataFrameQuery(
        query_id="min_by_simple",
        query_name="MIN_BY Simple",
        description="Find the customer with the lowest account balance in each nation",
        categories=[QueryCategory.AGGREGATE, QueryCategory.JOIN],
        expression_impl=min_by_simple_expression_impl,
        pandas_impl=min_by_simple_pandas_impl,
    ),
    # Array queries (semi-structured)
    DataFrameQuery(
        query_id="array_agg_simple",
        query_name="Array Aggregation",
        description="Aggregate part keys into arrays per supplier",
        categories=[QueryCategory.AGGREGATE],
        expression_impl=array_agg_simple_expression_impl,
        pandas_impl=array_agg_simple_pandas_impl,
    ),
    DataFrameQuery(
        query_id="array_agg_distinct",
        query_name="Distinct Array Aggregation",
        description="Distinct array aggregation",
        categories=[QueryCategory.AGGREGATE],
        expression_impl=array_agg_distinct_expression_impl,
        pandas_impl=array_agg_distinct_pandas_impl,
    ),
    # Additional filter queries
    DataFrameQuery(
        query_id="filter_decimal_in_list_selective",
        query_name="Decimal IN List Filter",
        description="IN-list predicate with decimal values and selectivity",
        categories=[QueryCategory.FILTER],
        expression_impl=filter_decimal_in_list_expression_impl,
        pandas_impl=filter_decimal_in_list_pandas_impl,
    ),
    DataFrameQuery(
        query_id="filter_string_like",
        query_name="String LIKE Filter",
        description="LIKE predicate with substring pattern matching",
        categories=[QueryCategory.FILTER],
        expression_impl=filter_string_like_expression_impl,
        pandas_impl=filter_string_like_pandas_impl,
    ),
    # Additional orderby queries
    DataFrameQuery(
        query_id="orderby_decimal16",
        query_name="Decimal Order By",
        description="Multi-column sort with mixed ASC/DESC on decimal columns",
        categories=[QueryCategory.SORT],
        expression_impl=orderby_decimal_expression_impl,
        pandas_impl=orderby_decimal_pandas_impl,
    ),
    # Min/Max runtime filter
    DataFrameQuery(
        query_id="min_max_runtime_filter",
        query_name="Min/Max Runtime Filter",
        description="Bloom filter and runtime filter effectiveness for join optimization",
        categories=[QueryCategory.FILTER, QueryCategory.JOIN],
        expression_impl=min_max_runtime_filter_expression_impl,
        pandas_impl=min_max_runtime_filter_pandas_impl,
    ),
    # Max/Min By complex queries
    DataFrameQuery(
        query_id="max_by_complex",
        query_name="MAX_BY Complex",
        description="Find the most expensive order for each customer segment",
        categories=[QueryCategory.AGGREGATE, QueryCategory.JOIN],
        expression_impl=max_by_complex_expression_impl,
        pandas_impl=max_by_complex_pandas_impl,
    ),
    DataFrameQuery(
        query_id="min_by_complex",
        query_name="MIN_BY Complex",
        description="Find the cheapest part for each brand",
        categories=[QueryCategory.AGGREGATE],
        expression_impl=min_by_complex_expression_impl,
        pandas_impl=min_by_complex_pandas_impl,
    ),
    # Modern SQL: ANY_VALUE queries
    DataFrameQuery(
        query_id="any_value_simple",
        query_name="ANY_VALUE Simple",
        description="Select any customer name per market segment (faster than MIN/MAX)",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=any_value_simple_expression_impl,
        pandas_impl=any_value_simple_pandas_impl,
    ),
    DataFrameQuery(
        query_id="any_value_with_filter",
        query_name="ANY_VALUE with Filter",
        description="Any value with additional aggregates",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=any_value_with_filter_expression_impl,
        pandas_impl=any_value_with_filter_pandas_impl,
    ),
    # Modern SQL: GROUP BY ALL queries
    DataFrameQuery(
        query_id="groupby_all_simple",
        query_name="GROUP BY ALL Simple",
        description="Automatic grouping by all non-aggregate columns",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=groupby_all_simple_expression_impl,
        pandas_impl=groupby_all_simple_pandas_impl,
    ),
    DataFrameQuery(
        query_id="groupby_all_complex",
        query_name="GROUP BY ALL Complex",
        description="GROUP BY ALL with multiple non-aggregate expressions",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=groupby_all_complex_expression_impl,
        pandas_impl=groupby_all_complex_pandas_impl,
    ),
    # Modern SQL: ORDER BY ALL queries
    DataFrameQuery(
        query_id="orderby_all_simple",
        query_name="ORDER BY ALL Simple",
        description="Order by all columns in SELECT list",
        categories=[QueryCategory.SORT, QueryCategory.JOIN, QueryCategory.AGGREGATE],
        expression_impl=orderby_all_simple_expression_impl,
        pandas_impl=orderby_all_simple_pandas_impl,
    ),
    DataFrameQuery(
        query_id="orderby_all_desc",
        query_name="ORDER BY ALL Descending",
        description="ORDER BY ALL with descending direction",
        categories=[QueryCategory.SORT, QueryCategory.AGGREGATE],
        expression_impl=orderby_all_desc_expression_impl,
        pandas_impl=orderby_all_desc_pandas_impl,
    ),
    # Max/Min By with ties queries
    DataFrameQuery(
        query_id="max_by_with_ties",
        query_name="MAX_BY with Ties",
        description="Find the supplier with the highest supply cost for each part",
        categories=[QueryCategory.AGGREGATE, QueryCategory.JOIN, QueryCategory.MULTI_JOIN],
        expression_impl=max_by_with_ties_expression_impl,
        pandas_impl=max_by_with_ties_pandas_impl,
    ),
    DataFrameQuery(
        query_id="min_by_with_ties",
        query_name="MIN_BY with Ties",
        description="Find the supplier with the lowest supply cost for each part",
        categories=[QueryCategory.AGGREGATE, QueryCategory.JOIN, QueryCategory.MULTI_JOIN],
        expression_impl=min_by_with_ties_expression_impl,
        pandas_impl=min_by_with_ties_pandas_impl,
    ),
    # Additional predicate queries
    DataFrameQuery(
        query_id="predicate_ordering_subquery",
        query_name="Predicate Ordering with Subquery",
        description="Order filter predicates by selectivity with subquery predicate",
        categories=[QueryCategory.FILTER, QueryCategory.SUBQUERY, QueryCategory.JOIN],
        expression_impl=predicate_ordering_subquery_expression_impl,
        pandas_impl=predicate_ordering_subquery_pandas_impl,
    ),
    # Shuffle with UNION ALL
    DataFrameQuery(
        query_id="shuffle_inner_join_union_all_with_groupby",
        query_name="Union All with GroupBy",
        description="Complex join with UNION ALL and different data sources",
        categories=[QueryCategory.JOIN, QueryCategory.GROUP_BY, QueryCategory.AGGREGATE],
        expression_impl=shuffle_union_all_groupby_expression_impl,
        pandas_impl=shuffle_union_all_groupby_pandas_impl,
    ),
    # Statistical percentiles
    DataFrameQuery(
        query_id="statistical_percentiles",
        query_name="Statistical Percentiles",
        description="Percentile calculation functions for distribution analysis",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=statistical_percentiles_expression_impl,
        pandas_impl=statistical_percentiles_pandas_impl,
    ),
    # Case-insensitive string matching
    DataFrameQuery(
        query_id="string_ilike_predicate_start",
        query_name="String ILIKE Prefix",
        description="Case insensitive matching prefix pattern",
        categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
        expression_impl=string_ilike_start_expression_impl,
        pandas_impl=string_ilike_start_pandas_impl,
    ),
    DataFrameQuery(
        query_id="string_ilike_predicate_end",
        query_name="String ILIKE Suffix",
        description="Case insensitive matching suffix pattern",
        categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
        expression_impl=string_ilike_end_expression_impl,
        pandas_impl=string_ilike_end_pandas_impl,
    ),
    DataFrameQuery(
        query_id="string_like_predicate_multi",
        query_name="String LIKE Multi",
        description="Case sensitive matching multipart pattern",
        categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
        expression_impl=string_like_multi_expression_impl,
        pandas_impl=string_like_multi_pandas_impl,
    ),
    DataFrameQuery(
        query_id="string_ilike_predicate_multi",
        query_name="String ILIKE Multi",
        description="Case insensitive matching multipart pattern",
        categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
        expression_impl=string_ilike_multi_expression_impl,
        pandas_impl=string_ilike_multi_pandas_impl,
    ),
    DataFrameQuery(
        query_id="string_like_predicate_center_insensitive",
        query_name="String ILIKE Center",
        description="Case insensitive matching pattern in any location",
        categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
        expression_impl=string_like_center_insensitive_expression_impl,
        pandas_impl=string_like_center_insensitive_pandas_impl,
    ),
    # Additional window queries
    DataFrameQuery(
        query_id="window_moving_frame",
        query_name="Window Moving Frame",
        description="Window aggregations with complex moving frame definitions",
        categories=[QueryCategory.WINDOW, QueryCategory.AGGREGATE],
        expression_impl=window_moving_frame_expression_impl,
        pandas_impl=window_moving_frame_pandas_impl,
    ),
    DataFrameQuery(
        query_id="window_unbounded_frame",
        query_name="Window Unbounded Frame",
        description="Window aggregations with the same unbounded frame definition",
        categories=[QueryCategory.WINDOW],
        expression_impl=window_unbounded_frame_expression_impl,
        pandas_impl=window_unbounded_frame_pandas_impl,
    ),
    # Intrinsic queries
    DataFrameQuery(
        query_id="intrinsic_appx_median",
        query_name="Approximate Median",
        description="Approximate statistical function (PERCENTILE_CONT for median)",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=intrinsic_appx_median_expression_impl,
        pandas_impl=intrinsic_appx_median_pandas_impl,
    ),
    DataFrameQuery(
        query_id="intrinsic_to_date",
        query_name="Date Conversion Filter",
        description="Date parsing and conversion function performance",
        categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
        expression_impl=intrinsic_to_date_expression_impl,
        pandas_impl=intrinsic_to_date_pandas_impl,
    ),
    # Fulltext queries (using string pattern matching as DataFrame equivalent)
    DataFrameQuery(
        query_id="fulltext_simple_search",
        query_name="Simple Text Search",
        description="Basic full-text search using string pattern matching",
        categories=[QueryCategory.FILTER],
        expression_impl=fulltext_simple_search_expression_impl,
        pandas_impl=fulltext_simple_search_pandas_impl,
    ),
    DataFrameQuery(
        query_id="fulltext_boolean_search",
        query_name="Boolean Text Search",
        description="Boolean text search with AND/NOT operators",
        categories=[QueryCategory.FILTER, QueryCategory.SORT],
        expression_impl=fulltext_boolean_search_expression_impl,
        pandas_impl=fulltext_boolean_search_pandas_impl,
    ),
    DataFrameQuery(
        query_id="fulltext_phrase_search",
        query_name="Phrase Text Search",
        description="Phrase-based text search with ranking",
        categories=[QueryCategory.FILTER, QueryCategory.SORT],
        expression_impl=fulltext_phrase_search_expression_impl,
        pandas_impl=fulltext_phrase_search_pandas_impl,
    ),
    # OLAP queries (CUBE/ROLLUP multi-dimensional aggregation)
    DataFrameQuery(
        query_id="olap_cube_analysis",
        query_name="OLAP CUBE Analysis",
        description="CUBE operation for multidimensional analysis",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY, QueryCategory.JOIN],
        expression_impl=olap_cube_analysis_expression_impl,
        pandas_impl=olap_cube_analysis_pandas_impl,
    ),
    DataFrameQuery(
        query_id="olap_rollup_analysis",
        query_name="OLAP ROLLUP Analysis",
        description="ROLLUP operation for hierarchical aggregation",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY, QueryCategory.JOIN, QueryCategory.SORT],
        expression_impl=olap_rollup_analysis_expression_impl,
        pandas_impl=olap_rollup_analysis_pandas_impl,
    ),
    # Pivot/Unpivot queries
    DataFrameQuery(
        query_id="pivot_basic",
        query_name="Basic Pivot",
        description="Pivot ship modes into columns",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=pivot_basic_expression_impl,
        pandas_impl=pivot_basic_pandas_impl,
    ),
    DataFrameQuery(
        query_id="unpivot_basic",
        query_name="Basic Unpivot",
        description="Unpivot part dimensions into rows",
        categories=[QueryCategory.PROJECTION],
        expression_impl=unpivot_basic_expression_impl,
        pandas_impl=unpivot_basic_pandas_impl,
    ),
    # Optimizer probe queries - test optimizer behavior with "naive" query patterns
    DataFrameQuery(
        query_id="optimizer_distinct_elimination",
        query_name="Optimizer: Distinct Elimination",
        description="Test DISTINCT elimination when result is already unique",
        categories=[QueryCategory.FILTER, QueryCategory.PROJECTION],
        expression_impl=optimizer_distinct_elimination_expression_impl,
        pandas_impl=optimizer_distinct_elimination_pandas_impl,
    ),
    DataFrameQuery(
        query_id="optimizer_common_subexpression",
        query_name="Optimizer: Common Subexpression",
        description="Test Common Subexpression Elimination (CSE)",
        categories=[QueryCategory.PROJECTION, QueryCategory.FILTER],
        expression_impl=optimizer_common_subexpression_expression_impl,
        pandas_impl=optimizer_common_subexpression_pandas_impl,
    ),
    DataFrameQuery(
        query_id="optimizer_predicate_pushdown",
        query_name="Optimizer: Predicate Pushdown",
        description="Test predicate pushdown through joins",
        categories=[QueryCategory.JOIN, QueryCategory.FILTER],
        expression_impl=optimizer_predicate_pushdown_expression_impl,
        pandas_impl=optimizer_predicate_pushdown_pandas_impl,
    ),
    DataFrameQuery(
        query_id="optimizer_join_reordering",
        query_name="Optimizer: Join Reordering",
        description="Test join reordering based on cardinality",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=optimizer_join_reordering_expression_impl,
        pandas_impl=optimizer_join_reordering_pandas_impl,
    ),
    DataFrameQuery(
        query_id="optimizer_limit_pushdown",
        query_name="Optimizer: Limit Pushdown",
        description="Test limit pushdown through operations",
        categories=[QueryCategory.JOIN, QueryCategory.SORT],
        expression_impl=optimizer_limit_pushdown_expression_impl,
        pandas_impl=optimizer_limit_pushdown_pandas_impl,
    ),
    DataFrameQuery(
        query_id="optimizer_aggregate_pushdown",
        query_name="Optimizer: Aggregate Pushdown",
        description="Test aggregate pushdown before join",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=optimizer_aggregate_pushdown_expression_impl,
        pandas_impl=optimizer_aggregate_pushdown_pandas_impl,
    ),
    DataFrameQuery(
        query_id="optimizer_constant_folding",
        query_name="Optimizer: Constant Folding",
        description="Test constant folding at compile time",
        categories=[QueryCategory.PROJECTION],
        expression_impl=optimizer_constant_folding_expression_impl,
        pandas_impl=optimizer_constant_folding_pandas_impl,
    ),
    DataFrameQuery(
        query_id="optimizer_column_pruning",
        query_name="Optimizer: Column Pruning",
        description="Test column pruning at scan",
        categories=[QueryCategory.JOIN, QueryCategory.FILTER, QueryCategory.PROJECTION],
        expression_impl=optimizer_column_pruning_expression_impl,
        pandas_impl=optimizer_column_pruning_pandas_impl,
    ),
    DataFrameQuery(
        query_id="optimizer_union_optimization",
        query_name="Optimizer: Union Optimization",
        description="Test union optimization with multiple scans",
        categories=[QueryCategory.SORT],
        expression_impl=optimizer_union_optimization_expression_impl,
        pandas_impl=optimizer_union_optimization_pandas_impl,
    ),
    DataFrameQuery(
        query_id="optimizer_runtime_filter",
        query_name="Optimizer: Runtime Filter",
        description="Test runtime filter / dynamic partition pruning",
        categories=[QueryCategory.JOIN, QueryCategory.FILTER],
        expression_impl=optimizer_runtime_filter_expression_impl,
        pandas_impl=optimizer_runtime_filter_pandas_impl,
    ),
    # QUALIFY queries - window function filtering
    DataFrameQuery(
        query_id="qualify_row_number",
        query_name="QUALIFY ROW_NUMBER",
        description="Find top N orders per customer using ROW_NUMBER",
        categories=[QueryCategory.JOIN, QueryCategory.WINDOW, QueryCategory.FILTER],
        expression_impl=qualify_row_number_expression_impl,
        pandas_impl=qualify_row_number_pandas_impl,
    ),
    DataFrameQuery(
        query_id="qualify_dense_rank",
        query_name="QUALIFY DENSE_RANK",
        description="Find top N parts by price per category using DENSE_RANK",
        categories=[QueryCategory.WINDOW, QueryCategory.FILTER],
        expression_impl=qualify_dense_rank_expression_impl,
        pandas_impl=qualify_dense_rank_pandas_impl,
    ),
    DataFrameQuery(
        query_id="qualify_ntile",
        query_name="QUALIFY NTILE",
        description="Find orders in top quartile per segment using NTILE",
        categories=[QueryCategory.JOIN, QueryCategory.WINDOW, QueryCategory.FILTER],
        expression_impl=qualify_ntile_expression_impl,
        pandas_impl=qualify_ntile_pandas_impl,
    ),
    DataFrameQuery(
        query_id="qualify_percentile",
        query_name="QUALIFY PERCENT_RANK",
        description="Find orders in top 10% per priority using PERCENT_RANK",
        categories=[QueryCategory.WINDOW, QueryCategory.FILTER],
        expression_impl=qualify_percentile_expression_impl,
        pandas_impl=qualify_percentile_pandas_impl,
    ),
    DataFrameQuery(
        query_id="qualify_cume_dist",
        query_name="QUALIFY CUME_DIST",
        description="Find lineitems in top 5% quantity per shipdate using CUME_DIST",
        categories=[QueryCategory.WINDOW, QueryCategory.FILTER],
        expression_impl=qualify_cume_dist_expression_impl,
        pandas_impl=qualify_cume_dist_pandas_impl,
    ),
    DataFrameQuery(
        query_id="qualify_lag_lead",
        query_name="QUALIFY LAG/LEAD",
        description="Find orders with increasing price using LAG",
        categories=[QueryCategory.JOIN, QueryCategory.WINDOW, QueryCategory.FILTER],
        expression_impl=qualify_lag_lead_expression_impl,
        pandas_impl=qualify_lag_lead_pandas_impl,
    ),
    # Struct queries
    DataFrameQuery(
        query_id="struct_construction",
        query_name="Struct Construction",
        description="Construct struct from columns",
        categories=[QueryCategory.PROJECTION],
        expression_impl=struct_construction_expression_impl,
        pandas_impl=struct_construction_pandas_impl,
    ),
    DataFrameQuery(
        query_id="struct_access",
        query_name="Struct Field Access",
        description="Access struct fields by name",
        categories=[QueryCategory.PROJECTION, QueryCategory.FILTER],
        expression_impl=struct_access_expression_impl,
        pandas_impl=struct_access_pandas_impl,
    ),
    # Array queries
    DataFrameQuery(
        query_id="array_contains",
        query_name="Array Contains",
        description="Check if array contains a specific value",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=array_contains_expression_impl,
        pandas_impl=array_contains_pandas_impl,
    ),
    DataFrameQuery(
        query_id="array_distinct",
        query_name="Array Distinct",
        description="Get distinct elements from array",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=array_distinct_expression_impl,
        pandas_impl=array_distinct_pandas_impl,
    ),
    DataFrameQuery(
        query_id="array_length",
        query_name="Array Length",
        description="Get array length/cardinality",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY, QueryCategory.SORT],
        expression_impl=array_length_expression_impl,
        pandas_impl=array_length_pandas_impl,
    ),
    DataFrameQuery(
        query_id="array_min_max",
        query_name="Array Min/Max",
        description="Get min and max from array",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=array_min_max_expression_impl,
        pandas_impl=array_min_max_pandas_impl,
    ),
    DataFrameQuery(
        query_id="array_of_struct",
        query_name="Array of Struct",
        description="Create array of structs from grouped data",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY, QueryCategory.JOIN],
        expression_impl=array_of_struct_expression_impl,
        pandas_impl=array_of_struct_pandas_impl,
    ),
    DataFrameQuery(
        query_id="array_slice",
        query_name="Array Slice",
        description="Get slice/subset of array",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY, QueryCategory.FILTER],
        expression_impl=array_slice_expression_impl,
        pandas_impl=array_slice_pandas_impl,
    ),
    DataFrameQuery(
        query_id="array_sort",
        query_name="Array Sort",
        description="Sort array elements",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=array_sort_expression_impl,
        pandas_impl=array_sort_pandas_impl,
    ),
    DataFrameQuery(
        query_id="array_unnest",
        query_name="Array Unnest",
        description="Unnest/explode array back to rows",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=array_unnest_expression_impl,
        pandas_impl=array_unnest_pandas_impl,
    ),
    # Map queries
    DataFrameQuery(
        query_id="map_construction",
        query_name="Map Construction",
        description="Construct map from key-value pairs",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=map_construction_expression_impl,
        pandas_impl=map_construction_pandas_impl,
    ),
    DataFrameQuery(
        query_id="map_access",
        query_name="Map Access",
        description="Access map values by key",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY, QueryCategory.PROJECTION],
        expression_impl=map_access_expression_impl,
        pandas_impl=map_access_pandas_impl,
    ),
    DataFrameQuery(
        query_id="map_keys_values",
        query_name="Map Keys/Values",
        description="Extract keys and values from map",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=map_keys_values_expression_impl,
        pandas_impl=map_keys_values_pandas_impl,
    ),
    # Higher-order function queries
    DataFrameQuery(
        query_id="list_filter",
        query_name="List Filter",
        description="Filter array elements by condition",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=list_filter_expression_impl,
        pandas_impl=list_filter_pandas_impl,
    ),
    DataFrameQuery(
        query_id="list_transform",
        query_name="List Transform",
        description="Transform each array element",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=list_transform_expression_impl,
        pandas_impl=list_transform_pandas_impl,
    ),
    DataFrameQuery(
        query_id="list_reduce",
        query_name="List Reduce",
        description="Reduce array to single value",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=list_reduce_expression_impl,
        pandas_impl=list_reduce_pandas_impl,
    ),
    # JSON queries
    DataFrameQuery(
        query_id="json_extract_simple",
        query_name="JSON Extract Simple",
        description="Extract from JSON with simple path expressions",
        categories=[QueryCategory.PROJECTION, QueryCategory.FILTER],
        expression_impl=json_extract_simple_expression_impl,
        pandas_impl=json_extract_simple_pandas_impl,
    ),
    DataFrameQuery(
        query_id="json_extract_nested",
        query_name="JSON Extract Nested",
        description="Extract from JSON with complex path expressions",
        categories=[QueryCategory.PROJECTION, QueryCategory.FILTER],
        expression_impl=json_extract_nested_expression_impl,
        pandas_impl=json_extract_nested_pandas_impl,
    ),
    DataFrameQuery(
        query_id="json_aggregates",
        query_name="JSON Aggregates",
        description="Create JSON arrays and objects from aggregations",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY, QueryCategory.FILTER],
        expression_impl=json_aggregates_expression_impl,
        pandas_impl=json_aggregates_pandas_impl,
    ),
    # Timeseries query
    DataFrameQuery(
        query_id="timeseries_trend_analysis",
        query_name="Timeseries Trend Analysis",
        description="Time series aggregation with month-over-month analysis",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY, QueryCategory.WINDOW, QueryCategory.SORT],
        expression_impl=timeseries_trend_analysis_expression_impl,
        pandas_impl=timeseries_trend_analysis_pandas_impl,
    ),
    # ASOF join query
    DataFrameQuery(
        query_id="asof_join_basic",
        query_name="ASOF Join Basic",
        description="ASOF join to find closest prior order for shipments",
        categories=[QueryCategory.JOIN, QueryCategory.FILTER],
        expression_impl=asof_join_basic_expression_impl,
        pandas_impl=asof_join_basic_pandas_impl,
    ),
]

# Register all queries
for query in _QUERIES:
    REGISTRY.register(query)


def get_dataframe_queries() -> QueryRegistry:
    """Get the Read Primitives DataFrame query registry.

    Returns:
        QueryRegistry containing all Read Primitives DataFrame queries
    """
    return REGISTRY


def get_skip_for_dataframe() -> list[str]:
    """Get query IDs that should be skipped for DataFrame execution.

    These are SQL-only queries (optimizer tests) that test SQL query
    planning behavior and are not applicable to DataFrame execution.

    Returns:
        List of query IDs to skip
    """
    return SKIP_FOR_DATAFRAME.copy()


def get_skip_for_expression_family() -> list[str]:
    """Get query IDs that should be skipped for expression-family platforms.

    Currently only map queries are skipped because Polars has no native Map
    dtype. All list/array, struct, and string-split queries are now supported
    through the unified expression API.

    Returns:
        List of query IDs to skip for expression-family platforms (map queries only)
    """
    return SKIP_FOR_EXPRESSION_FAMILY.copy()


def get_skip_for_datafusion() -> list[str]:
    """Get query IDs that should be skipped for DataFusion DataFrame mode.

    These use Polars-only features (.list.eval()) or DataFusion v50 functions
    that are missing from Python bindings (array_sum, array_distinct type bug).

    Returns:
        List of query IDs to skip for DataFusion
    """
    return SKIP_FOR_DATAFUSION.copy()
