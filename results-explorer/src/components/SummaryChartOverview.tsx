import { useMemo, useState } from "preact/hooks";
import type { ComponentChildren } from "preact";
import type { BenchmarkSummary } from "@/types";
import {
  applicableCharts,
  buildRenderableSummary,
  CHART_REGISTRY_BY_ID,
  type ChartContext,
  type ChartHistoricalEntry,
  type ChartRegistryEntry,
} from "@/lib/chartRegistry";
import { paletteColor, PHASE_COLORS, timeSeriesColor } from "@/lib/chartTheme";
import {
  buildLatencyBarScale,
  buildLogLatencyScale,
  colorForCell,
  computeECDFPoints,
  computeRankTable,
  latencyScaleFraction,
  logLatencyFraction,
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
} from "@/lib/displayEligibility";
import { formatRunIdentityLabelsForCohort, preserveUniqueAfterTruncation } from "@/lib/runIdentity";
import { fmtGeomean, fmtScore } from "@/utils";
import { DistributionBox } from "@/components/DistributionBox";
import { QueryHeatmap } from "@/components/QueryHeatmap";
import { QueryHistogram } from "@/components/QueryHistogram";
import { CostScatter } from "@/components/CostScatter";
import { TimeSeries } from "@/components/TimeSeries";
import { PercentileLadder } from "@/components/PercentileLadder";
import { StackedPhase } from "@/components/StackedPhase";
import { CDFChart } from "@/components/CDFChart";
import { RankTable } from "@/components/RankTable";

interface Props {
  context: Extract<ChartContext, { kind: "summary" }>;
  excludeChartIds?: readonly string[];
}

// These are the secondary views that carry useful analytical information in
// the long summary layout. They are deliberately ordered like the current
// chart navigation and remain visible as unavailable cards when a cohort does
// not contain the required data (for example, normalized cost or history).
const LONG_LAYOUT_CHART_IDS = [
  "query_heatmap",
  "percentile_ladder",
  "cdf_chart",
  "query_histogram",
  "stacked_phase",
  "time_series",
  "rank_table",
  "cost_scatter",
] as const;

const CHART_QUESTIONS: Record<string, string> = {
  query_heatmap: "Which queries drive the difference?",
  percentile_ladder: "Where does the tail sit, not just the middle?",
  cdf_chart: "What share of queries finish under a given time?",
  query_histogram: "Which individual queries are slow?",
  stacked_phase: "Where does the wall-clock time go?",
  time_series: "Is this platform getting faster over time?",
  rank_table: "Who wins query by query, not on average?",
  cost_scatter: "What does a unit of speed cost?",
};

const CHART_DISPLAY_TITLES: Record<string, string> = {
  rank_table: "Query ranks",
};

export function additionalAnalysesLabel(count: number): string {
  return `${count} additional ${count === 1 ? "analysis" : "analyses"}`;
}

