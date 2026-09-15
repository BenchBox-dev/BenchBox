# Free trial benchmarking: MotherDuck

> MotherDuck brings DuckDB to the cloud with a generous free tier. Here's how to use DuckDB compatibility for local development and cloud benchmarking.

**TL;DR**: MotherDuck gives you 21 days of full features plus an ongoing free tier (10 CU-hours/month, 10 GB storage). The DuckDB compatibility means you can develop locally and benchmark identically in the cloud. Storage overages block queries, so monitor your usage.

---

## What you get

**Trial details:**
- **Trial period**: 21 days with full features
- **Free tier** (ongoing): 10 CU-hours/month, 10 GB storage
- **Credit card**: Not required
- **Regions**: AWS us-east-1, eu-central-1

**The unique MotherDuck advantage:**

MotherDuck runs DuckDB in the cloud, meaning:
- Same SQL syntax as local DuckDB
- Develop and test locally, then run identical queries on MotherDuck
- Hybrid local+cloud workflow (query local and cloud data together)
- No learning curve if you already know DuckDB

**Pricing model (after trial):**

| Plan     | Base Fee   | CU-hours | Storage |
| -------- | ---------- | -------- | ------- |
| Free     | $0         | 10/month | 10 GB   |
| Lite     | $25/month  | Included | 100 GB  |
| Business | $100/month | Included | 500 GB  |

CU (Compute Unit) = CPU and memory usage over time. The free tier's 10 CU-hours/month is generous for small-scale benchmarking.

**What happens when trial ends:**
Account downgrades to Free tier. If you exceed storage limits, queries are blocked until you reduce usage or upgrade.

---

## Explore with MCP

Before spending CU-hours, use the MCP server to preview your benchmark runs:

**Validate configuration:**

> "Can I run TPC-H on MotherDuck with my current setup?"

The assistant calls `validate_config(platform="motherduck", benchmark="tpch")` and reports any issues with your MotherDuck token or DuckDB version compatibility.

**Preview resource consumption:**

> "What would a TPC-H SF1 run on MotherDuck look like?"

```
# Example MCP dry_run response
Platform: MotherDuck
Benchmark: TPC-H SF1
Estimated data size: ~1 GB
Tables: 8 (nation, region, part, supplier, partsupp, customer, orders, lineitem)
Queries: 22
Phases: load, power

Notes:
- Uses DuckDB's native TPC-H extension for data generation
- Load phase: Creates tables in your MotherDuck database
- Power phase: Runs all 22 queries sequentially
- Estimated CU consumption: 1-2 CU-hours
```

**Check DuckDB compatibility:**

> "What DuckDB versions are compatible with MotherDuck?"

Current compatibility:
- US-East-1: DuckDB 1.3.0-1.4.3
- EU-Central-1: DuckDB 1.4.1-1.4.3

BenchBox uses a compatible DuckDB version automatically.

---

## The game plan

### Free tier budget planning

With 10 CU-hours/month, here's what you can run:

| Scale Factor | Est. CU-hours | Monthly Runs (free tier) |
| ------------ | ------------- | ------------------------ |
| SF0.01       | 0.1-0.2       | ~50-100                  |
| SF1          | 1-2           | 5-10                     |
| SF10         | 5-10          | 1 (borderline)           |

**Strategy**: Use local DuckDB for development and iteration, MotherDuck for final validation runs.

### The hybrid workflow

MotherDuck's killer feature is the local+cloud hybrid:

```python
import duckdb

# Connect to MotherDuck (cloud)
conn = duckdb.connect('md:my_database')

# Query cloud data
conn.execute("SELECT * FROM cloud_table LIMIT 10")

# Query local data
conn.execute("SELECT * FROM read_parquet('local_file.parquet') LIMIT 10")

# Join local and cloud data
conn.execute("""
    SELECT *
    FROM cloud_table c
    JOIN read_parquet('local_file.parquet') l ON c.id = l.id
""")
```

For benchmarking, this means:
1. Generate TPC-H data locally
2. Test queries locally (no CU consumption)
3. Upload data to MotherDuck for cloud benchmarking
4. Compare local vs. cloud performance

