# Free trial benchmarking: Microsoft Fabric

> Microsoft Fabric offers a capacity-based trial: 64 CU over 60 days. Here's how to benchmark when you're throttled, not stopped.

**TL;DR**: Microsoft Fabric gives you 64 Capacity Units (CU) over 60 days. Unlike credit-based trials, exceeding capacity throttles you instead of stopping. Power BI license required (free tier works). Spark autoscale billing can reduce costs for batch benchmarks.

---

## What you get

**Trial details:**
- **Capacity**: 64 CU (or start at 4 CU, upgradeable)
- **Duration**: 60 days
- **Storage**: Up to 1 TB OneLake
- **Requirement**: Power BI license (free tier is sufficient)

**The Fabric difference: Capacity vs. credits**

Most platforms give you credits that run out. Fabric gives you capacity that throttles when exceeded:

| When Exceeded  | Credit-Based (e.g., Snowflake) | Capacity-Based (Fabric)      |
| -------------- | ------------------------------ | ---------------------------- |
| What happens   | Queries stop                   | Queries slow down            |
| Recovery       | Add credits or wait            | Wait for capacity to recover |
| Predictability | Hard stop                      | Gradual degradation          |

**Pricing model: Capacity Units (CU)**

CU bundles CPU, memory, disk I/O, and network:
- ~$0.18/CU-hour
- Spark: 1 CU = 2 Spark VCores
- SQL: 1 CU = 0.383 Database VCores

**What happens when trial ends:**
Trial capacity expires. Upgrade to paid capacity or export your data.

---

## Explore with MCP

Before consuming capacity, use the MCP server to preview your benchmark runs:

**Validate configuration:**

> "Can I run TPC-H on Microsoft Fabric with my current setup?"

The assistant calls `validate_config(platform="fabric_dw", benchmark="tpch")` (or `fabric-spark` for Spark mode) and reports any issues.

**Preview resource consumption:**

> "What would a TPC-H SF1 run on Fabric look like?"

```
# Example MCP dry_run response
Platform: Microsoft Fabric (Warehouse)
Benchmark: TPC-H SF1
Estimated data size: ~1 GB
Tables: 8 (nation, region, part, supplier, partsupp, customer, orders, lineitem)
Queries: 22
Phases: load, power

Notes:
- Uses Fabric Data Warehouse (SQL mode) or Spark (DataFrame mode)
- Capacity-based: throttled if exceeded, not stopped
- Data stored in OneLake (included in trial storage)
```

**Check available modes:**

> "What's the difference between Fabric Warehouse and Spark modes in BenchBox?"

BenchBox supports both:
- **SQL mode** (`fabric_dw`): Uses Fabric Data Warehouse, T-SQL queries
- **DataFrame mode** (`fabric-spark`): Uses Fabric Spark pools, PySpark operations

---

## The game plan

### Understanding capacity throttling

Fabric's throttling is progressive:

| Phase   | Trigger                     | Effect                                       |
| ------- | --------------------------- | -------------------------------------------- |
| Buffer  | 10-min future capacity used | No impact                                    |
| Phase 1 | Continued overage           | 20-second delays on new operations           |
| Phase 2 | Heavy overage               | New interactive operations rejected          |
| Phase 3 | Severe overage              | All new requests rejected (24-hour recovery) |

For benchmarking, this means:
- Small benchmarks: Run without issue
- Large benchmarks: May hit throttling, queries slow down
- Recovery: Capacity recovers over time

### Capacity math

With 64 CU trial capacity:

| Workload             | CU Consumed | Sustainable? |
| -------------------- | ----------- | ------------ |
| SF0.01 benchmark     | ~2-4 CU     | Yes          |
| SF1 benchmark        | ~10-20 CU   | Yes          |
| SF10 benchmark       | ~40-60 CU   | Borderline   |
| Concurrent workloads | Adds up     | May throttle |

**Spark autoscale billing** (for DataFrame mode):
- 0.5 CU-hour per Spark job
- Charged only during active execution
- More efficient for batch workloads

### The scaling progression

