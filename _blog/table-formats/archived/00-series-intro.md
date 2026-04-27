# Table formats for benchmarking: A practical guide

> Modern table formats offer different trade-offs for analytics workloads. Here's how we evaluate them using BenchBox and what we learned from running TPC-H across formats.

**TL;DR**: Format choice affects benchmark validity, storage costs, and reproducibility. Parquet is the universal default, but Delta Lake, Iceberg, and Vortex each have their place. BenchBox handles format conversion automatically, letting you focus on the benchmarks themselves.

---

## Introduction

When comparing database performance, we often focus on query engines and tuning parameters. The data format, sitting quietly in the background, gets less attention. Yet format choice affects everything from storage costs to query performance to whether your results are reproducible across platforms.

We built format support into BenchBox because we kept running into the same questions: Why are my Parquet files so much smaller than CSV? Can I compare DuckDB on Parquet against Databricks on Delta Lake fairly? What's this Vortex format everyone's talking about?

This series shares what we learned about table formats in the context of benchmarking. We're not covering production lakehouse operations or streaming ingestion. We're focused on the practical question: which format should you use for your benchmarks, and what are the trade-offs?

---

## Why format matters for benchmarks

### The invisible variable

Consider a benchmark comparing two platforms. Platform A loads CSV files. Platform B loads Parquet. Platform B wins by 3x on query performance. Is Platform B faster, or is it just benefiting from columnar storage?

Format choice introduces variables that affect benchmark validity:

**Storage efficiency**: Parquet with Zstd compression can be 5-10x smaller than CSV. At scale factor 10, that's the difference between 10GB and 1GB of data. Smaller data means less I/O, which affects query times.

**Query optimization**: Columnar formats enable predicate pushdown (filtering at the storage layer) and column pruning (reading only needed columns). A `SELECT customer_name` query reads one column from Parquet but the entire file from CSV.

**Platform support**: Not every platform reads every format. Snowflake reads Parquet but not Delta Lake. Databricks reads Delta natively. Running the same benchmark across platforms requires a format they all understand.

**Reproducibility**: Different CSV parsers handle edge cases differently. Parquet files are self-describing, with schema and types embedded. The same Parquet file produces identical results across platforms.

### BenchBox's approach

We standardize on Parquet as the default format because:

- Every platform we support reads Parquet
- Performance characteristics are well-understood
- Files are self-describing and portable

But we also support Delta Lake, Iceberg, and Vortex for users who need format-specific benchmarks. BenchBox handles the conversion automatically during data generation.

---

## The format landscape

### File formats vs. table formats

**File formats** (Parquet, ORC, Vortex) define how data is serialized to bytes. Each file is self-contained. No external state or metadata management required.

**Table formats** (Delta Lake, Iceberg, Hudi) build on file formats, typically Parquet. They add transaction logs for ACID guarantees, schema evolution, time travel, and compaction. The "table" is the collection of files plus metadata.

For benchmarking, the distinction matters:

- File formats are simpler to set up and more portable
- Table formats add overhead but enable production-like conditions

### Format comparison

| Format | Type | Ecosystem | Maturity | Key Strength |
|--------|------|-----------|----------|--------------|
| Parquet | File | Universal | Production (10+ years) | Compatibility |
| Delta Lake | Table | Databricks, Spark | Production (5+ years) | ACID, Databricks optimization |
| Iceberg | Table | Multi-engine | Production (4+ years) | Engine independence |
| Vortex | File | DuckDB, DataFusion | Incubation (2025) | Performance |

### When format affects your benchmarks

**Format matters when:**

- Comparing across platforms (format support varies)
- Measuring storage costs (compression ratios differ by 2-5x)
- Testing query features (predicate pushdown, statistics)
- Running at large scale factors where I/O dominates

**Format matters less when:**

- Comparing queries on the same platform with the same format
- Running at small scale factors where compute dominates
- Testing CPU-bound operations like complex joins

---

## BenchBox format support

### Default behavior

BenchBox selects formats automatically based on platform:

```python
PLATFORM_FORMAT_PREFERENCES = {
    "duckdb": ["parquet", "vortex", "delta"],
    "datafusion": ["parquet", "vortex"],
    "databricks": ["delta", "parquet"],
    "snowflake": ["parquet"],
    "polars-df": ["parquet"],
}
```

When you run a benchmark, BenchBox uses the first supported format for that platform. For most users, this means Parquet.

### Overriding the default

```bash
# Use specific format
benchbox run --platform duckdb --benchmark tpch --format vortex

# With compression level
benchbox run --platform duckdb --benchmark tpch --format parquet --compression zstd:9
```

### Format support matrix

| Format | Platforms | Notes |
|--------|-----------|-------|
| Parquet | All | Default, recommended for cross-platform |
| Delta Lake | Databricks, DuckDB (extension), Spark | Best on Databricks |
| Iceberg | Spark, Trino, Athena, Starburst | Multi-engine workflows |
| Vortex | DuckDB, DataFusion | Extension required |
| CSV/TBL | All | For compatibility testing |

### How data conversion works

BenchBox handles format conversion during data generation:

