"""Canonical JoinOrder Benchmark DataFrame queries for Expression and Pandas families.

Implements the 13 previously translated JoinOrder queries and registers
NotImplementedError stubs for the remaining canonical SQL query IDs.

The canonical JoinOrder Benchmark is based on "How Good Are Query Optimizers, Really?"
(VLDB 2015) and uses the 21-table IMDb 2013 schema. The key translation
challenge is converting implicit cross-joins (comma-separated FROM clauses
with WHERE join conditions) into explicit .join() chains.

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

IMPLEMENTED_DATAFRAME_QUERY_IDS = ["1a", "1b", "2a", "3a", "4a", "5a", "6a", "7a", "8a", "9a", "10a", "11a", "12a"]
UNTRANSLATED_DATAFRAME_QUERY_IDS = [
    "1c",
    "1d",
    "2b",
    "2c",
    "2d",
    "3b",
    "3c",
    "4b",
    "4c",
    "5b",
    "5c",
    "6b",
    "6c",
    "6d",
    "6e",
    "6f",
    "7b",
    "7c",
    "8b",
    "8c",
    "8d",
    "9b",
    "9c",
    "9d",
    "10b",
    "10c",
    "11b",
    "11c",
    "11d",
    "12b",
    "12c",
    "13a",
    "13b",
    "13c",
    "13d",
    "14a",
    "14b",
    "14c",
    "15a",
    "15b",
    "15c",
    "15d",
    "16a",
    "16b",
    "16c",
    "16d",
    "17a",
    "17b",
    "17c",
    "17d",
    "17e",
    "17f",
    "18a",
    "18b",
    "18c",
    "19a",
    "19b",
    "19c",
    "19d",
    "20a",
    "20b",
    "20c",
    "21a",
    "21b",
    "21c",
    "22a",
    "22b",
    "22c",
    "22d",
    "23a",
    "23b",
    "23c",
    "24a",
    "24b",
    "25a",
    "25b",
    "25c",
    "26a",
    "26b",
    "26c",
    "27a",
    "27b",
    "27c",
    "28a",
    "28b",
    "28c",
    "29a",
    "29b",
    "29c",
    "30a",
    "30b",
    "30c",
    "31a",
    "31b",
    "31c",
    "32a",
    "32b",
    "33a",
    "33b",
    "33c",
]
_TRACK2_TODO = "_project/TODO/main/planning/track2-joinorder-dataframe-coverage.yaml"


def _raise_untranslated_dataframe_query(query_id: str) -> None:
    raise NotImplementedError(
        f"DataFrame translation for query {query_id} not yet available. Track-2 TODO: {_TRACK2_TODO}"
    )


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


def q1c_expression_impl(ctx: DataFrameContext) -> Any:
    """1c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("1c")


def q1c_pandas_impl(ctx: DataFrameContext) -> Any:
    """1c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("1c")


def q1d_expression_impl(ctx: DataFrameContext) -> Any:
    """1d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("1d")


def q1d_pandas_impl(ctx: DataFrameContext) -> Any:
    """1d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("1d")


def q2b_expression_impl(ctx: DataFrameContext) -> Any:
    """2b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("2b")


def q2b_pandas_impl(ctx: DataFrameContext) -> Any:
    """2b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("2b")


def q2c_expression_impl(ctx: DataFrameContext) -> Any:
    """2c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("2c")


def q2c_pandas_impl(ctx: DataFrameContext) -> Any:
    """2c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("2c")


def q2d_expression_impl(ctx: DataFrameContext) -> Any:
    """2d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("2d")


def q2d_pandas_impl(ctx: DataFrameContext) -> Any:
    """2d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("2d")


def q3b_expression_impl(ctx: DataFrameContext) -> Any:
    """3b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("3b")


def q3b_pandas_impl(ctx: DataFrameContext) -> Any:
    """3b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("3b")


def q3c_expression_impl(ctx: DataFrameContext) -> Any:
    """3c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("3c")


def q3c_pandas_impl(ctx: DataFrameContext) -> Any:
    """3c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("3c")


def q4b_expression_impl(ctx: DataFrameContext) -> Any:
    """4b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("4b")


def q4b_pandas_impl(ctx: DataFrameContext) -> Any:
    """4b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("4b")


def q4c_expression_impl(ctx: DataFrameContext) -> Any:
    """4c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("4c")


def q4c_pandas_impl(ctx: DataFrameContext) -> Any:
    """4c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("4c")


def q5b_expression_impl(ctx: DataFrameContext) -> Any:
    """5b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("5b")


def q5b_pandas_impl(ctx: DataFrameContext) -> Any:
    """5b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("5b")


def q5c_expression_impl(ctx: DataFrameContext) -> Any:
    """5c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("5c")


def q5c_pandas_impl(ctx: DataFrameContext) -> Any:
    """5c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("5c")


def q6b_expression_impl(ctx: DataFrameContext) -> Any:
    """6b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("6b")


def q6b_pandas_impl(ctx: DataFrameContext) -> Any:
    """6b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("6b")


def q6c_expression_impl(ctx: DataFrameContext) -> Any:
    """6c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("6c")


def q6c_pandas_impl(ctx: DataFrameContext) -> Any:
    """6c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("6c")


def q6d_expression_impl(ctx: DataFrameContext) -> Any:
    """6d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("6d")


