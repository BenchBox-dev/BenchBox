/**
 * chartMath.ts - Pure chart computation helpers.
 *
 * All visualization math lives here so it can be:
 *   1. Called by SVG components without DOM/JSX dependencies.
 *   2. Loaded by the Vitest parity suite and compared against Python
 *      reference values in `tests/parity/fixtures/`.
 *
 * Rules:
 *   - No imports from Preact, no JSX, no DOM APIs.
 *   - Every export must have a Python equivalent in the CLI pipeline or
 *     `benchbox/core/visualization/` - document where.
 *   - Float comparison tolerance: 1e-9 (Python and JS IEEE-754 agree at
 *     this precision for these formulas).
 */

import { HEAT_MIN_RATIO, HEAT_MAX_RATIO } from "@/lib/chartTheme";
import { isValidTimingValue, validTimingValues } from "@/lib/displayEligibility";

// ---------------------------------------------------------------------------
// Latency magnitude scale
// Explorer-only SVG layout policy for lower-is-better latency bars. The CLI
// ASCII bar chart remains linear; the browser switches to log scale when a slow
// outlier would otherwise collapse faster platforms into unreadable slivers.
// ---------------------------------------------------------------------------

export const LATENCY_LOG_SCALE_THRESHOLD = 10;

export type LatencyScaleMode = "linear" | "log";

export interface LatencyBarScale {
  mode: LatencyScaleMode;
  min: number;
  max: number;
  domainMin: number;
  domainMax: number;
  spanRatio: number;
}

const LATENCY_LOG_DOMAIN_PAD = Math.sqrt(10);
const LATENCY_LOG_TICKS_MS = [0.1, 1, 10, 100, 1000, 10000, 100000, 1000000];

