"""Firebolt DDL rewrite rules for Phase.DDL_OPTIMIZE.

Firebolt uses a type system and constraint model incompatible with DuckDB DDL:
VARCHAR(n)/CHAR(n) map to TEXT, DECIMAL maps to NUMERIC, and PRIMARY KEY / FOREIGN KEY
constraint clauses must be removed as Firebolt does not enforce them.

FireboltAdapter._optimize_table_definition() is the runtime implementation for
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
        rule_id="ddl_optimize.firebolt.all.optimize_table_definition",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=RewriteDDLPayload(
            transformer_id="firebolt_ddl_optimizer",
            description=(
                "Convert DuckDB-style DDL to Firebolt dialect: VARCHAR(n)/CHAR(n) → TEXT, "
                "DECIMAL → NUMERIC, strip PRIMARY KEY and FOREIGN KEY constraint clauses"
            ),
            governance_only=True,
        ),
        reason=(
            "Firebolt uses TEXT for all string types (not VARCHAR/CHAR), NUMERIC for exact "
            "decimals (not DECIMAL), and does not enforce PRIMARY KEY or FOREIGN KEY constraints."
        ),
    ),
    Phase.DDL_OPTIMIZE,
    "firebolt",
)
