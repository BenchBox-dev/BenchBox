// ---------------------------------------------------------------------------
// DistributionBox - horizontal box plots of per-query latency distribution
//
// One box-and-whisker per platform, stacked vertically.
// Whiskers = raw min / max; box = Q1-Q3; vertical line = median.
// X axis: log2-scale latency (ms).
//
// Data: computed from BenchmarkSummary.platforms[i].timings values via
//       computeBoxStats.  Quartiles match textcharts.percentile_ladder.
//       compute_percentile; min/max are raw extremes (no IQR whiskering or
//       outlier detection - see chartMath.ts for the divergence rationale).
// Parity: tests/parity/fixtures/box_stats.json (generator: compute_box_stats
//         in tests/parity/generate_visualization_fixtures.py).
// ---------------------------------------------------------------------------

import type { BenchmarkSummary } from "@/types";
import { useElementSize } from "@/lib/useElementSize";
import { axisLabelAnchor, barRowLayout, chartFrame } from "@/lib/chartFrame";
import { paletteColor } from "@/lib/chartTheme";
import { buildLogLatencyScale, computeBoxStats, logLatencyFraction, logLatencyTicks } from "@/lib/chartMath";
import { formatTimingExclusion, isTimingDisplayable, platformTimingValue } from "@/lib/displayEligibility";
import { formatLatencyAxisLabels } from "@/lib/metricFormatters";
import { formatRunIdentityLabelsForCohort, preserveUniqueAfterTruncation } from "@/lib/runIdentity";

const LABEL_W = 200;
const ROW_H = 48;
// +12px over the tick-label row for the axis title (see the x-axis title
// below, matching the "Normalized cost (USD)" convention in CostScatter).
const AXIS_H = 36;
const PADDING_TOP = 12;
const PADDING_RIGHT = 12;

interface Props {
  summary: BenchmarkSummary;
}