def q6d_pandas_impl(ctx: DataFrameContext) -> Any:
    """6d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("6d")


def q6e_expression_impl(ctx: DataFrameContext) -> Any:
    """6e: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("6e")


def q6e_pandas_impl(ctx: DataFrameContext) -> Any:
    """6e: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("6e")


def q6f_expression_impl(ctx: DataFrameContext) -> Any:
    """6f: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("6f")


def q6f_pandas_impl(ctx: DataFrameContext) -> Any:
    """6f: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("6f")


def q7b_expression_impl(ctx: DataFrameContext) -> Any:
    """7b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("7b")


def q7b_pandas_impl(ctx: DataFrameContext) -> Any:
    """7b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("7b")


def q7c_expression_impl(ctx: DataFrameContext) -> Any:
    """7c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("7c")


def q7c_pandas_impl(ctx: DataFrameContext) -> Any:
    """7c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("7c")


def q8b_expression_impl(ctx: DataFrameContext) -> Any:
    """8b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("8b")


def q8b_pandas_impl(ctx: DataFrameContext) -> Any:
    """8b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("8b")


def q8c_expression_impl(ctx: DataFrameContext) -> Any:
    """8c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("8c")


def q8c_pandas_impl(ctx: DataFrameContext) -> Any:
    """8c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("8c")


def q8d_expression_impl(ctx: DataFrameContext) -> Any:
    """8d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("8d")


def q8d_pandas_impl(ctx: DataFrameContext) -> Any:
    """8d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("8d")


def q9b_expression_impl(ctx: DataFrameContext) -> Any:
    """9b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("9b")


def q9b_pandas_impl(ctx: DataFrameContext) -> Any:
    """9b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("9b")


def q9c_expression_impl(ctx: DataFrameContext) -> Any:
    """9c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("9c")


def q9c_pandas_impl(ctx: DataFrameContext) -> Any:
    """9c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("9c")


def q9d_expression_impl(ctx: DataFrameContext) -> Any:
    """9d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("9d")


def q9d_pandas_impl(ctx: DataFrameContext) -> Any:
    """9d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("9d")


def q10b_expression_impl(ctx: DataFrameContext) -> Any:
    """10b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("10b")


def q10b_pandas_impl(ctx: DataFrameContext) -> Any:
    """10b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("10b")


def q10c_expression_impl(ctx: DataFrameContext) -> Any:
    """10c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("10c")


def q10c_pandas_impl(ctx: DataFrameContext) -> Any:
    """10c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("10c")


def q11b_expression_impl(ctx: DataFrameContext) -> Any:
    """11b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("11b")


def q11b_pandas_impl(ctx: DataFrameContext) -> Any:
    """11b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("11b")


def q11c_expression_impl(ctx: DataFrameContext) -> Any:
    """11c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("11c")


def q11c_pandas_impl(ctx: DataFrameContext) -> Any:
    """11c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("11c")


def q11d_expression_impl(ctx: DataFrameContext) -> Any:
    """11d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("11d")


def q11d_pandas_impl(ctx: DataFrameContext) -> Any:
    """11d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("11d")


def q12b_expression_impl(ctx: DataFrameContext) -> Any:
    """12b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("12b")


def q12b_pandas_impl(ctx: DataFrameContext) -> Any:
    """12b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("12b")


def q12c_expression_impl(ctx: DataFrameContext) -> Any:
    """12c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("12c")


def q12c_pandas_impl(ctx: DataFrameContext) -> Any:
    """12c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("12c")


def q13a_expression_impl(ctx: DataFrameContext) -> Any:
    """13a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("13a")


def q13a_pandas_impl(ctx: DataFrameContext) -> Any:
    """13a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("13a")


def q13b_expression_impl(ctx: DataFrameContext) -> Any:
    """13b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("13b")


def q13b_pandas_impl(ctx: DataFrameContext) -> Any:
    """13b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("13b")


def q13c_expression_impl(ctx: DataFrameContext) -> Any:
    """13c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("13c")


def q13c_pandas_impl(ctx: DataFrameContext) -> Any:
    """13c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("13c")


def q13d_expression_impl(ctx: DataFrameContext) -> Any:
    """13d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("13d")


def q13d_pandas_impl(ctx: DataFrameContext) -> Any:
    """13d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("13d")


def q14a_expression_impl(ctx: DataFrameContext) -> Any:
    """14a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("14a")


def q14a_pandas_impl(ctx: DataFrameContext) -> Any:
    """14a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("14a")


def q14b_expression_impl(ctx: DataFrameContext) -> Any:
    """14b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("14b")


def q14b_pandas_impl(ctx: DataFrameContext) -> Any:
    """14b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("14b")


def q14c_expression_impl(ctx: DataFrameContext) -> Any:
    """14c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("14c")


def q14c_pandas_impl(ctx: DataFrameContext) -> Any:
    """14c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("14c")


def q15a_expression_impl(ctx: DataFrameContext) -> Any:
    """15a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("15a")


def q15a_pandas_impl(ctx: DataFrameContext) -> Any:
    """15a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("15a")


def q15b_expression_impl(ctx: DataFrameContext) -> Any:
    """15b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("15b")


