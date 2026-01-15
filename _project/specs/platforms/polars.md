# Specification: PolarsAdapter

## Overview

Platform adapter for Polars, a high-performance DataFrame library implemented in Rust. Provides DataFrame-based data loading and table management for benchmark workloads, with support for lazy evaluation, streaming execution, and in-memory OLAP processing.

**Note**: SQL mode has been removed due to fundamental limitations in Polars' SQL implementation (no implicit joins, limited subquery support, etc.) that make it incompatible with standard TPC benchmarks. For SQL benchmarks, use `duckdb` or `postgresql`. For Polars benchmarks, use the `polars-df` platform with DataFrame API.

## Location

**File**: `benchbox/platforms/polars_platform.py` | **Module**: `benchbox.platforms.polars_platform` | **Lines**: 1-740

## Public Interface

### `PolarsDataFrameContext`

Context for Polars DataFrame operations providing table storage and retrieval. SQL execution is not supported.

**Inheritance**: None (standalone class)

**Attributes**:

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| `_adapter` | `PolarsAdapter` | Parent adapter instance | Required |
| `_tables` | `dict[str, pl.LazyFrame]` | Registered tables mapping | `{}` |

**Methods**:

| Method | Signature | Description |
| ------ | --------- | ----------- |
| `__init__` | `(adapter: PolarsAdapter) -> None` | Initialize with parent adapter |
| `register_table` | `(name: str, df: pl.LazyFrame \| pl.DataFrame) -> None` | Register table in context |
| `unregister_table` | `(name: str) -> None` | Remove table from context |
| `get_table` | `(name: str) -> pl.LazyFrame \| None` | Get table by name |
| `get_tables` | `() -> list[str]` | List registered table names |

---

### `PolarsAdapter`

Platform adapter providing Polars-specific optimizations for in-memory OLAP benchmark workloads. DataFrame-only execution mode.

**Inheritance**: `PlatformAdapter` -> `PolarsAdapter`

**Attributes**:

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| `working_dir` | `Path` | Directory for Polars data files | `./polars_working` |
| `execution_mode` | `str` | Execution strategy: "lazy" or "eager" | `"lazy"` |
| `streaming` | `bool` | Enable streaming for large datasets | `False` |
| `n_rows` | `int \| None` | Row limit for testing | `None` |
| `rechunk` | `bool` | Rechunk data for memory layout | `True` |
| `_table_schemas` | `dict[str, dict]` | Schema definitions by table | `{}` |

**Methods**:

| Method | Signature | Description |
| ------ | --------- | ----------- |
| `platform_name` | Property | Returns "Polars" |
| `get_target_dialect` | `() -> str` | Returns "dataframe" |
| `add_cli_arguments` | `(parser) -> None` | Add Polars CLI options |
| `from_config` | `(config: dict) -> PolarsAdapter` | Factory from configuration |
| `__init__` | `(**config) -> None` | Initialize adapter with options |
| `get_platform_info` | `(connection) -> dict` | Get runtime information |
| `create_connection` | `(**config) -> PolarsDataFrameContext` | Create DataFrame context |
| `create_schema` | `(benchmark, connection) -> float` | Validate schema definitions |
| `load_data` | `(benchmark, connection, data_dir) -> tuple` | Load data into context |
| `configure_for_benchmark` | `(connection, benchmark_type) -> None` | Apply benchmark optimizations |
| `execute_query` | `(...) -> Never` | **Raises NotImplementedError** (SQL not supported) |
| `apply_platform_optimizations` | `(platform_config, connection) -> None` | Apply performance tuning |
| `apply_constraint_configuration` | `(pk_config, fk_config, connection) -> None` | Handle constraint config |
| `check_database_exists` | `(**config) -> bool` | Check for existing data |
| `drop_database` | `(**config) -> None` | Remove working directory |
| `validate_platform_capabilities` | `(benchmark_type) -> ValidationResult` | Validate platform support |

---

### `platform_name` (Property)

Get the platform display name.

**Returns**: `str` - "Polars"

