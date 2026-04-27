# Research: Why We Deleted Plotly and Wrote Our Own ASCII Charts

## 1. Git History Timeline

**Total elapsed time from ASCII introduction to Plotly removal: ~28 hours**

| Date/Time (EST) | Commit | Description | Lines |
|---|---|---|---|
| Feb 5, 8:52 AM | 07b8e436 | ASCII charts introduced (5 types + base) | +2,847 |
| Feb 5, 5:29 PM | 2448e586 | Histogram added (last Plotly feature) | +1,247 |
| Feb 6, 12:45 PM | 812d2bd2 | 3 new ASCII chart types (comparison, diverging, summary) | +1,896 |
| Feb 6, 12:51 PM | dd35df9e | **Plotly removed** (breaking change) | -4,300 / +918 |
| Feb 6, 12:55 PM | 8151a668 | TODO marked complete | |
| Feb 6, 1:18 PM | a7e1359d | Docs updated for ASCII-only | |
| Feb 6, 7:21 PM | 00006143 | 41 polish tests added | |
| Feb 9, 2:41 PM | f16f7ef5 | Auto post-run summary charts | +307 |

**Notable**: Plotly was in the codebase for approximately 2 days total (Feb 4-6, 2026) before being removed. The 3 new comparison chart types were added 6 minutes before Plotly removal, which would have required 2x implementation work under the old dual model.

## 2. Plotly Removal Stats (commit dd35df9e)

- **Files changed**: 42
- **Lines added**: 918 (refactoring, docs, TODO updates)
- **Lines deleted**: 4,300
- **Net change**: -3,382 lines
- **Files deleted**: 12
  - `benchbox/core/visualization/charts.py` (626 lines, 6 Plotly chart classes)
  - `benchbox/core/visualization/styles.py` (137 lines, Plotly theme system)
  - `benchbox/core/visualization/dependencies.py` (20 lines, require_plotly() gate)
  - `examples/visualization/cost_analysis_charts.ipynb` (68 lines)
  - `examples/visualization/flagship_post_charts.ipynb` (77 lines)
  - `examples/visualization/head_to_head_comparison.ipynb` (67 lines)
  - `examples/visualization/trend_analysis.ipynb` (85 lines)
  - `scripts/generate_doc_images.py` (430 lines)
  - `tests/integration/visualization/test_visualization_export.py` (50 lines)
  - `tests/unit/visualization/test_charts.py` (264 lines)
  - `tests/unit/visualization/test_result_plotter.py` (385 lines)
  - `tests/unit/visualization/test_styles.py` (102 lines)

**Dependency removal from pyproject.toml**: 4 lines removed across `viz`, `all`, `mcp`, and `dev` groups.

## 3. Evidence: HTML Charts Were Unused

Documented in `_project/DONE/core-functionality/active/drop-plotly-html-charts.yaml`:

1. **No `webbrowser.open()` or HTTP server in codebase** - HTML files sat on disk
2. **No CI workflow** generates or validates HTML charts
3. **MCP returns file paths for HTML** (useless to LLMs) vs inline for ASCII (useful)
4. **Blog workflow skill** does not reference chart generation
5. **HTML is the default format** but CLI visualize is rarely invoked
6. **Three Plotly test files use `pytest.importorskip`** - they skip silently in minimal envs
7. **Previous work** (trim-viz-deps-plotly-only.yaml) already removed kaleido, signaling trajectory toward lighter deps

## 4. The Dual Data Model Problem

**Old system had two parallel model hierarchies:**

| Plotly Models | ASCII Models | Purpose |
|---|---|---|
| BarDatum | BarData | Bar chart data |
| TimeSeriesPoint | LinePoint | Line chart data |
| CostPerformancePoint | ScatterPoint | Scatter plot data |
| DistributionSeries | BoxPlotSeries | Box plot data |
| QueryLatencyDatum | HistogramBar | Histogram data |

A conversion layer in `exporters.py` translated between them. Every new chart type required:
1. Implementation in both Plotly and ASCII
2. Two sets of data models
3. Conversion logic between them
4. Two sets of tests

After removal: ASCII models became canonical. ResultPlotter produces them directly. New chart types require one implementation only.

## 5. Dependency Weight

| Dependency | Size | Purpose | Status |
|---|---|---|---|
| plotly | ~43 MB | HTML chart rendering | **Removed** |
| narwhals | ~3.3 MB | Plotly's dataframe compatibility | **Removed** |
| kaleido | Variable (Chrome binary) | Static image export (PNG/SVG) | **Removed earlier** |
| pandas | ~50 MB | Unused but declared | **Removed earlier** |
| pillow | Variable | Unused | **Removed earlier** |
| **Total removed** | **~100 MB** | | |

ASCII charting implementation adds: **0 bytes** of external dependencies.

