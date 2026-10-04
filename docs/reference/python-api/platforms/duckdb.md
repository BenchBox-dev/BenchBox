<!-- markdownlint-disable MD024 -->

# DuckDB Platform Adapter

```{tags} reference, python-api, duckdb
```

The DuckDB adapter provides fast, embedded analytical database execution for benchmarks.

## Overview

DuckDB is installed with the `duckdb` extra (`pip install "benchbox[duckdb]"`); the base `benchbox` install does not include it. It provides:

- **No server or credentials** - Runs inside your Python process
- **Columnar query engine** - Optimized for analytical queries
- **In-memory or persistent** - Flexible storage options
- **ANSI SQL support** - Comprehensive analytical SQL features

Common use cases:

- Development and testing
- CI/CD pipelines
- Small to medium datasets (< 100GB)
- Local benchmarking without cloud infrastructure

## Quick Start

Basic usage:

```python
from benchbox.tpch import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter

# In-memory database (default)
adapter = DuckDBAdapter()

# Or persistent database
adapter = DuckDBAdapter(database_path="benchmark.duckdb")

# Run benchmark
benchmark = TPCH(scale_factor=0.1)
results = benchmark.run_with_platform(adapter)
```

## API Reference

### DuckDBAdapter Class

<span id="benchbox.platforms.duckdb.DuckDBAdapter"></span>

`benchbox.platforms.DuckDBAdapter` runs BenchBox benchmarks on an embedded DuckDB database, in memory or in a file.

**Import:** `from benchbox.platforms import DuckDBAdapter` · **Extras:** `duckdb`

#### Parameters

All parameters are keyword arguments (the signature is `(**config)`).

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `database_path` | `str` | `":memory:"` | Database file path, or `":memory:"`. |
| `memory_limit` | `str` or `None` | `"4GB"` | DuckDB `memory_limit`, applied when a connection is created. `None` leaves DuckDB's own default. |
| `thread_limit` | `int` or `None` | `None` | DuckDB `threads`. Anything `int()` accepts is converted (`"4"` becomes `4`). `None` leaves DuckDB's own default. |
| `max_temp_directory_size` | `str` or `None` | `None` | DuckDB `max_temp_directory_size`: a size such as `"2GB"` or `"90% of available disk space"`. |
| `progress_bar` | `bool` | `False` | Turns on DuckDB's progress bar for the connection. |
| `force_recreate` | `bool` | `False` | Delete an existing database file when a connection is created. |

A size must be a number followed by a unit (`B`, `KB`, `MB`, `GB`, `TB`, `KiB`, `MiB`, `GiB`, `TiB`, or long forms such as `gigabytes`), with optional spaces and an optional exponent. Other text raises `ValueError` when the adapter is constructed, for example `memory_limit must use a bounded memory size (e.g., '4GB')`.