---

### `get_target_dialect() -> str`

Get the target dialect identifier.

**Parameters**: None

**Returns**: `str` - "dataframe" (Polars uses DataFrame API, not SQL)

---

### `add_cli_arguments(parser) -> None` (Static)

Add Polars-specific CLI arguments to the argument parser.

**Parameters**:
- `parser`: argparse.ArgumentParser instance

**Returns**: None

**CLI Arguments Added**:

| Argument | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `--polars-execution-mode` | choice | `lazy` | Execution mode: lazy or eager |
| `--polars-streaming` | flag | `False` | Enable streaming for large datasets |
| `--polars-n-rows` | int | `None` | Limit rows to read (testing) |
| `--polars-working-dir` | str | Auto | Working directory for data files |
| `--polars-rechunk` | flag | `True` | Rechunk for better memory layout |

---

### `from_config(config: dict[str, Any]) -> PolarsAdapter` (Class Method)

Create adapter instance from unified configuration dictionary.

**Parameters**:
- `config` (dict): Configuration with keys:
  - `working_dir` (str, optional): Working directory path
  - `output_dir` (str, optional): Output directory for data
  - `benchmark` (str): Benchmark name
  - `scale_factor` (float): Scale factor
  - `execution_mode` (str, optional): "lazy" or "eager"
  - `streaming` (bool, optional): Enable streaming
  - `n_rows` (int, optional): Row limit
  - `rechunk` (bool, optional): Enable rechunking
  - `force` (bool, optional): Force recreate
  - `tuning_config` (dict, optional): Tuning configuration

**Returns**: Configured `PolarsAdapter` instance

**Behavior**:
- Determines working directory from config or generates canonical path
- Creates working directory if needed
- Passes through tuning and verbosity settings

---

### `__init__(**config) -> None`

Initialize the Polars adapter.

**Parameters**:
- `**config`: Configuration options:
  - `working_dir` (str | Path): Working directory
  - `execution_mode` (str): "lazy" or "eager"
  - `streaming` (bool): Enable streaming mode
  - `n_rows` (int | None): Row limit for testing
  - `rechunk` (bool): Enable data rechunking
  - Plus inherited `PlatformAdapter` options

**Returns**: None

**Raises**:
- `ImportError`: If Polars library is not installed

**Side Effects**:
- Creates working directory
- Enables Polars string cache globally

---

### `get_platform_info(connection: Any = None) -> dict[str, Any]`

Get Polars platform information and configuration.

**Parameters**:
- `connection`: Optional connection (not used)

**Returns**: Dictionary containing:
- `platform_type`: "polars"
- `platform_name`: "Polars"
- `connection_mode`: "in-memory"
- `client_library_version`: Polars version
- `platform_version`: Polars version
- `configuration`: Dict with working_dir, execution_mode, streaming, etc.

---

### `create_connection(**connection_config) -> PolarsDataFrameContext`

Create a Polars DataFrame context for table storage.

**Parameters**:
- `**connection_config`: Connection options (passed to handle_existing_database)

**Returns**: `PolarsDataFrameContext` wrapper instance

**Side Effects**:
- Enables Polars string cache
- Logs configuration details
- May drop existing database if force_recreate is set

**Behavior**:
1. Handles existing database check/recreation
2. Configures global Polars settings
3. Creates and returns DataFrame context wrapper

---

### `create_schema(benchmark, connection: Any) -> float`

Validate and extract schema information from benchmark.

**Parameters**:
- `benchmark`: Benchmark instance with `get_schema()` method
- `connection`: PolarsDataFrameContext (not modified)

**Returns**: Duration in seconds

**Behavior**:
- Extracts schema from benchmark's `get_schema()` method
- Stores column definitions in `_table_schemas`
- Notes that Polars does not enforce constraints (PKs, FKs)
- Actual table registration occurs during `load_data()`

---

### `load_data(benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]`

Load benchmark data into Polars using lazy scanning.

**Parameters**:
- `benchmark`: Benchmark instance
- `connection`: PolarsDataFrameContext for table registration
- `data_dir`: Directory containing data files

