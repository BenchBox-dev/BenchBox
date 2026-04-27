# Free trial benchmarking: BigQuery

> BigQuery offers something no other platform does: a permanent free tier. Here's how to run TPC-H benchmarks with $300 in trial credits plus 1 TB of queries per month, forever.

**TL;DR**: BigQuery gives you $300 in GCP credits (90 days) plus a permanent free tier of 1 TB queries per month. The per-TB pricing model means query complexity matters more than warehouse sizing. LIMIT clauses don't reduce costs. Partitioning and clustering can cut costs 30-90%.

---

## What you get

**Trial details:**
- **Trial credits**: $300 (shared across all GCP services)
- **Trial duration**: 90 days
- **Free tier**: 1 TB queries/month (permanent, no expiration)
- **Free storage**: 10 GB/month (permanent)
- **Credit card**: Not required for Sandbox

**The unique BigQuery advantage:**

Unlike credit-limited trials that expire, BigQuery's free tier continues indefinitely. This means:
- Run monthly benchmarks to track BigQuery version performance over time
- No pressure to rush evaluation
- Ongoing testing at SF0.01-SF1 without cost
- Sandbox mode available without credit card

**Sandbox limitations:**

| Feature               | Sandbox             | Paid (Free Tier)             |
| --------------------- | ------------------- | ---------------------------- |
| Query processing      | 1 TB/month          | 1 TB/month free, then billed |
| Storage               | 10 GB               | 10 GB free, then billed      |
| Table expiration      | 60 days auto-delete | Configurable                 |
| Streaming inserts     | No                  | Yes                          |
| DML statements        | No                  | Yes                          |
| Data Transfer Service | No                  | Yes                          |

For benchmarking, the main Sandbox limitation is the 60-day table expiration. Plan to regenerate data if you want to benchmark over longer periods.

**What happens when trial ends:**
The $300 credits expire after 90 days, but the free tier continues. You can keep running 1 TB of queries per month indefinitely.

---

## Explore with MCP

Before spending query budget, use the MCP server to preview your benchmark runs:

**Validate configuration:**

> "Can I run TPC-H on BigQuery with my current setup?"

The assistant calls `validate_config(platform="bigquery", benchmark="tpch")` and reports any issues with your GCP project or authentication.

**Preview resource consumption:**

> "What would a TPC-H SF1 run on BigQuery look like?"

```
# Example MCP dry_run response
Platform: BigQuery
Benchmark: TPC-H SF1
Estimated data size: ~1 GB
Estimated bytes scanned: ~1 TB across 22 queries
Tables: 8 (nation, region, part, supplier, partsupp, customer, orders, lineitem)
Queries: 22
Phases: load, power

Notes:
- BigQuery charges per TB scanned ($6.25/TB on-demand)
- SF1 queries typically scan 20-100 GB each
- Full TPC-H run: ~$6-8 at on-demand pricing
- Partitioning/clustering can reduce this 30-90%
```

**Estimate costs before running:**

> "How much would TPC-H at SF10 cost on BigQuery?"

The MCP server can estimate bytes scanned and resulting costs based on table sizes and query patterns.

---

## The game plan

### Understanding BigQuery's pricing model

BigQuery charges per TB of data scanned, not per compute time. This means:

- **Query complexity doesn't matter**: A 10-second query and a 10-minute query scanning the same data cost the same
- **Data size matters**: SF10 costs roughly 10x more than SF1
- **LIMIT clauses don't help**: BigQuery scans full partitions regardless of LIMIT
- **Column selection matters**: SELECT * costs more than SELECT specific_columns
- **Partitioning and clustering help**: Can reduce scanned data 30-90%

**Pricing:**
- On-demand: $6.25 per TB scanned
- First 1 TB/month: Free
- Minimum charge per query: 10 MB per table referenced

### Staying within free tier

With 1 TB free per month, here's what you can run:

| Scale Factor | Est. TB Scanned (full run) | Runs per Month (free tier) |
| ------------ | -------------------------- | -------------------------- |
| SF0.01       | ~0.01 TB                   | ~100 runs                  |
| SF1          | ~1 TB                      | ~1 run                     |
| SF10         | ~10 TB                     | Trial credits only         |

**Strategy**: Develop and validate at SF0.01 (essentially unlimited runs), then use trial credits for SF1+ runs.

