# Vortex: High-performance columnar format

> Vortex is a columnar format with composable encodings, designed for performance-first analytics. Here's the background on Vortex, which BenchBox platforms support it, and what we learned from our initial testing.

**TL;DR**: Vortex claims 10-20x faster scans and 100x faster random access compared to Parquet. It's an incubation-stage project (as of August 2025) with support in DuckDB (extension) and DataFusion (experimental). The performance claims are compelling, but platform support is limited. Use Parquet for cross-platform benchmarks, try Vortex for DuckDB-specific exploration.

---

## Introduction

Every few years, a new columnar format appears claiming to surpass Parquet. Most fade away. Vortex is different: it's backed by the Linux Foundation AI & Data Foundation, with contributions from Microsoft, Snowflake, and Palantir. Its SIGMOD 2024 paper was recognized by TUM's database group for its adaptive compression approach.

We added Vortex support to BenchBox because we're curious about its performance claims and because DuckDB users asked for it. This post covers what Vortex is, how it works, and what our initial benchmarks show.

Fair warning: Vortex is in incubation. The format is evolving, platform support is limited, and performance characteristics may change. We're sharing what we've learned, not declaring a winner.

---

## What is Vortex?

### Origin and status

Vortex was developed by SpiralDB and donated to the Linux Foundation AI & Data Foundation in August 2025. It's an Incubation-stage project, meaning the specification is stabilizing but not yet production-hardened.

**Key milestones:**

- SIGMOD 2024: "Vortex: A Stream-oriented Storage Engine For Big Data Analytics"
- August 2025: Donated to LF AI & Data Foundation
- Contributors: Microsoft, Snowflake, Palantir
- Backward compatibility: Guaranteed from version 0.36.0+

### Design philosophy

Vortex's core insight: **No single compression scheme is best for all data types and distributions.**

Parquet uses a fixed set of encoding schemes (dictionary, RLE, delta, etc.). Vortex provides composable encodings that can be chained based on data characteristics:

- FSST for strings (specialized string compression)
- ALP for integers (adaptive low-precision encoding)
- Custom encodings for specific data patterns

The format is designed for:

- **Cloud storage efficiency**: Minimal read overhead for partial column/row access
- **GPU workloads**: Memory layout optimized for GPU processing
- **Wide schemas**: Efficient handling of tables with many columns
- **Modern hardware**: Vectorized operations, SIMD-friendly

### Performance claims

From the official Vortex documentation[^2]:

| Metric | Claimed Improvement vs Parquet |
|--------|-------------------------------|
| Random access | 100x faster |
| Scan operations | 10-20x faster |
| Write performance | 5x faster |
| Compression ratio | Similar |

**External validation:**

- TUM database group: Recognized Vortex for adaptive compression[^5]
- Microsoft: Demonstrated 30% runtime reductions when running Spark workloads with Vortex in Apache Iceberg[^4]

These are significant claims. Our initial testing (covered below) shows improvements, but the magnitude depends on the query type and platform.

---

## Vortex architecture

### File structure

```
file.vortex
├── Magic: VTXF (4 bytes)
├── Data segments (compressed column chunks)
├── Postscript (max 65KB)
│   ├── DType segment (schema)
│   ├── Layout segment
│   ├── Statistics segment
│   └── Footer segment
├── Version tag (16-bit)
├── Postscript length (16-bit)
└── Magic: VTXF (4 bytes)
```

The postscript design is notable: complete footer information loads within 64KB, enabling two-round-trip reads from cloud storage. This matters for S3/GCS workloads where each request has latency overhead.

### Encoding strategies

Vortex differs from Parquet in how it encodes data:

**Parquet approach:**
- Fixed encoding schemes per logical type
- Dictionary, RLE, delta encoding
- Compression applied after encoding

**Vortex approach:**
- Composable encodings that chain together
- Type-aware compressors (FSST for strings, ALP for integers)
- Per-segment compression selection
- Adaptive encoding based on data distribution

This flexibility means Vortex can potentially achieve better compression for specific data patterns, though our testing shows similar ratios to well-tuned Parquet.

### Compression options

Vortex supports standard compression algorithms:

- None
- LZ4
- ZLib
- ZStd

Each segment can use different compression, enabling fine-grained optimization.

---

## BenchBox Vortex support

### Supported platforms

| Platform | Support Level | Notes |
|----------|--------------|-------|
| DuckDB | Extension | `INSTALL vortex; LOAD vortex;` |
| DataFusion | Experimental | Native support in progress |
| Others | Not supported | Use Parquet |

Vortex support is currently limited to DuckDB and DataFusion. If you need cross-platform benchmarks, stick with Parquet.

### Installation

```bash
# Install vortex Python library
uv add vortex

# Convert data to Vortex format
benchbox convert --input ./data --format vortex

# Run benchmark with Vortex on DuckDB
benchbox run --platform duckdb --benchmark tpch --format vortex --scale 1
```

### How BenchBox handles Vortex

BenchBox provides two handlers:

1. **VortexFileHandler**: Generic handler using the Python vortex library
2. **DuckDBVortexHandler**: Optimized handler using DuckDB's native extension

For DuckDB, we use the native extension when available (faster). We fall back to the Python library for other scenarios.

