// ---------------------------------------------------------------------------
// CDFChart - empirical CDF of per-query latency per platform
//
// X axis: latency in ms (log2 scale), Y axis: cumulative percentage (0-100%).
// One stepped line per platform, computed from BenchmarkSummary.platforms[i].timings.
//
// Math: sort per-platform timing values, assign cumulative fraction (i+1)/n.
// Python reference: textcharts.cdf_chart ECDF computation.
// ---------------------------------------------------------------------------

import type { BenchmarkSummary } from "@/types";
import { useElementSize } from "@/lib/useElementSize";
import { axisLabelAnchor, chartFrame } from "@/lib/chartFrame";
import { timeSeriesColor } from "@/lib/chartTheme";
import { buildLogLatencyScale, computeECDFPoints, logLatencyFraction, logLatencyTicks } from "@/lib/chartMath";
import { formatTimingExclusion, isTimingDisplayable, platformTimingValue } from "@/lib/displayEligibility";
import { formatLatencyMs } from "@/lib/metricFormatters";
import { formatRunIdentityLabelsForCohort, preserveUniqueAfterTruncation } from "@/lib/runIdentity";

const Y_TICKS_PCT = [0, 25, 50, 75, 100];

const LABEL_W = 36;
const AXIS_H = 28;
const PADDING_TOP = 8;
const PADDING_RIGHT = 12;
const PLOT_H = 180;

interface Props {
  summary: BenchmarkSummary;
}

export function CDFChart({ summary }: Props) {
  const [containerRef, { width: containerWidth }] = useElementSize();
  const frame = chartFrame(containerWidth);
  const w = frame.width;

  const cohortLabels = formatRunIdentityLabelsForCohort(
    summary.platforms.map((platform) => ({ ...platform, scale_factor: summary.scale_factor })),
  );
  const displayLabels = preserveUniqueAfterTruncation(
    cohortLabels.map((label) => label.disambiguated),
    15,
  );
  const series = summary.platforms
    .map((p, i) => ({
      label: displayLabels[i] ?? p.platform,
      fullLabel: cohortLabels[i]?.full ?? p.platform,
      color: timeSeriesColor(i),
      isDisplayable: isTimingDisplayable(p),
      points: computeECDFPoints(summary.query_ids.map((queryId) => platformTimingValue(p, queryId))),
    }))
    .filter((s) => s.isDisplayable && s.points.length > 0);

  if (series.length === 0) return null;
  const excludedRows = summary.platforms.filter((platform) => !isTimingDisplayable(platform));

  const allMs = series.flatMap((s) => s.points.map((p) => p.x));
  const scale = buildLogLatencyScale(allMs, { lowerPad: 0.2, upperPad: 0.2 });
  if (scale === null) return null;
  const logScale = scale;

  const plotW = w - LABEL_W - PADDING_RIGHT;
  const totalH = PADDING_TOP + PLOT_H + AXIS_H;

  function xFor(ms: number): number {
    return LABEL_W + logLatencyFraction(ms, logScale) * plotW;
  }
  function yFor(pct: number): number {
    return PADDING_TOP + PLOT_H * (1 - pct / 100);
  }

  const xTicks = logLatencyTicks(logScale);

  return (
    <div ref={containerRef} class="w-full">
      <svg
        class="bb-chart-svg"
        width="100%"
        height={totalH}
        viewBox={`0 0 ${w} ${totalH}`}
        role="img"
        aria-label="Cumulative distribution of per-query latency"
      >
        {/* Y-axis grid lines + labels */}
        {Y_TICKS_PCT.map((pct) => {
          const y = yFor(pct);
          return (
            <g key={pct}>
              <line x1={LABEL_W} y1={y} x2={w - PADDING_RIGHT} y2={y} stroke="var(--bb-chart-grid)" stroke-width={1} />
              <text x={LABEL_W - 4} y={y + 4} text-anchor="end" style={{ fontSize: "10px", fill: "var(--bb-chart-label-muted)" }}>
                {pct}%
              </text>
            </g>
          );
        })}

        {/* CDF stepped lines - true ECDF: horizontal then vertical jumps */}
        {series.map((s) => {
          const d = s.points
            .map((p, i) => {
              const x = xFor(p.x).toFixed(1);
              const y = yFor(p.y).toFixed(1);
              if (i === 0) return `M${x},${y}`;
              // Step: horizontal to new x (staying at prev y), then vertical to new y
              return `H${x} V${y}`;
            })
            .join(" ");
          return (
            <path key={s.label} d={d} stroke={s.color} stroke-width={2} fill="none">
              <title>{s.fullLabel}</title>
            </path>
          );
        })}

        {/* X-axis */}
        <g transform={`translate(0, ${PADDING_TOP + PLOT_H})`}>
          <line x1={LABEL_W} y1={0} x2={w - PADDING_RIGHT} y2={0} stroke="var(--bb-chart-grid)" stroke-width={1} />
          {xTicks.map((ms) => {
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
                  {formatLatencyMs(ms, { subMillisecond: "compact" }).valueText}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {/* Legend. One SVG row at a fixed 130-unit stride silently drops every
          entry past the drawing width, and the entries it drops are the slowest
          runs - the ones a reader is most likely asking about. HTML wraps, so
          the key always holds every series, matching StackedPhase and
          TimeSeries. */}
      <ul class="mt-1.5 flex list-none flex-wrap gap-x-3 gap-y-1 p-0 text-xs text-[var(--bb-data-fg-muted)]">
        {series.map((s) => (
          <li key={s.label} class="flex items-center gap-1.5" title={s.fullLabel}>
            <span
              class="inline-block h-0.5 w-4 flex-shrink-0 rounded-sm"
              style={{ backgroundColor: s.color }}
            />
            {s.label}
          </li>
        ))}
      </ul>
      {excludedRows.length > 0 && (
        <p class="mt-1 text-[10px] text-[var(--bb-data-fg-subtle)]">
          {excludedRows.length} row(s) excluded from CDF: {formatTimingExclusion(excludedRows[0])}
        </p>
      )}
    </div>
  );
}
