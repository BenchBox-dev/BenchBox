from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="clickhouse",
    rule_name="optimize_table_definition",
    transformer_id="clickhouse_ddl_optimizer",
    description="Convert DuckDB-style DDL to ClickHouse dialect: strip Nullable NOT NULL, "
    "add ENGINE = MergeTree(), add ORDER BY tuple() or primary key columns",
    reason="ClickHouse rejects Nullable(Type) NOT NULL combinations, requires an explicit "
    "ENGINE clause, and MergeTree tables must declare ORDER BY.",
)
