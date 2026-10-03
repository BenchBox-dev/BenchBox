# Cloud Storage Support

```{tags} intermediate, guide, cloud-storage, cloud-platform
```

BenchBox provides minimal cloud storage path support, allowing you to specify cloud storage locations for data generation and storage while maintaining simplicity and leveraging database cloud integration features.

## Overview

BenchBox supports cloud storage through the `cloudpathlib` library, which provides unified access to:
- **AWS S3** (`s3://bucket/path`)
- **Google Cloud Storage** (`gs://bucket/path`)
- **Azure Blob Storage** (`abfss://container@account.dfs.core.windows.net/path`)

The implementation follows a minimal abstraction approach:
1. **Local Generation**: Data is generated locally using TPC tools
2. **Cloud Upload**: Generated files are uploaded to specified cloud storage
3. **Database Integration**: Platform adapters load data directly from cloud storage using native cloud features

## Installation

Cloud storage support requires the optional `cloudstorage` dependency:

```bash
uv add benchbox --extra cloudstorage

uv add benchbox --extra cloud

python -m pip install "benchbox[cloudstorage]"
```

## Authentication Setup

### AWS S3

Set AWS credentials using environment variables:

```bash
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=us-west-2
```

Alternative authentication methods:
- AWS credentials file (`~/.aws/credentials`)
- IAM roles (for EC2 instances)
- AWS CLI profile (`aws configure`)

### Google Cloud Storage

Set GCP credentials using a service account:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

Alternative authentication methods:
- Google Cloud SDK (`gcloud auth application-default login`)
- Compute Engine default service account
- Workload Identity (for GKE)

### Azure Blob Storage

Set Azure credentials using environment variables:

```bash
export AZURE_STORAGE_ACCOUNT_NAME=your_account
export AZURE_STORAGE_ACCOUNT_KEY=your_key
```

Alternative authentication methods:
- Azure CLI (`az login`)
- Managed Service Identity
- SAS tokens

### Unity Catalog Volumes (Databricks)

Databricks Unity Catalog Volumes provide native file storage within the Databricks workspace. BenchBox automatically handles UC Volume uploads for seamless data loading.

**What are UC Volumes?**
- Native Databricks storage accessible via `dbfs:/Volumes/` paths
- Three-level namespace: `catalog.schema.volume`
- Available in all Databricks workspaces (including Free Edition)
- No external cloud storage account required

**Authentication:**
UC Volumes use the same Databricks authentication as SQL Warehouses (access token). No additional credentials needed.

**Automatic Upload Workflow:**
BenchBox automatically uploads locally-generated data to UC Volumes:

```bash
benchbox run --platform databricks --benchmark tpch --scale 0.01 \
             --output dbfs:/Volumes/workspace/benchbox/data
```

