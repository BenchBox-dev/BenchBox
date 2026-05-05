# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Verified

- **write_primitives sketch (sweep variants)** — live SF=0.01 measurement
  of KLL `k=100` and `k=1000` sweep variants on DuckDB 1.3.2 +
  datasketches extension `2e38607`. Observed merged sketch sizes:
  `kll_k100` 2508 bytes (within `[500, 5000]`), `kll_k1000` 21220 bytes
  (within `[5000, 40000]`). Replaces the prior "synthetic test" comments
  with real datasketches build numbers. Top-K (`lgmm8`/`lgmm10`) and
  Theta (`lgk10`/`lgk14`) sweep bounds remain spec-derived because
  `datasketch_frequent_items` and `datasketch_theta` are not exported
  by the current DuckDB community datasketches build — drift tracked in
  `_project/blind-spots/2026-05-02-155524-duckdb-datasketches-extension-drift.md`.
  Comments updated to make the spec-vs-measured distinction explicit.
- **write_primitives sketch** — live `benchbox run --platform clickhouse-local`
  smoke test against the eight ClickHouse-native sketch ops at SF=0.01
  (8/8 pass, all scalar-bounds and `*_storage_size_clickhouse` validations
  pass). Replaces the original chDB-only spike with a real adapter-driven
  run. Observed merged state sizes on clickhouse-local 25.4.2: theta
  60003 bytes, KLL 4314 bytes, topK 317 bytes — all inside existing bounds.
  Inline tolerance comments and `docs/benchmarks/write-primitives-sketch-functions.md`
  updated with the live numbers and a "Try it locally" snippet so new users
  can reproduce without cloud creds.

### New

- **write_primitives sketch** — DuckDB-only parameter-sweep variants
  (`sketch_query_*_{lgk10,lgk14,k100,k1000,lgmm8,lgmm10}`) so users can
  measure the size / accuracy / latency tradeoff per sketch family
  rather than guessing. Theta `lg_k ∈ {10, 14}`, KLL `k ∈ {100, 1000}`,
  Top-K `lg_max_map_size ∈ {8, 10}`. KLL variants verified end-to-end
  on the installed datasketches extension (~2KB merged at k=100, ~18KB
  at k=1000); Theta and frequent-items variants inherit the parent
  ops' extension-drift status. Cloud-engine sweeps are deferred.
- **write_primitives DataFrame** — PySpark sketch factory helpers
  (`make_pyspark_hll_persist_builder` / `make_pyspark_hll_merge_extract`
  for HLL on Spark 3.5+; `make_pyspark_topk_persist_builder` /
  `make_pyspark_topk_merge_extract` for top-K on Spark 4.1+, guarded by
  `pyspark_supports_approx_top_k`). The factories produce the closures
  expected by `manager.execute_aggregate_persist` / `execute_aggregate_merge`
  so PySpark sketch persist+merge cycles can run via the architecture-
  fixes dispatch primitives. KLL is intentionally omitted at the
  DataFrame layer — Spark's KLL surface is SQL-UDAF-only today.
  CLI integration (`benchbox run --queries sketch_df_*`) is a tracked
  follow-up; today the helpers are usable via direct manager calls.
- **write_primitives sketch** — DuckDB-only CPC and REQ sketch families.
  CPC (Compressed Probabilistic Counting) is an HLL-family alternative
  with dramatically smaller serialized state (~1.2KB merged vs Theta's
  ~16KB at SF=0.01) at the cost of slower update/merge throughput. REQ
  (Relative Error Quantile) is an alternative quantile sketch with
  relative-error guarantees vs KLL's normalized-rank error. 8 new ops
  total: `sketch_cpc_{create,insert,query_union_merge,drop}` and
  `sketch_req_{create,insert,query_quantile_merge,drop}`. Cloud engines
  skip cleanly (no native CPC/REQ surface today). Storage-cost
  side-by-side against Theta and KLL documented in
  `docs/benchmarks/write-primitives-sketch-functions.md`.
- **write_primitives sketch** — ClickHouse-native variants for the eight
  sketch ops using `uniqState`/`uniqMerge`,
  `quantileTDigestState`/`quantileTDigestMerge(0.5)`, and
  `topKState(8)`/`topKMerge(8)` over `AggregateFunction(...)` columns.
  ClickHouse goes from 0/8 (all skipped) to 8/8 supported, completing
  the cross-engine sketch matrix for the persist+merge+requery story.
- **write_primitives sketch** — add storage-size validation
  (`*_storage_size`) on the three ★ headline ops alongside the existing
  scalar-bounds validation. Per-engine SQL via the new
  `validation_query.platform_overrides`: `octet_length(<sketch>)` on
  DuckDB, `length(toString(<agg>MergeState(...)))` on ClickHouse. Bounds
  span both engines' observed merged-state sizes (theta ~16KB DuckDB /
  ~60KB ClickHouse, KLL ~3KB / ~3.8KB, topK ~600B / ~294B). Surfaces the
  cost-per-byte side of the persistence-vs-recompute tradeoff.
- **write_primitives validation** — `ValidationQuery.platform_overrides`
  schema extension: each validation query can declare per-platform SQL
  bodies (or explicit `null` skip). Mirrors operation-level
  `platform_overrides` and unblocks engine-specific sketch validation
  without forcing dialect probes into a single SQL body. See
  `docs/benchmarks/write-primitives-sketch-functions.md`.
