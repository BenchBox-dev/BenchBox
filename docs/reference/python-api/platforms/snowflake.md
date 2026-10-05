<!-- markdownlint-disable MD024 -->

# Snowflake Platform Adapter

```{tags} reference, python-api, snowflake
```

The Snowflake adapter provides cloud-native data warehouse execution with elastic compute and automatic optimization.

## Overview

Snowflake is a multi-cloud Data Cloud platform. The adapter needs the `snowflake` extra (`pip install "benchbox[snowflake]"`) and a Snowflake account. It provides:

- **Multi-cloud support** - Available on AWS, Azure, and GCP
- **Storage-compute separation** - Independent scaling of storage and compute
- **Elastic compute** - Scale warehouses up/down
- **Multi-cluster warehouses** - Concurrency scaling capabilities
- **Zero-copy cloning** - Instant data cloning for testing
- **Time Travel** - Query historical data (up to 90 days)
- **Micro-partitions** - Self-optimizing data organization

Common use cases:

- Multi-cloud analytics workloads
- Variable workload patterns (auto-suspend/resume)
- Multi-tenant benchmarking environments
- Enterprise-scale data warehousing
- Testing with per-second billing

## Quick Start

### Basic Configuration

```python
from benchbox.tpch import TPCH
from benchbox.platforms.snowflake import SnowflakeAdapter

# Connect to Snowflake
adapter = SnowflakeAdapter(
    account="xy12345.us-east-1",
    username="benchbox_user",
    password="secure_password_123",
    warehouse="COMPUTE_WH",
    database="BENCHBOX",
    schema="PUBLIC"
)

# Generate data, then run the benchmark
benchmark = TPCH(scale_factor=1.0)
benchmark.generate_data()
results = benchmark.run_with_platform(adapter)

print(f"Completed in {results.total_execution_time:.2f}s")
```

## API Reference

### SnowflakeAdapter Class

<span id="benchbox.platforms.snowflake.SnowflakeAdapter"></span>

`benchbox.platforms.snowflake.SnowflakeAdapter` runs BenchBox benchmarks on a Snowflake warehouse, loading data through internal stages.

**Import:** `from benchbox.platforms.snowflake import SnowflakeAdapter` · **Extras:** `snowflake`

#### Parameters

All parameters are keyword arguments (the signature is `(**config)`).

Connection:

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `account` | `str` | required | Snowflake account identifier, for example `"xy12345.us-east-1"`. |
| `username` | `str` | required | User name. |
| `password` | `str` | required | Password. It must be non-empty even with key-pair authentication, where it is not sent. |
| `warehouse` | `str` | `"COMPUTE_WH"` | Virtual warehouse. An empty value uses the default. |
| `database` | `str` | `"BENCHBOX"` | Database for the tables. An empty value uses the default. |
| `schema` | `str` | `"PUBLIC"` | Schema for the tables. |
| `role` | `str` or `None` | `None` | Role for the session. |
| `authenticator` | `str` | `"snowflake"` | Connector authenticator (`"oauth"` and so on). Any value other than `"snowflake"` is passed to the connector. |
| `private_key_path` | `str` or `None` | `None` | PEM private key for key-pair login. When set, the password is not sent. |
| `private_key_passphrase` | `str` or `None` | `None` | Passphrase of an encrypted private key. |

Warehouse. These values are recorded and reported; BenchBox changes the warehouse to match them only when `modify_warehouse_settings` is true:

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `warehouse_size` | `str` | `"MEDIUM"` | Size applied by `ALTER WAREHOUSE` when `modify_warehouse_settings` is true. |
| `auto_suspend` | `int` | `300` | Auto-suspend seconds, applied the same way. |
| `auto_resume` | `bool` | `True` | Auto-resume flag, applied the same way. |
| `multi_cluster_warehouse` | `bool` | `False` | With `modify_warehouse_settings`, sets 1 to 3 clusters instead of the size. |
| `modify_warehouse_settings` | `bool` | `False` | Let `configure_for_benchmark` run `ALTER WAREHOUSE`. The changes persist after the run. |
| `edition` | `str` or `None` | `None` | Account edition (`standard`, `enterprise`, `business_critical`, `vps`), used for cost normalisation. It cannot be read from the service. |

Session and loading:

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `query_tag` | `str` | `"BenchBox"` | Prefix of the session query tag. |
| `timezone` | `str` | `"UTC"` | Session time zone. |
| `disable_result_cache` | `bool` | `True` | Sets `USE_CACHED_RESULT = FALSE` for OLAP benchmark types. |
| `strict_validation` | `bool` | `True` | Raise if the cache setting cannot be confirmed. |
| `suppress_nondeterministic_errors` | `bool` | `False` | Turn off Snowflake's nondeterministic `MERGE` and `UPDATE` errors. |
| `compression` | `str` | `"AUTO"` | `COMPRESSION` of the load file formats. The text is placed in the SQL as given. |
| `file_format` | `str` | `"CSV"` | Recorded and reported only; it does not select the file format. |
| `staging_root` | `str` or `None` | `None` | Cloud URI for external tables, or the user stage `@~/...` for native loads. |
| `table_mode` | `str` | `"native"` | `"native"` or `"external"` (compared in lower case). |
| `iceberg_external_volume` | `str` or `None` | `None` | External volume for Iceberg tables in external mode. |
| `iceberg_catalog` | `str` | `"SNOWFLAKE"` | Catalog for Iceberg tables. |
| `delta_table_format` | `str` | `"DELTA"` | `TABLE_FORMAT` for Delta external tables. |
| `force_recreate` | `bool` | `False` | Drop an existing database when a connection is created. |

