<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Snowflake Platform

```{tags} intermediate, guide, snowflake, cloud-platform
```

Snowflake is a cloud-native data warehouse with automatic scaling, multi-cluster compute, and separation of storage and compute. BenchBox provides comprehensive support for Snowflake benchmarking across all cloud providers (AWS, Azure, GCP).

## Features

- **Auto-scaling compute** - Virtual warehouses scale independently
- **Multi-cluster warehouses** - Concurrent query capacity
- **Zero-copy cloning** - Instant database clones for testing
- **Time travel** - Historical data access
- **Tri-cloud support** - AWS, Azure, and GCP

## Prerequisites

- Snowflake account (trial or paid)
- Virtual warehouse with appropriate size
- Database with CREATE TABLE permissions
- Internal or external stage for data loading

## Installation

```bash
# Install Snowflake connector
pip install snowflake-connector-python

# Or via BenchBox extras
pip install "benchbox[snowflake]"
```

## Configuration

### Environment Variables (Recommended)

```bash
export SNOWFLAKE_ACCOUNT=your_account_identifier
export SNOWFLAKE_USER=your_username
export SNOWFLAKE_PASSWORD=your_password
export SNOWFLAKE_WAREHOUSE=your_warehouse
export SNOWFLAKE_DATABASE=BENCHBOX
export SNOWFLAKE_SCHEMA=PUBLIC
```

### Interactive Setup

```bash
benchbox setup --platform snowflake
```

### CLI Options

```bash
benchbox run --platform snowflake --benchmark tpch --scale 1.0 \
  --platform-option account=your_account \
  --platform-option user=your_user \
  --platform-option password=your_password \
  --platform-option warehouse=COMPUTE_WH \
  --platform-option database=BENCHBOX
```

## Platform Options

| Option | Default | Description |
|--------|---------|-------------|
| `account` | (env) | Snowflake account identifier |
| `user` | (env) | Username for authentication |
| `password` | (env) | Password for authentication |
| `warehouse` | (env) | Virtual warehouse name |
| `database` | (auto) | Database name |
| `schema` | PUBLIC | Schema name |
| `role` | (default) | Snowflake role |
| `stage_name` | (auto) | Stage for data loading |
| `stage_type` | user | Stage type: user, table, external |
| `driver_version` | (latest) | Pin the Snowflake Python connector version (e.g. `3.12.0`) |
| `driver_auto_install` | false | Auto-install the requested driver version via uv if missing |

### Testing a Specific Snowflake Connector Version

```bash
benchbox run --platform snowflake --benchmark tpch \
  --platform-option driver_version=3.12.0 \
  --platform-option driver_auto_install=true \
  --platform-option account=xy12345.us-east-1 \
  --platform-option warehouse=COMPUTE_WH
```

The driver package for Snowflake is `snowflake-connector-python`.

See {ref}`driver-version-management` for the full guide, including why `uv run` may
revert a manually-installed version and how to work around it.

## Authentication Methods

### Password Authentication

```bash
# Basic password auth
benchbox run --platform snowflake --benchmark tpch \
  --platform-option account=xy12345.us-east-1 \
  --platform-option user=benchbox_user \
  --platform-option password=secure_password
```

### Key Pair Authentication

```bash
# Generate key pair
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub

# Upload public key to Snowflake
# ALTER USER benchbox_user SET RSA_PUBLIC_KEY='MII...';

# Use key pair
benchbox run --platform snowflake --benchmark tpch \
  --platform-option account=xy12345.us-east-1 \
  --platform-option user=benchbox_user \
  --platform-option private_key_path=/path/to/rsa_key.p8
```

### SSO/Browser Authentication

```bash
benchbox run --platform snowflake --benchmark tpch \
  --platform-option account=xy12345.us-east-1 \
  --platform-option user=user@company.com \
  --platform-option authenticator=externalbrowser
```

## Usage Examples

### Basic Benchmark

```bash
# TPC-H at scale factor 1 (warehouse comes from stored credentials
# or SNOWFLAKE_WAREHOUSE)
benchbox run --platform snowflake --benchmark tpch --scale 1.0
```

