/**
 * chartTheme.ts - Single source of truth for chart colors and scale constants.
 *
 * All visualization components import from here so color/scale changes propagate
 * consistently.  Never define `CHART_COLORS` or color literals inline in a chart
 * component - use `paletteColor(i)` and the semantic fill constants instead.
 *
 * Python reference: no counterpart (purely presentational constants).
 */

// ---------------------------------------------------------------------------
// Platform color palette - blue, emerald, amber, red
// ---------------------------------------------------------------------------

export const PALETTE = [
  "var(--bb-chart-cat-1)",
  "var(--bb-chart-cat-2)",
  "var(--bb-chart-cat-3)",
  "var(--bb-chart-cat-4)",
] as const;

/** Return the palette color at `index`, wrapping with modulo. Never returns undefined. */
export function paletteColor(index: number): string {
  return PALETTE[index % PALETTE.length] ?? "var(--bb-chart-cat-1)";
}

// ---------------------------------------------------------------------------
// Time-series palette - contrast-checked 8-color set for many overlapping lines
// (the 4-entry PALETTE is insufficient for time_series where ≥5 platforms
// may share a chart and adjacent lines must be visually distinguishable).
// ---------------------------------------------------------------------------

export const TIME_SERIES_PALETTE = [
  "var(--bb-chart-cat-1)",
  "var(--bb-chart-cat-2)",
  "var(--bb-chart-cat-3)",
  "var(--bb-chart-cat-4)",
  "var(--bb-chart-cat-5)",
  "var(--bb-chart-cat-6)",
  "var(--bb-chart-warning)",
  "var(--bb-chart-axis)",
] as const;

/** Time-series palette accessor. Wraps with modulo; never returns undefined. */
export function timeSeriesColor(index: number): string {
  return TIME_SERIES_PALETTE[index % TIME_SERIES_PALETTE.length] ?? "var(--bb-chart-cat-1)";
}

// ---------------------------------------------------------------------------
// Heatmap ratio bounds
// log10 scale: 1× = fastest (green hue 120), 10× = slowest (hue 0)
// ---------------------------------------------------------------------------

export const HEAT_MIN_RATIO = 1;
export const HEAT_MAX_RATIO = 10;

// ---------------------------------------------------------------------------
// Speedup chart scale constants
// ---------------------------------------------------------------------------

export const SPEEDUP_LOG2_MIN = Math.log2(0.2); // a bit below 0.25×
export const SPEEDUP_LOG2_MAX = Math.log2(5);   // a bit above 4×
export const SPEEDUP_LOG2_RANGE = SPEEDUP_LOG2_MAX - SPEEDUP_LOG2_MIN;
export const SPEEDUP_GRID_STOPS = [0.25, 0.5, 1, 2, 4] as const;

// ---------------------------------------------------------------------------
// Diverging bar chart
// ---------------------------------------------------------------------------

/** Clamp extreme delta-percent values for bar width calculation. */
export const DIVERGING_MAX_PCT = 300;

// ---------------------------------------------------------------------------
// Phase duration colors - keyed by BenchBox phase name
// ---------------------------------------------------------------------------

export const PHASE_COLORS: Record<string, string> = {
  data_generation: "var(--bb-chart-grid)",
  schema_creation: "var(--bb-chart-cat-1)",
  data_loading: "var(--bb-chart-cat-3)",
  validation: "var(--bb-chart-success)",
  power_test: "var(--bb-chart-warning)",
  throughput_test: "var(--bb-chart-danger)",
};

// ---------------------------------------------------------------------------
// Semantic fill colors (faster / slower than baseline)
// ---------------------------------------------------------------------------

export const FASTER_FILL = "var(--bb-chart-success)";
export const SLOWER_FILL = "var(--bb-chart-danger)";
