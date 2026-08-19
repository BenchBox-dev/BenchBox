# ClickHouse Server Platform

`clickhouse-server` is the BenchBox platform for benchmarking self-hosted
ClickHouse instances - Docker containers, bare-metal servers, and clusters -
via the native TCP binary protocol (`clickhouse-driver`).

## Installation

```bash
uv add benchbox --extra clickhouse-server
# or equivalently:
uv add benchbox --extra clickhouse
```

## Quick Start

```bash
# Start a local ClickHouse server with Docker
docker run -d --name clickhouse-server \
  -p 9000:9000 -p 8123:8123 \
  clickhouse/clickhouse-server

# Run a TPC-H benchmark
benchbox run --platform clickhouse-server --benchmark tpch --scale 0.01
```

## Connection Options

| Option | Default | Description |
|---|---|---|
| `host` | `localhost` | ClickHouse server hostname |
| `port` | `9000` | Native TCP protocol port |
| `username` | `default` | Authentication username |
| `password` | `` | Authentication password |
| `secure` | `false` | Enable TLS |

```bash
benchbox run --platform clickhouse-server --benchmark tpch \
  --platform-option host=my-clickhouse.example.com \
  --platform-option port=9000 \
  --platform-option username=default \
  --platform-option password=secret \
  --platform-option secure=false
```

## Performance Options

These carry BenchBox defaults rather than ClickHouse's own, and are set as
session settings on each connection.

| Option | Default | Description |
|---|---|---|
| `max_memory_usage` | `8GB` | Per-query memory limit |
| `max_threads` | `8` | Query parallelism (`clickhouse-local` defaults to `4`) |
| `max_execution_time` | `300` | Per-query timeout in seconds |
| `insert_block_size` | `65536` | Rows per native streaming insert block |
| `send_receive_timeout` | `300` | Driver socket timeout in seconds |
| `compression` | `false` | Disabled by default (`clickhouse-cityhash` compatibility on Python 3.13+) |

`insert_block_size` rejects `1000` and any non-positive value. That guard is
deliberate: the loader streams natively and must never fall back to the
historical 1,000-row application batch.

`clickhouse-cloud` sets `max_memory_usage` and `max_threads` to `0` so the
managed service handles sizing.

### Relationship to the UAT container limit

`max_memory_usage` is a **per-query** limit. It is independent of the memory
ceiling applied to a containerized server, which the UAT managed stack sets from
`preflight.clickhouse_memory_limit` (default `8g`) via `CLICKHOUSE_MEMORY_LIMIT`
in `docker/clickhouse/docker-compose.yml`.

The two default to the same figure but are configured in different places and do
not track each other: overriding the compose rung does not adjust the per-query
default, and vice versa. When running a containerized server, size them together
and leave the container headroom above the per-query limit for background
MergeTree merges and caches.

Whether these two defaults should be coupled is an open question, recorded under
"Follow-up ownership" in
[ADR: `clickhouse-server` Containerization and Linux SF1 Certification](../development/adr/adr-clickhouse-server-containerization.md).
For how the container rung is selected and admitted, see
[the UAT framework doc](../operations/uat-framework.md).

## Docker Integration Testing

ClickHouse server Docker tests use the existing Compose stack:

```bash
make test-docker-clickhouse
```

## Comparison with Other ClickHouse Platforms

| | `clickhouse-local` | `clickhouse-server` | `clickhouse-cloud` |
|---|---|---|---|
| Infrastructure | None (in-process) | Docker / dedicated | Managed service |
| Driver | `chdb` | `clickhouse-driver` | `clickhouse-connect` |
| Network | None | TCP 9000 | HTTPS 8443 |
| Credentials | Not required | Optional | Required |
| Windows | Not supported | Supported | Supported |

See [clickhouse-migration.md](clickhouse-migration.md) for migration from
legacy `clickhouse:server` selectors.
