"""TPC-Havoc DataFrame variants for Q12.

Implements 10 structurally diverse variants of TPC-H Q12 (Shipping Modes and Order Priority).
Q12 filters lineitems by shipmode and date conditions, joins orders, and counts
high vs. low priority orders per shipping mode.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q12_expression_impl as _q12_expr_base,
    q12_pandas_impl as _q12_pandas_base,
)

# ---------------------------------------------------------------------------
# v1: baseline - delegate directly to TPC-H base implementation
# ---------------------------------------------------------------------------


def q12_v1_expression_impl(ctx: DataFrameContext) -> Any:
    return _q12_expr_base(ctx)


def q12_v1_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q12_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v2: pre-filter - apply all lineitem predicates before joining orders
# ---------------------------------------------------------------------------


def q12_v2_expression_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Pre-filter lineitem completely before joining
    filtered = lineitem.filter(
        col("l_shipmode").is_in([shipmode1, shipmode2])
        & (col("l_commitdate") < col("l_receiptdate"))
        & (col("l_shipdate") < col("l_commitdate"))
        & (col("l_receiptdate") >= lit(start_date))
        & (col("l_receiptdate") < lit(end_date))
    )

    return (
        filtered.join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .group_by("l_shipmode")
        .agg(
            col("o_orderpriority")
            .filter(col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
            .count()
            .alias("high_line_count"),
            col("o_orderpriority")
            .filter(~col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
            .count()
            .alias("low_line_count"),
        )
        .sort("l_shipmode")
    )


def q12_v2_pandas_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Explicit pre-filter step
    mask = (
        lineitem["l_shipmode"].isin([shipmode1, shipmode2])
        & (lineitem["l_commitdate"] < lineitem["l_receiptdate"])
        & (lineitem["l_shipdate"] < lineitem["l_commitdate"])
        & (lineitem["l_receiptdate"] >= start_date)
        & (lineitem["l_receiptdate"] < end_date)
    )
    filtered = lineitem[mask]
    joined = filtered.merge(orders, left_on="l_orderkey", right_on="o_orderkey").copy()
    joined["high_priority"] = joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"]).astype(int)
    joined["low_priority"] = (~joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"])).astype(int)

    return (
        joined.groupby("l_shipmode", as_index=False)
        .agg(high_line_count=("high_priority", "sum"), low_line_count=("low_priority", "sum"))
        .sort_values("l_shipmode")
    )


# ---------------------------------------------------------------------------
# v3: column prune - select only needed columns before joining
# ---------------------------------------------------------------------------


def q12_v3_expression_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    return (
        lineitem.select("l_orderkey", "l_shipmode", "l_commitdate", "l_receiptdate", "l_shipdate")
        .filter(
            col("l_shipmode").is_in([shipmode1, shipmode2])
            & (col("l_commitdate") < col("l_receiptdate"))
            & (col("l_shipdate") < col("l_commitdate"))
            & (col("l_receiptdate") >= lit(start_date))
            & (col("l_receiptdate") < lit(end_date))
        )
        .join(orders.select("o_orderkey", "o_orderpriority"), left_on="l_orderkey", right_on="o_orderkey")
        .group_by("l_shipmode")
        .agg(
            col("o_orderpriority")
            .filter(col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
            .count()
            .alias("high_line_count"),
            col("o_orderpriority")
            .filter(~col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
            .count()
            .alias("low_line_count"),
        )
        .sort("l_shipmode")
    )


def q12_v3_pandas_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    li = lineitem[["l_orderkey", "l_shipmode", "l_commitdate", "l_receiptdate", "l_shipdate"]]
    o = orders[["o_orderkey", "o_orderpriority"]]

    filtered = li[
        li["l_shipmode"].isin([shipmode1, shipmode2])
        & (li["l_commitdate"] < li["l_receiptdate"])
        & (li["l_shipdate"] < li["l_commitdate"])
        & (li["l_receiptdate"] >= start_date)
        & (li["l_receiptdate"] < end_date)
    ]

    joined = filtered.merge(o, left_on="l_orderkey", right_on="o_orderkey").copy()
    joined["high_priority"] = joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"]).astype(int)
    joined["low_priority"] = (~joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"])).astype(int)

    return (
        joined.groupby("l_shipmode", as_index=False)
        .agg(high_line_count=("high_priority", "sum"), low_line_count=("low_priority", "sum"))
        .sort_values("l_shipmode")
    )


# ---------------------------------------------------------------------------
# v4: intermediate vars - explicit DataFrames for each step
# ---------------------------------------------------------------------------


def q12_v4_expression_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Step 1: filter
    step1 = lineitem.filter(
        col("l_shipmode").is_in([shipmode1, shipmode2])
        & (col("l_commitdate") < col("l_receiptdate"))
        & (col("l_shipdate") < col("l_commitdate"))
        & (col("l_receiptdate") >= lit(start_date))
        & (col("l_receiptdate") < lit(end_date))
    )
    # Step 2: join
    step2 = step1.join(orders, left_on="l_orderkey", right_on="o_orderkey")
    # Step 3: aggregate
    step3 = step2.group_by("l_shipmode").agg(
        col("o_orderpriority")
        .filter(col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
        .count()
        .alias("high_line_count"),
        col("o_orderpriority")
        .filter(~col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
        .count()
        .alias("low_line_count"),
    )
    # Step 4: sort
    return step3.sort("l_shipmode")


def q12_v4_pandas_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Step 1: filter
    filtered = lineitem[
        lineitem["l_shipmode"].isin([shipmode1, shipmode2])
        & (lineitem["l_commitdate"] < lineitem["l_receiptdate"])
        & (lineitem["l_shipdate"] < lineitem["l_commitdate"])
        & (lineitem["l_receiptdate"] >= start_date)
        & (lineitem["l_receiptdate"] < end_date)
    ]
    # Step 2: join
    joined = filtered.merge(orders, left_on="l_orderkey", right_on="o_orderkey").copy()
    # Step 3: derive priority flags
    joined["high_priority"] = joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"]).astype(int)
    joined["low_priority"] = (~joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"])).astype(int)
    # Step 4: aggregate and sort
    aggregated = joined.groupby("l_shipmode", as_index=False).agg(
        high_line_count=("high_priority", "sum"), low_line_count=("low_priority", "sum")
    )
    return aggregated.sort_values("l_shipmode")


# ---------------------------------------------------------------------------
# v5: pre-compute derived - add priority flag columns before groupby
# ---------------------------------------------------------------------------


def q12_v5_expression_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Join first, then aggregate with explicit filter expressions per column
    joined = lineitem.filter(
        col("l_shipmode").is_in([shipmode1, shipmode2])
        & (col("l_commitdate") < col("l_receiptdate"))
        & (col("l_shipdate") < col("l_commitdate"))
        & (col("l_receiptdate") >= lit(start_date))
        & (col("l_receiptdate") < lit(end_date))
    ).join(orders.select("o_orderkey", "o_orderpriority"), left_on="l_orderkey", right_on="o_orderkey")

    high_prio = ["1-URGENT", "2-HIGH"]
    return (
        joined.group_by("l_shipmode")
        .agg(
            col("o_orderpriority").filter(col("o_orderpriority").is_in(high_prio)).count().alias("high_line_count"),
            col("o_orderpriority").filter(~col("o_orderpriority").is_in(high_prio)).count().alias("low_line_count"),
        )
        .sort("l_shipmode")
    )


def q12_v5_pandas_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    filtered = lineitem[
        lineitem["l_shipmode"].isin([shipmode1, shipmode2])
        & (lineitem["l_commitdate"] < lineitem["l_receiptdate"])
        & (lineitem["l_shipdate"] < lineitem["l_commitdate"])
        & (lineitem["l_receiptdate"] >= start_date)
        & (lineitem["l_receiptdate"] < end_date)
    ]
    joined = filtered.merge(orders, left_on="l_orderkey", right_on="o_orderkey").copy()
    # Pre-compute derived priority columns before groupby
    joined["high_priority"] = joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"]).astype(int)
    joined["low_priority"] = (~joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"])).astype(int)

    return (
        joined.groupby("l_shipmode", as_index=False)
        .agg(high_line_count=("high_priority", "sum"), low_line_count=("low_priority", "sum"))
        .sort_values("l_shipmode")
    )


# ---------------------------------------------------------------------------
# v6: chained style - maximum method chaining, no named intermediates
# ---------------------------------------------------------------------------


def q12_v6_expression_impl(ctx: DataFrameContext) -> Any:
    col = ctx.col
    lit = ctx.lit
    p = get_tpch_parameters(12)
    return (
        ctx.get_table("lineitem")
        .filter(
            col("l_shipmode").is_in([p["shipmode1"], p["shipmode2"]])
            & (col("l_commitdate") < col("l_receiptdate"))
            & (col("l_shipdate") < col("l_commitdate"))
            & (col("l_receiptdate") >= lit(p["start_date"]))
            & (col("l_receiptdate") < lit(p["end_date"]))
        )
        .join(ctx.get_table("orders"), left_on="l_orderkey", right_on="o_orderkey")
        .group_by("l_shipmode")
        .agg(
            col("o_orderpriority")
            .filter(col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
            .count()
            .alias("high_line_count"),
            col("o_orderpriority")
            .filter(~col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
            .count()
            .alias("low_line_count"),
        )
        .sort("l_shipmode")
    )


def q12_v6_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q12_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v7: join reorder - join orders first, then filter lineitem predicates
# ---------------------------------------------------------------------------


def q12_v7_expression_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Join first, then filter
    return (
        lineitem.join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .filter(
            col("l_shipmode").is_in([shipmode1, shipmode2])
            & (col("l_commitdate") < col("l_receiptdate"))
            & (col("l_shipdate") < col("l_commitdate"))
            & (col("l_receiptdate") >= lit(start_date))
            & (col("l_receiptdate") < lit(end_date))
        )
        .group_by("l_shipmode")
        .agg(
            col("o_orderpriority")
            .filter(col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
            .count()
            .alias("high_line_count"),
            col("o_orderpriority")
            .filter(~col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
            .count()
            .alias("low_line_count"),
        )
        .sort("l_shipmode")
    )


def q12_v7_pandas_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Join first, filter after
    joined = lineitem.merge(orders, left_on="l_orderkey", right_on="o_orderkey")
    filtered = joined[
        joined["l_shipmode"].isin([shipmode1, shipmode2])
        & (joined["l_commitdate"] < joined["l_receiptdate"])
        & (joined["l_shipdate"] < joined["l_commitdate"])
        & (joined["l_receiptdate"] >= start_date)
        & (joined["l_receiptdate"] < end_date)
    ].copy()

    filtered["high_priority"] = filtered["o_orderpriority"].isin(["1-URGENT", "2-HIGH"]).astype(int)
    filtered["low_priority"] = (~filtered["o_orderpriority"].isin(["1-URGENT", "2-HIGH"])).astype(int)

    return (
        filtered.groupby("l_shipmode", as_index=False)
        .agg(high_line_count=("high_priority", "sum"), low_line_count=("low_priority", "sum"))
        .sort_values("l_shipmode")
    )


# ---------------------------------------------------------------------------
# v8: filter combination - split date filter and mode filter as separate calls
# ---------------------------------------------------------------------------


def q12_v8_expression_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    return (
        lineitem.filter(col("l_shipmode").is_in([shipmode1, shipmode2]))
        .filter((col("l_commitdate") < col("l_receiptdate")) & (col("l_shipdate") < col("l_commitdate")))
        .filter((col("l_receiptdate") >= lit(start_date)) & (col("l_receiptdate") < lit(end_date)))
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .group_by("l_shipmode")
        .agg(
            col("o_orderpriority")
            .filter(col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
            .count()
            .alias("high_line_count"),
            col("o_orderpriority")
            .filter(~col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
            .count()
            .alias("low_line_count"),
        )
        .sort("l_shipmode")
    )


def q12_v8_pandas_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Split filter into separate steps
    step1 = lineitem[lineitem["l_shipmode"].isin([shipmode1, shipmode2])]
    step2 = step1[(step1["l_commitdate"] < step1["l_receiptdate"]) & (step1["l_shipdate"] < step1["l_commitdate"])]
    step3 = step2[(step2["l_receiptdate"] >= start_date) & (step2["l_receiptdate"] < end_date)]

    joined = step3.merge(orders, left_on="l_orderkey", right_on="o_orderkey").copy()
    joined["high_priority"] = joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"]).astype(int)
    joined["low_priority"] = (~joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"])).astype(int)

    return (
        joined.groupby("l_shipmode", as_index=False)
        .agg(high_line_count=("high_priority", "sum"), low_line_count=("low_priority", "sum"))
        .sort_values("l_shipmode")
    )


# ---------------------------------------------------------------------------
# v9: explicit sort - pass descending=[False] explicitly
# ---------------------------------------------------------------------------


def q12_v9_expression_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    return (
        lineitem.filter(
            col("l_shipmode").is_in([shipmode1, shipmode2])
            & (col("l_commitdate") < col("l_receiptdate"))
            & (col("l_shipdate") < col("l_commitdate"))
            & (col("l_receiptdate") >= lit(start_date))
            & (col("l_receiptdate") < lit(end_date))
        )
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .group_by("l_shipmode")
        .agg(
            col("o_orderpriority")
            .filter(col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
            .count()
            .alias("high_line_count"),
            col("o_orderpriority")
            .filter(~col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
            .count()
            .alias("low_line_count"),
        )
        .sort(["l_shipmode"], descending=[False])
    )


def q12_v9_pandas_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    filtered = lineitem[
        lineitem["l_shipmode"].isin([shipmode1, shipmode2])
        & (lineitem["l_commitdate"] < lineitem["l_receiptdate"])
        & (lineitem["l_shipdate"] < lineitem["l_commitdate"])
        & (lineitem["l_receiptdate"] >= start_date)
        & (lineitem["l_receiptdate"] < end_date)
    ]
    joined = filtered.merge(orders, left_on="l_orderkey", right_on="o_orderkey").copy()
    joined["high_priority"] = joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"]).astype(int)
    joined["low_priority"] = (~joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"])).astype(int)

    return (
        joined.groupby("l_shipmode", as_index=False)
        .agg(high_line_count=("high_priority", "sum"), low_line_count=("low_priority", "sum"))
        .sort_values("l_shipmode", ascending=[True])
    )


# ---------------------------------------------------------------------------
# v10: alternative formula - use shipmode in-list as two separate equality checks
# ---------------------------------------------------------------------------


def q12_v10_expression_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Use OR of equality checks instead of is_in for shipmode
    return (
        lineitem.filter(
            ((col("l_shipmode") == lit(shipmode1)) | (col("l_shipmode") == lit(shipmode2)))
            & (col("l_commitdate") < col("l_receiptdate"))
            & (col("l_shipdate") < col("l_commitdate"))
            & (col("l_receiptdate") >= lit(start_date))
            & (col("l_receiptdate") < lit(end_date))
        )
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .group_by("l_shipmode")
        .agg(
            col("o_orderpriority")
            .filter(col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
            .count()
            .alias("high_line_count"),
            col("o_orderpriority")
            .filter(~col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
            .count()
            .alias("low_line_count"),
        )
        .sort("l_shipmode")
    )


def q12_v10_pandas_impl(ctx: DataFrameContext) -> Any:
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Use OR of equality checks instead of isin for shipmode
    filtered = lineitem[
        ((lineitem["l_shipmode"] == shipmode1) | (lineitem["l_shipmode"] == shipmode2))
        & (lineitem["l_commitdate"] < lineitem["l_receiptdate"])
        & (lineitem["l_shipdate"] < lineitem["l_commitdate"])
        & (lineitem["l_receiptdate"] >= start_date)
        & (lineitem["l_receiptdate"] < end_date)
    ]
    joined = filtered.merge(orders, left_on="l_orderkey", right_on="o_orderkey").copy()
    joined["high_priority"] = joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"]).astype(int)
    joined["low_priority"] = (~joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"])).astype(int)

    return (
        joined.groupby("l_shipmode", as_index=False)
        .agg(high_line_count=("high_priority", "sum"), low_line_count=("low_priority", "sum"))
        .sort_values("l_shipmode")
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_IMPL_PAIRS = [
    (q12_v1_expression_impl, q12_v1_pandas_impl),
    (q12_v2_expression_impl, q12_v2_pandas_impl),
    (q12_v3_expression_impl, q12_v3_pandas_impl),
    (q12_v4_expression_impl, q12_v4_pandas_impl),
    (q12_v5_expression_impl, q12_v5_pandas_impl),
    (q12_v6_expression_impl, q12_v6_pandas_impl),
    (q12_v7_expression_impl, q12_v7_pandas_impl),
    (q12_v8_expression_impl, q12_v8_pandas_impl),
    (q12_v9_expression_impl, q12_v9_pandas_impl),
    (q12_v10_expression_impl, q12_v10_pandas_impl),
]

_DESCRIPTIONS = [
    "Baseline: direct delegation to TPC-H Q12 implementation",
    "Pre-filter: apply all lineitem predicates before joining orders",
    "Column prune: select only needed columns before joining",
    "Intermediate vars: explicit DataFrames for filter, join, agg, sort steps",
    "Pre-compute derived: add priority flag columns before groupby",
    "Chained style: maximum method chaining, no named intermediates",
    "Join reorder: join orders first, then apply lineitem filters",
    "Filter combination: split mode filter and date filters as separate calls",
    "Explicit sort: descending=[False] passed explicitly",
    "Alternative formula: OR of equality checks instead of is_in for shipmode",
]

Q12_VARIANTS: list[DataFrameQuery] = [
    DataFrameQuery(
        query_id=f"Q12v{v}",
        query_name=f"TPC-H Q12 Variant {v}",
        description=_DESCRIPTIONS[v - 1],
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=expr_impl,
        pandas_impl=pandas_impl,
    )
    for v, (expr_impl, pandas_impl) in enumerate(_IMPL_PAIRS, start=1)
]
