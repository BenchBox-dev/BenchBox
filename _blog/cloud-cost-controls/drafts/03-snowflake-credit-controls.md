# Snowflake credit controls for testing

*Part 3 of the Cloud Cost Controls for Benchmarking series*

> Resource monitors, warehouse auto-suspend, and query timeout for predictable benchmark costs.

**TL;DR**: Snowflake's credit-based pricing makes warehouse sizing and auto-suspend configuration the primary cost levers. Resource monitors with suspend actions provide hard credit limits per warehouse or account. Combined with aggressive auto-suspend (60 seconds minimum), these controls create layered protection for benchmark workloads.

*For series methodology, pricing scope, and cross-platform comparison, see the [series introduction](00-series-intro.md).*

---

## Why Snowflake benchmarks need cost controls

Snowflake's per-second billing and automatic scaling seem cost-friendly until a benchmark runs longer than expected. At approximately $2-4 per credit (depending on edition and region)[^1], costs accumulate based on warehouse size and runtime.

The numbers add up quickly:

| Warehouse Size | Credits/Hour | Cost/Hour @ $2/credit |
|----------------|--------------|----------------------|
| X-Small | 1 | $2 |
| Small | 2 | $4 |
| Medium | 4 | $8 |
| Large | 8 | $16 |
| X-Large | 16 | $32 |
| 2X-Large | 32 | $64 |

A benchmark that runs for an hour on an X-Large warehouse costs $32. If auto-suspend is set to the default 10 minutes and you step away between query batches, those idle minutes accumulate charges too.

**The specific challenges for benchmarking**:

- **Auto-suspend delay**: Default is 600 seconds (10 minutes). Warehouses stay active and consuming credits even when idle.
- **No native daily spending limit**: Snowflake doesn't have a "max credits per day" setting. Resource monitors provide quotas, but they're monthly or weekly by default.
- **Query queuing**: An undersized warehouse queues queries, extending runtime and accumulating more credits than a properly sized warehouse would.
- **Right-sizing uncertainty**: It's not obvious which warehouse size matches your workload until you've run it.

**Pricing context by edition**:

| Edition | On-Demand ($/credit) | Key Features |
|---------|---------------------|--------------|
| Standard | ~$2.00 | Core features, 1-day Time Travel |
| Enterprise | ~$2.50 | 90-day Time Travel, multi-cluster |
| Business Critical | ~$3.00 | Enhanced security, customer-managed keys |

Exact pricing varies by cloud provider (AWS, Azure, GCP) and region. Annual commitments reduce per-credit costs but require upfront commitment[^1].

---

## What drives benchmark costs

Unlike BigQuery (charged per-TB scanned) or Athena (same), Snowflake charges based on compute time. Understanding the cost drivers helps set appropriate controls.

### Warehouse size

Each warehouse size doubles both the compute capacity and the credit consumption:

| Size | Credits/Hour | Relative to X-Small |
|------|--------------|---------------------|
| X-Small | 1 | 1x |
| Small | 2 | 2x |
| Medium | 4 | 4x |
| Large | 8 | 8x |
| X-Large | 16 | 16x |
| 2X-Large | 32 | 32x |
| 3X-Large | 64 | 64x |
| 4X-Large | 128 | 128x |

**Right-sizing for TPC-H** (planning baseline):
- SF1 (~1GB): X-Small or Small sufficient
- SF10 (~10GB): Small or Medium recommended
- SF100 (~100GB): Large or X-Large for reasonable runtimes
- SF1000 (~1TB): X-Large or larger

An undersized warehouse runs slower and consumes credits longer. An oversized warehouse completes faster but burns through credits at a higher rate. There's often a sweet spot where the faster completion time of a larger warehouse actually costs less than an undersized one running longer.

### Auto-suspend behavior

Warehouses consume credits whenever they're running, regardless of whether queries are actively executing. The auto-suspend setting controls how long a warehouse stays active after the last query completes.

- **Default**: 600 seconds (10 minutes)
- **Minimum**: 60 seconds (1 minute)
- **Disabled**: 0 or NULL (not recommended for benchmarks)

Each time a warehouse resumes from suspended state, it incurs a 60-second minimum charge[^2]. For an X-Small warehouse at $2/credit, that's about $0.033 per resume; for an X-Large at $32/hour, about $0.53. For bursty workloads, very frequent suspend/resume cycles can cost more than leaving the warehouse running briefly. In practice, 60-second auto-suspend is a good starting point for benchmark-focused warehouses.

