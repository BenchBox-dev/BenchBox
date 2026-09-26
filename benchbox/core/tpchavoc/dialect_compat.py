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
_CLOUD_DIALECTS = frozenset({"bigquery", "databricks", "snowflake"})
_POSTGRES_DIALECTS = frozenset({"postgres", "postgresql"})


def rewrite_dialect_variant(query_id: str, query: str, target_dialect: str) -> str:
    """Preserve variant semantics where a target dialect rejects the translated shape."""
    target = target_dialect.lower()
    if target in _CLOUD_DIALECTS:
        return rewrite_cloud_variant(query_id, query, target)
    if target in _POSTGRES_DIALECTS:
        if query_id in POSTGRES_ALIAS_VARIANT_IDS:
            query = _inline_postgres_select_aliases(query)
        if columns := POSTGRES_QUALIFIED_COLUMNS.get(query_id):
            query = _qualify_postgres_columns(query, columns)
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


__all__ = ["POSTGRES_ALIAS_VARIANT_IDS", "POSTGRES_QUALIFIED_COLUMNS", "rewrite_dialect_variant"]
