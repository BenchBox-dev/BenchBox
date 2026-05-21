"""Athena DDL rewrite rules for Phase.DDL_OPTIMIZE.

AthenaAdapter._convert_to_external_table() is the local runtime path. It
converts DuckDB-style CREATE TABLE statements to Hive-compatible external table
DDL backed by S3, including staging-table variants for parquet mode.

This rule registers the REWRITE_DDL intent for governance and compat_lint. The
adapter does not inherit BaseDdlOptimizer, so transformer_id is documentary and
governance_only=True.
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
        rule_id="ddl_optimize.athena.all.convert_to_external_table",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=RewriteDDLPayload(
            transformer_id="athena_convert_to_external_table",
            description=(
                "Convert DuckDB-style CREATE TABLE to Athena/Hive external table DDL: "
                "CREATE EXTERNAL TABLE IF NOT EXISTS, Hive-compatible STRING types, "
                "storage format clauses, S3 LOCATION, and removal of unsupported NOT NULL / WITH clauses."
            ),
            governance_only=True,
        ),
        reason=(
            "Athena creates Hive external tables over S3 data. Standard DuckDB CREATE TABLE DDL lacks "
            "EXTERNAL TABLE, LOCATION, ROW FORMAT / STORED AS clauses, and may include constraints "
            "or types that Hive DDL rejects."
        ),
    ),
    Phase.DDL_OPTIMIZE,
    "athena",
)
