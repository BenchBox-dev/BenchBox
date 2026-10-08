# Write Primitives Benchmark API

```{tags} reference, python-api, custom-benchmark
```

Python API reference for the Write Primitives Benchmark.

## Overview

The Write Primitives benchmark tests fundamental database write operations using the TPC-H schema as foundation. It covers INSERT, UPDATE, DELETE, BULK_LOAD, MERGE and DDL operations with automatic validation and cleanup.

**Key Features**:

- **Data Sharing**: Reuses TPC-H data (no duplicate generation)
- **Catalog-Driven**: Operations defined in a YAML catalog
- **112 Operations**: In 6 categories (`bulk_load` 36, `merge` 23, `update` 15, `delete` 14, `insert` 12, `ddl` 12)
- **Automatic Validation**: Every write is checked with read queries
- **Lifecycle Management**: Setup, reset, teardown, status checking
- **Extensible**: Operations are added to the catalog

Transaction operations are not part of this benchmark in 0.4.1; they moved to the transaction primitives benchmark.

## Quick Start

```python
from benchbox import TPCH, WritePrimitives
from benchbox.platforms.duckdb import DuckDBAdapter

tpch = TPCH(scale_factor=0.01)
tpch.generate_data()

adapter = DuckDBAdapter()
conn = adapter.create_connection()
adapter.create_schema(tpch, conn)
adapter.load_data(tpch, conn, tpch.output_dir)

bench = WritePrimitives(scale_factor=0.01)
bench.generate_data()
bench.setup(conn)

result = bench.execute_operation("insert_single_row", conn)
print(f"Success: {result.success}, Time: {result.write_duration_ms:.2f}ms")
```

Load the TPC-H data first; it is required. Then set up Write Primitives and execute operations. `generate_data()` adds the files that the bulk-load operations read.

Load the TPC-H tables into the database before calling `WritePrimitives.generate_data()`: it writes two extra files (`orders_stage.tbl`, `lineitem_stage.tbl`) into the TPC-H directory, and a later `adapter.load_data(tpch, ...)` call from that directory tries to load them and reports errors. The DuckDB adapter needs the `duckdb` package.

## API Reference

### WritePrimitives Class

#### `benchbox.WritePrimitives`

<span id="benchbox.write_primitives.WritePrimitives"></span>

Creates a Write Primitives benchmark that runs 112 write operations against staging tables copied from loaded TPC-H tables, and validates each one.

**Import:** `from benchbox import WritePrimitives` · **Extras:** none

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `scale_factor` | `float` | `1.0` | TPC-H scale factor; use the one of the TPC-H data in the database. Must be positive. Values of 1 or more must be whole numbers. |
| `output_dir` | `str`, `Path` or `None` | `None` | Directory for generated data files. When `None`, the TPC-H directory `benchmark_runs/datagen/tpch_<sf token>` under the current directory (for example `tpch_sf001` for 0.01), or under `$BENCHBOX_OUTPUT_DIR/datagen`, so data is shared with a `TPCH` benchmark of the same scale factor. |
| `**kwargs` | keyword arguments | none | `verbose` (`bool` or `int`) and `quiet` (`bool`) set the log level. Other keywords are stored as attributes. |

The constructor creates no files and does not touch a database.

##### Returns

A `WritePrimitives` instance. It subclasses `BaseBenchmark`; see {doc}`/reference/python-api/base` for the shared interface.

##### Raises

`ValueError` when `scale_factor` is zero or negative, or is 1 or more and not a whole number.

##### Example

```python
from benchbox import WritePrimitives

bench = WritePrimitives(scale_factor=0.01)
print(len(bench.get_all_operations()), bench.get_operation_categories())
print(bench.get_data_source_benchmark())
```

Output on 0.4.1:

```text
112 ['bulk_load', 'ddl', 'delete', 'insert', 'merge', 'update']
tpch
```

##### Compatibility

`benchbox.write_primitives.WritePrimitives` is the same class. The class attribute `DATA_SOURCE_BENCHMARK` is `None`; `get_data_source_benchmark()` returns `"tpch"`. `get_query_categories()` raises `AttributeError` on 0.4.1; use `get_operation_categories()`.

### Constructor

<span id="benchbox.write_primitives.WritePrimitives.__init__"></span>

`WritePrimitives(scale_factor=1.0, output_dir=None, **kwargs)`. The arguments are in the Parameters table above.

### Data Methods

#### `generate_data(tables=None)`

