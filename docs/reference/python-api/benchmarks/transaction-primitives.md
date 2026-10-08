# Transaction Primitives API

```{tags} reference, python-api, custom-benchmark
```

<!-- markdownlint-disable MD024 -->

Python API reference for the Transaction Primitives benchmark.

## Overview

Transaction Primitives measures the cost and behaviour of database transactions on the TPC-H schema. It defines 23 operations in five categories (`overhead` 5, `savepoint` 2, `isolation` 3, `multi_statement` 8, `advanced` 5): commits and rollbacks of different sizes, nested savepoints, isolation levels, mixed DML inside one transaction, and transaction-scoped objects. Each operation is a script that uses `BEGIN` and `COMMIT` or `ROLLBACK`, and each is validated with read queries and then cleaned up.

The benchmark needs a platform with full transaction support. An operation that the platform cannot run is reported as failed, not raised. On DuckDB, 18 of the 23 run and the 2 savepoint and 3 isolation-level operations fail with a parser error.

It reuses the TPC-H data. Load the TPC-H tables into the database first; the operations work on three staging copies, `txn_orders`, `txn_lineitem` and `txn_customer`.

## `benchbox.TransactionPrimitives`

<span id="benchbox.transaction_primitives.TransactionPrimitives"></span>

Creates a Transaction Primitives benchmark that runs 23 transaction operations against staging tables copied from loaded TPC-H tables.

**Import:** `from benchbox import TransactionPrimitives` · **Extras:** none

### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `scale_factor` | `float` | `1.0` | TPC-H scale factor; use the one of the TPC-H data in the database. Must be positive. Values of 1 or more must be whole numbers. |
| `output_dir` | `str`, `Path` or `None` | `None` | Directory for generated data files. When `None`, the TPC-H directory `benchmark_runs/datagen/tpch_<sf token>` under the current directory (for example `tpch_sf001` for 0.01), or under `$BENCHBOX_OUTPUT_DIR/datagen`, so data is shared with a `TPCH` benchmark of the same scale factor. |
| `**kwargs` | keyword arguments | none | `verbose` (`bool` or `int`) and `quiet` (`bool`) set the log level. Other keywords are stored as attributes. |

The constructor creates no files and does not touch a database.

### Returns

A `TransactionPrimitives` instance. It subclasses `BaseBenchmark`; see {doc}`/reference/python-api/base` for the shared interface.

### Raises

- `ValueError` when `scale_factor` is zero or negative (`Scale factor must be positive`), or is 1 or more and not a whole number.
- `TypeError` when `scale_factor` is not a number.

### Example

```python
from benchbox import TPCH, TransactionPrimitives
from benchbox.platforms.duckdb import DuckDBAdapter

tpch = TPCH(scale_factor=0.01, output_dir="tx_data")
tpch.generate_data()
adapter = DuckDBAdapter(database=":memory:")
conn = adapter.create_connection()
adapter.create_schema(tpch, conn)
adapter.load_data(tpch, conn, tpch.output_dir)

bench = TransactionPrimitives(scale_factor=0.01, output_dir="tx_data")
print(bench.get_operation_categories())
print(bench.setup(conn)["table_row_counts"])
result = bench.execute_operation("transaction_commit_small", conn)
print(result.success, result.validation_passed)
results = bench.run_benchmark(conn, categories=["savepoint"])
print([(r.operation_id, r.success) for r in results])
```

Output on 0.4.1, after the adapter's progress lines:

```text
['advanced', 'isolation', 'multi_statement', 'overhead', 'savepoint']
{'txn_orders': 15000, 'txn_lineitem': 60175, 'txn_customer': 1500}
True True
[('transaction_savepoint_nested', False), ('transaction_savepoint_deep_nesting', False)]
```

The DuckDB adapter needs the `duckdb` package. The two savepoint operations fail on DuckDB with `Parser Error: syntax error at or near "SAVEPOINT"`.

### Compatibility

