# Base Benchmark API

```{tags} reference, python-api, contributor
```

The `benchbox.base` module provides the foundational abstract class that all benchmarks inherit from.

## Overview

Every benchmark in BenchBox extends `BaseBenchmark`, which provides a standardized interface for:

- Data generation and schema setup
- Query execution and timing
- Platform adapter integration
- SQL dialect translation
- Results collection and formatting

This abstraction ensures consistent behavior across all benchmark implementations (TPC-H, TPC-DS, ClickBench, etc.).

## Runtime Contract Notes

The lifecycle runner expects loader-resolved benchmarks to provide a shared runtime contract:

- `generate_data`
- `get_queries` / `get_query`
- `create_enhanced_benchmark_result`
- `create_minimal_benchmark_result`
- `validate_preflight` / `validate_manifest` / `validate_loaded_data`

`BaseBenchmark` defines the first three as abstract methods and gets the rest from a mixin, so a subclass of `benchbox.base.BaseBenchmark` provides all of them once it implements `generate_data`, `get_queries` and `get_query`.

Compatibility boundaries:

- Public benchmark implementations should inherit `benchbox.base.BaseBenchmark`.
- `benchbox.core.base_benchmark.BaseBenchmark` is a separate internal class, not a subclass of the public one. It remains temporarily for internal compatibility.
- `create_enhanced_benchmark_result()` accepts the legacy keyword arguments `table_statistics` (a mapping of table name to row count) and `data_loading_time` (seconds).

## Quick Example

```python
from benchbox.tpch import TPCH
from benchbox.platforms import DuckDBAdapter

benchmark = TPCH(scale_factor=0.01, output_dir="tpch_data")

data_files = benchmark.generate_data()
print(len(data_files), data_files[0].name)

adapter = DuckDBAdapter()
results = benchmark.run_with_platform(adapter, query_subset=[1, 3, 6])

print(f"Completed {results.successful_queries}/{results.total_queries} queries")
print(f"Average query time: {results.average_query_time:.3f}s")
```

Output on 0.4.1 (the adapter also prints its progress lines, which are omitted here; the timing varies by machine):

```text
8 customer.tbl
Completed 3/3 queries
Average query time: 0.007s
```

## Core Classes

<span id="benchbox.base.BaseBenchmark"></span>

### `benchbox.BaseBenchmark`

The abstract base class for every BenchBox benchmark. Subclass it and implement `generate_data`, `get_queries` and `get_query`.

**Import:** `from benchbox import BaseBenchmark` · **Extras:** none

Alias: `from benchbox.base import BaseBenchmark` returns the same object.

<span id="benchbox.base.BaseBenchmark.__init__"></span>

#### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `scale_factor` | `float` | `1.0` | The benchmark scale factor. |
| `output_dir` | `str`, `Path` or `None` | `None` | Directory for generated data. |
| `**kwargs` | any | none | `verbose` (bool or int) and `quiet` (bool) set the logging verbosity. Every other keyword is stored as an attribute of the instance. |

Full signature: `(scale_factor: float = 1.0, output_dir: Union[str, pathlib.Path, NoneType] = None, **kwargs: Any) -> None`

`scale_factor` must be positive, and a value of 1 or more must be a whole number. When `output_dir` is `None`, the directory is `benchmark_runs/datagen/<name>_sf<token>` under the current working directory, for example `benchmark_runs/datagen/dummy_sf01` for scale factor 0.1. If the `BENCHBOX_OUTPUT_DIR` environment variable is set, the directory is `datagen/<name>_sf<token>` under that path instead.

**Returns:** an instance of the subclass you construct, because `BaseBenchmark` itself is abstract. The instance keeps `scale_factor` as passed and `output_dir` as a `pathlib.Path` (or a cloud path object), and every extra keyword as an attribute of the same name. The constructor creates no files.

#### Raises

- `ValueError`: `scale_factor` is zero or negative (`Scale factor must be positive`), or is 1 or more and not a whole number (`Scale factors >= 1 must be whole integers`).
- `TypeError`: `scale_factor` is not a number, or the class still has abstract methods.
- `ImportError`: `output_dir` is a cloud storage URL such as `s3://bucket/path` and the `cloudstorage` extra is not installed.