<span id="benchbox.write_primitives.WritePrimitives.generate_data"></span>

`generate_data(tables=None) -> list` generates (or reuses) the TPC-H files in `output_dir` and the files that the bulk-load operations read, and returns 10 paths: the eight TPC-H `.tbl` files plus `orders_stage.tbl` and `lineitem_stage.tbl`. The bulk-load files (CSV, pipe-separated and compressed variants, about 14 MB at scale factor 0.01) go to a `write_primitives_auxiliary` subdirectory. `tables` is an optional list of table names. `benchmark.tables` is a `dict` of the same 10 paths.

Without these files the 36 `bulk_load` operations are skipped (see `OperationResult` below).

#### `tables`

<span id="benchbox.write_primitives.WritePrimitives.tables"></span>

`tables` is a `dict` mapping table name to data file path. It is empty until `generate_data()` has run.

### Lifecycle Methods

#### `setup(connection, force=False)`

<span id="benchbox.write_primitives.WritePrimitives.setup"></span>

`setup(connection, force=False) -> dict` creates the staging tables and fills them from the loaded TPC-H tables.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `connection` | database connection | required | Connection that already holds the TPC-H tables. |
| `force` | `bool` | `False` | When true, drop existing staging tables first. |

Returns a dict with `success`, `tables_created` (18 staging table names) and `table_row_counts`. Calling it again on a set-up database also succeeds. It additionally creates two bookkeeping tables, `benchbox_staging_manifest_v2` and `write_primitives_setup_lock`.

Raises `RuntimeError` when a TPC-H table is missing (`Required TPC-H table 'orders' not found. Please load TPC-H data first ...`).

```python
setup_result = bench.setup(conn, force=True)
print(f"Tables created: {len(setup_result['tables_created'])}")
print(f"Rows: {setup_result['table_row_counts']['delete_ops_lineitem']}")
```

The example prints `Tables created: 18` and `Rows: 60175`.

#### `is_setup(connection)`

<span id="benchbox.write_primitives.WritePrimitives.is_setup"></span>

`is_setup(connection) -> bool` is true when all staging tables exist and hold data.

```python
if bench.is_setup(conn):
    print("Ready to execute operations")
```

#### `reset(connection)`

<span id="benchbox.write_primitives.WritePrimitives.reset"></span>

`reset(connection) -> None` truncates and refills the staging tables from the TPC-H tables (about 0.6 s at scale factor 0.01). Reset after validation failures.

```python
bench.reset(conn)
```

#### `teardown(connection)`

<span id="benchbox.write_primitives.WritePrimitives.teardown"></span>

`teardown(connection) -> None` drops the staging tables; `is_setup()` is then false. The two bookkeeping tables stay. Call it when you are done.

```python
bench.teardown(conn)
```

#### `load_data(connection, **kwargs)`

<span id="benchbox.write_primitives.WritePrimitives.load_data"></span>

`load_data(connection, **kwargs) -> dict` is the entry point that platform adapters call; it runs `setup()` (a `force` keyword is passed through) and returns the same kind of dict. Call `setup()` directly in your own code.

### Operation Execution Methods

#### `execute_operation(operation_id, connection, **kwargs)`

<span id="benchbox.write_primitives.WritePrimitives.execute_operation"></span>

`execute_operation(operation_id, connection, **kwargs) -> OperationResult` runs one operation, validates it with its read queries, and runs its cleanup SQL.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `operation_id` | `str` | required | An id such as `"insert_single_row"`. |
| `connection` | database connection | required | Connection with the TPC-H and staging tables. |
| `platform_key` (keyword) | `str` | derived | Platform dialect key such as `"duckdb"`, used to pick platform-specific SQL. |
| `sql_override` (keyword) | `str` | none | SQL to run in place of the operation's write SQL. |

Other keywords, including the old `use_transaction`, are accepted and ignored: Write Primitives does not use transaction-based cleanup. If the staging tables are missing, the first call sets them up.

Raises `ValueError` for an unknown operation id (`Invalid operation ID: bogus. Available: ...`). Failures inside the operation are returned, not raised: a failed write gives `status="FAILED"` with `error` set, and a failed validation gives `status="VALIDATION_FAILED"`.

```python
result = bench.execute_operation("insert_single_row", conn)
print(f"Operation: {result.operation_id}")
print(f"Success: {result.success}")
print(f"Rows affected: {result.rows_affected}")
print(f"Write time: {result.write_duration_ms:.2f}ms")
print(f"Validation: {result.validation_passed}")
```

