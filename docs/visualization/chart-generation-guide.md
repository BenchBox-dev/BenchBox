# Chart Generation Guide

```{tags} intermediate, guide, visualization
```

This guide walks you through generating charts from BenchBox benchmark results. Whether you're inspecting results in a terminal, creating CI summaries, or comparing platforms, this guide covers the end-to-end workflow.

## Prerequisites

No additional dependencies are required. BenchBox visualization is built entirely on the Python standard library and renders directly to the terminal.

### Verify Installation

```bash
benchbox visualize --help
```

---

## Quick Start

### Generate Charts from Latest Result

```bash
benchbox visualize
```

This auto-detects the most recent result in `benchmark_runs/results/` and generates default charts.

*See [Chart Types](chart-types.md) for examples of each chart type.*

### Generate from Specific Results

```bash
benchbox visualize benchmark_runs/results/tpch_duckdb_sf1.json
```

### Compare Multiple Platforms

```bash
benchbox visualize duckdb.json snowflake.json bigquery.json
```

---

## Workflow by Content Type

### Flagship Analysis (Multi-Platform Comparison)

For comprehensive "State of the Data Warehouse" style analysis:

```bash
benchbox visualize results/*.json --template flagship
```

**Generates:**
- Performance bar chart (platform comparison)
- Query variance heatmap (per-query analysis)
- Cost-performance scatter (ROI analysis, if cost data available)
- Distribution box plot (consistency analysis)

### Head-to-Head Comparison

For "DuckDB vs Snowflake" style comparisons:

```bash
benchbox visualize duckdb.json snowflake.json --template head_to_head
```

**Generates:**
- Performance bar chart (side-by-side comparison)
- Distribution box plot (consistency comparison)
- Query variance heatmap (per-query winners)

### Performance Trend Analysis

For tracking performance over time:

```bash
benchbox visualize runs/2024/*.json runs/2025/*.json --template trends
```

**Generates:**
- Time-series line chart
- Latest snapshot bar chart

### Cost Optimization Analysis

For ROI and cost analysis:

```bash
benchbox visualize cloud_results/*.json --template cost_optimization
```

**Generates:**
- Cost-performance scatter
- Performance comparison bar chart

---

## Smart Chart Selection

When no template or specific chart types are specified, `--chart-type auto` (the default) renders all supported chart types based on the available data:

| Data Characteristics | Charts Generated |
|---------------------|------------------|
| Single platform | Query breakdown bar + distribution box |
| Multiple platforms | Platform comparison bar + heatmap |
| Cost data present | Adds cost-performance scatter |
| Multiple timestamps | Adds time-series trend |

```bash
benchbox visualize results/*.json

benchbox visualize results/*.json --chart-type performance_bar
```

The first command lets BenchBox decide which charts to generate. The second generates specific charts only.

---

## Display Options

### Dark Theme

```bash
benchbox visualize results/*.json --theme dark
```

### Pipe-Friendly Output

```bash
benchbox visualize results/*.json --no-color > charts.txt

benchbox visualize results/*.json --no-unicode
```

`--no-color` strips ANSI colors for file output. `--no-unicode` uses ASCII-only characters for basic terminals.

### Specific Chart Types

```bash
benchbox visualize results/*.json --chart-type performance_bar,cost_scatter
```

---

## Troubleshooting

### Empty or Missing Charts

Check that your result JSON includes the required fields:
- Performance bar: `total_time_ms` or `avg_time_ms`
- Distribution box: per-query `execution_time_ms` values
- Heatmap: At least 2 platforms with query-level timings
- Cost scatter: `cost_summary.total_cost`

### "No result sources provided"

Either specify files explicitly or ensure `benchmark_runs/results/` contains JSON files:
```bash
benchbox visualize benchmark_runs/results/my_result.json
```

### Charts Look Different Than Expected

- Check `--theme` setting (light vs dark)
- Ensure you're using the intended `--template`
- Verify terminal supports Unicode if using block characters (try `--no-unicode` as a fallback)

---

## Best Practices

1. **Use templates** for consistent chart sets across analyses
2. **Use `--no-color`** when piping output to files
3. **Name output files** clearly when saving (`> comparison-2025-q1.txt`)
4. **Keep source JSON** files for reproducibility
5. **Use MCP tools** for programmatic chart generation in AI workflows

---

## Next Steps

- [Chart Types](chart-types.md) - Understand each chart type in detail
- [Templates](templates.md) - Learn about predefined templates
- [Customization](customization.md) - Fine-tune colors, themes, and styling
- [CLI Reference](cli-reference.md) - Complete command reference
