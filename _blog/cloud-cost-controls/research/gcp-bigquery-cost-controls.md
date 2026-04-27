# GCP BigQuery Cost Controls Research

**Research Date**: 2026-01-31
**Status**: Complete
**For Post**: #2 - GCP cost controls for BigQuery benchmarking

---

## Pricing Summary

### On-Demand Pricing (Per TB Scanned)

| Region | Price/TB | First TB/Month |
|--------|----------|----------------|
| US multi-region | $6.25 | Free |
| EU multi-region | $6.25 | Free |
| Other regions | Varies | Free |

**Key behaviors**:
- Charged for bytes scanned, not query runtime
- No per-query minimum (unlike Athena's 10MB)
- `LIMIT` clause does NOT reduce bytes scanned
- Dry run available to estimate cost before execution

**Sources**:
- [BigQuery Pricing](https://cloud.google.com/bigquery/pricing) - Google Cloud
- [BigQuery Pricing Guide 2026](https://airbyte.com/data-engineering-resources/bigquery-pricing) - Airbyte

### BigQuery Editions (Slot-Based Pricing)

| Edition | Slot Cost/Hour | Commitment Options | Key Features |
|---------|----------------|-------------------|--------------|
| Standard | $0.04 | Pay-as-you-go only | Basic features |
| Enterprise | $0.06 | 1-year, 3-year | Multi-cluster, longer time travel |
| Enterprise Plus | Higher | 1-year, 3-year | Advanced security, BI Engine |

**Key details**:
- 100-slot minimum for commitments
- Commitments shared across organization
- Autoscaling available (set baseline + max)
- Flat-rate option: fixed slots, no autoscaling

**Sources**:
- [BigQuery Editions and What You Need to Know](https://www.doit.com/blog/bigquery-editions-and-what-you-need-to-know/) - DoiT
- [WYNTK About BigQuery Editions](https://adswerve.com/technical-insights/bigquery-editions-and-recent-billing-announcements) - Adswerve

### Storage Pricing

| Storage Type | Price/GB/Month |
|--------------|----------------|
| Active | $0.02 |
| Long-term (90+ days unchanged) | $0.01 |
| First 10GB | Free |

---

## Cost Control Mechanisms

### 1. maximum_bytes_billed (Query-Level)

**Description**: Per-query limit on bytes scanned. Query fails before execution if estimated bytes exceed limit.

**SQL syntax**:
```sql
SELECT * FROM dataset.table
OPTIONS (maximum_bytes_billed = 53687091200)  -- 50GB
```

**CLI syntax**:
```bash
bq query --maximum_bytes_billed=53687091200 "SELECT ..."
```

**Behavior**:
- Query fails with error if estimated scan exceeds limit
- No charge incurred for failed queries
- Must be set per-query (easy to forget)

**Sources**:
- [Estimate and control costs](https://docs.cloud.google.com/bigquery/docs/best-practices-costs) - Google Cloud
- [Controlling your BigQuery costs](https://cloud.google.com/blog/topics/developers-practitioners/controlling-your-bigquery-costs) - Google Cloud Blog

### 2. Custom Quotas (Project/User-Level)

**Description**: Daily aggregate limits on bytes scanned per project or per user.

**Quota types**:
- `QueryUsagePerDay`: Project-level aggregate
- `QueryUsagePerUserPerDay`: Per-user within project

**API endpoint**:
```
PATCH https://servicemanagement.googleapis.com/v1/services/bigquery-json.googleapis.com/projectSettings/PROJECT_ID?updateMask=quotaSettings.consumerOverrides["QueryUsagePerDay"]
```

**Key behaviors**:
- Quotas are proactive (can't start 11TB query with 10TB quota)
- Reset at midnight Pacific Time
- Quotas are approximate (not strict enforcement)
- Error: `usageQuotaExceeded`

**Required permissions**: Owner, Editor, Quota Administrator, or Service Usage Admin

**Recent changes (Sept 2025)**:
- New projects default to 200 TiB daily query limit
- Existing "unlimited" projects get custom limit based on peak usage

**Sources**:
- [Create custom query quotas](https://docs.cloud.google.com/bigquery/docs/custom-quotas) - Google Cloud
- [BigQuery: Set up limits and custom quotas through API](https://medium.com/google-cloud/bigquery-set-up-limits-and-custom-quotas-through-api-629f77438b7e) - Guillaume Blaquiere
- [Manage BigQuery costs with custom quotas](https://cloud.google.com/blog/products/data-analytics/manage-bigquery-costs-with-custom-quotas) - Google Cloud Blog

### 3. Slot Reservations (Capacity-Based)

**Description**: Pre-purchased compute capacity. No per-TB charges when using reserved slots.

**Creation**:
```bash
bq mk --reservation \
  --project_id=benchmark-project \
  --location=US \
  --slots=100 \
  benchmark-reservation
```

**Key behaviors**:
- Queries use reserved capacity only
- No per-TB charges for queries in reservation
- Idle slots are still charged
- Autoscaling slots available (set baseline + max)

**Trade-offs**:
- Predictable costs vs. on-demand flexibility
- Requires capacity commitment for best pricing
- Query performance bounded by slot count

### 4. Billing Budgets (Account-Level)

**Description**: Account-wide spend alerts with optional Pub/Sub notifications for automation.

**gcloud command**:
```bash
gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name="Benchmark Budget" \
  --budget-amount=50USD \
  --threshold-rule=percent=50,basis=current-spend \
  --threshold-rule=percent=80,basis=current-spend \
  --threshold-rule=percent=100,basis=current-spend
```

**Key behaviors**:
- Budgets are informational by default
- Automated shutdown requires Pub/Sub + Cloud Function
- Unlike AWS Budget Actions, no native IAM deny action

**Automation pattern**:
1. Budget alert triggers Pub/Sub message
2. Cloud Function receives message
3. Function disables billing API or modifies IAM

**Sources**:
- [Controlling your BigQuery costs](https://cloud.google.com/blog/topics/developers-practitioners/controlling-your-bigquery-costs) - Google Cloud Blog

---

## Comparison with AWS

| Aspect | AWS (Athena) | GCP (BigQuery) |
|--------|--------------|----------------|
| Per-TB cost | $5/TB | $6.25/TB |
| Per-query limit | BytesScannedCutoff (workgroup) | maximum_bytes_billed (query) |
| Aggregate daily limit | Workgroup setting | Custom quota (API) |
| Flat-rate option | None | Slot reservations |
| Billing automation | Budget Actions (native IAM deny) | Pub/Sub + Cloud Function |
| Free tier | First 1TB/month | First 1TB/month |
| Per-query minimum | 10MB (federated) | None |

---

## TPC-H Benchmark Cost Estimates

| Scale Factor | Data Size | On-Demand Cost (full run) |
|--------------|-----------|---------------------------|
| SF1 | ~1GB | ~$0.01 |
| SF10 | ~10GB | ~$0.06 |
| SF100 | ~100GB | ~$0.63 |
| SF1000 | ~1TB | ~$6.25 |

*Estimates assume single power run scanning all tables once*

---

## Gaps and Limitations

**What custom quotas don't cover**:
- Storage costs ($0.02/GB/month)
- Streaming insert costs
- BI Engine charges
- Cross-region data transfer

**Custom quota caveats**:
- Quotas are approximate (occasional overshoots possible)
- Reset at midnight Pacific (not configurable)
- API currently in beta for some operations

**Slot reservation caveats**:
- Requires commitment for best pricing
- Autoscaling slots cost more than baseline
- Idle slots still charged

---

## Verification Status

| Claim | Verified | Source |
|-------|----------|--------|
| $6.25/TB on-demand | Yes | Google Cloud pricing page |
| $0.04/slot-hour Standard | Yes | Multiple sources |
| Custom quota API available | Yes | Google Cloud docs |
| Quota reset at midnight PT | Yes | Google Cloud docs |
| New projects: 200TiB default | Yes | Google Cloud blog (Sept 2025) |

---

*Research completed: 2026-01-31*
