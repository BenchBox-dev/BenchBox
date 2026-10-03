<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Redshift Platform

```{tags} intermediate, guide, redshift, cloud-platform
```

Amazon Redshift is a fully managed petabyte-scale data warehouse service in AWS. BenchBox provides comprehensive support for Redshift benchmarking with S3-based data loading via COPY command.

## Features

- **Columnar storage** - Optimized for analytics
- **Massively parallel processing** - Distributed query execution
- **RA3 nodes** - Managed storage with S3 backing
- **Concurrency scaling** - Automatic burst capacity
- **Redshift Spectrum** - Query S3 directly

## Prerequisites

- Amazon Redshift cluster (provisioned or Serverless)
- IAM role with S3 access for COPY command
- S3 bucket for data staging
- VPC security group allowing inbound connections

## Installation

```bash
pip install redshift_connector boto3

pip install "benchbox[redshift]"
```

## Configuration

### Environment Variables (Recommended)

```bash
export REDSHIFT_HOST=your-cluster.abc123xyz.us-east-1.redshift.amazonaws.com
export REDSHIFT_USER=admin
export REDSHIFT_PASSWORD=your_password
export REDSHIFT_DATABASE=dev
export REDSHIFT_IAM_ROLE=arn:aws:iam::123456789:role/RedshiftS3Access
```

### Interactive Setup

```bash
benchbox setup --platform redshift
```

### CLI Options

```bash
benchbox run --platform redshift --benchmark tpch --scale 1.0 \
  --platform-option host=your-cluster.abc123xyz.us-east-1.redshift.amazonaws.com \
  --platform-option user=admin \
  --platform-option password=your_password \
  --platform-option database=dev
```

## Platform Options

| Option | Default | Description |
|--------|---------|-------------|
| `host` | (env) | Cluster endpoint |
| `user` | (env) | Database username |
| `password` | (env) | Database password |
| `database` | dev | Database name |
| `port` | 5439 | Connection port |
| `iam_role` | (env) | IAM role ARN for COPY |
| `region` | (auto) | AWS region |
| `ssl` | true | Enable SSL connection |
| `driver_version` | (latest) | Pin the redshift_connector package version (e.g. `2.1.3`) |
| `driver_auto_install` | false | Auto-install the requested driver version via uv if missing |

### Testing a Specific Redshift Connector Version

```bash
benchbox run --platform redshift --benchmark tpch \
  --platform-option driver_version=2.1.3 \
  --platform-option driver_auto_install=true \
  --platform-option host=my-cluster.abc123.us-east-1.redshift.amazonaws.com
```

The driver package for Redshift is `redshift-connector`.

See {ref}`driver-version-management` for the full guide, including why `uv run` may
revert a manually-installed version and how to work around it.

## Authentication Methods

### Standard Authentication

```bash
benchbox run --platform redshift --benchmark tpch --scale 1.0 \
  --platform-option host=cluster.abc123.us-east-1.redshift.amazonaws.com \
  --platform-option user=admin \
  --platform-option password=secure_password
```

### IAM Authentication

```bash
export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY

benchbox run --platform redshift --benchmark tpch \
  --platform-option host=cluster.abc123.us-east-1.redshift.amazonaws.com \
  --platform-option user=iam_user \
  --platform-option iam_auth=true
```

### Redshift Serverless

```bash
benchbox run --platform redshift --benchmark tpch \
  --platform-option workgroup_name=default \
  --platform-option database=dev
```

## Usage Examples

### Basic Benchmark

```bash
benchbox run --platform redshift --benchmark tpch --scale 1.0
```

### With S3 Staging

```bash
benchbox run --platform redshift --benchmark tpch --scale 100.0 \
  --output s3://your-bucket/benchbox/
```

### With Tuning

```bash
benchbox run --platform redshift --benchmark tpch --scale 10.0 \
  --tuning tuned
```

### Python API

```python
from benchbox import TPCH
from benchbox.platforms.redshift import RedshiftAdapter

adapter = RedshiftAdapter(
    host="cluster.abc123.us-east-1.redshift.amazonaws.com",
    user="admin",
    password="secure_password",
    database="dev",
    iam_role="arn:aws:iam::123456789:role/RedshiftS3Access",
)

benchmark = TPCH(scale_factor=1.0)
benchmark.generate_data()
adapter.load_benchmark(benchmark)
results = adapter.run_benchmark(benchmark)
```

