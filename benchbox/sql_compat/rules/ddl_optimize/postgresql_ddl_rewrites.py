"""PostgreSQL DDL rewrite rules for Phase.DDL_OPTIMIZE.

PostgreSQL natively supports FOREIGN KEY constraints, but some PostgreSQL-compatible
engines (e.g., CedarDB) reject certain FK patterns at CREATE TABLE time.
PostgreSQLAdapter._optimize_table_definition() is not used; the FK strip is a
retry-on-failure path inside PostgreSQLAdapter._execute_create_schema().

This rule registers the REWRITE_DDL intent for governance - compat_lint enforcement
only; transformer_id is not resolved at runtime.
"""

from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="postgresql",
    rule_name="strip_foreign_keys",
    transformer_id="postgresql_strip_foreign_keys",
    description="Remove FOREIGN KEY constraint clauses on retry when CREATE TABLE fails; "
    "some PostgreSQL-compatible engines (e.g., CedarDB) reject FK syntax.",
    reason="PostgreSQL itself supports FOREIGN KEY constraints, but PostgreSQL-compatible "
    "engines may reject them at CREATE TABLE time. The adapter strips FK clauses "
    "on retry so tables can be created without FK enforcement.",
)
