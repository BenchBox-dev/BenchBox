# Free trial benchmarking: Starburst Galaxy

> Starburst Galaxy offers the most generous trial credits: $500 over 30 days. Here's how to use Trino compatibility for federated benchmarking.

**TL;DR**: Starburst Galaxy gives you $500 in credits over 30 days, the most generous of any platform. It runs Trino under the hood, so your queries work on open-source Trino too. Cluster-based billing means you pay while workers are running, not per query.

---

## What you get

**Trial details:**
- **Credits**: $500 (most generous)
- **Duration**: 30 days
- **Requirement**: Valid email address
- **Post-trial**: Falls back to Free plan (limited features)

**The Starburst Galaxy advantage:**

Starburst Galaxy is managed Trino, which means:
- SQL:2003 compliance, ANSI SQL syntax
- Query federation across data sources (S3, HDFS, databases)
- Same queries work on open-source Trino
- No lock-in: migrate to self-hosted Trino anytime

**Pricing model: Universal credits**

Starburst uses a "universal credit" model:
- Credits consumed based on cluster size and uptime
- Example: 2-worker cluster = ~12 credits/hour
- Specific $/credit rates vary by plan tier (contact sales for details)

**What happens when trial ends:**
Account transitions to Free plan with limited compute hours. Upgrade to paid plan for continued access.

---

## Explore with MCP

Before spending credits, use the MCP server to preview your benchmark runs:

**Validate configuration:**

> "Can I run TPC-H on Starburst with my current setup?"

The assistant calls `validate_config(platform="starburst", benchmark="tpch")` and reports any issues with your cluster configuration or credentials.

**Preview resource consumption:**

> "What would a TPC-H SF1 run on Starburst look like?"

```
# Example MCP dry_run response
Platform: Starburst Galaxy
Benchmark: TPC-H SF1
Estimated data size: ~1 GB
Tables: 8 (nation, region, part, supplier, partsupp, customer, orders, lineitem)
Queries: 22
Phases: load, power

Notes:
- Uses Trino SQL dialect
- Data can be loaded from S3, HDFS, or object storage
- Cluster runs while queries execute
- Estimated credits: varies by cluster size
```

**Check federation capabilities:**

> "What data sources can I connect to Starburst Galaxy?"

Starburst supports catalogs for:
- Object storage (S3, GCS, Azure Blob)
- Databases (PostgreSQL, MySQL, Oracle)
- Data lakes (Delta Lake, Iceberg, Hudi)
- And more

---

## The game plan

### Credit budget planning

With $500 in credits, you have substantial room for experimentation. Key insight: credits are consumed while clusters run, not per query.

| Cluster Size | Est. Credits/hour | Hours Available |
| ------------ | ----------------- | --------------- |
| 1 worker     | ~6                | ~83 hours       |
| 2 workers    | ~12               | ~42 hours       |
| 4 workers    | ~24               | ~21 hours       |

**Strategy**: Start with 1-2 workers, scale up only for larger benchmarks.

### Trino compatibility workflow

Since Starburst runs Trino, you can develop locally:

1. **Local Trino** (Docker): Develop and test queries (free)
2. **Starburst Galaxy**: Production-like benchmarking (credits)

```bash
# Run local Trino for development
docker run -d -p 8080:8080 --name trino trinodb/trino

# Connect with Trino CLI
docker exec -it trino trino
```

### The scaling progression

1. **SF0.01 with 1 worker**: Validate connectivity, schema, queries (~15 minutes)
2. **SF1 with 2 workers**: First meaningful benchmark (~1 hour)
3. **SF1 with 4 workers**: Compare worker scaling (~30 minutes)
4. **SF10 with 4 workers**: Larger data volume (~3-4 hours)

---

## BenchBox setup

### Install dependencies

```bash
uv add trino
```

BenchBox uses the standard Trino Python client.

### Configuration

BenchBox reads Starburst credentials from environment variables:

```bash
# Starburst Galaxy connection
export STARBURST_HOST="your-cluster.galaxy.starburst.io"
export STARBURST_PORT="443"
export STARBURST_USER="your-email@company.com"
export STARBURST_PASSWORD="your-password"

# Catalog and schema for benchmark tables
export STARBURST_CATALOG="benchbox"
export STARBURST_SCHEMA="tpch"
```

**Setting up a catalog:**

1. Starburst Galaxy UI → Catalogs → Create
2. Choose your storage backend (S3 recommended for benchmarking)
3. Configure access credentials
4. Note the catalog name for BenchBox

**Authentication options:**
- **Username/password**: Simplest for trials (shown above)
- **OAuth/OIDC**: For enterprise SSO integration
- **API tokens**: For programmatic access

### Verify connection

```bash
# Quick connectivity test
uv run python -c "
import trino
import os

conn = trino.dbapi.connect(
    host=os.environ['STARBURST_HOST'],
    port=int(os.environ.get('STARBURST_PORT', 443)),
    user=os.environ['STARBURST_USER'],
    http_scheme='https',
    auth=trino.auth.BasicAuthentication(
        os.environ['STARBURST_USER'],
        os.environ['STARBURST_PASSWORD']
    )
)
cursor = conn.cursor()
cursor.execute('SELECT current_user')
print('Connected to Starburst as:', cursor.fetchone()[0])
cursor.close()
conn.close()
"
```

---

## Running the benchmarks

### Step 1: Ensure cluster is running

Starburst Galaxy clusters can be stopped when idle. Start your cluster before benchmarking:

