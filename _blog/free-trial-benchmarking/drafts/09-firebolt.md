# Free trial benchmarking: Firebolt

> Firebolt offers $200 in credits over 30 days for sub-second analytics. Here's how to understand the FBU system and run meaningful benchmarks.

**TL;DR**: Firebolt gives you $200 over 30 days with per-second billing while engines run. The FBU (Firebolt Unit) system requires understanding before starting: S nodes = 8 FBU, M nodes = 16 FBU. All node types available during trial.

---

## What you get

**Trial details:**
- **Credits**: $200
- **Duration**: 30 days
- **Credit card**: Not required
- **Node types**: All available (S, M, L, XL)

**The Firebolt value proposition:**

Firebolt focuses on sub-second analytics:
- Sparse indexes for fast data pruning
- Join indexes for accelerated joins
- F3 storage format optimized for analytics
- Sub-second latency on typical BI queries

**Pricing model: FBU (Firebolt Units)**

FBU is a normalized compute unit:

| Node Type        | FBU per Node | Typical Use                   |
| ---------------- | ------------ | ----------------------------- |
| S (Small)        | 8 FBU        | Development, small benchmarks |
| M (Medium)       | 16 FBU       | Production-like testing       |
| L (Large)        | 32 FBU       | Large scale benchmarks        |
| XL (Extra Large) | 64 FBU       | Maximum performance           |

Per-second billing while engine is running.

**Cost calculation:**
```
Compute Cost = query_time_seconds × (fbu_rate/3600) × total_fbu
total_fbu = fbu_per_node × cluster_size
```

**What happens when trial ends:**
Credits expire. Configure billing to continue, or engine access suspends.

---

## Explore with MCP

Before spending credits, use the MCP server to preview your benchmark runs:

**Validate configuration:**

> "Can I run TPC-H on Firebolt with my current setup?"

The assistant calls `validate_config(platform="firebolt", benchmark="tpch")` and reports any issues with your engine configuration or credentials.

**Preview resource consumption:**

> "What would a TPC-H SF1 run on Firebolt look like?"

```
# Example MCP dry_run response
Platform: Firebolt
Benchmark: TPC-H SF1
Estimated data size: ~1 GB
Tables: 8 (nation, region, part, supplier, partsupp, customer, orders, lineitem)
Queries: 22
Phases: load, power

Notes:
- Uses Firebolt-optimized table definitions with indexes
- Per-second billing while engine runs
- Estimated run time: 20-40 minutes on S node
- Engine should be stopped after benchmark completes
```

**Understand FBU pricing:**

> "How much does an S node cost per hour on Firebolt?"

FBU rates vary by region. Check Firebolt pricing page for current rates. Example calculation:
- S node = 8 FBU
- If $0.10/FBU-hour, S node = $0.80/hour

---

## The game plan

### Understanding FBU before starting

Unlike simpler pricing models, Firebolt's FBU system requires upfront understanding:

1. **FBU is the unit**: All billing is in FBU-hours
2. **Nodes have fixed FBU**: S=8, M=16, L=32, XL=64
3. **Clusters multiply**: 2× S nodes = 16 FBU
4. **Region affects rate**: US vs. non-US pricing differs

### Credit budget planning

With $200 and typical FBU rates:

| Node Config   | Est. $/hour | Hours Available |
| ------------- | ----------- | --------------- |
| 1× S (8 FBU)  | ~$0.80      | ~250 hours      |
| 1× M (16 FBU) | ~$1.60      | ~125 hours      |
| 2× S (16 FBU) | ~$1.60      | ~125 hours      |
| 1× L (32 FBU) | ~$3.20      | ~62 hours       |

**Strategy**: Start with S nodes, scale up only when needed.

### The scaling progression

1. **SF0.01 on 1× S node**: Validate connectivity, schema, queries (~10 minutes)
2. **SF1 on 1× S node**: First meaningful benchmark (~30 minutes)
3. **SF1 on 1× M node**: Compare node size impact (~20 minutes)
4. **SF10 on 1× M node**: Larger data volume (~2 hours)

Always stop engines between sessions.

---

## BenchBox setup

### Install dependencies

```bash
uv add firebolt-sdk
```

### Configuration

BenchBox reads Firebolt credentials from environment variables:

```bash
# Firebolt account
export FIREBOLT_CLIENT_ID="your-client-id"
export FIREBOLT_CLIENT_SECRET="your-client-secret"

# Database and engine
export FIREBOLT_DATABASE="benchbox"
export FIREBOLT_ENGINE="benchbox_engine"
export FIREBOLT_ACCOUNT="your-account-name"
```

**Setting up authentication:**

1. Firebolt console → Settings → Service accounts
2. Create a service account
3. Generate client ID and secret
4. Note your account name from the console URL

**Creating an engine:**

1. Firebolt console → Engines → Create
2. Name: `benchbox_engine`
3. Start with S node type, 1 node
4. Region: Match your data location

### Verify connection

```bash
# Quick connectivity test
uv run python -c "
from firebolt.db import connect
from firebolt.client.auth import ClientCredentials
import os

credentials = ClientCredentials(
    client_id=os.environ['FIREBOLT_CLIENT_ID'],
    client_secret=os.environ['FIREBOLT_CLIENT_SECRET']
)

connection = connect(
    auth=credentials,
    account_name=os.environ['FIREBOLT_ACCOUNT'],
    database=os.environ['FIREBOLT_DATABASE'],
    engine_name=os.environ['FIREBOLT_ENGINE']
)

cursor = connection.cursor()
cursor.execute('SELECT 1')
print('Connected to Firebolt:', cursor.fetchone())
cursor.close()
connection.close()
"
```

---

## Running the benchmarks

### Step 1: Start your engine

