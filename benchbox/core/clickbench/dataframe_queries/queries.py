"""ClickBench DataFrame query implementations.

All 43 ClickBench queries implemented for both Expression and Pandas families.
All queries operate on a single flat 'hits' table (no joins).

Categories:
- Basic aggregation (Q1-Q7): COUNT, SUM, AVG, MIN/MAX, COUNT(DISTINCT)
- Grouping and ordering (Q8-Q15): GROUP BY with various aggregates
- User analysis (Q16-Q20): User-centric grouping and point lookups
- Text and pattern matching (Q21-Q27): LIKE, string filtering
- String operations (Q28-Q29): LENGTH, REGEXP_REPLACE, HAVING
- Mathematical operations (Q30): Wide aggregation (90 columns)
- Complex grouping (Q31-Q36): Multi-column GROUP BY with derived columns
- Time-based analysis (Q37-Q43): Date filtering, OFFSET, CASE WHEN, DATE_TRUNC

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from csv import reader
from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory

from .registry import register_query

# =============================================================================
# Basic Aggregation (Q1-Q7)
# =============================================================================


def q1_expression_impl(ctx: DataFrameContext) -> Any:
    """Q1: COUNT(*) - full table scan count."""
    hits = ctx.get_table("hits")
    col = ctx.col
    return hits.select(col("WatchID").count().alias("count"))


def q1_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q1: COUNT(*) - full table scan count."""
    import pandas as pd

    hits = ctx.get_table("hits")
    count = len(hits)
    if hasattr(count, "compute"):
        count = count.compute()
    return pd.DataFrame({"count": [count]})


def q2_expression_impl(ctx: DataFrameContext) -> Any:
    """Q2: COUNT(*) with filter on AdvEngineID."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return hits.filter(col("AdvEngineID") != lit(0)).select(col("WatchID").count().alias("count"))


def q2_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q2: COUNT(*) with filter on AdvEngineID."""
    import pandas as pd

    hits = ctx.get_table("hits")
    count = len(hits[hits["AdvEngineID"] != 0])
    if hasattr(count, "compute"):
        count = count.compute()
    return pd.DataFrame({"count": [count]})


def q3_expression_impl(ctx: DataFrameContext) -> Any:
    """Q3: SUM, COUNT, AVG - multi-aggregate full scan."""
    hits = ctx.get_table("hits")
    col = ctx.col
    return hits.select(
        col("AdvEngineID").sum().alias("sum_adv"),
        col("AdvEngineID").count().alias("count"),
        col("ResolutionWidth").mean().alias("avg_resolution"),
    )


def q3_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q3: SUM, COUNT, AVG - multi-aggregate full scan."""
    import pandas as pd

    hits = ctx.get_table("hits")
    result = pd.DataFrame(
        {
            "sum_adv": [hits["AdvEngineID"].sum()],
            "count": [len(hits)],
            "avg_resolution": [hits["ResolutionWidth"].mean()],
        }
    )
    return result


def q4_expression_impl(ctx: DataFrameContext) -> Any:
    """Q4: AVG(UserID) - average of BIGINT column."""
    hits = ctx.get_table("hits")
    col = ctx.col
    return hits.select(col("UserID").mean().alias("avg_user_id"))


def q4_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q4: AVG(UserID) - average of BIGINT column."""
    import pandas as pd

    hits = ctx.get_table("hits")
    return pd.DataFrame({"avg_user_id": [hits["UserID"].mean()]})


def q5_expression_impl(ctx: DataFrameContext) -> Any:
    """Q5: COUNT(DISTINCT UserID)."""
    hits = ctx.get_table("hits")
    col = ctx.col
    return hits.select(col("UserID").n_unique().alias("uniq_users"))


def q5_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q5: COUNT(DISTINCT UserID)."""
    import pandas as pd

    hits = ctx.get_table("hits")
    return pd.DataFrame({"uniq_users": [hits["UserID"].nunique()]})


def q6_expression_impl(ctx: DataFrameContext) -> Any:
    """Q6: COUNT(DISTINCT SearchPhrase)."""
    hits = ctx.get_table("hits")
    col = ctx.col
    return hits.select(col("SearchPhrase").n_unique().alias("uniq_search"))


def q6_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q6: COUNT(DISTINCT SearchPhrase)."""
    import pandas as pd

    hits = ctx.get_table("hits")
    return pd.DataFrame({"uniq_search": [hits["SearchPhrase"].nunique()]})


def q7_expression_impl(ctx: DataFrameContext) -> Any:
    """Q7: MIN/MAX on EventDate."""
    hits = ctx.get_table("hits")
    col = ctx.col
    return hits.select(
        col("EventDate").min().alias("min_date"),
        col("EventDate").max().alias("max_date"),
    )


def q7_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q7: MIN/MAX on EventDate."""
    import pandas as pd

    hits = ctx.get_table("hits")
    return pd.DataFrame({"min_date": [hits["EventDate"].min()], "max_date": [hits["EventDate"].max()]})


# =============================================================================
# Grouping and Ordering (Q8-Q15)
# =============================================================================


def q8_expression_impl(ctx: DataFrameContext) -> Any:
    """Q8: GROUP BY AdvEngineID with COUNT, filtered and sorted."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.filter(col("AdvEngineID") != lit(0))
        .group_by("AdvEngineID")
        .agg(col("AdvEngineID").count().alias("c"))
        .sort("c", descending=True)
    )


