<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Trino Platform

```{tags} intermediate, guide, trino, sql-platform
```

Trino (formerly PrestoSQL) is a distributed SQL query engine designed for interactive analytics against data sources of all sizes. It's widely used by companies like Netflix, Airbnb, and Lyft for data lake analytics.

## Features

- **Distributed execution** - Query data across multiple workers
- **Federated queries** - Join data from multiple sources (S3, Hive, Iceberg, Delta)
- **Session properties** - Fine-grained query optimization
- **Table formats** - Support for Iceberg, Delta Lake, and Hive
- **Starburst compatible** - Works with Starburst Enterprise

## Important Notes

**Trino vs PrestoDB**: This adapter supports Trino only, NOT PrestoDB (Meta's fork). While they share ancestry, they have diverged significantly since 2019:

- Different Python drivers (`trino` vs `presto-python-client`)
- Different HTTP headers (`X-Trino-*` vs `X-Presto-*`)
- Diverging SQL syntax and functions

For PrestoDB, use the [Presto adapter](presto.md). For AWS managed Trino, use the [Athena adapter](athena.md).

## Installation

```bash
# Install Trino Python driver
pip install trino

# Or install with authentication support
pip install "trino[kerberos]"
```

## Configuration

### Environment Variables

```bash
export TRINO_HOST=localhost
export TRINO_PORT=8080
export TRINO_USER=trino
export TRINO_CATALOG=memory
export TRINO_SCHEMA=default
```

### CLI Options

```bash
benchbox run --platform trino --benchmark tpch --scale 1.0 \
  --platform-option host=trino-coordinator.example.com \
  --platform-option port=8080 \
  --platform-option catalog=hive \
  --platform-option schema=benchmark
```

### Platform Options

| Option | Default | Description |
|--------|---------|-------------|
| `host` | localhost | Trino coordinator hostname |
| `port` | 8080 | Trino coordinator port |
| `catalog` | memory | Default catalog (hive, iceberg, delta, memory) |
| `schema` | default | Default schema |
| `username` | trino | Trino user for query attribution |
| `password` | (none) | Password for LDAP/basic auth |
| `http_scheme` | http/https | Auto-detected based on auth |
| `verify_ssl` | true | Verify SSL certificates |
| `staging_root` | (none) | S3/GCS path for data staging |
| `table_format` | hive | Table format (hive, iceberg, delta) |
| `driver_version` | (latest) | Pin the trino package version (e.g. `0.336.0`) |
| `driver_auto_install` | false | Auto-install the requested driver version via uv if missing |

### Testing a Specific Trino Connector Version

```bash
benchbox run --platform trino --benchmark tpch \
  --platform-option driver_version=0.336.0 \
  --platform-option driver_auto_install=true \
  --platform-option host=trino.example.com \
  --platform-option catalog=hive
```

The driver package for Trino is `trino`.

See {ref}`driver-version-management` for the full guide, including why `uv run` may
revert a manually-installed version and how to work around it.

## Usage Examples

### Basic Benchmark Run

```bash
# Run TPC-H with Hive catalog
benchbox run --platform trino --benchmark tpch --scale 1.0 \
  --platform-option host=trino.example.com \
  --platform-option catalog=hive \
  --platform-option schema=tpch_sf1
```

### Iceberg Tables

```bash
# Run with Iceberg table format
benchbox run --platform trino --benchmark tpch --scale 1.0 \
  --platform-option catalog=iceberg \
  --platform-option table_format=iceberg \
  --platform-option staging_root=s3://bucket/staging/
```

### Python API

```python
from benchbox import TPCH
from benchbox.platforms.trino import TrinoAdapter

# Initialize adapter
adapter = TrinoAdapter(
    host="trino-coordinator.example.com",
    port=8080,
    catalog="hive",
    schema="benchmark",
    username="analyst",
)

# Load and run benchmark
benchmark = TPCH(scale_factor=1.0)
adapter.load_benchmark(benchmark)
results = adapter.run_benchmark(benchmark)
```

## Deployment Modes

### Local Development (Memory Catalog)

```bash
# Start Trino locally (Docker)
docker run -d -p 8080:8080 --name trino trinodb/trino

# Run benchmark with memory catalog
benchbox run --platform trino --benchmark tpch --scale 0.1 \
  --platform-option catalog=memory
```

If you installed Trino via Homebrew, you can start the service with:

```bash
brew install trino
brew services start trino
# or run it manually
trino-server run
```

BenchBox automatically detects when `localhost:8080` refuses connections and
emits a friendly error explaining that Trino needs to be started (including the
`brew services start trino` reminder) or that you should point BenchBox at a
remote Trino cluster via `--platform-option host=<host> --platform-option port=<port>`.

### Production (Hive/Iceberg)

```bash
# Run with Hive Metastore
benchbox run --platform trino --benchmark tpch --scale 10.0 \
  --platform-option host=trino.production.com \
  --platform-option catalog=hive \
  --platform-option staging_root=s3://data-lake/staging/
```

### Starburst Enterprise

The Trino adapter is fully compatible with Starburst Enterprise:

```bash
benchbox run --platform trino --benchmark tpch \
  --platform-option host=starburst.example.com \
  --platform-option http_scheme=https \
  --platform-option verify_ssl=true
```

## Performance Tuning

### Session Properties

Common session properties for optimization:

```python
adapter = TrinoAdapter(
    host="trino.example.com",
    session_properties={
        "query_max_memory": "8GB",
        "query_max_memory_per_node": "2GB",
        "join_distribution_type": "AUTOMATIC",
    }
)
```

### Data Format Recommendations

- **Parquet**: Best compression and performance for analytics
- **ORC**: Good alternative with predicate pushdown
- **Iceberg**: Recommended for updates and time-travel

## Query Plan Analysis

```bash
benchbox run --platform trino --benchmark tpch \
  --capture-plans
```

Trino provides detailed EXPLAIN output including:
- Distributed query plan fragments
- Data exchange patterns
- Join strategies
- Partition pruning

## Limitations

- **No local execution** - Requires Trino cluster
- **Infrastructure overhead** - Coordinator and workers needed
- **Cold start** - First queries may be slower

## Troubleshooting

### Connection Timeout

```bash
# Verify Trino is accessible
curl http://trino-host:8080/v1/info
```

### Catalog Not Found

```bash
# List available catalogs
trino --server trino-host:8080 --execute "SHOW CATALOGS"
```

### Memory Errors

```sql
-- Check memory usage
SELECT * FROM system.runtime.queries WHERE state = 'RUNNING';
```

## Related Documentation

- [Presto Platform](presto.md) - For PrestoDB (Meta fork)
- [Athena Platform](athena.md) - AWS managed Trino service
- [Spark Platform](spark.md) - Alternative distributed engine
