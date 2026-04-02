<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# TimescaleDB Platform

```{tags} intermediate, guide, timescaledb, sql-platform
```

TimescaleDB is a PostgreSQL extension for time-series workloads with hypertables, native compression, and continuous aggregates. BenchBox supports both self-hosted TimescaleDB and managed TigerData cloud deployments via the same adapter.

## Features

- Automatic hypertable conversion for time-series tables
- Native compression policies for historical data
- PostgreSQL-compatible wire protocol and COPY loading
- Cloud deployment mode with SSL enforcement
- TSBS and SQL benchmark support

## Deployment Modes

Use deployment mode colon syntax with `--platform`:

```bash
# Self-hosted (default)
benchbox run --platform timescaledb --benchmark tsbs-devops --scale 1.0

# TigerData managed cloud
benchbox run --platform timescaledb:cloud --benchmark tpch --scale 0.01
```

### Self-Hosted Mode

Use your own PostgreSQL server with TimescaleDB extension installed.

- Full database lifecycle operations are supported
- Default connection behavior is inherited from the PostgreSQL adapter

### TigerData Cloud Mode

Use TigerData managed PostgreSQL service.

- Requires SSL (`sslmode=require` by default)
- Skips DROP/CREATE database management for managed environments
- Uses `timescaledb:cloud` platform syntax
- `TIGERDATA_*` environment variables are primary; `TIMESCALE_*` are also accepted as fallback

## Cloud Connection Setup

### Option A: Service URL (recommended)

```bash
export TIGERDATA_SERVICE_URL='postgres://tsdbadmin:password@abc123.tsdb.cloud.timescale.com:5432/tsdb?sslmode=require'

benchbox run --platform timescaledb:cloud --benchmark tpch --scale 0.01 --non-interactive
```

Fallback remains supported:

```bash
export TIMESCALE_SERVICE_URL='postgres://tsdbadmin:password@abc123.tsdb.cloud.timescale.com:5432/tsdb?sslmode=require'
```

### Option B: Individual Environment Variables

```bash
# Primary (preferred)
export TIGERDATA_HOST='abc123.rc8ft3nbrw.tsdb.cloud.timescale.com'
export TIGERDATA_PASSWORD='your-password'
export TIGERDATA_USER='tsdbadmin'        # optional (default: tsdbadmin)
export TIGERDATA_PORT='5432'             # optional (default: 5432)
export TIGERDATA_DATABASE='tsdb'         # optional (default: tsdb)

benchbox run --platform timescaledb:cloud --benchmark tpch --scale 0.01 --non-interactive
```

Fallback (used if `TIGERDATA_*` is unset):

```bash
export TIMESCALE_HOST='abc123.rc8ft3nbrw.tsdb.cloud.timescale.com'
export TIMESCALE_PASSWORD='your-password'
export TIMESCALE_USER='tsdbadmin'
export TIMESCALE_PORT='5432'
export TIMESCALE_DATABASE='tsdb'
```

## Installation

```bash
uv add psycopg2-binary
```

Server must have TimescaleDB 2.x extension enabled:

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
```

## Common Commands

```bash
# TPC-H smoke on TigerData cloud
benchbox run --platform timescaledb:cloud --benchmark tpch --scale 0.01 --phases power --non-interactive

# TSBS on self-hosted TimescaleDB
benchbox run --platform timescaledb --benchmark tsbs-devops --scale 1.0 --non-interactive

# Self-hosted with compression options
benchbox run --platform timescaledb --benchmark tsbs-devops --scale 1.0 \
  --platform-option chunk_interval='1 day' \
  --platform-option compression_enabled=true \
  --platform-option compression_after='7 days' \
  --non-interactive
```

## Platform Options

| Option | Default | Description |
|--------|---------|-------------|
| `host` | `localhost` (self-hosted) | Server hostname |
| `port` | `5432` | Server port |
| `database` | auto/generated or `tsdb` (cloud) | Database name |
| `username` | `postgres` (self-hosted), `tsdbadmin` (cloud) | Login user |
| `password` | none | Login password |
| `schema` | `public` | Target schema |
| `chunk_interval` | `1 day` | Hypertable chunk interval |
| `compression_enabled` | `false` | Enable automatic compression |
| `compression_after` | `7 days` | Age threshold for compression |
| `service_url` | none | Parsed for cloud mode (`TIGERDATA_SERVICE_URL` or fallback) |

## SSL Requirements

TigerData cloud requires TLS. BenchBox defaults cloud mode to `sslmode=require`. `sslmode=verify-full` is not yet configured by default in BenchBox.

## Troubleshooting

```bash
# Verify TimescaleDB extension
psql -c "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';"

# Check cloud connectivity manually
psql "$TIGERDATA_SERVICE_URL"
```

## Related

- [Platform Selection Guide](platform-selection-guide.md)
- [PostgreSQL Platform](postgresql.md)
- [Comparison Matrix](comparison-matrix.md)
