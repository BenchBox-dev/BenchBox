"""Databend DDL rewrite rules for Phase.DDL_OPTIMIZE.

Databend requires type and constraint adjustments incompatible with DuckDB DDL:
CHAR(n) must become VARCHAR(n), and PRIMARY KEY / FOREIGN KEY constraint clauses
must be removed as Databend does not enforce them.

DatabendAdapter._optimize_table_definition() is the runtime implementation for
these transformations. This rule registers the REWRITE_DDL intent for governance -
compat_lint enforcement only; transformer_id is not resolved at runtime.
"""

from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="databend",
    rule_name="optimize_table_definition",
    transformer_id="databend_ddl_optimizer",
    description="Convert DuckDB-style DDL to Databend dialect: CHAR(n) → VARCHAR(n), "
    "strip PRIMARY KEY and FOREIGN KEY constraint clauses",
    reason="Databend uses VARCHAR for all string types (not CHAR), and does not enforce "
    "PRIMARY KEY or FOREIGN KEY constraints - both must be removed from DDL.",
)
