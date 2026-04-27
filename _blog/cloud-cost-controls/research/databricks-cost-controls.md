# Databricks Cost Controls Research

**Research Date**: 2026-02-01
**Status**: Complete
**For Post**: #4 - Databricks cost controls for benchmarking

---

## Pricing Summary

### Dual-Billing Structure

Databricks uses a **dual-billing model**: you pay Databricks for DBUs (processing power) AND your cloud provider (AWS/Azure/GCP) for underlying infrastructure (VMs, storage, networking). Cloud infrastructure costs often exceed DBU charges for compute-heavy workloads.

### DBU Pricing by Compute Type

| Compute Type | DBU Rate | Use Case | Notes |
|--------------|----------|----------|-------|
| Jobs Compute | 0.15-0.50 DBU/hr | Automated pipelines, ETL | 30-50% cheaper than All-Purpose |
| All-Purpose Compute | 0.40-0.75 DBU/hr | Interactive development, notebooks | Highest DBU rate per hour |
| SQL Compute (Classic) | 0.22-0.88 DBU/hr | SQL analytics, BI queries | Pro: $0.55/DBU |
| SQL Compute (Serverless) | Fixed per size | SQL analytics | $0.70/DBU, per-second billing |
| Jobs Light Compute | 0.07 DBU/hr | Lightweight tasks | Most economical |

**Key insight**: Jobs Compute can cost 70%+ less than All-Purpose Compute for identical workloads.

### DBU Pricing by Tier

| Tier | DBU Rate (approx) | Relative to Standard | Key Features |
|------|------------------|---------------------|--------------|
| Standard | $0.15-0.30/DBU | 1x | Core features (being phased out on AWS/GCP) |
| Premium | $0.40-0.55/DBU | ~1.3-1.5x | RBAC, audit logs, serverless SQL, Photon |
| Enterprise | $0.55-0.65/DBU | ~1.5-2x | Unity Catalog, compliance, advanced support |

**Important**: Standard tier is being phased out on AWS and GCP. Existing customers auto-upgrade to Premium by October 1, 2025. Azure still offers Standard and Premium.

### Regional Variations

- AWS offers most competitive pricing and widest feature set
- Azure runs ~10-20% higher on DBU rates
- GCP similar to AWS with some regional variations
- EU regions can be ~$0.91/DBU vs ~$0.55/DBU in US

### Serverless SQL Warehouse Sizes

| Size | DBU/Hour | Notes |
|------|----------|-------|
| 2X-Small | ~3 | Minimum size |
| X-Small | 6 | Good for testing |
| Small | 12 | Entry production |
| Medium | 24 | Typical workloads |
| Large | 48 | Complex queries |
| X-Large+ | 96+ | Heavy workloads |

