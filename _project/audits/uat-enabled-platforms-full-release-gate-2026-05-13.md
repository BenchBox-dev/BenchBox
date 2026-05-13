---
develop_sha: 3b351c000321dc80d9bdd3a9730db59a09f0d046
---

# UAT Enabled Platforms Full Release Gate - 2026-05-13

## Command

```bash
BENCHBOX_OUTPUT_DIR=/Users/joe/Developer/benchmark_runs \
  make uat-sweep CONFIG=tests/uat/configs/uat-enabled-platforms-full.yaml
```

Run root: `/Users/joe/Developer/benchmark_runs/logs/uat_enabled_platforms_full_20260513`

Checked commit: `0fc3d78b1` plus the release-gate config added in this branch.

## Outcome

The release gate is not green. The sweep completed without phase aborts and Docker
lifecycle was clean, but execution and validation returned nonzero:

```json
{
  "preflight": 0,
  "enumerate": 0,
  "execute": 1,
  "validate": 1,
  "package": 0,
  "explorer_smoke": 0,
  "report": 0
}
```

Matrix summary:

| Platform | Passed | Failed | Timed out |
|---|---:|---:|---:|
| lakesail | 18 | 0 | 0 |
| pg-duckdb | 7 | 15 | 0 |
| pg-mooncake | 1 | 21 | 0 |
| timescaledb | 7 | 14 | 1 |

Overall accounting: 88 candidates, 84 executed, 4 compatibility-pruned,
33 passed, 50 failed, 1 timed out.

## Compatibility Pruning

The four pruned cells were all LakeSail benchmark gates backed by SQL
compatibility registry rules:

- `lakesail/write_primitives`
- `lakesail/metadata_primitives`
- `lakesail/transaction_primitives`
- `lakesail/ai_primitives`

Follow-up remediation added registry-backed benchmark gates for three
PostgreSQL-family structural gaps, so the next enumeration should prune 13
cells total: the four LakeSail cells above plus these nine cells:

- `pg-duckdb/ai_primitives`
- `pg-duckdb/read_primitives`
- `pg-duckdb/vector_search`
- `pg-mooncake/ai_primitives`
- `pg-mooncake/read_primitives`
- `pg-mooncake/vector_search`
- `timescaledb/ai_primitives`
- `timescaledb/read_primitives`
- `timescaledb/vector_search`

## Validation And Explorer

`validator_rollup.tsv` was emitted. LakeSail validation was clean for all
submittable bundles except:

- `tpcds`: `refused-by-cli` because `compliance_class=unofficial_subscale`.
- `vector_search`: `warning_only` with two warnings.

Explorer external-corpus smoke passed against the packaged run corpus:

- `explorer_corpus_contract.json`: 32 bundles, 17 benchmarks, 4 platforms,
  4100 queries.
- `playwright_smoke.log`: `@uat-external-corpus` Chromium smoke, 1 passed.

## Remaining Red Cells

The gate still needs a follow-up remediation pass for the PG extension and
TimescaleDB cells. The most visible signatures from this run:

- `timescaledb/tpchavoc`: timed out at 600s after repeated 15s Q20 variants;
  earlier in the cell, `17_v4` also failed with missing `dual`.
