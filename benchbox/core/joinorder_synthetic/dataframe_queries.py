"""Synthetic JoinOrder DataFrame queries for Expression and Pandas families.

Implements the 13 historical JoinOrder smoke-test queries through a restricted
JOB SQL-to-DataFrame translator.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import re
from csv import reader
from typing import TYPE_CHECKING, Any

from sqlglot import exp, parse_one

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory, QueryRegistry
from benchbox.core.joinorder.dataframe_queries import (
    _aliases_in,
    _column_ref,
    _empty_safe_min,
    _expression_condition,
    _filter_pandas,
    _flatten_and,
    _is_join_equality,
    _join_key,
    _prefixed_pandas_frame,
    _qualified,
    _select_min_columns,
    _sql_tables,
)
from benchbox.core.joinorder_synthetic.queries import JoinOrderQueryManager

if TYPE_CHECKING:
    import pandas as pd

_QUERY_MANAGER = JoinOrderQueryManager()
_PARENTHESIZED_LIKE_PATTERN = re.compile(r"(NOT\s+LIKE|LIKE)\s+'%\(([^%()]+)\)%'", re.IGNORECASE)
_Q6A_ACTOR_NAME_PATTERN = re.compile(r"n\.name\s+LIKE\s+'%Downey%Robert%'", re.IGNORECASE)


def _query_sql(query_id: str) -> str:
    sql = _PARENTHESIZED_LIKE_PATTERN.sub(
        lambda match: f"{match.group(1)} '%{match.group(2)}%'", _QUERY_MANAGER.get_query(query_id)
    )
    if query_id == "6a":
        sql = _Q6A_ACTOR_NAME_PATTERN.sub("n.name LIKE '%Downey%' AND n.name LIKE '%Robert%'", sql)
    return sql


def _join_predicates(tree: exp.Select) -> tuple[list[tuple[str, str]], list[exp.Expression], list[exp.Expression]]:
    tables = _sql_tables(tree)
    predicates = _flatten_and(tree.args["where"].this)
    return tables, predicates, [predicate for predicate in predicates if _is_join_equality(predicate)]


def _referenced_columns(alias: str, tree: exp.Select, predicates: list[exp.Expression]) -> set[str]:
    columns = {
        column.name
        for node in [*predicates, *tree.expressions]
        for column in node.find_all(exp.Column)
        if str(column.table) == alias
    }
    return columns


def _prefixed_expression_frame(
    ctx: DataFrameContext,
    table_name: str,
    alias: str,
    predicates: list[exp.Expression],
    join_key_columns: list[tuple[str, int]],
    referenced_columns: set[str],
) -> Any:
    frame = ctx.get_table(table_name)
    frame = frame.select(
        [ctx.col(column).alias(_qualified(alias, column)) for column in sorted(referenced_columns)]
        + [ctx.col(column).alias(_join_key(alias, column, index)) for column, index in join_key_columns]
    )
    for predicate in predicates:
        frame = frame.filter(_expression_condition(ctx, predicate))
    return frame


def _execute_joinorder_expression_query(ctx: DataFrameContext, query_id: str) -> Any:
    tree = parse_one(_query_sql(query_id), read="duckdb")
    tables, predicates, join_predicates = _join_predicates(tree)
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
        alias: _prefixed_expression_frame(
            ctx,
            table_name,
            alias,
            local_predicates[alias],
            join_key_columns[alias],
            _referenced_columns(alias, tree, predicates),
        )
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


def _execute_joinorder_pandas_query(ctx: DataFrameContext, query_id: str) -> pd.DataFrame:
    import pandas as pd

    tree = parse_one(_query_sql(query_id), read="duckdb")
    tables, predicates, join_predicates = _join_predicates(tree)
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


def _make_expression_impl(query_id: str) -> Any:
    def _impl(ctx: DataFrameContext) -> Any:
        return _execute_joinorder_expression_query(ctx, query_id)

    _impl.__name__ = f"q{query_id}_expression_impl"
    _impl.__doc__ = f"{query_id}: generated synthetic JoinOrder DataFrame translation."
    return _impl


def _make_pandas_impl(query_id: str) -> Any:
    def _impl(ctx: DataFrameContext) -> Any:
        return _execute_joinorder_pandas_query(ctx, query_id)

    _impl.__name__ = f"q{query_id}_pandas_impl"
    _impl.__doc__ = f"{query_id}: generated synthetic JoinOrder pandas translation."
    return _impl


_QUERY_IDS = ("1a", "1b", "2a", "3a", "4a", "5a", "6a", "7a", "8a", "9a", "10a", "11a", "12a")

for _query_id in _QUERY_IDS:
    globals()[f"q{_query_id}_expression_impl"] = _make_expression_impl(_query_id)
    globals()[f"q{_query_id}_pandas_impl"] = _make_pandas_impl(_query_id)


JOINORDER_DATAFRAME_QUERIES = QueryRegistry("JoinOrder DataFrame")

_CATEGORY_CODES = {
    "AG": QueryCategory.AGGREGATE,
    "FI": QueryCategory.FILTER,
    "JO": QueryCategory.JOIN,
    "MJ": QueryCategory.MULTI_JOIN,
}

_QUERY_METADATA = """\
1a|Production Companies Top 250|Production companies with top 250 ranked movies (5 tables)|JO,AG,FI
1b|Production Companies Bottom 10|Variant of 1a with bottom 10 rank predicate (5 tables)|JO,AG,FI
2a|German Company Character Name Movies|Movies from German companies with character-name-in-title keyword (5 tables)|JO,AG,FI
3a|Scandinavian/German Sequel Movies|Sequel movies from Scandinavian/German countries after 1990 (4 tables)|JO,AG,FI
4a|Sequel Movies with High Rating|Sequel movies with rating > 2.0 after 1990 (5 tables)|JO,AG,FI
5a|European Theatrical Movies|European theatrical movies from France production companies after 2005 (5 tables)|JO,AG,FI
6a|Superhero Movies with Robert Downey Jr.|Superhero/action movies featuring Robert Downey Jr. after 2000 (5 tables)|JO,AG,FI
7a|Biography Movies with Person Criteria|Biography movies with specific person criteria (8 tables)|MJ,AG,FI
8a|Japanese Dubbed Movies|Japanese dubbed movies by specific actress criteria (7 tables)|MJ,AG,FI
9a|American Voice Actress Movies|American voice actress movies (8 tables)|MJ,AG,FI
10a|American Producer Movies|Movies with American producers after 1990 (7 tables)|MJ,AG,FI
11a|Non-Polish Sequel Movies with Follow Links|Sequel movies from Film/Warner companies with follow links (9 tables)|MJ,AG,FI
12a|Drama/Horror US Movies with High Ratings|US drama/horror movies with high ratings using double info_type join (8 tables)|MJ,AG,FI
"""


_QUERIES = [
    DataFrameQuery(
        query_id=query_id,
        query_name=query_name,
        description=description,
        categories=[_CATEGORY_CODES[code] for code in category_codes.split(",")],
        expression_impl=globals()[f"q{query_id}_expression_impl"],
        pandas_impl=globals()[f"q{query_id}_pandas_impl"],
    )
    for query_id, query_name, description, category_codes in reader(_QUERY_METADATA.splitlines(), delimiter="|")
]

for _query in _QUERIES:
    JOINORDER_DATAFRAME_QUERIES.register(_query)


def get_dataframe_queries() -> QueryRegistry:
    """Get the JoinOrder DataFrame query registry."""
    return JOINORDER_DATAFRAME_QUERIES
