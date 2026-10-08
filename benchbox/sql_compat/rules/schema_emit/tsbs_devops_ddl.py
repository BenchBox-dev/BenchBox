from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import (
    CompatibilityDecision,
    FailureMode,
    RewriteDDLPayload,
    SupportLevel,
)
from benchbox.sql_compat.registry import REGISTRY

REGISTRY.register(
    CompatibilityDecision(
        rule_id="schema_emit.clickhouse.tsbs_devops.all.mergetree_ddl",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=RewriteDDLPayload(
            transformer_id="tsbs_devops_clickhouse_ddl",
            description=(
                "Append ENGINE = MergeTree(), ORDER BY, and optional PARTITION BY toYYYYMMDD(col) "
                "to every TSBS DevOps CREATE TABLE for ClickHouse"
            ),
        ),
        reason=(
            "ClickHouse requires an explicit table engine and ORDER BY clause on every table. "
            "Standard CREATE TABLE without ENGINE = MergeTree() is rejected at parse time."
        ),
    ),
    Phase.SCHEMA_EMIT,
    "clickhouse",
    benchmark="tsbs_devops",
)


REGISTRY.register(
    CompatibilityDecision(
        rule_id="schema_emit.timescale.tsbs_devops.all.hypertable_ddl",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=RewriteDDLPayload(
            transformer_id="tsbs_devops_timescale_hypertable",
            description=(
                "Append SELECT create_hypertable(table, 'time', chunk_time_interval, if_not_exists) "
                "after CREATE TABLE for all non-tags TSBS DevOps tables on TimescaleDB"
            ),
        ),
        reason=(
            "TimescaleDB partitions time-series tables as hypertables via create_hypertable(). "
            "Without this call the table is a plain PostgreSQL table with no time-based chunking."
        ),
    ),
    Phase.SCHEMA_EMIT,
    "timescale",
    benchmark="tsbs_devops",
)


_NATIVE_TAGS = CompatibilityDecision(
    rule_id="schema_emit.timescale.tsbs_devops.tags.native_ddl",
    action=CompatAction.NATIVE,
    support_level=SupportLevel.NATIVE,
    failure_mode=FailureMode.NONE,
    payload=None,
    reason=(
        "The tags table stores host metadata, not time-series data. "
        "It must not be converted to a TimescaleDB hypertable. "
        "This tier-1 rule overrides the benchmark-wide REWRITE_DDL rule above."
    ),
)

REGISTRY.register(
    _NATIVE_TAGS,
    Phase.SCHEMA_EMIT,
    "timescale",
    benchmark="tsbs_devops",
    query_id="tags",
)
