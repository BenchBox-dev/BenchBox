# textcharts: Complete neutralization of domain-specific defaults

## Context

textcharts was extracted from BenchBox (a SQL benchmarking framework) and still
carries benchmark-specific assumptions in default labels, titles, color semantics,
and factory function names. A generic charting library should not know what
"Execution Time (ms)" means, should not assume negative percentage change means
"improvement," and should not name factories after query benchmarking concepts.

BenchBox already passes all labels and titles explicitly at every call site — the
risk is that textcharts defaults are wrong when a non-BenchBox caller omits them.

### What's already done

- Subtitle migration: `metadata: dict` → `subtitle: str | None` (complete)
- `value_formatter` on SummaryStats and StackedBar (complete, Group 2)
- `_format_metric()` dispatch in SummaryBox (complete, Group 2)
- Clean class aliases (BarChart, Histogram, etc.) exported alongside ASCII* names

### What remains (this prompt)

- **Group 1**: Neutralize default labels and titles
- **Group 3**: Add `lower_is_better` parameter for improvement direction
- **Group 4**: Rename factory functions to generic names with deprecated aliases

Group 5 (configurable outlier capping) is deferred and not covered here.

## Guiding principles

- **Every change must be backward-compatible.** No existing caller should break.
  Achieve this by changing defaults to neutral values and ensuring BenchBox
  (the primary caller) already passes explicit values for everything affected.
- **Run the full test suite after each change group.** Golden snapshot tests
  will need regeneration — use `--update-golden` when the visual change is
  intentional and correct.
- **One commit per change group.** Don't bundle unrelated changes.

---

## Change Group 1: Neutralize default labels and titles

These constructor parameters and factory functions have benchmark-specific
default values. Change them to generic alternatives.

### Constructor label defaults

| File | Line | Parameter | Current default | New default |
|------|------|-----------|----------------|-------------|
| `histogram.py` | 65 | `y_label` | `"Execution Time (ms)"` | `"Value"` |
| `comparison_bar.py` | 62 | `metric_label` | `"Execution Time (ms)"` | `"Value"` |
| `percentile_ladder.py` | 104 | `metric_label` | `"ms"` | `""` |
| `scatter_plot.py` | 58 | `x_label` | `"Cost (USD)"` | `"X"` |
| `scatter_plot.py` | 59 | `y_label` | `"Performance"` | `"Y"` |
| `stacked_bar.py` | 76 | `metric_label` | `"ms"` | `""` |
| `heatmap.py` | 60 | `value_label` | `"ms"` | `""` |

These constructors are already neutral and need no change:
- `bar_chart.py` — `metric_label` defaults to `"Value"`
- `box_plot.py` — `y_label` defaults to `"Value"`
- `cdf_chart.py` — `x_label` defaults to `"Value"`
- `line_chart.py` — `x_label`/`y_label` default to `"X"`/`"Y"`

### Factory function label defaults

Update factory defaults to match the new constructor defaults:

| File | Function | Parameter | Current default | New default |
|------|----------|-----------|----------------|-------------|
| `histogram.py` | `from_query_latency_data()` | `y_label` | `"Execution Time (ms)"` | `"Value"` |
| `comparison_bar.py` | `from_comparison_data()` | `metric_label` | `"Execution Time (ms)"` | `"Value"` |
| `scatter_plot.py` | `from_cost_performance_points()` | `cost_label` | `"Cost (USD)"` | `"X"` |
| `scatter_plot.py` | `from_cost_performance_points()` | `performance_label` | `"Queries per Hour"` | `"Y"` |
| `line_chart.py` | `from_time_series_points()` | `y_label` | `"Execution Time (ms)"` | `"Y"` |
| `box_plot.py` | `from_distribution_series()` | `y_label` | `"Execution Time (ms)"` | `"Value"` |
| `cdf_chart.py` | `cdf_from_query_results()` | `x_label` | `"Execution Time (ms)"` | `"Value"` |
| `heatmap.py` | `from_matrix()` | `value_label` | `"ms"` | `""` |
| `bar_chart.py` | `from_bar_data()` | `metric_label` | `"Execution Time (ms)"` | `"Value"` |

### Default titles

Change hardcoded chart titles to generic alternatives:

| File | Line | Current default title | New default title |
|------|------|----------------------|-------------------|
| `histogram.py` | 86 | `"Query Latency Histogram"` | `"Histogram"` |
| `diverging_bar.py` | 61 | `"Regression / Improvement Distribution"` | `"Change Distribution"` |
| `percentile_ladder.py` | 110 | `"Percentile Latency by Platform"` | `"Percentile Distribution"` |
| `cdf_chart.py` | 73 | `"Cumulative Distribution of Query Latency"` | `"Cumulative Distribution"` |
| `stacked_bar.py` | 81 | `"Phase Breakdown by Platform"` | `"Stacked Breakdown"` |
| `summary_box.py` | 20 | `"Benchmark Summary"` | `"Summary"` |
| `rank_table.py` | 55 | `"Query Rankings (1st = fastest)"` | `"Rankings (1st = best)"` |

### SummaryStats field comments

Remove the "expected keys" comments that encode BenchBox's schema (lines 51-56
of `summary_box.py`):

```python
# BEFORE (lines 51-57):
    # System environment info (displayed in middle column)
    # Expected keys: "OS", "Python", "CPUs", "Memory"
    environment: dict[str, str] | None = None
    # Platform/run configuration (displayed in right column)
    # Expected keys: "Driver", "Tables", "Tuning"
    platform_config: dict[str, str] | None = None

# AFTER:
    # System environment info (displayed in middle column)
    environment: dict[str, str] | None = None
    # Platform/run configuration (displayed in right column)
    platform_config: dict[str, str] | None = None
```

Verify that the rendering code iterates whatever keys are present rather than
branching on specific key names like "OS" or "Driver".

### stacked_bar.py: metric_label default vs _format_time() fallback

The current `_format_total()` dispatch (line 237) checks:
```python
if self.metric_label.strip().lower() == "ms":
    return self._format_time(value)
```

When you change `metric_label` from `"ms"` to `""`, this will change behavior —
the empty string won't match `"ms"`, so `_format_time()` won't be called. Since
Group 2 already added `value_formatter`, the fallback path for `metric_label=""`
should be `_format_value()` with no suffix (which is the correct generic
behavior). Verify this works correctly and doesn't break existing tests that
rely on default ms formatting.

If existing tests construct StackedBar without passing `metric_label` and expect
ms→s→min formatting, those tests are testing the BenchBox-specific default. They
should either be updated to pass `metric_label="ms"` explicitly or have their
golden output regenerated.

The same logic applies in summary_box.py `_format_metric()` (line 523):
```python
if self.stats.metric_label.strip().lower() == "ms":
    return self._format_time(value)
```

Changing `SummaryStats.metric_label` default from `"ms"` to `""` would break
the fallback to `_format_time()`. **Do NOT change `SummaryStats.metric_label`
default** — it's already correct at `"ms"` and is not a label that appears in
chart output. It's a format hint, not a display label.

Similarly for stacked_bar: the `metric_label` default change from `"ms"` to `""`
needs careful handling. The cleanest approach:

1. Change the _format_total() dispatch to:
   ```python
   if self.metric_label.strip().lower() in ("ms", ""):
       return self._format_time(value)
   ```
   This preserves backward compatibility for callers that don't pass metric_label.
2. OR: Keep metric_label default as `"ms"` (same approach as summary_box).

Choose whichever is more consistent. The key invariant: **a caller that passes
no arguments should get the same output as before.**

### Verification

Run the full test suite. Expect golden snapshot failures for charts that rendered
old default titles/labels without explicit overrides. Regenerate with
`--update-golden` after visual inspection.

BenchBox impact: **None.** BenchBox passes explicit titles, labels, and
`metric_label="ms"` at every call site.

**Commit**: `refactor: neutralize domain-specific default labels and titles`

---

## Change Group 3: Make improvement direction configurable

### Problem

Three chart types hardcode "negative % = improvement (green), positive % =
regression (red)":

