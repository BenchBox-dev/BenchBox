<!-- markdownlint-disable MD024 -->

# SQLite Platform Adapter

```{tags} reference, python-api, sqlite
```

The SQLite adapter provides lightweight testing and development capabilities with embedded database functionality.

## Overview

SQLite is a self-contained, serverless, zero-configuration SQL database engine. It is part of the Python standard library, so the adapter needs no extra package. It offers:

- **Embedded database** - No server process required
- **In-memory mode** - Fast testing with no disk I/O
- **File-based mode** - Persistent storage in single file
- **Zero configuration** - No setup or administration
- **ACID compliant** - Full transactional support
- **Cross-platform** - Runs on all platforms

Common use cases:

- Development and testing workflows
- Small-scale benchmarks (< 10GB data)
- CI/CD pipeline testing
- Proof-of-concept work
- Educational and learning purposes

```{note}
SQLite is not designed for production-scale OLAP workloads. Use ClickHouse, DuckDB, or cloud platforms for large-scale benchmarking.
```

## Quick Start

### In-Memory Mode

```python
from benchbox.tpch import TPCH
from benchbox.platforms.sqlite import SQLiteAdapter

# In-memory database (fastest, no persistence)
adapter = SQLiteAdapter(database_path=":memory:")

# Generate data, then run the benchmark
benchmark = TPCH(scale_factor=0.1)
benchmark.generate_data()
results = benchmark.run_with_platform(adapter)
```

`run_with_platform` does not generate data. Without `generate_data()` the tables are created empty and the queries succeed with zero rows.

### File-Based Mode

```python
from benchbox.tpch import TPCH
from benchbox.platforms.sqlite import SQLiteAdapter

# Persistent file-based database
adapter = SQLiteAdapter(
    database_path="./tpch.db",
    timeout=30.0
)

# Generate data, then run the benchmark
benchmark = TPCH(scale_factor=1.0)
benchmark.generate_data()
results = benchmark.run_with_platform(adapter)
```

The directory that holds the database file must already exist; SQLite does not create directories (`sqlite3.OperationalError: unable to open database file`).

## API Reference

### SQLiteAdapter Class

<span id="benchbox.platforms.sqlite.SQLiteAdapter"></span>

`benchbox.platforms.sqlite.SQLiteAdapter` runs BenchBox benchmarks on a SQLite database, in memory or in a file.

**Import:** `from benchbox.platforms.sqlite import SQLiteAdapter` · **Extras:** none

#### Parameters

All parameters are keyword arguments (the signature is `(**config)`).

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `database_path` | `str` | `":memory:"` | Database file path, or `":memory:"`. |
| `timeout` | `float` | `30.0` | Seconds a connection waits for a lock before `sqlite3.OperationalError: database is locked`. Passed to `sqlite3.connect`. |
| `check_same_thread` | `bool` | `False` | Passed to `sqlite3.connect`. `False` lets any thread use the connection; `True` makes another thread's use raise `sqlite3.ProgrammingError`. |
| `force_recreate` | `bool` | `False` | Delete an existing database file when a connection is created. |

