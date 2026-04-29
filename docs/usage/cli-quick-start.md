<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# BenchBox CLI - Quick Reference

```{tags} beginner, cli, reference
```

BenchBox ships with a full-featured CLI implemented with Click. This guide focuses on the commands and flags you will touch most often.

## Essential Commands

| Command | What it does |
| --- | --- |
| `benchbox profile` | Inspect CPU, memory, Python version, and platform availability. |
| `benchbox benchmarks list` | Show all shipped benchmarks and their categories. |
| `benchbox run` | Launch the interactive workflow or execute a scripted run. |
| `benchbox shell` | Open an interactive SQL shell to explore benchmark databases. |
| `benchbox platforms` | Manage database platforms: list, enable, disable, check dependencies. |
| `benchbox check-deps` | Summarize connector status and show install commands. |
| `benchbox tuning init` | Scaffold a tuning YAML grouped by platform and benchmark. |
| `benchbox results --limit N` | Display recent benchmark summaries. |

> Tip: `uv run -- benchbox <command>` automatically uses the project’s virtual environment. Activate the venv manually if you prefer to invoke `benchbox` directly.

## Running Benchmarks

The `run` subcommand accepts a rich set of options. The defaults favor the interactive experience; provide flags to drive unattended CI jobs.

### Core options

- `--platform TEXT` - Target platform (`duckdb`, `sqlite`, `clickhouse`, `databricks`, `bigquery`, `redshift`, `snowflake`, …).
- `--benchmark TEXT` - Benchmark module (`tpch`, `tpcds`, `ssb`, `primitives`, etc.).
- `--scale FLOAT` - Data scale factor (default: `0.01`).
- `--phases TEXT` - Comma-separated phases to run: `generate`, `load`, `warmup`, `power`, `throughput`, `maintenance` (default: `power`).
- `--non-interactive` - Assume defaults for every prompt (pair with explicit flags in CI).
- `--output PATH` - Root directory for generated data and artifacts (supports `s3://`, `gs://`, `abfss://`).
- `--dry-run PATH` - Produce the full execution plan without running it (queries, seeds, expected data volume).
- `--seed INTEGER` - Force a deterministic RNG seed for TPC benchmark parameter generation.
- `--force [MODE]` - Force regeneration (modes: `all`, `datagen`, `upload`, or `datagen,upload`).

### Validation and tuning

- `--validation MODE` - Validation mode: `exact`, `loose`, `range`, `disabled`, `full` (enables all checks).
- `--tuning tuned|notuning|PATH` - Apply optional tuning configs (`tuned` enables platform-specific constraints; supply a YAML path to use a custom profile).
- `--platform-option KEY=VALUE` - Pass adapter-specific options (repeatable). Use `benchbox platforms status <name>` to see platform details.
- `--platform-option driver_version=X.Y.Z` - Pin a platform driver package (DuckDB, Databricks connector, etc.). Add `driver_auto_install=true` or export `BENCHBOX_DRIVER_AUTO_INSTALL=1` to let BenchBox install the requested build before execution.

### Logging & resource control

- `--verbose / -v` (repeatable) - Increase logging detail (`-v` = INFO, `-vv` = DEBUG).
- `--quiet / -q` - Suppress console output (overrides `-v`).
- `--capture-plans` - Capture query execution plans during benchmark runs.
- `--compression TYPE[:LEVEL]` - Compression settings (e.g., `zstd`, `zstd:9`, `gzip:6`, `none`).

### Help system

- `--help` - Show common options.
- `--help-topic all` - Show all options including advanced.
- `--help-topic examples` - Show categorized usage examples.

### Common execution patterns

```bash
# Interactive workflow with guided prompts
uv run -- benchbox run

# Non-interactive run for CI or cron jobs
uv run -- benchbox run \
  --platform duckdb \
  --benchmark tpch \
  --scale 0.1 \
  --non-interactive

# Preview the entire plan (queries, file layout, seeds) without running it
uv run -- benchbox run \
  --platform duckdb \
  --benchmark tpch \
  --scale 0.1 \
  --dry-run ./preview

# Run specific queries only (for debugging or focused testing)
uv run -- benchbox run \
  --platform duckdb \
  --benchmark tpch \
  --queries "Q1,Q6,Q17" \
  --phases power

# Debug a single failing query with verbose output
uv run -- benchbox run \
  --platform postgres \
  --benchmark tpcds \
  --queries "Q42" \
  --verbose \
  --phases power

# See all CLI examples
uv run -- benchbox run --help-topic examples

# View platform status and capabilities
uv run -- benchbox platforms status databricks

# Compare two DuckDB releases without switching environments
uv run -- benchbox run \
  --platform duckdb \
  --benchmark tpch \
  --platform-option driver_version=1.0.0 \
  --output ./runs/v1.0.0

uv run -- benchbox run \
  --platform duckdb \
  --benchmark tpch \
  --platform-option driver_version=1.1.0 \
  --output ./runs/v1.1.0
```