1. **SF0.01 with Warehouse**: Validate SQL connectivity (~10 minutes)
2. **SF0.01 with Spark**: Validate DataFrame connectivity (~15 minutes)
3. **SF1 with Warehouse**: SQL benchmark (~1 hour)
4. **SF1 with Spark**: DataFrame benchmark for comparison (~1 hour)

---

## BenchBox setup

### Install dependencies

```bash
# For Fabric Data Warehouse (SQL mode)
uv add pyodbc azure-identity azure-storage-file-datalake

# For Fabric Spark (DataFrame mode)
uv add azure-identity azure-storage-file-datalake requests
```

### Configuration: Fabric Data Warehouse (SQL)

```bash
# Fabric workspace connection
export FABRIC_WORKSPACE_ID="your-workspace-id"
export FABRIC_WAREHOUSE_ID="your-warehouse-id"

# Azure authentication
export AZURE_TENANT_ID="your-tenant-id"
export AZURE_CLIENT_ID="your-client-id"
export AZURE_CLIENT_SECRET="your-client-secret"

# Or use Azure CLI authentication
az login
```

**Finding your workspace and warehouse IDs:**

1. Open Fabric portal (app.fabric.microsoft.com)
2. Navigate to your workspace
3. Open Data Warehouse
4. URL contains both IDs: `.../workspace/{workspace-id}/warehouse/{warehouse-id}`

### Configuration: Fabric Spark (DataFrame)

```bash
# Same workspace configuration
export FABRIC_WORKSPACE_ID="your-workspace-id"
export FABRIC_LAKEHOUSE_ID="your-lakehouse-id"

# Azure authentication (same as above)
export AZURE_TENANT_ID="your-tenant-id"
export AZURE_CLIENT_ID="your-client-id"
export AZURE_CLIENT_SECRET="your-client-secret"
```

### Verify connection

```bash
# Test Fabric Data Warehouse connection
uv run python -c "
import pyodbc
from azure.identity import DefaultAzureCredential
import struct

credential = DefaultAzureCredential()
token = credential.get_token('https://database.windows.net/.default')

# Build connection string (simplified)
print('Authentication successful, token obtained')
print('Full connection test requires Fabric-specific ODBC driver setup')
"
```

---

## Running the benchmarks

### Step 1: Check capacity status

Before benchmarking, check your trial capacity in Fabric portal:

1. Fabric portal → Settings → Capacity
2. View current usage vs. available capacity
3. Ensure you have headroom for your planned benchmark

### Step 2: Validate with SF0.01 (SQL mode)

```bash
benchbox run --platform fabric_dw --benchmark tpch --scale 0.01
```

Expected output:
```
BenchBox v0.2.0
Platform: Microsoft Fabric Data Warehouse
Benchmark: TPC-H SF0.01

[INFO] Generating data...
[INFO] Creating schema and loading data...
[INFO] Running power phase (22 queries)...
[SUCCESS] Completed in 12m 45s

Results saved to: benchmark_runs/results/tpch_sf001_fabric_dw_20260131_143022.json
```

**What BenchBox does automatically:**
- Creates tables in your Fabric warehouse
- Generates TPC-H data and uploads to OneLake
- Applies Fabric-optimized table configurations
- Runs all 22 TPC-H queries
- Validates results against reference answers

### Step 3: Try Spark mode (DataFrame)

```bash
benchbox run --platform fabric-spark --benchmark tpch --scale 0.01
```

Spark mode uses Fabric's Spark pools with PySpark DataFrame operations.

### Step 4: Scale up

```bash
# SQL mode at SF1
benchbox run --platform fabric_dw --benchmark tpch --scale 1

# Spark mode at SF1
benchbox run --platform fabric-spark --benchmark tpch --scale 1
```

Monitor capacity consumption in Fabric portal during runs.

### Running specific queries

```bash
# Run specific queries
benchbox run --platform fabric_dw --benchmark tpch --scale 1 --queries Q1,Q6,Q14
```

---

## Reproducing and comparing

### Find your previous runs

> "Show me my recent Fabric benchmark runs"

Or via CLI:

```bash
ls -la benchmark_runs/results/ | grep fabric
```

### Compare SQL vs. Spark modes

> "Compare my Fabric Warehouse and Spark runs"

