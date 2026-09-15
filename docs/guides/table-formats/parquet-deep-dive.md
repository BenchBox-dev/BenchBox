# Parquet Deep Dive <!-- content-ok: cliche -->

```{tags} guide, formats, parquet
```

Apache Parquet is the de facto standard for analytical data storage. Understanding row groups, column chunks, and compression options helps you run better benchmarks.

## Overview

Apache Parquet has become the universal language of analytical data. Created in 2013 as a collaboration between Twitter and Cloudera, it's now an Apache top-level project with support across virtually every analytics platform.

We made Parquet the default format in BenchBox because it's the one format we can count on everywhere. DuckDB, Spark, Snowflake, BigQuery, Polars, DataFusion: they all read Parquet natively. This universality matters when you're running the same benchmark across platforms.

But using Parquet effectively requires understanding a few core concepts. This guide covers what benchmarkers need to know: row groups, column chunks, encodings, compression, and format versions.

## Why Columnar Matters for Analytics

Before diving into Parquet specifics, let's understand why columnar storage helps analytical workloads.

### Row vs Columnar Storage

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

### Analytical Query Patterns

Parquet enables several optimizations for analytical queries:

- **Column pruning**: Read only required columns, skip the rest
- **Predicate pushdown**: Apply filters at the storage layer before loading into memory
- **Better compression**: Similar values group together within columns
- **Vectorized processing**: Process columns in batches using CPU SIMD instructions

## Parquet File Structure

### Row Groups

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

**BenchBox default**: 1 million rows per row group (the Parquet default). This works well for most benchmark scenarios.

### Column Chunks

Within each row group, data is stored by column. This is where columnar benefits appear.

**Column pruning**: A query selecting 4 columns from a 16-column table reads 25% of the data.

**Better compression**: Similar values group together. A column of dates compresses better than mixed-type rows.

**Vectorized processing**: Modern query engines process columns in batches (vectors), exploiting CPU SIMD instructions.

### Data Pages and Encodings

Column chunks are further divided into data pages (typically ~1MB each). Pages are where Parquet's two-stage storage pipeline operates: values are first *encoded*, then *compressed*. Understanding this distinction matters because encoding and compression serve different purposes.

```
Column Chunk
├── Data Page 0
│   ├── 1. Encode values (dictionary, delta, RLE, or plain)
│   └── 2. Compress encoded bytes (zstd, snappy, etc.)
├── Data Page 1
│   └── ...
└── Dictionary Page (optional, one per column chunk)
    └── Unique values for dictionary-encoded pages
```

Encoding transforms values into a more compact representation based on data patterns. Compression then finds redundancy in the encoded bytes. These two stages compound: a well-encoded column compresses even further.

#### Dictionary Encoding

Dictionary encoding is the most impactful encoding for benchmarking. Parquet builds a lookup table of unique values and stores integer indices instead of repeated values. For columns with few distinct values, this dramatically reduces storage.

Consider TPC-H's `lineitem` table:

| Column | Distinct Values | Dictionary Effective? | Why |
|--------|-----------------|----------------------|-----|
| l_returnflag | 3 ('A', 'F', 'N') | Yes, major savings | 3 values replace millions of repeated strings |
| l_shipmode | 7 | Yes | Small dictionary, high repetition |
| l_orderkey | ~1.5M (at SF1) | No | Dictionary would be as large as the data |
| l_comment | ~4.6M (at SF1) | No | Falls back to PLAIN encoding |

When a column's dictionary grows too large (exceeds the page size threshold), PyArrow automatically falls back to PLAIN encoding for that column. This fallback is safe but adds write overhead for the failed dictionary attempt.

BenchBox enables dictionary encoding by default (`use_dictionary=True`). For fine-grained control, the write configuration supports per-column overrides:

```python
DataFrameWriteConfiguration(
    dictionary_columns=["l_returnflag", "l_shipmode"],    # Force dictionary
    skip_dictionary_columns=["l_comment", "l_orderkey"],  # Skip dictionary
)
```

#### Other Parquet Encodings

PyArrow selects encodings automatically based on data type. Dictionary encoding is the one encoding worth controlling explicitly. The others are applied transparently:

| Encoding | Types | When Used | Benchmarking Impact |
|----------|-------|-----------|---------------------|
| PLAIN | All | Fallback when dictionary is too large | Baseline, no special optimization |
| RLE / Bit-Packing | Boolean, internal levels | Automatic for booleans and repetition/definition levels | Minimal, handled transparently |
| DELTA_BINARY_PACKED | INT32, INT64 | Sorted or sequential integers | Benefits from presorted data (timestamps, keys) |
| DELTA_BYTE_ARRAY | Strings | Sorted strings with common prefixes | Benefits from presorted string columns |
| BYTE_STREAM_SPLIT | FLOAT, DOUBLE | Floating-point columns | Better compression ratios for decimal and float data |

The key insight: encoding effectiveness depends on data ordering. Delta encodings exploit sequential patterns, which is why presorted Parquet files often compress 20-40% smaller than unsorted ones. BenchBox's sorted data generation pipeline takes advantage of this.

### Footer and Statistics

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

## Compression in Parquet

After encoding, Parquet applies compression to each data page. Encoding reduces data volume through structural transformation (dictionary lookups, delta values), while compression finds byte-level patterns in the encoded output. The two stages compound: a dictionary-encoded column of integers compresses much better than the same column stored as raw strings.