**Returns**: Tuple of:
- `table_stats`: Dict mapping table name to row count
- `duration`: Total loading time in seconds
- `per_table_timings`: Dict with per-table timing details

**Raises**:
- `ValueError`: If no data files found

**Behavior**:
1. Resolves data source using `DataSourceResolver`
2. Detects file format (Parquet, CSV, TBL)
3. Loads each table with appropriate scan method
4. Registers tables in DataFrame context
5. Uses lazy evaluation for memory efficiency

**Supported Formats**:
- Parquet (optimal performance)
- CSV with configurable delimiter
- TBL files with trailing delimiter handling

---

### `configure_for_benchmark(connection: Any, benchmark_type: str) -> None`

Apply Polars-specific optimizations for benchmark type.

**Parameters**:
- `connection`: PolarsDataFrameContext
- `benchmark_type`: Benchmark identifier (e.g., "tpch", "tpcds")

**Returns**: None

**Behavior**: Logs configuration; optimizations are automatic via Polars query optimizer

---

### `execute_query(...) -> Never`

**SQL execution is not supported.**

This method always raises `NotImplementedError` with guidance to use:
- `polars-df` platform for DataFrame API execution
- `duckdb` or `postgresql` for SQL benchmarks

**Raises**: `NotImplementedError` - Always

**Rationale**: Polars' SQL implementation has fundamental limitations:
- No implicit joins (`FROM a, b WHERE ...` syntax)
- Limited subquery support (no EXISTS, scalar comparisons)
- Non-equi join constraints not supported
- These make TPC-H (0/22), TPC-DS (0/99), and SSB (0/13) benchmarks incompatible

---

### `apply_platform_optimizations(platform_config, connection: Any) -> None`

Apply platform-specific optimizations.

**Parameters**:
- `platform_config`: Optimization configuration
- `connection`: PolarsDataFrameContext

**Returns**: None

**Behavior**: Logs that Polars optimizations are handled automatically by query optimizer

---

### `apply_constraint_configuration(primary_key_config, foreign_key_config, connection: Any) -> None`

Handle constraint configuration requests.

**Parameters**:
- `primary_key_config`: Primary key configuration
- `foreign_key_config`: Foreign key configuration
- `connection`: PolarsDataFrameContext

**Returns**: None

**Behavior**: Logs that Polars does not enforce constraints; configuration is noted but not applied

---

### `check_database_exists(**connection_config) -> bool`

Check if Polars working directory contains data.

**Parameters**:
- `**connection_config`: May include `working_dir`

**Returns**: `bool` - True if directory exists with Parquet or CSV files

---

### `drop_database(**connection_config) -> None`

Remove Polars working directory and all data.

**Parameters**:
- `**connection_config`: May include `working_dir`

**Returns**: None

**Side Effects**: Recursively deletes working directory

---

### `validate_platform_capabilities(benchmark_type: str) -> ValidationResult`

Validate Polars capabilities for the specified benchmark.

**Parameters**:
- `benchmark_type` (str): Benchmark identifier

**Returns**: `ValidationResult` with validation status

**Validation Checks**:
- Polars library availability
- Polars version (warns if < 0.20)
- **Always warns that SQL mode is not available**

**Details Returned**:
- `sql_mode`: False (always)
- `polars_available`: bool
- `polars_version`: string

---

## Dependencies

| Package/Module | Purpose |
| -------------- | ------- |
| `polars` | Core DataFrame library (optional import) |
| `benchbox.platforms.base.PlatformAdapter` | Base adapter interface |
| `benchbox.platforms.base.data_loading.DataSourceResolver` | Data file resolution |
| `benchbox.platforms.base.utils.detect_file_format` | File format detection |
| `benchbox.core.validation.ValidationResult` | Validation result type |
| `benchbox.utils.database_naming` | Database filename generation |
| `benchbox.utils.scale_factor` | Scale factor formatting |
| `benchbox.utils.path_utils` | Benchmark path utilities |

