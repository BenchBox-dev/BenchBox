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

from csv import reader
from datetime import date
from typing import TYPE_CHECKING, Any

from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory, QueryRegistry

if TYPE_CHECKING:
    from benchbox.core.dataframe.context import DataFrameContext


def _is_dask_context(ctx: DataFrameContext) -> bool:
    """Return whether a pandas-family context is backed by Dask."""
    platform = ctx.platform.lower().replace("_", "-")
    return platform in {"dask", "dask-df"}


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
    # PySpark is the only DataFrame engine with a native array-returning
    # approximate-quantile aggregate (`percentile_approx(col, array(...))`);
    # emulating via a per-quantile loop on Polars/DataFusion/pandas defeats
    # the latency measurement that the benchmark is supposed to report.
    "approx_quantiles_array",
    # PySpark 4.1+ is the only DataFrame engine with a native
    # `approx_top_k` accumulator. Polars' `top_k` returns largest-by-sort-key
    # (different semantics — not frequency-based). A real top-K port for
    # Polars/DataFusion/pandas is a deferred follow-up; see TODO
    # `write-primitives-sketch-pyspark-dataframe-surface` for the
    # PySpark-only DataFrame story this would slot into.
    "approx_top_k_lineitem",
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
SKIP_FOR_EXPRESSION_FAMILY: list[str] = [
    # Currently empty as most expression-family gaps are platform-specific
]

# Queries skipped specifically for Polars DataFrame mode.
SKIP_FOR_POLARS = [
    # --- Map operations: Polars has no native Map dtype ---
    "map_construction",  # ctx.struct() + ctx.map_from_entries()
    "map_access",  # ctx.struct() + ctx.map_from_entries() + .map.get()
    "map_keys_values",  # ctx.struct() + ctx.map_from_entries() + .map.keys/values()
]

# Queries skipped specifically for PySpark DataFrame mode.
SKIP_FOR_PYSPARK = [
    # list_filter and list_transform call ctx.element() in expression_impl.
    # PySpark does not override element() so it raises NotImplementedError.
    "list_filter",
    "list_transform",
]

# Queries skipped specifically for DataFusion DataFrame mode.
# These use Polars-only features or DataFusion v50 missing functions.
SKIP_FOR_DATAFUSION = [
    "list_filter",  # .list.eval() is Polars-only - no DataFusion equivalent
    "list_transform",  # .list.eval() is Polars-only - no DataFusion equivalent
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

    return orders.filter(col("o_orderdate") >= lit(date(1995, 1, 1))).select(
        col("o_custkey").n_unique().alias("unique_customers")
    )


def approx_count_distinct_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Approximate distinct count (HLL) on a large table.

    Sketch-backed on Polars (`approx_n_unique`), PySpark
    (`approx_count_distinct`), and DataFusion (`approx_distinct`); see
    `docs/benchmarks/read-primitives-approximate-functions.md` for the
    cross-platform DataFrame coverage matrix.
    """
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    return orders.filter(col("o_orderdate") >= lit(date(1995, 1, 1))).select(
        col("o_custkey").approx_n_unique().alias("unique_customers")
    )


def approx_count_distinct_groupby_expression_impl(ctx: DataFrameContext) -> Any:
    """Approximate distinct count (HLL) per low-cardinality group.

    Sketch-backed on Polars (`approx_n_unique`), PySpark
    (`approx_count_distinct`), and DataFusion (`approx_distinct`); see
    `docs/benchmarks/read-primitives-approximate-functions.md` for the
    cross-platform DataFrame coverage matrix.
    """
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    return lineitem.group_by("l_returnflag", "l_linestatus").agg(
        col("l_orderkey").approx_n_unique().alias("unique_orders"),
        col("l_partkey").approx_n_unique().alias("unique_parts"),
    )


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
    return order_totals.select(col("customer_total").mean().alias("avg_customer_spending"))


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
    return order_totals.group_by("c_mktsegment").agg(col("order_total").mean().alias("avg_segment_order"))


def aggregation_partition_expression_impl(ctx: DataFrameContext) -> Any:
    """Aggregates over the partition key."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    return (
        lineitem.filter((col("l_shipdate") >= lit(date(1995, 1, 1))) & (col("l_shipdate") < lit(date(1996, 1, 1))))
        .group_by("l_shipdate", "l_shipmode")
        .agg(
            col("l_quantity").sum().alias("daily_quantity"),
            col("l_orderkey").count().alias("shipment_count"),
        )
    )


def aggregation_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """Aggregate on a small subset of rows."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    return lineitem.filter((col("l_discount") > lit(0.05)) & (col("l_quantity") < lit(24))).select(
        (col("l_extendedprice") * col("l_discount")).sum().alias("total_discount_amount")
    )


def aggregation_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Aggregate over all rows in table."""
    orders = ctx.get_table("orders")
    col = ctx.col

    return orders.select(
        col("o_orderkey").count().alias("total_orders"),
        col("o_totalprice").sum().alias("total_revenue"),
    )


def filter_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """High selectivity filter - few rows match."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    return lineitem.filter(
        (col("l_quantity") > lit(45)) & (col("l_extendedprice") > lit(50000)) & (col("l_discount") < lit(0.05))
    ).select("l_orderkey", "l_partkey", "l_quantity", "l_extendedprice")


def filter_non_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """Low selectivity filter - many rows match."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    return lineitem.filter(col("l_quantity") > lit(1)).select(
        "l_orderkey", "l_partkey", "l_quantity", "l_extendedprice"
    )


def count_star_expression_impl(ctx: DataFrameContext) -> Any:
    """Metadata-based count optimization vs full table scan performance."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    return lineitem.select(col("l_orderkey").count().alias("total_lineitems"))


def decimal_arithmetic_expression_impl(ctx: DataFrameContext) -> Any:
    """Decimal precision arithmetic with complex expressions."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    return (
        lineitem.filter(col("l_quantity") > lit(0))
        .select(
            col("l_orderkey"),
            (col("l_extendedprice") * (lit(1) - col("l_discount")) * (lit(1) + col("l_tax"))).alias("final_price"),
            (col("l_extendedprice") / col("l_quantity")).alias("unit_price"),
        )
        .limit(1000)
    )


def orderby_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Simple ORDER BY single column."""
    orders = ctx.get_table("orders")

    return orders.select("o_orderkey", "o_orderdate", "o_totalprice").sort("o_orderdate").limit(100)


def orderby_multi_expression_impl(ctx: DataFrameContext) -> Any:
    """ORDER BY multiple columns."""
    lineitem = ctx.get_table("lineitem")

    return (
        lineitem.select("l_orderkey", "l_linenumber", "l_shipdate", "l_quantity")
        .sort(["l_shipdate", "l_orderkey", "l_linenumber"])
        .limit(100)
    )


def orderby_desc_expression_impl(ctx: DataFrameContext) -> Any:
    """ORDER BY with descending sort."""
    orders = ctx.get_table("orders")

    return orders.select("o_orderkey", "o_totalprice", "o_orderdate").sort("o_totalprice", descending=True).limit(100)


def topn_expression_impl(ctx: DataFrameContext) -> Any:
    """Top-N query with ORDER BY and LIMIT."""
    lineitem = ctx.get_table("lineitem")

    return (
        lineitem.select("l_orderkey", "l_partkey", "l_extendedprice").sort("l_extendedprice", descending=True).limit(10)
    )


def limit_expression_impl(ctx: DataFrameContext) -> Any:
    """Simple LIMIT without ORDER BY."""
    lineitem = ctx.get_table("lineitem")

    return lineitem.select("l_orderkey", "l_partkey", "l_suppkey", "l_quantity").limit(1000)


def string_like_expression_impl(ctx: DataFrameContext) -> Any:
    """String LIKE pattern matching."""
    part = ctx.get_table("part")
    col = ctx.col

    return part.filter(col("p_name").str.contains("blue")).select("p_partkey", "p_name", "p_type")


def string_starts_with_expression_impl(ctx: DataFrameContext) -> Any:
    """String starts_with pattern matching."""
    part = ctx.get_table("part")
    col = ctx.col

    return part.filter(col("p_type").str.starts_with("STANDARD")).select("p_partkey", "p_name", "p_type")


def string_ends_with_expression_impl(ctx: DataFrameContext) -> Any:
    """String ends_with pattern matching."""
    part = ctx.get_table("part")
    col = ctx.col

    return part.filter(col("p_type").str.ends_with("BRASS")).select("p_partkey", "p_name", "p_type")


def string_concat_expression_impl(ctx: DataFrameContext) -> Any:
    """String concatenation."""
    customer = ctx.get_table("customer")
    col = ctx.col
    lit = ctx.lit

    return customer.select(
        col("c_custkey"),
        (col("c_name") + lit(" - ") + col("c_mktsegment")).alias("customer_info"),
    ).limit(100)


def string_substring_expression_impl(ctx: DataFrameContext) -> Any:
    """String substring extraction."""
    customer = ctx.get_table("customer")
    col = ctx.col

    return customer.select(
        col("c_custkey"),
        col("c_phone").str.slice(0, 3).alias("country_code"),
    ).limit(100)


def window_row_number_expression_impl(ctx: DataFrameContext) -> Any:
    """Window function ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    return (
        lineitem.with_columns(
            ctx.window_row_number(
                order_by=[("l_extendedprice", False)],
                partition_by=["l_orderkey"],
            ).alias("row_num")
        )
        .filter(col("row_num") <= 3)
        .select("l_orderkey", "l_linenumber", "l_extendedprice", "row_num")
    )


def window_rank_expression_impl(ctx: DataFrameContext) -> Any:
    """Window function RANK() OVER (PARTITION BY ... ORDER BY ...)."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    return (
        lineitem.with_columns(
            ctx.window_rank(
                order_by=[("l_quantity", False)],
                partition_by=["l_returnflag"],
            ).alias("qty_rank")
        )
        .filter(col("qty_rank") <= 5)
        .select("l_orderkey", "l_returnflag", "l_quantity", "qty_rank")
    )


def window_sum_expression_impl(ctx: DataFrameContext) -> Any:
    """Window function SUM() OVER (PARTITION BY ...)."""
    lineitem = ctx.get_table("lineitem")

    return lineitem.with_columns(
        ctx.window_sum("l_extendedprice", partition_by=["l_orderkey"]).alias("order_total")
    ).select("l_orderkey", "l_linenumber", "l_extendedprice", "order_total")


def window_running_sum_expression_impl(ctx: DataFrameContext) -> Any:
    """Window function SUM() OVER (ORDER BY ...) - cumulative sum."""
    orders = ctx.get_table("orders")

    return (
        orders.sort("o_orderdate")
        .with_columns(ctx.window_sum("o_totalprice", order_by=[("o_orderdate", True)]).alias("cumulative_revenue"))
        .select("o_orderkey", "o_orderdate", "o_totalprice", "cumulative_revenue")
        .limit(100)
    )


def broadcast_join_two_tables_expression_impl(ctx: DataFrameContext) -> Any:
    """One small table broadcast to join with one large table."""
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    col = ctx.col

    return supplier.join(nation, left_on="s_nationkey", right_on="n_nationkey").select(
        col("s_suppkey").count().alias("supplier_count")
    )


def broadcast_join_three_tables_expression_impl(ctx: DataFrameContext) -> Any:
    """Two small tables broadcast to join with one large table."""
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col

    return (
        supplier.join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .group_by("r_name", "n_name")
        .agg(col("s_suppkey").count().alias("supplier_count"))
    )


def predicate_ordering_aggregation_expression_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity for aggregation."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    return lineitem.filter(
        (col("l_shipdate") >= lit(date(1994, 1, 1)))
        & (col("l_shipdate") < lit(date(1995, 1, 1)))
        & (col("l_discount") >= lit(0.05))
        & (col("l_discount") <= lit(0.07))
        & (col("l_quantity") < lit(24))
    ).select(col("l_extendedprice").sum().alias("total_price"))


def shuffle_join_expression_impl(ctx: DataFrameContext) -> Any:
    """Data is redistributed based on the join keys."""
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    return (
        orders.join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .group_by("o_orderkey")
        .agg(col("l_quantity").sum().alias("total_qty"))
    )


def empty_build_join_expression_impl(ctx: DataFrameContext) -> Any:
    """Join when build side produces no rows (edge case handling)."""
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Create empty orders set (no orders with negative price)
    empty_orders = orders.filter(col("o_totalprice") < lit(0)).select("o_orderkey")

    return lineitem.join(empty_orders, left_on="l_orderkey", right_on="o_orderkey", how="left").select(
        "l_orderkey", "l_partkey", "l_quantity"
    )


# -----------------------------------------------------------------------------
# Additional Filter queries
# -----------------------------------------------------------------------------


def filter_bigint_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """Equality predicate with high selectivity on integer column."""
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    return orders.filter(col("o_orderkey") == lit(1234567)).select(
        "o_orderkey", "o_custkey", "o_orderdate", "o_totalprice"
    )


def filter_bigint_non_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """Range predicate with low selectivity on large table."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    return lineitem.filter(col("l_orderkey") > lit(1000)).select(col("l_orderkey").count().alias("count"))


def filter_bigint_in_list_expression_impl(ctx: DataFrameContext) -> Any:
    """IN-list predicate with highly selective integer values."""
    orders = ctx.get_table("orders")
    col = ctx.col

    return orders.filter(col("o_orderkey").is_in([1, 100, 1000, 10000, 100000])).select(
        "o_orderkey", "o_custkey", "o_orderdate", "o_totalprice"
    )


def filter_decimal_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """Compound equality predicate with multiple decimal columns."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    return lineitem.filter((col("l_extendedprice") == lit(12345.67)) & (col("l_discount") == lit(0.05))).select(
        "l_orderkey", "l_partkey", "l_extendedprice", "l_discount"
    )


def filter_decimal_non_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """Range predicate on decimal column with low selectivity."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    return lineitem.filter(col("l_extendedprice") > lit(1000.00)).select(col("l_orderkey").count().alias("count"))


def filter_string_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """Exact string equality with high selectivity on varchar column."""
    customer = ctx.get_table("customer")
    col = ctx.col
    lit = ctx.lit

    return customer.filter(col("c_name") == lit("Customer#000001234")).select(
        "c_custkey", "c_name", "c_address", "c_phone"
    )


def filter_string_non_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """String comparison with low selectivity (most rows match)."""
    customer = ctx.get_table("customer")
    col = ctx.col
    lit = ctx.lit

    return customer.filter(col("c_mktsegment") >= lit("A")).select(col("c_custkey").count().alias("count"))


def filter_in_predicate_subquery_expression_impl(ctx: DataFrameContext) -> Any:
    """IN predicate with subquery and selective filtering."""
    part = ctx.get_table("part")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    # Get partkeys with high quantity
    high_qty_parts = lineitem.filter(col("l_quantity") > lit(45)).select("l_partkey").unique()

    return part.join(high_qty_parts, left_on="p_partkey", right_on="l_partkey", how="semi").select(
        "p_partkey", "p_name", "p_type", "p_size"
    )


# -----------------------------------------------------------------------------
# Additional GroupBy queries
# -----------------------------------------------------------------------------


def groupby_highndv_expression_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY with high distinct value count (many groups)."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    return lineitem.group_by("l_orderkey").agg(col("l_linenumber").count().alias("line_count"))