## 6. Library Evaluation (10+ Libraries)

**Requirements:**
1. `render() -> str` (return string, not print to stdout)
2. Benchmark-specific annotations (best/worst markers, % change, Pareto frontiers)
3. Sub-character bar precision (1/8 Unicode block characters)
4. 4-tier terminal color degradation (truecolor -> 256 -> 16 -> none)
5. Zero additional dependencies

**Evaluation results:**

| Library | Score | Strengths | Gaps |
|---|---|---|---|
| plotext-plus | 7/10 | Good charts, wide type support | Needs stdout->str wrappers, no benchmark annotations, requires numpy |
| plotille | 4/10 | Good scatter/line, returns strings | No bar charts |
| termgraph | 3/10 | Popular, zero deps | Simple bars only, no box/scatter/heatmap, stdout only |
| uniplot | 3/10 | Good quality | Line/scatter only, requires numpy, stdout only |
| rich | 2/10 | Good color support | Not a charting library (tables/panels only) |
| asciichartpy | ≤2/10 | Returns strings | Low precision, no colors |
| drawille | ≤2/10 | Braille rendering | No colors, niche use case |
| bashplotlib | ≤2/10 | | Unmaintained |
| textual | ≤2/10 | | TUI framework, wrong paradigm |
| plotext (base) | ≤2/10 | | Superseded by plotext-plus |

**Key disqualifiers across all libraries:**
- Most print to stdout instead of returning strings (unusable for MCP responses)
- No library supports benchmark-specific annotations (Pareto frontiers, regression markers)
- No library achieves 1/8 Unicode block precision for bars
- No library has 4-tier color degradation with NO_COLOR compliance

## 7. ASCII Charting Architecture

### File Structure and Line Counts

```
benchbox/core/visualization/ascii/
  __init__.py           35 lines
  base.py              494 lines  (core infrastructure)
  bar_chart.py         215 lines
  box_plot.py          340 lines
  comparison_bar.py    286 lines
  diverging_bar.py     248 lines
  heatmap.py           251 lines
  histogram.py         510 lines
  line_chart.py        336 lines
  scatter_plot.py      289 lines
  summary_box.py       361 lines
  ─────────────────────────────
  TOTAL              3,365 lines
```

### Terminal Capability Detection

From `base.py:89-134`:
- Width/height via `shutil.get_terminal_size(fallback=(80, 24))`
- Color mode detection: checks `COLORTERM`, `TERM` env vars, `sys.stdout.isatty()`
- Unicode support: checks `LANG`, `LC_ALL`, `LC_CTYPE` for utf-8
- NO_COLOR: respects `NO_COLOR` environment variable (no-color.org standard)

### Color System: Okabe-Ito Colorblind-Friendly Palette

```python
DEFAULT_PALETTE = (
    "#1b9e77",  # teal
    "#d95f02",  # orange
    "#7570b3",  # purple
    "#e7298a",  # magenta
    "#66a61e",  # green
    "#e6ab02",  # yellow/gold
    "#a6761d",  # brown
    "#666666",  # gray
)
```

Mapped to 256-color: `36, 166, 97, 162, 70, 178, 130, 242`
Mapped to 16-color: `6, 3, 5, 5, 2, 3, 3, 8`

### 4-Tier Color Degradation

| Tier | Mode | ANSI Escape | Colors |
|---|---|---|---|
| 1 | TRUECOLOR | `\033[38;2;R;G;Bm` | 16.7M (24-bit RGB) |
| 2 | EXTENDED | `\033[38;5;Nm` | 256 (lookup table + 6x6x6 cube) |
| 3 | BASIC | `\033[3Nm` | 16 (ANSI standard) |
| 4 | NONE | `""` (empty string) | 0 (no color output) |

### Unicode Block Characters (1/8 Precision)

**Horizontal bars**: `" ▏▎▍▌▋▊▉█"` (9 levels, U+258F through U+2588)
**Vertical bars**: `" ▁▂▃▄▅▆▇█"` (9 levels, U+2581 through U+2588)
**ASCII fallback**: `" .-=+#@"` (7 levels)

**Box drawing**: `─│┌┐└┘├┤┬┴┼` (Unicode) -> `+-+++++++` (ASCII)
**Intensity**: `" ░▒▓█"` (Unicode) -> `" .-=#"` (ASCII)

### The render() -> str Contract

```python
class ASCIIChartBase(ABC):
    @abstractmethod
    def render(self) -> str:
        """Render the chart as a string."""
```

All 9 chart types implement this. Charts return strings, enabling:
- MCP tool responses (JSON serialization)
- Test assertions (no stdout capture)
- Composition (embedding charts in larger outputs)
- File writing without stream redirection

## 8. MCP Integration: Before vs After

### Old (HTML Path)

