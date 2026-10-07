<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Google Cloud Dataproc Serverless Platform

```{tags} intermediate, guide, dataproc-serverless, cloud-platform
```

Dataproc Serverless is Google Cloud's fully managed Apache Spark service that eliminates cluster management entirely. You submit batches and Google Cloud handles all infrastructure automatically with sub-minute startup times.

## Features

- **Zero Cluster Management** - No clusters to create, configure, or maintain
- **Fast Startup** - Sub-minute batch startup (vs minutes for clusters)
- **Auto-scaling** - Resources scale automatically based on workload
- **Cost-effective** - Pay only for actual compute time, no idle costs
- **GCS Integration** - Native Google Cloud Storage support

## Installation

```bash
# Install with Dataproc Serverless support
uv add benchbox --extra dataproc-serverless

# Dependencies installed: google-cloud-dataproc, google-cloud-storage
```

## Prerequisites

1. **GCP project** with Dataproc Serverless API enabled
2. **GCS bucket** for data staging
3. **Google Cloud authentication** configured:
   - Interactive: `gcloud auth application-default login`
   - Service account: `GOOGLE_APPLICATION_CREDENTIALS` environment variable
   - Compute Engine: Automatic metadata service

## Configuration

### Environment Variables

```bash
# Required
export GOOGLE_CLOUD_PROJECT=my-project
export GCS_STAGING_DIR=gs://my-bucket/benchbox

# Optional
export DATAPROC_REGION=us-central1
export DATAPROC_RUNTIME_VERSION=2.1
```

### CLI Usage

```bash
# Basic usage
benchbox run --platform dataproc-serverless --benchmark tpch --scale 1.0 \
  --platform-option project_id=my-project \
  --platform-option gcs_staging_dir=gs://my-bucket/benchbox

# With custom region
benchbox run --platform dataproc-serverless --benchmark tpch --scale 1.0 \
  --platform-option project_id=my-project \
  --platform-option gcs_staging_dir=gs://my-bucket/benchbox \
  --platform-option region=europe-west1

# With service account
benchbox run --platform dataproc-serverless --benchmark tpch --scale 1.0 \
  --platform-option project_id=my-project \
  --platform-option gcs_staging_dir=gs://my-bucket/benchbox \
  --platform-option service_account=my-sa@my-project.iam.gserviceaccount.com

# Dry-run to preview queries
benchbox run --platform dataproc-serverless --benchmark tpch --dry-run ./preview \
  --platform-option project_id=my-project \
  --platform-option gcs_staging_dir=gs://my-bucket/benchbox
```

### Platform Options