def groupby_lowndv_expression_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY with low distinct value count (few groups)."""
    orders = ctx.get_table("orders")
    col = ctx.col

    return orders.group_by("o_orderpriority").agg(col("o_orderkey").count().alias("order_count"))


def groupby_pk_expression_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY on primary key (one row per group)."""
    customer = ctx.get_table("customer")
    col = ctx.col

    return customer.group_by("c_custkey").agg(col("c_name").max().alias("customer_name"))


def groupby_decimal_highndv_expression_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY with high cardinality decimal column."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    return lineitem.group_by("l_extendedprice").agg(col("l_orderkey").count().alias("price_frequency"))


def groupby_decimal_lowndv_expression_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY with low cardinality decimal column."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    return lineitem.group_by("l_discount").agg(
        col("l_orderkey").count().alias("discount_frequency"),
        col("l_quantity").mean().alias("avg_qty"),
    )


# -----------------------------------------------------------------------------
# Additional OrderBy queries
# -----------------------------------------------------------------------------


def orderby_all_expression_impl(ctx: DataFrameContext) -> Any:
    """Sort on full table with simple integer ordering."""
    customer = ctx.get_table("customer")

    return customer.sort("c_custkey").select(
        "c_custkey", "c_name", "c_address", "c_nationkey", "c_phone", "c_acctbal", "c_mktsegment"
    )


def orderby_bigint_expression_impl(ctx: DataFrameContext) -> Any:
    """Sort with aggregation results on integer column."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    return lineitem.group_by("l_orderkey").agg(col("l_quantity").sum().alias("total_qty")).sort("l_orderkey")


def orderby_expression_expression_impl(ctx: DataFrameContext) -> Any:
    """Sort on computed expressions with DESC ordering."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    return (
        lineitem.with_columns((col("l_quantity") * col("l_extendedprice")).alias("total_value"))
        .sort("total_value", descending=True)
        .select("l_orderkey", "l_partkey", "total_value")
        .limit(100)
    )


def orderby_multicol_expression_impl(ctx: DataFrameContext) -> Any:
    """Complex multi-column sort with string, date, and decimal columns."""
    orders = ctx.get_table("orders")

    return (
        orders.sort(
            ["o_orderpriority", "o_orderdate", "o_totalprice"],
            descending=[False, True, True],
        )
        .select("o_orderkey", "o_custkey", "o_orderpriority", "o_orderdate", "o_totalprice")
        .limit(100)
    )


def orderby_shortstrings_expression_impl(ctx: DataFrameContext) -> Any:
    """Sort on short string columns with DISTINCT operation."""
    lineitem = ctx.get_table("lineitem")

    return lineitem.select("l_returnflag", "l_linestatus").unique().sort(["l_returnflag", "l_linestatus"])


# -----------------------------------------------------------------------------
# Additional Shuffle/Join queries
# -----------------------------------------------------------------------------


def shuffle_inner_join_groupby_expression_impl(ctx: DataFrameContext) -> Any:
    """Standard inner join with one-to-many relationship."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col

    return (
        customer.join(orders, left_on="c_custkey", right_on="o_custkey")
        .group_by("c_mktsegment")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("o_totalprice").sum().alias("total_revenue"),
        )
    )


def shuffle_left_join_groupby_expression_impl(ctx: DataFrameContext) -> Any:
    """LEFT JOIN with preservation of all left-side rows."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col

    return (
        customer.join(orders, left_on="c_custkey", right_on="o_custkey", how="left")
        .group_by("c_mktsegment")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("c_custkey").count().alias("total_rows"),
        )
    )


def shuffle_full_join_groupby_expression_impl(ctx: DataFrameContext) -> Any:
    """FULL OUTER JOIN with string grouping and aggregation."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col

    return (
        customer.join(orders, left_on="c_custkey", right_on="o_custkey", how="outer")
        .group_by("c_mktsegment")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("c_custkey").count().alias("customer_count"),
        )
    )


def shuffle_self_join_expression_impl(ctx: DataFrameContext) -> Any:
    """Self-join with hash collision handling on large table."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    # Self-join on partkey and shipdate
    return (
        lineitem.join(
            lineitem.select("l_orderkey", "l_partkey", "l_shipdate").rename({"l_orderkey": "l_orderkey_2"}),
            on=["l_partkey", "l_shipdate"],
        )
        .filter(col("l_orderkey") != col("l_orderkey_2"))
        .group_by("l_orderkey")
        .agg(col("l_orderkey_2").count().alias("match_count"))
        .limit(10000)
    )


# -----------------------------------------------------------------------------
# Additional String queries
# -----------------------------------------------------------------------------


def string_equal_expression_impl(ctx: DataFrameContext) -> Any:
    """Exact string equality with selective matching."""
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    return part.filter(col("p_brand") == lit("Brand#23")).select(col("p_partkey").count().alias("count"))


def string_equal_lower_expression_impl(ctx: DataFrameContext) -> Any:
    """Equality predicate after applying case conversion."""
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    return part.filter(col("p_brand").str.to_lowercase() == lit("brand#23")).select(
        col("p_partkey").count().alias("count")
    )


def string_in_predicate_expression_impl(ctx: DataFrameContext) -> Any:
    """IN predicate with string values."""
    orders = ctx.get_table("orders")
    col = ctx.col

    return orders.filter(col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"])).select(
        col("o_orderkey").count().alias("count")
    )


def string_like_center_expression_impl(ctx: DataFrameContext) -> Any:
    """Case sensitive matching pattern in any location."""
    part = ctx.get_table("part")
    col = ctx.col

    return part.filter(col("p_name").str.contains("STEEL")).select(col("p_partkey").count().alias("count"))


def string_like_suffix_expression_impl(ctx: DataFrameContext) -> Any:
    """Case sensitive matching suffix pattern."""
    part = ctx.get_table("part")
    col = ctx.col

    return part.filter(col("p_name").str.ends_with("COPPER")).select(col("p_partkey").count().alias("count"))


def string_like_prefix_expression_impl(ctx: DataFrameContext) -> Any:
    """Case sensitive matching prefix pattern."""
    part = ctx.get_table("part")
    col = ctx.col

    return part.filter(col("p_name").str.starts_with("STANDARD")).select(col("p_partkey").count().alias("count"))


# -----------------------------------------------------------------------------
# Additional Window queries
# -----------------------------------------------------------------------------


def window_growing_frame_expression_impl(ctx: DataFrameContext) -> Any:
    """Running sum window aggregation with growing frame size."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    return (
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


def window_lead_lag_expression_impl(ctx: DataFrameContext) -> Any:
    """Offset window functions over the same frame."""
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    return (
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


def window_dense_rank_expression_impl(ctx: DataFrameContext) -> Any:
    """Window function DENSE_RANK() OVER (PARTITION BY ... ORDER BY ...)."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    return (
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


# -----------------------------------------------------------------------------
# Additional Predicate queries
# -----------------------------------------------------------------------------


def predicate_ordering_groupby_expression_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity for aggregation within a low cardinality grouping."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    return (
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


