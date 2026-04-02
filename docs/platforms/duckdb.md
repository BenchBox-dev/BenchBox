<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# DuckDB Platform

```{tags} intermediate, guide, duckdb, embedded-platform
```

DuckDB is an in-process analytical database optimized for OLAP workloads. Install it via the `[duckdb]` extra and it is ready for local development, testing, and small-to-medium scale benchmarks.

## Features

- **Zero configuration** - No server setup required
- **In-process execution** - Embedded in Python process
- **Columnar vectorized** - Optimized for analytics
- **SQLite-compatible** - File-based persistence
- **Parallel execution** - Multi-threaded queries

## Why DuckDB is the Recommended Starting Point

DuckDB is available via the `[duckdb]` extra and recommended for most local workloads:

1. **No server setup** - Works with no external dependencies after install
2. **Native file format support** - Parquet and CSV support
3. **Local execution** - No network or service variability
4. **Free and open source** - No licensing costs
5. **Suitable for development** - Quick iteration on benchmark workflows

Choose the platform that best fits your specific requirements. See the [Platform Selection Guide](platform-selection-guide.md) for help selecting the right platform for your use case.

## Installation

```bash
# Install BenchBox with the DuckDB extra
uv add benchbox --extra duckdb

# Or with pip
pip install "benchbox[duckdb]"
```

## Configuration

### Default Usage

No configuration needed - DuckDB works immediately:

```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.01
```

### Persistent Database

By default, BenchBox uses in-memory databases. For persistence:

```bash
benchbox run --platform duckdb --benchmark tpch --scale 1.0 \
  --platform-option database=/path/to/benchmark.duckdb
```

### CLI Options

```bash
benchbox run --platform duckdb --benchmark tpch --scale 1.0 \
  --platform-option threads=8 \
  --platform-option memory_limit=4GB
```

## Platform Options

| Option | Default | Description |
|--------|---------|-------------|
| `database` | :memory: | Database path or :memory: |
| `threads` | (auto) | Number of threads |
| `memory_limit` | (auto) | Maximum memory usage |
| `temp_directory` | (auto) | Temp file location |
| `enable_progress_bar` | true | Show query progress |
| `driver_version` | (latest) | Pin the DuckDB Python package version (e.g. `1.2.0`) |
| `driver_auto_install` | false | Auto-install the requested driver version via uv if missing |

### Testing a Specific DuckDB Version

```bash
benchbox run --platform duckdb --benchmark tpch \
  --platform-option driver_version=1.4.3 \
  --platform-option driver_auto_install=true
```

See {ref}`driver-version-management` for the full guide, including why `uv run` may
revert a manually-installed version and how to work around it.

## Usage Examples

### Quick Start

```bash
# Minimal benchmark
benchbox run --platform duckdb --benchmark tpch --scale 0.01

# With specific queries
benchbox run --platform duckdb --benchmark tpch --scale 0.1 \
  --queries Q1,Q6,Q17
```

### Scale Factor Guide

| Scale Factor | Data Size | Use Case |
|--------------|-----------|----------|
| 0.01 | ~10 MB | Unit testing, CI/CD |
| 0.1 | ~100 MB | Integration testing |
| 1.0 | ~1 GB | Standard benchmarking |
| 10.0 | ~10 GB | Performance testing |

**Note:** Execution times vary based on hardware, query complexity, and configuration. Run benchmarks to establish baselines for your environment.

### With Tuning

```bash
# Apply optimizations (indexes, etc.)
benchbox run --platform duckdb --benchmark tpch --scale 1.0 \
  --tuning tuned
```

### Python API

```python
from benchbox import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter

# In-memory database
adapter = DuckDBAdapter()

# Or persistent
adapter = DuckDBAdapter(database="./benchmarks.duckdb")

benchmark = TPCH(scale_factor=0.1)
benchmark.generate_data()
adapter.load_benchmark(benchmark)
results = adapter.run_benchmark(benchmark)

print(f"Total runtime: {results.total_time:.2f}s")
```

### Comparison Across Scales

