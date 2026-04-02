<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Docker Integration Tests

```{tags} contributor, guide, testing
```

Run real integration tests against database engines in Docker containers. No cloud credentials needed.

## Overview

Docker integration tests execute real queries against real database engines running locally in Docker containers. Unlike stub-based smoke tests (which only verify adapter wiring), these tests catch:

- SQL dialect incompatibilities
- Data type mapping errors
- Connection handling bugs
- Schema creation/cleanup failures
- Query execution correctness

**Cost**: Free (Docker only, no cloud credentials).

## Supported Platforms

| Platform | Docker Image | Ports | Protocol |
|----------|-------------|-------|----------|
| ClickHouse | `clickhouse/clickhouse-server:24.8` | 9000, 8123 | Native TCP / HTTP |
| Trino | `trinodb/trino:439` | 18080 -> 8080 | HTTP (DBAPI) |
| Presto | `prestodb/presto:0.289` | 18081 -> 8080 | HTTP (DBAPI) |
| PostgreSQL | `postgres:16` | 5432 | PostgreSQL wire |
| StarRocks | `starrocks/allin1-ubuntu:3.3.0` | 19030 -> 9030, 18040 -> 8040 | MySQL / HTTP Stream Load |
| Doris | `apache/doris:doris-all-in-one-2.1.0` | 19031 -> 9030, 18030 -> 8030 | MySQL / HTTP Stream Load |
| Databend | `datafuselabs/databend` + MinIO | 8000, 19000 -> 9000, 19001 -> 9001 | HTTP/DSN |
| InfluxDB | `influxdb:3-core` | 8181 | HTTP (FlightSQL) |

## Quick Start

```bash
# Test a single platform (starts Docker, runs tests, stops Docker)
make test-docker-clickhouse

# Test all Docker platforms sequentially
make test-docker-all
```

## Available Makefile Targets

| Target | Description |
|--------|-------------|
| `make test-docker-<platform>` | Full lifecycle: start service, run tests, stop service |
| `make test-docker-up-<platform>` | Start service only (for interactive debugging) |
| `make test-docker-down-<platform>` | Stop service and remove volumes |
| `make test-docker-all` | Run all Docker platform tests sequentially |
| `make test-docker-up-all` | Start all Docker services |
| `make test-docker-down-all` | Stop all Docker services |

Replace `<platform>` with: `clickhouse`, `trino`, `presto`, `postgresql`, `starrocks`, `doris`, `databend`, `influxdb`.

## Running Tests Manually

If you prefer to manage Docker services separately:

```bash
# 1. Start the service
make test-docker-up-clickhouse

# 2. Run tests (with verbose output)
uv run -- python -m pytest -m "live_clickhouse" --tb=short -v

# 3. Stop when done
make test-docker-down-clickhouse
```

Or using pytest markers directly:

```bash
# Run all Docker integration tests (services must be running)
uv run -- python -m pytest -m "docker_integration" --tb=short -v

# Run a specific platform
uv run -- python -m pytest -m "live_postgresql" --tb=short -v
```

## Pytest Markers

| Marker | Description |
|--------|-------------|
| `docker_integration` | All Docker-based integration tests |
| `live_integration` | All live tests (Docker + cloud) |
| `live_clickhouse` | ClickHouse-specific tests |
| `live_trino` | Trino-specific tests |
| `live_presto` | Presto-specific tests |
| `live_postgresql` | PostgreSQL-specific tests |
| `live_starrocks` | StarRocks-specific tests |
| `live_doris` | Doris-specific tests |
| `live_databend` | Databend-specific tests |
| `live_influxdb` | InfluxDB-specific tests |

## Graceful Skip Behavior

Tests skip automatically when their Docker service isn't running:

```
SKIPPED [1] test_clickhouse_live.py:44: Skipping ClickHouse Docker test: service not reachable at localhost:9000
```

This means:
- `make test-fast` is never affected by Docker availability
- CI pipelines can selectively enable Docker platforms
- Developers only need Docker for the platforms they're working on

## Platform Notes

### Host Port Overrides

The Docker test compose files use unique default host ports so `make test-docker-up-all`
can start every platform together. If you override those defaults and reintroduce a port
collision, run the affected platforms sequentially.

### Stack Isolation

BenchBox Docker test targets use isolated Docker Compose project names, so running
`make test-docker-<platform>` does not tear down an unrelated stack you already started
with the same compose file. The tracked `make test-docker-up-<platform>` and
`make test-docker-down-<platform>` targets still pair together for interactive debugging.

### Default Credentials

All Docker services use test-only credentials defined in their compose files:

| Platform | User | Password | Database |
|----------|------|----------|----------|
| ClickHouse | `default` | (empty) | `default` |
| Trino | `benchbox` | (none) | (none) |
| Presto | `benchbox` | (none) | (none) |
| PostgreSQL | `benchbox` | `benchbox` | `benchbox_test` |
| StarRocks | `root` | (empty) | (none) |
| Doris | `root` | (empty) | (none) |
| Databend | `benchbox` | `benchbox` | `default` |
| InfluxDB | (auth disabled) | (none) | `benchbox_test` |

### Startup Times

Most services start in under 10 seconds. StarRocks and Doris can take 30-60 seconds. The `docker compose up --wait` flag (used by Makefile targets) blocks until the healthcheck passes.

## Comparison: Test Tiers

| Tier | What It Tests | When It Runs | Cost |
|------|--------------|-------------|------|
| **Stub smoke tests** | Adapter wiring, SQL patterns, config validation | Always (CI, local) | Free |
| **Docker integration** | Real queries, data loading, schema CRUD | On demand (`make test-docker-*`) | Free |
| **Cloud live tests** | Full cloud workflow with real credentials | On demand (`make test-live-*`) | $0.05-0.20/run |

## Troubleshooting

### Service won't start

```bash
# Check Docker daemon is running
docker info

# Check for port conflicts
lsof -i :9000  # example: ClickHouse port

# View service logs
docker compose -f docker/clickhouse/docker-compose.yml logs
```

### Tests skip even though Docker is running

The `skip_unless_docker_service()` helper probes `localhost:<port>` with a 2-second timeout. If the service is still starting, wait for the healthcheck:

```bash
docker compose -f docker/clickhouse/docker-compose.yml up --wait
```

### Clean up stale containers

```bash
make test-docker-down-all
# or manually
docker compose -f docker/clickhouse/docker-compose.yml down -v
```