function log2Latency(ms: number): number {
  return Math.log2(Math.max(ms, Number.MIN_VALUE));
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

export function buildLatencyBarScale(
  values: (number | null)[],
  logThreshold = LATENCY_LOG_SCALE_THRESHOLD,
): LatencyBarScale | null {
  const valid = validTimingValues(values);
  if (valid.length === 0) return null;

  const min = Math.min(...valid);
  const max = Math.max(...valid);
  const spanRatio = max / min;
  const mode: LatencyScaleMode = spanRatio >= logThreshold ? "log" : "linear";

  if (mode === "linear") {
    return { mode, min, max, domainMin: 0, domainMax: max, spanRatio };
  }

  return {
    mode,
    min,
    max,
    domainMin: min / LATENCY_LOG_DOMAIN_PAD,
    domainMax: max,
    spanRatio,
  };
}

export function latencyScaleFraction(value: number | null, scale: LatencyBarScale): number | null {
  if (!isValidTimingValue(value)) return null;
  if (scale.mode === "linear") {
    if (scale.domainMax <= 0) return null;
    return clamp01(value / scale.domainMax);
  }

  const logMin = log2Latency(scale.domainMin);
  const logMax = log2Latency(scale.domainMax);
  const logRange = logMax - logMin || 1;
  return clamp01((log2Latency(value) - logMin) / logRange);
}

export function latencyScaleTicks(scale: LatencyBarScale): number[] {
  if (scale.mode === "linear") {
    return [0, 0.25, 0.5, 0.75, 1].map((fraction) => fraction * scale.domainMax);
  }

  // Always include both endpoint ticks so the right edge of the bar chart
  // has a labelled terminal value. Without this, ranges like 0.2-2 ms or
  // 100k-50M ms would be plotted against an unlabelled endpoint and the
  // axis could be misread. Canonical powers of ten remain for interior
  // labelling; dedupe collapses any duplicates at the endpoints.
  const interior = LATENCY_LOG_TICKS_MS.filter(
    (ms) => ms >= scale.domainMin * 0.99 && ms <= scale.domainMax * 1.01,
  );
  const combined = [scale.domainMin, ...interior, scale.domainMax];
  const seen = new Set<number>();
  const ticks: number[] = [];
  for (const value of combined) {
    if (!seen.has(value)) {
      seen.add(value);
      ticks.push(value);
    }
  }
  return ticks;
}

// ---------------------------------------------------------------------------
// Shared log latency axis
// Used by SVG views that plot latency distributions on a log2 ms axis.
// ---------------------------------------------------------------------------

export const LOG_LATENCY_TICKS_MS = [0.1, 1, 10, 100, 1000, 10000];

export interface LogLatencyScale {
  logMin: number;
  logMax: number;
  logRange: number;
  floorMs: number;
}

export function logLatencyValue(ms: number, floorMs = 0.1): number {
  return Math.log2(Math.max(ms, floorMs));
}

export function buildLogLatencyScale(
  values: readonly number[],
  options: {
    lowerPad?: number;
    upperPad?: number;
    floorMs?: number;
    minValue?: number;
    maxValue?: number;
  } = {},
): LogLatencyScale | null {
  const valid = validTimingValues(values);
  if (valid.length === 0) return null;

  const floorMs = options.floorMs ?? 0.1;
  const minValue = options.minValue ?? Math.min(...valid);
  const maxValue = options.maxValue ?? Math.max(...valid);
  const logMin = logLatencyValue(minValue, floorMs) - (options.lowerPad ?? 0);
  const logMax = logLatencyValue(maxValue, floorMs) + (options.upperPad ?? 0);
  return {
    logMin,
    logMax,
    logRange: logMax - logMin || 1,
    floorMs,
  };
}

export function logLatencyFraction(ms: number, scale: LogLatencyScale): number {
  return (logLatencyValue(ms, scale.floorMs) - scale.logMin) / scale.logRange;
}

export function logLatencyTicks(scale: LogLatencyScale, tolerance = 0.05): number[] {
  return LOG_LATENCY_TICKS_MS.filter(
    (ms) =>
      logLatencyValue(ms, scale.floorMs) >= scale.logMin - tolerance &&
      logLatencyValue(ms, scale.floorMs) <= scale.logMax + tolerance,
  );
}

// ---------------------------------------------------------------------------
// Heatmap color math
// Python reference: benchbox/core/visualization/ascii/heatmap.py
// (log10-ratio → hue mapping)
// ---------------------------------------------------------------------------

/**
 * Compute the HSL hue for a heat cell.
 *
 * Uses log10(ms / minInCol) clamped to [0, log10(10)] = [0, 1]:
 *   ratio = 1  → hue 120 (green, fastest)
 *   ratio = 10 → hue 0   (red, 10× slower or more)
 *
 * Returns null for missing/invalid inputs so the caller can skip coloring.
 */
export function colorForCell(ms: number | null, minInCol: number | null): number | null {
  if (!isValidTimingValue(ms) || !isValidTimingValue(minInCol)) return null;
  const ratio = Math.max(HEAT_MIN_RATIO, Math.min(HEAT_MAX_RATIO, ms / minInCol));
  const t = Math.log10(ratio);
  return Math.round(120 * (1 - t));
}

/**
 * Compute the grayscale lightness for a high-contrast cell.
 *
 * Returns a CSS percentage value string: "95%" (fastest) → "25%" (10× slower).
 * Returns null for missing/invalid inputs.
 */
export function lightnessForCell(ms: number | null, minInCol: number | null): string | null {
  if (!isValidTimingValue(ms) || !isValidTimingValue(minInCol)) return null;
  const ratio = Math.max(HEAT_MIN_RATIO, Math.min(HEAT_MAX_RATIO, ms / minInCol));
  const t = Math.log10(ratio);
  return `${Math.round(95 - 70 * t)}%`;
}

// ---------------------------------------------------------------------------
// Speedup math
// Two distinct speedup concepts - use the right one for the context:
//
//   vsSlowestRatio(thisMs, slowestMs)  - "how much faster am I than the slowest?"
//     Always >= 1 for valid inputs.  Used by summary cards and the per-query
//     breakdown table on the Compare page (both anchored to the slowest value).
//     Python reference:
//       benchbox.core.explorer_pipeline.compare_math.speedup_vs_slowest
//       (direction-aware variant invoked with higher_is_better=False).
//
//   speedupRatio(baselineMs, thisMs)   - "how do I compare to a chosen baseline?"
//     Can be < 1 (slower) or > 1 (faster).  Used by NormalizedSpeedupChart
//     where the user picks any result as the baseline.
//     Python reference:
//       benchbox.core.explorer_pipeline.compare_math.baseline_speedup_ratio
//       (also matches benchbox/core/visualization/ascii/normalized_speedup.py).
// ---------------------------------------------------------------------------

/**
 * Compute slowest_ms / this_ms - the "vs slowest" speedup for summary cards
 * and per-query breakdown rows.
 *
 *   = 1  when this result is also the slowest
 *   > 1  when this result is faster than the slowest (always >= 1)
 *
 * Returns null when either input is null, zero, or negative.
 *
 * @param thisMs     Canonical display_ms for the result being shown.
 * @param slowestMs  Largest display_ms across all results for this benchmark.
 */
export function vsSlowestRatio(thisMs: number | null, slowestMs: number | null): number | null {
  if (!isValidTimingValue(thisMs) || !isValidTimingValue(slowestMs)) return null;
  return slowestMs / thisMs;
}

// ---------------------------------------------------------------------------
// Python reference: benchbox/core/visualization/ascii/normalized_speedup.py
// ---------------------------------------------------------------------------

/**
 * Compute per-baseline speedup: baseline_ms / this_ms.
 *
 *   > 1: this result is faster than the baseline
 *   < 1: this result is slower than the baseline
 *   = 1: identical
 *
 * Returns null when either input is null, zero, or negative.
 *
 * @param baselineMs  Canonical display_ms for the chosen baseline result.
 * @param thisMs      Canonical display_ms for the result being compared.
 */
export function speedupRatio(baselineMs: number | null, thisMs: number | null): number | null {
  if (!isValidTimingValue(baselineMs) || !isValidTimingValue(thisMs)) return null;
  return baselineMs / thisMs;
}

// ---------------------------------------------------------------------------
// Delta percent math
// Python reference:
//   benchbox.core.explorer_pipeline.compare_math.delta_pct
//   (also matches benchbox/core/visualization/ascii/diverging_bar.py).
// ---------------------------------------------------------------------------

/**
 * Compute the percent change of `thisMs` relative to `baselineMs`.
 *
 *   (thisMs - baselineMs) / baselineMs * 100
 *
 *   negative: faster than baseline
 *   positive: slower than baseline
 *
 * Returns null when either input is null, zero, or negative.
 */
export function deltaPct(thisMs: number | null, baselineMs: number | null): number | null {
  if (!isValidTimingValue(thisMs) || !isValidTimingValue(baselineMs)) return null;
  return ((thisMs - baselineMs) / baselineMs) * 100;
}

// ---------------------------------------------------------------------------
// Group sort by magnitude
// Python reference: benchbox/core/visualization/ascii/diverging_bar.py
// (sort by max-abs-delta so biggest changes appear first)
// ---------------------------------------------------------------------------

/**
 * Sort query groups by the maximum absolute metric value in each group,
 * descending.  Used by DivergingBarChart to surface the largest
 * regressions/improvements at the top.
 *
 * @param groups    Map entries: [queryId, entries[]] where each entry has a
 *                  `deltaPct` numeric field.
 * @returns         A new array sorted by max(|deltaPct|) descending.
 */
export function sortByMagnitudeDesc<T extends { deltaPct: number }>(groups: [string, T[]][]): [string, T[]][] {
  return [...groups].sort((a, b) => {
    const maxA = Math.max(...a[1].map((e) => Math.abs(e.deltaPct)));
    const maxB = Math.max(...b[1].map((e) => Math.abs(e.deltaPct)));
    return maxB - maxA;
  });
}

// ---------------------------------------------------------------------------
// Per-query spread (slowest / fastest within a set of results for one query)
// Python reference:
//   benchbox.core.explorer_pipeline.compare_math.per_query_speedup_spread
// ---------------------------------------------------------------------------

/**
 * Compute the within-query speedup spread: slowest_ms / fastest_ms.
 *
 * Represents how much faster the fastest result for a given query is than the
 * slowest.  Always >= 1 when valid.
 *
 * @param validMs  Array of positive display_ms values for a single query
 *                 across multiple results.  Caller must filter nulls first.
 * @returns        slowest / fastest, or null when the array is empty or all
 *                 zero.
 */
export function perQuerySpeedup(validMs: number[]): number | null {
  const valid = validTimingValues(validMs);
  if (valid.length === 0) return null;
  const fastest = Math.min(...valid);
  const slowest = Math.max(...valid);
  return slowest / fastest;
}

// ---------------------------------------------------------------------------
// Geometric mean
// Python reference: benchbox/core/explorer_pipeline/transformer.py
//   _display_geomean_ms: math.exp(sum(math.log(v) for v in values) / len(values))
// ---------------------------------------------------------------------------

/**
 * Compute the geometric mean of an array of values.
 *
 * Matches the Python `_display_geomean_ms` implementation exactly:
 *   exp(mean(log(v) for v in positive_values))
 *
 * Null and non-positive values are silently excluded.  Returns null when no
 * valid positive values exist.
 *
 * @param values  Mixed array of display_ms values (may contain nulls).
 */
export function geomeanMs(values: (number | null)[]): number | null {
  const valid = validTimingValues(values);
  if (valid.length === 0) return null;
  return Math.exp(valid.reduce((sum, v) => sum + Math.log(v), 0) / valid.length);
}

// ---------------------------------------------------------------------------
// Box plot statistics
// Python reference: tests/parity/generate_visualization_fixtures.compute_box_stats
//
// NOTE: this deliberately diverges from textcharts.box_plot.compute_quartiles.
// That function returns IQR-whiskered whisker_low/whisker_high and a separate
// outliers list.  The explorer visualization instead shows the raw data extent
// (sorted[0], sorted[-1]) with no outlier handling - quartiles still use the
// same linear-interpolation percentile, so Q1/median/Q3 match the CLI exactly.
// ---------------------------------------------------------------------------

export interface BoxStats {
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
}

/**
 * Compute five-number summary (min, Q1, median, Q3, max) from an array of values.
 *
 * Quartiles use the same linear-interpolation percentile as ``computePercentile``,
 * matching ``textcharts.percentile_ladder.compute_percentile``.  Min/max are the
 * raw extremes of the valid input - no IQR whiskering, no outlier detection.
 *
 * Null and non-positive values are excluded.  Returns null when no valid values.
 */
export function computeBoxStats(values: (number | null)[]): BoxStats | null {
  const valid = validTimingValues(values);
  if (valid.length === 0) return null;
  const sorted = [...valid].sort((a, b) => a - b);
  return {
    min: sorted[0]!,
    q1: computePercentile(sorted, 25)!,
    median: computePercentile(sorted, 50)!,
    q3: computePercentile(sorted, 75)!,
    max: sorted[sorted.length - 1]!,
  };
}

// ---------------------------------------------------------------------------
// Empirical CDF points
// Python reference: tests/parity/generate_visualization_fixtures.compute_ecdf_points
// (also mirrors the ECDF plotting step inside textcharts.cdf_chart)
// ---------------------------------------------------------------------------

/**
 * Compute empirical CDF points from an array of values.
 *
 * For n sorted positive values [x1, ..., xn], returns n points where:
 *   point i: { x: xi, y: (i+1)/n * 100 }  (y in percent)
 *
 * Null, non-positive, and non-finite values are excluded.
 * Returns an empty array when no valid values exist.
 */
export function computeECDFPoints(values: (number | null)[]): { x: number; y: number }[] {
  const valid = validTimingValues(values);
  if (valid.length === 0) return [];
  const sorted = [...valid].sort((a, b) => a - b);
  const n = sorted.length;
  return sorted.map((x, i) => ({ x, y: ((i + 1) / n) * 100 }));
}

// ---------------------------------------------------------------------------
// Percentile computation
// Python reference: benchbox/core/explorer_pipeline/transformer.py
//   _compute_percentile - mirrors textcharts.percentile_ladder.compute_percentile
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Rank-table ranking
// Python reference: tests/parity/generate_visualization_fixtures.compute_rank_table
// Standard competition ranking (1, 1, 3): ties share the lower rank, the
// rank after a tie group jumps by the size of the group.
// ---------------------------------------------------------------------------

/**
 * Compute per-query ordinal ranks across platforms.
 *
 * Input: per-query, a row of (platform_index, display_ms | null).  A null,
 *        zero, or negative value means "did not run / failed" and receives
 *        rank null (rendered as -).  Positive values are sorted ascending
 *        (fastest = rank 1).  Equal values receive equal rank.
 *
 * The result mirrors the Python reference exactly - ties are the known
 * divergence risk between Python's `sorted` and JS `Array.sort`, both of
 * which are stable per ES2019+/CPython, so relative order of equal ms
 * values is preserved on both sides.
 */
export function computeRankTable(
  queryIds: string[],
  timingsByPlatform: Record<string, number | null>[],
): Record<string, (number | null)[]> {
  const ranks: Record<string, (number | null)[]> = {};
  const nPlatforms = timingsByPlatform.length;
  for (const qid of queryIds) {
    const valid: { i: number; ms: number }[] = [];
    for (let i = 0; i < nPlatforms; i++) {
      const ms = timingsByPlatform[i]?.[qid] ?? null;
      if (isValidTimingValue(ms)) valid.push({ i, ms });
    }
    valid.sort((a, b) => a.ms - b.ms);
    const rankArr: (number | null)[] = new Array(nPlatforms).fill(null);
    let r = 1;
    for (let j = 0; j < valid.length; j++) {
      if (j > 0 && valid[j]!.ms !== valid[j - 1]!.ms) r = j + 1;
      rankArr[valid[j]!.i] = r;
    }
    ranks[qid] = rankArr;
  }
  return ranks;
}

/**
 * Compute the p-th percentile of an array using linear interpolation.
 *
 * Matches ``textcharts.percentile_ladder.compute_percentile`` exactly:
 *   k = (p / 100) * (n - 1)
 *   result = values[floor(k)] * (ceil(k) - k) + values[ceil(k)] * (k - floor(k))
 *
 * @param values  Non-empty sorted or unsorted array of numeric values.
 * @param p       Percentile in range [0, 100].
 * @returns       Interpolated percentile value, or null for empty input - callers must handle null.
 */
export function computePercentile(values: number[], p: number): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const n = sorted.length;
  if (n === 1) return sorted[0]!;
  const k = (p / 100) * (n - 1);
  const f = Math.floor(k);
  const c = Math.ceil(k);
  if (f === c) return sorted[Math.round(k)]!;
  return sorted[f]! * (c - k) + sorted[c]! * (k - f);
}
