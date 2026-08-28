// ---------------------------------------------------------------------------
// CostScatter - scatter plot of normalized cost vs performance metric
//
// X axis: normalized_cost_usd (USD).  Y axis: power_score (higher=better) or
// display_geomean_ms (lower=better) depending on the benchmark family.
// One point per platform with cost_status=normalized.
//
// Anti-pattern prevented: never plots legacy submitter-supplied cost_usd or
// local not-applicable zeroes as comparable cloud cost.
//
// Python reference: textcharts.scatter_plot.ScatterPlot
// ---------------------------------------------------------------------------

import type { BenchmarkSummary, PlatformRow } from "@/types";
import { useElementSize } from "@/lib/useElementSize";
import { paletteColor } from "@/lib/chartTheme";
import { costModelDisclosure, normalizedCostValue } from "@/lib/costDisplay";
import { formatLatencyMs, formatPowerScore, formatUsd } from "@/lib/metricFormatters";

const AXIS_W = 54;
const AXIS_H = 32;
const PADDING_TOP = 20;
const PADDING_RIGHT = 16;
const CHART_H = 180;

interface Props {
  summary: BenchmarkSummary;
}

type ScatterPoint = {
  result_id: string;
  platform: string;
  cost: number;
  perf: number;
  modelVersion: string | null | undefined;
  scope: string | null | undefined;
  provider: string | null | undefined;
  region: string | null | undefined;
  color: string;
};

