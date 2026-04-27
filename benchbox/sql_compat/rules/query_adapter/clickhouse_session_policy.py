"""ClickHouse session policy rules for Phase.QUERY_ADAPTER.

TPC-DS Q23a, Q23b, and Q87 have unaliased inner subqueries that ClickHouse
rejects unless joined_subquery_requires_alias=0 is active.

AST-based alias injection via sqlglot is not safe for these queries - the
regex-based approach in ClickHouseQueryTransformer.add_subquery_aliases() was
disabled because it corrupts Q23 (splits GROUP BY out of its owning subquery)
and inserts aliases inside Q87's EXCEPT/INTERSECT set operations. The session
setting disables the requirement without touching the SQL text.
"""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import (
    CompatibilityDecision,
    FailureMode,
    SetSessionPolicyPayload,
    SupportLevel,
)
from benchbox.sql_compat.registry import REGISTRY

_P = Phase.QUERY_ADAPTER
_B = "tpcds"

_SETTING: tuple[tuple[str, str], ...] = (("joined_subquery_requires_alias", "0"),)
_REASON = (
    "ClickHouse requires explicit aliases on all FROM/JOIN subqueries; "
    "AST-based injection is unsafe for these queries (corrupts Q23 GROUP BY, "
    "inserts aliases inside Q87 EXCEPT/INTERSECT). "
    "Session setting joined_subquery_requires_alias=0 disables the requirement."
)

for _qid in ("23a", "23b", "87"):
    REGISTRY.register(
        CompatibilityDecision(
            rule_id=f"query_adapter.clickhouse.tpcds.q{_qid}_joined_subquery_alias_policy",
            action=CompatAction.SET_SESSION_POLICY,
            support_level=SupportLevel.REWRITTEN,  # SQL unchanged; executor behavior adapted via setting
            failure_mode=FailureMode.UNSUPPORTED_FEATURE,
            payload=SetSessionPolicyPayload(
                settings=_SETTING,
                issue_url=None,  # TODO: link GitHub issue documenting the sqlglot AST gap
            ),
            reason=_REASON,
        ),
        _P,
        "clickhouse",
        benchmark=_B,
        query_id=_qid,
    )
