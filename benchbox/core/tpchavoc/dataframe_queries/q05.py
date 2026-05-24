"""TPC-Havoc DataFrame variants for Q5.

Implements 10 structurally diverse variants of TPC-H Q5 (Local Supplier Volume).
Q5 is a 6-table join query: region→nation→customer→orders→lineitem→supplier.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q5_expression_impl as _q5_expr_base,
    q5_pandas_impl as _q5_pandas_base,
)
from benchbox.core.tpchavoc.dataframe_queries.loader import load_variant_specs

# ---------------------------------------------------------------------------
# v1: baseline
# ---------------------------------------------------------------------------


def q5_v1_expression_impl(ctx: DataFrameContext) -> Any:
    return _q5_expr_base(ctx)


def q5_v1_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q5_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v2: pre-filter - filter region and orders by date before joining
# ---------------------------------------------------------------------------


def q5_v2_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(5)
    region_name = params["region_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    filtered_region = region.filter(col("r_name") == lit(region_name))
    filtered_orders = orders.filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))

    return (
        filtered_region.join(nation, left_on="r_regionkey", right_on="n_regionkey")
        .join(customer, left_on="n_nationkey", right_on="c_nationkey")
        .join(filtered_orders, left_on="c_custkey", right_on="o_custkey")
        .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .join(supplier, left_on=["l_suppkey", "n_nationkey"], right_on=["s_suppkey", "s_nationkey"])
        .group_by("n_name")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .sort("revenue", descending=True)
    )


def q5_v2_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(5)
    region_name = params["region_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Pre-filter
    filtered_region = region[region["r_name"] == region_name]
    filtered_orders = orders[(orders["o_orderdate"] >= start_date) & (orders["o_orderdate"] < end_date)]

    region_nations = filtered_region.merge(nation, left_on="r_regionkey", right_on="n_regionkey")
    region_customers = region_nations.merge(customer, left_on="n_nationkey", right_on="c_nationkey")
    customer_orders = region_customers.merge(filtered_orders, left_on="c_custkey", right_on="o_custkey")
    order_lines = customer_orders.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    joined = order_lines.merge(supplier, left_on=["l_suppkey", "c_nationkey"], right_on=["s_suppkey", "s_nationkey"])

    joined = joined.copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])
    return (
        joined.groupby("n_name", as_index=False).agg(revenue=("revenue", "sum")).sort_values("revenue", ascending=False)
    )


# ---------------------------------------------------------------------------
# v3: column prune - select only needed columns from each table
# ---------------------------------------------------------------------------


def q5_v3_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(5)
    region_name = params["region_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    return (
        region.select("r_regionkey", "r_name")
        .filter(col("r_name") == lit(region_name))
        .join(nation.select("n_regionkey", "n_nationkey", "n_name"), left_on="r_regionkey", right_on="n_regionkey")
        .join(customer.select("c_nationkey", "c_custkey"), left_on="n_nationkey", right_on="c_nationkey")
        .join(
            orders.select("o_custkey", "o_orderkey", "o_orderdate").filter(
                (col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date))
            ),
            left_on="c_custkey",
            right_on="o_custkey",
        )
        .join(
            lineitem.select("l_orderkey", "l_suppkey", "l_extendedprice", "l_discount"),
            left_on="o_orderkey",
            right_on="l_orderkey",
        )
        .join(
            supplier.select("s_suppkey", "s_nationkey"),
            left_on=["l_suppkey", "n_nationkey"],
            right_on=["s_suppkey", "s_nationkey"],
        )
        .group_by("n_name")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .sort("revenue", descending=True)
    )


def q5_v3_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(5)
    region_name = params["region_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    r = region[["r_regionkey", "r_name"]]
    n = nation[["n_regionkey", "n_nationkey", "n_name"]]
    c = customer[["c_nationkey", "c_custkey"]]
    o = orders[["o_custkey", "o_orderkey", "o_orderdate"]]
    li = lineitem[["l_orderkey", "l_suppkey", "l_extendedprice", "l_discount"]]
    s = supplier[["s_suppkey", "s_nationkey"]]

    asia = r[r["r_name"] == region_name].merge(n, left_on="r_regionkey", right_on="n_regionkey")
    asia_c = asia.merge(c, left_on="n_nationkey", right_on="c_nationkey")
    o_filtered = o[(o["o_orderdate"] >= start_date) & (o["o_orderdate"] < end_date)]
    with_orders = asia_c.merge(o_filtered, left_on="c_custkey", right_on="o_custkey")
    with_lines = with_orders.merge(li, left_on="o_orderkey", right_on="l_orderkey")
    joined = with_lines.merge(s, left_on=["l_suppkey", "c_nationkey"], right_on=["s_suppkey", "s_nationkey"]).copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])
    return (
        joined.groupby("n_name", as_index=False).agg(revenue=("revenue", "sum")).sort_values("revenue", ascending=False)
    )


# ---------------------------------------------------------------------------
# v4: intermediate vars - one named DataFrame per join step
# ---------------------------------------------------------------------------


def q5_v4_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(5)
    region_name = params["region_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    step1 = region.filter(col("r_name") == lit(region_name))
    step2 = step1.join(nation, left_on="r_regionkey", right_on="n_regionkey")
    step3 = step2.join(customer, left_on="n_nationkey", right_on="c_nationkey")
    step4 = step3.join(orders, left_on="c_custkey", right_on="o_custkey")
    step5 = step4.filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))
    step6 = step5.join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    step7 = step6.join(supplier, left_on=["l_suppkey", "n_nationkey"], right_on=["s_suppkey", "s_nationkey"])
    aggregated = step7.group_by("n_name").agg(
        (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue")
    )
    return aggregated.sort("revenue", descending=True)


def q5_v4_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q5_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v5: pre-compute derived - add revenue column before groupby
# ---------------------------------------------------------------------------


def q5_v5_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(5)
    region_name = params["region_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    return (
        region.filter(col("r_name") == lit(region_name))
        .join(nation, left_on="r_regionkey", right_on="n_regionkey")
        .join(customer, left_on="n_nationkey", right_on="c_nationkey")
        .join(orders, left_on="c_custkey", right_on="o_custkey")
        .filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))
        .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .join(supplier, left_on=["l_suppkey", "n_nationkey"], right_on=["s_suppkey", "s_nationkey"])
        .with_columns((col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("revenue"))
        .group_by("n_name")
        .agg(col("revenue").sum().alias("revenue"))
        .sort("revenue", descending=True)
    )


def q5_v5_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(5)
    region_name = params["region_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    asia_region = region[region["r_name"] == region_name]
    asia_nations = asia_region.merge(nation, left_on="r_regionkey", right_on="n_regionkey")
    asia_customers = asia_nations.merge(customer, left_on="n_nationkey", right_on="c_nationkey")
    customer_orders = asia_customers.merge(orders, left_on="c_custkey", right_on="o_custkey")
    customer_orders = customer_orders[
        (customer_orders["o_orderdate"] >= start_date) & (customer_orders["o_orderdate"] < end_date)
    ]
    order_lines = customer_orders.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    joined = order_lines.merge(
        supplier, left_on=["l_suppkey", "c_nationkey"], right_on=["s_suppkey", "s_nationkey"]
    ).copy()
    # Pre-compute revenue
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])
    return (
        joined.groupby("n_name", as_index=False).agg(revenue=("revenue", "sum")).sort_values("revenue", ascending=False)
    )


# ---------------------------------------------------------------------------
# v6: chained style
# ---------------------------------------------------------------------------


def q5_v6_expression_impl(ctx: DataFrameContext) -> Any:
    col = ctx.col
    lit = ctx.lit
    p = get_tpch_parameters(5)
    return (
        ctx.get_table("region")
        .filter(col("r_name") == lit(p["region_name"]))
        .join(ctx.get_table("nation"), left_on="r_regionkey", right_on="n_regionkey")
        .join(ctx.get_table("customer"), left_on="n_nationkey", right_on="c_nationkey")
        .join(ctx.get_table("orders"), left_on="c_custkey", right_on="o_custkey")
        .filter((col("o_orderdate") >= lit(p["start_date"])) & (col("o_orderdate") < lit(p["end_date"])))
        .join(ctx.get_table("lineitem"), left_on="o_orderkey", right_on="l_orderkey")
        .join(ctx.get_table("supplier"), left_on=["l_suppkey", "n_nationkey"], right_on=["s_suppkey", "s_nationkey"])
        .group_by("n_name")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .sort("revenue", descending=True)
    )


def q5_v6_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q5_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v7: join reorder - start from supplier+nation instead of region
# ---------------------------------------------------------------------------


def q5_v7_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(5)
    region_name = params["region_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Start from nation→region to get Asia nations first
    asia_nations = nation.join(
        region.filter(col("r_name") == lit(region_name)),
        left_on="n_regionkey",
        right_on="r_regionkey",
    )
    asia_customers = customer.join(asia_nations, left_on="c_nationkey", right_on="n_nationkey")
    customer_orders = asia_customers.join(orders, left_on="c_custkey", right_on="o_custkey").filter(
        (col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date))
    )
    return (
        customer_orders.join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .join(supplier, left_on=["l_suppkey", "n_nationkey"], right_on=["s_suppkey", "s_nationkey"])
        .group_by("n_name")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .sort("revenue", descending=True)
    )


def q5_v7_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(5)
    region_name = params["region_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    asia_region = region[region["r_name"] == region_name]
    asia_nations = nation.merge(asia_region, left_on="n_regionkey", right_on="r_regionkey")
    asia_customers = customer.merge(asia_nations, left_on="c_nationkey", right_on="n_nationkey")
    customer_orders = asia_customers.merge(orders, left_on="c_custkey", right_on="o_custkey")
    customer_orders = customer_orders[
        (customer_orders["o_orderdate"] >= start_date) & (customer_orders["o_orderdate"] < end_date)
    ]
    order_lines = customer_orders.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    joined = order_lines.merge(
        supplier, left_on=["l_suppkey", "c_nationkey"], right_on=["s_suppkey", "s_nationkey"]
    ).copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])
    return (
        joined.groupby("n_name", as_index=False).agg(revenue=("revenue", "sum")).sort_values("revenue", ascending=False)
    )


# ---------------------------------------------------------------------------
# v8: filter combination - single combined date+region filter
# ---------------------------------------------------------------------------


def q5_v8_expression_impl(ctx: DataFrameContext) -> Any:
    return q5_v2_expression_impl(ctx)


def q5_v8_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(5)
    region_name = params["region_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    asia_region = region[region["r_name"] == region_name]
    asia_nations = asia_region.merge(nation, left_on="r_regionkey", right_on="n_regionkey")
    asia_customers = asia_nations.merge(customer, left_on="n_nationkey", right_on="c_nationkey")
    customer_orders = asia_customers.merge(orders, left_on="c_custkey", right_on="o_custkey")
    # Single combined filter
    date_mask = (customer_orders["o_orderdate"] >= start_date) & (customer_orders["o_orderdate"] < end_date)
    customer_orders = customer_orders[date_mask]
    order_lines = customer_orders.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    joined = order_lines.merge(
        supplier, left_on=["l_suppkey", "c_nationkey"], right_on=["s_suppkey", "s_nationkey"]
    ).copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])
    return (
        joined.groupby("n_name", as_index=False).agg(revenue=("revenue", "sum")).sort_values("revenue", ascending=False)
    )


# ---------------------------------------------------------------------------
# v9: explicit sort
# ---------------------------------------------------------------------------


def q5_v9_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(5)
    region_name = params["region_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    return (
        region.filter(col("r_name") == lit(region_name))
        .join(nation, left_on="r_regionkey", right_on="n_regionkey")
        .join(customer, left_on="n_nationkey", right_on="c_nationkey")
        .join(orders, left_on="c_custkey", right_on="o_custkey")
        .filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))
        .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .join(supplier, left_on=["l_suppkey", "n_nationkey"], right_on=["s_suppkey", "s_nationkey"])
        .group_by("n_name")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .sort("revenue", descending=True)
    )


def q5_v9_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(5)
    region_name = params["region_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    asia_region = region[region["r_name"] == region_name]
    asia_nations = asia_region.merge(nation, left_on="r_regionkey", right_on="n_regionkey")
    asia_customers = asia_nations.merge(customer, left_on="n_nationkey", right_on="c_nationkey")
    customer_orders = asia_customers.merge(orders, left_on="c_custkey", right_on="o_custkey")
    customer_orders = customer_orders[
        (customer_orders["o_orderdate"] >= start_date) & (customer_orders["o_orderdate"] < end_date)
    ]
    order_lines = customer_orders.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    joined = order_lines.merge(
        supplier, left_on=["l_suppkey", "c_nationkey"], right_on=["s_suppkey", "s_nationkey"]
    ).copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])
    return (
        joined.groupby("n_name", as_index=False).agg(revenue=("revenue", "sum")).sort_values("revenue", ascending=False)
    )


# ---------------------------------------------------------------------------
# v10: alternative formula - revenue = price - price*disc
# ---------------------------------------------------------------------------


def q5_v10_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(5)
    region_name = params["region_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    revenue_alt = col("l_extendedprice") - col("l_extendedprice") * col("l_discount")

    return (
        region.filter(col("r_name") == lit(region_name))
        .join(nation, left_on="r_regionkey", right_on="n_regionkey")
        .join(customer, left_on="n_nationkey", right_on="c_nationkey")
        .join(orders, left_on="c_custkey", right_on="o_custkey")
        .filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))
        .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .join(supplier, left_on=["l_suppkey", "n_nationkey"], right_on=["s_suppkey", "s_nationkey"])
        .group_by("n_name")
        .agg(revenue_alt.sum().alias("revenue"))
        .sort("revenue", descending=True)
    )


def q5_v10_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(5)
    region_name = params["region_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    asia_region = region[region["r_name"] == region_name]
    asia_nations = asia_region.merge(nation, left_on="r_regionkey", right_on="n_regionkey")
    asia_customers = asia_nations.merge(customer, left_on="n_nationkey", right_on="c_nationkey")
    customer_orders = asia_customers.merge(orders, left_on="c_custkey", right_on="o_custkey")
    customer_orders = customer_orders[
        (customer_orders["o_orderdate"] >= start_date) & (customer_orders["o_orderdate"] < end_date)
    ]
    order_lines = customer_orders.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    joined = order_lines.merge(
        supplier, left_on=["l_suppkey", "c_nationkey"], right_on=["s_suppkey", "s_nationkey"]
    ).copy()
    # Alternative formula
    joined["revenue"] = joined["l_extendedprice"] - joined["l_extendedprice"] * joined["l_discount"]
    return (
        joined.groupby("n_name", as_index=False).agg(revenue=("revenue", "sum")).sort_values("revenue", ascending=False)
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_IMPL_PAIRS, _DESCRIPTIONS = load_variant_specs(__file__, globals())

Q5_VARIANTS: list[DataFrameQuery] = [
    DataFrameQuery(
        query_id=f"Q5v{v}",
        query_name=f"TPC-H Q5 Variant {v}",
        description=_DESCRIPTIONS[v - 1],
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=expr_impl,
        pandas_impl=pandas_impl,
    )
    for v, (expr_impl, pandas_impl) in enumerate(_IMPL_PAIRS, start=1)
]
