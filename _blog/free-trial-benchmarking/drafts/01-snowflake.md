# Free trial benchmarking: Snowflake

> Snowflake's $400 trial gives you 30 days to evaluate one of the most popular cloud data platforms. Here's how to run meaningful TPC-H benchmarks without burning through credits on failed runs.

**TL;DR**: Snowflake's trial gives $400 in credits over 30 days. Auto-suspend is your best friend. Start with X-Small warehouses (1 credit/hour), validate at SF0.01, then scale up. BenchBox handles schema creation, data loading, and warehouse tuning automatically.

---

## What you get

**Trial details:**
- **Credits**: $400 (roughly 100-200 warehouse-hours depending on size)
- **Duration**: 30 days
- **Credit card**: Not required
- **Support**: Community only (no enterprise support)

**Key limitations during trial:**
- Cortex AI features capped at ~1 credit/day
- No external network access (outbound connections)
- No hybrid tables
- Some Public Preview features disabled
- Trial accounts cannot be canceled via UI (must contact support)

**What happens when trial ends:**
Trial converts to on-demand billing if you add a credit card. Otherwise, account suspends but data is preserved for 30 days.

---

## Explore with MCP

Before spending credits, use the MCP server to preview your benchmark runs. Connect BenchBox's MCP server to your AI assistant, then ask:

**Validate BenchBox can reach Snowflake:**

> "Can I run TPC-H on Snowflake with my current setup?"

The assistant calls `validate_config(platform="snowflake", benchmark="tpch")` and reports any missing dependencies or configuration issues.

**Preview resource consumption:**

> "What would a TPC-H SF1 run on Snowflake look like?"

```
# Example MCP dry_run response
Platform: Snowflake
Benchmark: TPC-H SF1
Estimated data size: ~1 GB
Tables: 8 (nation, region, part, supplier, partsupp, customer, orders, lineitem)
Queries: 22
Phases: load, power

Notes:
- Data generation: ~30 seconds
- Load phase: Creates tables, loads data
- Power phase: Runs all 22 queries sequentially
```

**Check what benchmarks are available:**

> "What benchmarks can I run on Snowflake?"

BenchBox supports TPC-H, TPC-DS, SSB, and ClickBench on Snowflake. For trial evaluation, we recommend starting with TPC-H (22 queries, well-understood workload).

---

## The game plan

### Credit budget planning

With $400 in credits and ~$2-4 per credit (varies by edition), you have roughly 100-200 credit-hours to work with. Here's how to allocate them:

| Phase         | Warehouse | Duration | Credits | Purpose                      |
| ------------- | --------- | -------- | ------- | ---------------------------- |
| Validate      | X-Small   | 30 min   | 0.5     | Confirm setup works          |
| Baseline SF1  | X-Small   | 1 hour   | 1       | First meaningful benchmark   |
| Scale compute | Small     | 1 hour   | 2       | Test warehouse sizing impact |
| Scale data    | X-Small   | 4 hours  | 4       | SF10 benchmark               |
| Buffer        | -         | -        | ~50     | Learning, experimentation    |

This leaves substantial credits for exploration while ensuring you get benchmark data at multiple configurations.

### Warehouse sizing and costs

| Size    | Credits/Hour | Typical Use                   |
| ------- | ------------ | ----------------------------- |
| X-Small | 1            | Development, small benchmarks |
| Small   | 2            | SF1-SF10 benchmarks           |
| Medium  | 4            | SF10-SF100 benchmarks         |
| Large   | 8            | Production-scale testing      |
| X-Large | 16           | High-concurrency testing      |

**Gen2 warehouses** (if available in your trial) use 1.25-1.35x credits but run queries faster. For benchmarking, standard warehouses give more predictable credit consumption.

### The scaling progression

1. **SF0.01 on X-Small**: Validate connectivity, schema creation, and query execution (5-10 minutes, ~0.1 credits)
2. **SF1 on X-Small**: First meaningful benchmark data (30-60 minutes, ~0.5-1 credit)
3. **SF1 on Small**: Compare warehouse scaling impact (30-60 minutes, ~1-2 credits)
4. **SF10 on X-Small**: Longer run, more data-volume-sensitive results (2-4 hours, ~2-4 credits)

---

## BenchBox setup

### Install dependencies

