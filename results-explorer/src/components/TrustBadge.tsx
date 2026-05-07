// ---------------------------------------------------------------------------
// TrustBadge - renders trust_label as a StatusBadge with role="trust"
//
// Tone semantics:
//   maintainer-run       → success  (verified by project maintainers)
//   community-submission → info     (user-submitted, explicitly disclosed)
//   ci-verified          → neutral  (automated pipeline, no human review)
//   local-run            → neutral  (developer machine, no CI validation)
//   unknown              → neutral  (fallback for unrecognised values)
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
  "local-run": {
    label: "Local",
    tone: "neutral",
    title: "Run on a developer machine - environment may vary",
  },
};

const DEFAULT_CONFIG = {
  label: "Unknown",
  tone: "neutral" as StatusTone,
  title: "Trust level not recorded",
};

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
  if (!trustLabel) return null;
  const known = TRUST_CONFIG[trustLabel];
  const config = known ?? {
    ...DEFAULT_CONFIG,
    label: trustLabel,
    title: `Trust tier: ${trustLabel} (unrecognised - contact maintainers)`,
  };
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