**Sources**:
- [Databricks Pricing](https://www.databricks.com/product/pricing) - Official
- [Databricks Pricing 2026](https://www.chaosgenius.io/blog/databricks-pricing-guide/) - ChaosGenius
- [Serverless DBU consumption by SKU](https://docs.databricks.com/aws/en/resources/pricing) - Databricks Docs
- [Azure Databricks Pricing](https://azure.microsoft.com/en-us/pricing/details/databricks/) - Microsoft

### Photon DBU Multiplier

| Platform | Photon DBU Multiplier | Effect |
|----------|----------------------|--------|
| AWS Jobs Compute | 2.9x | Charges ~3x DBUs |
| Azure/GCP Jobs Compute | 2.5x | Charges ~2.5x DBUs |
| SQL Warehouses | 1x (included) | No extra cost |

**Key insight**: Photon should make workloads at least 2x faster to be cost-neutral. For I/O-bound jobs (simple ETL, streaming), Photon often doubles DBU cost with minimal speed gain.

**Sources**:
- [When is Databricks Photon Worth It?](https://zipher.cloud/when-is-databricks-photon-worth-it/) - Zipher
- [Is Databricks Photon A No Brainer?](https://milescole.dev/data-engineering/2024/04/30/Is-Databricks-Photon-A-NoBrainer.html) - Miles Cole

---

## Cost Control Mechanisms

### Layer 1: Cluster-Level Controls

#### Auto-Termination

**Description**: Automatically shuts down idle clusters after specified period.

**Default values**:
- All-Purpose clusters: 120 minutes (UI default)
- Databricks default (legacy): 4,320 minutes (72 hours!)
- Recommended for benchmarks: 15-30 minutes

**JSON policy example** (fixed, hidden from users):
```json
{
  "autotermination_minutes": {
    "type": "fixed",
    "value": 30,
    "hidden": true
  }
}
```

**Cost impact**: A forgotten cluster with 72-hour auto-termination can cost $150,000+ across 50 clusters annually.

#### Cluster Size Limits

**Control max workers**:
```json
{
  "num_workers": {
    "type": "range",
    "maxValue": 10,
    "minValue": 1
  },
  "autoscale.max_workers": {
    "type": "range",
    "maxValue": 20
  }
}
```

**Control max DBU per hour** (virtual attribute):
```json
{
  "dbus_per_hour": {
    "type": "range",
    "maxValue": 50
  }
}
```

**Note**: `dbus_per_hour` caps per-cluster DBU but users can still create multiple clusters.

### Layer 2: Workspace Policies (Compute Policies)

#### Policy Types

| Type | Description | Example Use |
|------|-------------|-------------|
| fixed | Prevents user override | Force auto-termination |
| allowlist | Limits to specific values | Approved instance types |
| blocklist | Prohibits specific values | Block expensive instances |
| range | Sets min/max bounds | Limit cluster size |
| regex | Pattern matching | Naming conventions |
| unlimited | Requires value or sets default | Make tags mandatory |

#### Cost-Focused Policy Example

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
      "values": [
        "m5.large",
        "m5.xlarge",
        "m5.2xlarge"
      ]
    },
    "spark_version": {
      "type": "allowlist",
      "values": [
        "13.3.x-scala2.12",
        "14.3.x-scala2.12"
      ]
    },
    "custom_tags.cost_center": {
      "type": "unlimited"
    },
    "dbus_per_hour": {
      "type": "range",
      "maxValue": 25
    }
  }
}
```

#### Max Clusters Per User

```json
{
  "max_clusters_per_user": 3
}
```

Prevents runaway cluster creation within a policy scope.

#### Creating Policies via CLI

```bash
# Create policy from file
databricks cluster-policies create --json @policy.json

# List existing policies
databricks cluster-policies list

# Get policy details
databricks cluster-policies get --cluster-policy-id <policy-id>
```

**Sources**:
- [Create and manage compute policies](https://docs.databricks.com/aws/en/admin/clusters/policies) - Databricks Docs
- [Compute policy reference](https://docs.databricks.com/aws/en/admin/clusters/policy-definition) - Databricks Docs
- [cluster-policies CLI](https://docs.databricks.com/aws/en/dev-tools/cli/reference/cluster-policies-commands) - Databricks Docs

### Layer 3: Account-Level Controls

#### Budgets

**Description**: Track spending across account with email alerts when exceeded.

**Creation via UI**:
1. Navigate to Account Console > Usage > Budgets tab
2. Name budget, set monthly USD amount
3. Filter by workspace(s) or custom tags
4. Add email recipients for notifications

**Key behaviors**:
- Budgets are informational only - they do NOT stop spending
- Measured in USD at list price (excludes discounts)
- Up to 24-hour delay for email notifications
- Can filter by workspace, SKU, or custom tags

**Limitation**: No native "Budget Action" equivalent to AWS. Budgets alert but don't enforce.

#### Serverless Budget Policies

**Description**: Enforce cost attribution tags on serverless workloads for tracking.

**Purpose**: Cost attribution (chargeback), not spending limits.

**Key behaviors**:
- Tags applied to serverless compute activity
- Tags logged in billing records
- Only workspace admins can create
- Existing workloads not automatically assigned

#### Serverless Compute Quotas

**Description**: Regional DBU limits per hour on serverless resources.

| Quota Type | Scope | Behavior |
|------------|-------|----------|
| Notebooks/Jobs/Pipelines | Per-workload/hour | Scale-up limit, doesn't prevent new launches |
| SQL Warehouses | Per-region | Prevents new warehouse launches when reached |

**Key limitations**:
- Quotas are per-workload, not aggregate
- Not designed for spend management
- Cannot lower account quota
- Request increases via support

**Sources**:
- [Create and monitor budgets](https://docs.databricks.com/aws/en/admin/account-settings/budgets) - Databricks Docs
- [Serverless budget policies](https://docs.databricks.com/aws/en/admin/usage/budget-policies) - Databricks Docs
- [Serverless compute quotas](https://docs.databricks.com/aws/en/admin/account-settings/serverless-quotas) - Databricks Docs

### Instance Pools (Cost Optimization)

**Description**: Pre-warmed instances for faster cluster startup with cost savings.

**Cost optimization settings**:

```json
{
  "instance_pool_name": "benchmark-pool",
  "min_idle_instances": 0,
  "max_capacity": 20,
  "idle_instance_autotermination_minutes": 20,
  "node_type_id": "m5.large",
  "preloaded_spark_versions": ["13.3.x-scala2.12"]
}
```

**Key parameters**:
| Parameter | Recommended Setting | Rationale |
|-----------|-------------------|-----------|
| min_idle_instances | 0 | Avoid paying for unused instances |
| max_capacity | Based on peak usage | Cap maximum cost |
| idle_instance_autotermination_minutes | 10-20 | Balance availability vs. cost |

**DBU savings**: Databricks does NOT charge DBUs while instances are idle in pool (but cloud provider still bills for VMs).

**Spot instances**: Use for worker nodes, not driver. Can reduce costs 50-70%.

**Sources**:
- [Pool best practices](https://docs.databricks.com/aws/en/compute/pool-best-practices) - Databricks Docs
- [Pool configuration reference](https://docs.databricks.com/aws/en/compute/pools) - Databricks Docs

### Unity Catalog Cost Governance

**Description**: Centralized governance with system tables for billing/usage visibility.

**Key features**:
- No additional DBU cost (included in Premium/Enterprise tier)
- System tables for billing, usage, audit logs
- Cost attribution via lineage tracking
- Tag enforcement for cost allocation

**Limitations**:
- Available only with Unity Catalog enabled (Premium+ tier)
- No native spending limits
- Observability-focused, not enforcement-focused

---

## Terraform Implementation

### Cluster Policy Resource

```hcl
resource "databricks_cluster_policy" "benchmark_policy" {
  name = "Benchmark Cost Control"

  definition = jsonencode({
    "autotermination_minutes" : {
      "type" : "fixed",
      "value" : 30,
      "hidden" : true
    },
    "autoscale.max_workers" : {
      "type" : "range",
      "maxValue" : 10
    },
    "node_type_id" : {
      "type" : "allowlist",
      "values" : [
        "m5.large",
        "m5.xlarge"
      ]
    },
    "dbus_per_hour" : {
      "type" : "range",
      "maxValue" : 25
    },
    "custom_tags.cost_center" : {
      "type" : "unlimited"
    }
  })

  max_clusters_per_user = 3
}

resource "databricks_permissions" "policy_usage" {
  cluster_policy_id = databricks_cluster_policy.benchmark_policy.id

  access_control {
    group_name       = "benchmark-users"
    permission_level = "CAN_USE"
  }
}
```

### Instance Pool Resource

```hcl
resource "databricks_instance_pool" "benchmark_pool" {
  instance_pool_name                    = "benchmark-pool"
  min_idle_instances                    = 0
  max_capacity                          = 20
  idle_instance_autotermination_minutes = 20
  node_type_id                          = "m5.large"

  preloaded_spark_versions = [
    "13.3.x-scala2.12"
  ]

  aws_attributes {
    availability = "SPOT_WITH_FALLBACK"
  }

  custom_tags = {
    cost_center = "benchmarks"
    environment = "development"
  }
}
```

**Sources**:
- [databricks_cluster_policy](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/cluster_policy) - Terraform Registry
- [databricks-industry-solutions/cluster-policy](https://github.com/databricks-industry-solutions/cluster-policy) - GitHub

---

## Comparison with Other Platforms

| Aspect | Databricks | AWS (Redshift Serverless) | GCP (BigQuery) | Snowflake |
|--------|------------|--------------------------|----------------|-----------|
| Pricing unit | DBU-hours | RPU-hours | TB scanned / slots | Credits |
| Per-resource limit | Cluster policy (max DBU) | Usage limit API | max_bytes_billed | Resource monitor |
| Auto-shutdown | Auto-termination | Manual | N/A (serverless) | Auto-suspend |
| Account-wide limit | Budget (alerts only) | Budget Action (IAM deny) | Custom quota | Resource monitor (suspend) |
| Hard spending cap | No | Yes (deactivates workgroup) | Yes (query fails) | Yes (warehouse suspends) |
| Minimum billing | Per-second | 60 seconds | None | 60 seconds |
| Infrastructure separate | Yes (dual billing) | No (included) | No (included) | No (included) |

**Key differentiator**: Databricks budgets are **informational only** - they alert but cannot stop spending. This is unlike Snowflake (resource monitors can suspend) or AWS Redshift Serverless (usage limits can deactivate workgroups).

---

## TPC-H Benchmark Cost Estimates

*Estimates for Jobs Compute on AWS (Premium tier, ~$0.50/DBU)*

| Scale Factor | Cluster Size | Power Run (est. DBU-hours) | Est. DBU Cost | Est. Total (incl. EC2) |
|--------------|--------------|---------------------------|---------------|------------------------|
| SF1 | 2 workers (m5.large) | 0.5-1 | $0.25-0.50 | $1-2 |
| SF10 | 4 workers (m5.xlarge) | 2-4 | $1-2 | $3-6 |
| SF100 | 8 workers (m5.2xlarge) | 10-20 | $5-10 | $15-30 |
| SF1000 | 16 workers (m5.4xlarge) | 50-100 | $25-50 | $75-150 |

*Add ~50-100% for All-Purpose Compute. Add ~2x for Photon on Jobs Compute.*

---

## Gaps and Limitations

### What Cluster Policies Don't Cover

- **Serverless compute**: Policies don't apply to serverless SQL warehouses
- **Multiple clusters**: `dbus_per_hour` caps per-cluster, not per-user total
- **Cloud infrastructure costs**: Policies control DBUs, not VM spending
- **Storage costs**: Charged by cloud provider, no DBU equivalent
- **Existing clusters**: Policies only apply at cluster creation

### What Budgets Don't Cover

- **Enforcement**: Budgets alert but don't stop spending
- **Real-time**: Up to 24-hour delay in notifications
- **Cloud costs**: Only tracks DBU charges, not total cloud bill
- **Discounts**: Uses list prices, not negotiated rates

### Serverless Limitations

- **No per-workload spending limits**: Quotas are capacity-based, not cost-based
- **No account-wide hard cap**: Can't set "stop at $X"
- **Default query timeout**: None - must explicitly configure `spark.databricks.execution.timeout`

### General Gaps

- **No automatic suspend on budget threshold**: Unlike Snowflake/AWS
- **Policy complexity**: JSON-based, no UI builder for complex rules
- **Cross-workspace controls**: Each workspace needs separate policy setup
- **Historical lag**: Usage data can take hours to appear in dashboards

---

## Best Practice: Layered Setup for Benchmarks

```
+-----------------------------------------------------------+
|  Layer 3: Account-level budgets (alerts only)             |
|  - Email at 50%, 80%, 100% of monthly budget              |
|  - Manual intervention required                           |
+-----------------------------------------------------------+
|  Layer 2: Workspace cluster policies                      |
|  - Force auto-termination (15-30 min)                     |
|  - Cap max workers and DBU/hour                           |
|  - Restrict to approved instance types                    |
|  - Require cost attribution tags                          |
+-----------------------------------------------------------+
|  Layer 1: Per-cluster configuration                       |
|  - Use Jobs Compute (not All-Purpose)                     |
|  - Use pools with spot instances                          |
|  - Disable Photon for I/O-bound work                      |
+-----------------------------------------------------------+
```

### CLI Quick Setup

```bash
# 1. Create cost-controlled cluster policy
databricks cluster-policies create --json @benchmark-policy.json

# 2. Assign policy to group
databricks permissions update cluster-policy \
  --cluster-policy-id <policy-id> \
  --json '[{"group_name": "benchmark-users", "permission_level": "CAN_USE"}]'

# 3. Create instance pool
databricks instance-pools create --json @benchmark-pool.json
```

---

## Verification Status

| Claim | Verified | Source |
|-------|----------|--------|
| Dual billing (DBU + cloud) | Yes | Multiple sources |
| Jobs Compute 30-50% cheaper | Yes | Databricks docs, pricing guides |
| 120min default auto-termination (UI) | Yes | Databricks docs |
| Budgets don't stop spending | Yes | Databricks docs |
| Photon 2-2.9x DBU multiplier | Yes | Community sources |
| Premium tier ~$0.40-0.55/DBU | Yes | Official pricing |
| Standard tier phaseout Oct 2025 | Yes | Multiple sources |
| Serverless SQL $0.70/DBU | Yes | Databricks pricing page |
| Cluster policies support dbus_per_hour | Yes | Policy reference docs |
| Pools don't charge DBU when idle | Yes | Databricks docs |

---

*Research completed: 2026-02-01*
