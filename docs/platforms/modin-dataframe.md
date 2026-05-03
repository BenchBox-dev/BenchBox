<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Modin DataFrame Platform

```{tags} intermediate, guide, modin, dataframe-platform
```

Modin is a drop-in replacement for Pandas that enables parallel and distributed DataFrame operations. BenchBox supports benchmarking Modin using its Pandas-compatible API through the `modin-df` platform.

## Overview

| Attribute | Value |
|-----------|-------|
| CLI Name | `modin-df` |
| Family | Pandas |
| Execution | Eager (parallel) |
| Best For | Large datasets that don't fit in single-core Pandas |
| Min Version | 0.32.0 |

## Features

- **Drop-in Pandas replacement** - Same API as Pandas with automatic parallelization
- **Multiple backends** - Ray (default), Dask, or Unidist execution engines
- **Automatic parallelization** - No code changes needed for parallel execution
- **Full TPC-H support** - All 22 queries implemented via Pandas family

## How Modin Works

Modin partitions DataFrames across CPU cores and executes operations in parallel:

```
                  ┌─────────┐
                  │  Modin  │
                  │DataFrame│
                  └────┬────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐
    │Partition│   │Partition│   │Partition│
    │   1     │   │   2     │   │   3     │
    └────┬────┘   └────┬────┘   └────┬────┘
         │             │             │
         ▼             ▼             ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐
    │  Core   │   │  Core   │   │  Core   │
    │   1     │   │   2     │   │   3     │
    └─────────┘   └─────────┘   └─────────┘
```

## Installation

```bash
# Install Modin with Ray backend (recommended)
uv add benchbox --extra modin

# For Dask backend
uv add "modin[dask]"

# For Unidist backend (experimental)
uv add "modin[unidist]"
```

### Verify Installation

```bash
# Check package and selected backend without initializing Ray/Dask
benchbox platforms check modin-df

# Optional import smoke
uv run -- python -c "import modin.pandas as pd; print('Modin ready')"
```

## Quick Start

```bash
# Run TPC-H on Modin DataFrame platform (uses Ray backend by default)
benchbox run --platform modin-df --benchmark tpch --scale 0.1

# Specify the Ray backend explicitly
benchbox run --platform modin-df --benchmark tpch --scale 1 \
  --platform-option engine=ray

# Use Dask backend
benchbox run --platform modin-df --benchmark tpch --scale 1 \
  --platform-option engine=dask
```

`benchbox platforms check modin-df` reads `MODIN_ENGINE` (default `ray`) and verifies the corresponding backend
package is importable. The check does not import `modin.pandas`, start Ray, or create a Dask client.

## Configuration Options

| Option | Default | Choices | Description |
|--------|---------|---------|-------------|
| `engine` | `ray` | `ray`, `dask`, `unidist` | Execution backend |

### Backend Comparison

| Backend | Best For | Notes |
|---------|----------|-------|
| **Ray** (default) | Most use cases | Best single-machine performance |
| **Dask** | Distributed clusters | Integrates with existing Dask infrastructure |
| **Unidist** | MPI environments | Experimental, for HPC clusters |

## Scale Factor Guidelines

Modin can handle larger datasets than Pandas by utilizing multiple cores:

| Scale Factor | Data Size | Memory Required | Cores Used |
|--------------|-----------|-----------------|------------|
| 0.01 | ~10 MB | ~500 MB | 1-2 |
| 0.1 | ~100 MB | ~1 GB | 2-4 |
| 1.0 | ~1 GB | ~4 GB | 4-8 |
| 10.0 | ~10 GB | ~40 GB | 8-16 |
| 100.0 | ~100 GB | ~400 GB | 16-32+ |

**Recommendation:** For SF > 10 with limited memory, consider using Dask DataFrame (`dask-df`) for out-of-core processing.

## Performance Characteristics

### Strengths

