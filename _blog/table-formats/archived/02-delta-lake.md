# Delta Lake: ACID transactions meet benchmarking

> Delta Lake adds transaction logs and ACID semantics on top of Parquet. Here's how we benchmark with Delta Lake using BenchBox and what the transaction overhead means for performance.

**TL;DR**: Delta Lake stores data in Parquet files plus a transaction log. The overhead is minimal after OPTIMIZE (~1-5%). Use OPTIMIZE after data load for realistic query benchmarks. BenchBox supports Delta natively on Databricks and via the delta-rs extension on DuckDB.

---

## Introduction

Delta Lake started as Databricks' solution to the "data lake reliability problem": too many small files, no consistency guarantees, and no way to roll back bad data loads. It solves these problems by adding a transaction log on top of Parquet.

For benchmarking, Delta Lake matters because:

- It's the default format on Databricks (a major analytics platform)
- Transaction overhead affects measured performance
- OPTIMIZE and Z-ORDER change query characteristics
- You might want to compare Delta vs. raw Parquet

We added Delta Lake support to BenchBox because Databricks is one of the most widely-used analytics platforms, and understanding Delta's performance characteristics helps interpret results.

---

## What is Delta Lake?

### Parquet plus a transaction log

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

### ACID guarantees

| Property | What it means | Benchmark implication |
|----------|---------------|----------------------|
| Atomicity | Writes succeed or fail completely | No partial data during multi-table loads |
| Consistency | Schema enforced on write | No type mismatches between runs |
| Isolation | Concurrent reads/writes don't conflict | Reproducible during multi-phase benchmarks |
| Durability | Committed data persists | Results survive process crashes |

For benchmarking, ACID guarantees matter most during data loading. With Delta Lake, a failed load doesn't leave partial data. With raw Parquet, you might have orphaned files to clean up.

### The Delta Lake ecosystem

| Variant | Maintainer | Notes |
|---------|------------|-------|
| Delta Lake OSS | Linux Foundation | Core features, open protocol |
| Databricks Delta | Databricks | Photon optimization, Unity Catalog |
| delta-rs | Delta Lake project | Rust implementation, DuckDB/Polars |

BenchBox supports Delta Lake through:

- Native Databricks integration (full feature set)
- delta-rs for DuckDB (read-only via extension)
- Spark with open-source Delta Lake

---

## Delta Lake for benchmarking

### Transaction log overhead

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

### OPTIMIZE and Z-ORDER

Delta Lake provides two optimization commands that affect benchmark performance:

**OPTIMIZE** compacts small files into larger ones:

```sql
OPTIMIZE lineitem;
```

After a data load that creates many small files, OPTIMIZE consolidates them. This reduces:

- File listing overhead
- Number of file opens
- Transaction log size

**Z-ORDER** clusters data by specified columns:

```sql
OPTIMIZE lineitem ZORDER BY (l_shipdate, l_orderkey);
```

Z-ORDER reorders data so rows with similar values are stored together. Queries filtering on Z-ORDER columns skip more data.

**Benchmark implications:**

- Run OPTIMIZE after data load to measure realistic query performance
- Z-ORDER benefits queries that filter on specific columns
- Both add write-time overhead (significant for large tables)

### Version compatibility

| Delta Version | Key Features | BenchBox Support |
|--------------|--------------|------------------|
| 2.0+ | Change data feed, column mapping | Full |
| 1.0-1.2 | Basic transactions, OPTIMIZE | Full |
| 0.x | Legacy | Limited |

BenchBox uses Delta Lake 2.0+ features when available, with automatic fallback for older readers.

---

## BenchBox Delta Lake configuration

### Supported platforms

| Platform | Support Level | Delta Implementation |
|----------|--------------|---------------------|
| Databricks | Native | Databricks Delta (optimized) |
| Spark | Native | Open-source Delta Lake |
| DuckDB | Extension | delta-rs (read-only) |
| Polars | Experimental | delta-rs |

### Databricks setup

```bash
# Run TPC-H on Databricks with Delta Lake
benchbox run --platform databricks --benchmark tpch --scale 10 --format delta
```

BenchBox automatically:

1. Creates Delta tables in the configured catalog
2. Loads data using COPY INTO (efficient bulk load)
3. Runs OPTIMIZE after load (configurable)
4. Executes benchmark queries

### DuckDB setup

```bash
# Install delta extension (one-time)
duckdb -c "INSTALL delta; LOAD delta;"

# Run with Delta Lake format
benchbox run --platform duckdb --benchmark tpch --scale 1 --format delta
```

**Note**: DuckDB's delta-rs support is read-only. BenchBox generates Delta tables using the deltalake Python library, then queries with DuckDB. This workflow is useful for testing Delta read performance across platforms.

### Configuration options

```bash
# Enable OPTIMIZE after load (default on Databricks)
benchbox run --platform databricks --benchmark tpch --format delta --optimize

# Skip OPTIMIZE (measure raw load performance)
benchbox run --platform databricks --benchmark tpch --format delta --no-optimize

# Enable Z-ORDER on specific columns
benchbox run --platform databricks --benchmark tpch --format delta \
  --zorder="l_shipdate,l_orderkey"
```

---

## Benchmark results

We ran TPC-H on Databricks to measure Delta Lake overhead and optimization effects.

**Test environment:**
- Databricks Runtime 14.3 LTS
- i3.xlarge workers (4 vCPU, 30.5 GB RAM)
- 2-node cluster
- Delta Lake 2.4
- January 2026

### Storage comparison

| Format | SF10 Size | vs Parquet | Notes |
|--------|-----------|------------|-------|
| Parquet (zstd) | 2.8 GB | 1.0x | Baseline |
| Delta Lake (raw) | 2.9 GB | 1.04x | Includes transaction log |
| Delta + OPTIMIZE | 2.85 GB | 1.02x | After compaction |

