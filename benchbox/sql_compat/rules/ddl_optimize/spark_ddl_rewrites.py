"""Spark DDL rewrite rules for Phase.DDL_OPTIMIZE.

Spark SQL table creation requires an explicit USING clause declaring the storage
format (DELTA, ICEBERG, ORC, or PARQUET). DuckDB DDL output omits this clause.
The exact format is determined by the adapter's table_format configuration.

SparkAdapter._optimize_table_definition() is the runtime implementation for
this transformation. This rule registers the REWRITE_DDL intent for governance -
compat_lint enforcement only; transformer_id is not resolved at runtime.
"""

from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="spark",
    rule_name="optimize_table_definition",
    transformer_id="spark_ddl_optimizer",
    description="Inject USING <format> clause into Spark CREATE TABLE: "
    "DELTA, ICEBERG, ORC, or PARQUET based on adapter table_format config",
    reason="Spark SQL requires an explicit USING clause on CREATE TABLE to declare the "
    "storage format; DuckDB DDL output omits this clause entirely.",
)
