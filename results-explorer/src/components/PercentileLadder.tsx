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
import { axisLabelAnchor, barRowLayout, chartFrame, edgeSafeValueLabel } from "@/lib/chartFrame";
import { paletteColor } from "@/lib/chartTheme";
import { buildLogLatencyScale, logLatencyFraction, logLatencyTicks } from "@/lib/chartMath";
import { formatLatencyMs, formatLatencyAxisLabels } from "@/lib/metricFormatters";
import { preserveUniqueAfterTruncation } from "@/lib/runIdentity";

// Neutral gray for opacity-only legend swatches (shows opacity levels, not platform identity).
const LEGEND_SWATCH_COLOR = "var(--bb-chart-axis)";

export interface PercentileStatsRow {
  /** Stable per-result identifier, used as the row's React key so that two
   *  rows for the same platform with different tuning_modes (variants) do
   *  not collide on `key={platform}`. */
  result_id: string;
  platform: string;
  /**
   * Cohort-aware label from `formatRunIdentitiesForCohort`. When the row
   * is part of a cohort with duplicate platform names, the caller passes
   * a disambiguated label (e.g. "DataFusion v44 2026-04-12"). Falls back
   * to `platform` when not provided so older callers still render.
   */
  displayLabel?: string;
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
// +12px over the tick-label row for the axis title (see the x-axis title
// below, matching the "Normalized cost (USD)" convention in CostScatter).
const AXIS_H = 34;
const PADDING_TOP = 28; // space for legend

export function PercentileLadder({ rows }: Props) {
  const [containerRef, { width: containerWidth }] = useElementSize();
  const frame = chartFrame(containerWidth);
  const drawWidth = frame.width;
  const layout = barRowLayout(frame, { labelWidth: LABEL_W, rowHeight: ROW_H, valueTrail: 8 });

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

  const barAreaWidth = layout.plotWidth;

  function xForMs(ms: number): number {
    return layout.plotX + logLatencyFraction(ms, logScale) * barAreaWidth;
  }

  const totalHeight = PADDING_TOP + rows.length * layout.rowHeight + AXIS_H;

  const axisTicks = logLatencyTicks(logScale, 0.1);
  const tickLabels = formatLatencyAxisLabels(axisTicks);
  // A label on its own line has the full column to itself; one in the gutter
  // has 140 units. preserveUniqueAfterTruncation keeps the distinguishing
  // suffix inside whichever budget applies.
  const displayLabels = preserveUniqueAfterTruncation(
    rows.map((row) => row.displayLabel ?? row.platform),
    layout.labelAbove ? 32 : 18,
  );

  return (
    <div ref={containerRef} class="w-full">
      <svg
        class="bb-chart-svg"
        width="100%"
        height={totalHeight}
        viewBox={`0 0 ${drawWidth} ${totalHeight}`}
        role="img"
        aria-label="Percentile latency ladder chart"
      >
        {/* Legend */}
        <g transform="translate(0, 4)">
          {PERCENTILE_LABELS.map((label, li) => {
            const opacity = RUNG_OPACITY[li];
            return (
              <g key={label} transform={`translate(${layout.plotX + li * 56}, 0)`}>
                <rect width={14} height={10} y={3} fill={LEGEND_SWATCH_COLOR} opacity={opacity} rx={1} />
                <text x={18} y={12} class="text-[10px] fill-[var(--bb-data-fg-muted)] font-mono">
                  {label}
                </text>
              </g>
            );
          })}
        </g>

        {/* Platform rows */}
        {rows.map((row, ri) => {
          const color = paletteColor(row.colorIdx ?? ri);
          const y = PADDING_TOP + ri * layout.rowHeight;
          const midY = y + layout.barCenter;
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
                x={layout.labelAbove ? 0 : LABEL_W - 6}
                y={y + layout.labelBaseline}
                text-anchor={layout.labelAbove ? "start" : "end"}
                class="text-xs fill-[var(--bb-data-fg-primary)]"
                style={{ fontSize: "11px" }}
              >
                {displayLabels[ri] ?? row.platform}
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
              {/* A p50 close to the axis maximum lands at the end of the plot,
                  where a trailing label would be cropped. */}
              <text
                x={
                  layout.labelAbove
                    ? drawWidth
                    : edgeSafeValueLabel(xForMs(row.percentile_stats.p50), drawWidth, "right", 4).x
                }
                y={layout.labelAbove ? y + layout.labelBaseline : midY + 4}
                text-anchor={
                  layout.labelAbove
                    ? "end"
                    : edgeSafeValueLabel(xForMs(row.percentile_stats.p50), drawWidth, "right", 4).textAnchor
                }
                class="text-[10px] fill-[var(--bb-data-fg-muted)] font-mono"
                style={{ fontSize: "10px" }}
              >
                {formatLatencyMs(row.percentile_stats.p50).valueText}
              </text>

              {/* Separator line */}
              {ri < rows.length - 1 && (
                <line
                  x1={0}
                  y1={y + layout.rowHeight}
                  x2={drawWidth}
                  y2={y + layout.rowHeight}
                  stroke="var(--bb-chart-grid)"
                  stroke-width={1}
                />
              )}
            </g>
          );
        })}

        {/* X-axis */}
        <g transform={`translate(0, ${PADDING_TOP + rows.length * layout.rowHeight})`}>
          <line
            x1={layout.plotX}
            y1={0}
            x2={layout.plotX + barAreaWidth}
            y2={0}
            stroke="var(--bb-chart-grid)"
            stroke-width={1}
          />
          {axisTicks.map((ms, index) => {
            const x = xForMs(ms);
            return (
              <g key={ms}>
                <line x1={x} y1={0} x2={x} y2={4} stroke="var(--bb-chart-label-muted)" stroke-width={1} />
                <text
                  x={x}
                  y={16}
                  text-anchor={axisLabelAnchor(x, drawWidth)}
                  class="text-[10px] fill-[var(--bb-data-fg-subtle)] font-mono"
                  style={{ fontSize: "10px" }}
                >
                  {tickLabels[index]}
                </text>
              </g>
            );
          })}
          <text
            x={layout.plotX + barAreaWidth / 2}
            y={30}
            text-anchor="middle"
            style={{ fontSize: "10px", fill: "var(--bb-chart-label-muted)" }}
          >
            Latency (ms, log scale)
          </text>
        </g>
      </svg>
    </div>
  );
}