#### Example

```python
from benchbox import BaseBenchmark


class TinyBenchmark(BaseBenchmark):
    def generate_data(self):
        return []

    def get_queries(self):
        return {"q1": "SELECT 1 AS one", "q2": "SELECT 2 AS two"}

    def get_query(self, query_id, *, params=None):
        return self.get_queries()[str(query_id)]


TinyBenchmark(scale_factor=1.5)
```

```text
ValueError: Scale factors >= 1 must be whole integers. Got: 1.5. Use values like 1, 2, 10, etc. for large scale factors. Use values like 0.1, 0.01, 0.001, etc. for small scale factors.
```

#### Compatibility

- Instances keep `output_dir` as a `pathlib.Path` (or a cloud path object), whatever type you passed in.
- `benchbox.core.base_benchmark.BaseBenchmark` is a different class; do not use it as a base for new code.

### Class attributes

<span id="benchbox.base.BaseBenchmark.api_surface"></span>

`api_surface` is the string `"beta-public"`.

<span id="benchbox.base.BaseBenchmark.run_with_platform_api_surface"></span>

`run_with_platform_api_surface` is also the string `"beta-public"`. Both labels mark the class and `run_with_platform` as public but not yet frozen.

<span id="benchbox.base.BaseBenchmark.DATA_SOURCE_BENCHMARK"></span>

`DATA_SOURCE_BENCHMARK` is `None` by default. Set it to the lower-case identifier of another benchmark (for example `"tpch"`) when your benchmark reuses that benchmark's generated data. `get_data_source_benchmark()` returns it.

<span id="benchbox.base.BaseBenchmark.SKIP_DATA_LOADING"></span>

`SKIP_DATA_LOADING` is a `bool` class attribute that defaults to `False`. Set it to `True` for a benchmark that needs schema objects but no data files; the platform adapter then creates the schema and skips data loading. Added in 0.4.2.

### Other members

<span id="benchbox.base.BaseBenchmark.tables"></span>

`tables` is a `dict` that maps table names to data file paths. It is empty on a new instance and TPC-H fills it when `generate_data` runs. You can assign a new mapping.

<span id="benchbox.base.BaseBenchmark.csv_delimiter"></span>

`csv_delimiter` is a read-only `str | None`. It is `None` unless a benchmark sets it, and assigning to it raises `AttributeError`.

<span id="benchbox.base.BaseBenchmark.csv_null_marker"></span>

`csv_null_marker` is a `str | None` that you can assign. It is `None` unless a benchmark sets it.

<span id="benchbox.base.BaseBenchmark.get_csv_loading_config"></span>

`get_csv_loading_config(table_name)` returns a list of CSV reader options (strings) for the table, or `None` when the benchmark has no configuration. The base class returns `None`; ClickBench returns a list such as `["delim='|'", 'header=false', "nullstr='__NULL__'", 'ignore_errors=true', 'auto_detect=true']`.

<span id="benchbox.base.BaseBenchmark.cleanup"></span>

`cleanup()` does nothing in the base class and returns `None`. Subclasses may override it to release resources.

## Key Methods

### Data Generation

<span id="benchbox.base.BaseBenchmark.generate_data"></span>

#### `generate_data()`

**Required override.** Generates the benchmark data files and returns their paths.

**Returns:** `list[str | Path]`. The built-in benchmarks return `pathlib.Path` objects, for example eight `.tbl` files for TPC-H.

`BaseBenchmark` declares the method abstract, so a subclass that does not implement it cannot be instantiated.

### Query Access

<span id="benchbox.base.BaseBenchmark.get_queries"></span>

#### `get_queries()`

**Required override.** Returns every query of the benchmark as a `dict[str, str]` that maps query ID to SQL text.

The IDs are benchmark specific. TPC-H uses the strings `'1'` to `'22'`:

```python
from benchbox import TPCH

benchmark = TPCH(scale_factor=0.01, output_dir="tpch_data")
queries = benchmark.get_queries()
print(len(queries), list(queries)[:3])
```

