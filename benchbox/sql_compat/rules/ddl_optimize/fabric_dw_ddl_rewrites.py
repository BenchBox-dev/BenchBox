"""Microsoft Fabric Warehouse DDL rewrite rules for Phase.DDL_OPTIMIZE.

Fabric Warehouse requires schema-qualified table names ([schema].[table]) in
CREATE TABLE statements. DuckDB-generated DDL omits the schema prefix; the adapter
injects it at runtime using the configured schema.

FabricWarehouseAdapter._optimize_table_definition() is the runtime implementation.

This rule registers the REWRITE_DDL intent for governance - compat_lint enforcement
only; transformer_id is not resolved at runtime.

Note: the schema prefix injection depends on runtime adapter state (self.schema) and
cannot be expressed as a static DDL rule — the registration is a governance marker,
not a static rewrite.
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
        rule_id="ddl_optimize.fabric_dw.all.optimize_table_definition",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=RewriteDDLPayload(
            transformer_id="fabric_dw_ddl_optimizer",
            description=(
                "Inject schema prefix ([schema].[table_name]) into CREATE TABLE statements "
                "for Fabric Warehouse; DuckDB DDL output omits the schema qualifier."
            ),
            governance_only=True,
        ),
        reason=(
            "Fabric Warehouse requires schema-qualified table names in CREATE TABLE. "
            "Without the schema prefix, tables are created in the wrong schema or the "
            "statement references an unqualified name that doesn't resolve correctly."
        ),
    ),
    Phase.DDL_OPTIMIZE,
    "fabric_dw",
)