def q8_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q8: GROUP BY AdvEngineID with COUNT, filtered and sorted."""
    hits = ctx.get_table("hits")
    filtered = hits[hits["AdvEngineID"] != 0]
    return (
        filtered.groupby(["AdvEngineID"], as_index=False)
        .agg(c=("AdvEngineID", "count"))
        .sort_values("c", ascending=False)
    )


def q9_expression_impl(ctx: DataFrameContext) -> Any:
    """Q9: COUNT(DISTINCT UserID) by RegionID, top 10."""
    hits = ctx.get_table("hits")
    col = ctx.col
    return hits.group_by("RegionID").agg(col("UserID").n_unique().alias("u")).sort("u", descending=True).limit(10)


def q9_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q9: COUNT(DISTINCT UserID) by RegionID, top 10."""
    hits = ctx.get_table("hits")
    return (
        hits.groupby(["RegionID"], as_index=False)
        .agg(u=("UserID", "nunique"))
        .sort_values("u", ascending=False)
        .head(10)
    )


def q10_expression_impl(ctx: DataFrameContext) -> Any:
    """Q10: Multi-aggregate by RegionID, top 10."""
    hits = ctx.get_table("hits")
    col = ctx.col
    return (
        hits.group_by("RegionID")
        .agg(
            col("AdvEngineID").sum().alias("sum_adv"),
            col("RegionID").count().alias("c"),
            col("ResolutionWidth").mean().alias("avg_res"),
            col("UserID").n_unique().alias("uniq_users"),
        )
        .sort("c", descending=True)
        .limit(10)
    )


def q10_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q10: Multi-aggregate by RegionID, top 10."""
    hits = ctx.get_table("hits")
    grouped = hits.groupby(["RegionID"], as_index=False).agg(
        sum_adv=("AdvEngineID", "sum"),
        c=("RegionID", "count"),
        avg_res=("ResolutionWidth", "mean"),
        uniq_users=("UserID", "nunique"),
    )
    return grouped.sort_values("c", ascending=False).head(10)


def q11_expression_impl(ctx: DataFrameContext) -> Any:
    """Q11: COUNT(DISTINCT UserID) by MobilePhoneModel, filtered, top 10."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.filter(col("MobilePhoneModel") != lit(""))
        .group_by("MobilePhoneModel")
        .agg(col("UserID").n_unique().alias("u"))
        .sort("u", descending=True)
        .limit(10)
    )


def q11_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q11: COUNT(DISTINCT UserID) by MobilePhoneModel, filtered, top 10."""
    hits = ctx.get_table("hits")
    filtered = hits[hits["MobilePhoneModel"] != ""]
    return (
        filtered.groupby(["MobilePhoneModel"], as_index=False)
        .agg(u=("UserID", "nunique"))
        .sort_values("u", ascending=False)
        .head(10)
    )


def q12_expression_impl(ctx: DataFrameContext) -> Any:
    """Q12: COUNT(DISTINCT UserID) by MobilePhone + MobilePhoneModel, top 10."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.filter(col("MobilePhoneModel") != lit(""))
        .group_by("MobilePhone", "MobilePhoneModel")
        .agg(col("UserID").n_unique().alias("u"))
        .sort("u", descending=True)
        .limit(10)
    )


def q12_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q12: COUNT(DISTINCT UserID) by MobilePhone + MobilePhoneModel, top 10."""
    hits = ctx.get_table("hits")
    filtered = hits[hits["MobilePhoneModel"] != ""]
    return (
        filtered.groupby(["MobilePhone", "MobilePhoneModel"], as_index=False)
        .agg(u=("UserID", "nunique"))
        .sort_values("u", ascending=False)
        .head(10)
    )


def q13_expression_impl(ctx: DataFrameContext) -> Any:
    """Q13: Top search phrases by count."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.filter(col("SearchPhrase") != lit(""))
        .group_by("SearchPhrase")
        .agg(col("SearchPhrase").count().alias("c"))
        .sort("c", descending=True)
        .limit(10)
    )


def q13_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q13: Top search phrases by count."""
    hits = ctx.get_table("hits")
    filtered = hits[hits["SearchPhrase"] != ""]
    return (
        filtered.groupby(["SearchPhrase"], as_index=False)
        .agg(c=("SearchPhrase", "count"))
        .sort_values("c", ascending=False)
        .head(10)
    )


def q14_expression_impl(ctx: DataFrameContext) -> Any:
    """Q14: Top search phrases by unique users."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.filter(col("SearchPhrase") != lit(""))
        .group_by("SearchPhrase")
        .agg(col("UserID").n_unique().alias("u"))
        .sort("u", descending=True)
        .limit(10)
    )


def q14_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q14: Top search phrases by unique users."""
    hits = ctx.get_table("hits")
    filtered = hits[hits["SearchPhrase"] != ""]
    return (
        filtered.groupby(["SearchPhrase"], as_index=False)
        .agg(u=("UserID", "nunique"))
        .sort_values("u", ascending=False)
        .head(10)
    )


def q15_expression_impl(ctx: DataFrameContext) -> Any:
    """Q15: SearchEngineID + SearchPhrase count, top 10."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.filter(col("SearchPhrase") != lit(""))
        .group_by("SearchEngineID", "SearchPhrase")
        .agg(col("SearchPhrase").count().alias("c"))
        .sort("c", descending=True)
        .limit(10)
    )


