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
    shortText: "No valid display timing",
    detailText: "This run has no positive display timing values available for comparison.",
    recoveryHint: "Choose a run with positive timing evidence, or clear filters to widen the cohort.",
    category: "timing",
  },
  no_display_timing: {
    code: "no_display_timing",
    shortText: "No display timing",
    detailText: "Display timing is unavailable for this run.",
    recoveryHint: "Choose a run with published display timings.",
    category: "timing",
  },
  missing_timings: {
    code: "missing_timings",
    shortText: "Missing timings",
    detailText: "Required query timing evidence is missing for this run.",
    recoveryHint: "Clear filters or choose a run with more complete query coverage.",
    category: "coverage",
  },
  missing_timing: {
    code: "missing_timing",
    shortText: "Missing timing",
    detailText: "A required query timing is missing for this run.",
    recoveryHint: "Choose a run with complete timing evidence for the selected cohort.",
    category: "coverage",
  },
  insufficient_query_coverage: {
    code: "insufficient_query_coverage",
    shortText: "Insufficient query coverage",
    detailText: "Result does not have enough valid query coverage.",
    recoveryHint: "Clear filters or choose another run with more valid query timings.",
    category: "coverage",
  },
  insufficient_valid_timings: {
    code: "insufficient_valid_timings",
    shortText: "Insufficient valid timings",
    detailText: "Result does not have enough valid query timings.",
    recoveryHint: "Choose a run with at least two valid query timings.",
    category: "coverage",
  },
  insufficient_common_valid_timings: {
    code: "insufficient_common_valid_timings",
    shortText: "Not enough shared timings",
    detailText: "Selected runs do not share at least two valid query timings.",
    recoveryHint: "Clear selection and choose runs from a cohort with shared timing evidence.",
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
    detailText: "Exact zero timing is excluded from display evidence.",
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
    recoveryHint: "Choose a public result from the current cohort.",
    category: "visibility",
  },
  visibility_not_comparable: {
    code: "visibility_not_comparable",
    shortText: "Not publicly comparable",
    detailText: "Visibility policy excludes this result from comparison.",
    recoveryHint: "Choose a public curated result.",
    category: "visibility",
  },
  compliance_not_rankable: {
    code: "compliance_not_rankable",
    shortText: "Outside ranked class",
    detailText: "This result is outside the ranked compliance class.",
    recoveryHint: "Use the receipt for audit context, or choose a ranked-compliance run.",
    category: "rank",
  },
  trust_not_rankable: {
    code: "trust_not_rankable",
    shortText: "Trust tier unranked",
    detailText: "Trust policy excludes this result from ranking.",
    recoveryHint: "Choose a run from a rankable trust tier.",
    category: "rank",
  },
  validation_not_clean: {
    code: "validation_not_clean",
    shortText: "Validation not clean",
    detailText: "Validation status excludes this result from ranking.",
    recoveryHint: "Choose a run with clean validation status.",
    category: "rank",
  },
  display_metric_unavailable: {
    code: "display_metric_unavailable",
    shortText: "Display metric unavailable",
    detailText: "Display timing is unavailable for this run.",
    recoveryHint: "Choose a run with display timing evidence.",
    category: "timing",
  },
  missing_display_metric: {
    code: "missing_display_metric",
    shortText: "Missing display metric",
    detailText: "Display timing is unavailable for this run.",
    recoveryHint: "Choose a run with display timing evidence.",
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
      shortText: "Different cohort",
      detailText: normalized,
      recoveryHint: "Clear the current selection or choose a row from the locked cohort.",
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
