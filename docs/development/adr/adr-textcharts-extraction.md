# ADR: Extract ASCII Charting into `textcharts` Standalone Library

**Status**: Accepted
**Date**: 2026-03-05

## Context

BenchBox owns a mature ASCII charting system (15 chart types, zero external dependencies) tightly embedded under `benchbox/core/visualization/ascii/`. The charting code is general-purpose terminal visualization with no inherent dependency on benchmarking concepts, yet it can only be used through BenchBox.

## Decision

Extract the ASCII charting package into a standalone library called `textcharts` (PyPI: `textcharts`, import: `textcharts`).

### Ownership Boundaries

**`textcharts` owns:**
- Chart primitives: 15 chart classes (`BarChart`, `Histogram`, `Heatmap`, etc.)
- Data models: typed dataclasses (`BarData`, `HistogramBar`, `BoxPlotSeries`, etc.)
- Configuration: `ChartOptions` (width, height, color, unicode, theme, palette)
- Terminal infrastructure: `TerminalColors`, `TerminalCapabilities`, `ColorMode`, `detect_terminal_capabilities`
- Rendering utilities: `outlier_severity_markers`, `robust_p95`, `compute_percentile_linear`
- Factory functions: `from_bar_data`, `from_matrix`, `from_metrics`, etc.

**BenchBox owns:**
- `ascii_runtime.py` - dispatch layer converting `NormalizedResult` into chart-specific data models
- `exporters.py` - file export helpers
- `post_run_summary.py` - post-run chart assembly from `BenchmarkResults`
- `chart_types.py` - chart type registry with metadata and template associations
- `templates.py` - curated chart groupings for common use cases
- CLI commands and MCP tools

### Naming Convention

- Standalone classes drop the `ASCII` prefix: `BarChart` (not `ASCIIBarChart`), `ChartOptions` (not `ASCIIChartOptions`)
- BenchBox compatibility shims re-export with `ASCII*` aliases
- Data models keep their names unchanged: `BarData`, `HistogramBar`, etc.

### Key Design Decisions

1. **No dispatch in library**: `textcharts` does not include a `render(chart_type, results)` function. Standalone users construct chart objects directly. BenchBox keeps its own dispatch layer.

2. **Formatter injection over coupling**: The single coupling point (`format_scale_factor`) was resolved via an optional `Callable` on `ChartOptions`, not by inlining BenchBox logic.

3. **Compatibility shims during transition**: Old import paths (`benchbox.core.visualization.ascii.*`) continue working via thin re-export modules that delegate to `textcharts`.

4. **Exact text parity required**: Golden snapshot tests enforce byte-identical output before and after extraction. No rendering optimizations during extraction.

## Consequences

- BenchBox gains a clean API boundary for visualization
- The charting code becomes independently usable, testable, and releasable
- Migration requires a compatibility shim period (one release cycle minimum)
- Internal BenchBox callers must go through `ascii_api.py` facade (no direct submodule imports)

## Follow-up dependency decision (2026-08-02)

**Status**: Accepted — retain the direct `textcharts>=0.1.0` core dependency.

The extraction is complete, but it did not make `textcharts` optional. The
runtime still imports the package from the ASCII compatibility shims and from
`benchbox.monitoring.report`; the dependency audit records 20 production
import sites. Removing the declaration would make a normal BenchBox install
fail while importing supported visualization or monitoring paths, and would
also break the documented legacy shim imports.

Replacement, vendoring, and deprecation were compared:

- **Replacement** would require reimplementing or adopting another renderer and
  re-establishing byte-for-byte output and shim compatibility.
- **Vendoring** would duplicate the standalone package, create two ownership
  and security-update paths, and still require a migration for existing imports.
- **Deprecating the shims** would be a public API break without a release and
  migration window; it would not remove the monitoring import path by itself.

Retention is therefore the lowest-risk supported choice for this release. The
manifest, lockfile, generated dependency audit, ASCII shims, and MCP semantic
chart boundary remain coupled and must move together in any future migration.
Revisit after a replacement renderer and a separately approved compatibility
and package-install plan exist; no MCP server registration is implied by this
Python dependency.
