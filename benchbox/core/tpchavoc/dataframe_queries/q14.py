"""TPC-Havoc DataFrame variants for Q14.

Implements 10 structurally diverse variants of TPC-H Q14 (Promotion Effect).
Q14 joins lineitem and part, filters by date, and computes the percentage of
revenue from promotional parts using CASE WHEN / conditional sum logic.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q14_expression_impl as _q14_expr_base,
    q14_pandas_impl as _q14_pandas_base,
)

# ---------------------------------------------------------------------------
# v1: baseline - delegate directly to TPC-H base implementation
# ---------------------------------------------------------------------------


def q14_v1_expression_impl(ctx: DataFrameContext) -> Any:
    return _q14_expr_base(ctx)


def q14_v1_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q14_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v2: pre-filter - filter lineitem before joining part
# ---------------------------------------------------------------------------


def q14_v2_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Pre-filter lineitem before joining
    filtered = lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))

    return filtered.join(part, left_on="l_partkey", right_on="p_partkey").select(
        (
            lit(100.0)
            * (col("l_extendedprice") * (lit(1) - col("l_discount")))
            .filter(col("p_type").str.starts_with("PROMO"))
            .sum()
            / (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum()
        ).alias("promo_revenue")
    )


def q14_v2_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Explicit pre-filter step
    filtered = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)]
    joined = filtered.merge(part, left_on="l_partkey", right_on="p_partkey").copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])
    joined["promo_revenue"] = joined["revenue"] * joined["p_type"].str.startswith("PROMO").astype(float)

    total_revenue = joined["revenue"].sum()
    promo_revenue = joined["promo_revenue"].sum()
    total_val = total_revenue.compute() if hasattr(total_revenue, "compute") else total_revenue
    promo_val = promo_revenue.compute() if hasattr(promo_revenue, "compute") else promo_revenue
    promo_percent = 100.0 * promo_val / total_val if total_val > 0 else 0

    return pd.DataFrame({"promo_revenue": [promo_percent]})


# ---------------------------------------------------------------------------
# v3: column prune - select only needed columns before joining
# ---------------------------------------------------------------------------


def q14_v3_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    return (
        lineitem.select("l_partkey", "l_extendedprice", "l_discount", "l_shipdate")
        .filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
        .join(part.select("p_partkey", "p_type"), left_on="l_partkey", right_on="p_partkey")
        .select(
            (
                lit(100.0)
                * (col("l_extendedprice") * (lit(1) - col("l_discount")))
                .filter(col("p_type").str.starts_with("PROMO"))
                .sum()
                / (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum()
            ).alias("promo_revenue")
        )
    )


def q14_v3_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    li = lineitem[["l_partkey", "l_extendedprice", "l_discount", "l_shipdate"]]
    p = part[["p_partkey", "p_type"]]

    filtered = li[(li["l_shipdate"] >= start_date) & (li["l_shipdate"] < end_date)]
    joined = filtered.merge(p, left_on="l_partkey", right_on="p_partkey").copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])
    joined["promo_revenue"] = joined["revenue"] * joined["p_type"].str.startswith("PROMO").astype(float)

    total_val = joined["revenue"].sum()
    promo_val = joined["promo_revenue"].sum()
    total_val = total_val.compute() if hasattr(total_val, "compute") else total_val
    promo_val = promo_val.compute() if hasattr(promo_val, "compute") else promo_val
    promo_percent = 100.0 * promo_val / total_val if total_val > 0 else 0

    return pd.DataFrame({"promo_revenue": [promo_percent]})


# ---------------------------------------------------------------------------
# v4: intermediate vars - explicit DataFrames for each step
# ---------------------------------------------------------------------------


def q14_v4_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Step 1: filter lineitem
    step1 = lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
    # Step 2: join with part
    step2 = step1.join(part, left_on="l_partkey", right_on="p_partkey")
    # Step 3: calculate promo revenue
    result = step2.select(
        (
            lit(100.0)
            * (col("l_extendedprice") * (lit(1) - col("l_discount")))
            .filter(col("p_type").str.starts_with("PROMO"))
            .sum()
            / (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum()
        ).alias("promo_revenue")
    )
    return result


def q14_v4_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Step 1: filter
    filtered = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)]
    # Step 2: join
    joined = filtered.merge(part, left_on="l_partkey", right_on="p_partkey").copy()
    # Step 3: derive columns
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])
    joined["promo_revenue"] = joined["revenue"] * joined["p_type"].str.startswith("PROMO").astype(float)
    # Step 4: compute scalars
    total_val = joined["revenue"].sum()
    promo_val = joined["promo_revenue"].sum()
    total_val = total_val.compute() if hasattr(total_val, "compute") else total_val
    promo_val = promo_val.compute() if hasattr(promo_val, "compute") else promo_val
    promo_percent = 100.0 * promo_val / total_val if total_val > 0 else 0
    return pd.DataFrame({"promo_revenue": [promo_percent]})


# ---------------------------------------------------------------------------
# v5: pre-compute derived - compute revenue column before selecting
# ---------------------------------------------------------------------------


def q14_v5_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    return (
        lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
        .join(part, left_on="l_partkey", right_on="p_partkey")
        .with_columns(
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("revenue"),
        )
        .select(
            (
                lit(100.0) * col("revenue").filter(col("p_type").str.starts_with("PROMO")).sum() / col("revenue").sum()
            ).alias("promo_revenue")
        )
    )


def q14_v5_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    filtered = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)]
    joined = filtered.merge(part, left_on="l_partkey", right_on="p_partkey").copy()
    # Pre-compute revenue column before the promo calculation
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])
    joined["is_promo"] = joined["p_type"].str.startswith("PROMO").astype(float)
    joined["promo_revenue"] = joined["revenue"] * joined["is_promo"]

    total_val = joined["revenue"].sum()
    promo_val = joined["promo_revenue"].sum()
    total_val = total_val.compute() if hasattr(total_val, "compute") else total_val
    promo_val = promo_val.compute() if hasattr(promo_val, "compute") else promo_val
    promo_percent = 100.0 * promo_val / total_val if total_val > 0 else 0

    return pd.DataFrame({"promo_revenue": [promo_percent]})


# ---------------------------------------------------------------------------
# v6: chained style - maximum method chaining
# ---------------------------------------------------------------------------


def q14_v6_expression_impl(ctx: DataFrameContext) -> Any:
    col = ctx.col
    lit = ctx.lit
    p = get_tpch_parameters(14)
    return (
        ctx.get_table("lineitem")
        .filter((col("l_shipdate") >= lit(p["start_date"])) & (col("l_shipdate") < lit(p["end_date"])))
        .join(ctx.get_table("part"), left_on="l_partkey", right_on="p_partkey")
        .select(
            (
                lit(100.0)
                * (col("l_extendedprice") * (lit(1) - col("l_discount")))
                .filter(col("p_type").str.starts_with("PROMO"))
                .sum()
                / (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum()
            ).alias("promo_revenue")
        )
    )


def q14_v6_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Chained style - single expression chain mirroring the expression impl
    joined = (
        ctx.get_table("lineitem")
        .loc[lambda df: (df["l_shipdate"] >= start_date) & (df["l_shipdate"] < end_date)]
        .merge(ctx.get_table("part"), left_on="l_partkey", right_on="p_partkey")
        .assign(revenue=lambda df: df["l_extendedprice"] * (1 - df["l_discount"]))
        .assign(promo_revenue=lambda df: df["revenue"] * df["p_type"].str.startswith("PROMO").astype(float))
    )
    total_val = joined["revenue"].sum()
    promo_val = joined["promo_revenue"].sum()
    total_val = total_val.compute() if hasattr(total_val, "compute") else total_val
    promo_val = promo_val.compute() if hasattr(promo_val, "compute") else promo_val
    promo_percent = 100.0 * promo_val / total_val if total_val > 0 else 0

    return pd.DataFrame({"promo_revenue": [promo_percent]})


# ---------------------------------------------------------------------------
# v7: join reorder - start from part, join lineitem
# ---------------------------------------------------------------------------


def q14_v7_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Join from part → lineitem (reversed)
    return (
        part.join(lineitem, left_on="p_partkey", right_on="l_partkey")
        .filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
        .select(
            (
                lit(100.0)
                * (col("l_extendedprice") * (lit(1) - col("l_discount")))
                .filter(col("p_type").str.starts_with("PROMO"))
                .sum()
                / (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum()
            ).alias("promo_revenue")
        )
    )


def q14_v7_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Join from part → lineitem (reversed)
    joined = part.merge(lineitem, left_on="p_partkey", right_on="l_partkey")
    filtered = joined[(joined["l_shipdate"] >= start_date) & (joined["l_shipdate"] < end_date)].copy()
    filtered["revenue"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])
    filtered["promo_revenue"] = filtered["revenue"] * filtered["p_type"].str.startswith("PROMO").astype(float)

    total_val = filtered["revenue"].sum()
    promo_val = filtered["promo_revenue"].sum()
    total_val = total_val.compute() if hasattr(total_val, "compute") else total_val
    promo_val = promo_val.compute() if hasattr(promo_val, "compute") else promo_val
    promo_percent = 100.0 * promo_val / total_val if total_val > 0 else 0

    return pd.DataFrame({"promo_revenue": [promo_percent]})


# ---------------------------------------------------------------------------
# v8: filter combination - filter part for PROMO prefix before joining
# ---------------------------------------------------------------------------


def q14_v8_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Separate into promo and non-promo parts for dual join approach
    promo_parts = part.filter(col("p_type").str.starts_with("PROMO"))
    all_lineitem = lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))

    # Join all lineitem with part to get totals; join filtered lineitem with promo_parts for promo total
    total_rev = (
        all_lineitem.join(part, left_on="l_partkey", right_on="p_partkey")
        .select((col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("rev"))
        .select(col("rev").sum().alias("total"))
    )
    promo_rev = (
        all_lineitem.join(promo_parts, left_on="l_partkey", right_on="p_partkey")
        .select((col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("rev"))
        .select(col("rev").sum().alias("promo"))
    )

    # Combine single-row aggregates natively via cross join; return as
    # expression-family frame (no ctx.scalar(), no pandas dependency)
    return total_rev.join(promo_rev, how="cross").select(
        (lit(100.0) * col("promo") / col("total")).alias("promo_revenue")
    )


def q14_v8_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    filtered = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)]

    # Join with all parts first for total, then filter to promo only for promo total
    joined_all = filtered.merge(part, left_on="l_partkey", right_on="p_partkey").copy()
    joined_all["revenue"] = joined_all["l_extendedprice"] * (1 - joined_all["l_discount"])

    total_val = joined_all["revenue"].sum()
    total_val = total_val.compute() if hasattr(total_val, "compute") else total_val

    promo_mask = joined_all["p_type"].str.startswith("PROMO")
    promo_val = joined_all.loc[promo_mask, "revenue"].sum()
    promo_val = promo_val.compute() if hasattr(promo_val, "compute") else promo_val

    promo_percent = 100.0 * promo_val / total_val if total_val > 0 else 0
    return pd.DataFrame({"promo_revenue": [promo_percent]})


# ---------------------------------------------------------------------------
# v9: explicit sort - no sort needed for scalar; use different date check order
# ---------------------------------------------------------------------------


def q14_v9_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Check end_date condition first (different predicate ordering)
    return (
        lineitem.filter((col("l_shipdate") < lit(end_date)) & (col("l_shipdate") >= lit(start_date)))
        .join(part, left_on="l_partkey", right_on="p_partkey")
        .select(
            (
                lit(100.0)
                * (col("l_extendedprice") * (lit(1) - col("l_discount")))
                .filter(col("p_type").str.starts_with("PROMO"))
                .sum()
                / (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum()
            ).alias("promo_revenue")
        )
    )


def q14_v9_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Check end_date condition first (different predicate ordering)
    filtered = lineitem[(lineitem["l_shipdate"] < end_date) & (lineitem["l_shipdate"] >= start_date)]
    joined = filtered.merge(part, left_on="l_partkey", right_on="p_partkey").copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])
    joined["promo_revenue"] = joined["revenue"] * joined["p_type"].str.startswith("PROMO").astype(float)

    total_val = joined["revenue"].sum()
    promo_val = joined["promo_revenue"].sum()
    total_val = total_val.compute() if hasattr(total_val, "compute") else total_val
    promo_val = promo_val.compute() if hasattr(promo_val, "compute") else promo_val
    promo_percent = 100.0 * promo_val / total_val if total_val > 0 else 0

    return pd.DataFrame({"promo_revenue": [promo_percent]})


# ---------------------------------------------------------------------------
# v10: alternative formula - price - price*disc instead of price*(1-disc)
# ---------------------------------------------------------------------------


def q14_v10_expression_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Alternative: price - price*disc instead of price*(1-disc)
    rev_alt = col("l_extendedprice") - col("l_extendedprice") * col("l_discount")

    return (
        lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
        .join(part, left_on="l_partkey", right_on="p_partkey")
        .select(
            (lit(100.0) * rev_alt.filter(col("p_type").str.starts_with("PROMO")).sum() / rev_alt.sum()).alias(
                "promo_revenue"
            )
        )
    )


def q14_v10_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    filtered = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)]
    joined = filtered.merge(part, left_on="l_partkey", right_on="p_partkey").copy()
    # Alternative formula: price - price*disc
    joined["revenue"] = joined["l_extendedprice"] - joined["l_extendedprice"] * joined["l_discount"]
    joined["promo_revenue"] = joined["revenue"] * joined["p_type"].str.startswith("PROMO").astype(float)

    total_val = joined["revenue"].sum()
    promo_val = joined["promo_revenue"].sum()
    total_val = total_val.compute() if hasattr(total_val, "compute") else total_val
    promo_val = promo_val.compute() if hasattr(promo_val, "compute") else promo_val
    promo_percent = 100.0 * promo_val / total_val if total_val > 0 else 0

    return pd.DataFrame({"promo_revenue": [promo_percent]})


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_IMPL_PAIRS = [
    (q14_v1_expression_impl, q14_v1_pandas_impl),
    (q14_v2_expression_impl, q14_v2_pandas_impl),
    (q14_v3_expression_impl, q14_v3_pandas_impl),
    (q14_v4_expression_impl, q14_v4_pandas_impl),
    (q14_v5_expression_impl, q14_v5_pandas_impl),
    (q14_v6_expression_impl, q14_v6_pandas_impl),
    (q14_v7_expression_impl, q14_v7_pandas_impl),
    (q14_v8_expression_impl, q14_v8_pandas_impl),
    (q14_v9_expression_impl, q14_v9_pandas_impl),
    (q14_v10_expression_impl, q14_v10_pandas_impl),
]

_DESCRIPTIONS = [
    "Baseline: direct delegation to TPC-H Q14 implementation",
    "Pre-filter: filter lineitem by date before joining part",
    "Column prune: select only needed columns before joining",
    "Intermediate vars: explicit DataFrames for filter, join, compute steps",
    "Pre-compute derived: add revenue and is_promo columns before final select",
    "Chained style: maximum method chaining, no named intermediates",
    "Join reorder: start from part, join lineitem (reversed join direction)",
    "Filter combination: separate promo and non-promo parts for dual totals",
    "Explicit sort: end_date predicate checked first (different predicate ordering)",
    "Alternative formula: price - price*disc instead of price*(1-disc)",
]

Q14_VARIANTS: list[DataFrameQuery] = [
    DataFrameQuery(
        query_id=f"Q14v{v}",
        query_name=f"TPC-H Q14 Variant {v}",
        description=_DESCRIPTIONS[v - 1],
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=expr_impl,
        pandas_impl=pandas_impl,
    )
    for v, (expr_impl, pandas_impl) in enumerate(_IMPL_PAIRS, start=1)
]