- **write_primitives DataFrame** — `WriteOperationType.AGGREGATE_PERSIST`
  and `WriteOperationType.AGGREGATE_MERGE` op types with capability flags
  (`supports_aggregate_persist`/`supports_aggregate_merge`) and dispatch
  methods (`execute_aggregate_persist`/`execute_aggregate_merge`).
  PySpark presets enable both; concrete sketch wiring is deferred to a
  follow-up (write-primitives-sketch-pyspark-dataframe-surface).
- **read_primitives** — add approximate-aggregate query coverage
  (`approx_count_distinct_*`, `approx_quantile*`, `approx_top_k_*`).
  `intrinsic_appx_median` renamed to `approx_quantile_groupby` (its
  prior `PERCENTILE_CONT` body was exact, not approximate). Cross-engine
  function reference: `docs/benchmarks/read-primitives-approximate-functions.md`.
- **read_primitives DataFrame** — add `approx_count_distinct_*` impls
  (sketch-backed on Polars / PySpark / DataFusion; exact fallback on
  Pandas / Modin / cuDF / Dask). `approx_quantile_groupby` now uses
  sketch-backed quantile on PySpark (`percentile_approx`) and
  DataFusion (`approx_percentile_cont`) via the existing
  `UnifiedExpr.quantile()` dispatch (was unintentionally exact-via-
  fallback before). `SKIP_FOR_DATAFRAME` shrinks from 7 to 5;
  `approx_quantiles_array` and `approx_top_k_lineitem` remain
  PySpark-only at the DataFrame layer with explicit rationale.
  Cross-platform DataFrame coverage matrix in
  `docs/benchmarks/read-primitives-approximate-functions.md`.
- **read_primitives** — add Redshift variant for `approx_quantile_groupby`
  using `APPROXIMATE PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY x)`.
  Was previously skipped because sqlglot's Redshift dialect parser
  rejects the syntax; the static catalog linter now allowlists this
  specific parse failure while runtime execution sends the SQL as-is.
- **write_primitives** — add `sketch` category exercising DataSketches
  Theta / KLL / Top-K persist + merge + requery on Databricks,
  Snowflake, BigQuery, and DuckDB-with-extension. Three ★ headline
  ops measure the millisecond-merge claim end-to-end with
  tolerance-based scalar validation. Cross-engine reference:
  `docs/benchmarks/write-primitives-sketch-functions.md`.
- **write_primitives sketch** — add Redshift HLL coverage on the four
  HLL-applicable sketch ops (DDL, theta-style insert, theta-style
  merge, drop) using `HLL_CREATE_SKETCH` / `HLL_COMBINE` /
  `HLL_CARDINALITY` and `HLLSKETCH`-typed columns with `DISTSTYLE EVEN`.
  KLL and Top-K ops stay skipped — Redshift has no equivalent. Activates
  the previously-unused `_BINARY_TYPE_BY_DIALECT[redshift] = HLLSKETCH`
  path. Cloud verification deferred to the
  `write-primitives-sketch-cloud-verification` follow-up.

## [0.2.1] - 2026-04-26

### New

- **Benchmarks**
  - **Vector Search** - 6 kNN/ANN queries with recall@k and latency metrics;
    dialect variants for DuckDB, pgvector, Snowflake, ClickHouse, StarRocks,
    and Doris.
  - **FlightData** - 20 analytical queries over US BTS on-time aviation data
    with DataFrame support.
  - **NYC Taxi expansion** - Green Taxi, For-Hire Vehicle (FHV), and
    High-Volume FHV trip records now supported alongside Yellow Taxi; select
    via `--benchmark-option taxi_types=…`.
- **Platform adapters**
  - **Apache Doris** - Open-source MPP database powering real-time analytics at
    Baidu, Meituan, and JD.com; Uses the MySQL wire protocol.
  - **CedarDB** - HTAP engine (transactional + analytical) based on research from
    TU Munich (formerly Umbra). JIT-compiled queries. PostgreSQL wire compatible.
  - **StarRocks** - Sub-second columnar OLAP with best-in-class materialized
    views and data-lake federation
  - **SingleStore** - HTAP engine with unified row-store + columnstore for real-time
    ingest and simultaneous analytical queries without ETL; cloud and self-managed.
  - **QuestDB** - New time-series database with designated timestamps, automatic
    time partitioning, and millions-of-rows-per-second ingestion.
  - **Apache Gluten + Velox** - Spark accelerator, replaces JVM operators with
    Meta's C++ Velox engine to provide speedup with no application rewrites.
  - **Snowpark Connect and Onehouse Quanton restored** - Both platforms are
    back in the supported list after being removed in v0.2.0.

### Added

- **Scale factor harmonization** - Benchmarks with adjustable scale factors now
  target roughly 1 GB of uncompressed CSV data at SF=1, giving BenchBox a more
  consistent scale model. Output sizes at a given SF will change for affected
  benchmarks. Spec-locked benchmarks such as TPC-H, TPC-DS, SSB, ClickBench,
  and DataVault are unchanged.
- **Unofficial TPC-DS scales** (SF < 1) now work out of the box, backed by
  patched `dsdgen` binaries bundled with BenchBox. Runs are non-comparable to
  published TPC-DS results.
- **DataFrame execution coverage** - DataFrame mode now works on Metadata
  Primitives, Transaction Primitives, TPC-Havoc, FlightData, and JoinOrder.
