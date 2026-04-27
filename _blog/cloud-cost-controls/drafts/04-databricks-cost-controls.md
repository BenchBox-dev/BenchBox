# Databricks cost controls for benchmarking

*Part 4 of the Cloud Cost Controls for Benchmarking series*

> Cluster policies, auto-termination, and instance pools for predictable Spark benchmark costs, with the critical caveat that budgets don't stop spending.

**TL;DR**: Databricks is the only platform in this series where budgets are purely informational: they alert but cannot stop spending. Cluster policies with enforced auto-termination become your primary defense. Combine these with Jobs Compute (30-50% cheaper than All-Purpose) and instance pools with spot pricing for the closest approximation to cost control.

*For series methodology, pricing scope, and cross-platform comparison, see the [series introduction](00-series-intro.md).*

---

## The critical difference: budgets don't stop spending

Databricks stands apart from every other platform we've covered in this series. Unlike Snowflake's resource monitors (which can suspend warehouses), AWS Redshift Serverless usage limits (which can deactivate workgroups), or BigQuery quotas (which reject queries), Databricks budgets are informational only. They alert, but they cannot stop spending.

| Platform | Can Budget Stop Spending? | Mechanism |
|----------|--------------------------|-----------|
| AWS Redshift Serverless | Yes | Usage limit deactivates workgroup |
| GCP BigQuery | Yes | Quota rejects queries |
| Snowflake | Yes | Resource monitor suspends warehouse |
| **Databricks** | **No** | Alerts only, up to 24-hour delay |

A benchmark run that exceeds expectations will continue charging until you notice and intervene. This fundamental difference shapes everything about cost control on Databricks: cluster policies become critical, and active monitoring is required rather than optional.

**The dual-billing challenge**: Databricks also uses a dual-billing model. You pay Databricks for DBUs (processing power) AND your cloud provider (AWS/Azure/GCP) for underlying infrastructure. Cloud infrastructure costs often equal or exceed DBU charges for compute-heavy workloads, and they're tracked separately.

---

## Databricks pricing model

### DBU rates by compute type

DBU (Databricks Unit) is the unit of processing capability. Rates vary significantly by compute type:

| Compute Type | DBU Rate | Best For | Notes |
|--------------|----------|----------|-------|
| Jobs Compute | 0.15-0.50 DBU/hr | Automated benchmarks | 30-50% cheaper |
| All-Purpose Compute | 0.40-0.75 DBU/hr | Interactive development | Most expensive |
| SQL Classic | 0.22-0.88 DBU/hr | BI queries | Pro tier: $0.55/DBU |
| SQL Serverless | 0.70 DBU (fixed) | Variable SQL workloads | Per-second billing |

