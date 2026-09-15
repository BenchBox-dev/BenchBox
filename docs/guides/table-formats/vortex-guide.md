# Vortex Guide

```{tags} guide, formats, vortex, experimental
```

Vortex is a columnar format with composable encodings, designed for high-performance analytics. This guide covers Vortex's architecture, current status, and when to consider it for benchmarking.

## Overview

Every few years, a new columnar format appears claiming to surpass Parquet. Most fade away. Vortex is different: it's backed by the Linux Foundation AI & Data Foundation, with contributions from Microsoft, Snowflake, and Palantir. Its SIGMOD 2024 paper was recognized by TUM's database group for its adaptive compression approach.

We added Vortex support to BenchBox because we're curious about its performance claims and because DuckDB users asked for it. This guide covers what Vortex is, how it works, and what our initial assessment shows.

**Fair warning**: Vortex is in incubation. The format is evolving, platform support is limited, and performance characteristics may change. We're sharing what we've learned, not declaring a winner.

## Project Status and Maturity

### Origin

Vortex was developed by SpiralDB and donated to the Linux Foundation AI & Data Foundation in August 2025. It's an Incubation-stage project, meaning the specification is stabilizing but not yet production-hardened.

### Current Status (Incubation)

**Key milestones:**

- SIGMOD 2024: "Vortex: A Stream-oriented Storage Engine For Big Data Analytics"
- August 2025: Donated to LF AI & Data Foundation
- Contributors: Microsoft, Snowflake, Palantir

### Backward Compatibility

Backward compatibility is guaranteed from version 0.36.0+. Earlier versions may have breaking changes.

## Design Philosophy

### Composable Encodings

Vortex's core insight: **No single compression scheme is best for all data types and distributions.**

Parquet uses a fixed set of encoding schemes (dictionary, RLE, delta, etc.). Vortex provides composable encodings that can be chained based on data characteristics:

- FSST for strings (specialized string compression)
- ALP for integers (adaptive low-precision encoding)
- Custom encodings for specific data patterns

### Cloud Storage Optimization

The format is designed for:

- **Minimal read overhead**: Complete footer information loads within 64KB, enabling two-round-trip reads from cloud storage
- **Wide schemas**: Efficient handling of tables with many columns
- **Partial reads**: Column pruning and predicate pushdown

### Modern Hardware Targets

Vortex targets modern hardware:

- **GPU workloads**: Memory layout optimized for GPU processing
- **Vectorized operations**: SIMD-friendly data layout
- **Large memory**: Designed for systems with substantial RAM

## Performance Claims

### Official Claims

From the official Vortex documentation:

| Metric | Claimed Improvement vs Parquet |
|--------|-------------------------------|
| Random access | 100x faster |
| Scan operations | 10-20x faster |
| Write performance | 5x faster |
| Compression ratio | Similar |

### External Validation

- TUM database group: Recognized Vortex for adaptive compression
- Microsoft: Demonstrated 30% runtime reductions when running Spark workloads with Vortex in Apache Iceberg

### Caveats

These are significant claims. Our initial testing shows:

- Storage sizes are similar to well-tuned Parquet for TPC-H data
- At SF1 with data in memory, format differences are minimal (compute dominates I/O)
- The claimed 10-20x improvements would be more visible at larger scale factors where I/O becomes the bottleneck
- Tooling is still maturing

## Vortex Architecture

### File Structure

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

### Encoding Strategies

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

### Compression Options

Vortex supports standard compression algorithms:

- None
- LZ4
- ZLib
- ZStd

Each segment can use different compression, enabling fine-grained optimization.

## Platform Support

### DuckDB Extension

```bash
# Install vortex extension (one-time)
duckdb -c "INSTALL vortex; LOAD vortex;"

# Query Vortex files
SELECT * FROM read_vortex('customer.vortex')
```

### DataFusion Support

DataFusion has experimental Vortex support in progress.

### Limitations

| Platform | Support Level | Notes |
|----------|--------------|-------|
| DuckDB | Extension | `INSTALL vortex; LOAD vortex;` |
| DataFusion | Experimental | Native support in progress |
| Others | Not supported | Use Parquet |

Vortex support is currently limited to DuckDB and DataFusion. If you need cross-platform benchmarks, stick with Parquet.

## When to Consider Vortex

### Best-Fit Scenarios

| Scenario | Why Vortex |
|----------|------------|
| DuckDB-centric workflows | Native extension support |
| Analytical workloads with selective queries | Fast random access |
| Cloud storage with 100ms+ round-trip latency | Efficient read patterns |
| Exploring new technologies | Stay current with format evolution |

### When to Stay with Parquet

| Scenario | Why Parquet |
|----------|-------------|
| Cross-platform benchmarks | Universal support |
| Production stability | 10+ years of battle-testing |
| Cloud data warehouses | No Vortex support on Snowflake, Databricks |
| Ecosystem tooling | Most tools expect Parquet |

## Maturity Considerations

Vortex is in Incubation stage:

- API may change before 1.0 release
- Extension compatibility requires attention
- Community smaller than Parquet ecosystem
- Documentation still evolving

For production benchmarks, we recommend Parquet. For exploration and DuckDB-specific testing, Vortex is worth trying.

## BenchBox Usage

### Installation

```bash
# Install vortex Python library
uv add vortex-data
```

### Running Benchmarks

```bash
# Convert data to Vortex format
benchbox convert --input ./data --format vortex

# Run benchmark with Vortex on DuckDB
benchbox run --platform duckdb --benchmark tpch --table-format vortex --scale 1
```

### Reading Vortex Files

```python
# Python vortex library
import vortex
array = vortex.io.read('customer.vortex')
table = array.to_arrow()

# DuckDB (requires extension)
conn.execute("INSTALL vortex; LOAD vortex;")
conn.execute("SELECT * FROM read_vortex('customer.vortex')")
```

## See Also

- [Table Format Guides](index.md): Overview of all formats
- [Format Conversion Reference](../../advanced/format-conversion.md): CLI commands for format conversion
- [Parquet Deep Dive](parquet-deep-dive.md): The established alternative <!-- content-ok: cliche -->
- [Compression Guide](../compression.md): Data compression strategies
