# Cost Estimation Framework

## Overview

The cost estimation framework calculates compute costs for benchmark executions across different cloud data platforms. It provides:

- **Platform-specific cost models** for Snowflake, BigQuery, Redshift, and Databricks
- **Automatic cost calculation** integrated into benchmark result export
- **Detailed cost breakdown** by phase (power test, throughput test, maintenance test)
- **Validation and error handling** for robustness

## Supported Platforms

| Platform | Cost Model | Pricing Basis | Accuracy |
|----------|------------|---------------|----------|
| **Snowflake** | Credit-based | Credits consumed × price per credit | ±10% |
| **BigQuery** | Per-TB scanned | Data scanned (TB) × price per TB | ±10% |
| **Redshift** | Time-based | Execution time × node count × hourly rate | Marginal cost only* |
| **Databricks** | DBU-based | Execution time × DBU/hour × price per DBU | ±15% |
| **DuckDB** | Zero cost | Local execution | Exact ($0.00) |
| **ClickHouse** | Zero cost | Local execution | Exact ($0.00) |

\* See [Redshift Cost Model Clarifications](#redshift-cost-model-clarifications) below.

## Architecture

```
BenchmarkResults (from execution)
    ↓
add_cost_estimation_to_results()
    ↓
┌─────────────────────────────────────┐
│ 1. Extract platform config          │
│ 2. Validate configuration            │
│ 3. Calculate per-query costs         │
│ 4. Aggregate by phase                │
│ 5. Calculate total benchmark cost    │
└─────────────────────────────────────┘
    ↓
BenchmarkResults with cost_summary
    ↓
JSON export (schema v1.1)
```

### Key Components

1. **`integration.py`** - Main entry point, orchestrates cost calculation
2. **`calculator.py`** - Platform-specific cost calculation logic
3. **`pricing.py`** - Pricing tables with version tracking
4. **`models.py`** - Data models (QueryCost, PhaseCost, BenchmarkCost)
5. **`storage.py`** - Storage cost estimation

## Output Schema

The cost estimation framework adds a `cost_summary` object to benchmark results with the following structure:

```json
{
  "cost_summary": {
    "total_cost": 17.60,
    "currency": "USD",
    "cost_model": "actual",
    "warnings": [
      "Storage cost estimate: $0.1534 for 4.87 TB over 1.0 hours. On-demand storage pricing..."
    ],
    "storage_cost": 0.1534,
    "phase_costs": [
      {
        "phase_name": "power_test",
        "total_cost": 5.20,
        "query_count": 22,
        "currency": "USD",
        "wall_clock_duration_seconds": 450.0,
        "concurrent_streams": 1,
        "effective_cost_per_hour": 41.60
      },
      {
        "phase_name": "throughput_test",
        "total_cost": 12.40,
        "query_count": 88,
        "currency": "USD",
        "wall_clock_duration_seconds": 300.0,
        "concurrent_streams": 4,
        "effective_cost_per_hour": 148.80
      }
    ],
    "platform_details": {
      "platform": "snowflake",
      "edition": "standard",
      "cloud": "aws",
      "region": "us-east-1",
      "pricing_version": "2025.11",
      "pricing_date": "2025-11-09",
      "storage_estimate": {
        "storage_cost": 0.1534,
        "storage_tb": 4.87,
        "price_per_tb_month": 23.00,
        "duration_hours": 1.0,
        "note": "On-demand storage pricing. Time Travel and Fail-safe may incur additional costs."
      }
    }
  }
}
```

### Output Fields

**Top-level fields**:
- `total_cost` - Total compute cost across all phases (USD)
- `currency` - Always "USD"
- `cost_model` - Type of cost calculation:
  - `"actual"` - Represents actual cloud billing (Snowflake, BigQuery, Databricks SQL)
  - `"marginal"` - Per-query incremental cost, excludes cluster idle time (Redshift, Databricks all-purpose)
  - `"estimated"` - Rough estimate for unknown platforms
- `warnings` - Array of user-facing warnings about cost limitations
- `storage_cost` - Estimated storage cost (optional, only if data was loaded)
- `phase_costs` - Array of costs broken down by benchmark phase
- `platform_details` - Platform-specific configuration and pricing metadata

**Phase cost fields**:
- `phase_name` - "power_test", "throughput_test", or "data_maintenance"
- `total_cost` - Total cost for all queries in this phase
- `query_count` - Number of queries executed
- `wall_clock_duration_seconds` - Actual wall clock time (optional)
- `concurrent_streams` - Number of concurrent query streams (optional)
- `effective_cost_per_hour` - Computed as `total_cost / (wall_clock_duration_seconds / 3600)` (optional)

**Platform details fields**:
- `pricing_version` - Semantic version of pricing data (e.g., "2025.11")
- `pricing_date` - Last validation date in ISO 8601 format
- `storage_estimate` - Detailed storage cost breakdown (optional)

### Cost Model Types

**actual** - Cost directly tied to query execution:
- Snowflake: Credits consumed
- BigQuery: Data scanned
- Databricks SQL Warehouses: DBUs consumed
- Auto-scaling platforms where concurrent execution is properly reflected

**marginal** - Per-query incremental cost (excludes cluster idle time):
- Redshift: Execution time × cluster capacity
- Databricks All-Purpose Clusters: Execution time × cluster DBUs
- Use for query optimization and cost attribution
- **Warning**: Total marginal cost ≠ cluster TCO for concurrent queries

**estimated** - Rough estimate for unknown or unsupported platforms

### Warnings System

The framework provides user-facing warnings in the `warnings` array:

1. **Cost Model Warnings**:
   - Redshift: Explains marginal cost vs cluster TCO
   - Databricks all-purpose: Clarifies idle time exclusion

2. **Pricing Staleness Warnings**:
   - Triggered when pricing data is >90 days old
   - Includes pricing age and last update date

3. **Storage Cost Warnings**:
   - Explains estimate limitations
   - Notes platform-specific storage considerations

4. **Configuration Warnings**:
   - Missing required configuration fields
   - Incomplete platform metadata

### Timing Context

Phase costs now include timing information for better cost analysis:

```python
# Example: Understanding concurrent execution costs
phase_cost = {
    "phase_name": "throughput_test",
    "total_cost": 12.40,                    # Sum of all 88 queries
    "query_count": 88,                      # 4 streams × 22 queries
    "wall_clock_duration_seconds": 300.0,   # 5 minutes actual runtime
    "concurrent_streams": 4,                # Queries ran concurrently
    "effective_cost_per_hour": 148.80       # $12.40 / (300/3600) = $148.80/hr
}
```

Use `effective_cost_per_hour` for:
- Budgeting and forecasting
- Comparing different scale factors
- Understanding actual spending rate

### Pricing Metadata

All cost estimates include pricing version tracking:

```python
platform_details = {
    "pricing_version": "2025.11",      # YYYY.MM format
    "pricing_date": "2025-11-09",      # Last validation
    # ... other platform details
}
```

- Pricing is validated monthly
- Staleness warning after 90 days
- Target accuracy: ±5% for major regions

### Storage Cost Estimation

When benchmark data is loaded, storage costs are automatically estimated:

```python
storage_estimate = {
    "storage_cost": 0.1534,          # Prorated for duration
    "storage_tb": 4.87,              # Data size in TB
    "price_per_tb_month": 23.00,     # Monthly storage rate
    "duration_hours": 1.0,           # Storage duration
    "note": "Platform-specific notes..."
}
```

**Limitations**:
- Estimates only, not actual charges
- Assumes standard storage tier
- Doesn't include: compression ratios, replication, snapshots
- Minimum duration: 1 hour

## Cost Calculation Models

### Snowflake

**Formula**: `credits_used × price_per_credit`

**Resource Usage Required**:
- `credits_used` (required) - From Snowflake query history

**Configuration Required**:
- `edition` - standard | enterprise | business_critical
- `cloud` - aws | azure | gcp
- `region` - e.g., us-east-1, eu-west-1

**Pricing** (2025 list prices):
- Standard: $2.00/credit (AWS US), $2.40/credit (EU), $2.50/credit (AP)
- Enterprise: $3.00/credit (AWS US), $3.60/credit (EU), $3.75/credit (AP)
- Business Critical: $4.00/credit (AWS US), $4.80/credit (EU), $5.00/credit (AP)

**Example**:
```python
resource_usage = {"credits_used": 0.5}
config = {"edition": "standard", "cloud": "aws", "region": "us-east-1"}
# Cost = 0.5 credits × $2.00 = $1.00
```

### BigQuery

**Formula**: `bytes_billed / (1024^4) × price_per_TB`

**Resource Usage Required**:
- `bytes_billed` (preferred) OR `bytes_processed`

**Configuration Required**:
- `location` - us | eu | asia-northeast1 | etc.

**Pricing** (2025 on-demand):
- US multi-region: $5.00/TB
- EU multi-region: $5.00/TB
- Single regions: $6.00/TB (varies)

**Example**:
```python
resource_usage = {"bytes_billed": 1024**4}  # 1 TB
config = {"location": "us"}
# Cost = 1 TB × $5.00 = $5.00
```

### Redshift

**Formula**: `(execution_time_seconds / 3600) × node_count × price_per_node_hour`

**Resource Usage Required**:
- `execution_time_seconds` (required)

**Configuration Required**:
- `node_type` - dc2.large | ra3.4xlarge | etc.
- `node_count` - Number of nodes in cluster
- `region` - AWS region

**Pricing** (2025 on-demand, varies by region):
- dc2.large: $0.25/node-hour (us-east-1)
- ra3.xlplus: $1.086/node-hour
- ra3.4xlarge: $3.26/node-hour
- ra3.16xlarge: $13.04/node-hour

**Example**:
```python
resource_usage = {"execution_time_seconds": 3600}  # 1 hour
config = {"node_type": "ra3.4xlarge", "node_count": 4, "region": "us-east-1"}
# Cost = 1 hour × 4 nodes × $3.26 = $13.04
```

### Databricks

**Formula**: `(execution_time_seconds / 3600) × cluster_size_dbu_per_hour × price_per_dbu`

**Resource Usage Required**:
- `dbu_consumed` (preferred) OR `execution_time_seconds`

**Configuration Required**:
- `cloud` - aws | azure | gcp
- `tier` - standard | premium | enterprise
- `workload_type` - all_purpose | sql_compute | serverless_sql | jobs_compute
- `cluster_size_dbu_per_hour` - Extracted from warehouse size or provided

**Warehouse Size to DBU Mapping**:
- 2X-Small: 1 DBU/hour
- X-Small: 2 DBU/hour
- Small: 4 DBU/hour
- Medium: 8 DBU/hour
- Large: 16 DBU/hour
- X-Large: 32 DBU/hour
- 2X-Large: 64 DBU/hour
- 3X-Large: 128 DBU/hour
- 4X-Large: 256 DBU/hour

**Pricing** (2025, AWS Premium tier):
- All-purpose compute: $0.55/DBU
- SQL compute: $0.22/DBU
- Serverless SQL: $0.70/DBU
- Jobs compute: $0.15/DBU

**Example**:
```python
resource_usage = {"execution_time_seconds": 1800}  # 30 minutes
config = {
    "cloud": "aws",
    "tier": "premium",
    "workload_type": "sql_compute",
    "cluster_size_dbu_per_hour": 8.0,  # Medium warehouse
}
# Cost = 0.5 hours × 8 DBU/hour × $0.22 = $0.88
```

## Concurrent Query Cost Semantics

### Understanding Cost Calculations for Concurrent Execution

The cost framework calculates **per-query marginal costs**, which sum to the **total cost incurred by all queries**. This is the correct approach for understanding the total spend on a benchmark run.

#### Sequential Execution

For sequential query execution (e.g., power test):

```
Query 1: 10 seconds → Cost A
Query 2: 15 seconds → Cost B
Query 3: 20 seconds → Cost C

Total Time: 45 seconds (wall clock)
Total Cost: A + B + C
```

The wall clock time and total cost align - you pay for the sum of query execution times.

#### Concurrent Execution

For concurrent query execution (e.g., throughput test with multiple streams):

```
Stream 1: Query 1 (10s) → Cost A
Stream 2: Query 2 (15s) → Cost B  } Running concurrently
Stream 3: Query 3 (20s) → Cost C

Total Time: 20 seconds (wall clock - longest query)
Total Cost: A + B + C (sum of all queries)
```

**Key Points**:

1. **Total Cost = Sum of Individual Query Costs**
   - This is accurate for understanding total spend
   - Each query consumes resources independently

2. **Wall Clock Time ≠ Sum of Query Times**
   - Concurrent queries overlap in execution time
   - Wall clock time is shorter than sum of individual times
   - This is the expected behavior for parallel execution

3. **Cost Per Hour Calculation**
   - If you want "cost per hour of wall clock time", divide total cost by wall clock duration
   - This shows the effective rate during concurrent execution periods
   - Example: $10 total cost in 20 seconds wall clock = $1800/hour effective rate

#### Platform-Specific Behavior

**Snowflake**:
- Credits are consumed per query
- Multiple concurrent queries = multiple credits consumed
- Total cost = sum of credits × price per credit
- ✅ Accurate representation

**BigQuery**:
- Charged per TB scanned
- Concurrent queries scan data independently
- Total cost = sum of data scanned × price per TB
- ✅ Accurate representation

**Redshift** (dedicated cluster):
- Cluster runs continuously
- Per-query costs show **marginal cost** (incremental cost of running that query)
- **Total cluster cost** includes idle time not captured here
- ⚠️ See [Redshift Cost Model Clarifications](#redshift-cost-model-clarifications)

**Databricks**:
- DBUs consumed based on execution time
- Concurrent queries consume DBUs in parallel
- Warehouse auto-scales to handle concurrency
- Total cost = sum of DBU consumption
- ✅ Accurate for SQL warehouses
- ⚠️ For all-purpose clusters, see note below

#### Important Caveats

**1. Databricks All-Purpose Clusters**:
- Cluster runs continuously (like Redshift)
- Concurrent queries don't multiply cluster cost
- Our calculation shows **per-query resource attribution**
- For accurate cluster TCO, see dedicated cluster note below

**2. Dedicated Clusters (Redshift, Databricks All-Purpose)**:
- Framework calculates **marginal cost per query**
- Does **not** include cluster idle time
- Total cluster cost = cluster runtime × hourly rate
- Use these metrics for:
  - ✅ Query cost attribution
  - ✅ Workload cost comparison
  - ✅ Query optimization ROI
  - ❌ Total cluster TCO (need to add idle time)

**3. Auto-Scaling Platforms (BigQuery, Snowflake, Databricks SQL)**:
- Cost directly tied to query execution
- No idle cluster time
- Concurrent execution properly reflected in cost
- ✅ Our calculations represent true total cost

### Example: TPC-H Throughput Test

**Scenario**: 4 concurrent streams, each running 22 queries

**Snowflake** (X-Small warehouse, 2 DBU/hour equivalent):
```
Each query: ~0.1 credits
Total queries: 88 (4 streams × 22 queries)
Wall clock: 300 seconds (5 minutes)

Total cost: 88 × 0.1 credits × $2.00 = $17.60
Cost per query: $0.20
Cost per hour: $17.60 / (300s / 3600s) = $211.20/hour
```

**Redshift** (ra3.4xlarge, 4 nodes):
```
Each query: ~15 seconds
Total queries: 88
Wall clock: 45 seconds (queries complete concurrently)

Marginal cost: 88 × (15s / 3600s) × 4 nodes × $3.26 = $4.77
Cluster cost (5 min): 4 nodes × (300s / 3600s) × $3.26 = $1.09
Note: Marginal > Cluster because concurrent queries overlap
```

This discrepancy highlights why we call Redshift costs "marginal" - they represent the incremental cost if queries were run sequentially, not the actual cluster cost during concurrent execution.

### Best Practices

1. **For Query Optimization**:
   - Use per-query costs to identify expensive queries
   - Compare costs before/after optimizations
   - Track cost trends over time

2. **For Budget Planning**:
   - Auto-scaling platforms: Use our total cost
   - Dedicated clusters: Add cluster runtime × hourly rate
   - Consider concurrency patterns in your workload

3. **For Reporting**:
   - Report "Total Compute Cost" for all platforms
   - For dedicated clusters, add note about cluster runtime
   - Show "Cost per Query" and "Effective Cost per Hour" as supplementary metrics

4. **For Comparisons**:
   - Compare like-for-like: same concurrency, same scale
   - Normalize by query count or wall clock time
   - Consider platform auto-scaling behavior

## Redshift Cost Model Clarifications

### What We Calculate

The framework calculates **per-query marginal cost**:
- Cost = execution_time × node_count × hourly_rate
- Represents incremental cost of running that specific query
- Useful for query optimization and cost attribution

### What We Don't Calculate

**Cluster Total Cost of Ownership (TCO)**:
- Full cluster runtime (24/7 for on-demand, or reservation period)
- Cluster idle time between queries
- Cluster startup/shutdown overhead
- Reserved instance discounts

### When to Use This Cost Model

✅ **Good for**:
- Query performance optimization (cost reduction correlates with time reduction)
- Comparing query costs within same cluster configuration
- Understanding which queries are most expensive
- Benchmarking query cost trends

❌ **Not suitable for**:
- Total cluster cost estimation (need cluster uptime)
- Cross-platform cost comparisons (Redshift requires dedicated cluster)
- Budget planning (need to add cluster base cost)

### Example Clarification

**Scenario**: Run TPC-H power test (22 queries) on ra3.4xlarge (4 nodes) in us-east-1

**Our Calculation** (marginal cost):
```
Query 1: 30s → 30/3600 × 4 × $3.26 = $0.11
Query 2: 45s → 45/3600 × 4 × $3.26 = $0.16
...
Total: $5.50 (example sum of all queries)
```

**Actual Cluster Cost** (if cluster runs for 1 hour):
```
Cluster runtime: 1 hour
Total cost: 4 nodes × 1 hour × $3.26 = $13.04
```

**Interpretation**:
- $5.50 = cost attributed to benchmark queries
- $7.54 = cluster idle time (1 hour - total query time)
- $13.04 = total cluster cost for that hour

### Future Enhancement

For dedicated clusters, we could add:
- `cluster_uptime_seconds` parameter
- Full cluster TCO calculation
- Idle vs. active cost breakdown

This would provide complete cost picture for Redshift and Databricks all-purpose clusters.

## Usage

### Automatic Cost Estimation

Cost estimation is automatically added during result export:

```python
from benchbox.core.results.exporter import ResultExporter

exporter = ResultExporter()
exporter.export_result(benchmark_results, output_file)
# Cost estimation added automatically before JSON export
```

### Manual Cost Estimation

You can also manually add cost estimation:

```python
from benchbox.core.cost.integration import add_cost_estimation_to_results

# Automatic config extraction from results.platform_info
updated_results = add_cost_estimation_to_results(benchmark_results)

# Or with explicit config override
platform_config = {
    "edition": "enterprise",
    "cloud": "azure",
    "region": "eu-west-1",
}
updated_results = add_cost_estimation_to_results(
    benchmark_results,
    platform_config=platform_config
)
```

### Configuration Override

Override platform configuration for what-if scenarios:

```python
# Test cost with different warehouse size
snowflake_config = {
    "edition": "standard",
    "cloud": "aws",
    "region": "us-east-1",
    "warehouse_size": "X-LARGE",  # Override extracted size
}

# Test cost with different pricing tier
databricks_config = {
    "cloud": "aws",
    "tier": "enterprise",  # Test enterprise pricing
    "workload_type": "sql_compute",
    "cluster_size_dbu_per_hour": 16.0,
}
```

## Output Schema

Cost information is included in the JSON export (schema v1.1):

```json
{
  "schema_version": "1.1",
  "results": {
    "queries": {
      "details": [
        {
          "id": "Q1",
          "execution_time": 1.5,
          "cost": 0.25,  // Per-query cost in USD
          "resource_usage": {
            "credits_used": 0.125
          }
        }
      ]
    }
  },
  "cost_summary": {
    "total_cost": 10.50,
    "currency": "USD",
    "phase_costs": [
      {
        "phase_name": "power_test",
        "total_cost": 6.30,
        "query_count": 22,
        "currency": "USD"
      },
      {
        "phase_name": "throughput_test",
        "total_cost": 4.20,
        "query_count": 88,
        "currency": "USD"
      }
    ],
    "platform_details": {
      "platform": "snowflake",
      "region": "us-east-1",
      "warehouse_size": "LARGE",
      "edition": "standard"
    }
  }
}
```

## Validation

### Resource Usage Validation

Platform adapters must populate `resource_usage` with required fields:

```python
# Snowflake
resource_usage = {
    "credits_used": 0.5,  # Required
    "bytes_scanned": 1024000,  # Optional
}

# BigQuery
resource_usage = {
    "bytes_billed": 1024**4,  # Required (or bytes_processed)
}

# Redshift
resource_usage = {
    "execution_time_seconds": 3600,  # Required
}

# Databricks
resource_usage = {
    "execution_time_seconds": 1800,  # Required (or dbu_consumed)
}
```

Validation automatically logs warnings for missing required fields.

### Platform Configuration Validation

Configuration is validated before cost calculation:

```python
# Snowflake - requires edition, cloud, region
config = {
    "edition": "standard",
    "cloud": "aws",
    # Missing "region" - validation will warn
}

# BigQuery - requires location
config = {
    # Missing "location" - validation will warn
}

# Redshift - requires node_type, node_count, region
config = {
    "node_type": "ra3.4xlarge",
    "node_count": 4,
    # Missing "region" - validation will warn
}

# Databricks - requires cloud, tier, workload_type, cluster_size_dbu_per_hour
config = {
    "cloud": "aws",
    "tier": "premium",
    # Missing "workload_type" and "cluster_size_dbu_per_hour" - validation will warn
}
```

## Error Handling

The framework gracefully handles errors:

1. **Missing platform**: Skips cost estimation
2. **Missing resource_usage**: Returns `None` for that query
3. **Invalid configuration**: Logs warnings, attempts calculation with available data
4. **Calculation errors**: Logged with full context, doesn't fail benchmark

All errors are logged with platform/phase context for debugging.

## Limitations and Assumptions

### What's Included
- ✅ Compute costs (query execution)
- ✅ Platform-specific pricing models
- ✅ Regional pricing variations

### What's Excluded
- ❌ Storage costs
- ❌ Data transfer/network costs
- ❌ Enterprise/volume discounts
- ❌ Reserved capacity pricing
- ❌ Idle cluster time (for dedicated clusters)

### Assumptions
1. **List Prices**: All pricing based on 2025 public list prices
2. **USD Only**: No currency conversion
3. **On-Demand**: No reserved instance or savings plan discounts
4. **Compute Only**: Storage, network, and other costs not included
5. **Marginal Cost**: Dedicated clusters (Redshift, Databricks all-purpose) show per-query marginal cost, not total cluster TCO

## Pricing Data Maintenance

Pricing tables are in `benchbox/core/cost/pricing.py`:

- Last updated: January 2026
- Source: Public cloud provider pricing pages
- Update frequency: Review quarterly or on major pricing changes

To update pricing:
1. Review cloud provider pricing pages
2. Update pricing dictionaries in `pricing.py`
3. Update "Last updated" comment
4. Run tests to ensure calculations still work
5. Update this documentation if pricing models change

## Testing

The framework has comprehensive test coverage:

```bash
# Run all cost framework tests
pytest tests/unit/core/cost/

# Run specific test suites
pytest tests/unit/core/cost/test_calculator.py      # Cost calculations
pytest tests/unit/core/cost/test_integration.py     # Integration tests
pytest tests/unit/core/cost/test_validation.py      # Resource usage validation
pytest tests/unit/core/cost/test_config_validation.py  # Config validation
```

Test coverage includes:
- Platform-specific cost calculations
- Edge cases (missing data, malformed inputs)
- Validation logic
- Configuration override
- Error handling
- Schema completeness

## Future Enhancements

Potential improvements for future versions:

1. **Currency Support**: Add multi-currency support with conversion rates
2. **Storage Costs**: Model storage costs for data retention
3. **Network Costs**: Include data transfer and egress charges
4. **Discount Models**: Support for enterprise agreements and reserved capacity
5. **Cost Forecasting**: Predict costs for different scale factors
6. **Cost Optimization**: Suggest configuration changes to reduce costs
7. **Cluster TCO**: Full cost modeling for dedicated clusters including idle time

## See Also

- [Cost Models Documentation](./models.py) - Data structures
- [Pricing Tables](./pricing.py) - Platform pricing data
- [Calculator Implementation](./calculator.py) - Cost calculation logic
- [Integration Layer](./integration.py) - Result integration
- [Test Suite](../../tests/unit/core/cost/) - Comprehensive tests
