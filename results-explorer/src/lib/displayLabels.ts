import type { StatusTone } from "@/components/StatusBadge";
import { humanizeBenchmark } from "@/utils";

// Public-facing formatters for raw internal enum strings.
//
// Centralized so Query rows, facet chips, exports, result receipts, and
// result detail surfaces all render the same humanized label for the same
// raw value. New enum values added at the data layer should land their
// human label here (or fall through to the conservative `formatEnumLabel`
// default).

const TRUST_LABEL_LABELS: Record<string, string> = {
  "maintainer-run": "Maintainer run",
  "community-submission": "Community submission",
};

const VALIDATION_STATUS_LABELS: Record<string, string> = {
  passed: "passed",
  failed: "failed",
  warning: "warning",
  not_applicable: "not applicable",
  pending: "pending",
  // The remaining keys are the full validation-status enum from
  // benchbox/core/results/status.py (NON_CLEAN_VALIDATION_STATUSES). Mirrored
  // here rather than generated, same rationale as FUNDING_LABELS above.
  interrupted: "interrupted",
  partial: "partial pass",
  error: "validation error",
  not_run: "no validation",
  not_validated: "not validated",
  uncertain: "uncertain",
  unknown: "unknown",
};

/**
 * Longer, tooltip-length prose for each validation status. Paired 1:1 with
 * `VALIDATION_STATUS_LABELS` by key; a status without a curated label also has
 * no curated description here and falls back to a generic sentence built from
 * the short label in `describeValidationStatus`.
 */
const VALIDATION_STATUS_DESCRIPTIONS: Record<string, string> = {
  passed: "BenchBox checked this result against the expected answers and found no differences.",
  failed: "Validation ran and found this result incorrect.",
  warning: "Validation ran and flagged a concern short of a hard failure.",
  not_applicable: "Validation does not apply to this result.",
  pending: "Validation has not completed yet.",
  interrupted: "The run was interrupted before validation could complete.",
  partial: "Some queries failed validation; this is a partial pass.",
  error: "The validation process itself errored and produced no verdict.",
  not_run: "Validation was not run for this result. Its measurements have not been checked against the expected answers.",
  not_validated: "This result was not checked against the expected answers.",
  uncertain: "Validation completed with reduced confidence; treat this result with caution.",
  unknown: "Validation status was not recorded for this result.",
};

// Mirrors benchbox/core/results/status.py::CLI_FAILURE_VALIDATION_STATUSES.
// Statuses where the run itself failed at the CLI/execution level.
const VALIDATION_CLI_FAILURE_STATUSES = new Set(["failed", "interrupted", "partial", "error"]);

// Everything else non-clean falls to UNVALIDATED_VALIDATION_STATUSES in
// benchbox/core/results/status.py (not_run, not_validated, uncertain, unknown)
// plus warning/pending: the run completed but validation never produced a
// clean confirmation. Handled by the final `else` branch below rather than a
// duplicate literal set - keep the CLI-failure and clean sets as the only
// hand-maintained lists, same "derived, don't hand-maintain a third set"
// rule status.py itself follows.

// Statuses treated as a clean pass. "passed" is the current producer value;
// "pass", "exact", and "full" are historical/tolerance-mode values that carry
// the same meaning (see ResultDetail.tsx's isPassingValidationStatus, which
// also accepts "pass").
const VALIDATION_CLEAN_STATUSES = new Set(["passed", "pass", "exact", "full"]);

export interface ValidationStatusInfo {
  /** Normalized (trimmed, lowercased) raw status, or null when absent. */
  status: string | null;
  /** Short, reader-facing label. Always defined, even for an absent status. */
  label: string;
  /** Longer tooltip-length explanation of what the status means. */
  description: string;
  /** Suggested StatusBadge tone. */
  tone: StatusTone;
  /** True only for a clean pass ("passed"). */
  isClean: boolean;
}

/**
 * The ONE shared mapping from a raw validation-status enum value to
 * reader-facing language. Every surface that displays a validation status
 * (compare receipt, result detail chip, platform index Source column,
 * leaderboard validation badge) should call this - or `formatValidationStatus`
 * for just the short label - instead of rendering the raw enum string.
 *
 * The raw status stays available via the `status` field for any surface that
 * wants to show precision (a tooltip, a receipt row, a detail field) alongside
 * the interpretable label.
 */
export function describeValidationStatus(raw: string | null | undefined): ValidationStatusInfo {
  const status = raw === null || raw === undefined ? null : raw.trim().toLowerCase() || null;
  if (status === null) {
    return {
      status: null,
      label: "not recorded",
      description: "No validation status was recorded for this result.",
      tone: "neutral",
      isClean: false,
    };
  }
  const label = VALIDATION_STATUS_LABELS[status] ?? formatEnumLabel(status);
  const description = VALIDATION_STATUS_DESCRIPTIONS[status] ?? "No further detail is defined for this status.";
  const isClean = VALIDATION_CLEAN_STATUSES.has(status);
  let tone: StatusTone;
  if (isClean) {
    tone = "info";
  } else if (status === "loose" || status === "range") {
    // Tolerance-mode passes: validated, but with a wider acceptance band.
    tone = "warning";
  } else if (VALIDATION_CLI_FAILURE_STATUSES.has(status)) {
    tone = "danger";
  } else {
    // Everything else non-clean, including UNVALIDATED_VALIDATION_STATUSES
    // and any unrecognised status: never fall through to the least-alarming
    // ("neutral") tone for a value that is not a clean pass.
    tone = "warning";
  }
  return { status, label, description, tone, isClean };
}

