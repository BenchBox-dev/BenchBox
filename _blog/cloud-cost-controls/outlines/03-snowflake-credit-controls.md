# Snowflake credit controls for testing

> Resource monitors, warehouse auto-suspend, and query timeout for predictable benchmark costs.

**Series**: Cloud Cost Controls for Benchmarking
**Post Number**: 3 (Snowflake)
**Target Length**: 2,000-2,500 words
**Status**: RESEARCH COMPLETE - READY FOR DRAFT

---

## Metadata

```yaml
title: "Snowflake credit controls for testing"
slug: snowflake-credit-controls
series: cloud-cost-controls
post_number: 3
tags: [snowflake, cost-management, resource-monitors, benchmarking, credits]
```

---

## Thesis

> Snowflake's credit-based pricing makes warehouse sizing and auto-suspend configuration the primary cost levers. Resource monitors with suspend/notify actions, combined with warehouse-level controls, provide layered protection for benchmark workloads.

---

## Series context

This post adapts the layered-defense pattern to Snowflake:

| Post | Platform | Key cost APIs |
|------|----------|---------------|
| 1 | AWS | Redshift usage limits, Athena workgroup caps |
| 2 | GCP | BigQuery slot reservations, query quotas |
| **3 (this)** | **Snowflake** | **Resource monitors, warehouse auto-suspend, query timeout** |
| 4 | Databricks | Cluster policies, DBU limits |
| 5 | Azure | Synapse DWU caps, Fabric capacity controls |

---

## Outline

### 1. Introduction (~300 words)

**Hook**: Snowflake's per-second billing and automatic scaling seem cost-friendly until a benchmark runs on an XL warehouse for longer than expected. At ~$4/credit, a 16-credit XL warehouse costs $64/hour when active.

**The problem for benchmarking workloads**:
- Warehouses stay active for 5-10 minutes after last query (default auto-suspend)
- Credit consumption continues during idle periods
- Query queuing on undersized warehouses extends runtime and costs
- No native "max spend per day" setting

**Snowflake pricing context**:
- Credits consumed based on warehouse size and runtime
- On-demand: ~$2-4/credit depending on cloud/region/edition
- XS warehouse: 1 credit/hour; 4XL warehouse: 128 credits/hour
- Per-second billing with 60-second minimum

### 2. Snowflake cost model (~400 words)

**Warehouse sizing and credit consumption**:

| Size | Credits/Hour | Typical cost/hour |
|------|--------------|-------------------|
| XS | 1 | $2-4 |
| S | 2 | $4-8 |
| M | 4 | $8-16 |
| L | 8 | $16-32 |
| XL | 16 | $32-64 |
| 2XL | 32 | $64-128 |
| 3XL | 64 | $128-256 |
| 4XL | 128 | $256-512 |

**What drives benchmark costs**:
- Warehouse size (credits/hour)
- Query runtime (including queue time)
- Auto-suspend delay (default 5-10 minutes)
- Clustering/optimization background processes

**Storage vs compute split**:
- Compute: Credit-based, variable
- Storage: $23/TB/month (standard), $40/TB (on-demand)
- Benchmark data at SF100 (~100GB) = ~$2.30/month storage

### 3. Layered cost controls (~300 words)

**Architecture** (adapted from AWS pattern):

```
┌─────────────────────────────────────────────────────────┐
│  Layer 3: Account-level resource monitor (suspend)       │
│  - Credit quota for entire account                       │
│  - Suspend all warehouses at threshold                   │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Warehouse-level resource monitor (notify)      │
│  - Credit quota per warehouse                            │
│  - Email alerts at thresholds                            │
├─────────────────────────────────────────────────────────┤
│  Layer 1: Warehouse configuration (hard limits)          │
│  - Auto-suspend (1 minute for benchmarks)                │
│  - Statement timeout (max query runtime)                 │
│  - Warehouse size (right-size for workload)              │
└─────────────────────────────────────────────────────────┘
```

### 4. Warehouse-level controls (~500 words)

#### Auto-suspend configuration

```sql
-- Aggressive auto-suspend for benchmark warehouses
ALTER WAREHOUSE benchmark_wh SET
  AUTO_SUSPEND = 60,  -- 1 minute (minimum)
  AUTO_RESUME = TRUE;
```

**Default is 600 seconds (10 minutes)**. For benchmarks, 60 seconds is appropriate since workloads are bursty.

**Trade-off**: More resume latency (~1-2 seconds) between query batches.

#### Statement timeout

```sql
-- Prevent runaway queries (30 minute max)
ALTER WAREHOUSE benchmark_wh SET
  STATEMENT_TIMEOUT_IN_SECONDS = 1800;
```

**Behavior**: Queries exceeding timeout are canceled. Useful for catching inefficient queries during development.

#### Warehouse sizing

```sql
-- Create appropriately sized warehouse
CREATE WAREHOUSE benchmark_wh
  WAREHOUSE_SIZE = 'MEDIUM'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE;
```

**Right-sizing for TPC-H**:
- SF1: XS or S sufficient
- SF10: M or L recommended
- SF100: L or XL for reasonable runtimes

### 5. Resource monitors (~500 words)

#### Creating a resource monitor

```sql
-- Account-level monitor with suspend action
CREATE RESOURCE MONITOR benchmark_monitor
  WITH
    CREDIT_QUOTA = 100
    FREQUENCY = MONTHLY
    START_TIMESTAMP = IMMEDIATELY
    TRIGGERS
      ON 50 PERCENT DO NOTIFY
      ON 80 PERCENT DO NOTIFY
      ON 100 PERCENT DO SUSPEND;

-- Attach to account
ALTER ACCOUNT SET RESOURCE_MONITOR = benchmark_monitor;
```

