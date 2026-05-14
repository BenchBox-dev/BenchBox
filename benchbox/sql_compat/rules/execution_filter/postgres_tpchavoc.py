"""PostgreSQL-family execution-filter rules for unsupported TPC-Havoc variants."""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision, FailureMode, SkipQueryPayload, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

POSTGRES_TPCHAVOC_SKIPS: dict[str, str] = {
    "1_v7": "PostgreSQL-family engines do not provide DuckDB's `LIST()` aggregate used by this variant.",
    "2_v5": "PostgreSQL-family engines report ambiguous `ps_partkey` resolution for this variant shape.",
    "3_v7": "PostgreSQL-family engines do not allow the select-list alias `revenue` in HAVING.",
    "4_v7": "PostgreSQL-family engines do not allow the select-list alias `order_count` in HAVING.",
    "5_v7": "PostgreSQL-family engines do not allow the select-list alias `revenue` in HAVING.",
    "5_v9": "PostgreSQL-family engines reject aggregate expressions inside window definitions.",
    "7_v7": "PostgreSQL-family engines do not allow the select-list alias `revenue` in HAVING.",
    "7_v9": "PostgreSQL-family engines reject aggregate expressions inside window definitions.",
    "9_v7": "PostgreSQL-family engines do not allow the select-list alias `sum_profit` in HAVING.",
    "9_v9": "PostgreSQL-family engines reject aggregate expressions inside window definitions.",
    "10_v7": "PostgreSQL-family engines do not allow the select-list alias `revenue` in HAVING.",
    "10_v9": "PostgreSQL-family engines reject aggregate expressions inside window definitions.",
    "11_v7": "PostgreSQL-family engines do not allow the select-list alias `value` in WHERE.",
    "11_v9": "PostgreSQL-family engines reject this window expression in WHERE.",
    "13_v9": "PostgreSQL-family engines reject aggregate expressions inside window definitions.",
    "17_v2": "PostgreSQL-family engines report ambiguous `l_partkey` resolution for this variant shape.",
    "17_v4": "PostgreSQL-family engines do not provide Oracle's `dual` table.",
}

_POSTGRES_TPCHAVOC_PLATFORMS = ("pg-duckdb", "pg-mooncake", "timescaledb")

for _platform in _POSTGRES_TPCHAVOC_PLATFORMS:
    for _query_id, _reason in POSTGRES_TPCHAVOC_SKIPS.items():
        REGISTRY.register(
            CompatibilityDecision(
                rule_id=f"execution_filter.{_platform}.tpchavoc.{_query_id}",
                action=CompatAction.SKIP_QUERY,
                support_level=SupportLevel.SKIPPED_QUERY,
                failure_mode=FailureMode.UNSUPPORTED_FEATURE,
                payload=SkipQueryPayload(
                    reason=(
                        f"{_reason} Evidence: 2026-05-13 enabled-platform UAT reported this stable "
                        "TPC-Havoc variant failure on PostgreSQL-family SQL execution."
                    ),
                    query_id=_query_id,
                ),
                reason=_reason,
            ),
            Phase.EXECUTION_FILTER,
            _platform,
            benchmark="tpchavoc",
            query_id=_query_id,
        )
