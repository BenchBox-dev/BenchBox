<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Frequently Asked Questions (FAQ)

```{tags} beginner, guide
```

This page answers common questions about BenchBox. For troubleshooting specific errors, see the [Troubleshooting Guide](troubleshooting.md).

## General Questions

### What is BenchBox?

BenchBox is a benchmarking toolbox that makes it simple to benchmark analytical (OLAP) databases. It provides industry-standard benchmarks like TPC-H, TPC-DS, and others in a single Python tool with minimal setup required.

### Is BenchBox production-ready?

BenchBox is currently **Beta software**. Core functionality is stable (TPC-H, TPC-DS with DuckDB and major cloud platforms). APIs may still change before 1.0. We recommend thorough testing before using BenchBox in production. See the main README for details on Beta status.

The default wheel includes a `benchbox.experimental` namespace (nl2sql, aiml-functions, multiregion, gpu, concurrency). This namespace is **not part of the supported Beta surface** - it has no stability guarantees and is not integrated with the benchmark registry or CLI. Use it at your own risk.

### Which databases does BenchBox support?

BenchBox supports:
- **Local**: DuckDB, SQLite, ClickHouse (local mode)
- **Cloud**: Databricks, Snowflake, BigQuery, Redshift

See the [Platform Selection Guide](../platforms/platform-selection-guide.md) and [Comparison Matrix](../platforms/comparison-matrix.md) for detailed requirements and capabilities.

### Which benchmarks are available?

BenchBox includes **22** public-discovery benchmarks, with examples across:
- **TPC Standards**: TPC-H, TPC-DS, TPC-DI, TPC-DS-OBT, TPC-H Skew, TPC-Havoc
- **Academic Benchmarks**: SSB, AMPLab, JoinOrder
- **Industry and real-world workloads**: ClickBench, H2ODB, NYC Taxi, FlightData, TSBS DevOps, CoffeeShop
- **BenchBox Primitives and AI/ML**: Read Primitives, Write Primitives, Metadata Primitives, Transaction Primitives, AI Primitives, Vector Search, TPC-H Data Vault

See the [Benchmarks Catalog](../benchmarks/index.md) for feature details and selection guidance.

### How do I cite BenchBox in academic work?

BenchBox is MIT-licensed open-source software. When citing BenchBox in academic papers:

```
Harris, Joe. (2025). BenchBox: A Benchmarking Toolbox for Analytical Databases.
GitHub repository: https://github.com/joeharris76/benchbox
```

Please also cite the underlying benchmark specifications (TPC-H, TPC-DS, etc.) when reporting results.

## Installation & Setup

### How do I install BenchBox?

The recommended installation method uses `uv`:

```bash
uv add benchbox
```

For specific platforms, install extras:

```bash
uv add benchbox --extra databricks --extra snowflake
```

See the [Installation Guide](installation.md) for complete instructions.

### Why use `uv` instead of `pip`?

Both work fine! `uv` is faster and handles dependency resolution more reliably, but standard `pip` is fully supported:

```bash
python -m pip install benchbox
```

### Do I need to compile TPC tools manually?

No. BenchBox includes pre-compiled TPC-H and TPC-DS data generation tools (`dbgen`, `dsdgen`, `dsqgen`) for all major platforms (macOS, Linux, Windows) in the `_binaries/` directory. These are automatically used when you run benchmarks.

### Can I run BenchBox without any database installed?

Yes! Install BenchBox with the `[duckdb]` extra and you can run benchmarks immediately - DuckDB creates databases in-process with no server setup.

```bash
uv add benchbox --extra duckdb
uv run -- benchbox run --platform duckdb --benchmark tpch --scale 0.01
```

### How do I verify my installation?

Run these commands to verify:

```bash
# Check BenchBox version
benchbox --version

# Profile your environment
benchbox profile

# Check platform dependencies
benchbox check-deps --matrix
```

## Running Benchmarks

### What scale factor should I use?

It depends on your goal:
- **Quick testing**: `0.01` or `0.1` (completes in seconds/minutes)
- **Development**: `1` (standard size, ~1GB for TPC-H)
- **Performance testing**: `10`, `100`, or higher (requires more time and resources)
- **TPC-DS note**: Use scale ≥ 1 only (fractional scale causes binary segfaults)

Use `benchbox profile` to get scale factor recommendations for your system.

### How long does a benchmark take?

Time varies significantly based on scale factor, platform, hardware, and benchmark complexity:
- **Scale factor**: Larger scale factors = more data = longer runtimes
- **Query complexity**: TPC-DS has 99 complex queries; TPC-H has 22 simpler queries
- **Platform**: Cloud platforms add network latency and cluster startup time
- **Hardware**: CPU cores, memory, and disk speed all affect performance

