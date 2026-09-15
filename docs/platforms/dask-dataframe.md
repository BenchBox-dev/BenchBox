<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Dask DataFrame Platform

```{tags} intermediate, guide, dask, dataframe-platform
```

Dask is a flexible parallel computing library that enables distributed DataFrame operations. BenchBox supports benchmarking Dask using its Pandas-compatible API through the `dask-df` platform.

## Overview

| Attribute | Value |
|-----------|-------|
| CLI Name | `dask-df` |
| Family | Pandas |
| Execution | Lazy (partitioned) |
| Best For | Large datasets, distributed clusters, out-of-core processing |
| Min Version | 2024.1.0 |

## Features

- **Out-of-core processing** - Handle datasets larger than memory
- **Distributed execution** - Scale across clusters with Dask Distributed
- **Lazy evaluation** - Build computation graphs before execution
- **Pandas-like API** - Familiar DataFrame operations
- **Full TPC-H support** - All 22 queries implemented via Pandas family

## How Dask Works

Dask partitions DataFrames into chunks and builds a task graph for lazy execution:

```
                  ┌───────────────┐
                  │ Dask DataFrame│
                  │  (lazy graph) │
                  └───────┬───────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
     ┌─────────┐    ┌─────────┐    ┌─────────┐
     │Partition│    │Partition│    │Partition│
     │    1    │    │    2    │    │    3    │
     └────┬────┘    └────┬────┘    └────┬────┘
          │               │               │
          ▼               ▼               ▼
     ┌─────────┐    ┌─────────┐    ┌─────────┐
     │  Task   │    │  Task   │    │  Task   │
     │ groupby │    │ groupby │    │ groupby │
     └────┬────┘    └────┬────┘    └────┬────┘
          │               │               │
          └───────────────┼───────────────┘
                          ▼
                   ┌─────────────┐
                   │   .compute()│
                   │   (execute) │
                   └─────────────┘
```

## Installation

```bash
# Install Dask DataFrame support
uv add benchbox --extra dask

# Or with pip
pip install "benchbox[dask]"

# For distributed execution
pip install "dask[distributed]"
```

### Verify Installation

```bash
python -c "import dask.dataframe as dd; print('Dask DataFrame ready')"
```

## Quick Start

```bash
# Run TPC-H on Dask DataFrame platform
benchbox run --platform dask-df --benchmark tpch --scale 0.1

# Configure workers for local execution
benchbox run --platform dask-df --benchmark tpch --scale 1 \
  --platform-option n_workers=4 \
  --platform-option threads_per_worker=2

# Use distributed scheduler
benchbox run --platform dask-df --benchmark tpch --scale 10 \
  --platform-option use_distributed=true

# Connect to existing cluster
benchbox run --platform dask-df --benchmark tpch --scale 100 \
  --platform-option scheduler_address=tcp://scheduler:8786
```

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `n_workers` | auto | Number of worker processes |
| `threads_per_worker` | 1 | Threads per worker |
| `use_distributed` | false | Use Dask Distributed scheduler |
| `scheduler_address` | - | Address of existing Dask scheduler |

### Scheduler Options

**Synchronous** (default for small data):
- Single-threaded, good for debugging
- No parallelization overhead

**Threaded** (default for local):
- Multi-threaded within single process
- Good for I/O-bound operations

**Processes** (multi-core):
- Multiple processes for CPU-bound work
- Avoids Python GIL limitations

**Distributed** (clusters):
- Full distributed execution
- Scales across multiple machines

## Scale Factor Guidelines

Dask excels at out-of-core and distributed workloads:

| Scale Factor | Data Size | Memory Per Worker | Workers |
|--------------|-----------|-------------------|---------|
| 0.1 | ~100 MB | ~1 GB | 1-2 |
| 1.0 | ~1 GB | ~4 GB | 2-4 |
| 10.0 | ~10 GB | ~8 GB | 4-8 |
| 100.0 | ~100 GB | ~16 GB | 8-16 |
| 1000.0 | ~1 TB | ~32 GB | 16+ |

**Key insight:** Dask can process data larger than memory by streaming partitions.

## Performance Characteristics

### Strengths

- **Out-of-core** - Process datasets larger than available RAM
- **Distributed** - Scale horizontally across cluster nodes
- **Lazy execution** - Optimize full computation graph before running
- **Integration** - Works with Pandas, NumPy, scikit-learn ecosystem

### Considerations

