<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# DataFusion DataFrame Platform

```{tags} intermediate, guide, datafusion-df, dataframe-platform
```

DataFusion is an Apache Arrow-native query engine with a Rust backend and Python bindings. BenchBox supports benchmarking DataFusion using its native DataFrame API through the `datafusion-df` platform.

## Overview

| Attribute | Value |
|-----------|-------|
| CLI Name | `datafusion-df` |
| Family | Expression |
| Execution | Lazy |
| Best For | Medium to large datasets with complex analytical queries |
| Min Version | 40.0.0 |

## Features

- **Arrow-native** - Zero-copy data sharing with other Arrow tools
- **Lazy evaluation** - Query optimization before execution
- **Predicate pushdown** - Efficient Parquet filtering
- **Rust performance** - High-performance query execution
- **SQL support** - Hybrid DataFrame/SQL queries

## Installation

```bash
# Install DataFusion DataFrame support
uv add datafusion

# Or with pip
pip install datafusion

# Verify installation
python -c "import datafusion; print(f'DataFusion {datafusion.__version__}')"
```

## Quick Start

```bash
# Run TPC-H on DataFusion DataFrame
benchbox run --platform datafusion-df --benchmark tpch --scale 0.01

# With custom parallelism
benchbox run --platform datafusion-df --benchmark tpch --scale 1 \
  --platform-option target_partitions=8
```

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `target_partitions` | CPU count | Number of partitions for parallelism |
| `repartition_joins` | `true` | Enable automatic repartitioning for joins |
| `parquet_pushdown` | `true` | Enable predicate/projection pushdown for Parquet |
| `batch_size` | `8192` | Batch size for query execution |
| `memory_limit` | None | Memory limit for fair spill pool (e.g., '8G', '16GB') |
| `temp_dir` | System temp | Temporary directory for disk spilling |

### target_partitions

Controls parallelism by setting the number of partitions for query execution:

```bash
# Use 4 partitions (for limited memory)
benchbox run --platform datafusion-df --benchmark tpch --scale 1 \
  --platform-option target_partitions=4

# Use all available CPUs (default)
benchbox run --platform datafusion-df --benchmark tpch --scale 10
```

### parquet_pushdown

DataFusion can push predicates and projections down to the Parquet reader:

```bash
# Disable pushdown for debugging
benchbox run --platform datafusion-df --benchmark tpch --scale 1 \
  --platform-option parquet_pushdown=false
```

## Scale Factor Guidelines

DataFusion uses lazy evaluation and can handle larger datasets than eager frameworks:

| Scale Factor | Data Size | Memory Required | Use Case |
|--------------|-----------|-----------------|----------|
| 0.01 | ~10 MB | ~200 MB | Unit testing, CI/CD |
| 0.1 | ~100 MB | ~500 MB | Integration testing |
| 1.0 | ~1 GB | ~2 GB | Standard benchmarking |
| 10.0 | ~10 GB | ~8 GB | Performance testing |
| 100.0 | ~100 GB | ~32 GB | Large-scale testing |

**Note:** Execution times vary based on query complexity, hardware, and configuration. Run benchmarks to establish baselines for your environment.

## Performance Characteristics

### Strengths

- **Query optimization** - Lazy evaluation enables automatic optimization
- **Memory efficiency** - Streaming execution reduces memory pressure
- **Parquet performance** - Native Parquet support with pushdown
- **Arrow integration** - Zero-copy interop with PyArrow ecosystem

### Limitations

- **Single-node** - No distributed execution (unlike Spark)
- **Python overhead** - Some overhead in Python bindings
- **Smaller community** - Less documentation than Pandas/Polars

### Performance Tips

1. **Enable parallelism** for large datasets:
   ```bash
   --platform-option target_partitions=16
   ```

2. **Use Parquet format** for best performance:
   ```bash
   benchbox run --platform datafusion-df --benchmark tpch --scale 10
   ```

3. **Compare with Polars** for single-node workloads:
   ```bash
   --platform polars-df  # Alternative single-node DataFrame implementation
   ```

## Query Implementation

DataFusion queries use expression-based operations:

