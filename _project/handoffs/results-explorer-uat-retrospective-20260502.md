# Results Explorer UAT Retrospective - 2026-05-02

## W1 Pre-Flight

Status: passed after the free-space cutoff was revised from ~50 GiB to ~40 GiB.

- Output root: `~/Developer/benchmark_runs` (`BENCHBOX_OUTPUT_DIR` unset, so default applies).
- Free space: `46 GiB` available on `/System/Volumes/Data`, above the revised ~40 GiB cutoff.
- Docker: reachable; `docker ps` showed no running containers.
- Docker Desktop: `MemTotal=12,528,578,560`, `NCPU=10`.
- Host CPUs: `sysctl -n hw.ncpu hw.logicalcpu hw.physicalcpu` reported `10 / 10 / 10`.
- Host noise: current load is acceptable for a sequential UAT sweep on 10 cores; no process was killed.

## W2 Run Matrix

Sources:

- `scripts/local_stress_test.sh`, read only for platform groupings, TCP probes, uv extras, platform options, and CLI flags.
- `benchbox.core.benchmark_registry`, queried live with `uv run --no-sync -- python`.

### Platform Groups

| Group | Platforms |
| --- | --- |
| Fast native SQL | `duckdb`, `datafusion`, `lakesail`, `clickhouse-local` |
| Fast Docker SQL | `clickhouse-server`, `cedardb`, `starrocks` |
| Slow native SQL | `sqlite`, `spark` |
| Slow Docker SQL | `postgresql`, `presto`, `trino`, `databend`, `doris`, `influxdb`, `pg-duckdb`, `pg-mooncake`, `timescaledb`, `questdb`, `singlestore`, `velox` |
| DataFrame | `polars-df`, `pandas-df`, `modin-df`, `pyspark-df`, `dask-df`, `datafusion-df` |

SQL platforms: 21. DataFrame platforms: 6. Cloud platforms remain deferred by the TODO.

### Platform Modifiers

| Platform | TCP probe | uv mode | Extra benchbox args |
| --- | --- | --- | --- |
| `clickhouse-local` | none | `uv run --extra clickhouse-local --` | none |
| `clickhouse-server` | `localhost:9000` | `uv run --no-sync --` | none |
| `cedardb` | `localhost:5435` | `uv run --no-sync --` | none |
| `starrocks` | `localhost:19030` | `uv run --no-sync --` | `--platform-option port=19030 --platform-option http_port=18040` |
| `postgresql` | `localhost:5432` | `uv run --no-sync --` | none |
| `presto` | `localhost:18081` | `uv run --no-sync --` | none |
| `trino` | `localhost:18080` | `uv run --no-sync --` | none |
| `databend` | `localhost:8000` | `uv run --no-sync --` | none |
| `doris` | `localhost:19031` | `uv run --no-sync --` | `--platform-option port=19031 --platform-option http_port=18030 --platform-option be_http_port=18040` |
| `influxdb` | `localhost:8181` | `uv run --extra influxdb --` | none |
| `pg-duckdb` | `localhost:5432` | `uv run --no-sync --` | none |
| `pg-mooncake` | `localhost:5432` | `uv run --no-sync --` | none |
| `timescaledb` | `localhost:5432` | `uv run --no-sync --` | none |
| `questdb` | `localhost:8812` | `uv run --no-sync --` | `--platform-option http_port=19000` |
| `singlestore` | `localhost:13306` | `uv run --extra singlestore --` | `--platform-option port=13306 --platform-option password=benchbox` |
| `velox` | `localhost:50051` | `uv run --no-sync --` | `--platform-option deployment=remote --platform-option endpoint=sc://localhost:50051 --iterations 1` |

All other native SQL and DataFrame platforms use `uv run --no-sync --` with no TCP probe and no extra platform options.

### Benchmark Scale Ladder

Target scales: `0.01`, `0.1`, `1.0`; filter by registry `min_scale` / `max_scale`.

