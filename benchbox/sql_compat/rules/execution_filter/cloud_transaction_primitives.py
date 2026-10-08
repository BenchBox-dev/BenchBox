from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision, FailureMode, SkipQueryPayload, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

_SAVEPOINT = "{engine} has no SAVEPOINT statement."
_ISOLATION = "{engine} rejects SET TRANSACTION ISOLATION LEVEL."
_TEMP_TABLE = (
    "BigQuery runs each multi-statement script as chained single-statement jobs, "
    "so a TEMP TABLE created in one statement is invisible to the next."
)

_OPERATIONS = {
    "transaction_savepoint_nested": _SAVEPOINT,
    "transaction_savepoint_deep_nesting": _SAVEPOINT,
    "transaction_isolation_read_committed": _ISOLATION,
    "transaction_isolation_repeatable_read": _ISOLATION,
    "transaction_isolation_serializable": _ISOLATION,
}

_BIGQUERY_ONLY_OPERATIONS = {
    "transaction_create_temp_table": _TEMP_TABLE,
}

SNOWFLAKE_TRANSACTION_PRIMITIVES_OPERATION_SKIPS = {
    query_id: reason.format(engine="Snowflake") for query_id, reason in _OPERATIONS.items()
}
BIGQUERY_TRANSACTION_PRIMITIVES_OPERATION_SKIPS = {
    query_id: reason.format(engine="BigQuery") for query_id, reason in _OPERATIONS.items()
} | dict(_BIGQUERY_ONLY_OPERATIONS)

for _platform, _skips in (
    ("snowflake", SNOWFLAKE_TRANSACTION_PRIMITIVES_OPERATION_SKIPS),
    ("bigquery", BIGQUERY_TRANSACTION_PRIMITIVES_OPERATION_SKIPS),
):
    for _query_id, _reason in _skips.items():
        REGISTRY.register(
            CompatibilityDecision(
                rule_id=f"execution_filter.{_platform}.transaction_primitives.{_query_id}",
                action=CompatAction.SKIP_QUERY,
                support_level=SupportLevel.SKIPPED_QUERY,
                failure_mode=FailureMode.UNSUPPORTED_FEATURE,
                payload=SkipQueryPayload(
                    reason=f"{_reason} Evidence: live {_platform} probe on 2026-09-26.",
                    query_id=_query_id,
                ),
                reason=_reason,
            ),
            Phase.EXECUTION_FILTER,
            _platform,
            benchmark="transaction_primitives",
            query_id=_query_id,
        )