The adapter also accepts the keys every BenchBox adapter takes: see [Constructor Parameters](#constructor-parameters). Keys it does not recognise are accepted and ignored: `DuckDBAdapter(read_only=True)` is valid and sets nothing.

#### Returns

A `DuckDBAdapter`. Construction opens no connection and creates no file; call `create_connection()`.

#### Raises

- `ImportError`: the `duckdb` package is not installed (`DuckDB not installed. Install with: pip install duckdb`).
- `ValueError`: `memory_limit` is not a string in the size format (`memory_limit must use a bounded memory size (e.g., '4GB')`), `max_temp_directory_size` is not a size or the disk-space form, or `thread_limit` cannot be converted to `int` (`thread_limit must be an integer`).

#### Example

```python
from benchbox.platforms import DuckDBAdapter

adapter = DuckDBAdapter(memory_limit="512MB", thread_limit=2)
connection = adapter.create_connection()
result = adapter.execute_query(connection, "SELECT 42 AS answer", "q1")
print(result["status"], result["rows_returned"], result["first_row"])
print(adapter.get_platform_info(connection)["configuration"])

try:
    DuckDBAdapter(memory_limit="lots")
except ValueError as exc:
    print(exc)
print(DuckDBAdapter(read_only=True).memory_limit)
```

Output on 0.4.1 with `duckdb` 1.5.6:

```text
SUCCESS 1 (42,)
{'database_path': ':memory:', 'memory_limit': '512MB', 'thread_limit': 2, 'max_temp_directory_size': None, 'enable_progress_bar': False, 'result_cache_enabled': False}
memory_limit must use a bounded memory size (e.g., '4GB')
4GB
```

#### Compatibility

- `benchbox.platforms.duckdb.DuckDBAdapter` is the same object as `benchbox.platforms.DuckDBAdapter`.
- The base `benchbox` install does not include DuckDB; install the `duckdb` extra.
- `temp_directory`, `enable_profiling`, `read_only` and `config` are not parameters of `DuckDBAdapter` in 0.4.1. Passing them has no effect. Use `max_temp_directory_size` for temporary-file limits and `show_query_plans` (see Constructor Parameters) for plans.

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

The values are stored as attributes of the same name (`DuckDBAdapter().force_recreate` is `False`).

### Methods and attributes

#### Construction and configuration

<span id="benchbox.platforms.duckdb.DuckDBAdapter.__init__"></span>
**`__init__(**config)`**: Creates the adapter from keyword arguments. See Parameters above. It stores the settings and opens no connection.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.from_config"></span>
**`from_config(config: dict[str, Any])`** (class method): Builds an adapter from a unified configuration dictionary and returns it. `database_path` is used when present. Otherwise `benchmark` and `scale_factor` are required (a missing key raises `KeyError`) and the path is `<output_dir>/databases/<benchmark>_sf<token>/<benchmark>_sf<token>_notuning_noconstraints.duckdb`, for example `runs/databases/tpch_sf001/tpch_sf001_notuning_noconstraints.duckdb`; the directory is created. When `output_dir` is absent the directory is `benchmark_runs/databases/<benchmark>_sf<token>` in the current directory, for example `benchmark_runs/databases/tpch_sf1/tpch_sf1_notuning_noconstraints.duckdb`. The adapter keeps `memory_limit` (default `"4GB"`), `force` (as `force_recreate`, default `False`) and these pass-through keys when present: `thread_limit`, `max_temp_directory_size`, `progress_bar`, `tuning_config`, `tuning_enabled`, `unified_tuning_configuration`, `tuning_source`, `tuning_source_file`, `verbose_enabled`, `very_verbose` and the `driver_*` runtime keys. Other keys are dropped. `{"database_path": ":memory:"}` alone is a valid configuration.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.add_cli_arguments"></span>
**`add_cli_arguments(parser) -> None`** (static method): Adds a `DuckDB Arguments` group to an `argparse.ArgumentParser` and returns `None`. The group defines `--duckdb-database-path` (default `None`) and `--memory-limit` (default `4GB`).

<span id="benchbox.platforms.duckdb.DuckDBAdapter.get_database_path"></span>
**`get_database_path(**connection_config) -> str`**: Returns the database path as a `str`. A `database_path` keyword that is not `None` wins; otherwise the instance's `database_path` is returned (`':memory:'` by default). `get_database_path(database_path='x.db')` returns `'x.db'`.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.platform_name"></span>
**`platform_name`** (property): Always the string `'DuckDB'`.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.get_target_dialect"></span>
**`get_target_dialect() -> str`**: Returns `'duckdb'`, the SQL dialect BenchBox translates queries into.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.get_platform_info"></span>
**`get_platform_info(connection: Any = None) -> dict[str, Any]`**: Returns a `dict` describing the platform. Keys: `platform_type` (`'duckdb'`), `platform_name`, `connection_mode` (`'memory'` for `:memory:`, else `'file'`), `configuration` (`database_path`, `memory_limit`, `thread_limit`, `max_temp_directory_size`, `enable_progress_bar`, `result_cache_enabled` which is always `False`), `client_library_version`, `platform_version` and `driver_version_actual`. With a connection, the version comes from `SELECT version()`; without one it is the installed `duckdb` module version. The `driver_version_*` and `driver_runtime_strategy` keys appear when the matching runtime settings were supplied.

#### Connection and schema

<span id="benchbox.platforms.duckdb.DuckDBAdapter.create_connection"></span>
**`create_connection(**connection_config) -> Any`**: Opens a DuckDB connection to `get_database_path(**connection_config)` and returns it (a `duckdb.DuckDBPyConnection`). Before connecting it checks for an existing database file: with `force_recreate=True` the file is deleted; otherwise the file is validated and kept if it passes (`database_was_reused` becomes `True`), or deleted if it fails. It then runs `SET memory_limit`, `SET max_temp_directory_size` and `SET threads` for the settings that are not `None`, `SET enable_progress_bar = true` when `progress_bar` is set, and always `SET default_order = 'ASC'`. When `show_query_plans` is set and `capture_plans` is not, it also turns on DuckDB query profiling. In dry-run mode it returns a wrapper that records SQL instead of running it. Raises `RuntimeError` if a requested driver version differs from the version the connection reports.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.configure_for_benchmark"></span>
**`configure_for_benchmark(connection: Any, benchmark_type: str) -> None`**: Applies per-benchmark session settings to an open connection and returns `None`. It does nothing for ordinary benchmarks such as `'tpch'`. For the Transaction Primitives benchmark it runs `SET threads TO 1`, and it switches DuckDB profiling to `query_tree` when `show_query_plans` is set and `capture_plans` is not.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.create_schema"></span>
**`create_schema(benchmark, connection: Any) -> float`**: Creates the benchmark's tables on the connection and returns the elapsed time in seconds (`float`). It translates the benchmark's standard SQL DDL to DuckDB, drops foreign-key constraints for TPC-DS, and runs one `CREATE TABLE` per table. Raises `Exception` with the message `Failed to create table <name>: <cause>` if a statement fails.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.validate_connection_health"></span>
**`validate_connection_health(connection: Any)`**: Runs `SELECT 1` on the connection and returns a `ValidationResult` (`is_valid`, `errors`, `warnings`, `details`). It also tries to read the memory and thread settings with `PRAGMA`; if a read fails it adds a warning and stays valid. On the DuckDB 1.5.6 used for this page both reads failed, so a healthy connection returns `is_valid=True` with the warnings `Could not query memory limit setting` and `Could not query threads setting`.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.validate_platform_capabilities"></span>
**`validate_platform_capabilities(benchmark_type: str)`**: Checks the adapter setup for a benchmark type such as `'tpch'` and returns a `ValidationResult`. It reports an error if the `duckdb` module is missing, and warnings for DuckDB 0.8 or 0.9 and for a `memory_limit` below 1 GB. `details` holds the platform name, benchmark type, dry-run flag, database path, memory limit, thread limit and DuckDB version.

#### Loading data into tables

<span id="benchbox.platforms.duckdb.DuckDBAdapter.load_data"></span>
**`load_data(benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]`**: Loads the benchmark's generated files into the connection's tables and returns a tuple `(table_row_counts, seconds, None)`. `table_row_counts` is a `dict` that maps lower-case table names to the number of rows loaded (TPC-H at scale factor 0.01 gives `customer` 1500, `lineitem` 60175). The text formats `.tbl`, `.dat` and `.csv` are loaded natively. Create the tables first with `create_schema`.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.create_external_tables"></span>
**`create_external_tables(benchmark: Any, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]`**: Registers the data files as views instead of copying them, and returns `(table_row_counts, seconds, None)`. The views read Parquet, Delta, Iceberg, Vortex or text files directly (`table_type` is `VIEW` in `information_schema.tables`). Delta, Iceberg and Vortex sources install and load the matching DuckDB extension, which needs network access the first time.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.supports_external_tables"></span>
**`supports_external_tables`** (class attribute): `True`. The adapter implements `create_external_tables`.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.analyze_tables"></span>
**`analyze_tables(connection: Any) -> None`**: Runs `ANALYZE` on every base table in the `main` schema and prints how many tables it analysed. It returns `None` and does not raise: a failure prints `Could not analyze tables: <cause>` instead.

#### Query execution and plans

<span id="benchbox.platforms.duckdb.DuckDBAdapter.execute_query"></span>
**`execute_query(connection: Any, query: str, query_id: str, benchmark_type: str | None = None, scale_factor: float | None = None, validate_row_count: bool = True, stream_id: int | None = None) -> dict[str, Any]`**: Runs one query and returns a result `dict`; it never raises for SQL errors. On success `status` is `'SUCCESS'` and the dict holds `query_id`, `execution_time_seconds`, `rows_returned` and `first_row` (the first result row as a tuple, or `None`). When `benchmark_type` is given and `validate_row_count` is true, a `row_count_validation` entry reports the comparison with the expected row count (`status` `'SKIPPED'` when none is known). On an SQL error `status` is `'FAILED'` and the dict has `error` (message) and `error_type` (the exception class name, such as `'CatalogException'`). In dry-run mode it records the SQL and returns `status` `'DRY_RUN'` without running it.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.get_query_plan"></span>
**`get_query_plan(connection: Any, query: str) -> str | None`**: Returns the query plan as the JSON text of `EXPLAIN (FORMAT JSON) <query>`, or `None` if the statement fails (for example for a missing table). When the adapter was created with `analyze_plans=True` it uses `EXPLAIN (ANALYZE, FORMAT JSON)` so the plan has actual timings; that runs the query again, and data-changing statements (`INSERT`, `UPDATE`, `DELETE`, `MERGE`, `COPY`) are explained without `ANALYZE`.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.get_query_plan_parser"></span>
**`get_query_plan_parser()`**: Returns a `DuckDBQueryPlanParser` (from `benchbox.core.query_plans.parsers.duckdb`) for the text that `get_query_plan` returns.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.plan_capture_phase_eligible"></span>
**`plan_capture_phase_eligible`** (class attribute): `True`. Query plans for DuckDB are captured in a separate pass after the timed run, not inline with the timed queries.

#### Tuning

<span id="benchbox.platforms.duckdb.DuckDBAdapter.supports_tuning_type"></span>
**`supports_tuning_type(tuning_type) -> bool`**: Returns `True` for `TuningType.SORTING` and `TuningType.PARTITIONING` and `False` for every other `TuningType`.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.generate_tuning_clause"></span>
**`generate_tuning_clause(table_tuning) -> str`**: Returns `''` for every input. DuckDB has no `CREATE TABLE` tuning syntax; tuning is applied after the table exists by `apply_table_tunings`.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.apply_table_tunings"></span>
**`apply_table_tunings(table_name: str, table_tuning, connection: Any) -> None`**: Applies a `TableTuning` to one table and returns `None`. Sorting columns become the index `idx_<table>_sort` and clustering columns the index `idx_<table>_cluster` (columns in `order` sequence; `CREATE INDEX IF NOT EXISTS`). An index that fails to build is logged as a warning, not raised. Partitioning and distribution requests create nothing and are recorded as dropped. Raises `ValueError` (`Failed to apply tunings to DuckDB table <NAME>: ...`) for other failures. The call does nothing when `table_tuning` is empty.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.apply_unified_tuning"></span>
**`apply_unified_tuning(tuning_config, connection) -> None`**: Applies a `UnifiedTuningConfiguration`: for every entry in `table_tunings` it calls `apply_table_tunings`, then `apply_platform_optimizations`. The index statements are recorded in the applied-tuning ledger. Returns `None`; errors are logged and re-raised.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.apply_platform_optimizations"></span>
**`apply_platform_optimizations(tuning_config, connection) -> None`**: Validates the platform-optimisation section of a tuning configuration and returns `None`. It changes nothing in the database and only logs.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.apply_constraint_configuration"></span>
**`apply_constraint_configuration(tuning_config, table_name: str, connection) -> None`**: Checks the constraint settings of a tuning configuration for one table and returns `None`. It runs no SQL; primary and foreign keys are decided when `create_schema` builds the tables.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.apply_ctas_sort"></span>
**`apply_ctas_sort(table_name: str, tuning_config: Any, connection: Any) -> bool`**: Rebuilds a table in sorted order and returns `True`, or returns `False` when nothing was done (no tuning configuration, no sorting columns for `table_name`, or the table is not listed; the name match ignores case). The table is recreated with `CREATE OR REPLACE TABLE ... ORDER BY`, and the `idx_<table>_sort` index is created again afterwards. `tuning_config` is a `UnifiedTuningConfiguration` whose `table_tunings` hold the sorting columns.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.get_tuning_introspector"></span>
**`get_tuning_introspector()`**: Returns a `DuckDBTuningIntrospector` (from `benchbox.platforms.duckdb_introspection`), which confirms recorded `CREATE INDEX` statements against `duckdb_indexes()`.

#### Capabilities

<span id="benchbox.platforms.duckdb.DuckDBAdapter.driver_isolation_capability"></span>
**`driver_isolation_capability`** (class attribute): `DriverIsolationCapability.SUPPORTED` (from `benchbox.platforms.base`): a requested DuckDB driver version can run in an isolated runtime.

<span id="benchbox.platforms.duckdb.DuckDBAdapter.stream_connection_capability"></span>
**`stream_connection_capability`** (class attribute): `StreamConnectionCapability.SHARED_CURSOR` (from `benchbox.platforms.base`): concurrent throughput streams use cursors of the one connection instead of opening more connections.

## Configuration Examples

### In-Memory Database

Suitable for small datasets and rapid iteration:

```python
from benchbox.platforms.duckdb import DuckDBAdapter

# Default in-memory configuration
adapter = DuckDBAdapter()

# With memory limit
adapter = DuckDBAdapter(memory_limit="2GB")

# With thread control
adapter = DuckDBAdapter(
    memory_limit="4GB",
    thread_limit=4
)
```

### Persistent Database

For reusable benchmark data:

```python
# Create persistent database
adapter = DuckDBAdapter(database_path="./benchmarks/tpch.duckdb")

# Run benchmark (data persists)
benchmark = TPCH(scale_factor=1.0)
results = benchmark.run_with_platform(adapter)

# Later: reuse the same database
adapter2 = DuckDBAdapter(database_path="./benchmarks/tpch.duckdb")
results2 = benchmark.run_with_platform(adapter2)
```

### Performance Tuning

Configure for optimal performance:

```python
adapter = DuckDBAdapter(
    database_path="benchmark.duckdb",
    memory_limit="16GB",             # Set appropriate for your system
    thread_limit=8,                  # Match your CPU cores
    max_temp_directory_size="200GB"  # Cap the space used for spilling
)
```

To change other DuckDB settings, run `SET` statements on the connection returned by `create_connection()`:

```python
connection = adapter.create_connection()
connection.execute("SET preserve_insertion_order = false")
```

### Profiling and Debugging

Print each query's plan while a benchmark runs, or capture structured plans with the results:

```python
adapter = DuckDBAdapter(show_query_plans=True)

# Run benchmark: each query's plan is printed after it runs
results = benchmark.run_with_platform(adapter)

# Capture plans into the results instead of printing them
adapter = DuckDBAdapter(capture_plans=True)
```

To read a plan yourself, call `adapter.get_query_plan(connection, sql)`, which returns the plan as JSON text.

## Data Loading

The adapter handles data loading automatically, but you can customize the process:

### Bulk Loading from Parquet

```python
from benchbox.platforms.duckdb import DuckDBAdapter

# Create adapter and open a DuckDB connection
adapter = DuckDBAdapter(database_path="benchmark.duckdb")
conn = adapter.create_connection()

# Custom bulk load from Parquet
conn.execute("""
    CREATE TABLE lineitem AS
    SELECT * FROM read_parquet('data/lineitem/*.parquet')
""")
```

### Loading from CSV

```python
# DuckDB automatically detects CSV format
conn.execute("""
    CREATE TABLE customer AS
    SELECT * FROM read_csv('data/customer.tbl',
                           delim='|',
                           header=false,
                           columns={
                               'c_custkey': 'INTEGER',
                               'c_name': 'VARCHAR',
                               'c_address': 'VARCHAR',
                               'c_nationkey': 'INTEGER',
                               'c_phone': 'VARCHAR',
                               'c_acctbal': 'DECIMAL(15,2)',
                               'c_mktsegment': 'VARCHAR',
                               'c_comment': 'VARCHAR'
                           })
""")
```

## Query Execution

### Execute Queries Directly

```python
from benchbox.platforms.duckdb import DuckDBAdapter

adapter = DuckDBAdapter(database_path="benchmark.duckdb")
conn = adapter.create_connection()

# Execute arbitrary SQL
result = conn.execute("SELECT COUNT(*) FROM lineitem")
row_count = result.fetchone()[0]

# Execute with parameters
query = "SELECT * FROM orders WHERE o_orderdate > ?"
result = conn.execute(query, ["1995-01-01"])

# Or let the adapter time the query and return a result dict
outcome = adapter.execute_query(conn, "SELECT COUNT(*) FROM lineitem", "count_lineitem")
print(outcome["status"], outcome["first_row"])
```

### Query Plans and Optimization

```python
# Get query plan as JSON text
plan = adapter.get_query_plan(
    conn, "SELECT * FROM lineitem WHERE l_shipdate > '1995-01-01'"
)
print(plan[:200])

# Or use DuckDB's own EXPLAIN
explain_result = conn.execute(
    "EXPLAIN SELECT * FROM lineitem WHERE l_shipdate > '1995-01-01'"
)
print(explain_result.fetchall())

# Plans with actual timings: the adapter runs EXPLAIN ANALYZE
analyzing = DuckDBAdapter(database_path="benchmark.duckdb", analyze_plans=True)
```

## Advanced Features

### Parallel Query Execution

```python
# DuckDB automatically parallelizes queries
adapter = DuckDBAdapter(
    memory_limit="16GB",
    thread_limit=8  # Use 8 threads for parallel execution
)

# Complex aggregation will use all threads
results = benchmark.run_with_platform(adapter)
```

### Extensions and Functions

```python
adapter = DuckDBAdapter()
conn = adapter.create_connection()

# Load DuckDB extensions (the first INSTALL downloads the extension)
conn.execute("INSTALL httpfs")
conn.execute("LOAD httpfs")

# Now can read from S3
conn.execute("""
    CREATE TABLE data AS
    SELECT * FROM read_parquet('s3://bucket/data/*.parquet')
""")
```

### Window Functions

```python
# DuckDB supports advanced window functions
query = """
    SELECT
        l_orderkey,
        l_partkey,
        l_extendedprice,
        ROW_NUMBER() OVER (PARTITION BY l_orderkey ORDER BY l_extendedprice DESC) as rn
    FROM lineitem
    WHERE l_shipdate > '1995-01-01'
"""
result = conn.execute(query)
```

## Best Practices

### Memory Management

1. **Set memory limits** to prevent OOM errors:

   ```python
   adapter = DuckDBAdapter(memory_limit="8GB")
   ```

2. **Use persistent databases** for large datasets:

   ```python
   adapter = DuckDBAdapter(database_path="large_dataset.duckdb")
   ```

3. **Monitor memory usage** during execution:

   ```python
   import psutil
   process = psutil.Process()
   print(f"Memory usage: {process.memory_info().rss / 1024 / 1024:.0f} MB")
   ```

### Performance Optimization

1. **Match thread count** to CPU cores:

   ```python
   import os
   adapter = DuckDBAdapter(thread_limit=os.cpu_count())
   ```

2. **Use appropriate data types** in schema:

   ```python
   # Prefer HUGEINT over VARCHAR for large integers
   # Use DATE/TIMESTAMP instead of VARCHAR for dates
   ```

3. **Create indexes** for filtered columns:

   ```python
   conn.execute("CREATE INDEX idx_shipdate ON lineitem(l_shipdate)")
   ```

### Data Validation

1. **Verify row counts** after loading:

   ```python
   expected_rows = 6_001_215  # TPC-H lineitem rows at scale factor 1
   actual_rows = conn.execute("SELECT COUNT(*) FROM lineitem").fetchone()[0]
   assert actual_rows == expected_rows, f"Expected {expected_rows}, got {actual_rows}"
   ```

2. **Check data types**:

   ```python
   schema = conn.execute("PRAGMA table_info('lineitem')").fetchall()
   for column in schema:
       print(f"{column[1]}: {column[2]}")
   ```

## Common Issues

### Out of Memory Errors

**Problem**: Query fails with out of memory error

**Solution**:

```python
# Set explicit memory limit
adapter = DuckDBAdapter(memory_limit="4GB")

# Or use persistent database with disk spilling
adapter = DuckDBAdapter(
    database_path="benchmark.duckdb",
    memory_limit="4GB",
    max_temp_directory_size="100GB"
)
```

### Slow Query Performance

**Problem**: Queries execute slowly

**Solutions**:

```python
# 1. Increase thread count
adapter = DuckDBAdapter(thread_limit=8)

# 2. Use persistent database to avoid repeated loads
adapter = DuckDBAdapter(database_path="cached.duckdb")

# 3. Show query plans to identify bottlenecks
adapter = DuckDBAdapter(show_query_plans=True)
```

### Database Lock Errors

**Problem**: "Database is locked" error

**Solution**:

```python
# Use separate database files for concurrent access
adapter1 = DuckDBAdapter(database_path="benchmark1.duckdb")
adapter2 = DuckDBAdapter(database_path="benchmark2.duckdb")

# Or use in-memory for read-only workloads
adapter = DuckDBAdapter(database_path=":memory:")
```

## See Also

### Platform Documentation

- {doc}`/platforms/platform-selection-guide` - Choosing DuckDB vs other platforms
- {doc}`/platforms/quick-reference` - Quick setup for all platforms
- {doc}`/platforms/comparison-matrix` - Feature comparison

### Benchmark Guides

- {doc}`/benchmarks/tpc-h` - TPC-H on DuckDB
- {doc}`/benchmarks/tpc-ds` - TPC-DS on DuckDB
- {doc}`/benchmarks/clickbench` - ClickBench on DuckDB

### API Reference

- {doc}`../base` - Base benchmark interface
- {doc}`/reference/python-api/index` - Python API overview
- {doc}`/reference/api-reference` - High-level API guide

### External Resources

- [DuckDB Documentation](https://duckdb.org/docs/) - Official DuckDB docs
- [DuckDB Performance Guide](https://duckdb.org/docs/guides/performance/) - Performance tuning
- [DuckDB Extensions](https://duckdb.org/docs/extensions/overview) - Available extensions
