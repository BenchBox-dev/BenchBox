<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Pandas DataFrame Platform

```{tags} intermediate, guide, pandas, dataframe-platform
```

Pandas is the most widely-used Python data analysis library, with over 50 million monthly downloads. BenchBox supports benchmarking Pandas using its native DataFrame API through the `pandas-df` platform.

## Overview

| Attribute | Value |
|-----------|-------|
| CLI Name | `pandas-df` |
| Family | Pandas |
| Execution | Eager |
| Best For | Small to medium datasets (up to ~10GB) |
| Min Version | 2.0.0 |

## Features

- **Familiar API** - Industry-standard DataFrame operations
- **Eager evaluation** - Immediate result computation
- **Flexible backends** - NumPy, nullable NumPy, or PyArrow
- **Ecosystem integration** - Works with the entire Python data science stack

## Installation

```bash
# Install Pandas DataFrame support
uv add benchbox --extra pandas

# Or with pip
pip install "benchbox[pandas]"

# Verify installation
python -c "import pandas; print(f'Pandas {pandas.__version__}')"
```

## Quick Start

```bash
# Run TPC-H on Pandas DataFrame
benchbox run --platform pandas-df --benchmark tpch --scale 0.01

# With PyArrow backend (2-5x faster for aggregations)
benchbox run --platform pandas-df --benchmark tpch --scale 0.1 \
  --platform-option dtype_backend=pyarrow
```

## Configuration Options

| Option | Default | Choices | Description |
|--------|---------|---------|-------------|
| `dtype_backend` | `numpy_nullable` | `numpy`, `numpy_nullable`, `pyarrow` | Backend for nullable data types |

### dtype_backend Options

**`numpy`** - Classic NumPy backend
- Fastest for numeric-only data
- No native nullable integer/boolean support
- Uses `NaN` for missing values

**`numpy_nullable`** (Default) - Nullable extension types
- Native nullable `Int64`, `boolean`, `string` types
- Good balance of performance and correctness
- Recommended for most use cases

**`pyarrow`** - Apache Arrow backend
- Best memory efficiency
- Native string type (not object dtype)
- Excellent for mixed-type data
- Requires `pyarrow` package

```bash
# Example: Use PyArrow backend for large datasets
benchbox run --platform pandas-df --benchmark tpch --scale 1 \
  --platform-option dtype_backend=pyarrow
```

## Scale Factor Guidelines

Pandas loads entire datasets into memory with eager evaluation:

| Scale Factor | Data Size | Memory Required | Use Case |
|--------------|-----------|-----------------|----------|
| 0.01 | ~10 MB | ~500 MB | Unit testing, CI/CD |
| 0.1 | ~100 MB | ~2 GB | Integration testing |
| 1.0 | ~1 GB | ~6 GB | Standard benchmarking |
| 10.0 | ~10 GB | ~60 GB | Large-scale testing |

**Note:** Execution times vary based on query complexity, hardware, and configuration. For SF > 10, consider using Polars DataFrame (`polars-df`) or distributed alternatives.

## Performance Characteristics

### Strengths

- **Simplicity** - Straightforward API for common operations
- **Ecosystem** - Extensive integration with ML/visualization libraries
- **Development speed** - Fast prototyping and iteration

### Limitations

- **Memory usage** - Eager evaluation loads all data
- **Single-threaded** - Most operations don't parallelize automatically
- **String performance** - Object dtype for strings is slow

### Performance Tips

1. **Use PyArrow backend** for string-heavy workloads:
   ```bash
   --platform-option dtype_backend=pyarrow
   ```

2. **Reduce scale factor** for faster iteration:
   ```bash
   --scale 0.01  # Start small
   ```

3. **Consider Polars** for larger datasets:
   ```bash
   --platform polars-df  # Lazy evaluation and automatic parallelization
   ```

## Query Implementation

Pandas queries use string-based column access and boolean indexing:

```python
# TPC-H Q1: Pricing Summary Report
def q1_pandas_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")

    # Filter using boolean indexing
    cutoff = pd.to_datetime("1998-12-01") - pd.Timedelta(days=90)
    filtered = lineitem[lineitem["l_shipdate"] <= cutoff]

    # Compute derived columns
    filtered = filtered.assign(
        disc_price=filtered["l_extendedprice"] * (1 - filtered["l_discount"]),
        charge=filtered["l_extendedprice"] * (1 - filtered["l_discount"]) * (1 + filtered["l_tax"])
    )

    # Aggregate
    result = (
        filtered
        .groupby(["l_returnflag", "l_linestatus"], as_index=False)
        .agg({
            "l_quantity": ["sum", "mean"],
            "l_extendedprice": ["sum", "mean"],
            "disc_price": "sum",
            "charge": "sum",
            "l_discount": "mean",
            "l_orderkey": "count"
        })
        .sort_values(["l_returnflag", "l_linestatus"])
    )

    return result
```

## Comparison: Pandas vs Polars DataFrame

| Aspect | Pandas (`pandas-df`) | Polars (`polars-df`) |
|--------|---------------------|---------------------|
| Execution | Eager | Lazy (optimized) |
| Memory | Higher | Lower |
| Parallelism | Manual | Automatic |
| Best for | Prototyping, ecosystem integration | Larger datasets, performance-critical workloads |

**Note:** Performance differences vary significantly based on workload characteristics, dataset size, and specific operations. Run benchmarks with your actual workloads to determine which library best fits your needs.

## Troubleshooting

### MemoryError

```
MemoryError: Unable to allocate array with shape (N,) and dtype float64
```

**Solutions:**
1. Reduce scale factor: `--scale 0.1`
2. Use PyArrow backend: `--platform-option dtype_backend=pyarrow`
3. Switch to Polars: `--platform polars-df`

### Slow String Operations

If queries involving string columns are slow:

```bash
# Use PyArrow for efficient string handling
--platform-option dtype_backend=pyarrow
```

### Type Conversion Warnings

```
FutureWarning: Downcasting object dtype arrays...
```

These are safe to ignore or suppress with `--quiet`.

## Python API

```python
from benchbox.platforms.dataframe import PandasDataFrameAdapter

# Create adapter with custom configuration
adapter = PandasDataFrameAdapter(
    working_dir="./benchmark_data",
    dtype_backend="pyarrow"
)

# Create context and load tables
ctx = adapter.create_context()
adapter.load_tables(ctx, data_dir="./tpch_data")

# Execute query
from benchbox.core.tpch.dataframe_queries import TPCH_DATAFRAME_QUERIES
query = TPCH_DATAFRAME_QUERIES.get_query("Q1")
result = adapter.execute_query(ctx, query)
print(result)
```

## Related Documentation

- [DataFrame Platforms Overview](dataframe.md) - Architecture and concepts
- [Polars Platform](polars.md) - Polars SQL mode
- [cuDF Platform](cudf.md) - GPU-accelerated Pandas-compatible library
- [Getting Started](../usage/getting-started.md) - BenchBox quick start
