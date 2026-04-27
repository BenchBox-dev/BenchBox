# Post #2: Delta Lake - ACID transactions meet benchmarking

## Metadata

```yaml
title: "Delta Lake: ACID transactions meet benchmarking"
series: table-formats
post_number: 2
date: YYYY-MM-DD
tags: [benchmarking, benchbox, table-formats, delta-lake, databricks, acid, spark]
```

## Thesis

> Delta Lake adds transaction logs and ACID semantics on top of Parquet. Here's how to benchmark with Delta Lake using BenchBox and what the transaction overhead means for performance.

---

## 1. What is Delta Lake? (~350 words)

### Parquet with superpowers

Delta Lake is a table format that stores data in Parquet files plus a transaction log. The transaction log tracks:
- Which Parquet files belong to the table
- Schema and table metadata
- Transaction history (time travel)

```
delta_table/
├── _delta_log/
│   ├── 00000000000000000000.json  # Transaction 0
│   ├── 00000000000000000001.json  # Transaction 1
│   └── 00000000000000000002.json  # Transaction 2
├── part-00000-xxxx.parquet
├── part-00001-xxxx.parquet
└── part-00002-xxxx.parquet
```

### ACID guarantees

| Property | What it means | Why it matters for benchmarks |
|----------|---------------|-------------------------------|
| Atomicity | Writes succeed or fail completely | No partial data during load |
| Consistency | Schema enforced | No type mismatches |
| Isolation | Concurrent reads/writes don't conflict | Reproducible during multi-phase benchmarks |
| Durability | Committed data persists | Results survive crashes |

### Delta Lake ecosystem

| Variant | Maintainer | Features |
|---------|------------|----------|
| Delta Lake OSS | Linux Foundation | Core features, open protocol |
| Databricks Delta | Databricks | Photon optimization, Unity Catalog |
| delta-rs | Delta Lake project | Rust implementation, DuckDB/Polars support |

BenchBox supports Delta Lake through:
- Native Databricks integration
- delta-rs for DuckDB (extension)
- Spark with open-source Delta Lake

---

## 2. Delta Lake for benchmarking (~400 words)

### Transaction log overhead

The transaction log adds overhead for reads:
1. Read transaction log to identify valid files
2. Filter to relevant Parquet files
3. Read Parquet files

**Overhead characteristics:**
- Small for few transactions (~10ms for 100 transactions)
- Grows with transaction count (compaction helps)
- Mitigated by checkpoints (every 10 transactions by default)

### OPTIMIZE and Z-ORDER

**OPTIMIZE** compacts small files into larger ones:
```sql
OPTIMIZE my_table;
```

**Z-ORDER** clusters data by specified columns:
```sql
OPTIMIZE my_table ZORDER BY (customer_id, order_date);
```

**Benchmark implications:**
- OPTIMIZE after data load improves query performance
- Z-ORDER benefits queries filtering on those columns
- Both add write-time overhead

### Version compatibility

| Delta Lake Version | Protocol Version | Key Features |
|-------------------|------------------|--------------|
| 2.0+ | 2,5 | Change data feed, column mapping |
| 1.0-1.2 | 1,2 | Basic features |
| 0.x | 1,1 | Legacy |

BenchBox uses Delta Lake 2.0+ features when available, with fallback for older readers.

### Vacuum and maintenance

```sql
-- Remove old files (default: 7 day retention)
VACUUM my_table;

-- Aggressive cleanup for benchmarks
VACUUM my_table RETAIN 0 HOURS;
```

**For benchmarks**: Run VACUUM after data load to remove small files and transaction cruft.

---

## 3. BenchBox Delta Lake configuration (~400 words)

### Supported platforms

| Platform | Support Level | Delta Implementation |
|----------|--------------|---------------------|
| Databricks | Native | Databricks Delta (optimized) |
| Spark | Native | Open-source Delta Lake |
| DuckDB | Extension | delta-rs (`INSTALL delta;`) |
| Polars | Experimental | delta-rs |

### Databricks setup

```bash
# Run TPC-H on Databricks with Delta Lake
benchbox run --platform databricks --benchmark tpch --scale 10 --format delta

# BenchBox automatically:
# 1. Creates Delta tables in Unity Catalog
# 2. Loads data with COPY INTO
# 3. Runs OPTIMIZE after load
# 4. Executes benchmark queries
```

### DuckDB setup

```bash
# Install delta extension (once)
duckdb -c "INSTALL delta; LOAD delta;"

# Run with Delta Lake format
benchbox run --platform duckdb --benchmark tpch --scale 1 --format delta
```

**Note**: DuckDB delta-rs support is read-only. BenchBox generates Delta tables using PyArrow/deltalake, then queries with DuckDB.

### Spark setup

```bash
# Spark with open-source Delta Lake
benchbox run --platform spark --benchmark tpch --scale 10 --format delta

# Requires Spark with Delta Lake JARs:
# spark.jars.packages: io.delta:delta-core_2.12:2.4.0
```

### Configuration options

```bash
# Enable OPTIMIZE after load
benchbox run --platform databricks --benchmark tpch --format delta --optimize

# Enable Z-ORDER on specific columns
benchbox run --platform databricks --benchmark tpch --format delta --zorder="l_shipdate,l_orderkey"

# Skip OPTIMIZE (measure raw load performance)
benchbox run --platform databricks --benchmark tpch --format delta --no-optimize
```

---

## 4. Benchmark results (~500 words)

### Test configuration

- **Platforms**: Databricks (DBR 14.3 LTS), DuckDB
- **Benchmark**: TPC-H
- **Scale factors**: SF1, SF10
- **Comparison**: Delta Lake vs raw Parquet