- **New CLI flags** - `--benchmark-option K=V` (repeatable, for
  benchmark-specific parameters such as `taxi_types=yellow,green`) and
  `--iterations` (power-test measurement count).
- **HTTP TLS certificate validation** for HTTP-based data loading.
- **Advanced pg_mooncake and pg_duckdb benchmarking options.**
- **SQL compatibility subsystem** - Added `benchbox/sql_compat/` to centralize
  benchmark gating, query variants, query rewrites, schema emission, and DDL
  optimization.
- **Extended compressed data generation** - TSBS, FlightData, and NYC Taxi
  generators now support BenchBox compression options and write compression
  metadata manifests.
- **Broader platform coverage** - Added Docker-based live smoke tests for
  Firebolt Core and added SHA-256 DataVault hash-key support in the SQL ETL
  path.

### Fixed

- **Interactive `benchbox run` wizard** - Resolved phase-vs-query prompt
  confusion, `Q`-prefix query ID mismatches, invalid scale-factor
  recommendations, misleading tuning preview, and dead Test Execution Type
  input.
- **Platform config credential precedence** - Saved credentials now correctly
  override registered defaults across all builders.
- **Platform format preference defaults** - Data format selection now
  correctly defaults to each platform's preferred format.
- **ClickHouse correctness** - TPC-DS power tests now report `FAILED` when no
  queries execute (previously passed silently); added dialect overrides for
  `tpcdi`, `coffeeshop`, `h2odb` Q9, `nyctaxi` EXTRACT, `tpchavoc` Q6, and
  `read_primitives`; query error messages are now surfaced in results (pattern
  also extended to Redshift and Firebolt).
- **Apache Doris and StarRocks stability** - Hardened bulk loading, SQL
  compatibility, Docker startup, ARM64 support, timeouts, and type handling
  across `tpcdi`, `tpcds_obt`, `vector_search`, ClickBench, NYC Taxi, and
  primitives workloads.
- **QuestDB compatibility and loading** - Expanded query rewrites, improved
  `/imp` CSV loading with zstd and multi-chunk support, added platform option
  registration and HTTPS support, and stabilized table reuse.
- **Cross-adapter correctness fixes** - Resolved CedarDB benchmark failures,
  improved LakeSail local-mode startup and file scanning, added Firebolt S3
  staging and better load errors, improved Databend connection and cache
  behavior, and hardened pg_mooncake/pg_duckdb columnstore migration.
- **Dependency and test reliability** - Migrated pg-family adapters to
  psycopg3, relaxed a DataFusion v53 ordering assertion, raised the
  `pyarrow` cap to `<25.0.0`, and restored benchmark timeout enforcement on
  macOS.
- **Velox adapter** local mode now sets `spark.driver.extraClassPath` and
  `spark.executor.extraClassPath` alongside `spark.jars`. The Gluten plugin
  is loaded by `SparkContext.initializeSparkContext` before `spark.jars`
  promotions reach the executor classpath, so without these entries the
  plugin silently no-ops and queries run on plain Spark. The Docker entrypoint
  was already setting these for the server-mode path; adapter local mode is
  now consistent.
- **Velox adapter** error message for missing `gluten_jar_path` no longer
  references the removed `--velox-jar` legacy flag; it now points at the
  canonical `--platform-option gluten_jar_path=…` syntax.

### Changed

- **ClickHouse split into three platforms** - `clickhouse-local`,
  `clickhouse-server`, and `clickhouse-cloud` replace the single `clickhouse`
  platform, driven by a standardized `deployment_mode` contract.
- **TPC-DS-OBT now defaults to `parquet` output** - BenchBox now writes OBT
  artifacts as parquet by default for much smaller output size and better
  handling of wide, sparse tables. Use `--benchmark-option output_format=dat`
  to keep the old behavior.
- **Platform config builders consolidated** - Databend, Spark, ClickHouse
  Cloud, Snowflake, Databricks, and the remaining builders now share
  `build_platform_config()` with a consistent merge order.
- **Docker test platform image upgrades** - Local test platform images
  updated to latest stable versions. PostgreSQL and pg_duckdb have been
  upgraded to v18; all other images track their current stable releases.
- **Spark adapter** (`--platform spark`) now strips `PRIMARY KEY`, `FOREIGN KEY`,
  `UNIQUE` (both inline column-level and table-level), and `CHECK` constraints
  (including those with nested-paren expressions like `CHECK ((a > 0) AND (b > 0))`)
  from `CREATE TABLE` statements when running with `--table-format parquet`
  or `orc`, and rewrites `SMALLINT` to `INT` to avoid `CAST_INVALID_INPUT`
  on values above 32767. This unlocks benchmarks whose schemas carry these
  constraints (`write_primitives`, `metadata_primitives`,
  `transaction_primitives`, `datavault`, ClickBench) on Spark V1 datasource
  tables for the first time. `--table-format delta` and `iceberg` (V2 catalog
  tables) preserve constraints and `SMALLINT` as before.
- **LakeSail adapter** picks up the same constraint stripping and `SMALLINT`
  upcast through the shared Spark helpers; previously these benchmarks failed
  at `CREATE TABLE`. The orphaned-warehouse pre-purge that the Velox adapter
  introduced is now wired into LakeSail too, defending long-running pysail
  servers against `LOCATION_ALREADY_EXISTS` from prior on-disk warehouse data.

