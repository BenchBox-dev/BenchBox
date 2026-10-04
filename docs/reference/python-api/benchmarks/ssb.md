# SSB (Star Schema Benchmark) API

```{tags} reference, python-api, ssb
```

Python API reference for the Star Schema Benchmark (SSB).

## Overview

The Star Schema Benchmark (SSB) is a simplified variant of TPC-H specifically designed for testing OLAP systems and data warehouses. It transforms the normalized TPC-H schema into a denormalized star schema that better represents typical data warehouse designs.

**Key Features**:

- **Star schema design** - Single fact table (`lineorder`) with four dimension tables
- **13 analytical queries** - Organized into 4 logical flights
- **Simplified query patterns** - Focus on aggregation and filtering
- **OLAP-oriented** - Tests typical data warehouse patterns
- **Parameterized queries** - Configurable selectivity
- **Performance-focused** - Stresses aggregation and scan performance
- **Any positive scale factor** - 1.0 generates 6,000,000 `lineorder` rows

## Quick Start

```python
from benchbox import SSB
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = SSB(scale_factor=1.0)

benchmark.generate_data()

adapter = DuckDBAdapter()
results = benchmark.run_with_platform(adapter)

print(f"Completed in {results.total_execution_time:.2f}s")
```

The DuckDB adapter needs the `duckdb` package. Scale factor 1.0 writes about 610 MB.

## API Reference

### SSB Class

#### `benchbox.SSB`

<span id="benchbox.ssb.SSB"></span>

Creates a Star Schema Benchmark that generates five tables (`date`, `customer`, `supplier`, `part`, `lineorder`) and serves the 13 SSB queries.

**Import:** `from benchbox import SSB` · **Extras:** none

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `scale_factor` | `float` | `1.0` | Data size multiplier. Must be positive. Values of 1 or more must be whole numbers. 1.0 generates 6,000,000 `lineorder` rows and 0.01 generates 60,000. |
| `output_dir` | `str`, `Path` or `None` | `None` | Directory for generated data files. When `None`, the directory is `benchmark_runs/datagen/ssb_<sf token>` under the current directory (for example `ssb_sf001` for 0.01), or under `$BENCHBOX_OUTPUT_DIR/datagen` when that variable is set. |
| `**kwargs` | keyword arguments | none | `verbose` (`bool` or `int`) and `quiet` (`bool`) set the log level. `force_regenerate` is forwarded to the data generator. `compress_data=True` writes each table as `<table>.tbl.zst`; add `compression_type="gzip"` for `.gz`; `compression_level` sets the level. `compression_type` alone, without `compress_data=True`, has no effect, and an unsupported type raises `ValueError`. Any other keyword is stored as an attribute on the instance and otherwise ignored. |

The constructor creates no files. Data is written by `generate_data()`.

##### Returns

An `SSB` instance. It subclasses `BaseBenchmark`; see {doc}`/reference/python-api/base` for the shared interface.

##### Raises

`ValueError` when `scale_factor` is zero or negative, when it is 1 or more and not a whole number, or when `compression_type` is not one of `none`, `gzip`, `zstd`.

##### Example

```python
from benchbox import SSB

benchmark = SSB(scale_factor=0.01, output_dir="ssb_data")
files = benchmark.generate_data()
print(sorted(files))
print(list(benchmark.get_queries()))
```

Output on 0.4.1:

```text
['customer', 'date', 'lineorder', 'part', 'supplier']
['Q1.1', 'Q1.2', 'Q1.3', 'Q2.1', 'Q2.2', 'Q2.3', 'Q3.1', 'Q3.2', 'Q3.3', 'Q3.4', 'Q4.1', 'Q4.2', 'Q4.3']
```

##### Compatibility

`benchbox.ssb.SSB` is the same class. `generate_data()` and `get_schema()` return dicts although their annotations say `list`.

### Constructor

<span id="benchbox.ssb.SSB.__init__"></span>

`SSB(scale_factor=1.0, output_dir=None, **kwargs)`. The arguments are in the Parameters table above. `date_range_years` and `partition_fact_table` have no effect; they are only stored as attributes.

## Methods

### generate_data()

<span id="benchbox.ssb.SSB.generate_data"></span>

