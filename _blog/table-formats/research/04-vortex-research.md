# Vortex Research Notes

*Compiled: 2026-01-31*

## Overview

Vortex is a columnar file format with composable encodings, designed for high-performance data processing. Originally developed by SpiralDB, it was donated to the Linux Foundation AI & Data Foundation in August 2025 as an Incubation-stage project.

## Key Sources

- [Vortex GitHub Repository](https://github.com/vortex-data/vortex)
- [Vortex Official Website](https://vortex.dev/)
- [Vortex File Format Specification](https://docs.vortex.dev/specs/file-format)
- [LF AI & Data Foundation Announcement](https://www.linuxfoundation.org/press/lf-ai-data-foundation-hosts-vortex-project-to-power-high-performance-data-access-for-ai-and-analytics)
- [SIGMOD 2024 Paper](https://dl.acm.org/doi/10.1145/3626246.3653396)

## Performance Claims

From the official Vortex documentation:

| Metric | Improvement vs Parquet |
|--------|----------------------|
| Random access | 100x faster |
| Scan operations | 10-20x faster |
| Write performance | 5x faster |
| Compression ratio | Similar |

**External Validation:**
- Technical University of Munich's (TUM) database group recognized Vortex for its adaptive compression approach
- Microsoft demonstrated 30% runtime reductions when running traditional Spark workloads with Vortex in Apache Iceberg

## Design Philosophy

Unlike Apache Parquet and other formats built for structured analytics on CPUs, Vortex is optimized for:
- Multimodal data
- Wide schemas
- GPU-based training workloads
- High-performance reads from cloud object stores (S3, GCS)

**Core Insight**: No single compression scheme is best for all data types and distributions. Vortex operates like a framework for creating highly specialized, compressed columnar representations.

## Technical Architecture

### File Structure

```
file.vortex
├── Magic number: VTXF (4 bytes)
├── Binary data segments (with optional padding)
├── Postscript (max 65,528 bytes)
│   ├── DType segment (schema)
│   ├── Layout segment
│   ├── Statistics segment
│   └── Footer segment
├── Version tag (16-bit)
├── Postscript length (16-bit)
└── Magic number: VTXF (4 bytes)
```

### Compression Support

- None
- LZ4
- ZLib
- ZStd

Each segment can specify its own compression independently.

### Performance Optimizations

- **Cloud storage efficiency**: Minimal read overhead for partial column/row access
- **Two round-trip reads**: Postscript design ensures complete footer loads within 64KB
- **Composable encodings**: Rich library of type-aware compressors (FSST for strings, ALP for integers) that can be chained

### Compatibility Guarantees

Backward compatibility guaranteed from version 0.36.0 onwards. Any older Vortex file can be read by newer versions.

## Industry Support

Contributors and supporters include:
- Microsoft
- Snowflake
- Palantir
- Linux Foundation

## BenchBox Integration Status

### Supported Platforms

| Platform | Support Level | Notes |
|----------|--------------|-------|
| DuckDB | Extension | Requires vortex extension (`INSTALL vortex; LOAD vortex;`) |
| DataFusion | Experimental | Native support in progress |

### Implementation Details

**Format Capabilities** (`benchbox/platforms/base/format_capabilities.py`):
```python
VORTEX_CAPABILITY = FormatCapability(
    format_name="vortex",
    display_name="Vortex",
    file_extension=".vortex",
    features={
        "compression",
        "column_pruning",
        "predicate_pushdown",
        "statistics",
    },
    supported_platforms={
        "duckdb": SupportLevel.EXTENSION,
        "datafusion": SupportLevel.EXPERIMENTAL,
    },
)
```

**Data Loading Handlers**:
1. `VortexFileHandler`: Generic handler using Python vortex library
2. `DuckDBVortexHandler`: Optimized handler using DuckDB's native extension

**Format Preferences**:
```python
PLATFORM_FORMAT_PREFERENCES = {
    "duckdb": ["parquet", "vortex", "delta", "tbl", "csv"],
    "datafusion": ["parquet", "vortex", "tbl", "csv"],
}
```

### CLI Commands

```bash
# Convert to Vortex
benchbox convert --input ./data --format vortex
benchbox convert --input ./data --format vortex --compression zstd

# Run with Vortex on DuckDB
benchbox run --platform duckdb --benchmark tpch --scale 0.01
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

## Comparison with Parquet

| Aspect | Parquet | Vortex |
|--------|---------|--------|
| Maturity | Production (10+ years) | Incubation (2025) |
| Ecosystem | Universal | DuckDB, DataFusion |
| Random access | Standard | 100x faster (claimed) |
| Scan performance | Standard | 10-20x faster (claimed) |
| Compression | Good | Similar |
| GPU support | Limited | Designed for |
| Encoding | Fixed schemes | Composable, type-aware |

## Benchmarking Considerations

### What to Test

1. **Storage size comparison**: Vortex vs Parquet at SF1, SF10
2. **Query performance**: TPC-H full suite
3. **Query-specific behavior**: Which queries benefit most from Vortex?
4. **Compression levels**: Impact of different compression algorithms
5. **Random access patterns**: Q2, Q11 (supplier lookups)

### Expected Findings

Based on Vortex design goals:
- Simple aggregations (Q1, Q6) should show good scan performance
- Join-heavy queries may benefit from faster random access
- Wide table queries should benefit from column pruning
- Compression ratios should be similar to well-tuned Parquet

### Platform Considerations

- **DuckDB**: Extension must be installed, may have version compatibility issues
- **DataFusion**: Experimental support, may lack some features
- **Other platforms**: No Vortex support (yet)

## Open Questions

1. How does Vortex perform with TPC-DS wide tables vs TPC-H?
2. What is the extension installation overhead in DuckDB?
3. How stable is the DataFusion experimental support?
4. When will other platforms add Vortex support?

## Upcoming Events

- KubeCon + CloudNativeCon Europe 2026: March 23-26, Amsterdam
- Expected Vortex project updates at LF AI & Data events

---

*Last updated: 2026-01-31*
