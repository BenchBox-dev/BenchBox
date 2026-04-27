# Why We Deleted Plotly and Wrote Our Own ASCII Charts

> A benchmarking CLI that generates HTML files nobody opens is a benchmarking CLI with dead code.

**TL;DR**: We removed Plotly (46 MB, dual rendering pipelines, 4,300 lines deleted) and replaced it with 3,365 lines of zero-dependency ASCII charting that renders inline in terminals, CI logs, and LLM tool responses. We evaluated 10+ terminal charting libraries first. None met our requirements for string output, sub-character precision, and terminal color degradation.

---

## Metadata

```yaml
title: "Why we deleted Plotly and wrote our own ASCII charts"
series: building-benchbox
post_number: 1
type: architecture-design
target_length: 2,000-2,500 words
tags: [benchbox, visualization, ascii, plotly, cli, mcp, architecture, dependencies]
```

---

## Outline

### 1. The Problem: Charts Nobody Looked At (~300 words)

**Thesis**: BenchBox had a fully functional Plotly-based visualization pipeline that generated beautiful HTML charts. Nobody used it.

**Key evidence** (all verified in codebase):
- 6 Plotly chart classes (626 lines in charts.py), theme system (137 lines in styles.py), HTML/PNG/SVG/PDF export
- **No `webbrowser.open()`** anywhere in the codebase: HTML files landed in `benchmark_runs/charts/` and sat there
- **No HTTP server**: users had to manually navigate to the directory and open files
- **No CI integration**: no workflow generated or validated HTML charts
- **MCP returned file paths**: `{"file_path": "benchmark_runs/charts/performance_bar_20260213.html"}`. An LLM can't render HTML in a terminal conversation. Two-step workflow: generate chart, then Read() to see the file
- **3 test files used `pytest.importorskip("plotly")`**: in environments without Plotly (most CI, most installs), these tests silently skipped. CI was green, but the code was untested
- **Blog workflow skill** didn't reference chart generation

**MCP contrast to show** (before/after code snippets):

Before (HTML):
```json
{"status": "generated", "format": "html",
 "file_path": "benchmark_runs/charts/performance_bar.html"}
```

After (ASCII):
```json
{"status": "generated", "format": "ascii",
 "content": "┌──────────────────────────────┐\n│ DuckDB █████████ 264ms       │\n└──────────────────────────────┘"}
```

**Tone**: Honest self-critique. We built the "obvious" thing (Plotly is great!) for the wrong context (a CLI tool with MCP integration).

---

### 2. The Dependency Tax (~400 words)

**Thesis**: Plotly wasn't just unused code; it was actively expensive to maintain.

**a) Size and install friction** (verified from pyproject.toml history):
- plotly: ~43 MB (removed from 4 dependency groups: `viz`, `all`, `mcp`, `dev`)
- narwhals: ~3.3 MB (Plotly's dataframe compatibility layer)
- kaleido: Chrome binary for static image export (already removed earlier, signaling trajectory)
- Total optional dependency weight: ~46 MB for charts nobody opened
- ASCII implementation adds: 0 bytes of external dependencies

**b) The dual data model problem** (verified from codebase):

| Plotly Model | ASCII Model | Chart Type |
|---|---|---|
| BarDatum | BarData | Bar chart |
| TimeSeriesPoint | LinePoint | Line chart |
| CostPerformancePoint | ScatterPoint | Scatter plot |
| DistributionSeries | BoxPlotSeries | Box plot |
| QueryLatencyDatum | HistogramBar | Histogram |

A conversion layer in `exporters.py` translated between them. Every new chart type: implement twice, test twice, maintain two code paths. This is the complexity that makes contributors hesitate.

**c) Maintenance surface area** (verified from git diff dd35df9e):
- 783 lines of Plotly-specific source (charts.py: 626, styles.py: 137, dependencies.py: 20)
- 801 lines of Plotly-specific tests across 4 files
- ~725 lines in shared files serving the dual pipeline
- Format branching in MCP tools and CLI commands
- 4 example Jupyter notebooks (297 lines) and a doc image generator script (430 lines)
- **Total removed: 4,300 lines across 42 files (12 files deleted entirely)**

**Framing**: Not anti-Plotly. Plotly excels at dashboards, notebooks, web apps. A CLI benchmarking tool that talks to LLMs through MCP needs a different approach.

---

### 3. Why Not Just Use a Terminal Charting Library? (~500 words)

**Thesis**: Before writing our own, we evaluated 10+ terminal charting libraries. None fit BenchBox's specific requirements.

**Our 5 requirements**:
1. **`render() -> str`**: Must return a string, not print to stdout (needed for MCP JSON responses, test assertions, composition)
2. **Benchmark-specific annotations**: Best/worst markers, % change labels, Pareto frontiers, regression highlighting
3. **Sub-character bar precision**: 1/8 Unicode block rendering (`▏▎▍▌▋▊▉█`, 9 levels)
4. **4-tier terminal color degradation**: truecolor (24-bit) -> 256-color -> 16-color -> none, with NO_COLOR compliance
5. **Zero additional dependencies**: A benchmarking tool that's slow or bloated undermines its own credibility