export function CostScatter({ summary }: Props) {
  const [containerRef, { width: containerWidth }] = useElementSize();
  const w = Math.max(containerWidth, 400);

  // Primary metric comes from the canonical DuckDB-persisted ranking row.
  // Fallback is safe: every result has a display_geomean_ms.
  const metric = summary.ranking?.primary_metric ?? "display_geomean_ms";
  const higherIsBetter = metric === "power_score";

  const pts: ScatterPoint[] = summary.platforms
    .map((p, i) => {
      const cost = normalizedCostValue(p);
      return {
        result_id: p.result_id,
        platform: p.platform,
        cost,
        perf: metric === "power_score" ? p.power_score : p.display_geomean_ms,
        modelVersion: p.cost_model_version,
        scope: p.cost_scope,
        provider: p.cloud_provider,
        region: p.cloud_region ?? p.pricing_region,
        color: paletteColor(i),
      };
    })
    .filter((p): p is ScatterPoint => p.cost !== null && p.perf !== null) as ScatterPoint[];

  if (pts.length === 0) {
    return (
      <div class="space-y-1 text-sm italic text-[var(--bb-data-fg-subtle)]">
        <p>No normalized cost data available for this ranking.</p>
        <p class="text-xs">{normalizedCostEmptyReason(summary.platforms)}</p>
      </div>
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

  const metricLabel =
    metric === "power_score" ? "Power score (higher is better)" : "Geomean latency (lower is better)";
  const modelDisclosure = costModelDisclosure(summary.platforms);

  return (
    <div ref={containerRef} class="w-full overflow-x-auto">
      <svg
        class="bb-chart-svg"
        width={w}
        height={totalH}
        role="img"
        aria-label={`Normalized cost vs ${metricLabel} scatter plot (${modelDisclosure})`}
      >
        {/* Grid - label orientation flips with higherIsBetter so the top
            of the chart always shows the better-performance value. */}
        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const y = PADDING_TOP + f * CHART_H;
          const val = higherIsBetter ? yMax - f * yRange : yMin + f * yRange;
          const label =
            metric === "power_score"
              ? formatPowerScore(val).valueText
              : formatLatencyMs(val, { subMillisecond: "compact" }).valueText;
          return (
            <g key={f}>
              <line
                x1={AXIS_W}
                y1={y}
                x2={w - PADDING_RIGHT}
                y2={y}
                stroke="var(--bb-chart-grid-muted)"
                strokeWidth={1}
              />
              <text
                x={AXIS_W - 4}
                y={y + 4}
                textAnchor="end"
                style={{ fontSize: "9px", fill: "var(--bb-chart-label-muted)" }}
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
          const regionLabel = [p.provider, p.region].filter(Boolean).join(" ");
          return (
            <g key={p.result_id}>
              <circle cx={cx} cy={cy} r={7} fill={p.color} fillOpacity={0.85}>
                <title>
                  {`${p.platform}: normalized ${formatUsd(p.cost).valueText} / ${
                    metric === "power_score" ? formatPowerScore(p.perf).valueText : formatLatencyMs(p.perf).valueText
                  } (${p.modelVersion ?? "model unknown"}${regionLabel ? `, ${regionLabel}` : ""})`}
                </title>
              </circle>
              <text
                x={cx}
                y={cy - 11}
                textAnchor="middle"
                style={{ fontSize: "10px", fill: "var(--bb-chart-label)" }}
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
          stroke="var(--bb-chart-grid)"
          strokeWidth={1}
        />
        <line
          x1={AXIS_W}
          y1={PADDING_TOP + CHART_H}
          x2={w - PADDING_RIGHT}
          y2={PADDING_TOP + CHART_H}
          stroke="var(--bb-chart-grid)"
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
                stroke="var(--bb-chart-label-muted)"
                strokeWidth={1}
              />
              <text
                x={x}
                y={PADDING_TOP + CHART_H + 16}
                textAnchor="middle"
                style={{ fontSize: "10px", fill: "var(--bb-chart-axis)" }}
              >
                {formatUsd(cost).valueText}
              </text>
            </g>
          );
        })}
        <text
          x={AXIS_W + plotW / 2}
          y={PADDING_TOP + CHART_H + AXIS_H - 2}
          textAnchor="middle"
          style={{ fontSize: "10px", fill: "var(--bb-chart-label-muted)" }}
        >
          Normalized cost (USD)
        </text>

        {/* Y-axis label */}
        <text
          x={0}
          y={0}
          style={{ fontSize: "9px", fill: "var(--bb-chart-label-muted)" }}
          transform={`rotate(-90) translate(${-(PADDING_TOP + CHART_H / 2)}, 11)`}
          textAnchor="middle"
        >
          {metricLabel}
        </text>
      </svg>
      <p class="mt-1 text-xs text-[var(--bb-data-fg-subtle)]">
        {modelDisclosure}. Only rows with <code class="rounded bg-[var(--bb-surface-data-muted)] px-1">cost_status=normalized</code> are
        plotted; local and unavailable cost rows are omitted.
      </p>
    </div>
  );
}

function normalizedCostEmptyReason(platforms: PlatformRow[]): string {
  if (platforms.length === 0) return "No platforms are present in the selected ranking.";
  if (platforms.every((platform) => platform.cost_status === undefined || platform.cost_status === null)) {
    return "These rows predate the normalized_cost contract; rebuild the DuckDB snapshot to emit cost_status and model metadata.";
  }
  if (platforms.every((platform) => platform.cost_status === "not_applicable_local")) {
    return "Only local or self-hosted rows are present; BenchBox marks those as not_applicable_local instead of comparable cloud cost.";
  }

  const missing = new Set<string>();
  for (const platform of platforms) {
    if (platform.cost_status !== "unavailable") continue;
    if (!platform.cloud_provider) missing.add("cloud provider");
    if (!platform.cloud_region && !platform.pricing_region) missing.add("region");
    if (!platform.instance_type && !platform.warehouse_size && !platform.cluster_size) {
      missing.add("instance, warehouse, or cluster shape");
    }
    if (!platform.cost_model_version) missing.add("cost model version");
  }
  if (missing.size > 0) {
    return `Missing normalized-cost metadata: ${[...missing].join(", ")}.`;
  }
  return "No row has cost_status=normalized with a finite normalized_cost_usd value.";
}
