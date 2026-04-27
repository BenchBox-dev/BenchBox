# GCP cost controls for BigQuery benchmarking

*Part 2 of the Cloud Cost Controls for Benchmarking series*

> Slot reservations, custom quotas, and query-level limits for predictable benchmark costs on Google Cloud.

**TL;DR**: BigQuery's on-demand pricing ($6.25/TB scanned) can surprise benchmark runners with unpredictable costs. Query-level `maximum_bytes_billed`, project-level custom quotas, and billing budgets provide layered protection. Unlike AWS, GCP billing automation requires Pub/Sub and Cloud Functions rather than native budget actions.

*For series methodology, pricing scope, and cross-platform comparison, see the [series introduction](00-series-intro.md).*

---

## Why BigQuery benchmarks need cost controls

BigQuery's serverless model means no clusters to manage, but also no obvious "off switch." On-demand pricing of $6.25/TB scanned[^1] accumulates based on data volume, not query runtime. A `SELECT *` on a 100GB table costs approximately $0.63 regardless of whether the query takes 2 seconds or 20 seconds.

For benchmark workloads, this creates a specific challenge:

| Scenario | Data scanned | Cost per run | 50 debug runs |
|----------|-------------|--------------|---------------|
| TPC-H SF1 | ~1GB | ~$0.01 | ~$0.50 |
| TPC-H SF10 | ~10GB | ~$0.06 | ~$3.00 |
| TPC-H SF100 | ~100GB | ~$0.63 | ~$31.50 |
| TPC-H SF1000 | ~1TB | ~$6.25 | ~$312.50 |

These estimates assume one full scan per run at on-demand list pricing (`data scanned in TB × $6.25`).

At smaller scale factors, costs are negligible. At SF100 and above, a debug loop of 50 iterations can reach $30 before you notice. The `LIMIT` clause doesn't help either: BigQuery still scans the full table and charges accordingly.

The first 1TB per month is free[^1], which provides some buffer for small-scale testing. But once you're running multiple benchmark iterations at larger scale factors, on-demand costs accumulate quickly.

**GCP vs. AWS pricing context**: BigQuery charges $6.25/TB compared to Athena's $5/TB[^2]. However, BigQuery has no per-query minimum (Athena charges 10MB minimum for federated queries), which makes small queries more economical on BigQuery. The platforms take different approaches to aggregate controls, as we'll see below.

---

## BigQuery pricing models

Before setting up controls, it helps to understand the two pricing models BigQuery offers.

### On-demand pricing

- **$6.25/TB scanned** (US multi-region)[^1]
- First 1TB/month free
- Charged for bytes scanned, not query runtime
- No per-query minimum charge
- `LIMIT` clause doesn't reduce bytes scanned

This is the default model and works well for sporadic, unpredictable workloads. For benchmarking, costs scale linearly with data size and iteration count.

### Editions (slot-based pricing)

BigQuery Editions offer capacity-based pricing instead of per-scan pricing[^6]. Slots are units of compute capacity ($0.04-0.06/slot-hour depending on edition). When using slot reservations, you pay for capacity regardless of data scanned, providing a predictable cost ceiling. The smallest commitment is 100 slots.

**For most benchmark development, on-demand with appropriate controls makes sense.** Slot reservations become attractive when you're running benchmarks regularly enough that predictable capacity is more valuable than pay-per-query flexibility.

---

## Layered cost controls

Following the same layered approach from our AWS post, we apply controls at three levels:

```text
+-----------------------------------------------------------+
|  Layer 3: Billing budgets (project-wide alerting)          |
|  - Email alerts at percentage thresholds                   |
|  - Pub/Sub + Cloud Function for automated response         |
+-----------------------------------------------------------+
|  Layer 2: Custom quotas (project/user aggregate)           |
|  - Daily bytes-scanned limit per project                   |
|  - Per-user quotas available                               |
+-----------------------------------------------------------+
|  Layer 1: Query-level controls (per-query hard caps)       |
|  - maximum_bytes_billed per query                          |
|  - Query timeout settings                                  |
+-----------------------------------------------------------+
```

