"""TPC-Havoc DataFrame variants for Q3.

Implements 10 structurally diverse variants of TPC-H Q3 (Shipping Priority).
Q3 joins customer→orders→lineitem with date filters and returns top 10 by revenue.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q3_expression_impl as _q3_expr_base,
    q3_pandas_impl as _q3_pandas_base,
)

# ---------------------------------------------------------------------------
# v1: baseline
# ---------------------------------------------------------------------------


def q3_v1_expression_impl(ctx: DataFrameContext) -> Any:
    return _q3_expr_base(ctx)


def q3_v1_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q3_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v2: pre-filter - filter customer, orders, lineitem before joining
# ---------------------------------------------------------------------------


def q3_v2_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    # Pre-filter each table
    filtered_customer = customer.filter(col("c_mktsegment") == lit(segment))
    filtered_orders = orders.filter(col("o_orderdate") < lit(order_date))
    filtered_lineitem = lineitem.filter(col("l_shipdate") > lit(order_date))

    result = (
        filtered_customer.join(filtered_orders, left_on="c_custkey", right_on="o_custkey")
        .join(filtered_lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .group_by("o_orderkey", "o_orderdate", "o_shippriority")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .sort(["revenue", "o_orderdate"], descending=[True, False])
        .limit(10)
    )
    return result


def q3_v2_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    filtered_customer = customer[customer["c_mktsegment"] == segment]
    filtered_orders = orders[orders["o_orderdate"] < order_date]
    filtered_lineitem = lineitem[lineitem["l_shipdate"] > order_date].copy()

    joined = filtered_customer.merge(filtered_orders, left_on="c_custkey", right_on="o_custkey")
    joined = joined.merge(filtered_lineitem, left_on="o_orderkey", right_on="l_orderkey")
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])

    return (
        joined.groupby(["l_orderkey", "o_orderdate", "o_shippriority"], as_index=False)
        .agg(revenue=("revenue", "sum"))
        .sort_values(["revenue", "o_orderdate"], ascending=[False, True])
        .head(10)
    )


# ---------------------------------------------------------------------------
# v3: column prune - select only needed columns from each table
# ---------------------------------------------------------------------------


def q3_v3_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    result = (
        customer.select("c_custkey", "c_mktsegment")
        .filter(col("c_mktsegment") == lit(segment))
        .join(
            orders.select("o_custkey", "o_orderkey", "o_orderdate", "o_shippriority"),
            left_on="c_custkey",
            right_on="o_custkey",
        )
        .filter(col("o_orderdate") < lit(order_date))
        .join(
            lineitem.select("l_orderkey", "l_extendedprice", "l_discount", "l_shipdate"),
            left_on="o_orderkey",
            right_on="l_orderkey",
        )
        .filter(col("l_shipdate") > lit(order_date))
        .group_by("o_orderkey", "o_orderdate", "o_shippriority")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .sort(["revenue", "o_orderdate"], descending=[True, False])
        .limit(10)
    )
    return result


def q3_v3_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    cust_pruned = customer[["c_custkey", "c_mktsegment"]]
    orders_pruned = orders[["o_custkey", "o_orderkey", "o_orderdate", "o_shippriority"]]
    li_pruned = lineitem[["l_orderkey", "l_extendedprice", "l_discount", "l_shipdate"]]

    filtered_cust = cust_pruned[cust_pruned["c_mktsegment"] == segment]
    joined = filtered_cust.merge(orders_pruned, left_on="c_custkey", right_on="o_custkey")
    joined = joined[joined["o_orderdate"] < order_date]
    joined = joined.merge(li_pruned, left_on="o_orderkey", right_on="l_orderkey")
    joined = joined[joined["l_shipdate"] > order_date].copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])

    return (
        joined.groupby(["l_orderkey", "o_orderdate", "o_shippriority"], as_index=False)
        .agg(revenue=("revenue", "sum"))
        .sort_values(["revenue", "o_orderdate"], ascending=[False, True])
        .head(10)
    )


# ---------------------------------------------------------------------------
# v4: intermediate vars - explicit step-by-step named DataFrames
# ---------------------------------------------------------------------------


def q3_v4_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    # Step 1: filter customer
    building_customers = customer.filter(col("c_mktsegment") == lit(segment))
    # Step 2: join with orders and filter by date
    customer_orders = building_customers.join(orders, left_on="c_custkey", right_on="o_custkey")
    before_cutoff = customer_orders.filter(col("o_orderdate") < lit(order_date))
    # Step 3: join with lineitem and filter by shipdate
    with_lines = before_cutoff.join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    after_cutoff = with_lines.filter(col("l_shipdate") > lit(order_date))
    # Step 4: aggregate
    aggregated = after_cutoff.group_by("o_orderkey", "o_orderdate", "o_shippriority").agg(
        (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue")
    )
    # Step 5: sort and limit
    result = aggregated.sort(["revenue", "o_orderdate"], descending=[True, False]).limit(10)
    return result


def q3_v4_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    building_customers = customer[customer["c_mktsegment"] == segment]
    customer_orders = building_customers.merge(orders, left_on="c_custkey", right_on="o_custkey")
    before_cutoff = customer_orders[customer_orders["o_orderdate"] < order_date]
    with_lines = before_cutoff.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    after_cutoff = with_lines[with_lines["l_shipdate"] > order_date].copy()
    after_cutoff["revenue"] = after_cutoff["l_extendedprice"] * (1 - after_cutoff["l_discount"])
    aggregated = after_cutoff.groupby(["l_orderkey", "o_orderdate", "o_shippriority"], as_index=False).agg(
        revenue=("revenue", "sum")
    )
    return aggregated.sort_values(["revenue", "o_orderdate"], ascending=[False, True]).head(10)


# ---------------------------------------------------------------------------
# v5: pre-compute derived - add revenue column before groupby
# ---------------------------------------------------------------------------


def q3_v5_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    result = (
        customer.filter(col("c_mktsegment") == lit(segment))
        .join(orders, left_on="c_custkey", right_on="o_custkey")
        .filter(col("o_orderdate") < lit(order_date))
        .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .filter(col("l_shipdate") > lit(order_date))
        .with_columns((col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("revenue"))
        .group_by("o_orderkey", "o_orderdate", "o_shippriority")
        .agg(col("revenue").sum().alias("revenue"))
        .sort(["revenue", "o_orderdate"], descending=[True, False])
        .limit(10)
    )
    return result


def q3_v5_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    joined = customer[customer["c_mktsegment"] == segment].merge(orders, left_on="c_custkey", right_on="o_custkey")
    joined = joined[joined["o_orderdate"] < order_date].merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    joined = joined[joined["l_shipdate"] > order_date].copy()
    # Pre-compute
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])

    return (
        joined.groupby(["l_orderkey", "o_orderdate", "o_shippriority"], as_index=False)
        .agg(revenue=("revenue", "sum"))
        .sort_values(["revenue", "o_orderdate"], ascending=[False, True])
        .head(10)
    )


# ---------------------------------------------------------------------------
# v6: chained style
# ---------------------------------------------------------------------------


def q3_v6_expression_impl(ctx: DataFrameContext) -> Any:
    col = ctx.col
    lit = ctx.lit
    p = get_tpch_parameters(3)
    return (
        ctx.get_table("customer")
        .filter(col("c_mktsegment") == lit(p["segment"]))
        .join(ctx.get_table("orders"), left_on="c_custkey", right_on="o_custkey")
        .filter(col("o_orderdate") < lit(p["order_date"]))
        .join(ctx.get_table("lineitem"), left_on="o_orderkey", right_on="l_orderkey")
        .filter(col("l_shipdate") > lit(p["order_date"]))
        .group_by("o_orderkey", "o_orderdate", "o_shippriority")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .sort(["revenue", "o_orderdate"], descending=[True, False])
        .limit(10)
    )


def q3_v6_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q3_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v7: join reorder - join orders→lineitem first, then filter and join customer
# ---------------------------------------------------------------------------


def q3_v7_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    # Start from orders→lineitem (swapped from customer→orders→lineitem)
    orders_lineitem = orders.filter(col("o_orderdate") < lit(order_date)).join(
        lineitem.filter(col("l_shipdate") > lit(order_date)), left_on="o_orderkey", right_on="l_orderkey"
    )
    result = (
        customer.filter(col("c_mktsegment") == lit(segment))
        .join(orders_lineitem, left_on="c_custkey", right_on="o_custkey")
        .group_by("o_orderkey", "o_orderdate", "o_shippriority")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .sort(["revenue", "o_orderdate"], descending=[True, False])
        .limit(10)
    )
    return result


def q3_v7_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    # Start from orders→lineitem
    filtered_orders = orders[orders["o_orderdate"] < order_date]
    filtered_lineitem = lineitem[lineitem["l_shipdate"] > order_date]
    orders_lineitem = filtered_orders.merge(filtered_lineitem, left_on="o_orderkey", right_on="l_orderkey")

    # Join customer
    filtered_customer = customer[customer["c_mktsegment"] == segment]
    joined = filtered_customer.merge(orders_lineitem, left_on="c_custkey", right_on="o_custkey").copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])

    return (
        joined.groupby(["l_orderkey", "o_orderdate", "o_shippriority"], as_index=False)
        .agg(revenue=("revenue", "sum"))
        .sort_values(["revenue", "o_orderdate"], ascending=[False, True])
        .head(10)
    )


# ---------------------------------------------------------------------------
# v8: filter combination - combine order_date and shipdate predicates
# ---------------------------------------------------------------------------


def q3_v8_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    result = (
        customer.filter(col("c_mktsegment") == lit(segment))
        .join(orders, left_on="c_custkey", right_on="o_custkey")
        .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        # Combine both date filters in single filter call after all joins
        .filter((col("o_orderdate") < lit(order_date)) & (col("l_shipdate") > lit(order_date)))
        .group_by("o_orderkey", "o_orderdate", "o_shippriority")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .sort(["revenue", "o_orderdate"], descending=[True, False])
        .limit(10)
    )
    return result


def q3_v8_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    filtered_customer = customer[customer["c_mktsegment"] == segment]
    joined = filtered_customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    joined = joined.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    # Combined filter after all joins
    joined = joined[(joined["o_orderdate"] < order_date) & (joined["l_shipdate"] > order_date)].copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])

    return (
        joined.groupby(["l_orderkey", "o_orderdate", "o_shippriority"], as_index=False)
        .agg(revenue=("revenue", "sum"))
        .sort_values(["revenue", "o_orderdate"], ascending=[False, True])
        .head(10)
    )


# ---------------------------------------------------------------------------
# v9: explicit sort - use descending=[True, False] with ascending equivalents
# ---------------------------------------------------------------------------


def q3_v9_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    result = (
        customer.filter(col("c_mktsegment") == lit(segment))
        .join(orders, left_on="c_custkey", right_on="o_custkey")
        .filter(col("o_orderdate") < lit(order_date))
        .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .filter(col("l_shipdate") > lit(order_date))
        .group_by("o_orderkey", "o_orderdate", "o_shippriority")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .sort(["revenue", "o_orderdate"], descending=[True, False])
        .limit(10)
    )
    return result


def q3_v9_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    filtered_customer = customer[customer["c_mktsegment"] == segment]
    joined = filtered_customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    joined = joined[joined["o_orderdate"] < order_date]
    joined = joined.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    joined = joined[joined["l_shipdate"] > order_date].copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])

    return (
        joined.groupby(["l_orderkey", "o_orderdate", "o_shippriority"], as_index=False)
        .agg(revenue=("revenue", "sum"))
        .sort_values(["revenue", "o_orderdate"], ascending=[False, True])
        .head(10)
    )


# ---------------------------------------------------------------------------
# v10: alternative formula - revenue as price - price*disc
# ---------------------------------------------------------------------------


def q3_v10_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    revenue_alt = col("l_extendedprice") - col("l_extendedprice") * col("l_discount")

    result = (
        customer.filter(col("c_mktsegment") == lit(segment))
        .join(orders, left_on="c_custkey", right_on="o_custkey")
        .filter(col("o_orderdate") < lit(order_date))
        .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .filter(col("l_shipdate") > lit(order_date))
        .group_by("o_orderkey", "o_orderdate", "o_shippriority")
        .agg(revenue_alt.sum().alias("revenue"))
        .sort(["revenue", "o_orderdate"], descending=[True, False])
        .limit(10)
    )
    return result


def q3_v10_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    filtered_customer = customer[customer["c_mktsegment"] == segment]
    joined = filtered_customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    joined = joined[joined["o_orderdate"] < order_date]
    joined = joined.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    joined = joined[joined["l_shipdate"] > order_date].copy()
    # Alternative formula: price - price*disc
    joined["revenue"] = joined["l_extendedprice"] - joined["l_extendedprice"] * joined["l_discount"]

    return (
        joined.groupby(["l_orderkey", "o_orderdate", "o_shippriority"], as_index=False)
        .agg(revenue=("revenue", "sum"))
        .sort_values(["revenue", "o_orderdate"], ascending=[False, True])
        .head(10)
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_IMPL_PAIRS = [
    (q3_v1_expression_impl, q3_v1_pandas_impl),
    (q3_v2_expression_impl, q3_v2_pandas_impl),
    (q3_v3_expression_impl, q3_v3_pandas_impl),
    (q3_v4_expression_impl, q3_v4_pandas_impl),
    (q3_v5_expression_impl, q3_v5_pandas_impl),
    (q3_v6_expression_impl, q3_v6_pandas_impl),
    (q3_v7_expression_impl, q3_v7_pandas_impl),
    (q3_v8_expression_impl, q3_v8_pandas_impl),
    (q3_v9_expression_impl, q3_v9_pandas_impl),
    (q3_v10_expression_impl, q3_v10_pandas_impl),
]

_DESCRIPTIONS = [
    "Baseline: direct delegation to TPC-H Q3 implementation",
    "Pre-filter: filter customer, orders, lineitem before joining",
    "Column prune: select only needed columns from each table",
    "Intermediate vars: named DataFrames for each join and filter step",
    "Pre-compute derived: add revenue column before groupby",
    "Chained style: maximum method chaining, no named intermediates",
    "Join reorder: start from orders→lineitem, then join customer",
    "Filter combination: combine order_date and shipdate predicates after all joins",
    "Explicit sort: descending=[True, False] explicitly specified",
    "Alternative formula: price - price*disc instead of price*(1-disc)",
]

Q3_VARIANTS: list[DataFrameQuery] = [
    DataFrameQuery(
        query_id=f"Q3v{v}",
        query_name=f"TPC-H Q3 Variant {v}",
        description=_DESCRIPTIONS[v - 1],
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.SORT],
        expression_impl=expr_impl,
        pandas_impl=pandas_impl,
    )
    for v, (expr_impl, pandas_impl) in enumerate(_IMPL_PAIRS, start=1)
]
