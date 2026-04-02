<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Platform Deployment Modes

```{tags} guide, architecture
```

BenchBox supports multiple deployment modes for database platforms, enabling you to run the same benchmark against local, self-hosted, and cloud-managed instances of the same database engine. This guide explains the deployment mode architecture, configuration, and usage patterns.

## Overview

A **deployment mode** represents how a database platform is deployed and accessed:

| Mode | Description | Examples |
|------|-------------|----------|
| **local** | Embedded/in-process, no external server required | DuckDB, chDB (ClickHouse local), Firebolt Core |
| **self-hosted** | User-managed server or cluster | ClickHouse Server, Trino, TimescaleDB |
| **managed** | Vendor-managed cloud service | MotherDuck, ClickHouse Cloud, Starburst Galaxy, Timescale Cloud |

### Why Deployment Modes Matter

- **Same dialect, different infrastructure**: MotherDuck uses DuckDB's SQL dialect but requires cloud authentication
- **Consistent benchmarking**: Compare local vs cloud performance with identical queries
- **Flexible configuration**: Each mode has specific authentication and connection requirements

## Quick Start

### Syntax

Use the colon syntax to specify deployment modes:

```bash
# Default mode (usually local or self-hosted)
benchbox run --platform clickhouse --benchmark tpch --scale 0.1

# Explicit deployment mode
benchbox run --platform clickhouse:local --benchmark tpch --scale 0.1
benchbox run --platform clickhouse:server --benchmark tpch --scale 0.1

# ClickHouse Cloud is a first-class platform (not a deployment mode)
benchbox run --platform clickhouse-cloud --benchmark tpch --scale 0.1
```

### Platform-Specific Examples

```bash
# ClickHouse: local (chDB) or server (self-hosted)
benchbox run --platform clickhouse:local --benchmark tpch --scale 0.1
benchbox run --platform clickhouse:server --benchmark tpch --scale 0.1

# ClickHouse Cloud: first-class platform (not a deployment mode)
benchbox run --platform clickhouse-cloud --benchmark tpch --scale 0.1 \
    --platform-option host=abc123.aws.clickhouse.cloud

# Firebolt: core (local Docker), cloud (Firebolt Cloud)
benchbox run --platform firebolt:core --benchmark tpch --scale 0.1
benchbox run --platform firebolt:cloud --benchmark tpch --scale 0.1

# TimescaleDB: self-hosted or cloud (Timescale Cloud)
benchbox run --platform timescaledb --benchmark tpch --scale 0.1  # self-hosted
benchbox run --platform timescaledb:cloud --benchmark tpch --scale 0.1

# Standalone cloud platforms (managed mode only)
benchbox run --platform motherduck --benchmark tpch --scale 0.1
benchbox run --platform starburst --benchmark tpch --scale 0.1
```

## Platform Deployment Reference

### Platforms with Multiple Deployment Modes

| Platform | Default Mode | Available Modes | Notes |
|----------|--------------|-----------------|-------|
| **ClickHouse** | `local` | `local`, `server` | Local uses chDB, server uses clickhouse-driver |
| **Firebolt** | `core` | `core`, `cloud` | Core is free local Docker deployment |
| **TimescaleDB** | `self-hosted` | `self-hosted`, `cloud` | Cloud mode for Timescale Cloud |
| **PySpark** | `local` | `local` | Local single-node Spark |

### First-Class Cloud Platforms

| Platform | CLI Name | Inherits From | Notes |
|----------|----------|---------------|-------|
| **ClickHouse Cloud** | `clickhouse-cloud` | ClickHouse | Managed ClickHouse service (uses clickhouse-connect) |
| **MotherDuck** | `motherduck` | DuckDB | Serverless DuckDB cloud |
| **Starburst** | `starburst` | Trino | Starburst Galaxy managed Trino |
| **Snowflake** | `snowflake` | - | Multi-cloud data warehouse |
| **Databricks** | `databricks` | - | Lakehouse platform |
| **BigQuery** | `bigquery` | - | GCP serverless warehouse |
| **Redshift** | `redshift` | - | AWS data warehouse |

### Configuration Inheritance

Some platforms inherit SQL dialect and configuration from parent platforms:

| Platform | Parent | Inherited Features |
|----------|--------|-------------------|
| MotherDuck | DuckDB | SQL dialect, data types, benchmark compatibility |
| Starburst | Trino | SQL dialect, connector syntax, session properties |

This means MotherDuck automatically uses DuckDB's query translator and Starburst uses Trino's.

---

## ClickHouse Deployment Modes

ClickHouse supports two deployment modes for the base `clickhouse` platform, plus a separate first-class platform for ClickHouse Cloud.

### Local Mode (chDB)

Zero-configuration embedded ClickHouse via the chDB library.

```bash
# Install chDB
uv add chdb

# Run benchmark
benchbox run --platform clickhouse:local --benchmark tpch --scale 0.1

# Or simply (local is default)
benchbox run --platform clickhouse --benchmark tpch --scale 0.1
```

**Characteristics:**
- No server installation required
- In-process execution using chDB
- Same query engine as ClickHouse server
- Ideal for development and testing

### Server Mode (Self-Hosted)

Connect to a self-hosted ClickHouse server or cluster.

```bash
# Install driver
uv add clickhouse-driver

# Environment variables
export CLICKHOUSE_HOST=localhost
export CLICKHOUSE_PORT=9000
export CLICKHOUSE_USER=default
export CLICKHOUSE_PASSWORD=secret

# Run benchmark
benchbox run --platform clickhouse:server --benchmark tpch --scale 1.0

# Or with inline options
benchbox run --platform clickhouse:server --benchmark tpch --scale 1.0 \
    --platform-option host=clickhouse.example.com \
    --platform-option port=9000 \
    --platform-option username=benchuser \
    --platform-option password=secret
```

**Connection Parameters:**

| Parameter | Environment Variable | Default | Description |
|-----------|---------------------|---------|-------------|
| `host` | `CLICKHOUSE_HOST` | `localhost` | Server hostname |
| `port` | `CLICKHOUSE_PORT` | `9000` | Native protocol port |
| `username` | `CLICKHOUSE_USER` | `default` | Database username |
| `password` | `CLICKHOUSE_PASSWORD` | - | Database password |
| `database` | - | `default` | Target database |
| `secure` | - | `false` | Enable TLS |

### ClickHouse Cloud (First-Class Platform)

ClickHouse Cloud is now a **first-class platform** (`clickhouse-cloud`), not a deployment mode. This follows the pattern established by MotherDuck (DuckDB) and Starburst (Trino).

```bash
# Install clickhouse-connect
uv add clickhouse-connect

# Environment variables
export CLICKHOUSE_CLOUD_HOST=abc123.us-east-2.aws.clickhouse.cloud
export CLICKHOUSE_CLOUD_PASSWORD=your-password
export CLICKHOUSE_CLOUD_USER=default  # optional, defaults to 'default'

# Run benchmark (note: clickhouse-cloud, not clickhouse:cloud)
benchbox run --platform clickhouse-cloud --benchmark tpch --scale 1.0

# Or with inline options
benchbox run --platform clickhouse-cloud --benchmark tpch --scale 1.0 \
    --platform-option host=abc123.us-east-2.aws.clickhouse.cloud \
    --platform-option password=your-password
```

**Connection Parameters:**

| Parameter | Environment Variable | Default | Description |
|-----------|---------------------|---------|-------------|
| `host` | `CLICKHOUSE_CLOUD_HOST` | - | Cloud hostname (required) |
| `password` | `CLICKHOUSE_CLOUD_PASSWORD` | - | Password (required) |
| `username` | `CLICKHOUSE_CLOUD_USER` | `default` | Username |
| `port` | - | `8443` | HTTPS port |
| `database` | - | `default` | Target database |

**Notes:**
- Always uses HTTPS (port 8443)
- Compression enabled by default for network efficiency
- Result cache disabled by default for accurate benchmarking
- **Alias**: `clickhouse:cloud` is also accepted as a platform name

For full documentation, see [ClickHouse Cloud Platform](clickhouse-cloud.md).

---

## Firebolt Deployment Modes

Firebolt provides both a free local deployment (Core) and managed cloud service.

### Core Mode (Local Docker)

Free, self-hosted Firebolt via Docker with the same query engine as cloud.

