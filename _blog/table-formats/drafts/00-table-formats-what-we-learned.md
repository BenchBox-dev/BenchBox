---
blogpost: true
date: [TODO: set on publication]
author: Joe Harris
series: table-formats
post_number: 0
type: methodology-guide
tags: benchbox, benchmarking, methodology, table-formats, parquet, delta-lake, ducklake, iceberg, vortex
meta_description: "Format choice affects benchmark validity and storage cost. We measured TPC-H SF1 storage across all five formats, Parquet, Delta Lake, DuckLake, Iceberg, and Vortex, with BenchBox."
---

# Table Formats for Benchmarking: What We Learned

> The data format sitting quietly in the background affects everything from storage costs to query performance to whether your results are reproducible across platforms.

**TL;DR**: Format choice is a benchmark design decision, not a storage optimization. At TPC-H SF1, Parquet (zstd:3, 232 MB), Vortex (274 MB), Iceberg (snappy, 311 MB), Delta Lake (snappy, 305 MB), and DuckLake (snappy, 309 MB) all store the same data; the differences are compression defaults, metadata overhead, and setup complexity. BenchBox supports all five formats via `benchbox convert`.

---

## Introduction

When comparing database performance, format choice introduces variables that are easy to overlook. Platform A loads CSV. Platform B loads Parquet. Platform B wins by 3x on query performance. Is Platform B faster, or is it benefiting from columnar storage and predicate pushdown?

We built format support into BenchBox because we kept running into that question: Can I compare DuckDB on Parquet against Databricks on Delta Lake fairly? What does format conversion actually cost? When does Vortex's performance advantage become visible?

This post summarizes what we found. For the full details, see our [Table Format Guides](/docs/guides/table-formats/).

---

## The format landscape

### File formats vs table formats

**File formats** (Parquet, Vortex) define how data is serialized to bytes. Each file is self-contained with no external state or metadata management.

**Table formats** (Delta Lake, Iceberg, DuckLake) build on file formats, typically Parquet. They add transaction logs for ACID guarantees, schema evolution, time travel, and compaction. The "table" is the collection of files plus metadata.

| Format | Type | Key Strength | Best For |
| --- | --- | --- | --- |
| Parquet | File | Universal support | Baseline, portability |
| Vortex | File | Composable encodings, performance | DuckDB/DataFusion local workloads |
| Delta Lake | Table | ACID, time travel | Databricks and Spark ecosystems |
| Iceberg | Table | Multi-engine independence | Cross-platform lakehouses |
| DuckLake | Table | DuckDB-native ACID | Local development, DuckDB workflows |

For benchmarking, the distinction matters:

- File formats are simpler to set up and more portable across platforms
- Table formats add metadata overhead but enable production-like conditions

### When format choice matters

**Format matters when:**

- Comparing across platforms (format support varies by platform)
- Measuring storage costs (compression ratios can differ significantly)
- Testing query features (predicate pushdown, statistics-based pruning)
- Running at large scale factors where I/O time dominates

**Format matters less when:**

- Comparing queries on the same platform with the same format
- Running at small scale factors where compute time dominates
- Testing CPU-bound operations like complex joins

### Platform compatibility

| Platform | Parquet | Vortex | Delta Lake | Iceberg | DuckLake |
| --- | --- | --- | --- | --- | --- |
| DuckDB | Native | Extension | Extension | Experimental | Native |
| Spark | Native | - | Native | Native | - |
| Databricks | Native | - | Native | Native | - |
| Snowflake | Native | - | - | Native | - |
| BigQuery | External | - | - | External | - |
| Polars | Native | - | Native | - | - |
| DataFusion | Native | Experimental | - | - | - |

---

## BenchBox format workflow

BenchBox separates data generation from format conversion. Generate once, convert to any supported format:

```bash
# Step 1: generate TPC-H data
$ benchbox run --platform duckdb --benchmark tpch --scale 1 --phases generate

# Step 2: convert to target format
$ benchbox convert --input ./benchmark_runs/tpch_sf1 --format parquet --compression zstd
$ benchbox convert --input ./benchmark_runs/tpch_sf1 --format delta --compression zstd
$ benchbox convert --input ./benchmark_runs/tpch_sf1 --format ducklake
$ benchbox convert --input ./benchmark_runs/tpch_sf1 --format iceberg
$ benchbox convert --input ./benchmark_runs/tpch_sf1 --format vortex
```

