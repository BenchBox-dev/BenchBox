# Free trial benchmarking: Databricks

> Databricks offers $400 in credits, but only 14 days to use them. Here's how to run meaningful benchmarks on the shortest trial window of any major platform.

**TL;DR**: Databricks gives you $400 over just 14 days, the shortest window of any major platform. Use a business email for full capabilities (personal emails limit you to 50 DBU/hr). Jobs compute is 3-4x cheaper than All-Purpose. BenchBox supports both SQL and DataFrame modes.

---

## What you get

**Trial details:**
- **Credits**: $400 DBU credits
- **Duration**: 14 days (shortest of major platforms)
- **Credit card**: Not required for signup
- **Cloud**: Choose AWS, Azure, or GCP at signup

**Critical limitation: Personal vs. business email**

| Aspect           | Personal Email        | Business Email  |
| ---------------- | --------------------- | --------------- |
| Max compute      | 50 DBU/hr             | Unlimited       |
| GPU access       | No                    | Yes             |
| External network | Limited               | Full            |
| Use case         | Learning, small tests | Full evaluation |

If you're evaluating Databricks for production use, sign up with a business email. The 50 DBU/hr limit with personal emails restricts cluster sizes and significantly impacts benchmark capability.

**Free Trial vs. Free Edition:**

| Aspect         | Free Trial          | Free Edition        |
| -------------- | ------------------- | ------------------- |
| Target         | Business evaluation | Students, hobbyists |
| Duration       | 14 days             | Ongoing             |
| Credits        | $400                | None (fair usage)   |
| Commercial use | Yes                 | No                  |
| Support/SLA    | Covered             | Not covered         |

**What happens when trial ends:**
Trial converts to pay-as-you-go if cloud billing is configured. Otherwise, compute access suspends but data and notebooks are preserved.

---

## Explore with MCP

Before spending DBUs, use the MCP server to preview your benchmark runs:

**Validate configuration:**

> "Can I run TPC-H on Databricks with my current setup?"

The assistant calls `validate_config(platform="databricks", benchmark="tpch")` and reports any issues with your SQL warehouse connection or missing dependencies.

**Preview resource consumption:**

> "What would a TPC-H SF1 run on Databricks look like?"

```
# Example MCP dry_run response
Platform: Databricks (SQL Warehouse)
Benchmark: TPC-H SF1
Estimated data size: ~1 GB
Tables: 8 (nation, region, part, supplier, partsupp, customer, orders, lineitem)
Queries: 22
Phases: load, power

Notes:
- Uses Delta Lake format for optimal performance
- Data generation: ~30 seconds
- Load phase: Creates tables in Unity Catalog
- Power phase: Runs all 22 queries sequentially
```

**Check available modes:**

> "What's the difference between Databricks SQL and DataFrame modes in BenchBox?"

BenchBox supports both:
- **SQL mode** (`databricks`): Uses SQL Warehouse, standard TPC-H SQL
- **DataFrame mode** (`databricks-df`): Uses Spark clusters, PySpark DataFrame operations

---

## The game plan

### The 14-day constraint

With only 14 days, you need to be efficient. Here's a suggested schedule:

| Day   | Activity                     | DBUs (est.) |
| ----- | ---------------------------- | ----------- |
| 1     | Setup, validate SF0.01       | 2-5         |
| 2-3   | SF1 baseline runs            | 10-20       |
| 4-5   | Warehouse sizing experiments | 20-40       |
| 6-7   | SF10 runs                    | 40-80       |
| 8-10  | Specific query analysis      | 20-40       |
| 11-14 | Buffer, exploration          | Remaining   |

This leaves substantial credits for experimentation while ensuring you capture meaningful benchmark data.

### DBU costs by compute type

**Critical insight**: All-Purpose compute costs 3-4x more than Jobs compute per DBU.

| Compute Type  | DBU Rate       | Use Case                        |
| ------------- | -------------- | ------------------------------- |
| Jobs Compute  | $0.15/DBU      | Batch workloads, scheduled jobs |
| All-Purpose   | $0.40-0.55/DBU | Interactive development         |
| SQL Warehouse | $0.22-0.55/DBU | SQL analytics                   |

