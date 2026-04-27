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


def _register_all_queries() -> None:
    """Register all 43 ClickBench DataFrame queries."""
    # Basic aggregation (Q1-Q7)
    register_query(
        DataFrameQuery(
            query_id="Q1",
            query_name="Full Scan Count",
            description="COUNT(*) full table scan - baseline performance test",
            categories=[QueryCategory.SCAN, QueryCategory.AGGREGATE],
            expression_impl=q1_expression_impl,
            pandas_impl=q1_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q2",
            query_name="Filtered Count",
            description="COUNT(*) with single equality filter on AdvEngineID",
            categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
            expression_impl=q2_expression_impl,
            pandas_impl=q2_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q3",
            query_name="Multi-Aggregate Scan",
            description="SUM, COUNT, AVG on full table scan - multiple aggregate functions",
            categories=[QueryCategory.SCAN, QueryCategory.AGGREGATE],
            expression_impl=q3_expression_impl,
            pandas_impl=q3_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q4",
            query_name="Average UserID",
            description="AVG on BIGINT column - numeric precision test",
            categories=[QueryCategory.SCAN, QueryCategory.AGGREGATE],
            expression_impl=q4_expression_impl,
            pandas_impl=q4_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q5",
            query_name="Unique Users",
            description="COUNT(DISTINCT UserID) - cardinality estimation",
            categories=[QueryCategory.SCAN, QueryCategory.AGGREGATE],
            expression_impl=q5_expression_impl,
            pandas_impl=q5_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q6",
            query_name="Unique Search Phrases",
            description="COUNT(DISTINCT SearchPhrase) - string cardinality",
            categories=[QueryCategory.SCAN, QueryCategory.AGGREGATE],
            expression_impl=q6_expression_impl,
            pandas_impl=q6_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q7",
            query_name="Date Range",
            description="MIN/MAX on EventDate - date column statistics",
            categories=[QueryCategory.SCAN, QueryCategory.AGGREGATE],
            expression_impl=q7_expression_impl,
            pandas_impl=q7_pandas_impl,
        )
    )

    # Grouping and ordering (Q8-Q15)
    register_query(
        DataFrameQuery(
            query_id="Q8",
            query_name="AdvEngine Distribution",
            description="GROUP BY AdvEngineID with COUNT, filtered and sorted",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q8_expression_impl,
            pandas_impl=q8_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q9",
            query_name="Users by Region",
            description="COUNT(DISTINCT UserID) by RegionID, top 10",
            categories=[QueryCategory.GROUP_BY, QueryCategory.SORT, QueryCategory.AGGREGATE],
            expression_impl=q9_expression_impl,
            pandas_impl=q9_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q10",
            query_name="Region Multi-Aggregate",
            description="Multi-aggregate by RegionID - SUM, COUNT, AVG, COUNT(DISTINCT)",
            categories=[QueryCategory.GROUP_BY, QueryCategory.SORT, QueryCategory.AGGREGATE],
            expression_impl=q10_expression_impl,
            pandas_impl=q10_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q11",
            query_name="Mobile Phone Models",
            description="Unique users by phone model, filtered on non-empty",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q11_expression_impl,
            pandas_impl=q11_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q12",
            query_name="Phone + Model Unique Users",
            description="Unique users by phone and model, multi-column grouping",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q12_expression_impl,
            pandas_impl=q12_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q13",
            query_name="Top Search Phrases",
            description="Most frequent non-empty search phrases",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q13_expression_impl,
            pandas_impl=q13_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q14",
            query_name="Search Phrase Unique Users",
            description="Top search phrases by unique user count",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q14_expression_impl,
            pandas_impl=q14_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q15",
            query_name="Search Engine + Phrase",
            description="Search engine and phrase combination counts",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q15_expression_impl,
            pandas_impl=q15_pandas_impl,
        )
    )

    # User analysis (Q16-Q20)
    register_query(
        DataFrameQuery(
            query_id="Q16",
            query_name="Top Users",
            description="Most active users by event count",
            categories=[QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q16_expression_impl,
            pandas_impl=q16_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q17",
            query_name="User Search Activity",
            description="Top user + search phrase combinations by count",
            categories=[QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q17_expression_impl,
            pandas_impl=q17_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q18",
            query_name="User Search Unordered",
            description="User + search phrase group without ordering - nondeterministic",
            categories=[QueryCategory.GROUP_BY],
            expression_impl=q18_expression_impl,
            pandas_impl=q18_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q19",
            query_name="User Minute Activity",
            description="User + minute + search phrase grouping with datetime extraction",
            categories=[QueryCategory.GROUP_BY, QueryCategory.SORT, QueryCategory.ANALYTICAL],
            expression_impl=q19_expression_impl,
            pandas_impl=q19_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q20",
            query_name="User Point Lookup",
            description="Single user lookup by exact UserID value",
            categories=[QueryCategory.FILTER, QueryCategory.SCAN],
            expression_impl=q20_expression_impl,
            pandas_impl=q20_pandas_impl,
        )
    )

    # Text and pattern matching (Q21-Q27)
    register_query(
        DataFrameQuery(
            query_id="Q21",
            query_name="URL Google Count",
            description="Count rows where URL contains 'google' - string containment test",
            categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
            expression_impl=q21_expression_impl,
            pandas_impl=q21_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q22",
            query_name="Google URL Search Phrases",
            description="Top search phrases for google URLs with MIN(URL)",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q22_expression_impl,
            pandas_impl=q22_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q23",
            query_name="Google Title Analysis",
            description="Search phrases for Google titles excluding .google. URLs - case-sensitive LIKE",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT, QueryCategory.ANALYTICAL],
            expression_impl=q23_expression_impl,
            pandas_impl=q23_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q24",
            query_name="Google URL Full Rows",
            description="All columns for google URLs sorted by EventTime - wide output",
            categories=[QueryCategory.FILTER, QueryCategory.SORT, QueryCategory.PROJECTION],
            expression_impl=q24_expression_impl,
            pandas_impl=q24_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q25",
            query_name="Search Phrase by Time",
            description="Non-empty search phrases sorted by EventTime",
            categories=[QueryCategory.FILTER, QueryCategory.SORT, QueryCategory.PROJECTION],
            expression_impl=q25_expression_impl,
            pandas_impl=q25_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q26",
            query_name="Search Phrase Lexicographic",
            description="Non-empty search phrases sorted lexicographically",
            categories=[QueryCategory.FILTER, QueryCategory.SORT, QueryCategory.PROJECTION],
            expression_impl=q26_expression_impl,
            pandas_impl=q26_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q27",
            query_name="Search Phrase Compound Sort",
            description="Non-empty search phrases with compound sort (EventTime, SearchPhrase)",
            categories=[QueryCategory.FILTER, QueryCategory.SORT, QueryCategory.PROJECTION],
            expression_impl=q27_expression_impl,
            pandas_impl=q27_pandas_impl,
        )
    )

    # String operations (Q28-Q29)
    register_query(
        DataFrameQuery(
            query_id="Q28",
            query_name="URL Length Analysis",
            description="Average URL length by counter with HAVING > 100000",
            categories=[QueryCategory.GROUP_BY, QueryCategory.AGGREGATE, QueryCategory.ANALYTICAL],
            expression_impl=q28_expression_impl,
            pandas_impl=q28_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q29",
            query_name="Domain Extraction",
            description="Regex domain extraction from Referer with HAVING - complex string operation",
            categories=[QueryCategory.GROUP_BY, QueryCategory.AGGREGATE, QueryCategory.ANALYTICAL],
            expression_impl=q29_expression_impl,
            pandas_impl=q29_pandas_impl,
        )
    )

    # Mathematical operations (Q30)
    register_query(
        DataFrameQuery(
            query_id="Q30",
            query_name="Wide Aggregation",
            description="90-column SUM(ResolutionWidth + N) - wide aggregation test",
            categories=[QueryCategory.SCAN, QueryCategory.AGGREGATE],
            expression_impl=q30_expression_impl,
            pandas_impl=q30_pandas_impl,
        )
    )

    # Complex grouping (Q31-Q36)
    register_query(
        DataFrameQuery(
            query_id="Q31",
            query_name="Search Engine Client Analysis",
            description="Multi-agg by SearchEngineID + ClientIP, filtered on non-empty search",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q31_expression_impl,
            pandas_impl=q31_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q32",
            query_name="Watch Client Analysis (Filtered)",
            description="Multi-agg by WatchID + ClientIP, filtered - high cardinality",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q32_expression_impl,
            pandas_impl=q32_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q33",
            query_name="Watch Client Analysis (Unfiltered)",
            description="Multi-agg by WatchID + ClientIP, unfiltered - high cardinality full scan",
            categories=[QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q33_expression_impl,
            pandas_impl=q33_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q34",
            query_name="Top URLs",
            description="Top URLs by count - high cardinality text GROUP BY",
            categories=[QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q34_expression_impl,
            pandas_impl=q34_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q35",
            query_name="Literal Column URL Group",
            description="GROUP BY literal constant column plus URL - tests derived column grouping",
            categories=[QueryCategory.GROUP_BY, QueryCategory.SORT, QueryCategory.ANALYTICAL],
            expression_impl=q35_expression_impl,
            pandas_impl=q35_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q36",
            query_name="Derived Column Group",
            description="GROUP BY ClientIP and derived arithmetic columns - expression grouping",
            categories=[QueryCategory.GROUP_BY, QueryCategory.SORT, QueryCategory.ANALYTICAL],
            expression_impl=q36_expression_impl,
            pandas_impl=q36_pandas_impl,
        )
    )

    # Time-based analysis (Q37-Q43)
    register_query(
        DataFrameQuery(
            query_id="Q37",
            query_name="July URL Page Views",
            description="Top URLs for CounterID=62, July 2013 with multiple filters",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q37_expression_impl,
            pandas_impl=q37_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q38",
            query_name="July Title Page Views",
            description="Top titles for CounterID=62, July 2013 with multiple filters",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q38_expression_impl,
            pandas_impl=q38_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q39",
            query_name="URL Views with Offset",
            description="URL page views with OFFSET 1000 - pagination test",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q39_expression_impl,
            pandas_impl=q39_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q40",
            query_name="Traffic Source CASE WHEN",
            description="Traffic source analysis with CASE WHEN conditional and OFFSET",
            categories=[
                QueryCategory.FILTER,
                QueryCategory.GROUP_BY,
                QueryCategory.SORT,
                QueryCategory.ANALYTICAL,
            ],
            expression_impl=q40_expression_impl,
            pandas_impl=q40_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q41",
            query_name="URL Hash IN Clause",
            description="URLHash + EventDate with IN clause filter and OFFSET 100",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q41_expression_impl,
            pandas_impl=q41_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q42",
            query_name="Window Dimensions",
            description="Window dimensions for specific URL hash with large OFFSET 10000",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q42_expression_impl,
            pandas_impl=q42_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q43",
            query_name="Minute Granularity",
            description="Page views by minute with DATE_TRUNC - temporal aggregation",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT, QueryCategory.ANALYTICAL],
            expression_impl=q43_expression_impl,
            pandas_impl=q43_pandas_impl,
        )
    )


_register_all_queries()
