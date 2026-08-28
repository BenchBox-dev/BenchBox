# BenchBox Platform Configuration Audit

```{tags} contributor, reference
```

Adversarial sweep of the configs BenchBox **forces or defaults** per platform. Each bullet names the
file and line span plus the rationale/impact. Focus is on forced session toggles, caches, memory
limits, and DDL rewrites that diverge from vendor defaults.

## Connection/Network Settings (justified)

Infrastructure-level configurations for connection stability. These are distinct from query-level
behavior and are standard practice for OLAP workloads with long-running queries.

- ClickHouse - connection timeouts (`benchbox/platforms/clickhouse/setup.py:91-93,121-123`):
  `connect_timeout=30`, `send_receive_timeout=300`, `sync_request_timeout=300`. Socket-level timeouts
  prevent hanging connections; distinct from query-level `max_execution_time`.
- Redshift - TCP keepalive (`benchbox/platforms/redshift.py:873-877`): `tcp_keepalive=True`,
  `tcp_keepalive_idle=600`, `tcp_keepalive_interval=30`, `tcp_keepalive_count=3`. Prevents connection
  drops on long-running OLAP queries; standard practice for cloud data warehouses.
- Redshift - connect timeout (`benchbox/platforms/redshift.py:94`): `connect_timeout=10` (default).
  Controls initial connection establishment; distinct from `statement_timeout`.
- Redshift - application name (`benchbox/platforms/redshift.py:873,890`): `application_name="BenchBox"`.
  Identifies connection source in `pg_stat_activity`; standard practice for connection tracking.
- SQLite - lock timeout (`benchbox/platforms/sqlite.py:181,204`): `timeout=30.0`. Controls behavior
  when database is locked; reasonable default for concurrent access scenarios.

## Justified Configurations (keep)
- BigQuery - `use_legacy_sql=False` and `flatten_results=False` for OLAP
  (`benchbox/platforms/bigquery.py:1083-1106`): avoids legacy dialect and nested flattens that would
  break TPC-style SQL and row shape expectations.
- BigQuery - dataset naming/staging defaults (`benchbox/platforms/bigquery.py:61-103`): safe
  scaffolding to ensure runs land in isolated, repeatable locations.
- ClickHouse - `use_uncompressed_cache=0` and MergeTree PK enforcement
  (`benchbox/platforms/clickhouse/tuning.py:40-42,52-71`): prevents pathological memory bloat and
  satisfies engine requirements.
- ClickHouse - base execution caps (`max_memory_usage`, `max_execution_time`, `max_threads`) and
  server memory ratio 0.8 (`benchbox/platforms/clickhouse/setup.py:16-61`): guardrails against OOM
  on shared hosts, aligned with recent memory incident.
- DataFusion - repartitioning/pruning/batch size, disk spill via `with_disk_manager_os()`, and memory pool
  (`benchbox/platforms/datafusion.py:213-248,232-237`): necessary for stable OLAP execution; disk spilling
  avoids outright failure under pressure. Note: disk manager is always enabled when RuntimeEnvBuilder
  is available and uses system temp directory if temp_dir is not specified.
- DuckDB - memory_limit (default 4GB), thread_limit, max_temp_directory_size, and default_order='ASC'
  (`benchbox/platforms/duckdb.py:172-237,205-227`): practical guardrails with user overrides; avoids
  unlimited growth. Settings applied via `SET memory_limit`, `SET threads TO`, `SET max_temp_directory_size`,
  and `SET default_order = 'ASC'` (OLAP optimization).
- Redshift - `enable_case_sensitive_identifier=OFF`, `datestyle='ISO, MDY'`, `extra_float_digits=0`
  (`benchbox/platforms/redshift.py:1299-1345`): keeps canonical identifier/locale behavior for
  benchmarks; matches example justification.
- Redshift - search_path and autocommit (`benchbox/platforms/redshift.py:821-918`): ensures objects
  land in the intended schema and avoids transaction state surprises.
- Snowflake - Standard warehouse/database/schema defaults and timezone/autocommit settings
  (`benchbox/platforms/snowflake.py:51-88,752-819`): predictable session context for benchmarks.
- SQLite - PRAGMAs for WAL, foreign_keys=ON, synchronous=NORMAL, cache_size=10000 (~40MB), temp_store=MEMORY
  (`benchbox/platforms/sqlite.py:209-224`): common performance/durability balance for analytic
  workloads. The cache_size setting significantly affects memory footprint and query performance.
- SQLite - OLTP path `synchronous=FULL` safeguard (`benchbox/platforms/sqlite.py:316-324`): preserves
  durability when explicitly running OLTP-style tests.

## Excess Configurations (consider removal/opt-in)
- Snowflake - `ERROR_ON_NONDETERMINISTIC_MERGE=FALSE` and `ERROR_ON_NONDETERMINISTIC_UPDATE=FALSE`
  (`benchbox/platforms/snowflake.py:774-778`). **RESOLVED**: Now opt-in via
  `suppress_nondeterministic_errors=True` in config (default: `False`). These settings are unnecessary
  for TPC-H/TPC-DS which don't use MERGE/UPDATE operations.