```text
22 ['1', '2', '3']
```

<span id="benchbox.base.BaseBenchmark.get_query"></span>

#### `get_query(query_id, *, params=None)`

**Required override.** Returns the SQL text for one query.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `query_id` | `int` or `str` | required | The query ID. Each benchmark decides which types it accepts. |
| `params` | `dict[str, Any]` or `None` | `None` | Query parameters, keyword-only. Which keys are used depends on the benchmark. |

**Returns:** `str`, the query with its parameters resolved.

**Raises:** `ValueError` for an unknown query ID in the built-in benchmarks.

The built-in TPC-H and TPC-DS classes take integer IDs: `get_query(1)` works, `get_query("1")` raises `TypeError: query_id must be an integer, got str`, and `get_query(999)` on TPC-H raises `ValueError: Query ID must be 1-22, got 999`. Check the reference page for the benchmark you use.

```python
query_sql = benchmark.get_query(1)
print(query_sql[:30])
```

```text
SELECT l_returnflag, l_linesta
```

### Database Setup

<span id="benchbox.base.BaseBenchmark.setup_database"></span>

#### `setup_database(connection)`

Generates the data if this instance has not generated it yet, then loads it through the subclass's `_load_data(connection)` method.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `connection` | `DatabaseConnection` | required | The connection to load into. |

**Returns:** `None`.

**Raises:** `NotImplementedError` unless the subclass overrides `_load_data`. The built-in benchmarks do not override it, so `setup_database` and `run_benchmark` with the default `setup_database=True` fail on them with `TPCH must implement _load_data() method to support database execution functionality`. Load built-in benchmarks through `run_with_platform` instead. Any other error from data generation or loading is re-raised.

`generate_data` runs once per instance: a second call to `setup_database` loads again but does not regenerate.

### Execution

<span id="benchbox.base.BaseBenchmark.run_query"></span>

#### `run_query(query_id, connection, params=None, fetch_results=False)`

Runs one query on a connection and times it.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `query_id` | `int` or `str` | required | The query to run, as accepted by `get_query`. |
| `connection` | `DatabaseConnection` | required | An object with `execute(sql)` and `fetchall(cursor)`. |
| `params` | `dict[str, Any]` or `None` | `None` | Passed to `get_query`. |
| `fetch_results` | `bool` | `False` | Fetch all rows. |

**Returns:** a `dict` with the keys `query_id`, `execution_time_seconds`, `query_text`, `results` and `row_count`. `results` is `None` and `row_count` is `0` unless `fetch_results` is true.

**Raises:** whatever `get_query` or the connection raises, after logging it. A failed query raises; it is not returned as an error entry.

```python
import sqlite3
from benchbox.core.connection import DatabaseConnection

connection = DatabaseConnection(sqlite3.connect(":memory:"))
benchmark = TinyBenchmark(scale_factor=0.01, output_dir="tiny_out")
print(benchmark.run_query("q1", connection, fetch_results=True)["results"])
```

```text
[(1,)]
```

<span id="benchbox.base.BaseBenchmark.run_benchmark"></span>

#### `run_benchmark(connection, query_ids=None, fetch_results=False, setup_database=True)`

Runs a set of queries one after another and summarises the timings.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `connection` | `DatabaseConnection` | required | The connection to run on. |
| `query_ids` | `list[int \| str]` or `None` | `None` | Queries to run. `None` runs every key of `get_queries()`. |
| `fetch_results` | `bool` | `False` | Passed to `run_query`. |
| `setup_database` | `bool` | `True` | Call `setup_database` first. |

**Returns:** a `dict` with `benchmark_name` (the class name, for example `"TinyBenchmark"`), `total_execution_time`, `total_queries`, `successful_queries`, `failed_queries`, `query_results`, `setup_time`, `average_query_time`, `min_query_time` and `max_query_time`. Times are in seconds and exclude setup. The three summary times cover successful queries only and are `0.0` when none succeeded.

A query that fails does not stop the run. Its entry in `query_results` has `execution_time_seconds` of `0.0`, `query_text` of `None`, `row_count` of `0` and an extra `error` string, and `failed_queries` counts it.

