"""DuckDB execution-filter rules for transaction_primitives operation gaps."""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision, FailureMode, SkipQueryPayload, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

DUCKDB_TRANSACTION_PRIMITIVES_OPERATION_SKIPS = {
    "transaction_savepoint_nested": "DuckDB rejects SAVEPOINT syntax in transaction_primitives operations.",
    "transaction_savepoint_deep_nesting": "DuckDB rejects SAVEPOINT syntax in transaction_primitives operations.",
    "transaction_isolation_read_committed": "DuckDB rejects explicit SET TRANSACTION ISOLATION LEVEL syntax.",
    "transaction_isolation_repeatable_read": "DuckDB rejects explicit SET TRANSACTION ISOLATION LEVEL syntax.",
    "transaction_isolation_serializable": "DuckDB rejects explicit SET TRANSACTION ISOLATION LEVEL syntax.",
}

for _query_id, _reason in DUCKDB_TRANSACTION_PRIMITIVES_OPERATION_SKIPS.items():
    REGISTRY.register(
        CompatibilityDecision(
            rule_id=f"execution_filter.duckdb.transaction_primitives.{_query_id}",
            action=CompatAction.SKIP_QUERY,
            support_level=SupportLevel.SKIPPED_QUERY,
            failure_mode=FailureMode.UNSUPPORTED_FEATURE,
            payload=SkipQueryPayload(
                reason=f"{_reason} Evidence: DuckDB 1.3.2 local parser verification on 2026-05-29.",
                query_id=_query_id,
            ),
            reason=_reason,
        ),
        Phase.EXECUTION_FILTER,
        "duckdb",
        benchmark="transaction_primitives",
        query_id=_query_id,
    )
