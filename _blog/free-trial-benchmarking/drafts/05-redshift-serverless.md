# Free trial benchmarking: Redshift Serverless

> Redshift Serverless offers the longest trial window: 90 days with $300 in credits. Here's how to run methodical benchmarks without the time pressure of shorter trials.

**TL;DR**: Redshift Serverless gives you $300 over 90 days, the longest runway of any credit-based trial. RPU (Redshift Processing Unit) pricing varies by region ($0.36-$0.60/RPU-hour). Open transactions consume RPUs even when idle. Configure usage limits immediately.

---

## What you get

**Trial details:**
- **Credits**: $300
- **Duration**: 90 days (longest credit-based trial)
- **Eligibility**: First-time Redshift Serverless users only
- **Requirement**: AWS account (separate from AWS Free Tier)

**The Redshift Serverless advantage:**

With 90 days instead of 14-30, you can:
- Take time to learn the platform before heavy benchmarking
- Run benchmarks at different times to observe variance
- Test multiple configurations systematically
- Not feel rushed to cram everything into two weeks

**Pricing model: RPU-hours**

RPU = Redshift Processing Unit (16 GB memory each)

| Region           | RPU-hour Rate |
| ---------------- | ------------- |
| US East (Ohio)   | $0.36         |
| US West (Oregon) | $0.36         |
| EU (Ireland)     | $0.45         |
| SA (São Paulo)   | $0.60         |

Per-second billing with 60-second minimum per startup.

**What happens when trial ends:**
Billing converts to pay-as-you-go if usage limits aren't set to stop queries. Otherwise, queries are blocked until billing is configured.

---

## Explore with MCP

Before spending RPU-hours, use the MCP server to preview your benchmark runs:

**Validate configuration:**

> "Can I run TPC-H on Redshift with my current setup?"

The assistant calls `validate_config(platform="redshift", benchmark="tpch")` and reports any issues with your workgroup configuration or credentials.

**Preview resource consumption:**

> "What would a TPC-H SF1 run on Redshift Serverless look like?"

```
# Example MCP dry_run response
Platform: Redshift Serverless
Benchmark: TPC-H SF1
Estimated data size: ~1 GB
Tables: 8 (nation, region, part, supplier, partsupp, customer, orders, lineitem)
Queries: 22
Phases: load, power

Notes:
- Default capacity: 128 RPU (adjustable 8-512)
- Data loaded from S3 via COPY
- Estimated run time: 30-60 minutes
- Estimated cost: $1-3 depending on RPU capacity
```

**Check capacity settings:**

> "What RPU capacity should I use for TPC-H benchmarking?"

For trial benchmarking:
- 8 RPU: Minimum, slowest but most cost-effective
- 32 RPU: Good balance for SF1-SF10
- 128 RPU (default): Fast but burns credits quickly

---

## The game plan

### 90-day evaluation strategy

Unlike rushed 14-day trials, you can pace yourself:

| Week | Activity                                  | Est. RPU-hours |
| ---- | ----------------------------------------- | -------------- |
| 1-2  | Setup, learn console, SF0.01 validation   | 2-5            |
| 3-4  | SF1 baseline runs at different capacities | 10-20          |
| 5-6  | SF10 runs, scaling experiments            | 20-40          |
| 7-8  | Specific query analysis, tuning           | 10-20          |
| 9-12 | Buffer, advanced testing                  | Remaining      |

This leaves substantial credits for exploration and ensures you're not rushed.

### Understanding RPU capacity

| Capacity | Cost/hour | Use Case                      |
| -------- | --------- | ----------------------------- |
| 8 RPU    | $2.88     | Minimum for testing           |
| 32 RPU   | $11.52    | Development, small benchmarks |
| 128 RPU  | $46.08    | Production-like testing       |
| 512 RPU  | $184.32   | Maximum concurrency testing   |

**Cost calculation:**
```
Cost = (elapsed_time_seconds / 3600) × RPU × rate
Example: 10-minute query at 8 RPU = (600/3600) × 8 × $0.36 = $0.48
```

### The scaling progression

1. **SF0.01 at 8 RPU**: Validate connectivity, schema creation (10-15 minutes, ~$0.50)
2. **SF1 at 8 RPU**: Baseline benchmark (1-2 hours, ~$3-6)
3. **SF1 at 32 RPU**: Compare capacity impact (30-60 minutes, ~$6-12)
4. **SF10 at 32 RPU**: Larger data volume (2-4 hours, ~$25-50)