`generate_data()` writes one pipe-delimited `.tbl` file per table, without a header row, plus `_datagen_manifest.json`. It returns a `dict` that maps table name to file path (the signature is annotated `list[str | Path]`, but the value is a dict). `benchmark.tables` holds the same mapping.

At scale factor 0.01:

| Table | Rows | Size |
| --- | --- | --- |
| `date` | 2,557 | 216 KB |
| `customer` | 300 | 27 KB |
| `supplier` | 20 | 1.5 KB |
| `part` | 2,000 | 130 KB |
| `lineorder` | 60,000 | 5.5 MB |

```python
data_files = benchmark.generate_data()
print(f"Generated {len(data_files)} table files")
```

This prints `Generated 5 table files`.

### get_query(query_id, \*, params=None)

<span id="benchbox.ssb.SSB.get_query"></span>

`get_query(query_id, *, params=None) -> str` returns one query as SQL text.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `query_id` | `str` | required | `"Q1.1"` to `"Q4.3"` (13 ids). Ids are case-sensitive: `"1.1"` and `"q1.1"` are rejected. |
| `params` | `dict` or `None` | `None` | Values that replace the defaults below. Names that the query does not use are ignored. |

Raises `ValueError` for an unknown id: `Invalid query ID: q1.1. Available: Q1.1, Q1.2, ...`.

Parameter names and defaults:

| Parameter | Default | Used by |
| --- | --- | --- |
| `year` | `1993` | Q1.1, Q1.3 |
| `year_month` | `199401` (`"Dec1997"` for Q3.4) | Q1.2, Q3.4 |
| `week` | `6` | Q1.3 |
| `discount_min`, `discount_max` | `1`, `3` | Q1.1, Q1.2, Q1.3 |
| `quantity` | `25` | Q1.1 |
| `quantity_min`, `quantity_max` | `26`, `35` | Q1.2, Q1.3 |
| `category` | `"MFGR#12"` | Q2.1, Q4.3 |
| `brand_min`, `brand_max` | `"MFGR#2221"`, `"MFGR#2228"` | Q2.2 |
| `brand` | `"MFGR#2221"` | Q2.3 |
| `region` | `"AMERICA"` | Q2.1, Q2.2, Q2.3 (supplier region); Q4.1, Q4.2, Q4.3 (customer and supplier region) |
| `c_region`, `s_region` | `"ASIA"` | Q3.1 |
| `c_nation`, `s_nation` | `"UNITED STATES"` | Q3.2 |
| `c_city1`, `c_city2`, `s_city1`, `s_city2` | `"UNITED KI1"`, `"UNITED KI5"`, `"UNITED KI1"`, `"UNITED KI5"` | Q3.3, Q3.4 |
| `year_min`, `year_max` | `1992`, `1997` | Q3.1, Q3.2, Q3.3 |
| `mfgr1`, `mfgr2` | `"MFGR#1"`, `"MFGR#2"` | Q4.1, Q4.2 |
| `year1`, `year2` | `1997`, `1998` | Q4.2, Q4.3 |

```python
q1_1 = benchmark.get_query("Q1.1")

q2_1 = benchmark.get_query("Q2.1", params={
    "category": "MFGR#12",
    "region": "EUROPE"
})

q3_1 = benchmark.get_query("Q3.1")
```

### get_queries(dialect=None)

<span id="benchbox.ssb.SSB.get_queries"></span>

`get_queries(dialect=None) -> dict[str, str]` returns all 13 queries keyed `"Q1.1"` to `"Q4.3"`, rendered with the default parameters.

With a `dialect`, each query is translated with SQLGlot. DuckDB output for Q1.1 starts `SELECT SUM("lo_extendedprice" * "lo_discount") AS "revenue" FROM "lineorder", "date" ...`: identifiers are quoted and the trailing semicolon is dropped.

```python
queries = benchmark.get_queries()
print(f"Total queries: {len(queries)}")

queries_ch = benchmark.get_queries(dialect="clickhouse")
```

The first print shows `Total queries: 13`.

### get_schema()

<span id="benchbox.ssb.SSB.get_schema"></span>

