import { formatTimingExclusion } from "@/lib/displayEligibility";

export type CompareExclusionCategory = "coverage" | "timing" | "visibility" | "cohort" | "limit" | "rank" | "unknown";

export interface CompareExclusionReasonCopy {
  code: string;
  shortText: string;
  detailText: string;
  recoveryHint: string;
  category: CompareExclusionCategory;
}

const REASON_COPY: Record<string, CompareExclusionReasonCopy> = {
  no_queries: {
    code: "no_queries",
    shortText: "No query timings",
    detailText: "This run did not publish query timing evidence for comparison.",
    recoveryHint: "Choose a run that published query timings, or clear filters to find comparable rows.",
    category: "coverage",
  },
  no_valid_display_timing: {
    code: "no_valid_display_timing",
    shortText: "No usable timings",
    detailText: "This run has no positive timing measurements that can be compared.",
    recoveryHint: "Choose a run with positive timings, or clear filters to see more runs.",
    category: "timing",
  },
  no_display_timing: {
    code: "no_display_timing",
    shortText: "No timing recorded",
    detailText: "This run has no timing measurement to compare.",
    recoveryHint: "Choose a run with published timings.",
    category: "timing",
  },
  missing_timings: {
    code: "missing_timings",
    shortText: "Missing timings",
    detailText: "This run is missing required query timings.",
    recoveryHint: "Clear filters or choose a run with more complete query coverage.",
    category: "coverage",
  },
  missing_timing: {
    code: "missing_timing",
    shortText: "Missing timing",
    detailText: "This run is missing a required query timing.",
    recoveryHint: "Choose a run with complete timing evidence for the selected ranking.",
    category: "coverage",
  },
  insufficient_query_coverage: {
    code: "insufficient_query_coverage",
    shortText: "Insufficient query coverage",
    detailText: "This run does not include enough usable query timings.",
    recoveryHint: "Clear filters or choose another run with more valid query timings.",
    category: "coverage",
  },
  insufficient_valid_timings: {
    code: "insufficient_valid_timings",
    shortText: "Insufficient valid timings",
    detailText: "This run does not include enough usable query timings.",
    recoveryHint: "Choose a run with at least two valid query timings.",
    category: "coverage",
  },
  insufficient_common_valid_timings: {
    code: "insufficient_common_valid_timings",
    shortText: "Not enough shared timings",
    detailText: "Selected runs do not share at least two valid query timings.",
    recoveryHint: "Clear selection and choose runs from a ranking with shared timing evidence.",
    category: "coverage",
  },
  insufficient_common_valid_timing_coverage: {
    code: "insufficient_common_valid_timing_coverage",
    shortText: "Not enough shared coverage",
    detailText: "Selected runs do not share enough valid query timing coverage.",
    recoveryHint: "Clear selection and choose runs with broader query coverage.",
    category: "coverage",
  },
  zero_timing: {
    code: "zero_timing",
    shortText: "Zero timing excluded",
    detailText: "A zero timing cannot be used in this comparison.",
    recoveryHint: "Choose a run with positive timing measurements.",
    category: "timing",
  },
  zero_timings_only: {
    code: "zero_timings_only",
    shortText: "Only zero timings",
    detailText: "Only exact zero timings are available for this run.",
    recoveryHint: "Choose a run with positive timing measurements.",
    category: "timing",
  },
  hidden_result: {
    code: "hidden_result",
    shortText: "Hidden result",
    detailText: "This result is not in the public comparison set.",
    recoveryHint: "Choose a public result from the current ranking.",
    category: "visibility",
  },
  visibility_not_comparable: {
    code: "visibility_not_comparable",
    shortText: "Not publicly comparable",
    detailText: "Visibility policy excludes this result from comparison.",
    recoveryHint: "Choose a published, maintainer-reviewed result.",
    category: "visibility",
  },
  compliance_not_rankable: {
    code: "compliance_not_rankable",
    shortText: "Not included in rankings",
    detailText: "This result does not meet the requirements for a ranked result.",
    recoveryHint: "Review its run receipt, or choose a result that is included in rankings.",
    category: "rank",
  },
  trust_not_rankable: {
    code: "trust_not_rankable",
    shortText: "Source not included in rankings",
    detailText: "Results from this source are not included in rankings.",
    recoveryHint: "Choose a result from an accepted source.",
    category: "rank",
  },
  validation_not_clean: {
    code: "validation_not_clean",
    shortText: "Validation did not pass",
    detailText: "This result is not ranked because its validation did not pass.",
    recoveryHint: "Choose a result that passed validation.",
    category: "rank",
  },
  tuning_not_applied: {
    code: "tuning_not_applied",
    shortText: "Tuning not applied",
    detailText: "Custom tuning was requested, but the run did not record any applied settings.",
    recoveryHint: "Choose a run whose receipt lists the tuning settings that were applied.",
    category: "rank",
  },
  display_metric_unavailable: {
    code: "display_metric_unavailable",
    shortText: "Timing unavailable",
    detailText: "This run has no timing measurement to compare.",
    recoveryHint: "Choose a run with a published timing measurement.",
    category: "timing",
  },
  missing_display_metric: {
    code: "missing_display_metric",
    shortText: "Timing not recorded",
    detailText: "This run has no timing measurement to compare.",
    recoveryHint: "Choose a run with a published timing measurement.",
    category: "timing",
  },
};

export function describeCompareExclusionReason(reason: string | null | undefined): CompareExclusionReasonCopy | null {
  if (reason === null || reason === undefined || reason.trim() === "") return null;
  const normalized = reason.trim();
  const known = REASON_COPY[normalized];
  if (known) return known;

  if (normalized.startsWith("Locked:")) {
    return {
      code: "cohort_lock",
      shortText: "Different ranking",
      detailText: normalized,
      recoveryHint: "Clear the current selection or choose a row from the locked ranking.",
      category: "cohort",
    };
  }

  if (/^Up to \d+ runs can be compared\.?$/.test(normalized)) {
    return {
      code: "selection_limit",
      shortText: "Selection limit reached",
      detailText: ensureSentence(normalized),
      recoveryHint: "Clear one selected run before adding another.",
      category: "limit",
    };
  }

  const detailText = formatTimingExclusion(normalized, humanizeReason(normalized));
  return {
    code: normalized,
    shortText: sentenceToShortText(detailText),
    detailText,
    recoveryHint: "Clear filters or choose a different comparison candidate.",
    category: "unknown",
  };
}

export function summarizeCompareExclusionReasons(
  reasons: readonly (string | null | undefined)[],
): { copy: CompareExclusionReasonCopy; count: number }[] {
  const byCode = new Map<string, { copy: CompareExclusionReasonCopy; count: number }>();
  for (const reason of reasons) {
    const copy = describeCompareExclusionReason(reason);
    if (copy === null) continue;
    const existing = byCode.get(copy.code);
    if (existing) existing.count += 1;
    else byCode.set(copy.code, { copy, count: 1 });
  }
  return [...byCode.values()].sort((a, b) => b.count - a.count || a.copy.shortText.localeCompare(b.copy.shortText));
}

function ensureSentence(text: string): string {
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

function humanizeReason(reason: string): string {
  return ensureSentence(reason.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()));
}

function sentenceToShortText(sentence: string): string {
  const first = sentence.split(/[.!?]/)[0]?.trim() ?? sentence;
  return first.length > 0 ? first : "Not comparable";
}
