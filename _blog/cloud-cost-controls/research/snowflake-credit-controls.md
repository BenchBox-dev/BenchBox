# Snowflake Credit Controls Research

**Research Date**: 2026-01-31
**Status**: Complete
**For Post**: #3 - Snowflake credit controls for testing

---

## Pricing Summary

### Credit Pricing by Edition

| Edition | On-Demand ($/credit) | With Commitment | Key Features |
|---------|---------------------|-----------------|--------------|
| Standard | ~$2.00 | ~$1.50-2.00 | Core features, 1-day Time Travel |
| Enterprise | ~$2.50 | ~$2.00 | 90-day Time Travel, multi-cluster warehouses |
| Business Critical | ~$3.00 | ~$2.50 | Enhanced security, customer-managed keys |

**Notes**:
- Exact pricing varies by cloud provider and region
- AWS, Azure, GCP have slightly different rates
- Commitment discounts require annual contract

**Sources**:
- [Snowflake Pricing Guide 2026](https://mammoth.io/blog/snowflake-pricing/) - Mammoth Analytics
- [Snowflake Pricing Breakdown in 2026](https://qrvey.com/blog/snowflake-pricing/) - Qrvey
- [2026 Snowflake Pricing Guide](https://www.revefi.com/blog/snowflake-pricing-guide) - Revefi

### Warehouse Sizes and Credit Consumption

| Size | Credits/Hour | Relative Cost |
|------|--------------|---------------|
| X-Small | 1 | 1x |
| Small | 2 | 2x |
| Medium | 4 | 4x |
| Large | 8 | 8x |
| X-Large | 16 | 16x |
| 2X-Large | 32 | 32x |
| 3X-Large | 64 | 64x |
| 4X-Large | 128 | 128x |
| 5X-Large | 256 | 256x |
| 6X-Large | 512 | 512x |

**Snowpark-optimized warehouses**: 16x memory, 1.5x cost per size tier.

**Sources**:
- [Understanding compute cost](https://docs.snowflake.com/en/user-guide/cost-understanding-compute) - Snowflake Documentation

### Billing Details

- **Per-second billing** with 60-second minimum
- Each start, resume, or size increase triggers 1-minute minimum
- Resizing only bills for added compute
- Warehouses don't consume credits when suspended
- **Compute typically 80% of total Snowflake bill**

### Storage Pricing

| Region | Price/TB/Month |
|--------|----------------|
| AWS US | ~$23.00 |
| AWS Europe | ~$25.00 |
| AWS Zurich | ~$26.95 |

---

## Cost Control Mechanisms

### 1. Auto-Suspend (Warehouse-Level)

**Description**: Automatic suspension of idle warehouses to stop credit consumption.

**SQL syntax**:
```sql
ALTER WAREHOUSE benchmark_wh SET
  AUTO_SUSPEND = 60,  -- seconds (minimum 60)
  AUTO_RESUME = TRUE;
```

**Key behaviors**:
- Minimum value: 60 seconds (1 minute)
- Values less than 30 or not multiples of 30 may behave unexpectedly (30-second poll interval)
- Setting to 0 or NULL: warehouse never suspends (not recommended)
- Default: 600 seconds (10 minutes)

**Best practices by workload**:
| Workload Type | Recommended Auto-Suspend |
|---------------|-------------------------|
| BI/Query warehouses | 600 seconds (cache retention) |
| Task warehouses | 60 seconds (immediate) |
| Benchmark warehouses | 60 seconds |
| Sporadic queries | 60 seconds |
| Heavy steady workload | Consider disabling |

**Trade-off**: Short auto-suspend = more resume latency (~1-2 seconds) between query batches.

**Sources**:
- [Warehouse considerations](https://docs.snowflake.com/en/user-guide/warehouses-considerations) - Snowflake Documentation
- [Cost controls for warehouses](https://docs.snowflake.com/en/user-guide/cost-controlling-controls) - Snowflake Documentation
- [Warehouse Auto-Suspend in Snowflake](https://www.capitalone.com/software/blog/slingshot-warehouse-auto-suspend/) - Capital One

### 2. Resource Monitors (Credit Quotas)

**Description**: Credit quotas with trigger actions (notify, suspend) at percentage thresholds.

**SQL syntax**:
```sql
CREATE OR REPLACE RESOURCE MONITOR benchmark_monitor
  WITH
    CREDIT_QUOTA = 100
    FREQUENCY = MONTHLY
    START_TIMESTAMP = IMMEDIATELY
    TRIGGERS
      ON 50 PERCENT DO NOTIFY
      ON 80 PERCENT DO NOTIFY
      ON 100 PERCENT DO SUSPEND
      ON 110 PERCENT DO SUSPEND_IMMEDIATE;
```

**Trigger actions**:
| Action | Behavior |
|--------|----------|
| NOTIFY | Send alert, no warehouse impact |
| SUSPEND | Suspend warehouses after running queries complete |
| SUSPEND_IMMEDIATE | Suspend immediately, cancel running queries |

**Action limits per monitor**:
- 1 Suspend action
- 1 Suspend Immediate action
- Up to 5 Notify actions

**Frequency options**:
- Daily
- Weekly
- Monthly
- Yearly
- Never (accumulates indefinitely)

All resets occur at 12:00 AM UTC.

**Monitor types**:
- **Account-level**: One per account, applies to all warehouses
- **Warehouse-level**: Multiple allowed, assigned to specific warehouses

**Attachment**:
```sql
-- Account-level
ALTER ACCOUNT SET RESOURCE_MONITOR = benchmark_monitor;

-- Warehouse-level
ALTER WAREHOUSE benchmark_wh SET RESOURCE_MONITOR = wh_monitor;
```

**Key behaviors**:
- If either account or warehouse monitor triggers suspend, warehouse stops
- Only ACCOUNTADMIN can create resource monitors
- Suspended warehouses need quota increase or threshold change to resume

**Sources**:
- [Working with resource monitors](https://docs.snowflake.com/en/user-guide/resource-monitors) - Snowflake Documentation
- [CREATE RESOURCE MONITOR](https://docs.snowflake.com/en/sql-reference/sql/create-resource-monitor) - Snowflake Documentation
- [Snowflake Resource Monitors 101](https://www.chaosgenius.io/blog/snowflake-resource-monitors/) - ChaosGenius

### 3. Statement Timeout (Query-Level)

**Description**: Maximum runtime for individual queries.

**SQL syntax**:
```sql
-- Warehouse-level
ALTER WAREHOUSE benchmark_wh SET
  STATEMENT_TIMEOUT_IN_SECONDS = 1800;  -- 30 minutes

-- Session-level
ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 600;  -- 10 minutes
```

**Use case**: Catch runaway queries during benchmark development.

### 4. Query Tagging (Cost Attribution)

**Description**: Tag queries for tracking in QUERY_HISTORY.

**SQL syntax**:
```sql
ALTER SESSION SET QUERY_TAG = 'tpch-sf10-power-run';
```

**Use case**: Identify which benchmark runs consumed credits.

---

## Comparison with AWS/GCP

| Aspect | AWS (Redshift Serverless) | GCP (BigQuery) | Snowflake |
|--------|--------------------------|----------------|-----------|
| Pricing unit | RPU-hours | TB scanned | Credits |
| Per-service limit | Usage limit API | max_bytes_billed | Resource monitor |
| Auto-shutdown | Manual | N/A (serverless) | Auto-suspend |
| Native budget action | Yes (IAM deny) | Pub/Sub required | Suspend action |
| Granularity | Workgroup | Project/query | Warehouse/account |
| Minimum billing | 60 seconds | None | 60 seconds |

---

## TPC-H Benchmark Credit Estimates

*Estimates based on typical query patterns, actual consumption varies*

| Scale Factor | Warehouse Size | Power Run (est. credits) | Hourly Cost @ $2/credit |
|--------------|----------------|-------------------------|-------------------------|
| SF1 | X-Small | 0.1-0.2 | $0.20-0.40 |
| SF10 | Small/Medium | 0.5-1.0 | $1.00-2.00 |
| SF100 | Large/X-Large | 2-5 | $4.00-10.00 |
| SF1000 | X-Large/2X-Large | 10-20 | $20.00-40.00 |

---

## Gaps and Limitations

**What resource monitors don't cover**:
- Storage costs (charged separately, no credit quota)
- Serverless features (Snowpipe, tasks) outside warehouses
- Cloud services layer (metadata operations)
- Reader account consumption
- AI/ML services credits

**Resource monitor caveats**:
- Only ACCOUNTADMIN can create
- Account can only have one account-level monitor
- Not designed for hourly control
- Recommend 90% threshold buffer instead of 100%
- Each warehouse can only have one monitor assigned

**Resuming suspended warehouses**:
- Requires ACCOUNTADMIN to increase quota or adjust threshold
- No automatic resume at quota reset

---

## Best Practice: Layered Setup

```sql
-- Layer 1: Warehouse configuration
CREATE WAREHOUSE benchmark_wh
  WAREHOUSE_SIZE = 'MEDIUM'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  STATEMENT_TIMEOUT_IN_SECONDS = 1800;

-- Layer 2: Warehouse-level monitor (notify at 80%)
CREATE RESOURCE MONITOR wh_monitor
  WITH CREDIT_QUOTA = 80
  TRIGGERS ON 80 PERCENT DO NOTIFY;
ALTER WAREHOUSE benchmark_wh SET RESOURCE_MONITOR = wh_monitor;

-- Layer 3: Account-level backstop (suspend at 100%)
CREATE RESOURCE MONITOR account_monitor
  WITH CREDIT_QUOTA = 100
  TRIGGERS
    ON 80 PERCENT DO NOTIFY
    ON 100 PERCENT DO SUSPEND;
ALTER ACCOUNT SET RESOURCE_MONITOR = account_monitor;
```

---

## Verification Status

| Claim | Verified | Source |
|-------|----------|--------|
| ~$2/credit on-demand | Yes | Multiple pricing guides |
| 60-second minimum auto-suspend | Yes | Snowflake docs |
| 60-second minimum billing | Yes | Snowflake docs |
| Resource monitor actions | Yes | Snowflake docs |
| ACCOUNTADMIN required for monitors | Yes | Snowflake docs |
| Warehouse sizes 1-512 credits/hour | Yes | Snowflake docs |

---

*Research completed: 2026-01-31*
