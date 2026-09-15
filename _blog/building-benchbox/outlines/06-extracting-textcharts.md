# Outline: Extracting textcharts from BenchBox

**Series**: Building BenchBox (#6)
**Type**: Architecture/Design
**Tags**: [benchbox, textcharts, extraction, open-source, refactoring, architecture, dependencies]
**Target Length**: 1,500-2,500 words
**Audience**: Developers considering extracting libraries from monoliths, open-source maintainers, BenchBox users

**Thesis**: Extracting our ASCII charting code into an independent library forced API improvements we wouldn't have made otherwise, and the extraction process itself revealed coupling we didn't know existed.

**Relationship to Post #1**: Post #1 ("Why We Deleted Plotly") covered _why_ we built ASCII charts. This post covers what happened when we gave them their own home.

**Research**: `research/textcharts-extraction-research.md`

---

## Hook

> The best refactoring happens when you try to explain your code to someone who doesn't share your assumptions.

**TL;DR**: We extracted BenchBox's 7,500-line ASCII charting system into `textcharts`, a standalone zero-dependency library on PyPI. The extraction forced us to rename benchmark-specific APIs to generic ones, decouple a hidden dependency we'd overlooked, and move ~290 test methods out of BenchBox. The result: a cleaner BenchBox and a charting library anyone can use.

---

## Section 1: The Problem (~250 words)

**Why extract at all?**

- Post #1 told the story of building ASCII charts. By March 2026, the system had grown to 15 chart types across 19 modules (~7,500 lines)
- The code had zero external dependencies and no real coupling to BenchBox's core, except it was trapped inside BenchBox's package hierarchy
- Three motivations:
  1. **Reuse**: Other projects (MCP servers, CLI tools, dashboards) could use terminal charts, but not if they required installing a benchmarking framework
  2. **Maintenance boundary**: Rendering bugs vs. benchmarking bugs were mixed in the same issue tracker and test suite (~4,500 lines of interleaved tests)
  3. **API honesty**: Class names like `ASCIIBarChart` and field names like `query_id` revealed that we'd built a general-purpose library wearing a benchmark-shaped costume

**Key evidence**: The `ascii/` package had zero runtime dependencies (pure stdlib). The only thing keeping it inside BenchBox was a single import and benchmark-shaped naming.

---

## Section 2: What the Code Looked Like Before (~400 words)

**The benchmark costume**

Show the original module structure: 16 files under `benchbox/core/visualization/ascii/`

Highlight the naming problem with a table:

| Layer | BenchBox Name | What It Actually Was |
|-------|---------------|---------------------|
| Class | `ASCIIBarChart` | A bar chart renderer |
| Class | `ASCIIHistogram` | A histogram renderer |
| Field | `HistogramBar.query_id` | A label |
| Field | `HistogramBar.latency_ms` | A value |
| Field | `SummaryStats.num_queries` | An item count |
| Field | `SummaryStats.best_queries` | Best items |
| Factory | `from_query_results()` | `from_series()` |
| Factory | `from_normalized_results()` | `from_ratios()` |
| Factory | `from_heatmap_data()` | `from_matrix()` |

**The single hidden coupling** (code example):
```python
# benchbox/core/visualization/ascii/base.py
sf = self.metadata.get("scale_factor")
if sf is not None:
    from benchbox.utils.scale_factor import format_scale_factor  # <-- ONE IMPORT
    parts.append(f"SF={format_scale_factor(sf)}")
```
One import. That's all it took to make the entire 7,500-line package non-extractable.

**Scattered callers**: 5 different modules made ~28 deep submodule imports, each reaching into specific chart files:
- `exporters.py`: ~20 deep imports across 13+ submodules
- `post_run_summary.py`: 6 imports
- CLI, MCP tools, chart generator: 2 imports each

---

## Section 3: The Extraction Strategy (~500 words)

**Three phases, not a big bang**

**Phase A: Prepare the boundary** (in-tree, no new package)
- Created `ascii_api.py` facade (22 lines): consolidated 28 deep imports from 5 callers into a single public surface
- Decoupled `format_scale_factor` via callable injection:
  ```python
  @dataclass
  class ChartOptions:
      scale_factor_formatter: Callable[[float], str] | None = field(default=None, repr=False)
  ```
  BenchBox injects its formatter at the call site; textcharts falls back to `f"SF={sf}"`.
- Built golden snapshot tests for all 15 chart types: byte-identical baselines to catch any rendering drift
- Key insight: _preparing_ for extraction improved BenchBox's architecture before we extracted anything

**Phase B: Extract and shim**
- Scaffolded standalone `textcharts` package with src layout, `py.typed`, zero dependencies
- Dropped the `ASCII` prefix: `ASCIIBarChart` became `BarChart`, `ASCIIChartOptions` became `ChartOptions` (16 classes renamed)
- Replaced BenchBox's `ascii/` modules with thin re-export shims, each ~3 lines:
  ```python
  """Compatibility shim - delegates to textcharts.histogram."""
  from textcharts.histogram import *  # noqa: F401, F403
  ```
- 568 tests passed without modification on the first try, because the shims preserved every import path

**Phase C: De-BenchBox the API** (the unexpected payoff)
- Once the library stood alone, benchmark-specific naming looked wrong:
  - `HistogramBar.query_id` became `.label`; `.latency_ms` became `.value`
  - `SummaryStats.num_queries` became `.num_items`; `.geo_mean_baseline_ms` became `.primary_baseline`
  - `from_query_results()` became `from_series()`; `from_normalized_results()` became `from_ratios()`
- Each rename forced BenchBox to make its data transformation explicit:
  ```python
  # benchbox/core/visualization/ascii_runtime.py (AFTER)
  # EXPLICIT: BenchBox domain -> generic textcharts domain
  histogram_data.append(
      HistogramBar(label=query_id, value=mean_latency, platform=platform)
  )
  ```

---

## Section 4: What Improved in BenchBox (~400 words)

**The extraction made BenchBox better, not just smaller**

**Cleaner ownership boundary**:
- textcharts owns: rendering, terminal detection, Unicode/color support, data visualization primitives
- BenchBox owns: `NormalizedResult` conversion, chart dispatch, file export, CLI/MCP integration
- The line between "what to show" and "how to show it" became a real API contract

**Smaller, more focused test suite**:
- ~290 pure-rendering test methods moved to textcharts (46 test classes)
- BenchBox's `test_ascii_charts.py` shrank from ~4,500 lines to 770 lines
- Remaining ~65 tests in 13 classes cover integration: "does BenchBox pass the right data to charts?"
- Previously, a rendering bug and a data-conversion bug looked identical in test output

**Eliminated a cross-layer cycle**:
- Discovered during extraction: `chart_generator.py` imported `_render_single_ascii_chart` from `benchbox.mcp.tools.visualization` (visualization layer importing from the MCP layer)
- Extraction forced us to trace every import; that cycle would have stayed hidden otherwise
- Fix: chart_generator now calls `render_ascii_chart_from_results` directly through the facade

**Explicit data transformation**:
- Before: chart classes silently accepted benchmark-shaped data via field names like `query_id`
- After: BenchBox's dispatch layer explicitly maps `query_id` to `label`, `latency_ms` to `value`
- The mapping is visible, testable, and documented in `ascii_runtime.py`

---

## Section 5: What We Learned (~300 words)

Five takeaways, each with concrete evidence:

1. **Extraction is a design tool, not just a packaging exercise**: The act of making code standalone reveals assumptions baked into naming, imports, and data shapes. We found coupling we didn't know we had.

2. **The "one import" problem**: A single cross-boundary import (`format_scale_factor`) blocked extraction of 7,500 lines. Scanning for explicit dependencies isn't enough; you need to trace every import chain.

3. **Golden snapshots build confidence**: Byte-identical rendering tests (15 fixtures, one per chart type) let us refactor aggressively without worrying about visual regressions. We ran them at every phase boundary.

4. **Compatibility shims buy time**: 17 thin re-export modules (60 lines total) let BenchBox's existing code work during the transition. We'll deprecate them later, but they eliminated the "big bang" migration risk.

5. **Generic naming is a forcing function**: Renaming `query_id` to `label` sounds trivial. But propagating that change through the codebase forced us to identify every place BenchBox assumes "this chart shows benchmark queries," and that assumption wasn't always correct.

---

## Section 6: Try It Yourself (~150 words)

**Install:**
```bash
pip install textcharts
```

**Quick example:**
```python
from textcharts import BarChart, BarData

data = [
    BarData(label="Python", value=89.5),
    BarData(label="Rust", value=95.2),
    BarData(label="Go", value=78.0),
]
print(BarChart(data=data, title="Language Benchmark").render())
```

**CLI one-liner:**
```bash
echo '[{"label":"Python","value":89.5},{"label":"Rust","value":95.2}]' \
  | textcharts bar --title "Benchmarks"
```

**MCP server** (for Claude Desktop or other AI tools):
```json
{
  "mcpServers": {
    "textcharts": {"command": "textcharts-mcp"}
  }
}
```

**BenchBox users**: already using it. textcharts is a dependency as of v0.1.4.

**Links**: PyPI (`textcharts` v0.1.3), GitHub (`joeharris76/textcharts`)

---

## References & Resources

- Post #1: "Why We Deleted Plotly and Wrote Our Own ASCII Charts" (building-benchbox series)
- textcharts on PyPI: https://pypi.org/project/textcharts/
- ADR: `docs/development/adr/adr-textcharts-extraction.md`
- Research notes: `research/textcharts-extraction-research.md`

---

*Outline created: 2026-03-10*
*Research completed: 2026-03-10*
