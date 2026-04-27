# Azure Synapse and Fabric cost controls for benchmarking

> DWU caps, pause/resume, and capacity management for predictable analytics benchmark costs on Microsoft's platforms.

**Series**: Cloud Cost Controls for Benchmarking
**Post Number**: 5 (Azure)
**Target Length**: 2,000-2,500 words
**Status**: OUTLINE COMPLETE - READY FOR DRAFT

---

## Metadata

```yaml
title: "Azure Synapse and Fabric cost controls for benchmarking"
slug: azure-synapse-fabric-cost-controls
series: cloud-cost-controls
post_number: 5
tags: [azure, synapse, fabric, cost-management, dwu, benchmarking]
```

---

## Thesis

> Azure Synapse dedicated pools require manual pause (no auto-pause), serverless pools support data processing limits, and Fabric capacities can be paused but require automation. Azure Budgets don't automatically stop resources, requiring Action Groups with Logic Apps for enforcement, unlike AWS's native Budget Actions.

---

## Series context

| Post | Platform | Key Control | Budget Enforcement |
|------|----------|-------------|-------------------|
| 1 | AWS | Usage limits, Budget Actions | Native IAM deny |
| 2 | GCP | max_bytes_billed, quotas | Pub/Sub + Cloud Function |
| 3 | Snowflake | Resource monitors | Native suspend |
| 4 | Databricks | Cluster policies | Alerts only |
| **5 (this)** | **Azure** | **Pause/resume, data limits** | **Action Groups + automation** |

---

## Outline

### 1. Introduction (~300 words)

**Hook**: Azure offers three distinct analytics pricing models: Synapse dedicated pools (DWU-hours), Synapse serverless (per-TB scanned), and Fabric (capacity units). Each requires different cost controls, and none has automatic budget enforcement, you'll need automation for that.

