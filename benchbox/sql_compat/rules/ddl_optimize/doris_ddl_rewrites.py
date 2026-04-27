"""Apache Doris DDL rewrite rules for Phase.DDL_OPTIMIZE.

Doris OLAP requires substantial DDL transformations beyond what DuckDB generates:
FOREIGN KEY and PRIMARY KEY constraints must be stripped, TIME must map to VARCHAR(8),
STRING/TEXT must map to VARCHAR(65533), SMALLINT must map to INT, and DUPLICATE KEY /
DISTRIBUTED BY HASH clauses must be injected (both required by Doris OLAP).

DorisAdapter._inject_doris_ddl_clauses() is the runtime implementation.

This rule registers the REWRITE_DDL intent for governance - compat_lint enforcement
only; transformer_id is not resolved at runtime.
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
        rule_id="ddl_optimize.doris.all.inject_ddl_clauses",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=RewriteDDLPayload(
            transformer_id="doris_inject_ddl_clauses",
            description=(
                "Transform DuckDB DDL to valid Doris OLAP DDL: strip FOREIGN KEY and "
                "PRIMARY KEY constraints, translate TIME → VARCHAR(8), "
                "STRING/TEXT → VARCHAR(65533), SMALLINT → INT, "
                "inject DUPLICATE KEY and DISTRIBUTED BY HASH clauses, "
                "inject PROPERTIES(replication_num) for single-node deployments."
            ),
            governance_only=True,
        ),
        reason=(
            "Doris OLAP rejects standard SQL DDL in multiple ways: it does not support "
            "FOREIGN KEY or PRIMARY KEY constraint syntax, lacks TIME as a column type, "
            "and requires explicit DUPLICATE KEY and DISTRIBUTED BY HASH clauses — "
            "both mandatory for CREATE TABLE to succeed in OLAP mode."
        ),
    ),
    Phase.DDL_OPTIMIZE,
    "doris",
)
