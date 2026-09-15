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

## Library Performance Baselines

The automated performance suite exercises the BenchBox orchestration layer to
ensure the library remains lightweight. The current guardrails are summarized
below.

| Scenario | Metric | Threshold | Status |
| --- | --- | --- | --- |
| Lifecycle orchestration vs. direct adapter | Runtime overhead ratio | `< 1.30x` | Target* |
| Lifecycle orchestration | Peak memory overhead | `< 1 MB` | Enforced |
| Result exporting (`json`) | Peak allocation during export | `< 2.5 MB` | Enforced |
| Result exporting (`csv`) | Peak allocation during export | `< 3.0 MB` | Enforced |

*The runtime overhead test is currently skipped due to timing variability across
systems. Memory thresholds are actively enforced.

These baselines are defined in `tests/performance/test_library_overhead.py`. If
new functionality increases memory usage beyond the limits, the performance
tests will fail and surface a regression alert.

---

## Monitoring Utilities

BenchBox ships with reusable monitoring helpers in
`benchbox.monitoring.performance`.

### Deep CLI Integration

**Performance monitoring is now automatic by default** for all benchmark executions.
The CLI enables monitoring and progress tracking automatically, with options to
disable if needed.

```bash
# Standard run - monitoring enabled by default
benchbox run --platform duckdb --benchmark tpch --scale 1

# Disable monitoring (advanced option, use --help-topic all to see)
benchbox run --platform duckdb --benchmark tpch --no-monitoring

# Disable progress bars (simple text output)
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

# Attach the snapshot to BenchmarkResults (persists in exports and CLI output)
attach_snapshot_to_result(result, snapshot)

# Persist history for trend analysis / CI regressions
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

# Setup
tpch = TPCH(scale_factor=0.1)
# ... database setup (DuckDB recommended) ...

# Measure single query execution
def time_query(connection, query_sql: str, query_id: str = "") -> dict:
    """Time a single query execution."""

    start_time = time.time()
    result = connection.execute(query_sql).fetchall()
    execution_time = time.time() - start_time

    return {
        "query_id": query_id,
        "execution_time_seconds": execution_time,
        "rows_returned": len(result),
        "execution_time_ms": execution_time * 1000
    }

# Example usage
query_1 = tpch.get_query(1)
timing_result = time_query(connection, query_1, "Q1")

print(f"Query {timing_result['query_id']}:")
print(f"  Execution time: {timing_result['execution_time_ms']:.1f} ms")
print(f"  Rows returned: {timing_result['rows_returned']}")
```

### Multiple Query Timing

```python
import time
from benchbox import TPCH

def time_multiple_queries(connection, benchmark, query_ids: list) -> dict:
    """Time multiple query executions."""

    results = {}
    total_start_time = time.time()

    for query_id in query_ids:
        query_sql = benchmark.get_query(query_id)

        # Time individual query
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

# Example usage with DuckDB
import duckdb
from benchbox import TPCH

conn = duckdb.connect(":memory:")
tpch = TPCH(scale_factor=0.1)

# Setup database...
# (data loading code here)

# Time first 5 TPC-H queries
query_results = time_multiple_queries(conn, tpch, list(range(1, 6)))

print(f"\nTotal time for {query_results['queries_executed']} queries: "
      f"{query_results['total_execution_time']:.2f} seconds")
```

---

## Timing Benchmark Execution

### Complete Benchmark Timing

