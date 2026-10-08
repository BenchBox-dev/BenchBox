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

The commands run embedded ClickHouse (chDB, no server required), a self-hosted or Docker ClickHouse server, and managed
ClickHouse Cloud.

```bash
benchbox run --platform clickhouse-local --benchmark tpch --scale 0.01

benchbox run --platform clickhouse-server --benchmark tpch --scale 0.01 \
  --platform-option host=localhost \
  --platform-option port=9000

benchbox run --platform clickhouse-cloud --benchmark tpch --scale 0.01 \
  --platform-option host=abc123.us-east-2.aws.clickhouse.cloud \
  --platform-option password=my-password
```

## Installation

The extras are `clickhouse-local` (chDB embedded), `clickhouse-server` (self-hosted, via `clickhouse-driver`) and
`clickhouse-cloud` (managed, via `clickhouse-connect`). `--extra clickhouse` is equivalent to `--extra
clickhouse-server`.

```bash
uv add benchbox --extra clickhouse-local

uv add benchbox --extra clickhouse-server
uv add benchbox --extra clickhouse

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

### Bare `clickhouse` (removed)

Bare `--platform clickhouse` has been **removed** after its deprecation window
(shipped v0.2.1, removed after v0.3.1). It now raises an error naming the
replacements instead of silently defaulting to `clickhouse-local`. Choose the
first-class name explicitly: `clickhouse-local` (embedded chDB),
`clickhouse-server` (self-hosted), or `clickhouse-cloud` (managed). The
explicit `clickhouse:local` / `clickhouse:server` / `clickhouse:cloud`
selectors still work (they emit a deprecation warning and route to the
first-class name).

### Config Files

YAML configuration files that use bare `clickhouse` no longer resolve and must
be updated to a first-class name:

The first two lines are the old configuration, which was removed and now errors. The last line is the new one.

```yaml
platform: clickhouse
deployment_mode: local

platform: clickhouse-local
```

Again, the first two lines are the removed configuration, and the last line is the replacement.

```yaml
platform: clickhouse
deployment_mode: server

platform: clickhouse-server
```

## Historical Result Artifacts

Result JSON files written before this migration may contain
`"platform_type": "clickhouse"` or related legacy labels. These files remain
readable.

## What Was Changed

- `clickhouse-local` and `clickhouse-server` are first-class platform names
  everywhere a platform is selected, including the CLI and configuration files.
- `clickhouse-cloud` was already a first-class platform and is unchanged.
- Bare `clickhouse` has been removed and now raises an error naming the
  first-class replacements. Colon-suffix syntax (`clickhouse:local`, etc.)
  remains a compatibility alias with explicit `DeprecationWarning` emission.
- SQL dialect, workloads, and tuning behave the same on all three platforms.

## Alias Removal Timeline

The bare `clickhouse` alias has now been **removed** (after the v0.2.1 → v0.3.1
deprecation window); passing it raises an error naming the first-class
replacements. The colon-suffix selectors (`clickhouse:local` / `:server` /
`:cloud`) remain as deprecating aliases.
