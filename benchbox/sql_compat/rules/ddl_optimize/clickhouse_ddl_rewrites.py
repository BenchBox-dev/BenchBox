"""ClickHouse DDL rewrite rules for Phase.DDL_OPTIMIZE.

ClickHouse rejects standard DuckDB DDL: Nullable(Type) NOT NULL combinations
produce errors, tables require an explicit ENGINE clause, and ClickHouse
MergeTree tables must declare an ORDER BY key.

ClickHouseWorkloadMixin._optimize_table_definition() is the runtime implementation
for these transformations. This rule registers the REWRITE_DDL intent for
governance - compat_lint enforcement only; transformer_id is not resolved at runtime.
"""

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
