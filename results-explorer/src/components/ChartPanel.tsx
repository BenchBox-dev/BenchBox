import { useEffect, useMemo, useState } from "preact/hooks";
import type { BenchmarkSummary } from "@/types";
import {
  applicableCharts,
  buildRenderableSummary,
  groupChartsByQuestion,
  type ChartContext,
  type ChartHistoricalEntry,
  type ChartRegistryEntry,
} from "@/lib/chartRegistry";
import { useElementSize } from "@/lib/useElementSize";
import { PowerBar } from "@/components/PowerBar";
import { DistributionBox } from "@/components/DistributionBox";
import { QueryHeatmap } from "@/components/QueryHeatmap";
import { QueryHistogram } from "@/components/QueryHistogram";
import { CostScatter } from "@/components/CostScatter";
import { TimeSeries } from "@/components/TimeSeries";
import { GroupedQueryChart } from "@/components/QueryTimingChart";
import { NormalizedSpeedupChart } from "@/components/NormalizedSpeedupChart";
import { DivergingBarChart } from "@/components/DivergingBarChart";
import { PercentileLadder } from "@/components/PercentileLadder";
import { StackedPhase } from "@/components/StackedPhase";
import { SparklineTable } from "@/components/SparklineTable";
import { CDFChart } from "@/components/CDFChart";
import { RankTable } from "@/components/RankTable";
import { fmtGeomean, fmtScore } from "@/utils";
import { paletteColor } from "@/lib/chartTheme";

interface ChartPanelProps {
  context: ChartContext;
}

interface CompareQueryRow {
  queryId: string;
  timings: ({ ms: number; status: "pass" } | null)[];
}

