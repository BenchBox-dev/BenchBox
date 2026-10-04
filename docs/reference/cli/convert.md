(cli-convert)=
# `convert` - Convert Data Formats

```{tags} reference, cli
```

Convert benchmark data from TBL (pipe-delimited) format to optimized columnar formats like Parquet, Vortex, Delta Lake, Apache Iceberg, or DuckLake.

## Basic Syntax

```bash
benchbox convert --input PATH --format FORMAT [OPTIONS]
```

## Why Convert Formats?

Converting TPC benchmark data to columnar formats provides benefits:

- **Query Performance**: Faster query execution due to columnar storage and compression (improvement varies by query selectivity)
- **Storage Efficiency**: Better compression ratio compared to raw TBL files (typically 3-5x)
- **Platform Compatibility**: Native support in modern data platforms (Databricks, Snowflake, etc.)
- **Analytics Features**: Partition pruning, predicate pushdown, and statistics-based optimization

## Core Options

**Required:**
- `--input PATH`: Input directory containing benchmark data and `_datagen_manifest.json`
- `--format FORMAT`: Target format (`parquet`, `vortex`, `delta`, `iceberg`, `ducklake`)

**Output:**
- `--output PATH`: Output directory (default: same as input)

**Compression:**
- `--compression CODEC`: Compression algorithm (default: `snappy`)
  - `snappy` - Fast compression, moderate ratio (default)
  - `gzip` - Better ratio, slower compression
  - `zstd` - Best ratio, moderate speed
  - `none` - No compression

**Partitioning:**
- `--partition COLUMN`: Column(s) to partition by (can be specified multiple times)
  - Creates Hive-style partitioning (`column=value/` directories)
  - Enables partition pruning for filtered queries

**Schema:**
- `--benchmark NAME`: Benchmark name for schema lookup (auto-detected from manifest if not specified)

**Validation:**
- `--validate/--no-validate`: Validate row counts after conversion (default: enabled)
  - Ensures data integrity and TPC compliance
  - Disable with `--no-validate` for faster conversion (not TPC compliant)

**Debugging:**
- `--verbose, -v`: Enable verbose output

## Supported Formats

### Apache Parquet

Columnar storage format with efficient compression and encoding.

```bash
benchbox convert --input ./data/tpch_sf1 --format parquet
```

**Characteristics:**
- Single file per table (or partitioned directory)
- Excellent query engine support (DuckDB, Spark, Polars, etc.)
- Row group statistics for predicate pushdown
- No external dependencies required (uses PyArrow)

### Vortex

High-performance columnar format with excellent compression for analytical workloads.

```bash
benchbox convert --input ./data/tpch_sf1 --format vortex
```

**Characteristics:**
- Single file per table
- Optimized for analytical scan workloads
- Excellent compression ratio
- DuckDB support via extension, DataFusion experimental support
- **Requires**: `vortex-data` package (`uv add vortex-data`)

### Delta Lake

Open table format with ACID transactions and time travel.

```bash
benchbox convert --input ./data/tpch_sf1 --format delta
```

**Characteristics:**
- Directory-based format with `_delta_log/` transaction log
- ACID transactions and concurrent writes
- Time travel (query historical versions)
- Schema evolution support
- **Requires**: `deltalake` package (`uv add deltalake`)

### Apache Iceberg

Modern table format with hidden partitioning and schema evolution.

```bash
benchbox convert --input ./data/tpch_sf1 --format iceberg
```

**Characteristics:**
- Directory-based format with `metadata/` directory
- Hidden partitioning (partition columns not exposed in schema)
- Schema evolution without rewriting data
- Snapshot isolation
- **Requires**: `pyiceberg` package (`uv add pyiceberg`)

### DuckLake

DuckDB's native open table format with full ACID transactions and time travel.

```bash
benchbox convert --input ./data/tpch_sf1 --format ducklake
```

**Characteristics:**
- Directory-based format with `metadata.ducklake` catalog and `data/` directory
- Full ACID transactions with snapshot isolation
- Time travel (query historical versions)
- Schema evolution support
- Native DuckDB integration with optimal performance
- **Requires**: DuckDB >= 1.2.0 (ducklake extension auto-installs)

## Examples

### Basic Conversion

```bash
benchbox convert --input ./benchmark_runs/tpch_sf1 --format parquet

benchbox convert --input ./benchmark_runs/tpch_sf1 --format delta

benchbox convert --input ./benchmark_runs/tpch_sf1 --format ducklake
```