For benchmarking, SQL Warehouses or Jobs Compute give you the most runs per credit. All-Purpose clusters burn through credits quickly.

### The scaling progression

1. **SF0.01 on Small warehouse**: Validate connectivity, schema, queries (10-15 minutes, ~2 DBU)
2. **SF1 on Small warehouse**: First meaningful benchmark (30-60 minutes, ~10 DBU)
3. **SF1 on Medium warehouse**: Compare warehouse scaling (30-60 minutes, ~15 DBU)
4. **SF10 on Medium warehouse**: Longer run, larger data (2-4 hours, ~40 DBU)

---

## BenchBox setup

### Install dependencies

```bash
uv add databricks-sql-connector
```

### Configuration

BenchBox reads Databricks credentials from environment variables:

```bash
# SQL Warehouse configuration
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_HTTP_PATH="/sql/1.0/warehouses/your-warehouse-id"
export DATABRICKS_TOKEN="your-personal-access-token"

# Optional: specify catalog and schema
export DATABRICKS_CATALOG="main"
export DATABRICKS_SCHEMA="benchbox"
```

**Finding your SQL Warehouse HTTP path:**
1. Open Databricks workspace
2. Go to SQL Warehouses
3. Click on your warehouse
4. Copy the "HTTP path" from Connection Details

**Creating a Personal Access Token:**
1. Click your username (top right)
2. User Settings → Developer → Access tokens
3. Generate new token

### Verify connection

```bash
# Quick connectivity test
uv run python -c "
from databricks import sql
import os

conn = sql.connect(
    server_hostname=os.environ['DATABRICKS_HOST'].replace('https://', ''),
    http_path=os.environ['DATABRICKS_HTTP_PATH'],
    access_token=os.environ['DATABRICKS_TOKEN']
)
cursor = conn.cursor()
cursor.execute('SELECT current_catalog()')
print('Connected to Databricks:', cursor.fetchone()[0])
cursor.close()
conn.close()
"
```

---

## Running the benchmarks

### Step 1: Validate with SF0.01

```bash
benchbox run --platform databricks --benchmark tpch --scale 0.01
```

Expected output:
```
BenchBox v0.2.0
Platform: Databricks SQL Warehouse
Benchmark: TPC-H SF0.01

[INFO] Generating data...
[INFO] Creating schema and loading data (Delta Lake)...
[INFO] Running power phase (22 queries)...
[SUCCESS] Completed in 12m 07s

Results saved to: benchmark_runs/results/tpch_sf001_databricks_20260131_143022.json
```

**What BenchBox does automatically:**
- Creates the benchmark catalog/schema in Unity Catalog
- Generates TPC-H data
- Creates Delta Lake tables with optimized settings
- Applies OPTIMIZE and ZORDER for better query performance
- Runs all 22 TPC-H queries
- Validates results against reference answers

### Step 2: Baseline at SF1

```bash
benchbox run --platform databricks --benchmark tpch --scale 1
```

This takes 30-60 minutes on a small SQL warehouse.

### Step 3: Try DataFrame mode

Databricks is one of the few platforms where BenchBox supports DataFrame mode:

```bash
benchbox run --platform databricks-df --benchmark tpch --scale 1
```

DataFrame mode uses PySpark operations instead of SQL. This can be useful for:
- Comparing SQL vs. DataFrame performance characteristics
- Evaluating Spark's DataFrame API
- Understanding optimizer differences

### Running specific queries

```bash
# Run only the join-heavy queries
benchbox run --platform databricks --benchmark tpch --scale 1 --queries Q2,Q8,Q9,Q21
```

---

## Reproducing and comparing

### Find your previous runs

> "Show me my recent Databricks benchmark runs"

Or via CLI:

```bash
ls -la benchmark_runs/results/ | grep databricks
```

### Compare SQL vs. DataFrame

If you ran both modes:

> "Compare my SQL and DataFrame runs on Databricks"

