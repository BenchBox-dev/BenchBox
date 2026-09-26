<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# ParadeDB Platform

```{tags} intermediate, guide, paradedb, sql-platform, postgresql-extension
```

> **CLI name:** `paradedb` - use `benchbox run --platform paradedb`

ParadeDB is a PostgreSQL extension for hybrid search and analytics workloads. Its `pg_analytics` extension adds Elasticsearch-compatible BM25 full-text search over ordinary PostgreSQL heap tables. BenchBox provides first-class ParadeDB support for benchmarking analytics workloads on ParadeDB-backed PostgreSQL.

## Features

- **Heap tables** - Benchmark tables stay ordinary PostgreSQL heap tables loaded through the inherited COPY path
- **Extension gating** - Connection setup verifies (or creates) `pg_analytics` with an actionable install error otherwise
- **Version provenance** - The installed `pg_analytics` version is recorded in platform info
- **PostgreSQL compatible** - Standard PostgreSQL wire protocol, dialect, and COPY loading

## Quick Start

```bash
# Basic TPC-H benchmark
benchbox run --platform paradedb --benchmark tpch --scale 0.01

# With custom connection
benchbox run --platform paradedb --benchmark tpch --scale 1.0 \
  --platform-option host=paradedb.example.com \
  --platform-option password=secret
```

## Installation

### Python Dependencies

ParadeDB uses the same Python driver as PostgreSQL:

```bash
uv add psycopg2-binary
```

### Server Requirements

ParadeDB must be installed on the PostgreSQL server. The recommended approach is Docker.

**Docker (recommended):**

```bash
docker run -d --name paradedb \
  -e POSTGRES_PASSWORD=benchbox \
  -p 5432:5432 \
  paradedb/paradedb:latest

# Verify extension
psql -h localhost -U postgres -c "CREATE EXTENSION pg_analytics;"
```

See the [ParadeDB GitHub repository](https://github.com/paradedb/paradedb) for additional installation methods.

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `host` | `localhost` | PostgreSQL server hostname |
| `port` | `5432` | PostgreSQL server port |
| `database` | auto-generated | Database name |
| `username` | `postgres` | PostgreSQL username |
| `password` | (none) | PostgreSQL password |
| `schema` | `public` | PostgreSQL schema name |

## Recommended Benchmarks

- **TPC-H** - Standard OLAP benchmark on ParadeDB-backed heap tables
- **TPC-DS** - Complex OLAP; same heap-table path as PostgreSQL
