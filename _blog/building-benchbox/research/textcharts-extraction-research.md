# Research: Extracting textcharts from BenchBox

## Key Numbers

| Metric | Value | Source |
|--------|-------|--------|
| textcharts source | 7,559 lines, 19 modules | `~/Developer/textcharts/src/textcharts/` |
| textcharts test suite | 7,622 lines, 591 methods, 26 files | `~/Developer/textcharts/tests/` |
| Chart types | 15 | BarChart through RankTable |
| BenchBox test file (before) | ~4,500 lines, ~360 methods | `test_ascii_charts.py` pre-extraction |
| BenchBox test file (after) | 770 lines, ~65 methods, 13 classes | `test_ascii_charts.py` post-extraction |
| Test methods moved | ~290 (46 test classes) | Pure rendering tests |
| BenchBox shim modules | 60 lines total, 17 files | `benchbox/core/visualization/ascii/*.py` |
| `ascii_api.py` facade | 22 lines | `benchbox/core/visualization/ascii_api.py` |
| Golden snapshot fixtures | 15 files, ~120K | `~/Developer/textcharts/tests/fixtures/golden/ascii/` |
| External dependencies | 0 | stdlib only |
| Work items completed | 4 major | Test migration, API renames, de-benchboxing, neutral defaults |
| Timeline | ~5 days (Mar 5-10, 2026) | Commit history |

---

## Code Examples for Blog Post

### 1. The "One Import" Problem

The single coupling point that made extraction impossible:

```python
# benchbox/core/visualization/ascii/base.py (BEFORE)
# Inside _get_metadata_subtitle():
sf = self.metadata.get("scale_factor")
if sf is not None:
    from benchbox.utils.scale_factor import format_scale_factor  # <-- BLOCKED EXTRACTION
    parts.append(f"SF={format_scale_factor(sf)}")
```

The fix, callable injection on `ChartOptions`:

```python
# textcharts/base.py (AFTER)
@dataclass
class ChartOptions:
    # ... other fields ...
    scale_factor_formatter: Callable[[float], str] | None = field(default=None, repr=False)
```

BenchBox injects at the call site:

```python
# benchbox/core/visualization/post_run_summary.py
from benchbox.utils.scale_factor import format_scale_factor

options = ChartOptions(
    theme=theme,
    use_color=color,
    use_unicode=unicode,
    scale_factor_formatter=format_scale_factor,  # injected here
)
```

---

### 2. The Benchmark Costume (Field Name Renames)

| Before (BenchBox-specific) | After (generic textcharts) | Model |
|---------------------------|---------------------------|-------|
| `query_id` | `label` | HistogramBar |
| `latency_ms` | `value` | HistogramBar |
| `geo_mean_baseline_ms` | `primary_baseline` | SummaryStats |
| `geo_mean_comparison_ms` | `primary_comparison` | SummaryStats |
| `total_time_ms` | `total_value` | SummaryStats |
| `num_queries` | `num_items` | SummaryStats |
| `best_queries` | `best_items` | SummaryStats |
| `worst_queries` | `worst_items` | SummaryStats |

Factory function renames:

| Before | After | Chart Type |
|--------|-------|-----------|
| `from_query_results()` | `from_series()` | BoxPlot, CDFChart |
| `from_normalized_results()` | `from_ratios()` | NormalizedSpeedup |
| `from_metrics()` | `from_data()` | Histogram |
| `from_heatmap_data()` | `from_matrix()` | Heatmap, RankTable |

Class name renames:

| Before | After |
|--------|-------|
| `ASCIIBarChart` | `BarChart` |
| `ASCIIHistogram` | `Histogram` |
| `ASCIIBoxPlot` | `BoxPlot` |
| `ASCIIChartOptions` | `ChartOptions` |
| `ASCIIChartBase` | `ChartBase` |
| ... (16 classes total) | ... |

---

### 3. Scattered Imports to Facade

**Before** (exporters.py, ~20 deep submodule imports):
```python
from benchbox.core.visualization.ascii.bar_chart import ASCIIBarChart, BarData
from benchbox.core.visualization.ascii.base import ASCIIChartOptions
from benchbox.core.visualization.ascii.box_plot import BoxPlotSeries
from benchbox.core.visualization.ascii.histogram import HistogramBar
from benchbox.core.visualization.ascii.comparison_bar import ASCIIComparisonBar, ComparisonBarData
from benchbox.core.visualization.ascii.diverging_bar import ASCIIDivergingBar, DivergingBarData
# ... 13+ submodules imported individually
```

