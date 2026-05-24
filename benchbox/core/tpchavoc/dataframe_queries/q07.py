"""TPC-Havoc DataFrame variants for Q7.

Implements 10 structurally diverse variants of TPC-H Q7 (Volume Shipping).
Q7 is a 5-table join with self-join on nation and bidirectional nation filter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q7_expression_impl as _q7_expr_base,
    q7_pandas_impl as _q7_pandas_base,
)
from benchbox.core.tpchavoc.dataframe_queries.loader import load_variant_specs

# ---------------------------------------------------------------------------
# v1: baseline
# ---------------------------------------------------------------------------


def q7_v1_expression_impl(ctx: DataFrameContext) -> Any:
    return _q7_expr_base(ctx)


def q7_v1_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q7_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v2: pre-filter - filter lineitem by date before joining
# ---------------------------------------------------------------------------


def q7_v2_expression_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(7)
    nation1 = params["nation1"]
    nation2 = params["nation2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n1 = nation.select(col("n_nationkey").alias("n1_nationkey"), col("n_name").alias("supp_nation"))
    n2 = nation.select(col("n_nationkey").alias("n2_nationkey"), col("n_name").alias("cust_nation"))

    # Pre-filter lineitem by date
    filtered_lineitem = lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") <= lit(end_date)))

    return (
        supplier.join(n1, left_on="s_nationkey", right_on="n1_nationkey")
        .join(filtered_lineitem, left_on="s_suppkey", right_on="l_suppkey")
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .join(customer, left_on="o_custkey", right_on="c_custkey")
        .join(n2, left_on="c_nationkey", right_on="n2_nationkey")
        .filter(
            ((col("supp_nation") == lit(nation1)) & (col("cust_nation") == lit(nation2)))
            | ((col("supp_nation") == lit(nation2)) & (col("cust_nation") == lit(nation1)))
        )
        .with_columns(
            col("l_shipdate").dt.year().alias("l_year"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("volume"),
        )
        .group_by("supp_nation", "cust_nation", "l_year")
        .agg(col("volume").sum().alias("revenue"))
        .sort("supp_nation", "cust_nation", "l_year")
    )


def q7_v2_pandas_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(7)
    nation1 = params["nation1"]
    nation2 = params["nation2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n1 = nation[["n_nationkey", "n_name"]].copy()
    n1.columns = ["n1_nationkey", "supp_nation"]
    n2 = nation[["n_nationkey", "n_name"]].copy()
    n2.columns = ["n2_nationkey", "cust_nation"]

    # Pre-filter lineitem
    filtered_li = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] <= end_date)]

    joined = supplier.merge(n1, left_on="s_nationkey", right_on="n1_nationkey")
    joined = joined.merge(filtered_li, left_on="s_suppkey", right_on="l_suppkey")
    joined = joined.merge(orders, left_on="l_orderkey", right_on="o_orderkey")
    joined = joined.merge(customer, left_on="o_custkey", right_on="c_custkey")
    joined = joined.merge(n2, left_on="c_nationkey", right_on="n2_nationkey")

    joined = joined[
        ((joined["supp_nation"] == nation1) & (joined["cust_nation"] == nation2))
        | ((joined["supp_nation"] == nation2) & (joined["cust_nation"] == nation1))
    ].copy()
    joined["l_year"] = joined["l_shipdate"].dt.year
    joined["volume"] = joined["l_extendedprice"] * (1 - joined["l_discount"])

    return (
        joined.groupby(["supp_nation", "cust_nation", "l_year"], as_index=False)
        .agg(revenue=("volume", "sum"))
        .sort_values(["supp_nation", "cust_nation", "l_year"])
    )


# ---------------------------------------------------------------------------
# v3: column prune - select only needed columns from each table
# ---------------------------------------------------------------------------


def q7_v3_expression_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(7)
    nation1 = params["nation1"]
    nation2 = params["nation2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n1 = nation.select(col("n_nationkey").alias("n1_nationkey"), col("n_name").alias("supp_nation"))
    n2 = nation.select(col("n_nationkey").alias("n2_nationkey"), col("n_name").alias("cust_nation"))

    return (
        supplier.select("s_suppkey", "s_nationkey")
        .join(n1, left_on="s_nationkey", right_on="n1_nationkey")
        .join(
            lineitem.select("l_suppkey", "l_orderkey", "l_shipdate", "l_extendedprice", "l_discount"),
            left_on="s_suppkey",
            right_on="l_suppkey",
        )
        .filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") <= lit(end_date)))
        .join(orders.select("o_orderkey", "o_custkey"), left_on="l_orderkey", right_on="o_orderkey")
        .join(customer.select("c_custkey", "c_nationkey"), left_on="o_custkey", right_on="c_custkey")
        .join(n2, left_on="c_nationkey", right_on="n2_nationkey")
        .filter(
            ((col("supp_nation") == lit(nation1)) & (col("cust_nation") == lit(nation2)))
            | ((col("supp_nation") == lit(nation2)) & (col("cust_nation") == lit(nation1)))
        )
        .with_columns(
            col("l_shipdate").dt.year().alias("l_year"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("volume"),
        )
        .group_by("supp_nation", "cust_nation", "l_year")
        .agg(col("volume").sum().alias("revenue"))
        .sort("supp_nation", "cust_nation", "l_year")
    )


def q7_v3_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q7_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v4: intermediate vars - explicit named step DataFrames
# ---------------------------------------------------------------------------


def q7_v4_expression_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(7)
    nation1 = params["nation1"]
    nation2 = params["nation2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n1 = nation.select(col("n_nationkey").alias("n1_nationkey"), col("n_name").alias("supp_nation"))
    n2 = nation.select(col("n_nationkey").alias("n2_nationkey"), col("n_name").alias("cust_nation"))

    step1 = supplier.join(n1, left_on="s_nationkey", right_on="n1_nationkey")
    step2 = step1.join(lineitem, left_on="s_suppkey", right_on="l_suppkey")
    step3 = step2.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") <= lit(end_date)))
    step4 = step3.join(orders, left_on="l_orderkey", right_on="o_orderkey")
    step5 = step4.join(customer, left_on="o_custkey", right_on="c_custkey")
    step6 = step5.join(n2, left_on="c_nationkey", right_on="n2_nationkey")
    step7 = step6.filter(
        ((col("supp_nation") == lit(nation1)) & (col("cust_nation") == lit(nation2)))
        | ((col("supp_nation") == lit(nation2)) & (col("cust_nation") == lit(nation1)))
    )
    step8 = step7.with_columns(
        col("l_shipdate").dt.year().alias("l_year"),
        (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("volume"),
    )
    return (
        step8.group_by("supp_nation", "cust_nation", "l_year")
        .agg(col("volume").sum().alias("revenue"))
        .sort("supp_nation", "cust_nation", "l_year")
    )


def q7_v4_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q7_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v5: pre-compute derived - add volume before groupby
# ---------------------------------------------------------------------------


def q7_v5_expression_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(7)
    nation1 = params["nation1"]
    nation2 = params["nation2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n1 = nation.select(col("n_nationkey").alias("n1_nationkey"), col("n_name").alias("supp_nation"))
    n2 = nation.select(col("n_nationkey").alias("n2_nationkey"), col("n_name").alias("cust_nation"))

    return (
        supplier.join(n1, left_on="s_nationkey", right_on="n1_nationkey")
        .join(lineitem, left_on="s_suppkey", right_on="l_suppkey")
        .filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") <= lit(end_date)))
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .join(customer, left_on="o_custkey", right_on="c_custkey")
        .join(n2, left_on="c_nationkey", right_on="n2_nationkey")
        .filter(
            ((col("supp_nation") == lit(nation1)) & (col("cust_nation") == lit(nation2)))
            | ((col("supp_nation") == lit(nation2)) & (col("cust_nation") == lit(nation1)))
        )
        # Pre-compute both derived columns
        .with_columns(
            col("l_shipdate").dt.year().alias("l_year"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("volume"),
        )
        .group_by("supp_nation", "cust_nation", "l_year")
        .agg(col("volume").sum().alias("revenue"))
        .sort("supp_nation", "cust_nation", "l_year")
    )


def q7_v5_pandas_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(7)
    nation1 = params["nation1"]
    nation2 = params["nation2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n1 = nation[["n_nationkey", "n_name"]].copy()
    n1.columns = ["n1_nationkey", "supp_nation"]
    n2 = nation[["n_nationkey", "n_name"]].copy()
    n2.columns = ["n2_nationkey", "cust_nation"]

    joined = supplier.merge(n1, left_on="s_nationkey", right_on="n1_nationkey")
    joined = joined.merge(lineitem, left_on="s_suppkey", right_on="l_suppkey")
    joined = joined[(joined["l_shipdate"] >= start_date) & (joined["l_shipdate"] <= end_date)]
    joined = joined.merge(orders, left_on="l_orderkey", right_on="o_orderkey")
    joined = joined.merge(customer, left_on="o_custkey", right_on="c_custkey")
    joined = joined.merge(n2, left_on="c_nationkey", right_on="n2_nationkey")
    joined = joined[
        ((joined["supp_nation"] == nation1) & (joined["cust_nation"] == nation2))
        | ((joined["supp_nation"] == nation2) & (joined["cust_nation"] == nation1))
    ].copy()
    # Pre-compute
    joined["l_year"] = joined["l_shipdate"].dt.year
    joined["volume"] = joined["l_extendedprice"] * (1 - joined["l_discount"])
    return (
        joined.groupby(["supp_nation", "cust_nation", "l_year"], as_index=False)
        .agg(revenue=("volume", "sum"))
        .sort_values(["supp_nation", "cust_nation", "l_year"])
    )


# ---------------------------------------------------------------------------
# v6: chained style
# ---------------------------------------------------------------------------


def q7_v6_expression_impl(ctx: DataFrameContext) -> Any:
    col = ctx.col
    lit = ctx.lit
    p = get_tpch_parameters(7)
    n1 = ctx.get_table("nation").select(col("n_nationkey").alias("n1_nationkey"), col("n_name").alias("supp_nation"))
    n2 = ctx.get_table("nation").select(col("n_nationkey").alias("n2_nationkey"), col("n_name").alias("cust_nation"))
    return (
        ctx.get_table("supplier")
        .join(n1, left_on="s_nationkey", right_on="n1_nationkey")
        .join(ctx.get_table("lineitem"), left_on="s_suppkey", right_on="l_suppkey")
        .filter((col("l_shipdate") >= lit(p["start_date"])) & (col("l_shipdate") <= lit(p["end_date"])))
        .join(ctx.get_table("orders"), left_on="l_orderkey", right_on="o_orderkey")
        .join(ctx.get_table("customer"), left_on="o_custkey", right_on="c_custkey")
        .join(n2, left_on="c_nationkey", right_on="n2_nationkey")
        .filter(
            ((col("supp_nation") == lit(p["nation1"])) & (col("cust_nation") == lit(p["nation2"])))
            | ((col("supp_nation") == lit(p["nation2"])) & (col("cust_nation") == lit(p["nation1"])))
        )
        .with_columns(
            col("l_shipdate").dt.year().alias("l_year"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("volume"),
        )
        .group_by("supp_nation", "cust_nation", "l_year")
        .agg(col("volume").sum().alias("revenue"))
        .sort("supp_nation", "cust_nation", "l_year")
    )


def q7_v6_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q7_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v7: join reorder - join lineitem→supplier instead of supplier→lineitem
# ---------------------------------------------------------------------------


def q7_v7_expression_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(7)
    nation1 = params["nation1"]
    nation2 = params["nation2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n1 = nation.select(col("n_nationkey").alias("n1_nationkey"), col("n_name").alias("supp_nation"))
    n2 = nation.select(col("n_nationkey").alias("n2_nationkey"), col("n_name").alias("cust_nation"))

    # Swapped: lineitem → supplier instead of supplier → lineitem
    return (
        lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") <= lit(end_date)))
        .join(supplier, left_on="l_suppkey", right_on="s_suppkey")
        .join(n1, left_on="s_nationkey", right_on="n1_nationkey")
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .join(customer, left_on="o_custkey", right_on="c_custkey")
        .join(n2, left_on="c_nationkey", right_on="n2_nationkey")
        .filter(
            ((col("supp_nation") == lit(nation1)) & (col("cust_nation") == lit(nation2)))
            | ((col("supp_nation") == lit(nation2)) & (col("cust_nation") == lit(nation1)))
        )
        .with_columns(
            col("l_shipdate").dt.year().alias("l_year"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("volume"),
        )
        .group_by("supp_nation", "cust_nation", "l_year")
        .agg(col("volume").sum().alias("revenue"))
        .sort("supp_nation", "cust_nation", "l_year")
    )


def q7_v7_pandas_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(7)
    nation1 = params["nation1"]
    nation2 = params["nation2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n1 = nation[["n_nationkey", "n_name"]].copy()
    n1.columns = ["n1_nationkey", "supp_nation"]
    n2 = nation[["n_nationkey", "n_name"]].copy()
    n2.columns = ["n2_nationkey", "cust_nation"]

    # Swapped: start from lineitem
    filtered_li = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] <= end_date)]
    joined = filtered_li.merge(supplier, left_on="l_suppkey", right_on="s_suppkey")
    joined = joined.merge(n1, left_on="s_nationkey", right_on="n1_nationkey")
    joined = joined.merge(orders, left_on="l_orderkey", right_on="o_orderkey")
    joined = joined.merge(customer, left_on="o_custkey", right_on="c_custkey")
    joined = joined.merge(n2, left_on="c_nationkey", right_on="n2_nationkey")
    joined = joined[
        ((joined["supp_nation"] == nation1) & (joined["cust_nation"] == nation2))
        | ((joined["supp_nation"] == nation2) & (joined["cust_nation"] == nation1))
    ].copy()
    joined["l_year"] = joined["l_shipdate"].dt.year
    joined["volume"] = joined["l_extendedprice"] * (1 - joined["l_discount"])
    return (
        joined.groupby(["supp_nation", "cust_nation", "l_year"], as_index=False)
        .agg(revenue=("volume", "sum"))
        .sort_values(["supp_nation", "cust_nation", "l_year"])
    )


# ---------------------------------------------------------------------------
# v8: filter combination - combine nation pair filter into compound expression
# ---------------------------------------------------------------------------


def q7_v8_expression_impl(ctx: DataFrameContext) -> Any:
    return q7_v2_expression_impl(ctx)


def q7_v8_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q7_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v9: explicit sort
# ---------------------------------------------------------------------------


def q7_v9_expression_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(7)
    nation1 = params["nation1"]
    nation2 = params["nation2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n1 = nation.select(col("n_nationkey").alias("n1_nationkey"), col("n_name").alias("supp_nation"))
    n2 = nation.select(col("n_nationkey").alias("n2_nationkey"), col("n_name").alias("cust_nation"))

    return (
        supplier.join(n1, left_on="s_nationkey", right_on="n1_nationkey")
        .join(lineitem, left_on="s_suppkey", right_on="l_suppkey")
        .filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") <= lit(end_date)))
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .join(customer, left_on="o_custkey", right_on="c_custkey")
        .join(n2, left_on="c_nationkey", right_on="n2_nationkey")
        .filter(
            ((col("supp_nation") == lit(nation1)) & (col("cust_nation") == lit(nation2)))
            | ((col("supp_nation") == lit(nation2)) & (col("cust_nation") == lit(nation1)))
        )
        .with_columns(
            col("l_shipdate").dt.year().alias("l_year"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("volume"),
        )
        .group_by("supp_nation", "cust_nation", "l_year")
        .agg(col("volume").sum().alias("revenue"))
        .sort(["supp_nation", "cust_nation", "l_year"], descending=[False, False, False])
    )


def q7_v9_pandas_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(7)
    nation1 = params["nation1"]
    nation2 = params["nation2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n1 = nation[["n_nationkey", "n_name"]].copy()
    n1.columns = ["n1_nationkey", "supp_nation"]
    n2 = nation[["n_nationkey", "n_name"]].copy()
    n2.columns = ["n2_nationkey", "cust_nation"]

    joined = supplier.merge(n1, left_on="s_nationkey", right_on="n1_nationkey")
    joined = joined.merge(lineitem, left_on="s_suppkey", right_on="l_suppkey")
    joined = joined[(joined["l_shipdate"] >= start_date) & (joined["l_shipdate"] <= end_date)]
    joined = joined.merge(orders, left_on="l_orderkey", right_on="o_orderkey")
    joined = joined.merge(customer, left_on="o_custkey", right_on="c_custkey")
    joined = joined.merge(n2, left_on="c_nationkey", right_on="n2_nationkey")
    joined = joined[
        ((joined["supp_nation"] == nation1) & (joined["cust_nation"] == nation2))
        | ((joined["supp_nation"] == nation2) & (joined["cust_nation"] == nation1))
    ].copy()
    joined["l_year"] = joined["l_shipdate"].dt.year
    joined["volume"] = joined["l_extendedprice"] * (1 - joined["l_discount"])
    return (
        joined.groupby(["supp_nation", "cust_nation", "l_year"], as_index=False)
        .agg(revenue=("volume", "sum"))
        .sort_values(["supp_nation", "cust_nation", "l_year"], ascending=[True, True, True])
    )


# ---------------------------------------------------------------------------
# v10: alternative formula - volume = price - price*disc
# ---------------------------------------------------------------------------


def q7_v10_expression_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(7)
    nation1 = params["nation1"]
    nation2 = params["nation2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n1 = nation.select(col("n_nationkey").alias("n1_nationkey"), col("n_name").alias("supp_nation"))
    n2 = nation.select(col("n_nationkey").alias("n2_nationkey"), col("n_name").alias("cust_nation"))

    # Alternative: price - price*disc
    volume_alt = col("l_extendedprice") - col("l_extendedprice") * col("l_discount")

    return (
        supplier.join(n1, left_on="s_nationkey", right_on="n1_nationkey")
        .join(lineitem, left_on="s_suppkey", right_on="l_suppkey")
        .filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") <= lit(end_date)))
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .join(customer, left_on="o_custkey", right_on="c_custkey")
        .join(n2, left_on="c_nationkey", right_on="n2_nationkey")
        .filter(
            ((col("supp_nation") == lit(nation1)) & (col("cust_nation") == lit(nation2)))
            | ((col("supp_nation") == lit(nation2)) & (col("cust_nation") == lit(nation1)))
        )
        .with_columns(
            col("l_shipdate").dt.year().alias("l_year"),
            volume_alt.alias("volume"),
        )
        .group_by("supp_nation", "cust_nation", "l_year")
        .agg(col("volume").sum().alias("revenue"))
        .sort("supp_nation", "cust_nation", "l_year")
    )


def q7_v10_pandas_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(7)
    nation1 = params["nation1"]
    nation2 = params["nation2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n1 = nation[["n_nationkey", "n_name"]].copy()
    n1.columns = ["n1_nationkey", "supp_nation"]
    n2 = nation[["n_nationkey", "n_name"]].copy()
    n2.columns = ["n2_nationkey", "cust_nation"]

    joined = supplier.merge(n1, left_on="s_nationkey", right_on="n1_nationkey")
    joined = joined.merge(lineitem, left_on="s_suppkey", right_on="l_suppkey")
    joined = joined[(joined["l_shipdate"] >= start_date) & (joined["l_shipdate"] <= end_date)]
    joined = joined.merge(orders, left_on="l_orderkey", right_on="o_orderkey")
    joined = joined.merge(customer, left_on="o_custkey", right_on="c_custkey")
    joined = joined.merge(n2, left_on="c_nationkey", right_on="n2_nationkey")
    joined = joined[
        ((joined["supp_nation"] == nation1) & (joined["cust_nation"] == nation2))
        | ((joined["supp_nation"] == nation2) & (joined["cust_nation"] == nation1))
    ].copy()
    joined["l_year"] = joined["l_shipdate"].dt.year
    # Alternative formula
    joined["volume"] = joined["l_extendedprice"] - joined["l_extendedprice"] * joined["l_discount"]
    return (
        joined.groupby(["supp_nation", "cust_nation", "l_year"], as_index=False)
        .agg(revenue=("volume", "sum"))
        .sort_values(["supp_nation", "cust_nation", "l_year"])
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_IMPL_PAIRS, _DESCRIPTIONS = load_variant_specs(__file__, globals())

Q7_VARIANTS: list[DataFrameQuery] = [
    DataFrameQuery(
        query_id=f"Q7v{v}",
        query_name=f"TPC-H Q7 Variant {v}",
        description=_DESCRIPTIONS[v - 1],
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=expr_impl,
        pandas_impl=pandas_impl,
    )
    for v, (expr_impl, pandas_impl) in enumerate(_IMPL_PAIRS, start=1)
]
