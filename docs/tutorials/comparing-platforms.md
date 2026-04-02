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
# Default: materialize native tables
benchbox run --platform duckdb --benchmark tpch --scale 0.1 --table-mode native

# External registration over files (views/external tables)
benchbox run --platform duckdb --benchmark tpch --scale 0.1 --table-mode external
```

`--table-mode external` is useful when you want direct file-based comparisons across engines. It is not compatible with `--tuning tuned`.

## Quick Comparison: DuckDB vs SQLite

```bash
# Run on DuckDB
benchbox run --platform duckdb --benchmark tpch --scale 0.1 -o duckdb_results.json

# Run on SQLite (uses same generated data)
benchbox run --platform sqlite --benchmark tpch --scale 0.1 -o sqlite_results.json

# Compare results
benchbox compare duckdb_results.json sqlite_results.json
```

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
# Local baseline
benchbox run --platform duckdb --benchmark tpch --scale 1 -o local.json

# Cloud (requires credentials)
benchbox run --platform snowflake --benchmark tpch --scale 1 -o snowflake.json
benchbox run --platform bigquery --benchmark tpch --scale 1 -o bigquery.json

# Cloud external-mode examples (file-backed registration)
benchbox run --platform snowflake --benchmark tpch --scale 1 --table-mode external \
  --platform-option staging_root=s3://bucket/benchbox/ -o snowflake_external.json
benchbox run --platform athena --benchmark tpch --scale 1 --table-mode external \
  --platform-option staging_root=s3://bucket/benchbox/ -o athena_external.json
benchbox run --platform bigquery --benchmark tpch --scale 1 --table-mode external \
  --platform-option staging_root=gs://bucket/benchbox/ -o bigquery_external.json

# Multi-way comparison
benchbox compare local.json snowflake.json bigquery.json
```

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
# SQL execution
benchbox run --platform duckdb --benchmark tpch --scale 0.1 -o sql.json

# DataFrame execution (Polars)
benchbox run --platform polars-df --benchmark tpch --scale 0.1 -o polars.json

# Compare paradigms
benchbox compare sql.json polars.json
```

## Best Practices

### Use Same Scale Factor

```bash
# Correct: same scale factor
benchbox run --platform duckdb --benchmark tpch --scale 1
benchbox run --platform snowflake --benchmark tpch --scale 1

# Incorrect: different scale factors (not comparable)
benchbox run --platform duckdb --benchmark tpch --scale 0.1
benchbox run --platform snowflake --benchmark tpch --scale 10
```

### Run Multiple Iterations

For statistical significance, run multiple times:

```bash
for i in 1 2 3; do
  benchbox run --platform duckdb --benchmark tpch -o duckdb_run$i.json
done
```

### Consider Cold vs Warm

First run includes caching overhead. For warm comparisons:

```bash
# Warm up (discard first run)
benchbox run --platform duckdb --benchmark tpch

# Measured run
benchbox run --platform duckdb --benchmark tpch -o results.json
```

## Comparison Script

For systematic platform evaluation:

```python
#!/usr/bin/env python3
"""Compare TPC-H across platforms."""
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

# Compare total times
for platform, data in results.items():
    total = data.get("summary", {}).get("total_time_seconds", 0)
    print(f"{platform}: {total:.1f}s")
```

## Next Steps

- [DataFrame Benchmarking](dataframe-quickstart.md) - SQL vs DataFrame comparison
- [Platform Selection Guide](../platforms/platform-selection-guide.md) - Choosing a platform
- [Cost Optimization](../advanced/cost-optimization.md) - Cloud cost management
