(cli-visualize)=
# `visualize` - Generate Charts

```{tags} reference, cli, visualization
```

Generate ASCII charts from benchmark result files directly in the terminal.

## Basic Syntax

```bash
benchbox visualize [SOURCES...] [OPTIONS]
```

## Arguments

- `SOURCES`: One or more paths to benchmark result JSON files. If omitted, auto-discovers the 5 most recent results from `benchmark_runs/results/`.

## Options

- `--chart-type TEXT`: Chart type to render (default: `auto`). Can be specified multiple times.
  - `auto` or `all`: Render all applicable chart types
  - Specific types: `performance_bar`, `query_time_histogram`, `speedup`, `comparison`, and others
- `--template TEXT`: Named template that defines a preset combination of chart types (overrides `--chart-type`)
- `--theme [light|dark]`: Color theme (default: `light`)
- `--no-color`: Disable ANSI colors in output (useful for piping to files)
- `--no-unicode`: Use ASCII-only characters (for terminals without Unicode support)

## Usage Examples

```bash
benchbox visualize

benchbox visualize benchmark_runs/results/duckdb_tpch_sf01.json

benchbox visualize result_a.json result_b.json --chart-type speedup

benchbox visualize result.json --chart-type performance_bar

benchbox visualize result.json --template overview

benchbox visualize result.json --no-color --no-unicode > charts.txt

benchbox visualize result.json --theme dark
```

## Notes

- Pairwise comparison charts (e.g., `speedup`) require exactly 2 result files when specified explicitly. When using `auto` or `all`, pairwise charts are skipped if the input count doesn't match.
- Chart types can be listed with `benchbox visualize --help`.

## Related

- [run](run.md) - Run benchmarks to generate result files
- [results](results.md) - View and export benchmark results
