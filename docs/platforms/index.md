<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Platform Documentation

```{tags} guide
```

Documentation for database platforms supported by BenchBox.

## Platform Guides

- [Platform Selection Guide](platform-selection-guide.md) - Choose the right platform for your needs
- [Quick Reference](quick-reference.md) - Quick comparison and feature matrix
- [Comparison Matrix](comparison-matrix.md) - Detailed platform comparison
- [Support Status](support-status.md) - Registry support taxonomy and optional import diagnostics
- [**Deployment Modes**](deployment-modes.md) - Platform deployment architecture (local, self-hosted, cloud)

## DataFrame Platforms (Native API)

BenchBox supports benchmarking DataFrame libraries using their native APIs instead of SQL. This enables direct performance comparison between SQL and DataFrame paradigms on identical workloads.

- [**DataFrame Platforms Overview**](dataframe.md) - Architecture, installation, and usage guide

### Available DataFrame Platforms

| Platform | CLI Name | Family | Status | Documentation |
|----------|----------|--------|--------|---------------|
| **Polars** | `polars-df` | Expression | Production-ready | [Polars DataFrame](polars.md) |
| **Pandas** | `pandas-df` | Pandas | Production-ready | [Pandas DataFrame](pandas-dataframe.md) |
| **Modin** | `modin-df` | Pandas | Production-ready | [Modin DataFrame](modin-dataframe.md) |
| **Dask** | `dask-df` | Pandas | Production-ready | [Dask DataFrame](dask-dataframe.md) |
| **cuDF** | `cudf-df` | Pandas | Production-ready | [cuDF DataFrame](cudf.md) |
| **PySpark** | `pyspark-df` | Expression | Production-ready | [PySpark DataFrame](pyspark-dataframe.md) |
| **LakeSail** | `lakesail-df` | Expression | Production-ready | [LakeSail DataFrame](lakesail.md) |
| **DataFusion** | `datafusion-df` | Expression | Production-ready | [DataFusion DataFrame](datafusion-dataframe.md) |
| **Databricks** | `databricks-df` | Expression | Production-ready | [Databricks DataFrame](databricks-dataframe.md) |

```bash
# Quick start with DataFrame platforms
benchbox run --platform polars-df --benchmark tpch --scale 0.1    # Recommended - fast
benchbox run --platform pandas-df --benchmark tpch --scale 0.1    # Familiar API
benchbox run --platform modin-df --benchmark tpch --scale 0.1     # Parallel Pandas
benchbox run --platform dask-df --benchmark tpch --scale 0.1      # Distributed
benchbox run --platform cudf-df --benchmark tpch --scale 0.1      # GPU (Linux only)
benchbox run --platform pyspark-df --benchmark tpch --scale 0.1   # Spark ecosystem
benchbox run --platform lakesail-df --benchmark tpch --scale 0.1  # Sail (fast Spark)
benchbox run --platform datafusion-df --benchmark tpch --scale 0.1
benchbox run --platform databricks-df --benchmark tpch --scale 0.1  # Databricks Connect

# Compare SQL vs DataFrame on same workload
benchbox run --platform polars --benchmark tpch --scale 0.1       # SQL mode
benchbox run --platform polars-df --benchmark tpch --scale 0.1    # DataFrame mode
```

## SQL Platforms

### Core Local Databases

These platforms are included in the base BenchBox installation with no additional dependencies:

- [**DuckDB**](duckdb.md) - Embedded analytical database (default local platform)
- [**SQLite**](sqlite.md) - Embedded row-store database for lightweight testing

### Local/Embedded Analytics Engines

- [Apache DataFusion](datafusion.md) - Rust-based in-memory query engine
- [ClickHouse Local](clickhouse-local-mode.md) - Embedded ClickHouse via chDB (zero-config)
- [ClickHouse Server](clickhouse-server.md) - Self-hosted ClickHouse via clickhouse-driver
- [Polars](polars.md) - High-performance DataFrame library with SQL support

### Traditional Relational Databases

- [PostgreSQL](postgresql.md) - Open-source relational database with TimescaleDB support
- [CedarDB](cedardb.md) - High-performance HTAP engine over PostgreSQL wire protocol (formerly Umbra)

### PostgreSQL Extensions

- [pg_duckdb](pg_duckdb.md) - DuckDB-powered Postgres extension for vectorized OLAP
- [pg_mooncake](pg_mooncake.md) - Columnar storage for Postgres with Iceberg and Delta Lake support

### Self-Hosted OLAP Databases

- [StarRocks](starrocks.md) - MPP columnar OLAP database (MySQL protocol + Stream Load)
- [Apache Doris](doris.md) - MPP real-time analytical database (MySQL protocol + Stream Load)
- [SingleStore](singlestore.md) - Distributed SQL with columnstore analytics (MySQL protocol + LOAD DATA)
- [QuestDB](questdb.md) - Time-series database (PostgreSQL wire protocol + REST API)

### Distributed SQL Engines

- [PrestoDB](presto.md) - Distributed SQL query engine (Facebook fork)
- [Trino](trino.md) - Distributed SQL query engine (community fork, formerly PrestoSQL)
- [Apache Spark](spark.md) - Unified analytics engine for large-scale data processing
- [LakeSail Sail](lakesail.md) - High-performance Spark-compatible engine (Spark Connect)
- [Apache Gluten + Velox](velox.md) - Spark plugin that offloads physical operators to a vectorized C++ engine (Linux-only, Docker on macOS/Windows)

