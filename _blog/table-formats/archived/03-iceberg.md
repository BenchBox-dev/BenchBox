# Apache Iceberg: The open table format

> Iceberg provides table format features with true multi-engine support. Here's how we benchmark with Iceberg across different query engines using BenchBox.

**TL;DR**: Iceberg's engine independence makes it ideal for cross-platform benchmarks. The same Iceberg table works on Spark, Trino, Athena, and DuckDB. Metadata overhead is minimal for read-heavy benchmarks. Use REST catalog for portability or AWS Glue for AWS-native workflows.

---

## Introduction

Apache Iceberg was created at Netflix to solve a specific problem: running the same analytics across multiple query engines without locking into one vendor. Unlike Hive tables (Hive metastore-dependent), Iceberg tables work identically across Spark, Trino, Flink, Athena, Snowflake, and more.

For benchmarking, Iceberg's engine independence enables fair comparisons. We can load TPC-H data once, store it in Iceberg format, and run the same queries on Spark, Trino, and Athena. The data is identical across engines, isolating engine performance from data format differences.

We added Iceberg support to BenchBox for users building multi-engine lakehouses and those running on platforms where Iceberg is the native format (Athena, Starburst, Snowflake).

---

## What is Iceberg?

### Table format designed for openness

Apache Iceberg was created at Netflix in 2017 and donated to the Apache Software Foundation in 2018. Its core design principle: **engine independence**.

The same Iceberg table is readable by:

- Apache Spark
- Trino and Presto
- Apache Flink
- Amazon Athena
- Snowflake
- BigQuery
- DuckDB (via extension)

This multi-engine support comes from a carefully designed metadata layer that doesn't depend on any specific query engine's implementation.

### How Iceberg works

```
iceberg_table/
├── metadata/
│   ├── v1.metadata.json
│   ├── v2.metadata.json (current version)
│   └── snap-xxxxx.avro (manifest list)
├── data/
│   ├── partition=2024-01/
│   │   └── data-xxxxx.parquet
│   └── partition=2024-02/
│       └── data-xxxxx.parquet
└── (catalog points here)
```

**Key components:**

- **Metadata files**: Track table state, schema, and partitioning
- **Manifest lists**: Point to manifest files per snapshot
- **Manifest files**: List data files and their statistics
- **Data files**: Parquet (or ORC, Avro) containing actual data

### Iceberg vs. Delta Lake

| Aspect | Iceberg | Delta Lake |
|--------|---------|------------|
| Engine lock-in | None | Databricks-optimized |
| Catalog options | REST, Hive, Glue, Nessie | Unity Catalog, Hive |
| Partition evolution | Yes (metadata-only) | Limited |
| Hidden partitioning | Yes | No |
| Community | Apache project | Linux Foundation |

Both formats provide ACID transactions and time travel. The key difference is Iceberg's broader engine support and more flexible partitioning.

---

## Iceberg for benchmarking

### Manifest overhead

Iceberg tracks files through a hierarchy of manifests:

1. Read current metadata file
2. Read manifest list (points to manifests)
3. Read relevant manifest files
4. Filter to needed data files based on partition pruning
5. Read data files

**Overhead characteristics:**

- Grows with file count and table history
- Mitigated by manifest caching (engine-dependent)
- Partition pruning reduces manifest reads

For TPC-H benchmarks with standard data loads, manifest overhead is typically under 50ms. For tables with millions of files, consider compaction.

### Partition evolution

Iceberg allows changing partition schemes without rewriting data:

```sql
-- Original table partitioned by date
CREATE TABLE events (...) PARTITIONED BY (event_date);

-- Add hour-level partitioning for new data (no rewrite)
ALTER TABLE events ADD PARTITION FIELD hour(event_time);
```

**Benchmark implications:**

- Partition evolution is metadata-only (fast)
- Queries automatically use appropriate partitioning per file
- Historical data keeps its original partitioning

### Hidden partitioning

Iceberg can partition on transforms without exposing partition columns in queries:

```sql
-- Create table partitioned by month transform
CREATE TABLE orders
  PARTITIONED BY (month(order_date))
  AS SELECT * FROM raw_orders;

-- Query by exact date, Iceberg applies partition pruning automatically
SELECT * FROM orders WHERE order_date = '2024-03-15';
```

**Benchmark implications:**

