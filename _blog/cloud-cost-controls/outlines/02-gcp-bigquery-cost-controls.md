# GCP cost controls for BigQuery benchmarking

> Slot reservations, query quotas, and flat-rate pricing for predictable benchmark costs on Google Cloud.

**Series**: Cloud Cost Controls for Benchmarking
**Post Number**: 2 (GCP)
**Target Length**: 2,000-2,500 words
**Status**: RESEARCH COMPLETE - READY FOR DRAFT

---

## Metadata

```yaml
title: "GCP cost controls for BigQuery benchmarking"
slug: gcp-bigquery-cost-controls
series: cloud-cost-controls
post_number: 2
tags: [gcp, bigquery, cost-management, benchmarking, slots]
```

---

## Thesis

> BigQuery's on-demand pricing ($6.25/TB scanned) can surprise benchmark runners with unpredictable costs. Slot reservations, query quotas, and project-level controls provide the layered defense needed for reproducible, cost-bounded analytics benchmarks.

---

## Series context

This post adapts the layered-defense pattern from Post #1 (AWS) to GCP:

| Post | Platform | Key cost APIs |
|------|----------|---------------|
| 1 | AWS | Redshift usage limits, Athena workgroup caps, EMR max capacity |
| **2 (this)** | **GCP** | **BigQuery slot reservations, custom quotas, query byte limits** |
| 3 | Snowflake | Resource monitors, warehouse auto-suspend |
| 4 | Databricks | Cluster policies, DBU limits |
| 5 | Azure | Synapse DWU caps, Fabric capacity controls |

---

## Outline

### 1. Introduction (~300 words)

**Hook**: BigQuery's serverless model means no clusters to manage, but also no obvious "off switch." On-demand pricing of $6.25/TB scanned[^1] can accumulate rapidly during benchmark iterations.

**The problem for benchmarking workloads**:
- TPC-H SF100 scans ~100GB per full run; at $6.25/TB, each iteration costs ~$0.60
- Debug loops of 50 runs can reach $30 before you notice
- No native per-day aggregate spending limit (only per-query controls)
- Flat-rate pricing exists but requires commitment

**GCP-specific considerations**:
- BigQuery slots: Compute capacity, not storage-based charging
- Reservations: Pre-purchased capacity with predictable pricing
- Editions: Different commitment levels (Standard, Enterprise, Enterprise Plus)

### 2. BigQuery pricing models (~400 words)

