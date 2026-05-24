"""TPC-Havoc DataFrame variants for Q6.

Q6 is a single-table predicate plus scalar aggregate. The variants keep the
existing filter sequencing, column-pruning, precomputed-revenue, and formula
differences explicit while sharing repeated predicate and scalar-result code.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q6_expression_impl as _q6_expr_base,
    q6_pandas_impl as _q6_pandas_base,
)

VariantImpl = Callable[[DataFrameContext], Any]

_NEEDED_COLUMNS = ["l_shipdate", "l_discount", "l_quantity", "l_extendedprice"]
_DESCRIPTIONS = [
    "Baseline: direct delegation to TPC-H Q6 implementation",
    "Pre-filter: apply each WHERE predicate separately before revenue computation",
    "Column prune: select only needed columns before filtering",
    "Intermediate vars: named DataFrames for date, discount, quantity filter steps",
    "Pre-compute derived: add revenue column before summing",
    "Chained style: maximum method chaining, no named intermediates",
    "Aggregation alternative: discount+quantity filter first, then date filter",
    "Filter combination: two compound predicates ANDed together",
    "Explicit select: explicit revenue column selection before sum",
    "Alternative formula: commuted discount*price instead of price*discount",
]


def _q6_expr_predicate(ctx: DataFrameContext, params: dict[str, Any]) -> Any:
    col = ctx.col
    lit = ctx.lit
    return (
        (col("l_shipdate") >= lit(params["start_date"]))
        & (col("l_shipdate") < lit(params["end_date"]))
        & (col("l_discount") >= lit(params["discount_low"]))
        & (col("l_discount") <= lit(params["discount_high"]))
        & (col("l_quantity") < lit(params["quantity_limit"]))
    )


def _q6_expr_revenue(ctx: DataFrameContext, *, commuted: bool = False) -> Any:
    col = ctx.col
    left, right = ("l_discount", "l_extendedprice") if commuted else ("l_extendedprice", "l_discount")
    return (col(left) * col(right)).alias("revenue")


def _q6_expr_sum(frame: Any, ctx: DataFrameContext, *, commuted: bool = False) -> Any:
    return frame.select(_q6_expr_revenue(ctx, commuted=commuted)).sum()


def _make_q6_expression_impl(variant: int) -> VariantImpl:
    def impl(ctx: DataFrameContext) -> Any:
        if variant == 1:
            return _q6_expr_base(ctx)

        lineitem = ctx.get_table("lineitem")
        col = ctx.col
        lit = ctx.lit
        params = get_tpch_parameters(6)

        if variant == 2:
            filtered = (
                lineitem.filter(col("l_shipdate") >= lit(params["start_date"]))
                .filter(col("l_shipdate") < lit(params["end_date"]))
                .filter(col("l_discount") >= lit(params["discount_low"]))
                .filter(col("l_discount") <= lit(params["discount_high"]))
                .filter(col("l_quantity") < lit(params["quantity_limit"]))
            )
            return _q6_expr_sum(filtered, ctx)

        if variant == 3:
            return _q6_expr_sum(lineitem.select(_NEEDED_COLUMNS).filter(_q6_expr_predicate(ctx, params)), ctx)

        if variant == 4:
            date_filtered = lineitem.filter(
                (col("l_shipdate") >= lit(params["start_date"])) & (col("l_shipdate") < lit(params["end_date"]))
            )
            discount_filtered = date_filtered.filter(
                (col("l_discount") >= lit(params["discount_low"])) & (col("l_discount") <= lit(params["discount_high"]))
            )
            final_filtered = discount_filtered.filter(col("l_quantity") < lit(params["quantity_limit"]))
            return _q6_expr_sum(final_filtered, ctx)

        if variant == 5:
            return (
                lineitem.filter(_q6_expr_predicate(ctx, params))
                .with_columns(_q6_expr_revenue(ctx))
                .select("revenue")
                .sum()
            )

        if variant == 6:
            return ctx.get_table("lineitem").filter(_q6_expr_predicate(ctx, params)).select(_q6_expr_revenue(ctx)).sum()

        if variant == 7:
            by_discount_qty = lineitem.filter(
                (col("l_discount") >= lit(params["discount_low"]))
                & (col("l_discount") <= lit(params["discount_high"]))
                & (col("l_quantity") < lit(params["quantity_limit"]))
            )
            by_date = by_discount_qty.filter(
                (col("l_shipdate") >= lit(params["start_date"])) & (col("l_shipdate") < lit(params["end_date"]))
            )
            return _q6_expr_sum(by_date, ctx)

        if variant == 8:
            date_pred = (col("l_shipdate") >= lit(params["start_date"])) & (col("l_shipdate") < lit(params["end_date"]))
            rest_pred = (
                (col("l_discount") >= lit(params["discount_low"]))
                & (col("l_discount") <= lit(params["discount_high"]))
                & (col("l_quantity") < lit(params["quantity_limit"]))
            )
            return _q6_expr_sum(lineitem.filter(date_pred & rest_pred), ctx)

        if variant == 9:
            filtered = lineitem.filter(_q6_expr_predicate(ctx, params))
            revenue_col = _q6_expr_revenue(ctx)
            return filtered.select(revenue_col).sum()

        return _q6_expr_sum(lineitem.filter(_q6_expr_predicate(ctx, params)), ctx, commuted=True)

    impl.__name__ = f"q6_v{variant}_expression_impl"
    impl.__qualname__ = impl.__name__
    return impl


def _q6_pandas_predicate(lineitem: Any, params: dict[str, Any]) -> Any:
    return (
        (lineitem["l_shipdate"] >= params["start_date"])
        & (lineitem["l_shipdate"] < params["end_date"])
        & (lineitem["l_discount"] >= params["discount_low"])
        & (lineitem["l_discount"] <= params["discount_high"])
        & (lineitem["l_quantity"] < params["quantity_limit"])
    )


def _q6_pandas_frame(value: Any) -> Any:
    import pandas as pd

    value = value.compute() if hasattr(value, "compute") else value
    return pd.DataFrame({"revenue": [value]})


def _q6_pandas_sum(frame: Any, *, commuted: bool = False) -> Any:
    left, right = ("l_discount", "l_extendedprice") if commuted else ("l_extendedprice", "l_discount")
    return _q6_pandas_frame((frame[left] * frame[right]).sum())


def _make_q6_pandas_impl(variant: int) -> VariantImpl:
    def impl(ctx: DataFrameContext) -> Any:
        if variant == 1:
            return _q6_pandas_base(ctx)

        lineitem = ctx.get_table("lineitem")
        params = get_tpch_parameters(6)

        if variant == 2:
            mask = lineitem["l_shipdate"] >= params["start_date"]
            mask = mask & (lineitem["l_shipdate"] < params["end_date"])
            mask = mask & (lineitem["l_discount"] >= params["discount_low"])
            mask = mask & (lineitem["l_discount"] <= params["discount_high"])
            mask = mask & (lineitem["l_quantity"] < params["quantity_limit"])
            return _q6_pandas_sum(lineitem[mask])

        if variant == 3:
            pruned = lineitem[_NEEDED_COLUMNS]
            return _q6_pandas_sum(pruned[_q6_pandas_predicate(pruned, params)])

        if variant == 4:
            date_filtered = lineitem[
                (lineitem["l_shipdate"] >= params["start_date"]) & (lineitem["l_shipdate"] < params["end_date"])
            ]
            discount_filtered = date_filtered[
                (date_filtered["l_discount"] >= params["discount_low"])
                & (date_filtered["l_discount"] <= params["discount_high"])
            ]
            return _q6_pandas_sum(discount_filtered[discount_filtered["l_quantity"] < params["quantity_limit"]])

        if variant == 5:
            filtered = lineitem[_q6_pandas_predicate(lineitem, params)].copy()
            filtered["revenue"] = filtered["l_extendedprice"] * filtered["l_discount"]
            return _q6_pandas_frame(filtered["revenue"].sum())

        if variant == 6:
            li = ctx.get_table("lineitem")
            return _q6_pandas_sum(li[_q6_pandas_predicate(li, params)])

        if variant == 7:
            by_discount_qty = lineitem[
                (lineitem["l_discount"] >= params["discount_low"])
                & (lineitem["l_discount"] <= params["discount_high"])
                & (lineitem["l_quantity"] < params["quantity_limit"])
            ]
            filtered = by_discount_qty[
                (by_discount_qty["l_shipdate"] >= params["start_date"])
                & (by_discount_qty["l_shipdate"] < params["end_date"])
            ]
            return _q6_pandas_sum(filtered)

        if variant == 8:
            date_mask = (lineitem["l_shipdate"] >= params["start_date"]) & (lineitem["l_shipdate"] < params["end_date"])
            rest_mask = (
                (lineitem["l_discount"] >= params["discount_low"])
                & (lineitem["l_discount"] <= params["discount_high"])
                & (lineitem["l_quantity"] < params["quantity_limit"])
            )
            return _q6_pandas_sum(lineitem[date_mask & rest_mask])

        if variant == 9:
            filtered = lineitem[_q6_pandas_predicate(lineitem, params)]
            revenue_series = filtered["l_extendedprice"] * filtered["l_discount"]
            return _q6_pandas_frame(revenue_series.sum())

        return _q6_pandas_sum(lineitem[_q6_pandas_predicate(lineitem, params)], commuted=True)

    impl.__name__ = f"q6_v{variant}_pandas_impl"
    impl.__qualname__ = impl.__name__
    return impl


q6_v1_expression_impl = _make_q6_expression_impl(1)
q6_v1_pandas_impl = _make_q6_pandas_impl(1)
q6_v2_expression_impl = _make_q6_expression_impl(2)
q6_v2_pandas_impl = _make_q6_pandas_impl(2)
q6_v3_expression_impl = _make_q6_expression_impl(3)
q6_v3_pandas_impl = _make_q6_pandas_impl(3)
q6_v4_expression_impl = _make_q6_expression_impl(4)
q6_v4_pandas_impl = _make_q6_pandas_impl(4)
q6_v5_expression_impl = _make_q6_expression_impl(5)
q6_v5_pandas_impl = _make_q6_pandas_impl(5)
q6_v6_expression_impl = _make_q6_expression_impl(6)
q6_v6_pandas_impl = _make_q6_pandas_impl(6)
q6_v7_expression_impl = _make_q6_expression_impl(7)
q6_v7_pandas_impl = _make_q6_pandas_impl(7)
q6_v8_expression_impl = _make_q6_expression_impl(8)
q6_v8_pandas_impl = _make_q6_pandas_impl(8)
q6_v9_expression_impl = _make_q6_expression_impl(9)
q6_v9_pandas_impl = _make_q6_pandas_impl(9)
q6_v10_expression_impl = _make_q6_expression_impl(10)
q6_v10_pandas_impl = _make_q6_pandas_impl(10)

_IMPL_PAIRS = [
    (q6_v1_expression_impl, q6_v1_pandas_impl),
    (q6_v2_expression_impl, q6_v2_pandas_impl),
    (q6_v3_expression_impl, q6_v3_pandas_impl),
    (q6_v4_expression_impl, q6_v4_pandas_impl),
    (q6_v5_expression_impl, q6_v5_pandas_impl),
    (q6_v6_expression_impl, q6_v6_pandas_impl),
    (q6_v7_expression_impl, q6_v7_pandas_impl),
    (q6_v8_expression_impl, q6_v8_pandas_impl),
    (q6_v9_expression_impl, q6_v9_pandas_impl),
    (q6_v10_expression_impl, q6_v10_pandas_impl),
]

Q6_VARIANTS: list[DataFrameQuery] = [
    DataFrameQuery(
        query_id=f"Q6v{variant}",
        query_name=f"TPC-H Q6 Variant {variant}",
        description=_DESCRIPTIONS[variant - 1],
        categories=[QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=expr_impl,
        pandas_impl=pandas_impl,
    )
    for variant, (expr_impl, pandas_impl) in enumerate(_IMPL_PAIRS, start=1)
]
