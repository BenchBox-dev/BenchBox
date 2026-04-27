# "Table Formats with BenchBox" Content Plan

**Concept**: Practical guides for using modern table formats (Parquet, Delta Lake, Iceberg, Vortex) with BenchBox, covering format selection, configuration, and performance characteristics.

**Audience**: Data engineers and analytics practitioners evaluating or adopting table formats for their data lake/lakehouse architectures, who want to understand format trade-offs through benchmarking.

**Tone**: Educational, practical, format-neutral. We share what we learned running BenchBox with different table formats, with concrete numbers and reproducible commands.

**Length**: 1,500-2,500 words per post (Methodology Guide / Tutorial type)

**Cadence**: Weekly during series launch (5 posts over 5 weeks)

---

## Series Vision

Table formats are foundational to modern analytics architectures, but choosing between them, and configuring them correctly, requires understanding their trade-offs. This series uses BenchBox to explore how different table formats affect benchmark performance, storage efficiency, and query patterns.

**Key differentiator**: BenchBox provides a consistent methodology to compare formats. Each post shows real benchmark data with reproducible commands, not just theoretical comparisons.

**What this series covers:**
- Format fundamentals and when each matters
- BenchBox configuration for each format
- Performance characteristics at different scale factors
- Storage efficiency and compression trade-offs
- Platform compatibility considerations

**What this series does NOT cover:**
- Production deployment and operations
- Schema evolution and time travel features in depth
- Streaming ingestion patterns
- Format internals beyond what affects benchmarking

---

## Post Template

### Structure

1. **Format Overview** (~300 words)
   - What is this format and why does it exist?
   - Key characteristics relevant to benchmarking
   - When to consider this format

2. **BenchBox Configuration** (~300 words)
   - How to configure BenchBox to use this format
   - Supported platforms and any limitations
   - Example commands

3. **Benchmark Results** (~500 words)
   - TPC-H results at SF1 and SF10
   - Query-level analysis (which queries benefit most)
   - Storage size comparisons

4. **Performance Characteristics** (~400 words)
   - Compression ratios
   - Read vs. write trade-offs
   - Scale factor sensitivity

5. **Platform Compatibility** (~200 words)
   - Which BenchBox platforms support this format
   - Platform-specific considerations
   - Cross-platform consistency

6. **When to Use This Format** (~200 words)
   - Best-fit scenarios
   - Limitations and trade-offs
   - Comparison with alternatives

### Metadata Template

```yaml
title: "Table formats with BenchBox: {Format}"
series: table-formats
post_number: N
date: YYYY-MM-DD
tags: [benchmarking, benchbox, table-formats, {format}, parquet, data-lake]
```

---

## Planned Posts

| # | Post | Status | Purpose |
|---|------|--------|---------|
| 0 | **Series intro: Table formats for benchmarking** | PUBLISHED 2026-03-04 | Overview of formats, why they matter, series roadmap |
| 1 | **Parquet basics: The foundation of modern analytics** | DRAFT | Parquet fundamentals, compression, row groups; SF1 data measured |
| 2 | **Delta Lake: ACID transactions meet benchmarking** | OUTLINE | Delta Lake with BenchBox, local SF1 storage measured (305 MB); Databricks/Spark cloud benchmarks pending |
| 3 | **Apache Iceberg: The open table format** | OUTLINE | Iceberg with BenchBox, multi-engine support; local SF1 measured (311 MB snappy, 246 MB zstd) via pyiceberg SQLite catalog |
| 4 | **DuckLake: DuckDB-native ACID** | OUTLINE | DuckLake with BenchBox, local SF1 storage measured (309 MB) |
| 5 | **Vortex: High-performance columnar format** | OUTLINE | Vortex with BenchBox; DuckDB extension + Python vortex-data bindings available; SF1 measured (274 MB) |

### Outline Files

- `outlines/00-series-intro.md` - Series introduction
- `outlines/01-parquet-basics.md` - Parquet fundamentals
- `outlines/02-delta-lake.md` - Delta Lake with BenchBox
- `outlines/03-iceberg.md` - Apache Iceberg multi-engine
- `outlines/04-vortex.md` - Vortex high-performance format

