# Open Table Formats Guide

```{tags} advanced, guide
```

Convert benchmark data to modern columnar formats for improved query performance, storage efficiency, and platform compatibility.

> **Looking for conceptual guidance?** See the [Table Format Guides](../guides/table-formats/index.md) for in-depth explanations of when to use each format and benchmarking considerations.

## Overview

BenchBox supports six open table formats for storing benchmark data:

| Format | Type | Key Features | Best For |
|--------|------|--------------|----------|
| **Parquet** | File | Fast, universal support | General analytics, portability |
| **Vortex** | File | High compression, fast scans | Analytical workloads, storage efficiency |
| **Delta Lake** | Table | ACID, time travel | Production data lakes, Databricks |
| **Iceberg** | Table | Schema evolution, hidden partitioning | Enterprise data platforms |
| **Apache Hudi** | Table | Record-level ACID, incremental processing | Streaming workloads, upserts |
| **DuckLake** | Table | ACID, time travel, DuckDB-native | DuckDB-native analytics, local development |

## Why Use Columnar Formats?

TPC benchmarks generate data in TBL format (pipe-delimited text files). Converting to columnar formats provides:

### Performance Benefits

- **Faster queries**: Columnar storage enables reading only required columns (improvement varies by query selectivity)
- **Predicate pushdown**: Filter data at the storage layer before loading into memory
- **Partition pruning**: Skip irrelevant data partitions entirely
- **Statistics-based optimization**: Min/max values and row counts per column chunk

### Storage Benefits

- **3-5x compression**: Columnar layout enables efficient encoding and compression
- **Type-aware encoding**: Dictionary encoding for strings, RLE for repeated values
- **Compression algorithms**: Snappy, Gzip, or Zstd for different size/speed tradeoffs

### Platform Compatibility

| Platform | Parquet | Vortex | Delta Lake | Iceberg | Hudi | DuckLake |
|----------|---------|--------|------------|---------|------|----------|
| DuckDB | Native | Extension | Extension | - | - | Native |
| Spark | Native | - | Native | Native | Native | - |
| Databricks | Native | - | Native | Native | Native | - |
| Quanton | Native | - | Native | Native | Native | - |
| Snowflake | External | - | External | Native | - | - |
| BigQuery | External | - | - | External | - | - |
| Polars | Native | - | Native | - | - | - |
| DataFusion | Native | Experimental | - | - | - | - |

## Quick Start

### Basic Conversion

```bash
# Generate TPC-H data first
benchbox run --platform duckdb --benchmark tpch --scale 1 --phases generate

# Convert to Parquet
benchbox convert --input ./benchmark_runs/tpch_sf1 --format parquet
```

### Query Converted Data

```python
import duckdb

# Connect and query Parquet files
conn = duckdb.connect()
result = conn.execute("""
    SELECT l_returnflag, SUM(l_extendedprice) as revenue
    FROM read_parquet('./benchmark_runs/tpch_sf1/lineitem.parquet')
    GROUP BY l_returnflag
""").fetchdf()
```

## Format Deep Dive <!-- content-ok: cliche -->

### Apache Parquet

The most widely supported columnar format. Ideal for analytics workloads and data interchange.

**Structure:**
```
customer.parquet
├── Row Group 0
│   ├── Column: c_custkey (INT64, snappy)
│   ├── Column: c_name (STRING, dictionary)
│   └── Column: c_acctbal (DECIMAL, snappy)
├── Row Group 1
│   └── ...
└── Footer (schema, statistics)
```

**Usage:**
```bash
# Basic conversion
benchbox convert --input ./data --format parquet

# With Zstd compression (best ratio)
benchbox convert --input ./data --format parquet --compression zstd

# Partitioned by date
benchbox convert --input ./data --format parquet --partition l_shipdate
```

**Reading Parquet:**
```python
# DuckDB
conn.execute("SELECT * FROM read_parquet('customer.parquet')")

# PyArrow
import pyarrow.parquet as pq
table = pq.read_table('customer.parquet')

# Polars
import polars as pl
df = pl.read_parquet('customer.parquet')

# Pandas
import pandas as pd
df = pd.read_parquet('customer.parquet')
```