This workflow:
1. Generates TPC-H data files locally (TPC tools can't write directly to UC Volumes)
2. **Automatically creates the schema and UC Volume if they don't exist**
3. Automatically uploads files to UC Volume using Databricks Files API
4. Executes COPY INTO to load data from UC Volume into tables

**Prerequisites:**
Only one prerequisite - install `databricks-sdk` for file uploads:
```bash
uv pip install databricks-sdk
```

Note: Both the schema and UC Volume are automatically created by BenchBox. Manual creation is not required.

**Platform Options:**
Databricks supports these platform options for UC Volume configuration:

```bash
benchbox run --platform databricks --benchmark tpch --scale 1 \
             --platform-option uc_catalog=workspace \
             --platform-option uc_schema=benchbox \
             --platform-option uc_volume=data

benchbox run --platform databricks --benchmark tpch --scale 1 \
             --output dbfs:/Volumes/workspace/benchbox/data
```

**Databricks Free Edition Workflow:**
Free Edition workspaces are limited to UC Volumes (no external S3/Azure/GCS). BenchBox fully supports this:

```bash
benchbox run --platform databricks --benchmark tpch --scale 0.01 \
             --output dbfs:/Volumes/workspace/benchbox/data \
             --phases generate,load,power
```

Both the schema and UC Volume are automatically created if they don't exist - no manual setup required!

**Permission Requirements:**
If you don't have CREATE SCHEMA or CREATE VOLUME permissions, BenchBox will provide clear guidance:
```
Permission denied creating schema: workspace.benchbox
Ensure you have CREATE SCHEMA permission on catalog workspace
Or create it manually: CREATE SCHEMA IF NOT EXISTS workspace.benchbox
```

## Basic Usage

### Command Line Interface

Use the `--output` parameter with cloud storage paths:

```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.01 \
             --output s3://my-bucket/benchbox/tpch-data

benchbox run --platform duckdb --benchmark tpch --scale 0.01 \
             --output gs://my-bucket/benchbox/tpch-data

benchbox run --platform duckdb --benchmark tpch --scale 0.01 \
             --output abfss://container@account.dfs.core.windows.net/benchbox/data
```

### Output Path Normalization (Remote Paths)

BenchBox normalizes remote output roots by appending the dataset suffix `<benchmark>_<sf>`.
This matches local defaults and prevents dataset collisions.

Examples:

```bash
benchbox run --platform databricks --benchmark tpch --scale 0.01 \
             --output dbfs:/Volumes/workspace/raw/source/

benchbox run --platform duckdb --benchmark tpcds --scale 1.0 \
             --output s3://my-bucket/benchbox
```

### Python API

Cloud storage paths work seamlessly with the Python API:

```python
from benchbox import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = TPCH(
    scale_factor=0.01,
    output_dir="s3://my-bucket/benchbox/tpch-data"
)

adapter = DuckDBAdapter()
results = adapter.run_benchmark(benchmark)
```

## Credential Validation

BenchBox automatically validates cloud credentials before execution:

```bash
$ benchbox run --platform duckdb --benchmark tpch --output s3://my-bucket/data

Cloud storage output detected: s3://my-bucket/data
✅ Cloud storage credentials validated
  Provider: s3
  Bucket: my-bucket
```

If credentials are missing or invalid, BenchBox provides setup guidance:

```bash
❌ Cloud storage credentials validation failed:
   Provider: s3
   Bucket: my-bucket
   Error: Missing environment variables: AWS_ACCESS_KEY_ID

AWS S3 Setup:
1. Set environment variables:
   export AWS_ACCESS_KEY_ID=your_access_key
   export AWS_SECRET_ACCESS_KEY=your_secret_key
   export AWS_DEFAULT_REGION=us-west-2
```

## Data Flow

The cloud storage implementation follows this workflow:

1. **Local Generation**: TPC data generators create files in temporary directory
2. **Cloud Upload**: Files are uploaded to specified cloud storage path
3. **Database Loading**: Platform adapters load data directly from cloud storage
4. **Query Execution**: Benchmarks execute against cloud-loaded data

```
Local TPC Tools → Temp Directory → Cloud Upload → Database Loading → Query Execution
     └─────────────── Local ─────────────┘  └─────────── Cloud ──────────────┘
```

## Platform Integration

### DuckDB Cloud Support

DuckDB can read directly from cloud storage:

```sql
SELECT * FROM read_csv('s3://bucket/data/lineitem.tbl', delim='|', header=false)
```

Configuration is handled automatically by the DuckDB adapter.

### BigQuery Integration

BigQuery benchmarks use Google Cloud Storage integration:

```python
benchmark = TPCH(output_dir="gs://my-bucket/bq-data")
adapter = BigQueryAdapter()
results = adapter.run_benchmark(benchmark)
```

### Snowflake Integration

Snowflake benchmarks use cloud storage stages:

```python
benchmark = TPCH(output_dir="s3://my-bucket/snowflake-data")
adapter = SnowflakeAdapter()
results = adapter.run_benchmark(benchmark)
```

## Best Practices

### Bucket Organization

Organize cloud storage with consistent naming:

```
s3://my-benchbox-bucket/
├── benchmarks/
│   ├── tpch/
│   │   ├── scale-0.01/
│   │   ├── scale-0.1/
│   │   └── scale-1.0/
│   ├── tpcds/
│   └── ssb/
└── results/
    ├── 2025-01-15/
    └── 2025-01-16/
```

### Performance Considerations

1. **Reuse Data**: Generated cloud data persists across runs
2. **Regional Locality**: Use cloud storage in same region as compute
3. **Parallel Generation**: TPC tools generate data locally in parallel
4. **Incremental Upload**: Only missing files are uploaded to cloud storage

### Security Guidelines

1. **Least Privilege**: Grant minimal required permissions
2. **Bucket Policies**: Restrict access to specific prefixes
3. **Credential Rotation**: Regularly rotate access keys
4. **Network Security**: Use VPC endpoints when possible

## Troubleshooting

### Connection Issues

```bash
python -c "
from benchbox.utils.cloud_storage import validate_cloud_credentials
result = validate_cloud_credentials('s3://my-bucket/test')
print(f'Valid: {result[\"valid\"]}')
print(f'Error: {result[\"error\"]}')
"
```

### Permission Errors

Ensure your cloud credentials have the following permissions:

**AWS S3 Permissions:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::my-bucket",
        "arn:aws:s3:::my-bucket/*"
      ]
    }
  ]
}
```

**Google Cloud Storage Permissions:**
- `storage.objects.get`
- `storage.objects.create`
- `storage.objects.delete`
- `storage.buckets.get`

### Large Scale Factors

For large benchmarks (scale factor ≥ 1.0):
- Monitor upload progress and costs
- Consider using cloud compute near storage region
- Implement upload retry logic for reliability

## Examples

See the `examples/` directory for complete cloud storage examples:
- `cloud_storage_s3.py` - AWS S3 integration
- `cloud_storage_gcs.py` - Google Cloud Storage integration

## Limitations

1. **Upload Time**: Large datasets require upload time to cloud storage
2. **Network Dependency**: Requires stable internet connection
3. **Cloud Costs**: Storage and data transfer charges apply
4. **Local Generation**: TPC tools still require local generation
5. **Single Region**: No cross-region replication built-in

Cloud storage support maintains BenchBox's simplicity while enabling cloud-scale benchmarking workflows.

## Manifest-Based Upload Validation

BenchBox writes a `_datagen_manifest.json` alongside generated data. When loading to
remote storage (e.g., Databricks UC Volumes), BenchBox performs a pre‑upload validation:

- If a remote manifest exists and matches the local manifest (benchmark, scale factor,
  compression, table/file counts), and all referenced remote files are present, BenchBox
  reuses the existing data and skips uploading.
- If validation fails (missing/changed data), BenchBox uploads the manifest and data files.

Use `--force-upload` to bypass validation and force a re‑upload, even when the remote data is
valid. This is helpful for debugging or refreshing remote data.

Troubleshooting tips:
- Ensure the remote path is correct (e.g., `dbfs:/Volumes/<catalog>/<schema>/<volume>`)
- Verify permissions for reading and writing to the target location
- Check logs for detailed validation messages (differences between local and remote manifest)