The warehouse is not a `benchbox run` option. Set it once with
`benchbox setup --platform snowflake`, or export `SNOWFLAKE_WAREHOUSE`.

### With Tuning

```bash
# Apply clustering and optimizations
# (export SNOWFLAKE_WAREHOUSE=LARGE_WH first)
benchbox run --platform snowflake --benchmark tpch --scale 10.0 \
  --tuning tuned
```

### Python API

```python
from benchbox import TPCH
from benchbox.platforms.snowflake import SnowflakeAdapter

adapter = SnowflakeAdapter(
    account="xy12345.us-east-1",
    user="benchbox_user",
    password="secure_password",
    warehouse="COMPUTE_WH",
    database="BENCHBOX",
)

benchmark = TPCH(scale_factor=1.0)
benchmark.generate_data()
adapter.load_benchmark(benchmark)
results = adapter.run_benchmark(benchmark)
```

## Warehouse Sizing

| Warehouse Size | Credits/Hour | Recommended Scale |
|----------------|--------------|-------------------|
| X-Small | 1 | SF 0.01-0.1 |
| Small | 2 | SF 0.1-1.0 |
| Medium | 4 | SF 1.0-10.0 |
| Large | 8 | SF 10.0-100.0 |
| X-Large | 16 | SF 100.0+ |

## Performance Features

### Clustering Keys

BenchBox applies clustering keys with `--tuning tuned`:

```sql
ALTER TABLE lineitem CLUSTER BY (l_shipdate);
ALTER TABLE orders CLUSTER BY (o_orderdate);
```

### Result Caching

BenchBox disables result caching for accurate benchmarks:

```sql
ALTER SESSION SET USE_CACHED_RESULT = FALSE;
```

### Query Tagging

Queries are tagged for tracking:

```sql
ALTER SESSION SET QUERY_TAG = 'benchbox:tpch:power:Q1';
```

## Data Loading

### User Stage (Default)

Files uploaded to user stage, then loaded via COPY INTO:

```bash
# Auto-detected, no configuration needed
benchbox run --platform snowflake --benchmark tpch --scale 1.0
```

### External Stage (S3/Azure/GCS)

For large scale factors, use external staging:

```bash
# The cloud --output path becomes the external staging root
benchbox run --platform snowflake --benchmark tpch --scale 100.0 \
  --output s3://bucket/benchbox/ \
  --table-mode external
```

## Cost Optimization

### Auto-Suspend

Configure warehouses to auto-suspend:

```sql
ALTER WAREHOUSE BENCHMARK_WH SET AUTO_SUSPEND = 60;
```

### Multi-Cluster Control

For throughput tests:

```bash
benchbox run --platform snowflake --benchmark tpch --scale 1.0 \
  --phases throughput \
  --platform-option max_cluster_count=4 \
  --platform-option scaling_policy=standard
```

## Troubleshooting

### Authentication Failed

```bash
# Verify account identifier format
# Should be: <account_locator>.<region>.<cloud> or <orgname>-<account_name>
# Examples: xy12345.us-east-1, xy12345.us-east-1.aws, myorg-myaccount

# Test connection
snowsql -a xy12345.us-east-1 -u benchbox_user
```

### Warehouse Not Found

```bash
# List available warehouses
snowsql -q "SHOW WAREHOUSES;"

# Create warehouse if needed
snowsql -q "CREATE WAREHOUSE BENCHMARK_WH WITH WAREHOUSE_SIZE = 'SMALL';"
```

### Insufficient Permissions

```sql
-- Grant required permissions
GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE benchbox_role;
GRANT CREATE DATABASE ON ACCOUNT TO ROLE benchbox_role;
GRANT CREATE SCHEMA ON DATABASE benchbox TO ROLE benchbox_role;
```

### Data Loading Timeout

```bash
# Use a larger warehouse (SNOWFLAKE_WAREHOUSE) or external staging for big datasets
benchbox run --platform snowflake --benchmark tpch --scale 100.0 \
  --output s3://bucket/benchbox/
```

## Related Documentation

- [BigQuery](bigquery.md) - Google Cloud alternative
- [Redshift](redshift.md) - AWS native warehouse
- [Databricks](databricks.md) - Lakehouse alternative
- [Platform Comparison](comparison-matrix.md)