---

## Post #0 Outline: Series Introduction

### Title
"Table formats for benchmarking: A practical guide"

### Thesis
> Modern table formats (Parquet, Delta Lake, Iceberg, Vortex) offer different trade-offs for analytics workloads. Here's how to evaluate them using BenchBox and what we learned from running TPC-H across formats.

### Structure

**1. Why Table Formats Matter for Benchmarking** (~400 words)
- Format choice affects benchmark validity
- Storage efficiency impacts cost comparisons
- Query performance varies by format features
- Reproducibility requires format consistency

**2. The Format Landscape** (~300 words)

| Format | Type | Key Strength | Best For |
|--------|------|--------------|----------|
| Parquet | File format | Universal support | Baseline, compatibility |
| Delta Lake | Table format | ACID, time travel | Databricks, Spark ecosystems |
| Iceberg | Table format | Multi-engine | Cross-platform lakehouses |
| Vortex | File format | Performance | High-throughput analytics |

**3. How BenchBox Handles Formats** (~300 words)
- Default format selection per platform
- Overriding with `--format` flag
- Format-specific optimizations
- Validation considerations

**4. What We Learned** (~400 words)
- Storage size comparison at SF10
- Query performance patterns
- Platform compatibility matrix
- Surprising findings

**5. Series Roadmap** (~200 words)
- What each post covers
- Recommended reading order
- How to request additional formats

### Metadata

```yaml
title: "Table formats for benchmarking: A practical guide"
series: table-formats
post_number: 0
date: YYYY-MM-DD
tags: [benchmarking, benchbox, table-formats, parquet, delta-lake, iceberg, vortex]
```

---

## Post #1 Outline: Parquet Basics

### Title
"Parquet basics: The foundation of modern analytics"

### Thesis
> Parquet is the de facto standard for analytical data storage. Understanding row groups, column chunks, and compression options is essential for meaningful benchmarking.

### Structure

**1. What is Parquet?** (~300 words)
- Columnar file format history (Apache project)
- Why columnar matters for analytics
- Parquet vs. CSV/JSON for benchmarking

**2. Parquet Concepts for Benchmarkers** (~400 words)
- Row groups: What they are, how they affect parallelism
- Column chunks: Predicate pushdown, column pruning
- Compression: Snappy, Zstd, LZ4, Gzip trade-offs
- Statistics: Min/max, null counts, bloom filters

**3. BenchBox Parquet Configuration** (~300 words)
- Default settings
- Compression options: `--compression zstd:9`
- Row group size considerations
- Platform-specific Parquet implementations

**4. Benchmark Results** (~500 words)
- TPC-H SF1/SF10 with different compression levels
- Storage size vs. query performance trade-offs
- Which queries benefit from Parquet features

**5. Best Practices** (~200 words)
- Recommended settings for benchmarking
- When to adjust row group size
- Compression selection guide

### Metadata

```yaml
title: "Parquet basics: The foundation of modern analytics"
series: table-formats
post_number: 1
date: YYYY-MM-DD
tags: [benchmarking, benchbox, table-formats, parquet, compression, columnar]
```

---

## Post #2 Outline: Delta Lake

### Title
"Delta Lake: ACID transactions meet benchmarking"

### Thesis
> Delta Lake adds transaction logs and ACID semantics on top of Parquet. Here's how to benchmark with Delta Lake using BenchBox and what the transaction overhead means for performance.

### Structure

**1. What is Delta Lake?** (~300 words)
- Parquet + transaction log
- ACID guarantees: Why they matter
- Delta Lake ecosystem (Databricks, open source)

**2. Delta Lake for Benchmarking** (~400 words)
- Transaction log overhead: reads vs. writes
- Optimize and Z-order: When to use them
- Vacuum and maintenance considerations
- Version compatibility (Delta Lake versions)

