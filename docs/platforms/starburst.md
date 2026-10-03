<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Starburst Platform

```{tags} intermediate, guide, starburst, sql-platform, cloud
```

Starburst Galaxy is a managed Trino service providing serverless distributed SQL query execution. BenchBox provides first-class Starburst support, inheriting Trino's SQL dialect and federated query capabilities.

## Features

- **Managed Trino** - No cluster management required
- **Trino dialect** - Inherits SQL dialect from Trino
- **Federated queries** - Query data across multiple sources
- **Built-in catalogs** - Pre-configured data connectors
- **HTTPS secure** - Always encrypted connections
- **Multiple table formats** - Iceberg, Hive, Delta Lake support

## Quick Start

```bash
uv add trino

export STARBURST_HOST=my-cluster.trino.galaxy.starburst.io
export STARBURST_USER=joe@example.com/accountadmin
export STARBURST_PASSWORD=your-password

benchbox run --platform starburst --benchmark tpch --scale 1.0
```

## Authentication

Starburst Galaxy uses a unique username format that combines your email with a role:

```
username = email/role
# Example: joe@example.com/accountadmin
```

### Configuration Methods

**Environment Variables (recommended):**

```bash
export STARBURST_HOST=my-cluster.trino.galaxy.starburst.io
export STARBURST_USER=joe@example.com/accountadmin
export STARBURST_PASSWORD=your-password

export STARBURST_USER=joe@example.com
export STARBURST_ROLE=accountadmin

export STARBURST_CATALOG=tpch_sf1

benchbox run --platform starburst --benchmark tpch --scale 1.0
```

**CLI Options:**

```bash
benchbox run --platform starburst --benchmark tpch --scale 1.0 \
    --platform-option host=my-cluster.trino.galaxy.starburst.io \
    --platform-option username=joe@example.com/accountadmin \
    --platform-option password=your-password \
    --platform-option catalog=tpch_sf1
```

## Configuration Options

| Option | Environment Variable | Required | Default | Description |
|--------|---------------------|----------|---------|-------------|
| `host` | `STARBURST_HOST` | Yes | - | Galaxy cluster hostname |
| `username` | `STARBURST_USER` / `STARBURST_USERNAME` | Yes | - | User email or email/role |
| `password` | `STARBURST_PASSWORD` | Yes | - | Password or API key |
| `role` | `STARBURST_ROLE` | No | - | Role (appended to username if not included) |
| `catalog` | `STARBURST_CATALOG` | No | - | Default catalog |
| `port` | `STARBURST_PORT` | No | `443` | HTTPS port |
| `schema` | - | No | `default` | Default schema |
| `table_format` | - | No | `iceberg` | Table format: `memory`, `hive`, `iceberg`, `delta` |
| `verify_ssl` | - | No | `true` | SSL certificate verification |

## Usage Examples

### Basic Benchmark

```bash
benchbox run --platform starburst --benchmark tpch --scale 1.0

benchbox run --platform starburst --benchmark tpcds --scale 10.0
```

### With Specific Catalog

```bash
benchbox run --platform starburst --benchmark tpch --scale 1.0 \
    --platform-option catalog=my_catalog \
    --platform-option schema=benchmark_data
```

### With Table Format

```bash
benchbox run --platform starburst --benchmark tpch --scale 1.0 \
    --platform-option table_format=iceberg

benchbox run --platform starburst --benchmark tpch --scale 1.0 \
    --platform-option table_format=delta
```

## Python API

```python
from benchbox import TPCH
from benchbox.platforms.starburst import StarburstAdapter

adapter = StarburstAdapter(
    host="my-cluster.trino.galaxy.starburst.io",
    username="joe@example.com/accountadmin",
    password="your-password",
    catalog="tpch_catalog",
    schema="benchmark_data",
    table_format="iceberg",
)

benchmark = TPCH(scale_factor=1.0)
benchmark.generate_data()
adapter.load_benchmark(benchmark)
results = adapter.run_benchmark(benchmark)
```

## Architecture

Starburst inherits from Trino, which means:

- **SQL Dialect**: Uses Trino's SQL dialect for query translation
- **Connector Syntax**: Same catalog.schema.table naming convention
- **Session Properties**: Trino session properties are supported

```python
from benchbox.core.platform_registry import PlatformRegistry

family = PlatformRegistry.get_platform_family("starburst")

parent = PlatformRegistry.get_inherited_platform("starburst")
```

## Table Formats

Starburst Galaxy supports multiple table formats:

| Format | Description | Use Case |
|--------|-------------|----------|
| `memory` | In-memory tables | Fast testing, small data |
| `hive` | Hive format | Compatibility with Hive ecosystem |
| `iceberg` | Apache Iceberg | Production analytics, ACID transactions |
| `delta` | Delta Lake | Databricks ecosystem integration |

```bash
benchbox run --platform starburst --benchmark tpch --scale 1.0 \
    --platform-option table_format=iceberg
```

## Comparison: Starburst vs Trino

| Feature | Starburst Galaxy | Self-Hosted Trino |
|---------|-----------------|-------------------|
| Deployment | Cloud managed | Self-hosted cluster |
| Authentication | Password/API key | Configurable |
| SSL | Always HTTPS | Configurable |
| Scaling | Automatic | Manual |
| Catalogs | Pre-configured | Manual setup |
| Cost | Pay-per-use | Infrastructure cost |
| Best For | Quick start, production | Full control, customization |

## When to Use Starburst

**Use Starburst when:**
- You need managed Trino without cluster management
- Running federated queries across multiple data sources
- Using Iceberg/Delta Lake table formats
- You want built-in catalog management

**Use self-hosted Trino instead when:**
- You need full control over cluster configuration
- Cost optimization is critical
- You have existing Trino infrastructure
- You need specific Trino plugins/connectors

## Troubleshooting

### Authentication Failed (401)

```
Starburst Galaxy authentication failed.
```

**Solutions:**
1. Verify username format: `email/role` (e.g., `joe@example.com/accountadmin`)
2. Check password is correct
3. Verify credentials at [galaxy.starburst.io](https://galaxy.starburst.io)

### Connection Refused

```
Cannot connect to Starburst Galaxy at {host}:{port}
```

**Solutions:**
1. Verify host is correct: `{cluster-name}.trino.galaxy.starburst.io`
2. Check network connectivity
3. Verify no firewall blocking port 443

### SSL Certificate Error

```
SSL certificate error connecting to Starburst Galaxy.
```

**Solutions:**
1. Check network proxy settings
2. Verify SSL certificate chain
3. Use `--platform-option verify_ssl=false` (not recommended for production)

### Catalog Not Found

```
Catalog 'my_catalog' does not exist
```

**Solutions:**
1. Create the catalog in Starburst Galaxy console
2. Use an existing catalog: check available catalogs in the console
3. Omit catalog option to use the default

## Related Documentation

- [Trino Platform](trino.md) - Self-hosted Trino benchmarking
- [Deployment Modes Guide](deployment-modes.md) - Platform deployment architecture
- [Platform Selection Guide](platform-selection-guide.md) - Choose the right platform
- [Getting Started](../usage/getting-started.md) - Quick start guide
