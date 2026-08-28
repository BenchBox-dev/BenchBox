// ---------------------------------------------------------------------------
// TuningBadge - renders tuning_mode as a StatusBadge with role="computed"
// ---------------------------------------------------------------------------

import { NOT_RECORDED_TUNING_MODE } from "@/lib/facetMatching";
import { StatusBadge, type StatusTone } from "./StatusBadge";

interface TuningEntry {
  label: string;
  tone: StatusTone;
  title: string;
}

const NOT_RECORDED_CONFIG: TuningEntry = {
  label: "Not Recorded",
  tone: "neutral",
  title: "Tuning state unknown - the run predates tuning metadata or did not record it",
};

export const TUNING_CONFIG: Record<string, TuningEntry> = {
  tuned: {
    label: "Tuned",
    tone: "success",
    title: "Platform-recommended tuning applied",
  },
  "tuned-fallback": {
    label: "Tuned (Fallback)",
    tone: "warning",
    title:
      "tuned was requested but no platform/benchmark template was found - basic constraints-only " +
      "config was used instead. Does not represent a curated-template tuned run (ADR-2).",
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
  custom: {
    label: "Custom Tuning",
    tone: "warning",
    title: "User-supplied tuning configuration file",
  },
  [NOT_RECORDED_TUNING_MODE]: NOT_RECORDED_CONFIG,
};

const DEFAULT_CONFIG: TuningEntry = {
  label: "Custom Tuning",
  tone: "warning",
  title: "Non-standard tuning configuration",
};

function resolveConfig(tuningMode: string | null | undefined): TuningEntry {
  if (tuningMode === null || tuningMode === undefined) return NOT_RECORDED_CONFIG;
  return TUNING_CONFIG[tuningMode] ?? DEFAULT_CONFIG;
}

export function tuningLabel(tuningMode: string | null | undefined): string {
  return resolveConfig(tuningMode).label;
}

interface TuningBadgeProps {
  tuningMode: string | null | undefined;
}

export function TuningBadge({ tuningMode }: TuningBadgeProps) {
  const config = resolveConfig(tuningMode);
  return (
    <StatusBadge role="computed" tone={config.tone} title={config.title}>
      {config.label}
    </StatusBadge>
  );
}
