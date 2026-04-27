# Free trial benchmarking: Amazon Athena

> Athena has no dedicated trial, but AWS Free Tier credits work. Here's how to run TPC-H benchmarks on AWS's serverless query engine with per-TB pricing.

**TL;DR**: Athena doesn't have a dedicated trial, but new AWS accounts get $300 in Free Tier credits (12 months). Athena charges $5 per TB scanned, similar to BigQuery. Workgroup data scan limits prevent runaway costs. Partitioning and columnar formats (Parquet) can reduce costs 90%+.

---

## What you get

**Trial details:**
- **Dedicated trial**: None
- **AWS Free Tier**: $300 credits for new accounts (12 months, shared across all AWS services)
- **Athena-specific free tier**: None (every query costs money)
- **Credit card**: Required for AWS account

**The Athena model:**

Athena is AWS's serverless query engine built on Presto/Trino. Key characteristics:
- No infrastructure to manage
- Pay only for data scanned ($5/TB)
- Queries run directly against S3 data
- Supports standard SQL (ANSI SQL)
- Integrates with AWS Glue Data Catalog

**Pricing model: Per-TB scanned**

| Component      | Cost                         |
| -------------- | ---------------------------- |
| Data scanned   | $5.00 per TB                 |
| Minimum charge | 10 MB per query              |
| DDL queries    | Free (CREATE, ALTER, DROP)   |
| Failed queries | Free (no data scanned)       |
| S3 storage     | Separate (standard S3 rates) |

**Cost comparison with BigQuery:**
- BigQuery: $6.25/TB scanned
- Athena: $5.00/TB scanned
- Athena is ~20% cheaper per TB, but lacks a permanent free tier

**What happens when credits run out:**
Queries continue at standard pay-per-query rates. No hard stop unless you configure workgroup limits.

---

## Explore with MCP

Before spending credits, use the MCP server to preview your benchmark runs:

**Validate configuration:**

> "Can I run TPC-H on Athena with my current setup?"

The assistant calls `validate_config(platform="athena", benchmark="tpch")` and reports any issues with your AWS credentials or S3 bucket configuration.

**Preview resource consumption:**

> "What would a TPC-H SF1 run on Athena look like?"

```
# Example MCP dry_run response
Platform: Amazon Athena
Benchmark: TPC-H SF1
Estimated data size: ~1 GB (Parquet compressed)
Tables: 8 (nation, region, part, supplier, partsupp, customer, orders, lineitem)
Queries: 22
Phases: load, power

Notes:
- Data stored in S3, queried via Athena
- Per-TB billing ($5/TB scanned)
- Parquet format reduces scanned data significantly
- Estimated cost: $2-5 depending on format
```

**Check cost optimization options:**

> "How can I reduce Athena query costs for TPC-H?"

Key optimizations:
- Use Parquet or ORC format (columnar, compressed)
- Partition tables by date columns
- Use projection queries (SELECT specific columns, not *)
- Enable workgroup query result reuse

---

## The game plan

### Understanding Athena's pricing model

Like BigQuery, Athena charges per TB scanned:
- **Query complexity doesn't matter**: Simple or complex, same data = same cost
- **Data format matters hugely**: Parquet can reduce scanned data 90%+
- **Partitioning helps**: Queries can skip irrelevant partitions
- **Column selection helps**: Columnar formats only read needed columns

**Pricing comparison:**

| Format                 | SF1 Full Scan | Est. Cost |
| ---------------------- | ------------- | --------- |
| CSV (uncompressed)     | ~1 GB         | ~$0.005   |
| Parquet (compressed)   | ~300 MB       | ~$0.0015  |
| Parquet + partitioning | ~100 MB       | ~$0.0005  |

At small scale factors, costs are minimal. At SF100+, format and partitioning become critical.

### AWS Free Tier budget

With $300 in AWS Free Tier credits (shared across all services):

| Scale Factor | Est. TB Scanned    | Est. Cost | Runs Available |
| ------------ | ------------------ | --------- | -------------- |
| SF0.01       | ~0.001 TB          | ~$0.01    | ~30,000        |
| SF1          | ~0.05 TB (Parquet) | ~$0.25    | ~1,200         |
| SF10         | ~0.5 TB (Parquet)  | ~$2.50    | ~120           |
| SF100        | ~5 TB (Parquet)    | ~$25      | ~12            |