**On-demand pricing**:
- $6.25/TB scanned (US regions)[^1]
- First 1TB/month free
- No per-query minimum (unlike Athena's 10MB)
- Charged for bytes scanned, not query runtime

**Flat-rate pricing (Editions)**:
- BigQuery Standard: $0.04/slot-hour (~$29/slot-month)
- BigQuery Enterprise: $0.06/slot-hour with advanced features
- Requires capacity commitment (1 year or 3 year)
- Predictable costs regardless of data scanned

**When each makes sense for benchmarks**:
- On-demand: Occasional testing, < 10TB/month scanned
- Flat-rate: Regular benchmarking, predictable capacity needs

### 3. Layered cost controls (~300 words)

**Architecture** (adapted from AWS pattern):

```
┌─────────────────────────────────────────────────────────┐
│  Layer 3: Billing budgets + alerts (project-wide)        │
│  - Pub/Sub notifications, Cloud Functions shutdown       │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Custom quotas (per-project/per-user)           │
│  - BigQuery bytes scanned quota                          │
│  - Query count limits                                    │
├─────────────────────────────────────────────────────────┤
│  Layer 1: Query-level controls (hard caps)               │
│  - Maximum bytes billed per query                        │
│  - Query timeout settings                                │
│  - Slot reservations (capacity ceiling)                  │
└─────────────────────────────────────────────────────────┘
```

### 4. Query-level controls (~500 words)

#### Maximum bytes billed

```sql
-- Limit query to 50GB max scan
SELECT * FROM dataset.table
OPTIONS (maximum_bytes_billed = 53687091200)
```

**CLI equivalent**:
```bash
$ bq query --maximum_bytes_billed=53687091200 \
  "SELECT * FROM dataset.table"
```

**Behavior**: Query fails before execution if estimated scan exceeds limit.

#### Query timeout

```bash
$ bq query --job_timeout_ms=300000 "SELECT ..."  # 5 minute timeout
```

#### Slot reservations

```bash
$ bq mk --reservation \
  --project_id=benchmark-project \
  --location=US \
  --slots=100 \
  benchmark-reservation
```

**Behavior**: Queries use reserved capacity; no per-TB charges. Capacity is your ceiling.

### 5. Project-level quotas (~400 words)

**Custom quotas via Cloud Quotas API**:
- `Query usage per day` - Limit total bytes scanned per project
- `Query count` - Limit number of queries per time period

**Setting quotas**:
```bash
$ gcloud alpha services quota update \
  --service=bigquery.googleapis.com \
  --consumer=projects/benchmark-project \
  --quota-id=QueryUsagePerDay \
  --value=1099511627776  # 1TB/day
```

**Behavior**: Queries exceeding quota fail with `quotaExceeded` error.

### 6. Billing budgets and alerts (~300 words)

**Creating a budget**:
```bash
$ gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name="Benchmark Budget" \
  --budget-amount=50USD \
  --threshold-rule=percent=50,basis=current-spend \
  --threshold-rule=percent=80,basis=current-spend \
  --threshold-rule=percent=100,basis=current-spend
```

**Automated response via Pub/Sub**:
- Budget alert triggers Pub/Sub message
- Cloud Function receives message
- Function disables billing or restricts IAM

**Important**: GCP billing budgets are informational by default; automated shutdown requires custom Cloud Function integration.

### 7. Comparison with AWS approach (~200 words)

| Aspect | AWS (Athena) | GCP (BigQuery) |
|--------|--------------|----------------|
| Per-TB cost | $5/TB | $6.25/TB |
| Per-query limit | BytesScannedCutoff | maximum_bytes_billed |
| Aggregate daily limit | Workgroup setting | Custom quota (beta) |
| Flat-rate option | None | Slot reservations |
| Billing automation | Budget Actions (native) | Pub/Sub + Cloud Function |

### 8. Complete setup example (~300 words)

**Putting layers together for a $50/month benchmark budget**:

```bash
# Layer 1: Query-level limit (50GB per query)
# Applied via --maximum_bytes_billed flag or SQL OPTIONS

# Layer 2: Project quota (1TB/day)
gcloud alpha services quota update ...

# Layer 3: Billing budget with alerts
gcloud billing budgets create ...
```

### 9. Limitations (~200 words)

**What these controls don't cover**:
- Storage costs ($0.02/GB/month for active storage)
- Streaming insert costs ($0.01 per 200MB)
- BI Engine charges (if enabled)
- Cross-region data transfer

**Slot reservation caveats**:
- Requires capacity commitment for best pricing
- Autoscaling slots available but cost more
- Idle slots are still charged

### 10. Conclusion (~150 words)

**Key takeaways**:
1. BigQuery's on-demand pricing ($6.25/TB) can surprise benchmark runners
2. `maximum_bytes_billed` provides per-query hard limits
3. Slot reservations offer predictable capacity-based pricing
4. Billing automation requires Pub/Sub + Cloud Function (unlike AWS native Budget Actions)

**Next in series**: Snowflake credit controls, resource monitors and warehouse auto-suspend for predictable testing costs.

---

## Research completed

- [x] Verify current BigQuery pricing (editions, regions) - See `research/gcp-bigquery-cost-controls.md`
- [x] Custom quota API documentation - Available via Service Management API
- [ ] Create Cloud Function example for billing automation - Needed for draft
- [x] Benchmark typical TPC-H bytes scanned at various scale factors - Estimated in research
- [x] Compare BigQuery Editions pricing tiers - $0.04/slot-hour (Standard) to $0.06/slot-hour (Enterprise)

## Verified References

[^1]: [BigQuery Pricing](https://cloud.google.com/bigquery/pricing) - Google Cloud. $6.25/TB on-demand, first 1TB/month free.

[^2]: [Create custom query quotas](https://cloud.google.com/bigquery/docs/custom-quotas) - Google Cloud. QueryUsagePerDay and QueryUsagePerUserPerDay quotas.

[^3]: [Estimate and control costs](https://docs.cloud.google.com/bigquery/docs/best-practices-costs) - Google Cloud. maximum_bytes_billed query option.

[^4]: [BigQuery Editions](https://www.doit.com/blog/bigquery-editions-and-what-you-need-to-know/) - DoiT. Standard $0.04/slot-hour, Enterprise $0.06/slot-hour.

[^5]: [Manage BigQuery costs with custom quotas](https://cloud.google.com/blog/products/data-analytics/manage-bigquery-costs-with-custom-quotas) - Google Cloud Blog. Sept 2025: New projects default to 200 TiB daily limit.

---

*Outline created: 2026-01-31*
*Research completed: 2026-01-31*
*Status: RESEARCH COMPLETE - READY FOR DRAFT*
