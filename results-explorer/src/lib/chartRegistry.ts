/**
 * chartRegistry.ts - Explorer chart type registry.
 *
 * Mirrors the canonical semantic chart list in
 * ``benchbox/core/visualization/chart_types.py`` (_CHART_SPECS).
 *
 * Policy: new chart types are added to ``chart_types.py`` first; this
 * file follows.  A parity test (chartRegistry.parity.test.ts) asserts
 * the two lists are in sync (bidirectional).
 *
 * Each entry carries:
 *   - id              matching the Python chart_types.py name
 *   - title           human-readable display name
 *   - description     matches chart_types.py ChartTypeSpec.description
 *   - requires        data requirements (used by pages to gate rendering)
 *   - cli_equivalent  name in chart_types.py (always === id for now)
 */

import type { BenchmarkSummary, DetailResult, PlatformRow } from "@/types";
import {
  isTimingDisplayable,
  isValidTimingValue,
  type ChartDatasetEligibilityClass,
} from "@/lib/displayEligibility";

/**
 * Narrow shape consumed by historical/trend charts (TimeSeries, summary_box).
 *
 * Both `ManifestEntry` and DuckDB `ResultRow`/`PlatformIndexRowRow` satisfy
 * this structurally, so pages can hand over DuckDB query results directly
 * without reshaping.
 */
export interface ChartHistoricalEntry {
  result_id: string;
  benchmark: string;
  scale_factor: number;
  platform: string;
  platform_id: string;
  run_date: string;
  power_score: number | null;
  display_geomean_ms: number | null;
}

export interface DataRequirements {
  /** Needs a BenchmarkSummary artifact (benchmark × platform matrix). */
  requiresSummary?: boolean;
  /** Needs ≥2 results (comparison-mode charts: diverging_bar, speedup, etc.). */
  requiresTwoResults?: boolean;
  /** Needs normalized_cost_usd to be populated on ≥1 normalized platform. */
  requiresCostData?: boolean;
  /** Needs power_score to be populated on ≥1 platform. */
  requiresPowerScore?: boolean;
  /** Needs phase_durations to be populated on ≥1 platform. */
  requiresPhaseDurations?: boolean;
  /** Needs ≥2 ManifestEntries per platform (trend/history charts). */
  requiresHistorical?: boolean;
  /** Needs a per-query timings matrix. */
  requiresQueryTimings?: boolean;
  /** Needs percentile_stats to be populated on ≥1 platform. */
  requiresPercentileStats?: boolean;
}

export type ChartQuestionGroupId =
  | "overview"
  | "per_query"
  | "distribution"
  | "cost"
  | "trend"
  | "rank";

export interface ChartQuestionGroup {
  id: ChartQuestionGroupId;
  label: string;
  description: string;
}

export interface ChartRegistryEntry {
  /** Canonical ID - matches chart_types.py ALL_CHART_TYPES entry. */
  id: string;
  title: string;
  shortTitle: string;
  description: string;
  /** Analytical question this chart answers in Explorer navigation. */
  questionGroup: ChartQuestionGroupId;
  /** Dataset eligibility class enforced before rendering chart data points. */
  eligibilityClass: ChartDatasetEligibilityClass;
  requires: DataRequirements;
  /** Python CLI equivalent chart type name (always === id). */
  cli_equivalent: string;
}

export interface ChartQuestionGroupWithCharts extends ChartQuestionGroup {
  charts: ChartRegistryEntry[];
}

export const CHART_QUESTION_GROUPS: readonly ChartQuestionGroup[] = [
  {
    id: "overview",
    label: "Overview",
    description: "Top-line metric summaries and phase composition",
  },
  {
    id: "per_query",
    label: "Per-query",
    description: "Query-level comparisons and outlier views",
  },
  {
    id: "distribution",
    label: "Distribution",
    description: "Latency spread and percentile shape",
  },
  {
    id: "cost",
    label: "Cost",
    description: "Cost and performance tradeoffs",
  },
  {
    id: "trend",
    label: "Trend",
    description: "Historical movement over time",
  },
  {
    id: "rank",
    label: "Rank",
    description: "Per-query ranking tables",
  },
] as const;

