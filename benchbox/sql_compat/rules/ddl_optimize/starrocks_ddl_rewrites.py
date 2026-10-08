from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="starrocks",
    rule_name="optimize_table_definition",
    transformer_id="starrocks_ddl_optimizer",
    description="Convert DuckDB-style DDL to StarRocks dialect: add DUPLICATE/PRIMARY KEY model, "
    "rewrite types, strip AUTO_INCREMENT / ENGINE= / FOREIGN KEY",
    reason="StarRocks DDL dialect differs from DuckDB: requires DUPLICATE KEY or PRIMARY KEY table model, "
    "rejects AUTO_INCREMENT, ENGINE=, FOREIGN KEY, and uses backtick identifiers.",
)
