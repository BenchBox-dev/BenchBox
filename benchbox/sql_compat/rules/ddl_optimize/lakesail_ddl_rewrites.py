from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="lakesail",
    rule_name="optimize_table_definition",
    transformer_id="lakesail_ddl_optimizer",
    description="Inject USING ORC or USING PARQUET into LakeSail CREATE TABLE based on adapter table_format config",
    reason="LakeSail (Sail) requires an explicit USING clause on CREATE TABLE; "
    "DuckDB DDL output omits this clause entirely.",
)
