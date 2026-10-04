# Advanced Performance Optimization Guide

```{tags} advanced, guide, performance
```

Comprehensive guide to optimizing BenchBox benchmarks for maximum performance across different platforms and configurations.

## Overview

This guide covers advanced optimization techniques for achieving optimal benchmark performance. For basic performance monitoring, see the [Performance Monitoring](performance.md) guide.

## Table of Contents

- [Platform-Specific Optimizations](#platform-specific-optimizations)
- [Tuning Configuration](#tuning-configuration)
- [Query Optimization](#query-optimization)
- [Data Generation Optimization](#data-generation-optimization)
- [Cloud Platform Optimization](#cloud-platform-optimization)
- [Resource Management](#resource-management)
- [Performance Profiling](#performance-profiling)

## Platform-Specific Optimizations

### DuckDB Optimizations

DuckDB is optimized for analytical workloads by default, but additional tunings can improve performance:

```python
from benchbox.tpch import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.core.tuning.interface import UnifiedTuningConfiguration, TuningType

tuning = UnifiedTuningConfiguration()

tuning.enable_table_tuning(
    "lineitem",
    TuningType.PARTITIONING,
    columns=["l_shipdate"],
    num_partitions=12
)

tuning.enable_table_tuning(
    "lineitem",
    TuningType.CLUSTERING,
    columns=["l_orderkey"]
)

tuning.enable_table_tuning(
    "orders",
    TuningType.CLUSTERING,
    columns=["o_orderkey"]
)

benchmark = TPCH(scale_factor=1.0)

adapter = DuckDBAdapter(memory_limit="8GB", threads=8)
results = adapter.run_benchmark(benchmark, tuning_config=tuning)

print(f"Optimized execution: {results.total_execution_time:.2f}s")
```

This configuration partitions `lineitem` into 12 partitions, which are monthly, and adds clustering on frequently joined columns.

### ClickHouse Local Optimizations

```python
from benchbox.tpch import TPCH
from benchbox.platforms.clickhouse import ClickHouseAdapter
from benchbox.core.tuning.interface import UnifiedTuningConfiguration, TuningType

tuning = UnifiedTuningConfiguration()

tuning.enable_table_tuning(
    "lineitem",
    TuningType.PARTITIONING,
    columns=["l_shipdate"],
    partition_by="toYYYYMM(l_shipdate)"
)

tuning.enable_table_tuning(
    "lineitem",
    TuningType.SORTING,
    columns=["l_orderkey", "l_partkey"]
)

tuning.enable_table_tuning(
    "lineitem",
    TuningType.COMPRESSION,
    compression_method="LZ4"
)

benchmark = TPCH(scale_factor=1.0)
adapter = ClickHouseAdapter(local_mode=True)
results = adapter.run_benchmark(benchmark, tuning_config=tuning)
```

This configuration partitions `lineitem` by month, orders it by common filter columns, and enables LZ4 compression.

### Databricks Delta Lake Optimizations

```python
from benchbox.tpch import TPCH
from benchbox.platforms.databricks import DatabricksAdapter
from benchbox.core.tuning.interface import UnifiedTuningConfiguration, TuningType

tuning = UnifiedTuningConfiguration()

tuning.enable_platform_optimization(
    TuningType.Z_ORDERING,
    table_name="lineitem",
    columns=["l_orderkey", "l_partkey", "l_shipdate"]
)

tuning.enable_platform_optimization(
    TuningType.AUTO_OPTIMIZE,
    enabled=True
)

tuning.enable_platform_optimization(
    TuningType.AUTO_COMPACT,
    enabled=True
)

tuning.enable_platform_optimization(
    TuningType.BLOOM_FILTER_INDEX,
    table_name="lineitem",
    columns=["l_orderkey"],
    expected_items=1000000,
    false_positive_rate=0.01
)

benchmark = TPCH(scale_factor=10.0)
adapter = DatabricksAdapter(
    warehouse_id="your_warehouse_id",
    catalog="main",
    schema="benchmarks"
)

results = adapter.run_benchmark(benchmark, tuning_config=tuning)
```

Z-ordering gives multi-dimensional clustering. Auto-optimize handles background compaction, and auto-compact merges small files. Bloom filters help on high-cardinality columns.

### Snowflake Clustering Optimizations

```python
from benchbox.tpch import TPCH
from benchbox.platforms.snowflake import SnowflakeAdapter
from benchbox.core.tuning.interface import UnifiedTuningConfiguration, TuningType

tuning = UnifiedTuningConfiguration()

tuning.enable_table_tuning(
    "lineitem",
    TuningType.CLUSTERING,
    columns=["l_shipdate", "l_orderkey"]
)

tuning.enable_table_tuning(
    "orders",
    TuningType.CLUSTERING,
    columns=["o_orderdate", "o_custkey"]
)

tuning.enable_table_tuning(
    "lineitem",
    TuningType.PARTITIONING,
    columns=["l_shipdate"],
    num_partitions=12
)

benchmark = TPCH(scale_factor=100.0)
adapter = SnowflakeAdapter(
    warehouse="LARGE_WH",
    database="BENCHMARKS",
    schema="TPCH"
)

results = adapter.run_benchmark(benchmark, tuning_config=tuning)
```

Clustering keys cover frequently filtered columns, large tables are partitioned, and `LARGE_WH` is a larger warehouse.

### BigQuery Optimizations

```python
from benchbox.tpch import TPCH
from benchbox.platforms.bigquery import BigQueryAdapter
from benchbox.core.tuning.interface import UnifiedTuningConfiguration, TuningType

tuning = UnifiedTuningConfiguration()

tuning.enable_table_tuning(
    "lineitem",
    TuningType.PARTITIONING,
    columns=["l_shipdate"],
    partition_type="DAY"
)

tuning.enable_table_tuning(
    "lineitem",
    TuningType.CLUSTERING,
    columns=["l_orderkey", "l_partkey", "l_suppkey", "l_linenumber"]
)

benchmark = TPCH(scale_factor=1000.0)
adapter = BigQueryAdapter(
    project_id="your_project",
    dataset_id="benchmarks",
    location="US"
)

results = adapter.run_benchmark(benchmark, tuning_config=tuning)
```

This uses native BigQuery partitioning on a date column and clustering for multi-column optimization.

## Tuning Configuration

### Comprehensive Tuning Strategy

```python
from benchbox.tpcds import TPCDS
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.core.tuning.interface import UnifiedTuningConfiguration, TuningType

def create_comprehensive_tuning(benchmark_name: str, scale_factor: float):
    tuning = UnifiedTuningConfiguration()

    if benchmark_name == "tpcds":
        fact_tables = ["store_sales", "web_sales", "catalog_sales"]

        for table in fact_tables:
            tuning.enable_table_tuning(
                table,
                TuningType.PARTITIONING,
                columns=["ss_sold_date_sk"] if table == "store_sales"
                        else ["ws_sold_date_sk"] if table == "web_sales"
                        else ["cs_sold_date_sk"],
                num_partitions=24 if scale_factor >= 1.0 else 12
            )

            primary_keys = {
                "store_sales": ["ss_item_sk", "ss_ticket_number"],
                "web_sales": ["ws_item_sk", "ws_order_number"],
                "catalog_sales": ["cs_item_sk", "cs_order_number"]
            }

            tuning.enable_table_tuning(
                table,
                TuningType.CLUSTERING,
                columns=primary_keys[table]
            )

        dimension_tables = ["item", "store", "customer", "date_dim"]

        for dim_table in dimension_tables:
            key_column = f"{dim_table.rstrip('_dim')}_sk"
            if dim_table == "date_dim":
                key_column = "d_date_sk"

            tuning.enable_table_tuning(
                dim_table,
                TuningType.PRIMARY_KEY,
                columns=[key_column]
            )

    return tuning

tuning = create_comprehensive_tuning("tpcds", scale_factor=10.0)
benchmark = TPCDS(scale_factor=10.0)
adapter = DuckDBAdapter(memory_limit="16GB", threads=16)
results = adapter.run_benchmark(benchmark, tuning_config=tuning)
```

For TPC-DS, the function partitions each fact table by date, clusters it by primary key, and adds primary-key tuning on the dimension tables. Partition counts depend on the scale factor.

### Constraint-Based Optimization

```python
from benchbox.tpch import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.core.tuning.interface import (
    UnifiedTuningConfiguration,
    TuningType,
    PrimaryKeyConfiguration,
    ForeignKeyConfiguration
)

tuning = UnifiedTuningConfiguration()

tuning.add_primary_key(
    PrimaryKeyConfiguration(
        table_name="nation",
        column_names=["n_nationkey"],
        constraint_name="nation_pk"
    )
)

tuning.add_primary_key(
    PrimaryKeyConfiguration(
        table_name="region",
        column_names=["r_regionkey"],
        constraint_name="region_pk"
    )
)

tuning.add_foreign_key(
    ForeignKeyConfiguration(
        table_name="nation",
        column_names=["n_regionkey"],
        referenced_table="region",
        referenced_columns=["r_regionkey"],
        constraint_name="nation_region_fk"
    )
)

tuning.add_foreign_key(
    ForeignKeyConfiguration(
        table_name="lineitem",
        column_names=["l_orderkey"],
        referenced_table="orders",
        referenced_columns=["o_orderkey"],
        constraint_name="lineitem_orders_fk"
    )
)

benchmark = TPCH(scale_factor=1.0)
adapter = DuckDBAdapter()
results = adapter.run_benchmark(benchmark, tuning_config=tuning)
```

Primary keys are defined for referential integrity. Foreign keys enable join optimizations.

## Query Optimization

### Query Subset Selection

Run only performance-critical queries:

```python
from benchbox.tpch import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter

slow_queries = [1, 6, 12, 17, 21]

benchmark = TPCH(scale_factor=1.0)
adapter = DuckDBAdapter()

benchmark.generate_data()

for query_id in slow_queries:
    query = benchmark.get_query(query_id)

    import time
    start = time.time()
    conn = adapter.create_connection()
    result = conn.execute(query).fetchall()
    elapsed = time.time() - start

    print(f"Query {query_id}: {elapsed:.3f}s ({len(result)} rows)")
```

The `slow_queries` list holds queries identified as slow in a previous run. Data is generated once, then only those queries run.

### Query Caching

Cache frequently used query results:

```python
from functools import lru_cache
from benchbox.tpch import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter
import hashlib

class CachedBenchmark:
    def __init__(self, benchmark, adapter):
        self.benchmark = benchmark
        self.adapter = adapter
        self.cache = {}

    def run_query_cached(self, query_id):
        query_sql = self.benchmark.get_query(query_id)

        cache_key = hashlib.md5(query_sql.encode()).hexdigest()

        if cache_key in self.cache:
            print(f"Query {query_id}: Cache hit")
            return self.cache[cache_key]

        print(f"Query {query_id}: Cache miss, executing...")
        conn = self.adapter.create_connection()
        result = conn.execute(query_sql).fetchall()

        self.cache[cache_key] = result

        return result

benchmark = TPCH(scale_factor=0.01)
adapter = DuckDBAdapter()
cached = CachedBenchmark(benchmark, adapter)

result1 = cached.run_query_cached(1)

result2 = cached.run_query_cached(1)
```

The first call is a cache miss and executes the query. The second call is a cache hit.

## Data Generation Optimization

### Parallel Data Generation

Generate data faster using parallel processes:

```python
from benchbox.tpch import TPCH
from concurrent.futures import ProcessPoolExecutor
import time

def generate_with_parallelization(scale_factor: float, num_workers: int = 4):
    start_time = time.time()

    benchmark = TPCH(scale_factor=scale_factor)

    data_files = benchmark.generate_data(verbose=True)

    generation_time = time.time() - start_time

    print(f"\nData generation completed:")
    print(f"  Time: {generation_time:.2f}s")
    print(f"  Files: {len(data_files)}")
    print(f"  Total size: {sum(f.stat().st_size for f in data_files) / 1024 / 1024:.1f} MB")

    return data_files

data_files = generate_with_parallelization(scale_factor=1.0, num_workers=8)
```

The TPC tools handle parallelization internally for most benchmarks. Controlling the worker count is an additional optimization.

### Data Reuse Strategy

Reuse generated data across runs:

```python
from benchbox.tpch import TPCH
from pathlib import Path

def get_or_generate_data(benchmark_name: str, scale_factor: float, cache_dir: str = "data_cache"):
    cache_path = Path(cache_dir) / benchmark_name / f"sf{scale_factor}"

    if cache_path.exists() and list(cache_path.glob("*.tbl")):
        print(f"Using cached data from {cache_path}")
        return cache_path

    print(f"Generating new data to {cache_path}")
    cache_path.mkdir(parents=True, exist_ok=True)

    benchmark = TPCH(scale_factor=scale_factor, output_dir=str(cache_path))
    benchmark.generate_data()

    return cache_path

data_dir = get_or_generate_data("tpch", scale_factor=1.0)

benchmark = TPCH(scale_factor=1.0, output_dir=str(data_dir))
```

## Cloud Platform Optimization

### S3 Data Staging

Optimize data loading from S3:

```python
from benchbox.tpch import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = TPCH(
    scale_factor=10.0,
    output_dir="s3://my-benchbox-bucket/tpch/sf10"
)

benchmark.generate_data(verbose=True)

adapter = DuckDBAdapter()
conn = adapter.create_connection()

adapter.create_schema(benchmark, conn)
adapter.load_data(benchmark, conn, "s3://my-benchbox-bucket/tpch/sf10")

results = adapter.run_benchmark(benchmark)
```

Data is generated directly to S3 once and reused many times. DuckDB reads from S3 natively, so `load_data` pulls from the bucket without a local copy.

### Regional Optimization

Use cloud storage in the same region as compute:

```python
from benchbox.tpch import TPCH
from benchbox.platforms.databricks import DatabricksAdapter

benchmark = TPCH(
    scale_factor=100.0,
    output_dir="dbfs:/Volumes/main/benchmarks/tpch_sf100"
)

benchmark.generate_data(verbose=True)

adapter = DatabricksAdapter(
    warehouse_id="your_warehouse_id",
    catalog="main",
    schema="benchmarks"
)

results = adapter.run_benchmark(benchmark)
```

The Unity Catalog volume and the SQL warehouse should be in the same region as the workspace, so data is generated to regional storage.

## Resource Management

### Memory Management

Optimize memory usage for large benchmarks:

```python
import gc
from benchbox.tpcds import TPCDS
from benchbox.platforms.duckdb import DuckDBAdapter

def run_memory_optimized_benchmark(scale_factor: float):
    adapter = DuckDBAdapter(
        memory_limit="8GB",
        threads=4
    )

    benchmark = TPCDS(scale_factor=scale_factor)

    print("Generating data...")
    benchmark.generate_data()

    gc.collect()

    print("Running benchmark...")
    results = adapter.run_benchmark(benchmark)

    gc.collect()

    return results

results = run_memory_optimized_benchmark(scale_factor=10.0)
```

The explicit `memory_limit` sets a hard cap, and `threads=4` limits parallelism to control memory use. Garbage collection runs before loading and after the benchmark.

### Disk Space Management

Manage disk space for large benchmarks:

```python
from benchbox.tpch import TPCH
from pathlib import Path
import shutil

def run_with_cleanup(scale_factor: float, temp_dir: str = "/tmp/benchbox"):
    temp_path = Path(temp_dir)
    temp_path.mkdir(parents=True, exist_ok=True)

    try:
        benchmark = TPCH(scale_factor=scale_factor, output_dir=str(temp_path))
        benchmark.generate_data()

        adapter = DuckDBAdapter(database_path=str(temp_path / "benchmark.db"))
        results = adapter.run_benchmark(benchmark)

        return results

    finally:
        print(f"Cleaning up {temp_path}")
        shutil.rmtree(temp_path, ignore_errors=True)

results = run_with_cleanup(scale_factor=1.0)
```

The `finally` block removes the temporary files even if the benchmark fails.

## Performance Profiling

### Detailed Query Profiling

Profile query execution with detailed breakdowns:

```python
from benchbox.tpch import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.core.results.timing import TimingCollector, TimingAnalyzer
import time

def profile_queries(benchmark, adapter, query_ids):
    collector = TimingCollector(enable_detailed_timing=True)
    conn = adapter.create_connection()

    for query_id in query_ids:
        query_sql = benchmark.get_query(query_id)

        with collector.time_query(query_id, f"Query {query_id}") as timing:
            with collector.time_phase(query_id, "compile"):
                pass

            with collector.time_phase(query_id, "execute"):
                result = conn.execute(query_sql).fetchall()

            collector.record_metric(query_id, "rows_returned", len(result))

    timings = collector.get_completed_timings()
    analyzer = TimingAnalyzer(timings)

    analysis = analyzer.analyze_query_performance()

    print("\nPerformance Analysis:")
    print(f"Queries: {analysis['basic_stats']['count']}")
    print(f"Mean: {analysis['basic_stats']['mean']:.3f}s")
    print(f"Median: {analysis['basic_stats']['median']:.3f}s")
    print(f"P95: {analysis['percentiles'][95]:.3f}s")

    if analysis['timing_phases']:
        print("\nPhase Breakdown:")
        for phase, stats in analysis['timing_phases'].items():
            print(f"  {phase}: {stats['mean']:.3f}s avg")

    return analysis

benchmark = TPCH(scale_factor=0.1)
adapter = DuckDBAdapter()
benchmark.generate_data()
adapter.create_schema(benchmark, adapter.create_connection())

analysis = profile_queries(benchmark, adapter, [1, 3, 6, 12, 17])
```

The `compile` phase is an empty placeholder because DuckDB compiles on first execute. The `execute` phase holds the real work.

### Performance Regression Testing

Automated regression detection:

```python
from benchbox.tpch import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.core.results.exporter import ResultExporter
from pathlib import Path

def run_regression_test(baseline_file: Path, threshold: float = 10.0):
    benchmark = TPCH(scale_factor=0.01)
    adapter = DuckDBAdapter()
    current_results = adapter.run_benchmark(benchmark)

    exporter = ResultExporter(output_dir="regression_tests")
    current_file = exporter.export_result(current_results, formats=["json"])["json"]

    comparison = exporter.compare_results(baseline_file, current_file)

    perf_changes = comparison.get("performance_changes", {})
    avg_change = perf_changes.get("average_query_time", {})

    if avg_change.get("change_percent", 0) > threshold:
        print(f"❌ REGRESSION DETECTED: {avg_change['change_percent']:.2f}% slower")
        return False
    else:
        print(f"✅ No regression: {avg_change.get('change_percent', 0):.2f}% change")
        return True

baseline = Path("baselines/tpch_sf001_duckdb.json")
passed = run_regression_test(baseline, threshold=10.0)
exit(0 if passed else 1)
```

The final lines show use in CI/CD: the script exits non-zero when a regression exceeds the threshold.

## Best Practices

### 1. Start Small, Scale Up

Always test with small scale factors first:

```python
benchmark = TPCH(scale_factor=0.01)

benchmark = TPCH(scale_factor=0.1)

benchmark = TPCH(scale_factor=1.0)
```

Use 0.01 for development (fast iteration), 0.1 for testing, and 1.0 for production-scale runs.

### 2. Use Appropriate Tunings

Match tunings to your workload:

```python
tuning.enable_table_tuning("fact_table", TuningType.CLUSTERING, columns=["date", "id"])

tuning.enable_table_tuning("fact_table", TuningType.PRIMARY_KEY, columns=["id"])
```

The clustering tuning suits OLAP-focused workloads (analytical queries). The primary key tuning suits OLTP-focused workloads (point lookups).

### 3. Monitor Resource Usage

Track resource consumption:

```python
import psutil
import os

process = psutil.Process(os.getpid())

print(f"Memory: {process.memory_info().rss / 1024 / 1024:.1f} MB")
print(f"CPU: {process.cpu_percent()}%")
```

### 4. Cache and Reuse

Reuse generated data and connections:

```python
benchmark.generate_data()

conn = adapter.create_connection()

for config in configurations:
    results = run_with_config(conn, benchmark, config)
```

### 5. Profile Before Optimizing

Always profile to identify bottlenecks:

```python
from benchbox.core.results.timing import TimingAnalyzer

analyzer = TimingAnalyzer(timings)
outliers = analyzer.identify_outliers(method="iqr")

print("Optimization targets:")
for outlier in outliers:
    print(f"  Query {outlier.query_id}: {outlier.execution_time:.3f}s")
```

## See Also

- [Performance Monitoring](performance.md) - Basic performance monitoring
- [Tuning Configuration API](../reference/python-api/tuning.md) - Tuning API reference
- [Result Analysis API](../reference/python-api/result-analysis.rst) - Analysis utilities
- [CI/CD Integration](ci-cd-integration.md) - Automated performance testing
- [Platform Adapters](../reference/python-api/platforms/) - Platform-specific optimizations
