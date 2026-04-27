# Azure Synapse and Microsoft Fabric Cost Controls Research

**Research Date**: 2026-02-01
**Status**: Complete
**For Post**: #5 - Azure Synapse and Fabric cost controls for benchmarking

---

## Platform Overview

Azure Synapse Analytics and Microsoft Fabric represent Microsoft's analytics offerings:

| Platform | Type | Primary Use Case |
|----------|------|------------------|
| Azure Synapse Dedicated SQL Pools | PaaS | Data warehousing with DWU-based compute |
| Azure Synapse Serverless SQL Pools | PaaS | Ad-hoc querying of data lake (per-TB) |
| Azure Synapse Spark Pools | PaaS | Big data processing (per-vCore) |
| Microsoft Fabric | SaaS | Unified analytics platform (CU-based) |

**Key distinction**: Synapse is PaaS (you manage pools), Fabric is SaaS (unified capacity pool). Microsoft positions Fabric as the successor to Synapse, though Synapse remains supported with no announced end-of-life.

**Sources**:
- [Microsoft Fabric vs Azure Synapse: Architecture & Features](https://atlan.com/microsoft-fabric-vs-azure-synapse/) - Atlan
- [Microsoft Fabric vs Azure Synapse 2025 Breakdown](https://kanerika.com/blogs/fabric-vs-synapse/) - Kanerika
- [Azure Synapse vs Fabric: 9 Things You Should Know](https://www.chaosgenius.io/blog/azure-synapse-vs-fabric/) - ChaosGenius

---

## Pricing Summary

### Azure Synapse Dedicated SQL Pools (DWU-Based)

| DWU Level | Compute Nodes | Credits/Hour (est.) | Monthly (24x7) |
|-----------|---------------|---------------------|----------------|
| DW100c | 1 | ~$1.51 | ~$1,100 |
| DW500c | 1 | ~$7.55 | ~$5,500 |
| DW1000c | 2 | ~$15.10 | ~$11,000 |
| DW3000c | 6 | ~$45.30 | ~$33,000 |
| DW6000c | 12 | ~$90.60 | ~$66,000 |
| DW30000c | 60 | ~$453.00 | ~$330,000 |

**Billing model**:
- Billed hourly (rounded up) based on highest DWU during that hour
- Per-second billing NOT available for dedicated pools
- Storage billed separately (~$0.02-0.03/GB/month)
- 7 days of incremental snapshots included

**Reserved capacity savings**: Up to 65% for 1-year or 3-year commitments.

**Sources**:
- [Azure Synapse Analytics Pricing](https://azure.microsoft.com/en-us/pricing/details/synapse-analytics/) - Microsoft Azure
- [Azure Synapse Pricing: A Complete Cost & Savings Guide](https://www.pump.co/blog/azure-synapse-pricing) - Pump
- [Save on Azure Synapse Analytics - Dedicated SQL pool charges](https://learn.microsoft.com/en-us/azure/cost-management-billing/reservations/prepay-sql-data-warehouse-charges) - Microsoft Learn

### Azure Synapse Serverless SQL Pools (Per-TB)

| Metric | Value |
|--------|-------|
| Price per TB scanned | ~$5.00 |
| Minimum charge per query | 10 MB |
| DDL statements | Free |
| Created with workspace | Yes (no idle cost) |

**Billing model**:
- Charged for bytes read from storage + metadata
- No provisioned compute to manage
- Similar to BigQuery on-demand pricing

**Sources**:
- [Cost management for serverless SQL pool](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql/data-processed) - Microsoft Learn
- [Serverless SQL pool - Azure Synapse Analytics](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql/on-demand-workspace-overview) - Microsoft Learn

### Azure Synapse Spark Pools (Per-vCore)

| Node Size | vCores | Memory | Approx. Cost/vCore-Hour |
|-----------|--------|--------|-------------------------|
| Small | 4 | 32 GB | ~$0.14 |
| Medium | 8 | 64 GB | ~$0.14 |
| Large | 16 | 128 GB | ~$0.14 |
| X-Large | 32 | 256 GB | ~$0.14 |
| XX-Large | 64 | 432 GB | ~$0.14 |

**Billing model**:
- Per-vCore-hour, prorated by minute
- Minimum 3 nodes per pool instance (1 head + 2 workers)
- No charge for pool definition; only when jobs execute
- Auto-pause after configurable idle timeout

**Sources**:
- [Apache Spark pool concepts](https://learn.microsoft.com/en-us/azure/synapse-analytics/spark/apache-spark-pool-configurations) - Microsoft Learn
- [Plan to manage costs for Azure Synapse Analytics](https://learn.microsoft.com/en-us/azure/synapse-analytics/plan-manage-costs) - Microsoft Learn

### Microsoft Fabric Capacity Units (CU-Based)

| SKU | Capacity Units | Pay-as-You-Go/Month | Reserved/Month | Notes |
|-----|----------------|---------------------|----------------|-------|
| F2 | 2 | ~$263 | ~$155 | Development/test |
| F4 | 4 | ~$526 | ~$310 | Small workloads |
| F8 | 8 | ~$1,052 | ~$620 | |
| F16 | 16 | ~$2,104 | ~$1,240 | |
| F32 | 32 | ~$4,208 | ~$2,480 | |
| F64 | 64 | ~$8,417 | ~$4,960 | No Pro license needed |
| F128 | 128 | ~$16,834 | ~$9,920 | |
| F256 | 256 | ~$33,668 | ~$19,840 | |
| F512 | 512 | ~$67,337 | ~$39,680 | |
| F2048 | 2048 | ~$269,107 | ~$158,720 | Enterprise scale |

**Billing model**:
- ~$0.18 per CU-hour (varies by region ~10-15%)
- Single capacity pool serves all Fabric workloads
- Billed per minute with 1-minute minimum
- Can pause/resume capacity for cost savings

**Reserved capacity**: ~41% discount for 1-year commitment.

**Storage** (OneLake): ~$0.023/GB/month ($23/TB/month), billed separately from CUs.

**Sources**:
- [Microsoft Fabric Pricing](https://azure.microsoft.com/en-us/pricing/details/microsoft-fabric/) - Microsoft Azure
- [Microsoft Fabric Capacity Pricing - A Clear & Practical Breakdown](https://www.synapx.com/microsoft-fabric-pricing-guide-2025/) - Synapx
- [OneLake consumption](https://learn.microsoft.com/en-us/fabric/onelake/onelake-consumption) - Microsoft Learn

---

## Cost Control Mechanisms

### Layer 1: Pool/Capacity-Level Controls

#### Synapse Dedicated SQL Pool: Pause/Resume

**Description**: Stop compute charges entirely by pausing the pool.

**Azure CLI**:
```bash
# Pause a SQL pool
az synapse sql pool pause \
  --name benchmark-pool \
  --workspace-name my-workspace \
  --resource-group my-rg

# Resume a SQL pool
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

**Key behaviors**:
- Paused pool: $0 compute, storage continues charging
- Resume takes 1-2 minutes
- Running transactions canceled on pause
- DWU changes take effect immediately (billed at new rate)

**Best practice for benchmarks**: Pause pools when not running benchmarks. A pool paused overnight and weekends reduces compute costs by 60-70%.

**Sources**:
- [Pause and resume compute in dedicated SQL pool via the Azure portal](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql-data-warehouse/pause-and-resume-compute-portal) - Microsoft Learn
- [Manage compute resources for dedicated SQL pool](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql-data-warehouse/sql-data-warehouse-manage-compute-overview) - Microsoft Learn

#### Synapse Serverless SQL Pool: Data Processed Limits

**Description**: Daily, weekly, or monthly caps on terabytes scanned.

**T-SQL syntax**:
```sql
-- Set daily limit to 1 TB
EXEC sp_set_data_processed_limit @type = N'daily', @limit_tb = 1

-- Set weekly limit to 5 TB
EXEC sp_set_data_processed_limit @type = N'weekly', @limit_tb = 5

-- Set monthly limit to 20 TB
EXEC sp_set_data_processed_limit @type = N'monthly', @limit_tb = 20
```

**Synapse Studio UI**: Manage > SQL pools > Serverless > Cost control icon

**Key behaviors**:
- Queries rejected when limit exceeded
- Error: "Query is rejected because SQL Serverless budget limit for a period is exceeded"
- Limits reset at midnight (timezone not specified in docs)
- Can be set via UI or T-SQL

**Trade-off for benchmarks**: A limit of 1 TB/day = ~$5/day max spend. Size based on expected benchmark data volume.

**Sources**:
- [Cost management for serverless SQL pool](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql/data-processed) - Microsoft Learn
- [Cost Control in Synapse Analytics Serverless SQL](https://data-mozart.com/cost-control-in-synapse-analytics-serverless-sql-easy-way/) - Data Mozart

#### Synapse Spark Pool: Auto-Pause and Node Limits

**Description**: Automatic suspension of idle Spark pools and resource caps.

**Configuration options**:
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

# Enable autoscale with limits
az synapse spark pool update \
  --name benchmark-spark \
  --workspace-name my-workspace \
  --resource-group my-rg \
  --enable-auto-scale true \
  --min-node-count 3 \
  --max-node-count 10
```

**Key behaviors**:
- Auto-pause default: 15 minutes idle
- Pool definitions are free; charges only when jobs run
- Autoscale bounded by min/max nodes
- Synapse Studio sends keep-alive; close sessions when done

**Sources**:
- [Apache Spark pool configurations](https://learn.microsoft.com/en-us/azure/synapse-analytics/spark/apache-spark-pool-configurations) - Microsoft Learn

#### Microsoft Fabric: Capacity Pause/Resume

**Description**: Pause entire Fabric capacity to stop CU charges.

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

**REST API**:
```bash
# Pause
POST https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Fabric/capacities/{capacity}/suspend?api-version=2022-07-01-preview

# Resume
POST https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Fabric/capacities/{capacity}/resume?api-version=2022-07-01-preview
```

**Key behaviors**:
- No built-in scheduled pause (requires automation)
- OneLake storage costs continue when paused
- Pausing settles any burst overuse charges
- Resume takes 1-2 minutes

**Automation options**: Azure Logic Apps, PowerShell runbooks, Azure Automation, or Fabric REST API from pipelines.

**Sources**:
- [Pause and resume your capacity](https://learn.microsoft.com/en-us/fabric/enterprise/pause-resume) - Microsoft Learn
- [How to Pause/Resume a Fabric Capacity on the command line](https://community.fabric.microsoft.com/t5/Fabric-platform/How-to-Pause-Resume-a-Fabric-Capacity-on-the-command-line/m-p/4640379) - Microsoft Fabric Community

### Layer 2: Workload Management Controls

#### Synapse Dedicated SQL Pool: Workload Groups

**Description**: Resource isolation and containment for different workload types.

**SQL syntax**:
```sql
-- Create workload group with resource limits
CREATE WORKLOAD GROUP benchmark_wg
WITH (
  MIN_PERCENTAGE_RESOURCE = 10,     -- Guaranteed minimum
  CAP_PERCENTAGE_RESOURCE = 50,     -- Maximum allowed
  REQUEST_MIN_RESOURCE_GRANT_PERCENT = 5
);

-- Assign users to workload group via classifier
CREATE WORKLOAD CLASSIFIER benchmark_classifier
WITH (
  WORKLOAD_GROUP = 'benchmark_wg',
  MEMBERNAME = 'benchmark_user'
);
```

**Key behaviors**:
- Workload groups replace legacy resource classes
- CAP_PERCENTAGE_RESOURCE limits max resource consumption
- Queries wait if cap reached (not rejected)
- Enables cost attribution by workload

**Sources**:
- [Workload management](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql-data-warehouse/sql-data-warehouse-workload-management) - Microsoft Learn
- [Workload isolation](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql-data-warehouse/sql-data-warehouse-workload-isolation) - Microsoft Learn

#### Microsoft Fabric: Throttling and Smoothing

**Description**: Built-in capacity management with bursting, smoothing, and progressive throttling.

**How it works**:
1. **Bursting**: Short-term usage can exceed allocated CUs (F4 can burst to ~64 CUs briefly)
2. **Smoothing**: Usage averaged over time windows (5 min for interactive, 24 hr for background)
3. **Throttling**: Progressive delay when sustained overuse detected

**Throttling stages**:
| Stage | Trigger | Effect |
|-------|---------|--------|
| None | < 100% | Normal operation |
| Delayed | 100-110% | Interactive requests delayed |
| Rejected | > 110% sustained | Interactive requests rejected |

**Surge protection**: Enable in capacity settings to prioritize interactive queries over background jobs.

**Monitoring**: Fabric Capacity Metrics App shows utilization and throttling events.

**Sources**:
- [Understand your Fabric capacity throttling](https://learn.microsoft.com/en-us/fabric/enterprise/throttling) - Microsoft Learn
- [Smoothing and Throttling](https://learn.microsoft.com/en-us/fabric/data-warehouse/compute-capacity-smoothing-throttling) - Microsoft Learn
- [Burstable Capacity](https://learn.microsoft.com/en-us/fabric/data-warehouse/burstable-capacity) - Microsoft Learn

### Layer 3: Subscription-Level Controls

#### Azure Budgets

**Description**: Subscription or resource group spending alerts with optional automation.

**Azure CLI**:
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

**Key behaviors**:
- Budgets are informational by default
- Resources NOT automatically stopped when budget exceeded
- Supports multiple thresholds (50%, 80%, 100%)
- Forecasted spend alerts available
- Action groups can trigger automation

**For actual resource control**: Budget + Action Group + Logic App/Function to pause pools.

**Sources**:
- [Create and manage budgets](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets) - Microsoft Learn
- [Monitor usage and spending with cost alerts](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/cost-mgt-alerts-monitor-usage-spending) - Microsoft Learn

#### Azure Spending Limit

**Description**: Account-level spending cap for free trial and credit-based subscriptions.

**Key behaviors**:
- Only available for Azure Free Account and credit-based subscriptions
- NOT available for Pay-as-You-Go subscriptions
- Cannot adjust the limit amount; can only remove it
- When reached: VMs stop, resources become read-only

**Limitation**: Not useful for production benchmark accounts (requires PAYG or Enterprise Agreement).

**Sources**:
- [Azure spending limit](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/spending-limit) - Microsoft Learn

---

## Comparison with AWS/GCP/Snowflake

| Aspect | AWS Redshift Serverless | GCP BigQuery | Snowflake | Azure Synapse Dedicated | Azure Synapse Serverless | Microsoft Fabric |
|--------|------------------------|--------------|-----------|------------------------|-------------------------|------------------|
| Pricing unit | RPU-hours | TB scanned | Credits | DWU-hours | TB scanned | CU-hours |
| Per-service limit | Usage limit API | max_bytes_billed | Resource monitor | Pause/DWU | sp_set_data_processed_limit | Pause/scale |
| Auto-shutdown | Manual | N/A | Auto-suspend (60s min) | Manual pause | N/A | Manual pause |
| Native budget action | Yes (IAM deny) | Pub/Sub required | Suspend action | Via Action Groups | Via Action Groups | Via Action Groups |
| Minimum billing | 60 seconds | None | 60 seconds | 1 hour | 10 MB query | 1 minute |
| Reserved savings | ~65% (3yr) | ~40% (commitment) | ~25-50% (commitment) | ~65% (3yr) | N/A | ~41% (1yr) |

---

## TPC-H Benchmark Cost Estimates

### Azure Synapse Dedicated SQL Pool

| Scale Factor | Recommended DWU | Est. Query Time | Est. Cost |
|--------------|-----------------|-----------------|-----------|
| SF1 | DW100c | ~5 min | ~$0.13 |
| SF10 | DW500c | ~15 min | ~$1.90 |
| SF100 | DW1000c | ~45 min | ~$11.30 |
| SF1000 | DW3000c | ~2 hr | ~$90.60 |

*Estimates assume pool is paused before/after benchmark. Actual times vary by query complexity and data distribution.*

### Azure Synapse Serverless SQL Pool

| Scale Factor | Data Size | Est. TB Scanned | Est. Cost |
|--------------|-----------|-----------------|-----------|
| SF1 | ~1 GB | ~0.02 TB | ~$0.10 |
| SF10 | ~10 GB | ~0.2 TB | ~$1.00 |
| SF100 | ~100 GB | ~2 TB | ~$10.00 |
| SF1000 | ~1 TB | ~20 TB | ~$100.00 |

*Parquet format with column pruning can reduce scanned data by 50-80%.*

### Microsoft Fabric

| Scale Factor | Recommended SKU | Est. Time | Est. Cost |
|--------------|-----------------|-----------|-----------|
| SF1 | F4 | ~10 min | ~$0.15 |
| SF10 | F8-F16 | ~20 min | ~$0.60 |
| SF100 | F32-F64 | ~45 min | ~$4.20 |
| SF1000 | F128+ | ~2 hr | ~$33.70 |

*Estimates assume capacity is paused before/after benchmark.*

---

## Gaps and Limitations

### What Synapse Pause Doesn't Cover
- **Storage costs**: Data warehouse storage continues charging (~$0.02/GB/month)
- **Snapshot storage**: 7 days of incremental backups included, charged after
- **Geo-redundant storage**: If enabled, continues charging
- **Synapse workspace costs**: Data integration pipelines, linked services

### What Fabric Pause Doesn't Cover
- **OneLake storage**: ~$23/TB/month continues charging
- **Power BI Pro licenses**: $10-14/user/month if < F64
- **External data access**: Cross-region egress fees

### Platform Limitations

| Platform | Limitation |
|----------|------------|
| Synapse Dedicated | No auto-pause; requires manual or automated pause |
| Synapse Dedicated | Hourly billing minimum (not per-second like serverless) |
| Synapse Serverless | No per-query byte limit (only aggregate daily/weekly/monthly) |
| Synapse Spark | Keep-alive from Synapse Studio prevents auto-pause |
| Fabric | No built-in scheduled pause; requires external automation |
| Fabric | Throttling only slows queries, doesn't provide hard cost cap |

### Azure Budgets Limitation

**Critical gap**: Azure Budgets do NOT automatically stop resources. Unlike AWS Budget Actions with IAM deny policies, Azure requires custom automation:

1. Budget alert triggers Action Group
2. Action Group calls Logic App or Azure Function
3. Function calls pause API for specific resources

This is more complex than AWS's native Budget Actions.

---

## Best Practice: Layered Setup

### For Synapse Dedicated SQL Pool

```bash
# Layer 1: Start with pool paused, resume only for benchmarks
az synapse sql pool pause --name benchmark-pool --workspace-name my-ws --resource-group my-rg

# Before benchmark:
az synapse sql pool resume --name benchmark-pool --workspace-name my-ws --resource-group my-rg

# After benchmark:
az synapse sql pool pause --name benchmark-pool --workspace-name my-ws --resource-group my-rg

# Layer 2: Workload group to cap benchmark resource usage
# (via T-SQL workload management)

# Layer 3: Budget alert at 80% of monthly spend
az consumption budget create \
  --budget-name "Synapse-Benchmark" \
  --amount 100 \
  --time-grain Monthly \
  --resource-group my-synapse-rg
```

### For Synapse Serverless SQL Pool

```sql
-- Layer 1: Set daily data limit
EXEC sp_set_data_processed_limit @type = N'daily', @limit_tb = 2;

-- Layer 2: Set weekly limit
EXEC sp_set_data_processed_limit @type = N'weekly', @limit_tb = 10;

-- Layer 3: Set monthly limit
EXEC sp_set_data_processed_limit @type = N'monthly', @limit_tb = 30;
```

### For Microsoft Fabric

```bash
# Layer 1: Pause capacity when not in use
az fabric capacity suspend --capacity-name my-fabric --resource-group my-rg

# Layer 2: Right-size capacity for workload
# F8 for development, F32-F64 for benchmarks

# Layer 3: Azure budget with Action Group for alerting
az consumption budget create \
  --budget-name "Fabric-Benchmark" \
  --amount 500 \
  --time-grain Monthly

# Automation: Schedule pause/resume via Logic App or Azure Automation
```

---

## CLI/API Command Reference

### Azure CLI: Synapse SQL Pool

| Action | Command |
|--------|---------|
| Pause | `az synapse sql pool pause --name NAME --workspace-name WS --resource-group RG` |
| Resume | `az synapse sql pool resume --name NAME --workspace-name WS --resource-group RG` |
| Scale | `az synapse sql pool update --name NAME --workspace-name WS --resource-group RG --performance-level DW500c` |
| Status | `az synapse sql pool show --name NAME --workspace-name WS --resource-group RG` |

### Azure CLI: Fabric Capacity

| Action | Command |
|--------|---------|
| Pause | `az fabric capacity suspend --capacity-name NAME --resource-group RG` |
| Resume | `az fabric capacity resume --capacity-name NAME --resource-group RG` |
| List | `az fabric capacity list --resource-group RG` |

### PowerShell: Synapse

| Action | Command |
|--------|---------|
| Pause | `Suspend-AzSynapseSqlPool -WorkspaceName WS -Name NAME` |
| Resume | `Resume-AzSynapseSqlPool -WorkspaceName WS -Name NAME` |
| Scale | `Update-AzSynapseSqlPool -WorkspaceName WS -Name NAME -PerformanceLevel DW500c` |

---

## Verification Status

| Claim | Verified | Source |
|-------|----------|--------|
| DW100c ~$1,100/month | Yes | Azure pricing page |
| Pause stops compute charges | Yes | Microsoft Learn |
| Serverless ~$5/TB | Yes | Microsoft Learn |
| sp_set_data_processed_limit exists | Yes | Microsoft Learn |
| Fabric ~$0.18/CU-hour | Yes | Multiple sources |
| 41% reserved discount | Yes | Microsoft docs |
| No auto-pause for dedicated pools | Yes | Microsoft Learn |
| Budget doesn't auto-stop resources | Yes | Microsoft Learn |
| OneLake ~$23/TB/month | Yes | Microsoft Learn |

---

## Sources

### Microsoft Documentation
- [Azure Synapse Analytics Pricing](https://azure.microsoft.com/en-us/pricing/details/synapse-analytics/)
- [Microsoft Fabric Pricing](https://azure.microsoft.com/en-us/pricing/details/microsoft-fabric/)
- [Plan to manage costs for Azure Synapse Analytics](https://learn.microsoft.com/en-us/azure/synapse-analytics/plan-manage-costs)
- [Cost management for serverless SQL pool](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql/data-processed)
- [Manage compute resources for dedicated SQL pool](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql-data-warehouse/sql-data-warehouse-manage-compute-overview)
- [Pause and resume your capacity (Fabric)](https://learn.microsoft.com/en-us/fabric/enterprise/pause-resume)
- [Understand your Fabric capacity throttling](https://learn.microsoft.com/en-us/fabric/enterprise/throttling)
- [Workload management](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql-data-warehouse/sql-data-warehouse-workload-management)
- [Create and manage budgets](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets)

### Third-Party Analysis
- [Microsoft Fabric vs Azure Synapse: Key Differences](https://datakulture.com/blog/microsoft-fabric-vs-azure-synapse/)
- [Azure Synapse Pricing: A Complete Cost & Savings Guide](https://www.pump.co/blog/azure-synapse-pricing)
- [Microsoft Fabric Capacity Pricing - A Clear & Practical Breakdown](https://www.synapx.com/microsoft-fabric-pricing-guide-2025/)
- [The 7 Hidden Costs of Microsoft Fabric](https://www.timextender.com/blog/product-technology/the-7-hidden-costs-of-microsoft-fabric-a-practitioners-guide)

---

*Research completed: 2026-02-01*
