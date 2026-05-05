// ---------------------------------------------------------------------------
// PercentileLadder - per-platform P50/P90/P95/P99 ladder chart
//
// Visual design: for each platform, render 4 concentric horizontal bars
// at P99 (lightest), P95, P90, and P50 (darkest/innermost) on a shared
// log-scale x-axis.  This "ladder rung" layout makes it immediately obvious
// when P99 tail latency dwarfs the median.
//
// Data source: BenchmarkSummary.platforms[i].percentile_stats (pre-computed
// by the pipeline).  No TS-side percentile math - pure renderer.
// ---------------------------------------------------------------------------

import type { PercentileStats } from "@/types";
import { useElementSize } from "@/lib/useElementSize";
import { paletteColor } from "@/lib/chartTheme";
import { buildLogLatencyScale, logLatencyFraction, logLatencyTicks } from "@/lib/chartMath";

// Neutral gray for opacity-only legend swatches (shows opacity levels, not platform identity).
const LEGEND_SWATCH_COLOR = "#6b7280"; // Tailwind gray-500

export interface PercentileStatsRow {
  /** Stable per-result identifier, used as the row's React key so that two
   *  rows for the same platform with different tuning_modes (variants) do
   *  not collide on `key={platform}`. */
  result_id: string;
  platform: string;
  percentile_stats: PercentileStats;
  colorIdx?: number;
}

interface Props {
  rows: PercentileStatsRow[];
}

// Opacity levels for each rung (P99 outermost → lightest, P50 innermost → darkest).
const RUNG_OPACITY = [0.18, 0.32, 0.5, 1.0] as const; // P99, P95, P90, P50
const PERCENTILE_LABELS = ["P99", "P95", "P90", "P50"] as const;

const ROW_H = 36;
const LABEL_W = 140;
const AXIS_H = 22;
const PADDING_TOP = 28; // space for legend

export function PercentileLadder({ rows }: Props) {
  const [containerRef, { width: containerWidth }] = useElementSize();
  const drawWidth = Math.max(containerWidth, 400);

  if (rows.length === 0) return null;

  const maxP99 = Math.max(...rows.map((r) => r.percentile_stats.p99));
  // logMin is pinned to 0.1ms so
  // the axis always starts at 0.1ms regardless of the fastest p50 observed.
  // This keeps the ladder visually anchored to a shared left edge across
  // benchmarks and prevents sub-ms platforms from stretching their rungs
  // to fill the whole area.
  const scale = buildLogLatencyScale([0.1, maxP99], { minValue: 0.1, maxValue: maxP99 * 1.05 });
  if (scale === null) return null;
  const logScale = scale;

  const barAreaWidth = drawWidth - LABEL_W - 8;

  function xForMs(ms: number): number {
    return LABEL_W + logLatencyFraction(ms, logScale) * barAreaWidth;
  }

  const totalHeight = PADDING_TOP + rows.length * ROW_H + AXIS_H;

  const axisTicks = logLatencyTicks(logScale, 0.1);

  return (
    <div ref={containerRef} class="w-full overflow-x-auto">
      <svg width={drawWidth} height={totalHeight} role="img" aria-label="Percentile latency ladder chart">
        {/* Legend */}
        <g transform="translate(0, 4)">
          {PERCENTILE_LABELS.map((label, li) => {
            const opacity = RUNG_OPACITY[li];
            return (
              <g key={label} transform={`translate(${LABEL_W + li * 56}, 0)`}>
                <rect width={14} height={10} y={3} fill={LEGEND_SWATCH_COLOR} opacity={opacity} rx={1} />
                <text x={18} y={12} class="text-[10px] fill-gray-600 font-mono">
                  {label}
                </text>
              </g>
            );
          })}
        </g>

        {/* Platform rows */}
        {rows.map((row, ri) => {
          const color = paletteColor(row.colorIdx ?? ri);
          const y = PADDING_TOP + ri * ROW_H;
          const midY = y + ROW_H * 0.5;
          const barH = ROW_H * 0.55;

          // Draw P99 → P95 → P90 → P50 (widest first, darkest last)
          const rungs: { label: string; ms: number; opacity: number }[] = [
            { label: "p99", ms: row.percentile_stats.p99, opacity: RUNG_OPACITY[0] },
            { label: "p95", ms: row.percentile_stats.p95, opacity: RUNG_OPACITY[1] },
            { label: "p90", ms: row.percentile_stats.p90, opacity: RUNG_OPACITY[2] },
            { label: "p50", ms: row.percentile_stats.p50, opacity: RUNG_OPACITY[3] },
          ];

          return (
            <g key={row.result_id} data-result-id={row.result_id}>
              {/* Platform label */}
              <text
                x={LABEL_W - 6}
                y={midY + 4}
                textAnchor="end"
                class="text-xs fill-gray-700"
                style={{ fontSize: "11px" }}
              >
                {row.platform.length > 18 ? row.platform.slice(0, 17) + "…" : row.platform}
              </text>

              {/* Rung bars */}
              {rungs.map(({ label, ms, opacity }) => {
                const x1 = xForMs(0.1);
                const x2 = xForMs(ms);
                const barWidth = Math.max(2, x2 - x1);
                return (
                  <rect
                    key={label}
                    x={x1}
                    y={midY - barH / 2}
                    width={barWidth}
                    height={barH}
                    fill={color}
                    opacity={opacity}
                    rx={2}
                  />
                );
              })}

              {/* P50 value label */}
              <text
                x={xForMs(row.percentile_stats.p50) + 4}
                y={midY + 4}
                class="text-[10px] fill-gray-600 font-mono"
                style={{ fontSize: "10px" }}
              >
                {row.percentile_stats.p50 >= 1000
                  ? `${(row.percentile_stats.p50 / 1000).toFixed(1)}s`
                  : `${row.percentile_stats.p50.toFixed(1)}ms`}
              </text>

              {/* Separator line */}
              {ri < rows.length - 1 && (
                <line x1={0} y1={y + ROW_H} x2={drawWidth} y2={y + ROW_H} stroke="#e5e7eb" strokeWidth={1} />
              )}
            </g>
          );
        })}

        {/* X-axis */}
        <g transform={`translate(0, ${PADDING_TOP + rows.length * ROW_H})`}>
          <line x1={LABEL_W} y1={0} x2={drawWidth - 4} y2={0} stroke="#d1d5db" strokeWidth={1} />
          {axisTicks.map((ms) => {
            const x = xForMs(ms);
            return (
              <g key={ms}>
                <line x1={x} y1={0} x2={x} y2={4} stroke="#9ca3af" strokeWidth={1} />
                <text
                  x={x}
                  y={16}
                  textAnchor="middle"
                  class="text-[10px] fill-gray-500 font-mono"
                  style={{ fontSize: "10px" }}
                >
                  {ms >= 1000 ? `${ms / 1000}s` : `${ms}ms`}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
