# TPC-DS Benchmark API

```{tags} reference, python-api, tpc-ds
```

Python API reference for the TPC-DS benchmark.

## Overview

The TPC-DS benchmark models a retail product supplier with 99 complex decision support queries. It includes advanced SQL features like window functions, complex joins, and subqueries.

**Key Features**:

- 99 decision support queries with varying complexity
- 25 tables modeling retail operations
- Advanced SQL features (window functions, CTEs, complex joins)
- Query variants for different data distributions
- Data and queries generated with the TPC-DS `dsdgen` and `dsqgen` tools
- Scale factors from 0.001 up to 100000

## Quick Start

```python
from benchbox import TPCDS
from benchbox.platforms.duckdb import DuckDBAdapter

# Create benchmark
benchmark = TPCDS(scale_factor=1.0)

# Generate data
benchmark.generate_data()

# Run on platform
adapter = DuckDBAdapter()
results = benchmark.run_with_platform(adapter)

print(f"Completed in {results.total_execution_time:.2f}s")
```

The DuckDB adapter needs the `duckdb` package. Scale factor 1.0 writes about 1 GB.

## API Reference

### TPCDS Class

#### `benchbox.TPCDS`

<span id="benchbox.tpcds.TPCDS"></span>

Creates a TPC-DS benchmark that generates the 25 TPC-DS tables with `dsdgen` and serves the 99 TPC-DS queries.

**Import:** `from benchbox import TPCDS` · **Extras:** none

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `scale_factor` | `float` | `1.0` | Data size multiplier. Must be a number from 0.001 up to 100000. Values of 1 or more must be whole numbers. |
| `output_dir` | `str`, `Path` or `None` | `None` | Directory for generated data files. When `None`, the directory is `benchmark_runs/datagen/tpcds_<sf token>` under the current directory (for example `tpcds_sf001` for 0.01), or under `$BENCHBOX_OUTPUT_DIR/datagen` when that variable is set. |
| `**kwargs` | keyword arguments | none | See the list below. |

Keyword arguments that the constructor acts on:

- `parallel` (`int`, default `1`): number of `dsdgen` processes. Files are then named `<table>_<chunk>_<parallel>.dat`. At scale factor 0.01 with `parallel=2`, only the first chunk file was written per table and it held all rows (28,810 `store_sales` rows, as with `parallel=1`).
- `force_regenerate` (`bool`, default `False`): regenerate data even when a valid set exists in `output_dir`.
- `official` (`bool`, default `False`): mark the run as an official run; it only affects the compliance class.
- `compress_data` (`bool`): write `.zst` files; add `compression_type="gzip"` for `.gz`. An unsupported `compression_type` raises `ValueError`.
- `verbose` (`bool` or `int`) and `quiet` (`bool`): log level.

Any other keyword is stored as an attribute on the instance. `update_percentage` and similar options have no effect.

The constructor creates no files. Data is written by `generate_data()`.

##### Returns

A `TPCDS` instance. It subclasses `BaseBenchmark`; see {doc}`/reference/python-api/base` for the shared interface.

##### Raises

- `TypeError` when `scale_factor` is not a number, or `parallel` is not an integer.
- `ValueError` when `scale_factor` is zero or negative, is below 0.001 or above 100000, or is 1 or more and not a whole number; or when `parallel` is below 1.

##### Example

```python
from benchbox import TPCDS

benchmark = TPCDS(scale_factor=0.01, output_dir="tpcds_data")
files = benchmark.generate_data()
print(len(files), len(benchmark.get_queries()))
print(sorted(benchmark.tables)[:3])
```

Output on 0.4.1:

```text
25 99
['call_center', 'catalog_page', 'catalog_returns']
```

##### Compatibility

`benchbox.tpcds.TPCDS` is the same class. Unlike `TPCH`, the instance has no `compliance_class` attribute; the classification (`official`, `unofficial_nonstandard` or `unofficial_subscale`) exists only on the internal implementation. The `queries` and `generator` properties return internal objects whose methods are not part of the contract. `generate_table_data` fails on 0.4.1.

### Constructor

<span id="benchbox.tpcds.TPCDS.__init__"></span>

`TPCDS(scale_factor=1.0, output_dir=None, **kwargs)`. The arguments are in the Parameters table above.

## Methods

