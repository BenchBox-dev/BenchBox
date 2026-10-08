from __future__ import annotations

import re

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision, FailureMode, SkipQueryPayload, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_MERGE_INTO = re.compile(r"\bMERGE\s+INTO\b", re.IGNORECASE)

DUCKDB_WRITE_PRIMITIVES_MERGE_SKIP_REASON = (
    "DuckDB 1.3.2 rejects the catalog's MERGE INTO statements; keep them explicit skips until the "
    "bundled driver supports MERGE. Portable merge operations written as UPDATE/INSERT run normally."
)


def _has_merge_into(sql: str) -> bool:
    stripped = _BLOCK_COMMENT.sub(" ", sql)
    stripped = _LINE_COMMENT.sub(" ", stripped)
    stripped = _STRING_LITERAL.sub(" ", stripped)
    return _MERGE_INTO.search(stripped) is not None


def duckdb_write_primitive_skip_reason(operation, effective_sql: str | None = None) -> str | None:
    sql = effective_sql if effective_sql is not None else (getattr(operation, "write_sql", "") or "")
    if _has_merge_into(sql):
        return DUCKDB_WRITE_PRIMITIVES_MERGE_SKIP_REASON
    return None


def _register_merge_into_skips() -> None:
    try:
        from benchbox.core.write_primitives.catalog import load_write_primitives_catalog

        catalog = load_write_primitives_catalog()
    except Exception:
        return

    for op_id, operation in catalog.operations.items():
        if not _has_merge_into(getattr(operation, "write_sql", "") or ""):
            continue
        REGISTRY.register(
            CompatibilityDecision(
                rule_id=f"execution_filter.duckdb.write_primitives.{op_id}",
                action=CompatAction.SKIP_QUERY,
                support_level=SupportLevel.SKIPPED_QUERY,
                failure_mode=FailureMode.UNSUPPORTED_FEATURE,
                payload=SkipQueryPayload(
                    reason=(
                        f"{DUCKDB_WRITE_PRIMITIVES_MERGE_SKIP_REASON} "
                        "Evidence: DuckDB 1.3.2 local execution verification on 2026-06-30."
                    ),
                    query_id=op_id,
                ),
                reason=DUCKDB_WRITE_PRIMITIVES_MERGE_SKIP_REASON,
            ),
            Phase.EXECUTION_FILTER,
            "duckdb",
            benchmark="write_primitives",
            query_id=op_id,
        )


_register_merge_into_skips()