### Vortex

A high-performance columnar file format optimized for analytical workloads with excellent compression.

**Structure:**
```
customer.vortex
├── Encoded column chunks
│   ├── Column: c_custkey (INT64, compressed)
│   ├── Column: c_name (STRING, dictionary)
│   └── Column: c_acctbal (DECIMAL, compressed)
└── Footer (schema, statistics)
```

**Installation:**
```bash
uv add vortex-data
```

**Usage:**
```bash
# Basic conversion
benchbox convert --input ./data --format vortex

# With compression
benchbox convert --input ./data --format vortex --compression zstd
```

**Reading Vortex:**
```python
# Python vortex library
import vortex
array = vortex.io.read('customer.vortex')
table = array.to_arrow()

# DuckDB (requires vortex extension)
conn.execute("INSTALL vortex; LOAD vortex;")
conn.execute("SELECT * FROM read_vortex('customer.vortex')")
```

### Delta Lake

Open table format with ACID transactions, built on Parquet files.

**Structure:**
```
customer/
├── _delta_log/
│   ├── 00000000000000000000.json  # Initial commit
│   └── 00000000000000000001.json  # Update commit
├── part-00000-*.parquet
└── part-00001-*.parquet
```

**Features:**
- **ACID Transactions**: Concurrent reads/writes with isolation
- **Time Travel**: Query historical versions of data
- **Schema Evolution**: Add/remove columns without rewriting
- **Unified Batch/Streaming**: Same table for both workloads

**Installation:**
```bash
uv add deltalake
```

**Usage:**
```bash
# Convert to Delta Lake
benchbox convert --input ./data --format delta

# With compression
benchbox convert --input ./data --format delta --compression zstd
```

**Reading Delta Lake:**
```python
# Python deltalake library
from deltalake import DeltaTable
dt = DeltaTable('./customer')
df = dt.to_pandas()

# DuckDB (requires delta extension)
conn.execute("INSTALL delta; LOAD delta;")
conn.execute("SELECT * FROM delta_scan('./customer')")

# Spark
df = spark.read.format("delta").load("./customer")
```

**Time Travel:**
```python
# Query specific version
dt = DeltaTable('./customer', version=0)

# Query by timestamp
dt = DeltaTable('./customer', as_of='2024-01-15T10:00:00')
```

### Apache Iceberg

Modern table format designed for large-scale data lakes with enterprise features.

**Structure:**
```
customer/
├── metadata/
│   ├── v1.metadata.json
│   ├── snap-*.avro  # Snapshot manifests
│   └── *.avro       # Manifest files
└── data/
    └── *.parquet    # Data files
```

**Features:**
- **Hidden Partitioning**: Partition columns not exposed in queries
- **Schema Evolution**: Full schema changes without data rewrite
- **Snapshot Isolation**: Consistent reads during writes
- **Partition Evolution**: Change partitioning without rewriting data

**Installation:**
```bash
uv add pyiceberg
```

**Usage:**
```bash
# Convert to Iceberg
benchbox convert --input ./data --format iceberg

# With partitioning
benchbox convert --input ./data --format iceberg --partition l_shipdate
```

**Reading Iceberg:**
```python
# PyIceberg
from pyiceberg.catalog import load_catalog
catalog = load_catalog("local", **{"type": "sql", "uri": "sqlite:///catalog.db"})
table = catalog.load_table("default.customer")
df = table.scan().to_pandas()

# Spark
df = spark.read.format("iceberg").load("./customer")
```

### Apache Hudi

Open table format optimized for incremental processing and record-level operations.

**Structure:**
```
customer/
├── .hoodie/
│   ├── hoodie.properties      # Table metadata
│   └── *.commit               # Commit timeline
└── data/
    └── *.parquet              # Data files with Hudi metadata
```