export function ChartPanel({ context }: ChartPanelProps) {
  const charts = useMemo(() => applicableCharts(context), [context]);
  const chartGroups = useMemo(() => groupChartsByQuestion(charts), [charts]);
  const summary = useMemo(() => buildRenderableSummary(context), [context]);
  const historical = useMemo(
    () =>
      context.kind === "summary"
        ? context.historical ?? []
        : context.kind === "detail"
          ? context.historical ?? []
          : [],
    [context],
  );
  const compareRows = useMemo(() => {
    if (context.kind !== "compare" || !summary) return [];
    return summary.query_ids.map((queryId) => ({
      queryId,
      timings: summary.platforms.map((platform) => {
        const ms = platform.timings[queryId] ?? null;
        return ms !== null ? { ms, status: "pass" as const } : null;
      }),
    }));
  }, [context, summary]);
  const compareGroups = useMemo(() => {
    if (context.kind !== "compare" || !summary) return [];
    return summary.query_ids.map((queryId) => ({
      queryId,
      values: summary.platforms.map((platform, index) => {
        const timing = platform.timings[queryId];
        return {
          label: platform.platform,
          value: timing ?? null,
          color: paletteColor(index),
        };
      }),
    }));
  }, [context, summary]);
  const preferredId = useMemo(() => preferredChartId(context, charts), [context, charts]);
  const [activeId, setActiveId] = useState<string>(preferredId);
  const [baselineIdx, setBaselineIdx] = useState(0);

  useEffect(() => {
    if (!charts.some((chart) => chart.id === activeId)) {
      setActiveId(preferredId);
    }
  }, [activeId, charts, preferredId]);

  useEffect(() => {
    setBaselineIdx(0);
  }, [context]);

  if (charts.length === 0) return null;

  const activeChart = charts.find((chart) => chart.id === activeId) ?? charts[0]!;
  const activeGroup =
    chartGroups.find((group) => group.charts.some((chart) => chart.id === activeChart.id)) ??
    chartGroups[0]!;
  const activeGroupCharts = activeGroup.charts;
  const showBaseline = context.kind === "compare" && (activeId === "normalized_speedup" || activeId === "diverging_bar");

  const selectGroup = (group: (typeof chartGroups)[number]) => {
    const nextChart =
      group.charts.find((chart) => chart.id === activeId) ??
      group.charts.find((chart) => chart.id === preferredId) ??
      group.charts[0];
    if (nextChart) setActiveId(nextChart.id);
  };

  return (
    <section class="card">
      <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
        <h2 class="text-base font-semibold text-gray-900">Charts</h2>
        <div class="flex w-full flex-col items-stretch gap-2 sm:w-auto sm:items-end">
          {chartGroups.length > 1 && (
            <div
              class="flex flex-wrap gap-1 rounded-md border border-gray-200 bg-gray-50 p-1"
              role="tablist"
              aria-label="Chart question groups"
            >
              {chartGroups.map((group) => {
                const selected = group.id === activeGroup.id;
                return (
                  <button
                    key={group.id}
                    role="tab"
                    type="button"
                    aria-selected={selected}
                    aria-controls="chart-panel-chart"
                    class={`rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                      selected
                        ? "bg-white text-gray-900 shadow-sm"
                        : "text-gray-600 hover:bg-white hover:text-gray-900"
                    }`}
                    onClick={() => selectGroup(group)}
                    title={group.description}
                  >
                    {group.label}
                  </button>
                );
              })}
            </div>
          )}
          {showBaseline && summary && summary.platforms.length > 1 && (
            <div class="flex items-center gap-2">
              <label class="text-xs text-gray-500" for="chart-panel-baseline">
                Baseline:
              </label>
              <select
                id="chart-panel-baseline"
                class="rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-700 focus:outline-none"
                value={String(baselineIdx)}
                onChange={(event) => setBaselineIdx(Number((event.target as HTMLSelectElement).value))}
              >
                {summary.platforms.map((platform, index) => (
                  <option key={platform.result_id} value={String(index)}>
                    {platform.platform}
                  </option>
                ))}
              </select>
            </div>
          )}
          {activeGroupCharts.length > 1 && (
            <div
              class="flex flex-wrap justify-end gap-1"
              role="group"
              aria-label={`${activeGroup.label} charts`}
            >
              {activeGroupCharts.map((chart) => (
                <button
                  key={chart.id}
                  type="button"
                  class={`rounded px-3 py-1 text-xs font-medium transition-colors ${
                    activeChart.id === chart.id
                      ? "bg-brand-600 text-white"
                      : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                  }`}
                  onClick={() => setActiveId(chart.id)}
                  aria-pressed={activeChart.id === chart.id}
                  title={chart.description}
                >
                  {chart.title}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div id="chart-panel-chart" role="tabpanel" aria-label={`${activeGroup.label} chart`}>
        {renderChart(activeChart, {
          context,
          summary,
          historical,
          compareRows,
          compareGroups,
          baselineIdx,
        })}
      </div>
    </section>
  );
}

function preferredChartId(
  context: ChartContext,
  charts: readonly ChartRegistryEntry[],
): string {
  const ids = new Set(charts.map((chart) => chart.id));

  if (context.kind === "compare") {
    if (context.results.length === 2 && ids.has("normalized_speedup")) {
      return "normalized_speedup";
    }
    if (ids.has("comparison_bar")) return "comparison_bar";
  }

  if (context.kind === "detail" && ids.has("query_histogram")) {
    return "query_histogram";
  }

  if (context.kind === "summary" && context.summary === null) {
    if (ids.has("time_series")) return "time_series";
    if (ids.has("summary_box")) return "summary_box";
  }

  if (context.kind === "summary" && ids.has("sparkline_table")) {
    return "sparkline_table";
  }

  return charts[0]?.id ?? "";
}

function renderChart(
  chart: ChartRegistryEntry,
  {
    context,
    summary,
    historical,
    compareRows,
    compareGroups,
    baselineIdx,
  }: {
    context: ChartContext;
    summary: BenchmarkSummary | null;
    historical: ChartHistoricalEntry[];
    compareRows: CompareQueryRow[];
    compareGroups: { queryId: string; values: { label: string; value: number | null; color: string }[] }[];
    baselineIdx: number;
  },
) {
  switch (chart.id) {
    case "performance_bar":
      return summary ? <PerformanceBar summary={summary} /> : null;
    case "power_bar":
      return summary ? <PowerBar summary={summary} /> : null;
    case "distribution_box":
      return summary ? <DistributionBox summary={summary} /> : null;
    case "query_heatmap":
      return summary ? <QueryHeatmap summary={summary} /> : null;
    case "query_histogram":
      return summary ? <QueryHistogram summary={summary} /> : null;
    case "cost_scatter":
      return summary ? <CostScatter summary={summary} /> : null;
    case "time_series":
      return historical && historical.length > 1 ? (
        <TimeSeries
          entries={historical}
          primaryMetric={
            (summary?.ranking?.primary_metric as "power_score" | "display_geomean_ms" | undefined)
          }
        />
      ) : (
        <p class="text-sm text-gray-400 italic">
          Not enough historical data for a trend chart.
        </p>
      );
    case "comparison_bar":
      return compareGroups.length > 0 ? (
        <div class="space-y-4">
          {summary && summary.platforms.length > 1 && (
            <div class="flex flex-wrap gap-4">
              {summary.platforms.map((platform, index) => (
                <div key={platform.result_id} class="flex items-center gap-1.5 text-sm text-gray-600">
                  <span
                    class="inline-block h-3 w-3 rounded-sm"
                    style={{ backgroundColor: paletteColor(index) }}
                  />
                  {platform.platform}
                </div>
              ))}
            </div>
          )}
          <GroupedQueryChart groups={compareGroups} />
        </div>
      ) : null;
    case "diverging_bar":
      return summary ? (
        <DivergingBarChart
          queries={compareRows}
          results={summary.platforms.map((platform) => ({ platform: platform.platform }))}
          baselineIdx={baselineIdx}
        />
      ) : null;
    case "summary_box":
      return <SummaryBoxPanel context={context} summary={summary} historical={historical} />;
    case "percentile_ladder":
      return summary ? (
        <PercentileLadder
          rows={summary.platforms.flatMap((platform, index) =>
            platform.percentile_stats !== null
              ? [
                  {
                    result_id: platform.result_id,
                    platform: platform.platform,
                    percentile_stats: platform.percentile_stats,
                    colorIdx: index,
                  },
                ]
              : [],
          )}
        />
      ) : null;
    case "normalized_speedup":
      return summary ? (
        <NormalizedSpeedupChart
          queries={compareRows}
          results={summary.platforms.map((platform) => ({ platform: platform.platform }))}
          baselineIdx={baselineIdx}
        />
      ) : null;
    case "stacked_phase":
      return summary ? <StackedPhase summary={summary} /> : null;
    case "sparkline_table":
      return summary ? <SparklineTable summary={summary} /> : null;
    case "cdf_chart":
      return summary ? <CDFChart summary={summary} /> : null;
    case "rank_table":
      return summary ? <RankTable summary={summary} /> : null;
    default:
      return null;
  }
}

function PerformanceBar({ summary }: { summary: BenchmarkSummary }) {
  const [containerRef, { width: containerWidth }] = useElementSize();
  const width = Math.max(containerWidth, 400);
  const rows = summary.platforms
    .filter((platform) => platform.display_geomean_ms !== null && platform.display_geomean_ms > 0)
    .sort((a, b) => (a.display_geomean_ms ?? Infinity) - (b.display_geomean_ms ?? Infinity))
    .map((platform, index) => ({ ...platform, color: paletteColor(index) }));

  if (rows.length === 0) {
    return (
      <p class="text-sm text-gray-400 italic">
        Geomean query timings are not available for these results.
      </p>
    );
  }

  const labelWidth = 160;
  const rowHeight = 36;
  const axisHeight = 32;
  const topPadding = 8;
  const valueWidth = 72;
  const plotWidth = width - labelWidth - valueWidth;
  const totalHeight = topPadding + rows.length * rowHeight + axisHeight;
  const maxValue = Math.max(...rows.map((row) => row.display_geomean_ms ?? 0));

  return (
    <div ref={containerRef} class="w-full overflow-x-auto">
      <svg
        width={width}
        height={totalHeight}
        role="img"
        aria-label="Geomean performance comparison"
      >
        {rows.map((row, index) => {
          const barWidth = ((row.display_geomean_ms ?? 0) / maxValue) * plotWidth;
          const y = topPadding + index * rowHeight;
          const midY = y + rowHeight * 0.5;
          const barHeight = rowHeight * 0.55;
          return (
            <g key={row.result_id}>
              <text
                x={labelWidth - 6}
                y={midY + 4}
                textAnchor="end"
                style={{ fontSize: "11px", fill: "#374151" }}
              >
                {row.platform.length > 22 ? `${row.platform.slice(0, 21)}…` : row.platform}
              </text>
              <rect
                x={labelWidth}
                y={midY - barHeight / 2}
                width={Math.max(2, barWidth)}
                height={barHeight}
                fill={row.color}
                opacity={0.85}
                rx={2}
              >
                <title>{`${row.platform}: ${fmtGeomean(row.display_geomean_ms)}`}</title>
              </rect>
              <text
                x={labelWidth + barWidth + 6}
                y={midY + 4}
                style={{ fontSize: "11px", fill: "#374151" }}
              >
                {fmtGeomean(row.display_geomean_ms)}
              </text>
              {index < rows.length - 1 && (
                <line
                  x1={0}
                  y1={y + rowHeight}
                  x2={width}
                  y2={y + rowHeight}
                  stroke="#e5e7eb"
                  strokeWidth={1}
                />
              )}
            </g>
          );
        })}

        <g transform={`translate(0, ${topPadding + rows.length * rowHeight})`}>
          <line
            x1={labelWidth}
            y1={0}
            x2={labelWidth + plotWidth}
            y2={0}
            stroke="#d1d5db"
            strokeWidth={1}
          />
          {[0, 0.25, 0.5, 0.75, 1].map((fraction) => {
            const x = labelWidth + fraction * plotWidth;
            const value = fraction * maxValue;
            return (
              <g key={fraction}>
                <line x1={x} y1={0} x2={x} y2={4} stroke="#9ca3af" strokeWidth={1} />
                <text
                  x={x}
                  y={16}
                  textAnchor="middle"
                  style={{ fontSize: "10px", fill: "#6b7280" }}
                >
                  {fmtGeomean(value)}
                </text>
              </g>
            );
          })}
          <text
            x={labelWidth + plotWidth / 2}
            y={axisHeight - 2}
            textAnchor="middle"
            style={{ fontSize: "10px", fill: "#9ca3af" }}
          >
            Geomean query time (median-of-passing) - lower is faster
          </text>
        </g>
      </svg>
    </div>
  );
}

function SummaryBoxPanel({
  context,
  summary,
  historical,
}: {
  context: ChartContext;
  summary: BenchmarkSummary | null;
  historical: ChartHistoricalEntry[];
}) {
  if (context.kind === "summary" && context.summary === null) {
    const benchmarks = new Set(historical.map((entry) => entry.benchmark));
    const latest = [...historical].sort((a, b) => b.run_date.localeCompare(a.run_date))[0] ?? null;
    return (
      <div class="grid gap-3 sm:grid-cols-3">
        <SummaryStat label="Runs" value={String(historical.length)} />
        <SummaryStat label="Benchmarks" value={String(benchmarks.size)} />
        <SummaryStat label="Latest run" value={latest ? latest.run_date.slice(0, 10) : "-"} />
      </div>
    );
  }

  if (!summary) return null;

  // summary.ranking.primary_metric is authoritative - it is either the
  // DuckDB-persisted value (summary loaded via getBenchmarkSummaryFromDuckDB)
  // or the page-resolved primaryMetric threaded through ChartContext. The
  // geomean fallback is reached only when ranking is null, which happens for
  // a single-result detail with no matching benchmark_rankings row yet.
  const primaryMetric = summary.ranking?.primary_metric ?? "display_geomean_ms";
  const higherIsBetter = summary.ranking?.primary_order === "desc";
  const best = [...summary.platforms]
    .filter((platform) => {
      const value = primaryMetric === "power_score" ? platform.power_score : platform.display_geomean_ms;
      return value !== null;
    })
    .sort((a, b) => {
      const av = primaryMetric === "power_score" ? (a.power_score ?? -Infinity) : (a.display_geomean_ms ?? Infinity);
      const bv = primaryMetric === "power_score" ? (b.power_score ?? -Infinity) : (b.display_geomean_ms ?? Infinity);
      return higherIsBetter ? bv - av : av - bv;
    })[0] ?? null;

  const sampleCount =
    context.kind === "detail"
      ? context.detail.display_timings.reduce((total, timing) => total + timing.sample_count, 0)
      : null;

  return (
    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <SummaryStat label="Platforms" value={String(summary.platforms.length)} />
      <SummaryStat label="Queries" value={String(summary.query_ids.length)} />
      <SummaryStat
        label={primaryMetric === "power_score" ? "Best power" : "Best geomean"}
        value={
          best
            ? `${best.platform} · ${
                primaryMetric === "power_score" ? fmtScore(best.power_score) : fmtGeomean(best.display_geomean_ms)
              }`
            : "-"
        }
      />
      <SummaryStat
        label={sampleCount !== null ? "Median samples" : "Phase"}
        value={sampleCount !== null ? String(sampleCount) : summary.phase}
      />
    </div>
  );
}

function SummaryStat({ label, value }: { label: string; value: string }) {
  return (
    <div class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
      <div class="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</div>
      <div class="mt-1 text-sm font-semibold text-gray-900">{value}</div>
    </div>
  );
}
