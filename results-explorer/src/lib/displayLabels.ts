import { humanizeBenchmark } from "@/utils";

// Public-facing formatters for raw internal enum strings.
//
// Centralized so Query rows, facet chips, exports, result receipts, and
// result detail surfaces all render the same humanized label for the same
// raw value. New enum values added at the data layer should land their
// human label here (or fall through to the conservative `formatEnumLabel`
// default).

const TRUST_LABEL_LABELS: Record<string, string> = {
  "maintainer-run": "maintainer run",
  "community-submission": "community submission",
};

const VALIDATION_STATUS_LABELS: Record<string, string> = {
  passed: "passed",
  failed: "failed",
  warning: "warning",
  not_applicable: "not applicable",
  pending: "pending",
};

const VISIBILITY_LABELS: Record<string, string> = {
  "public-curated": "public (curated)",
  "public-community": "public (community)",
  internal: "internal",
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
  unspecified: "unspecified",
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
  if (raw === null || raw === undefined || raw === "") return "unspecified";
  return FUNDING_LABELS[raw] ?? formatEnumLabel(raw);
}

export function formatValidationStatus(raw: string | null | undefined): string {
  if (raw === null || raw === undefined || raw === "") return "unknown";
  return VALIDATION_STATUS_LABELS[raw] ?? formatEnumLabel(raw);
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
