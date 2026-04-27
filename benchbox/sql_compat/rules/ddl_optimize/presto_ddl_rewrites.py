"""Presto DDL rewrite rules for Phase.DDL_OPTIMIZE.

Presto DDL varies by connector/catalog: the memory catalog does not support
WITH properties or NOT NULL constraints, while Hive connectors benefit from
explicit format declarations (WITH (format = 'PARQUET')).

PrestoAdapter._optimize_table_definition() (invoked via execute_schema_statements
in presto_trino_utils) is the runtime implementation for these transformations.
This rule registers the REWRITE_DDL intent for governance - compat_lint
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
        rule_id="ddl_optimize.presto.all.optimize_table_definition",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=RewriteDDLPayload(
            transformer_id="presto_ddl_optimizer",
            description=(
                "Adjust CREATE TABLE DDL for Presto connector: strip WITH/NOT NULL for memory "
                "catalog, add WITH (format = 'PARQUET') for Hive connector"
            ),
            governance_only=True,
        ),
        reason=(
            "Presto memory catalog rejects WITH properties and NOT NULL constraints; "
            "Hive connector requires explicit format declaration for table creation."
        ),
    ),
    Phase.DDL_OPTIMIZE,
    "presto",
)
