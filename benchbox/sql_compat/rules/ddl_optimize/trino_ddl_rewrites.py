"""Trino DDL rewrite rules for Phase.DDL_OPTIMIZE.

Trino DDL varies by connector/catalog: the memory catalog does not support
WITH properties, while Hive/Iceberg connectors benefit from explicit format
declarations (WITH (format = 'PARQUET')).

TrinoAdapter._optimize_table_definition() (invoked via execute_schema_statements
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
        rule_id="ddl_optimize.trino.all.optimize_table_definition",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=RewriteDDLPayload(
            transformer_id="trino_ddl_optimizer",
            description=(
                "Adjust CREATE TABLE DDL for Trino connector: strip WITH clause for memory "
                "catalog, add WITH (format = 'PARQUET') for Hive/Iceberg connector"
            ),
            governance_only=True,
        ),
        reason=(
            "Trino memory catalog rejects WITH clause properties; Hive and Iceberg connectors "
            "require explicit format declaration for table creation."
        ),
    ),
    Phase.DDL_OPTIMIZE,
    "trino",
)
