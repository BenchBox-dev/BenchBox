<!-- markdownlint-disable MD024 -->

# Databricks Platform Adapter

```{tags} reference, python-api, databricks
```

The Databricks adapter provides cloud-native Spark SQL execution with Delta Lake optimization for analytical benchmarks.

## Overview

Databricks is a Data Intelligence Platform with lakehouse architecture, built on Apache Spark. The adapter needs the `databricks` extra (`pip install "benchbox[databricks]"`) and a SQL warehouse you can reach. It provides:

- **Lakehouse Architecture** - Combines data warehouse and data lake capabilities
- **Serverless SQL Warehouses** - On-demand compute without cluster management
- **Delta Lake** - ACID transactions and time travel support
- **Unity Catalog** - Unified governance for data and AI assets
- **Photon Engine** - Vectorized query engine for analytical workloads

Common use cases:

- Lakehouse deployments
- ML and data science workflows
- Large-scale benchmarking (multi-TB datasets)
- Multi-cloud deployments (AWS, Azure, GCP)
- Delta Lake performance evaluation

## Quick Start

### Basic Configuration

```python
from benchbox.tpch import TPCH
from benchbox.platforms.databricks import DatabricksAdapter

# Connect to Databricks SQL Warehouse
adapter = DatabricksAdapter(
    server_hostname="dbc-12345678-abcd.cloud.databricks.com",
    http_path="/sql/1.0/warehouses/abcd1234efgh5678",
    access_token="dapi1234567890abcdef",
    catalog="main",
    schema="benchbox"
)

# Generate data, then run the benchmark
benchmark = TPCH(scale_factor=1.0)
benchmark.generate_data()
results = benchmark.run_with_platform(adapter)
```

`run_with_platform` does not generate data. Without `generate_data()` there are no data files to load. Loading also needs a staging location (see Data Loading).

### Auto-Detection (Recommended)

```python
# Auto-detect from Databricks SDK configuration
# Uses ~/.databrickscfg or environment variables
from benchbox.platforms.databricks import DatabricksAdapter

adapter = DatabricksAdapter.from_config({
    "benchmark": "tpch",
    "scale_factor": 1.0,
    "very_verbose": True  # Shows auto-detection details
})
# The schema name is generated (tpch_sf1_notuning_noconstraints) and the
# catalog defaults to "workspace"
```

## API Reference

### DatabricksAdapter Class

<span id="benchbox.platforms.databricks.DatabricksAdapter"></span>

`benchbox.platforms.DatabricksAdapter` runs BenchBox benchmarks on a Databricks SQL warehouse, with Delta Lake tables and Unity Catalog staging.

**Import:** `from benchbox.platforms import DatabricksAdapter` · **Extras:** `databricks`

#### Parameters

All parameters are keyword arguments (the signature is `(**config)`).

Connection:

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `server_hostname` | `str` | required | Workspace host name without `https://`. `host` is read when `server_hostname` is absent. |
| `http_path` | `str` | required | SQL warehouse HTTP path, for example `/sql/1.0/warehouses/<id>`. |
| `access_token` | `str` | required | Personal access token. `token` is read when `access_token` is absent. |
| `catalog` | `str` | `"main"` | Catalog for the benchmark schema. |
| `schema` | `str` | `"benchbox"` | Schema for the tables. |
| `create_catalog` | `bool` | `False` | `create_schema` also runs `CREATE CATALOG IF NOT EXISTS`. |
| `region` | `str` or `None` | `None` | Workspace cloud region, for reporting. `cloud_region` and `workspace_region` are read when `region` is absent. |

Staging:

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `staging_root` | `str` or `None` | `None` | Cloud location (`dbfs:/`, `s3://`, `gs://`, `abfss://`) that `COPY INTO` reads from. |
| `uc_catalog`, `uc_schema`, `uc_volume` | `str` or `None` | `None` | Unity Catalog volume `dbfs:/Volumes/<uc_catalog>/<uc_schema>/<uc_volume>` used for staging when `staging_root` is not a cloud location. |
| `force_upload` | `bool` | `False` | Upload local files to the volume even if they are already there. |

Tables and maintenance:

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `table_format` | `str` | `"delta"` | `"delta"` or `"hudi"`, in any case. Hudi tables cannot be loaded with `load_data`. |
| `hudi_primary_key` | `str` or `None` | `None` | Hudi record key column (a plain identifier). |
| `hudi_precombine_field` | `str` or `None` | `None` | Hudi precombine column (a plain identifier). |
| `hudi_table_type` | `str` | `"cow"` | `"cow"` or `"mor"`, in any case. |
| `enable_delta_optimization` | `bool` | `True` | Allows `optimize_table`, `vacuum_table` and the post-load `OPTIMIZE` and `ANALYZE` of tuned runs. |
| `delta_auto_optimize` | `bool` | `True` | Adds the properties `delta.autoOptimize.optimizeWrite` and `delta.autoOptimize.autoCompact` to created tables. |
| `delta_auto_compact` | `bool` | `True` | Recorded and reported only; `delta_auto_optimize` sets both table properties. |
| `cluster_size` | `str` or `None` | `None` | Intended warehouse size, recorded and reported only. BenchBox never resizes the warehouse. |
| `auto_terminate_minutes` | `int` | `30` | Recorded and reported only. BenchBox never changes the warehouse's auto-stop. |
| `disable_result_cache` | `bool` | `True` | Runs `SET use_cached_result = false` in `configure_for_benchmark`. |
| `force_recreate` | `bool` | `False` | Drop an existing schema when a connection is created. |

