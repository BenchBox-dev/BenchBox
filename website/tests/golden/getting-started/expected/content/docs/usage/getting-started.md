---
title: Getting Started in 5 Minutes
tags:
  - beginner
  - quickstart
  - cli
  - duckdb
sourcePath: docs/usage/getting-started.md
titleId: getting-started-in-5-minutes
headingIds:
  - step-0-prerequisites
  - step-1-install-benchbox-with-duckdb
  - step-2-profile-your-environment
  - step-3-run-your-first-benchmark
  - step-4-inspect-the-results
  - step-5-export-results-optional
  - optional-dataframe-platforms
  - quick-start-with-dataframes
  - compare-sql-vs-dataframe
  - optional-python-api-in-15-lines
  - next-steps
  - essential-guides
  - understanding-benchbox
  - expanding-your-testing
  - troubleshooting
---

<span id="getting-started-in-5-minutes"></span>

Follow these steps to install BenchBox, verify your environment, and run a reproducible benchmark. Everything below works on macOS, Linux, and Windows with Python 3.11+.

## Step 0 - Prerequisites

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended) or make sure you have pip available.
2. Ensure DuckDB can create temporary files in your working directory. No other services are required for the quick start.

```bash
mkdir benchbox-demo && cd benchbox-demo
```

Creating an isolated project directory is optional.

## Step 1 - Install BenchBox with DuckDB

Install the `duckdb` extra. **DuckDB is an optional dependency** - a plain
`uv add benchbox` installs the core package with SQLite only, and every command
in this guide uses DuckDB.

```bash
uv add benchbox --extra duckdb
```

Prefer pip? `python -m pip install "benchbox[duckdb]"` (quote the brackets so
your shell does not expand them).

Verify the CLI is on your PATH:

```bash
uv run -- benchbox --version
```

For other platforms, extras, and dependency checks, see the dedicated
[installation guide](/docs/usage/installation.html).

## Step 2 - Profile Your Environment

The profile command confirms CPU, memory, and available adapters. BenchBox uses this information to suggest scale factors and concurrency levels.

```bash
uv run -- benchbox profile
```

Look for the *Available Databases* table. `duckdb` should be **Ready** because Step 1 installed the `duckdb` extra; if it is not, re-run the Step 1 install command. If you plan to use cloud platforms later, run `uv run -- benchbox check-deps --platform <name>`, or use the guided `benchbox setup --platform <name>` wizard once you have credentials handy.

## Step 3 - Run Your First Benchmark

Run a minimal TPC-H benchmark to generate data, load it into DuckDB, and execute the standard power test.

```bash
uv run -- benchbox run \
  --platform duckdb \
  --benchmark tpch \
  --scale 0.01
```

Unattended execution? Add `--non-interactive` to skip prompts. BenchBox stores outputs under `benchmark_runs/` by default.

## Step 4 - Inspect the Results

Summarize the most recent run:

```bash
uv run -- benchbox results --limit 1
```

The results display shows timing, validation status, and per-query metrics from your benchmark execution.

## Step 5 - Export Results (Optional)

Share your results in different formats without re-running the benchmark:

```bash
uv run -- benchbox export --last --format csv

uv run -- benchbox export --last --format html --output-dir ./reports/

uv run -- benchbox export --last --format json --format csv --format html
```

The commands export to CSV for spreadsheet analysis, generate an HTML report for sharing with your team, and export to all formats.

The export command is useful for:

- Creating shareable HTML reports for stakeholders
- Analyzing query performance in spreadsheets (Excel, Google Sheets)
- Archiving results in multiple formats
- Converting between formats without re-running expensive benchmarks

## Optional - DataFrame Platforms

BenchBox also supports benchmarking DataFrame libraries using their native APIs. This enables direct comparison between SQL and DataFrame execution paradigms.

### Quick Start with DataFrames

```bash
uv run -- benchbox run --platform polars-df --benchmark tpch --scale 0.01

uv add benchbox --extra pandas
uv run -- benchbox run --platform pandas-df --benchmark tpch --scale 0.01
```

Polars is included in the base install. Pandas requires an extra.

### Compare SQL vs DataFrame

```bash
uv run -- benchbox run --platform duckdb --benchmark tpch --scale 0.1
uv run -- benchbox run --platform polars-df --benchmark tpch --scale 0.1
```

These commands run the same benchmark with different paradigms: DuckDB runs SQL, and Polars runs DataFrame operations.

For more details, see the [DataFrame Platforms Guide](/docs/platforms/dataframe.html).

## Optional - Python API in 15 Lines

```python
import duckdb
from benchbox import TPCH

conn = duckdb.connect(":memory:")
benchmark = TPCH(scale_factor=0.01, output_dir="./tpch_data")

benchmark.generate_data()
conn.execute(benchmark.get_create_tables_sql())

for table, path in benchmark.tables.items():
    conn.execute(
        f"COPY {table} FROM '{path}' (DELIMITER '|' NULL '' HEADER FALSE);"
    )

rows = conn.execute(benchmark.get_query(1)).fetchall()
print(f"Query 1 returned {len(rows)} rows")
```

## Next Steps

### Essential Guides

- **[CLI Quick Reference](/docs/usage/cli-quick-start.html)**, Complete command reference with examples
- **[Configuration Handbook](/docs/usage/configuration.html)**, CLI flags, config files, and advanced options
- **[Examples Guide](/docs/usage/examples.html)**, Code snippets and automation patterns

### Understanding BenchBox

- **[Architecture Overview](/docs/concepts/architecture.html)** - How BenchBox components work together
- **[Workflow Patterns](/docs/concepts/workflow.html)** - Common benchmarking workflows
- **[Data Model](/docs/concepts/data-model.html)** - Understanding result schemas and analysis
- **[Glossary](/docs/concepts/glossary.html)** - Benchmark terminology reference

### Expanding Your Testing

- **[Platform Selection Guide](/docs/platforms/platform-selection-guide.html)** - Choosing the right database
- **[Platform Quick Reference](/docs/platforms/quick-reference.html)** - Setup for each platform
- **[DataFrame Platforms](/docs/platforms/dataframe.html)** - Native DataFrame API benchmarking
- **[Benchmark Catalog](/docs/benchmarks/index.html)** - Available benchmarks beyond TPC-H
- **[Data Generation Guide](/docs/usage/data-generation.html)** - Advanced data generation options

### Troubleshooting

- **[Troubleshooting Guide](/docs/usage/troubleshooting.html)** - Common issues and solutions
- **[Dry Run Mode](/docs/usage/dry-run.html)** - Preview queries before execution
