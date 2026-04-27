"""Databricks DDL rewrite rules for Phase.DDL_OPTIMIZE.

Databricks requires Delta Lake DDL syntax incompatible with DuckDB's output:
CREATE TABLE must become CREATE OR REPLACE TABLE, USING DELTA must be declared,
and TBLPROPERTIES may include auto-optimize settings.

DatabricksAdapter._convert_to_delta_table() is the runtime implementation for
these transformations (applied as a pre-pass loop before _execute_schema_statements,
w17). This rule registers the REWRITE_DDL intent for governance - compat_lint
enforcement only; transformer_id is not resolved at runtime.
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
        rule_id="ddl_optimize.databricks.all.convert_to_delta_table",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=RewriteDDLPayload(
            transformer_id="databricks_delta_ddl_optimizer",
            description=(
                "Convert DuckDB-style DDL to Databricks Delta Lake format: "
                "CREATE OR REPLACE TABLE, USING DELTA, TBLPROPERTIES auto-optimize settings"
            ),
            governance_only=True,
        ),
        reason=(
            "Databricks requires Delta Lake DDL: CREATE TABLE must use CREATE OR REPLACE TABLE "
            "for idempotency, tables must declare USING DELTA, and auto-optimize TBLPROPERTIES "
            "improve write performance when delta_auto_optimize is enabled."
        ),
    ),
    Phase.DDL_OPTIMIZE,
    "databricks",
)