export const CHART_QUESTION_GROUP_BY_ID: Readonly<Record<ChartQuestionGroupId, ChartQuestionGroup>> =
  Object.fromEntries(CHART_QUESTION_GROUPS.map((group) => [group.id, group])) as Record<
    ChartQuestionGroupId,
    ChartQuestionGroup
  >;

// ---------------------------------------------------------------------------
// Registry - must stay in sync with chart_types.py _CHART_SPECS order
// ---------------------------------------------------------------------------

export const CHART_REGISTRY: readonly ChartRegistryEntry[] = [
  {
    id: "performance_bar",
    title: "Performance Bar",
    shortTitle: "Performance",
    description: "Bar chart comparing total runtime across platforms",
    questionGroup: "overview",
    eligibilityClass: "display_safe",
    requires: { requiresSummary: true },
    cli_equivalent: "performance_bar",
  },
  {
    id: "power_bar",
    title: "Power@Size Bar",
    shortTitle: "Power",
    description: "Bar chart comparing TPC Power@Size metric across platforms (higher is better)",
    questionGroup: "overview",
    eligibilityClass: "rank_safe",
    requires: { requiresSummary: true, requiresPowerScore: true },
    cli_equivalent: "power_bar",
  },
  {
    id: "distribution_box",
    title: "Distribution Box Plot",
    shortTitle: "Box Plot",
    description: "Box plot showing query execution time distribution",
    questionGroup: "distribution",
    eligibilityClass: "display_safe",
    requires: { requiresSummary: true, requiresQueryTimings: true },
    cli_equivalent: "distribution_box",
  },
  {
    id: "query_heatmap",
    title: "Query Heatmap",
    shortTitle: "Heatmap",
    description: "Heatmap comparing per-query execution times across platforms",
    questionGroup: "per_query",
    eligibilityClass: "display_safe",
    requires: { requiresSummary: true, requiresQueryTimings: true },
    cli_equivalent: "query_heatmap",
  },
  {
    id: "query_histogram",
    title: "Query Histogram",
    shortTitle: "Histogram",
    description:
      "Vertical bar histogram showing latency per query (auto-splits for >33 queries)",
    questionGroup: "per_query",
    eligibilityClass: "display_safe",
    requires: { requiresSummary: true, requiresQueryTimings: true },
    cli_equivalent: "query_histogram",
  },
  {
    id: "cost_scatter",
    title: "Cost vs Performance Scatter",
    shortTitle: "Cost",
    description: "Scatter plot of normalized cost vs performance with cost-status empty states",
    questionGroup: "cost",
    eligibilityClass: "cost_safe",
    // Adding `requiresCostData` makes the chart unavailable when no platform
    // in the cohort has normalized_cost_usd. Without this gate the Cost tab
    // would render an empty selectable panel and force the user to discover
    // "no cost recorded" by clicking through. The empty state is now
    // surfaced one level up: the tab itself disappears for cost-less cohorts.
    requires: { requiresSummary: true, requiresCostData: true },
    cli_equivalent: "cost_scatter",
  },
  {
    id: "time_series",
    title: "Performance Trend",
    shortTitle: "Trend",
    description: "Line chart showing performance trends over time",
    questionGroup: "trend",
    eligibilityClass: "trend_safe",
    requires: { requiresHistorical: true },
    cli_equivalent: "time_series",
  },
  {
    id: "comparison_bar",
    title: "Comparison Bar",
    shortTitle: "Compare",
    description:
      "Paired side-by-side bars comparing two runs per query with % change annotations",
    questionGroup: "per_query",
    eligibilityClass: "compare_safe",
    requires: { requiresTwoResults: true },
    cli_equivalent: "comparison_bar",
  },
  {
    id: "diverging_bar",
    title: "Diverging Bar",
    shortTitle: "Diverging",
    description:
      "Centered-zero chart showing regression/improvement distribution sorted by magnitude",
    questionGroup: "per_query",
    eligibilityClass: "compare_safe",
    requires: { requiresTwoResults: true },
    cli_equivalent: "diverging_bar",
  },
  {
    id: "summary_box",
    title: "Summary Box",
    shortTitle: "Summary",
    description:
      "Bordered panel with aggregate stats (geo mean, total time, improved/regressed counts)",
    questionGroup: "overview",
    eligibilityClass: "provenance_only",
    requires: {},
    cli_equivalent: "summary_box",
  },
  {
    id: "percentile_ladder",
    title: "Percentile Ladder",
    shortTitle: "Percentiles",
    description: "Percentile ladder chart (P50/P90/P95/P99) across platforms",
    questionGroup: "distribution",
    eligibilityClass: "display_safe",
    requires: { requiresSummary: true, requiresPercentileStats: true },
    cli_equivalent: "percentile_ladder",
  },
  {
    id: "normalized_speedup",
    title: "Normalized Speedup",
    shortTitle: "Speedup",
    description: "Normalized speedup chart relative to a selected baseline platform",
    questionGroup: "per_query",
    eligibilityClass: "compare_safe",
    requires: { requiresTwoResults: true },
    cli_equivalent: "normalized_speedup",
  },
  {
    id: "stacked_phase",
    title: "Stacked Phase Breakdown",
    shortTitle: "Phases",
    description: "Stacked phase breakdown chart across benchmark execution phases",
    questionGroup: "overview",
    eligibilityClass: "display_safe",
    requires: { requiresSummary: true, requiresPhaseDurations: true },
    cli_equivalent: "stacked_phase",
  },
  {
    id: "sparkline_table",
    title: "Sparkline Table",
    shortTitle: "Sparklines",
    description: "Compact sparkline table of key metrics across platforms",
    questionGroup: "overview",
    eligibilityClass: "display_safe",
    requires: { requiresSummary: true },
    cli_equivalent: "sparkline_table",
  },
  {
    id: "cdf_chart",
    title: "CDF Chart",
    shortTitle: "CDF",
    description: "Cumulative distribution chart of per-query execution latency",
    questionGroup: "distribution",
    eligibilityClass: "display_safe",
    requires: { requiresSummary: true, requiresQueryTimings: true },
    cli_equivalent: "cdf_chart",
  },
  {
    id: "rank_table",
    title: "Rank Table",
    shortTitle: "Ranks",
    description: "Per-query platform ranking table (1st=fastest)",
    questionGroup: "rank",
    eligibilityClass: "rank_safe",
    requires: { requiresSummary: true, requiresQueryTimings: true },
    cli_equivalent: "rank_table",
  },
] as const;