---

## BenchBox setup

### Install dependencies

```bash
uv add redshift-connector boto3
```

### Configuration

BenchBox reads Redshift credentials from environment variables:

```bash
# Redshift Serverless workgroup
export REDSHIFT_HOST="your-workgroup.123456789012.us-east-1.redshift-serverless.amazonaws.com"
export REDSHIFT_DATABASE="dev"
export REDSHIFT_USER="admin"
export REDSHIFT_PASSWORD="your-password"

# AWS credentials for S3 data loading
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_REGION="us-east-1"

# S3 bucket for staging data (required for COPY)
export REDSHIFT_S3_BUCKET="your-benchmark-bucket"
```

**Finding your workgroup endpoint:**
1. AWS Console → Amazon Redshift → Serverless dashboard
2. Select your workgroup
3. Copy the "Endpoint" from Workgroup configuration

**Creating an S3 bucket for data staging:**
Redshift loads data via COPY from S3. Create a bucket in the same region as your workgroup:
```bash
aws s3 mb s3://your-benchmark-bucket --region us-east-1
```

### Verify connection

```bash
# Quick connectivity test
uv run python -c "
import redshift_connector
import os

conn = redshift_connector.connect(
    host=os.environ['REDSHIFT_HOST'],
    database=os.environ['REDSHIFT_DATABASE'],
    user=os.environ['REDSHIFT_USER'],
    password=os.environ['REDSHIFT_PASSWORD']
)
cursor = conn.cursor()
cursor.execute('SELECT current_database()')
print('Connected to Redshift:', cursor.fetchone()[0])
cursor.close()
conn.close()
"
```

---

## Running the benchmarks

### Step 1: Configure usage limits (do this first!)

Before running benchmarks, set usage limits to avoid surprise charges:

```sql
-- Via Redshift console or SQL
-- Set daily limit of 10 RPU-hours (~$3.60)
CREATE USAGE LIMIT daily_limit
ON SERVERLESS WORKGROUP your_workgroup
LIMIT 10 DAILY
ACTION log;  -- or 'alert' or 'disable'
```

Or via AWS Console:
1. Redshift → Serverless dashboard → Limits
2. Create limit: Daily, 10 RPU-hours, Action: Disable queries

### Step 2: Validate with SF0.01

```bash
benchbox run --platform redshift --benchmark tpch --scale 0.01
```

Expected output:
```
BenchBox v0.2.0
Platform: Redshift Serverless (your-workgroup)
Benchmark: TPC-H SF0.01

[INFO] Generating data...
[INFO] Uploading to S3...
[INFO] Creating schema and loading via COPY...
[INFO] Running power phase (22 queries)...
[SUCCESS] Completed in 15m 23s

Results saved to: benchmark_runs/results/tpch_sf001_redshift_20260131_143022.json
```

**What BenchBox does automatically:**
- Generates TPC-H data locally
- Uploads to your S3 bucket
- Creates Redshift tables with sort keys and distribution keys
- Loads data via COPY
- Runs all 22 TPC-H queries
- Validates results against reference answers

### Step 3: Baseline at SF1

```bash
benchbox run --platform redshift --benchmark tpch --scale 1
```

This takes 1-2 hours at 8 RPU capacity. Monitor your usage limits.

### Step 4: Adjust capacity and compare

Change capacity via console or SQL:
```sql
ALTER WORKGROUP your_workgroup SET BASE_CAPACITY TO 32;
```

Then re-run:
```bash
benchbox run --platform redshift --benchmark tpch --scale 1
```

### Running specific queries

```bash
# Run only the join-heavy queries
benchbox run --platform redshift --benchmark tpch --scale 1 --queries Q2,Q9,Q21
```

---

## Reproducing and comparing

### Find your previous runs

> "Show me my recent Redshift benchmark runs"

Or via CLI:

```bash
ls -la benchmark_runs/results/ | grep redshift
```

### Compare capacity configurations

> "Compare my 8 RPU and 32 RPU runs on Redshift"