**The problem for benchmarking workloads**:
- Synapse dedicated pools have no auto-pause (unlike Snowflake's auto-suspend)
- Hourly billing for dedicated pools (not per-second like serverless)
- Fabric has no built-in scheduled pause
- Azure Budgets are informational by default

**Pricing context**:

| Service | Pricing Model | Example Cost |
|---------|---------------|--------------|
| Synapse Dedicated | DWU-hours | DW100c ~$1,100/month (24x7)[^1] |
| Synapse Serverless | Per-TB scanned | ~$5/TB[^2] |
| Synapse Spark | Per-vCore-hour | ~$0.14/vCore-hour |
| Fabric | Capacity units | F2 ~$263/month, F64 ~$8,400/month[^3] |

**Microsoft's positioning**: Fabric is the future (SaaS, unified platform), Synapse remains supported (PaaS, separate pools). No announced end-of-life for Synapse.

### 2. Azure analytics pricing models (~400 words)

#### Synapse Dedicated SQL Pools

| DWU Level | Compute Nodes | Hourly Cost | Monthly (24x7) |
|-----------|---------------|-------------|----------------|
| DW100c | 1 | ~$1.51 | ~$1,100 |
| DW500c | 1 | ~$7.55 | ~$5,500 |
| DW1000c | 2 | ~$15.10 | ~$11,000 |
| DW3000c | 6 | ~$45.30 | ~$33,000 |

- **Billing**: Hourly (rounded up), not per-second
- **Storage**: Separate (~$0.02/GB/month)
- **Reserved capacity**: Up to 65% discount for 3-year commitment[^1]

#### Synapse Serverless SQL Pools

- **$5 per TB scanned**
- No provisioned compute to manage
- 10 MB minimum per query
- Similar to BigQuery/Athena pricing

#### Synapse Spark Pools

- **~$0.14 per vCore-hour**
- Minimum 3 nodes per pool instance
- Auto-pause available (unlike dedicated SQL)

#### Microsoft Fabric

- **~$0.18 per CU-hour**
- Single capacity pool serves all workloads
- F64+ includes Power BI Pro license
- Reserved: ~41% discount for 1-year[^3]

### 3. Layered cost controls (~300 words)

**Architecture**:

```
+-----------------------------------------------------------+
|  Layer 3: Subscription-level budgets + Action Groups       |
|  - Email alerts at thresholds                              |
|  - Logic App/Function for automated pause (if configured)  |
+-----------------------------------------------------------+
|  Layer 2: Workload management                              |
|  - Synapse: Workload groups with CAP_PERCENTAGE_RESOURCE   |
|  - Fabric: Throttling/smoothing (built-in, not configurable)|
+-----------------------------------------------------------+
|  Layer 1: Pool/capacity-level controls                     |
|  - Synapse Dedicated: Pause/resume (manual or scripted)    |
|  - Synapse Serverless: sp_set_data_processed_limit         |
|  - Synapse Spark: Auto-pause with idle timeout             |
|  - Fabric: Capacity pause/resume                           |
+-----------------------------------------------------------+
```

**Key difference from AWS**: Azure Budgets don't have native "Budget Actions" like AWS. Automated resource control requires Action Groups triggering Logic Apps or Azure Functions.

### 4. Synapse Dedicated SQL Pool controls (~500 words)

#### Pause/resume (primary control)

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
Suspend-AzSynapseSqlPool -WorkspaceName "my-ws" -Name "benchmark-pool"
Resume-AzSynapseSqlPool -WorkspaceName "my-ws" -Name "benchmark-pool"
```

**Behavior**:
- Paused: $0 compute, storage continues charging
- Resume: 1-2 minutes
- Running transactions canceled on pause

**Best practice for benchmarks**: Pause pools when not running benchmarks. Pausing overnight and weekends reduces compute costs by 60-70%.

#### Workload groups (resource isolation)

```sql
CREATE WORKLOAD GROUP benchmark_wg
WITH (
  MIN_PERCENTAGE_RESOURCE = 10,
  CAP_PERCENTAGE_RESOURCE = 50,
  REQUEST_MIN_RESOURCE_GRANT_PERCENT = 5
);

CREATE WORKLOAD CLASSIFIER benchmark_classifier
WITH (
  WORKLOAD_GROUP = 'benchmark_wg',
  MEMBERNAME = 'benchmark_user'
);
```

**CAP_PERCENTAGE_RESOURCE**: Limits maximum resource consumption. Queries wait (not rejected) when cap reached.

### 5. Synapse Serverless SQL Pool controls (~400 words)

#### Data processed limits

```sql
-- Daily limit (1 TB = ~$5/day max)
EXEC sp_set_data_processed_limit @type = N'daily', @limit_tb = 1

-- Weekly limit
EXEC sp_set_data_processed_limit @type = N'weekly', @limit_tb = 5

-- Monthly limit
EXEC sp_set_data_processed_limit @type = N'monthly', @limit_tb = 20
```

**Behavior**: Queries rejected when limit exceeded. Error: "Query is rejected because SQL Serverless budget limit for a period is exceeded."

**Trade-off for benchmarks**: A 2 TB/day limit = ~$10/day max. Size based on expected benchmark data volume plus buffer.

**UI access**: Synapse Studio > Manage > SQL pools > Serverless > Cost control icon

### 6. Synapse Spark Pool controls (~300 words)

#### Auto-pause (available for Spark, unlike dedicated SQL)

```bash
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
- Auto-pause default: 15 minutes idle
- Pool definitions are free; charges only when jobs run
- Synapse Studio sends keep-alive, close sessions when done

#### Autoscale with limits

```bash
az synapse spark pool update \
  --name benchmark-spark \
  --workspace-name my-workspace \
  --resource-group my-rg \
  --enable-auto-scale true \
  --min-node-count 3 \
  --max-node-count 10
```

### 7. Microsoft Fabric controls (~400 words)

#### Capacity pause/resume

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

**Behavior**:
- Paused: $0 compute, OneLake storage continues (~$23/TB/month)
- Resume: 1-2 minutes
- No built-in scheduled pause (requires automation)

#### Throttling and smoothing (built-in)

Fabric has automatic capacity management:
1. **Bursting**: Short-term usage can exceed allocated CUs
2. **Smoothing**: Usage averaged over time windows
3. **Throttling**: Progressive delay when sustained overuse detected

| Stage | Trigger | Effect |
|-------|---------|--------|
| None | < 100% | Normal operation |
| Delayed | 100-110% | Interactive requests delayed |
| Rejected | > 110% sustained | Interactive requests rejected |

**Key point**: Throttling slows queries but doesn't provide a hard cost cap.

### 8. Azure Budgets and Action Groups (~400 words)

#### Creating a budget

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

**Key limitation**: Budgets are informational by default. Resources NOT automatically stopped when budget exceeded.

#### Automated enforcement (requires custom setup)

Unlike AWS Budget Actions, Azure requires:

1. Budget alert triggers Action Group
2. Action Group calls Logic App or Azure Function
3. Function calls pause API for specific resources

**Logic App approach** (conceptual):
- Trigger: HTTP request from Action Group
- Action: Call `az synapse sql pool pause` or Fabric suspend API
- Result: Automatic resource pause on budget threshold

**Trade-off**: More complex than AWS's native Budget Actions, but provides flexibility for custom logic.

### 9. Comparison with other platforms (~200 words)

| Aspect | AWS Redshift | GCP BigQuery | Snowflake | Azure Synapse | Azure Fabric |
|--------|--------------|--------------|-----------|---------------|--------------|
| Per-TB cost | N/A | $6.25 | N/A | $5 (serverless) | N/A |
| Per-hour cost | RPU-based | Slot-based | Credit-based | DWU-based | CU-based |
| Auto-pause | Manual | N/A | 60s min | Manual (dedicated) | Manual |
| Native budget action | Yes | No | Yes | No | No |
| Aggregate limit | Usage limit | Quota | Resource monitor | sp_set_data_processed_limit | None |

### 10. Complete setup example (~300 words)

**Synapse Dedicated + Serverless + Budget**:

```bash
# Layer 1a: Keep pool paused when not benchmarking
az synapse sql pool pause --name benchmark-pool --workspace-name my-ws --resource-group my-rg

# Layer 1b: Set serverless data limits
# (via T-SQL)
# EXEC sp_set_data_processed_limit @type = N'daily', @limit_tb = 2

# Layer 3: Create budget with alerts
az consumption budget create \
  --budget-name "Synapse-Benchmark" \
  --amount 100 \
  --time-grain Monthly \
  --resource-group my-synapse-rg
```

**Fabric setup**:

```bash
# Layer 1: Pause capacity when not in use
az fabric capacity suspend --capacity-name my-fabric --resource-group my-rg

# Layer 3: Create budget
az consumption budget create \
  --budget-name "Fabric-Benchmark" \
  --amount 500 \
  --time-grain Monthly
```

**Resulting protection**:

| Service | Control | Limit | Enforcement |
|---------|---------|-------|-------------|
| Synapse Dedicated | Pause/resume | Manual | Compute stops |
| Synapse Serverless | Data limit | 2 TB/day | Query rejected |
| Fabric | Pause/resume | Manual | Compute stops |
| All | Budget | $100-500/month | Email alert |

### 11. Limitations (~200 words)

**What pause doesn't cover**:
- Storage costs (continue when paused)
- Snapshot storage beyond 7 days
- OneLake storage (~$23/TB/month)

**Platform limitations**:
- Synapse Dedicated: No auto-pause
- Synapse Dedicated: Hourly billing minimum
- Synapse Serverless: No per-query byte limit (only aggregate)
- Spark: Keep-alive from Synapse Studio prevents auto-pause
- Fabric: No built-in scheduled pause
- Fabric: Throttling doesn't provide hard cost cap

**Budget limitations**:
- Informational only (no native enforcement)
- Requires Action Group + Logic App for automated response

### 12. Conclusion (~150 words)

**Key takeaways**:
1. **Synapse Dedicated requires manual pause**, unlike Snowflake's auto-suspend. Budget pause automation requires Logic Apps.
2. **Serverless has data processing limits** via `sp_set_data_processed_limit`, providing aggregate daily/weekly/monthly caps.
3. **Fabric capacities can be paused** but require external automation for scheduling.
4. **Azure Budgets are informational**, requiring Action Groups with Logic Apps for automatic enforcement.

**Next in series**: The AWS Free Tier trap, what happens when an account joins an Organization, and why your "free" analytics benchmarks cost money.

---

## References

[^1]: [Azure Synapse Analytics Pricing](https://azure.microsoft.com/en-us/pricing/details/synapse-analytics/) - Microsoft Azure. DWU rates and reserved capacity discounts.

[^2]: [Cost management for serverless SQL pool](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql/data-processed) - Microsoft Learn. Per-TB pricing and data limits.

[^3]: [Microsoft Fabric Pricing](https://azure.microsoft.com/en-us/pricing/details/microsoft-fabric/) - Microsoft Azure. Capacity unit rates and reserved discounts.

[^4]: [Pause and resume compute in dedicated SQL pool](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql-data-warehouse/pause-and-resume-compute-portal) - Microsoft Learn. Pause/resume behavior.

[^5]: [Pause and resume your capacity (Fabric)](https://learn.microsoft.com/en-us/fabric/enterprise/pause-resume) - Microsoft Learn. Fabric capacity management.

[^6]: [Workload management](https://learn.microsoft.com/en-us/azure/synapse-analytics/sql-data-warehouse/sql-data-warehouse-workload-management) - Microsoft Learn. Workload groups and classifiers.

[^7]: [Understand your Fabric capacity throttling](https://learn.microsoft.com/en-us/fabric/enterprise/throttling) - Microsoft Learn. Throttling and smoothing behavior.

[^8]: [Create and manage budgets](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets) - Microsoft Learn. Budget creation and Action Groups.

---

*Outline created: 2026-02-01*
*Research completed: 2026-02-01*
*Status: OUTLINE COMPLETE - READY FOR DRAFT*