def q15b_pandas_impl(ctx: DataFrameContext) -> Any:
    """15b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("15b")


def q15c_expression_impl(ctx: DataFrameContext) -> Any:
    """15c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("15c")


def q15c_pandas_impl(ctx: DataFrameContext) -> Any:
    """15c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("15c")


def q15d_expression_impl(ctx: DataFrameContext) -> Any:
    """15d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("15d")


def q15d_pandas_impl(ctx: DataFrameContext) -> Any:
    """15d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("15d")


def q16a_expression_impl(ctx: DataFrameContext) -> Any:
    """16a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("16a")


def q16a_pandas_impl(ctx: DataFrameContext) -> Any:
    """16a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("16a")


def q16b_expression_impl(ctx: DataFrameContext) -> Any:
    """16b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("16b")


def q16b_pandas_impl(ctx: DataFrameContext) -> Any:
    """16b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("16b")


def q16c_expression_impl(ctx: DataFrameContext) -> Any:
    """16c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("16c")


def q16c_pandas_impl(ctx: DataFrameContext) -> Any:
    """16c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("16c")


def q16d_expression_impl(ctx: DataFrameContext) -> Any:
    """16d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("16d")


def q16d_pandas_impl(ctx: DataFrameContext) -> Any:
    """16d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("16d")


def q17a_expression_impl(ctx: DataFrameContext) -> Any:
    """17a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("17a")


def q17a_pandas_impl(ctx: DataFrameContext) -> Any:
    """17a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("17a")


def q17b_expression_impl(ctx: DataFrameContext) -> Any:
    """17b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("17b")


def q17b_pandas_impl(ctx: DataFrameContext) -> Any:
    """17b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("17b")


def q17c_expression_impl(ctx: DataFrameContext) -> Any:
    """17c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("17c")


def q17c_pandas_impl(ctx: DataFrameContext) -> Any:
    """17c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("17c")


def q17d_expression_impl(ctx: DataFrameContext) -> Any:
    """17d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("17d")


def q17d_pandas_impl(ctx: DataFrameContext) -> Any:
    """17d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("17d")


def q17e_expression_impl(ctx: DataFrameContext) -> Any:
    """17e: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("17e")


def q17e_pandas_impl(ctx: DataFrameContext) -> Any:
    """17e: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("17e")


def q17f_expression_impl(ctx: DataFrameContext) -> Any:
    """17f: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("17f")


def q17f_pandas_impl(ctx: DataFrameContext) -> Any:
    """17f: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("17f")


def q18a_expression_impl(ctx: DataFrameContext) -> Any:
    """18a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("18a")


def q18a_pandas_impl(ctx: DataFrameContext) -> Any:
    """18a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("18a")


def q18b_expression_impl(ctx: DataFrameContext) -> Any:
    """18b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("18b")


def q18b_pandas_impl(ctx: DataFrameContext) -> Any:
    """18b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("18b")


def q18c_expression_impl(ctx: DataFrameContext) -> Any:
    """18c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("18c")


def q18c_pandas_impl(ctx: DataFrameContext) -> Any:
    """18c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("18c")


def q19a_expression_impl(ctx: DataFrameContext) -> Any:
    """19a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("19a")


def q19a_pandas_impl(ctx: DataFrameContext) -> Any:
    """19a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("19a")


def q19b_expression_impl(ctx: DataFrameContext) -> Any:
    """19b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("19b")


def q19b_pandas_impl(ctx: DataFrameContext) -> Any:
    """19b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("19b")


def q19c_expression_impl(ctx: DataFrameContext) -> Any:
    """19c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("19c")


def q19c_pandas_impl(ctx: DataFrameContext) -> Any:
    """19c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("19c")


def q19d_expression_impl(ctx: DataFrameContext) -> Any:
    """19d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("19d")


def q19d_pandas_impl(ctx: DataFrameContext) -> Any:
    """19d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("19d")


def q20a_expression_impl(ctx: DataFrameContext) -> Any:
    """20a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("20a")


def q20a_pandas_impl(ctx: DataFrameContext) -> Any:
    """20a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("20a")


def q20b_expression_impl(ctx: DataFrameContext) -> Any:
    """20b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("20b")


def q20b_pandas_impl(ctx: DataFrameContext) -> Any:
    """20b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("20b")


def q20c_expression_impl(ctx: DataFrameContext) -> Any:
    """20c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("20c")


def q20c_pandas_impl(ctx: DataFrameContext) -> Any:
    """20c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("20c")


def q21a_expression_impl(ctx: DataFrameContext) -> Any:
    """21a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("21a")


def q21a_pandas_impl(ctx: DataFrameContext) -> Any:
    """21a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("21a")


def q21b_expression_impl(ctx: DataFrameContext) -> Any:
    """21b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("21b")


def q21b_pandas_impl(ctx: DataFrameContext) -> Any:
    """21b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("21b")


def q21c_expression_impl(ctx: DataFrameContext) -> Any:
    """21c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("21c")


def q21c_pandas_impl(ctx: DataFrameContext) -> Any:
    """21c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("21c")


def q22a_expression_impl(ctx: DataFrameContext) -> Any:
    """22a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("22a")


def q22a_pandas_impl(ctx: DataFrameContext) -> Any:
    """22a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("22a")


def q22b_expression_impl(ctx: DataFrameContext) -> Any:
    """22b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("22b")


