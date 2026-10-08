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
        rule_id="schema_emit.clickhouse.nyctaxi.all.mergetree_ddl",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=RewriteDDLPayload(
            transformer_id="nyctaxi_clickhouse_ddl",
            description=(
                "Append ENGINE = MergeTree(), ORDER BY, and optional PARTITION BY toYYYYMM "
                "to every NYC Taxi CREATE TABLE for ClickHouse"
            ),
        ),
        reason=(
            "ClickHouse requires an explicit table engine and ORDER BY clause on every table. "
            "Standard CREATE TABLE without ENGINE = MergeTree() is rejected at parse time."
        ),
    ),
    Phase.SCHEMA_EMIT,
    "clickhouse",
    benchmark="nyctaxi",
)


_POSTGRES_DDL = CompatibilityDecision(
    rule_id="schema_emit.postgres.nyctaxi.all.range_partition_ddl",
    action=CompatAction.REWRITE_DDL,
    support_level=SupportLevel.REWRITTEN,
    failure_mode=FailureMode.UNSUPPORTED_FEATURE,
    payload=RewriteDDLPayload(
        transformer_id="nyctaxi_postgres_partition_ddl",
        description=(
            "Rewrite closing ) to ) PARTITION BY RANGE (partition_col) "
            "for NYC Taxi tables that carry a partition_by definition under PostgreSQL"
        ),
    ),
    reason=(
        "PostgreSQL native table partitioning requires PARTITION BY RANGE declared inline in "
        "CREATE TABLE.  Tables with a partition_by field in the schema definition are partitioned "
        "on that column; tables without are emitted as standard CREATE TABLE."
    ),
)

REGISTRY.register(
    _POSTGRES_DDL,
    Phase.SCHEMA_EMIT,
    "postgres",
    benchmark="nyctaxi",
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="schema_emit.postgresql.nyctaxi.all.range_partition_ddl",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=RewriteDDLPayload(
            transformer_id="nyctaxi_postgres_partition_ddl",
            description=(
                "Rewrite closing ) to ) PARTITION BY RANGE (partition_col) "
                "for NYC Taxi tables that carry a partition_by definition under PostgreSQL"
            ),
        ),
        reason=(
            "Alias dialect name 'postgresql' maps to the same PostgreSQL partitioning transform "
            "as 'postgres'.  Registered separately because the context carries the raw dialect string."
        ),
    ),
    Phase.SCHEMA_EMIT,
    "postgresql",
    benchmark="nyctaxi",
)


REGISTRY.register(
    CompatibilityDecision(
        rule_id="schema_emit.timescale.nyctaxi.all.range_partition_ddl",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=RewriteDDLPayload(
            transformer_id="nyctaxi_postgres_partition_ddl",
            description=(
                "Rewrite closing ) to ) PARTITION BY RANGE (partition_col) "
                "for NYC Taxi tables that carry a partition_by definition under TimescaleDB"
            ),
        ),
        reason=(
            "TimescaleDB is built on PostgreSQL and inherits its PARTITION BY RANGE syntax. "
            "The same transformer applies for partitioned tables."
        ),
    ),
    Phase.SCHEMA_EMIT,
    "timescale",
    benchmark="nyctaxi",
)
