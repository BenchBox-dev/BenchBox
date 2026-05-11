import type {
  BenchmarkSummary,
  DetailResult,
  MetaCohort,
  MetaCohortPlatform,
  PlatformRow,
  QueryDisplayTiming,
} from "@/types";

export type EligibilityRow = DetailResult | PlatformRow | MetaCohortPlatform;
export type PrimaryMetricRow = DetailResult | PlatformRow;
export type PrimaryMetric = "power_score" | "display_geomean_ms";

export interface CompareEvidenceSummary {
  comparable: boolean;
  reason: string | null;
  totalQueries: number;
  commonValidQueries: number;
  requiredValidQueriesPerResult: number;
}

const EXCLUSION_LABELS: Record<string, string> = {
  compliance_not_rankable: "Result is outside the ranked compliance class.",
  display_metric_unavailable: "Display timing is unavailable.",
  failed_queries: "One or more queries failed.",
  hidden_result: "Result is not in the public comparison set.",
  insufficient_common_valid_timing_coverage: "Selected runs do not share enough valid query timings.",
  insufficient_common_valid_timings: "Selected runs do not share at least two valid query timings.",
  insufficient_query_coverage: "Result does not have enough valid query coverage.",
  insufficient_valid_timings: "Result does not have enough valid query timings.",
  invalid_timing: "Timing is invalid.",
  missing_display_metric: "Display timing is unavailable.",
  missing_primary_metric: "Primary metric is unavailable.",
  missing_timing: "Timing is missing.",
  no_comparable_results: "No comparable results are available.",
  no_display_timing: "Display timing is unavailable.",
  no_rankable_results: "No rankable results are available.",
  no_valid_display_timing: "No valid display timing is available.",
  non_positive_primary_metric: "Primary metric is not positive.",
  non_positive_timing: "Timing is not positive.",
  partial_query_coverage: "Result has partial query coverage.",
  trust_not_rankable: "Trust policy excludes this result from ranking.",
  validation_not_clean: "Validation status excludes this result from ranking.",
  visibility_not_comparable: "Visibility policy excludes this result from comparison.",
  visibility_not_rankable: "Visibility policy excludes this result from ranking.",
  zero_timing: "Exact zero timing is excluded from display evidence.",
  zero_timings_only: "Only exact zero timings are available.",
};

export function isValidTimingValue(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && Number.isFinite(value) && value > 0;
}

export function validTimingValues(values: readonly (number | null | undefined)[]): number[] {
  return values.filter(isValidTimingValue);
}

export function displayTimingValue(timing: QueryDisplayTiming | null | undefined): number | null {
  if (!timing?.is_valid_display_timing) return null;
  return isValidTimingValue(timing.display_ms) ? timing.display_ms : null;
}

export function validDisplayTimingValues(timings: readonly QueryDisplayTiming[]): number[] {
  return timings.map(displayTimingValue).filter(isValidTimingValue);
}

export function timingValueForQuery(result: DetailResult, queryId: string): number | null {
  return displayTimingValue(result.display_timings.find((timing) => timing.query_id === queryId));
}

export function platformTimingValue(row: PlatformRow, queryId: string): number | null {
  const eligibility = row.timing_eligibility[queryId];
  if (!eligibility?.is_valid_display_timing) return null;
  return validPlatformTimingValue(row.timings[queryId] ?? null);
}

export function validPlatformTimingValue(value: number | null | undefined): number | null {
  return isValidTimingValue(value) ? value : null;
}

export function isTimingDisplayable(row: EligibilityRow): boolean {
  return row.display_exclusion_reason === null;
}

export function isComparable(row: EligibilityRow): boolean {
  return row.comparison_exclusion_reason === null;
}

export function isRankable(row: EligibilityRow): boolean {
  return row.ranking_exclusion_reason === null;
}

export function primaryMetricValue(row: PrimaryMetricRow, metric: PrimaryMetric): number | null {
  return metric === "power_score" ? row.power_score : row.display_geomean_ms;
}

export function validPrimaryMetricValue(row: PrimaryMetricRow, metric: PrimaryMetric): number | null {
  const value = primaryMetricValue(row, metric);
  return isValidTimingValue(value) ? value : null;
}

export function formatTimingExclusion(
  input: EligibilityRow | QueryDisplayTiming | string | null | undefined,
  fallback = "Timing is excluded from display evidence.",
): string {
  const reason = exclusionReason(input);
  if (reason === null) return fallback;
  return EXCLUSION_LABELS[reason] ?? humanizeReason(reason);
}

export function formatCohortExclusion(cohort: BenchmarkSummary | MetaCohort): string | null {
  if ("cohort_ranking_exclusion_reason" in cohort && cohort.cohort_ranking_exclusion_reason !== null) {
    return formatTimingExclusion(cohort.cohort_ranking_exclusion_reason, "Cohort is not rankable.");
  }
  if ("platforms" in cohort && cohort.platforms && cohort.platforms.length > 0) {
    if (cohort.platforms.every((platform) => !isRankable(platform))) {
      return EXCLUSION_LABELS.no_rankable_results ?? "No rankable results are available.";
    }
  }
  return null;
}

export function compareEvidenceSummary(results: readonly DetailResult[]): CompareEvidenceSummary {
  const queryIds = [...new Set(results.flatMap((result) => result.display_timings.map((timing) => timing.query_id)))];
  const requiredValidQueriesPerResult = Math.max(2, Math.ceil(queryIds.length * 0.5));
  const commonValidQueries = countCommonValidQueries(results, queryIds);
  const ineligible = results.find((result) => !isComparable(result));
  if (ineligible) {
    return {
      comparable: false,
      reason: formatTimingExclusion(ineligible.comparison_exclusion_reason, "Selected run is not comparable."),
      totalQueries: queryIds.length,
      commonValidQueries,
      requiredValidQueriesPerResult,
    };
  }

  if (commonValidQueries < 2) {
    return {
      comparable: false,
      reason: EXCLUSION_LABELS.insufficient_common_valid_timings ?? "Selected runs do not share enough valid timings.",
      totalQueries: queryIds.length,
      commonValidQueries,
      requiredValidQueriesPerResult,
    };
  }
  const underCovered = results.find(
    (result) => validDisplayTimingValues(result.display_timings).length < requiredValidQueriesPerResult,
  );
  if (underCovered) {
    return {
      comparable: false,
      reason:
        EXCLUSION_LABELS.insufficient_common_valid_timing_coverage ??
        "Selected runs do not share enough valid query timing coverage.",
      totalQueries: queryIds.length,
      commonValidQueries,
      requiredValidQueriesPerResult,
    };
  }
  return {
    comparable: true,
    reason: null,
    totalQueries: queryIds.length,
    commonValidQueries,
    requiredValidQueriesPerResult,
  };
}

function countCommonValidQueries(results: readonly DetailResult[], queryIds: readonly string[]): number {
  return queryIds.filter((queryId) =>
    results.every((result) => timingValueForQuery(result, queryId) !== null),
  ).length;
}

function exclusionReason(input: EligibilityRow | QueryDisplayTiming | string | null | undefined): string | null {
  if (typeof input === "string") return input;
  if (!input) return null;
  if ("timing_exclusion_reason" in input) return input.timing_exclusion_reason;
  return (
    input.display_exclusion_reason ??
    input.comparison_exclusion_reason ??
    input.ranking_exclusion_reason ??
    null
  );
}

function humanizeReason(reason: string): string {
  const text = reason.replace(/_/g, " ");
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}.`;
}