**Actions available**:
- `NOTIFY`: Send notification (email to account admins)
- `SUSPEND`: Suspend warehouses, running queries complete
- `SUSPEND_IMMEDIATE`: Suspend warehouses, cancel running queries

#### Warehouse-specific monitors

```sql
-- Per-warehouse monitor
CREATE RESOURCE MONITOR wh_monitor
  WITH CREDIT_QUOTA = 20;

-- Attach to specific warehouse
ALTER WAREHOUSE benchmark_wh
  SET RESOURCE_MONITOR = wh_monitor;
```

**Best practice**: Use warehouse-level monitors for granular control, account-level as backstop.

### 6. Query-level controls (~300 words)

#### Query timeout parameter

```sql
-- Session-level timeout
ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 600;

-- Or per-query via warehouse setting
```

#### Query tagging for cost attribution

```sql
-- Tag queries for tracking
ALTER SESSION SET QUERY_TAG = 'tpch-sf10-power-run';
```

**Useful for**: Identifying which benchmark runs consumed credits via `QUERY_HISTORY`.

### 7. Comparison with AWS/GCP approach (~200 words)

| Aspect | AWS (Redshift) | GCP (BigQuery) | Snowflake |
|--------|----------------|----------------|-----------|
| Pricing unit | RPU-hours | Bytes scanned | Credits |
| Per-service limit | Usage limit API | max_bytes_billed | Resource monitor |
| Auto-shutdown | Manual | N/A (serverless) | Auto-suspend |
| Native budget action | Yes | Pub/Sub required | Suspend action |
| Granularity | Workgroup | Project/query | Warehouse/account |

### 8. Complete setup example (~300 words)

**Layered setup for a 100-credit/month benchmark budget**:

```sql
-- Layer 1: Warehouse configuration
CREATE WAREHOUSE benchmark_wh
  WAREHOUSE_SIZE = 'MEDIUM'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  STATEMENT_TIMEOUT_IN_SECONDS = 1800;

-- Layer 2: Warehouse monitor (80% notify)
CREATE RESOURCE MONITOR wh_monitor
  WITH CREDIT_QUOTA = 80
  TRIGGERS ON 80 PERCENT DO NOTIFY;
ALTER WAREHOUSE benchmark_wh SET RESOURCE_MONITOR = wh_monitor;

-- Layer 3: Account backstop (100% suspend)
CREATE RESOURCE MONITOR account_monitor
  WITH CREDIT_QUOTA = 100
  TRIGGERS
    ON 80 PERCENT DO NOTIFY
    ON 100 PERCENT DO SUSPEND;
ALTER ACCOUNT SET RESOURCE_MONITOR = account_monitor;
```

### 9. Limitations (~200 words)

**What these controls don't cover**:
- Storage costs (charged separately, no credit quota)
- Serverless features (Snowpipe, tasks) consume credits outside warehouses
- Cloud services layer (metadata operations)
- Reader account consumption

**Resource monitor caveats**:
- Account can only have one account-level monitor
- Resetting quota requires manual intervention
- Suspended warehouses need ACCOUNTADMIN to resume

### 10. Conclusion (~150 words)

**Key takeaways**:
1. Warehouse auto-suspend is your first line of defense (set to 60 seconds for benchmarks)
2. Resource monitors provide credit quotas with suspend/notify actions
3. Layer warehouse-level monitors under account-level backstop
4. Right-size warehouses for your scale factor to avoid queue time

**Next in series**: Databricks cost controls, cluster policies and DBU limits for Spark benchmarking.

---

## Research completed

- [x] Verify current Snowflake credit pricing by edition/cloud - See `research/snowflake-credit-controls.md`
- [x] Resource monitor behavior documented - NOTIFY, SUSPEND, SUSPEND_IMMEDIATE actions
- [x] Warehouse sizes and credit consumption verified - XS (1) to 6XL (512) credits/hour
- [x] Auto-suspend minimum: 60 seconds, default 600 seconds
- [ ] Benchmark typical credit consumption for TPC-H - Estimates in research, needs validation
- [x] Document serverless feature credit consumption - Not covered by resource monitors

## Verified References

[^1]: [Understanding compute cost](https://docs.snowflake.com/en/user-guide/cost-understanding-compute) - Snowflake. Warehouse sizes 1-512 credits/hour.

[^2]: [Working with resource monitors](https://docs.snowflake.com/en/user-guide/resource-monitors) - Snowflake. NOTIFY, SUSPEND, SUSPEND_IMMEDIATE actions.

[^3]: [Warehouse considerations](https://docs.snowflake.com/en/user-guide/warehouses-considerations) - Snowflake. Auto-suspend minimum 60 seconds.

[^4]: [Cost controls for warehouses](https://docs.snowflake.com/en/user-guide/cost-controlling-controls) - Snowflake. Statement timeout, auto-suspend best practices.

[^5]: [Snowflake Pricing Guide 2026](https://mammoth.io/blog/snowflake-pricing/) - Mammoth Analytics. ~$2/credit on-demand.

[^6]: [CREATE RESOURCE MONITOR](https://docs.snowflake.com/en/sql-reference/sql/create-resource-monitor) - Snowflake. SQL syntax and options.

---

*Outline created: 2026-01-31*
*Research completed: 2026-01-31*
*Status: RESEARCH COMPLETE - READY FOR DRAFT*
