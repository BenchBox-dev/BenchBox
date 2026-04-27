"""TPC-Havoc DataFrame variants for Q1.

Implements 10 structurally diverse variants of TPC-H Q1 (Pricing Summary Report).
Q1 is a single-table aggregate with a date filter and grouped aggregation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q1_expression_impl as _q1_expr_base,
    q1_pandas_impl as _q1_pandas_base,
)

# ---------------------------------------------------------------------------
# v1: baseline - delegate directly to TPC-H base implementation
# ---------------------------------------------------------------------------


def q1_v1_expression_impl(ctx: DataFrameContext) -> Any:
    return _q1_expr_base(ctx)


def q1_v1_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q1_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v2: pre-filter - apply the WHERE predicate before any aggregation column work
# ---------------------------------------------------------------------------


def q1_v2_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    # Pre-filter first, then aggregate
    filtered = lineitem.filter(col("l_shipdate") <= lit(cutoff_date))
    result = (
        filtered.group_by("l_returnflag", "l_linestatus")
        .agg(
            col("l_quantity").sum().alias("sum_qty"),
            col("l_extendedprice").sum().alias("sum_base_price"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("sum_disc_price"),
            (col("l_extendedprice") * (lit(1) - col("l_discount")) * (lit(1) + col("l_tax"))).sum().alias("sum_charge"),
            col("l_quantity").mean().alias("avg_qty"),
            col("l_extendedprice").mean().alias("avg_price"),
            col("l_discount").mean().alias("avg_disc"),
            col("l_orderkey").count().alias("count_order"),
        )
        .sort("l_returnflag", "l_linestatus")
    )
    return result


def q1_v2_pandas_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    # Explicit pre-filter step
    mask = lineitem["l_shipdate"] <= cutoff_date
    filtered = lineitem[mask].copy()

    # Derive columns
    filtered["disc_price"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])
    filtered["charge"] = filtered["disc_price"] * (1 + filtered["l_tax"])

    result = (
        filtered.groupby(["l_returnflag", "l_linestatus"], as_index=False)
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
    return result


# ---------------------------------------------------------------------------
# v3: column prune - select only needed columns before aggregation
# ---------------------------------------------------------------------------


def q1_v3_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    needed_cols = [
        "l_returnflag",
        "l_linestatus",
        "l_quantity",
        "l_extendedprice",
        "l_discount",
        "l_tax",
        "l_orderkey",
        "l_shipdate",
    ]
    result = (
        lineitem.select(needed_cols)
        .filter(col("l_shipdate") <= lit(cutoff_date))
        .group_by("l_returnflag", "l_linestatus")
        .agg(
            col("l_quantity").sum().alias("sum_qty"),
            col("l_extendedprice").sum().alias("sum_base_price"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("sum_disc_price"),
            (col("l_extendedprice") * (lit(1) - col("l_discount")) * (lit(1) + col("l_tax"))).sum().alias("sum_charge"),
            col("l_quantity").mean().alias("avg_qty"),
            col("l_extendedprice").mean().alias("avg_price"),
            col("l_discount").mean().alias("avg_disc"),
            col("l_orderkey").count().alias("count_order"),
        )
        .sort("l_returnflag", "l_linestatus")
    )
    return result


def q1_v3_pandas_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    needed_cols = [
        "l_returnflag",
        "l_linestatus",
        "l_quantity",
        "l_extendedprice",
        "l_discount",
        "l_tax",
        "l_orderkey",
        "l_shipdate",
    ]
    pruned = lineitem[needed_cols]
    filtered = pruned[pruned["l_shipdate"] <= cutoff_date].copy()

    filtered["disc_price"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])
    filtered["charge"] = filtered["disc_price"] * (1 + filtered["l_tax"])

    result = (
        filtered.groupby(["l_returnflag", "l_linestatus"], as_index=False)
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
    return result


# ---------------------------------------------------------------------------
# v4: intermediate vars - explicit intermediate DataFrames for each step
# ---------------------------------------------------------------------------


def q1_v4_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    # Step 1: filter
    step1 = lineitem.filter(col("l_shipdate") <= lit(cutoff_date))
    # Step 2: group and aggregate
    step2 = step1.group_by("l_returnflag", "l_linestatus").agg(
        col("l_quantity").sum().alias("sum_qty"),
        col("l_extendedprice").sum().alias("sum_base_price"),
        (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("sum_disc_price"),
        (col("l_extendedprice") * (lit(1) - col("l_discount")) * (lit(1) + col("l_tax"))).sum().alias("sum_charge"),
        col("l_quantity").mean().alias("avg_qty"),
        col("l_extendedprice").mean().alias("avg_price"),
        col("l_discount").mean().alias("avg_disc"),
        col("l_orderkey").count().alias("count_order"),
    )
    # Step 3: sort
    result = step2.sort("l_returnflag", "l_linestatus")
    return result


def q1_v4_pandas_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    # Step 1: filter
    filtered = lineitem[lineitem["l_shipdate"] <= cutoff_date].copy()
    # Step 2: derive
    filtered["disc_price"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])
    filtered["charge"] = filtered["disc_price"] * (1 + filtered["l_tax"])
    # Step 3: aggregate
    aggregated = filtered.groupby(["l_returnflag", "l_linestatus"], as_index=False).agg(
        sum_qty=("l_quantity", "sum"),
        sum_base_price=("l_extendedprice", "sum"),
        sum_disc_price=("disc_price", "sum"),
        sum_charge=("charge", "sum"),
        avg_qty=("l_quantity", "mean"),
        avg_price=("l_extendedprice", "mean"),
        avg_disc=("l_discount", "mean"),
        count_order=("l_orderkey", "count"),
    )
    # Step 4: sort
    result = aggregated.sort_values(["l_returnflag", "l_linestatus"])
    return result


# ---------------------------------------------------------------------------
# v5: pre-compute derived columns - add disc_price/charge before groupby
# ---------------------------------------------------------------------------


def q1_v5_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    result = (
        lineitem.filter(col("l_shipdate") <= lit(cutoff_date))
        .with_columns(
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("disc_price"),
            (col("l_extendedprice") * (lit(1) - col("l_discount")) * (lit(1) + col("l_tax"))).alias("charge"),
        )
        .group_by("l_returnflag", "l_linestatus")
        .agg(
            col("l_quantity").sum().alias("sum_qty"),
            col("l_extendedprice").sum().alias("sum_base_price"),
            col("disc_price").sum().alias("sum_disc_price"),
            col("charge").sum().alias("sum_charge"),
            col("l_quantity").mean().alias("avg_qty"),
            col("l_extendedprice").mean().alias("avg_price"),
            col("l_discount").mean().alias("avg_disc"),
            col("l_orderkey").count().alias("count_order"),
        )
        .sort("l_returnflag", "l_linestatus")
    )
    return result


def q1_v5_pandas_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    filtered = lineitem[lineitem["l_shipdate"] <= cutoff_date].copy()
    # Pre-compute derived columns before groupby
    filtered["disc_price"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])
    filtered["charge"] = filtered["disc_price"] * (1 + filtered["l_tax"])

    result = (
        filtered.groupby(["l_returnflag", "l_linestatus"], as_index=False)
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
    return result


# ---------------------------------------------------------------------------
# v6: chained style - maximum method chaining, no intermediate variables
# ---------------------------------------------------------------------------


def q1_v6_expression_impl(ctx: DataFrameContext) -> Any:
    col = ctx.col
    lit = ctx.lit
    params = get_tpch_parameters(1)
    return (
        ctx.get_table("lineitem")
        .filter(col("l_shipdate") <= lit(params["cutoff_date"]))
        .group_by("l_returnflag", "l_linestatus")
        .agg(
            col("l_quantity").sum().alias("sum_qty"),
            col("l_extendedprice").sum().alias("sum_base_price"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("sum_disc_price"),
            (col("l_extendedprice") * (lit(1) - col("l_discount")) * (lit(1) + col("l_tax"))).sum().alias("sum_charge"),
            col("l_quantity").mean().alias("avg_qty"),
            col("l_extendedprice").mean().alias("avg_price"),
            col("l_discount").mean().alias("avg_disc"),
            col("l_orderkey").count().alias("count_order"),
        )
        .sort("l_returnflag", "l_linestatus")
    )


def q1_v6_pandas_impl(ctx: DataFrameContext) -> Any:
    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]
    li = ctx.get_table("lineitem")
    filtered = li[li["l_shipdate"] <= cutoff_date].copy()
    filtered["disc_price"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])
    filtered["charge"] = filtered["disc_price"] * (1 + filtered["l_tax"])
    return (
        filtered.groupby(["l_returnflag", "l_linestatus"], as_index=False)
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


# ---------------------------------------------------------------------------
# v7: aggregation alternative - for single-table, split agg into two passes
#     (no join reorder applicable; use alternative groupby key order instead)
# ---------------------------------------------------------------------------


def q1_v7_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    # Group by in reversed key order, then re-sort correctly
    result = (
        lineitem.filter(col("l_shipdate") <= lit(cutoff_date))
        .group_by("l_linestatus", "l_returnflag")
        .agg(
            col("l_quantity").sum().alias("sum_qty"),
            col("l_extendedprice").sum().alias("sum_base_price"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("sum_disc_price"),
            (col("l_extendedprice") * (lit(1) - col("l_discount")) * (lit(1) + col("l_tax"))).sum().alias("sum_charge"),
            col("l_quantity").mean().alias("avg_qty"),
            col("l_extendedprice").mean().alias("avg_price"),
            col("l_discount").mean().alias("avg_disc"),
            col("l_orderkey").count().alias("count_order"),
        )
        .select(
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
        )
        .sort("l_returnflag", "l_linestatus")
    )
    return result


def q1_v7_pandas_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    filtered = lineitem[lineitem["l_shipdate"] <= cutoff_date].copy()
    filtered["disc_price"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])
    filtered["charge"] = filtered["disc_price"] * (1 + filtered["l_tax"])

    result = (
        filtered.groupby(["l_linestatus", "l_returnflag"], as_index=False)
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
    return result[
        [
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
    ]


# ---------------------------------------------------------------------------
# v8: filter combination - use compound filter expression (single & chain)
# ---------------------------------------------------------------------------


def q1_v8_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    # Compound predicate in a single filter call
    result = (
        lineitem.filter((col("l_shipdate") <= lit(cutoff_date)) & (col("l_quantity") > lit(0)))
        .filter(col("l_extendedprice") > lit(0))
        .group_by("l_returnflag", "l_linestatus")
        .agg(
            col("l_quantity").sum().alias("sum_qty"),
            col("l_extendedprice").sum().alias("sum_base_price"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("sum_disc_price"),
            (col("l_extendedprice") * (lit(1) - col("l_discount")) * (lit(1) + col("l_tax"))).sum().alias("sum_charge"),
            col("l_quantity").mean().alias("avg_qty"),
            col("l_extendedprice").mean().alias("avg_price"),
            col("l_discount").mean().alias("avg_disc"),
            col("l_orderkey").count().alias("count_order"),
        )
        .sort("l_returnflag", "l_linestatus")
    )
    return result


def q1_v8_pandas_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    # TPC-H data always has positive quantity and price; these predicates are no-ops
    filtered = lineitem[
        (lineitem["l_shipdate"] <= cutoff_date) & (lineitem["l_quantity"] > 0) & (lineitem["l_extendedprice"] > 0)
    ].copy()

    filtered["disc_price"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])
    filtered["charge"] = filtered["disc_price"] * (1 + filtered["l_tax"])

    result = (
        filtered.groupby(["l_returnflag", "l_linestatus"], as_index=False)
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
    return result


# ---------------------------------------------------------------------------
# v9: explicit sort - pass descending flags explicitly
# ---------------------------------------------------------------------------


def q1_v9_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    result = (
        lineitem.filter(col("l_shipdate") <= lit(cutoff_date))
        .group_by("l_returnflag", "l_linestatus")
        .agg(
            col("l_quantity").sum().alias("sum_qty"),
            col("l_extendedprice").sum().alias("sum_base_price"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("sum_disc_price"),
            (col("l_extendedprice") * (lit(1) - col("l_discount")) * (lit(1) + col("l_tax"))).sum().alias("sum_charge"),
            col("l_quantity").mean().alias("avg_qty"),
            col("l_extendedprice").mean().alias("avg_price"),
            col("l_discount").mean().alias("avg_disc"),
            col("l_orderkey").count().alias("count_order"),
        )
        .sort(["l_returnflag", "l_linestatus"], descending=[False, False])
    )
    return result


def q1_v9_pandas_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    filtered = lineitem[lineitem["l_shipdate"] <= cutoff_date].copy()
    filtered["disc_price"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])
    filtered["charge"] = filtered["disc_price"] * (1 + filtered["l_tax"])

    result = (
        filtered.groupby(["l_returnflag", "l_linestatus"], as_index=False)
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
        .sort_values(["l_returnflag", "l_linestatus"], ascending=[True, True])
    )
    return result


# ---------------------------------------------------------------------------
# v10: alternative formula - use a - a*b instead of a*(1-b) for disc_price
# ---------------------------------------------------------------------------


def q1_v10_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    # Alternative formula: price - price*disc instead of price*(1-disc)
    disc_price_alt = col("l_extendedprice") - col("l_extendedprice") * col("l_discount")
    charge_alt = disc_price_alt * (lit(1) + col("l_tax"))

    result = (
        lineitem.filter(col("l_shipdate") <= lit(cutoff_date))
        .group_by("l_returnflag", "l_linestatus")
        .agg(
            col("l_quantity").sum().alias("sum_qty"),
            col("l_extendedprice").sum().alias("sum_base_price"),
            disc_price_alt.sum().alias("sum_disc_price"),
            charge_alt.sum().alias("sum_charge"),
            col("l_quantity").mean().alias("avg_qty"),
            col("l_extendedprice").mean().alias("avg_price"),
            col("l_discount").mean().alias("avg_disc"),
            col("l_orderkey").count().alias("count_order"),
        )
        .sort("l_returnflag", "l_linestatus")
    )
    return result


def q1_v10_pandas_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    filtered = lineitem[lineitem["l_shipdate"] <= cutoff_date].copy()
    # Alternative formula: price - price*disc instead of price*(1-disc)
    filtered["disc_price"] = filtered["l_extendedprice"] - filtered["l_extendedprice"] * filtered["l_discount"]
    filtered["charge"] = filtered["disc_price"] * (1 + filtered["l_tax"])

    result = (
        filtered.groupby(["l_returnflag", "l_linestatus"], as_index=False)
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
    return result


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

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

Q1_VARIANTS: list[DataFrameQuery] = [
    DataFrameQuery(
        query_id=f"Q1v{v}",
        query_name=f"TPC-H Q1 Variant {v}",
        description=_DESCRIPTIONS[v - 1],
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY, QueryCategory.FILTER],
        expression_impl=expr_impl,
        pandas_impl=pandas_impl,
    )
    for v, (expr_impl, pandas_impl) in enumerate(_IMPL_PAIRS, start=1)
]