```
Comparison: SQL Warehouse vs DataFrame (PySpark)

Overall:
- SQL total: 38m 12s
- DataFrame total: 45m 33s

Notable differences:
- Q2: SQL 2m 10s, DataFrame 4m 30s (DataFrame 2x slower)
- Q17: SQL 3m 45s, DataFrame 3m 20s (DataFrame slightly faster)
- Q21: SQL 8m 12s, DataFrame 10m 05s (SQL faster on correlated subquery)

Notes:
- SQL uses Photon engine (optimized C++)
- DataFrame uses standard Spark execution
```

### Compare warehouse sizes

> "How did my SF1 results change between Small and Medium warehouses?"

---

## Trial traps to avoid

### 1. Using a personal email

**The trap**: Signing up with gmail.com or similar limits you to 50 DBU/hr, which restricts cluster sizes and makes larger benchmarks impractical.

**The fix**: Use a business email. If you don't have one, consider whether the Free Edition (ongoing, but non-commercial) meets your needs for initial learning.

### 2. Using All-Purpose compute for benchmarks

**The trap**: All-Purpose clusters cost 3-4x more per DBU than Jobs compute. A benchmark that costs 10 DBU on Jobs costs 30-40 DBU on All-Purpose.

**The fix**: Use SQL Warehouses for SQL benchmarks. They're optimized for analytical queries and cost less than All-Purpose.

### 3. Forgetting about cloud infrastructure costs

**The trap**: Databricks charges DBUs, but your cloud provider (AWS/Azure/GCP) also charges for the underlying VMs. Trial credits cover DBUs only.

**The fix**: Monitor both Databricks usage (in the workspace) and cloud provider billing. For trial evaluation, cloud costs are typically small, but be aware they exist.

### 4. Rushing the 14-day window

**The trap**: Trying to do everything in the first few days, burning credits on mistakes, then having nothing left for follow-up experiments.

**The fix**: Pace yourself. Days 1-3 for setup and validation, days 4-10 for systematic benchmarking, days 11-14 for buffer and exploration.

### 5. Not using Delta Lake optimizations

**The trap**: Creating basic tables without OPTIMIZE or ZORDER, resulting in slower queries and misleading benchmark results.

**The fix**: BenchBox applies Delta Lake optimizations automatically. If running manual queries, use:
```sql
OPTIMIZE your_table ZORDER BY (key_column);
```

### Cleanup checklist before trial ends

- [ ] Download result files from `benchmark_runs/results/`
- [ ] Export notebooks with analysis
- [ ] Document SQL Warehouse configurations that worked well
- [ ] Note any Unity Catalog or Delta Lake learnings
- [ ] Decide: configure cloud billing or let trial expire

---

## DBU consumption reference

Based on our testing with Small SQL Warehouses:

| Scale Factor | Load Time | Query Time | Total Time | Est. DBUs |
| ------------ | --------- | ---------- | ---------- | --------- |
| SF0.01       | ~5 min    | ~7 min     | ~12 min    | 2-3       |
| SF1          | ~15 min   | ~35 min    | ~50 min    | 8-12      |
| SF10         | ~45 min   | ~3 hours   | ~4 hours   | 35-50     |

DBU consumption varies by warehouse size and cluster configuration. These estimates assume a Small SQL Warehouse (2x-Small nodes). Larger warehouses consume more DBUs per hour but complete faster.

---

## Summary

Databricks' 14-day window is the shortest of any major platform, requiring efficient use of time. The keys to success:

1. **Use a business email** for full trial capabilities
2. **Use SQL Warehouses** (not All-Purpose) for cost-effective benchmarking
3. **Pace your evaluation** across the full 14 days
4. **Try both SQL and DataFrame modes** if comparing execution paths

BenchBox handles Delta Lake optimization, Unity Catalog setup, and query validation. You focus on understanding how Databricks performs at different scales.

---

## References

[^1]: [Databricks Free Trial](https://docs.databricks.com/aws/en/getting-started/free-trial) - Databricks Documentation
[^2]: [Databricks Pricing](https://www.databricks.com/product/pricing) - Databricks
[^3]: [Free Trial vs Free Edition](https://docs.databricks.com/aws/en/getting-started/free-trial-vs-free-edition) - Databricks Documentation

---

*Questions or feedback? [Open an issue](https://github.com/oxbow-analytics/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: ~1,700
**Series**: free-trial-benchmarking
**Post Number**: 2
