<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Apache DataFusion Platform Guide

```{tags} intermediate, guide, datafusion, sql-platform
```

Apache DataFusion is a fast, embeddable query engine for building high-quality data-centric systems in Rust, Python, and other languages. BenchBox's DataFusion adapter enables in-memory OLAP benchmarking with support for both CSV and Parquet formats.

## Overview

**Type**: In-memory Query Engine
**Common Use Cases**: In-process analytics, rapid prototyping, OLAP workload testing
**Installation**: `pip install datafusion`

### Key Features

- **In-memory execution**: Fast analytical queries without persistent database overhead
- **PostgreSQL-compatible SQL**: Uses PostgreSQL dialect for broad compatibility
- **Dual format support**: Native CSV loading or high-performance Parquet conversion
- **Automatic optimization**: Query optimization, predicate pushdown, and partition pruning
- **Python-native**: Direct integration with Python data ecosystem (PyArrow, Pandas)
- **Configurable parallelism**: Multi-threaded execution with tunable partition count

## Quick Start

### Installation

Install DataFusion support:

```bash
pip install datafusion
```

Or with BenchBox:

```bash
uv add benchbox datafusion
```

**Version Compatibility**: BenchBox supports DataFusion 0.x through latest versions. The adapter automatically handles API differences between versions:
- **Older versions**: Uses `RuntimeEnv` class
- **Newer versions**: Uses `RuntimeEnvBuilder` class
- **Recommendation**: Install latest version with `pip install datafusion` for best performance and features

### Basic Usage

```python
from benchbox.platforms.datafusion import DataFusionAdapter
from benchbox import TPCH

# Create adapter with default settings
adapter = DataFusionAdapter(
    working_dir="./datafusion_working",
    memory_limit="16G",
    data_format="parquet"  # Columnar format with compression and predicate pushdown
)

# Run TPC-H benchmark
benchmark = TPCH(scale_factor=1.0)
results = benchmark.run_with_platform(adapter)

print(f"Completed in {results.duration_seconds:.2f}s")
print(f"Average query time: {results.average_query_time:.3f}s")
```

### CLI Usage

```bash
# Run TPC-H benchmark with DataFusion
benchbox run --platform datafusion --benchmark tpch --scale 1.0 \
  --datafusion-memory-limit 16G \
  --datafusion-format parquet \
  --datafusion-partitions 8

# Use CSV format (direct loading, lower memory)
benchbox run --platform datafusion --benchmark tpch --scale 1.0 \
  --datafusion-format csv

# Specify custom working directory
benchbox run --platform datafusion --benchmark tpch --scale 1.0 \
  --datafusion-working-dir /fast/ssd/datafusion
```

## Configuration

### Constructor Parameters

```python
DataFusionAdapter(
    working_dir: str = "./datafusion_working",
    memory_limit: str = "16G",
    target_partitions: int = None,  # Defaults to CPU count
    data_format: str = "parquet",   # "parquet" or "csv"
    temp_dir: str = None,           # For disk spilling
    batch_size: int = 8192,         # RecordBatch size
    force_recreate: bool = False,   # Force rebuild existing data
)
```

### CLI Arguments

| CLI Argument | Python Parameter | Type | Default | Description |
|--------------|------------------|------|---------|-------------|
| `--datafusion-memory-limit` | `memory_limit` | str | "16G" | Memory limit (e.g., '16G', '8GB', '4096MB') |
| `--datafusion-partitions` | `target_partitions` | int | CPU count | Number of parallel partitions |
| `--datafusion-format` | `data_format` | str | "parquet" | Data format: "csv" or "parquet" |
| `--datafusion-temp-dir` | `temp_dir` | str | None | Temporary directory for disk spilling |
| `--datafusion-batch-size` | `batch_size` | int | 8192 | RecordBatch size for query execution |
| `--datafusion-working-dir` | `working_dir` | str | Auto | Working directory for tables and data |

### Testing a Specific DataFusion Version

The universal `driver_version` and `driver_auto_install` options are available via `--platform-option`:

```bash
benchbox run --platform datafusion --benchmark tpch \
  --platform-option driver_version=50.1.0 \
  --platform-option driver_auto_install=true
```

The driver package for DataFusion is `datafusion`.

See {ref}`driver-version-management` for the full guide, including why `uv run` may
revert a manually-installed version and how to work around it.

### Performance Tuning

#### Memory Configuration

```python
# Conservative memory limit for constrained environments
adapter = DataFusionAdapter(memory_limit="4G")

# Aggressive memory allocation for large-scale benchmarks
adapter = DataFusionAdapter(memory_limit="64G")

# Memory limit with disk spilling
adapter = DataFusionAdapter(
    memory_limit="16G",
    temp_dir="/fast/nvme/temp"  # Fast SSD for spilling
)
```