**Features:**
- **Record-Level ACID**: Update and delete individual records efficiently
- **Incremental Processing**: Query only changed data since last commit
- **COPY_ON_WRITE**: Faster reads, better for analytics workloads
- **MERGE_ON_READ**: Faster writes, better for streaming workloads
- **Time Travel**: Query historical versions via commit timeline

**Installation:**
```bash
# Hudi requires PySpark with hudi-spark-bundle
pip install pyspark
# Configure Spark with: spark.jars.packages=org.apache.hudi:hudi-spark3.5-bundle_2.12:0.14.0
```

**Usage:**
Hudi operations require PySpark SQL. For direct Hudi support, use the Quanton platform:

```bash
# Via Quanton platform (recommended)
benchbox run --platform quanton --benchmark tpch --scale 1.0 \
  --platform-option table_format=hudi \
  --platform-option record_key=l_orderkey
```

**Reading Hudi:**
```python
# PySpark
spark = SparkSession.builder \
    .config("spark.jars.packages", "org.apache.hudi:hudi-spark3.5-bundle_2.12:0.14.0") \
    .getOrCreate()

df = spark.read.format("hudi").load("./customer")

# Incremental query (changes since last commit)
df = spark.read.format("hudi") \
    .option("hoodie.datasource.query.type", "incremental") \
    .option("hoodie.datasource.read.begin.instanttime", "20240101000000") \
    .load("./customer")
```

**Time Travel:**
```python
# Query specific timestamp
df = spark.read.format("hudi") \
    .option("as.of.instant", "20240115100000") \
    .load("./customer")
```

### DuckLake

DuckDB's native open table format with full ACID transactions, time travel, and optimal DuckDB performance.

**Structure:**
```
customer/
├── metadata.ducklake          # DuckLake metadata catalog
└── data/
    └── *.parquet              # Data stored as Parquet files
```

**Features:**
- **ACID Transactions**: Full transactional support with snapshot isolation
- **Time Travel**: Query historical versions of data
- **Schema Evolution**: Add/modify columns without rewriting data
- **Native DuckDB Integration**: Optimal performance with DuckDB query engine
- **Predicate Pushdown**: Filter data at the storage layer

**Installation:**
```bash
# DuckLake is part of DuckDB >= 1.2.0, no separate installation needed
# The ducklake extension is auto-installed on first use
```

**Usage:**
```bash
# Convert to DuckLake
benchbox convert --input ./data --format ducklake

# With compression
benchbox convert --input ./data --format ducklake --compression zstd
```

**Reading DuckLake:**
```python
import duckdb

conn = duckdb.connect()

# Install and load the ducklake extension
conn.execute("INSTALL ducklake; LOAD ducklake;")

# Attach DuckLake database
conn.execute("""
    ATTACH 'ducklake:./customer/metadata.ducklake' AS ducklake_db
    (DATA_PATH './customer/data')
""")

# Query the table
result = conn.execute("SELECT * FROM ducklake_db.main.customer").fetchdf()
```

**Time Travel:**
```python
# DuckLake supports querying historical snapshots
# Query specific version (when supported by your DuckDB version)
conn.execute("""
    SELECT * FROM ducklake_db.main.customer
    AT SNAPSHOT 'snapshot_id'
""")
```

**When to Use DuckLake:**
- **DuckDB-centric workflows**: When DuckDB is your primary analytics engine
- **Local development**: Fast iteration with full ACID guarantees
- **Single-engine scenarios**: When you don't need multi-engine compatibility
- **Benchmarking DuckDB**: Compare DuckLake vs Delta Lake vs Iceberg performance

## Compression Guide

### Compression Algorithms

| Algorithm | Compression | Speed | Use Case |
|-----------|-------------|-------|----------|
| **Snappy** | Moderate | Fast | Default, good balance |
| **Gzip** | Good | Slow | Cold storage, archival |
| **Zstd** | Best | Moderate | Large datasets, cloud storage |
| **None** | None | Fastest | Debugging, already compressed |

### Compression Benchmarks (TPC-H SF=10)

