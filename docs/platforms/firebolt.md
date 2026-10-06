<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Firebolt Platform

```{tags} intermediate, guide, firebolt, sql-platform
```

Firebolt is a high-performance cloud analytics database with a vectorized query engine optimized for sub-second analytics. BenchBox supports both Firebolt Core (local) and Firebolt Cloud deployments.

## Features

- **Vectorized execution** - SIMD-optimized query processing
- **Two deployment modes** - Local (Core) and Cloud
- **PostgreSQL-compatible** - Familiar SQL dialect
- **Sparse indexes** - Efficient data skipping
- **Same engine everywhere** - Core and Cloud use identical engine

## Deployment Modes

Firebolt supports two deployment modes, selectable via the colon syntax:

```bash
# Firebolt Core (local Docker, default)
benchbox run --platform firebolt:core --benchmark tpch --scale 0.1

# Firebolt Cloud (managed service)
benchbox run --platform firebolt:cloud --benchmark tpch --scale 1.0
```

### Firebolt Core (Local)

Free, self-hosted version running in Docker with the same query engine as cloud:

```bash
# Start Firebolt Core
docker run -i --rm \
  --ulimit memlock=8589934592:8589934592 \
  --security-opt seccomp=unconfined \
  -p 127.0.0.1:3473:3473 \
  -v ./firebolt-data:/firebolt-core/volume \
  ghcr.io/firebolt-db/firebolt-core:preview-rc
```

**Characteristics:**
- No authentication required
- Databases created implicitly on connection
- Same vectorized query engine as cloud
- Ideal for development and testing

### Firebolt Cloud

Managed cloud service requiring OAuth authentication:
- Sign up at [firebolt.io](https://www.firebolt.io)
- Create service account credentials in Settings > Service Accounts
- Configure engine and database

## Installation

```bash
# Install Firebolt SDK
pip install firebolt-sdk

# Or via BenchBox extras
pip install "benchbox[firebolt]"
```

## Configuration

### Firebolt Core (Local)

```bash
benchbox run --platform firebolt --benchmark tpch --scale 0.1 \
  --platform-option url=http://localhost:3473 \
  --platform-option database=benchbox
```

### Firebolt Cloud

```bash
# Environment variables (recommended)
export FIREBOLT_CLIENT_ID=your_client_id
export FIREBOLT_CLIENT_SECRET=your_client_secret
export FIREBOLT_ACCOUNT_NAME=your_account_name
export FIREBOLT_ENGINE_NAME=your_engine_name

# Alternative environment variable names (also supported)
export SERVICE_ACCOUNT_ID=your_client_id
export SERVICE_ACCOUNT_SECRET=your_client_secret

# Run with deployment mode syntax
benchbox run --platform firebolt:cloud --benchmark tpch --scale 1.0

# Or with inline CLI options
benchbox run --platform firebolt:cloud --benchmark tpch --scale 1.0 \
  --platform-option client_id=$FIREBOLT_CLIENT_ID \
  --platform-option client_secret=$FIREBOLT_CLIENT_SECRET \
  --platform-option account_name=your_account \
  --platform-option engine_name=your_engine \
  --platform-option database=benchmarks
```

### Platform Options

| Option | Default | Description |
|--------|---------|-------------|
| `url` | (none) | Firebolt Core URL (triggers Core mode) |
| `client_id` | (none) | Cloud OAuth client ID |
| `client_secret` | (none) | Cloud OAuth client secret |
| `account_name` | (none) | Firebolt Cloud account |
| `engine_name` | (none) | Cloud engine name |
| `database` | (auto) | Database name |
| `api_endpoint` | api.firebolt.io | API endpoint for Cloud |

## Usage Examples

### Firebolt Core

```bash
# Start Core container first
docker run -d -p 127.0.0.1:3473:3473 ghcr.io/firebolt-db/firebolt-core:preview-rc

# Run benchmark
benchbox run --platform firebolt --benchmark tpch --scale 0.1 \
  --platform-option url=http://localhost:3473
```

### Python API (Core)

```python
from benchbox import TPCH
from benchbox.platforms.firebolt import FireboltAdapter

# Firebolt Core adapter
adapter = FireboltAdapter(
    url="http://localhost:3473",
    database="benchbox",
)

# Load and run benchmark
benchmark = TPCH(scale_factor=0.1)
benchmark.generate_data()
adapter.load_benchmark(benchmark)
results = adapter.run_benchmark(benchmark)
```

### Python API (Cloud)

```python
from benchbox import TPCH
from benchbox.platforms.firebolt import FireboltAdapter

# Firebolt Cloud adapter
adapter = FireboltAdapter(
    client_id="your_client_id",
    client_secret="your_client_secret",
    account_name="your_account",
    engine_name="benchmark_engine",
    database="benchmarks",
)

# Load and run benchmark
benchmark = TPCH(scale_factor=1.0)
adapter.load_benchmark(benchmark)
results = adapter.run_benchmark(benchmark)
```

## Performance Features

### Sparse Indexes

Firebolt automatically creates sparse indexes for efficient data skipping:

```sql
-- Create table with primary index
CREATE TABLE lineitem (
    l_orderkey BIGINT,
    l_partkey BIGINT,
    ...
) PRIMARY INDEX (l_orderkey, l_partkey);
```

### Aggregating Indexes

For pre-aggregated analytics:

```sql
CREATE AGGREGATING INDEX agg_revenue ON lineitem (
    l_returnflag,
    SUM(l_extendedprice),
    COUNT(*)
);
```

## Firebolt Core vs Cloud

| Aspect | Core | Cloud |
|--------|------|-------|
| Cost | Free | Pay-per-use |
| Setup | Docker | Managed |
| Auth | None | OAuth |
| Scaling | Single node | Multi-node |
| Best for | Development | Production |

## Benchmark Recommendations

### Development (Core)

```bash
# Quick local testing
benchbox run --platform firebolt --benchmark tpch --scale 0.1 \
  --platform-option url=http://localhost:3473
```

### Production (Cloud)

```bash
# Production benchmark
benchbox run --platform firebolt --benchmark tpch --scale 10.0 \
  --platform-option engine_name=large_engine \
  --tuning tuned
```

## Troubleshooting

### Core Connection Refused

```bash
# Verify container is running
docker ps | grep firebolt

# Check logs
docker logs <container_id>

# Test connection
curl http://localhost:3473/health
```

### Cloud Authentication Failed

```bash
# Verify credentials
curl -X POST "https://api.firebolt.io/oauth/token" \
  -d "client_id=$FIREBOLT_CLIENT_ID" \
  -d "client_secret=$FIREBOLT_CLIENT_SECRET" \
  -d "grant_type=client_credentials"
```

### Engine Not Running

```bash
# Start engine via API or console
# Engines auto-stop after inactivity
```

## Related Documentation

- [ClickHouse Local Mode](clickhouse-local-mode.md) - Alternative local analytics
- [DuckDB](../usage/getting-started.md) - Embedded analytics
- [Platform Selection Guide](platform-selection-guide.md)