```bash
uv add snowflake-connector-python
```

### Configuration

BenchBox reads Snowflake credentials from environment variables:

```bash
export SNOWFLAKE_ACCOUNT="your-account-identifier"
export SNOWFLAKE_USER="your-username"
export SNOWFLAKE_PASSWORD="your-password"
export SNOWFLAKE_WAREHOUSE="COMPUTE_WH"
export SNOWFLAKE_DATABASE="BENCHBOX_DB"
export SNOWFLAKE_SCHEMA="PUBLIC"
```

**Finding your account identifier:**
Your account identifier appears in the URL when you log in: `https://<account-identifier>.snowflakecomputing.com`. For example, if your URL is `https://xy12345.us-east-1.snowflakecomputing.com`, your account identifier is `xy12345.us-east-1`.

**Authentication options:**
- **Username/password** (shown above): Simplest for trials
- **Browser SSO**: Set `SNOWFLAKE_AUTHENTICATOR=externalbrowser`
- **Key pair**: Set `SNOWFLAKE_AUTHENTICATOR=SNOWFLAKE_JWT` with `SNOWFLAKE_PRIVATE_KEY_PATH`

### Verify connection

```bash
# Quick connectivity test
uv run python -c "
import snowflake.connector
import os

conn = snowflake.connector.connect(
    account=os.environ['SNOWFLAKE_ACCOUNT'],
    user=os.environ['SNOWFLAKE_USER'],
    password=os.environ['SNOWFLAKE_PASSWORD'],
    warehouse=os.environ['SNOWFLAKE_WAREHOUSE']
)
print('Connected to Snowflake:', conn.get_query_status_throw_if_error(conn.execute_string('SELECT CURRENT_ACCOUNT()')[0].sfqid))
conn.close()
"
```

---

## Running the benchmarks

### Step 1: Validate with SF0.01

```bash
benchbox run --platform snowflake --benchmark tpch --scale 0.01
```

Expected output:
```
BenchBox v0.2.0
Platform: Snowflake (COMPUTE_WH)
Benchmark: TPC-H SF0.01

[INFO] Generating data...
[INFO] Creating schema and loading data...
[INFO] Running power phase (22 queries)...
[SUCCESS] Completed in 5m 23s

Results saved to: benchmark_runs/results/tpch_sf001_snowflake_20260131_143022.json
```

**What BenchBox does automatically:**
- Creates the benchmark database and schema
- Generates TPC-H data using the built-in generator
- Creates tables with appropriate clustering keys
- Loads data efficiently
- Runs all 22 TPC-H queries
- Validates results against reference answers

### Step 2: Baseline at SF1

```bash
benchbox run --platform snowflake --benchmark tpch --scale 1
```

This takes 30-60 minutes on an X-Small warehouse. The result file contains per-query timings you can analyze later.

### Step 3: Scale up

Once you have baseline data, experiment with warehouse sizing:

```bash
# Temporarily resize warehouse (in Snowflake console or via SQL)
# ALTER WAREHOUSE COMPUTE_WH SET WAREHOUSE_SIZE = 'SMALL';

benchbox run --platform snowflake --benchmark tpch --scale 1
```

Or scale data:

```bash
benchbox run --platform snowflake --benchmark tpch --scale 10
```

### Running specific queries

To focus on particular queries (useful for debugging or targeted analysis):

```bash
# Run only Q1, Q6, and Q17
benchbox run --platform snowflake --benchmark tpch --scale 1 --queries Q1,Q6,Q17
```

---

## Reproducing and comparing

### Find your previous runs

Using the MCP server:

> "Show me my recent Snowflake benchmark runs"

Or via CLI:

```bash
ls -la benchmark_runs/results/ | grep snowflake
```

### Analyze results

> "What were the results of my last TPC-H run on Snowflake?"

The MCP server loads the result file and presents a summary:

```
TPC-H SF1 on Snowflake (COMPUTE_WH X-Small)
Total time: 42m 17s
Queries passed: 22/22

Slowest queries:
- Q21: 8m 32s (suppliers who kept orders waiting)
- Q18: 6m 47s (large volume customer)
- Q9: 4m 23s (product type profit measure)

Fastest queries:
- Q6: 12s (forecasting revenue change)
- Q1: 18s (pricing summary report)
- Q14: 23s (promotion effect)
```

