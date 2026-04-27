# Post #1: Parquet basics - The foundation of modern analytics

## Metadata

```yaml
title: "Parquet basics: The foundation of modern analytics"
series: table-formats
post_number: 1
date: YYYY-MM-DD
tags: [benchmarking, benchbox, table-formats, parquet, compression, columnar, row-groups]
```

## Thesis

> Parquet is the de facto standard for analytical data storage. Understanding row groups, column chunks, and compression options is essential for meaningful benchmarking.

---

## 1. What is Parquet? (~300 words)

### A brief history

Apache Parquet was created in 2013 as a collaboration between Twitter and Cloudera. It's now an Apache top-level project with universal adoption across the analytics ecosystem.

### Why columnar matters for analytics

| Storage Type | Best For | Example |
|--------------|----------|---------|
| Row-oriented (CSV, JSON) | OLTP, full-row access | `SELECT * FROM users WHERE id = 123` |
| Columnar (Parquet, ORC) | OLAP, analytical queries | `SELECT AVG(revenue) FROM orders` |

Analytical queries typically:
- Read few columns but many rows
- Aggregate, filter, and join
- Benefit from column-level compression and statistics

### Parquet vs. CSV/JSON for benchmarking

| Aspect | CSV/JSON | Parquet |
|--------|----------|---------|
| File size | Large | 2-10x smaller |
| Query performance | Slower (parse overhead) | Faster (native types) |
| Predicate pushdown | No | Yes |
| Column pruning | No | Yes |
| Reproducibility | Parsing variations | Consistent |

BenchBox generates TPC-H data in TBL format (pipe-delimited), then converts to Parquet for benchmarking. This ensures consistent, optimized data across all platforms.

---

## 2. Parquet concepts for benchmarkers (~500 words)

### Row groups

Parquet files are divided into row groups (chunks of rows stored together).

```
parquet_file.parquet
├── Row Group 1 (e.g., rows 0-999,999)
│   ├── Column Chunk: customer_id
│   ├── Column Chunk: name
│   └── Column Chunk: revenue
├── Row Group 2 (e.g., rows 1,000,000-1,999,999)
│   └── ...
└── Footer (schema, statistics)
```

**Why row groups matter for benchmarks:**
- **Parallelism**: Each row group can be read independently
- **Memory**: Larger row groups = more memory during processing
- **Statistics**: Min/max values per row group enable predicate pushdown

**BenchBox default**: 1 million rows per row group (Parquet default)

### Column chunks

Within each row group, data is stored by column.

**Benefits for analytical queries:**
- Read only needed columns (column pruning)
- Apply filters before reading data (predicate pushdown)
- Better compression (similar values together)

**Example query benefits:**
```sql
-- Only reads 'revenue' column chunk
SELECT SUM(revenue) FROM orders;

-- Reads 'customer_id' and 'order_date' chunks, skips row groups where date < 2024
SELECT customer_id FROM orders WHERE order_date > '2024-01-01';
```

### Encodings

Column chunks are divided into data pages (~1MB). Values are first *encoded*, then *compressed*:

- **Dictionary encoding**: Builds a lookup table of unique values, stores integer indices. Effective for low-cardinality columns (l_returnflag, l_shipmode). Falls back to PLAIN for high-cardinality columns (l_comment). BenchBox enables dictionary encoding by default.
- **Other encodings**: PLAIN (fallback), RLE (booleans), DELTA_BINARY_PACKED (sorted integers), DELTA_BYTE_ARRAY (sorted strings), BYTE_STREAM_SPLIT (floats). PyArrow selects these automatically.

### Compression options

| Algorithm | Speed | Ratio | When to use |
|-----------|-------|-------|-------------|
| Snappy | Fastest | Good | Interactive queries, low-latency |
| LZ4 | Fast | Good | Balance of speed and compression |
| Zstd | Medium | Best | Storage efficiency, batch workloads |
| Gzip | Slow | Good | Compatibility with older tools |

**BenchBox recommendation**: Zstd for most benchmarks (best compression, acceptable speed)

### Statistics

Parquet stores statistics in the file footer:
- **Min/max values** per column per row group
- **Null counts**
- **Distinct counts** (optional)
- **Bloom filters** (optional, for string lookups)

**How statistics affect benchmarks:**
- Queries with range filters benefit from min/max statistics
- Queries with equality filters benefit from bloom filters
- Statistics overhead is minimal (<1% of file size)

---

## 3. BenchBox Parquet configuration (~400 words)

### Default settings

BenchBox uses sensible defaults for benchmark reproducibility:

```python
PARQUET_DEFAULTS = {
    "compression": "zstd",
    "compression_level": 3,  # Balance of speed and ratio
    "row_group_size": 1_000_000,
    "page_size": 1_048_576,  # 1MB
}
```

### Compression options

```bash
# Default (Zstd level 3)
benchbox run --platform duckdb --benchmark tpch --scale 1

# Higher compression (smaller files, slower write)
benchbox run --platform duckdb --benchmark tpch --scale 1 --compression zstd:9

# Faster compression (larger files, faster write)
benchbox run --platform duckdb --benchmark tpch --scale 1 --compression snappy

# No compression (debugging, baseline)
benchbox run --platform duckdb --benchmark tpch --scale 1 --compression none
```

### When to adjust row group size

| Scenario | Row Group Size | Reason |
|----------|----------------|--------|
| Default | 1M rows | Balanced parallelism and overhead |
| High parallelism | 100K rows | More parallel tasks |
| Memory constrained | 500K rows | Reduce per-task memory |
| Large files | 2-5M rows | Reduce footer overhead |

