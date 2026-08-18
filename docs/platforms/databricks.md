<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Databricks Platform

```{tags} intermediate, guide, databricks, cloud-platform
```

Databricks provides a unified lakehouse platform combining data lakes with warehouse capabilities. BenchBox supports Databricks SQL Warehouses and classic clusters with Delta Lake optimizations.

## Features

- **Multi-format support** - Delta Lake (native), Apache Iceberg, Apache Hudi
- **Unity Catalog** - Unified governance and security
- **Photon engine** - Vectorized query execution
- **Auto-scaling** - Dynamic cluster management
- **Multi-cloud** - AWS, Azure, and GCP support

## Prerequisites

- Databricks workspace (AWS, Azure, or GCP)
- SQL Warehouse or All-Purpose Cluster
- Personal Access Token or OAuth credentials
- Unity Catalog (recommended) or Hive Metastore

## Installation

```bash
# Install Databricks SQL connector
pip install databricks-sql-connector databricks-sdk

# Or via BenchBox extras
pip install "benchbox[databricks]"
```

## Configuration

### Environment Variables (Recommended)

```bash
export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
export DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/abc123def456
export DATABRICKS_TOKEN=dapi1234567890abcdef
```

### Interactive Setup

```bash
benchbox setup --platform databricks
```

### CLI Options

```bash
benchbox run --platform databricks --benchmark tpch --scale 1.0 \
  --platform-option server_hostname=your-workspace.cloud.databricks.com \
  --platform-option http_path=/sql/1.0/warehouses/abc123def456 \
  --platform-option access_token=dapi1234...
```

## Platform Options

| Option | Default | Description |
|--------|---------|-------------|
| `server_hostname` | (env) | Workspace URL |
| `http_path` | (env) | SQL Warehouse or cluster path |
| `access_token` | (env) | Personal Access Token |
| `catalog` | (default) | Unity Catalog name |
| `schema` | (auto) | Schema name |
| `use_volumes` | true | Use UC Volumes for staging |
| `volume_path` | (auto) | Path within volume |
| `driver_version` | (latest) | Pin the Databricks SQL connector version (e.g. `3.3.0`) |
| `driver_auto_install` | false | Auto-install the requested driver version via uv if missing |

### Testing a Specific Databricks Connector Version

```bash
benchbox run --platform databricks --benchmark tpch \
  --platform-option driver_version=3.3.0 \
  --platform-option driver_auto_install=true \
  --platform-option warehouse_id=abc123xyz
```

The driver package for Databricks is `databricks-sql-connector`.

See {ref}`driver-version-management` for the full guide, including why `uv run` may
revert a manually-installed version and how to work around it.

## Authentication Methods

### Personal Access Token

```bash
# Generate token: User Settings > Developer > Access Tokens
export DATABRICKS_TOKEN=dapi1234567890abcdef

benchbox run --platform databricks --benchmark tpch --scale 1.0
```

### OAuth (M2M)

```bash
# Service principal authentication
export DATABRICKS_CLIENT_ID=your_client_id
export DATABRICKS_CLIENT_SECRET=your_client_secret

benchbox run --platform databricks --benchmark tpch \
  --platform-option auth_type=oauth-m2m
```

### Azure AD (Azure Databricks)

```bash
# Azure Active Directory token
export ARM_CLIENT_ID=your_client_id
export ARM_CLIENT_SECRET=your_client_secret
export ARM_TENANT_ID=your_tenant_id

benchbox run --platform databricks --benchmark tpch \
  --platform-option auth_type=azure-ad
```

## Usage Examples

### Basic Benchmark

```bash
# TPC-H on SQL Warehouse
benchbox run --platform databricks --benchmark tpch --scale 1.0
```

### With Unity Catalog

```bash
# Specify catalog and schema
benchbox run --platform databricks --benchmark tpch --scale 10.0 \
  --platform-option catalog=benchmarks \
  --platform-option schema=tpch_sf10
```

### With Tuning

```bash
# Apply Delta Lake optimizations
benchbox run --platform databricks --benchmark tpch --scale 10.0 \
  --tuning tuned
```

### Python API