/** Canonical chart type IDs - must match chart_types.py ALL_CHART_TYPES. */
export const ALL_CHART_IDS: readonly string[] = CHART_REGISTRY.map((e) => e.id);

/** Quick-lookup map from id → entry. */
export const CHART_REGISTRY_BY_ID: Readonly<Record<string, ChartRegistryEntry>> =
  Object.fromEntries(CHART_REGISTRY.map((e) => [e.id, e]));

/** Returns true when the id is a known chart type. */
export function isValidChartId(id: string): boolean {
  return id in CHART_REGISTRY_BY_ID;
}

export type ChartContext =
  | { kind: "summary"; summary: BenchmarkSummary | null; historical?: ChartHistoricalEntry[] }
  | {
      kind: "compare";
      results: DetailResult[];
      /** Canonical `benchmark_rankings.primary_metric`, loaded from DuckDB. */
      primaryMetric?: "power_score" | "display_geomean_ms";
    }
  | {
      kind: "detail";
      detail: DetailResult;
      historical?: ChartHistoricalEntry[];
      /** Canonical `benchmark_rankings.primary_metric`, loaded from DuckDB. */
      primaryMetric?: "power_score" | "display_geomean_ms";
    };

interface ChartCapabilities {
  hasSummary: boolean;
  hasTwoResults: boolean;
  hasCostData: boolean;
  hasPowerScore: boolean;
  hasPhaseDurations: boolean;
  hasHistorical: boolean;
  hasQueryTimings: boolean;
  hasPercentileStats: boolean;
}