#### Parallelism Configuration

```python
# Match CPU core count (default)
import os
adapter = DataFusionAdapter(target_partitions=os.cpu_count())

# Conservative for multi-tenant systems
adapter = DataFusionAdapter(target_partitions=4)

# Aggressive for dedicated benchmark server
adapter = DataFusionAdapter(target_partitions=32)
```

#### Batch Size Tuning

The `batch_size` parameter controls RecordBatch size for query execution:

```python
# Default (recommended for most workloads)
adapter = DataFusionAdapter(batch_size=8192)

# Smaller batches: Lower latency, lower memory
adapter = DataFusionAdapter(
    batch_size=4096,
    memory_limit="4G"
)
# Use when: Memory-constrained, interactive queries, lower latency required

# Larger batches: Higher throughput, higher memory
adapter = DataFusionAdapter(
    batch_size=16384,
    memory_limit="32G"
)
# Use when: Batch processing, maximum throughput, ample memory available
```

**Batch Size Guidelines**:
- **4096**: Best for interactive queries and memory-constrained environments
- **8192** (default): Good balance for most analytical workloads
- **16384**: Optimal for high-throughput batch processing with sufficient RAM
- **Trade-off**: Larger batches = higher memory usage but better vectorized execution

#### Data Format Selection

**Parquet Format (Recommended)**:
- Better query performance due to columnar format
- Automatic columnar compression
- Predicate pushdown optimization
- Higher memory usage during conversion

```python
adapter = DataFusionAdapter(
    data_format="parquet",
    working_dir="/fast/ssd/datafusion"  # Fast storage for conversion
)
```

**CSV Format**:
- Direct loading (no conversion step)
- Lower memory footprint
- Slower query execution
- Good for memory-constrained environments

```python
adapter = DataFusionAdapter(
    data_format="csv",
    memory_limit="4G"  # Lower memory requirements
)
```

#### Configuration from Unified Config

For programmatic configuration, use BenchBox's unified config pattern:

```python
from benchbox.platforms.datafusion import DataFusionAdapter

config = {
    "benchmark": "tpch",
    "scale_factor": 10.0,
    "memory_limit": "32G",
    "partitions": 16,
    "format": "parquet",
    "batch_size": 16384
}

adapter = DataFusionAdapter.from_config(config)
```

The `from_config()` method automatically generates appropriate working directory paths based on benchmark name and scale factor.

## Data Loading

DataFusion supports two data loading strategies:

### CSV Mode (Direct Loading)

Directly registers CSV files as external tables without conversion:

```python
adapter = DataFusionAdapter(data_format="csv")
```

**Characteristics**:
- Fast initial load
- Lower memory usage
- Slower query performance
- Handles TPC format (pipe-delimited with trailing delimiter)

### Parquet Mode (Conversion)

Converts CSV to Parquet format first, then registers Parquet tables:

```python
adapter = DataFusionAdapter(data_format="parquet")
```

**Characteristics**:
- One-time conversion overhead
- Better query performance due to columnar format
- Higher initial memory usage
- Automatic columnar compression
- Optimized for repeated query execution

**Format Comparison**:

| Aspect | CSV Mode | Parquet Mode |
|--------|----------|--------------|
| Initial Load | Faster (streaming) | Slower (conversion required) |
| Query Execution | Row-by-row parsing | Columnar with pushdown |
| Memory Usage | Lower | Higher |
| Disk Storage | N/A (external) | Compressed (~50-80% of CSV) |
| Best For | Quick testing | Repeated query execution |

Parquet format provides better query performance due to columnar compression and predicate pushdown optimization. The magnitude of improvement varies depending on query characteristics, data selectivity, and hardware. Run benchmarks to measure performance for your specific environment.

## Benchmark Support

### TPC-H

Full support for all TPC-H queries at all scale factors:

```python
from benchbox import TPCH

benchmark = TPCH(scale_factor=10.0)
adapter = DataFusionAdapter(
    memory_limit="32G",
    data_format="parquet"
)

results = benchmark.run_with_platform(adapter)
```

**Recommended Configuration**:
- Scale Factor 0.1-1: 8G memory, 4-8 partitions
- Scale Factor 1-10: 16G memory, 8-16 partitions
- Scale Factor 10+: 32G+ memory, 16+ partitions

### TPC-DS

Good support for most TPC-DS queries (some complex queries may fail due to SQL feature limitations):

