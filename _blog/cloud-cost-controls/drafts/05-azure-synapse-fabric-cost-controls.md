# Azure Synapse and Fabric cost controls for benchmarking

*Part 5 of the Cloud Cost Controls for Benchmarking series*

> DWU caps, pause/resume, and capacity management for predictable analytics benchmark costs on Microsoft's platforms.

**TL;DR**: Azure offers three distinct analytics pricing models: Synapse dedicated pools (DWU-hours), Synapse serverless (per-TB scanned), and Fabric (capacity units). Synapse dedicated pools have no auto-pause and require manual intervention. Serverless pools support data processing limits. Azure Budgets are informational by default, requiring Action Groups with Logic Apps for automated enforcement.

*For series methodology, pricing scope, and cross-platform comparison, see the [series introduction](00-series-intro.md).*

---

## Three platforms, three pricing models

Microsoft's analytics stack includes multiple options, each with different cost characteristics:

| Service | Pricing Model | Example Cost | Auto-Pause |
|---------|---------------|--------------|------------|
| Synapse Dedicated SQL Pool | DWU-hours | DW100c ~$1,100/month (24x7)[^1] | No |
| Synapse Serverless SQL Pool | Per-TB scanned | ~$5/TB[^2] | N/A |
| Synapse Spark Pool | Per-vCore-hour | ~$0.14/vCore-hour | Yes |
| Microsoft Fabric | Capacity units (CU) | F2 ~$263/month[^3] | Manual |

