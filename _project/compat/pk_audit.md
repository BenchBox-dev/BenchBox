# PRIMARY KEY Enforcement Audit

**Date**: 2026-04-26
**Workstream**: `refine-sql-compat-skip-semantics` / w2
**Purpose**: Classify every BenchBox-supported platform by its PRIMARY KEY enforcement semantics
for `write_primitives` / `transaction_primitives` lock-table DDL.

## Bucket Definitions

| Bucket | Meaning |
|--------|---------|
| **NATIVE** | Parser accepts PRIMARY KEY DDL AND uniqueness is enforced at INSERT time |
| **REWRITTEN** | Parser accepts PRIMARY KEY DDL but it has engine-internal semantics (e.g., ordering key), not SQL constraint enforcement |
| **INFORMATIONAL** | Parser accepts PRIMARY KEY DDL but uniqueness is NOT enforced (silent; both INSERTs succeed) |
| **SKIPPED_DDL_FRAGMENT** | Parser rejects PRIMARY KEY DDL outright (SYNTAX_ERROR); workload runs without the lock table |

## Cross-Check: NoConstraintEnforcementMixin

The following adapters inherit from `benchbox/platforms/base/no_constraint_mixin.py`. The mixin
no-ops `apply_constraint_configuration` at runtime, which is direct in-tree evidence that PK
constraints are not enforced. Every mixin user must classify as INFORMATIONAL or SKIPPED_DDL_FRAGMENT.

| Platform | Adapter class | Bucket |
|----------|--------------|--------|
| DataFusion | `DataFusionAdapter` | SKIPPED_DDL_FRAGMENT (parser rejects PK DDL) |
| Polars | `PolarsAdapter` | out of scope — DataFrame platform, no SQL-mode primitives |
| cuDF | `CuDFAdapter` | out of scope — DataFrame platform, no SQL-mode primitives |

## Platform Classification Table