def predicate_ordering_costs_expression_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity with result projection only."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    return (
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

    return (
        partsupp.join(supplier, left_on="ps_suppkey", right_on="s_suppkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .join(part, left_on="ps_partkey", right_on="p_partkey")
        .filter(col("p_size") == lit(15))
        .group_by("r_name", "p_type")
        .agg((col("ps_supplycost") * col("ps_availqty")).sum().alias("total_value"))
    )


def exchange_broadcast_expression_impl(ctx: DataFrameContext) -> Any:
    """One small table is copied to all nodes that have the large table."""
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    # Small parts filtered from part table
    small_parts = part.filter(col("p_size") == lit(1)).select("p_partkey")

    return (
        lineitem.join(small_parts, left_on="l_partkey", right_on="p_partkey")
        .group_by("l_orderkey")
        .agg(col("l_quantity").sum().alias("total_qty"))
    )


def exchange_merge_expression_impl(ctx: DataFrameContext) -> Any:
    """Sorted data from multiple nodes is combined while keeping the sort order."""
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    return (
        orders.join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .select("o_orderkey", "l_linenumber", "l_quantity")
        .sort(["o_orderkey", "l_linenumber"])
    )


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

    return (
        ps1.join(ps2, left_on="ps_partkey", right_on="ps_partkey_2")
        .filter((col("supp1") < col("supp2")) & (col("cost1") > lit(100)))
        .select("ps_partkey", "supp1", "supp2")
    )


# -----------------------------------------------------------------------------
# TopN queries
# -----------------------------------------------------------------------------


def topn_aggregate_expression_impl(ctx: DataFrameContext) -> Any:
    """Top 10 limit returning 2 columns after aggregation and computed ordering."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    return (
        lineitem.group_by("l_orderkey")
        .agg(col("l_quantity").sum().alias("total_quantity"))
        .sort("total_quantity", descending=True)
        .limit(10)
    )


def topn_allcols_expression_impl(ctx: DataFrameContext) -> Any:
    """Top-10 limit returning all columns after ordering over all table rows."""
    lineitem = ctx.get_table("lineitem")

    return lineitem.sort("l_extendedprice", descending=True).limit(10)


# -----------------------------------------------------------------------------
# Statistical queries
# -----------------------------------------------------------------------------


def statistical_variance_expression_impl(ctx: DataFrameContext) -> Any:
    """Variance and standard deviation calculations."""
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    return (
        orders.filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .group_by("o_orderpriority")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("o_totalprice").mean().alias("avg_price"),
            col("o_totalprice").var().alias("price_variance"),
            col("o_totalprice").std().alias("price_stddev"),
        )
    )


def statistical_correlation_expression_impl(ctx: DataFrameContext) -> Any:
    """Correlation analysis between numeric columns."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    filtered = lineitem.filter(
        (col("l_shipdate") >= lit(date(1995, 1, 1))) & (col("l_shipdate") < lit(date(1996, 1, 1)))
    )

    # Calculate correlation between quantity and price
    return filtered.select(
        col("l_quantity").mean().alias("avg_quantity"),
        col("l_extendedprice").mean().alias("avg_price"),
        # Correlation requires special handling - use pearson_corr where available
        (
            (col("l_quantity") * col("l_extendedprice")).mean()
            - col("l_quantity").mean() * col("l_extendedprice").mean()
        ).alias("covariance_approx"),
    )


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

    return (
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
    return (
        with_nation.join(max_balances, on="n_name")
        .filter(col("c_acctbal") == col("max_balance"))
        .select("n_name", "c_name", "max_balance")
        .unique(subset=["n_name"])
        .sort("max_balance", descending=True)
    )


def min_by_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Find the customer with the lowest account balance in each nation."""
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    col = ctx.col

    with_nation = customer.join(nation, left_on="c_nationkey", right_on="n_nationkey")

    min_balances = with_nation.group_by("n_name").agg(col("c_acctbal").min().alias("min_balance"))

    return (
        with_nation.join(min_balances, on="n_name")
        .filter(col("c_acctbal") == col("min_balance"))
        .select("n_name", "c_name", "min_balance")
        .unique(subset=["n_name"])
        .sort("min_balance")
    )


# -----------------------------------------------------------------------------
# Array operations (semi-structured data)
# -----------------------------------------------------------------------------


def array_agg_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Aggregate part keys into arrays per supplier."""
    partsupp = ctx.get_table("partsupp")
    col = ctx.col

    return (
        partsupp.group_by("ps_suppkey")
        .agg(
            col("ps_partkey").sort_by("ps_partkey").alias("supplied_parts"),
            col("ps_partkey").count().alias("part_count"),
        )
        .filter(col("part_count") <= 10)
        .limit(100)
    )


def array_agg_distinct_expression_impl(ctx: DataFrameContext) -> Any:
    """Distinct array aggregation."""
    customer = ctx.get_table("customer")
    col = ctx.col

    return customer.group_by("c_mktsegment").agg(
        col("c_nationkey").unique().sort().alias("nation_keys"),
    )


# =============================================================================
# Pandas Family Implementations (Pandas, Modin, Dask)
# =============================================================================


def aggregation_distinct_pandas_impl(ctx: DataFrameContext) -> Any:
    """Distinct count of high cardinality key on a large table."""
    orders = ctx.get_table("orders")

    filtered = orders[orders["o_orderdate"] >= date(1995, 1, 1)]
    return filtered[["o_custkey"]].nunique().to_frame(name="unique_customers").reset_index(drop=True)


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


def approx_count_distinct_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Approximate distinct count fallback for the pandas family.

    Dask uses native `nunique_approx()` (HLL) for this single-value
    query. Pandas, Modin, and cuDF expose only exact `.nunique()` at
    the API surface, so the "approximate" label degrades to exact on
    those platforms.
    """
    orders = ctx.get_table("orders")

    filtered = orders[orders["o_orderdate"] >= date(1995, 1, 1)]
    if _is_dask_context(ctx):
        return ctx.scalar_to_df({"unique_customers": filtered["o_custkey"].nunique_approx().compute()})

    return filtered[["o_custkey"]].nunique().to_frame(name="unique_customers").reset_index(drop=True)


def approx_count_distinct_groupby_pandas_impl(ctx: DataFrameContext) -> Any:
    """Approximate distinct count groupby fallback for the pandas family.

    Pandas, Modin, cuDF, and current Dask expose no groupby approximate
    distinct aggregate matching this query shape. Dask has Series-level
    `nunique_approx()`, but no groupby equivalent in the dask-expr API,
    so this query remains an exact fallback for the pandas family.
    """
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
    return ctx.scalar_to_df({"avg_customer_spending": order_totals["customer_total"].mean()})


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
    return order_totals.groupby("c_mktsegment", as_index=False).agg(avg_segment_order=("order_total", "mean"))


def aggregation_partition_pandas_impl(ctx: DataFrameContext) -> Any:
    """Aggregates over the partition key."""
    lineitem = ctx.get_table("lineitem")

    filtered = lineitem[(lineitem["l_shipdate"] >= date(1995, 1, 1)) & (lineitem["l_shipdate"] < date(1996, 1, 1))]

    return filtered.groupby(["l_shipdate", "l_shipmode"], as_index=False).agg(
        daily_quantity=("l_quantity", "sum"),
        shipment_count=("l_orderkey", "count"),
    )


def aggregation_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """Aggregate on a small subset of rows."""
    lineitem = ctx.get_table("lineitem")

    filtered = lineitem[(lineitem["l_discount"] > 0.05) & (lineitem["l_quantity"] < 24)]
    total = (filtered["l_extendedprice"] * filtered["l_discount"]).sum()
    return ctx.scalar_to_df({"total_discount_amount": total})


def aggregation_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Aggregate over all rows in table."""
    orders = ctx.get_table("orders")

    return ctx.scalar_to_df(
        {
            "total_orders": len(orders),
            "total_revenue": orders["o_totalprice"].sum(),
        }
    )


def filter_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """High selectivity filter - few rows match."""
    lineitem = ctx.get_table("lineitem")

    return lineitem[
        (lineitem["l_quantity"] > 45) & (lineitem["l_extendedprice"] > 50000) & (lineitem["l_discount"] < 0.05)
    ][["l_orderkey", "l_partkey", "l_quantity", "l_extendedprice"]]


def filter_non_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """Low selectivity filter - many rows match."""
    lineitem = ctx.get_table("lineitem")

    return lineitem[lineitem["l_quantity"] > 1][["l_orderkey", "l_partkey", "l_quantity", "l_extendedprice"]]


def count_star_pandas_impl(ctx: DataFrameContext) -> Any:
    """Metadata-based count optimization vs full table scan performance."""
    lineitem = ctx.get_table("lineitem")

    return ctx.scalar_to_df({"total_lineitems": len(lineitem)})


def decimal_arithmetic_pandas_impl(ctx: DataFrameContext) -> Any:
    """Decimal precision arithmetic with complex expressions."""
    lineitem = ctx.get_table("lineitem")

    filtered = lineitem[lineitem["l_quantity"] > 0].copy()
    filtered["final_price"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"]) * (1 + filtered["l_tax"])
    filtered["unit_price"] = filtered["l_extendedprice"] / filtered["l_quantity"]

    return filtered[["l_orderkey", "final_price", "unit_price"]].head(1000)


def orderby_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Simple ORDER BY single column."""
    orders = ctx.get_table("orders")

    return orders[["o_orderkey", "o_orderdate", "o_totalprice"]].sort_values("o_orderdate").head(100)


def orderby_multi_pandas_impl(ctx: DataFrameContext) -> Any:
    """ORDER BY multiple columns."""
    lineitem = ctx.get_table("lineitem")

    return (
        lineitem[["l_orderkey", "l_linenumber", "l_shipdate", "l_quantity"]]
        .sort_values(["l_shipdate", "l_orderkey", "l_linenumber"])
        .head(100)
    )


def orderby_desc_pandas_impl(ctx: DataFrameContext) -> Any:
    """ORDER BY with descending sort."""
    orders = ctx.get_table("orders")

    return orders[["o_orderkey", "o_totalprice", "o_orderdate"]].sort_values("o_totalprice", ascending=False).head(100)


def topn_pandas_impl(ctx: DataFrameContext) -> Any:
    """Top-N query with ORDER BY and LIMIT."""
    lineitem = ctx.get_table("lineitem")

    return lineitem.nlargest(10, "l_extendedprice")[["l_orderkey", "l_partkey", "l_extendedprice"]]


def limit_pandas_impl(ctx: DataFrameContext) -> Any:
    """Simple LIMIT without ORDER BY."""
    lineitem = ctx.get_table("lineitem")

    return lineitem[["l_orderkey", "l_partkey", "l_suppkey", "l_quantity"]].head(1000)


def string_like_pandas_impl(ctx: DataFrameContext) -> Any:
    """String LIKE pattern matching."""
    part = ctx.get_table("part")

    return part[part["p_name"].str.contains("blue", na=False)][["p_partkey", "p_name", "p_type"]]


def string_starts_with_pandas_impl(ctx: DataFrameContext) -> Any:
    """String starts_with pattern matching."""
    part = ctx.get_table("part")

    return part[part["p_type"].str.startswith("STANDARD", na=False)][["p_partkey", "p_name", "p_type"]]


def string_ends_with_pandas_impl(ctx: DataFrameContext) -> Any:
    """String ends_with pattern matching."""
    part = ctx.get_table("part")

    return part[part["p_type"].str.endswith("BRASS", na=False)][["p_partkey", "p_name", "p_type"]]


def string_concat_pandas_impl(ctx: DataFrameContext) -> Any:
    """String concatenation."""
    customer = ctx.get_table("customer")

    result = customer.copy()
    result["customer_info"] = result["c_name"] + " - " + result["c_mktsegment"]
    return result[["c_custkey", "customer_info"]].head(100)


def string_substring_pandas_impl(ctx: DataFrameContext) -> Any:
    """String substring extraction."""
    customer = ctx.get_table("customer")

    result = customer.copy()
    result["country_code"] = result["c_phone"].str[:3]
    return result[["c_custkey", "country_code"]].head(100)


def window_row_number_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window function ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)."""
    lineitem = ctx.get_table("lineitem")

    # Sort and rank within groups
    sorted_df = lineitem.sort_values(["l_orderkey", "l_extendedprice"], ascending=[True, False])
    sorted_df["row_num"] = sorted_df.groupby("l_orderkey").cumcount() + 1

    return sorted_df[sorted_df["row_num"] <= 3][["l_orderkey", "l_linenumber", "l_extendedprice", "row_num"]]


def window_rank_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window function RANK() OVER (PARTITION BY ... ORDER BY ...)."""
    lineitem = ctx.get_table("lineitem")

    # Rank within groups
    lineitem = lineitem.copy()
    lineitem["qty_rank"] = lineitem.groupby("l_returnflag")["l_quantity"].rank(method="min", ascending=False)

    return lineitem[lineitem["qty_rank"] <= 5][["l_orderkey", "l_returnflag", "l_quantity", "qty_rank"]]


def window_sum_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window function SUM() OVER (PARTITION BY ...)."""
    lineitem = ctx.get_table("lineitem")

    lineitem = lineitem.copy()
    lineitem["order_total"] = lineitem.groupby("l_orderkey")["l_extendedprice"].transform("sum")

    return lineitem[["l_orderkey", "l_linenumber", "l_extendedprice", "order_total"]]


def window_running_sum_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window function SUM() OVER (ORDER BY ...) - cumulative sum."""
    orders = ctx.get_table("orders")

    sorted_orders = orders.sort_values("o_orderdate").copy()
    sorted_orders["cumulative_revenue"] = sorted_orders["o_totalprice"].cumsum()

    return sorted_orders[["o_orderkey", "o_orderdate", "o_totalprice", "cumulative_revenue"]].head(100)


def broadcast_join_two_tables_pandas_impl(ctx: DataFrameContext) -> Any:
    """One small table broadcast to join with one large table."""
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")

    merged = supplier.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    return ctx.scalar_to_df({"supplier_count": len(merged)})


def broadcast_join_three_tables_pandas_impl(ctx: DataFrameContext) -> Any:
    """Two small tables broadcast to join with one large table."""
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    merged = supplier.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    merged = merged.merge(region, left_on="n_regionkey", right_on="r_regionkey")

    return merged.groupby(["r_name", "n_name"], as_index=False).agg(supplier_count=("s_suppkey", "count"))


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

    return ctx.scalar_to_df({"total_price": filtered["l_extendedprice"].sum()})


def shuffle_join_pandas_impl(ctx: DataFrameContext) -> Any:
    """Data is redistributed based on the join keys."""
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    merged = orders.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    return merged.groupby("o_orderkey", as_index=False).agg(total_qty=("l_quantity", "sum"))


def empty_build_join_pandas_impl(ctx: DataFrameContext) -> Any:
    """Join when build side produces no rows (edge case handling)."""
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")

    empty_orders = orders[orders["o_totalprice"] < 0][["o_orderkey"]]
    return lineitem.merge(empty_orders, left_on="l_orderkey", right_on="o_orderkey", how="left")[
        ["l_orderkey", "l_partkey", "l_quantity"]
    ]


# -----------------------------------------------------------------------------
# Additional Filter queries (Pandas)
# -----------------------------------------------------------------------------


def filter_bigint_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """Equality predicate with high selectivity on integer column."""
    orders = ctx.get_table("orders")

    return orders[orders["o_orderkey"] == 1234567][["o_orderkey", "o_custkey", "o_orderdate", "o_totalprice"]]


def filter_bigint_non_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """Range predicate with low selectivity on large table."""
    lineitem = ctx.get_table("lineitem")

    count = len(lineitem[lineitem["l_orderkey"] > 1000])
    return ctx.scalar_to_df({"count": count})


def filter_bigint_in_list_pandas_impl(ctx: DataFrameContext) -> Any:
    """IN-list predicate with highly selective integer values."""
    orders = ctx.get_table("orders")

    return orders[orders["o_orderkey"].isin([1, 100, 1000, 10000, 100000])][
        ["o_orderkey", "o_custkey", "o_orderdate", "o_totalprice"]
    ]


def filter_decimal_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """Compound equality predicate with multiple decimal columns."""
    lineitem = ctx.get_table("lineitem")

    return lineitem[(lineitem["l_extendedprice"] == 12345.67) & (lineitem["l_discount"] == 0.05)][
        ["l_orderkey", "l_partkey", "l_extendedprice", "l_discount"]
    ]


def filter_decimal_non_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """Range predicate on decimal column with low selectivity."""
    lineitem = ctx.get_table("lineitem")

    count = len(lineitem[lineitem["l_extendedprice"] > 1000.00])
    return ctx.scalar_to_df({"count": count})


def filter_string_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """Exact string equality with high selectivity on varchar column."""
    customer = ctx.get_table("customer")

    return customer[customer["c_name"] == "Customer#000001234"][["c_custkey", "c_name", "c_address", "c_phone"]]


def filter_string_non_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """String comparison with low selectivity (most rows match)."""
    customer = ctx.get_table("customer")

    count = len(customer[customer["c_mktsegment"] >= "A"])
    return ctx.scalar_to_df({"count": count})


def filter_in_predicate_subquery_pandas_impl(ctx: DataFrameContext) -> Any:
    """IN predicate with subquery and selective filtering."""
    part = ctx.get_table("part")
    lineitem = ctx.get_table("lineitem")

    high_qty_parts = lineitem[lineitem["l_quantity"] > 45]["l_partkey"].unique()
    return part[part["p_partkey"].isin(high_qty_parts)][["p_partkey", "p_name", "p_type", "p_size"]]


# -----------------------------------------------------------------------------
# Additional GroupBy queries (Pandas)
# -----------------------------------------------------------------------------


def groupby_highndv_pandas_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY with high distinct value count (many groups)."""
    lineitem = ctx.get_table("lineitem")

    return lineitem.groupby("l_orderkey", as_index=False).agg(line_count=("l_linenumber", "count"))


def groupby_lowndv_pandas_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY with low distinct value count (few groups)."""
    orders = ctx.get_table("orders")

    return orders.groupby("o_orderpriority", as_index=False).agg(order_count=("o_orderkey", "count"))


def groupby_pk_pandas_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY on primary key (one row per group)."""
    customer = ctx.get_table("customer")

    return customer.groupby("c_custkey", as_index=False).agg(customer_name=("c_name", "max"))


def groupby_decimal_highndv_pandas_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY with high cardinality decimal column."""
    lineitem = ctx.get_table("lineitem")

    return lineitem.groupby("l_extendedprice", as_index=False).agg(price_frequency=("l_orderkey", "count"))


def groupby_decimal_lowndv_pandas_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY with low cardinality decimal column."""
    lineitem = ctx.get_table("lineitem")

    return lineitem.groupby("l_discount", as_index=False).agg(
        discount_frequency=("l_orderkey", "count"),
        avg_qty=("l_quantity", "mean"),
    )


# -----------------------------------------------------------------------------
# Additional OrderBy queries (Pandas)
# -----------------------------------------------------------------------------


def orderby_all_pandas_impl(ctx: DataFrameContext) -> Any:
    """Sort on full table with simple integer ordering."""
    customer = ctx.get_table("customer")

    return customer.sort_values("c_custkey")[
        ["c_custkey", "c_name", "c_address", "c_nationkey", "c_phone", "c_acctbal", "c_mktsegment"]
    ]


def orderby_bigint_pandas_impl(ctx: DataFrameContext) -> Any:
    """Sort with aggregation results on integer column."""
    lineitem = ctx.get_table("lineitem")

    return lineitem.groupby("l_orderkey", as_index=False).agg(total_qty=("l_quantity", "sum")).sort_values("l_orderkey")


def orderby_expression_pandas_impl(ctx: DataFrameContext) -> Any:
    """Sort on computed expressions with DESC ordering."""
    lineitem = ctx.get_table("lineitem")

    df = lineitem.copy()
    df["total_value"] = df["l_quantity"] * df["l_extendedprice"]
    return df.sort_values("total_value", ascending=False)[["l_orderkey", "l_partkey", "total_value"]].head(100)


def orderby_multicol_pandas_impl(ctx: DataFrameContext) -> Any:
    """Complex multi-column sort with string, date, and decimal columns."""
    orders = ctx.get_table("orders")

    return orders.sort_values(
        ["o_orderpriority", "o_orderdate", "o_totalprice"],
        ascending=[True, False, False],
    )[["o_orderkey", "o_custkey", "o_orderpriority", "o_orderdate", "o_totalprice"]].head(100)


def orderby_shortstrings_pandas_impl(ctx: DataFrameContext) -> Any:
    """Sort on short string columns with DISTINCT operation."""
    lineitem = ctx.get_table("lineitem")

    return lineitem[["l_returnflag", "l_linestatus"]].drop_duplicates().sort_values(["l_returnflag", "l_linestatus"])


# -----------------------------------------------------------------------------
# Additional Shuffle/Join queries (Pandas)
# -----------------------------------------------------------------------------


def shuffle_inner_join_groupby_pandas_impl(ctx: DataFrameContext) -> Any:
    """Standard inner join with one-to-many relationship."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    return merged.groupby("c_mktsegment", as_index=False).agg(
        order_count=("o_orderkey", "count"),
        total_revenue=("o_totalprice", "sum"),
    )


def shuffle_left_join_groupby_pandas_impl(ctx: DataFrameContext) -> Any:
    """LEFT JOIN with preservation of all left-side rows."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey", how="left")
    return merged.groupby("c_mktsegment", as_index=False).agg(
        order_count=("o_orderkey", "count"),
        total_rows=("c_custkey", "count"),
    )


def shuffle_full_join_groupby_pandas_impl(ctx: DataFrameContext) -> Any:
    """FULL OUTER JOIN with string grouping and aggregation."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey", how="outer")
    return merged.groupby("c_mktsegment", as_index=False).agg(
        order_count=("o_orderkey", "count"),
        customer_count=("c_custkey", "count"),
    )


def shuffle_self_join_pandas_impl(ctx: DataFrameContext) -> Any:
    """Self-join with hash collision handling on large table."""
    lineitem = ctx.get_table("lineitem")

    # Create copies for self-join
    df1 = lineitem[["l_orderkey", "l_partkey", "l_shipdate"]].copy()
    df2 = lineitem[["l_orderkey", "l_partkey", "l_shipdate"]].copy()
    df2 = df2.rename(columns={"l_orderkey": "l_orderkey_2"})

    merged = df1.merge(df2, on=["l_partkey", "l_shipdate"])
    filtered = merged[merged["l_orderkey"] != merged["l_orderkey_2"]]
    return filtered.groupby("l_orderkey", as_index=False).agg(match_count=("l_orderkey_2", "count")).head(10000)


# -----------------------------------------------------------------------------
# Additional String queries (Pandas)
# -----------------------------------------------------------------------------


def string_equal_pandas_impl(ctx: DataFrameContext) -> Any:
    """Exact string equality with selective matching."""
    part = ctx.get_table("part")

    count = len(part[part["p_brand"] == "Brand#23"])
    return ctx.scalar_to_df({"count": count})


def string_equal_lower_pandas_impl(ctx: DataFrameContext) -> Any:
    """Equality predicate after applying case conversion."""
    part = ctx.get_table("part")

    count = len(part[part["p_brand"].str.lower() == "brand#23"])
    return ctx.scalar_to_df({"count": count})


def string_in_predicate_pandas_impl(ctx: DataFrameContext) -> Any:
    """IN predicate with string values."""
    orders = ctx.get_table("orders")

    count = len(orders[orders["o_orderpriority"].isin(["1-URGENT", "2-HIGH"])])
    return ctx.scalar_to_df({"count": count})


def string_like_center_pandas_impl(ctx: DataFrameContext) -> Any:
    """Case sensitive matching pattern in any location."""
    part = ctx.get_table("part")

    count = len(part[part["p_name"].str.contains("STEEL", na=False)])
    return ctx.scalar_to_df({"count": count})


def string_like_suffix_pandas_impl(ctx: DataFrameContext) -> Any:
    """Case sensitive matching suffix pattern."""
    part = ctx.get_table("part")

    count = len(part[part["p_name"].str.endswith("COPPER", na=False)])
    return ctx.scalar_to_df({"count": count})


def string_like_prefix_pandas_impl(ctx: DataFrameContext) -> Any:
    """Case sensitive matching prefix pattern."""
    part = ctx.get_table("part")

    count = len(part[part["p_name"].str.startswith("STANDARD", na=False)])
    return ctx.scalar_to_df({"count": count})


# -----------------------------------------------------------------------------
# Additional Window queries (Pandas)
# -----------------------------------------------------------------------------


def window_growing_frame_pandas_impl(ctx: DataFrameContext) -> Any:
    """Running sum window aggregation with growing frame size."""
    lineitem = ctx.get_table("lineitem")

    df = lineitem[lineitem["l_orderkey"] <= 1000].copy()
    df = df.sort_values(["l_orderkey", "l_linenumber"])
    df["running_quantity"] = df.groupby("l_orderkey")["l_quantity"].cumsum()

    return df[["l_orderkey", "l_linenumber", "l_quantity", "running_quantity"]]


def window_lead_lag_pandas_impl(ctx: DataFrameContext) -> Any:
    """Offset window functions over the same frame."""
    orders = ctx.get_table("orders")

    df = orders[(orders["o_orderdate"] >= date(1995, 1, 1)) & (orders["o_orderdate"] < date(1996, 1, 1))].copy()
    df = df.sort_values(["o_custkey", "o_orderdate"])
    df["prev_order_price"] = df.groupby("o_custkey")["o_totalprice"].shift(1)
    df["next_order_price"] = df.groupby("o_custkey")["o_totalprice"].shift(-1)

    return df[["o_orderkey", "o_orderdate", "o_totalprice", "prev_order_price", "next_order_price"]]


def window_dense_rank_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window function DENSE_RANK() OVER (PARTITION BY ... ORDER BY ...)."""
    lineitem = ctx.get_table("lineitem")

    df = lineitem[lineitem["l_orderkey"] <= 10000].copy()
    df["price_rank"] = df.groupby("l_orderkey")["l_extendedprice"].rank(method="dense", ascending=False)
    df = df.sort_values(["l_orderkey", "price_rank"])

    return df[["l_orderkey", "l_partkey", "l_quantity", "l_extendedprice", "price_rank"]]


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

    return filtered.groupby("l_returnflag", as_index=False).agg(total_qty=("l_quantity", "sum"))


def predicate_ordering_costs_pandas_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity with result projection only."""
    lineitem = ctx.get_table("lineitem")

    return lineitem[
        (lineitem["l_quantity"] > 45)
        & (lineitem["l_extendedprice"] > 50000)
        & (lineitem["l_discount"] < 0.05)
        & (lineitem["l_shipinstruct"] == "DELIVER IN PERSON")
        & (lineitem["l_shipmode"].isin(["AIR", "AIR REG"]))
    ][["l_orderkey", "l_partkey", "l_quantity", "l_extendedprice", "l_discount", "l_shipinstruct", "l_shipmode"]].head(
        100
    )


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
    return filtered.groupby(["r_name", "p_type"], as_index=False).agg(total_value=("total_value", "sum"))


def exchange_broadcast_pandas_impl(ctx: DataFrameContext) -> Any:
    """One small table is copied to all nodes that have the large table."""
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")

    small_parts = part[part["p_size"] == 1][["p_partkey"]]
    merged = lineitem.merge(small_parts, left_on="l_partkey", right_on="p_partkey")

    return merged.groupby("l_orderkey", as_index=False).agg(total_qty=("l_quantity", "sum"))


def exchange_merge_pandas_impl(ctx: DataFrameContext) -> Any:
    """Sorted data from multiple nodes is combined while keeping the sort order."""
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    merged = orders.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    return merged[["o_orderkey", "l_linenumber", "l_quantity"]].sort_values(["o_orderkey", "l_linenumber"])


def exchange_shuffle_pandas_impl(ctx: DataFrameContext) -> Any:
    """Data is redistributed based on the join keys so matching rows end up on the same node."""
    partsupp = ctx.get_table("partsupp")

    ps1 = partsupp[["ps_partkey", "ps_suppkey", "ps_supplycost"]].rename(
        columns={"ps_suppkey": "supp1", "ps_supplycost": "cost1"}
    )
    ps2 = partsupp[["ps_partkey", "ps_suppkey"]].rename(columns={"ps_suppkey": "supp2"})

    merged = ps1.merge(ps2, on="ps_partkey")
    return merged[(merged["supp1"] < merged["supp2"]) & (merged["cost1"] > 100)][["ps_partkey", "supp1", "supp2"]]


# -----------------------------------------------------------------------------
# TopN queries (Pandas)
# -----------------------------------------------------------------------------


def topn_aggregate_pandas_impl(ctx: DataFrameContext) -> Any:
    """Top 10 limit returning 2 columns after aggregation and computed ordering."""
    lineitem = ctx.get_table("lineitem")

    return (
        lineitem.groupby("l_orderkey", as_index=False)
        .agg(total_quantity=("l_quantity", "sum"))
        .nlargest(10, "total_quantity")
    )


def topn_allcols_pandas_impl(ctx: DataFrameContext) -> Any:
    """Top-10 limit returning all columns after ordering over all table rows."""
    lineitem = ctx.get_table("lineitem")

    return lineitem.nlargest(10, "l_extendedprice")


# -----------------------------------------------------------------------------
# Statistical queries (Pandas)
# -----------------------------------------------------------------------------


def statistical_variance_pandas_impl(ctx: DataFrameContext) -> Any:
    """Variance and standard deviation calculations."""
    orders = ctx.get_table("orders")

    filtered = orders[orders["o_orderdate"] >= date(1995, 1, 1)]
    return filtered.groupby("o_orderpriority", as_index=False).agg(
        order_count=("o_orderkey", "count"),
        avg_price=("o_totalprice", "mean"),
        price_variance=("o_totalprice", "var"),
        price_stddev=("o_totalprice", "std"),
    )


def statistical_correlation_pandas_impl(ctx: DataFrameContext) -> Any:
    """Correlation analysis between numeric columns."""
    lineitem = ctx.get_table("lineitem")

    filtered = lineitem[(lineitem["l_shipdate"] >= date(1995, 1, 1)) & (lineitem["l_shipdate"] < date(1996, 1, 1))]

    return ctx.scalar_to_df(
        {
            "avg_quantity": filtered["l_quantity"].mean(),
            "avg_price": filtered["l_extendedprice"].mean(),
            "qty_price_correlation": filtered["l_quantity"].corr(filtered["l_extendedprice"]),
        }
    )


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

    return ctx.scalar_to_df({"count": len(filtered)})


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
    return result.sort_values("max_balance", ascending=False)


def min_by_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find the customer with the lowest account balance in each nation."""
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")

    merged = customer.merge(nation, left_on="c_nationkey", right_on="n_nationkey")

    # Get min balance per nation
    min_idx = merged.groupby("n_name")["c_acctbal"].idxmin()
    result = merged.loc[min_idx][["n_name", "c_name", "c_acctbal"]].rename(columns={"c_acctbal": "min_balance"})
    return result.sort_values("min_balance")


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
    return result[result["part_count"] <= 10].head(100)


def array_agg_distinct_pandas_impl(ctx: DataFrameContext) -> Any:
    """Distinct array aggregation."""
    customer = ctx.get_table("customer")

    return customer.groupby("c_mktsegment", as_index=False).agg(
        nation_keys=("c_nationkey", lambda x: sorted(set(x))),
    )


# -----------------------------------------------------------------------------
# Limit query (Expression)
# -----------------------------------------------------------------------------


def limit_ordered_expression_impl(ctx: DataFrameContext) -> Any:
    """LIMIT clause with ordering on large result set."""
    lineitem = ctx.get_table("lineitem")

    return lineitem.sort(["l_orderkey", "l_linenumber"]).limit(100)


def limit_ordered_pandas_impl(ctx: DataFrameContext) -> Any:
    """LIMIT clause with ordering on large result set."""
    lineitem = ctx.get_table("lineitem")

    return lineitem.sort_values(["l_orderkey", "l_linenumber"]).head(100)


# -----------------------------------------------------------------------------
# Decimal IN list filter queries
# -----------------------------------------------------------------------------


def filter_decimal_in_list_expression_impl(ctx: DataFrameContext) -> Any:
    """IN-list predicate with decimal values and selectivity."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    return lineitem.filter(col("l_extendedprice").is_in([1000.00, 5000.00, 10000.00, 50000.00])).select(
        "l_orderkey", "l_partkey", "l_extendedprice", "l_quantity"
    )


def filter_decimal_in_list_pandas_impl(ctx: DataFrameContext) -> Any:
    """IN-list predicate with decimal values and selectivity."""
    lineitem = ctx.get_table("lineitem")

    return lineitem[lineitem["l_extendedprice"].isin([1000.00, 5000.00, 10000.00, 50000.00])][
        ["l_orderkey", "l_partkey", "l_extendedprice", "l_quantity"]
    ]


# -----------------------------------------------------------------------------
# String LIKE filter queries (LIKE pattern)
# -----------------------------------------------------------------------------


def filter_string_like_expression_impl(ctx: DataFrameContext) -> Any:
    """LIKE predicate with substring pattern matching."""
    part = ctx.get_table("part")
    col = ctx.col

    return part.filter(col("p_name").str.contains("COPPER")).select("p_partkey", "p_name", "p_type", "p_size")


def filter_string_like_pandas_impl(ctx: DataFrameContext) -> Any:
    """LIKE predicate with substring pattern matching."""
    part = ctx.get_table("part")

    return part[part["p_name"].str.contains("COPPER", na=False)][["p_partkey", "p_name", "p_type", "p_size"]]


# -----------------------------------------------------------------------------
# OrderBy decimal queries
# -----------------------------------------------------------------------------


def orderby_decimal_expression_impl(ctx: DataFrameContext) -> Any:
    """Multi-column sort with mixed ASC/DESC on decimal columns."""
    lineitem = ctx.get_table("lineitem")

    return (
        lineitem.sort(["l_extendedprice", "l_discount"], descending=[True, False])
        .select("l_orderkey", "l_extendedprice", "l_discount")
        .limit(100)
    )


def orderby_decimal_pandas_impl(ctx: DataFrameContext) -> Any:
    """Multi-column sort with mixed ASC/DESC on decimal columns."""
    lineitem = ctx.get_table("lineitem")

    return lineitem.sort_values(["l_extendedprice", "l_discount"], ascending=[False, True])[
        ["l_orderkey", "l_extendedprice", "l_discount"]
    ].head(100)


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

    return lineitem.join(date_filtered_orders, left_on="l_orderkey", right_on="o_orderkey", how="semi").select(
        "l_orderkey", "l_partkey", "l_quantity", "l_extendedprice"
    )


def min_max_runtime_filter_pandas_impl(ctx: DataFrameContext) -> Any:
    """Bloom filter and runtime filter effectiveness for join optimization."""
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")

    date_filtered_orders = orders[
        (orders["o_orderdate"] >= date(1995, 1, 1)) & (orders["o_orderdate"] <= date(1995, 3, 31))
    ]["o_orderkey"].unique()

    return lineitem[lineitem["l_orderkey"].isin(date_filtered_orders)][
        ["l_orderkey", "l_partkey", "l_quantity", "l_extendedprice"]
    ]


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

    return (
        merged.join(max_prices, on="c_mktsegment")
        .filter(col("o_totalprice") == col("max_order_value"))
        .select("c_mktsegment", "o_orderkey", "o_orderdate", "max_order_value")
        .unique(subset=["c_mktsegment"])
        .sort("max_order_value", descending=True)
    )


def max_by_complex_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find the most expensive order for each customer segment."""
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")

    merged = orders.merge(customer, left_on="o_custkey", right_on="c_custkey")
    max_idx = merged.groupby("c_mktsegment")["o_totalprice"].idxmax()
    result = merged.loc[max_idx][["c_mktsegment", "o_orderkey", "o_orderdate", "o_totalprice"]].rename(
        columns={"o_totalprice": "max_order_value"}
    )
    return result.sort_values("max_order_value", ascending=False)


def min_by_complex_expression_impl(ctx: DataFrameContext) -> Any:
    """Find the cheapest part for each brand."""
    part = ctx.get_table("part")
    col = ctx.col

    min_prices = part.group_by("p_brand").agg(col("p_retailprice").min().alias("min_price"))

    return (
        part.join(min_prices, on="p_brand")
        .filter(col("p_retailprice") == col("min_price"))
        .select("p_brand", "p_name", "p_type", "min_price")
        .unique(subset=["p_brand"])
        .sort("min_price")
    )


def min_by_complex_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find the cheapest part for each brand."""
    part = ctx.get_table("part")

    min_idx = part.groupby("p_brand")["p_retailprice"].idxmin()
    result = part.loc[min_idx][["p_brand", "p_name", "p_type", "p_retailprice"]].rename(
        columns={"p_retailprice": "min_price"}
    )
    return result.sort_values("min_price")


# -----------------------------------------------------------------------------
# ANY_VALUE queries (modern SQL feature)
# -----------------------------------------------------------------------------


def any_value_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Select any customer name per market segment (faster than MIN/MAX)."""
    customer = ctx.get_table("customer")
    col = ctx.col

    return customer.group_by("c_mktsegment").agg(
        col("c_name").first().alias("sample_customer"),
        col("c_custkey").count().alias("customer_count"),
    )


def any_value_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Select any customer name per market segment (faster than MIN/MAX)."""
    customer = ctx.get_table("customer")

    return customer.groupby("c_mktsegment", as_index=False).agg(
        sample_customer=("c_name", "first"),
        customer_count=("c_custkey", "count"),
    )


def any_value_with_filter_expression_impl(ctx: DataFrameContext) -> Any:
    """Any value with additional aggregates."""
    nation = ctx.get_table("nation")
    col = ctx.col

    return nation.group_by("n_regionkey").agg(
        col("n_name").first().alias("sample_nation"),
        col("n_comment").first().alias("sample_comment"),
        col("n_nationkey").count().alias("nation_count"),
    )


def any_value_with_filter_pandas_impl(ctx: DataFrameContext) -> Any:
    """Any value with additional aggregates."""
    nation = ctx.get_table("nation")

    return nation.groupby("n_regionkey", as_index=False).agg(
        sample_nation=("n_name", "first"),
        sample_comment=("n_comment", "first"),
        nation_count=("n_nationkey", "count"),
    )


# -----------------------------------------------------------------------------
# GROUP BY ALL queries (modern SQL feature)
# Note: GROUP BY ALL automatically groups by all non-aggregate columns
# In DataFrames, we explicitly specify the grouping columns
# -----------------------------------------------------------------------------


def groupby_all_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Automatic grouping by all non-aggregate columns."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    return lineitem.group_by("l_returnflag", "l_linestatus").agg(
        col("l_quantity").sum().alias("total_qty"),
        col("l_extendedprice").mean().alias("avg_price"),
    )


def groupby_all_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Automatic grouping by all non-aggregate columns."""
    lineitem = ctx.get_table("lineitem")

    return lineitem.groupby(["l_returnflag", "l_linestatus"], as_index=False).agg(
        total_qty=("l_quantity", "sum"),
        avg_price=("l_extendedprice", "mean"),
    )


def groupby_all_complex_expression_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY ALL with multiple non-aggregate expressions."""
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    filtered = orders.filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
    return (
        filtered.with_columns(col("o_orderdate").dt.truncate("1mo").alias("order_month"))
        .group_by("order_month", "o_orderpriority")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("o_totalprice").sum().alias("monthly_revenue"),
        )
        .sort(["order_month", "o_orderpriority"])
    )


def groupby_all_complex_pandas_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY ALL with multiple non-aggregate expressions."""
    orders = ctx.get_table("orders")

    filtered = orders[orders["o_orderdate"] >= date(1995, 1, 1)].copy()
    filtered["order_month"] = filtered["o_orderdate"].dt.to_period("M")

    return (
        filtered.groupby(["order_month", "o_orderpriority"], as_index=False)
        .agg(
            order_count=("o_orderkey", "count"),
            monthly_revenue=("o_totalprice", "sum"),
        )
        .sort_values(["order_month", "o_orderpriority"])
    )


# -----------------------------------------------------------------------------
# ORDER BY ALL queries (modern SQL feature)
# -----------------------------------------------------------------------------


def orderby_all_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Order by all columns in SELECT list."""
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col

    return (
        supplier.join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .group_by("r_name", "n_name")
        .agg(col("s_suppkey").count().alias("supplier_count"))
        .sort(["r_name", "n_name", "supplier_count"])
    )


def orderby_all_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Order by all columns in SELECT list."""
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    merged = supplier.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    merged = merged.merge(region, left_on="n_regionkey", right_on="r_regionkey")

    return (
        merged.groupby(["r_name", "n_name"], as_index=False)
        .agg(supplier_count=("s_suppkey", "count"))
        .sort_values(["r_name", "n_name", "supplier_count"])
    )


def orderby_all_desc_expression_impl(ctx: DataFrameContext) -> Any:
    """ORDER BY ALL with descending direction."""
    part = ctx.get_table("part")
    col = ctx.col

    return (
        part.group_by("p_brand", "p_type")
        .agg(col("p_retailprice").mean().alias("avg_price"))
        .sort(["p_brand", "p_type", "avg_price"], descending=True)
        .limit(100)
    )


def orderby_all_desc_pandas_impl(ctx: DataFrameContext) -> Any:
    """ORDER BY ALL with descending direction."""
    part = ctx.get_table("part")

    return (
        part.groupby(["p_brand", "p_type"], as_index=False)
        .agg(avg_price=("p_retailprice", "mean"))
        .sort_values(["p_brand", "p_type", "avg_price"], ascending=False)
        .head(100)
    )


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

    return (
        merged.join(max_costs, on=["ps_partkey", "p_name"])
        .filter(col("ps_supplycost") == col("max_supply_cost"))
        .select("ps_partkey", "p_name", "s_name", "max_supply_cost")
        .unique(subset=["ps_partkey"])
        .sort("max_supply_cost", descending=True)
        .limit(100)
    )


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
    return result.sort_values("max_supply_cost", ascending=False).head(100)


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

    return (
        merged.join(min_costs, on=["ps_partkey", "p_name"])
        .filter(col("ps_supplycost") == col("min_supply_cost"))
        .select("ps_partkey", "p_name", "s_name", "min_supply_cost")
        .unique(subset=["ps_partkey"])
        .sort("min_supply_cost")
        .limit(100)
    )


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
    return result.sort_values("min_supply_cost").head(100)


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

    return (
        orders.filter((col("o_totalprice") > lit(100000)) & (col("o_orderdate") >= lit(date(1995, 1, 1))))
        .join(building_customers, left_on="o_custkey", right_on="c_custkey", how="semi")
        .select("o_orderkey", "o_totalprice")
    )


def predicate_ordering_subquery_pandas_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity with subquery predicate."""
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")

    building_customers = customer[(customer["c_mktsegment"] == "BUILDING") & (customer["c_nationkey"] == 1)][
        "c_custkey"
    ].unique()

    filtered_orders = orders[(orders["o_totalprice"] > 100000) & (orders["o_orderdate"] >= date(1995, 1, 1))]
    return filtered_orders[filtered_orders["o_custkey"].isin(building_customers)][["o_orderkey", "o_totalprice"]]


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
    return (
        orders_source.vstack(lineitem_orders).group_by("source_type").agg(col("cust_id").count().alias("record_count"))
    )


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
    return combined.groupby("source_type", as_index=False).agg(record_count=("cust_id", "count"))


# -----------------------------------------------------------------------------
# Statistical percentiles query
# -----------------------------------------------------------------------------


def statistical_percentiles_expression_impl(ctx: DataFrameContext) -> Any:
    """Percentile calculation functions for distribution analysis."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    return lineitem.group_by("l_returnflag", "l_linestatus").agg(
        col("l_orderkey").count().alias("record_count"),
        col("l_quantity").quantile(0.25).alias("quantity_q1"),
        col("l_quantity").quantile(0.5).alias("quantity_median"),
        col("l_quantity").quantile(0.75).alias("quantity_q3"),
        col("l_extendedprice").quantile(0.95).alias("price_p95"),
    )


