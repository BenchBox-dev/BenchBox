# Post #0: Table formats for benchmarking - A practical guide

## Metadata

```yaml
title: "Table formats for benchmarking: A practical guide"
series: table-formats
post_number: 0
date: YYYY-MM-DD
tags: [benchmarking, benchbox, table-formats, parquet, delta-lake, iceberg, vortex, data-lake]
```

## Thesis

> Modern table formats (Parquet, Delta Lake, Iceberg, Vortex) offer different trade-offs for analytics workloads. Here's how to evaluate them using BenchBox and what we learned from running TPC-H across formats.

---

## 1. Why table formats matter for benchmarking (~400 words)

### The invisible variable

When comparing database performance, the data format often goes unexamined. Yet format choice affects:

- **Storage efficiency**: Parquet with Zstd can be 10x smaller than CSV
- **Query performance**: Columnar formats enable predicate pushdown and column pruning
- **Reproducibility**: Different formats on different platforms introduce variables
- **Cost**: Storage size directly impacts cloud benchmark costs

### BenchBox's approach

BenchBox standardizes on Parquet as the default format because:
- Universal platform support
- Well-understood performance characteristics
- Reproducible across engines

But we also support Delta Lake, Iceberg, and Vortex for users who need format-specific benchmarks.

### What this series covers

| Post | Format | Focus |
|------|--------|-------|
| 0 (this) | All | Overview and comparison |
| 1 | Parquet | Compression, row groups, fundamentals |
| 2 | Delta Lake | ACID transactions, Databricks integration |
| 3 | Iceberg | Multi-engine support, catalog options |
| 4 | Vortex | Next-gen performance, DuckDB extension |

---

## 2. The format landscape (~400 words)

### File formats vs. table formats

**File formats** (Parquet, ORC, Vortex):
- Define how data is serialized to bytes
- No transaction logs or metadata management
- Each file is self-contained

**Table formats** (Delta Lake, Iceberg, Hudi):
- Build on file formats (usually Parquet)
- Add transaction logs for ACID guarantees
- Enable time travel, schema evolution, compaction

### Quick comparison

| Format | Type | Ecosystem | Maturity | Key Strength |
|--------|------|-----------|----------|--------------|
| Parquet | File | Universal | Production (10+ years) | Compatibility |
| Delta Lake | Table | Databricks, Spark | Production (5+ years) | ACID, Databricks integration |
| Iceberg | Table | Multi-engine | Production (4+ years) | Engine independence |
| Vortex | File | DuckDB, DataFusion | Incubation (2025) | Performance |

### When format matters for benchmarks

**Format affects benchmark validity when:**
- Comparing across platforms (format support varies)
- Measuring storage costs (compression ratios differ)
- Testing query-specific features (predicate pushdown, statistics)

**Format is less critical when:**
- Comparing queries on the same platform
- Running standardized benchmarks with fixed data

---

## 3. BenchBox format support (~400 words)

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

### Overriding the default

```bash
# Use specific format
benchbox run --platform duckdb --benchmark tpch --format vortex

# With compression
benchbox run --platform duckdb --benchmark tpch --format parquet --compression zstd:9
```

### Format-specific considerations

| Format | BenchBox Support | Notes |
|--------|------------------|-------|
| Parquet | All platforms | Default, recommended |
| Delta Lake | Databricks, DuckDB (extension) | Requires catalog setup on some platforms |
| Iceberg | Spark, Trino, Athena | Requires catalog configuration |
| Vortex | DuckDB, DataFusion | Extension required for DuckDB |
| CSV/TBL | All platforms | For compatibility testing |

### Data conversion

BenchBox handles format conversion during data generation:

```bash
# Generate TPC-H data in Vortex format
benchbox run --platform duckdb --benchmark tpch --scale 1 --format vortex

# Conversion happens automatically:
# 1. Generate TBL files
# 2. Convert to target format
# 3. Load into platform
```

---

## 4. Storage comparison at SF10 (~300 words)

### Benchmark methodology

- **Dataset**: TPC-H SF10 (all 8 tables)
- **Baseline**: Raw TBL files (~10GB)
- **Compression**: Zstd for all formats where supported

### Results