```
Comparison: 8 RPU vs 32 RPU (SF1)

Overall:
- 8 RPU total: 1h 45m, cost ~$5.04
- 32 RPU total: 38m, cost ~$7.30

Notable differences:
- Q21: 8 RPU 18m, 32 RPU 4m (4.5x faster)
- Q9: 8 RPU 12m, 32 RPU 3m (4x faster)
- Q6: 8 RPU 45s, 32 RPU 20s (2.25x faster)

Cost efficiency:
- 8 RPU: slower but cheaper per run
- 32 RPU: faster but 45% more expensive
```

### Monitor trial credit consumption

Via AWS Console:
1. Redshift → Serverless dashboard → Usage
2. View RPU-hours consumed and estimated cost

---

## Trial traps to avoid

### 1. Open transactions consuming RPUs

**The trap**: Starting a transaction (BEGIN) and forgetting to COMMIT or ROLLBACK. Open transactions keep the serverless endpoint warm, consuming RPUs indefinitely.

**The fix**: Always close transactions. BenchBox does this automatically. For manual queries:
```sql
-- Always end with
COMMIT;
-- or
ROLLBACK;
```

Check for open transactions:
```sql
SELECT * FROM stv_inflight WHERE status = 'Running';
```

### 2. Not setting usage limits

**The trap**: Default configuration has no limits. A runaway query or forgotten connection can burn through credits quickly.

**The fix**: Set usage limits immediately after workgroup creation:
```sql
CREATE USAGE LIMIT daily_limit
ON SERVERLESS WORKGROUP your_workgroup
LIMIT 10 DAILY
ACTION disable;  -- Hard stop when exceeded
```

### 3. Choosing expensive regions

**The trap**: Creating workgroup in São Paulo ($0.60/RPU-hr) instead of US East ($0.36/RPU-hr). 67% cost difference for identical benchmarks.

**The fix**: Use US East (Ohio) for benchmarking unless you have latency requirements.

### 4. Using default 128 RPU capacity

**The trap**: Default capacity of 128 RPU burns credits fast: $46/hour. A failed benchmark run can cost $20+ before you notice.

**The fix**: Start with 8 or 32 RPU:
```sql
ALTER WORKGROUP your_workgroup SET BASE_CAPACITY TO 8;
```

### 5. Concurrency scaling charges

**The trap**: Concurrency scaling (automatically adding capacity for concurrent queries) is billed separately and can exceed base usage.

**The fix**: For benchmarking (single-user), disable concurrency scaling:
```sql
ALTER WORKGROUP your_workgroup SET MAX_CAPACITY TO BASE;
```

### Cleanup checklist before trial ends

- [ ] Download result files from `benchmark_runs/results/`
- [ ] Export query performance insights from console
- [ ] Delete S3 staging data to avoid storage charges
- [ ] Note effective capacity settings for different scale factors
- [ ] Set usage limits to $0 if not continuing (prevents charges)

---

## RPU consumption reference

Based on our testing at 8 RPU base capacity:

| Scale Factor | Load Time | Query Time | Total Time | Est. Cost (US East) |
| ------------ | --------- | ---------- | ---------- | ------------------- |
| SF0.01       | ~5 min    | ~10 min    | ~15 min    | ~$0.72              |
| SF1          | ~20 min   | ~90 min    | ~2 hours   | ~$5.76              |
| SF10         | ~60 min   | ~6 hours   | ~7 hours   | ~$20.16             |

Costs scale linearly with RPU capacity. At 32 RPU, expect 4x the cost but 2-3x faster completion.

---

## Summary

Redshift Serverless' 90-day window removes the time pressure of shorter trials. The keys to success:

1. **Configure usage limits immediately** (before any benchmarking)
2. **Start with low RPU capacity** (8-32 RPU for trials)
3. **Choose US East region** for lowest costs
4. **Watch for open transactions** (they consume RPUs while idle)

BenchBox handles S3 staging, COPY operations, sort/distribution key configuration, and query validation. You focus on understanding Redshift's scaling characteristics.

---

## References

[^1]: [Redshift Free Trial](https://aws.amazon.com/redshift/free-trial/) - AWS Documentation
[^2]: [Redshift Serverless Billing](https://docs.aws.amazon.com/redshift/latest/mgmt/serverless-billing.html) - AWS Documentation
[^3]: [Redshift Usage Limits](https://docs.aws.amazon.com/redshift/latest/mgmt/serverless-workgroup-max-rpu.html) - AWS Documentation

---

*Questions or feedback? [Open an issue](https://github.com/oxbow-analytics/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: ~1,900
**Series**: free-trial-benchmarking
**Post Number**: 5