**Strategy**: Athena is extremely cost-effective for benchmarking. Even aggressive testing rarely exceeds $50.

### The scaling progression

1. **SF0.01 with Parquet**: Validate connectivity, schema, queries (pennies)
2. **SF1 with Parquet**: First meaningful benchmark (~$0.25)
3. **SF1 CSV vs Parquet**: Compare format impact on cost and performance
4. **SF10 with Parquet**: Larger data volume (~$2.50)

---

## BenchBox setup

### Install dependencies

```bash
uv add boto3 pyathena
```

### Configuration

BenchBox reads Athena credentials from environment variables:

```bash
# AWS credentials
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_REGION="us-east-1"

# Athena configuration
export ATHENA_S3_STAGING_DIR="s3://your-bucket/athena-results/"
export ATHENA_DATABASE="benchbox"
export ATHENA_WORKGROUP="primary"

# S3 bucket for benchmark data
export ATHENA_DATA_BUCKET="your-benchmark-data-bucket"
```

**Setting up S3 buckets:**

You need two S3 locations:
1. **Data bucket**: Where TPC-H tables are stored
2. **Results bucket**: Where Athena writes query results

```bash
# Create buckets (same region as Athena)
aws s3 mb s3://your-benchmark-data-bucket --region us-east-1
aws s3 mb s3://your-athena-results-bucket --region us-east-1
```

**Setting up a workgroup with limits:**

```bash
aws athena create-work-group \
  --name benchbox \
  --configuration "BytesScannedCutoffPerQuery=10737418240" \
  --description "BenchBox benchmarking with 10GB scan limit"
```

### Verify connection

```bash
# Quick connectivity test
uv run python -c "
import boto3
import os

athena = boto3.client('athena', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
result = athena.list_work_groups()
print('Connected to Athena. Workgroups:', [wg['Name'] for wg in result['WorkGroups']])
"
```

---

## Running the benchmarks

### Step 1: Configure workgroup limits (recommended)

Before benchmarking, set up a workgroup with data scan limits:

```bash
# Create workgroup with 10GB per-query limit
aws athena create-work-group \
  --name benchbox \
  --configuration '{
    "BytesScannedCutoffPerQuery": 10737418240,
    "EnforceWorkGroupConfiguration": true,
    "PublishCloudWatchMetricsEnabled": true
  }'
```

This prevents any single query from scanning more than 10GB, limiting worst-case cost to $0.05.

### Step 2: Validate with SF0.01

```bash
benchbox run --platform athena --benchmark tpch --scale 0.01
```

Expected output:
```
BenchBox v0.2.0
Platform: Amazon Athena
Benchmark: TPC-H SF0.01

[INFO] Generating data (Parquet format)...
[INFO] Uploading to S3...
[INFO] Creating external tables...
[INFO] Running power phase (22 queries)...
[SUCCESS] Completed in 8m 45s

Total data scanned: 12.3 MB
Estimated cost: $0.0001

Results saved to: benchmark_runs/results/tpch_sf001_athena_20260131_143022.json
```

**What BenchBox does automatically:**
- Generates TPC-H data in Parquet format
- Uploads to your S3 data bucket
- Creates external tables in AWS Glue Data Catalog
- Configures partitioning for large tables
- Runs all 22 TPC-H queries
- Reports data scanned and estimated cost
- Validates results against reference answers

### Step 3: Baseline at SF1

```bash
benchbox run --platform athena --benchmark tpch --scale 1
```

This typically scans 50-100 MB (Parquet) across all 22 queries, costing ~$0.25-0.50.

### Step 4: Compare formats

To understand the cost impact of data format:

```bash
# Generate data, then run against Athena with pre-generated data
benchbox datagen --benchmark tpch --scale 1 --output ./data/tpch
benchbox run --platform athena --benchmark tpch --scale 1 --data-dir ./data/tpch

# Default run uses Parquet (no extra flags needed)
benchbox run --platform athena --benchmark tpch --scale 1
```

### Running specific queries

```bash
# Run only the scan-heavy queries
benchbox run --platform athena --benchmark tpch --scale 1 --queries Q1,Q6,Q12,Q14
```

---

## Reproducing and comparing

### Find your previous runs

> "Show me my recent Athena benchmark runs"

Or via CLI:

```bash
ls -la benchmark_runs/results/ | grep athena
```

### Analyze cost efficiency

> "Which TPC-H queries scanned the most data on Athena?"

