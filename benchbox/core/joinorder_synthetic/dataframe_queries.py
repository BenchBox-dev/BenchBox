"""Synthetic JoinOrder DataFrame queries for Expression and Pandas families.

Implements the 13 historical JoinOrder smoke-test queries for DataFrame execution.

This internal module is schema-compatible with canonical JOB, but uses
uniformly-random synthetic data. The key translation challenge is converting
implicit cross-joins (comma-separated FROM clauses with WHERE join conditions)
into explicit .join() chains.

NOTE: Unlike the SQL version which stresses query optimizer join ordering,
the DataFrame version defines an explicit join sequence. The intent shifts
from optimizer stress-testing to measuring multi-join execution performance
across platforms with identical join sequences.

Each query returns MIN aggregations over filtered multi-table joins.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory, QueryRegistry

# ===========================================================================
# Expression Family (Polars, DataFusion, PySpark)
#
# Translation pattern for implicit cross-joins with WHERE conditions:
#   FROM t1, t2, t3 WHERE t1.id = t2.fk AND t2.id = t3.fk AND filter
#   -> t1.filter(filter).join(t2, ...).join(t3, ...)
#
# All queries use title as the central hub table (most queries reference it).
# ===========================================================================


def q1a_expression_impl(ctx: DataFrameContext) -> Any:
    """1a: Production companies with top 250 rank."""
    company_type = ctx.get_table("company_type")
    info_type = ctx.get_table("info_type")
    movie_companies = ctx.get_table("movie_companies")
    movie_info_idx = ctx.get_table("movie_info_idx")
    title = ctx.get_table("title")
    col, lit = ctx.col, ctx.lit

    ct = company_type.filter(col("kind") == lit("production companies")).select(col("id").alias("ct_id"))
    it = info_type.filter(col("info") == lit("top 250 rank")).select(col("id").alias("it_id"))
    mc = movie_companies.filter(
        (~col("note").str.contains("as Metro-Goldwyn-Mayer Pictures"))
        & (col("note").str.contains("co-production") | col("note").str.contains("presents"))
    ).select(col("movie_id").alias("mc_movie_id"), col("company_type_id"), col("note").alias("mc_note"))

    return (
        title.join(mc, left_on="id", right_on="mc_movie_id")
        .join(ct, left_on="company_type_id", right_on="ct_id")
        .join(movie_info_idx, left_on="id", right_on="movie_id")
        .join(it, left_on="info_type_id", right_on="it_id")
        .select(
            col("mc_note").min().alias("production_note"),
            col("title").min().alias("movie_title"),
            col("production_year").min().alias("movie_year"),
        )
    )


def q1b_expression_impl(ctx: DataFrameContext) -> Any:
    """1b: Variant of 1a with bottom 10 rank predicate."""
    company_type = ctx.get_table("company_type")
    info_type = ctx.get_table("info_type")
    movie_companies = ctx.get_table("movie_companies")
    movie_info_idx = ctx.get_table("movie_info_idx")
    title = ctx.get_table("title")
    col, lit = ctx.col, ctx.lit

    ct = company_type.filter(col("kind") == lit("production companies")).select(col("id").alias("ct_id"))
    it = info_type.filter(col("info") == lit("bottom 10 rank")).select(col("id").alias("it_id"))
    mc = movie_companies.filter(
        (~col("note").str.contains("as Metro-Goldwyn-Mayer Pictures"))
        & (col("note").str.contains("co-production") | col("note").str.contains("presents"))
    ).select(col("movie_id").alias("mc_movie_id"), col("company_type_id"), col("note").alias("mc_note"))

    return (
        title.join(mc, left_on="id", right_on="mc_movie_id")
        .join(ct, left_on="company_type_id", right_on="ct_id")
        .join(movie_info_idx, left_on="id", right_on="movie_id")
        .join(it, left_on="info_type_id", right_on="it_id")
        .select(
            col("mc_note").min().alias("production_note"),
            col("title").min().alias("movie_title"),
            col("production_year").min().alias("movie_year"),
        )
    )


def q2a_expression_impl(ctx: DataFrameContext) -> Any:
    """2a: German production company movies with specific keyword."""
    company_name = ctx.get_table("company_name")
    keyword = ctx.get_table("keyword")
    movie_companies = ctx.get_table("movie_companies")
    movie_keyword = ctx.get_table("movie_keyword")
    title = ctx.get_table("title")
    col, lit = ctx.col, ctx.lit

    cn = company_name.filter(col("country_code") == lit("[de]")).select(col("id").alias("cn_id"))
    k = keyword.filter(col("keyword") == lit("character-name-in-title")).select(col("id").alias("k_id"))
    mc = movie_companies.select(col("movie_id").alias("mc_movie_id"), col("company_id"))
    mk = movie_keyword.select(col("movie_id").alias("mk_movie_id"), col("keyword_id"))

    return (
        title.join(mc, left_on="id", right_on="mc_movie_id")
        .join(cn, left_on="company_id", right_on="cn_id")
        .join(mk, left_on="id", right_on="mk_movie_id")
        .join(k, left_on="keyword_id", right_on="k_id")
        .select(col("title").min().alias("movie_title"))
    )


def q3a_expression_impl(ctx: DataFrameContext) -> Any:
    """3a: Scandinavian/German movies with sequel keywords after 1990."""
    keyword = ctx.get_table("keyword")
    movie_info = ctx.get_table("movie_info")
    movie_keyword = ctx.get_table("movie_keyword")
    title = ctx.get_table("title")
    col, lit = ctx.col, ctx.lit

    k = keyword.filter(col("keyword").str.contains("sequel")).select(col("id").alias("k_id"))
    mi = movie_info.filter(
        col("info").is_in(
            ["Sweden", "Norway", "Germany", "Denmark", "Swedish", "Denish", "Norwegian", "German", "USA", "American"]
        )
    ).select(col("movie_id").alias("mi_movie_id"))
    mk = movie_keyword.select(col("movie_id").alias("mk_movie_id"), col("keyword_id"))

    return (
        title.filter(col("production_year") > lit(1990))
        .join(mi, left_on="id", right_on="mi_movie_id")
        .join(mk, left_on="id", right_on="mk_movie_id")
        .join(k, left_on="keyword_id", right_on="k_id")
        .select(col("title").min().alias("movie_title"))
    )


def q4a_expression_impl(ctx: DataFrameContext) -> Any:
    """4a: Sequel movies with rating > 2.0 after 1990."""
    info_type = ctx.get_table("info_type")
    keyword = ctx.get_table("keyword")
    movie_info_idx = ctx.get_table("movie_info_idx")
    movie_keyword = ctx.get_table("movie_keyword")
    title = ctx.get_table("title")
    col, lit = ctx.col, ctx.lit

    it = info_type.filter(col("info") == lit("rating")).select(col("id").alias("it_id"))
    k = keyword.filter(col("keyword").str.contains("sequel")).select(col("id").alias("k_id"))
    mi_idx = movie_info_idx.filter(col("info") > lit("2.0")).select(
        col("movie_id").alias("mi_movie_id"), col("info_type_id"), col("info").alias("rating")
    )
    mk = movie_keyword.select(col("movie_id").alias("mk_movie_id"), col("keyword_id"))

    return (
        title.filter(col("production_year") > lit(1990))
        .join(mi_idx, left_on="id", right_on="mi_movie_id")
        .join(it, left_on="info_type_id", right_on="it_id")
        .join(mk, left_on="id", right_on="mk_movie_id")
        .join(k, left_on="keyword_id", right_on="k_id")
        .select(
            col("rating").min().alias("rating"),
            col("title").min().alias("movie_title"),
        )
    )


def q5a_expression_impl(ctx: DataFrameContext) -> Any:
    """5a: European theatrical movies after 2005."""
    company_type = ctx.get_table("company_type")
    info_type = ctx.get_table("info_type")
    movie_companies = ctx.get_table("movie_companies")
    movie_info = ctx.get_table("movie_info")
    title = ctx.get_table("title")
    col, lit = ctx.col, ctx.lit

    ct = company_type.filter(col("kind") == lit("production companies")).select(col("id").alias("ct_id"))
    it = info_type.select(col("id").alias("it_id"))  # no filter on info_type in SQL
    mc = movie_companies.filter(col("note").str.contains("theatrical") & col("note").str.contains("France")).select(
        col("movie_id").alias("mc_movie_id"), col("company_type_id")
    )
    mi = movie_info.filter(
        col("info").is_in(["Sweden", "Norway", "Germany", "Denmark", "Swedish", "Denish", "Norwegian", "German"])
    ).select(col("movie_id").alias("mi_movie_id"), col("info_type_id"))

    return (
        title.filter(col("production_year") > lit(2005))
        .join(mi, left_on="id", right_on="mi_movie_id")
        .join(it, left_on="info_type_id", right_on="it_id")
        .join(mc, left_on="id", right_on="mc_movie_id")
        .join(ct, left_on="company_type_id", right_on="ct_id")
        .select(col("title").min().alias("typical_european_movie"))
    )


def q6a_expression_impl(ctx: DataFrameContext) -> Any:
    """6a: Superhero movies with Robert Downey Jr. after 2000."""
    cast_info = ctx.get_table("cast_info")
    keyword = ctx.get_table("keyword")
    movie_keyword = ctx.get_table("movie_keyword")
    name = ctx.get_table("name")
    title = ctx.get_table("title")
    col, lit = ctx.col, ctx.lit

    k = keyword.filter(
        col("keyword").is_in(
            ["superhero", "sequel", "second-part", "marvel-comics", "based-on-comic", "tv-special", "fight", "violence"]
        )
    ).select(col("id").alias("k_id"), col("keyword"))
    n = name.filter(col("name").str.contains("Downey") & col("name").str.contains("Robert")).select(
        col("id").alias("n_id"), col("name").alias("actor_name")
    )
    mk = movie_keyword.select(col("movie_id").alias("mk_movie_id"), col("keyword_id"))
    ci = cast_info.select(col("movie_id").alias("ci_movie_id"), col("person_id"))

    return (
        title.filter(col("production_year") > lit(2000))
        .join(mk, left_on="id", right_on="mk_movie_id")
        .join(k, left_on="keyword_id", right_on="k_id")
        .join(ci, left_on="id", right_on="ci_movie_id")
        .join(n, left_on="person_id", right_on="n_id")
        .select(
            col("keyword").min().alias("movie_keyword"),
            col("actor_name").min().alias("actor_name"),
            col("title").min().alias("hero_movie"),
        )
    )


def q7a_expression_impl(ctx: DataFrameContext) -> Any:
    """7a: Biography movies with specific person criteria (8 tables)."""
    aka_name = ctx.get_table("aka_name")
    cast_info = ctx.get_table("cast_info")
    info_type = ctx.get_table("info_type")
    link_type = ctx.get_table("link_type")
    movie_link = ctx.get_table("movie_link")
    name = ctx.get_table("name")
    person_info = ctx.get_table("person_info")
    title = ctx.get_table("title")
    col, lit = ctx.col, ctx.lit

    it = info_type.filter(col("info") == lit("mini biography")).select(col("id").alias("it_id"))
    lt = link_type.filter(col("link") == lit("features")).select(col("id").alias("lt_id"))
    n = name.filter(col("name_pcode_cf").str.starts_with("D") & (col("gender") == lit("m"))).select(
        col("id").alias("n_id"), col("name").alias("person_name")
    )
    pi = person_info.filter(col("note") == lit("Volker Boehm")).select(
        col("person_id").alias("pi_person_id"), col("info_type_id")
    )
    an = aka_name.filter(col("name").str.contains("a")).select(col("person_id").alias("an_person_id"))
    ci = cast_info.select(col("person_id").alias("ci_person_id"), col("movie_id").alias("ci_movie_id"))
    ml = movie_link.select(col("linked_movie_id"), col("link_type_id"))

    return (
        title.filter(col("production_year").is_between(1980, 1995))
        .join(ci, left_on="id", right_on="ci_movie_id")
        .join(n, left_on="ci_person_id", right_on="n_id")
        .join(pi, left_on="ci_person_id", right_on="pi_person_id")
        .join(it, left_on="info_type_id", right_on="it_id")
        .join(an, left_on="ci_person_id", right_on="an_person_id")
        .join(ml, left_on="id", right_on="linked_movie_id")
        .join(lt, left_on="link_type_id", right_on="lt_id")
        .select(
            col("person_name").min().alias("of_person"),
            col("title").min().alias("biography_movie"),
        )
    )


def q8a_expression_impl(ctx: DataFrameContext) -> Any:
    """8a: Japanese dubbed movies with specific actress criteria (7 tables)."""
    aka_name = ctx.get_table("aka_name")
    cast_info = ctx.get_table("cast_info")
    company_name = ctx.get_table("company_name")
    movie_companies = ctx.get_table("movie_companies")
    name = ctx.get_table("name")
    role_type = ctx.get_table("role_type")
    title = ctx.get_table("title")
    col, lit = ctx.col, ctx.lit

    cn = company_name.filter(col("country_code") == lit("[jp]")).select(col("id").alias("cn_id"))
    rt = role_type.filter(col("role") == lit("actress")).select(col("id").alias("rt_id"))
    n1 = name.filter(col("name").str.contains("Yo") & (~col("name").str.contains("Yu"))).select(
        col("id").alias("n1_id")
    )
    ci = cast_info.filter(col("note") == lit("(voice: Japanese version)")).select(
        col("person_id").alias("ci_person_id"), col("movie_id").alias("ci_movie_id"), col("role_id")
    )
    mc = movie_companies.filter(col("note").str.contains("Japan") & (~col("note").str.contains("USA"))).select(
        col("movie_id").alias("mc_movie_id"), col("company_id")
    )
    an1 = aka_name.select(col("person_id").alias("an1_person_id"), col("name").alias("aka_name"))

    return (
        title.join(mc, left_on="id", right_on="mc_movie_id")
        .join(cn, left_on="company_id", right_on="cn_id")
        .join(ci, left_on="id", right_on="ci_movie_id")
        .join(n1, left_on="ci_person_id", right_on="n1_id")
        .join(rt, left_on="role_id", right_on="rt_id")
        .join(an1, left_on="ci_person_id", right_on="an1_person_id")
        .select(
            col("aka_name").min().alias("actress_pseudonym"),
            col("title").min().alias("japanese_movie_dubbed"),
        )
    )


def q9a_expression_impl(ctx: DataFrameContext) -> Any:
    """9a: American voice actress movies (8 tables)."""
    aka_name = ctx.get_table("aka_name")
    char_name = ctx.get_table("char_name")
    cast_info = ctx.get_table("cast_info")
    company_name = ctx.get_table("company_name")
    movie_companies = ctx.get_table("movie_companies")
    name = ctx.get_table("name")
    role_type = ctx.get_table("role_type")
    title = ctx.get_table("title")
    col, lit = ctx.col, ctx.lit

    cn = company_name.filter(col("country_code") == lit("[us]")).select(col("id").alias("cn_id"))
    rt = role_type.filter(col("role") == lit("actress")).select(col("id").alias("rt_id"))
    n = name.filter((col("gender") == lit("f")) & col("name").str.contains("An")).select(
        col("id").alias("n_id"), col("name").alias("actress_name")
    )
    ci = cast_info.filter(
        col("note").is_in(["(voice)", "(voice: Japanese version)", "(voice) (uncredited)", "(voice: English version)"])
    ).select(
        col("person_id").alias("ci_person_id"),
        col("movie_id").alias("ci_movie_id"),
        col("role_id"),
        col("person_role_id"),
    )
    mc = movie_companies.filter(col("note").str.contains("USA") & (~col("note").str.contains("worldwide"))).select(
        col("movie_id").alias("mc_movie_id"), col("company_id")
    )
    an = aka_name.select(col("person_id").alias("an_person_id"), col("name").alias("alt_name"))
    chn = char_name.select(col("id").alias("chn_id"), col("name").alias("char_name_val"))

    return (
        title.filter(col("production_year").is_between(2005, 2015))
        .join(ci, left_on="id", right_on="ci_movie_id")
        .join(mc, left_on="id", right_on="mc_movie_id")
        .join(cn, left_on="company_id", right_on="cn_id")
        .join(n, left_on="ci_person_id", right_on="n_id")
        .join(rt, left_on="role_id", right_on="rt_id")
        .join(chn, left_on="person_role_id", right_on="chn_id")
        .join(an, left_on="ci_person_id", right_on="an_person_id")
        .select(
            col("alt_name").min().alias("alternative_name"),
            col("char_name_val").min().alias("voiced_character_name"),
            col("actress_name").min().alias("voicing_actress"),
            col("title").min().alias("american_movie"),
        )
    )


def q10a_expression_impl(ctx: DataFrameContext) -> Any:
    """10a: American producer movies after 1990 (7 tables)."""
    char_name = ctx.get_table("char_name")
    cast_info = ctx.get_table("cast_info")
    company_name = ctx.get_table("company_name")
    company_type = ctx.get_table("company_type")
    movie_companies = ctx.get_table("movie_companies")
    role_type = ctx.get_table("role_type")
    title = ctx.get_table("title")
    col, lit = ctx.col, ctx.lit

    cn = company_name.filter(col("country_code") == lit("[us]")).select(col("id").alias("cn_id"))
    ct = company_type.select(col("id").alias("ct_id"))
    rt = role_type.filter(col("role") == lit("producer")).select(col("id").alias("rt_id"))
    ci = cast_info.filter(col("note").str.contains("producer")).select(
        col("person_id"), col("movie_id").alias("ci_movie_id"), col("role_id"), col("person_role_id")
    )
    mc = movie_companies.select(col("movie_id").alias("mc_movie_id"), col("company_id"), col("company_type_id"))
    chn = char_name.select(col("id").alias("chn_id"), col("name").alias("character"))

    return (
        title.filter(col("production_year") > lit(1990))
        .join(ci, left_on="id", right_on="ci_movie_id")
        .join(rt, left_on="role_id", right_on="rt_id")
        .join(chn, left_on="person_role_id", right_on="chn_id")
        .join(mc, left_on="id", right_on="mc_movie_id")
        .join(ct, left_on="company_type_id", right_on="ct_id")
        .join(cn, left_on="company_id", right_on="cn_id")
        .select(
            col("character").min().alias("character"),
            col("title").min().alias("movie_with_american_producer"),
        )
    )


def q11a_expression_impl(ctx: DataFrameContext) -> Any:
    """11a: Non-Polish sequel movies with follow links (9 tables - most complex)."""
    company_name = ctx.get_table("company_name")
    company_type = ctx.get_table("company_type")
    keyword = ctx.get_table("keyword")
    link_type = ctx.get_table("link_type")
    movie_companies = ctx.get_table("movie_companies")
    movie_info = ctx.get_table("movie_info")
    movie_keyword = ctx.get_table("movie_keyword")
    movie_link = ctx.get_table("movie_link")
    title = ctx.get_table("title")
    col, lit = ctx.col, ctx.lit

    cn = company_name.filter(
        (col("country_code") != lit("[pl]")) & (col("name").str.contains("Film") | col("name").str.contains("Warner"))
    ).select(col("id").alias("cn_id"), col("name").alias("company"))
    ct = company_type.filter(col("kind") == lit("production companies")).select(col("id").alias("ct_id"))
    k = keyword.filter(col("keyword") == lit("sequel")).select(col("id").alias("k_id"))
    lt = link_type.filter(col("link").str.contains("follow")).select(col("id").alias("lt_id"), col("link"))
    mc = movie_companies.filter(col("note").is_null()).select(
        col("movie_id").alias("mc_movie_id"), col("company_id"), col("company_type_id")
    )
    mi = movie_info.filter(
        col("info").is_in(
            ["Sweden", "Norway", "Germany", "Denmark", "Swedish", "Denish", "Norwegian", "German", "English"]
        )
    ).select(col("movie_id").alias("mi_movie_id"))
    mk = movie_keyword.select(col("movie_id").alias("mk_movie_id"), col("keyword_id"))
    ml = movie_link.select(col("movie_id").alias("ml_movie_id"), col("link_type_id"))

    return (
        title.filter(col("production_year").is_between(1950, 2010))
        .join(mc, left_on="id", right_on="mc_movie_id")
        .join(ct, left_on="company_type_id", right_on="ct_id")
        .join(cn, left_on="company_id", right_on="cn_id")
        .join(mk, left_on="id", right_on="mk_movie_id")
        .join(k, left_on="keyword_id", right_on="k_id")
        .join(ml, left_on="id", right_on="ml_movie_id")
        .join(lt, left_on="link_type_id", right_on="lt_id")
        .join(mi, left_on="id", right_on="mi_movie_id")
        .select(
            col("company").min().alias("from_company"),
            col("link").min().alias("movie_link_type"),
            col("title").min().alias("non_polish_sequel_movie"),
        )
    )


def q12a_expression_impl(ctx: DataFrameContext) -> Any:
    """12a: Drama/horror US movies with high ratings (8 tables, double info_type join)."""
    company_name = ctx.get_table("company_name")
    company_type = ctx.get_table("company_type")
    info_type = ctx.get_table("info_type")
    movie_companies = ctx.get_table("movie_companies")
    movie_info = ctx.get_table("movie_info")
    movie_info_idx = ctx.get_table("movie_info_idx")
    title = ctx.get_table("title")
    col, lit = ctx.col, ctx.lit

    cn = company_name.filter(col("country_code") == lit("[us]")).select(
        col("id").alias("cn_id"), col("name").alias("company")
    )
    ct = company_type.filter(col("kind") == lit("production companies")).select(col("id").alias("ct_id"))
    # it1 for genres, it2 for rating - alias to distinguish
    it_genres = info_type.filter(col("info") == lit("genres")).select(col("id").alias("it1_id"))
    it_rating = info_type.filter(col("info") == lit("rating")).select(col("id").alias("it2_id"))
    mi = movie_info.filter(col("info").is_in(["Drama", "Horror", "Western", "Family"])).select(
        col("movie_id").alias("mi_movie_id"), col("info_type_id").alias("mi_info_type_id")
    )
    mi_idx = movie_info_idx.filter(col("info") > lit("8.0")).select(
        col("movie_id").alias("mi_idx_movie_id"),
        col("info_type_id").alias("mi_idx_info_type_id"),
        col("info").alias("rating"),
    )
    mc = movie_companies.select(col("movie_id").alias("mc_movie_id"), col("company_id"), col("company_type_id"))

    return (
        title.filter(col("production_year").is_between(2005, 2008))
        .join(mi, left_on="id", right_on="mi_movie_id")
        .join(it_genres, left_on="mi_info_type_id", right_on="it1_id")
        .join(mi_idx, left_on="id", right_on="mi_idx_movie_id")
        .join(it_rating, left_on="mi_idx_info_type_id", right_on="it2_id")
        .join(mc, left_on="id", right_on="mc_movie_id")
        .join(ct, left_on="company_type_id", right_on="ct_id")
        .join(cn, left_on="company_id", right_on="cn_id")
        .select(
            col("company").min().alias("movie_company"),
            col("rating").min().alias("rating"),
            col("title").min().alias("drama_horror_movie"),
        )
    )


# ===========================================================================
# Pandas Family (Pandas, Modin, cuDF, Dask)
#
# Translation pattern: pd.merge(left, right, ...) chained sequentially.
# Use descriptive variable names for intermediate merged DataFrames.
# ===========================================================================


def q1a_pandas_impl(ctx: DataFrameContext) -> Any:
    """1a: Production companies with top 250 rank (pandas)."""
    company_type = ctx.get_table("company_type")
    info_type = ctx.get_table("info_type")
    movie_companies = ctx.get_table("movie_companies")
    movie_info_idx = ctx.get_table("movie_info_idx")
    title = ctx.get_table("title")

    ct = company_type[company_type["kind"] == "production companies"][["id"]].rename(columns={"id": "ct_id"})
    it = info_type[info_type["info"] == "top 250 rank"][["id"]].rename(columns={"id": "it_id"})
    mc = movie_companies[
        (~movie_companies["note"].str.contains("as Metro-Goldwyn-Mayer Pictures", na=False))
        & (
            movie_companies["note"].str.contains("co-production", na=False)
            | movie_companies["note"].str.contains("presents", na=False)
        )
    ][["movie_id", "company_type_id", "note"]].rename(columns={"note": "mc_note"})

    merged = (
        title.merge(mc, left_on="id", right_on="movie_id", how="inner")
        .merge(ct, left_on="company_type_id", right_on="ct_id", how="inner")
        .merge(movie_info_idx, left_on="id", right_on="movie_id", how="inner")
        .merge(it, left_on="info_type_id", right_on="it_id", how="inner")
    )
    return pd.DataFrame(
        [
            {
                "production_note": merged["mc_note"].min() if len(merged) else None,
                "movie_title": merged["title"].min() if len(merged) else None,
                "movie_year": merged["production_year"].min() if len(merged) else None,
            }
        ]
    )


def q1b_pandas_impl(ctx: DataFrameContext) -> Any:
    """1b: Production companies with bottom 10 rank (pandas)."""
    company_type = ctx.get_table("company_type")
    info_type = ctx.get_table("info_type")
    movie_companies = ctx.get_table("movie_companies")
    movie_info_idx = ctx.get_table("movie_info_idx")
    title = ctx.get_table("title")

    ct = company_type[company_type["kind"] == "production companies"][["id"]].rename(columns={"id": "ct_id"})
    it = info_type[info_type["info"] == "bottom 10 rank"][["id"]].rename(columns={"id": "it_id"})
    mc = movie_companies[
        (~movie_companies["note"].str.contains("as Metro-Goldwyn-Mayer Pictures", na=False))
        & (
            movie_companies["note"].str.contains("co-production", na=False)
            | movie_companies["note"].str.contains("presents", na=False)
        )
    ][["movie_id", "company_type_id", "note"]].rename(columns={"note": "mc_note"})

    merged = (
        title.merge(mc, left_on="id", right_on="movie_id", how="inner")
        .merge(ct, left_on="company_type_id", right_on="ct_id", how="inner")
        .merge(movie_info_idx, left_on="id", right_on="movie_id", how="inner")
        .merge(it, left_on="info_type_id", right_on="it_id", how="inner")
    )
    return pd.DataFrame(
        [
            {
                "production_note": merged["mc_note"].min() if len(merged) else None,
                "movie_title": merged["title"].min() if len(merged) else None,
                "movie_year": merged["production_year"].min() if len(merged) else None,
            }
        ]
    )


def q2a_pandas_impl(ctx: DataFrameContext) -> Any:
    """2a: German company keyword movies (pandas)."""
    company_name = ctx.get_table("company_name")
    keyword = ctx.get_table("keyword")
    movie_companies = ctx.get_table("movie_companies")
    movie_keyword = ctx.get_table("movie_keyword")
    title = ctx.get_table("title")

    cn = company_name[company_name["country_code"] == "[de]"][["id"]].rename(columns={"id": "cn_id"})
    k = keyword[keyword["keyword"] == "character-name-in-title"][["id"]].rename(columns={"id": "k_id"})

    merged = (
        title.merge(movie_companies[["movie_id", "company_id"]], left_on="id", right_on="movie_id", how="inner")
        .merge(cn, left_on="company_id", right_on="cn_id", how="inner")
        .merge(movie_keyword[["movie_id", "keyword_id"]], left_on="id", right_on="movie_id", how="inner")
        .merge(k, left_on="keyword_id", right_on="k_id", how="inner")
    )
    return pd.DataFrame([{"movie_title": merged["title"].min() if len(merged) else None}])


def q3a_pandas_impl(ctx: DataFrameContext) -> Any:
    """3a: Sequel Scandinavian/German movies (pandas)."""
    keyword = ctx.get_table("keyword")
    movie_info = ctx.get_table("movie_info")
    movie_keyword = ctx.get_table("movie_keyword")
    title = ctx.get_table("title")

    k = keyword[keyword["keyword"].str.contains("sequel", na=False)][["id"]].rename(columns={"id": "k_id"})
    mi = movie_info[
        movie_info["info"].isin(
            ["Sweden", "Norway", "Germany", "Denmark", "Swedish", "Denish", "Norwegian", "German", "USA", "American"]
        )
    ][["movie_id"]].rename(columns={"movie_id": "mi_movie_id"})

    merged = (
        title[title["production_year"] > 1990]
        .merge(mi, left_on="id", right_on="mi_movie_id", how="inner")
        .merge(movie_keyword[["movie_id", "keyword_id"]], left_on="id", right_on="movie_id", how="inner")
        .merge(k, left_on="keyword_id", right_on="k_id", how="inner")
    )
    return pd.DataFrame([{"movie_title": merged["title"].min() if len(merged) else None}])


def q4a_pandas_impl(ctx: DataFrameContext) -> Any:
    """4a: Sequel movies with high rating (pandas)."""
    info_type = ctx.get_table("info_type")
    keyword = ctx.get_table("keyword")
    movie_info_idx = ctx.get_table("movie_info_idx")
    movie_keyword = ctx.get_table("movie_keyword")
    title = ctx.get_table("title")

    it = info_type[info_type["info"] == "rating"][["id"]].rename(columns={"id": "it_id"})
    k = keyword[keyword["keyword"].str.contains("sequel", na=False)][["id"]].rename(columns={"id": "k_id"})
    mi_idx = movie_info_idx[movie_info_idx["info"] > "2.0"][["movie_id", "info_type_id", "info"]].rename(
        columns={"info": "rating"}
    )

    merged = (
        title[title["production_year"] > 1990]
        .merge(mi_idx, left_on="id", right_on="movie_id", how="inner")
        .merge(it, left_on="info_type_id", right_on="it_id", how="inner")
        .merge(movie_keyword[["movie_id", "keyword_id"]], left_on="id", right_on="movie_id", how="inner")
        .merge(k, left_on="keyword_id", right_on="k_id", how="inner")
    )
    return pd.DataFrame(
        [
            {
                "rating": merged["rating"].min() if len(merged) else None,
                "movie_title": merged["title"].min() if len(merged) else None,
            }
        ]
    )


def q5a_pandas_impl(ctx: DataFrameContext) -> Any:
    """5a: European theatrical movies (pandas)."""
    company_type = ctx.get_table("company_type")
    info_type = ctx.get_table("info_type")
    movie_companies = ctx.get_table("movie_companies")
    movie_info = ctx.get_table("movie_info")
    title = ctx.get_table("title")

    ct = company_type[company_type["kind"] == "production companies"][["id"]].rename(columns={"id": "ct_id"})
    mc = (
        movie_companies[
            movie_companies["note"].str.contains("theatrical", na=False)
            & movie_companies["note"].str.contains("France", na=False)
        ][["movie_id", "company_type_id", "info_type_id"]].rename(columns={"movie_id": "mc_movie_id"})
        if "info_type_id" in movie_companies.columns
        else movie_companies[
            movie_companies["note"].str.contains("theatrical", na=False)
            & movie_companies["note"].str.contains("France", na=False)
        ][["movie_id", "company_type_id"]].rename(columns={"movie_id": "mc_movie_id"})
    )
    mi = movie_info[
        movie_info["info"].isin(["Sweden", "Norway", "Germany", "Denmark", "Swedish", "Denish", "Norwegian", "German"])
    ][["movie_id", "info_type_id"]].rename(columns={"movie_id": "mi_movie_id"})

    it = info_type[info_type["info"] == "countries"][["id"]].rename(columns={"id": "it_id"})

    merged = (
        title[title["production_year"] > 2005]
        .merge(mi, left_on="id", right_on="mi_movie_id", how="inner")
        .merge(it, left_on="info_type_id", right_on="it_id", how="inner")
        .merge(mc, left_on="id", right_on="mc_movie_id", how="inner")
        .merge(ct, left_on="company_type_id", right_on="ct_id", how="inner")
    )
    return pd.DataFrame([{"typical_european_movie": merged["title"].min() if len(merged) else None}])


def q6a_pandas_impl(ctx: DataFrameContext) -> Any:
    """6a: Superhero movies with Robert Downey Jr. (pandas)."""
    cast_info = ctx.get_table("cast_info")
    keyword = ctx.get_table("keyword")
    movie_keyword = ctx.get_table("movie_keyword")
    name = ctx.get_table("name")
    title = ctx.get_table("title")

    k = keyword[
        keyword["keyword"].isin(
            ["superhero", "sequel", "second-part", "marvel-comics", "based-on-comic", "tv-special", "fight", "violence"]
        )
    ][["id", "keyword"]].rename(columns={"id": "k_id"})
    n = name[name["name"].str.contains("Downey", na=False) & name["name"].str.contains("Robert", na=False)][
        ["id", "name"]
    ].rename(columns={"id": "n_id", "name": "actor_name"})

    merged = (
        title[title["production_year"] > 2000]
        .merge(movie_keyword[["movie_id", "keyword_id"]], left_on="id", right_on="movie_id", how="inner")
        .merge(k, left_on="keyword_id", right_on="k_id", how="inner")
        .merge(cast_info[["movie_id", "person_id"]], left_on="id", right_on="movie_id", how="inner")
        .merge(n, left_on="person_id", right_on="n_id", how="inner")
    )
    return pd.DataFrame(
        [
            {
                "movie_keyword": merged["keyword"].min() if len(merged) else None,
                "actor_name": merged["actor_name"].min() if len(merged) else None,
                "hero_movie": merged["title"].min() if len(merged) else None,
            }
        ]
    )


def q7a_pandas_impl(ctx: DataFrameContext) -> Any:
    """7a: Biography movies (8 tables, pandas)."""
    aka_name = ctx.get_table("aka_name")
    cast_info = ctx.get_table("cast_info")
    info_type = ctx.get_table("info_type")
    link_type = ctx.get_table("link_type")
    movie_link = ctx.get_table("movie_link")
    name = ctx.get_table("name")
    person_info = ctx.get_table("person_info")
    title = ctx.get_table("title")

    it = info_type[info_type["info"] == "mini biography"][["id"]].rename(columns={"id": "it_id"})
    lt = link_type[link_type["link"] == "features"][["id", "link"]].rename(columns={"id": "lt_id"})
    n = name[name["name_pcode_cf"].str.startswith("D", na=False) & (name["gender"] == "m")][["id", "name"]].rename(
        columns={"id": "n_id", "name": "person_name"}
    )
    pi = person_info[person_info["note"] == "Volker Boehm"][["person_id", "info_type_id"]].rename(
        columns={"person_id": "pi_person_id"}
    )
    an = aka_name[aka_name["name"].str.contains("a", na=False)][["person_id"]].rename(
        columns={"person_id": "an_person_id"}
    )

    merged = (
        title[title["production_year"].between(1980, 1995)]
        .merge(cast_info[["person_id", "movie_id"]], left_on="id", right_on="movie_id", how="inner")
        .merge(n, left_on="person_id", right_on="n_id", how="inner")
        .merge(pi, left_on="person_id", right_on="pi_person_id", how="inner")
        .merge(it, left_on="info_type_id", right_on="it_id", how="inner")
        .merge(an, left_on="person_id", right_on="an_person_id", how="inner")
        .merge(movie_link[["linked_movie_id", "link_type_id"]], left_on="id", right_on="linked_movie_id", how="inner")
        .merge(lt, left_on="link_type_id", right_on="lt_id", how="inner")
    )
    return pd.DataFrame(
        [
            {
                "of_person": merged["person_name"].min() if len(merged) else None,
                "biography_movie": merged["title"].min() if len(merged) else None,
            }
        ]
    )


def q8a_pandas_impl(ctx: DataFrameContext) -> Any:
    """8a: Japanese dubbed movies (7 tables, pandas)."""
    aka_name = ctx.get_table("aka_name")
    cast_info = ctx.get_table("cast_info")
    company_name = ctx.get_table("company_name")
    movie_companies = ctx.get_table("movie_companies")
    name = ctx.get_table("name")
    role_type = ctx.get_table("role_type")
    title = ctx.get_table("title")

    cn = company_name[company_name["country_code"] == "[jp]"][["id"]].rename(columns={"id": "cn_id"})
    rt = role_type[role_type["role"] == "actress"][["id"]].rename(columns={"id": "rt_id"})
    n1 = name[name["name"].str.contains("Yo", na=False) & (~name["name"].str.contains("Yu", na=False))][["id"]].rename(
        columns={"id": "n1_id"}
    )
    ci = cast_info[cast_info["note"] == "(voice: Japanese version)"][["person_id", "movie_id", "role_id"]]
    mc = movie_companies[
        movie_companies["note"].str.contains("Japan", na=False)
        & (~movie_companies["note"].str.contains("USA", na=False))
    ][["movie_id", "company_id"]].rename(columns={"movie_id": "mc_movie_id"})

    merged_title_mc = title.merge(mc, left_on="id", right_on="mc_movie_id", how="inner")
    merged_cn = merged_title_mc.merge(cn, left_on="company_id", right_on="cn_id", how="inner")
    merged_ci = merged_cn.merge(ci, left_on="id", right_on="movie_id", how="inner")
    merged_n1 = merged_ci.merge(n1, left_on="person_id", right_on="n1_id", how="inner")
    merged_rt = merged_n1.merge(rt, left_on="role_id", right_on="rt_id", how="inner")
    merged = merged_rt.merge(
        aka_name[["person_id", "name"]].rename(columns={"name": "aka_name"}), on="person_id", how="inner"
    )

    return pd.DataFrame(
        [
            {
                "actress_pseudonym": merged["aka_name"].min() if len(merged) else None,
                "japanese_movie_dubbed": merged["title"].min() if len(merged) else None,
            }
        ]
    )


def q9a_pandas_impl(ctx: DataFrameContext) -> Any:
    """9a: American voice actress movies (8 tables, pandas)."""
    aka_name = ctx.get_table("aka_name")
    char_name = ctx.get_table("char_name")
    cast_info = ctx.get_table("cast_info")
    company_name = ctx.get_table("company_name")
    movie_companies = ctx.get_table("movie_companies")
    name = ctx.get_table("name")
    role_type = ctx.get_table("role_type")
    title = ctx.get_table("title")

    cn = company_name[company_name["country_code"] == "[us]"][["id"]].rename(columns={"id": "cn_id"})
    rt = role_type[role_type["role"] == "actress"][["id"]].rename(columns={"id": "rt_id"})
    n = name[(name["gender"] == "f") & name["name"].str.contains("An", na=False)][["id", "name"]].rename(
        columns={"id": "n_id", "name": "actress_name"}
    )
    ci = cast_info[
        cast_info["note"].isin(
            ["(voice)", "(voice: Japanese version)", "(voice) (uncredited)", "(voice: English version)"]
        )
    ][["person_id", "movie_id", "role_id", "person_role_id"]]
    mc = movie_companies[
        movie_companies["note"].str.contains("USA", na=False)
        & (~movie_companies["note"].str.contains("worldwide", na=False))
    ][["movie_id", "company_id"]].rename(columns={"movie_id": "mc_movie_id"})

    merged = (
        title[title["production_year"].between(2005, 2015)]
        .merge(ci, left_on="id", right_on="movie_id", how="inner")
        .merge(mc, left_on="id", right_on="mc_movie_id", how="inner")
        .merge(cn, left_on="company_id", right_on="cn_id", how="inner")
        .merge(n, left_on="person_id", right_on="n_id", how="inner")
        .merge(rt, left_on="role_id", right_on="rt_id", how="inner")
        .merge(
            char_name[["id", "name"]].rename(columns={"id": "chn_id", "name": "char_name_val"}),
            left_on="person_role_id",
            right_on="chn_id",
            how="inner",
        )
        .merge(aka_name[["person_id", "name"]].rename(columns={"name": "alt_name"}), on="person_id", how="inner")
    )
    return pd.DataFrame(
        [
            {
                "alternative_name": merged["alt_name"].min() if len(merged) else None,
                "voiced_character_name": merged["char_name_val"].min() if len(merged) else None,
                "voicing_actress": merged["actress_name"].min() if len(merged) else None,
                "american_movie": merged["title"].min() if len(merged) else None,
            }
        ]
    )


def q10a_pandas_impl(ctx: DataFrameContext) -> Any:
    """10a: American producer movies (7 tables, pandas)."""
    char_name = ctx.get_table("char_name")
    cast_info = ctx.get_table("cast_info")
    company_name = ctx.get_table("company_name")
    company_type = ctx.get_table("company_type")
    movie_companies = ctx.get_table("movie_companies")
    role_type = ctx.get_table("role_type")
    title = ctx.get_table("title")

    cn = company_name[company_name["country_code"] == "[us]"][["id"]].rename(columns={"id": "cn_id"})
    rt = role_type[role_type["role"] == "producer"][["id"]].rename(columns={"id": "rt_id"})
    ci = cast_info[cast_info["note"].str.contains("producer", na=False)][
        ["person_id", "movie_id", "role_id", "person_role_id"]
    ]

    merged = (
        title[title["production_year"] > 1990]
        .merge(ci, left_on="id", right_on="movie_id", how="inner")
        .merge(rt, left_on="role_id", right_on="rt_id", how="inner")
        .merge(
            char_name[["id", "name"]].rename(columns={"id": "chn_id", "name": "character"}),
            left_on="person_role_id",
            right_on="chn_id",
            how="inner",
        )
        .merge(
            movie_companies[["movie_id", "company_id", "company_type_id"]],
            left_on="id",
            right_on="movie_id",
            how="inner",
        )
        .merge(
            company_type[["id"]].rename(columns={"id": "ct_id"}),
            left_on="company_type_id",
            right_on="ct_id",
            how="inner",
        )
        .merge(cn, left_on="company_id", right_on="cn_id", how="inner")
    )
    return pd.DataFrame(
        [
            {
                "character": merged["character"].min() if len(merged) else None,
                "movie_with_american_producer": merged["title"].min() if len(merged) else None,
            }
        ]
    )


def q11a_pandas_impl(ctx: DataFrameContext) -> Any:
    """11a: Non-Polish sequel movies with follow links (9 tables, pandas)."""
    company_name = ctx.get_table("company_name")
    company_type = ctx.get_table("company_type")
    keyword = ctx.get_table("keyword")
    link_type = ctx.get_table("link_type")
    movie_companies = ctx.get_table("movie_companies")
    movie_info = ctx.get_table("movie_info")
    movie_keyword = ctx.get_table("movie_keyword")
    movie_link = ctx.get_table("movie_link")
    title = ctx.get_table("title")

    cn = company_name[
        (company_name["country_code"] != "[pl]")
        & (company_name["name"].str.contains("Film", na=False) | company_name["name"].str.contains("Warner", na=False))
    ][["id", "name"]].rename(columns={"id": "cn_id", "name": "company"})
    ct = company_type[company_type["kind"] == "production companies"][["id"]].rename(columns={"id": "ct_id"})
    k = keyword[keyword["keyword"] == "sequel"][["id"]].rename(columns={"id": "k_id"})
    lt = link_type[link_type["link"].str.contains("follow", na=False)][["id", "link"]].rename(columns={"id": "lt_id"})
    mc = movie_companies[movie_companies["note"].isna()][["movie_id", "company_id", "company_type_id"]].rename(
        columns={"movie_id": "mc_movie_id"}
    )
    mi = movie_info[
        movie_info["info"].isin(
            ["Sweden", "Norway", "Germany", "Denmark", "Swedish", "Denish", "Norwegian", "German", "English"]
        )
    ][["movie_id"]].rename(columns={"movie_id": "mi_movie_id"})

    merged = (
        title[title["production_year"].between(1950, 2010)]
        .merge(mc, left_on="id", right_on="mc_movie_id", how="inner")
        .merge(ct, left_on="company_type_id", right_on="ct_id", how="inner")
        .merge(cn, left_on="company_id", right_on="cn_id", how="inner")
        .merge(movie_keyword[["movie_id", "keyword_id"]], left_on="id", right_on="movie_id", how="inner")
        .merge(k, left_on="keyword_id", right_on="k_id", how="inner")
        .merge(
            movie_link[["movie_id", "link_type_id"]].rename(columns={"movie_id": "ml_movie_id"}),
            left_on="id",
            right_on="ml_movie_id",
            how="inner",
        )
        .merge(lt, left_on="link_type_id", right_on="lt_id", how="inner")
        .merge(mi, left_on="id", right_on="mi_movie_id", how="inner")
    )
    return pd.DataFrame(
        [
            {
                "from_company": merged["company"].min() if len(merged) else None,
                "movie_link_type": merged["link"].min() if len(merged) else None,
                "non_polish_sequel_movie": merged["title"].min() if len(merged) else None,
            }
        ]
    )


def q12a_pandas_impl(ctx: DataFrameContext) -> Any:
    """12a: Drama/horror US movies with high ratings (8 tables, double info_type, pandas)."""
    company_name = ctx.get_table("company_name")
    company_type = ctx.get_table("company_type")
    info_type = ctx.get_table("info_type")
    movie_companies = ctx.get_table("movie_companies")
    movie_info = ctx.get_table("movie_info")
    movie_info_idx = ctx.get_table("movie_info_idx")
    title = ctx.get_table("title")

    cn = company_name[company_name["country_code"] == "[us]"][["id", "name"]].rename(
        columns={"id": "cn_id", "name": "company"}
    )
    ct = company_type[company_type["kind"] == "production companies"][["id"]].rename(columns={"id": "ct_id"})
    it_genres = info_type[info_type["info"] == "genres"][["id"]].rename(columns={"id": "it1_id"})
    it_rating = info_type[info_type["info"] == "rating"][["id"]].rename(columns={"id": "it2_id"})
    mi = movie_info[movie_info["info"].isin(["Drama", "Horror", "Western", "Family"])][
        ["movie_id", "info_type_id"]
    ].rename(columns={"movie_id": "mi_movie_id", "info_type_id": "mi_info_type_id"})
    mi_idx = movie_info_idx[movie_info_idx["info"] > "8.0"][["movie_id", "info_type_id", "info"]].rename(
        columns={"movie_id": "mi_idx_movie_id", "info_type_id": "mi_idx_info_type_id", "info": "rating"}
    )

    merged = (
        title[title["production_year"].between(2005, 2008)]
        .merge(mi, left_on="id", right_on="mi_movie_id", how="inner")
        .merge(it_genres, left_on="mi_info_type_id", right_on="it1_id", how="inner")
        .merge(mi_idx, left_on="id", right_on="mi_idx_movie_id", how="inner")
        .merge(it_rating, left_on="mi_idx_info_type_id", right_on="it2_id", how="inner")
        .merge(
            movie_companies[["movie_id", "company_id", "company_type_id"]],
            left_on="id",
            right_on="movie_id",
            how="inner",
        )
        .merge(ct, left_on="company_type_id", right_on="ct_id", how="inner")
        .merge(cn, left_on="company_id", right_on="cn_id", how="inner")
    )
    return pd.DataFrame(
        [
            {
                "movie_company": merged["company"].min() if len(merged) else None,
                "rating": merged["rating"].min() if len(merged) else None,
                "drama_horror_movie": merged["title"].min() if len(merged) else None,
            }
        ]
    )


# ===========================================================================
# Registry
# ===========================================================================

JOINORDER_DATAFRAME_QUERIES = QueryRegistry("JoinOrder DataFrame")

_QUERIES = [
    DataFrameQuery(
        query_id="1a",
        query_name="Production Companies Top 250",
        description="Production companies with top 250 ranked movies (5 tables)",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q1a_expression_impl,
        pandas_impl=q1a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="1b",
        query_name="Production Companies Bottom 10",
        description="Variant of 1a with bottom 10 rank predicate (5 tables)",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q1b_expression_impl,
        pandas_impl=q1b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="2a",
        query_name="German Company Character Name Movies",
        description="Movies from German companies with character-name-in-title keyword (5 tables)",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q2a_expression_impl,
        pandas_impl=q2a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="3a",
        query_name="Scandinavian/German Sequel Movies",
        description="Sequel movies from Scandinavian/German countries after 1990 (4 tables)",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q3a_expression_impl,
        pandas_impl=q3a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="4a",
        query_name="Sequel Movies with High Rating",
        description="Sequel movies with rating > 2.0 after 1990 (5 tables)",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q4a_expression_impl,
        pandas_impl=q4a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="5a",
        query_name="European Theatrical Movies",
        description="European theatrical movies from France production companies after 2005 (5 tables)",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q5a_expression_impl,
        pandas_impl=q5a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="6a",
        query_name="Superhero Movies with Robert Downey Jr.",
        description="Superhero/action movies featuring Robert Downey Jr. after 2000 (5 tables)",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q6a_expression_impl,
        pandas_impl=q6a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="7a",
        query_name="Biography Movies with Person Criteria",
        description="Biography movies with specific person criteria (8 tables)",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q7a_expression_impl,
        pandas_impl=q7a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="8a",
        query_name="Japanese Dubbed Movies",
        description="Japanese dubbed movies by specific actress criteria (7 tables)",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q8a_expression_impl,
        pandas_impl=q8a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="9a",
        query_name="American Voice Actress Movies",
        description="American voice actress movies (8 tables)",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q9a_expression_impl,
        pandas_impl=q9a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="10a",
        query_name="American Producer Movies",
        description="Movies with American producers after 1990 (7 tables)",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q10a_expression_impl,
        pandas_impl=q10a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="11a",
        query_name="Non-Polish Sequel Movies with Follow Links",
        description="Sequel movies from Film/Warner companies with follow links (9 tables)",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q11a_expression_impl,
        pandas_impl=q11a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="12a",
        query_name="Drama/Horror US Movies with High Ratings",
        description="US drama/horror movies with high ratings using double info_type join (8 tables)",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q12a_expression_impl,
        pandas_impl=q12a_pandas_impl,
    ),
]

for _query in _QUERIES:
    JOINORDER_DATAFRAME_QUERIES.register(_query)


def get_dataframe_queries() -> QueryRegistry:
    """Get the JoinOrder DataFrame query registry.

    Returns:
        QueryRegistry containing all 13 JoinOrder DataFrame queries
    """
    return JOINORDER_DATAFRAME_QUERIES