**The challenge for benchmarking**: Synapse dedicated pools have no auto-pause (unlike Snowflake's auto-suspend). If you forget to pause a pool, it charges continuously. Azure Budgets can alert you, but unlike AWS Budget Actions, they can't automatically stop resources without custom automation.

**Platform status**: Microsoft offers both Fabric (SaaS, unified platform) and Synapse (PaaS, separate pools). As of early 2026, both are actively supported with no announced deprecation for Synapse, making either viable for benchmarking.

---

## Azure Synapse Dedicated SQL Pool

Dedicated SQL pools use Data Warehouse Units (DWU) as the billing metric. Each DWU level represents a combination of CPU, memory, and I/O capacity.

### DWU pricing

| DWU Level | Compute Nodes | Hourly Cost | Monthly (24x7) |
|-----------|---------------|-------------|----------------|
| DW100c | 1 | ~$1.51 | ~$1,100 |
| DW500c | 1 | ~$7.55 | ~$5,500 |
| DW1000c | 2 | ~$15.10 | ~$11,000 |
| DW3000c | 6 | ~$45.30 | ~$33,000 |
| DW6000c | 12 | ~$90.60 | ~$66,000 |

**Billing model**:
- **Billed hourly, rounded up** (not per-second like Snowflake or Databricks). A 5-minute query on DW1000c costs the same as a 55-minute query: ~$15.10. This is the most significant cost difference from other platforms in this series.
- Storage billed separately (~$0.02/GB/month)
- 7 days of incremental snapshots included
- Reserved capacity: up to 65% discount for 3-year commitment[^1]

### Pause/resume: your primary control

Synapse dedicated pools have no auto-pause[^4]. You must pause manually or via automation.

**Azure CLI**:

```bash
# Pause (stops compute charges)
az synapse sql pool pause \
  --name benchmark-pool \
  --workspace-name my-workspace \
  --resource-group my-rg

# Resume (starts compute charges)
az synapse sql pool resume \
  --name benchmark-pool \
  --workspace-name my-workspace \
  --resource-group my-rg

# Scale DWU level
az synapse sql pool update \
  --name benchmark-pool \
  --workspace-name my-workspace \
  --resource-group my-rg \
  --performance-level DW500c
```

**PowerShell**:

```powershell
Suspend-AzSynapseSqlPool -WorkspaceName "my-workspace" -Name "benchmark-pool"
Resume-AzSynapseSqlPool -WorkspaceName "my-workspace" -Name "benchmark-pool"
```

**Behavior**:
- Paused: $0 compute, storage continues charging
- Resume: 1-2 minutes
- Running transactions canceled on pause

**Best practice for benchmarks**: Pause pools when not running benchmarks. Pausing overnight and weekends reduces compute costs by 60-70%.

### Workload groups for resource isolation

Workload groups let you cap resource consumption for specific users or workloads[^6]:

```sql
-- Create workload group with resource limits
CREATE WORKLOAD GROUP benchmark_wg
WITH (
  MIN_PERCENTAGE_RESOURCE = 10,     -- Guaranteed minimum
  CAP_PERCENTAGE_RESOURCE = 50,     -- Maximum allowed
  REQUEST_MIN_RESOURCE_GRANT_PERCENT = 5
);

-- Assign users to workload group
CREATE WORKLOAD CLASSIFIER benchmark_classifier
WITH (
  WORKLOAD_GROUP = 'benchmark_wg',
  MEMBERNAME = 'benchmark_user'
);
```

**CAP_PERCENTAGE_RESOURCE**: Limits maximum resource consumption. When the cap is reached, queries wait (they're not rejected).

---

## Azure Synapse Serverless SQL Pool

Serverless pools charge per-TB scanned, similar to BigQuery and Athena.

### Pricing

- **~$5 per TB scanned**
- No provisioned compute to manage
- 10 MB minimum per query
- DDL statements (CREATE/ALTER/DROP) are free

### Data processed limits

Unlike dedicated pools, serverless pools support aggregate data limits:

```sql
-- Set daily limit (1 TB = ~$5/day max)
EXEC sp_set_data_processed_limit @type = N'daily', @limit_tb = 1

-- Set weekly limit
EXEC sp_set_data_processed_limit @type = N'weekly', @limit_tb = 5

-- Set monthly limit
EXEC sp_set_data_processed_limit @type = N'monthly', @limit_tb = 20
```

**Behavior**: When the limit is exceeded, queries are rejected with the error: "Query is rejected because SQL Serverless budget limit for a period is exceeded."

**UI access**: Synapse Studio > Manage > SQL pools > Serverless > Cost control icon

**Trade-off for benchmarks**: A 2 TB/day limit caps spending at ~$10/day. Size the limit based on your expected benchmark data volume plus a buffer for debugging iterations.

---

## Azure Synapse Spark Pool

Spark pools charge per-vCore-hour and support auto-pause (unlike dedicated SQL pools).

### Pricing

- **~$0.14 per vCore-hour**, prorated by minute
- Minimum 3 nodes per pool instance (1 head + 2 workers)
- No charge for pool definition; only when jobs execute

### Auto-pause configuration

```bash
# Create Spark pool with auto-pause
az synapse spark pool create \
  --name benchmark-spark \
  --workspace-name my-workspace \
  --resource-group my-rg \
  --node-count 3 \
  --node-size Medium \
  --enable-auto-pause true \
  --delay 15  # minutes before auto-pause
```

**Behavior**:
- Default auto-pause: 15 minutes idle
- Pool definitions are free; charges only when jobs run

**WARNING: Synapse Studio prevents auto-pause.** Synapse Studio sends keep-alive signals to Spark pools. If you leave a browser tab open with Synapse Studio, the pool won't auto-pause even if no jobs are running. Close your browser session when you're done, or the pool will continue consuming credits indefinitely. This is one of the most common sources of unexpected Spark pool charges. Use CLI-based workflows (BenchBox or `az synapse spark`) to avoid this trap entirely.

### Autoscale with limits

```bash
az synapse spark pool update \
  --name benchmark-spark \
  --workspace-name my-workspace \
  --resource-group my-rg \
  --enable-auto-scale true \
  --min-node-count 3 \
  --max-node-count 10
```

---

## Microsoft Fabric

Fabric uses Capacity Units (CU) as its billing metric. A single capacity pool serves all Fabric workloads (Data Factory, Data Warehouse, Spark, Power BI, etc.).

### Pricing

| SKU | Capacity Units | Pay-as-You-Go/Month | Reserved/Month |
|-----|----------------|---------------------|----------------|
| F2 | 2 | ~$263 | ~$155 |
| F4 | 4 | ~$526 | ~$310 |
| F8 | 8 | ~$1,052 | ~$620 |
| F16 | 16 | ~$2,104 | ~$1,240 |
| F32 | 32 | ~$4,208 | ~$2,480 |
| F64 | 64 | ~$8,417 | ~$4,960 |

- **~$0.18 per CU-hour** (varies by region)
- Billed per minute with 1-minute minimum
- Reserved capacity: ~41% discount for 1-year commitment[^3]
- F64+ includes Power BI Pro license (otherwise ~$10-14/user/month)

**Storage**: OneLake storage is billed separately at ~$23/TB/month.

### Capacity pause/resume

Fabric capacities can be paused when not in use[^5].

**Azure CLI**:

```bash
# Pause Fabric capacity
az fabric capacity suspend \
  --resource-group my-rg \
  --capacity-name my-fabric-capacity

# Resume Fabric capacity
az fabric capacity resume \
  --resource-group my-rg \
  --capacity-name my-fabric-capacity
```

`az fabric` commands require the `microsoft-fabric` Azure CLI extension. Install with `az extension add --name microsoft-fabric`. Verify availability with `az fabric -h` before automating.

**Behavior**:
- Paused: $0 compute, OneLake storage continues charging
- Resume: 1-2 minutes
- No built-in scheduled pause (requires automation)

### Throttling and smoothing

Fabric has automatic capacity management[^7]:

1. **Bursting**: Short-term usage can exceed allocated CUs (F4 can briefly burst to ~64 CUs)
2. **Smoothing**: Usage averaged over time windows (5 min for interactive, 24 hr for background)
3. **Throttling**: Progressive delay when sustained overuse detected

| Stage | Trigger | Effect |
|-------|---------|--------|
| None | < 100% | Normal operation |
| Delayed | 100-110% | Interactive requests delayed |
| Rejected | > 110% sustained | Interactive requests rejected |

**Key point**: Throttling slows queries but doesn't provide a hard cost cap. It prevents runaway performance degradation, not runaway costs.

---

## Layered cost controls

Following the series pattern:

```text
+-----------------------------------------------------------+
|  Layer 3: Subscription-level budgets + Action Groups       |
|  - Email alerts at thresholds                              |
|  - Logic App/Function for automated pause (if configured)  |
+-----------------------------------------------------------+
|  Layer 2: Workload management                              |
|  - Synapse: Workload groups with CAP_PERCENTAGE_RESOURCE   |
|  - Fabric: Throttling/smoothing (built-in)                 |
+-----------------------------------------------------------+
|  Layer 1: Pool/capacity-level controls                     |
|  - Synapse Dedicated: Pause/resume (manual or scripted)    |
|  - Synapse Serverless: sp_set_data_processed_limit         |
|  - Synapse Spark: Auto-pause with idle timeout             |
|  - Fabric: Capacity pause/resume                           |
+-----------------------------------------------------------+
```

---

## Azure Budgets and Action Groups

### Creating a budget

Azure Budgets can be created via CLI or portal[^8]:

```bash
az consumption budget create \
  --budget-name "Synapse-Benchmark-Budget" \
  --amount 500 \
  --category Cost \
  --time-grain Monthly \
  --resource-group my-synapse-rg \
  --notifications '[{
    "enabled": true,
    "operator": "GreaterThan",
    "threshold": 80,
    "contactEmails": ["you@example.com"]
  }]'
```

### The enforcement gap

**Critical limitation**: Azure Budgets are informational by default. Unlike AWS Budget Actions (which can attach IAM deny policies), Azure requires custom automation for enforcement.

To automatically pause resources when a budget threshold is reached:

1. Budget alert triggers Action Group
2. Action Group calls Logic App or Azure Function
3. Function calls `az synapse sql pool pause` or Fabric suspend API

This is more complex than AWS's native Budget Actions, but provides flexibility for custom logic (e.g., pause only benchmark pools, not production).

---

## How Azure compares

For the full cross-platform comparison, see the [series introduction](00-series-intro.md). The key Azure-specific differences:

- **Hourly billing minimum** for Synapse Dedicated is unique in this series. Every other platform bills per-second or per-query. A short benchmark on DW1000c costs a minimum of $15.10 regardless of duration.
- **No native budget enforcement**: Like Databricks, Azure Budgets are informational only. Automated response requires Action Groups with Logic Apps.
- **Synapse Serverless is the bright spot**: `sp_set_data_processed_limit` provides aggregate daily limits similar to BigQuery quotas, and at the same $5/TB price point as Athena.
- **Fabric lacks per-query limits**: Throttling manages performance degradation but doesn't cap costs.

---

## Complete setup example

### For Synapse Dedicated + Serverless

```bash
# Layer 1a: Keep pool paused when not benchmarking
az synapse sql pool pause \
  --name benchmark-pool \
  --workspace-name my-ws \
  --resource-group my-rg

# Layer 1b: Set serverless data limits (via T-SQL)
# EXEC sp_set_data_processed_limit @type = N'daily', @limit_tb = 2

# Layer 3: Create budget with alerts
az consumption budget create \
  --budget-name "Synapse-Benchmark" \
  --amount 100 \
  --time-grain Monthly \
  --resource-group my-synapse-rg
```

### For Fabric

```bash
# Layer 1: Pause capacity when not in use
az fabric capacity suspend \
  --capacity-name my-fabric \
  --resource-group my-rg

# Layer 3: Create budget with alerts
az consumption budget create \
  --budget-name "Fabric-Benchmark" \
  --amount 500 \
  --time-grain Monthly
```

### Resulting protection

| Service | Control | Limit | Enforcement |
|---------|---------|-------|-------------|
| Synapse Dedicated | Pause/resume | Manual | Compute stops |
| Synapse Serverless | Data limit | 2 TB/day | Query rejected |
| Synapse Spark | Auto-pause | 15 min idle | Pool suspends |
| Fabric | Pause/resume | Manual | Compute stops |
| All | Budget | $X/month | Email alert |

---

## Estimated benchmark costs

The tables below are planning estimates derived from published unit rates and simplified runtime assumptions; use your own telemetry for chargeback/forecasting.

### Synapse Dedicated SQL Pool

| Scale Factor | Recommended DWU | Est. Query Time | Est. Cost |
|--------------|-----------------|-----------------|-----------|
| SF1 | DW100c | ~5 min | ~$0.13 |
| SF10 | DW500c | ~15 min | ~$1.90 |
| SF100 | DW1000c | ~45 min | ~$11.30 |

*Assumes pool is paused before/after benchmark.*

### Synapse Serverless SQL Pool

| Scale Factor | Data Size | Est. TB Scanned | Est. Cost |
|--------------|-----------|-----------------|-----------|
| SF1 | ~1 GB | ~0.02 TB | ~$0.10 |
| SF10 | ~10 GB | ~0.2 TB | ~$1.00 |
| SF100 | ~100 GB | ~2 TB | ~$10.00 |

*Parquet format with column pruning can reduce scanned data by 50-80%.*

### Microsoft Fabric

| Scale Factor | Recommended SKU | Est. Query Time | Est. CU Cost |
|--------------|-----------------|-----------------|--------------|
| SF1 | F2 | ~10 min | ~$0.06 |
| SF10 | F4 | ~20 min | ~$0.35 |
| SF100 | F8-F16 | ~60 min | ~$2-4 |

*Fabric costs depend heavily on workload type (SQL, Spark, or Data Pipeline) and CU burst behavior. These estimates assume Fabric Data Warehouse queries on a paused-then-resumed capacity.*

---

## Limitations

### What pause doesn't cover

- **Storage costs**: Data warehouse storage continues charging (~$0.02/GB/month)
- **Snapshot storage**: Beyond 7 days of included snapshots
- **OneLake storage**: ~$23/TB/month continues when Fabric is paused

### Platform limitations

| Platform | Limitation |
|----------|------------|
| Synapse Dedicated | No auto-pause; **hourly billing minimum** (significant cost impact vs per-second billing) |
| Synapse Serverless | No per-query byte limit (only aggregate) |
| Synapse Spark | Keep-alive from Synapse Studio prevents auto-pause |
| Fabric | No built-in scheduled pause; no hard cost cap from throttling |

### Budget limitations

- Informational only (no native enforcement)
- Requires Action Group + Logic App for automated response
- More complex than AWS's native Budget Actions

---

## Conclusions

Azure's analytics platforms require more manual intervention than AWS or Snowflake.

**Key takeaways**:

1. **Synapse Dedicated requires manual pause**: Unlike Snowflake's auto-suspend, you must pause pools explicitly. Automation via Logic Apps is recommended.

2. **Synapse Serverless has data processing limits**: Use `sp_set_data_processed_limit` for aggregate daily/weekly/monthly caps.

3. **Fabric capacities can be paused**: But require external automation for scheduling.

4. **Azure Budgets are informational**: Automated enforcement requires Action Groups with Logic Apps or Azure Functions.

5. **Synapse Spark is the exception**: It supports auto-pause, similar to Snowflake's behavior.

**Next in series**: The AWS Free Tier trap, what happens when an account joins an Organization, and why your "free" analytics benchmarks cost money.

---

## References

[^1]: [Azure Synapse Analytics Pricing](https://azure.microsoft.com/en-us/pricing/details/synapse-analytics/), Microsoft Azure. DWU rates and reserved capacity.

[^2]: [Cost management for serverless SQL pool](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql/data-processed), Microsoft Learn. Per-TB pricing and data limits.

[^3]: [Microsoft Fabric Pricing](https://azure.microsoft.com/en-us/pricing/details/microsoft-fabric/), Microsoft Azure. CU rates and reserved discounts.

[^4]: [Pause and resume compute in dedicated SQL pool](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql-data-warehouse/pause-and-resume-compute-portal), Microsoft Learn. Pause/resume behavior.

[^5]: [Pause and resume your capacity (Fabric)](https://learn.microsoft.com/en-us/fabric/enterprise/pause-resume), Microsoft Learn. Fabric capacity management.

[^6]: [Workload management](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql-data-warehouse/sql-data-warehouse-workload-management), Microsoft Learn. Workload groups.

[^7]: [Understand your Fabric capacity throttling](https://learn.microsoft.com/en-us/fabric/enterprise/throttling), Microsoft Learn. Throttling behavior.

[^8]: [Create and manage budgets](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets), Microsoft Learn. Budget and Action Groups.

---

*Questions or feedback? [Open an issue](https://github.com/benchbox/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: 2496
**Created**: 2026-02-01
**Series**: Cloud Cost Controls for Benchmarking (Post 5: Azure)
