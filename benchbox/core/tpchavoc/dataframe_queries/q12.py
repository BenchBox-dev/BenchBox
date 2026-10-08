# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q12_expression_impl as _q12_expr_base,
    q12_pandas_impl as _q12_pandas_base,
)
from benchbox.core.tpchavoc.dataframe_queries.loader import JOIN_AGG_FILTER, build_yaml_variants


def q12_v1_expression_impl(ctx: DataFrameContext) -> Any:
    return _q12_expr_base(ctx)


def q12_v1_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q12_pandas_base(ctx)


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

    step1 = lineitem.filter(
        col("l_shipmode").is_in([shipmode1, shipmode2])
        & (col("l_commitdate") < col("l_receiptdate"))
        & (col("l_shipdate") < col("l_commitdate"))
        & (col("l_receiptdate") >= lit(start_date))
        & (col("l_receiptdate") < lit(end_date))
    )
    step2 = step1.join(orders, left_on="l_orderkey", right_on="o_orderkey")
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
    return step3.sort("l_shipmode")


def q12_v4_pandas_impl(ctx: DataFrameContext) -> Any:
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
    aggregated = joined.groupby("l_shipmode", as_index=False).agg(
        high_line_count=("high_priority", "sum"), low_line_count=("low_priority", "sum")
    )
    return aggregated.sort_values("l_shipmode")


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
    joined["high_priority"] = joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"]).astype(int)
    joined["low_priority"] = (~joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"])).astype(int)

    return (
        joined.groupby("l_shipmode", as_index=False)
        .agg(high_line_count=("high_priority", "sum"), low_line_count=("low_priority", "sum"))
        .sort_values("l_shipmode")
    )


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


Q12_VARIANTS = build_yaml_variants(__file__, globals(), 12, JOIN_AGG_FILTER)