### Internal

- Lifted the three identical `apply_constraint_configuration`,
  `apply_unified_tuning`, and `apply_platform_optimizations` bodies from
  spark / lakesail / velox into a `SparkLikeAdapterMixin` next to the
  existing Spark helpers.
- The `optimize_spark_table_definition` helper now uses balanced-paren
  matching for table-level constraints so DDL with nested-paren CHECK
  clauses no longer corrupts when stripped.


## [0.2.0] - 2026-04-01

### Added

- **On-demand TPC answer file downloads** - Wheel installs now fetch missing
  TPC-H and TPC-DS answer files automatically for row-count validation, or
  pre-populate the cache with `benchbox download-answers` for offline and
  air-gapped environments. Supports `--benchmark tpch|tpcds|all`, `--force`,
  `--show-cache-dir`, SHA-256 verification, retries, and `BENCHBOX_NO_DOWNLOAD=1`.
- **Adaptive Redshift connection timeout** - Connection timeout now adjusts to
  deployment state: paused or resuming provisioned clusters get a longer timeout,
  and Serverless gets a cold-start floor to reduce spurious connection failures.
- **Cloud platform live integration tests** - Added live smoke tests for
  Firebolt, Starburst Galaxy, MotherDuck, pg_duckdb, and pg_mooncake with
  per-platform markers, fixtures, Makefile targets, Docker Compose harness for
  PostgreSQL extensions, and multi-extension comparison orchestration.
- **Read Primitives Redshift dialect coverage** - Expanded Redshift Read
  Primitives support from 0 to 40+ queries with dialect-specific rewrites for
  window functions, fulltext operators, array operations, and statistical
  functions. Queries without semantically-exact Redshift equivalents are skipped
  rather than approximated.

### Fixed

- **Redshift data-loading reliability** - Fixed S3 upload retry failures caused
  by botocore stream rewind errors, `DROP DATABASE` timeouts (extended socket
  timeout to 300 s and pre-terminate active connections), `Is a directory` errors
  with multi-format manifests, stale native datagen reuse, Serverless-compatible
  system table queries (`sys_serverless_usage` vs `stv_cluster_configuration`),
  and `pg_stat_activity` column references (`procpid` vs `pid`). Platform format
  preferences now take priority over manifest defaults.
- **Dask DataFrame `.isin()` runtime errors** - Seven TPC-H queries (Q4, Q16,
  Q18, Q20, Q21, Q22) and five TPC-DS queries (Q37, Q41, Q45, Q82, Q83) passed
  lazy Dask Series to `.isin()`, causing `TypeError` at runtime. All call sites
  now materialize via `.compute()` before `.isin()`.
- **BigQuery and format loading correctness** - Standardized text files (`.tbl`)
  as the default load source for SQL platforms while preserving columnar
  preferences for catalog platforms. Enabled parquet-first native loads on
  BigQuery and fixed GCS blob naming to preserve compound suffixes
  (`.parquet.zst` not `.zst`).
- **Data-source database resolution** - Shared-data benchmarks (e.g. Read
  Primitives) now resolve the source benchmark's database name instead of
  generating independent empty databases, fixing silent failures in
  multi-benchmark workflows.
- **TPC-H validation noise on measurement runs** - Non-stream-0 power runs no
  longer emit spurious "Validation skipped" warnings for all 22 queries on every
  measurement iteration.
- **Monitoring without optional extras** - Benchmark execution and progress
  reporting now degrade gracefully when the monitoring extra is not installed
  instead of failing during import.
- **Redshift adapter-only validation** - Repaired live test guard and validation
  logic so adapter-only (non-admin) Redshift connections no longer crash during
  row-count validation.

### Changed

- **Project status promoted to Beta** - BenchBox is now `Development Status ::
  4 - Beta` in package metadata.
- **Release-quality hardening** - Raised the coverage threshold to 80%, added
  behavioral coverage across adapter SQL generation, CLI paths, credential
  prompts, and adapter lifecycle flows, removed unreachable code, cleaned up
  tautological assertions and overspecified mocks, and accelerated
  `coverage-fast` runs with parallel execution.
- **Dead code cleanup** - Removed 9 unused platform imports and prefixed 12
  unused function parameters with `_` across the adapter layer.
- **Redshift format selection logic** - Scoped Redshift-specific format
  overrides to native COPY loads only and added platform-preference priority over
  manifest preferences, fixing incorrect format choices in mixed-format
  environments.

### Removed

- **Legacy `plot` CLI command** - Removed `benchbox plot` and its undeclared
  matplotlib dependency. Use `benchbox visualize` for terminal chart rendering.
- **Snowpark Connect and Onehouse Quanton platforms** - Removed from the
  supported SQL platform list (31 → 29).

## [0.1.5] - 2026-03-10

### Added

- **Textcharts standalone library** - Extracted all 15 ASCII chart types and base rendering
  primitives into an independent `textcharts` package under `packages/textcharts/`. The library
  has its own `pyproject.toml`, README with chart gallery and API reference, and zero BenchBox
  dependencies. Clean standalone names (`BarChart`, `Histogram`, `Heatmap`, etc.) are exported
  alongside BenchBox-compatible aliases. BenchBox now depends on textcharts as a path dependency
  with compatibility shims preserving existing import paths.
