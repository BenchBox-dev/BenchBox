// ---------------------------------------------------------------------------
// TrustBadge - renders trust_label as a StatusBadge with role="trust"
//
// Tone semantics:
//   maintainer-run       → success  (verified by project maintainers)
//   community-submission → info     (user-submitted, explicitly disclosed)
//   vendor-supplied      → warning  (vendor-produced; ranked but conflict of interest)
//   ci / ci-verified     → neutral  (automated pipeline, no human review)
//   local / local-run    → neutral  (developer machine, no CI validation)
//   unofficial-research  → warning  (non-standard config, not comparable)
//   unknown / empty      → neutral  (fallback for unrecognised / missing values)
//
// The keys below cover BOTH the explorer pipeline's trust labels
// (ci-verified, local-run) AND the publisher vocabulary in
// benchbox/core/publishing/bundle_publisher.py:VALID_LABELS
// (ci, local, unofficial-research), so a valid label never falls through to the
// "unrecognised" fallback. Keep the two in sync.
//
// Tones meet WCAG AA contrast (light background + dark text in each tier).
// Do NOT de-emphasise community results - show them prominently with their
// own color rather than a "cautionary" yellow.
// ---------------------------------------------------------------------------

import { StatusBadge, type StatusTone } from "./StatusBadge";

const TRUST_CONFIG: Record<string, { label: string; tone: StatusTone; title: string }> = {
  "maintainer-run": {
    label: "Maintainer",
    tone: "success",
    title: "Run by a BenchBox project maintainer under controlled conditions",
  },
  "community-submission": {
    label: "Community",
    tone: "info",
    title: "Submitted by a community member - see result detail for provenance",
  },
  "vendor-supplied": {
    label: "Vendor",
    tone: "warning",
    title:
      "Produced by the platform vendor - ranked, but the vendor has a direct interest in the outcome; verify against independent results",
  },
  "ci-verified": {
    label: "CI",
    tone: "neutral",
    title: "Validated by automated CI pipeline",
  },
  "ci-validated": {
    label: "CI",
    tone: "neutral",
    title: "Validated by automated CI pipeline",
  },
  ci: {
    label: "CI",
    tone: "neutral",
    title: "Validated by automated CI pipeline",
  },
  "local-run": {
    label: "Local",
    tone: "neutral",
    title: "Run on a developer machine - environment may vary",
  },
  local: {
    label: "Local",
    tone: "neutral",
    title: "Run on a developer machine - environment may vary",
  },
  "unofficial-research": {
    label: "Unofficial",
    tone: "warning",
    title: "Unofficial / non-standard configuration - not comparable and excluded from official rankings",
  },
};

const DEFAULT_CONFIG = {
  label: "Unknown",
  tone: "neutral" as StatusTone,
  title: "Trust level not recorded",
};

/** Tooltip/legend prose for a trust label. Single source for both surfaces. */
export function trustLabelDescription(trustLabel: string): string {
  return TRUST_CONFIG[trustLabel]?.title ?? DEFAULT_CONFIG.title;
}

interface TrustBadgeProps {
  trustLabel: string;
  /** When true, show only the first word of the label. */
  compact?: boolean;
}

interface ValidationBadgeProps {
  validationStatus?: string | null;
  showMissing?: boolean;
}

export function TrustBadge({ trustLabel, compact = false }: TrustBadgeProps) {
  // Render an explicit "Unknown" badge for a missing label rather than hiding
  // the trust dimension entirely: a silently-absent badge reads as "no opinion"
  // instead of "provenance not recorded". (trust_label is NOT NULL in the
  // snapshot schema today, so this is a defensive contract, not a hot path.)
  const known = trustLabel ? TRUST_CONFIG[trustLabel] : undefined;
  const config =
    known ??
    (trustLabel
      ? {
          ...DEFAULT_CONFIG,
          label: trustLabel,
          title: `Trust tier: ${trustLabel} (unrecognised - contact maintainers)`,
        }
      : DEFAULT_CONFIG);
  const text = compact ? (config.label.split(" ")[0] ?? config.label) : config.label;
  return (
    <StatusBadge role="trust" tone={config.tone} title={config.title}>
      {text}
    </StatusBadge>
  );
}

export function ValidationBadge({ validationStatus, showMissing = false }: ValidationBadgeProps) {
  if (!validationStatus && !showMissing) return null;
  const status = validationStatus?.trim() || "not recorded";
  const lower = status.toLowerCase();
  const tone = validationTone(lower);
  const label = validationStatus ? lower : "validation n/a";
  return (
    <StatusBadge role="validation" tone={tone} title={`Validation status: ${status}`}>
      {label}
    </StatusBadge>
  );
}

function validationTone(status: string): StatusTone {
  if (status.includes("fail")) return "danger";
  if (status.includes("disabled") || status.includes("partial")) return "warning";
  if (status === "exact" || status === "full" || status === "passed" || status === "pass") {
    return "info";
  }
  if (status === "loose" || status === "range") return "warning";
  return "neutral";
}

export default TrustBadge;
