from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="trino",
    rule_name="optimize_table_definition",
    transformer_id="trino_ddl_optimizer",
    description="Adjust CREATE TABLE DDL for Trino connector: strip WITH clause for memory "
    "catalog, add WITH (format = 'PARQUET') for Hive/Iceberg connector",
    reason="Trino memory catalog rejects WITH clause properties; Hive and Iceberg connectors "
    "require explicit format declaration for table creation.",
)