`benchbox.transaction_primitives.TransactionPrimitives` is the same class. The class attribute `DATA_SOURCE_BENCHMARK` is `None`; `get_data_source_benchmark()` returns `"tpch"`. `get_query_categories()` raises `AttributeError` on 0.4.1; use `get_operation_categories()`.

## Constructor

<span id="benchbox.transaction_primitives.TransactionPrimitives.__init__"></span>

`TransactionPrimitives(scale_factor=1.0, output_dir=None, **kwargs)`. The arguments are in the Parameters table above.

## Data methods

### generate_data(tables=None)

<span id="benchbox.transaction_primitives.TransactionPrimitives.generate_data"></span>

`generate_data(tables=None) -> list` generates (or reuses) the TPC-H files in `output_dir` and returns 10 paths: the eight TPC-H `.tbl` files plus `orders_stage.tbl` and `lineitem_stage.tbl`. `tables` is accepted but has no effect: `generate_data(tables=["region"])` also returns all 10. `benchmark.tables` is a `dict` of the same 10 paths, empty until `generate_data()` has run.

### get_data_source_benchmark()

<span id="benchbox.transaction_primitives.TransactionPrimitives.get_data_source_benchmark"></span>

`get_data_source_benchmark() -> str` returns `"tpch"`.

## Lifecycle methods

### setup(connection, force=False)

<span id="benchbox.transaction_primitives.TransactionPrimitives.setup"></span>

`setup(connection, force=False) -> dict` creates the staging tables and fills them from the loaded TPC-H tables.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `connection` | database connection | required | Connection that already holds the TPC-H tables. |
| `force` | `bool` | `False` | When true, drop existing staging tables first. |

Returns a dict with `success`, `tables_created` (`txn_orders`, `txn_lineitem`, `txn_customer`) and `table_row_counts`. At scale factor 0.01 the counts are 15,000, 60,175 and 1,500. Calling it again on a set-up database also succeeds.

Raises `RuntimeError` when the TPC-H tables are missing.

### is_setup(connection)

<span id="benchbox.transaction_primitives.TransactionPrimitives.is_setup"></span>

`is_setup(connection) -> bool` is true when all staging tables exist and hold data.

### reset(connection)

<span id="benchbox.transaction_primitives.TransactionPrimitives.reset"></span>

`reset(connection) -> None` truncates and refills the staging tables from the TPC-H tables.

### teardown(connection)

<span id="benchbox.transaction_primitives.TransactionPrimitives.teardown"></span>

`teardown(connection) -> None` drops the staging tables; `is_setup()` is then false.

### load_data(connection, \*\*kwargs)

<span id="benchbox.transaction_primitives.TransactionPrimitives.load_data"></span>

`load_data(connection, **kwargs) -> dict` is the entry point that platform adapters call; it runs `setup()` (a `force` keyword is passed through) and returns the same kind of dict. Call `setup()` directly in your own code.

## Operation execution methods

### execute_operation(operation_id, connection)

<span id="benchbox.transaction_primitives.TransactionPrimitives.execute_operation"></span>

`execute_operation(operation_id, connection) -> OperationResult` runs one operation, validates it with its read queries, and runs its cleanup SQL. If the staging tables are missing, the first call sets them up.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `operation_id` | `str` | required | An id such as `"transaction_commit_small"`. |
| `connection` | database connection | required | Connection with the TPC-H tables. |

Raises `ValueError` for an unknown operation id (`Invalid operation ID: bogus. Available: ...`). Failures inside the operation are returned, not raised: `success` is false and `error` holds the message.

The result has these fields: `operation_id`, `success`, `write_duration_ms`, `rows_affected` (`-1` for the transaction scripts), `validation_duration_ms`, `validation_passed`, `validation_results`, `cleanup_duration_ms`, `cleanup_success`, `error`, `cleanup_warning`, `status`, `skip_reason` and `executed_sql`. `status` and `skip_reason` stay `None` on both successful and failed DuckDB runs.

```python
result = bench.execute_operation("transaction_commit_small", conn)
print(result.operation_id, result.success, result.validation_passed)
```

This prints `transaction_commit_small True True`.

### run_benchmark(connection, operation_ids=None, categories=None)

