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
  label: "Not recorded",
  tone: "neutral",
  title: "This run did not record whether it used tuning settings.",
};

export const TUNING_CONFIG: Record<string, TuningEntry> = {
  tuned: {
    label: "Tuned",
    tone: "success",
    title: "This run applied the recommended tuning settings for the platform.",
  },
  "tuned-fallback": {
    label: "Tuned with fallback settings",
    tone: "warning",
    title:
      "Tuning was requested, but BenchBox found no recommended settings for this platform and benchmark. It used basic settings instead.",
  },
  notuning: {
    label: "No tuning",
    tone: "neutral",
    title: "This run used the platform defaults and applied no tuning settings.",
  },
  auto: {
    label: "Automatic tuning",
    tone: "info",
    title: "The platform selected the tuning settings automatically.",
  },
  custom: {
    label: "Custom tuning",
    tone: "warning",
    title: "This run used tuning settings supplied by the person who ran it.",
  },
  [NOT_RECORDED_TUNING_MODE]: NOT_RECORDED_CONFIG,
};

const DEFAULT_CONFIG: TuningEntry = {
  label: "Custom tuning",
  tone: "warning",
  title: "This run used tuning settings that BenchBox does not recognize.",
};

const CUSTOM_REQUESTED_CONFIG: TuningEntry = {
  label: "Custom tuning requested",
  tone: "warning",
  title: "Custom tuning was requested, but the run did not record whether it was applied.",
};

const CUSTOM_NOOP_CONFIG: TuningEntry = {
  label: "No tuning applied",
  tone: "neutral",
  title: "Custom tuning was requested, but the run recorded no applied tuning settings.",
};

const CUSTOM_FAILED_CONFIG: TuningEntry = {
  label: "Tuning failed",
  tone: "danger",
  title: "Custom tuning was requested, but BenchBox could not apply it.",
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
