"""TPC-Havoc DataFrame variants for Q1.

Q1 is a single-table grouped aggregate. The variants below keep the existing
filter timing, projection, grouping-order, and formula differences explicit
while sharing the repeated aggregation scaffolding.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q1_expression_impl as _q1_expr_base,
    q1_pandas_impl as _q1_pandas_base,
)
from benchbox.core.tpchavoc.dataframe_queries.loader import AGG_GROUP_FILTER, build_variants

VariantImpl = Callable[[DataFrameContext], Any]

_RESULT_COLUMNS = [
    "l_returnflag",
    "l_linestatus",
    "sum_qty",
    "sum_base_price",
    "sum_disc_price",
    "sum_charge",
    "avg_qty",
    "avg_price",
    "avg_disc",
    "count_order",
]
_NEEDED_COLUMNS = [
    "l_returnflag",
    "l_linestatus",
    "l_quantity",
    "l_extendedprice",
    "l_discount",
    "l_tax",
    "l_orderkey",
    "l_shipdate",
]
_DESCRIPTIONS = [
    "Baseline: direct delegation to TPC-H Q1 implementation",
    "Pre-filter: apply date predicate before aggregation setup",
    "Column prune: select only needed columns before operations",
    "Intermediate vars: explicit DataFrames for filter, agg, sort steps",
    "Pre-compute derived: add disc_price/charge columns before groupby",
    "Chained style: maximum method chaining, no named intermediates",
    "Aggregation alternative: reversed group-by key order, re-sort correctly",
    "Filter combination: compound predicate with extra no-op guards",
    "Explicit sort: pass descending=[False, False] explicitly",
    "Alternative formula: price - price*disc instead of price*(1-disc)",
]


def _q1_expr_disc_price(ctx: DataFrameContext, *, alternate: bool = False) -> Any:
    col = ctx.col
    if alternate:
        return col("l_extendedprice") - col("l_extendedprice") * col("l_discount")
    return col("l_extendedprice") * (ctx.lit(1) - col("l_discount"))


def _q1_expr_charge(ctx: DataFrameContext, disc_price: Any) -> Any:
    return disc_price * (ctx.lit(1) + ctx.col("l_tax"))


def _q1_expr_aggregate(
    ctx: DataFrameContext,
    frame: Any,
    *,
    reversed_keys: bool = False,
    precomputed: bool = False,
    alternate_formula: bool = False,
    explicit_sort: bool = False,
    sort: bool = True,
) -> Any:
    col = ctx.col
    group_cols = ("l_linestatus", "l_returnflag") if reversed_keys else ("l_returnflag", "l_linestatus")
    disc_price = _q1_expr_disc_price(ctx, alternate=alternate_formula)
    charge = _q1_expr_charge(ctx, disc_price)
    sum_disc_price = (
        col("disc_price").sum().alias("sum_disc_price") if precomputed else disc_price.sum().alias("sum_disc_price")
    )
    sum_charge = col("charge").sum().alias("sum_charge") if precomputed else charge.sum().alias("sum_charge")
    result = frame.group_by(*group_cols).agg(
        col("l_quantity").sum().alias("sum_qty"),
        col("l_extendedprice").sum().alias("sum_base_price"),
        sum_disc_price,
        sum_charge,
        col("l_quantity").mean().alias("avg_qty"),
        col("l_extendedprice").mean().alias("avg_price"),
        col("l_discount").mean().alias("avg_disc"),
        col("l_orderkey").count().alias("count_order"),
    )
    if reversed_keys:
        result = result.select(*_RESULT_COLUMNS)
    if not sort:
        return result
    if explicit_sort:
        return result.sort(["l_returnflag", "l_linestatus"], descending=[False, False])
    return result.sort("l_returnflag", "l_linestatus")


def _make_q1_expression_impl(variant: int) -> VariantImpl:
    def impl(ctx: DataFrameContext) -> Any:
        if variant == 1:
            return _q1_expr_base(ctx)

        lineitem = ctx.get_table("lineitem")
        col = ctx.col
        lit = ctx.lit
        cutoff_date = get_tpch_parameters(1)["cutoff_date"]
        shipdate_filter = col("l_shipdate") <= lit(cutoff_date)

        if variant == 2:
            return _q1_expr_aggregate(ctx, lineitem.filter(shipdate_filter))

        if variant == 3:
            return _q1_expr_aggregate(ctx, lineitem.select(_NEEDED_COLUMNS).filter(shipdate_filter))

        if variant == 4:
            step1 = lineitem.filter(shipdate_filter)
            step2 = _q1_expr_aggregate(ctx, step1, sort=False)
            return step2.sort("l_returnflag", "l_linestatus")

        if variant == 5:
            disc_price = _q1_expr_disc_price(ctx)
            filtered = lineitem.filter(shipdate_filter).with_columns(
                disc_price.alias("disc_price"),
                _q1_expr_charge(ctx, disc_price).alias("charge"),
            )
            return _q1_expr_aggregate(ctx, filtered, precomputed=True)

        if variant == 6:
            return (
                ctx.get_table("lineitem")
                .filter(col("l_shipdate") <= lit(cutoff_date))
                .group_by("l_returnflag", "l_linestatus")
                .agg(
                    col("l_quantity").sum().alias("sum_qty"),
                    col("l_extendedprice").sum().alias("sum_base_price"),
                    _q1_expr_disc_price(ctx).sum().alias("sum_disc_price"),
                    _q1_expr_charge(ctx, _q1_expr_disc_price(ctx)).sum().alias("sum_charge"),
                    col("l_quantity").mean().alias("avg_qty"),
                    col("l_extendedprice").mean().alias("avg_price"),
                    col("l_discount").mean().alias("avg_disc"),
                    col("l_orderkey").count().alias("count_order"),
                )
                .sort("l_returnflag", "l_linestatus")
            )

        if variant == 7:
            return _q1_expr_aggregate(ctx, lineitem.filter(shipdate_filter), reversed_keys=True)

        if variant == 8:
            filtered = lineitem.filter(shipdate_filter & (col("l_quantity") > lit(0))).filter(
                col("l_extendedprice") > lit(0)
            )
            return _q1_expr_aggregate(ctx, filtered)

        if variant == 9:
            return _q1_expr_aggregate(ctx, lineitem.filter(shipdate_filter), explicit_sort=True)

        return _q1_expr_aggregate(ctx, lineitem.filter(shipdate_filter), alternate_formula=True)

    impl.__name__ = f"q1_v{variant}_expression_impl"
    impl.__qualname__ = impl.__name__
    return impl


def _q1_pandas_derive(frame: Any, *, alternate_formula: bool = False) -> Any:
    if alternate_formula:
        frame["disc_price"] = frame["l_extendedprice"] - frame["l_extendedprice"] * frame["l_discount"]
    else:
        frame["disc_price"] = frame["l_extendedprice"] * (1 - frame["l_discount"])
    frame["charge"] = frame["disc_price"] * (1 + frame["l_tax"])
    return frame


def _q1_pandas_aggregate(frame: Any, *, reversed_keys: bool = False) -> Any:
    group_cols = ["l_linestatus", "l_returnflag"] if reversed_keys else ["l_returnflag", "l_linestatus"]
    result = (
        frame.groupby(group_cols, as_index=False)
        .agg(
            sum_qty=("l_quantity", "sum"),
            sum_base_price=("l_extendedprice", "sum"),
            sum_disc_price=("disc_price", "sum"),
            sum_charge=("charge", "sum"),
            avg_qty=("l_quantity", "mean"),
            avg_price=("l_extendedprice", "mean"),
            avg_disc=("l_discount", "mean"),
            count_order=("l_orderkey", "count"),
        )
        .sort_values(["l_returnflag", "l_linestatus"])
    )
    return result[_RESULT_COLUMNS] if reversed_keys else result


def _make_q1_pandas_impl(variant: int) -> VariantImpl:
    def impl(ctx: DataFrameContext) -> Any:
        if variant == 1:
            return _q1_pandas_base(ctx)

        lineitem = ctx.get_table("lineitem")
        cutoff_date = get_tpch_parameters(1)["cutoff_date"]

        if variant == 3:
            source = lineitem[_NEEDED_COLUMNS]
        else:
            source = lineitem

        if variant == 8:
            filtered = source[
                (source["l_shipdate"] <= cutoff_date) & (source["l_quantity"] > 0) & (source["l_extendedprice"] > 0)
            ].copy()
        else:
            filtered = source[source["l_shipdate"] <= cutoff_date].copy()

        if variant in {2, 3, 4, 5, 6, 7, 8, 9, 10}:
            _q1_pandas_derive(filtered, alternate_formula=variant == 10)

        return _q1_pandas_aggregate(filtered, reversed_keys=variant == 7)

    impl.__name__ = f"q1_v{variant}_pandas_impl"
    impl.__qualname__ = impl.__name__
    return impl


q1_v1_expression_impl = _make_q1_expression_impl(1)
q1_v1_pandas_impl = _make_q1_pandas_impl(1)
q1_v2_expression_impl = _make_q1_expression_impl(2)
q1_v2_pandas_impl = _make_q1_pandas_impl(2)
q1_v3_expression_impl = _make_q1_expression_impl(3)
q1_v3_pandas_impl = _make_q1_pandas_impl(3)
q1_v4_expression_impl = _make_q1_expression_impl(4)
q1_v4_pandas_impl = _make_q1_pandas_impl(4)
q1_v5_expression_impl = _make_q1_expression_impl(5)
q1_v5_pandas_impl = _make_q1_pandas_impl(5)
q1_v6_expression_impl = _make_q1_expression_impl(6)
q1_v6_pandas_impl = _make_q1_pandas_impl(6)
q1_v7_expression_impl = _make_q1_expression_impl(7)
q1_v7_pandas_impl = _make_q1_pandas_impl(7)
q1_v8_expression_impl = _make_q1_expression_impl(8)
q1_v8_pandas_impl = _make_q1_pandas_impl(8)
q1_v9_expression_impl = _make_q1_expression_impl(9)
q1_v9_pandas_impl = _make_q1_pandas_impl(9)
q1_v10_expression_impl = _make_q1_expression_impl(10)
q1_v10_pandas_impl = _make_q1_pandas_impl(10)

_IMPL_PAIRS = [
    (q1_v1_expression_impl, q1_v1_pandas_impl),
    (q1_v2_expression_impl, q1_v2_pandas_impl),
    (q1_v3_expression_impl, q1_v3_pandas_impl),
    (q1_v4_expression_impl, q1_v4_pandas_impl),
    (q1_v5_expression_impl, q1_v5_pandas_impl),
    (q1_v6_expression_impl, q1_v6_pandas_impl),
    (q1_v7_expression_impl, q1_v7_pandas_impl),
    (q1_v8_expression_impl, q1_v8_pandas_impl),
    (q1_v9_expression_impl, q1_v9_pandas_impl),
    (q1_v10_expression_impl, q1_v10_pandas_impl),
]

Q1_VARIANTS = build_variants(1, _IMPL_PAIRS, _DESCRIPTIONS, AGG_GROUP_FILTER)
