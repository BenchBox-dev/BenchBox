<!-- markdownlint-disable MD024 -->

# BigQuery Platform Adapter

```{tags} reference, python-api, bigquery
```

The BigQuery adapter provides Google Cloud's serverless data warehouse execution for analytical benchmarks with built-in cost optimization.

## Overview

Google BigQuery is a fully managed, serverless data warehouse. The adapter needs the `bigquery` extra (`pip install "benchbox[bigquery]"`), a Google Cloud project and credentials. It provides:

- **Serverless architecture** - No infrastructure management required
- **Petabyte-scale support** - Supports large datasets
- **Pay-per-query pricing** - Usage-based cost model
- **Built-in ML** - SQL-based machine learning capabilities
- **Query optimization** - Automatic query optimization and caching

Common use cases:

- Cloud-native analytics workloads on Google Cloud
- Large-scale benchmarking (multi-TB to PB scale)
- Testing with pay-per-query pricing and budget controls
- Multi-region deployments
- Integration with Google Cloud ecosystem

## Quick Start

### Basic Configuration

```python
from benchbox.tpch import TPCH
from benchbox.platforms.bigquery import BigQueryAdapter

# Connect to BigQuery
adapter = BigQueryAdapter(
    project_id="my-project-id",
    dataset_id="benchbox_tpch",
    location="US",
    credentials_path="/path/to/service-account.json"
)

# Generate data, then run the benchmark
benchmark = TPCH(scale_factor=1.0)
benchmark.generate_data()
results = benchmark.run_with_platform(adapter)
```

`run_with_platform` does not generate data. Without `generate_data()` the tables are created empty.

### Auto-Detection

```python
# Auto-detect from Application Default Credentials
from benchbox.platforms.bigquery import BigQueryAdapter

adapter = BigQueryAdapter.from_config({
    "benchmark": "tpch",
    "scale_factor": 1.0,
    # project_id taken from Application Default Credentials when it is not given
})
```

`from_config` generates the dataset name (`tpch_sf1_notuning_noconstraints` here) and ignores any `dataset_id` in the configuration. The constructor itself never auto-detects the project: `BigQueryAdapter(...)` without `project_id` raises `ConfigurationError`.

## API Reference

### BigQueryAdapter Class

<span id="benchbox.platforms.bigquery.BigQueryAdapter"></span>

`benchbox.platforms.bigquery.BigQueryAdapter` runs BenchBox benchmarks on Google BigQuery, optionally staging data through Cloud Storage.

**Import:** `from benchbox.platforms.bigquery import BigQueryAdapter` · **Extras:** `bigquery`

#### Parameters

All parameters are keyword arguments (the signature is `(**config)`).

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `project_id` | `str` | required | Google Cloud project that runs and bills the queries. An empty value counts as missing. |
| `dataset_id` | `str` | `"benchbox"` | Dataset that holds the tables. |
| `location` | `str` | `"US"` | Location of the client and of a dataset that BenchBox creates (`"EU"`, `"asia-northeast1"`, ...). It also selects the price used for cost estimates. |
| `credentials_path` | `str` or `None` | `None` | Service-account key file. `None` uses Application Default Credentials. |
| `staging_root` | `str` or `None` | `None` | Cloud Storage staging location `gs://bucket/prefix`. It sets `storage_bucket` and `storage_prefix` (the prefix is `benchbox-data` when the URL has no path). Any other scheme raises `ValueError`. |
| `storage_bucket` | `str` or `None` | `None` | Bucket for staging data files. Used when `staging_root` is not given. |
| `storage_prefix` | `str` | `"benchbox-data"` | Object-name prefix inside the bucket. |
| `job_priority` | `str` | `"INTERACTIVE"` | `"INTERACTIVE"` or `"BATCH"`. Not checked at construction; an unknown name behaves as `"INTERACTIVE"` when the connection is configured. |
| `query_cache` | `bool` | `False` | Let BigQuery serve queries from its result cache. |
| `disable_result_cache` | `bool` | none | The opposite of `query_cache`, used when `query_cache` is not given. |
| `dry_run` | `bool` | `False` | Estimate queries instead of running them. |
| `maximum_bytes_billed` | `int` or `None` | `None` | Fail any query that would bill more than this many bytes. |
| `biglake_connection` | `str` or `None` | `None` | BigLake connection that Delta and Iceberg external tables need. |
| `partitioning_field` | `str` or `None` | `None` | Column for `PARTITION BY DATE(...)`. Added to every table that `create_schema` creates. |
| `clustering_fields` | `list[str]` | `[]` | Columns for `CLUSTER BY`, added to every table that `create_schema` creates. |
| `force_recreate` | `bool` | `False` | Drop an existing dataset when a connection is created. |

