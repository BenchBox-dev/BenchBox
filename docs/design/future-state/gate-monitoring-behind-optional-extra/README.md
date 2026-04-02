<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Monitoring Optional Extra Future State

```{tags} contributor, architecture
```

Related TODO: `gate-monitoring-behind-optional-extra`

## Future State

The monitoring package is excluded from the default wheel via MANIFEST.in and
gated behind a `benchbox[monitoring]` optional extra. Default installs do not
carry monitoring code. The runner gracefully degrades when monitoring is not
installed, benchmark execution works identically, reports simply omit
resource/timing detail.

## Why This Is Valuable

- Default installs become smaller and more focused on core benchmarking.
- The monitoring boundary is explicit: users opt in via `benchbox[monitoring]`.
- Monitoring source stays in the repo for development and testing.

## How The End State Is Used

Default install (no monitoring):

```bash
uv add benchbox
benchbox run --platform duckdb --benchmark tpch --scale 0.01
```

With monitoring:

```bash
uv add benchbox[monitoring]
benchbox run --platform duckdb --benchmark tpch --scale 0.01 -v
benchbox report benchmark_runs/results/latest.json
```

## BenchBox After The Refactor

- MANIFEST.in excludes `benchbox/monitoring/` from the default wheel.
- pyproject.toml defines a `monitoring` optional extra.
- Runner imports monitoring conditionally (try/except ImportError).
- Monitoring source code stays in the repo, testable from source checkout.

## Non-Goals

- Extracting monitoring into a standalone `runwatch` package (~2,000 lines
  with one consumer does not justify a separate distribution)
- Changing timing keys or report schemas
- Introducing a network service or daemon requirement