```bash
# Start Firebolt Core
docker run -i --rm --ulimit memlock=8589934592:8589934592 \
  --security-opt seccomp=unconfined -p 127.0.0.1:3473:3473 \
  -v ./firebolt-core-data:/firebolt-core/volume \
  ghcr.io/firebolt-db/firebolt-core:preview-rc

# Install SDK
uv add firebolt-sdk

# Run benchmark
benchbox run --platform firebolt:core --benchmark tpch --scale 0.1 \
    --platform-option url=http://localhost:3473
```

**Configuration:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `url` | `http://localhost:3473` | Firebolt Core endpoint |
| `database` | `benchbox` | Database name (auto-created) |

**Characteristics:**
- No authentication required
- Same vectorized query engine as cloud
- Ideal for development and local testing
- Databases created implicitly on connection

### Cloud Mode (Firebolt Cloud)

Connect to Firebolt Cloud managed service with OAuth authentication.

```bash
# Environment variables
export FIREBOLT_CLIENT_ID=your-client-id
export FIREBOLT_CLIENT_SECRET=your-client-secret
export FIREBOLT_ACCOUNT_NAME=your-account
export FIREBOLT_ENGINE_NAME=your-engine

# Alternative environment variable names (also supported)
export SERVICE_ACCOUNT_ID=your-client-id
export SERVICE_ACCOUNT_SECRET=your-client-secret

# Run benchmark
benchbox run --platform firebolt:cloud --benchmark tpch --scale 1.0

# Or with inline options
benchbox run --platform firebolt:cloud --benchmark tpch --scale 1.0 \
    --platform-option client_id=your-client-id \
    --platform-option client_secret=your-client-secret \
    --platform-option account_name=your-account \
    --platform-option engine_name=your-engine
```

**Connection Parameters:**

| Parameter | Environment Variable | Required | Description |
|-----------|---------------------|----------|-------------|
| `client_id` | `FIREBOLT_CLIENT_ID` / `SERVICE_ACCOUNT_ID` | Yes | OAuth client ID |
| `client_secret` | `FIREBOLT_CLIENT_SECRET` / `SERVICE_ACCOUNT_SECRET` | Yes | OAuth client secret |
| `account_name` | `FIREBOLT_ACCOUNT_NAME` | Yes | Firebolt account name |
| `engine_name` | `FIREBOLT_ENGINE_NAME` | Yes | Engine to use for queries |
| `database` | `FIREBOLT_DATABASE` | No | Database name (default: `benchbox`) |
| `api_endpoint` | `FIREBOLT_API_ENDPOINT` | No | API endpoint (default: `api.app.firebolt.io`) |

**Notes:**
- Create service account credentials in Firebolt console: Settings > Service Accounts
- Result cache disabled by default for accurate benchmarking
- Cloud mode requires all four credential parameters

---

## TimescaleDB Deployment Modes

TimescaleDB extends PostgreSQL with time-series capabilities and supports both self-hosted and managed cloud deployments.

### Self-Hosted Mode (Default)

Connect to a self-hosted TimescaleDB server.

```bash
# Install driver
uv add psycopg2-binary

# Run benchmark
benchbox run --platform timescaledb --benchmark tpch --scale 0.1 \
    --platform-option host=localhost \
    --platform-option username=postgres \
    --platform-option password=secret
```

**Connection Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `host` | `localhost` | TimescaleDB server hostname |
| `port` | `5432` | PostgreSQL port |
| `username` | `postgres` | Database username |
| `password` | - | Database password |
| `database` | auto-generated | Target database |
| `sslmode` | `prefer` | SSL connection mode |

### Cloud Mode (Timescale Cloud)

Connect to Timescale Cloud managed service.

```bash
# Environment variables (preferred)
export TIMESCALE_SERVICE_URL=postgres://user:pass@abc123.tsdb.cloud.timescale.com:5432/tsdb?sslmode=require

# Or individual variables
export TIMESCALE_HOST=abc123.rc8ft3nbrw.tsdb.cloud.timescale.com
export TIMESCALE_PASSWORD=your-password
export TIMESCALE_USER=tsdbadmin  # optional, defaults to 'tsdbadmin'

# Run benchmark
benchbox run --platform timescaledb:cloud --benchmark tpch --scale 1.0
```

**Connection Parameters:**