The adapter also accepts the keys every BenchBox adapter takes: see [Constructor Parameters](#constructor-parameters). Keys it does not recognise are accepted and ignored. The constructor reads no environment variables: `BIGQUERY_PROJECT` and `GOOGLE_CLOUD_PROJECT` are not consulted, so pass `project_id` yourself.

#### Returns

A `BigQueryAdapter`. Construction makes no network call; call `create_connection()` to get a client.

#### Raises

- `ImportError`: the Google Cloud client packages are not installed. The message lists `google-cloud-bigquery`, `google-cloud-storage` and `cloudpathlib` and the install command `pip install 'benchbox[bigquery]'`. This check runs before the `project_id` check.
- `ConfigurationError` (from `benchbox.core.exceptions`): `project_id` is missing or empty (`BigQuery configuration requires project_id.`).
- `ValueError`: `staging_root` is not a `gs://` location (`BigQuery requires GCS (gs://) staging location, got: s3://`).

Credentials are not checked here. They fail in `create_connection()`.

#### Example

```python
from benchbox.platforms.bigquery import BigQueryAdapter

adapter = BigQueryAdapter(project_id="my-project", location="EU", staging_root="gs://my-bucket/staging/tpch")
print(adapter.dataset_id, adapter.storage_bucket, adapter.storage_prefix, adapter.query_cache, adapter.job_priority)

for kwargs in ({}, {"project_id": "p", "staging_root": "s3://bucket/x"}):
    try:
        BigQueryAdapter(**kwargs)
    except Exception as exc:
        print(type(exc).__name__, str(exc).splitlines()[0])

configured = BigQueryAdapter.from_config({"benchmark": "tpch", "scale_factor": 0.01, "project_id": "my-project"})
print(configured.dataset_id)
```

Output on 0.4.1 with `google-cloud-bigquery` 3.46.1, run without a network connection:

```text
benchbox my-bucket staging/tpch False INTERACTIVE
ConfigurationError BigQuery configuration requires project_id.
ValueError BigQuery requires GCS (gs://) staging location, got: s3://
tpch_sf001_notuning_noconstraints
```

#### Compatibility

- `benchbox.platforms.BigQueryAdapter` is the same class.
- `query_cache` defaults to `False`, so that timings are not served from BigQuery's result cache.
- The Google Cloud packages come with the `bigquery` extra; the base `benchbox` install does not include them.

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

The values are stored as attributes of the same name (`BigQueryAdapter(project_id="p").force_recreate` is `False`). BigQuery also stores `dry_run` as given by its own parameter (see above).

### Methods and attributes

#### Construction and configuration

<span id="benchbox.platforms.bigquery.BigQueryAdapter.__init__"></span>
**`__init__(**config)`**: Creates the adapter from keyword arguments. See Parameters above. It checks that the BigQuery client packages are importable and that `project_id` is set, and opens no connection.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.from_config"></span>
**`from_config(config: dict[str, Any])`** (class method): Builds an adapter from a unified configuration dictionary and returns it. `benchmark` and `scale_factor` are required (a missing key raises `KeyError`). `dataset_id` is always generated from them as `<benchmark>_sf<token>_<tuning>`, for example `tpch_sf001_notuning_noconstraints`; a `dataset_id` in the configuration is ignored. `project_id` is used when given; otherwise the adapter asks Google Application Default Credentials for a project (this contacts Google's credential machinery) and leaves it unset if none is found, which then fails in the constructor. These keys pass through when present: `location`, `credentials_path`, `storage_bucket`, `storage_prefix`, `staging_root`, `job_priority`, `biglake_connection`, `query_cache`, `disable_result_cache`, `maximum_bytes_billed`, the tuning keys and the verbosity keys. Other keys are dropped, including `force` and `force_recreate`.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.add_cli_arguments"></span>
**`add_cli_arguments(parser: argparse.ArgumentParser) -> None`** (static method): Adds a `BigQuery Arguments` group to an `argparse.ArgumentParser` and returns `None`: `--project-id`, `--dataset-id`, `--location` (default `US`), `--credentials-path` and `--storage-bucket`; all except `--location` default to `None`.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.platform_name"></span>
**`platform_name`** (property): Always the string `'BigQuery'`.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.get_target_dialect"></span>
**`get_target_dialect() -> str`**: Returns `'bigquery'`, the SQL dialect BenchBox translates queries into.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.get_platform_info"></span>
**`get_platform_info(connection: Any = None) -> dict[str, Any]`**: Returns a `dict` describing the platform. Without a connection it holds `platform_type` (`'bigquery'`), `platform_name`, `connection_mode` (`'remote'`), `cloud_provider` (`'GCP'`), `configuration` (`project_id`, `dataset_id`, `location`, `storage_bucket`, `storage_prefix`, `staging_root`, `biglake_connection`, `job_timeout`, `job_priority`, `query_cache_enabled`, `maximum_bytes_billed`), `client_library_version` (the installed `google-cloud-bigquery` version) and `platform_version` (`None`). With a connection it also reads the dataset and, best effort, the project's reservation information from `INFORMATION_SCHEMA`, and adds that as `compute_configuration`; failures there are tolerated.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.get_normalized_result_metadata"></span>
**`get_normalized_result_metadata(*, connection: Any | None = None, platform_info: Mapping[str, Any] | None = None) -> dict[str, Any]`**: Returns the platform metadata that BenchBox stores with results, as a `dict` with the entries `execution_environment`, `platform_deployment` (`deployment_type` `'serverless'`), `platform_raw_config`, `platform_cloud`, `platform_compute`, `platform_raw_metadata` and `platform_storage`. Pass `connection` or a precomputed `platform_info` (keyword-only); without either it calls `get_platform_info()`. Without a connection the compute entries are marked `collection_status: 'partial'`.

#### Connection and datasets

<span id="benchbox.platforms.bigquery.BigQueryAdapter.create_connection"></span>
**`create_connection(**connection_config) -> Any`**: Returns a `google.cloud.bigquery.Client` for `project_id` and `location`. Existing-dataset handling comes first: with `force_recreate=True` the dataset is dropped, and otherwise it is validated and kept if it passes (`database_was_reused` becomes `True`, and empty tables left by a failed earlier load are removed). Credentials come from the service-account file at `credentials_path`, or Application Default Credentials when it is `None`. The client runs `SELECT 1` to prove the connection works, so bad credentials or a wrong project raise here, as the underlying Google exception.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.close_connection"></span>
**`close_connection(connection: Any) -> None`**: Closes the client and returns `None`. `None` is accepted. Errors about credentials, tokens or authentication during cleanup are suppressed; other errors are logged as warnings, not raised.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.check_server_database_exists"></span>
**`check_server_database_exists(**connection_config) -> bool`**: Returns `True` when the project has a dataset named `dataset_id` (or the `dataset` keyword), by listing the project's datasets. Any error, including missing credentials, returns `False`.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.drop_database"></span>
**`drop_database(**connection_config) -> None`**: Deletes the dataset and every table in it (`delete_contents=True`; a missing dataset is not an error) and returns `None`. Raises `RuntimeError` (`Failed to drop BigQuery dataset ...`) on failure.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.configure_for_benchmark"></span>
**`configure_for_benchmark(connection: Any, benchmark_type: str) -> None`**: Stores default query-job settings on the connection (as `connection._default_job_config`) and returns `None`. The settings are: priority from `job_priority` (an unknown name falls back to `INTERACTIVE`), `use_query_cache` from `query_cache`, `dry_run`, `maximum_bytes_billed` when set, the default dataset `<project_id>.<dataset_id>`, and, for the benchmark types `olap`, `analytics`, `tpch` and `tpcds`, standard SQL with unflattened results. `execute_query` runs queries with these settings.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.create_schema"></span>
**`create_schema(benchmark, connection: Any) -> float`**: Creates the dataset if it does not exist (with `location`) and then runs one `CREATE OR REPLACE TABLE` per benchmark table, returning the elapsed time in seconds (`float`). Table names are upper-cased (`LINEITEM`). `partitioning_field` and `clustering_fields`, when set, are added to every table whose statement has no `PARTITION BY` or `CLUSTER BY`, so every table must contain those columns.

#### Loading data into tables

<span id="benchbox.platforms.bigquery.BigQueryAdapter.load_data"></span>
**`load_data(benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]`**: Loads the benchmark's data files into the tables and returns `(table_row_counts, seconds, per_table_timings)`; `table_row_counts` maps table names to row counts and `per_table_timings` maps each table to its timing. Files go through Cloud Storage when `storage_bucket` (or `staging_root`) is set, and are loaded directly from local files otherwise. Parquet and delimited text (`.tbl`, `.csv`) are supported. Zstandard-compressed files are rejected with a `ValueError` that tells you to regenerate the data with gzip or no compression. The first file of a table replaces its content and later files append.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.create_external_tables"></span>
**`create_external_tables(benchmark: Any, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]`**: Uploads Parquet files (or Delta and Iceberg directories) to the Cloud Storage bucket and registers BigQuery external tables over them, returning `(table_row_counts, seconds, None)`. It first calls `validate_external_table_requirements`, so it raises `ValueError` when no bucket is configured. Delta and Iceberg sources also need `biglake_connection`. A table with no supported source raises `ValueError`.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.supports_external_tables"></span>
**`supports_external_tables`** (class attribute): `True`. The adapter implements `create_external_tables`.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.validate_external_table_requirements"></span>
**`validate_external_table_requirements() -> None`**: Returns `None` when a Cloud Storage bucket is configured (`storage_bucket`, or `staging_root` as `gs://...`). Otherwise raises `ValueError` with the message `BigQuery external mode requires a GCS bucket (set --platform-option storage_bucket=<bucket> or provide --platform-option staging_root=gs://bucket/path).`

<span id="benchbox.platforms.bigquery.BigQueryAdapter.get_table_row_count"></span>
**`get_table_row_count(connection: Any, table: str) -> int`**: Returns the number of rows in a table, as an `int`, by running `SELECT COUNT(*)` against `<project_id>.<dataset_id>.<TABLE>` (the upper-case name is tried first, then the name as given). Returns `0` when the count cannot be determined, for example when the table does not exist.

#### Query execution and plans

<span id="benchbox.platforms.bigquery.BigQueryAdapter.execute_query"></span>
**`execute_query(connection: Any, query: str, query_id: str, benchmark_type: str | None = None, scale_factor: float | None = None, validate_row_count: bool = True, stream_id: int | None = None) -> dict[str, Any]`**: Runs one query and returns a result `dict`; it does not raise for SQL errors. Unquoted table names are rewritten to `` `project.dataset.TABLE` ``, divisions are routed through `SAFE_DIVIDE`, and TPC-DI queries get extra rewrites. On success `status` is `'SUCCESS'` with `query_id`, `execution_time_seconds`, `rows_returned`, `first_row`, `translated_query` (`None` when unchanged), `job_id`, and `job_statistics` (`bytes_processed`, `bytes_billed`, `slot_ms`, `creation_time`, `start_time`, `end_time`; the same dict is under `resource_usage`). With `capture_plans` set it adds `query_plan` and `plan_fingerprint` from the finished job. On an error `status` is `'FAILED'` with `error` and `error_type`. With `dry_run` set the query is only estimated, not run.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.get_query_plan"></span>
**`get_query_plan(connection: Any, query: str) -> dict[str, Any] | None`**: Returns a `dict` with the dry-run estimate for the query, or `None` on any failure: `bytes_processed` (`int`), `estimated_cost` (US dollars at the on-demand price for `location`, `bytes_processed / 1024**4 * price per TiB`; `None` if no price is known) and `pricing_fallback` (`True` when a default price was used). BigQuery has no `EXPLAIN` text, so this is a cost estimate and not a plan tree. For 2 TiB in `US` the estimate is `12.5` (6.25 dollars per TiB). A dry-run job does not run the query.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.get_query_plan_parser"></span>
**`get_query_plan_parser()`**: Returns a `BigQueryQueryPlanParser` (from `benchbox.core.query_plans.parsers.bigquery`).

<span id="benchbox.platforms.bigquery.BigQueryAdapter.plan_capture_phase_eligible"></span>
**`plan_capture_phase_eligible`** (class attribute): `False`. BigQuery has no `EXPLAIN` statement and a second run would cost money, so plans are captured from the finished query job (`job.query_plan`) during `execute_query`, not in a separate pass.

#### Tuning

<span id="benchbox.platforms.bigquery.BigQueryAdapter.generate_tuning_clause"></span>
**`generate_tuning_clause(table_tuning) -> str`**: Returns the clauses to append to `CREATE TABLE`, or `''` when there is no tuning. A partitioning column of `DATE` type gives `PARTITION BY <column>`, a `TIMESTAMP` or `DATETIME` column gives `PARTITION BY DATE(<column>)`, an integer column gives `PARTITION BY RANGE_BUCKET(<column>, GENERATE_ARRAY(0, 1000000, 10000))`, and any other type gives `PARTITION BY DATE(<column>)`; only the first partitioning column (by `order`) is used. Clustering columns give `CLUSTER BY` with at most the first four. Sorting and distribution add nothing. Example: partition on a `DATE` column plus one clustering column gives `PARTITION BY d CLUSTER BY c`.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.apply_table_tunings"></span>
**`apply_table_tunings(table_tuning, connection: Any) -> None`**: Compares a table's tuning with the existing table and returns `None`. It does not change the table: it logs the partitioning and clustering the table has, warns when they differ from the request, and warns that distribution is unsupported. BigQuery partitioning and clustering are set when the table is created (see `generate_tuning_clause`). It does nothing for an empty tuning. Raises `ValueError` (`Failed to apply tunings to BigQuery table <name>: ...`) if reading the table fails.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.apply_unified_tuning"></span>
**`apply_unified_tuning(unified_config: UnifiedTuningConfiguration, connection: Any) -> None`**: Applies a `UnifiedTuningConfiguration` and returns `None`: it calls `apply_constraint_configuration`, then `apply_platform_optimizations` when the configuration has platform optimisations, then `apply_table_tunings` for each table. It does nothing for an empty configuration.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.apply_platform_optimizations"></span>
**`apply_platform_optimizations(platform_config: PlatformOptimizationConfiguration, connection: Any) -> None`**: Logs that the optimisations are stored for query execution and returns `None`. It changes nothing in BigQuery, and does nothing for `None`.

<span id="benchbox.platforms.bigquery.BigQueryAdapter.apply_constraint_configuration"></span>
**`apply_constraint_configuration(primary_key_config: PrimaryKeyConfiguration, foreign_key_config: ForeignKeyConfiguration, connection: Any) -> None`**: Logs that primary-key or foreign-key constraints are enabled and returns `None`. It runs no SQL.

#### Capabilities

<span id="benchbox.platforms.bigquery.BigQueryAdapter.driver_isolation_capability"></span>
**`driver_isolation_capability`** (class attribute): `DriverIsolationCapability.FEASIBLE_CLIENT_ONLY` (from `benchbox.platforms.base`): a requested client-library version can run in an isolated runtime, but the BigQuery service itself cannot be versioned.

#### Added in 0.4.2

<span id="benchbox.platforms.bigquery.BigQueryAdapter.preprocess_operation_sql"></span>
**`preprocess_operation_sql(query_id: str, operation: Any) -> str | None`**: Returns the write SQL of a Write Primitives operation rewritten for BigQuery, or `None` when the operation's `bigquery` override skips it. It starts from the `bigquery` override when one exists, otherwise from the default write SQL, and then: turns `CAST(x AS VARCHAR)` into `CAST(x AS STRING)`, turns `INTERVAL 'N' UNIT` into `INTERVAL N UNIT`, types bare decimal literals as `NUMERIC`, adds `WHERE true` to an `UPDATE` or `DELETE` that has no `WHERE`, and turns a trailing bare `WHEN NOT MATCHED ... THEN INSERT` into `INSERT ROW`.

## Configuration Examples

### Application Default Credentials

```bash
# Set up default credentials
gcloud auth application-default login
```

```python
# No credentials_path needed
adapter = BigQueryAdapter(
    project_id="my-project",
    dataset_id="benchbox_tpch"
)
```

### Service Account Authentication

```bash
# Create service account and download key
gcloud iam service-accounts create benchbox-runner
gcloud projects add-iam-policy-binding my-project \
    --member="serviceAccount:benchbox-runner@my-project.iam.gserviceaccount.com" \
    --role="roles/bigquery.admin"
gcloud iam service-accounts keys create key.json \
    --iam-account=benchbox-runner@my-project.iam.gserviceaccount.com
```

```python
adapter = BigQueryAdapter(
    project_id="my-project",
    dataset_id="benchbox_tpch",
    credentials_path="./key.json"
)
```

### GCS Integration for Data Loading

```python
# Efficient loading via Cloud Storage
adapter = BigQueryAdapter(
    project_id="my-project",
    dataset_id="benchbox_tpch",
    storage_bucket="my-benchmark-data",
    storage_prefix="tpch/sf1"
)

# Data is automatically uploaded to GCS then loaded to BigQuery
# Recommended for large datasets
```

### Cost Control Configuration

```python
# Set budget limits and use BATCH priority
adapter = BigQueryAdapter(
    project_id="my-project",
    dataset_id="benchbox_tpch",
    job_priority="BATCH",  # Queued execution
    query_cache=True,  # Allow BigQuery to serve cached results (default: False)
    maximum_bytes_billed=10 * 1024**3  # 10 GB limit per query
)
```

### Table Optimization

`partitioning_field` and `clustering_fields` are added to every table that `create_schema` builds, so each column must exist in all of them. A column such as `l_shipdate` is in `LINEITEM` only, and the other TPC-H tables would fail to create:

```python
# Every table the adapter creates gets this clause
adapter = BigQueryAdapter(
    project_id="my-project",
    dataset_id="benchbox_tpch",
    partitioning_field="created_date",   # must exist in every table
    clustering_fields=["id"]             # must exist in every table
)
```

For per-table partitioning and clustering use a tuning configuration; `generate_tuning_clause` renders it as BigQuery clauses (a `DATE` partitioning column gives `PARTITION BY l_shipdate`, clustering columns give `CLUSTER BY ...`, at most four).

## Authentication

### Application Default Credentials (Development)

```bash
# Log in with your Google account
gcloud auth application-default login

# Set default project
gcloud config set project my-project-id
```

```python
# Credentials come from Application Default Credentials;
# project_id is always required by the constructor
adapter = BigQueryAdapter(
    project_id="my-project",
    dataset_id="benchbox"
)
```

### Service Account (Production)

```bash
# Create service account with required roles
gcloud iam service-accounts create benchbox-sa

# Grant BigQuery permissions
gcloud projects add-iam-policy-binding my-project \
    --member="serviceAccount:benchbox-sa@my-project.iam.gserviceaccount.com" \
    --role="roles/bigquery.admin"

# Grant GCS permissions (if using cloud storage)
gcloud projects add-iam-policy-binding my-project \
    --member="serviceAccount:benchbox-sa@my-project.iam.gserviceaccount.com" \
    --role="roles/storage.objectAdmin"

# Download key
gcloud iam service-accounts keys create sa-key.json \
    --iam-account=benchbox-sa@my-project.iam.gserviceaccount.com
```

```python
# Use service account key
adapter = BigQueryAdapter(
    project_id="my-project",
    credentials_path="/secure/path/sa-key.json"
)
```

### Environment Variables

```bash
# Set credentials via environment variable
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/key.json"
export GOOGLE_CLOUD_PROJECT="my-project-id"
```

```python
# Credentials automatically loaded from environment
import os
adapter = BigQueryAdapter(
    project_id=os.environ["GOOGLE_CLOUD_PROJECT"],
    dataset_id="benchbox"
)
```

## Data Loading

### Via Cloud Storage (Recommended)

```python
from benchbox.platforms.bigquery import BigQueryAdapter
from benchbox.tpch import TPCH
from pathlib import Path

# Configure with GCS bucket
adapter = BigQueryAdapter(
    project_id="my-project",
    dataset_id="benchbox_tpch_sf10",
    storage_bucket="benchmark-data-bucket",
    storage_prefix="tpch/sf10"
)

# Generate data
data_dir = Path("./tpch_data")
benchmark = TPCH(scale_factor=10.0, output_dir=data_dir)
benchmark.generate_data()

# Create the dataset and tables, then load data (uploads to GCS first)
conn = adapter.create_connection()
adapter.create_schema(benchmark, conn)
table_stats, load_time, _ = adapter.load_data(benchmark, conn, data_dir)
```

### Direct Loading (Small Datasets)

```python
# For small datasets (< 1GB), skip GCS
adapter = BigQueryAdapter(
    project_id="my-project",
    dataset_id="benchbox_tpch_sf001"
    # No storage_bucket specified
)

# Direct loading from local files
conn = adapter.create_connection()
adapter.create_schema(benchmark, conn)
table_stats, load_time, _ = adapter.load_data(benchmark, conn, data_dir)
```

## Query Execution

### Basic Query Execution

```python
adapter = BigQueryAdapter(project_id="my-project", dataset_id="benchbox")
conn = adapter.create_connection()

# Execute SQL query
query = """
    SELECT
        l_returnflag,
        l_linestatus,
        sum(l_quantity) as sum_qty,
        count(*) as count_order
    FROM `my-project.benchbox.LINEITEM`
    WHERE l_shipdate <= '1998-09-01'
    GROUP BY l_returnflag, l_linestatus
    ORDER BY l_returnflag, l_linestatus
"""

query_job = conn.query(query)
results = list(query_job.result())

# Check query statistics
print(f"Bytes processed: {query_job.total_bytes_processed:,}")
print(f"Bytes billed: {query_job.total_bytes_billed:,}")
print(f"Slot milliseconds: {query_job.slot_millis:,}")
```

### Cost Estimation (Dry Run)

```python
from google.cloud import bigquery

# Estimate query cost before execution
adapter = BigQueryAdapter(project_id="my-project", dataset_id="benchbox")

# Get query plan without execution
plan = adapter.get_query_plan(conn, query)
print(f"Estimated bytes: {plan['bytes_processed']:,}")
print(f"Estimated cost: ${plan['estimated_cost']:.4f}")
```

### Query Plans and Optimization

```python
# Get query execution plan
job_config = bigquery.QueryJobConfig(dry_run=True)
query_job = conn.query(query, job_config=job_config)

print(f"This query will process {query_job.total_bytes_processed:,} bytes")

# On-demand rate varies by location; US/EU/Asia multi-region is $6.25/TiB.
# See benchbox/core/cost/pricing_data.yaml for all locations.
cost_per_tb = 6.25
estimated_cost = (query_job.total_bytes_processed / 1024**4) * cost_per_tb
print(f"Estimated cost: ${estimated_cost:.4f}")
```

## Advanced Features

### Partitioning

```python
# Create partitioned table
query = """
    CREATE OR REPLACE TABLE `my-project.benchbox.orders_partitioned`
    PARTITION BY DATE(o_orderdate)
    AS SELECT * FROM `my-project.benchbox.ORDERS`
"""
conn.query(query).result()

# Query with partition filter (reduces cost)
query = """
    SELECT COUNT(*) FROM `my-project.benchbox.orders_partitioned`
    WHERE DATE(o_orderdate) BETWEEN '1995-01-01' AND '1995-12-31'
"""
# Only scans data from 1995 partitions
```

### Clustering

```python
# Create clustered table (up to 4 columns)
query = """
    CREATE OR REPLACE TABLE `my-project.benchbox.lineitem_clustered`
    PARTITION BY DATE(l_shipdate)
    CLUSTER BY l_orderkey, l_partkey, l_suppkey
    AS SELECT * FROM `my-project.benchbox.LINEITEM`
"""
conn.query(query).result()

# Queries filtering on clustered columns are optimized
query = """
    SELECT * FROM `my-project.benchbox.lineitem_clustered`
    WHERE l_orderkey = 12345
    AND DATE(l_shipdate) = '1995-03-15'
"""
```

### Query Caching

```python
# Allow caching (the adapter default is False)
adapter = BigQueryAdapter(
    project_id="my-project",
    dataset_id="benchbox",
    query_cache=True
)
# The adapter applies query_cache to queries run through adapter.execute_query();
# conn.query() below uses BigQuery's own default, which allows caching

# First execution processes data
query = "SELECT COUNT(*) FROM `my-project.benchbox.LINEITEM`"
job1 = conn.query(query)
print(f"Bytes billed (first): {job1.total_bytes_billed:,}")

# Second execution uses cache (0 bytes billed)
job2 = conn.query(query)
print(f"Bytes billed (cached): {job2.total_bytes_billed:,}")  # 0
```

### Batch vs Interactive Priority

```python
from google.cloud import bigquery

# Interactive (default) - immediate execution
job_config_interactive = bigquery.QueryJobConfig(
    priority=bigquery.QueryPriority.INTERACTIVE
)

# Batch - queued execution
job_config_batch = bigquery.QueryJobConfig(
    priority=bigquery.QueryPriority.BATCH
)

query = "SELECT COUNT(*) FROM `my-project.benchbox.LINEITEM`"

# Use batch for non-time-sensitive queries
job = conn.query(query, job_config=job_config_batch)
job.result()  # May wait in queue
```

## Best Practices

### Cost Optimization

1. **Use partitioning** to reduce data scanned:

   ```python
   # Partition by date column
   adapter = BigQueryAdapter(
       project_id="my-project",
       partitioning_field="created_date"  # must exist in every table the adapter creates
   )
   ```

2. **Enable query caching**:

   ```python
   adapter = BigQueryAdapter(
       query_cache=True  # Reuse cached results (default: False)
   )
   ```

3. **Set billing limits**:

   ```python
   adapter = BigQueryAdapter(
       maximum_bytes_billed=10 * 1024**3  # 10 GB max
   )
   ```

4. **Use BATCH priority** for non-urgent queries:

   ```python
   adapter = BigQueryAdapter(
       job_priority="BATCH"  # Queued; starts when resources are available
   )
   ```

5. **Estimate costs** before execution:

   ```python
   plan = adapter.get_query_plan(conn, query)
   if plan["estimated_cost"] > 1.0:  # > $1
       print("Query too expensive, optimizing...")
   ```

### Data Loading Efficiency

1. **Use Cloud Storage** for large datasets:

   ```python
   adapter = BigQueryAdapter(
       storage_bucket="benchmark-data"  # Recommended for large datasets
   )
   ```

2. **Compress data files** with gzip (the adapter rejects Zstandard `.zst` files for BigQuery with a `ValueError`):

   ```bash
   # BigQuery supports gzip-compressed files
   gzip data/*.csv
   ```

3. **Use Parquet files** when the benchmark provides them; `load_data` loads Parquet as well as `.tbl` and `.csv`.

### Performance Optimization

1. **Cluster frequently filtered columns**:

   ```python
   adapter = BigQueryAdapter(
       project_id="my-project",
       clustering_fields=["id"]  # must exist in every table the adapter creates
   )
   ```

2. **Avoid SELECT \***:

   ```sql
   -- Bad: scans all columns
   SELECT * FROM lineitem WHERE l_orderkey = 1

   -- Good: only scans needed columns
   SELECT l_orderkey, l_quantity FROM lineitem WHERE l_orderkey = 1
   ```

3. **Use materialized views** for repeated queries:

   ```sql
   CREATE MATERIALIZED VIEW benchbox.lineitem_summary AS
   SELECT
       l_orderkey,
       sum(l_quantity) as total_qty
   FROM benchbox.LINEITEM
   GROUP BY l_orderkey
   ```

## Common Issues

### Permission Denied

**Problem**: "Access Denied" errors

**Solutions**:

```bash
# 1. Check required permissions
gcloud projects get-iam-policy my-project

# 2. Grant BigQuery Admin role
gcloud projects add-iam-policy-binding my-project \
    --member="user:your-email@example.com" \
    --role="roles/bigquery.admin"

# 3. Grant Storage permissions (if using GCS)
gcloud projects add-iam-policy-binding my-project \
    --member="user:your-email@example.com" \
    --role="roles/storage.objectAdmin"
```

```python
# 4. Verify credentials in code
from google.cloud import bigquery

client = bigquery.Client(project="my-project")
print(f"Authenticated as: {client._credentials.service_account_email}")
```

### Dataset Not Found

**Problem**: "Dataset not found" error

**Solutions**:

```python
# 1. List available datasets
client = bigquery.Client(project="my-project")
datasets = list(client.list_datasets())
print("Datasets:", [d.dataset_id for d in datasets])

# 2. Create dataset if it doesn't exist
from google.cloud import bigquery

dataset_id = "benchbox"
dataset = bigquery.Dataset(f"my-project.{dataset_id}")
dataset.location = "US"
client.create_dataset(dataset, exists_ok=True)
```

### Quota Exceeded

**Problem**: "Quota exceeded" errors

**Solutions**:

```python
# 1. Check current quota usage
# Visit: https://console.cloud.google.com/iam-admin/quotas

# 2. Set maximum bytes billed
adapter = BigQueryAdapter(
    maximum_bytes_billed=100 * 1024**3  # 100 GB limit
)

# 3. Use BATCH priority (queued execution)
adapter = BigQueryAdapter(
    job_priority="BATCH"
)

# 4. Request quota increase
# Visit: https://console.cloud.google.com/iam-admin/quotas
```

### Slow Query Performance

**Problem**: Queries are slower than expected

**Solutions**:

```python
# 1. Check query execution details
query_job = conn.query(query)
query_job.result()

print(f"Total slot time: {query_job.slot_millis}ms")
print(f"Bytes processed: {query_job.total_bytes_processed:,}")

# 2. Add partitioning to reduce data scanned
CREATE TABLE dataset.table_partitioned
PARTITION BY DATE(date_column)
AS SELECT * FROM dataset.table

# 3. Add clustering for better data organization
CREATE TABLE dataset.table_clustered
CLUSTER BY key_column1, key_column2
AS SELECT * FROM dataset.table

# 4. Check for full table scans
# Use query plan to identify issues
job_config = bigquery.QueryJobConfig(dry_run=True)
query_job = conn.query(query, job_config=job_config)
```

### High Costs

**Problem**: Unexpected high query costs

**Solutions**:

```python
# 1. Enable dry run to estimate costs
adapter = BigQueryAdapter(
    project_id="my-project",
    dry_run=True  # Preview only
)

# 2. Check query costs
plan = adapter.get_query_plan(conn, query)
print(f"Will process: {plan['bytes_processed'] / 1024**3:.2f} GB")
print(f"Estimated cost: ${plan['estimated_cost']:.4f}")

# 3. Set billing limits
adapter = BigQueryAdapter(
    maximum_bytes_billed=10 * 1024**3  # Hard limit
)

# 4. Use partitioning and clustering
# Reduces data scanned per query
CREATE TABLE dataset.table_optimized
PARTITION BY DATE(date_column)
CLUSTER BY key1, key2
AS SELECT * FROM dataset.table_raw
```

## See Also

### Platform Documentation

- {doc}`/platforms/platform-selection-guide` - Choosing BigQuery vs other platforms
- {doc}`/platforms/quick-reference` - Quick setup for all platforms
- {doc}`/platforms/comparison-matrix` - Feature comparison
- {doc}`/guides/cloud-storage` - GCS, S3, Azure Blob Storage integration

### Benchmark Guides

- {doc}`/benchmarks/tpc-h` - TPC-H on BigQuery
- {doc}`/benchmarks/tpc-ds` - TPC-DS on BigQuery
- {doc}`/benchmarks/clickbench` - ClickBench on BigQuery

### API Reference

- {doc}`duckdb` - DuckDB adapter
- {doc}`clickhouse` - ClickHouse adapter
- {doc}`databricks` - Databricks adapter
- {doc}`../base` - Base benchmark interface
- {doc}`../index` - Python API overview

### External Resources

- [BigQuery Documentation](https://docs.cloud.google.com/bigquery/docs) - Official BigQuery docs
- [BigQuery Best Practices](https://docs.cloud.google.com/bigquery/docs/best-practices-performance-overview) - Performance and cost optimization
- [Partitioning Guide](https://docs.cloud.google.com/bigquery/docs/partitioned-tables) - Partitioning strategies
- [Clustering Guide](https://docs.cloud.google.com/bigquery/docs/clustered-tables) - Clustering best practices
- [Cost Optimization](https://docs.cloud.google.com/bigquery/docs/best-practices-costs) - Reducing query costs
