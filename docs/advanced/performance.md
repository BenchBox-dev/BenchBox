<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Performance Monitoring

```{tags} advanced, guide, performance
```

Guide to performance measurement and analysis with BenchBox.

## Prerequisites

The memory monitoring examples in this guide require the `psutil` package:

```bash
pip install psutil
```

Core BenchBox functionality (timing, monitoring utilities) works without additional
dependencies.

---

## Monitoring Utilities

BenchBox ships with reusable monitoring helpers in
`benchbox.monitoring.performance`.

### Deep CLI Integration

**Performance monitoring is now automatic by default** for all benchmark executions.
The CLI enables monitoring and progress tracking automatically, with options to
disable if needed.

```bash
benchbox run --platform duckdb --benchmark tpch --scale 1

benchbox run --platform duckdb --benchmark tpch --no-monitoring

benchbox run --platform duckdb --benchmark tpch --no-progress
```

**CLI Flags** (advanced options, visible with `--help-topic all`):
- `--no-monitoring`: Disable automatic performance monitoring and metrics collection
- `--no-progress`: Disable progress bars (use simple text output instead)

### Programmatic Usage

For custom benchmark implementations, monitoring utilities remain available as
helper classes:

1. Import the monitoring classes (`PerformanceMonitor`, `ResourceMonitor`, etc.)
2. Create a monitor instance in your code
3. Record metrics during execution
4. Attach snapshots to results using `attach_snapshot_to_result()`

```python
from pathlib import Path
from benchbox.monitoring import (
    PerformanceMonitor,
    PerformanceHistory,
    attach_snapshot_to_result,
)

monitor = PerformanceMonitor()

for query in workload:
    with monitor.time_operation("query_execution"):
        run_query(query)
    monitor.increment_counter("executed_queries")

snapshot = monitor.snapshot()

attach_snapshot_to_result(result, snapshot)

history = PerformanceHistory(Path("benchmark_runs/performance_history.json"))
alerts = history.record(
    snapshot,
    regression_thresholds={"query_execution": 0.20},
    prefer_lower_metrics=["query_execution"],
)

if alerts:
    raise RuntimeError(f"Performance regression detected: {alerts}")
```

- `PerformanceMonitor` records counters, gauges, and timings with millisecond
  precision.
- `PerformanceHistory` persists snapshots (JSON) and can emit regression alerts
  when a new run breaches configured thresholds.
- `PerformanceTracker` offers higher level helpers used in the performance
  tests for long-term trend analysis and anomaly detection.

Integrate this snippet in CI to automatically publish the latest snapshot as a
build artifact and fail the pipeline when regression alerts are returned. The
JSON files live under `benchmark_runs/` by default and are small enough to store
with other benchmark artifacts.

---

## Basic Performance Measurement

### Simple Query Timing

```python
import time
from benchbox import TPCH

tpch = TPCH(scale_factor=0.1)

def time_query(connection, query_sql: str, query_id: str = "") -> dict:

    start_time = time.time()
    result = connection.execute(query_sql).fetchall()
    execution_time = time.time() - start_time

    return {
        "query_id": query_id,
        "execution_time_seconds": execution_time,
        "rows_returned": len(result),
        "execution_time_ms": execution_time * 1000
    }

query_1 = tpch.get_query(1)
timing_result = time_query(connection, query_1, "Q1")

print(f"Query {timing_result['query_id']}:")
print(f"  Execution time: {timing_result['execution_time_ms']:.1f} ms")
print(f"  Rows returned: {timing_result['rows_returned']}")
```

The example assumes `connection` is an open database connection (DuckDB is
recommended) with the TPC-H schema and data already loaded.

### Multiple Query Timing

```python
import time
from benchbox import TPCH

def time_multiple_queries(connection, benchmark, query_ids: list) -> dict:

    results = {}
    total_start_time = time.time()

    for query_id in query_ids:
        query_sql = benchmark.get_query(query_id)

        start_time = time.time()
        result = connection.execute(query_sql).fetchall()
        execution_time = time.time() - start_time

        results[query_id] = {
            "execution_time_seconds": execution_time,
            "execution_time_ms": execution_time * 1000,
            "rows_returned": len(result)
        }

        print(f"Query {query_id}: {execution_time * 1000:.1f} ms ({len(result)} rows)")

    total_time = time.time() - total_start_time

    return {
        "individual_results": results,
        "total_execution_time": total_time,
        "queries_executed": len(query_ids)
    }

import duckdb
from benchbox import TPCH

conn = duckdb.connect(":memory:")
tpch = TPCH(scale_factor=0.1)


query_results = time_multiple_queries(conn, tpch, list(range(1, 6)))

print(f"\nTotal time for {query_results['queries_executed']} queries: "
      f"{query_results['total_execution_time']:.2f} seconds")
```