| platform_key | dialect | bucket | uses_no_constraint_mixin | failure_mode | conditions | doc_url |
|---|---|---|---|---|---|---|
| duckdb | duckdb | NATIVE | no | — | Standard SQL PK constraint enforced | https://duckdb.org/docs/sql/constraints.html |
| motherduck | duckdb | NATIVE | no | — | Same engine as DuckDB; PK enforced | https://motherduck.com/docs |
| sqlite | sqlite | NATIVE | no | — | Standard PK enforced via UNIQUE index | https://www.sqlite.org/lang_createtable.html |
| postgresql | postgres | NATIVE | no | — | Standard SQL PK constraint enforced | https://www.postgresql.org/docs/current/ddl-constraints.html |
| cedardb | postgres | NATIVE | no | — | PostgreSQL-compatible; PK enforced | https://cedardb.com/docs |
| pg_duckdb | postgres | NATIVE | no | — | PostgreSQL extension; PK enforced by PostgreSQL | https://github.com/duckdb/pg_duckdb |
| pg_mooncake | postgres | NATIVE | no | — | PostgreSQL extension; PK enforced by PostgreSQL | https://github.com/Mooncake-Labs/pg_mooncake |
| timescaledb | postgres | NATIVE | no | — | PostgreSQL extension; PK enforced by PostgreSQL | https://docs.timescale.com |
| singlestore | mysql | NATIVE | no | — | SingleStore enforces PK uniqueness (storage engine constraint) | https://docs.singlestore.com/db/latest/create-reference/sql-reference/data-definition-language-ddl/create-table/ |
| clickhouse | clickhouse | REWRITTEN | no | UNSUPPORTED_FEATURE | PRIMARY KEY is MergeTree ORDER BY key, not a SQL constraint; DDL accepted but uniqueness not enforced | https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/mergetree/#primary-keys-and-indexes-in-queries |
| clickhouse-cloud | clickhouse | REWRITTEN | no | UNSUPPORTED_FEATURE | Same as clickhouse; ClickHouse Cloud uses same engine | https://clickhouse.com/docs/en/cloud/ |
| clickhouse-local | clickhouse | REWRITTEN | no | UNSUPPORTED_FEATURE | Same as clickhouse | — |
| starrocks | starrocks | INFORMATIONAL | no | SILENT_CORRUPTION | Accepts PK DDL; uniqueness enforced only if PK columns are the first N columns of the table | https://docs.starrocks.io/docs/table_design/table_types/primary_key_table/ |
| doris | doris | INFORMATIONAL | no | SILENT_CORRUPTION | Accepts PK DDL but uses DUP_KEYS model by default; PK semantics differ from SQL standard | https://doris.apache.org/docs/table-design/data-model/duplicate/ |
| datafusion | datafusion | SKIPPED_DDL_FRAGMENT | yes | SYNTAX_ERROR | DataFusion does not parse PRIMARY KEY in CREATE TABLE; parse error at DDL emit | https://arrow.apache.org/datafusion/user-guide/sql/ddl.html |
| snowflake | snowflake | INFORMATIONAL | no | SILENT_CORRUPTION | Snowflake accepts PRIMARY KEY DDL but explicitly documents it as "informational only"; uniqueness not enforced | https://docs.snowflake.com/en/sql-reference/constraints-overview |
| databend | snowflake | INFORMATIONAL | no | SILENT_CORRUPTION | Databend uses Snowflake dialect; PRIMARY KEY not enforced (advisory only) | https://docs.databend.com/sql/sql-commands/ddl/table/create-table |
| redshift | redshift | INFORMATIONAL | no | SILENT_CORRUPTION | Redshift documents PK as "informational"; constraint metadata only, not enforced | https://docs.aws.amazon.com/redshift/latest/dg/t_Defining_constraints.html |
| bigquery | bigquery | INFORMATIONAL | no | SILENT_CORRUPTION | BigQuery PRIMARY KEY is "NOT ENFORCED" by default; DDL accepted, uniqueness not guaranteed | https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#column_schema |
| databricks | databricks | INFORMATIONAL | no | SILENT_CORRUPTION | Databricks Delta Lake PRIMARY KEY is "informational" (NOT ENFORCED); accepts DDL, uniqueness not enforced | https://docs.databricks.com/en/sql/language-manual/sql-ref-syntax-ddl-create-table-constraint.html |
| azure-synapse | tsql | INFORMATIONAL | no | SILENT_CORRUPTION | Synapse dedicated SQL pool documents PK as "not enforced"; accepted for optimizer hints only | https://learn.microsoft.com/en-us/azure/synapse-analytics/sql-data-warehouse/sql-data-warehouse-table-constraints |
| fabric-warehouse | tsql | INFORMATIONAL | no | SILENT_CORRUPTION | Microsoft Fabric Warehouse: PK constraints accepted but not enforced | https://learn.microsoft.com/en-us/fabric/data-warehouse/table-constraints |
| spark | spark | INFORMATIONAL | no | SILENT_CORRUPTION | Apache Spark SQL accepts PRIMARY KEY DDL (Delta Lake format) but does not enforce uniqueness at INSERT time | https://docs.delta.io/latest/delta-constraints.html |
| pyspark | spark | INFORMATIONAL | no | SILENT_CORRUPTION | PySpark uses same Spark SQL engine; same PK non-enforcement semantics | https://docs.delta.io/latest/delta-constraints.html |
| lakesail | spark | INFORMATIONAL | no | SILENT_CORRUPTION | LakeSail uses Spark dialect; PK not enforced (same as Spark) | — |
| trino | trino | INFORMATIONAL | no | SILENT_CORRUPTION | Trino accepts CREATE TABLE with PRIMARY KEY syntax but does not enforce uniqueness | https://trino.io/docs/current/sql/create-table.html |
| athena | trino | INFORMATIONAL | no | SILENT_CORRUPTION | Athena uses Trino SQL; same PK non-enforcement as Trino | https://docs.aws.amazon.com/athena/latest/ug/create-table.html |
| starburst | trino | INFORMATIONAL | no | SILENT_CORRUPTION | Starburst uses Trino; same PK non-enforcement as Trino | https://docs.starburst.io/latest/ |
| presto | presto | INFORMATIONAL | no | SILENT_CORRUPTION | Presto/PrestoDB: PRIMARY KEY DDL accepted but not enforced; advisory constraint only | https://prestodb.io/docs/current/sql/create-table.html |
| firebolt | postgres | KNOWN_CONFLICT | no | SILENT_CORRUPTION | Firebolt uses PostgreSQL dialect but does not enforce PK uniqueness. Cannot register a "postgres" PK rule because that key is shared with PostgreSQL (NATIVE). See Conflict note below. | https://docs.firebolt.io/sql_reference/commands/data-definition/create-fact-dimension-table.html |
| polars-df | — | out_of_scope | yes | — | DataFrame platform; no SQL-mode write_primitives/transaction_primitives | — |
| pandas-df | — | out_of_scope | no | — | DataFrame platform; no SQL-mode write_primitives/transaction_primitives | — |
| cudf | — | out_of_scope | yes | — | DataFrame platform; no SQL-mode write_primitives/transaction_primitives | — |