def statistical_percentiles_pandas_impl(ctx: DataFrameContext) -> Any:
    """Percentile calculation functions for distribution analysis."""
    lineitem = ctx.get_table("lineitem")

    return lineitem.groupby(["l_returnflag", "l_linestatus"], as_index=False).agg(
        record_count=("l_orderkey", "count"),
        quantity_q1=("l_quantity", lambda x: x.quantile(0.25)),
        quantity_median=("l_quantity", "median"),
        quantity_q3=("l_quantity", lambda x: x.quantile(0.75)),
        price_p95=("l_extendedprice", lambda x: x.quantile(0.95)),
    )


# -----------------------------------------------------------------------------
# Case-insensitive string matching queries
# -----------------------------------------------------------------------------


def string_ilike_start_expression_impl(ctx: DataFrameContext) -> Any:
    """Case insensitive matching prefix pattern."""
    part = ctx.get_table("part")
    col = ctx.col

    return part.filter(col("p_name").str.to_lowercase().str.starts_with("standard")).select(
        col("p_partkey").count().alias("count")
    )


def string_ilike_start_pandas_impl(ctx: DataFrameContext) -> Any:
    """Case insensitive matching prefix pattern."""
    part = ctx.get_table("part")

    count = len(part[part["p_name"].str.lower().str.startswith("standard", na=False)])
    return ctx.scalar_to_df({"count": count})