- **Open table format loading** - Added runtime loading support for external table formats
  (Delta Lake, Iceberg, Hudi) through adapter-level `load_table` implementations for Spark
  mixin platforms, cloud SQL platforms, and Snowflake/ClickHouse adapters. Format support is
  gated on adapter configuration so it is only available on platforms that implement it.
- **Expanded format capability registry** - Registered format capabilities for Hudi,
  Presto/Trino, Snowflake, ClickHouse, Redshift, BigQuery, and Spark-based platforms including
  cloud lakehouse variants (EMR, Dataproc, Glue, Fabric Spark, Synapse Spark, Dataproc
  Serverless). Removed registrations for platforms without actual loading code (including
  LakeSail for delta/iceberg/hudi).
- **Mutation testing** - Added `mutmut` mutation testing targeting 5 critical modules
  (`duckdb.py`, `adapter.py`, `runner.py`, `chart_generator.py`, `run.py`) with a
  `make mutation-test` Makefile target for manual quality reviews.

### Fixed

- **Format capability registry accuracy** - Normalized platform display names to match registry
  keys and removed platforms from format registrations where adapter code has no actual loading
  implementation.
- **CLI recursive import** - Fixed a circular lazy-import in the benchmarks module that caused a
  `RecursionError` on CLI startup.
- **CoffeeShop SA2 query** - Corrected `group_by` column name from `'name'` to
  `'product_name'`.
- **Textcharts API migration** - Migrated to textcharts v0.1.2 API after breaking changes,
  renamed `ASCII*`-prefixed classes across 10 source and test files, removed 3 unused deprecated
  factory imports, and regenerated golden snapshots for neutralized defaults.
- **pytest-xdist worker title patch** - Tightened the xdist worker title monkeypatch to prevent
  test pollution across parallel workers.
- **Comprehensive Windows CI compatibility** - Fixed 80+ Windows test failures spanning path
  separators (`.as_posix()` for forward-slash comparison), file encoding (`encoding="utf-8"`
  for `write_text()`), numpy int32 overflow on 64-bit multiplication, Rich Console width on
  headless CI, Python ABI tag format differences (`.pyd` vs `.so`), `Path.touch()` vs
  `time.time()` mocking, NTFS directory `st_size` returning 0, Windows CWD locks preventing
  temp directory cleanup, and `shutil.copytree` replacing symlinks for TPC-DS template setup.
- **TPC-DS dsqgen Windows option prefix** - Fixed dsqgen invocation on Windows where the binary
  expects `/` option prefixes instead of `-` (`OPTION_START` in `r_params.c`), and switched to
  relative paths to stay under dsqgen's 80-char `PARAM_MAX_LEN` buffer.
- **Missing `tpcds.idx` distribution file** - Added the required TPC-DS distribution index file
  to Windows binary packages (both x86_64 and ARM64).
- **Throughput test timer resolution** - Used `time.perf_counter()` for throughput duration
  calculation to avoid zero-duration results from low-resolution `time.time()` on Windows.

### Changed

- **Test suite quality overhaul** - Deleted 13 hollow coverage-theater test files and replaced
  them with behavior-verifying tests for DuckDB, SQLite, and DataFusion adapters. Replaced mock
  credential tests with real file-based tests. Strengthened 150 `is-not-None` assertions across
  5 test files, replaced hollow `isinstance` assertions with behavioral checks, and swapped
  `MagicMock` for `SimpleNamespace` on attribute-only objects. Removed per-file coverage
  enforcement in favor of a suite-wide 60% threshold.
- **~316 rendering tests migrated to textcharts** - Pure chart-rendering tests moved from
  BenchBox's test suite to the standalone textcharts library, with shim import smoke tests
  retained in BenchBox to verify re-export paths.
- **Pytest lane restructure** - Converted test lanes from implicit timing heuristics to explicit
  source markers with measured-timing-based rebucketing. Restored a lightweight fast lane,
  serialized stress tests, re-laned cloud adapter tests to `slow+cloud_import`, and documented
  pytest-xdist safety requirements.
- **Chart subtitle simplified** - Migrated chart subtitle storage from a metadata dict to a
  plain string, removing an unnecessary layer of indirection.
- **Verbose logging extracted** - Moved verbose logging configuration from `run.py` into a
  dedicated `cli/verbose_logging.py` module.
- **Visualization constants** - Extracted magic numbers into named constants across
  visualization modules.

## [0.1.4] - 2026-03-03

### Added

- **`power_bar` chart type** - Added a horizontal bar chart for TPC Power@Size comparisons.
  Higher values are treated as better (opposite of `performance_bar`), powered by
  `summary.tpc_metrics.power_at_size` and exposed in `NormalizedResult`.
- **`power_bar` template coverage** - Added to `flagship`, `head_to_head`, `trends`,
  `regression_triage`, and `executive_summary`. The chart renders only when TPC metric data is
  present and is skipped for non-TPC runs.
- **Driver-version-aware chart labeling** - Multi-platform chart series labels and run summaries
  now include driver version context so version comparisons stay explicit in rendered output.
- **Runtime ABI validation for isolated drivers** - Added ABI compatibility checks to isolated
  runtime discovery so driver auto-install paths fail fast with actionable validation errors
  instead of late runtime crashes.
- **Presorted data-generation modes for table formats** - Added `parquet-sorted` output mode,
  plus `delta-sorted` and `iceberg-sorted` organization paths with clustering primitives
  (z-order, Hilbert, partition-aware sorting) and `cluster-by` tuning integration.

