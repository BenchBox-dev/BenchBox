# SQL Compat DDL Drift Audit

**Date:** 2026-04-25
**Scope:** `benchbox/platforms/**/*.py` — every DDL regex / string replacement / DDL method
**Purpose:** w2 punch list for `register-adapter-ddl-rewrites-under-sql-compat`

---

## Summary

| # | Adapter | File:Line | Operation | Registered? | Target rule_id | Action |
|---|---------|-----------|-----------|-------------|----------------|--------|
| 1 | PostgreSQL | postgresql.py:120 | `_strip_foreign_keys()` module fn — FK strip | ✗ | `ddl_optimize.postgresql.all.strip_foreign_keys` | Register in w5; migrate to shared helper in w4 |
| 2 | QuestDB | questdb.py:656 | `_strip_fk_constraints()` — FK strip | ✗ | `ddl_optimize.questdb.all.strip_fk_and_pk` | Register in w5; migrate FK portion to shared helper in w4 |
| 3 | QuestDB | questdb.py:680 | `_strip_pk_constraints()` — PK strip | ✗ | (covered by same rule as #2) | Register together with #2 |
| 4 | Doris | doris.py:1422 | `_inject_doris_ddl_clauses()` — PK/FK strip, TIME→VARCHAR, DUPLICATE KEY, DISTRIBUTED BY, PROPERTIES | ✗ | `ddl_optimize.doris.all.inject_ddl_clauses` | Register in w5 |
| 5 | Doris | doris.py:1495 | Inline STRING→VARCHAR, TEXT→VARCHAR, SMALLINT→INT, ARRAY strip (inside `_inject_doris_ddl_clauses`) | ✗ | (covered by same rule as #4) | Covered by #4 registration |
| 6 | FabricWarehouse | fabric_warehouse.py:1207 | `_optimize_table_definition()` — standard method, no rule | ✗ | `ddl_optimize.fabric_warehouse.all.optimize_table_definition` | Register in w5 |
| 7 | DuckDB | duckdb.py:731 | Inline FOREIGN KEY / REFERENCES strip inside `create_schema()` (TPC-DS only) | ✗ | — | **Accept as-is**: duckdb.py is in `scope_limit.do_not_modify`; strip is benchmark-conditional (TPC-DS only), not a platform DDL transform |
| 8 | pg_mooncake | pg_mooncake.py:193 | `_transform_create_statement()` appends `USING columnstore` | ✗ (post-w7) | `ddl_optimize.pg_mooncake.all.add_columnstore_access_method` | **Missed by initial audit walk** — surfaced when w7 fail-CI flipped on; registered as governance-only in follow-up commit |
| 9 | Firebolt | firebolt.py:1077 | Inline FK-strip regex inside registered `_optimize_table_definition` | ✓ (covered) | n/a | Covered governance-wise by `firebolt_ddl_rewrites.py`; FK regex itself was duplicating `strip_foreign_keys()`. Migrated to shared helper in follow-up commit. |

---

## Already-Registered Platforms (no action needed)

These platforms have registered rules in `benchbox/sql_compat/rules/ddl_optimize/` that cover their `_optimize_table_definition()` transforms:

| Platform | Rule file | Transforms covered |
|----------|-----------|-------------------|
| azure_synapse | azure_synapse_ddl_rewrites.py | Full DDL rewrite via `_optimize_table_definition` |
| clickhouse | clickhouse_ddl_rewrites.py | Full DDL rewrite |
| databend | databend_ddl_rewrites.py | CHAR→VARCHAR, PK/FK strip |
| databricks | databricks_ddl_rewrites.py | CREATE TABLE→OR REPLACE, USING DELTA |
| firebolt | firebolt_ddl_rewrites.py | VARCHAR→TEXT |
| lakesail | lakesail_ddl_rewrites.py | Full DDL rewrite |
| presto | presto_ddl_rewrites.py | Full DDL rewrite |
| redshift | redshift_ddl_rewrites.py | Full DDL rewrite |
| singlestore | singlestore_ddl_rewrites.py | FK strip, SHARD KEY, SORT KEY, REFERENCE TABLE (**added in w1**) |
| snowflake | snowflake_ddl_rewrites.py | CREATE TABLE→OR REPLACE |
| spark | spark_ddl_rewrites.py | Full DDL rewrite |
| starrocks | starrocks_ddl_rewrites.py | DUPLICATE/PRIMARY KEY model, type rewrite, FK/AUTO_INCREMENT strip |
| trino | trino_ddl_rewrites.py | Full DDL rewrite |
| velox | velox_ddl_rewrites.py | USING ORC/PARQUET injection |

### Notes on Athena and BigQuery

- **Athena** (athena.py:587 `_convert_to_external_table()`): type conversion (VARCHAR→STRING, CHAR→STRING) and external table DDL. The method is not named `_optimize_table_definition` so compat_lint currently does NOT detect it. Not in `scope_limit.only_modify`. Flagged for a follow-up TODO.
- **BigQuery** (bigquery.py:1413): inline `CREATE TABLE → CREATE OR REPLACE TABLE` inside `create_schema()`. Same situation — not `_optimize_table_definition`, not in scope. Follow-up TODO.
- **spark_helpers.py:122**: `_SMALLINT_RE = re.compile(...)` is a module-level constant used by the Spark `_optimize_table_definition` implementation. The Spark rule covers the full transform. Not a separate unregistered operation.

---

## Punch List Count

- **Unregistered transforms requiring registration (w5):** 4 distinct operations across 4 adapters (PostgreSQL, QuestDB, Doris, FabricWarehouse)
- **Accepted as-is:** 1 (DuckDB — out of scope, benchmark-conditional)
- **Out of scope (follow-up TODO):** 2 (Athena, BigQuery)
- **Initial total: 4** — well under the w2 decision gate threshold of 30; proceed with w5 registration

### Post-w7 follow-ups (surfaced after fail-CI flip)

- **pg_mooncake** (`pg_mooncake.py:193`) — missed by the initial walk; registered as governance-only in
  `pg_mooncake_ddl_rewrites.py`. Lesson: the audit should have grepped every `def _transform_create_statement`
  across `benchbox/platforms/`, not only the adapters listed in `scope_limit.only_modify`.
- **Firebolt** FK-strip regex (`firebolt.py:1077`) was governance-covered by the registered
  `firebolt_ddl_rewrites.py`, but the regex itself duplicated `strip_foreign_keys()`. Migrated to the shared
  helper to satisfy the "Zero inline FK-strip regex" success metric in literal terms.

---

## w5 Work Items

| Priority | File | Registration target |
|----------|------|---------------------|
| HIGH | postgresql.py:120 → w4 FK migration | `postgresql_ddl_rewrites.py` — `ddl_optimize.postgresql.all.strip_foreign_keys` |
| HIGH | questdb.py:656,680 → w4 FK migration | `questdb_ddl_rewrites.py` — `ddl_optimize.questdb.all.strip_fk_and_pk_constraints` |
| HIGH | doris.py:1422 | `doris_ddl_rewrites.py` — `ddl_optimize.doris.all.inject_ddl_clauses` |
| MEDIUM | fabric_warehouse.py:1207 | `fabric_warehouse_ddl_rewrites.py` — `ddl_optimize.fabric_warehouse.all.optimize_table_definition` |

---

## Reference Locations

- Registered rules: `benchbox/sql_compat/rules/ddl_optimize/`
- SingleStore reference: `benchbox/sql_compat/rules/ddl_optimize/singlestore_ddl_rewrites.py`
- FK duplicates to consolidate (w3/w4): singlestore.py:101, postgresql.py:120, doris.py:1435, starrocks/workload.py:134, databend/adapter.py:871, questdb.py:656
