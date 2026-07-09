"""Presto DDL rewrite rules for Phase.DDL_OPTIMIZE.

Presto DDL varies by connector/catalog: benchmark schemas can include PRIMARY
KEY metadata that Presto rejects, the memory catalog does not support WITH
properties or NOT NULL constraints, and Hive connectors benefit from explicit
format declarations (WITH (format = 'PARQUET')).

PrestoAdapter._optimize_table_definition() (invoked via execute_schema_statements
in presto_trino_utils) is the runtime implementation for these transformations.
This rule registers the REWRITE_DDL intent for governance - compat_lint
enforcement only; transformer_id is not resolved at runtime.
"""

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