`get_schema() -> dict` returns a mapping from table name to a definition with `name` and `columns`. The keys, in order, are `date` (17 columns), `customer` (8), `supplier` (7), `part` (9) and `lineorder` (17). The annotation says `list[dict]`, but the value is a dict.

```python
schema = benchmark.get_schema()
for name, table in schema.items():
    print(f"{table['name']}: {len(table['columns'])} columns")
```

### get_create_tables_sql(dialect="standard", tuning_config=None)

<span id="benchbox.ssb.SSB.get_create_tables_sql"></span>

`get_create_tables_sql(dialect="standard", tuning_config=None) -> str` returns the `CREATE TABLE` statements for all five tables, `date` first.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `dialect` | `str` | `"standard"` | Accepted but has no effect: `standard`, `duckdb` and `clickhouse` return the same script. |
| `tuning_config` | `UnifiedTuningConfiguration` or `None` | `None` | With `None`, no constraints are emitted. When `tuning_config.primary_keys.enabled` is true (the default of a new `UnifiedTuningConfiguration()`), five `PRIMARY KEY` clauses are added; no foreign keys are emitted. |

```python
from benchbox.core.tuning.interface import UnifiedTuningConfiguration

create_sql = benchmark.get_create_tables_sql()
create_sql_pk = benchmark.get_create_tables_sql(tuning_config=UnifiedTuningConfiguration())
print(create_sql.count("PRIMARY KEY"), create_sql_pk.count("PRIMARY KEY"))
```

This prints `0 5`.

### Inherited members

Every other member comes from `BaseBenchmark`. See {doc}`/reference/python-api/base` for what they do. The ids on this page for the inherited members are kept in the table.