def q15_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q15: SearchEngineID + SearchPhrase count, top 10."""
    hits = ctx.get_table("hits")
    filtered = hits[hits["SearchPhrase"] != ""]
    return (
        filtered.groupby(["SearchEngineID", "SearchPhrase"], as_index=False)
        .agg(c=("SearchPhrase", "count"))
        .sort_values("c", ascending=False)
        .head(10)
    )


# =============================================================================
# User Analysis (Q16-Q20)
# =============================================================================


def q16_expression_impl(ctx: DataFrameContext) -> Any:
    """Q16: Top users by activity count."""
    hits = ctx.get_table("hits")
    col = ctx.col
    return hits.group_by("UserID").agg(col("UserID").count().alias("c")).sort("c", descending=True).limit(10)


def q16_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q16: Top users by activity count."""
    hits = ctx.get_table("hits")
    return (
        hits.groupby(["UserID"], as_index=False).agg(c=("UserID", "count")).sort_values("c", ascending=False).head(10)
    )


def q17_expression_impl(ctx: DataFrameContext) -> Any:
    """Q17: Top user + search phrase combinations by count."""
    hits = ctx.get_table("hits")
    col = ctx.col
    return (
        hits.group_by("UserID", "SearchPhrase")
        .agg(col("UserID").count().alias("c"))
        .sort("c", descending=True)
        .limit(10)
    )


def q17_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q17: Top user + search phrase combinations by count."""
    hits = ctx.get_table("hits")
    return (
        hits.groupby(["UserID", "SearchPhrase"], as_index=False)
        .agg(c=("UserID", "count"))
        .sort_values("c", ascending=False)
        .head(10)
    )


def q18_expression_impl(ctx: DataFrameContext) -> Any:
    """Q18: User + search phrase group, no order, limit 10."""
    hits = ctx.get_table("hits")
    col = ctx.col
    return hits.group_by("UserID", "SearchPhrase").agg(col("UserID").count().alias("c")).limit(10)


def q18_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q18: User + search phrase group, no order, limit 10."""
    hits = ctx.get_table("hits")
    return hits.groupby(["UserID", "SearchPhrase"], as_index=False).agg(c=("UserID", "count")).head(10)


def q19_expression_impl(ctx: DataFrameContext) -> Any:
    """Q19: User + minute + search phrase group, top 10."""
    hits = ctx.get_table("hits")
    col = ctx.col
    return (
        hits.with_columns(col("EventTime").dt.minute().alias("m"))
        .group_by("UserID", "m", "SearchPhrase")
        .agg(col("UserID").count().alias("c"))
        .sort("c", descending=True)
        .limit(10)
    )


def q19_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q19: User + minute + search phrase group, top 10."""
    hits = ctx.get_table("hits")
    hits = hits.copy()
    hits["m"] = hits["EventTime"].dt.minute
    return (
        hits.groupby(["UserID", "m", "SearchPhrase"], as_index=False)
        .agg(c=("UserID", "count"))
        .sort_values("c", ascending=False)
        .head(10)
    )


def q20_expression_impl(ctx: DataFrameContext) -> Any:
    """Q20: Point lookup by UserID."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return hits.filter(col("UserID") == lit(435090932899640449))


def q20_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q20: Point lookup by UserID."""
    hits = ctx.get_table("hits")
    return hits[hits["UserID"] == 435090932899640449]


# =============================================================================
# Text and Pattern Matching (Q21-Q27)
# =============================================================================


def q21_expression_impl(ctx: DataFrameContext) -> Any:
    """Q21: COUNT(*) where URL contains 'google'."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return hits.filter(col("URL").str.contains(lit("google"))).select(col("WatchID").count().alias("count"))


def q21_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q21: COUNT(*) where URL contains 'google'."""
    import pandas as pd

    hits = ctx.get_table("hits")
    count = len(hits[hits["URL"].str.contains("google", na=False)])
    return pd.DataFrame({"count": [count]})


def q22_expression_impl(ctx: DataFrameContext) -> Any:
    """Q22: Top search phrases for google URLs."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.filter((col("URL").str.contains(lit("google"))) & (col("SearchPhrase") != lit("")))
        .group_by("SearchPhrase")
        .agg(
            col("URL").min().alias("min_url"),
            col("SearchPhrase").count().alias("c"),
        )
        .sort("c", descending=True)
        .limit(10)
    )


def q22_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q22: Top search phrases for google URLs."""
    hits = ctx.get_table("hits")
    filtered = hits[hits["URL"].str.contains("google", na=False) & (hits["SearchPhrase"] != "")]
    return (
        filtered.groupby(["SearchPhrase"], as_index=False)
        .agg(min_url=("URL", "min"), c=("SearchPhrase", "count"))
        .sort_values("c", ascending=False)
        .head(10)
    )


def q23_expression_impl(ctx: DataFrameContext) -> Any:
    """Q23: Search phrases for Google titles excluding .google. URLs."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.filter(
            (col("Title").str.contains(lit("Google")))
            & (~col("URL").str.contains(lit(".google.")))
            & (col("SearchPhrase") != lit(""))
        )
        .group_by("SearchPhrase")
        .agg(
            col("URL").min().alias("min_url"),
            col("Title").min().alias("min_title"),
            col("SearchPhrase").count().alias("c"),
            col("UserID").n_unique().alias("uniq_users"),
        )
        .sort("c", descending=True)
        .limit(10)
    )