#### `run_benchmark(connection, operation_ids=None, categories=None)`

<span id="benchbox.write_primitives.WritePrimitives.run_benchmark"></span>

`run_benchmark(connection, operation_ids=None, categories=None) -> list[OperationResult]` runs several operations in catalog order and returns one result per operation.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `connection` | database connection | required | Connection with the TPC-H and staging tables. |
| `operation_ids` | `list[str]` or `None` | `None` | Operations to run. `None` runs all 112. An unknown id raises `ValueError`. |
| `categories` | `list[str]` or `None` | `None` | Categories to run (`"insert"`, `"update"`, `"delete"`, `"ddl"`, `"bulk_load"`, `"merge"`). An unknown category contributes no operations; if no operation remains the result is `[]`. |

With a set-up database and `generate_data()` run, all 112 operations return `SUCCESS` at scale factor 0.01 on DuckDB, in about 1.4 seconds.

The example runs all operations, then only the INSERT operations, then two specific operations.

```python
results = bench.run_benchmark(conn)

insert_results = bench.run_benchmark(conn, categories=["insert"])

specific_ops = ["insert_single_row", "update_single_row_pk"]
results = bench.run_benchmark(conn, operation_ids=specific_ops)
print(len(results))
```

The last statement prints `2`.

### Operation Query Methods

#### `get_all_operations()`

<span id="benchbox.write_primitives.WritePrimitives.get_all_operations"></span>

`get_all_operations() -> dict[str, WriteOperation]` returns all 112 operations keyed by id. Each `WriteOperation` has `id`, `category`, `description`, `write_sql`, `validation_queries`, `cleanup_sql`, `expected_rows_affected`, `file_dependencies`, `platform_overrides`, `requires_setup` and `aggregate_state`.

```python
operations = bench.get_all_operations()
print(f"Total operations: {len(operations)}")
```

The example prints `Total operations: 112`.

#### `get_operation(operation_id)`

<span id="benchbox.write_primitives.WritePrimitives.get_operation"></span>

`get_operation(operation_id) -> WriteOperation` returns one operation. Raises `ValueError` for an unknown id.

```python
op = bench.get_operation("insert_single_row")
print(f"Category: {op.category}")
```

The example prints `Category: insert`.

#### `get_operations_by_category(category)`

<span id="benchbox.write_primitives.WritePrimitives.get_operations_by_category"></span>

`get_operations_by_category(category) -> dict[str, WriteOperation]` returns the operations in one category. An unknown category returns `{}`.

```python
insert_ops = bench.get_operations_by_category("insert")
print(f"INSERT operations: {len(insert_ops)}")
```

The example prints `INSERT operations: 12`.

#### `get_operation_categories()`

<span id="benchbox.write_primitives.WritePrimitives.get_operation_categories"></span>

`get_operation_categories() -> list[str]` returns the category names in alphabetical order.

```python
categories = bench.get_operation_categories()
```

The result is `['bulk_load', 'ddl', 'delete', 'insert', 'merge', 'update']`.

#### `get_queries(dialect=None)`

<span id="benchbox.write_primitives.WritePrimitives.get_queries"></span>

`get_queries(dialect=None) -> dict[str, str]` returns the write SQL of all 112 operations keyed by operation id. With a `dialect`, the SQL is translated.

```python
queries = bench.get_queries()
print(queries["insert_single_row"])
```

#### `get_query(query_id, **kwargs)`

<span id="benchbox.write_primitives.WritePrimitives.get_query"></span>

`get_query(query_id, **kwargs) -> str` returns the write SQL of one operation. Raises `ValueError` for an unknown id.

```python
sql = bench.get_query("insert_single_row")
```

#### `get_queries_by_category(category)`

<span id="benchbox.write_primitives.WritePrimitives.get_queries_by_category"></span>

`get_queries_by_category(category) -> dict[str, str]` returns the write SQL for one category, keyed by operation id. An unknown category returns `{}`.

### Schema Methods

#### `get_schema(dialect="standard")`

<span id="benchbox.write_primitives.WritePrimitives.get_schema"></span>

`get_schema(dialect="standard") -> dict[str, dict]` returns a mapping from table name to a definition with `name` and `columns`, for 26 tables: the eight TPC-H tables and the staging tables. `dialect` has no effect on the result.

```python
schema = bench.get_schema(dialect="duckdb")
for table, definition in list(schema.items())[:3]:
    print(f"{table}: {len(definition['columns'])} columns")
```

