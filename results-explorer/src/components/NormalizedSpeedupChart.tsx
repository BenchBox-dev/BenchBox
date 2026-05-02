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

import { speedupRatio } from "@/lib/chartMath";
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

  if (queries.length === 0 || results.length < 2) return null;

  const BAR_H = 16;
  const BAR_GAP = 4;
  const LABEL_W = 60;
  const AXIS_H = 24;
  const PADDING = 8;

  const nonBaselineCount = results.length - 1;
  const rowHeight = BAR_H * nonBaselineCount + BAR_GAP * (nonBaselineCount + 1);
  const totalHeight = AXIS_H + queries.length * rowHeight + PADDING;

  // Compute speedup entries
  const entries: SpeedupEntry[] = queries.map(({ queryId, timings }) => {
    const baselineT = timings[baselineIdx];
    const baselineMs = baselineT && baselineT.ms > 0 ? baselineT.ms : null;
    const speedups = timings
      .filter((_, i) => i !== baselineIdx)
      .map((t) => speedupRatio(baselineMs, t?.ms ?? null));
    return { queryId, speedups };
  });

  const nonBaselineResults = results.filter((_, i) => i !== baselineIdx);

  return (
    <div ref={containerRef} class="w-full overflow-x-auto">
      <svg
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
                {stop}×
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
                      {speedup.toFixed(2)}×
                    </text>
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>

      {/* Legend */}
      <div class="mt-2 flex flex-wrap gap-3 text-xs text-gray-500">
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
          <span class="inline-block h-2 w-3 rounded-sm mr-1" style={{ backgroundColor: FASTER_FILL }} />faster than baseline
        </span>
        <span>
          <span class="inline-block h-2 w-3 rounded-sm mr-1" style={{ backgroundColor: SLOWER_FILL }} />slower than baseline
        </span>
      </div>
    </div>
  );
}
