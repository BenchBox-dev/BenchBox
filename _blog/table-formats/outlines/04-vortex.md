# Post #4: Vortex - High-performance columnar format

## Metadata

```yaml
title: "Vortex: High-performance columnar format"
series: table-formats
post_number: 4
date: YYYY-MM-DD
tags: [benchmarking, benchbox, table-formats, vortex, columnar, performance]
```

## Thesis

> Vortex is a columnar format with composable encodings, designed for performance-first analytics. Here's the background on Vortex, which BenchBox platforms support it, and what our benchmarks show.

---

## 1. What is Vortex? (~400 words)

### Origin and History
- Developed by SpiralDB as a performance-focused alternative to Parquet
- Donated to Linux Foundation AI & Data Foundation in August 2025
- Now an Incubation-stage project with support from Microsoft, Snowflake, Palantir

### Design Philosophy
- **Core insight**: No single compression scheme is best for all data types
- Operates as a framework for creating specialized columnar representations
- Designed for modern workloads: GPU training, cloud object stores, multimodal data

### Performance Claims (with caveats)
| Metric | Claimed Improvement |
|--------|-------------------|
| Random access | 100x faster |
| Scan operations | 10-20x faster |
| Write performance | 5x faster |
| Compression | Similar to Parquet |

**External validation**:
- TUM database group: recognized for adaptive compression
- Microsoft: 30% runtime reduction in Spark workloads with Iceberg

### Current Status
- Version 0.36.0+ guarantees backward compatibility
- Active development with regular releases
- Growing ecosystem support

---

## 2. Vortex Architecture (~300 words)

### File Structure
```
file.vortex
├── Magic: VTXF (4 bytes)
├── Data segments (compressed column chunks)
├── Postscript (max 65KB)
│   ├── DType (schema)
│   ├── Layout
│   ├── Statistics
│   └── Footer
└── Magic: VTXF (4 bytes)
```

### Encoding Strategies
- **Composable encodings**: Chain compressors for optimal results
- **Type-aware**: FSST for strings, ALP for integers
- **Segment-level compression**: Each segment can use different compression

### Compression Options
- None, LZ4, ZLib, ZStd
- Fine-grained control per segment

### Read Path Design
- **Two round-trip reads**: Complete footer in 64KB
- **Cloud storage optimized**: Minimal overhead for partial reads
- **Statistics-based pruning**: Skip irrelevant data

---

## 3. BenchBox Vortex Support (~300 words)

### Supported Platforms

| Platform | Support Level | Notes |
|----------|--------------|-------|
| DuckDB | Extension | `INSTALL vortex; LOAD vortex;` |
| DataFusion | Experimental | Native support in progress |
| Others | Not supported | Parquet recommended |

### Configuration

```bash
# Install vortex package
uv add vortex

# Convert data to Vortex
benchbox convert --input ./data --format vortex

# With compression
benchbox convert --input ./data --format vortex --compression zstd
```

### BenchBox Automation

BenchBox handles:
- Format conversion from TBL to Vortex
- Extension installation for DuckDB
- Fallback to generic handler if extension unavailable
- Result validation across formats

### Limitations and Known Issues
- Extension compatibility with DuckDB versions
- DataFusion support is experimental
- No support on cloud platforms (Snowflake, Databricks, etc.)

---

## 4. Benchmark Results (~500 words)

### Test Configuration
- Platforms: DuckDB, DataFusion
- Benchmark: TPC-H
- Scale factors: SF1, SF10
- Comparison: Vortex vs Parquet (Zstd)

### Storage Size Comparison

| Scale Factor | TBL (raw) | Parquet (zstd) | Vortex (zstd) |
|--------------|-----------|----------------|---------------|
| SF1          | ~1 GB     | ~X MB          | ~X MB         |
| SF10         | ~10 GB    | ~X MB          | ~X MB         |

*[TO BE FILLED: Run actual benchmarks]*

### Query Performance (DuckDB)

#### Fastest Improvements
*[TO BE FILLED: Identify queries where Vortex excels]*

Expected patterns:
- Simple aggregations (Q1, Q6) benefit from fast scans
- Selective lookups (Q2, Q11) benefit from random access

#### Similar Performance
*[TO BE FILLED: Queries with comparable results]*

#### Slower Queries
*[TO BE FILLED: Any queries where Vortex underperforms]*

### Scale Factor Sensitivity

*[TO BE FILLED: How does the performance gap change with scale?]*

Expected: Performance benefits more pronounced at larger scale factors where I/O becomes bottleneck.

---

## 5. When to Consider Vortex (~200 words)

### Best-Fit Scenarios
- **DuckDB-centric workflows**: Native extension support
- **Analytical workloads with selective queries**: Benefits from fast random access
- **Cloud storage with high I/O costs**: Optimized for minimal reads
- **Experimentation**: Trying new format technologies

### When to Stay with Parquet
- **Multi-platform requirements**: Parquet has universal support
- **Production stability**: Parquet is battle-tested (10+ years)
- **Cloud data warehouses**: No Vortex support on Snowflake, Databricks, etc.
- **Ecosystem tooling**: Most tools expect Parquet

### Maturity Considerations
- Vortex is in Incubation stage (as of 2025)
- API may change before 1.0 release
- Extension compatibility requires attention
- Community smaller than Parquet ecosystem

### Platform Support Roadmap
- DuckDB: Stable extension
- DataFusion: Experimental, improving
- Spark: Not announced
- Polars: Not announced
- Cloud platforms: Unlikely near-term

---

## 6. Conclusion (~100 words)

Vortex represents the next generation of columnar formats, designed from the ground up for modern analytics workloads. Its performance claims are compelling, and early adoption by major companies suggests staying power.

For BenchBox users:
- **Try Vortex** if you're DuckDB-centric and want to explore new formats
- **Stick with Parquet** if you need multi-platform compatibility
- **Benchmark your own workloads** to validate performance claims for your use case

---

## Research Completed

- [x] Vortex background and history
- [x] Technical architecture documentation
- [x] BenchBox integration status
- [x] Platform support inventory

## Benchmarks Needed

- [ ] TPC-H SF1 on DuckDB: Parquet vs Vortex
- [ ] TPC-H SF10 on DuckDB: Parquet vs Vortex
- [ ] TPC-H SF1 on DataFusion: Parquet vs Vortex
- [ ] Storage size comparison at each scale factor
- [ ] Per-query analysis to identify patterns

## Open Questions

- How stable is the DuckDB Vortex extension across versions?
- What is the conversion overhead (TBL to Vortex vs TBL to Parquet)?
- Any query correctness issues in experimental DataFusion support?

---

*Outline created: 2026-01-31*
*Status: OUTLINE (ready for benchmarks)*
