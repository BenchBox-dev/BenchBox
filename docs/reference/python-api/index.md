# Python API Reference

```{tags} reference, python-api
```

Complete reference for BenchBox's Python API, covering benchmarks, platform adapters, results, and utilities.

## Overview

BenchBox provides a comprehensive Python API for programmatic benchmark execution. The API is organized into several layers:

- **Benchmark Layer**: Abstract interfaces and concrete benchmark implementations
- **Platform Layer**: Database-specific adapters for query execution
- **Results Layer**: Structured result objects and validation
- **Utilities Layer**: Helper functions for common operations

## Quick Start

Basic benchmark execution:

```python
from benchbox.tpch import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = TPCH(scale_factor=0.1)
adapter = DuckDBAdapter()

results = benchmark.run_with_platform(adapter)

print(f"Completed {results.successful_queries} queries")
print(f"Average time: {results.average_query_time:.3f}s")
```

## API Organization

### Core APIs

```{toctree}
:maxdepth: 1

base
core
benchmarks
dataframe-query
dataframe-runtime
results
result-analysis
dataframe
```

### Platform Adapters

```{toctree}
:maxdepth: 1

platforms/common
platforms/duckdb
platforms/datafusion
platforms/sqlite
platforms/clickhouse
platforms/databricks
platforms/bigquery
platforms/snowflake
platforms/redshift
platforms/polars
```

### Utilities

```{toctree}
:maxdepth: 1

cloud-storage
data-validation
utilities-index
additional-utilities
```

### Performance & Monitoring

```{toctree}
:maxdepth: 1

performance-monitoring
tuning
```

## Common Patterns

### Data Generation

```python
from benchbox.tpcds import TPCDS

benchmark = TPCDS(scale_factor=1.0, output_dir="./tpcds_data")
data_files = benchmark.generate_data()

benchmark2 = TPCDS(scale_factor=1.0, output_dir="./tpcds_data")
```

The second benchmark reuses the data generated in the same directory. Generation is skipped when the data already exists.

### Query Access

```python
from benchbox.tpch import TPCH

benchmark = TPCH(scale_factor=0.1)

queries = benchmark.get_queries()

q1 = benchmark.get_query("q1")

q1_parameterized = benchmark.get_query("q1", params={"date": "1998-09-02"})
```

The example gets all queries, one specific query, and a query with parameters.

### Platform Execution

```python
from benchbox.clickbench import ClickBench
from benchbox.platforms.clickhouse import ClickHouseAdapter

benchmark = ClickBench(scale_factor=0.01)
adapter = ClickHouseAdapter(
    host="localhost",
    port=9000,
    database="benchmark"
)

results = benchmark.run_with_platform(
    adapter,
    query_subset=["Q1", "Q2", "Q3"]
)
```

The `query_subset` argument is optional. It limits the run to the listed queries.

### Result Analysis

```python
from benchbox.core.results.models import BenchmarkResults

results = BenchmarkResults.from_json_file("results.json")

for qr in results.query_results:
    if qr.status == "SUCCESS":
        print(f"{qr.query_id}: {qr.execution_time:.3f}s")

import math
times = [qr.execution_time for qr in results.query_results
         if qr.status == "SUCCESS"]
geomean = math.prod(times) ** (1.0 / len(times))
```

The example loads results from a file, prints the time of each successful query, and calculates the geometric mean of the successful query times.

### Cross-Platform Comparison

```python
from benchbox.tpch import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.platforms.clickhouse import ClickHouseAdapter

benchmark = TPCH(scale_factor=1.0)

platforms = {
    "DuckDB": DuckDBAdapter(),
    "ClickHouse": ClickHouseAdapter(host="localhost")
}

results = {}
for name, adapter in platforms.items():
    print(f"Running on {name}...")
    results[name] = benchmark.run_with_platform(adapter)

for name, result in results.items():
    print(f"{name}: {result.total_execution_time:.2f}s")
```

The final loop compares performance across the platforms.

### Error Handling

```python
from benchbox.tpch import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter

try:
    benchmark = TPCH(scale_factor=0.1)
    adapter = DuckDBAdapter()
    results = benchmark.run_with_platform(adapter)

    if results.failed_queries > 0:
        print(f"Warning: {results.failed_queries} queries failed")
        for qr in results.query_results:
            if qr.status == "FAILED":
                print(f"  {qr.query_id}: {qr.error_message}")

except ValueError as e:
    print(f"Configuration error: {e}")
except Exception as e:
    print(f"Execution error: {e}")
```

The `failed_queries` check reports query failures after the run.

## Type Hints

BenchBox provides comprehensive type hints for IDE support:

```python
from typing import Optional, Dict, Any, List
from benchbox.base import BaseBenchmark
from benchbox.core.results.models import BenchmarkResults

def run_benchmark(
    benchmark: BaseBenchmark,
    adapter,
    config: Optional[Dict[str, Any]] = None
) -> BenchmarkResults:
    return benchmark.run_with_platform(adapter, **(config or {}))
```

## Configuration Classes

Platform adapters accept configuration via constructor parameters:

```python
from benchbox.platforms.duckdb import DuckDBAdapter

adapter = DuckDBAdapter(
    database_path=":memory:",
    memory_limit="4GB",
    thread_limit=4,
    enable_profiling=True
)

from benchbox.platforms.clickhouse import ClickHouseAdapter

adapter = ClickHouseAdapter(
    host="localhost",
    port=9000,
    database="benchmark",
    username="default",
    password="",
    settings={
        "max_memory_usage": "8GB",
        "max_threads": 8
    }
)
```

The first adapter is a DuckDB configuration. `database_path` accepts `":memory:"` or a file path. The second adapter is a ClickHouse configuration.

## See Also

- {doc}`/reference/api-reference` - High-level API overview
- {doc}`/concepts/architecture` - System architecture and design
- {doc}`/concepts/workflow` - Common workflow patterns
- {doc}`/usage/examples` - Code examples and snippets
- {doc}`/usage/troubleshooting` - Common issues and solutions