```
Data scanned by query (SF1, Parquet):

Most expensive:
- Q1: 45 MB (full lineitem scan)
- Q6: 42 MB (lineitem with predicates)
- Q12: 38 MB (lineitem + orders join)

Most efficient:
- Q2: 8 MB (small tables, selective)
- Q11: 6 MB (supplier + partsupp)
- Q22: 5 MB (customer subset)

Total: 52 MB scanned, ~$0.26 cost
```

### Compare with other platforms

> "Compare my Athena and Redshift Serverless TPC-H results"

Both are AWS services with different pricing models:
- Athena: Per-TB scanned, no idle cost
- Redshift: Per-RPU-hour, capacity-based

---

## Trial traps to avoid

### 1. Using CSV instead of Parquet

**The trap**: Storing TPC-H data as CSV. Athena scans the entire file for every query, even if you only need one column.

**The fix**: Always use Parquet (or ORC). BenchBox defaults to Parquet. For manual data:
```sql
CREATE TABLE lineitem
WITH (format = 'PARQUET', external_location = 's3://bucket/lineitem/')
AS SELECT * FROM lineitem_csv;
```

### 2. SELECT * on large tables

**The trap**: Running `SELECT * FROM lineitem LIMIT 10` still scans significant data because Athena reads all columns.

**The fix**: Select only needed columns:
```sql
SELECT l_orderkey, l_quantity FROM lineitem LIMIT 10;
```

### 3. No workgroup limits

**The trap**: A malformed query or missing partition filter scans your entire dataset unexpectedly.

**The fix**: Set `BytesScannedCutoffPerQuery` in your workgroup:
```bash
aws athena update-work-group \
  --work-group benchbox \
  --configuration-updates "BytesScannedCutoffPerQuery=10737418240"
```

### 4. Forgetting S3 storage costs

**The trap**: Focusing only on query costs while S3 storage accumulates.

**The fix**: Clean up test data after benchmarking:
```bash
aws s3 rm s3://your-bucket/tpch-data/ --recursive
```

### 5. Not partitioning large tables

**The trap**: Creating unpartitioned tables, forcing full scans for date-range queries.

**The fix**: BenchBox partitions `lineitem` and `orders` by date. For manual tables:
```sql
CREATE TABLE lineitem (...)
PARTITIONED BY (l_shipdate_year STRING)
STORED AS PARQUET
LOCATION 's3://bucket/lineitem/';
```

### Cleanup checklist before credits run out

- [ ] Download result files from `benchmark_runs/results/`
- [ ] Delete test data from S3: `aws s3 rm s3://bucket/tpch-data/ --recursive`
- [ ] Delete Athena databases: `DROP DATABASE benchbox CASCADE`
- [ ] Review CloudWatch metrics for query history
- [ ] Note effective format and partitioning strategies

---

## Cost reference

Based on our testing with Parquet format:

| Scale Factor | Data Size (Parquet) | Est. Scanned | Est. Cost |
| ------------ | ------------------- | ------------ | --------- |
| SF0.01       | ~10 MB              | ~12 MB       | ~$0.0001  |
| SF1          | ~300 MB             | ~50 MB       | ~$0.25    |
| SF10         | ~3 GB               | ~500 MB      | ~$2.50    |
| SF100        | ~30 GB              | ~5 GB        | ~$25      |

With CSV format, expect 5-10x higher scanned data and costs.

---

## Summary

Athena's per-TB pricing makes it extremely cost-effective for benchmarking. The keys to success:

1. **Always use Parquet** (or ORC) format
2. **Set workgroup limits** to prevent runaway queries
3. **Partition large tables** by date columns
4. **Clean up S3 data** after testing

BenchBox handles format optimization, partitioning, and Glue Catalog integration. You focus on understanding Athena's query performance characteristics.

---

## References

[^1]: [Amazon Athena Pricing](https://aws.amazon.com/athena/pricing/) - AWS Documentation
[^2]: [Athena Workgroups](https://docs.aws.amazon.com/athena/latest/ug/workgroups.html) - AWS Documentation
[^3]: [Athena Performance Tuning](https://docs.aws.amazon.com/athena/latest/ug/performance-tuning.html) - AWS Documentation

---

*Questions or feedback? [Open an issue](https://github.com/oxbow-analytics/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: ~1,700
**Series**: free-trial-benchmarking
**Post Number**: 10
