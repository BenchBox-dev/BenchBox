"""Databend DDL rewrite rules for Phase.DDL_OPTIMIZE.

Databend requires type and constraint adjustments incompatible with DuckDB DDL:
CHAR(n) must become VARCHAR(n), and PRIMARY KEY / FOREIGN KEY constraint clauses
must be removed as Databend does not enforce them.

DatabendAdapter._optimize_table_definition() is the runtime implementation for
these transformations. This rule registers the REWRITE_DDL intent for governance -
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
        rule_id="ddl_optimize.databend.all.optimize_table_definition",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=RewriteDDLPayload(
            transformer_id="databend_ddl_optimizer",
            description=(
                "Convert DuckDB-style DDL to Databend dialect: CHAR(n) → VARCHAR(n), "
                "strip PRIMARY KEY and FOREIGN KEY constraint clauses"
            ),
            governance_only=True,
        ),
        reason=(
            "Databend uses VARCHAR for all string types (not CHAR), and does not enforce "
            "PRIMARY KEY or FOREIGN KEY constraints - both must be removed from DDL."
        ),
    ),
    Phase.DDL_OPTIMIZE,
    "databend",
)