- Simpler query writing (no partition column gymnastics)
- Partition pruning happens automatically
- Consistent query behavior across engines

### Catalog options

| Catalog | Use Case | BenchBox Support |
|---------|----------|------------------|
| REST Catalog | Standard, portable | Default |
| Hive Metastore | Spark/Hadoop ecosystems | Supported |
| AWS Glue | AWS-native (Athena, EMR) | Supported |
| Nessie | Git-like versioning | Experimental |

BenchBox defaults to REST catalog for portability, with platform-specific overrides for AWS Glue and Hive.

---

## BenchBox Iceberg configuration

### Supported platforms

| Platform | Iceberg Support | Catalog Options |
|----------|-----------------|-----------------|
| Spark | Native | REST, Hive, Glue |
| Trino | Native | REST, Hive, Glue |
| Athena | Native | Glue |
| Starburst | Native | REST, Hive, Glue |
| DuckDB | Extension | REST (iceberg extension) |
| Snowflake | Native | Snowflake catalog |

### Spark setup

```bash
# Run TPC-H on Spark with Iceberg
benchbox run --platform spark --benchmark tpch --scale 10 --format iceberg
```

BenchBox configures Spark with:

```
spark.sql.catalog.spark_catalog = org.apache.iceberg.spark.SparkSessionCatalog
spark.sql.catalog.spark_catalog.type = hive
```

### Trino/Starburst setup

```bash
# Run TPC-H on Trino with Iceberg
benchbox run --platform trino --benchmark tpch --scale 10 --format iceberg
```

Requires Trino Iceberg connector configuration. BenchBox provides templates for common setups.

### Athena setup

```bash
# Run TPC-H on Athena with Iceberg (Glue catalog)
benchbox run --platform athena --benchmark tpch --scale 10 --format iceberg
```

BenchBox:

1. Creates Iceberg tables in AWS Glue catalog
2. Loads data via Athena CTAS (CREATE TABLE AS SELECT)
3. Runs benchmark queries

### DuckDB setup

```bash
# Install iceberg extension (one-time)
duckdb -c "INSTALL iceberg; LOAD iceberg;"

# Run with Iceberg format
benchbox run --platform duckdb --benchmark tpch --scale 1 --format iceberg
```

**Note**: DuckDB Iceberg support is read-only. BenchBox generates Iceberg tables using PyIceberg, then queries with DuckDB.

### Catalog configuration

```bash
# Use REST catalog (default, most portable)
benchbox run --platform spark --format iceberg --catalog rest

# Use Glue catalog (AWS native)
benchbox run --platform spark --format iceberg --catalog glue

# Use Hive metastore
benchbox run --platform spark --format iceberg --catalog hive
```

---

## Benchmark results

We ran TPC-H on multiple engines with the same Iceberg tables to measure cross-engine consistency.

**Test environment:**
- AWS us-east-1 region
- Iceberg tables stored in S3 with AWS Glue catalog
- Spark: EMR 7.0 with Spark 3.5 (3x m5.xlarge)
- Trino: Starburst Galaxy (medium cluster)
- Athena: Athena v3 (serverless)
- Cold cache, median of 3 runs
- January 2026

### Storage comparison

| Format | SF10 Size | vs Parquet | Notes |
|--------|-----------|------------|-------|
| Parquet (zstd) | 2.8 GB | 1.0x | Baseline |
| Iceberg | 2.85 GB | 1.02x | Includes metadata |

Iceberg metadata overhead is minimal (1-3%) for typical benchmark tables.

### Query performance (Spark)

| Format | SF10 Geometric Mean | Notes |
|--------|---------------------|-------|
| Parquet (Hive) | 1.1s | Hive table on Parquet |
| Iceberg | 1.15s | Iceberg table |

Iceberg adds ~5% overhead compared to Hive tables on Spark. The overhead comes from manifest reading and statistics evaluation.

### Cross-engine comparison

We loaded TPC-H SF10 once into Iceberg (Glue catalog) and ran queries on three engines:

| Engine | Geometric Mean | Notes |
|--------|----------------|-------|
| Spark (EMR) | 1.15s | Iceberg native |
| Trino (Starburst) | 0.95s | Iceberg connector |
| Athena | 1.8s | Serverless, pay-per-query |

Results vary by engine, but the key insight is that all three engines query the same data files. Performance differences reflect engine characteristics, not data format differences.

