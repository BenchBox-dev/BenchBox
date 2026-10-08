from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="athena",
    rule_name="convert_to_external_table",
    transformer_id="athena_convert_to_external_table",
    description="Convert DuckDB-style CREATE TABLE to Athena/Hive external table DDL: "
    "CREATE EXTERNAL TABLE IF NOT EXISTS, Hive-compatible STRING types, "
    "storage format clauses, S3 LOCATION, and removal of unsupported NOT NULL / WITH clauses.",
    reason="Athena creates Hive external tables over S3 data. Standard DuckDB CREATE TABLE DDL lacks "
    "EXTERNAL TABLE, LOCATION, ROW FORMAT / STORED AS clauses, and may include constraints "
    "or types that Hive DDL rejects.",
)
