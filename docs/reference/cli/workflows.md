(cli-usage-patterns)=
# Common Workflows

```{tags} reference, cli
```

This page covers common usage patterns and troubleshooting for BenchBox CLI.

## Local Development and Testing

```bash
benchbox run --platform duckdb --benchmark tpch

benchbox run --benchmark tpcds --scale 0.01 --phases generate \
  --output ./test-data

benchbox profile

benchbox run --help-topic examples
```

## Cloud Platform Benchmarking

```bash
benchbox run --platform databricks --benchmark tpcds --scale 1 \
  --phases power,throughput --output dbfs:/benchmarks/

benchbox run --platform bigquery --benchmark tpch --scale 0.1 \
  --tuning ./bigquery-tuning.yaml

benchbox run --platform snowflake --benchmark tpch --scale 1 \
  --tuning notuning --verbose
```

## Data Pipeline Testing

```bash
benchbox run --benchmark tpcdi --scale 0.1 --phases generate,load \
  --output s3://my-bucket/test-data/

benchbox run --platform redshift --benchmark tpch --scale 1 \
  --phases load --force
```

## Automation and Scripting

```bash
BENCHBOX_NON_INTERACTIVE=true benchbox run \
  --platform duckdb --benchmark tpch --scale 0.01 \
  --quiet --output ./ci-results

benchbox run --platform duckdb --benchmark tpcds \
  --seed 42 --phases power --output ./reproducible-results
```

## Performance Analysis

```bash
benchbox run --platform snowflake --benchmark tpch --scale 1 \
  --tuning notuning --output ./baseline

benchbox run --platform snowflake --benchmark tpch --scale 1 \
  --tuning tuned --output ./optimized

benchbox compare \
  baseline/results/*.json \
  optimized/results/*.json \
  --format html --output tuning-comparison.html

benchbox run --platform databricks --benchmark tpcds \
  --capture-plans --verbose --scale 0.1
```

## CI/CD Integration

```bash
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
benchbox --version

uv tool install benchbox
```

### Platform Dependencies Missing

```bash
benchbox check-deps --platform databricks

uv add benchbox --extra databricks
```

### Local Platform Environment Skips

```bash
benchbox platforms check clickhouse-server trino lakesail-df dask-df

benchbox platforms status lakesail-df
benchbox platforms status dask-df
```

`benchbox platforms check` reports local service ports and LakeSail Spark Connect gaps as
environment readiness issues. These checks are bounded probes only; they do not start servers, initialize Ray/Dask,
or create/drop benchmark databases.

### Authentication Errors

```bash
benchbox platforms status databricks

echo $DATABRICKS_TOKEN

benchbox platforms check
```

### Permission Denied Errors

```bash
uv tool install benchbox

ls -la /path/to/output/directory
```

### Memory or Disk Space Issues

```bash
benchbox profile

benchbox run --platform duckdb --benchmark tpch --scale 0.001

benchbox run --platform duckdb --benchmark tpch --compression zstd:9
```

### Configuration Validation Failures

```bash
benchbox validate

cat ~/.benchbox/config.yaml

benchbox run --dry-run ./debug --platform duckdb --benchmark tpch
```

## Getting Help

### Built-in Help

```bash
benchbox --help

benchbox run --help
benchbox run --help-topic all
benchbox run --help-topic examples
benchbox platforms --help

benchbox platforms status clickhouse
```

### Verbose Output

```bash
benchbox run --verbose --platform duckdb --benchmark tpch

benchbox run -vv --platform duckdb --benchmark tpch
```

### Dry Run for Debugging

```bash
benchbox run --dry-run ./debug --platform databricks --benchmark tpch
```

For additional support, see the [GitHub Issues](https://github.com/joeharris76/benchbox/issues) page.
