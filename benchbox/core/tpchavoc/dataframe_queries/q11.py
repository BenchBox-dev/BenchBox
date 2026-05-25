"""TPC-Havoc DataFrame variants for Q11.

Implements 10 structurally diverse variants of TPC-H Q11 (Important Stock Identification).
Q11 uses a scalar subquery pattern: find parts whose stock value exceeds a threshold.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q11_expression_impl as _q11_expr_base,
    q11_pandas_impl as _q11_pandas_base,
)
from benchbox.core.tpchavoc.dataframe_queries.loader import JOIN_AGG_SUBQUERY, build_yaml_variants

# ---------------------------------------------------------------------------
# v1: baseline
# ---------------------------------------------------------------------------


def q11_v1_expression_impl(ctx: DataFrameContext) -> Any:
    return _q11_expr_base(ctx)


def q11_v1_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q11_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v2: pre-filter - filter nation and supplier before joining with partsupp
# ---------------------------------------------------------------------------


def q11_v2_expression_impl(ctx: DataFrameContext) -> Any:
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(11)
    nation_name = params["nation_name"]
    fraction = params["fraction"]

    # Pre-filter nation and then join with supplier
    filtered_nation = nation.filter(col("n_name") == lit(nation_name))
    nation_suppliers = supplier.join(filtered_nation, left_on="s_nationkey", right_on="n_nationkey")

    nation_stock = partsupp.join(nation_suppliers, left_on="ps_suppkey", right_on="s_suppkey").with_columns(
        (col("ps_supplycost") * col("ps_availqty")).alias("value")
    )

    total_value = ctx.scalar(nation_stock.select(col("value").sum().alias("total")))
    threshold = total_value * fraction

    return (
        nation_stock.group_by("ps_partkey")
        .agg(col("value").sum().alias("value"))
        .filter(col("value") > lit(threshold))
        .sort("value", descending=True)
    )


def q11_v2_pandas_impl(ctx: DataFrameContext) -> Any:
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(11)
    nation_name = params["nation_name"]
    fraction = params["fraction"]

    # Pre-filter nation
    filtered_nation = nation[nation["n_name"] == nation_name]
    nation_suppliers = supplier.merge(filtered_nation, left_on="s_nationkey", right_on="n_nationkey")

    joined = partsupp.merge(nation_suppliers, left_on="ps_suppkey", right_on="s_suppkey").copy()
    joined["value"] = joined["ps_supplycost"] * joined["ps_availqty"]

    total_value = joined["value"].sum()
    total_value = total_value.compute() if hasattr(total_value, "compute") else total_value
    threshold = total_value * fraction

    aggregated = joined.groupby("ps_partkey", as_index=False).agg(value=("value", "sum"))
    return aggregated[aggregated["value"] > threshold].sort_values("value", ascending=False)


# ---------------------------------------------------------------------------
# v3: column prune - select only needed columns before joining
# ---------------------------------------------------------------------------


def q11_v3_expression_impl(ctx: DataFrameContext) -> Any:
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(11)
    nation_name = params["nation_name"]
    fraction = params["fraction"]

    nation_stock = (
        partsupp.select("ps_suppkey", "ps_partkey", "ps_supplycost", "ps_availqty")
        .join(supplier.select("s_suppkey", "s_nationkey"), left_on="ps_suppkey", right_on="s_suppkey")
        .join(
            nation.filter(col("n_name") == lit(nation_name)).select("n_nationkey"),
            left_on="s_nationkey",
            right_on="n_nationkey",
        )
        .with_columns((col("ps_supplycost") * col("ps_availqty")).alias("value"))
    )

    total_value = ctx.scalar(nation_stock.select(col("value").sum().alias("total")))
    threshold = total_value * fraction

    return (
        nation_stock.group_by("ps_partkey")
        .agg(col("value").sum().alias("value"))
        .filter(col("value") > lit(threshold))
        .sort("value", descending=True)
    )


def q11_v3_pandas_impl(ctx: DataFrameContext) -> Any:
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(11)
    nation_name = params["nation_name"]
    fraction = params["fraction"]

    # Pruned columns
    ps = partsupp[["ps_suppkey", "ps_partkey", "ps_supplycost", "ps_availqty"]]
    s = supplier[["s_suppkey", "s_nationkey"]]
    n = nation[["n_nationkey", "n_name"]]

    joined = ps.merge(s, left_on="ps_suppkey", right_on="s_suppkey")
    joined = joined.merge(n, left_on="s_nationkey", right_on="n_nationkey")
    joined = joined[joined["n_name"] == nation_name].copy()
    joined["value"] = joined["ps_supplycost"] * joined["ps_availqty"]

    total_value = joined["value"].sum()
    total_value = total_value.compute() if hasattr(total_value, "compute") else total_value
    threshold = total_value * fraction

    aggregated = joined.groupby("ps_partkey", as_index=False).agg(value=("value", "sum"))
    return aggregated[aggregated["value"] > threshold].sort_values("value", ascending=False)


# ---------------------------------------------------------------------------
# v4: intermediate vars - explicit named DataFrames for each step
# ---------------------------------------------------------------------------


def q11_v4_expression_impl(ctx: DataFrameContext) -> Any:
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(11)
    nation_name = params["nation_name"]
    fraction = params["fraction"]

    # Step 1: join partsupp and supplier
    ps_with_sup = partsupp.join(supplier, left_on="ps_suppkey", right_on="s_suppkey")
    # Step 2: join with nation and filter
    with_nation = ps_with_sup.join(nation, left_on="s_nationkey", right_on="n_nationkey")
    nation_only = with_nation.filter(col("n_name") == lit(nation_name))
    # Step 3: compute value
    nation_stock = nation_only.with_columns((col("ps_supplycost") * col("ps_availqty")).alias("value"))
    # Step 4: compute total and threshold
    total_value = ctx.scalar(nation_stock.select(col("value").sum().alias("total")))
    threshold = total_value * fraction
    # Step 5: aggregate and filter
    aggregated = nation_stock.group_by("ps_partkey").agg(col("value").sum().alias("value"))
    above_threshold = aggregated.filter(col("value") > lit(threshold))
    return above_threshold.sort("value", descending=True)


def q11_v4_pandas_impl(ctx: DataFrameContext) -> Any:
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(11)
    nation_name = params["nation_name"]
    fraction = params["fraction"]

    ps_with_sup = partsupp.merge(supplier, left_on="ps_suppkey", right_on="s_suppkey")
    with_nation = ps_with_sup.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    nation_only = with_nation[with_nation["n_name"] == nation_name].copy()
    nation_only["value"] = nation_only["ps_supplycost"] * nation_only["ps_availqty"]

    total_value = nation_only["value"].sum()
    total_value = total_value.compute() if hasattr(total_value, "compute") else total_value
    threshold = total_value * fraction

    aggregated = nation_only.groupby("ps_partkey", as_index=False).agg(value=("value", "sum"))
    return aggregated[aggregated["value"] > threshold].sort_values("value", ascending=False)


# ---------------------------------------------------------------------------
# v5: pre-compute derived - add value column before total calculation
# ---------------------------------------------------------------------------


def q11_v5_expression_impl(ctx: DataFrameContext) -> Any:
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(11)
    nation_name = params["nation_name"]
    fraction = params["fraction"]

    # Pre-compute value column early
    nation_stock = (
        partsupp.with_columns((col("ps_supplycost") * col("ps_availqty")).alias("value"))
        .join(supplier, left_on="ps_suppkey", right_on="s_suppkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .filter(col("n_name") == lit(nation_name))
    )

    total_value = ctx.scalar(nation_stock.select(col("value").sum().alias("total")))
    threshold = total_value * fraction

    return (
        nation_stock.group_by("ps_partkey")
        .agg(col("value").sum().alias("value"))
        .filter(col("value") > lit(threshold))
        .sort("value", descending=True)
    )


def q11_v5_pandas_impl(ctx: DataFrameContext) -> Any:
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(11)
    nation_name = params["nation_name"]
    fraction = params["fraction"]

    # Pre-compute value before joining
    partsupp_copy = partsupp.copy()
    partsupp_copy["value"] = partsupp_copy["ps_supplycost"] * partsupp_copy["ps_availqty"]

    joined = partsupp_copy.merge(supplier, left_on="ps_suppkey", right_on="s_suppkey")
    joined = joined.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    joined = joined[joined["n_name"] == nation_name]

    total_value = joined["value"].sum()
    total_value = total_value.compute() if hasattr(total_value, "compute") else total_value
    threshold = total_value * fraction

    aggregated = joined.groupby("ps_partkey", as_index=False).agg(value=("value", "sum"))
    return aggregated[aggregated["value"] > threshold].sort_values("value", ascending=False)


# ---------------------------------------------------------------------------
# v6: chained style
# ---------------------------------------------------------------------------


def q11_v6_expression_impl(ctx: DataFrameContext) -> Any:
    col = ctx.col
    lit = ctx.lit
    p = get_tpch_parameters(11)

    nation_stock = (
        ctx.get_table("partsupp")
        .join(ctx.get_table("supplier"), left_on="ps_suppkey", right_on="s_suppkey")
        .join(ctx.get_table("nation"), left_on="s_nationkey", right_on="n_nationkey")
        .filter(col("n_name") == lit(p["nation_name"]))
        .with_columns((col("ps_supplycost") * col("ps_availqty")).alias("value"))
    )
    total_value = ctx.scalar(nation_stock.select(col("value").sum().alias("total")))
    threshold = total_value * p["fraction"]
    return (
        nation_stock.group_by("ps_partkey")
        .agg(col("value").sum().alias("value"))
        .filter(col("value") > lit(threshold))
        .sort("value", descending=True)
    )


def q11_v6_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q11_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v7: join reorder - start from nation→supplier→partsupp
# ---------------------------------------------------------------------------


def q11_v7_expression_impl(ctx: DataFrameContext) -> Any:
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(11)
    nation_name = params["nation_name"]
    fraction = params["fraction"]

    # Reordered: nation → supplier → partsupp
    germany_suppliers = nation.filter(col("n_name") == lit(nation_name)).join(
        supplier, left_on="n_nationkey", right_on="s_nationkey"
    )

    nation_stock = germany_suppliers.join(partsupp, left_on="s_suppkey", right_on="ps_suppkey").with_columns(
        (col("ps_supplycost") * col("ps_availqty")).alias("value")
    )

    total_value = ctx.scalar(nation_stock.select(col("value").sum().alias("total")))
    threshold = total_value * fraction

    return (
        nation_stock.group_by("ps_partkey")
        .agg(col("value").sum().alias("value"))
        .filter(col("value") > lit(threshold))
        .sort("value", descending=True)
    )


def q11_v7_pandas_impl(ctx: DataFrameContext) -> Any:
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(11)
    nation_name = params["nation_name"]
    fraction = params["fraction"]

    # Reordered: nation → supplier → partsupp
    germany_nation = nation[nation["n_name"] == nation_name]
    germany_suppliers = germany_nation.merge(supplier, left_on="n_nationkey", right_on="s_nationkey")
    joined = germany_suppliers.merge(partsupp, left_on="s_suppkey", right_on="ps_suppkey").copy()
    joined["value"] = joined["ps_supplycost"] * joined["ps_availqty"]

    total_value = joined["value"].sum()
    total_value = total_value.compute() if hasattr(total_value, "compute") else total_value
    threshold = total_value * fraction

    aggregated = joined.groupby("ps_partkey", as_index=False).agg(value=("value", "sum"))
    return aggregated[aggregated["value"] > threshold].sort_values("value", ascending=False)


# ---------------------------------------------------------------------------
# v8: filter combination - apply nation name filter as part of join condition
# ---------------------------------------------------------------------------


def q11_v8_expression_impl(ctx: DataFrameContext) -> Any:
    return q11_v2_expression_impl(ctx)


def q11_v8_pandas_impl(ctx: DataFrameContext) -> Any:
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(11)
    nation_name = params["nation_name"]
    fraction = params["fraction"]

    joined = partsupp.merge(supplier, left_on="ps_suppkey", right_on="s_suppkey")
    joined = joined.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    # Combined mask for nation filter
    nation_mask = joined["n_name"] == nation_name
    joined = joined[nation_mask].copy()
    joined["value"] = joined["ps_supplycost"] * joined["ps_availqty"]

    total_value = joined["value"].sum()
    total_value = total_value.compute() if hasattr(total_value, "compute") else total_value
    threshold = total_value * fraction

    aggregated = joined.groupby("ps_partkey", as_index=False).agg(value=("value", "sum"))
    return aggregated[aggregated["value"] > threshold].sort_values("value", ascending=False)


# ---------------------------------------------------------------------------
# v9: explicit sort
# ---------------------------------------------------------------------------


def q11_v9_expression_impl(ctx: DataFrameContext) -> Any:
    return _q11_expr_base(ctx)


def q11_v9_pandas_impl(ctx: DataFrameContext) -> Any:
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(11)
    nation_name = params["nation_name"]
    fraction = params["fraction"]

    joined = partsupp.merge(supplier, left_on="ps_suppkey", right_on="s_suppkey")
    joined = joined.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    joined = joined[joined["n_name"] == nation_name].copy()
    joined["value"] = joined["ps_supplycost"] * joined["ps_availqty"]

    total_value = joined["value"].sum()
    total_value = total_value.compute() if hasattr(total_value, "compute") else total_value
    threshold = total_value * fraction

    aggregated = joined.groupby("ps_partkey", as_index=False).agg(value=("value", "sum"))
    return aggregated[aggregated["value"] > threshold].sort_values("value", ascending=False)


# ---------------------------------------------------------------------------
# v10: alternative formula - value = availqty * supplycost (commuted)
# ---------------------------------------------------------------------------


def q11_v10_expression_impl(ctx: DataFrameContext) -> Any:
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(11)
    nation_name = params["nation_name"]
    fraction = params["fraction"]

    # Commuted: availqty * supplycost
    nation_stock = (
        partsupp.join(supplier, left_on="ps_suppkey", right_on="s_suppkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .filter(col("n_name") == lit(nation_name))
        .with_columns((col("ps_availqty") * col("ps_supplycost")).alias("value"))
    )

    total_value = ctx.scalar(nation_stock.select(col("value").sum().alias("total")))
    threshold = total_value * fraction

    return (
        nation_stock.group_by("ps_partkey")
        .agg(col("value").sum().alias("value"))
        .filter(col("value") > lit(threshold))
        .sort("value", descending=True)
    )


def q11_v10_pandas_impl(ctx: DataFrameContext) -> Any:
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(11)
    nation_name = params["nation_name"]
    fraction = params["fraction"]

    joined = partsupp.merge(supplier, left_on="ps_suppkey", right_on="s_suppkey")
    joined = joined.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    joined = joined[joined["n_name"] == nation_name].copy()
    # Commuted: availqty * supplycost
    joined["value"] = joined["ps_availqty"] * joined["ps_supplycost"]

    total_value = joined["value"].sum()
    total_value = total_value.compute() if hasattr(total_value, "compute") else total_value
    threshold = total_value * fraction

    aggregated = joined.groupby("ps_partkey", as_index=False).agg(value=("value", "sum"))
    return aggregated[aggregated["value"] > threshold].sort_values("value", ascending=False)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

Q11_VARIANTS = build_yaml_variants(__file__, globals(), 11, JOIN_AGG_SUBQUERY)
