"""Spark query rewrite rules for Phase.QUERY_ADAPTER.

Spark rejects three TPC-Havoc variant shapes at parse or analysis time:

- Correlated scalar subqueries in the SELECT list of an aggregated query
  (``SCALAR_SUBQUERY_IS_IN_GROUP_BY_OR_AGGREGATE_FUNCTION``). The scalar is
  correlated on the GROUP BY keys and therefore constant per group, so the
  transformer wraps it in ``first()`` without changing semantics.
- Empty grouping (``GROUP BY ()``), which the Spark parser rejects. Dropping
  the empty grouping keeps single-group aggregate semantics.
- The ``(SELECT 1) AS dual`` UNION ALL leg, which carries no explicit column
  alias. The transformer adds one.
"""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import (
    CompatibilityDecision,
    FailureMode,
    RewriteQueryPayload,
    SupportLevel,
)
from benchbox.sql_compat.registry import REGISTRY

_P = Phase.QUERY_ADAPTER
_B = "tpchavoc"

# (query_id, rule_slug, description)
_REWRITES = [
    (
        "1_v1",
        "q01_scalar_group_by_first",
        "Spark rejects the correlated scalar subquery in this aggregated SELECT list; wrap it in first()",
    ),
    (
        "3_v1",
        "q03_scalar_group_by_first",
        "Spark rejects the correlated scalar subquery in this aggregated SELECT list; wrap it in first()",
    ),
    (
        "6_v2",
        "q06_group_by_empty_drop",
        "Spark parser rejects the empty GROUP BY () in this variant; drop it",
    ),
    (
        "7_v1",
        "q07_scalar_group_by_first",
        "Spark rejects the correlated scalar subquery in this aggregated SELECT list; wrap it in first()",
    ),
    (
        "8_v1",
        "q08_scalar_group_by_first",
        "Spark rejects the correlated scalar subqueries in this aggregated SELECT list; wrap them in first()",
    ),
    (
        "9_v1",
        "q09_scalar_group_by_first",
        "Spark rejects the correlated scalar subquery in this aggregated SELECT list; wrap it in first()",
    ),
    (
        "10_v1",
        "q10_scalar_group_by_first",
        "Spark rejects the correlated scalar subquery in this aggregated SELECT list; wrap it in first()",
    ),
    (
        "12_v1",
        "q12_scalar_group_by_first",
        "Spark rejects the correlated scalar subqueries in this aggregated SELECT list; wrap them in first()",
    ),
    (
        "14_v2",
        "q14_group_by_empty_drop",
        "Spark parser rejects the empty GROUP BY () in this variant; drop it",
    ),
    (
        "16_v1",
        "q16_scalar_group_by_first",
        "Spark rejects the correlated scalar subquery in this aggregated SELECT list; wrap it in first()",
    ),
    (
        "17_v4",
        "q17_dual_column_alias",
        "Spark-Connect engines need an explicit column alias on the (SELECT 1) dual leg; add one",
    ),
]

for _qid, _slug, _reason in _REWRITES:
    REGISTRY.register(
        CompatibilityDecision(
            rule_id=f"query_adapter.spark.tpchavoc.{_slug}",
            action=CompatAction.REWRITE_QUERY,
            support_level=SupportLevel.REWRITTEN,
            failure_mode=FailureMode.UNSUPPORTED_FEATURE,
            payload=RewriteQueryPayload(
                transformer_id="spark_tpchavoc_query_transformer",
                description=_reason,
            ),
            reason=_reason,
        ),
        _P,
        "spark",
        benchmark=_B,
        query_id=_qid,
    )
