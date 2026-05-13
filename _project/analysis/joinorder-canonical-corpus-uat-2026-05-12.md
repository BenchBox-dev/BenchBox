# Canonical JoinOrder Corpus UAT Matrix - 2026-05-12

## Recommendation

Run the Issue #289 canonical corpus backfill on SQL-mode engines that executed the full 113-query canonical JoinOrder workload end to end and produced complete schema-v2 bundles with canonical dataset identity:

| Platform | Mode | Include | Evidence |
|---|---:|---:|---|
| `duckdb` | SQL | Yes | UAT result `joinorder_sf1_duckdb_sql_20260512_202135_4bd91dc4.json`: 339/339 measurement rows, 113 unique query IDs, 113 warmup IDs, canonical dataset identity present. |
| `clickhouse-local` | SQL | Yes | UAT result `joinorder_sf1_clickhouse_local_sql_20260512_223843_3d5d76b6.json`: 339/339 measurement rows, 113 unique query IDs, 113 warmup IDs, canonical dataset identity present. |
| `lakesail` | SQL | Yes | UAT result `joinorder_sf1_lakesail_sql_20260512_225022_528b8c08.json`: 339/339 measurement rows, 113 unique query IDs, 113 warmup IDs, canonical dataset identity present. |
| `datafusion` | SQL | No | Durable compatibility TODO: `_project/TODO/main/planning/joinorder-datafusion-dialect.yaml`; 113/113 fail before execution because Parquet registration exposes `f0` columns. |
| `*-df` platforms | DataFrame | No | Durable Track-2 TODO: `_project/TODO/main/planning/track2-joinorder-dataframe-coverage.yaml`; only 13 of 113 canonical queries are translated. |
| `spark` | SQL | No | Durable compatibility TODO: `_project/TODO/main/planning/joinorder-spark-dialect.yaml`; q33c failed during canonical UAT. |
| `sqlite` | SQL | No | Durable performance TODO: `_project/TODO/main/planning/joinorder-sqlite-performance.yaml`; warmup reached only 75/113 within the 7200 second backfill cell budget and emitted no result bundle. |
| `presto` | SQL | No | Durable compatibility TODO: `_project/TODO/main/planning/joinorder-presto-ddl.yaml`; schema creation fails on `PRIMARY KEY` syntax before load. |

Other Docker/server platforms are not part of this local backfill unless explicitly brought up for a later enabled-platform release gate. The broader enabled-platform UAT gate remains open; this backfill is limited to canonical JoinOrder bundles that can be made complete and validator-clean now.

## Success Criteria

- Each included platform runs `joinorder --scale 1 --phases load,power` through UAT with 113/113 logical query coverage and no failed query rows.
- Each staged bundle validates cleanly via the UAT validator rollup and `scripts/validate_submission.py`.
- Each staged bundle records `dataset_version`, `manifest_hash`, and `data_archive_hash` matching `benchbox/core/joinorder/data_manifest.toml`.
- Only complete, clean bundles are copied to `results-data/bundles/`, each with its matching `.manifest.json` sidecar.
- `results-data/corpus-inventory.json` is regenerated and the canonical `joinorder@sf1.0` cohort has three platforms.
- No old synthetic bundles remain under `results-data/bundles/joinorder_sf1_*`; canonical `joinorder_sf1_*` files are limited to the three clean backfilled bundles. Historical synthetic results stay under `joinorder_synthetic_sf1_*`.

## Commands

Long-running UAT command:

```bash
BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs make uat-sweep CONFIG=tests/uat/configs/uat-joinorder-canonical-corpus-20260512.yaml
```

Additional targeted cells used during investigation:

```bash
BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs make uat-cell PLATFORM=presto BENCHMARK=joinorder SCALE=1 PHASES=load,power TIMEOUT_S=7200 LOG_DIR=~/Developer/benchmark_runs/logs/uat_joinorder_canonical_corpus_20260512
BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs make uat-bring-up PLATFORM=lakesail TIMEOUT_S=600 BENCHMARK_RUNS_DIR=~/Developer/benchmark_runs
BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs make uat-cell PLATFORM=lakesail BENCHMARK=joinorder SCALE=1 PHASES=load,power TIMEOUT_S=7200 LOG_DIR=~/Developer/benchmark_runs/logs/uat_joinorder_canonical_corpus_20260512
```

Logs:

```text
~/Developer/benchmark_runs/logs/uat_joinorder_canonical_corpus_20260512/
```

Stop condition: stop on any included platform that fails, times out, emits fewer than 113 logical query IDs, or produces a non-submittable bundle. Do not copy partial results into `results-data/bundles/`.

## UAT Outcome

| Platform | Outcome | Log |
|---|---|---|
| DuckDB | Passed; staged and copied to corpus. | `~/Developer/benchmark_runs/logs/uat_joinorder_canonical_corpus_20260512/duckdb_joinorder_1.0_20260512_202042.log` |
| ClickHouse Local | Passed; staged and copied to corpus. | `~/Developer/benchmark_runs/logs/uat_joinorder_canonical_corpus_20260512/clickhouse-local_joinorder_1.0_20260512_223700.log` |
| LakeSail | Passed; staged and copied to corpus. | `~/Developer/benchmark_runs/logs/uat_joinorder_canonical_corpus_20260512/lakesail_joinorder_1.0_20260512_224431.log` |
| SQLite | Excluded; timed out before completing warmup, no bundle emitted. | `~/Developer/benchmark_runs/logs/uat_joinorder_canonical_corpus_20260512/sqlite_joinorder_1.0_20260512_202135.log` |
| Spark | Excluded; q33c failed, partial bundle not staged. | `~/Developer/benchmark_runs/logs/uat_joinorder_canonical_corpus_20260512/spark_joinorder_1.0_20260512_222136.log` |
| Presto | Excluded; DDL rejected before load. | `~/Developer/benchmark_runs/logs/uat_joinorder_canonical_corpus_20260512/presto_joinorder_1.0_20260512_224026.log` |

The staged submission validator passed for the three copied bundles. The corpus-level depth script now reports `joinorder SF=1.0: 3 platforms (['ClickHouse Local', 'DuckDB', 'LakeSail']) [OK]`; its process exit remains nonzero because unrelated pre-existing cohorts (`tpcds`, `ai_primitives@sf1`, and `flightdata@sf1`) are below the three-platform depth threshold.
