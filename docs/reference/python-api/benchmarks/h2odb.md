# H2O.ai Database Benchmark API

```{tags} reference, python-api, h2odb
```

Python API reference for the H2O.ai Database Benchmark.

## Overview

The H2O.ai Database Benchmark tests analytical database performance using real-world taxi trip data patterns. Developed by H2O.ai for their database benchmarking initiative, this benchmark focuses on fundamental analytical operations common in data science and machine learning workflows: aggregations, grouping, and time-series analysis.

**Key Features**:

- **Real-World Data**: Based on NYC taxi trip data structure
- **Data Science Focus**: Tests operations common in ML pipelines
- **Single-Table Design**: One `trips` table with 22 columns
- **Time-Series Operations**: Tests temporal aggregation patterns
- **Scalable**: 0.01 generates 100,000 rows and 0.1 generates 1,000,000
- **Analytics-Oriented**: Focuses on data exploration patterns

**Reference**: <https://h2oai.github.io/db-benchmark/>

## Quick Start

```python
from benchbox import H2ODB
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = H2ODB(scale_factor=0.1)
benchmark.generate_data()

adapter = DuckDBAdapter()
results = adapter.run_benchmark(benchmark)
print(results.total_queries)
```

The DuckDB adapter needs the `duckdb` package. On 0.4.1 the run executes all 10 queries and prints `10`.

## API Reference

### H2ODB Class

#### `benchbox.H2ODB`

<span id="benchbox.h2odb.H2ODB"></span>

Creates an H2O.ai benchmark that generates one table of synthetic taxi trips (`trips`) and serves ten fixed aggregation queries.

**Import:** `from benchbox import H2ODB` · **Extras:** none

##### Parameters

<span id="benchbox.h2odb.H2ODB.__init__"></span>

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `scale_factor` | `float` | `1.0` | Data size multiplier. Must be positive. Values of 1 or more must be whole numbers. 0.01 generates 100,000 rows and 0.1 generates 1,000,000. |
| `output_dir` | `str`, `Path` or `None` | `None` | Directory for generated data files. When `None`, the directory is `benchmark_runs/datagen/h2odb_<sf token>` under the current directory (for example `h2odb_sf001` for 0.01), or under `$BENCHBOX_OUTPUT_DIR/datagen` when that variable is set. |
| `**kwargs` | keyword arguments | none | `verbose` (`bool` or `int`) and `quiet` (`bool`) set the log level. `force_regenerate` is forwarded to the data generator. Any other keyword is stored as an attribute on the instance. |

The constructor creates no files. Data is written by `generate_data()`.

##### Returns

An `H2ODB` instance. It subclasses `BaseBenchmark`; see {doc}`/reference/python-api/base` for the shared interface.

##### Raises

`ValueError` when `scale_factor` is zero or negative, or when it is 1 or more and not a whole number.

##### Example

```python
from benchbox import H2ODB

benchmark = H2ODB(scale_factor=0.01, output_dir="h2o_data")
files = benchmark.generate_data()
print(files)
print(list(benchmark.get_queries()))
```

Output on 0.4.1:

```text
{'trips': 'h2o_data/trips.tbl'}
['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6', 'Q7', 'Q8', 'Q9', 'Q10']
```

##### Compatibility

`benchbox.h2odb.H2ODB` is the same class. `generate_data()` and `get_schema()` return dicts although their annotations say `list`.

#### `H2ODB.generate_data`

<span id="benchbox.h2odb.H2ODB.generate_data"></span>

`generate_data()` writes `trips.tbl` and returns a `dict` that maps the table name `trips` to its file path. The signature is annotated `list[str | Path]`, but the value is a dict on 0.4.1.

At scale factor 0.01 the file is pipe-delimited, has no header row, 100,000 rows and 14 MB, for example `1|2018-08-02 07:47:17|2018-08-02 08:23:17|1|17.67|...`. The directory also receives `_datagen_manifest.json`, and `benchmark.tables` holds the same mapping.

### Schema Methods

#### `H2ODB.get_create_tables_sql`

<span id="benchbox.h2odb.H2ODB.get_create_tables_sql"></span>

`get_create_tables_sql(dialect="standard", tuning_config=None) -> str` returns the `CREATE TABLE trips` statement.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `dialect` | `str` | `"standard"` | Accepted but has no effect; every value returns the same script. |
| `tuning_config` | `UnifiedTuningConfiguration` or `None` | `None` | Accepted but has no effect: the table defines no primary or foreign keys. |