### Cloud Data Warehouses

- [**ClickHouse Cloud**](clickhouse-cloud.md) - Managed ClickHouse service (inherits ClickHouse dialect)
- [**Snowflake**](snowflake.md) - Cloud-native data platform (AWS, Azure, GCP)
- [**Databricks**](databricks.md) - Lakehouse platform with Unity Catalog support
- [**Onehouse Quanton**](quanton.md) - Serverless Spark with multi-format support (Hudi, Iceberg, Delta)
- [**Google BigQuery**](bigquery.md) - Serverless data warehouse
- [**Amazon Redshift**](redshift.md) - Columnar data warehouse
- [**MotherDuck**](motherduck.md) - Serverless DuckDB cloud (inherits DuckDB dialect)
- [**Starburst**](starburst.md) - Managed Trino / Starburst Galaxy (inherits Trino dialect)
- [Amazon Athena](athena.md) - Serverless query service for S3
- [Firebolt](firebolt.md) - High-performance cloud analytics (Core + Cloud modes)
- [Databend](databend.md) - Cloud-native OLAP warehouse (Snowflake-compatible SQL, S3/MinIO storage)
- [Azure Synapse Analytics](azure-platforms.md) - Microsoft cloud analytics platform
- [Microsoft Fabric Warehouse](microsoft-fabric.md) - T-SQL warehouse with OneLake-native storage
- [Microsoft Fabric Lakehouse SQL](fabric-lakehouse.md) - Read-only SQL endpoint over Fabric lakehouses
- [TimescaleDB / TigerData](timescaledb.md) - TimescaleDB with managed TigerData cloud mode (`timescaledb:cloud`)

### GPU-Accelerated Platforms

- [CUDF](cudf.md) - NVIDIA RAPIDS GPU-accelerated DataFrames

## Platform Categories

### By Installation Complexity

**Zero Config** (included in base install):
- DuckDB, SQLite

**Single Extra** (one `pip install` command):
- DataFusion, Polars, PostgreSQL, ClickHouse

**Cloud SDK Required** (authentication setup needed):
- Databricks SQL, Databend, BigQuery, Redshift, Snowflake, Amazon Athena, Firebolt, Azure Synapse Analytics

**Infrastructure Required** (external cluster needed):
- Trino, Presto, Spark, LakeSail, Gluten+Velox (Linux/Docker), StarRocks, Doris, QuestDB, ClickHouse (server mode)

### By Use Case

**Local Development & Testing:**
- DuckDB (recommended), SQLite, DataFusion, Polars

**Production Benchmarking:**
- Databricks, Snowflake, BigQuery, Redshift

**Self-Hosted Analytics:**
- ClickHouse, StarRocks, Doris, QuestDB, PostgreSQL, Trino, Presto, Spark, LakeSail, Gluten+Velox

**GPU Workloads:**
- CUDF (NVIDIA GPUs required)

## Quick Start by Platform

### Local Platforms (No Setup Required)

```bash
# DuckDB - Default, included in base install
benchbox run --platform duckdb --benchmark tpch --scale 0.01

# SQLite - Included in base install
benchbox run --platform sqlite --benchmark tpch --scale 0.01
```

### Cloud Platforms (Credentials Required)

```bash
# Databricks - Requires DATABRICKS_TOKEN and DATABRICKS_HOST
benchbox run --platform databricks --benchmark tpch --scale 1.0

# BigQuery - Requires GOOGLE_APPLICATION_CREDENTIALS
benchbox run --platform bigquery --benchmark tpch --scale 1.0

# Snowflake - Requires SNOWFLAKE_USER, SNOWFLAKE_PASSWORD, SNOWFLAKE_ACCOUNT
benchbox run --platform snowflake --benchmark tpch --scale 1.0
```

## Future Platforms

- [Development Roadmap](../development/roadmap.md) - Planned platform and benchmark additions

## Related Documentation

- [Getting Started](../usage/getting-started.md) - Quick start guide
- [Cloud Storage Guide](../guides/cloud-storage.md) - Cloud storage configuration for staging data
- [Platform Configuration](../usage/configuration.md) - Detailed configuration options

```{toctree}
:maxdepth: 1

platform-selection-guide
quick-reference
comparison-matrix
support-status
deployment-modes
dataframe
duckdb
sqlite
polars
pandas-dataframe
modin-dataframe
dask-dataframe
cudf
pyspark-dataframe
datafusion-dataframe
databricks-dataframe
spark
lakesail
velox
velox_jar_setup
starrocks
doris
singlestore
questdb
databend
cedardb
clickhouse-local-mode
clickhouse-server
clickhouse-cloud
clickhouse-migration
postgresql
pg_duckdb
pg_mooncake
presto
trino
snowflake
databricks
bigquery
redshift
motherduck
starburst
quanton
athena
athena-spark
firebolt
microsoft-fabric
fabric-lakehouse
azure-platforms
datafusion
influxdb
timescaledb
aws-glue
gcp-dataproc
dataproc-serverless
emr-serverless
fabric-spark
synapse-spark
snowpark-connect
```