```python
import time
from benchbox import TPCH
import duckdb

def run_timed_benchmark(benchmark_class, scale_factor: float = 0.1) -> dict:
    """Run complete benchmark with detailed timing."""

    print(f"Running {benchmark_class.__name__} benchmark (SF={scale_factor})")

    # Initialize benchmark
    benchmark_start = time.time()
    benchmark = benchmark_class(scale_factor=scale_factor)

    # Time data generation
    print("Generating data...")
    data_gen_start = time.time()
    data_files = benchmark.generate_data()
    data_gen_time = time.time() - data_gen_start

    # Calculate data size
    total_size_mb = sum(f.stat().st_size for f in data_files) / (1024 * 1024)

    # Time database setup
    print("Setting up database...")
    setup_start = time.time()
    conn = duckdb.connect(":memory:")

    # Create tables
    ddl = benchmark.get_create_tables_sql()
    conn.execute(ddl)

    # Load data
    for file_path in data_files:
        table_name = file_path.stem
        conn.execute(f"""
            INSERT INTO {table_name}
            SELECT * FROM read_csv('{file_path}', delimiter='|', header=false)
        """)

    setup_time = time.time() - setup_start

    # Time query execution
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

    # Calculate statistics
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

# Example usage
benchmark_results = run_timed_benchmark(TPCH, scale_factor=0.1)

print(f"\n=== {benchmark_results['benchmark_name']} Results ===")
print(f"Data generation: {benchmark_results['timing']['data_generation_seconds']:.2f}s")
print(f"Database setup: {benchmark_results['timing']['database_setup_seconds']:.2f}s")
print(f"Query execution: {benchmark_results['timing']['query_execution_seconds']:.2f}s")
print(f"Total time: {benchmark_results['timing']['total_seconds']:.2f}s")
print(f"Average query time: {benchmark_results['query_stats']['average_query_time_ms']:.1f}ms")
print(f"Success rate: {benchmark_results['query_stats']['successful_queries']}/{benchmark_results['query_stats']['total_queries']}")
```

### Library Overhead Baselines

BenchBox includes automated performance tests that track the framework's own
runtime and memory overhead relative to direct adapter execution. The suite in
`tests/performance/test_library_overhead.py` establishes two baselines:

- **Runtime overhead** - `run_benchmark_lifecycle` must remain within 30% of the
  adapter-only baseline when executing a representative workload. The test
  simulates short-lived runs (1 ms) for both in-memory and file-backed
  configurations and asserts on the measured ratio.
- **Peak memory overhead** - lifecycle orchestration must add less than 1 MB of
  additional peak memory compared to the direct adapter path. Memory is tracked
  via `tracemalloc`, ensuring regressions are caught automatically.

Run the tests locally with:

```bash
uv run -- python -m pytest tests/performance/test_library_overhead.py
```

The failure messages include the measured ratio and peak memory deltas to aid
investigation should a regression occur.

### Performance Profiling