- `comparison_bar.py` `_format_annotation()` (line 247): `if pct_change > 0`
  assigns red (#d95f02), else green (#66a61e)
- `diverging_bar.py` `_colorize_sides()` (line 193): `if pct_change < 0` assigns
  green, `if pct_change > 0` assigns red
- `summary_box.py` `_format_pct_colored()`: same pattern

This is correct for latency (lower is better) but wrong for throughput, success
rate, or any higher-is-better metric.

### Solution

Add `lower_is_better: bool = True` to each chart's constructor. When `False`,
invert the color mapping.

#### comparison_bar.py

Add parameter to `__init__`:
```python
def __init__(
    self,
    data: Sequence[ComparisonBarData],
    title: str | None = None,
    metric_label: str = "Value",
    lower_is_better: bool = True,
    options: ASCIIChartOptions | None = None,
    subtitle: str | None = None,
):
    ...
    self.lower_is_better = lower_is_better
```

In `_format_annotation()` (line 252), replace:
```python
if pct_change > 0:
    # Regression (slower)
```
with:
```python
is_worse = pct_change > 0 if self.lower_is_better else pct_change < 0
if is_worse:
```

Update both branches (positive=worse and negative=better) to use the
`is_worse` / `not is_worse` logic rather than hardcoded pct_change direction.

#### diverging_bar.py

Add `lower_is_better: bool = True` to `__init__`. In `_colorize_sides()`:
```python
# BEFORE:
if pct_change < 0:
    return colors.colorize(left_side, fg_color="#66a61e"), right_side
if pct_change > 0:
    return left_side, colors.colorize(right_side, fg_color="#d95f02")

# AFTER:
is_improvement = pct_change < 0 if self.lower_is_better else pct_change > 0
if is_improvement:
    return colors.colorize(left_side, fg_color="#66a61e"), right_side
is_regression = pct_change > 0 if self.lower_is_better else pct_change < 0
if is_regression:
    return left_side, colors.colorize(right_side, fg_color="#d95f02")
```

Also check `_render_summary_counts()` if it labels counts as "improved" vs
"regressed" — those labels should also respect `lower_is_better`.

#### summary_box.py

Add `lower_is_better: bool = True` to `SummaryStats` dataclass (after
`value_formatter`). Use it in `_format_pct_colored()`.

#### from_comparison_data() and from_regression_data() factories

Pass `lower_is_better` through to the constructors if the factory accepts it.
Add `lower_is_better: bool = True` as a parameter to both factories.

### Verification

- All existing tests pass (default `lower_is_better=True` preserves behavior).
- Add a test for ComparisonBar with `lower_is_better=False` — verify that a
  positive pct_change gets green color and negative gets red.
- Add a test for DivergingBar with `lower_is_better=False`.

BenchBox impact: **None.** Default `True` matches BenchBox's latency semantics.

**Commit**: `feat: add lower_is_better parameter for improvement direction`

---

## Change Group 4: Rename factory functions to generic names

### Factory function renames

Create new generic-named functions and keep old names as deprecated aliases.

| File | Current name | New name |
|------|-------------|----------|
| `histogram.py` | `from_query_latency_data()` | `from_data()` |
| `scatter_plot.py` | `from_cost_performance_points()` | `from_points()` |
| `diverging_bar.py` | `from_regression_data()` | `from_data()` |
| `line_chart.py` | `from_time_series_points()` | `from_points()` |
| `box_plot.py` | `from_distribution_series()` | `from_series()` |
| `stacked_bar.py` | `from_phase_data()` | `from_data()` |
| `rank_table.py` | `from_heatmap_data()` | `from_matrix()` |
| `cdf_chart.py` | `cdf_from_query_results()` | `from_series()` |
| `percentile_ladder.py` | `percentile_from_query_results()` | `from_series()` |
| `normalized_speedup.py` | `from_normalized_results()` | `from_ratios()` |
| `bar_chart.py` | `from_bar_data()` | `from_data()` |
| `comparison_bar.py` | `from_comparison_data()` | `from_data()` |

Already generic (no change needed):
- `heatmap.py` — `from_matrix()` ✓
- `sparkline_table.py` — `from_metrics()` ✓

### Implementation pattern

For each rename:

1. Rename the existing function to the new generic name.
2. Create a thin deprecated alias with the old name:

```python
import warnings

def from_query_latency_data(*args, **kwargs):
    """Deprecated: use from_data() instead."""
    warnings.warn(
        "from_query_latency_data() is deprecated, use from_data() instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return from_data(*args, **kwargs)
```

Using `*args, **kwargs` passthrough keeps the alias maintenance-free.

### Parameter renames in new factories

The new `from_points()` in scatter_plot.py should accept `x_label`/`y_label`
instead of the current `cost_label`/`performance_label`. Map them through:

```python
def from_points(
    points: Sequence[ScatterPoint],
    title: str | None = None,
    x_label: str = "X",
    y_label: str = "Y",
    options: ASCIIChartOptions | None = None,
    subtitle: str | None = None,
) -> ASCIIScatterPlot:
    return ASCIIScatterPlot(
        points=points,
        title=title,
        x_label=x_label,
        y_label=y_label,
        options=options,
        subtitle=subtitle,
    )
```

The deprecated `from_cost_performance_points()` keeps its original parameter
names (`cost_label`, `performance_label`) and maps them to `x_label`/`y_label`
when calling `from_points()`.

### histogram.py constant rename

`DEFAULT_MAX_QUERIES = 33` → `DEFAULT_MAX_BARS = 33`. This limits bars per chart,
not "queries." Update any internal references.

### __init__.py exports

Add all new factory names to `__all__` and the import block. Keep the old names
exported too (they're the deprecated aliases). The factory section should look
like:

```python
# Factory functions (preferred generic names)
"from_data",         # bar_chart, comparison_bar, diverging_bar, histogram, stacked_bar
"from_series",       # box_plot, cdf_chart, percentile_ladder
"from_points",       # line_chart, scatter_plot
"from_ratios",       # normalized_speedup
"from_matrix",       # heatmap (already exists), rank_table

# Factory functions (deprecated domain-specific names — still exported)
"cdf_from_query_results",
"from_bar_data",
...
```

Note: Several modules will export a function named `from_data()`. Since they're
module-level functions imported from different modules, `__init__.py` needs to
handle name collisions. The cleanest approach:

**Option A** (recommended): Don't export bare `from_data` from `__init__.py` —
they collide. Instead, export them as module-qualified: users call
`textcharts.bar_chart.from_data()` or construct via `BarChart(...)` directly.
Only export unique names like `from_ratios`, `from_matrix` from `__init__.py`.

**Option B**: Export with prefixed names: `bar_from_data`, `histogram_from_data`,
etc. Ugly but unambiguous.

**Option C**: Don't export new factory names from `__init__.py` at all. The
preferred API is direct construction (`BarChart(data=...)`) and factories are
convenience helpers imported from submodules. Only the deprecated names need to
remain in `__init__.py` for backward compatibility.

Choose whichever approach is cleanest. The critical requirement is: **the old
names must remain importable from `textcharts` and emit DeprecationWarning.**

### Verification

- All existing tests pass (via deprecated aliases or because they use direct
  construction).
- Update any internal usage within textcharts tests to use the new names.
- Run: `python -W error::DeprecationWarning -c "from textcharts import from_bar_data"`
  should raise DeprecationWarning.

BenchBox impact: **Minor.** BenchBox imports `from_query_results`,
`from_normalized_results`, `from_metrics`, `from_heatmap_data`,
`from_phase_data`, `from_bar_data`, `from_comparison_data`,
`from_query_latency_data`, `from_regression_data`, `from_time_series_points`,
`from_distribution_series`, `from_cost_performance_points` via
`ascii_runtime.py`. These will emit deprecation warnings until BenchBox updates
(tracked in BenchBox TODO `adapt-benchbox-to-textcharts-neutral-defaults`).

**Commit**: `refactor: rename benchmark-specific factory functions to generic names`

---

## Execution order

1. **Group 1 first** — labels and titles are the simplest, most mechanical changes
2. **Group 3 second** — `lower_is_better` is self-contained and doesn't interact
   with the renames
3. **Group 4 last** — factory renames touch every module and `__init__.py`, so do
   this after Groups 1 and 3 are stable

## Files modified per group

**Group 1** (labels/titles/comments): `histogram.py`, `comparison_bar.py`,
`percentile_ladder.py`, `scatter_plot.py`, `stacked_bar.py`, `heatmap.py`,
`diverging_bar.py`, `cdf_chart.py`, `summary_box.py`, `rank_table.py`,
`bar_chart.py`, `line_chart.py`, `box_plot.py`

**Group 3** (improvement direction): `comparison_bar.py`, `diverging_bar.py`,
`summary_box.py`

**Group 4** (factory renames): All 12 chart files with factories +
`__init__.py` exports
