"""TPC-Havoc DataFrame variants for Q6.

Implements 10 structurally diverse variants of TPC-H Q6 (Forecasting Revenue Change).
Q6 is a single-table filter + scalar aggregate (no joins, no groupby).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q6_expression_impl as _q6_expr_base,
    q6_pandas_impl as _q6_pandas_base,
)

# ---------------------------------------------------------------------------
# v1: baseline
# ---------------------------------------------------------------------------


def q6_v1_expression_impl(ctx: DataFrameContext) -> Any:
    return _q6_expr_base(ctx)


def q6_v1_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q6_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v2: pre-filter - apply each WHERE clause separately before revenue computation
# ---------------------------------------------------------------------------


def q6_v2_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    # Apply each predicate separately
    filtered = (
        lineitem.filter(col("l_shipdate") >= lit(start_date))
        .filter(col("l_shipdate") < lit(end_date))
        .filter(col("l_discount") >= lit(discount_low))
        .filter(col("l_discount") <= lit(discount_high))
        .filter(col("l_quantity") < lit(quantity_limit))
    )
    return filtered.select((col("l_extendedprice") * col("l_discount")).alias("revenue")).sum()


def q6_v2_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    # Chained boolean masks applied sequentially
    mask = lineitem["l_shipdate"] >= start_date
    mask = mask & (lineitem["l_shipdate"] < end_date)
    mask = mask & (lineitem["l_discount"] >= discount_low)
    mask = mask & (lineitem["l_discount"] <= discount_high)
    mask = mask & (lineitem["l_quantity"] < quantity_limit)
    filtered = lineitem[mask]

    revenue = (filtered["l_extendedprice"] * filtered["l_discount"]).sum()
    revenue_val = revenue.compute() if hasattr(revenue, "compute") else revenue
    return pd.DataFrame({"revenue": [revenue_val]})


# ---------------------------------------------------------------------------
# v3: column prune - select only needed columns before filtering
# ---------------------------------------------------------------------------


def q6_v3_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    needed = ["l_shipdate", "l_discount", "l_quantity", "l_extendedprice"]
    return (
        lineitem.select(needed)
        .filter(
            (col("l_shipdate") >= lit(start_date))
            & (col("l_shipdate") < lit(end_date))
            & (col("l_discount") >= lit(discount_low))
            & (col("l_discount") <= lit(discount_high))
            & (col("l_quantity") < lit(quantity_limit))
        )
        .select((col("l_extendedprice") * col("l_discount")).alias("revenue"))
        .sum()
    )


def q6_v3_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    needed = ["l_shipdate", "l_discount", "l_quantity", "l_extendedprice"]
    pruned = lineitem[needed]
    filtered = pruned[
        (pruned["l_shipdate"] >= start_date)
        & (pruned["l_shipdate"] < end_date)
        & (pruned["l_discount"] >= discount_low)
        & (pruned["l_discount"] <= discount_high)
        & (pruned["l_quantity"] < quantity_limit)
    ]
    revenue = (filtered["l_extendedprice"] * filtered["l_discount"]).sum()
    revenue_val = revenue.compute() if hasattr(revenue, "compute") else revenue
    return pd.DataFrame({"revenue": [revenue_val]})


# ---------------------------------------------------------------------------
# v4: intermediate vars - named intermediate DataFrames for each step
# ---------------------------------------------------------------------------


def q6_v4_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    # Step 1: date filter
    date_filtered = lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
    # Step 2: discount filter
    discount_filtered = date_filtered.filter(
        (col("l_discount") >= lit(discount_low)) & (col("l_discount") <= lit(discount_high))
    )
    # Step 3: quantity filter
    final_filtered = discount_filtered.filter(col("l_quantity") < lit(quantity_limit))
    # Step 4: compute revenue
    return final_filtered.select((col("l_extendedprice") * col("l_discount")).alias("revenue")).sum()


def q6_v4_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    date_filtered = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)]
    discount_filtered = date_filtered[
        (date_filtered["l_discount"] >= discount_low) & (date_filtered["l_discount"] <= discount_high)
    ]
    final_filtered = discount_filtered[discount_filtered["l_quantity"] < quantity_limit]
    revenue = (final_filtered["l_extendedprice"] * final_filtered["l_discount"]).sum()
    revenue_val = revenue.compute() if hasattr(revenue, "compute") else revenue
    return pd.DataFrame({"revenue": [revenue_val]})


# ---------------------------------------------------------------------------
# v5: pre-compute derived - add revenue column before summing
# ---------------------------------------------------------------------------


def q6_v5_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    return (
        lineitem.filter(
            (col("l_shipdate") >= lit(start_date))
            & (col("l_shipdate") < lit(end_date))
            & (col("l_discount") >= lit(discount_low))
            & (col("l_discount") <= lit(discount_high))
            & (col("l_quantity") < lit(quantity_limit))
        )
        .with_columns((col("l_extendedprice") * col("l_discount")).alias("revenue"))
        .select("revenue")
        .sum()
    )


def q6_v5_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    filtered = lineitem[
        (lineitem["l_shipdate"] >= start_date)
        & (lineitem["l_shipdate"] < end_date)
        & (lineitem["l_discount"] >= discount_low)
        & (lineitem["l_discount"] <= discount_high)
        & (lineitem["l_quantity"] < quantity_limit)
    ].copy()
    # Pre-compute derived column
    filtered["revenue"] = filtered["l_extendedprice"] * filtered["l_discount"]
    revenue_val = filtered["revenue"].sum()
    revenue_val = revenue_val.compute() if hasattr(revenue_val, "compute") else revenue_val
    return pd.DataFrame({"revenue": [revenue_val]})


# ---------------------------------------------------------------------------
# v6: chained style - maximum chaining, no intermediate variables
# ---------------------------------------------------------------------------


def q6_v6_expression_impl(ctx: DataFrameContext) -> Any:
    col = ctx.col
    lit = ctx.lit
    p = get_tpch_parameters(6)
    return (
        ctx.get_table("lineitem")
        .filter(
            (col("l_shipdate") >= lit(p["start_date"]))
            & (col("l_shipdate") < lit(p["end_date"]))
            & (col("l_discount") >= lit(p["discount_low"]))
            & (col("l_discount") <= lit(p["discount_high"]))
            & (col("l_quantity") < lit(p["quantity_limit"]))
        )
        .select((col("l_extendedprice") * col("l_discount")).alias("revenue"))
        .sum()
    )


def q6_v6_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    p = get_tpch_parameters(6)
    li = ctx.get_table("lineitem")
    filtered = li[
        (li["l_shipdate"] >= p["start_date"])
        & (li["l_shipdate"] < p["end_date"])
        & (li["l_discount"] >= p["discount_low"])
        & (li["l_discount"] <= p["discount_high"])
        & (li["l_quantity"] < p["quantity_limit"])
    ]
    revenue = (filtered["l_extendedprice"] * filtered["l_discount"]).sum()
    revenue_val = revenue.compute() if hasattr(revenue, "compute") else revenue
    return pd.DataFrame({"revenue": [revenue_val]})


# ---------------------------------------------------------------------------
# v7: aggregation alternative - split into date-discount vs quantity filters
# ---------------------------------------------------------------------------


def q6_v7_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    # Split into discount+quantity filter first, then date filter
    by_discount_qty = lineitem.filter(
        (col("l_discount") >= lit(discount_low))
        & (col("l_discount") <= lit(discount_high))
        & (col("l_quantity") < lit(quantity_limit))
    )
    by_date = by_discount_qty.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
    return by_date.select((col("l_extendedprice") * col("l_discount")).alias("revenue")).sum()


def q6_v7_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    # Discount and quantity filter first
    by_discount_qty = lineitem[
        (lineitem["l_discount"] >= discount_low)
        & (lineitem["l_discount"] <= discount_high)
        & (lineitem["l_quantity"] < quantity_limit)
    ]
    # Then date filter
    filtered = by_discount_qty[
        (by_discount_qty["l_shipdate"] >= start_date) & (by_discount_qty["l_shipdate"] < end_date)
    ]

    revenue = (filtered["l_extendedprice"] * filtered["l_discount"]).sum()
    revenue_val = revenue.compute() if hasattr(revenue, "compute") else revenue
    return pd.DataFrame({"revenue": [revenue_val]})


# ---------------------------------------------------------------------------
# v8: filter combination - use AND of two compound predicates
# ---------------------------------------------------------------------------


def q6_v8_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    date_pred = (col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date))
    rest_pred = (
        (col("l_discount") >= lit(discount_low))
        & (col("l_discount") <= lit(discount_high))
        & (col("l_quantity") < lit(quantity_limit))
    )
    return (
        lineitem.filter(date_pred & rest_pred)
        .select((col("l_extendedprice") * col("l_discount")).alias("revenue"))
        .sum()
    )


def q6_v8_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    date_mask = (lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)
    rest_mask = (
        (lineitem["l_discount"] >= discount_low)
        & (lineitem["l_discount"] <= discount_high)
        & (lineitem["l_quantity"] < quantity_limit)
    )
    filtered = lineitem[date_mask & rest_mask]
    revenue = (filtered["l_extendedprice"] * filtered["l_discount"]).sum()
    revenue_val = revenue.compute() if hasattr(revenue, "compute") else revenue
    return pd.DataFrame({"revenue": [revenue_val]})


# ---------------------------------------------------------------------------
# v9: explicit sort (not applicable for scalar; use explicit select instead)
# ---------------------------------------------------------------------------


def q6_v9_expression_impl(ctx: DataFrameContext) -> Any:
    """Variant using explicit column selection before aggregation."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    # Explicit select of revenue expression, then alias and sum
    filtered = lineitem.filter(
        (col("l_shipdate") >= lit(start_date))
        & (col("l_shipdate") < lit(end_date))
        & (col("l_discount") >= lit(discount_low))
        & (col("l_discount") <= lit(discount_high))
        & (col("l_quantity") < lit(quantity_limit))
    )
    revenue_col = (col("l_extendedprice") * col("l_discount")).alias("revenue")
    return filtered.select(revenue_col).sum()


