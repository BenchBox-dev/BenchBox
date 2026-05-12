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
import { paletteColor } from "@/lib/chartTheme";
import { buildLogLatencyScale, computeBoxStats, logLatencyFraction, logLatencyTicks } from "@/lib/chartMath";
import { formatTimingExclusion, isTimingDisplayable, platformTimingValue } from "@/lib/displayEligibility";
import { formatLatencyMs } from "@/lib/metricFormatters";
import { formatRunIdentityLabelsForCohort, preserveUniqueAfterTruncation } from "@/lib/runIdentity";

const LABEL_W = 144;
const ROW_H = 48;
const AXIS_H = 24;
const PADDING_TOP = 12;
const PADDING_RIGHT = 12;

interface Props {
  summary: BenchmarkSummary;
}

export function DistributionBox({ summary }: Props) {
  const [containerRef, { width: containerWidth }] = useElementSize();
  const w = Math.max(containerWidth, 400);

  const cohortLabels = formatRunIdentityLabelsForCohort(
    summary.platforms.map((platform) => ({ ...platform, scale_factor: summary.scale_factor })),
  );
  // Truncation budget = 20 chars (LABEL_W=144 px / ~7 px per char). When
  // truncation would collapse otherwise-unique cohort identities to the same
  // prefix (e.g. four "DataFusion v53.0.0 …"), preserveUniqueAfterTruncation
  // preserves the distinguishing suffix (date or short id) inside the same
  // budget. Audit finding #7.
  const rawLabels = summary.platforms.map((p, i) => cohortLabels[i]?.disambiguated ?? p.platform);
  const displayLabels = preserveUniqueAfterTruncation(rawLabels, 20);
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

  const plotW = w - LABEL_W - PADDING_RIGHT;
  const totalH = PADDING_TOP + rows.length * ROW_H + AXIS_H;

  function xFor(ms: number): number {
    return LABEL_W + logLatencyFraction(ms, logScale) * plotW;
  }

  const xTicks = logLatencyTicks(logScale);

  return (
    <div ref={containerRef} class="w-full overflow-x-auto">
      <svg class="bb-chart-svg" width={w} height={totalH} role="img" aria-label="Distribution box plots of per-query latency">
        {rows.map((row, ri) => {
          const y = PADDING_TOP + ri * ROW_H;
          const midY = y + ROW_H * 0.5;
          const boxH = ROW_H * 0.46;
          const { min, q1, median, q3, max } = row.stats;

          return (
            <g key={row.label}>
              {/* Platform label */}
              <text x={LABEL_W - 6} y={midY + 4} textAnchor="end" style={{ fontSize: "11px", fill: "#374151" }}>
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
                strokeWidth={1.5}
                strokeDasharray="3 2"
              />
              {/* Min cap */}
              <line x1={xFor(min)} y1={midY - 5} x2={xFor(min)} y2={midY + 5} stroke={row.color} strokeWidth={1.5} />
              {/* Max cap */}
              <line x1={xFor(max)} y1={midY - 5} x2={xFor(max)} y2={midY + 5} stroke={row.color} strokeWidth={1.5} />

              {/* IQR box (Q1-Q3) */}
              <rect
                x={xFor(q1)}
                y={midY - boxH / 2}
                width={Math.max(2, xFor(q3) - xFor(q1))}
                height={boxH}
                fill={row.color}
                fillOpacity={0.18}
                stroke={row.color}
                strokeWidth={1.5}
                rx={2}
              />

              {/* Median line */}
              <line
                x1={xFor(median)}
                y1={midY - boxH / 2}
                x2={xFor(median)}
                y2={midY + boxH / 2}
                stroke={row.color}
                strokeWidth={2.5}
              />

              {/* Separator */}
              {ri < rows.length - 1 && (
                <line x1={0} y1={y + ROW_H} x2={w} y2={y + ROW_H} stroke="#e5e7eb" strokeWidth={1} />
              )}
            </g>
          );
        })}

        {/* X-axis */}
        <g transform={`translate(0, ${PADDING_TOP + rows.length * ROW_H})`}>
          <line x1={LABEL_W} y1={0} x2={w - PADDING_RIGHT} y2={0} stroke="#d1d5db" strokeWidth={1} />
          {xTicks.map((ms) => {
            const x = xFor(ms);
            return (
              <g key={ms}>
                <line x1={x} y1={0} x2={x} y2={4} stroke="#9ca3af" strokeWidth={1} />
                <text x={x} y={16} textAnchor="middle" style={{ fontSize: "10px", fill: "#6b7280" }}>
                  {formatLatencyMs(ms, { subMillisecond: "compact" }).valueText}
                </text>
              </g>
            );
          })}
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