### The scaling progression

1. **SF0.01 in Sandbox**: Validate connectivity, schema, queries (free tier covers this easily)
2. **SF1 in paid project**: First meaningful benchmark (~$6-8 with trial credits)
3. **SF1 with optimization**: Apply partitioning/clustering, measure improvement
4. **SF10 with optimization**: Larger scale, still cost-effective with optimization

---

## BenchBox setup

### Install dependencies

```bash
uv add google-cloud-bigquery google-cloud-storage
```

### Configuration

BenchBox reads BigQuery credentials from environment variables:

```bash
# GCP project for benchmarking
export GCP_PROJECT_ID="your-project-id"

# Dataset for benchmark tables
export BIGQUERY_DATASET="benchbox"

# Optional: specify location
export BIGQUERY_LOCATION="US"

# Authentication (one of these methods)
# Method 1: Application Default Credentials
gcloud auth application-default login

# Method 2: Service account key
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
```

**Setting up a project for benchmarking:**

1. Create a new GCP project (keeps benchmark costs isolated)
2. Enable BigQuery API
3. Create a dataset for benchmark tables
4. Set up authentication (ADC or service account)

### Verify connection

```bash
# Quick connectivity test
uv run python -c "
from google.cloud import bigquery
import os

client = bigquery.Client(project=os.environ['GCP_PROJECT_ID'])
print('Connected to BigQuery project:', client.project)

# Check dataset exists or create it
dataset_id = os.environ.get('BIGQUERY_DATASET', 'benchbox')
dataset_ref = client.dataset(dataset_id)
try:
    client.get_dataset(dataset_ref)
    print('Dataset exists:', dataset_id)
except:
    print('Dataset not found, will be created during benchmark')
"
```

---

## Running the benchmarks

### Step 1: Validate with SF0.01

```bash
benchbox run --platform bigquery --benchmark tpch --scale 0.01
```

Expected output:
```
BenchBox v0.2.0
Platform: BigQuery (your-project-id)
Benchmark: TPC-H SF0.01

[INFO] Generating data...
[INFO] Creating schema and loading data...
[INFO] Running power phase (22 queries)...
[SUCCESS] Completed in 8m 45s

Bytes scanned: 12.3 GB
Estimated cost: $0.08 (within free tier)

Results saved to: benchmark_runs/results/tpch_sf001_bigquery_20260131_143022.json
```

**What BenchBox does automatically:**
- Creates the benchmark dataset
- Generates TPC-H data and loads to Cloud Storage
- Creates BigQuery tables with appropriate partitioning
- Applies clustering keys for common query patterns
- Runs all 22 TPC-H queries
- Reports bytes scanned and estimated cost
- Validates results against reference answers

### Step 2: Baseline at SF1

```bash
benchbox run --platform bigquery --benchmark tpch --scale 1
```

This typically scans ~1 TB across all 22 queries. With the free tier, your first run is free; subsequent SF1 runs in the same month consume trial credits.

### Step 3: Monitor bytes scanned

BigQuery reports bytes scanned per query. BenchBox captures this in the result file:

```bash
# View per-query costs from results
uv run python -c "
import json
with open('benchmark_runs/results/tpch_sf1_bigquery_20260131_143022.json') as f:
    results = json.load(f)
for q in results['queries']:
    tb = q.get('bytes_scanned', 0) / 1e12
    cost = tb * 6.25
    print(f\"{q['query_id']}: {tb:.2f} TB, \${cost:.2f}\")
"
```

### Running specific queries

```bash
# Run only the aggregation-heavy queries
benchbox run --platform bigquery --benchmark tpch --scale 1 --queries Q1,Q6,Q14,Q19
```

This can significantly reduce bytes scanned for targeted analysis.

---

## Reproducing and comparing

### Find your previous runs

> "Show me my recent BigQuery benchmark runs"

Or via CLI:

```bash
ls -la benchmark_runs/results/ | grep bigquery
```

### Analyze cost efficiency

> "Which TPC-H queries scan the most data on BigQuery?"

```
Bytes scanned by query (SF1):

Most expensive:
- Q9: 180 GB (product type profit, joins all tables)
- Q21: 165 GB (suppliers who kept orders waiting)
- Q5: 142 GB (local supplier volume)

Most efficient:
- Q6: 45 GB (simple scan with predicates)
- Q1: 52 GB (aggregation on lineitem)
- Q14: 58 GB (promotion effect)

Optimization opportunity:
- Partitioning lineitem by l_shipdate could reduce Q6 by ~80%
- Clustering orders by o_orderdate helps date-range queries
```