def q23_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q23: Search phrases for Google titles excluding .google. URLs."""
    hits = ctx.get_table("hits")
    filtered = hits[
        hits["Title"].str.contains("Google", na=False)
        & ~hits["URL"].str.contains(".google.", na=False, regex=False)
        & (hits["SearchPhrase"] != "")
    ]
    return (
        filtered.groupby(["SearchPhrase"], as_index=False)
        .agg(
            min_url=("URL", "min"),
            min_title=("Title", "min"),
            c=("SearchPhrase", "count"),
            uniq_users=("UserID", "nunique"),
        )
        .sort_values("c", ascending=False)
        .head(10)
    )


def q24_expression_impl(ctx: DataFrameContext) -> Any:
    """Q24: All columns for google URLs sorted by EventTime, top 10."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return hits.filter(col("URL").str.contains(lit("google"))).sort("EventTime").limit(10)


def q24_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q24: All columns for google URLs sorted by EventTime, top 10."""
    hits = ctx.get_table("hits")
    return hits[hits["URL"].str.contains("google", na=False)].sort_values("EventTime").head(10)


def q25_expression_impl(ctx: DataFrameContext) -> Any:
    """Q25: Non-empty search phrases sorted by EventTime, top 10."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return hits.filter(col("SearchPhrase") != lit("")).sort("EventTime").limit(10).select("SearchPhrase")


def q25_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q25: Non-empty search phrases sorted by EventTime, top 10."""
    hits = ctx.get_table("hits")
    return hits[hits["SearchPhrase"] != ""].sort_values("EventTime").head(10)[["SearchPhrase"]]


def q26_expression_impl(ctx: DataFrameContext) -> Any:
    """Q26: Non-empty search phrases sorted by SearchPhrase, top 10."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return hits.filter(col("SearchPhrase") != lit("")).sort("SearchPhrase").limit(10).select("SearchPhrase")


def q26_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q26: Non-empty search phrases sorted by SearchPhrase, top 10."""
    hits = ctx.get_table("hits")
    return hits[hits["SearchPhrase"] != ""].sort_values("SearchPhrase").head(10)[["SearchPhrase"]]


def q27_expression_impl(ctx: DataFrameContext) -> Any:
    """Q27: Non-empty search phrases sorted by EventTime then SearchPhrase, top 10."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.filter(col("SearchPhrase") != lit("")).sort(["EventTime", "SearchPhrase"]).limit(10).select("SearchPhrase")
    )


def q27_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q27: Non-empty search phrases sorted by EventTime then SearchPhrase, top 10."""
    hits = ctx.get_table("hits")
    return hits[hits["SearchPhrase"] != ""].sort_values(["EventTime", "SearchPhrase"]).head(10)[["SearchPhrase"]]


# =============================================================================
# String Operations (Q28-Q29)
# =============================================================================


def q28_expression_impl(ctx: DataFrameContext) -> Any:
    """Q28: AVG URL length by CounterID with HAVING > 100000."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.filter(col("URL") != lit(""))
        .with_columns(col("URL").str.len_chars().alias("url_len"))
        .group_by("CounterID")
        .agg(
            col("url_len").mean().alias("l"),
            col("CounterID").count().alias("c"),
        )
        .filter(col("c") > lit(100000))
        .sort("l", descending=True)
        .limit(25)
    )


def q28_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q28: AVG URL length by CounterID with HAVING > 100000."""
    hits = ctx.get_table("hits")
    filtered = hits[hits["URL"] != ""].copy()
    filtered["url_len"] = filtered["URL"].str.len()
    grouped = filtered.groupby(["CounterID"], as_index=False).agg(l=("url_len", "mean"), c=("url_len", "count"))
    return grouped[grouped["c"] > 100000].sort_values("l", ascending=False).head(25)


def q29_expression_impl(ctx: DataFrameContext) -> Any:
    """Q29: Domain extraction from Referer via regex, with HAVING > 100000."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.filter(col("Referer") != lit(""))
        .with_columns(
            col("Referer").str.replace(lit(r"^https?://(?:www\.)?([^/]+)/.*$"), lit("$1")).alias("k"),
            col("Referer").str.len_chars().alias("ref_len"),
        )
        .group_by("k")
        .agg(
            col("ref_len").mean().alias("l"),
            col("k").count().alias("c"),
            col("Referer").min().alias("min_referer"),
        )
        .filter(col("c") > lit(100000))
        .sort("l", descending=True)
        .limit(25)
    )


def q29_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q29: Domain extraction from Referer via regex, with HAVING > 100000."""
    hits = ctx.get_table("hits")
    filtered = hits[hits["Referer"] != ""].copy()
    filtered["k"] = filtered["Referer"].str.replace(r"^https?://(?:www\.)?([^/]+)/.*$", r"\1", regex=True)
    filtered["ref_len"] = filtered["Referer"].str.len()
    grouped = filtered.groupby(["k"], as_index=False).agg(
        l=("ref_len", "mean"), c=("ref_len", "count"), min_referer=("Referer", "min")
    )
    return grouped[grouped["c"] > 100000].sort_values("l", ascending=False).head(25)


# =============================================================================
# Mathematical Operations (Q30)
# =============================================================================


def q30_expression_impl(ctx: DataFrameContext) -> Any:
    """Q30: Wide aggregation - SUM(ResolutionWidth + N) for N=0..89."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    agg_exprs = [(col("ResolutionWidth") + lit(i)).sum().alias(f"sum_{i}") for i in range(90)]
    return hits.select(*agg_exprs)


