# Post #3: Apache Iceberg - The open table format

## Metadata

```yaml
title: "Apache Iceberg: The open table format"
series: table-formats
post_number: 3
date: YYYY-MM-DD
tags: [benchmarking, benchbox, table-formats, iceberg, multi-engine, spark, trino, data-lake]
```

## Thesis

> Iceberg provides table format features with true multi-engine support. Here's how to benchmark with Iceberg across different query engines using BenchBox.

---

## 1. What is Iceberg? (~350 words)

### Table format designed for openness

Apache Iceberg was created at Netflix and donated to the Apache Software Foundation in 2018. Its core design principle: **engine independence**.

Unlike Delta Lake (Databricks-centric) or Hive tables (Hive metastore-dependent), Iceberg tables work the same across:
- Spark
- Trino/Presto
- Flink
- Athena
- DuckDB
- Snowflake
- BigQuery

### How Iceberg works

```
iceberg_table/
├── metadata/
│   ├── v1.metadata.json
│   ├── v2.metadata.json (current)
│   └── snap-xxxxx.avro (snapshots)
├── data/
│   ├── partition=2024-01/
│   │   └── data-xxxxx.parquet
│   └── partition=2024-02/
│       └── data-xxxxx.parquet
└── (catalog reference points here)
```

**Key components:**
- **Metadata files**: Track table state, schema, partitioning
- **Manifest files**: List data files per snapshot
- **Data files**: Parquet (or ORC, Avro) containing actual data

### Iceberg vs Delta Lake

| Aspect | Iceberg | Delta Lake |
|--------|---------|------------|
| Engine lock-in | None | Databricks-optimized |
| Catalog options | REST, Hive, Glue, Nessie | Unity Catalog, Hive |
| Partition evolution | Yes | Limited |
| Hidden partitioning | Yes | No |
| Protocol | Open specification | Open specification |

### Current status

- Apache top-level project
- Adopted by Snowflake, Databricks, AWS, Google, Apple
- Growing ecosystem of catalogs and tools

---

## 2. Iceberg for benchmarking (~400 words)

### Manifest overhead

Iceberg tracks files through manifest files, adding read overhead:
1. Read current metadata file
2. Read manifest list
3. Read relevant manifests
4. Filter to needed data files
5. Read data files

**Overhead characteristics:**
- Grows with table history and file count
- Mitigated by manifest caching (engine-dependent)
- Partition pruning reduces manifest reads

### Partition evolution

Iceberg allows changing partition schemes without rewriting data:

```sql
-- Original partitioning
CREATE TABLE events ... PARTITIONED BY (event_date);

-- Add hour-level partitioning (no data rewrite)
ALTER TABLE events ADD PARTITION FIELD hour(event_time);
```

**Benchmark implications:**
- Partition evolution is metadata-only (fast)
- Queries use appropriate partitioning per file
- Historical data maintains original partitioning

### Hidden partitioning

Iceberg can partition on transforms without exposing partition columns:

```sql
-- Partition by month, but query by date
CREATE TABLE orders
  PARTITIONED BY (month(order_date))
  AS SELECT * FROM raw_orders;

-- Query uses partition pruning automatically
SELECT * FROM orders WHERE order_date = '2024-03-15';
```

**Benchmark implications:**
- Simplifies query writing
- Partition pruning happens automatically
- No need to include partition columns in WHERE

### Catalog options

| Catalog | Use Case | BenchBox Support |
|---------|----------|------------------|
| REST Catalog | Standard, portable | Yes |
| Hive Metastore | Spark/Hadoop ecosystems | Yes |
| AWS Glue | AWS native | Yes (Athena) |
| Nessie | Git-like versioning | Experimental |

BenchBox defaults to REST catalog for portability, with platform-specific overrides.

---

## 3. BenchBox Iceberg configuration (~400 words)

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

# BenchBox configures:
# spark.sql.catalog.spark_catalog = org.apache.iceberg.spark.SparkSessionCatalog
# spark.sql.catalog.spark_catalog.type = hive
```

### Trino/Starburst setup

```bash
# Run TPC-H on Trino with Iceberg
benchbox run --platform trino --benchmark tpch --scale 10 --format iceberg

# Requires Trino Iceberg connector configuration
# (BenchBox provides templates)
```

### Athena setup

```bash
# Run TPC-H on Athena with Iceberg (Glue catalog)
benchbox run --platform athena --benchmark tpch --scale 10 --format iceberg

# BenchBox:
# 1. Creates Iceberg tables in Glue catalog
# 2. Loads data via Athena CTAS
# 3. Runs benchmark queries
```

### DuckDB setup

```bash
# Install iceberg extension
duckdb -c "INSTALL iceberg; LOAD iceberg;"

# Run with Iceberg format
benchbox run --platform duckdb --benchmark tpch --scale 1 --format iceberg
```

**Note**: DuckDB Iceberg support is read-only. BenchBox generates Iceberg tables using PyIceberg, then queries with DuckDB.

### Catalog configuration

```bash
# Use REST catalog (default)
benchbox run --platform spark --format iceberg --catalog rest

# Use Glue catalog (AWS)
benchbox run --platform spark --format iceberg --catalog glue

