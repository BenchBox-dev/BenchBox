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

`insert_block_size` rejects `1000` and any non-positive value.

`clickhouse-cloud` sets `max_memory_usage` and `max_threads` to `0` so the
managed service handles sizing.

### Container memory limits

`max_memory_usage` is a **per-query** limit. It does not track any memory limit
set on a containerized ClickHouse server. When you run the server in a container,
size the two together and leave the container headroom above the per-query limit
for background MergeTree merges and caches.

## Tuned Runs

`--tuning tuned` applies a curated template for TPC-H, SSB and TPC-DS:
MergeTree sort keys, plus monthly partitions on the TPC-H `LINEITEM` and
`ORDERS` tables. The same templates serve the local, server and cloud platforms
(`examples/tunings/clickhouse/`, packaged with BenchBox). For other
benchmarks there is no curated template, so `--tuning tuned` resolves to the
fallback. ClickHouse's "OLAP session pack" session settings apply to tuned runs
either way.

```bash
benchbox run --platform clickhouse-server --benchmark tpch --tuning tuned
```

The templates disable every constraint, so a table the template sorts has no
`PRIMARY KEY` clause and its sort key is the index. A table the template does
not tune keeps the schema's primary key and derives its `ORDER BY` from it. If you supply a template that enables
`primary_keys`, its columns must be a prefix of the tuned sort key, or the run
fails before any table is created.

`OPTIMIZE TABLE ... FINAL` is off by default. To run it on each table after it
loads, set `--platform-option optimize_after_load=true`. It runs on tuned runs
only. Its time is reported as `phases.post_load_maintenance` and is not
counted in data-loading time.

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
