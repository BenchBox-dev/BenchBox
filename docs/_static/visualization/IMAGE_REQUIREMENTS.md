# Visualization Documentation Image Requirements

This document specifies the images needed to complete the visualization documentation. All images should be terminal screenshots of actual BenchBox ASCII chart output for authenticity.

## Image Generation Strategy

1. **Source Data**: Use fixture/sample benchmark results or run actual benchmarks
2. **Consistency**: Generate all images in a single session for consistent terminal settings
3. **Formats**: Save as PNG terminal screenshots
4. **Naming**: Use exact filenames specified below
5. **Terminal**: Use a dark terminal theme with Unicode support for best ASCII chart rendering

---

## Required Images by Document

### chart-types.md (Priority: Critical)

These images are essential - users choose chart types based on visual examples.

| Filename | Description | Source Command |
|----------|-------------|----------------|
| `chart-performance-bar.png` | Multi-platform bar chart with best/worst highlighting | `benchbox visualize --chart-type performance_bar` with 4 platforms |
| `chart-time-series.png` | Trend line chart | `benchbox visualize --chart-type time_series` with 5+ runs |
| `chart-cost-scatter.png` | Cost-performance scatter with Pareto frontier | `benchbox visualize --chart-type cost_scatter` with cost data |
| `chart-query-heatmap.png` | Query x Platform heatmap | `benchbox visualize --chart-type query_heatmap` with 3+ platforms |
| `chart-distribution-box.png` | Latency distribution box plot | `benchbox visualize --chart-type distribution_box` with 3 platforms |

**Generation approach:**
```bash
benchbox visualize samples/*.json --chart-type performance_bar
```

---

### templates.md (Priority: Critical)

Gallery images showing complete template output.

| Filename | Description | Source Command |
|----------|-------------|----------------|
| `template-flagship-gallery.png` | Screenshot of flagship template output | `benchbox visualize --template flagship` |
| `template-head-to-head-gallery.png` | Screenshot of head-to-head template output | `benchbox visualize --template head_to_head` |
| `template-trends-gallery.png` | Screenshot of trends template output | `benchbox visualize --template trends` |
| `template-cost-optimization-gallery.png` | Screenshot of cost optimization template output | `benchbox visualize --template cost_optimization` |

**Notes:**
- Each template generates multiple charts separated by `────────` dividers
- Capture the full terminal output as a single screenshot

---

### customization.md (Priority: Important)

| Filename | Description | Source Command |
|----------|-------------|----------------|
| `theme-light-dark-comparison.png` | Side-by-side light vs dark theme | Same chart with `--theme light` and `--theme dark` |
| `color-palette-swatches.png` | Okabe-Ito colorblind-friendly palette display | Generate programmatically or screenshot |

---

### chart-generation-guide.md (Priority: Important)

| Filename | Description | Source Command |
|----------|-------------|----------------|
| `workflow-quickstart-output.png` | Default `benchbox visualize` output | Screenshot of auto-detected chart |
| `workflow-flagship-gallery.png` | (Same as template-flagship-gallery.png) | Reuse |

---

## Current Automation

BenchBox's screenshot capture automation lives in [`scripts/capture_chart_images.py`](../../../scripts/capture_chart_images.py).

- `make docs-images` renders the supported chart screenshots and writes them to `_blog/building-benchbox/images`
- The same command also syncs shared copies into `docs/blog/images`
- `make docs-validate` verifies the two shared image trees stay byte-identical

For copy-only resyncs after a manual asset update, run:

```bash
uv run -- python scripts/capture_chart_images.py --sync-only
```

This automation currently covers the shared blog/documentation screenshot set. The `docs/_static/visualization/*.png`
gallery assets listed above still use the manual capture workflow described in this file.

---

## Verification Checklist

After generating images, verify:

- [ ] All 5 chart-types.md images exist and show clear ASCII chart examples
- [ ] All 4 template gallery images show complete template output
- [ ] Theme comparison clearly shows light vs dark terminal rendering
- [ ] Color palette is visually accurate (Okabe-Ito colors)
- [ ] All images are reasonable file sizes (<500KB each)
- [ ] Images render correctly in docs build (`make html`)