### The scaling progression

1. **Local DuckDB SF0.01**: Validate query logic (0 CU)
2. **MotherDuck SF0.01**: Validate cloud connectivity (~0.1 CU-hours)
3. **Local DuckDB SF1**: Full benchmark locally (0 CU)
4. **MotherDuck SF1**: Cloud benchmark for comparison (~1-2 CU-hours)

---

## BenchBox setup

### Install dependencies

```bash
uv add duckdb
```

BenchBox uses the standard DuckDB connector with MotherDuck connection strings.

### Configuration

BenchBox reads MotherDuck credentials from environment variables:

```bash
# MotherDuck authentication token
export MOTHERDUCK_TOKEN="your-motherduck-token"

# Optional: specify database name
export MOTHERDUCK_DATABASE="benchbox"
```

**Getting your MotherDuck token:**

1. **Browser-based** (interactive):
   ```bash
   duckdb -c ".open md:"
   # Browser opens, authenticate, token saved to ~/.duckdb
   ```

2. **Token from UI**:
   - Log in to motherduck.com
   - Settings → Access Tokens
   - Create new token

3. **Connection string** (programmatic):
   ```
   md:my_database?motherduck_token=YOUR_TOKEN
   ```

### Verify connection

```bash
# Quick connectivity test
uv run python -c "
import duckdb
import os

token = os.environ.get('MOTHERDUCK_TOKEN')
conn = duckdb.connect(f'md:?motherduck_token={token}')
result = conn.execute('SELECT current_database()').fetchone()
print('Connected to MotherDuck:', result[0])
conn.close()
"
```

---

## Running the benchmarks

### Step 1: Local development (recommended first step)

Before using MotherDuck CU-hours, validate everything locally:

```bash
# Run TPC-H locally with DuckDB
benchbox run --platform duckdb --benchmark tpch --scale 0.01
```

This confirms BenchBox works and your TPC-H queries execute correctly, with zero cloud cost.

### Step 2: Validate with MotherDuck SF0.01

```bash
benchbox run --platform motherduck --benchmark tpch --scale 0.01
```

Expected output:
```
BenchBox v0.2.0
Platform: MotherDuck
Benchmark: TPC-H SF0.01

[INFO] Generating data...
[INFO] Creating schema and loading data...
[INFO] Running power phase (22 queries)...
[SUCCESS] Completed in 3m 45s

Results saved to: benchmark_runs/results/tpch_sf001_motherduck_20260131_143022.json
```

**What BenchBox does automatically:**
- Creates a database in your MotherDuck account
- Generates TPC-H data using DuckDB's built-in generator
- Creates tables optimized for DuckDB's columnar format
- Runs all 22 TPC-H queries
- Validates results against reference answers

### Step 3: Compare local vs. cloud

Run the same benchmark on both platforms:

```bash
# Local
benchbox run --platform duckdb --benchmark tpch --scale 1

# Cloud
benchbox run --platform motherduck --benchmark tpch --scale 1
```

Then compare:

> "Compare my local DuckDB and MotherDuck SF1 runs"

```
Comparison: Local DuckDB vs MotherDuck (SF1)

Overall:
- Local total: 28m 12s
- MotherDuck total: 32m 45s

Notable differences:
- Q1: Local 45s, MotherDuck 52s (network overhead)
- Q21: Local 5m 30s, MotherDuck 6m 12s
- Most queries within 15% of each other

Notes:
- MotherDuck adds network latency (~5-15% overhead typical)
- Cloud execution is more consistent (no local CPU contention)
```

### Running specific queries

```bash
# Run specific queries on MotherDuck
benchbox run --platform motherduck --benchmark tpch --scale 1 --queries Q1,Q6,Q14
```

---

## Reproducing and comparing

### Find your previous runs

> "Show me my recent MotherDuck benchmark runs"

Or via CLI:

```bash
ls -la benchmark_runs/results/ | grep motherduck
```

### Monitor CU consumption

