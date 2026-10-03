# PostgreSQL Extension Docker Compose Files

Docker Compose configurations for running PostgreSQL with analytical extensions.
Each extension has its own Compose file because some extensions conflict with each other.

## Quick Start

```bash

docker compose -f docker-compose.pg-duckdb.yaml up -d

docker compose -f docker-compose.pg-mooncake.yaml up -d

docker compose -f docker-compose.timescaledb.yaml up -d
```

## Running Benchmarks

```bash
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
docker compose -f docker-compose.pg-duckdb.yaml down

docker compose -f docker-compose.pg-duckdb.yaml down -v
```
