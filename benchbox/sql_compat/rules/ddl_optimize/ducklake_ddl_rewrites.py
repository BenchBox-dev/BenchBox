"""DuckLake DDL rewrite rules for Phase.DDL_OPTIMIZE.

DuckLake shares the DuckDB SQL dialect unchanged but does not implement
PRIMARY KEY/UNIQUE constraints, so benchmark CREATE TABLE DDL carrying that
metadata must have it stripped before execution.

DuckLakeAdapter._rewrite_schema_statement() is the runtime implementation for
this transformation. This rule registers the REWRITE_DDL intent for governance
- compat_lint enforcement only; transformer_id is not resolved at runtime.
"""

from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="ducklake",
    rule_name="strip_primary_keys",
    transformer_id="ducklake_strip_primary_keys",
    description="Adjust CREATE TABLE DDL for DuckLake: strip PRIMARY KEY/UNIQUE constraints",
    reason="DuckLake rejects PRIMARY KEY/UNIQUE constraints in benchmark DDL; "
    "the constraint is metadata only for immutable benchmark data and is stripped before execution.",
)
