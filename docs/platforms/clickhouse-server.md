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
