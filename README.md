<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# BenchBox

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Beta Software](https://img.shields.io/badge/Status-Beta-blue.svg)](https://github.com/joeharris76/benchbox/issues)
[![codecov](https://codecov.io/github/joeharris76/BenchBox/graph/badge.svg?token=3NY6DK7MDO)](https://codecov.io/github/joeharris76/BenchBox)
[![PyPI Release](https://img.shields.io/pypi/v/benchbox)](https://pypi.org/project/benchbox/)
[![PyPI Downloads](https://img.shields.io/pepy/dt/benchbox.svg?label=PyPI%20Downloads)](https://pypi.org/project/benchbox/)

**"Running a benchmark should be as simple as `import {benchmark}`"**

BenchBox is a "**bench**marking tool**box**" that makes it simple to benchmark analytic (OLAP) databases.

## Overview

BenchBox provides industry-standard (TPC-H, TPC-DS), academic (Join Order), and custom designed (Primitives) benchmarks for data warehouse workloads.

BenchBox embeds the entire benchmark lifecycle, including query and data generation, result analysis, and reporting for these benchmarks in a single Python tool with simple setup.

BenchBox uses Python-native interfaces for popular local data tools (DuckDB, DataFusion, Polars) and cloud platforms (Snowflake, Databricks, ClickHouse).

## Versioning

BenchBox _loosely_ follows [Semantic Versioning](https://semver.org/) using the `MAJOR.MINOR.PATCH` scheme. Variations on the "official" SemVer spec are made to better fit the nature of BenchBox as an evolving benchmarking tool rather than a stable API library. See below for details.

- **MAJOR** when we make incompatible changes _OR significant changes in scope or functionality_.
- **MINOR** when we add backward-compatible changes _OR significantly expand functionality_.
- **PATCH** when we make bug fixes or documentation updates, _bug-fixes may not be backward-compatible_.

Current release: v0.3.1. Check your installation with `benchbox --version`, which also reports metadata consistency diagnostics pulled from `pyproject.toml` and documentation markers.

**For Developers**: See [Release Automation Guide](release/RELEASE_AUTOMATION.md) for the automated release process with reproducible builds and timestamp normalization.

## Beta Software

> **BenchBox is BETA software.** Core functionality and the CLI are stable. APIs may still change before 1.0. See [DISCLAIMER.md](DISCLAIMER.md) for full details on what this means and how to get help.

The default wheel ships the `benchbox.experimental` namespace (nl2sql, aiml-functions, multiregion, gpu, concurrency subsystems). This namespace is **outside the supported Beta product surface**: it has no stability guarantees, may change or be removed without notice, and is not integrated with the benchmark registry or public CLI. It is present in the wheel for developer convenience only.

Public contract tiers, support-status vocabulary, and source-of-truth rules for platform and benchmark count claims are tracked in [Public Contracts and Support Taxonomy](docs/reference/public-contracts.md).

Registry-backed count claims are checked by unit tests so README and platform docs do not drift from runtime metadata:

<!-- benchbox-registry-counts:start -->

- Platform registry: **50** metadata entries; **45** SQL-capable; **19** DataFrame-capable; **14** dual-mode; support status counts: stable=5, beta=27, experimental=17, deprecated=1.
- Benchmark registry: **23** metadata entries; **22** public discovery entries.

<!-- benchbox-registry-counts:end -->

## Features

- **Embedded Benchmarks**: Self-contained benchmark data and queries
- **Benchmark Catalog**: TPC-H, TPC-DS, TPC-DI, TPC-DS-OBT, TPC-H Skew, TPC-Havoc, SSB, AMPLab, JoinOrder, ClickBench, H2ODB, NYC Taxi, Flight Data, TSBS DevOps, CoffeeShop, TPC-H Data Vault, Vector Search, Read Primitives, Write Primitives, Transaction Primitives, Metadata Primitives, AI Primitives
- **Cross-Database**: Same benchmarks work on any database platform
- **DataFrame Mode**: Native DataFrame API benchmarking with Polars, Pandas, DataFusion, Dask, and other DataFrame runtimes
- **SQL Platforms**: DuckDB, MotherDuck, SQLite, DataFusion, PostgreSQL, TimescaleDB, ClickHouse (Local, Server, Cloud), CedarDB, Firebolt, Databend, Doris, StarRocks, SingleStore, QuestDB, InfluxDB, pg_duckdb, pg_mooncake, Databricks SQL, Snowflake, BigQuery, Redshift, Azure Synapse Analytics, Microsoft Fabric Warehouse, Microsoft Fabric Lakehouse SQL, Trino, Starburst, Presto, Amazon Athena, Spark, PySpark, LakeSail Sail, Apache Gluten + Velox, Onehouse Quanton, AWS Glue, Amazon EMR Serverless, Amazon Athena for Apache Spark, Google Cloud Dataproc, Google Cloud Dataproc Serverless, Microsoft Fabric Spark, Azure Synapse Analytics Spark
- **DataFrame Platforms**: DataFusion-DF, Polars-DF, Pandas-DF, Modin-DF, Dask-DF, cuDF-DF (GPU), PySpark-DF, Databricks-DF, LakeSail-DF
- **Open Table Formats**: Delta Lake, Apache Iceberg, Apache Hudi (via Databricks, Quanton, Trino, Spark platforms)
- **SQL Translation**: Automatic query conversion between SQL dialects
- **Self-Contained Python Package**: Core install requires no external database servers or system dependencies; opt-in to extra package installs for cloud platforms when needed.

## Documentation Tour

The full documentation lives under [`docs/`](docs/README.md) and is published with Sphinx.

| Topic                     | Where to start                                                                                                |
| ------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Install & first benchmark | [docs/usage/getting-started.md](docs/usage/getting-started.md)                                                |
| Everyday CLI workflows    | [docs/usage/cli-quick-start.md](docs/usage/cli-quick-start.md)                                                |
| DataFrame benchmarking    | [docs/platforms/dataframe.md](docs/platforms/dataframe.md)                                                    |
| Config and automation     | [docs/usage/configuration.md](docs/usage/configuration.md) & [docs/usage/examples.md](docs/usage/examples.md) |
| Platform guidance         | [docs/platforms/platform-selection-guide.md](docs/platforms/platform-selection-guide.md)                      |
| Troubleshooting           | [docs/usage/troubleshooting.md](docs/usage/troubleshooting.md)                                                |
| Developer docs            | [docs/development/getting-started.rst](docs/development/getting-started.rst) & [docs/design/index.md](docs/design/index.md) |
| Browse results online     | [benchbox.dev/results/](https://benchbox.dev/results/) - compare benchmark results across platforms            |

Run `uv run -- sphinx-build -b html docs docs/_build/html` to build the local site.

## Benchmarks

- **TPC Standards**: TPC-H, TPC-DS, TPC-DI
- **Academic Benchmarks**: SSB, AMPLab, JoinOrder
- **Industry Benchmarks**: ClickBench, H2ODB, CoffeeShop
- **Real-World Data**: NYC Taxi, Flight Data
- **Time-Series Benchmarks**: TSBS DevOps
- **BenchBox Primitives**: Read Primitives, Write Primitives, Transaction Primitives, Metadata Primitives, AI Primitives
- **AI & ML Benchmarks**: Vector Search
- **BenchBox Experimental**: TPC-DS-OBT, TPC-Havoc, TPC-H Skew, TPC-H Data Vault

## Related Tools

BenchBox is one of several open-source database benchmarking tools. Each has different strengths:

### Bench**Box** vs Bench*Base*

BenchBox focuses on OLAP analytic benchmarks while [BenchBase](https://github.com/cmu-db/benchbase) focuses on OLTP transactional benchmarks.

BenchBox provides Python-native benchmarking with embedded data generation, while BenchBase uses Java with JDBC drivers. Both have their setup requirements - BenchBox requires Python dependencies and database connections, while BenchBase requires Java and JDBC setup.

Consider BenchBox for analytical workloads when you prefer Python-based tooling. Consider BenchBase for transactional workloads or when you need mature, production-tested benchmarking infrastructure with diverse OLTP workloads (TPC-C, Twitter, YCSB, etc.).

### Bench**Box** vs *Hammer*DB

BenchBox and [HammerDB](https://www.hammerdb.com/) (hosted by the TPC Council) target different workload types.

HammerDB focuses on **OLTP transactional benchmarks** (TPROC-C derived from TPC-C) with support for enterprise databases - Oracle, SQL Server, PostgreSQL, MySQL/MariaDB, and IBM Db2. It uses Tcl and provides GUI, CLI, and web service interfaces. HammerDB measures throughput in NOPM (New Orders Per Minute) and has decades of enterprise credibility.

BenchBox focuses on **OLAP analytical benchmarks** (TPC-H, TPC-DS, ClickBench, etc.) with support for the broad platform spectrum - from embedded engines like DuckDB and DataFusion, through DataFrame libraries like Polars and Pandas, to cloud data warehouses like Snowflake, BigQuery, and Databricks.

Consider HammerDB when testing transactional throughput on enterprise databases or when you need TPC Council-sponsored credibility. Consider BenchBox when benchmarking analytical queries across cloud data warehouses, embedded engines, or DataFrame libraries.

### Bench**Box** vs Lake*Bench*

BenchBox and [LakeBench](https://github.com/mwc360/LakeBench) are both Python-based benchmarking frameworks, but target different ecosystems.

LakeBench focuses on **lakehouse compute engines** (Spark, Fabric, Synapse, HDInsight) and evaluates end-to-end ELT workflows - ingestion, transformation, maintenance, and queries - using Delta Lake tables. It offers 4 benchmarks including ELTBench, a custom workflow-oriented benchmark.

BenchBox focuses on the **broad ecosystem of analytic platforms**-from single-node engines like DuckDB, to DataFrame libraries like Polars and Pandas, through to cloud data warehouses like Snowflake, BigQuery, and Redshift. It provides 22 public-discovery benchmarks including TPC standards, academic workloads like SSB and JoinOrder, and BenchBox-original benchmarks like TPC-Havoc for optimizer stress testing.

Consider LakeBench when evaluating Spark-based lakehouse engines, testing complete ELT pipeline performance, or working primarily in Microsoft Fabric/Azure environments. Consider BenchBox when benchmarking across the analytic platform spectrum, needing benchmark variety beyond TPC standards, or comparing DataFrame libraries alongside SQL engines.

## Installation

BenchBox ships as a Python package with optional extras that enable specific database platforms. Start with the core installation, then layer in the extras that match your environment.

### Local Development (DuckDB + SQLite)

Install the `[duckdb]` extra to get DuckDB and SQLite for local workflows. This is the recommended starting point.

- DuckDB engine for quick benchmarks (requires `[duckdb]` extra)
- Local data generators and CLI utilities
- SQLite integration for lightweight testing
- **Does not** include remote warehouse connectors (Databricks, Snowflake, etc.)

Install with DuckDB:

**Recommended (using uv):**
```bash
uv add benchbox --extra duckdb
```

**Alternative (pip-compatible):**
```bash
uv pip install "benchbox[duckdb]"
# or
python -m pip install "benchbox[duckdb]"
# or
pipx install "benchbox[duckdb]"
```

> **Note:** DuckDB is an optional dependency. A plain `uv add benchbox` (no extras) installs the core package with SQLite only - no DuckDB. Use `benchbox[duckdb]` for DuckDB support or `benchbox[all]` for all platforms.

### Optional Dependency Groups

Extras unlock connectors and helpers for each platform. Quote the extras specification so shells like zsh do not expand the brackets.

- `[duckdb]` - DuckDB (local analytics, default for most benchmarks)
- `[polars]` - Polars DataFrame engine (in-memory columnar analytics)
- `[clickhouse-cloud]` - ClickHouse Cloud HTTP connector (`clickhouse-connect`)
- `[postgresql]` - PostgreSQL (`psycopg2-binary`)
- `[cloud]` - Databricks, BigQuery, Redshift, Snowflake connectors (recommended starting point)
- `[cloudstorage]` - Cloud storage helpers (`cloudpathlib`)
- `[databricks]` - Databricks SQL Warehouses (`databricks-sql-connector`, `cloudpathlib`)
- `[bigquery]` - Google BigQuery (`google-cloud-bigquery`, `google-cloud-storage`, `cloudpathlib`)
- `[redshift]` - Amazon Redshift (`redshift-connector`, `boto3`, `cloudpathlib`)
- `[snowflake]` - Snowflake Data Cloud (`snowflake-connector-python`, `cloudpathlib`)
- `[clickhouse]` - ClickHouse Analytics (`clickhouse-driver`, TCP binary protocol)
- `[clickhouse-local]` - ClickHouse Local via chDB (embedded, zero-config)
- `[clickhouse-server]` - ClickHouse Server (`clickhouse-driver`, TCP binary protocol)
- `[datafusion]` - Apache DataFusion OLAP Engine (`datafusion`, `pyarrow`)
- `[all]` - Everything (DuckDB, all connectors, cloud tooling, ClickHouse, and DataFusion)

### Installation Matrix

Choose the installation that matches your environment and requirements:

#### Common Installation Scenarios

| Use Case                        | Platforms Enabled                         | Extras           | Recommended Command (uv)                    | Alternative (pip-compatible)              |
| ------------------------------- | ----------------------------------------- | ---------------- | ------------------------------------------- | ----------------------------------------- |
| **Local development & testing** | DuckDB, SQLite                            | `[duckdb]`       | `uv add benchbox --extra duckdb`            | `uv pip install "benchbox[duckdb]"`       |
| **Cloud storage helpers**       | S3, GCS, Azure path utilities             | `[cloudstorage]` | `uv add benchbox --extra cloudstorage`      | `uv pip install "benchbox[cloudstorage]"` |
| **All cloud platforms**         | Databricks, BigQuery, Redshift, Snowflake | `[cloud]`        | `uv add benchbox --extra cloud`             | `uv pip install "benchbox[cloud]"`        |
| **Everything included**         | All platforms + ClickHouse                | `[all]`          | `uv add benchbox --extra all`               | `uv pip install "benchbox[all]"`          |
| **Development with cloud**      | Core + all platforms + dev tools          | `[cloud,dev]`    | `uv add benchbox --extra cloud --extra dev` | `uv pip install "benchbox[cloud,dev]"`    |

#### Single Platform Installations

| Platform            | What's Included                     | Extras         | Recommended Command (uv)             | Alternative (pip-compatible)            |
| ------------------- | ----------------------------------- | -------------- | ------------------------------------ | --------------------------------------- |
| **DuckDB**              | Local analytics, TPC benchmarks          | `[duckdb]`              | `uv add benchbox --extra duckdb`              | `uv pip install "benchbox[duckdb]"`              |
| **Polars**              | DataFrame engine, in-memory analytics    | `[polars]`              | `uv add benchbox --extra polars`              | `uv pip install "benchbox[polars]"`              |
| **ClickHouse Cloud**    | ClickHouse Cloud (HTTP connector)        | `[clickhouse-cloud]`    | `uv add benchbox --extra clickhouse-cloud`    | `uv pip install "benchbox[clickhouse-cloud]"`    |
| **PostgreSQL**          | PostgreSQL-compatible databases          | `[postgresql]`          | `uv add benchbox --extra postgresql`          | `uv pip install "benchbox[postgresql]"`          |
| **Databricks**          | SQL Warehouses, Unity Catalog, DBFS      | `[databricks]`          | `uv add benchbox --extra databricks`          | `uv pip install "benchbox[databricks]"`          |
| **Google BigQuery**     | BigQuery, Cloud Storage                  | `[bigquery]`            | `uv add benchbox --extra bigquery`            | `uv pip install "benchbox[bigquery]"`            |
| **Amazon Redshift**     | Redshift, S3 integration                 | `[redshift]`            | `uv add benchbox --extra redshift`            | `uv pip install "benchbox[redshift]"`            |
| **Snowflake**           | Snowflake Data Cloud                     | `[snowflake]`           | `uv add benchbox --extra snowflake`           | `uv pip install "benchbox[snowflake]"`           |
| **ClickHouse**          | ClickHouse Analytics (binary protocol)   | `[clickhouse]`          | `uv add benchbox --extra clickhouse`          | `uv pip install "benchbox[clickhouse]"`          |
| **ClickHouse Local**    | Embedded ClickHouse via chDB             | `[clickhouse-local]`    | `uv add benchbox --extra clickhouse-local`    | `uv pip install "benchbox[clickhouse-local]"`    |
| **ClickHouse Server**   | Self-hosted ClickHouse (binary protocol) | `[clickhouse-server]`   | `uv add benchbox --extra clickhouse-server`   | `uv pip install "benchbox[clickhouse-server]"`   |
| **DataFusion**          | Apache DataFusion OLAP Engine            | `[datafusion]`          | `uv add benchbox --extra datafusion`          | `uv pip install "benchbox[datafusion]"`          |

#### Advanced Combinations

| Scenario                   | Recommended Command (uv)                               | Alternative (pip-compatible)                      | Use Case                             |
| -------------------------- | ------------------------------------------------------ | ------------------------------------------------- | ------------------------------------ |
| **Multi-cloud analytics**  | `uv add benchbox --extra cloud --extra clickhouse`     | `uv pip install "benchbox[cloud,clickhouse]"`     | Compare cloud platforms + ClickHouse |
| **Full development setup** | `uv add benchbox --extra all --extra dev --extra docs` | `uv pip install "benchbox[all,dev,docs]"`         | Contributing to BenchBox             |
| **AWS-focused**            | `uv add benchbox --extra redshift`                     | `uv pip install "benchbox[redshift]"`             | Amazon Redshift only                 |
| **Google Cloud-focused**   | `uv add benchbox --extra bigquery`                     | `uv pip install "benchbox[bigquery]"`             | Google BigQuery only                 |
| **Azure-compatible**       | `uv add benchbox --extra databricks --extra snowflake` | `uv pip install "benchbox[databricks,snowflake]"` | Databricks + Snowflake on Azure      |

#### Alternative Package Managers

All installation commands above work with different Python package managers:

| Package Manager      | Recommended Format                         | Example                                   | Alternative (pip-compatible)       |
| -------------------- | ------------------------------------------ | ----------------------------------------- | ---------------------------------- |
| **uv (recommended)** | `uv add benchbox --extra <name>`           | `uv add benchbox --extra cloud`           | `uv pip install "benchbox[cloud]"` |
| **pip**              | `python -m pip install "benchbox[extras]"` | `python -m pip install "benchbox[cloud]"` | N/A (only format available)        |
| **pipx**             | `pipx install "benchbox[extras]"`          | `pipx install "benchbox[cloud]"`          | N/A (only format available)        |

> **Note**: When using pip-compatible syntax, use quotes around the package specification (`"benchbox[extras]"`) to prevent shell expansion in zsh and other shells. The `uv add` syntax doesn't require quotes.

### Installing Multiple Extras

You can combine extras in a single installation command. Order does not matter.

**Recommended (using uv):**
```bash
uv add benchbox --extra cloud --extra clickhouse
```

**Alternative (pip-compatible):**
```bash
uv pip install "benchbox[cloud,clickhouse]"
python -m pip install "benchbox[cloud,clickhouse]"
pipx install "benchbox[cloud,clickhouse]"
```

Already installed BenchBox? Re-run the installer with the extras you need or use `pipx inject benchbox "benchbox[cloud]"` to add connectors to an existing pipx environment.

### Validate Your Installation

Use the built-in dependency checker to confirm that everything is ready before running benchmarks.

```bash
# Overview of installed extras
benchbox check-deps

# Focus on a single platform
benchbox check-deps --platform databricks

# View the installation matrix in the terminal
benchbox check-deps --matrix

# Include detailed guidance and next steps
benchbox check-deps --verbose
```

### Troubleshooting Installation Issues

#### Common Installation Problems

**Shell and Package Manager Issues:**
- **Shell quoting errors (`zsh: no matches found`)** - wrap extras in quotes: `"benchbox[cloud]"`
- **`uv` not installed** - install with `pipx install uv` or use `python -m pip install ...` instead
- **`pip` cannot find wheels** - upgrade packaging tools: `python -m pip install --upgrade pip setuptools wheel`
- **Conflicting virtual environments** - remove old installs: `pip uninstall benchbox` before re-installing

**Platform-Specific Compilation Issues:**
- **macOS SSL errors** - update certificates: `/Applications/Python 3.x/Install Certificates.command`
- **Windows Visual C++ build tools missing** - install "Desktop development with C++" workload from Visual Studio Installer
- **Linux missing development packages** - install build tools: `sudo apt-get install build-essential` (Ubuntu/Debian) or `sudo yum groupinstall "Development Tools"` (RHEL/CentOS)

**Cloud Platform Authentication:**
- **Databricks connection issues** - verify SQL warehouse is running and accessible
- **BigQuery authentication errors** - ensure service account credentials or `gcloud auth` is configured
- **Snowflake connection timeouts** - check network connectivity and account URL format
- **Redshift SSL errors** - verify cluster security group allows connections

#### Installation Verification

After installation, verify everything works:

```bash
# Check if BenchBox is installed and working
benchbox --version

# Verify your platform dependencies
benchbox check-deps

# Test core functionality
python -c "from benchbox import TPCH; print('✅ BenchBox core working')"

# Test specific platform (example for BigQuery)
python -c "from benchbox.platforms.bigquery import BigQueryAdapter; print('✅ BigQuery connector working')"
```

#### Quick Fixes for Common Errors

**Import Error: No module named 'benchbox'**
```bash
# Verify installation
pip list | grep benchbox
# If missing, reinstall
uv add benchbox
# or: uv pip install benchbox
```

**ModuleNotFoundError for platform-specific connectors**
```bash
# Install the missing platform extra
uv add benchbox --extra databricks
# or: uv pip install "benchbox[databricks]"
```

**Permission denied errors**
```bash
# Use user installation if you don't have admin rights
python -m pip install --user "benchbox[cloud]"
```

**Virtual environment conflicts**
```bash
# Clean install in fresh environment
python -m venv fresh_env
source fresh_env/bin/activate  # or `fresh_env\Scripts\activate` on Windows
uv add benchbox --extra cloud
# or: uv pip install "benchbox[cloud]"
```

For detailed platform-specific setup guides, see [Platform Documentation](docs/platforms/index.md) and the [Troubleshooting Guide](docs/usage/troubleshooting.md).

### Dependency Overview

BenchBox uses a layered dependency approach: minimal core dependencies for local development plus optional extras for specific platforms.

#### Core Dependencies (installed automatically)

These libraries are required for every installation and provide complete local benchmarking functionality:

- **sqlglot** - SQL dialect translation between databases
- **click** - Command-line interface framework
- **rich** - Terminal output formatting and progress indicators
- **psutil** - System resource monitoring
- **pydantic** - Data validation and configuration models
- **pyyaml** - YAML configuration file support
- **pytest libraries** - Testing framework components for built-in validation

The core package includes all necessary Python dependencies for running benchmarks. DuckDB is available via `benchbox[duckdb]` - a plain `benchbox` install uses SQLite. No external database servers or system installations are required for basic functionality.

#### Optional Platform Dependencies (installed on demand)

These extras add connectivity to specific platforms and are installed only when needed:

**Cloud Platform SDKs:**
- `[cloud]` - All major cloud platforms (Databricks, BigQuery, Redshift, Snowflake)
- `[databricks]` - Databricks SQL Warehouses (`databricks-sql-connector`, `cloudpathlib`)
- `[bigquery]` - Google BigQuery and Cloud Storage (`google-cloud-bigquery`, `google-cloud-storage`)
- `[redshift]` - Amazon Redshift (`redshift-connector`, `boto3` for S3)
- `[snowflake]` - Snowflake Data Cloud (`snowflake-connector-python`)

**Database-Specific Drivers:**
- `[clickhouse]` - ClickHouse Analytics (`clickhouse-driver`)

**Development Tools:**
- `[dev]` - Development dependencies (additional testing tools)
- `[docs]` - Documentation generation tools

#### Why This Architecture?

- **Fast installation**: Core package installs quickly with minimal dependencies
- **No vendor lock-in**: Install only the platforms you actually use
- **Reduced conflicts**: Platform-specific dependencies are isolated
- **Easy maintenance**: Update cloud SDKs independently of core functionality

## Quick Start

Get started with BenchBox in 3 steps:

### 1. Install BenchBox

Choose the installation that matches your target platform:

**Recommended (using uv):**
```bash
# For local development (DuckDB only)
uv add benchbox

# For cloud platforms (recommended)
uv add benchbox --extra cloud

# For everything (all platforms + ClickHouse)
uv add benchbox --extra all
```

**Alternative (pip-compatible):**
```bash
uv pip install benchbox
uv pip install "benchbox[cloud]"
uv pip install "benchbox[all]"
```

### 2. Verify Installation

Check that everything is working:

```bash
# Verify BenchBox is installed
benchbox --version

# Check available platforms
benchbox check-deps --matrix
```

### 3. Run Your First Benchmark

Start with a simple local benchmark:

```python
from benchbox import TPCH

# Create a small TPC-H benchmark for testing
tpch = TPCH(scale_factor=0.01)  # ~10MB dataset for quick testing

# Generate sample data
print("Generating data...")
data_paths = tpch.generate_data()
print(f"✅ Generated {len(data_paths)} data files")

# Get a sample query
query1 = tpch.get_query(1, seed=42)  # Reproducible parameters
print(f"✅ Generated TPC-H Query 1")

# Run on embedded DuckDB (no setup required)
import duckdb
conn = duckdb.connect(":memory:")

# Create schema and load data
conn.execute(tpch.get_create_tables_sql())
for table_file in data_paths:
    table_name = table_file.split('/')[-1].replace('.csv', '')
    conn.execute(f"COPY {table_name} FROM '{table_file}' WITH (DELIMITER '|', HEADER false)")

# Execute the query
result = conn.execute(query1).fetchdf()
print(f"✅ Query executed successfully, returned {len(result)} rows")
```

### Run a DataFrame Benchmark

Compare SQL vs DataFrame execution paradigms:

```bash
# SQL mode - queries executed via SQL
benchbox run --platform duckdb --benchmark tpch --scale 0.01

# DataFrame mode - queries executed via native Polars API
benchbox run --platform polars-df --benchmark tpch --scale 0.01
```

Same benchmark, same scale factor, different execution paradigm.

### Next Steps

**For Cloud Platforms:**
- See [Platform Documentation](docs/platforms/index.md) for platform-specific setup
- Start with `examples/getting_started/` for zero-config DuckDB runs and credential-ready cloud samples
- Explore `examples/features/` for capability-specific examples (query subsets, tuning, result analysis, etc.)
- Check `examples/use_cases/` for real-world patterns (CI/CD regression testing, platform evaluation, cost optimization)
- See `examples/programmatic/` for Python API usage and integration patterns
- Use `--dry-run OUTPUT_DIR` on the CLI or example scripts to export a JSON/YAML plan and per-query SQL files before executing benchmarks
- Use `benchbox run` CLI for full benchmark execution

**For Advanced Usage:**
- Explore the full benchmark suite: TPC-H, TPC-DS, TPC-DI, ClickBench, H2ODB, NYC Taxi, Flight Data, Vector Search, and more
- Scale up with larger datasets (scale factors 1.0, 10.0, 100.0+)
- Compare performance across different platforms
- See [examples/INDEX.md](examples/INDEX.md) for complete examples navigation
- See [examples/PATTERNS.md](examples/PATTERNS.md) for common workflow patterns
## Command-Line Interface (CLI)

BenchBox provides a comprehensive command-line interface (CLI) for all benchmarking operations, from data generation to result analysis.

### Quick CLI Reference

| Command               | Purpose                   | Example                                                   |
| --------------------- | ------------------------- | --------------------------------------------------------- |
| `benchbox run`        | Execute benchmarks        | `benchbox run --platform duckdb --benchmark tpch`         |
| `benchbox visualize`  | Generate result charts    | `benchbox visualize results.json`                         |
| `benchbox shell`      | Interactive SQL shell     | `benchbox shell --last --benchmark tpch`                  |
| `benchbox platforms`  | Manage database platforms | `benchbox platforms list`                                 |
| `benchbox check-deps` | Check dependencies        | `benchbox check-deps --platform databricks`               |
| `benchbox profile`    | System analysis           | `benchbox profile`                                        |
| `benchbox benchmarks` | Manage benchmark suites   | `benchbox benchmarks list`                                |

### Common CLI Workflows

**Local Development:**
```bash
# TPC-H benchmark on DuckDB
benchbox run --platform duckdb --benchmark tpch

# Run specific queries only (in custom order)
benchbox run --platform duckdb --benchmark tpch --queries "Q1,Q6,Q17"

# Run a single query for testing
benchbox run --platform duckdb --benchmark tpch --queries "Q1"

# Explore benchmark data interactively
benchbox shell --last --benchmark tpch

# System analysis for optimization recommendations
benchbox profile

# See all CLI examples
benchbox run --help examples

# Check available benchmarks
benchbox benchmarks list
```

#### Running Specific Queries with `--queries`

The `--queries` flag allows you to run a subset of benchmark queries in your specified order, useful for debugging and focused testing:

```bash
# Run specific TPC-H queries in custom order
benchbox run --platform duckdb --benchmark tpch --queries "1,6,17"

# Run single query for debugging
benchbox run --platform duckdb --benchmark tpch --queries "6"

# TPC-DS queries (1-99)
benchbox run --platform duckdb --benchmark tpcds --queries "1,2,3"
```

**Query ID Ranges by Benchmark:**
- **TPC-H**: 1-22
- **TPC-DS**: 1-99
- **SSB**: 1-13

**⚠️ Important Constraints:**

1. **TPC-H Compliance**: Using `--queries` overrides the official TPC-H stream permutation order, making results **non-compliant** with official TPC-H benchmarks. Use for development/debugging only.

2. **Validation Limits**:
   - Maximum 100 queries per run
   - Query IDs must be alphanumeric (letters, numbers, dash, underscore)
   - Maximum 20 characters per query ID
   - Duplicate query IDs are removed automatically

3. **Phase Compatibility**: Only applies to `power` and `standard` phases. Ignored for `warmup`, `throughput`, and `maintenance` phases.

4. **Order Preservation**: Queries execute in exactly the order you specify, not the benchmark's default order.

**Error Examples:**

```bash
# ERROR: Invalid query ID for TPC-H (only 1-22 valid)
benchbox run --platform duckdb --benchmark tpch --queries "99"
# ❌ Invalid query IDs: 99. Available: 1-22

# ERROR: Invalid format (no special characters)
benchbox run --platform duckdb --benchmark tpch --queries "1;DROP TABLE"
# ❌ Invalid query ID format (must be alphanumeric)

# ERROR: Too many queries
benchbox run --platform duckdb --benchmark tpch --queries "1,2,3,...,101"
# ❌ Too many queries: 101 (max 100)

# ERROR: Incompatible phases
benchbox run --platform duckdb --benchmark tpch --queries "1,6" --phases warmup
# ❌ --queries only works with power/standard phases
```

**Programmatic API Equivalent:**

```python
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH

benchmark = TPCH(scale_factor=1.0)
adapter = DuckDBAdapter()

# Load data
adapter.load_benchmark_data(benchmark)

# Run specific queries
run_config = {
    "query_subset": ["1", "6", "17"],  # Note: parameter is 'query_subset'
    "timeout": 60,
    "verbose": True
}

results = adapter.run_standard_queries(benchmark, run_config)
```

**Cloud Platform Setup:**
```bash
# Check platform dependencies
benchbox check-deps --platform databricks

# Install platform dependencies (if needed)
uv add benchbox --extra databricks
# or: uv pip install "benchbox[databricks]"

# Configure platform
benchbox platforms setup
```

**Production Benchmarking:**
```bash
# Full TPC-DS benchmark on Databricks with tuning
benchbox run --platform databricks --benchmark tpcds --scale 1 \
  --tuning tuned --phases power,throughput \
  --output dbfs:/Volumes/workspace/benchmarks/

# BigQuery with custom configuration
benchbox run --platform bigquery --benchmark tpch --scale 0.1 \
  --platform-option project_id=my-project \
  --verbose

# Snowflake baseline comparison
benchbox run --platform snowflake --benchmark tpch --scale 1 \
  --tuning notuning --output s3://my-bucket/baseline/
```

**Data Generation and Testing:**
```bash
# Generate test data only
benchbox run --benchmark tpch --scale 0.01 --phases generate \
  --output ./test-data

# Preview configuration without execution
benchbox run --platform databricks --benchmark tpcds --scale 0.1 \
  --dry-run ./preview

# Load data into database
benchbox run --platform duckdb --benchmark tpch --scale 0.1 \
  --phases load --force
```

### Key CLI Features

**Multi-Phase Execution:**
- `generate`: Create benchmark data files
- `load`: Load data into database
- `warmup`: Warm up database caches
- `power`: Execute single-stream queries
- `throughput`: Execute concurrent query streams
- `maintenance`: Execute data maintenance operations

**Platform Integration:**
- Automatic platform detection and configuration
- Platform-specific options via `--platform-option KEY=VALUE`
- Cloud storage support (S3, GCS, Azure Blob, DBFS)
- Authentication via environment variables

**Advanced Configuration:**
- Tuning modes: `tuned`, `notuning`, or custom config files
- Compression options: `none`, `gzip`, `zstd` with configurable levels
- Validation: preflight and post-load data validation
- Reproducible runs with seed control

**Output and Analysis:**
- JSON results saved automatically; export to CSV/HTML via `benchbox export`
- Dry-run mode for configuration preview
- Verbose logging for debugging
- Query plan capture with `--capture-plans`

### Visualizing Results

BenchBox generates ASCII charts directly in the terminal:

```bash
# Display charts in terminal
benchbox visualize benchmark_runs/results/*.json

# Without colors (for piping to files)
benchbox visualize benchmark_runs/results/*.json --no-color

# Without Unicode (for basic terminals)
benchbox visualize benchmark_runs/results/*.json --no-unicode
```

For HTML reports, use the export command:

```bash
benchbox export --last --format html
```

### Contributing Results

BenchBox also publishes a public results corpus and explorer at `benchbox.dev/results/`.
If you run BenchBox on a platform you want represented there, package the run with
`uv run -- benchbox submit --output ./submission` and open a PR against the `published-results`
branch of the public repository.

The full contributor workflow, local validation steps, and trust-label rules live in
[docs/contributing-results.md](docs/contributing-results.md).

**Chart Types Available:**
- `performance_bar` - Compare total execution time across platforms
- `distribution_box` - Query time distribution with quartiles and outliers
- `query_heatmap` - Per-query execution times across platforms
- `query_histogram` - Vertical bars showing individual query latencies
- `cost_scatter` - Cost vs performance trade-off (requires cost data)
- `time_series` - Performance trends over multiple runs

**Examples:**
```bash
# Specific chart type
benchbox visualize results.json --chart-type query_heatmap

# Multiple chart types
benchbox visualize results.json --chart-type performance_bar --chart-type distribution_box

# All charts
benchbox visualize results.json --chart-type all
```

### Interactive vs Non-Interactive Mode

**Interactive Mode (Default):**
```bash
# Guided setup with system recommendations
benchbox run
```

**Non-Interactive Mode:**
```bash
# Direct execution with all parameters specified
benchbox run --platform duckdb --benchmark tpch --scale 0.01 \
  --non-interactive

# Automation-friendly with environment variables
BENCHBOX_NON_INTERACTIVE=true benchbox run \
  --platform databricks --benchmark tpcds --quiet
```

### Platform-Specific Examples

**Databricks:**
```bash
# Databricks SQL Warehouse with Unity Catalog
benchbox run --platform databricks --benchmark tpch --scale 1 \
  --platform-option catalog=main \
  --platform-option schema=benchbox \
  --output dbfs:/Volumes/main/benchbox/results/

# Check available Databricks options
benchbox run --describe-platform-options databricks
```

**BigQuery:**
```bash
# BigQuery with custom project and dataset
benchbox run --platform bigquery --benchmark tpcds --scale 0.1 \
  --platform-option project_id=my-project \
  --platform-option dataset=benchbox \
  --output gs://my-bucket/benchmarks/

# BigQuery with specific location
benchbox run --platform bigquery --benchmark tpch \
  --platform-option location=europe-west1
```

**Snowflake:**
```bash
# Snowflake with custom warehouse
benchbox run --platform snowflake --benchmark tpch --scale 1 \
  --platform-option warehouse=LARGE_WH \
  --platform-option database=BENCHBOX \
  --tuning tuned

# Snowflake baseline run
benchbox run --platform snowflake --benchmark tpcds \
  --tuning notuning --phases power
```

**ClickHouse:**
```bash
# Local ClickHouse instance
benchbox run --platform clickhouse --benchmark clickbench \
  --platform-option mode=local \
  --platform-option port=9000

# ClickHouse with TLS
benchbox run --platform clickhouse --benchmark tpch \
  --platform-option secure=true \
  --platform-option port=9440
```

### Troubleshooting CLI Issues

**Common Issues:**

1. **Platform Dependencies Missing:**
```bash
# Check what's needed
benchbox check-deps --platform databricks

# Install missing dependencies
uv add benchbox --extra databricks
# or: uv pip install "benchbox[databricks]"
```

2. **Authentication Errors:**
```bash
# Check platform status
benchbox platforms status

# Verify environment variables
echo $DATABRICKS_TOKEN
```

3. **Memory or Storage Issues:**
```bash
# Profile system for recommendations
benchbox profile

# Use smaller scale factors
benchbox run --platform duckdb --benchmark tpch --scale 0.001
```

4. **Configuration Problems:**
```bash
# Validate configuration
benchbox validate

# Preview settings with dry-run
benchbox run --dry-run ./debug --platform duckdb --benchmark tpch
```

### CLI Help and Documentation

**Get Help:**
```bash
# General help
benchbox --help

# Command-specific help
benchbox run --help
benchbox platforms --help

# Platform options
benchbox run --describe-platform-options clickhouse
```

**Enable Verbose Output:**
```bash
# Standard verbose logging
benchbox run --verbose --platform duckdb --benchmark tpch

# Very verbose for debugging
benchbox run -vv --platform duckdb --benchmark tpch
```

For complete CLI documentation, see [CLI Reference](docs/CLI_REFERENCE.md).

### Remote Output Paths (Minimal Example)

When you pass a remote output root (dbfs:/, s3://, gs://, abfss://), BenchBox appends
the dataset suffix automatically for consistency with local paths.

CLI example:

```bash
benchbox run \
  --platform databricks \
  --benchmark tpch \
  --scale 0.01 \
  --output dbfs:/Volumes/workspace/raw/source/
# Writes to: dbfs:/Volumes/workspace/raw/source/tpch_sf01
```

### Platform-Specific Options

Platform adapters now register their own CLI options that are supplied via the
generic `--platform-option` flag. Each option follows a `KEY=VALUE` format and
can be provided multiple times. For example, to run ClickHouse in local mode
with TLS enabled:

```bash
benchbox run \
  --platform clickhouse \
  --benchmark tpch \
  --platform-option mode=local \
  --platform-option secure=true
```

You can inspect the available options for any platform without executing a
benchmark by using `--describe-platform-options`:

```bash
benchbox run --describe-platform-options clickhouse
```

Python helper:

```python
from benchbox.utils.output_path import normalize_output_root
print(normalize_output_root("s3://bucket/prefix", "tpch", 0.01))
# s3://bucket/prefix/tpch_sf01
```

## Benchmarks Provided

### TPC Standards
* **TPC-H** - 22 queries for data warehouses. Tests basic SQL operations with string columns and date predicates.
    * Official site: http://www.tpc.org/tpch
* **TPC-DS** - 99 complex queries with CTEs, subqueries, window functions. Tests advanced SQL features.
    * Official site: http://www.tpc.org/tpcds
* **TPC-DI** - ETL workflows and data integration testing. Focuses on data transformation pipelines.
    * Official site: http://www.tpc.org/tpcdi

### Academic Benchmarks
* **SSB** - Star schema queries for OLAP testing. Simplified dimensional modeling.
    * Original paper: https://www.cs.umb.edu/~poneil/StarSchemaB.PDF
* **AMPLab** - Big data benchmark with text processing. Complex data patterns.
    * Original site: https://amplab.cs.berkeley.edu/benchmark/
* **Join Order** - Canonical IMDb 2013 JOB dataset for join optimization testing. Runs at sf=1 only; first use downloads and verifies the Parquet archive under `BENCHBOX_OUTPUT_DIR` / `benchmark_runs/datagen/joinorder_sf1/`.
    * Original paper: https://www.vldb.org/pvldb/vol9/p204-leis.pdf

### Industry Benchmarks
* **ClickBench** - Real-world analytical queries from web analytics. Wide range of operations.
    * Official site: https://benchmark.clickhouse.com
* **H2ODB/db-benchmark** - Data science operations. GroupBy and join patterns for analytical workloads.
    * Current version: https://duckdblabs.github.io/db-benchmark/
* **NYC Taxi** - 25 OLAP queries on real NYC TLC taxi trip data. Temporal, geographic, and financial analytics.
    * Data source: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
* **TSBS DevOps** - Time Series Benchmark Suite for DevOps monitoring. 18 queries testing CPU, memory, disk, network metrics.
    * Based on: https://github.com/timescale/tsbs
* **CoffeeShop** - Point-of-sale benchmark with regional weighting. 11 analytics queries on retail transaction data.
    * Newly created for BenchBox

### BenchBox Primitives
* **Read Primitives** - 136 queries testing aggregation, joins, filters, window functions, and advanced SQL operations.
    * Newly created for BenchBox
* **Write Primitives** - 12 write operations testing INSERT, UPDATE, DELETE, BULK_LOAD, MERGE, DDL, TRANSACTION operations.
    * Newly created for BenchBox
* **Transaction Primitives** - 12 transaction operations testing ACID compliance, isolation levels, savepoints.
    * Newly created for BenchBox
* **Metadata Primitives** - 62 catalog-introspection queries across information_schema, system catalogs, and platform-specific metadata views.
    * Newly created for BenchBox
* **AI Primitives** - 16 AI/ML function queries for Snowflake Cortex, BigQuery ML, and Databricks AI (embeddings, classification, summarization).
    * Newly created for BenchBox

### BenchBox Experimental
* **TPC-H Data Vault** - TPC-H queries adapted for Data Vault 2.0 modeling (Hubs, Links, Satellites). Tests enterprise DWH patterns.
    * Newly created for BenchBox
* **TPC-DS-OBT** - TPC-DS queries adapted for a single denormalized "One Big Table" schema. Tests wide-table analytics.
    * Newly created for BenchBox
* **TPC-Havoc** - Query optimizer stress testing. 220 query variants (22 TPC-H queries × 10 syntax variants).
    * Newly created for BenchBox
* **TPC-H Skew** - TPC-H with configurable data skew distributions. Tests optimizer behavior on non-uniform data.
    * Newly created for BenchBox

## TPC-H Detailed Example

BenchBox provides complete TPC-H implementation:

- Data generation per specification
- 22 queries with parameter substitution
- Schema definition and SQL generation
- Database loading and query execution
- Stream generation for concurrent testing
- Performance measurement and reporting

### Basic Usage

```python
from benchbox import TPCH

# Initialize TPC-H at scale factor 1 (~1GB data)
tpch = TPCH(scale_factor=1, output_dir="tpch_data")

# Generate data files (returns paths to the generated files)
data_files = tpch.generate_data()

# Get schema information
schema = tpch.get_schema()

# Get SQL to create tables
create_tables_sql = tpch.get_create_tables_sql()

# Get a specific query with random parameters
query1 = tpch.get_query(1)

# Get a query with specific parameters
params = {"days": 90}  # 90 days for Query 1
query1_with_params = tpch.get_query(1, params=params, seed=42)

# Get all queries
all_queries = tpch.get_queries()
```

### Advanced Features

```python
from benchbox import TPCH

# Initialize with verbose output
tpch = TPCH(scale_factor=1, output_dir="tpch_data", verbose=True)

# Generate data if needed
tpch.generate_data()

# Generate query streams for concurrent testing
stream_files = tpch.generate_streams(
    num_streams=4,          # 4 concurrent streams
    rng_seed=42,           # Reproducible parameters
    streams_output_dir="streams"
)

# Get stream information
stream_info = tpch.get_all_streams_info()
for stream in stream_info:
    print(f"Stream {stream['stream_id']}: {len(stream['queries'])} queries")

# Load data directly into a database
tpch.load_data_to_database(
    connection_string="duckdb://tpch.db",
    dialect="duckdb",
    drop_existing=True
)

# Run individual queries with timing
result = tpch.run_query(
    query_id=1,
    connection_string="duckdb://tpch.db",
    dialect="duckdb"
)
print(f"Query 1 took {result['execution_time']:.3f}s")

# Run the full benchmark
benchmark_results = tpch.run_benchmark(
    connection_string="duckdb://tpch.db",
    queries=[1, 2, 3, 4, 5],  # Run specific queries
    iterations=3,              # Run each query 3 times
    dialect="duckdb"
)

# Run concurrent streams
stream_results = tpch.run_streams(
    connection_string="duckdb://tpch.db",
    stream_files=stream_files,
    concurrent=True,
    dialect="duckdb"
)
```

### Working with Databases

```python
from benchbox import TPCH
from pathlib import Path
import duckdb

# Initialize TPC-H benchmark
tpch = TPCH(scale_factor=0.1)  # Small scale for quick testing

# Generate data
tpch.generate_data()

# Create a DuckDB database and connection
conn = duckdb.connect("tpch.db")

# Create tables
conn.execute(tpch.get_create_tables_sql())

# Load data using DuckDB's efficient CSV reading
data_files = tpch.generate_data()
for file_path in data_files:
    table_name = Path(file_path).stem  # Get filename without extension
    print(f"Loading {table_name} from {file_path}")

    # DuckDB can read CSV files directly with proper delimiter
    conn.execute(f"""
        COPY {table_name} FROM '{file_path}'
        WITH (DELIMITER '|', HEADER false)
    """)

# Run a query
query = tpch.get_query(1)
results = conn.execute(query).fetchall()
print(results)

# You can also run all queries and time them
import time
for query_id in range(1, 23):  # TPC-H has 22 queries
    query = tpch.get_query(query_id, seed=42)  # Use seed for reproducible parameters
    start_time = time.time()
    result = conn.execute(query).fetchall()
    end_time = time.time()
    print(f"Query {query_id}: {len(result)} rows, {end_time - start_time:.3f}s")

# Clean up
conn.close()
```

## Testing

Run the test suite using either `make` commands or direct `pytest`:

```bash
# Fast tests (default)
make test
# or
uv run -- python -m pytest -m fast

# All tests
make test-all
# or
uv run -- python -m pytest

# Specific benchmark tests
make test-tpch
# or
uv run -- python -m pytest -m tpch

# Unit tests only
make test-unit
# or
uv run -- python -m pytest -m unit

# Integration tests only
make test-integration
# or
uv run -- python -m pytest -m "integration and not live_integration"

# With coverage (fast tests only - quick feedback)
make coverage-fast
# or full suite
make coverage-all
# or
uv run -- python -m pytest --cov=benchbox --cov-report=term-missing
```

## Cloud Platform Notebooks

Ready-to-run notebooks for major cloud platforms are available in `examples/notebooks`:

- Databricks: examples/notebooks/databricks_benchmarking.ipynb
- BigQuery: examples/notebooks/bigquery_benchmarking.ipynb
- Snowflake: examples/notebooks/snowflake_benchmarking.ipynb
- Redshift: examples/notebooks/redshift_benchmarking.ipynb
- ClickHouse: examples/notebooks/clickhouse_benchmarking.ipynb

See examples/notebooks/README.md for structure, prerequisites, and selection guidance.

## Extending BenchBox

Add new benchmarks by extending `BaseBenchmark`:

```python
from benchbox import BaseBenchmark

class MyCustomBenchmark(BaseBenchmark):
    def __init__(self, scale_factor=1.0, **kwargs):
        super().__init__(scale_factor=scale_factor, **kwargs)
        # Custom initialization

    def generate_data(self, tables=None, output_format="memory"):
        # Implement data generation logic
        pass

    def get_query(self, query_id):
        # Return a specific query
        pass

    def get_all_queries(self):
        # Return all benchmark queries
        pass

    def execute_query(self, query_id, connection, params=None):
        # Execute a query against a database
        pass
```

## Project Structure

```
BenchBox/
├── benchbox/                       # Main package directory
│   ├── __init__.py                 # Package initialization
│   ├── base.py                     # Base class for benchmarks
│   ├── tpch.py                     # TPC-H implementation
│   ├── core/                       # Core implementation modules
│   │   ├── __init__.py
│   │   ├── tpch/                   # TPC-H detailed implementation
│   │   │   ├── __init__.py
│   │   │   ├── benchmark.py        # Main TPC-H benchmark class
│   │   │   ├── generator.py        # Data generation logic
│   │   │   ├── queries.py          # Query management
│   │   │   └── schema.py           # Schema definition
├── tests/                          # Test directory
│   ├── __init__.py
│   ├── conftest.py                 # Common pytest fixtures
│   ├── test_tpch.py                # Tests for TPC-H benchmark
│   ├── test_tpch_comprehensive.py  # Comprehensive TPC-H tests
│   ├── specialized/                # Specialized test cases
│   │   ├── test_tpch_minimal.py    # Minimal TPC-H tests
│   │   └── test_tpcds_minimal.py   # Minimal TPC-DS tests
│   ├── utilities/                  # Unified test utilities
│   │   ├── unified_test_runner.py  # Unified test runner
│   │   └── benchmark_validator.py  # Benchmark validation
│   ├── integration/                # Integration tests
│   │   ├── __init__.py
│   │   └── test_database_integration.py  # Database integration tests
├── examples/                       # Example scripts and documentation
│   ├── getting_started/            # Beginner-friendly examples
│   │   ├── local/                  # DuckDB and SQLite examples
│   │   └── cloud/                  # Cloud platform examples
│   ├── features/                   # Feature-specific examples (8 files)
│   │   ├── test_types.py           # Power, throughput, maintenance tests
│   │   ├── query_subset.py         # Query selection strategies
│   │   ├── tuning_comparison.py    # Baseline vs tuned comparison
│   │   ├── result_analysis.py      # Result loading and comparison
│   │   ├── multi_platform.py       # Multi-platform execution
│   │   ├── export_formats.py       # JSON, CSV, HTML export
│   │   ├── data_validation.py      # Data quality checks
│   │   └── performance_monitoring.py # Resource monitoring
│   ├── use_cases/                  # Production-ready patterns (4 files)
│   │   ├── ci_regression_test.py   # CI/CD regression testing
│   │   ├── platform_evaluation.py  # Platform comparison
│   │   ├── incremental_tuning.py   # Iterative optimization
│   │   └── cost_optimization.py    # Cost management
│   ├── programmatic/               # Python API documentation
│   │   └── README.md               # API reference and integration examples
│   ├── INDEX.md                    # Complete examples navigation
│   └── PATTERNS.md                 # Common workflow patterns
├── Makefile                        # Build and test automation
├── pytest.ini                     # Fast local pytest configuration
├── pytest-ci.ini                  # CI pytest profile (coverage + reports)
└── README.md                       # Project README
```

## Contributing

As Beta software, BenchBox benefits greatly from community feedback and contributions. Here's how you can help:

### Reporting Issues

**Bug Reports**: Found a problem? [Create an issue](https://github.com/joeharris76/benchbox/issues/new) with:
- Steps to reproduce the issue
- Expected vs actual behavior
- Environment details (Python version, platform, database)
- Minimal code example if possible

**Feature Requests**: Have an idea? [Open an issue](https://github.com/joeharris76/benchbox/issues/new) describing:
- The use case and problem you're trying to solve
- Proposed solution or approach
- How it fits with existing functionality

### Community Guidelines

- **Be patient**: As Beta software, responses may take time
- **Search first**: Check existing [issues](https://github.com/joeharris76/benchbox/issues) before creating new ones
- **Be specific**: Detailed reports help us understand and fix issues faster
- **Stay constructive**: Focus on problems and solutions, not criticism

### Development Contributions

Ready to contribute code? Here's the process:

1. **Fork and clone** the repository
2. **Install dependencies**: `uv sync --group dev` (or `uv pip install -e ".[dev]"`)
3. **Run tests**: `make test` to ensure everything works
4. **Make changes** with appropriate tests
5. **Test thoroughly**: `make test-all` and `make lint`
6. **Submit pull request** with clear description of changes

### Contact

- **GitHub Issues**: Primary channel for bugs and features
- **Discussions**: Use GitHub discussions for questions and ideas
- **Email**: For security issues or private concerns: joe@benchbox.dev

## Disclaimer

BenchBox is an independent personal project by Joe Harris, not affiliated with any past or present employer. See [DISCLAIMER.md](DISCLAIMER.md) for full details.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