**Why layers matter**: Layer 1 prevents any single query from scanning excessive data. Layer 2 bounds the aggregate for an entire day. Layer 3 provides visibility across the billing account and can trigger automated responses.

---

## Query-level controls

### maximum_bytes_billed

The `maximum_bytes_billed` option sets a hard cap on bytes scanned per query. If the estimated scan exceeds the limit, the query fails before execution, incurring no charge.

**SQL syntax**:
```sql
SELECT customer_name, SUM(total_price) as revenue
FROM orders
GROUP BY customer_name
OPTIONS (maximum_bytes_billed = 53687091200)  -- 50GB limit
```

**Note**: The `OPTIONS` clause is supported in the BigQuery web console and API. Some third-party SQL tools may not pass it through correctly. The `bq` CLI flag is the most reliable method for setting this limit.

**bq CLI syntax**:
```bash
$ bq query --maximum_bytes_billed=53687091200 \
  "SELECT customer_name, SUM(total_price) FROM orders GROUP BY 1"
```

**Behavior**: The query fails with an error if estimated bytes exceed the limit. No charge is incurred for failed queries. This is preventive, not reactive[^5].

**Common values**:

| Limit | Bytes | Max cost (on-demand) |
|-------|-------|---------------------|
| 10GB | 10737418240 | ~$0.06 |
| 50GB | 53687091200 | ~$0.31 |
| 100GB | 107374182400 | ~$0.63 |
| 1TB | 1099511627776 | ~$6.25 |

**Trade-off for benchmarking**: The limit must be set per-query. It's easy to forget when iterating quickly. For TPC-H at SF100 (~100GB), a 200GB limit provides headroom for the largest queries while catching accidental `SELECT *` operations on the full dataset.

### Query timeout

BigQuery queries can also be limited by runtime:

```bash
$ bq query --job_timeout_ms=300000 "SELECT ..."  # 5 minute timeout
```

This is less useful for cost control (BigQuery charges per-scan, not per-second) but helps catch queries that are hung or inefficient during benchmark development.

### Dry run for cost estimation

Before executing expensive queries, use dry run to estimate bytes scanned:

```bash
$ bq query --dry_run "SELECT * FROM bigdata.orders"
Query successfully validated. Assuming the tables are not modified,
running this query will process 23847582910 bytes of data.
```

This returns the estimated scan size without executing the query or incurring charges. Useful for validating that a query is within expected bounds before committing to execution.

---

## Project-level quotas

Query-level controls require remembering to set them on every query. Project-level quotas provide aggregate protection regardless of individual query settings.

### Custom quotas via Cloud Quotas API

BigQuery supports custom quotas for bytes scanned per day[^3]:

- **QueryUsagePerDay**: Total bytes scanned across the project
- **QueryUsagePerUserPerDay**: Per-user limit within the project

**Setting a project quota**:

```bash
$ gcloud alpha services quota update \
  --service=bigquery.googleapis.com \
  --consumer=projects/benchmark-project \
  --quota-id=QueryUsagePerDay \
  --value=1099511627776  # 1TB per day
```

**Behavior**: When the quota is reached, subsequent queries fail with `usageQuotaExceeded` error. The quota resets at midnight Pacific Time.

**Permissions required**: Owner, Editor, Quota Administrator, or Service Usage Admin role.

**Recent changes (September 2025)**: New projects now default to a 200 TiB daily query limit[^4]. Previously, projects had no limit by default. Existing projects with no custom limit will receive one based on peak historical usage. This change means new projects have some protection out of the box, though 200 TiB is far above typical benchmark needs.

### Custom quota example

For a benchmark project with a $50/month on-demand budget:

- $50 budget / $6.25 per TB = 8 TB/month
- 8 TB / 30 days = ~267 GB/day

Setting a 500GB daily quota provides headroom:

```bash
$ gcloud alpha services quota update \
  --service=bigquery.googleapis.com \
  --consumer=projects/benchmark-project \
  --quota-id=QueryUsagePerDay \
  --value=536870912000  # 500GB
```

