<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# pg_mooncake Platform

```{tags} intermediate, guide, pg-mooncake, sql-platform, postgresql-extension, columnstore
```

> **CLI name:** `pg-mooncake` - use `benchbox run --platform pg-mooncake`

pg_mooncake is a PostgreSQL extension that adds native columnstore tables with DuckDB-powered vectorized execution. Data is stored in Parquet format with Iceberg metadata, providing 5-20x columnar compression and top-10 ClickBench performance. BenchBox provides first-class pg_mooncake support for benchmarking columnstore PostgreSQL workloads.

## Features

- **Columnstore mirrors** - BenchBox heap-loads with COPY, then promotes loaded tables with `mooncake.create_table`
- **DuckDB execution** - Vectorized query engine for analytical workloads
- **Columnar compression** - 5-20x compression ratios vs PostgreSQL heap tables
- **Object storage** - Optional S3/GCS backend for Parquet data
- **PostgreSQL compatible** - Uses standard PostgreSQL wire protocol and COPY loading before columnstore promotion
- **Top-10 ClickBench** - Competitive with dedicated OLAP engines on real-world analytical queries

## Quick Start

```bash
# Basic TPC-H benchmark with columnstore mirrors
benchbox run --platform pg-mooncake --benchmark tpch --scale 0.01

# With custom connection
benchbox run --platform pg-mooncake --benchmark tpch --scale 1.0 \
  --platform-option host=mooncake.example.com \
  --platform-option password=secret

# With S3 storage backend
benchbox run --platform pg-mooncake --benchmark tpch --scale 1.0 \
  --platform-option storage_mode=s3 \
  --platform-option mooncake_bucket=s3://my-bucket/mooncake-data
```

## Installation

### Python Dependencies

pg_mooncake uses the same Python driver as PostgreSQL:

```bash
uv add psycopg2-binary
```

### Server Requirements

pg_mooncake must be installed on the PostgreSQL server. The recommended approach is Docker.

**Docker (recommended):**

```bash
docker run -d --name pg-mooncake \
  -e POSTGRES_PASSWORD=benchbox \
  -p 5432:5432 \
  mooncakelabs/pg_mooncake:latest

# Verify extension
psql -h localhost -U postgres -c "CREATE EXTENSION pg_mooncake;"
```

See the [pg_mooncake GitHub repository](https://github.com/Mooncake-Labs/pg_mooncake) for additional installation methods.

## How It Works

pg_mooncake transforms PostgreSQL into a hybrid analytical database:

1. **Schema creation** - BenchBox creates PostgreSQL heap tables so COPY remains supported
2. **Data loading** - PostgreSQL COPY loads benchmark files into the heap tables
3. **Promotion** - BenchBox renames the loaded heap tables and exposes mooncake mirrors with the original benchmark table names
4. **Query execution** - Queries on the mooncake mirrors are routed through DuckDB's vectorized engine
5. **Results** - Results are returned through the standard PostgreSQL wire protocol

### Storage Architecture

```
PostgreSQL Instance
├── pg_mooncake extension
│   ├── Columnstore Access Method (USING mooncake)
│   ├── pg_moonlink (WAL-based ingestion)
│   └── DuckDB execution engine
└── Storage Backend
    ├── Local disk (default) → Parquet files
    └── Object storage (S3/GCS) → Parquet files with Iceberg metadata
```

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `host` | `localhost` | PostgreSQL server hostname |
| `port` | `5432` | PostgreSQL server port |
| `database` | auto-generated | Database name |
| `username` | `postgres` | PostgreSQL username |
| `password` | (none) | PostgreSQL password |
| `schema` | `public` | PostgreSQL schema name |
| `storage_mode` | `local` | Storage backend: `local` (disk) or `s3` (object storage) |
| `mooncake_bucket` | (none) | S3/GCS bucket URL (required when `storage_mode=s3`) |

### S3 Storage Configuration

```bash
# Set S3 bucket via environment variable
export MOONCAKE_S3_BUCKET=s3://my-bucket/mooncake-data

# Or via platform option
benchbox run --platform pg-mooncake --benchmark tpch \
  --platform-option storage_mode=s3 \
  --platform-option mooncake_bucket=s3://my-bucket/data
```

S3 mode requires standard AWS credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`).

## Comparison with Other Platforms

| Aspect | pg_mooncake | pg_duckdb | Native DuckDB | PostgreSQL |
|--------|-------------|-----------|---------------|------------|
| Storage | Columnstore (Parquet) | PostgreSQL heap | DuckDB columnar | PostgreSQL heap |
| Execution | DuckDB vectorized | DuckDB vectorized | DuckDB vectorized | PostgreSQL row-based |
| Compression | 5-20x (columnar) | No (heap) | Yes (columnar) | No (heap) |
| Load path | COPY into heap, then mooncake mirror promotion | COPY into heap | Native load | COPY into heap |
| Workload | OLAP columnstore | OLAP acceleration | Standalone analytics | General purpose |
| ClickBench rank | Top 10 | Not ranked | Top 5 | Not ranked |

## Known Limitations

- **Extension conflicts** - pg_mooncake cannot coexist with standalone pg_duckdb (shared libduckdb.so). Use separate PostgreSQL instances for each.
- **Direct COPY limitation** - pg_mooncake 0.2.0 does not support COPY directly into `USING mooncake` tables; BenchBox uses heap-load plus mirror promotion.
- **Data type support** - Not all PostgreSQL data types are supported on columnstore tables. The extension is actively evolving.
- **No constraints** - Columnstore tables don't support PRIMARY KEY, FOREIGN KEY, or other constraints.
- **No indexes** - B-tree and other indexes are not applicable to columnstore tables.
- **Server installation required** - pg_mooncake must be pre-installed on the PostgreSQL server; Docker is the recommended setup method.

## Recommended Benchmarks

- **TPC-H** - Standard OLAP benchmark; demonstrates columnstore compression and DuckDB execution benefits
- **ClickBench** - Real-world analytical queries; pg_mooncake is a top-10 performer
- **TPC-DS** - Complex OLAP; note some data types may not be fully supported yet
