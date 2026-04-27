---
blogpost: true
date: [TODO: set on publication]
author: Joe Harris
series: table-formats
post_number: 1
type: methodology-guide
tags: benchbox, benchmarking, methodology, table-formats, parquet, compression, columnar
meta_description: "Parquet compression affects benchmark storage cost and reproducibility. What benchmarkers need to know about codecs, row groups, and when tuning matters."
---

# Parquet basics: The foundation of modern analytics

> At TPC-H SF1, uncompressed Parquet is already 40% smaller than raw pipe-delimited source files. Understanding why, and how to go further, determines whether your benchmark is measuring the database or the format.

**TL;DR**: Parquet's columnar layout enables efficient analytical queries through column pruning and predicate pushdown. BenchBox defaults to Zstd compression (230 MB at SF1 vs 604 MB uncompressed). Row group size rarely needs adjustment. Parquet's universal support makes it the right default for cross-platform benchmarks.

---

## Introduction

Apache Parquet has become the universal language of analytical data.[^1] Created in 2013 as a collaboration between Twitter and Cloudera, it's now an Apache top-level project with support across virtually every analytics platform.

We made Parquet the default format in BenchBox because it's the one format we can count on everywhere. DuckDB, Spark, Snowflake, BigQuery, Polars, DataFusion: they all read Parquet natively. This universality matters when you're running the same benchmark across platforms.

But using Parquet effectively requires understanding a few core concepts. This post covers what benchmarkers need to know: row groups, column chunks, compression options, and when (rarely) to tune these settings.

---

## Why columnar matters for analytics

Before diving into Parquet specifics, here is why columnar storage helps analytical workloads.

### Row vs. columnar storage

| Storage Type | Data Layout | Best For |
|--------------|-------------|----------|
| Row-oriented | All columns for row 1, then all columns for row 2... | OLTP, full-row access |
| Columnar | All values for column 1, then all values for column 2... | OLAP, analytical queries |

Analytical queries typically read few columns but many rows:

```sql
-- Only needs 'revenue' column, but all 6M rows
SELECT SUM(l_extendedprice) FROM lineitem;

-- Only needs 4 columns out of 16
SELECT l_returnflag, l_linestatus, SUM(l_quantity)
FROM lineitem
GROUP BY l_returnflag, l_linestatus;
```

With row storage, the query reads entire rows, including columns it doesn't need. With columnar storage, it reads only the columns requested.

### Parquet vs. CSV for benchmarking

| Aspect | CSV | Parquet |
|--------|-----|---------|
| File size | Large (text encoding) | 3-5x smaller (binary + compression) |
| Parsing | Required (expensive) | Native types (fast) |
| Column pruning | No (read all columns) | Yes (read only needed) |
| Predicate pushdown | No | Yes (skip irrelevant data) |
| Schema | External | Embedded in file |

BenchBox generates TPC-H data in TBL format (pipe-delimited text), then loads it into the target platform's native storage. For Parquet-based workflows, the `benchbox convert` command exports to Parquet explicitly. The numbers below come from exporting to each codec from the same DuckDB source database.

---

## Parquet concepts for benchmarkers

### Row groups

Parquet files are divided into row groups, chunks of rows stored together. Each row group is independently readable, enabling parallel processing.

```
lineitem.parquet
├── Row Group 0 (rows 0-999,999)
│   ├── Column: l_orderkey (INT64, compressed)
│   ├── Column: l_quantity (DECIMAL, compressed)
│   └── Column: l_extendedprice (DECIMAL, compressed)
├── Row Group 1 (rows 1,000,000-1,999,999)
│   └── ...
└── Footer (schema, statistics, offsets)
```

**Why row groups matter for benchmarks:**

**Parallelism**: Each row group can be processed independently. More row groups enable more parallel tasks, up to a point.

**Memory**: Larger row groups require more memory to process. For memory-constrained environments, smaller row groups help.

**Statistics**: Parquet stores min/max values per column per row group. Queries with range filters can skip row groups entirely.

**BenchBox default**: 1 million rows per row group (the Parquet default[^2]). This works well for most benchmark scenarios.

### Column chunks

Within each row group, data is stored by column. This is where columnar benefits appear.

**Column pruning**: A query selecting 4 columns from a 16-column table reads 25% of the data.

**Better compression**: Similar values group together. A column of dates compresses better than mixed-type rows.

**Vectorized processing**: Modern query engines process columns in batches (vectors), exploiting CPU SIMD instructions.

### Encodings