```
Format          | Algorithm | Size (MB) | Compress Time | Query Time
----------------|-----------|-----------|---------------|------------
TBL (raw)       | -         | 10,240    | -             | baseline
Parquet         | snappy    | 3,413     | 45s           | 0.32x
Parquet         | gzip      | 2,560     | 120s          | 0.35x
Parquet         | zstd      | 2,048     | 65s           | 0.33x
Delta Lake      | snappy    | 3,450     | 48s           | 0.34x
```

### Choosing Compression

```bash
# Fast iteration during development
benchbox convert --input ./data --format parquet --compression snappy

# Production with best compression
benchbox convert --input ./data --format parquet --compression zstd

# Cloud storage (minimize transfer costs)
benchbox convert --input ./data --format parquet --compression zstd
```

## Partitioning Guide

### When to Partition

Partitioning is beneficial when:
- Table has >1M rows
- Queries frequently filter on specific columns (dates, regions, status)
- Data has natural partitioning boundaries

### Partition Column Selection

**Good partition columns:**
- Date/time columns (l_shipdate, o_orderdate)
- Categorical columns with 10-1000 distinct values (l_returnflag, c_mktsegment)
- Region/geography columns

**Bad partition columns:**
- High cardinality columns (customer_id, order_id)
- Columns rarely used in filters

### Partitioning Examples

```bash
# Single partition column (date-based)
benchbox convert --input ./data --format parquet --partition l_shipdate
# Creates: lineitem/l_shipdate=1996-01-01/part-*.parquet

# Multiple partition columns (hierarchical)
benchbox convert --input ./data --format parquet \
    --partition l_returnflag --partition l_linestatus
# Creates: lineitem/l_returnflag=N/l_linestatus=O/part-*.parquet
```

### Querying Partitioned Data

```sql
-- DuckDB: Hive partitioning
SELECT * FROM read_parquet('./lineitem/**/*.parquet', hive_partitioning=true)
WHERE l_shipdate = '1996-03-15';  -- Only reads relevant partition

-- Partition pruning filters are pushed down automatically
```

## Platform Integration

### DuckDB

```python
import duckdb

conn = duckdb.connect()

# Parquet
conn.execute("SELECT * FROM read_parquet('./data/*.parquet')")

# Delta Lake
conn.execute("INSTALL delta; LOAD delta;")
conn.execute("SELECT * FROM delta_scan('./data/customer')")

# DuckLake (native table format)
conn.execute("INSTALL ducklake; LOAD ducklake;")
conn.execute("""
    ATTACH 'ducklake:./data/customer/metadata.ducklake' AS ducklake_db
    (DATA_PATH './data/customer/data')
""")
conn.execute("SELECT * FROM ducklake_db.main.customer")

# Partitioned Parquet
conn.execute("""
    SELECT * FROM read_parquet('./lineitem/**/*.parquet', hive_partitioning=true)
    WHERE l_shipdate >= '1996-01-01'
""")
```

### Polars

```python
import polars as pl

# Parquet
df = pl.read_parquet('./data/customer.parquet')

# Delta Lake
df = pl.read_delta('./data/customer')

# Lazy evaluation for large datasets
lf = pl.scan_parquet('./data/*.parquet')
result = lf.filter(pl.col('c_acctbal') > 1000).collect()
```

### PySpark

```python
from pyspark.sql import SparkSession

spark = SparkSession.builder \
    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
    .getOrCreate()

# Parquet
df = spark.read.parquet('./data/customer.parquet')

# Delta Lake
df = spark.read.format("delta").load('./data/customer')

# Iceberg
df = spark.read.format("iceberg").load('./data/customer')

# Hudi
df = spark.read.format("hudi").load('./data/customer')
```

### Databricks

```python
# Parquet (auto-detected)
df = spark.read.load('/mnt/data/customer.parquet')

# Delta Lake (default format)
df = spark.read.load('/mnt/data/customer')

# Iceberg
df = spark.read.format("iceberg").load('/mnt/data/customer')

# Hudi
df = spark.read.format("hudi").load('/mnt/data/customer')
```