def q30_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q30: Wide aggregation - SUM(ResolutionWidth + N) for N=0..89."""
    import pandas as pd

    hits = ctx.get_table("hits")
    base = hits["ResolutionWidth"]
    result = {f"sum_{i}": [(base + i).sum()] for i in range(90)}
    return pd.DataFrame(result)


# =============================================================================
# Complex Grouping (Q31-Q36)
# =============================================================================


def q31_expression_impl(ctx: DataFrameContext) -> Any:
    """Q31: Multi-agg by SearchEngineID + ClientIP, filtered."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.filter(col("SearchPhrase") != lit(""))
        .group_by("SearchEngineID", "ClientIP")
        .agg(
            col("ClientIP").count().alias("c"),
            col("IsRefresh").sum().alias("sum_refresh"),
            col("ResolutionWidth").mean().alias("avg_res"),
        )
        .sort("c", descending=True)
        .limit(10)
    )


def q31_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q31: Multi-agg by SearchEngineID + ClientIP, filtered."""
    hits = ctx.get_table("hits")
    filtered = hits[hits["SearchPhrase"] != ""]
    return (
        filtered.groupby(["SearchEngineID", "ClientIP"], as_index=False)
        .agg(c=("ClientIP", "count"), sum_refresh=("IsRefresh", "sum"), avg_res=("ResolutionWidth", "mean"))
        .sort_values("c", ascending=False)
        .head(10)
    )


def q32_expression_impl(ctx: DataFrameContext) -> Any:
    """Q32: Multi-agg by WatchID + ClientIP, filtered (high cardinality)."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.filter(col("SearchPhrase") != lit(""))
        .group_by("WatchID", "ClientIP")
        .agg(
            col("ClientIP").count().alias("c"),
            col("IsRefresh").sum().alias("sum_refresh"),
            col("ResolutionWidth").mean().alias("avg_res"),
        )
        .sort("c", descending=True)
        .limit(10)
    )


def q32_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q32: Multi-agg by WatchID + ClientIP, filtered (high cardinality)."""
    hits = ctx.get_table("hits")
    filtered = hits[hits["SearchPhrase"] != ""]
    return (
        filtered.groupby(["WatchID", "ClientIP"], as_index=False)
        .agg(c=("ClientIP", "count"), sum_refresh=("IsRefresh", "sum"), avg_res=("ResolutionWidth", "mean"))
        .sort_values("c", ascending=False)
        .head(10)
    )


def q33_expression_impl(ctx: DataFrameContext) -> Any:
    """Q33: Multi-agg by WatchID + ClientIP, unfiltered (high cardinality)."""
    hits = ctx.get_table("hits")
    col = ctx.col
    return (
        hits.group_by("WatchID", "ClientIP")
        .agg(
            col("ClientIP").count().alias("c"),
            col("IsRefresh").sum().alias("sum_refresh"),
            col("ResolutionWidth").mean().alias("avg_res"),
        )
        .sort("c", descending=True)
        .limit(10)
    )


def q33_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q33: Multi-agg by WatchID + ClientIP, unfiltered (high cardinality)."""
    hits = ctx.get_table("hits")
    return (
        hits.groupby(["WatchID", "ClientIP"], as_index=False)
        .agg(c=("ClientIP", "count"), sum_refresh=("IsRefresh", "sum"), avg_res=("ResolutionWidth", "mean"))
        .sort_values("c", ascending=False)
        .head(10)
    )


def q34_expression_impl(ctx: DataFrameContext) -> Any:
    """Q34: Top URLs by count (high cardinality text GROUP BY)."""
    hits = ctx.get_table("hits")
    col = ctx.col
    return hits.group_by("URL").agg(col("URL").count().alias("c")).sort("c", descending=True).limit(10)


def q34_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q34: Top URLs by count (high cardinality text GROUP BY)."""
    hits = ctx.get_table("hits")
    return hits.groupby(["URL"], as_index=False).agg(c=("URL", "count")).sort_values("c", ascending=False).head(10)


def q35_expression_impl(ctx: DataFrameContext) -> Any:
    """Q35: Literal constant column + URL group by count, top 10."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.with_columns(lit(1).alias("one"))
        .group_by("one", "URL")
        .agg(col("URL").count().alias("c"))
        .sort("c", descending=True)
        .limit(10)
    )


def q35_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q35: Literal constant column + URL group by count, top 10."""
    hits = ctx.get_table("hits")
    hits = hits.copy()
    hits["one"] = 1
    return (
        hits.groupby(["one", "URL"], as_index=False).agg(c=("URL", "count")).sort_values("c", ascending=False).head(10)
    )


def q36_expression_impl(ctx: DataFrameContext) -> Any:
    """Q36: GROUP BY ClientIP and derived columns (ClientIP-1, -2, -3)."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.with_columns(
            (col("ClientIP") - lit(1)).alias("ip_m1"),
            (col("ClientIP") - lit(2)).alias("ip_m2"),
            (col("ClientIP") - lit(3)).alias("ip_m3"),
        )
        .group_by("ClientIP", "ip_m1", "ip_m2", "ip_m3")
        .agg(col("ClientIP").count().alias("c"))
        .sort("c", descending=True)
        .limit(10)
    )


