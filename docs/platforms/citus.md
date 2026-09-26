<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Citus Platform

```{tags} intermediate, guide, citus, sql-platform, postgresql-extension, distributed
```

> **CLI name:** `citus` - use `benchbox run --platform citus`

Citus is a PostgreSQL extension that transparently distributes tables across a coordinator and worker nodes. BenchBox provides first-class Citus support for benchmarking distributed PostgreSQL workloads.

## Features

- **Extension gating** - Connection setup verifies (or creates) `citus` with an actionable install error otherwise
- **Opt-in distribution** - Pass `distribution_column` to distribute every benchmark table with `create_distributed_table` after schema creation
- **Graceful fallback** - Tables lacking the distribution column stay coordinator-local with a warning instead of failing the run
- **Version provenance** - The installed `citus` version is recorded in platform info
- **PostgreSQL compatible** - Standard PostgreSQL wire protocol, dialect, and COPY loading

## Quick Start

```bash
# Coordinator-local tables (measures single-node Postgres on a Citus server)
benchbox run --platform citus --benchmark tpch --scale 0.01

# Distributed TPC-H on l_orderkey
benchbox run --platform citus --benchmark tpch --scale 1.0 \
  --platform-option host=citus.example.com \
  --platform-option password=secret \
  --platform-option distribution_column=l_orderkey
```

## Installation

### Python Dependencies

Citus uses the same Python driver as PostgreSQL:

```bash
uv add psycopg2-binary
```

### Server Requirements

Citus must be installed on the PostgreSQL coordinator (and workers for real distribution). The recommended approach is Docker.

**Docker (recommended):**

```bash
docker run -d --name citus \
  -e POSTGRES_PASSWORD=benchbox \
  -p 5432:5432 \
  citusdata/citus:latest

# Verify extension
psql -h localhost -U postgres -c "CREATE EXTENSION citus;"
```

See the [Citus GitHub repository](https://github.com/citusdata/citus) for worker setup and additional installation methods.

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `host` | `localhost` | Citus coordinator hostname |
| `port` | `5432` | Citus coordinator port |
| `database` | auto-generated | Database name |
| `username` | `postgres` | PostgreSQL username |
| `password` | (none) | PostgreSQL password |
| `schema` | `public` | PostgreSQL schema name |
| `distribution_column` | (none) | Distribute every benchmark table on this column (unset keeps coordinator-local tables) |

## Known Limitations

- **Single distribution column** - One column applies to every benchmark table; per-table control is future work. Dimension tables that lack the column stay coordinator-local by design.
- **Coordinator-only default** - Without `distribution_column`, tables are coordinator-local and the run measures single-node Postgres, not distribution.

## Recommended Benchmarks

- **TPC-H** - Standard OLAP benchmark; distribute on `l_orderkey` for lineitem-heavy queries
- **TPC-DS** - Complex OLAP; pick a store-sales key present across the fact tables being measured