| Group | Member | Kind | Notes |
| --- | --- | --- | --- |
| Run and results | <span id="benchbox.ssb.SSB.cleanup"></span>`cleanup` | method | |
| Run and results | <span id="benchbox.ssb.SSB.create_enhanced_benchmark_result"></span>`create_enhanced_benchmark_result` | method | |
| Run and results | <span id="benchbox.ssb.SSB.create_minimal_benchmark_result"></span>`create_minimal_benchmark_result` | method | |
| Run and results | <span id="benchbox.ssb.SSB.format_results"></span>`format_results` | method | |
| Run and results | <span id="benchbox.ssb.SSB.run_benchmark"></span>`run_benchmark` | method | |
| Run and results | <span id="benchbox.ssb.SSB.run_query"></span>`run_query` | method | |
| Run and results | <span id="benchbox.ssb.SSB.run_with_platform"></span>`run_with_platform` | method | |
| Run and results | <span id="benchbox.ssb.SSB.setup_database"></span>`setup_database` | method | |
| Run and results | <span id="benchbox.ssb.SSB.translate_query"></span>`translate_query` | method | |
| Validation | <span id="benchbox.ssb.SSB.validate_loaded_data"></span>`validate_loaded_data` | method | |
| Validation | <span id="benchbox.ssb.SSB.validate_manifest"></span>`validate_manifest` | method | |
| Validation | <span id="benchbox.ssb.SSB.validate_preflight"></span>`validate_preflight` | method | |
| Verbosity and logging | <span id="benchbox.ssb.SSB.apply_verbosity"></span>`apply_verbosity` | method | |
| Verbosity and logging | <span id="benchbox.ssb.SSB.log_debug_info"></span>`log_debug_info` | method | |
| Verbosity and logging | <span id="benchbox.ssb.SSB.log_error_with_debug_info"></span>`log_error_with_debug_info` | method | |
| Verbosity and logging | <span id="benchbox.ssb.SSB.log_notice"></span>`log_notice` | method | |
| Verbosity and logging | <span id="benchbox.ssb.SSB.log_operation_complete"></span>`log_operation_complete` | method | |
| Verbosity and logging | <span id="benchbox.ssb.SSB.log_operation_start"></span>`log_operation_start` | method | |
| Verbosity and logging | <span id="benchbox.ssb.SSB.log_verbose"></span>`log_verbose` | method | |
| Verbosity and logging | <span id="benchbox.ssb.SSB.log_version_warning"></span>`log_version_warning` | method | |
| Verbosity and logging | <span id="benchbox.ssb.SSB.log_very_verbose"></span>`log_very_verbose` | method | |
| Verbosity and logging | <span id="benchbox.ssb.SSB.logger"></span>`logger` | property | |
| Verbosity and logging | <span id="benchbox.ssb.SSB.quiet"></span>`quiet` | class attribute | |
| Verbosity and logging | <span id="benchbox.ssb.SSB.verbose"></span>`verbose` | class attribute | |
| Verbosity and logging | <span id="benchbox.ssb.SSB.verbose_enabled"></span>`verbose_enabled` | class attribute | |
| Verbosity and logging | <span id="benchbox.ssb.SSB.verbose_level"></span>`verbose_level` | class attribute | |
| Verbosity and logging | <span id="benchbox.ssb.SSB.verbosity_settings"></span>`verbosity_settings` | property | |
| Verbosity and logging | <span id="benchbox.ssb.SSB.very_verbose"></span>`very_verbose` | class attribute | |
| Data and configuration | <span id="benchbox.ssb.SSB.api_surface"></span>`api_surface` | class attribute | |
| Data and configuration | <span id="benchbox.ssb.SSB.benchmark_name"></span>`benchmark_name` | property | |
| Data and configuration | <span id="benchbox.ssb.SSB.csv_delimiter"></span>`csv_delimiter` | property | `None`. |
| Data and configuration | <span id="benchbox.ssb.SSB.csv_null_marker"></span>`csv_null_marker` | property | `None`. |
| Data and configuration | <span id="benchbox.ssb.SSB.DATA_SOURCE_BENCHMARK"></span>`DATA_SOURCE_BENCHMARK` | class attribute | `None`: SSB generates its own data. |
| Data and configuration | <span id="benchbox.ssb.SSB.get_csv_loading_config"></span>`get_csv_loading_config` | method | Returns `["delim='\|'", "header=false", "nullstr=''", "ignore_errors=false", "auto_detect=true"]` for every table. |
| Data and configuration | <span id="benchbox.ssb.SSB.get_data_source_benchmark"></span>`get_data_source_benchmark` | method | |
| Data and configuration | <span id="benchbox.ssb.SSB.output_dir"></span>`output_dir` | property | The resolved directory from the constructor argument. |
| Data and configuration | <span id="benchbox.ssb.SSB.run_with_platform_api_surface"></span>`run_with_platform_api_surface` | class attribute | |
| Data and configuration | <span id="benchbox.ssb.SSB.scale_factor"></span>`scale_factor` | instance attribute | The constructor argument. |
| Data and configuration | <span id="benchbox.ssb.SSB.SKIP_DATA_LOADING"></span>`SKIP_DATA_LOADING` | class attribute | Not defined in the released 0.4.1 wheel. Source builds after 0.4.1 define it on `BaseBenchmark`, default `False`. |
| Data and configuration | <span id="benchbox.ssb.SSB.tables"></span>`tables` | property | Empty until `generate_data()` has run, then the table-to-path mapping. |

## Query Flights

SSB organizes 13 queries into 4 logical flights:

### Flight 1: Simple Aggregation (Q1.1 - Q1.3)

Tests basic aggregation and filtering on the fact table. Each flight loop below only builds the query text; run it on your connection.

```python
flight_1_queries = ["Q1.1", "Q1.2", "Q1.3"]

for query_id in flight_1_queries:
    query = benchmark.get_query(query_id)
```

**Query Characteristics**:

- **Q1.1**: Year-based aggregation with discount and quantity filters
- **Q1.2**: Month-based aggregation with quantity range
- **Q1.3**: Week-based aggregation with refined quantity range

### Flight 2: Customer-Supplier Analysis (Q2.1 - Q2.3)

Tests dimension table joins and drill-down analysis.

```python
flight_2_queries = ["Q2.1", "Q2.2", "Q2.3"]

for query_id in flight_2_queries:
    query = benchmark.get_query(query_id, params={
        "region": "AMERICA"
    })
```

**Query Characteristics**:

- **Q2.1**: Part category analysis with supplier region
- **Q2.2**: Brand range analysis with supplier region
- **Q2.3**: Single brand analysis with supplier region

### Flight 3: Customer Behavior Analysis (Q3.1 - Q3.4)

Tests complex multi-dimension analysis with customer geography.

