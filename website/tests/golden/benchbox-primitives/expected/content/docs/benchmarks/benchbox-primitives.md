---
title: BenchBox Primitives
tags:
  - reference
  - custom-benchmark
sourcePath: docs/benchmarks/benchbox-primitives.md
titleId: benchbox-primitives
headingIds:
  - why-primitives
  - design-philosophy
  - use-cases-for-primitives
  - primitive-categories
  - dataframe-support
  - included-benchmarks
  - see-also
---

<span id="benchbox-primitives"></span>

Fundamental database operation testing designed for deep performance investigation.

## Why Primitives?

Standard benchmarks like TPC-H measure end-to-end query performance, but when a query runs slowly, they don't tell you *why*. Is it the join algorithm? Predicate pushdown? Aggregation strategy? Data loading? Primitive benchmarks isolate individual operations to answer these questions.

BenchBox Primitives were created to fill a gap in the benchmarking landscape:

- **TPC benchmarks** test complete queries but hide which operations are slow
- **Microbenchmarks** test operations but lack realistic data characteristics
- **Primitives** combine isolated operations with benchmark-scale data

This approach enables systematic performance investigation that pinpoints bottlenecks.

## Design Philosophy

BenchBox Primitives follow several design principles:

<dl>

<dt><strong>Isolation</strong></dt>

<dd>

Each primitive tests one operation or a small family of related operations. A filter primitive tests filtering, not filtering-then-joining. This isolation makes performance differences attributable to specific capabilities.

</dd>

<dt><strong>Realistic data</strong></dt>

<dd>

Primitives use TPC-derived data with realistic distributions, cardinalities, and correlations. Testing a filter on uniformly distributed random data tells you little about production performance.

</dd>

<dt><strong>Coverage</strong></dt>

<dd>

The primitives cover the fundamental operations that compose all analytical queries: scans, filters, projections, aggregations, joins, sorts, and more. Understanding primitive performance predicts complex query performance.

</dd>

<dt><strong>Platform agnostic</strong></dt>

<dd>

Primitives work across SQL and DataFrame platforms, enabling comparison between Pandas and PostgreSQL, or Polars and DuckDB. The same logical operation is tested regardless of API.

</dd>

</dl>

## Use Cases for Primitives

<dl>

<dt><strong>Performance debugging</strong></dt>

<dd>

When a TPC-H query runs slower than expected, run the corresponding primitives to identify which operation is the bottleneck. Is Q9's slowdown from the join strategy or the aggregation?

</dd>

<dt><strong>Platform evaluation</strong></dt>

<dd>

Before choosing a database, test the operations your workload uses most. If your queries are join-heavy, the join primitives predict real performance better than aggregate TPC scores.

</dd>

<dt><strong>Optimization validation</strong></dt>

<dd>

After tuning a database, run primitives to verify the optimization worked. Did the new index actually speed up the filter operation? Primitives provide focused measurement.

</dd>

<dt><strong>Regression detection</strong></dt>

<dd>

Track primitive performance across database versions to catch regressions early. A 20% slowdown in aggregation primitives predicts problems before they appear in complex queries.

</dd>

<dt><strong>DataFrame vs SQL comparison</strong></dt>

<dd>

Primitives enable apples-to-apples comparison between DataFrame libraries (Polars, Pandas) and SQL databases (DuckDB, PostgreSQL) on the same logical operations.

</dd>

</dl>

## Primitive Categories

BenchBox Primitives are organized into three categories:

| Category                   | Operations                                                                | Insights                                                                  |
| -------------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| **Read Primitives**        | Scans, filters, projections, aggregations, joins, sorts, window functions | Query execution performance, optimizer effectiveness                      |
| **Write Primitives**       | Inserts, bulk loads, updates, deletes, upserts                            | Data loading performance, transaction overhead                            |
| **Transaction Primitives** | Isolation levels, concurrent access, conflict resolution                  | ACID compliance, concurrency characteristics                              |
| **Metadata Primitives**    | INFORMATION_SCHEMA, SHOW, DESCRIBE, PRAGMA catalog queries                | Catalog introspection performance for data catalogs, BI tools, governance |
| **AI Primitives**          | SQL-based AI functions - generation, summarization, sentiment, embeddings | Cloud AI SQL surface (Snowflake Cortex, BigQuery ML, Databricks AI)       |

### DataFrame Support

Read and Write Primitives include full DataFrame implementations supporting both expression-based platforms (Polars, PySpark, DataFusion) and pandas-compatible platforms (Pandas, Dask, cuDF). This enables direct comparison between SQL and DataFrame performance on identical operations.

## Included Benchmarks

- [read-primitives](/docs/benchmarks/read-primitives.html)
- [write-primitives](/docs/benchmarks/write-primitives.html)
- [transaction-primitives](/docs/benchmarks/transaction-primitives.html)
- [metadata-primitives](/docs/benchmarks/metadata-primitives.html)
- [ai-primitives](/docs/benchmarks/ai-primitives.html)

## See Also

- [understanding-results](/docs/tutorials/understanding-results.html) - Interpreting benchmark output
- [platform-comparison](/docs/guides/platform-comparison.html) - Comparing platforms systematically
- [tpc-standards](/docs/benchmarks/tpc-standards.html) - End-to-end query benchmarks
