"""Firebolt DDL rewrite rules for Phase.DDL_OPTIMIZE.

Firebolt uses a type system and constraint model incompatible with DuckDB DDL:
VARCHAR(n)/CHAR(n) map to TEXT, DECIMAL maps to NUMERIC, and PRIMARY KEY / FOREIGN KEY
constraint clauses must be removed as Firebolt does not enforce them.

FireboltAdapter._optimize_table_definition() is the runtime implementation for
these transformations. This rule registers the REWRITE_DDL intent for governance -
compat_lint enforcement only; transformer_id is not resolved at runtime.
"""

from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="firebolt",
    rule_name="optimize_table_definition",
    transformer_id="firebolt_ddl_optimizer",
    description="Convert DuckDB-style DDL to Firebolt dialect: VARCHAR(n)/CHAR(n) → TEXT, "
    "DECIMAL → NUMERIC, strip PRIMARY KEY and FOREIGN KEY constraint clauses",
    reason="Firebolt uses TEXT for all string types (not VARCHAR/CHAR), NUMERIC for exact "
    "decimals (not DECIMAL), and does not enforce PRIMARY KEY or FOREIGN KEY constraints.",
)