def string_ilike_end_expression_impl(ctx: DataFrameContext) -> Any:
    """Case insensitive matching suffix pattern."""
    part = ctx.get_table("part")
    col = ctx.col

    return part.filter(col("p_name").str.to_lowercase().str.ends_with("copper")).select(
        col("p_partkey").count().alias("count")
    )


def string_ilike_end_pandas_impl(ctx: DataFrameContext) -> Any:
    """Case insensitive matching suffix pattern."""
    part = ctx.get_table("part")

    count = len(part[part["p_name"].str.lower().str.endswith("copper", na=False)])
    return ctx.scalar_to_df({"count": count})


def string_like_multi_expression_impl(ctx: DataFrameContext) -> Any:
    """Case sensitive matching multipart pattern."""
    part = ctx.get_table("part")
    col = ctx.col

    return part.filter(col("p_name").str.contains("STEEL") & col("p_name").str.contains("BRASS")).select(
        col("p_partkey").count().alias("count")
    )


def string_like_multi_pandas_impl(ctx: DataFrameContext) -> Any:
    """Case sensitive matching multipart pattern."""
    part = ctx.get_table("part")

    count = len(part[part["p_name"].str.contains("STEEL", na=False) & part["p_name"].str.contains("BRASS", na=False)])
    return ctx.scalar_to_df({"count": count})


def string_ilike_multi_expression_impl(ctx: DataFrameContext) -> Any:
    """Case insensitive matching multipart pattern."""
    part = ctx.get_table("part")
    col = ctx.col

    lower_name = col("p_name").str.to_lowercase()
    return part.filter(lower_name.str.contains("steel") & lower_name.str.contains("brass")).select(
        col("p_partkey").count().alias("count")
    )


def string_ilike_multi_pandas_impl(ctx: DataFrameContext) -> Any:
    """Case insensitive matching multipart pattern."""
    part = ctx.get_table("part")

    lower_name = part["p_name"].str.lower()
    count = len(part[lower_name.str.contains("steel", na=False) & lower_name.str.contains("brass", na=False)])
    return ctx.scalar_to_df({"count": count})


def string_like_center_insensitive_expression_impl(ctx: DataFrameContext) -> Any:
    """Case insensitive matching pattern in any location."""
    part = ctx.get_table("part")
    col = ctx.col

    return part.filter(col("p_name").str.to_lowercase().str.contains("steel")).select(
        col("p_partkey").count().alias("count")
    )


def string_like_center_insensitive_pandas_impl(ctx: DataFrameContext) -> Any:
    """Case insensitive matching pattern in any location."""
    part = ctx.get_table("part")

    count = len(part[part["p_name"].str.lower().str.contains("steel", na=False)])
    return ctx.scalar_to_df({"count": count})


# -----------------------------------------------------------------------------
# Additional Window queries
# -----------------------------------------------------------------------------


