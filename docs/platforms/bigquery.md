<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# BigQuery Platform

```{tags} intermediate, guide, bigquery, cloud-platform
```

Google BigQuery is a serverless, highly scalable data warehouse with built-in machine learning and real-time analytics. BenchBox provides full support for BigQuery benchmarking with optimized data loading via Cloud Storage.

## Features

- **Serverless** - No infrastructure to manage
- **Separation of storage and compute** - Pay for what you use
- **Standard SQL** - ANSI SQL compliant
- **Columnar storage** - Capacitor format with automatic compression
- **Slot-based pricing** - On-demand or reserved capacity

## Prerequisites

- Google Cloud project with BigQuery API enabled
- Service account or user credentials with BigQuery permissions
- Cloud Storage bucket for data staging (recommended for large datasets)
- Billing enabled on the project

## Installation

```bash
# Install BigQuery client
pip install google-cloud-bigquery google-cloud-storage

# Or via BenchBox extras
pip install "benchbox[bigquery]"
```

## Configuration

### Service Account (Recommended)

```bash
# Set credentials path
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
export BIGQUERY_PROJECT=your-project-id
```

### Application Default Credentials

```bash
# Login with gcloud
gcloud auth application-default login

# Set project
export BIGQUERY_PROJECT=your-project-id
```

### Interactive Setup

```bash
benchbox setup --platform bigquery
```

### CLI Options

```bash
benchbox run --platform bigquery --benchmark tpch --scale 1.0 \
  --platform-option project_id=your-project-id \
  --platform-option dataset=benchbox \
  --platform-option location=US
```

## Platform Options

| Option | Default | Description |
|--------|---------|-------------|
| `project_id` | (env) | GCP project ID |
| `dataset` | (auto) | BigQuery dataset name |
| `location` | US | Data location (US, EU, etc.) |
| `credentials_path` | (env) | Service account JSON path |
| `staging_bucket` | (none) | GCS bucket for staging |
| `maximum_bytes_billed` | (none) | Query cost limit |
| `driver_version` | (latest) | Pin the google-cloud-bigquery package version (e.g. `3.0.0`) |
| `driver_auto_install` | false | Auto-install the requested driver version via uv if missing |

### Testing a Specific BigQuery Connector Version

```bash
benchbox run --platform bigquery --benchmark tpch \
  --platform-option driver_version=3.0.0 \
  --platform-option driver_auto_install=true \
  --platform-option project_id=your-gcp-project
```

The driver package for BigQuery is `google-cloud-bigquery`.

See {ref}`driver-version-management` for the full guide, including why `uv run` may
revert a manually-installed version and how to work around it.

## Authentication Methods

### Service Account

```bash
# Create service account
gcloud iam service-accounts create benchbox-sa \
  --display-name="BenchBox Service Account"

# Grant permissions
gcloud projects add-iam-policy-binding your-project \
  --member="serviceAccount:benchbox-sa@your-project.iam.gserviceaccount.com" \
  --role="roles/bigquery.admin"

# Create key
gcloud iam service-accounts keys create benchbox-key.json \
  --iam-account=benchbox-sa@your-project.iam.gserviceaccount.com

# Set credentials
export GOOGLE_APPLICATION_CREDENTIALS=benchbox-key.json
```

### User Credentials

```bash
# Interactive login
gcloud auth application-default login

# Set project
gcloud config set project your-project-id
```

### Workload Identity (GKE)

```bash
# Use with Workload Identity Federation
benchbox run --platform bigquery --benchmark tpch \
  --platform-option use_workload_identity=true
```

## Usage Examples

### Basic Benchmark

```bash
# TPC-H at scale factor 1
benchbox run --platform bigquery --benchmark tpch --scale 1.0 \
  --platform-option project_id=your-project-id
```

### With Cloud Storage Staging

```bash
# For large datasets, use GCS staging
benchbox run --platform bigquery --benchmark tpch --scale 100.0 \
  --output gs://your-bucket/benchbox/
```

### With Cost Controls

```bash
# Limit query costs
benchbox run --platform bigquery --benchmark tpch --scale 10.0 \
  --platform-option maximum_bytes_billed=10000000000  # 10GB limit
```

