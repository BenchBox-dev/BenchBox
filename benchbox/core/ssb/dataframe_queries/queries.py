"""SSB DataFrame query implementations.

This module provides DataFrame implementations of all 13 Star Schema Benchmark queries
for both Expression and Pandas families.

SSB queries are organized into 4 flights:
- Flight 1 (Q1.1-Q1.3): Revenue aggregations (lineorder + date only)
- Flight 2 (Q2.1-Q2.3): Revenue by year and brand (lineorder + date + part + supplier)
- Flight 3 (Q3.1-Q3.4): Revenue by geography and year (lineorder + customer + supplier + date)
- Flight 4 (Q4.1-Q4.3): Profit by various dimensions (all 5 tables)

Schema: Star schema with lineorder fact table joined to date, customer, supplier, part dimensions.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from csv import reader
from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory

from .parameters import get_parameters
from .registry import register_query

# =============================================================================
# Flight 1: Revenue aggregations (lineorder + date)
# All compute SUM(lo_extendedprice * lo_discount) AS revenue - scalar result
# =============================================================================


def q1_1_expression_impl(ctx: DataFrameContext) -> Any:
    """SSB Q1.1: Revenue by year filter (Expression Family).

    Computes total revenue for a given year with discount and quantity filters.
    Tables: lineorder, date
    Pattern: 2-table join -> filter -> scalar aggregation
    """
    params = get_parameters("Q1.1")
    year = params.get("year", 1993)
    discount_min = params.get("discount_min", 1)
    discount_max = params.get("discount_max", 3)
    quantity = params.get("quantity", 25)

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineorder.join(date, left_on="lo_orderdate", right_on="d_datekey")
        .filter(
            (col("d_year") == lit(year))
            & (col("lo_discount") >= lit(discount_min))
            & (col("lo_discount") <= lit(discount_max))
            & (col("lo_quantity") < lit(quantity))
        )
        .select((col("lo_extendedprice") * col("lo_discount")).sum().alias("revenue"))
    )

    return result


def q1_1_pandas_impl(ctx: DataFrameContext) -> Any:
    """SSB Q1.1: Revenue by year filter (Pandas Family)."""
    params = get_parameters("Q1.1")
    year = params.get("year", 1993)
    discount_min = params.get("discount_min", 1)
    discount_max = params.get("discount_max", 3)
    quantity = params.get("quantity", 25)

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")

    merged = lineorder.merge(date, left_on="lo_orderdate", right_on="d_datekey")

    filtered = merged[
        (merged["d_year"] == year)
        & (merged["lo_discount"] >= discount_min)
        & (merged["lo_discount"] <= discount_max)
        & (merged["lo_quantity"] < quantity)
    ]

    import pandas as pd

    revenue = (filtered["lo_extendedprice"] * filtered["lo_discount"]).sum()
    if hasattr(revenue, "compute"):
        revenue = revenue.compute()

    return pd.DataFrame({"revenue": [revenue]})


def q1_2_expression_impl(ctx: DataFrameContext) -> Any:
    """SSB Q1.2: Revenue by year-month filter (Expression Family).

    Drill-down from year to year-month with quantity range filter.
    Tables: lineorder, date
    Pattern: 2-table join -> filter -> scalar aggregation
    """
    params = get_parameters("Q1.2")
    year_month = params.get("year_month", 199401)
    discount_min = params.get("discount_min", 1)
    discount_max = params.get("discount_max", 3)
    quantity_min = params.get("quantity_min", 26)
    quantity_max = params.get("quantity_max", 35)

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineorder.join(date, left_on="lo_orderdate", right_on="d_datekey")
        .filter(
            (col("d_yearmonthnum") == lit(year_month))
            & (col("lo_discount") >= lit(discount_min))
            & (col("lo_discount") <= lit(discount_max))
            & (col("lo_quantity") >= lit(quantity_min))
            & (col("lo_quantity") <= lit(quantity_max))
        )
        .select((col("lo_extendedprice") * col("lo_discount")).sum().alias("revenue"))
    )

    return result


def q1_2_pandas_impl(ctx: DataFrameContext) -> Any:
    """SSB Q1.2: Revenue by year-month filter (Pandas Family)."""
    params = get_parameters("Q1.2")
    year_month = params.get("year_month", 199401)
    discount_min = params.get("discount_min", 1)
    discount_max = params.get("discount_max", 3)
    quantity_min = params.get("quantity_min", 26)
    quantity_max = params.get("quantity_max", 35)

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")

    merged = lineorder.merge(date, left_on="lo_orderdate", right_on="d_datekey")

    filtered = merged[
        (merged["d_yearmonthnum"] == year_month)
        & (merged["lo_discount"] >= discount_min)
        & (merged["lo_discount"] <= discount_max)
        & (merged["lo_quantity"] >= quantity_min)
        & (merged["lo_quantity"] <= quantity_max)
    ]

    import pandas as pd

    revenue = (filtered["lo_extendedprice"] * filtered["lo_discount"]).sum()
    if hasattr(revenue, "compute"):
        revenue = revenue.compute()

    return pd.DataFrame({"revenue": [revenue]})


def q1_3_expression_impl(ctx: DataFrameContext) -> Any:
    """SSB Q1.3: Revenue by week filter (Expression Family).

    Drill-down from year-month to week-in-year with quantity range filter.
    Tables: lineorder, date
    Pattern: 2-table join -> filter -> scalar aggregation
    """
    params = get_parameters("Q1.3")
    week = params.get("week", 6)
    year = params.get("year", 1993)
    discount_min = params.get("discount_min", 1)
    discount_max = params.get("discount_max", 3)
    quantity_min = params.get("quantity_min", 26)
    quantity_max = params.get("quantity_max", 35)

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineorder.join(date, left_on="lo_orderdate", right_on="d_datekey")
        .filter(
            (col("d_weeknuminyear") == lit(week))
            & (col("d_year") == lit(year))
            & (col("lo_discount") >= lit(discount_min))
            & (col("lo_discount") <= lit(discount_max))
            & (col("lo_quantity") >= lit(quantity_min))
            & (col("lo_quantity") <= lit(quantity_max))
        )
        .select((col("lo_extendedprice") * col("lo_discount")).sum().alias("revenue"))
    )

    return result


def q1_3_pandas_impl(ctx: DataFrameContext) -> Any:
    """SSB Q1.3: Revenue by week filter (Pandas Family)."""
    params = get_parameters("Q1.3")
    week = params.get("week", 6)
    year = params.get("year", 1993)
    discount_min = params.get("discount_min", 1)
    discount_max = params.get("discount_max", 3)
    quantity_min = params.get("quantity_min", 26)
    quantity_max = params.get("quantity_max", 35)

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")

    merged = lineorder.merge(date, left_on="lo_orderdate", right_on="d_datekey")

    filtered = merged[
        (merged["d_weeknuminyear"] == week)
        & (merged["d_year"] == year)
        & (merged["lo_discount"] >= discount_min)
        & (merged["lo_discount"] <= discount_max)
        & (merged["lo_quantity"] >= quantity_min)
        & (merged["lo_quantity"] <= quantity_max)
    ]

    import pandas as pd

    revenue = (filtered["lo_extendedprice"] * filtered["lo_discount"]).sum()
    if hasattr(revenue, "compute"):
        revenue = revenue.compute()

    return pd.DataFrame({"revenue": [revenue]})


# =============================================================================
# Flight 2: Revenue by year and brand (lineorder + date + part + supplier)
# All compute SUM(lo_revenue) grouped by d_year, p_brand1
# =============================================================================


def q2_1_expression_impl(ctx: DataFrameContext) -> Any:
    """SSB Q2.1: Revenue by year/brand filtered by category and region (Expression Family).

    Reports revenue grouped by year and brand for a part category and supplier region.
    Tables: lineorder, date, part, supplier
    Pattern: 4-table join -> filter -> group by -> aggregate -> order by
    """
    params = get_parameters("Q2.1")
    category = params.get("category", "MFGR#12")
    region = params.get("region", "AMERICA")

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineorder.join(date, left_on="lo_orderdate", right_on="d_datekey")
        .join(part, left_on="lo_partkey", right_on="p_partkey")
        .join(supplier, left_on="lo_suppkey", right_on="s_suppkey")
        .filter((col("p_category") == lit(category)) & (col("s_region") == lit(region)))
        .group_by("d_year", "p_brand1")
        .agg(col("lo_revenue").sum().alias("revenue"))
        .sort(["d_year", "p_brand1"])
    )

    return result


def q2_1_pandas_impl(ctx: DataFrameContext) -> Any:
    """SSB Q2.1: Revenue by year/brand filtered by category and region (Pandas Family)."""
    params = get_parameters("Q2.1")
    category = params.get("category", "MFGR#12")
    region = params.get("region", "AMERICA")

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")

    merged = lineorder.merge(date, left_on="lo_orderdate", right_on="d_datekey")
    merged = merged.merge(part, left_on="lo_partkey", right_on="p_partkey")
    merged = merged.merge(supplier, left_on="lo_suppkey", right_on="s_suppkey")

    filtered = merged[(merged["p_category"] == category) & (merged["s_region"] == region)]

    result = (
        filtered.groupby(["d_year", "p_brand1"], as_index=False)
        .agg(revenue=("lo_revenue", "sum"))
        .sort_values(["d_year", "p_brand1"])
    )

    return result


def q2_2_expression_impl(ctx: DataFrameContext) -> Any:
    """SSB Q2.2: Revenue by year/brand filtered by brand range and region (Expression Family).

    Drill-down from category to brand range.
    Tables: lineorder, date, part, supplier
    Pattern: 4-table join -> filter -> group by -> aggregate -> order by
    """
    params = get_parameters("Q2.2")
    brand_min = params.get("brand_min", "MFGR#2221")
    brand_max = params.get("brand_max", "MFGR#2228")
    region = params.get("region", "AMERICA")

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineorder.join(date, left_on="lo_orderdate", right_on="d_datekey")
        .join(part, left_on="lo_partkey", right_on="p_partkey")
        .join(supplier, left_on="lo_suppkey", right_on="s_suppkey")
        .filter(
            (col("p_brand1") >= lit(brand_min)) & (col("p_brand1") <= lit(brand_max)) & (col("s_region") == lit(region))
        )
        .group_by("d_year", "p_brand1")
        .agg(col("lo_revenue").sum().alias("revenue"))
        .sort(["d_year", "p_brand1"])
    )

    return result


def q2_2_pandas_impl(ctx: DataFrameContext) -> Any:
    """SSB Q2.2: Revenue by year/brand filtered by brand range and region (Pandas Family)."""
    params = get_parameters("Q2.2")
    brand_min = params.get("brand_min", "MFGR#2221")
    brand_max = params.get("brand_max", "MFGR#2228")
    region = params.get("region", "AMERICA")

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")

    merged = lineorder.merge(date, left_on="lo_orderdate", right_on="d_datekey")
    merged = merged.merge(part, left_on="lo_partkey", right_on="p_partkey")
    merged = merged.merge(supplier, left_on="lo_suppkey", right_on="s_suppkey")

    filtered = merged[
        (merged["p_brand1"] >= brand_min) & (merged["p_brand1"] <= brand_max) & (merged["s_region"] == region)
    ]

    result = (
        filtered.groupby(["d_year", "p_brand1"], as_index=False)
        .agg(revenue=("lo_revenue", "sum"))
        .sort_values(["d_year", "p_brand1"])
    )

    return result


def q2_3_expression_impl(ctx: DataFrameContext) -> Any:
    """SSB Q2.3: Revenue by year/brand filtered by single brand and region (Expression Family).

    Drill-down from brand range to single brand.
    Tables: lineorder, date, part, supplier
    Pattern: 4-table join -> filter -> group by -> aggregate -> order by
    """
    params = get_parameters("Q2.3")
    brand = params.get("brand", "MFGR#2221")
    region = params.get("region", "AMERICA")

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineorder.join(date, left_on="lo_orderdate", right_on="d_datekey")
        .join(part, left_on="lo_partkey", right_on="p_partkey")
        .join(supplier, left_on="lo_suppkey", right_on="s_suppkey")
        .filter((col("p_brand1") == lit(brand)) & (col("s_region") == lit(region)))
        .group_by("d_year", "p_brand1")
        .agg(col("lo_revenue").sum().alias("revenue"))
        .sort(["d_year", "p_brand1"])
    )

    return result


def q2_3_pandas_impl(ctx: DataFrameContext) -> Any:
    """SSB Q2.3: Revenue by year/brand filtered by single brand and region (Pandas Family)."""
    params = get_parameters("Q2.3")
    brand = params.get("brand", "MFGR#2221")
    region = params.get("region", "AMERICA")

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")

    merged = lineorder.merge(date, left_on="lo_orderdate", right_on="d_datekey")
    merged = merged.merge(part, left_on="lo_partkey", right_on="p_partkey")
    merged = merged.merge(supplier, left_on="lo_suppkey", right_on="s_suppkey")

    filtered = merged[(merged["p_brand1"] == brand) & (merged["s_region"] == region)]

    result = (
        filtered.groupby(["d_year", "p_brand1"], as_index=False)
        .agg(revenue=("lo_revenue", "sum"))
        .sort_values(["d_year", "p_brand1"])
    )

    return result


# =============================================================================
# Flight 3: Revenue by geography and year (lineorder + customer + supplier + date)
# All compute SUM(lo_revenue) with progressively narrower geographic filters
# =============================================================================


def q3_1_expression_impl(ctx: DataFrameContext) -> Any:
    """SSB Q3.1: Revenue by nation/year filtered by region (Expression Family).

    Revenue by customer nation, supplier nation, and year for a region pair.
    Tables: customer, lineorder, supplier, date
    Pattern: 4-table join -> filter -> group by -> aggregate -> order by
    """
    params = get_parameters("Q3.1")
    c_region = params.get("c_region", "ASIA")
    s_region = params.get("s_region", "ASIA")
    year_min = params.get("year_min", 1992)
    year_max = params.get("year_max", 1997)

    lineorder = ctx.get_table("lineorder")
    customer = ctx.get_table("customer")
    supplier = ctx.get_table("supplier")
    date = ctx.get_table("date")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineorder.join(customer, left_on="lo_custkey", right_on="c_custkey")
        .join(supplier, left_on="lo_suppkey", right_on="s_suppkey")
        .join(date, left_on="lo_orderdate", right_on="d_datekey")
        .filter(
            (col("c_region") == lit(c_region))
            & (col("s_region") == lit(s_region))
            & (col("d_year") >= lit(year_min))
            & (col("d_year") <= lit(year_max))
        )
        .group_by("c_nation", "s_nation", "d_year")
        .agg(col("lo_revenue").sum().alias("revenue"))
        .sort(["d_year", "revenue"], descending=[False, True])
    )

    return result


def q3_1_pandas_impl(ctx: DataFrameContext) -> Any:
    """SSB Q3.1: Revenue by nation/year filtered by region (Pandas Family)."""
    params = get_parameters("Q3.1")
    c_region = params.get("c_region", "ASIA")
    s_region = params.get("s_region", "ASIA")
    year_min = params.get("year_min", 1992)
    year_max = params.get("year_max", 1997)

    lineorder = ctx.get_table("lineorder")
    customer = ctx.get_table("customer")
    supplier = ctx.get_table("supplier")
    date = ctx.get_table("date")

    merged = lineorder.merge(customer, left_on="lo_custkey", right_on="c_custkey")
    merged = merged.merge(supplier, left_on="lo_suppkey", right_on="s_suppkey")
    merged = merged.merge(date, left_on="lo_orderdate", right_on="d_datekey")

    filtered = merged[
        (merged["c_region"] == c_region)
        & (merged["s_region"] == s_region)
        & (merged["d_year"] >= year_min)
        & (merged["d_year"] <= year_max)
    ]

    result = (
        filtered.groupby(["c_nation", "s_nation", "d_year"], as_index=False)
        .agg(revenue=("lo_revenue", "sum"))
        .sort_values(["d_year", "revenue"], ascending=[True, False])
    )

    return result


def q3_2_expression_impl(ctx: DataFrameContext) -> Any:
    """SSB Q3.2: Revenue by city/year filtered by nation (Expression Family).

    Drill-down from region to nation; groups by city instead of nation.
    Tables: customer, lineorder, supplier, date
    Pattern: 4-table join -> filter -> group by -> aggregate -> order by
    """
    params = get_parameters("Q3.2")
    c_nation = params.get("c_nation", "UNITED STATES")
    s_nation = params.get("s_nation", "UNITED STATES")
    year_min = params.get("year_min", 1992)
    year_max = params.get("year_max", 1997)

    lineorder = ctx.get_table("lineorder")
    customer = ctx.get_table("customer")
    supplier = ctx.get_table("supplier")
    date = ctx.get_table("date")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineorder.join(customer, left_on="lo_custkey", right_on="c_custkey")
        .join(supplier, left_on="lo_suppkey", right_on="s_suppkey")
        .join(date, left_on="lo_orderdate", right_on="d_datekey")
        .filter(
            (col("c_nation") == lit(c_nation))
            & (col("s_nation") == lit(s_nation))
            & (col("d_year") >= lit(year_min))
            & (col("d_year") <= lit(year_max))
        )
        .group_by("c_city", "s_city", "d_year")
        .agg(col("lo_revenue").sum().alias("revenue"))
        .sort(["d_year", "revenue"], descending=[False, True])
    )

    return result


def q3_2_pandas_impl(ctx: DataFrameContext) -> Any:
    """SSB Q3.2: Revenue by city/year filtered by nation (Pandas Family)."""
    params = get_parameters("Q3.2")
    c_nation = params.get("c_nation", "UNITED STATES")
    s_nation = params.get("s_nation", "UNITED STATES")
    year_min = params.get("year_min", 1992)
    year_max = params.get("year_max", 1997)

    lineorder = ctx.get_table("lineorder")
    customer = ctx.get_table("customer")
    supplier = ctx.get_table("supplier")
    date = ctx.get_table("date")

    merged = lineorder.merge(customer, left_on="lo_custkey", right_on="c_custkey")
    merged = merged.merge(supplier, left_on="lo_suppkey", right_on="s_suppkey")
    merged = merged.merge(date, left_on="lo_orderdate", right_on="d_datekey")

    filtered = merged[
        (merged["c_nation"] == c_nation)
        & (merged["s_nation"] == s_nation)
        & (merged["d_year"] >= year_min)
        & (merged["d_year"] <= year_max)
    ]

    result = (
        filtered.groupby(["c_city", "s_city", "d_year"], as_index=False)
        .agg(revenue=("lo_revenue", "sum"))
        .sort_values(["d_year", "revenue"], ascending=[True, False])
    )

    return result


def q3_3_expression_impl(ctx: DataFrameContext) -> Any:
    """SSB Q3.3: Revenue by city/year filtered by city pairs (Expression Family).

    Drill-down from nation to specific city pairs (OR filter).
    Tables: customer, lineorder, supplier, date
    Pattern: 4-table join -> filter (OR conditions) -> group by -> aggregate -> order by
    """
    params = get_parameters("Q3.3")
    c_city1 = params.get("c_city1", "UNITED KI1")
    c_city2 = params.get("c_city2", "UNITED KI5")
    s_city1 = params.get("s_city1", "UNITED KI1")
    s_city2 = params.get("s_city2", "UNITED KI5")
    year_min = params.get("year_min", 1992)
    year_max = params.get("year_max", 1997)

    lineorder = ctx.get_table("lineorder")
    customer = ctx.get_table("customer")
    supplier = ctx.get_table("supplier")
    date = ctx.get_table("date")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineorder.join(customer, left_on="lo_custkey", right_on="c_custkey")
        .join(supplier, left_on="lo_suppkey", right_on="s_suppkey")
        .join(date, left_on="lo_orderdate", right_on="d_datekey")
        .filter(
            ((col("c_city") == lit(c_city1)) | (col("c_city") == lit(c_city2)))
            & ((col("s_city") == lit(s_city1)) | (col("s_city") == lit(s_city2)))
            & (col("d_year") >= lit(year_min))
            & (col("d_year") <= lit(year_max))
        )
        .group_by("c_city", "s_city", "d_year")
        .agg(col("lo_revenue").sum().alias("revenue"))
        .sort(["d_year", "revenue"], descending=[False, True])
    )

    return result


def q3_3_pandas_impl(ctx: DataFrameContext) -> Any:
    """SSB Q3.3: Revenue by city/year filtered by city pairs (Pandas Family)."""
    params = get_parameters("Q3.3")
    c_city1 = params.get("c_city1", "UNITED KI1")
    c_city2 = params.get("c_city2", "UNITED KI5")
    s_city1 = params.get("s_city1", "UNITED KI1")
    s_city2 = params.get("s_city2", "UNITED KI5")
    year_min = params.get("year_min", 1992)
    year_max = params.get("year_max", 1997)

    lineorder = ctx.get_table("lineorder")
    customer = ctx.get_table("customer")
    supplier = ctx.get_table("supplier")
    date = ctx.get_table("date")

    merged = lineorder.merge(customer, left_on="lo_custkey", right_on="c_custkey")
    merged = merged.merge(supplier, left_on="lo_suppkey", right_on="s_suppkey")
    merged = merged.merge(date, left_on="lo_orderdate", right_on="d_datekey")

    filtered = merged[
        ((merged["c_city"] == c_city1) | (merged["c_city"] == c_city2))
        & ((merged["s_city"] == s_city1) | (merged["s_city"] == s_city2))
        & (merged["d_year"] >= year_min)
        & (merged["d_year"] <= year_max)
    ]

    result = (
        filtered.groupby(["c_city", "s_city", "d_year"], as_index=False)
        .agg(revenue=("lo_revenue", "sum"))
        .sort_values(["d_year", "revenue"], ascending=[True, False])
    )

    return result


def q3_4_expression_impl(ctx: DataFrameContext) -> Any:
    """SSB Q3.4: Revenue by city/year filtered by city pairs and year-month (Expression Family).

    Drill-down from year range to single year-month.
    Tables: customer, lineorder, supplier, date
    Pattern: 4-table join -> filter (OR + equality) -> group by -> aggregate -> order by
    """
    params = get_parameters("Q3.4")
    c_city1 = params.get("c_city1", "UNITED KI1")
    c_city2 = params.get("c_city2", "UNITED KI5")
    s_city1 = params.get("s_city1", "UNITED KI1")
    s_city2 = params.get("s_city2", "UNITED KI5")
    year_month = params.get("year_month", "Dec1997")

    lineorder = ctx.get_table("lineorder")
    customer = ctx.get_table("customer")
    supplier = ctx.get_table("supplier")
    date = ctx.get_table("date")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineorder.join(customer, left_on="lo_custkey", right_on="c_custkey")
        .join(supplier, left_on="lo_suppkey", right_on="s_suppkey")
        .join(date, left_on="lo_orderdate", right_on="d_datekey")
        .filter(
            ((col("c_city") == lit(c_city1)) | (col("c_city") == lit(c_city2)))
            & ((col("s_city") == lit(s_city1)) | (col("s_city") == lit(s_city2)))
            & (col("d_yearmonth") == lit(year_month))
        )
        .group_by("c_city", "s_city", "d_year")
        .agg(col("lo_revenue").sum().alias("revenue"))
        .sort(["d_year", "revenue"], descending=[False, True])
    )

    return result


def q3_4_pandas_impl(ctx: DataFrameContext) -> Any:
    """SSB Q3.4: Revenue by city/year filtered by city pairs and year-month (Pandas Family)."""
    params = get_parameters("Q3.4")
    c_city1 = params.get("c_city1", "UNITED KI1")
    c_city2 = params.get("c_city2", "UNITED KI5")
    s_city1 = params.get("s_city1", "UNITED KI1")
    s_city2 = params.get("s_city2", "UNITED KI5")
    year_month = params.get("year_month", "Dec1997")

    lineorder = ctx.get_table("lineorder")
    customer = ctx.get_table("customer")
    supplier = ctx.get_table("supplier")
    date = ctx.get_table("date")

    merged = lineorder.merge(customer, left_on="lo_custkey", right_on="c_custkey")
    merged = merged.merge(supplier, left_on="lo_suppkey", right_on="s_suppkey")
    merged = merged.merge(date, left_on="lo_orderdate", right_on="d_datekey")

    filtered = merged[
        ((merged["c_city"] == c_city1) | (merged["c_city"] == c_city2))
        & ((merged["s_city"] == s_city1) | (merged["s_city"] == s_city2))
        & (merged["d_yearmonth"] == year_month)
    ]

    result = (
        filtered.groupby(["c_city", "s_city", "d_year"], as_index=False)
        .agg(revenue=("lo_revenue", "sum"))
        .sort_values(["d_year", "revenue"], ascending=[True, False])
    )

    return result


# =============================================================================
# Flight 4: Profit by various dimensions (all 5 tables)
# All compute SUM(lo_revenue - lo_supplycost) AS profit
# =============================================================================


def q4_1_expression_impl(ctx: DataFrameContext) -> Any:
    """SSB Q4.1: Profit by year/nation filtered by region and manufacturer (Expression Family).

    Profit aggregation across all 5 tables with region and manufacturer filters.
    Tables: date, customer, supplier, part, lineorder
    Pattern: 5-table join -> filter (OR conditions) -> group by -> aggregate -> order by
    """
    params = get_parameters("Q4.1")
    region = params.get("region", "AMERICA")
    mfgr1 = params.get("mfgr1", "MFGR#1")
    mfgr2 = params.get("mfgr2", "MFGR#2")

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")
    customer = ctx.get_table("customer")
    supplier = ctx.get_table("supplier")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineorder.join(date, left_on="lo_orderdate", right_on="d_datekey")
        .join(customer, left_on="lo_custkey", right_on="c_custkey")
        .join(supplier, left_on="lo_suppkey", right_on="s_suppkey")
        .join(part, left_on="lo_partkey", right_on="p_partkey")
        .filter(
            (col("c_region") == lit(region))
            & (col("s_region") == lit(region))
            & ((col("p_mfgr") == lit(mfgr1)) | (col("p_mfgr") == lit(mfgr2)))
        )
        .group_by("d_year", "c_nation")
        .agg((col("lo_revenue") - col("lo_supplycost")).sum().alias("profit"))
        .sort(["d_year", "c_nation"])
    )

    return result


def q4_1_pandas_impl(ctx: DataFrameContext) -> Any:
    """SSB Q4.1: Profit by year/nation filtered by region and manufacturer (Pandas Family)."""
    params = get_parameters("Q4.1")
    region = params.get("region", "AMERICA")
    mfgr1 = params.get("mfgr1", "MFGR#1")
    mfgr2 = params.get("mfgr2", "MFGR#2")

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")
    customer = ctx.get_table("customer")
    supplier = ctx.get_table("supplier")
    part = ctx.get_table("part")

    merged = lineorder.merge(date, left_on="lo_orderdate", right_on="d_datekey")
    merged = merged.merge(customer, left_on="lo_custkey", right_on="c_custkey")
    merged = merged.merge(supplier, left_on="lo_suppkey", right_on="s_suppkey")
    merged = merged.merge(part, left_on="lo_partkey", right_on="p_partkey")

    filtered = merged[
        (merged["c_region"] == region)
        & (merged["s_region"] == region)
        & ((merged["p_mfgr"] == mfgr1) | (merged["p_mfgr"] == mfgr2))
    ]

    filtered = filtered.copy()
    filtered["profit"] = filtered["lo_revenue"] - filtered["lo_supplycost"]

    result = (
        filtered.groupby(["d_year", "c_nation"], as_index=False)
        .agg(profit=("profit", "sum"))
        .sort_values(["d_year", "c_nation"])
    )

    return result


def q4_2_expression_impl(ctx: DataFrameContext) -> Any:
    """SSB Q4.2: Profit by year/nation/category with year filter (Expression Family).

    Adds year filter and groups by supplier nation and part category.
    Tables: date, customer, supplier, part, lineorder
    Pattern: 5-table join -> filter (OR conditions) -> group by -> aggregate -> order by
    """
    params = get_parameters("Q4.2")
    region = params.get("region", "AMERICA")
    year1 = params.get("year1", 1997)
    year2 = params.get("year2", 1998)
    mfgr1 = params.get("mfgr1", "MFGR#1")
    mfgr2 = params.get("mfgr2", "MFGR#2")

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")
    customer = ctx.get_table("customer")
    supplier = ctx.get_table("supplier")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineorder.join(date, left_on="lo_orderdate", right_on="d_datekey")
        .join(customer, left_on="lo_custkey", right_on="c_custkey")
        .join(supplier, left_on="lo_suppkey", right_on="s_suppkey")
        .join(part, left_on="lo_partkey", right_on="p_partkey")
        .filter(
            (col("c_region") == lit(region))
            & (col("s_region") == lit(region))
            & ((col("d_year") == lit(year1)) | (col("d_year") == lit(year2)))
            & ((col("p_mfgr") == lit(mfgr1)) | (col("p_mfgr") == lit(mfgr2)))
        )
        .group_by("d_year", "s_nation", "p_category")
        .agg((col("lo_revenue") - col("lo_supplycost")).sum().alias("profit"))
        .sort(["d_year", "s_nation", "p_category"])
    )

    return result


def q4_2_pandas_impl(ctx: DataFrameContext) -> Any:
    """SSB Q4.2: Profit by year/nation/category with year filter (Pandas Family)."""
    params = get_parameters("Q4.2")
    region = params.get("region", "AMERICA")
    year1 = params.get("year1", 1997)
    year2 = params.get("year2", 1998)
    mfgr1 = params.get("mfgr1", "MFGR#1")
    mfgr2 = params.get("mfgr2", "MFGR#2")

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")
    customer = ctx.get_table("customer")
    supplier = ctx.get_table("supplier")
    part = ctx.get_table("part")

    merged = lineorder.merge(date, left_on="lo_orderdate", right_on="d_datekey")
    merged = merged.merge(customer, left_on="lo_custkey", right_on="c_custkey")
    merged = merged.merge(supplier, left_on="lo_suppkey", right_on="s_suppkey")
    merged = merged.merge(part, left_on="lo_partkey", right_on="p_partkey")

    filtered = merged[
        (merged["c_region"] == region)
        & (merged["s_region"] == region)
        & ((merged["d_year"] == year1) | (merged["d_year"] == year2))
        & ((merged["p_mfgr"] == mfgr1) | (merged["p_mfgr"] == mfgr2))
    ]

    filtered = filtered.copy()
    filtered["profit"] = filtered["lo_revenue"] - filtered["lo_supplycost"]

    result = (
        filtered.groupby(["d_year", "s_nation", "p_category"], as_index=False)
        .agg(profit=("profit", "sum"))
        .sort_values(["d_year", "s_nation", "p_category"])
    )

    return result


def q4_3_expression_impl(ctx: DataFrameContext) -> Any:
    """SSB Q4.3: Profit by year/city/brand with category filter (Expression Family).

    Drill-down from manufacturer to category; groups by city and brand.
    Tables: date, customer, supplier, part, lineorder
    Pattern: 5-table join -> filter -> group by -> aggregate -> order by
    """
    params = get_parameters("Q4.3")
    region = params.get("region", "AMERICA")
    year1 = params.get("year1", 1997)
    year2 = params.get("year2", 1998)
    category = params.get("category", "MFGR#12")

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")
    customer = ctx.get_table("customer")
    supplier = ctx.get_table("supplier")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    result = (
        lineorder.join(date, left_on="lo_orderdate", right_on="d_datekey")
        .join(customer, left_on="lo_custkey", right_on="c_custkey")
        .join(supplier, left_on="lo_suppkey", right_on="s_suppkey")
        .join(part, left_on="lo_partkey", right_on="p_partkey")
        .filter(
            (col("c_region") == lit(region))
            & (col("s_region") == lit(region))
            & ((col("d_year") == lit(year1)) | (col("d_year") == lit(year2)))
            & (col("p_category") == lit(category))
        )
        .group_by("d_year", "s_city", "p_brand1")
        .agg((col("lo_revenue") - col("lo_supplycost")).sum().alias("profit"))
        .sort(["d_year", "s_city", "p_brand1"])
    )

    return result


def q4_3_pandas_impl(ctx: DataFrameContext) -> Any:
    """SSB Q4.3: Profit by year/city/brand with category filter (Pandas Family)."""
    params = get_parameters("Q4.3")
    region = params.get("region", "AMERICA")
    year1 = params.get("year1", 1997)
    year2 = params.get("year2", 1998)
    category = params.get("category", "MFGR#12")

    lineorder = ctx.get_table("lineorder")
    date = ctx.get_table("date")
    customer = ctx.get_table("customer")
    supplier = ctx.get_table("supplier")
    part = ctx.get_table("part")

    merged = lineorder.merge(date, left_on="lo_orderdate", right_on="d_datekey")
    merged = merged.merge(customer, left_on="lo_custkey", right_on="c_custkey")
    merged = merged.merge(supplier, left_on="lo_suppkey", right_on="s_suppkey")
    merged = merged.merge(part, left_on="lo_partkey", right_on="p_partkey")

    filtered = merged[
        (merged["c_region"] == region)
        & (merged["s_region"] == region)
        & ((merged["d_year"] == year1) | (merged["d_year"] == year2))
        & (merged["p_category"] == category)
    ]

    filtered = filtered.copy()
    filtered["profit"] = filtered["lo_revenue"] - filtered["lo_supplycost"]

    result = (
        filtered.groupby(["d_year", "s_city", "p_brand1"], as_index=False)
        .agg(profit=("profit", "sum"))
        .sort_values(["d_year", "s_city", "p_brand1"])
    )

    return result


# =============================================================================
# Query Registration
# =============================================================================

_CATEGORY_CODES = {
    "AG": QueryCategory.AGGREGATE,
    "FI": QueryCategory.FILTER,
    "GB": QueryCategory.GROUP_BY,
    "JO": QueryCategory.JOIN,
    "MJ": QueryCategory.MULTI_JOIN,
    "SO": QueryCategory.SORT,
}

_QUERY_METADATA = """\
Q1.1|Revenue by Year|Revenue aggregation filtered by year, discount range, and quantity threshold|JO,FI,AG|q1_1
Q1.2|Revenue by Year-Month|Revenue drill-down from year to year-month with quantity range filter|JO,FI,AG|q1_2
Q1.3|Revenue by Week|Revenue drill-down from year-month to week with quantity range filter|JO,FI,AG|q1_3
Q2.1|Revenue by Year/Brand (Category)|Revenue by year and brand filtered by part category and supplier region|MJ,FI,GB,SO|q2_1
Q2.2|Revenue by Year/Brand (Brand Range)|Revenue by year and brand filtered by brand range and supplier region|MJ,FI,GB,SO|q2_2
Q2.3|Revenue by Year/Brand (Single Brand)|Revenue by year and brand filtered by single brand and supplier region|MJ,FI,GB,SO|q2_3
Q3.1|Revenue by Nation/Year|Revenue by customer/supplier nation and year filtered by region|MJ,FI,GB,SO|q3_1
Q3.2|Revenue by City/Year (Nation)|Revenue by city and year filtered by nation (drill-down from region)|MJ,FI,GB,SO|q3_2
Q3.3|Revenue by City/Year (City Pairs)|Revenue by city and year filtered by specific city pairs (OR conditions)|MJ,FI,GB,SO|q3_3
Q3.4|Revenue by City/Year-Month|Revenue by city filtered by city pairs and specific year-month|MJ,FI,GB,SO|q3_4
Q4.1|Profit by Year/Nation|Profit (revenue - supply cost) by year and nation filtered by region and manufacturer|MJ,FI,GB,SO|q4_1
Q4.2|Profit by Year/Nation/Category|Profit by year, supplier nation, and part category with year and manufacturer filters|MJ,FI,GB,SO|q4_2
Q4.3|Profit by Year/City/Brand|Profit by year, supplier city, and brand with category filter (deepest drill-down)|MJ,FI,GB,SO|q4_3
"""


def _impl_for(stem: str, family: str) -> Any:
    return globals()[f"{stem}_{family}_impl"]


def _register_all_queries() -> None:
    for query_id, query_name, description, category_codes, impl_stem in reader(
        _QUERY_METADATA.splitlines(), delimiter="|"
    ):
        register_query(
            DataFrameQuery(
                query_id=query_id,
                query_name=query_name,
                description=description,
                categories=[_CATEGORY_CODES[code] for code in category_codes.split(",")],
                expression_impl=_impl_for(impl_stem, "expression"),
                pandas_impl=_impl_for(impl_stem, "pandas"),
            )
        )


_register_all_queries()