| Option | Default | Description |
|--------|---------|-------------|
| `project_id` | *required* | GCP project ID |
| `gcs_staging_dir` | *required* | GCS path for data staging (e.g., gs://bucket/path) |
| `region` | us-central1 | GCP region for batch execution |
| `database` | benchbox | Hive database name |
| `runtime_version` | 2.1 | Dataproc Serverless runtime version |
| `service_account` | - | Service account email for batch execution |
| `network_uri` | - | VPC network URI (optional) |
| `subnetwork_uri` | - | Subnetwork URI (optional) |
| `timeout_minutes` | 60 | Batch timeout in minutes |

## Python API

```python
from benchbox.platforms.gcp import DataprocServerlessAdapter

# Initialize with project and staging
adapter = DataprocServerlessAdapter(
    project_id="my-project",
    region="us-central1",
    gcs_staging_dir="gs://my-bucket/benchbox",
)

# Verify connection
adapter.create_connection()

# Create schema
adapter.create_schema("tpch_benchmark")

# Load data to GCS and create tables
adapter.load_data(
    tables=["lineitem", "orders", "customer"],
    source_dir="/path/to/tpch/data",
)

# Execute query via Serverless batch
result = adapter.execute_query("SELECT COUNT(*) FROM lineitem")

# Clean up
adapter.close()
```

## Execution Model

Dataproc Serverless executes benchmarks via the Batch Controller API:

1. **Batch Submission** - PySpark script submitted to Serverless
2. **Resource Provisioning** - GCP automatically provisions Spark resources
3. **Execution** - SQL query executed via Spark SQL
4. **Result Storage** - Results written to GCS
5. **Cleanup** - Resources automatically released

## Serverless vs Cluster-based Dataproc

| Aspect | Dataproc Serverless | Dataproc Clusters |
|--------|---------------------|-------------------|
| Startup | Sub-minute | Minutes |
| Management | Zero | Requires configuration |
| Scaling | Automatic | Manual or auto-scale rules |
| Idle Costs | None | Cluster running costs |
| Use Case | Intermittent workloads | Continuous workloads |
| Customization | Runtime only | Full cluster control |

## Runtime Versions

| Version | Spark | Python | Release |
|---------|-------|--------|---------|
| 2.2 | 3.5.x | 3.11 | Latest |
| 2.1 | 3.4.x | 3.10 | Stable |
| 2.0 | 3.3.x | 3.10 | Legacy |

## Authentication

Dataproc Serverless uses Google Cloud Application Default Credentials (ADC):

### Interactive Login (Development)

```bash
gcloud auth application-default login
```

### Service Account (Automation)

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json

# Or use service account impersonation
gcloud auth application-default login --impersonate-service-account=SA@PROJECT.iam.gserviceaccount.com
```

### Compute Engine (GCE/GKE)

No configuration needed - automatically uses instance service account.

## Cost Estimation

Dataproc Serverless uses consumption-based billing:

| Resource | Price |
|----------|-------|
| vCPU | ~$0.06/hour |
| Memory | ~$0.0065/GB-hour |

| Scale Factor | Data Size | Est. Runtime | Est. Cost* |
|--------------|-----------|--------------|------------|
| 0.01 | ~10 MB | ~10 min | ~$0.05 |
| 1.0 | ~1 GB | ~45 min | ~$0.50 |
| 10.0 | ~10 GB | ~2 hours | ~$3.00 |
| 100.0 | ~100 GB | ~6 hours | ~$15.00 |

*Estimates vary based on query complexity and data distribution.

## IAM Permissions

Required roles for the executing identity:

```
roles/dataproc.worker        # Submit and manage batches
roles/storage.objectAdmin    # Read/write GCS staging
```

Recommended project-level setup:

```bash
# Grant Dataproc permissions
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="user:USER@DOMAIN.COM" \
  --role="roles/dataproc.worker"

# Grant storage permissions
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="user:USER@DOMAIN.COM" \
  --role="roles/storage.objectAdmin"
```

## VPC Configuration

For private networking, specify VPC and subnet:

```bash
benchbox run --platform dataproc-serverless --benchmark tpch \
  --platform-option project_id=my-project \
  --platform-option gcs_staging_dir=gs://my-bucket/benchbox \
  --platform-option network_uri=projects/my-project/global/networks/my-vpc \
  --platform-option subnetwork_uri=projects/my-project/regions/us-central1/subnetworks/my-subnet
```

## Troubleshooting

### Common Issues

**Authentication fails:**
- Run `gcloud auth application-default login`
- Check service account permissions
- Verify project ID is correct

**Batch fails to start:**
- Check Dataproc Serverless API is enabled
- Verify IAM permissions
- Review GCP quotas

**Storage access denied:**
- Check `roles/storage.objectAdmin` permission
- Verify GCS bucket exists
- Check bucket is in same project or cross-project permissions

**Batch timeout:**
- Increase `timeout_minutes` for large scale factors
- Check for data skew issues
- Review batch logs in GCP Console

## Related

- [Google Cloud Dataproc](gcp-dataproc.md) - Cluster-based managed Spark
- [Apache Spark Platform](spark.md) - Local/cluster Spark usage
- [Cloud Platforms Overview](cloud-platforms.md) - All cloud platforms
