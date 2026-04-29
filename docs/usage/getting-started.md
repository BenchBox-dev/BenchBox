<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Getting Started in 5 Minutes

```{tags} beginner, quickstart, cli, duckdb
```

Follow these four steps to install BenchBox, verify your environment, and run a reproducible benchmark. Everything below works on macOS, Linux, and Windows with Python 3.10+.

## Step 0 - Prerequisites

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended) or make sure you have pip available.
2. Ensure DuckDB can create temporary files in your working directory. No other services are required for the quick start.

```bash
# Optional: create an isolated project directory
mkdir benchbox-demo && cd benchbox-demo
```

## Step 1 - Install BenchBox

If you have not installed BenchBox yet, follow the dedicated [installation guide](installation.md). It covers `uv`, `pip`, extras, and dependency checks.

Already installed? Verify the CLI is on your PATH:

```bash
uv run -- benchbox --version
```

## Step 2 - Profile Your Environment

The profile command confirms CPU, memory, and available adapters. BenchBox uses this information to suggest scale factors and concurrency levels.

```bash
uv run -- benchbox profile
```

Look for the *Available Databases* table,`duckdb` should be **Ready** immediately. If you plan to use cloud platforms later, run `uv run -- benchbox check-deps --platform <name>` or use the guided `benchbox platforms setup` wizard once you have credentials handy.

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
# Export to CSV for spreadsheet analysis
uv run -- benchbox export --last --format csv

# Generate HTML report for sharing with team
uv run -- benchbox export --last --format html --output-dir ./reports/

# Export to all formats
uv run -- benchbox export --last --format json --format csv --format html
```

The export command is useful for:
- Creating shareable HTML reports for stakeholders
- Analyzing query performance in spreadsheets (Excel, Google Sheets)
- Archiving results in multiple formats
- Converting between formats without re-running expensive benchmarks

## Optional - DataFrame Platforms

BenchBox also supports benchmarking DataFrame libraries using their native APIs. This enables direct comparison between SQL and DataFrame execution paradigms.

### Quick Start with DataFrames

```bash
# Polars DataFrame (included in base install)
uv run -- benchbox run --platform polars-df --benchmark tpch --scale 0.01

# Pandas DataFrame (requires extra)
uv add benchbox --extra pandas
uv run -- benchbox run --platform pandas-df --benchmark tpch --scale 0.01
```

### Compare SQL vs DataFrame

```bash
# Run the same benchmark with different paradigms
uv run -- benchbox run --platform duckdb --benchmark tpch --scale 0.1     # SQL
uv run -- benchbox run --platform polars-df --benchmark tpch --scale 0.1  # DataFrame
```

For more details, see the [DataFrame Platforms Guide](../platforms/dataframe.md).

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

- **[CLI Quick Reference](cli-quick-start.md)**, Complete command reference with examples
- **[Configuration Handbook](configuration.md)**, CLI flags, config files, and advanced options
- **[Examples Guide](examples.md)**, Code snippets and automation patterns

### Understanding BenchBox

- **[Architecture Overview](../concepts/architecture.md)** - How BenchBox components work together
- **[Workflow Patterns](../concepts/workflow.md)** - Common benchmarking workflows
- **[Data Model](../concepts/data-model.md)** - Understanding result schemas and analysis
- **[Glossary](../concepts/glossary.md)** - Benchmark terminology reference

### Expanding Your Testing

- **[Platform Selection Guide](../platforms/platform-selection-guide.md)** - Choosing the right database
- **[Platform Quick Reference](../platforms/quick-reference.md)** - Setup for each platform
- **[DataFrame Platforms](../platforms/dataframe.md)** - Native DataFrame API benchmarking
- **[Benchmark Catalog](../benchmarks/index.md)** - Available benchmarks beyond TPC-H
- **[Data Generation Guide](data-generation.md)** - Advanced data generation options

### Troubleshooting

- **[Troubleshooting Guide](troubleshooting.md)** - Common issues and solutions
- **[Dry Run Mode](dry-run.md)** - Preview queries before execution