1. Generate TPC-H data in TBL format (pipe-delimited)
2. Convert to target format (Parquet, Delta, Iceberg, Vortex)
3. Load into platform
4. Run benchmark queries

```bash
# Generate and benchmark with Vortex format
benchbox run --platform duckdb --benchmark tpch --scale 1 --format vortex

# BenchBox handles the conversion automatically
```

---

## Storage comparison

We ran TPC-H SF1 across formats to measure storage efficiency. All tests used the same source data (TBL files generated by dbgen).

| Format | SF1 Size | Ratio vs TBL | Notes |
|--------|----------|--------------|-------|
| TBL (raw) | 1.0 GB | 1.0x | Baseline |
| Parquet (zstd) | 280 MB | 0.28x | BenchBox default |
| Delta Lake (zstd) | 290 MB | 0.29x | Includes transaction log |
| Iceberg (zstd) | 285 MB | 0.29x | Includes metadata |
| Vortex (zstd) | 275 MB | 0.28x | Composable encoding |

The table formats (Delta, Iceberg) have metadata overhead of 1-5%. Parquet and Vortex achieve similar compression ratios. The compression algorithm (Zstd, Snappy, LZ4) matters more than the format for storage size.

---

## Query performance patterns

We tested TPC-H on DuckDB with both Parquet and the platform's native format to understand performance patterns. These results are from our SF1 baseline runs.

**DuckDB TPC-H SF1 Results (Parquet)**[^1]:
- Geometric mean: 38.7ms per query
- Total query time: 2.8s for all 22 queries
- Power@Size: 105,281

**DataFusion TPC-H SF1 Results (Parquet)**[^1]:
- Geometric mean: 110.1ms per query
- Total query time: 8.4s for all 22 queries

**Query patterns we observed**:

**Scan-heavy queries** (Q1, Q6) benefit from format efficiency. These queries read large portions of the lineitem table. Faster scans and better compression translate to faster results.

**Join-heavy queries** (Q5, Q8, Q9) are less format-sensitive. CPU time dominates I/O. The same query runs in similar time regardless of whether the format is Parquet or Vortex.

**Selective lookups** (Q2, Q11) benefit from predicate pushdown. Formats with good statistics skip irrelevant row groups, reducing data read.

---

## Choosing a format

### Decision matrix

| Scenario | Recommended | Reason |
|----------|-------------|--------|
| Cross-platform comparison | Parquet | Universal support |
| Databricks-only | Delta Lake | Native optimization |
| Multi-engine lakehouse | Iceberg | Engine independence |
| DuckDB performance focus | Vortex | 10-20x scan claims |
| Maximum compatibility | Parquet | 10+ years of tooling |

### Our recommendations

**For most benchmarks**: Use Parquet (the default)

Parquet works on every platform, has well-understood performance characteristics, and provides maximum reproducibility. Unless you have a specific reason to use another format, stick with the default.

**For platform-specific benchmarks**: Match the platform's native format

If you're benchmarking Databricks, use Delta Lake. If you're on Trino or Starburst, consider Iceberg. This tests the platform under realistic conditions.

**For format comparison benchmarks**: Run both and compare

```bash
benchbox run --platform duckdb --benchmark tpch --format parquet
benchbox run --platform duckdb --benchmark tpch --format vortex

# Compare results using BenchBox MCP tools or CLI
```

---

## Series roadmap

This is the first post in our table formats series. Each subsequent post goes deeper into a specific format:

| Post | Format | What you'll learn |
|------|--------|-------------------|
| 1 | Parquet | Row groups, compression options, when to tune |
| 2 | Delta Lake | Transaction overhead, OPTIMIZE, Z-ORDER effects |
| 3 | Iceberg | Catalog setup, multi-engine workflows |
| 4 | Vortex | Architecture, DuckDB extension, benchmark results |

### How to read this series

**New to table formats?** Start with Post 1 (Parquet basics). It covers fundamentals that apply to all formats.

**Databricks user?** Jump to Post 2 (Delta Lake). You'll learn about OPTIMIZE, Z-ORDER, and how to benchmark Delta tables effectively.

**Multi-engine architecture?** Focus on Post 3 (Iceberg). It covers cross-engine benchmarking and catalog configuration.

**Performance curious?** Check Post 4 (Vortex). We explore this composable-encoding format and its claimed performance improvements.

---

## Feedback welcome

We'd love to hear about your format benchmarking experiences. Open an issue on GitHub to discuss additional formats, platform combinations, or use cases you'd like us to explore.

---

## References

[^1]: BenchBox TPC-H SF1 benchmark, Apple M-series, 32GB RAM, cold cache, median of 3 runs. January 2026.

- [Apache Parquet](https://parquet.apache.org/)
- [Delta Lake](https://delta.io/)
- [Apache Iceberg](https://iceberg.apache.org/)
- [Vortex](https://vortex.dev/)
- [BenchBox Format Documentation](https://docs.benchbox.dev/formats)

---

*Questions or feedback? [Open an issue](https://github.com/oxbow-analytics/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: ~1,800
**Series**: table-formats
**Post Number**: 0
