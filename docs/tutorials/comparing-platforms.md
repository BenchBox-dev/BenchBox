# Comparing Platforms

```{tags} intermediate, tutorial, sql-platform
```

Run the same benchmark on multiple databases to compare performance.

## Overview

BenchBox makes it easy to compare platforms because:
- Same benchmark runs identically on all platforms
- Same data (shared generation)
- Same validation criteria

### Shared Parquet Data

BenchBox generates benchmark data as Parquet files once, then every platform reads from the same dataset. This gives you an apples-to-apples comparison: differences in results reflect engine performance, not data differences. When you run the same benchmark at the same scale factor across DuckDB, DataFusion, Polars, and others, they all query identical Parquet files from a shared data directory.

### Choosing Table Mode

Use `--table-mode` to control how data is registered before query execution:

```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.1 --table-mode native

benchbox run --platform duckdb --benchmark tpch --scale 0.1 --table-mode external
```

The first command uses the default mode, which materializes native tables. The second registers the files externally (views or external tables).

`--table-mode external` is useful when you want direct file-based comparisons across engines. It is not compatible with `--tuning tuned`.

## Quick Comparison: DuckDB vs SQLite

```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.1 --output duckdb_results.json

benchbox run --platform sqlite --benchmark tpch --scale 0.1 --output sqlite_results.json

benchbox compare duckdb_results.json sqlite_results.json
```

The SQLite run uses the same generated data as the DuckDB run.

**Example output** (actual results vary based on hardware, configuration, and workload):
```
Platform Comparison: TPC-H SF0.1

              DuckDB    SQLite    Ratio
Query 1       156ms     312ms     2.0x
Query 2       89ms      178ms     2.0x
Query 3       234ms     890ms     3.8x
...
Total Time    2.4s      8.9s      3.7x

DuckDB completed in 3.7x less time
```

## Adding Cloud Platforms

Compare local and cloud performance:

```bash
benchbox run --platform duckdb --benchmark tpch --scale 1 --output local.json

benchbox run --platform snowflake --benchmark tpch --scale 1 --output snowflake.json
benchbox run --platform bigquery --benchmark tpch --scale 1 --output bigquery.json

benchbox run --platform snowflake --benchmark tpch --scale 1 --table-mode external \
  --platform-option staging_root=s3://bucket/benchbox/ --output snowflake_external.json
benchbox run --platform athena --benchmark tpch --scale 1 --table-mode external \
  --platform-option staging_root=s3://bucket/benchbox/ --output athena_external.json
benchbox run --platform bigquery --benchmark tpch --scale 1 --table-mode external \
  --platform-option staging_root=gs://bucket/benchbox/ --output bigquery_external.json

benchbox compare local.json snowflake.json bigquery.json
```

The first command is the local baseline. The cloud runs require credentials. The `--table-mode external` examples use file-backed registration. The last command is a multi-way comparison.

## Platform Requirements

| Platform | Setup Required |
|----------|----------------|
| DuckDB | None (embedded) |
| SQLite | None (embedded) |
| DataFusion | None (embedded) |
| Snowflake | Account + credentials |
| BigQuery | Project + credentials |
| Databricks | Workspace + warehouse |
| Redshift | Cluster + credentials |
| ClickHouse | Server + credentials |

See [Platform Documentation](../platforms/index.md) for setup guides.

## DataFrame Platforms

Compare SQL and DataFrame execution:

```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.1 --output sql.json

benchbox run --platform polars-df --benchmark tpch --scale 0.1 --output polars.json

benchbox compare sql.json polars.json
```

The first command is SQL execution, the second is DataFrame execution with Polars, and the `compare` command compares the two paradigms.

## Best Practices

### Use Same Scale Factor

```bash
benchbox run --platform duckdb --benchmark tpch --scale 1
benchbox run --platform snowflake --benchmark tpch --scale 1

benchbox run --platform duckdb --benchmark tpch --scale 0.1
benchbox run --platform snowflake --benchmark tpch --scale 10
```

The first pair is correct because both platforms use the same scale factor. The second pair is incorrect because the scale factors differ, so the results are not comparable.

### Run Multiple Iterations

For statistical significance, run multiple times:

```bash
for i in 1 2 3; do
  benchbox run --platform duckdb --benchmark tpch --output duckdb_run$i.json
done
```

### Consider Cold vs Warm

First run includes caching overhead. For warm comparisons:

```bash
benchbox run --platform duckdb --benchmark tpch

benchbox run --platform duckdb --benchmark tpch --output results.json
```

The first command is a warm-up run whose results you discard. The second is the measured run.

## Comparison Script

For systematic platform evaluation:

```python
import subprocess
import json

PLATFORMS = ["duckdb", "sqlite", "datafusion"]
SCALE = 0.1

results = {}
for platform in PLATFORMS:
    output = f"{platform}_results.json"
    subprocess.run([
        "benchbox", "run",
        "--platform", platform,
        "--benchmark", "tpch",
        "--scale", str(SCALE),
        "-o", output
    ])
    with open(output) as f:
        results[platform] = json.load(f)

for platform, data in results.items():
    total = data.get("summary", {}).get("total_time_seconds", 0)
    print(f"{platform}: {total:.1f}s")
```

The script compares TPC-H across platforms and prints the total time for each. It is a standalone Python 3 script.

## Next Steps

- [DataFrame Benchmarking](dataframe-quickstart.md) - SQL vs DataFrame comparison
- [Platform Selection Guide](../platforms/platform-selection-guide.md) - Choosing a platform
