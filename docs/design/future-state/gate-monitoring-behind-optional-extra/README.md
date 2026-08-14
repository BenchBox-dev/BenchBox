<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Monitoring Optional Extra Future State

```{tags} contributor, architecture
```

Related TODO: `gate-monitoring-behind-optional-extra`

## Status (2026-08-13)

**Blocked on evidence; the proposal is not implemented.** The current default
wheel still contains five `benchbox.monitoring` entries, and `psutil>=5.9.0`
remains a core dependency. The measured baseline does not show an install-size
win for moving monitoring behind an optional extra.

Measured on `origin/develop` at `723126bf3` with `uv build --wheel`:

| Measure | Result |
| --- | --- |
| Wheel | 10,219,657 bytes; 1,325 archive entries |
| `benchbox.monitoring` entries | 5 |
| Warm `import benchbox` in five fresh processes | 0.298–0.409 seconds; environment setup excluded |

Keep monitoring in the default wheel and keep the core dependency until a
follow-up supplies a measured size win and a second-consumer or demand case.

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
