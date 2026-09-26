"""Targeted SQL rewrites for TPC-Havoc cloud query variants."""

from __future__ import annotations

import sqlglot
from sqlglot import exp

_BIGQUERY_FROMLESS_IDS = frozenset({"7_v8", "12_v8", "13_v8", "18_v4"})
_BIGQUERY_HAVING_COLUMNS = {"5_v4": "revenue", "11_v4": "value"}
_SNOWFLAKE_EMPTY_GROUP_IDS = frozenset({"6_v2", "14_v2"})
BIGQUERY_FILTER_IDS = frozenset(
    {
        "1_v6",
        "2_v7",
        "3_v7",
        "4_v7",
        "5_v7",
        "6_v7",
        "7_v7",
        "8_v7",
        "9_v7",
        "10_v7",
        "11_v7",
        "12_v7",
        "13_v7",
        "14_v7",
        "15_v7",
        "16_v7",
        "17_v7",
        "18_v7",
    }
)


def rewrite_cloud_variant(query_id: str, query: str, target_dialect: str) -> str:
    """Preserve variant semantics where the target rejects translated syntax."""
    if target_dialect == "databricks":
        from benchbox.core.tpchavoc.spark_query_transformer import SparkTPCHavocQueryTransformer

        if query_id in SparkTPCHavocQueryTransformer.known_variant_ids():
            return SparkTPCHavocQueryTransformer().transform(query, query_id)
        return query
    if target_dialect == "snowflake" and query_id in _SNOWFLAKE_EMPTY_GROUP_IDS:
        return query.replace(" GROUP BY ()", "", 1)
    if target_dialect != "bigquery":
        return query

    has_filter = " FILTER(" in query
    if not (has_filter or query_id in _BIGQUERY_FROMLESS_IDS or query_id in _BIGQUERY_HAVING_COLUMNS):
        if query_id == "3_v9":
            return query.replace("ORDER BY `l_orderkey` NULLS LAST", "ORDER BY `l_orderkey`")
        return query

    tree = sqlglot.parse_one(query, read="bigquery")
    if has_filter:
        tree = tree.transform(_rewrite_bigquery_filter)
    if query_id in _BIGQUERY_FROMLESS_IDS:
        one_row_source = sqlglot.parse_one("SELECT 1 FROM UNNEST([1])", read="bigquery").args["from_"]
        for select in tree.find_all(exp.Select):
            if select.args.get("where") is not None and select.args.get("from_") is None:
                select.set("from_", one_row_source.copy())
    if column_name := _BIGQUERY_HAVING_COLUMNS.get(query_id):
        for having in tree.find_all(exp.Having):
            for column in having.find_all(exp.Column):
                if column.name == column_name and not column.table:
                    column.set("table", exp.to_identifier("combined", quoted=True))
    return tree.sql(dialect="bigquery")


def _rewrite_bigquery_filter(node: exp.Expression) -> exp.Expression:
    if not isinstance(node, exp.Filter):
        return node
    aggregate = node.this.copy()
    condition = node.expression.this.copy()
    value = aggregate.this
    if isinstance(aggregate, exp.Count) and isinstance(value, exp.Star):
        return exp.CountIf(this=condition)
    if isinstance(value, exp.Distinct):
        distinct = value.copy()
        distinct.set(
            "expressions",
            [exp.If(this=condition, true=expression.copy(), false=exp.Null()) for expression in distinct.expressions],
        )
        aggregate.set("this", distinct)
    else:
        aggregate.set("this", exp.If(this=condition, true=value.copy(), false=exp.Null()))
    return aggregate
