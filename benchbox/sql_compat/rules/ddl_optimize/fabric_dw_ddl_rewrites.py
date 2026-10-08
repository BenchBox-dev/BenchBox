from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="fabric_dw",
    rule_name="optimize_table_definition",
    transformer_id="fabric_dw_ddl_optimizer",
    description="Inject schema prefix ([schema].[table_name]) into CREATE TABLE statements "
    "for Fabric Warehouse; DuckDB DDL output omits the schema qualifier.",
    reason="Fabric Warehouse requires schema-qualified table names in CREATE TABLE. "
    "Without the schema prefix, tables are created in the wrong schema or the "
    "statement references an unqualified name that doesn't resolve correctly.",
)