- **Easy migration** - Change `import pandas as pd` to `import modin.pandas as pd`
- **Automatic parallelization** - Operations scale across available CPU cores
- **Memory efficiency** - Partitioned execution reduces peak memory
- **Familiar API** - No learning curve for Pandas users

### Considerations

- **Overhead** - Small datasets may be slower due to parallelization overhead
- **API coverage** - Not all Pandas operations are equally optimized
- **Backend dependency** - Requires Ray, Dask, or Unidist

### When to Use Modin

| Use Case | Recommendation |
|----------|----------------|
| Pandas code with large data | Use `modin-df` |
| Small data (< 1GB) | Use `pandas-df` (less overhead) |
| Distributed cluster | Use `dask-df` |
| GPU available | Use `cudf-df` |
| Production analytics | Use `polars-df` (optimized) |

### Parallelization Behavior

Modin can utilize multiple CPU cores for parallel execution. The actual performance improvement depends on:

- Operation type (some operations parallelize better than others)
- Dataset size (larger datasets benefit more from parallelization)
- Data distribution and partition characteristics
- Available CPU cores and memory bandwidth <!-- content-ok: cliche -->
- Backend engine (Ray, Dask, or Unidist)

Run benchmarks with your specific workloads to measure actual performance characteristics.

## Query Implementation

Modin uses the same Pandas-compatible API:

```python
# TPC-H Q1: Pricing Summary Report (Modin)
def q1_pandas_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")  # Modin DataFrame

    cutoff = date(1998, 12, 1) - timedelta(days=90)
    filtered = lineitem[lineitem["l_shipdate"] <= cutoff]

    filtered = filtered.copy()
    filtered["disc_price"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])
    filtered["charge"] = filtered["disc_price"] * (1 + filtered["l_tax"])

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

## Python API

```python
from benchbox.platforms.dataframe import ModinDataFrameAdapter

# Create adapter with Ray backend
adapter = ModinDataFrameAdapter(
    working_dir="./benchmark_data",
    engine="ray"
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

## Troubleshooting

### Ray Initialization Errors

```
ray.exceptions.RaySystemError: System error: ...
```

**Solutions:**
1. Ensure Ray is properly installed: `uv add "modin[ray]"`
2. Initialize Ray manually: `ray.init()`
3. Check for port conflicts on default Ray ports

### Slow Performance

If Modin is slower than expected:

1. **Check dataset size** - Small datasets have parallelization overhead
2. **Check operation** - Some operations fall back to Pandas
3. **Check memory** - Insufficient memory causes swapping

```python
# Check if operation fell back to Pandas
import modin.config as cfg
cfg.IsExperimental.put(False)  # Disable fallback warnings
```

### Memory Issues

```
MemoryError: ...
```

**Solutions:**
1. Reduce scale factor
2. Use Dask backend for out-of-core: `--platform-option engine=dask`
3. Increase system memory or use distributed cluster

### Import Warnings

```
UserWarning: Modin is not using Ray...
```

The backend wasn't properly initialized. Set explicitly:

```python
import os
os.environ["MODIN_ENGINE"] = "ray"  # Before importing modin
import modin.pandas as pd
```

## Comparison: Modin vs Other DataFrame Platforms

| Aspect | Modin (`modin-df`) | Pandas (`pandas-df`) | Dask (`dask-df`) |
|--------|-------------------|----------------------|-------------------|
| API | Pandas-compatible | Native Pandas | Pandas-like |
| Parallelism | Automatic | None | Manual partitioning |
| Memory | Multi-core | Single-core | Out-of-core |
| Best for | Easy migration | Small data | Large/distributed |

## Related Documentation

- [DataFrame Platforms Overview](dataframe.md) - Architecture and concepts
- [Pandas DataFrame](pandas-dataframe.md) - Single-core Pandas
- [Dask DataFrame](dask-dataframe.md) - Distributed DataFrame
- [cuDF Platform](cudf.md) - GPU-accelerated DataFrame
- [Getting Started](../usage/getting-started.md) - BenchBox quick start
