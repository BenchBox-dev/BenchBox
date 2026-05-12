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
import {
  formatRunIdentitiesForCohort,
  formatRunIdentityLabelsForCohort,
  preserveUniqueAfterTruncation,
} from "@/lib/runIdentity";
import {
  buildLatencyBarScale,
  latencyScaleFraction,
  latencyScaleTicks,
} from "@/lib/chartMath";
import {
  chartDatasetClassLabel,
  chartDatasetEmptyTitle,
  filterSummaryForChartDataset,
  isRankable,
  isTimingDisplayable,
  isValidTimingValue,
  platformTimingValue,
  summarizeChartDatasetExclusions,
  validPrimaryMetricValue,
  type ChartDatasetEligibilityClass,
} from "@/lib/displayEligibility";

interface ChartPanelProps {
  context: ChartContext;
  baselineIndex?: number;
  onBaselineIndexChange?: (baselineIndex: number) => void;
  // w18: thread the Compare-page guardrail (cohort mismatch → suppress
  // winner language) into chart-level summaries. Without this, ChartPanel
  // could still surface "Best power" / "Best geomean" claims even when the
  // page-level decision summary correctly avoided them.
  suppressWinnerClaims?: boolean;
  suppressionReason?: string;
  // w2 (chart-panel-scope-and-labeling): hosts that already render a
  // chart at page level (e.g. BenchmarkIndex matrix view rendering
  // QueryHeatmap above the panel) pass the duplicated chart ids here so
  // the panel does not expose the same view as a redundant subtab.
  excludeChartIds?: readonly string[];
}

interface CompareQueryRow {
  queryId: string;
  timings: ({ ms: number; status: "pass" } | null)[];
}

interface ValueLabelPlacement {
  x: number;
  textAnchor: "start" | "end";
  fill: string;
  placement: "outside" | "inside" | "gutter";
}

