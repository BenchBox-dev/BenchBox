<!-- markdownlint-disable MD024 -->

# Apache DataFusion Platform Adapter

```{tags} reference, python-api, sql-platform
```

The DataFusion adapter provides in-memory analytical query execution using Apache DataFusion's fast query engine.

## Overview

DataFusion is a fast, embeddable query engine written in Rust with Python bindings. It is installed with the `datafusion` extra (`pip install "benchbox[datafusion]"`), which also installs PyArrow. It provides:

- **In-memory execution** - Optimized for analytical workloads
- **Dual format support** - CSV direct loading or Parquet conversion
- **PostgreSQL-compatible SQL** - Broad SQL dialect compatibility
- **PyArrow integration** - Native Arrow columnar format support
- **Automatic optimization** - Query planning and execution optimization

Common use cases:

- In-process analytics without database overhead
- Rapid prototyping and development
- PyArrow-based data workflows
- OLAP benchmark testing
- Memory-constrained environments (CSV mode)

## Quick Start

Basic usage:

```python
from benchbox import TPCH
from benchbox.platforms.datafusion import DataFusionAdapter

adapter = DataFusionAdapter(
    working_dir="./datafusion_working",
    memory_limit="16G",
    data_format="parquet"
)

benchmark = TPCH(scale_factor=1.0)
benchmark.generate_data()
results = benchmark.run_with_platform(adapter)
```

`run_with_platform` does not generate data. Without `generate_data()` the tables are created empty and the queries succeed with zero rows.

## API Reference

### DataFusionAdapter Class

<span id="benchbox.platforms.datafusion.DataFusionAdapter"></span>

`benchbox.platforms.datafusion.DataFusionAdapter` runs BenchBox benchmarks on Apache DataFusion, an in-process query engine, with the benchmark data held in a working directory.

**Import:** `from benchbox.platforms.datafusion import DataFusionAdapter` · **Extras:** `datafusion`

#### Parameters

All parameters are keyword arguments (the signature is `(**config)`).

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `working_dir` | `str` | `"./datafusion_working"` | Directory for the converted Parquet files. Created (with parents) when the adapter is constructed. |
| `memory_limit` | `str` | `"16G"` | Size of the memory pool. A number with an optional `G`, `M` or `K` unit and an optional trailing `B` (`"16G"`, `"8GB"`, `"4096MB"`); a bare number is bytes. |
| `target_partitions` | `int` | CPU count | DataFusion `target_partitions`, the degree of parallelism. |
| `data_format` | `str` | `"parquet"` | `"parquet"` converts each table to a Parquet file in `working_dir`; any other value registers the text files as CSV. |
| `temp_dir` | `str` or `None` | `None` | Recorded and reported by `get_platform_info`. In 0.4.1 it does not move spill files: spilling uses the operating system's temporary directory. |
| `batch_size` | `int` | `8192` | DataFusion record-batch size. |
| `parquet_pushdown` | `bool` | `True` | Turns Parquet pruning on or off. |
| `repartition_joins` | `bool` | `True` | Turns join repartitioning on or off. |
| `force_recreate` | `bool` | `False` | Delete the working directory when a connection is created. |

