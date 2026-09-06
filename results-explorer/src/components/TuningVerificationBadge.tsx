// ---------------------------------------------------------------------------
// TuningVerificationBadge - renders the ADR-1 tuning verified-state
// (tuning_validation_status) as a StatusBadge. applied_verified is the only
// state earned via the post-load introspection receipt's corroboration; the
// rest are the honest execution-derived applied-ledger statuses.
// ---------------------------------------------------------------------------

import { StatusBadge, type StatusTone } from "./StatusBadge";

interface VerificationEntry {
  label: string;
  tone: StatusTone;
  title: string;
}

const UNKNOWN_CONFIG: VerificationEntry = {
  label: "Not recorded",
  tone: "neutral",
  title: "This run did not record whether the applied tuning settings were checked.",
};

export const TUNING_VERIFICATION_CONFIG: Record<string, VerificationEntry> = {
  applied_verified: {
    label: "Verified",
    tone: "success",
    title: "BenchBox checked the live database after loading the data and confirmed the applied tuning settings.",
  },
  applied_unverified: {
    label: "Applied, not independently checked",
    tone: "info",
    title: "The run recorded at least one applied tuning setting, but BenchBox did not check the live database afterward.",
  },
  noop: {
    label: "Nothing applied",
    tone: "neutral",
    title: "Tuning was requested, but the run applied no tuning settings.",
  },
  not_applicable: {
    label: "Not applicable",
    tone: "neutral",
    title: "Tuning was disabled or no tuning settings applied to this run.",
  },
  failed: {
    label: "Failed",
    tone: "danger",
    title: "BenchBox tried to apply tuning settings, but every attempt failed.",
  },
};

function resolveConfig(status: string | null | undefined): VerificationEntry {
  if (status === null || status === undefined || status === "") return UNKNOWN_CONFIG;
  return TUNING_VERIFICATION_CONFIG[status] ?? UNKNOWN_CONFIG;
}

export function tuningVerificationLabel(status: string | null | undefined): string {
  return resolveConfig(status).label;
}

interface TuningVerificationBadgeProps {
  status: string | null | undefined;
}

export function TuningVerificationBadge({ status }: TuningVerificationBadgeProps) {
  const config = resolveConfig(status);
  return (
    <StatusBadge role="computed" tone={config.tone} title={config.title}>
      {config.label}
    </StatusBadge>
  );
}