def q36_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q36: GROUP BY ClientIP and derived columns (ClientIP-1, -2, -3)."""
    hits = ctx.get_table("hits")
    hits = hits.copy()
    hits["ip_m1"] = hits["ClientIP"] - 1
    hits["ip_m2"] = hits["ClientIP"] - 2
    hits["ip_m3"] = hits["ClientIP"] - 3
    return (
        hits.groupby(["ClientIP", "ip_m1", "ip_m2", "ip_m3"], as_index=False)
        .agg(c=("ClientIP", "count"))
        .sort_values("c", ascending=False)
        .head(10)
    )


# =============================================================================
# Time-Based Analysis (Q37-Q43)
# =============================================================================


def q37_expression_impl(ctx: DataFrameContext) -> Any:
    """Q37: Top URLs by page views for CounterID=62, July 2013."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.filter(
            (col("CounterID") == lit(62))
            & (col("EventDate") >= lit("2013-07-01"))
            & (col("EventDate") <= lit("2013-07-31"))
            & (col("DontCountHits") == lit(0))
            & (col("IsRefresh") == lit(0))
            & (col("URL") != lit(""))
        )
        .group_by("URL")
        .agg(col("URL").count().alias("PageViews"))
        .sort("PageViews", descending=True)
        .limit(10)
    )


def q37_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q37: Top URLs by page views for CounterID=62, July 2013."""
    hits = ctx.get_table("hits")
    filtered = hits[
        (hits["CounterID"] == 62)
        & (hits["EventDate"] >= "2013-07-01")
        & (hits["EventDate"] <= "2013-07-31")
        & (hits["DontCountHits"] == 0)
        & (hits["IsRefresh"] == 0)
        & (hits["URL"] != "")
    ]
    return (
        filtered.groupby(["URL"], as_index=False)
        .agg(PageViews=("URL", "count"))
        .sort_values("PageViews", ascending=False)
        .head(10)
    )


def q38_expression_impl(ctx: DataFrameContext) -> Any:
    """Q38: Top titles by page views for CounterID=62, July 2013."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.filter(
            (col("CounterID") == lit(62))
            & (col("EventDate") >= lit("2013-07-01"))
            & (col("EventDate") <= lit("2013-07-31"))
            & (col("DontCountHits") == lit(0))
            & (col("IsRefresh") == lit(0))
            & (col("Title") != lit(""))
        )
        .group_by("Title")
        .agg(col("Title").count().alias("PageViews"))
        .sort("PageViews", descending=True)
        .limit(10)
    )


def q38_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q38: Top titles by page views for CounterID=62, July 2013."""
    hits = ctx.get_table("hits")
    filtered = hits[
        (hits["CounterID"] == 62)
        & (hits["EventDate"] >= "2013-07-01")
        & (hits["EventDate"] <= "2013-07-31")
        & (hits["DontCountHits"] == 0)
        & (hits["IsRefresh"] == 0)
        & (hits["Title"] != "")
    ]
    return (
        filtered.groupby(["Title"], as_index=False)
        .agg(PageViews=("Title", "count"))
        .sort_values("PageViews", ascending=False)
        .head(10)
    )


def q39_expression_impl(ctx: DataFrameContext) -> Any:
    """Q39: URL page views with OFFSET 1000 (pagination)."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    sorted_result = (
        hits.filter(
            (col("CounterID") == lit(62))
            & (col("EventDate") >= lit("2013-07-01"))
            & (col("EventDate") <= lit("2013-07-31"))
            & (col("IsRefresh") == lit(0))
            & (col("IsLink") != lit(0))
            & (col("IsDownload") == lit(0))
        )
        .group_by("URL")
        .agg(col("URL").count().alias("PageViews"))
        .sort("PageViews", descending=True)
    )
    return sorted_result.slice(1000, 10)


def q39_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q39: URL page views with OFFSET 1000 (pagination)."""
    hits = ctx.get_table("hits")
    filtered = hits[
        (hits["CounterID"] == 62)
        & (hits["EventDate"] >= "2013-07-01")
        & (hits["EventDate"] <= "2013-07-31")
        & (hits["IsRefresh"] == 0)
        & (hits["IsLink"] != 0)
        & (hits["IsDownload"] == 0)
    ]
    sorted_result = (
        filtered.groupby(["URL"], as_index=False)
        .agg(PageViews=("URL", "count"))
        .sort_values("PageViews", ascending=False)
    )
    return sorted_result.iloc[1000:1010]


def q40_expression_impl(ctx: DataFrameContext) -> Any:
    """Q40: Traffic source analysis with CASE WHEN and OFFSET."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit

    filtered = hits.filter(
        (col("CounterID") == lit(62))
        & (col("EventDate") >= lit("2013-07-01"))
        & (col("EventDate") <= lit("2013-07-31"))
        & (col("IsRefresh") == lit(0))
    )
    # Add conditional Src column: CASE WHEN SearchEngineID=0 AND AdvEngineID=0 THEN Referer ELSE '' END
    with_src = filtered.with_columns(
        ctx.when((col("SearchEngineID") == lit(0)) & (col("AdvEngineID") == lit(0)))
        .then(col("Referer"))
        .otherwise(lit(""))
        .alias("Src")
    )
    sorted_result = (
        with_src.group_by("TraficSourceID", "SearchEngineID", "AdvEngineID", "Src", "URL")
        .agg(col("URL").count().alias("PageViews"))
        .sort("PageViews", descending=True)
    )
    return sorted_result.slice(1000, 10)