### Compare runs

> "Compare my X-Small and Small warehouse runs on Snowflake"

```
Comparison: X-Small vs Small warehouse

Overall:
- X-Small total: 42m 17s
- Small total: 23m 45s
- Speedup: 1.78x

Notable differences (>50% change):
- Q21: 8m 32s → 4m 12s (1.8x faster)
- Q18: 6m 47s → 3m 01s (2.2x faster)
- Q6: 12s → 11s (minimal change, already fast)
```

---

## Trial traps to avoid

### 1. Leaving warehouses running

**The trap**: Snowflake warehouses consume credits while running, even when idle. An X-Small warehouse left running overnight costs 8 credits (~$16-32).

**The fix**: Configure auto-suspend immediately:

```sql
ALTER WAREHOUSE COMPUTE_WH SET AUTO_SUSPEND = 60;  -- Suspend after 60 seconds idle
```

For benchmarking, consider even shorter timeouts (30-60 seconds) since BenchBox runs queries back-to-back.

### 2. Starting too big

**The trap**: Jumping straight to SF100 or Large warehouses, then discovering configuration issues after burning 50+ credits.

**The fix**: Always start with SF0.01 on X-Small. Validate that everything works, then scale incrementally.

### 3. Forgetting the 60-second minimum

**The trap**: Snowflake bills in per-second increments but with a 60-second minimum per warehouse startup. Frequent suspends and resumes accumulate minimums.

**The fix**: For benchmark runs, let the warehouse stay active during the full run. Auto-suspend between runs, not between queries.

### 4. Cortex AI experimentation

**The trap**: Cortex AI features (LLMs, ML functions) consume credits quickly and are capped at ~1 credit/day during trial. Easy to burn through daily allowance accidentally.

**The fix**: If evaluating Cortex, do it separately from benchmarking. Don't mix AI experiments with TPC-H runs.

### 5. Large warehouse "just to see"

**The trap**: Spinning up a 2X-Large warehouse "just to see how fast it is" costs 32 credits per hour (~$64-128).

**The fix**: Scale methodically. X-Small → Small → Medium. You'll get useful scaling data without the credit shock.

### Cleanup checklist before trial ends

- [ ] Download result files from `benchmark_runs/results/`
- [ ] Export any analysis or charts you've created
- [ ] Note warehouse configurations that worked well
- [ ] Document any platform-specific learnings
- [ ] Decide: add credit card to continue, or let trial expire

---

## Credit consumption reference

Based on our testing with X-Small warehouses:

| Scale Factor | Load Time | Query Time | Total Time | Est. Credits |
| ------------ | --------- | ---------- | ---------- | ------------ |
| SF0.01       | ~2 min    | ~3 min     | ~5 min     | 0.1          |
| SF1          | ~10 min   | ~30 min    | ~40 min    | 0.7          |
| SF10         | ~30 min   | ~3 hours   | ~3.5 hours | 3.5          |

Your mileage may vary based on warehouse size, network conditions, and Snowflake load. These estimates are conservative; actual credit consumption may be lower.

---

## Summary

Snowflake's $400 trial provides ample room for thorough TPC-H evaluation. The keys to success:

1. **Configure auto-suspend immediately** (60 seconds or less)
2. **Start small** (SF0.01 on X-Small) to validate setup
3. **Scale methodically** to build understanding
4. **Keep result files** for later analysis and comparison

BenchBox handles the tedious parts: schema creation, data loading, warehouse tuning, and result validation. You focus on evaluating the platform.

---

## References

[^1]: [Snowflake Trial Accounts](https://docs.snowflake.com/en/user-guide/admin-trial-account) - Snowflake Documentation
[^2]: [Snowflake Compute Cost](https://docs.snowflake.com/en/user-guide/cost-understanding-compute) - Snowflake Documentation
[^3]: [Snowflake Warehouse Considerations](https://docs.snowflake.com/en/user-guide/warehouses-considerations) - Snowflake Documentation
[^4]: [Snowflake Authentication](https://docs.snowflake.com/en/developer-guide/node-js/nodejs-driver-authenticate) - Snowflake Documentation

---

*Questions or feedback? [Open an issue](https://github.com/oxbow-analytics/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: ~1,800
**Series**: free-trial-benchmarking
**Post Number**: 1