**Evaluation matrix** (from _project/DONE/core-functionality/planning/enhance-ascii-charting.yaml):

| Library | render->str | Precision | Color Degradation | Deps | Score |
|---|:-:|:-:|:-:|:-:|:-:|
| plotext-plus | Needs wrapper | Good | Basic | numpy | 7/10 |
| plotille | Yes | Low | 256 only | 0 | 4/10 |
| termgraph | No (stdout) | Low | Basic | 0 | 3/10 |
| uniplot | No (stdout) | Medium | Basic | numpy | 3/10 |
| rich | N/A | N/A | Good | rich | 2/10 |
| asciichartpy | Yes | Low | None | 0 | 2/10 |
| drawille | Yes | Braille | None | 0 | 2/10 |
| bashplotlib | No | Low | None | 0 | ≤2/10 |
| textual | N/A | N/A | Good | textual | ≤2/10 |
| plotext (base) | No | Good | Basic | 0 | ≤2/10 |

**The closest competitor**: plotext-plus scored 7/10 but still needed stdout-to-string capture wrappers, custom annotation overlays for benchmark markers, and regression highlighting. Plus one more dependency (numpy).

**Key disqualifiers across all libraries**:
- Most print to stdout (unusable for MCP JSON responses)
- None support benchmark-specific annotations
- None achieve 1/8 block precision
- None have 4-tier color degradation with NO_COLOR compliance

**Framing**: Not NIH syndrome. We evaluated with specific criteria, scored each library, measured the gap. The evaluation is what makes "build" defensible. Show the matrix, not just the conclusion.

---

### 4. What We Built: 9 Chart Types, Zero Dependencies (~500 words)

**Thesis**: The ASCII charting system is purpose-built for benchmarking output in terminal and LLM contexts.

**Architecture** (3,365 lines across 11 files):
- `base.py` (494 lines): terminal detection, 4-tier color system, Unicode/ASCII fallback, `ASCIIChartBase` abstract class
- 9 chart type files (215-510 lines each), all implementing `render() -> str`

**Chart types** (show 2-3 inline examples):

1. **Summary box** (stats panel with environment info):
```
┌──────────────────────────────────────────────────────────────────────┐
│                      TPC-H on DuckDB (SF 0.01)                       │
├──────────────────────────────────┬───────────────────────────────────┤
│ Geo Mean:  15.1ms                │ OS: Darwin 25.2.0                 │
│ Median:    14.6ms                │ CPUs: 10 (arm64)                  │
│ Total:     92.2ms                │ Memory: 16 GB                     │
├──────────────────────────────────┴───────────────────────────────────┤
│ Best:  Q17 (11.2ms), Q14 (13.2ms), Q6 (14.5ms)                     │
│ Worst: Q10 (20.5ms), Q1 (18.0ms), Q3 (14.8ms)                      │
└──────────────────────────────────────────────────────────────────────┘
```

2. **Box plot** (distribution with quartiles and outliers):
```
        ╷   ┌────┬──────────┐                ╷
DuckDB  ├───│    │          │────────────────┤                    o  o
        ╵   └────┴──────────┘                ╵
        9                               22.5                       36
```

3. **Query histogram** (per-query vertical bars, auto-splits at 33 queries):
```
   20.5 ██                    ← Q10 highlighted as worst
        ██ ▄▄ ▃▃ ██ ·· ··
   10.2 ██ ██ ██ ██ ██ ██
        Q1 Q3 Q6 Q10 Q14 Q17
```

Plus: performance bar, heatmap, scatter plot (with Pareto frontier), line chart, comparison bar (paired with % change), diverging bar (centered-zero regression/improvement).

**5 key design decisions**:
- **Okabe-Ito colorblind-friendly palette**: 8 research-backed colors (`#1b9e77`, `#d95f02`, `#7570b3`, ...), mapped to 256-color and 16-color fallbacks
- **4-tier color degradation**: Detects `COLORTERM`/`TERM` env vars, falls back gracefully. NO_COLOR env var disables all color (no-color.org standard)
- **1/8 block precision**: Horizontal bars use `▏▎▍▌▋▊▉█` (9 levels), vertical bars use `▁▂▃▄▅▆▇█`, ASCII fallback: `.-=+#@`
- **Width-constrained**: 40-120 characters (readability over space-filling)
- **Auto post-run summary**: After `benchbox run`, automatically prints summary box + query histogram

**Integration (single-step in all contexts)**:
- CLI: `benchbox visualize results.json` renders inline
- MCP: `generate_chart()` returns content in `"content"` field (not file paths)
- Post-run: automatic charts after `benchbox run` completes
- CI: no ANSI if stdout is not a TTY