The adapter also accepts the keys every BenchBox adapter takes: see [Constructor Parameters](#constructor-parameters). Keys it does not recognise are accepted and ignored. The constructor reads no environment variables: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER` and `SNOWFLAKE_PASSWORD` are mentioned in its error message but not consulted, so pass the values yourself.

#### Returns

A `SnowflakeAdapter`. Construction makes no network call; call `create_connection()` to log in.

#### Raises

- `ImportError`: the Snowflake connector is not installed. The message lists `snowflake-connector-python` and `cloudpathlib` and the install command `pip install 'benchbox[snowflake]'`. This check runs before the others.
- `ConfigurationError` (from `benchbox.core.exceptions`): `account`, `username` or `password` is missing or empty (`Snowflake configuration is incomplete. Missing: ...`; the message lists each missing name).
- `ValueError`: `staging_root` is a Snowflake stage reference that is not valid for the mode. Native mode accepts only the user stage `@~/...`, and external mode accepts only a cloud URI.

Credentials and the account name are not checked here. They fail in `create_connection()`, which needs a live connection and was taken from reading the code.

#### Example

```python
from benchbox.platforms.snowflake import SnowflakeAdapter

adapter = SnowflakeAdapter(account="xy12345.us-east-1", username="benchbox_user", password="secret")
print(adapter.warehouse, adapter.database, adapter.schema, adapter.warehouse_size, adapter.modify_warehouse_settings)
print(adapter.platform_name, adapter.get_target_dialect())

for kwargs in (
    {},
    {"account": "a", "username": "u"},
    {"account": "a", "username": "u", "private_key_path": "key.p8"},
    {"account": "a", "username": "u", "password": "p", "staging_root": "@mystage/x"},
):
    try:
        SnowflakeAdapter(**kwargs)
    except Exception as exc:
        print(type(exc).__name__, str(exc).splitlines()[0])
```

Output on 0.4.1 with `snowflake-connector-python` 4.8.0, run without a network connection:

```text
COMPUTE_WH BENCHBOX PUBLIC MEDIUM False
Snowflake snowflake
ConfigurationError Snowflake configuration is incomplete. Missing: account (or SNOWFLAKE_ACCOUNT), username (or SNOWFLAKE_USER), password (or SNOWFLAKE_PASSWORD)
ConfigurationError Snowflake configuration is incomplete. Missing: password (or SNOWFLAKE_PASSWORD)
ConfigurationError Snowflake configuration is incomplete. Missing: password (or SNOWFLAKE_PASSWORD)
ValueError Snowflake native loads do not reuse named or table stage references as staging_root; use the documented user stage @~/... or a cloud URI for external mode.
```

#### Compatibility

- `benchbox.platforms.SnowflakeAdapter` is the same class.
- The connector comes with the `snowflake` extra; the base `benchbox` install does not include it.
- Key-pair login still needs a non-empty `password`; `password=""` raises `ConfigurationError`. Pass any placeholder.

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

The values are stored as attributes of the same name (`SnowflakeAdapter(account="a", username="u", password="p").force_recreate` is `False`).

### Methods and attributes

Each method is marked with how its description was checked. Calls that talk to Snowflake need an account and a live connection; those are marked as taken from reading the code. The others were run offline, either directly or against a stub connection object that records the SQL the adapter sends and returns prepared rows.

#### Construction and configuration

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.__init__"></span>
**`__init__(**config)`**: Creates the adapter from keyword arguments. See Parameters above. It checks that the Snowflake connector is importable, validates the settings and opens no connection. *Checked offline.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.from_config"></span>
**`from_config(config: dict[str, Any])`** (class method): Builds an adapter from a unified configuration dictionary and returns it. `benchmark` and `scale_factor` are required (a missing key raises `KeyError`). `database` is used when the configuration has a non-empty one; otherwise (absent or empty) it is generated as `<benchmark>_sf<token>_<tuning>`, for example `tpch_sf001_notuning_noconstraints`. The keys `account`, `warehouse`, `schema`, `username`, `password`, `role`, `edition`, `authenticator`, `private_key_path`, `private_key_passphrase`, `warehouse_size`, `auto_suspend`, `auto_resume`, `multi_cluster_warehouse`, `query_tag`, `timezone`, `file_format`, `compression`, `staging_root`, `iceberg_external_volume`, `iceberg_catalog`, `delta_table_format`, `disable_result_cache`, `strict_validation`, `suppress_nondeterministic_errors`, `modify_warehouse_settings`, `force_recreate` and the tuning keys pass through. `force` sets `force_recreate`. `table_mode` and other keys are not forwarded. *Checked offline.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.add_cli_arguments"></span>
**`add_cli_arguments(parser) -> None`** (static method): Adds a `Snowflake Arguments` group to an `argparse.ArgumentParser` and returns `None`: `--account`, `--warehouse` (default `COMPUTE_WH`), `--platform` (the database name), `--schema` (default `PUBLIC`), `--username`, `--password`, `--role`, `--authenticator` (default `snowflake`), `--private-key-path`, `--modify-warehouse-settings`, `--suppress-nondeterministic-errors` and `--no-disable-result-cache`. *Checked offline.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.platform_name"></span>
**`platform_name`** (property): Always the string `'Snowflake'`. *Checked offline.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.get_target_dialect"></span>
**`get_target_dialect() -> str`**: Returns `'snowflake'`, the SQL dialect BenchBox translates queries into. *Checked offline.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.get_platform_info"></span>
**`get_platform_info(connection: Any = None) -> dict[str, Any]`**: Returns a `dict` describing the platform. Without a connection it holds `platform_type` (`'snowflake'`), `platform_name`, `connection_mode` (`'remote'`), `configuration` (`account`, `warehouse`, `database`, `schema`, `role`, `edition`, `warehouse_size`, `auto_suspend`, `auto_resume`, `multi_cluster_warehouse`, `result_cache_enabled`, `file_format`, `compression`, `staging_root`), `client_library_version` (the installed `snowflake-connector-python` version) and `platform_version` (`None`). With a connection it also reads the Snowflake version and warehouse details from the account. *The no-connection form was checked offline; the connected form needs a live connection and was taken from reading the code.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.get_normalized_result_metadata"></span>
**`get_normalized_result_metadata(*, connection: Any | None = None, platform_info: Mapping[str, Any] | None = None) -> dict[str, Any]`**: Returns the platform metadata that BenchBox stores with results, as a `dict` with the entries `execution_environment`, `platform_deployment` (`deployment_type` `'managed_cloud'`), `platform_raw_config` (with `username` and `password` shown as `<redacted>`), `platform_cloud`, `platform_compute` and `platform_storage`. Pass `connection` or a precomputed `platform_info` (keyword-only); without either it calls `get_platform_info()`. *Checked offline.*

#### Connection and database

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.create_connection"></span>
**`create_connection(**connection_config) -> Any`**: Returns a `snowflake.connector` connection with `autocommit` on, `application='BenchBox'` and the adapter's `timezone`, `warehouse`, `database` and `schema`. Existing-database handling comes first: with `force_recreate=True` the database is dropped, and otherwise it is validated and reused if it passes. With `private_key_path` it logs in with the key (read with `private_key_passphrase`) and does not send the password; with `authenticator` other than `'snowflake'` it passes that authenticator through. It runs `SELECT CURRENT_VERSION()` to prove the connection works, so bad credentials or a missing database raise here, as the underlying connector exception. *Needs a live connection; taken from reading the code.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.close_connection"></span>
**`close_connection(connection: Any) -> None`**: Closes the connection and returns `None`. `None` is accepted, and an error while closing is logged as a warning, not raised. *Checked offline against a stub connection.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.check_server_database_exists"></span>
**`check_server_database_exists(**connection_config) -> bool`**: Returns `True` when the account has a database named `database` (or the `database` keyword). If it does not, it also returns `True` when that database has a schema `schema` that already holds tables. Any error, including a failed login, returns `False`. *Needs a live connection; taken from reading the code.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.drop_database"></span>
**`drop_database(**connection_config) -> None`**: Runs `DROP DATABASE IF EXISTS "<database>"` and returns `None`. Raises `RuntimeError` (`Failed to drop Snowflake database ...`) on failure. *Needs a live connection; taken from reading the code.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.configure_for_benchmark"></span>
**`configure_for_benchmark(connection: Any, benchmark_type: str) -> None`**: Applies session settings to an open connection and returns `None`. It sets the query tag `<query_tag>_optimization`, the time zone, `AUTOCOMMIT = TRUE`, and for the benchmark types `olap`, `analytics`, `tpch` and `tpcds` also `QUERY_ACCELERATION_MAX_SCALE_FACTOR = 8`, `USE_CACHED_RESULT` (`FALSE` while `disable_result_cache` is true) and `STATEMENT_TIMEOUT_IN_SECONDS = 1800`. With `suppress_nondeterministic_errors` it turns off the nondeterministic-merge and -update errors. Warehouse changes (`ALTER WAREHOUSE` for size, auto-suspend, auto-resume or multi-cluster scaling) happen only when `modify_warehouse_settings` is true; they persist after the run. It finishes with `USE WAREHOUSE` and, when the result cache is disabled, validates the setting as `validate_session_cache_control` does and stores the outcome. *Checked offline against a stub connection.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.validate_session_cache_control"></span>
**`validate_session_cache_control(connection: Any) -> dict[str, Any]`**: Reads `SHOW PARAMETERS LIKE 'USE_CACHED_RESULT' IN SESSION` and returns a `dict` with `validated` (the value matches what `disable_result_cache` asks for), `cache_disabled`, `settings` (for example `{'USE_CACHED_RESULT': 'FALSE'}`), `warnings` and `errors`. When the value does not match and `strict_validation` is true (the default) it raises `ConfigurationError` (`Snowflake session cache control validation failed - benchmark results may be incorrect due to cached query results`); with `strict_validation=False` it returns `validated: False` instead. *Checked offline against a stub connection.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.create_schema"></span>
**`create_schema(benchmark, connection: Any) -> float`**: Creates the database and schema if they do not exist, makes them current, and runs the benchmark's `CREATE TABLE` statements, returning the elapsed time in seconds (`float`). When every expected table already exists and holds rows (and `force_recreate` is false) it skips the table creation and returns early; loads are full refreshes either way, so skipped DDL never leaves stale data. It sets the query tag `<query_tag>_schema_creation`. *Needs a live connection; taken from reading the code.*

#### Loading data into tables

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.load_data"></span>
**`load_data(benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]`**: Loads the benchmark's data files and returns `(table_row_counts, seconds, per_table_timings)`; `table_row_counts` maps upper-case table names to the row counts read back with `SELECT COUNT(*)`. Each file is uploaded with `PUT` to the table's internal stage (`@%TABLE`) and loaded with `COPY INTO ... ON_ERROR = 'CONTINUE' PURGE = TRUE FORCE = TRUE`. Every load is a full refresh: leftover stage files are removed and the table is truncated first, so reruns do not append. A table with no usable files is reported with `0` rows. Any other failure stops the run, because a half-loaded table must not be benchmarked. Text files use the delimiter the benchmark declares (`|` for `.tbl`) and the file formats `BENCHBOX_CSV_FORMAT` and `BENCHBOX_TBL_FORMAT`, created with the adapter's `compression`; Parquet files are loaded with `MATCH_BY_COLUMN_NAME = 'CASE_INSENSITIVE'`. *Needs a live connection; taken from reading the code.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.create_external_tables"></span>
**`create_external_tables(benchmark: Any, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]`**: Registers external tables over files in cloud storage and returns `(table_row_counts, seconds, None)`. It first calls `validate_external_table_requirements`. It creates the stage `<schema>.BENCHBOX_EXTERNAL_STAGE` with `URL` set to `staging_root`, and then, per table, an external table (Parquet or Delta, selected from the local files' layout) or, for Iceberg directories, an Iceberg table that needs `iceberg_external_volume`. Each table is refreshed and counted. *Needs a live connection; taken from reading the code.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.supports_external_tables"></span>
**`supports_external_tables`** (class attribute): `True`. The adapter implements `create_external_tables`. *Checked offline.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.validate_external_table_requirements"></span>
**`validate_external_table_requirements() -> None`**: Returns `None` when `staging_root` is a cloud URI. Raises `ValueError` when it is not set (`Snowflake external mode requires --platform-option staging_root=<cloud-uri> ...`), or when it is a Snowflake stage reference such as `@~/path` (external tables need a URI). *Checked offline.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.analyze_table"></span>
**`analyze_table(connection: Any, table_name: str) -> None`**: Runs `ALTER TABLE <TABLE> RECLUSTER` for the upper-cased table name and returns `None`. Snowflake keeps its own statistics, so this is a clustering maintenance call. A failure is raised, not swallowed, so that the statistics phase can record it as failed. *Checked offline against a stub connection.*

#### Query execution and plans

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.execute_query"></span>
**`execute_query(connection: Any, query: str, query_id: str, benchmark_type: str | None = None, scale_factor: float | None = None, validate_row_count: bool = True, stream_id: int | None = None) -> dict[str, Any]`**: Runs one query and returns a result `dict`; it does not raise for SQL errors. It sets the session query tag to `<query_tag>_<query_id>`, runs the query (divisions are guarded against zero divisors), and on success returns `status` `'SUCCESS'` with `query_id`, `execution_time_seconds`, `rows_returned`, `first_row`, `translated_query` (`None`), `query_statistics` and `resource_usage`. `query_statistics` comes from `INFORMATION_SCHEMA.QUERY_HISTORY` and may hold only a note that statistics were not available yet. It accepts a connection or an open cursor. On an error `status` is `'FAILED'` with `error` and `error_type`. *Checked offline against a stub connection.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.get_query_plan"></span>
**`get_query_plan(connection: Any, query: str) -> str | None`**: Returns the plan as the JSON text of `EXPLAIN USING JSON <query>` (a single value), or `None` if the statement fails or returns nothing. It accepts a connection or an open cursor. *Checked offline against a stub connection.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.get_query_plan_parser"></span>
**`get_query_plan_parser()`**: Returns a `SnowflakeQueryPlanParser` (from `benchbox.core.query_plans.parsers.snowflake`). *Checked offline.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.plan_capture_phase_eligible"></span>
**`plan_capture_phase_eligible`** (class attribute): `True`. Query plans for Snowflake are captured in a separate pass after the timed run, not inline with the timed queries. *Checked offline.*

#### Tuning

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.generate_tuning_clause"></span>
**`generate_tuning_clause(table_tuning) -> str`**: Returns the clause to append to `CREATE TABLE`, or `''` when there is no tuning. Clustering columns give `CLUSTER BY (c1, c2, ...)` in `order` sequence. Without clustering columns, partitioning columns give the same `CLUSTER BY (...)`. Sorting and distribution add nothing; a table with only those returns `''`. *Checked offline.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.apply_table_tunings"></span>
**`apply_table_tunings(table_tuning, connection: Any) -> None`**: Sets the clustering key of an existing table and returns `None`. It reads `CLUSTERING_KEY` and `AUTO_CLUSTERING_ON` from `INFORMATION_SCHEMA.TABLES`; if the key differs from the wanted columns (clustering columns, else partitioning columns) it runs `ALTER TABLE <TABLE> CLUSTER BY (...)`. For four columns or fewer it also marks the table for `ALTER TABLE <TABLE> RESUME RECLUSTER`, which runs after the table loads and is reported as `phases.post_load_maintenance`, not as load time. If the key already matches it skips the `ALTER` and only marks the table when automatic reclustering is off. Sorting adds nothing and distribution is logged as unsupported. It does nothing for an empty tuning. Raises `ValueError` (`Failed to apply tunings to Snowflake table <TABLE>: ...`) on an unexpected failure. *Checked offline against a stub connection.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.apply_unified_tuning"></span>
**`apply_unified_tuning(unified_config: UnifiedTuningConfiguration, connection: Any) -> None`**: Applies a `UnifiedTuningConfiguration` and returns `None`: `apply_constraint_configuration`, then `apply_platform_optimizations` when present, then `apply_table_tunings` for each table. It does nothing for an empty configuration. *Checked offline against a stub connection.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.apply_platform_optimizations"></span>
**`apply_platform_optimizations(platform_config: PlatformOptimizationConfiguration, connection: Any) -> None`**: Logs that the optimisations are stored for warehouse and session management and returns `None`. It changes nothing in Snowflake, and does nothing for `None`. *Checked offline against a stub connection.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.apply_constraint_configuration"></span>
**`apply_constraint_configuration(primary_key_config: PrimaryKeyConfiguration, foreign_key_config: ForeignKeyConfiguration, connection: Any) -> None`**: Logs that primary-key or foreign-key constraints are enabled (informational only in Snowflake) and returns `None`. It runs no SQL. *Checked offline against a stub connection.*

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.get_tuning_introspector"></span>
**`get_tuning_introspector()`**: Returns a `SnowflakeTuningIntrospector` (from `benchbox.platforms.snowflake_introspection`), which reads clustering keys from `INFORMATION_SCHEMA` to confirm that the recorded `ALTER TABLE ... CLUSTER BY` statements took effect. *Checked offline.*

#### Capabilities

<span id="benchbox.platforms.snowflake.SnowflakeAdapter.driver_isolation_capability"></span>
**`driver_isolation_capability`** (class attribute): `DriverIsolationCapability.FEASIBLE_CLIENT_ONLY` (from `benchbox.platforms.base`): a requested connector version can run in an isolated runtime, but the Snowflake service itself cannot be versioned. *Checked offline.*

## Configuration Examples

### Password Authentication

```python
adapter = SnowflakeAdapter(
    account="xy12345.us-east-1",
    username="benchbox_user",
    password="secure_password_123",
    warehouse="COMPUTE_WH",
    database="BENCHBOX"
)
```

### Key-Pair Authentication (Recommended for Production)

```bash
# Generate key pair
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt

# Extract public key
openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub

# In Snowflake, assign public key to user
ALTER USER benchbox_user SET RSA_PUBLIC_KEY='MIIBIjANBgkqh...';
```

```python
adapter = SnowflakeAdapter(
    account="xy12345.us-east-1",
    username="benchbox_user",
    password="unused",  # Must be non-empty, but is not sent with key-pair
    private_key_path="/path/to/rsa_key.p8",
    warehouse="COMPUTE_WH",
    database="BENCHBOX"
)
```

### OAuth Authentication

```python
adapter = SnowflakeAdapter(
    account="xy12345.us-east-1",
    username="benchbox_user",
    password="oauth_token_here",
    authenticator="oauth",
    warehouse="COMPUTE_WH",
    database="BENCHBOX"
)
```

### Warehouse Sizing

`warehouse_size`, `auto_suspend`, `auto_resume` and `multi_cluster_warehouse` change the warehouse only when `modify_warehouse_settings=True` is also set. Without it the adapter uses the warehouse as it is and only records the values. The `ALTER WAREHOUSE` changes persist after the run.

```python
# Small for development (1 credit/hour)
adapter = SnowflakeAdapter(
    account="xy12345.us-east-1",
    username="user",
    password="password",
    warehouse="DEV_WH",
    warehouse_size="X-SMALL",
    modify_warehouse_settings=True
)

# Large for production (8 credits/hour)
adapter = SnowflakeAdapter(
    account="xy12345.us-east-1",
    username="user",
    password="password",
    warehouse="PROD_WH",
    warehouse_size="LARGE",
    modify_warehouse_settings=True
)

# 4X-Large for heavy workloads (128 credits/hour)
adapter = SnowflakeAdapter(
    account="xy12345.us-east-1",
    username="user",
    password="password",
    warehouse="HEAVY_WH",
    warehouse_size="4X-LARGE",
    modify_warehouse_settings=True
)
```

### Multi-Cluster Warehouse

```python
# Auto-scale for concurrent workloads
adapter = SnowflakeAdapter(
    account="xy12345.us-east-1",
    username="user",
    password="password",
    warehouse="MULTI_CLUSTER_WH",
    warehouse_size="LARGE",
    multi_cluster_warehouse=True,
    modify_warehouse_settings=True,  # Needed for the settings above to take effect
    auto_suspend=60,  # Suspend after 1 minute idle
    auto_resume=True
)
```

## Data Loading

### PUT and COPY INTO (Recommended)

Snowflake uses internal stages for efficient data loading:

```python
from benchbox.platforms.snowflake import SnowflakeAdapter
from benchbox.tpch import TPCH
from pathlib import Path

adapter = SnowflakeAdapter(
    account="xy12345.us-east-1",
    username="user",
    password="password",
    warehouse="LOAD_WH",
    database="BENCHBOX"
)

# Generate data locally
data_dir = Path("./tpch_data")
benchmark = TPCH(scale_factor=1.0, output_dir=data_dir)
benchmark.generate_data()

# Create the tables, then load data (automatically uses PUT + COPY INTO)
conn = adapter.create_connection()
adapter.create_schema(benchmark, conn)
table_stats, load_time, _ = adapter.load_data(benchmark, conn, data_dir)

# Data uploaded to internal stage, then bulk loaded
print(f"Loaded {sum(table_stats.values()):,} rows in {load_time:.2f}s")
```

### External Stage (S3/GCS/Azure)

```python
# Create external stage
conn = adapter.create_connection()
cursor = conn.cursor()

# S3 external stage
cursor.execute("""
    CREATE OR REPLACE STAGE benchbox_stage
    URL = 's3://my-bucket/benchbox-data/'
    CREDENTIALS = (
        AWS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'
        AWS_SECRET_KEY = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'
    )
""")

# Load from external stage
cursor.execute("""
    COPY INTO lineitem
    FROM @benchbox_stage/lineitem.tbl
    FILE_FORMAT = (
        TYPE = 'CSV'
        FIELD_DELIMITER = '|'
        SKIP_HEADER = 0
    )
""")
```

### Compressed Data

```python
# compression sets the COMPRESSION option of the load file formats
adapter = SnowflakeAdapter(
    account="xy12345.us-east-1",
    username="user",
    password="password",
    compression="GZIP"  # GZIP, BROTLI, ZSTD, etc.
)

# GZIP files automatically decompressed during COPY INTO
```

## Query Execution

### Basic Query Execution

```python
adapter = SnowflakeAdapter(account="...", username="...", password="...")
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

### Query Statistics

```python
# Execute with query tag for tracking
cursor.execute("ALTER SESSION SET QUERY_TAG = 'benchmark_q1'")
cursor.execute(query)
results = cursor.fetchall()

# Get query history with performance metrics
cursor.execute("""
    SELECT
        QUERY_ID,
        QUERY_TEXT,
        TOTAL_ELAPSED_TIME,
        EXECUTION_TIME,
        COMPILATION_TIME,
        BYTES_SCANNED,
        ROWS_PRODUCED,
        CREDITS_USED_CLOUD_SERVICES,
        WAREHOUSE_SIZE
    FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY())
    WHERE QUERY_TAG = 'benchmark_q1'
    ORDER BY START_TIME DESC
    LIMIT 1
""")

stats = cursor.fetchone()
print(f"Execution time: {stats[3]}ms")
print(f"Bytes scanned: {stats[5]:,}")
print(f"Credits used: {stats[7]}")
```

### Query Plans

```python
# Get query execution plan
cursor.execute("""
    EXPLAIN
    SELECT * FROM lineitem
    WHERE l_shipdate > '1995-01-01'
""")

plan = cursor.fetchall()
for step in plan:
    print(step[0])
```

## Advanced Features

### Clustering

```python
# Create table with clustering key
cursor.execute("""
    CREATE OR REPLACE TABLE orders_clustered (
        o_orderkey NUMBER,
        o_custkey NUMBER,
        o_orderstatus STRING,
        o_totalprice NUMBER(15,2),
        o_orderdate DATE
    )
    CLUSTER BY (o_orderdate, o_orderkey)
""")

# Snowflake automatically maintains clustering

# Manual recluster if needed
cursor.execute("ALTER TABLE orders_clustered RECLUSTER")

# Enable automatic clustering
cursor.execute("ALTER TABLE orders_clustered RESUME RECLUSTER")

# Check clustering quality
cursor.execute("""
    SELECT SYSTEM$CLUSTERING_INFORMATION('orders_clustered')
""")
```

### Time Travel

```python
# Query data as of 1 hour ago
cursor.execute("""
    SELECT * FROM lineitem
    AT(OFFSET => -3600)
    WHERE l_shipdate = '1995-01-01'
""")

# Query data at specific timestamp
cursor.execute("""
    SELECT * FROM lineitem
    AT(TIMESTAMP => '2025-01-01 00:00:00'::TIMESTAMP)
    WHERE l_shipdate = '1995-01-01'
""")

# View table changes (before/after)
cursor.execute("""
    SELECT * FROM lineitem
    BEFORE(STATEMENT => '01a12345-6789-abcd-ef01-234567890abc')
""")
```

### Zero-Copy Cloning

```python
# Clone database instantly (no data copy)
cursor.execute("""
    CREATE DATABASE benchbox_clone
    CLONE benchbox
""")

# Clone table
cursor.execute("""
    CREATE TABLE lineitem_clone
    CLONE lineitem
""")

# Clone at specific time
cursor.execute("""
    CREATE TABLE lineitem_yesterday
    CLONE lineitem
    AT(OFFSET => -86400)  -- 24 hours ago
""")
```

### Result Set Caching

Snowflake caches results by default, but the adapter turns the cache off for benchmark runs (`disable_result_cache=True`) so that timings are real. To allow caching, pass `disable_result_cache=False` or set the parameter yourself:

```python
# Enable result caching
cursor.execute("ALTER SESSION SET USE_CACHED_RESULT = TRUE")

# First execution computes result
cursor.execute("SELECT COUNT(*) FROM lineitem")
result1 = cursor.fetchone()  # Executes query

# Second execution uses cached result (instant, no credits)
cursor.execute("SELECT COUNT(*) FROM lineitem")
result2 = cursor.fetchone()  # Returns cached result
```

## Best Practices

### Warehouse Management

1. **Right-size warehouses** for workload:

   ```python
   # Development: X-SMALL to SMALL
   # Testing: MEDIUM to LARGE
   # Production: LARGE to 4X-LARGE

   adapter = SnowflakeAdapter(
       warehouse_size="MEDIUM",  # Balance of cost and performance
       auto_suspend=300,  # Suspend after 5 min idle
       auto_resume=True,  # Auto-resume on query
       modify_warehouse_settings=True  # Apply these values to the warehouse
   )
   ```

2. **Use separate warehouses** for different workloads:

   ```python
   # Loading warehouse
   load_adapter = SnowflakeAdapter(warehouse="LOAD_WH", warehouse_size="LARGE")

   # Query warehouse
   query_adapter = SnowflakeAdapter(warehouse="QUERY_WH", warehouse_size="MEDIUM")
   ```

3. **Enable multi-cluster** for concurrent workloads:

   ```python
   adapter = SnowflakeAdapter(
       warehouse="CONCURRENT_WH",
       multi_cluster_warehouse=True
   )
   ```

### Cost Optimization

1. **Suspend idle warehouses**:

   ```python
   adapter = SnowflakeAdapter(
       auto_suspend=60,  # Aggressive suspension (1 minute)
       auto_resume=True
   )
   ```

2. **Use result caching**:

   ```python
   # Snowflake reuses results for identical queries when this is TRUE.
   # BenchBox sets it to FALSE during benchmark runs (disable_result_cache=True).
   cursor.execute("ALTER SESSION SET USE_CACHED_RESULT = TRUE")
   ```

3. **Start small, scale up as needed**:

   ```python
   # Start with smallest warehouse
   adapter = SnowflakeAdapter(warehouse_size="X-SMALL")

   # Monitor and resize if needed
   cursor.execute(f"ALTER WAREHOUSE {warehouse} SET WAREHOUSE_SIZE = 'MEDIUM'")
   ```

4. **Monitor credit usage**:

   ```python
   # Check warehouse credit usage
   cursor.execute("""
       SELECT
           WAREHOUSE_NAME,
           SUM(CREDITS_USED) as total_credits,
           SUM(CREDITS_USED_COMPUTE) as compute_credits,
           SUM(CREDITS_USED_CLOUD_SERVICES) as cloud_services_credits
       FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
       WHERE START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP())
       GROUP BY WAREHOUSE_NAME
       ORDER BY total_credits DESC
   """)
   ```

### Data Organization

1. **Use clustering keys** for filtered columns:

   ```python
   CREATE TABLE lineitem (...)
   CLUSTER BY (l_shipdate, l_orderkey)
   ```

2. **Partition large tables** by date:

   ```python
   # Snowflake automatically creates micro-partitions
   # Clustering by date provides similar benefits
   CLUSTER BY (DATE_TRUNC('month', order_date))
   ```

3. **Analyze clustering quality**:

   ```python
   cursor.execute("""
       SELECT SYSTEM$CLUSTERING_INFORMATION('lineitem')
   """)

   # Recluster if quality degrades
   if clustering_depth > 10:
       cursor.execute("ALTER TABLE lineitem RECLUSTER")
   ```

## Common Issues

### Warehouse Not Running

**Problem**: "Warehouse is suspended" error

**Solutions**:

```python
# 1. Enable auto-resume
adapter = SnowflakeAdapter(
    auto_resume=True  # Warehouse starts automatically
)

# 2. Manually resume warehouse
cursor.execute(f"ALTER WAREHOUSE {warehouse} RESUME")

# 3. Check warehouse status
cursor.execute(f"SHOW WAREHOUSES LIKE '{warehouse}'")
status = cursor.fetchall()
print(f"Warehouse state: {status[0][1]}")
```

### Authentication Failed

**Problem**: "Incorrect username or password" error

**Solutions**:

```python
# 1. Verify account identifier format
# Correct: "xy12345.us-east-1" or "xy12345.us-east-1.aws"
# Incorrect: "https://xy12345.snowflakecomputing.com"

# 2. Check username (case-insensitive but must exist)
# In Snowflake UI: SHOW USERS;

# 3. Use key-pair auth for better security
adapter = SnowflakeAdapter(
    account="xy12345.us-east-1",
    username="benchbox_user",
    password="unused",  # Must be non-empty, but is not sent with key-pair
    private_key_path="/path/to/key.p8"
)
```

### Insufficient Privileges

**Problem**: "Insufficient privileges" error

**Solutions**:

```bash
# Grant required privileges in Snowflake
GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE benchbox_role;
GRANT USAGE ON DATABASE BENCHBOX TO ROLE benchbox_role;
GRANT CREATE SCHEMA ON DATABASE BENCHBOX TO ROLE benchbox_role;
GRANT USAGE ON SCHEMA BENCHBOX.PUBLIC TO ROLE benchbox_role;
GRANT CREATE TABLE ON SCHEMA BENCHBOX.PUBLIC TO ROLE benchbox_role;
```

```python
# Specify role with sufficient privileges
adapter = SnowflakeAdapter(
    account="xy12345.us-east-1",
    username="user",
    password="password",
    role="BENCHBOX_ROLE"  # Role with required privileges
)
```

### High Costs

**Problem**: Unexpected credit consumption

**Solutions**:

```python
# 1. Check query history for expensive queries
cursor.execute("""
    SELECT
        QUERY_TEXT,
        TOTAL_ELAPSED_TIME,
        BYTES_SCANNED,
        CREDITS_USED_CLOUD_SERVICES
    FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY())
    WHERE START_TIME >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
    ORDER BY CREDITS_USED_CLOUD_SERVICES DESC
    LIMIT 10
""")

# 2. Use smaller warehouse
adapter = SnowflakeAdapter(warehouse_size="X-SMALL")

# 3. Enable aggressive auto-suspend
adapter = SnowflakeAdapter(auto_suspend=60)  # 1 minute

# 4. Set resource monitors
cursor.execute("""
    CREATE RESOURCE MONITOR daily_limit WITH CREDIT_QUOTA = 100
    TRIGGERS ON 75 PERCENT DO NOTIFY
             ON 100 PERCENT DO SUSPEND
""")

cursor.execute(f"""
    ALTER WAREHOUSE {warehouse} SET RESOURCE_MONITOR = daily_limit
""")
```

### Slow Query Performance

**Problem**: Queries slower than expected

**Solutions**:

```python
# 1. Resize warehouse
cursor.execute(f"""
    ALTER WAREHOUSE {warehouse} SET WAREHOUSE_SIZE = 'LARGE'
""")

# 2. Check clustering quality
cursor.execute("""
    SELECT SYSTEM$CLUSTERING_INFORMATION('lineitem')
""")

# 3. Add clustering keys
cursor.execute("""
    ALTER TABLE lineitem CLUSTER BY (l_shipdate, l_orderkey)
""")

# 4. Enable automatic clustering
cursor.execute("ALTER TABLE lineitem RESUME RECLUSTER")

# 5. Check query profile
# In Snowflake UI: Query History → Click query → View Profile
```

## See Also

### Platform Documentation

- {doc}`/platforms/platform-selection-guide` - Choosing Snowflake vs other platforms
- {doc}`/platforms/quick-reference` - Quick setup for all platforms
- {doc}`/platforms/comparison-matrix` - Feature comparison

### Benchmark Guides

- {doc}`/benchmarks/tpc-h` - TPC-H on Snowflake
- {doc}`/benchmarks/tpc-ds` - TPC-DS on Snowflake

### API Reference

- {doc}`duckdb` - DuckDB adapter
- {doc}`clickhouse` - ClickHouse adapter
- {doc}`databricks` - Databricks adapter
- {doc}`bigquery` - BigQuery adapter
- {doc}`../base` - Base benchmark interface
- {doc}`../index` - Python API overview

### External Resources

- [Snowflake Documentation](https://docs.snowflake.com/en/) - Official Snowflake docs
- [Warehouse Sizing](https://docs.snowflake.com/en/user-guide/warehouses-considerations) - Sizing guidance
- [Clustering Keys](https://docs.snowflake.com/en/user-guide/tables-clustering-keys) - Clustering best practices
- [Cost Optimization](https://docs.snowflake.com/en/user-guide/cost-understanding-overall) - Cost management
- [Time Travel](https://docs.snowflake.com/en/user-guide/data-time-travel) - Time Travel guide