## Node Types

### RA3 Nodes (Recommended)

| Node Type | vCPU | Memory | Storage |
|-----------|------|--------|---------|
| ra3.xlplus | 4 | 32 GB | Managed |
| ra3.4xlarge | 12 | 96 GB | Managed |
| ra3.16xlarge | 48 | 384 GB | Managed |

### DC2 Nodes (Dense Compute)

| Node Type | vCPU | Memory | Storage |
|-----------|------|--------|---------|
| dc2.large | 2 | 15 GB | 160 GB |
| dc2.8xlarge | 32 | 244 GB | 2.56 TB |

### Serverless

```bash
benchbox run --platform redshift --benchmark tpch \
  --platform-option workgroup_name=benchbox-wg
```

## Performance Features

### Distribution Keys

BenchBox applies distribution keys with `--tuning tuned`:

```sql
CREATE TABLE lineitem (...)
DISTKEY (l_orderkey)
SORTKEY (l_shipdate);

CREATE TABLE nation (...)
DISTSTYLE ALL;
```

### Sort Keys

```sql
CREATE TABLE orders (...)
COMPOUND SORTKEY (o_orderdate, o_custkey);

CREATE TABLE lineitem (...)
INTERLEAVED SORTKEY (l_shipdate, l_receiptdate);
```

### WLM Configuration

BenchBox uses dedicated queue for benchmark queries:

```bash
benchbox run --platform redshift --benchmark tpch \
  --platform-option query_group=benchbox \
  --platform-option concurrency_scaling=on
```

## Data Loading

### COPY from S3 (Recommended)

```bash
benchbox run --platform redshift --benchmark tpch --scale 10.0 \
  --output s3://bucket/benchbox/
```

### IAM Role Setup

```bash
aws iam create-role --role-name RedshiftS3Access \
  --assume-role-policy-document file://trust-policy.json

aws iam attach-role-policy --role-name RedshiftS3Access \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess

aws redshift modify-cluster-iam-roles \
  --cluster-identifier my-cluster \
  --add-iam-roles arn:aws:iam::123456789:role/RedshiftS3Access
```

### Direct Insert (Small Datasets)

For datasets under 1GB, direct INSERT is used automatically:

```bash
benchbox run --platform redshift --benchmark tpch --scale 0.01
```

## Cost Optimization

### Concurrency Scaling

```bash
benchbox run --platform redshift --benchmark tpch \
  --platform-option concurrency_scaling=auto
```

### Pause/Resume

```bash
aws redshift pause-cluster --cluster-identifier my-cluster

aws redshift resume-cluster --cluster-identifier my-cluster
```

### Serverless RPU

```bash
benchbox run --platform redshift --benchmark tpch \
  --platform-option workgroup_name=benchbox \
  --platform-option max_rpu=128
```

## Troubleshooting

### Connection Refused

```bash
aws redshift describe-clusters --cluster-identifier my-cluster

aws ec2 describe-security-groups --group-ids sg-xxx

aws ec2 authorize-security-group-ingress \
  --group-id sg-xxx \
  --protocol tcp \
  --port 5439 \
  --cidr YOUR_IP/32
```

### COPY Failed

```bash
SELECT * FROM stl_load_errors ORDER BY starttime DESC LIMIT 10;

aws redshift describe-clusters --cluster-identifier my-cluster \
  --query 'Clusters[0].IamRoles'

SELECT * FROM svl_s3list
WHERE bucket = 'your-bucket';
```

### Permission Denied

```sql
GRANT CREATE ON DATABASE dev TO benchbox_user;
GRANT CREATE ON SCHEMA public TO benchbox_user;
GRANT ALL ON ALL TABLES IN SCHEMA public TO benchbox_user;
```

### Query Timeout

```bash
benchbox run --platform redshift --benchmark tpch \
  --platform-option statement_timeout=3600000
```

### Disk Space Exceeded

```bash
SELECT owner, host, diskno, used, capacity
FROM stv_partitions
ORDER BY used DESC;

VACUUM FULL lineitem;
```

## Related Documentation

- [BigQuery](bigquery.md) - Google Cloud alternative
- [Snowflake](snowflake.md) - Multi-cloud warehouse
- [Athena](athena.md) - Serverless S3 queries
- [Platform Comparison](comparison-matrix.md)