### Onehouse Quanton

```python
# Quanton supports all three table formats via Spark SQL
# Use BenchBox CLI for streamlined access:
# benchbox run --platform quanton --benchmark tpch \
#   --platform-option table_format=hudi
```

## Best Practices

### 1. Choose the Right Format

| Scenario | Recommended Format |
|----------|-------------------|
| One-time analysis | Parquet |
| Shared datasets | Parquet |
| Maximum compression | Vortex |
| DuckDB/DataFusion analytics | Vortex |
| Production data lake | Delta Lake |
| Multi-engine access | Iceberg |
| Schema changes expected | Iceberg |
| Streaming/upsert workloads | Hudi |
| Record-level updates | Hudi |
| Time travel needed | Delta Lake, DuckLake |
| DuckDB-native workflows | DuckLake |
| Local development with ACID | DuckLake |

### 2. Compression Strategy

```bash
# Development (fast iteration)
--compression snappy

# Production (storage optimization)
--compression zstd

# Cloud storage (minimize costs)
--compression zstd
```

### 3. Validation

```bash
# Always validate for TPC compliance
benchbox convert --input ./data --format parquet --validate

# Skip validation only for exploratory work
benchbox convert --input ./data --format parquet --no-validate
```

### 4. Directory Organization

```
benchmark_runs/
├── tpch_sf1_tbl/           # Raw TBL files
├── tpch_sf1_parquet/       # Parquet conversion
├── tpch_sf1_vortex/        # Vortex for high compression
├── tpch_sf1_ducklake/      # DuckLake for DuckDB-native workflows
├── tpch_sf10_delta/        # Delta Lake for larger scale
├── tpch_sf10_hudi/         # Hudi for streaming/upsert workloads
└── tpch_sf100_iceberg/     # Iceberg for production
```

## Troubleshooting

### Conversion Fails with "vortex not installed"

```bash
uv add vortex-data
```

### Conversion Fails with "deltalake not installed"

```bash
uv add deltalake
```

### Conversion Fails with "pyiceberg not installed"

```bash
uv add pyiceberg
```

### Conversion Fails with "DuckLake extension not available"

DuckLake requires DuckDB >= 1.2.0. The extension is auto-installed on first use:

```python
import duckdb
conn = duckdb.connect()
conn.execute("INSTALL ducklake; LOAD ducklake;")
```

If installation fails, ensure you have a compatible DuckDB version:

```bash
uv add "duckdb>=1.2.0"
```

### Row Count Mismatch

If validation fails with row count mismatch:
1. Check source TBL files for corruption
2. Regenerate data with `--force datagen`
3. If intentional, use `--no-validate`

### Large File Handling

For very large scale factors (SF > 100):
```bash
# Use Zstd for best compression
benchbox convert --input ./data --format parquet --compression zstd

# Skip validation if conversion is slow
benchbox convert --input ./data --format parquet --no-validate
```

## See Also

- [CLI Reference: convert](../reference/cli/convert.md) - Full command options
- [Data Generation](../usage/data-generation.md) - Generating benchmark data
- [DuckDB Platform](../platforms/duckdb.md) - DuckDB integration
- [Performance Optimization](performance-optimization.md) - Query performance tuning

### Table Format Guides

For conceptual depth on each format, see the Table Format Guides:

- [Table Format Guides Overview](../guides/table-formats/index.md) - When format choice matters for benchmarks
- [Parquet Deep Dive](../guides/table-formats/parquet-deep-dive.md) - Row groups, compression options, statistics <!-- content-ok: cliche -->
- [Delta Lake Guide](../guides/table-formats/delta-lake-guide.md) - Transaction overhead, OPTIMIZE, Z-ORDER
- [Apache Iceberg Guide](../guides/table-formats/iceberg-guide.md) - Multi-engine support, partition evolution
- [Vortex Guide](../guides/table-formats/vortex-guide.md) - Composable encodings, maturity considerations