**After** (single facade import):
```python
from benchbox.core.visualization.ascii_api import (
    BarChart, BarData, BoxPlot, ChartOptions,
    Histogram, HistogramBar, ComparisonBar,
    # ... all from one module
)
```

5 callers consolidated: CLI, MCP tools, exporters, post_run_summary, chart_generator.

---

### 4. Cross-Layer Cycle

**Before** (chart_generator.py imported from MCP layer):
```python
# benchbox/core/visualization/chart_generator.py
from benchbox.mcp.tools.visualization import _render_single_ascii_chart  # viz -> MCP!
```

**After** (direct call through facade):
```python
from benchbox.core.visualization.ascii_api import ChartOptions, render_ascii_chart_from_results
```

---

### 5. Explicit Data Transformation (The Payoff)

The conversion from BenchBox domain objects to generic textcharts data is now visible:

```python
# benchbox/core/visualization/ascii_runtime.py
def _render_query_histogram(results, options, subtitle):
    # EXPLICIT: BenchBox domain (query_id, execution_time_ms)
    #         -> textcharts domain (label, value)
    for (platform, query_id), timings in query_timings.items():
        mean_latency = sum(timings) / len(timings)
        histogram_data.append(
            HistogramBar(label=query_id, value=mean_latency, platform=platform)
        )
```

Previously the chart classes directly consumed benchmark-shaped data via field names. Now the mapping is explicit, testable, and documented.

---

### 6. Compatibility Shims

Each of BenchBox's 17 shim files is ~3 lines:

```python
"""Compatibility shim - delegates to textcharts.histogram."""

from textcharts.histogram import *  # noqa: F401, F403
```

The package `__init__.py`:

```python
"""Compatibility shim - all implementations live in textcharts."""

from textcharts import *  # noqa: F401, F403
from textcharts import __all__ as _textcharts_all

__all__ = list(_textcharts_all)
```

---

### 7. Golden Snapshot Test Pattern

```python
# textcharts/tests/test_golden_output.py
GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "golden" / "ascii"
OPTS = ChartOptions(use_color=False, use_unicode=True, width=80)

def _bar_chart() -> tuple[str, str]:
    data = [
        BarData(label="DuckDB", value=1234.5, is_best=True),
        BarData(label="SQLite", value=3456.7, is_worst=True),
        BarData(label="Polars", value=2100.0),
    ]
    chart = BarChart(data=data, title="Total Runtime", metric_label="ms", options=OPTS)
    return "bar_chart", chart.render()

@pytest.mark.parametrize("name,rendered", [_bar_chart(), _histogram(), ...])
def test_golden_output(name, rendered, update_golden):
    """Verify byte-identical output against golden snapshots."""
```

15 parametrizations, one per chart type. Byte-for-byte comparison.

---

### 8. Try It Yourself

**Install:**
```bash
pip install textcharts
```

**Python:**
```python
from textcharts import BarChart, BarData

data = [
    BarData(label="Python", value=89.5),
    BarData(label="Rust", value=95.2),
    BarData(label="Go", value=78.0),
]
print(BarChart(data=data, title="Language Benchmark").render())
```

**CLI:**
```bash
echo '[{"label":"Python","value":89.5},{"label":"Rust","value":95.2}]' \
  | textcharts bar --title "Benchmarks"
```

**MCP (Claude Desktop):**
```json
{
  "mcpServers": {
    "textcharts": {"command": "textcharts-mcp"}
  }
}
```

**Links:**
- PyPI: `textcharts` (v0.1.3)
- GitHub: `joeharris76/textcharts`

---

## Narrative Arc for Blog Post

**Post #1** ("Why We Deleted Plotly") asked: _Where do benchmark charts get read?_ Answer: terminals and LLMs. So we built ASCII charts.

**This post** asks: _What happens when you give internal code its own identity?_ Answer: You discover assumptions baked into naming and coupling. The extraction itself is a design tool.

Key beats:
1. The code was general-purpose but wearing a benchmark costume
2. One import blocked extraction (the "one import" problem)
3. Preparing for extraction improved BenchBox before we extracted anything
4. The API renames forced explicit data transformation
5. The test suite got smaller AND more focused
6. The cross-layer cycle would have stayed hidden without the extraction forcing a full import trace

---

*Research compiled: 2026-03-10*
