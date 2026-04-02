# BenchBox CLI Reference

This document is the canonical command reference for the `benchbox` CLI.
It is intended to complement `benchbox --help` with a stable, searchable
overview of core commands, common flags, and practical invocation patterns.

BenchBox supports SQL and DataFrame benchmark execution across local and
cloud platforms. Most commands can be run in interactive mode or fully
non-interactive mode with explicit flags.

## Command Reference

### Global Patterns

- Base command: `benchbox <command> [options]`
- Non-interactive runs: use `--non-interactive` plus explicit benchmark inputs.
- Help topics: many commands support `--help-topic examples` and `--help-topic all`.
- Verbosity: use `-v` or `-vv` for diagnostics, and `--quiet` for minimal output.

### `benchbox run`

Runs a benchmark lifecycle (generate, load, execute phases) with optional
phase control, compression settings, and platform-specific options.

Common flags:

- `--platform <name>`
- `--benchmark <name>`
- `--scale <float>`
- `--phases <csv>`
- `--non-interactive`
- `--dry-run <output-dir>`
- `--compression <none|gzip|zstd|bzip2|xz>`
- `--seed <int>`

Examples:

- `benchbox run --platform duckdb --benchmark tpch --scale 0.01 --phases power --non-interactive`
- `benchbox run --platform polars-df --benchmark tpch --scale 0.01 --non-interactive`
- `benchbox run --platform duckdb --benchmark tpch --scale 0.1 --dry-run ./preview --phases generate,load`

### `benchbox profile`

Collects system profile and benchmark-oriented diagnostics to support
capacity planning and performance troubleshooting.

### `benchbox validate`

Validates benchmark configuration and execution readiness, including
syntax checks and platform dependency checks where applicable.

### `benchbox benchmarks list`

Lists available benchmark suites with concise descriptions and
expected runtime characteristics.

### `benchbox results`

Displays benchmark execution history and summary metrics from stored
artifacts under `benchmark_runs/`.

### `benchbox export`

Exports result files to structured output formats for downstream analysis
and reporting automation.

### `benchbox check-deps`

Checks optional platform dependencies and prints installation guidance.

### `benchbox visualize`

Generates ASCII charts from benchmark result JSON files. Auto-discovers
recent results if no files are specified. Supports chart type selection,
templates, themes, and pipe-friendly output modes.

### `benchbox report`

Historical result analysis with subcommands: `rankings` (platform
comparisons), `trends` (performance over time), `regressions` (detect
slowdowns), `import` (load results into database), `stats`, and `list`.

### `benchbox metrics qphh`

Calculates the TPC-H QphH@Size composite metric from power and throughput
test results. Auto-detects scale factor from result files.

### `benchbox aggregate`

Aggregates multiple result JSON files into a CSV with geometric mean,
p50/p95/p99 statistics per run. Useful for trend tracking.

### `benchbox datagen`

Standalone data generation (wrapper for `benchbox run --phases generate`).
Supports benchmark, scale, format, and seed options.

### `benchbox setup`

Interactive cloud credential configuration for Databricks, Snowflake,
BigQuery, Redshift, and Athena. Includes validation, status checks,
and Redshift connectivity diagnostics.

### `benchbox show-plan`

Displays a query execution plan from benchmark results as an ASCII tree,
summary, or JSON. Requires plans captured with `--capture-plans`.

### `benchbox plan-history`

Shows query plan evolution across runs with fingerprint tracking and
optional plan flapping detection.

### `benchbox download-answers`

Pre-downloads TPC-H and TPC-DS answer files to a local cache for
offline row-count validation.

## Notes

- Cloud platforms may require explicit output/staging roots.
- TPC scale-factor rules apply (for example, TPC SF >= 1 must be integers).
- Some test and benchmark flows rely on optional extras that are not installed
  in minimal environments.