| Category | Benchmark | DataFrame? | Registry min | Registry max | UAT scales |
| --- | --- | --- | --- | --- | --- |
| TPC | `tpch` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| TPC | `tpcds` | yes | none | none | `0.01`, `0.1`, `1.0` |
| TPC | `tpcdi` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Primitives | `read_primitives` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Primitives | `write_primitives` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Primitives | `metadata_primitives` | yes | `1.0` | none | `1.0` |
| Primitives | `transaction_primitives` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Primitives | `ai_primitives` | no | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Industry | `clickbench` | yes | `1.0` | none | `1.0` |
| Industry | `h2odb` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Industry | `coffeeshop` | yes | `0.001` | none | `0.01`, `0.1`, `1.0` |
| Academic | `ssb` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Academic | `amplab` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Academic | `joinorder` | yes | `1.0` | none | `1.0` |
| Time Series | `tsbs_devops` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Real World | `nyctaxi` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Real World | `flightdata` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| AI/ML | `vector_search` | no | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Experimental | `tpcds_obt` | yes | `1.0` | none | `1.0` |
| Experimental | `tpchavoc` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Experimental | `tpch_skew` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Experimental | `datavault` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |

SQL-only benchmarks: `ai_primitives`, `vector_search`.

Candidate cells before reachability checks and scale-ladder early stops:

- SQL: 58 cells per SQL platform x 21 platforms = 1,218 cells.
- DataFrame: 52 cells per DataFrame platform x 6 platforms = 312 cells.
- Total: 1,530 candidate cells.

### W3 Execution Template

Per cell, adapt platform modifiers above:

```bash
[timeout-backend] 600 uv run [--no-sync | --extra <extra>] -- \
  benchbox run \
  --platform <platform> \
  --benchmark <benchmark> \
  --scale <scale> \
  --phases load,power \
  --non-interactive \
  [platform options] \
  [platform CLI flags]
```

Timeout backend check: this host currently has neither `timeout` nor `gtimeout`; `/usr/bin/perl` is available. W3 must use
the same real-timeout Perl fallback pattern from `scripts/local_stress_test.sh` or install/use `gtimeout` before executing
cells. Do not run cells without a hard 600-second wall-clock cap.

Run order should stay sequential by platform, with scale ladder order `0.01 -> 0.1 -> 1.0` per platform/benchmark pair.

Database cleanup is part of W3. Preserve generated source data under
`~/Developer/benchmark_runs/datagen/` while later platforms can reuse it, but prune loaded local database artifacts under
`~/Developer/benchmark_runs/databases/` after safe reuse boundaries. The important boundary is source/scale reuse: do not
delete TPC-H loaded databases immediately after `tpch`, because TPC-H data is reused by `read_primitives`,
`write_primitives`, `transaction_primitives`, and `ai_primitives`. Prefer cleanup after each platform completes; mid-platform
cleanup is only safe after all consumers for the source/scale have completed.

## W3 Execution

Status: complete. The sweep was initially blocked by disk during the DuckDB ladder, then resumed after the user changed the
hard stop to 5 GiB free and requested reuse-aware database cleanup.

- Log directory: `~/Developer/benchmark_runs/logs/uat_20260502/`.
- Summary file: `~/Developer/benchmark_runs/logs/uat_20260502/matrix_summary.tsv`.
- Sentinel file: `~/Developer/benchmark_runs/logs/uat_20260502/.sweep_start`.
- Timeout backend: Perl process-group wrapper with a 600-second cap, because this host has neither `timeout` nor `gtimeout`.
- Partial counts: 46 passed, 1 failed, 1 timed out, 1 blocked-disk.
- Last completed successful cell: `duckdb/vector_search` SF 1.0.
- Next cell when resuming: `duckdb/tpcds_obt` SF 1.0.
- Hard blocker: `df -k ~/Developer/benchmark_runs` reported `41,432,632 KiB` available, below the revised 40 GiB cutoff
  of `41,943,040 KiB`.
- User override: do not stop on the 40 GiB cutoff; treat free space as telemetry unless available space falls below 5 GiB.
- Cleanup override: add reuse-aware loaded-database cleanup so disk growth stays bounded. Preserve reusable datagen inputs.
- Resume interruption note: the first post-override resume was stopped to add cleanup. The `duckdb/tpcds_obt` SF 1.0
  `exit=143` row in `matrix_summary.tsv` is an operator interruption and should be retried, not triaged as a benchmark
  defect.