### Storage (separate from compute)

Storage costs are charged separately and are typically a small fraction of total cost:

- ~$23/TB/month (AWS US regions)[^1]
- TPC-H at SF100 (~100GB) = ~$2.30/month storage

Storage costs don't have credit quotas. Resource monitors only control compute credits.

---

## Layered cost controls

Following the same layered approach from our AWS and GCP posts:

```text
+-----------------------------------------------------------+
|  Layer 3: Account-level resource monitor (suspend)         |
|  - Credit quota for entire account                         |
|  - Suspend all warehouses at threshold                     |
+-----------------------------------------------------------+
|  Layer 2: Warehouse-level resource monitor (notify)        |
|  - Credit quota per warehouse                              |
|  - Email alerts at thresholds                              |
+-----------------------------------------------------------+
|  Layer 1: Warehouse configuration (hard limits)            |
|  - Auto-suspend (60 seconds for benchmarks)                |
|  - Statement timeout (max query runtime)                   |
|  - Warehouse size (right-size for workload)                |
+-----------------------------------------------------------+
```

**Why layers matter**: Layer 1 minimizes idle credit consumption and catches runaway queries. Layer 2 provides early warning when a specific warehouse approaches its budget. Layer 3 is the circuit breaker that stops all compute when total account credits are exhausted.

---

## Warehouse-level controls

### Auto-suspend configuration

```sql
-- Aggressive auto-suspend for benchmark warehouses
ALTER WAREHOUSE benchmark_wh SET
  AUTO_SUSPEND = 60,  -- 1 minute (minimum allowed)
  AUTO_RESUME = TRUE;
```

**Behavior**: Warehouse suspends 60 seconds after the last query completes. `AUTO_RESUME = TRUE` means the next query automatically resumes the warehouse (with a 1-2 second delay).

**Default is 600 seconds (10 minutes)**. For BI/query warehouses with frequent ad-hoc queries, longer suspend times make sense to retain cached data. For benchmark warehouses with bursty workloads, 60 seconds is appropriate.

**Trade-off**: More frequent resume cycles mean more 60-second minimum charges. If you're running queries every 30 seconds, the warehouse stays active anyway. If you have 5-minute gaps between batches, short auto-suspend saves significant credits.

### Statement timeout

```sql
-- Prevent runaway queries
ALTER WAREHOUSE benchmark_wh SET
  STATEMENT_TIMEOUT_IN_SECONDS = 1800;  -- 30 minutes
```

**Behavior**: Queries exceeding 30 minutes are automatically canceled. This catches inefficient queries during benchmark development without requiring intervention.

For TPC-H, most queries complete in seconds to minutes depending on scale factor and warehouse size. A 30-minute timeout provides headroom while catching obviously stuck queries.

### Creating a benchmark warehouse

Putting these settings together when creating a new warehouse:

```sql
CREATE WAREHOUSE benchmark_wh
  WAREHOUSE_SIZE = 'MEDIUM'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  STATEMENT_TIMEOUT_IN_SECONDS = 1800;
```

`INITIALLY_SUSPENDED = TRUE` means the warehouse doesn't start consuming credits immediately upon creation. It only activates when the first query runs.

---

## Resource monitors

Resource monitors are Snowflake's primary mechanism for credit quotas. They can trigger notifications and actions when credit consumption reaches defined thresholds.

**Important**: When a resource monitor triggers SUSPEND, warehouses stop accepting new queries. To resume operations, you'll need ACCOUNTADMIN privileges to either increase the credit quota, adjust the threshold, or wait for the quota reset period. Plan accordingly if you're not the account admin.



### Creating a resource monitor

```sql
CREATE RESOURCE MONITOR benchmark_monitor
  WITH
    CREDIT_QUOTA = 100
    FREQUENCY = MONTHLY
    START_TIMESTAMP = IMMEDIATELY
    TRIGGERS
      ON 50 PERCENT DO NOTIFY
      ON 80 PERCENT DO NOTIFY
      ON 100 PERCENT DO SUSPEND;
```

**Trigger actions**:

| Action | Behavior |
|--------|----------|
| NOTIFY | Send notification to account admins. No impact on warehouses. |
| SUSPEND | Suspend warehouses after running queries complete. New queries queue. |
| SUSPEND_IMMEDIATE | Suspend warehouses immediately, cancel running queries. |

