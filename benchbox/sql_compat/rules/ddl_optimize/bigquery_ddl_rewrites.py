"""BigQuery DDL rewrite rules for Phase.DDL_OPTIMIZE.

BigQueryAdapter._convert_to_bigquery_table() is the local runtime path. It
converts DuckDB-style CREATE TABLE statements to BigQuery DDL by making table
creation idempotent, qualifying the target table with project and dataset, and
adding optional partitioning or clustering clauses.

This rule registers the REWRITE_DDL intent for governance and compat_lint. The
adapter does not inherit BaseDdlOptimizer, so transformer_id is documentary and
governance_only=True.
"""

from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="bigquery",
    rule_name="convert_to_bigquery_table",
    transformer_id="bigquery_convert_to_bigquery_table",
    description="Convert DuckDB-style CREATE TABLE to BigQuery DDL: CREATE OR REPLACE TABLE, "
    "project.dataset table qualification, and optional PARTITION BY / CLUSTER BY clauses.",
    reason="BigQuery DDL runs in a project/dataset namespace and benchmark schema creation must be "
    "idempotent across repeated runs. Optional partitioning and clustering clauses are appended "
    "from adapter configuration because DuckDB DDL does not emit BigQuery storage layout hints.",
)
