# CLI Reference: `benchbox visualize`

```{tags} intermediate, reference, visualization, cli
```

Generate ASCII charts directly from benchmark result JSON files.

## Synopsis

```
benchbox visualize [SOURCES...] [OPTIONS]
```

## Description

The `visualize` command transforms BenchBox result JSON files into ASCII charts rendered directly in the terminal. It supports multiple chart types, templates for common workflows, and display customization options.

**Auto-detection:** When no sources are specified, automatically finds the latest results in `benchmark_runs/results/`.

## Arguments

**SOURCES** (optional)
: One or more result JSON files or glob patterns. If omitted, uses the latest result files.

```bash
benchbox visualize
benchbox visualize results.json
benchbox visualize results/*.json
benchbox visualize run1.json run2.json
```

The four commands auto-detect the latest results, read a single file, expand a glob pattern, and read multiple files, in that order.

## Options

### Template Selection

`--template {default,flagship,head_to_head,trends,cost_optimization,comparison,latency_deep_dive,regression_triage,executive_summary}`
: Use a predefined chart template. Overrides `--chart-type`.

```bash
benchbox visualize results/*.json --template flagship
```

### Chart Type Selection

`--chart-type {auto,all,performance_bar,power_bar,distribution_box,query_heatmap,query_histogram,cost_scatter,time_series,...}`
: Specify chart types to generate. Repeatable for multiple types. Run `benchbox visualize --help` for the full list.

```bash
benchbox visualize results/*.json --chart-type performance_bar --chart-type distribution_box
```

| Value | Description |
|-------|-------------|
| `auto` | Render all applicable chart types (default) |
| `all` | Same as `auto` |
| `performance_bar` | Platform comparison bar chart (total execution time, lower is better) |
| `power_bar` | TPC Power@Size comparison bar chart; falls back to power-run query latency bars when no TPC metric exists |
| `distribution_box` | Latency distribution box plot |
| `query_heatmap` | Query x platform variance heatmap |
| `query_histogram` | Per-query latency bars; uses horizontal bars for long query labels and vertical bars otherwise |
| `cost_scatter` | Cost-performance scatter plot |
| `time_series` | Performance trend line chart |
| `comparison_bar` | Per-query paired bars with % change (requires 2 results) |
| `diverging_bar` | Percentage change centered on zero (requires 2 results) |
| `summary_box` | Key aggregate statistics panel |
| `percentile_ladder` | P50/P90/P95/P99 ladder across platforms |
| `normalized_speedup` | Log₂-scaled speedup relative to a baseline |
| `stacked_phase` | Stacked phase breakdown by benchmark phase |
| `sparkline_table` | Compact metric table with sparklines |
| `cdf_chart` | Cumulative distribution of query latency |
| `rank_table` | Per-query platform rankings (1st = fastest) |

### Appearance

`--theme {light,dark}`
: Color theme for charts.

```bash
benchbox visualize results/*.json --theme dark
```
Default: `light`

`--no-color`
: Disable ANSI colors in output. Useful for piping to files or plain terminals.

```bash
benchbox visualize results/*.json --no-color > charts.txt
```

`--no-unicode`
: Use ASCII-only characters instead of Unicode block characters. For terminals without Unicode support.

```bash
benchbox visualize results/*.json --no-unicode
```

## Examples

### Basic Usage

```bash
benchbox visualize

benchbox visualize benchmark_runs/results/tpch_duckdb_sf1.json

benchbox visualize duckdb.json snowflake.json bigquery.json
```

The commands generate charts from the latest result (auto-detected), from a specific file, and from multiple files for comparison.

### Using Templates

```bash
benchbox visualize results/*.json --template flagship

benchbox visualize platform_a.json platform_b.json --template head_to_head

benchbox visualize runs/2024/*.json runs/2025/*.json --template trends

benchbox visualize cloud_results/*.json --template cost_optimization
```

The templates give a flagship comparison (a four-chart set), a head-to-head comparison, performance trends over time, and a cost optimization analysis, in that order.

### Display Options

```bash
benchbox visualize results/*.json --theme dark

benchbox visualize results/*.json --chart-type performance_bar --chart-type cost_scatter

benchbox visualize results/*.json --no-color > comparison.txt

benchbox visualize results/*.json --no-unicode

benchbox visualize results/*.json --theme dark --no-color --no-unicode
```

The commands select the dark theme, limit output to specific chart types, produce pipe-friendly output with no ANSI codes, produce ASCII-only output for basic terminals, and combine options.

### Query Latency Histogram

```bash
benchbox visualize results/*.json --chart-type query_histogram

benchbox visualize tpcds_results.json --chart-type query_histogram
```

The first command draws a per-query latency histogram, which is ideal for identifying slow queries. TPC-DS results are split automatically into three charts (99 queries, 33 per chart).

## Output

Charts render directly to the terminal (stdout). All output is text-based with optional ANSI color codes.

To save output to a file:

```bash
benchbox visualize results/*.json > charts.ansi

benchbox visualize results/*.json --no-color > charts.txt
```

The first command preserves ANSI codes, so the file is viewable in terminals that support ANSI. The second writes plain text with no color codes.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (invalid input, no results found, etc.) |

## Dependencies

No additional dependencies required. Visualization is built into BenchBox core.

## See Also

- [Chart Types](chart-types.md) - Detailed chart type documentation
- [Templates](templates.md) - Template descriptions and use cases
- [Customization](customization.md) - Themes, colors, and styling options
