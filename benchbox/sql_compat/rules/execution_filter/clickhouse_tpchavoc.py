from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision, FailureMode, SkipQueryPayload, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

CLICKHOUSE_TPCHAVOC_SKIPS: dict[str, str] = {
    "1_v7": "ClickHouse has no DuckDB `LIST` aggregate / `list_transform`/`list_zip` lambda forms this variant uses (`Syntax error` at the `->` lambda).",
    "1_v10": "ClickHouse rejects a GROUP BY whose key is a CASE aliased to the same name as a column it references (alias shadowing, Code 215 NOT_AN_AGGREGATE).",
    "3_v1": "ClickHouse does not support correlated subqueries in ORDER BY (Code 48 NOT_IMPLEMENTED).",
    "3_v9": "ClickHouse rejects a window function used in WHERE (Code 184 ILLEGAL_AGGREGATION).",
    "3_v10": "ClickHouse cannot SUM a `Variant(Decimal, Float64)` column produced by this variant's mixed-type CASE (Code 43 ILLEGAL_TYPE_OF_ARGUMENT).",
    "4_v7": "ClickHouse does not support correlated subqueries in an aggregate-function argument (Code 48 NOT_IMPLEMENTED).",
    "4_v10": "ClickHouse does not support correlated subqueries in an aggregate-function argument (Code 48 NOT_IMPLEMENTED).",
    "7_v1": "ClickHouse cannot execute this correlated revenue subquery (Code 1/48 correlated subquery planning failure).",
    "8_v1": "ClickHouse cannot execute the two correlated market-share subqueries (Code 1/48 correlated subquery planning failure).",
    "9_v1": "ClickHouse cannot execute this correlated profit subquery (Code 1/48 correlated subquery planning failure).",
    "5_v1": "ClickHouse does not support correlated subqueries in ORDER BY (Code 48 NOT_IMPLEMENTED).",
    "5_v4": "ClickHouse rejects an aggregate over a select-list-alias aggregate (nested aggregate, Code 184 ILLEGAL_AGGREGATION).",
    "5_v10": "ClickHouse cannot SUM a `Variant(Decimal, Float64)` column produced by this variant's mixed-type CASE (Code 43 ILLEGAL_TYPE_OF_ARGUMENT).",
    "10_v1": "ClickHouse does not support correlated subqueries in ORDER BY (Code 48 NOT_IMPLEMENTED).",
    "11_v4": "ClickHouse rejects an aggregate over a select-list-alias aggregate (nested aggregate, Code 184 ILLEGAL_AGGREGATION).",
    "13_v8": "ClickHouse cannot lower this variant's correlated subquery (CommonSubplan plan step, Code 48 NOT_IMPLEMENTED).",
    "14_v8": "ClickHouse does not support correlated subqueries in an aggregate-function argument (Code 48 NOT_IMPLEMENTED).",
    "16_v1": "ClickHouse does not support correlated subqueries in ORDER BY (Code 48 NOT_IMPLEMENTED).",
    "16_v4": "ClickHouse cannot lower this variant's correlated subquery (DelayedCreatingSets plan step, Code 48 NOT_IMPLEMENTED).",
    "17_v7": "ClickHouse does not support correlated subqueries in an aggregate-function argument (Code 48 NOT_IMPLEMENTED).",
    "17_v10": "ClickHouse does not support correlated subqueries in an aggregate-function argument (Code 48 NOT_IMPLEMENTED).",
}

_CLICKHOUSE_TPCHAVOC_PLATFORMS = ("clickhouse-local", "clickhouse-server", "clickhouse-cloud")

for _platform in _CLICKHOUSE_TPCHAVOC_PLATFORMS:
    for _query_id, _reason in CLICKHOUSE_TPCHAVOC_SKIPS.items():
        REGISTRY.register(
            CompatibilityDecision(
                rule_id=f"execution_filter.{_platform}.tpchavoc.{_query_id}",
                action=CompatAction.SKIP_QUERY,
                support_level=SupportLevel.SKIPPED_QUERY,
                failure_mode=FailureMode.UNSUPPORTED_FEATURE,
                payload=SkipQueryPayload(
                    reason=_reason,
                    query_id=_query_id,
                ),
                reason=_reason,
            ),
            Phase.EXECUTION_FILTER,
            _platform,
            benchmark="tpchavoc",
            query_id=_query_id,
        )