## Results and Artefacts

```bash
# Show the latest run summary (duration, validation status, failures)
uv run -- benchbox results --limit 1
```

## Exporting Results

Re-export existing benchmark results in different formats without re-running:

```bash
# Export most recent result to CSV
uv run -- benchbox export --last --format csv

# Export specific result to HTML report
uv run -- benchbox export benchmark_runs/results/tpch_sf1_duckdb.json --format html

# Export to multiple formats at once
uv run -- benchbox export --last --format csv --format html --format json

# Export latest TPC-H result with filtering
uv run -- benchbox export --last --benchmark tpc_h --format csv

# Export to custom directory
uv run -- benchbox export --last --format html --output-dir ./reports/
```

**Common Use Cases:**
- **CSV** for spreadsheet analysis (Excel, Google Sheets)
- **HTML** for standalone reports with formatted tables
- **JSON** for programmatic analysis and archival

## Visualizing Results

Generate ASCII charts from benchmark results directly in the terminal:

```bash
# Auto-detect latest result and render all applicable charts
uv run -- benchbox visualize

# Visualize a specific result file
uv run -- benchbox visualize benchmark_runs/results/tpch_duckdb_sf0.01_*.json

# Compare multiple result files
uv run -- benchbox visualize duckdb.json sqlite.json --template head_to_head

# Specific chart type
uv run -- benchbox visualize --last --chart-type performance_bar

# Save plain-text output to file (strip ANSI colors)
uv run -- benchbox visualize --last --no-color > charts.txt
```

See the [Visualization Guide](../visualization/overview.md) for chart types, templates, and customization options.

## Platform Management

The `platforms` command helps you discover, enable, and configure database platforms.

```bash
# List all available platforms with their status
uv run -- benchbox platforms list

# Show detailed information about a specific platform
uv run -- benchbox platforms status duckdb

# Enable a platform for use in benchmarks
uv run -- benchbox platforms enable clickhouse

# Disable a platform
uv run -- benchbox platforms disable sqlite

# Get installation guidance for missing dependencies
uv run -- benchbox platforms install databricks

# Check if enabled platforms are ready
uv run -- benchbox platforms check --enabled-only

# Interactive setup wizard
uv run -- benchbox platforms setup
```

**Platform Management vs Credential Setup:**
- `benchbox platforms` manages platform *availability* (dependencies installed, enabled/disabled)
- `benchbox setup --platform <name>` manages *credentials* for cloud platforms
- For cloud platforms, you need both: enable the platform AND configure credentials

**Typical Cloud Platform Workflow:**
```bash
# 1. Check if platform dependencies are installed
uv run -- benchbox platforms status databricks

# 2. Install dependencies if needed (follow the guidance shown)
uv add databricks-sql-connector

# 3. Enable the platform
uv run -- benchbox platforms enable databricks

# 4. Configure credentials
uv run -- benchbox setup --platform databricks

# 5. Verify everything is ready
uv run -- benchbox platforms check databricks
```

## Interactive SQL Shell

Open an interactive SQL shell to explore benchmark databases, debug queries, and inspect data:

```bash
# Discover and connect to available databases interactively
uv run -- benchbox shell

# List all available databases
uv run -- benchbox shell --list

# Connect to most recent database
uv run -- benchbox shell --last

# Connect to specific benchmark database
uv run -- benchbox shell --last --benchmark tpch

# Filter by scale factor
uv run -- benchbox shell --benchmark tpch --scale 1.0

# Direct connection to database file
uv run -- benchbox shell --database benchmark.duckdb

# Use custom output directory
uv run -- benchbox shell --output ./my-benchmarks
```

**Shell Features:**
- **DuckDB & SQLite**: Full interactive shells with `.tables`, `.schema`, `.info` commands
- **Command History**: Navigate previous commands with arrow keys
- **Query Timing**: Automatic execution time measurement
- **Database Discovery**: Automatically finds databases in benchmark_runs/

**Common Use Cases:**
- Verify data loaded correctly after benchmarks
- Debug individual queries before running full suite
- Explore table schemas and row counts
- Compare data across different scale factors

## Dependency Checks & Tuning Templates

```bash
# Summarize optional dependencies and extras guidance
uv run -- benchbox check-deps --matrix

# Focus on a single adapter with verbose remediation
uv run -- benchbox check-deps --platform snowflake --verbose

# Generate a tuning skeleton for your project
uv run -- benchbox tuning init --platform duckdb
```

## Working With uv

- `uv run -- benchbox …` keeps dependency management simple: no manual activation required.
- Use `uvx benchbox …` to execute without installing into the current project.
- If you are using a traditional virtual environment, run `source .venv/bin/activate` (or the Windows equivalent) and call `benchbox` directly.

For a full explanation of workflows, visit the [usage overview](index.md). When you need to customise execution further, the [configuration guide](configuration.md) explains YAML profiles, environment overrides, and validation rules in detail.
