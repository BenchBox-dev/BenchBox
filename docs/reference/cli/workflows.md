(cli-usage-patterns)=
# Common Workflows

```{tags} reference, cli
```

This page covers common usage patterns and troubleshooting for BenchBox CLI.

## Local Development and Testing

```bash
# TPC-H test on DuckDB
benchbox run --platform duckdb --benchmark tpch

# Generate test data for development
benchbox run --benchmark tpcds --scale 0.01 --phases generate \
  --output ./test-data

# System analysis for optimization
benchbox profile

# See all available CLI examples
benchbox run --help-topic examples
```

## Cloud Platform Benchmarking

```bash
# Full TPC-DS benchmark on Databricks
benchbox run --platform databricks --benchmark tpcds --scale 1 \
  --phases power,throughput --output dbfs:/benchmarks/

# BigQuery with custom tuning
benchbox run --platform bigquery --benchmark tpch --scale 0.1 \
  --tuning ./bigquery-tuning.yaml

# Snowflake baseline comparison
benchbox run --platform snowflake --benchmark tpch --scale 1 \
  --tuning notuning --verbose
```

## Data Pipeline Testing

```bash
# Generate data for ETL testing
benchbox run --benchmark tpcdi --scale 0.1 --phases generate,load \
  --output s3://my-bucket/test-data/

# Load-only mode for existing data
benchbox run --platform redshift --benchmark tpch --scale 1 \
  --phases load --force
```

## Automation and Scripting

```bash
# Non-interactive mode for CI/CD
BENCHBOX_NON_INTERACTIVE=true benchbox run \
  --platform duckdb --benchmark tpch --scale 0.01 \
  --quiet --output ./ci-results

# Reproducible benchmark runs
benchbox run --platform duckdb --benchmark tpcds \
  --seed 42 --phases power --output ./reproducible-results
```

## Performance Analysis

```bash
# Compare tuning vs baseline
benchbox run --platform snowflake --benchmark tpch --scale 1 \
  --tuning notuning --output ./baseline

benchbox run --platform snowflake --benchmark tpch --scale 1 \
  --tuning tuned --output ./optimized

# Compare the results
benchbox compare \
  baseline/results/*.json \
  optimized/results/*.json \
  --format html --output tuning-comparison.html

# Detailed query analysis with plan capture
benchbox run --platform databricks --benchmark tpcds \
  --capture-plans --verbose --scale 0.1
```

## CI/CD Integration

```bash
# Run benchmark and fail on regression
benchbox run --platform duckdb --benchmark tpch --scale 0.1 \
  --output ./current-results

benchbox compare \
  ./baseline-results/results/*.json \
  ./current-results/results/*.json \
  --fail-on-regression 10%
```

---

(cli-troubleshooting)=
# Troubleshooting

## Common Issues and Solutions

### Command Not Found

```bash
# Verify installation
benchbox --version

# If not found, check your PATH or reinstall for CLI use
uv tool install benchbox
```

### Platform Dependencies Missing

```bash
# Check what's missing
benchbox check-deps --platform databricks

# Install missing dependencies
uv add benchbox --extra databricks
```

### Local Platform Environment Skips

```bash
# Check package availability plus local provisioning readiness
benchbox platforms check clickhouse-server trino lakesail-df modin-df

# Inspect one platform, including endpoint/backend readiness notes
benchbox platforms status lakesail-df
benchbox platforms status modin-df
```

`benchbox platforms check` reports local service ports, LakeSail Spark Connect, and Modin backend gaps as
environment readiness issues. These checks are bounded probes only; they do not start servers, initialize Ray/Dask,
or create/drop benchmark databases.

### Authentication Errors

```bash
# Check platform status
benchbox platforms status databricks

# Verify environment variables
echo $DATABRICKS_TOKEN

# Test platform configuration
benchbox platforms check
```

### Permission Denied Errors

```bash
# Use a user-level CLI installation
uv tool install benchbox

# Check output directory permissions
ls -la /path/to/output/directory
```

### Memory or Disk Space Issues

```bash
# Profile system resources
benchbox profile

# Use smaller scale factor
benchbox run --platform duckdb --benchmark tpch --scale 0.001

# Enable high compression
benchbox run --platform duckdb --benchmark tpch --compression zstd:9
```

### Configuration Validation Failures

```bash
# Validate configuration
benchbox validate

# Check configuration file syntax
cat ~/.benchbox/config.yaml

# Use dry-run to preview settings
benchbox run --dry-run ./debug --platform duckdb --benchmark tpch
```

## Getting Help

### Built-in Help

```bash
# General help
benchbox --help

# Command-specific help
benchbox run --help              # Common options
benchbox run --help-topic all    # All options including advanced
benchbox run --help-topic examples  # Categorized usage examples
benchbox platforms --help

# Platform status and details
benchbox platforms status clickhouse
```

### Verbose Output

```bash
# Enable detailed logging
benchbox run --verbose --platform duckdb --benchmark tpch

# Very verbose for debugging
benchbox run -vv --platform duckdb --benchmark tpch
```

### Dry Run for Debugging

```bash
# Preview configuration without execution
benchbox run --dry-run ./debug --platform databricks --benchmark tpch
```

For additional support, see the [GitHub Issues](https://github.com/joeharris76/benchbox/issues) page.