Firebolt engines must be running to execute queries:

1. Firebolt console → Engines
2. Select `benchbox_engine` → Start
3. Wait for "Running" status

Or via SQL:
```sql
START ENGINE benchbox_engine;
```

### Step 2: Validate with SF0.01

```bash
benchbox run --platform firebolt --benchmark tpch --scale 0.01
```

Expected output:
```
BenchBox v0.2.0
Platform: Firebolt
Benchmark: TPC-H SF0.01

[INFO] Generating data...
[INFO] Creating schema and loading data...
[INFO] Running power phase (22 queries)...
[SUCCESS] Completed in 6m 12s

Results saved to: benchmark_runs/results/tpch_sf001_firebolt_20260131_143022.json
```

**What BenchBox does automatically:**
- Creates the benchmark database
- Generates TPC-H data and uploads to S3 (or cloud storage)
- Creates Firebolt tables with appropriate indexes
- Runs all 22 TPC-H queries
- Validates results against reference answers

### Step 3: Stop engine, review results

After validation, stop the engine to preserve credits:

```sql
STOP ENGINE benchbox_engine;
```

Or via Firebolt console.

### Step 4: Baseline at SF1

Start engine, run benchmark, stop engine:

```bash
# Via console: Start engine
benchbox run --platform firebolt --benchmark tpch --scale 1
# Via console: Stop engine
```

### Running specific queries

```bash
# Run only join-heavy queries
benchbox run --platform firebolt --benchmark tpch --scale 1 --queries Q2,Q8,Q9,Q21
```

---

## Reproducing and comparing

### Find your previous runs

> "Show me my recent Firebolt benchmark runs"

Or via CLI:

```bash
ls -la benchmark_runs/results/ | grep firebolt
```

### Analyze Firebolt performance characteristics

> "Which TPC-H queries ran fastest on Firebolt?"

```
TPC-H SF1 on Firebolt (1× S node)

Fastest queries:
- Q6: 0.5s (simple aggregation, sparse index pruning)
- Q1: 0.8s (aggregation with grouping)
- Q14: 1.2s (promotion effect)

Slowest queries:
- Q21: 35s (correlated subquery)
- Q2: 28s (minimum cost supplier)
- Q9: 25s (product type profit)

Notes:
- Firebolt excels at selective queries (sparse indexes)
- Join-heavy queries benefit from join indexes
- Sub-second latency achieved on multiple queries
```

### Compare node configurations

> "Compare my S node and M node runs on Firebolt"

---

## Trial traps to avoid

### 1. Not understanding FBU before starting

**The trap**: Assuming pricing is simple per-hour, then being surprised by FBU calculations.

**The fix**: Calculate expected costs before spinning up nodes:
```
Expected cost = hours × FBU_per_node × $/FBU-hour
```

### 2. Leaving engines running

**The trap**: Starting an engine for benchmarking, forgetting to stop it. Per-second billing continues indefinitely.

**The fix**: Always stop engines after benchmarks:
```sql
STOP ENGINE benchbox_engine;
```
Or use Firebolt console to verify engine status.

### 3. Starting with large nodes

**The trap**: Spinning up L or XL nodes "to see maximum performance." Burns through credits quickly.

**The fix**: Start with S nodes. They're sufficient for SF1-SF10 benchmarks and cost 4-8x less than larger nodes.

### 4. Regional pricing differences

**The trap**: Creating resources in a more expensive region without realizing FBU rates differ.

**The fix**: Check Firebolt pricing page for regional rates. US regions are typically cheapest.

### 5. Not using Firebolt indexes

**The trap**: Creating basic tables without sparse indexes or join indexes, missing Firebolt's key optimization.

**The fix**: BenchBox applies Firebolt-optimized table definitions automatically. For manual tables:
```sql
CREATE TABLE lineitem (
    ...
) PRIMARY INDEX l_orderkey
PARTITION BY EXTRACT(YEAR FROM l_shipdate);
```

### Cleanup checklist before trial ends

- [ ] Stop all engines
- [ ] Download result files from `benchmark_runs/results/`
- [ ] Note effective node configurations for different scale factors
- [ ] Document Firebolt-specific optimizations that helped
- [ ] Decide: configure billing or let trial expire

---

## FBU consumption reference

Based on our testing with S nodes (8 FBU):

| Scale Factor | Est. Time | Est. FBU-hours | Est. Cost* |
| ------------ | --------- | -------------- | ---------- |
| SF0.01       | ~10 min   | ~1.3           | ~$0.13     |
| SF1          | ~30 min   | ~4             | ~$0.40     |
| SF10         | ~3 hours  | ~24            | ~$2.40     |

*Assuming ~$0.10/FBU-hour. Actual rates vary by region and plan.

---

## Summary

Firebolt's FBU system requires understanding before you start, but the trial gives you access to all node types. The keys to success:

1. **Understand FBU math** before spinning up nodes
2. **Start with S nodes** (8 FBU) for cost-effective benchmarking
3. **Stop engines immediately** after each session
4. **Use Firebolt indexes** for best performance

BenchBox handles Firebolt-optimized table definitions, index configuration, and query validation. You focus on understanding Firebolt's sub-second analytics capabilities.

---

## References

[^1]: [Firebolt Pricing](https://www.firebolt.io/pricing) - Firebolt Documentation
[^2]: [Firebolt Billing](https://docs.firebolt.io/overview/billing) - Firebolt Documentation
[^3]: [Firebolt Trial](https://www.firebolt.io/blog/firebolt-trial-for-30-days-with-200-free-credits-now-open-to-all) - Firebolt Blog

---

*Questions or feedback? [Open an issue](https://github.com/oxbow-analytics/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: ~1,600
**Series**: free-trial-benchmarking
**Post Number**: 9