**3. BenchBox Delta Lake Configuration** (~300 words)
- Supported platforms: Databricks, Spark, DuckDB (via delta-rs)
- Configuration options
- Auto-optimization settings
- Example commands

**4. Benchmark Results** (~500 words)
- TPC-H on Databricks with Delta Lake
- Comparison with raw Parquet
- Impact of OPTIMIZE on query performance
- Z-order effects on specific queries

**5. Platform-Specific Considerations** (~200 words)
- Databricks optimizations
- Open-source Delta Lake vs. Databricks Delta
- DuckDB delta-rs support status

### Metadata

```yaml
title: "Delta Lake: ACID transactions meet benchmarking"
series: table-formats
post_number: 2
date: YYYY-MM-DD
tags: [benchmarking, benchbox, table-formats, delta-lake, databricks, acid]
```

---

## Post #3 Outline: Apache Iceberg

### Title
"Apache Iceberg: The open table format"

### Thesis
> Iceberg provides table format features with true multi-engine support. Here's how to benchmark with Iceberg across different query engines using BenchBox.

### Structure

**1. What is Iceberg?** (~300 words)
- Table format design philosophy
- Multi-engine support: Spark, Trino, Flink, DuckDB
- Iceberg vs. Delta Lake positioning

**2. Iceberg for Benchmarking** (~400 words)
- Manifest files and metadata overhead
- Partition evolution: Flexibility for benchmarks
- Hidden partitioning: Transparent optimization
- Catalog options: Hive, Glue, REST

**3. BenchBox Iceberg Configuration** (~300 words)
- Supported platforms: Spark, Trino/Starburst, Athena
- Catalog setup
- Configuration options
- Example commands

**4. Benchmark Results** (~500 words)
- TPC-H on Spark with Iceberg
- Cross-engine comparison (same Iceberg tables)
- Metadata overhead at different scale factors
- Partition strategy impact

**5. Multi-Engine Workflow** (~200 words)
- Writing with one engine, reading with another
- Ensuring consistent results across engines
- BenchBox validation with Iceberg

### Metadata

```yaml
title: "Apache Iceberg: The open table format"
series: table-formats
post_number: 3
date: YYYY-MM-DD
tags: [benchmarking, benchbox, table-formats, iceberg, multi-engine, data-lake]
```

---

## Post #4 Outline: Vortex

### Title
"Vortex: High-performance columnar format"

### Thesis
> Vortex is a columnar format with composable encodings, designed for performance. Here's the background on Vortex, which BenchBox platforms support it, and what our benchmarks show.

### Structure

**1. What is Vortex?** (~400 words)
- Background and origin
- Design goals: Performance-first columnar format
- How Vortex differs from Parquet
- Current status and maturity

**2. Vortex Architecture** (~300 words)
- Encoding strategies
- Compression approach
- Memory layout optimizations
- Read path design

**3. BenchBox Vortex Support** (~300 words)
- Supported platforms (list with status)
- Configuration options
- Limitations and known issues
- Example commands

**4. Benchmark Results** (~500 words)
- TPC-H comparison: Vortex vs. Parquet
- Query performance characteristics
- Storage efficiency
- Scale factor behavior

**5. When to Consider Vortex** (~200 words)
- Best-fit scenarios
- Maturity considerations
- Platform support roadmap
- Comparison with established formats

### Metadata

```yaml
title: "Vortex: High-performance columnar format"
series: table-formats
post_number: 4
date: YYYY-MM-DD
tags: [benchmarking, benchbox, table-formats, vortex, columnar, performance]
```

---

## Key Themes

### 1. Format-Neutral Evaluation

We present benchmarks without advocating for specific formats. Each format has trade-offs:
- **Parquet**: Universal but basic
- **Delta Lake**: Rich features, Databricks-centric
- **Iceberg**: Multi-engine, more metadata overhead
- **Vortex**: Performance-focused, less mature

### 2. Reproducibility