### Databricks results

#### Storage size

| Format | SF10 Size | vs Parquet | Notes |
|--------|-----------|------------|-------|
| Parquet (zstd) | [TBD] | 1.0x | Baseline |
| Delta Lake | [TBD] | [TBD] | Includes _delta_log |
| Delta + OPTIMIZE | [TBD] | [TBD] | After compaction |

*[Benchmarks to be run and filled in]*

#### Query performance

| Scenario | SF10 Total | Geometric Mean | Notes |
|----------|------------|----------------|-------|
| Parquet (baseline) | [TBD] | [TBD] | Raw Parquet files |
| Delta Lake (raw) | [TBD] | [TBD] | After load, no OPTIMIZE |
| Delta + OPTIMIZE | [TBD] | [TBD] | After OPTIMIZE |
| Delta + Z-ORDER | [TBD] | [TBD] | Z-ORDER on l_shipdate |

*[Benchmarks to be run and filled in]*

### DuckDB results

| Format | SF10 Total | Notes |
|--------|------------|-------|
| Parquet (zstd) | [TBD] | Native DuckDB |
| Delta Lake | [TBD] | Via delta-rs extension |

*[Benchmarks to be run and filled in]*

### OPTIMIZE impact

#### Queries most affected by OPTIMIZE

*[To be filled after benchmarks]*

Expected patterns:
- Queries scanning large tables (Q1, Q6) benefit from file consolidation
- Selective queries benefit less (I/O already minimal)

#### Z-ORDER impact on specific queries

| Query | Without Z-ORDER | With Z-ORDER (l_shipdate) | Improvement |
|-------|-----------------|---------------------------|-------------|
| Q1 | [TBD] | [TBD] | [TBD] |
| Q4 | [TBD] | [TBD] | [TBD] |
| Q6 | [TBD] | [TBD] | [TBD] |

*[Benchmarks to be run and filled in]*

### Key findings

*[To be filled after benchmarks]*

Expected findings:
- Delta overhead is minimal after OPTIMIZE (~1-5%)
- Z-ORDER benefits date-filtered queries significantly
- Transaction log overhead grows with table history

---

## 5. Platform-specific considerations (~300 words)

### Databricks optimizations

Databricks Delta includes proprietary optimizations:
- **Photon engine**: Vectorized execution for Delta tables
- **Predictive I/O**: Prefetches data based on query patterns
- **Auto-compaction**: Background OPTIMIZE for streaming tables

**For benchmarks**: Disable auto-compaction to measure baseline, or enable to measure production-like behavior.

### Open-source Delta Lake vs Databricks Delta

| Aspect | OSS Delta Lake | Databricks Delta |
|--------|----------------|------------------|
| OPTIMIZE | Manual | Auto-compact option |
| Z-ORDER | Supported | Enhanced |
| Caching | Standard | Photon acceleration |
| Protocol | Same | Same |

BenchBox results are comparable across implementations when using the same Delta protocol version.

### DuckDB delta-rs support status

As of 2026, DuckDB's delta-rs support:
- Read-only (writes require external tools)
- Supports Delta Lake protocol v1 and v2
- May have version compatibility issues with latest Delta features

**Recommendation**: Use DuckDB for Delta read benchmarks, but generate Delta tables with PyArrow/deltalake or Spark.

---

## 6. When to use Delta Lake for benchmarks (~250 words)

### Best-fit scenarios

| Scenario | Reason |
|----------|--------|
| Databricks benchmarks | Native support, optimized |
| Multi-phase benchmarks | ACID ensures consistency |
| Load + query workloads | Measure end-to-end |
| Time travel testing | Benchmark historical queries |

### When to stay with Parquet

| Scenario | Reason |
|----------|--------|
| Cross-platform comparison | Parquet has universal support |
| Maximum simplicity | No transaction log overhead |
| Storage efficiency focus | Delta adds metadata overhead |
| Non-Spark/Databricks | Limited Delta support |

### Benchmark design considerations

1. **Include OPTIMIZE in load phase**: Measure realistic query performance
2. **Measure with and without Z-ORDER**: Quantify the benefit for your queries
3. **Track transaction log size**: Grows with table history
4. **Use VACUUM before benchmarks**: Remove old versions for clean baseline

---

## 7. Conclusion (~150 words)

Delta Lake adds valuable features for production lakehouses, and those features have benchmarking implications:

- **Transaction log overhead**: Minimal after OPTIMIZE (~1-5%)
- **OPTIMIZE impact**: Significant for large table scans
- **Z-ORDER benefit**: Query-dependent, measure for your workload
- **Platform support**: Best on Databricks, growing elsewhere

For BenchBox users benchmarking on Databricks, Delta Lake is the natural choice. For cross-platform comparisons, Parquet remains the common denominator.

In the next post, we'll explore Apache Iceberg, which offers similar table format capabilities with a focus on multi-engine support.

---

## Research Needed

- [ ] Run TPC-H on Databricks with Delta Lake (SF1, SF10)
- [ ] Compare Delta vs Parquet query performance
- [ ] Measure OPTIMIZE impact on query performance
- [ ] Test Z-ORDER on date-filtered queries
- [ ] Verify DuckDB delta-rs extension status

## References

- [Delta Lake Documentation](https://docs.delta.io/)
- [Databricks Delta Lake Guide](https://docs.databricks.com/delta/index.html)
- [delta-rs GitHub](https://github.com/delta-io/delta-rs)
- [DuckDB Delta Extension](https://duckdb.org/docs/extensions/delta)

---

*Outline created: 2026-01-31*
*Status: OUTLINE - NEEDS BENCHMARKS*
