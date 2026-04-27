# Free trial benchmarking: ClickHouse Cloud

> ClickHouse Cloud offers $300 in credits with per-minute billing. Here's how to benchmark the real-time analytics platform without burning credits on idle time.

**TL;DR**: ClickHouse Cloud gives you $300 over 30 days with per-minute billing. Services bill while active, even without queries. Configure auto-stop immediately (20-30 second resume time). Email notifications at 50%, 75%, 90% consumption are helpful.

---

## What you get

**Trial details:**
- **Credits**: $300
- **Duration**: 30 days
- **Email notifications**: At 50%, 75%, 90% consumption
- **Post-trial**: Continues as pay-as-you-go if billing configured

**The ClickHouse advantage:**

ClickHouse is designed for real-time analytics:
- Column-oriented storage optimized for aggregations
- Vectorized query execution
- Real-time data ingestion
- Sub-second queries on large datasets

**Pricing model: Per-minute compute**

| Component  | Billing Model                                |
| ---------- | -------------------------------------------- |
| Compute    | Per-minute in 8 GB RAM increments            |
| Storage    | Compressed data size                         |
| Egress     | Data transfer out                            |
| ClickPipes | $0.04/GB ingested, $0.20/hr per compute unit |

Key insight: Compute bills while the service is active, even without running queries.

**What happens when trial ends:**
Transitions to pay-as-you-go if billing is configured. Otherwise, service suspends.

---

## Explore with MCP

Before spending credits, use the MCP server to preview your benchmark runs:

**Validate configuration:**

> "Can I run TPC-H on ClickHouse with my current setup?"

The assistant calls `validate_config(platform="clickhouse", benchmark="tpch")` and reports any issues with your service configuration or credentials.

**Preview resource consumption:**

> "What would a TPC-H SF1 run on ClickHouse look like?"

```
# Example MCP dry_run response
Platform: ClickHouse Cloud
Benchmark: TPC-H SF1
Estimated data size: ~1 GB
Tables: 8 (nation, region, part, supplier, partsupp, customer, orders, lineitem)
Queries: 22
Phases: load, power

Notes:
- Uses ClickHouse-optimized table engines (MergeTree)
- Per-minute billing while service is active
- Estimated run time: 15-30 minutes
- Service should auto-stop after completion
```

**Check ClickHouse-specific features:**

> "What table engines does BenchBox use for TPC-H on ClickHouse?"

BenchBox uses MergeTree family engines with appropriate ORDER BY and PARTITION BY clauses for optimal query performance.

---

## The game plan

### Credit budget planning

With $300 and per-minute billing, time management is critical:

| Activity          | Est. Minutes | Est. Cost (varies by tier) |
| ----------------- | ------------ | -------------------------- |
| SF0.01 validation | 10-15        | ~$0.50-1.00                |
| SF1 benchmark     | 30-60        | ~$2-5                      |
| SF10 benchmark    | 120-240      | ~$8-20                     |
| Idle time (trap!) | Varies       | Varies                     |

**Strategy**: Configure auto-stop, validate quickly, stop service between sessions.

### Auto-stop configuration (do this first!)

ClickHouse Cloud services can idle (stop automatically after inactivity):

1. ClickHouse Cloud console → Services
2. Select your service → Settings
3. Configure idle timeout (recommended: 5-10 minutes)
4. Save

Resume time is 20-30 seconds. The brief delay is worth the credit savings.

### The scaling progression

1. **SF0.01**: Validate connectivity, schema, queries (10-15 minutes)
2. **SF1**: First meaningful benchmark (30-60 minutes)
3. **SF10**: Larger data volume (2-4 hours)
4. **Stop service** between each session

---

## BenchBox setup

### Install dependencies

```bash
uv add clickhouse-driver
```

### Configuration

BenchBox reads ClickHouse credentials from environment variables:

```bash
# ClickHouse Cloud connection
export CLICKHOUSE_HOST="your-service.clickhouse.cloud"
export CLICKHOUSE_PORT="9440"  # Native protocol, TLS
export CLICKHOUSE_USER="default"
export CLICKHOUSE_PASSWORD="your-password"
export CLICKHOUSE_DATABASE="benchbox"

# Use secure connection
export CLICKHOUSE_SECURE="true"
```

**Finding your connection details:**

1. ClickHouse Cloud console → Services
2. Select your service → Connect
3. Copy host, port, username from connection string
4. Password is what you set during service creation

**Connection string format:**
```
clickhouse://default:password@your-service.clickhouse.cloud:9440/benchbox?secure=true
```

### Verify connection

```bash
# Quick connectivity test
uv run python -c "
from clickhouse_driver import Client
import os

client = Client(
    host=os.environ['CLICKHOUSE_HOST'],
    port=int(os.environ.get('CLICKHOUSE_PORT', 9440)),
    user=os.environ.get('CLICKHOUSE_USER', 'default'),
    password=os.environ['CLICKHOUSE_PASSWORD'],
    secure=True
)
result = client.execute('SELECT currentUser()')
print('Connected to ClickHouse as:', result[0][0])
"
```

---

## Running the benchmarks

### Step 1: Configure auto-stop (critical!)

Before any benchmarking:

1. ClickHouse Cloud console → Services → Your service
2. Settings → Idle timeout
3. Set to 5-10 minutes
4. Save

This prevents credits from draining while you're not actively querying.

