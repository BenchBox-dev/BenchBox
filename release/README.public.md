<!--
NOTE: This sanitized README is no longer used in public releases.
Public releases now use the full README.md from the repository root.

This file is kept for reference/historical purposes only.
Last used: Before 2025-11-07
-->

# BenchBox

BenchBox provides production-grade benchmark automation for analytical database
comparisons. It focuses on reliable, reproducible workflows that help you measure
performance across SQL engines with minimal setup.

## Included Benchmarks

**TPC Standards:**
- **TPC-H** - canonical 22-query decision-support benchmark
- **TPC-DS** - 99-query workload covering advanced SQL features
- **TPC-DI** - ETL workflows and data integration testing

**Academic & Industry Benchmarks:**
- **SSB** - Star Schema Benchmark for OLAP testing
- **AMPLab Big Data Benchmark** - real-world web analytics workload
- **H2O Benchmark** - machine-learning inspired feature engineering
- **ClickBench** - clickstream analytics benchmark
- **Join Order Bench** - optimizer join-order selection testing

**BenchBox Original Benchmarks:**
- **Read Primitives** - 90+ queries testing aggregations, joins, filters, window functions
- **Write Primitives** - 117 operations testing INSERT, UPDATE, DELETE, MERGE, DDL, transactions
- **Transaction Primitives** - concurrency and ACID compliance testing
- **TPC-Havoc** - query optimizer stress testing with multiple variants
- **CoffeeShop** - friendly getting-started workload for quick smoke tests

## Supported Platforms

**Local & Embedded:**
- **DuckDB** - default engine for local development and CI automation
- **SQLite** - lightweight baseline for functional validation

**Cloud Data Warehouses:**
- **Databricks** - SQL Warehouses with Unity Catalog support
- **Snowflake** - Snowflake Data Cloud
- **BigQuery** - Google Cloud BigQuery
- **Redshift** - Amazon Redshift

**Analytics Databases:**
- **ClickHouse** - high-performance analytical database

## Key Features

- End-to-end orchestration for data generation, schema creation, loading, and query execution
- Configurable scale factors, concurrency modes, and execution phases
- Rich CLI with dry-run previews, platform detection, and structured exports
- Built-in validation, metrics capture, and optional anonymised reporting

## Installation

**Core Installation** (DuckDB + SQLite):
```bash
uv add benchbox
```

**With Cloud Platforms**:
```bash
# All cloud platforms (Databricks, BigQuery, Redshift, Snowflake)
uv add benchbox --extra cloud

# Everything (all platforms + ClickHouse)
uv add benchbox --extra all

# Individual platforms
uv add benchbox --extra databricks  # Databricks only
uv pip install "benchbox[snowflake]"   # Snowflake only
uv pip install "benchbox[bigquery]"    # BigQuery only
uv pip install "benchbox[redshift]"    # Redshift only
uv pip install "benchbox[clickhouse]"  # ClickHouse only
```

BenchBox targets Python 3.10 through 3.14.

## Quick Start

**Local development:**
```bash
# Run TPC-H on DuckDB (no configuration needed)
benchbox run --platform duckdb --benchmark tpch --scale 0.01

# Check available platforms and dependencies
benchbox check-deps --matrix

# List all available benchmarks
benchbox benchmarks list
```

**Cloud platforms:**
```bash
# Databricks SQL Warehouse
benchbox run --platform databricks --benchmark tpch --scale 1 \
  --output dbfs:/Volumes/workspace/benchbox/data

# Snowflake
benchbox run --platform snowflake --benchmark tpcds --scale 0.1

# BigQuery
benchbox run --platform bigquery --benchmark tpch --scale 1 \
  --platform-option project_id=my-project
```

Use `benchbox --help` for the full CLI reference or explore the `examples/` directory for detailed usage patterns.

## Project Status

BenchBox is pre-release software. Expect rapid iteration and breaking changes as
we stabilise the public API. Track progress and roadmap items in the project's
issue tracker.

## License

MIT License. See `LICENSE` for details.
