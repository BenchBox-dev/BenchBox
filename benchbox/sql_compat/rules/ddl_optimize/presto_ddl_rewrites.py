from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="presto",
    rule_name="optimize_table_definition",
    transformer_id="presto_ddl_optimizer",
    description="Adjust CREATE TABLE DDL for Presto connector: strip PRIMARY KEY constraints, "
    "strip WITH/NOT NULL for memory catalog, add WITH (format = 'PARQUET') for Hive connector",
    reason="Presto rejects PRIMARY KEY constraints in benchmark DDL; memory catalog rejects WITH properties "
    "and NOT NULL constraints; Hive connector requires explicit format declaration for table creation.",
)
