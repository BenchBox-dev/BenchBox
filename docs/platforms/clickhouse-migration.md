# ClickHouse Platform Migration Guide

BenchBox previously exposed a single `clickhouse` base platform with mixed
local/server behavior. That design has been replaced by three first-class
platform identifiers:

| Platform | Mode | Driver | Use case |
|---|---|---|---|
| `clickhouse-local` | In-process (chDB) | `chdb` | Embedded analytics, zero infrastructure |
| `clickhouse-server` | Self-hosted (TCP) | `clickhouse-driver` | Docker, dedicated server, cluster |
| `clickhouse-cloud` | Managed cloud (HTTPS) | `clickhouse-connect` | ClickHouse Cloud service |

## Quick Reference

```bash
# Embedded ClickHouse (chDB) - no server required
benchbox run --platform clickhouse-local --benchmark tpch --scale 0.01

# Self-hosted / Docker ClickHouse
benchbox run --platform clickhouse-server --benchmark tpch --scale 0.01 \
  --platform-option host=localhost \
  --platform-option port=9000

# Managed ClickHouse Cloud
benchbox run --platform clickhouse-cloud --benchmark tpch --scale 0.01 \
  --platform-option host=abc123.us-east-2.aws.clickhouse.cloud \
  --platform-option password=my-password
```

## Installation

```bash
# clickhouse-local (chDB embedded)
uv add benchbox --extra clickhouse-local

# clickhouse-server (self-hosted via clickhouse-driver)
uv add benchbox --extra clickhouse-server
# or equivalently:
uv add benchbox --extra clickhouse

# clickhouse-cloud (managed via clickhouse-connect)
uv add benchbox --extra clickhouse-cloud
```

## Migrating from Legacy Selectors

The following legacy selectors emit a `DeprecationWarning` and continue to work
during the migration window. They will be removed in a future release.

| Legacy selector | Canonical replacement |
|---|---|
| `--platform clickhouse` | `--platform clickhouse-local` (default) |
| `--platform clickhouse:local` | `--platform clickhouse-local` |
| `--platform clickhouse:server` | `--platform clickhouse-server` |
| `--platform clickhouse:cloud` | `--platform clickhouse-cloud` |
| `--platform clickhouse --platform-option deployment_mode=local` | `--platform clickhouse-local` |
| `--platform clickhouse --platform-option deployment_mode=server` | `--platform clickhouse-server` |

### Bare `clickhouse`

Bare `--platform clickhouse` resolves to `clickhouse-local` by default (the
chDB embedded path). If you relied on `--platform clickhouse` for a real
server, switch to `--platform clickhouse-server`.

### Config Files

YAML configuration files that reference `clickhouse` will continue to work
during the migration window. To silence the warning, update:

```yaml
# Before (deprecated)
platform: clickhouse
deployment_mode: local

# After
platform: clickhouse-local
```

```yaml
# Before (deprecated)
platform: clickhouse
deployment_mode: server

# After
platform: clickhouse-server
```

## Historical Result Artifacts

Result JSON files written before this migration may contain
`"platform_type": "clickhouse"` or related legacy labels. These files remain
readable during the migration window. Bulk artifact relabeling is deferred
until after alias removal.

## What Was Changed

- `clickhouse-local` and `clickhouse-server` are now registered as first-class
  platform identifiers in the registry, adapter factory, CLI, DDL generator,
  cost calculator, and dependency surfaces.
- `clickhouse-cloud` was already a first-class platform and is unchanged.
- Bare `clickhouse` and colon-suffix syntax are compatibility aliases with
  explicit `DeprecationWarning` emission.
- Shared ClickHouse SQL dialect, workload, and tuning logic is unchanged and
  shared across all three platform identifiers.

## Alias Removal Timeline

Alias removal will happen in a follow-up release after the deprecation window.
Tracked in: `deferred` items of the `first-class-clickhouse-local-server-cloud-platforms` TODO.