function rankingFromPrimaryMetric(
  primaryMetric: "power_score" | "display_geomean_ms" | undefined,
): { primary_metric: string; primary_order: "asc" | "desc" } {
  return primaryMetric === "power_score"
    ? { primary_metric: "power_score", primary_order: "desc" }
    : { primary_metric: "display_geomean_ms", primary_order: "asc" };
}

function buildDetailSummary(
  detail: DetailResult,
  primaryMetric: "power_score" | "display_geomean_ms" | undefined,
): BenchmarkSummary {
  return {
    benchmark: detail.benchmark,
    scale_factor: detail.scale_factor,
    phase: detail.test_type ?? "power",
    query_ids: detail.display_timings.map((timing) => timing.query_id),
    platforms: [detailToPlatformRow(detail)],
    cell_reduction: "median",
    ranking: {
      ...rankingFromPrimaryMetric(primaryMetric),
      secondary_metric: "platform",
    },
  };
}

function buildCompareSummary(
  results: DetailResult[],
  primaryMetric: "power_score" | "display_geomean_ms" | undefined,
): BenchmarkSummary | null {
  if (results.length === 0) return null;

  const queryIds = [...new Set(results.flatMap((result) => result.display_timings.map((timing) => timing.query_id)))].sort(
    (a, b) => a.localeCompare(b, undefined, { numeric: true }),
  );

  return {
    benchmark: results[0]!.benchmark,
    scale_factor: results[0]!.scale_factor,
    phase: results[0]!.test_type ?? "power",
    query_ids: queryIds,
    platforms: results.map(detailToPlatformRow),
    cell_reduction: "median",
    ranking: {
      ...rankingFromPrimaryMetric(primaryMetric),
      secondary_metric: "platform",
    },
  };
}

function detailToPlatformRow(detail: DetailResult): PlatformRow {
  return {
    result_id: detail.result_id,
    short_id: detail.result_id.slice(0, 8),
    platform_id: detail.platform_id,
    platform: detail.platform,
    platform_version: detail.platform_version,
    tuning_mode: detail.tuning_mode,
    tuning_hash: detail.tuning_hash,
    execution_mode: detail.execution_mode,
    trust_label: detail.trust_label,
    funding: detail.funding,
    run_date: detail.run_date,
    is_ranking_eligible: detail.ranking_exclusion_reason === null,
    has_display_timing: detail.has_display_timing,
    valid_query_count: detail.valid_query_count,
    missing_query_count: detail.missing_query_count,
    zero_timing_count: detail.zero_timing_count,
    display_exclusion_reason: detail.display_exclusion_reason,
    comparison_exclusion_reason: detail.comparison_exclusion_reason,
    ranking_exclusion_reason: detail.ranking_exclusion_reason,
    power_score: detail.power_score,
    display_geomean_ms: detail.display_geomean_ms,
    sample_geomean_ms: detail.geomean_ms,
    cost_usd: detail.cost_usd,
    normalized_cost_usd: detail.normalized_cost_usd,
    cost_model_version: detail.cost_model_version,
    cost_model_source: detail.cost_model_source,
    cost_scope: detail.cost_scope,
    cost_status: detail.cost_status,
    billing_unit: detail.billing_unit,
    pricing_region: detail.pricing_region,
    deployment_class: detail.deployment_class,
    cloud_provider: detail.cloud_provider,
    cloud_region: detail.cloud_region,
    instance_or_warehouse: detail.instance_or_warehouse,
    instance_type: detail.instance_type,
    warehouse_size: detail.warehouse_size,
    node_count: detail.node_count,
    cluster_size: detail.cluster_size,
    storage_format: detail.storage_format,
    storage_tier: detail.storage_tier,
    compliance_class: detail.compliance_class,
    percentile_stats: null,
    phase_durations: null,
    timings: Object.fromEntries(detail.display_timings.map((timing) => [timing.query_id, timing.display_ms])),
    timing_eligibility: Object.fromEntries(
      detail.display_timings.map((timing) => [
        timing.query_id,
        {
          is_valid_display_timing: timing.is_valid_display_timing,
          timing_exclusion_reason: timing.timing_exclusion_reason,
        },
      ]),
    ),
  };
}