### generate_data()

<span id="benchbox.tpcds.TPCDS.generate_data"></span>

`generate_data() -> list` runs `dsdgen` and returns the data files. The result is a list with one entry per table (25 entries), and each entry is itself a **list** of `pathlib.Path` (one path unless the table was written in chunks). `benchmark.tables` maps each table name to the same list. The signature is annotated `list[str | Path]`, but the entries are lists.

The files are pipe-delimited `.dat` files named after the table (`store_sales.dat`). The directory also receives `_datagen_manifest.json`. At scale factor 0.01 the 25 files total 26 MB, with 28,810 `store_sales` rows, 73,049 `date_dim` rows, 1,000 `customer` rows and 180 `item` rows. A second call finds the valid data and returns at once, unless `force_regenerate=True`.

```python
data_files = benchmark.generate_data()
print(f"Generated {len(data_files)} table files")
# Generated 25 table files
```

### get_query(query_id, \*, params=None, seed=None, scale_factor=None, dialect=None)

<span id="benchbox.tpcds.TPCDS.get_query"></span>

`get_query(query_id, *, params=None, seed=None, scale_factor=None, dialect=None, **kwargs) -> str` returns one query as SQL text generated by `dsqgen`.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `query_id` | `int` | required | `1` to `99`. Strings such as `"1"` raise `TypeError`. |
| `params` | `dict` or `None` | `None` | Optional keys: `seed`, `scale_factor`, `stream_id` (used as the seed) and `permutation` (a list of query ids; the seed is the query's index in it). The `seed` and `scale_factor` arguments take precedence. Other keys are ignored. |
| `seed` | `int` or `None` | `None` | RNG seed for the query parameters. The same seed always gives the same text; `None` also gives a fixed text. |
| `scale_factor` | `float` or `None` | `None` | Scale factor used for scale-dependent parameters, in place of the benchmark's own. Must be positive. For 10 of the 99 queries the text changes with it (1, 9, 16, 27, 34, 36, 44, 46, 68, 73). |
| `dialect` | `str` or `None` | `None` | Target SQL dialect, translated with SQLGlot from `netezza`. |
| `base_dialect` (keyword) | `str` or `None` | `None` | Source dialect for the translation, default `netezza`. |
| `variant` (keyword) | `str` or `None` | `None` | `"a"` or `"b"` for the four queries that have two forms: 14, 23, 24 and 39. `"a"` equals `None`. Any other query or value raises an error (`ValueError` for a bad value, `TPCDSError` when `dsqgen` has no such template). |

Raises `TypeError` for a non-integer `query_id` or `seed` or a non-numeric `scale_factor`, and `ValueError` for a `query_id` outside 1 to 99 (`Query ID must be 1-99, got 0`) or a `scale_factor` that is not positive.

```python
# Get query 1
q1 = benchmark.get_query(1)

# Get with dialect translation
q1_bq = benchmark.get_query(1, dialect="bigquery")

# Get with a seed and scale factor 10
q1_param = benchmark.get_query(1, seed=42, scale_factor=10.0)

# Second form of query 14
q14_b = benchmark.get_query(14, variant="b")
```

### get_queries(dialect=None, base_dialect=None)

<span id="benchbox.tpcds.TPCDS.get_queries"></span>

`get_queries(dialect=None, base_dialect=None) -> dict[str, str]` returns all 99 queries keyed `"1"` to `"99"` (string keys).

Unlike `get_query`, it always renders scale-dependent parameters for scale factor 1. On a benchmark with `scale_factor=0.01`, queries 9, 44, 46 and 68 differ from `get_query(i)`; they match `get_query(i, scale_factor=1)`.

With a `dialect`, each query is translated from `base_dialect` (default `netezza`) with SQLGlot.

```python
# Get all queries
queries = benchmark.get_queries()
print(f"Total queries: {len(queries)}")
# Total queries: 99

# Get with dialect translation
queries_bq = benchmark.get_queries(dialect="bigquery")
```

### get_available_queries()

<span id="benchbox.tpcds.TPCDS.get_available_queries"></span>

`get_available_queries() -> list[int]` returns the integers 1 to 99.

```python
query_ids = benchmark.get_available_queries()
print(f"Available queries: {len(query_ids)}")
# Available queries: 99
```

### get_available_tables()

<span id="benchbox.tpcds.TPCDS.get_available_tables"></span>

`get_available_tables() -> list[str]` returns 24 table names in alphabetical order, from `call_center` to `web_site`. It leaves out `dbgen_version`, which `generate_data()`, `tables` and `get_schema()` include (25 tables).

```python
tables = benchmark.get_available_tables()
print(f"Tables: {', '.join(tables[:3])}, ...")
# Tables: call_center, catalog_page, catalog_returns, ...
```

### generate_table_data(table_name, output_dir=None)

<span id="benchbox.tpcds.TPCDS.generate_table_data"></span>

`generate_table_data(table_name, output_dir=None)` is meant to generate the rows of one table. On 0.4.1 it raises `AttributeError` (`'TPCDSDataGenerator' object has no attribute 'generate_table'`, or `'TPCDSCTools' object has no attribute 'generate_data_table'` when `output_dir` is given). Use `generate_data()` instead.

### get_schema()

<span id="benchbox.tpcds.TPCDS.get_schema"></span>

`get_schema() -> dict` returns a mapping from table name to a definition with `name` and `columns`, for 25 tables. Each column is a dict with `name`, `type`, `nullable`, `primary_key` and `foreign_key` (`None` or a `(table, column)` tuple). The annotation says `list[dict]`, but the value is a dict.

```python
schema = benchmark.get_schema()
for name in ("store_sales", "date_dim"):
    print(f"{schema[name]['name']}: {len(schema[name]['columns'])} columns")
# store_sales: 23 columns
# date_dim: 28 columns
```

### get_create_tables_sql(dialect="standard", tuning_config=None)

<span id="benchbox.tpcds.TPCDS.get_create_tables_sql"></span>

`get_create_tables_sql(dialect="standard", tuning_config=None) -> str` returns the `CREATE TABLE` statements for the 25 tables.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `dialect` | `str` | `"standard"` | Accepted but has no effect: `standard` and `bigquery` return the same script. |
| `tuning_config` | `UnifiedTuningConfiguration` or `None` | `None` | With `None`, no constraints are emitted. A new `UnifiedTuningConfiguration()` enables primary and foreign keys, adding 23 `PRIMARY KEY` and 87 `FOREIGN KEY` clauses. |

```python
from benchbox.core.tuning.interface import UnifiedTuningConfiguration

create_sql = benchmark.get_create_tables_sql()
create_sql_keys = benchmark.get_create_tables_sql(tuning_config=UnifiedTuningConfiguration())
print(create_sql.count("PRIMARY KEY"), create_sql_keys.count("PRIMARY KEY"), create_sql_keys.count("FOREIGN KEY"))
# 0 23 87
```

### generate_streams(num_streams=1, rng_seed=None, streams_output_dir=None)

<span id="benchbox.tpcds.TPCDS.generate_streams"></span>

`generate_streams(num_streams=1, rng_seed=None, streams_output_dir=None) -> list[Path]` writes one SQL file per stream and returns the paths.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `num_streams` | `int` | `1` | Number of streams. |
| `rng_seed` | `int` or `None` | `None` | Base seed. `None` and `0` both mean 42. |
| `streams_output_dir` | `str`, `Path` or `None` | `None` | Output directory, created if missing. When `None`, `<output_dir>/streams`. |

The files are named `stream_0.sql`, `stream_1.sql` and so on. Each starts with comment lines (stream id, scale factor, seed), then every query of the stream in its permuted order with a `-- Query N (Stream S, Position P)` comment. A stream holds 103 entries: the 99 queries with 14, 23, 24 and 39 each split into an `a` and a `b` part.

```python
# Generate 4 concurrent streams
streams = benchmark.generate_streams(
    num_streams=4,
    rng_seed=42,
    streams_output_dir="./streams"
)

for stream_path in streams:
    print(f"Stream: {stream_path}")
# Stream: streams/stream_0.sql
# Stream: streams/stream_1.sql
# Stream: streams/stream_2.sql
# Stream: streams/stream_3.sql
```

### get_stream_info(stream_id)

<span id="benchbox.tpcds.TPCDS.get_stream_info"></span>

`get_stream_info(stream_id) -> dict` describes one stream as `generate_streams` would produce it with seed 42, whatever seed you passed there. Keys: `stream_id`, `scale_factor`, `query_count` (103), `unique_query_count` (103), `rng_seed` (`42 + stream_id`), `parameter_seed` (`1042 + stream_id`), `query_order` (query ids in execution order, with 14, 23, 24 and 39 appearing twice), `query_list` (the same with `a`/`b` suffixes) and `permutation_mode` (`"tpcds_standard"`).

Raises `ValueError` for a negative id or an id of 100 or more.

### get_all_streams_info()

<span id="benchbox.tpcds.TPCDS.get_all_streams_info"></span>

`get_all_streams_info() -> list[dict]` returns `get_stream_info` for streams 0 and 1. The wrapper takes no arguments, so the stream count cannot be changed.

### get_benchmark_info()

<span id="benchbox.tpcds.TPCDS.get_benchmark_info"></span>

`get_benchmark_info() -> dict` returns `name` (`"TPC-DS"`), `scale_factor`, `available_tables` (24 names), `available_queries` (1 to 99), `c_tools_info` (the location of the bundled `dsdgen` and `dsqgen` and the templates) and `maintenance_test_supported` (`True`).

## Properties

### queries

<span id="benchbox.tpcds.TPCDS.queries"></span>

`queries` returns the internal query manager (a `TPCDSQueryManager`). Its methods are not part of the contract. Use `get_query()`, `get_queries()` and `get_available_queries()`.

### generator

<span id="benchbox.tpcds.TPCDS.generator"></span>

`generator` returns the internal data generator (a `TPCDSDataGenerator`). Its methods are not part of the contract. Use `generate_data()` and `get_schema()`.

### Inherited members

Every other member comes from `BaseBenchmark`. See {doc}`/reference/python-api/base` for what they do. The ids on this page for the inherited members are kept in the table.

| Group | Member | Kind | Notes |
| --- | --- | --- | --- |
| Run and results | <span id="benchbox.tpcds.TPCDS.cleanup"></span>`cleanup` | method | |
| Run and results | <span id="benchbox.tpcds.TPCDS.create_enhanced_benchmark_result"></span>`create_enhanced_benchmark_result` | method | |
| Run and results | <span id="benchbox.tpcds.TPCDS.create_minimal_benchmark_result"></span>`create_minimal_benchmark_result` | method | |
| Run and results | <span id="benchbox.tpcds.TPCDS.format_results"></span>`format_results` | method | |
| Run and results | <span id="benchbox.tpcds.TPCDS.run_benchmark"></span>`run_benchmark` | method | |
| Run and results | <span id="benchbox.tpcds.TPCDS.run_query"></span>`run_query` | method | |
| Run and results | <span id="benchbox.tpcds.TPCDS.run_with_platform"></span>`run_with_platform` | method | |
| Run and results | <span id="benchbox.tpcds.TPCDS.setup_database"></span>`setup_database` | method | |
| Run and results | <span id="benchbox.tpcds.TPCDS.translate_query"></span>`translate_query` | method | |
| Validation | <span id="benchbox.tpcds.TPCDS.validate_loaded_data"></span>`validate_loaded_data` | method | |
| Validation | <span id="benchbox.tpcds.TPCDS.validate_manifest"></span>`validate_manifest` | method | |
| Validation | <span id="benchbox.tpcds.TPCDS.validate_preflight"></span>`validate_preflight` | method | |
| Verbosity and logging | <span id="benchbox.tpcds.TPCDS.apply_verbosity"></span>`apply_verbosity` | method | |
| Verbosity and logging | <span id="benchbox.tpcds.TPCDS.log_debug_info"></span>`log_debug_info` | method | |
| Verbosity and logging | <span id="benchbox.tpcds.TPCDS.log_error_with_debug_info"></span>`log_error_with_debug_info` | method | |
| Verbosity and logging | <span id="benchbox.tpcds.TPCDS.log_notice"></span>`log_notice` | method | |
| Verbosity and logging | <span id="benchbox.tpcds.TPCDS.log_operation_complete"></span>`log_operation_complete` | method | |
| Verbosity and logging | <span id="benchbox.tpcds.TPCDS.log_operation_start"></span>`log_operation_start` | method | |
| Verbosity and logging | <span id="benchbox.tpcds.TPCDS.log_verbose"></span>`log_verbose` | method | |
| Verbosity and logging | <span id="benchbox.tpcds.TPCDS.log_version_warning"></span>`log_version_warning` | method | |
| Verbosity and logging | <span id="benchbox.tpcds.TPCDS.log_very_verbose"></span>`log_very_verbose` | method | |
| Verbosity and logging | <span id="benchbox.tpcds.TPCDS.logger"></span>`logger` | property | |
| Verbosity and logging | <span id="benchbox.tpcds.TPCDS.quiet"></span>`quiet` | class attribute | |
| Verbosity and logging | <span id="benchbox.tpcds.TPCDS.verbose"></span>`verbose` | class attribute | |
| Verbosity and logging | <span id="benchbox.tpcds.TPCDS.verbose_enabled"></span>`verbose_enabled` | class attribute | |
| Verbosity and logging | <span id="benchbox.tpcds.TPCDS.verbose_level"></span>`verbose_level` | class attribute | |
| Verbosity and logging | <span id="benchbox.tpcds.TPCDS.verbosity_settings"></span>`verbosity_settings` | property | |
| Verbosity and logging | <span id="benchbox.tpcds.TPCDS.very_verbose"></span>`very_verbose` | class attribute | |
| Data and configuration | <span id="benchbox.tpcds.TPCDS.api_surface"></span>`api_surface` | class attribute | |
| Data and configuration | <span id="benchbox.tpcds.TPCDS.benchmark_name"></span>`benchmark_name` | property | |
| Data and configuration | <span id="benchbox.tpcds.TPCDS.csv_delimiter"></span>`csv_delimiter` | property | `None`. |
| Data and configuration | <span id="benchbox.tpcds.TPCDS.csv_null_marker"></span>`csv_null_marker` | property | `None`. |
| Data and configuration | <span id="benchbox.tpcds.TPCDS.DATA_SOURCE_BENCHMARK"></span>`DATA_SOURCE_BENCHMARK` | class attribute | `None`: TPC-DS generates its own data. |
| Data and configuration | <span id="benchbox.tpcds.TPCDS.get_csv_loading_config"></span>`get_csv_loading_config` | method | `None`. |
| Data and configuration | <span id="benchbox.tpcds.TPCDS.get_data_source_benchmark"></span>`get_data_source_benchmark` | method | |
| Data and configuration | <span id="benchbox.tpcds.TPCDS.output_dir"></span>`output_dir` | property | The resolved directory from the constructor argument. |
| Data and configuration | <span id="benchbox.tpcds.TPCDS.run_with_platform_api_surface"></span>`run_with_platform_api_surface` | class attribute | |
| Data and configuration | <span id="benchbox.tpcds.TPCDS.scale_factor"></span>`scale_factor` | instance attribute | The constructor argument. |
| Data and configuration | <span id="benchbox.tpcds.TPCDS.SKIP_DATA_LOADING"></span>`SKIP_DATA_LOADING` | class attribute | Defined on `BaseBenchmark` from 0.4.2, default `False`. Set it to `True` for a benchmark that needs schema objects but no data files. |
| Data and configuration | <span id="benchbox.tpcds.TPCDS.tables"></span>`tables` | property | Empty until `generate_data()` has run, then the table-to-paths mapping. |

## Usage Examples

### Basic Benchmark Run

```python
from benchbox import TPCDS
from benchbox.platforms.duckdb import DuckDBAdapter

# Create benchmark with scale factor 1 (about 1 GB)
benchmark = TPCDS(scale_factor=1.0)

# Generate data
benchmark.generate_data()

# Run on DuckDB
adapter = DuckDBAdapter()
results = benchmark.run_with_platform(adapter)

# Print results
print(f"Benchmark: {results.benchmark_name}")
print(f"Total time: {results.total_execution_time:.2f}s")
print(f"Queries: {results.successful_queries}/{results.total_queries}")
```

### Query Subset Execution

```python
from benchbox import TPCDS
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = TPCDS(scale_factor=0.1)
benchmark.generate_data()

adapter = DuckDBAdapter()
conn = adapter.create_connection()

# Load data
adapter.create_schema(benchmark, conn)
adapter.load_data(benchmark, conn, benchmark.output_dir)

# Execute the first ten queries
for query_id in range(1, 11):
    query = benchmark.get_query(query_id)
    result = adapter.execute_query(conn, query, f"query{query_id}")
    print(f"Query {query_id}: {result['execution_time_seconds']:.3f}s")
```

### Query Complexity Analysis

```python
from benchbox import TPCDS
import re

benchmark = TPCDS(scale_factor=1.0)
queries = benchmark.get_queries()

complexity_metrics = []

for query_id, query_text in queries.items():
    metrics = {
        "query_id": query_id,
        "lines": len(query_text.split("\n")),
        "joins": query_text.upper().count("JOIN"),
        "subqueries": query_text.upper().count("SELECT") - 1,
        "window_functions": len(re.findall(r'\bOVER\s*\(', query_text, re.IGNORECASE)),
        "ctes": query_text.upper().count("WITH"),
    }
    complexity_metrics.append(metrics)

# Sort by complexity
sorted_queries = sorted(
    complexity_metrics,
    key=lambda x: (x["subqueries"], x["joins"], x["window_functions"]),
    reverse=True
)

print("Top 5 most complex queries:")
for q in sorted_queries[:5]:
    print(f"Query {q['query_id']}: {q['subqueries']} subqueries, "
          f"{q['joins']} joins, {q['window_functions']} window functions")
```

### Multi-Platform Comparison

Run the same generated data through several adapters and compare the result objects. This example uses two DuckDB configurations; add other adapters to the dictionary the same way.

```python
from benchbox import TPCDS
from benchbox.platforms.duckdb import DuckDBAdapter
import pandas as pd

benchmark = TPCDS(scale_factor=0.1, output_dir="./data/tpcds_sf01")
benchmark.generate_data()

platforms = {
    "DuckDB 1GB": DuckDBAdapter(memory_limit="1GB"),
    "DuckDB 4GB": DuckDBAdapter(memory_limit="4GB"),
}

results_data = []

for name, adapter in platforms.items():
    results = benchmark.run_with_platform(adapter)

    results_data.append({
        "platform": name,
        "total_time": results.total_execution_time,
        "avg_query_time": results.average_query_time,
        "successful": results.successful_queries,
        "failed": results.failed_queries,
    })

df = pd.DataFrame(results_data)
print(df)
```

### Variant Testing

```python
from benchbox import TPCDS

benchmark = TPCDS(scale_factor=1.0)

# Generate queries with different seeds
variants = {}
for seed in [42, 123, 456]:
    variant_queries = {}
    for query_id in range(1, 100):
        variant_queries[query_id] = benchmark.get_query(
            query_id,
            seed=seed
        )
    variants[seed] = variant_queries

# Compare query variants
q1_v1 = variants[42][1]
q1_v2 = variants[123][1]
if q1_v1 != q1_v2:
    print("Query 1 has parametrized variants")
```

### Stream-Based Testing

```python
from benchbox import TPCDS
from benchbox.platforms.duckdb import DuckDBAdapter
import concurrent.futures

benchmark = TPCDS(scale_factor=0.01)
benchmark.generate_data()

# Generate 4 streams
streams = benchmark.generate_streams(num_streams=4, rng_seed=42)

adapter = DuckDBAdapter()

def run_stream(stream_id):
    stream_info = benchmark.get_stream_info(stream_id)
    total_time = 0

    conn = adapter.create_connection()
    adapter.create_schema(benchmark, conn)
    adapter.load_data(benchmark, conn, benchmark.output_dir)

    for query_id in stream_info["query_order"]:
        query = benchmark.get_query(query_id)
        result = adapter.execute_query(conn, query, f"q{query_id}")
        total_time += result["execution_time_seconds"]

    return {"stream_id": stream_id, "total_time": total_time}

# Run streams in parallel
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(run_stream, i) for i in range(4)]
    results = [f.result() for f in concurrent.futures.as_completed(futures)]

for r in sorted(results, key=lambda r: r["stream_id"]):
    print(f"Stream {r['stream_id']}: {r['total_time']:.2f}s")
```

## See Also

- {doc}`index` - Benchmark API overview
- {doc}`tpch` - TPC-H benchmark API
- {doc}`../base` - Base benchmark interface
- {doc}`../results` - Results API
- {doc}`/benchmarks/tpc-ds` - TPC-DS guide
- {doc}`/guides/tpc/tpc-ds-official-guide` - Official benchmark guide
