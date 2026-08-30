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

const CUSTOM_REQUESTED_CONFIG: TuningEntry = {
  label: "Custom Tuning Requested",
  tone: "warning",
  title: "A custom tuning configuration was requested, but applied tuning evidence was not recorded",
};

const CUSTOM_NOOP_CONFIG: TuningEntry = {
  label: "No Tuning Applied",
  tone: "neutral",
  title: "A custom tuning configuration was requested, but execution recorded no applied tuning operations",
};

const CUSTOM_FAILED_CONFIG: TuningEntry = {
  label: "Tuning Failed",
  tone: "danger",
  title: "A custom tuning configuration was requested, but the tuning apply path failed",
};

const APPLIED_TUNING_STATUSES = new Set(["applied_unverified", "applied_verified"]);

function resolveConfig(
  tuningMode: string | null | undefined,
  tuningValidationStatus?: string | null,
): TuningEntry {
  if (tuningMode === null || tuningMode === undefined) return NOT_RECORDED_CONFIG;
  if (tuningMode === "custom") {
    if (APPLIED_TUNING_STATUSES.has(tuningValidationStatus ?? "")) return TUNING_CONFIG.custom!;
    if (tuningValidationStatus === "noop" || tuningValidationStatus === "not_applicable") return CUSTOM_NOOP_CONFIG;
    if (tuningValidationStatus === "failed") return CUSTOM_FAILED_CONFIG;
    return CUSTOM_REQUESTED_CONFIG;
  }
  return TUNING_CONFIG[tuningMode] ?? DEFAULT_CONFIG;
}

export function tuningLabel(tuningMode: string | null | undefined): string {
  if (tuningMode === "custom") return TUNING_CONFIG.custom!.label;
  return resolveConfig(tuningMode).label;
}

interface TuningBadgeProps {
  tuningMode: string | null | undefined;
  tuningValidationStatus?: string | null;
}

export function TuningBadge({ tuningMode, tuningValidationStatus }: TuningBadgeProps) {
  const config = resolveConfig(tuningMode, tuningValidationStatus);
  return (
    <StatusBadge role="computed" tone={config.tone} title={config.title}>
      {config.label}
    </StatusBadge>
  );
}
