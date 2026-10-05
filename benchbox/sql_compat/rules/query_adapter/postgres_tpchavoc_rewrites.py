"""Document PostgreSQL-family TPC-Havoc query rewrites."""

from __future__ import annotations

from benchbox.core.tpchavoc.dialect_compat import (
    POSTGRES_ALIAS_VARIANT_IDS,
    POSTGRES_DUAL_VARIANT_IDS,
    POSTGRES_QUALIFIED_COLUMNS,
)
from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision, FailureMode, RewriteQueryPayload, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

for _platform in ("pg-duckdb", "pg-mooncake", "timescaledb"):
    for _query_id in POSTGRES_ALIAS_VARIANT_IDS:
        _reason = "Inline the aggregate expression where PostgreSQL rejects a SELECT alias in HAVING or WHERE"
        REGISTRY.register(
            CompatibilityDecision(
                rule_id=f"query_adapter.{_platform}.tpchavoc.{_query_id}.inline_select_alias",
                action=CompatAction.REWRITE_QUERY,
                support_level=SupportLevel.REWRITTEN,
                failure_mode=FailureMode.UNSUPPORTED_FEATURE,
                payload=RewriteQueryPayload(transformer_id="tpchavoc_dialect_rewriter", description=_reason),
                reason=_reason,
            ),
            Phase.QUERY_ADAPTER,
            _platform,
            benchmark="tpchavoc",
            query_id=_query_id,
        )
    for _query_id in POSTGRES_QUALIFIED_COLUMNS:
        _reason = "Qualify translated column references that are ambiguous to PostgreSQL"
        REGISTRY.register(
            CompatibilityDecision(
                rule_id=f"query_adapter.{_platform}.tpchavoc.{_query_id}.qualify_columns",
                action=CompatAction.REWRITE_QUERY,
                support_level=SupportLevel.REWRITTEN,
                failure_mode=FailureMode.UNSUPPORTED_FEATURE,
                payload=RewriteQueryPayload(transformer_id="tpchavoc_dialect_rewriter", description=_reason),
                reason=_reason,
            ),
            Phase.QUERY_ADAPTER,
            _platform,
            benchmark="tpchavoc",
            query_id=_query_id,
        )
    for _query_id in POSTGRES_DUAL_VARIANT_IDS:
        _reason = "Use an explicit VALUES relation instead of the generated dual-style source"
        REGISTRY.register(
            CompatibilityDecision(
                rule_id=f"query_adapter.{_platform}.tpchavoc.{_query_id}.values_source",
                action=CompatAction.REWRITE_QUERY,
                support_level=SupportLevel.REWRITTEN,
                failure_mode=FailureMode.UNSUPPORTED_FEATURE,
                payload=RewriteQueryPayload(transformer_id="tpchavoc_dialect_rewriter", description=_reason),
                reason=_reason,
            ),
            Phase.QUERY_ADAPTER,
            _platform,
            benchmark="tpchavoc",
            query_id=_query_id,
        )
