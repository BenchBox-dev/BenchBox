# Databricks cost controls for benchmarking

> Cluster policies, auto-termination, and instance pools for predictable Spark benchmark costs, with the critical caveat that budgets don't stop spending.

**Series**: Cloud Cost Controls for Benchmarking
**Post Number**: 4 (Databricks)
**Target Length**: 2,000-2,500 words
**Status**: OUTLINE COMPLETE - READY FOR DRAFT

---

## Metadata

```yaml
title: "Databricks cost controls for benchmarking"
slug: databricks-cost-controls
series: cloud-cost-controls
post_number: 4
tags: [databricks, cost-management, cluster-policies, dbu, benchmarking, spark]
```

---

## Thesis

> Databricks uses dual-billing (DBU charges + cloud infrastructure) and budgets are informational only, they alert but cannot stop spending. Cluster policies with enforced auto-termination and DBU caps, combined with Jobs Compute and instance pools, provide the closest approximation to cost controls, but require more vigilance than AWS, GCP, or Snowflake.

---

## Series context

This post highlights a critical gap compared to other platforms:

| Post | Platform | Hard Spending Cap | Budget Enforcement |
|------|----------|-------------------|-------------------|
| 1 | AWS | Yes (usage limit deactivates) | IAM deny action |
| 2 | GCP | Yes (quota fails query) | Pub/Sub automation |
| 3 | Snowflake | Yes (resource monitor suspends) | Native suspend |
| **4 (this)** | **Databricks** | **No** | **Alerts only, up to 24hr delay** |
| 5 | Azure | Pause required | Action Group automation |

---

## Outline

### 1. Introduction (~300 words)

**Hook**: Databricks is the only platform in this series where budgets are purely informational. Unlike Snowflake's resource monitors (which can suspend warehouses) or AWS Redshift Serverless usage limits (which can deactivate workgroups), Databricks budgets alert but cannot stop spending. A benchmark run that exceeds expectations will continue charging until you notice and intervene.

**The problem for benchmarking workloads**:
- Dual-billing: DBU charges (Databricks) + cloud infrastructure (AWS/Azure/GCP)
- No automatic enforcement on budget threshold
- Up to 24-hour delay in budget notifications
- Default auto-termination is 120 minutes (UI) or up to 72 hours (legacy)
- All-Purpose Compute costs 30-50% more than Jobs Compute for identical workloads

**Pricing context**:
- Jobs Compute: 0.15-0.50 DBU/hr (most economical)
- All-Purpose Compute: 0.40-0.75 DBU/hr (most expensive)
- Serverless SQL: $0.70/DBU with per-second billing
- Premium tier: ~$0.40-0.55/DBU[^1]
- Plus cloud VM costs (often 50-100% of DBU costs)

### 2. Databricks pricing model (~400 words)

**Dual-billing structure**:

| Component | Billed To | Example |
|-----------|-----------|---------|
| DBU charges | Databricks | $0.50/DBU × 10 DBU-hours = $5 |
| VM costs | Cloud provider | m5.xlarge × 2 hours = $0.38 |
| Storage | Cloud provider | S3/ADLS/GCS rates |
| Network | Cloud provider | Data transfer fees |

**DBU rates by compute type**:

| Compute Type | DBU Rate | Best For |
|--------------|----------|----------|
| Jobs Compute | 0.15-0.50 | Automated benchmarks |
| All-Purpose | 0.40-0.75 | Interactive development |
| SQL Classic | 0.22-0.88 | BI queries |
| SQL Serverless | 0.70 (fixed) | Variable SQL workloads |

**Photon consideration**: 2-2.9x DBU multiplier. Only cost-effective if workload runs >2x faster. For I/O-bound benchmarks, often doubles cost with minimal speedup[^2].

**Standard tier phase-out**: Standard tier being phased out on AWS/GCP by October 2025. Existing customers auto-upgrade to Premium[^3].

### 3. Layered cost controls (~300 words)

**Architecture** (adapted from series pattern, with critical difference):

```
+-----------------------------------------------------------+
|  Layer 3: Account-level budgets (ALERTS ONLY)              |
|  - Email at percentage thresholds                          |
|  - Up to 24-hour notification delay                        |
|  - NO automatic enforcement (unlike Snowflake/AWS)         |
+-----------------------------------------------------------+
|  Layer 2: Workspace cluster policies                       |
|  - Force auto-termination (15-30 min for benchmarks)       |
|  - Cap max workers and DBU/hour per cluster                |
|  - Restrict to approved instance types                     |
|  - max_clusters_per_user prevents runaway creation         |
+-----------------------------------------------------------+
|  Layer 1: Per-cluster configuration                        |
|  - Use Jobs Compute (not All-Purpose)                      |
|  - Use pools with spot instances                           |
|  - Disable Photon for I/O-bound work                       |
|  - Require cost attribution tags                           |
+-----------------------------------------------------------+
```

