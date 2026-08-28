<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Amazon Athena Platform

```{tags} intermediate, guide, athena, cloud-platform
```

Amazon Athena is AWS's serverless interactive query service for analyzing data directly in Amazon S3 using standard SQL. Under the hood, Athena runs Trino, optimized for ad-hoc querying of data lakes.

## Features

- **Serverless** - No infrastructure to manage, scales automatically
- **Pay-per-query** - Charged based on data scanned ($5 per TB)
- **S3 native** - Query data directly in S3 without data movement
- **AWS Glue integration** - Uses Glue Data Catalog for metadata
- **Multiple formats** - Parquet, ORC, JSON, CSV, Avro support
- **Partition pruning** - Efficient queries on partitioned data

## Installation

```bash
# Install required dependencies
pip install pyathena boto3

# Or via BenchBox extras
pip install "benchbox[athena]"
```

## Configuration

### Environment Variables

```bash
# AWS credentials
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=us-east-1

# Or use AWS profile
export AWS_PROFILE=your-profile
```

### CLI Options

```bash
benchbox run --platform athena --benchmark tpch --scale 1.0 \
  --platform-option region=us-east-1 \
  --platform-option workgroup=primary \
  --platform-option database=benchbox \
  --platform-option s3_staging_dir=s3://your-bucket/athena-results/
```

### Platform Options

| Option | Default | Description |
|--------|---------|-------------|
| `region` | us-east-1 | AWS region |
| `workgroup` | primary | Athena workgroup for cost tracking |
| `database` | default | Glue Data Catalog database |
| `s3_staging_dir` | (required) | S3 path for query results |
| `s3_data_dir` | (none) | S3 path for benchmark data |
| `catalog` | AwsDataCatalog | Data catalog name |
| `aws_profile` | (none) | AWS credentials profile |

## Usage Examples

### Basic Benchmark Run

```bash
# Run TPC-H on Athena
benchbox run --platform athena --benchmark tpch --scale 1.0 \
  --platform-option s3_staging_dir=s3://my-bucket/athena-results/ \
  --platform-option database=benchmarks
```

### Python API

```python
from benchbox import TPCH
from benchbox.platforms.athena import AthenaAdapter

# Initialize adapter
adapter = AthenaAdapter(
    region="us-east-1",
    workgroup="primary",
    database="benchmarks",
    s3_staging_dir="s3://my-bucket/athena-results/",
    s3_data_dir="s3://my-bucket/benchmark-data/",
)

# Load and run benchmark
benchmark = TPCH(scale_factor=1.0)
adapter.load_benchmark(benchmark)
results = adapter.run_benchmark(benchmark)
```

### External Table Mode

Skip CTAS materialization and register external tables directly over staged Parquet:

```bash
# External mode: query over S3 Parquet without materializing native tables
benchbox run --platform athena --benchmark tpch --scale 1.0 \
  --table-mode external \
  --platform-option staging_root=s3://my-bucket/benchbox/
```

This requires an S3 bucket (via `staging_root` or `s3_bucket`). Not compatible
with `--tuning tuned`.

## S3 Data Staging

BenchBox stages benchmark data to S3 before querying:

```bash
# Specify data location
benchbox run --platform athena --benchmark tpch --scale 1.0 \
  --output s3://my-bucket/benchmarks/tpch_sf1/
```

### Recommended Data Format

For best performance, use Parquet with Snappy compression:

```bash
benchbox run --platform athena --benchmark tpch \
  --table-format parquet \
  --compression snappy
```

## Cost Optimization

### Reduce Data Scanned

Athena charges $5 per TB scanned. Optimize costs with:

1. **Columnar formats** - Parquet/ORC scan only needed columns
2. **Partitioning** - Partition by date/region for predicate pushdown
3. **Compression** - Smaller files = less data scanned

### Workgroup Limits

Set query data scan limits in your workgroup:

```bash
# Create workgroup with cost controls
aws athena create-work-group \
  --name benchbox \
  --configuration "BytesScannedCutoffPerQuery=10737418240"  # 10 GB limit
```

### Cost Estimation

| Scale Factor | Data Size | Est. Full Run Cost |
|--------------|-----------|-------------------|
| 0.1 | ~100 MB | < $0.01 |
| 1.0 | ~1 GB | ~$0.02 |
| 10.0 | ~10 GB | ~$0.20 |
| 100.0 | ~100 GB | ~$2.00 |

## Performance Tips

### Use Partitioning

```sql
-- Create partitioned table
CREATE EXTERNAL TABLE lineitem (...)
PARTITIONED BY (l_shipdate STRING)
STORED AS PARQUET
LOCATION 's3://bucket/lineitem/'
```

### Enable Query Result Reuse

```bash
benchbox run --platform athena --benchmark tpch \
  --platform-option result_reuse_enabled=true
```

### Optimize File Sizes

- **Minimum**: 128 MB per file
- **Optimal**: 256 MB - 1 GB per file
- Avoid many small files

## Limitations

- **Query timeout**: 30 minutes maximum
- **Result size**: 2 GB maximum per query
- **Concurrent queries**: Limited by workgroup (default: 20)
- **No updates**: Read-only queries on S3 data

## Troubleshooting

### Access Denied

```bash
# Verify S3 permissions
aws s3 ls s3://your-bucket/

# Check IAM policy includes:
# - s3:GetObject
# - s3:ListBucket
# - s3:PutObject (for results)
# - athena:StartQueryExecution
# - glue:GetTable, glue:GetDatabase
```

### Query Timeout

```bash
# For long-running queries, increase timeout
benchbox run --platform athena --benchmark tpcds \
  --platform-option query_timeout=1800  # 30 minutes
```

### Data Not Found

```bash
# Verify Glue table exists
aws glue get-table --database-name benchmarks --name lineitem

# Run MSCK REPAIR for partitioned tables
MSCK REPAIR TABLE lineitem;
```

## Related Documentation

- [BigQuery Platform](bigquery.md) - Google Cloud alternative
- [Redshift Platform](redshift.md) - AWS data warehouse
- [Trino Platform](trino.md) - Self-hosted Trino
- [Cloud Storage Guide](../guides/cloud-storage.md)