MotherDuck shows CU consumption in the web UI (motherduck.com → Usage). BenchBox result files include timing data you can use to estimate consumption.

### Track free tier budget

> "How much of my MotherDuck free tier have I used this month?"

Check the MotherDuck UI for exact numbers. As a rough guide:
- SF0.01 run: ~0.1-0.2 CU-hours
- SF1 run: ~1-2 CU-hours

---

## Trial traps to avoid

### 1. Storage overage blocking queries

**The trap**: Exceeding 10 GB storage on free tier blocks ALL queries until resolved, including queries to delete data.

**The fix**: Monitor storage proactively. Delete test databases when done:

```sql
DROP DATABASE IF EXISTS old_benchmark_db;
```

Or via MotherDuck UI: Databases → Delete.

### 2. Pulse auto-scaling surprises

**The trap**: MotherDuck's "Pulse" auto-scaling feature scales compute based on query complexity. Complex queries can consume CUs faster than expected.

**The fix**: For predictable benchmarking, use Standard mode (fixed compute) rather than Pulse. Check your account settings.

### 3. DuckDB version mismatch

**The trap**: Using a local DuckDB version incompatible with MotherDuck, causing connection failures or query errors.

**The fix**: BenchBox handles this automatically. For manual connections, check compatibility:
- US-East-1: DuckDB 1.3.0-1.4.3
- EU-Central-1: DuckDB 1.4.1-1.4.3

### 4. Not leveraging local development

**The trap**: Running all iterations on MotherDuck, burning through CU-hours on failed runs or query tweaking.

**The fix**: Develop locally first:
```bash
# Free, unlimited iterations
benchbox run --platform duckdb --benchmark tpch --scale 0.01

# Only after local validation
benchbox run --platform motherduck --benchmark tpch --scale 0.01
```

### 5. Forgetting the platform fee

**The trap**: Planning based on CU-hour costs alone, then discovering Lite ($25/mo) or Business ($100/mo) base fees.

**The fix**: For trial evaluation, the free tier is sufficient. If you need more, factor in the platform fee when comparing to pay-per-query alternatives.

### Cleanup checklist before trial ends

- [ ] Download result files from `benchmark_runs/results/`
- [ ] Note local vs. cloud performance differences
- [ ] Check storage usage (stay under 10 GB for free tier)
- [ ] Delete test databases you don't need
- [ ] Decide: stay on free tier, upgrade, or export data

---

## CU consumption reference

Based on our testing:

| Scale Factor | Est. CU-hours | Storage | Fits Free Tier?            |
| ------------ | ------------- | ------- | -------------------------- |
| SF0.01       | 0.1-0.2       | ~10 MB  | Yes (~50 runs/month)       |
| SF1          | 1-2           | ~1 GB   | Yes (5-10 runs/month)      |
| SF10         | 5-10          | ~10 GB  | Borderline (storage limit) |

Storage is often the limiting factor on free tier, not CU-hours.

---

## Summary

MotherDuck's DuckDB compatibility makes it uniquely suited for hybrid local+cloud workflows. The keys to success:

1. **Develop locally first**: Use DuckDB for iteration (zero cost)
2. **Validate in cloud**: MotherDuck for final benchmarks
3. **Monitor storage**: 10 GB limit can block queries
4. **Compare local vs. cloud**: Understand network overhead

BenchBox works identically on both DuckDB and MotherDuck, making the transition seamless. Same queries, same validation, different execution environment.

---

## References

[^1]: [MotherDuck Pricing](https://motherduck.com/product/pricing/) - MotherDuck Documentation
[^2]: [MotherDuck Billing](https://motherduck.com/docs/about-motherduck/billing/pricing/) - MotherDuck Documentation
[^3]: [MotherDuck Authentication](https://motherduck.com/docs/key-tasks/authenticating-and-connecting-to-motherduck/authenticating-to-motherduck/) - MotherDuck Documentation

---

*Questions or feedback? [Open an issue](https://github.com/oxbow-analytics/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: ~1,700
**Series**: free-trial-benchmarking
**Post Number**: 4