Use `--dry-run` to preview configurations without running queries. Run benchmarks to establish baselines for your specific environment. See [Dry Run Mode](dry-run.md).

### Can I run just specific queries?

Yes, use the `--queries` flag:

```bash
benchbox run --platform duckdb --benchmark tpch --scale 1 --queries 1,6,13
```

Or run specific phases:

```bash
benchbox run --platform duckdb --benchmark tpch --scale 1 --phases power
```

See [CLI Quick Start](cli-quick-start.md) for all options.

### How do I run benchmarks in CI/CD?

Add `--non-interactive` to skip prompts and use specific output directories:

```bash
benchbox run \
  --non-interactive \
  --platform duckdb \
  --benchmark tpch \
  --scale 0.1 \
  --output results/ci-run-${{ github.run_id }}
```

See [CI/CD Integration](../advanced/ci-cd-integration.md) for complete examples.

### Where are benchmark results stored?

By default, results are stored in `benchmark_runs/` with timestamped subdirectories:

```
benchmark_runs/
├── 20250103_143022_tpch_duckdb_sf1/
│   ├── manifest.json
│   ├── results/
│   │   └── power_test_results.json
│   └── logs/
```

Specify a custom location with `--output`:

```bash
benchbox run --output /path/to/results --platform duckdb --benchmark tpch --scale 1
```

### Can I reuse generated data?

Yes! By default, BenchBox checks for existing data and skips regeneration. To force regeneration:

```bash
benchbox run --force --platform duckdb --benchmark tpch --scale 1
```

Generated data is stored in `benchmark_runs/*/data/` by default.

## Platform-Specific Questions

### How do I configure cloud platform credentials?

Use environment variables (recommended) or the interactive setup wizard:

**Environment variables**:
```bash
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="your-token"
export SNOWFLAKE_ACCOUNT="your-account"
export SNOWFLAKE_USER="your-user"
export SNOWFLAKE_PASSWORD="your-password"
```

**Setup wizard**:
```bash
benchbox platforms setup
```

See the [Platform Selection Guide](../platforms/platform-selection-guide.md) for platform-specific details.

### Why is my cloud benchmark slow?

Common causes:
- **Cold start**: First query on cloud warehouses is often slower (cluster startup)
- **Small warehouse**: Increase warehouse/cluster size (e.g., XSmall to Small)
- **Network latency**: Data transfer between cloud storage and compute
- **Cache warming**: Run with `--phases generate,load,power` first

See [Performance Optimization](../advanced/performance-optimization.md) for tuning tips.

### Can I use BenchBox with self-hosted databases?

Yes! BenchBox currently supports:
- **ClickHouse**: Fully supported via `--platform clickhouse` (local or remote)
- **DuckDB**: Fully supported for local/embedded use via `--platform duckdb`
- **SQLite**: Fully supported for local/embedded use via `--platform sqlite`

For databases not yet supported, see the [Development Roadmap](../development/roadmap.md).
You can also create custom platform adapters - see [Adding New Platforms](../development/adding-new-platforms.md) for guidance.

### Do cloud benchmarks cost money?

Yes. Running benchmarks on cloud platforms incurs costs for:
- Compute (warehouse/cluster runtime)
- Storage (data stored)
- Data transfer (network egress)

Start with small scale factors and monitor costs. Use `--dry-run` to plan resource usage without executing queries.

## Data & Query Questions

### Are the TPC benchmarks official/compliant?

BenchBox implements TPC-H and TPC-DS queries and data generation according to specifications, but **BenchBox is not TPC-certified** and results cannot be published as official TPC results.

