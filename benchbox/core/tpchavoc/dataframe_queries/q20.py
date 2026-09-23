"""TPC-Havoc DataFrame variants for Q20.

Q20 is a semi-join promotion query: parts matching a color prefix, a
per-(part,supplier) shipped-quantity threshold, and suppliers with stock
above that threshold. The variants keep the canonical output while
varying the semi-join structure around threshold-first ordering,
join-order swaps, semi-vs-inner formulations, and filter pushdown.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.tpch.dataframe_queries import (
    get_query as get_tpch_query,
    get_tpch_parameters,
    q20_expression_impl as _q20_expr_base,
    q20_pandas_impl as _q20_pandas_base,
)
from benchbox.core.tpchavoc.dataframe_queries.loader import build_variants

VariantImpl = Callable[[DataFrameContext], Any]

_DESCRIPTIONS = [
    "Baseline: direct delegation to TPC-H Q20 implementation",
    "Threshold-first: aggregate shipped quantities before filtering forest parts",
    "Join-order swap: partsupp-shipped join before the forest semi-join",
    "Inner-plus-unique: inner joins with deduplication instead of semi-joins",
    "Column prune: select only needed columns before each join",
    "Nation-first: filter the supplier-nation dimension before the fact joins",
    "Chained style: maximum method chaining, no named intermediates",
    "Pushdown-first: date and color predicates before any aggregation",
    "Threshold materialized: with_columns half-quantity after the aggregation",
    "Distinct-via-groupby: group-by aggregation instead of unique for suppliers",
]


def _q20_expr_threshold(lineitem: Any, col: Any, lit: Any, start_date: str, end_date: str) -> Any:
    return (
        lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
        .group_by("l_partkey", "l_suppkey")
        .agg((col("l_quantity").sum() * lit(0.5)).alias("threshold"))
    )


def _q20_expr_forest(part: Any, col: Any, color_prefix: str) -> Any:
    return part.filter(col("p_name").str.starts_with(color_prefix)).select("p_partkey")


def _q20_expr_main(
    supplier: Any, nation: Any, excess: Any, col: Any, lit: Any, nation_name: str, *, inner: bool = False
) -> Any:
    supp_nation = supplier.join(nation, left_on="s_nationkey", right_on="n_nationkey").filter(
        col("n_name") == lit(nation_name)
    )
    if inner:
        return (
            supp_nation.join(excess, left_on="s_suppkey", right_on="ps_suppkey")
            .select("s_name", "s_address")
            .unique()
            .sort("s_name")
        )
    return (
        supp_nation.join(excess, left_on="s_suppkey", right_on="ps_suppkey", how="semi")
        .select("s_name", "s_address")
        .sort("s_name")
    )


def _make_q20_expression_impl(variant: int) -> VariantImpl:
    def impl(ctx: DataFrameContext) -> Any:
        if variant == 1:
            return _q20_expr_base(ctx)

        col = ctx.col
        lit = ctx.lit
        params = get_tpch_parameters(20)
        color_prefix = params["color_prefix"]
        nation_name = params["nation_name"]
        start_date = params["start_date"]
        end_date = params["end_date"]
        supplier = ctx.get_table("supplier")
        nation = ctx.get_table("nation")
        partsupp = ctx.get_table("partsupp")
        part = ctx.get_table("part")
        lineitem = ctx.get_table("lineitem")

        if variant == 2:
            shipped_qty = _q20_expr_threshold(lineitem, col, lit, start_date, end_date)
            forest_parts = _q20_expr_forest(part, col, color_prefix)
            excess = (
                partsupp.join(forest_parts, left_on="ps_partkey", right_on="p_partkey", how="semi")
                .join(shipped_qty, left_on=["ps_partkey", "ps_suppkey"], right_on=["l_partkey", "l_suppkey"])
                .filter(col("ps_availqty") > col("threshold"))
                .select("ps_suppkey")
                .unique()
            )
            return _q20_expr_main(supplier, nation, excess, col, lit, nation_name)

        if variant == 3:
            forest_parts = _q20_expr_forest(part, col, color_prefix)
            shipped_qty = _q20_expr_threshold(lineitem, col, lit, start_date, end_date)
            stocked = partsupp.join(
                shipped_qty, left_on=["ps_partkey", "ps_suppkey"], right_on=["l_partkey", "l_suppkey"]
            ).filter(col("ps_availqty") > col("threshold"))
            excess = (
                stocked.join(forest_parts, left_on="ps_partkey", right_on="p_partkey", how="semi")
                .select("ps_suppkey")
                .unique()
            )
            return _q20_expr_main(supplier, nation, excess, col, lit, nation_name)

        if variant == 4:
            forest_parts = _q20_expr_forest(part, col, color_prefix)
            shipped_qty = _q20_expr_threshold(lineitem, col, lit, start_date, end_date)
            excess = (
                partsupp.join(forest_parts, left_on="ps_partkey", right_on="p_partkey")
                .select("ps_partkey", "ps_suppkey", "ps_availqty")
                .unique()
                .join(shipped_qty, left_on=["ps_partkey", "ps_suppkey"], right_on=["l_partkey", "l_suppkey"])
                .filter(col("ps_availqty") > col("threshold"))
                .select("ps_suppkey")
                .unique()
            )
            return _q20_expr_main(supplier, nation, excess, col, lit, nation_name, inner=True)

        if variant == 5:
            forest_parts = _q20_expr_forest(part, col, color_prefix)
            shipped_qty = _q20_expr_threshold(
                lineitem.select("l_partkey", "l_suppkey", "l_quantity", "l_shipdate"), col, lit, start_date, end_date
            )
            excess = (
                partsupp.select("ps_partkey", "ps_suppkey", "ps_availqty")
                .join(forest_parts, left_on="ps_partkey", right_on="p_partkey", how="semi")
                .join(shipped_qty, left_on=["ps_partkey", "ps_suppkey"], right_on=["l_partkey", "l_suppkey"])
                .filter(col("ps_availqty") > col("threshold"))
                .select("ps_suppkey")
                .unique()
            )
            return _q20_expr_main(
                supplier.select("s_suppkey", "s_nationkey", "s_name", "s_address"),
                nation.select("n_nationkey", "n_name"),
                excess,
                col,
                lit,
                nation_name,
            )

        if variant == 6:
            supp_nation = (
                supplier.join(nation, left_on="s_nationkey", right_on="n_nationkey")
                .filter(col("n_name") == lit(nation_name))
                .select("s_suppkey", "s_name", "s_address")
            )
            forest_parts = _q20_expr_forest(part, col, color_prefix)
            shipped_qty = _q20_expr_threshold(lineitem, col, lit, start_date, end_date)
            excess = (
                partsupp.join(forest_parts, left_on="ps_partkey", right_on="p_partkey", how="semi")
                .join(shipped_qty, left_on=["ps_partkey", "ps_suppkey"], right_on=["l_partkey", "l_suppkey"])
                .filter(col("ps_availqty") > col("threshold"))
                .select("ps_suppkey")
                .unique()
            )
            return (
                supp_nation.join(excess, left_on="s_suppkey", right_on="ps_suppkey", how="semi")
                .select("s_name", "s_address")
                .sort("s_name")
            )

        if variant == 7:
            forest = part.filter(col("p_name").str.starts_with(color_prefix)).select("p_partkey")
            shipped = (
                lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
                .group_by("l_partkey", "l_suppkey")
                .agg((col("l_quantity").sum() * lit(0.5)).alias("threshold"))
            )
            return (
                supplier.join(nation, left_on="s_nationkey", right_on="n_nationkey")
                .filter(col("n_name") == lit(nation_name))
                .join(
                    partsupp.join(forest, left_on="ps_partkey", right_on="p_partkey", how="semi")
                    .join(shipped, left_on=["ps_partkey", "ps_suppkey"], right_on=["l_partkey", "l_suppkey"])
                    .filter(col("ps_availqty") > col("threshold"))
                    .select("ps_suppkey")
                    .unique(),
                    left_on="s_suppkey",
                    right_on="ps_suppkey",
                    how="semi",
                )
                .select("s_name", "s_address")
                .sort("s_name")
            )

        if variant == 8:
            dated = lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
            forest_parts = _q20_expr_forest(part, col, color_prefix)
            shipped_qty = dated.group_by("l_partkey", "l_suppkey").agg(
                (col("l_quantity").sum() * lit(0.5)).alias("threshold")
            )
            excess = (
                partsupp.join(forest_parts, left_on="ps_partkey", right_on="p_partkey", how="semi")
                .join(shipped_qty, left_on=["ps_partkey", "ps_suppkey"], right_on=["l_partkey", "l_suppkey"])
                .filter(col("ps_availqty") > col("threshold"))
                .select("ps_suppkey")
                .unique()
            )
            return _q20_expr_main(supplier, nation, excess, col, lit, nation_name)

        if variant == 9:
            forest_parts = _q20_expr_forest(part, col, color_prefix)
            shipped_qty = (
                lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
                .group_by("l_partkey", "l_suppkey")
                .agg(col("l_quantity").sum().alias("total_qty"))
                .with_columns((col("total_qty") * lit(0.5)).alias("threshold"))
            )
            excess = (
                partsupp.join(forest_parts, left_on="ps_partkey", right_on="p_partkey", how="semi")
                .join(shipped_qty, left_on=["ps_partkey", "ps_suppkey"], right_on=["l_partkey", "l_suppkey"])
                .filter(col("ps_availqty") > col("threshold"))
                .select("ps_suppkey")
                .unique()
            )
            return _q20_expr_main(supplier, nation, excess, col, lit, nation_name)

        forest_parts = _q20_expr_forest(part, col, color_prefix)
        shipped_qty = _q20_expr_threshold(lineitem, col, lit, start_date, end_date)
        excess = (
            partsupp.join(forest_parts, left_on="ps_partkey", right_on="p_partkey", how="semi")
            .join(shipped_qty, left_on=["ps_partkey", "ps_suppkey"], right_on=["l_partkey", "l_suppkey"])
            .filter(col("ps_availqty") > col("threshold"))
            .group_by("ps_suppkey")
            .agg(col("ps_partkey").count().alias("n_parts"))
            .select("ps_suppkey")
        )
        return _q20_expr_main(supplier, nation, excess, col, lit, nation_name)

    impl.__name__ = f"q20_v{variant}_expression_impl"
    impl.__qualname__ = impl.__name__
    return impl


def _q20_pandas_threshold(lineitem: Any, start_date: str, end_date: str) -> Any:
    filtered = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)]
    grouped = filtered.groupby(["l_partkey", "l_suppkey"], as_index=False).agg(threshold=("l_quantity", "sum"))
    grouped["threshold"] = grouped["threshold"] * 0.5
    return grouped


def _make_q20_pandas_impl(variant: int) -> VariantImpl:
    def impl(ctx: DataFrameContext) -> Any:
        if variant == 1:
            return _q20_pandas_base(ctx)

        supplier = ctx.get_table("supplier")
        nation = ctx.get_table("nation")
        partsupp = ctx.get_table("partsupp")
        part = ctx.get_table("part")
        lineitem = ctx.get_table("lineitem")
        params = get_tpch_parameters(20)
        color_prefix = params["color_prefix"]
        nation_name = params["nation_name"]
        start_date = params["start_date"]
        end_date = params["end_date"]

        forest_keys = list(part[part["p_name"].str.startswith(color_prefix)]["p_partkey"])

        def _main(excess_suppliers: list, *, inner: bool = False, nation_first: bool = False) -> Any:
            supp_nation = supplier.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
            if nation_first:
                supp_nation = supp_nation[supp_nation["n_name"] == nation_name]
            if inner:
                merged = supp_nation.merge(
                    supplier[supplier["s_suppkey"].isin(excess_suppliers)][["s_suppkey"]],
                    on="s_suppkey",
                )
                merged = merged[merged["n_name"] == nation_name]
                return merged.drop_duplicates(subset=["s_name", "s_address"])[["s_name", "s_address"]].sort_values(
                    "s_name"
                )
            if nation_first:
                return supp_nation[supp_nation["s_suppkey"].isin(excess_suppliers)][
                    ["s_name", "s_address"]
                ].sort_values("s_name")
            return supp_nation[
                (supp_nation["n_name"] == nation_name) & (supp_nation["s_suppkey"].isin(excess_suppliers))
            ][["s_name", "s_address"]].sort_values("s_name")

        def _excess(frame_ps: Any, shipped: Any) -> list:
            joined = frame_ps.merge(shipped, left_on=["ps_partkey", "ps_suppkey"], right_on=["l_partkey", "l_suppkey"])
            return list(joined[joined["ps_availqty"] > joined["threshold"]]["ps_suppkey"].unique())

        if variant == 2:
            shipped_qty = _q20_pandas_threshold(lineitem, start_date, end_date)
            return _main(_excess(partsupp[partsupp["ps_partkey"].isin(forest_keys)], shipped_qty))

        if variant == 3:
            shipped_qty = _q20_pandas_threshold(lineitem, start_date, end_date)
            stocked = partsupp.merge(
                shipped_qty, left_on=["ps_partkey", "ps_suppkey"], right_on=["l_partkey", "l_suppkey"]
            )
            stocked = stocked[stocked["ps_availqty"] > stocked["threshold"]]
            return _main(list(stocked[stocked["ps_partkey"].isin(forest_keys)]["ps_suppkey"].unique()))

        if variant == 4:
            shipped_qty = _q20_pandas_threshold(lineitem, start_date, end_date)
            forest_ps = partsupp[partsupp["ps_partkey"].isin(forest_keys)]
            return _main(_excess(forest_ps, shipped_qty), inner=True)

        if variant == 5:
            shipped_qty = _q20_pandas_threshold(
                lineitem[["l_partkey", "l_suppkey", "l_quantity", "l_shipdate"]], start_date, end_date
            )
            forest_ps = partsupp[partsupp["ps_partkey"].isin(forest_keys)][["ps_partkey", "ps_suppkey", "ps_availqty"]]
            return _main(_excess(forest_ps, shipped_qty))

        if variant == 6:
            shipped_qty = _q20_pandas_threshold(lineitem, start_date, end_date)
            forest_ps = partsupp[partsupp["ps_partkey"].isin(forest_keys)]
            return _main(_excess(forest_ps, shipped_qty), nation_first=True)

        if variant == 7:
            shipped_qty = _q20_pandas_threshold(lineitem, start_date, end_date)
            excess = _excess(partsupp[partsupp["ps_partkey"].isin(forest_keys)], shipped_qty)
            joined = supplier.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
            return joined[(joined["n_name"] == nation_name) & (joined["s_suppkey"].isin(excess))][
                ["s_name", "s_address"]
            ].sort_values("s_name")

        if variant == 8:
            dated = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)]
            shipped_qty = dated.groupby(["l_partkey", "l_suppkey"], as_index=False).agg(threshold=("l_quantity", "sum"))
            shipped_qty["threshold"] = shipped_qty["threshold"] * 0.5
            forest_ps = partsupp[partsupp["ps_partkey"].isin(forest_keys)]
            return _main(_excess(forest_ps, shipped_qty))

        if variant == 9:
            filtered = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)]
            totals = filtered.groupby(["l_partkey", "l_suppkey"], as_index=False).agg(total=("l_quantity", "sum"))
            totals["threshold"] = totals["total"] * 0.5
            forest_ps = partsupp[partsupp["ps_partkey"].isin(forest_keys)]
            return _main(_excess(forest_ps, totals))

        # variant 10: distinct-via-groupby
        shipped_qty = _q20_pandas_threshold(lineitem, start_date, end_date)
        forest_ps = partsupp[partsupp["ps_partkey"].isin(forest_keys)]
        joined = forest_ps.merge(shipped_qty, left_on=["ps_partkey", "ps_suppkey"], right_on=["l_partkey", "l_suppkey"])
        over = joined[joined["ps_availqty"] > joined["threshold"]]
        return _main(list(over.groupby("ps_suppkey").size().index))

    impl.__name__ = f"q20_v{variant}_pandas_impl"
    impl.__qualname__ = impl.__name__
    return impl


_Q20_BASE = get_tpch_query("Q20")

Q20_VARIANTS = build_variants(
    20,
    [(_make_q20_expression_impl(v), _make_q20_pandas_impl(v)) for v in range(1, 11)],
    _DESCRIPTIONS,
    _Q20_BASE.categories,
)