The adapter also accepts the keys every BenchBox adapter takes: see [Constructor Parameters](#constructor-parameters). Keys it does not recognise are accepted and ignored.

The constructor checks no value. `memory_limit="lots"` and `data_format="orc"` are accepted; an unparseable `memory_limit` leaves the memory pool unset, and `batch_size` is checked only when `create_connection()` runs.

#### Returns

A `DataFusionAdapter`. Construction creates `working_dir` but opens no connection; call `create_connection()`.

#### Raises

- `ImportError`: the `datafusion` package is not installed (`DataFusion not installed. Install with: pip install datafusion`).
- Nothing else. Invalid values fail later; see `create_connection`.

#### Example

```python
from benchbox.platforms.datafusion import DataFusionAdapter

adapter = DataFusionAdapter(working_dir="df_example", memory_limit="1G", target_partitions=2)
connection = adapter.create_connection()
result = adapter.execute_query(connection, "SELECT 42 AS answer", "q1")
print(result["status"], result["rows_returned"], result["first_row"])
print(adapter.get_platform_info(connection)["configuration"])
print(adapter.get_query_plan(connection, "SELECT 1").splitlines()[0])
print(adapter.check_database_exists())

bad = DataFusionAdapter(working_dir="df_example", batch_size="big")
try:
    bad.create_connection()
except TypeError as exc:
    print(exc)
print(DataFusionAdapter(working_dir="df_example", data_format="orc").data_format)
```

Output on 0.4.1 with `datafusion` 54.0.0:

```text
SUCCESS 1 (42,)
{'working_dir': 'df_example', 'memory_limit': '1G', 'target_partitions': 2, 'data_format': 'parquet', 'temp_dir': None, 'batch_size': 8192, 'result_cache_enabled': False}
logical_plan | Projection: Int64(1)
False
argument 'batch_size': 'str' object cannot be interpreted as an integer
orc
```

#### Compatibility

- `benchbox.platforms.DataFusionAdapter` is the same class.
- DataFusion needs the `datafusion` extra; the base `benchbox` install does not include it.
- `tuning_config` takes a `UnifiedTuningConfiguration`, not a dictionary.

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

The values are stored as attributes of the same name (`DataFusionAdapter().force_recreate` is `False`).

### Methods and attributes

#### Construction and configuration

<span id="benchbox.platforms.datafusion.DataFusionAdapter.__init__"></span>
**`__init__(**config)`**: Creates the adapter from keyword arguments. See Parameters above. It stores the settings, creates `working_dir` (and any missing parents) on disk, and opens no connection.

<span id="benchbox.platforms.datafusion.DataFusionAdapter.from_config"></span>
**`from_config(config: dict[str, Any])`** (class method): Builds an adapter from a unified configuration dictionary and returns it. `working_dir` is used when present; otherwise `benchmark` and `scale_factor` are required (a missing key raises `KeyError`) and the directory is `<output_dir>/databases/<benchmark>_sf<token>/<benchmark>_sf<token>_notuning_noconstraints.datafusion`, created if missing (`benchmark_runs/databases/...` when `output_dir` is absent). Keys map to constructor parameters as follows: `memory_limit` (default `"16G"`), `target_partitions` or else `partitions` or else the CPU count, `format` to `data_format` (default `"parquet"`), `temp_dir`, `batch_size` (default `8192`), `force` to `force_recreate` (a `force_recreate` key is ignored), plus `parquet_pushdown`, `repartition_joins` and the tuning and verbosity keys, which pass through. Keys of a nested `options` dictionary are merged in, and top-level keys win.

<span id="benchbox.platforms.datafusion.DataFusionAdapter.add_cli_arguments"></span>
**`add_cli_arguments(parser) -> None`** (static method): Adds a `DataFusion Arguments` group to an `argparse.ArgumentParser` and returns `None`: `--datafusion-memory-limit` (default `16G`), `--datafusion-partitions` (int, default `None`), `--datafusion-format` (`csv` or `parquet`, default `parquet`), `--datafusion-temp-dir` (default `None`), `--datafusion-batch-size` (int, default `8192`) and `--datafusion-working-dir` (default `None`).

<span id="benchbox.platforms.datafusion.DataFusionAdapter.platform_name"></span>
**`platform_name`** (property): Always the string `'DataFusion'`.

<span id="benchbox.platforms.datafusion.DataFusionAdapter.get_target_dialect"></span>
**`get_target_dialect() -> str`**: Returns `'datafusion'`, the SQL dialect BenchBox translates queries into.

<span id="benchbox.platforms.datafusion.DataFusionAdapter.get_platform_info"></span>
**`get_platform_info(connection: Any = None) -> dict[str, Any]`**: Returns a `dict`: `platform_type` (`'datafusion'`), `platform_name`, `connection_mode` (`'in-memory'`), `configuration` (`working_dir`, `memory_limit`, `target_partitions`, `data_format`, `temp_dir`, `batch_size`, `result_cache_enabled` which is `False`), `client_library_version`, `platform_version` and `driver_version_actual` (all three are the installed `datafusion` version). The `connection` argument is accepted and not used.

#### Connection and schema

<span id="benchbox.platforms.datafusion.DataFusionAdapter.create_connection"></span>
**`create_connection(**connection_config) -> Any`**: Returns a `DataFusionConnectionCompat`, a thin wrapper around a DataFusion `SessionContext`. Existing-database handling runs first, under a lock file next to `working_dir`: with `force_recreate=True` the whole working directory is deleted; otherwise a directory that holds `.parquet` files is validated and reused (`database_was_reused` becomes `True`). The session is built with `target_partitions`, `batch_size`, Parquet pruning (`parquet_pushdown`), join repartitioning (`repartition_joins`), and a fair-spill memory pool of `memory_limit` with disk spilling. If the pool cannot be configured, for example because `memory_limit` cannot be parsed, no error is raised and the pool is left unset. A `batch_size` that is not an integer raises `TypeError` here, not in the constructor. Raises `RuntimeError` if the working-directory lock cannot be acquired within 10 seconds.

<span id="benchbox.platforms.datafusion.DataFusionAdapter.configure_for_benchmark"></span>
**`configure_for_benchmark(connection: Any, benchmark_type: str) -> None`**: Does nothing and returns `None`. DataFusion is configured when the connection is created.

<span id="benchbox.platforms.datafusion.DataFusionAdapter.create_schema"></span>
**`create_schema(benchmark, connection: Any) -> float`**: Records the benchmark's table definitions and returns the elapsed time in seconds (`float`). It creates no tables: the connection has no tables until `load_data` runs. DataFusion does not enforce primary or foreign keys, so none are created.

<span id="benchbox.platforms.datafusion.DataFusionAdapter.validate_platform_capabilities"></span>
**`validate_platform_capabilities(benchmark_type: str)`**: Checks the adapter setup for a benchmark type such as `'tpch'` and returns a `ValidationResult` (`is_valid`, `errors`, `warnings`, `details`). It adds an error if the `datafusion` package is missing, the warning `Some TPC-DS queries may fail due to DataFusion SQL feature limitations` for `'tpcds'`, and a warning for a `memory_limit` below 2 GB. `details` holds the platform name, benchmark type, dry-run flag, working directory, memory limit, partitions, data format and DataFusion version.

#### Loading data into tables

<span id="benchbox.platforms.datafusion.DataFusionAdapter.load_data"></span>
**`load_data(benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]`**: Loads the benchmark's data files and registers them as tables, and returns `(table_row_counts, seconds, per_table_timings)`. `table_row_counts` maps lower-case table names to row counts (TPC-H at scale factor 0.01 gives `customer` 1500, `lineitem` 60175); `per_table_timings` maps each table to `{'total_ms': ...}`. With `data_format="parquet"` each text file is converted to `<table>.parquet` in `working_dir` and registered; any other `data_format` value registers the text files directly as CSV. Delta Lake and Iceberg directories are detected and registered as such. Tables defined by the schema but without data files are created empty. A benchmark with no data files gets empty tables and `seconds` of `0.0`.

<span id="benchbox.platforms.datafusion.DataFusionAdapter.create_external_tables"></span>
**`create_external_tables(benchmark: Any, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]`**: Same as `load_data`: external-table mode uses the same registration path, and the return value is identical.

<span id="benchbox.platforms.datafusion.DataFusionAdapter.supports_external_tables"></span>
**`supports_external_tables`** (class attribute): `True`. The adapter implements `create_external_tables`.

#### Working directory

<span id="benchbox.platforms.datafusion.DataFusionAdapter.check_database_exists"></span>
**`check_database_exists(**connection_config) -> bool`**: Returns `True` when `working_dir` (or a `working_dir` keyword) exists and holds at least one `.parquet` file directly inside it, otherwise `False`. It is `False` for a new directory and `True` after a Parquet-mode `load_data`; CSV mode writes no Parquet files.

<span id="benchbox.platforms.datafusion.DataFusionAdapter.drop_database"></span>
**`drop_database(**connection_config) -> None`**: Deletes the working directory, including all converted Parquet files, and returns `None`. It does nothing if the directory does not exist.

#### Query execution and plans

<span id="benchbox.platforms.datafusion.DataFusionAdapter.execute_query"></span>
**`execute_query(connection: Any, query: str, query_id: str, benchmark_type: str | None = None, scale_factor: float | None = None, validate_row_count: bool = True, stream_id: int | None = None) -> dict[str, Any]`**: Runs one query and returns a result `dict`; it does not raise for SQL errors. On success `status` is `'SUCCESS'` with `query_id`, `execution_time_seconds`, `rows_returned` and `first_row` (a tuple, or `None`); when `benchmark_type` is given and `validate_row_count` is true it adds a `row_count_validation` entry (`status` `'SKIPPED'` when no expected count is known). On an error `status` is `'FAILED'` with `error` and `error_type` (for example `'ValueError'`). In dry-run mode it records the SQL and returns `status` `'DRY_RUN'`. For TPC-H queries 11, 16, 18 and 20 the SQL is rewritten into an equivalent form first (CTEs, `NOT EXISTS`, joins) because DataFusion mis-executes the original; this applies when `benchmark_type` is `'tpch'` or omitted and `query_id` is `'11'`, `'Q11'` and so on. Do not reuse those query IDs for other SQL without setting another `benchmark_type`.

<span id="benchbox.platforms.datafusion.DataFusionAdapter.preprocess_operation_sql"></span>
**`preprocess_operation_sql(operation_id: str, operation: Any) -> str | None`**: Rewrites the SQL of a write operation. For an operation whose `category` is `'bulk_load'` it returns SQL that replaces `COPY bulk_load_ops_target FROM '<path>'` with `DROP TABLE IF EXISTS` / `CREATE EXTERNAL TABLE ... STORED AS CSV|PARQUET LOCATION '<path>'` / `INSERT INTO bulk_load_ops_target SELECT ...`; SQL that matches no known pattern is returned unchanged. For any other category it returns `None`. `operation` needs the attributes `category`, `write_sql` and `file_dependencies`.

<span id="benchbox.platforms.datafusion.DataFusionAdapter.get_query_plan"></span>
**`get_query_plan(connection: Any, query: str) -> str | None`**: Returns the plan as text from `EXPLAIN <query>`, one line per plan row in the form `<plan_type> | <plan text>` (for example `logical_plan | TableScan: nation projection=[...]`), or `None` if the statement fails or returns nothing.

<span id="benchbox.platforms.datafusion.DataFusionAdapter.get_query_plan_parser"></span>
**`get_query_plan_parser()`**: Returns a `DataFusionQueryPlanParser` (from `benchbox.core.query_plans.parsers.datafusion`) for the text that `get_query_plan` returns.

<span id="benchbox.platforms.datafusion.DataFusionAdapter.plan_capture_phase_eligible"></span>
**`plan_capture_phase_eligible`** (class attribute): `True`. Query plans for DataFusion are captured in a separate pass after the timed run, not inline with the timed queries.

#### Capabilities

<span id="benchbox.platforms.datafusion.DataFusionAdapter.driver_isolation_capability"></span>
**`driver_isolation_capability`** (class attribute): `DriverIsolationCapability.SUPPORTED` (from `benchbox.platforms.base`): a requested DataFusion driver version can run in an isolated runtime.

#### Added in 0.4.2

<span id="benchbox.platforms.datafusion.DataFusionAdapter.materialize_schema_only_tables"></span>
**`materialize_schema_only_tables(benchmark, connection: Any) -> dict[str, int]`**: Creates empty tables from the schema recorded by `create_schema` and returns a `dict` of table name to row count. BenchBox calls it instead of `load_data` for benchmarks that set `SKIP_DATA_LOADING`.

## Configuration Examples

### Basic Configuration

In-memory analytics with default settings:

```python
from benchbox.platforms.datafusion import DataFusionAdapter

adapter = DataFusionAdapter()

adapter = DataFusionAdapter(
    working_dir="/fast/ssd/datafusion"
)
```

The first adapter uses the defaults (Parquet format, 16G memory). The second sets a custom working directory.

### Performance Optimized

Optimized for high-performance benchmarks:

```python
import os

adapter = DataFusionAdapter(
    working_dir="/fast/nvme/datafusion",
    memory_limit="64G",
    target_partitions=os.cpu_count(),
    data_format="parquet",
    batch_size=16384,
    temp_dir="/fast/ssd/temp"
)
```

`target_partitions=os.cpu_count()` uses all cores, Parquet is a columnar format with compression, and `batch_size=16384` uses larger batches for throughput.

### Memory Constrained

Optimized for memory-limited environments:

```python
adapter = DataFusionAdapter(
    memory_limit="4G",
    target_partitions=4,
    data_format="csv",
    batch_size=4096
)
```

CSV has a lower memory footprint than Parquet.

### Data Format Selection

Choose between CSV and Parquet formats:

```python
adapter_parquet = DataFusionAdapter(
    data_format="parquet",
    memory_limit="16G"
)

adapter_csv = DataFusionAdapter(
    data_format="csv",
    memory_limit="8G"
)
```

Parquet is recommended for query performance. CSV gives a faster initial load and a lower memory footprint.

### Configuration from Unified Config

Create adapter from BenchBox's unified configuration dictionary:

```python
from benchbox.platforms.datafusion import DataFusionAdapter

config = {
    "benchmark": "tpch",
    "scale_factor": 10.0,
    "output_dir": "/data/benchmarks",
    "memory_limit": "32G",
    "partitions": 16,
    "format": "parquet",
    "batch_size": 16384,
    "force": False
}

adapter = DataFusionAdapter.from_config(config)
```

**Configuration Keys**:

- **benchmark** (str): Benchmark name (e.g., "tpch", "tpcds"); required unless `working_dir` is given
- **scale_factor** (float): Benchmark scale factor; required unless `working_dir` is given
- **output_dir** (str, optional): Base directory for the generated working directory
- **memory_limit** (str): Memory limit (e.g., "16G", "32G"). Default: "16G"
- **partitions** (int, optional): Number of parallel partitions (`target_partitions` is read first)
- **format** (str): Data format ("csv" or "parquet"). Default: "parquet"
- **batch_size** (int): RecordBatch size. Default: 8192
- **temp_dir** (str, optional): Recorded and reported only; see the `temp_dir` parameter
- **force** (bool): Force recreate existing data
- **working_dir** (str, optional): Explicit working directory path

The `from_config()` method automatically generates appropriate paths based on
benchmark name and scale factor when `working_dir` is not explicitly provided.

## Data Loading

DataFusion supports two data loading strategies:

### CSV Mode (Direct Loading)

Directly registers CSV files as external tables:

```python
adapter = DataFusionAdapter(data_format="csv")
```

The CSV reader handles the TPC format automatically: pipe-delimited fields (`|`), a trailing delimiter and no header row.

**Characteristics**:

- Fast initial load (under 3 seconds for SF=1 on a 4-core machine)
- Lower memory usage (peak resident memory of about 240 MB while loading SF=1, against about 530 MB for Parquet)
- Slower query execution
- Good for one-time queries or memory-constrained environments

### Parquet Mode (Conversion)

Converts CSV to Parquet format first:

```python
adapter = DataFusionAdapter(data_format="parquet")
```

The conversion process is:

1. Read the CSV files with PyArrow.
2. Handle trailing delimiters.
3. Apply the schema from the benchmark.
4. Write compressed Parquet files.
5. Register the Parquet tables in DataFusion.

**Characteristics**:

- One-time conversion overhead (9 to 10 seconds for SF=1 on a 4-core machine)
- Better query performance due to columnar format
- Automatic columnar compression (the SF=1 TPC-H Parquet files take 390 MB, against 1.1 GB of `.tbl` text)
- Suited for repeated query execution

### Performance Comparison

```python
adapter_csv = DataFusionAdapter(data_format="csv")

adapter_parquet = DataFusionAdapter(data_format="parquet")
```

For scale factor 1 on 4 cores, CSV mode loads in about 3 seconds and is the query-time baseline: a `COUNT(*)` over `lineitem` took about 0.5 to 1.2 seconds. Parquet mode loads in about 10 seconds and its queries are faster: the same `COUNT(*)` took under 0.02 seconds.

## Query Execution

### Execute Queries

Execute SQL queries directly:

```python
from benchbox.platforms.datafusion import DataFusionAdapter

adapter = DataFusionAdapter()
connection = adapter.create_connection()

df = connection.sql("SELECT COUNT(*) FROM lineitem")
result_batches = df.collect()

row_count = result_batches[0].column(0)[0]
print(f"Row count: {row_count}")
```

The tables exist after `create_schema()` and `load_data()` (see Data Loading). Queries run on the `SessionContext`, and `collect()` returns a list of PyArrow record batches.

### Execute with Validation

Execute queries with automatic row count validation:

```python
result = adapter.execute_query(
    connection,
    query="SELECT * FROM lineitem WHERE l_shipdate > '1995-01-01'",
    query_id="q1",
    benchmark_type="tpch",
    scale_factor=1.0,
    validate_row_count=True
)

print(f"Status: {result['status']}")
print(f"Execution time: {result['execution_time_seconds']:.3f}s")
print(f"Rows returned: {result['rows_returned']}")

validation = result.get('row_count_validation')
if validation:
    print(f"Expected rows: {validation['expected']} ({validation['status']})")
```

### Dry-Run Mode

Preview queries without execution:

```python
from benchbox import TPCH

adapter = DataFusionAdapter()
adapter.enable_dry_run()

benchmark = TPCH(scale_factor=1.0)
results = benchmark.run_with_platform(adapter, query_subset=[1, 6])

for entry in adapter.captured_sql:
    print(f"{entry['order']}: {entry['sql'][:100]}...")
```

Queries are captured but not executed, and the SQL is available in `adapter.captured_sql`. It is a list of dicts with `order`, `sql` and `operation_type`.

## Platform Information

### Get Platform Details

Retrieve DataFusion version and configuration:

```python
adapter = DataFusionAdapter(memory_limit="16G")
connection = adapter.create_connection()

info = adapter.get_platform_info(connection)

print(f"Platform: {info['platform_name']}")
print(f"Version: {info['platform_version']}")
print(f"Memory limit: {info['configuration']['memory_limit']}")
print(f"Partitions: {info['configuration']['target_partitions']}")
print(f"Data format: {info['configuration']['data_format']}")
```

### Validate Capabilities

Check platform capabilities before running benchmarks:

```python
validation = adapter.validate_platform_capabilities("tpch")

if validation.is_valid:
    print("Platform ready for TPC-H benchmark")
else:
    print("Validation errors:")
    for error in validation.errors:
        print(f"  - {error}")

if validation.warnings:
    print("Warnings:")
    for warning in validation.warnings:
        print(f"  - {warning}")

print(f"DataFusion version: {validation.details.get('datafusion_version')}")
```

`validation.details` holds the platform details, such as the DataFusion version.

## Advanced Features

### Custom Configuration

Configure DataFusion SessionContext options:

```python
adapter = DataFusionAdapter(
    memory_limit="32G",
    target_partitions=16,
    batch_size=16384
)
```

The adapter also configures these automatically: Parquet optimizations (pruning and pushdown), the target partitions (parallelism), the memory limit, the batch size and identifier normalization (lowercase, for TPC compatibility).

### Working Directory Management

Manage DataFusion working directory:

```python
exists = adapter.check_database_exists()

if exists:
    print("Existing DataFusion data found")

    adapter.drop_database()

adapter = DataFusionAdapter(force_recreate=True)
```

`check_database_exists()` checks whether the working directory exists with data. Drop existing data if needed, or create the adapter with `force_recreate=True`.

### PyArrow Integration

DataFusion uses PyArrow for data representation:

```python
import pyarrow as pa
import pyarrow.parquet as pq

adapter = DataFusionAdapter(data_format="parquet")
connection = adapter.create_connection()

df = connection.sql("SELECT * FROM lineitem LIMIT 10")
batches = df.collect()

table = pa.Table.from_batches(batches)
print(f"Schema: {table.schema}")
print(f"Rows: {table.num_rows}")

pandas_df = table.to_pandas()
```

Query results are PyArrow record batches. `pa.Table.from_batches` builds a PyArrow table from them. `to_pandas()` needs the `pandas` package, which this extra does not install.

## Advanced Features

### Manual Connection Management

For advanced use cases requiring connection reuse:

```python
from benchbox.platforms.datafusion import DataFusionAdapter

adapter = DataFusionAdapter(memory_limit="16G", data_format="parquet")
connection = adapter.create_connection()

result1 = connection.sql("SELECT COUNT(*) FROM lineitem").collect()
result2 = connection.sql("SELECT AVG(l_extendedprice) FROM lineitem").collect()
```

This runs two custom queries on one connection.

**When to use**:

- Executing multiple custom queries without benchmark overhead
- Testing individual queries during development
- Building custom benchmark workflows
- Integrating with existing DataFusion SessionContext

**Note**: `benchmark.run_with_platform(adapter)` handles connection lifecycle automatically and is recommended for most use cases.

## Best Practices

### Memory Management

1. **Set appropriate memory limits** for your system:

   ```python
   import psutil
   available_memory = psutil.virtual_memory().available
   memory_limit = f"{int(available_memory * 0.7 / 1024**3)}G"

   adapter = DataFusionAdapter(memory_limit=memory_limit)
   ```

2. **Use CSV format** for memory-constrained environments:

   ```python
   adapter = DataFusionAdapter(
       data_format="csv",
       memory_limit="4G"
   )
   ```

3. **Put the system temporary directory on fast storage** for disk spilling. DataFusion spills to the operating system's temporary directory, and `temp_dir` is recorded in the platform information but does not move the spill files in 0.4.1:

   ```python
   adapter = DataFusionAdapter(
       memory_limit="16G"
   )
   ```

### Performance Optimization

1. **Use Parquet format** for repeated query execution:

   ```python
   adapter = DataFusionAdapter(data_format="parquet")
   ```

2. **Match partitions to CPU cores**:

   ```python
   import os
   adapter = DataFusionAdapter(
       target_partitions=os.cpu_count()
   )
   ```

3. **Use fast storage** for working directory:

   ```python
   adapter = DataFusionAdapter(
       working_dir="/fast/nvme/datafusion",
       data_format="parquet"
   )
   ```

4. **Tune batch size** for your workload:

   ```python
   adapter = DataFusionAdapter(
       batch_size=4096,
       memory_limit="4G"
   )

   adapter = DataFusionAdapter(
       batch_size=16384,
       memory_limit="32G"
   )
   ```

   The first adapter uses smaller batches, which give lower latency and lower memory use. The second uses larger batches, which give higher throughput and higher memory use.

   **Batch Size Guidelines**:

   - **4096**: Best for interactive queries and memory-constrained environments
   - **8192** (default): Good balance for most analytical workloads
   - **16384**: Optimal for high-throughput batch processing with sufficient RAM
   - **Trade-off**: Larger batches = higher memory usage but better vectorized execution

### Scale Factor Recommendations

**Small Scale (SF < 1)**:

```python
adapter = DataFusionAdapter(
    memory_limit="4G",
    target_partitions=4,
    data_format="csv"
)
```

**Medium Scale (SF 1-10)**:

```python
adapter = DataFusionAdapter(
    memory_limit="16G",
    target_partitions=8,
    data_format="parquet"
)
```

**Large Scale (SF 10+)**:

```python
adapter = DataFusionAdapter(
    memory_limit="64G",
    target_partitions=16,
    data_format="parquet",
    temp_dir="/fast/ssd/temp",
    batch_size=16384
)
```

## Common Issues

### Out of Memory Errors

**Problem**: Query fails with out of memory error

**Solution**:

```python
adapter = DataFusionAdapter(
    memory_limit="8G",
    data_format="csv"
)

adapter = DataFusionAdapter(
    memory_limit="4G"
)
```

The first adapter reduces the memory limit and uses CSV format. The second lowers the memory pool so that operators spill to disk earlier. Spill files go to the operating system's temporary directory.

### Slow Query Performance

**Problem**: Queries execute slowly

**Solutions**:

```python
adapter = DataFusionAdapter(data_format="parquet")

adapter = DataFusionAdapter(target_partitions=16)

adapter = DataFusionAdapter(
    working_dir="/fast/nvme/datafusion"
)
```

These use Parquet format, increase parallelism and put the working directory on fast storage, in that order.

### SQL Feature Errors

**Problem**: Some queries fail with SQL errors

**Solution**:

```python
validation = adapter.validate_platform_capabilities("tpcds")

if validation.warnings:
    print("Platform warnings:")
    for warning in validation.warnings:
        print(f"  - {warning}")
```

Validate the platform capabilities first. BenchBox translates queries for the `datafusion` dialect, which is close to PostgreSQL, so some advanced SQL features may not be supported.

## See Also

### Platform Documentation

- {doc}`/platforms/datafusion` - Comprehensive DataFusion platform guide
- {doc}`/platforms/platform-selection-guide` - Platform selection guide
- {doc}`/platforms/comparison-matrix` - Platform comparison
- {doc}`duckdb` - Similar in-process analytics platform

### Benchmark Guides

- {doc}`/benchmarks/tpc-h` - TPC-H benchmark
- {doc}`/benchmarks/tpc-ds` - TPC-DS benchmark
- {doc}`/benchmarks/index` - All benchmarks

### API Reference

- {doc}`../base` - Base platform adapter interface
- {doc}`/reference/python-api/index` - Python API overview

### External Resources

- [Apache DataFusion Documentation](https://datafusion.apache.org/) - Official docs
- [DataFusion Python Bindings](https://datafusion.apache.org/python/) - Python API
- [Apache Arrow](https://arrow.apache.org/) - Arrow columnar format