### Step 2: Validate with SF0.01

```bash
benchbox run --platform clickhouse --benchmark tpch --scale 0.01
```

Expected output:
```
BenchBox v0.2.0
Platform: ClickHouse Cloud
Benchmark: TPC-H SF0.01

[INFO] Generating data...
[INFO] Creating schema and loading data...
[INFO] Running power phase (22 queries)...
[SUCCESS] Completed in 4m 23s

Results saved to: benchmark_runs/results/tpch_sf001_clickhouse_20260131_143022.json
```

**What BenchBox does automatically:**
- Creates the benchmark database
- Generates TPC-H data
- Creates MergeTree tables with optimized ORDER BY
- Applies ClickHouse-specific optimizations
- Runs all 22 TPC-H queries
- Validates results against reference answers

### Step 3: Baseline at SF1

```bash
benchbox run --platform clickhouse --benchmark tpch --scale 1
```

ClickHouse's vectorized execution typically completes TPC-H faster than many other platforms. Expect 15-30 minutes for SF1.

### Step 4: Scale to SF10

```bash
benchbox run --platform clickhouse --benchmark tpch --scale 10
```

Monitor service status in ClickHouse Cloud console during the run.

### Running specific queries

```bash
# Run the aggregation-heavy queries
benchbox run --platform clickhouse --benchmark tpch --scale 1 --queries Q1,Q6,Q13,Q14
```

---

## Reproducing and comparing

### Find your previous runs

> "Show me my recent ClickHouse benchmark runs"

Or via CLI:

```bash
ls -la benchmark_runs/results/ | grep clickhouse
```

### Analyze ClickHouse performance characteristics

> "Which TPC-H queries ran fastest on ClickHouse?"

```
TPC-H SF1 on ClickHouse Cloud

Fastest queries:
- Q6: 0.8s (simple aggregation, ClickHouse excels here)
- Q1: 1.2s (aggregation on lineitem)
- Q14: 1.5s (promotion effect)

Slowest queries:
- Q21: 45s (correlated subquery, complex joins)
- Q2: 38s (minimum cost supplier, nested query)
- Q9: 32s (product type profit, multi-table join)

Notes:
- Aggregation queries show ClickHouse's columnar strength
- Complex joins take longer (expected for column-oriented DB)
```

### Compare with other platforms

If you've run the same benchmark on other platforms:

> "Compare my ClickHouse and DuckDB TPC-H results"

---

## Trial traps to avoid

### 1. Forgetting per-minute billing while active

**The trap**: Service is "Running" in console, billing continues even without queries. Leave it running overnight = significant credit drain.

**The fix**: Configure auto-stop (5-10 minute idle timeout). Check service status before leaving.

### 2. Not configuring auto-stop

**The trap**: Assuming service will stop automatically. Default may be longer than expected or disabled entirely.

**The fix**: Explicitly configure idle timeout in service settings before first benchmark.

### 3. The 20-30 second resume delay

**The trap**: Expecting instant query execution after service has idled. First query after resume takes longer.

**The fix**: Plan for resume time. For benchmarking, keep service active during the benchmark session, then let it idle between sessions.

### 4. January 2025 pricing changes

**The trap**: Using outdated pricing estimates. ClickHouse Cloud updated pricing in January 2025 (~30% increase for typical workloads).

**The fix**: Check current pricing in ClickHouse Cloud console. Monitor credit consumption during initial runs.

### 5. ClickPipes ingestion costs

**The trap**: Using ClickPipes for data loading without realizing the separate per-GB and per-hour charges.

**The fix**: For benchmarking, BenchBox uses direct INSERT statements which avoid ClickPipes charges. Reserve ClickPipes for production streaming use cases.

### Cleanup checklist before trial ends

- [ ] Download result files from `benchmark_runs/results/`
- [ ] Stop service (or verify auto-stop is configured)
- [ ] Note query performance characteristics
- [ ] Document table configurations that worked well
- [ ] Decide: configure billing or let service suspend

---

## Credit consumption reference

Based on our testing (actual costs vary by service tier and configuration):

| Scale Factor | Est. Time | Est. Cost |
| ------------ | --------- | --------- |
| SF0.01       | ~5 min    | ~$0.50    |
| SF1          | ~20 min   | ~$2-3     |
| SF10         | ~2 hours  | ~$10-15   |

ClickHouse's fast execution means shorter run times, but per-minute billing still applies. The biggest cost risk is idle time, not query execution.

---

## Summary

ClickHouse Cloud's per-minute billing rewards efficiency. The keys to success:

1. **Configure auto-stop immediately** (before any benchmarking)
2. **Run benchmarks in focused sessions** (keep active during runs, idle between)
3. **Use email notifications** (50%, 75%, 90% alerts help track consumption)
4. **Expect fast execution** (ClickHouse excels at aggregations)

BenchBox handles MergeTree configuration, ORDER BY optimization, and query validation. You focus on understanding ClickHouse's performance characteristics.

---

## References

[^1]: [ClickHouse Pricing](https://clickhouse.com/pricing) - ClickHouse Documentation
[^2]: [ClickHouse Billing](https://clickhouse.com/docs/cloud/manage/billing/overview) - ClickHouse Documentation

---

*Questions or feedback? [Open an issue](https://github.com/oxbow-analytics/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: ~1,550
**Series**: free-trial-benchmarking
**Post Number**: 7