### Fixed

- **Query plan capture correctness and persistence** - Fixed multiple plan-capture defects:
  forwarding `capture_plans` through `RunConfig`, DuckDB JSON plan parsing edge cases,
  preservation of `query_plan` through normalization, and `show-plan` / `compare-plans`
  loading through the standard result-file path.
- **SSB dot-notation query IDs** - `--queries` now accepts IDs like `Q2.1`, and plan-oriented
  CLI flows preserve dotted IDs instead of normalizing them away.
- **Result timing pipeline accuracy** - Fixed datagen/load timing propagation end-to-end,
  including per-table load timings in `table_statistics`, corrected load-phase duration keying,
  datagen phase duration and manifest stats in metadata, and explicit total duration override
  propagation in result builders. Data-only runs now correctly execute generation, and
  `force_regenerate` is forwarded through CLI and runner paths.
- **ASCII visualization readability under skewed data** - Fixed outlier handling across chart
  types (bar, histogram, stacked, scatter, line, CDF, percentile ladder, heatmap), addressed
  zero-heavy fallback truncation edge cases, improved natural query sorting and color cycling,
  and raised effective render width cap from 120 to 400 characters.
- **`--quiet` output contract for automation** - Quiet mode now emits only the bare result
  filepath to stdout, removing decorative output that broke script parsing.
- **Runtime environment stability** - Fixed interpreter targeting for driver auto-install,
  corrected `auto_install_used` state propagation, and resolved SIGSEGV-class failures when
  `driver_auto_install=true` reused an already-matching version.
- **Additional correctness fixes** - Restored `ai_primitives` registry resolution fallback,
  corrected SQLite `force_recreate` option handling, fixed SSB customer row-count expectation in
  `SSBRowCountStrategy`, and resolved visualize command crashes / multi-series rendering issues.

### Changed

- **Plan-capture default now uses actual execution timing** - `--capture-plans` now defaults to
  `EXPLAIN (ANALYZE, FORMAT JSON)` behavior via `analyze_plans=True`, recording measured timing
  in captured plans. Users can opt out with `analyze_plans: false` for estimate-only capture.
- **Benchmark runtime/result internals harmonized** - Refactored enhanced result construction to
  use a shared factory path and aligned canonical runtime behavior for benchmarks like NYC Taxi
  and TSBS DevOps.
- **`make test-all` resource policy and parallelism** - Resource-heavy tests are now serialized
  to prevent machine stalls, while slow/performance suites are moved to a dedicated stress lane.
  The test suite also replaces fixed sleeps with bounded polling, reduces fixture/harness
  duplication, and shifts selected CLI/e2e coverage to in-process runners for faster execution.
- **CI quality gates tightened** - Added required table-format integration coverage and promoted
  doc checks (linkcheck, example validation, docstring coverage) plus security audit policy
  controls to blocking CI behavior.

## [0.1.3] - 2026-02-23

### Added

- **Driver version pinning** - New `--platform-option driver_version=X.Y.Z` flag to pin any
  platform's Python driver to a specific version. Pair with `driver_auto_install=true` to have
  BenchBox install the requested version automatically via `uv`. All platforms support these
  options; the active driver version is now displayed in the run announcement line.
- **Bulk multi-shard table loading** - New `load_table_bulk()` interface on `FileFormatHandler`
  lets the DataLoader ingest multi-shard tables in a single native call instead of
  row-by-row iteration. DuckDB (CSV, Parquet) and ClickHouse Native handlers are the first
  implementations; benchmark runs with sharded TPC-DS data are measurably faster.
- **Greyscale / no-color ASCII chart fallbacks** - All seven ASCII chart types now have
  fill-pattern and glyph-based differentiation when color is unavailable (e.g. CI logs,
  `NO_COLOR`, piped output). `ASCIIBarChart` uses Unicode fill blocks, `ASCIIComparisonBar`
  uses hatch patterns, and the heatmap cell shading is legible without ANSI colors. A
  standardized `no_color` detection path is shared across all chart renderers, and
  ASCII-only rendering is covered by new unit tests.
- **Five new ASCII chart types** - Percentile ladder, stacked bar, sparkline table, CDF
  (cumulative distribution), rank table, and normalized speedup (log₂-scaled baseline
  comparison). All types are registered in the chart registry, accessible via CLI and MCP,
  and included in the flagship/default chart templates.
- **Post-run summary charts** - Charts are automatically generated and displayed in the
  terminal after every benchmark run and included in MCP `run_benchmark` responses.
- **Three new chart template bundles** - `latency_deep_dive`, `regression_triage`, and
  `executive_summary` template sets added alongside the existing default and flagship bundles.
- `fabric-dw` as a preferred CLI alias for `fabric_dw` platform

### Fixed

- **Driver auto-install version switching** - `sys.modules` and metadata caching could return
  stale package metadata after `driver_auto_install` swapped in a different driver version,
  causing the wrong version to be used for the remainder of the run. The module cache is
  now invalidated on version switch.
- **DataFrame cache path mismatch** - DataFrame mode cached generated data under a different
  directory structure than SQL mode, forcing redundant data generation when switching between
  modes on the same scale factor. Both modes now share a flat directory layout.