export function DistributionBox({ summary }: Props) {
  const [containerRef, { width: containerWidth }] = useElementSize();
  const frame = chartFrame(containerWidth);
  const w = frame.width;
  const layout = barRowLayout(frame, { labelWidth: LABEL_W, rowHeight: ROW_H, valueTrail: PADDING_RIGHT });

  const cohortLabels = formatRunIdentityLabelsForCohort(
    summary.platforms.map((platform) => ({ ...platform, scale_factor: summary.scale_factor })),
  );
  // Truncation budget = 26 chars (LABEL_W=200 px / ~7.5 px per char at the
  // 13px label size, which matches the speed-and-throughput table beside it).
  // When truncation would collapse otherwise-unique cohort identities to the same
  // prefix (e.g. four "DataFusion v53.0.0 …"), preserveUniqueAfterTruncation
  // preserves the distinguishing suffix (date or short id) inside the same
  // budget. Audit finding #7.
  const rawLabels = summary.platforms.map((p, i) => cohortLabels[i]?.disambiguated ?? p.platform);
  const displayLabels = preserveUniqueAfterTruncation(rawLabels, 26);
  const rows = summary.platforms
    .map((p, i) => ({
      label: displayLabels[i] ?? p.platform,
      fullLabel: cohortLabels[i]?.full ?? rawLabels[i] ?? p.platform,
      color: paletteColor(i),
      isDisplayable: isTimingDisplayable(p),
      stats: computeBoxStats(summary.query_ids.map((queryId) => platformTimingValue(p, queryId))),
    }))
    .filter((r) => r.isDisplayable && r.stats !== null) as {
    label: string;
    fullLabel: string;
    color: string;
    isDisplayable: boolean;
    stats: NonNullable<ReturnType<typeof computeBoxStats>>;
  }[];

  if (rows.length === 0) return null;
  const excludedRows = summary.platforms.filter((platform) => !isTimingDisplayable(platform));

  const allMs = rows.flatMap((r) => [r.stats.min, r.stats.q1, r.stats.median, r.stats.q3, r.stats.max]);
  const scale = buildLogLatencyScale(allMs, { lowerPad: 0.3, upperPad: 0.3 });
  if (scale === null) return null;
  const logScale = scale;

  const plotW = layout.plotWidth;
  const totalH = PADDING_TOP + rows.length * layout.rowHeight + AXIS_H;

  function xFor(ms: number): number {
    return layout.plotX + logLatencyFraction(ms, logScale) * plotW;
  }

  const xTicks = logLatencyTicks(logScale);
  const tickLabels = formatLatencyAxisLabels(xTicks);

  return (
    <div ref={containerRef} class="w-full">
      <svg
        class="bb-chart-svg"
        width="100%"
        height={totalH}
        viewBox={`0 0 ${w} ${totalH}`}
        role="img"
        aria-label="Distribution box plots of per-query latency"
      >
        {rows.map((row, ri) => {
          const y = PADDING_TOP + ri * layout.rowHeight;
          const midY = y + layout.barCenter;
          const boxH = ROW_H * 0.46;
          const { min, q1, median, q3, max } = row.stats;

          return (
            <g key={row.label}>
              {/* Platform label */}
              <text
                x={layout.labelAbove ? 0 : LABEL_W - 6}
                y={y + layout.labelBaseline}
                text-anchor={layout.labelAbove ? "start" : "end"}
                style={{ fontSize: "13px", fill: "var(--bb-chart-label)" }}
              >
                <title>{row.fullLabel}</title>
                {row.label}
              </text>

              {/* Whisker (min-max) */}
              <line
                x1={xFor(min)}
                y1={midY}
                x2={xFor(max)}
                y2={midY}
                stroke={row.color}
                stroke-width={1.5}
                stroke-dasharray="3 2"
              />
              {/* Min cap */}
              <line x1={xFor(min)} y1={midY - 5} x2={xFor(min)} y2={midY + 5} stroke={row.color} stroke-width={1.5} />
              {/* Max cap */}
              <line x1={xFor(max)} y1={midY - 5} x2={xFor(max)} y2={midY + 5} stroke={row.color} stroke-width={1.5} />

              {/* IQR box (Q1-Q3) */}
              <rect
                x={xFor(q1)}
                y={midY - boxH / 2}
                width={Math.max(2, xFor(q3) - xFor(q1))}
                height={boxH}
                fill={row.color}
                fill-opacity={0.18}
                stroke={row.color}
                stroke-width={1.5}
                rx={2}
              />

              {/* Median line */}
              <line
                x1={xFor(median)}
                y1={midY - boxH / 2}
                x2={xFor(median)}
                y2={midY + boxH / 2}
                stroke={row.color}
                stroke-width={2.5}
              />

              {/* Separator */}
              {ri < rows.length - 1 && (
                <line
                  x1={0}
                  y1={y + layout.rowHeight}
                  x2={w}
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
          <line x1={layout.plotX} y1={0} x2={layout.plotX + plotW} y2={0} stroke="var(--bb-chart-grid)" stroke-width={1} />
          {xTicks.map((ms, index) => {
            const x = xFor(ms);
            return (
              <g key={ms}>
                <line x1={x} y1={0} x2={x} y2={4} stroke="var(--bb-chart-label-muted)" stroke-width={1} />
                <text
                  x={x}
                  y={16}
                  text-anchor={axisLabelAnchor(x, w)}
                  style={{ fontSize: "10px", fill: "var(--bb-chart-axis)" }}
                >
                  {tickLabels[index]}
                </text>
              </g>
            );
          })}
          <text
            x={layout.plotX + plotW / 2}
            y={30}
            text-anchor="middle"
            style={{ fontSize: "10px", fill: "var(--bb-chart-label-muted)" }}
          >
            Latency (ms, log scale)
          </text>
        </g>
      </svg>
      <p class="mt-1 text-[10px] text-[var(--bb-data-fg-subtle)]">
        Box: Q1-Q3 · Line: median · Whiskers: min/max of per-query display latencies
        {excludedRows.length > 0
          ? ` · ${excludedRows.length} row(s) excluded: ${formatTimingExclusion(excludedRows[0])}`
          : ""}
      </p>
    </div>
  );
}
