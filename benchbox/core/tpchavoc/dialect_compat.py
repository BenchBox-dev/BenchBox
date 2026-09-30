"""Targeted cross-dialect rewrites for TPC-Havoc query variants."""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from benchbox.core.tpchavoc.cloud_compat import rewrite_cloud_variant

POSTGRES_ALIAS_VARIANT_IDS = frozenset({"3_v7", "4_v7", "5_v7", "7_v7", "9_v7", "10_v7", "11_v7"})
POSTGRES_QUALIFIED_COLUMNS: dict[str, dict[str, str]] = {
    "2_v5": {"ps_partkey": "partsupp", "ps_supplycost": "partsupp"},
    "17_v2": {"l_partkey": "lineitem", "l_quantity": "lineitem", "l_extendedprice": "lineitem"},
}
POSTGRES_DUAL_VARIANT_IDS = frozenset({"17_v4"})
CLICKHOUSE_FILTER_VARIANT_IDS = frozenset({"1_v6", "12_v7"})
DATAFUSION_EMPTY_GROUP_VARIANT_IDS = frozenset({"6_v2", "14_v2"})
_CLOUD_DIALECTS = frozenset({"bigquery", "databricks", "snowflake"})
_POSTGRES_DIALECTS = frozenset({"postgres", "postgresql"})


def rewrite_dialect_variant(query_id: str, query: str, target_dialect: str) -> str:
    """Preserve variant semantics where a target dialect rejects the translated shape."""
    target = target_dialect.lower()
    if target in _CLOUD_DIALECTS:
        return rewrite_cloud_variant(query_id, query, target)
    if target == "clickhouse" and query_id in CLICKHOUSE_FILTER_VARIANT_IDS:
        return _rewrite_clickhouse_filters(query)
    if target == "datafusion" and query_id in DATAFUSION_EMPTY_GROUP_VARIANT_IDS:
        return _drop_empty_grouping(query)
    if target in _POSTGRES_DIALECTS:
        if query_id in POSTGRES_ALIAS_VARIANT_IDS:
            query = _inline_postgres_select_aliases(query)
        if columns := POSTGRES_QUALIFIED_COLUMNS.get(query_id):
            query = _qualify_postgres_columns(query, columns)
        if query_id in POSTGRES_DUAL_VARIANT_IDS:
            query = _rewrite_postgres_dual(query)
    return query


def _inline_postgres_select_aliases(query: str) -> str:
    """Replace PostgreSQL-illegal HAVING/WHERE select aliases with their expressions."""
    tree = sqlglot.parse_one(query, read="postgres")
    for select in tree.find_all(exp.Select):
        aliases = {
            projection.alias: projection.this
            for projection in select.expressions
            if isinstance(projection, exp.Alias) and projection.alias
        }
        if not aliases:
            continue
        for clause_name in ("having", "where"):
            clause = select.args.get(clause_name)
            if clause is None:
                continue
            for column in list(clause.find_all(exp.Column)):
                if column.table or column.name not in aliases:
                    continue
                if column.find_ancestor(exp.Select) is select:
                    column.replace(aliases[column.name].copy())
    return tree.sql(dialect="postgres")


def _qualify_postgres_columns(query: str, columns: dict[str, str]) -> str:
    """Qualify variant columns whose unqualified names collide after translation."""
    tree = sqlglot.parse_one(query, read="postgres")
    for column in tree.find_all(exp.Column):
        if not column.table and (table := columns.get(column.name)):
            column.set("table", exp.to_identifier(table))
    return tree.sql(dialect="postgres")


def _rewrite_postgres_dual(query: str) -> str:
    """Replace the generated one-row SELECT source with an explicit VALUES relation."""
    tree = sqlglot.parse_one(query, read="postgres")
    replacement = sqlglot.parse_one("SELECT * FROM (VALUES (1)) AS dual(dual_col)", read="postgres").args["from_"].this
    for subquery in tree.find_all(exp.Subquery):
        inner = subquery.this
        if subquery.alias != "dual" or not isinstance(inner, exp.Select) or len(inner.expressions) != 1:
            continue
        expression = inner.expressions[0]
        if isinstance(expression, exp.Literal) and expression.this == "1" and not expression.is_string:
            subquery.replace(replacement.copy())
    return tree.sql(dialect="postgres")


def _rewrite_clickhouse_filters(query: str) -> str:
    """Replace aggregate FILTER clauses with ClickHouse aggregate combinators."""
    tree = sqlglot.parse_one(query, read="clickhouse")
    return tree.transform(_clickhouse_filter_node).sql(dialect="clickhouse")


def _clickhouse_filter_node(node: exp.Expression) -> exp.Expression:
    if not isinstance(node, exp.Filter):
        return node
    aggregate = node.this
    condition = node.expression.this.copy()
    if isinstance(aggregate, exp.Count) and isinstance(aggregate.this, exp.Star):
        return exp.Anonymous(this="countIf", expressions=[condition])
    combinator = {exp.Sum: "sumOrNullIf", exp.Avg: "avgOrNullIf"}.get(type(aggregate))
    if combinator is None:
        raise NotImplementedError(
            f"ClickHouse FILTER rewrite handles only COUNT(*), SUM, and AVG; got {type(aggregate).__name__}. "
            "Extend the combinator map before scoping this variant."
        )
    return exp.Anonymous(this=combinator, expressions=[aggregate.this.copy(), condition])


def _drop_empty_grouping(query: str) -> str:
    """Drop GROUP BY () while retaining global aggregate and HAVING semantics."""
    tree = sqlglot.parse_one(query, read="postgres")
    for select in tree.find_all(exp.Select):
        group = select.args.get("group")
        if group and len(group.expressions) == 1:
            only = group.expressions[0]
            if isinstance(only, exp.Tuple) and not only.expressions:
                select.set("group", None)
    return tree.sql(dialect="postgres")


__all__ = [
    "CLICKHOUSE_FILTER_VARIANT_IDS",
    "DATAFUSION_EMPTY_GROUP_VARIANT_IDS",
    "POSTGRES_ALIAS_VARIANT_IDS",
    "POSTGRES_DUAL_VARIANT_IDS",
    "POSTGRES_QUALIFIED_COLUMNS",
    "rewrite_dialect_variant",
]