## Dialect Sharing Notes

Several platform groups share a SQL dialect string. Registry rules are keyed on dialect (what
`_pk_lock_bypass_required` passes as `platform` in the CompatibilityContext). Where all members
of a dialect group agree on the same bucket, a single rule covers the group.

| Dialect key | Platforms | Common bucket |
|-------------|-----------|---------------|
| `duckdb` | duckdb, motherduck | NATIVE — no rule needed (fallback=False is correct) |
| `sqlite` | sqlite | NATIVE — no rule needed |
| `postgres` | postgresql, cedardb, pg_duckdb, pg_mooncake, timescaledb, firebolt | **CONFLICT** — see below |
| `mysql` | singlestore | NATIVE — no rule needed |
| `snowflake` | snowflake, databend | INFORMATIONAL — one `snowflake` rule covers both |
| `redshift` | redshift | INFORMATIONAL |
| `bigquery` | bigquery | INFORMATIONAL |
| `databricks` | databricks | INFORMATIONAL |
| `tsql` | azure-synapse, fabric-warehouse | INFORMATIONAL — one `tsql` rule covers both |
| `spark` | spark, pyspark, lakesail | INFORMATIONAL — one `spark` rule covers all |
| `trino` | trino, athena, starburst | INFORMATIONAL — one `trino` rule covers all |
| `presto` | presto | INFORMATIONAL |
| `clickhouse` | clickhouse, clickhouse-cloud, clickhouse-local | REWRITTEN — already registered |
| `starrocks` | starrocks | INFORMATIONAL — already registered |
| `doris` | doris | INFORMATIONAL — already registered |
| `datafusion` | datafusion | SKIPPED_DDL_FRAGMENT — already registered |

## Known Conflict: `postgres` Dialect

Firebolt uses `self._dialect = "postgres"` (PostgreSQL-compatible wire protocol) but does NOT
enforce PRIMARY KEY uniqueness — it is an OLAP-only engine.

PostgreSQL, CedarDB, pg_duckdb, pg_mooncake, and TimescaleDB all use `self._dialect = "postgres"`
AND enforce PK uniqueness (NATIVE).

Registering a single `postgres` rule would be incorrect for either group. Resolution:

1. **Do not register a `postgres` PK rule in w5.** The `legacy_bypass` fallback for "postgres"
   is `False`, which is correct for PostgreSQL/CedarDB/pg_duckdb (NATIVE — they should use the
   PK lock, not bypass it). Firebolt inherits this behavior: it will also attempt to use the PK
   lock, which creates the same potential for concurrent double-population as other uncovered
   INFORMATIONAL platforms.

2. **Firebolt risk assessment**: the window is theoretical for Firebolt because (a) Firebolt
   is an OLAP engine unlikely to run concurrent multi-process setup workers, and (b) Firebolt
   does not commonly run `write_primitives` / `transaction_primitives` (OLTP-style tests).
   The risk is noted here for completeness; a follow-up can add dialect disambiguation
   (e.g., a `platform_name` field on CompatibilityContext) if Firebolt benchmarking expands.

3. **Tracking**: This is documented as a KNOWN_CONFLICT in the audit table above. It does not
   block w5 because the Firebolt case cannot be expressed in the current registry without
   risking incorrect classification of the NATIVE postgres-dialect platforms.

## Platforms Not Requiring a Rule (NATIVE, already covered, or out-of-scope)

Platforms with no registry rule after w5 completes, and why that is correct:

| platform_key | dialect | reason |
|---|---|---|
| duckdb | duckdb | NATIVE; fallback=False correct |
| motherduck | duckdb | NATIVE; covered by duckdb dialect rule (same fallback) |
| sqlite | sqlite | NATIVE; fallback=False correct |
| postgresql | postgres | NATIVE; fallback=False correct |
| cedardb | postgres | NATIVE; fallback=False correct |
| pg_duckdb | postgres | NATIVE; fallback=False correct |
| pg_mooncake | postgres | NATIVE; fallback=False correct |
| timescaledb | postgres | NATIVE; fallback=False correct |
| singlestore | mysql | NATIVE; fallback=False correct |
| firebolt | postgres | Known conflict (see above); left unregistered |
| polars-df | — | DataFrame only; out of scope |
| pandas-df | — | DataFrame only; out of scope |
| cudf | — | DataFrame only; out of scope |