- **ClickHouse zstd double-decompression** - `ClickHouseNativeHandler` was applying manual
  zstd decompression on top of the driver's built-in decompression, corrupting data for
  compressed bulk loads.
- **Platform display names** - Corrected display names for Amazon Athena (was "AWS Athena"),
  Google Cloud Dataproc (was "GCP Dataproc"), Microsoft Azure platforms, Databricks (now
  "Databricks SQL"), and `adapter.get_platform_info()` propagated to match.
- CLI warning logged when a platform option's default value is not in the declared choices list
- Ranking normalization crash when all metric values are negative finite numbers
- PySpark SIGINT handler hanging `pytest-xdist` workers in medium-speed test runs
- `--validation-mode` CLI prompt crash when `spec.default` is not a string

### Changed

- **Four platform drivers moved to optional extras** - DuckDB (`benchbox[duckdb]`), Polars
  (`benchbox[polars]`), ClickHouse Cloud (`benchbox[clickhouse-cloud]`), and psycopg2
  (`benchbox[postgresql]`) are no longer hard dependencies. Users installing BenchBox now get
  a leaner core and can pin each driver independently. `pip install benchbox[all]` restores
  the previous behaviour.
- All user-facing terminal output in the run pipeline now flows through `emit()`, making
  `--quiet` suppression and output capture in tests consistent.
- `BaseQueryCatalogMixin` and `TranslatableQueryMixin` extracted from duplicate query-catalog
  implementations across benchmark classes.

## [0.1.2] - 2026-02-09

### Added

- **DataFrame mode for all benchmarks** - Complete DataFrame query implementations across all
  18 benchmarks including TPC-DS (102 queries), TPC-H (22 queries), SSB (13q), ClickBench (43q),
  NYC Taxi (25q), TSBS DevOps (18q), H2ODB, AMPLab, CoffeeShop, TPC-H Skew, and Data Vault.
  DataFrame platforms now include Polars, DuckDB, DataFusion, PySpark, Pandas, Modin, Dask,
  and cuDF (GPU).
- **ASCII chart visualizations** - Replaced Plotly HTML charts with terminal-native ASCII
  rendering. Seven chart types: performance bar, distribution box, query heatmap, comparison bar,
  diverging bar, summary box, and query latency histogram. Charts include ANSI colors, Unicode
  box-drawing, and best/worst highlighting.
- **14 new SQL platform adapters** - PostgreSQL, Trino, PrestoDB, Apache Spark, AWS Athena,
  Azure Synapse, Microsoft Fabric, Firebolt, MotherDuck, InfluxDB 3.x, TimescaleDB, ClickHouse
  Cloud (first-class), Onehouse Quanton, and managed Spark variants (EMR, Dataproc, Glue,
  Fabric Spark, Synapse Spark, Dataproc Serverless).
- **Open table format support** - Delta Lake, Apache Iceberg, Apache Hudi, DuckLake, and Vortex
  columnar format with format conversion orchestration and manifest v2 for multi-format tracking.
- **Physical tuning DDL generation** - Platform-specific DDL generators for DuckDB, Snowflake,
  Redshift, BigQuery, ClickHouse, Firebolt, PostgreSQL, TimescaleDB, Trino/Presto/Athena, and
  Spark family (Delta, Iceberg, Parquet, Hive) with sort keys, partitioning, clustering, and
  compression support.
- **Query plan capture and comparison** - Plan parsers for DuckDB, PostgreSQL, Redshift,
  DataFusion, and SQLite. Comparison engine with regression detection, fingerprinting, historical
  tracking with flapping detection, and CLI visualization.
- **Interactive CLI wizard** - Guided benchmark configuration with platform selection, tuning
  wizard, scale factor validation, phase/query selection, onboarding system, and persistent
  preferences.
- **TPC-DI benchmark** - Complete implementation across 4 phases: core schema, query suite,
  ETL pipeline, and validation/testing.
- **Cross-platform comparison engine** - `benchbox compare` command with multi-platform
  analysis, SQL vs DataFrame comparison, and unified visualization.
- **Unified tuning configuration** - YAML-based tuning system with per-platform DDL generation,
  write-time physical layout configuration, and dry-run preview support.
- Cloud storage and deployment modes for S3/GCS/ADLS/DBFS with credential setup wizard and
  cost estimation for Snowflake, Redshift, Synapse, Fabric, and Firebolt
- TPC compliance improvements: stream-aware validation, query permutations, warmup/measurement
  iterations, maintenance operations (RF1/RF2), and `--seed` for reproducibility
- Configurable compression (zstd, gzip, none) across all benchmarks and data generation
- New benchmarks: AI/ML Primitives, Metadata Primitives, Write Primitives, Transaction Primitives
- MCP server: `suggest_charts` and `generate_chart` tools, platform/mode parameters
- `--queries` flag for running specific query subsets, `--validation-mode` flag,
  tiered `--help`

### Fixed

- **TPC-DS data generation reliability** - Fixed segfaults with fractional scale factors,
  parallel generation errors, streaming compression, and chunked file handling.
- **Cloud platform stability** - Fixed credential refresh errors, schema creation ordering,
  UC Volume uploads, S3 key handling, and BigQuery/Snowflake/Redshift/Databricks adapter issues.
- **Type safety** - Multi-phase type checking campaign resolving 150+ type errors across
  production code with proper annotations and TYPE_CHECKING imports.