| Parameter | Environment Variable | Default | Description |
|-----------|---------------------|---------|-------------|
| `service_url` | `TIMESCALE_SERVICE_URL` | - | Full connection URL (preferred) |
| `host` | `TIMESCALE_HOST` | - | Cloud hostname (required if no URL) |
| `password` | `TIMESCALE_PASSWORD` / `PGPASSWORD` | - | Password (required) |
| `username` | `TIMESCALE_USER` / `PGUSER` | `tsdbadmin` | Username |
| `port` | `TIMESCALE_PORT` / `PGPORT` | `5432` | PostgreSQL port |
| `database` | `TIMESCALE_DATABASE` / `PGDATABASE` | `tsdb` | Database name |

**Service URL Format:**
```
postgres://username:password@hostname:port/database?sslmode=require
```

**Notes:**
- Cloud mode always uses SSL (`sslmode=require`)
- Database management (DROP/CREATE) disabled in cloud mode
- Find your service URL in the Timescale Cloud console

---

## MotherDuck (Cloud DuckDB)

MotherDuck is a managed cloud service for DuckDB, inheriting DuckDB's SQL dialect.

```bash
# Install DuckDB (includes MotherDuck support)
uv add duckdb

# Environment variable
export MOTHERDUCK_TOKEN=your-token

# Run benchmark
benchbox run --platform motherduck --benchmark tpch --scale 1.0

# Or with inline token
benchbox run --platform motherduck --benchmark tpch --scale 1.0 \
    --platform-option token=your-token
```

**Configuration:**

| Parameter | Environment Variable | Default | Description |
|-----------|---------------------|---------|-------------|
| `token` | `MOTHERDUCK_TOKEN` | - | MotherDuck auth token (required) |
| `database` | - | `benchbox` | MotherDuck database name |
| `memory_limit` | - | `4GB` | Local memory limit for hybrid queries |

