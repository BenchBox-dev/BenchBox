"""Velox DDL rewrite rules for Phase.DDL_OPTIMIZE.

Velox (via Gluten+Spark) requires an explicit USING clause declaring the table
storage format (ORC or PARQUET). DuckDB DDL output omits this clause. The exact
format is determined by the adapter's table_format configuration.

VeloxAdapter._optimize_table_definition() is the runtime implementation for
this transformation. This rule registers the REWRITE_DDL intent for governance -
compat_lint enforcement only; transformer_id is not resolved at runtime.
"""

from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="velox",
    rule_name="optimize_table_definition",
    transformer_id="velox_ddl_optimizer",
    description="Inject USING ORC or USING PARQUET into Velox CREATE TABLE based on adapter table_format config",
    reason="Velox (Gluten+Spark) requires an explicit USING clause on CREATE TABLE; "
    "DuckDB DDL output omits this clause entirely.",
)