- Cleanup action: after the DuckDB TPC-H-source consumers were complete, pruned DuckDB loaded database files under
  `~/Developer/benchmark_runs/databases/` while preserving datagen. `df -k ~/Developer/benchmark_runs` moved from
  `39,260,012 KiB` available to `40,889,044 KiB` available; `du -ck` reported `6,604,732 KiB` of DuckDB database files.

Known non-blocking W4 triage inputs from the partial run:

- `duckdb/clickbench` SF 1.0 failed quickly. Log:
  `~/Developer/benchmark_runs/logs/uat_20260502/duckdb_clickbench_1.0_20260502_164814.log`.
  Last signal: `NOT NULL constraint failed: hits.Referer`, then data validation halted with empty `hits`.
- `duckdb/flightdata` SF 1.0 timed out after the 600-second cap. Log:
  `~/Developer/benchmark_runs/logs/uat_20260502/duckdb_flightdata_1.0_20260502_170040.log`.
  Last signal: still generating benchmark data.

### W3 Completion Summary

Interpret `matrix_summary.tsv` by latest `(platform, benchmark, scale)` row. The file intentionally contains earlier duplicate
rows from the old disk cutoff and the operator-interrupted cleanup-rule resume.

| Metric | Count |
| --- | ---: |
| Candidate cells | 1,530 |
| Real attempted terminal cells | 527 |
| Passed cells | 434 |
| Captured unique result JSON paths | 388 |
| Failed | 85 |
| Timed out at 600 seconds | 8 |
| Skipped by scale-ladder pruning | 133 |
| Skipped because TCP platform unreachable | 870 |

All 388 captured result JSON paths exist. The 46 passed cells without captured paths are early DuckDB rows from before the
result-path extractor was improved; recover them from the per-run logs/result directory before W5 submission.

Platform latest-status counts:

| Platform | Latest status counts |
| --- | --- |
| `duckdb` | passed 55, failed 1, timed-out 2 |
| `datafusion` | passed 43, failed 7, skipped-ladder-pruned 8 |
| `lakesail` | failed 22, skipped-ladder-pruned 36 |
| `clickhouse-local` | passed 54, failed 2, timed-out 1, skipped-ladder-pruned 1 |
| `sqlite` | passed 35, failed 5, timed-out 3, skipped-ladder-pruned 15 |
| `spark` | passed 28, failed 11, skipped-ladder-pruned 19 |
| `polars-df` | passed 48, failed 2, skipped-ladder-pruned 2 |
| `pandas-df` | passed 49, failed 1, skipped-ladder-pruned 2 |
| `modin-df` | failed 20, skipped-ladder-pruned 32 |
| `pyspark-df` | passed 40, failed 4, timed-out 1, skipped-ladder-pruned 7 |
| `dask-df` | passed 34, failed 8, timed-out 1, skipped-ladder-pruned 9 |
| `datafusion-df` | passed 48, failed 2, skipped-ladder-pruned 2 |
| TCP SQL platforms | 15 platforms x 58 cells = 870 skipped-unreachable |

### W3 Cleanup Notes

Cleanup log: `~/Developer/benchmark_runs/logs/uat_20260502/database_cleanup_20260502.log`.

- Preserved reusable generated source data in `~/Developer/benchmark_runs/datagen/` for cross-platform reuse.
- Pruned loaded database artifacts at safe reuse boundaries, including DuckDB after TPC-H-source consumers, ClickHouse Local
  at a mid-platform safe boundary and platform completion, and SQLite at mid-platform/platform completion boundaries.
- Removed worktree-local Spark warehouse directories only after Spark/PySpark platform completion. The Spark SQL cleanup found
  35 loaded warehouse directories with `du_kib=2,637,172`; APFS reported `df_delta_kib=351,092` immediately after removal.
- Dask had transient free-space dips during exit-137 cells, but released the space when the subprocess exited. Free space never
  fell below the user-defined 5 GiB hard stop.
- Ignore the malformed ClickHouse Local cleanup row with empty timestamp/`after_kib`; the immediately following
  `mid-platform-safe-boundary-corrected` row is the valid cleanup record.
- Post-W5 cleanup recheck found no remaining loaded database artifacts under `~/Developer/benchmark_runs/databases/`. The
  remaining UAT steps should operate from submitted bundles and explorer snapshots, not by generating or loading more
  benchmark databases.

