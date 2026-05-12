// ---------------------------------------------------------------------------
// NormalizedSpeedupChart - log-scale horizontal speedup bars per query
//
// speedup = baseline_ms / this_ms
//   > 1: faster than baseline (green)
//   < 1: slower than baseline (red)
//   = 1: same (neutral)
//
// Log2 scale with grid lines at 0.25×, 0.5×, 1×, 2×, 4×.
// ---------------------------------------------------------------------------

import { useState } from "preact/hooks";
import { speedupRatio } from "@/lib/chartMath";
import { isValidTimingValue } from "@/lib/displayEligibility";
import { formatSpeedup } from "@/lib/metricFormatters";
import {
  FASTER_FILL,
  SLOWER_FILL,
  SPEEDUP_GRID_STOPS,
  SPEEDUP_LOG2_MIN,
  SPEEDUP_LOG2_RANGE,
  paletteColor,
} from "@/lib/chartTheme";
import { useElementSize } from "@/lib/useElementSize";

function toX(speedup: number, width: number): number {
  const clamped = Math.max(0.1, Math.min(speedup, 10));
  return ((Math.log2(clamped) - SPEEDUP_LOG2_MIN) / SPEEDUP_LOG2_RANGE) * width;
}

interface SpeedupEntry {
  queryId: string;
  speedups: (number | null)[]; // one per non-baseline result; null = query absent
}

interface Props {
  queries: { queryId: string; timings: ({ ms: number; status: string } | null)[] }[];
  results: { platform: string }[];
  baselineIdx: number;
}

