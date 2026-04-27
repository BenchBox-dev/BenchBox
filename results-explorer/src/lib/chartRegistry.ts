/**
 * chartRegistry.ts - Explorer chart type registry.
 *
 * Mirrors the canonical 16-entry list in
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

import type { BenchmarkSummary, DetailResult } from "@/types";

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
  /** Needs cost_usd to be populated on ≥1 platform. */
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

export interface ChartRegistryEntry {
  /** Canonical ID - matches chart_types.py ALL_CHART_TYPES entry. */
  id: string;
  title: string;
  description: string;
  requires: DataRequirements;
  /** Python CLI equivalent chart type name (always === id). */
  cli_equivalent: string;
}

// ---------------------------------------------------------------------------
// Registry - must stay in sync with chart_types.py _CHART_SPECS order
// ---------------------------------------------------------------------------

export const CHART_REGISTRY: readonly ChartRegistryEntry[] = [
  {
    id: "performance_bar",
    title: "Performance Bar",
    description: "Bar chart comparing total runtime across platforms",
    requires: { requiresSummary: true },
    cli_equivalent: "performance_bar",
  },
  {
    id: "power_bar",
    title: "Power@Size Bar",
    description: "Bar chart comparing TPC Power@Size metric across platforms (higher is better)",
    requires: { requiresSummary: true, requiresPowerScore: true },
    cli_equivalent: "power_bar",
  },
  {
    id: "distribution_box",
    title: "Distribution Box Plot",
    description: "Box plot showing query execution time distribution",
    requires: { requiresSummary: true, requiresQueryTimings: true },
    cli_equivalent: "distribution_box",
  },
  {
    id: "query_heatmap",
    title: "Query Heatmap",
    description: "Heatmap comparing per-query execution times across platforms",
    requires: { requiresSummary: true, requiresQueryTimings: true },
    cli_equivalent: "query_heatmap",
  },
  {
    id: "query_histogram",
    title: "Query Histogram",
    description:
      "Vertical bar histogram showing latency per query (auto-splits for >33 queries)",
    requires: { requiresSummary: true, requiresQueryTimings: true },
    cli_equivalent: "query_histogram",
  },
  {
    id: "cost_scatter",
    title: "Cost vs Performance Scatter",
    description: "Scatter plot of cost vs performance (requires cost data)",
    requires: { requiresSummary: true, requiresCostData: true },
    cli_equivalent: "cost_scatter",
  },
  {
    id: "time_series",
    title: "Performance Trend",
    description: "Line chart showing performance trends over time",
    requires: { requiresHistorical: true },
    cli_equivalent: "time_series",
  },
  {
    id: "comparison_bar",
    title: "Comparison Bar",
    description:
      "Paired side-by-side bars comparing two runs per query with % change annotations",
    requires: { requiresTwoResults: true },
    cli_equivalent: "comparison_bar",
  },
  {
    id: "diverging_bar",
    title: "Diverging Bar",
    description:
      "Centered-zero chart showing regression/improvement distribution sorted by magnitude",
    requires: { requiresTwoResults: true },
    cli_equivalent: "diverging_bar",
  },
  {
    id: "summary_box",
    title: "Summary Box",
    description:
      "Bordered panel with aggregate stats (geo mean, total time, improved/regressed counts)",
    requires: {},
    cli_equivalent: "summary_box",
  },
  {
    id: "percentile_ladder",
    title: "Percentile Ladder",
    description: "Percentile ladder chart (P50/P90/P95/P99) across platforms",
    requires: { requiresSummary: true, requiresPercentileStats: true },
    cli_equivalent: "percentile_ladder",
  },
  {
    id: "normalized_speedup",
    title: "Normalized Speedup",
    description: "Normalized speedup chart relative to a selected baseline platform",
    requires: { requiresTwoResults: true },
    cli_equivalent: "normalized_speedup",
  },
  {
    id: "stacked_phase",
    title: "Stacked Phase Breakdown",
    description: "Stacked phase breakdown chart across benchmark execution phases",
    requires: { requiresSummary: true, requiresPhaseDurations: true },
    cli_equivalent: "stacked_phase",
  },
  {
    id: "sparkline_table",
    title: "Sparkline Table",
    description: "Compact sparkline table of key metrics across platforms",
    requires: { requiresSummary: true },
    cli_equivalent: "sparkline_table",
  },
  {
    id: "cdf_chart",
    title: "CDF Chart",
    description: "Cumulative distribution chart of per-query execution latency",
    requires: { requiresSummary: true, requiresQueryTimings: true },
    cli_equivalent: "cdf_chart",
  },
  {
    id: "rank_table",
    title: "Rank Table",
    description: "Per-query platform ranking table (1st=fastest)",
    requires: { requiresSummary: true, requiresQueryTimings: true },
    cli_equivalent: "rank_table",
  },
] as const;