```python
schema_sql = benchmark.get_create_tables_sql(dialect="duckdb")
print(schema_sql.splitlines()[:3])
```

This prints the first three lines of the script: `CREATE TABLE trips (`, `  vendor_id INTEGER,` and `  pickup_datetime TIMESTAMP,`.

#### `H2ODB.get_schema`

<span id="benchbox.h2odb.H2ODB.get_schema"></span>

`get_schema() -> dict` returns `{"trips": {"name": "trips", "columns": [...]}}`. Each column is a dict with `name` and `type`. The 22 columns are `vendor_id`, `pickup_datetime`, `dropoff_datetime`, `passenger_count`, `trip_distance`, pickup and dropoff longitude and latitude, `rate_code_id`, `store_and_fwd_flag`, `payment_type`, `fare_amount`, `extra`, `mta_tax`, `tip_amount`, `tolls_amount`, `improvement_surcharge`, `total_amount`, `pickup_location_id`, `dropoff_location_id` and `congestion_surcharge`. The annotation says `list[dict]`, but the value is a dict.

### Query Methods

#### `H2ODB.get_query`

<span id="benchbox.h2odb.H2ODB.get_query"></span>

`get_query(query_id, *, params=None) -> str` returns the SQL text of one query.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `query_id` | `str` | required | `"Q1"` to `"Q10"`. Ids are case-sensitive: `"1"`, `1` and `"q1"` are rejected. |
| `params` | `None` | `None` | The queries are static and have no parameters. Passing any dict, even `{}`, raises `ValueError`. |

Raises `ValueError` for an unknown id (`Invalid query ID: 1. Available: Q1, Q10, Q2, ...`) and for any non-`None` `params` (`H2O DB queries are static and don't accept parameters`).

```python
count_query = benchmark.get_query("Q1")
hourly_query = benchmark.get_query("Q7")
```

`Q1` is `SELECT COUNT(*) as count FROM trips;`.

#### `H2ODB.get_queries`

<span id="benchbox.h2odb.H2ODB.get_queries"></span>

`get_queries(dialect=None) -> dict[str, str]` returns all ten queries keyed `"Q1"` to `"Q10"`.

With a `dialect`, each query is translated with SQLGlot. DuckDB output for Q9 uses `QUANTILE_CONT("fare_amount", 0.5 ORDER BY "fare_amount")` and quotes every identifier.

```python
queries = benchmark.get_queries()
print(f"Available queries: {list(queries.keys())}")
```

This prints the ten ids, `Q1` to `Q10`, in order.

### Query Categories

The ten queries read the `trips` table and take no parameters:

**Basic Aggregation Queries (Q1-Q2)**:

- Q1: `COUNT(*)`
- Q2: `SUM(fare_amount)` and `AVG(fare_amount)`
- **Performance focus**: Sequential scan and basic aggregation speed

**Grouping Queries (Q3-Q6)**:

- Q3: `SUM(fare_amount)` grouped by `passenger_count`
- Q4: the same grouping with `SUM` and `AVG`
- Q5: `SUM` grouped by `passenger_count` and `vendor_id`
- Q6: `SUM` and `AVG` grouped by `passenger_count` and `vendor_id`
- **Performance focus**: Hash aggregation and grouping algorithms

**Temporal Analysis Queries (Q7-Q8)**:

- Q7: `SUM(fare_amount)` by hour of `pickup_datetime`
- Q8: `SUM(fare_amount)` by year and hour of `pickup_datetime`
- **Performance focus**: Date/time function evaluation and temporal grouping

**Advanced Analytics Queries (Q9-Q10)**:

- Q9: median and 90th percentile of `fare_amount` per `passenger_count` (`PERCENTILE_CONT`)
- Q10: the ten `pickup_location_id` values with the most trips
- **Performance focus**: Statistical function computation and sorting

### Inherited members

Every other member comes from `BaseBenchmark`. See {doc}`/reference/python-api/base` for what they do. The ids on this page for the inherited members are kept in the table.