- ClickHouse - experimental correlated subqueries on by default and aggressive OLAP join/spill tuning
  (`benchbox/platforms/clickhouse/tuning.py:52-118`). Impact if removed: plans revert to safer
  defaults; correlated-subquery TPC-H cases may fail or change results. Tests to confirm: quick TPC-H
  smoke `benchbox run --platform clickhouse-local --benchmark tpch --scale 0.01 --phases power --non-interactive`
  and targeted query validation for Q2/4/17/20/21/22.
- DataFusion - memory_limit=16G default and identifier normalization flag
  (`benchbox/platforms/datafusion.py:101-169,213-299`). Impact if removed: risk of OOM on large data
  unless user sets limit; identifier casing may differ but matches engine defaults. Note: identifier
  normalization uses soft failure (silent fallback to PostgreSQL defaults if setting not available).
  Tests to confirm: fast suite `uv run -- python -m pytest -m fast -k datafusion` and TPC-H smoke
  `benchbox run --platform datafusion --benchmark tpch --scale 0.01 --phases power --non-interactive`.
- DuckDB - `default_order='ASC'` OLAP bias (`benchbox/platforms/duckdb.py:172-237`). Impact if
  removed: planner uses DuckDB defaults; ordering-dependent plans may differ slightly. Tests to
  confirm: fast DuckDB path `uv run -- python -m pytest -m fast -k duckdb` and TPC-H smoke
  `benchbox run --platform duckdb --benchmark tpch --scale 0.01 --phases power --non-interactive`.
- Databricks - Delta auto_optimize/auto_compact, ANALYZE TABLE post-tuning, and forced Delta rewrite
  of CREATE TABLE (`benchbox/platforms/databricks/adapter.py:61-95,1422-1458,1730-1738`). When
  `enable_delta_optimization=True` (default), runs OPTIMIZE and ANALYZE TABLE after tuning. Impact if
  removed: fewer automatic OPTIMIZE/compaction costs; tables may stay in source format; query planner
  has less statistics. Disable via `enable_delta_optimization=False` in config. Tests to confirm:
  Databricks integration suite (if available) or manual smoke load/query of TPCH SF0.01 with and
  without rewrites (`benchbox run --platform databricks --benchmark tpch --scale 0.01 --phases load,power`).
- Databricks - cluster_size “Medium” default and 30m auto-terminate
  (`benchbox/platforms/databricks/adapter.py:61-95`). Impact if removed: warehouse sizing/terminate
  policy defer to workspace defaults; cost/perf may shift. Tests to confirm: run same TPCH SF0.01
  twice (with default sizing vs. explicit) and compare timings/costs; minimal regression risk aside
  from longer startup/terminate behavior.
- Redshift - `query_group='benchbox'` and 30m statement_timeout defaults
  (`benchbox/platforms/redshift.py:1299-1345`). Impact if removed: workload tagging and timeout fall
  back to cluster defaults; risk of runaway queries without timeout, but aligns with customer WLM.
  Tests to confirm: Redshift integration tests or TPCH SF0.01 smoke
  `benchbox run --platform redshift --benchmark tpch --scale 0.01 --phases power --non-interactive`
  ensuring no WLM/timeout regressions.
- Redshift - auto_vacuum/auto_analyze triggered post-load (`benchbox/platforms/redshift.py:1329-1364`)
  and COPY `compupdate=PRESET` (`benchbox/platforms/redshift.py:128-158`). Impact if removed: table
  stats/encoding rely on cluster policies; possible slower queries on fresh loads but less implicit
  maintenance. Tests to confirm: load + power run TPCH SF0.01 and compare query latencies; check
  PG_TABLE_DEF stats presence post-load.
- Snowflake - query acceleration max scale factor=8, query_tag, and **ALTER WAREHOUSE** settings
  (`benchbox/platforms/snowflake.py:768,786,797-817`). **RESOLVED**: ALTER WAREHOUSE changes
  (size, auto-suspend, scaling policy) PERSIST beyond benchmark run. Now controlled via
  `modify_warehouse_settings=False` (default). Set to `True` via config or CLI to opt-in to warehouse
  modifications. Query tag (`QUERY_TAG='BenchBox_optimization'`) still applied.

  These are adapter configuration keys, not `benchbox run` options: set
  `modify_warehouse_settings`, `suppress_nondeterministic_errors`, and
  `disable_result_cache` when constructing the adapter.

  **Config usage**: Set `modify_warehouse_settings: true` in your platform config to enable warehouse
  modifications. Set `suppress_nondeterministic_errors: true` for nondeterministic workloads.

  Tests to confirm: Snowflake TPCH SF0.01 power run with/without overrides and compare runtimes and
  credit usage (`benchbox run --platform snowflake --benchmark tpch --scale 0.01 --phases power --non-interactive`).