```python
import time
import psutil
import os
from benchbox import TPCH

def profile_benchmark_execution(benchmark_class, scale_factor: float = 0.1):
    """Profile benchmark execution with resource monitoring."""

    # Get initial system stats
    process = psutil.Process(os.getpid())
    initial_memory = process.memory_info().rss / (1024 * 1024)  # MB
    initial_cpu_time = process.cpu_times()

    print(f"Starting {benchmark_class.__name__} execution profile")
    print(f"Initial memory usage: {initial_memory:.1f} MB")

    # Run benchmark with monitoring
    start_time = time.time()

    # Data generation phase
    benchmark = benchmark_class(scale_factor=scale_factor)
    data_files = benchmark.generate_data()

    gen_memory = process.memory_info().rss / (1024 * 1024)
    gen_time = time.time() - start_time

    print(f"After data generation ({gen_time:.1f}s): {gen_memory:.1f} MB (+{gen_memory - initial_memory:.1f} MB)")

    # Database setup phase
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

    # Query execution phase
    queries = benchmark.get_queries()
    query_count = 0

    for query_id, query_sql in list(queries.items())[:5]:  # First 5 queries
        try:
            result = conn.execute(query_sql).fetchall()
            query_count += 1

            current_memory = process.memory_info().rss / (1024 * 1024)
            current_time = time.time() - start_time

            print(f"Query {query_id} ({current_time:.1f}s): {current_memory:.1f} MB, {len(result)} rows")

        except Exception as e:
            print(f"Query {query_id} failed: {e}")

    # Final stats
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

# Example usage
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
    """Simple memory usage monitoring during benchmark execution."""

    process = psutil.Process(os.getpid())

    def get_memory_mb():
        return process.memory_info().rss / (1024 * 1024)

    print(f"Initial memory: {get_memory_mb():.1f} MB")

    # Initialize benchmark
    tpch = TPCH(scale_factor=0.1)
    print(f"After benchmark init: {get_memory_mb():.1f} MB")

    # Generate data
    data_files = tpch.generate_data()
    print(f"After data generation: {get_memory_mb():.1f} MB")

    # Database operations
    import duckdb
    conn = duckdb.connect(":memory:")
    ddl = tpch.get_create_tables_sql()
    conn.execute(ddl)

    print(f"After DDL execution: {get_memory_mb():.1f} MB")

    # Load data
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
    """Run benchmark with memory-efficient patterns."""

    # Use smaller scale factor for memory constraints
    if scale_factor > 0.5:
        print("Warning: Large scale factor may cause memory issues")

    tpch = TPCH(scale_factor=scale_factor)

    # Generate data to disk (not kept in memory)
    data_files = tpch.generate_data()

    # Use file-based DuckDB for larger datasets
    if scale_factor > 0.1:
        conn = duckdb.connect("temp_benchmark.duckdb")
    else:
        conn = duckdb.connect(":memory:")

    # Create schema
    ddl = tpch.get_create_tables_sql()
    conn.execute(ddl)

    # Load data table by table to manage memory
    for file_path in data_files:
        table_name = file_path.stem
        print(f"Loading {table_name}...")

        conn.execute(f"""
            INSERT INTO {table_name}
            SELECT * FROM read_csv('{file_path}', delimiter='|', header=false)
        """)

        # Force garbage collection after each table
        gc.collect()

    # Run queries with results not stored in memory
    queries = tpch.get_queries()

    for query_id in list(queries.keys())[:5]:  # Limit to first 5
        query_sql = queries[query_id]

        # Execute but don't fetch all results
        cursor = conn.execute(query_sql)
        first_few_rows = cursor.fetchmany(10)  # Just sample

        print(f"Query {query_id}: Sample of {len(first_few_rows)} rows")

    conn.close()

    # Cleanup temporary files
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
    """Optimize DuckDB for benchmark performance."""

    # Connect with specific configuration
    conn = duckdb.connect(":memory:")

    # Configure DuckDB for analytical workloads
    # Note: DuckDB auto-detects appropriate settings, but you can override:

    if scale_factor >= 1.0:
        # For larger datasets, consider memory limits
        conn.execute("SET memory_limit='4GB'")
        conn.execute("SET threads=4")

    # Enable progress bar for long operations
    conn.execute("SET enable_progress_bar=true")

    # Optimize for analytical queries
    conn.execute("SET default_order='ASC'")

    # Setup benchmark
    tpch = TPCH(scale_factor=scale_factor)
    data_files = tpch.generate_data()

    # Create tables with optimizations
    ddl = tpch.get_create_tables_sql()
    conn.execute(ddl)

    # Load data efficiently
    print("Loading data with DuckDB optimizations...")
    for file_path in data_files:
        table_name = file_path.stem

        # Use DuckDB's configured CSV reader
        conn.execute(f"""
            INSERT INTO {table_name}
            SELECT * FROM read_csv('{file_path}',
                                   delimiter='|',
                                   header=false,
                                   auto_detect=false)
        """)

    # Collect statistics for query optimization
    conn.execute("ANALYZE")

    # Run queries with timing
    queries = tpch.get_queries()

    for query_id in [1, 3, 6, 12]:  # Representative queries
        query_sql = queries[query_id]

        # Enable query profiling
        conn.execute("PRAGMA enable_profiling='query_tree'")

        import time
        start_time = time.time()
        result = conn.execute(query_sql).fetchall()
        execution_time = time.time() - start_time

        print(f"Query {query_id}: {execution_time * 1000:.1f} ms ({len(result)} rows)")

        # Get query plan (optional)
        # plan = conn.execute("PRAGMA show_tables").fetchall()

optimize_duckdb_performance(0.1)
```