| Group | Member | Kind | Notes |
| --- | --- | --- | --- |
| Run and results | <span id="benchbox.h2odb.H2ODB.cleanup"></span>`cleanup` | method | |
| Run and results | <span id="benchbox.h2odb.H2ODB.create_enhanced_benchmark_result"></span>`create_enhanced_benchmark_result` | method | |
| Run and results | <span id="benchbox.h2odb.H2ODB.create_minimal_benchmark_result"></span>`create_minimal_benchmark_result` | method | |
| Run and results | <span id="benchbox.h2odb.H2ODB.format_results"></span>`format_results` | method | |
| Run and results | <span id="benchbox.h2odb.H2ODB.run_benchmark"></span>`run_benchmark` | method | |
| Run and results | <span id="benchbox.h2odb.H2ODB.run_query"></span>`run_query` | method | |
| Run and results | <span id="benchbox.h2odb.H2ODB.run_with_platform"></span>`run_with_platform` | method | |
| Run and results | <span id="benchbox.h2odb.H2ODB.setup_database"></span>`setup_database` | method | |
| Run and results | <span id="benchbox.h2odb.H2ODB.translate_query"></span>`translate_query` | method | |
| Validation | <span id="benchbox.h2odb.H2ODB.validate_loaded_data"></span>`validate_loaded_data` | method | |
| Validation | <span id="benchbox.h2odb.H2ODB.validate_manifest"></span>`validate_manifest` | method | |
| Validation | <span id="benchbox.h2odb.H2ODB.validate_preflight"></span>`validate_preflight` | method | |
| Verbosity and logging | <span id="benchbox.h2odb.H2ODB.apply_verbosity"></span>`apply_verbosity` | method | |
| Verbosity and logging | <span id="benchbox.h2odb.H2ODB.log_debug_info"></span>`log_debug_info` | method | |
| Verbosity and logging | <span id="benchbox.h2odb.H2ODB.log_error_with_debug_info"></span>`log_error_with_debug_info` | method | |
| Verbosity and logging | <span id="benchbox.h2odb.H2ODB.log_notice"></span>`log_notice` | method | |
| Verbosity and logging | <span id="benchbox.h2odb.H2ODB.log_operation_complete"></span>`log_operation_complete` | method | |
| Verbosity and logging | <span id="benchbox.h2odb.H2ODB.log_operation_start"></span>`log_operation_start` | method | |
| Verbosity and logging | <span id="benchbox.h2odb.H2ODB.log_verbose"></span>`log_verbose` | method | |
| Verbosity and logging | <span id="benchbox.h2odb.H2ODB.log_version_warning"></span>`log_version_warning` | method | |
| Verbosity and logging | <span id="benchbox.h2odb.H2ODB.log_very_verbose"></span>`log_very_verbose` | method | |
| Verbosity and logging | <span id="benchbox.h2odb.H2ODB.logger"></span>`logger` | property | |
| Verbosity and logging | <span id="benchbox.h2odb.H2ODB.quiet"></span>`quiet` | class attribute | |
| Verbosity and logging | <span id="benchbox.h2odb.H2ODB.verbose"></span>`verbose` | class attribute | |
| Verbosity and logging | <span id="benchbox.h2odb.H2ODB.verbose_enabled"></span>`verbose_enabled` | class attribute | |
| Verbosity and logging | <span id="benchbox.h2odb.H2ODB.verbose_level"></span>`verbose_level` | class attribute | |
| Verbosity and logging | <span id="benchbox.h2odb.H2ODB.verbosity_settings"></span>`verbosity_settings` | property | |
| Verbosity and logging | <span id="benchbox.h2odb.H2ODB.very_verbose"></span>`very_verbose` | class attribute | |
| Data and configuration | <span id="benchbox.h2odb.H2ODB.api_surface"></span>`api_surface` | class attribute | |
| Data and configuration | <span id="benchbox.h2odb.H2ODB.benchmark_name"></span>`benchmark_name` | property | |
| Data and configuration | <span id="benchbox.h2odb.H2ODB.csv_delimiter"></span>`csv_delimiter` | property | `None`. |
| Data and configuration | <span id="benchbox.h2odb.H2ODB.csv_null_marker"></span>`csv_null_marker` | property | `None`. |
| Data and configuration | <span id="benchbox.h2odb.H2ODB.DATA_SOURCE_BENCHMARK"></span>`DATA_SOURCE_BENCHMARK` | class attribute | `None`: H2ODB generates its own data. |
| Data and configuration | <span id="benchbox.h2odb.H2ODB.get_csv_loading_config"></span>`get_csv_loading_config` | method | `None` for every table. |
| Data and configuration | <span id="benchbox.h2odb.H2ODB.get_data_source_benchmark"></span>`get_data_source_benchmark` | method | |
| Data and configuration | <span id="benchbox.h2odb.H2ODB.output_dir"></span>`output_dir` | property | The resolved directory from the constructor argument. |
| Data and configuration | <span id="benchbox.h2odb.H2ODB.run_with_platform_api_surface"></span>`run_with_platform_api_surface` | class attribute | |
| Data and configuration | <span id="benchbox.h2odb.H2ODB.scale_factor"></span>`scale_factor` | instance attribute | The constructor argument. |
| Data and configuration | <span id="benchbox.h2odb.H2ODB.SKIP_DATA_LOADING"></span>`SKIP_DATA_LOADING` | class attribute | Defined on `BaseBenchmark` from 0.4.2, default `False`. Set it to `True` for a benchmark that needs schema objects but no data files. |
| Data and configuration | <span id="benchbox.h2odb.H2ODB.tables"></span>`tables` | property | Empty until `generate_data()` has run, then the table-to-path mapping. |

