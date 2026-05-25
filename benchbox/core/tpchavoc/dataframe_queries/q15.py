"""TPC-Havoc DataFrame variants for Q15.

Implements 10 structurally diverse variants of TPC-H Q15 (Top Supplier).
Q15 computes revenue per supplier, finds the max via scalar extraction,
then returns supplier(s) matching that max - a classic top-N via scalar subquery.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q15_expression_impl as _q15_expr_base,
    q15_pandas_impl as _q15_pandas_base,
)
from benchbox.core.tpchavoc.dataframe_queries.loader import JOIN_AGG_SUBQUERY, build_yaml_variants

# ---------------------------------------------------------------------------
# v1: baseline - delegate directly to TPC-H base implementation
# ---------------------------------------------------------------------------


def q15_v1_expression_impl(ctx: DataFrameContext) -> Any:
    return _q15_expr_base(ctx)


def q15_v1_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q15_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v2: pre-filter - filter lineitem before revenue aggregation
# ---------------------------------------------------------------------------


def q15_v2_expression_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(15)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Explicit pre-filter before aggregation
    filtered = lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
    revenue = filtered.group_by(col("l_suppkey").alias("supplier_no")).agg(
        (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("total_revenue")
    )

    max_revenue = ctx.scalar(revenue.select(col("total_revenue").max().alias("max_rev")))

    return (
        supplier.join(revenue, left_on="s_suppkey", right_on="supplier_no")
        .filter(col("total_revenue") == lit(max_revenue))
        .select("s_suppkey", "s_name", "s_address", "s_phone", "total_revenue")
        .sort("s_suppkey")
    )


def q15_v2_pandas_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(15)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Explicit pre-filter step
    filtered = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)].copy()
    filtered["revenue"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])

    revenue = (
        filtered.groupby("l_suppkey", as_index=False)
        .agg(total_revenue=("revenue", "sum"))
        .rename(columns={"l_suppkey": "supplier_no"})
    )

    max_revenue = revenue["total_revenue"].max()
    max_revenue = max_revenue.compute() if hasattr(max_revenue, "compute") else max_revenue

    top_suppliers = revenue[revenue["total_revenue"] == max_revenue]
    return supplier.merge(top_suppliers, left_on="s_suppkey", right_on="supplier_no")[
        ["s_suppkey", "s_name", "s_address", "s_phone", "total_revenue"]
    ].sort_values("s_suppkey")


# ---------------------------------------------------------------------------
# v3: column prune - select only needed columns before computing revenue
# ---------------------------------------------------------------------------


def q15_v3_expression_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(15)
    start_date = params["start_date"]
    end_date = params["end_date"]

    revenue = (
        lineitem.select("l_suppkey", "l_extendedprice", "l_discount", "l_shipdate")
        .filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
        .group_by(col("l_suppkey").alias("supplier_no"))
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("total_revenue"))
    )

    max_revenue = ctx.scalar(revenue.select(col("total_revenue").max().alias("max_rev")))

    return (
        supplier.select("s_suppkey", "s_name", "s_address", "s_phone")
        .join(revenue, left_on="s_suppkey", right_on="supplier_no")
        .filter(col("total_revenue") == lit(max_revenue))
        .select("s_suppkey", "s_name", "s_address", "s_phone", "total_revenue")
        .sort("s_suppkey")
    )


def q15_v3_pandas_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(15)
    start_date = params["start_date"]
    end_date = params["end_date"]

    li = lineitem[["l_suppkey", "l_extendedprice", "l_discount", "l_shipdate"]]
    s = supplier[["s_suppkey", "s_name", "s_address", "s_phone"]]

    filtered = li[(li["l_shipdate"] >= start_date) & (li["l_shipdate"] < end_date)].copy()
    filtered["revenue"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])

    revenue = (
        filtered.groupby("l_suppkey", as_index=False)
        .agg(total_revenue=("revenue", "sum"))
        .rename(columns={"l_suppkey": "supplier_no"})
    )

    max_revenue = revenue["total_revenue"].max()
    max_revenue = max_revenue.compute() if hasattr(max_revenue, "compute") else max_revenue

    top_suppliers = revenue[revenue["total_revenue"] == max_revenue]
    return s.merge(top_suppliers, left_on="s_suppkey", right_on="supplier_no")[
        ["s_suppkey", "s_name", "s_address", "s_phone", "total_revenue"]
    ].sort_values("s_suppkey")


# ---------------------------------------------------------------------------
# v4: intermediate vars - explicit named DataFrames for each step
# ---------------------------------------------------------------------------


def q15_v4_expression_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(15)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Step 1: filter lineitem
    filtered_li = lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
    # Step 2: compute revenue per supplier
    revenue = filtered_li.group_by(col("l_suppkey").alias("supplier_no")).agg(
        (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("total_revenue")
    )
    # Step 3: find max revenue
    max_revenue = ctx.scalar(revenue.select(col("total_revenue").max().alias("max_rev")))
    # Step 4: filter to top suppliers
    top_revenue = revenue.filter(col("total_revenue") == lit(max_revenue))
    # Step 5: join with suppliers
    return (
        supplier.join(top_revenue, left_on="s_suppkey", right_on="supplier_no")
        .select("s_suppkey", "s_name", "s_address", "s_phone", "total_revenue")
        .sort("s_suppkey")
    )


def q15_v4_pandas_impl(ctx: DataFrameContext) -> Any:
    return q15_v2_pandas_impl(ctx)


# ---------------------------------------------------------------------------
# v5: pre-compute derived - add revenue column before groupby
# ---------------------------------------------------------------------------


def q15_v5_expression_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(15)
    start_date = params["start_date"]
    end_date = params["end_date"]

    revenue = (
        lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
        .with_columns(
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("line_revenue"),
        )
        .group_by(col("l_suppkey").alias("supplier_no"))
        .agg(col("line_revenue").sum().alias("total_revenue"))
    )

    max_revenue = ctx.scalar(revenue.select(col("total_revenue").max().alias("max_rev")))

    return (
        supplier.join(revenue, left_on="s_suppkey", right_on="supplier_no")
        .filter(col("total_revenue") == lit(max_revenue))
        .select("s_suppkey", "s_name", "s_address", "s_phone", "total_revenue")
        .sort("s_suppkey")
    )


def q15_v5_pandas_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(15)
    start_date = params["start_date"]
    end_date = params["end_date"]

    filtered = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)].copy()
    # Pre-compute line_revenue column before groupby
    filtered["line_revenue"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])

    revenue = (
        filtered.groupby("l_suppkey", as_index=False)
        .agg(total_revenue=("line_revenue", "sum"))
        .rename(columns={"l_suppkey": "supplier_no"})
    )

    max_revenue = revenue["total_revenue"].max()
    max_revenue = max_revenue.compute() if hasattr(max_revenue, "compute") else max_revenue

    top_suppliers = revenue[revenue["total_revenue"] == max_revenue]
    return supplier.merge(top_suppliers, left_on="s_suppkey", right_on="supplier_no")[
        ["s_suppkey", "s_name", "s_address", "s_phone", "total_revenue"]
    ].sort_values("s_suppkey")


# ---------------------------------------------------------------------------
# v6: chained style - maximum method chaining
# ---------------------------------------------------------------------------


def q15_v6_expression_impl(ctx: DataFrameContext) -> Any:
    col = ctx.col
    lit = ctx.lit
    p = get_tpch_parameters(15)

    revenue = (
        ctx.get_table("lineitem")
        .filter((col("l_shipdate") >= lit(p["start_date"])) & (col("l_shipdate") < lit(p["end_date"])))
        .group_by(col("l_suppkey").alias("supplier_no"))
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("total_revenue"))
    )

    max_revenue = ctx.scalar(revenue.select(col("total_revenue").max().alias("max_rev")))

    return (
        ctx.get_table("supplier")
        .join(revenue, left_on="s_suppkey", right_on="supplier_no")
        .filter(col("total_revenue") == lit(max_revenue))
        .select("s_suppkey", "s_name", "s_address", "s_phone", "total_revenue")
        .sort("s_suppkey")
    )


def q15_v6_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q15_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v7: join reorder - join from revenue to supplier (reversed)
# ---------------------------------------------------------------------------


def q15_v7_expression_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(15)
    start_date = params["start_date"]
    end_date = params["end_date"]

    revenue = (
        lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
        .group_by(col("l_suppkey").alias("supplier_no"))
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("total_revenue"))
    )

    max_revenue = ctx.scalar(revenue.select(col("total_revenue").max().alias("max_rev")))

    # Reversed join: revenue → supplier
    return (
        revenue.filter(col("total_revenue") == lit(max_revenue))
        .join(supplier, left_on="supplier_no", right_on="s_suppkey")
        .select("s_suppkey", "s_name", "s_address", "s_phone", "total_revenue")
        .sort("s_suppkey")
    )


def q15_v7_pandas_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(15)
    start_date = params["start_date"]
    end_date = params["end_date"]

    filtered = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)].copy()
    filtered["revenue"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])

    revenue = (
        filtered.groupby("l_suppkey", as_index=False)
        .agg(total_revenue=("revenue", "sum"))
        .rename(columns={"l_suppkey": "supplier_no"})
    )

    max_revenue = revenue["total_revenue"].max()
    max_revenue = max_revenue.compute() if hasattr(max_revenue, "compute") else max_revenue

    # Reversed: filter revenue first, then join supplier
    top_revenue = revenue[revenue["total_revenue"] == max_revenue]
    return top_revenue.merge(supplier, left_on="supplier_no", right_on="s_suppkey")[
        ["s_suppkey", "s_name", "s_address", "s_phone", "total_revenue"]
    ].sort_values("s_suppkey")


# ---------------------------------------------------------------------------
# v8: filter combination - apply date range as two separate filters
# ---------------------------------------------------------------------------


def q15_v8_expression_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(15)
    start_date = params["start_date"]
    end_date = params["end_date"]

    revenue = (
        lineitem.filter(col("l_shipdate") >= lit(start_date))
        .filter(col("l_shipdate") < lit(end_date))
        .group_by(col("l_suppkey").alias("supplier_no"))
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("total_revenue"))
    )

    max_revenue = ctx.scalar(revenue.select(col("total_revenue").max().alias("max_rev")))

    return (
        supplier.join(revenue, left_on="s_suppkey", right_on="supplier_no")
        .filter(col("total_revenue") == lit(max_revenue))
        .select("s_suppkey", "s_name", "s_address", "s_phone", "total_revenue")
        .sort("s_suppkey")
    )


def q15_v8_pandas_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(15)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Split date filter into separate steps
    step1 = lineitem[lineitem["l_shipdate"] >= start_date]
    filtered = step1[step1["l_shipdate"] < end_date].copy()
    filtered["revenue"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])

    revenue = (
        filtered.groupby("l_suppkey", as_index=False)
        .agg(total_revenue=("revenue", "sum"))
        .rename(columns={"l_suppkey": "supplier_no"})
    )

    max_revenue = revenue["total_revenue"].max()
    max_revenue = max_revenue.compute() if hasattr(max_revenue, "compute") else max_revenue

    top_suppliers = revenue[revenue["total_revenue"] == max_revenue]
    return supplier.merge(top_suppliers, left_on="s_suppkey", right_on="supplier_no")[
        ["s_suppkey", "s_name", "s_address", "s_phone", "total_revenue"]
    ].sort_values("s_suppkey")


# ---------------------------------------------------------------------------
# v9: explicit sort - pass ascending=[True] explicitly
# ---------------------------------------------------------------------------


def q15_v9_expression_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(15)
    start_date = params["start_date"]
    end_date = params["end_date"]

    revenue = (
        lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
        .group_by(col("l_suppkey").alias("supplier_no"))
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("total_revenue"))
    )

    max_revenue = ctx.scalar(revenue.select(col("total_revenue").max().alias("max_rev")))

    return (
        supplier.join(revenue, left_on="s_suppkey", right_on="supplier_no")
        .filter(col("total_revenue") == lit(max_revenue))
        .select("s_suppkey", "s_name", "s_address", "s_phone", "total_revenue")
        .sort(["s_suppkey"], descending=[False])
    )


def q15_v9_pandas_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(15)
    start_date = params["start_date"]
    end_date = params["end_date"]

    filtered = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)].copy()
    filtered["revenue"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])

    revenue = (
        filtered.groupby("l_suppkey", as_index=False)
        .agg(total_revenue=("revenue", "sum"))
        .rename(columns={"l_suppkey": "supplier_no"})
    )

    max_revenue = revenue["total_revenue"].max()
    max_revenue = max_revenue.compute() if hasattr(max_revenue, "compute") else max_revenue

    top_suppliers = revenue[revenue["total_revenue"] == max_revenue]
    return supplier.merge(top_suppliers, left_on="s_suppkey", right_on="supplier_no")[
        ["s_suppkey", "s_name", "s_address", "s_phone", "total_revenue"]
    ].sort_values("s_suppkey", ascending=[True])


# ---------------------------------------------------------------------------
# v10: alternative formula - price - price*disc instead of price*(1-disc)
# ---------------------------------------------------------------------------


def q15_v10_expression_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(15)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Alternative: price - price*disc
    revenue = (
        lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
        .group_by(col("l_suppkey").alias("supplier_no"))
        .agg((col("l_extendedprice") - col("l_extendedprice") * col("l_discount")).sum().alias("total_revenue"))
    )

    max_revenue = ctx.scalar(revenue.select(col("total_revenue").max().alias("max_rev")))

    return (
        supplier.join(revenue, left_on="s_suppkey", right_on="supplier_no")
        .filter(col("total_revenue") == lit(max_revenue))
        .select("s_suppkey", "s_name", "s_address", "s_phone", "total_revenue")
        .sort("s_suppkey")
    )


def q15_v10_pandas_impl(ctx: DataFrameContext) -> Any:
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(15)
    start_date = params["start_date"]
    end_date = params["end_date"]

    filtered = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)].copy()
    # Alternative formula: price - price*disc
    filtered["revenue"] = filtered["l_extendedprice"] - filtered["l_extendedprice"] * filtered["l_discount"]

    revenue = (
        filtered.groupby("l_suppkey", as_index=False)
        .agg(total_revenue=("revenue", "sum"))
        .rename(columns={"l_suppkey": "supplier_no"})
    )

    max_revenue = revenue["total_revenue"].max()
    max_revenue = max_revenue.compute() if hasattr(max_revenue, "compute") else max_revenue

    top_suppliers = revenue[revenue["total_revenue"] == max_revenue]
    return supplier.merge(top_suppliers, left_on="s_suppkey", right_on="supplier_no")[
        ["s_suppkey", "s_name", "s_address", "s_phone", "total_revenue"]
    ].sort_values("s_suppkey")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

Q15_VARIANTS = build_yaml_variants(__file__, globals(), 15, JOIN_AGG_SUBQUERY)
