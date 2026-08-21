<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Polars Platform

```{tags} intermediate, guide, polars, dataframe-platform
```

Polars is a high-performance DataFrame library implemented in Rust with Python bindings. It provides both lazy and eager execution modes, with automatic query optimization and parallelization.

BenchBox supports **two modes** for benchmarking Polars:

| Mode | CLI Name | Query Type | Best For |
|------|----------|------------|----------|
| **SQL Mode** | `polars` | SQL strings via SQLContext | SQL-oriented workflows |
| **DataFrame Mode** | `polars-df` | Native expression API | DataFrame-native workflows |

## Features

- **Fast execution** - Rust-based implementation with SIMD optimizations
- **Lazy execution** - Build query plans and optimize before execution
- **Memory efficient** - Zero-copy operations and out-of-core processing
- **SQL support** - Query DataFrames using SQL via `pl.SQLContext`
- **Parallel execution** - Automatic parallelization across CPU cores
- **Native file formats** - Parquet, CSV, JSON, Arrow IPC

## Installation

```bash
# Install Polars
pip install polars

# Or with all optional dependencies
pip install "polars[all]"
```

## Configuration

### CLI Options

```bash
# SQL Mode - queries executed via Polars SQLContext
benchbox run --platform polars --benchmark tpch --scale 0.1

# DataFrame Mode - queries executed via native expression API
benchbox run --platform polars-df --benchmark tpch --scale 0.1
```

### Platform Options (SQL Mode: `polars`)

| Option | Default | Description |
|--------|---------|-------------|
| `execution_mode` | lazy | Execution mode (lazy, eager) |
| `streaming` | false | Enable streaming execution for large datasets |
| `n_threads` | auto | Number of threads for parallel execution |
| `driver_version` | (latest) | Pin the polars package version (e.g. `1.36.1`) |
| `driver_auto_install` | false | Auto-install the requested driver version via uv if missing |

### Platform Options (DataFrame Mode: `polars-df`)

| Option | Default | Description |
|--------|---------|-------------|
| `streaming` | false | Enable streaming mode for large datasets |
| `rechunk` | true | Rechunk data for better memory layout |
| `n_rows` | - | Limit rows to read (for testing) |
| `driver_version` | (latest) | Pin the polars package version (e.g. `1.36.1`) |
| `driver_auto_install` | false | Auto-install the requested driver version via uv if missing |

### Testing a Specific Polars Version

```bash
benchbox run --platform polars-df --benchmark tpch \
  --platform-option driver_version=1.36.1 \
  --platform-option driver_auto_install=true
```

See {ref}`driver-version-management` for the full guide, including why `uv run` may
revert a manually-installed version and how to work around it.

## Usage Examples

### Basic Benchmark Run

```bash
# SQL Mode - Run TPC-H using SQL queries
benchbox run --platform polars --benchmark tpch --scale 0.1

# DataFrame Mode - Run TPC-H using native expressions
benchbox run --platform polars-df --benchmark tpch --scale 0.1
```

### Compare SQL vs DataFrame Performance

```bash
# Same benchmark, different execution paradigms
benchbox run --platform polars --benchmark tpch --scale 1 --output ./polars-sql
benchbox run --platform polars-df --benchmark tpch --scale 1 --output ./polars-df

# Compare results
benchbox compare ./polars-sql ./polars-df
```

### Python API

```python
from benchbox import TPCH
from benchbox.platforms.polars_platform import PolarsAdapter

# Initialize adapter
adapter = PolarsAdapter()

# Load and run benchmark
benchmark = TPCH(scale_factor=0.1)
benchmark.generate_data()
adapter.load_benchmark(benchmark)
results = adapter.run_benchmark(benchmark)
```

### Direct Polars Usage

```python
import polars as pl
from benchbox import TPCH

# Generate benchmark data
tpch = TPCH(scale_factor=0.1)
tpch.generate_data()

# Load data into Polars
lineitem = pl.scan_csv(tpch.tables["lineitem"], separator="|")
orders = pl.scan_csv(tpch.tables["orders"], separator="|")

# Run SQL query
ctx = pl.SQLContext()
ctx.register("lineitem", lineitem)
ctx.register("orders", orders)

result = ctx.execute("""
    SELECT l_returnflag, SUM(l_quantity) as total_qty
    FROM lineitem
    GROUP BY l_returnflag
    ORDER BY l_returnflag
""").collect()

print(result)
```

## Execution Modes

### Lazy Execution (Default)

Lazy execution builds a query plan and optimizes before execution:

