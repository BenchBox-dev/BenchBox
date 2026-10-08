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
pip install --extra-index-url=https://pypi.nvidia.com cudf-cu12

conda install -c rapidsai -c conda-forge -c nvidia \
    cudf=25.02 python=3.11 cuda-version=12.0
```

The first command installs cuDF for CUDA 12.x. Conda is the recommended alternative.

### Verify Installation

```bash
python -c "import cudf; print(f'cuDF {cudf.__version__}')"
```

## Quick Start

```bash
benchbox run --platform cudf-df --benchmark tpch --scale 0.1

benchbox run --platform cudf-df --benchmark tpch --scale 1 \
  --platform-option device_id=0

benchbox run --platform cudf-df --benchmark tpch --scale 10 \
  --platform-option spill_to_host=true
```

The commands run, in order: the default setup, a specific GPU device, and spilling to host memory for large datasets.

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `device_id` | 0 | GPU device ID to use |
| `spill_to_host` | false | Enable spilling to host memory when GPU memory is full |

### GPU Memory Management

cuDF uses RAPIDS Memory Manager (RMM) for GPU memory:

```python
import rmm

rmm.reinitialize(
    pool_allocator=True,
    initial_pool_size=8 * 1024**3,
)
```

Initialize the memory pool for better allocation performance. `initial_pool_size` is 8 GB here.

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

This is TPC-H Q1, the Pricing Summary Report, for cuDF. `lineitem` is a cuDF DataFrame.

```python
def q1_pandas_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")

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

## Known Limitations

### NULL and NaN in numeric columns (TPC-DS)

BenchBox has not run these TPC-DS queries on a GPU. The points below come from reading the BenchBox code and the cuDF documentation, not from a run.

pandas stores a missing number as `NaN`, and the SQL reference reports it as `NULL`. To match the reference, the TPC-DS pandas-family queries convert missing values to `None` by casting the column to `object` and masking the missing rows. cuDF handles missing numbers differently in two ways:

- **No separate NULL and NaN in checks.** cuDF marks a missing value with a null mask. Its `isna()` reports both a null and a floating-point `NaN` as missing, so BenchBox cannot tell a true `NULL` from a `NaN` that arithmetic produced (such as `0/0`) when it checks a numeric column.
- **`object` means text.** cuDF uses the `object` type only for strings and does not store arbitrary Python objects. Casting a numeric column to `object` is therefore not the same as in pandas, and the numbers may come back as text or as a different type.

The queries that apply this conversion to numeric result columns are Q12, Q20 and Q98 (item revenue and revenue ratio), Q66 (warehouse square footage and the per-square-foot columns), Q71 (`ext_price`) and Q76 (`sales_amt`). On cuDF, expect these queries to be the most likely to differ from the other platforms in how they report NULL or NaN, and in the type of those columns. Queries that convert only text columns (Q62, Q99 and Q21) are less exposed, because `object` already means text on cuDF. Check these results against a CPU platform before you rely on them. If you run them on a GPU, please report any difference.

## Python API

```python
from benchbox.platforms.dataframe import CuDFDataFrameAdapter

adapter = CuDFDataFrameAdapter(
    working_dir="./benchmark_data",
    device_id=0,
    spill_to_host=True
)

ctx = adapter.create_context()
adapter.load_tables(ctx, data_dir="./tpch_data")

from benchbox.core.tpch.dataframe_queries import TPCH_DATAFRAME_QUERIES
query = TPCH_DATAFRAME_QUERIES.get_query("Q1")
result = adapter.execute_query(ctx, query)
print(result)
```

## Troubleshooting

### CUDA Not Found

```bash
nvidia-smi
nvcc --version

export CUDA_HOME=/usr/local/cuda
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
```

Verify the CUDA installation, then set the CUDA path.

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
python -c "import cudf; print(cudf.__version__)"

python -c "import cudf; cudf.Series([1,2,3]).sum()"
```

The first command verifies the installation and the second checks CUDA compatibility with a basic test.

### Multi-GPU Setup

```bash
nvidia-smi -L

export CUDA_VISIBLE_DEVICES=0,1,2,3
```

Verify that all GPUs are visible, then set the visible devices. For multi-GPU, use Dask-cuDF rather than `cudf-df` directly.

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