```python
from benchbox import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter

scales = [0.01, 0.1, 1.0]
for sf in scales:
    adapter = DuckDBAdapter()
    benchmark = TPCH(scale_factor=sf)
    benchmark.generate_data()
    adapter.load_benchmark(benchmark)
    results = adapter.run_benchmark(benchmark)
    print(f"SF {sf}: {results.total_time:.2f}s")
```

## Performance Features

### Thread Configuration

```bash
# Control parallelism
benchbox run --platform duckdb --benchmark tpch \
  --platform-option threads=4
```

### Memory Limits

```bash
# Limit memory usage
benchbox run --platform duckdb --benchmark tpch --scale 10.0 \
  --platform-option memory_limit=8GB
```

### Temporary Storage

For large datasets that exceed memory:

```bash
benchbox run --platform duckdb --benchmark tpch --scale 10.0 \
  --platform-option temp_directory=/fast/ssd/tmp
```

## Data Loading

DuckDB supports fast data loading from multiple formats:

### Default

```bash
# Data is generated as .tbl flat files (zstd-compressed by default) and loaded automatically
benchbox run --platform duckdb --benchmark tpch --scale 1.0
```

### Pre-generated Data

```bash
# Generate data separately, then run benchmark with pre-generated data
benchbox datagen --benchmark tpch --scale 1.0 --output ./data/tpch
benchbox run --platform duckdb --benchmark tpch --scale 1.0 --data-dir ./data/tpch
```

### Direct Query (No Load)

For testing queries without loading:

```python
import duckdb

conn = duckdb.connect()
# Query Parquet files directly
result = conn.execute("""
    SELECT count(*) FROM read_parquet('lineitem/*.parquet')
""").fetchone()
```

## Best Practices

### 1. Start Small

Begin with SF 0.01 to validate your workflow:

```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.01
```

### 2. Use In-Memory for Speed

For benchmarks, in-memory is fastest:

```bash
# Default - no database option needed
benchbox run --platform duckdb --benchmark tpch --scale 1.0
```

### 3. Persist for Development

When iterating on queries, persist the database:

```bash
# Load once
benchbox run --platform duckdb --benchmark tpch --scale 1.0 \
  --phases generate,load \
  --platform-option database=./dev.duckdb

# Run queries multiple times
benchbox run --platform duckdb --benchmark tpch --scale 1.0 \
  --phases power \
  --platform-option database=./dev.duckdb
```

### 4. Match Production Scale

Test at similar scale to production platforms:

```bash
# If planning to run SF 100 on Snowflake, test at SF 1-10 on DuckDB
benchbox run --platform duckdb --benchmark tpch --scale 10.0
```

## Troubleshooting

### Out of Memory

```bash
# Increase memory or use spilling
benchbox run --platform duckdb --benchmark tpch --scale 10.0 \
  --platform-option memory_limit=16GB \
  --platform-option temp_directory=/tmp/duckdb
```

### Slow Queries

```bash
# Check thread count
benchbox run --platform duckdb --benchmark tpch \
  --platform-option threads=$(nproc)

# Enable progress for visibility
benchbox run --platform duckdb --benchmark tpch \
  --platform-option enable_progress_bar=true
```

### Database Locked

```bash
# Only one connection allowed for write operations
# Close other DuckDB connections or use a new database path
benchbox run --platform duckdb --benchmark tpch \
  --platform-option database=./new_benchmark.duckdb
```

### Disk Space for Temp Files

```bash
# Check temp directory space
df -h /tmp

# Use different temp location
benchbox run --platform duckdb --benchmark tpch --scale 10.0 \
  --platform-option temp_directory=/data/tmp
```

## Comparison with Other Platforms

| Feature | DuckDB | SQLite | PostgreSQL |
|---------|--------|--------|------------|
| Setup | None | None | Server |
| Best for | OLAP | OLTP | General |
| Parallelism | Multi-thread | Single-thread | Multi-process |
| Memory | In-process | In-process | Separate |
| Scale | ~100 GB | ~10 GB | ~TB |

## Related Documentation

- [SQLite](sqlite.md) - Alternative embedded database
- [DataFusion](datafusion.md) - Rust-based alternative
- [Quick Start](../tutorials/first-benchmark.md) - Getting started tutorial
- [Platform Selection](platform-selection-guide.md)