export function NormalizedSpeedupChart({ queries, results, baselineIdx }: Props) {
  const [containerRef, { width: containerWidth }] = useElementSize();
  // Use measured width; fall back to 600 if not yet observed (before first paint).
  const drawWidth = Math.max(containerWidth, 300);

  // w6 (chart-panel-scope-and-labeling): default to "comparable only"
  // so cohorts with hundreds of queries (e.g. read_primitives' ~149)
  // don't dominate the chart with mostly-missing rows. Toggling
  // exposes the partials when the user wants the wider context.
  const [showComparableOnly, setShowComparableOnly] = useState(true);

  if (queries.length === 0 || results.length < 2) return null;

  const BAR_H = 16;
  const BAR_GAP = 4;
  const LABEL_W = 60;
  const AXIS_H = 24;
  const PADDING = 8;

  // Compute speedup entries (full set first, then filter for the visible
  // chart). Counts let the toggle disclose how many rows are hidden.
  const allEntries: SpeedupEntry[] = queries.map(({ queryId, timings }) => {
    const baselineT = timings[baselineIdx];
    const baselineMs = isValidTimingValue(baselineT?.ms) ? baselineT.ms : null;
    const speedups = timings
      .filter((_, i) => i !== baselineIdx)
      .map((t) => speedupRatio(baselineMs, t?.ms ?? null));
    return { queryId, speedups };
  });
  const fullyComparableEntries = allEntries.filter((entry) =>
    entry.speedups.every((speedup) => speedup !== null),
  );
  const entries = showComparableOnly && fullyComparableEntries.length > 0
    ? fullyComparableEntries
    : allEntries;
  const hiddenEntryCount = allEntries.length - entries.length;

  const nonBaselineCount = results.length - 1;
  const rowHeight = BAR_H * nonBaselineCount + BAR_GAP * (nonBaselineCount + 1);
  const totalHeight = AXIS_H + entries.length * rowHeight + PADDING;

  const nonBaselineResults = results.filter((_, i) => i !== baselineIdx);
  const measuredSpeedups = entries
    .flatMap((entry) => entry.speedups)
    .filter((speedup): speedup is number => speedup !== null);
  const hasMissingSpeedups = entries.some((entry) => entry.speedups.some((speedup) => speedup === null));
  const allNearEqual =
    !hasMissingSpeedups &&
    measuredSpeedups.length > 0 &&
    measuredSpeedups.every((speedup) => Math.abs(speedup - 1) <= 0.01);

  if (allNearEqual && hiddenEntryCount === 0) {
    return (
      <SpeedupParityState
        baseline={results[baselineIdx]?.platform ?? "baseline"}
        candidates={nonBaselineResults.map((result) => result.platform)}
        speedupCount={measuredSpeedups.length}
      />
    );
  }

  return (
    <div ref={containerRef} class="w-full overflow-x-auto">
      {(hiddenEntryCount > 0 || (!showComparableOnly && fullyComparableEntries.length < allEntries.length)) && (
        <div class="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--bb-data-fg-muted)]">
          <span>
            {showComparableOnly
              ? `Showing ${entries.length} fully comparable queries (${hiddenEntryCount} hidden — at least one run missing data).`
              : `Showing all ${entries.length} queries; ${allEntries.length - fullyComparableEntries.length} have missing data.`}
          </span>
          <label class="inline-flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={showComparableOnly}
              onChange={(event) => setShowComparableOnly((event.target as HTMLInputElement).checked)}
              data-testid="normalized-speedup-comparable-only-toggle"
              class="h-3.5 w-3.5 rounded border-[var(--bb-data-border-strong)]"
            />
            <span>Comparable only</span>
          </label>
        </div>
      )}
      <svg
        class="bb-chart-svg"
        width="100%"
        height={totalHeight}
        viewBox={`0 0 ${drawWidth} ${totalHeight}`}
        aria-label="Normalized speedup chart"
      >
        {/* Grid lines and axis labels */}
        {SPEEDUP_GRID_STOPS.map((stop) => {
          const x = LABEL_W + toX(stop, drawWidth - LABEL_W - PADDING);
          return (
            <g key={stop}>
              <line
                x1={x} y1={0}
                x2={x} y2={totalHeight - AXIS_H}
                stroke={stop === 1 ? "#6b7280" : "#e5e7eb"}
                stroke-width={stop === 1 ? 1.5 : 1}
                stroke-dasharray={stop === 1 ? "none" : "3 3"}
              />
              <text
                x={x}
                y={totalHeight - 4}
                text-anchor="middle"
                font-size="9"
                fill="#9ca3af"
              >
                {formatSpeedup(stop, { unit: "×" }).valueText}
              </text>
            </g>
          );
        })}

        {/* Bars */}
        {entries.map(({ queryId, speedups }, rowIdx) => {
          const y0 = rowIdx * rowHeight;
          const barAreaW = drawWidth - LABEL_W - PADDING;
          const centerX = LABEL_W + toX(1, barAreaW);

          // Composite key: the `queries` prop is not deduped at the boundary
          // (unlike sortQueryIds), so a caller passing variant rows for the
          // same queryId would collide on key={queryId}. The row index
          // disambiguates within this iteration.
          return (
            <g key={`${queryId}-${rowIdx}`} transform={`translate(0, ${y0})`}>
              <text
                x={LABEL_W - 4}
                y={rowHeight / 2 + 4}
                text-anchor="end"
                font-size="9"
                fill="#6b7280"
                font-family="monospace"
              >
                {queryId}
              </text>
              {speedups.map((speedup, si) => {
                const colorIdx = si < baselineIdx ? si : si + 1;
                const color = paletteColor(colorIdx);
                const barY = BAR_GAP + si * (BAR_H + BAR_GAP);
                if (speedup === null) {
                  return (
                    <text key={si} x={centerX + 4} y={barY + BAR_H / 2 + 3} font-size="8" fill="#d1d5db">
                      -
                    </text>
                  );
                }
                const sx = LABEL_W + toX(speedup, barAreaW);
                const barX = Math.min(sx, centerX);
                const barW = Math.abs(sx - centerX);
                const isSlower = speedup < 1;
                return (
                  <g key={si}>
                    <rect
                      x={barX}
                      y={barY}
                      width={Math.max(barW, 1)}
                      height={BAR_H}
                      fill={isSlower ? SLOWER_FILL : FASTER_FILL}
                      opacity={0.75}
                    />
                    <text
                      x={isSlower ? barX - 2 : sx + 2}
                      y={barY + BAR_H / 2 + 3}
                      font-size="8"
                      fill={color}
                      text-anchor={isSlower ? "end" : "start"}
                    >
                      {formatSpeedup(speedup, { unit: "×" }).valueText}
                    </text>
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>

      {/* Legend */}
      <div class="mt-2 flex flex-wrap gap-3 text-xs text-[var(--bb-data-fg-muted)]">
        <span>Baseline: <strong>{results[baselineIdx]?.platform}</strong></span>
        {nonBaselineResults.map((r, i) => {
          const colorIdx = i < baselineIdx ? i : i + 1;
          const color = paletteColor(colorIdx);
          return (
            <span key={r.platform} class="flex items-center gap-1">
              <span class="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: color }} />
              {r.platform}
            </span>
          );
        })}
        <span class="ml-2">
          <span class="mr-1 inline-block h-2 w-3 rounded-sm" style={{ backgroundColor: FASTER_FILL }} />
          faster than baseline
        </span>
        <span>
          <span class="mr-1 inline-block h-2 w-3 rounded-sm" style={{ backgroundColor: SLOWER_FILL }} />
          slower than baseline
        </span>
      </div>
    </div>
  );
}

function SpeedupParityState({
  baseline,
  candidates,
  speedupCount,
}: {
  baseline: string;
  candidates: string[];
  speedupCount: number;
}) {
  return (
    <div class="rounded-lg panel-muted p-4 text-sm">
      <p class="font-semibold text-[var(--bb-data-fg-primary)]">No meaningful per-query speedup difference</p>
      <p class="mt-1 text-[var(--bb-data-fg-muted)]">
        All {speedupCount.toLocaleString()} compared query speedups are 1.00× versus baseline {baseline}.
      </p>
      <p class="mt-2 text-xs text-[var(--bb-data-fg-muted)]">
        Baseline: <strong>{baseline}</strong>
        {candidates.length > 0 && <> · Compared with {candidates.join(", ")}</>}
      </p>
    </div>
  );
}