# Use Hive metastore
benchbox run --platform spark --format iceberg --catalog hive
```

---

## 4. Benchmark results (~500 words)

### Test configuration

- **Platforms**: Spark, Trino, Athena
- **Benchmark**: TPC-H
- **Scale factors**: SF1, SF10
- **Comparison**: Iceberg vs Parquet, cross-engine consistency

### Storage comparison

| Format | SF10 Size | vs Parquet | Notes |
|--------|-----------|------------|-------|
| Parquet (zstd) | [TBD] | 1.0x | Baseline |
| Iceberg | [TBD] | [TBD] | Includes metadata |

*[Benchmarks to be run and filled in]*

### Query performance (Spark)

| Format | SF10 Total | Geometric Mean | Notes |
|--------|------------|----------------|-------|
| Parquet | [TBD] | [TBD] | Hive tables |
| Iceberg | [TBD] | [TBD] | Iceberg tables |

*[Benchmarks to be run and filled in]*

### Cross-engine comparison (same Iceberg tables)

| Engine | SF10 Total | Geometric Mean | Notes |
|--------|------------|----------------|-------|
| Spark | [TBD] | [TBD] | Iceberg tables |
| Trino | [TBD] | [TBD] | Same tables, different engine |
| Athena | [TBD] | [TBD] | Via Glue catalog |

*[Benchmarks to be run and filled in]*

### Metadata overhead

| Table | Files | Manifests | Overhead |
|-------|-------|-----------|----------|
| lineitem (SF10) | [TBD] | [TBD] | [TBD] |
| orders (SF10) | [TBD] | [TBD] | [TBD] |

*[Benchmarks to be run and filled in]*

### Partition strategy impact

| Partitioning | Query | Time | Notes |
|--------------|-------|------|-------|
| None | Q1 | [TBD] | Full table scan |
| By l_shipdate (month) | Q1 | [TBD] | Partition pruning |
| By l_shipdate (day) | Q1 | [TBD] | Fine-grained pruning |

*[Benchmarks to be run and filled in]*

### Key findings

*[To be filled after benchmarks]*

Expected findings:
- Iceberg overhead is minimal for read-heavy benchmarks
- Manifest overhead grows with file count
- Partition pruning significantly impacts query performance
- Cross-engine results should be consistent

---

## 5. Multi-engine workflow (~350 words)

### Writing with one engine, reading with another

A key Iceberg benefit: write with Spark, read with Trino (or vice versa).

**BenchBox multi-engine benchmark:**

```bash
# 1. Generate and load data with Spark
benchbox run --platform spark --benchmark tpch --scale 10 --format iceberg --phases load

# 2. Run queries with Trino (same tables)
benchbox run --platform trino --benchmark tpch --scale 10 --format iceberg --phases power

# 3. Run queries with Athena (same tables via Glue)
benchbox run --platform athena --benchmark tpch --scale 10 --format iceberg --phases power
```

### Ensuring consistent results across engines

BenchBox validates query results against reference answers, catching:
- Type handling differences
- NULL behavior variations
- Ordering differences

**Validation across engines:**

```bash
# Compare results from different engines
benchbox compare-results spark-results.json trino-results.json --validate-answers
```

### Catalog synchronization

For multi-engine workflows, catalog consistency is critical:

| Catalog | Multi-Engine Support | BenchBox Handling |
|---------|---------------------|-------------------|
| REST | Best | Default for portability |
| Glue | Good | AWS-native engines |
| Hive | Good | Spark/Trino/Flink |

### Common multi-engine issues

1. **Schema evolution**: Some engines lag on new schema features
2. **Partition pruning**: Implementation varies by engine
3. **Statistics**: May not be shared across engines
4. **Caching**: Engine-specific, can skew comparisons

BenchBox mitigates these by:
- Using cold cache between runs
- Validating results against reference answers
- Documenting known engine differences

---

## 6. When to use Iceberg for benchmarks (~250 words)

### Best-fit scenarios

| Scenario | Reason |
|----------|--------|
| Multi-engine comparison | Same data, different engines |
| Lakehouse architectures | Production-like conditions |
| Cloud data platforms | Athena, Starburst, Snowflake support |
| Long-running benchmark projects | Schema evolution, time travel |

### When to stay with Parquet

| Scenario | Reason |
|----------|--------|
| Single-engine benchmarks | Simpler, no catalog needed |
| Maximum portability | Parquet is universal |
| Local development | No external catalog required |
| Quick comparisons | Less setup overhead |

### Benchmark design considerations

1. **Catalog setup**: Plan for REST catalog or cloud-native option
2. **Partition strategy**: Match production or use default
3. **Multi-engine**: Ensure catalog is accessible from all engines
4. **Metadata cleanup**: Use `expire_snapshots` before benchmarks

---

## 7. Conclusion (~150 words)

Apache Iceberg brings table format capabilities with true multi-engine support. For BenchBox users:

- **Multi-engine benchmarks**: Iceberg enables apples-to-apples comparisons
- **Cloud platforms**: Native support on Athena, Starburst, Snowflake
- **Overhead**: Minimal for read-heavy benchmarks after proper setup
- **Catalog choice**: REST for portability, Glue for AWS

The key differentiator is engine independence. If you're comparing Spark vs Trino vs Athena on the same data, Iceberg provides a fair playing field.

In the next post, we'll explore Vortex, a columnar format with composable encodings designed for maximum performance.

---

## Research Needed

- [ ] Set up REST catalog for BenchBox
- [ ] Run TPC-H on Spark with Iceberg (SF1, SF10)
- [ ] Run cross-engine benchmark (Spark, Trino, same tables)
- [ ] Measure metadata overhead at different scale factors
- [ ] Test partition strategy impact on TPC-H queries

## References

- [Apache Iceberg Documentation](https://iceberg.apache.org/docs/latest/)
- [Iceberg Table Specification](https://iceberg.apache.org/spec/)
- [PyIceberg](https://py.iceberg.apache.org/)
- [Trino Iceberg Connector](https://trino.io/docs/current/connector/iceberg.html)
- [Athena Iceberg Tables](https://docs.aws.amazon.com/athena/latest/ug/querying-iceberg.html)

---

*Outline created: 2026-01-31*
*Status: OUTLINE - NEEDS BENCHMARKS*