The DBU rate ranges above vary by instance type, cloud provider, and whether Photon is enabled. Larger instance families (memory-optimized, GPU) have higher per-hour DBU rates than general-purpose instances. Check the [Databricks pricing calculator](https://www.databricks.com/product/pricing) for your specific configuration.

**Key insight for benchmarks**: Jobs Compute can cost 30-50% less than All-Purpose Compute for identical workloads. For automated benchmark runs, there's rarely a reason to use All-Purpose.

### DBU pricing by tier

| Tier | DBU Rate (approx) | Notes |
|------|------------------|-------|
| Standard | $0.15-0.30/DBU | Being phased out on AWS/GCP |
| Premium | $0.40-0.55/DBU | RBAC, audit logs, serverless SQL |
| Enterprise | $0.55-0.65/DBU | Unity Catalog, compliance |

**Important**: Databricks announced the Standard tier phase-out on AWS and GCP, with existing workspaces upgrading to Premium[^1]. Azure continues to offer both tiers. Check your workspace tier in the Account Console, as your actual DBU rate depends on your current tier.

### The Photon question

Photon is Databricks' vectorized query engine. It typically uses different DBU rates than non-Photon compute for the same SKU, and actual economics depend on your workload/runtime mix.

| Platform | Photon DBU Multiplier |
|----------|----------------------|
| AWS Jobs Compute | Higher than non-Photon (varies by SKU) |
| Azure/GCP Jobs Compute | Higher than non-Photon (varies by SKU) |
| SQL Warehouses | Included in SQL warehouse pricing |

**When Photon makes sense**: Measure both runtime and DBU consumption for your exact benchmark mix. For CPU-heavy query workloads, Photon often improves latency; for I/O-bound workloads, savings are less predictable. We recommend benchmarking with and without Photon to compare total cost for your own profile[^2].

### Don't forget cloud infrastructure

A complete cost picture for a Databricks benchmark includes:

| Component | Billed To | Example |
|-----------|-----------|---------|
| DBU charges | Databricks | $0.50/DBU × 10 DBU-hours = $5 |
| VM costs | Cloud provider | m5.xlarge × 2 hours × 2 nodes = $0.76 |
| Storage | Cloud provider | S3/ADLS rates |
| Network | Cloud provider | Data transfer fees |

For compute-heavy workloads, cloud VM costs can equal or exceed DBU charges.

---

## Layered cost controls

Following the same layered approach from our previous posts, but with a critical adjustment: Layer 3 provides no enforcement.

```text
+-----------------------------------------------------------+
|  Layer 3: Account-level budgets (ALERTS ONLY)              |
|  - Email at percentage thresholds                          |
|  - Up to 24-hour notification delay                        |
|  - NO automatic enforcement                                |
+-----------------------------------------------------------+
|  Layer 2: Workspace cluster policies (PRIMARY DEFENSE)     |
|  - Force auto-termination (15-30 min for benchmarks)       |
|  - Cap max workers and DBU/hour per cluster                |
|  - Restrict to approved instance types                     |
|  - max_clusters_per_user prevents runaway creation         |
+-----------------------------------------------------------+
|  Layer 1: Per-cluster configuration                        |
|  - Use Jobs Compute (not All-Purpose)                      |
|  - Use pools with spot instances                           |
|  - Disable Photon for I/O-bound work                       |
+-----------------------------------------------------------+
```

**The key difference**: Because Layer 3 can't enforce limits, Layer 2 (cluster policies) becomes your primary defense mechanism.

---

## Cluster-level controls

### Auto-termination: your first line of defense

**The problem**: Long idle timeouts leave clusters running and accruing DBU and cloud VM charges after work stops. Workspace defaults vary over time, so relying on defaults is risky for benchmark environments.

**The solution**: Enforce via cluster policy with a fixed, hidden value:

```json
{
  "autotermination_minutes": {
    "type": "fixed",
    "value": 30,
    "hidden": true
  }
}
```

Setting `hidden: true` prevents users from seeing or modifying this value. The cluster simply terminates after 30 minutes of inactivity.

**Recommended for benchmarks**: 15-30 minutes. Short enough to catch forgotten clusters, long enough for iteration between query batches.

### Cluster size limits

Cap the maximum number of workers:

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

### DBU per hour cap

The `dbus_per_hour` virtual attribute limits DBU consumption per cluster:

```json
{
  "dbus_per_hour": {
    "type": "range",
    "maxValue": 25
  }
}
```

**Limitation**: This caps per-cluster DBU, not per-user total. A user can still create multiple clusters (unless you also set `max_clusters_per_user`).

### Jobs Compute vs All-Purpose

For automated benchmarks, prefer Jobs Compute:

- 30-50% cheaper DBU rates
- Designed for non-interactive workloads
- No notebook UI overhead

All-Purpose Compute makes sense for interactive development and debugging, but once your benchmark is ready to run, switch to Jobs Compute.

### Instance pools with spot pricing

Instance pools provide pre-warmed instances for faster cluster startup, with cost optimization through spot pricing:

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

| Parameter | Recommended | Rationale |
|-----------|-------------|-----------|
| min_idle_instances | 0 | Don't pay for unused instances |
| max_capacity | Based on peak | Cap maximum cloud VM cost |
| idle_instance_autotermination_minutes | 10-20 | Balance availability vs cost |
| Spot instances | Yes (workers only) | 50-70% savings on cloud VMs |

Databricks does NOT charge DBUs while instances are idle in a pool. However, your cloud provider still charges for the VMs until they're terminated. This is why `min_idle_instances: 0` is important for cost control.

---

## Cluster policies

Cluster policies are JSON-based definitions that control what users can configure when creating clusters.

### Policy types

| Type | Use Case | Example |
|------|----------|---------|
| fixed | Enforce setting, hide from users | Force auto-termination |
| allowlist | Limit to approved values | Approved instance types |
| blocklist | Prohibit specific values | Block expensive instances |
| range | Set min/max bounds | Cap cluster size |
| unlimited | Require value | Mandatory cost tags |

### Complete benchmark policy

Here's a policy that enforces cost controls for benchmark workloads:

```json
{
  "name": "Benchmark Cost Control Policy",
  "max_clusters_per_user": 3,
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
  }
}
```

Note: `max_clusters_per_user` is a top-level policy attribute, not part of the `definition` block[^3].

This policy:
- Forces 30-minute auto-termination (users can't change it)
- Caps clusters at 10 workers maximum
- Limits instance types to cost-effective options
- Caps DBU consumption at 25 DBU/hour
- Requires a cost_center tag
- Limits each user to 3 clusters

### Creating policies via CLI

```bash
# Create policy from file
databricks cluster-policies create --json @benchmark-policy.json

# List existing policies
databricks cluster-policies list

# Assign policy to a group
databricks permissions update cluster-policy \
  --cluster-policy-id <policy-id> \
  --json '[{"group_name": "benchmark-users", "permission_level": "CAN_USE"}]'
```

### Policies don't apply to serverless

**Critical limitation**: Cluster policies only apply to classic compute. Serverless SQL warehouses have separate controls: you can set max scaling limits on the warehouse itself and use workspace-level quotas. However, these don't provide the same granular cost control as cluster policies. If you're using serverless compute, monitor usage closely via the Account Console or set up alerts through your cloud provider's billing tools.

---

## Account-level budgets

### Creating a budget

Budgets are created in the Account Console:

1. Navigate to Account Console > Usage > Budgets tab
2. Set monthly USD amount
3. Filter by workspace(s) or custom tags
4. Add email recipients for notifications

### Critical limitations

We can't emphasize this enough:

- **Informational only**: Budgets alert but cannot stop spending
- **Up to 24-hour delay**: Notifications may arrive after significant overrun
- **List prices only**: Doesn't reflect negotiated discounts
- **DBU costs only**: Cloud infrastructure is tracked separately

**Why this matters for benchmarks**: A benchmark that runs away won't be stopped automatically. By the time you receive an alert, you may have already exceeded your budget. Active monitoring during benchmark runs is required.

---

## Comparison with other platforms

| Aspect | Databricks | Snowflake | AWS Redshift | BigQuery |
|--------|------------|-----------|--------------|----------|
| Hard spending cap | **No** | Yes (suspend) | Yes (deactivate) | Yes (quota) |
| Budget enforcement | Alerts only | Suspend action | IAM deny | Pub/Sub automation |
| Billing model | Dual (DBU + cloud) | Single (credits) | Single (RPU) | Single (TB/slots) |
| Auto-shutdown | Auto-termination | Auto-suspend | Manual | N/A |
| Minimum billing | Per-second | 60 seconds | 60 seconds | None |

The single-bill simplicity of Snowflake, AWS, and BigQuery doesn't exist on Databricks. You're managing two cost streams (DBU and cloud infrastructure) with different monitoring tools.

---

## Complete setup example

Putting the layers together for benchmark cost control:

```bash
# Layer 1: Create instance pool with spot instances
databricks instance-pools create --json @benchmark-pool.json

# Layer 2: Create cluster policy with enforced limits
databricks cluster-policies create --json @benchmark-policy.json

# Layer 2b: Assign policy to benchmark users
databricks permissions update cluster-policy \
  --cluster-policy-id <policy-id> \
  --json '[{"group_name": "benchmark-users", "permission_level": "CAN_USE"}]'

# Layer 3: Create budget via Account Console UI
# Set monthly limit, add email alerts at 50%, 80%, 100%
```

### Resulting protection

| Layer | Control | Limit | Enforcement |
|-------|---------|-------|-------------|
| 1 | Auto-termination | 30 min idle | Cluster terminates |
| 1 | Spot instances | Worker nodes | 50-70% cloud savings |
| 2 | Max workers | 10 | Policy blocks creation |
| 2 | Max DBU/hour | 25 | Policy blocks creation |
| 2 | Max clusters/user | 3 | Policy blocks creation |
| 3 | Monthly budget | $X | **Email alert only** |

---

## Limitations

### What cluster policies don't cover

- **Serverless compute**: Policies don't apply to serverless SQL warehouses
- **Multiple clusters**: `dbus_per_hour` caps per-cluster, not per-user total
- **Cloud infrastructure**: Policies control DBU, not VM spending
- **Existing clusters**: Policies apply at creation only

### What budgets don't cover

- **Enforcement**: Alerts only, no automatic action
- **Real-time**: Up to 24-hour delay in notifications
- **Cloud costs**: DBU only, not infrastructure
- **Negotiated pricing**: Uses list prices

### Mitigation strategies

Given these limitations:

- **Active monitoring during benchmark runs**: Don't walk away
- **Use Jobs Compute**: Automated execution with cheaper DBU rates
- **Set conservative auto-termination**: 15-30 minutes
- **Review usage daily**: Not weekly
- **Set up cloud provider alerts**: For the infrastructure portion

---

## Conclusions

Databricks cost control requires more vigilance than other platforms in this series.

**Key takeaways**:

1. **Budgets are informational only**: They cannot stop spending. This is the critical difference from Snowflake, AWS, and GCP.

2. **Cluster policies are your primary defense**: Enforce auto-termination, cap cluster sizes, restrict instance types.

3. **Jobs Compute saves 30-50%**: Use it for automated benchmark execution instead of All-Purpose Compute.

4. **Instance pools with spot instances**: Reduce cloud VM costs by 50-70%.

5. **Active monitoring is required**: Automated enforcement isn't available.

**Estimated costs for TPC-H benchmarks** (Jobs Compute, Premium tier; modeled ranges, not bill export totals):

| Scale Factor | Cluster Size | Est. DBU Cost | Est. Total (incl. cloud) |
|--------------|--------------|---------------|--------------------------|
| SF1 | 2 workers (m5.large) | $0.25-0.50 | $1-2 |
| SF10 | 4 workers (m5.xlarge) | $1-2 | $3-6 |
| SF100 | 8 workers (m5.2xlarge) | $5-10 | $15-30 |

**Next in series**: Azure Synapse and Fabric cost controls, where pause/resume replaces auto-suspend and budget enforcement requires Logic App automation.

---

## References

[^1]: [Databricks Pricing](https://www.databricks.com/product/pricing), Databricks. DBU rates by compute type and tier.

[^2]: [Databricks Photon overview](https://docs.databricks.com/aws/en/compute/photon), Databricks. Photon behavior and workload fit guidance.

[^3]: [Compute policy reference](https://docs.databricks.com/aws/en/admin/clusters/policy-definition), Databricks. Policy-enforced settings including idle/size constraints.

[^4]: [Create and manage compute policies](https://docs.databricks.com/aws/en/admin/clusters/policies), Databricks. Policy creation and management.

[^5]: [Create and monitor budgets](https://docs.databricks.com/aws/en/admin/account-settings/budgets), Databricks. Budget limitations.

[^6]: [Pool best practices](https://docs.databricks.com/aws/en/compute/pool-best-practices), Databricks. Instance pool configuration.

---

*Questions or feedback? [Open an issue](https://github.com/benchbox/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: 2443
**Created**: 2026-02-01
**Series**: Cloud Cost Controls for Benchmarking (Post 4: Databricks)