### W4 Triage Inputs

Cluster these before filing follow-up defect TODOs:

- Partial success exits: several platforms returned a passed cell while logs contained query failures, including Spark/SQLite
  TPCHavoc, DataFusion SQL transaction primitives, Pandas/PySpark read primitives, and Dask ClickBench before timeout.
- FlightData SF 1.0: failed on DataFusion SQL, ClickHouse Local, Polars, PySpark, Dask, and DataFusion DataFrame; Pandas passed.
- Lakesail: every first-rung cell failed; logs point to missing `pysail` and no Sail server at `sc://localhost:50051`.
- Modin DataFrame: every first-rung cell failed immediately; likely missing backend/runtime setup.
- Dask DataFrame: repeated exit 137/resource-spike failures on TPC-H, TPC-DS SF 0.1, read primitives SF 1.0, FlightData, and
  TPCHavoc; Dask ClickBench timed out at 600 seconds.
- Spark/PySpark: expression and analysis failures, including scalar-subquery grouping, missing `dual`, unresolved supplier
  columns in TPCHavoc variants, and type handling in read primitives.
- SQLite: slow cells and timeouts in TPC-H-source workloads; TPC-DS OBT exited 137; several cells returned partial results with
  query-level failures.
- DuckDB: ClickBench SF 1.0 failed during load with `NOT NULL constraint failed: hits.Referer`; FlightData and TPCHavoc hit the
  600-second cap.
- TCP-backed SQL platforms: 15 platforms were skipped-unreachable because local ports were not listening; classify as local
  environment, not benchmark defects.

## W4 Failure Triage

Status: classified. No trivial config/syntax fix was applied in W4. The failures either require environment provisioning
(`pysail`, Modin backend, TCP services), exceed the 600-second/local-resource budget, or require benchmark/platform code changes
that are explicitly out of scope for this UAT TODO.

| Bucket | Rows | Classification | Representative evidence |
| --- | ---: | --- | --- |
| TCP SQL platforms unreachable | 870 skipped | Environment | 15 TCP-backed platforms had closed local ports; no benchmark command was attempted. |
| Lakesail | 22 failed, 36 pruned | Environment | `lakesail_tpch_0.01_20260502_183842.log:8`: missing `pysail` and no Sail server at `sc://localhost:50051`. |
| Modin DataFrame | 20 failed, 32 pruned | Environment | `modin-df_tpch_0.01_20260502_212808.log:1`: platform unavailable due missing dependencies. |
| Dask resource exits | 5 exit-137 failures | Environment/resource budget | Summary rows show exit 137 for TPC-H, TPC-DS SF 0.1, read primitives SF 1.0, FlightData, and TPCHavoc. |
| 600-second timeouts | 8 timed out | Deferred too slow | DuckDB FlightData/TPCHavoc, ClickHouse Local read primitives, SQLite read/write/TPCHavoc, PySpark TPCHavoc, Dask ClickBench. |
| FlightData corpus/loader failures | 8 failed, 1 timed out | Deferred engineering | `datafusion_flightdata_1.0_20260502_182841.log:13`, `clickhouse-local_flightdata_1.0_20260502_185846.log:15`, and `polars-df_flightdata_1.0_20260502_211319.log:8` all point to truncated/incomplete `flightdata_1.0/flights.csv.zst`. |
| Partial-success cells | multiple passed rows | Deferred engineering | `spark_tpchavoc_0.1_20260502_205516.log:5910` reports 203 passed and 17 failed queries despite a passed cell; `pandas-df_read_primitives_1.0_20260502_211633.log:145` reports completed with failures. |
| Spark/PySpark compatibility | 15 failed, 1 timed out | Deferred engineering | `spark_read_primitives_0.01_20260502_203844.log:18` strict identifier retry failure; `pyspark-df_tpcds_0.01_20260502_213449.log:17` illegal Parquet `TIME(MILLIS,false)`. |
| SQLite compatibility/perf | 5 failed, 3 timed out | Deferred engineering | `sqlite_tpcds_obt_1.0_20260502_200038.log` ended with summary `exit=137`; several SQLite cells returned passed status with query-level failures. |
| DuckDB ClickBench load | 1 failed | Deferred engineering | `duckdb_clickbench_1.0_20260502_164814.log:10` reports `NOT NULL constraint failed: hits.Referer`. |
| DataFrame transaction primitives | 4 failed | Expected unsupported surface / deferred UX | `datafusion-df_transaction_primitives_0.01_20260502_223256.log:8` says transaction primitives require ACID support. |

