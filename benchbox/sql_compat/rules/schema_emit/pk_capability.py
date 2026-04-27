"""PRIMARY KEY capability rules for write_primitives lock-table DDL.

Registered at import time into the module-level REGISTRY singleton.
"""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import (
    CompatibilityDecision,
    FailureMode,
    PKCapabilityPayload,
    SupportLevel,
)
from benchbox.sql_compat.registry import REGISTRY

_B = "write_primitives"
_P = Phase.SCHEMA_EMIT

REGISTRY.register(
    CompatibilityDecision(
        rule_id="schema_emit.datafusion.write_primitives.pk_lock_table_unsupported",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.SKIPPED_DDL_FRAGMENT,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=PKCapabilityPayload(
            ddl_accepted=False,
            uniqueness_enforced=False,
            conditions=None,
            failure_mode_detail="DataFusion does not parse PRIMARY KEY in CREATE TABLE",
        ),
        reason="DataFusion does not support PRIMARY KEY syntax; skip lock table DDL",
    ),
    _P,
    "datafusion",
    benchmark=_B,
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="schema_emit.clickhouse.write_primitives.pk_lock_table_unsupported",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=PKCapabilityPayload(
            ddl_accepted=False,
            uniqueness_enforced=False,
            conditions=None,
            failure_mode_detail="ClickHouse PRIMARY KEY is part of MergeTree ENGINE ORDER BY, not a SQL constraint",
        ),
        reason="ClickHouse does not support standard SQL PRIMARY KEY constraint; skip lock table DDL",
    ),
    _P,
    "clickhouse",
    benchmark=_B,
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="schema_emit.starrocks.write_primitives.pk_lock_table_unsupported",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.INFORMATIONAL,
        failure_mode=FailureMode.SILENT_CORRUPTION,
        payload=PKCapabilityPayload(
            ddl_accepted=True,
            uniqueness_enforced=False,
            conditions="first N columns only",
            failure_mode_detail=("StarRocks silently ignores PRIMARY KEY unless columns are the first N in the table"),
        ),
        reason="StarRocks accepts PRIMARY KEY DDL but does not enforce uniqueness; skip lock table DDL",
    ),
    _P,
    "starrocks",
    benchmark=_B,
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="schema_emit.doris.write_primitives.pk_lock_table_unsupported",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.INFORMATIONAL,
        failure_mode=FailureMode.SILENT_CORRUPTION,
        payload=PKCapabilityPayload(
            ddl_accepted=True,
            uniqueness_enforced=False,
            conditions="DUP_KEYS table model required; PRIMARY KEY has different semantics",
            failure_mode_detail="Doris PRIMARY KEY model differs from standard SQL PRIMARY KEY constraint",
        ),
        reason="Doris does not enforce standard SQL PRIMARY KEY uniqueness; skip lock table DDL",
    ),
    _P,
    "doris",
    benchmark=_B,
)

# ---------------------------------------------------------------------------
# Cloud analytics platforms: PRIMARY KEY DDL accepted but not enforced.
# Each entry closes the silent-corruption window identified in _project/compat/pk_audit.md.
# Dialect-based registration: the CompatibilityContext.platform field is set to
# the adapter's self._dialect value, so rules keyed on dialect string match all
# adapters sharing that dialect.
# ---------------------------------------------------------------------------

_INFORMATIONAL_DIALECTS: list[tuple[str, str, str, str]] = [
    # (dialect_key, rule_id_platform_slug, conditions, failure_mode_detail)
    (
        "snowflake",
        "snowflake",
        "Snowflake PRIMARY KEY is INFORMATIONAL by vendor documentation",
        "Snowflake accepts PRIMARY KEY DDL but explicitly documents uniqueness as not enforced "
        "(also covers Databend, which uses the Snowflake dialect)",
    ),
    (
        "redshift",
        "redshift",
        "Redshift PRIMARY KEY is INFORMATIONAL per ALTER TABLE docs",
        "Redshift accepts PRIMARY KEY DDL but documents uniqueness as not enforced",
    ),
    (
        "bigquery",
        "bigquery",
        "BigQuery PRIMARY KEY is NOT ENFORCED by default per DDL reference",
        "BigQuery accepts PRIMARY KEY DDL but uniqueness is advisory; both INSERTs succeed",
    ),
    (
        "databricks",
        "databricks",
        "Databricks Delta Lake PRIMARY KEY is informational (NOT ENFORCED) per docs",
        "Databricks accepts PRIMARY KEY DDL but uniqueness is not enforced by the Delta engine",
    ),
    (
        "tsql",
        "tsql",
        "Azure Synapse and Fabric Warehouse PRIMARY KEY is not enforced per Microsoft docs",
        "T-SQL DW platforms accept PRIMARY KEY for optimizer hints only; uniqueness not enforced "
        "(covers azure-synapse and fabric-warehouse dialects)",
    ),
    (
        "spark",
        "spark",
        "Apache Spark SQL / Delta Lake PRIMARY KEY constraint is not enforced at INSERT time",
        "Spark accepts PRIMARY KEY DDL (Delta format) but uniqueness not enforced "
        "(covers spark, pyspark, lakesail dialects)",
    ),
    (
        "trino",
        "trino",
        "Trino accepts PRIMARY KEY syntax but does not enforce uniqueness",
        "Trino / Athena / Starburst accept CREATE TABLE PRIMARY KEY but do not enforce it "
        "(covers trino, athena, starburst dialects)",
    ),
    (
        "presto",
        "presto",
        "Presto accepts PRIMARY KEY syntax but does not enforce uniqueness",
        "PrestoDB accepts PRIMARY KEY DDL as advisory constraint; uniqueness not enforced",
    ),
]

for _dialect, _slug, _conditions, _detail in _INFORMATIONAL_DIALECTS:
    REGISTRY.register(
        CompatibilityDecision(
            rule_id=f"schema_emit.{_slug}.write_primitives.pk_not_enforced",
            action=CompatAction.REWRITE_DDL,
            support_level=SupportLevel.INFORMATIONAL,
            failure_mode=FailureMode.SILENT_CORRUPTION,
            payload=PKCapabilityPayload(
                ddl_accepted=True,
                uniqueness_enforced=False,
                conditions=_conditions,
                failure_mode_detail=_detail,
            ),
            reason=(
                f"Workload runs; PRIMARY KEY uniqueness is not enforced on {_slug} - "
                "lock table bypass required to prevent concurrent double-population"
            ),
        ),
        _P,
        _dialect,
        benchmark=_B,
    )