The adapter also accepts the keys every BenchBox adapter takes: see [Constructor Parameters](#constructor-parameters). Keys it does not recognise are accepted and ignored: `SQLiteAdapter(read_only=True)` is valid and sets nothing.

#### Returns

A `SQLiteAdapter`. Construction does not validate or use the values and opens no connection; call `create_connection()`.

#### Raises

Nothing the constructor raises itself. Bad values fail later, in `create_connection()`: a `timeout` that is not a number raises `TypeError` (`must be real number, not str`), a `database_path` that is not a path raises `TypeError`, and a path in a directory that does not exist raises `sqlite3.OperationalError` (`unable to open database file`).

#### Example

```python
from benchbox.platforms.sqlite import SQLiteAdapter

adapter = SQLiteAdapter(timeout=5.0)
connection = adapter.create_connection()
connection.execute("CREATE TABLE customer (c_custkey INTEGER)")
connection.execute("INSERT INTO customer VALUES (1), (2)")
result = adapter.execute_query(connection, "SELECT COUNT(*) FROM customer", "count_customers")
print(result["status"], result["rows_returned"], result["first_row"])
print(adapter.get_query_plan(connection, "SELECT * FROM customer WHERE c_custkey = 1"))
print(adapter.get_platform_info(connection)["configuration"])

try:
    adapter.run_power_test(None)
except NotImplementedError as exc:
    print(exc)
print(SQLiteAdapter(read_only=True).timeout)
```

Output on 0.4.1:

```text
SUCCESS 1 (2,)
QUERY PLAN
`--SCAN customer
{'database_path': ':memory:', 'timeout': 5.0, 'check_same_thread': False}
Power test not implemented for SQLite adapter
30.0
```

#### Compatibility

- `from benchbox.platforms import SQLiteAdapter` returns the same class, although the name is not listed in `benchbox.platforms.__all__`.
- SQLite needs no extra package: the adapter uses the `sqlite3` module of the Python standard library.
- The power, throughput and maintenance tests are not implemented (see the methods below).

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

The values are stored as attributes of the same name (`SQLiteAdapter().force_recreate` is `False`).

### Methods and attributes

#### Construction and configuration

<span id="benchbox.platforms.sqlite.SQLiteAdapter.__init__"></span>
**`__init__(**config)`**: Creates the adapter from keyword arguments. See Parameters above. It stores the settings and opens no connection.

<span id="benchbox.platforms.sqlite.SQLiteAdapter.from_config"></span>
**`from_config(config: dict[str, Any])`** (class method): Builds an adapter from a unified configuration dictionary and returns it. The database path is the first of `database_path`, `connection_string`, or a generated path `<output_dir>/databases/<benchmark>_sf<token>/<benchmark>_sf<token>_notuning_noconstraints.sqlite` (for example `runs/databases/tpch_sf001/tpch_sf001_notuning_noconstraints.sqlite`; the directory is created, and `benchmark_runs/databases/...` is used when `output_dir` is absent). The generated path needs `benchmark` and a `scale_factor` that is not `None`. With none of the three it raises `ConfigurationError` (`benchbox.core.exceptions`) with the two-line message `SQLite requires database path configuration.` followed by `Either pass --platform-option database_path=<path> or provide --benchmark and --scale.` `timeout` (default `30.0`) and `check_same_thread` (default `False`) are copied. `force_recreate` is true if any of `force_recreate`, `options['force_recreate']` or `force` is true. The tuning and verbosity keys (`tuning_config`, `tuning_enabled`, `unified_tuning_configuration`, `tuning_source`, `tuning_source_file`, `verbose_enabled`, `very_verbose`) pass through; other keys are dropped.

<span id="benchbox.platforms.sqlite.SQLiteAdapter.add_cli_arguments"></span>
**`add_cli_arguments(parser) -> None`** (static method): Adds three options to an `argparse` parser and returns `None`: `--sqlite-database` (stored as `database_path`, default `None`), `--sqlite-timeout` (float, stored as `timeout`, default `30.0`) and `--sqlite-check-same-thread` (flag, stored as `check_same_thread`, default `False`). Errors while adding them are swallowed.

<span id="benchbox.platforms.sqlite.SQLiteAdapter.get_database_path"></span>
**`get_database_path(**connection_config) -> str | None`**: Returns the database path. A `database_path` keyword that is not `None` wins; otherwise the instance's `database_path` is returned (`':memory:'` by default).

<span id="benchbox.platforms.sqlite.SQLiteAdapter.platform_name"></span>
**`platform_name`** (property): Always the string `'SQLite'`.

<span id="benchbox.platforms.sqlite.SQLiteAdapter.get_target_dialect"></span>
**`get_target_dialect() -> str`**: Returns `'sqlite'`, the SQL dialect BenchBox translates queries into.

<span id="benchbox.platforms.sqlite.SQLiteAdapter.get_platform_info"></span>
**`get_platform_info(connection: Any = None) -> dict[str, Any]`**: Returns a `dict`: `platform_type` (`'sqlite'`), `platform_name`, `connection_mode` (`'memory'` for `:memory:`, else `'file'`), `configuration` (`database_path`, `timeout`, `check_same_thread`), `client_library_version` (`'builtin'`) and `platform_version` (the SQLite library version of the Python build). The `connection` argument is accepted and not used.

#### Connection and schema

<span id="benchbox.platforms.sqlite.SQLiteAdapter.create_connection"></span>
**`create_connection(**connection_config) -> Any`**: Opens a `sqlite3` connection and returns it. Existing-database handling comes first: `force_recreate=True` deletes the file, and otherwise the file is validated and kept if it passes (`database_was_reused` becomes `True`). The connection uses the adapter's `timeout` and `check_same_thread` and runs `PRAGMA foreign_keys = ON`, `journal_mode = WAL`, `synchronous = NORMAL`, `cache_size = 10000` and `temp_store = MEMORY`. An in-memory database reports `journal_mode` `memory`, since WAL needs a file. It also registers SQL functions that SQLite lacks: `REGEXP_REPLACE(value, pattern, replacement)`, the aggregates `STDDEV` and `STDDEV_SAMP` (sample standard deviation) and the two-argument aggregate `PERCENTILE_CONT(fraction, value)`. Calling it registers a `sqlite3` adapter that stores `decimal.Decimal` values as `float`; this is process-wide. A bad `timeout` raises `TypeError` and an unusable path raises `sqlite3.OperationalError` (`unable to open database file`).

<span id="benchbox.platforms.sqlite.SQLiteAdapter.configure_for_benchmark"></span>
**`configure_for_benchmark(connection: Any, benchmark_type: str) -> None`**: Sets session pragmas for a benchmark type and returns `None`. The comparison is exact and lower-case: `'olap'` runs `PRAGMA query_only = false` and `PRAGMA read_uncommitted = true`; `'oltp'` runs `PRAGMA synchronous = FULL`. Any other value, including `'OLAP'` and `'tpch'`, changes nothing.

<span id="benchbox.platforms.sqlite.SQLiteAdapter.create_schema"></span>
**`create_schema(benchmark, connection: Any) -> float`**: Creates the benchmark's tables and returns the elapsed time in seconds (`float`). The benchmark's standard SQL DDL is translated to SQLite, run as one script and committed.

#### Loading data into tables

<span id="benchbox.platforms.sqlite.SQLiteAdapter.load_data"></span>
**`load_data(benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]`**: Loads the benchmark's generated files into the tables and returns `(table_row_counts, seconds, None)`; `table_row_counts` maps lower-case table names to row counts (TPC-H at scale factor 0.01 gives `customer` 1500, `lineitem` 60175). For TPC-H and Join Order it then builds helper indexes named `idx_bb_tpch_*` and `idx_bb_job_*`, and their time is included in `seconds`. Create the tables first with `create_schema`.

#### Query execution and plans

<span id="benchbox.platforms.sqlite.SQLiteAdapter.execute_query"></span>
**`execute_query(connection: Any, query: str, query_id: str, benchmark_type: str | None = None, scale_factor: float | None = None, validate_row_count: bool = True, stream_id: int | None = None) -> dict[str, Any]`**: Runs one query and returns a result `dict`; it does not raise for SQL errors. On success `status` is `'SUCCESS'` and the dict holds `query_id`, `execution_time_seconds`, `rows_returned`, `first_row` and `results` (every row, as a list of tuples). On an error `status` is `'FAILED'` with `error` (message), `error_type` (for example `'OperationalError'`), `execution_time_seconds` and `rows_returned` of `0`. When `benchmark_type` is given and `validate_row_count` is true, a row-count comparison is added to the result.

<span id="benchbox.platforms.sqlite.SQLiteAdapter.get_query_plan"></span>
**`get_query_plan(connection: Any, query: str) -> str | None`**: Returns the plan as text built from `EXPLAIN QUERY PLAN`: the line `QUERY PLAN` followed by an indented tree, for example `QUERY PLAN` then `` `--SCAN nation``. Returns `None` if the statement fails (for example for a missing table) or returns no rows.

<span id="benchbox.platforms.sqlite.SQLiteAdapter.get_query_plan_parser"></span>
**`get_query_plan_parser()`**: Returns a `SQLiteQueryPlanParser` (from `benchbox.core.query_plans.parsers.sqlite`) for the text that `get_query_plan` returns.

<span id="benchbox.platforms.sqlite.SQLiteAdapter.plan_capture_phase_eligible"></span>
**`plan_capture_phase_eligible`** (class attribute): `True`. Query plans for SQLite are captured in a separate pass after the timed run, not inline with the timed queries.

#### TPC test drivers

<span id="benchbox.platforms.sqlite.SQLiteAdapter.run_power_test"></span>
**`run_power_test(benchmark, **kwargs) -> dict[str, Any]`**: Always raises `NotImplementedError('Power test not implemented for SQLite adapter')`.

<span id="benchbox.platforms.sqlite.SQLiteAdapter.run_throughput_test"></span>
**`run_throughput_test(benchmark, **kwargs) -> dict[str, Any]`**: Always raises `NotImplementedError('Throughput test not implemented for SQLite adapter')`.

<span id="benchbox.platforms.sqlite.SQLiteAdapter.run_maintenance_test"></span>
**`run_maintenance_test(benchmark, **kwargs) -> dict[str, Any]`**: Always raises `NotImplementedError('Maintenance test not implemented for SQLite adapter')`.

#### Tuning

<span id="benchbox.platforms.sqlite.SQLiteAdapter.generate_tuning_clause"></span>
**`generate_tuning_clause(table_tuning: TableTuning) -> str`**: Returns `''` for every input. SQLite has no `CREATE TABLE` tuning syntax.

<span id="benchbox.platforms.sqlite.SQLiteAdapter.apply_table_tunings"></span>
**`apply_table_tunings(table_tuning: TableTuning, connection: Any) -> None`**: Does nothing and returns `None`: it issues no SQL for any `TableTuning`.

<span id="benchbox.platforms.sqlite.SQLiteAdapter.apply_unified_tuning"></span>
**`apply_unified_tuning(unified_config: UnifiedTuningConfiguration, connection: Any) -> None`**: Does nothing and returns `None`: it issues no SQL for any `UnifiedTuningConfiguration`.

<span id="benchbox.platforms.sqlite.SQLiteAdapter.apply_platform_optimizations"></span>
**`apply_platform_optimizations(platform_config: PlatformOptimizationConfiguration, connection: Any) -> None`**: Does nothing and returns `None`.

<span id="benchbox.platforms.sqlite.SQLiteAdapter.apply_constraint_configuration"></span>
**`apply_constraint_configuration(primary_key_config: PrimaryKeyConfiguration, foreign_key_config: ForeignKeyConfiguration, connection: Any) -> None`**: Switches foreign-key enforcement and returns `None`: it runs `PRAGMA foreign_keys = ON` when `foreign_key_config.enabled` is true and `PRAGMA foreign_keys = OFF` when it is false. `primary_key_config` is not used, and the call does nothing when `foreign_key_config` is `None`.

#### Capabilities

<span id="benchbox.platforms.sqlite.SQLiteAdapter.driver_isolation_capability"></span>
**`driver_isolation_capability`** (class attribute): `DriverIsolationCapability.NOT_APPLICABLE` (from `benchbox.platforms.base`): SQLite is part of the Python standard library, so there is no driver version to isolate.

<span id="benchbox.platforms.sqlite.SQLiteAdapter.stream_connection_capability"></span>
**`stream_connection_capability`** (read-only attribute): `StreamConnectionCapability.SHARED_CURSOR` (from `benchbox.platforms.base`), declared in the platform manifest rather than on the class: concurrent throughput streams use cursors of the one connection instead of opening more connections.

## Configuration Examples

### Development Testing

```python
# Fast in-memory testing for development
adapter = SQLiteAdapter(database_path=":memory:")

# Quick benchmark validation
from benchbox.tpch import TPCH
benchmark = TPCH(scale_factor=0.01)  # Tiny scale for speed
benchmark.generate_data()
results = benchmark.run_with_platform(adapter)

print(f"Validation complete in {results.total_execution_time:.2f}s")
```

### Persistent Storage

```python
from pathlib import Path

# Store results in file for later analysis
db_path = Path("./data/benchmarks.db")
db_path.parent.mkdir(parents=True, exist_ok=True)

adapter = SQLiteAdapter(
    database_path=str(db_path),
    timeout=60.0  # Longer timeout for file I/O
)
```

### CI/CD Pipeline

```python
import os
from benchbox.platforms.sqlite import SQLiteAdapter
from benchbox.tpch import TPCH

# Fast CI testing
if os.getenv("CI"):
    adapter = SQLiteAdapter(database_path=":memory:")
    benchmark = TPCH(scale_factor=0.01)
else:
    # Local development with larger dataset
    adapter = SQLiteAdapter(database_path="./dev_benchmark.db")
    benchmark = TPCH(scale_factor=0.1)

benchmark.generate_data()
results = benchmark.run_with_platform(adapter)

# Assert benchmark quality
assert results.successful_queries == results.total_queries
assert results.total_execution_time < 60.0  # CI time limit
```

### Multi-threaded Access

```python
# Enable for multi-threaded applications
adapter = SQLiteAdapter(
    database_path="./benchmark.db",
    check_same_thread=False,  # Allow access from multiple threads
    timeout=120.0  # Higher timeout for concurrent access
)
```

## Connection Management

### Basic Connection

```python
from benchbox.platforms.sqlite import SQLiteAdapter

adapter = SQLiteAdapter(database_path="./benchmark.db")

# Create connection
conn = adapter.create_connection()

# Connection is auto-configured with optimizations:
# - WAL journal mode
# - NORMAL synchronous mode
# - Foreign keys enabled
# - Cache size: 10000 pages
# - Temp storage: MEMORY
```

### Query Execution

```python
from benchbox.platforms.sqlite import SQLiteAdapter

adapter = SQLiteAdapter(database_path=":memory:")
conn = adapter.create_connection()

# A table to query (see Data Loading for loading benchmark tables)
conn.execute("CREATE TABLE customer (c_custkey INTEGER)")
conn.execute("INSERT INTO customer VALUES (1), (2)")

# Execute query
result = adapter.execute_query(
    conn,
    "SELECT COUNT(*) FROM customer",
    "count_customers"
)

print(f"Status: {result['status']}")
print(f"Execution time: {result['execution_time_seconds']:.3f}s")
print(f"Rows: {result['rows_returned']}")
```

On 0.4.1 this prints `Status: SUCCESS`, a time of a few milliseconds, and `Rows: 1`. If the query fails, `status` is `FAILED` and `result['error']` holds the message; `execute_query` does not raise.

## Data Loading

### From Generated Data

```python
from benchbox.platforms.sqlite import SQLiteAdapter
from benchbox.tpch import TPCH
from pathlib import Path

# Generate data
data_dir = Path("./tpch_data")
benchmark = TPCH(scale_factor=0.1, output_dir=data_dir)
benchmark.generate_data()

# Load into SQLite
adapter = SQLiteAdapter(database_path="./tpch.db")
conn = adapter.create_connection()

# Create schema
adapter.create_schema(benchmark, conn)

# Load data
table_stats, load_time, _ = adapter.load_data(benchmark, conn, data_dir)

print(f"Loaded {sum(table_stats.values()):,} rows in {load_time:.2f}s")
for table, count in table_stats.items():
    print(f"  {table}: {count:,} rows")
```

## Performance Optimization

### Connection Pragmas

SQLite adapter automatically applies these optimizations:

```sql
-- Write-Ahead Logging for better concurrency
PRAGMA journal_mode = WAL;

-- Normal durability (faster than FULL)
PRAGMA synchronous = NORMAL;

-- Large cache (10K pages) for reduced disk I/O
PRAGMA cache_size = 10000;

-- In-memory temp tables
PRAGMA temp_store = MEMORY;

-- Enable foreign key constraints
PRAGMA foreign_keys = ON;
```

### Query Optimization Tips

1. **Use appropriate indexes**:

   ```sql
   CREATE INDEX idx_orders_custkey ON orders(o_custkey);
   CREATE INDEX idx_lineitem_orderkey ON lineitem(l_orderkey);
   ```

2. **Analyze statistics after data load**:

   ```python
   conn.execute("ANALYZE")
   conn.commit()
   ```

3. **Vacuum to reclaim space and defragment**:

   ```python
   conn.execute("VACUUM")
   conn.commit()
   ```

### Scale Factor Guidelines

Recommended scale factors for SQLite:

- **Development/Testing**: SF = 0.01 to 0.1 (~10MB to 100MB)
- **CI/CD Pipelines**: SF = 0.01 (~10MB, completes in seconds)
- **Local benchmarking**: SF = 0.1 to 1.0 (~100MB to 1GB)
- **Maximum practical**: SF = 10 (~10GB, slow queries)

```{warning}
SQLite is not designed for large-scale OLAP workloads. Scale factors above 1.0 will result in slow query performance.
```

## Best Practices

### Use Case Selection

**When to use SQLite adapter**:

- Development and testing
- CI/CD pipeline validation
- Learning and education
- Small datasets (< 1GB)
- Single-user applications

**When NOT to use SQLite adapter**:

- Production benchmarking
- Large-scale data (> 10GB)
- Concurrent multi-user workloads
- Performance-critical comparisons

### Testing Strategy

```python
from benchbox.platforms.sqlite import SQLiteAdapter
from benchbox.tpch import TPCH

def test_benchmark_queries():
    """Test all benchmark queries for correctness."""
    adapter = SQLiteAdapter(database_path=":memory:")
    benchmark = TPCH(scale_factor=0.01)  # Small scale for speed
    benchmark.generate_data()

    results = benchmark.run_with_platform(adapter)

    # Validate all queries succeeded
    assert results.successful_queries == results.total_queries

    # Validate reasonable performance
    assert results.average_query_time < 1.0  # 1s per query at SF=0.01

    return results

# Run in test suite
test_benchmark_queries()
```

### Development Workflow

```python
from benchbox.platforms.sqlite import SQLiteAdapter

# 1. Start with in-memory for quick iterations
adapter = SQLiteAdapter(database_path=":memory:")

# 2. Validate query logic
# ... test queries ...

# 3. Move to file-based for persistent testing
adapter = SQLiteAdapter(database_path="./dev_test.db")

# 4. Graduate to production platform (DuckDB, ClickHouse, etc.)
```

### Resource Management

```python
from benchbox.platforms.sqlite import SQLiteAdapter

adapter = SQLiteAdapter(database_path="./benchmark.db")

try:
    conn = adapter.create_connection()
    # ... benchmark operations ...
finally:
    # Close connection
    conn.close()

    # Optional: Delete temporary database
    if adapter.database_path != ":memory:":
        import os
        if os.path.exists(adapter.database_path):
            os.remove(adapter.database_path)
```

## Common Issues

### Database Locked Error

**Problem**: "database is locked" error during concurrent access

**Solutions**:

```python
# 1. Increase timeout
adapter = SQLiteAdapter(
    database_path="./benchmark.db",
    timeout=120.0  # Wait up to 2 minutes
)

# 2. Use WAL mode (already enabled by default)
# WAL mode allows concurrent reads

# 3. Avoid concurrent writes
# SQLite only supports one writer at a time
```

### Memory Error

**Problem**: Out of memory with large datasets

**Solutions**:

```python
# 1. Use smaller scale factor
benchmark = TPCH(scale_factor=0.1)  # Not 1.0 or higher

# 2. Use file-based instead of in-memory
adapter = SQLiteAdapter(database_path="./benchmark.db")  # Not ":memory:"

# 3. Process data in chunks
# (Not directly supported; consider using DuckDB instead)
```

### Slow Query Performance

**Problem**: Queries take longer than expected

**Solutions**:

```python
# 1. Reduce scale factor
benchmark = TPCH(scale_factor=0.1)

# 2. Add indexes for common joins
conn.execute("CREATE INDEX idx_lineitem_orderkey ON lineitem(l_orderkey)")
conn.execute("ANALYZE")

# 3. Consider using DuckDB for analytical queries (columnar storage)
from benchbox.platforms.duckdb import DuckDBAdapter
adapter = DuckDBAdapter()  # Optimized for OLAP workloads
```

### Missing Tables

**Problem**: "no such table" error

**Solutions**:

```python
# 1. Ensure schema is created before data loading
adapter.create_schema(benchmark, conn)
adapter.load_data(benchmark, conn, data_dir)

# 2. Check if using existing database with old schema
adapter = SQLiteAdapter(
    database_path="./benchmark.db",
    force_recreate=True  # Delete the existing database file on connect
)
```

### Feature Not Supported

**Problem**: "Power test not implemented for SQLite adapter"

**Explanation**: `SQLiteAdapter.run_power_test`, `run_throughput_test` and `run_maintenance_test` always raise `NotImplementedError`.

**Solution**:

```python
# For the TPC power, throughput and maintenance tests, use another platform
from benchbox.platforms.duckdb import DuckDBAdapter
adapter = DuckDBAdapter()  # Does not override these tests with NotImplementedError
```

## See Also

### Platform Documentation

- {doc}`/platforms/platform-selection-guide` - Choosing SQLite vs other platforms
- {doc}`/platforms/quick-reference` - Quick setup for all platforms
- {doc}`/platforms/comparison-matrix` - Feature comparison

### API Reference

- {doc}`duckdb` - DuckDB adapter (recommended for OLAP testing)
- {doc}`clickhouse` - ClickHouse adapter
- {doc}`../base` - Base benchmark interface
- {doc}`../index` - Python API overview

### Benchmarks

- {doc}`/benchmarks/tpc-h` - TPC-H benchmark
- {doc}`/usage/getting-started` - Getting started guide
- {doc}`/usage/troubleshooting` - General troubleshooting

### External Resources

- [SQLite Documentation](https://www.sqlite.org/docs.html) - Official SQLite docs
- [SQLite Query Optimizer](https://sqlite.org/optoverview.html) - Performance guide
- [SQLite PRAGMA Statements](https://www.sqlite.org/pragma.html) - Configuration options
- [SQLite Limitations](https://www.sqlite.org/limits.html) - Size and performance limits