```python
from benchbox import TPCDS

benchmark = TPCDS(scale_factor=1.0)
adapter = DataFusionAdapter(
    memory_limit="32G",
    data_format="parquet",
    target_partitions=16
)

results = benchmark.run_with_platform(adapter)
```

**Known Limitations**:
- Some window function edge cases
- Complex correlated subqueries
- Advanced SQL features (platform will validate before execution)

### Other Benchmarks

DataFusion supports:
- **SSB (Star Schema Benchmark)**: Full support
- **ClickBench**: Full support
- **H2ODB**: Full support
- **AMPLab**: Full support
- **Custom benchmarks**: PostgreSQL-compatible SQL

## Advanced Features

### Manual Connection Management

For advanced use cases requiring connection reuse or custom query execution:

```python
from benchbox.platforms.datafusion import DataFusionAdapter

# Create adapter
adapter = DataFusionAdapter(
    memory_limit="16G",
    data_format="parquet"
)

# Create and manage connection manually
connection = adapter.create_connection()

# Execute multiple custom queries on same connection
query1 = "SELECT COUNT(*) FROM lineitem WHERE l_shipdate > '1995-01-01'"
result1 = connection.sql(query1).collect()

query2 = "SELECT AVG(l_extendedprice) FROM lineitem"
result2 = connection.sql(query2).collect()

# Connection is automatically cleaned up when adapter is garbage collected
# or you can explicitly close if needed
```

**When to use manual connection management**:
- Executing multiple custom queries without benchmark overhead
- Testing individual queries during development
- Building custom benchmark workflows
- Integrating with existing DataFusion SessionContext

**Note**: `benchmark.run_with_platform(adapter)` handles connection lifecycle automatically and is recommended for most use cases.

### Query Execution Options

```python
# Execute with row count validation
result = adapter.execute_query(
    connection,
    query="SELECT * FROM lineitem WHERE l_shipdate > '1995-01-01'",
    query_id="custom_query_1",
    benchmark_type="tpch",
    scale_factor=1.0,
    validate_row_count=True
)

print(f"Query completed in {result['execution_time']:.3f}s")
print(f"Returned {result['rows_returned']} rows")
```

### Dry-Run Mode

Preview queries without executing them:

```python
adapter = DataFusionAdapter(dry_run_mode=True)

# Queries will be validated but not executed
results = benchmark.run_with_platform(adapter)
# Check generated SQL in results
```

### Platform Validation

```python
# Validate platform capabilities before running
validation = adapter.validate_platform_capabilities("tpch")

if validation.is_valid:
    print("Platform ready for benchmarking")
else:
    print("Validation errors:", validation.errors)
    print("Warnings:", validation.warnings)
```

## Performance Optimization

### Best Practices

1. **Use Parquet format** for repeated query execution:
   ```python
   adapter = DataFusionAdapter(data_format="parquet")
   ```

2. **Set appropriate memory limits** to prevent OOM:
   ```python
   adapter = DataFusionAdapter(memory_limit="16G")
   ```

3. **Match partitions to CPU cores**:
   ```python
   import os
   adapter = DataFusionAdapter(target_partitions=os.cpu_count())
   ```

4. **Use fast storage** for working directory:
   ```python
   adapter = DataFusionAdapter(working_dir="/fast/nvme/datafusion")
   ```

5. **Enable query optimization** (automatic):
   - Predicate pushdown
   - Partition pruning
   - Join reordering
   - Aggregate pushdown

### Performance Tuning by Scale Factor

**Small Scale (SF < 1)**:
```python
adapter = DataFusionAdapter(
    memory_limit="4G",
    target_partitions=4,
    data_format="csv"  # CSV is fine for small datasets
)
```

**Medium Scale (SF 1-10)**:
```python
adapter = DataFusionAdapter(
    memory_limit="16G",
    target_partitions=8,
    data_format="parquet"
)
```

**Large Scale (SF 10+)**:
```python
adapter = DataFusionAdapter(
    memory_limit="64G",
    target_partitions=16,
    data_format="parquet",
    temp_dir="/fast/ssd/temp",
    batch_size=16384
)
```

## Comparison with Other Platforms

### DataFusion vs DuckDB

| Feature | DataFusion | DuckDB |
|---------|-----------|--------|
| Architecture | Python bindings to Rust engine | Embedded C++ database |
| Query Performance | Excellent | Excellent |
| Data Format | In-memory tables | Persistent/in-memory |
| Python Integration | PyArrow native | Python API |
| Maturity | Growing | Mature |
| SQL Compatibility | PostgreSQL | PostgreSQL-like |
| Persistence | None (working directory only) | Native database files |

**When to use DataFusion**:
- Testing Rust-based query engine
- PyArrow-centric workflows
- In-memory analytics only
- Rapid prototyping