Before compression, Parquet *encodes* values to reduce their size based on data patterns. The most important encoding for benchmarking is dictionary encoding: Parquet builds a lookup table of unique values and stores compact integer indices instead of repeated values. For TPC-H's `l_returnflag` column (3 distinct values across millions of rows), this reduces storage dramatically. When a column has too many unique values (like `l_comment`), dictionary encoding falls back to PLAIN (raw values back-to-back).

Other encodings are applied automatically by PyArrow based on data type: RLE for booleans, delta encoding for sorted integers and strings, and byte stream split for floating-point data. These encodings compound with compression: a well-encoded column compresses even further. PyArrow (which BenchBox uses for Parquet writes)[^3] enables dictionary encoding by default (`use_dictionary=True`) and exposes `dictionary_columns` and `skip_dictionary_columns` for per-column control.

### Compression options

Parquet supports several compression algorithms:

| Algorithm | Speed | Ratio | When to use |
|-----------|-------|-------|-------------|
| Snappy | Fastest | Good | Low-latency queries, interactive workloads |
| LZ4 | Fast | Good | Balance of speed and compression |
| Zstd | Medium | Best | Storage efficiency, batch workloads |
| Gzip | Slow | Good | Compatibility with older tools |

**BenchBox recommendation**: Zstd for most benchmarks. It provides the best compression ratio with acceptable decompression speed. At scale factor 10 and above, smaller files mean less I/O, which often outweighs the decompression cost.

### Statistics

Parquet stores statistics in the file footer:

- **Min/max values** per column per row group
- **Null counts**
- **Distinct counts** (optional)
- **Bloom filters** (optional, for string lookups)

**How statistics affect benchmarks:**

```sql
-- Query with range filter
SELECT * FROM lineitem WHERE l_shipdate > '1998-01-01';
```

If a row group's max l_shipdate is '1997-12-31', the query engine skips that entire row group. This predicate pushdown happens automatically based on statistics.

Statistics overhead is minimal (less than 1% of file size) but the query optimization benefits can be substantial.

---

## BenchBox Parquet configuration

### Default settings

BenchBox uses sensible defaults optimized for benchmark reproducibility:

```python
PARQUET_DEFAULTS = {
    "compression": "zstd",
    "compression_level": 3,  # Balance of speed and ratio
    "row_group_size": 1_000_000,  # 1M rows
    "page_size": 1_048_576,  # 1MB
}
```

These defaults work well for TPC-H at scale factors 1-100. You rarely need to change them.

### Compression options

```bash
# Default (Zstd level 3)
benchbox run --platform duckdb --benchmark tpch --scale 1

# Higher compression (smaller files, slower write)
benchbox run --platform duckdb --benchmark tpch --compression zstd:9

# Faster compression (larger files, faster write)
benchbox run --platform duckdb --benchmark tpch --compression snappy

# No compression (debugging, baseline)
benchbox run --platform duckdb --benchmark tpch --compression none
```

### When to adjust compression

| Priority | Recommended | Reason |
|----------|-------------|--------|
| Storage cost | Zstd:9 | Smallest files |
| Query speed | Snappy | Fastest decompression |
| Balanced | Zstd:3 | BenchBox default |
| Debugging | None | No decompression overhead |

For most benchmarks, the default Zstd:3 works well. Higher compression levels (Zstd:9) save storage but add write time. Snappy trades ~20% larger files for faster decompression.

### Platform-specific implementations

Each platform has its own Parquet reader:

| Platform | Implementation | Notes |
|----------|----------------|-------|
| DuckDB | Native | Fast, feature-complete |
| Polars | Native (Rust) | Excellent performance |
| Spark | Hadoop Parquet | Mature, widely tested |
| DataFusion | Arrow Parquet | Good performance |
| Snowflake | Proprietary | Optimized for internal use |

BenchBox generates Parquet files using PyArrow, which produces standard-compliant files readable by all platforms. We've verified that the same Parquet file produces identical results on DuckDB[^4], Polars, and Spark.

### Format versions

Parquet has two version concepts worth knowing about. The *file format version* controls which logical types are available (BenchBox uses version 2.6, the PyArrow default, which supports all modern types including high-precision decimals). The *data page version* controls how values are serialized within pages. Version 1.0 (the default) stores definition/repetition levels alongside values in a single compressed block. Version 2.0 separates them, enabling page-level skipping without decompression.

BenchBox inherits PyArrow's defaults (file version 2.6, data page version 1.0) without setting them explicitly. These defaults prioritize compatibility across all supported platforms. For standard TPC-H and TPC-DS benchmarks, the defaults work well.