- `datavault`: query 1 failed on `INTERVAL 90 DAY` syntax. Fixed by rendering
  `INTERVAL '90 days'`; targeted `pg-duckdb/datavault` UAT passed at
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_duckdb_fixcheck_20260513/pg-duckdb_datavault_0.01_20260513_125018.log`.
- `flightdata`: PostgreSQL-family engines rejected `ROUND(double precision,
  integer)`. Fixed by dialect-rendering FlightData `ROUND()` inputs as numeric;
  targeted `pg-duckdb/flightdata` UAT passed at
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_duckdb_fixcheck_20260513/pg-duckdb_flightdata_0.01_20260513_125001.log`.
- `tpcds`: PostgreSQL COPY was stripping trailing fields from TPC-DS `.dat`
  files, causing empty tables and validation failure. Fixed by preserving `.dat`
  trailing delimiters. Targeted `pg-duckdb/tpcds` now passes load validation and
  executes 99/103 queries, but remains PARTIAL with Q36/Q70/Q86/Q90 failed:
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_duckdb_fixcheck_20260513/pg-duckdb_tpcds_0.01_20260513_125030.log`.
- `amplab`: PostgreSQL-family engines rejected AMPLab queries that referenced
  SELECT aliases in HAVING (`visit_count`, `total_visits`). Fixed by repeating
  the aggregate expressions in HAVING. Targeted `pg-duckdb/amplab` passed:
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_duckdb_fixcheck_20260513b/pg-duckdb_amplab_0.01_20260513_130249.log`.
- `clickbench`: PostgreSQL CSV COPY treated empty fields as NULL despite the
  ClickBench dialect requiring empty-string preservation, causing NOT NULL load
  failures on `Referer`. Fixed by emitting a non-empty NULL sentinel when
  `csv_null_marker=None`. Targeted `pg-duckdb/clickbench` passed:
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_duckdb_fixcheck_20260513b/pg-duckdb_clickbench_1.0_20260513_130253.log`.
- `joinorder` / `tpcds_obt`: PostgreSQL COPY can now stream Parquet inputs
  through PyArrow CSV batches instead of failing immediately with "Parquet is
  not supported". JoinOrder also omits canonical IMDb foreign keys by default
  because the dataset contains dangling references. Targeted `pg-duckdb/joinorder`
  now reaches query execution but timed out at 600s:
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_duckdb_fixcheck_20260513d/pg-duckdb_joinorder_1.0_20260513_131609.log`.
  Targeted `pg-duckdb/tpcds_obt` no longer hit the temp-file disk exhaustion,
  but failed after the previous timeout with a closed socket:
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_duckdb_fixcheck_20260513d/pg-duckdb_tpcds_obt_1.0_20260513_132611.log`.
  Docker Desktop then reported a project-scoped remove failure against
  containerd metadata; the container could not be removed cleanly in-session.
- `metadata_primitives`: `large_catalog_column_count` divided by zero when no
  generated catalog tables existed. Fixed by guarding the average denominator
  with `NULLIF` / `nullIf`. Targeted `pg-duckdb/metadata_primitives` passed:
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_duckdb_fixcheck_20260513e/pg-duckdb_metadata_primitives_1.0_20260513_155557.log`.
- `tpcdi`: PostgreSQL-family query rendering now rewrites SQLite `JULIANDAY`
  date arithmetic, boolean-to-integer comparisons, and PostgreSQL-invalid alias
  references in `A5`, `AQ10`, and `EQ7`. Targeted `pg-duckdb/tpcdi` passed:
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_duckdb_fixcheck_20260513f/pg-duckdb_tpcdi_0.01_20260513_155734.log`.
- `write_primitives`: PostgreSQL-family operation execution now rewrites
  DuckDB `unnest(generate_series(...))` to PostgreSQL `generate_series(...)`,
  rolls back failed operation attempts so one unsupported query does not poison
  the connection, exports skipped operation rows without counting them as
  failures, and has registry-backed execution filters for the server-side
  bulk-load path, DuckDB DataSketches SQL, and PostgreSQL-incompatible MERGE
  variants. Targeted `pg-duckdb/write_primitives` passed with 64 executed
  operations and 67 compatibility skips:
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_duckdb_fixcheck_20260513l/pg-duckdb_write_primitives_0.01_20260513_161717.log`.
- `transaction_primitives`: PostgreSQL-family operation execution now rewrites
  `unnest(generate_series(...))`, rewrites isolation-level transaction starts
  to PostgreSQL `BEGIN TRANSACTION ISOLATION LEVEL ...`, fixes
  `transaction_commit_large` cleanup to be repeatable across warmup/measurement
  runs, and has pg_duckdb-specific execution filters for SAVEPOINT and
  non-default isolation-level gaps. Targeted `pg-duckdb/transaction_primitives`
  passed with 19 executed operations and 4 compatibility skips:
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_duckdb_fixcheck_20260513n/pg-duckdb_transaction_primitives_0.01_20260513_162215.log`.
- `pg-mooncake/amplab`: fresh rerun after Docker recovery no longer reproduced
  the sweep's `max_wal_senders` promotion failure, but intermittently failed
  measured query execution with `DuckDB execution is not supported inside
  functions`. Fixed by closing pg_mooncake query transaction boundaries before
  and after each benchmark SELECT, with a one-shot retry for that exact
  pg_mooncake transient error. Targeted `pg-mooncake/amplab` passed:
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_mooncake_fixcheck_20260513_amplab_retry.log`.
- `pg-mooncake/h2odb`, `pg-mooncake/coffeeshop`, `pg-mooncake/ssb`,
  `pg-mooncake/clickbench`, and `pg-mooncake/tpcdi`: targeted reruns passed
  after the pg_mooncake transaction-boundary fix and prior PostgreSQL-family
  SQL/data-loading fixes:
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_mooncake_fixcheck_20260513_h2odb.log`,
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_mooncake_fixcheck_20260513_coffeeshop.log`,
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_mooncake_fixcheck_20260513_ssb.log`,
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_mooncake_fixcheck_20260513_clickbench.log`,
  and
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_mooncake_fixcheck_20260513_tpcdi.log`.
- `pg-mooncake/write_primitives` and `pg-mooncake/transaction_primitives`:
  the Docker pg_mooncake stack now starts PostgreSQL with
  `max_wal_senders=128`, `max_replication_slots=128`, and `wal_level=logical`
  so multi-cell UAT promotion does not exhaust the default sender limit.
  After that provisioning fix, `write_primitives` reached execution but failed
  setup against mooncake mirror tables with `DuckDB does not support
  modififying Postgres tables`; `transaction_primitives` failed in the same
  TPC-H corpus promotion/write path with Moonlink duplicate replication
  registration. Added pg-mooncake-only benchmark gates for both write-heavy
  primitive benchmarks:
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_mooncake_fixcheck_20260513_write_primitives_retry.log`
  and
  `/Users/joe/Developer/benchmark_runs/logs/uat_pg_mooncake_fixcheck_20260513_transaction_primitives.log`.