Every benchmark is reproducible with BenchBox commands:
```bash
# Generate data once
benchbox run --platform duckdb --benchmark tpch --scale 1 --phases generate

# Convert to target format
benchbox convert --input ./benchmark_runs/tpch_sf1 --format parquet --compression zstd
benchbox convert --input ./benchmark_runs/tpch_sf1 --format delta --compression zstd
benchbox convert --input ./benchmark_runs/tpch_sf1 --format ducklake
```

### 3. Practical Guidance

Focus on what matters for benchmarking:
- Storage size affects cost comparisons
- Format features affect query patterns
- Platform support affects reproducibility

### 4. BenchBox Integration

Show how BenchBox handles format complexity:
- Default format selection per platform
- Format-specific optimizations
- Consistent validation across formats

---

## Research Needs

### Per-Post Research

| Post | Research Required |
|------|-------------------|
| 0 - Intro | Format comparison matrix, storage size benchmarks |
| 1 - Parquet | Compression benchmarks (Snappy/Zstd/LZ4/Gzip), row group size tests |
| 2 - Delta Lake | Databricks benchmarks, OPTIMIZE impact, Z-order tests |
| 3 - Iceberg | Multi-engine benchmarks, catalog setup documentation |
| 4 - Vortex | Vortex background research, supported platform inventory |

### Benchmarks to Run

- [x] TPC-H SF1 Parquet compression (none/snappy/lz4/zstd:3/zstd:9) - 2026-03-04
- [x] TPC-H SF1 Delta Lake storage (305 MB snappy, 305 MB zstd) - 2026-03-04
- [x] TPC-H SF1 DuckLake storage (309 MB: 5 MB catalog + 304 MB data) - 2026-03-04
- [x] TPC-H SF1 Iceberg storage (311 MB snappy, 246 MB zstd) via pyiceberg SQLite catalog - 2026-03-04
- [x] TPC-H SF1 Vortex storage (274 MB) via DuckDB vortex extension - 2026-03-04
- [ ] TPC-H SF10 compression and storage across formats (run format_benchmark.py --sf 10)
- [ ] TPC-H SF1/SF10 on Databricks with Delta Lake (requires cloud access)
- [ ] TPC-H SF1/SF10 cross-engine Iceberg comparisons (requires shared catalog)

### Documentation to Review

- [ ] Parquet specification and best practices
- [ ] Delta Lake protocol documentation
- [ ] Iceberg specification and catalog options
- [x] Vortex documentation and design documents - 2026-01-31

---

## Publishing Recommendation

**Publish under BenchBox blog**

Rationale:
1. Educational content about using BenchBox features
2. Format-neutral stance (no format advocacy)
3. Reproducible benchmarks with BenchBox commands
4. Practical guidance for BenchBox users

---

*Series created: 2026-01-31*
*Last updated: 2026-03-04*

## Progress Tracker

| Milestone | Status | Date |
|-----------|--------|------|
| Series plan created | Done | 2026-01-31 |
| Post #0 outline | Done | 2026-01-31 |
| Post #1 outline | Done | 2026-01-31 |
| Post #2 outline | Done | 2026-01-31 |
| Post #3 outline | Done | 2026-01-31 |
| Vortex research | Done | 2026-01-31 |
| Local SF1 measurements (Parquet compressions) | Done | 2026-03-04 |
| Local SF1 measurements (Delta Lake, DuckLake) | Done | 2026-03-04 |
| Local SF1 measurements (Iceberg, Vortex) | Done | 2026-03-04 |
| Post #0 published | Done | 2026-03-04 |
| Post #1 draft (Parquet) | In Progress | 2026-03-04 |
| Post #2 outline (Delta Lake) | Done | 2026-01-31 |
| Post #3 outline (Iceberg) | Done | 2026-01-31 |
| Post #4 outline (DuckLake) | Needed | - |
| Post #5 outline (Vortex) | Needed | - |
| SF10 benchmarks | Needed | - |
| Cloud platform benchmarks (Delta/Iceberg) | Blocked | - |

## Research Files

- `research/04-vortex-research.md` - Comprehensive Vortex background research
- `research/format_benchmark.py` - Benchmarking script for local SF1/SF10 measurements (all five formats)
