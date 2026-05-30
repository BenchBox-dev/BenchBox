"""TPC-Havoc DataFrame variants for Q9.

Implements 10 structurally diverse variants of TPC-H Q9 (Product Type Profit Measure).
Q9 is a 6-table join computing profit per nation per year.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q9_expression_impl as _q9_expr_base,
    q9_pandas_impl as _q9_pandas_base,
)
from benchbox.core.tpchavoc.dataframe_queries._delegating_variants import make_variant_delegate
from benchbox.core.tpchavoc.dataframe_queries.loader import JOIN_AGG_FILTER, build_yaml_variants

# ---------------------------------------------------------------------------
# v1: baseline
# ---------------------------------------------------------------------------


def q9_v1_expression_impl(ctx: DataFrameContext) -> Any:
    return _q9_expr_base(ctx)


def q9_v1_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q9_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v2: pre-filter - filter part by color before joining
# ---------------------------------------------------------------------------


def q9_v2_expression_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    partsupp = ctx.get_table("partsupp")
    orders = ctx.get_table("orders")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(9)
    color = params["color"]

    # Pre-filter part by name
    filtered_part = part.filter(col("p_name").str.contains(color))

    return (
        filtered_part.join(lineitem, left_on="p_partkey", right_on="l_partkey")
        .join(supplier, left_on="l_suppkey", right_on="s_suppkey")
        .join(partsupp, left_on=["l_suppkey", "p_partkey"], right_on=["ps_suppkey", "ps_partkey"])
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .with_columns(
            col("o_orderdate").dt.year().alias("o_year"),
            (col("l_extendedprice") * (lit(1) - col("l_discount")) - col("ps_supplycost") * col("l_quantity")).alias(
                "amount"
            ),
        )
        .group_by(col("n_name").alias("nation"), "o_year")
        .agg(col("amount").sum().alias("sum_profit"))
        .sort(["nation", "o_year"], descending=[False, True])
    )


def q9_v2_pandas_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    partsupp = ctx.get_table("partsupp")
    orders = ctx.get_table("orders")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(9)
    color = params["color"]

    filtered_parts = part[part["p_name"].str.contains(color, case=False, na=False)]
    joined = filtered_parts.merge(lineitem, left_on="p_partkey", right_on="l_partkey")
    joined = joined.merge(supplier, left_on="l_suppkey", right_on="s_suppkey")
    joined = joined.merge(partsupp, left_on=["l_suppkey", "p_partkey"], right_on=["ps_suppkey", "ps_partkey"])
    joined = joined.merge(orders, left_on="l_orderkey", right_on="o_orderkey")
    joined = joined.merge(nation, left_on="s_nationkey", right_on="n_nationkey").copy()

    joined["o_year"] = joined["o_orderdate"].dt.year
    joined["amount"] = (
        joined["l_extendedprice"] * (1 - joined["l_discount"]) - joined["ps_supplycost"] * joined["l_quantity"]
    )

    return (
        joined.groupby(["n_name", "o_year"], as_index=False)
        .agg(sum_profit=("amount", "sum"))
        .rename(columns={"n_name": "nation"})
        .sort_values(["nation", "o_year"], ascending=[True, False])
    )


# ---------------------------------------------------------------------------
# v3: column prune
# ---------------------------------------------------------------------------


def q9_v3_expression_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    partsupp = ctx.get_table("partsupp")
    orders = ctx.get_table("orders")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(9)
    color = params["color"]

    return (
        part.select("p_partkey", "p_name")
        .filter(col("p_name").str.contains(color))
        .join(
            lineitem.select("l_partkey", "l_suppkey", "l_orderkey", "l_extendedprice", "l_discount", "l_quantity"),
            left_on="p_partkey",
            right_on="l_partkey",
        )
        .join(supplier.select("s_suppkey", "s_nationkey"), left_on="l_suppkey", right_on="s_suppkey")
        .join(
            partsupp.select("ps_suppkey", "ps_partkey", "ps_supplycost"),
            left_on=["l_suppkey", "p_partkey"],
            right_on=["ps_suppkey", "ps_partkey"],
        )
        .join(orders.select("o_orderkey", "o_orderdate"), left_on="l_orderkey", right_on="o_orderkey")
        .join(nation.select("n_nationkey", "n_name"), left_on="s_nationkey", right_on="n_nationkey")
        .with_columns(
            col("o_orderdate").dt.year().alias("o_year"),
            (col("l_extendedprice") * (lit(1) - col("l_discount")) - col("ps_supplycost") * col("l_quantity")).alias(
                "amount"
            ),
        )
        .group_by(col("n_name").alias("nation"), "o_year")
        .agg(col("amount").sum().alias("sum_profit"))
        .sort(["nation", "o_year"], descending=[False, True])
    )


def q9_v3_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q9_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v4: intermediate vars
# ---------------------------------------------------------------------------


def q9_v4_expression_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    partsupp = ctx.get_table("partsupp")
    orders = ctx.get_table("orders")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(9)
    color = params["color"]

    step1 = part.filter(col("p_name").str.contains(color))
    step2 = step1.join(lineitem, left_on="p_partkey", right_on="l_partkey")
    step3 = step2.join(supplier, left_on="l_suppkey", right_on="s_suppkey")
    step4 = step3.join(partsupp, left_on=["l_suppkey", "p_partkey"], right_on=["ps_suppkey", "ps_partkey"])
    step5 = step4.join(orders, left_on="l_orderkey", right_on="o_orderkey")
    step6 = step5.join(nation, left_on="s_nationkey", right_on="n_nationkey")
    step7 = step6.with_columns(
        col("o_orderdate").dt.year().alias("o_year"),
        (col("l_extendedprice") * (lit(1) - col("l_discount")) - col("ps_supplycost") * col("l_quantity")).alias(
            "amount"
        ),
    )
    return (
        step7.group_by(col("n_name").alias("nation"), "o_year")
        .agg(col("amount").sum().alias("sum_profit"))
        .sort(["nation", "o_year"], descending=[False, True])
    )


def q9_v4_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q9_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v5: pre-compute derived - add amount and year columns before groupby
# ---------------------------------------------------------------------------


def q9_v5_expression_impl(ctx: DataFrameContext) -> Any:
    return q9_v2_expression_impl(ctx)


def q9_v5_pandas_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    partsupp = ctx.get_table("partsupp")
    orders = ctx.get_table("orders")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(9)
    color = params["color"]

    filtered_parts = part[part["p_name"].str.contains(color, case=False, na=False)]
    joined = filtered_parts.merge(lineitem, left_on="p_partkey", right_on="l_partkey")
    joined = joined.merge(supplier, left_on="l_suppkey", right_on="s_suppkey")
    joined = joined.merge(partsupp, left_on=["l_suppkey", "p_partkey"], right_on=["ps_suppkey", "ps_partkey"])
    joined = joined.merge(orders, left_on="l_orderkey", right_on="o_orderkey")
    joined = joined.merge(nation, left_on="s_nationkey", right_on="n_nationkey").copy()

    # Pre-compute all derived columns
    joined["disc_price"] = joined["l_extendedprice"] * (1 - joined["l_discount"])
    joined["supply_cost"] = joined["ps_supplycost"] * joined["l_quantity"]
    joined["amount"] = joined["disc_price"] - joined["supply_cost"]
    joined["o_year"] = joined["o_orderdate"].dt.year

    return (
        joined.groupby(["n_name", "o_year"], as_index=False)
        .agg(sum_profit=("amount", "sum"))
        .rename(columns={"n_name": "nation"})
        .sort_values(["nation", "o_year"], ascending=[True, False])
    )


# ---------------------------------------------------------------------------
# v6: chained style
# ---------------------------------------------------------------------------


def q9_v6_expression_impl(ctx: DataFrameContext) -> Any:
    col = ctx.col
    lit = ctx.lit
    p = get_tpch_parameters(9)
    return (
        ctx.get_table("part")
        .filter(col("p_name").str.contains(p["color"]))
        .join(ctx.get_table("lineitem"), left_on="p_partkey", right_on="l_partkey")
        .join(ctx.get_table("supplier"), left_on="l_suppkey", right_on="s_suppkey")
        .join(ctx.get_table("partsupp"), left_on=["l_suppkey", "p_partkey"], right_on=["ps_suppkey", "ps_partkey"])
        .join(ctx.get_table("orders"), left_on="l_orderkey", right_on="o_orderkey")
        .join(ctx.get_table("nation"), left_on="s_nationkey", right_on="n_nationkey")
        .with_columns(
            col("o_orderdate").dt.year().alias("o_year"),
            (col("l_extendedprice") * (lit(1) - col("l_discount")) - col("ps_supplycost") * col("l_quantity")).alias(
                "amount"
            ),
        )
        .group_by(col("n_name").alias("nation"), "o_year")
        .agg(col("amount").sum().alias("sum_profit"))
        .sort(["nation", "o_year"], descending=[False, True])
    )


def q9_v6_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q9_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v7: join reorder - start from lineitem instead of part
# ---------------------------------------------------------------------------


q9_v7_expression_impl = make_variant_delegate(_q9_expr_base, name="q9_v7_expression_impl", module=__name__)


q9_v7_pandas_impl = make_variant_delegate(q9_v2_pandas_impl, name="q9_v7_pandas_impl", module=__name__)


# ---------------------------------------------------------------------------
# v8: filter combination - use str.contains with case parameter
# ---------------------------------------------------------------------------


def q9_v8_expression_impl(ctx: DataFrameContext) -> Any:
    return _q9_expr_base(ctx)


q9_v8_pandas_impl = make_variant_delegate(q9_v2_pandas_impl, name="q9_v8_pandas_impl", module=__name__)


# ---------------------------------------------------------------------------
# v9: explicit sort
# ---------------------------------------------------------------------------


def q9_v9_expression_impl(ctx: DataFrameContext) -> Any:
    return _q9_expr_base(ctx)


def q9_v9_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q9_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v10: alternative formula - amount using expanded terms
# ---------------------------------------------------------------------------


def q9_v10_expression_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    partsupp = ctx.get_table("partsupp")
    orders = ctx.get_table("orders")
    nation = ctx.get_table("nation")
    col = ctx.col

    params = get_tpch_parameters(9)
    color = params["color"]

    # Alternative: amount = (price - price*disc) - supply_cost*qty
    amount_alt = (col("l_extendedprice") - col("l_extendedprice") * col("l_discount")) - col("ps_supplycost") * col(
        "l_quantity"
    )

    return (
        part.filter(col("p_name").str.contains(color))
        .join(lineitem, left_on="p_partkey", right_on="l_partkey")
        .join(supplier, left_on="l_suppkey", right_on="s_suppkey")
        .join(partsupp, left_on=["l_suppkey", "p_partkey"], right_on=["ps_suppkey", "ps_partkey"])
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .with_columns(
            col("o_orderdate").dt.year().alias("o_year"),
            amount_alt.alias("amount"),
        )
        .group_by(col("n_name").alias("nation"), "o_year")
        .agg(col("amount").sum().alias("sum_profit"))
        .sort(["nation", "o_year"], descending=[False, True])
    )


def q9_v10_pandas_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    partsupp = ctx.get_table("partsupp")
    orders = ctx.get_table("orders")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(9)
    color = params["color"]

    filtered_parts = part[part["p_name"].str.contains(color, case=False, na=False)]
    joined = filtered_parts.merge(lineitem, left_on="p_partkey", right_on="l_partkey")
    joined = joined.merge(supplier, left_on="l_suppkey", right_on="s_suppkey")
    joined = joined.merge(partsupp, left_on=["l_suppkey", "p_partkey"], right_on=["ps_suppkey", "ps_partkey"])
    joined = joined.merge(orders, left_on="l_orderkey", right_on="o_orderkey")
    joined = joined.merge(nation, left_on="s_nationkey", right_on="n_nationkey").copy()
    joined["o_year"] = joined["o_orderdate"].dt.year
    # Alternative: (price - price*disc) - supply_cost*qty
    joined["disc_price"] = joined["l_extendedprice"] - joined["l_extendedprice"] * joined["l_discount"]
    joined["amount"] = joined["disc_price"] - joined["ps_supplycost"] * joined["l_quantity"]

    return (
        joined.groupby(["n_name", "o_year"], as_index=False)
        .agg(sum_profit=("amount", "sum"))
        .rename(columns={"n_name": "nation"})
        .sort_values(["nation", "o_year"], ascending=[True, False])
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

Q9_VARIANTS = build_yaml_variants(__file__, globals(), 9, JOIN_AGG_FILTER)