**Trade-off**: Quotas are approximate. BigQuery may occasionally allow queries that slightly exceed the quota before enforcement kicks in. We recommend setting the quota 10-20% below your actual limit to account for this.

---

## Billing budgets and alerts

Billing budgets provide project-wide visibility and can trigger automated responses.

### Creating a budget

```bash
$ gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name="Benchmark Budget" \
  --budget-amount=50USD \
  --threshold-rule=percent=50,basis=current-spend \
  --threshold-rule=percent=80,basis=current-spend \
  --threshold-rule=percent=100,basis=current-spend
```

This creates alerts at 50%, 80%, and 100% of the $50 monthly budget.

### Automated response (unlike AWS)

GCP billing budgets are **informational by default**. Unlike AWS Budget Actions, there's no native option to attach an IAM deny policy when a threshold is reached.

Automated shutdown requires custom integration:

1. Configure budget to publish to Pub/Sub topic
2. Create Cloud Function triggered by Pub/Sub
3. Function disables billing API or modifies IAM permissions

**Cloud Function approach** (pseudocode, not production-ready):

```python
def budget_alert_handler(event, context):
    """Triggered by Pub/Sub when budget threshold reached."""
    import json
    import base64
    from google.cloud import billing_v1

    # Parse the Pub/Sub message
    budget_data = json.loads(base64.b64decode(event['data']).decode())

    if budget_data['costAmount'] >= budget_data['budgetAmount']:
        # Disable billing for the project
        # NOTE: Requires appropriate IAM permissions and PROJECT_ID env var
        client = billing_v1.CloudBillingClient()
        client.update_project_billing_info(
            name=f"projects/{PROJECT_ID}",
            project_billing_info={'billing_account_name': ''}
        )
```

**Note**: This is simplified pseudocode. A production implementation requires error handling, logging, environment variable configuration, and appropriate IAM roles. See Google's [Cap billing to stop usage](https://cloud.google.com/billing/docs/how-to/notify#cap_billing_to_stop_usage) documentation for a complete example.

**Trade-off**: This is more complex than AWS Budget Actions. The benefit is flexibility: you can implement any response logic. The cost is additional infrastructure to maintain.

For most benchmark scenarios, the combination of query-level limits (Layer 1) and project quotas (Layer 2) provides sufficient protection without requiring custom Cloud Functions.

---

## Comparison with AWS approach

| Aspect | AWS (Athena) | GCP (BigQuery) |
|--------|--------------|----------------|
| Per-TB cost | $5/TB | $6.25/TB |
| Per-query minimum | 10MB (federated) | None |
| Per-query limit | BytesScannedCutoff (workgroup) | maximum_bytes_billed (per query) |
| Aggregate daily limit | Workgroup aggregate limit | Custom quota (API) |
| Flat-rate option | None | Slot reservations |
| Billing automation | Budget Actions (native IAM deny) | Pub/Sub + Cloud Function |
| Free tier (query scans) | None | First 1TB/month |

**Key differences**:

1. **Per-query limits**: Athena sets limits at the workgroup level; BigQuery requires per-query settings or dry runs. This makes Athena's approach less error-prone for teams.

2. **Aggregate limits**: Both support daily aggregate limits, but through different APIs. Athena uses workgroup configuration; BigQuery uses the Cloud Quotas API.

3. **Billing automation**: AWS Budget Actions can automatically attach IAM deny policies. GCP requires Pub/Sub and Cloud Functions for the same effect.

4. **Flat-rate option**: BigQuery's slot reservations provide a capacity-based alternative that Athena lacks. For regular benchmarking, this can be more predictable.

---

## Complete setup example

Putting the layers together for a $50/month benchmark budget on BigQuery:

### Layer 1: Query-level protection

Add `maximum_bytes_billed` to benchmark queries:

```sql
-- 100GB limit per query (~$0.63 max per query)
SELECT l_returnflag, SUM(l_quantity)
FROM lineitem
GROUP BY l_returnflag
OPTIONS (maximum_bytes_billed = 107374182400)
```

Or create a wrapper script that adds the flag:

```bash
#!/bin/bash
# bq-benchmark.sh - run query with cost limit
bq query --maximum_bytes_billed=107374182400 "$1"
```

### Layer 2: Project quota

```bash
$ gcloud alpha services quota update \
  --service=bigquery.googleapis.com \
  --consumer=projects/benchmark-project \
  --quota-id=QueryUsagePerDay \
  --value=536870912000  # 500GB/day
```

### Layer 3: Billing budget

```bash
$ gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name="Benchmark Budget" \
  --budget-amount=50USD \
  --threshold-rule=percent=50,basis=current-spend \
  --threshold-rule=percent=80,basis=current-spend
```

### Resulting protection

| Control | Limit | Enforcement |
|---------|-------|-------------|
| Per-query | 100GB | Query fails before execution |
| Per-day aggregate | 500GB | Quota exceeded error |
| Monthly budget | $50 | Email alerts at 50%, 80% |

---

## Limitations

**What these controls don't cover**:

- **Storage costs**: $0.02/GB/month for active storage, $0.01 for long-term. No quota API for storage.
- **Streaming inserts**: $0.01 per 200MB inserted. Not controlled by query quotas.
- **BI Engine**: If enabled, charges separately from query costs.
- **Cross-region transfer**: Data egress charges accumulate outside query costs.

**Custom quota caveats**:

- Quotas are approximate (occasional overshoots possible before enforcement)
- Reset at midnight Pacific Time (not configurable)
- Some operations are in beta
- Requires appropriate IAM permissions to modify

**Slot reservation caveats**:

- 100-slot minimum for commitments (smallest option ~$2,900/month)
- Idle slots are still charged
- Autoscaling slots cost more than baseline commitment
- Query performance bounded by available slots

---

## Conclusions

BigQuery's on-demand pricing ($6.25/TB) can accumulate quickly during benchmark iterations. Unlike instance-based databases, there's no cluster to "turn off" when not in use.

**Key takeaways**:

1. **`maximum_bytes_billed`** provides per-query hard limits. Queries fail before execution if estimated scan exceeds the cap. No charge for failed queries.

2. **Custom quotas** provide project-level daily aggregates. The Cloud Quotas API allows setting `QueryUsagePerDay` limits that prevent runaway usage.

3. **Slot reservations** offer an alternative pricing model for predictable capacity needs. No per-TB charges when using reserved slots.

4. **Billing automation differs from AWS**. GCP requires Pub/Sub and Cloud Functions for automated budget responses; there's no native Budget Actions equivalent.

**Next steps**:

- Run `bq query --dry_run` on your typical benchmark queries to understand scan sizes
- Set `maximum_bytes_billed` appropriate to your scale factor
- Consider a project-level quota if multiple people run benchmarks against the same project

**Next in series**: Snowflake credit controls, resource monitors and warehouse auto-suspend for predictable benchmark costs.

---

## References

[^1]: [BigQuery Pricing](https://cloud.google.com/bigquery/pricing), Google Cloud. $6.25/TB on-demand, first 1TB/month free.

[^2]: [Amazon Athena Pricing](https://aws.amazon.com/athena/pricing/), AWS. $5/TB scanned for comparison.

[^3]: [Create custom query quotas](https://cloud.google.com/bigquery/docs/custom-quotas), Google Cloud. QueryUsagePerDay and QueryUsagePerUserPerDay quotas.

[^4]: [Manage BigQuery costs with custom quotas](https://cloud.google.com/blog/products/data-analytics/manage-bigquery-costs-with-custom-quotas), Google Cloud Blog. September 2025: New projects default to 200 TiB daily limit.

[^5]: [Estimate and control costs](https://cloud.google.com/bigquery/docs/best-practices-costs), Google Cloud. maximum_bytes_billed query option.

[^6]: [BigQuery Pricing (Editions)](https://cloud.google.com/bigquery/pricing#editions_pricing), Google Cloud. Edition pricing and slot commitment details.

---

*Questions or feedback? [Open an issue](https://github.com/benchbox/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: 2364
**Created**: 2026-01-31
**Series**: Cloud Cost Controls for Benchmarking (Post 2: GCP BigQuery)
