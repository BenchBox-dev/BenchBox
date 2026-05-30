"""Snowflake DDL rewrite rules for Phase.DDL_OPTIMIZE.

Snowflake schema creation uses CREATE OR REPLACE TABLE for idempotent DDL.
DuckDB DDL output uses plain CREATE TABLE which fails on re-runs when the table
already exists.

SnowflakeAdapter._optimize_table_definition() is the runtime implementation for
this transformation. This rule registers the REWRITE_DDL intent for governance -
compat_lint enforcement only; transformer_id is not resolved at runtime.
"""

from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="snowflake",
    rule_name="optimize_table_definition",
    transformer_id="snowflake_ddl_optimizer",
    description="Rewrite CREATE TABLE → CREATE OR REPLACE TABLE for Snowflake idempotency",
    reason="Snowflake schema creation must be idempotent across benchmark runs; "
    "CREATE OR REPLACE TABLE avoids failures when a table already exists.",
)