**Raises:** errors from `setup_database` when `setup_database=True`, including the `NotImplementedError` described above.

`params` is not accepted: each query runs with its default parameters.

```python
results = benchmark.run_benchmark(connection, query_ids=["q1", "q2"], setup_database=False)
print(results["total_queries"], results["successful_queries"], results["failed_queries"])
print(benchmark.format_results(results).splitlines()[0])
```

```text
2 2 0
Benchmark: TinyBenchmark
```

<span id="benchbox.base.BaseBenchmark.run_with_platform"></span>

#### `run_with_platform(platform_adapter, **run_config)`

**Recommended entry point.** Runs the benchmark through a platform adapter, which handles connection, data loading and query execution.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `platform_adapter` | adapter | required | An object with a `run_benchmark(benchmark, **config)` method, such as `DuckDBAdapter()`. |
| `**run_config` | any | none | Passed unchanged to the adapter. `query_subset` (a list of query IDs) selects queries on the built-in adapters. |

**Returns:** the `BenchmarkResults` that the adapter returns.

`run_with_platform` sets `benchmark_type` to `"olap"` in `run_config` when you do not supply it, then calls `platform_adapter.run_benchmark(self, **run_config)`. A subclass can change the default by overriding `_get_default_benchmark_type`.

**Raises:** `CapabilityContractError` (message `object does not provide SQL benchmark execution; missing: run_benchmark`) when the adapter has no `run_benchmark` method. Everything else comes from the adapter.

```python
from benchbox.tpch import TPCH
from benchbox.platforms import DuckDBAdapter

benchmark = TPCH(scale_factor=0.01, output_dir="tpch_data")
results = benchmark.run_with_platform(DuckDBAdapter(), query_subset=[1, 6])
print(results.successful_queries, results.total_queries)
```

```text
2 2
```

Adapters for cloud warehouses such as Databricks are constructed with keyword configuration (`DatabricksAdapter(**config)`) and need live credentials; see {doc}`/platforms/platform-selection-guide`.

### SQL Translation

<span id="benchbox.base.BaseBenchmark.translate_query"></span>

#### `translate_query(query_id, dialect)`

Translates a query to another SQL dialect with sqlglot.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `query_id` | `int` or `str` | required | The query to translate, as accepted by `get_query`. |
| `dialect` | `str` | required | The target dialect name. |

**Returns:** `str`. The query is read as PostgreSQL SQL, and all identifiers are quoted in the output. The query is fetched with default parameters.

**Raises:** `ValueError` for an unknown query ID or an unknown dialect (`Error translating to dialect 'nonsense': Unknown dialect 'nonsense'.`).

Any dialect that sqlglot knows is accepted. These all translated TPC-H query 6 on 0.4.1: postgres, mysql, sqlite, duckdb, snowflake, bigquery, redshift, clickhouse, databricks, trino, athena and spark. The dialect name is case-insensitive (`"SNOWFLAKE"` works).

```{note}
**Dialect Translation vs Platform Adapters**: BenchBox can translate queries to many SQL dialects, but this doesn't mean platform adapters exist for all those databases. BenchBox supports 30+ platforms including DuckDB, SQLite, PostgreSQL, Databricks, BigQuery, Redshift, Snowflake, Trino, Athena, and more. See {doc}`/platforms/index` for the full list or {doc}`/development/roadmap` for planned platforms (MySQL, etc.).
```

```python
from benchbox import TPCH

benchmark = TPCH(scale_factor=0.01, output_dir="tpch_data")
print(benchmark.translate_query(6, "snowflake"))
print(benchmark.translate_query(6, "bigquery")[:40])
```

