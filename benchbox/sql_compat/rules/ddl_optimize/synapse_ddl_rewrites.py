"""Azure Synapse DDL rewrite rules for Phase.DDL_OPTIMIZE.

Azure Synapse Dedicated SQL Pool requires a WITH (DISTRIBUTION = ...) clause
for every table. DuckDB DDL output does not include this clause.
Note: the schema-prefix injection in _optimize_table_definition is operational
(uses runtime adapter state self.schema) and is not represented in this rule -
only the distribution-style DDL concern is registered here.

AzureSynapseAdapter._optimize_table_definition() is the runtime implementation
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
        rule_id="ddl_optimize.azure_synapse.all.optimize_table_definition",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=RewriteDDLPayload(
            transformer_id="azure_synapse_ddl_optimizer",
            description=(
                "Append Azure Synapse distribution clause to CREATE TABLE: "
                "WITH (DISTRIBUTION = ROUND_ROBIN) or configured default"
            ),
            governance_only=True,
        ),
        reason=(
            "Azure Synapse Dedicated SQL Pool requires a WITH (DISTRIBUTION = ...) clause "
            "on every CREATE TABLE statement; DuckDB DDL output omits this clause."
        ),
    ),
    Phase.DDL_OPTIMIZE,
    "synapse",
)
