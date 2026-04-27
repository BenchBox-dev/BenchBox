<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# CedarDB Platform

```{tags} intermediate, guide, cedardb, sql-platform
```

> **CLI name:** `cedardb` - use `benchbox run --platform cedardb`

CedarDB (formerly Umbra, from TU Munich) is a high-performance standalone RDBMS
supporting both OLAP and OLTP workloads over the PostgreSQL wire protocol.
BenchBox drives CedarDB through its PostgreSQL adapter, with OLAP-tuned session
defaults and standard `COPY` for bulk loading.

## Features

- **HTAP engine** - OLAP and OLTP on the same storage, compiled query execution
- **PostgreSQL-compatible** - standard Postgres drivers (`psycopg`), tools (`psql`, DBeaver, DataGrip)
- **Standalone** - not a Postgres extension; its own engine and storage
- **Bulk loading** - standard PostgreSQL `COPY` is fully supported
- **OLAP-tuned defaults** - session-level settings applied at connection time

## Deployment Modes

| Mode          | Description                                                    |
| ------------- | -------------------------------------------------------------- |
| `self-hosted` | Self-hosted CedarDB server over PG wire protocol (default)     |

```bash
# Self-hosted (default)
benchbox run --platform cedardb --benchmark tpch --scale 1.0
```

## Installation

CedarDB uses the same Python driver as PostgreSQL:

```bash
uv add benchbox --extra postgresql
```

Run a local CedarDB server (see [CedarDB docs](https://cedardb.com/docs/) for
install options). Default PG-wire port is `5432`.

## Configuration

Connection parameters mirror PostgreSQL and are provided via BenchBox's
standard credential flow (`benchbox credentials …`) or passed inline with
`--platform-option`:

```bash
benchbox run --platform cedardb --benchmark tpch --scale 1.0 \
  --platform-option host=localhost \
  --platform-option port=5432 \
  --platform-option username=postgres \
  --platform-option database=benchbox
```

Defaults come from the `cedardb` credential store entry (see
`benchbox credentials`). If you prefer environment-driven configuration, store
`${PGHOST}`-style placeholders in that credential entry and let BenchBox resolve
them at runtime; there is no dedicated `CEDARDB_*` environment-variable surface.

## Supported Benchmarks

CedarDB inherits the PostgreSQL dialect, so it can in principle run any BenchBox
benchmark supported on PostgreSQL - TPC-H, TPC-DS, SSB, Join Order, Read
Primitives, Write Primitives, Transaction Primitives, and similar. Individual
benchmark/tuning combinations require validation; partitioning and clustering
tuning are not yet verified.

## Notes

- Data types, functions, and COPY syntax follow PostgreSQL. OLAP session
  defaults (planner GUCs, page-cost tuning) are applied automatically during
  `configure_for_benchmark()` - no CLI flag is required.
- CedarDB is positioned as an HTAP engine - transactional workloads such as
  Transaction Primitives will also run.
- For large scale factors, prefer `--compression zstd` on staged data files to
  speed up `COPY`.

## See Also

- [PostgreSQL Platform](postgresql.md) - parent dialect and driver
- [pg_duckdb](pg_duckdb.md), [pg_mooncake](pg_mooncake.md) - Postgres-compatible
  analytics alternatives
