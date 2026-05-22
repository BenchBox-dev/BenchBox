"""TPC-Havoc DataFrame variants for Q8.

Implements 10 structurally diverse variants of TPC-H Q8 (National Market Share).
Q8 is a 7-table join computing market share by year.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q8_expression_impl as _q8_expr_base,
    q8_pandas_impl as _q8_pandas_base,
)
from benchbox.core.tpchavoc.dataframe_queries.loader import load_variant_specs

# ---------------------------------------------------------------------------
# v1: baseline
# ---------------------------------------------------------------------------


def q8_v1_expression_impl(ctx: DataFrameContext) -> Any:
    return _q8_expr_base(ctx)


def q8_v1_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q8_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v2: pre-filter - filter part and orders by date before joining
# ---------------------------------------------------------------------------


def q8_v2_expression_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(8)
    target_nation = params["target_nation"]
    target_region = params["target_region"]
    target_type = params["target_type"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n2 = nation.select(col("n_nationkey").alias("n2_nationkey"), col("n_name").alias("nation"))

    # Pre-filter part and orders
    filtered_part = part.filter(col("p_type") == lit(target_type))
    filtered_orders = orders.filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") <= lit(end_date)))

    return (
        filtered_part.join(lineitem, left_on="p_partkey", right_on="l_partkey")
        .join(supplier, left_on="l_suppkey", right_on="s_suppkey")
        .join(n2, left_on="s_nationkey", right_on="n2_nationkey")
        .join(filtered_orders, left_on="l_orderkey", right_on="o_orderkey")
        .join(customer, left_on="o_custkey", right_on="c_custkey")
        .join(nation, left_on="c_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .filter(col("r_name") == lit(target_region))
        .with_columns(
            col("o_orderdate").dt.year().alias("o_year"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("volume"),
        )
        .group_by("o_year")
        .agg(
            col("volume").filter(col("nation") == lit(target_nation)).sum().alias("nation_volume"),
            col("volume").sum().alias("total_volume"),
        )
        .with_columns((col("nation_volume") / col("total_volume")).alias("mkt_share"))
        .select("o_year", "mkt_share")
        .sort("o_year")
    )


def q8_v2_pandas_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(8)
    target_nation = params["target_nation"]
    target_region = params["target_region"]
    target_type = params["target_type"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n2 = nation[["n_nationkey", "n_name"]].copy()
    n2.columns = ["n2_nationkey", "nation"]

    filtered_parts = part[part["p_type"] == target_type]
    filtered_orders = orders[(orders["o_orderdate"] >= start_date) & (orders["o_orderdate"] <= end_date)]

    joined = filtered_parts.merge(lineitem, left_on="p_partkey", right_on="l_partkey")
    joined = joined.merge(supplier, left_on="l_suppkey", right_on="s_suppkey")
    joined = joined.merge(n2, left_on="s_nationkey", right_on="n2_nationkey")
    joined = joined.merge(filtered_orders, left_on="l_orderkey", right_on="o_orderkey")
    joined = joined.merge(customer, left_on="o_custkey", right_on="c_custkey")
    joined = joined.merge(nation, left_on="c_nationkey", right_on="n_nationkey")
    joined = joined.merge(region, left_on="n_regionkey", right_on="r_regionkey")
    joined = joined[joined["r_name"] == target_region].copy()

    joined["o_year"] = joined["o_orderdate"].dt.year
    joined["volume"] = joined["l_extendedprice"] * (1 - joined["l_discount"])

    yearly = joined.groupby("o_year", as_index=False).agg(total_volume=("volume", "sum"))
    brazil_volume = (
        joined[joined["nation"] == target_nation].groupby("o_year", as_index=False).agg(nation_volume=("volume", "sum"))
    )
    result = yearly.merge(brazil_volume, on="o_year", how="left")
    result["nation_volume"] = result["nation_volume"].fillna(0)
    result["mkt_share"] = result["nation_volume"] / result["total_volume"]
    return result[["o_year", "mkt_share"]].sort_values("o_year")


# ---------------------------------------------------------------------------
# v3: column prune
# ---------------------------------------------------------------------------


def q8_v3_expression_impl(ctx: DataFrameContext) -> Any:
    return _q8_expr_base(ctx)


def q8_v3_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q8_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v4: intermediate vars
# ---------------------------------------------------------------------------


def q8_v4_expression_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(8)
    target_nation = params["target_nation"]
    target_region = params["target_region"]
    target_type = params["target_type"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n2 = nation.select(col("n_nationkey").alias("n2_nationkey"), col("n_name").alias("nation"))

    step1 = part.filter(col("p_type") == lit(target_type))
    step2 = step1.join(lineitem, left_on="p_partkey", right_on="l_partkey")
    step3 = step2.join(supplier, left_on="l_suppkey", right_on="s_suppkey")
    step4 = step3.join(n2, left_on="s_nationkey", right_on="n2_nationkey")
    step5 = step4.join(orders, left_on="l_orderkey", right_on="o_orderkey")
    step6 = step5.filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") <= lit(end_date)))
    step7 = step6.join(customer, left_on="o_custkey", right_on="c_custkey")
    step8 = step7.join(nation, left_on="c_nationkey", right_on="n_nationkey")
    step9 = step8.join(region, left_on="n_regionkey", right_on="r_regionkey")
    step10 = step9.filter(col("r_name") == lit(target_region))
    step11 = step10.with_columns(
        col("o_orderdate").dt.year().alias("o_year"),
        (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("volume"),
    )
    step12 = step11.group_by("o_year").agg(
        col("volume").filter(col("nation") == lit(target_nation)).sum().alias("nation_volume"),
        col("volume").sum().alias("total_volume"),
    )
    return (
        step12.with_columns((col("nation_volume") / col("total_volume")).alias("mkt_share"))
        .select("o_year", "mkt_share")
        .sort("o_year")
    )


def q8_v4_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q8_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v5: pre-compute derived
# ---------------------------------------------------------------------------


def q8_v5_expression_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(8)
    target_nation = params["target_nation"]
    target_region = params["target_region"]
    target_type = params["target_type"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n2 = nation.select(col("n_nationkey").alias("n2_nationkey"), col("n_name").alias("nation"))

    return (
        part.filter(col("p_type") == lit(target_type))
        .join(lineitem, left_on="p_partkey", right_on="l_partkey")
        .join(supplier, left_on="l_suppkey", right_on="s_suppkey")
        .join(n2, left_on="s_nationkey", right_on="n2_nationkey")
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") <= lit(end_date)))
        .join(customer, left_on="o_custkey", right_on="c_custkey")
        .join(nation, left_on="c_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .filter(col("r_name") == lit(target_region))
        # Pre-compute volume before group_by
        .with_columns(
            col("o_orderdate").dt.year().alias("o_year"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("volume"),
        )
        .group_by("o_year")
        .agg(
            col("volume").filter(col("nation") == lit(target_nation)).sum().alias("nation_volume"),
            col("volume").sum().alias("total_volume"),
        )
        .with_columns((col("nation_volume") / col("total_volume")).alias("mkt_share"))
        .select("o_year", "mkt_share")
        .sort("o_year")
    )


def q8_v5_pandas_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(8)
    target_nation = params["target_nation"]
    target_region = params["target_region"]
    target_type = params["target_type"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n2 = nation[["n_nationkey", "n_name"]].copy()
    n2.columns = ["n2_nationkey", "nation"]

    filtered_parts = part[part["p_type"] == target_type]
    joined = filtered_parts.merge(lineitem, left_on="p_partkey", right_on="l_partkey")
    joined = joined.merge(supplier, left_on="l_suppkey", right_on="s_suppkey")
    joined = joined.merge(n2, left_on="s_nationkey", right_on="n2_nationkey")
    joined = joined.merge(orders, left_on="l_orderkey", right_on="o_orderkey")
    joined = joined[(joined["o_orderdate"] >= start_date) & (joined["o_orderdate"] <= end_date)]
    joined = joined.merge(customer, left_on="o_custkey", right_on="c_custkey")
    joined = joined.merge(nation, left_on="c_nationkey", right_on="n_nationkey")
    joined = joined.merge(region, left_on="n_regionkey", right_on="r_regionkey")
    joined = joined[joined["r_name"] == target_region].copy()

    # Pre-compute derived
    joined["o_year"] = joined["o_orderdate"].dt.year
    joined["volume"] = joined["l_extendedprice"] * (1 - joined["l_discount"])

    yearly = joined.groupby("o_year", as_index=False).agg(total_volume=("volume", "sum"))
    brazil = (
        joined[joined["nation"] == target_nation].groupby("o_year", as_index=False).agg(nation_volume=("volume", "sum"))
    )
    result = yearly.merge(brazil, on="o_year", how="left")
    result["nation_volume"] = result["nation_volume"].fillna(0)
    result["mkt_share"] = result["nation_volume"] / result["total_volume"]
    return result[["o_year", "mkt_share"]].sort_values("o_year")


# ---------------------------------------------------------------------------
# v6: chained style
# ---------------------------------------------------------------------------


def q8_v6_expression_impl(ctx: DataFrameContext) -> Any:
    col = ctx.col
    lit = ctx.lit
    p = get_tpch_parameters(8)
    n2 = ctx.get_table("nation").select(col("n_nationkey").alias("n2_nationkey"), col("n_name").alias("nation"))
    return (
        ctx.get_table("part")
        .filter(col("p_type") == lit(p["target_type"]))
        .join(ctx.get_table("lineitem"), left_on="p_partkey", right_on="l_partkey")
        .join(ctx.get_table("supplier"), left_on="l_suppkey", right_on="s_suppkey")
        .join(n2, left_on="s_nationkey", right_on="n2_nationkey")
        .join(ctx.get_table("orders"), left_on="l_orderkey", right_on="o_orderkey")
        .filter((col("o_orderdate") >= lit(p["start_date"])) & (col("o_orderdate") <= lit(p["end_date"])))
        .join(ctx.get_table("customer"), left_on="o_custkey", right_on="c_custkey")
        .join(ctx.get_table("nation"), left_on="c_nationkey", right_on="n_nationkey")
        .join(ctx.get_table("region"), left_on="n_regionkey", right_on="r_regionkey")
        .filter(col("r_name") == lit(p["target_region"]))
        .with_columns(
            col("o_orderdate").dt.year().alias("o_year"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("volume"),
        )
        .group_by("o_year")
        .agg(
            col("volume").filter(col("nation") == lit(p["target_nation"])).sum().alias("nation_volume"),
            col("volume").sum().alias("total_volume"),
        )
        .with_columns((col("nation_volume") / col("total_volume")).alias("mkt_share"))
        .select("o_year", "mkt_share")
        .sort("o_year")
    )


def q8_v6_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q8_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v7: join reorder - start from lineitem instead of part
# ---------------------------------------------------------------------------


def q8_v7_expression_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(8)
    target_nation = params["target_nation"]
    target_region = params["target_region"]
    target_type = params["target_type"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n2 = nation.select(col("n_nationkey").alias("n2_nationkey"), col("n_name").alias("nation"))

    # Swapped: start from lineitem→part instead of part→lineitem
    return (
        lineitem.join(part.filter(col("p_type") == lit(target_type)), left_on="l_partkey", right_on="p_partkey")
        .join(supplier, left_on="l_suppkey", right_on="s_suppkey")
        .join(n2, left_on="s_nationkey", right_on="n2_nationkey")
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") <= lit(end_date)))
        .join(customer, left_on="o_custkey", right_on="c_custkey")
        .join(nation, left_on="c_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .filter(col("r_name") == lit(target_region))
        .with_columns(
            col("o_orderdate").dt.year().alias("o_year"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("volume"),
        )
        .group_by("o_year")
        .agg(
            col("volume").filter(col("nation") == lit(target_nation)).sum().alias("nation_volume"),
            col("volume").sum().alias("total_volume"),
        )
        .with_columns((col("nation_volume") / col("total_volume")).alias("mkt_share"))
        .select("o_year", "mkt_share")
        .sort("o_year")
    )


def q8_v7_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q8_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v8: filter combination - combine region and date filters
# ---------------------------------------------------------------------------


def q8_v8_expression_impl(ctx: DataFrameContext) -> Any:
    return q8_v2_expression_impl(ctx)


def q8_v8_pandas_impl(ctx: DataFrameContext) -> Any:
    return q8_v2_pandas_impl(ctx)


# ---------------------------------------------------------------------------
# v9: explicit sort
# ---------------------------------------------------------------------------


def q8_v9_expression_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(8)
    target_nation = params["target_nation"]
    target_region = params["target_region"]
    target_type = params["target_type"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n2 = nation.select(col("n_nationkey").alias("n2_nationkey"), col("n_name").alias("nation"))

    return (
        part.filter(col("p_type") == lit(target_type))
        .join(lineitem, left_on="p_partkey", right_on="l_partkey")
        .join(supplier, left_on="l_suppkey", right_on="s_suppkey")
        .join(n2, left_on="s_nationkey", right_on="n2_nationkey")
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") <= lit(end_date)))
        .join(customer, left_on="o_custkey", right_on="c_custkey")
        .join(nation, left_on="c_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .filter(col("r_name") == lit(target_region))
        .with_columns(
            col("o_orderdate").dt.year().alias("o_year"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("volume"),
        )
        .group_by("o_year")
        .agg(
            col("volume").filter(col("nation") == lit(target_nation)).sum().alias("nation_volume"),
            col("volume").sum().alias("total_volume"),
        )
        .with_columns((col("nation_volume") / col("total_volume")).alias("mkt_share"))
        .select("o_year", "mkt_share")
        .sort("o_year", descending=False)
    )


def q8_v9_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q8_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v10: alternative formula - volume = price - price*disc
# ---------------------------------------------------------------------------


def q8_v10_expression_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(8)
    target_nation = params["target_nation"]
    target_region = params["target_region"]
    target_type = params["target_type"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n2 = nation.select(col("n_nationkey").alias("n2_nationkey"), col("n_name").alias("nation"))
    volume_alt = col("l_extendedprice") - col("l_extendedprice") * col("l_discount")

    return (
        part.filter(col("p_type") == lit(target_type))
        .join(lineitem, left_on="p_partkey", right_on="l_partkey")
        .join(supplier, left_on="l_suppkey", right_on="s_suppkey")
        .join(n2, left_on="s_nationkey", right_on="n2_nationkey")
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") <= lit(end_date)))
        .join(customer, left_on="o_custkey", right_on="c_custkey")
        .join(nation, left_on="c_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .filter(col("r_name") == lit(target_region))
        .with_columns(
            col("o_orderdate").dt.year().alias("o_year"),
            volume_alt.alias("volume"),
        )
        .group_by("o_year")
        .agg(
            col("volume").filter(col("nation") == lit(target_nation)).sum().alias("nation_volume"),
            col("volume").sum().alias("total_volume"),
        )
        .with_columns((col("nation_volume") / col("total_volume")).alias("mkt_share"))
        .select("o_year", "mkt_share")
        .sort("o_year")
    )


def q8_v10_pandas_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(8)
    target_nation = params["target_nation"]
    target_region = params["target_region"]
    target_type = params["target_type"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    n2 = nation[["n_nationkey", "n_name"]].copy()
    n2.columns = ["n2_nationkey", "nation"]

    filtered_parts = part[part["p_type"] == target_type]
    joined = filtered_parts.merge(lineitem, left_on="p_partkey", right_on="l_partkey")
    joined = joined.merge(supplier, left_on="l_suppkey", right_on="s_suppkey")
    joined = joined.merge(n2, left_on="s_nationkey", right_on="n2_nationkey")
    joined = joined.merge(orders, left_on="l_orderkey", right_on="o_orderkey")
    joined = joined[(joined["o_orderdate"] >= start_date) & (joined["o_orderdate"] <= end_date)]
    joined = joined.merge(customer, left_on="o_custkey", right_on="c_custkey")
    joined = joined.merge(nation, left_on="c_nationkey", right_on="n_nationkey")
    joined = joined.merge(region, left_on="n_regionkey", right_on="r_regionkey")
    joined = joined[joined["r_name"] == target_region].copy()

    joined["o_year"] = joined["o_orderdate"].dt.year
    # Alternative formula
    joined["volume"] = joined["l_extendedprice"] - joined["l_extendedprice"] * joined["l_discount"]

    yearly = joined.groupby("o_year", as_index=False).agg(total_volume=("volume", "sum"))
    brazil = (
        joined[joined["nation"] == target_nation].groupby("o_year", as_index=False).agg(nation_volume=("volume", "sum"))
    )
    result = yearly.merge(brazil, on="o_year", how="left")
    result["nation_volume"] = result["nation_volume"].fillna(0)
    result["mkt_share"] = result["nation_volume"] / result["total_volume"]
    return result[["o_year", "mkt_share"]].sort_values("o_year")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_IMPL_PAIRS, _DESCRIPTIONS = load_variant_specs(__file__, globals())

Q8_VARIANTS: list[DataFrameQuery] = [
    DataFrameQuery(
        query_id=f"Q8v{v}",
        query_name=f"TPC-H Q8 Variant {v}",
        description=_DESCRIPTIONS[v - 1],
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=expr_impl,
        pandas_impl=pandas_impl,
    )
    for v, (expr_impl, pandas_impl) in enumerate(_IMPL_PAIRS, start=1)
]