```python
# TPC-H Q1: Pricing Summary Report
def q1_datafusion_impl(ctx: DataFrameContext) -> Any:
    lineitem = ctx.get_table("lineitem")

    # Filter using expression API
    cutoff = ctx.cast_date(ctx.lit("1998-09-02"))
    filtered = lineitem.filter(ctx.col("l_shipdate") <= cutoff)

    # Compute derived columns
    disc_price = ctx.col("l_extendedprice") * (ctx.lit(1) - ctx.col("l_discount"))
    charge = disc_price * (ctx.lit(1) + ctx.col("l_tax"))

    # Aggregate with window functions
    result = (
        filtered
        .aggregate(
            [ctx.col("l_returnflag"), ctx.col("l_linestatus")],
            [
                f.sum(ctx.col("l_quantity")).alias("sum_qty"),
                f.avg(ctx.col("l_quantity")).alias("avg_qty"),
                f.sum(disc_price).alias("sum_disc_price"),
                f.sum(charge).alias("sum_charge"),
            ]
        )
        .sort(ctx.col("l_returnflag").sort(ascending=True))
    )

    return result
```

## Comparison: DataFusion vs Polars DataFrame

| Aspect | DataFusion (`datafusion-df`) | Polars (`polars-df`) |
|--------|----------------------------|---------------------|
| Backend | Rust (via Arrow) | Rust |
| Execution | Lazy | Lazy |
| Memory | Efficient | Very efficient |
| Speed | Sub-second queries | Sub-100ms queries |
| SQL Support | Full SQL engine | Basic SQL |
| Best for | SQL + DataFrame hybrid | Pure DataFrame |

## Window Functions

DataFusion supports SQL-style window functions:

```python
from benchbox.platforms.dataframe import DataFusionDataFrameAdapter

adapter = DataFusionDataFrameAdapter()

# Create window expressions
row_num = adapter.window_row_number(
    order_by=[("sale_date", True)],
    partition_by=["category"]
)

running_total = adapter.window_sum(
    column="amount",
    partition_by=["category"],
    order_by=[("sale_date", True)]
)
```

## Troubleshooting

### Memory Issues

```
DataFusion error: Memory exhausted
```

**Solutions:**
1. Set a memory limit with spilling: `--platform-option memory_limit=8G`
2. Reduce partitions: `--platform-option target_partitions=4`
3. Reduce batch size: `--platform-option batch_size=4096`
4. Set a temp directory for spilling: `--platform-option temp_dir=/tmp/datafusion`
5. Reduce scale factor: `--scale 1`

### Slow Parquet Reads

If Parquet file reads are slow:

```bash
# Ensure pushdown is enabled (default)
--platform-option parquet_pushdown=true
```

### Type Errors

DataFusion is strict about types. Ensure date columns are properly cast:

```python
# Cast string to date
date_col = adapter.cast_date(adapter.col("date_string"))
```

## Python API

```python
from benchbox.platforms.dataframe import DataFusionDataFrameAdapter

# Create adapter with custom configuration
adapter = DataFusionDataFrameAdapter(
    working_dir="./benchmark_data",
    target_partitions=8,
    repartition_joins=True,
    parquet_pushdown=True,
    batch_size=8192,
    memory_limit="8G",  # Enable memory management with spilling
    temp_dir="/tmp/datafusion"  # Directory for spilled data
)

# Create context and load tables
ctx = adapter.create_context()
adapter.load_tables(ctx, data_dir="./tpch_data")

# Execute SQL query directly
df = adapter.sql("SELECT * FROM lineitem WHERE l_quantity > 10")
result = adapter.collect(df)

# Execute DataFrame query
from benchbox.core.tpch.dataframe_queries import TPCH_DATAFRAME_QUERIES
query = TPCH_DATAFRAME_QUERIES.get_query("Q1")
result = adapter.execute_query(ctx, query)
print(result)
```

## Related Documentation

- [DataFusion SQL Platform](datafusion.md) - DataFusion SQL mode
- [Polars Platform](polars.md) - Alternative expression-family adapter
- [Pandas DataFrame Platform](pandas-dataframe.md) - Pandas-family adapter
- [Getting Started](../usage/getting-started.md) - BenchBox quick start