## Usage Examples

### Basic Benchmark Execution

```python
from benchbox import H2ODB
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = H2ODB(scale_factor=0.1)
data_files = benchmark.generate_data()

adapter = DuckDBAdapter(memory_limit="4GB")
results = adapter.run_benchmark(benchmark)

print(f"Queries: {results.total_queries}")
print(f"Average time: {results.average_query_time:.3f}s")
```

### Query Group Testing

```python
from benchbox import H2ODB
from benchbox.platforms.duckdb import DuckDBAdapter
import time

benchmark = H2ODB(scale_factor=0.01)
benchmark.generate_data()

adapter = DuckDBAdapter()
conn = adapter.create_connection()
adapter.create_schema(benchmark, conn)
adapter.load_data(benchmark, conn, benchmark.output_dir)

query_groups = {
    'Basic': ['Q1', 'Q2'],
    'Grouping': ['Q3', 'Q4', 'Q5', 'Q6'],
    'Temporal': ['Q7', 'Q8'],
    'Advanced': ['Q9', 'Q10']
}

for group_name, query_ids in query_groups.items():
    print(f"\n{group_name} Queries:")
    for query_id in query_ids:
        query = benchmark.get_query(query_id)

        start = time.time()
        result = conn.execute(query).fetchall()
        elapsed = time.time() - start

        print(f"  {query_id}: {elapsed*1000:.1f} ms ({len(result)} rows)")
```

### Aggregation Performance Analysis

```python
from benchbox import H2ODB
from benchbox.platforms.duckdb import DuckDBAdapter
import time
from statistics import mean

scale_factors = [0.01, 0.1, 1.0]

for sf in scale_factors:
    print(f"\n=== Scale Factor {sf} ===")

    benchmark = H2ODB(scale_factor=sf)
    benchmark.generate_data()

    adapter = DuckDBAdapter()
    conn = adapter.create_connection()
    adapter.create_schema(benchmark, conn)
    adapter.load_data(benchmark, conn, benchmark.output_dir)

    aggregation_tests = [
        ('Q1', 'Simple count'),
        ('Q2', 'Sum and avg'),
        ('Q3', 'Single-column GROUP BY'),
        ('Q5', 'Two-column GROUP BY'),
        ('Q9', 'Statistical functions')
    ]

    for query_id, description in aggregation_tests:
        query = benchmark.get_query(query_id)

        times = []
        for _ in range(3):
            start = time.time()
            result = conn.execute(query).fetchall()
            times.append(time.time() - start)

        print(f"{query_id} ({description}): {mean(times)*1000:.1f} ms")
```

Scale factor 1.0 generates 10 million rows (about 1.4 GB on disk).

### Data Science Workflow Integration