```python
from benchbox import TPCH
from benchbox.platforms.databricks import DatabricksAdapter

adapter = DatabricksAdapter(
    server_hostname="your-workspace.cloud.databricks.com",
    http_path="/sql/1.0/warehouses/abc123def456",
    access_token="dapi1234567890abcdef",
    catalog="benchmarks",
)

benchmark = TPCH(scale_factor=1.0)
benchmark.generate_data()
adapter.load_benchmark(benchmark)
results = adapter.run_benchmark(benchmark)
```

## SQL Warehouse Sizing

| Size | DBU/Hour | Recommended Scale |
|------|----------|-------------------|
| 2X-Small | 2 | SF 0.01-0.1 |
| X-Small | 4 | SF 0.1-1.0 |
| Small | 8 | SF 1.0-10.0 |
| Medium | 16 | SF 10.0-100.0 |
| Large | 32 | SF 100.0+ |

## Performance Features

### Delta Lake Optimizations

BenchBox applies Delta optimizations with `--tuning tuned`:

```sql
-- Optimize file layout
OPTIMIZE lineitem ZORDER BY (l_shipdate);

-- Clustering (liquid clustering)
ALTER TABLE lineitem CLUSTER BY (l_shipdate, l_orderkey);

-- Vacuum old versions
VACUUM lineitem RETAIN 0 HOURS;
```

### Photon Acceleration

Photon is automatically enabled on SQL Warehouses:

```bash
# Verify Photon is enabled
benchbox run --platform databricks --benchmark tpch --scale 1.0 \
  --platform-option check_photon=true
```

### Query Caching

BenchBox disables caching for accurate benchmarks by using unique query tags.

## Data Loading

### Unity Catalog Volumes (Default)

Data uploaded to managed volumes, then loaded via COPY INTO:

```bash
# Automatic with UC enabled
benchbox run --platform databricks --benchmark tpch --scale 1.0
```

### External Location (S3/ADLS/GCS)

For large datasets, use external cloud storage:

```bash
# Configure external staging
benchbox run --platform databricks --benchmark tpch --scale 100.0 \
  --output s3://bucket/benchbox/
```

### DBFS (Legacy)

For workspaces without Unity Catalog:

```bash
benchbox run --platform databricks --benchmark tpch --scale 1.0 \
  --platform-option use_volumes=false \
  --platform-option dbfs_path=/tmp/benchbox/
```

## Cost Optimization

### Auto-Stop

Configure warehouses to auto-stop:

```sql
-- Set via UI or API
-- Warehouse Settings > Auto Stop > 10 minutes
```

### Serverless Warehouses

For variable workloads:

```bash
benchbox run --platform databricks --benchmark tpch \
  --platform-option http_path=/sql/1.0/warehouses/serverless_wh
```

## Troubleshooting

### Authentication Failed

```bash
# Verify token is valid
curl -H "Authorization: Bearer $DATABRICKS_TOKEN" \
  https://your-workspace.cloud.databricks.com/api/2.0/clusters/list

# Check token expiration
# Tokens expire after 90 days by default
```

### SQL Warehouse Not Found

```bash
# List warehouses via API
curl -H "Authorization: Bearer $DATABRICKS_TOKEN" \
  https://your-workspace.cloud.databricks.com/api/2.0/sql/warehouses

# Verify http_path format
# SQL Warehouse: /sql/1.0/warehouses/<warehouse_id>
# Cluster: /sql/protocolv1/o/<org_id>/<cluster_id>
```

### Unity Catalog Access Denied

```sql
-- Grant catalog access
GRANT USE CATALOG ON CATALOG benchmarks TO `user@company.com`;
GRANT CREATE SCHEMA ON CATALOG benchmarks TO `user@company.com`;
```

### Volume Upload Failed

```bash
# Verify volume exists and has write access
# Create volume if needed (SQL Warehouse)
CREATE VOLUME IF NOT EXISTS benchmarks.staging.uploads;

# Grant permissions
GRANT WRITE VOLUME ON VOLUME benchmarks.staging.uploads TO `user@company.com`;
```

## Related Documentation

- [Snowflake](snowflake.md) - Cloud warehouse alternative
- [BigQuery](bigquery.md) - Google Cloud alternative
- [Spark](spark.md) - Open-source Spark
- [Platform Comparison](comparison-matrix.md)
