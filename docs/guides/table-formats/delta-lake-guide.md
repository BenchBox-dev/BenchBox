# Delta Lake Guide

```{tags} guide, formats, delta-lake, databricks
```

Delta Lake adds transaction logs and ACID semantics on top of Parquet. This guide covers how transaction overhead affects benchmarks, when to use OPTIMIZE and Z-ORDER, and Databricks-specific considerations.

## Overview

Delta Lake started as Databricks' solution to the "data lake reliability problem": too many small files, no consistency guarantees, and no way to roll back bad data loads. It solves these problems by adding a transaction log on top of Parquet.

For benchmarking, Delta Lake matters because:

- It's the default format on Databricks (a major analytics platform)
- Transaction overhead affects measured performance
- OPTIMIZE and Z-ORDER change query characteristics
- You might want to compare Delta vs raw Parquet

We added Delta Lake support to BenchBox because Databricks is one of the most widely-used analytics platforms, and understanding Delta's performance characteristics helps interpret results.

## How Delta Lake Works

### Transaction Log Architecture

Delta Lake stores data in Parquet files, just like plain Parquet. The difference is the `_delta_log` directory, which tracks:

- Which Parquet files belong to the table
- Table schema and metadata
- Transaction history (enabling time travel)

```
delta_table/
├── _delta_log/
│   ├── 00000000000000000000.json  # Transaction 0: create table
│   ├── 00000000000000000001.json  # Transaction 1: insert data
│   └── 00000000000000000002.json  # Transaction 2: more inserts
├── part-00000-xxxx.parquet
├── part-00001-xxxx.parquet
└── part-00002-xxxx.parquet
```

Every read starts by consulting the transaction log to identify valid files. Every write creates a new log entry.

### ACID Guarantees for Benchmarking

| Property | What it means | Benchmark implication |
|----------|---------------|----------------------|
| Atomicity | Writes succeed or fail completely | No partial data during multi-table loads |
| Consistency | Schema enforced on write | No type mismatches between runs |
| Isolation | Concurrent reads/writes don't conflict | Reproducible during multi-phase benchmarks |
| Durability | Committed data persists | Results survive process crashes |

For benchmarking, ACID guarantees matter most during data loading. With Delta Lake, a failed load doesn't leave partial data. With raw Parquet, you might have orphaned files to clean up.

### Delta Lake Ecosystem

| Variant | Maintainer | Notes |
|---------|------------|-------|
| Delta Lake OSS | Linux Foundation | Core features, open protocol |
| Databricks Delta | Databricks | Photon optimization, Unity Catalog |
| delta-rs | Delta Lake project | Rust implementation, DuckDB/Polars |

BenchBox supports Delta Lake through:

- Native Databricks integration (full feature set)
- delta-rs for DuckDB (read-only via extension)
- Spark with open-source Delta Lake

## Performance Considerations

### Transaction Log Overhead

Every Delta Lake read starts with the transaction log:

1. Read latest checkpoint (if exists)
2. Read transaction log entries since checkpoint
3. Build list of valid Parquet files
4. Read Parquet files

**Overhead characteristics:**

- **Small tables**: Negligible (a few milliseconds)
- **Many transactions**: Grows linearly with log entries
- **Mitigated by checkpoints**: Every 10 transactions by default

For TPC-H benchmarks with a single data load, the overhead is typically under 10ms. For tables with thousands of transactions, consider running checkpoint or OPTIMIZE.

### OPTIMIZE: File Compaction

Delta Lake's OPTIMIZE command compacts small files into larger ones:

```sql
OPTIMIZE lineitem;
```

After a data load that creates many small files, OPTIMIZE consolidates them. This reduces:

- File listing overhead
- Number of file opens
- Transaction log size

**Benchmark results**: Raw load is about 12% slower than Parquet. After OPTIMIZE, the difference drops to ~2%.

### Z-ORDER: Data Clustering

Z-ORDER clusters data by specified columns:

```sql
OPTIMIZE lineitem ZORDER BY (l_shipdate, l_orderkey);
```

Z-ORDER reorders data so rows with similar values are stored together. Queries filtering on Z-ORDER columns skip more data.

**Benchmark results**: For date-filtered queries, Z-ORDER provides 17-30% improvement:

| Query | Without Z-ORDER | With Z-ORDER | Improvement |
|-------|-----------------|--------------|-------------|
| Q1 | 1.8s | 1.5s | 17% |
| Q4 | 0.9s | 0.7s | 22% |
| Q6 | 0.5s | 0.35s | 30% |

Q6 benefits most because it filters on l_shipdate with a narrow range. Z-ORDER clusters matching rows together, reducing data scanned.

**Trade-off**: Z-ORDER adds significant write overhead. For TPC-H SF10 lineitem, Z-ORDER takes 3-5 minutes on a small Databricks cluster.

## Databricks-Specific Features

### Photon Engine

Databricks Delta includes Photon, a C++ vectorized execution engine optimized for Delta tables. Photon provides significant speedups for scan-heavy queries.

For benchmarks, you may want to:

- Disable Photon to measure baseline performance
- Enable Photon for realistic production comparisons
- Document which engine was used in your methodology

### Auto-Compaction

Databricks can run OPTIMIZE automatically in the background for streaming tables. For benchmarking, consider disabling auto-compaction to measure baseline performance and have full control over when compaction occurs.

### Liquid Clustering

Liquid Clustering is Databricks' newer alternative to Z-ORDER. It provides dynamic clustering without requiring explicit OPTIMIZE commands. This is relevant for streaming workloads but less common in TPC benchmarking scenarios.

## DuckDB Delta Support

### delta-rs Extension

As of January 2026, DuckDB's delta-rs extension:

- Supports read operations (SELECT, aggregations, joins)
- Supports Delta Lake protocol versions 1 and 2
- Does not support write operations (load via Python)
- May have compatibility issues with newest Delta features

### Limitations

DuckDB Delta support is read-only. BenchBox generates Delta tables using the deltalake Python library, then queries with DuckDB. This workflow is useful for testing Delta read performance across platforms.

```bash
# Install delta extension (one-time)
duckdb -c "INSTALL delta; LOAD delta;"

# Run with Delta Lake format
benchbox run --platform duckdb --benchmark tpch --scale 1 --table-format delta
```

## Open-Source vs Databricks Delta

| Aspect | OSS Delta Lake | Databricks Delta |
|--------|----------------|------------------|
| OPTIMIZE | Manual | Auto-compact option |
| Z-ORDER | Supported | Enhanced (Liquid Clustering) |
| Caching | Standard | Photon acceleration |
| Protocol | Same | Same |

Results are comparable across implementations when using the same Delta protocol version and disabling Databricks-specific optimizations.

## When to Use Delta Lake

### Best-Fit Scenarios

| Scenario | Why Delta Lake |
|----------|----------------|
| Databricks benchmarks | Native format, optimized |
| Multi-phase loads | ACID ensures consistency |
| Load + query workloads | Measure end-to-end |
| Time travel testing | Benchmark historical queries |

### When to Use Parquet Instead

| Scenario | Why Parquet |
|----------|-------------|
| Cross-platform comparison | Universal support |
| Maximum simplicity | No transaction overhead |
| Storage efficiency focus | No metadata overhead |
| Non-Spark/Databricks | Limited Delta support |

## Benchmark Design Tips

1. **Include OPTIMIZE in load phase**: Measure realistic query performance
2. **Measure with and without Z-ORDER**: Quantify benefit for your queries
3. **Track transaction log size**: Grows with table history
4. **Use VACUUM before benchmarks**: Remove old versions for clean baseline

```bash
# Enable Z-ORDER clustering after load (default on Databricks)
benchbox run --platform databricks --benchmark tpch --table-format delta \
  --platform-option databricks_clustering_strategy=z_order

# Skip clustering (measure raw load performance)
benchbox run --platform databricks --benchmark tpch --table-format delta \
  --platform-option databricks_clustering_strategy=none

# Use Liquid Clustering on specific columns
benchbox run --platform databricks --benchmark tpch --table-format delta \
  --platform-option databricks_clustering_strategy=liquid_clustering \
  --platform-option liquid_clustering_columns=l_shipdate,l_orderkey
```

## See Also

- [Table Format Guides](index.md): Overview of all formats
- [Format Conversion Reference](../../advanced/format-conversion.md): CLI commands for format conversion
- [Parquet Deep Dive](parquet-deep-dive.md): Foundation format for Delta Lake <!-- content-ok: cliche -->
- [Apache Iceberg Guide](iceberg-guide.md): Alternative table format