### Python API

```python
from benchbox import TPCH
from benchbox.platforms.bigquery import BigQueryAdapter

adapter = BigQueryAdapter(
    project_id="your-project-id",
    dataset="benchbox",
    location="US",
)

benchmark = TPCH(scale_factor=1.0)
benchmark.generate_data()
adapter.load_benchmark(benchmark)
results = adapter.run_benchmark(benchmark)
```

## Pricing

### On-Demand Pricing

| Operation | Cost |
|-----------|------|
| Queries | $5 per TB scanned |
| Storage | $0.02 per GB/month |
| Streaming inserts | $0.01 per 200MB |

### Slot Reservations

For predictable costs, use slot reservations:

```bash
# Use with reserved slots
benchbox run --platform bigquery --benchmark tpch \
  --platform-option reservation_id=projects/proj/locations/US/reservations/benchbox
```

## Performance Features

### Partitioning

BenchBox applies partitioning with `--tuning tuned`:

```sql
-- Date partitioning
CREATE TABLE lineitem
PARTITION BY DATE(l_shipdate)
CLUSTER BY l_orderkey
AS SELECT * FROM staging.lineitem;
```

### Clustering

Clustering improves query performance:

```sql
-- Clustering keys
ALTER TABLE lineitem
CLUSTER BY l_shipdate, l_orderkey;
```

### Query Caching

BenchBox disables caching for accurate benchmarks:

```python
job_config = bigquery.QueryJobConfig(
    use_query_cache=False,
    use_legacy_sql=False,
)
```

## Data Loading

### Direct Load (Small Datasets)

For datasets under 10GB, direct loading via API:

```bash
# Automatic for small scale factors
benchbox run --platform bigquery --benchmark tpch --scale 0.1
```

### Cloud Storage (Large Datasets)

For large datasets, stage in GCS first:

```bash
# Configure GCS staging
benchbox run --platform bigquery --benchmark tpch --scale 100.0 \
  --output gs://your-bucket/benchbox/
```

### Load Job Configuration

```bash
# Customize load behavior
benchbox run --platform bigquery --benchmark tpch \
  --platform-option write_disposition=WRITE_TRUNCATE \
  --platform-option create_disposition=CREATE_IF_NEEDED
```

## Cost Optimization

### Query Cost Limits

Prevent runaway queries:

```bash
# Set per-query limit
benchbox run --platform bigquery --benchmark tpch \
  --platform-option maximum_bytes_billed=1000000000  # 1GB
```

### Dry Run Estimates

Preview query costs:

```bash
# Dry run mode
benchbox run --platform bigquery --benchmark tpch --dry-run ./estimate
```

### Dataset Expiration

Auto-delete test datasets:

```bash
# Set dataset TTL
benchbox run --platform bigquery --benchmark tpch \
  --platform-option dataset_expires_days=7
```

## Troubleshooting

### Authentication Failed

```bash
# Verify credentials
gcloud auth application-default print-access-token

# Check service account permissions
gcloud projects get-iam-policy your-project \
  --filter="bindings.members:benchbox-sa"
```

### Project Not Found

```bash
# Verify project ID
gcloud projects list

# Set default project
gcloud config set project your-project-id
```

### Quota Exceeded

```bash
# Check quotas
gcloud compute project-info describe --project your-project-id

# Request quota increase via Cloud Console
# BigQuery > Quotas > Request Increase
```

### Dataset Location Mismatch

```bash
# Datasets must be in same location as jobs
# Specify location explicitly
benchbox run --platform bigquery --benchmark tpch \
  --platform-option location=us-east1
```

### Permission Denied

```sql
-- Required permissions
-- roles/bigquery.admin (full access)
-- Or specific roles:
-- - roles/bigquery.dataEditor
-- - roles/bigquery.jobUser
-- - roles/storage.objectAdmin (for GCS staging)
```

## Related Documentation

- [Snowflake](snowflake.md) - Multi-cloud warehouse
- [Redshift](redshift.md) - AWS native warehouse
- [Databricks](databricks.md) - Lakehouse alternative
- [Platform Comparison](comparison-matrix.md)
