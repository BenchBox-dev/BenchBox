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

The commands, in order, run a TPC-H test on DuckDB, generate test data for development, analyze the system for optimization, and show all available CLI examples.

## Cloud Platform Benchmarking

```bash
benchbox run --platform databricks --benchmark tpcds --scale 1 \
  --phases power,throughput --output dbfs:/benchmarks/

benchbox run --platform bigquery --benchmark tpch --scale 0.1 \
  --tuning ./bigquery-tuning.yaml

benchbox run --platform snowflake --benchmark tpch --scale 1 \
  --tuning notuning --verbose
```

The commands run a full TPC-DS benchmark on Databricks, run BigQuery with custom tuning, and run a Snowflake baseline for comparison.

## Data Pipeline Testing

```bash
benchbox run --benchmark tpcdi --scale 0.1 --phases generate,load \
  --output s3://my-bucket/test-data/

benchbox run --platform redshift --benchmark tpch --scale 1 \
  --phases load --force
```

The first command generates data for ETL testing. The second runs in load-only mode for data that already exists.

## Automation and Scripting

```bash
BENCHBOX_NON_INTERACTIVE=true benchbox run \
  --platform duckdb --benchmark tpch --scale 0.01 \
  --quiet --output ./ci-results

benchbox run --platform duckdb --benchmark tpcds \
  --seed 42 --phases power --output ./reproducible-results
```

The first command runs in non-interactive mode for CI/CD. The second gives reproducible benchmark runs.

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

The first two commands and the `compare` command compare tuning against a baseline. The last command gives detailed query analysis with plan capture.

## CI/CD Integration

```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.1 \
  --output ./current-results

benchbox compare \
  ./baseline-results/results/*.json \
  ./current-results/results/*.json \
  --fail-on-regression 10%
```

This runs the benchmark and fails on a regression of more than 10%.

---

(cli-troubleshooting)=
# Troubleshooting

## Common Issues and Solutions

### Command Not Found

```bash
benchbox --version

uv tool install benchbox
```

The first command verifies the installation. If the command is not found, check your PATH or reinstall for CLI use.

### Platform Dependencies Missing

```bash
benchbox check-deps --platform databricks

uv add benchbox --extra databricks
```

The first command checks what is missing and the second installs the missing dependencies.

### Local Platform Environment Skips

```bash
benchbox platforms check clickhouse-server trino lakesail-df dask-df

benchbox platforms status lakesail-df
benchbox platforms status dask-df
```

The first command checks package availability and local provisioning readiness. The other commands inspect one platform, including endpoint and backend readiness notes.

`benchbox platforms check` reports local service ports and LakeSail Spark Connect gaps as
environment readiness issues. These checks are bounded probes only; they do not start servers, initialize Ray/Dask,
or create/drop benchmark databases.

### Authentication Errors

```bash
benchbox platforms status databricks

echo $DATABRICKS_TOKEN

benchbox platforms check
```

The commands check the platform status, verify the environment variables, and test the platform configuration.

### Permission Denied Errors

```bash
uv tool install benchbox

ls -la /path/to/output/directory
```

The first command uses a user-level CLI installation. The second checks the output directory permissions.

### Memory or Disk Space Issues

```bash
benchbox profile

benchbox run --platform duckdb --benchmark tpch --scale 0.001

benchbox run --platform duckdb --benchmark tpch --compression zstd:9
```

The commands profile system resources, use a smaller scale factor, and enable high compression.

### Configuration Validation Failures

```bash
benchbox validate

cat ~/.benchbox/config.yaml

benchbox run --dry-run ./debug --platform duckdb --benchmark tpch
```

The commands validate the configuration, check the configuration file syntax, and use a dry run to preview settings.

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

The commands give general help, then command-specific help. `--help` shows the common options, `--help-topic all` shows all options including advanced ones, and `--help-topic examples` shows categorized usage examples. The last command shows platform status and details.

### Verbose Output

```bash
benchbox run --verbose --platform duckdb --benchmark tpch

benchbox run -vv --platform duckdb --benchmark tpch
```

The first command enables detailed logging. The second is very verbose, for debugging.

### Dry Run for Debugging

```bash
benchbox run --dry-run ./debug --platform databricks --benchmark tpch
```

For additional support, see the [GitHub Issues](https://github.com/joeharris76/benchbox/issues) page.