### DuckDB Performance Settings

```python
import duckdb
from benchbox import TPCH

def configure_duckdb_for_benchmark(memory_limit_gb: int = 4, num_threads: int = None):
    """Configure DuckDB with specific performance settings."""

    conn = duckdb.connect(":memory:")

    # Memory configuration
    conn.execute(f"SET memory_limit='{memory_limit_gb}GB'")

    # Thread configuration
    if num_threads:
        conn.execute(f"SET threads={num_threads}")
    else:
        # Use all available cores
        import os
        conn.execute(f"SET threads={os.cpu_count()}")

    # Performance settings
    conn.execute("SET enable_progress_bar=true")
    conn.execute("SET preserve_insertion_order=false")  # Allow reordering for performance

    # Query optimizer settings
    conn.execute("SET enable_optimizer=true")
    conn.execute("SET enable_profiling='query_tree'")

    return conn

# Example usage
conn = configure_duckdb_for_benchmark(memory_limit_gb=2, num_threads=4)

# Run benchmark with configured connection
tpch = TPCH(scale_factor=0.1)
# ... rest of benchmark code
```

---

## Performance Comparison

### Scale Factor Performance Comparison

```python
import time
from benchbox import TPCH
import duckdb

def compare_scale_factors(scale_factors: list = [0.01, 0.1, 0.5]):
    """Compare performance across different scale factors."""

    results = {}

    for sf in scale_factors:
        print(f"\n=== Testing Scale Factor {sf} ===")

        start_time = time.time()

        # Setup
        tpch = TPCH(scale_factor=sf)
        data_files = tpch.generate_data()

        # Calculate data size
        total_size_mb = sum(f.stat().st_size for f in data_files) / (1024 * 1024)

        # Database setup
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

        # Run subset of queries
        test_queries = [1, 3, 6, 12]  # Representative mix
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

    # Summary comparison
    print(f"\n=== Scale Factor Comparison ===")
    print("SF\tData(MB)\tSetup(s)\tAvg Query(ms)\tTotal(s)")
    for sf, metrics in results.items():
        print(f"{sf}\t{metrics['data_size_mb']:.1f}\t\t"
              f"{metrics['setup_time']:.1f}\t\t"
              f"{metrics['avg_query_time'] * 1000:.1f}\t\t"
              f"{metrics['total_time']:.1f}")

    return results

# Run comparison
performance_results = compare_scale_factors([0.01, 0.1, 0.5])
```

### Benchmark Comparison

```python
import time
import duckdb
from benchbox import TPCH, SSB

def compare_benchmarks(scale_factor: float = 0.01):
    """Compare performance across different benchmarks."""

    benchmarks = [
        ("TPC-H", TPCH),
        ("SSB", SSB),
    ]

    results = {}

    for name, benchmark_class in benchmarks:
        print(f"\n=== Testing {name} ===")

        try:
            start_time = time.time()

            # Setup benchmark
            benchmark = benchmark_class(scale_factor=scale_factor)
            data_files = benchmark.generate_data()

            # Database setup
            conn = duckdb.connect(":memory:")
            ddl = benchmark.get_create_tables_sql()
            conn.execute(ddl)

            for file_path in data_files:
                table_name = file_path.stem
                conn.execute(f"""
                    INSERT INTO {table_name}
                    SELECT * FROM read_csv('{file_path}', delimiter='|', header=false)
                """)

            # Get queries
            queries = benchmark.get_queries()

            # Test first few queries
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

# Run benchmark comparison
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
    """Check if system has enough memory for scale factor."""

    # Estimate memory needed
    estimated_data_gb = scale_factor * 1.0  # Rule of thumb for TPC-H
    estimated_working_gb = estimated_data_gb * 2.5  # Working memory

    # Check available memory
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

# Check before running benchmark
if check_memory_requirements(0.5):
    # Proceed with benchmark
    pass
else:
    print("Consider using a smaller scale factor")
```

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