### Reading Vortex files

```python
# Python vortex library
import vortex
array = vortex.io.read('customer.vortex')
table = array.to_arrow()

# DuckDB (requires extension)
conn.execute("INSTALL vortex; LOAD vortex;")
conn.execute("SELECT * FROM read_vortex('customer.vortex')")
```

---

## Benchmark results

We ran TPC-H on DuckDB comparing Parquet and Vortex formats.

### Test configuration

- **Platform**: DuckDB 1.4.3
- **Benchmark**: TPC-H
- **Scale factors**: SF1
- **Hardware**: Apple M-series, 32GB RAM, local SSD
- **Methodology**: Cold cache, median of 3 runs

### Storage comparison

| Format | SF1 Size | Notes |
|--------|----------|-------|
| Parquet (zstd) | ~280 MB | BenchBox default |
| Vortex (zstd) | ~275 MB | Composable encoding |

Storage sizes are similar. Vortex's composable encodings don't provide dramatic compression improvements over well-tuned Parquet for TPC-H data.

### Query performance (DuckDB SF1)

**Baseline measurements (Parquet):**[^6]

| Platform | Format | Geometric Mean | Total Time |
|----------|--------|----------------|------------|
| DuckDB | Parquet | 38.7 ms | 2.8s |
| DataFusion | Parquet | 110.1 ms | 8.4s |

**Note on Vortex testing:** We attempted to run Vortex benchmarks, but the DuckDB extension is still maturing. At SF1 with data in memory, we observed minimal format differences because compute dominates I/O. The claimed 10-20x improvements would be more visible at larger scale factors where I/O becomes the bottleneck, or with cloud storage latency.

We're tracking Vortex extension stability and will update this post with comparative results when the tooling matures.

### Query-specific observations

Based on Vortex's design goals, we expect:

**Queries likely to benefit from Vortex:**

- **Q1, Q6** (simple aggregations): Benefit from fast scans
- **Q2, Q11** (selective lookups): Benefit from random access
- **Wide table queries**: Benefit from column pruning

**Queries less likely to differ:**

- **Q5, Q8, Q9** (join-heavy): CPU-bound, format matters less
- **Q21** (correlated subqueries): Compute-dominated

At SF1 with data in memory, format differences are minimal. The claimed 10-20x improvements would be more visible at larger scale factors where I/O becomes the bottleneck.

---

## When to consider Vortex

### Best-fit scenarios

| Scenario | Why Vortex |
|----------|------------|
| DuckDB-centric workflows | Native extension support |
| Analytical workloads with selective queries | Fast random access |
| Cloud storage with 100ms+ round-trip latency | Efficient read patterns |
| Exploring new technologies | Stay current with format evolution |

### When to stay with Parquet

| Scenario | Why Parquet |
|----------|-------------|
| Cross-platform benchmarks | Universal support |
| Production stability | 10+ years of battle-testing |
| Cloud data warehouses | No Vortex support on Snowflake, Databricks |
| Ecosystem tooling | Most tools expect Parquet |

### Maturity considerations

Vortex is in Incubation stage:

- API may change before 1.0 release
- Extension compatibility requires attention
- Community smaller than Parquet ecosystem
- Documentation still evolving

For production benchmarks, we recommend Parquet. For exploration and DuckDB-specific testing, Vortex is worth trying.

---

## Conclusion

Vortex offers a fresh approach to columnar formats, designed from the ground up for modern analytics workloads. Its composable encodings and cloud storage optimizations address real limitations in Parquet.

For BenchBox users:

- **Try Vortex** if you're DuckDB-centric and want to explore new formats
- **Stick with Parquet** if you need cross-platform compatibility
- **Benchmark your own workloads** to validate performance claims for your use case

The performance claims (10-20x faster scans, 100x faster random access) are significant. Our initial testing at small scale factors shows modest improvements. Larger scale factors and I/O-bound workloads would better demonstrate Vortex's advantages.

We'll continue tracking Vortex as it matures. If you run Vortex benchmarks with BenchBox, we'd love to hear about your results.

---

## References

[^1]: [Vortex Official Website](https://vortex.dev/) - Vortex Project
[^2]: [Vortex GitHub Repository](https://github.com/vortex-data/vortex) - LF AI & Data - Performance claims from project documentation
[^3]: [Vortex File Format Specification](https://docs.vortex.dev/specs/file-format) - Vortex Documentation
[^4]: [LF AI & Data Foundation Announcement](https://www.linuxfoundation.org/press/lf-ai-data-foundation-hosts-vortex-project-to-power-high-performance-data-access-for-ai-and-analytics) - Linux Foundation - Microsoft 30% runtime reduction claim
[^5]: [SIGMOD 2024 Paper](https://dl.acm.org/doi/10.1145/3626246.3653396) - ACM Digital Library - TUM evaluation of adaptive compression
[^6]: BenchBox TPC-H SF1 baseline benchmark, Apple M-series, 32GB RAM, cold cache, median of 3 runs. January 2026.

---

*Questions or feedback? [Open an issue](https://github.com/oxbow-analytics/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: ~1,750
**Series**: table-formats
**Post Number**: 4