**Get Your Token:**
Visit [app.motherduck.com/token-request](https://app.motherduck.com/token-request)

**Characteristics:**
- Uses DuckDB SQL dialect
- Supports hybrid local/cloud queries
- Automatic data transfer to MotherDuck cloud

---

## Starburst (Managed Trino)

Starburst Galaxy is a managed Trino service, inheriting Trino's SQL dialect.

```bash
# Install Trino driver
uv add trino

# Environment variables
export STARBURST_HOST=my-cluster.trino.galaxy.starburst.io
export STARBURST_USER=joe@example.com/accountadmin
export STARBURST_PASSWORD=your-password

# Run benchmark
benchbox run --platform starburst --benchmark tpch --scale 1.0

# Or with inline options
benchbox run --platform starburst --benchmark tpch --scale 1.0 \
    --platform-option host=my-cluster.trino.galaxy.starburst.io \
    --platform-option username=joe@example.com/accountadmin \
    --platform-option password=your-password
```

**Connection Parameters:**

| Parameter | Environment Variable | Required | Description |
|-----------|---------------------|----------|-------------|
| `host` | `STARBURST_HOST` | Yes | Galaxy cluster hostname |
| `username` | `STARBURST_USER` / `STARBURST_USERNAME` | Yes | User email or email/role |
| `password` | `STARBURST_PASSWORD` | Yes | Password or API key |
| `role` | `STARBURST_ROLE` | No | Role (appended to username if not included) |
| `catalog` | `STARBURST_CATALOG` | No | Default catalog |
| `port` | `STARBURST_PORT` | No | Port (default: 443) |

**Username Format:**
```
email/role (e.g., joe@example.com/accountadmin)
```

If you provide the role separately via `STARBURST_ROLE`, it will be automatically appended to the username.

**Characteristics:**
- Uses Trino SQL dialect
- Always uses HTTPS (port 443)
- Supports Iceberg, Hive, and Delta table formats
- SSL verification enabled by default

---

## Architecture: DeploymentCapability System

The deployment mode system is built on the `DeploymentCapability` dataclass in `platform_registry.py`:

```python
@dataclass
class DeploymentCapability:
    """Describes requirements and characteristics of a specific deployment mode."""

    mode: Literal["local", "self-hosted", "managed"]
    requires_credentials: bool = False
    requires_cloud_storage: bool = False
    requires_network: bool = False
    default_for_platform: bool = False
    display_name: str = ""
    description: str = ""
    dependencies: list[str] = field(default_factory=list)
    auth_methods: list[str] = field(default_factory=list)
```

### Registry API

Query deployment information programmatically:

```python
from benchbox.core.platform_registry import PlatformRegistry

# Get available deployment modes
modes = PlatformRegistry.get_available_deployment_modes("clickhouse")
# ['local', 'server', 'cloud']

# Get default deployment mode
default = PlatformRegistry.get_default_deployment("clickhouse")
# 'local'

# Check if mode is supported
supported = PlatformRegistry.supports_deployment_mode("clickhouse", "cloud")
# True

# Get deployment capability details
cap = PlatformRegistry.get_deployment_capability("clickhouse", "cloud")
# DeploymentCapability(mode='managed', requires_credentials=True, ...)

# Check cloud storage requirements
needs_storage = PlatformRegistry.requires_cloud_storage_for_deployment("clickhouse", "cloud")
# True
```

### Platform Family and Inheritance

Platforms can inherit SQL dialect and configuration from parent platforms:

```python
# Get platform family for dialect inheritance
family = PlatformRegistry.get_platform_family("motherduck")
# 'duckdb'

# Get parent platform for configuration inheritance
parent = PlatformRegistry.get_inherited_platform("motherduck")
# 'duckdb'

parent = PlatformRegistry.get_inherited_platform("starburst")
# 'trino'
```

---

## Authentication Best Practices

### Environment Variables (Recommended)

Store credentials in environment variables to avoid exposing them in command history:

```bash
# ClickHouse Cloud
export CLICKHOUSE_CLOUD_HOST=...
export CLICKHOUSE_CLOUD_PASSWORD=...

# Firebolt Cloud
export FIREBOLT_CLIENT_ID=...
export FIREBOLT_CLIENT_SECRET=...
export FIREBOLT_ACCOUNT_NAME=...
export FIREBOLT_ENGINE_NAME=...

# MotherDuck
export MOTHERDUCK_TOKEN=...

# Starburst Galaxy
export STARBURST_HOST=...
export STARBURST_USER=...
export STARBURST_PASSWORD=...

# Timescale Cloud
export TIMESCALE_SERVICE_URL=...
```

### Credential Manager

BenchBox includes a credential manager for secure storage:

```bash
# Save credentials (stored securely)
benchbox config credentials set --platform firebolt

# Credentials are automatically loaded when running benchmarks
benchbox run --platform firebolt:cloud --benchmark tpch --scale 1.0
```

### Platform-Specific Notes

| Platform | Auth Method | Notes |
|----------|-------------|-------|
| ClickHouse Cloud | Password | Basic auth over HTTPS |
| Firebolt Cloud | OAuth | Service account credentials |
| MotherDuck | Token | Single token authentication |
| Starburst | Password/API Key | Email/role username format |
| Timescale Cloud | Password | PostgreSQL-style auth with SSL |

---

## Troubleshooting

### Common Errors

**"Invalid deployment mode"**
```
ValueError: Invalid ClickHouse deployment mode 'cluster'. Valid modes: cloud, local, server
```
Solution: Use one of the valid modes for the platform.

**"Missing required credentials"**
```
ValueError: ClickHouse Cloud requires host configuration.
```
Solution: Set the required environment variables or use `--platform-option`.

**"Connection refused"**
```
ConnectionRefusedError: Cannot connect to Firebolt Core at http://localhost:3473
```
Solution: Ensure the local service (Docker container) is running.

### Debug Mode

Enable verbose logging to debug connection issues:

```bash
# Verbose mode
benchbox run --platform clickhouse:cloud --benchmark tpch --scale 0.1 -v

# Very verbose mode (includes connection parameters)
benchbox run --platform clickhouse:cloud --benchmark tpch --scale 0.1 -vv
```

---

## See Also

- [Platform Comparison Matrix](comparison-matrix.md) - Compare all platforms
- [Platform Selection Guide](platform-selection-guide.md) - Choose the right platform
- [ClickHouse Local Mode](clickhouse-local-mode.md) - Detailed chDB guide
- [Firebolt](firebolt.md) - Detailed Firebolt guide
- [Getting Started](../usage/getting-started.md) - Quick start guide