```text
SELECT SUM("l_extendedprice" * "l_discount") AS "revenue" FROM "lineitem" WHERE "l_shipdate" >= CAST('1994-01-01' AS DATE) AND "l_shipdate" < CAST('1994-01-01' AS DATE) + INTERVAL '1 YEAR' AND "l_discount" BETWEEN 0.06 - 0.01 AND 0.06 + 0.01 AND "l_quantity" < 24
SELECT SUM(`l_extendedprice` * `l_discou
```

### Results Creation

`create_enhanced_benchmark_result` and the other result and validation methods come from a mixin that `BaseBenchmark` inherits, not from `BaseBenchmark` itself.

#### `create_enhanced_benchmark_result(platform, query_results, ...)`

Builds a `BenchmarkResults` object from query results and metadata. Platform adapters use it so results have a consistent shape.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `platform` | `str` | required | The platform name. |
| `query_results` | `list[dict]` | required | One dict per executed query. |
| `execution_metadata` | `dict` or `None` | `None` | Run metadata. |
| `phases` | `dict` or `None` | `None` | Per-phase details. |
| `resource_utilization` | `dict` or `None` | `None` | Resource usage. |
| `performance_characteristics` | `dict` or `None` | `None` | Performance summary. |
| `duration_seconds` | `float` or `None` | `None` | Total run duration. |
| `**kwargs` | any | none | Includes the legacy `table_statistics` and `data_loading_time`. |

**Returns:** `benchbox.core.results.models.BenchmarkResults`.

```python
result = benchmark.create_enhanced_benchmark_result(
    "duckdb",
    [{"query_id": "1", "execution_time_seconds": 0.1, "status": "SUCCESS", "rows_returned": 4}],
    table_statistics={"lineitem": 10},
    data_loading_time=1.5,
)
print(result.benchmark_name, result.total_queries, result.table_statistics, result.data_loading_time)
```

```text
TPC-H 1 {'lineitem': {'rows': 10}} 1.5
```

## Properties

<span id="benchbox.base.BaseBenchmark.benchmark_name"></span>

`benchmark_name` is a read-only `str`: the human-readable benchmark name. The built-in benchmarks return names such as `"TPC-H Benchmark"` and `"ClickBench"`, and a subclass that sets no name returns its class name.

<span id="benchbox.base.BaseBenchmark.scale_factor"></span>

`scale_factor` is the `float` you passed to the constructor (1.0 = standard size, 0.01 = 1% size, 10 = 10x size). It is a plain attribute, so assigning to it later skips the constructor's validation.

<span id="benchbox.base.BaseBenchmark.output_dir"></span>

`output_dir` is the directory for generated data, stored as a `pathlib.Path` (or cloud path object). Assigning a `str` or `Path` converts it; assigning `None` clears it.

## Utility Methods

<span id="benchbox.base.BaseBenchmark.format_results"></span>

### `format_results(benchmark_result)`

Formats the dictionary returned by `run_benchmark` as a multi-line text report. It lists the query counts, the setup and total times, the average, minimum and maximum query times, and one line per query (`Query q2: FAILED - boom` for a failed one).

**Returns:** `str`. Passing a dict without the keys that `run_benchmark` produces raises `KeyError`.

### `get_data_source_benchmark()`

<span id="benchbox.base.BaseBenchmark.get_data_source_benchmark"></span>

Returns the lower-case name of the benchmark whose data this one reuses, or `None` when it generates its own. `ReadPrimitives` returns `"tpch"`, and `TPCH` returns `None`.

## Best Practices

1. **Always use platform adapters** - Call `run_with_platform` instead of direct `run_benchmark` for production use. Platform adapters provide optimized data loading and query execution, and the built-in benchmarks cannot load data through `run_benchmark`.

2. **Handle scale factors carefully** - Scale factors ≥1 must be integers. Use 0.1, 0.01, etc. for small-scale testing.

3. **Check data generation** - Call `generate_data` explicitly if you need to inspect or manipulate data files before loading.

4. **Use query subsets for debugging** - Pass `query_subset=[1]` to test single queries during development.

5. **Use SQL translation** - Call `translate_query` to adapt queries to platform-specific dialects when needed.

## See Also

- {doc}`/usage/getting-started` - Getting started guide with complete examples
- {doc}`/platforms/platform-selection-guide` - Platform adapter documentation
- {doc}`/benchmarks/index` - Available benchmark implementations
- {doc}`/reference/api-reference` - High-level API overview