The adapter also accepts the keys every BenchBox adapter takes: see [Constructor Parameters](#constructor-parameters). Keys it does not recognise are accepted and ignored. The constructor reads no environment variables: `DATABRICKS_HOST`, `DATABRICKS_HTTP_PATH` and `DATABRICKS_TOKEN` are mentioned in its error message but not consulted, so pass the values yourself. `from_config` can fill missing connection values from the Databricks SDK instead.

#### Returns

A `DatabricksAdapter`. Construction makes no network call; call `create_connection()` to connect.

#### Raises

- `ImportError`: the Databricks SQL connector is not installed. The message lists `databricks-sql-connector` and `cloudpathlib` and the install command `pip install 'benchbox[databricks]'`. This check runs before the others.
- `ConfigurationError` (from `benchbox.core.exceptions`): `server_hostname`, `http_path` or `access_token` is missing or empty (`Databricks configuration is incomplete. Missing: ...`).
- `ValueError`: `table_format` is not `delta` or `hudi` (`Unsupported Databricks table_format 'iceberg'. Use 'delta' or 'hudi'.`) or `hudi_table_type` is not `cow` or `mor` (`Unsupported hudi_table_type 'x'. Use 'cow' or 'mor'.`).
- `DataLoadingError` (from `benchbox.platforms.base.data_loading`): `hudi_primary_key` or `hudi_precombine_field` is not a plain identifier.

The workspace and token are not checked here. They fail in `create_connection()`, which needs a live connection and was taken from reading the code.

#### Example

```python
from benchbox.platforms import DatabricksAdapter

adapter = DatabricksAdapter(
    server_hostname="dbc-1234.cloud.databricks.com",
    http_path="/sql/1.0/warehouses/abcd1234",
    access_token="dapi-example",
    staging_root="s3://my-bucket/benchbox-staging",
)
print(adapter.catalog, adapter.schema, adapter.table_format, adapter.cluster_size, adapter.disable_result_cache)
print(adapter.platform_name, adapter.get_target_dialect(), adapter.hudi_table_type)

for kwargs in (
    {},
    {"server_hostname": "h", "http_path": "p", "access_token": "t", "table_format": "iceberg"},
    {"server_hostname": "h", "http_path": "p", "access_token": "t", "hudi_table_type": "x"},
):
    try:
        DatabricksAdapter(**kwargs)
    except Exception as exc:
        print(type(exc).__name__, str(exc).splitlines()[0])

configured = DatabricksAdapter.from_config(
    {"benchmark": "tpch", "scale_factor": 0.01, "server_hostname": "h", "http_path": "/sql/1.0/warehouses/w", "access_token": "t"}
)
print(configured.catalog, configured.schema)
```

Output on 0.4.1 with `databricks-sql-connector` 4.6.0, run without a network connection:

```text
main benchbox delta None True
Databricks databricks cow
ConfigurationError Databricks configuration is incomplete. Missing: server_hostname (or DATABRICKS_HOST), http_path (or DATABRICKS_HTTP_PATH), access_token (or DATABRICKS_TOKEN)
ValueError Unsupported Databricks table_format 'iceberg'. Use 'delta' or 'hudi'.
ValueError Unsupported hudi_table_type 'x'. Use 'cow' or 'mor'.
workspace tpch_sf001_notuning_noconstraints
```

#### Compatibility

- `benchbox.platforms.databricks.DatabricksAdapter` is the same class.
- The constructor defaults `catalog` to `"main"`, but `from_config` defaults it to `"workspace"`.
- `cluster_size` defaults to `None`. `cluster_size`, `auto_terminate_minutes` and `delta_auto_compact` change nothing on the warehouse; they are only reported.
- The connector comes with the `databricks` extra; the base `benchbox` install does not include it.

### Constructor Parameters

Every platform adapter accepts these keyword arguments. All are optional.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `force_recreate` | `bool` | `False` | Recreate an existing database instead of reusing it. |
| `show_query_plans` | `bool` | `False` | Print each query's plan after it runs. |
| `capture_plans` | `bool` | `False` | Add `query_plan` and `plan_fingerprint` to each successful query result. |
| `analyze_plans` | `bool` | `False` | Capture plans with actual timings; each captured `SELECT` is executed once more. |
| `tuning_enabled` | `bool` | `False` | Apply the tuning configuration given in `tuning_config`. |
| `tuning_config` | `UnifiedTuningConfiguration` or `None` | `None` | The tuning configuration (`unified_tuning_configuration` is read as a fallback). |
| `enable_validation` | `bool` | `False` | The benchmark runner passes `validate_row_count=True` to `execute_query`. |
| `dry_run` | `bool` | `False` | Makes `is_dry_run` true. |
| `verbose_enabled`, `very_verbose`, `quiet` | `bool` | `False` | Logging verbosity. `verbose_level` (0, 1 or 2) sets the first two. |

The values are stored as attributes of the same name (`DatabricksAdapter(server_hostname="h", http_path="p", access_token="t").force_recreate` is `False`).

### Methods and attributes

Each method is marked with how its description was checked. Calls that talk to Databricks need a workspace and a live connection; those are marked as taken from reading the code. The others were run offline, either directly or against a stub connection object that records the SQL the adapter sends and returns prepared rows.

#### Construction and configuration

<span id="benchbox.platforms.databricks.DatabricksAdapter.__init__"></span>
**`__init__(**config)`**: Creates the adapter from keyword arguments. See Parameters above. It checks that the Databricks SQL connector is importable, validates the settings and opens no connection. *Checked offline.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.from_config"></span>
**`from_config(config: dict[str, Any])`** (class method): Builds an adapter from a unified configuration dictionary and returns it. `server_hostname`, `http_path` and `access_token` are used when present and not placeholders (values containing `your-workspace`, `your-warehouse-id`, `${` or `example` are treated as missing). If any of the three is missing, the adapter asks the Databricks SDK for a workspace, token and SQL warehouse and fills in what it finds, which contacts the workspace. `catalog` defaults to `"workspace"` here (the constructor defaults to `"main"`). `schema` is generated from `benchmark` and `scale_factor` as `<benchmark>_sf<token>_<tuning>`, for example `tpch_sf001_notuning_noconstraints`, when the configuration has both and the schema is empty, `None` or `"benchbox"`; any other `schema` value is kept; with no `benchmark` context the schema is the given one or `"benchbox"`. These keys pass through when present: `uc_catalog`, `uc_schema`, `uc_volume`, `staging_root`, `region`, `cloud_region`, `workspace_region`, `cluster_size`, `auto_terminate_minutes`, `enable_delta_optimization`, `delta_auto_optimize`, `delta_auto_compact`, `table_format`, `hudi_primary_key`, `hudi_precombine_field`, `hudi_table_type`, `create_catalog`, `disable_result_cache`, the tuning keys and the verbosity keys. Other keys are dropped, including `force` and `force_recreate`. *Checked offline with all three connection values supplied; the SDK lookup was taken from reading the code.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.add_cli_arguments"></span>
**`add_cli_arguments(parser) -> None`** (static method): Adds a `Databricks Arguments` group to an `argparse.ArgumentParser` and returns `None`: `--server-hostname`, `--http-path`, `--access-token`, `--catalog` (default `workspace`) and `--schema` (default `None`, meaning generated). *Checked offline.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.platform_name"></span>
**`platform_name`** (property): Always the string `'Databricks'`. *Checked offline.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.get_target_dialect"></span>
**`get_target_dialect() -> str`**: Returns `'databricks'`, the SQL dialect BenchBox translates queries into. *Checked offline.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.get_platform_info"></span>
**`get_platform_info(connection: Any = None) -> dict[str, Any]`**: Returns a `dict` describing the platform: `platform_type` (`'databricks'`), `platform_name`, `connection_mode` (`'remote'`), `host`, `configuration` (connection and Unity Catalog settings, the Delta and Hudi settings, `cluster_size`, `auto_terminate_minutes`, `result_cache_enabled`, the resolved clustering strategy and the lists of layout operations applied or skipped), `client_library_version`, `platform_version`, `engine_version` and, when it can be read, `compute_configuration` for the SQL warehouse. With a connection, the version comes from `current_version()`. It also calls the Databricks SDK to read the warehouse (size, type, Photon, serverless) from the workspace, and tries to detect the region when `region` is unset; if the SDK or the call is unavailable, `compute_configuration` records that the metadata is unavailable instead of raising. These workspace calls happen even when no connection is passed. *Needs a live connection; taken from reading the code.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.get_normalized_result_metadata"></span>
**`get_normalized_result_metadata(*, connection: Any | None = None, platform_info: Mapping[str, Any] | None = None) -> dict[str, Any]`**: Returns the platform metadata that BenchBox stores with results, as a `dict` built from `get_platform_info` (so it also contacts the workspace unless you pass a precomputed `platform_info`). Pass `connection` or `platform_info` (keyword-only). The result has the entries `platform_deployment`, `platform_cloud`, `platform_compute` and `platform_storage` on top of the default metadata. *Needs a live connection; taken from reading the code.*

#### Connection and schema

<span id="benchbox.platforms.databricks.DatabricksAdapter.create_connection"></span>
**`create_connection(**connection_config) -> Any`**: Returns a `databricks.sql` connection to the SQL warehouse (`server_hostname`, `http_path`, `access_token`, user agent entry `BenchBox/1.0`). Existing-schema handling comes first: with `force_recreate=True` the schema is dropped, and otherwise it is validated and reused if it passes. It runs `SELECT 1`, `USE CATALOG <catalog>` and, for a reused schema, `USE SCHEMA <schema>`; a new schema is selected by `create_schema`. Bad credentials, a stopped warehouse or a missing catalog raise here, as the connector's exception. *Needs a live connection; taken from reading the code.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.close_connection"></span>
**`close_connection(connection: Any) -> None`**: Closes the connection and returns `None`. `None` is accepted, and an error while closing is logged as a warning, not raised. *Checked offline against a stub connection.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.new_stream_connection"></span>
**`new_stream_connection(connection: Any, *, benchmark_type: str | None = None) -> Any`**: Returns the handle one concurrent throughput stream should use. Databricks declares the default shared-cursor capability, so this returns a cursor wrapper over the one shared connection; closing it does not close the connection. `benchmark_type` is ignored for this capability. Inherited from the shared adapter base class. *Checked offline against a stub connection.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.check_server_database_exists"></span>
**`check_server_database_exists(**connection_config) -> bool`**: Returns `True` when `SHOW CATALOGS` lists `catalog` and `SHOW SCHEMAS IN <catalog>` lists `schema` (or the `catalog` and `schema` keywords). Any error, including a failed login, returns `False`. *Needs a live connection; taken from reading the code.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.drop_database"></span>
**`drop_database(**connection_config) -> None`**: Runs `DROP SCHEMA IF EXISTS <catalog>.<schema> CASCADE` and returns `None`; the catalog is not dropped. Raises `RuntimeError` (`Failed to drop Databricks schema ...`) on failure. *Needs a live connection; taken from reading the code.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.configure_for_benchmark"></span>
**`configure_for_benchmark(connection: Any, benchmark_type: str) -> None`**: Sets session options and returns `None`. With `disable_result_cache` true (the default) it runs `SET use_cached_result = false`; a failure is logged and not raised. The `benchmark_type` is not used. Custom Spark settings in an attribute `spark_configs`, if you set one, are applied with `SET`. *Checked offline against a stub connection.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.create_schema"></span>
**`create_schema(benchmark, connection: Any) -> float`**: Creates the schema (and the catalog first when `create_catalog` is true), selects them, and runs the benchmark's `CREATE TABLE` statements, returning the elapsed time in seconds (`float`). Each statement becomes `CREATE OR REPLACE TABLE ... USING DELTA` (`USING HUDI` with record-key properties when `table_format` is `hudi`). With `delta_auto_optimize` true the table gets the properties `delta.autoOptimize.optimizeWrite` and `delta.autoOptimize.autoCompact` set to `true`; with it false the statement ends in an empty `TBLPROPERTIES ()`, which was not run against a warehouse. Raises `RuntimeError` when the benchmark produces no schema SQL. *The statement rewriting was checked offline; schema and table creation needs a live connection and was taken from reading the code.*

#### Loading data into tables

<span id="benchbox.platforms.databricks.DatabricksAdapter.load_data"></span>
**`load_data(benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]`**: Loads the benchmark's data files into the Delta tables with `COPY INTO` and returns `(table_row_counts, seconds, per_table_timings)`; `table_row_counts` maps upper-case table names to row counts and each `per_table_timings` entry holds `copy_into_ms`, `optimize_ms`, `total_ms` and `rows`. The files must be at a staging location: `staging_root` (`dbfs:/`, `s3://`, `gs://` or `abfss://`), or the Unity Catalog volume `dbfs:/Volumes/<uc_catalog>/<uc_schema>/<uc_volume>`. When the data is local and the staging location is a complete UC volume path, the adapter creates the volume if needed and uploads the files itself (re-uploading only with `force_upload`). With no staging location it raises `ValueError`; with no data files it raises `ValueError` (`No data files found. Ensure benchmark.generate_data() was called first.`); with `table_format='hudi'` it raises `ValueError`, since `COPY INTO` targets Delta only. A table that fails to load does not raise: it is logged and counted as `0` rows. Create the tables first with `create_schema`. *Needs a live connection; taken from reading the code.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.create_external_tables"></span>
**`create_external_tables(benchmark: Any, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]`**: Registers Parquet data in the staging location as external tables and returns `(table_row_counts, seconds, None)`: for each table it runs `DROP TABLE IF EXISTS` and `CREATE TABLE <TABLE> USING PARQUET LOCATION '<location>'` and counts the rows. The tables must already exist (`create_schema`), or it raises `RuntimeError`. Non-Parquet sources raise `ValueError`. It uses the same staging rules and upload as `load_data`. *Needs a live connection; taken from reading the code.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.supports_external_tables"></span>
**`supports_external_tables`** (class attribute): `True`. The adapter implements `create_external_tables`. *Checked offline.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.validate_external_table_requirements"></span>
**`validate_external_table_requirements() -> None`**: Returns `None` when `staging_root` is a cloud URI (`dbfs:/`, `s3://`, `gs://`, `abfss://`) or all of `uc_catalog`, `uc_schema` and `uc_volume` are set. Otherwise raises `ValueError` (`Databricks external mode requires cloud staging. ...`). *Checked offline.*

#### Table maintenance

<span id="benchbox.platforms.databricks.DatabricksAdapter.analyze_table"></span>
**`analyze_table(connection: Any, table_name: str) -> None`**: Runs `ANALYZE TABLE <TABLE> COMPUTE STATISTICS` with the upper-cased table name and returns `None`. A failure is logged as a warning and not raised. *Checked offline against a stub connection.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.optimize_table"></span>
**`optimize_table(connection: Any, table_name: str) -> None`**: Runs `OPTIMIZE <TABLE>` and returns `None`. It does nothing when `enable_delta_optimization` is false, and for a Hudi table it only records the operation as skipped. A failure is logged as a warning and not raised. *Checked offline against a stub connection.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.vacuum_table"></span>
**`vacuum_table(connection: Any, table_name: str, hours: int = 168) -> None`**: Runs `VACUUM <TABLE> RETAIN <hours> HOURS` (`hours` defaults to `168`, seven days) and returns `None`. It does nothing when `enable_delta_optimization` is false, and for a Hudi table it only records the operation as skipped. A failure is logged as a warning and not raised. *Checked offline against a stub connection.*

#### Query execution and plans

<span id="benchbox.platforms.databricks.DatabricksAdapter.execute_query"></span>
**`execute_query(connection: Any, query: str, query_id: str, benchmark_type: str | None = None, scale_factor: float | None = None, validate_row_count: bool = True, stream_id: int | None = None) -> dict[str, Any]`**: Runs one query and returns a result `dict`; it does not raise for SQL errors. TPC-DI queries get extra rewrites, output names that repeat are made unique, and divisions are guarded against zero divisors. On success `status` is `'SUCCESS'` with `query_id`, `execution_time_seconds`, `rows_returned`, `first_row`, `translated_query` (`None`) and `resource_usage` (the measured time). On an error `status` is `'FAILED'` with `error` and `error_type`. It accepts a connection or an open cursor. With `capture_plans` set it adds `query_plan` and `plan_fingerprint`. *Checked offline against a stub connection.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.get_query_plan"></span>
**`get_query_plan(connection: Any, query: str) -> str | None`**: Returns the Spark plan as the text of `EXPLAIN EXTENDED <query>`, or `None` if the statement fails or returns nothing. *Checked offline against a stub connection.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.get_query_plan_parser"></span>
**`get_query_plan_parser()`**: Returns a `SparkQueryPlanParser` (from `benchbox.core.query_plans.parsers.spark`), because Databricks runs Spark SQL. *Checked offline.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.plan_capture_phase_eligible"></span>
**`plan_capture_phase_eligible`** (class attribute): `True`. Query plans for Databricks are captured in a separate pass after the timed run, not inline with the timed queries. *Checked offline.*

#### Tuning

<span id="benchbox.platforms.databricks.DatabricksAdapter.generate_tuning_clause"></span>
**`generate_tuning_clause(table_tuning) -> str`**: Returns the clauses to append to `CREATE TABLE`, or `''` when there is no tuning. For Delta tables the result starts with `USING DELTA`, then `PARTITIONED BY (c1, ...)` for partitioning columns and `CLUSTER BY (c1, ...)` for clustering columns (both in `order` sequence). Distribution and sorting add nothing here; a table with only those returns `USING DELTA`. With `table_format='hudi'` the result is `USING HUDI TBLPROPERTIES ('type' = 'cow')` plus the primary-key and precombine properties and `PARTITIONED BY`, with no clustering. A Liquid Clustering strategy together with partitioning columns raises `ValueError`. Example: partition on `d` plus clustering on `c` gives `USING DELTA PARTITIONED BY (d) CLUSTER BY (c)`. *Checked offline.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.apply_table_tunings"></span>
**`apply_table_tunings(table_tuning, connection: Any) -> None`**: Applies post-creation layout to an existing table and returns `None`. It runs `DESCRIBE EXTENDED <TABLE>` to see whether the table is Delta. Depending on the clustering strategy in the tuning configuration it then runs `ALTER TABLE ... CLUSTER BY AUTO`, `ALTER TABLE ... CLUSTER BY (columns)` (Liquid Clustering), or, when only clustering or distribution columns are given, `OPTIMIZE ... ZORDER BY (clustering columns, then distribution columns)`. It does not run `OPTIMIZE` or `ANALYZE`: for Delta tables with `enable_delta_optimization` true, a tuned run executes `OPTIMIZE <TABLE>` and `ANALYZE TABLE <TABLE> COMPUTE STATISTICS` after each table loads and reports that time as `phases.post_load_maintenance`, not as load time. Hudi tables only record the Delta-only operations as skipped. Liquid Clustering combined with partitioning or distribution columns raises `ValueError`, as does any unexpected failure (`Failed to apply tunings to Databricks table <TABLE>: ...`). It does nothing for an empty tuning. *Checked offline against a stub connection.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.apply_unified_tuning"></span>
**`apply_unified_tuning(unified_config: UnifiedTuningConfiguration, connection: Any) -> None`**: Applies a `UnifiedTuningConfiguration` and returns `None`: `apply_constraint_configuration`, then `apply_platform_optimizations` when present, then `apply_table_tunings` for each table. It does nothing for an empty configuration. *Checked offline against a stub connection.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.apply_platform_optimizations"></span>
**`apply_platform_optimizations(platform_config: PlatformOptimizationConfiguration, connection: Any) -> None`**: Logs that the optimisations are stored for Spark session and Delta Lake management and returns `None`. It changes nothing in Databricks, and does nothing for `None`. *Checked offline against a stub connection.*

<span id="benchbox.platforms.databricks.DatabricksAdapter.apply_constraint_configuration"></span>
**`apply_constraint_configuration(primary_key_config: PrimaryKeyConfiguration, foreign_key_config: ForeignKeyConfiguration, connection: Any) -> None`**: Logs that primary-key or foreign-key constraints are enabled (informational only in Databricks) and returns `None`. It runs no SQL. *Checked offline against a stub connection.*

#### Capabilities

<span id="benchbox.platforms.databricks.DatabricksAdapter.driver_isolation_capability"></span>
**`driver_isolation_capability`** (class attribute): `DriverIsolationCapability.FEASIBLE_CLIENT_ONLY` (from `benchbox.platforms.base`): a requested connector version can run in an isolated runtime, but the Databricks service itself cannot be versioned. *Checked offline.*

#### Not in the 0.4.1 release

<span id="benchbox.platforms.databricks.DatabricksAdapter.preprocess_operation_sql"></span>
**`preprocess_operation_sql`**: `preprocess_operation_sql` is not part of the 0.4.1 release of `DatabricksAdapter`; it exists only on the development branch. Do not rely on it with 0.4.1.

<span id="benchbox.platforms.databricks.DatabricksAdapter.reset_database_in_place"></span>
**`reset_database_in_place`**: `reset_database_in_place` is not part of the 0.4.1 release of `DatabricksAdapter`; it exists only on the development branch. Do not rely on it with 0.4.1.

## Configuration Examples

### Environment Variables

```bash
# Set Databricks credentials
export DATABRICKS_HOST="https://dbc-12345678-abcd.cloud.databricks.com"
export DATABRICKS_TOKEN="dapi1234567890abcdef"
export DATABRICKS_WAREHOUSE_ID="abcd1234efgh5678"
```

```python
import os
from benchbox.platforms.databricks import DatabricksAdapter

# Use environment variables
adapter = DatabricksAdapter(
    server_hostname=os.environ["DATABRICKS_HOST"].replace("https://", ""),
    http_path=f"/sql/1.0/warehouses/{os.environ['DATABRICKS_WAREHOUSE_ID']}",
    access_token=os.environ["DATABRICKS_TOKEN"]
)
```

### Unity Catalog Configuration

```python
# With Unity Catalog volumes for staging
adapter = DatabricksAdapter(
    server_hostname="workspace.cloud.databricks.com",
    http_path="/sql/1.0/warehouses/abc123",
    access_token="dapi...",
    catalog="production",
    schema="tpch_sf100",
    uc_catalog="staging",
    uc_schema="benchmark_data",
    uc_volume="tpch_staging"
)

# Data will be staged to: dbfs:/Volumes/staging/benchmark_data/tpch_staging/
```

### S3 Staging Configuration

```python
# Use S3 for data staging
adapter = DatabricksAdapter(
    server_hostname="workspace.cloud.databricks.com",
    http_path="/sql/1.0/warehouses/abc123",
    access_token="dapi...",
    staging_root="s3://my-bucket/benchbox-staging"
)
```

### Delta Lake Optimization

```python
# High-performance Delta Lake configuration
adapter = DatabricksAdapter(
    server_hostname="workspace.cloud.databricks.com",
    http_path="/sql/1.0/warehouses/large-warehouse",
    access_token="dapi...",
    enable_delta_optimization=True,
    delta_auto_optimize=True,
    delta_auto_compact=True
)
```

## Authentication

### Personal Access Token

```bash
# Generate token in Databricks UI:
# User Settings → Developer → Access Tokens → Generate New Token

# Use in environment
export DATABRICKS_TOKEN="dapi1234567890abcdef"
```

### Databricks CLI Configuration

```bash
# Configure Databricks CLI
databricks configure --token
# Enter workspace URL and token

# Then use auto-detection
adapter = DatabricksAdapter.from_config({
    "benchmark": "tpch",
    "scale_factor": 1.0
})
```

### Service Principal (Production)

```python
# For production deployments
from databricks.sdk import WorkspaceClient
from databricks.sdk.oauth import ClientCredentials

client = WorkspaceClient(
    host="https://workspace.cloud.databricks.com",
    auth_type="oauth",
    client_id="your-client-id",
    client_secret="your-client-secret"
)

adapter = DatabricksAdapter(
    server_hostname=client.config.host.replace("https://", ""),
    http_path="/sql/1.0/warehouses/abc123",
    access_token=client.config.token
)
```

## Data Loading

### UC Volumes (Recommended)

```python
from benchbox.platforms.databricks import DatabricksAdapter
from benchbox.tpch import TPCH
from pathlib import Path

# Configure adapter with UC Volume
adapter = DatabricksAdapter(
    server_hostname="workspace.cloud.databricks.com",
    http_path="/sql/1.0/warehouses/abc123",
    access_token="dapi...",
    uc_catalog="staging",
    uc_schema="benchmark_data",
    uc_volume="tpch_volume"
)

# Generate data locally
data_dir = Path("./tpch_data")
benchmark = TPCH(scale_factor=1.0, output_dir=data_dir)
benchmark.generate_data()

# Create the tables, then load data. With a complete UC Volume configured
# and local data, load_data creates the volume if needed and uploads the
# files itself; a manual upload is not required.
conn = adapter.create_connection()
adapter.create_schema(benchmark, conn)
table_stats, load_time, _ = adapter.load_data(benchmark, conn, data_dir)
```

### S3 Data Loading

```python
# Load directly from S3
adapter = DatabricksAdapter(
    server_hostname="workspace.cloud.databricks.com",
    http_path="/sql/1.0/warehouses/abc123",
    access_token="dapi...",
    staging_root="s3://my-bucket/benchbox-data"
)

# Data is loaded via COPY INTO from S3
# Ensure IAM role or instance profile has S3 read permissions
```

## Delta Lake Tables

### Automatic Delta Conversion

All benchmark tables are created as Delta Lake tables (or Hudi tables when `table_format="hudi"`):

```python
adapter = DatabricksAdapter(...)
conn = adapter.create_connection()

# Creates Delta Lake tables automatically
schema_time = adapter.create_schema(benchmark, conn)

# Tables created with:
# - CREATE OR REPLACE TABLE ... USING DELTA
# - delta.autoOptimize.optimizeWrite and delta.autoOptimize.autoCompact
#   set to true (while delta_auto_optimize is true)
```

### Manual Delta Optimization

```python
# Optimize specific table
adapter.optimize_table(conn, "lineitem")

# Vacuum old files (removes files older than retention period)
adapter.vacuum_table(conn, "lineitem", hours=168)  # 7 days

# Z-ORDER clustering for query performance
cursor = conn.cursor()
cursor.execute("""
    OPTIMIZE lineitem
    ZORDER BY (l_shipdate, l_orderkey)
""")
```

### Delta Lake Time Travel

```python
# Query historical data
cursor = conn.cursor()

# Query by version
cursor.execute("""
    SELECT * FROM lineitem VERSION AS OF 5
    WHERE l_shipdate = '1995-01-01'
""")

# Query by timestamp
cursor.execute("""
    SELECT * FROM lineitem TIMESTAMP AS OF '2025-01-01 00:00:00'
    WHERE l_shipdate = '1995-01-01'
""")

# View table history
cursor.execute("DESCRIBE HISTORY lineitem")
history = cursor.fetchall()
```

## Query Execution

### Basic Query Execution

```python
adapter = DatabricksAdapter(...)
conn = adapter.create_connection()

# Execute SQL query
cursor = conn.cursor()
cursor.execute("""
    SELECT
        l_returnflag,
        l_linestatus,
        sum(l_quantity) as sum_qty,
        count(*) as count_order
    FROM lineitem
    WHERE l_shipdate <= '1998-09-01'
    GROUP BY l_returnflag, l_linestatus
    ORDER BY l_returnflag, l_linestatus
""")

results = cursor.fetchall()
for row in results:
    print(row)
```

### Query Plans and Optimization

```python
# View query plan
cursor.execute("""
    EXPLAIN FORMATTED
    SELECT * FROM lineitem
    WHERE l_shipdate > '1995-01-01'
""")
plan = cursor.fetchall()

# View query costs
cursor.execute("""
    EXPLAIN COST
    SELECT count(*) FROM lineitem
    GROUP BY l_orderkey
""")
```

## Advanced Features

### Spark Configuration

```python
# Configure Spark settings for performance
cursor = conn.cursor()

# Adaptive Query Execution
cursor.execute("SET spark.sql.adaptive.enabled = true")
cursor.execute("SET spark.sql.adaptive.coalescePartitions.enabled = true")

# Join optimization
cursor.execute("SET spark.sql.adaptive.skewJoin.enabled = true")
cursor.execute("SET spark.sql.join.preferSortMergeJoin = true")
```

### Partitioning Strategy

```python
# Create partitioned Delta table
cursor.execute("""
    CREATE OR REPLACE TABLE orders
    USING DELTA
    PARTITIONED BY (order_year, order_month)
    AS SELECT
        *,
        YEAR(o_orderdate) as order_year,
        MONTH(o_orderdate) as order_month
    FROM orders_raw
""")
```

### Clustering and Z-ORDER

```python
# Z-ORDER clustering for co-location
cursor.execute("""
    OPTIMIZE lineitem
    ZORDER BY (l_orderkey, l_partkey, l_shipdate)
""")

# Check optimization metrics
cursor.execute("DESCRIBE HISTORY lineitem")
history = cursor.fetchall()
```

### Photon Engine

```python
# Photon is enabled automatically on compatible warehouses
# Check if Photon is active
cursor.execute("SET spark.databricks.photon.enabled")
result = cursor.fetchone()
print(f"Photon enabled: {result}")
```

## Best Practices

### Warehouse Selection

1. **Choose appropriate warehouse size** for workload:

   ```python
   # Small: 1-10GB data, development
   # Medium: 10-100GB data, testing
   # Large: 100GB-1TB data, production
   # X-Large/2X-Large: 1TB+ data, heavy workloads
   ```

2. **Use Serverless SQL Warehouses** for variable workloads:

   - Faster start times
   - Better resource utilization
   - Automatic scaling

### Data Staging

1. **Use Unity Catalog Volumes** for managed storage:

   ```python
   adapter = DatabricksAdapter(
       uc_catalog="staging",
       uc_schema="benchmarks",
       uc_volume="tpch_data"
   )
   ```

2. **Prefer cloud storage** (S3, ADLS, GCS) for large datasets:

   ```python
   adapter = DatabricksAdapter(
       staging_root="s3://benchmark-data/tpch"
   )
   ```

### Delta Lake Optimization

1. **Enable auto-optimize** for write performance:

   ```python
   adapter = DatabricksAdapter(
       delta_auto_optimize=True  # Sets both the optimizeWrite and autoCompact table properties
   )
   ```

2. **Run OPTIMIZE regularly** on active tables:

   ```python
   # After bulk loads
   adapter.optimize_table(conn, "lineitem")

   # With Z-ORDER for query patterns
   cursor.execute("OPTIMIZE lineitem ZORDER BY (l_shipdate, l_orderkey)")
   ```

3. **Vacuum old files** to reduce storage costs:

   ```python
   # Keep 7 days of history
   adapter.vacuum_table(conn, "lineitem", hours=168)
   ```

### Cost Optimization

1. **Auto-terminate idle warehouses**. The adapter only records `auto_terminate_minutes`; set the auto-stop time on the SQL warehouse itself (workspace UI or API).

2. **Use smallest warehouse** that meets SLA. Choose the size when you create the warehouse; `cluster_size` on the adapter is only recorded in the results and does not resize anything.

3. **Cache frequently accessed data**:

   ```python
   cursor.execute("CACHE SELECT * FROM lineitem WHERE l_shipdate > '1995-01-01'")
   ```

## Common Issues

### Warehouse Not Available

**Problem**: "Warehouse is not available" error

**Solutions**:

```python
# 1. Check warehouse status
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
warehouses = list(w.warehouses.list())
for wh in warehouses:
    print(f"{wh.name}: {wh.state}")

# 2. Start warehouse manually
# Or use serverless warehouses (auto-start)

# 3. Wait for auto-start (may take 1-2 minutes)
import time
adapter = DatabricksAdapter(...)
for attempt in range(5):
    try:
        conn = adapter.create_connection()
        break
    except Exception as e:
        if "not running" in str(e).lower():
            print(f"Waiting for warehouse to start... (attempt {attempt+1}/5)")
            time.sleep(30)
        else:
            raise
```

### Authentication Failed

**Problem**: "Invalid access token" error

**Solutions**:

```bash
# 1. Verify token hasn't expired
databricks workspace list  # Test token

# 2. Generate new token
# Databricks UI → User Settings → Access Tokens

# 3. Check environment variables
echo $DATABRICKS_TOKEN
```

```python
# 4. Verify token in code
import os
token = os.getenv("DATABRICKS_TOKEN")
if not token:
    raise ValueError("DATABRICKS_TOKEN not set")
```

### Unity Catalog Errors

**Problem**: "Catalog not found" or "Schema not found"

**Solutions**:

```python
# 1. Check catalog permissions
cursor = conn.cursor()
cursor.execute("SHOW CATALOGS")
catalogs = cursor.fetchall()
print("Available catalogs:", catalogs)

# 2. Use workspace catalog (always available)
adapter = DatabricksAdapter(
    catalog="workspace",  # Or "hive_metastore"
    schema="default"
)

# 3. Create catalog if authorized
adapter = DatabricksAdapter(
    catalog="benchmarks",
    schema="tpch",
    create_catalog=True
)
```

### Slow Query Performance

**Problem**: Queries are slower than expected

**Solutions**:

```python
# 1. Enable Photon (if not already enabled)
# Use Photon-enabled warehouse

# 2. Optimize Delta tables
adapter.optimize_table(conn, "lineitem")

# 3. Add Z-ORDER clustering
cursor.execute("""
    OPTIMIZE lineitem
    ZORDER BY (l_orderkey, l_shipdate)
""")

# 4. Update table statistics
cursor.execute("ANALYZE TABLE lineitem COMPUTE STATISTICS")

# 5. Check query plan
cursor.execute("EXPLAIN EXTENDED SELECT ...")
plan = cursor.fetchall()
# Look for FullScan - may need better clustering
```

### Out of Memory Errors

**Problem**: "Out of memory" during query execution

**Solutions**:

```python
# 1. Use larger warehouse
# Switch from Medium to Large or X-Large

# 2. Optimize data layout
cursor.execute("""
    OPTIMIZE lineitem
    ZORDER BY (l_orderkey)
""")

# 3. Reduce data scan with partitioning
cursor.execute("""
    CREATE OR REPLACE TABLE lineitem_partitioned
    USING DELTA
    PARTITIONED BY (l_shipdate_year, l_shipdate_month)
    AS SELECT *, YEAR(l_shipdate) as l_shipdate_year, MONTH(l_shipdate) as l_shipdate_month
    FROM lineitem
""")
```

## See Also

### Platform Documentation

- {doc}`/platforms/platform-selection-guide` - Choosing Databricks vs other platforms
- {doc}`/platforms/quick-reference` - Quick setup for all platforms
- {doc}`/platforms/comparison-matrix` - Feature comparison
- {doc}`/guides/cloud-storage` - S3, ADLS, GCS integration

### Benchmark Guides

- {doc}`/benchmarks/tpc-h` - TPC-H on Databricks
- {doc}`/benchmarks/tpc-ds` - TPC-DS on Databricks
- {doc}`/benchmarks/tpc-di` - TPC-DI on Databricks

### API Reference

- {doc}`duckdb` - DuckDB adapter
- {doc}`clickhouse` - ClickHouse adapter
- {doc}`bigquery` - BigQuery adapter for comparison
- {doc}`../base` - Base benchmark interface
- {doc}`../index` - Python API overview

### External Resources

- [Databricks Documentation](https://docs.databricks.com/aws/en) - Official Databricks docs
- [Delta Lake Guide](https://docs.databricks.com/aws/en/delta) - Delta Lake reference
- [Unity Catalog](https://docs.databricks.com/aws/en/data-governance/unity-catalog) - Unity Catalog docs
- [SQL Warehouses](https://docs.databricks.com/aws/en/compute/sql-warehouse/create) - Warehouse configuration
- [Photon Engine](https://docs.databricks.com/aws/en/compute/photon) - Photon performance
