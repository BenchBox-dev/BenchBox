"""TPC-Havoc DataFrame variants for Q18.

Q18 finds large orders via a quantity aggregate, semi-joins them against
customer/orders, re-joins lineitem, and groups with a top-100 sort. The
variants keep the canonical output while varying the large-order
materialization, the semi-join ordering, prefiltering, column pruning,
and aggregation structure.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.tpch.dataframe_queries import (
    get_query as get_tpch_query,
    get_tpch_parameters,
    q18_expression_impl as _q18_expr_base,
    q18_pandas_impl as _q18_pandas_base,
)
from benchbox.core.tpchavoc.dataframe_queries.loader import build_variants

VariantImpl = Callable[[DataFrameContext], Any]

_DESCRIPTIONS = [
    "Baseline: direct delegation to TPC-H Q18 implementation",
    "Large-order materialization: precompute qualifying order keys before the join",
    "Semi-join ordering: customer/orders joined before the large-order filter",
    "Order-side prefilter: threshold predicate pushed before the aggregate",
    "Column prune: select only needed columns before the joins",
    "Per-threshold branches: split quantity bands, concatenated after",
    "Chained style: maximum method chaining, no named intermediates",
    "Alternative aggregation: sum before the top-100 sort with limit pushdown",
    "Materialized join: with_columns order total before grouping",
    "Filter-first ordering: large-order keys applied before customer join",
]

_GROUP_KEYS = ["c_name", "c_custkey", "o_orderkey", "o_orderdate", "o_totalprice"]
_SORT_KEYS = ["o_totalprice", "o_orderdate"]
_SORT_DESC = [True, False]


def _q18_expr_large_orders(lineitem: Any, col: Any, lit: Any, threshold: Any) -> Any:
    return (
        lineitem.group_by("l_orderkey")
        .agg(col("l_quantity").sum().alias("total_qty"))
        .filter(col("total_qty") > lit(threshold))
        .select("l_orderkey")
    )


def _q18_expr_aggregate(joined: Any, col: Any) -> Any:
    return (
        joined.group_by(*_GROUP_KEYS)
        .agg(col("l_quantity").sum().alias("sum_qty"))
        .sort(_SORT_KEYS, descending=_SORT_DESC)
        .limit(100)
    )


def _make_q18_expression_impl(variant: int) -> VariantImpl:
    def impl(ctx: DataFrameContext) -> Any:
        if variant == 1:
            return _q18_expr_base(ctx)

        col = ctx.col
        lit = ctx.lit
        params = get_tpch_parameters(18)
        threshold = params["quantity_threshold"]
        customer = ctx.get_table("customer")
        orders = ctx.get_table("orders")
        lineitem = ctx.get_table("lineitem")

        if variant == 2:
            large_orders = _q18_expr_large_orders(lineitem, col, lit, threshold)
            joined = (
                customer.join(orders, left_on="c_custkey", right_on="o_custkey")
                .join(large_orders, left_on="o_orderkey", right_on="l_orderkey", how="semi")
                .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
            )
            return _q18_expr_aggregate(joined, col)

        if variant == 3:
            base = customer.join(orders, left_on="c_custkey", right_on="o_custkey")
            large_orders = _q18_expr_large_orders(lineitem, col, lit, threshold)
            joined = base.join(large_orders, left_on="o_orderkey", right_on="l_orderkey", how="semi").join(
                lineitem, left_on="o_orderkey", right_on="l_orderkey"
            )
            return _q18_expr_aggregate(joined, col)

        if variant == 4:
            large_orders = (
                lineitem.filter(col("l_quantity") > lit(0))
                .group_by("l_orderkey")
                .agg(col("l_quantity").sum().alias("total_qty"))
                .filter(col("total_qty") > lit(threshold))
                .select("l_orderkey")
            )
            joined = (
                customer.join(orders, left_on="c_custkey", right_on="o_custkey")
                .join(large_orders, left_on="o_orderkey", right_on="l_orderkey", how="semi")
                .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
            )
            return _q18_expr_aggregate(joined, col)

        if variant == 5:
            customer_cols = customer.select("c_custkey", "c_name")
            orders_cols = orders.select("o_orderkey", "o_custkey", "o_orderdate", "o_totalprice")
            lineitem_cols = lineitem.select("l_orderkey", "l_quantity")
            large_orders = _q18_expr_large_orders(lineitem, col, lit, threshold)
            joined = (
                customer_cols.join(orders_cols, left_on="c_custkey", right_on="o_custkey")
                .join(large_orders, left_on="o_orderkey", right_on="l_orderkey", how="semi")
                .join(lineitem_cols, left_on="o_orderkey", right_on="l_orderkey")
            )
            return _q18_expr_aggregate(joined, col)

        if variant == 6:
            lower = _q18_expr_large_orders(lineitem, col, lit, threshold)
            upper = _q18_expr_large_orders(lineitem.filter(col("l_quantity") > lit(threshold)), col, lit, threshold)
            large_orders = ctx.concat([lower, upper]).distinct()
            joined = (
                customer.join(orders, left_on="c_custkey", right_on="o_custkey")
                .join(large_orders, left_on="o_orderkey", right_on="l_orderkey", how="semi")
                .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
            )
            return _q18_expr_aggregate(joined, col)

        if variant == 7:
            large_orders = _q18_expr_large_orders(lineitem, col, lit, threshold)
            return (
                customer.join(orders, left_on="c_custkey", right_on="o_custkey")
                .join(large_orders, left_on="o_orderkey", right_on="l_orderkey", how="semi")
                .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
                .group_by(*_GROUP_KEYS)
                .agg(col("l_quantity").sum().alias("sum_qty"))
                .sort(_SORT_KEYS, descending=_SORT_DESC)
                .limit(100)
            )

        if variant == 8:
            large_orders = _q18_expr_large_orders(lineitem, col, lit, threshold)
            joined = (
                customer.join(orders, left_on="c_custkey", right_on="o_custkey")
                .join(large_orders, left_on="o_orderkey", right_on="l_orderkey", how="semi")
                .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
            )
            return (
                joined.group_by(*_GROUP_KEYS)
                .agg(col("l_quantity").sum().alias("sum_qty"))
                .sort(_SORT_KEYS, descending=_SORT_DESC)
                .limit(100)
            )

        if variant == 9:
            large_orders = _q18_expr_large_orders(lineitem, col, lit, threshold)
            joined = (
                customer.join(orders, left_on="c_custkey", right_on="o_custkey")
                .join(large_orders, left_on="o_orderkey", right_on="l_orderkey", how="semi")
                .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
                .with_columns(col("l_quantity").alias("qty"))
            )
            return (
                joined.group_by(*_GROUP_KEYS)
                .agg(col("qty").sum().alias("sum_qty"))
                .sort(_SORT_KEYS, descending=_SORT_DESC)
                .limit(100)
            )

        large_orders = _q18_expr_large_orders(lineitem, col, lit, threshold)
        filtered_orders = orders.join(large_orders, left_on="o_orderkey", right_on="l_orderkey", how="semi")
        joined = customer.join(filtered_orders, left_on="c_custkey", right_on="o_custkey").join(
            lineitem, left_on="o_orderkey", right_on="l_orderkey"
        )
        return _q18_expr_aggregate(joined, col)

    impl.__name__ = f"q18_v{variant}_expression_impl"
    impl.__qualname__ = impl.__name__
    return impl


def _q18_pandas_large_orders(lineitem: Any, threshold: Any) -> Any:
    order_qty = lineitem.groupby("l_orderkey", as_index=False).agg(total_qty=("l_quantity", "sum"))
    return _to_list(order_qty[order_qty["total_qty"] > threshold]["l_orderkey"])


def _q18_pandas_aggregate(joined: Any) -> Any:
    return (
        joined.groupby(["c_name", "c_custkey", "o_orderkey", "o_orderdate", "o_totalprice"], as_index=False)
        .agg(sum_qty=("l_quantity", "sum"))
        .sort_values(["o_totalprice", "o_orderdate"], ascending=[False, True])
        .head(100)
    )


def _make_q18_pandas_impl(variant: int) -> VariantImpl:
    def impl(ctx: DataFrameContext) -> Any:
        if variant == 1:
            return _q18_pandas_base(ctx)

        customer = ctx.get_table("customer")
        orders = ctx.get_table("orders")
        lineitem = ctx.get_table("lineitem")
        params = get_tpch_parameters(18)
        threshold = params["quantity_threshold"]

        if variant == 2:
            large_orders = _q18_pandas_large_orders(lineitem, threshold)
            joined = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
            joined = joined[joined["o_orderkey"].isin(large_orders)]
            return _q18_pandas_aggregate(joined.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey"))

        if variant == 3:
            base = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
            large_orders = _q18_pandas_large_orders(lineitem, threshold)
            joined = base[base["o_orderkey"].isin(large_orders)]
            return _q18_pandas_aggregate(joined.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey"))

        if variant == 4:
            positive = lineitem[lineitem["l_quantity"] > 0]
            order_qty = positive.groupby("l_orderkey", as_index=False).agg(total_qty=("l_quantity", "sum"))
            large_orders = _to_list(order_qty[order_qty["total_qty"] > threshold]["l_orderkey"])
            joined = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
            joined = joined[joined["o_orderkey"].isin(large_orders)]
            return _q18_pandas_aggregate(joined.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey"))

        if variant == 5:
            customer_cols = customer[["c_custkey", "c_name"]]
            orders_cols = orders[["o_orderkey", "o_custkey", "o_orderdate", "o_totalprice"]]
            lineitem_cols = lineitem[["l_orderkey", "l_quantity"]]
            large_orders = _q18_pandas_large_orders(lineitem, threshold)
            joined = customer_cols.merge(orders_cols, left_on="c_custkey", right_on="o_custkey")
            joined = joined[joined["o_orderkey"].isin(large_orders)]
            return _q18_pandas_aggregate(joined.merge(lineitem_cols, left_on="o_orderkey", right_on="l_orderkey"))

        if variant == 6:
            lower = _q18_pandas_large_orders(lineitem, threshold)
            upper = _q18_pandas_large_orders(lineitem[lineitem["l_quantity"] > threshold], threshold)
            large_orders = list(dict.fromkeys(lower + upper))
            joined = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
            joined = joined[joined["o_orderkey"].isin(large_orders)]
            return _q18_pandas_aggregate(joined.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey"))

        if variant == 7:
            large_orders = _q18_pandas_large_orders(lineitem, threshold)
            return _q18_pandas_aggregate(
                customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
                .pipe(lambda f: f[f["o_orderkey"].isin(large_orders)])
                .merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
            )

        if variant == 8:
            large_orders = _q18_pandas_large_orders(lineitem, threshold)
            joined = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
            joined = joined[joined["o_orderkey"].isin(large_orders)]
            merged = joined.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
            return _q18_pandas_aggregate(merged)

        if variant == 9:
            large_orders = _q18_pandas_large_orders(lineitem, threshold)
            joined = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
            joined = joined[joined["o_orderkey"].isin(large_orders)]
            merged = joined.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey").copy()
            merged["qty"] = merged["l_quantity"]
            grouped = (
                merged.groupby(["c_name", "c_custkey", "o_orderkey", "o_orderdate", "o_totalprice"], as_index=False)
                .agg(sum_qty=("qty", "sum"))
                .sort_values(["o_totalprice", "o_orderdate"], ascending=[False, True])
                .head(100)
            )
            return grouped

        large_orders = _q18_pandas_large_orders(lineitem, threshold)
        filtered_orders = orders[orders["o_orderkey"].isin(large_orders)]
        joined = customer.merge(filtered_orders, left_on="c_custkey", right_on="o_custkey")
        return _q18_pandas_aggregate(joined.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey"))

    impl.__name__ = f"q18_v{variant}_pandas_impl"
    impl.__qualname__ = impl.__name__
    return impl


def _to_list(values: Any) -> list:
    return values.compute().tolist() if hasattr(values, "compute") else list(values)


_Q18_BASE = get_tpch_query("Q18")

Q18_VARIANTS = build_variants(
    18,
    [(_make_q18_expression_impl(v), _make_q18_pandas_impl(v)) for v in range(1, 11)],
    _DESCRIPTIONS,
    _Q18_BASE.categories,
)
