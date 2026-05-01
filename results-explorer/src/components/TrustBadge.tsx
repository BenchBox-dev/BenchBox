// ---------------------------------------------------------------------------
// TrustBadge - renders trust_label as a styled pill badge
//
// Color semantics:
//   maintainer-run     → green  (verified by project maintainers)
//   community-submission → blue (user-submitted, explicitly disclosed)
//   ci-verified        → gray   (automated pipeline, no human review)
//   local-run          → gray   (developer machine, no CI validation)
//   unknown            → gray   (fallback for unrecognised values)
//
// Colors meet WCAG AA contrast (light background + dark text in each tier).
// Do NOT de-emphasise community results - show them prominently with their
// own color rather than a "cautionary" yellow.
// ---------------------------------------------------------------------------

const TRUST_CONFIG: Record<string, { label: string; badgeClass: string; title: string }> = {
  "maintainer-run": {
    label: "Maintainer",
    badgeClass: "badge-green",
    title: "Run by a BenchBox project maintainer under controlled conditions",
  },
  "community-submission": {
    label: "Community",
    badgeClass: "badge-blue",
    title: "Submitted by a community member - see result detail for provenance",
  },
  "ci-verified": {
    label: "CI",
    badgeClass: "badge-gray",
    title: "Validated by automated CI pipeline",
  },
  "ci-validated": {
    label: "CI",
    badgeClass: "badge-gray",
    title: "Validated by automated CI pipeline",
  },
  "local-run": {
    label: "Local",
    badgeClass: "badge-gray",
    title: "Run on a developer machine - environment may vary",
  },
};

const DEFAULT_CONFIG = {
  label: "Unknown",
  badgeClass: "badge-gray",
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
    <span class={`badge ${config.badgeClass}`} title={config.title}>
      {text}
    </span>
  );
}

export function ValidationBadge({ validationStatus, showMissing = false }: ValidationBadgeProps) {
  if (!validationStatus && !showMissing) return null;
  const status = validationStatus?.trim() || "not recorded";
  const lower = status.toLowerCase();
  const badgeClass = validationBadgeClass(lower);
  const label = validationStatus ? lower : "validation n/a";
  return (
    <span class={`badge ${badgeClass}`} title={`Validation status: ${status}`}>
      {label}
    </span>
  );
}

function validationBadgeClass(status: string) {
  if (status.includes("fail")) return "badge-red";
  if (status.includes("disabled") || status.includes("partial")) return "badge-yellow";
  if (status === "exact" || status === "full" || status === "passed" || status === "pass") {
    return "badge-green";
  }
  if (status === "loose" || status === "range") return "badge-yellow";
  return "badge-gray";
}

export default TrustBadge;
