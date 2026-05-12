# Unified Runner Example - README

**Run benchmark on allsupported platforms using `unified_runner.py`**

This guide shows how to run each of the 12 supported benchmarks using the `unified_runner`. All examples use the same tool with different `--benchmark` flags.

The `unified_runner.py` script provides a fully worked **single-file** example of using the core BenchBox modules. The behavior is very similar to the CLI for comparability.

## Quick Start

```bash
# Navigate to examples directory
cd examples

# Run any benchmark (replace 'tpch' with any benchmark name below)
python unified_runner.py --platform duckdb --benchmark tpch --scale 0.01 --phases power
```

---

## All Supported Benchmarks

### 1. TPC-H (Standard OLAP)
**Best for:** General analytical query performance, vendor comparison

```bash
# Basic power test
python unified_runner.py --platform duckdb --benchmark tpch --scale 0.1 --phases power

# With tuning
python unified_runner.py --platform duckdb --benchmark tpch --scale 1.0 --phases power --tuning tuned

# Specific queries only
python unified_runner.py --platform duckdb --benchmark tpch --scale 0.1 --phases power --queries 1,6,12

# Dry-run (preview without execution)
python unified_runner.py --platform duckdb --benchmark tpch --scale 1.0 --phases power --dry-run ./preview
```

**Scale Factor Guide:**
- `0.01` = ~10MB (< 1 min, testing)
- `0.1` = ~100MB (2-5 min, development)
- `1.0` = ~1GB (10-15 min, standard)
- `10.0` = ~10GB (30-60 min, large)

---

### 2. TPC-DS (Complex Analytics)
**Best for:** Complex analytical workloads, BI reporting

```bash
# Power test
python unified_runner.py --platform duckdb --benchmark tpcds --scale 0.1 --phases power

# With tuning
python unified_runner.py --platform duckdb --benchmark tpcds --scale 1.0 --phases power --tuning tuned
```

**Scale Factor Guide:**
- `0.01` = ~5MB (< 1 min)
- `0.1` = ~50MB (3-10 min)
- `1.0` = ~500MB (20-40 min)
- `10.0` = ~5GB (1-3 hours)

---

### 3. TPC-DI (Data Integration)
**Best for:** ETL performance, data warehouse loading

```bash
# Standard test (data loading + transformation)
python unified_runner.py --platform duckdb --benchmark tpcdi --scale 0.01 --phases generate,load

# Full workflow
python unified_runner.py --platform duckdb --benchmark tpcdi --scale 1.0 --phases generate,load
```

**Note:** TPC-DI focuses on data loading rather than query execution

**Scale Factor Guide:**
- `0.01` = Tiny (< 1 min)
- `1.0` = Small (5-10 min)
- `10.0` = Medium (30-60 min)

---

### 4. SSB (Star Schema Benchmark)
**Best for:** Star schema queries, dimensional modeling

```bash
# Power test (13 queries)
python unified_runner.py --platform duckdb --benchmark ssb --scale 0.1 --phases power

# With tuning
python unified_runner.py --platform duckdb --benchmark ssb --scale 1.0 --phases power --tuning tuned
```

**Scale Factor Guide:**
- `0.01` = ~5MB (< 1 min)
- `1.0` = ~500MB (5-10 min)
- `10.0` = ~5GB (30-60 min)

---

### 5. ClickBench (Web Analytics)
**Best for:** Real-time analytics, web/log data

```bash
# Power test (43 queries)
python unified_runner.py --platform duckdb --benchmark clickbench --scale 0.01 --phases power

# Larger dataset
python unified_runner.py --platform duckdb --benchmark clickbench --scale 0.1 --phases power
```

**Scale Factor Guide:**
- `0.01` = ~1M rows (~100MB, < 1 min)
- `0.1` = ~10M rows (~1GB, 3-5 min)
- `1.0` = ~100M rows (~10GB, 15-30 min)

---

### 6. AMPLab Big Data Benchmark
**Best for:** Big data query patterns, Hadoop/Spark comparison

```bash
# Power test (3 query types: scan, aggregation, join)
python unified_runner.py --platform duckdb --benchmark amplab --scale 0.1 --phases power

# Larger scale
python unified_runner.py --platform duckdb --benchmark amplab --scale 1.0 --phases power
```