## Configuration

| Parameter | Type | Default | Required |
| --------- | ---- | ------- | -------- |
| `working_dir` | Path | `./polars_working` | No |
| `execution_mode` | str | `lazy` | No |
| `streaming` | bool | `False` | No |
| `n_rows` | int | `None` | No |
| `rechunk` | bool | `True` | No |

## Platform Registry

```python
"polars": {
    "display_name": "Polars",
    "description": "DataFrame engine • In-memory • Columnar",
    "capabilities": {
        "supports_sql": False,
        "supports_dataframe": True,
        "default_mode": "dataframe"
    },
}
```

## Environment Variables

None directly consumed. Uses standard Polars environment variables if set (e.g., `POLARS_MAX_THREADS`).

## Behavior Specification

**Preconditions**:
- Polars library must be installed
- Data files must exist in expected format for loading
- Benchmark must provide schema via `get_schema()` for optimal loading

**Postconditions**:
- After `create_connection()`: DataFrame context ready for table operations
- After `load_data()`: All tables registered and accessible via `get_table()`
- After `execute_query()`: **NotImplementedError raised** (SQL not supported)

**Invariants**:
- DataFrame context remains valid throughout session
- String cache enabled for consistent categorical handling
- Lazy execution used unless explicitly configured otherwise
- SQL execution never succeeds (always raises NotImplementedError)

**Side Effects**:
- `create_connection()`: Modifies global Polars string cache setting
- `load_data()`: Registers tables in DataFrame context
- `drop_database()`: Deletes filesystem directory

## Error Handling

| Exception | Condition | Recovery |
| --------- | --------- | -------- |
| `ImportError` | Polars not installed | Install with `pip install polars` |
| `ValueError` | No data files found | Ensure data generation completed |
| `NotImplementedError` | SQL execution attempted | Use `polars-df` for DataFrame API or `duckdb` for SQL |
| `FileNotFoundError` | Data file missing | Regenerate data files |

## Examples

```python
from benchbox.platforms.polars_platform import PolarsAdapter, PolarsDataFrameContext

# Create adapter with default settings
adapter = PolarsAdapter(working_dir="./benchmark_data")

# Create with lazy execution (recommended)
adapter = PolarsAdapter(
    working_dir="./data",
    execution_mode="lazy",
    streaming=False,
    rechunk=True
)

# Create DataFrame context and load data
ctx = adapter.create_connection()
# After loading data via benchmark...

# Access tables via DataFrame API
lineitem_lf = ctx.get_table("lineitem")
if lineitem_lf is not None:
    # Perform DataFrame operations
    result = lineitem_lf.filter(pl.col("l_quantity") > 25).collect()

# SQL execution will raise NotImplementedError
try:
    adapter.execute_query(ctx, "SELECT * FROM lineitem", "Q1")
except NotImplementedError as e:
    print(f"Expected: {e}")
    # Use polars-df platform for DataFrame API execution instead
```

## Recommended Usage

For TPC benchmarks with Polars, use the DataFrame adapter instead:

```bash
# DataFrame API (recommended for Polars)
benchbox run --platform polars-df --benchmark tpch --scale 0.1

# SQL benchmarks should use SQL-native platforms
benchbox run --platform duckdb --benchmark tpch --scale 0.1
```

## Notes

- **SQL mode has been removed** due to fundamental Polars SQL limitations
- Polars SQL cannot handle: implicit joins, EXISTS subqueries, scalar subquery comparisons, non-equi joins
- This makes 0/22 TPC-H, 0/99 TPC-DS, and 0/13 SSB queries viable in SQL mode
- Use `polars-df` platform for DataFrame API execution (full benchmark support)
- Lazy execution mode is recommended for memory efficiency
- Streaming mode helps with datasets larger than available RAM
- Polars does not enforce PRIMARY KEY or FOREIGN KEY constraints
- Query optimization is automatic; no manual tuning required
- Thread safety: Polars handles parallelism internally; adapter is not thread-safe
- Rechunking improves memory layout but adds initial overhead
