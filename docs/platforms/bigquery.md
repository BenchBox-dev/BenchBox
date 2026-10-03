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
pip install google-cloud-bigquery google-cloud-storage

pip install "benchbox[bigquery]"
```

## Configuration

### Service Account (Recommended)

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
export BIGQUERY_PROJECT=your-project-id
```

### Application Default Credentials

```bash
gcloud auth application-default login

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
gcloud iam service-accounts create benchbox-sa \
  --display-name="BenchBox Service Account"

gcloud projects add-iam-policy-binding your-project \
  --member="serviceAccount:benchbox-sa@your-project.iam.gserviceaccount.com" \
  --role="roles/bigquery.admin"

gcloud iam service-accounts keys create benchbox-key.json \
  --iam-account=benchbox-sa@your-project.iam.gserviceaccount.com

export GOOGLE_APPLICATION_CREDENTIALS=benchbox-key.json
```

### User Credentials

```bash
gcloud auth application-default login

gcloud config set project your-project-id
```

### Workload Identity (GKE)

```bash
benchbox run --platform bigquery --benchmark tpch \
  --platform-option use_workload_identity=true
```

## Usage Examples

### Basic Benchmark

```bash
benchbox run --platform bigquery --benchmark tpch --scale 1.0 \
  --platform-option project_id=your-project-id
```

### With Cloud Storage Staging

```bash
benchbox run --platform bigquery --benchmark tpch --scale 100.0 \
  --output gs://your-bucket/benchbox/
```

### With Cost Controls

```bash
benchbox run --platform bigquery --benchmark tpch --scale 10.0 \
  --platform-option maximum_bytes_billed=10000000000
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
| Queries | $6.25 per TiB scanned (US/EU/Asia multi-region; per-location rates in `benchbox/core/cost/pricing_data.yaml`) |
| Storage | $0.02 per GB/month |
| Streaming inserts | $0.01 per 200MB |

### Slot Reservations

For predictable costs, use slot reservations:

```bash
benchbox run --platform bigquery --benchmark tpch \
  --platform-option reservation_id=projects/proj/locations/US/reservations/benchbox
```

## Performance Features

### Partitioning

BenchBox applies partitioning with `--tuning tuned`:

```sql
CREATE TABLE lineitem
PARTITION BY DATE(l_shipdate)
CLUSTER BY l_orderkey
AS SELECT * FROM staging.lineitem;
```

### Clustering

Clustering improves query performance:

```sql
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
benchbox run --platform bigquery --benchmark tpch --scale 0.1
```

### Cloud Storage (Large Datasets)

For large datasets, stage in GCS first:

```bash
benchbox run --platform bigquery --benchmark tpch --scale 100.0 \
  --output gs://your-bucket/benchbox/
```

### Load Job Configuration

```bash
benchbox run --platform bigquery --benchmark tpch \
  --platform-option write_disposition=WRITE_TRUNCATE \
  --platform-option create_disposition=CREATE_IF_NEEDED
```

## Cost Optimization

### Query Cost Limits

Prevent runaway queries:

```bash
benchbox run --platform bigquery --benchmark tpch \
  --platform-option maximum_bytes_billed=1000000000
```

### Dry Run Estimates

Preview query costs:

```bash
benchbox run --platform bigquery --benchmark tpch --dry-run ./estimate
```

### Dataset Expiration

Auto-delete test datasets:

```bash
benchbox run --platform bigquery --benchmark tpch \
  --platform-option dataset_expires_days=7
```

## Troubleshooting

### Authentication Failed

```bash
gcloud auth application-default print-access-token

gcloud projects get-iam-policy your-project \
  --filter="bindings.members:benchbox-sa"
```

### Project Not Found

```bash
gcloud projects list

gcloud config set project your-project-id
```

### Quota Exceeded

```bash
gcloud compute project-info describe --project your-project-id

```

### Dataset Location Mismatch

```bash
benchbox run --platform bigquery --benchmark tpch \
  --platform-option location=us-east1
```

### Permission Denied

```sql
```

## Related Documentation

- [Snowflake](snowflake.md) - Multi-cloud warehouse
- [Redshift](redshift.md) - AWS native warehouse
- [Databricks](databricks.md) - Lakehouse alternative
- [Platform Comparison](comparison-matrix.md)