<span id="benchbox.transaction_primitives.TransactionPrimitives.run_benchmark"></span>

`run_benchmark(connection, operation_ids=None, categories=None) -> list[OperationResult]` runs several operations in catalog order and returns one result per operation.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `connection` | database connection | required | Connection with the TPC-H tables. |
| `operation_ids` | `list[str]` or `None` | `None` | Operations to run. `None` runs all 23. An unknown id raises `ValueError`. |
| `categories` | `list[str]` or `None` | `None` | Categories to run: `"overhead"`, `"savepoint"`, `"isolation"`, `"multi_statement"`, `"advanced"`. An unknown category contributes no operations; if none remain the result is `[]`. |

```python
results = bench.run_benchmark(conn)
print(len(results), sum(r.success for r in results))
```

This prints `23 18`: the number of results, then the number that succeeded.

## Operation query methods

### get_all_operations()

<span id="benchbox.transaction_primitives.TransactionPrimitives.get_all_operations"></span>

`get_all_operations() -> dict[str, WriteOperation]` returns all 23 operations keyed by id. Each has `id`, `category`, `description`, `write_sql`, `validation_queries`, `cleanup_sql`, `expected_rows_affected`, `file_dependencies`, `platform_overrides` and `requires_setup`.

### get_operation(operation_id)

<span id="benchbox.transaction_primitives.TransactionPrimitives.get_operation"></span>

`get_operation(operation_id) -> WriteOperation` returns one operation. Raises `ValueError` for an unknown id.

### get_operations_by_category(category)

<span id="benchbox.transaction_primitives.TransactionPrimitives.get_operations_by_category"></span>

`get_operations_by_category(category) -> dict[str, WriteOperation]` returns the operations in one category. An unknown category returns `{}`.

### get_operation_categories()

<span id="benchbox.transaction_primitives.TransactionPrimitives.get_operation_categories"></span>

`get_operation_categories() -> list[str]` returns `['advanced', 'isolation', 'multi_statement', 'overhead', 'savepoint']`.

### get_queries(dialect=None) and get_query(query_id)

<span id="benchbox.transaction_primitives.TransactionPrimitives.get_queries"></span>
<span id="benchbox.transaction_primitives.TransactionPrimitives.get_query"></span>

`get_queries(dialect=None) -> dict[str, str]` returns the SQL script of all 23 operations keyed by operation id; `get_query(query_id) -> str` returns one. `dialect` is accepted and makes no difference to the text. `get_query()` raises `ValueError` for an unknown id.

### get_queries_by_category(category)

<span id="benchbox.transaction_primitives.TransactionPrimitives.get_queries_by_category"></span>

`get_queries_by_category(category) -> dict[str, str]` returns the SQL of one category, keyed by operation id. An unknown category returns `{}`.

## Schema methods

### get_schema(dialect="standard")

<span id="benchbox.transaction_primitives.TransactionPrimitives.get_schema"></span>

`get_schema(dialect="standard") -> dict[str, dict]` returns the staging tables only: `txn_orders`, `txn_lineitem` and `txn_customer`, each a definition with `name` and `columns`. `dialect` has no effect on the result.

### get_create_tables_sql(dialect="standard", tuning_config=None)

<span id="benchbox.transaction_primitives.TransactionPrimitives.get_create_tables_sql"></span>

`get_create_tables_sql(dialect="standard", tuning_config=None) -> str` returns the `CREATE TABLE` statements for 13 tables: the eight TPC-H tables, `orders_stage`, `lineitem_stage`, and the three staging tables.

### get_benchmark_info()

<span id="benchbox.transaction_primitives.TransactionPrimitives.get_benchmark_info"></span>

`get_benchmark_info() -> dict` returns `name`, `version`, `description`, `scale_factor`, `total_operations` (23), `categories`, `tables` (the three staging tables) and `data_source` (`"tpch"`).

## Inherited members

Every other member comes from `BaseBenchmark`: platform runs (`run_with_platform`), validation, logging, `output_dir`, `scale_factor` and the loading configuration. See {doc}`/reference/python-api/base`.