Create the schema and load the data into `conn` before calling
`time_multiple_queries`. The call times the first five TPC-H queries.

---

## Timing Benchmark Execution

### Complete Benchmark Timing

```python
import time
from benchbox import TPCH
import duckdb

def run_timed_benchmark(benchmark_class, scale_factor: float = 0.1) -> dict:

    print(f"Running {benchmark_class.__name__} benchmark (SF={scale_factor})")

    benchmark_start = time.time()
    benchmark = benchmark_class(scale_factor=scale_factor)

    print("Generating data...")
    data_gen_start = time.time()
    data_files = benchmark.generate_data()
    data_gen_time = time.time() - data_gen_start

    total_size_mb = sum(f.stat().st_size for f in data_files) / (1024 * 1024)

    print("Setting up database...")
    setup_start = time.time()
    conn = duckdb.connect(":memory:")

    ddl = benchmark.get_create_tables_sql()
    conn.execute(ddl)

    for file_path in data_files:
        table_name = file_path.stem
        conn.execute(f"""
            INSERT INTO {table_name}
            SELECT * FROM read_csv('{file_path}', delimiter='|', header=false)
        """)

    setup_time = time.time() - setup_start

    print("Executing queries...")
    query_start = time.time()

    queries = benchmark.get_queries()
    query_results = {}

    for query_id, query_sql in queries.items():
        start_time = time.time()
        try:
            result = conn.execute(query_sql).fetchall()
            execution_time = time.time() - start_time

            query_results[query_id] = {
                "success": True,
                "execution_time_ms": execution_time * 1000,
                "rows_returned": len(result)
            }

        except Exception as e:
            execution_time = time.time() - start_time
            query_results[query_id] = {
                "success": False,
                "execution_time_ms": execution_time * 1000,
                "error": str(e)
            }

    query_exec_time = time.time() - query_start
    total_time = time.time() - benchmark_start

    successful_queries = [q for q in query_results.values() if q["success"]]
    failed_queries = [q for q in query_results.values() if not q["success"]]

    avg_query_time = sum(q["execution_time_ms"] for q in successful_queries) / len(successful_queries) if successful_queries else 0

    return {
        "benchmark_name": benchmark_class.__name__,
        "scale_factor": scale_factor,
        "timing": {
            "data_generation_seconds": data_gen_time,
            "database_setup_seconds": setup_time,
            "query_execution_seconds": query_exec_time,
            "total_seconds": total_time
        },
        "data_stats": {
            "total_size_mb": total_size_mb,
            "num_tables": len(data_files)
        },
        "query_stats": {
            "total_queries": len(queries),
            "successful_queries": len(successful_queries),
            "failed_queries": len(failed_queries),
            "average_query_time_ms": avg_query_time
        },
        "query_results": query_results
    }

benchmark_results = run_timed_benchmark(TPCH, scale_factor=0.1)

print(f"\n=== {benchmark_results['benchmark_name']} Results ===")
print(f"Data generation: {benchmark_results['timing']['data_generation_seconds']:.2f}s")
print(f"Database setup: {benchmark_results['timing']['database_setup_seconds']:.2f}s")
print(f"Query execution: {benchmark_results['timing']['query_execution_seconds']:.2f}s")
print(f"Total time: {benchmark_results['timing']['total_seconds']:.2f}s")
print(f"Average query time: {benchmark_results['query_stats']['average_query_time_ms']:.1f}ms")
print(f"Success rate: {benchmark_results['query_stats']['successful_queries']}/{benchmark_results['query_stats']['total_queries']}")
```

### Performance Profiling