The example prints `region: 3 columns`, `nation: 4 columns` and `customer: 8 columns`.

#### `get_create_tables_sql(dialect="standard", tuning_config=None)`

<span id="benchbox.write_primitives.WritePrimitives.get_create_tables_sql"></span>

`get_create_tables_sql(dialect="standard", tuning_config=None) -> str` returns the `CREATE TABLE` statements for the TPC-H tables and the staging tables (28 statements). `dialect` has no effect on the text.

```python
create_sql = bench.get_create_tables_sql(dialect="postgres")
print(create_sql.count("CREATE TABLE"))
```

The example prints `28`.

#### `get_benchmark_info()`

<span id="benchbox.write_primitives.WritePrimitives.get_benchmark_info"></span>

`get_benchmark_info() -> dict` returns `name` (`"Write Primitives Benchmark"`), `version`, `description`, `scale_factor`, `total_operations` (112), `categories`, `tables` (the 18 staging table names) and `data_source` (`"tpch"`).

```python
info = bench.get_benchmark_info()
print(info["total_operations"], info["data_source"])
```

The example prints `112 tpch`.

### OperationResult Class

Result object returned by `execute_operation` and `run_benchmark`. It is a dataclass, `benchbox.core.write_primitives.benchmark.OperationResult` (not one of the listed public symbols).

**Fields**:

- **operation_id** (str): Operation identifier
- **success** (bool): Whether the operation succeeded and validated
- **write_duration_ms** (float): Write execution time in milliseconds
- **rows_affected** (int): Number of rows affected (`-1` if the database does not report it, as DuckDB does not)
- **validation_duration_ms** (float): Validation time in milliseconds
- **validation_passed** (bool): Whether all validation queries passed
- **validation_results** (list[dict]): One dict per validation query with `query_id`, `sql`, `expected_rows`, `actual_rows`, `passed` and `sample`
- **cleanup_duration_ms** (float): Cleanup time in milliseconds
- **cleanup_success** (bool): Whether cleanup succeeded
- **status** (str): `"SUCCESS"`, `"VALIDATION_FAILED"`, `"FAILED"` or `"SKIPPED"`
- **error** (str | None): Error message if the operation failed
- **cleanup_warning** (str | None): Warning for cleanup failures
- **skip_reason** (str | None): Why a `SKIPPED` operation did not run. A skipped operation has `success=True`, `rows_affected=0` and zero durations; the 36 bulk-load operations are skipped with `required bulk-load files are missing` until `generate_data()` has run.
- **executed_sql** (str): The write SQL that was run, after platform overrides and placeholder replacement

### Inherited members

Every other member comes from `BaseBenchmark`. See {doc}`/reference/python-api/base` for what they do. The ids on this page for the inherited members are kept in the table.