def q22b_pandas_impl(ctx: DataFrameContext) -> Any:
    """22b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("22b")


def q22c_expression_impl(ctx: DataFrameContext) -> Any:
    """22c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("22c")


def q22c_pandas_impl(ctx: DataFrameContext) -> Any:
    """22c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("22c")


def q22d_expression_impl(ctx: DataFrameContext) -> Any:
    """22d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("22d")


def q22d_pandas_impl(ctx: DataFrameContext) -> Any:
    """22d: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("22d")


def q23a_expression_impl(ctx: DataFrameContext) -> Any:
    """23a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("23a")


def q23a_pandas_impl(ctx: DataFrameContext) -> Any:
    """23a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("23a")


def q23b_expression_impl(ctx: DataFrameContext) -> Any:
    """23b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("23b")


def q23b_pandas_impl(ctx: DataFrameContext) -> Any:
    """23b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("23b")


def q23c_expression_impl(ctx: DataFrameContext) -> Any:
    """23c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("23c")


def q23c_pandas_impl(ctx: DataFrameContext) -> Any:
    """23c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("23c")


def q24a_expression_impl(ctx: DataFrameContext) -> Any:
    """24a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("24a")


def q24a_pandas_impl(ctx: DataFrameContext) -> Any:
    """24a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("24a")


def q24b_expression_impl(ctx: DataFrameContext) -> Any:
    """24b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("24b")


def q24b_pandas_impl(ctx: DataFrameContext) -> Any:
    """24b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("24b")


def q25a_expression_impl(ctx: DataFrameContext) -> Any:
    """25a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("25a")


def q25a_pandas_impl(ctx: DataFrameContext) -> Any:
    """25a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("25a")


def q25b_expression_impl(ctx: DataFrameContext) -> Any:
    """25b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("25b")


def q25b_pandas_impl(ctx: DataFrameContext) -> Any:
    """25b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("25b")


def q25c_expression_impl(ctx: DataFrameContext) -> Any:
    """25c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("25c")


def q25c_pandas_impl(ctx: DataFrameContext) -> Any:
    """25c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("25c")


def q26a_expression_impl(ctx: DataFrameContext) -> Any:
    """26a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("26a")


def q26a_pandas_impl(ctx: DataFrameContext) -> Any:
    """26a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("26a")


def q26b_expression_impl(ctx: DataFrameContext) -> Any:
    """26b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("26b")


def q26b_pandas_impl(ctx: DataFrameContext) -> Any:
    """26b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("26b")


def q26c_expression_impl(ctx: DataFrameContext) -> Any:
    """26c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("26c")


def q26c_pandas_impl(ctx: DataFrameContext) -> Any:
    """26c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("26c")


def q27a_expression_impl(ctx: DataFrameContext) -> Any:
    """27a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("27a")


def q27a_pandas_impl(ctx: DataFrameContext) -> Any:
    """27a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("27a")


def q27b_expression_impl(ctx: DataFrameContext) -> Any:
    """27b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("27b")


def q27b_pandas_impl(ctx: DataFrameContext) -> Any:
    """27b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("27b")


def q27c_expression_impl(ctx: DataFrameContext) -> Any:
    """27c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("27c")


def q27c_pandas_impl(ctx: DataFrameContext) -> Any:
    """27c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("27c")


def q28a_expression_impl(ctx: DataFrameContext) -> Any:
    """28a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("28a")


def q28a_pandas_impl(ctx: DataFrameContext) -> Any:
    """28a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("28a")


def q28b_expression_impl(ctx: DataFrameContext) -> Any:
    """28b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("28b")


def q28b_pandas_impl(ctx: DataFrameContext) -> Any:
    """28b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("28b")


def q28c_expression_impl(ctx: DataFrameContext) -> Any:
    """28c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("28c")


def q28c_pandas_impl(ctx: DataFrameContext) -> Any:
    """28c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("28c")


def q29a_expression_impl(ctx: DataFrameContext) -> Any:
    """29a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("29a")


def q29a_pandas_impl(ctx: DataFrameContext) -> Any:
    """29a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("29a")


def q29b_expression_impl(ctx: DataFrameContext) -> Any:
    """29b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("29b")


def q29b_pandas_impl(ctx: DataFrameContext) -> Any:
    """29b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("29b")


def q29c_expression_impl(ctx: DataFrameContext) -> Any:
    """29c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("29c")


def q29c_pandas_impl(ctx: DataFrameContext) -> Any:
    """29c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("29c")


def q30a_expression_impl(ctx: DataFrameContext) -> Any:
    """30a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("30a")


def q30a_pandas_impl(ctx: DataFrameContext) -> Any:
    """30a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("30a")


def q30b_expression_impl(ctx: DataFrameContext) -> Any:
    """30b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("30b")


def q30b_pandas_impl(ctx: DataFrameContext) -> Any:
    """30b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("30b")


def q30c_expression_impl(ctx: DataFrameContext) -> Any:
    """30c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("30c")


def q30c_pandas_impl(ctx: DataFrameContext) -> Any:
    """30c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("30c")


def q31a_expression_impl(ctx: DataFrameContext) -> Any:
    """31a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("31a")


def q31a_pandas_impl(ctx: DataFrameContext) -> Any:
    """31a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("31a")


def q31b_expression_impl(ctx: DataFrameContext) -> Any:
    """31b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("31b")