The transaction log adds 2-4% overhead. After OPTIMIZE, overhead drops to 1-2%.

### Query performance

| Scenario | SF10 Geometric Mean | vs Parquet |
|----------|---------------------|------------|
| Parquet (baseline) | 1.2s | 1.0x |
| Delta Lake (raw load) | 1.35s | 1.12x |
| Delta + OPTIMIZE | 1.22s | 1.02x |

Without OPTIMIZE, Delta is about 12% slower due to small file overhead. After OPTIMIZE, the difference drops to 2%.

### OPTIMIZE impact by query type

**Queries most affected by small files:**

- Q1 (full lineitem scan): 15% improvement after OPTIMIZE
- Q6 (lineitem aggregation): 12% improvement
- Q12 (lineitem + orders join): 10% improvement

**Queries less affected:**

- Q2 (selective supplier lookup): 2% improvement
- Q11 (small tables): 1% improvement

Scan-heavy queries benefit most from file consolidation. Selective queries already read few files, so OPTIMIZE helps less.

### Z-ORDER effects

We tested Z-ORDER on l_shipdate for date-filtered queries:

| Query | Without Z-ORDER | With Z-ORDER | Improvement |
|-------|-----------------|--------------|-------------|
| Q1 | 1.8s | 1.5s | 17% |
| Q4 | 0.9s | 0.7s | 22% |
| Q6 | 0.5s | 0.35s | 30% |

Q6 benefits most because it filters on l_shipdate with a narrow range. Z-ORDER clusters matching rows together, reducing data scanned.

**Trade-off**: Z-ORDER adds significant write overhead. For TPC-H SF10 lineitem, Z-ORDER takes 3-5 minutes on a small Databricks cluster.

---

## Platform considerations

### Databricks optimizations

Databricks Delta includes proprietary optimizations beyond open-source Delta Lake:

- **Photon engine**: Vectorized execution optimized for Delta tables
- **Predictive I/O**: Prefetches data based on query patterns
- **Auto-compaction**: Background OPTIMIZE for streaming tables
- **Liquid clustering**: Dynamic clustering (alternative to Z-ORDER)

For benchmarks, you may want to:

- Disable auto-compaction to measure baseline performance
- Enable Photon for realistic production comparisons
- Use open-source Delta Lake for reproducibility

### DuckDB delta-rs status

As of January 2026, DuckDB's delta-rs extension:

- Supports read operations (SELECT, aggregations, joins)
- Supports Delta Lake protocol versions 1 and 2
- Does not support write operations (load via Python)
- May have compatibility issues with newest Delta features

**Recommendation**: Use DuckDB for Delta read benchmarks. Generate Delta tables with PyArrow/deltalake or Spark.

### Open-source vs. Databricks Delta

| Aspect | OSS Delta Lake | Databricks Delta |
|--------|----------------|------------------|
| OPTIMIZE | Manual | Auto-compact option |
| Z-ORDER | Supported | Enhanced (Liquid Clustering) |
| Caching | Standard | Photon acceleration |
| Protocol | Same | Same |

Results are comparable across implementations when using the same Delta protocol version and disabling Databricks-specific optimizations.

---

## When to use Delta Lake for benchmarks

### Best-fit scenarios

| Scenario | Why Delta Lake |
|----------|----------------|
| Databricks benchmarks | Native format, optimized |
| Multi-phase loads | ACID ensures consistency |
| Load + query workloads | Measure end-to-end |
| Time travel testing | Benchmark historical queries |

### When to stay with Parquet

| Scenario | Why Parquet |
|----------|-------------|
| Cross-platform comparison | Universal support |
| Maximum simplicity | No transaction overhead |
| Storage efficiency focus | No metadata overhead |
| Non-Spark/Databricks | Limited Delta support |

### Benchmark design tips

1. **Include OPTIMIZE in load phase**: Measure realistic query performance
2. **Measure with and without Z-ORDER**: Quantify benefit for your queries
3. **Track transaction log size**: Grows with table history
4. **Use VACUUM before benchmarks**: Remove old versions for clean baseline

---

## Conclusion

Delta Lake adds valuable features for production lakehouses. For benchmarking:

- **Transaction log overhead**: Minimal after OPTIMIZE (~1-5%)
- **OPTIMIZE impact**: Significant for scan-heavy queries
- **Z-ORDER benefit**: Query-dependent, measure for your workload
- **Platform support**: Best on Databricks, growing elsewhere

For BenchBox users on Databricks, Delta Lake is the natural choice. It's the native format, it's optimized, and it reflects production conditions.

For cross-platform comparisons, Parquet remains the common denominator. If you need to compare Databricks vs. Snowflake vs. DuckDB, use Parquet on all platforms for a fair comparison.

In the next post, we'll explore Apache Iceberg, which offers similar table format capabilities with a focus on multi-engine support.

---

## References

[^1]: [Delta Lake Documentation](https://docs.delta.io/) - Linux Foundation
[^2]: [Databricks Delta Lake Guide](https://docs.databricks.com/delta/index.html) - Databricks
[^3]: [delta-rs GitHub](https://github.com/delta-io/delta-rs) - Delta Lake Project
[^4]: [DuckDB Delta Extension](https://duckdb.org/docs/extensions/delta) - DuckDB Documentation
[^5]: BenchBox TPC-H SF10 benchmark on Databricks DBR 14.3 LTS, i3.xlarge 2-node cluster, cold cache, median of 3 runs. January 2026.

---

*Questions or feedback? [Open an issue](https://github.com/oxbow-analytics/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: ~1,900
**Series**: table-formats
**Post Number**: 2
