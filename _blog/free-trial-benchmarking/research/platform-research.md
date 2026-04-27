# Free Trial Benchmarking: Platform Research

Consolidated research for the "Free Trial Benchmarking" blog series.

*Last updated: 2026-01-31*

---

## Research Status

| Post | Platform | Trial Research | Pricing Research | BenchBox Config | Ready |
|------|----------|----------------|------------------|-----------------|-------|
| 0 | Intro | Complete | Complete | N/A | Yes |
| 1 | Snowflake | Complete | Complete | Documented | Yes |
| 2 | Databricks | Complete | Complete | Documented | Yes |
| 3 | BigQuery | Complete | Complete | Documented | Yes |
| 4 | MotherDuck | Complete | Complete | Documented | Yes |
| 5 | Redshift Serverless | Complete | Complete | Documented | Yes |
| 6 | Starburst Galaxy | Complete | Partial | Documented | Yes |
| 7 | ClickHouse Cloud | Complete | Complete | Documented | Yes |
| 8 | Microsoft Fabric | Complete | Complete | Documented | Yes |
| 9 | Firebolt | Complete | Partial | Documented | Yes |

---

## Platform-by-Platform Research

### 1. Snowflake

**Trial Details**
- Credits: $400
- Duration: 30 days
- No credit card required
- Limitations: Cortex AI capped at ~1 credit/day, no customer support

