"""DuckDB execution-filter rules for write_primitives operation gaps."""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision, FailureMode, SkipQueryPayload, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

DUCKDB_WRITE_PRIMITIVES_CATEGORY_SKIPS = {
    "merge": "DuckDB 1.3.2 rejects the catalog's MERGE statements; keep them explicit skips until the bundled driver supports MERGE.",
}

DUCKDB_WRITE_PRIMITIVES_OPERATION_SKIPS = {
    "bulk_load_upsert_mode": DUCKDB_WRITE_PRIMITIVES_CATEGORY_SKIPS["merge"],
}

for _query_id, _reason in DUCKDB_WRITE_PRIMITIVES_OPERATION_SKIPS.items():
    REGISTRY.register(
        CompatibilityDecision(
            rule_id=f"execution_filter.duckdb.write_primitives.{_query_id}",
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
        benchmark="write_primitives",
        query_id=_query_id,
    )
