// ---------------------------------------------------------------------------
// TuningBadge - renders tuning_mode as a styled badge
// ---------------------------------------------------------------------------

export const TUNING_CONFIG: Record<string, { label: string; class: string; title: string }> = {
  tuned: {
    label: "Tuned",
    class: "badge-green",
    title: "Platform-recommended tuning applied",
  },
  notuning: {
    label: "No Tuning",
    class: "badge-gray",
    title: "Platform defaults only - no tuning applied",
  },
  auto: {
    label: "Auto",
    class: "badge-blue",
    title: "Automatic tuning selected by the platform",
  },
};

const DEFAULT_CONFIG = {
  label: "Custom Tuning",
  class: "badge-yellow",
  title: "Non-standard tuning configuration",
};

export function tuningLabel(tuningMode: string): string {
  return (TUNING_CONFIG[tuningMode] ?? DEFAULT_CONFIG).label;
}

interface TuningBadgeProps {
  tuningMode: string;
}

export function TuningBadge({ tuningMode }: TuningBadgeProps) {
  const config = TUNING_CONFIG[tuningMode] ?? DEFAULT_CONFIG;
  return (
    <span class={`badge ${config.class}`} title={config.title}>
      {config.label}
    </span>
  );
}