- **Overhead** - Task scheduling has overhead for small operations
- **Shuffles** - Operations requiring data movement (joins, groupby) can be expensive
- **Learning curve** - Understanding partitioning and task graphs takes time

### When to Use Dask

| Use Case | Recommendation |
|----------|----------------|
| Data fits in memory | Use `pandas-df` or `polars-df` |
| Data larger than memory | Use `dask-df` |
| Cluster available | Use `dask-df` with distributed |
| GPU available | Use `cudf-df` (or Dask-cuDF) |
| Maximum single-node speed | Use `polars-df` |

### Performance Tips

1. **Use appropriate partition sizes** (100 MB - 1 GB per partition)
2. **Persist intermediate results** for iterative algorithms
3. **Use Parquet files** for efficient partial reads
4. **Minimize shuffles** by filtering early in the pipeline

## Query Implementation

Dask uses Pandas-compatible API with lazy evaluation:

```python
# TPC-H Q1: Pricing Summary Report (Dask)
def q1_pandas_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")  # Dask DataFrame

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
        .compute()  # Trigger computation
    )

    return result
```

## Python API

```python
from benchbox.platforms.dataframe import DaskDataFrameAdapter

# Create adapter for local execution
adapter = DaskDataFrameAdapter(
    working_dir="./benchmark_data",
    n_workers=4,
    threads_per_worker=2
)

# Or connect to distributed cluster
adapter = DaskDataFrameAdapter(
    working_dir="./benchmark_data",
    use_distributed=True,
    scheduler_address="tcp://scheduler:8786"
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

## Distributed Cluster Setup

### Local Cluster (Multi-Process)

```python
from dask.distributed import Client, LocalCluster

# Create local cluster
cluster = LocalCluster(
    n_workers=4,
    threads_per_worker=2,
    memory_limit="4GB"
)
client = Client(cluster)

# Run benchmark
adapter = DaskDataFrameAdapter(
    use_distributed=True,
    scheduler_address=client.scheduler.address
)
```

### Remote Cluster

```bash
# On scheduler machine
dask scheduler

# On worker machines
dask worker tcp://scheduler:8786

# In BenchBox
benchbox run --platform dask-df --benchmark tpch --scale 100 \
  --platform-option scheduler_address=tcp://scheduler:8786
```

### Kubernetes

```bash
# Using Dask Kubernetes operator
helm install dask dask/dask

# Connect to the scheduler
benchbox run --platform dask-df --benchmark tpch --scale 1000 \
  --platform-option scheduler_address=tcp://dask-scheduler:8786
```

## Troubleshooting

### Memory Errors

```
distributed.worker - WARNING - Memory use is high but worker has no data to store
```

**Solutions:**
1. Increase memory per worker
2. Reduce partition size
3. Use fewer workers with more memory each
4. Add more workers to distribute load

### Slow Performance

**Check partition count:**
```python
ddf.npartitions  # Should be 2-4x number of workers
```

**Repartition if needed:**
```python
ddf = ddf.repartition(npartitions=16)
```

### Shuffle Errors

```
KilledWorker: ... exceeded memory limit
```

**Solutions:**
1. Increase worker memory
2. Use `persist()` to materialize intermediate results
3. Break large shuffles into smaller operations

### Connection Issues

```
OSError: [Errno 111] Connection refused
```

**Solutions:**
1. Verify scheduler is running
2. Check firewall rules for scheduler port (default: 8786)
3. Ensure all workers can reach scheduler

## Comparison: Dask vs Other DataFrame Platforms

| Aspect | Dask (`dask-df`) | Pandas (`pandas-df`) |
|--------|-----------------|----------------------|
| Evaluation | Lazy | Eager |
| Memory | Out-of-core | In-memory |
| Distributed | Yes | No |
| Best for | Large/cluster | Small data |

## Dask vs PySpark

| Aspect | Dask | PySpark |
|--------|------|---------|
| API | Pandas-like | Spark DataFrame |
| Ecosystem | Python-native | JVM-based |
| Deployment | Python only | Requires Spark |
| Best for | Python workflows | Existing Spark infra |

## Related Documentation

- [DataFrame Platforms Overview](dataframe.md) - Architecture and concepts
- [Pandas DataFrame](pandas-dataframe.md) - Single-core Pandas
- [Migrating from Modin](modin-dataframe.md) - Replacement guidance
- [PySpark DataFrame](pyspark-dataframe.md) - Distributed Spark
- [cuDF Platform](cudf.md) - GPU-accelerated DataFrame
- [Getting Started](../usage/getting-started.md) - BenchBox quick start
