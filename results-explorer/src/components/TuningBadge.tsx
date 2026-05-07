// ---------------------------------------------------------------------------
// TuningBadge - renders tuning_mode as a StatusBadge with role="computed"
// ---------------------------------------------------------------------------

import { StatusBadge, type StatusTone } from "./StatusBadge";

interface TuningEntry {
  label: string;
  tone: StatusTone;
  title: string;
}

export const TUNING_CONFIG: Record<string, TuningEntry> = {
  tuned: {
    label: "Tuned",
    tone: "success",
    title: "Platform-recommended tuning applied",
  },
  notuning: {
    label: "No Tuning",
    tone: "neutral",
    title: "Platform defaults only - no tuning applied",
  },
  auto: {
    label: "Auto",
    tone: "info",
    title: "Automatic tuning selected by the platform",
  },
};

const DEFAULT_CONFIG: TuningEntry = {
  label: "Custom Tuning",
  tone: "warning",
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
    <StatusBadge role="computed" tone={config.tone} title={config.title}>
      {config.label}
    </StatusBadge>
  );
}
