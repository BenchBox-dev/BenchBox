"""PostgreSQL DDL rewrite rules for Phase.DDL_OPTIMIZE.

PostgreSQL natively supports FOREIGN KEY constraints, but some PostgreSQL-compatible
engines (e.g., CedarDB) reject certain FK patterns at CREATE TABLE time.
PostgreSQLAdapter._optimize_table_definition() is not used; the FK strip is a
retry-on-failure path inside PostgreSQLAdapter._execute_create_schema().

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
        rule_id="ddl_optimize.postgresql.all.strip_foreign_keys",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=RewriteDDLPayload(
            transformer_id="postgresql_strip_foreign_keys",
            description=(
                "Remove FOREIGN KEY constraint clauses on retry when CREATE TABLE fails; "
                "some PostgreSQL-compatible engines (e.g., CedarDB) reject FK syntax."
            ),
            governance_only=True,
        ),
        reason=(
            "PostgreSQL itself supports FOREIGN KEY constraints, but PostgreSQL-compatible "
            "engines may reject them at CREATE TABLE time. The adapter strips FK clauses "
            "on retry so tables can be created without FK enforcement."
        ),
    ),
    Phase.DDL_OPTIMIZE,
    "postgresql",
)
