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
import { timeSeriesColor } from "@/lib/chartTheme";
import { buildLogLatencyScale, computeECDFPoints, logLatencyFraction, logLatencyTicks } from "@/lib/chartMath";
import { formatRunIdentitiesForCohort } from "@/lib/runIdentity";

const Y_TICKS_PCT = [0, 25, 50, 75, 100];

const LABEL_W = 36;
const AXIS_H = 28;
const PADDING_TOP = 30; // legend space
const PADDING_RIGHT = 12;
const PLOT_H = 180;

interface Props {
  summary: BenchmarkSummary;
}

export function CDFChart({ summary }: Props) {
  const [containerRef, { width: containerWidth }] = useElementSize();
  const w = Math.max(containerWidth, 400);

  const cohortLabels = formatRunIdentitiesForCohort(
    summary.platforms.map((platform) => ({ ...platform, scale_factor: summary.scale_factor })),
    "chart",
  );
  const series = summary.platforms
    .map((p, i) => ({
      label: cohortLabels[i] ?? p.platform,
      color: timeSeriesColor(i),
      points: computeECDFPoints(Object.values(p.timings)),
    }))
    .filter((s) => s.points.length > 0);

  if (series.length === 0) return null;

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
    <div ref={containerRef} class="w-full overflow-x-auto">
      <svg class="bb-chart-svg" width={w} height={totalH} role="img" aria-label="Cumulative distribution of per-query latency">
        {/* Y-axis grid lines + labels */}
        {Y_TICKS_PCT.map((pct) => {
          const y = yFor(pct);
          return (
            <g key={pct}>
              <line x1={LABEL_W} y1={y} x2={w - PADDING_RIGHT} y2={y} stroke="#e5e7eb" strokeWidth={1} />
              <text x={LABEL_W - 4} y={y + 4} textAnchor="end" style={{ fontSize: "10px", fill: "#9ca3af" }}>
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
          return <path key={s.label} d={d} stroke={s.color} strokeWidth={2} fill="none" />;
        })}

        {/* X-axis */}
        <g transform={`translate(0, ${PADDING_TOP + PLOT_H})`}>
          <line x1={LABEL_W} y1={0} x2={w - PADDING_RIGHT} y2={0} stroke="#d1d5db" strokeWidth={1} />
          {xTicks.map((ms) => {
            const x = xFor(ms);
            return (
              <g key={ms}>
                <line x1={x} y1={0} x2={x} y2={4} stroke="#9ca3af" strokeWidth={1} />
                <text x={x} y={16} textAnchor="middle" style={{ fontSize: "10px", fill: "#6b7280" }}>
                  {ms >= 1000 ? `${ms / 1000}s` : `${ms}ms`}
                </text>
              </g>
            );
          })}
        </g>

        {/* Legend */}
        <g transform="translate(0, 8)">
          {series.map((s, i) => (
            <g key={s.label} transform={`translate(${LABEL_W + i * 130}, 0)`}>
              <line x1={0} y1={6} x2={16} y2={6} stroke={s.color} strokeWidth={2} />
              <text x={20} y={10} style={{ fontSize: "11px", fill: "#374151" }}>
                {s.label.length > 15 ? `${s.label.slice(0, 14)}…` : s.label}
              </text>
            </g>
          ))}
        </g>
      </svg>
    </div>
  );
}