The first command converts TPC-H data to Parquet with default settings, the second converts to Delta Lake, and the third converts to DuckLake (DuckDB's native table format).

### Compression Options

```bash
benchbox convert --input ./data/tpch_sf10 --format parquet --compression zstd

benchbox convert --input ./data/tpch_sf10 --format parquet --compression gzip

benchbox convert --input ./data/tpch_sf1 --format parquet --compression none
```

Use Zstd for the best compression ratio, gzip for compatibility with older systems, and no compression for debugging.

### Partitioned Output

```bash
benchbox convert --input ./data/tpch_sf1 --format parquet \
    --partition l_shipdate

benchbox convert --input ./data/tpch_sf1 --format parquet \
    --partition l_returnflag --partition l_linestatus

benchbox convert --input ./data/tpch_sf10 --format delta \
    --partition l_shipdate
```

The first command partitions the lineitem table by ship date. The second uses multiple partition columns (hierarchical), and the third partitions a Delta Lake table by date.

### Performance Optimization

```bash
benchbox convert --input ./data/tpch_sf100 --format parquet --no-validate

benchbox convert --input ./data/tpch_sf1 --format parquet --verbose
```

`--no-validate` skips validation for faster conversion, but the result is not TPC compliant. `--verbose` gives detailed output for debugging.

### Separate Output Directory

```bash
benchbox convert --input ./raw_data/tpch_sf1 --format parquet \
    --output ./converted_data/tpch_sf1_parquet
```

This writes the converted data to a different directory.

## Output

The convert command displays progress and summary information:

```
Converting to PARQUET
Input: ./benchmark_runs/tpch_sf1
Compression: snappy
Row validation: enabled

Converting 8 tables...
  ✓ customer: 150,000 rows, compression: 2.45x
  ✓ lineitem: 6,001,215 rows, compression: 3.12x
  ✓ nation: 25 rows, compression: 1.89x
  ✓ orders: 1,500,000 rows, compression: 2.87x
  ✓ part: 200,000 rows, compression: 2.34x
  ✓ partsupp: 800,000 rows, compression: 2.56x
  ✓ region: 5 rows, compression: 1.67x
  ✓ supplier: 10,000 rows, compression: 2.23x

Summary:
  Tables converted: 8
  Total rows: 8,661,245
  Source size: 1024.5 MB
  Output size: 342.1 MB
  Overall compression: 2.99x
  Manifest updated: ./benchmark_runs/tpch_sf1/_datagen_manifest.json
```

## Using Converted Data

### With DuckDB

```sql
SELECT * FROM read_parquet('./data/customer.parquet');

SELECT * FROM read_parquet('./data/lineitem/**/*.parquet', hive_partitioning=true);

INSTALL delta;
LOAD delta;
SELECT * FROM delta_scan('./data/lineitem');

INSTALL ducklake;
LOAD ducklake;
ATTACH 'ducklake:./data/lineitem/metadata.ducklake' AS ducklake_db (DATA_PATH './data/lineitem/data');
SELECT * FROM ducklake_db.main.lineitem;
```

The statements read a Parquet file, a partitioned Parquet dataset, a Delta Lake table (this requires the delta extension) and a DuckLake table (DuckDB's native format), in that order.

### With Python

```python
import duckdb
import pyarrow.parquet as pq

table = pq.read_table('./data/customer.parquet')
df = table.to_pandas()

conn = duckdb.connect()
df = conn.execute("SELECT * FROM read_parquet('./data/customer.parquet')").fetchdf()

from deltalake import DeltaTable
dt = DeltaTable('./data/customer')
df = dt.to_pandas()

conn.execute("INSTALL ducklake; LOAD ducklake;")
conn.execute("""
    ATTACH 'ducklake:./data/customer/metadata.ducklake' AS ducklake_db
    (DATA_PATH './data/customer/data')
""")
df = conn.execute("SELECT * FROM ducklake_db.main.customer").fetchdf()
```

The examples read Parquet with PyArrow, Parquet with DuckDB, a Delta Lake table, and a DuckLake table, in that order.

## Prerequisites

The `convert` command requires:

1. **Generated benchmark data**: Run `benchbox run --phases generate` first
2. **Valid manifest**: `_datagen_manifest.json` in the input directory

For Vortex, Delta Lake, and Iceberg formats, install optional dependencies:

```bash
uv add vortex-data

uv add deltalake

uv add pyiceberg
```

These provide Vortex, Delta Lake and Apache Iceberg support, in that order.

DuckLake requires DuckDB >= 1.2.0 but has no additional dependencies - the ducklake extension auto-installs on first use.

## Troubleshooting

### "Manifest not found"

Ensure you've generated benchmark data first:

```bash
benchbox run --platform duckdb --benchmark tpch --scale 1 --phases generate
```

### "Could not get schemas from benchmark"

The benchmark type couldn't be auto-detected. Specify it explicitly:

```bash
benchbox convert --input ./data --format parquet --benchmark tpch
```

### "vortex package not installed"

Install the Vortex package:

```bash
uv add vortex-data
```

### "deltalake package not installed"

Install the Delta Lake package:

```bash
uv add deltalake
```

### "pyiceberg package not installed"

Install the PyIceberg package:

```bash
uv add pyiceberg
```

## See Also

- [Open Table Formats Guide](../../advanced/format-conversion.md) - Detailed guide on format selection and usage
- [Data Generation](../../usage/data-generation.md) - Generating benchmark data
- [Performance Optimization](../../advanced/performance-optimization.md) - Optimizing benchmark performance