```python
from benchbox import H2ODB
import pandas as pd
import time

benchmark = H2ODB(scale_factor=0.01)
files = benchmark.generate_data()

columns = [column["name"] for column in benchmark.get_schema()["trips"]["columns"]]
trips_df = pd.read_csv(files["trips"], sep="|", header=None, names=columns)

print("Data Science Operations Performance:")

start = time.time()
trips_df['hour'] = pd.to_datetime(trips_df['pickup_datetime']).dt.hour
trips_df['day_of_week'] = pd.to_datetime(trips_df['pickup_datetime']).dt.dayofweek
trips_df['trip_duration'] = (
    pd.to_datetime(trips_df['dropoff_datetime']) -
    pd.to_datetime(trips_df['pickup_datetime'])
).dt.total_seconds()
print(f"Feature engineering: {time.time() - start:.3f}s")

start = time.time()
hourly_stats = trips_df.groupby('hour').agg({
    'fare_amount': ['sum', 'mean', 'std', 'count'],
    'trip_distance': ['mean'],
    'passenger_count': ['mean']
})
print(f"GroupBy aggregation: {time.time() - start:.3f}s")

start = time.time()
vendor_stats = trips_df.groupby('vendor_id').agg({
    'fare_amount': ['count', 'sum', 'mean', 'std', 'min', 'max'],
    'tip_amount': ['mean', 'std']
})
print(f"Statistical analysis: {time.time() - start:.3f}s")
```

The script generates data for a machine-learning preprocessing simulation and loads it into pandas. It then times feature engineering, an aggregation similar to the H2O queries, and a statistical analysis. The data file has no header row, so the script reads the column names from `get_schema()`.

## Best Practices

1. **Use Appropriate Scale Factors**

   ```python
   dev = H2ODB(scale_factor=0.01)
   test = H2ODB(scale_factor=0.1)
   prod = H2ODB(scale_factor=1.0)
   ```

   Use `0.01` for development and testing (100,000 rows, about 14 MB), `0.1` for the standard benchmark (1,000,000 rows, about 140 MB), and `1.0` for large-scale testing (10,000,000 rows, about 1.4 GB).

2. **Test Query Groups Separately**

   ```python
   basic_queries = ['Q1', 'Q2']
   grouping_queries = ['Q3', 'Q4', 'Q5', 'Q6']
   temporal_queries = ['Q7', 'Q8']
   advanced_queries = ['Q9', 'Q10']
   ```

   Test basic aggregation (`Q1`, `Q2`), grouping (`Q3` to `Q6`), temporal analysis (`Q7`, `Q8`), and advanced analytics (`Q9`, `Q10`) performance separately.

3. **Keep Query Text Unchanged**

   The queries are static, so `get_query()` rejects `params`. To change a filter, edit the SQL text that `get_query()` returns.

   ```python
   query = benchmark.get_query("Q8")
   ```

4. **Monitor Memory for Large Grouping Operations**

   ```python
   adapter = DuckDBAdapter(memory_limit="8GB")
   ```

   Large scale factors may require memory configuration.

5. **Use Multiple Iterations for Timing**

   ```python
   from statistics import mean

   times = []
   for _ in range(3):
       start = time.time()
       result = conn.execute(query).fetchall()
       times.append(time.time() - start)

   avg_time = mean(times)
   ```

## Common Issues

**Issue: Slow aggregation queries on large datasets:**

- **Solution**: Use columnar storage and appropriate indices
- Consider partitioning by date for temporal queries
- Increase memory limits for large GROUP BY operations

**Issue: Memory errors with high scale factors:**

- **Solution**: Start with smaller scale factors (0.01, 0.1)
- Increase database memory limits
- Use external aggregation if available

**Issue: Incorrect temporal analysis results:**

- **Solution**: Ensure proper timezone handling
- Filter out NULL or invalid dates
- Use appropriate date truncation functions

**Issue: `ValueError: H2O DB queries are static and don't accept parameters`**

- **Solution**: Call `get_query(query_id)` without `params`

## See Also

- {doc}`/benchmarks/h2odb` - H2O.ai benchmark guide
- {doc}`clickbench` - ClickBench analytics benchmark
- {doc}`amplab` - AMPLab big data benchmark
- {doc}`/reference/python-api/base` - Base benchmark interface

### External Resources

- [H2O.ai DB Benchmark](https://h2oai.github.io/db-benchmark/) - Original specification
- [NYC Taxi Data](https://www1.nyc.gov/site/tlc/about/tlc-trip-record-data.page) - Source data format
- [Database Performance Analysis](https://duckdblabs.github.io/db-benchmark/) - Performance comparisons