**Which suspend action to use**: For benchmarks, prefer SUSPEND over SUSPEND_IMMEDIATE. SUSPEND lets in-progress queries finish (preserving results), while SUSPEND_IMMEDIATE cancels them mid-flight. Use SUSPEND_IMMEDIATE only as an emergency measure when a runaway query is actively consuming credits and you need it stopped now.

**Limits per monitor**:
- Up to 5 NOTIFY triggers at different thresholds
- 1 SUSPEND trigger
- 1 SUSPEND_IMMEDIATE trigger

### Account-level monitor

An account-level monitor applies to all warehouses in the account:

```sql
-- Create the monitor
CREATE RESOURCE MONITOR account_monitor
  WITH
    CREDIT_QUOTA = 100
    FREQUENCY = MONTHLY
    START_TIMESTAMP = IMMEDIATELY
    TRIGGERS
      ON 80 PERCENT DO NOTIFY
      ON 100 PERCENT DO SUSPEND;

-- Attach to account (requires ACCOUNTADMIN)
ALTER ACCOUNT SET RESOURCE_MONITOR = account_monitor;
```

**Only one account-level monitor** can be active at a time. It serves as the backstop for all compute across the account.

### Warehouse-level monitor

Warehouse-level monitors provide granular control over specific warehouses:

```sql
-- Create warehouse-specific monitor
CREATE RESOURCE MONITOR wh_monitor
  WITH
    CREDIT_QUOTA = 50
    FREQUENCY = MONTHLY
    TRIGGERS
      ON 80 PERCENT DO NOTIFY
      ON 100 PERCENT DO SUSPEND;

-- Attach to specific warehouse
ALTER WAREHOUSE benchmark_wh SET RESOURCE_MONITOR = wh_monitor;
```

**Multiple warehouse-level monitors** can exist, each assigned to different warehouses. If both an account-level and warehouse-level monitor exist, either one triggering SUSPEND will stop the warehouse.

### Frequency options

Resource monitors can reset on different schedules:

| Frequency | Reset |
|-----------|-------|
| DAILY | Midnight UTC |
| WEEKLY | Midnight UTC on first day of week |
| MONTHLY | Midnight UTC on first day of month |
| YEARLY | Midnight UTC on first day of year |
| NEVER | Never resets (accumulates indefinitely) |

For benchmark workloads, MONTHLY is typical. DAILY provides tighter control but requires higher administrative overhead if the quota is hit.

---

## Query-level controls

### Query timeout

In addition to warehouse-level timeout, you can set session-level limits:

```sql
-- Session-level timeout
ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 600;  -- 10 minutes
```

This applies to queries in the current session only. Useful for interactive debugging where you want tighter limits than the warehouse default.

**Tip: query tagging for cost attribution**. Set `ALTER SESSION SET QUERY_TAG = 'tpch-sf10-power-run'` before benchmark runs, then query `snowflake.account_usage.query_history` to see where credits went. This doesn't control costs but helps with post-run analysis.

---

## Comparison with AWS and GCP

| Aspect | AWS (Redshift Serverless) | GCP (BigQuery) | Snowflake |
|--------|--------------------------|----------------|-----------|
| Pricing unit | RPU-hours | Bytes scanned | Credits |
| Per-service limit | Usage limit API | max_bytes_billed | Resource monitor |
| Auto-shutdown | Manual | N/A (serverless) | Auto-suspend |
| Native budget action | Yes (IAM deny) | Pub/Sub required | Suspend action |
| Granularity | Workgroup | Project/query | Warehouse/account |
| Minimum billing | 60 seconds | None | 60 seconds |

**Key differences from AWS/GCP**: Snowflake is credit-time based (not bytes scanned), supports native suspend actions through resource monitors, and gives direct warehouse sizing control. Storage charges are separate from monitor quotas.

---

## Complete setup example

Putting all three layers together for a 100-credit/month benchmark budget:

### Layer 1: Warehouse configuration

```sql
-- Create appropriately sized warehouse with aggressive controls
CREATE WAREHOUSE benchmark_wh
  WAREHOUSE_SIZE = 'MEDIUM'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  STATEMENT_TIMEOUT_IN_SECONDS = 1800;
```

### Layer 2: Warehouse monitor (notify at 80%)

```sql
-- Early warning for this specific warehouse
CREATE RESOURCE MONITOR wh_monitor
  WITH
    CREDIT_QUOTA = 80
    FREQUENCY = MONTHLY
    TRIGGERS
      ON 80 PERCENT DO NOTIFY;

ALTER WAREHOUSE benchmark_wh SET RESOURCE_MONITOR = wh_monitor;
```

