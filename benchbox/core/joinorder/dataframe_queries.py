"""Canonical JoinOrder Benchmark DataFrame queries for Expression and Pandas families.

Implements all 113 canonical JoinOrder query IDs. The original 13 queries keep
their hand-written translations; the remaining canonical SQL queries use the
restricted JOB SQL-to-DataFrame translator in this module.

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

import re
from csv import reader
from typing import Any

import pandas as pd
from sqlglot import exp, parse_one

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory, QueryRegistry
from benchbox.core.joinorder.queries import CANONICAL_JOINORDER_QUERIES, JoinOrderQueryManager
from benchbox.core.joinorder.schema import JoinOrderSchema

IMPLEMENTED_DATAFRAME_QUERY_IDS = list(CANONICAL_JOINORDER_QUERIES)
UNTRANSLATED_DATAFRAME_QUERY_IDS: list[str] = []
_HAND_TRANSLATED_DATAFRAME_QUERY_IDS = {
    "1a",
    "1b",
    "2a",
    "3a",
    "4a",
    "5a",
    "6a",
    "7a",
    "8a",
    "9a",
    "10a",
    "11a",
    "12a",
}
_TRACK2_TODO = "_project/TODO/main/planning/track2-joinorder-dataframe-coverage.yaml"
_QUERY_MANAGER = JoinOrderQueryManager()


def _schema_columns() -> dict[str, list[str]]:
    schema = JoinOrderSchema()
    tables = schema._tables  # noqa: SLF001 - internal benchmark module consuming its schema definition.
    return {
        table: [column_def.split()[0] for column_def in table_def["columns"]] for table, table_def in tables.items()
    }


_TABLE_COLUMNS = _schema_columns()


def _raise_untranslated_dataframe_query(query_id: str) -> None:
    raise NotImplementedError(
        f"DataFrame translation for query {query_id} not yet available. Track-2 TODO: {_TRACK2_TODO}"
    )


def _qualified(alias: str, column: str) -> str:
    return f"{alias}__{column}"


def _join_key(alias: str, column: str, predicate_index: int) -> str:
    return f"{_qualified(alias, column)}__join_key_{predicate_index}"


def _column_ref(node: exp.Expression) -> tuple[str, str]:
    if not isinstance(node, exp.Column) or not node.table:
        raise NotImplementedError(f"Unsupported JoinOrder DataFrame SQL column expression: {node}")
    return str(node.table), node.name


def _literal_value(node: exp.Expression) -> Any:
    if isinstance(node, exp.Null):
        return None
    if not isinstance(node, exp.Literal):
        raise NotImplementedError(f"Unsupported JoinOrder DataFrame SQL literal expression: {node}")
    if node.is_string:
        return str(node.this)
    raw = str(node.this)
    return int(raw) if raw.isdigit() else float(raw)


def _like_pattern_to_regex(pattern: str) -> str:
    parts: list[str] = ["^"]
    for char in pattern:
        if char == "%":
            parts.append(".*")
        elif char == "_":
            parts.append(".")
        else:
            parts.append(re.escape(char))
    parts.append("$")
    return "".join(parts)


def _flatten_and(node: exp.Expression) -> list[exp.Expression]:
    if isinstance(node, exp.And):
        return _flatten_and(node.this) + _flatten_and(node.expression)
    if isinstance(node, exp.Paren):
        return _flatten_and(node.this)
    return [node]


def _aliases_in(node: exp.Expression) -> set[str]:
    return {str(column.table) for column in node.find_all(exp.Column) if column.table}


def _is_join_equality(node: exp.Expression) -> bool:
    if not isinstance(node, exp.EQ):
        return False
    left = node.this
    right = node.expression
    return isinstance(left, exp.Column) and isinstance(right, exp.Column) and str(left.table) != str(right.table)


def _sql_tables(tree: exp.Select) -> list[tuple[str, str]]:
    tables: list[tuple[str, str]] = []
    from_expr = tree.args.get("from_")
    if from_expr is not None and isinstance(from_expr.this, exp.Table):
        table = from_expr.this
        tables.append((table.alias_or_name, table.name))
    for join in tree.args.get("joins") or []:
        if isinstance(join.this, exp.Table):
            table = join.this
            tables.append((table.alias_or_name, table.name))
    if not tables:
        raise NotImplementedError("JoinOrder DataFrame SQL query has no FROM tables")
    return tables


def _select_min_columns(tree: exp.Select) -> list[tuple[str, str, str]]:
    columns: list[tuple[str, str, str]] = []
    for select_expr in tree.expressions:
        if not isinstance(select_expr, exp.Alias) or not isinstance(select_expr.this, exp.Min):
            raise NotImplementedError(f"JoinOrder DataFrame only supports MIN(...) projections: {select_expr}")
        alias, column = _column_ref(select_expr.this.this)
        columns.append((alias, column, select_expr.alias))
    return columns


def _expr_value(ctx: DataFrameContext, node: exp.Expression) -> Any:
    if isinstance(node, exp.Column):
        alias, column = _column_ref(node)
        return ctx.col(_qualified(alias, column))
    return ctx.lit(_literal_value(node))


def _expression_condition(ctx: DataFrameContext, node: exp.Expression) -> Any:
    if isinstance(node, exp.Paren):
        return _expression_condition(ctx, node.this)
    if isinstance(node, exp.And):
        return _expression_condition(ctx, node.this) & _expression_condition(ctx, node.expression)
    if isinstance(node, exp.Or):
        return _expression_condition(ctx, node.this) | _expression_condition(ctx, node.expression)
    if isinstance(node, exp.Not):
        return ~_expression_condition(ctx, node.this)
    if isinstance(node, exp.EQ):
        return _expr_value(ctx, node.this) == _expr_value(ctx, node.expression)
    if isinstance(node, exp.NEQ):
        return _expr_value(ctx, node.this) != _expr_value(ctx, node.expression)
    if isinstance(node, exp.GT):
        return _expr_value(ctx, node.this) > _expr_value(ctx, node.expression)
    if isinstance(node, exp.GTE):
        return _expr_value(ctx, node.this) >= _expr_value(ctx, node.expression)
    if isinstance(node, exp.LT):
        return _expr_value(ctx, node.this) < _expr_value(ctx, node.expression)
    if isinstance(node, exp.Between):
        return _expr_value(ctx, node.this).is_between(
            _expr_value(ctx, node.args["low"]), _expr_value(ctx, node.args["high"])
        )
    if isinstance(node, exp.In):
        return _expr_value(ctx, node.this).is_in([_literal_value(value) for value in node.expressions])
    if isinstance(node, exp.Like):
        return _expr_value(ctx, node.this).str.contains(_like_pattern_to_regex(_literal_value(node.expression)))
    if isinstance(node, exp.Is):
        expr = _expr_value(ctx, node.this)
        return expr.is_null() if isinstance(node.expression, exp.Null) else expr == _expr_value(ctx, node.expression)
    raise NotImplementedError(f"Unsupported JoinOrder DataFrame SQL predicate: {node}")


def _prefixed_expression_frame(
    ctx: DataFrameContext,
    table_name: str,
    alias: str,
    predicates: list[exp.Expression],
    join_key_columns: list[tuple[str, int]],
) -> Any:
    frame = ctx.get_table(table_name)
    frame = frame.select(
        [ctx.col(column).alias(_qualified(alias, column)) for column in _TABLE_COLUMNS[table_name]]
        + [ctx.col(column).alias(_join_key(alias, column, index)) for column, index in join_key_columns]
    )
    for predicate in predicates:
        frame = frame.filter(_expression_condition(ctx, predicate))
    return frame


def _execute_joinorder_expression_query(ctx: DataFrameContext, query_id: str) -> Any:
    tree = parse_one(_QUERY_MANAGER.get_query(query_id), read="duckdb")
    tables = _sql_tables(tree)
    predicates = _flatten_and(tree.args["where"].this)
    join_predicates = [predicate for predicate in predicates if _is_join_equality(predicate)]
    join_key_columns: dict[str, list[tuple[str, int]]] = {alias: [] for alias, _table in tables}
    for index, predicate in enumerate(join_predicates):
        left_alias, left_column = _column_ref(predicate.this)
        right_alias, right_column = _column_ref(predicate.expression)
        join_key_columns[left_alias].append((left_column, index))
        join_key_columns[right_alias].append((right_column, index))
    local_predicates = {
        alias: [
            predicate
            for predicate in predicates
            if not _is_join_equality(predicate) and _aliases_in(predicate) == {alias}
        ]
        for alias, _table in tables
    }
    frames = {
        alias: _prefixed_expression_frame(ctx, table_name, alias, local_predicates[alias], join_key_columns[alias])
        for alias, table_name in tables
    }

    joined_aliases = {tables[0][0]}
    result = frames[tables[0][0]]
    remaining_aliases = {alias for alias, _table in tables[1:]}
    used_join_predicates: set[int] = set()

    while remaining_aliases:
        for predicate_index, predicate in enumerate(join_predicates):
            left_alias, left_column = _column_ref(predicate.this)
            right_alias, right_column = _column_ref(predicate.expression)
            if left_alias in joined_aliases and right_alias in remaining_aliases:
                result = result.join(
                    frames[right_alias],
                    left_on=_join_key(left_alias, left_column, predicate_index),
                    right_on=_join_key(right_alias, right_column, predicate_index),
                )
                joined_aliases.add(right_alias)
                remaining_aliases.remove(right_alias)
                used_join_predicates.add(id(predicate))
                break
            if right_alias in joined_aliases and left_alias in remaining_aliases:
                result = result.join(
                    frames[left_alias],
                    left_on=_join_key(right_alias, right_column, predicate_index),
                    right_on=_join_key(left_alias, left_column, predicate_index),
                )
                joined_aliases.add(left_alias)
                remaining_aliases.remove(left_alias)
                used_join_predicates.add(id(predicate))
                break
        else:
            alias = remaining_aliases.pop()
            result = result.join(frames[alias], how="cross")
            joined_aliases.add(alias)

    for predicate in predicates:
        if id(predicate) not in used_join_predicates:
            result = result.filter(_expression_condition(ctx, predicate))

    return result.select(
        [
            ctx.col(_qualified(alias, column)).min().alias(output_alias)
            for alias, column, output_alias in _select_min_columns(tree)
        ]
    )


def _native_pandas_frame(frame: Any) -> Any:
    return frame.native if hasattr(frame, "native") else frame


def _pandas_value(frame: pd.DataFrame, node: exp.Expression) -> Any:
    if isinstance(node, exp.Column):
        alias, column = _column_ref(node)
        return frame[_qualified(alias, column)]
    return _literal_value(node)


def _pandas_not_null_mask(*values: Any) -> Any:
    mask = True
    for value in values:
        if hasattr(value, "notna"):
            mask = mask & value.notna()
    return mask


def _pandas_sql_compare(left: Any, right: Any, operator: Any) -> Any:
    return operator(left, right) & _pandas_not_null_mask(left, right)


def _pandas_condition(frame: pd.DataFrame, node: exp.Expression) -> Any:
    if isinstance(node, exp.Paren):
        return _pandas_condition(frame, node.this)
    if isinstance(node, exp.And):
        return _pandas_condition(frame, node.this) & _pandas_condition(frame, node.expression)
    if isinstance(node, exp.Or):
        return _pandas_condition(frame, node.this) | _pandas_condition(frame, node.expression)
    if isinstance(node, exp.Not):
        return ~_pandas_condition(frame, node.this)
    if isinstance(node, exp.EQ):
        return _pandas_sql_compare(
            _pandas_value(frame, node.this), _pandas_value(frame, node.expression), lambda a, b: a == b
        )
    if isinstance(node, exp.NEQ):
        return _pandas_sql_compare(
            _pandas_value(frame, node.this), _pandas_value(frame, node.expression), lambda a, b: a != b
        )
    if isinstance(node, exp.GT):
        return _pandas_sql_compare(
            _pandas_value(frame, node.this), _pandas_value(frame, node.expression), lambda a, b: a > b
        )
    if isinstance(node, exp.GTE):
        return _pandas_sql_compare(
            _pandas_value(frame, node.this), _pandas_value(frame, node.expression), lambda a, b: a >= b
        )
    if isinstance(node, exp.LT):
        return _pandas_sql_compare(
            _pandas_value(frame, node.this), _pandas_value(frame, node.expression), lambda a, b: a < b
        )
    if isinstance(node, exp.Between):
        return _pandas_value(frame, node.this).between(
            _literal_value(node.args["low"]), _literal_value(node.args["high"])
        )
    if isinstance(node, exp.In):
        return _pandas_value(frame, node.this).isin([_literal_value(value) for value in node.expressions])
    if isinstance(node, exp.Like):
        return (
            _pandas_value(frame, node.this)
            .astype("string")
            .str.contains(_like_pattern_to_regex(_literal_value(node.expression)), regex=True, na=pd.NA)
        )
    if isinstance(node, exp.Is):
        value = _pandas_value(frame, node.this)
        return value.isna() if isinstance(node.expression, exp.Null) else value == _pandas_value(frame, node.expression)
    raise NotImplementedError(f"Unsupported JoinOrder DataFrame SQL predicate: {node}")


def _filter_pandas(frame: pd.DataFrame, predicate: exp.Expression) -> pd.DataFrame:
    return frame[_pandas_condition(frame, predicate).fillna(False)]


def _prefixed_pandas_frame(
    ctx: DataFrameContext, table_name: str, alias: str, predicates: list[exp.Expression]
) -> pd.DataFrame:
    frame = _native_pandas_frame(ctx.get_table(table_name))
    frame = frame.rename(columns={column: _qualified(alias, column) for column in _TABLE_COLUMNS[table_name]})
    for predicate in predicates:
        frame = _filter_pandas(frame, predicate)
    return frame


def _empty_safe_min(frame: Any, column: str) -> Any:
    value = frame[column].min()
    if hasattr(value, "compute"):
        value = value.compute()
    return None if pd.isna(value) else value


def _execute_joinorder_pandas_query(ctx: DataFrameContext, query_id: str) -> pd.DataFrame:
    tree = parse_one(_QUERY_MANAGER.get_query(query_id), read="duckdb")
    tables = _sql_tables(tree)
    predicates = _flatten_and(tree.args["where"].this)
    join_predicates = [predicate for predicate in predicates if _is_join_equality(predicate)]
    local_predicates = {
        alias: [
            predicate
            for predicate in predicates
            if not _is_join_equality(predicate) and _aliases_in(predicate) == {alias}
        ]
        for alias, _table in tables
    }
    frames = {
        alias: _prefixed_pandas_frame(ctx, table_name, alias, local_predicates[alias]) for alias, table_name in tables
    }

    joined_aliases = {tables[0][0]}
    result = frames[tables[0][0]]
    remaining_aliases = {alias for alias, _table in tables[1:]}
    used_join_predicates: set[int] = set()

    while remaining_aliases:
        for predicate in join_predicates:
            left_alias, left_column = _column_ref(predicate.this)
            right_alias, right_column = _column_ref(predicate.expression)
            if left_alias in joined_aliases and right_alias in remaining_aliases:
                result = result.merge(
                    frames[right_alias],
                    left_on=_qualified(left_alias, left_column),
                    right_on=_qualified(right_alias, right_column),
                    how="inner",
                )
                joined_aliases.add(right_alias)
                remaining_aliases.remove(right_alias)
                used_join_predicates.add(id(predicate))
                break
            if right_alias in joined_aliases and left_alias in remaining_aliases:
                result = result.merge(
                    frames[left_alias],
                    left_on=_qualified(right_alias, right_column),
                    right_on=_qualified(left_alias, left_column),
                    how="inner",
                )
                joined_aliases.add(left_alias)
                remaining_aliases.remove(left_alias)
                used_join_predicates.add(id(predicate))
                break
        else:
            alias = remaining_aliases.pop()
            result = result.merge(frames[alias], how="cross")
            joined_aliases.add(alias)

    for predicate in predicates:
        if id(predicate) not in used_join_predicates:
            result = _filter_pandas(result, predicate)

    return pd.DataFrame(
        [
            {
                output_alias: _empty_safe_min(result, _qualified(alias, column))
                for alias, column, output_alias in _select_min_columns(tree)
            }
        ]
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


def _make_generated_expression_impl(query_id: str) -> Any:
    def _impl(ctx: DataFrameContext) -> Any:
        return _execute_joinorder_expression_query(ctx, query_id)

    _impl.__name__ = f"q{query_id}_expression_impl"
    _impl.__doc__ = f"{query_id}: generated canonical JoinOrder DataFrame translation."
    return _impl


def _make_generated_pandas_impl(query_id: str) -> Any:
    def _impl(ctx: DataFrameContext) -> Any:
        return _execute_joinorder_pandas_query(ctx, query_id)

    _impl.__name__ = f"q{query_id}_pandas_impl"
    _impl.__doc__ = f"{query_id}: generated canonical JoinOrder pandas translation."
    return _impl


for _query_id in CANONICAL_JOINORDER_QUERIES:
    if _query_id in _HAND_TRANSLATED_DATAFRAME_QUERY_IDS:
        continue
    globals()[f"q{_query_id}_expression_impl"] = _make_generated_expression_impl(_query_id)
    globals()[f"q{_query_id}_pandas_impl"] = _make_generated_pandas_impl(_query_id)


# ===========================================================================
# Registry
# ===========================================================================

JOINORDER_DATAFRAME_QUERIES = QueryRegistry("JoinOrder DataFrame")

_CATEGORY_CODES = {
    "A": QueryCategory.AGGREGATE,
    "F": QueryCategory.FILTER,
    "J": QueryCategory.JOIN,
    "M": QueryCategory.MULTI_JOIN,
}
_DEFAULT_GENERATED_CATEGORIES = (QueryCategory.MULTI_JOIN, QueryCategory.AGGREGATE, QueryCategory.FILTER)

_QUERY_IDS = """\
1a
1b
2a
3a
4a
5a
6a
7a
8a
9a
10a
11a
12a
1c
1d
2b
2c
2d
3b
3c
4b
4c
5b
5c
6b
6c
6d
6e
6f
7b
7c
8b
8c
8d
9b
9c
9d
10b
10c
11b
11c
11d
12b
12c
13a
13b
13c
13d
14a
14b
14c
15a
15b
15c
15d
16a
16b
16c
16d
17a
17b
17c
17d
17e
17f
18a
18b
18c
19a
19b
19c
19d
20a
20b
20c
21a
21b
21c
22a
22b
22c
22d
23a
23b
23c
24a
24b
25a
25b
25c
26a
26b
26c
27a
27b
27c
28a
28b
28c
29a
29b
29c
30a
30b
30c
31a
31b
31c
32a
32b
33a
33b
33c
"""

_HAND_QUERY_METADATA = """\
1a|Production Companies Top 250|Production companies with top 250 ranked movies (5 tables)|J,A,F
1b|Production Companies Bottom 10|Variant of 1a with bottom 10 rank predicate (5 tables)|J,A,F
2a|German Company Character Name Movies|Movies from German companies with character-name-in-title keyword (5 tables)|J,A,F
3a|Scandinavian/German Sequel Movies|Sequel movies from Scandinavian/German countries after 1990 (4 tables)|J,A,F
4a|Sequel Movies with High Rating|Sequel movies with rating > 2.0 after 1990 (5 tables)|J,A,F
5a|European Theatrical Movies|European theatrical movies from France production companies after 2005 (5 tables)|J,A,F
6a|Superhero Movies with Robert Downey Jr.|Superhero/action movies featuring Robert Downey Jr. after 2000 (5 tables)|J,A,F
7a|Biography Movies with Person Criteria|Biography movies with specific person criteria (8 tables)|M,A,F
8a|Japanese Dubbed Movies|Japanese dubbed movies by specific actress criteria (7 tables)|M,A,F
9a|American Voice Actress Movies|American voice actress movies (8 tables)|M,A,F
10a|American Producer Movies|Movies with American producers after 1990 (7 tables)|M,A,F
11a|Non-Polish Sequel Movies with Follow Links|Sequel movies from Film/Warner companies with follow links (9 tables)|M,A,F
12a|Drama/Horror US Movies with High Ratings|US drama/horror movies with high ratings using double info_type join (8 tables)|M,A,F
"""


def _category_list(codes: str) -> list[QueryCategory]:
    return [_CATEGORY_CODES[code] for code in codes.split(",")]


_HAND_QUERY_METADATA_BY_ID = {
    query_id: (query_name, description, tuple(_category_list(category_codes)))
    for query_id, query_name, description, category_codes in reader(_HAND_QUERY_METADATA.splitlines(), delimiter="|")
}


def _make_query(query_id: str) -> DataFrameQuery:
    if query_id in _HAND_QUERY_METADATA_BY_ID:
        query_name, description, categories = _HAND_QUERY_METADATA_BY_ID[query_id]
    else:
        query_name = f"Canonical JoinOrder {query_id}"
        description = f"Canonical JoinOrder SQL query {query_id}; generated DataFrame translation"
        categories = _DEFAULT_GENERATED_CATEGORIES
    return DataFrameQuery(
        query_id=query_id,
        query_name=query_name,
        description=description,
        categories=list(categories),
        expression_impl=globals()[f"q{query_id}_expression_impl"],
        pandas_impl=globals()[f"q{query_id}_pandas_impl"],
    )


_QUERIES = [_make_query(query_id) for query_id in _QUERY_IDS.splitlines()]

for _query in _QUERIES:
    JOINORDER_DATAFRAME_QUERIES.register(_query)


def get_dataframe_queries() -> QueryRegistry:
    """Get the canonical JoinOrder DataFrame query registry.

    The registry contains DataFrame implementations for all 113 canonical query IDs.
    """
    return JOINORDER_DATAFRAME_QUERIES


def get_implemented_dataframe_query_ids() -> list[str]:
    """Return query IDs with real DataFrame translations."""
    return list(IMPLEMENTED_DATAFRAME_QUERY_IDS)


def get_untranslated_dataframe_query_ids() -> list[str]:
    """Return canonical query IDs that are not available in DataFrame mode."""
    return list(UNTRANSLATED_DATAFRAME_QUERY_IDS)
