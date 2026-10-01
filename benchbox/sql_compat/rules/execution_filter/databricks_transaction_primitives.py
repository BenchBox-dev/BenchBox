"""Databricks execution-filter rules for transaction_primitives operation gaps."""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision, FailureMode, SkipQueryPayload, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

_SAVEPOINT = "Databricks SQL multi-statement transactions do not support SAVEPOINT."
_ISOLATION = "Databricks SQL rejects SET TRANSACTION ISOLATION LEVEL."
_TRUNCATE = "Databricks SQL does not allow TRUNCATE TABLE inside a transaction (TRANSACTION_NOT_SUPPORTED.COMMAND)."
_TEMP_TABLE = (
    "Databricks SQL rejects CREATE TEMPORARY TABLE ... IF NOT EXISTS, and temporary views are not allowed inside "
    "a transaction (TRANSACTION_NOT_SUPPORTED.COMMAND)."
)

DATABRICKS_TRANSACTION_PRIMITIVES_OPERATION_SKIPS = {
    "transaction_savepoint_nested": _SAVEPOINT,
    "transaction_savepoint_deep_nesting": _SAVEPOINT,
    "transaction_isolation_read_committed": _ISOLATION,
    "transaction_isolation_repeatable_read": _ISOLATION,
    "transaction_isolation_serializable": _ISOLATION,
    "transaction_truncate_in_transaction": _TRUNCATE,
    "transaction_create_temp_table": _TEMP_TABLE,
}

for _query_id, _reason in DATABRICKS_TRANSACTION_PRIMITIVES_OPERATION_SKIPS.items():
    REGISTRY.register(
        CompatibilityDecision(
            rule_id=f"execution_filter.databricks.transaction_primitives.{_query_id}",
            action=CompatAction.SKIP_QUERY,
            support_level=SupportLevel.SKIPPED_QUERY,
            failure_mode=FailureMode.UNSUPPORTED_FEATURE,
            payload=SkipQueryPayload(
                reason=f"{_reason} Evidence: live Databricks SQL warehouse probe on 2026-09-26.",
                query_id=_query_id,
            ),
            reason=_reason,
        ),
        Phase.EXECUTION_FILTER,
        "databricks",
        benchmark="transaction_primitives",
        query_id=_query_id,
    )
