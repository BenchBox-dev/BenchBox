"""Cloud TPC-Havoc variants with unsupported engine-specific constructs."""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision, FailureMode, SkipQueryPayload, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

CLOUD_TPCHAVOC_SKIPS: dict[str, dict[str, str]] = {
    "bigquery": {
        # 1_v7 has a native-array rewrite (cloud_compat._rewrite_array_aggregation)
        # awaiting a live compile check on BigQuery before the skip is lifted.
        "1_v7": "BigQuery does not support DuckDB LIST aggregates and LIST lambda functions in this variant.",
        "2_v2": "BigQuery rejects the correlated scalar subquery in this grouped variant.",
    },
    # Snowflake 2_v2 fails live compilation (002031/42601: unsupported
    # subquery type, verified 2026-09-26 on tpchavoc SF0.01 via EXPLAIN USING
    # TEXT through the adapter query path); the sqlglot parse check cannot
    # catch this engine-side limit, so the skip stays until a rewrite avoids
    # the correlated scalar subquery and compiles live on Snowflake.
    # 1_v7 likewise keeps its skip until _rewrite_array_aggregation compiles
    # live on Snowflake.
    "snowflake": {
        "1_v7": "Snowflake does not support DuckDB LIST aggregates and LIST lambda functions in this variant.",
        "2_v2": "Snowflake rejects the correlated scalar subquery in this grouped variant.",
    },
    # Databricks 1_v7 keeps its skip until _rewrite_array_aggregation compiles
    # live on Databricks.
    "databricks": {
        "1_v7": "Databricks SQL has array aggregation but not DuckDB's LIST_SUM and LIST_ZIP functions used here.",
    },
}

for _platform, _skips in CLOUD_TPCHAVOC_SKIPS.items():
    for _query_id, _reason in _skips.items():
        REGISTRY.register(
            CompatibilityDecision(
                rule_id=f"execution_filter.{_platform}.tpchavoc.{_query_id}",
                action=CompatAction.SKIP_QUERY,
                support_level=SupportLevel.SKIPPED_QUERY,
                failure_mode=FailureMode.UNSUPPORTED_FEATURE,
                payload=SkipQueryPayload(reason=_reason, query_id=_query_id),
                reason=_reason,
            ),
            Phase.EXECUTION_FILTER,
            _platform,
            benchmark="tpchavoc",
            query_id=_query_id,
        )