```python
import time
import psutil
import os
from benchbox import TPCH

def profile_benchmark_execution(benchmark_class, scale_factor: float = 0.1):

    process = psutil.Process(os.getpid())
    initial_memory = process.memory_info().rss / (1024 * 1024)
    initial_cpu_time = process.cpu_times()

    print(f"Starting {benchmark_class.__name__} execution profile")
    print(f"Initial memory usage: {initial_memory:.1f} MB")

    start_time = time.time()

    benchmark = benchmark_class(scale_factor=scale_factor)
    data_files = benchmark.generate_data()

    gen_memory = process.memory_info().rss / (1024 * 1024)
    gen_time = time.time() - start_time

    print(f"After data generation ({gen_time:.1f}s): {gen_memory:.1f} MB (+{gen_memory - initial_memory:.1f} MB)")

    import duckdb
    conn = duckdb.connect(":memory:")
    ddl = benchmark.get_create_tables_sql()
    conn.execute(ddl)

    for file_path in data_files:
        table_name = file_path.stem
        conn.execute(f"""
            INSERT INTO {table_name}
            SELECT * FROM read_csv('{file_path}', delimiter='|', header=false)
        """)

    setup_memory = process.memory_info().rss / (1024 * 1024)
    setup_time = time.time() - start_time

    print(f"After database setup ({setup_time:.1f}s): {setup_memory:.1f} MB (+{setup_memory - gen_memory:.1f} MB)")

    queries = benchmark.get_queries()
    query_count = 0

    for query_id, query_sql in list(queries.items())[:5]:
        try:
            result = conn.execute(query_sql).fetchall()
            query_count += 1

            current_memory = process.memory_info().rss / (1024 * 1024)
            current_time = time.time() - start_time

            print(f"Query {query_id} ({current_time:.1f}s): {current_memory:.1f} MB, {len(result)} rows")

        except Exception as e:
            print(f"Query {query_id} failed: {e}")

    final_memory = process.memory_info().rss / (1024 * 1024)
    final_cpu_time = process.cpu_times()
    total_time = time.time() - start_time

    cpu_usage = (final_cpu_time.user - initial_cpu_time.user) + (final_cpu_time.system - initial_cpu_time.system)

    print(f"\n=== Execution Profile Summary ===")
    print(f"Total execution time: {total_time:.1f}s")
    print(f"Peak memory usage: {final_memory:.1f} MB")
    print(f"Memory increase: {final_memory - initial_memory:.1f} MB")
    print(f"CPU time used: {cpu_usage:.1f}s")
    print(f"Queries executed: {query_count}/{len(queries)}")

profile_benchmark_execution(TPCH, scale_factor=0.1)
```

---

## Memory Usage Monitoring

### Simple Memory Tracking

```python
import psutil
import os
from benchbox import TPCH

def monitor_memory_usage():

    process = psutil.Process(os.getpid())

    def get_memory_mb():
        return process.memory_info().rss / (1024 * 1024)

    print(f"Initial memory: {get_memory_mb():.1f} MB")

    tpch = TPCH(scale_factor=0.1)
    print(f"After benchmark init: {get_memory_mb():.1f} MB")

    data_files = tpch.generate_data()
    print(f"After data generation: {get_memory_mb():.1f} MB")

    import duckdb
    conn = duckdb.connect(":memory:")
    ddl = tpch.get_create_tables_sql()
    conn.execute(ddl)

    print(f"After DDL execution: {get_memory_mb():.1f} MB")

    for file_path in data_files:
        table_name = file_path.stem
        conn.execute(f"""
            INSERT INTO {table_name}
            SELECT * FROM read_csv('{file_path}', delimiter='|', header=false)
        """)
        print(f"After loading {table_name}: {get_memory_mb():.1f} MB")

monitor_memory_usage()
```

### Memory-Efficient Patterns

```python
from benchbox import TPCH
import duckdb
import gc

def memory_efficient_benchmark(scale_factor: float = 0.1):

    if scale_factor > 0.5:
        print("Warning: Large scale factor may cause memory issues")

    tpch = TPCH(scale_factor=scale_factor)

    data_files = tpch.generate_data()

    if scale_factor > 0.1:
        conn = duckdb.connect("temp_benchmark.duckdb")
    else:
        conn = duckdb.connect(":memory:")

    ddl = tpch.get_create_tables_sql()
    conn.execute(ddl)

    for file_path in data_files:
        table_name = file_path.stem
        print(f"Loading {table_name}...")

        conn.execute(f"""
            INSERT INTO {table_name}
            SELECT * FROM read_csv('{file_path}', delimiter='|', header=false)
        """)

        gc.collect()

    queries = tpch.get_queries()

    for query_id in list(queries.keys())[:5]:
        query_sql = queries[query_id]

        cursor = conn.execute(query_sql)
        first_few_rows = cursor.fetchmany(10)

        print(f"Query {query_id}: Sample of {len(first_few_rows)} rows")

    conn.close()

    if scale_factor > 0.1:
        import os
        os.remove("temp_benchmark.duckdb")

memory_efficient_benchmark(0.1)
```

---