1. Galaxy UI → Clusters
2. Select your cluster → Start
3. Wait for "Running" status

### Step 2: Validate with SF0.01

```bash
benchbox run --platform starburst --benchmark tpch --scale 0.01
```

Expected output:
```
BenchBox v0.2.0
Platform: Starburst Galaxy
Benchmark: TPC-H SF0.01

[INFO] Generating data...
[INFO] Creating schema and loading data...
[INFO] Running power phase (22 queries)...
[SUCCESS] Completed in 8m 12s

Results saved to: benchmark_runs/results/tpch_sf001_starburst_20260131_143022.json
```

**What BenchBox does automatically:**
- Creates the benchmark schema in your catalog
- Generates TPC-H data and uploads to object storage
- Creates tables optimized for Trino
- Runs all 22 TPC-H queries
- Validates results against reference answers

### Step 3: Baseline at SF1

```bash
benchbox run --platform starburst --benchmark tpch --scale 1
```

Monitor your cluster during the run: Galaxy UI shows query progress and resource utilization.

### Step 4: Scale workers and compare

Add workers via Galaxy UI:
1. Clusters → Your cluster → Edit
2. Increase worker count
3. Apply changes (rolling restart)

Then re-run:
```bash
benchbox run --platform starburst --benchmark tpch --scale 1
```

### Running specific queries

```bash
# Run only the aggregation queries
benchbox run --platform starburst --benchmark tpch --scale 1 --queries Q1,Q3,Q5,Q10
```

---

## Reproducing and comparing

### Find your previous runs

> "Show me my recent Starburst benchmark runs"

Or via CLI:

```bash
ls -la benchmark_runs/results/ | grep starburst
```

### Compare worker configurations

> "Compare my 2-worker and 4-worker runs on Starburst"

```
Comparison: 2 workers vs 4 workers (SF1)

Overall:
- 2 workers total: 52m 30s
- 4 workers total: 28m 45s

Notable differences:
- Q21: 2w 12m, 4w 5m (2.4x faster)
- Q9: 2w 8m, 4w 3m 30s (2.3x faster)
- Q6: 2w 1m 20s, 4w 1m 10s (1.15x faster, not parallel)

Notes:
- Join-heavy queries scale better with more workers
- Simple scans show diminishing returns
- Double workers ≈ 1.8x speedup (not 2x due to overhead)
```

### Compare with local Trino

If you ran the same queries on local Trino:

> "Compare my Starburst and local Trino results"

---

## Trial traps to avoid

### 1. Forgetting clusters run continuously

**The trap**: Starting a cluster for benchmarking, then leaving it running for days. Credits consumed 24/7 while cluster is "Running."

**The fix**: Stop clusters when not in use:
- Galaxy UI → Clusters → Stop
- Or configure auto-stop after idle period

### 2. Over-provisioning workers

**The trap**: Starting with 8 workers "just to see," burning through credits quickly on small benchmarks.

**The fix**: Start with 1-2 workers. Add workers only when you see slow queries that could benefit from parallelism.

### 3. Not configuring catalog storage

**The trap**: Creating tables without understanding where data lands. Some catalog configurations charge for storage separately.

**The fix**: Use S3 or equivalent object storage with clear cost visibility. BenchBox uses your configured catalog for all tables.

### 4. Ignoring query history

**The trap**: Running benchmarks without capturing query plans or execution stats for later analysis.

**The fix**: Starburst Galaxy stores query history in the UI. Export or screenshot results you want to keep. BenchBox result files also capture timing data.

### 5. Missing Trino portability opportunity

**The trap**: Treating Starburst as a black box, not realizing queries work identically on open-source Trino.

**The fix**: Test queries locally first:
```bash
# Local Trino development (free)
docker run -d -p 8080:8080 trinodb/trino
```

### Cleanup checklist before trial ends

- [ ] Download result files from `benchmark_runs/results/`
- [ ] Export query history from Galaxy UI
- [ ] Stop all clusters (avoid charges on last day)
- [ ] Note effective cluster sizes for different scale factors
- [ ] Document any Trino-specific query patterns

---

## Credit consumption reference

Based on our testing with 2-worker clusters:

| Scale Factor | Est. Time | Est. Credits |
| ------------ | --------- | ------------ |
| SF0.01       | ~10 min   | ~2           |
| SF1          | ~1 hour   | ~12          |
| SF10         | ~4 hours  | ~48          |

Actual credit consumption depends on your cluster configuration and Starburst's current pricing. Monitor usage in Galaxy UI.

---

## Summary

Starburst Galaxy's $500 trial is the most generous, and its Trino foundation provides portability. The keys to success:

1. **Stop clusters when idle** (they consume credits continuously)
2. **Start with small clusters** (1-2 workers for most benchmarks)
3. **Use Trino compatibility** (develop locally, benchmark in Galaxy)
4. **Monitor credit consumption** in Galaxy UI

BenchBox handles Trino dialect, catalog configuration, and query validation. You focus on understanding Starburst's scaling characteristics.

---

## References

[^1]: [Starburst Pricing](https://www.starburst.io/pricing/) - Starburst Documentation
[^2]: [Starburst Billing Basics](https://docs.starburst.io/starburst-galaxy/cluster-administration/monitor-and-manage-cost-and-performance/billing-basics.html) - Starburst Documentation

---

*Questions or feedback? [Open an issue](https://github.com/oxbow-analytics/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: ~1,600
**Series**: free-trial-benchmarking
**Post Number**: 6
