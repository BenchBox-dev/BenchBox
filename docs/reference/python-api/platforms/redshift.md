<!-- markdownlint-disable MD024 -->

# Amazon Redshift Platform Adapter

```{tags} reference, python-api, cloud-platform
```

The Redshift adapter provides AWS-native data warehouse execution with S3 integration and columnar storage optimization.

## Overview

Amazon Redshift is a fully managed petabyte-scale data warehouse service. The adapter needs the `redshift` extra (`pip install "benchbox[redshift]"`) and a cluster or serverless workgroup you can reach. It provides:

- **Columnar storage** - Optimized for analytical queries
- **Massively parallel processing** - Distributed query execution
- **S3 integration** - COPY command for bulk loading
- **Automatic backups** - Point-in-time recovery capabilities
- **Concurrency scaling** - Automatic scaling for concurrent workloads
- **Redshift Spectrum** - Query data directly in S3

Common use cases:

- AWS-native analytics workloads
- Large-scale data warehousing (TB to PB scale)
- Integration with AWS ecosystem
- Reserved or serverless deployment options
- Federated queries across data lake and warehouse

## Quick Start

### Basic Configuration

```python
from benchbox.tpch import TPCH
from benchbox.platforms.redshift import RedshiftAdapter

adapter = RedshiftAdapter(
    host="my-cluster.123456.us-east-1.redshift.amazonaws.com",
    port=5439,
    database="dev",
    username="admin",
    password="SecurePassword123"
)

benchmark = TPCH(scale_factor=1.0)
benchmark.generate_data()
results = benchmark.run_with_platform(adapter)
```

`run_with_platform` does not generate data. Without `generate_data()` the tables are created empty.

### With S3 Data Loading

```python
adapter = RedshiftAdapter(
    host="my-cluster.123456.us-east-1.redshift.amazonaws.com",
    username="admin",
    password="SecurePassword123",
    database="benchbox",
    s3_bucket="my-redshift-data",
    s3_prefix="benchbox/staging",
    iam_role="arn:aws:iam::123456789:role/RedshiftCopyRole"
)
```

This configuration loads data efficiently through the S3 COPY command.

## API Reference

### RedshiftAdapter Class

<span id="benchbox.platforms.redshift.RedshiftAdapter"></span>

`benchbox.platforms.redshift.RedshiftAdapter` runs BenchBox benchmarks on Amazon Redshift (provisioned or serverless), loading data through S3 when a bucket is configured.

**Import:** `from benchbox.platforms.redshift import RedshiftAdapter` · **Extras:** `redshift`

#### Parameters

All parameters are keyword arguments (the signature is `(**config)`).

Connection:

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `host` | `str` | required | Cluster or workgroup endpoint. A name containing `.redshift-serverless.amazonaws.com` is treated as serverless, `.redshift.amazonaws.com` as provisioned, anything else as unknown (`deployment_type`). |
| `username` | `str` | required | Database user. |
| `password` | `str` | required | Password. |
| `port` | `int` | `5439` | Port. `None` also gives `5439`. |
| `database` | `str` | `"dev"` | Database for the tables; created if it does not exist. |
| `admin_database` | `str` | `"dev"` | Existing database used to run `CREATE DATABASE`, `DROP DATABASE` and existence checks. |
| `schema` | `str` | `"public"` | Schema for the tables; set as the search path. |
| `cluster_identifier` | `str` or `None` | `None` | Cluster identifier, recorded for metadata. |
| `connect_timeout` | `int` | `10` | Base connection timeout in seconds; raised automatically for serverless, paused or resuming targets. |
| `statement_timeout` | `int` | `0` | `statement_timeout` for the session; `0` sets nothing. |
| `sslmode` | `str` | `"require"` | SSL mode. |
| `ssl_enabled` | `bool` | `True` | Use SSL. |
| `ssl_insecure` | `bool` | `False` | Skip certificate verification. |
| `sslrootcert` | `str` or `None` | `None` | Root certificate for the `psycopg` driver. |