Compression options: `snappy` (default, fast), `zstd` (best ratio, moderate speed), `gzip` (compatible, slower), `none` (fastest write). Vortex uses its own composable encoding and does not accept a compression parameter.

---

## Key findings

### Storage efficiency

We exported TPC-H SF1 from DuckDB to each format and measured output size against uncompressed Parquet as a baseline.

| Format | SF1 Size | Ratio vs Uncompressed | Notes |
| --- | ---: | ---: | --- |
| Parquet (none) | 551 MB | 1.0x | Baseline (columnar, no compression) |
| Parquet (zstd:3) | 232 MB | 0.42x | BenchBox default |
| Vortex | 274 MB | 0.50x | Composable encodings, DuckDB extension |
| Iceberg (snappy) | 311 MB | 0.56x | Parquet data + metadata manifests; pyiceberg with local SQLite catalog |
| Delta Lake (snappy) | 305 MB | 0.55x | Parquet data + transaction log; delta-rs default |
| DuckLake (snappy) | 309 MB | 0.56x | 5 MB SQLite catalog + 304 MB Parquet data |

The three table formats (Delta Lake, Iceberg, DuckLake) all store snappy-compressed Parquet data files. The metadata overhead (transaction log, SQLite catalog, or Iceberg manifests) adds less than 5 MB. Converting with explicit `zstd` compression brings them closer to Parquet (zstd:3): Iceberg (zstd) reaches 246 MB, while Delta Lake (zstd) stays at 305 MB due to delta-rs writer defaults. Vortex uses its own composable encoding scheme and reaches 274 MB without a separate compression step.

### Parquet compression options

We exported TPC-H SF1 from DuckDB to Parquet with each compression codec:

| Compression | SF1 Size | Ratio vs None | Notes |
| --- | ---: | ---: | --- |
| None | 551 MB | 1.0x | Fastest write |
| Snappy | 308 MB | 0.56x | Fast read/write |
| LZ4 | 318 MB | 0.58x | Similar to snappy |
| Zstd:3 | 232 MB | 0.42x | BenchBox default |
| Zstd:9 | 220 MB | 0.40x | Marginal gain over :3 at SF1 |

Zstd provides the best compression ratio. At SF1, the difference between zstd:3 and zstd:9 is small (232 vs 220 MB). At SF10 and above, zstd:9 pulls ahead more noticeably. LZ4 runs slightly larger than Snappy in this measurement (318 vs 308 MB); the two are generally comparable and results can vary with row group configuration and data characteristics. The compression advantage over Snappy and LZ4 becomes more significant at large scale factors where I/O time dominates.

Note on uncompressed Parquet: at 551 MB, uncompressed Parquet is already ~45% smaller than the raw TBL pipe-delimited format (~1 GB). The columnar layout and dictionary encoding account for the size reduction before any compression is applied.