```python
# Polars optimizes the entire query plan
df = (
    pl.scan_csv("lineitem.csv")
    .filter(pl.col("l_quantity") > 10)
    .group_by("l_returnflag")
    .agg(pl.sum("l_quantity"))
    .collect()  # Execute the optimized plan
)
```

Optimizations include:
- Predicate pushdown
- Projection pushdown
- Common subexpression elimination
- Join reordering

### Eager Execution

For immediate results without optimization:

```python
adapter = PolarsAdapter(execution_mode="eager")
```

### Streaming Mode

For datasets larger than memory:

```python
adapter = PolarsAdapter(streaming=True)
```

## Performance Characteristics

### Strengths

- **CPU-bound queries**: Excellent vectorized execution
- **In-memory analytics**: Optimized for RAM-resident data
- **File scanning**: Efficient Parquet/CSV reading with pushdown
- **Parallel aggregations**: Automatic multi-core utilization

### Considerations

- **Single-node only**: No distributed execution
- **Memory bound**: Large datasets require streaming mode
- **SQL subset**: Some advanced SQL features not yet supported

## Benchmark Recommendations

### Best For

- Local development and testing
- Small to medium datasets (up to ~100GB)
- Quick iteration and prototyping
- Comparison baseline against DuckDB

### Scale Factor Guidelines

| Scale Factor | Memory Required | Use Case |
|--------------|-----------------|----------|
| 0.01 | ~100 MB | Unit testing, CI/CD |
| 0.1 | ~500 MB | Integration testing |
| 1.0 | ~4 GB | Standard benchmarking |
| 10.0 | ~40 GB (streaming) | Large-scale testing |

**Note:** Execution times vary based on query complexity, hardware, and configuration. Run benchmarks to establish baselines for your environment.

## Comparison with DuckDB

| Aspect | Polars | DuckDB |
|--------|--------|--------|
| Language | Rust/Python | C++/Python |
| Execution | DataFrame API + SQL | SQL-first |
| Persistence | External files | Embedded database |
| Best for | DataFrame workflows | SQL queries |

## Troubleshooting

### Memory Errors

```python
# Enable streaming for large datasets
adapter = PolarsAdapter(streaming=True)
```

### SQL Syntax Errors

Polars SQL supports a subset of SQL. For unsupported features, use the DataFrame API:

```python
# Instead of unsupported SQL, use DataFrame API
result = (
    df.filter(pl.col("column") > 10)
    .group_by("category")
    .agg(pl.sum("value"))
)
```

### Thread Configuration

```python
# Limit thread usage
import polars as pl
pl.Config.set_global_string_cache()
```

## DataFrame Mode Deep Dive <!-- content-ok: cliche -->

The `polars-df` platform executes TPC-H queries using Polars' native expression API instead of SQL. This provides:

- **Full lazy optimization** - Polars query planner optimizes the entire expression chain
- **Type safety** - Expression errors caught at construction time
- **Composability** - Build complex queries from reusable expression components

### Expression API Example

```python
# TPC-H Q1 implemented with Polars expressions
result = (
    lineitem.filter(col("l_shipdate") <= lit(cutoff_date))
    .group_by("l_returnflag", "l_linestatus")
    .agg(
        col("l_quantity").sum().alias("sum_qty"),
        col("l_extendedprice").sum().alias("sum_base_price"),
        (col("l_extendedprice") * (lit(1) - col("l_discount")))
            .sum().alias("sum_disc_price"),
    )
    .sort("l_returnflag", "l_linestatus")
)
```

### When to Use DataFrame Mode

| Use Case | Recommended Mode |
|----------|------------------|
| SQL-based workflows | `polars` (SQL mode) |
| DataFrame-native development | `polars-df` (DataFrame mode) |
| Comparing with Pandas | `polars-df` (same paradigm) |
| Maximum optimization control | `polars-df` (expression API) |

### Streaming Mode for Large Data

```bash
# Enable streaming for datasets larger than memory
benchbox run --platform polars-df --benchmark tpch --scale 100 \
  --platform-option streaming=true
```

## Related Documentation

- [DataFrame Platforms Overview](dataframe.md) - DataFrame architecture and concepts
- [Pandas DataFrame](pandas-dataframe.md) - Pandas DataFrame mode
- [DuckDB](../usage/getting-started.md) - SQL-first embedded database
- [DataFusion](datafusion.md) - Rust-based SQL engine
- [CUDF](cudf.md) - GPU-accelerated DataFrames
