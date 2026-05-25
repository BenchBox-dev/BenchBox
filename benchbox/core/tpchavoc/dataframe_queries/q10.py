"""TPC-Havoc DataFrame variants for Q10.

Implements 10 structurally diverse variants of TPC-H Q10 (Returned Item Reporting).
Q10 is a 4-table join finding customers with returned parts and their revenue impact.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q10_expression_impl as _q10_expr_base,
    q10_pandas_impl as _q10_pandas_base,
)
from benchbox.core.tpchavoc.dataframe_queries.loader import JOIN_AGG_SORT, build_yaml_variants

# ---------------------------------------------------------------------------
# v1: baseline
# ---------------------------------------------------------------------------


def q10_v1_expression_impl(ctx: DataFrameContext) -> Any:
    return _q10_expr_base(ctx)


def q10_v1_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q10_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v2: pre-filter - filter orders and lineitem before joining
# ---------------------------------------------------------------------------


def q10_v2_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(10)
    start_date = params["start_date"]
    end_date = params["end_date"]

    filtered_orders = orders.filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))
    filtered_lineitem = lineitem.filter(col("l_returnflag") == lit("R"))

    return (
        customer.join(filtered_orders, left_on="c_custkey", right_on="o_custkey")
        .join(filtered_lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .join(nation, left_on="c_nationkey", right_on="n_nationkey")
        .group_by("c_custkey", "c_name", "c_acctbal", "c_phone", "n_name", "c_address", "c_comment")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .sort("revenue", descending=True)
        .limit(20)
    )


def q10_v2_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(10)
    start_date = params["start_date"]
    end_date = params["end_date"]

    filtered_orders = orders[(orders["o_orderdate"] >= start_date) & (orders["o_orderdate"] < end_date)]
    filtered_li = lineitem[lineitem["l_returnflag"] == "R"]

    joined = customer.merge(filtered_orders, left_on="c_custkey", right_on="o_custkey")
    joined = joined.merge(filtered_li, left_on="o_orderkey", right_on="l_orderkey")
    joined = joined.merge(nation, left_on="c_nationkey", right_on="n_nationkey").copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])

    return (
        joined.groupby(
            ["c_custkey", "c_name", "c_acctbal", "c_phone", "n_name", "c_address", "c_comment"], as_index=False
        )
        .agg(revenue=("revenue", "sum"))
        .sort_values("revenue", ascending=False)
        .head(20)
    )


# ---------------------------------------------------------------------------
# v3: column prune
# ---------------------------------------------------------------------------


def q10_v3_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(10)
    start_date = params["start_date"]
    end_date = params["end_date"]

    return (
        customer.select("c_custkey", "c_name", "c_acctbal", "c_phone", "c_address", "c_comment", "c_nationkey")
        .join(
            orders.select("o_custkey", "o_orderkey", "o_orderdate").filter(
                (col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date))
            ),
            left_on="c_custkey",
            right_on="o_custkey",
        )
        .join(
            lineitem.select("l_orderkey", "l_extendedprice", "l_discount", "l_returnflag").filter(
                col("l_returnflag") == lit("R")
            ),
            left_on="o_orderkey",
            right_on="l_orderkey",
        )
        .join(nation.select("n_nationkey", "n_name"), left_on="c_nationkey", right_on="n_nationkey")
        .group_by("c_custkey", "c_name", "c_acctbal", "c_phone", "n_name", "c_address", "c_comment")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .sort("revenue", descending=True)
        .limit(20)
    )


def q10_v3_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q10_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v4: intermediate vars
# ---------------------------------------------------------------------------


def q10_v4_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(10)
    start_date = params["start_date"]
    end_date = params["end_date"]

    step1 = customer.join(orders, left_on="c_custkey", right_on="o_custkey")
    step2 = step1.filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))
    step3 = step2.join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    step4 = step3.filter(col("l_returnflag") == lit("R"))
    step5 = step4.join(nation, left_on="c_nationkey", right_on="n_nationkey")
    step6 = step5.group_by("c_custkey", "c_name", "c_acctbal", "c_phone", "n_name", "c_address", "c_comment").agg(
        (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue")
    )
    return step6.sort("revenue", descending=True).limit(20)


def q10_v4_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(10)
    start_date = params["start_date"]
    end_date = params["end_date"]

    step1 = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    step2 = step1[(step1["o_orderdate"] >= start_date) & (step1["o_orderdate"] < end_date)]
    step3 = step2.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    step4 = step3[step3["l_returnflag"] == "R"]
    step5 = step4.merge(nation, left_on="c_nationkey", right_on="n_nationkey").copy()
    step5["revenue"] = step5["l_extendedprice"] * (1 - step5["l_discount"])

    return (
        step5.groupby(
            ["c_custkey", "c_name", "c_acctbal", "c_phone", "n_name", "c_address", "c_comment"], as_index=False
        )
        .agg(revenue=("revenue", "sum"))
        .sort_values("revenue", ascending=False)
        .head(20)
    )


# ---------------------------------------------------------------------------
# v5: pre-compute derived - add revenue column before groupby
# ---------------------------------------------------------------------------


def q10_v5_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(10)
    start_date = params["start_date"]
    end_date = params["end_date"]

    return (
        customer.join(orders, left_on="c_custkey", right_on="o_custkey")
        .filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))
        .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .filter(col("l_returnflag") == lit("R"))
        .join(nation, left_on="c_nationkey", right_on="n_nationkey")
        .with_columns((col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("revenue"))
        .group_by("c_custkey", "c_name", "c_acctbal", "c_phone", "n_name", "c_address", "c_comment")
        .agg(col("revenue").sum().alias("revenue"))
        .sort("revenue", descending=True)
        .limit(20)
    )


def q10_v5_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(10)
    start_date = params["start_date"]
    end_date = params["end_date"]

    joined = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    joined = joined[(joined["o_orderdate"] >= start_date) & (joined["o_orderdate"] < end_date)]
    joined = joined.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    joined = joined[joined["l_returnflag"] == "R"]
    joined = joined.merge(nation, left_on="c_nationkey", right_on="n_nationkey").copy()
    # Pre-compute revenue
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])

    return (
        joined.groupby(
            ["c_custkey", "c_name", "c_acctbal", "c_phone", "n_name", "c_address", "c_comment"], as_index=False
        )
        .agg(revenue=("revenue", "sum"))
        .sort_values("revenue", ascending=False)
        .head(20)
    )


# ---------------------------------------------------------------------------
# v6: chained style
# ---------------------------------------------------------------------------


def q10_v6_expression_impl(ctx: DataFrameContext) -> Any:
    col = ctx.col
    lit = ctx.lit
    p = get_tpch_parameters(10)
    return (
        ctx.get_table("customer")
        .join(ctx.get_table("orders"), left_on="c_custkey", right_on="o_custkey")
        .filter((col("o_orderdate") >= lit(p["start_date"])) & (col("o_orderdate") < lit(p["end_date"])))
        .join(ctx.get_table("lineitem"), left_on="o_orderkey", right_on="l_orderkey")
        .filter(col("l_returnflag") == lit("R"))
        .join(ctx.get_table("nation"), left_on="c_nationkey", right_on="n_nationkey")
        .group_by("c_custkey", "c_name", "c_acctbal", "c_phone", "n_name", "c_address", "c_comment")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .sort("revenue", descending=True)
        .limit(20)
    )


def q10_v6_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q10_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v7: join reorder - join orders before customer
# ---------------------------------------------------------------------------


def q10_v7_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(10)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Swapped: start from orders→customer
    return (
        orders.filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))
        .join(customer, left_on="o_custkey", right_on="c_custkey")
        .join(lineitem.filter(col("l_returnflag") == lit("R")), left_on="o_orderkey", right_on="l_orderkey")
        .join(nation, left_on="c_nationkey", right_on="n_nationkey")
        .group_by("c_custkey", "c_name", "c_acctbal", "c_phone", "n_name", "c_address", "c_comment")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .sort("revenue", descending=True)
        .limit(20)
    )


def q10_v7_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(10)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Start from orders
    filtered_orders = orders[(orders["o_orderdate"] >= start_date) & (orders["o_orderdate"] < end_date)]
    joined = filtered_orders.merge(customer, left_on="o_custkey", right_on="c_custkey")
    filtered_li = lineitem[lineitem["l_returnflag"] == "R"]
    joined = joined.merge(filtered_li, left_on="o_orderkey", right_on="l_orderkey")
    joined = joined.merge(nation, left_on="c_nationkey", right_on="n_nationkey").copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])

    return (
        joined.groupby(
            ["c_custkey", "c_name", "c_acctbal", "c_phone", "n_name", "c_address", "c_comment"], as_index=False
        )
        .agg(revenue=("revenue", "sum"))
        .sort_values("revenue", ascending=False)
        .head(20)
    )


# ---------------------------------------------------------------------------
# v8: filter combination - combine date and returnflag filters
# ---------------------------------------------------------------------------


def q10_v8_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(10)
    start_date = params["start_date"]
    end_date = params["end_date"]

    return (
        customer.join(orders, left_on="c_custkey", right_on="o_custkey")
        .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        # Combine both filters in single call after all joins
        .filter(
            (col("o_orderdate") >= lit(start_date))
            & (col("o_orderdate") < lit(end_date))
            & (col("l_returnflag") == lit("R"))
        )
        .join(nation, left_on="c_nationkey", right_on="n_nationkey")
        .group_by("c_custkey", "c_name", "c_acctbal", "c_phone", "n_name", "c_address", "c_comment")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .sort("revenue", descending=True)
        .limit(20)
    )


def q10_v8_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(10)
    start_date = params["start_date"]
    end_date = params["end_date"]

    joined = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    joined = joined.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    # Combined filter
    joined = joined[
        (joined["o_orderdate"] >= start_date) & (joined["o_orderdate"] < end_date) & (joined["l_returnflag"] == "R")
    ]
    joined = joined.merge(nation, left_on="c_nationkey", right_on="n_nationkey").copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])

    return (
        joined.groupby(
            ["c_custkey", "c_name", "c_acctbal", "c_phone", "n_name", "c_address", "c_comment"], as_index=False
        )
        .agg(revenue=("revenue", "sum"))
        .sort_values("revenue", ascending=False)
        .head(20)
    )


# ---------------------------------------------------------------------------
# v9: explicit sort
# ---------------------------------------------------------------------------


def q10_v9_expression_impl(ctx: DataFrameContext) -> Any:
    return _q10_expr_base(ctx)


def q10_v9_pandas_impl(ctx: DataFrameContext) -> Any:
    return q10_v5_pandas_impl(ctx)


# ---------------------------------------------------------------------------
# v10: alternative formula - revenue = price - price*disc
# ---------------------------------------------------------------------------


def q10_v10_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(10)
    start_date = params["start_date"]
    end_date = params["end_date"]

    revenue_alt = col("l_extendedprice") - col("l_extendedprice") * col("l_discount")

    return (
        customer.join(orders, left_on="c_custkey", right_on="o_custkey")
        .filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))
        .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .filter(col("l_returnflag") == lit("R"))
        .join(nation, left_on="c_nationkey", right_on="n_nationkey")
        .group_by("c_custkey", "c_name", "c_acctbal", "c_phone", "n_name", "c_address", "c_comment")
        .agg(revenue_alt.sum().alias("revenue"))
        .sort("revenue", descending=True)
        .limit(20)
    )


def q10_v10_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(10)
    start_date = params["start_date"]
    end_date = params["end_date"]

    joined = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    joined = joined[(joined["o_orderdate"] >= start_date) & (joined["o_orderdate"] < end_date)]
    joined = joined.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    joined = joined[joined["l_returnflag"] == "R"]
    joined = joined.merge(nation, left_on="c_nationkey", right_on="n_nationkey").copy()
    # Alternative formula
    joined["revenue"] = joined["l_extendedprice"] - joined["l_extendedprice"] * joined["l_discount"]

    return (
        joined.groupby(
            ["c_custkey", "c_name", "c_acctbal", "c_phone", "n_name", "c_address", "c_comment"], as_index=False
        )
        .agg(revenue=("revenue", "sum"))
        .sort_values("revenue", ascending=False)
        .head(20)
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

Q10_VARIANTS = build_yaml_variants(__file__, globals(), 10, JOIN_AGG_SORT)
