# Comparing Platforms

```{tags} intermediate, tutorial, sql-platform
```

Run the same benchmark on multiple databases to compare performance.

## Overview

BenchBox makes it easy to compare platforms because:
- Same benchmark runs identically on all platforms
- Same data (shared generation)
- Same validation criteria

### Shared Generated Data

BenchBox generates benchmark data once per benchmark and scale factor (compressed `.tbl` files), then every platform loads from the same dataset. This gives you an apples-to-apples comparison: differences in results reflect engine performance, not data differences. A second run at the same scale factor reuses the generated data instead of regenerating it.

### Choosing Table Mode

Use `--table-mode` to control how data is registered before query execution:

```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.1 --table-mode native

benchbox run --platform duckdb --benchmark tpch --scale 0.1 --table-mode external
```

The first command uses the default mode, which materializes native tables. The second registers the files externally (views or external tables).

`--table-mode external` is useful when you want direct file-based comparisons across engines.

## Quick Comparison: DuckDB vs SQLite

```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.1 --output ./benchmark_runs

benchbox run --platform sqlite --benchmark tpch --scale 0.1 --output ./benchmark_runs

benchbox results --limit 2
```

`--output` takes a directory for generated data; result files land in the runs
root (`benchmark_runs/` next to your checkout, or `BENCHBOX_OUTPUT_DIR`). Copy
the two result paths from `benchbox results` and compare them:

```bash
benchbox compare ./benchmark_runs/results/<duckdb-result>.json ./benchmark_runs/results/<sqlite-result>.json
```

The SQLite run reuses the same generated data as the DuckDB run.

**Example output** (actual results vary based on hardware, configuration, and workload):
```
BenchBox Platform Comparison

...
Speedup Ratio: 3.7x
```

## Adding Cloud Platforms

Compare local and cloud performance:

```bash
benchbox run --platform duckdb --benchmark tpch --scale 1 --output ./benchmark_runs

benchbox run --platform snowflake --benchmark tpch --scale 1 --output ./benchmark_runs
benchbox run --platform bigquery --benchmark tpch --scale 1 --output ./benchmark_runs

benchbox run --platform snowflake --benchmark tpch --scale 1 --table-mode external \
  --platform-option staging_root=s3://bucket/benchbox/ --output ./benchmark_runs
benchbox run --platform athena --benchmark tpch --scale 1 --table-mode external \
  --platform-option staging_root=s3://bucket/benchbox/ --output ./benchmark_runs
benchbox run --platform bigquery --benchmark tpch --scale 1 --table-mode external \
  --platform-option staging_root=gs://bucket/benchbox/ --output ./benchmark_runs
```

The first command is the local baseline. The cloud runs require credentials. The `--table-mode external` examples use file-backed registration. Locate the result files with `benchbox results --limit` and pass them to `benchbox compare`.

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
benchbox run --platform duckdb --benchmark tpch --scale 0.1 --output ./benchmark_runs

benchbox run --platform polars-df --benchmark tpch --scale 0.1 --output ./benchmark_runs
```

The first command is SQL execution, the second is DataFrame execution with Polars. Find the two result files with `benchbox results --limit 2` and pass them to `benchbox compare`.

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
  benchbox run --platform duckdb --benchmark tpch --output ./benchmark_runs
done
```

Each run writes a new result file; list them with `benchbox results --limit 3`.

### Consider Cold vs Warm

First run includes caching overhead. For warm comparisons:

```bash
benchbox run --platform duckdb --benchmark tpch --output ./benchmark_runs

benchbox run --platform duckdb --benchmark tpch --output ./benchmark_runs
```

Power tests already run one warm-up iteration plus three measured iterations by default. For an extra-primed comparison, treat the first command as the cache-priming run and compare using the second run's result file.

## Comparison Script

For systematic platform evaluation:

```python
import glob
import json
import os
import subprocess

PLATFORMS = ["duckdb", "sqlite", "datafusion"]
SCALE = 0.1

for platform in PLATFORMS:
    runs_root = f"./runs-{platform}"
    subprocess.run(
        [
            "benchbox", "run",
            "--platform", platform,
            "--benchmark", "tpch",
            "--scale", str(SCALE),
            "--output", "./benchmark_runs",
            "--non-interactive",
        ],
        env={**os.environ, "BENCHBOX_OUTPUT_DIR": runs_root},
        check=True,
    )

for platform in PLATFORMS:
    paths = glob.glob(f"./runs-{platform}/results/*.json")
    latest = max(paths, key=os.path.getmtime)
    with open(latest) as f:
        data = json.load(f)
    total_ms = data.get("summary", {}).get("timing", {}).get("total_ms", 0)
    print(f"{platform}: {total_ms / 1000:.1f}s")
```

The script runs TPC-H on each platform into its own runs root, reads the newest result file per platform, and prints total measured query time. It is a standalone Python 3 script.

## Next Steps

- [DataFrame Benchmarking](dataframe-quickstart.md) - SQL vs DataFrame comparison
- [Platform Selection Guide](../platforms/platform-selection-guide.md) - Choosing a platform