| Group | Member | Kind | Notes |
| --- | --- | --- | --- |
| Run and results | <span id="benchbox.write_primitives.WritePrimitives.cleanup"></span>`cleanup` | method | |
| Run and results | <span id="benchbox.write_primitives.WritePrimitives.create_enhanced_benchmark_result"></span>`create_enhanced_benchmark_result` | method | |
| Run and results | <span id="benchbox.write_primitives.WritePrimitives.create_minimal_benchmark_result"></span>`create_minimal_benchmark_result` | method | |
| Run and results | <span id="benchbox.write_primitives.WritePrimitives.format_results"></span>`format_results` | method | |
| Run and results | <span id="benchbox.write_primitives.WritePrimitives.run_query"></span>`run_query` | method | |
| Run and results | <span id="benchbox.write_primitives.WritePrimitives.run_with_platform"></span>`run_with_platform` | method | |
| Run and results | <span id="benchbox.write_primitives.WritePrimitives.setup_database"></span>`setup_database` | method | |
| Run and results | <span id="benchbox.write_primitives.WritePrimitives.translate_query"></span>`translate_query` | method | |
| Validation | <span id="benchbox.write_primitives.WritePrimitives.validate_loaded_data"></span>`validate_loaded_data` | method | |
| Validation | <span id="benchbox.write_primitives.WritePrimitives.validate_manifest"></span>`validate_manifest` | method | |
| Validation | <span id="benchbox.write_primitives.WritePrimitives.validate_preflight"></span>`validate_preflight` | method | |
| Verbosity and logging | <span id="benchbox.write_primitives.WritePrimitives.apply_verbosity"></span>`apply_verbosity` | method | |
| Verbosity and logging | <span id="benchbox.write_primitives.WritePrimitives.log_debug_info"></span>`log_debug_info` | method | |
| Verbosity and logging | <span id="benchbox.write_primitives.WritePrimitives.log_error_with_debug_info"></span>`log_error_with_debug_info` | method | |
| Verbosity and logging | <span id="benchbox.write_primitives.WritePrimitives.log_notice"></span>`log_notice` | method | |
| Verbosity and logging | <span id="benchbox.write_primitives.WritePrimitives.log_operation_complete"></span>`log_operation_complete` | method | |
| Verbosity and logging | <span id="benchbox.write_primitives.WritePrimitives.log_operation_start"></span>`log_operation_start` | method | |
| Verbosity and logging | <span id="benchbox.write_primitives.WritePrimitives.log_verbose"></span>`log_verbose` | method | |
| Verbosity and logging | <span id="benchbox.write_primitives.WritePrimitives.log_version_warning"></span>`log_version_warning` | method | |
| Verbosity and logging | <span id="benchbox.write_primitives.WritePrimitives.log_very_verbose"></span>`log_very_verbose` | method | |
| Verbosity and logging | <span id="benchbox.write_primitives.WritePrimitives.logger"></span>`logger` | property | |
| Verbosity and logging | <span id="benchbox.write_primitives.WritePrimitives.quiet"></span>`quiet` | class attribute | |
| Verbosity and logging | <span id="benchbox.write_primitives.WritePrimitives.verbose"></span>`verbose` | class attribute | |
| Verbosity and logging | <span id="benchbox.write_primitives.WritePrimitives.verbose_enabled"></span>`verbose_enabled` | class attribute | |
| Verbosity and logging | <span id="benchbox.write_primitives.WritePrimitives.verbose_level"></span>`verbose_level` | class attribute | |
| Verbosity and logging | <span id="benchbox.write_primitives.WritePrimitives.verbosity_settings"></span>`verbosity_settings` | property | |
| Verbosity and logging | <span id="benchbox.write_primitives.WritePrimitives.very_verbose"></span>`very_verbose` | class attribute | |
| Data and configuration | <span id="benchbox.write_primitives.WritePrimitives.api_surface"></span>`api_surface` | class attribute | |
| Data and configuration | <span id="benchbox.write_primitives.WritePrimitives.benchmark_name"></span>`benchmark_name` | property | |
| Data and configuration | <span id="benchbox.write_primitives.WritePrimitives.csv_delimiter"></span>`csv_delimiter` | property | `None`. |
| Data and configuration | <span id="benchbox.write_primitives.WritePrimitives.csv_null_marker"></span>`csv_null_marker` | property | `None`. |
| Data and configuration | <span id="benchbox.write_primitives.WritePrimitives.DATA_SOURCE_BENCHMARK"></span>`DATA_SOURCE_BENCHMARK` | class attribute | `None` on this class; `get_data_source_benchmark()` returns `"tpch"`. |
| Data and configuration | <span id="benchbox.write_primitives.WritePrimitives.get_csv_loading_config"></span>`get_csv_loading_config` | method | `None`. |
| Data and configuration | <span id="benchbox.write_primitives.WritePrimitives.get_data_source_benchmark"></span>`get_data_source_benchmark` | method | |
| Data and configuration | <span id="benchbox.write_primitives.WritePrimitives.get_query_categories"></span>`get_query_categories` | method | |
| Data and configuration | <span id="benchbox.write_primitives.WritePrimitives.output_dir"></span>`output_dir` | property | The resolved directory from the constructor argument (the TPC-H directory by default). |
| Data and configuration | <span id="benchbox.write_primitives.WritePrimitives.run_with_platform_api_surface"></span>`run_with_platform_api_surface` | class attribute | |
| Data and configuration | <span id="benchbox.write_primitives.WritePrimitives.scale_factor"></span>`scale_factor` | instance attribute | The constructor argument. |
| Data and configuration | <span id="benchbox.write_primitives.WritePrimitives.SKIP_DATA_LOADING"></span>`SKIP_DATA_LOADING` | class attribute | Defined on `BaseBenchmark` from 0.4.2, default `False`. Set it to `True` for a benchmark that needs schema objects but no data files. |

## Operations Catalog

The benchmark includes **112 operations** in 6 categories. Operation ids start with the category name.

### INSERT Operations (3)

