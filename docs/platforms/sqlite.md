<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# SQLite Platform

```{tags} intermediate, guide, sqlite, embedded-platform
```

SQLite is the most widely deployed database engine in the world. While optimized for OLTP workloads, BenchBox supports SQLite for comparison benchmarks and scenarios where simplicity is paramount.

## Features

- **Zero configuration** - No server required
- **Single file** - Complete database in one file
- **Cross-platform** - Works everywhere
- **ACID compliant** - Full transaction support
- **Battle-tested** - Decades of production use

## Use Cases

SQLite is useful in BenchBox for:

1. **Baseline comparisons** - Compare OLAP platforms against OLTP baseline
2. **CI/CD testing** - Fast, isolated test environments
3. **Educational** - Learn SQL benchmarking concepts
4. **Embedded scenarios** - Test mobile/edge database performance

## Installation

```bash
# SQLite is included with Python
uv add benchbox

# Or with pip
pip install benchbox
```

## Configuration

### Default Usage

```bash
benchbox run --platform sqlite --benchmark tpch --scale 0.01
```

### Persistent Database

```bash
benchbox run --platform sqlite --benchmark tpch --scale 0.1 \
  --platform-option database=/path/to/benchmark.db
```

### CLI Options

```bash
benchbox run --platform sqlite --benchmark tpch --scale 0.1 \
  --platform-option database=./benchmark.db \
  --platform-option journal_mode=WAL \
  --platform-option cache_size=-64000
```

## Platform Options

| Option | Default | Description |
|--------|---------|-------------|
| `database` | :memory: | Database path or :memory: |
| `journal_mode` | WAL | WAL, DELETE, TRUNCATE, etc. |
| `cache_size` | -2000 | Page cache size (negative = KB) |
| `synchronous` | NORMAL | OFF, NORMAL, FULL |
| `temp_store` | MEMORY | DEFAULT, FILE, MEMORY |

## Usage Examples

### Quick Start

```bash
# Small benchmark
benchbox run --platform sqlite --benchmark tpch --scale 0.01
```

### With Optimizations

```bash
# Optimized for read performance
benchbox run --platform sqlite --benchmark tpch --scale 0.1 \
  --platform-option journal_mode=WAL \
  --platform-option cache_size=-64000 \
  --platform-option synchronous=NORMAL
```

### Python API

```python
from benchbox import TPCH
from benchbox.platforms.sqlite import SQLiteAdapter

adapter = SQLiteAdapter(
    database="./benchmark.db",
    journal_mode="WAL",
    cache_size=-64000,
)

benchmark = TPCH(scale_factor=0.01)
benchmark.generate_data()
adapter.load_benchmark(benchmark)
results = adapter.run_benchmark(benchmark)
```

## Performance Tuning

### TPC-H Helper Indexes

BenchBox creates a small set of SQLite-specific helper indexes after loading
TPC-H data. These indexes target the order, supplier, nation, and lineitem
access paths used by correlated queries such as Q21, which otherwise require
repeated full scans in SQLite and can dominate local smoke runs even at SF 0.01.

The helper indexes are applied after bulk load so they do not slow row ingestion,
and they preserve query results and status classification. Generated `.tbl` data
is still reusable across TPC-H-derived workloads; only loaded SQLite database
files need cleanup when disk space is constrained.

### WAL Mode

Write-Ahead Logging improves read performance:

```bash
benchbox run --platform sqlite --benchmark tpch \
  --platform-option journal_mode=WAL
```

### Cache Size

Increase cache to reduce disk I/O:

```bash
# 64 MB cache
benchbox run --platform sqlite --benchmark tpch \
  --platform-option cache_size=-64000
```

### Memory-Mapped I/O

For large databases:

```bash
benchbox run --platform sqlite --benchmark tpch \
  --platform-option mmap_size=268435456  # 256 MB
```

## Limitations

SQLite has characteristics that affect OLAP benchmarks:

1. **Single-threaded writes** - Only one writer at a time
2. **Row-based storage** - Not optimized for analytical scans
3. **Limited parallelism** - Sequential query execution
4. **Memory constraints** - In-memory limited by process memory

### Recommended Scale Factors

| Scale Factor | Expected Performance |
|--------------|---------------------|
| 0.01 | Fast for smoke; Q21 is sensitive to missing helper indexes |
| 0.1 | Moderate (minutes) |
| 1.0 | Slow (10+ minutes) |
| 10.0+ | Not recommended |

## Comparison with DuckDB

SQLite and DuckDB are optimized for different workload types:

| Aspect | SQLite | DuckDB |
|--------|--------|--------|
| Optimized For | OLTP (transactional) | OLAP (analytical) |
| Storage | Row-based | Columnar |
| Parallelism | Single-thread | Multi-thread |

**Note:** Performance differences vary based on query characteristics, data size, and hardware. Run benchmarks with your specific workloads to compare.

```bash
# Compare performance
benchbox run --platform sqlite --benchmark tpch --scale 0.1
benchbox run --platform duckdb --benchmark tpch --scale 0.1
```

## Troubleshooting

### Database Locked

```bash
# Wait for lock
benchbox run --platform sqlite --benchmark tpch \
  --platform-option busy_timeout=30000  # 30 seconds
```

### Out of Memory

```bash
# Use file-based temp storage
benchbox run --platform sqlite --benchmark tpch \
  --platform-option temp_store=FILE
```

### Slow Queries

```bash
# Increase cache and use WAL
benchbox run --platform sqlite --benchmark tpch \
  --platform-option cache_size=-128000 \
  --platform-option journal_mode=WAL \
  --platform-option synchronous=OFF
```

## Related Documentation

- [DuckDB](duckdb.md) - Columnar analytical database
- [PostgreSQL](postgresql.md) - Full-featured RDBMS
- [Platform Selection](platform-selection-guide.md)
