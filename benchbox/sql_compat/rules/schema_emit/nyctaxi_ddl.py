"""NYC Taxi DDL compatibility rules for Phase.SCHEMA_EMIT.

_generate_create_table in core/nyctaxi/schema.py branches on dialect to emit
engine-specific DDL.  Three policy branches are registered here; the DuckDB
partition-comment branch is legitimate storage-layout rendering and is covered
by the @compat_local decorator on _generate_create_table.

  clickhouse              → REWRITE_DDL (tier-2): MergeTree + ORDER BY + PARTITION BY
  postgres / postgresql   → REWRITE_DDL (tier-2): PARTITION BY RANGE for partitioned tables
  timescale               → REWRITE_DDL (tier-2): PARTITION BY RANGE (timescale extends pg)
"""

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

# ---------------------------------------------------------------------------
# ClickHouse: ENGINE = MergeTree + ORDER BY + optional PARTITION BY toYYYYMM
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# PostgreSQL: PARTITION BY RANGE for tables that have a partition_by column
#
# W16 wiring note: _generate_create_table applies PARTITION BY RANGE only when
# time_partitioning AND "partition_by" in table_def. taxi_zones has no
# partition_by, so legacy will NOT rewrite it. The tier-2 rules below register
# REWRITE_DDL for all tables; the harness wiring in W16 must either:
#   (a) call harness with "REWRITE_DDL" only for tables where the rewrite fires, or
#   (b) add tier-1 NATIVE overrides for non-partitioned tables
# to avoid false shadow-mode divergence for taxi_zones.
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# TimescaleDB: same PARTITION BY RANGE transform (TimescaleDB extends PostgreSQL)
# ---------------------------------------------------------------------------

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