Workload and maintenance:

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `wlm_query_slot_count` | `int` | `1` | Sets `wlm_query_slot_count` for the session when above 1. |
| `wlm_query_queue_name` | `str` or `None` | `None` | Query group for validation connections. |
| `wlm_config` | any | `None` | Stored as `workload_management_config`. |
| `compupdate` | `str` | `"PRESET"` | `COMPUPDATE` option of `COPY`: `ON`, `OFF` or `PRESET`, in any case. Anything else raises `ValueError`. |
| `auto_vacuum` | `bool` | `True` | Run `VACUUM` on every table in `configure_for_benchmark`. |
| `auto_analyze` | `bool` | `True` | Run `ANALYZE` after each `COPY` load and in `configure_for_benchmark`. |
| `disable_result_cache` | `bool` | `True` | Sets `enable_result_cache_for_session` to `off`. |
| `strict_validation` | `bool` | `True` | Raise if the cache setting cannot be confirmed. |
| `force_recreate` | `bool` | `False` | Drop an existing database when a connection is created. |

S3 and credentials:

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `staging_root` | `str` or `None` | `None` | `s3://bucket/prefix`. Sets `s3_bucket` and `s3_prefix` (the prefix is `benchbox-data` when the URL has no path). Any other scheme raises `ValueError`. |
| `s3_bucket` | `str` or `None` | `None` | Bucket for staging data files. Used when `staging_root` is not given. |
| `s3_prefix` | `str` | `"benchbox-data"` | Key prefix inside the bucket. |
| `iam_role` | `str` or `None` | `None` | IAM role ARN that `COPY` and Spectrum use. |
| `aws_access_key_id`, `aws_secret_access_key`, `aws_session_token` | `str` or `None` | `None` | Explicit credentials for the S3 upload and for `COPY` when no `iam_role` is set. The first two must be given together. |
| `aws_region` | `str` | `"us-east-1"` | Region for the S3 and Glue clients. |

