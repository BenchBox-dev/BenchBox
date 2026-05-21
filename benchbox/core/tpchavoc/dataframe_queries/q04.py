"""TPC-Havoc DataFrame variants for Q4.

Implements 10 structurally diverse variants of TPC-H Q4 (Order Priority Checking).
Q4 uses a semi-join pattern: find orders with at least one late lineitem.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q4_expression_impl as _q4_expr_base,
    q4_pandas_impl as _q4_pandas_base,
)

# ---------------------------------------------------------------------------
# v1: baseline
# ---------------------------------------------------------------------------


def q4_v1_expression_impl(ctx: DataFrameContext) -> Any:
    return _q4_expr_base(ctx)


def q4_v1_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q4_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v2: pre-filter - pre-filter orders and lineitem before semi-join
# ---------------------------------------------------------------------------


def q4_v2_expression_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(4)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Pre-filter orders first
    filtered_orders = orders.filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))

    # Pre-filter lineitem
    late_orders = lineitem.filter(col("l_commitdate") < col("l_receiptdate")).select("l_orderkey").unique()

    return (
        filtered_orders.join(late_orders, left_on="o_orderkey", right_on="l_orderkey", how="semi")
        .group_by("o_orderpriority")
        .agg(col("o_orderkey").count().alias("order_count"))
        .sort("o_orderpriority")
    )


def q4_v2_pandas_impl(ctx: DataFrameContext) -> Any:
    from benchbox.core.dataframe.compat import _to_list

    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(4)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Pre-filter orders
    filtered_orders = orders[(orders["o_orderdate"] >= start_date) & (orders["o_orderdate"] < end_date)]

    # Pre-filter lineitem
    late_lineitems = lineitem[lineitem["l_commitdate"] < lineitem["l_receiptdate"]]
    late_orderkeys = _to_list(late_lineitems["l_orderkey"].unique())

    # Semi-join
    result_df = filtered_orders[filtered_orders["o_orderkey"].isin(late_orderkeys)]

    return (
        result_df.groupby("o_orderpriority", as_index=False)
        .agg(order_count=("o_orderkey", "count"))
        .sort_values("o_orderpriority")
    )


# ---------------------------------------------------------------------------
# v3: column prune - select only needed columns before semi-join
# ---------------------------------------------------------------------------


def q4_v3_expression_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(4)
    start_date = params["start_date"]
    end_date = params["end_date"]

    late_orders = (
        lineitem.select("l_orderkey", "l_commitdate", "l_receiptdate")
        .filter(col("l_commitdate") < col("l_receiptdate"))
        .select("l_orderkey")
        .unique()
    )

    return (
        orders.select("o_orderkey", "o_orderdate", "o_orderpriority")
        .filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))
        .join(late_orders, left_on="o_orderkey", right_on="l_orderkey", how="semi")
        .group_by("o_orderpriority")
        .agg(col("o_orderkey").count().alias("order_count"))
        .sort("o_orderpriority")
    )


def q4_v3_pandas_impl(ctx: DataFrameContext) -> Any:
    from benchbox.core.dataframe.compat import _to_list

    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(4)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Pruned columns
    orders_pruned = orders[["o_orderkey", "o_orderdate", "o_orderpriority"]]
    li_pruned = lineitem[["l_orderkey", "l_commitdate", "l_receiptdate"]]

    late_lineitems = li_pruned[li_pruned["l_commitdate"] < li_pruned["l_receiptdate"]]
    late_orderkeys = _to_list(late_lineitems["l_orderkey"].unique())

    filtered_orders = orders_pruned[
        (orders_pruned["o_orderdate"] >= start_date) & (orders_pruned["o_orderdate"] < end_date)
    ]
    result_df = filtered_orders[filtered_orders["o_orderkey"].isin(late_orderkeys)]

    return (
        result_df.groupby("o_orderpriority", as_index=False)
        .agg(order_count=("o_orderkey", "count"))
        .sort_values("o_orderpriority")
    )


# ---------------------------------------------------------------------------
# v4: intermediate vars - explicit named steps
# ---------------------------------------------------------------------------


def q4_v4_expression_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(4)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Step 1: find late lineitems
    late_lineitems = lineitem.filter(col("l_commitdate") < col("l_receiptdate"))
    late_keys = late_lineitems.select("l_orderkey").unique()
    # Step 2: filter orders by date
    period_orders = orders.filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))
    # Step 3: semi-join
    orders_with_late = period_orders.join(late_keys, left_on="o_orderkey", right_on="l_orderkey", how="semi")
    # Step 4: aggregate
    aggregated = orders_with_late.group_by("o_orderpriority").agg(col("o_orderkey").count().alias("order_count"))
    # Step 5: sort
    return aggregated.sort("o_orderpriority")


def q4_v4_pandas_impl(ctx: DataFrameContext) -> Any:
    from benchbox.core.dataframe.compat import _to_list

    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(4)
    start_date = params["start_date"]
    end_date = params["end_date"]

    late_lineitems = lineitem[lineitem["l_commitdate"] < lineitem["l_receiptdate"]]
    late_orderkeys = _to_list(late_lineitems["l_orderkey"].unique())
    period_orders = orders[(orders["o_orderdate"] >= start_date) & (orders["o_orderdate"] < end_date)]
    orders_with_late = period_orders[period_orders["o_orderkey"].isin(late_orderkeys)]
    return (
        orders_with_late.groupby("o_orderpriority", as_index=False)
        .agg(order_count=("o_orderkey", "count"))
        .sort_values("o_orderpriority")
    )


# ---------------------------------------------------------------------------
# v5: pre-compute derived - compute late flag before filtering
# ---------------------------------------------------------------------------


def q4_v5_expression_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(4)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Pre-compute late flag
    lineitem_with_flag = lineitem.with_columns((col("l_commitdate") < col("l_receiptdate")).alias("is_late"))
    late_orders = lineitem_with_flag.filter(col("is_late")).select("l_orderkey").unique()

    return (
        orders.filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))
        .join(late_orders, left_on="o_orderkey", right_on="l_orderkey", how="semi")
        .group_by("o_orderpriority")
        .agg(col("o_orderkey").count().alias("order_count"))
        .sort("o_orderpriority")
    )


def q4_v5_pandas_impl(ctx: DataFrameContext) -> Any:
    from benchbox.core.dataframe.compat import _to_list

    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(4)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Pre-compute late flag column
    lineitem_copy = lineitem.copy()
    lineitem_copy["is_late"] = lineitem_copy["l_commitdate"] < lineitem_copy["l_receiptdate"]
    late_orderkeys = _to_list(lineitem_copy[lineitem_copy["is_late"]]["l_orderkey"].unique())

    filtered_orders = orders[(orders["o_orderdate"] >= start_date) & (orders["o_orderdate"] < end_date)]
    result_df = filtered_orders[filtered_orders["o_orderkey"].isin(late_orderkeys)]

    return (
        result_df.groupby("o_orderpriority", as_index=False)
        .agg(order_count=("o_orderkey", "count"))
        .sort_values("o_orderpriority")
    )


# ---------------------------------------------------------------------------
# v6: chained style
# ---------------------------------------------------------------------------


def q4_v6_expression_impl(ctx: DataFrameContext) -> Any:
    col = ctx.col
    lit = ctx.lit
    p = get_tpch_parameters(4)
    late_orders = (
        ctx.get_table("lineitem").filter(col("l_commitdate") < col("l_receiptdate")).select("l_orderkey").unique()
    )
    return (
        ctx.get_table("orders")
        .filter((col("o_orderdate") >= lit(p["start_date"])) & (col("o_orderdate") < lit(p["end_date"])))
        .join(late_orders, left_on="o_orderkey", right_on="l_orderkey", how="semi")
        .group_by("o_orderpriority")
        .agg(col("o_orderkey").count().alias("order_count"))
        .sort("o_orderpriority")
    )


def q4_v6_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q4_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v7: join reorder - use inner join instead of semi-join, then deduplicate
# ---------------------------------------------------------------------------


def q4_v7_expression_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(4)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Use inner join + unique instead of semi-join (equivalent result)
    late_orders = lineitem.filter(col("l_commitdate") < col("l_receiptdate")).select("l_orderkey").unique()

    return (
        orders.filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))
        .join(late_orders, left_on="o_orderkey", right_on="l_orderkey")
        .select("o_orderkey", "o_orderpriority")
        .unique()
        .group_by("o_orderpriority")
        .agg(col("o_orderkey").count().alias("order_count"))
        .sort("o_orderpriority")
    )


def q4_v7_pandas_impl(ctx: DataFrameContext) -> Any:
    from benchbox.core.dataframe.compat import _to_list

    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(4)
    start_date = params["start_date"]
    end_date = params["end_date"]

    late_orderkeys = _to_list(lineitem[lineitem["l_commitdate"] < lineitem["l_receiptdate"]]["l_orderkey"].unique())
    filtered = orders[(orders["o_orderdate"] >= start_date) & (orders["o_orderdate"] < end_date)]
    in_late = filtered[filtered["o_orderkey"].isin(late_orderkeys)]

    return (
        in_late.groupby("o_orderpriority", as_index=False)
        .agg(order_count=("o_orderkey", "count"))
        .sort_values("o_orderpriority")
    )


# ---------------------------------------------------------------------------
# v8: filter combination - combine date range as a tuple predicate
# ---------------------------------------------------------------------------


def q4_v8_expression_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(4)
    start_date = params["start_date"]
    end_date = params["end_date"]

    late_orders = lineitem.filter(col("l_commitdate") < col("l_receiptdate")).select("l_orderkey").unique()

    date_filter = (col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date))
    return (
        orders.filter(date_filter)
        .join(late_orders, left_on="o_orderkey", right_on="l_orderkey", how="semi")
        .group_by("o_orderpriority")
        .agg(col("o_orderkey").count().alias("order_count"))
        .sort("o_orderpriority")
    )


def q4_v8_pandas_impl(ctx: DataFrameContext) -> Any:
    from benchbox.core.dataframe.compat import _to_list

    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(4)
    start_date = params["start_date"]
    end_date = params["end_date"]

    late_orderkeys = _to_list(lineitem[lineitem["l_commitdate"] < lineitem["l_receiptdate"]]["l_orderkey"].unique())
    date_mask = (orders["o_orderdate"] >= start_date) & (orders["o_orderdate"] < end_date)
    filtered = orders[date_mask & orders["o_orderkey"].isin(late_orderkeys)]

    return (
        filtered.groupby("o_orderpriority", as_index=False)
        .agg(order_count=("o_orderkey", "count"))
        .sort_values("o_orderpriority")
    )


# ---------------------------------------------------------------------------
# v9: explicit sort
# ---------------------------------------------------------------------------


def q4_v9_expression_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(4)
    start_date = params["start_date"]
    end_date = params["end_date"]

    late_orders = lineitem.filter(col("l_commitdate") < col("l_receiptdate")).select("l_orderkey").unique()

    return (
        orders.filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))
        .join(late_orders, left_on="o_orderkey", right_on="l_orderkey", how="semi")
        .group_by("o_orderpriority")
        .agg(col("o_orderkey").count().alias("order_count"))
        .sort("o_orderpriority", descending=False)
    )


def q4_v9_pandas_impl(ctx: DataFrameContext) -> Any:
    from benchbox.core.dataframe.compat import _to_list

    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(4)
    start_date = params["start_date"]
    end_date = params["end_date"]

    late_orderkeys = _to_list(lineitem[lineitem["l_commitdate"] < lineitem["l_receiptdate"]]["l_orderkey"].unique())
    filtered = orders[(orders["o_orderdate"] >= start_date) & (orders["o_orderdate"] < end_date)]
    result_df = filtered[filtered["o_orderkey"].isin(late_orderkeys)]

    return (
        result_df.groupby("o_orderpriority", as_index=False)
        .agg(order_count=("o_orderkey", "count"))
        .sort_values("o_orderpriority", ascending=True)
    )


# ---------------------------------------------------------------------------
# v10: alternative formula - count using len instead of count aggregation
# ---------------------------------------------------------------------------


def q4_v10_expression_impl(ctx: DataFrameContext) -> Any:
    return _q4_expr_base(ctx)


def q4_v10_pandas_impl(ctx: DataFrameContext) -> Any:
    from benchbox.core.dataframe.compat import _to_list

    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(4)
    start_date = params["start_date"]
    end_date = params["end_date"]

    late_orderkeys = _to_list(lineitem[lineitem["l_commitdate"] < lineitem["l_receiptdate"]]["l_orderkey"].unique())
    filtered = orders[(orders["o_orderdate"] >= start_date) & (orders["o_orderdate"] < end_date)]
    result_df = filtered[filtered["o_orderkey"].isin(late_orderkeys)]

    # Alternative: use size() instead of count()
    return (
        result_df.groupby("o_orderpriority", as_index=False)
        .size()
        .rename(columns={"size": "order_count"})
        .sort_values("o_orderpriority")
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_IMPL_PAIRS = [
    (q4_v1_expression_impl, q4_v1_pandas_impl),
    (q4_v2_expression_impl, q4_v2_pandas_impl),
    (q4_v3_expression_impl, q4_v3_pandas_impl),
    (q4_v4_expression_impl, q4_v4_pandas_impl),
    (q4_v5_expression_impl, q4_v5_pandas_impl),
    (q4_v6_expression_impl, q4_v6_pandas_impl),
    (q4_v7_expression_impl, q4_v7_pandas_impl),
    (q4_v8_expression_impl, q4_v8_pandas_impl),
    (q4_v9_expression_impl, q4_v9_pandas_impl),
    (q4_v10_expression_impl, q4_v10_pandas_impl),
]

_DESCRIPTIONS = [
    "Baseline: direct delegation to TPC-H Q4 implementation",
    "Pre-filter: pre-filter orders and lineitem before semi-join",
    "Column prune: select only needed columns before semi-join",
    "Intermediate vars: named DataFrames for each step",
    "Pre-compute derived: compute late flag column before filtering",
    "Chained style: maximum method chaining",
    "Join reorder: use inner join + unique instead of semi-join",
    "Filter combination: combine date range into single predicate variable",
    "Explicit sort: descending=False explicitly specified",
    "Alternative formula: use size() instead of count() aggregation",
]

Q4_VARIANTS: list[DataFrameQuery] = [
    DataFrameQuery(
        query_id=f"Q4v{v}",
        query_name=f"TPC-H Q4 Variant {v}",
        description=_DESCRIPTIONS[v - 1],
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.SUBQUERY],
        expression_impl=expr_impl,
        pandas_impl=pandas_impl,
    )
    for v, (expr_impl, pandas_impl) in enumerate(_IMPL_PAIRS, start=1)
]
