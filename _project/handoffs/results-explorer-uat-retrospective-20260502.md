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