The adapter also accepts the keys every BenchBox adapter takes: see [Constructor Parameters](#constructor-parameters). Keys it does not recognise are accepted and ignored. `compression_encoding` is not a parameter; the `COPY` compression option is `compupdate`. The constructor reads no environment variables: `REDSHIFT_HOST`, `REDSHIFT_USER` and `REDSHIFT_PASSWORD` are mentioned in its error message but not consulted, so pass the values yourself.

#### Returns

A `RedshiftAdapter`. Construction makes no network call; call `create_connection()` to connect.

#### Raises

- `ImportError`: no Redshift driver (`redshift-connector` or `psycopg`) is installed, or a shared package (`boto3`, `cloudpathlib`) is missing. The message lists the packages and the install command `pip install 'benchbox[redshift]'`. This check runs before the others.
- `ConfigurationError` (from `benchbox.core.exceptions`): `host`, `username` or `password` is missing or empty (`Redshift configuration is incomplete. Missing: ...`).
- `ValueError`: `compupdate` is not `ON`, `OFF` or `PRESET` (`Invalid COMPUPDATE value: 'bogus'. Must be one of: OFF, ON, PRESET`), or `staging_root` is not an `s3://` location (`Redshift requires S3 (s3://) staging location, got: gs://`).

Hosts and credentials are not checked here. They fail in `create_connection()`, which needs a live connection and was taken from reading the code.

#### Example

```python
from benchbox.platforms.redshift import RedshiftAdapter

adapter = RedshiftAdapter(
    host="wg.123456789012.us-east-2.redshift-serverless.amazonaws.com",
    username="admin",
    password="secret",
    staging_root="s3://my-bucket/benchbox/tpch",
    compupdate="off",
)
print(adapter.deployment_type, adapter.port, adapter.database, adapter.s3_bucket, adapter.s3_prefix, adapter.compupdate)
print(adapter.platform_name, adapter.get_target_dialect(), adapter.auto_vacuum, adapter.auto_analyze)

for kwargs in (
    {},
    {"host": "h", "username": "u", "password": "p", "compupdate": "bogus"},
    {"host": "h", "username": "u", "password": "p", "staging_root": "gs://b/p"},
):
    try:
        RedshiftAdapter(**kwargs)
    except Exception as exc:
        print(type(exc).__name__, str(exc).splitlines()[0])
```

Output on 0.4.1 with `redshift-connector` 2.1.17, run without a network connection:

```text
serverless 5439 dev my-bucket benchbox/tpch OFF
Redshift redshift True True
ConfigurationError Redshift configuration is incomplete. Missing: host (or REDSHIFT_HOST), username (or REDSHIFT_USER), password (or REDSHIFT_PASSWORD)
ValueError Invalid COMPUPDATE value: 'bogus'. Must be one of: OFF, ON, PRESET
ValueError Redshift requires S3 (s3://) staging location, got: gs://
```

#### Compatibility

- `benchbox.platforms.RedshiftAdapter` is the same class.
- The driver and helpers come with the `redshift` extra; the base `benchbox` install does not include them.
- `auto_vacuum` and `auto_analyze` default to true, so `configure_for_benchmark` runs `VACUUM` and `ANALYZE` on every table in the schema before the timed queries. Set both to `False` to skip that.

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

The values are stored as attributes of the same name (`RedshiftAdapter(host="h", username="u", password="p").force_recreate` is `False`).

### Methods and attributes

Each method is marked with how its description was checked. Calls that talk to Redshift or AWS need a cluster and a live connection; those are marked as taken from reading the code. The others were run offline, either directly or against a stub connection object that records the SQL the adapter sends and returns prepared rows.

#### Construction and configuration

<span id="benchbox.platforms.redshift.RedshiftAdapter.__init__"></span>
**`__init__(**config)`**: Creates the adapter from keyword arguments. See Parameters above. It checks that a Redshift driver (`redshift-connector`, else `psycopg`) and the shared helper packages are importable, validates the settings, works out from the host name whether the endpoint is serverless or provisioned, and opens no connection. *Checked offline.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.from_config"></span>
**`from_config(config: dict[str, Any])`** (class method): Builds an adapter from a unified configuration dictionary and returns it. `benchmark` and `scale_factor` are required (a missing key raises `KeyError`). `database` is used when the configuration has a non-empty one; otherwise it is generated as `<benchmark>_sf<token>_<tuning>`, for example `tpch_sf001_notuning_noconstraints`. These keys pass through when present: `host`, `port`, `username`, `password`, `schema`, `iam_role`, `s3_bucket`, `s3_prefix`, `staging_root`, `aws_access_key_id`, `aws_secret_access_key`, `aws_session_token`, `aws_region`, `cluster_identifier`, `admin_database`, `connect_timeout`, `statement_timeout`, `sslmode`, `ssl_enabled`, `ssl_insecure`, `sslrootcert`, `wlm_query_slot_count`, `wlm_query_queue_name`, `wlm_config`, `compupdate`, `auto_vacuum`, `auto_analyze`, `disable_result_cache`, `strict_validation` and the tuning keys. Other keys are dropped, including `force` and `force_recreate`. *Checked offline.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.add_cli_arguments"></span>
**`add_cli_arguments(parser) -> None`** (static method): Adds a `Redshift Arguments` group to an `argparse.ArgumentParser` and returns `None`: `--host`, `--port` (int, default `5439`), `--database` (default `dev`), `--username`, `--password`, `--iam-role`, `--s3-bucket` and `--s3-prefix` (default `benchbox-data`). *Checked offline.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.platform_name"></span>
**`platform_name`** (property): Always the string `'Redshift'`. *Checked offline.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.get_target_dialect"></span>
**`get_target_dialect() -> str`**: Returns `'redshift'`, the SQL dialect BenchBox translates queries into. *Checked offline.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.get_platform_info"></span>
**`get_platform_info(connection: Any = None) -> dict[str, Any]`**: Returns a `dict` describing the platform. Without a connection it holds `platform_type` (`'redshift'`), `platform_name`, `connection_mode` (`'remote'`), `cloud_provider` (`'AWS'`), `host`, `port`, `configuration` (`database`, `schema`, `region`, `s3_bucket`, `s3_prefix`, `staging_root`, `iam_role`, `iam_role_configured`, `cluster_identifier`, `compupdate`, `result_cache_enabled`, `wlm_query_slot_count`, `wlm_query_queue_name`, `deployment_type`), `client_library_version` and `platform_version` (`None`). With a connection it also reads the Redshift version and workload-management details, and for a serverless or provisioned host name it may call the AWS API for workgroup or cluster details. *The no-connection form was checked offline; the connected form needs a live connection and was taken from reading the code.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.get_normalized_result_metadata"></span>
**`get_normalized_result_metadata(*, connection: Any | None = None, platform_info: Mapping[str, Any] | None = None) -> dict[str, Any]`**: Returns the platform metadata that BenchBox stores with results, as a `dict` with the entries `execution_environment`, `platform_deployment` (`deployment_type` `'managed_cloud'`), `platform_raw_config` (credentials shown as `<redacted>`), `platform_cloud`, `platform_compute` and `platform_storage`. Pass `connection` or a precomputed `platform_info` (keyword-only); without either it calls `get_platform_info()`. *Checked offline.*

#### Connection and database

<span id="benchbox.platforms.redshift.RedshiftAdapter.create_connection"></span>
**`create_connection(**connection_config) -> Any`**: Returns a Redshift connection (`redshift_connector`, or `psycopg` when that is not installed) with autocommit on. Existing-database handling comes first: with `force_recreate=True` the database is dropped, and otherwise it is validated and reused if it passes. If the target database does not exist, the adapter connects to `admin_database` and runs `CREATE DATABASE`. It then connects with TCP keep-alive, a connection timeout that depends on the cluster state (longer for serverless, paused or resuming clusters), `SET wlm_query_slot_count` when above 1, `SET statement_timeout` when above 0, `SET search_path` to `schema`, and `SELECT version()` to prove the connection works. Network, credential and permission failures raise here, as the driver's exception. *Needs a live connection; taken from reading the code.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.close_connection"></span>
**`close_connection(connection: Any) -> None`**: Closes the connection and returns `None`. `None` is accepted, and an error while closing is logged as a warning, not raised. *Checked offline against a stub connection.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.check_server_database_exists"></span>
**`check_server_database_exists(**connection_config) -> bool`**: Returns `True` when `pg_database` on the cluster lists a database named `database` (or the `database` keyword), checked through a connection to `admin_database`. Any error, including a failed login, returns `False`. *Needs a live connection; taken from reading the code.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.drop_database"></span>
**`drop_database(**connection_config) -> None`**: Terminates other sessions on the database and runs `DROP DATABASE`, then returns `None`. It does nothing when the database does not exist. If Redshift reports the database still has active connections (SQLSTATE 55006) it retries once on a fresh connection. Raises `RuntimeError` (`Failed to drop Redshift database ...`) on failure. *Needs a live connection; taken from reading the code.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.configure_for_benchmark"></span>
**`configure_for_benchmark(connection: Any, benchmark_type: str) -> None`**: Applies session settings and returns `None`. It runs `SET enable_result_cache_for_session` (`OFF` while `disable_result_cache` is true), `SET query_group TO 'benchbox'` and `SET statement_timeout TO '1800000'`, and for the benchmark types `olap`, `analytics`, `tpch` and `tpcds` also `enable_case_sensitive_identifier`, `datestyle` and `extra_float_digits`. When the result cache is disabled it validates the setting as `validate_session_cache_control` does. With `auto_vacuum` or `auto_analyze` true (the defaults) it then runs `VACUUM` and `ANALYZE` on every table in `schema`, on a separate connection so that a timeout cannot break the benchmark connection; a failure there is logged and the remaining tables are skipped. *Checked offline against a stub connection with `auto_vacuum=False` and `auto_analyze=False`; the maintenance connection needs a live cluster and was taken from reading the code.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.validate_session_cache_control"></span>
**`validate_session_cache_control(connection: Any) -> dict[str, Any]`**: Reads `current_setting('enable_result_cache_for_session')` and returns a `dict` with `validated` (the value matches what `disable_result_cache` asks for), `cache_disabled`, `settings` (for example `{'enable_result_cache_for_session': 'off'}`), `warnings` and `errors`. When the value does not match and `strict_validation` is true (the default) it raises `ConfigurationError` (`Redshift session cache control validation failed - benchmark results may be incorrect due to cached query results`); with `strict_validation=False` it returns `validated: False` instead. *Checked offline against a stub connection.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.create_schema"></span>
**`create_schema(benchmark, connection: Any) -> float`**: Creates `schema` when it is not `public`, sets the search path, and then, per benchmark table, runs `DROP TABLE IF EXISTS` and `CREATE TABLE`, returning the elapsed time in seconds (`float`). Table names are lower-cased, and statements that carry no `DISTSTYLE` or `SORTKEY` get `DISTSTYLE AUTO` and `SORTKEY AUTO` appended. Re-running it therefore replaces the tables. *Needs a live connection; taken from reading the code.*

#### Loading data into tables

<span id="benchbox.platforms.redshift.RedshiftAdapter.load_data"></span>
**`load_data(benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]`**: Loads the benchmark's data files and returns `(table_row_counts, seconds, None)`; `table_row_counts` maps lower-case table names to row counts. With `s3_bucket` set (or `staging_root`) and `boto3` installed, each file is uploaded to the bucket and loaded with `COPY` (several files through a manifest); otherwise the rows are inserted with batched `INSERT` statements, which is much slower. `COPY` uses `IAM_ROLE` when `iam_role` is set, the access keys otherwise, and no credentials clause if neither is set; delimited files pass `COMPUPDATE <compupdate>` and gzip or Zstandard files are detected from the file name. With `auto_analyze` true each `COPY`-loaded table is analysed. A table that fails to load does not raise: it is logged and counted as `0` rows. Loading does not truncate, so create the tables with `create_schema` first. *Needs a live connection; taken from reading the code.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.create_external_tables"></span>
**`create_external_tables(benchmark: Any, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]`**: Uploads Parquet files (or Delta and Iceberg directories) to S3 and registers Redshift Spectrum tables over them in the external schema `<schema>_external`, returning `(table_row_counts, seconds, None)`. It first calls `validate_external_table_requirements`. Iceberg tables are registered in the AWS Glue catalog. A table with no supported source raises `ValueError`. *Needs a live connection; taken from reading the code.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.supports_external_tables"></span>
**`supports_external_tables`** (class attribute): `True`. The adapter implements `create_external_tables`. *Checked offline.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.validate_external_table_requirements"></span>
**`validate_external_table_requirements() -> None`**: Returns `None` when both an S3 bucket (`s3_bucket` or an `s3://` `staging_root`) and `iam_role` are set. Otherwise raises `ValueError`: `Redshift external mode requires S3 staging (set --platform-option s3_bucket=<bucket> or provide --platform-option staging_root=s3://bucket/path).` for a missing bucket, or `Redshift external mode requires IAM role credentials for Spectrum (set --platform-option iam_role=<arn>).` for a missing role. *Checked offline.*

#### Statistics and maintenance

<span id="benchbox.platforms.redshift.RedshiftAdapter.analyze_table"></span>
**`analyze_table(connection: Any, table_name: str) -> None`**: Runs `ANALYZE <table>` with the lower-cased table name and returns `None`. A failure is raised, not swallowed, so that the statistics phase can record it as failed. *Checked offline against a stub connection.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.gather_statistics"></span>
**`gather_statistics(connection: Any, table_names: list[str]) -> tuple[str, int]`**: Statistics-phase hook that returns `(attribution, tables_analysed)`. With `auto_analyze` true (the default) it returns `('auto-on-load', 0)` and runs nothing, because `load_data` already analysed the tables. With `auto_analyze` false it runs `ANALYZE` per table and returns `('explicit', <number of tables>)`. *Checked offline against a stub connection.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.vacuum_table"></span>
**`vacuum_table(connection: Any, table_name: str) -> None`**: Runs `VACUUM <table>` with the lower-cased table name and returns `None`. A failure is logged as a warning and not raised. *Checked offline against a stub connection.*

#### Query execution and plans

<span id="benchbox.platforms.redshift.RedshiftAdapter.execute_query"></span>
**`execute_query(connection: Any, query: str, query_id: str, benchmark_type: str | None = None, scale_factor: float | None = None, validate_row_count: bool = True, stream_id: int | None = None) -> dict[str, Any]`**: Runs one query and returns a result `dict`; it does not raise for SQL errors. On success `status` is `'SUCCESS'` with `query_id`, `execution_time_seconds`, `rows_returned`, `first_row`, `translated_query` (`None`), `query_statistics` and `resource_usage` (the measured time plus Redshift system-table figures when they can be read). On an error `status` is `'FAILED'` with `error` and `error_type`. With `capture_plans` set it adds `query_plan` and `plan_fingerprint`. *Checked offline against a stub connection.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.get_query_plan"></span>
**`get_query_plan(connection: Any, query: str) -> str | None`**: Returns the plan as the lines of `EXPLAIN <query>` joined by newlines, or `None` if the statement fails or returns nothing. *Checked offline against a stub connection.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.get_query_plan_parser"></span>
**`get_query_plan_parser()`**: Returns a `RedshiftQueryPlanParser` (from `benchbox.core.query_plans.parsers.redshift`). *Checked offline.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.plan_capture_phase_eligible"></span>
**`plan_capture_phase_eligible`** (class attribute): `True`. Query plans for Redshift are captured in a separate pass after the timed run, not inline with the timed queries. *Checked offline.*

#### Tuning

<span id="benchbox.platforms.redshift.RedshiftAdapter.generate_tuning_clause"></span>
**`generate_tuning_clause(table_tuning) -> str`**: Returns the clauses to append to `CREATE TABLE`, or `''` when there is no tuning. A distribution column gives `DISTSTYLE KEY DISTKEY (<column>)` (first column by `order`); without one the clause is `DISTSTYLE EVEN`. Sorting columns add `SORTKEY (c1, c2, ...)`, a compound sort key. Partitioning and clustering add nothing. For example, one distribution and one sorting column give `DISTSTYLE KEY DISTKEY (k) SORTKEY (a)`. *Checked offline.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.apply_table_tunings"></span>
**`apply_table_tunings(table_tuning, connection: Any) -> None`**: Compares a table's distribution and sort keys with the request and returns `None`. It reads `pg_table_def` for the table, warns when the keys differ (Redshift needs the table recreated to change them), and then runs `ANALYZE <table>` and, with `auto_vacuum` true, `VACUUM <table>`. It does nothing for an empty tuning. Raises `ValueError` (`Failed to apply tunings to Redshift table <name>: ...`) on an unexpected failure. *Checked offline against a stub connection.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.apply_unified_tuning"></span>
**`apply_unified_tuning(unified_config: UnifiedTuningConfiguration, connection: Any) -> None`**: Applies a `UnifiedTuningConfiguration` and returns `None`: `apply_constraint_configuration`, then `apply_platform_optimizations` when present, then `apply_table_tunings` for each table. It does nothing for an empty configuration. *Checked offline against a stub connection.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.apply_platform_optimizations"></span>
**`apply_platform_optimizations(platform_config: PlatformOptimizationConfiguration, connection: Any) -> None`**: Logs that the optimisations are stored for session and workload management and returns `None`. It changes nothing in Redshift, and does nothing for `None`. *Checked offline against a stub connection.*

<span id="benchbox.platforms.redshift.RedshiftAdapter.apply_constraint_configuration"></span>
**`apply_constraint_configuration(primary_key_config: PrimaryKeyConfiguration, foreign_key_config: ForeignKeyConfiguration, connection: Any) -> None`**: Logs that primary-key or foreign-key constraints are enabled (informational only in Redshift) and returns `None`. It runs no SQL. *Checked offline against a stub connection.*

#### Capabilities

<span id="benchbox.platforms.redshift.RedshiftAdapter.driver_isolation_capability"></span>
**`driver_isolation_capability`** (class attribute): `DriverIsolationCapability.FEASIBLE_CLIENT_ONLY` (from `benchbox.platforms.base`): a requested driver version can run in an isolated runtime, but the Redshift service itself cannot be versioned. *Checked offline.*

## Configuration Examples

### IAM Role Authentication (Recommended)

The commands below create an IAM role with S3 read permissions, attach the S3 read policy to it, and associate the role with the cluster.

```bash
aws iam create-role --role-name RedshiftCopyRole \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "redshift.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }'

aws iam attach-role-policy --role-name RedshiftCopyRole \
    --policy-arn arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess

aws redshift modify-cluster-iam-roles \
    --cluster-identifier my-cluster \
    --add-iam-roles arn:aws:iam::123456789:role/RedshiftCopyRole
```

```python
adapter = RedshiftAdapter(
    host="my-cluster.123456.us-east-1.redshift.amazonaws.com",
    username="admin",
    password="password",
    s3_bucket="my-data-bucket",
    iam_role="arn:aws:iam::123456789:role/RedshiftCopyRole"
)
```

### Access Key Authentication

```python
adapter = RedshiftAdapter(
    host="my-cluster.123456.us-east-1.redshift.amazonaws.com",
    username="admin",
    password="password",
    s3_bucket="my-data-bucket",
    aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
    aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    aws_region="us-east-1"
)
```

### Workload Management (WLM)

```python
adapter = RedshiftAdapter(
    host="my-cluster.123456.us-east-1.redshift.amazonaws.com",
    username="admin",
    password="password",
    wlm_query_slot_count=3
)
```

Using multiple query slots gives large queries more resources. This example uses 3 slots.

## Data Loading

### Via S3 COPY (Recommended)

The data is generated locally. `load_data` automatically uploads it to S3 and then loads it with COPY.

```python
from benchbox.platforms.redshift import RedshiftAdapter
from benchbox.tpch import TPCH
from pathlib import Path

adapter = RedshiftAdapter(
    host="my-cluster.123456.us-east-1.redshift.amazonaws.com",
    username="admin",
    password="password",
    database="benchbox",
    s3_bucket="my-redshift-staging",
    s3_prefix="benchbox/tpch",
    iam_role="arn:aws:iam::123456789:role/RedshiftCopyRole"
)

data_dir = Path("./tpch_data")
benchmark = TPCH(scale_factor=1.0, output_dir=data_dir)
benchmark.generate_data()

conn = adapter.create_connection()
adapter.create_schema(benchmark, conn)
table_stats, load_time, _ = adapter.load_data(benchmark, conn, data_dir)

print(f"Loaded {sum(table_stats.values()):,} rows in {load_time:.2f}s")
```

### Direct Loading (Small Datasets)

For small datasets (under 100 MB), skip S3. No `s3_bucket` is specified here, so the adapter loads with direct INSERT statements.

```python
adapter = RedshiftAdapter(
    host="my-cluster.123456.us-east-1.redshift.amazonaws.com",
    username="admin",
    password="password"
)
```

## Advanced Features

### Distribution Keys

This creates a table with a distribution key.

```python
cursor.execute("""
    CREATE TABLE orders (
        o_orderkey BIGINT,
        o_custkey BIGINT,
        o_orderstatus CHAR(1),
        o_totalprice DECIMAL(15,2),
        o_orderdate DATE
    )
    DISTSTYLE KEY
    DISTKEY (o_custkey)
    SORTKEY (o_orderdate)
""")
```

### Sort Keys

Illustrative SQL fragments; supply complete table definitions before execution.

```sql
CREATE TABLE lineitem (...)
SORTKEY (l_shipdate, l_orderkey)

CREATE TABLE lineitem (...)
INTERLEAVED SORTKEY (l_shipdate, l_orderkey, l_partkey)
```

The first table uses a compound sort key, which is the most common choice. The second uses an interleaved sort key, which suits queries with multiple filters.

### Compression

`compupdate` sets the COPY compression analysis: `PRESET` (the default) applies encodings from the column types without sampling, `ON` samples the data, and `OFF` disables it. The query below then checks the compression encoding of each column.

```python
adapter = RedshiftAdapter(
    host="my-cluster...",
    compupdate="PRESET"
)

cursor.execute("""
    SELECT
        "column",
        type,
        encoding
    FROM pg_table_def
    WHERE tablename = 'lineitem'
""")
```

### Vacuum and Analyze

```python
adapter.vacuum_table(conn, "lineitem")
adapter.analyze_table(conn, "lineitem")

adapter = RedshiftAdapter(
    auto_vacuum=True,
    auto_analyze=True
)
```

The first two calls run maintenance manually. The adapter settings run it automatically.

## Best Practices

### Distribution Strategy

1. **Choose appropriate DISTSTYLE**:

   ```sql
   CREATE TABLE region (...) DISTSTYLE EVEN

   CREATE TABLE orders (...) DISTSTYLE KEY DISTKEY (o_custkey)

   CREATE TABLE nation (...) DISTSTYLE ALL
   ```

   `EVEN` suits small tables with no joins. `KEY` suits large fact tables; distribute by the join key. `ALL` suits small dimension tables, which are broadcast to all nodes.

### Sort Keys

1. **Use compound sort keys** for range/equality filters:

   ```sql
   SORTKEY (l_shipdate, l_orderkey)
   ```

   This suits queries such as `WHERE l_shipdate BETWEEN ... AND l_orderkey = ...`.

2. **Use interleaved for multiple filter combinations**:

   ```sql
   INTERLEAVED SORTKEY (l_shipdate, l_orderkey, l_partkey)
   ```

   This suits varying filter combinations.

### Data Loading

1. **Use COPY from S3** for best performance
2. **Load compressed files** (GZIP recommended)
3. **Use manifest files** for multiple files
4. **Run ANALYZE after loading**

### Cost Optimization

1. **Use reserved instances** for predictable workloads
2. **Pause clusters** when not in use
3. **Use concurrency scaling** for burst workloads
4. **Monitor query performance** with system tables

## Common Issues

### Connection Timeout

**Problem**: Cannot connect to cluster

**Solutions**: check the cluster status, verify that the security group allows inbound traffic on port 5439, check VPC routing and the NAT gateway, and test connectivity:

```bash
aws redshift describe-clusters --cluster-identifier my-cluster

psql -h my-cluster.123456.us-east-1.redshift.amazonaws.com \
     -U admin -d dev -p 5439
```

### S3 COPY Errors

**Problem**: COPY command fails

**Solutions**: verify the IAM role permissions (the role needs `s3:GetObject` and `s3:ListBucket`), check that the S3 bucket region matches the cluster region, and view the error details:

```python
cursor.execute("""
    SELECT * FROM stl_load_errors
    ORDER BY starttime DESC
    LIMIT 10
""")
```

### Slow Query Performance

**Problem**: Queries slower than expected

**Solutions**: check the query execution plan, verify the distribution keys, check sort key usage, and run VACUUM and ANALYZE:

```python
plan = adapter.get_query_plan(conn, query)

cursor.execute("""
    SELECT
        TRIM(t.name) AS table,
        TRIM(c.name) AS column,
        c.distkey
    FROM stv_tbl_perm t
    JOIN pg_attribute a ON a.attrelid = t.id
    JOIN pg_class c ON c.oid = t.id
    WHERE c.distkey = TRUE
""")

cursor.execute("""
    SELECT * FROM svv_table_info
    WHERE "table" = 'lineitem'
""")

adapter.vacuum_table(conn, "lineitem")
adapter.analyze_table(conn, "lineitem")
```

## See Also

### Platform Documentation

- {doc}`/platforms/platform-selection-guide` - Choosing Redshift vs other platforms
- {doc}`/platforms/quick-reference` - Quick setup for all platforms
- {doc}`/platforms/comparison-matrix` - Feature comparison

### API Reference

- {doc}`snowflake` - Snowflake adapter
- {doc}`databricks` - Databricks adapter
- {doc}`bigquery` - BigQuery adapter
- {doc}`../base` - Base benchmark interface
- {doc}`../index` - Python API overview

### External Resources

- [Redshift Documentation](https://docs.aws.amazon.com/redshift/) - Official Redshift docs
- [Best Practices](https://docs.aws.amazon.com/redshift/latest/dg/best-practices.html) - Performance optimization
- [Distribution Styles](https://docs.aws.amazon.com/redshift/latest/dg/c_choosing_dist_sort.html) - Distribution guidance
- [COPY Command](https://docs.aws.amazon.com/redshift/latest/dg/r_COPY.html) - Data loading reference