## DuckDB Performance Optimization

### DuckDB-Specific Optimizations

```python
import duckdb
from benchbox import TPCH

def optimize_duckdb_performance(scale_factor: float = 0.1):

    conn = duckdb.connect(":memory:")


    if scale_factor >= 1.0:
        conn.execute("SET memory_limit='4GB'")
        conn.execute("SET threads=4")

    conn.execute("SET enable_progress_bar=true")

    conn.execute("SET default_order='ASC'")

    tpch = TPCH(scale_factor=scale_factor)
    data_files = tpch.generate_data()

    ddl = tpch.get_create_tables_sql()
    conn.execute(ddl)

    print("Loading data with DuckDB optimizations...")
    for file_path in data_files:
        table_name = file_path.stem

        conn.execute(f"""
            INSERT INTO {table_name}
            SELECT * FROM read_csv('{file_path}',
                                   delimiter='|',
                                   header=false,
                                   auto_detect=false)
        """)

    conn.execute("ANALYZE")

    queries = tpch.get_queries()

    for query_id in [1, 3, 6, 12]:
        query_sql = queries[query_id]

        conn.execute("PRAGMA enable_profiling='query_tree'")

        import time
        start_time = time.time()
        result = conn.execute(query_sql).fetchall()
        execution_time = time.time() - start_time

        print(f"Query {query_id}: {execution_time * 1000:.1f} ms ({len(result)} rows)")


optimize_duckdb_performance(0.1)
```

### DuckDB Performance Settings

```python
import duckdb
from benchbox import TPCH

def configure_duckdb_for_benchmark(memory_limit_gb: int = 4, num_threads: int = None):

    conn = duckdb.connect(":memory:")

    conn.execute(f"SET memory_limit='{memory_limit_gb}GB'")

    if num_threads:
        conn.execute(f"SET threads={num_threads}")
    else:
        import os
        conn.execute(f"SET threads={os.cpu_count()}")

    conn.execute("SET enable_progress_bar=true")
    conn.execute("SET preserve_insertion_order=false")

    conn.execute("SET enable_optimizer=true")
    conn.execute("SET enable_profiling='query_tree'")

    return conn

conn = configure_duckdb_for_benchmark(memory_limit_gb=2, num_threads=4)

tpch = TPCH(scale_factor=0.1)
```

`preserve_insertion_order=false` lets DuckDB reorder rows, which improves load
and scan performance. When no thread count is given, the function uses all
available CPU cores.

---

## Performance Comparison

### Scale Factor Performance Comparison

```python
import time
from benchbox import TPCH
import duckdb

def compare_scale_factors(scale_factors: list = [0.01, 0.1, 0.5]):

    results = {}

    for sf in scale_factors:
        print(f"\n=== Testing Scale Factor {sf} ===")

        start_time = time.time()

        tpch = TPCH(scale_factor=sf)
        data_files = tpch.generate_data()

        total_size_mb = sum(f.stat().st_size for f in data_files) / (1024 * 1024)

        conn = duckdb.connect(":memory:")
        ddl = tpch.get_create_tables_sql()
        conn.execute(ddl)

        for file_path in data_files:
            table_name = file_path.stem
            conn.execute(f"""
                INSERT INTO {table_name}
                SELECT * FROM read_csv('{file_path}', delimiter='|', header=false)
            """)

        setup_time = time.time() - start_time

        test_queries = [1, 3, 6, 12]
        query_times = []

        for query_id in test_queries:
            query_sql = tpch.get_query(query_id)

            query_start = time.time()
            result = conn.execute(query_sql).fetchall()
            query_time = time.time() - query_start

            query_times.append(query_time)
            print(f"  Query {query_id}: {query_time * 1000:.1f} ms")

        avg_query_time = sum(query_times) / len(query_times)
        total_time = time.time() - start_time

        results[sf] = {
            "data_size_mb": total_size_mb,
            "setup_time": setup_time,
            "avg_query_time": avg_query_time,
            "total_time": total_time
        }

        print(f"  Data size: {total_size_mb:.1f} MB")
        print(f"  Setup time: {setup_time:.1f}s")
        print(f"  Avg query time: {avg_query_time * 1000:.1f} ms")
        print(f"  Total time: {total_time:.1f}s")

        conn.close()

    print(f"\n=== Scale Factor Comparison ===")
    print("SF\tData(MB)\tSetup(s)\tAvg Query(ms)\tTotal(s)")
    for sf, metrics in results.items():
        print(f"{sf}\t{metrics['data_size_mb']:.1f}\t\t"
              f"{metrics['setup_time']:.1f}\t\t"
              f"{metrics['avg_query_time'] * 1000:.1f}\t\t"
              f"{metrics['total_time']:.1f}")

    return results

performance_results = compare_scale_factors([0.01, 0.1, 0.5])
```