```python
flight_3_queries = ["Q3.1", "Q3.2", "Q3.3", "Q3.4"]

for query_id in flight_3_queries:
    query = benchmark.get_query(query_id)
```

**Query Characteristics**:

- **Q3.1**: Customer and supplier nation within a region
- **Q3.2**: City-level analysis within a nation
- **Q3.3**: Two specific cities, 1992-1997
- **Q3.4**: Two specific cities, one month

### Flight 4: Profit Analysis (Q4.1 - Q4.3)

Tests complex aggregation with profit calculations.

```python
flight_4_queries = ["Q4.1", "Q4.2", "Q4.3"]

for query_id in flight_4_queries:
    query = benchmark.get_query(query_id)
```

**Query Characteristics**:

- **Q4.1**: Profit (`lo_revenue - lo_supplycost`) by year and customer nation
- **Q4.2**: Profit by year, supplier nation and part category for two years
- **Q4.3**: Profit by year, supplier city and brand for one part category

## Usage Examples

### Basic Benchmark Run

```python
from benchbox import SSB
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = SSB(scale_factor=1.0)

benchmark.generate_data()

adapter = DuckDBAdapter()
results = benchmark.run_with_platform(adapter)

print(f"Benchmark: {results.benchmark_name}")
print(f"Total time: {results.total_execution_time:.2f}s")
print(f"Queries: {results.successful_queries}/{results.total_queries}")
```

Scale factor 1 is about 610 MB.

### Flight-Based Execution

```python
from benchbox import SSB
from benchbox.platforms.duckdb import DuckDBAdapter
import time

benchmark = SSB(scale_factor=0.1)
benchmark.generate_data()

adapter = DuckDBAdapter()
conn = adapter.create_connection()

adapter.create_schema(benchmark, conn)
adapter.load_data(benchmark, conn, benchmark.output_dir)

print("Flight 1: Simple Aggregation")
flight_1_queries = ["Q1.1", "Q1.2", "Q1.3"]

flight_1_times = {}
for query_id in flight_1_queries:
    query = benchmark.get_query(query_id)

    start = time.time()
    result = adapter.execute_query(conn, query, query_id)
    duration = time.time() - start

    flight_1_times[query_id] = duration
    print(f"  {query_id}: {duration:.3f}s")

print(f"Flight 1 total: {sum(flight_1_times.values()):.2f}s")
```

### Parameterized Query Execution

```python
from benchbox import SSB

benchmark = SSB(scale_factor=1.0)

custom_params = {
    "year": 1994,
    "year_month": 199401,
    "week": 6,
    "discount_min": 1,
    "discount_max": 3,
    "quantity": 25,
    "quantity_min": 26,
    "quantity_max": 35,
    "category": "MFGR#12",
    "region": "AMERICA",
    "brand_min": "MFGR#2221",
    "brand_max": "MFGR#2228",
    "brand": "MFGR#2221"
}

q1_1 = benchmark.get_query("Q1.1", params=custom_params)
q2_1 = benchmark.get_query("Q2.1", params=custom_params)

print("Q1.1 with custom year:")
print(q1_1[:200])
```

Output on 0.4.1:

```text
Q1.1 with custom year:

SELECT sum(lo_extendedprice*lo_discount) as revenue
FROM lineorder, date
WHERE lo_orderdate = d_datekey
  AND d_year = 1994
  AND lo_discount between 1 and 3
  AND lo_quantity < 25;
```

### Complete Flight Benchmark

```python
from benchbox import SSB
from benchbox.platforms.duckdb import DuckDBAdapter
import time

benchmark = SSB(scale_factor=0.1)
adapter = DuckDBAdapter()

benchmark.generate_data()
conn = adapter.create_connection()
adapter.create_schema(benchmark, conn)
adapter.load_data(benchmark, conn, benchmark.output_dir)

flights = {
    "Flight 1": ["Q1.1", "Q1.2", "Q1.3"],
    "Flight 2": ["Q2.1", "Q2.2", "Q2.3"],
    "Flight 3": ["Q3.1", "Q3.2", "Q3.3", "Q3.4"],
    "Flight 4": ["Q4.1", "Q4.2", "Q4.3"]
}

all_results = {}

for flight_name, query_ids in flights.items():
    print(f"\n{flight_name}:")
    flight_results = {}

    for query_id in query_ids:
        query = benchmark.get_query(query_id)

        start = time.time()
        result = adapter.execute_query(conn, query, query_id)
        duration = time.time() - start

        flight_results[query_id] = {
            "duration": duration,
            "status": result["status"],
            "rows": result.get("rows_returned", 0)
        }

        print(f"  {query_id}: {duration:.3f}s ({result['status']})")

    all_results[flight_name] = flight_results

print("\n" + "="*60)
print("SSB Benchmark Summary")
print("="*60)
for flight_name, flight_results in all_results.items():
    total_time = sum(r["duration"] for r in flight_results.values())
    print(f"{flight_name}: {total_time:.2f}s total")
```