Follow-up TODO candidates for W7:

- `results-explorer-uat-defect-partial-success-exit-contract`: passed cells must not hide query-level failures.
- `results-explorer-uat-defect-flightdata-sf1-corpus-integrity`: repair or quarantine the truncated FlightData SF 1.0 corpus.
- `results-explorer-uat-defect-dask-resource-envelope`: define Dask resource limits, spill cleanup, and exit-137 reporting.
- `results-explorer-uat-defect-spark-pyspark-expression-compat`: group Spark/PySpark expression, Parquet, and TPCHavoc failures.
- `results-explorer-uat-defect-local-platform-provisioning`: document or automate Lakesail, Modin, and TCP service readiness.
- `results-explorer-uat-defect-sqlite-slow-partial-cells`: classify SQLite timeout and partial-result behavior.
- `results-explorer-uat-defect-duckdb-clickbench-load`: ClickBench `Referer` NOT NULL load failure.

No W4 changes were made to benchmark queries, dialect adapters, datagen, platform implementations, or the generated result
corpus.

## W5 Submission Flow

Status: Phase 2 PR-package flow exercised. No hosted `--service` upload was attempted, and no `results-data/` PR was opened
from the full staged set because local submission validation rejects too many bundles.

Entrypoints checked:

- `benchbox submit --help`: primary submission path. Default `--output` mode creates a local PR-ready package; `--service`
  is opt-in hosted upload.
- `benchbox publish --help`: storage copy/history tool, not the community submission path.
- `benchbox results --help`: result discovery/history.
- `benchbox explorer build --help`: can build an explorer data snapshot from any `DATA_DIR/bundles/` directory, which makes a
  local W6 UAT possible against a staged valid subset.

Submission artifacts:

| Artifact | Path / Count |
| --- | --- |
| Captured result paths attempted | 388 |
| Full package output | `~/Developer/benchmark_runs/submissions/uat_20260502` |
| Full package log | `~/Developer/benchmark_runs/logs/uat_20260502/submission_packaging_20260502.log` |
| Successfully packaged bundles | 376 bundles + 376 manifests |
| CLI-refused results | 12 |
| Full-package validation log | `~/Developer/benchmark_runs/logs/uat_20260502/submission_validation_20260502.log` |
| Validator-clean subset | `~/Developer/benchmark_runs/submissions/uat_20260502_valid` |
| Validator-clean subset count | 205 bundles + 205 manifests |
| Valid-subset validation log | `~/Developer/benchmark_runs/logs/uat_20260502/submission_validation_valid_20260502.log` |

Validation outcomes:

- Full staged package: `scripts/validate_submission.py` reported `Validated 376 bundle(s): 188 error(s), 212 warning(s)`.
- Valid subset: `scripts/validate_submission.py` reported `Validated 205 bundle(s): 0 error(s), 126 warning(s)`.
- The 12 CLI refusals were all TPC-DS compliance guardrails: eight `unofficial_subscale` and four `unofficial_nonstandard`
  TPC-DS results.
- The 171 validator-failing packaged bundles had two dominant error types:
  - 134 occurrences: `cost.total_usd` present while `cost_status` is `unavailable`.
  - 54 occurrences: all query timings are `0ms`.

Submission-flow friction:

- A guessed result filename fails clearly with `Path ... does not exist`; contributors still need a reliable "copy exact path"
  affordance from results history or the matrix summary.
- `benchbox submit --dry-run` exited 0 for
  `amplab_sf001_clickhouse_local_sql_20260502_185809_f2e17de5.json`, but the same bundle later failed
  `scripts/validate_submission.py` due the normalized-cost contract. This contradicts the hosted-results contract text that
  dry-run runs client-side validations.
- The real `--output` package flow is clear and prints `PR target: published-results`, which fixes the older generated
  `CONTRIBUTING.md` branch-target ambiguity noted in the April dry-runs.