const VISIBILITY_LABELS: Record<string, string> = {
  "public-curated": "Published, maintainer reviewed",
  "public-community": "Published, community submitted",
  internal: "Not public",
};

// Source of truth: benchbox/core/results/provenance.py::FUNDING_SOURCES.
// Mirrored here (rather than generated) because the explorer ships as a static
// bundle with no Python build step; add a label here when that tuple grows.
// Unrecognised values fall through to `formatEnumLabel`.
const FUNDING_LABELS: Record<string, string> = {
  employer: "employer funded",
  personal: "personally funded",
  "free-trial": "free trial",
  "vendor-sponsored": "vendor sponsored",
  grant: "grant funded",
  unspecified: "No funding information provided",
};

const COST_STATUS_LABELS: Record<string, string> = {
  normalized: "normalized",
  not_applicable: "not applicable",
  not_applicable_local: "not applicable (local)",
  unavailable: "unavailable",
};

export function formatTrustLabel(raw: string | null | undefined): string {
  if (raw === null || raw === undefined || raw === "") return "unknown";
  return TRUST_LABEL_LABELS[raw] ?? formatEnumLabel(raw);
}

/**
 * Humanize a funding disclosure. A missing/empty value is treated as
 * `unspecified` rather than "unknown": `funding` is NOT NULL in the snapshot
 * schema and the producer default is literally `unspecified`, so an absent
 * value carries the same meaning as a declared one.
 */
export function formatFunding(raw: string | null | undefined): string {
  if (raw === null || raw === undefined || raw === "") return FUNDING_LABELS.unspecified!;
  return FUNDING_LABELS[raw] ?? formatEnumLabel(raw);
}

export function formatValidationStatus(raw: string | null | undefined): string {
  if (raw === null || raw === undefined || raw === "") return "unknown";
  return describeValidationStatus(raw).label;
}

/**
 * Non-clean validation status: anything that is not the literal "passed"
 * value, including missing/empty status. Mirrors the condition
 * MetaLeaderboard.tsx already uses to decide whether the validation badge
 * needs to surface outside its normal (ranked-cell) placement - kept here so
 * every surface that needs an "is this validation status a problem" check
 * shares one predicate rather than each re-deriving it.
 *
 * This is a placeholder pending the shared status->reader-facing-label
 * mapping being introduced on fix/explorer-compare-validation-disclosure;
 * once that lands, callers of this predicate should reconcile with it.
 */
export function isValidationNotClean(raw: string | null | undefined): boolean {
  return (raw?.trim().toLowerCase() ?? "") !== "passed";
}

export function formatVisibility(raw: string | null | undefined): string {
  if (raw === null || raw === undefined || raw === "") return "unknown";
  return VISIBILITY_LABELS[raw] ?? formatEnumLabel(raw);
}

export function formatCostStatus(raw: string | null | undefined): string {
  if (raw === null || raw === undefined || raw === "") return "unknown";
  return COST_STATUS_LABELS[raw] ?? formatEnumLabel(raw);
}

/**
 * Conservative fallback that turns underscore-and-dash separated tokens into
 * a readable phrase. Intentionally does NOT touch hyphens that are part of
 * technical identifiers (e.g., `result_id`, `cloud_region`); call sites that
 * format those identifiers should not pass them through this helper. The
 * shared rule is: if the raw value is a known enum it gets a curated label,
 * otherwise the default is "lowercase token, separators replaced with
 * spaces".
 */
export function formatEnumLabel(raw: string): string {
  return raw.replace(/[_-]+/g, " ").trim();
}

export function formatArchitecture(raw: string): string {
  const normalized = raw.trim().toLowerCase();
  if (normalized === "x86_64" || normalized === "amd64") return "x86-64";
  if (normalized === "arm64" || normalized === "aarch64") return "Arm64";
  return formatEnumLabel(raw);
}

export function formatCpuFamily(raw: string): string {
  const normalized = raw.trim().toLowerCase();
  if (normalized === "amd_epyc") return "AMD EPYC";
  if (normalized === "intel_xeon") return "Intel Xeon";
  if (normalized === "apple_silicon") return "Apple silicon";
  return formatEnumLabel(raw);
}

export function formatExecutionMode(raw: string): string {
  const normalized = raw.trim().toLowerCase();
  if (normalized === "sql") return "SQL";
  if (normalized === "dataframe") return "DataFrame";
  return formatEnumLabel(raw);
}

export function formatTuningMode(raw: string): string {
  const normalized = raw.trim().toLowerCase();
  const labels: Record<string, string> = {
    notuning: "No tuning",
    tuned: "Tuned",
    "tuned-fallback": "Tuned with fallback settings",
    auto: "Automatic tuning",
    custom: "Custom tuning",
  };
  return labels[normalized] ?? formatEnumLabel(raw);
}

export function formatMemoryGb(value: number): string {
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value)} GB`;
}

/** Stable identity used by cohort/ranking surfaces. Raw slugs remain on rows. */
export function canonicalBenchmarkSlug(raw: string): string {
  const normalized = raw.trim().toLowerCase();
  return normalized === "star_schema" ? "ssb" : normalized;
}

/** Stable phase identity; missing provenance is explicit and never guessed. */
export function canonicalPhase(raw: string | null | undefined): string {
  const normalized = (raw ?? "").trim().toLowerCase();
  return normalized || "unknown";
}

/**
 * Render a benchmark slug for facet/listing contexts. The canonical SSB slug
 * is `ssb`; the historical `star_schema` value remains visibly identifiable
 * when it is encountered in raw evidence or a legacy route.
 */
export function formatBenchmarkLabel(slug: string): string {
  if (slug === "star_schema") return "SSB (historical source)";
  return humanizeBenchmark(slug);
}
