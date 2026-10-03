# Programmatic API Examples

**Using BenchBox as a Python library in your code**

This directory documents how to use BenchBox programmatically in your Python applications, scripts, and notebooks.

## Overview

BenchBox provides a clean Python API for:
- Creating benchmarks
- Running queries
- Collecting results
- Analyzing performance

All examples in the parent directories demonstrate programmatic usage. This README consolidates the key patterns.

## Basic Usage Pattern

```python
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH

benchmark = TPCH(
    scale_factor=0.01,
    output_dir="./data",
    force_regenerate=False
)

benchmark.generate_data()

adapter = DuckDBAdapter(database_path=":memory:")

results = adapter.run_benchmark(
    benchmark,
    test_execution_type="power"
)

print(f"Total time: {results.total_execution_time:.2f}s")
print(f"Queries: {results.total_queries}")
```

## Reference Examples

### Simple API Usage
See: [duckdb_coffeeshop.py](../duckdb_coffeeshop.py)
- Basic benchmark setup
- Direct database connection
- Query execution
- Result retrieval

### Feature-Specific Usage
See: [features/](../features/) directory
- `test_types.py`: Different execution types
- `query_subset.py`: Selective query execution
- `result_analysis.py`: Result processing
- `export_formats.py`: Output formatting

### Use-Case Patterns
See: [use_cases/](../use_cases/) directory
- `ci_regression_test.py`: Baseline comparison
- `platform_evaluation.py`: Multi-platform execution
- `incremental_tuning.py`: Iterative optimization

## API Reference

### Benchmark Creation

```python
from benchbox.tpch import TPCH
benchmark = TPCH(scale_factor=0.1, output_dir="./data")

from benchbox.tpcds import TPCDS
benchmark = TPCDS(scale_factor=0.1, output_dir="./data")

```

### Platform Adapters

```python
from benchbox.platforms.duckdb import DuckDBAdapter
adapter = DuckDBAdapter(database_path=":memory:")

from benchbox.platforms.sqlite import SQLiteAdapter
adapter = SQLiteAdapter(database_path="./db.sqlite")

from benchbox.platforms.clickhouse import ClickHouseAdapter
adapter = ClickHouseAdapter(host="localhost", port=9000)

```

### Running Benchmarks

```python
results = adapter.run_benchmark(
    benchmark,
    test_execution_type="power"
)

results = adapter.run_benchmark(
    benchmark,
    test_execution_type="power",
    query_subset=["1", "6", "12"]
)

results = adapter.run_benchmark(
    benchmark,
    test_execution_type="throughput",
    num_streams=4
)
```

### Result Processing

```python
print(results.total_execution_time)
print(results.total_queries)
print(results.successful_queries)
print(results.average_query_time)

for query_result in results.query_results:
    print(f"{query_result.query_name}: {query_result.execution_time:.3f}s")

results_dict = results.model_dump()
import json
with open("results.json", "w") as f:
    json.dump(results_dict, f, indent=2)
```

## Common Patterns

### 1. Batch Execution

```python
platforms = ["duckdb", "sqlite"]
results = {}

for platform in platforms:
    adapter = create_adapter(platform)
    results[platform] = adapter.run_benchmark(benchmark)
```

### 2. Result Comparison

```python
import json

baseline = json.load(open("baseline.json"))
current = json.load(open("current.json"))

baseline_time = baseline["total_execution_time"]
current_time = current["total_execution_time"]
change = (current_time - baseline_time) / baseline_time * 100

print(f"Performance change: {change:+.1f}%")
```

### 3. Custom Benchmarks

```python
from benchbox.base import BaseBenchmark

class MyBenchmark(BaseBenchmark):
    def generate_data(self):
        pass

    def get_query(self, query_id, params=None):
        pass
```

## Integration Examples

### Jupyter Notebooks

Install BenchBox in the notebook environment first:

```bash
uv pip install benchbox
```

```python
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH

benchmark = TPCH(scale_factor=0.01, output_dir="./data")
benchmark.generate_data()

adapter = DuckDBAdapter(database_path=":memory:")
results = adapter.run_benchmark(benchmark, test_execution_type="power")

import pandas as pd
import matplotlib.pyplot as plt

df = pd.DataFrame([
    {"query": q.query_name, "time": q.execution_time}
    for q in results.query_results
])

df.plot(x="query", y="time", kind="bar")
plt.show()
```

### FastAPI Integration

```python
from fastapi import FastAPI
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH

app = FastAPI()

@app.post("/benchmark/run")
async def run_benchmark(scale_factor: float = 0.01):
    benchmark = TPCH(scale_factor=scale_factor, output_dir="./data")
    benchmark.generate_data()

    adapter = DuckDBAdapter(database_path=":memory:")
    results = adapter.run_benchmark(benchmark, test_execution_type="power")

    return {
        "total_time": results.total_execution_time,
        "queries": results.total_queries,
        "successful": results.successful_queries
    }
```

### Airflow DAG

```python
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime

def run_performance_test():
    from benchbox.platforms.duckdb import DuckDBAdapter
    from benchbox.tpch import TPCH

    benchmark = TPCH(scale_factor=0.1, output_dir="/tmp/data")
    benchmark.generate_data()

    adapter = DuckDBAdapter(database_path=":memory:")
    results = adapter.run_benchmark(benchmark, test_execution_type="power")

    import json
    with open("/tmp/results.json", "w") as f:
        json.dump(results.model_dump(), f)

with DAG("performance_test", start_date=datetime(2024, 1, 1), schedule="@daily") as dag:
    test_task = PythonOperator(
        task_id="run_benchmark",
        python_callable=run_performance_test
    )
```

## Tips

1. **Reuse Benchmark Objects**: Create once, run multiple times
2. **Cache Data**: Use `force_regenerate=False` to reuse generated data
3. **Handle Errors**: Wrap in try/except for production code
4. **Clean Up**: Close database connections after use
5. **Memory Management**: Use file-based databases for large scale factors

## Next Steps

- Review [features/](../features/) for capability-specific examples
- Check [use_cases/](../use_cases/) for real-world patterns
- Read [PATTERNS.md](../PATTERNS.md) for workflow combinations
- Use [unified_runner.py](../unified_runner.py) for production workflows

---

**Remember:** All feature and use-case examples demonstrate programmatic usage. Study their source code for additional patterns.
