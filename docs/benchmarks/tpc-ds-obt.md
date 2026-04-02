<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# TPC-DS-OBT Benchmark

```{tags} advanced, concept, tpc-ds-obt, tpc-ds, experimental
```

> **CLI name:** `tpcds_obt` — use `benchbox run --benchmark tpcds_obt`

## Overview

The TPC-DS-OBT (One Big Table) benchmark adapts the standard TPC-DS benchmark to run against a single denormalized table instead of the traditional 25-table normalized schema. This experimental benchmark tests how databases handle wide tables with hundreds of columns, a pattern increasingly common in modern data warehouses and lakehouse architectures.

The benchmark is ideal for evaluating column pruning efficiency, wide table scan performance, and storage format effectiveness (Parquet, Delta Lake, Iceberg) on denormalized schemas.

## Key Features

- **Single wide table** - All TPC-DS data flattened into one denormalized table
- **Same 99 queries** - Standard TPC-DS queries rewritten for flat schema
- **No joins required** - Tests pure scan and aggregation performance
- **Column pruning focus** - Evaluates optimizer column projection efficiency
- **Modern lakehouse pattern** - Simulates real-world denormalized data models
- **Storage format comparison** - Ideal for Parquet vs Delta vs Iceberg testing

## Use Cases

### When to Use TPC-DS-OBT

- **Lakehouse performance testing** - Evaluate denormalized table performance
- **Column pruning benchmarks** - Test how efficiently engines skip unused columns
- **Wide table handling** - Stress test databases with 200+ column tables
- **Storage format comparison** - Compare Parquet, Delta Lake, Iceberg on wide tables
- **Scan-heavy workloads** - Benchmark pure analytical scan performance without join overhead

### When to Use Standard TPC-DS

- **Join performance testing** - Evaluating multi-table join strategies
- **Normalized schema workloads** - Traditional data warehouse patterns
- **TPC compliance** - Official TPC-DS compliance requires normalized schema

## Data Model

### One Big Table Schema

The OBT schema denormalizes all 25 TPC-DS tables into a single wide table:

| Aspect | Value |
|--------|-------|
| **Tables** | 1 (denormalized) |
| **Columns** | ~200+ |
| **Source Tables** | All 25 TPC-DS tables flattened |
| **Primary Grain** | store_sales fact table |

### Column Groups

The denormalized table contains columns from all TPC-DS dimensions:

| Source Table | Columns Added | Prefix |
|--------------|---------------|--------|
| store_sales | ~23 | `ss_` |
| customer | ~18 | `c_` |
| customer_address | ~13 | `ca_` |
| customer_demographics | ~9 | `cd_` |
| date_dim | ~28 | `d_` |
| item | ~22 | `i_` |
| store | ~29 | `s_` |
| promotion | ~19 | `p_` |
| household_demographics | ~5 | `hd_` |
| time_dim | ~10 | `t_` |
| ... | ... | ... |

### Scale Factors

| Scale Factor | Approximate Rows | Approximate Size |
|--------------|------------------|------------------|
| 1 | ~2.8 million | ~2 GB |
| 10 | ~28 million | ~20 GB |
| 100 | ~280 million | ~200 GB |
| 1000 | ~2.8 billion | ~2 TB |

## Quick Start

```bash
# Run TPC-DS-OBT on DuckDB
benchbox run --platform duckdb --benchmark tpc-ds-obt --scale 1.0

# Run specific queries
benchbox run --platform duckdb --benchmark tpc-ds-obt --scale 1.0 --queries Q1,Q3,Q7

# Compare with standard TPC-DS
benchbox run --platform duckdb --benchmark tpcds --scale 1.0
benchbox run --platform duckdb --benchmark tpc-ds-obt --scale 1.0
```

## Query Adaptations

TPC-DS-OBT rewrites the standard 99 TPC-DS queries to work with the flat schema:

### Example: Query 1

**Standard TPC-DS Q1** (with joins):
```sql
SELECT c_customer_id, c_first_name, c_last_name, ...
FROM customer, store_sales, date_dim, store
WHERE c_customer_sk = ss_customer_sk
  AND ss_sold_date_sk = d_date_sk
  AND ss_store_sk = s_store_sk
  ...
```

**TPC-DS-OBT Q1** (flat table):
```sql
SELECT c_customer_id, c_first_name, c_last_name, ...
FROM tpcds_obt
WHERE d_year = 2000
  AND s_state = 'TN'
  ...
```

## Performance Considerations

### Advantages of OBT

- **No join overhead** - Eliminates multi-table join costs
- **Simplified query plans** - Single table scan with filters
- **Columnar format efficiency** - Modern formats excel at column pruning
- **Predictable performance** - Less optimizer variability

### Challenges of OBT

- **Storage overhead** - Denormalization increases data redundancy
- **Column count** - Wide tables stress metadata handling
- **Update complexity** - Changes require full table rewrites
- **Memory pressure** - Wide rows can stress memory buffers

## Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| DuckDB | ✅ Full | Excellent wide table handling |
| ClickHouse | ✅ Full | Strong columnar performance |
| Databricks | ✅ Full | Native Delta Lake support |
| Snowflake | ✅ Full | Automatic micro-partitioning |
| BigQuery | ✅ Full | Columnar storage optimized |
| Polars | ✅ Full | Efficient Arrow-based scans |
| PostgreSQL | ⚠️ Limited | Row-store less efficient for wide tables |

## Comparison with Related Benchmarks

| Benchmark | Schema | Tables | Focus |
|-----------|--------|--------|-------|
| **TPC-DS** | Normalized | 25 | Join performance, complex queries |
| **TPC-DS-OBT** | Denormalized | 1 | Wide table scans, column pruning |
| **TPC-H** | Normalized | 8 | Simpler decision support |
| **ClickBench** | Single table | 1 | Real-world analytics patterns |

## See Also

- [TPC-DS Benchmark](tpc-ds.md) - Standard normalized TPC-DS
- [ClickBench](clickbench.md) - Another single-table analytics benchmark
- [Data Vault](datavault.md) - Alternative schema modeling approach
- [Platform Comparison](../platforms/comparison-matrix.md) - Platform capabilities