- `timescaledb/amplab`, `timescaledb/clickbench`, `timescaledb/tpcdi`, and
  `timescaledb/write_primitives`: targeted reruns passed after the shared
  PostgreSQL-family SQL/data-loading and primitive operation fixes:
  `/Users/joe/Developer/benchmark_runs/logs/uat_timescaledb_fixcheck_20260513_amplab.log`,
  `/Users/joe/Developer/benchmark_runs/logs/uat_timescaledb_fixcheck_20260513_clickbench.log`,
  `/Users/joe/Developer/benchmark_runs/logs/uat_timescaledb_fixcheck_20260513_tpcdi.log`,
  and
  `/Users/joe/Developer/benchmark_runs/logs/uat_timescaledb_fixcheck_20260513_write_primitives.log`.
- `timescaledb/transaction_primitives`: targeted rerun exposed only
  `transaction_isolation_repeatable_read` and
  `transaction_isolation_serializable` failures with `SET TRANSACTION ISOLATION
  LEVEL must be called before any query`. Added TimescaleDB-specific execution
  filters for those two operations; retry passed with 21 executed operations and
  2 compatibility skips:
  `/Users/joe/Developer/benchmark_runs/logs/uat_timescaledb_fixcheck_20260513_transaction_primitives_retry.log`.
- `timescaledb/tpcds`: targeted rerun now clears schema creation, `.dat` load,
  and table validation. It remains PARTIAL on query execution with Q36, Q70,
  and Q86 failing on the `lochierarchy` alias in `ORDER BY`, plus Q90 failing
  with division by zero:
  `/Users/joe/Developer/benchmark_runs/logs/uat_timescaledb_fixcheck_20260513_tpcds.log`.
- Remaining PG extension and TimescaleDB cells still need per-log clustering
  before they can be fixed or converted to evidence-backed compatibility rules.

No raw UAT logs, result bundles, screenshots, or browser reports are committed.