**When to use DuckDB**:
- Production analytics workloads
- Persistent database required
- Mature feature set needed
- File-based workflows

### DataFusion vs ClickHouse

| Feature | DataFusion | ClickHouse |
|---------|-----------|------------|
| Deployment | Embedded | Client-server |
| Scale | Single-node in-memory | Distributed clusters |
| Setup Complexity | Minimal | Moderate |
| Query Performance | Excellent (small-medium) | Excellent (all scales) |
| Operational Overhead | None | Moderate-high |

## Troubleshooting

### Common Issues

#### Out of Memory Errors

**Problem**: Query fails with OOM error

**Solution**:
```python
# Reduce memory limit or use CSV format
adapter = DataFusionAdapter(
    memory_limit="8G",
    data_format="csv",  # Lower memory footprint
    temp_dir="/large/disk/temp"
)
```

#### Slow CSV Loading

**Problem**: CSV loading takes too long

**Solution**:
```python
# Use Parquet format for better query performance
adapter = DataFusionAdapter(
    data_format="parquet",
    working_dir="/fast/ssd/datafusion"  # Use fast storage
)
```

#### Query Failures

**Problem**: Some queries fail with SQL errors

**Solution**:
```python
# Validate platform capabilities first
validation = adapter.validate_platform_capabilities("tpcds")
if validation.warnings:
    print("Platform warnings:", validation.warnings)

# Check query compatibility with PostgreSQL dialect
```

#### Mixed-Case Column Names

**Problem**: Queries fail with `Schema error: No field named <lowercase_column>` even though the column exists in the table.

**Root cause**: DataFusion lowercases all unquoted SQL identifiers at parse time (e.g. `AdvEngineID` in a query becomes `advengineid`). If the underlying parquet file or schema retains the original mixed-case column names, every column lookup fails.

**How BenchBox handles it**: The DataFusion adapter automatically lowercases all column names across every data-loading path - CSV-to-Parquet conversion (`_convert_and_register_parquet`), pre-existing Parquet files (`_register_parquet_files`), Delta Lake tables (`_load_table_delta`), Iceberg tables (`_load_table_iceberg`), and empty schema tables (`_create_empty_schema_tables`). Benchmarks whose SQL schemas define mixed-case column names - such as ClickBench (`WatchID`, `AdvEngineID`, etc.) and AMPLab (`pageURL`, `pageRank`, `sourceIP`, etc.) - are transparently normalized so that DataFusion's identifier lowercasing and the stored schema always agree.

**Important**: All BenchBox SQL queries targeting DataFusion must use unquoted identifiers. DataFusion does support quoted case-sensitive identifiers (e.g. `SELECT "AdvEngineID" FROM hits`), but the adapter normalizes stored column names to lowercase, so quoted mixed-case lookups will fail at query time.

#### Trailing Delimiter Issues

**Problem**: TPC files with trailing pipe delimiters cause extra columns

**Solution**: The adapter automatically handles trailing delimiters in TPC format files. No action needed.

## Limitations

DataFusion has some limitations compared to full database systems:

1. **No persistence**: Data is session-scoped (working directory contains Parquet conversions only)
2. **No transactions**: ACID properties not enforced
3. **No constraints**: PRIMARY KEY and FOREIGN KEY are informational only
4. **SQL feature gaps**: Some advanced SQL features may not be supported
5. **Single-node**: No distributed query execution

## See Also

### Platform Documentation
- [Platform Selection Guide](platform-selection-guide.md) - Choosing the right platform
- [Quick Reference](quick-reference.md) - Multi-platform quick start
- [Comparison Matrix](comparison-matrix.md) - Detailed platform comparison
- [DuckDB Platform Guide](../reference/python-api/platforms/duckdb.rst) - Similar in-process analytics

### API Reference
- [DataFusion Adapter API](../reference/python-api/platforms/datafusion.rst) - Complete API documentation
- [Platform Base API](../reference/python-api/platforms.rst) - Platform adapter interface

### Benchmark Guides
- [TPC-H Benchmark](../benchmarks/tpc-h.md) - TPC-H on DataFusion
- [TPC-DS Benchmark](../benchmarks/tpc-ds.md) - TPC-DS on DataFusion
- [Benchmark Catalog](../benchmarks/index.md) - All available benchmarks

### External Resources
- [Apache DataFusion Documentation](https://datafusion.apache.org/) - Official DataFusion docs
- [DataFusion Python Bindings](https://datafusion.apache.org/python/) - Python API reference
- [Apache Arrow](https://arrow.apache.org/) - Arrow columnar format