```
Comparison: Fabric Data Warehouse vs Fabric Spark (SF1)

Overall:
- Data Warehouse total: 45m 12s
- Spark total: 52m 30s

Notable differences:
- Q6: DW 25s, Spark 45s (SQL optimizer advantage)
- Q1: DW 40s, Spark 1m 10s
- Q21: DW 8m, Spark 9m 30s

Notes:
- Data Warehouse optimized for SQL analytics
- Spark provides more flexibility for complex transformations
- Both use OneLake storage (no data duplication)
```

### Monitor capacity impact

> "How much capacity did my SF1 benchmark use?"

Check Fabric portal → Capacity metrics after each run.

---

## Trial traps to avoid

### 1. Not having a Power BI license

**The trap**: Trying to start Fabric trial without any Power BI license. Trial requires at least Power BI Free.

**The fix**: Sign up for Power BI Free first (free.powerbi.com), then start Fabric trial.

### 2. Running concurrent workloads

**The trap**: Running multiple benchmarks or mixing benchmarking with other Fabric workloads (Power BI, Data Factory, etc.). Capacity is shared across all workloads.

**The fix**: Run benchmarks in isolation. Pause or reduce other workloads during benchmark sessions.

### 3. Hitting throttling during benchmark

**The trap**: Starting a large benchmark, hitting Phase 2 throttling mid-run, and getting inconsistent results.

**The fix**: Start with smaller scale factors. Monitor capacity during initial runs. If throttling occurs, results may not be representative.

### 4. Trial capacity cannot be paused

**The trap**: Expecting to pause trial capacity when not using it (like other platforms). Fabric trial capacity is "use it or lose it" over 60 days.

**The fix**: Plan benchmarking sessions across the 60-day window. Unlike credit-based trials, you can't "save" capacity for later.

### 5. Ignoring Spark autoscale billing

**The trap**: Using default Spark pools which may consume more CU than necessary.

**The fix**: For benchmarking, consider Spark autoscale (0.5 CU-hour per job). Configure in Fabric portal → Workspace settings → Spark.

### Cleanup checklist before trial ends

- [ ] Download result files from `benchmark_runs/results/`
- [ ] Export data from OneLake if needed
- [ ] Document capacity consumption patterns
- [ ] Note differences between Warehouse and Spark modes
- [ ] Decide: upgrade to paid capacity or export data

---

## Capacity consumption reference

Based on our testing with default configurations:

| Scale Factor | Mode      | Est. Time  | Est. CU |
| ------------ | --------- | ---------- | ------- |
| SF0.01       | Warehouse | ~15 min    | ~2-4    |
| SF0.01       | Spark     | ~20 min    | ~3-5    |
| SF1          | Warehouse | ~1 hour    | ~10-15  |
| SF1          | Spark     | ~1.5 hours | ~12-18  |
| SF10         | Warehouse | ~5 hours   | ~40-60  |

Capacity consumption varies by query complexity and concurrent usage. Monitor Fabric portal for actual consumption.

---

## Summary

Microsoft Fabric's capacity-based model is different from credit-based trials. The keys to success:

1. **Understand throttling** (queries slow down, don't stop)
2. **Monitor capacity** in Fabric portal during benchmarks
3. **Run in isolation** (don't compete with other workloads)
4. **Try both modes** (Warehouse SQL and Spark DataFrame)

BenchBox handles both Fabric execution modes, OneLake integration, and query validation. You focus on understanding Fabric's performance characteristics.

---

## References

[^1]: [Microsoft Fabric Trial](https://learn.microsoft.com/en-us/fabric/fundamentals/fabric-trial) - Microsoft Documentation
[^2]: [Fabric Pricing](https://azure.microsoft.com/en-us/pricing/details/microsoft-fabric/) - Azure Documentation
[^3]: [Fabric Spark Billing](https://learn.microsoft.com/en-us/fabric/data-engineering/billing-capacity-management-for-spark) - Microsoft Documentation
[^4]: [Fabric Throttling](https://learn.microsoft.com/en-us/fabric/enterprise/throttling) - Microsoft Documentation

---

*Questions or feedback? [Open an issue](https://github.com/oxbow-analytics/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: ~1,750
**Series**: free-trial-benchmarking
**Post Number**: 8