def q6_v9_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    filtered = lineitem[
        (lineitem["l_shipdate"] >= start_date)
        & (lineitem["l_shipdate"] < end_date)
        & (lineitem["l_discount"] >= discount_low)
        & (lineitem["l_discount"] <= discount_high)
        & (lineitem["l_quantity"] < quantity_limit)
    ]
    # Explicit assignment into a new column before summing
    revenue_series = filtered["l_extendedprice"] * filtered["l_discount"]
    revenue_val = revenue_series.sum()
    revenue_val = revenue_val.compute() if hasattr(revenue_val, "compute") else revenue_val
    return pd.DataFrame({"revenue": [revenue_val]})


# ---------------------------------------------------------------------------
# v10: alternative formula - price*(1-disc) != price*disc but here Q6 is
#      specifically revenue = price*discount; algebraic alt: disc*(price)
# ---------------------------------------------------------------------------


def q6_v10_expression_impl(ctx: DataFrameContext) -> Any:
    """Alternative formula: revenue computed as disc * price (commutative)."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    return (
        lineitem.filter(
            (col("l_shipdate") >= lit(start_date))
            & (col("l_shipdate") < lit(end_date))
            & (col("l_discount") >= lit(discount_low))
            & (col("l_discount") <= lit(discount_high))
            & (col("l_quantity") < lit(quantity_limit))
        )
        # Commuted: discount * extendedprice instead of extendedprice * discount
        .select((col("l_discount") * col("l_extendedprice")).alias("revenue"))
        .sum()
    )


def q6_v10_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    filtered = lineitem[
        (lineitem["l_shipdate"] >= start_date)
        & (lineitem["l_shipdate"] < end_date)
        & (lineitem["l_discount"] >= discount_low)
        & (lineitem["l_discount"] <= discount_high)
        & (lineitem["l_quantity"] < quantity_limit)
    ]
    # Commuted multiplication
    revenue = (filtered["l_discount"] * filtered["l_extendedprice"]).sum()
    revenue_val = revenue.compute() if hasattr(revenue, "compute") else revenue
    return pd.DataFrame({"revenue": [revenue_val]})


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

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

Q6_VARIANTS: list[DataFrameQuery] = [
    DataFrameQuery(
        query_id=f"Q6v{v}",
        query_name=f"TPC-H Q6 Variant {v}",
        description=_DESCRIPTIONS[v - 1],
        categories=[QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=expr_impl,
        pandas_impl=pandas_impl,
    )
    for v, (expr_impl, pandas_impl) in enumerate(_IMPL_PAIRS, start=1)
]