For details, see [Parquet Deep Dive: Compression](/docs/guides/table-formats/parquet-deep-dive/#compression-in-parquet).

### Delta Lake: OPTIMIZE and production conditions

Delta Lake's transaction log adds small file overhead at load time. Running `OPTIMIZE` compacts small files; Z-ORDER clusters data by specified columns, which benefits queries with range filters. These operations require running on Databricks or a Delta-compatible engine with write support. We measured Delta storage locally (305 MB at SF1 with snappy) but did not run performance tuning benchmarks, which require Databricks access.

For methodology and expected behavior, see [Delta Lake Guide: Performance Considerations](/docs/guides/table-formats/delta-lake-guide/#performance-considerations).

### Iceberg: local catalog and cross-engine comparisons

Iceberg's key value proposition for benchmarking is engine independence: write data once, query from any supported engine. Performance differences across engines reflect engine characteristics rather than format differences.

BenchBox uses pyiceberg with a local SQLite-backed SQL catalog, so no external catalog service (AWS Glue, Nessie) is needed for local benchmarking. At SF1, Iceberg (snappy) produces 311 MB, comparable to Delta Lake and DuckLake. With zstd compression, Iceberg reaches 246 MB. The metadata overhead (manifest files) is minimal: ~20 KB per table.

For production multi-engine workflows with shared catalogs, see [Apache Iceberg Guide: Multi-Engine Workflows](/docs/guides/table-formats/iceberg-guide/#multi-engine-workflows).

### Vortex: composable encodings

Vortex uses composable encodings rather than a single compression codec, aiming for 10-20x faster scans and 100x faster random access compared to Parquet (source: [Vortex documentation](https://vortex.dev/), [SIGMOD 2024 paper](https://dl.acm.org/doi/10.1145/3626246.3653396)).

BenchBox supports Vortex conversion via the DuckDB vortex extension or Python `vortex-data` bindings. At SF1, Vortex produces 274 MB, smaller than snappy-compressed Parquet (308 MB) but larger than zstd-compressed Parquet (232 MB). The difference reflects Vortex's encoding strategy: it applies column-specific encodings (dictionary, run-length, frame-of-reference) automatically rather than using a general-purpose compressor.

Vortex's claimed scan speed improvements are most relevant at large scale factors and with cloud storage latency (S3, GCS) where I/O is the bottleneck. At SF1 with data in memory, format differences in query time are expected to be minimal. DataFusion support exists but is classified as experimental.

For details, see [Vortex Guide: Maturity Considerations](/docs/guides/table-formats/vortex-guide/#maturity-considerations).

---

## Decision guide

| Scenario | Recommended Format | Reason |
| --- | --- | --- |
| Most benchmarks | Parquet | Universal support, well-understood behavior |
| Databricks benchmarks | Delta Lake | Native optimization, production-realistic conditions |
| Multi-engine comparisons | Iceberg | Engine independence, fair cross-platform results |
| DuckDB local development | DuckLake | Native ACID without cloud dependencies |
| DuckDB scan-heavy workloads | Vortex | Composable encodings, optimized for analytical scans |

In practice, these paths complement each other. Parquet is the right default for portability. When you need production-like conditions or cross-engine comparability, the table formats add value at the cost of setup complexity.

---

## Try it yourself

```bash
# Generate TPC-H SF1 data
$ benchbox run --platform duckdb --benchmark tpch --scale 1 --phases generate

# Convert to target format
$ benchbox convert --input ./benchmark_runs/tpch_sf1 --format parquet --compression zstd
$ benchbox convert --input ./benchmark_runs/tpch_sf1 --format delta --compression zstd
$ benchbox convert --input ./benchmark_runs/tpch_sf1 --format ducklake
$ benchbox convert --input ./benchmark_runs/tpch_sf1 --format iceberg --compression zstd
$ benchbox convert --input ./benchmark_runs/tpch_sf1 --format vortex

# Run queries against the converted data
$ benchbox run --platform duckdb --benchmark tpch --scale 1 --phases load,power \
    --table-mode external
```

---

## What we learned

Format choice is a benchmark design decision, not just a storage optimization.

Using Parquet for a multi-platform comparison and raw TBL for another is not an apples-to-apples test. The format itself determines whether predicate pushdown is available, how much I/O the query engine performs, and whether the results are reproducible across different engines.

BenchBox's convert workflow makes it straightforward to hold format constant across platforms, which is the right baseline for most benchmark comparisons.

---

## Methodology

All local measurements in this post were run with BenchBox or directly via DuckDB Python API.

- **Hardware**: Apple Silicon Mac mini class host, 10 CPU cores, 16 GB RAM, local SSD
- **DuckDB**: 1.4.3
- **BenchBox**: 0.1.4
- **Python**: 3.11, `deltalake` 1.3.2, `pyiceberg` 0.10.0, `vortex-data` 0.61.0
- **Benchmark**: TPC-H SF1
- **Methodology**: Format storage is deterministic (single export per format). Compression codec comparisons use identical source data exported from the same DuckDB database. Iceberg uses a local SQLite-backed pyiceberg catalog (no external service).
- **Limitations**: Local results at SF1 are I/O-light and may not reflect large-scale behavior. Delta performance tuning (OPTIMIZE, Z-ORDER) requires Databricks access and is not covered here. Cross-engine Iceberg comparisons require shared catalog infrastructure.

---

## References

1. [Apache Parquet](https://parquet.apache.org/)
2. [Delta Lake](https://delta.io/)
3. [Apache Iceberg](https://iceberg.apache.org/)
4. [DuckLake](https://duckdb.org/2025/06/03/ducklake.html)
5. [Vortex](https://vortex.dev/) / [Vortex GitHub](https://github.com/vortex-data/vortex)
6. [Vortex SIGMOD 2024 paper](https://dl.acm.org/doi/10.1145/3626246.3653396)
7. [BenchBox GitHub](https://github.com/joeharris76/BenchBox)
8. [BenchBox Table Format Guides](/docs/guides/table-formats/)
9. [BenchBox Format Conversion Reference](/docs/advanced/format-conversion/)

---

*Status: Published 2026-03-04*
