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
benchbox visualize                              # Auto-detect latest
benchbox visualize results.json                 # Single file
benchbox visualize results/*.json               # Glob pattern
benchbox visualize run1.json run2.json          # Multiple files
```

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
# Generate charts from latest result (auto-detected)
benchbox visualize

# Generate from specific file
benchbox visualize benchmark_runs/results/tpch_duckdb_sf1.json

# Generate from multiple files for comparison
benchbox visualize duckdb.json snowflake.json bigquery.json
```

### Using Templates

```bash
# Flagship comparison (4-chart set)
benchbox visualize results/*.json --template flagship

# Head-to-head comparison
benchbox visualize platform_a.json platform_b.json --template head_to_head

# Performance trends over time
benchbox visualize runs/2024/*.json runs/2025/*.json --template trends

# Cost optimization analysis
benchbox visualize cloud_results/*.json --template cost_optimization
```

### Display Options

```bash
# Dark theme
benchbox visualize results/*.json --theme dark

# Specific chart types only
benchbox visualize results/*.json --chart-type performance_bar --chart-type cost_scatter

# Pipe-friendly output (no ANSI codes)
benchbox visualize results/*.json --no-color > comparison.txt

# ASCII-only for basic terminals
benchbox visualize results/*.json --no-unicode

# Combine options
benchbox visualize results/*.json --theme dark --no-color --no-unicode
```

### Query Latency Histogram

```bash
# Per-query latency histogram (ideal for identifying slow queries)
benchbox visualize results/*.json --chart-type query_histogram

# TPC-DS results auto-split into 3 charts (99 queries / 33 per chart)
benchbox visualize tpcds_results.json --chart-type query_histogram
```

## Output

Charts render directly to the terminal (stdout). All output is text-based with optional ANSI color codes.

To save output to a file:

```bash
# With ANSI codes preserved (viewable in terminals that support ANSI)
benchbox visualize results/*.json > charts.ansi

# Plain text (no color codes)
benchbox visualize results/*.json --no-color > charts.txt
```

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
