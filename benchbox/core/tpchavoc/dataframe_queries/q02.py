"""TPC-Havoc DataFrame variants for Q2.

Implements 10 structurally diverse variants of TPC-H Q2 (Minimum Cost Supplier).
Q2 involves a correlated subquery pattern: find the min-cost supplier per part in a region.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q2_expression_impl as _q2_expr_base,
    q2_pandas_impl as _q2_pandas_base,
)

# ---------------------------------------------------------------------------
# v1: baseline
# ---------------------------------------------------------------------------


def q2_v1_expression_impl(ctx: DataFrameContext) -> Any:
    return _q2_expr_base(ctx)


def q2_v1_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q2_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v2: pre-filter - filter part and region tables before joining
# ---------------------------------------------------------------------------


def q2_v2_expression_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    partsupp = ctx.get_table("partsupp")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(2)
    size = params["size"]
    type_suffix = params["type_suffix"]
    region_name = params["region_name"]

    # Pre-filter part and region before any join
    filtered_part = part.filter((col("p_size") == lit(size)) & col("p_type").str.ends_with(type_suffix))
    filtered_region = region.filter(col("r_name") == lit(region_name))

    # Build min cost subquery
    min_cost_per_part = (
        partsupp.join(supplier, left_on="ps_suppkey", right_on="s_suppkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .join(filtered_region, left_on="n_regionkey", right_on="r_regionkey")
        .group_by("ps_partkey")
        .agg(col("ps_supplycost").min().alias("min_cost"))
    )

    result = (
        filtered_part.join(partsupp, left_on="p_partkey", right_on="ps_partkey")
        .join(supplier, left_on="ps_suppkey", right_on="s_suppkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .join(filtered_region, left_on="n_regionkey", right_on="r_regionkey")
        .join(min_cost_per_part, left_on="p_partkey", right_on="ps_partkey")
        .filter(col("ps_supplycost") == col("min_cost"))
        .select(
            "s_acctbal",
            "s_name",
            "n_name",
            "p_partkey",
            "p_mfgr",
            "s_address",
            "s_phone",
            "s_comment",
        )
        .sort(["s_acctbal", "n_name", "s_name", "p_partkey"], descending=[True, False, False, False])
        .limit(100)
    )
    return result


def q2_v2_pandas_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    partsupp = ctx.get_table("partsupp")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(2)
    size = params["size"]
    type_suffix = params["type_suffix"]
    region_name = params["region_name"]

    # Pre-filter
    filtered_part = part[(part["p_size"] == size) & (part["p_type"].str.endswith(type_suffix))]
    filtered_region = region[region["r_name"] == region_name]

    # Min cost subquery
    region_nations = filtered_region.merge(nation, left_on="r_regionkey", right_on="n_regionkey")
    region_suppliers = region_nations.merge(supplier, left_on="n_nationkey", right_on="s_nationkey")
    region_partsupp = region_suppliers.merge(partsupp, left_on="s_suppkey", right_on="ps_suppkey")
    min_cost = region_partsupp.groupby("ps_partkey", as_index=False).agg(min_cost=("ps_supplycost", "min"))

    # Main query
    joined = filtered_part.merge(partsupp, left_on="p_partkey", right_on="ps_partkey")
    joined = joined.merge(supplier, left_on="ps_suppkey", right_on="s_suppkey")
    joined = joined.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    joined = joined.merge(filtered_region, left_on="n_regionkey", right_on="r_regionkey")
    joined = joined.merge(min_cost, left_on="p_partkey", right_on="ps_partkey")
    joined = joined[joined["ps_supplycost"] == joined["min_cost"]]

    result = (
        joined[["s_acctbal", "s_name", "n_name", "p_partkey", "p_mfgr", "s_address", "s_phone", "s_comment"]]
        .sort_values(["s_acctbal", "n_name", "s_name", "p_partkey"], ascending=[False, True, True, True])
        .head(100)
    )
    return result


# ---------------------------------------------------------------------------
# v3: column prune - project subquery to only needed columns early
# ---------------------------------------------------------------------------


def q3_v3_expression_impl_q2(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    partsupp = ctx.get_table("partsupp")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(2)
    size = params["size"]
    type_suffix = params["type_suffix"]
    region_name = params["region_name"]

    # Min cost subquery with pruned columns
    min_cost_per_part = (
        partsupp.select("ps_suppkey", "ps_partkey", "ps_supplycost")
        .join(supplier.select("s_suppkey", "s_nationkey"), left_on="ps_suppkey", right_on="s_suppkey")
        .join(nation.select("n_nationkey", "n_regionkey"), left_on="s_nationkey", right_on="n_nationkey")
        .join(
            region.filter(col("r_name") == lit(region_name)).select("r_regionkey"),
            left_on="n_regionkey",
            right_on="r_regionkey",
        )
        .group_by("ps_partkey")
        .agg(col("ps_supplycost").min().alias("min_cost"))
    )

    result = (
        part.filter((col("p_size") == lit(size)) & col("p_type").str.ends_with(type_suffix))
        .join(partsupp, left_on="p_partkey", right_on="ps_partkey")
        .join(supplier, left_on="ps_suppkey", right_on="s_suppkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .join(region.filter(col("r_name") == lit(region_name)), left_on="n_regionkey", right_on="r_regionkey")
        .join(min_cost_per_part, left_on="p_partkey", right_on="ps_partkey")
        .filter(col("ps_supplycost") == col("min_cost"))
        .select("s_acctbal", "s_name", "n_name", "p_partkey", "p_mfgr", "s_address", "s_phone", "s_comment")
        .sort(["s_acctbal", "n_name", "s_name", "p_partkey"], descending=[True, False, False, False])
        .limit(100)
    )
    return result


def q2_v3_expression_impl(ctx: DataFrameContext) -> Any:
    return q3_v3_expression_impl_q2(ctx)


def q2_v3_pandas_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    partsupp = ctx.get_table("partsupp")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(2)
    size = params["size"]
    type_suffix = params["type_suffix"]
    region_name = params["region_name"]

    # Pruned columns for subquery
    partsupp_pruned = partsupp[["ps_suppkey", "ps_partkey", "ps_supplycost"]]
    supplier_pruned = supplier[["s_suppkey", "s_nationkey"]]
    nation_pruned = nation[["n_nationkey", "n_regionkey"]]
    region_filtered = region[region["r_name"] == region_name][["r_regionkey"]]

    sub = partsupp_pruned.merge(supplier_pruned, left_on="ps_suppkey", right_on="s_suppkey")
    sub = sub.merge(nation_pruned, left_on="s_nationkey", right_on="n_nationkey")
    sub = sub.merge(region_filtered, left_on="n_regionkey", right_on="r_regionkey")
    min_cost = sub.groupby("ps_partkey", as_index=False).agg(min_cost=("ps_supplycost", "min"))

    filtered_part = part[(part["p_size"] == size) & (part["p_type"].str.endswith(type_suffix))]
    joined = filtered_part.merge(partsupp, left_on="p_partkey", right_on="ps_partkey")
    joined = joined.merge(supplier, left_on="ps_suppkey", right_on="s_suppkey")
    joined = joined.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    joined = joined.merge(region[region["r_name"] == region_name], left_on="n_regionkey", right_on="r_regionkey")
    joined = joined.merge(min_cost, left_on="p_partkey", right_on="ps_partkey")
    joined = joined[joined["ps_supplycost"] == joined["min_cost"]]
    return (
        joined[["s_acctbal", "s_name", "n_name", "p_partkey", "p_mfgr", "s_address", "s_phone", "s_comment"]]
        .sort_values(["s_acctbal", "n_name", "s_name", "p_partkey"], ascending=[False, True, True, True])
        .head(100)
    )


# ---------------------------------------------------------------------------
# v4: intermediate vars - build each join as named step
# ---------------------------------------------------------------------------


def q2_v4_expression_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    partsupp = ctx.get_table("partsupp")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(2)
    size = params["size"]
    type_suffix = params["type_suffix"]
    region_name = params["region_name"]

    # Build region nations
    region_filtered = region.filter(col("r_name") == lit(region_name))
    nation_in_region = nation.join(region_filtered, left_on="n_regionkey", right_on="r_regionkey")
    suppliers_in_region = supplier.join(nation_in_region, left_on="s_nationkey", right_on="n_nationkey")

    # Min cost subquery
    min_cost_per_part = (
        partsupp.join(suppliers_in_region, left_on="ps_suppkey", right_on="s_suppkey")
        .group_by("ps_partkey")
        .agg(col("ps_supplycost").min().alias("min_cost"))
    )

    # Main query
    filtered_part = part.filter((col("p_size") == lit(size)) & col("p_type").str.ends_with(type_suffix))
    part_with_partsupp = filtered_part.join(partsupp, left_on="p_partkey", right_on="ps_partkey")
    with_supplier = part_with_partsupp.join(supplier, left_on="ps_suppkey", right_on="s_suppkey")
    with_nation = with_supplier.join(nation_in_region, left_on="s_nationkey", right_on="n_nationkey")
    with_min = with_nation.join(min_cost_per_part, left_on="p_partkey", right_on="ps_partkey")
    at_min_cost = with_min.filter(col("ps_supplycost") == col("min_cost"))
    result = (
        at_min_cost.select("s_acctbal", "s_name", "n_name", "p_partkey", "p_mfgr", "s_address", "s_phone", "s_comment")
        .sort(["s_acctbal", "n_name", "s_name", "p_partkey"], descending=[True, False, False, False])
        .limit(100)
    )
    return result


def q2_v4_pandas_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    partsupp = ctx.get_table("partsupp")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(2)
    size = params["size"]
    type_suffix = params["type_suffix"]
    region_name = params["region_name"]

    region_filtered = region[region["r_name"] == region_name]
    nation_in_region = nation.merge(region_filtered, left_on="n_regionkey", right_on="r_regionkey")
    suppliers_in_region = supplier.merge(nation_in_region, left_on="s_nationkey", right_on="n_nationkey")
    ps_with_sup = partsupp.merge(suppliers_in_region, left_on="ps_suppkey", right_on="s_suppkey")
    min_cost = ps_with_sup.groupby("ps_partkey", as_index=False).agg(min_cost=("ps_supplycost", "min"))

    filtered_part = part[(part["p_size"] == size) & (part["p_type"].str.endswith(type_suffix))]
    joined = filtered_part.merge(partsupp, left_on="p_partkey", right_on="ps_partkey")
    joined = joined.merge(supplier, left_on="ps_suppkey", right_on="s_suppkey")
    joined = joined.merge(nation_in_region, left_on="s_nationkey", right_on="n_nationkey")
    joined = joined.merge(min_cost, left_on="p_partkey", right_on="ps_partkey")
    joined = joined[joined["ps_supplycost"] == joined["min_cost"]]
    return (
        joined[["s_acctbal", "s_name", "n_name", "p_partkey", "p_mfgr", "s_address", "s_phone", "s_comment"]]
        .sort_values(["s_acctbal", "n_name", "s_name", "p_partkey"], ascending=[False, True, True, True])
        .head(100)
    )


# ---------------------------------------------------------------------------
# v5: pre-compute derived - compute value column in partsupp before groupby
# ---------------------------------------------------------------------------


def q2_v5_expression_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    partsupp = ctx.get_table("partsupp")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(2)
    size = params["size"]
    type_suffix = params["type_suffix"]
    region_name = params["region_name"]

    min_cost_per_part = (
        partsupp.join(supplier, left_on="ps_suppkey", right_on="s_suppkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .filter(col("r_name") == lit(region_name))
        .group_by("ps_partkey")
        .agg(col("ps_supplycost").min().alias("min_cost"))
    )

    result = (
        part.filter((col("p_size") == lit(size)) & col("p_type").str.ends_with(type_suffix))
        .join(partsupp, left_on="p_partkey", right_on="ps_partkey")
        .join(supplier, left_on="ps_suppkey", right_on="s_suppkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .filter(col("r_name") == lit(region_name))
        .join(min_cost_per_part, left_on="p_partkey", right_on="ps_partkey")
        .filter(col("ps_supplycost") == col("min_cost"))
        .select("s_acctbal", "s_name", "n_name", "p_partkey", "p_mfgr", "s_address", "s_phone", "s_comment")
        .sort(["s_acctbal", "n_name", "s_name", "p_partkey"], descending=[True, False, False, False])
        .limit(100)
    )
    return result


def q2_v5_pandas_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    partsupp = ctx.get_table("partsupp")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(2)
    size = params["size"]
    type_suffix = params["type_suffix"]
    region_name = params["region_name"]

    europe_region = region[region["r_name"] == region_name]
    europe_nations = europe_region.merge(nation, left_on="r_regionkey", right_on="n_regionkey")
    europe_suppliers = europe_nations.merge(supplier, left_on="n_nationkey", right_on="s_nationkey")
    supplier_parts = europe_suppliers.merge(partsupp, left_on="s_suppkey", right_on="ps_suppkey")
    # Pre-compute supply value
    supplier_parts = supplier_parts.copy()
    supplier_parts["supply_value"] = supplier_parts["ps_supplycost"]
    min_cost = supplier_parts.groupby("ps_partkey", as_index=False).agg(min_cost=("supply_value", "min"))

    filtered_part = part[(part["p_size"] == size) & (part["p_type"].str.endswith(type_suffix))]
    joined = filtered_part.merge(partsupp, left_on="p_partkey", right_on="ps_partkey")
    joined = joined.merge(supplier, left_on="ps_suppkey", right_on="s_suppkey")
    joined = joined.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    joined = joined.merge(region, left_on="n_regionkey", right_on="r_regionkey")
    joined = joined[joined["r_name"] == region_name]
    joined = joined.merge(min_cost, left_on="p_partkey", right_on="ps_partkey")
    joined = joined[joined["ps_supplycost"] == joined["min_cost"]]
    return (
        joined[["s_acctbal", "s_name", "n_name", "p_partkey", "p_mfgr", "s_address", "s_phone", "s_comment"]]
        .sort_values(["s_acctbal", "n_name", "s_name", "p_partkey"], ascending=[False, True, True, True])
        .head(100)
    )


# ---------------------------------------------------------------------------
# v6: chained style
# ---------------------------------------------------------------------------


def q2_v6_expression_impl(ctx: DataFrameContext) -> Any:
    col = ctx.col
    lit = ctx.lit
    p = get_tpch_parameters(2)
    size = p["size"]
    type_suffix = p["type_suffix"]
    region_name = p["region_name"]

    min_cost_per_part = (
        ctx.get_table("partsupp")
        .join(ctx.get_table("supplier"), left_on="ps_suppkey", right_on="s_suppkey")
        .join(ctx.get_table("nation"), left_on="s_nationkey", right_on="n_nationkey")
        .join(ctx.get_table("region"), left_on="n_regionkey", right_on="r_regionkey")
        .filter(col("r_name") == lit(region_name))
        .group_by("ps_partkey")
        .agg(col("ps_supplycost").min().alias("min_cost"))
    )
    return (
        ctx.get_table("part")
        .filter((col("p_size") == lit(size)) & col("p_type").str.ends_with(type_suffix))
        .join(ctx.get_table("partsupp"), left_on="p_partkey", right_on="ps_partkey")
        .join(ctx.get_table("supplier"), left_on="ps_suppkey", right_on="s_suppkey")
        .join(ctx.get_table("nation"), left_on="s_nationkey", right_on="n_nationkey")
        .join(ctx.get_table("region"), left_on="n_regionkey", right_on="r_regionkey")
        .filter(col("r_name") == lit(region_name))
        .join(min_cost_per_part, left_on="p_partkey", right_on="ps_partkey")
        .filter(col("ps_supplycost") == col("min_cost"))
        .select("s_acctbal", "s_name", "n_name", "p_partkey", "p_mfgr", "s_address", "s_phone", "s_comment")
        .sort(["s_acctbal", "n_name", "s_name", "p_partkey"], descending=[True, False, False, False])
        .limit(100)
    )


def q2_v6_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q2_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v7: join reorder - start subquery from nation→partsupp instead of partsupp→supplier
# ---------------------------------------------------------------------------


def q2_v7_expression_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    partsupp = ctx.get_table("partsupp")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(2)
    size = params["size"]
    type_suffix = params["type_suffix"]
    region_name = params["region_name"]

    # Reordered: start from region → nation → supplier → partsupp for subquery
    region_nation = region.filter(col("r_name") == lit(region_name)).join(
        nation, left_on="r_regionkey", right_on="n_regionkey"
    )
    region_suppliers = region_nation.join(supplier, left_on="n_nationkey", right_on="s_nationkey")
    min_cost_per_part = (
        region_suppliers.join(partsupp, left_on="s_suppkey", right_on="ps_suppkey")
        .group_by("ps_partkey")
        .agg(col("ps_supplycost").min().alias("min_cost"))
    )

    result = (
        part.filter((col("p_size") == lit(size)) & col("p_type").str.ends_with(type_suffix))
        .join(partsupp, left_on="p_partkey", right_on="ps_partkey")
        .join(supplier, left_on="ps_suppkey", right_on="s_suppkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .filter(col("r_name") == lit(region_name))
        .join(min_cost_per_part, left_on="p_partkey", right_on="ps_partkey")
        .filter(col("ps_supplycost") == col("min_cost"))
        .select("s_acctbal", "s_name", "n_name", "p_partkey", "p_mfgr", "s_address", "s_phone", "s_comment")
        .sort(["s_acctbal", "n_name", "s_name", "p_partkey"], descending=[True, False, False, False])
        .limit(100)
    )
    return result


def q2_v7_pandas_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    partsupp = ctx.get_table("partsupp")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(2)
    size = params["size"]
    type_suffix = params["type_suffix"]
    region_name = params["region_name"]

    # Reordered: region → nation → supplier → partsupp
    region_filtered = region[region["r_name"] == region_name]
    region_nation = region_filtered.merge(nation, left_on="r_regionkey", right_on="n_regionkey")
    region_suppliers = region_nation.merge(supplier, left_on="n_nationkey", right_on="s_nationkey")
    region_ps = region_suppliers.merge(partsupp, left_on="s_suppkey", right_on="ps_suppkey")
    min_cost = region_ps.groupby("ps_partkey", as_index=False).agg(min_cost=("ps_supplycost", "min"))

    filtered_part = part[(part["p_size"] == size) & (part["p_type"].str.endswith(type_suffix))]
    joined = filtered_part.merge(partsupp, left_on="p_partkey", right_on="ps_partkey")
    joined = joined.merge(supplier, left_on="ps_suppkey", right_on="s_suppkey")
    joined = joined.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    joined = joined.merge(region, left_on="n_regionkey", right_on="r_regionkey")
    joined = joined[joined["r_name"] == region_name]
    joined = joined.merge(min_cost, left_on="p_partkey", right_on="ps_partkey")
    joined = joined[joined["ps_supplycost"] == joined["min_cost"]]
    return (
        joined[["s_acctbal", "s_name", "n_name", "p_partkey", "p_mfgr", "s_address", "s_phone", "s_comment"]]
        .sort_values(["s_acctbal", "n_name", "s_name", "p_partkey"], ascending=[False, True, True, True])
        .head(100)
    )


# ---------------------------------------------------------------------------
# v8: filter combination - combined region+type filter in single predicate
# ---------------------------------------------------------------------------


def q2_v8_expression_impl(ctx: DataFrameContext) -> Any:
    return q2_v2_expression_impl(ctx)


def q2_v8_pandas_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    partsupp = ctx.get_table("partsupp")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(2)
    size = params["size"]
    type_suffix = params["type_suffix"]
    region_name = params["region_name"]

    europe_region = region[region["r_name"] == region_name]
    europe_nations = europe_region.merge(nation, left_on="r_regionkey", right_on="n_regionkey")
    europe_suppliers = europe_nations.merge(supplier, left_on="n_nationkey", right_on="s_nationkey")
    supplier_parts = europe_suppliers.merge(partsupp, left_on="s_suppkey", right_on="ps_suppkey")
    min_cost = supplier_parts.groupby("ps_partkey", as_index=False).agg(min_cost=("ps_supplycost", "min"))

    # Combined size+type filter in single boolean
    filtered_part = part[(part["p_size"] == size) & part["p_type"].str.endswith(type_suffix)]
    joined = filtered_part.merge(partsupp, left_on="p_partkey", right_on="ps_partkey")
    joined = joined.merge(supplier, left_on="ps_suppkey", right_on="s_suppkey")
    joined = joined.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    joined = joined.merge(region, left_on="n_regionkey", right_on="r_regionkey")
    joined = joined[joined["r_name"] == region_name]
    joined = joined.merge(min_cost, left_on="p_partkey", right_on="ps_partkey")
    joined = joined[joined["ps_supplycost"] == joined["min_cost"]]
    return (
        joined[["s_acctbal", "s_name", "n_name", "p_partkey", "p_mfgr", "s_address", "s_phone", "s_comment"]]
        .sort_values(["s_acctbal", "n_name", "s_name", "p_partkey"], ascending=[False, True, True, True])
        .head(100)
    )


# ---------------------------------------------------------------------------
# v9: explicit sort - pass descending flags and nulls_last explicitly
# ---------------------------------------------------------------------------


def q2_v9_expression_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    partsupp = ctx.get_table("partsupp")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(2)
    size = params["size"]
    type_suffix = params["type_suffix"]
    region_name = params["region_name"]

    min_cost_per_part = (
        partsupp.join(supplier, left_on="ps_suppkey", right_on="s_suppkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .filter(col("r_name") == lit(region_name))
        .group_by("ps_partkey")
        .agg(col("ps_supplycost").min().alias("min_cost"))
    )

    result = (
        part.filter((col("p_size") == lit(size)) & col("p_type").str.ends_with(type_suffix))
        .join(partsupp, left_on="p_partkey", right_on="ps_partkey")
        .join(supplier, left_on="ps_suppkey", right_on="s_suppkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .filter(col("r_name") == lit(region_name))
        .join(min_cost_per_part, left_on="p_partkey", right_on="ps_partkey")
        .filter(col("ps_supplycost") == col("min_cost"))
        .select("s_acctbal", "s_name", "n_name", "p_partkey", "p_mfgr", "s_address", "s_phone", "s_comment")
        .sort(
            ["s_acctbal", "n_name", "s_name", "p_partkey"],
            descending=[True, False, False, False],
        )
        .limit(100)
    )
    return result


def q2_v9_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q2_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v10: alternative formula - same logic, different subquery build order
# ---------------------------------------------------------------------------


def q2_v10_expression_impl(ctx: DataFrameContext) -> Any:
    return _q2_expr_base(ctx)


def q2_v10_pandas_impl(ctx: DataFrameContext) -> Any:
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    partsupp = ctx.get_table("partsupp")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(2)
    size = params["size"]
    type_suffix = params["type_suffix"]
    region_name = params["region_name"]

    # Alternative: build from part outward (part→partsupp→supplier→nation→region)
    filtered_part = part[(part["p_size"] == size) & (part["p_type"].str.endswith(type_suffix))]
    part_ps = filtered_part.merge(partsupp, left_on="p_partkey", right_on="ps_partkey")
    part_ps_s = part_ps.merge(supplier, left_on="ps_suppkey", right_on="s_suppkey")
    part_ps_s_n = part_ps_s.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    part_ps_s_n_r = part_ps_s_n.merge(region, left_on="n_regionkey", right_on="r_regionkey")
    in_region = part_ps_s_n_r[part_ps_s_n_r["r_name"] == region_name]

    # Min cost per part using the in-region data
    min_cost = in_region.groupby("p_partkey", as_index=False).agg(min_cost=("ps_supplycost", "min"))
    result_df = in_region.merge(min_cost, on="p_partkey")
    result_df = result_df[result_df["ps_supplycost"] == result_df["min_cost"]]
    return (
        result_df[["s_acctbal", "s_name", "n_name", "p_partkey", "p_mfgr", "s_address", "s_phone", "s_comment"]]
        .sort_values(["s_acctbal", "n_name", "s_name", "p_partkey"], ascending=[False, True, True, True])
        .head(100)
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_IMPL_PAIRS = [
    (q2_v1_expression_impl, q2_v1_pandas_impl),
    (q2_v2_expression_impl, q2_v2_pandas_impl),
    (q2_v3_expression_impl, q2_v3_pandas_impl),
    (q2_v4_expression_impl, q2_v4_pandas_impl),
    (q2_v5_expression_impl, q2_v5_pandas_impl),
    (q2_v6_expression_impl, q2_v6_pandas_impl),
    (q2_v7_expression_impl, q2_v7_pandas_impl),
    (q2_v8_expression_impl, q2_v8_pandas_impl),
    (q2_v9_expression_impl, q2_v9_pandas_impl),
    (q2_v10_expression_impl, q2_v10_pandas_impl),
]

_DESCRIPTIONS = [
    "Baseline: direct delegation to TPC-H Q2 implementation",
    "Pre-filter: filter part and region tables before joining",
    "Column prune: project subquery to only needed columns early",
    "Intermediate vars: named DataFrames for each join step",
    "Pre-compute derived: add supply_value column before min aggregation",
    "Chained style: maximum method chaining, no named intermediates",
    "Join reorder: subquery starts from region→nation→supplier→partsupp",
    "Filter combination: combined region+type filter in single predicate",
    "Explicit sort: descending=[True, False, False, False] with explicit flags",
    "Alternative formula: build min-cost subquery from part outward",
]

Q2_VARIANTS: list[DataFrameQuery] = [
    DataFrameQuery(
        query_id=f"Q2v{v}",
        query_name=f"TPC-H Q2 Variant {v}",
        description=_DESCRIPTIONS[v - 1],
        categories=[QueryCategory.JOIN, QueryCategory.SUBQUERY, QueryCategory.SORT],
        expression_impl=expr_impl,
        pandas_impl=pandas_impl,
    )
    for v, (expr_impl, pandas_impl) in enumerate(_IMPL_PAIRS, start=1)
]