| Format | Size | Ratio vs TBL | Notes |
|--------|------|--------------|-------|
| TBL (raw) | 10.0 GB | 1.0x | Baseline |
| CSV (gzip) | [TBD] | [TBD] | |
| Parquet (zstd) | [TBD] | [TBD] | BenchBox default |
| Delta Lake (zstd) | [TBD] | [TBD] | Includes transaction log |
| Iceberg (zstd) | [TBD] | [TBD] | Includes metadata |
| Vortex (zstd) | [TBD] | [TBD] | Composable encoding |

*[Benchmarks to be run and filled in]*

### Key observations

- Table formats (Delta, Iceberg) have metadata overhead (~1-5%)
- Parquet and Vortex achieve similar compression ratios
- Compression level matters more than format for storage size

---

## 5. Query performance patterns (~400 words)

### What we tested

- **Benchmark**: TPC-H 22 queries
- **Platforms**: DuckDB (Parquet vs Vortex)
- **Scale factors**: SF1, SF10

### Aggregate results

| Format | SF1 Total | SF10 Total | Geometric Mean |
|--------|-----------|------------|----------------|
| Parquet (zstd) | [TBD] | [TBD] | [TBD] |
| Vortex (zstd) | [TBD] | [TBD] | [TBD] |

*[Benchmarks to be run and filled in]*

### Query-specific observations

**Queries that benefit from format choice:**
- **Q1, Q6** (simple aggregations): Scan-heavy, benefit from format scan speed
- **Q2, Q11** (selective lookups): Benefit from random access performance
- **Q5, Q8** (multi-table joins): Less format-sensitive, join-bound

**Queries where format matters less:**
- Join-heavy queries where compute dominates I/O
- Queries that must scan most of the table regardless of format

### When to care about format performance

- **Large scale factors** (SF100+): I/O becomes bottleneck
- **Cloud storage**: Read latency amplifies format efficiency
- **Selective queries**: Predicate pushdown differences emerge

---

## 6. Choosing a format (~300 words)

### Decision matrix

| Scenario | Recommended Format | Reason |
|----------|-------------------|--------|
| Cross-platform benchmarks | Parquet | Universal support |
| Databricks-only | Delta Lake | Native optimization |
| Multi-engine lakehouse | Iceberg | Engine independence |
| DuckDB performance focus | Vortex | Claimed 10-20x scan improvement |
| Maximum compatibility | Parquet | 10+ years of tooling |

### What we recommend for BenchBox users

**For most benchmarks**: Use Parquet (the default)
- Works on all platforms
- Well-understood performance characteristics
- Maximum reproducibility

**For platform-specific benchmarks**: Match the platform
- Delta Lake on Databricks
- Iceberg on Trino/Starburst
- Vortex on DuckDB (experimental)

**For format comparison benchmarks**: Run both
```bash
benchbox run --platform duckdb --benchmark tpch --format parquet
benchbox run --platform duckdb --benchmark tpch --format vortex
benchbox compare-results parquet-results.json vortex-results.json
```

---

## 7. Series roadmap (~200 words)

### Coming next

| Post | What you'll learn |
|------|-------------------|
| 1. Parquet basics | Row groups, compression levels, when to tune |
| 2. Delta Lake | Transaction overhead, OPTIMIZE, Z-order effects |
| 3. Iceberg | Catalog setup, multi-engine workflows |
| 4. Vortex | Architecture, DuckDB extension, benchmark results |

### How to read this series

- **New to table formats?** Start with Post 1 (Parquet basics)
- **Databricks user?** Jump to Post 2 (Delta Lake)
- **Multi-engine architecture?** Focus on Post 3 (Iceberg)
- **Performance curious?** Check Post 4 (Vortex)

### Feedback welcome

We'd love to hear about your format benchmarking experiences. Open an issue to discuss additional formats or platform combinations you'd like us to explore.

---

## Research Needed

- [ ] Run TPC-H SF10 storage size comparison (all formats)
- [ ] Run TPC-H SF1/SF10 query benchmarks (Parquet vs Vortex on DuckDB)
- [ ] Verify platform format support matrix
- [ ] Check BenchBox format conversion commands

## References

- [Apache Parquet](https://parquet.apache.org/)
- [Delta Lake](https://delta.io/)
- [Apache Iceberg](https://iceberg.apache.org/)
- [Vortex](https://vortex.dev/)
- BenchBox format documentation (internal)

---

*Outline created: 2026-01-31*
*Status: OUTLINE - NEEDS BENCHMARKS*