### Layer 3: Account backstop (suspend at 100%)

```sql
-- Account-wide circuit breaker
CREATE RESOURCE MONITOR account_monitor
  WITH
    CREDIT_QUOTA = 100
    FREQUENCY = MONTHLY
    TRIGGERS
      ON 80 PERCENT DO NOTIFY
      ON 100 PERCENT DO SUSPEND;

ALTER ACCOUNT SET RESOURCE_MONITOR = account_monitor;
```

### Resulting protection

| Layer | Control | Limit | Action |
|-------|---------|-------|--------|
| 1 | Auto-suspend | 60 seconds idle | Warehouse suspends |
| 1 | Statement timeout | 30 minutes | Query canceled |
| 2 | Warehouse monitor | 80 credits | Email notification |
| 3 | Account monitor | 100 credits | All warehouses suspend |

With this setup, idle compute suspends quickly, runaway queries time out, and account-wide consumption stops at the defined monitor threshold.

---

## Limitations

**What resource monitors don't cover**:

- **Storage costs**: Charged separately, no credit quota available
- **Serverless features**: Snowpipe, tasks, and other serverless compute consume credits outside warehouse monitors
- **Cloud services layer**: Metadata operations consume credits (usually < 10% of total)
- **Reader accounts**: Consumption by reader accounts doesn't count against your monitors

**Resource monitor caveats**:

- **ACCOUNTADMIN required**: Only ACCOUNTADMIN role can create resource monitors
- **One account-level monitor**: Can only have one active account-level monitor
- **Not designed for hourly control**: Minimum frequency is DAILY; finer granularity requires manual monitoring
- **Resuming suspended warehouses**: Requires ACCOUNTADMIN to either increase quota or adjust threshold

## Conclusions

Snowflake's credit-based pricing makes warehouse configuration the primary cost lever. Unlike byte-scanned pricing (BigQuery, Athena), costs scale with compute time and warehouse size.

**Key takeaways**:

1. **Auto-suspend is your first line of defense**. Set to 60 seconds for benchmark warehouses to minimize idle credit consumption.

2. **Resource monitors provide credit quotas**. Use warehouse-level monitors for granular control and an account-level monitor as the backstop.

3. **Right-size your warehouse**. An undersized warehouse runs longer and may cost more than a properly sized one completing faster.

4. **Statement timeout catches runaway queries**. Set a reasonable timeout (e.g., 30 minutes) to prevent queries from running indefinitely.

**Estimated credit consumption for TPC-H** (rough planning ranges based on warehouse size and expected runtimes, not measured benchmarks; actual consumption depends on query complexity, caching, and data layout):

| Scale Factor | Recommended Size | Power Run (est. credits) |
|--------------|-----------------|-------------------------|
| SF1 | X-Small | 0.05-0.3 |
| SF10 | Small/Medium | 0.3-1.5 |
| SF100 | Large/X-Large | 2-8 |
| SF1000 | X-Large/2X-Large | 8-30 |

**Next steps**:

- Review warehouse auto-suspend settings (10 minutes default can be expensive)
- Create resource monitors appropriate to your budget before running benchmarks
- Tag queries for post-run cost attribution

---

## References

[^1]: [Snowflake Pricing](https://www.snowflake.com/en/pricing/), Snowflake. On-demand pricing varies by edition, cloud provider, and region.

[^2]: [Understanding compute cost](https://docs.snowflake.com/en/user-guide/cost-understanding-compute), Snowflake Documentation. Warehouse sizes and credit consumption.

[^3]: [Working with resource monitors](https://docs.snowflake.com/en/user-guide/resource-monitors), Snowflake Documentation. NOTIFY, SUSPEND, SUSPEND_IMMEDIATE actions.

[^4]: [Warehouse considerations](https://docs.snowflake.com/en/user-guide/warehouses-considerations), Snowflake Documentation. Auto-suspend minimum 60 seconds.

[^5]: [CREATE RESOURCE MONITOR](https://docs.snowflake.com/en/sql-reference/sql/create-resource-monitor), Snowflake Documentation. SQL syntax and options.

[^6]: [Cost controls for warehouses](https://docs.snowflake.com/en/user-guide/cost-controlling-controls), Snowflake Documentation. Statement timeout, auto-suspend best practices.

---

*Questions or feedback? [Open an issue](https://github.com/benchbox/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: 2470
**Created**: 2026-01-31
**Series**: Cloud Cost Controls for Benchmarking (Post 3: Snowflake)