/** All 16 canonical chart type IDs - must match chart_types.py ALL_CHART_TYPES. */
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
  const timings = Object.fromEntries(
    detail.display_timings.map((timing) => [timing.query_id, timing.display_ms]),
  );

  return {
    benchmark: detail.benchmark,
    scale_factor: detail.scale_factor,
    phase: detail.test_type ?? "power",
    query_ids: detail.display_timings.map((timing) => timing.query_id),
    platforms: [
      {
        result_id: detail.result_id,
        short_id: detail.result_id.slice(0, 8),
        platform_id: detail.platform_id,
        platform: detail.platform,
        platform_version: detail.platform_version,
        tuning_mode: detail.tuning_mode,
        tuning_hash: detail.tuning_hash,
        execution_mode: detail.execution_mode,
        trust_label: detail.trust_label,
        run_date: detail.run_date,
        is_ranking_eligible: true,
        power_score: detail.power_score,
        display_geomean_ms: detail.display_geomean_ms,
        sample_geomean_ms: detail.geomean_ms,
        cost_usd: detail.cost_usd,
        compliance_class: detail.compliance_class,
        percentile_stats: null,
        phase_durations: null,
        timings,
      },
    ],
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
    platforms: results.map((result) => ({
      result_id: result.result_id,
      short_id: result.result_id.slice(0, 8),
      platform_id: result.platform_id,
      platform: result.platform,
      platform_version: result.platform_version,
      tuning_mode: result.tuning_mode,
      tuning_hash: result.tuning_hash,
      execution_mode: result.execution_mode,
      trust_label: result.trust_label,
      run_date: result.run_date,
      is_ranking_eligible: true,
      power_score: result.power_score,
      display_geomean_ms: result.display_geomean_ms,
      sample_geomean_ms: result.geomean_ms,
      cost_usd: result.cost_usd,
      compliance_class: result.compliance_class,
      percentile_stats: null,
      phase_durations: null,
      timings: Object.fromEntries(
        result.display_timings.map((timing) => [timing.query_id, timing.display_ms]),
      ),
    })),
    cell_reduction: "median",
    ranking: {
      ...rankingFromPrimaryMetric(primaryMetric),
      secondary_metric: "platform",
    },
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
    hasCostData: summary?.platforms.some((platform) => platform.cost_usd !== null) ?? false,
    hasPowerScore: summary?.platforms.some((platform) => platform.power_score !== null) ?? false,
    hasPhaseDurations:
      summary?.platforms.some(
        (platform) => platform.phase_durations !== null && Object.keys(platform.phase_durations).length > 0,
      ) ?? false,
    hasHistorical: historical.length >= 2,
    hasQueryTimings:
      (summary?.platforms.some((platform) =>
        Object.values(platform.timings).some((v) => v !== null && v > 0),
      ) ?? false),
    hasPercentileStats:
      summary?.platforms.some((platform) => platform.percentile_stats !== null) ?? false,
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