- Batch submission is not built in; W5 had to loop one result at a time over captured paths.

W6 should use the validator-clean subset for local explorer UAT. The full corpus should not be copied into `results-data/` or
opened as a `published-results` PR until the invalid-bundle clusters are fixed or filtered deliberately.

Cleanup carry-forward: preserve reusable generated source data under `~/Developer/benchmark_runs/datagen/`; prune loaded
database artifacts only after all source/scale consumers have completed. At this point W6 should not require any loaded
database artifact, because it can build the explorer snapshot from `DATA_DIR/bundles/`.

## W6 Explorer UAT

Status: complete against the validator-clean subset. The explorer was built and smoke-tested from external artifacts only; no
`results-data/`, `results-explorer/public/data/`, or source code was modified.

Artifacts:

| Artifact | Path / Count |
| --- | --- |
| External UAT root | `~/Developer/benchmark_runs/explorer_uat/uat_20260502_valid` |
| Source bundles | `source/bundles/` with 205 bundles |
| Explorer data snapshot | `data/results.duckdb` plus 205 copied `data/bundles/*.json` |
| Explorer build log | `logs/explorer_build_20260503.log` |
| App build log | `logs/results_explorer_build_20260503.log` |
| Browser smoke log | `logs/playwright_smoke_20260503.log` |
| Performance log | `logs/performance_marks_20260503.log` and `.json` |
| Screenshots | `screenshots/desktop-home.png`, `desktop-query-local-filter.png`, `desktop-tpch.png`, `mobile-query-filters.png` |

Snapshot inventory:

| Check | Count |
| --- | ---: |
| `results` | 205 |
| `platform_index_rows` | 205 |
| `benchmark_rankings` | 205 |
| `benchmark_matrix_cells` | 13,146 |
| `result_detail_metrics` | 205 |
| `query_display_timings` | 9,057 |
| `query_executions` | 26,975 |
| `short_ids` | 205 |

Platform/scale coverage:

| Dimension | Counts |
| --- | --- |
| Platform | DataFusion 68, Polars 41, PySpark 34, SQLite 28, Spark 25, DuckDB 9 |
| Scale | SF 0.01 = 70, SF 0.1 = 63, SF 1.0 = 72 |
| Trust/visibility | 205 `community-submission` / `public-self-reported` |
| Deployment | 205 `local`; cloud/provider/region/instance facets are `unknown`-only |

Browser smoke:

- Used the existing static server with `--dist-dir` and `--fixture-dir` pointed at the external UAT artifacts.
- Used installed Google Chrome via Playwright `channel: "chrome"` because the bundled Playwright Chromium binary was not
  present.
- Passed terminating checks for desktop Home, desktop Query with Deployment filter, desktop TPC-H benchmark page, and mobile
  Query filter drawer.
- Horizontal overflow checks passed at 1440x1000 and 390x844.
- Performance marks on this snapshot:
  - Home: `db-init` 553.8 ms, `home-leaderboard-data` 571.0 ms, `leaderboard-render-after-data` 17.8 ms.
  - Query: `db-init` 542.6 ms, `query-workbench-render-after-db` 74.5 ms.

Explorer/submission UAT findings for W7:

- Minor: `benchbox explorer build --help` still documents `manifest.json`, but the current pipeline deletes legacy JSON
  manifests and emits only `results.duckdb` plus copied bundles.
- Minor: Query facet accessible labels are easy to match ambiguously. The Deployment `local` checkbox also partially matches
  Cost status `not_applicable_local`; exact label `local 205` was required in the smoke script.
- Minor/corpus limitation: this local-only UAT corpus validates facet rendering/filtering mechanics, but cloud/provider/region
  and instance facets are `unknown`-only. A dedicated cloud or provisioned local-service corpus is still needed for true
  cloud/container/region differentiation.
- Nit: Home load requests `/results/favicon.svg`, which is a 404 under the static test server.

Cleanup state after W6:

- `~/Developer/benchmark_runs/databases/` still had no loaded benchmark database artifacts.
- W6 generated only external explorer build/smoke artifacts under `~/Developer/benchmark_runs/explorer_uat/`.
