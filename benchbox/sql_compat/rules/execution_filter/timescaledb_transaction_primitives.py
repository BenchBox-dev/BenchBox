"""TimescaleDB execution-filter rules for transaction_primitives operation gaps."""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision, FailureMode, SkipQueryPayload, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

TIMESCALEDB_TRANSACTION_PRIMITIVES_OPERATION_SKIPS = {
    "transaction_isolation_repeatable_read": (
        "TimescaleDB rejects non-default transaction isolation changes once the benchmark operation wrapper has "
        "already executed statements on the connection."
    ),
    "transaction_isolation_serializable": (
        "TimescaleDB rejects non-default transaction isolation changes once the benchmark operation wrapper has "
        "already executed statements on the connection."
    ),
}

for _query_id, _reason in TIMESCALEDB_TRANSACTION_PRIMITIVES_OPERATION_SKIPS.items():
    REGISTRY.register(
        CompatibilityDecision(
            rule_id=f"execution_filter.timescaledb.transaction_primitives.{_query_id}",
            action=CompatAction.SKIP_QUERY,
            support_level=SupportLevel.SKIPPED_QUERY,
            failure_mode=FailureMode.UNSUPPORTED_FEATURE,
            payload=SkipQueryPayload(
                reason=f"{_reason} Evidence: TimescaleDB targeted UAT on 2026-05-13.",
                query_id=_query_id,
            ),
            reason=_reason,
        ),
        Phase.EXECUTION_FILTER,
        "timescaledb",
        benchmark="transaction_primitives",
        query_id=_query_id,
    )
