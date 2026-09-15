# InfluxDB

```{tags} intermediate, guide, influxdb, sql-platform
```

BenchBox supports InfluxDB 3.x for time series benchmarking workloads via FlightSQL.

## Overview

InfluxDB 3.x is a time series database built on the FDAP stack (Apache Arrow, DataFusion, and Parquet). It provides native SQL support through the FlightSQL protocol, making it well-suited for benchmarking time series query performance.

### Key Features

- **Native SQL Support**: Query via FlightSQL protocol (Flux deprecated)
- **Time Series Optimized**: Built for high-cardinality time series data
- **Arrow Data Format**: Native Apache Arrow for efficient data transfer
- **Two Deployment Modes**: Core (OSS) and Cloud (managed service)

### Deployment Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| **Core** | Self-hosted open source | Development, testing, local benchmarking |
| **Cloud** | Managed InfluxDB Cloud service | Production workloads, serverless benchmarking |

## Installation

### Prerequisites

- Python 3.11+
- InfluxDB 3.x server (Core or Cloud)
- Authentication token with read/write permissions

### Install BenchBox with InfluxDB Support

```bash
# Install with InfluxDB extra
uv add benchbox --extra influxdb

# Or with pip
pip install benchbox[influxdb]
```

This installs:
- `influxdb3-python` - Official InfluxDB 3.x Python client
- `pyarrow` - Apache Arrow data handling

### Verify Installation

```python
from benchbox.platforms.influxdb import InfluxDBAdapter, INFLUXDB_AVAILABLE

print(f"InfluxDB support available: {INFLUXDB_AVAILABLE}")
```

## Usage

### CLI Usage

```bash
# InfluxDB Cloud
benchbox run --platform influxdb \
  --benchmark tsbs-devops \
  --influxdb-host us-east-1-1.aws.cloud2.influxdata.com \
  --influxdb-token $INFLUXDB_TOKEN \
  --influxdb-org my-org \
  --influxdb-database benchmarks \
  --influxdb-mode cloud

# InfluxDB Core (local)
benchbox run --platform influxdb \
  --benchmark tsbs-devops \
  --influxdb-host localhost \
  --influxdb-port 8086 \
  --influxdb-token $INFLUXDB_TOKEN \
  --influxdb-database benchmarks \
  --influxdb-mode core \
  --influxdb-ssl false
```

### CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--influxdb-host` | `localhost` | InfluxDB server hostname |
| `--influxdb-port` | `8086` | Server port |
| `--influxdb-token` | - | Authentication token (or set `INFLUXDB_TOKEN` env var) |
| `--influxdb-org` | - | Organization name |
| `--influxdb-database` | `benchbox` | Database (bucket) name |
| `--influxdb-mode` | `cloud` | Deployment mode: `core` or `cloud` |
| `--influxdb-ssl` | `true` | Use SSL/TLS connection |

### Python API

```python
from benchbox.platforms.influxdb import InfluxDBAdapter

# InfluxDB Cloud
adapter = InfluxDBAdapter(
    host="us-east-1-1.aws.cloud2.influxdata.com",
    token="your-token",
    org="your-org",
    database="benchmarks",
    mode="cloud",
)

# InfluxDB Core (local Docker)
adapter = InfluxDBAdapter(
    host="localhost",
    port=8086,
    token="your-token",
    database="benchmarks",
    mode="core",
    ssl=False,
)

# Create connection
connection = adapter.create_connection()

# Execute query
result = connection.execute("SELECT * FROM cpu LIMIT 10")
print(result)

# Close connection
connection.close()
```

## Supported Benchmarks

### TSBS DevOps

The Time Series Benchmark Suite (TSBS) DevOps workload is the primary benchmark for InfluxDB:

```bash
benchbox run --platform influxdb --benchmark tsbs-devops --scale 1
```

TSBS DevOps simulates a DevOps monitoring scenario with:
- **CPU metrics**: Usage, user, system, idle, etc.
- **Memory metrics**: Total, available, used, etc.
- **Disk metrics**: IOPS, throughput, latency
- **Network metrics**: Bytes in/out, packets, errors

### Query Types

| Query Type | Description |
|------------|-------------|
| Single-host | Query metrics for one host over time range |
| Groupby | Aggregate metrics grouped by time buckets |
| Lastpoint | Most recent metric value per host |
| High-CPU | Find hosts with CPU above threshold |
| Double-groupby | Group by multiple dimensions |

## Configuration

### Environment Variables

```bash
# Authentication token (recommended for security)
export INFLUXDB_TOKEN="your-token-here"
```

### Connection Configuration

```python
# Full configuration example
config = {
    "host": "localhost",
    "port": 8086,
    "token": "your-token",
    "org": "your-org",
    "database": "benchmarks",
    "ssl": False,
    "mode": "core",
}

adapter = InfluxDBAdapter.from_config(config)
```

## InfluxDB Core vs Cloud

### InfluxDB Core (Open Source)

```bash
# Start InfluxDB Core with Docker
docker run -d \
  --name influxdb \
  -p 8086:8086 \
  -e DOCKER_INFLUXDB_INIT_MODE=setup \
  -e DOCKER_INFLUXDB_INIT_USERNAME=admin \
  -e DOCKER_INFLUXDB_INIT_PASSWORD=password123 \
  -e DOCKER_INFLUXDB_INIT_ORG=benchbox \
  -e DOCKER_INFLUXDB_INIT_BUCKET=benchmarks \
  -e DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=my-token \
  influxdb:3.0
```

Core limitations:
- No data compaction for historical queries
- No delete capabilities via SQL
- Optimized for "leading edge" (recent) data

### InfluxDB Cloud

1. Sign up at [cloud2.influxdata.com](https://cloud2.influxdata.com)
2. Create a bucket (database)
3. Generate an API token with read/write permissions
4. Use the provided host URL in your configuration

## Performance Considerations

- **Leading Edge Queries**: InfluxDB Core is optimized for recent data queries
- **Time Range Filters**: Always include time bounds for best performance
- **Cardinality**: InfluxDB handles high-cardinality tag values well
- **Aggregations**: Time-bucketed aggregations are highly optimized

## Troubleshooting

### Connection Issues

```python
# Test connection
connection = adapter.create_connection()
if connection.test_connection():
    print("Connection successful")
else:
    print("Connection failed")
```

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `ConnectionError: Failed to connect` | Wrong host/port | Verify server is running and accessible |
| `No InfluxDB client library` | Missing dependency | Run `uv add influxdb3-python` |
| `Authentication failed` | Invalid token | Check token has correct permissions |

### Debug Logging

```python
import logging

logging.getLogger("benchbox.platforms.influxdb").setLevel(logging.DEBUG)
```

## See Also

- [TSBS DevOps Benchmark](../benchmarks/tsbs-devops.md)
- [Platform Comparison](./comparison-matrix.md)
- [InfluxDB Documentation](https://docs.influxdata.com/influxdb3/core/)