```python
# MCP tool returned file paths
return {
    "status": "generated",
    "chart_type": "performance_bar",
    "format": "html",
    "file_path": "benchmark_runs/charts/performance_bar_20260213.html",
    "file_name": "performance_bar_20260213.html",
}
# LLM had to: call Read() to open the HTML file, then parse HTML
```

### New (ASCII Path)

```python
# MCP tool returns inline content
return {
    "status": "generated",
    "chart_type": "performance_bar",
    "format": "ascii",
    "content": "... complete rendered chart ...",
    "note": "ASCII chart rendered inline.",
}
# LLM sees the chart immediately in the tool response
```

**Workflow reduction**: 2 steps (generate -> read file) -> 1 step (generate returns content)

### Post-Run Automatic Summary

After `benchbox run` completes, automatically renders:
1. **Summary box**: Aggregate stats (geo mean, median, total, best/worst queries, environment)
2. **Query histogram**: Per-query vertical bars with best/worst highlighting

Both returned inline in MCP response as `summary_charts` dict, or printed directly to console in CLI.

## 9. Sample ASCII Chart Outputs

### Summary Box
```
┌────────────────────────────────────────────────────────────────────────────┐
│                         TPC-H on DuckDB (SF 0.01)                          │
├──────────────────────────────────────────┬─────────────────────────────────┤
│ Geo Mean:  15.1ms                        │ OS: Darwin 25.2.0               │
│ Median:    14.6ms                        │ Python: 3.12.11                 │
│ Total:     92.2ms                        │ CPUs: 10 (arm64)                │
│ Queries:   6                             │ Memory: 16 GB                   │
├──────────────────────────────────────────┴─────────────────────────────────┤
│ Best:  Q17 (11.2ms), Q14 (13.2ms), Q6 (14.5ms)                           │
│ Worst: Q10 (20.5ms), Q1 (18.0ms), Q3 (14.8ms)                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### Box Plot
```
                Query Time Distribution (Execution Time (ms))
                       TPC-H | SF=sf001 | DuckDB 1.4.3
──────────────────────────────────────────────────────────────────────────────

        ╷   ┌────┬──────────┐                ╷
DuckDB  ├───│    │          │────────────────┤                          o  o
        ╵   └────┴──────────┘                ╵

        ────────────────────────────────────────────────────────────────────
        9                               22.5                              36
                            Execution Time (ms) →

Statistics:
  DuckDB: median=13, mean=15.4, std=7.3
```

### Performance Bar
```
                 Performance Comparison (Execution Time (ms))
                       TPC-H | SF=sf001 | DuckDB 1.4.3
──────────────────────────────────────────────────────────────────────────────
DuckDB █████████████████████████████████████████████████████████████      264
```

## 10. Key Narrative Angles

### "Not anti-Plotly"
Plotly is excellent for dashboards, notebooks, web apps. But a CLI benchmarking tool that talks to LLMs through MCP needs inline content, not file paths. The mismatch was contextual, not qualitative.

### "Evaluated before building"
We didn't start with NIH syndrome. We started with Plotly (the obvious choice), recognized the mismatch, evaluated 10+ terminal alternatives, scored them against specific requirements, and only built custom when the evaluation said "build."

### "Same-day proof"
Three new comparison chart types (comparison_bar, diverging_bar, summary_box) were added 6 minutes before Plotly removal. Under the old dual model, these would have required 2x the implementation work. The single-pipeline architecture immediately paid for itself.

### "The importorskip pattern"
Three Plotly test files used `pytest.importorskip("plotly")`. In environments without Plotly installed, these tests silently skipped. CI was green, but the code was untested. This is a subtle anti-pattern: silent skipping hides dead code.

### Honest trade-off
We lost HTML/PNG/SVG export. Users needing publication-quality charts must export data and use their own tools. For a CLI benchmarking tool, this is the right trade-off, but worth acknowledging explicitly.

## References & Resources

### Primary (Our Own Implementation)
- ASCII charting module: `benchbox/core/visualization/ascii/`
- MCP tool: `benchbox/mcp/tools/visualization.py`
- Post-run summary: `benchbox/core/visualization/post_run_summary.py`
- Plotly removal decision: `_project/DONE/core-functionality/active/drop-plotly-html-charts.yaml`
- Library evaluation: `_project/DONE/core-functionality/planning/enhance-ascii-charting.yaml`

### External References
- [NO_COLOR standard](https://no-color.org/) - Environment variable convention for disabling color
- [Okabe-Ito palette](https://jfly.uni-koeln.de/color/) - Colorblind-friendly palette research
- [Unicode Block Elements](https://en.wikipedia.org/wiki/Block_Elements) - U+2580-U+259F character reference
- plotext-plus: Terminal plotting library (closest competitor, scored 7/10)
- plotille: Terminal plotting with string output support
