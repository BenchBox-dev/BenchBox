"""Velox DDL rewrite rules for Phase.DDL_OPTIMIZE.

Velox (via Gluten+Spark) requires an explicit USING clause declaring the table
storage format (ORC or PARQUET). DuckDB DDL output omits this clause. The exact
format is determined by the adapter's table_format configuration.

VeloxAdapter._optimize_table_definition() is the runtime implementation for
this transformation. This rule registers the REWRITE_DDL intent for governance -
compat_lint enforcement only; transformer_id is not resolved at runtime.
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
        rule_id="ddl_optimize.velox.all.optimize_table_definition",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=RewriteDDLPayload(
            transformer_id="velox_ddl_optimizer",
            description=(
                "Inject USING ORC or USING PARQUET into Velox CREATE TABLE based on adapter table_format config"
            ),
            governance_only=True,
        ),
        reason=(
            "Velox (Gluten+Spark) requires an explicit USING clause on CREATE TABLE; "
            "DuckDB DDL output omits this clause entirely."
        ),
    ),
    Phase.DDL_OPTIMIZE,
    "velox",
)