The `insert` category has 12 operations. The first three:

- **insert_single_row**: Single row INSERT with all columns
- **insert_batch_values_10**: Batch INSERT with 10 rows
- **insert_select_simple**: INSERT...SELECT with WHERE filter

Others include `insert_batch_values_100`, `insert_batch_values_1000`, `insert_select_with_join`, `insert_select_aggregated`, `insert_select_from_multiple`, `insert_with_default_values`, `insert_select_union`, `insert_on_conflict_ignore` and `insert_returning_clause`.

### UPDATE Operations (3)

The `update` category has 15 operations. The first three:

- **update_single_row_pk**: UPDATE single row by primary key
- **update_selective_10pct**: UPDATE about 10% of rows
- **update_with_subquery**: UPDATE with a subquery

Others include `update_bulk_50pct`, `update_bulk_all`, `update_with_join`, `update_from_select`, `update_with_case_expression`, `update_date_arithmetic` and `update_returning`.

### DELETE Operations (2)

The `delete` category has 14 operations. The first two:

- **delete_single_row_pk**: DELETE single row by primary key
- **delete_selective_10pct**: DELETE about 10% of rows

Others include `delete_with_subquery`, `delete_with_join`, `delete_bulk_25pct`, `delete_bulk_50pct`, `delete_bulk_75pct`, `delete_with_not_exists`, `delete_returning` and `delete_gdpr_suppliers_1pct`.

### DDL Operations (3)

The `ddl` category has 12 operations. The first three:

- **ddl_create_table_simple**: CREATE TABLE with simple schema
- **ddl_truncate_table_small**: TRUNCATE small staging table
- **ddl_create_table_as_select_simple**: CTAS with simple SELECT

Others include `ddl_create_table_with_constraints`, `ddl_alter_table_add_column`, `ddl_alter_table_drop_column`, `ddl_create_index_on_existing`, `ddl_create_view_simple` and `ddl_drop_table`.

### TRANSACTION Operations (1)

There are no transaction operations in 0.4.1 (`get_operation_categories()` does not list `transaction`); they moved to the transaction primitives benchmark. The `bulk_load` category (36 operations, for example `bulk_load_csv_small_gzip`) and the `merge` category (23 operations, for example `merge_simple_upsert_small`) complete the 112.

## Staging Tables

`setup()` creates these staging tables (18) from the TPC-H tables:

**Data Tables**:

- **insert_ops_lineitem**, **insert_ops_orders**: Targets for INSERT operations
- **insert_ops_orders_summary**, **insert_ops_lineitem_enriched**: Targets for aggregated and joined INSERT...SELECT
- **update_ops_orders**: Target for UPDATE operations
- **delete_ops_orders**, **delete_ops_lineitem**, **delete_ops_supplier**: Targets for DELETE operations
- **merge_ops_target**, **merge_ops_source**, **merge_ops_lineitem_target**, **merge_ops_summary_target**: Targets and sources for MERGE operations
- **scd2_ops_dim_customer**, **scd2_ops_stage_customer**: Slowly changing dimension MERGE tests
- **bulk_load_ops_target**: Target for BULK_LOAD operations
- **ddl_truncate_target**: Target for the TRUNCATE operation

**Metadata Tables**:

- **write_ops_log**: Audit log for write operations
- **batch_metadata**: Tracks batch operations

## Usage Examples

### Complete Workflow

The example loads the TPC-H data first, then sets up Write Primitives. It executes a single operation, runs all operations and then cleans up.

```python
from benchbox import TPCH, WritePrimitives
from benchbox.platforms.duckdb import DuckDBAdapter

tpch = TPCH(scale_factor=0.01)
tpch.generate_data()

adapter = DuckDBAdapter()
conn = adapter.create_connection()
adapter.create_schema(tpch, conn)
adapter.load_data(tpch, conn, tpch.output_dir)

bench = WritePrimitives(scale_factor=0.01)
bench.generate_data()
setup_result = bench.setup(conn, force=True)
print(f"Setup: {setup_result['success']}")
print(f"Tables: {len(setup_result['tables_created'])}")

result = bench.execute_operation("insert_single_row", conn)
print(f"Success: {result.success}")
print(f"Time: {result.write_duration_ms:.2f}ms")
print(f"Validation: {result.validation_passed}")

results = bench.run_benchmark(conn)
print(f"Total: {len(results)}")
successful = [r for r in results if r.success]
print(f"Successful: {len(successful)}")

bench.teardown(conn)
```