### Compare with and without optimization

If you run benchmarks before and after applying partitioning/clustering:

> "Compare my optimized and unoptimized BigQuery runs"

---

## Trial traps to avoid

### 1. Thinking LIMIT reduces cost

**The trap**: Adding `LIMIT 100` to a query and expecting to scan less data. BigQuery scans full partitions regardless of LIMIT.

```sql
-- Both queries cost the same!
SELECT * FROM lineitem LIMIT 100;
SELECT * FROM lineitem;
```

**The fix**: Use WHERE clauses on partitioned columns to reduce scanned data, not LIMIT.

### 2. Using SELECT *

**The trap**: Selecting all columns when you only need a few. BigQuery is columnar; unused columns cost money.

**The fix**: BenchBox's TPC-H queries select only needed columns. For ad-hoc queries, be explicit about columns.

### 3. Forgetting trial credits are GCP-wide

**The trap**: Using other GCP services (Compute Engine, Cloud Storage, etc.) and finding benchmark budget depleted.

**The fix**: Create a dedicated GCP project for benchmarking. Monitor usage at the project level. BigQuery free tier (1 TB/month) is separate from the $300 trial credit.

### 4. Not using partitioning

**The trap**: Creating unpartitioned tables, then scanning all data for every query.

**The fix**: BenchBox partitions large tables (lineitem, orders) by date columns automatically. For manual tables:

```sql
CREATE TABLE lineitem
PARTITION BY DATE(l_shipdate)
CLUSTER BY l_orderkey
AS SELECT * FROM source_table;
```

### 5. Cross-region queries

**The trap**: Storing data in one region and querying from another, incurring egress costs.

**The fix**: Keep data and queries in the same region. BenchBox uses the location specified in `BIGQUERY_LOCATION`.

### Cleanup checklist before trial ends

Note: BigQuery's free tier continues after trial credits expire, so cleanup is less urgent than other platforms.

- [ ] Download result files from `benchmark_runs/results/`
- [ ] Note which queries benefit most from partitioning/clustering
- [ ] Document bytes scanned per scale factor
- [ ] Consider keeping Sandbox access for ongoing SF0.01 testing
- [ ] Delete large (SF10+) tables to stay within free storage

---

## Cost reference

Based on our testing with default BenchBox table configurations:

| Scale Factor | Total Bytes Scanned | On-Demand Cost | Free Tier?            |
| ------------ | ------------------- | -------------- | --------------------- |
| SF0.01       | ~12 GB              | $0.08          | Yes (100+ runs/month) |
| SF1          | ~1 TB               | ~$6.25         | Yes (1 run/month)     |
| SF10         | ~10 TB              | ~$62.50        | No (trial credits)    |
| SF100        | ~100 TB             | ~$625          | No (trial credits)    |

With optimized partitioning and clustering, costs can be reduced 30-90% depending on query patterns.

---

## Summary

BigQuery's permanent free tier makes it unique among cloud analytics platforms. The keys to success:

1. **Understand per-TB pricing**: Cost is about data scanned, not compute time
2. **Use the free tier strategically**: SF0.01 for development, SF1 occasionally
3. **Partition and cluster tables**: Can reduce costs 30-90%
4. **Don't rely on LIMIT**: Use WHERE on partitioned columns instead

BenchBox handles partitioning decisions, cost tracking, and query validation. You focus on understanding BigQuery's cost/performance characteristics.

---

## References

[^1]: [Google Cloud Free](https://cloud.google.com/free) - Google Cloud Documentation
[^2]: [BigQuery Pricing](https://cloud.google.com/bigquery/pricing) - Google Cloud Documentation
[^3]: [BigQuery Sandbox](https://cloud.google.com/bigquery/docs/sandbox) - Google Cloud Documentation
[^4]: [BigQuery Cost Best Practices](https://cloud.google.com/bigquery/docs/best-practices-costs) - Google Cloud Documentation

---

*Questions or feedback? [Open an issue](https://github.com/oxbow-analytics/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: ~1,900
**Series**: free-trial-benchmarking
**Post Number**: 3
