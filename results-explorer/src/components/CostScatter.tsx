// ---------------------------------------------------------------------------
// CostScatter - scatter plot of cost_usd vs performance metric
//
// X axis: cost_usd (USD).  Y axis: power_score (higher=better) or
// display_geomean_ms (lower=better) depending on the benchmark family.
// One point per platform.  Section is hidden entirely when no cost data.
//
// Anti-pattern prevented: never renders when all cost_usd values are null.
//
// Python reference: textcharts.scatter_plot.ScatterPlot
// ---------------------------------------------------------------------------

import type { BenchmarkSummary } from "@/types";
import { useElementSize } from "@/lib/useElementSize";
import { paletteColor } from "@/lib/chartTheme";

const AXIS_W = 54;
const AXIS_H = 32;
const PADDING_TOP = 20;
const PADDING_RIGHT = 16;
const CHART_H = 180;

interface Props {
  summary: BenchmarkSummary;
}

export function CostScatter({ summary }: Props) {
  const [containerRef, { width: containerWidth }] = useElementSize();
  const w = Math.max(containerWidth, 400);

  // Primary metric comes from the canonical DuckDB-persisted ranking row.
  // Fallback is safe: every result has a display_geomean_ms.
  const metric = summary.ranking?.primary_metric ?? "display_geomean_ms";
  const higherIsBetter = metric === "power_score";

  type ScatterPoint = {
    result_id: string;
    platform: string;
    cost: number;
    perf: number;
    color: string;
  };

  const pts: ScatterPoint[] = summary.platforms
    .map((p, i) => ({
      result_id: p.result_id,
      platform: p.platform,
      cost: p.cost_usd,
      perf: metric === "power_score" ? p.power_score : p.display_geomean_ms,
      color: paletteColor(i),
    }))
    .filter(
      (p): p is ScatterPoint =>
        p.cost !== null && p.cost > 0 && p.perf !== null,
    ) as ScatterPoint[];

  if (pts.length === 0) {
    return (
      <p class="text-sm text-gray-400 italic">
        No cost data available - cost_usd must be populated in the result bundle.
      </p>
    );
  }

  const costs = pts.map((p) => p.cost);
  const perfs = pts.map((p) => p.perf);
  const minCost = Math.min(...costs);
  const maxCost = Math.max(...costs);
  const minPerf = Math.min(...perfs);
  const maxPerf = Math.max(...perfs);
  const costPad = (maxCost - minCost) * 0.1 || maxCost * 0.1 || 0.01;
  const perfPad = (maxPerf - minPerf) * 0.1 || maxPerf * 0.1 || 1;

  const xMin = Math.max(0, minCost - costPad);
  const xMax = maxCost + costPad;
  const yMin = Math.max(0, minPerf - perfPad);
  const yMax = maxPerf + perfPad;
  const xRange = xMax - xMin || 1;
  const yRange = yMax - yMin || 1;

  const plotW = w - AXIS_W - PADDING_RIGHT;
  const totalH = PADDING_TOP + CHART_H + AXIS_H;

  function xFor(cost: number): number {
    return AXIS_W + ((cost - xMin) / xRange) * plotW;
  }

  function yFor(perf: number): number {
    const normalized = (perf - yMin) / yRange;
    // Higher perf → top of chart when higher-is-better
    const pos = higherIsBetter ? normalized : 1 - normalized;
    return PADDING_TOP + CHART_H * (1 - pos);
  }

  const metricLabel = metric === "power_score" ? "Power@Size (↑ better)" : "Geomean ms (↓ better)";

  return (
    <div ref={containerRef} class="w-full overflow-x-auto">
      <svg
        width={w}
        height={totalH}
        role="img"
        aria-label={`Cost vs ${metricLabel} scatter plot`}
      >
        {/* Grid - label orientation flips with higherIsBetter so the top
            of the chart always shows the better-performance value. */}
        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const y = PADDING_TOP + f * CHART_H;
          const val = higherIsBetter ? yMax - f * yRange : yMin + f * yRange;
          const label =
            metric === "power_score"
              ? val.toLocaleString(undefined, { maximumFractionDigits: 0 })
              : val >= 1000
                ? `${(val / 1000).toFixed(1)}s`
                : `${val.toFixed(0)}ms`;
          return (
            <g key={f}>
              <line
                x1={AXIS_W}
                y1={y}
                x2={w - PADDING_RIGHT}
                y2={y}
                stroke="#f3f4f6"
                strokeWidth={1}
              />
              <text
                x={AXIS_W - 4}
                y={y + 4}
                textAnchor="end"
                style={{ fontSize: "9px", fill: "#9ca3af" }}
              >
                {label}
              </text>
            </g>
          );
        })}

        {/* Scatter points */}
        {pts.map((p) => {
          const cx = xFor(p.cost);
          const cy = yFor(p.perf);
          const shortLabel = p.platform.length > 10 ? `${p.platform.slice(0, 9)}…` : p.platform;
          return (
            <g key={p.result_id}>
              <circle cx={cx} cy={cy} r={7} fill={p.color} fillOpacity={0.85}>
                <title>{`${p.platform}: $${p.cost.toFixed(2)} / ${p.perf.toFixed(1)}`}</title>
              </circle>
              <text
                x={cx}
                y={cy - 11}
                textAnchor="middle"
                style={{ fontSize: "10px", fill: "#374151" }}
              >
                {shortLabel}
              </text>
            </g>
          );
        })}

        {/* Axes */}
        <line
          x1={AXIS_W}
          y1={PADDING_TOP}
          x2={AXIS_W}
          y2={PADDING_TOP + CHART_H}
          stroke="#d1d5db"
          strokeWidth={1}
        />
        <line
          x1={AXIS_W}
          y1={PADDING_TOP + CHART_H}
          x2={w - PADDING_RIGHT}
          y2={PADDING_TOP + CHART_H}
          stroke="#d1d5db"
          strokeWidth={1}
        />

        {/* X-axis labels */}
        {[0, 0.5, 1].map((f) => {
          const x = AXIS_W + f * plotW;
          const cost = xMin + f * xRange;
          return (
            <g key={f}>
              <line
                x1={x}
                y1={PADDING_TOP + CHART_H}
                x2={x}
                y2={PADDING_TOP + CHART_H + 4}
                stroke="#9ca3af"
                strokeWidth={1}
              />
              <text
                x={x}
                y={PADDING_TOP + CHART_H + 16}
                textAnchor="middle"
                style={{ fontSize: "10px", fill: "#6b7280" }}
              >
                ${cost.toFixed(2)}
              </text>
            </g>
          );
        })}
        <text
          x={AXIS_W + plotW / 2}
          y={PADDING_TOP + CHART_H + AXIS_H - 2}
          textAnchor="middle"
          style={{ fontSize: "10px", fill: "#9ca3af" }}
        >
          Cost (USD)
        </text>

        {/* Y-axis label */}
        <text
          x={0}
          y={0}
          style={{ fontSize: "9px", fill: "#9ca3af" }}
          transform={`rotate(-90) translate(${-(PADDING_TOP + CHART_H / 2)}, 11)`}
          textAnchor="middle"
        >
          {metricLabel}
        </text>
      </svg>
    </div>
  );
}
