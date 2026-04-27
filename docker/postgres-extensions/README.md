# PostgreSQL Extension Docker Compose Files

Docker Compose configurations for running PostgreSQL with analytical extensions.
Each extension has its own Compose file because some extensions conflict with each other.

## Quick Start

```bash
# Start ONE extension at a time on port 5432:

# pg_duckdb - DuckDB-accelerated PostgreSQL
docker compose -f docker-compose.pg-duckdb.yaml up -d

# pg_mooncake - Columnstore PostgreSQL
docker compose -f docker-compose.pg-mooncake.yaml up -d

# TimescaleDB - Time-series PostgreSQL
docker compose -f docker-compose.timescaledb.yaml up -d
```

## Running Benchmarks

```bash
# After starting the container:
benchbox run --platform pg-duckdb --benchmark tpch --scale 0.01 \
  --platform-option host=localhost --platform-option password=benchbox

benchbox run --platform pg-mooncake --benchmark tpch --scale 0.01 \
  --platform-option host=localhost --platform-option password=benchbox

benchbox run --platform timescaledb --benchmark tsbs-devops --scale 1.0 \
  --platform-option host=localhost --platform-option password=benchbox
```

## Extension Compatibility

| Extension | pg_duckdb | pg_mooncake | TimescaleDB |
|-----------|-----------|-------------|-------------|
| pg_duckdb | - | **CONFLICT** | Compatible |
| pg_mooncake | **CONFLICT** | - | Compatible |
| TimescaleDB | Compatible | Compatible | - |

**pg_duckdb and pg_mooncake cannot coexist** in the same PostgreSQL instance
(shared `libduckdb.so`). Use separate containers for each.

## Default Credentials

All containers use the same defaults for simplicity:

| Setting | Value |
|---------|-------|
| User | `postgres` |
| Password | `benchbox` |
| Database | `benchbox` |
| Port | `5432` |

## Cleanup

```bash
# Stop and remove a specific container
docker compose -f docker-compose.pg-duckdb.yaml down

# Stop and remove with volumes (deletes data)
docker compose -f docker-compose.pg-duckdb.yaml down -v
```