export function SummaryChartOverview({ context, excludeChartIds = [] }: Props) {
  const summary = buildRenderableSummary(context);
  const [openChartIds, setOpenChartIds] = useState<Set<string>>(() => new Set());
  const charts = useMemo(() => {
    const applicableById = new Map(applicableCharts(context).map((chart) => [chart.id, chart]));
    const excluded = new Set(excludeChartIds);
    return LONG_LAYOUT_CHART_IDS.map((id) => {
      const chart = applicableById.get(id) ?? CHART_REGISTRY_BY_ID[id];
      return chart && !excluded.has(id) ? chart : null;
    }).filter((chart): chart is ChartRegistryEntry => chart !== null);
  }, [context, excludeChartIds]);

  if (summary === null) return null;

  const displayRows = summary.platforms.filter(
    (platform) => isTimingDisplayable(platform) && validPrimaryMetricValue(platform, "display_geomean_ms") !== null,
  );
  const powerRows = summary.platforms.filter(
    (platform) => isRankable(platform) && validPrimaryMetricValue(platform, "power_score") !== null,
  );
  const displayScale = buildLatencyBarScale(displayRows.map((platform) => platform.display_geomean_ms));
  const maxPower = Math.max(...powerRows.map((platform) => platform.power_score ?? 0), 1);
  const labels = formatRunIdentityLabelsForCohort(
    summary.platforms.map((platform) => ({ ...platform, scale_factor: summary.scale_factor })),
  );
  const displayLabels = preserveUniqueAfterTruncation(
    labels.map((label) => label.disambiguated),
    30,
  );
  const rows = [...summary.platforms].sort((a, b) => {
    const av = validPrimaryMetricValue(a, "display_geomean_ms");
    const bv = validPrimaryMetricValue(b, "display_geomean_ms");
    if (av !== null && bv !== null) return av - bv;
    if (av !== null) return -1;
    if (bv !== null) return 1;
    return a.platform.localeCompare(b.platform);
  });
  const rowIndexByResultId = new Map(summary.platforms.map((platform, index) => [platform.result_id, index]));
  const displayExclusions = summarizeChartDatasetExclusions(summary.platforms, "display_safe");
  const powerExclusions = summarizeChartDatasetExclusions(summary.platforms, "rank_safe");

  return (
    <div class="scroll-mt-24 space-y-6" data-testid="summary-chart-overview" id="cohort-charts">
      <section class="card" aria-labelledby="summary-metric-overview-title">
        <div class="mb-4 flex flex-wrap items-start justify-between gap-3 border-b border-[var(--bb-data-border)] pb-4">
          <div>
            <h2 id="summary-metric-overview-title" class="text-lg font-semibold text-[var(--bb-data-fg-primary)]">
              Which engines lead on speed and throughput?
            </h2>
            <p class="mt-1 text-sm text-[var(--bb-data-fg-muted)]">
              Display geomean and Power@Size in one compact comparison. Lower latency and higher throughput are better.
            </p>
          </div>
          <p class="font-mono text-xs text-[var(--bb-data-fg-subtle)]">display_geomean_ms · Power@Size</p>
        </div>

        <div class="overflow-x-auto">
          <table
            class="summary-metric-table min-w-[38rem] w-full border-collapse"
            aria-label="Speed and throughput by engine"
          >
            <caption class="sr-only">
              Display geomean latency and Power@Size for every submitted engine in this cohort
            </caption>
            <thead>
              <tr class="border-b border-[var(--bb-data-border-strong)]">
                <th
                  scope="col"
                  class="w-[14rem] px-2 py-2 text-left text-xs font-medium text-[var(--bb-data-fg-muted)]"
                >
                  Platform
                </th>
                <th scope="col" class="px-2 py-2 text-left text-xs font-medium text-[var(--bb-data-fg-muted)]">
                  <span class="block">Display geomean</span>
                  <span class="font-normal text-[var(--bb-data-fg-subtle)]">lower is better</span>
                </th>
                <th scope="col" class="px-2 py-2 text-left text-xs font-medium text-[var(--bb-data-fg-muted)]">
                  <span class="block">Power@Size</span>
                  <span class="font-normal text-[var(--bb-data-fg-subtle)]">higher is better</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((platform, rowIndex) => {
                const sourceIndex = rowIndexByResultId.get(platform.result_id) ?? rowIndex;
                const color = paletteColor(sourceIndex);
                const displayValue = validPrimaryMetricValue(platform, "display_geomean_ms");
                const powerValue = isRankable(platform)
                  ? validPrimaryMetricValue(platform, "power_score")
                  : null;
                const displayFraction = displayValue !== null && displayScale
                  ? latencyScaleFraction(displayValue, displayScale)
                  : null;
                const powerFraction = powerValue !== null ? Math.min(1, powerValue / maxPower) : null;
                return (
                  <tr key={platform.result_id} class="border-b border-[var(--bb-data-border)] align-middle">
                    <th scope="row" class="px-2 py-1.5 text-left text-sm font-medium text-[var(--bb-data-fg-primary)]">
                      <span
                        class="flex min-w-0 items-center gap-2"
                        title={labels[sourceIndex]?.full ?? platform.platform}
                      >
                        <span
                          class="h-2.5 w-2.5 shrink-0 rounded-full"
                          style={{ backgroundColor: color }}
                          aria-hidden="true"
                        />
                        <span class="min-w-0 break-words">{displayLabels[sourceIndex] ?? platform.platform}</span>
                      </span>
                    </th>
                    <InlineMetricCell
                      value={displayValue}
                      formatted={displayValue === null ? "—" : fmtGeomean(displayValue)}
                      fraction={displayFraction}
                      color={color}
                      title={
                        displayValue === null
                          ? "Display timing unavailable"
                          : `${fmtGeomean(displayValue)} display geomean`
                      }
                    />
                    <InlineMetricCell
                      value={powerValue}
                      formatted={powerValue === null ? "—" : fmtScore(powerValue)}
                      fraction={powerFraction}
                      color={color}
                      title={
                        powerValue === null
                          ? "Power@Size unavailable or not rank-safe"
                          : `${fmtScore(powerValue)} Power@Size`
                      }
                    />
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div
          class="mt-4 grid gap-3 border-t border-[var(--bb-data-border)] pt-4 text-sm
            text-[var(--bb-data-fg-muted)] sm:grid-cols-2"
        >
          <p>
            <strong class="text-[var(--bb-data-fg-primary)]">Population:</strong> {summary.platforms.length} submitted
            runs · {displayRows.length} display-safe rows · {summary.query_ids.length} queries
          </p>
          <p>
            <strong class="text-[var(--bb-data-fg-primary)]">Ranking:</strong> {powerRows.length} rank-safe rows ·
            values stay tied to the persisted ranking contract
          </p>
          {(displayExclusions.length > 0 || powerExclusions.length > 0) && (
            <p class="sm:col-span-2 text-xs text-[var(--bb-data-fg-subtle)]">
              {formatExclusionCount(displayExclusions, "display chart")}
              {displayExclusions.length > 0 && powerExclusions.length > 0 ? " · " : ""}
              {formatExclusionCount(powerExclusions, "ranking chart")}
            </p>
          )}
        </div>
      </section>

      <section class="card" aria-labelledby="summary-distribution-title">
        <div class="mb-4 border-b border-[var(--bb-data-border)] pb-4">
          <h2 id="summary-distribution-title" class="text-lg font-semibold text-[var(--bb-data-fg-primary)]">
            How wide is the query-latency spread?
          </h2>
          <p class="mt-1 text-sm text-[var(--bb-data-fg-muted)]">
            Full distribution view for display-safe rows. Whiskers show the observed per-query range.
          </p>
        </div>
        <div data-chart-container>
          <DistributionBox summary={summary} />
        </div>
        <div class="mt-3 border-t border-[var(--bb-data-border)] pt-3 text-sm text-[var(--bb-data-fg-muted)]">
          <p>
            The spread is across different queries, not repeated runs of the same query.{" "}
            <a class="font-medium text-[var(--bb-accent)]" href="#evidence-matrix">
              See the per-query matrix
            </a>
            .
          </p>
        </div>
      </section>

      {charts.length > 0 && (
        <section class="card" aria-labelledby="summary-more-views-title" data-testid="summary-more-views">
          <div class="mb-4 flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-[var(--bb-data-border)] pb-4">
            <h2 id="summary-more-views-title" class="text-lg font-semibold text-[var(--bb-data-fg-primary)]">
              More views
            </h2>
            <p class="ml-auto text-sm font-medium text-[var(--bb-accent)]">
              {additionalAnalysesLabel(charts.length)}
            </p>
            <p class="text-sm text-[var(--bb-data-fg-muted)]">
              {excludeChartIds.includes("query_heatmap")
                ? "The evidence matrix above is the query heatmap. "
                : ""}
              Each thumbnail is drawn from this cohort when the cohort has data for it. Open a card to
              inspect the full chart and its data scope.
            </p>
          </div>
          <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {charts.map((chart) => {
              const isOpen = openChartIds.has(chart.id);
              const chartSummary = filterSummaryForChartDataset(summary, chart.eligibilityClass);
              const isEmpty = shouldShowEmptyState(summary, chartSummary, chart);
              const exclusions = summarizeChartDatasetExclusions(summary.platforms, chart.eligibilityClass);
              return (
                <details
                  key={chart.id}
                  class={`summary-chart-details rounded-lg border border-[var(--bb-data-border)]
                    bg-[var(--bb-surface-data)] ${isOpen ? "sm:col-span-2 xl:col-span-4" : ""}`}
                  open={isOpen}
                  onToggle={(event) => {
                    const open = (event.currentTarget as HTMLDetailsElement).open;
                    setOpenChartIds((current) => {
                      const next = new Set(current);
                      if (open) next.add(chart.id);
                      else next.delete(chart.id);
                      return next;
                    });
                  }}
                  data-testid={`summary-chart-preview-${chart.id}`}
                >
                  <summary
                    class="cursor-pointer list-none p-4 outline-none focus-visible:ring-2
                      focus-visible:ring-[var(--bb-focus-ring)] focus-visible:ring-inset"
                  >
                    {/* The preview exists to say what the card contains before
                        it is opened. Once the full chart is rendered below,
                        keeping the thumbnail draws the same chart twice, and
                        only one of the two carries readable detail. */}
                    <div class={`flex flex-col ${isOpen ? "" : "min-h-[13rem]"}`}>
                      <div>
                        <h3 class="text-sm font-semibold text-[var(--bb-data-fg-primary)]">
                          {CHART_DISPLAY_TITLES[chart.id] ?? chart.shortTitle}
                        </h3>
                        <p class="mt-1 text-xs leading-5 text-[var(--bb-data-fg-muted)]">
                          {CHART_QUESTIONS[chart.id] ?? chart.description}
                        </p>
                      </div>
                      {!isOpen && (
                        <ChartThumbnail
                          chartId={chart.id}
                          summary={chartSummary}
                          historical={context.historical ?? []}
                        />
                      )}
                      <span class="mt-auto pt-3 text-xs font-medium text-[var(--bb-accent)]">
                        {isOpen ? "Close full chart" : "Open full chart ↗"}
                      </span>
                    </div>
                  </summary>
                  <div
                    class="border-t border-[var(--bb-data-border)] p-4"
                    data-testid={`summary-chart-full-${chart.id}`}
                    data-chart-container
                  >
                    {isOpen && (
                      <>
                        {isEmpty ? (
                          <ChartDatasetEmptyState chart={chart} summary={summary} />
                        ) : (
                          renderExpandedChart(chart, chartSummary, context.historical ?? []) ?? (
                            <p class="text-sm italic text-[var(--bb-data-fg-subtle)]">
                              No chart data is available for this view.
                            </p>
                          )
                        )}
                        {chartSummary.platforms.length > 0 && exclusions.length > 0 && (
                          <ChartDatasetExclusionSummary
                            eligibilityClass={chart.eligibilityClass}
                            originalCount={summary.platforms.length}
                            renderedCount={chartSummary.platforms.length}
                            reasons={exclusions}
                          />
                        )}
                      </>
                    )}
                  </div>
                </details>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}

function InlineMetricCell({
  value,
  formatted,
  fraction,
  color,
  title,
}: {
  value: number | null;
  formatted: string;
  fraction: number | null;
  color: string;
  title: string;
}) {
  return (
    <td class="summary-metric-cell px-2 py-1.5" title={title}>
      <div class="flex items-center gap-2">
        <span class="w-[4.5rem] shrink-0 text-right font-mono text-sm text-[var(--bb-data-fg-primary)]">
          {formatted}
        </span>
        <span class="sr-only">{value === null ? "unavailable" : "measured"}</span>
        <div class="summary-metric-track min-w-0 flex-1" aria-hidden="true">
          <span
            class="summary-metric-fill"
            style={{ width: `${fraction === null ? 0 : Math.max(3, fraction * 100)}%`, backgroundColor: color }}
          />
        </div>
      </div>
    </td>
  );
}

function shouldShowEmptyState(
  summary: BenchmarkSummary,
  chartSummary: BenchmarkSummary,
  chart: ChartRegistryEntry,
): boolean {
  if (chart.eligibilityClass === "provenance_only" || chart.eligibilityClass === "trend_safe") return false;
  return summary.platforms.length > 0 && chartSummary.platforms.length === 0;
}

function formatExclusionCount(reasons: { reason: string; count: number }[], label: string): string {
  const count = reasons.reduce((total, reason) => total + reason.count, 0);
  if (count === 0) return "";
  const reason = reasons[0]?.reason ?? "eligibility policy";
  return `${count} ${count === 1 ? "row" : "rows"} excluded from the ${label} dataset (${reason})`;
}

function ChartDatasetEmptyState({ chart, summary }: { chart: ChartRegistryEntry; summary: BenchmarkSummary }) {
  const reasons = summarizeChartDatasetExclusions(summary.platforms, chart.eligibilityClass);
  return (
    <div
      role="status"
      aria-label={`${chart.title} unavailable`}
      class="rounded-md border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-3 py-3 text-sm"
    >
      <p class="font-semibold text-[var(--bb-data-fg-primary)]">{chartDatasetEmptyTitle(chart.eligibilityClass)}</p>
      <p class="mt-1 text-[var(--bb-data-fg-muted)]">
        This view requires {chartDatasetClassLabel(chart.eligibilityClass)}. Submitted rows remain visible in the
        table or receipt, but they are not plotted as normal chart data.
      </p>
      {reasons.length > 0 && (
        <ul class="mt-2 space-y-1 text-xs text-[var(--bb-data-fg-subtle)]">
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
  eligibilityClass: ChartRegistryEntry["eligibilityClass"];
  originalCount: number;
  renderedCount: number;
  reasons: { reason: string; count: number }[];
}) {
  if (renderedCount >= originalCount) return null;
  const excludedCount = originalCount - renderedCount;
  return (
    <p class="mt-3 text-[11px] text-[var(--bb-data-fg-subtle)]">
      {excludedCount} {excludedCount === 1 ? "row" : "rows"} excluded from this view&apos;s{" "}
      {chartDatasetClassLabel(eligibilityClass)} dataset: {reasons[0]?.reason ?? "eligibility policy"}
    </p>
  );
}

function renderExpandedChart(
  chart: ChartRegistryEntry,
  summary: BenchmarkSummary,
  historical: ChartHistoricalEntry[],
): ComponentChildren {
  switch (chart.id) {
    case "query_heatmap":
      return <QueryHeatmap summary={summary} />;
    case "percentile_ladder":
      return (
        <PercentileLadder
          rows={summary.platforms.flatMap((platform, index) =>
            platform.percentile_stats !== null
              ? [
                  {
                    result_id: platform.result_id,
                    platform: platform.platform,
                    displayLabel: platform.platform,
                    percentile_stats: platform.percentile_stats,
                    colorIdx: index,
                  },
                ]
              : [],
          )}
        />
      );
    case "cdf_chart":
      return <CDFChart summary={summary} />;
    case "query_histogram":
      return <QueryHistogram summary={summary} />;
    case "stacked_phase":
      return <StackedPhase summary={summary} />;
    case "time_series":
      return (
        <TimeSeries
          entries={historical}
          primaryMetric={summary.ranking?.primary_metric as "power_score" | "display_geomean_ms" | undefined}
        />
      );
    case "rank_table":
      return <RankTable summary={summary} />;
    case "cost_scatter":
      return <CostScatter summary={summary} />;
    default:
      return null;
  }
}

function ChartThumbnail({
  chartId,
  summary,
  historical,
}: {
  chartId: string;
  summary: BenchmarkSummary;
  historical: ChartHistoricalEntry[];
}) {
  switch (chartId) {
    case "query_heatmap":
      return <MiniHeatmap summary={summary} />;
    case "percentile_ladder":
      return <MiniPercentiles summary={summary} />;
    case "cdf_chart":
      return <MiniCDF summary={summary} />;
    case "query_histogram":
      return <MiniHistogram summary={summary} />;
    case "stacked_phase":
      return <MiniPhases summary={summary} />;
    case "time_series":
      return <MiniTrend summary={summary} historical={historical} />;
    case "rank_table":
      return <MiniRanks summary={summary} />;
    case "cost_scatter":
      return <MiniCost summary={summary} />;
    default:
      return <MiniUnavailable label="Preview unavailable" />;
  }
}

function MiniFrame({ children }: { children: ComponentChildren }) {
  return (
    <div
      class="summary-chart-thumbnail mt-4 flex items-center justify-center rounded-md bg-[var(--bb-surface-data-muted)]
        p-2"
    >
      {children}
    </div>
  );
}

function MiniUnavailable({ label }: { label: string }) {
  return (
    <MiniFrame>
      <p class="px-3 text-center text-xs text-[var(--bb-data-fg-subtle)]">{label}</p>
    </MiniFrame>
  );
}

function MiniHeatmap({ summary }: { summary: BenchmarkSummary }) {
  const queryIds = summary.query_ids.slice(0, 14);
  const platforms = summary.platforms.slice(0, 5);
  if (queryIds.length === 0 || platforms.length === 0) return <MiniUnavailable label="No query timings recorded" />;
  const minima = new Map(
    queryIds.map((queryId) => {
      const values = platforms.map((platform) => platformTimingValue(platform, queryId)).filter(isValidTimingValue);
      return [queryId, values.length > 0 ? Math.min(...values) : null];
    }),
  );
  return (
    <MiniFrame>
      <div
        class="summary-mini-heatmap grid w-full gap-px"
        style={{ gridTemplateColumns: `repeat(${queryIds.length}, minmax(0, 1fr))` }}
        aria-label="Heatmap thumbnail"
      >
        {platforms.flatMap((platform) =>
          queryIds.map((queryId) => {
            const value = platformTimingValue(platform, queryId);
            const hue = colorForCell(value, minima.get(queryId) ?? null);
            return (
              <span
                key={`${platform.result_id}-${queryId}`}
                class="aspect-square rounded-[1px]"
                style={{ backgroundColor: hue === null ? "var(--bb-data-border)" : `hsl(${hue} 68% 56%)` }}
                title={`${platform.platform} · ${queryId}`}
              />
            );
          }),
        )}
      </div>
    </MiniFrame>
  );
}

function MiniPercentiles({ summary }: { summary: BenchmarkSummary }) {
  const rows = summary.platforms
    .filter((platform) => isTimingDisplayable(platform) && platform.percentile_stats !== null)
    .slice(0, 6);
  if (rows.length === 0) return <MiniUnavailable label="No percentile statistics recorded" />;
  const max = Math.max(...rows.map((row) => row.percentile_stats!.p99), 1);
  return (
    <MiniFrame>
      <div class="summary-mini-stack w-full space-y-1.5">
        {rows.map((row, index) => (
          <div key={row.result_id} class="flex items-center gap-1">
            <span class="w-10 truncate text-[8px] text-[var(--bb-data-fg-subtle)]">{row.platform}</span>
            <span class="relative h-2 flex-1 rounded-sm bg-[var(--bb-data-border)]">
              <span
                class="absolute inset-y-0 left-0 rounded-sm opacity-40"
                style={{
                  width: `${(row.percentile_stats!.p99 / max) * 100}%`,
                  backgroundColor: paletteColor(index),
                }}
              />
              <span
                class="absolute inset-y-0 left-0 rounded-sm"
                style={{
                  width: `${(row.percentile_stats!.p50 / max) * 100}%`,
                  backgroundColor: paletteColor(index),
                }}
              />
            </span>
          </div>
        ))}
      </div>
    </MiniFrame>
  );
}

function MiniCDF({ summary }: { summary: BenchmarkSummary }) {
  const series = summary.platforms.slice(0, 6).map((platform, index) => ({
    color: timeSeriesColor(index),
    points: computeECDFPoints(summary.query_ids.map((queryId) => platformTimingValue(platform, queryId))),
  })).filter((entry) => entry.points.length > 0);
  const allMs = series.flatMap((entry) => entry.points.map((point) => point.x));
  const scale = buildLogLatencyScale(allMs, { lowerPad: 0.2, upperPad: 0.2 });
  if (scale === null) return <MiniUnavailable label="No valid display timings" />;
  const width = 240;
  const height = 86;
  return (
    <MiniFrame>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        class="summary-mini-plot h-[5.5rem] w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label="CDF thumbnail"
      >
        <line x1="8" y1="76" x2="232" y2="76" stroke="var(--bb-chart-grid)" />
        <line x1="8" y1="8" x2="8" y2="76" stroke="var(--bb-chart-grid)" />
        {series.map((entry, index) => {
          const d = entry.points.map((point, pointIndex) => {
            const x = 8 + logLatencyFraction(point.x, scale) * 224;
            const y = 76 - (point.y / 100) * 68;
            return pointIndex === 0 ? `M${x.toFixed(1)},${y.toFixed(1)}` : `H${x.toFixed(1)} V${y.toFixed(1)}`;
          }).join(" ");
          return <path key={index} d={d} fill="none" stroke={entry.color} stroke-width="1.5" />;
        })}
      </svg>
    </MiniFrame>
  );
}

function MiniHistogram({ summary }: { summary: BenchmarkSummary }) {
  const values = summary.query_ids.slice(0, 20).map((queryId) => {
    const timings = summary.platforms
      .map((platform) => platformTimingValue(platform, queryId))
      .filter(isValidTimingValue);
    return timings.length > 0 ? timings.reduce((total, value) => total + value, 0) / timings.length : null;
  }).filter(isValidTimingValue);
  if (values.length === 0) return <MiniUnavailable label="No valid query timings" />;
  const max = Math.max(...values, 1);
  return (
    <MiniFrame>
      <div class="summary-mini-plot flex h-[5.5rem] w-full items-end gap-1 border-b border-l border-[var(--bb-data-border)] px-2 pb-1">
        {values.map((value, index) => (
          <span
            key={index}
            class="min-w-0 flex-1 rounded-t-sm bg-[var(--bb-chart-cat-1)]"
            style={{ height: `${Math.max(4, (value / max) * 100)}%` }}
          />
        ))}
      </div>
    </MiniFrame>
  );
}

function MiniPhases({ summary }: { summary: BenchmarkSummary }) {
  const rows = summary.platforms
    .filter((platform) => platform.phase_durations && Object.keys(platform.phase_durations).length > 0)
    .slice(0, 6);
  if (rows.length === 0) return <MiniUnavailable label="No phase breakdown recorded" />;
  const max = Math.max(
    ...rows.map((row) => Object.values(row.phase_durations!).reduce((total, value) => total + value, 0)),
    1,
  );
  return (
    <MiniFrame>
      <div class="summary-mini-stack w-full space-y-1.5">
        {rows.map((row) => {
          const phases = Object.entries(row.phase_durations!);
          const total = phases.reduce((sum, [, value]) => sum + value, 0);
          return (
            <div
              key={row.result_id}
              class="flex h-2 overflow-hidden rounded-sm bg-[var(--bb-data-border)]"
              style={{ width: `${Math.max(12, (total / max) * 100)}%` }}
            >
              {phases.map(([phase, value]) => (
                <span
                  key={phase}
                  style={{
                    width: `${(value / total) * 100}%`,
                    backgroundColor: PHASE_COLORS[phase] ?? "var(--bb-chart-axis)",
                  }}
                />
              ))}
            </div>
          );
        })}
      </div>
    </MiniFrame>
  );
}

function MiniTrend({ summary, historical }: { summary: BenchmarkSummary; historical: ChartHistoricalEntry[] }) {
  const metric = summary.ranking?.primary_metric === "power_score" ? "power_score" : "display_geomean_ms";
  const values = historical.map((entry) => entry[metric]).filter(isValidTimingValue);
  if (values.length < 2) return <MiniUnavailable label="Not enough history for a trend" />;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const byPlatform = new Map<string, ChartHistoricalEntry[]>();
  historical.forEach((entry) => {
    const group = byPlatform.get(entry.platform_id) ?? [];
    group.push(entry);
    byPlatform.set(entry.platform_id, group);
  });
  return (
    <MiniFrame>
      <svg
        viewBox="0 0 240 86"
        class="summary-mini-plot h-[5.5rem] w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label="Trend thumbnail"
      >
        <line x1="8" y1="76" x2="232" y2="76" stroke="var(--bb-chart-grid)" />
        {Array.from(byPlatform.values()).slice(0, 6).map((entries, index) => {
          const points = entries
            .filter((entry) => isValidTimingValue(entry[metric]))
            .sort((a, b) => a.run_date.localeCompare(b.run_date));
          if (points.length < 2) return null;
          const d = points.map((entry, pointIndex) => {
            const x = 12 + (pointIndex / Math.max(points.length - 1, 1)) * 216;
            const normalized = ((entry[metric] as number) - min) / span;
            const y = metric === "power_score" ? 10 + (1 - normalized) * 62 : 10 + normalized * 62;
            return `${pointIndex === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
          }).join(" ");
          return <path key={index} d={d} fill="none" stroke={timeSeriesColor(index)} stroke-width="1.5" />;
        })}
      </svg>
    </MiniFrame>
  );
}

function MiniRanks({ summary }: { summary: BenchmarkSummary }) {
  const queryIds = summary.query_ids.slice(0, 8);
  const ranks = computeRankTable(
    queryIds,
    summary.platforms.map((platform) =>
      Object.fromEntries(queryIds.map((queryId) => [queryId, platformTimingValue(platform, queryId)])),
    ),
  );
  if (queryIds.length === 0 || summary.platforms.length === 0) {
    return <MiniUnavailable label="No rank-safe query timings" />;
  }
  return (
    <MiniFrame>
      <div
        class="summary-mini-grid grid w-full gap-px"
        style={{ gridTemplateColumns: `repeat(${summary.platforms.length}, minmax(0, 1fr))` }}
        aria-label="Rank table thumbnail"
      >
        {queryIds.flatMap((queryId) =>
          summary.platforms.map((platform, index) => {
            const rank = ranks[queryId]?.[index];
            return (
              <span
                key={`${queryId}-${platform.result_id}`}
                class="flex aspect-[1.8] items-center justify-center rounded-[1px] font-mono text-[8px]"
                style={{
                  backgroundColor: rank === 1 ? "var(--bb-chart-cat-1)" : "var(--bb-tone-neutral-bg)",
                  color: rank === 1 ? "white" : "var(--bb-data-fg-muted)",
                }}
              >
                {rank ?? "—"}
              </span>
            );
          }),
        )}
      </div>
    </MiniFrame>
  );
}

function MiniCost({ summary }: { summary: BenchmarkSummary }) {
  const metric = summary.ranking?.primary_metric === "power_score" ? "power_score" : "display_geomean_ms";
  const points = summary.platforms.filter(
    (platform) =>
      Number.isFinite(platform.normalized_cost_usd) &&
      platform.normalized_cost_usd !== null &&
      validPrimaryMetricValue(platform, metric) !== null,
  );
  if (points.length === 0) return <MiniUnavailable label="No normalized cost recorded" />;
  const costs = points.map((point) => point.normalized_cost_usd as number);
  const metricValues = points.map((point) => validPrimaryMetricValue(point, metric) as number);
  const minCost = Math.min(...costs);
  const maxCost = Math.max(...costs);
  const minMetric = Math.min(...metricValues);
  const maxMetric = Math.max(...metricValues);
  const higherIsBetter = metric === "power_score";
  return (
    <MiniFrame>
      <div class="summary-mini-plot relative h-[5.5rem] w-full border-b border-l border-[var(--bb-data-border)]">
        {points.map((point, index) => {
          const x = ((point.normalized_cost_usd as number) - minCost) / (maxCost - minCost || 1);
          const normalized = ((validPrimaryMetricValue(point, metric) as number) - minMetric) /
            (maxMetric - minMetric || 1);
          const y = higherIsBetter ? 1 - normalized : normalized;
          return (
            <span
              key={point.result_id}
              class="absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full"
              style={{
                left: `${8 + x * 90}%`,
                top: `${8 + y * 84}%`,
                backgroundColor: paletteColor(index),
              }}
              title={point.platform}
            />
          );
        })}
      </div>
    </MiniFrame>
  );
}
