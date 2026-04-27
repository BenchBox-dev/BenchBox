<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# pg_duckdb Platform

```{tags} intermediate, guide, pg-duckdb, sql-platform, postgresql-extension
```

> **CLI name:** `pg-duckdb` - use `benchbox run --platform pg-duckdb`

pg_duckdb is a PostgreSQL extension that embeds DuckDB's columnar-vectorized analytics engine inside PostgreSQL, accelerating OLAP queries without requiring SQL changes or data migration. BenchBox provides first-class pg_duckdb support for benchmarking DuckDB-accelerated PostgreSQL workloads.

## Features

- **DuckDB vectorized execution** - Analytical queries routed through DuckDB's high-performance engine
- **No SQL changes needed** - Existing PostgreSQL queries work transparently
- **Configurable execution** - Force DuckDB execution or let PostgreSQL decide per query
- **Parallel table scanning** - Configurable thread count for PostgreSQL heap table scans
- **PostgreSQL compatible** - Uses PostgreSQL COPY for efficient bulk loading
- **MotherDuck integration** - Optional cloud offload for hybrid local+cloud queries
- **Two deployment modes** - Self-hosted and MotherDuck

## Deployment Modes

pg_duckdb supports two deployment modes, selectable via the colon syntax:

```bash
# Self-hosted (default) - PostgreSQL with pg_duckdb extension
benchbox run --platform pg-duckdb --benchmark tpch --scale 1.0

# MotherDuck mode - hybrid local+cloud queries
benchbox run --platform pg-duckdb:motherduck --benchmark tpch --scale 1.0
```

### Self-Hosted Mode (Default)

Connect to a PostgreSQL server with pg_duckdb extension installed:
- pg_duckdb 1.0+ extension must be installed on the server
- Full database management (CREATE/DROP database) available
- DuckDB execution engine handles analytical queries on heap tables

### MotherDuck Mode

Connect pg_duckdb to MotherDuck for hybrid queries:
- Requires MOTHERDUCK_TOKEN for authentication
- Enables queries that join local PostgreSQL tables with MotherDuck cloud data
- Sign up at [motherduck.com](https://app.motherduck.com/token)

**MotherDuck Configuration:**

```bash
# Set MotherDuck token
export MOTHERDUCK_TOKEN=your-token-here

# Run benchmark with MotherDuck hybrid mode
benchbox run --platform pg-duckdb:motherduck --benchmark tpch --scale 1.0
```

## Installation

### Python Dependencies

pg_duckdb uses the same Python driver as PostgreSQL:

```bash
uv add psycopg2-binary
```

### Server Requirements

pg_duckdb must be installed on the PostgreSQL server. See the
[pg_duckdb GitHub repository](https://github.com/duckdb/pg_duckdb) for installation instructions.

**Docker (recommended for testing):**

```bash
docker run -d --name pg-duckdb \
  -e POSTGRES_PASSWORD=benchbox \
  -p 5432:5432 \
  pgduckdb/pgduckdb:18-v1.1.1

# Verify extension
psql -h localhost -U postgres -c "CREATE EXTENSION pg_duckdb;"
```

## Quick Start

```bash
# Basic TPC-H benchmark
benchbox run --platform pg-duckdb --benchmark tpch --scale 0.01

# With custom connection
benchbox run --platform pg-duckdb --benchmark tpch --scale 1.0 \
  --platform-option host=pgduckdb.example.com \
  --platform-option password=secret

# Disable force execution (let PostgreSQL choose when to use DuckDB)
benchbox run --platform pg-duckdb --benchmark tpch --scale 1.0 \
  --platform-option force_execution=false

# Configure parallel scan threads
benchbox run --platform pg-duckdb --benchmark tpch --scale 1.0 \
  --platform-option postgres_scan_threads=8
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
| `force_execution` | `true` | Force DuckDB execution for all queries |
| `postgres_scan_threads` | `0` (auto) | Threads for parallel PostgreSQL table scanning |

## How It Works

pg_duckdb accelerates queries by routing them through DuckDB's vectorized execution engine:

1. **Schema creation** - Standard PostgreSQL DDL (CREATE TABLE) is used
2. **Data loading** - PostgreSQL COPY loads data into standard heap tables
3. **Query execution** - With `force_execution=true`, queries are executed by DuckDB's engine
4. **Results** - Results are returned through the standard PostgreSQL wire protocol

### Performance Characteristics

- **Up to ~4x faster** than PostgreSQL with full indexes on TPC-H
- **Up to 1500x faster** on specific TPC-DS queries vs unindexed PostgreSQL
- **Row-oriented storage** - Data remains in PostgreSQL heap format (no columnar compression)
- **Best for** analytical scans, aggregations, and joins
- **Less benefit for** point lookups and index-dependent OLTP queries

## Comparison with Other Platforms

| Aspect | pg_duckdb | Native DuckDB | PostgreSQL |
|--------|-----------|---------------|------------|
| Storage | PostgreSQL heap | DuckDB columnar | PostgreSQL heap |
| Execution | DuckDB vectorized | DuckDB vectorized | PostgreSQL row-based |
| SQL dialect | PostgreSQL | DuckDB | PostgreSQL |
| Data loading | COPY (psycopg2) | Direct file read | COPY (psycopg2) |
| Compression | No (heap tables) | Yes (columnar) | No (heap tables) |
| Best for | Adding analytics to existing PG | Standalone analytics | Transactional + basic analytics |

## Known Limitations

- **Extension conflicts** - pg_duckdb cannot coexist with pg_mooncake (shared libduckdb.so). Use separate PostgreSQL instances for each.
- **Row-oriented storage** - Queries operate on PostgreSQL's row-oriented heap tables, missing DuckDB's columnar compression benefits.
- **Server installation required** - pg_duckdb must be pre-installed on the PostgreSQL server; BenchBox cannot install it remotely.
- **GUC permissions** - Thread count tuning may require superuser or pg_duckdb role privileges.

## Recommended Benchmarks

- **TPC-H** - Standard OLAP benchmark; shows pg_duckdb's analytical acceleration
- **TPC-DS** - Complex OLAP benchmark; demonstrates vectorized execution benefits
- **ClickBench** - Real-world analytical queries; good for comparison with columnar stores
