"""DataFusion query rewrite rules for Phase.QUERY_ADAPTER.

TPC-H Q11, Q16, Q18, Q20 produce incorrect results under DataFusion due to
execution differences with HAVING scalar subqueries, NOT IN NULL semantics, IN
with HAVING, and nested correlated IN. DataFusionQueryTransformer rewrites each
into a semantically equivalent form that DataFusion executes correctly.
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
_B = "tpch"

# (query_id, rule_slug, description)
_REWRITES = [
    (
        "11",
        "q11_having_threshold_cte",
        "DataFusion miscomputes HAVING with scalar subquery threshold; extract threshold to CTE",
    ),
    (
        "16",
        "q16_not_in_to_not_exists",
        "DataFusion NOT IN with potential NULLs gives wrong results; rewrite to NOT EXISTS",
    ),
    (
        "18",
        "q18_in_having_to_exists",
        "DataFusion IN subquery with HAVING clause decorrelates incorrectly; rewrite to EXISTS wrapper",
    ),
    (
        "20",
        "q20_correlated_to_cte",
        "DataFusion nested correlated IN produces wrong results; rewrite using pre-aggregating CTEs",
    ),
]

for _qid, _slug, _reason in _REWRITES:
    REGISTRY.register(
        CompatibilityDecision(
            rule_id=f"query_adapter.datafusion.tpch.{_slug}",
            action=CompatAction.REWRITE_QUERY,
            support_level=SupportLevel.REWRITTEN,
            failure_mode=FailureMode.SILENT_CORRUPTION,
            payload=RewriteQueryPayload(
                transformer_id="datafusion_query_transformer",
                description=_reason,
            ),
            reason=_reason,
        ),
        _P,
        "datafusion",
        benchmark=_B,
        query_id=_qid,
    )
