# Customization

```{tags} advanced, guide, visualization
```

BenchBox visualization supports customization for themes, colors, and terminal display options.

## Themes

BenchBox provides light and dark themes optimized for different contexts:

```bash
benchbox visualize results/*.json --theme light   # Default, best for light terminals
benchbox visualize results/*.json --theme dark    # Best for dark terminal backgrounds
```

**Theme Differences:**

| Aspect | Light Theme | Dark Theme |
|--------|-------------|------------|
| Background | Terminal default | Terminal default |
| Text emphasis | Dark gray tones | Light gray tones |
| Chart palette | Same colorblind-safe colors | Same colorblind-safe colors |

---

## Color Palette

BenchBox uses a colorblind-safe categorical palette designed for data visualization:

**Palette Colors:**

| Color | Hex | Usage |
|-------|-----|-------|
| Teal | `#1b9e77` | Primary series, best performer |
| Orange | `#d95f02` | Secondary series |
| Purple | `#7570b3` | Tertiary series |
| Pink | `#e7298a` | Fourth series |
| Green | `#66a61e` | Fifth series |
| Yellow | `#e6ab02` | Sixth series |
| Brown | `#a6761d` | Seventh series |
| Gray | `#666666` | Eighth series |

**Special Colors:**

| Purpose | Color | Hex |
|---------|-------|-----|
| Best performer | Green | `#28a745` |
| Worst performer | Red | `#dc3545` |
| Improvement (%) | Green | `#66a61e` |
| Regression (%) | Orange | `#d95f02` |

---

## Terminal Display Options

### Color Control

```bash
# Full ANSI color output (default)
benchbox visualize results/*.json

# Disable colors (for piping to files or plain terminals)
benchbox visualize results/*.json --no-color
```

### Character Set

```bash
# Unicode block characters (default): ▏▎▍▌▋▊▉█
benchbox visualize results/*.json

# ASCII-only characters for basic terminals: .-=+#@
benchbox visualize results/*.json --no-unicode
```

### Terminal Width

Charts automatically detect terminal width and constrain output to 40-120 characters. The chart rendering adapts:
- Labels are truncated to fit available space
- Bar widths scale proportionally
- Legends wrap as needed

---

## Accessibility

BenchBox visualizations are designed for accessibility:

**Color Accessibility:**
- Palette passes WCAG AA contrast requirements
- Colorblind-safe: distinguishable for deuteranopia, protanopia, tritanopia
- `--no-color` flag for screen readers and plain text processing

**Screen Reader Support:**
- Text-based output is inherently screen reader compatible
- Use `--no-color` to strip ANSI codes for cleanest plain text
- Consistent labeling with values, legends, and scale notes

**Contrast Ratios:**
- Text on background: minimum 4.5:1 (WCAG AA)
- Chart elements: minimum 3:1

---

## Advanced: Python API Customization

For fine-grained control, use the Python API directly:

```python
from benchbox.core.visualization.ascii.base import ChartOptions
from benchbox.core.visualization.ascii.bar_chart import BarChart, BarData

# Custom chart options
opts = ChartOptions(
    use_color=True,
    use_unicode=True,
    theme="dark",
    width=100,  # Override terminal width detection
)

# Create chart with custom settings
data = [
    BarData(label="Platform A", value=100.5, is_best=True),
    BarData(label="Platform B", value=150.2),
    BarData(label="Platform C", value=200.1, is_worst=True),
]

chart = BarChart(
    data=data,
    title="Custom Chart Title",
    metric_label="Execution Time (ms)",
    options=opts,
)

print(chart.render())
```

### Using the Generic Factory

```python
from benchbox.core.visualization.exporters import render_ascii_chart

# Render any chart type via the generic factory
output = render_ascii_chart(
    chart_type="performance_bar",
    data=data,
    title="My Chart",
)
print(output)
```

### Exporting to File

```python
from benchbox.core.visualization.exporters import export_ascii

export_ascii(
    ascii_content=chart.render(),
    output_dir="./charts",
    base_name="performance_comparison",
    format="txt",
)
```

---

## Configuration Summary

| Option | CLI Flag | Default | Values |
|--------|----------|---------|--------|
| Theme | `--theme` | `light` | `light`, `dark` |
| Colors | `--no-color` | enabled | flag to disable |
| Unicode | `--no-unicode` | enabled | flag to disable |
| Template | `--template` | none | `default`, `flagship`, `head_to_head`, `trends`, `cost_optimization`, `comparison` |
| Chart type | `--chart-type` | `auto` | `auto`, `all`, `performance_bar`, `distribution_box`, `query_heatmap`, `query_histogram`, `cost_scatter`, `time_series` |