def q40_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q40: Traffic source analysis with CASE WHEN and OFFSET."""
    import numpy as np

    hits = ctx.get_table("hits")
    filtered = hits[
        (hits["CounterID"] == 62)
        & (hits["EventDate"] >= "2013-07-01")
        & (hits["EventDate"] <= "2013-07-31")
        & (hits["IsRefresh"] == 0)
    ].copy()
    filtered["Src"] = np.where(
        (filtered["SearchEngineID"] == 0) & (filtered["AdvEngineID"] == 0), filtered["Referer"], ""
    )
    sorted_result = (
        filtered.groupby(["TraficSourceID", "SearchEngineID", "AdvEngineID", "Src", "URL"], as_index=False)
        .agg(PageViews=("URL", "count"))
        .sort_values("PageViews", ascending=False)
    )
    return sorted_result.iloc[1000:1010]


def q41_expression_impl(ctx: DataFrameContext) -> Any:
    """Q41: URLHash + EventDate with IN clause and specific hash, OFFSET 100."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    sorted_result = (
        hits.filter(
            (col("CounterID") == lit(62))
            & (col("EventDate") >= lit("2013-07-01"))
            & (col("EventDate") <= lit("2013-07-31"))
            & (col("IsRefresh") == lit(0))
            & (col("TraficSourceID").is_in([-1, 6]))
            & (col("RefererHash") == lit(3594120000172545465))
        )
        .group_by("URLHash", "EventDate")
        .agg(col("URLHash").count().alias("PageViews"))
        .sort("PageViews", descending=True)
    )
    return sorted_result.slice(100, 10)


def q41_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q41: URLHash + EventDate with IN clause and specific hash, OFFSET 100."""
    hits = ctx.get_table("hits")
    filtered = hits[
        (hits["CounterID"] == 62)
        & (hits["EventDate"] >= "2013-07-01")
        & (hits["EventDate"] <= "2013-07-31")
        & (hits["IsRefresh"] == 0)
        & (hits["TraficSourceID"].isin([-1, 6]))
        & (hits["RefererHash"] == 3594120000172545465)
    ]
    sorted_result = (
        filtered.groupby(["URLHash", "EventDate"], as_index=False)
        .agg(PageViews=("URLHash", "count"))
        .sort_values("PageViews", ascending=False)
    )
    return sorted_result.iloc[100:110]


def q42_expression_impl(ctx: DataFrameContext) -> Any:
    """Q42: Window dimensions for specific URL hash, OFFSET 10000."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    sorted_result = (
        hits.filter(
            (col("CounterID") == lit(62))
            & (col("EventDate") >= lit("2013-07-01"))
            & (col("EventDate") <= lit("2013-07-31"))
            & (col("IsRefresh") == lit(0))
            & (col("DontCountHits") == lit(0))
            & (col("URLHash") == lit(2868770270353813622))
        )
        .group_by("WindowClientWidth", "WindowClientHeight")
        .agg(col("WindowClientWidth").count().alias("PageViews"))
        .sort("PageViews", descending=True)
    )
    return sorted_result.slice(10000, 10)


def q42_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q42: Window dimensions for specific URL hash, OFFSET 10000."""
    hits = ctx.get_table("hits")
    filtered = hits[
        (hits["CounterID"] == 62)
        & (hits["EventDate"] >= "2013-07-01")
        & (hits["EventDate"] <= "2013-07-31")
        & (hits["IsRefresh"] == 0)
        & (hits["DontCountHits"] == 0)
        & (hits["URLHash"] == 2868770270353813622)
    ]
    sorted_result = (
        filtered.groupby(["WindowClientWidth", "WindowClientHeight"], as_index=False)
        .agg(PageViews=("WindowClientWidth", "count"))
        .sort_values("PageViews", ascending=False)
    )
    return sorted_result.iloc[10000:10010]


def q43_expression_impl(ctx: DataFrameContext) -> Any:
    """Q43: Page views by minute with DATE_TRUNC."""
    hits = ctx.get_table("hits")
    col = ctx.col
    lit = ctx.lit
    return (
        hits.filter(
            (col("CounterID") == lit(62))
            & (col("EventDate") >= lit("2013-07-14"))
            & (col("EventDate") <= lit("2013-07-15"))
            & (col("IsRefresh") == lit(0))
            & (col("DontCountHits") == lit(0))
        )
        .with_columns(col("EventTime").dt.truncate("1m").alias("M"))
        .group_by("M")
        .agg(col("M").count().alias("PageViews"))
        .sort("M")
    )


def q43_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q43: Page views by minute with DATE_TRUNC."""
    hits = ctx.get_table("hits")
    filtered = hits[
        (hits["CounterID"] == 62)
        & (hits["EventDate"] >= "2013-07-14")
        & (hits["EventDate"] <= "2013-07-15")
        & (hits["IsRefresh"] == 0)
        & (hits["DontCountHits"] == 0)
    ].copy()
    filtered["M"] = filtered["EventTime"].dt.floor("min")
    return filtered.groupby(["M"], as_index=False).agg(PageViews=("M", "count")).sort_values("M")


# =============================================================================
# Query Registration
# =============================================================================

_CATEGORY_CODES = {
    "AG": QueryCategory.AGGREGATE,
    "AN": QueryCategory.ANALYTICAL,
    "FI": QueryCategory.FILTER,
    "GB": QueryCategory.GROUP_BY,
    "PR": QueryCategory.PROJECTION,
    "SC": QueryCategory.SCAN,
    "SO": QueryCategory.SORT,
}