For official TPC compliance and publication:
- Results must be audited by the TPC
- Specific hardware and configuration requirements apply
- See [TPC.org](https://www.tpc.org/) for official benchmarking

BenchBox is designed for **internal performance testing and comparison**.

### Can I modify the queries?

Yes, but be aware that modifying standard benchmark queries defeats the purpose of standardized benchmarking. For custom workloads, consider:
- Creating custom benchmarks (see [Custom Benchmarks](../advanced/custom-benchmarks.md))
- Using query variants (some benchmarks support this)
- Forking queries for experimentation

Query files are located in `benchbox/core/{benchmark}/queries/`.

### How does query translation work?

BenchBox automatically translates queries to platform-specific SQL dialects using SQLGlot. The translation handles:
- Function name differences (e.g., `SUBSTRING` vs `SUBSTR`)
- Date/time functions
- Type casting
- Platform-specific syntax

In rare cases, manual tuning may be needed for platform-specific SQL syntax.

### Can I use compressed data formats?

Yes! BenchBox supports multiple compression formats:
- Parquet (recommended for most platforms)
- CSV with compression (gzip, zstd)
- Platform-native formats

Configure with tuning files or command-line options. See the [Data Generation](data-generation.md) guide for details.

## Troubleshooting & Errors

### I get "command not found: benchbox"

The `benchbox` CLI is not in your PATH. Solutions:
1. Ensure your virtual environment is activated
2. Add Python's scripts directory to PATH
3. Run with `uv run -- benchbox` instead

See the [Troubleshooting Guide](troubleshooting.md) Installation Issues section.

### Benchmark fails with "missing dependency"

Install the required platform extras:

```bash
uv add benchbox --extra databricks
```

Run `benchbox check-deps --matrix` to see all platform dependencies and their status.

### Queries fail with syntax errors

This may indicate a query translation issue. Try:
1. Check the platform is officially supported
2. Review query logs in `benchmark_runs/*/logs/`
3. Report the issue with query details

See the [Troubleshooting Guide](troubleshooting.md) Query Execution Issues section.

### TPC-DS fails at scale < 1

TPC-DS data generation tools have a known issue with fractional scale factors (causes segfault). **Always use scale ≥ 1 for TPC-DS**:

```bash
benchbox run --platform duckdb --benchmark tpcds --scale 1
```

This is a limitation of the upstream TPC-DS tools, not BenchBox.

## Advanced Features

### Can I run benchmarks in parallel?

Yes! Some benchmarks support throughput tests with concurrent queries. The
primary `run` command does not have a `--streams`/`--concurrency` flag yet, so
today the number of concurrent streams is set through the deprecated
`run-official` compatibility command:

```bash
benchbox run-official tpch --platform duckdb --scale 1 --phases throughput --streams 4 --seed 42
```

See [CLI Reference → Deprecated: `run-official`](../reference/cli/run.md#deprecated-run-official)
and [Power Run & Concurrent Queries](../advanced/power-run-concurrent-queries.md).

### How do I compare results across runs?

BenchBox stores results in JSON format with full run metadata. You can:
- Parse JSON files programmatically
- Use the Python API for analysis
- Build custom comparison tools

See [Result Schema](../reference/result-schema-v1.md) and [API Reference](../reference/api-reference.md).

### Can I create custom benchmarks?

Yes! BenchBox provides APIs for creating custom benchmarks:

```python
from benchbox.core.base import BaseBenchmark

class MyCustomBenchmark(BaseBenchmark):
    # Implement required methods
    pass
```

See [Custom Benchmarks Guide](../advanced/custom-benchmarks.md) for complete instructions.

### How do I automate performance regression detection?

BenchBox integrates with CI/CD for automated regression detection:
1. Run benchmarks in CI on each commit
2. Compare results against baseline
3. Fail builds when performance regresses

See [Performance Monitoring](../advanced/performance.md) for setup examples.

## Contributing & Support

### How can I contribute?

Contributions are welcome! See the root `CONTRIBUTING.md` file for:
- Code contribution guidelines
- Development setup
- Testing requirements
- Pull request process

You can also contribute by:
- Reporting bugs and issues
- Improving documentation
- Sharing feedback and use cases

### Where do I report bugs?

[Create an issue on GitHub](https://github.com/joeharris76/benchbox/issues/new) with:
- BenchBox version (`benchbox --version`)
- Platform and benchmark being used
- Complete error messages and logs
- Minimal reproduction steps

### How do I request new features?

[Open a feature request](https://github.com/joeharris76/benchbox/issues/new) on GitHub describing:
- The use case and motivation
- Proposed behavior or API
- Alternative solutions you've considered
- Any relevant examples from other tools

### Where can I ask questions?

For questions not covered in the documentation:
1. Check existing [GitHub issues and discussions](https://github.com/joeharris76/benchbox/issues)
2. Open a new discussion or issue
3. Provide context and specific details

Support is provided on a best-effort basis during Beta development.

## See Also

- [Troubleshooting Guide](troubleshooting.md) - Solutions to specific errors
- [Getting Started](getting-started.md) - Quick start tutorial
- [CLI Quick Reference](cli-quick-start.md) - Command overview
- [Platform Selection Guide](../platforms/platform-selection-guide.md) - Choose the right platform
- [Benchmarks Catalog](../benchmarks/index.md) - All available benchmarks