Output on 0.4.1 (times vary):

```text
Setup: True
Tables: 18
Success: True
Time: 1.32ms
Validation: True
Total: 112
Successful: 112
```

### Category-Based Testing

Test each category separately, and reset between categories.

```python
categories = bench.get_operation_categories()

for category in categories:
    print(f"\nTesting {category.upper()} operations:")
    results = bench.run_benchmark(conn, categories=[category])

    for result in results[:3]:
        status = "OK" if result.success else "FAIL"
        print(f"  {status} {result.operation_id}: {result.write_duration_ms:.2f}ms")

    bench.reset(conn)
```

### Performance Analysis

Run multiple iterations for stable timing, and reset between iterations.

```python
import time
from statistics import mean, median

operation_id = "insert_single_row"
iterations = 10
times = []

for i in range(iterations):
    result = bench.execute_operation(operation_id, conn)
    if result.success:
        times.append(result.write_duration_ms)

    if i < iterations - 1:
        bench.reset(conn)

print(f"Operation: {operation_id}")
print(f"Iterations: {iterations}")
print(f"Mean: {mean(times):.2f}ms")
print(f"Median: {median(times):.2f}ms")
print(f"Min: {min(times):.2f}ms")
print(f"Max: {max(times):.2f}ms")
```

### Error Handling and Recovery

Reset the staging tables to recover from an operation failure. After a validation failure, reset and retry.

```python
result = bench.execute_operation("insert_batch_values_10", conn)

if not result.success:
    print(f"Operation failed: {result.error}")
    if result.cleanup_warning:
        print(f"Cleanup warning: {result.cleanup_warning}")

    print("Resetting staging tables...")
    bench.reset(conn)

if not result.validation_passed:
    print("Validation failed:")
    for val_result in result.validation_results:
        if not val_result['passed']:
            print(f"  Query: {val_result['query_id']}")
            print(f"  Expected: {val_result['expected_rows']}")
            print(f"  Actual: {val_result['actual_rows']}")

    bench.reset(conn)
    result = bench.execute_operation("insert_batch_values_10", conn)
```

## Best Practices

1. **Always Load TPC-H First**

   The first two statements are wrong: `setup` fails with a `RuntimeError` because the TPC-H table `orders` is not found. Load the TPC-H data first, as the remaining statements show.

   ```python
   bench = WritePrimitives()
   bench.setup(conn)

   tpch = TPCH(scale_factor=1.0)
   tpch.generate_data()
   adapter = DuckDBAdapter()
   adapter.create_schema(tpch, conn)
   adapter.load_data(tpch, conn, tpch.output_dir)

   bench = WritePrimitives(scale_factor=1.0)
   bench.setup(conn)
   ```

2. **Check Setup Status**

   ```python
   if not bench.is_setup(conn):
       bench.setup(conn)
   ```

3. **Run `generate_data()` for Bulk Loads**

   Without `generate_data()`, the 36 `bulk_load` operations are skipped.

   ```python
   bench.generate_data()
   results = bench.run_benchmark(conn, categories=["bulk_load"])
   ```

4. **Reset Between Test Runs**

   Reset after each operation to start the next one from a clean state.

   ```python
   for operation_id in ["insert_single_row", "update_single_row_pk"]:
       result = bench.execute_operation(operation_id, conn)
       bench.reset(conn)
   ```

5. **Validate and Handle Errors**

   ```python
   result = bench.execute_operation("insert_select_simple", conn)

   if result.success and result.validation_passed:
       print(f"Success: {result.write_duration_ms:.2f}ms")
   elif result.status == "FAILED":
       print(f"Failed: {result.error}")
   elif result.status == "VALIDATION_FAILED":
       print("Validation failed, check data dependencies")
   ```

## Common Issues

**Issue: "Required TPC-H table not found":**

- **Cause**: Write Primitives requires TPC-H base tables
- **Solution**: Load TPC-H data before calling `setup()`

**Issue: Bulk-load operations report SKIPPED:**

- **Cause**: The bulk-load files have not been generated
- **Solution**: Call `bench.generate_data()` (after loading TPC-H into the database)

**Issue: Validation failures:**

- **Cause**: Data-dependent operations or constraint violations
- **Solution**: Check `validation_results` for details, reset if needed

**Issue: rows_affected = -1:**

- **Cause**: Some databases (DuckDB) don't return a row count
- **Impact**: Normal behavior, doesn't affect operation success

## DataFrame Support