---

### 5. The Results: Before and After (~300 words)

**What we deleted** (commit dd35df9e, Feb 6, 2026):
- 4,300 lines across 42 files (12 files deleted entirely)
- 46 MB of optional dependencies
- Dual data model + conversion layer
- Format branching in MCP tools and CLI
- Silent test skipping (`pytest.importorskip`)

**What we simplified**:
- One rendering pipeline instead of two
- One data model (ASCII models are canonical)
- MCP always returns inline content
- New chart types require one implementation, not two

**Same-day proof**: Three new comparison chart types (comparison_bar, diverging_bar, summary_box) were committed 6 minutes before Plotly removal (812d2bd2 at 12:45 PM, dd35df9e at 12:51 PM). Under the old dual model, those would have required 2x implementation. The single-pipeline architecture paid for itself on day one.

**Code stats**:

| Metric | Before (Plotly + ASCII) | After (ASCII only) |
|---|---|---|
| Rendering pipelines | 2 | 1 |
| Data model hierarchies | 2 (with conversion layer) | 1 (canonical) |
| Chart types | 6 (Plotly) + 6 (ASCII) | 9 (ASCII, 3 new) |
| Visualization source lines | ~5,400+ | ~3,365 |
| External dependencies | plotly, narwhals, (kaleido) | 0 |
| Test strategy | importorskip (silent skip) | Always runs |

**Honest trade-off**: We lost HTML/PNG/SVG export. Users needing publication-quality charts must export data and use their own visualization tool. For a CLI benchmarking tool with MCP integration, we think this is the right call, but worth stating explicitly.

---

### 6. Lessons for CLI Tool Builders (~300 words)

**5 takeaways**:

1. **Output format should match consumption context**. HTML is great when users have browsers. Terminal tools need terminal output. LLM integrations need inline content. We had a mismatch.

2. **Evaluate before you build, but build when evaluation says so**. We started with Plotly (the obvious choice), recognized the mismatch, evaluated 10+ alternatives with a scoring matrix, and built custom only when the data said "build." The evaluation makes the decision defensible.

3. **Dual rendering pipelines are a maintenance trap**. Two output formats means every feature costs 2x. Be intentional about which formats you support. Be willing to drop one.

4. **Silent test skipping hides dead code**. `pytest.importorskip("plotly")` meant CI was green but the code was untested in most environments. If tests skip silently, you won't notice when the code they cover stops being relevant.

5. **Dependencies cost more than disk space**. 46 MB is the headline number, but the real cost was the conversion layers, branching logic, dual models, container compatibility issues, and contributor confusion.

**Closing**: We're not anti-dependency. BenchBox uses DuckDB, Click, Rich, and plenty of other libraries. Each one earns its place by being used in every run, not sitting in an optional extra that generates files nobody opens.

---

## Research Status

- [x] Exact line counts from git diff for Plotly removal commit (dd35df9e: -4,300 / +918, 42 files, 12 deleted)
- [x] Before/after MCP tool response (file path vs inline content, from git history)
- [x] Library evaluation details (10+ libraries, scores, gaps, from enhance-ascii-charting.yaml)
- [x] ASCII architecture details (3,365 lines, 4-tier color, Okabe-Ito palette, 1/8 block precision)
- [x] Timeline (28 hours from ASCII intro to Plotly removal)
- [x] Representative ASCII chart outputs (summary box, box plot, histogram from live run)
- [x] Evidence points for "HTML was unused" (7 evidence points from decision document)
- [x] Dual data model mapping table (5 model pairs)
- [x] Dependency weight breakdown (plotly 43MB, narwhals 3.3MB, kaleido variable)

## Visual Elements for Draft

1. **MCP response contrast** (section 1): before/after JSON showing file_path vs content
2. **Dual data model table** (section 2): 5 rows mapping Plotly models to ASCII models
3. **Library evaluation matrix** (section 3): 10 rows, 5 criteria columns
4. **Inline ASCII chart examples** (section 4): summary box, box plot, histogram snippet
5. **Before/after stats table** (section 5): pipelines, models, types, lines, deps

## Cross-References

- Decision document: `_project/DONE/core-functionality/active/drop-plotly-html-charts.yaml`
- Library evaluation: `_project/DONE/core-functionality/planning/enhance-ascii-charting.yaml`
- Implementation: `benchbox/core/visualization/ascii/` (3,365 lines)
- Full research: `_blog/building-benchbox/research/plotly-removal-research.md`

## Conflicts Check

- No overlap with analytics-architecture (database design patterns)
- No overlap with benchbox-in-action (using the tool for benchmarking)
- No overlap with free-trial-benchmarking or cloud-cost-controls (cloud platforms)
- Potential complement to a future "BenchBox MCP integration" post
