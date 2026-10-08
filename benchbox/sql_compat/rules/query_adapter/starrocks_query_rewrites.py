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

REGISTRY.register(
    CompatibilityDecision(
        rule_id="query_adapter.starrocks.all.inject_subquery_aliases",
        action=CompatAction.REWRITE_QUERY,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=RewriteQueryPayload(
            transformer_id="starrocks_subquery_alias_injector",
            description="StarRocks requires aliases on all FROM/JOIN derived tables; inject AS _sqN aliases for unaliased subqueries",
        ),
        reason=(
            "StarRocks inherits MySQL's requirement that every derived table carries an alias. "
            "Unaliased subqueries produce a syntax error at parse time."
        ),
    ),
    Phase.QUERY_ADAPTER,
    "starrocks",
)