export function ChartPanel({
  context,
  baselineIndex,
  onBaselineIndexChange,
  suppressWinnerClaims = false,
  suppressionReason,
  excludeChartIds,
}: ChartPanelProps) {
  const charts = useMemo(() => {
    const applicable = applicableCharts(context);
    if (!excludeChartIds || excludeChartIds.length === 0) return applicable;
    const exclude = new Set(excludeChartIds);
    return applicable.filter((entry) => !exclude.has(entry.id));
  }, [context, excludeChartIds]);
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
  const summaryPlatformSelectLabels = useMemo(
    () =>
      summary
        ? formatRunIdentitiesForCohort(
            summary.platforms.map((platform) => ({ ...platform, scale_factor: summary.scale_factor })),
            "selectOption",
          )
        : [],
    [summary],
  );
  const preferredId = useMemo(() => preferredChartId(context, charts), [context, charts]);
  const [activeId, setActiveId] = useState<string>(preferredId);
  const [localBaselineIdx, setLocalBaselineIdx] = useState(0);
  const isBaselineControlled = baselineIndex !== undefined;
  const baselineIdx = normalizeBaselineIndex(
    summary?.platforms.length ?? 0,
    isBaselineControlled ? baselineIndex : localBaselineIdx,
  );
  const setBaselineIdx = onBaselineIndexChange ?? setLocalBaselineIdx;

  useEffect(() => {
    if (!charts.some((chart) => chart.id === activeId)) {
      setActiveId(preferredId);
    }
  }, [activeId, charts, preferredId]);

  useEffect(() => {
    if (!isBaselineControlled) setLocalBaselineIdx(0);
  }, [context, isBaselineControlled]);

  const activeChart = charts.find((chart) => chart.id === activeId) ?? charts[0] ?? null;
  const activeGroup =
    activeChart !== null
      ? (chartGroups.find((group) => group.charts.some((chart) => chart.id === activeChart.id)) ??
        chartGroups[0] ??
        null)
      : null;
  const activeGroupCharts = activeGroup?.charts ?? [];
  const activeEligibilityClass = activeChart?.eligibilityClass ?? "provenance_only";
  const showBaseline =
    !isBaselineControlled &&
    context.kind === "compare" &&
    (activeChart?.id === "normalized_speedup" || activeChart?.id === "diverging_bar");
  const chartSummary = useMemo(
    () => (summary ? filterSummaryForChartDataset(summary, activeEligibilityClass) : null),
    [activeEligibilityClass, summary],
  );
  const chartPlatformLabels = useMemo(
    () =>
      chartSummary
        ? formatRunIdentitiesForCohort(
            chartSummary.platforms.map((platform) => ({ ...platform, scale_factor: chartSummary.scale_factor })),
            "chart",
          )
        : [],
    [chartSummary],
  );
  const compareRows = useMemo(() => {
    if (context.kind !== "compare" || !chartSummary) return [];
    return chartSummary.query_ids.map((queryId) => ({
      queryId,
      timings: chartSummary.platforms.map((platform) => {
        const ms = platformTimingValue(platform, queryId);
        return ms !== null ? { ms, status: "pass" as const } : null;
      }),
    }));
  }, [chartSummary, context]);
  const compareGroups = useMemo(() => {
    if (context.kind !== "compare" || !chartSummary) return [];
    return chartSummary.query_ids.map((queryId) => ({
      queryId,
      values: chartSummary.platforms.map((platform, index) => {
        const timing = platformTimingValue(platform, queryId);
        return {
          label: chartPlatformLabels[index] ?? platform.platform,
          value: timing ?? null,
          color: paletteColor(index),
        };
      }),
    }));
  }, [chartPlatformLabels, chartSummary, context]);
  const chartExclusionSummary = useMemo(
    () => (summary ? summarizeChartDatasetExclusions(summary.platforms, activeEligibilityClass) : []),
    [activeEligibilityClass, summary],
  );
  const chartDatasetEmpty = shouldShowChartDatasetEmpty(activeEligibilityClass, summary, chartSummary);

  if (activeChart === null || activeGroup === null) return null;

  const selectGroup = (group: (typeof chartGroups)[number]) => {
    const nextChart =
      group.charts.find((chart) => chart.id === activeId) ??
      group.charts.find((chart) => chart.id === preferredId) ??
      group.charts[0];
    if (nextChart) setActiveId(nextChart.id);
  };

  return (
    <section class="card">
      <div class="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <h2 class="text-base font-semibold text-[var(--bb-data-fg-primary)]">Charts</h2>
        {chartGroups.length > 1 && (
          <div
            class="flex flex-wrap items-center gap-1 rounded-md panel-muted p-1"
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
                  aria-label={group.label}
                  class={`min-h-9 rounded px-2 py-1 text-xs font-medium transition-colors sm:px-3 ${
                    selected
                      ? "bg-[var(--bb-surface-data)] text-[var(--bb-data-fg-primary)] shadow-sm"
                      : "text-[var(--bb-data-fg-muted)] hover:bg-[var(--bb-surface-data)] hover:text-[var(--bb-data-fg-primary)]"
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
        {activeGroupCharts.length > 1 && (
          <div
            class="flex flex-wrap items-center gap-1 rounded-md panel-muted p-1"
            role="group"
            aria-label={`${activeGroup.label} charts`}
          >
            {activeGroupCharts.map((chart) => {
              const selected = activeChart.id === chart.id;
              return (
                <button
                  key={chart.id}
                  type="button"
                  class={`min-h-9 rounded px-2 py-1 text-xs font-medium transition-colors sm:px-3 ${
                    selected
                      ? "bg-[var(--bb-surface-data)] text-[var(--bb-data-fg-primary)] shadow-sm"
                      : "text-[var(--bb-data-fg-muted)] hover:bg-[var(--bb-surface-data)] hover:text-[var(--bb-data-fg-primary)]"
                  }`}
                  onClick={() => setActiveId(chart.id)}
                  aria-pressed={selected}
                  aria-label={chart.title}
                  title={chart.description}
                >
                  {chartButtonLabel(chart)}
                </button>
              );
            })}
          </div>
        )}
        {showBaseline && summary && summary.platforms.length > 1 && (
          <div class="ml-auto flex items-center gap-2">
            <label class="text-xs text-[var(--bb-data-fg-muted)]" for="chart-panel-baseline">
              Baseline:
            </label>
            <select
              id="chart-panel-baseline"
              class="min-w-0 max-w-full rounded border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-2 py-1 text-xs text-[var(--bb-data-fg-primary)]"
              value={String(baselineIdx)}
              onChange={(event) => setBaselineIdx(Number((event.target as HTMLSelectElement).value))}
            >
              {summary.platforms.map((platform, index) => (
                <option key={platform.result_id} value={String(index)}>
                  {summaryPlatformSelectLabels[index] ?? platform.platform}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      <div id="chart-panel-chart" role="tabpanel" aria-label={`${activeGroup.label} chart`} data-chart-container>
        {chartDatasetEmpty ? (
          <ChartDatasetEmptyState chart={activeChart} summary={summary!} />
        ) : (
          <>
            {renderChart(activeChart, {
              context,
              summary: chartSummary,
              historical,
              compareRows,
              compareGroups,
              baselineIdx,
              platformLabels: chartPlatformLabels,
              suppressWinnerClaims,
              suppressionReason,
            })}
            {summary && chartSummary && chartSummary.platforms.length > 0 && chartExclusionSummary.length > 0 && (
              <ChartDatasetExclusionSummary
                eligibilityClass={activeChart.eligibilityClass}
                originalCount={summary.platforms.length}
                renderedCount={chartSummary.platforms.length}
                reasons={chartExclusionSummary}
              />
            )}
          </>
        )}
      </div>
    </section>
  );
}

function chartButtonLabel(chart: ChartRegistryEntry): string {
  return chart.shortTitle;
}

function normalizeBaselineIndex(platformCount: number, baselineIndex: number) {
  return baselineIndex >= 0 && baselineIndex < platformCount ? baselineIndex : 0;
}

function shouldShowChartDatasetEmpty(
  eligibilityClass: ChartDatasetEligibilityClass,
  summary: BenchmarkSummary | null,
  chartSummary: BenchmarkSummary | null,
): boolean {
  if (eligibilityClass === "provenance_only" || eligibilityClass === "trend_safe") return false;
  return Boolean(summary && chartSummary && summary.platforms.length > 0 && chartSummary.platforms.length === 0);
}

function ChartDatasetEmptyState({
  chart,
  summary,
}: {
  chart: ChartRegistryEntry;
  summary: BenchmarkSummary;
}) {
  const reasons = summarizeChartDatasetExclusions(summary.platforms, chart.eligibilityClass);
  return (
    <div
      role="status"
      aria-label={`${chart.title} unavailable`}
      class="rounded-md border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-4 py-3 text-sm"
    >
      <p class="font-semibold text-[var(--bb-data-fg-primary)]">{chartDatasetEmptyTitle(chart.eligibilityClass)}</p>
      <p class="mt-1 text-[var(--bb-data-fg-muted)]">
        This chart requires {chartDatasetClassLabel(chart.eligibilityClass)}. Submitted rows remain visible in the
        table or receipt, but they are not plotted as normal chart data.
      </p>
      {reasons.length > 0 && (
        <ul class="mt-2 space-y-1 text-xs text-[var(--bb-data-fg-muted)]">
          {reasons.slice(0, 3).map(({ reason, count }) => (
            <li key={reason}>
              {count} {count === 1 ? "row" : "rows"}: {reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ChartDatasetExclusionSummary({
  eligibilityClass,
  originalCount,
  renderedCount,
  reasons,
}: {
  eligibilityClass: ChartDatasetEligibilityClass;
  originalCount: number;
  renderedCount: number;
  reasons: { reason: string; count: number }[];
}) {
  if (renderedCount >= originalCount) return null;
  const excludedCount = originalCount - renderedCount;
  const topReason = reasons[0]?.reason ?? chartDatasetClassLabel(eligibilityClass);
  return (
    <p class="mt-2 text-[11px] text-[var(--bb-data-fg-subtle)]">
      {excludedCount} {excludedCount === 1 ? "row" : "rows"} excluded from this chart's{" "}
      {chartDatasetClassLabel(eligibilityClass)} dataset: {topReason}
    </p>
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
    platformLabels,
    suppressWinnerClaims = false,
    suppressionReason,
  }: {
    context: ChartContext;
    summary: BenchmarkSummary | null;
    historical: ChartHistoricalEntry[];
    compareRows: CompareQueryRow[];
    compareGroups: { queryId: string; values: { label: string; value: number | null; color: string }[] }[];
    baselineIdx: number;
    platformLabels: string[];
    suppressWinnerClaims?: boolean;
    suppressionReason?: string;
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
        <p class="text-sm italic text-[var(--bb-data-fg-subtle)]">
          Not enough historical data for a trend chart.
        </p>
      );
    case "comparison_bar":
      return compareGroups.length > 0 ? (
        <div class="space-y-4">
          {summary && summary.platforms.length > 1 && (() => {
            const legendLabels = formatRunIdentitiesForCohort(
              summary.platforms.map((platform) => ({ ...platform, scale_factor: summary.scale_factor })),
              "chart",
            );
            return (
              <div class="flex flex-wrap gap-4">
                {summary.platforms.map((platform, index) => (
                  <div key={platform.result_id} class="flex items-center gap-1.5 text-sm text-[var(--bb-data-fg-muted)]">
                    <span
                      class="inline-block h-3 w-3 rounded-sm"
                      style={{ backgroundColor: paletteColor(index) }}
                    />
                    {legendLabels[index] ?? platform.platform}
                  </div>
                ))}
              </div>
            );
          })()}
          <GroupedQueryChart groups={compareGroups} />
        </div>
      ) : null;
    case "diverging_bar":
      return summary ? (
        <DivergingBarChart
          queries={compareRows}
          results={summary.platforms.map((platform, index) => ({
            platform: platformLabels[index] ?? platform.platform,
          }))}
          baselineIdx={baselineIdx}
        />
      ) : null;
    case "summary_box":
      return (
        <SummaryBoxPanel
          context={context}
          summary={summary}
          historical={historical}
          suppressWinnerClaims={suppressWinnerClaims}
          suppressionReason={suppressionReason}
        />
      );
    case "percentile_ladder":
      if (!summary) return null;
      {
        const cohortLabels = formatRunIdentitiesForCohort(
          summary.platforms.map((platform) => ({ ...platform, scale_factor: summary.scale_factor })),
          "chart",
        );
        return (
          <PercentileLadder
            rows={summary.platforms.flatMap((platform, index) =>
              platform.percentile_stats !== null
                ? [
                    {
                      result_id: platform.result_id,
                      platform: platform.platform,
                      displayLabel: cohortLabels[index] ?? platform.platform,
                      percentile_stats: platform.percentile_stats,
                      colorIdx: index,
                    },
                  ]
                : [],
            )}
          />
        );
      }
    case "normalized_speedup":
      return summary ? (
        <NormalizedSpeedupChart
          queries={compareRows}
          results={summary.platforms.map((platform, index) => ({
            platform: platformLabels[index] ?? platform.platform,
          }))}
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
  const cohortLabels = formatRunIdentityLabelsForCohort(
    summary.platforms.map((platform) => ({ ...platform, scale_factor: summary.scale_factor })),
  );
  const displayLabels = preserveUniqueAfterTruncation(
    cohortLabels.map((label) => label.disambiguated),
    22,
  );
  const labelByResultId = new Map(
    summary.platforms.map((platform, index) => [platform.result_id, displayLabels[index] ?? platform.platform]),
  );
  const fullLabelByResultId = new Map(
    summary.platforms.map((platform, index) => [platform.result_id, cohortLabels[index]?.full ?? platform.platform]),
  );
  const rows = summary.platforms
    .filter((platform) => isTimingDisplayable(platform) && isValidTimingValue(platform.display_geomean_ms))
    .sort((a, b) => (a.display_geomean_ms ?? Infinity) - (b.display_geomean_ms ?? Infinity))
    .map((platform, index) => ({
      ...platform,
      color: paletteColor(index),
      displayLabel: labelByResultId.get(platform.result_id) ?? platform.platform,
      fullLabel: fullLabelByResultId.get(platform.result_id) ?? platform.platform,
    }));

  if (rows.length === 0) {
    return (
      <p class="text-sm italic text-[var(--bb-data-fg-subtle)]">
        Geomean query timings are not available for these results.
      </p>
    );
  }

  const labelWidth = 160;
  const rowHeight = 36;
  const axisHeight = 32;
  const topPadding = 8;
  const valueLabelGutter = 96;
  const plotWidth = width - labelWidth - valueLabelGutter;
  const totalHeight = topPadding + rows.length * rowHeight + axisHeight;
  const scale = buildLatencyBarScale(rows.map((row) => row.display_geomean_ms));
  if (scale === null) return null;

  const ticks = latencyScaleTicks(scale);
  const scaleLabel =
    scale.mode === "log"
      ? "Geomean query time (log scale) - lower is better"
      : "Geomean query time (median-of-passing) - lower is better";

  return (
    <div ref={containerRef} class="w-full overflow-x-auto">
      <svg
        class="bb-chart-svg"
        width={width}
        height={totalHeight}
        role="img"
        aria-label={
          scale.mode === "log"
            ? "Geomean performance comparison (log scale)"
            : "Geomean performance comparison"
        }
      >
        {rows.map((row, index) => {
          const fraction = latencyScaleFraction(row.display_geomean_ms, scale) ?? 0;
          const barWidth = fraction * plotWidth;
          const renderedBarWidth = Math.max(2, barWidth);
          const valueLabel = fmtGeomean(row.display_geomean_ms);
          const valueLabelPlacement = placePerformanceValueLabel({
            barWidth: renderedBarWidth,
            plotWidth,
            labelWidth,
            valueText: valueLabel,
          });
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
                <title>{row.fullLabel}</title>
                {row.displayLabel}
              </text>
              <rect
                x={labelWidth}
                y={midY - barHeight / 2}
                width={renderedBarWidth}
                height={barHeight}
                fill={row.color}
                opacity={0.85}
                rx={2}
              >
                <title>{`${row.fullLabel}: ${fmtGeomean(row.display_geomean_ms)}`}</title>
              </rect>
              {valueLabelPlacement.placement === "gutter" && (
                <line
                  x1={labelWidth + renderedBarWidth + 4}
                  y1={midY}
                  x2={valueLabelPlacement.x - 5}
                  y2={midY}
                  stroke="#d1d5db"
                  strokeWidth={1}
                  strokeDasharray="2 2"
                />
              )}
              <text
                x={valueLabelPlacement.x}
                y={midY + 4}
                textAnchor={valueLabelPlacement.textAnchor}
                data-value-placement={valueLabelPlacement.placement}
                style={{ fontSize: "11px", fill: valueLabelPlacement.fill }}
              >
                {valueLabel}
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
          {ticks.map((value) => {
            const fraction = latencyScaleFraction(value, scale) ?? 0;
            const x = labelWidth + fraction * plotWidth;
            return (
              <g key={value}>
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
            {scaleLabel}
          </text>
        </g>
      </svg>
    </div>
  );
}

function placePerformanceValueLabel({
  barWidth,
  plotWidth,
  labelWidth,
  valueText,
}: {
  barWidth: number;
  plotWidth: number;
  labelWidth: number;
  valueText: string;
}): ValueLabelPlacement {
  const labelGap = 6;
  const labelPx = valueText.length * 6.5;
  const plotRight = labelWidth + plotWidth;
  const outsideX = labelWidth + barWidth + labelGap;
  const outsideFits = outsideX + labelPx <= plotRight - labelGap;
  if (outsideFits) {
    return {
      x: outsideX,
      textAnchor: "start",
      fill: "#374151",
      placement: "outside",
    };
  }

  const insideFits = barWidth >= labelPx + labelGap * 2;
  if (insideFits) {
    return {
      x: labelWidth + barWidth - labelGap,
      textAnchor: "end",
      fill: "#ffffff",
      placement: "inside",
    };
  }

  return {
    x: plotRight + labelGap,
    textAnchor: "start",
    fill: "#374151",
    placement: "gutter",
  };
}

function SummaryBoxPanel({
  context,
  summary,
  historical,
  suppressWinnerClaims = false,
  suppressionReason,
}: {
  context: ChartContext;
  summary: BenchmarkSummary | null;
  historical: ChartHistoricalEntry[];
  suppressWinnerClaims?: boolean;
  suppressionReason?: string;
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
  const primaryMetric = summary.ranking?.primary_metric === "power_score" ? "power_score" : "display_geomean_ms";
  const higherIsBetter = summary.ranking?.primary_order === "desc";
  const best = [...summary.platforms]
    .filter((platform) => {
      return isRankable(platform) && validPrimaryMetricValue(platform, primaryMetric) !== null;
    })
    .sort((a, b) => {
      const av = validPrimaryMetricValue(a, primaryMetric) ?? (higherIsBetter ? -Infinity : Infinity);
      const bv = validPrimaryMetricValue(b, primaryMetric) ?? (higherIsBetter ? -Infinity : Infinity);
      return higherIsBetter ? bv - av : av - bv;
    })[0] ?? null;
  const summaryLabels = formatRunIdentityLabelsForCohort(
    summary.platforms.map((platform) => ({ ...platform, scale_factor: summary.scale_factor })),
  );
  const summaryLabelByResultId = new Map(
    summary.platforms.map((platform, index) => [platform.result_id, summaryLabels[index]?.compact ?? platform.platform]),
  );

  const sampleCount =
    context.kind === "detail"
      ? context.detail.display_timings.reduce((total, timing) => total + timing.sample_count, 0)
      : null;

  return (
    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <SummaryStat label="Platforms" value={String(summary.platforms.length)} />
      <SummaryStat label="Queries" value={String(summary.query_ids.length)} />
      <SummaryStat
        label={
          suppressWinnerClaims
            ? primaryMetric === "power_score"
              ? "Highest power score in cohort"
              : "Lowest geomean in cohort"
            : primaryMetric === "power_score"
              ? "Best power"
              : "Best geomean"
        }
        value={
          best
            ? `${summaryLabelByResultId.get(best.result_id) ?? best.platform} · ${
                primaryMetric === "power_score" ? fmtScore(best.power_score) : fmtGeomean(best.display_geomean_ms)
              }${suppressWinnerClaims ? " (cohort mismatch — not comparable)" : ""}`
            : "-"
        }
        title={suppressWinnerClaims ? suppressionReason : undefined}
      />
      <SummaryStat
        label={sampleCount !== null ? "Median samples" : "Phase"}
        value={sampleCount !== null ? String(sampleCount) : summary.phase}
      />
    </div>
  );
}

function SummaryStat({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div class="rounded-lg panel-muted px-4 py-3" title={title}>
      <div class="text-xs font-medium uppercase tracking-wide text-[var(--bb-data-fg-subtle)]">{label}</div>
      <div class="mt-1 text-sm font-semibold text-[var(--bb-data-fg-primary)]">{value}</div>
    </div>
  );
}