---

## Compression comparison

We exported TPC-H SF1 from DuckDB to Parquet with each compression codec and measured output file size.

### Storage size

| Compression | SF1 Size | Ratio vs None |
|-------------|----------|---------------|
| None | 604 MB | 1.0x |
| Snappy | 319 MB | 0.53x |
| LZ4 | 329 MB | 0.54x |
| Zstd:3 | 230 MB | 0.38x |
| Zstd:9 | 230 MB | 0.38x |

Zstd provides the best compression ratio. At SF1, Zstd:3 and Zstd:9 produce identical file sizes because the dataset is small enough that the extra compression work runs out of entropy to exploit. LZ4 runs slightly larger than Snappy (329 vs 319 MB); the two are generally comparable, with results varying by row group configuration and data characteristics.

Note: uncompressed Parquet at 604 MB is already 40% smaller than the raw TBL pipe-delimited source (~1 GB). The columnar layout and dictionary encoding account for that reduction before any compression is applied.

At SF1, the differences in query time are minimal since the data fits in memory.

### Query performance

At SF1, compression differences are within measurement noise because data fits in cache. At larger scale factors (SF10+), compression matters more:

- I/O-bound queries benefit from smaller files
- CPU-bound queries see slight overhead from decompression
- The net effect depends on your storage speed (SSD vs. cloud storage)

**Key finding**: For local SSD benchmarks at SF1-10, compression choice matters less than you might expect. For cloud storage benchmarks, smaller files (Zstd) usually win because network latency dominates.

---

## Best practices

### Recommended settings for benchmarking

```bash
# Standard benchmark (reproducible, efficient)
benchbox run --platform duckdb --benchmark tpch --scale 10 --compression zstd:3

# Storage-focused comparison
benchbox run --platform duckdb --benchmark tpch --scale 10 --compression zstd:9

# Performance baseline (measure decompression impact)
benchbox run --platform duckdb --benchmark tpch --scale 10 --compression none
```

### When to adjust row group size

**Increase row group size when:**
- Running at SF100+ (reduce footer overhead)
- Using cloud storage (fewer S3/GCS GET requests)
- Memory is not constrained

**Decrease row group size when:**
- Maximizing parallelism on many-core systems
- Running in memory-constrained environments
- Debugging query execution patterns

BenchBox uses the 1M row default, which works for most scenarios. Custom row group sizes require manual data generation with PyArrow.

### Common mistakes to avoid

**1. Using CSV for benchmarks**

CSV parsing adds overhead that skews results. A "fast" platform might just be a better CSV parser, not a better query engine.

**2. Ignoring compression settings**

Different tools use different defaults. DuckDB might generate Snappy, while Spark uses Zstd. Specify compression explicitly for reproducible comparisons.

**3. Comparing across formats**

Parquet vs. CSV isn't a fair comparison. If you're evaluating formats, compare Parquet to Parquet with different settings, or to other columnar formats like ORC (or Vortex, when it becomes available).

**4. Forgetting about statistics**

Queries that filter on columns with good min/max separation benefit from predicate pushdown. If your benchmark doesn't include filtering queries, you're missing a key Parquet optimization.

---

## Conclusion

The right compression choice depends on your storage medium and scale factor, not the algorithm's reputation. At SF1 on local SSD, the differences between codecs are within measurement noise; at SF10+ on cloud storage, Zstd's smaller file sizes reduce I/O meaningfully. The BenchBox default (Zstd:3) lands in the right place for most runs.

More important than codec choice is consistency: if two platforms use different compression defaults, you're no longer comparing query engines. The overhead that matters most in cross-platform benchmarks isn't file size; it's whether format and compression settings are identical across every platform you're comparing.

---

## References

[^1]: [Apache Parquet Documentation](https://parquet.apache.org/docs/) - Apache Software Foundation
[^2]: [Parquet Format Specification](https://github.com/apache/parquet-format) - GitHub
[^3]: [PyArrow Parquet Documentation](https://arrow.apache.org/docs/python/parquet.html) - Apache Arrow
[^4]: [DuckDB Parquet Support](https://duckdb.org/docs/data/parquet) - DuckDB Documentation
[^5]: TPC-H SF1 exported from DuckDB 1.4.3 to Parquet via PyArrow. Apple Silicon, 16 GB RAM, local SSD. Storage measurements are deterministic single exports. March 2026.

---

*Questions or feedback? [Open an issue](https://github.com/joeharris76/BenchBox/issues) or join the discussion.*