*BenchBox currently uses the default. Custom row group sizes require manual data generation.*

### Platform-specific Parquet implementations

Each platform has its own Parquet reader/writer:

| Platform | Implementation | Notes |
|----------|----------------|-------|
| DuckDB | Native | Fast, feature-complete |
| Polars | Native (Rust) | Excellent performance |
| Spark | Hadoop Parquet | Mature, widely tested |
| DataFusion | Arrow Parquet | Good performance |
| Snowflake | Proprietary | Optimized for internal storage |

BenchBox generates Parquet files using PyArrow, which produces standard-compliant files readable by all platforms.

### Format versions

Parquet has two version concepts: file format version (controls logical types, BenchBox uses 2.6) and data page version (controls page serialization, BenchBox uses 1.0 for compatibility). Data page v2 separates definition/repetition levels from values, enabling page-level skipping without decompression. BenchBox inherits PyArrow's defaults, which are safe for all supported platforms.

---

## 4. Benchmark results: Compression comparison (~500 words)

### Test configuration

- **Platforms**: DuckDB
- **Benchmark**: TPC-H
- **Scale factors**: SF1, SF10
- **Compression**: None, Snappy, LZ4, Zstd:3, Zstd:9, Gzip

### Storage size comparison

| Compression | SF1 Size | Ratio | SF10 Size | Ratio |
|-------------|----------|-------|-----------|-------|
| None | [TBD] | 1.0x | [TBD] | 1.0x |
| Snappy | [TBD] | [TBD] | [TBD] | [TBD] |
| LZ4 | [TBD] | [TBD] | [TBD] | [TBD] |
| Zstd:3 | [TBD] | [TBD] | [TBD] | [TBD] |
| Zstd:9 | [TBD] | [TBD] | [TBD] | [TBD] |
| Gzip | [TBD] | [TBD] | [TBD] | [TBD] |

*[Benchmarks to be run and filled in]*

### Query performance comparison

| Compression | SF1 Total | SF10 Total | Notes |
|-------------|-----------|------------|-------|
| None | [TBD] | [TBD] | Baseline (no decompression) |
| Snappy | [TBD] | [TBD] | Fast decompression |
| Zstd:3 | [TBD] | [TBD] | BenchBox default |
| Zstd:9 | [TBD] | [TBD] | Higher compression |

*[Benchmarks to be run and filled in]*

### Query-specific observations

**Queries that benefit from compression:**
- I/O-bound queries (simple scans, aggregations)
- Large table scans (Q1, Q6)
- Cloud storage workloads (network latency)

**Queries where compression matters less:**
- CPU-bound queries (complex joins)
- Small data volumes (SF1)
- In-memory workloads

### Key findings

*[To be filled after benchmarks]*

Expected findings based on Parquet characteristics:
- Zstd provides best compression ratio with acceptable decompression speed
- Snappy trades ~20% larger files for faster decompression
- At SF10+, compression differences become more visible

---

## 5. Best practices (~300 words)

### Recommended settings for benchmarking

```bash
# Standard benchmark (reproducible, efficient)
benchbox run --platform duckdb --benchmark tpch --scale 10 --compression zstd:3

# Storage-focused comparison
benchbox run --platform duckdb --benchmark tpch --scale 10 --compression zstd:9

# Performance baseline (no compression overhead)
benchbox run --platform duckdb --benchmark tpch --scale 10 --compression none
```

### When to adjust row group size

**Increase row group size when:**
- Running at SF100+ (reduce metadata overhead)
- Using cloud storage (fewer S3/GCS requests)
- Memory is not constrained

**Decrease row group size when:**
- Maximizing parallelism on many-core systems
- Memory constrained environments
- Debugging query execution

### Compression selection guide

| Priority | Recommended | Reason |
|----------|-------------|--------|
| Storage cost | Zstd:9 | Best compression |
| Query speed | Snappy | Fastest decompression |
| Balanced | Zstd:3 | BenchBox default |
| Debugging | None | No decompression noise |

### Common mistakes to avoid

1. **Using CSV for benchmarks**: Parsing overhead skews results
2. **Ignoring compression**: Default varies by tool, specify explicitly
3. **Comparing across formats**: Parquet vs CSV is apples to oranges
4. **Forgetting row group size**: Affects parallelism and memory

---

## 6. Conclusion (~150 words)

Parquet is the foundation of modern analytics benchmarking for good reason:
- Universal support across platforms
- Efficient columnar storage
- Statistics for query optimization
- Mature, well-understood behavior

For BenchBox users, the defaults work well. The main tuning knobs are:
- **Compression**: Zstd:3 (default) for balance, Zstd:9 for storage, Snappy for speed
- **Row group size**: Rarely needs adjustment

In the next post, we'll explore Delta Lake, which builds on Parquet to add ACID transactions and time travel, and how those features affect benchmark design.

---

## Research Needed

- [ ] Run compression comparison benchmarks (None, Snappy, LZ4, Zstd:3, Zstd:9, Gzip)
- [ ] Measure storage sizes at SF1 and SF10
- [ ] Identify query-specific compression effects
- [ ] Verify BenchBox compression CLI options

## References

- [Apache Parquet Documentation](https://parquet.apache.org/docs/)
- [Parquet Format Specification](https://github.com/apache/parquet-format)
- [PyArrow Parquet Documentation](https://arrow.apache.org/docs/python/parquet.html)
- [DuckDB Parquet Support](https://duckdb.org/docs/data/parquet)

---

*Outline created: 2026-01-31*
*Status: OUTLINE - NEEDS BENCHMARKS*
