"""Apache Doris DDL rewrite rules for Phase.DDL_OPTIMIZE.

Doris OLAP requires substantial DDL transformations beyond what DuckDB generates:
FOREIGN KEY and PRIMARY KEY constraints must be stripped, TIME must map to VARCHAR(8),
STRING/TEXT must map to VARCHAR(65533), SMALLINT must map to INT, and DUPLICATE KEY /
DISTRIBUTED BY HASH clauses must be injected (both required by Doris OLAP).

DorisAdapter._inject_doris_ddl_clauses() is the runtime implementation.

This rule registers the REWRITE_DDL intent for governance - compat_lint enforcement
only; transformer_id is not resolved at runtime.
"""

from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="doris",
    rule_name="inject_ddl_clauses",
    transformer_id="doris_inject_ddl_clauses",
    description="Transform DuckDB DDL to valid Doris OLAP DDL: strip FOREIGN KEY and "
    "PRIMARY KEY constraints, translate TIME → VARCHAR(8), "
    "STRING/TEXT → VARCHAR(65533), SMALLINT → INT, "
    "inject DUPLICATE KEY and DISTRIBUTED BY HASH clauses, "
    "inject PROPERTIES(replication_num) for single-node deployments.",
    reason="Doris OLAP rejects standard SQL DDL in multiple ways: it does not support "
    "FOREIGN KEY or PRIMARY KEY constraint syntax, lacks TIME as a column type, "
    "and requires explicit DUPLICATE KEY and DISTRIBUTED BY HASH clauses — "
    "both mandatory for CREATE TABLE to succeed in OLAP mode.",
)