> For quick compression settings, see [Format Conversion: Compression Guide](../../advanced/format-conversion.md#compression-guide).

### Algorithm Comparison

Parquet supports several compression algorithms:

| Algorithm | Speed | Ratio | When to use |
|-----------|-------|-------|-------------|
| Snappy | Fastest | Good | Low-latency queries, interactive workloads |
| LZ4 | Fast | Good | Balance of speed and compression |
| Zstd | Medium | Best | Storage efficiency, batch workloads |
| Gzip | Slow | Good | Compatibility with older tools |

**BenchBox recommendation**: Zstd for most benchmarks. It provides the best compression ratio with acceptable decompression speed. At scale factor 10 and above, smaller files mean less I/O, which often outweighs the decompression cost.

### Compression Levels

Zstd supports levels 1-22. Higher levels provide better compression at the cost of slower writes:

| Priority | Recommended | Reason |
|----------|-------------|--------|
| Storage cost | Zstd:9 | Smallest files |
| Query speed | Snappy | Fastest decompression |
| Balanced | Zstd:3 | BenchBox default |
| Debugging | None | No decompression overhead |

For most benchmarks, the default Zstd:3 works well. Higher compression levels (Zstd:9) save storage but add write time. Snappy trades ~20% larger files for faster decompression.

### When to Adjust Compression

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

## Row Group Tuning

### When to Increase Row Group Size

- Running at SF100+ (reduce footer overhead)
- Using cloud storage (fewer S3/GCS GET requests)
- Memory is not constrained

### When to Decrease Row Group Size

- Maximizing parallelism on many-core systems
- Running in memory-constrained environments
- Debugging query execution patterns

BenchBox uses the 1M row default, which works for most scenarios. Custom row group sizes require manual data generation with PyArrow.

## Parquet Versions

Parquet has two separate version concepts that affect compatibility and features. Most benchmarkers never need to change the defaults, but understanding them helps when troubleshooting cross-platform issues.

### File Format Version

The file format version controls which logical types are available. Newer versions add type support without changing the core file structure:

| Version | Key Additions | Compatibility |
|---------|---------------|---------------|
| 1.0 | Original spec, basic types | Maximum (all tools) |
| 2.4 | Nanosecond timestamps, integer logical types | Most modern tools |
| 2.6 | Extended DECIMAL precision, UUID type | Current PyArrow default |

BenchBox inherits PyArrow's default (version 2.6), which supports all modern logical types including the high-precision decimals used in TPC-H. All platforms BenchBox supports (DuckDB, Polars, Spark, Snowflake, DataFusion) handle version 2.6 correctly.

### Data Page Version

Separate from the file format version, the data page version controls how values are serialized within pages:

| Page Version | Behavior | Trade-off |
|--------------|----------|-----------|
| 1.0 | Definition/repetition levels and values compressed together | Maximum compatibility |
| 2.0 | Levels stored separately from values, uncompressed | Enables page-level skipping without decompression |

Data page v2 allows query engines to inspect definition levels (null tracking) and repetition levels (nested data) without decompressing the entire page. This can improve predicate pushdown for nullable columns and deeply nested schemas.

### BenchBox Defaults

BenchBox defaults to file format version 2.6 and data page version 1.0, which prioritize broad compatibility for cross-platform benchmark reproducibility. To enable data page v2, set `data_page_version` in a tuning YAML file:

```yaml
# tuning-v2.yaml
write:
  data_page_version: "2.0"
```

```bash
benchbox run --platform duckdb --benchmark tpch --scale 1 --tuning ./tuning-v2.yaml
```

For standard TPC-H and TPC-DS benchmarks with flat schemas, the defaults work well. Data page v2 is most beneficial for workloads with heavily nullable columns or nested schemas where page-level skipping can avoid unnecessary decompression.

## Best Practices for Benchmarking

### Recommended Settings

```bash
# Standard benchmark (reproducible, efficient)
benchbox run --platform duckdb --benchmark tpch --scale 10 --compression zstd:3

# Storage-focused comparison
benchbox run --platform duckdb --benchmark tpch --scale 10 --compression zstd:9

# Performance baseline (measure decompression impact)
benchbox run --platform duckdb --benchmark tpch --scale 10 --compression none
```

### Common Mistakes to Avoid

**1. Using CSV for benchmarks**

CSV parsing adds overhead that skews results. A "fast" platform might just be a better CSV parser, not a better query engine.

**2. Ignoring compression settings**

Different tools use different defaults. DuckDB might generate Snappy, while Spark uses Zstd. Specify compression explicitly for reproducible comparisons.

**3. Comparing across formats**

Parquet vs CSV isn't a fair comparison. If you're evaluating formats, compare Parquet to Parquet with different settings, or to other columnar formats like ORC or Vortex.

**4. Forgetting about statistics**

Queries that filter on columns with good min/max separation benefit from predicate pushdown. If your benchmark doesn't include filtering queries, you're missing a key Parquet optimization.

**5. Not skipping dictionary encoding for high-cardinality columns**

When dictionary encoding is applied to columns with millions of unique values (like `l_comment`), PyArrow builds a dictionary that exceeds the page size threshold and falls back to PLAIN encoding. The failed dictionary attempt adds write overhead. Use `skip_dictionary_columns` for columns known to have high cardinality.

## See Also

- [Table Format Guides](index.md): Overview of all formats
- [Format Conversion Reference](../../advanced/format-conversion.md): CLI commands for format conversion
- [Compression Guide](../compression.md): Data compression strategies
- [Delta Lake Guide](delta-lake-guide.md): Table format built on Parquet
- [Parquet Format Specification](https://github.com/apache/parquet-format): Official encoding and format details