### Partition strategy impact

We tested different partitioning strategies on the lineitem table:

| Partitioning | Q1 Time | Q6 Time | Notes |
|--------------|---------|---------|-------|
| None | 2.5s | 1.2s | Full scan |
| month(l_shipdate) | 1.8s | 0.6s | Month-level pruning |
| day(l_shipdate) | 1.7s | 0.4s | Day-level pruning |

Fine-grained partitioning helps queries with narrow date ranges (Q6) more than broad aggregations (Q1).

---

## Multi-engine workflows

### Write with one engine, read with another

A key Iceberg benefit: load data with Spark, query with Trino (or vice versa).

**BenchBox multi-engine benchmark:**

```bash
# 1. Generate and load data with Spark
benchbox run --platform spark --benchmark tpch --scale 10 \
  --format iceberg --phases load

# 2. Run queries with Trino (same Iceberg tables)
benchbox run --platform trino --benchmark tpch --scale 10 \
  --format iceberg --phases power

# 3. Run queries with Athena (same tables via Glue)
benchbox run --platform athena --benchmark tpch --scale 10 \
  --format iceberg --phases power
```

### Ensuring consistent results

BenchBox validates query results against reference answers, catching:

- Type handling differences between engines
- NULL behavior variations
- Ordering differences

```bash
# Compare results from different engines
benchbox compare-results spark-results.json trino-results.json --validate
```

### Common multi-engine issues

**1. Schema evolution lag**

Some engines support new Iceberg schema features before others. If you add a column with Spark, older Trino versions might not see it.

**2. Partition pruning variations**

Partition pruning implementation differs by engine. One engine might prune more aggressively than another.

**3. Statistics availability**

Column-level statistics may not be shared across all engines. This affects query optimization.

**4. Caching effects**

Engine-specific caching can skew comparisons. BenchBox uses cold cache between runs to mitigate this.

---

## When to use Iceberg for benchmarks

### Best-fit scenarios

| Scenario | Why Iceberg |
|----------|-------------|
| Multi-engine comparison | Same data, fair comparison |
| Lakehouse architectures | Production-like conditions |
| AWS-native platforms | Athena, EMR native support |
| Cross-platform portability | Engine-independent format |

### When to stay with Parquet

| Scenario | Why Parquet |
|----------|-------------|
| Single-engine benchmarks | Simpler, no catalog needed |
| Local development | No external catalog required |
| Quick comparisons | Less setup overhead |
| DuckDB-only | Native Parquet is faster |

### Benchmark design tips

1. **Choose catalog carefully**: REST for portability, Glue for AWS
2. **Partition thoughtfully**: Match production or use sensible defaults
3. **Ensure catalog access**: All engines need to reach the same catalog
4. **Clean up metadata**: Use `expire_snapshots` before benchmarks

---

## Conclusion

Apache Iceberg brings table format capabilities with true multi-engine support. For BenchBox users:

- **Multi-engine benchmarks**: Iceberg enables apples-to-apples comparisons
- **Cloud platforms**: Native support on Athena, Starburst, Snowflake
- **Overhead**: Minimal for read-heavy benchmarks after proper setup
- **Catalog choice**: REST for portability, Glue for AWS

The key differentiator is engine independence. If you're comparing Spark vs. Trino vs. Athena on the same data, Iceberg provides a fair playing field.

In the next post, we'll explore Vortex, a columnar format with composable encodings designed for maximum performance.

---

## References

[^1]: [Apache Iceberg Documentation](https://iceberg.apache.org/docs/latest/) - Apache Software Foundation
[^2]: [Iceberg Table Specification](https://iceberg.apache.org/spec/) - Apache Iceberg
[^3]: [PyIceberg](https://py.iceberg.apache.org/) - Apache Iceberg Python Library
[^4]: [Trino Iceberg Connector](https://trino.io/docs/current/connector/iceberg.html) - Trino Documentation
[^5]: [Athena Iceberg Tables](https://docs.aws.amazon.com/athena/latest/ug/querying-iceberg.html) - AWS Documentation
[^6]: BenchBox TPC-H SF10 cross-engine benchmark, AWS us-east-1, Glue catalog, cold cache, median of 3 runs. January 2026.

---

*Questions or feedback? [Open an issue](https://github.com/oxbow-analytics/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: ~1,950
**Series**: table-formats
**Post Number**: 3
