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
from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="databricks",
    rule_name="convert_to_delta_table",
    transformer_id="databricks_delta_ddl_optimizer",
    description="Convert DuckDB-style DDL to Databricks Delta Lake or Apache Hudi format: "
    "CREATE OR REPLACE TABLE, USING DELTA or USING HUDI, with TBLPROPERTIES settings",
    reason="Databricks requires Delta Lake or Hudi DDL: CREATE TABLE must use CREATE OR REPLACE TABLE "
    "for idempotency, tables must declare USING DELTA or USING HUDI, and auto-optimize TBLPROPERTIES "
    "improve write performance when delta_auto_optimize is enabled (Delta only).",
)

# Benchmark-scoped rule for the Transaction Primitives staging DDL. Registered
# with REGISTRY.register directly (not the register_ddl_rewrite helper, which
# has no benchmark tier) so REGISTRY.resolve() keeps returning a single winner
# at the platform-wide tier instead of raising CompatibilityRegistryConflict
# (see singlestore_ddl_rewrites.py). The schema emitter
# (benchbox/core/transaction_primitives/schema.py) declares the feature only
# when this rule resolves; the generated compatibility docs render it from the
# registry. governance_only: the emitter applies the rewrite itself.
REGISTRY.register(
    CompatibilityDecision(
        rule_id="ddl_optimize.databricks.transaction_primitives.txn_staging_catalog_managed",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=RewriteDDLPayload(
            transformer_id="txn_staging_catalog_managed",
            description="Transaction Primitives staging DDL declares the catalogManaged Delta table "
            "feature: USING DELTA TBLPROPERTIES ('delta.feature.catalogManaged' = 'supported')",
            governance_only=True,
        ),
        reason="Databricks multi-statement transactions only write Delta tables with the catalogManaged "
        "feature (TRANSACTION_NOT_SUPPORTED.WRITE_NON_CATALOG_MANAGED_TABLE otherwise); the txn_* staging "
        "tables are the only tables these transactions write, so the schema emitter declares the feature "
        "when the registry resolves this benchmark-scoped rule.",
    ),
    Phase.DDL_OPTIMIZE,
    "databricks",
    benchmark="transaction_primitives",
)