def window_moving_frame_expression_impl(ctx: DataFrameContext) -> Any:
    """Window aggregations with complex moving frame definitions."""
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    return (
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


def window_moving_frame_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window aggregations with complex moving frame definitions."""
    orders = ctx.get_table("orders")

    filtered = orders[(orders["o_orderdate"] >= date(1995, 1, 1)) & (orders["o_orderdate"] < date(1996, 1, 1))].copy()
    filtered = filtered.sort_values("o_orderdate")
    # Rolling average with 6 order window
    filtered["moving_avg"] = filtered["o_totalprice"].rolling(window=6, min_periods=1).mean()

    return filtered[["o_orderkey", "o_orderdate", "o_totalprice", "moving_avg"]]


def window_unbounded_frame_expression_impl(ctx: DataFrameContext) -> Any:
    """Window aggregations with the same unbounded frame definition."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    return (
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


def window_unbounded_frame_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window aggregations with the same unbounded frame definition."""
    lineitem = ctx.get_table("lineitem")

    filtered = lineitem[(lineitem["l_orderkey"] >= 1) & (lineitem["l_orderkey"] <= 5000)].copy()
    filtered = filtered.sort_values(["l_orderkey", "l_linenumber"])

    filtered["first_line_qty"] = filtered.groupby("l_orderkey")["l_quantity"].transform("first")
    filtered["last_line_qty"] = filtered.groupby("l_orderkey")["l_quantity"].transform("last")

    return filtered[["l_orderkey", "l_linenumber", "l_shipdate", "l_quantity", "first_line_qty", "last_line_qty"]]


# =============================================================================
# Intrinsic Queries (Approximate Median, Date Conversion)
# =============================================================================


def approx_quantile_groupby_expression_impl(ctx: DataFrameContext) -> Any:
    """Approximate median per group via UnifiedExpr.quantile(0.5).

    `UnifiedExpr.quantile()` dispatches to the platform's sketch-backed
    aggregate where one exists:

    - PySpark: `F.percentile_approx(col, 0.5)` (KLL-equivalent).
    - DataFusion: `df_f.approx_percentile_cont(col, 0.5)` (T-Digest).
    - Polars: `.quantile(0.5)` (exact — no sketch alternative; the
      benchmark surface degrades to exact on Polars).

    See `docs/benchmarks/read-primitives-approximate-functions.md` for
    the cross-platform DataFrame coverage matrix.
    """
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    return lineitem.group_by("l_shipmode").agg(col("l_quantity").quantile(0.5).alias("median_quantity"))


def approx_quantile_groupby_pandas_impl(ctx: DataFrameContext) -> Any:
    """Approximate median per group — exact fallback for the pandas family.

    Pandas / Modin / cuDF have no sketch-backed quantile at the
    DataFrame layer, so this implementation returns the exact median.
    Current Dask exposes Series-level T-Digest quantile only when the
    optional `crick` dependency is installed, and does not expose a
    groupby quantile method in the dask-expr API. This query therefore
    remains exact on Dask too.
    """
    lineitem = ctx.get_table("lineitem")

    return lineitem.groupby("l_shipmode", as_index=False).agg(median_quantity=("l_quantity", "median"))


def intrinsic_to_date_expression_impl(ctx: DataFrameContext) -> Any:
    """Count orders matching a specific date."""
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Filter for specific date and count
    return orders.filter(col("o_orderdate") == lit(date(1995, 3, 15))).select(
        col("o_orderkey").count().alias("orders_by_month")
    )


def intrinsic_to_date_pandas_impl(ctx: DataFrameContext) -> Any:
    """Count orders matching a specific date."""
    orders = ctx.get_table("orders")

    target_date = date(1995, 3, 15)
    count = len(orders[orders["o_orderdate"] == target_date])
    return ctx.scalar_to_df({"orders_by_month": count})


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
    return (
        part.filter(
            col("p_name").str.contains("STEEL")
            | col("p_name").str.contains("COPPER")
            | col("p_comment").str.contains("STEEL")
            | col("p_comment").str.contains("COPPER")
        )
        .select("p_partkey", "p_name", "p_mfgr", "p_comment")
        .limit(100)
    )


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
    return part[mask][["p_partkey", "p_name", "p_mfgr", "p_comment"]].head(100)


def fulltext_boolean_search_expression_impl(ctx: DataFrameContext) -> Any:
    """Boolean text search with AND/NOT operators."""
    customer = ctx.get_table("customer")
    col = ctx.col

    # Must contain "BUILDING", must NOT contain "FURNITURE"
    # Also compute a simple relevance score (1 for match, 0 for no match)
    return (
        customer.filter(col("c_comment").str.contains("BUILDING") & ~col("c_comment").str.contains("FURNITURE"))
        .with_columns(col("c_comment").str.contains("BUILDING").cast(int).alias("relevance_score"))
        .select("c_custkey", "c_name", "c_comment", "relevance_score")
        .sort("relevance_score", descending=True)
        .limit(50)
    )


def fulltext_boolean_search_pandas_impl(ctx: DataFrameContext) -> Any:
    """Boolean text search with AND/NOT operators."""
    customer = ctx.get_table("customer")

    # Must contain "BUILDING", must NOT contain "FURNITURE"
    contains_building = customer["c_comment"].str.contains("BUILDING", case=True, na=False)
    contains_furniture = customer["c_comment"].str.contains("FURNITURE", case=True, na=False)

    filtered = customer[contains_building & ~contains_furniture].copy()
    filtered["relevance_score"] = 1  # Simple relevance: all matches score 1

    return (
        filtered[["c_custkey", "c_name", "c_comment", "relevance_score"]]
        .sort_values("relevance_score", ascending=False)
        .head(50)
    )


def fulltext_phrase_search_expression_impl(ctx: DataFrameContext) -> Any:
    """Phrase-based text search for exact phrase match."""
    supplier = ctx.get_table("supplier")
    col = ctx.col

    # Search for exact phrase "Customer Complaints" (case-insensitive for robustness)
    return (
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


def fulltext_phrase_search_pandas_impl(ctx: DataFrameContext) -> Any:
    """Phrase-based text search for exact phrase match."""
    supplier = ctx.get_table("supplier")

    # Search for exact phrase "Customer Complaints" (case-insensitive)
    phrase_match = supplier["s_comment"].str.lower().str.contains("customer complaints", na=False)

    filtered = supplier[phrase_match].copy()
    filtered["phrase_match_score"] = 1  # All matches score 1

    return filtered[["s_suppkey", "s_name", "s_comment", "phrase_match_score"]].sort_values(
        "phrase_match_score", ascending=False
    )


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
    return joined.group_by("n_name", "r_name").agg(
        col("o_orderkey").count().alias("order_count"),
        col("o_totalprice").sum().alias("total_revenue"),
        col("o_totalprice").mean().alias("avg_order_value"),
    )


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
    return merged.groupby(["n_name", "r_name"], as_index=False).agg(
        order_count=("o_orderkey", "count"),
        total_revenue=("o_totalprice", "sum"),
        avg_order_value=("o_totalprice", "mean"),
    )


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
    return (
        joined.group_by("r_name", "n_name", "c_mktsegment")
        .agg(
            col("c_custkey").n_unique().alias("customer_count"),
            col("o_orderkey").count().alias("order_count"),
            col("o_totalprice").sum().alias("total_revenue"),
            col("o_totalprice").mean().alias("avg_order_value"),
        )
        .sort("r_name", "n_name", "c_mktsegment", nulls_last=True)
    )


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

    return result.sort_values(["r_name", "n_name", "c_mktsegment"], na_position="last")


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
    return filtered.group_by("l_returnflag").agg(
        col("l_quantity").filter(col("l_shipmode") == lit("AIR")).sum().alias("AIR"),
        col("l_quantity").filter(col("l_shipmode") == lit("RAIL")).sum().alias("RAIL"),
        col("l_quantity").filter(col("l_shipmode") == lit("SHIP")).sum().alias("SHIP"),
        col("l_quantity").filter(col("l_shipmode") == lit("TRUCK")).sum().alias("TRUCK"),
    )


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
    return filtered.pivot_table(
        index="l_returnflag",
        columns="l_shipmode",
        values="l_quantity",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()


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
    return filtered.melt(
        id_vars=["p_partkey"],
        value_vars=["p_size", "p_retailprice"],
        variable_name="dimension_name",
        value_name="dimension_value",
    )


def unpivot_basic_pandas_impl(ctx: DataFrameContext) -> Any:
    """Unpivot part dimensions into rows.

    Pandas-family implementation using melt.
    """
    part = ctx.get_table("part")

    # Filter and select
    filtered = part[part["p_partkey"] <= 100][["p_partkey", "p_size", "p_retailprice"]].copy()
    filtered["p_size"] = filtered["p_size"].astype(float)

    # Melt (unpivot)
    return filtered.melt(
        id_vars=["p_partkey"],
        value_vars=["p_size", "p_retailprice"],
        var_name="dimension_name",
        value_name="dimension_value",
    )


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
    return (
        orders.filter((col("o_orderdate") >= lit(date(1995, 1, 1))) & (col("o_orderdate") < lit(date(1996, 1, 1))))
        .select("o_orderkey", "o_custkey", "o_orderdate", "o_totalprice")
        .unique()  # Should be eliminated by optimizer since o_orderkey is unique
    )


def optimizer_distinct_elimination_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test DISTINCT elimination when result is already unique (PK included)."""
    orders = ctx.get_table("orders")

    filtered = orders[(orders["o_orderdate"] >= date(1995, 1, 1)) & (orders["o_orderdate"] < date(1996, 1, 1))]
    return filtered[["o_orderkey", "o_custkey", "o_orderdate", "o_totalprice"]].drop_duplicates()


def optimizer_common_subexpression_expression_impl(ctx: DataFrameContext) -> Any:
    """Test Common Subexpression Elimination (CSE).

    Write the SAME complex expression multiple times - optimizer should compute once.
    """
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    # Define the complex expression (will be repeated)
    # DO NOT name it once and reuse - let optimizer find the common subexpression
    return (
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


def optimizer_common_subexpression_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test Common Subexpression Elimination (CSE)."""
    lineitem = ctx.get_table("lineitem")

    filtered = lineitem[lineitem["l_quantity"] > 0].copy()

    # Compute the expression multiple times (pandas will compute each time)
    expr = filtered["l_quantity"] * filtered["l_extendedprice"] * (1 - filtered["l_discount"]) * (1 + filtered["l_tax"])

    filtered["revenue_with_tax"] = expr
    filtered["revenue_copy"] = expr

    return filtered[filtered["revenue_with_tax"] > 1000][
        ["l_orderkey", "l_partkey", "l_suppkey", "l_linenumber", "revenue_with_tax", "revenue_copy"]
    ].head(100)


def optimizer_predicate_pushdown_expression_impl(ctx: DataFrameContext) -> Any:
    """Test predicate pushdown through joins.

    IMPORTANT: Filter AFTER join to let optimizer push predicates down.
    """
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Join first, THEN filter (optimizer should push predicates down)
    return (
        customer.join(orders, col("c_custkey") == col("o_custkey"))
        .filter(col("c_nationkey") == lit(15))  # Predicate on customer - should push before join
        .filter(col("o_orderdate") >= lit(date(1995, 1, 1)))  # Predicate on orders - should push before join
        .select("c_name", "c_mktsegment", "o_orderdate", "o_totalprice")
        .limit(100)
    )


def optimizer_predicate_pushdown_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test predicate pushdown through joins."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    # Join first, then filter (pandas doesn't optimize, but tests the pattern)
    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    filtered = merged[(merged["c_nationkey"] == 15) & (merged["o_orderdate"] >= date(1995, 1, 1))]
    return filtered[["c_name", "c_mktsegment", "o_orderdate", "o_totalprice"]].head(100)


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
    return (
        orders.filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .join(customer, col("o_custkey") == col("c_custkey"))
        .join(nation, col("c_nationkey") == col("n_nationkey"))
        .group_by("n_name", "c_name")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("o_totalprice").sum().alias("total_value"),
        )
    )


def optimizer_join_reordering_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test join reordering optimization."""
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")

    # Join in suboptimal order
    filtered = orders[orders["o_orderdate"] >= date(1995, 1, 1)]
    merged = filtered.merge(customer, left_on="o_custkey", right_on="c_custkey")
    merged = merged.merge(nation, left_on="c_nationkey", right_on="n_nationkey")

    return merged.groupby(["n_name", "c_name"], as_index=False).agg(
        order_count=("o_orderkey", "count"),
        total_value=("o_totalprice", "sum"),
    )


def optimizer_limit_pushdown_expression_impl(ctx: DataFrameContext) -> Any:
    """Test limit pushdown through operations.

    Apply limit at the END only - optimizer should push partial limits down.
    """
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Join and sort, then limit at the end only
    return (
        customer.join(orders, col("c_custkey") == col("o_custkey"))
        .filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .select("c_name", "c_mktsegment", "o_orderdate", "o_totalprice", "o_orderpriority")
        .sort("o_totalprice", descending=True)
        .limit(100)  # Optimizer should push partial limit into join
    )


def optimizer_limit_pushdown_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test limit pushdown through operations."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    filtered = merged[merged["o_orderdate"] >= date(1995, 1, 1)]
    return (
        filtered[["c_name", "c_mktsegment", "o_orderdate", "o_totalprice", "o_orderpriority"]]
        .sort_values("o_totalprice", ascending=False)
        .head(100)
    )


def optimizer_aggregate_pushdown_expression_impl(ctx: DataFrameContext) -> Any:
    """Test aggregate pushdown before join.

    Join first, THEN aggregate - optimizer can push partial aggregates before join.
    """
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Join first, then aggregate (optimizer can push partial agg before join)
    return (
        customer.join(orders, col("c_custkey") == col("o_custkey"))
        .filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .group_by("c_custkey", "c_name", "c_mktsegment")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("o_totalprice").sum().alias("total_spent"),
            col("o_totalprice").mean().alias("avg_order"),
        )
    )


def optimizer_aggregate_pushdown_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test aggregate pushdown before join."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    filtered = merged[merged["o_orderdate"] >= date(1995, 1, 1)]

    return filtered.groupby(["c_custkey", "c_name", "c_mktsegment"], as_index=False).agg(
        order_count=("o_orderkey", "count"),
        total_spent=("o_totalprice", "sum"),
        avg_order=("o_totalprice", "mean"),
    )


def optimizer_constant_folding_expression_impl(ctx: DataFrameContext) -> Any:
    """Test constant folding optimization.

    Use Spark expressions for constants - optimizer should fold them at compile time.
    """
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    # Use Spark expressions for constants (optimizer should fold lit(2)*lit(3)+lit(4) to lit(10))
    return (
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


def optimizer_constant_folding_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test constant folding optimization."""
    lineitem = ctx.get_table("lineitem")

    filtered = lineitem[lineitem["l_quantity"] > 0].copy()
    # In pandas, constants are evaluated at Python level anyway
    filtered["scaled_quantity"] = filtered["l_quantity"] * (2 * 3 + 4)
    filtered["discounted_unit_price"] = filtered["l_extendedprice"] * (1 - 0.1) / 10

    return filtered[["l_orderkey", "l_quantity", "scaled_quantity", "discounted_unit_price"]].head(1000)


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
    return (
        customer.join(orders, col("c_custkey") == col("o_custkey"))
        .join(lineitem, col("o_orderkey") == col("l_orderkey"))
        .filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .filter(col("l_quantity") > lit(10))
        .select("c_name")  # Only select c_name at the end - optimizer prunes all other columns
        .unique()
        .limit(100)
    )


def optimizer_column_pruning_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test column pruning optimization."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    merged = merged.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    filtered = merged[(merged["o_orderdate"] >= date(1995, 1, 1)) & (merged["l_quantity"] > 10)]

    return filtered[["c_name"]].drop_duplicates().head(100)


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
    return ctx.concat([urgent, high, medium]).sort("o_totalprice", descending=True).limit(100)


def optimizer_union_optimization_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test union optimization."""
    orders = ctx.get_table("orders")

    cols = ["o_orderkey", "o_custkey", "o_orderpriority", "o_totalprice"]
    urgent = orders[orders["o_orderpriority"] == "1-URGENT"][cols]
    high = orders[orders["o_orderpriority"] == "2-HIGH"][cols]
    medium = orders[orders["o_orderpriority"] == "3-MEDIUM"][cols]

    combined = ctx.concat([urgent, high, medium])
    return combined.sort_values("o_totalprice", ascending=False).head(100)


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

    return (
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


def optimizer_runtime_filter_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test runtime filter / dynamic partition pruning."""
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")

    # Selective filter on part table
    selective_parts = part[(part["p_brand"] == "Brand#23") & (part["p_container"] == "MED BOX")]

    merged = lineitem.merge(selective_parts, left_on="l_partkey", right_on="p_partkey")
    return merged[["l_orderkey", "l_quantity", "l_extendedprice", "p_partkey", "p_name"]].head(100)


def optimizer_groupjoin_expression_impl(ctx: DataFrameContext) -> Any:
    """Test group-join (join+aggregate fusion) optimization.

    Join orders→lineitem then immediately GROUP BY join key - good optimizers
    fuse these into a single grouped-join pass, never materializing the full
    intermediate result.
    """
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    return (
        orders.join(lineitem, col("o_orderkey") == col("l_orderkey"))
        .group_by("o_orderkey", "o_custkey", "o_orderdate")
        .agg(
            col("l_linenumber").count().alias("line_count"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"),
        )
        .sort("revenue", descending=True)
        .limit(100)
    )


def optimizer_groupjoin_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test group-join (join+aggregate fusion) optimization."""
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    merged = orders.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    merged = merged.copy()
    merged["revenue"] = merged["l_extendedprice"] * (1 - merged["l_discount"])

    return (
        merged.groupby(["o_orderkey", "o_custkey", "o_orderdate"], as_index=False)
        .agg(line_count=("l_linenumber", "count"), revenue=("revenue", "sum"))
        .nlargest(100, "revenue")
        .reset_index(drop=True)
    )


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
    return (
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
    return filtered[filtered["order_rank"] <= 3][cols].sort_values(["c_custkey", "order_rank"]).reset_index(drop=True)


def qualify_dense_rank_expression_impl(ctx: DataFrameContext) -> Any:
    """Find top 2 most expensive parts in each category using DENSE_RANK.

    Expression-family implementation using window functions.
    """
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    # Add dense rank and filter (QUALIFY equivalent)
    return (
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


def qualify_dense_rank_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find top 2 most expensive parts in each category using DENSE_RANK."""
    part = ctx.get_table("part")

    df = part.copy()

    # Add dense rank within partition
    df["price_rank"] = df.groupby("p_type")["p_retailprice"].rank(method="dense", ascending=False)

    # Filter (QUALIFY equivalent)
    return (
        df[df["price_rank"] <= 2][["p_type", "p_name", "p_retailprice", "price_rank"]]
        .sort_values(["p_type", "price_rank"])
        .reset_index(drop=True)
    )


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
    return (
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
    return (
        filtered[filtered["quartile"] == 4][["c_mktsegment", "o_orderkey", "o_totalprice", "quartile"]]
        .sort_values(["c_mktsegment", "o_totalprice"], ascending=[True, False])
        .reset_index(drop=True)
    )


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
    return (
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


def qualify_percentile_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find orders in top 10% by value for each order priority using PERCENT_RANK."""
    orders = ctx.get_table("orders")

    # Filter
    filtered = orders[orders["o_orderdate"] >= date(1995, 1, 1)].copy()

    # Add percent rank within partition
    filtered["price_percentile"] = filtered.groupby("o_orderpriority")["o_totalprice"].rank(pct=True)

    # Filter for top 10%
    return (
        filtered[filtered["price_percentile"] >= 0.9][
            ["o_orderpriority", "o_orderkey", "o_totalprice", "price_percentile"]
        ]
        .sort_values(["o_orderpriority", "o_totalprice"], ascending=[True, False])
        .reset_index(drop=True)
    )


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
    return (
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
    return (
        filtered[filtered["quantity_cumulative_dist"] >= 0.95][
            ["l_shipdate", "l_orderkey", "l_linenumber", "l_quantity", "quantity_cumulative_dist"]
        ]
        .sort_values(["l_shipdate", "l_quantity"], ascending=[True, False])
        .reset_index(drop=True)
    )


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
    return (
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
    return (
        filtered[filtered["o_totalprice"] > filtered["prev_order_price"]][
            ["c_custkey", "c_name", "o_orderkey", "o_orderdate", "o_totalprice", "prev_order_price"]
        ]
        .sort_values(["c_custkey", "o_orderdate"])
        .reset_index(drop=True)
    )


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

    return (
        customer.filter(col("c_nationkey") == lit(1))
        .select(
            "c_custkey",
            struct(col("c_name"), col("c_address"), col("c_phone")).alias("contact_info"),
            "c_acctbal",
        )
        .limit(100)
    )


def struct_construction_pandas_impl(ctx: DataFrameContext) -> Any:
    """Construct struct from columns."""
    customer = ctx.get_table("customer")

    filtered = customer[customer["c_nationkey"] == 1].copy()

    # Create dict column to represent struct
    filtered["contact_info"] = filtered.apply(
        lambda row: {"c_name": row["c_name"], "c_address": row["c_address"], "c_phone": row["c_phone"]}, axis=1
    )

    return filtered[["c_custkey", "contact_info", "c_acctbal"]].head(100).reset_index(drop=True)


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
    return (
        with_struct.select(
            "c_custkey",
            col("info").struct.field("name").alias("name"),
            col("info").struct.field("balance").alias("balance"),
        )
        .filter(col("balance") > lit(5000))
        .limit(100)
    )


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
    return filtered[filtered["balance"] > 5000][["c_custkey", "name", "balance"]].head(100).reset_index(drop=True)


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
    return supplier_parts.with_columns(col("parts").list.contains(lit(100)).alias("has_part_100")).limit(100)


def array_contains_pandas_impl(ctx: DataFrameContext) -> Any:
    """Check if array contains a value."""
    partsupp = ctx.get_table("partsupp")

    # Aggregate parts per supplier into lists
    supplier_parts = partsupp.groupby("ps_suppkey")["ps_partkey"].apply(list).reset_index()
    supplier_parts.columns = ["ps_suppkey", "parts"]

    # Check if 100 is in each list
    supplier_parts["has_part_100"] = supplier_parts["parts"].apply(lambda x: 100 in x)

    return supplier_parts.head(100).reset_index(drop=True)


def array_distinct_expression_impl(ctx: DataFrameContext) -> Any:
    """Get distinct array elements.

    Expression-family implementation using array aggregation and unique.
    """
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    # Aggregate ship modes per order
    ship_modes = lineitem.group_by("l_orderkey").agg(col("l_shipmode").list().alias("modes"))

    # Get unique modes
    return ship_modes.with_columns(col("modes").list.unique().alias("unique_modes")).limit(100)


def array_distinct_pandas_impl(ctx: DataFrameContext) -> Any:
    """Get distinct array elements."""
    lineitem = ctx.get_table("lineitem")

    # Aggregate ship modes per order
    ship_modes = lineitem.groupby("l_orderkey")["l_shipmode"].apply(list).reset_index()
    ship_modes.columns = ["l_orderkey", "modes"]

    # Get unique modes
    ship_modes["unique_modes"] = ship_modes["modes"].apply(lambda x: list(set(x)))

    return ship_modes.head(100).reset_index(drop=True)


def array_length_expression_impl(ctx: DataFrameContext) -> Any:
    """Get array length/cardinality.

    Expression-family implementation using array aggregation and length.
    """
    partsupp = ctx.get_table("partsupp")
    col = ctx.col

    # Aggregate parts per supplier
    supplier_parts = partsupp.group_by("ps_suppkey").agg(col("ps_partkey").list().alias("parts"))

    # Get count and sort
    return (
        supplier_parts.with_columns(col("parts").list.len().alias("num_parts")).sort(col("num_parts").desc()).limit(100)
    )


def array_length_pandas_impl(ctx: DataFrameContext) -> Any:
    """Get array length/cardinality."""
    partsupp = ctx.get_table("partsupp")

    # Aggregate parts per supplier
    supplier_parts = partsupp.groupby("ps_suppkey")["ps_partkey"].apply(list).reset_index()
    supplier_parts.columns = ["ps_suppkey", "parts"]

    # Get length
    supplier_parts["num_parts"] = supplier_parts["parts"].apply(len)

    # Sort by num_parts descending
    return supplier_parts.sort_values("num_parts", ascending=False).head(100).reset_index(drop=True)


def array_min_max_expression_impl(ctx: DataFrameContext) -> Any:
    """Get min/max from array.

    Expression-family implementation using array aggregation and min/max.
    """
    orders = ctx.get_table("orders")
    col = ctx.col

    # Aggregate prices per customer
    order_prices = orders.group_by("o_custkey").agg(col("o_totalprice").list().alias("prices"))

    # Get min and max from array
    return order_prices.with_columns(
        col("prices").list.min().alias("min_order"), col("prices").list.max().alias("max_order")
    ).limit(100)


def array_min_max_pandas_impl(ctx: DataFrameContext) -> Any:
    """Get min/max from array."""
    orders = ctx.get_table("orders")

    # Aggregate prices per customer
    order_prices = orders.groupby("o_custkey")["o_totalprice"].apply(list).reset_index()
    order_prices.columns = ["o_custkey", "prices"]

    # Get min and max
    order_prices["min_order"] = order_prices["prices"].apply(min)
    order_prices["max_order"] = order_prices["prices"].apply(max)

    return order_prices.head(100).reset_index(drop=True)


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
    return (
        joined.group_by("o_orderkey")
        .agg(
            struct(col("l_linenumber"), col("l_partkey"), col("l_quantity"), col("l_extendedprice"))
            .list()
            .alias("line_items")
        )
        .limit(50)
    )


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
    return (
        order_prices.filter(col("cnt") >= 5)
        .with_columns(col("prices").list.slice(0, 3).alias("top_3_orders"))
        .select("o_custkey", "top_3_orders")
        .limit(100)
    )


def array_slice_pandas_impl(ctx: DataFrameContext) -> Any:
    """Get array slice/subset."""
    orders = ctx.get_table("orders")

    # Aggregate prices per customer sorted descending
    order_prices = orders.groupby("o_custkey")["o_totalprice"].apply(lambda x: sorted(x, reverse=True)).reset_index()
    order_prices.columns = ["o_custkey", "prices"]

    # Filter for 5+ orders and get top 3
    order_prices = order_prices[order_prices["prices"].apply(len) >= 5].copy()
    order_prices["top_3_orders"] = order_prices["prices"].apply(lambda x: x[:3])

    return order_prices[["o_custkey", "top_3_orders"]].head(100).reset_index(drop=True)


def array_sort_expression_impl(ctx: DataFrameContext) -> Any:
    """Sort array elements.

    Expression-family implementation using array sorting.
    """
    part = ctx.get_table("part")
    col = ctx.col

    # Aggregate sizes per brand
    part_sizes = part.group_by("p_brand").agg(col("p_size").list().alias("sizes"))

    # Sort the array
    return part_sizes.with_columns(col("sizes").list.sort().alias("sorted_sizes")).limit(50)


def array_sort_pandas_impl(ctx: DataFrameContext) -> Any:
    """Sort array elements."""
    part = ctx.get_table("part")

    # Aggregate sizes per brand
    part_sizes = part.groupby("p_brand")["p_size"].apply(list).reset_index()
    part_sizes.columns = ["p_brand", "sizes"]

    # Sort each array
    part_sizes["sorted_sizes"] = part_sizes["sizes"].apply(sorted)

    return part_sizes.head(50).reset_index(drop=True)


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
    return supplier_parts.explode("parts").rename({"parts": "part_key"})


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
    return result.with_columns(map_from_entries("entries").alias("part_costs")).select("ps_suppkey", "part_costs")


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
    return with_map.select(
        "ps_suppkey",
        col("part_costs").map.get(lit("1")).alias("cost_for_part_1"),
        col("part_costs").map.get(lit("5")).alias("cost_for_part_5"),
    ).limit(10)


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

    return result[["ps_suppkey", "cost_for_part_1", "cost_for_part_5"]].head(10).reset_index(drop=True)


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
    return with_map.select(
        "ps_suppkey",
        col("part_costs").map.keys().alias("part_ids"),
        col("part_costs").map.values().alias("costs"),
    )


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

    return result[["ps_suppkey", "part_ids", "costs"]].reset_index(drop=True)


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
    return order_prices.with_columns(
        col("prices").list.eval(elem.filter(elem > lit(100000))).alias("large_orders")
    ).limit(100)


def list_filter_pandas_impl(ctx: DataFrameContext) -> Any:
    """Filter array elements by condition."""
    orders = ctx.get_table("orders")

    # Aggregate prices per customer
    order_prices = orders.groupby("o_custkey")["o_totalprice"].apply(list).reset_index()
    order_prices.columns = ["o_custkey", "prices"]

    # Filter to keep only large orders
    order_prices["large_orders"] = order_prices["prices"].apply(lambda x: [p for p in x if p > 100000])

    return order_prices.head(100).reset_index(drop=True)


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
    return part_prices.with_columns(col("prices").list.eval(elem * lit(1.1)).alias("prices_with_tax")).limit(50)


def list_transform_pandas_impl(ctx: DataFrameContext) -> Any:
    """Transform each array element."""
    part = ctx.get_table("part")

    # Aggregate prices per brand
    part_prices = part.groupby("p_brand")["p_retailprice"].apply(list).reset_index()
    part_prices.columns = ["p_brand", "prices"]

    # Transform with 10% markup
    part_prices["prices_with_tax"] = part_prices["prices"].apply(lambda x: [p * 1.1 for p in x])

    return part_prices.head(50).reset_index(drop=True)


def list_reduce_expression_impl(ctx: DataFrameContext) -> Any:
    """Reduce array to single value.

    Expression-family implementation using list sum (as reduce equivalent).
    """
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    # Aggregate quantities per order
    quantities = lineitem.group_by("l_orderkey").agg(col("l_quantity").list().alias("qtys"))

    # Reduce to sum (most frameworks don't have general reduce, use sum)
    return quantities.with_columns(col("qtys").list.sum().alias("total_qty")).limit(100)


def list_reduce_pandas_impl(ctx: DataFrameContext) -> Any:
    """Reduce array to single value."""
    lineitem = ctx.get_table("lineitem")

    # Aggregate quantities per order
    quantities = lineitem.groupby("l_orderkey")["l_quantity"].apply(list).reset_index()
    quantities.columns = ["l_orderkey", "qtys"]

    # Reduce to sum
    quantities["total_qty"] = quantities["qtys"].apply(sum)

    return quantities.head(100).reset_index(drop=True)


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
    return (
        orders.with_columns(
            col("o_comment").str.split(" ").list.get(0).alias("first_word"),
            col("o_comment").str.len_chars().alias("comment_length"),
        )
        .filter(col("comment_length") > lit(10))
        .select("o_orderkey", "o_comment", "first_word", "comment_length")
        .limit(1000)
    )


def json_extract_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Extract from JSON with simple path expressions."""
    orders = ctx.get_table("orders")

    # Simulate JSON extraction with string operations
    df = orders.copy()
    df["first_word"] = df["o_comment"].str.split(" ").str[0]
    df["comment_length"] = df["o_comment"].str.len()

    return (
        df[df["comment_length"] > 10][["o_orderkey", "o_comment", "first_word", "comment_length"]]
        .head(1000)
        .reset_index(drop=True)
    )


def json_extract_nested_expression_impl(ctx: DataFrameContext) -> Any:
    """Extract from JSON with complex path expressions.

    Expression-family implementation - uses string operations as placeholder.
    """
    customer = ctx.get_table("customer")
    col = ctx.col
    lit = ctx.lit

    # Simulate nested extraction with string split operations
    return (
        customer.with_columns(
            col("c_comment").str.split(" ").list.get(0).alias("segment_word"),
            col("c_comment").str.split(",").list.get(0).alias("first_segment"),
            col("c_comment").str.len_chars().alias("comment_len"),
        )
        .filter(col("comment_len") > lit(20))
        .select("c_custkey", "segment_word", "first_segment", "comment_len")
        .limit(500)
    )


def json_extract_nested_pandas_impl(ctx: DataFrameContext) -> Any:
    """Extract from JSON with complex path expressions."""
    customer = ctx.get_table("customer")

    # Simulate nested extraction with string operations
    df = customer.copy()
    df["segment_word"] = df["c_comment"].str.split(" ").str[0]
    df["first_segment"] = df["c_comment"].str.split(",").str[0]
    df["comment_len"] = df["c_comment"].str.len()

    return (
        df[df["comment_len"] > 20][["c_custkey", "segment_word", "first_segment", "comment_len"]]
        .head(500)
        .reset_index(drop=True)
    )


def json_aggregates_expression_impl(ctx: DataFrameContext) -> Any:
    """Create JSON array and object with aggregate functions.

    Expression-family implementation - creates list structures as JSON equivalent.
    """
    part = ctx.get_table("part")
    col = ctx.col

    # Filter and aggregate into list structures (JSON array equivalent)
    return (
        part.filter(col("p_type").str.contains("STEEL"))
        .group_by("p_brand")
        .agg(
            col("p_name").list().alias("part_names"),
            col("p_retailprice").list().alias("part_prices"),
            col("p_partkey").count().alias("part_count"),
        )
        .limit(100)
    )


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
    return (
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
    return (
        filtered_lineitem.join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .filter(col("l_shipdate") >= col("o_orderdate"))
        .with_columns((col("l_shipdate") - col("o_orderdate")).dt.total_days().alias("days_to_ship"))
        .select("l_orderkey", "l_shipdate", "o_orderdate", "o_totalprice", "days_to_ship")
        .limit(100)
    )


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

_CATEGORY_CODES = {
    "A": QueryCategory.AGGREGATE,
    "C": QueryCategory.SCAN,
    "F": QueryCategory.FILTER,
    "G": QueryCategory.GROUP_BY,
    "J": QueryCategory.JOIN,
    "M": QueryCategory.MULTI_JOIN,
    "P": QueryCategory.PROJECTION,
    "Q": QueryCategory.SUBQUERY,
    "S": QueryCategory.SORT,
    "W": QueryCategory.WINDOW,
}

_QUERY_METADATA = """\
aggregation_distinct|Distinct Aggregation|Distinct count of high cardinality key on a large table|A||SELECT COUNT(DISTINCT o_custkey) FROM orders WHERE o_orderdate >= DATE '1995-01-01'
aggregation_distinct_groupby|Distinct Aggregation with Group By|Distinct count of high cardinality keys in low cardinality groups|A,G||
approx_count_distinct_simple|Approximate Distinct Count|HLL distinct count on a high-cardinality key (sketch on Polars/PySpark/DataFusion; exact on Pandas/Modin/cuDF/Dask)|A||SELECT APPROX_COUNT_DISTINCT(o_custkey) FROM orders WHERE o_orderdate >= DATE '1995-01-01'
approx_count_distinct_groupby|Approximate Distinct Count with Group By|HLL distinct counts per low-cardinality group (sketch on Polars/PySpark/DataFusion; exact on Pandas/Modin/cuDF/Dask)|A,G||
aggregation_groupby_large|Large Cardinality Group By|Aggregates within high cardinality grouping|A,G||
aggregation_groupby_small|Small Cardinality Group By|Aggregates within low cardinality grouping|A,G||
aggregation_materialize|Nested Aggregation|Nested aggregation requiring CTE materialization|A,Q||
aggregation_materialize_subquery|Subquery Materialization|Complex nested aggregation with joins|A,Q,J||
aggregation_partition|Partition Key Aggregation|Aggregates over the partition key|A,G||
aggregation_selective|Selective Aggregation|Aggregate on a small subset of rows|A,F||
aggregation_simple|Simple Aggregation|Aggregate over all rows in table|A||
filter_selective|High Selectivity Filter|High selectivity filter - few rows match|F||
filter_non_selective|Low Selectivity Filter|Low selectivity filter - many rows match|F||
count_star|Count Star|Metadata-based count optimization vs full table scan|A||
decimal_arithmetic|Decimal Arithmetic|Decimal precision arithmetic with complex expressions|P||
orderby_simple|Simple Order By|Simple ORDER BY single column|S||
orderby_multi|Multi-Column Order By|ORDER BY multiple columns|S||
orderby_desc|Descending Order By|ORDER BY with descending sort|S||
topn|Top-N Query|Top-N query with ORDER BY and LIMIT|S||
limit|Simple Limit|Simple LIMIT without ORDER BY|C||
limit_ordered|Ordered Limit|LIMIT clause with ordering on large result set|S||
string_like|String LIKE|String LIKE pattern matching|F||
string_starts_with|String Starts With|String starts_with pattern matching|F||
string_ends_with|String Ends With|String ends_with pattern matching|F||
string_concat|String Concatenation|String concatenation|P||
string_substring|String Substring|String substring extraction|P||
window_row_number|Window ROW_NUMBER|Window function ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)|W||
window_rank|Window RANK|Window function RANK() OVER (PARTITION BY ... ORDER BY ...)|W||
window_sum|Window SUM|Window function SUM() OVER (PARTITION BY ...)|W,A||
window_running_sum|Window Running Sum|Window function SUM() OVER (ORDER BY ...) - cumulative sum|W,A||
broadcast_join_two_tables|Broadcast Join (2 tables)|One small table broadcast to join with one large table|J||
broadcast_join_three_tables|Broadcast Join (3 tables)|Two small tables broadcast to join with one large table|J,M||
predicate_ordering_aggregation|Predicate Ordering with Aggregation|Order filter predicates by selectivity for aggregation|F,A||
shuffle_join|Shuffle Join|Data is redistributed based on the join keys|J,A||
empty_build_join|Empty Build Side Join|Join when build side produces no rows (edge case handling)|J||
filter_bigint_selective|Bigint Selective Filter|Equality predicate with high selectivity on integer column|F||
filter_bigint_non_selective|Bigint Non-Selective Filter|Range predicate with low selectivity on large table|F,A||
filter_bigint_in_list_selective|Bigint IN List Filter|IN-list predicate with highly selective integer values|F|filter_bigint_in_list|
filter_decimal_selective|Decimal Selective Filter|Compound equality predicate with multiple decimal columns|F||
filter_decimal_non_selective|Decimal Non-Selective Filter|Range predicate on decimal column with low selectivity|F,A||
filter_string_selective|String Selective Filter|Exact string equality with high selectivity on varchar column|F||
filter_string_non_selective|String Non-Selective Filter|String comparison with low selectivity (most rows match)|F,A||
filter_in_predicate_selective|IN Predicate with Subquery|IN predicate with subquery and selective filtering|F,Q|filter_in_predicate_subquery|
groupby_bigint_highndv|High NDV GroupBy|GROUP BY with high distinct value count (many groups)|G,A|groupby_highndv|
groupby_bigint_lowndv|Low NDV GroupBy|GROUP BY with low distinct value count (few groups)|G,A|groupby_lowndv|
groupby_bigint_pk|Primary Key GroupBy|GROUP BY on primary key (one row per group)|G,A|groupby_pk|
groupby_decimal_highndv|High NDV Decimal GroupBy|GROUP BY with high cardinality decimal column|G,A||
groupby_decimal_lowndv|Low NDV Decimal GroupBy|GROUP BY with low cardinality decimal column|G,A||
orderby_all|Full Table Order By|Sort on full table with simple integer ordering|S||
orderby_bigint|Bigint Order By|Sort with aggregation results on integer column|S,A||
orderby_bigint_expression|Expression Order By|Sort on computed expressions with DESC ordering|S,P|orderby_expression|
orderby_multicol|Multi-Column Complex Order By|Complex multi-column sort with string, date, and decimal columns|S||
orderby_shortstrings|Short Strings Order By|Sort on short string columns with DISTINCT operation|S||
shuffle_inner_join_one_to_many_string_with_groupby|Inner Join with GroupBy|Standard inner join with one-to-many relationship|J,G,A|shuffle_inner_join_groupby|
shuffle_left_join_one_to_many_string_with_groupby|Left Join with GroupBy|LEFT JOIN with preservation of all left-side rows|J,G,A|shuffle_left_join_groupby|
shuffle_full_join_one_to_many_string_with_groupby|Full Outer Join with GroupBy|FULL OUTER JOIN with string grouping and aggregation|J,G,A|shuffle_full_join_groupby|
shuffle_1mb_rows|Self Join with Hash Collision|Self-join with hash collision handling on large table|J,A|shuffle_self_join|
string_equal_predicate|String Equality|Exact string equality with selective matching|F,A|string_equal|
string_equal_predicate_lower|String Equality (Case Insensitive)|Equality predicate after applying case conversion|F,A|string_equal_lower|
string_in_predicate|String IN Predicate|IN predicate with string values|F,A||
string_like_predicate_center|String LIKE Center|Case sensitive matching pattern in any location|F,A|string_like_center|
string_like_predicate_end|String LIKE Suffix|Case sensitive matching suffix pattern|F,A|string_like_suffix|
string_like_predicate_start|String LIKE Prefix|Case sensitive matching prefix pattern|F,A|string_like_prefix|
window_growing_frame|Window Growing Frame|Running sum window aggregation with growing frame size|W,A||
window_lead_lag_same_frame|Window Lead/Lag|Offset window functions over the same frame|W|window_lead_lag|
window_multiple_orderings|Window Dense Rank|Window function DENSE_RANK() OVER (PARTITION BY ... ORDER BY ...)|W|window_dense_rank|
predicate_ordering_aggregation_groupby|Predicate Ordering with GroupBy|Order filter predicates by selectivity for aggregation within a low cardinality grouping|F,G,A|predicate_ordering_groupby|
predicate_ordering_costs|Predicate Ordering Costs|Order filter predicates by selectivity with result projection only|F,P||
broadcast_join_four_tables|Broadcast Join (4 tables)|Three small tables broadcast to join with one large table|J,M,A||
exchange_broadcast|Exchange Broadcast|One small table is copied to all nodes that have the large table|J,A||
exchange_merge|Exchange Merge|Sorted data from multiple nodes is combined while keeping the sort order|J,S||
exchange_shuffle|Exchange Shuffle|Data is redistributed based on the join keys so matching rows end up on the same node|J||
topn_aggregate_2columns|TopN with Aggregation|Top 10 limit returning 2 columns after aggregation and computed ordering|S,A|topn_aggregate|
topn_ordered_allcols|TopN All Columns|Top-10 limit returning all columns after ordering over all table rows|S,C|topn_allcols|
statistical_variance_stddev|Variance and StdDev|Variance and standard deviation calculations|A|statistical_variance|
statistical_correlation|Correlation Analysis|Correlation analysis between numeric columns|A||
long_predicate|Long Predicate|Query with many conjunctive predicates across multiple tables|F,J,M||
max_by_simple|MAX_BY Simple|Find the customer with the highest account balance in each nation|A,J||
min_by_simple|MIN_BY Simple|Find the customer with the lowest account balance in each nation|A,J||
array_agg_simple|Array Aggregation|Aggregate part keys into arrays per supplier|A||
array_agg_distinct|Distinct Array Aggregation|Distinct array aggregation|A||
filter_decimal_in_list_selective|Decimal IN List Filter|IN-list predicate with decimal values and selectivity|F|filter_decimal_in_list|
filter_string_like|String LIKE Filter|LIKE predicate with substring pattern matching|F||
orderby_decimal16|Decimal Order By|Multi-column sort with mixed ASC/DESC on decimal columns|S|orderby_decimal|
min_max_runtime_filter|Min/Max Runtime Filter|Bloom filter and runtime filter effectiveness for join optimization|F,J||
max_by_complex|MAX_BY Complex|Find the most expensive order for each customer segment|A,J||
min_by_complex|MIN_BY Complex|Find the cheapest part for each brand|A||
any_value_simple|ANY_VALUE Simple|Select any customer name per market segment (faster than MIN/MAX)|A,G||
any_value_with_filter|ANY_VALUE with Filter|Any value with additional aggregates|A,G||
groupby_all_simple|GROUP BY ALL Simple|Automatic grouping by all non-aggregate columns|A,G||
groupby_all_complex|GROUP BY ALL Complex|GROUP BY ALL with multiple non-aggregate expressions|A,G||
orderby_all_simple|ORDER BY ALL Simple|Order by all columns in SELECT list|S,J,A||
orderby_all_desc|ORDER BY ALL Descending|ORDER BY ALL with descending direction|S,A||
max_by_with_ties|MAX_BY with Ties|Find the supplier with the highest supply cost for each part|A,J,M||
min_by_with_ties|MIN_BY with Ties|Find the supplier with the lowest supply cost for each part|A,J,M||
predicate_ordering_subquery|Predicate Ordering with Subquery|Order filter predicates by selectivity with subquery predicate|F,Q,J||
shuffle_inner_join_union_all_with_groupby|Union All with GroupBy|Complex join with UNION ALL and different data sources|J,G,A|shuffle_union_all_groupby|
statistical_percentiles|Statistical Percentiles|Percentile calculation functions for distribution analysis|A,G||
string_ilike_predicate_start|String ILIKE Prefix|Case insensitive matching prefix pattern|F,A|string_ilike_start|
string_ilike_predicate_end|String ILIKE Suffix|Case insensitive matching suffix pattern|F,A|string_ilike_end|
string_like_predicate_multi|String LIKE Multi|Case sensitive matching multipart pattern|F,A|string_like_multi|
string_ilike_predicate_multi|String ILIKE Multi|Case insensitive matching multipart pattern|F,A|string_ilike_multi|
string_like_predicate_center_insensitive|String ILIKE Center|Case insensitive matching pattern in any location|F,A|string_like_center_insensitive|
window_moving_frame|Window Moving Frame|Window aggregations with complex moving frame definitions|W,A||
window_unbounded_frame|Window Unbounded Frame|Window aggregations with the same unbounded frame definition|W||
approx_quantile_groupby|Approximate Median|Approximate statistical function (PERCENTILE_CONT for median)|A,G||
intrinsic_to_date|Date Conversion Filter|Date parsing and conversion function performance|F,A||
fulltext_simple_search|Simple Text Search|Basic full-text search using string pattern matching|F||
fulltext_boolean_search|Boolean Text Search|Boolean text search with AND/NOT operators|F,S||
fulltext_phrase_search|Phrase Text Search|Phrase-based text search with ranking|F,S||
olap_cube_analysis|OLAP CUBE Analysis|CUBE operation for multidimensional analysis|A,G,J||
olap_rollup_analysis|OLAP ROLLUP Analysis|ROLLUP operation for hierarchical aggregation|A,G,J,S||
pivot_basic|Basic Pivot|Pivot ship modes into columns|A,G||
unpivot_basic|Basic Unpivot|Unpivot part dimensions into rows|P||
optimizer_distinct_elimination|Optimizer: Distinct Elimination|Test DISTINCT elimination when result is already unique|F,P||
optimizer_common_subexpression|Optimizer: Common Subexpression|Test Common Subexpression Elimination (CSE)|P,F||
optimizer_predicate_pushdown|Optimizer: Predicate Pushdown|Test predicate pushdown through joins|J,F||
optimizer_join_reordering|Optimizer: Join Reordering|Test join reordering based on cardinality|J,A,G||
optimizer_limit_pushdown|Optimizer: Limit Pushdown|Test limit pushdown through operations|J,S||
optimizer_aggregate_pushdown|Optimizer: Aggregate Pushdown|Test aggregate pushdown before join|J,A,G||
optimizer_constant_folding|Optimizer: Constant Folding|Test constant folding at compile time|P||
optimizer_column_pruning|Optimizer: Column Pruning|Test column pruning at scan|J,F,P||
optimizer_union_optimization|Optimizer: Union Optimization|Test union optimization with multiple scans|S||
optimizer_runtime_filter|Optimizer: Runtime Filter|Test runtime filter / dynamic partition pruning|J,F||
optimizer_groupjoin|Optimizer: Group-Join Fusion|Test join+aggregate fusion into a single grouped-join pass|J,A,G||
qualify_row_number|QUALIFY ROW_NUMBER|Find top N orders per customer using ROW_NUMBER|J,W,F||
qualify_dense_rank|QUALIFY DENSE_RANK|Find top N parts by price per category using DENSE_RANK|W,F||
qualify_ntile|QUALIFY NTILE|Find orders in top quartile per segment using NTILE|J,W,F||
qualify_percentile|QUALIFY PERCENT_RANK|Find orders in top 10% per priority using PERCENT_RANK|W,F||
qualify_cume_dist|QUALIFY CUME_DIST|Find lineitems in top 5% quantity per shipdate using CUME_DIST|W,F||
qualify_lag_lead|QUALIFY LAG/LEAD|Find orders with increasing price using LAG|J,W,F||
struct_construction|Struct Construction|Construct struct from columns|P||
struct_access|Struct Field Access|Access struct fields by name|P,F||
array_contains|Array Contains|Check if array contains a specific value|A,G||
array_distinct|Array Distinct|Get distinct elements from array|A,G||
array_length|Array Length|Get array length/cardinality|A,G,S||
array_min_max|Array Min/Max|Get min and max from array|A,G||
array_of_struct|Array of Struct|Create array of structs from grouped data|A,G,J||
array_slice|Array Slice|Get slice/subset of array|A,G,F||
array_sort|Array Sort|Sort array elements|A,G||
array_unnest|Array Unnest|Unnest/explode array back to rows|A,G||
map_construction|Map Construction|Construct map from key-value pairs|A,G||
map_access|Map Access|Access map values by key|A,G,P||
map_keys_values|Map Keys/Values|Extract keys and values from map|A,G||
list_filter|List Filter|Filter array elements by condition|A,G||
list_transform|List Transform|Transform each array element|A,G||
list_reduce|List Reduce|Reduce array to single value|A,G||
json_extract_simple|JSON Extract Simple|Extract from JSON with simple path expressions|P,F||
json_extract_nested|JSON Extract Nested|Extract from JSON with complex path expressions|P,F||
json_aggregates|JSON Aggregates|Create JSON arrays and objects from aggregations|A,G,F||
timeseries_trend_analysis|Timeseries Trend Analysis|Time series aggregation with month-over-month analysis|A,G,W,S||
asof_join_basic|ASOF Join Basic|ASOF join to find closest prior order for shipments|J,F||
"""


def _impl_for(impl_base: str, family: str) -> Any:
    return globals()[f"{impl_base}_{family}_impl"]


def _make_query(row: list[str]) -> DataFrameQuery:
    query_id, query_name, description, category_codes, impl_base, sql_equivalent = row
    impl_base = impl_base or query_id
    return DataFrameQuery(
        query_id=query_id,
        query_name=query_name,
        description=description,
        categories=[_CATEGORY_CODES[code] for code in category_codes.split(",")],
        expression_impl=_impl_for(impl_base, "expression"),
        pandas_impl=_impl_for(impl_base, "pandas"),
        sql_equivalent=sql_equivalent or None,
    )


_QUERIES = [_make_query(row) for row in reader(_QUERY_METADATA.splitlines(), delimiter="|")]

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


def get_skip_for_polars() -> list[str]:
    """Get query IDs that should be skipped for Polars DataFrame mode.

    Polars lacks a native Map dtype, so map queries are skipped.

    Returns:
        List of query IDs to skip for Polars
    """
    return SKIP_FOR_POLARS.copy()


def get_skip_for_pyspark() -> list[str]:
    """Get query IDs that should be skipped for PySpark DataFrame mode.

    PySpark lacks native implementations for higher-order list functions
    that use the unified expression API's element() hook.

    Returns:
        List of query IDs to skip for PySpark
    """
    return SKIP_FOR_PYSPARK.copy()


def get_skip_for_datafusion() -> list[str]:
    """Get query IDs that should be skipped for DataFusion DataFrame mode.

    These use Polars-only features (.list.eval()) or DataFusion v50 functions
    that are missing from Python bindings (array_sum, array_distinct type bug).

    Returns:
        List of query IDs to skip for DataFusion
    """
    return SKIP_FOR_DATAFUSION.copy()
