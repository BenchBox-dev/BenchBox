"""Trino DDL rewrite rules for Phase.DDL_OPTIMIZE.

Trino DDL varies by connector/catalog: the memory catalog does not support
WITH properties, while Hive/Iceberg connectors benefit from explicit format
declarations (WITH (format = 'PARQUET')).

TrinoAdapter._optimize_table_definition() (invoked via execute_schema_statements
in presto_trino_utils) is the runtime implementation for these transformations.
This rule registers the REWRITE_DDL intent for governance - compat_lint
enforcement only; transformer_id is not resolved at runtime.
"""

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