def q31b_pandas_impl(ctx: DataFrameContext) -> Any:
    """31b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("31b")


def q31c_expression_impl(ctx: DataFrameContext) -> Any:
    """31c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("31c")


def q31c_pandas_impl(ctx: DataFrameContext) -> Any:
    """31c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("31c")


def q32a_expression_impl(ctx: DataFrameContext) -> Any:
    """32a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("32a")


def q32a_pandas_impl(ctx: DataFrameContext) -> Any:
    """32a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("32a")


def q32b_expression_impl(ctx: DataFrameContext) -> Any:
    """32b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("32b")


def q32b_pandas_impl(ctx: DataFrameContext) -> Any:
    """32b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("32b")


def q33a_expression_impl(ctx: DataFrameContext) -> Any:
    """33a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("33a")


def q33a_pandas_impl(ctx: DataFrameContext) -> Any:
    """33a: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("33a")


def q33b_expression_impl(ctx: DataFrameContext) -> Any:
    """33b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("33b")


def q33b_pandas_impl(ctx: DataFrameContext) -> Any:
    """33b: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("33b")


def q33c_expression_impl(ctx: DataFrameContext) -> Any:
    """33c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("33c")


def q33c_pandas_impl(ctx: DataFrameContext) -> Any:
    """33c: untranslated canonical JoinOrder query."""
    _raise_untranslated_dataframe_query("33c")


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
    DataFrameQuery(
        query_id="1c",
        query_name="Canonical JoinOrder 1c",
        description="Canonical JoinOrder SQL query 1c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q1c_expression_impl,
        pandas_impl=q1c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="1d",
        query_name="Canonical JoinOrder 1d",
        description="Canonical JoinOrder SQL query 1d; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q1d_expression_impl,
        pandas_impl=q1d_pandas_impl,
    ),
    DataFrameQuery(
        query_id="2b",
        query_name="Canonical JoinOrder 2b",
        description="Canonical JoinOrder SQL query 2b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q2b_expression_impl,
        pandas_impl=q2b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="2c",
        query_name="Canonical JoinOrder 2c",
        description="Canonical JoinOrder SQL query 2c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q2c_expression_impl,
        pandas_impl=q2c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="2d",
        query_name="Canonical JoinOrder 2d",
        description="Canonical JoinOrder SQL query 2d; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q2d_expression_impl,
        pandas_impl=q2d_pandas_impl,
    ),
    DataFrameQuery(
        query_id="3b",
        query_name="Canonical JoinOrder 3b",
        description="Canonical JoinOrder SQL query 3b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q3b_expression_impl,
        pandas_impl=q3b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="3c",
        query_name="Canonical JoinOrder 3c",
        description="Canonical JoinOrder SQL query 3c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q3c_expression_impl,
        pandas_impl=q3c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="4b",
        query_name="Canonical JoinOrder 4b",
        description="Canonical JoinOrder SQL query 4b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q4b_expression_impl,
        pandas_impl=q4b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="4c",
        query_name="Canonical JoinOrder 4c",
        description="Canonical JoinOrder SQL query 4c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q4c_expression_impl,
        pandas_impl=q4c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="5b",
        query_name="Canonical JoinOrder 5b",
        description="Canonical JoinOrder SQL query 5b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q5b_expression_impl,
        pandas_impl=q5b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="5c",
        query_name="Canonical JoinOrder 5c",
        description="Canonical JoinOrder SQL query 5c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q5c_expression_impl,
        pandas_impl=q5c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="6b",
        query_name="Canonical JoinOrder 6b",
        description="Canonical JoinOrder SQL query 6b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q6b_expression_impl,
        pandas_impl=q6b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="6c",
        query_name="Canonical JoinOrder 6c",
        description="Canonical JoinOrder SQL query 6c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q6c_expression_impl,
        pandas_impl=q6c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="6d",
        query_name="Canonical JoinOrder 6d",
        description="Canonical JoinOrder SQL query 6d; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q6d_expression_impl,
        pandas_impl=q6d_pandas_impl,
    ),
    DataFrameQuery(
        query_id="6e",
        query_name="Canonical JoinOrder 6e",
        description="Canonical JoinOrder SQL query 6e; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q6e_expression_impl,
        pandas_impl=q6e_pandas_impl,
    ),
    DataFrameQuery(
        query_id="6f",
        query_name="Canonical JoinOrder 6f",
        description="Canonical JoinOrder SQL query 6f; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q6f_expression_impl,
        pandas_impl=q6f_pandas_impl,
    ),
    DataFrameQuery(
        query_id="7b",
        query_name="Canonical JoinOrder 7b",
        description="Canonical JoinOrder SQL query 7b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q7b_expression_impl,
        pandas_impl=q7b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="7c",
        query_name="Canonical JoinOrder 7c",
        description="Canonical JoinOrder SQL query 7c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q7c_expression_impl,
        pandas_impl=q7c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="8b",
        query_name="Canonical JoinOrder 8b",
        description="Canonical JoinOrder SQL query 8b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q8b_expression_impl,
        pandas_impl=q8b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="8c",
        query_name="Canonical JoinOrder 8c",
        description="Canonical JoinOrder SQL query 8c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q8c_expression_impl,
        pandas_impl=q8c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="8d",
        query_name="Canonical JoinOrder 8d",
        description="Canonical JoinOrder SQL query 8d; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q8d_expression_impl,
        pandas_impl=q8d_pandas_impl,
    ),
    DataFrameQuery(
        query_id="9b",
        query_name="Canonical JoinOrder 9b",
        description="Canonical JoinOrder SQL query 9b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q9b_expression_impl,
        pandas_impl=q9b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="9c",
        query_name="Canonical JoinOrder 9c",
        description="Canonical JoinOrder SQL query 9c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q9c_expression_impl,
        pandas_impl=q9c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="9d",
        query_name="Canonical JoinOrder 9d",
        description="Canonical JoinOrder SQL query 9d; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q9d_expression_impl,
        pandas_impl=q9d_pandas_impl,
    ),
    DataFrameQuery(
        query_id="10b",
        query_name="Canonical JoinOrder 10b",
        description="Canonical JoinOrder SQL query 10b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q10b_expression_impl,
        pandas_impl=q10b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="10c",
        query_name="Canonical JoinOrder 10c",
        description="Canonical JoinOrder SQL query 10c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q10c_expression_impl,
        pandas_impl=q10c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="11b",
        query_name="Canonical JoinOrder 11b",
        description="Canonical JoinOrder SQL query 11b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q11b_expression_impl,
        pandas_impl=q11b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="11c",
        query_name="Canonical JoinOrder 11c",
        description="Canonical JoinOrder SQL query 11c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q11c_expression_impl,
        pandas_impl=q11c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="11d",
        query_name="Canonical JoinOrder 11d",
        description="Canonical JoinOrder SQL query 11d; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q11d_expression_impl,
        pandas_impl=q11d_pandas_impl,
    ),
    DataFrameQuery(
        query_id="12b",
        query_name="Canonical JoinOrder 12b",
        description="Canonical JoinOrder SQL query 12b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q12b_expression_impl,
        pandas_impl=q12b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="12c",
        query_name="Canonical JoinOrder 12c",
        description="Canonical JoinOrder SQL query 12c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q12c_expression_impl,
        pandas_impl=q12c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="13a",
        query_name="Canonical JoinOrder 13a",
        description="Canonical JoinOrder SQL query 13a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q13a_expression_impl,
        pandas_impl=q13a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="13b",
        query_name="Canonical JoinOrder 13b",
        description="Canonical JoinOrder SQL query 13b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q13b_expression_impl,
        pandas_impl=q13b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="13c",
        query_name="Canonical JoinOrder 13c",
        description="Canonical JoinOrder SQL query 13c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q13c_expression_impl,
        pandas_impl=q13c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="13d",
        query_name="Canonical JoinOrder 13d",
        description="Canonical JoinOrder SQL query 13d; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q13d_expression_impl,
        pandas_impl=q13d_pandas_impl,
    ),
    DataFrameQuery(
        query_id="14a",
        query_name="Canonical JoinOrder 14a",
        description="Canonical JoinOrder SQL query 14a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q14a_expression_impl,
        pandas_impl=q14a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="14b",
        query_name="Canonical JoinOrder 14b",
        description="Canonical JoinOrder SQL query 14b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q14b_expression_impl,
        pandas_impl=q14b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="14c",
        query_name="Canonical JoinOrder 14c",
        description="Canonical JoinOrder SQL query 14c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q14c_expression_impl,
        pandas_impl=q14c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="15a",
        query_name="Canonical JoinOrder 15a",
        description="Canonical JoinOrder SQL query 15a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q15a_expression_impl,
        pandas_impl=q15a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="15b",
        query_name="Canonical JoinOrder 15b",
        description="Canonical JoinOrder SQL query 15b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q15b_expression_impl,
        pandas_impl=q15b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="15c",
        query_name="Canonical JoinOrder 15c",
        description="Canonical JoinOrder SQL query 15c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q15c_expression_impl,
        pandas_impl=q15c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="15d",
        query_name="Canonical JoinOrder 15d",
        description="Canonical JoinOrder SQL query 15d; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q15d_expression_impl,
        pandas_impl=q15d_pandas_impl,
    ),
    DataFrameQuery(
        query_id="16a",
        query_name="Canonical JoinOrder 16a",
        description="Canonical JoinOrder SQL query 16a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q16a_expression_impl,
        pandas_impl=q16a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="16b",
        query_name="Canonical JoinOrder 16b",
        description="Canonical JoinOrder SQL query 16b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q16b_expression_impl,
        pandas_impl=q16b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="16c",
        query_name="Canonical JoinOrder 16c",
        description="Canonical JoinOrder SQL query 16c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q16c_expression_impl,
        pandas_impl=q16c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="16d",
        query_name="Canonical JoinOrder 16d",
        description="Canonical JoinOrder SQL query 16d; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q16d_expression_impl,
        pandas_impl=q16d_pandas_impl,
    ),
    DataFrameQuery(
        query_id="17a",
        query_name="Canonical JoinOrder 17a",
        description="Canonical JoinOrder SQL query 17a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q17a_expression_impl,
        pandas_impl=q17a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="17b",
        query_name="Canonical JoinOrder 17b",
        description="Canonical JoinOrder SQL query 17b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q17b_expression_impl,
        pandas_impl=q17b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="17c",
        query_name="Canonical JoinOrder 17c",
        description="Canonical JoinOrder SQL query 17c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q17c_expression_impl,
        pandas_impl=q17c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="17d",
        query_name="Canonical JoinOrder 17d",
        description="Canonical JoinOrder SQL query 17d; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q17d_expression_impl,
        pandas_impl=q17d_pandas_impl,
    ),
    DataFrameQuery(
        query_id="17e",
        query_name="Canonical JoinOrder 17e",
        description="Canonical JoinOrder SQL query 17e; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q17e_expression_impl,
        pandas_impl=q17e_pandas_impl,
    ),
    DataFrameQuery(
        query_id="17f",
        query_name="Canonical JoinOrder 17f",
        description="Canonical JoinOrder SQL query 17f; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q17f_expression_impl,
        pandas_impl=q17f_pandas_impl,
    ),
    DataFrameQuery(
        query_id="18a",
        query_name="Canonical JoinOrder 18a",
        description="Canonical JoinOrder SQL query 18a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q18a_expression_impl,
        pandas_impl=q18a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="18b",
        query_name="Canonical JoinOrder 18b",
        description="Canonical JoinOrder SQL query 18b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q18b_expression_impl,
        pandas_impl=q18b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="18c",
        query_name="Canonical JoinOrder 18c",
        description="Canonical JoinOrder SQL query 18c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q18c_expression_impl,
        pandas_impl=q18c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="19a",
        query_name="Canonical JoinOrder 19a",
        description="Canonical JoinOrder SQL query 19a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q19a_expression_impl,
        pandas_impl=q19a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="19b",
        query_name="Canonical JoinOrder 19b",
        description="Canonical JoinOrder SQL query 19b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q19b_expression_impl,
        pandas_impl=q19b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="19c",
        query_name="Canonical JoinOrder 19c",
        description="Canonical JoinOrder SQL query 19c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q19c_expression_impl,
        pandas_impl=q19c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="19d",
        query_name="Canonical JoinOrder 19d",
        description="Canonical JoinOrder SQL query 19d; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q19d_expression_impl,
        pandas_impl=q19d_pandas_impl,
    ),
    DataFrameQuery(
        query_id="20a",
        query_name="Canonical JoinOrder 20a",
        description="Canonical JoinOrder SQL query 20a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q20a_expression_impl,
        pandas_impl=q20a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="20b",
        query_name="Canonical JoinOrder 20b",
        description="Canonical JoinOrder SQL query 20b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q20b_expression_impl,
        pandas_impl=q20b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="20c",
        query_name="Canonical JoinOrder 20c",
        description="Canonical JoinOrder SQL query 20c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q20c_expression_impl,
        pandas_impl=q20c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="21a",
        query_name="Canonical JoinOrder 21a",
        description="Canonical JoinOrder SQL query 21a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q21a_expression_impl,
        pandas_impl=q21a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="21b",
        query_name="Canonical JoinOrder 21b",
        description="Canonical JoinOrder SQL query 21b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q21b_expression_impl,
        pandas_impl=q21b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="21c",
        query_name="Canonical JoinOrder 21c",
        description="Canonical JoinOrder SQL query 21c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q21c_expression_impl,
        pandas_impl=q21c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="22a",
        query_name="Canonical JoinOrder 22a",
        description="Canonical JoinOrder SQL query 22a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q22a_expression_impl,
        pandas_impl=q22a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="22b",
        query_name="Canonical JoinOrder 22b",
        description="Canonical JoinOrder SQL query 22b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q22b_expression_impl,
        pandas_impl=q22b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="22c",
        query_name="Canonical JoinOrder 22c",
        description="Canonical JoinOrder SQL query 22c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q22c_expression_impl,
        pandas_impl=q22c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="22d",
        query_name="Canonical JoinOrder 22d",
        description="Canonical JoinOrder SQL query 22d; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q22d_expression_impl,
        pandas_impl=q22d_pandas_impl,
    ),
    DataFrameQuery(
        query_id="23a",
        query_name="Canonical JoinOrder 23a",
        description="Canonical JoinOrder SQL query 23a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q23a_expression_impl,
        pandas_impl=q23a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="23b",
        query_name="Canonical JoinOrder 23b",
        description="Canonical JoinOrder SQL query 23b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q23b_expression_impl,
        pandas_impl=q23b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="23c",
        query_name="Canonical JoinOrder 23c",
        description="Canonical JoinOrder SQL query 23c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q23c_expression_impl,
        pandas_impl=q23c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="24a",
        query_name="Canonical JoinOrder 24a",
        description="Canonical JoinOrder SQL query 24a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q24a_expression_impl,
        pandas_impl=q24a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="24b",
        query_name="Canonical JoinOrder 24b",
        description="Canonical JoinOrder SQL query 24b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q24b_expression_impl,
        pandas_impl=q24b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="25a",
        query_name="Canonical JoinOrder 25a",
        description="Canonical JoinOrder SQL query 25a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q25a_expression_impl,
        pandas_impl=q25a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="25b",
        query_name="Canonical JoinOrder 25b",
        description="Canonical JoinOrder SQL query 25b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q25b_expression_impl,
        pandas_impl=q25b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="25c",
        query_name="Canonical JoinOrder 25c",
        description="Canonical JoinOrder SQL query 25c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q25c_expression_impl,
        pandas_impl=q25c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="26a",
        query_name="Canonical JoinOrder 26a",
        description="Canonical JoinOrder SQL query 26a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q26a_expression_impl,
        pandas_impl=q26a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="26b",
        query_name="Canonical JoinOrder 26b",
        description="Canonical JoinOrder SQL query 26b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q26b_expression_impl,
        pandas_impl=q26b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="26c",
        query_name="Canonical JoinOrder 26c",
        description="Canonical JoinOrder SQL query 26c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q26c_expression_impl,
        pandas_impl=q26c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="27a",
        query_name="Canonical JoinOrder 27a",
        description="Canonical JoinOrder SQL query 27a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q27a_expression_impl,
        pandas_impl=q27a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="27b",
        query_name="Canonical JoinOrder 27b",
        description="Canonical JoinOrder SQL query 27b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q27b_expression_impl,
        pandas_impl=q27b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="27c",
        query_name="Canonical JoinOrder 27c",
        description="Canonical JoinOrder SQL query 27c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q27c_expression_impl,
        pandas_impl=q27c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="28a",
        query_name="Canonical JoinOrder 28a",
        description="Canonical JoinOrder SQL query 28a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q28a_expression_impl,
        pandas_impl=q28a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="28b",
        query_name="Canonical JoinOrder 28b",
        description="Canonical JoinOrder SQL query 28b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q28b_expression_impl,
        pandas_impl=q28b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="28c",
        query_name="Canonical JoinOrder 28c",
        description="Canonical JoinOrder SQL query 28c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q28c_expression_impl,
        pandas_impl=q28c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="29a",
        query_name="Canonical JoinOrder 29a",
        description="Canonical JoinOrder SQL query 29a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q29a_expression_impl,
        pandas_impl=q29a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="29b",
        query_name="Canonical JoinOrder 29b",
        description="Canonical JoinOrder SQL query 29b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q29b_expression_impl,
        pandas_impl=q29b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="29c",
        query_name="Canonical JoinOrder 29c",
        description="Canonical JoinOrder SQL query 29c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q29c_expression_impl,
        pandas_impl=q29c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="30a",
        query_name="Canonical JoinOrder 30a",
        description="Canonical JoinOrder SQL query 30a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q30a_expression_impl,
        pandas_impl=q30a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="30b",
        query_name="Canonical JoinOrder 30b",
        description="Canonical JoinOrder SQL query 30b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q30b_expression_impl,
        pandas_impl=q30b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="30c",
        query_name="Canonical JoinOrder 30c",
        description="Canonical JoinOrder SQL query 30c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q30c_expression_impl,
        pandas_impl=q30c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="31a",
        query_name="Canonical JoinOrder 31a",
        description="Canonical JoinOrder SQL query 31a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q31a_expression_impl,
        pandas_impl=q31a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="31b",
        query_name="Canonical JoinOrder 31b",
        description="Canonical JoinOrder SQL query 31b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q31b_expression_impl,
        pandas_impl=q31b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="31c",
        query_name="Canonical JoinOrder 31c",
        description="Canonical JoinOrder SQL query 31c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q31c_expression_impl,
        pandas_impl=q31c_pandas_impl,
    ),
    DataFrameQuery(
        query_id="32a",
        query_name="Canonical JoinOrder 32a",
        description="Canonical JoinOrder SQL query 32a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q32a_expression_impl,
        pandas_impl=q32a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="32b",
        query_name="Canonical JoinOrder 32b",
        description="Canonical JoinOrder SQL query 32b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q32b_expression_impl,
        pandas_impl=q32b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="33a",
        query_name="Canonical JoinOrder 33a",
        description="Canonical JoinOrder SQL query 33a; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q33a_expression_impl,
        pandas_impl=q33a_pandas_impl,
    ),
    DataFrameQuery(
        query_id="33b",
        query_name="Canonical JoinOrder 33b",
        description="Canonical JoinOrder SQL query 33b; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q33b_expression_impl,
        pandas_impl=q33b_pandas_impl,
    ),
    DataFrameQuery(
        query_id="33c",
        query_name="Canonical JoinOrder 33c",
        description="Canonical JoinOrder SQL query 33c; DataFrame translation pending Track-2 coverage",
        categories=[QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=q33c_expression_impl,
        pandas_impl=q33c_pandas_impl,
    ),
]

for _query in _QUERIES:
    JOINORDER_DATAFRAME_QUERIES.register(_query)


def get_dataframe_queries() -> QueryRegistry:
    """Get the canonical JoinOrder DataFrame query registry.

    The registry contains all 113 canonical query IDs. Only
    IMPLEMENTED_DATAFRAME_QUERY_IDS are selected by default by the benchmark;
    the remaining functions raise NotImplementedError with the Track-2 TODO.
    """
    return JOINORDER_DATAFRAME_QUERIES


def get_implemented_dataframe_query_ids() -> list[str]:
    """Return query IDs with real DataFrame translations."""
    return list(IMPLEMENTED_DATAFRAME_QUERY_IDS)


def get_untranslated_dataframe_query_ids() -> list[str]:
    """Return canonical query IDs that are registered as Track-2 stubs."""
    return list(UNTRANSLATED_DATAFRAME_QUERY_IDS)