Write Primitives provides DataFrame support for write operations on DataFrame platforms, in `benchbox.core.write_primitives.dataframe_operations` (not one of the listed public symbols, so its layout may change).

**Platform Capabilities** (from `DataFrameWriteOperationsManager(platform).get_capabilities()`):

| Platform | INSERT | UPDATE | DELETE | MERGE | BULK_LOAD | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Polars (`polars-df`) | yes | yes | yes | yes | yes | Compressions: zstd, snappy, gzip, lz4; partitioning supported |
| Pandas (`pandas-df`) | no | no | no | no | yes | Compressions: snappy, gzip, brotli |
| PySpark (`pyspark-df`) | no | no | no | no | yes | Also supports aggregate persist and merge |
| DataFusion, Dask, cuDF | no | no | no | no | yes | Bulk load only |

### DataFrameWriteOperationsManager

The example creates a manager, checks its capabilities and then executes a bulk load.

```python
from benchbox.core.write_primitives.dataframe_operations import (
    DataFrameWriteOperationsManager,
    WriteOperationType,
    get_dataframe_write_manager,
)

with open("orders.csv", "w") as f:
    f.write("o_orderkey,o_custkey,o_totalprice\n1,10,100.5\n2,20,250.0\n3,30,75.25\n")

manager = DataFrameWriteOperationsManager("polars-df")

caps = manager.get_capabilities()
print(f"Supports UPDATE: {caps.supports_operation(WriteOperationType.UPDATE)}")

result = manager.execute_bulk_load(
    source_path="orders.csv",
    target_path="orders",
    source_format="csv",
    target_format="parquet",
    compression="zstd",
)
print(result.success, result.rows_affected, result.compression, result.file_count)
```

Output on 0.4.1:

```text
Supports UPDATE: True
True 3 zstd 1
```

`get_dataframe_write_manager(platform_name)` returns a manager, or `None` for an unknown platform. The `polars-df` manager uses the `polars` package.

**Available Methods**:

- `get_capabilities()` - Get platform write capabilities
- `supports_operation(op)` - Check if the manager's platform supports an operation type
- `execute_insert(table_path, dataframe, partition_columns=None, mode="append")` - Insert rows
- `execute_update(table_path, condition, updates)` - Update rows
- `execute_delete(table_path, condition)` - Delete rows
- `execute_merge(table_path, source_dataframe, merge_condition, when_matched=None, when_not_matched=None)` - Merge/upsert rows
- `execute_bulk_load(source_path, target_path, source_format="parquet", target_format="parquet", compression="zstd", partition_columns=None, sort_columns=None)` - Bulk load files

The bulk load above writes `part-00000.parquet` under the `orders` directory. A following `execute_update("orders", "o_custkey = 20", {"o_totalprice": 999.0})` and `execute_delete("orders", "o_custkey = 10")` each affected 1 row.

### DataFrameWriteResult

All DataFrame write operations return a `DataFrameWriteResult`:

```python
@dataclass
class DataFrameWriteResult:
    operation_type: WriteOperationType
    success: bool
    start_time: float
    end_time: float
    duration_ms: float
    rows_affected: int
    bytes_written: int | None = None
    compression: str | None = None
    file_count: int | None = None
    error_message: str | None = None
    validation_passed: bool = True
    validation_results: list[dict[str, Any]]
    metrics: dict[str, Any]
```

### DataFrameWriteCapabilities

Platform capabilities for write operations. `supported_compressions` lists codecs such as `["zstd", "snappy", "gzip"]`:

```python
@dataclass
class DataFrameWriteCapabilities:
    platform_name: str
    maintenance_caps: DataFrameMaintenanceCapabilities | None
    supports_bulk_load: bool = True
    supports_compression: bool = True
    supported_compressions: list[str]
    supports_partitioning: bool = False
    supports_sorting: bool = True
    supports_aggregate_persist: bool
    supports_aggregate_merge: bool
    notes: str
```

## See Also

- {doc}`/benchmarks/write-primitives` - Write Primitives benchmark guide
- {doc}`read-primitives` - Read Primitives benchmark
- {doc}`tpch` - TPC-H benchmark (data source)
- {doc}`/reference/python-api/base` - Base benchmark interface
- {doc}`/platforms/dataframe` - DataFrame platforms overview

### Future Expansion

The operation catalog is YAML-driven, so more operations can be added to it. The catalog holds 112 operations. Transaction operations are in the transaction primitives benchmark.
