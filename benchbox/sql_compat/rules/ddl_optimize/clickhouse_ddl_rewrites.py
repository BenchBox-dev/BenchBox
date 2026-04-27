"""ClickHouse DDL rewrite rules for Phase.DDL_OPTIMIZE.

ClickHouse rejects standard DuckDB DDL: Nullable(Type) NOT NULL combinations
produce errors, tables require an explicit ENGINE clause, and ClickHouse
MergeTree tables must declare an ORDER BY key.

ClickHouseWorkloadMixin._optimize_table_definition() is the runtime implementation
for these transformations. This rule registers the REWRITE_DDL intent for
governance - compat_lint enforcement only; transformer_id is not resolved at runtime.
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

REGISTRY.register(
    CompatibilityDecision(
        rule_id="ddl_optimize.clickhouse.all.optimize_table_definition",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=RewriteDDLPayload(
            transformer_id="clickhouse_ddl_optimizer",
            description=(
                "Convert DuckDB-style DDL to ClickHouse dialect: strip Nullable NOT NULL, "
                "add ENGINE = MergeTree(), add ORDER BY tuple() or primary key columns"
            ),
            governance_only=True,
        ),
        reason=(
            "ClickHouse rejects Nullable(Type) NOT NULL combinations, requires an explicit "
            "ENGINE clause, and MergeTree tables must declare ORDER BY."
        ),
    ),
    Phase.DDL_OPTIMIZE,
    "clickhouse",
)
