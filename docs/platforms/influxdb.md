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
uv add benchbox --extra influxdb

pip install benchbox[influxdb]
```

The first command installs the `influxdb` extra with uv. The second does the same with pip.

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
benchbox run --platform influxdb \
  --benchmark tsbs-devops \
  --platform-option host=us-east-1-1.aws.cloud2.influxdata.com \
  --platform-option token=$INFLUXDB_TOKEN \
  --platform-option org=my-org \
  --platform-option database=benchmarks \
  --platform-option mode=cloud

benchbox run --platform influxdb \
  --benchmark tsbs-devops \
  --platform-option host=localhost \
  --platform-option port=8086 \
  --platform-option token=$INFLUXDB_TOKEN \
  --platform-option database=benchmarks \
  --platform-option mode=core
```

The first command targets InfluxDB Cloud. The second targets a local InfluxDB Core server. All options are passed as `--platform-option KEY=VALUE`.

### CLI Arguments

| Option key | Default | Description |
|------------|---------|-------------|
| `host` | `localhost` | InfluxDB server hostname |
| `port` | `8086` | Server port |
| `token` | - | Authentication token (or set `INFLUXDB_TOKEN` env var) |
| `org` | - | Organization name |
| `database` | `benchbox` | Database (bucket) name |
| `mode` | `cloud` | Deployment mode: `core` or `cloud` |
| `ssl` | `true` | Use SSL/TLS connection. The CLI passes option values as strings, so disabling SSL from the CLI is not supported; use the Python API with `ssl=False` for plaintext local servers (see below) |

### Python API

```python
from benchbox.platforms.influxdb import InfluxDBAdapter

adapter = InfluxDBAdapter(
    host="us-east-1-1.aws.cloud2.influxdata.com",
    token="your-token",
    org="your-org",
    database="benchmarks",
    mode="cloud",
)

adapter = InfluxDBAdapter(
    host="localhost",
    port=8086,
    token="your-token",
    database="benchmarks",
    mode="core",
    ssl=False,
)

connection = adapter.create_connection()

result = connection.execute("SELECT * FROM cpu LIMIT 10")
print(result)

connection.close()
```

The first adapter targets InfluxDB Cloud. The second targets InfluxDB Core running locally in Docker. The remaining lines create a connection, execute a query, and close the connection.

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
export INFLUXDB_TOKEN="your-token-here"
```

Setting the authentication token in the environment is recommended for security.

### Connection Configuration

```python
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

This is a full configuration example.

## InfluxDB Core vs Cloud

### InfluxDB Core (Open Source)

```bash
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

This starts InfluxDB Core with Docker.

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
connection = adapter.create_connection()
if connection.test_connection():
    print("Connection successful")
else:
    print("Connection failed")
```

This tests the connection.

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