**Source**: [Snowflake Trial Docs](https://docs.snowflake.com/en/user-guide/admin-trial-account)

**Pricing Model: Credits per Hour by Warehouse Size**

| Size | Credits/Hour | Credits/Second |
|------|--------------|----------------|
| X-Small | 1 | 0.0003 |
| Small | 2 | 0.0006 |
| Medium | 4 | 0.0011 |
| Large | 8 | 0.0022 |
| X-Large | 16 | 0.0044 |
| 2X-Large | 32 | 0.0089 |

**Credit costs**: ~$2-4/credit on-demand (varies by edition and region)

**Source**: [Snowflake Compute Cost Docs](https://docs.snowflake.com/en/user-guide/cost-understanding-compute)

**Billing Details**
- Per-second billing with 60-second minimum per startup
- Warehouses only billed while running
- Gen2 warehouses: 1.25-1.35x credits but faster queries

**Auto-Suspend Best Practices**
- Default: 10 minutes (enabled automatically)
- Recommendation: 5-10 minutes for most workloads
- For benchmarking: Consider shorter (1-2 min) between runs
- Cache consideration: Suspending clears cache, may affect subsequent queries
- Poll interval: ~30 seconds, so values under 30s may not behave as expected

**Source**: [Snowflake Warehouse Considerations](https://docs.snowflake.com/en/user-guide/warehouses-considerations)

**BenchBox Configuration**
```
Installation: uv add snowflake-connector-python
Platform name: snowflake
Supports: SQL only
```

**Features Disabled in Trial**
- External network access (outbound connections)
- Hybrid tables
- Outbound private connectivity
- Container services (limited)
- Data Exchange activation
- Some Public Preview features (e.g., Budgets)

**Source**: [Snowflake Trial Docs](https://docs.snowflake.com/en/user-guide/admin-trial-account)

**Authentication Options**
- Username/password (simplest for trials)
- External browser SSO: Set `authenticator=externalbrowser`
- Key pair authentication: Set `authenticator=SNOWFLAKE_JWT`

**Source**: [Snowflake Authentication Docs](https://docs.snowflake.com/en/developer-guide/node-js/nodejs-driver-authenticate)

**Trial Traps**
- Leaving warehouse running overnight: 1 credit/hour = $2-4/hour
- Forgetting auto-suspend: Can burn 50+ credits in a day
- Large warehouse experimentation: 2X-Large for 1 hour = 32 credits ($64-128)
- Cortex AI features consume credits quickly
- Trial accounts cannot be canceled via UI (must contact support)

**Credit Consumption Estimates (TPC-H)**

| Scale Factor | Est. Credits (X-Small) | Est. Wall Time |
|--------------|------------------------|----------------|
| SF0.01 | 0.1-0.2 | ~5-10 min |
| SF1 | 0.5-1.0 | ~30-60 min |
| SF10 | 2-5 | ~2-4 hours |

---

### 2. Databricks

**Trial Details**
- Credits: $400
- Duration: 14 days (shortest of major platforms)
- No credit card required for signup
- Limitations (personal email): 50 DBU/hr max, CPU only, limited external network

**Source**: [Databricks Free Trial Docs](https://docs.databricks.com/aws/en/getting-started/free-trial)

**Pricing Model: DBUs**

DBU = Databricks Unit, consumption varies by:
- Compute type: All-Purpose ($0.40-0.55/DBU) vs Jobs ($0.15/DBU)
- Instance type: Larger instances consume more DBUs/hour
- Runtime features enabled

**Example**: m4.large (2 cores, 8GB) = 0.4 DBU/hour

**Source**: [Databricks Pricing](https://www.databricks.com/product/pricing)

**Key Insight**: Personal email signups are limited
- Max 50 DBU/hr (limits cluster size)
- No GPU access
- Use business email for full trial capabilities

**Free Trial vs Free Edition**
| Aspect | Free Trial | Free Edition |
|--------|------------|--------------|
| Target | Business evaluation | Students, hobbyists |
| Duration | 14 days | Ongoing |
| Credits | $400 | None (fair usage) |
| Commercial Use | Yes | No |
| Support/SLA | Covered | Not covered |

**Source**: [Databricks Free Trial vs Free Edition](https://docs.databricks.com/aws/en/getting-started/free-trial-vs-free-edition)

**BenchBox Configuration**
```
Installation: uv add databricks-sql-connector
Platform name: databricks, databricks-df
Supports: SQL and DataFrame modes
```

**Trial Traps**
- Two bills: Databricks DBUs + cloud infrastructure (AWS/Azure/GCP)
- All-Purpose compute is 3-4x more expensive than Jobs compute
- 14-day deadline is tight for thorough evaluation
- Azure standard tier retiring October 2026

**Credit Consumption Estimates (TPC-H)**

| Scale Factor | Est. DBUs | Est. Wall Time |
|--------------|-----------|----------------|
| SF0.01 | 1-2 | ~10-15 min |
| SF1 | 5-10 | ~30-60 min |
| SF10 | 20-40 | ~2-4 hours |

---

### 3. BigQuery

**Trial Details**
- Trial credits: $300 (GCP-wide, 90 days)
- Free tier: 1 TB queries/month (ongoing, no expiration)
- Storage: 10 GB free/month
- Sandbox available without credit card

**Source**: [Google Cloud Free](https://cloud.google.com/free), [BigQuery Pricing](https://cloud.google.com/bigquery/pricing)

**Pricing Model: Per-TB Scanned**

- On-demand: $6.25 per TB scanned
- First 1 TB/month: Free
- Minimum charge: 10 MB per table referenced
- LIMIT clause does NOT reduce bytes scanned

**Source**: [BigQuery Pricing Docs](https://cloud.google.com/bigquery/pricing)

**Cost Optimization**
- Partitioning: Can reduce costs 30-90%
- Clustering: Prunes blocks scanned
- Dry runs: Preview bytes before running
- Materialized views: Pre-compute aggregations

**Source**: [BigQuery Cost Best Practices](https://docs.cloud.google.com/bigquery/docs/best-practices-costs)

**BenchBox Configuration**
```
Installation: uv add google-cloud-bigquery google-cloud-storage
Platform name: bigquery
Supports: SQL only
```

**BigQuery Sandbox Limitations**
| Feature | Sandbox | Paid |
|---------|---------|------|
| Query Processing | 1 TB/month | Higher |
| Storage | 10 GB | Higher |
| Table Expiration | 60 days auto-expire | Configurable |
| Streaming Data | No | Yes |
| DML Statements | No | Yes |
| Data Transfer Service | No | Yes |
| BI Engine | 1 GB max | Higher |

**Source**: [BigQuery Sandbox Docs](https://cloud.google.com/bigquery/docs/sandbox)

**Unique Advantage**: Permanent free tier enables ongoing testing
- Run monthly benchmarks indefinitely at SF0.01-SF1
- Track BigQuery version performance over time
- No "trial expired" pressure
- Sandbox available without credit card

**Trial Traps**
- LIMIT clause doesn't reduce cost (still scans full table)
- SELECT * on large tables expensive
- Cross-region queries incur egress costs
- $300 credit shared across ALL GCP services

**Credit Consumption Estimates (TPC-H)**

| Scale Factor | Est. TB Scanned | Est. Cost |
|--------------|-----------------|-----------|
| SF0.01 | ~0.01 TB | Free tier |
| SF1 | ~1 TB | ~$6.25 |
| SF10 | ~10 TB | ~$62.50 |

---

### 4. MotherDuck

**Trial Details**
- Trial: 21 days with full features
- Free tier (ongoing): 10 CU-hours/month, 10 GB storage
- No credit card required
- Regions: AWS us-east-1, eu-central-1

**Source**: [MotherDuck Pricing](https://motherduck.com/product/pricing/)

**Pricing Model: Compute Units (CU)**

- CU = CPU and memory usage over time
- Pulse (auto-scaling): Per-query metering
- Standard/Jumbo/Mega/Giga: Per-second while running
- Estimated: ~$0.25/CU-hour

**Source**: [MotherDuck Pricing Model](https://motherduck.com/docs/about-motherduck/billing/pricing/)

**Platform Plans (Feb 2025 Update)**
- Free: 10 CU-hrs/mo, 10 GB storage
- Lite: $25/mo base + usage
- Business: $100/mo base + usage

**BenchBox Configuration**
```
Installation: uv add duckdb (uses duckdb with MotherDuck token)
Platform name: motherduck
Supports: SQL only
```

**Authentication**
- Browser-based: Run `.open md:` in DuckDB CLI, follow browser prompt
- Token in connection string: `md:my_db?motherduck_token=<token>`
- Environment variable: Set `MOTHERDUCK_TOKEN`
- Python: `duckdb.connect('md:?motherduck_token=<token>')`

**DuckDB Version Compatibility**
- US-East-1: DuckDB 1.3.0-1.4.3
- EU-Central-1: DuckDB 1.4.1-1.4.3

**Source**: [MotherDuck Authentication Docs](https://motherduck.com/docs/key-tasks/authenticating-and-connecting-to-motherduck/authenticating-to-motherduck/)

**Unique Advantage**: DuckDB compatibility
- Test locally with DuckDB, then run same queries on MotherDuck
- Hybrid local+cloud workflow
- No data loading required if using shared databases

**Trial Traps**
- Storage overage (>10 GB): Queries blocked until resolved
- Pulse auto-scaling can consume CUs faster than expected
- Platform fee separate from usage (Lite: $25/mo, Business: $100/mo)

**Credit Consumption Estimates (TPC-H)**

| Scale Factor | Est. CU-hours | Fits Free Tier? |
|--------------|---------------|-----------------|
| SF0.01 | 0.1-0.2 | Yes |
| SF1 | 1-2 | Yes (5-10 runs) |
| SF10 | 5-10 | Borderline |

---

### 5. Redshift Serverless

**Trial Details**
- Credits: $300
- Duration: 90 days (longest of credit-based trials)
- Eligibility: First-time Serverless users only
- Separate from AWS Free Tier

**Source**: [Redshift Free Trial](https://aws.amazon.com/redshift/free-trial/)

**Pricing Model: RPU-hours**

- RPU = Redshift Processing Unit (16 GB memory each)
- Rate: ~$0.36-0.60/RPU-hour (varies by region)
- US East (Ohio): $0.36/RPU-hour
- SA-EAST-1: $0.5976/RPU-hour
- Per-second billing (60-second minimum)

**Capacity Settings**
- Range: 4-1024 RPUs
- Minimum capacity option: 4 RPU (announced June 2025)
- Base + scaled capacity billed at same rate

**Source**: [Redshift Serverless Billing](https://docs.aws.amazon.com/redshift/latest/mgmt/serverless-billing.html)

**Cost Calculation**
```
Cost = (elapsed_time_seconds / 3600) x RPU x rate
Example: 10-min query at 8 RPU = (600/3600) x 8 x $0.36 = $0.48
```

**BenchBox Configuration**
```
Installation: uv add redshift-connector boto3
Platform name: redshift
Supports: SQL only
```

**Unique Advantage**: 90-day trial
- More time for methodical evaluation
- Can test at multiple scale factors without rushing
- Time to learn platform quirks

**Usage Limits Configuration**
- Set RPU-hour limits: Daily, Weekly, or Monthly
- Actions when exceeded: Log, Alert (SNS), or Turn off queries
- Default base capacity: 128 RPU (adjustable 8-512 RPU)
- Auto-pause: Built-in, no manual config needed (scales to zero when idle)

**Source**: [Redshift Serverless Usage Limits](https://docs.aws.amazon.com/redshift/latest/mgmt/serverless-workgroup-max-rpu.html)

**Trial Traps**
- Open transactions continue consuming RPUs
- Concurrency scaling adds to costs
- Region pricing varies significantly ($0.36-$0.60/RPU-hr)
- Usage limits not configured by default (set them immediately)

**Credit Consumption Estimates (TPC-H at 8 RPU)**

| Scale Factor | Est. RPU-hours | Est. Cost |
|--------------|----------------|-----------|
| SF0.01 | 0.5-1 | $0.18-0.36 |
| SF1 | 2-4 | $0.72-1.44 |
| SF10 | 10-20 | $3.60-7.20 |

---

### 6. Starburst Galaxy

**Trial Details**
- Credits: $500 (most generous)
- Duration: 30 days
- Valid email required
- Falls back to Free plan after trial

**Source**: [Starburst Pricing](https://www.starburst.io/pricing/)

**Pricing Model: Universal Credits**

- Credit = universal compute unit
- Consumption same across all tiers
- Price per credit varies by plan (features/support)
- Example: 2-worker cluster = 12 credits/hour

**Source**: [Starburst Billing Basics](https://docs.starburst.io/starburst-galaxy/cluster-administration/monitor-and-manage-cost-and-performance/billing-basics.html)

**BenchBox Configuration**
```
Installation: uv add trino (uses Trino protocol)
Platform name: starburst
Supports: SQL only
```

**Unique Advantage**: Trino compatibility
- Federated queries across data sources
- Same SQL works on open-source Trino
- Good for evaluating Trino ecosystem

**Trial Traps**
- Specific credit-to-dollar rates not publicly documented
- Cluster workers consume credits while running
- Contact sales for committed pricing details

---

### 7. ClickHouse Cloud

**Trial Details**
- Credits: $300
- Duration: 30 days
- Email notifications at 50%, 75%, 90% consumption
- Continues as pay-as-you-go after trial

**Source**: [ClickHouse Pricing](https://clickhouse.com/pricing)

**Pricing Model: Per-Minute Compute**

- Metered per minute in 8 GB RAM increments
- Three tiers: Basic, Scale, Enterprise
- Costs vary by tier, region, and cloud provider
- Service can idle (20-30s resume time)

**Source**: [ClickHouse Billing Docs](https://clickhouse.com/docs/cloud/manage/billing/overview)

**Key Billing Components**
- Compute (primary factor)
- Storage (compressed data size)
- Data transfer (egress)
- ClickPipes: $0.04/GB ingested, $0.20/hr per compute unit

**BenchBox Configuration**
```
Installation: uv add clickhouse-driver
Platform name: clickhouse
Supports: SQL only
```

**Idle Timeout / Auto-Stop**
- Services can be configured with idle timeout
- Compute stops automatically after inactivity period
- Resume time: 20-30 seconds
- Billing continues while service is active (even without queries)

**Source**: [ClickHouse Billing Docs](https://clickhouse.com/docs/cloud/manage/billing/overview)

**Trial Traps**
- Per-minute billing continues while service is active (even without queries)
- 20-30 second resume time after idling
- January 2025 pricing changes (~30% increase for typical workloads)
- Auto-stop configuration critical (set immediately after signup)
- Email notifications at 50%, 75%, 90% consumption (helpful)

---

### 8. Microsoft Fabric

**Trial Details**
- Capacity: 64 CU (or 4 CU, upgradeable)
- Duration: 60 days
- Storage: Up to 1 TB OneLake
- Requires Power BI license (Free tier OK)

**Source**: [Fabric Trial Docs](https://learn.microsoft.com/en-us/fabric/fundamentals/fabric-trial)

**Pricing Model: Capacity Units (CU)**

- CU bundles CPU, memory, disk I/O, network
- ~$0.18/CU-hour
- F2 (2 CU): ~$262.80/month reserved
- Spark: 1 CU = 2 Spark VCores
- SQL: 1 CU = 0.383 Database VCores

**Source**: [Fabric Pricing](https://azure.microsoft.com/en-us/pricing/details/microsoft-fabric/)

**Spark-Specific Billing**
- Autoscale billing available (pay-as-you-go for Spark)
- 0.5 CU-hour per Spark job
- Only charged during active execution

**Source**: [Fabric Spark Billing](https://learn.microsoft.com/en-us/fabric/data-engineering/billing-capacity-management-for-spark)

**BenchBox Configuration**
```
Installation: uv add pyodbc azure-identity azure-storage-file-datalake
Platform names: fabric_dw (SQL), fabric-spark (Spark)
Supports: SQL and DataFrame (Spark)
```

**Unique Characteristic**: Capacity-based, not credit-based
- Throttled when capacity exceeded, not stopped
- Can continue running at reduced performance
- Trial capacity upgradeable (4 CU to 64 CU)

**Throttling Behavior When Capacity Exceeded**
1. **10-min buffer**: Overage protection allows 10 min of future capacity without throttling
2. **Phase 1**: 20-second delays on new interactive operations
3. **Phase 2**: New interactive operations rejected (background allowed)
4. **Phase 3**: All new requests rejected (24-hour carryforward)

**Trial-Specific Limitations**
- Cannot pause/resume trial capacity (paid only)
- Cannot reset once usage limits exceeded
- Must contact Microsoft rep for extension

**Source**: [Fabric Throttling Docs](https://learn.microsoft.com/en-us/fabric/enterprise/throttling)

**Trial Traps**
- Power BI Premium P-SKUs retired December 2024
- Capacity shared across all Fabric workloads
- Region pricing varies 10-15%
- Trial cannot be paused/reset once exceeded

---

### 9. Firebolt

**Trial Details**
- Credits: $200
- Duration: 30 days
- No credit card required
- All node types available

**Source**: [Firebolt Trial Blog](https://www.firebolt.io/blog/firebolt-trial-for-30-days-with-200-free-credits-now-open-to-all)

**Pricing Model: FBU (Firebolt Units)**

- FBU = normalized compute unit
- S node: 8 FBU
- M node: 16 FBU
- Per-second billing while engine running

**Cost Calculation**
```
Compute Cost = query_time_seconds x (fbu_rate/3600) x total_fbu
total_fbu = fbu_per_node x cluster_size
```

**Source**: [Firebolt Billing Docs](https://docs.firebolt.io/overview/billing)

**BenchBox Configuration**
```
Installation: uv add firebolt-sdk
Platform name: firebolt
Supports: SQL only
```

**Trial Traps**
- FBU pricing varies by region (US vs non-US)
- Need to understand FBU system before starting
- Specific $/FBU rates require checking pricing page

---

## Cross-Platform Comparison

### Trial Value by Dollar Amount

| Platform | Credits | Duration | $/Day |
|----------|---------|----------|-------|
| Starburst Galaxy | $500 | 30 days | $16.67 |
| Snowflake | $400 | 30 days | $13.33 |
| Databricks | $400 | 14 days | $28.57 |
| BigQuery | $300 | 90 days | $3.33 |
| Redshift Serverless | $300 | 90 days | $3.33 |
| ClickHouse Cloud | $300 | 30 days | $10.00 |
| Firebolt | $200 | 30 days | $6.67 |

### Constraint Models

**Credit-Limited** (run out of dollars):
- Snowflake, Databricks, Starburst, ClickHouse, Redshift, Firebolt

**Capacity-Limited** (throttled, not stopped):
- Microsoft Fabric, MotherDuck free tier

**Hybrid** (credits + ongoing free tier):
- BigQuery ($300 trial + 1TB/mo ongoing)

### BenchBox Platform Support Summary

| Platform | SQL | DataFrame | Install Command |
|----------|-----|-----------|-----------------|
| Snowflake | Yes | No | `uv add snowflake-connector-python` |
| Databricks | Yes | Yes | `uv add databricks-sql-connector` |
| BigQuery | Yes | No | `uv add google-cloud-bigquery google-cloud-storage` |
| MotherDuck | Yes | No | `uv add duckdb` |
| Redshift | Yes | No | `uv add redshift-connector boto3` |
| Starburst | Yes | No | `uv add trino` |
| ClickHouse | Yes | No | `uv add clickhouse-driver` |
| Fabric (DW) | Yes | No | `uv add pyodbc azure-identity azure-storage-file-datalake` |
| Fabric (Spark) | Yes | Yes | `uv add azure-identity azure-storage-file-datalake requests` |
| Firebolt | Yes | No | `uv add firebolt-sdk` |

---

## Research Sources

### Primary Sources (Official Documentation)

- [Snowflake Trial Accounts](https://docs.snowflake.com/en/user-guide/admin-trial-account)
- [Snowflake Compute Cost](https://docs.snowflake.com/en/user-guide/cost-understanding-compute)
- [Snowflake Warehouse Considerations](https://docs.snowflake.com/en/user-guide/warehouses-considerations)
- [Databricks Free Trial](https://docs.databricks.com/aws/en/getting-started/free-trial)
- [Databricks Pricing](https://www.databricks.com/product/pricing)
- [Google Cloud Free](https://cloud.google.com/free)
- [BigQuery Pricing](https://cloud.google.com/bigquery/pricing)
- [BigQuery Cost Best Practices](https://docs.cloud.google.com/bigquery/docs/best-practices-costs)
- [MotherDuck Pricing](https://motherduck.com/product/pricing/)
- [MotherDuck Billing](https://motherduck.com/docs/about-motherduck/billing/pricing/)
- [Redshift Free Trial](https://aws.amazon.com/redshift/free-trial/)
- [Redshift Serverless Billing](https://docs.aws.amazon.com/redshift/latest/mgmt/serverless-billing.html)
- [Starburst Pricing](https://www.starburst.io/pricing/)
- [Starburst Billing Basics](https://docs.starburst.io/starburst-galaxy/cluster-administration/monitor-and-manage-cost-and-performance/billing-basics.html)
- [ClickHouse Pricing](https://clickhouse.com/pricing)
- [ClickHouse Billing](https://clickhouse.com/docs/cloud/manage/billing/overview)
- [Microsoft Fabric Trial](https://learn.microsoft.com/en-us/fabric/fundamentals/fabric-trial)
- [Fabric Pricing](https://azure.microsoft.com/en-us/pricing/details/microsoft-fabric/)
- [Fabric Spark Billing](https://learn.microsoft.com/en-us/fabric/data-engineering/billing-capacity-management-for-spark)
- [Firebolt Pricing](https://www.firebolt.io/pricing)
- [Firebolt Billing](https://docs.firebolt.io/overview/billing)

### Secondary Sources (Analysis/Guides)

- [Mammoth Analytics Snowflake Pricing Guide](https://mammoth.io/blog/snowflake-pricing/)
- [ChaosGenius Databricks Pricing](https://www.chaosgenius.io/blog/databricks-pricing-guide/)
- [Airbyte BigQuery Pricing](https://airbyte.com/data-engineering-resources/bigquery-pricing)
- [CloudChipr Redshift Pricing](https://cloudchipr.com/blog/amazon-redshift-pricing)
- [Promethium Fabric Pricing Guide](https://promethium.ai/guides/microsoft-fabric-pricing-licensing-guide/)

---

## Research Gaps

### Resolved
- [x] Snowflake warehouse sizing and credits
- [x] Snowflake trial feature limitations
- [x] Snowflake authentication options
- [x] Databricks DBU consumption rates
- [x] Databricks Free Trial vs Free Edition comparison
- [x] BigQuery per-TB pricing details
- [x] BigQuery Sandbox limitations
- [x] MotherDuck CU pricing model
- [x] MotherDuck authentication methods
- [x] MotherDuck DuckDB version compatibility
- [x] Redshift RPU rates by region
- [x] Redshift usage limits configuration
- [x] ClickHouse per-minute billing details
- [x] ClickHouse idle timeout configuration
- [x] Fabric CU pricing breakdown
- [x] Fabric throttling behavior when exceeded
- [x] Firebolt FBU consumption rates

### Outstanding (Low Priority, Not Blocking)
- [ ] Starburst Galaxy specific credit-to-dollar rates (contact sales required)
- [ ] Firebolt specific $/FBU by region (pricing page lookup required)

### To Be Generated During Drafting
- Actual benchmark results from BenchBox runs on each platform
- Platform-specific MCP conversation examples
- BenchBox configuration file examples for each platform

---

---

## Per-Post Checklist

### Post #0: Series Introduction
- [x] Comparison table with all 9 platforms
- [x] Constraint model categorization (credit/capacity/hybrid)
- [x] Trial value ranking ($/day)
- [x] BenchBox installation commands
- [ ] MCP conversation example for platform discovery

### Post #1: Snowflake
- [x] Trial details ($400/30 days)
- [x] Warehouse sizing and credits/hour
- [x] Auto-suspend best practices
- [x] Feature limitations in trial
- [x] Authentication options
- [x] Trial traps
- [x] Credit consumption estimates
- [ ] Actual benchmark results
- [ ] MCP conversation example

### Post #2: Databricks
- [x] Trial details ($400/14 days)
- [x] DBU pricing by compute type
- [x] Personal vs business email limitations
- [x] Free Trial vs Free Edition comparison
- [x] Trial traps
- [x] Credit consumption estimates
- [ ] Actual benchmark results
- [ ] MCP conversation example

### Post #3: BigQuery
- [x] Trial + free tier details
- [x] Per-TB pricing
- [x] Sandbox limitations
- [x] Cost optimization strategies
- [x] Trial traps
- [x] Credit consumption estimates
- [ ] Actual benchmark results
- [ ] MCP conversation example

### Post #4: MotherDuck
- [x] Trial + free tier details
- [x] CU pricing model
- [x] Authentication methods
- [x] DuckDB version compatibility
- [x] Trial traps
- [x] Credit consumption estimates
- [ ] Actual benchmark results
- [ ] MCP conversation example

### Post #5: Redshift Serverless
- [x] Trial details ($300/90 days)
- [x] RPU pricing by region
- [x] Usage limits configuration
- [x] Auto-pause behavior
- [x] Trial traps
- [x] Credit consumption estimates
- [ ] Actual benchmark results
- [ ] MCP conversation example

### Post #6: Starburst Galaxy
- [x] Trial details ($500/30 days)
- [x] Universal credit model
- [x] Trino compatibility
- [x] Trial traps
- [ ] Specific $/credit rates (contact sales)
- [ ] Actual benchmark results
- [ ] MCP conversation example

### Post #7: ClickHouse Cloud
- [x] Trial details ($300/30 days)
- [x] Per-minute billing model
- [x] Idle timeout configuration
- [x] Trial traps
- [ ] Actual benchmark results
- [ ] MCP conversation example

### Post #8: Microsoft Fabric
- [x] Trial details (64 CU/60 days)
- [x] CU pricing model
- [x] Throttling behavior
- [x] Trial-specific limitations
- [x] Trial traps
- [ ] Actual benchmark results
- [ ] MCP conversation example

### Post #9: Firebolt
- [x] Trial details ($200/30 days)
- [x] FBU system (S=8, M=16)
- [x] Per-second billing
- [ ] Specific $/FBU rates by region
- [ ] Actual benchmark results
- [ ] MCP conversation example

---

*Research compiled: 2026-01-31*
*Last updated: 2026-01-31*
