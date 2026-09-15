<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# cuDF DataFrame Platform

```{tags} advanced, guide, cudf, dataframe-platform, performance
```

cuDF is NVIDIA's GPU-accelerated DataFrame library, part of the RAPIDS ecosystem. BenchBox supports benchmarking cuDF using its native Pandas-compatible API through the `cudf-df` platform.

## Overview

| Attribute | Value |
|-----------|-------|
| CLI Name | `cudf-df` |
| Family | Pandas |
| Execution | Eager (GPU) |
| Best For | Large datasets with GPU acceleration |
| Min Version | 25.02.0 |

## Features

- **GPU acceleration** - Use NVIDIA GPU compute for analytics
- **Pandas-compatible API** - Familiar DataFrame interface
- **Multi-GPU support** - Scale across multiple GPUs with Dask-cuDF
- **Zero-copy operations** - Efficient GPU memory management via RMM
- **Full TPC-H support** - All 22 queries implemented via Pandas family

## Requirements

- **NVIDIA GPU** - CUDA-capable GPU (Pascal or newer recommended)
- **CUDA Toolkit** - CUDA 12.x
- **Linux** - Currently Linux-only support
- **GPU Memory** - Sufficient VRAM for your dataset

## Installation

cuDF is not available on standard PyPI. Install via NVIDIA's pip index:

```bash
# Install cuDF for CUDA 12.x
pip install --extra-index-url=https://pypi.nvidia.com cudf-cu12

# Or use conda (recommended)
conda install -c rapidsai -c conda-forge -c nvidia \
    cudf=25.02 python=3.11 cuda-version=12.0
```

### Verify Installation

```bash
python -c "import cudf; print(f'cuDF {cudf.__version__}')"
```

## Quick Start

```bash
# Run TPC-H on cuDF DataFrame platform
benchbox run --platform cudf-df --benchmark tpch --scale 0.1

# Specify GPU device
benchbox run --platform cudf-df --benchmark tpch --scale 1 \
  --platform-option device_id=0

# Enable spill to host memory for large datasets
benchbox run --platform cudf-df --benchmark tpch --scale 10 \
  --platform-option spill_to_host=true
```

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `device_id` | 0 | GPU device ID to use |
| `spill_to_host` | false | Enable spilling to host memory when GPU memory is full |

### GPU Memory Management

cuDF uses RAPIDS Memory Manager (RMM) for GPU memory:

```python
import rmm

# Initialize memory pool for better allocation performance
rmm.reinitialize(
    pool_allocator=True,
    initial_pool_size=8 * 1024**3,  # 8 GB
)
```

## Scale Factor Guidelines

GPU memory limits dataset size. Guidelines for common GPUs:

| GPU | VRAM | Max Scale Factor | Notes |
|-----|------|------------------|-------|
| RTX 3080 | 10 GB | ~1.0 | Consumer GPU |
| RTX 3090/4090 | 24 GB | ~3.0 | High-end consumer |
| A100 40GB | 40 GB | ~5.0 | Data center |
| A100 80GB | 80 GB | ~10.0 | Data center |
| H100 | 80 GB | ~10.0 | Latest generation |

**With spill_to_host=true**, you can process larger datasets at the cost of performance.

## Performance Characteristics

### Strengths

- **Massive parallelism** - Thousands of GPU cores for data processing
- **High memory bandwidth** - GPU memory provides higher bandwidth than system memory <!-- content-ok: cliche -->
- **Vectorized operations** - SIMD-like execution across GPU threads
- **Zero-copy integration** - Efficient data sharing with other RAPIDS libraries

### Considerations

- **Data transfer overhead** - CPU-GPU transfer can be a bottleneck
- **Memory limited** - Must fit in GPU memory (or use spill_to_host)
- **Linux only** - No Windows/macOS support currently
- **Installation complexity** - Requires CUDA and NVIDIA drivers

### Performance Considerations

GPU acceleration can provide significant performance benefits for specific operations on large datasets. Benefits vary based on:

- GPU model and compute capability
- Data transfer overhead between CPU and GPU memory
- Operation complexity and data types
- Dataset size (larger datasets benefit more from parallelization)

Not all operations benefit equally from GPU acceleration. Run benchmarks with your actual workloads to evaluate performance for your use case.

## Query Implementation

cuDF queries use Pandas-compatible API:

```python
# TPC-H Q1: Pricing Summary Report (cuDF)
def q1_pandas_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")  # cuDF DataFrame

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
from benchbox.platforms.dataframe import CuDFDataFrameAdapter

# Create adapter with custom configuration
adapter = CuDFDataFrameAdapter(
    working_dir="./benchmark_data",
    device_id=0,
    spill_to_host=True
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

### CUDA Not Found

```bash
# Verify CUDA installation
nvidia-smi
nvcc --version

# Set CUDA path
export CUDA_HOME=/usr/local/cuda
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
```

### Out of GPU Memory

```
cudf.errors.MemoryError: std::bad_alloc: out of memory
```

**Solutions:**
1. Reduce scale factor: `--scale 0.1`
2. Enable spill to host: `--platform-option spill_to_host=true`
3. Use RMM memory pool (pre-allocated pool reduces fragmentation)

### cuDF Import Error

```bash
# Verify installation
python -c "import cudf; print(cudf.__version__)"

# Check CUDA compatibility
python -c "import cudf; cudf.Series([1,2,3]).sum()"  # Basic test
```

### Multi-GPU Setup

```bash
# Verify all GPUs visible
nvidia-smi -L

# Set visible devices
export CUDA_VISIBLE_DEVICES=0,1,2,3

# For multi-GPU, use Dask-cuDF (not cudf-df directly)
```

## Comparison: cuDF vs Other DataFrame Platforms

| Aspect | cuDF (`cudf-df`) | Pandas (`pandas-df`) | Polars (`polars-df`) |
|--------|------------------|----------------------|----------------------|
| Hardware | NVIDIA GPU | CPU | CPU |
| Execution | GPU-accelerated | Single-threaded | Multi-threaded |
| Memory | GPU VRAM | System RAM | System RAM |
| Platform | Linux only | Cross-platform | Cross-platform |
| Installation | Complex | Simple | Simple |

## Related Documentation

- [DataFrame Platforms Overview](dataframe.md) - Architecture and concepts
- [Pandas DataFrame](pandas-dataframe.md) - CPU-based Pandas
- [Polars Platform](polars.md) - Fast CPU DataFrame
- [Dask DataFrame](dask-dataframe.md) - Distributed Pandas
- [Getting Started](../usage/getting-started.md) - BenchBox quick start
