"""Targeted SQL rewrites for TPC-Havoc cloud query variants."""

from __future__ import annotations

import sqlglot
from sqlglot import exp

_BIGQUERY_FROMLESS_IDS = frozenset({"7_v8", "12_v8", "13_v8", "18_v4"})
_BIGQUERY_HAVING_COLUMNS = {"5_v4": "revenue", "11_v4": "value"}
_SNOWFLAKE_EMPTY_GROUP_IDS = frozenset({"6_v2", "14_v2"})
_ARRAY_AGGREGATION_ID = "1_v7"
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
    if query_id == _ARRAY_AGGREGATION_ID:
        return _rewrite_array_aggregation(query, target_dialect)
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


def _rewrite_array_aggregation(query: str, target_dialect: str) -> str:
    """Render q1_v7's collected arrays with functions native to each cloud engine."""
    if target_dialect not in {"bigquery", "databricks", "snowflake"}:
        return query

    tree = sqlglot.parse_one(query, read=target_dialect)
    tree = tree.transform(
        lambda node: _ordered_array(node.expressions[0], target_dialect) if isinstance(node, exp.List) else node
    )

    projection_sql = _array_projection_sql(target_dialect)
    projections = [
        sqlglot.parse_one(f"SELECT {projection}", read=target_dialect).expressions[0] for projection in projection_sql
    ]
    tree.set("expressions", [*tree.expressions[:2], *projections])
    return tree.sql(dialect=target_dialect)


def _ordered_array(value: exp.Expression, target_dialect: str) -> exp.Expression:
    """Collect values in lineitem key order so separately reduced arrays stay aligned."""
    rendered = value.sql(dialect=target_dialect)
    if target_dialect == "snowflake":
        expression = f"ARRAY_AGG({rendered}) WITHIN GROUP (ORDER BY l_orderkey, l_linenumber)"
    elif target_dialect == "databricks":
        expression = (
            "TRANSFORM(SORT_ARRAY(COLLECT_LIST(NAMED_STRUCT("
            f"'orderkey', l_orderkey, 'linenumber', l_linenumber, 'value', {rendered}))), row -> row.value)"
        )
    else:
        expression = f"ARRAY_AGG({rendered} ORDER BY l_orderkey, l_linenumber)"
    return sqlglot.parse_one(f"SELECT {expression}", read=target_dialect).expressions[0]


def _array_projection_sql(target_dialect: str) -> tuple[str, ...]:
    if target_dialect == "snowflake":
        zero = "CAST(0 AS NUMBER(38, 12))"

        def reduce_array(expression: str) -> str:
            return f"REDUCE({expression}, {zero}, (acc, x) -> acc + x)"

        sum_qty = reduce_array("quantities")
        sum_price = reduce_array("prices")
        sum_disc_price = reduce_array(
            "TRANSFORM(ARRAY_GENERATE_RANGE(0, ARRAY_SIZE(prices)), i -> prices[i] * (1 - discounts[i]))"
        )
        sum_charge = reduce_array(
            "TRANSFORM(ARRAY_GENERATE_RANGE(0, ARRAY_SIZE(prices)), "
            "i -> prices[i] * (1 - discounts[i]) * (1 + taxes[i]))"
        )
        size = "ARRAY_SIZE"
    elif target_dialect == "databricks":
        zero = "CAST(0 AS DOUBLE)"

        def reduce_array(expression: str) -> str:
            return f"AGGREGATE({expression}, {zero}, (acc, x) -> acc + x)"

        sum_qty = reduce_array("TRANSFORM(quantities, x -> CAST(x AS DOUBLE))")
        sum_price = reduce_array("TRANSFORM(prices, x -> CAST(x AS DOUBLE))")
        sum_disc_price = reduce_array(
            "ZIP_WITH(prices, discounts, (price, discount) -> CAST(price AS DOUBLE) * (1 - CAST(discount AS DOUBLE)))"
        )
        sum_charge = reduce_array(
            "ZIP_WITH(ZIP_WITH(prices, discounts, "
            "(price, discount) -> CAST(price AS DOUBLE) * (1 - CAST(discount AS DOUBLE))), taxes, "
            "(discounted, tax) -> discounted * (1 + CAST(tax AS DOUBLE)))"
        )
        size = "SIZE"
    else:
        sum_qty = "(SELECT SUM(value) FROM UNNEST(quantities) AS value)"
        sum_price = "(SELECT SUM(value) FROM UNNEST(prices) AS value)"
        sum_disc_price = (
            "(SELECT SUM(price * (1 - discounts[SAFE_OFFSET(position)])) "
            "FROM UNNEST(prices) AS price WITH OFFSET AS position)"
        )
        sum_charge = (
            "(SELECT SUM(price * (1 - discounts[SAFE_OFFSET(position)]) * "
            "(1 + taxes[SAFE_OFFSET(position)])) "
            "FROM UNNEST(prices) AS price WITH OFFSET AS position)"
        )
        size = "ARRAY_LENGTH"

    if target_dialect == "bigquery":
        avg_qty = "(SELECT AVG(value) FROM UNNEST(quantities) AS value)"
        avg_price = "(SELECT AVG(value) FROM UNNEST(prices) AS value)"
        avg_disc = "(SELECT AVG(value) FROM UNNEST(discounts) AS value)"
    else:
        avg_qty = f"{sum_qty} / NULLIF({size}(quantities), 0)"
        avg_price = f"{sum_price} / NULLIF({size}(prices), 0)"
        avg_disc_sum = (
            reduce_array("TRANSFORM(discounts, x -> CAST(x AS DOUBLE))")
            if target_dialect == "databricks"
            else reduce_array("discounts")
        )
        avg_disc = f"{avg_disc_sum} / NULLIF({size}(discounts), 0)"

    return (
        f"{sum_qty} AS sum_qty",
        f"{sum_price} AS sum_base_price",
        f"{sum_disc_price} AS sum_disc_price",
        f"{sum_charge} AS sum_charge",
        f"{avg_qty} AS avg_qty",
        f"{avg_price} AS avg_price",
        f"{avg_disc} AS avg_disc",
        f"{size}(quantities) AS count_order",
    )


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