### Multi-Platform Comparison

Run the same generated data through several adapters and compare the result objects. This example uses two DuckDB configurations; add other adapters to the dictionary the same way.

```python
from benchbox import SSB
from benchbox.platforms.duckdb import DuckDBAdapter
import pandas as pd

benchmark = SSB(scale_factor=0.1, output_dir="./data/ssb_sf01")
benchmark.generate_data()

platforms = {
    "DuckDB 1GB": DuckDBAdapter(memory_limit="1GB"),
    "DuckDB 4GB": DuckDBAdapter(memory_limit="4GB"),
}

results_data = []

for name, adapter in platforms.items():
    print(f"\nBenchmarking {name}...")
    results = benchmark.run_with_platform(adapter)

    results_data.append({
        "platform": name,
        "total_time": results.total_execution_time,
        "avg_query_time": results.average_query_time,
        "successful": results.successful_queries,
        "failed": results.failed_queries,
    })

df = pd.DataFrame(results_data)
print("\nBenchmark Results:")
print(df)
```

### Columnar Database Optimization

SSB is a star schema over one wide fact table (`lineorder`), which suits columnar engines. The table definitions that a platform receives are the same for every dialect, so engine-specific sort keys or codecs have to be applied by the platform adapter or by your own statements after `create_schema()`.

```python
from benchbox import SSB

benchmark = SSB(scale_factor=0.1)
ddl = benchmark.get_create_tables_sql()
print([line for line in ddl.splitlines() if line.startswith("CREATE TABLE")])
```

This prints `['CREATE TABLE date (', 'CREATE TABLE customer (', 'CREATE TABLE supplier (', 'CREATE TABLE part (', 'CREATE TABLE lineorder (']`.

### Scale Factor Comparison

```python
from benchbox import SSB
from benchbox.platforms.duckdb import DuckDBAdapter
import os
import pandas as pd

adapter = DuckDBAdapter()
scale_factors = [0.01, 0.1, 1.0]
results_data = []

for sf in scale_factors:
    print(f"\nTesting SF={sf}...")

    benchmark = SSB(scale_factor=sf, output_dir=f"./data/ssb_sf{sf}")
    data_files = benchmark.generate_data()

    results = benchmark.run_with_platform(adapter)

    results_data.append({
        "scale_factor": sf,
        "data_size_mb": sum(os.path.getsize(path) for path in data_files.values()) / 1e6,
        "total_time": results.total_execution_time,
        "avg_query_time": results.average_query_time,
        "queries_per_sec": results.total_queries / results.total_execution_time
    })

df = pd.DataFrame(results_data)
print("\nScale Factor Performance:")
print(df)
```

## See Also

- {doc}`index` - Benchmark API overview
- {doc}`tpch` - TPC-H benchmark API (normalized schema)
- {doc}`tpcds` - TPC-DS benchmark API
- {doc}`../base` - Base benchmark interface
- {doc}`../results` - Results API
- {doc}`/benchmarks/ssb` - SSB guide
- {doc}`/benchmarks/tpc-h` - TPC-H guide (SSB is derived from TPC-H)

### External Resources

- [Original SSB Paper](https://www.cs.umb.edu/~poneil/StarSchemaB.PDF) - "Star Schema Benchmark" by O'Neil et al.
- [Star Schema Design](https://en.wikipedia.org/wiki/Star_schema) - Star schema principles
- [OLAP Performance](https://link.springer.com/chapter/10.1007/978-3-642-10424-4_17) - Data warehouse benchmarking
