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

import { describeValidationStatus } from "@/lib/displayLabels";
import { StatusBadge, type StatusTone } from "./StatusBadge";

const TRUST_CONFIG: Record<string, { label: string; tone: StatusTone; title: string }> = {
  "maintainer-run": {
    label: "Maintainer",
    tone: "success",
    title: "A BenchBox maintainer ran and reviewed this result.",
  },
  "community-submission": {
    label: "Community",
    tone: "info",
    title: "A community member submitted this result. Open it to review the source details.",
  },
  "vendor-supplied": {
    label: "Vendor",
    tone: "warning",
    title:
      "The platform vendor produced this result. Compare it with independent results before drawing conclusions.",
  },
  "ci-verified": {
    label: "CI",
    tone: "neutral",
    title: "An automated test run produced this result.",
  },
  "ci-validated": {
    label: "CI",
    tone: "neutral",
    title: "An automated test run produced this result.",
  },
  ci: {
    label: "CI",
    tone: "neutral",
    title: "An automated test run produced this result.",
  },
  "local-run": {
    label: "Local",
    tone: "neutral",
    title: "This result came from a developer machine, so its environment may differ from other runs.",
  },
  local: {
    label: "Local",
    tone: "neutral",
    title: "This result came from a developer machine, so its environment may differ from other runs.",
  },
  "unofficial-research": {
    label: "Unofficial",
    tone: "warning",
    title: "This result used a nonstandard configuration and is not included in rankings.",
  },
};

const DEFAULT_CONFIG = {
  label: "Unknown",
  tone: "neutral" as StatusTone,
  title: "The source of this result was not recorded.",
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
          title: `The source label “${trustLabel}” is not recognized. Contact the BenchBox maintainers for details.`,
        }
      : DEFAULT_CONFIG);
  const text = compact ? (config.label.split(" ")[0] ?? config.label) : config.label;
  return (
    <StatusBadge role="trust" tone={config.tone} title={config.title}>
      {text}
    </StatusBadge>
  );
}

// Renders the shared validation-status vocabulary (see
// `describeValidationStatus` in src/lib/displayLabels.ts) as a badge. The
// visible text is the reader-facing label, never the raw enum value (e.g.
// "no validation", not "not_run") - the raw status is still available via the
// title tooltip for anyone who wants precision.
export function ValidationBadge({ validationStatus, showMissing = false }: ValidationBadgeProps) {
  if (!validationStatus && !showMissing) return null;
  if (!validationStatus) {
    return (
      <StatusBadge role="validation" tone="neutral" title="No validation status was recorded for this result.">
        Not recorded
      </StatusBadge>
    );
  }
  const info = describeValidationStatus(validationStatus);
  return (
    <StatusBadge role="validation" tone={info.tone} title={`${info.description} Recorded status: ${info.status}.`}>
      {info.label}
    </StatusBadge>
  );
}


export default TrustBadge;
