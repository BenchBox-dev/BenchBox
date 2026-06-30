"""DuckDB execution-filter rules for write_primitives operation gaps."""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision, FailureMode, SkipQueryPayload, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

# Bundled DuckDB 1.3.2 rejects ``MERGE INTO``. The skip is gated on the presence of that token in
# an operation's write_sql rather than on the whole ``merge`` operation category, because the
# category also covers portable SCD Type 2 ops (merge_scd_type2_basic / _no_change /
# _new_keys_only) that are expressed as UPDATE + INSERT and which DuckDB runs and validates
# correctly. Token-gating keeps those portable ops executing and automatically covers any future
# MERGE INTO operation with no per-operation skip list to maintain.
#
# Evidence: DuckDB 1.3.2 local execution verification on 2026-06-30 — the 20 legacy MERGE INTO
# ops still raise a parser error, while the portable SCD Type 2 ops execute and validate green
# (tests/integration/test_write_primitives_duckdb.py -k scd2).
DUCKDB_MERGE_INTO_TOKEN = "MERGE INTO"

DUCKDB_WRITE_PRIMITIVES_MERGE_SKIP_REASON = (
    "DuckDB 1.3.2 rejects the catalog's MERGE INTO statements; keep them explicit skips until the "
    "bundled driver supports MERGE. Portable merge operations written as UPDATE/INSERT run normally."
)

# Operation-level skips keyed by id, for gaps that cannot be detected from the write_sql token.
DUCKDB_WRITE_PRIMITIVES_OPERATION_SKIPS = {
    "bulk_load_upsert_mode": DUCKDB_WRITE_PRIMITIVES_MERGE_SKIP_REASON,
}


def duckdb_write_primitive_skip_reason(operation) -> str | None:
    """Return a skip reason if ``operation`` cannot execute on bundled DuckDB, else ``None``.

    Gating on the ``MERGE INTO`` token rather than the broad ``merge`` category lets portable merge
    operations — e.g. the SCD Type 2 ops expressed as UPDATE + INSERT — run on DuckDB while genuine
    ``MERGE INTO`` statements continue to skip cleanly.
    """
    write_sql = (getattr(operation, "write_sql", "") or "").upper()
    if DUCKDB_MERGE_INTO_TOKEN in write_sql:
        return DUCKDB_WRITE_PRIMITIVES_MERGE_SKIP_REASON
    operation_id = getattr(operation, "id", None)
    if operation_id in DUCKDB_WRITE_PRIMITIVES_OPERATION_SKIPS:
        return DUCKDB_WRITE_PRIMITIVES_OPERATION_SKIPS[operation_id]
    return None


for _query_id, _reason in DUCKDB_WRITE_PRIMITIVES_OPERATION_SKIPS.items():
    REGISTRY.register(
        CompatibilityDecision(
            rule_id=f"execution_filter.duckdb.write_primitives.{_query_id}",
            action=CompatAction.SKIP_QUERY,
            support_level=SupportLevel.SKIPPED_QUERY,
            failure_mode=FailureMode.UNSUPPORTED_FEATURE,
            payload=SkipQueryPayload(
                reason=f"{_reason} Evidence: DuckDB 1.3.2 local execution verification on 2026-06-30.",
                query_id=_query_id,
            ),
            reason=_reason,
        ),
        Phase.EXECUTION_FILTER,
        "duckdb",
        benchmark="write_primitives",
        query_id=_query_id,
    )