**Critical difference from other platforms**: Layer 3 is informational only. This means Layer 2 (cluster policies) becomes the primary enforcement mechanism.

### 4. Cluster-level controls (~500 words)

#### Auto-termination

**Problem**: Default can be 120 minutes (UI) or up to 72 hours (legacy). A forgotten cluster with 72-hour auto-termination can cost $150,000+ across 50 clusters annually[^4].

**Solution**: Enforce via cluster policy:

```json
{
  "autotermination_minutes": {
    "type": "fixed",
    "value": 30,
    "hidden": true
  }
}
```

**Recommended for benchmarks**: 15-30 minutes. Short enough to catch forgotten clusters, long enough for iteration between query batches.

#### Cluster size limits

**Control max workers**:

```json
{
  "num_workers": {
    "type": "range",
    "maxValue": 10
  },
  "autoscale.max_workers": {
    "type": "range",
    "maxValue": 20
  }
}
```

#### DBU per hour cap (virtual attribute)

```json
{
  "dbus_per_hour": {
    "type": "range",
    "maxValue": 25
  }
}
```

**Limitation**: This caps per-cluster DBU, not per-user total. Users can still create multiple clusters.

#### Jobs Compute vs All-Purpose

For benchmarks, use Jobs Compute (workflows API):
- 30-50% cheaper DBU rates
- Designed for automated workloads
- No interactive notebook overhead

### 5. Cluster policies (~500 words)

#### Policy types

| Type | Use Case | Example |
|------|----------|---------|
| fixed | Enforce setting, hide from users | Force auto-termination |
| allowlist | Limit to approved values | Approved instance types |
| blocklist | Prohibit specific values | Block expensive instances |
| range | Set min/max bounds | Cap cluster size |
| unlimited | Require value | Mandatory cost tags |

#### Complete benchmark policy

```json
{
  "name": "Benchmark Cost Control Policy",
  "definition": {
    "autotermination_minutes": {
      "type": "fixed",
      "value": 30,
      "hidden": true
    },
    "autoscale.max_workers": {
      "type": "range",
      "maxValue": 10
    },
    "node_type_id": {
      "type": "allowlist",
      "values": ["m5.large", "m5.xlarge", "m5.2xlarge"]
    },
    "dbus_per_hour": {
      "type": "range",
      "maxValue": 25
    },
    "custom_tags.cost_center": {
      "type": "unlimited"
    }
  },
  "max_clusters_per_user": 3
}
```

#### Creating policies via CLI

```bash
# Create policy
databricks cluster-policies create --json @benchmark-policy.json

# Assign to group
databricks permissions update cluster-policy \
  --cluster-policy-id <id> \
  --json '[{"group_name": "benchmark-users", "permission_level": "CAN_USE"}]'
```

#### Policies don't apply to serverless

**Critical limitation**: Cluster policies only apply to classic compute. Serverless SQL warehouses have separate controls (quotas, not policies).

### 6. Instance pools (~300 words)

**Cost optimization strategy**: Pre-warmed instances with spot pricing.

```json
{
  "instance_pool_name": "benchmark-pool",
  "min_idle_instances": 0,
  "max_capacity": 20,
  "idle_instance_autotermination_minutes": 20,
  "node_type_id": "m5.large",
  "aws_attributes": {
    "availability": "SPOT_WITH_FALLBACK"
  }
}
```

**Key settings for benchmarks**:

| Parameter | Recommended | Rationale |
|-----------|-------------|-----------|
| min_idle_instances | 0 | Don't pay for unused instances |
| max_capacity | Based on peak | Cap maximum cost |
| idle_instance_autotermination_minutes | 10-20 | Balance availability vs cost |
| spot instances | Yes (workers only) | 50-70% savings |

**DBU behavior**: No DBU charges while instances are idle in pool. But cloud VMs still charged until terminated.

### 7. Account-level budgets (~300 words)

**Creating a budget**:
1. Account Console > Usage > Budgets tab
2. Set monthly USD amount
3. Filter by workspace(s) or custom tags
4. Add email recipients

**Critical limitations**:
- **Informational only**: Budgets alert but cannot stop spending
- **Up to 24-hour delay**: Notification may arrive after significant overrun
- **List prices only**: Doesn't reflect negotiated discounts
- **DBU costs only**: Cloud infrastructure tracked separately

**Why this matters for benchmarks**: A benchmark that runs away won't be stopped automatically. You must monitor actively and intervene manually.

