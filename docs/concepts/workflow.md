<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Benchmarking Workflows

```{tags} concept, intermediate
```

Common patterns and workflows for running benchmarks with BenchBox.

## Quick Start Workflow

The simplest path from installation to results:

```bash
# 1. Install
uv pip install benchbox

# 2. Run benchmark
benchbox run --benchmark tpch --platform duckdb --scale 0.1

# 3. View results
cat benchmark_runs/tpch_0.1_duckdb_*/results.json
```

**What happens**:
1. BenchBox generates TPC-H data at scale factor 0.1 (~100MB)
2. Loads data into DuckDB (an in-memory database)
3. Executes all 22 TPC-H queries
4. Saves timing results to `benchmark_runs/` directory

**Time to complete**: ~2-3 minutes

See: [Getting Started Guide](../usage/getting-started.md)

## Development Workflow

Typical workflow for developers testing query changes or experimenting:

```bash
# 1. Generate data once
benchbox datagen --benchmark tpch --scale 0.01 --output ./data/tpch_0.01

# 2. Run specific queries during development
benchbox run --benchmark tpch --platform duckdb --scale 0.01 \
  --data-dir ./data/tpch_0.01 \
  --query-subset q1,q3,q7 \
  --verbose

# 3. Run full suite when ready
benchbox run --benchmark tpch --platform duckdb --scale 0.01 \
  --data-dir ./data/tpch_0.01
```

**Benefits**:
- Data generation happens once (can be slow for large scale factors)
- Iterate quickly on specific queries
- Full validation before committing changes

**Use Cases**:
- Testing query modifications
- Debugging platform adapter issues
- Developing custom benchmarks

## Multi-Platform Comparison Workflow

Compare performance across different database platforms:

```bash
# Generate data once
benchbox datagen --benchmark tpch --scale 1 --output ./data/tpch_1

# Run on multiple platforms
for platform in duckdb clickhouse; do
  benchbox run --benchmark tpch --platform $platform --scale 1 \
    --data-dir ./data/tpch_1 \
    --output benchmark_runs/tpch_1_${platform}
done

# Compare results
benchbox compare \
  benchmark_runs/tpch_1_duckdb/results.json \
  benchmark_runs/tpch_1_clickhouse/results.json
```

**Output**:
- Side-by-side query timing comparison
- Geometric mean calculations
- Performance regression detection

See: [Platform Comparison Matrix](../platforms/comparison-matrix.md)

## Cloud Platform Workflow

Running benchmarks on cloud platforms (BigQuery, Snowflake, Databricks):

```bash
# 1. Check cloud credentials
export DATABRICKS_TOKEN="dapi..."
export DATABRICKS_HOST="https://....cloud.databricks.com"

# 2. Preview queries without execution (to avoid costs)
benchbox run --benchmark tpcds --platform databricks --scale 1 \
  --dry-run ./preview

# Review generated queries in ./preview/queries/

# 3. Run benchmark (queries will execute and incur costs)
benchbox run --benchmark tpcds --platform databricks --scale 1 \
  --platform-option uc_catalog=hive_metastore \
  --platform-option uc_schema=benchbox_test

# 4. Results saved with cloud execution metadata
cat benchmark_runs/tpcds_1_databricks_*/results.json
```

**External Table Mode**:

Skip native table materialization (COPY/CTAS) and query directly over staged Parquet files:

```bash
# External mode: register views/external tables over staged data
benchbox run --benchmark tpch --platform snowflake --scale 1 \
  --table-mode external \
  --platform-option staging_root=s3://my-bucket/benchbox/
```

This is useful for quick file-based comparisons across engines without paying for
data loading. Not compatible with `--tuning tuned`. See the
[Platform Comparison Guide](../guides/platform-comparison.md) for supported platforms.

**Cost Control**:
- Use `--dry-run` to preview queries before execution
- Start with small scale factors (0.1, 1)
- Set platform-specific cost limits (BigQuery `maximum_bytes_billed`)
- Use auto-suspend/auto-resume for warehouse platforms

See: [Platform Selection Guide](../platforms/platform-selection-guide.md)

## Dry Run Workflow

Preview benchmark execution without running queries:

```bash
# Generate queries and configuration
benchbox run --benchmark tpcds --platform bigquery --scale 10 \
  --dry-run ./preview

# Inspect outputs
tree ./preview
# preview/
# ├── queries/
# │   ├── q1.sql
# │   ├── q2.sql
# │   └── ...
# ├── schema/
# │   ├── store_sales.ddl
# │   └── ...
# └── summary.json

# Review summary
cat ./preview/summary.json
```

**Use Cases**:
- Query validation before cloud execution
- Cost estimation (query complexity, data scanned)
- Debugging query generation logic
- Sharing queries with team members

See: [Dry Run Guide](../usage/dry-run.md)

## CI/CD Workflow

Automated benchmarking in continuous integration:

```yaml
# .github/workflows/benchmarks.yml
name: Benchmark Tests

on: [pull_request]

jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Install BenchBox
        run: uv pip install benchbox

      - name: Run regression test
        run: |
          benchbox run --benchmark tpch --platform duckdb --scale 0.01 \
            --output results/

      - name: Compare against baseline
        run: |
          benchbox compare \
            baseline/tpch_0.01_duckdb.json \
            results/results.json \
            --fail-on-regression 10%
```

**Benefits**:
- Catch performance regressions before merge
- Validate query compatibility across platforms
- Track performance trends over time

See: [Testing Guide](../development/testing.md)

## Compliance Workflow (Official TPC Benchmarks)

Running benchmarks according to TPC specifications for official results:

```bash
# 1. Power Test (single query stream)
benchbox run-official tpch --platform snowflake --scale 100 \
  --test-type power \
  --seed 42 \
  --output results/power/

# 2. Throughput Test (concurrent streams)
benchbox run-official tpch --platform snowflake --scale 100 \
  --test-type throughput \
  --streams 4 \
  --seed 42 \
  --output results/throughput/

# 3. Calculate composite metric
benchbox calculate-qphh \
  --power-results results/power/results.json \
  --throughput-results results/throughput/results.json
```

**Requirements**:
- Specific scale factors (1, 10, 30, 100, 300, 1000, 3000, 10000, 30000, 100000)
- Random seed management
- Refresh function execution
- Full validation

See:
- [TPC-H Official Benchmark Guide](../guides/tpc/tpc-h-official-guide.md)
- [TPC-DS Official Benchmark Guide](../guides/tpc/tpc-ds-official-guide.md)
- [TPC Validation Guide](../guides/tpc/tpc-validation-guide.md)

## Performance Tuning Workflow

Optimizing query performance with platform-specific tunings:

```bash
# 1. Baseline run (no tunings)
benchbox run --benchmark tpcds --platform clickhouse --scale 10 \
  --output baseline/

# 2. Apply tunings (partitioning, sorting, indexes)
benchbox run --benchmark tpcds --platform clickhouse --scale 10 \
  --tuning tunings/clickhouse_tpcds.yaml \
  --output tuned/

# 3. Compare results
benchbox compare baseline/results.json tuned/results.json
```

**Example Tuning Config** (`tunings/clickhouse_tpcds.yaml`):
```yaml
tables:
  store_sales:
    partition_by: ss_sold_date_sk
    order_by: [ss_customer_sk, ss_item_sk]
    primary_key: [ss_item_sk, ss_ticket_number]

  customer:
    order_by: c_customer_sk
    primary_key: c_customer_sk
```

See: [Performance Guide](../advanced/performance.md)

## Data Generation Workflow

Generating benchmark data separately from execution:

```bash
# Generate multiple scale factors
for sf in 0.01 0.1 1 10; do
  benchbox datagen --benchmark tpch --scale $sf \
    --output ./data/tpch_${sf}
done

# Compress for storage
tar -czf tpch_data.tar.gz ./data/

# Later: use pre-generated data
benchbox run --benchmark tpch --platform duckdb --scale 1 \
  --data-dir ./data/tpch_1
```

**Benefits**:
- Generate data once, use many times
- Share data across team members
- Version control data generation parameters
- Faster iteration on query/platform testing

See: [Data Generation Guide](../usage/data-generation.md)

## Validation Workflow

Verifying benchmark results for correctness:

```bash
# Run with validation enabled
benchbox run --benchmark tpch --platform duckdb --scale 0.1 \
  --validate-results \
  --validation-mode strict

# Validation checks:
# - Row count verification
# - Result checksum validation
# - Data type compliance
# - Constraint satisfaction
```

**Validation Modes**:
- `none`: No validation (fastest)
- `basic`: Row count checks only
- `strict`: Full result validation (slowest, most thorough)

See: [TPC Validation Guide](../guides/tpc/tpc-validation-guide.md)

## Monitoring Workflow

Tracking benchmark performance over time:

```bash
# Run benchmark daily
benchbox run --benchmark tpch --platform duckdb --scale 1 \
  --output benchmark_runs/$(date +%Y%m%d)/

# Aggregate results
benchbox aggregate \
  --input-dir benchmark_runs/ \
  --output-file performance_trends.csv

# Visualize trends
benchbox visualize benchmark_runs/results/*.json
```

**Metrics Tracked**:
- Query execution times (p50, p95, p99)
- Geometric mean
- Total execution time
- Data loading time
- Memory usage
- Failure rates

See: [Performance Monitoring](../advanced/performance.md)

## Debugging Workflow

Troubleshooting benchmark issues:

```bash
# 1. Enable verbose logging
benchbox run --benchmark tpch --platform duckdb --scale 0.01 \
  --verbose \
  --log-file debug.log

# 2. Run single query with maximum detail
benchbox run --benchmark tpch --platform duckdb --scale 0.01 \
  --query-subset q1 \
  --verbose \
  --explain  # Shows query plan

# 3. Inspect database state
benchbox shell --platform duckdb --database benchmark.duckdb
# Interactive SQL shell opens
```

**Common Issues**:
- Data generation failures → Check disk space, permissions
- Query failures → Check SQL dialect compatibility
- Performance issues → Check scale factor vs. available memory
- Connection errors → Verify credentials, network access

See: [Troubleshooting Guide](../usage/troubleshooting.md)

## Custom Benchmark Workflow

Creating and running a custom benchmark:

```python
# 1. Define benchmark class
from benchbox.base import BaseBenchmark

class MyBenchmark(BaseBenchmark):
    def generate_data(self):
        # Custom data generation logic
        ...

    def get_queries(self):
        return {
            "q1": "SELECT ...",
            "q2": "SELECT ...",
        }

    def get_query(self, query_id, params=None):
        queries = self.get_queries()
        return queries[query_id]

# 2. Run benchmark
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = MyBenchmark(scale_factor=0.1)
adapter = DuckDBAdapter()
results = benchmark.run_with_platform(adapter)

print(f"Completed in {results.duration_seconds:.2f}s")
```

See: [Custom Benchmarks Guide](../advanced/custom-benchmarks.md)

## Best Practices

### General Recommendations

1. **Start Small**: Begin with a scale factor of 0.01 or 0.1 for testing
2. **Use Dry Run**: Preview queries before expensive cloud execution
3. **Generate Once**: Reuse generated data across multiple runs
4. **Version Control**: Track benchmark configurations and results
5. **Monitor Costs**: Set budget alerts for cloud platforms

### Performance Optimization

1. **Match Platform to Workload**: Use DuckDB for development, cloud platforms for production
2. **Optimize Data Loading**: Use platform-specific bulk loading (COPY, external tables)
3. **Apply Tunings**: Use partitioning, clustering, indexes for large datasets
4. **Measure Baselines**: Establish baseline performance before optimizations

### Compliance and Validation

1. **Follow TPC Specs**: Use official runners for compliance testing
2. **Validate Results**: Enable validation for correctness verification
3. **Document Configuration**: Record all benchmark parameters and system info
4. **Reproduce Results**: Use fixed seeds and version-locked dependencies

## Related Documentation

- [Architecture](architecture.md) - System design and components
- [Data Model](data-model.md) - Result schema and structures
- [Getting Started](../usage/getting-started.md) - First benchmark in 5 minutes
- [CLI Quick Start](../usage/cli-quick-start.md) - Command-line reference
- [Examples](../usage/examples.md) - Code snippets and automation patterns
