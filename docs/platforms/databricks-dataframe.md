<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Databricks DataFrame Platform

```{tags} intermediate, guide, databricks-df, dataframe-platform, cloud-platform
```

> **CLI name:** `databricks-df` - use `benchbox run --platform databricks-df`

Databricks DataFrame executes BenchBox benchmarks using the PySpark DataFrame
API on Databricks compute, via Spark Connect or Databricks Connect. It reuses
the full SQL-mode Databricks infrastructure - Unity Catalog, UC Volume staging,
Delta Lake tables - but runs queries as DataFrame expressions instead of SQL.

## Features

- **PySpark DataFrame API** - filter, groupBy, agg, join expressions on Databricks compute
- **Spark Connect / Databricks Connect** - remote DataFrame execution
- **Shared SQL infrastructure** - same auth, UC Volume staging, Delta tables as `databricks` SQL mode
- **Expression family** - comparable to `pyspark-df`, `datafusion-df`, `polars-df`
- **Unity Catalog** - catalog / schema-aware execution

## When to Use

| Goal                                              | Recommended Platform     |
| ------------------------------------------------- | ------------------------ |
| Evaluate Databricks SQL Warehouse performance     | `databricks` (SQL)       |
| Evaluate PySpark on Databricks Connect compute    | `databricks-df`          |
| Compare SQL vs. DataFrame on the same workload    | Run both, same benchmark |

## Installation

```bash
# Installs databricks-sql-connector + databricks-sdk + databricks-connect
uv add benchbox --extra cloud-spark-databricks
```

The base `databricks` extra covers SQL-mode only; it does **not** pull in
`databricks-connect`. Use `cloud-spark-databricks` (or the legacy
`databricks-connect` alias) for DataFrame-mode runs. See
[Databricks Connect docs](https://docs.databricks.com/aws/en/dev-tools/databricks-connect).

## Authentication

Same credentials as the `databricks` SQL platform - set via environment
variables or `--platform-option`:

| Variable                | Purpose                                              |
| ----------------------- | ---------------------------------------------------- |
| `DATABRICKS_HOST`       | Workspace URL (`xxx.cloud.databricks.com`)           |
| `DATABRICKS_TOKEN`      | Personal access token                                |
| `DATABRICKS_HTTP_PATH`  | SQL Warehouse HTTP path (used for the load phase)    |

The DataFrame adapter itself accepts `cluster_id`, but BenchBox does not yet
surface that field through the shared Databricks config builder or
`--platform-option`. Select the target cluster in your external Databricks
Connect / Spark Connect configuration instead. `DATABRICKS_HTTP_PATH` remains
required for the load phase, which uses the SQL connector regardless of
execution mode.

## Usage

```bash
# Run TPC-H with DataFrame execution
benchbox run --platform databricks-df --benchmark tpch --scale 1.0

# Compare SQL vs DataFrame on the same benchmark
benchbox run --platform databricks    --benchmark tpch --scale 1.0  # SQL
benchbox run --platform databricks-df --benchmark tpch --scale 1.0  # DataFrame
```

## Supported Benchmarks

DataFrame-mode benchmarks require DataFrame query definitions. Covered today:

- TPC-H (22 queries)
- SSB (13 queries)
- Read Primitives (selected categories)
- Write Primitives (selected categories)

See the [DataFrame Platforms Overview](dataframe.md) for the full DataFrame
execution model and compatibility matrix.

## Notes

- Data loading uses the standard Databricks SQL connector (UC Volume staging +
  Delta Lake) regardless of execution mode. Only query execution differs.
- Credentials and Unity Catalog configuration are shared between `databricks`
  and `databricks-df` - a single authenticated environment serves both.
- Expect different performance profiles: SQL Warehouse (photon) vs. Databricks
  Connect (JVM Spark) execute the same logical query very differently.

## See Also

- [Databricks SQL](databricks.md) - sibling SQL-mode platform
- [DataFrame Platforms Overview](dataframe.md) - execution model
- [PySpark DataFrame](pyspark-dataframe.md) - self-hosted PySpark comparison
- [Snowpark Connect](snowpark-connect.md) - PySpark-compatible API on Snowflake
