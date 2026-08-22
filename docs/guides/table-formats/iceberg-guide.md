# Apache Iceberg Guide

```{tags} guide, formats, iceberg, multi-engine
```

Iceberg provides table format features with true multi-engine support. This guide covers how to benchmark with Iceberg across different query engines, catalog configuration, and multi-engine workflows.

## Overview

Apache Iceberg was created at Netflix to solve a specific problem: running the same analytics across multiple query engines without locking into one vendor. Unlike Hive tables (Hive metastore-dependent), Iceberg tables work identically across Spark, Trino, Flink, Athena, Snowflake, and more.

For benchmarking, Iceberg's engine independence enables fair comparisons. We can load TPC-H data once, store it in Iceberg format, and run the same queries on Spark, Trino, and Athena. The data is identical across engines, isolating engine performance from data format differences.

We added Iceberg support to BenchBox for users building multi-engine lakehouses and those running on platforms where Iceberg is the native format (Athena, Starburst, Snowflake).

## Multi-Engine Support

### Supported Engines

The same Iceberg table is readable by:

- Apache Spark
- Trino and Presto
- Apache Flink
- Amazon Athena
- Snowflake
- BigQuery
- DuckDB (via extension)

This multi-engine support comes from a carefully designed metadata layer that doesn't depend on any specific query engine's implementation.

### Why Engine Independence Matters

For benchmarking, engine independence means:

- Load data once, query from multiple engines
- Fair comparisons (identical data across engines)
- Production-like conditions for multi-engine architectures
- No vendor lock-in in your benchmark methodology

## Iceberg Architecture

### Metadata Files

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

### Manifest Lists and Files

- **Metadata files**: Track table state, schema, and partitioning
- **Manifest lists**: Point to manifest files per snapshot
- **Manifest files**: List data files and their statistics

### Data Files

Data files are typically Parquet (or ORC, Avro) containing actual data. Iceberg manages the metadata layer; the underlying storage format is Parquet in most cases.

## Iceberg vs Delta Lake

| Aspect | Iceberg | Delta Lake |
|--------|---------|------------|
| Engine lock-in | None | Databricks-optimized |
| Catalog options | REST, Hive, Glue, Nessie | Unity Catalog, Hive |
| Partition evolution | Yes (metadata-only) | Limited |
| Hidden partitioning | Yes | No |
| Community | Apache project | Linux Foundation |

Both formats provide ACID transactions and time travel. The key difference is Iceberg's broader engine support and more flexible partitioning.

## Performance Considerations

### Manifest Overhead

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

### Mitigation Strategies

- Use partition pruning to reduce manifest reads
- Enable manifest caching where available
- Compact manifests for tables with many small files
- Use `expire_snapshots` to clean up historical metadata

## Advanced Partitioning

### Partition Evolution

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

### Hidden Partitioning

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

### Partition Transforms

Iceberg supports several partition transforms:

| Transform | Example | Use Case |
|-----------|---------|----------|
| identity | `identity(region)` | Exact value partitioning |
| year | `year(date_col)` | Annual aggregations |
| month | `month(date_col)` | Monthly aggregations |
| day | `day(date_col)` | Daily partitions |
| hour | `hour(timestamp_col)` | Hourly partitions |
| bucket | `bucket(100, id)` | Distribute by hash |
| truncate | `truncate(10, string_col)` | Prefix partitioning |

## Catalog Configuration

### REST Catalog

The REST catalog is the most portable option, working across engines:

```bash
benchbox run --platform spark --table-format iceberg --platform-option catalog=rest
```

### AWS Glue

For AWS-native workflows with Athena, EMR:

```bash
benchbox run --platform spark --table-format iceberg --platform-option catalog=glue
```

### Hive Metastore

For Spark/Hadoop ecosystems:

```bash
benchbox run --platform spark --table-format iceberg --platform-option catalog=hive
```

### Nessie

For git-like versioning (experimental):

```bash
benchbox run --platform spark --table-format iceberg --platform-option catalog=nessie
```

| Catalog | Use Case | BenchBox Support |
|---------|----------|------------------|
| REST Catalog | Standard, portable | Default |
| Hive Metastore | Spark/Hadoop ecosystems | Supported |
| AWS Glue | AWS-native (Athena, EMR) | Supported |
| Nessie | Git-like versioning | Experimental |

## Multi-Engine Workflows

### Write with One Engine, Read with Another

A key Iceberg benefit: load data with Spark, query with Trino (or vice versa).

**BenchBox multi-engine benchmark:**

```bash
# 1. Generate and load data with Spark
benchbox run --platform spark --benchmark tpch --scale 10 \
  --table-format iceberg --phases load

# 2. Run queries with Trino (same Iceberg tables)
benchbox run --platform trino --benchmark tpch --scale 10 \
  --table-format iceberg --phases power

# 3. Run queries with Athena (same tables via Glue)
benchbox run --platform athena --benchmark tpch --scale 10 \
  --table-format iceberg --phases power
```

### Ensuring Consistent Results

BenchBox validates query results against reference answers, catching:

- Type handling differences between engines
- NULL behavior variations
- Ordering differences

```bash
# Compare results from different engines
benchbox compare spark-results.json trino-results.json
```

### Common Multi-Engine Issues

**1. Schema evolution lag**

Some engines support new Iceberg schema features before others. If you add a column with Spark, older Trino versions might not see it.

**2. Partition pruning variations**

Partition pruning implementation differs by engine. One engine might prune more aggressively than another.

**3. Statistics availability**

Column-level statistics may not be shared across all engines. This affects query optimization.

**4. Caching effects**

Engine-specific caching can skew comparisons. BenchBox uses cold cache between runs to mitigate this.

## When to Use Iceberg

### Best-Fit Scenarios

| Scenario | Why Iceberg |
|----------|-------------|
| Multi-engine comparison | Same data, fair comparison |
| Lakehouse architectures | Production-like conditions |
| AWS-native platforms | Athena, EMR native support |
| Cross-platform portability | Engine-independent format |

### When to Use Parquet Instead

| Scenario | Why Parquet |
|----------|-------------|
| Single-engine benchmarks | Simpler, no catalog needed |
| Local development | No external catalog required |
| Quick comparisons | Less setup overhead |
| DuckDB-only | Native Parquet is faster |

## See Also

- [Table Format Guides](index.md): Overview of all formats
- [Format Conversion Reference](../../advanced/format-conversion.md): CLI commands for format conversion
- [Delta Lake Guide](delta-lake-guide.md): Alternative table format
- [Parquet Deep Dive](parquet-deep-dive.md): Foundation format for Iceberg <!-- content-ok: cliche -->