_QUERY_METADATA = """Q1|Full Scan Count|COUNT(*) full table scan - baseline performance test|SC,AG
Q2|Filtered Count|COUNT(*) with single equality filter on AdvEngineID|FI,AG
Q3|Multi-Aggregate Scan|SUM, COUNT, AVG on full table scan - multiple aggregate functions|SC,AG
Q4|Average UserID|AVG on BIGINT column - numeric precision test|SC,AG
Q5|Unique Users|COUNT(DISTINCT UserID) - cardinality estimation|SC,AG
Q6|Unique Search Phrases|COUNT(DISTINCT SearchPhrase) - string cardinality|SC,AG
Q7|Date Range|MIN/MAX on EventDate - date column statistics|SC,AG
Q8|AdvEngine Distribution|GROUP BY AdvEngineID with COUNT, filtered and sorted|FI,GB,SO
Q9|Users by Region|COUNT(DISTINCT UserID) by RegionID, top 10|GB,SO,AG
Q10|Region Multi-Aggregate|Multi-aggregate by RegionID - SUM, COUNT, AVG, COUNT(DISTINCT)|GB,SO,AG
Q11|Mobile Phone Models|Unique users by phone model, filtered on non-empty|FI,GB,SO
Q12|Phone + Model Unique Users|Unique users by phone and model, multi-column grouping|FI,GB,SO
Q13|Top Search Phrases|Most frequent non-empty search phrases|FI,GB,SO
Q14|Search Phrase Unique Users|Top search phrases by unique user count|FI,GB,SO
Q15|Search Engine + Phrase|Search engine and phrase combination counts|FI,GB,SO
Q16|Top Users|Most active users by event count|GB,SO
Q17|User Search Activity|Top user + search phrase combinations by count|GB,SO
Q18|User Search Unordered|User + search phrase group without ordering - nondeterministic|GB
Q19|User Minute Activity|User + minute + search phrase grouping with datetime extraction|GB,SO,AN
Q20|User Point Lookup|Single user lookup by exact UserID value|FI,SC
Q21|URL Google Count|Count rows where URL contains 'google' - string containment test|FI,AG
Q22|Google URL Search Phrases|Top search phrases for google URLs with MIN(URL)|FI,GB,SO
Q23|Google Title Analysis|Search phrases for Google titles excluding .google. URLs - case-sensitive LIKE|FI,GB,SO,AN
Q24|Google URL Full Rows|All columns for google URLs sorted by EventTime - wide output|FI,SO,PR
Q25|Search Phrase by Time|Non-empty search phrases sorted by EventTime|FI,SO,PR
Q26|Search Phrase Lexicographic|Non-empty search phrases sorted lexicographically|FI,SO,PR
Q27|Search Phrase Compound Sort|Non-empty search phrases with compound sort (EventTime, SearchPhrase)|FI,SO,PR
Q28|URL Length Analysis|Average URL length by counter with HAVING > 100000|GB,AG,AN
Q29|Domain Extraction|Regex domain extraction from Referer with HAVING - complex string operation|GB,AG,AN
Q30|Wide Aggregation|90-column SUM(ResolutionWidth + N) - wide aggregation test|SC,AG
Q31|Search Engine Client Analysis|Multi-agg by SearchEngineID + ClientIP, filtered on non-empty search|FI,GB,SO
Q32|Watch Client Analysis (Filtered)|Multi-agg by WatchID + ClientIP, filtered - high cardinality|FI,GB,SO
Q33|Watch Client Analysis (Unfiltered)|Multi-agg by WatchID + ClientIP, unfiltered - high cardinality full scan|GB,SO
Q34|Top URLs|Top URLs by count - high cardinality text GROUP BY|GB,SO
Q35|Literal Column URL Group|GROUP BY literal constant column plus URL - tests derived column grouping|GB,SO,AN
Q36|Derived Column Group|GROUP BY ClientIP and derived arithmetic columns - expression grouping|GB,SO,AN
Q37|July URL Page Views|Top URLs for CounterID=62, July 2013 with multiple filters|FI,GB,SO
Q38|July Title Page Views|Top titles for CounterID=62, July 2013 with multiple filters|FI,GB,SO
Q39|URL Views with Offset|URL page views with OFFSET 1000 - pagination test|FI,GB,SO
Q40|Traffic Source CASE WHEN|Traffic source analysis with CASE WHEN conditional and OFFSET|FI,GB,SO,AN
Q41|URL Hash IN Clause|URLHash + EventDate with IN clause filter and OFFSET 100|FI,GB,SO
Q42|Window Dimensions|Window dimensions for specific URL hash with large OFFSET 10000|FI,GB,SO
Q43|Minute Granularity|Page views by minute with DATE_TRUNC - temporal aggregation|FI,GB,SO,AN
"""


def _impl_for(query_id: str, family: str) -> Any:
    return globals()[f"q{query_id[1:]}_{family}_impl"]


def _register_all_queries() -> None:
    for query_id, query_name, description, category_codes in reader(_QUERY_METADATA.splitlines(), delimiter="|"):
        register_query(
            DataFrameQuery(
                query_id=query_id,
                query_name=query_name,
                description=description,
                categories=[_CATEGORY_CODES[code] for code in category_codes.split(",")],
                expression_impl=_impl_for(query_id, "expression"),
                pandas_impl=_impl_for(query_id, "pandas"),
            )
        )


_register_all_queries()