**Scale Factor Guide:**
- `0.01` = Tiny (< 1 min)
- `1.0` = Small (2-5 min)
- `10.0` = Medium (10-20 min)

---

### 7. H2O.ai Database Benchmark
**Best for:** Data science workloads, GroupBy operations

```bash
# Power test (GroupBy-heavy queries)
python unified_runner.py --platform duckdb --benchmark h2odb --scale 0.1 --phases power
```

**Scale Factor Guide:**
- `0.01` = ~100K rows (< 1 min)
- `1.0` = ~10M rows (2-5 min)
- `10.0` = ~100M rows (10-30 min)

---

### 8. Join Order Benchmark
**Best for:** Query optimizer testing, join algorithm evaluation

```bash
# Power test (complex multi-way joins)
python unified_runner.py --platform duckdb --benchmark joinorder --scale 1 --phases power
```

**Scale Factor Guide:**
- `1.0` is the only supported public `joinorder` scale.
- First use downloads and verifies the canonical IMDb 2013 JOB Parquet package.
- Use the internal `joinorder_synthetic` benchmark only for synthetic loader or schema smoke tests.

---

### 9. Read Primitives (Basic OLAP)
**Best for:** Quick smoke tests, basic functionality validation

```bash
# Power test (simple analytical queries)
python unified_runner.py --platform duckdb --benchmark read_primitives --scale 0.01 --phases power

# CI/CD quick test
python unified_runner.py --platform duckdb --benchmark read_primitives --scale 0.01 --phases power --queries 1,2,3
```

**Scale Factor Guide:**
- `0.01` = ~10MB (< 10 seconds, CI/CD)
- `0.1` = ~100MB (< 1 min, smoke testing)
- `1.0` = ~1GB (2-5 min, baseline)

---

### 10. Write Primitives (Write Operations)
**Best for:** Write performance testing, MERGE/UPSERT testing, transaction validation

```bash
# Test write operations
python unified_runner.py --platform duckdb --benchmark write_primitives --scale 0.01 --phases generate,load

# Larger write operation tests
python unified_runner.py --platform duckdb --benchmark write_primitives --scale 1.0 --phases generate,load
```

**Scale Factor Guide:**
- `0.01` = ~10MB TPC-H data (< 1 min)
- `1.0` = ~1GB TPC-H data (2-5 min)
- `10.0` = ~10GB TPC-H data (10-30 min)

---

### 11. TPC-H Havoc (Optimizer Stress Test)
**Best for:** Query optimizer validation, edge case testing

```bash
# Power test (modified TPC-H queries designed to stress optimizers)
python unified_runner.py --platform duckdb --benchmark tpchavoc --scale 0.1 --phases power
```

**Note:** Some queries may intentionally fail or perform poorly to test optimizer robustness

**Scale Factor Guide:**
- `0.01` = ~10MB (< 1 min)
- `0.1` = ~100MB (3-10 min)
- `1.0` = ~1GB (15-30 min)

---

## Platform Options

Use `--platform` to run on different databases:

```bash
# Local databases (no credentials required)
--platform duckdb       # In-memory or persistent
--platform sqlite       # SQLite database

# Self-hosted
--platform clickhouse   # ClickHouse server

# Cloud platforms (requires credentials)
--platform databricks   # Databricks SQL Warehouse
--platform bigquery     # Google BigQuery
--platform snowflake    # Snowflake warehouse
--platform redshift     # Amazon Redshift
```

### Cloud Platform Examples

```bash
# Databricks (requires DATABRICKS_TOKEN and DATABRICKS_HOST)
python unified_runner.py \
  --platform databricks \
  --benchmark tpch \
  --scale 1.0 \
  --phases power

# BigQuery (requires GOOGLE_APPLICATION_CREDENTIALS or BIGQUERY_PROJECT)
python unified_runner.py \
  --platform bigquery \
  --benchmark tpch \
  --scale 0.1 \
  --phases power \
  --dry-run ./preview  # Preview before spending credits

# Snowflake (requires Snowflake credentials)
python unified_runner.py \
  --platform snowflake \
  --benchmark tpch \
  --scale 1.0 \
  --phases power
```

---

## Test Execution Types

Use `--phases` to control what executes:

```bash
# Power test (sequential query execution)
--phases power

# Throughput test (concurrent streams)
--phases throughput --streams 4

# Maintenance test (data modifications)
--phases maintenance

# Multiple phases
--phases warmup,power,throughput

# Data generation only
--phases generate

# Load data only (no queries)
--phases load

# Full workflow
--phases generate,load,power
```

---

## Common Options

### Query Selection
```bash
# Run specific queries
--queries 1,6,12,14

# Run query range
--queries 1-10
```

### Tuning
```bash
# Apply optimizations (uses tunings/{platform}/{benchmark}_tuned.yaml)
--tuning tuned

# Baseline (no optimizations)
--tuning notuning

# Custom tuning file
--tuning /path/to/custom_tuning.yaml
```

### Output & Export
```bash
# Preview without execution
--dry-run ./preview_output

# Export results in multiple formats
--formats json,csv,html

# Custom output directory
--output-dir ./my_results

# Quiet mode (minimal console output)
--quiet

# Verbose mode (detailed logging)
--verbose

# Very verbose
-vv
```

### Data Management
```bash
# Force data regeneration
--force

# Compress generated data
--compress

# Specify data location
--output /path/to/data
```

---

## Complete Examples

### Development Workflow
```bash
# 1. Quick smoke test
python unified_runner.py --platform duckdb --benchmark primitives --scale 0.01 --phases power

# 2. Test specific benchmark
python unified_runner.py --platform duckdb --benchmark tpch --scale 0.1 --phases power

# 3. Preview cloud run
python unified_runner.py --platform databricks --benchmark tpch --scale 1.0 --dry-run ./preview

# 4. Execute on cloud
python unified_runner.py --platform databricks --benchmark tpch --scale 1.0 --phases power
```

### Performance Testing
```bash
# 1. Baseline (no tuning)
python unified_runner.py --platform duckdb --benchmark tpch --scale 1.0 --phases power \
  --tuning notuning --output-dir ./results/baseline

# 2. Optimized (with tuning)
python unified_runner.py --platform duckdb --benchmark tpch --scale 1.0 --phases power \
  --tuning tuned --output-dir ./results/tuned

# 3. Compare results (see result_analysis.py example)
```

### CI/CD Integration
```bash
# Fast validation test (< 30 seconds)
python unified_runner.py --platform duckdb --benchmark primitives --scale 0.01 \
  --phases power --quiet --formats json --output-dir ./ci_results
```

### Multi-Platform Comparison
```bash
# Run same benchmark on 3 platforms
for platform in duckdb clickhouse databricks; do
  python unified_runner.py --platform $platform --benchmark tpch --scale 1.0 \
    --phases power --output-dir ./comparison/$platform
done
```

---

## Getting Help

```bash
# Show all options
python unified_runner.py --help

# List available platforms
python unified_runner.py --list-platforms

# List available benchmarks
python unified_runner.py --list-benchmarks

# Platform-specific help
python unified_runner.py --platform databricks --help
```

---

## Next Steps

- **New users:** Start with [getting_started/](getting_started/) examples
- **Learn patterns:** See [PATTERNS.md](PATTERNS.md) for common workflows
- **Find examples:** Browse [INDEX.md](INDEX.md) by goal/platform/benchmark
- **Advanced usage:** See [UNIFIED_RUNNER_GUIDE.md](UNIFIED_RUNNER_GUIDE.md) (comprehensive guide)
- **Feature examples:** Explore [features/](features/) for specific capabilities

---

## Troubleshooting

**Import errors:**
```bash
uv add benchbox
# Or with platform extras
uv add benchbox --extra databricks
```

**Platform not available:**
```bash
# Check required dependencies
python unified_runner.py --list-platforms

# Install platform extras
pip install "benchbox[cloud]"  # All cloud platforms
pip install "benchbox[databricks]"  # Single platform
```

**Credentials missing:**
```bash
# Set required environment variables (platform-specific)
export DATABRICKS_TOKEN="your-token"
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
```

**Performance issues:**
- Start with small scale factors (0.01 or 0.1)
- Use `--dry-run` to preview before execution
- Enable tuning with `--tuning tuned`
- Check system resources (RAM, CPU)

---

**Remember:** `unified_runner.py` supports ALL benchmarks and ALL platforms. You don't need separate scripts for each combination!
