(cli-report)=
# `report` - Historical Analysis

```{tags} reference, cli, analysis
```

Analyze benchmark results over time, generate platform rankings, and detect performance regressions. Results are stored in a local SQLite database at `~/.benchbox/results.db`.

## Basic Syntax

```bash
benchbox report <subcommand> [OPTIONS]
```

## Subcommands

### `rankings` - Platform Rankings

Generate platform rankings for a benchmark based on historical results.

```bash
benchbox report rankings --benchmark <name> --scale-factor <sf> [OPTIONS]
```

**Required:**
- `--benchmark, -b TEXT`: Benchmark name (e.g., TPC-H, TPC-DS)
- `--scale-factor, -s FLOAT`: Scale factor to rank

**Optional:**
- `--metric, -m [geometric_mean|power_at_size|cost_efficiency]`: Metric to rank by (default: `geometric_mean`)
- `--min-samples INT`: Minimum samples required to include a platform (default: 1)
- `--lookback-days INT`: Consider results from the last N days (default: 90)
- `--db-path PATH`: Path to result database

```bash
benchbox report rankings --benchmark TPC-H --scale-factor 1
benchbox report rankings -b TPC-DS -s 10 --metric power_at_size
```

### `trends` - Performance Trends

Show performance trends for a platform over time, highlighting regressions.

```bash
benchbox report trends --platform <name> --benchmark <name> --scale-factor <sf> [OPTIONS]
```

**Required:**
- `--platform, -p TEXT`: Platform name
- `--benchmark, -b TEXT`: Benchmark name
- `--scale-factor, -s FLOAT`: Scale factor

**Optional:**
- `--periods INT`: Number of periods to analyze (default: 6)
- `--period-days INT`: Days per period (default: 30)
- `--db-path PATH`: Path to result database

```bash
benchbox report trends --platform DuckDB --benchmark TPC-H --scale-factor 1
```

### `regressions` - Detect Regressions

Scan all platforms and benchmarks for significant performance slowdowns.

```bash
benchbox report regressions [OPTIONS]
```

**Optional:**
- `--threshold FLOAT`: Regression threshold percentage (default: 10.0)
- `--lookback-days INT`: Comparison period in days (default: 30)
- `--db-path PATH`: Path to result database

```bash
benchbox report regressions
benchbox report regressions --threshold 15 --lookback-days 14
```

### `import` - Import Results

Import benchmark result files into the historical database.

```bash
benchbox report import <directory> [OPTIONS]
```

**Required:**
- `DIRECTORY`: Path to directory containing result JSON files

**Optional:**
- `--pattern TEXT`: Glob pattern for result files (default: `**/*.json`)
- `--db-path PATH`: Path to result database

```bash
benchbox report import benchmark_runs/results/
benchbox report import ./results --pattern "*.json"
```

### `stats` - Database Statistics

Show summary statistics for the result database.

```bash
benchbox report stats [OPTIONS]
```

**Optional:**
- `--db-path PATH`: Path to result database

### `list` - List Results

List stored benchmark results with optional filters.

```bash
benchbox report list [OPTIONS]
```

**Optional:**
- `--platform, -p TEXT`: Filter by platform
- `--benchmark, -b TEXT`: Filter by benchmark
- `--limit INT`: Maximum results to show (default: 20)
- `--db-path PATH`: Path to result database

```bash
benchbox report list
benchbox report list --platform DuckDB --limit 10
```

## Related

- [results](results.md) - View and export recent benchmark results
- [visualize](visualize.md) - Generate charts from results