- **SQL dialect translation** - Fixed SQLGlot compatibility for DuckDB, ClickHouse, DataFusion,
  and Netezza dialects; resolved reserved keyword quoting and identifier case sensitivity.
- Security hardening: SQL injection prevention, parameterized queries, path traversal protection
- CLI hanging in non-interactive mode, progress display precision, `--quiet` mode propagation
- TPC compliance: correct stream permutations, maintenance phase SQL execution, Power@Size
  calculation parity between SQL and DataFrame modes

### Changed

- Dropped Plotly HTML charts in favor of ASCII-only rendering
- Lazy-load cloud platform adapters to speed up CLI startup and test suite
- Optimized TPC-DS smoke tests with selective table generation

## [0.1.1] - 2026-01-24

### Fixed

- **Critical: TPC-H/TPC-DS query templates missing from wheel distribution** - BenchBox installed
  from PyPI via wheel could not run TPC-H or TPC-DS benchmarks because query template files were
  stored outside the package tree and excluded from wheels. Templates are now bundled inside
  `benchbox/_binaries/*/templates/` with a resolution utility that checks the bundled location
  first and falls back to `_sources/` for development installs.
- **dsqgen path buffer overflow** - TPC-DS query generation could fail on systems with long temp
  directory paths (e.g., macOS `/var/folders/...`) due to dsqgen's internal 80-char path buffer.
  Fixed by using short symlinks in the temp directory.
- Python 3.10 compatibility for CLI, version utilities, and `tomllib` imports
- Windows CI test failures and cross-platform compatibility issues
- DuckDB version compatibility in tests
- MCP server: XSS prevention and strengthened path traversal checks

### Added

- MCP server: 7 new tools (`get_query_details`, `detect_regressions`, `get_performance_trends`,
  `aggregate_results`, `get_query_plan`, `export_results`, `export_summary`) and 2 prompts
- GitHub Actions PyPI publishing with trusted publishers
- Release automation: `--push`, `--auto-continue`, CI validation integration, bidirectional sync
- Platform adoption tiers (`recommended`, `supported`, `experimental`, `preview`) replacing
  boolean `recommended` field

### Changed

- Minimum Python version explicitly documented as 3.10
- MCP server refactored to use public API instead of CLI internals
- Benchmark metadata centralized into single registry
- Per-platform TPC-DS query template duplicates removed (530 files, ~4MB saved from wheel)
- MANIFEST.in expanded to include TPC patches, EULAs, and compilation infrastructure for
  sdist users who build from source

## [0.1.0] - 2026-01-10 (Initial Release)

> **Alpha Software**: BenchBox is alpha software. APIs may change without notice, features may be incomplete, and production use is not recommended. See [DISCLAIMER.md](DISCLAIMER.md) for full details.

### Overview

BenchBox v0.1.0 is the **initial public release** of the database benchmarking framework. BenchBox makes it simple to run industry-standard benchmarks (TPC-H, TPC-DS) on analytical databases, from embedded engines like DuckDB to cloud data warehouses like Snowflake and Databricks.

### What's Included

**Benchmarks** (18 total):
- **TPC Standards**: TPC-H (22 queries), TPC-DS (99 queries), TPC-DI
- **Academic**: SSB, AMPLab, JoinOrder (IMDB dataset)
- **Industry**: ClickBench, H2ODB, NYC Taxi, TSBS DevOps, CoffeeShop
- **Data Modeling**: TPC-H Data Vault
- **BenchBox Primitives**: Read Primitives, Write Primitives, Transaction Primitives
- **Experimental**: TPC-DS-OBT, TPC-Havoc, TPC-H Skew

**SQL Platforms** (16 total):
- **Embedded**: DuckDB, SQLite, DataFusion
- **Cloud Data Warehouses**: Snowflake, Databricks, BigQuery, Redshift, Azure Synapse
- **Analytical Databases**: ClickHouse, Trino, Presto, Firebolt, InfluxDB
- **General Purpose**: PostgreSQL, Spark, Athena

**DataFrame Platforms** (8 total):
- **Expression Family**: Polars, DataFusion, DuckDB, PySpark
- **Pandas Family**: Pandas, Modin, Dask, cuDF (GPU)

**Core Features**:
- Self-contained data generation (no external tools required)
- Automatic SQL dialect translation between platforms
- CLI with dry-run support, progress bars, and rich output
- Programmatic Python API for integration
- Result export in JSON, CSV, and HTML formats

### Quick Start

```bash
# Install
pip install benchbox

# Run TPC-H on DuckDB
benchbox run --platform duckdb --benchmark tpch --scale 0.01

# Run with DataFrame API
benchbox run --platform polars-df --benchmark tpch --scale 0.01
```

### Links

- **Documentation**: [GitHub Repository](https://github.com/joeharris76/benchbox)
- **Issues**: [Report bugs and request features](https://github.com/joeharris76/benchbox/issues)
- **PyPI**: [pypi.org/project/benchbox](https://pypi.org/project/benchbox/)

[Unreleased]: https://github.com/joeharris76/benchbox/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/joeharris76/benchbox/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/joeharris76/benchbox/compare/v0.1.5...v0.2.0
[0.1.5]: https://github.com/joeharris76/benchbox/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/joeharris76/benchbox/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/joeharris76/benchbox/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/joeharris76/benchbox/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/joeharris76/benchbox/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/joeharris76/benchbox/releases/tag/v0.1.0
