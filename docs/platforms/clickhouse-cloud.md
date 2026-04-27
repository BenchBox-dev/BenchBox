<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# ClickHouse Cloud Platform

```{tags} intermediate, guide, clickhouse, sql-platform, cloud
```

ClickHouse Cloud is the managed cloud version of ClickHouse, providing serverless and dedicated compute options with automatic scaling. BenchBox provides first-class ClickHouse Cloud support, inheriting ClickHouse's SQL dialect and benchmark compatibility.

## Features

- **Managed ClickHouse** - No infrastructure management
- **ClickHouse dialect** - Inherits SQL dialect from ClickHouse
- **HTTPS connectivity** - Secure connection via port 8443
- **Serverless & dedicated** - Flexible compute options
- **Auto-scaling** - Automatic resource management
- **Compression** - Network-efficient data transfer

## Quick Start

```bash
# Install ClickHouse Cloud extra
uv add benchbox --extra clickhouse-cloud

# Set your credentials
export CLICKHOUSE_CLOUD_HOST=abc123.us-east-2.aws.clickhouse.cloud
export CLICKHOUSE_CLOUD_PASSWORD=your-password

# Run benchmark
benchbox run --platform clickhouse-cloud --benchmark tpch --scale 1.0
```

## Authentication

### Getting Your Credentials

1. Sign in to [clickhouse.cloud](https://clickhouse.cloud)
2. Navigate to your service
3. Click "Connect" to get your connection details:
   - **Host**: `abc123.us-east-2.aws.clickhouse.cloud`
   - **Port**: `8443` (HTTPS)
   - **Username**: Usually `default`
   - **Password**: Your service password

### Configuration

**Environment Variables (recommended):**

```bash
export CLICKHOUSE_CLOUD_HOST=abc123.us-east-2.aws.clickhouse.cloud
export CLICKHOUSE_CLOUD_PASSWORD=your-password
export CLICKHOUSE_CLOUD_USER=default  # optional, defaults to 'default'

benchbox run --platform clickhouse-cloud --benchmark tpch --scale 1.0
```

**CLI Options:**

```bash
benchbox run --platform clickhouse-cloud --benchmark tpch --scale 1.0 \
    --platform-option host=abc123.us-east-2.aws.clickhouse.cloud \
    --platform-option password=your-password \
    --platform-option username=default
```

## Configuration Options

| Option | Environment Variable | Default | Description |
|--------|---------------------|---------|-------------|
| `host` | `CLICKHOUSE_CLOUD_HOST` | - | Cloud hostname (required) |
| `password` | `CLICKHOUSE_CLOUD_PASSWORD` | - | Authentication password (required) |
| `username` | `CLICKHOUSE_CLOUD_USER` | `default` | Username |
| `database` | - | `default` | Target database |
| `max_memory_usage` | - | - | Max memory per query (bytes) |
| `max_execution_time` | - | - | Query timeout (seconds) |
| `disable_result_cache` | - | `true` | Disable result cache for benchmarking |
| `compression` | - | `true` | Enable network compression |
| `driver_version` | - | (latest) | Pin the clickhouse-connect package version (e.g. `0.10.0`) |
| `driver_auto_install` | - | false | Auto-install the requested driver version via uv if missing |

### Testing a Specific clickhouse-connect Version

```bash
benchbox run --platform clickhouse-cloud --benchmark tpch \
  --platform-option driver_version=0.10.0 \
  --platform-option driver_auto_install=true \
  --platform-option host=your-instance.clickhouse.cloud \
  --platform-option password=your-password
```

The driver package for ClickHouse Cloud is `clickhouse-connect` (the HTTP-based connector).
This is distinct from the `[clickhouse]` extra which uses `clickhouse-driver` (the TCP binary protocol).

See {ref}`driver-version-management` for the full guide, including why `uv run` may
revert a manually-installed version and how to work around it.

## Usage Examples

### Basic Benchmark

```bash
# TPC-H at scale factor 1
benchbox run --platform clickhouse-cloud --benchmark tpch --scale 1.0

# TPC-DS at scale factor 10
benchbox run --platform clickhouse-cloud --benchmark tpcds --scale 10.0

# ClickBench (ClickHouse's own benchmark)
benchbox run --platform clickhouse-cloud --benchmark clickbench
```

### Custom Database Name

```bash
benchbox run --platform clickhouse-cloud --benchmark tpch --scale 1.0 \
    --platform-option database=my_benchmarks
```

### Performance Tuning

```bash
# Increase memory limit for complex queries
benchbox run --platform clickhouse-cloud --benchmark tpcds --scale 100 \
    --platform-option max_memory_usage=16000000000

# Set query timeout
benchbox run --platform clickhouse-cloud --benchmark tpch --scale 10 \
    --platform-option max_execution_time=300
```

### Dry Run (Preview)

```bash
# Preview what will be executed without running
benchbox run --platform clickhouse-cloud --benchmark tpch --scale 1.0 --dry-run ./preview
```

## Comparison with Base ClickHouse

| Feature | ClickHouse (local) | ClickHouse (server) | ClickHouse Cloud |
|---------|-------------------|---------------------|------------------|
| **CLI Name** | `clickhouse-local` | `clickhouse-server` | `clickhouse-cloud` |
| **Infrastructure** | None (chDB) | Self-hosted | Managed |
| **Driver** | chdb | clickhouse-driver | clickhouse-connect |
| **Port** | N/A | 9000 (native) | 8443 (HTTPS) |
| **Authentication** | None | Optional | Required |
| **Best For** | Development | Production self-hosted | Production cloud |

## Platform Syntax

The canonical platform name is `clickhouse-cloud`. The `clickhouse:cloud` syntax is also accepted as an alias.

```bash
benchbox run --platform clickhouse-cloud --benchmark tpch --scale 1.0
```

## Troubleshooting

### Connection Refused

```
Error: Cannot connect to ClickHouse Cloud
```

**Solutions:**
1. Verify your host URL is correct (should end with `.clickhouse.cloud`)
2. Check that your IP is allowed in the ClickHouse Cloud console
3. Ensure the service is running (not paused)

### Authentication Failed

```
Error: Authentication failed for user 'default'
```

**Solutions:**
1. Verify your password is correct
2. Check if the user has the required permissions
3. Try resetting the password in the ClickHouse Cloud console

### Missing Host Configuration

```
Error: ClickHouse Cloud requires host configuration.
```

**Solutions:**
1. Set `CLICKHOUSE_CLOUD_HOST` environment variable
2. Or use `--platform-option host=your-host.clickhouse.cloud`

## Platform Information

At runtime, BenchBox captures platform metadata:

```python
{
    "platform_type": "clickhouse-cloud",
    "platform_name": "ClickHouse Cloud",
    "connection_mode": "cloud",
    "configuration": {
        "deployment": "managed",
        "host": "abc123.us-east-2.aws.clickhouse.cloud",
        "port": 8443,
        "secure": True
    }
}
```

## See Also

- [ClickHouse Local Mode](clickhouse-local-mode.md) - Embedded ClickHouse via chDB
- [Deployment Modes Guide](deployment-modes.md) - Platform deployment architecture
- [Platform Comparison Matrix](comparison-matrix.md) - Compare all platforms
- [TPC-H Benchmark](../benchmarks/tpch.md) - TPC-H benchmark guide
