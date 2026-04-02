(cli-aggregate)=
# `aggregate` - Aggregate Results

```{tags} reference, cli, analysis
```

Aggregate multiple benchmark result files into a CSV file for performance trend tracking and downstream analysis.

## Basic Syntax

```bash
benchbox aggregate --input-dir <path> --output-file <path> [OPTIONS]
```

## Options

**Required:**
- `--input-dir PATH`: Directory containing result JSON files (searched recursively)
- `--output-file PATH`: Output CSV file path

**Optional:**
- `--benchmark TEXT`: Filter results by benchmark name
- `--platform TEXT`: Filter results by platform name

## Output Format

The CSV output contains one row per result file with these columns:

| Column | Description |
|--------|-------------|
| `timestamp` | Benchmark execution timestamp |
| `benchmark` | Benchmark name |
| `platform` | Platform name |
| `scale_factor` | Scale factor used |
| `total_time_s` | Total execution time in seconds |
| `geometric_mean_ms` | Geometric mean of query times (ms) |
| `p50_ms` | Median query time (ms) |
| `p95_ms` | 95th percentile query time (ms) |
| `p99_ms` | 99th percentile query time (ms) |
| `num_queries` | Number of successful queries |
| `file` | Source result filename |

## Usage Examples

```bash
# Aggregate all results in directory
benchbox aggregate --input-dir benchmark_runs/ --output-file trends.csv

# Filter by benchmark
benchbox aggregate \
  --input-dir benchmark_runs/ \
  --output-file tpch_trends.csv \
  --benchmark tpch

# Filter by platform
benchbox aggregate \
  --input-dir benchmark_runs/ \
  --output-file duckdb_trends.csv \
  --platform duckdb
```

## Related

- [report](report.md) - Historical analysis and trend detection from the result database
- [results](results.md) - View individual benchmark results