### Benchmark Comparison

```python
import time
import duckdb
from benchbox import TPCH, SSB

def compare_benchmarks(scale_factor: float = 0.01):

    benchmarks = [
        ("TPC-H", TPCH),
        ("SSB", SSB),
    ]

    results = {}

    for name, benchmark_class in benchmarks:
        print(f"\n=== Testing {name} ===")

        try:
            start_time = time.time()

            benchmark = benchmark_class(scale_factor=scale_factor)
            data_files = benchmark.generate_data()

            conn = duckdb.connect(":memory:")
            ddl = benchmark.get_create_tables_sql()
            conn.execute(ddl)

            for file_path in data_files:
                table_name = file_path.stem
                conn.execute(f"""
                    INSERT INTO {table_name}
                    SELECT * FROM read_csv('{file_path}', delimiter='|', header=false)
                """)

            queries = benchmark.get_queries()

            test_queries = list(queries.keys())[:3]
            query_times = []

            for query_id in test_queries:
                query_sql = queries[query_id]

                query_start = time.time()
                result = conn.execute(query_sql).fetchall()
                query_time = time.time() - query_start

                query_times.append(query_time)
                print(f"  Query {query_id}: {query_time * 1000:.1f} ms ({len(result)} rows)")

            total_time = time.time() - start_time
            avg_query_time = sum(query_times) / len(query_times) if query_times else 0

            results[name] = {
                "total_queries": len(queries),
                "tested_queries": len(test_queries),
                "avg_query_time": avg_query_time,
                "total_time": total_time,
                "success": True
            }

            print(f"  Total queries: {len(queries)}")
            print(f"  Avg query time: {avg_query_time * 1000:.1f} ms")
            print(f"  Total time: {total_time:.1f}s")

            conn.close()

        except Exception as e:
            print(f"  Failed: {e}")
            results[name] = {"success": False, "error": str(e)}

    return results

benchmark_results = compare_benchmarks(0.01)
```

---

## Troubleshooting Performance Issues

### Common Performance Issues

#### Memory Issues

```python
import psutil
from benchbox import TPCH

def check_memory_requirements(scale_factor: float):

    estimated_data_gb = scale_factor * 1.0
    estimated_working_gb = estimated_data_gb * 2.5

    available_gb = psutil.virtual_memory().available / (1024**3)

    print(f"Scale factor {scale_factor}:")
    print(f"  Estimated data size: {estimated_data_gb:.1f} GB")
    print(f"  Estimated working memory: {estimated_working_gb:.1f} GB")
    print(f"  Available memory: {available_gb:.1f} GB")

    if estimated_working_gb > available_gb:
        print(f"  WARNING: Insufficient memory!")
        print(f"  Recommended scale factor: {available_gb / 2.5:.3f}")
        return False
    else:
        print(f"  OK: Sufficient memory available")
        return True

if check_memory_requirements(0.5):
    pass
else:
    print("Consider using a smaller scale factor")
```

The estimate uses a TPC-H rule of thumb: about 1 GB of data per unit of scale
factor, and 2.5 times that for working memory.

### Performance Optimization Tips

1. **Use DuckDB as your primary database** - it's configured for analytics workloads
2. **Start with small scale factors** (0.01-0.1) for development and testing
3. **Monitor memory usage** - keep working set under 50% of available RAM
4. **Use file-based DuckDB** for scale factors > 0.5 to avoid memory pressure
5. **Focus on simple queries first** - complex queries may be slower to debug
6. **Use SSD storage** for better I/O performance with larger datasets
7. **Clean up temporary files** and databases after testing
8. **Use connection pooling** for repeated query executions
9. **Profile your specific use case** - performance varies significantly by query type
10. **Consider your hardware** - more CPU cores and memory improve parallel query performance

---

## See Also

- [Getting Started](../usage/getting-started.md) - Basic BenchBox usage
- [Configuration](../usage/configuration.md) - Performance configuration options
- [Examples](../usage/examples.md) - Performance testing examples

---

**Next steps:** For production benchmarking, review the [TPC-H Official Guide](../guides/tpc/tpc-h-official-guide.md) for compliance requirements and [Performance Optimization](performance-optimization.md) for platform-specific tuning.