export function buildRenderableSummary(context: ChartContext): BenchmarkSummary | null {
  if (context.kind === "summary") return context.summary;
  if (context.kind === "detail") return buildDetailSummary(context.detail, context.primaryMetric);
  return buildCompareSummary(context.results, context.primaryMetric);
}

function getChartCapabilities(context: ChartContext): ChartCapabilities {
  const summary = buildRenderableSummary(context);
  const historical =
    context.kind === "summary"
      ? context.historical ?? []
      : context.kind === "detail"
        ? context.historical ?? []
        : [];

  return {
    hasSummary: summary !== null,
    hasTwoResults: context.kind === "compare" && context.results.length >= 2,
    hasCostData:
      summary?.platforms.some(
        (platform) => platform.cost_status === "normalized" && platform.normalized_cost_usd != null,
      ) ?? false,
    hasPowerScore: summary?.platforms.some((platform) => isValidTimingValue(platform.power_score)) ?? false,
    hasPhaseDurations:
      summary?.platforms.some(
        (platform) =>
          isTimingDisplayable(platform) &&
          platform.phase_durations !== null &&
          Object.keys(platform.phase_durations).length > 0,
      ) ?? false,
    hasHistorical: historical.length >= 2,
    hasQueryTimings:
      (summary?.platforms.some(
        (platform) =>
          summary.query_ids.some((queryId) => Object.prototype.hasOwnProperty.call(platform.timings, queryId)),
      ) ?? false),
    hasPercentileStats:
      summary?.platforms.some((platform) => isTimingDisplayable(platform) && platform.percentile_stats !== null) ?? false,
  };
}

function contextSupportsEntry(entry: ChartRegistryEntry, context: ChartContext): boolean {
  // time_series needs a historical ManifestEntry[] trend across run dates, which
  // neither compare nor detail contexts provide - they are single-point-in-time.
  // The summary context owns historical data when it's present.
  if (context.kind === "compare") {
    return entry.id !== "time_series";
  }

  if (context.kind === "detail") {
    return !entry.requires.requiresTwoResults && entry.id !== "time_series";
  }

  if (context.summary === null) {
    return entry.id === "summary_box" || entry.id === "time_series";
  }

  return true;
}

export function applicableCharts(context: ChartContext): ChartRegistryEntry[] {
  const capabilities = getChartCapabilities(context);
  return CHART_REGISTRY.filter((entry) => {
    if (!contextSupportsEntry(entry, context)) return false;

    const requires = entry.requires;
    if (requires.requiresSummary && !capabilities.hasSummary) return false;
    if (requires.requiresTwoResults && !capabilities.hasTwoResults) return false;
    if (requires.requiresCostData && !capabilities.hasCostData) return false;
    if (requires.requiresPowerScore && !capabilities.hasPowerScore) return false;
    if (requires.requiresPhaseDurations && !capabilities.hasPhaseDurations) return false;
    if (requires.requiresHistorical && !capabilities.hasHistorical) return false;
    if (requires.requiresQueryTimings && !capabilities.hasQueryTimings) return false;
    if (requires.requiresPercentileStats && !capabilities.hasPercentileStats) return false;
    return true;
  });
}

export function groupChartsByQuestion(
  charts: readonly ChartRegistryEntry[],
): ChartQuestionGroupWithCharts[] {
  return CHART_QUESTION_GROUPS.map((group) => ({
    ...group,
    charts: charts.filter((chart) => chart.questionGroup === group.id),
  })).filter((group) => group.charts.length > 0);
}
