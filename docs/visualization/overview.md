# BenchBox Visualization Architecture

```{tags} intermediate, concept, visualization
```

## Goals and Constraints
- Automate terminal-friendly charts from canonical BenchBox results with zero manual wrangling.
- One consistent theming surface across light and dark ASCII output.
- Self contained: Python-first, no external rendering dependencies; zero additional packages required.
- Works everywhere: CI logs, SSH sessions, LLM/MCP agents, screen readers.

## Library Selection
- **ASCII Output:** Custom implementation using ANSI escape codes and Unicode block characters for terminal display. Supports all chart types with colorblind-friendly palettes and ASCII fallback for basic terminals.
- **No external charting dependencies:** Plotly, Matplotlib, Kaleido, and similar libraries are not used. All rendering is built-in.

## Module Architecture
```
benchbox/core/visualization/
  __init__.py             # Public entrypoints and convenience re-exports
  templates.py            # Named chart templates (flagship, head-to-head, trends, cost, comparison)
  exporters.py            # Export helpers for ASCII text files; render_ascii_chart() factory
  result_plotter.py       # High-level orchestration over BenchmarkResults / canonical JSON
  ascii/                  # ASCII chart implementations
    base.py               # Base class, options, terminal detection, color helpers
    bar_chart.py          # Performance bar chart
    box_plot.py           # Distribution box plot
    histogram.py          # Query latency histogram
    line_chart.py         # Time-series line chart
    scatter_plot.py       # Cost-performance scatter plot
    comparison_bar.py     # Paired comparison bar chart (side-by-side runs)
    diverging_bar.py      # Diverging bar chart (percentage change)
    summary_box.py        # Summary statistics box
```

## Chart Taxonomy
- **Performance bar:** Multi-platform comparisons with sorting, error bars, winners highlighted.
- **Time-series line:** Performance over time/runs with multi-series support.
- **Cost-performance scatter:** Price/performance visualization with platform labels.
- **Query variance heatmap:** Query x platform grid for TPC-H/TPC-DS/ClickBench analysis.
- **Query latency histogram:** Per-query vertical bars showing latency; auto-splits for large benchmarks (>33 queries).
- **Distribution box plot:** Latency distributions with quartiles, whiskers, and outlier markers.
- **Comparison bar:** Paired side-by-side bars per query with percentage change annotations.
- **Diverging bar:** Percentage change bars centered on zero (green for improvement, red for regression).
- **Summary box:** Key statistics in a bordered box (total time, geometric mean, query count, etc.).

## Style Guide
- Palette: Colorblind-friendly Okabe-Ito set, `#1b9e77`, `#d95f02`, `#7570b3`, `#e7298a`, `#66a61e`, `#e6ab02`.
- Neutral grays: `#2f3437` text, `#6b7075` secondary.
- Best/worst highlighting: green for fastest, red/orange for slowest.
- Annotations: Best/worst markers, legends with platform naming, scale notes.
- Accessibility: Colorblind-safe palette, Unicode/ASCII fallback, screen reader friendly text output.

## CLI Design (`benchbox visualize`)
- Inputs: Single/multiple result JSON files or directories. Auto-detect latest in `benchmark_runs/results` when none provided.
- Core flags:
  - `--chart-type` (`auto` default; supports performance_bar|distribution_box|query_heatmap|query_histogram|cost_scatter|time_series|all)
  - `--template` (default|flagship|head_to_head|trends|cost_optimization|comparison)
  - `--theme` (light|dark)
  - `--no-color` (disable ANSI colors for piping to files or plain terminals)
  - `--no-unicode` (use ASCII-only characters for basic terminals)
- Behavior:
  - Smart selection: when `auto`, renders all supported chart types based on available data.
  - Templates bundle predefined chart sets for common content workflows.

## ASCII Chart Output

ASCII charts provide terminal-friendly visualization without requiring a browser or external dependencies:

```bash
benchbox visualize results.json

benchbox visualize results.json --no-color

benchbox visualize results.json --no-unicode

benchbox visualize results.json --chart-type performance_bar

benchbox visualize results.json --template flagship
```

The commands, in order, display charts directly in the terminal, drop colors (for piping or plain terminals), drop Unicode (for terminals without Unicode support), select a specific chart type, and use a template.

**Features:**
- 9 chart types: bar, box, heatmap, histogram, scatter, line, comparison bar, diverging bar, summary box
- Colorblind-friendly Okabe-Ito palette with 256-color and 16-color fallbacks
- Unicode block characters (▏▎▍▌▋▊▉█) with ASCII fallback ( .-=+#@)
- Terminal width detection (40-120 character constraint)
- Best/worst highlighting, legends, and statistical summaries
- Light and dark themes

**Use cases:**
- LLM/MCP integration where agents interpret text output
- CI/CD pipelines needing visual summaries in logs
- SSH sessions without X11 forwarding
- Screen reader accessibility
- Quick result inspection during development

## Export

- ASCII charts render directly to the terminal (stdout).
- Use `--no-color` to strip ANSI codes for piping to files or text processing.
- Text file export available via the `export_ascii()` helper function.

## Dependency Footprint
- Zero additional dependencies: visualization is built entirely on Python standard library plus the existing `rich` dependency for console output.
- No lazy imports or optional packages needed for chart generation.

## Related Documentation

- [Chart Generation Guide](chart-generation-guide.md) - Step-by-step guide to creating charts
- [Chart Types](chart-types.md) - Available chart types and when to use them
- [Customization](customization.md) - Styling, theming, and advanced options
- [Templates](templates.md) - Reusable chart templates
- [CLI Reference](cli-reference.md) - Command-line interface for visualization

```{toctree}
:maxdepth: 1
:caption: Visualization
:hidden:

chart-generation-guide
chart-types
customization
templates
cli-reference
```