### 8. Comparison with other platforms (~200 words)

| Aspect | Databricks | Snowflake | AWS Redshift | BigQuery |
|--------|------------|-----------|--------------|----------|
| Hard spending cap | **No** | Yes (suspend) | Yes (deactivate) | Yes (quota) |
| Budget enforcement | Alerts only | Suspend action | IAM deny | Pub/Sub automation |
| Billing model | Dual (DBU + cloud) | Single (credits) | Single (RPU) | Single (TB/slots) |
| Auto-shutdown | Auto-termination | Auto-suspend | Manual | N/A |
| Minimum billing | Per-second | 60 seconds | 60 seconds | None |

**Key differentiator**: Databricks is the only platform where you cannot automatically stop spending at a threshold. This requires more active monitoring.

### 9. Complete setup example (~300 words)

**Layered setup for benchmark cost control**:

```bash
# Layer 1: Create instance pool with spot instances
databricks instance-pools create --json @benchmark-pool.json

# Layer 2: Create cluster policy with enforced limits
databricks cluster-policies create --json @benchmark-policy.json

# Layer 2b: Assign policy to benchmark users
databricks permissions update cluster-policy \
  --cluster-policy-id <id> \
  --json '[{"group_name": "benchmark-users", "permission_level": "CAN_USE"}]'

# Layer 3: Create budget (alerting only)
# Via Account Console UI - set monthly limit, add email alerts
```

**Resulting protection**:

| Layer | Control | Limit | Enforcement |
|-------|---------|-------|-------------|
| 1 | Auto-termination | 30 min idle | Cluster terminates |
| 1 | Spot instances | Worker nodes | 50-70% savings |
| 2 | Max workers | 10 | Policy blocks creation |
| 2 | Max DBU/hour | 25 | Policy blocks creation |
| 2 | Max clusters/user | 3 | Policy blocks creation |
| 3 | Monthly budget | $X | **Email alert only** |

### 10. Limitations (~200 words)

**What cluster policies don't cover**:
- Serverless compute (separate controls)
- Multiple clusters (per-cluster limits, not per-user total)
- Cloud infrastructure costs (separate from DBU)
- Existing clusters (policies apply at creation only)

**What budgets don't cover**:
- Enforcement (alerts only)
- Real-time monitoring (up to 24-hour delay)
- Cloud costs (DBU only)
- Negotiated pricing (uses list prices)

**Mitigation strategies**:
- Active monitoring during benchmark runs
- Use Jobs Compute for automated execution
- Set conservative auto-termination (15-30 min)
- Review usage daily, not weekly

### 11. Conclusion (~150 words)

**Key takeaways**:
1. Databricks budgets are informational only, they cannot stop spending. This is the critical difference from Snowflake, AWS, and GCP.
2. Cluster policies with enforced auto-termination are your primary cost control.
3. Jobs Compute saves 30-50% over All-Purpose Compute for identical workloads.
4. Instance pools with spot instances can reduce cloud VM costs 50-70%.
5. Active monitoring is required, automated enforcement isn't available.

**Next in series**: Azure Synapse and Fabric cost controls, DWU caps, pause/resume, and capacity management.

---

## References

[^1]: [Databricks Pricing](https://www.databricks.com/product/pricing) - Databricks. DBU rates by compute type and tier.

[^2]: [When is Databricks Photon Worth It?](https://zipher.cloud/when-is-databricks-photon-worth-it/) - Zipher. Photon DBU multiplier analysis.

[^3]: [Databricks Pricing 2026](https://www.chaosgenius.io/blog/databricks-pricing-guide/) - ChaosGenius. Standard tier phase-out timeline.

[^4]: [How to Prevent Databricks Cost Disasters with Smart Compute Policies](https://www.sunnydata.ai/blog/databricks-compute-policies-cost-control) - SunnyData. Auto-termination cost impact.

[^5]: [Create and manage compute policies](https://docs.databricks.com/aws/en/admin/clusters/policies) - Databricks. Policy creation and management.

[^6]: [Compute policy reference](https://docs.databricks.com/aws/en/admin/clusters/policy-definition) - Databricks. Policy attribute types and syntax.

[^7]: [Create and monitor budgets](https://docs.databricks.com/aws/en/admin/account-settings/budgets) - Databricks. Budget creation and limitations.

[^8]: [Pool best practices](https://docs.databricks.com/aws/en/compute/pool-best-practices) - Databricks. Instance pool configuration.

---

*Outline created: 2026-02-01*
*Research completed: 2026-02-01*
*Status: OUTLINE COMPLETE - READY FOR DRAFT*
