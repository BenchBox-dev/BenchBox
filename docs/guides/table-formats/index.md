# Table Format Guides

```{tags} guide, formats
```

Understanding table formats helps you run better benchmarks and interpret results correctly. This guide series covers file formats (Parquet, Vortex) and table formats (Delta Lake, Iceberg) from a benchmarking perspective.

> **Looking for CLI commands?** See the [Format Conversion Reference](../../advanced/format-conversion.md) for `benchbox convert` commands, format comparison tables, and platform compatibility matrices.

## Overview

When comparing database performance, the data format sitting quietly in the background often gets less attention than query engines and tuning parameters. Yet format choice affects everything from storage costs to query performance to whether your results are reproducible across platforms.

We built format support into BenchBox because we kept running into the same questions: Why are my Parquet files so much smaller than CSV? Can I compare DuckDB on Parquet against Databricks on Delta Lake fairly? What's this Vortex format everyone's talking about?

## Why Format Choice Matters for Benchmarks

Consider a benchmark comparing two platforms. Platform A loads CSV files. Platform B loads Parquet. Platform B wins by 3x on query performance. Is Platform B faster, or is it just benefiting from columnar storage?

Format choice introduces variables that affect benchmark validity:

**Storage efficiency**: Parquet with Zstd compression can be 5-10x smaller than CSV. At scale factor 10, that's the difference between 10GB and 1GB of data. Smaller data means less I/O, which affects query times.

**Query optimization**: Columnar formats enable predicate pushdown (filtering at the storage layer) and column pruning (reading only needed columns). A `SELECT customer_name` query reads one column from Parquet but the entire file from CSV.

**Platform support**: Not every platform reads every format. Snowflake reads Parquet but not Delta Lake natively. Databricks reads Delta natively. Running the same benchmark across platforms requires a format they all understand.

**Reproducibility**: Different CSV parsers handle edge cases differently. Parquet files are self-describing, with schema and types embedded. The same Parquet file produces identical results across platforms.

## File Formats vs Table Formats

**File formats** (Parquet, ORC, Vortex) define how data is serialized to bytes. Each file is self-contained. No external state or metadata management required.

**Table formats** (Delta Lake, Iceberg, Hudi) build on file formats, typically Parquet. They add transaction logs for ACID guarantees, schema evolution, time travel, and compaction. The "table" is the collection of files plus metadata.

For benchmarking, the distinction matters:

- File formats are simpler to set up and more portable
- Table formats add overhead but enable production-like conditions

## Format Comparison

For a detailed comparison table of all supported formats including Parquet, Vortex, Delta Lake, Iceberg, Hudi, and DuckLake, see the [Format Conversion Reference](../../advanced/format-conversion.md#overview).

Key distinctions for benchmarking:

- **File formats** (Parquet, Vortex): Simpler setup, more portable, no metadata overhead
- **Table formats** (Delta Lake, Iceberg, Hudi): ACID guarantees, schema evolution, but added complexity

## When to Consider Format Impact

**Format matters when:**

- Comparing across platforms (format support varies)
- Measuring storage costs (compression ratios differ by 2-5x)
- Testing query features (predicate pushdown, statistics)
- Running at large scale factors where I/O dominates

**Format matters less when:**

- Comparing queries on the same platform with the same format
- Running at small scale factors where compute dominates
- Testing CPU-bound operations like complex joins

## Choosing the Right Format

| Scenario | Recommended | Reason |
|----------|-------------|--------|
| Cross-platform comparison | Parquet | Universal support |
| Databricks-only | Delta Lake | Native optimization |
| Multi-engine lakehouse | Iceberg | Engine independence |
| DuckDB performance focus | Vortex | Composable encodings |
| Maximum compatibility | Parquet | 10+ years of tooling |

### Recommendations

**For most benchmarks**: Use Parquet (the BenchBox default)

Parquet works on every platform, has well-understood performance characteristics, and provides maximum reproducibility. Unless you have a specific reason to use another format, stick with the default.

**For platform-specific benchmarks**: Match the platform's native format

If you're benchmarking Databricks, use Delta Lake. If you're on Trino or Starburst, consider Iceberg. This tests the platform under realistic conditions.

**For format comparison benchmarks**: Run both and compare using the CLI:

```bash
benchbox run --platform duckdb --benchmark tpch

benchbox run --platform duckdb --benchmark tpch --table-format vortex
```

For complete conversion examples, see [Format Conversion Reference: Quick Start](../../advanced/format-conversion.md#quick-start).

## Guide Index

Detailed guides for each format:

- **[Parquet Deep Dive](parquet-deep-dive.md)**: Row groups, compression options, statistics, and when to tune settings <!-- content-ok: cliche -->
- **[Delta Lake Guide](delta-lake-guide.md)**: Transaction overhead, OPTIMIZE, Z-ORDER, Databricks-specific features
- **[Apache Iceberg Guide](iceberg-guide.md)**: Multi-engine support, partition evolution, catalog configuration
- **[Vortex Guide](vortex-guide.md)**: Composable encodings, DuckDB integration, current status

## Related Documentation

- [Format Conversion Reference](../../advanced/format-conversion.md): CLI commands for converting between formats
- [Compression Guide](../compression.md): Data compression strategies
- [Cloud Storage](../cloud-storage.md): S3, GCS, and Azure Blob integration

```{toctree}
:maxdepth: 1

parquet-deep-dive
delta-lake-guide
iceberg-guide
vortex-guide
```
